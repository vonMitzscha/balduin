"""D2 Formaterkennung: von gleichen Inhalten übernehmen, sonst Siegfried in zwei Stufen."""
from .basis import *  # noqa: F401,F403
from . import archivdateien
from .platte import angeschlossene_platte_pruefen

# D2a Funktionen: Formate übernehmen oder mit Siegfried bestimmen
def formate_uebernehmen(platte_id):
    """Übernimmt das Format von einer schon bestimmten Datei mit gleichem SHA-256 und gleicher Endung
    (auch von anderen Platten). Braucht keine angeschlossene Platte."""
    with db() as con:
        offen = pd.read_sql("SELECT relpfad, sha256 FROM datei WHERE platte_id = ? AND sf_am IS NULL "
                            "AND sha256 IS NOT NULL", con, params=(platte_id,))
        # Vorlagen mit Siegfried-Fehler (z. B. Lesefehler) nicht weitergeben
        fertig = pd.read_sql("""SELECT platte_id, relpfad, sha256, sf_quelle IS NULL AS direkt FROM datei
                                WHERE sf_am IS NOT NULL AND COALESCE(sf_fehler, '') = '' AND sha256 IN
                                      (SELECT sha256 FROM datei WHERE platte_id = ? AND sf_am IS NULL)""",
                             con, params=(platte_id,))
        vorlagen = vorlagen_waehlen(offen, fertig)
        con.executemany("""
            UPDATE datei SET (puid, format, formatversion, mime, sf_basis, sf_warnung, sf_fehler, sf_quelle) =
                (SELECT puid, format, formatversion, mime, sf_basis, sf_warnung, sf_fehler,
                        COALESCE(sf_quelle, platte_id || ':' || relpfad)
                 FROM datei q WHERE q.platte_id = ? AND q.relpfad = ?), sf_am = ?
            WHERE platte_id = ? AND relpfad = ?""",
            [(vp, vr, jetzt(), platte_id, r) for r, vp, vr in vorlagen.itertuples(index=False)])
    if len(vorlagen):
        herkunft = ", ".join(f"{p} {n}" for p, n in vorlagen.vorlage_platte.value_counts().sort_index().items())
        protokolliere("D2", platte_id, "format_uebernommen", "", f"{len(vorlagen)} Dateien (Vorlagen: {herkunft})")
        print(f"Format von gleichen Inhalten übernommen: {len(vorlagen):,} Dateien (Vorlagen: {herkunft}).")


SF_FENSTER = 65536    # Bytes, die Stufe 1 am Anfang und am Ende jeder Datei durchsucht


def sf_version(*optionen):
    """Version von Programm und Signatursatz, z. B. „siegfried 1.11.6, DROID_SignatureFile_V124, …, max BOF 65536“."""
    text = subprocess.run([system.werkzeug("sf"), "-version", *optionen], capture_output=True, text=True).stdout
    return ", ".join(re.findall(r"siegfried [\d.]+|DROID_SignatureFile_V\d+|container-signature-\d+|max [BE]OF \d+",
                                text))


def signatursatz_begrenzt():
    """Baut mit roy einen Signatursatz, der nur die ersten und letzten SF_FENSTER Bytes jeder Datei durchsucht.
    Grundlage sind die mit Siegfried installierten PRONOM-Dateien (kein Download); roy findet sie über Verknüpfungen
    in siegfried/ im Projekt. Gebaut wird einmal je Siegfried-Version. Ergebnis: Optionen für sf."""
    text = subprocess.run([system.werkzeug("sf"), "-version"], capture_output=True, text=True).stdout
    heim_sf = Path(re.search(r"^(\S.*)[/\\]default\.sig", text, re.M).group(1))
    name = f"begrenzt_{re.search(r'siegfried ([\d.]+)', text).group(1)}_{SF_FENSTER // 1024}k.sig"
    if not (P.siegfried / name).exists():
        if not system.werkzeug_pfad("roy"):
            raise RuntimeError("roy fehlt; es gehört zu Siegfried. " + system.installationshinweis("sf"))
        P.siegfried.mkdir(parents=True, exist_ok=True)
        for alt in P.siegfried.iterdir():           # Verknüpfungen (Windows: Kopien) einer älteren Version ersetzen
            if alt.is_symlink() or alt.suffix == ".xml":
                alt.unlink()
            elif alt.name == "pronom":
                shutil.rmtree(alt)
        for quelle in [*heim_sf.glob("*.xml"), heim_sf / "pronom"]:
            system.verknuepfen(quelle, P.siegfried / quelle.name)
        ergebnis = subprocess.run([system.werkzeug("roy"), "build", "-bof", str(SF_FENSTER), "-eof", str(SF_FENSTER),
                                   "-home", str(P.siegfried), name], capture_output=True, text=True)
        if ergebnis.returncode != 0 or not (P.siegfried / name).exists():
            raise RuntimeError("roy konnte den Signatursatz nicht bauen:\n" + ergebnis.stderr[-1000:])
        print(f"Signatursatz {name} gebaut (Anfang und Ende je {SF_FENSTER // 1024} KB).")
    return ["-home", str(P.siegfried), "-sig", name]


def sf_ergebnisse(pfad, relpfade, optionen, parallel, log, stufe):
    """Lässt Siegfried die Dateien prüfen (optionen wählen den Signatursatz) und liefert je Datei
    (relpfad, Zeile aus der CSV von Siegfried). Mit contextlib.closing aufrufen, dann endet sf auch beim Unterbrechen.
    pfad: archivdateien.Pfade (Pfad im Dateisystem je relpfad, auch für Dateien in Archivdateien, und zurück)."""
    with tempfile.NamedTemporaryFile("w", suffix=".txt", encoding="utf-8", delete=False) as liste:
        liste.write("".join(os.path.abspath(pfad(r)) + "\n" for r in relpfade))
    start = time.monotonic()
    prozess = subprocess.Popen([system.werkzeug("sf"), *optionen, "-csv", "-coe", "-multi", str(parallel), "-f", liste.name],
                               stdout=subprocess.PIPE, stderr=log, text=True, encoding="utf-8", errors="replace")
    try:
        for anzahl, z in enumerate(csv.DictReader(prozess.stdout), 1):
            yield pfad.relpfad(z["filename"]), z
            minuten = (time.monotonic() - start) / 60
            rest = minuten / anzahl * max(len(relpfade) - anzahl, 0)
            fortschritt(anzahl / len(relpfade),
                        f"{stufe}: {anzahl:,}/{len(relpfade):,} Dateien · {restzeit(rest)}")
    finally:
        if prozess.poll() is None:
            prozess.terminate()
        prozess.wait()
        os.unlink(liste.name)


STAPEL_DATEIEN, STAPEL_GB = 2000, 4      # Abbilder: so viele Dateien bzw. GB liegen höchstens zugleich in entpackt/


def stapeln(platte_id, wurzel, relpfade):
    """Teile der Liste für Siegfried: alles auf einmal, bei einem Abbild Stapel (STAPEL_DATEIEN, STAPEL_GB)."""
    from . import quelle
    if not quelle.ist_abbild(wurzel):
        yield relpfade
        return
    with db() as con:
        groesse = dict(con.execute("SELECT relpfad, groesse FROM schnellscan WHERE platte_id = ?", (platte_id,)))
    teil, summe = [], 0
    for r in relpfade:
        if teil and (len(teil) >= STAPEL_DATEIEN or summe + (groesse.get(r) or 0) > STAPEL_GB * 1e9):
            yield teil
            teil, summe = [], 0
        teil.append(r)
        summe += groesse.get(r) or 0
    if teil:
        yield teil


def siegfried(platte_id, wurzel, parallel=1):
    """Bestimmt für alle Dateien ohne Format das PRONOM-Format mit Siegfried, in zwei Stufen:
    1. begrenzter Signatursatz, liest nur die ersten und letzten 64 KB jeder Datei (schnell, auch bei großen Videos);
    2. Standardsatz, liest notfalls die ganze Datei, nur für Dateien, die in Stufe 1 UNKNOWN bleiben oder eine Warnung haben.
    Gespeichert wird je Datei nur das endgültige Ergebnis; nach einer Unterbrechung macht der nächste Lauf mit dem Rest weiter.
    parallel: Anzahl der Siegfried-Abläufe; bei einer drehenden Platte 1, sonst springt der Lesekopf hin und her."""
    with db() as con:
        offen = [r for (r,) in con.execute("SELECT relpfad FROM datei WHERE platte_id = ? AND sf_am IS NULL "
                                           "ORDER BY relpfad", (platte_id,))]
    # Siegfried bekommt die Dateien als Liste, eine je Zeile; Namen mit Zeilenumbruch oder Wagenrücklauf
    # (z. B. „Icon\r“, die Ordnersymbole von macOS) gehen darin nicht
    umbruch = [r for r in offen if "\n" in r or "\r" in r]
    offen = [r for r in offen if r not in umbruch]
    if umbruch:
        print(f"{len(umbruch):,} Dateien mit Zeilenumbruch im Namen (z. B. Ordnersymbole „Icon“) bleiben ohne Format.")
    if not offen:
        print(f"Für {platte_id} sind alle Formate bestimmt.")
        return
    if not system.werkzeug_pfad("sf"):
        raise RuntimeError("Siegfried fehlt. " + system.installationshinweis("sf"))
    angeschlossene_platte_pruefen(platte_id, wurzel)
    begrenzt = signatursatz_begrenzt()
    version = f"Stufe 1: {sf_version(*begrenzt)}; Stufe 2: {sf_version()}"
    with db() as con:
        lauf_id = con.execute("INSERT INTO scanlauf (platte_id, art, start) VALUES (?,?,?)",
                              (platte_id, "siegfried", jetzt())).lastrowid
    logdatei = P.logs / f"siegfried_{platte_id}_{datetime.now():%Y-%m-%d_%H%M}.log"

    sql = ("UPDATE datei SET puid = ?, format = ?, formatversion = ?, mime = ?, sf_basis = ?, "
           "sf_warnung = ?, sf_fehler = ?, sf_am = ?, sf_quelle = NULL WHERE platte_id = ? AND relpfad = ?")
    werte = lambda relpfad, z: (z["id"], z["format"], z["version"], z["mime"], z["basis"],
                                z["warning"], z["errors"], jetzt(), platte_id, relpfad)
    stufe1 = stufe2 = 0
    unterbrochen = False
    with open(logdatei, "w", encoding="utf-8") as log, db() as con:
        try:
            print(f"{len(offen):,} Dateien ohne Format. Stufe 1: Anfang und Ende jeder Datei …")
            # aus einem Abbild kommt jede Datei kurz nach entpackt/: in Stapeln, damit nie die ganze Platte dort liegt
            for teil in stapeln(platte_id, wurzel, offen):
                nachpruefen = []
                with archivdateien.bereitstellen(platte_id, wurzel, teil) as pfad:
                    with closing(sf_ergebnisse(pfad, teil, begrenzt, parallel, log, "Stufe 1")) as ergebnisse:
                        for anzahl, (relpfad, z) in enumerate(ergebnisse, 1):
                            if z["id"] == "UNKNOWN" or z["warning"]:
                                nachpruefen.append(relpfad)
                            else:
                                stufe1 += con.execute(sql, werte(relpfad, z)).rowcount
                            if anzahl % 200 == 0:
                                con.commit()
                    con.commit()
                    if nachpruefen:
                        print(f"\nStufe 2: {len(nachpruefen):,} Dateien ohne sichere Erkennung, ganze Datei …")
                        with closing(sf_ergebnisse(pfad, nachpruefen, [], parallel, log, "Stufe 2")) as ergebnisse:
                            for relpfad, z in ergebnisse:
                                stufe2 += con.execute(sql, werte(relpfad, z)).rowcount
                                con.commit()
        except KeyboardInterrupt:
            unterbrochen = True
        con.execute("UPDATE scanlauf SET ende = ?, dateien = ? WHERE lauf_id = ?",
                    (jetzt(), stufe1 + stufe2, lauf_id))
    protokolliere("D2", platte_id, "siegfried", "",
                  f"{stufe1 + stufe2} Dateien (Stufe 1, Anfang/Ende: {stufe1}; Stufe 2, ganze Datei: {stufe2}); "
                  f"{version}" + (", unterbrochen" if unterbrochen else ""))
    print(f"\n{'Unterbrochen' if unterbrochen else 'Fertig'}: {stufe1 + stufe2:,} Dateien bestimmt, "
          f"davon {stufe1:,} an Anfang und Ende, {stufe2:,} aus der ganzen Datei.\n{version}")
    if not unterbrochen and stufe1 + stufe2 < len(offen):
        print(f"ACHTUNG: {len(offen) - stufe1 - stufe2:,} von {len(offen):,} Dateien ohne Format, "
              "Meldungen im Log prüfen.")
    print("Meldungen von Siegfried:", logdatei.relative_to(P.ordner))

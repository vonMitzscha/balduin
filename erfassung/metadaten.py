"""E Eingebettete Metadaten mit ExifTool (übernehmen oder lesen) und bestes Datum je Datei.

E1 liest alle Felder (`-all`): eine Auswahl geht in die Tabelle `metadaten`, die ganze Ausgabe komprimiert in
`exif_voll` je Inhalt und Endung, weil die Platten nach der Analyse nicht mehr zur Verfügung stehen
(Entscheidung 03.11.2026)."""
import zlib

from .basis import *  # noqa: F401,F403
from . import archivdateien
from .platte import angeschlossene_platte_pruefen

# E1a Funktionen: Metadaten mit ExifTool lesen
# Spalte in der Tabelle metadaten: ExifTool-Felder (Gruppe:Feld), das erste vorhandene gilt
FELDER = {
    "dateityp": ["File:FileType"],
    "aufnahme": ["EXIF:DateTimeOriginal", "XMP:DateTimeOriginal"],
    "erstellt": ["EXIF:CreateDate", "XMP:CreateDate", "PDF:CreateDate", "QuickTime:CreateDate", "FlashPix:CreateDate",
                 "RTF:CreateDate", "PostScript:CreateDate"],
    "datum_xmp": ["XMP:DateCreated", "IPTC:DateCreated"],
    "hersteller": ["EXIF:Make", "XMP:Make"],
    "kamera": ["EXIF:Model", "XMP:Model"],
    "seriennummer": ["EXIF:SerialNumber", "MakerNotes:SerialNumber", "MakerNotes:InternalSerialNumber", "XMP:SerialNumber"],
    "breite": ["File:ImageWidth", "EXIF:ImageWidth", "PNG:ImageWidth", "EXIF:ExifImageWidth", "Composite:ImageWidth"],
    "hoehe": ["File:ImageHeight", "EXIF:ImageHeight", "PNG:ImageHeight", "EXIF:ExifImageHeight", "Composite:ImageHeight"],
    "bittiefe": ["File:BitsPerSample", "EXIF:BitsPerSample", "PNG:BitDepth", "Photoshop:BitDepth"],
    "farbraum": ["Photoshop:ColorMode", "EXIF:PhotometricInterpretation", "File:ColorComponents", "PNG:ColorType",
                 "EXIF:ColorSpace"],
    "farbprofil": ["ICC_Profile:ProfileDescription"],
    "ausrichtung": ["EXIF:Orientation"],
    "gps_breite": ["Composite:GPSLatitude"],
    "gps_laenge": ["Composite:GPSLongitude"],
    "urheber": ["EXIF:Artist", "XMP:Creator", "IPTC:By-line", "PDF:Author", "FlashPix:Author", "XMP:Author",
                "RTF:Author", "HTML:Author", "PostScript:For"],
    "copyright": ["EXIF:Copyright", "XMP:Rights", "IPTC:CopyrightNotice"],
    "titel": ["XMP:Title", "IPTC:ObjectName", "XMP:Headline", "IPTC:Headline", "PDF:Title", "FlashPix:Title",
              "RTF:Title", "HTML:Title", "PostScript:Title"],
    "beschreibung": ["XMP:Description", "IPTC:Caption-Abstract", "EXIF:ImageDescription", "PDF:Subject", "FlashPix:Subject",
                     "FlashPix:Comments", "RTF:Subject", "RTF:Comments", "HTML:Description"],
    # bei Word ab 2007 ist XMP:Subject das „Thema“, die Stichwörter stehen in XML:Keywords; daher XML zuerst
    "schlagworte": ["IPTC:Keywords", "XML:Keywords", "XMP:Subject", "PDF:Keywords", "FlashPix:Keywords", "RTF:Keywords",
                    "HTML:Keywords"],
    "software": ["EXIF:Software", "XMP:CreatorTool", "PDF:Creator", "PDF:Producer", "FlashPix:Software",
                 "XML:Application", "PostScript:Creator"],
    "seiten": ["PDF:PageCount", "XMP:NPages", "FlashPix:Pages", "XML:Pages"],
    "dauer": ["Composite:Duration", "QuickTime:Duration", "RIFF:Duration", "ASF:Duration"],
    "warnung": ["ExifTool:Warning"],
    "fehler": ["ExifTool:Error"],
}
ZAHLEN = {"breite", "hoehe", "ausrichtung", "seiten", "gps_breite", "gps_laenge", "dauer"}   # Spalten mit Zahlen
ALS_ZAHL = {"Orientation", "GPSLatitude", "GPSLongitude", "Duration"}   # mit # = Zahl statt Text (z. B. 6 statt „Rotate 90 CW“)
# alle Felder; die Felder mit # müssen vor -all stehen, sonst gibt ExifTool sie als Text aus (getestet mit 13.55)
EXIF_ARGUMENTE = ["-json", "-G0", "-fast", "-api", "largefilesupport=1"] + [f"-{n}#" for n in sorted(ALS_ZAHL)] + ["-all"]
# hängen am Fundort, nicht am Inhalt (stehen im Schnellscan); fehlen deshalb in exif_voll
PFADANGABEN = {"SourceFile", "File:FileName", "File:Directory", "File:FileModifyDate", "File:FileAccessDate",
               "File:FileInodeChangeDate", "File:FilePermissions", "File:FileCreateDate", "File:FileAttributes",
               "ExifTool:ExifToolVersion"}
MAX_WERT, MAX_LISTE = 4000, 200      # lange XMP-Verläufe u. Ä. kürzen, damit die Datenbank schmal bleibt


def endung(relpfad):
    """Endung wie bei der Übernahme gleicher Inhalte (basis.vorlagen_waehlen)."""
    return os.path.splitext(relpfad)[1].lower()


def kuerzen_wert(wert):
    if isinstance(wert, str) and len(wert) > MAX_WERT:
        return wert[:MAX_WERT] + " …[gekürzt]"
    if isinstance(wert, list):
        return [kuerzen_wert(w) for w in wert[:MAX_LISTE]] + (["…[gekürzt]"] if len(wert) > MAX_LISTE else [])
    if isinstance(wert, dict):
        return {k: kuerzen_wert(v) for k, v in wert.items()}
    return wert


def vollabbild(eintrag):
    """Die ganze ExifTool-Ausgabe einer Datei ohne Fundortangaben, als komprimiertes JSON; dazu die Zahl der Felder."""
    daten = {k: kuerzen_wert(v) for k, v in eintrag.items() if k not in PFADANGABEN}
    return zlib.compress(json.dumps(daten, ensure_ascii=False, sort_keys=True).encode("utf-8"), 6), len(daten)


def exif_voll_holen(sha256, end):
    """Gespeicherte vollständige ExifTool-Ausgabe eines Inhalts (für Vorlauf und Erschließung); None, wenn keine."""
    with db() as con:
        z = con.execute("SELECT daten FROM exif_voll WHERE sha256 = ? AND endung = ?", (sha256, end)).fetchone()
    return json.loads(zlib.decompress(z[0])) if z and z[0] else None


def exiftool_version():
    try:
        return subprocess.run([system.werkzeug("exiftool"), "-ver"], capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def datum_iso(wert):
    """ExifTool-Datum „2003:05:12 14:22:01“ → „2003-05-12 14:22:01“; Unsinn wie „0000:00:00“ → None.
    Ältere EPS-Dateien schreiben das Datum deutsch („12.05.2003 14:22“); das wird umgestellt."""
    wert = re.sub(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})", lambda t: f"{t[3]}:{int(t[2]):02d}:{int(t[1]):02d}", str(wert or ""))
    m = re.match(r"(\d{4})[:\-](\d{2})[:\-](\d{2})(?:[ T](\d{2}):(\d{2}):(\d{2}))?", wert)
    if not m or not 1900 <= int(m[1]) <= datetime.now().year or not 1 <= int(m[2]) <= 12 or not 1 <= int(m[3]) <= 31:
        return None
    return f"{m[1]}-{m[2]}-{m[3]}" + (f" {m[4]}:{m[5]}:{m[6]}" if m[4] else "")


def auswahl(eintrag):
    """Macht aus der ExifTool-Ausgabe einer Datei eine Zeile für die Tabelle metadaten."""
    zeile = {}
    for spalte, felder in FELDER.items():
        wert = next((eintrag[f] for f in felder if eintrag.get(f) not in (None, "", [])), None)
        if isinstance(wert, list):
            wert = "; ".join(str(w) for w in wert)
        if wert is not None and spalte not in ZAHLEN:
            wert = str(wert).strip() or None
        zeile[spalte] = wert
    for spalte in ("aufnahme", "erstellt", "datum_xmp"):
        zeile[spalte] = datum_iso(zeile[spalte])
    for spalte in ("breite", "hoehe", "ausrichtung", "seiten"):
        zeile[spalte] = int(zeile[spalte]) if str(zeile[spalte] or "").isdigit() else None
    return zeile


EXIF_NICHT_GELESEN = "von ExifTool nicht gelesen (siehe Log)"


def metadaten_offen(con, platte_id, nur_tabelle=False):
    """Dateien einer Platte, für die noch keine Metadaten vorliegen (oder die seit dem Lesen neu gehasht wurden) oder
    deren Inhalt (SHA-256 + Endung) noch keine vollständige ExifTool-Ausgabe in exif_voll hat.
    nur_tabelle: nur die fehlenden Zeilen in `metadaten` (für die Übernahme von gleichem Inhalt)."""
    offen = pd.read_sql("""
        SELECT d.relpfad, d.sha256, m.relpfad IS NULL OR m.gelesen_am < d.gehasht_am AS ohne_zeile
        FROM datei d LEFT JOIN metadaten m ON m.platte_id = d.platte_id AND m.relpfad = d.relpfad
        WHERE d.platte_id = ? AND d.groesse > 0
          AND NOT EXISTS (SELECT 1 FROM virenscan v WHERE v.sha256 = d.sha256 AND v.befund = 'Fund')
        ORDER BY d.relpfad""", con, params=(platte_id,))
    offen = offen[~offen.relpfad.map(ist_systemdatei) & ~offen.relpfad.str.contains("\n", regex=False)]
    if nur_tabelle:
        return offen[offen.ohne_zeile == 1][["relpfad", "sha256"]]
    voll = set(con.execute("SELECT sha256, endung FROM exif_voll").fetchall())
    ohne_voll = [s is not None and (s, endung(r)) not in voll for r, s in zip(offen.relpfad, offen.sha256)]
    return offen[(offen.ohne_zeile == 1) | pd.Series(ohne_voll, index=offen.index)][["relpfad", "sha256"]]


def metadaten_uebernehmen(platte_id):
    """Übernimmt die Metadaten von einer schon gelesenen Datei mit gleichem SHA-256 und gleicher Endung
    (auch von anderen Platten). Braucht keine angeschlossene Platte."""
    with db() as con:
        offen = metadaten_offen(con, platte_id, nur_tabelle=True).dropna(subset=["sha256"])
        # nur gültige Vorlagen: seit dem Hashen gelesen und nicht an ExifTool gescheitert
        fertig = pd.read_sql("""
            SELECT m.platte_id, m.relpfad, d.sha256, m.quelle IS NULL AS direkt
            FROM metadaten m JOIN datei d ON d.platte_id = m.platte_id AND d.relpfad = m.relpfad
            WHERE m.gelesen_am >= d.gehasht_am AND COALESCE(m.fehler, '') != ? AND d.sha256 IN
                  (SELECT sha256 FROM datei WHERE platte_id = ?)""", con, params=(EXIF_NICHT_GELESEN, platte_id))
        vorlagen = vorlagen_waehlen(offen, fertig)
        con.executemany(f"""
            INSERT OR REPLACE INTO metadaten (platte_id, relpfad, {', '.join(FELDER)}, gelesen_am, quelle)
            SELECT ?, ?, {', '.join(FELDER)}, ?, COALESCE(quelle, platte_id || ':' || relpfad)
            FROM metadaten WHERE platte_id = ? AND relpfad = ?""",
            [(platte_id, r, jetzt(), vp, vr) for r, vp, vr in vorlagen.itertuples(index=False)])
    if len(vorlagen):
        herkunft = ", ".join(f"{p} {n}" for p, n in vorlagen.vorlage_platte.value_counts().sort_index().items())
        protokolliere("E1", platte_id, "metadaten_uebernommen", "", f"{len(vorlagen)} Dateien (Vorlagen: {herkunft})")
        print(f"Metadaten von gleichen Inhalten übernommen: {len(vorlagen):,} Dateien (Vorlagen: {herkunft}).")


class ExifTool:
    """Hält ein ExifTool-Programm offen (-stay_open), statt es für jede Datei neu zu starten."""
    def __init__(self, log):
        self.prozess = subprocess.Popen([system.werkzeug("exiftool"), "-stay_open", "True", "-@", "-"], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=log, text=True, encoding="utf-8",
                                        errors="replace")

    def lesen(self, pfade):
        self.prozess.stdin.write("\n".join(EXIF_ARGUMENTE + pfade) + "\n-execute\n")
        self.prozess.stdin.flush()
        zeilen = []
        while (zeile := self.prozess.stdout.readline()).strip() != "{ready}":
            if not zeile:
                raise RuntimeError("ExifTool hat sich beendet, siehe Logdatei.")
            zeilen.append(zeile)
        text = "".join(zeilen).strip()
        return json.loads(text) if text else []

    def beenden(self):
        self.prozess.stdin.write("-stay_open\nFalse\n")
        self.prozess.stdin.flush()
        self.prozess.wait()


def antworten_zuordnen(pfade, antworten, pfadmodul=os.path):
    """Antworten von ExifTool zu den relpfaden: pfade = {Pfad im Dateisystem: relpfad}. Verglichen wird über
    pfad_schluessel, denn ExifTool schreibt SourceFile unter Windows mit „/“."""
    je_schluessel = {pfad_schluessel(p, pfadmodul): r for p, r in pfade.items()}
    zugeordnet = {}
    for e in antworten:
        r = je_schluessel.get(pfad_schluessel(e.get("SourceFile", ""), pfadmodul))
        if r is not None:
            zugeordnet[r] = e
    return zugeordnet


def metadaten_lesen(platte_id, wurzel, stapel=100):
    """Liest die Metadaten aller Dateien, für die noch keine vorliegen (oder die seit dem Lesen neu gehasht wurden) oder
    deren Inhalt noch keine vollständige ExifTool-Ausgabe hat. Gleicher Inhalt mit gleicher Endung wird je Platte nur
    einmal gelesen; die übrigen Fundorte übernehmen danach die Zeile in `metadaten` (metadaten_uebernehmen)."""
    if not system.werkzeug_pfad("exiftool"):
        raise RuntimeError("ExifTool fehlt. " + system.installationshinweis("exiftool"))
    with db() as con:
        weg = con.execute("DELETE FROM metadaten WHERE platte_id = ? AND NOT EXISTS (SELECT 1 FROM datei d "
                          "WHERE d.platte_id = metadaten.platte_id AND d.relpfad = metadaten.relpfad)",
                          (platte_id,)).rowcount
        offen = metadaten_offen(con, platte_id)
        # gleicher Inhalt mit gleicher Endung: nur einmal lesen (ohne Prüfsumme jede Datei einzeln)
        offen = offen.assign(schluessel=[f"{s}|{endung(r)}" if s else r for r, s in zip(offen.relpfad, offen.sha256)])
        sha_von = dict(zip(offen.relpfad, offen.sha256))
        offen = offen.drop_duplicates("schluessel").relpfad.tolist()
    if weg:
        print(f"{weg:,} Einträge zu nicht mehr vorhandenen Dateien entfernt.")
    if not offen:
        print(f"Für {platte_id} liegen alle Metadaten vor.")
        return
    angeschlossene_platte_pruefen(platte_id, wurzel)
    print(f"Offen: {len(offen):,} Dateien.")

    with db() as con:
        lauf_id = con.execute("INSERT INTO scanlauf (platte_id, art, start) VALUES (?,?,?)",
                              (platte_id, "metadaten", jetzt())).lastrowid
    spalten = ["platte_id", "relpfad", *FELDER, "gelesen_am"]
    sql = f"INSERT OR REPLACE INTO metadaten ({', '.join(spalten)}) VALUES ({', '.join('?' * len(spalten))})"
    sql_voll = ("INSERT OR REPLACE INTO exif_voll (sha256, endung, daten, felder, exiftool, fehler, gelesen_am, quelle) "
                "VALUES (?,?,?,?,?,?,?,?)")
    version = exiftool_version()
    logdatei = P.logs / f"exiftool_{platte_id}_{datetime.now():%Y-%m-%d_%H%M}.log"
    erledigt = 0
    start = time.monotonic()
    unterbrochen = False
    with open(logdatei, "w", encoding="utf-8") as log, db() as con:
        exiftool = ExifTool(log)
        try:
            for i in range(0, len(offen), stapel):
                teil = offen[i:i + stapel]
                # Dateien in Archivdateien je Stapel kurz ins Projekt entpacken (Entscheidung 06.11.2026)
                with archivdateien.bereitstellen(platte_id, wurzel, teil) as pfad:
                    pfade = {os.path.abspath(pfad(r)): r for r in teil}
                    roh = antworten_zuordnen(pfade, exiftool.lesen(list(pfade)))
                zeilen, voll = [], []
                for r in teil:      # Dateien, die ExifTool nicht lesen konnte, bekommen einen Fehlereintrag
                    z = auswahl(roh[r]) if r in roh else {**dict.fromkeys(FELDER), "fehler": EXIF_NICHT_GELESEN}
                    zeilen.append((platte_id, r, *(z[s] for s in FELDER), jetzt()))
                    if sha_von.get(r):
                        daten, felder = vollabbild(roh[r]) if r in roh else (None, 0)
                        voll.append((sha_von[r], endung(r), daten, felder, version,
                                     None if r in roh else EXIF_NICHT_GELESEN, jetzt(), f"{platte_id}:{r}"))
                con.executemany(sql, zeilen)
                con.executemany(sql_voll, voll)
                con.commit()
                erledigt += len(teil)
                minuten = (time.monotonic() - start) / 60
                fortschritt(erledigt / len(offen), f"{erledigt:,}/{len(offen):,} Dateien · "
                            f"{restzeit(minuten / erledigt * (len(offen) - erledigt))}")
        except KeyboardInterrupt:
            unterbrochen = True
        finally:
            exiftool.beenden()
        con.execute("UPDATE scanlauf SET ende = ?, dateien = ? WHERE lauf_id = ?", (jetzt(), erledigt, lauf_id))
    protokolliere("E1", platte_id, "metadaten", "", f"{erledigt} Dateien" + (", unterbrochen" if unterbrochen else ""))
    if not unterbrochen:
        metadaten_uebernehmen(platte_id)     # weitere Fundorte gleichen Inhalts auf dieser Platte
    print(f"\n{'Unterbrochen' if unterbrochen else 'Fertig'}: {erledigt:,} Dateien gelesen. "
          f"Meldungen von ExifTool: {logdatei.relative_to(P.ordner)}")


def bestes_datum():
    """E2 Bestes Datum je Datei mit Quelle ableiten (alle Datenträger, keine Platte nötig)."""
    JAHR = r"(?<!\d)(19\d\d|20\d\d)(?!\d)"
    DATUM_IM_NAMEN = r"(?<!\d)(19\d\d|20\d\d)[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])(?!\d)"


    def jahr_ok(jahr):
        return pd.to_numeric(jahr, errors="coerce").between(1900, datetime.now().year)


    with db() as con:
        m = pd.read_sql("""SELECT m.platte_id, m.relpfad, m.aufnahme, m.datum_xmp, m.erstellt, m.datum, m.datum_quelle,
                                  d.mtime FROM metadaten m JOIN datei d USING (platte_id, relpfad)""", con)
    name = m.relpfad.map(os.path.basename)
    ordner = m.relpfad.map(os.path.dirname)

    im_namen = name.str.extract(DATUM_IM_NAMEN)
    aus_namen = (im_namen[0] + "-" + im_namen[1] + "-" + im_namen[2]).where(jahr_ok(im_namen[0]))
    jahr_im_namen = name.str.findall(JAHR).map(lambda j: j[-1] if j else None)
    aus_namen = aus_namen.fillna(jahr_im_namen.where(jahr_ok(jahr_im_namen)))
    # im Ordnerpfad zählt das Jahr im tiefsten Ordner, z. B. „Archiv 1999/Messe 2003“ → 2003
    aus_ordner = ordner.str.findall(JAHR).map(lambda j: j[-1] if j else None)
    aus_ordner = aus_ordner.where(jahr_ok(aus_ordner))
    plausibel = m.mtime.between(MTIME_AB, datetime.now().timestamp())
    aus_dateisystem = pd.to_datetime(m.mtime.where(plausibel), unit="s").dt.strftime("%Y-%m-%d")

    kandidaten = [("EXIF", m.aufnahme), ("XMP/IPTC", m.datum_xmp), ("Dokument", m.erstellt),
                  ("Dateiname", aus_namen), ("Ordnername", aus_ordner), ("Dateisystem", aus_dateisystem)]
    neu_datum = pd.Series(None, index=m.index, dtype="object")
    neu_quelle = pd.Series(None, index=m.index, dtype="object")
    for quelle_name, werte in kandidaten:
        frei = neu_datum.isna() & werte.notna()
        neu_datum[frei] = werte[frei].str[:10]
        neu_quelle[frei] = quelle_name

    geaendert = (neu_datum.fillna("") != m.datum.fillna("")) | (neu_quelle.fillna("") != m.datum_quelle.fillna(""))
    with db() as con:
        con.executemany("UPDATE metadaten SET datum = ?, datum_quelle = ? WHERE platte_id = ? AND relpfad = ?",
                        zip(neu_datum[geaendert], neu_quelle[geaendert], m.platte_id[geaendert], m.relpfad[geaendert]))
    if geaendert.any():
        protokolliere("E2", "alle Datenträger", "datum", "", f"{geaendert.sum()} Dateien neu datiert")
    print(f"Bestes Datum für {neu_datum.notna().sum():,} von {len(m):,} Dateien, davon {geaendert.sum():,} neu oder geändert.")

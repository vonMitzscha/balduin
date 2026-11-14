"""Ergebnisse ansehen (nur im Notebook): liest nur aus der Datenbank, keine Platte nötig."""
from .basis import *  # noqa: F401,F403
from .anzeige import balken, kacheln, neben, saeulen_jahre
from .archiv import STUFE

def schnellscan(platte_id):
    """C1c Erster Blick auf eine gescannte Platte."""
    with db() as con:
        df = pd.read_sql("SELECT * FROM schnellscan WHERE platte_id = ?", con, params=(platte_id,))
        # Lesefehler des letzten Schnellscans dieser Platte (so läuft die Zelle auch ohne C1b nach einem Neustart)
        fehler = pd.read_sql("""
            SELECT relpfad, fehler FROM scanfehler WHERE lauf_id =
                (SELECT MAX(lauf_id) FROM scanlauf WHERE platte_id = ? AND art = 'schnellscan')""",
            con, params=(platte_id,))

    df["endung"] = df.name.str.extract(r"\.([^.]+)$", expand=False).str.lower().fillna("(ohne)")
    # Defekte Zeitstempel nicht umrechnen; der Rohwert bleibt in der Datenbank
    plausibel = df.mtime.between(MTIME_AB, datetime.now().timestamp())
    df["datum"] = pd.to_datetime(df.mtime.where(plausibel), unit="s")
    df["jahr"] = df.datum.dt.year.astype("Int64").astype("string").fillna("(unplausibel)")

    print(f"{platte_id}: {len(df):,} Dateien, {df.groesse.sum() / 1e9:.1f} GB")
    print("Änderungsdatum von", df.datum.min().date(), "bis", df.datum.max().date())
    if (~plausibel).any():
        print(f"{(~plausibel).sum():,} Dateien mit unplausiblem Änderungsdatum (vor 1980 oder nach heute), z. B.:")
        zeige(df.loc[~plausibel, ["relpfad", "mtime"]].head(10))

    endungen = (df.groupby("endung")
                  .agg(dateien=("name", "size"), gb=("groesse", lambda s: round(s.sum() / 1e9, 2)))
                  .sort_values("dateien", ascending=False).head(20))
    neben(endungen, balken(endungen.dateien, "Dateien je Endung (häufigste 20)"),
          balken(endungen.gb.sort_values(ascending=False), "Umfang in GB je Endung"))

    jahre = df.jahr.value_counts().sort_index().rename("Dateien nach Jahr der letzten Änderung").to_frame()
    plausible_jahre = df.datum.dt.year.dropna().astype(int).value_counts().sort_index()
    neben(jahre, saeulen_jahre(plausible_jahre, "Dateien nach Jahr der letzten Änderung"))
    if len(fehler):
        print(f"{len(fehler)} Pfade konnten nicht gelesen werden:")
        zeige(fehler.head(20))


def platten():
    """C1d Alle registrierten Platten im Überblick."""
    with db() as con:
        uebersicht = pd.read_sql("""
            SELECT p.platte_id, p.etikett_text, p.volume_name, p.dateisystem, p.smart_status, p.kopie_von,
                   COUNT(s.relpfad)                     AS dateien,
                   ROUND(SUM(s.groesse) / 1e9, 1)       AS gb,
                   DATE(MIN(CASE WHEN s.mtime BETWEEN :ab AND :bis THEN s.mtime END), 'unixepoch') AS aelteste,
                   DATE(MAX(CASE WHEN s.mtime BETWEEN :ab AND :bis THEN s.mtime END), 'unixepoch') AS juengste,
                   SUM(s.mtime NOT BETWEEN :ab AND :bis) AS datum_unplausibel,
                   p.volume_uuid
            FROM platte p LEFT JOIN schnellscan s USING (platte_id)
            GROUP BY p.platte_id ORDER BY p.platte_id""", con,
            params={"ab": MTIME_AB, "bis": datetime.now().timestamp()})
    return uebersicht


def vollscan(platte_id):
    """D4 Ergebnis des Vollscans: Formate, nicht erkannt, Warnungen, Virenscan, gleiche Inhalte."""
    with db() as con:
        d = pd.read_sql("SELECT * FROM datei WHERE platte_id = ?", con, params=(platte_id,))
    d["endung"] = d.relpfad.str.extract(r"\.([^./]+)$", expand=False).str.lower().fillna("(ohne)")
    lesefehler = d.sha256.isna() & d.hash_fehler.notna()

    print(f"{platte_id}: {len(d):,} Dateien · mit Prüfsummen {d.sha256.notna().sum():,} · "
          f"Format bestimmt {d.sf_am.notna().sum():,} (davon übernommen {d.sf_quelle.notna().sum():,}) · "
          f"Lesefehler {lesefehler.sum():,}")

    print("\nHäufigste Formate:")
    formate = (d.groupby(["puid", "format", "formatversion"], dropna=False)
                 .agg(dateien=("relpfad", "size"), gb=("groesse", lambda s: round(s.sum() / 1e9, 2)))
                 .sort_values("dateien", ascending=False).head(25))
    beschriftung = [f"{kuerzen(next((x for x in (f, p) if pd.notna(x) and x), '(nicht bestimmt)'), 34)} "
                    f"{v if pd.notna(v) else ''}".strip() for p, f, v in formate.index]
    neben(formate, balken(pd.Series(formate.dateien.values, index=beschriftung), "Dateien je Format (häufigste 25)"))

    unbekannt = d[d.puid == "UNKNOWN"]
    if len(unbekannt):
        print(f"\nNicht erkannt: {len(unbekannt):,} Dateien, nach Endung:")
        unbekannt_endungen = unbekannt.endung.value_counts().head(15)
        neben(unbekannt_endungen.to_frame("dateien"), balken(unbekannt_endungen, "Nicht erkannte Dateien je Endung"))

    warnung = d[(d.puid != "UNKNOWN") & d.sf_warnung.fillna("").ne("")]
    if len(warnung):
        print(f"\nWarnungen von Siegfried: {len(warnung):,} Dateien")
        zeige(warnung.sf_warnung.value_counts().head(10).to_frame("dateien"))

    if lesefehler.any() or d.hash_fehler.notna().any():
        print("\nLesefehler und Auffälligkeiten beim Lesen:")
        zeige(d.loc[d.hash_fehler.notna(), ["relpfad", "groesse", "hash_fehler"]].head(20))

    with db() as con:
        viren = pd.read_sql("""SELECT d.relpfad, COALESCE(v.befund, 'noch nicht geprüft') AS befund, v.meldung
                               FROM datei d LEFT JOIN virenscan v ON v.sha256 = d.sha256
                               WHERE d.platte_id = ? AND d.groesse > 0""", con, params=(platte_id,))
    print("\nVirenscan (D3), je Datei:", ", ".join(f"{b} {n:,}" for b, n in viren.befund.value_counts().items()))
    if (viren.befund == "Fund").any():
        print("⚠ Dateien mit Virenfund (nicht öffnen; E und F lassen sie aus, H setzt sie auf rot):")
        zeige(viren.loc[viren.befund == "Fund", ["relpfad", "meldung"]])
    if (viren.befund == "nicht geprüft").any():
        zeige(viren[viren.befund == "nicht geprüft"].meldung.value_counts().head(10).to_frame("nicht geprüft, Dateien"))

    gleich = d[(d.groesse > 0) & d.sha256.notna()].groupby("sha256").agg(n=("relpfad", "size"), groesse=("groesse", "first"))
    gleich = gleich[gleich.n > 1]
    print(f"\nGleiche Inhalte auf dieser Platte: {len(gleich):,} Inhalte liegen mehrfach vor "
          f"({gleich.n.sum():,} Dateien, davon {((gleich.n - 1) * gleich.groesse).sum() / 1e9:.1f} GB überzählig). "
          "Auswertung in Abschnitt G.")


def metadaten(platte_id):
    """E3 Ergebnis der Metadaten: Abdeckung, Datumsquelle, Kameras, Meldungen."""
    with db() as con:
        m = pd.read_sql("SELECT m.*, d.mime FROM metadaten m JOIN datei d USING (platte_id, relpfad) WHERE platte_id = ?",
                        con, params=(platte_id,))
    bilder = m[m.mime.fillna("").str.startswith("image/")]
    print(f"{platte_id}: Metadaten für {len(m):,} Dateien, davon {len(bilder):,} Bilder.")

    felder = ["aufnahme", "hersteller", "seriennummer", "gps_breite", "urheber", "copyright", "titel",
              "beschreibung", "schlagworte", "software", "farbprofil"]
    abdeckung = pd.DataFrame({"Bilder %": (bilder[felder].notna().mean() * 100).round(1),
                              "alle Dateien %": (m[felder].notna().mean() * 100).round(1)})
    print("\nAbdeckung der Felder:")
    neben(abdeckung, balken(abdeckung["Bilder %"], "Bilder mit diesem Feld, in %"))

    print("Herkunft des besten Datums:")
    quellen = m.datum_quelle.fillna("(keines)").value_counts()
    jahre = m.datum.dropna().str[:4].astype(int).value_counts().sort_index()
    neben(quellen.to_frame("dateien"), balken(quellen, "Dateien je Datumsquelle"),
          saeulen_jahre(jahre, "Dateien je Jahr (bestes Datum)"))

    kameras = (bilder.assign(kamera=(bilder.hersteller.fillna("") + " " + bilder.kamera.fillna("")).str.strip())
               .query("kamera != ''").kamera.value_counts().head(15))
    if len(kameras):
        print("Häufigste Kameras und Scanner:")
        neben(kameras.to_frame("bilder"), balken(kameras, "Bilder je Gerät"))

    meldungen = m.fehler.fillna(m.warnung).dropna()
    if len(meldungen):
        print(f"Meldungen von ExifTool: {m.fehler.notna().sum():,} Fehler, {m.warnung.notna().sum():,} Warnungen")
        zeige(meldungen.value_counts().head(10).to_frame("dateien"))


def vorschauen(platte_id):
    """F4 Vorschaubilder: Zahlen, Probleme und eine Zufallsauswahl."""
    with db() as con:
        v = pd.read_sql("""SELECT DISTINCT v.*, d.relpfad FROM vorschau v JOIN datei d ON d.sha256 = v.sha256
                           WHERE d.platte_id = ?""", con, params=(platte_id,)).drop_duplicates("sha256")
    print(f"{platte_id}: {v.datei.notna().sum():,} Vorschaubilder für {len(v):,} Inhalte.")
    zeige(pd.crosstab(v.art, v.quelle.fillna("keine"), margins=True, margins_name="Summe"))

    ohne = v[v.datei.isna()]
    if len(ohne):
        print(f"\nOhne Vorschau: {len(ohne):,}, nach Endung:")
        zeige(ohne.relpfad.str.extract(r"\.([^./]+)$", expand=False).str.lower().value_counts().head(10).to_frame("inhalte"))
    holprig = v[v.datei.notna() & v.fehler.notna() & (v.art == "bild")]
    if len(holprig):
        print(f"Bilder, die Pillow nicht lesen konnte (Vorschau über einen anderen Weg): {len(holprig):,}. Beispiele:")
        zeige(holprig[["relpfad", "quelle", "fehler"]].head(10))

    print("\nZufallsauswahl:")
    probe = v[v.datei.notna()].sample(min(24, v.datei.notna().sum()), random_state=1)
    kacheln([(s, kuerzen(r, 60)) for s, r in zip(probe.sha256, probe.relpfad)])


def anton():
    """G5d Abgleich mit Anton: Status je Platte, Bestände in Anton, Ordner mit Treffern."""
    REIHENFOLGE_ANTON = ["in Anton", "gleicher Name, andere Datei", "nicht in Anton", "nicht geprüft", "leere Datei", "Systemdatei"]
    with db() as con:
        a = pd.read_sql("SELECT a.*, d.groesse FROM anton_abgleich a JOIN datei d USING (platte_id, relpfad)", con)
        quelle_anton, stand, nur_platten = con.execute("SELECT quelle, stand, nur_platten FROM anton_stand WHERE aktuell = 1").fetchone()
    print(f"Auszug {quelle_anton}, Stand {stand}" + (f"; vollständig abgeglichen nur {nur_platten}." if nur_platten else "."))
    zeige(pd.crosstab(a.platte_id, a.status, margins=True, margins_name="Summe")
            .reindex(columns=[s for s in REIHENFOLGE_ANTON if s in set(a.status)] + ["Summe"]).rename_axis(index=None, columns=None))

    treffer = a[a.status == "in Anton"]
    if len(treffer):
        print(f"\nIn Anton: {len(treffer):,} Dateien ({treffer.md5.nunique():,} verschiedene Inhalte), {treffer.groesse.sum() / 1e9:.1f} GB.")
        bestaende = treffer.assign(bestand=treffer.signatur.str.split(" | ", regex=False)).explode("bestand")
        bestaende["bestand"] = bestaende.bestand.str.extract(r"^(\D*\d+)", expand=False)
        zeige(bestaende.groupby("bestand").agg(dateien=("relpfad", "size"), inhalte=("md5", "nunique"),
                                                 platten=("platte_id", lambda p: ", ".join(sorted(set(p)))))
                .sort_values("dateien", ascending=False).rename_axis(index="Bestand in Anton"))
        ordner = (treffer.assign(ordner=treffer.platte_id + ": " + treffer.relpfad.map(os.path.dirname))
                  .groupby("ordner").size().sort_values(ascending=False).head(15).rename("in Anton"))
        print("\nOrdner mit den meisten Dateien in Anton:")
        zeige(ordner.to_frame())


def archiv(platte_id):
    """H3 Ergebnis der Archivfähigkeit."""
    with db() as con:
        a = pd.read_sql("""SELECT a.*, d.groesse, d.format, d.puid FROM archiv a JOIN datei d USING (platte_id, relpfad)
                           WHERE platte_id = ?""", con, params=(platte_id,))
    ampel = (a.groupby("ampel").agg(dateien=("relpfad", "size"), gb=("groesse", lambda s: round(s.sum() / 1e9, 1)))
              .reindex(list(STUFE)).fillna(0))
    print(f"{platte_id}: Archivfähigkeit")
    neben(ampel, balken(ampel.dateien, "Dateien je Ampel"))

    gelb = a[a.ampel == "gelb"]
    if len(gelb):
        print("Gelb: Maßnahmen")
        massnahmen = gelb.groupby("massnahme").agg(dateien=("relpfad", "size"), gb=("groesse", lambda s: round(s.sum() / 1e9, 1)))
        massnahmen = massnahmen.sort_values("dateien", ascending=False)
        neben(massnahmen, balken(massnahmen.dateien.head(15), "Gelbe Dateien je Maßnahme"))

    rot = a[a.ampel == "rot"]
    if len(rot):
        print("Rot: Gründe (ohne Formatnamen)")
        gruende = rot.grund.str.split(" · ").map(lambda t: t[-1] if len(t) > 1 else t[0]).value_counts().head(15)
        neben(gruende.to_frame("dateien"), balken(gruende, "Rote Dateien je Grund"))

    if a.nara_risiko.notna().any():
        print("Eigene Ampel (Zeilen) und NARA-Risiko (Spalten), Dateien:")
        vergleich = pd.crosstab(a.ampel, a.nara_risiko, margins=True, margins_name="Summe")
        zeige(vergleich.reindex(index=[*STUFE, "Summe"], columns=["Low", "Moderate", "High", "Unknown", "Summe"]).dropna(how="all")
                .dropna(axis=1, how="all").fillna(0).astype(int))
        print("NARA-Maßnahmen:")
        zeige(a.fillna({"nara_massnahme": "(nicht bei NARA)", "nara_plan": ""}).groupby(["nara_massnahme", "nara_plan"])
                 .agg(dateien=("relpfad", "size"), gb=("groesse", lambda s: round(s.sum() / 1e9, 1)))
                 .sort_values("dateien", ascending=False).head(15))

    fehlt = a[a.grund.str.contains("nicht in der Regeltabelle")]
    if len(fehlt):
        print("Formate ohne Regel (in vorgaben/archivformate.csv ergänzen):")
        zeige(fehlt.groupby(["puid", "format"], dropna=False).size().sort_values(ascending=False).head(20).to_frame("dateien"))

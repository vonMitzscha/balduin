"""H Archivfähigkeit (Ampel nach Regeltabelle und Befunden, NARA daneben) und Leitdatei je Duplikatgruppe."""
from .basis import *  # noqa: F401,F403


STUFE = {"grün": 0, "gelb": 1, "rot": 2}

# Maßnahmen der NARA mit ihrer Bezeichnung (wie resolveNaraIdLabel in nara-risk)
NARA_MASSNAHME = {"Retain": "Retain", "Assess": "Retain for Future Assessment", "Transform": "Transform",
                  "Identify": "Identify Version"}


def nara_datei():
    """Neueste fileformats.ttl der NARA: Kopie im Projekt (vorgaben/nara/), sonst die aus dem Git.
    Neu laden mit werkzeuge/nara_laden.py."""
    for ordner in (P.vorgaben / "nara", CODE / "vorgaben" / "nara"):
        dateien = sorted(ordner.glob("NARA_fileformats_*.ttl"))
        if dateien:
            return dateien[-1]
    raise FileNotFoundError("vorgaben/nara/NARA_fileformats_*.ttl fehlt (werkzeuge/nara_laden.py)")


def nara_lesen(pfad):
    """fileformats.ttl → {PUID: {puid, nara_id, nara_kategorie, nara_risiko, nara_massnahme, nara_plan}}.
    Gleiche Regeln wie NaraTtlParserService in kraenzle-ritter/nara-risk (v0.2.0), damit Balduin und Anton für
    dieselbe Datei dasselbe zeigen: je NARA-Format die erste PRONOM-ID (erste Eigenschaft mit „fmt/“ im Wert);
    führen mehrere Formate dieselbe PUID, gilt das letzte in der Datei; Kategorie, Risiko, Maßnahme je der erste Wert.
    Die Kategorie bleibt der Schlüssel der NARA (z. B. StillImage), wie ihn auch das Anton-Importformat nennt."""
    text = pfad.read_text(encoding="utf-8")
    ergebnis = {}
    for subjekt, rumpf in re.findall(r"^naraid:(NF\d+)\s*\n(.*?)^\.\s*$", text, re.S | re.M):
        zeilen = re.findall(r"^\s+(\S+)\s+(.*?)\s*;\s*$", rumpf, re.M)
        puid = next((m[1] for _, o in zeilen if "fmt/" in o.lower() for m in [re.search(r"(fmt/\d+|x-fmt/\d+)", o)] if m),
                    None)
        if not puid:
            continue

        def erster(eigenschaft):
            return next((o for p, o in zeilen if p == eigenschaft), "")

        wert = lambda o: o.split(":", 1)[1] if o.startswith("naraid:") else o.strip('"')   # noqa: E731
        massnahme = wert(erster("nara:preservationAction"))
        ergebnis[puid] = {"puid": puid, "nara_id": subjekt, "nara_kategorie": wert(erster("nara:category")) or None,
                          "nara_risiko": wert(erster("nara:riskLevel")) or None,
                          "nara_massnahme": NARA_MASSNAHME.get(massnahme, massnahme) or None,
                          "nara_plan": erster("nara:preservationPlan").strip('"') or None}
    return ergebnis


def archivfaehigkeit():
    """H1 Regeltabelle laden, Ampel je Datei bestimmen, NARA-Risiko daneben (alle Platten)."""
    regeln = csv_lesen(P.vorgaben / "archivformate.csv")
    assert set(regeln.ampel) <= set(STUFE), f"Unbekannte Ampel in archivformate.csv: {set(regeln.ampel) - set(STUFE)}"


    def regel_fuer(puid, format_name):
        """Erste passende Zeile der Regeltabelle: PRONOM-ID exakt oder Formatname als Suchmuster."""
        format_name = format_name if isinstance(format_name, str) else ""     # fehlender Formatname kommt als NaN (float)
        for r in regeln.itertuples():
            if (r.puid and r.puid == puid) or (r.format_muster and format_name and re.search(r.format_muster, format_name, re.I)):
                return r.ampel, r.massnahme, r.begruendung
        return "gelb", "prüfen und Regel in archivformate.csv ergänzen", "Format nicht in der Regeltabelle"


    with db() as con:
        d = pd.read_sql("""SELECT d.platte_id, d.relpfad, d.groesse, d.sha256, d.hash_fehler, d.puid, d.format, d.sf_am,
                                  d.sf_warnung, v.art AS v_art, v.datei AS v_datei, v.fehler AS v_fehler, m.fehler AS exif_fehler,
                                  vs.befund AS viren_befund, vs.meldung AS viren_meldung
                           FROM datei d LEFT JOIN vorschau v ON v.sha256 = d.sha256
                           LEFT JOIN virenscan vs ON vs.sha256 = d.sha256
                           LEFT JOIN metadaten m ON m.platte_id = d.platte_id AND m.relpfad = d.relpfad""", con)

    if d.empty:                                         # noch keine Datei im Projekt (z. B. leerer Datenträger)
        print("Noch keine Dateien mit Prüfsumme: nichts zu bewerten.")
        return
    formate = d[["puid", "format"]].drop_duplicates()
    formate[["ampel", "massnahme", "grund"]] = [regel_fuer(p, f) for p, f in zip(formate.puid, formate.format)]
    d = d.merge(formate, on=["puid", "format"], how="left")
    d["grund"] = d.format.fillna(d.puid).fillna("") + ": " + d.grund

    # Befunde aus D, E und F, jeweils (Bedingung, Ampel, Grund, Maßnahme oder None = Maßnahme der Regel bleibt)
    bild = d.v_art.isin(["bild", "raw"])
    pillow_fehler = d.v_fehler.fillna("").str.contains("mit_pillow") & ~d.v_fehler.fillna("").str.contains("cannot identify")
    befunde = [
        (d.viren_befund == "Fund", "rot", "Virenfund: " + d.viren_meldung.fillna(""), "nicht übernehmen; Original nur isoliert prüfen"),
        (d.viren_befund == "nicht geprüft", None, "nicht auf Viren geprüft: " + d.viren_meldung.fillna(""), None),
        (d.relpfad.map(ist_systemdatei).astype(bool), "rot", "Systemdatei", "kassieren (Vorschlag)"),
        (d.groesse == 0, "rot", "leere Datei (0 Byte)", "kassieren (Vorschlag)"),
        (d.sha256.isna() & d.hash_fehler.notna(), "rot", "Lesefehler im Vollscan", "Datenträger erneut lesen, sonst verloren"),
        (d.sf_am.isna(), "gelb", "Format noch nicht bestimmt (D2)", "D2 ausführen"),
        (bild & d.v_datei.isna() & d.v_fehler.notna(), "rot", "Bild nicht lesbar", "Original prüfen, ggf. beschädigt"),
        (bild & d.v_datei.notna() & pillow_fehler, "gelb", "Bild nur über Umweg lesbar", "Original prüfen"),
        (d.exif_fehler.notna() & ~d.exif_fehler.fillna("").str.startswith("von ExifTool"), "gelb",
         "ExifTool meldet Fehler", "Original prüfen"),
        (d.sf_warnung.fillna("").str.contains("extension mismatch"), None, "Endung passt nicht zum Inhalt", None),
    ]
    for bedingung, ampel, grund, massnahme in befunde:
        bedingung = bedingung.fillna(False).astype(bool)
        d.loc[bedingung, "grund"] = d.loc[bedingung, "grund"] + " · " + grund
        if ampel:
            schlechter = bedingung & (d.ampel.map(STUFE) < STUFE[ampel])
            d.loc[schlechter, "ampel"] = ampel
            if massnahme:
                d.loc[schlechter, "massnahme"] = massnahme

    # NARA: Risiko und Maßnahme je PRONOM-ID, neben der eigenen Ampel (Digital Preservation Framework, gleiche Quelle
    # und Zuordnung wie das Anton-Paket nara-risk, Entscheidung 04.11.2026)
    nara_pfad = nara_datei()
    nara_stand = re.search(r"\d{8}", nara_pfad.name).group()
    nara = pd.DataFrame(nara_lesen(nara_pfad).values())
    NARA_SPALTEN = ["nara_id", "nara_kategorie", "nara_risiko", "nara_massnahme", "nara_plan"]
    d = d.merge(nara[["puid"] + NARA_SPALTEN], on="puid", how="left")
    d["nara_risiko"] = d.nara_risiko.fillna("Unknown")
    d.loc[d.puid.isna() | (d.puid == "UNKNOWN"), "nara_massnahme"] = "Identify"     # wie Anton: nicht identifiziert
    d["nara_stand"] = nara_stand
    nara_werte = d[NARA_SPALTEN + ["nara_stand"]].astype(object)
    nara_werte = nara_werte.where(nara_werte.notna(), None)

    with db() as con:
        alt = dict(con.execute("SELECT ampel, COUNT(*) FROM archiv GROUP BY ampel").fetchall())
        alt_nara = dict(con.execute("SELECT nara_risiko, COUNT(*) FROM archiv GROUP BY nara_risiko").fetchall())
        con.execute("DELETE FROM archiv")
        con.executemany("INSERT INTO archiv (platte_id, relpfad, ampel, grund, massnahme, bewertet_am, nara_id, nara_kategorie, "
                        "nara_risiko, nara_massnahme, nara_plan, nara_stand) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        [(*z, *n) for z, n in zip(zip(d.platte_id, d.relpfad, d.ampel, d.grund, d.massnahme, [jetzt()] * len(d)),
                                                  nara_werte.itertuples(index=False))])
    neu = d.ampel.value_counts().to_dict()
    neu_nara = d.nara_risiko.value_counts().to_dict()
    protokolliere("H1", "alle Datenträger", "ampel", json.dumps(alt, ensure_ascii=False), json.dumps(neu, ensure_ascii=False))
    protokolliere("H1", "alle Datenträger", f"nara_risiko (NARA {nara_stand})", json.dumps(alt_nara), json.dumps(neu_nara))
    print("Ampel für alle Datenträger:", ", ".join(f"{a} {neu.get(a, 0):,}" for a in STUFE))
    print(f"NARA-Risiko (Stand {nara_stand}):", ", ".join(f"{r} {neu_nara.get(r, 0):,}" for r in ["Low", "Moderate", "High", "Unknown"]))


def leitdateien():
    """H2 Leitdatei je Duplikatgruppe vorschlagen."""
    with db() as con:
        g = pd.read_sql("""
            SELECT g.art, g.gruppe_id, g.platte_id, g.relpfad, g.leitdatei, a.ampel, d.groesse, d.mtime, p.kopie_von,
                   COALESCE(m.breite, v.breite) AS breite, COALESCE(m.hoehe, v.hoehe) AS hoehe, m.datum,
                   (m.urheber IS NOT NULL) + (m.copyright IS NOT NULL) + (m.titel IS NOT NULL) + (m.beschreibung IS NOT NULL)
                   + (m.schlagworte IS NOT NULL) + (m.aufnahme IS NOT NULL) + (m.gps_breite IS NOT NULL) AS metadaten
            FROM gruppe g JOIN datei d USING (platte_id, relpfad)
            LEFT JOIN archiv a USING (platte_id, relpfad)
            LEFT JOIN metadaten m USING (platte_id, relpfad)
            LEFT JOIN vorschau v ON v.sha256 = d.sha256
            LEFT JOIN platte p ON p.platte_id = g.platte_id""", con)
    g["stufe"] = g.ampel.map(STUFE).fillna(1)
    g["pixel"] = (g.breite * g.hoehe).fillna(0)
    g["auf_kopie"] = g.kopie_von.notna()
    g["datum"] = g.datum.fillna("9999")
    g["pfadlaenge"] = g.relpfad.str.len()
    g = g.sort_values(["art", "gruppe_id", "stufe", "pixel", "groesse", "metadaten", "auf_kopie", "datum", "mtime", "pfadlaenge"],
                      ascending=[True, True, True, False, False, False, True, True, True, True])
    g["neu"] = (~g.duplicated(["art", "gruppe_id"])).astype(int)

    geaendert = g[g.neu != g.leitdatei]
    with db() as con:
        con.executemany("UPDATE gruppe SET leitdatei = ? WHERE art = ? AND platte_id = ? AND relpfad = ?",
                        zip(geaendert.neu, geaendert.art, geaendert.platte_id, geaendert.relpfad))
    if len(geaendert):
        protokolliere("H2", "alle Datenträger", "leitdatei", "", f"{(geaendert.neu == 1).sum()} Leitdateien neu gesetzt")
    print(f"Leitdateien: {g.neu.sum():,} Gruppen, {len(geaendert):,} Einträge geändert.")

    beispiel = g[g.gruppe_id.isin(g[g.art == "variante"].gruppe_id.drop_duplicates().head(3))]
    if len(beispiel):
        print("\nBeispiel Formatvarianten (Leitdatei = 1):")
        zeige(beispiel[["gruppe_id", "relpfad", "ampel", "breite", "hoehe", "groesse", "neu"]])

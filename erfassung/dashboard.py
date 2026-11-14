"""Daten für das Dashboard des Tools und den daraus gespeicherten Bericht (docs/plan.md, Entscheidung 29.10.2026).

Rechnet aus der Datenbank: Bestand (Formate, Zeitraum), Archivfähigkeit (eigene Regeln
und NARA getrennt), Duplikate (mit Treemap), Ordnerbaum je Platte, Anton, Probleme, Platten, Scanläufe und Protokoll. Ergebnis ist ein dict, das sich als
JSON ausgeben lässt; die Bewertung (wirksame Entscheidungen) und den Stand der Analyse ergänzt das Tool.
Aufruf durch das Tool: python -m erfassung.lauf dashboard --projekt …
"""
from .basis import *  # noqa: F401,F403
from .uebersicht import ARTEN, DATUMSSTUFE, FORMATGRUPPEN, duplikat_spalten, formatgruppe, ordnerbaum, treemap_daten

GRENZE = 300             # höchstens so viele Zeilen je Tabelle; der Bericht soll handlich bleiben


def zeilen(df, grenze=GRENZE):
    """Tabelle als Liste von dicts für JSON (NaN → None)."""
    df = df.head(grenze).astype(object)
    return df.where(df.notna(), None).to_dict("records")


def daten():
    with db() as con:
        alle = pd.read_sql("""
            SELECT d.platte_id, d.relpfad, d.groesse, d.sha256, d.md5, d.puid, d.format, d.formatversion, d.mime,
                   d.hash_fehler, d.sf_warnung, d.sf_fehler, m.datum, m.datum_quelle, m.fehler AS exif_fehler,
                   a.ampel, a.grund, a.massnahme, a.nara_risiko, a.nara_massnahme, a.nara_plan,
                   v.datei AS vorschau, v.fehler AS v_fehler, an.status AS anton_status, an.signatur AS anton_signatur,
                   vs.befund AS viren_befund, vs.meldung AS viren_meldung
            FROM datei d
            LEFT JOIN metadaten m ON m.platte_id = d.platte_id AND m.relpfad = d.relpfad
            LEFT JOIN archiv a ON a.platte_id = d.platte_id AND a.relpfad = d.relpfad
            LEFT JOIN vorschau v ON v.sha256 = d.sha256
            LEFT JOIN anton_abgleich an ON an.platte_id = d.platte_id AND an.relpfad = d.relpfad
            LEFT JOIN virenscan vs ON vs.sha256 = d.sha256""", con)
        platten = pd.read_sql("SELECT * FROM platte ORDER BY platte_id", con)
        gruppen = pd.read_sql("SELECT g.art, g.gruppe_id, g.platte_id, g.relpfad, g.leitdatei, d.groesse "
                              "FROM gruppe g JOIN datei d USING (platte_id, relpfad)", con)
        ordnergruppen = pd.read_sql("SELECT * FROM ordnergruppe", con)
        scanfehler = pd.read_sql("SELECT platte_id, relpfad, fehler FROM scanfehler", con)
        scanlaeufe = pd.read_sql("SELECT * FROM scanlauf ORDER BY lauf_id DESC LIMIT 60", con)
        protokoll = pd.read_sql("SELECT zeit, abschnitt, objekt, feld, alt, neu FROM protokoll "
                                "ORDER BY zeit DESC, rowid DESC LIMIT 200", con)
        anton_stand = con.execute("SELECT stand, quelle, nur_platten, zugang, eingelesen_am FROM anton_stand "
                                  "WHERE aktuell = 1").fetchone()

    # herausgenommene Platten (Tool, Entscheidung 30.10.2026) zählen nicht mit; ihre Daten bleiben in der Datenbank
    platten = platten[platten.deaktiviert_am.isna()]
    alle, gruppen, ordnergruppen, scanfehler = (t[t.platte_id.isin(platten.platte_id)]
                                                for t in (alle, gruppen, ordnergruppen, scanfehler))
    alle["gruppe"] = formatgruppe(alle) if len(alle) else []
    alle["system"] = alle.gruppe == "Systemdatei"
    alle["ordner"] = alle.relpfad.map(os.path.dirname)
    alle["name"] = alle.relpfad.map(os.path.basename)
    alle = duplikat_spalten(alle, gruppen)
    bestand = alle[~alle.system]
    leitdateien = alle.ueberz_art.isna() & ~alle.system        # bleiben, wenn überzählige Kopien wegfallen
    gb = lambda s: s.sum()

    # ---- Bestand: Formatgruppen je Platte, häufigste Formate, Zeitraum, Datumsquellen
    reihenfolge = [g for g, _ in FORMATGRUPPEN] + ["Sonstiges", "nicht erkannt", "Systemdatei"]
    fg = (alle.groupby(["gruppe", "platte_id"]).agg(dateien=("relpfad", "size"), bytes=("groesse", "sum")).reset_index())
    formatgruppen = [{"gruppe": g, "dateien": int(t.dateien.sum()), "bytes": int(t.bytes.sum()),
                      "je_platte": {p: int(n) for p, n in zip(t.platte_id, t.dateien)}}
                     for g in reihenfolge for t in [fg[fg.gruppe == g]] if len(t)]
    formate = (bestand.groupby(["gruppe", "format", "formatversion", "puid"], dropna=False)
               .agg(dateien=("relpfad", "size"), bytes=("groesse", "sum"), ampel=("ampel", "first"),
                    endungen=("relpfad", lambda r: ", ".join(r.str.extract(r"\.([^./]+)$", expand=False).str.lower()
                                                             .value_counts().index[:4])),
                    platten=("platte_id", lambda p: ", ".join(sorted(set(p)))))
               .reset_index().sort_values("dateien", ascending=False))
    datiert = bestand[bestand.datum.notna() & bestand.datum_quelle.notna()]
    jahre = []
    if len(datiert):
        j = (datiert.assign(jahr=datiert.datum.str[:4].astype(int), stufe=datiert.datum_quelle.map(DATUMSSTUFE))
             .pivot_table(index="jahr", columns="stufe", values="relpfad", aggfunc="size", fill_value=0))
        j = j.reindex(range(j.index.min(), j.index.max() + 1), fill_value=0)
        jahre = [{"jahr": int(jahr), **{s: int(z.get(s, 0)) for s in dict.fromkeys(DATUMSSTUFE.values())}}
                 for jahr, z in j.iterrows()]
    quellen = bestand.assign(q=bestand.datum_quelle.fillna("ohne Datum")).groupby(["q", "platte_id"]).size()
    datumsquellen = [{"quelle": q, "je_platte": {p: int(n) for p, n in quellen[q].items()}}
                     for q in [*dict.fromkeys(DATUMSSTUFE), "ohne Datum"] if q in quellen.index.get_level_values(0)]

    # ---- Archivfähigkeit, getrennt: eigene Regeln (Ampel, H1) und NARA-Risiko (nur das Format)
    alle["nara_stufe"] = alle.nara_risiko.fillna("Unknown")          # Unknown: nicht bei NARA oder nicht identifiziert
    je_platte = lambda spalte, wert, f: {p: {k: int(n) for k, n in t.groupby(spalte)[wert].agg(f).items()}
                                         for p, t in alle.groupby("platte_id")}
    ohne_dup = ("relpfad", lambda r: int(leitdateien[r.index].sum()))
    formate3 = ("format", lambda f: ", ".join(f.dropna().value_counts().index[:3]))
    massnahmen = (alle.groupby(["ampel", "massnahme"]).agg(dateien=("relpfad", "size"), bytes=("groesse", "sum"),
                                                          ohne_duplikate=ohne_dup, formate=formate3)
                  .reset_index().assign(stufe=lambda x: x.ampel.map({"rot": 0, "gelb": 1, "grün": 2}))
                  .sort_values(["stufe", "dateien"], ascending=[True, False]).drop(columns="stufe"))
    gruende = (alle[alle.ampel.isin(["gelb", "rot"])].groupby(["ampel", "grund"]).agg(dateien=("relpfad", "size"), bytes=("groesse", "sum"))
               .reset_index().sort_values("dateien", ascending=False))
    mit_nara = alle.fillna({"nara_massnahme": "(nicht bei NARA)", "nara_plan": "", "nara_risiko": "Unknown"})
    nara = (mit_nara.groupby(["nara_risiko", "nara_massnahme", "nara_plan"])
            .agg(dateien=("relpfad", "size"), bytes=("groesse", "sum"), ohne_duplikate=ohne_dup,
                 ampel=("ampel", lambda a: ", ".join(f"{k} {v}" for k, v in a.value_counts().items())), formate=formate3)
            .reset_index().assign(stufe=lambda x: x.nara_risiko.map({"High": 0, "Moderate": 1, "Low": 2, "Unknown": 3}))
            .sort_values(["stufe", "dateien"], ascending=[True, False]).drop(columns="stufe"))
    nara_ampel = mit_nara.groupby(["nara_risiko", "ampel"]).size()
    nara_ampel = {r: {a: int(n) for a, n in nara_ampel[r].items()} for r in nara_ampel.index.get_level_values(0).unique()}

    # ---- Duplikate: überzählig je Art, Platten untereinander, ganze Ordner mehrfach
    arten = [{"art": ARTEN[a], "gruppen": int(t.gruppe_id.nunique()), "ueberzaehlig": int((t.leitdatei == 0).sum()),
              "bytes": int(t.groesse[t.leitdatei == 0].sum())} for a in ARTEN for t in [gruppen[gruppen.art == a]]]
    inhalte = bestand[bestand.sha256.notna() & (bestand.groesse > 0)].drop_duplicates(["platte_id", "sha256"])
    matrix = {}
    if inhalte.platte_id.nunique() > 1:
        paare = inhalte[["platte_id", "sha256"]].merge(inhalte[["platte_id", "sha256"]], on="sha256")
        m = pd.crosstab(paare.platte_id_x, paare.platte_id_y)
        matrix = {a: {b: round(float(m.loc[a, b]) / float(m.loc[a, a]), 4) for b in m.columns} for a in m.index}
    ordner = []
    if len(ordnergruppen):
        for gid, t in ordnergruppen.groupby("gruppe_id"):
            ordner.append({"kopien": len(t), "dateien": int(t.dateien.iloc[0]), "bytes": int(t.bytes.iloc[0]),
                           "ueberzaehlig": int(t.bytes.iloc[0]) * (len(t) - 1),
                           "fundorte": [f"{p}: {o or '(ganze Platte)'}" for p, o in sorted(zip(t.platte_id, t.ordner))]})
        ordner.sort(key=lambda o: -o["ueberzaehlig"])

    # ---- Ordnerbaum je Platte (alle Duplikatarten und nur exakt gleich)
    baum = {p: e for p, (_, e) in ordnerbaum(bestand, gruppen).items()} if len(bestand) else {}

    # ---- Anton: Status je Platte, Bestände in Anton
    anton = {"stand": dict(zip(("stand", "quelle", "nur_platten", "zugang", "eingelesen_am"), anton_stand)) if anton_stand else None}
    if anton_stand:
        st = bestand.assign(s=bestand.anton_status.fillna("noch nicht abgeglichen")).groupby(["platte_id", "s"]).size()
        anton["je_platte"] = {p: {s: int(n) for s, n in st[p].items()} for p in st.index.get_level_values(0).unique()}
        treffer = bestand[bestand.anton_status == "in Anton"]
        b = treffer.assign(bestand=treffer.anton_signatur.fillna("").str.split(" | ", regex=False)).explode("bestand")
        b["bestand"] = b.bestand.str.extract(r"^(\D*\d+)", expand=False)
        anton["bestaende"] = zeilen(b.groupby("bestand").agg(dateien=("relpfad", "size"), inhalte=("md5", "nunique"),
                                                            platten=("platte_id", lambda p: ", ".join(sorted(set(p)))))
                                    .reset_index().sort_values("dateien", ascending=False), 50)

    # ---- Probleme (I8)
    gefuellt = lambda s: s.fillna("").str.strip() != ""
    ohne_mount = lambda s: s.fillna("").str.replace(system.MOUNTPFAD_MUSTER, "(Datei)", regex=True)
    teile = [scanfehler.assign(bereich="Verzeichnis: nicht lesbar", meldung=scanfehler.fehler)]
    for bedingung, bereich, meldung in [
            (gefuellt(alle.hash_fehler), "Prüfsummen: Lesefehler", alle.hash_fehler),
            (gefuellt(alle.sf_fehler), "Formate: Fehler", alle.sf_fehler),
            (gefuellt(alle.sf_warnung), "Formate: Warnung", alle.sf_warnung),
            (alle.viren_befund == "Fund", "Virenscan: Fund", alle.viren_meldung),
            (alle.viren_befund.isin(["nicht geprüft", "Fehler"]), "Virenscan: nicht geprüft", alle.viren_meldung),
            (gefuellt(alle.exif_fehler), "Metadaten: Fehler", alle.exif_fehler),
            (gefuellt(alle.v_fehler) & alle.vorschau.isna(), "Vorschaubilder: keine erzeugt", ohne_mount(alle.v_fehler)),
            (alle.ampel == "rot", "Archivfähigkeit: rot", alle.grund)]:
        teile.append(alle[bedingung].assign(bereich=bereich, meldung=meldung[bedingung]))
    probleme = pd.concat(teile)[["platte_id", "bereich", "relpfad", "meldung"]]
    probleme = probleme[~(probleme.bereich.str.startswith("Archiv") & probleme.meldung.str.contains("Systemdatei", na=False))]
    je_bereich = probleme.groupby(["bereich", "platte_id"]).size()
    probleme_bereiche = [{"bereich": b, "dateien": int(je_bereich[b].sum()), "je_platte": {p: int(n) for p, n in je_bereich[b].items()}}
                         for b in dict.fromkeys(probleme.bereich)]

    return {
        "erstellt": jetzt(), "projekt": P.ordner.name, "dateien_gesamt": int(len(alle)),
        "bestand": {"formatgruppen": formatgruppen, "formate": zeilen(formate.rename(columns={"formatversion": "version"})),
                    "jahre": jahre, "stufen": list(dict.fromkeys(DATUMSSTUFE.values())), "datumsquellen": datumsquellen},
        "archiv": {"eigene": {"bytes_je_platte": je_platte("ampel", "groesse", "sum"), "massnahmen": zeilen(massnahmen),
                              "gruende": zeilen(gruende, 100)},
                   "nara": {"dateien_je_platte": je_platte("nara_stufe", "relpfad", "size"),
                            "bytes_je_platte": je_platte("nara_stufe", "groesse", "sum"),
                            "ampel_je_risiko": nara_ampel, "massnahmen": zeilen(nara)}},
        "duplikate": {"arten": arten, "matrix": matrix, "ordner": ordner[:GRENZE], "ordner_gesamt": len(ordner),
                      "treemap": treemap_daten(alle) if len(alle) else None},
        "ordnerbaum": baum,
        "anton": anton,
        "probleme": {"bereiche": probleme_bereiche, "gesamt": int(len(probleme)),
                     "liste": zeilen(probleme.sort_values(["bereich", "platte_id", "relpfad"]), 1000)},
        "platten": zeilen(platten[["platte_id", "volume_name", "dateisystem", "kapazitaet_bytes", "kopie_von", "etikett_text",
                                   "notiz", "smart_status", "registriert_am"]]),
        "scanlaeufe": zeilen(scanlaeufe), "protokoll": zeilen(protokoll, 200),
    }

"""G Duplikate über alle Datenträger: exakt (SHA-256), Formatvarianten, beinahe gleich (pHash)."""
from html import escape

from IPython.display import HTML

from .basis import *  # noqa: F401,F403
from .anzeige import balken, kacheln, neben

# G0 Funktion: Gruppen speichern
def gruppen_speichern(art, df):
    """df: Spalten platte_id, relpfad, gruppe_id und optional abstand. Ersetzt alle Gruppen dieser Art."""
    if "abstand" not in df:
        df = df.assign(abstand=None)
    with db() as con:
        alt = con.execute("SELECT COUNT(DISTINCT gruppe_id) FROM gruppe WHERE art = ?", (art,)).fetchone()[0]
        con.execute("DELETE FROM gruppe WHERE art = ?", (art,))
        con.executemany("INSERT INTO gruppe (art, gruppe_id, platte_id, relpfad, abstand) VALUES (?,?,?,?,?)",
                        zip([art] * len(df), df.gruppe_id, df.platte_id, df.relpfad, df.abstand))
    protokolliere("G", art, "gruppen", alt, df.gruppe_id.nunique())
    print(f"Gespeichert: {df.gruppe_id.nunique():,} Gruppen „{art}“ mit {len(df):,} Dateien.")


def exakte_duplikate():
    """G1 Exakte Duplikate, Ordnerpaare und ganz mehrfach vorliegende Ordner (Tabelle ordnergruppe)."""
    with db() as con:
        d = pd.read_sql("SELECT platte_id, relpfad, groesse, sha256 FROM datei WHERE sha256 IS NOT NULL AND groesse > 0", con)
    d = nur_aktive(ohne_systemdateien(d))          # herausgenommene Platten zählen nicht mit
    exakt = d[d.duplicated("sha256", keep=False)].assign(gruppe_id=lambda x: "E-" + x.sha256.str[:12])
    gruppen_speichern("exakt", exakt)

    je_inhalt = exakt.groupby("sha256").agg(n=("relpfad", "size"), groesse=("groesse", "first"))
    print(f"{len(je_inhalt):,} Inhalte liegen mehrfach vor, zusammen {len(exakt):,} Dateien; "
          f"überzählig {(je_inhalt.n - 1).sum():,} Dateien, {((je_inhalt.n - 1) * je_inhalt.groesse).sum() / 1e9:.1f} GB.")

    if d.platte_id.nunique() > 1:
        print("\nGemeinsame Inhalte zwischen den Platten (Anzahl verschiedener Inhalte auf beiden):")
        inhalte = d.drop_duplicates(["platte_id", "sha256"])
        paare = inhalte.merge(inhalte, on="sha256")
        zeige(pd.crosstab(paare.platte_id_x, paare.platte_id_y).rename_axis(index=None, columns=None))

    # Welche Ordner teilen sich viele gleiche Inhalte? Hinweis auf kopierte Ordner und Backups.
    d["ordner"] = d.platte_id + ": " + d.relpfad.map(lambda p: os.path.dirname(p) or "(oberste Ebene)")
    dateien_je_ordner = d.groupby("ordner").size()
    ordner = exakt.assign(ordner=d.ordner).drop_duplicates(["sha256", "ordner"])
    ordner = ordner[ordner.groupby("sha256").ordner.transform("size").between(2, 20)]   # sehr häufige Inhalte (Logos) auslassen
    paare = ordner.merge(ordner, on="sha256").query("ordner_x < ordner_y")
    if len(paare):
        top = paare.groupby(["ordner_x", "ordner_y"]).size().sort_values(ascending=False).head(20).rename("gleich").reset_index()
        top["Anteil A %"] = (top.gleich / top.ordner_x.map(dateien_je_ordner) * 100).round(0)
        top["Anteil B %"] = (top.gleich / top.ordner_y.map(dateien_je_ordner) * 100).round(0)
        top[["ordner_x", "ordner_y"]] = top[["ordner_x", "ordner_y"]].map(lambda t: kuerzen(t, 70))
        print("\nOrdnerpaare mit den meisten gleichen Inhalten (100 % = der Ordner liegt vollständig auch im anderen):")
        zeige(top.rename(columns={"ordner_x": "Ordner A", "ordner_y": "Ordner B"}))

    # Ganze Ordner (mit Unterordnern), die mehrfach mit genau denselben Inhalten vorliegen, egal unter welchem Namen
    MIN_DATEIEN_ORDNER = 3       # kleinere Ordner zählen nicht, sonst fluten Ordner mit einer einzigen Datei die Liste
    zeilen = []
    for platte_id, relpfad, sha, groesse in zip(d.platte_id, d.relpfad, d.sha256, d.groesse):
        teile = relpfad.split("/")[:-1]
        for i in range(len(teile) + 1):              # die Datei zählt zu ihrem Ordner und allen darüber
            zeilen.append((platte_id, "/".join(teile[:i]), sha, groesse))
    baum = pd.DataFrame(zeilen, columns=["platte_id", "ordner", "sha256", "groesse"])
    je_ordner = baum.groupby(["platte_id", "ordner"]).agg(
        dateien=("sha256", "size"), bytes=("groesse", "sum"),
        fingerabdruck=("sha256", lambda s: hashlib.sha1("\n".join(sorted(set(s))).encode()).hexdigest())).reset_index()
    je_ordner = je_ordner[je_ordner.dateien >= MIN_DATEIEN_ORDNER]
    kandidaten = []
    for _, teil in je_ordner[je_ordner.duplicated("fingerabdruck", keep=False)].groupby("fingerabdruck"):
        behalten = []                                 # verschachtelte Treffer (Ordner, der nur einen Unterordner hat) zusammenfassen
        for o in teil.assign(tiefe=teil.ordner.str.count("/") + (teil.ordner != "")).sort_values("tiefe").itertuples():
            if not any(b.platte_id == o.platte_id and (b.ordner == "" or o.ordner.startswith(b.ordner + "/")) for b in behalten):
                behalten.append(o)
        if len(behalten) > 1:
            kandidaten.append(behalten)
    mitglieder = {(o.platte_id, o.ordner) for gruppe in kandidaten for o in gruppe}
    ordnergruppen, zeilen = [], []
    for gruppe in kandidaten:
        # nur die oberste Ebene zeigen: steckt jede Kopie in einem Ordner, der selbst mehrfach vorliegt, entfällt die Zeile
        if all(o.ordner and (o.platte_id, os.path.dirname(o.ordner)) in mitglieder for o in gruppe):
            continue
        zeilen += [("O-" + o.fingerabdruck[:12], o.platte_id, o.ordner, o.dateien, o.bytes) for o in gruppe]
        ordnergruppen.append({"kopien": len(gruppe), "dateien": gruppe[0].dateien, "gb": round(gruppe[0].bytes / 1e9, 2),
                              "überzählig gb": round(gruppe[0].bytes * (len(gruppe) - 1) / 1e9, 2),
                              "fundorte": "<br>".join(escape(f"{o.platte_id}: {o.ordner or '(ganze Platte)'}") for o in gruppe)})
    with db() as con:                                 # für I (Dashboard) und Notebook 2
        alt = con.execute("SELECT COUNT(DISTINCT gruppe_id) FROM ordnergruppe").fetchone()[0]
        con.execute("DELETE FROM ordnergruppe")
        con.executemany("INSERT INTO ordnergruppe VALUES (?,?,?,?,?)", zeilen)
    protokolliere("G1", "alle Datenträger", "ordnergruppen", alt, len(ordnergruppen))
    if ordnergruppen:
        ordnergruppen = pd.DataFrame(ordnergruppen).sort_values(["überzählig gb", "kopien"], ascending=False)
        print(f"\nOrdner, die mehrfach vorliegen (ganzer Ordner mit Unterordnern, gleiche Inhalte): {len(ordnergruppen):,} Gruppen, "
              f"zusammen {ordnergruppen['überzählig gb'].sum():.1f} GB überzählig. Die 25 größten:")
        zeige(HTML(ordnergruppen.head(25).to_html(index=False, escape=False)))


def formatvarianten():
    """G2 Formatvarianten derselben Aufnahme (braucht E)."""
    with db() as con:
        v = pd.read_sql("""SELECT d.platte_id, d.relpfad, d.sha256, m.aufnahme, m.hersteller, m.kamera, m.seriennummer
                           FROM datei d JOIN metadaten m USING (platte_id, relpfad)
                           WHERE d.sha256 IS NOT NULL AND length(m.aufnahme) > 10""", con)
    v = nur_aktive(ohne_systemdateien(v))
    geraet = (v.hersteller.fillna("") + " " + v.kamera.fillna("") + " " + v.seriennummer.fillna("")).str.strip()
    stamm = v.relpfad.map(lambda p: Path(p).stem.lower())
    v["schluessel"] = v.aufnahme + " | " + geraet + " | " + stamm
    varianten = v[v.groupby("schluessel").sha256.transform("nunique") > 1].copy()
    varianten["gruppe_id"] = "V-" + varianten.schluessel.map(lambda s: hashlib.sha1(s.encode()).hexdigest()[:12])
    gruppen_speichern("variante", varianten)

    if len(varianten):
        varianten["endung"] = varianten.relpfad.map(lambda p: Path(p).suffix.lower().lstrip(".") or "(ohne)")
        kombi = varianten.groupby("gruppe_id").endung.agg(lambda e: " + ".join(sorted(set(e)))).value_counts().head(15)
        print("Häufigste Kombinationen von Formaten:")
        neben(kombi.to_frame("gruppen"), balken(kombi, "Gruppen je Formatkombination"))
        beispiel = varianten[varianten.gruppe_id.isin(varianten.gruppe_id.drop_duplicates().head(3))]
        zeige(beispiel[["gruppe_id", "platte_id", "relpfad", "aufnahme"]])


def finde(eltern, i):
    while eltern[i] != i:
        eltern[i] = eltern[eltern[i]]
        i = eltern[i]
    return i


def beinahe_gleiche(schwelle=4):
    """G3 Beinahe gleiche Bilder über den pHash (braucht F). schwelle: abweichende Bits von 64;
    0 = gleicher Bildeindruck, bis 4 meist dieselbe Aufnahme, über 8 viele Fehltreffer."""
    with db() as con:
        h = pd.read_sql("SELECT sha256, phash FROM vorschau WHERE phash IS NOT NULL AND einfarbig = 0", con)
    werte = np.array([int(x, 16) for x in h.phash], dtype=np.uint64)
    eltern = list(range(len(werte)))
    naechster = np.full(len(werte), 99)
    abstaende = []
    for start in range(0, len(werte), 256):          # in Blöcken, damit der Speicher reicht
        block = werte[start:start + 256]
        bits = np.bitwise_count(block[:, None] ^ werte[None, :])
        for a, b in zip(*np.nonzero(bits <= schwelle)):
            i, j = start + a, b
            if i < j:
                abstaende.append(int(bits[a, b]))
                eltern[finde(eltern, i)] = finde(eltern, j)
                naechster[i] = min(naechster[i], bits[a, b])
                naechster[j] = min(naechster[j], bits[a, b])
    h["wurzel"] = [finde(eltern, i) for i in range(len(werte))]
    h["abstand"] = naechster
    h = h[h.groupby("wurzel").sha256.transform("size") > 1]
    h["gruppe_id"] = "B-" + h.groupby("wurzel").sha256.transform("min").str[:12]

    with db() as con:
        dateien = pd.read_sql("SELECT platte_id, relpfad, sha256 FROM datei WHERE sha256 IS NOT NULL", con)
    dateien = nur_aktive(ohne_systemdateien(dateien))
    beinahe = dateien.merge(h[["sha256", "gruppe_id", "abstand"]], on="sha256")
    gruppen_speichern("beinahe", beinahe)

    if abstaende:
        print("Bildpaare je Abstand (0 = gleicher Bildeindruck, z. B. neu gespeichert):")
        zeige(pd.Series(abstaende).value_counts().sort_index().rename_axis("abweichende Bits").to_frame("paare").T)
        groesse = h.groupby("gruppe_id").size().sort_values(ascending=False)
        if (groesse > 30).any():
            print(f"⚠ {(groesse > 30).sum()} sehr große Gruppen (über 30 Inhalte): oft Grafiken mit wenig Struktur. "
                  "Bei Bedarf die Schwelle senken.")
        print("\nBeispiele zum Prüfen der Schwelle (je Zeile eine Gruppe, Zahl = abweichende Bits zum nächsten Bild):")
        erste = dateien.drop_duplicates("sha256").set_index("sha256").relpfad
        for gid in list(groesse.index[:3]) + list(groesse.index[-3:]):
            teil = h[h.gruppe_id == gid].head(6)
            kacheln([(s, f"{a} · {kuerzen(erste.get(s, ''), 50)}") for s, a in zip(teil.sha256, teil.abstand)], breite=130)


def gruppen_ueberblick():
    """G4 Überblick über alle Gruppen."""
    with db() as con:
        g = pd.read_sql("SELECT g.*, d.groesse FROM gruppe g JOIN datei d USING (platte_id, relpfad)", con)
    zeige(g.groupby("art").agg(gruppen=("gruppe_id", "nunique"), dateien=("relpfad", "size"),
                                 platten=("platte_id", "nunique"), gb=("groesse", lambda s: round(s.sum() / 1e9, 1)))
             .reindex(["exakt", "variante", "beinahe"]).dropna(how="all"))
    print("Leitdateien wählt H. Nach G also H ausführen.")

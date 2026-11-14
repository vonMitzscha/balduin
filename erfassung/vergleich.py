"""C2/C3 Plattenvergleich über Name + Größe, Bestätigung mit Prüfsummen-Stichprobe, Kopie vermerken."""
from .basis import *  # noqa: F401,F403


# C2a Funktionen für den Vergleich
def vergleichsdaten():
    with db() as con:
        df = pd.read_sql("SELECT platte_id, relpfad, name, groesse FROM schnellscan WHERE groesse >= ?",
                         con, params=(MIN_GROESSE_VERGLEICH,))
    df = df[~df.name.isin(SYSTEMDATEIEN) & ~df.name.str.startswith("._")].copy()
    df["schluessel"] = df.name + "|" + df.groesse.astype(str)
    df["pfadschluessel"] = df.relpfad + "|" + df.groesse.astype(str)
    return df


def einstufen(ab, ba, gleiche_pfade):
    if ab >= 0.99 and ba >= 0.99:
        return "identisch, gleiche Ordnerstruktur" if gleiche_pfade >= 0.95 else "identischer Inhalt, andere Ordnerstruktur"
    if ab >= 0.95:
        return "A ist in B enthalten"
    if ba >= 0.95:
        return "B ist in A enthalten"
    if max(ab, ba) >= 0.30:
        return "starke Überschneidung"
    if max(ab, ba) >= 0.05:
        return "teilweise Überschneidung"
    return "unabhängig"


def plattenvergleich(df):
    platten = sorted(df.platte_id.unique())
    schluessel = {p: set(df.loc[df.platte_id == p, "schluessel"]) for p in platten}
    pfade = {p: set(df.loc[df.platte_id == p, "pfadschluessel"]) for p in platten}
    zeilen = []
    for a in platten:
        da = df[df.platte_id == a]
        for b in platten:
            if a == b:
                continue
            treffer = da.schluessel.isin(schluessel[b])
            zeilen.append({
                "A": a, "B": b, "dateien_A": len(da),
                "anteil_A_in_B": treffer.mean(),
                "anteil_bytes": da.groesse[treffer].sum() / da.groesse.sum(),
                "gleiche_pfade": da.pfadschluessel.isin(pfade[b]).mean(),
            })
    gerichtet = pd.DataFrame(zeilen)
    matrix = gerichtet.pivot(index="A", columns="B", values="anteil_A_in_B")

    paare = []
    for i, a in enumerate(platten):
        for b in platten[i + 1:]:
            ab = gerichtet[(gerichtet.A == a) & (gerichtet.B == b)].iloc[0]
            ba = gerichtet[(gerichtet.A == b) & (gerichtet.B == a)].iloc[0]
            paare.append({
                "A": a, "B": b,
                "A_in_B": ab.anteil_A_in_B, "B_in_A": ba.anteil_A_in_B,
                "gleiche_pfade": max(ab.gleiche_pfade, ba.gleiche_pfade),
                "einstufung": einstufen(ab.anteil_A_in_B, ba.anteil_A_in_B,
                                        max(ab.gleiche_pfade, ba.gleiche_pfade)),
            })
    return matrix, pd.DataFrame(paare), gerichtet


def ordner_auf_anderer_platte(df, a, b, tiefe=2, min_dateien=20, schwelle=0.95):
    """Ordner von A (bis zur angegebenen Tiefe), deren Dateien fast vollständig auch auf B liegen."""
    da = df[df.platte_id == a].copy()
    da["ordner"] = da.relpfad.map(lambda p: "/".join(p.split("/")[:-1][:tiefe]) or "(oberste Ebene)")
    da["auf_B"] = da.schluessel.isin(set(df.loc[df.platte_id == b, "schluessel"]))
    erg = da.groupby("ordner").agg(dateien=("auf_B", "size"), anteil_auf_B=("auf_B", "mean"),
                                   gb=("groesse", lambda s: round(s.sum() / 1e9, 2)))
    return erg[(erg.dateien >= min_dateien) & (erg.anteil_auf_B >= schwelle)].sort_values("gb", ascending=False)


def platten_vergleichen():
    """Vergleicht alle gescannten Platten (C2b) und zeigt bei teilweiser Überschneidung gemeinsame Ordner (C2c)."""
    vdf = vergleichsdaten()
    if vdf.platte_id.nunique() < 2:
        print("Für einen Vergleich müssen mindestens zwei Datenträger gelesen sein.")
    else:
        matrix, paare, gerichtet = plattenvergleich(vdf)
        print("Anteil der Dateien von A (Zeile), die auch auf B (Spalte) liegen:")
        try:
            zeige(matrix.style.format("{:.0%}", na_rep="–").background_gradient(cmap="Blues", axis=None, vmin=0, vmax=1))
        except ImportError:   # ohne matplotlib ohne Farben
            zeige(matrix.style.format("{:.0%}", na_rep="–"))
        zeige(paare.style.format({"A_in_B": "{:.1%}", "B_in_A": "{:.1%}", "gleiche_pfade": "{:.1%}"}))

        stempel = datetime.now().strftime("%Y-%m-%d_%H%M")
        paare.to_csv(P.berichte / f"plattenvergleich_{stempel}.csv", index=False)
        matrix.to_csv(P.berichte / f"plattenvergleich_matrix_{stempel}.csv")
        print("Gespeichert in", P.berichte)
    if vdf.platte_id.nunique() >= 2:
        teilweise = gerichtet[(gerichtet.anteil_A_in_B >= 0.05) & (gerichtet.anteil_A_in_B < 0.99)]
        for z in teilweise.itertuples():
            ordner = ordner_auf_anderer_platte(vdf, z.A, z.B)
            if len(ordner):
                print(f"\nOrdner von {z.A}, die (fast) vollständig auch auf {z.B} liegen:")
                zeige(ordner.head(20).style.format({"anteil_auf_B": "{:.0%}"}))


STICHPROBE = 500          # Anzahl Dateien je Paar (C3)


def sha256(pfad, block=1024 * 1024):
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        while stueck := f.read(block):
            h.update(stueck)
    return h.hexdigest()


def sha256_auf_platte(wurzel, relpfad, block=1024 * 1024):
    """Wie sha256, aber für einen Pfad der Platte, auch in einer Archivdatei (Entscheidung 06.11.2026)."""
    from .platte import oeffne
    h = hashlib.sha256()
    with oeffne(wurzel, relpfad) as f:
        while stueck := f.read(block):
            h.update(stueck)
    return h.hexdigest()


def stichprobe_hashen(paar, platte_id, wurzel, n=STICHPROBE):
    paar = tuple(sorted(paar))
    paar_id = "|".join(paar)
    df = vergleichsdaten()
    gemeinsam = sorted(set(df.loc[df.platte_id == paar[0], "schluessel"])
                       & set(df.loc[df.platte_id == paar[1], "schluessel"]))
    auswahl = set(random.Random(paar_id).sample(gemeinsam, min(n, len(gemeinsam))))
    eigene = (df[(df.platte_id == platte_id) & df.schluessel.isin(auswahl)]
              .sort_values("relpfad").drop_duplicates("schluessel"))
    ergebnisse = []
    for i, z in enumerate(eigene.itertuples(), 1):
        try:
            h = sha256_auf_platte(wurzel, z.relpfad)
        except OSError as e:
            h = "FEHLER: " + repr(e)
        ergebnisse.append((paar_id, platte_id, z.name, z.groesse, z.relpfad, h, jetzt()))
        if i % 25 == 0:
            print(f"{i}/{len(eigene)} gehasht …", end="\r")
    with db() as con:
        con.executemany("INSERT OR REPLACE INTO stichprobe_hash VALUES (?,?,?,?,?,?,?)", ergebnisse)
    print(f"{len(ergebnisse)} Dateien von {platte_id} gehasht (Paar {paar_id}).")


def stichprobe_auswerten(paar):
    paar = tuple(sorted(paar))
    with db() as con:
        h = pd.read_sql("SELECT * FROM stichprobe_hash WHERE paar = ?", con, params=("|".join(paar),))
    a, b = h[h.platte_id == paar[0]], h[h.platte_id == paar[1]]
    if a.empty or b.empty:
        fehlt = [p for p, t in zip(paar, (a, b)) if t.empty]
        print("Noch nicht gehasht:", ", ".join(fehlt))
        return None
    m = a.merge(b, on=["name", "groesse"], suffixes=("_A", "_B"))
    m["gleich"] = m.sha256_A == m.sha256_B
    print(f"{paar[0]} ↔ {paar[1]}: {m.gleich.sum()} von {len(m)} Stichproben bitgleich ({m.gleich.mean():.1%}).")
    return m.loc[~m.gleich, ["name", "groesse", "relpfad_A", "relpfad_B", "sha256_A", "sha256_B"]]


def kopie_vermerken(kopie_von):
    """Vermerkt bestätigte Kopien, z. B. {"HD04": "HD01"} = HD04 ist eine Kopie von HD01."""
    for kopie, original in kopie_von.items():
        with db() as con:
            alt = con.execute("SELECT kopie_von FROM platte WHERE platte_id = ?", (kopie,)).fetchone()
            con.execute("UPDATE platte SET kopie_von = ? WHERE platte_id = ?", (original, kopie))
        protokolliere("C3", kopie, "kopie_von", alt[0] if alt else "", original)
        print(f"{kopie} als Kopie von {original} vermerkt.")

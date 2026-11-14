"""V10 Verwandte Ordner: Ordnerpaare, die vermutlich zum selben Thema gehören, mit Grund und Score (Messung an
einem Bestand von rund 85.000 Dateien, 03.11.2026). Nur allgemeine Signale, Schwellen fest und eher genau:

- duplikate   mind. MIN_GEMEINSAM gleiche Inhalte (exakt, Formatvariante, beinahe gleich aus G); Gruppen, die über mehr
              als MAX_ORDNER Ordner streuen (Logos, Schriften), zählen nicht
- tag_kamera  mind. MIN_GEMEINSAM Aufnahmen vom selben Tag mit derselben Kameraseriennummer
- name        Ordnernamen teilen mind. zwei seltene Wörter (in höchstens SELTEN Ordnern), gewichtete Überschneidung
              ≥ NAME_SCHWELLE; Geschwisterordner zählen nicht (das ist schon die Ordnung der Platte)

Ein Ordner zählt, wenn darunter direkt Dateien liegen. Mindestens eine Seite jedes Paars hat Dateien im Umfang; die
andere darf kassiert sein (dann nur Kontext). Gleichnamige Arbeitsunterordner, die es oft gibt („Document fonts“,
„Links“), verbinden nicht.
"""
import itertools
import math
import time
from collections import Counter, defaultdict

from erfassung.basis import db, fortschritt, ist_systemdatei, zeige
from .gemeinsam import arbeitsordner, datum_deutsch, elternordner, name_von, norm, stand_schreiben, umfang, woerter

MIN_GEMEINSAM = 2
MAX_ORDNER = 20
SELTEN = 30
NAME_SCHWELLE = 0.6
GLEICHER_NAME_HAEUFIG = 10


def namenswoerter(name):
    """Inhaltliche Wörter eines Ordnernamens (normalisiert, ohne Ziffern, Arbeitsordner und kurze Wörter)."""
    return {norm(w) for w in woerter(name) if len(w) >= 3 and not any(z.isdigit() for z in w) and not arbeitsordner(w)}


def verwandte_finden(umfang_art=""):
    beginn = time.time()
    dateien_umfang = umfang()
    with db() as con:
        ordner_je_datei = {(p, r): (p, elternordner(r)) for p, r in con.execute(
            "SELECT platte_id, relpfad FROM datei WHERE groesse > 0") if not ist_systemdatei(r)}
        gruppen = defaultdict(list)
        for art, gid, p, r in con.execute("SELECT art, gruppe_id, platte_id, relpfad FROM gruppe"):
            if (p, r) in ordner_je_datei:
                gruppen[(art, gid)].append(ordner_je_datei[(p, r)])
        aufnahmen = defaultdict(list)
        for p, r, tag, sn, kamera in con.execute(
                "SELECT platte_id, relpfad, substr(aufnahme, 1, 10), seriennummer, kamera FROM metadaten "
                "WHERE aufnahme IS NOT NULL AND seriennummer IS NOT NULL AND seriennummer != ''"):
            if (p, r) in ordner_je_datei:
                aufnahmen[(tag, sn, kamera or "")].append(ordner_je_datei[(p, r)])
    im_umfang = {ordner_je_datei.get(k, (k[0], elternordner(k[1]))) for k in dateien_umfang}
    alle_ordner = set(ordner_je_datei.values())
    name_zahl = Counter(norm(name_von(o)) for _, o in alle_ordner)

    def zaehlt(a, b):
        if a == b or (a not in im_umfang and b not in im_umfang):
            return False
        na, nb = norm(name_von(a[1])), norm(name_von(b[1]))
        return not (na == nb and name_zahl[na] > GLEICHER_NAME_HAEUFIG)

    paare = {}                                            # (a, b, grund) -> (score, beleg)
    fortschritt(0.2, "Duplikate")
    dup = Counter()
    for ords in gruppen.values():
        ords = sorted(set(ords))
        if 2 <= len(ords) <= MAX_ORDNER:
            for a, b in itertools.combinations(ords, 2):
                if zaehlt(a, b):
                    dup[(a, b)] += 1
    for (a, b), n in dup.items():
        if n >= MIN_GEMEINSAM:
            paare[(a, b, "duplikate")] = (round(min(0.99, 0.6 + 0.1 * math.log2(n)), 2), f"{n} gleiche Inhalte")
    fortschritt(0.5, "Tag und Kamera")
    tk = defaultdict(Counter)
    for (tag, sn, kamera), ords in aufnahmen.items():
        zahl = Counter(ords)
        if len(zahl) < 2 or len(zahl) > MAX_ORDNER:
            continue
        for a, b in itertools.combinations(sorted(zahl), 2):
            if zaehlt(a, b) and min(zahl[a], zahl[b]) >= 1:
                tk[(a, b)][(tag, kamera)] += min(zahl[a], zahl[b])
    for (a, b), tage in tk.items():
        n = sum(tage.values())
        if n >= MIN_GEMEINSAM:
            (tag, kamera), _ = tage.most_common(1)[0]
            paare[(a, b, "tag_kamera")] = (0.8, f"{n} Aufnahmen am {datum_deutsch(tag[:10].replace(':', '-'))}"
                                                + (f", {kamera}" if kamera else "") + " (gleiche Seriennummer)")
    fortschritt(0.75, "Ordnernamen")
    namen = {o: namenswoerter(name_von(o[1])) for o in alle_ordner if o[1]}
    df = Counter(w for s in namen.values() for w in s)
    idf = {w: math.log(len(namen) / n) for w, n in df.items()}
    index = defaultdict(set)
    for o, s in namen.items():
        for w in s:
            if df[w] <= SELTEN:
                index[w].add(o)
    kandidaten = set()
    for os_ in index.values():
        for a, b in itertools.combinations(sorted(os_), 2):
            kandidaten.add((a, b))
    for a, b in kandidaten:
        if elternordner(a[1]) == elternordner(b[1]) and a[0] == b[0]:
            continue
        gemeinsam = {w for w in namen[a] & namen[b] if df[w] <= SELTEN}
        if len(gemeinsam) < 2 or not zaehlt(a, b):
            continue
        j = sum(idf[w] for w in namen[a] & namen[b]) / sum(idf[w] for w in namen[a] | namen[b])
        if j >= NAME_SCHWELLE:
            paare[(a, b, "name")] = (round(0.9 * j, 2), "gleiche Wörter im Namen: " + ", ".join(sorted(gemeinsam)))
    with db() as con:
        con.execute("DELETE FROM verwandt")
        con.executemany("INSERT INTO verwandt VALUES (?,?,?,?,?,?,?)",
                        [(a[0], a[1], b[0], b[1], grund, s, beleg) for (a, b, grund), (s, beleg) in paare.items()])
    beteiligt = {o for a, b, _ in paare for o in (a, b)} & im_umfang
    gruende = Counter(g for _, _, g in paare)
    fortschritt(1, f"{len(paare):,} Paare")
    zeige(f"V10: {len(paare):,} Ordnerpaare ({dict(gruende)}), {len(beteiligt):,} von {len(im_umfang):,} Ordnern mit Verwandten")
    mit = sum(1 for k in dateien_umfang if ordner_je_datei.get(k) in beteiligt)
    stand_schreiben("V10", dateien_umfang, mit, {"paare": len(paare), "gruende": dict(gruende),
                                                 "ordner": len(im_umfang), "ordner_mit": len(beteiligt)}, beginn, umfang_art)
    return {"paare": len(paare)}

"""V5 Pfade und Namen: Datum, Wörter und Ordnertitel aus Ordner- und Dateinamen, nur allgemeine Muster
(keine bestandsbezogenen Regeln, Entscheidung 03.11.2026). Jeder Vorschlag trägt den Ordnernamen als Beleg.

Ergebnis je Ordner mit Dateien im Umfang:
- titel     Wörter des Ordnernamens ohne Datum, Zähler und Arbeitsordner, dazu das Jahr („Technology Day 2007“)
- zeitraum  Datum aus dem Ordnernamen (Tag, Monat, Jahr oder Jahrespaar) als [von, bis, ca]
- begriff   Wörter und Wortpaare als Kandidaten für den Normdatenabgleich (V8, nicht angezeigt)
"""
import json
import re
import time

from erfassung.basis import fortschritt, zeige
from .gemeinsam import (FUELLWOERTER, arbeitsordner, datum_deutsch, name_von, norm, ordner_mit_dateien,
                        stand_schreiben, umfang, vorschlaege_ersetzen, woerter)

J = r"(19[4-9]\d|20[0-4]\d)"                     # Jahr 1940–2049
M = r"(0[1-9]|1[0-2])"
T = r"(0[1-9]|[12]\d|3[01])"
S = r"[-_. ]?"
# (Muster, Genauigkeit, Score); Reihenfolge: genaueste zuerst
DATUMSMUSTER = [
    (re.compile(rf"(?<!\d){J}{S}{M}{S}{T}(?!\d)"), "tag", 0.75),
    (re.compile(rf"(?<!\d){T}[-_.]{M}[-_.]{J}(?!\d)"), "tag_rueck", 0.75),
    (re.compile(rf"(?<!\d){J}[-_.]{M}(?![\d])"), "monat", 0.6),
    (re.compile(rf"(?<!\d){J}\s*[-_–]\s*{J}(?!\d)"), "jahre", 0.55),
    (re.compile(rf"(?<!\d){J}[-_/]([0-9]{{2}})(?!\d)"), "jahrespaar", 0.5),     # 2012_13
    (re.compile(rf"(?<!\d){J}(?!\d)"), "jahr", 0.5),
]
ZAEHLER = re.compile(r"^(img|dsc|dscn|dscf|pict|mvi|cimg|imag|mg|p|k|nr|no)?\d+[a-z]?$", re.I)


def datum_finden(text):
    """Erstes Datum im Text: (von, bis, genauigkeit, score, Fundstelle) mit ISO-Teilen (2007-09-27, 2007-09, 2007)
    oder None. Ein Tag muss es geben (31.02. nicht)."""
    for muster, art, score in DATUMSMUSTER:
        m = muster.search(text)
        if not m:
            continue
        if art == "tag":
            j, mo, t = m[1], m[2], m[3]
        elif art == "tag_rueck":
            t, mo, j = m[1], m[2], m[3]
        if art in ("tag", "tag_rueck"):
            try:
                time.strptime(f"{j}-{mo}-{t}", "%Y-%m-%d")
            except ValueError:
                continue
            iso = f"{j}-{mo}-{t}"
            return iso, iso, "Tag", score, m.span()
        if art == "monat":
            return f"{m[1]}-{m[2]}", f"{m[1]}-{m[2]}", "Monat", score, m.span()
        if art == "jahre" and m[1] < m[2]:
            return m[1], m[2], "Jahre", score, m.span()
        if art == "jahrespaar":
            zweites = int(m[1][:2] + m[2])
            if zweites == int(m[1]) + 1:
                return m[1], str(zweites), "Jahre", score, m.span()
            continue
        if art == "jahr":
            return m[1], m[1], "Jahr", score, m.span()
    return None


def name_zerlegen(name):
    """Ordnername → (Datum oder None, inhaltliche Wörter in Originalschreibung)."""
    datum = datum_finden(name)
    rest = name
    if datum:
        a, b = datum[4]
        rest = name[:a] + " " + name[b:]
    inhalt = []
    for w in woerter(rest):
        if ZAEHLER.match(w) or w.isdigit() or arbeitsordner(w) or len(w) < 2:
            continue
        inhalt.append(w)
    return datum, inhalt


def titel_aus(name):
    """Titelvorschlag aus einem Ordnernamen oder None: Wörter, erstes groß, dazu das Jahr, wenn eines erkannt ist."""
    datum, inhalt = name_zerlegen(name)
    if not inhalt or all(norm(w) in FUELLWOERTER for w in inhalt) or not any(len(w) >= 4 for w in inhalt):
        return None
    titel = " ".join(inhalt)
    titel = titel[0].upper() + titel[1:]
    jahr = datum[0][:4] if datum else ""
    if datum and datum[0][:4] != datum[1][:4]:
        jahr = f"{datum[0][:4]}–{datum[1][:4]}"
    if jahr and jahr not in titel:
        titel += f" {jahr}"
    score = min(0.5 + 0.1 * len(inhalt), 0.8)
    return titel, score


def begriffe_aus(name):
    """Kandidaten für den Normdatenabgleich: einzelne Wörter (ab 3 Buchstaben, keine Füllwörter), Wortpaare und
    -tripel (Personen mit zwei Vornamen, Entscheidung 04.11.2026)."""
    _, inhalt = name_zerlegen(name)
    einzeln = [w for w in inhalt if len(w) >= 3 and norm(w) not in FUELLWOERTER and not any(z.isdigit() for z in w)]
    paare = [f"{a} {b}" for a, b in zip(einzeln, einzeln[1:])]
    tripel = [f"{a} {b} {c}" for a, b, c in zip(einzeln, einzeln[1:], einzeln[2:])]
    return list(dict.fromkeys(einzeln + paare + tripel))


def pfade_und_namen(umfang_art=""):
    """V5 für alle Ordner über den Dateien im Umfang."""
    beginn = time.time()
    dateien = umfang()
    ordner = ordner_mit_dateien(dateien)
    zeilen, mit_titel, mit_datum = [], 0, 0
    for i, ((p, o), n) in enumerate(sorted(ordner.items())):
        if i % 500 == 0:
            fortschritt(i / max(len(ordner), 1), f"{i:,} von {len(ordner):,} Ordnern")
        if not o:
            continue                                   # die Platte selbst hat keinen Namen im Pfad
        name = name_von(o)
        t = titel_aus(name)
        if t:
            zeilen.append((p, o, "titel", t[0], "Ordnername", t[1], name))
            mit_titel += 1
        datum = datum_finden(name)
        if datum:
            von, bis, genau, score, _ = datum
            wert = json.dumps([datum_deutsch(von), datum_deutsch(bis) if bis != von else "", False], ensure_ascii=False)
            zeilen.append((p, o, "zeitraum", wert, f"Ordnername ({genau})", score, name))
            mit_datum += 1
        for b in begriffe_aus(name):
            zeilen.append((p, o, "begriff", b, "Ordnername", 0.5, name))
    n = vorschlaege_ersetzen("V5", zeilen)
    fortschritt(1, f"{len(ordner):,} Ordner")
    zeige(f"V5: {len(ordner):,} Ordner, {mit_titel:,} mit Titelvorschlag, {mit_datum:,} mit Datum; {n:,} Vorschläge")
    stand_schreiben("V5", dateien, mit_titel, {"ordner": len(ordner), "titel": mit_titel, "datum": mit_datum,
                                               "vorschlaege": n}, beginn, umfang_art)
    return {"ordner": len(ordner), "titel": mit_titel, "datum": mit_datum}

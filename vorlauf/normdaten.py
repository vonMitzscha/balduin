"""V8 Normdaten abgleichen (mit V9 „neue Normdaten“ als Liste in den Kennzahlen).

1. Anton-Vokabular holen: Schlagworte, Orte, Akteur:innen über die öffentliche API (ohne Token, nur lesend), in
   anton_begriff zwischengespeichert, höchstens alle VOKABULAR_TAGE neu. Eine Seite, die Anton nicht ausliefert
   (Schlagwort 9803 → HTTP 500, docs/plan.md „Offen“), wird Eintrag für Eintrag nachgeholt; Fehlende werden gezählt.
2. Kandidaten aus V5 (Wörter der Ordnernamen) und V7 (Urheber:in, Ort, Schlagworte, GPS; Wörter aus eingebettetem
   Titel und Beschreibung wie Pfadwörter) zuordnen:
   gelernt (Bestätigung in der Erschließung) > exakt > Alternativname > Mehrzahl/Endung > ähnlich ab 0,85 (nur für
   Werte aus den Metadaten; Wörter aus Pfaden nur exakt, sonst zu viel Rauschen). GPS: nächster Anton-Ort mit
   Koordinaten bis GPS_KM. Ausschlüsse aus der Erschließung gelten. Personen finden sich als „Nachname, Vorname(n)“
   und „Vorname(n) Nachname“ gegenseitig (Namensteile ohne Reihenfolge, Entscheidung 04.11.2026). Eingebettete
   Schlagworte zusätzlich gegen Personen und Orte (nur exakt). Urheber- und Ortswerte ohne Vorsatz („© “, „Foto: “);
   findet der ganze Wert nichts, wird er an Komma, Semikolon, Schrägstrich zerlegt und jeder Teil als Person und Ort
   gesucht („nik hunger, zuerich“ → Hunger, Nik + Zürich, Entscheidung 05.11.2026).
3. Vorschläge (schritt V8) für schlagwort, ort, akteur mit Anton-ID; Werte aus den Metadaten ohne Treffer als „neu“
   (ohne Anton-ID). Häufige Pfadwörter ohne Treffer stehen als Liste in den Kennzahlen (V9).
"""
import json
import math
import re
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from difflib import SequenceMatcher, get_close_matches

from erfassung.basis import P, db, fortschritt, jetzt, zeige
from .gemeinsam import FUELLWOERTER, norm, stand_schreiben, umfang, vorschlaege_ersetzen, woerter

VOKABULAR_TAGE = 7
JE_SEITE = 200
GPS_KM = 25
AEHNLICH = 0.85
ARTEN = {"keyword": ("keywords", "schlagwort"), "place": ("places", "ort"), "actor": ("actors", "akteur")}


# ---------- 1 Vokabular ----------

def anton_lesen(pfad, versuche=2):
    """Öffentliche Anton-API, ohne Token (nur das öffentliche Vokabular)."""
    anfrage = urllib.request.Request(P.anton_url + "/api" + pfad, headers={"Accept": "application/json"})
    for versuch in range(versuche):
        try:
            with urllib.request.urlopen(anfrage, timeout=120) as antwort:
                return json.load(antwort)
        except urllib.error.HTTPError:
            if versuch == versuche - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if versuch == versuche - 1:
                raise
        time.sleep(3 * (versuch + 1))


def eintrag_zeile(art, e, zeit):
    """Ein Eintrag der API → Zeile für anton_begriff."""
    alternativ = [*e.get("alternative_names", []), *e.get("variants", []), *e.get("abbreviations", [])]
    alternativ = [a if isinstance(a, str) else (a.get("name") or a.get("label") or "") for a in alternativ]
    quellen = {r.get("provider"): r.get("resource_id") for r in e.get("resources") or [] if isinstance(r, dict)}
    breite = laenge = None
    m = re.match(r"POINT\(\s*(-?[\d.]+)\s+(-?[\d.]+)\s*\)", e.get("location") or "")
    if m:                                                 # Anton: POINT(Breite Länge)
        breite, laenge = float(m[1]), float(m[2])
    name = e.get("label") or e.get("name") or ""
    voll = e.get("fullname") or name
    typ = e.get("authority_type") or e.get("place_type") or e.get("type") or ""
    if art == "place" and e.get("city") and norm(e["city"]) != norm(name):
        alternativ.append(e["city"])
    return (art, e["id"], name, voll, typ, json.dumps([a for a in alternativ if a], ensure_ascii=False),
            quellen.get("wikidata"), quellen.get("gnd"), breite, laenge, zeit)


def vokabular_holen(neu=False):
    """Holt das Vokabular, wenn es fehlt oder älter als VOKABULAR_TAGE ist. Ergebnis: {art: Anzahl}, fehlende."""
    with db() as con:
        alt = con.execute("SELECT MIN(geholt_am), COUNT(*) FROM anton_begriff").fetchone()
    if not neu and alt[1] and alt[0] and time.time() - time.mktime(time.strptime(alt[0][:19], "%Y-%m-%dT%H:%M:%S")) < VOKABULAR_TAGE * 86400:
        zeige(f"Anton-Vokabular vom {alt[0][:10]} ({alt[1]:,} Begriffe) genügt.")
        return {}, 0
    zeit, zahlen, fehlend = jetzt(), {}, 0
    for art, (endpunkt, _) in ARTEN.items():
        zeilen, seite, letzte = [], 1, 1
        while seite <= letzte:
            fortschritt(0.05 + 0.25 * list(ARTEN).index(art) / 3, f"Anton-Vokabular {endpunkt} · Seite {seite} von {letzte}")
            try:
                d = anton_lesen(f"/{endpunkt}?page={seite}&perPage={JE_SEITE}")
                letzte = d["meta"]["last_page"]
                zeilen += [eintrag_zeile(art, e, zeit) for e in d["data"]]
            except urllib.error.HTTPError as f:
                if f.code < 500:
                    raise
                # Seite einzeln nachholen: Einträge (seite-1)*JE_SEITE+1 … seite*JE_SEITE als Seiten mit perPage=1
                for nr in range((seite - 1) * JE_SEITE + 1, seite * JE_SEITE + 1):
                    try:
                        d1 = anton_lesen(f"/{endpunkt}?page={nr}&perPage=1", versuche=1)
                    except urllib.error.HTTPError:
                        fehlend += 1
                        continue
                    if not d1["data"]:
                        break
                    zeilen += [eintrag_zeile(art, e, zeit) for e in d1["data"]]
            seite += 1
        with db() as con:
            con.execute("DELETE FROM anton_begriff WHERE art = ?", (art,))
            con.executemany("INSERT OR REPLACE INTO anton_begriff VALUES (?,?,?,?,?,?,?,?,?,?,?)", zeilen)
        zahlen[art] = len(zeilen)
    zeige(f"Anton-Vokabular geholt: {zahlen}" + (f", {fehlend} Einträge lieferte Anton nicht aus" if fehlend else ""))
    return zahlen, fehlend


# ---------- 2 Zuordnen ----------

def formen(name, art):
    """Vergleichsformen eines Anton-Begriffs: Name ohne Klammerzusatz, bei Personen auch „Vorname Nachname“."""
    n = norm(re.sub(r"\s*\(.*?\)\s*", " ", name or "")).strip(" ,")
    erg = {n} if n else set()
    if art == "actor" and "," in n:
        nach, _, vor = n.partition(",")
        erg.add(f"{vor.strip()} {nach.strip()}")
    return erg


def namensteile(n):
    """Personen ohne Reihenfolge: „Müller, Hans Peter“ = „Hans Peter Müller“ (nur ab zwei Teilen)."""
    teile = sorted(x for x in re.split(r"[\s,]+", n) if x)
    return " ".join(teile) if len(teile) >= 2 else ""


# Namenszusätze („Gogh, Vincent van“), Zusätze hinter dem Nachnamen, Firmenendungen (bleiben unverändert)
NAMENSZUSAETZE = {"von", "van", "de", "der", "den", "di", "da", "du", "del", "della", "zu", "zum", "zur", "vom", "ten", "ter", "le", "la"}
NACHSAETZE = {"jr", "jr.", "jun", "jun.", "sr", "sr.", "sen", "sen.", "ii", "iii", "iv"}
FIRMA = {"ag", "gmbh", "sa", "sàrl", "sarl", "ltd", "ltd.", "inc", "inc.", "co", "co.", "kg", "ohg", "llc", "plc", "corp",
         "corp.", "ug", "e.v.", "verein", "stiftung", "studio", "atelier", "verlag", "agentur", "gruppe", "group"}


def nachname_vorname(name):
    """Personenname als „Nachname, Vorname(n)“ wie in Anton und GND: „Vincent van Gogh“ → „Gogh, Vincent van“.
    Unverändert: Werte mit Komma, einzelne Wörter, Ziffern oder Sonderzeichen, Firmen."""
    n = re.sub(r"\s+", " ", (name or "").strip())
    w = n.split(" ")
    if ("," in n or len(w) < 2 or any(c.isdigit() or c in "&+@/()" for c in n)
            or any(x.lower() in FIRMA for x in w)):
        return n
    if n == n.lower():                                   # „erika muster“ → „Erika Muster“, Zusätze bleiben klein
        w = [x if x in NAMENSZUSAETZE else x[:1].upper() + x[1:] for x in w]
    nach = [w.pop()]
    if w and nach[0].lower() in NACHSAETZE:              # „King Jr.“ bleibt zusammen
        nach.insert(0, w.pop())
    if not w:
        return n
    zusatz = []
    while len(w) > 1 and w[-1].lower() in NAMENSZUSAETZE:
        zusatz.insert(0, w.pop())
    return f"{' '.join(nach)}, {' '.join(w + zusatz)}"


def text_begriffe(text, hoechstens=60):
    """Wörter (ab 3 Buchstaben, ohne Füllwörter und Ziffern), Wortpaare und -tripel aus eingebettetem Titel oder
    Beschreibung: Kandidaten wie die Wörter der Ordnernamen (nur exakt)."""
    w = [x for x in woerter(text)[:hoechstens] if len(x) >= 3 and norm(x) not in FUELLWOERTER and not any(z.isdigit() for z in x)]
    return list(dict.fromkeys(w + [f"{a} {b}" for a, b in zip(w, w[1:])] + [f"{a} {b} {c}" for a, b, c in zip(w, w[1:], w[2:])]))


# Vorsätze vor Namen in Urheberfeldern („© “, „Foto: “, „Photo by “)
VORSATZ = re.compile(r"^\s*(?:©|\(c\)|copyright|fotos?|photos?|fotograf(?:in)?|photograph(?:er|y)?|bild|aufnahme)?"
                     r"\s*(?:by|von)?\s*[:©]?\s*", re.I)


def ohne_vorsatz(wert):
    return VORSATZ.sub("", wert or "", count=1).strip() or (wert or "").strip()


def teile(wert):
    """Angaben in einem Metadatenwert, getrennt durch Komma, Semikolon, Schrägstrich oder „ - “."""
    return [t.strip() for t in re.split(r"\s*[,;/|]\s*|\s+[-–]\s+", wert or "") if t.strip()]


def endungen_weg(n):
    for e in ("en", "e", "n", "s"):
        if len(n) > 5 and n.endswith(e):
            return n[: -len(e)]
    return n


class Vokabular:
    def __init__(self):
        with db() as con:
            self.begriffe = {(z[0], z[1]): z for z in con.execute(
                "SELECT art, anton_id, name, voll, typ, alternativ, breite, laenge FROM anton_begriff")}
            self.gelernt = defaultdict(dict)                 # (art, wort) -> {anton_id: ausschluss}
            for art, wort, aid, aus in con.execute("SELECT art, wort, anton_id, ausschluss FROM begriff_gelernt"):
                self.gelernt[(art, wort)][aid] = aus
        self.exakt, self.alternativ, self.stamm = defaultdict(dict), defaultdict(dict), defaultdict(dict)
        self.person = {}                                     # Namensteile ohne Reihenfolge → anton_id (nur actor)
        # Reihenfolge: bei gleichem Namen gewinnt die Stadt vor Kanton oder Land, sonst der kürzere Name
        for (art, aid), z in sorted(self.begriffe.items(), key=lambda x: (not (x[1][4] or "").startswith("Stadt"),
                                                                           len(x[1][2] or ""))):
            for f in formen(z[2], art) | formen(z[3], art):
                self.exakt[art].setdefault(f, aid)
                self.stamm[art].setdefault(endungen_weg(f), aid)
                if art == "actor" and namensteile(f):
                    self.person.setdefault(namensteile(f), aid)
            for a in json.loads(z[5] or "[]"):
                for f in formen(a, art):
                    if len(f) >= 3:
                        self.alternativ[art].setdefault(f, aid)
        self.liste = {art: sorted(self.exakt[art]) for art in ARTEN}
        self.orte_gps = [(aid, z[6], z[7]) for (art, aid), z in self.begriffe.items()
                         if art == "place" and z[6] is not None]

    def treffer(self, art, wort, aehnlich=False):
        """[(anton_id, wie, score)] für ein Wort; Ausschlüsse aus der Erschließung abgezogen."""
        n = norm(wort).strip(" ,")
        if not n or n in FUELLWOERTER:
            return []
        gelernt = self.gelernt.get((art, n), {})
        erg = [(aid, "gelernt", 0.9) for aid, aus in gelernt.items() if not aus]
        if not erg:
            for tabelle, wie, score in ((self.exakt, "exakt", 0.85), (self.alternativ, "Alternativname", 0.75),
                                        (self.stamm, "Wortform", 0.7)):
                schluessel = n if tabelle is not self.stamm else endungen_weg(n)
                if schluessel in tabelle[art]:
                    erg = [(tabelle[art][schluessel], wie, score)]
                    break
        if not erg and art == "actor" and namensteile(re.sub(r"\s*\(.*?\)\s*", " ", n)) in self.person:
            erg = [(self.person[namensteile(re.sub(r"\s*\(.*?\)\s*", " ", n))], "Namensform", 0.8)]
        if not erg and aehnlich and len(n) >= 5:
            for f in get_close_matches(n, self.liste[art], n=1, cutoff=AEHNLICH):
                erg = [(self.exakt[art][f], "ähnlich", round(0.8 * SequenceMatcher(None, n, f).ratio(), 2))]
        return [(aid, wie, s) for aid, wie, s in erg if not gelernt.get(aid)]

    def name(self, art, aid):
        z = self.begriffe.get((art, aid))
        return (z[3] or z[2]) if z else ""

    def naechster_ort(self, breite, laenge):
        beste = None
        for aid, b, l in self.orte_gps:
            km = 6371 * math.acos(min(1, max(-1, math.sin(math.radians(breite)) * math.sin(math.radians(b))
                                          + math.cos(math.radians(breite)) * math.cos(math.radians(b))
                                          * math.cos(math.radians(laenge - l)))))
            if km <= GPS_KM and (beste is None or km < beste[1]):
                beste = (aid, km)
        return beste


def normdaten_abgleichen(umfang_art=""):
    beginn = time.time()
    try:
        zahlen, fehlend = vokabular_holen()
    except (urllib.error.URLError, TimeoutError, OSError) as f:
        with db() as con:
            vorhanden = con.execute("SELECT COUNT(*) FROM anton_begriff").fetchone()[0]
        if not vorhanden:
            raise RuntimeError(f"Anton-Vokabular nicht erreichbar ({P.anton_url}): {getattr(f, 'reason', f)}") from None
        zeige(f"Anton nicht erreichbar, nehme das zwischengespeicherte Vokabular ({vorhanden:,} Begriffe).")
        zahlen, fehlend = {}, 0
    fortschritt(0.35, "Kandidaten zuordnen")
    v = Vokabular()
    if not v.begriffe:
        raise RuntimeError("Das Anton-Vokabular ist leer.")
    dateien = umfang()
    with db() as con:
        kandidaten = con.execute("SELECT platte_id, pfad, feld, wert, quelle, beleg FROM vorschlag "
                                 "WHERE schritt IN ('V5', 'V7') AND feld IN ('begriff', 'akteur', 'ort', 'schlagwort', 'gps')"
                                 ).fetchall()
        # Wörter aus eingebettetem Titel und Beschreibung (V7) wie Pfadwörter; je Element und Wort einmal
        for p, pfad, feld, wert, quelle, beleg in con.execute(
                "SELECT platte_id, pfad, feld, wert, quelle, beleg FROM vorschlag WHERE schritt = 'V7' AND feld IN ('titel', 'inhalt')"):
            kandidaten += [(p, pfad, "textwort", w, quelle, beleg) for w in text_begriffe(wert)]
    zeilen, ohne_treffer = [], Counter()
    zugeordnet = neu = 0
    cache = {}
    for i, (p, pfad, feld, wert, quelle, beleg) in enumerate(kandidaten):
        if i % 5000 == 0:
            fortschritt(0.35 + 0.6 * i / max(len(kandidaten), 1), f"{i:,} von {len(kandidaten):,} Kandidaten")
        if feld == "gps":
            b, l = json.loads(wert)
            t = v.naechster_ort(b, l)
            if t:
                aid, km = t
                zeilen.append((p, pfad, "ort", v.name("place", aid), f"Anton · GPS {km:.0f} km", round(0.75 - km / 100, 2),
                               f"GPS {b:.4f}, {l:.4f}", aid, v.name("place", aid)))
                zugeordnet += 1
            continue
        if feld in ("begriff", "textwort"):                # Wörter aus Pfaden und Texten: nur exakt; Personen ab 2 Wörtern
            arten = [("keyword", False), ("place", False)] + ([("actor", False)] if " " in wert else [])
        else:
            art = {"schlagwort": "keyword", "ort": "place", "akteur": "actor"}[feld]
            arten = [(art, "lange Schlagwortliste" not in quelle)]      # Agenturlisten nur exakt
            if feld == "schlagwort":                       # eingebettete Schlagworte auch als Person oder Ort, nur exakt
                arten += ([("actor", False)] if " " in wert.strip() else []) + [("place", False)]   # Personen ab 2 Wörtern
        gefunden = False
        suchwert = ohne_vorsatz(wert) if feld in ("akteur", "ort") else wert
        versuche = [(suchwert, arten, 1.0)]
        if feld in ("akteur", "ort") and len(teile(suchwert)) > 1:
            # Wert aus mehreren Angaben („nik hunger, zuerich“): erst als Ganzes, sonst je Teil als Person und Ort
            versuche += [(t, ([("actor", False)] if " " in t else []) + [("place", False)], 0.9) for t in teile(suchwert)]
        for nr, (such, such_arten, faktor) in enumerate(versuche):
            if gefunden and nr == 1:                       # der ganze Wert hat getroffen: nicht mehr zerlegen
                break
            for art, aehnlich in such_arten:
                schluessel = (art, norm(such), aehnlich)
                if schluessel not in cache:
                    cache[schluessel] = v.treffer(art, such, aehnlich)
                for aid, wie, score in cache[schluessel]:
                    ziel = ARTEN[art][1]
                    if feld == "begriff" and wie != "gelernt":     # Pfadwort: unsicherer als ein Metadatenwert
                        score = round(score * 0.8, 2)
                    elif feld == "textwort" and wie != "gelernt":  # Wort aus einem Text: noch unsicherer
                        score = round(score * 0.7, 2)
                    elif art != such_arten[0][0]:                  # Schlagwort als Person oder Ort
                        score = round(score * 0.85, 2)
                    zeilen.append((p, pfad, ziel, v.name(art, aid), f"Anton · {wie}", round(score * faktor, 2),
                                   f"{quelle}: „{wert}“", aid, v.name(art, aid)))
                    gefunden = True
        if gefunden:
            zugeordnet += 1
        elif feld == "begriff":
            ohne_treffer[wert] += 1
        elif feld == "textwort":
            continue
        elif "lange Schlagwortliste" not in quelle:          # Werte aus den Metadaten: als neu vorschlagen
            vorschlag = nachname_vorname(suchwert) if feld == "akteur" else wert   # Personen wie in Anton
            zeilen.append((p, pfad, feld, vorschlag, "neu (nicht in Anton)", 0.4, f"{quelle}: „{wert}“"))
            neu += 1
    n = vorschlaege_ersetzen("V8", zeilen)
    fortschritt(1, f"{len(kandidaten):,} Kandidaten")
    zeige(f"V8: {len(kandidaten):,} Kandidaten, {zugeordnet:,} mit Anton-Treffer, {neu:,} neu; {n:,} Vorschläge")
    stand_schreiben("V8", dateien, zugeordnet, {
        "kandidaten": len(kandidaten), "treffer": zugeordnet, "neu": neu, "vokabular": zahlen, "fehlend": fehlend,
        "ohne_treffer": ohne_treffer.most_common(40)}, beginn, umfang_art)
    return {"kandidaten": len(kandidaten), "treffer": zugeordnet}

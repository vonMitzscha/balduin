"""Angezeigte Texte sammeln und Neufassungen zurückschreiben (Redaktion des Wordings).

    .venv/bin/python werkzeuge/texte.py sammeln                 # schreibt docs/wording/texte.csv
    .venv/bin/python werkzeuge/texte.py einspielen --probe      # zeigt, was sich ändern würde
    .venv/bin/python werkzeuge/texte.py einspielen              # schreibt die Spalte „neu“ in den Code

Gesammelt wird, was Nutzende zu sehen bekommen: Text und Tooltips der Oberfläche (tool/web), Meldungen des
Servers und der Hintergrundläufe (Python). Jede Zeile nennt Datei und Zeile; eingespielt wird nur an dieser
Stelle (sucht in der Nähe, falls sich Zeilen verschoben haben). Platzhalter wie ${zahl(n)} oder {fehler}
müssen in der Neufassung erhalten bleiben, sonst wird die Zeile abgewiesen.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import io
import re
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
ZIEL = CODE / "docs" / "wording" / "texte.csv"

# Dateien und ihr Bereich (Reihenfolge = Reihenfolge in der Liste)
BEREICHE = [
    ("tool/web/index.html", "Rahmen"),
    ("tool/web/projekt.js", "Start und Projekte"),
    ("tool/web/erfassung.js", "1 Registrierung/Analyse"),
    ("tool/web/app.js", "2 Bewertung"),
    ("tool/web/erschliessung.js", "Vorlauf und 3 Erschließung"),
    ("tool/web/export.js", "4 Bestand und Export"),
    ("tool/web/dashboard.js", "Dashboard"),
    ("tool/web/icons.js", "Rahmen"),
    ("tool/server.py", "Server"),
    ("tool/erschliessung.py", "Server Erschließung"),
    ("tool/pakete.py", "Server Bestand und Export"),
    ("erfassung/*.py", "Läufe Analyse"),
    ("vorlauf/*.py", "Läufe Vorlauf"),
    ("export/*.py", "Läufe Export"),
]
AUSLASSEN = {"tool/web/sprache.js"}          # Easteregg „skartieren“, nur Wortersetzung

BUCHSTABEN = "A-Za-zÄÖÜäöüßéèàç"
WORT = re.compile(rf"[{BUCHSTABEN}]{{2,}}")
PLATZHALTER = re.compile(r"\$\{[^}]*\}|\{[^}]*\}")
TEXT_ATTRIBUTE = {"title", "placeholder", "aria-label", "alt", "data-tipp"}


@dataclass
class Fund:
    zeile: int
    text: str
    art: str        # text, title, placeholder, aria-label, alt, zeichenkette, meldung
    start: int = 0  # Stelle im Quelltext


class _Zeilen:
    """Stelle im Quelltext → Zeilennummer (1-basiert)."""
    def __init__(self, quelltext: str):
        self.anfaenge = [0] + [m.end() for m in re.finditer("\n", quelltext)]

    def __call__(self, stelle: int) -> int:
        return bisect.bisect_right(self.anfaenge, stelle)


def _hat_text(t: str) -> bool:
    ohne = PLATZHALTER.sub(" ", re.sub(r"&#?\w+;", " ", t))
    return bool(WORT.search(ohne))


def _sieht_aus_wie_text(t: str) -> bool:
    """Für einzelne Zeichenketten ohne HTML: ist das Anzeige oder ein Bezeichner/Wert?"""
    s = t.strip()
    if not _hat_text(s) or s.startswith(("/", ".", "#", "[", "-", "http", "data-", "aria-")):
        return False
    ohne = PLATZHALTER.sub("", s)
    # Code, Regex; in Prosa stehen „;“ und „=“ mit Leerzeichen („…; das“, „leer = keiner“)
    if re.search(r"[{}]|\S=|=\S|;\S|;$|=>|\\[dswbn]|\(\?", ohne):
        return False
    if re.search(r"[äöüÄÖÜß…„“–·]", ohne):
        return True
    woerter = ohne.split()
    if len(woerter) == 1:
        w = woerter[0].strip(".,:!?()")
        # ein Wort: nur mit großem Anfang und sonst klein (Speichern, Fehler), keine Tasten- oder Ereignisnamen
        return bool(re.fullmatch(rf"[A-ZÄÖÜ][a-zäöüß]+[.:!?]?", woerter[0])) and w not in {
            "Enter", "Escape", "Tab", "Backspace", "Delete", "Node", "Date", "Error", "Object", "Array", "Number"}
    # mehrere Wörter: Klassenlisten (alles klein mit Bindestrich/Unterstrich) sind kein Text
    if all(re.fullmatch(r"[a-z0-9_\-]+", w) for w in woerter) and any(re.search(r"[-_0-9]", w) for w in woerter):
        return False
    return True


# ================================================================================================ JavaScript / HTML

class _Html:
    """Zerlegt statischen Text (aus HTML oder einer JS-Vorlage) in Textläufe und Attributwerte."""

    def __init__(self, sammler: list[Fund], quelltext: str):
        self.funde, self.q = sammler, quelltext
        self.im_tag = False
        self.name = ""            # gerade gelesener Attributname
        self.wert_quote = ""      # Anführungszeichen des offenen Attributwerts
        self.wert_attr = ""
        self.wert_start = 0
        self.lauf_start = None    # Anfang des aktuellen Textlaufs
        self.lauf_ende = 0
        self.kommentar = False
        self.tagname = ""
        self.nach_gleich = False

    def zeichen(self, i: int):
        q, c = self.q, self.q[i]
        if self.kommentar:
            if q.startswith("-->", i - 2) and i >= 2:
                self.kommentar = False
            return
        if not self.im_tag:
            if c == "<" and i + 1 < len(q) and (q[i + 1].isalpha() or q[i + 1] in "/!"):
                self.abschliessen()
                if q.startswith("<!--", i):
                    self.kommentar = True
                    return
                self.im_tag, self.name, self.tagname, self.nach_gleich = True, "", "", False
                return
            if self.lauf_start is None:
                self.lauf_start = i
            self.lauf_ende = i + 1
            return
        # im Tag
        if self.wert_quote:
            if c == self.wert_quote:
                if self.wert_attr in TEXT_ATTRIBUTE:
                    self._fund(self.wert_start, i, self.wert_attr)
                self.wert_quote = ""
            return
        if c == ">":
            self.im_tag = False
        elif c in "\"'" and self.nach_gleich:
            self.wert_quote, self.wert_attr, self.wert_start = c, self.name.lower(), i + 1
            self.nach_gleich, self.name = False, ""
        elif c == "=":
            self.nach_gleich = True
        elif c.isspace():
            if self.name and not self.nach_gleich:
                pass
        else:
            if self.nach_gleich and not c.isspace():   # Wert ohne Anführungszeichen
                self.nach_gleich = False
            if c.isalnum() or c in "-_:":
                if self.name and self.q[i - 1].isspace():
                    self.name = ""
                self.name += c

    def platzhalter(self, start: int, ende: int):
        """Einfacher ${…} mitten im Text: gehört zum Lauf."""
        if not self.im_tag and not self.kommentar:
            if self.lauf_start is None:
                self.lauf_start = start
            self.lauf_ende = ende

    def abschliessen(self):
        if self.lauf_start is not None:
            self._fund(self.lauf_start, self.lauf_ende, "text")
        self.lauf_start = None

    def _fund(self, start: int, ende: int, art: str):
        roh = self.q[start:ende]
        links = len(roh) - len(roh.lstrip())
        text = roh.strip()
        if art == "text" and re.match(r'[\w-]+="', text):     # Attributteil einer Vorlage, die kein ganzes Tag ist
            return
        if text and _hat_text(text) and "`" not in text:
            self.funde.append(Fund(0, text, art, start + links))


class _Js:
    WORT_VOR_REGEX = {"return", "typeof", "case", "in", "of", "delete", "void", "throw", "new", "else", "do"}

    def __init__(self, quelltext: str):
        self.q = quelltext
        self.funde: list[Fund] = []

    def code(self, i: int, bis_klammer: bool = False) -> int:
        """Liest Code ab i; mit bis_klammer bis zur schließenden } eines ${…}. Gibt die Stelle danach zurück."""
        q, tiefe, letztes = self.q, 0, "("
        while i < len(q):
            c = q[i]
            if q.startswith("//", i):
                i = q.find("\n", i)
                i = len(q) if i < 0 else i
                continue
            if q.startswith("/*", i):
                e = q.find("*/", i + 2)
                i = len(q) if e < 0 else e + 2
                continue
            if c in "\"'":
                i = self.zeichenkette(i)
                letztes = "a"
                continue
            if c == "`":
                i = self.vorlage(i)
                letztes = "a"
                continue
            if c == "/":
                vorher = q[max(0, i - 12):i].rstrip()
                wort = re.search(r"[A-Za-z_$]+$", vorher)
                if letztes in "(,=:[!&|?{};+-*%<>~^" or (wort and wort.group() in self.WORT_VOR_REGEX):
                    i = self.regex(i)
                    letztes = "a"
                    continue
            if bis_klammer:
                if c == "{":
                    tiefe += 1
                elif c == "}":
                    if tiefe == 0:
                        return i + 1
                    tiefe -= 1
            if not c.isspace():
                letztes = "a" if (c.isalnum() or c in "_$)]") else c
            i += 1
        return i

    def regex(self, i: int) -> int:
        q, i, klasse = self.q, i + 1, False
        while i < len(q) and q[i] != "\n":
            c = q[i]
            if c == "\\":
                i += 2
                continue
            if c == "[":
                klasse = True
            elif c == "]":
                klasse = False
            elif c == "/" and not klasse:
                i += 1
                while i < len(q) and q[i].isalpha():
                    i += 1
                return i
            i += 1
        return i

    def zeichenkette(self, i: int) -> int:
        q, zeichen, start = self.q, self.q[i], i + 1
        i += 1
        while i < len(q) and q[i] != zeichen and q[i] != "\n":
            i += 2 if q[i] == "\\" else 1
        inhalt = q[start:i]
        if re.search(r"<[A-Za-z/]", inhalt):          # HTML in einer einfachen Zeichenkette
            h = _Html(self.funde, q)
            for j in range(start, i):
                h.zeichen(j)
            h.abschliessen()
        elif _sieht_aus_wie_text(inhalt):
            links = len(inhalt) - len(inhalt.lstrip())
            self.funde.append(Fund(0, inhalt.strip(), "zeichenkette", start + links))
        return i + 1

    def vorlage(self, i: int) -> int:
        q = self.q
        h = _Html(self.funde, q)
        i += 1
        while i < len(q):
            c = q[i]
            if c == "\\":
                h.zeichen(i)
                i += 2
                continue
            if c == "`":
                h.abschliessen()
                return i + 1
            if q.startswith("${", i):
                # Ausdruck getrennt lesen; einfach = ohne eigene Texte und ohne Vorlage darin
                innen = _Js(q)
                ende = innen.code(i + 2, bis_klammer=True)
                einfach = not innen.funde and "`" not in q[i:ende]
                if einfach:
                    h.platzhalter(i, ende)
                else:
                    if not h.im_tag:
                        h.abschliessen()
                    self.funde.extend(innen.funde)
                i = ende
                continue
            h.zeichen(i)
            i += 1
        h.abschliessen()
        return i


def _mit_zeilen(funde: list[Fund], quelltext: str) -> list[Fund]:
    zeile = _Zeilen(quelltext)
    for f in funde:
        f.zeile = zeile(f.start)
    return sorted(funde, key=lambda f: f.start)


def js_texte(quelltext: str) -> list[Fund]:
    js = _Js(quelltext)
    js.code(0)
    return _mit_zeilen(js.funde, quelltext)


def html_texte(quelltext: str) -> list[Fund]:
    funde: list[Fund] = []
    h = _Html(funde, quelltext)
    i = 0
    while i < len(quelltext):
        m = re.match(r"<(script|style)\b[^>]*>", quelltext[i:i + 200], re.I) if quelltext[i] == "<" else None
        if m and not h.im_tag and not h.kommentar:
            h.abschliessen()
            innen_start = i + m.end()
            ende = quelltext.lower().find(f"</{m.group(1).lower()}", innen_start)
            ende = len(quelltext) if ende < 0 else ende
            if m.group(1).lower() == "script":
                js = _Js(quelltext)
                # nur den Skriptteil lesen: Kopie mit Leerraum davor, damit die Stellen stimmen
                js.q = quelltext[:ende]
                js.code(innen_start)
                funde.extend(js.funde)
            i = ende
            continue
        h.zeichen(i)
        i += 1
    h.abschliessen()
    return _mit_zeilen(funde, quelltext)


# ================================================================================================ Python

SQL = re.compile(r"^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|WITH|PRAGMA|REPLACE|BEGIN)\b", re.I)
# Folgezeilen mehrzeiliger Abfragen: Schlüsselwörter in Großbuchstaben irgendwo im Text
SQL_TEIL = re.compile(r"\b(SELECT|FROM|WHERE|ORDER BY|GROUP BY|JOIN|LIMIT|VALUES|INSERT INTO|DISTINCT|COALESCE|"
                      r"AND \w+(\.\w+)? *(=|!=|<|>|IS|IN|LIKE)|OR \w+ *(=|IS))\b")


def _py_text_ok(inhalt: str) -> bool:
    ohne = PLATZHALTER.sub("", inhalt)
    if not _hat_text(ohne) or SQL.search(ohne) or SQL_TEIL.search(ohne) or len(ohne.split()) < 2:
        return False                                  # einzelne Wörter sind in Python fast immer Werte
    if re.search(r"\\[dswbn(]|\(\?|^\^|[;{}<>]|=>|%\(|%[sd]\b", ohne):
        return False
    if re.fullmatch(r"[a-z0-9_\-., /:|]+", ohne) and not re.search(r"[äöüß]", ohne):
        # klein und ohne Satzzeichen: eher Bezeichner, Pfade, Spaltenlisten
        return " " in ohne.strip() and not re.search(r"[_/|]|\w\.\w|, ?\w+_", ohne)
    return True


def py_texte(quelltext: str) -> list[Fund]:
    zeile = _Zeilen(quelltext)
    anfaenge = zeile.anfaenge
    stelle = lambda pos: anfaenge[pos[0] - 1] + pos[1]   # (zeile, spalte) → Stelle
    tokens = list(tokenize.generate_tokens(io.StringIO(quelltext).readline))
    funde: list[Fund] = []
    STRING_ANFANG = {tokenize.STRING, getattr(tokenize, "FSTRING_START", -1)}
    vorher = tokenize.NEWLINE
    k = 0
    while k < len(tokens):
        t = tokens[k]
        if t.type in STRING_ANFANG:
            if t.type == tokenize.STRING:
                ende_tok = t
            else:                                     # f-String bis FSTRING_END zusammenfassen
                tiefe, j = 0, k
                while j < len(tokens):
                    if tokens[j].type == t.type:
                        tiefe += 1
                    elif tokens[j].type == tokenize.FSTRING_END:
                        tiefe -= 1
                        if tiefe == 0:
                            break
                    j += 1
                ende_tok, k = tokens[j], j
            nach = tokens[k + 1].type if k + 1 < len(tokens) else tokenize.ENDMARKER
            # Docstrings und lose Zeichenketten: allein auf der Zeile
            allein = vorher in (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.NL, tokenize.ENCODING) \
                and nach in (tokenize.NEWLINE, tokenize.ENDMARKER)
            a, e = stelle(t.start), stelle(ende_tok.end)
            roh = quelltext[a:e]
            m = re.match(r"([rRbBuUfF]*)('''|\"\"\"|'|\")", roh)
            if m and not allein and "b" not in m.group(1).lower():
                inhalt_a = a + m.end()
                inhalt_e = e - len(m.group(2))
                inhalt = quelltext[inhalt_a:inhalt_e]
                if _py_text_ok(inhalt):
                    links = len(inhalt) - len(inhalt.lstrip())
                    funde.append(Fund(zeile(inhalt_a + links), inhalt.strip(), "meldung", inhalt_a + links))
        if t.type not in (tokenize.COMMENT, tokenize.NL):
            vorher = tokens[k].type if t.type in STRING_ANFANG else t.type
        k += 1
    return funde


# ================================================================================================ Werte im Code

def als_wert(text: str, code: str) -> bool:
    """Steht der Text auch als Wert im Code (Vergleich, Schlüssel, Liste von Werten, SQL)? Dann ändert eine
    Neufassung an nur einer Stelle die Logik – solche Zeilen markiert die Liste."""
    if len(text) > 80 or "\n" in text or "${" in text:
        return False
    for zeichen in "\"'`":
        lit = zeichen + text + zeichen
        stelle = code.find(lit)
        while stelle >= 0:
            # nur die eigene Zeile ansehen: davor und danach
            a = code.rfind("\n", 0, stelle) + 1
            e = code.find("\n", stelle + len(lit))
            vor, nach = code[a:stelle], code[stelle + len(lit):e if e >= 0 else len(code)]
            if (re.search(r"(===?|!==?)\s*$", vor) or re.match(r"\s*(===?|!==?)", nach)       # Vergleich
                    or (re.search(r"(^|[{,])\s*$", vor) and re.match(r"\s*:(?!\w)", nach))      # Schlüssel
                    or re.search(r"(\bisin\(|\.includes\(|\.has\(|\bnot in\s*[\[({]|\bin\s*[\[({])\s*\[?[^)\]}]*$", vor)
                    or re.search(r"\bcase\s*$", vor)
                    or (zeichen == "'" and re.search(r"(=|\bIN\s*\([^)]*)\s*$", vor))):   # SQL
                return True
            stelle = code.find(lit, stelle + 1)
    return False


# ================================================================================================ Zurückschreiben

def platzhalter(text: str) -> list[str]:
    return sorted(PLATZHALTER.findall(text))


def _grenze_ok(q: str, a: int, e: int) -> bool:
    vor = q[a - 1] if a > 0 else "\n"
    nach = q[e] if e < len(q) else "\n"
    return (vor in "\"'`>}" or vor.isspace()) and (nach in "\"'`<$" or nach.isspace())


def einspielen(quelltext: str, aenderungen: list[tuple[int, str, str]], fenster: int = 80):
    """Ersetzt je (Zeile, alt, neu) das Vorkommen von alt nahe der Zeile. → (neuer Text, [(zeile, grund, alt)])"""
    zeile = _Zeilen(quelltext)
    abgewiesen, ersetzen = [], []
    for z, alt, neu in aenderungen:
        if platzhalter(alt) != platzhalter(neu):
            abgewiesen.append((z, "Platzhalter fehlen oder sind neu: " + ", ".join(platzhalter(alt)), alt))
            continue
        kandidaten = []
        for m in re.finditer(re.escape(alt), quelltext):
            abstand = abs(zeile(m.start()) - z)
            if abstand <= fenster and _grenze_ok(quelltext, m.start(), m.end()):
                kandidaten.append((abstand, m.start()))
        if not kandidaten:
            abgewiesen.append((z, "Text an dieser Stelle nicht gefunden", alt))
            continue
        kandidaten.sort()
        if len(kandidaten) > 1 and kandidaten[0][0] == kandidaten[1][0]:
            abgewiesen.append((z, "Text steht mehrfach gleich nah, nicht eindeutig", alt))
            continue
        ersetzen.append((kandidaten[0][1], alt, neu, z))
    ersetzen.sort(reverse=True)
    belegt_bis = len(quelltext) + 1
    for a, alt, neu, z in ersetzen:
        if a + len(alt) > belegt_bis:
            abgewiesen.append((z, "überschneidet sich mit einer anderen Änderung", alt))
            continue
        quelltext = quelltext[:a] + neu + quelltext[a + len(alt):]
        belegt_bis = a
    return quelltext, abgewiesen


# ================================================================================================ Befehle

def dateien():
    gesehen = set()
    for muster, bereich in BEREICHE:
        for p in sorted(CODE.glob(muster)):
            rel = p.relative_to(CODE).as_posix()
            if rel in gesehen or rel in AUSLASSEN:
                continue
            gesehen.add(rel)
            yield rel, bereich


def texte_der_datei(rel: str) -> list[Fund]:
    q = (CODE / rel).read_text(encoding="utf-8")
    if rel.endswith(".js"):
        return js_texte(q)
    if rel.endswith(".html"):
        return html_texte(q)
    return py_texte(q)


def sammeln(ziel: Path = ZIEL) -> int:
    zeilen, alles = [], []
    for rel, bereich in dateien():
        roh = (CODE / rel).read_text(encoding="utf-8")
        alles.append(roh)
        quelle = roh.split("\n")
        for f in texte_der_datei(rel):
            zeilen.append({"bereich": bereich, "datei": rel, "zeile": f.zeile, "art": f.art, "text": f.text,
                           "kontext": quelle[f.zeile - 1].strip()[:200]})
    # wie oft derselbe Text vorkommt (hilft beim Vereinheitlichen; mehrfach = vielleicht auch ein Wert im Code)
    anzahl: dict[str, int] = {}
    for z in zeilen:
        anzahl[z["text"]] = anzahl.get(z["text"], 0) + 1
    code = "\n".join(alles)
    werte = {t for t in anzahl if als_wert(t, code)}
    ziel.parent.mkdir(parents=True, exist_ok=True)
    with ziel.open("w", encoding="utf-8", newline="") as d:
        w = csv.writer(d)
        w.writerow(["nr", "bereich", "datei", "zeile", "art", "text", "neu", "anmerkung", "achtung", "gleich_oft",
                    "kontext"])
        for nr, z in enumerate(zeilen, 1):
            achtung = "auch Wert im Code: nur mit Claude ändern" if z["text"] in werte else ""
            w.writerow([nr, z["bereich"], z["datei"], z["zeile"], z["art"], z["text"], "", "", achtung,
                        anzahl[z["text"]], z["kontext"]])
    return len(zeilen)


def _csv_lesen(pfad: Path) -> list[dict]:
    roh = pfad.read_text(encoding="utf-8-sig")
    trenner = ";" if roh.split("\n", 1)[0].count(";") > roh.split("\n", 1)[0].count(",") else ","
    return list(csv.DictReader(io.StringIO(roh), delimiter=trenner))


def einspielen_csv(pfad: Path = ZIEL, probe: bool = False) -> tuple[int, list]:
    je_datei: dict[str, list] = {}
    for z in _csv_lesen(pfad):
        neu = (z.get("neu") or "").strip()
        if neu and neu != z["text"]:
            je_datei.setdefault(z["datei"], []).append((int(z["zeile"]), z["text"], neu))
    geaendert, alle_abgewiesen = 0, []
    for rel, aenderungen in je_datei.items():
        datei = CODE / rel
        alt = datei.read_text(encoding="utf-8")
        neu, abgewiesen = einspielen(alt, aenderungen)
        geaendert += len(aenderungen) - len(abgewiesen)
        alle_abgewiesen += [(rel, *a) for a in abgewiesen]
        if not probe and neu != alt:
            datei.write_text(neu, encoding="utf-8")
    return geaendert, alle_abgewiesen


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("befehl", choices=["sammeln", "einspielen"])
    ap.add_argument("--csv", type=Path, default=ZIEL)
    ap.add_argument("--probe", action="store_true", help="nur zeigen, nichts schreiben")
    a = ap.parse_args(argv)
    if a.befehl == "sammeln":
        print(f"{sammeln(a.csv)} Texte nach {a.csv}")
        return
    n, abgewiesen = einspielen_csv(a.csv, a.probe)
    print(f"{n} Texte {'würden geändert' if a.probe else 'geändert'}")
    for rel, z, grund, alt in abgewiesen:
        print(f"  abgewiesen {rel}:{z}: {grund}: {alt[:80]}", file=sys.stderr)


if __name__ == "__main__":
    main()

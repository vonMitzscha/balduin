"""Gemeinsames für die Schritte des Vorlaufs: Umfang, Textregeln, Liste des Unbrauchbaren, Vorschläge schreiben."""
import csv
import json
import re
import time
import unicodedata
from functools import lru_cache

from erfassung.basis import CODE, P, db, jetzt

# Endungen der Dokumente (wie TEXT_ENDUNGEN in erfassung/texte.py)
TEXT_ENDUNGEN = {".pdf", ".doc", ".dot", ".docx", ".docm", ".dotx", ".ppt", ".pps", ".pot", ".pptx", ".ppsx",
                 ".pptm", ".odt", ".odp", ".rtf", ".txt", ".htm", ".html"}
# Wörter ohne eigene Bedeutung für Titel und Begriffe (allgemein, mehrsprachig, kurz gehalten)
FUELLWOERTER = set("""der die das den dem des ein eine einer und oder mit von vom für fuer im in am an auf aus bei zu zum zur
nach über ueber unter vor the a an and or of for in on at to by with from le la les de du des et en un une il lo gli e di da
con per""".split())


def elternordner(relpfad):
    return relpfad.rsplit("/", 1)[0] if "/" in relpfad else ""


def name_von(relpfad):
    return relpfad.rsplit("/", 1)[-1]


def endung(relpfad):
    name = name_von(relpfad)
    return name[name.rfind("."):].lower() if "." in name else ""


def norm(text):
    """Vergleichsform: NFC, klein, Umlaute ausgeschrieben, Akzente weg, Leerraum vereinfacht."""
    t = unicodedata.normalize("NFC", text or "").lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(a, b)
    t = "".join(z for z in unicodedata.normalize("NFD", t) if unicodedata.category(z) != "Mn")
    return " ".join(t.split())


def woerter(text):
    """Wörter eines Ordner- oder Dateinamens: CamelCase und Trennzeichen getrennt, in Originalschreibung."""
    text = re.sub(r"([a-zäöüß])([A-ZÄÖÜ])", r"\1 \2", text or "")
    text = re.sub(r"([A-ZÄÖÜ]{2,})([A-ZÄÖÜ][a-zäöüß]{2,})", r"\1 \2", text)      # ABCMuster → ABC Muster
    return [w for w in re.split(r"[\s_\-.,;:()\[\]{}+&/\\#'\"!?]+", text) if w]


# ---------- Unbrauchbares (vorgaben/vorlauf_verwerfen.csv) ----------

@lru_cache(maxsize=1)
def verwerfen_liste():
    """Arbeitsordner, Platzhalter und Kameratexte aus der Regeltabelle (Projektkopie, sonst die aus dem Git)."""
    datei = P.vorgaben / "vorlauf_verwerfen.csv"
    if not datei.exists():
        datei = CODE / "vorgaben" / "vorlauf_verwerfen.csv"
    liste = {"arbeitsordner": set(), "text": set(), "vorsatz": [], "enthaelt": [], "muster": []}
    with open(datei, encoding="utf-8") as f:
        for z in csv.DictReader(f, delimiter=";"):
            art, wert = (z.get("art") or "").strip(), (z.get("wert") or "")
            if art in ("arbeitsordner", "text"):
                liste[art].add(norm(wert))
            elif art == "vorsatz":
                liste[art].append(norm(wert).rstrip() + " ")
            elif art == "enthaelt":
                liste[art].append(norm(wert))
            elif art == "muster":
                liste[art].append(re.compile(wert.strip(), re.I))
    return liste


def arbeitsordner(wort):
    return norm(wort) in verwerfen_liste()["arbeitsordner"]


def bereinigen(text):
    """Eingebetteter Text (Titel, Beschreibung, Name) → brauchbarer Wert oder "" (Kameratexte, Platzhalter,
    Dateinamen, Benutzerkürzel, Software-Copyright). Steuerzeichen und Leerraum werden bereinigt, Vorsätze wie
    „Microsoft Word - “ abgeschnitten."""
    if text is None:
        return ""
    if isinstance(text, (list, tuple)):
        text = ", ".join(str(t) for t in text)
    t = re.sub(r"[\x00-\x1f\x7f]+", " ", str(text))
    t = " ".join(t.split()).strip(" ,;-–")
    if not t or len(t) > 500:
        return ""
    liste = verwerfen_liste()
    n = norm(t)
    for v in liste["vorsatz"]:
        if n.startswith(v):
            t = t[len(v):].strip()
            n = norm(t)
    if n in liste["text"] or any(e in n for e in liste["enthaelt"]) or any(m.search(n) for m in liste["muster"]):
        return ""
    if not re.search(r"[A-Za-zÄÖÜäöüß]{2}", t):
        return ""
    return t


# ---------- Umfang ----------

def umfang():
    """Dateien, für die der Vorlauf rechnet: vom Tool vor dem Start in vorlauf_umfang geschrieben."""
    with db() as con:
        return [(p, r) for p, r in con.execute("SELECT platte_id, relpfad FROM vorlauf_umfang ORDER BY platte_id, relpfad")]


def ordner_mit_dateien(dateien):
    """Alle Ordner (samt Platte "") über den Dateien, je mit der Zahl der Dateien darunter."""
    zahl = {}
    for p, r in dateien:
        o = r
        while True:
            o = elternordner(o) if o else None
            if o is None:
                break
            zahl[(p, o)] = zahl.get((p, o), 0) + 1
            if o == "":
                break
    return zahl


# ---------- Vorschläge schreiben ----------

def vorschlaege_ersetzen(schritt, zeilen):
    """Ersetzt alle Vorschläge des Schritts durch zeilen (platte, pfad, feld, wert, quelle, score, beleg[, anton_id,
    anton_name]). Urteile in vorschlag_urteil bleiben; verworfene Werte werden gar nicht erst geschrieben."""
    zeit = jetzt()
    with db() as con:
        verworfen = {tuple(z) for z in con.execute(
            "SELECT platte_id, pfad, feld, wert FROM vorschlag_urteil WHERE urteil = 'verworfen'")}
        con.execute("DELETE FROM vorschlag WHERE schritt = ?", (schritt,))
        daten, gesehen = [], set()
        for z in zeilen:
            z = tuple(z) + (None,) * (9 - len(z))
            schluessel = z[:4]
            if schluessel in verworfen or schluessel in gesehen:
                continue
            gesehen.add(schluessel)
            daten.append((*z[:7], schritt, z[7], z[8], zeit))
        con.executemany("INSERT INTO vorschlag (platte_id, pfad, feld, wert, quelle, score, beleg, schritt, anton_id, "
                        "anton_name, zeit) VALUES (?,?,?,?,?,?,?,?,?,?,?)", daten)
    return len(daten)


def stand_schreiben(schritt, dateien, ergebnis, kennzahlen, beginn, umfang_art=""):
    """Kennzahlen des Schritts und die berücksichtigten Dateien (für „offen“ in der Übersicht)."""
    with db() as con:
        con.execute("DELETE FROM vorlauf_erledigt WHERE schritt = ?", (schritt,))
        con.executemany("INSERT INTO vorlauf_erledigt VALUES (?,?,?)", [(schritt, p, r) for p, r in dateien])
        con.execute("INSERT OR REPLACE INTO vorlauf_stand VALUES (?,?,?,?,?,?,?)",
                    (schritt, umfang_art, len(dateien), ergebnis, json.dumps(kennzahlen, ensure_ascii=False), jetzt(),
                     round(time.time() - beginn, 1)))


def datum_deutsch(iso):
    """2007-09-27 → 27.09.2007, 2007-09 → 09.2007, 2007 → 2007."""
    teile = (iso or "").split("-")
    return ".".join(reversed(teile)) if all(teile) else ""

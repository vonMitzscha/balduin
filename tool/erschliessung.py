"""Vorlauf und Modul 3 Erschließung im Server (Entscheidungen 03.11.2026 in docs/plan.md). Nur Standardbibliothek.

Arbeitet auf dem geladenen Bestand des Servers (Dateien, Zähler, wirksame Entscheidungen) und der Datenbank:
- Vorlauf: Stand der Vorverarbeitung, Einstellungen (projekt.json → vorlauf), Start als Hintergrundlauf der Art
  „vorlauf“ (Rechencode in vorlauf/, über erfassung/lauf.py); vorher schreibt der Server den Umfang (vorlauf_umfang).
- Erschließung: Baum mit Stand je Ordner, Facetten, zusammengefasste Angaben mit Vorschlägen, Felder speichern
  (Tabelle `erschliessung`); ein Wert gilt wie eine Entscheidung vom Ordner abwärts, eine eigene Angabe geht vor.
  Abgleich mit verwandten Ordnern, Sprachmodell auf Abruf (vorlauf/sprachmodell.py über erfassung.lauf).
- Bestandsboxen: Anton-Einheiten nur lesend (erfassung.lauf, Token bleibt dort), neue Ebenen und Zuordnungen nur in
  der Datenbank; angelegt wird in Anton allein durch den Import (Modul 4).
"""
import json
import os
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vorlauf.schema import SCHEMA_VORLAUF  # noqa: E402  (nur ein Text, keine Abhängigkeiten)

SCHEMA = """
-- Modul 3 Erschließung: je Platte + Pfad (Datei, Ordner oder "" = Platte) und Feld der gleichbleibende Teil und
-- der Teil je Datei (Muster mit {laufnummer}, {dateiname}, {datum} oder fester Text); dieselben Tabellen legt
-- erfassung/basis.py an
CREATE TABLE IF NOT EXISTS erschliessung (
    platte_id TEXT, pfad TEXT, feld TEXT, gleich TEXT, je_datei TEXT, quelle TEXT, wer TEXT, zeit TEXT,
    PRIMARY KEY (platte_id, pfad, feld));
CREATE TABLE IF NOT EXISTS bestandsbox (
    anton_id INTEGER PRIMARY KEY, signatur TEXT, titel TEXT, stufe TEXT, objektart TEXT, anzahl INTEGER, link TEXT,
    eltern TEXT, zugang TEXT, geladen_am TEXT, reihenfolge INTEGER, laufzeit TEXT, gesperrt INTEGER);
""" + SCHEMA_VORLAUF

# Felder. import: was der API-Import übernimmt (docs/anton_import.md, A7); art: text, zeitraum, begriff (ein
# Anton-Eintrag), begriffe (mehrere); anton: Art im Vokabular
FELDER = {
    "titel": {"name": "Titel", "pflicht": True, "art": "text", "import": "kommt mit dem Import an", "an": True},
    "zeitraum": {"name": "Entstehungszeitraum", "pflicht": True, "art": "zeitraum",
                 "import": "kommt an (erstes Entstehungsereignis)", "an": True},
    "inhalt": {"name": "Form und Inhalt", "pflicht": False, "art": "text", "import": "kommt an (scopecontent)", "an": True},
    "akteur": {"name": "Akteur:in (Entstehung)", "pflicht": False, "art": "begriff", "anton": "actor", "an": True,
               "import": "kommt an, nur als Anton-Eintrag (ein Name ohne Eintrag bleibt vorerst weg, sonst bräche der Import ab)"},
    "ort": {"name": "Ort (Entstehung)", "pflicht": False, "art": "begriff", "anton": "place", "an": True,
            "import": "kommt an, nur als Anton-Eintrag (ein Name ohne Eintrag bleibt vorerst weg)"},
    "schlagworte": {"name": "Schlagworte", "pflicht": False, "art": "begriffe", "anton": "keyword", "an": False,
                    "import": "geht mit; der API-Import übernimmt sie, sobald Anton ihn erweitert (angekündigt 04.11.2026)"},
    # Register wie in Anton (Entscheidung 05.11.2026): neben Akteur:in und Ort der Entstehung beliebig viele
    "akteure": {"name": "Akteur:innen (Register)", "pflicht": False, "art": "begriffe", "anton": "actor", "an": False,
                "import": "geht als actors[] mit, wenn die Instanz das Importformat 0.8 liest (davor nicht)"},
    "orte": {"name": "Orte (Register)", "pflicht": False, "art": "begriffe", "anton": "place", "an": False,
             "import": "geht als places[] mit; der API-Import übernimmt sie, sobald Anton ihn erweitert"},
    # Sprache (Entscheidung 14.11.2026): aus Balduins Liste (SPRACHEN), gespeichert mit Name und Code
    "sprachen": {"name": "Sprachen", "pflicht": False, "art": "begriffe", "anton": "language", "an": False,
                 "import": "geht als languages[] mit (ISO 639-2, wie Anton die Sprachen führt)"},
}
# Sprachen als ISO-639-2-Code, wie Anton sie in der Tabelle languages führt (alle an einer Testinstanz geprüft,
# 14.11.2026); die API von Anton liefert nur interne IDs und Namen, darum eine feste Liste
SPRACHEN = [("ger", "Deutsch"), ("gsw", "Schweizerdeutsch"), ("fre", "Französisch"), ("ita", "Italienisch"),
            ("roh", "Rätoromanisch"), ("eng", "Englisch"), ("spa", "Spanisch"), ("por", "Portugiesisch"),
            ("dut", "Niederländisch"), ("dan", "Dänisch"), ("swe", "Schwedisch"), ("nor", "Norwegisch"),
            ("fin", "Finnisch"), ("pol", "Polnisch"), ("cze", "Tschechisch"), ("slo", "Slowakisch"),
            ("hun", "Ungarisch"), ("rus", "Russisch"), ("gre", "Griechisch"), ("grc", "Altgriechisch"),
            ("lat", "Latein"), ("tur", "Türkisch"), ("ara", "Arabisch"), ("heb", "Hebräisch"), ("hin", "Hindi"),
            ("chi", "Chinesisch"), ("jpn", "Japanisch"), ("kor", "Koreanisch"), ("mul", "Mehrere Sprachen"),
            ("zxx", "Kein sprachlicher Inhalt"), ("und", "Unbestimmt")]
PFLICHT = [k for k, f in FELDER.items() if f["pflicht"]]
VORSCHLAG_FELD = {"titel": "titel", "zeitraum": "zeitraum", "inhalt": "inhalt", "akteur": "akteur", "ort": "ort",
                  "schlagwort": "schlagworte"}
# Felder, in denen ein Vorschlag außerdem erscheint (Register neben dem Entstehungsereignis)
VORSCHLAG_AUCH = {"akteur": "akteure", "ort": "orte"}
UEBERNEHMEN = "übernehmen"
# Endungen der Dokumente (wie TEXT_ENDUNGEN in erfassung/texte.py)
TEXT_ENDUNGEN = {".pdf", ".doc", ".dot", ".docx", ".docm", ".dotx", ".ppt", ".pps", ".pot", ".pptx", ".ppsx",
                 ".pptm", ".odt", ".odp", ".rtf", ".txt", ".htm", ".html"}
# Weitere Metadaten im Editor (Entscheidung 04.11.2026): beschreibende Tags der vollständigen ExifTool-Ausgabe
# (exif_voll, Schlüssel „Gruppe:Tag“), je Tag Bezeichnung und vorgeschlagenes Feld; Reihenfolge = Anzeige
META_TAGS = [
    ("Artist", "Urheber", "akteur"), ("Creator", "Urheber", "akteur"), ("By-line", "Urheber", "akteur"),
    ("Author", "Autor", "akteur"), ("XPAuthor", "Autor", "akteur"), ("Credit", "Credit", "akteur"),
    ("PersonInImage", "Person im Bild", "akteure"), ("Company", "Firma", "akteur"), ("LastModifiedBy", "Zuletzt bearbeitet von", ""),
    ("Copyright", "Copyright", ""), ("CopyrightNotice", "Copyright", ""), ("Rights", "Rechte", ""), ("Source", "Quelle", ""),
    ("Title", "Titel", "titel"), ("ObjectName", "Objektname", "titel"), ("Headline", "Überschrift", "titel"), ("XPTitle", "Titel", "titel"),
    ("ImageDescription", "Bildbeschreibung", "inhalt"), ("Description", "Beschreibung", "inhalt"),
    ("Caption-Abstract", "Bildunterschrift", "inhalt"), ("UserComment", "Kommentar", "inhalt"), ("Comment", "Kommentar", "inhalt"),
    ("XPComment", "Kommentar", "inhalt"), ("Keywords", "Schlagworte", "schlagworte"), ("Subject", "Schlagworte", "schlagworte"),
    ("XPKeywords", "Schlagworte", "schlagworte"), ("SupplementalCategories", "Kategorien", "schlagworte"), ("Category", "Kategorie", "schlagworte"),
    ("Event", "Ereignis", "titel"), ("City", "Ort", "ort"), ("Sub-location", "Ortsteil", "ort"), ("Location", "Ort", "ort"),
    ("Province-State", "Region", "ort"), ("State", "Region", "ort"), ("Country-PrimaryLocationName", "Land", "ort"), ("Country", "Land", "ort"),
    ("Make", "Kamerahersteller", ""), ("Model", "Kameramodell", ""), ("Software", "Software", ""), ("CreatorTool", "Programm", ""),
    ("Producer", "erzeugt mit", ""),
]
META_ART = {"akteur": "actor", "ort": "place", "schlagworte": "keyword", "akteure": "actor", "orte": "place"}

STUFEN = {"class": "Gliederungsebene", "file": "Dossier", "item": "Einzelstück", "": "Ordner aufgelöst"}
# Ordner als Einzelstück (Entscheidung 05.11.2026): ein Objekt in Anton, alle übernommenen Dateien darunter als Medien

# Schritte des Vorlaufs (Kürzel wie im Entwurf docs/vorlauf_erschliessung_felder.md); lauf: im Hintergrundlauf
# (vorlauf/), sonst nur Anzeige. Dauer geschätzt für rund 85.000 Dateien (03.11.2026)
VORLAUF_SCHRITTE = [
    {"k": "V5", "name": "Pfade und Namen", "lauf": True, "dauer": "Sekunden",
     "was": "Titel, Datum und Begriffe aus den Namen der Ordner und Dateien"},
    {"k": "V7", "name": "Metadaten verteilen", "lauf": True, "dauer": "1–3 min",
     "was": "Titel, Inhalt, Urheber:in, Ort und Schlagworte aus den Metadaten und Texten der Dateien"},
    {"k": "V3", "name": "Sujet", "lauf": True, "dauer": "rund 1 min je 2.500 Fotos",
     "was": "Bildinhalte auf den Vorschaubildern der Fotos erkennen (OpenCLIP, lokal); Anton-Schlagworte als Vorschlag, "
            "sonst englisch als Kontext"},
    {"k": "V8", "name": "Normdaten abgleichen", "lauf": True, "dauer": "1–5 min",
     "was": "Gefundene Begriffe mit den Schlagworten, Orten und Akteur:innen in Anton abgleichen"},
    {"k": "V10", "name": "Verwandte finden", "lauf": True, "dauer": "unter 1 min",
     "was": "Ordner, die zusammengehören: gleiche Dateien, gleicher Tag und Kamera, ähnliche Namen"},
]
SCHRITTE_IM_LAUF = [s["k"] for s in VORLAUF_SCHRITTE if s["lauf"]]


def elternordner(relpfad):
    return relpfad.rsplit("/", 1)[0] if "/" in relpfad else ""


def weg_nach_oben(pfad):
    """pfad selbst und alle Ordner darüber bis zur Platte (""), unterster zuerst."""
    kette = [pfad]
    while kette[-1]:
        kette.append(elternordner(kette[-1]))
    return kette


def unter(pfad, ordner):
    return ordner == "" or pfad == ordner or pfad.startswith(ordner + "/")


# SQL: pfad ist der Ordner selbst oder liegt darunter (ohne LIKE, denn _ und % kommen in Pfaden vor)
DARUNTER = "(? = '' OR pfad = ? OR substr(pfad, 1, ?) = ?)"


def darunter(ordner):
    return ordner, ordner, len(ordner) + 1, ordner + "/"


# Ziel „o:<Platte>|<Ordner>“: Datei in einer Ordner-Einheit (Ordner mit eigener Ebene, Entscheidung 06.11.2026)
def ordner_ziel(platte, pfad):
    return f"o:{platte}|{pfad}"


def ordner_ziel_teilen(ziel):
    """„o:<Platte>|<Ordner>“ → (Platte, Ordner), sonst None."""
    if not (ziel or "").startswith("o:") or "|" not in ziel:
        return None
    platte, _, pfad = ziel[2:].partition("|")
    return platte, pfad


def datum_deutsch(iso):
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    return f"{m[3]}.{m[2]}.{m[1]}" if m else (iso or "")


def norm(text):
    t = unicodedata.normalize("NFC", text or "").lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(a, b)
    t = "".join(z for z in unicodedata.normalize("NFD", t) if unicodedata.category(z) != "Mn")
    return " ".join(t.split())


def zeit():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def zeitraum_teile(gleich):
    """Gespeicherter Zeitraum → (von, bis, ca_von, ca_bis). Seit 04.11.2026 [von, bis, ca_von, ca_bis] wie in Anton
    (je Seite „ca.“); ältere Einträge [von, bis, ca] gelten für beide Seiten."""
    w = json.loads(gleich) if gleich else ["", "", False]
    von, bis = (w + ["", ""])[:2]
    ca_von = bool(w[2]) if len(w) > 2 else False
    ca_bis = bool(w[3]) if len(w) > 3 else ca_von
    return von or "", bis or "", ca_von, ca_bis


def zeitraum_text(gleich):
    try:
        von, bis, ca_von, ca_bis = zeitraum_teile(gleich)
    except (ValueError, TypeError, AttributeError):
        return gleich or ""
    if bis == von and bool(ca_von) == bool(ca_bis):     # ein Tag, Monat oder Jahr (von = bis)
        bis = ""
    teile = [("ca. " if ca else "") + x for x, ca in ((von, ca_von), (bis, ca_bis)) if x]
    return "–".join(teile)


def datum_lesen(text):
    """„TT.MM.JJJJ“, „MM.JJJJ“ oder „JJJJ“ → (jahr, monat, tag) mit 0 für unbekannt; None, wenn nicht lesbar."""
    m = re.fullmatch(r"(?:(?:(\d{1,2})\.)?(\d{1,2})\.)?(\d{4})", (text or "").strip())
    if not m:
        return None
    tag, monat, jahr = int(m[1] or 0), int(m[2] or 0), int(m[3])
    if monat > 12 or tag > 31 or (tag and not monat):
        return None
    return jahr, monat, tag


def zeitraum_gueltig(gleich):
    """Laufzeit lesbar und von ≤ bis (für das Häkchen und die Pflichtprüfung)."""
    try:
        von, bis, _, _ = zeitraum_teile(gleich)
    except (ValueError, TypeError, AttributeError):
        return False
    a, b = datum_lesen(von), datum_lesen(bis) if bis else None
    if not a or (bis and not b):
        return False
    return not b or a <= b


def begriff_text(feld, gleich):
    try:
        w = json.loads(gleich) if gleich else None
    except ValueError:
        return gleich or ""
    if isinstance(w, list):                              # Schlagworte und Register
        return ", ".join(x.get("name", "") for x in w)
    return (w or {}).get("name", "")


def beleg_wort(beleg):
    """Ursprüngliches Wort aus einem Beleg wie „Ordnername: „Technology Day““ (für Synonyme und Ausschlüsse)."""
    m = re.search(r"„([^“]+)“\s*$", beleg or "")
    return m[1] if m else ""


class Erschliessung:
    def __init__(self, bestand, erfassung):
        self.b = bestand
        self.erfassung = erfassung
        self.cache_stand, self.cache = None, {}

    # ---- Grunddaten (je Datenbankstand einmal gelesen) ----

    def daten(self):
        stand = (self.b.db_stand(), id(self.b.wirksam_je_datei))
        if stand != self.cache_stand:
            con = self.b.verbinden()
            try:
                werte = {}
                for z in con.execute("SELECT * FROM erschliessung"):
                    werte.setdefault((z["platte_id"], z["pfad"]), {})[z["feld"]] = dict(z)
                datum = {(z[0], z[1]): z[2] for z in con.execute(
                    "SELECT platte_id, relpfad, datum FROM metadaten WHERE datum IS NOT NULL AND datum != ''")}
                zuordnung = {(z["platte_id"], z["pfad"]): dict(z) for z in con.execute("SELECT * FROM zuordnung")}
                hinweise = {(z[0], z[1]) for z in con.execute("SELECT platte_id, pfad FROM erschliessungshinweis")}
            finally:
                con.close()
            d = {"werte": werte, "datum": datum, "lfd": {}, "zuordnung": zuordnung, "hinweise": hinweise}
            d["uebernommen"] = [k for k in self.b.dateien if self.uebernommen(*k)]
            d["erschlossen"] = {k for k in d["uebernommen"] if self.erschlossen(*k, d)}
            for (platte, pfad), z in zuordnung.items():      # Ordner als Einzelstück: erschlossen über den Ordner
                if z["stufe"] == "item" and (platte, pfad) not in self.b.dateien and self.erschlossen(platte, pfad, d):
                    d["erschlossen"].update((platte, r) for r in self.uebernommene_unter(platte, pfad)
                                            if self.einzelstueck_von(platte, r, d) == pfad)
            self.cache_stand, self.cache = stand, d
        return self.cache

    def uebernommen(self, platte, relpfad):
        w = self.b.wirksam_je_datei.get((platte, relpfad))
        return bool(w) and w[0] == UEBERNEHMEN and not self.b.dateien[(platte, relpfad)]["system"]

    def uebernommene_unter(self, platte, pfad):
        if (platte, pfad) in self.b.dateien:
            return [pfad] if self.uebernommen(platte, pfad) else []
        return sorted((r for r in self.b.dateien_unter(platte, pfad) if self.uebernommen(platte, r)), key=str.casefold)

    # ---- Felder: feste und weitere Anton-Felder (note.*, Entscheidung 04.11.2026) ----

    def anton_felder(self):
        """Notizfelder aus Anton (Tabelle anton_feld): {name: {label, import}}, je Datenbankstand einmal gelesen."""
        d = self.daten()
        if "anton_felder" not in d:
            con = self.b.verbinden()
            try:
                d["anton_felder"] = {z["name"]: dict(z) for z in con.execute("SELECT * FROM anton_feld ORDER BY reihenfolge")}
            finally:
                con.close()
        return d["anton_felder"]

    def feld_def(self, feld):
        """Beschreibung eines Felds: fest (FELDER) oder ein Notizfeld note.<name> als Text, nicht Pflicht."""
        if feld in FELDER:
            return FELDER[feld]
        if not str(feld).startswith("note."):
            raise KeyError(feld)
        a = self.anton_felder().get(feld) or {}
        an = bool(a.get("import"))
        return {"name": a.get("label") or feld[5:].replace("_", " "), "pflicht": False, "art": "text", "an": an,
                "zusatz": True, "import": ("kommt mit dem Import an (Notiz " + feld[5:] + ")") if an
                else "geht mit; kommt an, sobald Anton den Import erweitert"}

    @staticmethod
    def feld_gilt(feld):
        return feld in FELDER or (isinstance(feld, str) and re.fullmatch(r"note\.[a-z0-9_]+", feld) is not None)

    def wert(self, platte, relpfad, feld, d):
        """Eintrag eines Felds für eine Datei oder einen Ordner. Seit 04.11.2026 nur der eigene: Ordnerwerte gehen
        nicht mehr still nach unten, sondern nur über „Vererben“ (vererben). Antwort (Eintrag, Pfad) oder (None, None)."""
        e = d["werte"].get((platte, relpfad), {}).get(feld)
        return (e, relpfad) if e else (None, None)

    def wert_darueber(self, platte, relpfad, feld, d):
        """Nächster Eintrag in einem Ordner darüber (nur als Hinweis im Editor): (Eintrag, Pfad) oder (None, None)."""
        for p in weg_nach_oben(relpfad)[1:]:
            e = d["werte"].get((platte, p), {}).get(feld)
            if e:
                return e, p
        return None, None

    def bestes_datum(self, platte, pfad, d):
        """Bestes Datum (E2) einer Datei bzw. frühestes und spätestes der übernommenen Dateien eines Ordners:
        (von, bis) als ISO-Text oder None."""
        if (platte, pfad) in self.b.dateien:
            x = d["datum"].get((platte, pfad))
            return (x, x) if x else None
        tage = sorted(d["datum"][(platte, r)] for r in self.uebernommene_unter(platte, pfad) if (platte, r) in d["datum"])
        return (tage[0], tage[-1]) if tage else None

    @staticmethod
    def zeitraum_aus(von_bis, ca=False):
        """(von, bis) in ISO → gespeicherter Zeitraum [von, bis, ca_von, ca_bis] in der Schreibweise des Editors."""
        von, bis = (datum_deutsch(x[:10]) for x in von_bis)
        return json.dumps([von, "" if bis == von else bis, ca, ca], ensure_ascii=False)

    def laufnummer(self, platte, ort, relpfad, d):
        """Stelle der Datei unter den übernommenen Dateien des Ordners, an dem das Muster steht (1, 2, …)."""
        schluessel = (platte, ort)
        if schluessel not in d["lfd"]:
            d["lfd"][schluessel] = {r: i for i, r in enumerate(self.uebernommene_unter(platte, ort), 1)}
        return d["lfd"][schluessel].get(relpfad)

    def muster(self, text, platte, relpfad, ort, d):
        if not text:
            return ""
        name = relpfad.rsplit("/", 1)[-1]
        ersatz = {"laufnummer": lambda: str(self.laufnummer(platte, ort, relpfad, d) or ""),
                  "dateiname": lambda: os.path.splitext(name)[0],
                  "datum": lambda: datum_deutsch(d["datum"].get((platte, relpfad), ""))}
        return re.sub(r"\{(laufnummer|dateiname|datum)\}", lambda m: ersatz[m[1]](), text)

    def wert_fuer_datei(self, platte, relpfad, feld, d):
        """Fertiger Wert eines Felds für eine Datei (für Anzeige, Pflichtprüfung und später den Export)."""
        e, ort = self.wert(platte, relpfad, feld, d)
        if not e:
            return ""
        art = self.feld_def(feld)["art"]
        datei = (platte, relpfad) in self.b.dateien
        if art == "zeitraum":
            if datei and e["je_datei"] == "datum":           # je Datei das beste Datum (E2), sonst das gemeinsame
                eigen = d["datum"].get((platte, relpfad))
                if eigen:
                    return datum_deutsch(eigen)
            return zeitraum_text(e["gleich"]) if zeitraum_gueltig(e["gleich"]) else ""
        if art in ("begriff", "begriffe"):
            return begriff_text(feld, e["gleich"])
        # beim Ordner selbst zählt nur der gleichbleibende Teil; der Teil je Datei ist das Muster fürs Vererben
        teil = self.muster(e["je_datei"], platte, relpfad, ort, d) if datei else ""
        return " ".join(x for x in ((e["gleich"] or "").strip(), teil.strip()) if x)

    def erschlossen(self, platte, relpfad, d):
        return all(self.wert_fuer_datei(platte, relpfad, f, d) for f in PFLICHT)

    def zaehlen(self, platte, pfad, d):
        dateien = self.uebernommene_unter(platte, pfad)
        return {"uebernommen": len(dateien), "erschlossen": sum((platte, r) in d["erschlossen"] for r in dateien),
                "zugeordnet": sum(self.zuordnung_von(platte, r, d) is not None for r in dateien)}

    def einzelstueck_von(self, platte, relpfad, d):
        """Ordner, dessen Einzelstück diese Datei als Medium trägt (nächste Zuordnung darüber hat Stufe item), sonst None."""
        z = self.zuordnung_von(platte, relpfad, d)
        return z["pfad"] if z and z["stufe"] == "item" and z["pfad"] != relpfad else None

    def zuordnung_von(self, platte, relpfad, d):
        """Nächste Zuordnung auf dem Weg nach oben (eigene oder die eines Ordners): Eintrag oder None."""
        for p in weg_nach_oben(relpfad):
            z = d["zuordnung"].get((platte, p))
            if z:
                return z
        return None

    # ---- Baum ----

    def ziel_name(self, ziel, boxen=None, ebenen=None):
        o = ordner_ziel_teilen(ziel)
        if o:
            return self.wert_fuer_datei(*o, "titel", self.daten()) or o[1].rsplit("/", 1)[-1] or o[0]
        if boxen is None:
            con = self.b.verbinden()
            try:
                boxen = {f"a:{z[0]}": z[1] for z in con.execute("SELECT anton_id, titel FROM bestandsbox")}
                ebenen = {f"e:{z[0]}": z[1] for z in con.execute("SELECT ebene_id, titel FROM ebene")}
            finally:
                con.close()
        return boxen.get(ziel) or ebenen.get(ziel) or ziel

    def platten(self):
        d = self.daten()
        # zaehler und urteil wie in der Bewertung: der Baum zeigt dieselben Spalten Größe und Entscheidung
        return {"platten": [{"id": p["platte_id"], "volume": p["volume_name"], "etikett": p["etikett_text"] or "",
                             "kopie_von": p["kopie_von"], "traeger": p.get("traeger", ""),
                             "zaehler": self.b.zaehler[(p["platte_id"], "")],
                             "urteil": self.b.urteil(p["platte_id"], ""),
                             **self.zaehlen(p["platte_id"], "", d)} for p in self.b.platten],
                "pflicht": [FELDER[f]["name"] for f in PFLICHT]}

    def kinder(self, platte, ordner, offset=0):
        d = self.daten()
        k = self.b.kinder(platte, ordner, offset=offset)
        namen = {}
        for e in k["ordner"] + k["dateien"]:
            z = d["zuordnung"].get((platte, e["pfad"]))
            if z:
                if z["ziel"] not in namen:
                    namen[z["ziel"]] = self.ziel_name(z["ziel"])
                e["zuordnung"] = {"ziel": z["ziel"], "name": namen[z["ziel"]], "stufe": STUFEN.get(z["stufe"], z["stufe"])}
            e["hinweis"] = (platte, e["pfad"]) in d["hinweise"]
        for o in k["ordner"]:
            o.update(self.zaehlen(platte, o["pfad"], d))
            o["titel"] = self.wert_fuer_datei(platte, o["pfad"], "titel", d)
        for f in k["dateien"]:
            f["uebernommen"] = self.uebernommen(platte, f["pfad"])
            f["erschlossen"] = (platte, f["pfad"]) in d["erschlossen"]
            f["zugeordnet"] = self.zuordnung_von(platte, f["pfad"], d) is not None
            f["titel"] = self.wert_fuer_datei(platte, f["pfad"], "titel", d)
        return k

    # ---- Facetten und Suche ----

    def attribute(self, d):
        """Je übernommener Datei die Merkmale für die Facetten (einmal je Datenbankstand)."""
        if "attr" in d:
            return d["attr"]
        con = self.b.verbinden()
        try:
            vorschlaege = defaultdict(set)
            verworfen = {tuple(z) for z in con.execute(
                "SELECT platte_id, pfad, feld, wert FROM vorschlag_urteil WHERE urteil = 'verworfen'")}
            for p, pf, feld, name, wert in con.execute(
                    "SELECT platte_id, pfad, feld, anton_name, wert FROM vorschlag WHERE schritt IN ('V8', 'V3') "
                    "AND anton_id IS NOT NULL AND feld IN ('schlagwort', 'ort')"):
                if (p, pf, feld, wert) not in verworfen:
                    vorschlaege[(p, pf)].add((feld, name))
        finally:
            con.close()
        attr = {}
        for p, r in d["uebernommen"]:
            info = self.b.dateien[(p, r)]
            mime = info["mime"]
            end = os.path.splitext(r)[1].lower()
            art = ("Foto" if mime.startswith("image/") else "Film" if mime.startswith("video/") else
                   "Dokument" if end in TEXT_ENDUNGEN else "Ton" if mime.startswith("audio/") else "Andere")
            kette = weg_nach_oben(r)
            begriffe = set().union(*(vorschlaege.get((p, x), set()) for x in kette))
            stand = ("zugeordnet" if self.zuordnung_von(p, r, d) else
                     "erschlossen" if (p, r) in d["erschlossen"] else "offen")
            attr[(p, r)] = {
                "jahr": (d["datum"].get((p, r)) or "")[:4], "art": art, "platte": p, "stand": stand,
                "personen": bool(info["bildtyp"]), "duplikate": bool(info["arten"]),
                "hinweis": any((p, x) in d["hinweise"] for x in kette),
                "schlagwort": sorted(n for f, n in begriffe if f == "schlagwort"),
                "ort": sorted(n for f, n in begriffe if f == "ort"),
                "suchtext": (r + " " + self.wert_fuer_datei(p, r, "titel", d)).casefold()}
        d["attr"] = attr
        return attr

    def suche(self, anfrage):
        """Trefferliste mit Facetten (Anzahlen über den Treffern). anfrage: q, nur (dateien/ordner), jahr, art,
        platte, stand, personen, hinweis, duplikate, schlagwort, ort."""
        d = self.daten()
        attr = self.attribute(d)
        q = (anfrage.get("q") or "").strip().casefold()
        f = {k: anfrage.get(k) for k in ("jahr", "art", "platte", "stand", "schlagwort", "ort") if anfrage.get(k)}
        schalter = [k for k in ("personen", "hinweis", "duplikate") if anfrage.get(k)]
        treffer = []
        for k, a in attr.items():
            if q and not all(w in a["suchtext"] for w in q.split()):
                continue
            if any((v not in a[n]) if isinstance(a[n], list) else (a[n] != v) for n, v in f.items()):
                continue
            if any(not a[s] for s in schalter):
                continue
            treffer.append(k)
        facetten = {n: Counter() for n in ("jahr", "art", "platte", "stand", "schlagwort", "ort")}
        zaehler = Counter()
        for k in treffer:
            a = attr[k]
            for n in ("jahr", "art", "platte", "stand"):
                facetten[n][a[n] or "ohne"] += 1
            for n in ("schlagwort", "ort"):
                facetten[n].update(a[n])
            for s in ("personen", "hinweis", "duplikate"):
                zaehler[s] += a[s]
        aus = {"gesamt": len(treffer), "facetten": {n: c.most_common(12 if n in ("schlagwort", "ort") else 40)
                                                   for n, c in facetten.items()}, "schalter": dict(zaehler)}
        if anfrage.get("ansicht", "baum") == "baum":
            aus["baum"] = self.trefferbaum(treffer, d, ohne_dateien=anfrage.get("nur") == "ordner")
            return aus
        if anfrage.get("nur") == "ordner":
            je = Counter((p, elternordner(r)) for p, r in treffer)
            aus["ordner"] = [{"platte": p, "pfad": o, "name": o.rsplit("/", 1)[-1] or p, "treffer": n,
                              "zaehler": self.b.zaehler[(p, o)], "urteil": self.b.urteil(p, o),
                              "titel": self.wert_fuer_datei(p, o, "titel", d),
                              **self.zaehlen(p, o, d)} for (p, o), n in je.most_common(300)]
        else:
            treffer.sort(key=lambda k: (k[0], k[1].casefold()))
            aus["dateien"] = [{**self.b.datei_kurz(p, r), "ordner": elternordner(r), "titel": self.wert_fuer_datei(p, r, "titel", d),
                               "stand": attr[(p, r)]["stand"], "art": attr[(p, r)]["art"]} for p, r in treffer[:400]]
        return aus

    def trefferbaum(self, treffer, d, ohne_dateien=False, grenze_dateien=1500, grenze_ordner=1500):
        """Treffer mit ihrer Ordnerstruktur (Entscheidung 04.11.2026): Platten und Ordner, die Treffer enthalten, mit
        Trefferzahl, darunter die Dateien; alles andere bleibt weg. Flache Liste, Eltern vor Kindern."""
        je_ordner = Counter()
        for p, r in treffer:
            for o in weg_nach_oben(elternordner(r)):
                je_ordner[(p, o)] += 1
        ordner = sorted(je_ordner, key=lambda k: (k[0], k[1].count("/") if k[1] else -1, k[1].casefold()))
        knapp = len(ordner) > grenze_ordner
        ordner = ordner[:grenze_ordner]
        knoten = []
        for p, o in ordner:
            platte = self.b.platte(p) or {}
            knoten.append({"art": "ordner" if o else "platte", "platte": p, "pfad": o,
                           "name": o.rsplit("/", 1)[-1] if o else p, "eltern": elternordner(o) if o else None,
                           "treffer": je_ordner[(p, o)], "volume": platte.get("volume_name") or "",
                           "zaehler": self.b.zaehler[(p, o)], "urteil": self.b.urteil(p, o), **self.zaehlen(p, o, d),
                           "titel": self.wert_fuer_datei(p, o, "titel", d) if o else ""})
        dateien = [] if ohne_dateien else sorted(treffer, key=lambda k: (k[0], k[1].casefold()))[:grenze_dateien]
        for p, r in dateien:
            knoten.append({**self.b.datei_kurz(p, r), "art": "datei", "eltern": elternordner(r), "uebernommen": True,
                           "erschlossen": (p, r) in d["erschlossen"], "zugeordnet": self.zuordnung_von(p, r, d) is not None,
                           "titel": self.wert_fuer_datei(p, r, "titel", d)})
        return {"knoten": knoten, "dateien_gekuerzt": not ohne_dateien and len(treffer) > grenze_dateien,
                "ordner_gekuerzt": knapp}

    # ---- Angaben zur Auswahl ----

    def vorschlaege(self, platte, pfad, d):
        """Vorschläge je Feld für ein Element (ohne verworfene); gleiche Werte aus mehreren Schritten zusammengefasst.
        Akteur:in, Ort und Schlagworte nur aus dem Normdatenabgleich (V8, V3). Dazu, wie die Facetten sie zählen, die
        Normdaten-Vorschläge der Ordner darüber und bei einem Ordner die der Elemente darin (Entscheidung 04.11.2026)."""
        kette = weg_nach_oben(pfad)
        ordner = (platte, pfad) not in self.b.dateien
        con = self.b.verbinden()
        try:
            zeilen = con.execute(
                f"SELECT * FROM vorschlag WHERE platte_id = ? AND (pfad = ? OR (pfad IN ({','.join('?' * len(kette))}) "
                "AND feld IN ('akteur', 'ort', 'schlagwort'))) ORDER BY score DESC", (platte, pfad, *kette)).fetchall()
            if ordner:                                       # darin: je Begriff, in wie vielen Elementen er vorkommt
                darin = con.execute(
                    f"SELECT * FROM vorschlag WHERE platte_id = ? AND pfad != ? AND {DARUNTER} AND schritt IN ('V8', 'V3') "
                    "AND feld IN ('akteur', 'ort', 'schlagwort') ORDER BY score DESC", (platte, pfad, *darunter(pfad))).fetchall()
                je = defaultdict(list)
                for z in darin:
                    je[(z["feld"], z["anton_id"] or norm(z["wert"]))].append(z)
                for liste in je.values():
                    z = dict(liste[0])
                    orte = list(dict.fromkeys(x["pfad"].rsplit("/", 1)[-1] for x in liste))
                    z["beleg"] = (f"darin bei {len(orte)} {'Element' if len(orte) == 1 else 'Elementen'}: "
                                  + ", ".join(orte[:3]) + (" …" if len(orte) > 3 else ""))
                    z["darin"] = len(orte)
                    zeilen.append(z)
            urteile = {(z["feld"], z["wert"]): z["urteil"] for z in con.execute(
                "SELECT feld, wert, urteil FROM vorschlag_urteil WHERE platte_id = ? AND pfad = ?", (platte, pfad))}
        finally:
            con.close()
        erg = defaultdict(dict)
        for z in zeilen:
            feld = VORSCHLAG_FELD.get(z["feld"])
            if not feld or urteile.get((z["feld"], z["wert"])) == "verworfen":
                continue
            if self.feld_def(feld)["art"] in ("begriff", "begriffe") and z["schritt"] not in ("V8", "V3"):
                continue
            schluessel = (z["anton_id"], "") if z["anton_id"] else (None, norm(z["wert"]))
            if z["pfad"] != pfad and not (isinstance(z, dict) and z.get("darin")):   # von einem Ordner darüber
                z = {**dict(z), "beleg": f"aus Ordner „{z['pfad'].rsplit('/', 1)[-1] or platte}“: {z['beleg'] or ''}"}
            alt = erg[feld].get(schluessel)
            if alt:
                alt["quellen"].append(z["quelle"])
                alt["belege"].append(z["beleg"] or "")
                alt["score"] = max(alt["score"], z["score"] or 0)
                continue
            erg[feld][schluessel] = {"feld": z["feld"], "wert": z["wert"], "anzeige": (
                zeitraum_text(z["wert"]) if feld == "zeitraum" else z["anton_name"] or z["wert"]),
                "anton_id": z["anton_id"], "quellen": [z["quelle"]], "belege": [z["beleg"] or ""],
                "score": z["score"] or 0, "schritt": z["schritt"],
                "angenommen": urteile.get((z["feld"], z["wert"])) == "angenommen"}
        erg = {feld: sorted(v.values(), key=lambda x: -x["score"])[:8] for feld, v in erg.items()}
        for feld, auch in VORSCHLAG_AUCH.items():
            if feld in erg:
                erg[auch] = [dict(v) for v in erg[feld]]
        return erg

    def vorschlaege_mehrere(self, ziele, d, grenze=300):
        """Mehrfachauswahl: Normdaten-Vorschläge (Akteur:in, Ort, Schlagworte) der gewählten Elemente zusammengefasst,
        je mit der Zahl der Elemente, die ihn haben. Titel, Laufzeit und Inhalt bleiben je Element."""
        zusammen = defaultdict(dict)
        for platte, pfad in ziele[:grenze]:
            for feld, liste in self.vorschlaege(platte, pfad, d).items():
                if self.feld_def(feld)["art"] not in ("begriff", "begriffe"):
                    continue
                for v in liste:
                    k = v["anton_id"] or norm(v["wert"])
                    e = zusammen[feld].setdefault(k, {**v, "anzahl": 0, "angenommen": False})
                    e["anzahl"] += 1
                    e["score"] = max(e["score"], v["score"])
        n = min(len(ziele), grenze)
        for feld, werte in zusammen.items():
            for v in werte.values():
                v["belege"] = [f"bei {v['anzahl']} von {n} gewählten Elementen"] + v["belege"][:2]
        return {feld: sorted(w.values(), key=lambda x: (-x["anzahl"], -x["score"]))[:8] for feld, w in zusammen.items()}

    def verwandte(self, platte, ordner, d, grenze=40):
        """Verwandte Ordner (V10) ohne abgewählte, je mit Grund, Score und Stand."""
        con = self.b.verbinden()
        try:
            zeilen = con.execute("SELECT * FROM verwandt WHERE (platte_a = ? AND pfad_a = ?) OR (platte_b = ? AND pfad_b = ?)",
                                 (platte, ordner, platte, ordner)).fetchall()
            nicht = {tuple(z) for z in con.execute("SELECT platte_a, pfad_a, platte_b, pfad_b FROM nicht_verwandt")}
        finally:
            con.close()
        partner = {}
        for z in zeilen:
            a, b = (z["platte_a"], z["pfad_a"]), (z["platte_b"], z["pfad_b"])
            anderer = b if a == (platte, ordner) else a
            if (*min(a, b), *max(a, b)) in nicht:
                continue
            e = partner.setdefault(anderer, {"platte": anderer[0], "pfad": anderer[1], "gruende": [], "score": 0})
            e["gruende"].append({"grund": z["grund"], "beleg": z["beleg"], "score": z["score"]})
            e["score"] = max(e["score"], z["score"])
        erg = []
        kandidaten = []
        for (p, o), e in partner.items():
            if self.b.platte(p) is not None:
                kandidaten.append(((p, o), e, self.zaehlen(p, o, d)))
        kandidaten.sort(key=lambda x: (not x[2]["uebernommen"], -x[1]["score"]))     # Übernommenes zuerst
        for (p, o), e, z in kandidaten[:grenze]:
            gesamt = len([r for r in self.b.dateien_unter(p, o) if not self.b.dateien[(p, r)]["system"]])
            titel, ort = self.wert(p, o, "titel", d)
            erg.append({**e, "name": o.rsplit("/", 1)[-1] or p, **z, "dateien": gesamt,
                        "titel": titel["gleich"] if titel else "", "titel_eigen": ort == o,
                        "thumbs": [self.b.vorschauen[self.b.dateien[(p, r)]["sha256"]]
                                   for r in self.b.dateien_in.get((p, o), [])[:3]
                                   if self.b.dateien[(p, r)]["sha256"] in self.b.vorschauen]})
        return erg

    def angaben(self, ziele):
        d = self.daten()
        dateien = []
        for platte, pfad in ziele:
            dateien += [(platte, r) for r in self.uebernommene_unter(platte, pfad)]
        dateien = list(dict.fromkeys(dateien))
        if not dateien:
            raise ValueError("In der Auswahl ist nichts übernommen.")
        daten = [self.b.dateien[k] for k in dateien]
        tage = sorted(d["datum"][k] for k in dateien if k in d["datum"])
        menge = set(dateien)
        con = self.b.verbinden()
        try:
            kameras = Counter()
            for platte in {p for p, _ in dateien}:
                for z in con.execute("SELECT relpfad, kamera FROM metadaten WHERE platte_id = ? AND kamera IS NOT NULL "
                                     "AND kamera != ''", (platte,)):
                    if (platte, z[0]) in menge:
                        kameras[z[1]] += 1
            stand_vorlauf = {z[0]: z[1] for z in con.execute("SELECT schritt, zeit FROM vorlauf_stand")}
            # Sujet (V3, englisch, Kontext): Datei ihre Begriffe; mehrere Fotos: Anteil der Fotos je Begriff
            shas = list({x["sha256"] for x in daten if x["sha256"]})
            sujet_je = {}
            for i in range(0, len(shas), 900):
                teil = shas[i:i + 900]
                for sha, begriffe in con.execute(f"SELECT sha256, begriffe FROM sujet WHERE sha256 IN "
                                                 f"({','.join('?' * len(teil))})", teil):
                    sujet_je[sha] = json.loads(begriffe or "[]")
        finally:
            con.close()
        # kassierte Kopien (gleicher Inhalt anderswo, dort kassiert): nur Kontext
        kassiert = set()
        for (platte, r), info in zip(dateien, daten):
            for k2 in self.b.gleicher_inhalt.get(info["sha256"], []) if info["sha256"] else []:
                w = self.b.wirksam_je_datei.get(k2)
                if k2 != (platte, r) and w and w[0] == "kassieren":
                    kassiert.add(k2)
        # deutsch, wenn vorhanden ([englisch, score, deutsch]); sonst „a factory hall“ → „factory hall“
        kurz = lambda x: (x[2] if len(x) > 2 and x[2] else re.sub(r"^(a|an) ", "", x[0]))
        mit_sujet = [sujet_je[x["sha256"]] for x in daten if x["sha256"] in sujet_je]
        if len(mit_sujet) == 1:
            sujet = [[kurz(x), x[1]] for x in mit_sujet[0]]
        else:
            anteil = Counter(kurz(x) for liste in mit_sujet for x in liste[:3])
            sujet = [[b, n / len(mit_sujet)] for b, n in anteil.most_common(6) if n / len(mit_sujet) >= 0.15]
        einzeln = len(ziele) == 1
        platte0, pfad0 = ziele[0]
        art0 = ("datei" if (platte0, pfad0) in self.b.dateien else "ordner") if einzeln else "auswahl"
        felder = {}
        # Notizfelder mit Wert an einem Ziel erscheinen von selbst; weitere wählt man im Dropdown (anton_felder)
        mit_wert = {f for z in ziele for f in d["werte"].get(z, {}) if f.startswith("note.")}
        for feld in list(FELDER) + sorted(mit_wert):
            f = self.feld_def(feld)
            eigen = d["werte"].get((platte0, pfad0), {}).get(feld) if einzeln else None
            geerbt = None                                    # nur Hinweis: Wert eines Ordners darüber (nicht wirksam)
            if einzeln and pfad0 != "":
                e, ort = self.wert_darueber(platte0, pfad0, feld, d)
                if e and (platte0, pfad0) in self.b.dateien:     # Datei: so, wie „Vererben“ es ihr geben würde
                    e = {**e, "gleich": self.wert_fuer_erbe(platte0, ort, pfad0, feld, e, d), "je_datei": ""}
                geerbt = {**e, "ort": ort, "text": self.wert_anzeige(feld, e)} if e else None
            if not einzeln:                                  # mehrere: gemeinsamer Wert, wenn überall gleich
                eintraege = {json.dumps(d["werte"].get(z, {}).get(feld, {}).get("gleich")) for z in ziele}
                if len(eintraege) == 1:
                    eigen = d["werte"].get(ziele[0], {}).get(feld)
            belegt = sum(1 for z in ziele if d["werte"].get(z, {}).get(feld))
            felder[feld] = {**f, "eigen": eigen, "geerbt": geerbt, "belegt": belegt,
                            "beispiele": [{"name": r.rsplit("/", 1)[-1], "wert": self.wert_fuer_datei(p, r, feld, d)}
                                          for p, r in dateien[:3]]}
        p = self.b.platte(platte0) or {}
        vorschlaege = self.vorschlaege(platte0, pfad0, d) if einzeln else self.vorschlaege_mehrere(ziele, d)
        verwandte_ordner = pfad0 if art0 == "ordner" else elternordner(pfad0)
        zuordnung = self.zuordnung_von(platte0, pfad0, d) if einzeln else None
        # bestes Datum je gewähltem Eintrag (Mehrfachauswahl: jeder bekommt sein eigenes, Entscheidung 04.11.2026)
        je_eintrag = [self.bestes_datum(pl, pf, d) for pl, pf in ziele]
        bilder = []                                          # Vorschaubilder mit Fundort (Vergrößern, Datei zeigen)
        for (pl, r), x in zip(dateien, daten):
            if x["sha256"] in self.b.vorschauen:
                bilder.append({"thumb": self.b.vorschauen[x["sha256"]], "platte": pl, "pfad": r, "name": r.rsplit("/", 1)[-1]})
                if len(bilder) >= 60:
                    break
        if art0 == "datei":
            stufe = "Einzelstück"
        elif einzeln and (platte0, pfad0) in d["zuordnung"]:
            z0 = d["zuordnung"][(platte0, pfad0)]
            stufe = z0.get("stufe_name") or STUFEN.get(z0["stufe"], z0["stufe"])
        else:
            stufe = ""
        return {
            "ziele": [{"platte": p_, "pfad": pf} for p_, pf in ziele], "einzeln": einzeln, "art": art0,
            "name": (pfad0.rsplit("/", 1)[-1] or f"{platte0} · {p.get('volume_name') or ''}") if einzeln
                    else f"{len(ziele)} Elemente",
            "dateien": len(dateien), "erschlossen": sum(k in d["erschlossen"] for k in dateien),
            "zugeordnet": sum(self.zuordnung_von(*k, d) is not None for k in dateien),
            # Elemente der Auswahl mit eigener Zuordnung (Knopf „N Zuordnungen lösen“ bei Mehrfachauswahl)
            "selbst_zugeordnet": sum(k in d["zuordnung"] for k in dict.fromkeys(ziele)),
            "zeitraum": [tage[0], tage[-1]] if tage else None,
            "kameras": kameras.most_common(3), "personen": sum(bool(x["bildtyp"]) for x in daten),
            "fotos": sum(x["mime"].startswith("image/") for x in daten),
            "dokumente": sum(os.path.splitext(r)[1].lower() in TEXT_ENDUNGEN for _, r in dateien),
            "thumbs": [b["thumb"] for b in bilder[:6]], "bilder": bilder, "sujet": sujet, "sujet_fotos": len(mit_sujet),
            "datum_je_eintrag": {"mit": sum(x is not None for x in je_eintrag), "von": len(ziele)},
            "stufe": stufe, "ordner_erschlossen": (art0 != "datei" and einzeln
                                                   and all(self.wert_fuer_datei(platte0, pfad0, f, d) for f in PFLICHT)),
            "volume": p.get("volume_name") or "",
            "kassierte_kopien": len(kassiert), "etikett": p.get("etikett_text") or "",
            "hinweise": self.b.hinweise(platte0, pfad0) if einzeln else None,
            "felder": felder, "pflicht": PFLICHT, "vorschlaege": vorschlaege,
            "verwandte": self.verwandte(platte0, verwandte_ordner, d, grenze=6) if einzeln else [],
            "zuordnung": ({**zuordnung, "name": self.ziel_name(zuordnung["ziel"]),
                           "stufe_name": STUFEN.get(zuordnung["stufe"], zuordnung["stufe"])} if zuordnung else None),
            "vorlauf": stand_vorlauf,
            "anton_felder": [{"name": n, "label": a["label"], "import": bool(a["import"])} for n, a in self.anton_felder().items()]}

    def wert_anzeige(self, feld, e):
        art = self.feld_def(feld)["art"]
        if art == "zeitraum":
            return zeitraum_text(e["gleich"]) + (" · je Datei Aufnahmedatum" if e.get("je_datei") == "datum" else "")
        if art in ("begriff", "begriffe"):
            return begriff_text(feld, e["gleich"])
        return " ".join(x for x in (e["gleich"] or "", f"· je Datei „{e['je_datei']}“" if e.get("je_datei") else "") if x)

    def gleich_aus(self, feld, wert):
        """Eingabe aus der Oberfläche → gespeicherter Text des gleichbleibenden Teils ("" = leer)."""
        gleich = wert.get("gleich")
        art = self.feld_def(feld)["art"]
        if art == "zeitraum":
            if isinstance(gleich, list):
                return json.dumps(gleich, ensure_ascii=False) if any(gleich[:2]) else ""
            return (gleich or "").strip()
        if art == "begriff":
            if isinstance(gleich, dict) and (gleich.get("name") or "").strip():
                return json.dumps({"name": gleich["name"].strip(), "anton_id": gleich.get("anton_id")}, ensure_ascii=False)
            return ""
        if art == "begriffe":
            if self.feld_def(feld).get("anton") == "language":       # Sprachen: Name und Code aus SPRACHEN
                codes = dict(SPRACHEN)
                liste = [{"name": codes[x["code"]], "code": x["code"]} for x in (gleich or [])
                         if isinstance(x, dict) and x.get("code") in codes]
                return json.dumps(liste, ensure_ascii=False) if liste else ""
            liste = [{"name": x["name"].strip(), "anton_id": x.get("anton_id")} for x in (gleich or [])
                     if isinstance(x, dict) and (x.get("name") or "").strip()]
            return json.dumps(liste, ensure_ascii=False) if liste else ""
        return (gleich or "").strip()

    def speichern(self, ziele, felder, wer="", angenommen=(), nur_leere=()):
        """Felder für Ordner oder Dateien schreiben; leere Felder entfernen den eigenen Wert (dann gilt der darüber).
        Bei mehreren einzelnen Dateien wird {laufnummer} je Datei aufgelöst (Stelle in der Auswahl). angenommen:
        übernommene Vorschläge [{feld, wert, anton_id, beleg}] → Urteil und bei Normdaten ein gelerntes Synonym.
        nur_leere: Felder, die nur dort geschrieben werden, wo noch kein eigener Wert steht (Rückfrage im Tool).
        Antwort mit den verwandten Ordnern, wenn der Titel eines einzelnen Ordners geändert wurde (Abgleich)."""
        if not ziele:
            raise ValueError("Nichts gewählt.")
        d = self.daten()
        for platte, pfad in ziele:
            if not self.uebernommene_unter(platte, pfad):
                raise ValueError(f"{platte} / {pfad or '(Platte)'} enthält nichts Übernommenes.")
        nur_dateien = len(ziele) > 1 and all(z in self.b.dateien for z in ziele)
        # Zeitraum „bestes Datum je Eintrag“: jedem Ziel sein eigenes Datum, sonst das eingetippte gemeinsame
        zr = felder.get("zeitraum") or {}
        je_eintrag = {}
        if zr.get("je_eintrag"):
            ca = bool((zr.get("gleich") or [0, 0, False])[2:3] and zr["gleich"][2])
            for z in ziele:
                b = self.bestes_datum(*z, d)
                if b:
                    je_eintrag[z] = self.zeitraum_aus(b, ca)
        jetzt = zeit()
        geaendert, titel_geaendert = 0, False
        with self.b.sperre, self.b.schreibend() as con:
            for i, (platte, pfad) in enumerate(sorted(ziele, key=lambda z: (z[0], z[1].casefold())), 1):
                for feld, wert in felder.items():
                    if not self.feld_gilt(feld):
                        continue
                    gleich = self.gleich_aus(feld, wert)
                    if feld == "zeitraum" and (platte, pfad) in je_eintrag:
                        gleich = je_eintrag[(platte, pfad)]
                    elif feld == "zeitraum" and zr.get("je_eintrag") and not gleich:
                        continue                             # ohne eigenes Datum und ohne Eingabe: bisherigen Wert lassen
                    je = (wert.get("je_datei") or "").strip() if self.feld_def(feld)["art"] in ("text", "zeitraum") else ""
                    if nur_dateien and je and feld != "zeitraum":
                        je = je.replace("{laufnummer}", str(i))
                    alt = d["werte"].get((platte, pfad), {}).get(feld)
                    if alt and feld in nur_leere:
                        continue
                    if (alt and (alt["gleich"] or "") == gleich and (alt["je_datei"] or "") == je) or \
                            (not alt and not gleich and not je):     # unverändert oder leer und war leer
                        continue
                    if gleich or je:
                        con.execute("INSERT OR REPLACE INTO erschliessung VALUES (?,?,?,?,?,?,?,?)",
                                    (platte, pfad, feld, gleich, je, wert.get("quelle") or "eigen", wer.strip(), jetzt))
                    else:
                        con.execute("DELETE FROM erschliessung WHERE platte_id = ? AND pfad = ? AND feld = ?",
                                    (platte, pfad, feld))
                    alt_text = " | ".join(x for x in ((alt or {}).get("gleich"), (alt or {}).get("je_datei")) if x)
                    con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                                (jetzt, "Erschließung", f"{platte}:{pfad}", feld, alt_text,
                                 " | ".join(x for x in (gleich, je) if x) or "entfernt"))
                    geaendert += 1
                    titel_geaendert = titel_geaendert or (feld == "titel" and bool(gleich))
            if len(ziele) == 1:
                platte, pfad = ziele[0]
                for a in angenommen or ():
                    self.urteil_schreiben(con, platte, pfad, a, "angenommen", wer, jetzt)
        with self.b.sperre:
            self.b.stand = self.b.db_stand()             # eigene Änderung: Bestand muss nicht neu laden
        antwort = {"ok": True, "geaendert": geaendert, "verwandte": []}
        if titel_geaendert and len(ziele) == 1 and ziele[0] not in self.b.dateien:
            antwort["verwandte"] = self.verwandte(*ziele[0], self.daten())
        return antwort

    # ---- Vererben (Entscheidung 04.11.2026) ----

    def vererben_ziele(self, platte, pfad, umfang):
        """Elemente unter einem Ordner, die beim Vererben einen Wert bekommen. umfang: dateien (bool), ordner (bool),
        tief (bool: alle Ebenen, sonst nur direkt enthaltene). Nur Übernommenes; Ordner nur mit Übernommenem."""
        dateien, ordner = [], []
        stapel = [pfad]
        while stapel:
            o = stapel.pop()
            if umfang.get("dateien"):
                dateien += [r for r in self.b.dateien_in.get((platte, o), []) if self.uebernommen(platte, r)]
            for u in self.b.unterordner.get((platte, o), ()):
                if not self.uebernommene_unter(platte, u):
                    continue
                if umfang.get("ordner"):
                    ordner.append(u)
                if umfang.get("tief"):
                    stapel.append(u)
        return sorted(dateien, key=str.casefold), sorted(ordner, key=str.casefold)

    def vererben_pruefen(self, platte, pfad, felder, umfang):
        """Für den Dialog: wie viele Dateien und Ordner betroffen sind und wie viele davon schon eigene Werte haben."""
        d = self.daten()
        dateien, ordner = self.vererben_ziele(platte, pfad, umfang)
        felder = [f for f in felder if self.feld_gilt(f) and d["werte"].get((platte, pfad), {}).get(f)]
        belegt = sum(any(d["werte"].get((platte, x), {}).get(f) for f in felder) for x in dateien + ordner)
        return {"dateien": len(dateien), "ordner": len(ordner), "belegt": belegt, "felder": felder,
                "leer": [FELDER[f]["name"] for f in FELDER if not d["werte"].get((platte, pfad), {}).get(f)]}

    def wert_fuer_erbe(self, platte, ordner, relpfad, feld, e, d):
        """Was eine Datei vom Eintrag e eines Ordners erbt: Teil je Datei aufgelöst ({laufnummer} zählt im Ordner),
        „Aufnahmedatum je Datei“ als ihr eigenes bestes Datum, sonst der gleichbleibende Teil."""
        art = self.feld_def(feld)["art"]
        if art == "text":
            teil = self.muster(e["je_datei"], platte, relpfad, ordner, d)
            return " ".join(x for x in ((e["gleich"] or "").strip(), teil.strip()) if x)
        if art == "zeitraum" and e["je_datei"] == "datum" and (platte, relpfad) in d["datum"]:
            return self.zeitraum_aus((d["datum"][(platte, relpfad)],) * 2)
        return e["gleich"]

    def vererben(self, platte, pfad, felder, umfang, ueberschreiben=False, wer="", zeitraum_je_datei=None):
        """Schreibt die Werte eines Ordners (oder der Platte) als eigene Werte in die Dateien und Unterordner darunter.
        Dateien bekommen fertige Werte: Teil je Datei aufgelöst ({laufnummer} zählt im Ordner, an dem vererbt wird),
        „Aufnahmedatum je Datei“ wird das eigene beste Datum. Unterordner bekommen den Eintrag unverändert (das Muster
        bleibt für ihre Dateien). ueberschreiben=False füllt nur leere Felder. Jede Angabe wird protokolliert."""
        if (platte, pfad) in self.b.dateien:
            raise ValueError("Vererben geht nur von einem Ordner oder einem Datenträger aus.")
        d = self.daten()
        quelle = {f: d["werte"].get((platte, pfad), {}).get(f) for f in felder if self.feld_gilt(f)}
        quelle = {f: e for f, e in quelle.items() if e}
        if not quelle:
            raise ValueError("Die gewählten Felder sind hier leer; zuerst ausfüllen und speichern.")
        if "zeitraum" in quelle and zeitraum_je_datei is not None:   # Wahl im Dialog gilt vor dem gespeicherten Muster
            quelle["zeitraum"] = {**quelle["zeitraum"], "je_datei": "datum" if zeitraum_je_datei else ""}
        dateien, ordner = self.vererben_ziele(platte, pfad, umfang)
        if not dateien and not ordner:
            raise ValueError("Darunter liegt nichts Übernommenes, das erben könnte.")
        herkunft, jetzt = f"vererbt:{platte}:{pfad}", zeit()
        zeilen = []
        for feld, e in quelle.items():
            for r in dateien:
                zeilen.append((r, feld, self.wert_fuer_erbe(platte, pfad, r, feld, e, d), ""))
            for o in ordner:
                zeilen.append((o, feld, e["gleich"], e["je_datei"] or ""))
        geschrieben = uebersprungen = 0
        with self.b.sperre, self.b.schreibend() as con:
            for ziel, feld, gleich, je in zeilen:
                alt = d["werte"].get((platte, ziel), {}).get(feld)
                if alt and not ueberschreiben:
                    uebersprungen += 1
                    continue
                if alt and (alt["gleich"] or "") == (gleich or "") and (alt["je_datei"] or "") == je:
                    continue
                con.execute("INSERT OR REPLACE INTO erschliessung VALUES (?,?,?,?,?,?,?,?)",
                            (platte, ziel, feld, gleich, je, herkunft, wer.strip(), jetzt))
                con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                            (jetzt, "Erschließung", f"{platte}:{ziel}", feld,
                             " | ".join(x for x in ((alt or {}).get("gleich"), (alt or {}).get("je_datei")) if x),
                             f"vererbt von {platte}:{pfad}: " + " | ".join(x for x in (gleich, je) if x)))
                geschrieben += 1
        with self.b.sperre:
            self.b.stand = self.b.db_stand()
        return {"ok": True, "geschrieben": geschrieben, "uebersprungen": uebersprungen,
                "dateien": len(dateien), "ordner": len(ordner)}

    def urteil_schreiben(self, con, platte, pfad, v, urteil, wer, jetzt):
        """Urteil über einen Vorschlag; bei Normdaten (Anton-ID und Wort im Beleg) gelerntes Synonym oder Ausschluss."""
        feld, wert = v.get("feld"), v.get("wert")
        if not feld or wert is None:
            return
        con.execute("INSERT OR REPLACE INTO vorschlag_urteil VALUES (?,?,?,?,?,?,?)",
                    (platte, pfad, feld, wert, urteil, wer.strip(), jetzt))
        con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                    (jetzt, "Erschließung", f"{platte}:{pfad}", f"vorschlag {feld}", "", f"{urteil}: {wert}"))
        art = {"schlagwort": "keyword", "ort": "place", "akteur": "actor"}.get(feld)
        wort = norm(beleg_wort(v.get("beleg") or ""))
        if art and v.get("anton_id") and wort:
            con.execute("INSERT OR REPLACE INTO begriff_gelernt VALUES (?,?,?,?,?,?,?)",
                        (art, wort, int(v["anton_id"]), wert, 1 if urteil == "verworfen" else 0, wer.strip(), jetzt))
            con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                        (jetzt, "Erschließung", f"Begriff {art}", wort, "",
                         f"{'Ausschluss' if urteil == 'verworfen' else 'Synonym'}: {wert} (Anton {v['anton_id']})"))

    def verwerfen(self, platte, pfad, vorschlag, wer=""):
        jetzt = zeit()
        with self.b.sperre, self.b.schreibend() as con:
            self.urteil_schreiben(con, platte, pfad, vorschlag, "verworfen", wer, jetzt)
        with self.b.sperre:
            self.b.stand = self.b.db_stand()
        return {"ok": True}

    # ---- Abgleich mit Verwandten ----

    def abgleichen(self, quelle, ziele, abgewaehlt, felder, wer=""):
        """Übernimmt die gewählten Felder des Quellordners in die gewählten verwandten Ordner (nur Übernommenes, nie
        Kassiertes); abgewählte Treffer merkt sich das Projekt als „nicht verwandt“."""
        d = self.daten()
        q = (quelle["platte"], quelle["pfad"])
        werte = {f: d["werte"].get(q, {}).get(f) for f in felder if self.feld_gilt(f)}
        werte = {f: e for f, e in werte.items() if e}
        jetzt, geschrieben = zeit(), 0
        with self.b.sperre, self.b.schreibend() as con:
            for z in ziele:
                k = (z["platte"], z["pfad"])
                if k == q or not self.uebernommene_unter(*k):
                    continue
                for feld, e in werte.items():
                    alt = d["werte"].get(k, {}).get(feld)
                    con.execute("INSERT OR REPLACE INTO erschliessung VALUES (?,?,?,?,?,?,?,?)",
                                (k[0], k[1], feld, e["gleich"], e["je_datei"], f"abgleich:{q[0]}:{q[1]}", wer.strip(), jetzt))
                    con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                                (jetzt, "Erschließung", f"{k[0]}:{k[1]}", feld,
                                 " | ".join(x for x in ((alt or {}).get("gleich"), (alt or {}).get("je_datei")) if x),
                                 f"aus Abgleich mit {q[0]}:{q[1]}: " + " | ".join(x for x in (e["gleich"], e["je_datei"]) if x)))
                    geschrieben += 1
            for z in abgewaehlt:
                k = (z["platte"], z["pfad"])
                a, b = min(q, k), max(q, k)
                con.execute("INSERT OR REPLACE INTO nicht_verwandt VALUES (?,?,?,?,?,?)", (*a, *b, wer.strip(), jetzt))
                con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                            (jetzt, "Erschließung", f"{q[0]}:{q[1]}", "nicht verwandt", "", f"{k[0]}:{k[1]}"))
        with self.b.sperre:
            self.b.stand = self.b.db_stand()
        return {"ok": True, "geschrieben": geschrieben}

    # ---- Zuordnen ----

    def stufe_darunter(self, stufe):
        return "file" if stufe in ("class", "file") else ""

    def zuordnen_pruefen(self, ziele, ziel, stufen=None):
        """Für den Dialog: je Ordner der Auswahl samt Unterordnern (mit Übernommenem) die Stufe (gewählt in stufen,
        sonst Vorgabe), die Zahl der Einzelstücke und was fehlt; dazu, ob alle Dateien erschlossen sind. Ein Ordner
        als Einzelstück („item“) nimmt alle Dateien darunter als Medien auf: keine Unterordner-Ebenen, die Dateien
        brauchen keine eigenen Werte."""
        d = self.daten()
        stufen = stufen or {}
        im_einzelstueck = set()
        self.ziel_pruefen(ziel)
        if ordner_ziel_teilen(ziel) and any((platte, pfad) not in self.b.dateien for platte, pfad in ziele):
            raise ValueError("In einen Ordner, der eine eigene Einheit ist, lassen sich nur einzelne Dateien zuordnen, "
                             "keine Ordner.")
        ordner, dateien_direkt, alle = [], [], []
        for platte, pfad in ziele:
            if (platte, pfad) in self.b.dateien:
                if self.uebernommen(platte, pfad):
                    dateien_direkt.append((platte, pfad))
                    alle.append((platte, pfad))
                continue
            stapel = [(pfad, "file", 0)]
            while stapel:
                o, stufe, tiefe = stapel.pop()
                stufe = stufen.get(f"{platte}|{o}", stufe)
                dateien = self.uebernommene_unter(platte, o)
                if not dateien:
                    continue
                eigen = [r for r in self.b.dateien_in.get((platte, o), []) if self.uebernommen(platte, r)]
                titel = d["werte"].get((platte, o), {}).get("titel")
                ordner.append({"platte": platte, "pfad": o, "name": o.rsplit("/", 1)[-1] or platte, "tiefe": tiefe,
                               "stufe": stufe, "dateien": len(dateien), "direkt": len(eigen),
                               "titel": self.wert_fuer_datei(platte, o, "titel", d) if titel else "",
                               "fehlt": self.ebene_fehlt(platte, o, d, einzelstueck=stufe == "item")})
                if stufe == "item":                         # alle Dateien darunter werden Medien, keine Unterebenen
                    im_einzelstueck.update((platte, r) for r in dateien)
                    continue
                for u in sorted(self.b.unterordner.get((platte, o), ()), key=str.casefold, reverse=True):
                    stapel.append((u, self.stufe_darunter(stufe), tiefe + 1))
            alle += [(platte, r) for r in self.uebernommene_unter(platte, pfad)]
        alle = list(dict.fromkeys(alle))
        offen = [k for k in alle if k not in d["erschlossen"] and k not in im_einzelstueck]
        return {"ordner": ordner, "dateien": len(alle), "einzeldateien": len(dateien_direkt),
                "nicht_erschlossen": len(offen), "beispiele_offen": [f"{p}/{r}" for p, r in offen[:5]],
                "ziel": ziel, "ziel_name": self.ziel_name(ziel), "stufen": {k: v for k, v in STUFEN.items() if k != "item"}}

    def ebene_fehlt(self, platte, ordner, d, einzelstueck=False):
        """Was einer neuen Unterebene aus einem Ordner fehlt: eigener Titel (nicht geerbt), Zeitraum, Form und Inhalt;
        einem Einzelstück nur die Pflichtfelder (eigener Titel, Zeitraum) wie einer Datei."""
        fehlt = []
        if not d["werte"].get((platte, ordner), {}).get("titel"):
            fehlt.append("eigener Titel")
        if not self.wert(platte, ordner, "zeitraum", d)[0]:
            fehlt.append("Entstehungszeitraum")
        if not einzelstueck and not self.wert(platte, ordner, "inhalt", d)[0]:
            fehlt.append("Form und Inhalt")
        return fehlt

    def ziel_pruefen(self, ziel):
        con = self.b.verbinden()
        try:
            art, _, nr = (ziel or "").partition(":")
            if art == "a" and nr.isdigit():
                ok = con.execute("SELECT 1 FROM bestandsbox WHERE anton_id = ?", (int(nr),)).fetchone()
            elif art == "e" and nr.isdigit():
                ok = con.execute("SELECT 1 FROM ebene WHERE ebene_id = ?", (int(nr),)).fetchone()
            elif ordner_ziel_teilen(ziel):
                ok = con.execute("SELECT 1 FROM zuordnung WHERE platte_id = ? AND pfad = ? AND stufe IN ('class', 'file')",
                                 ordner_ziel_teilen(ziel)).fetchone()
            else:
                ok = None
        finally:
            con.close()
        if not ok:
            raise ValueError("Diese Box oder Ebene gibt es nicht (mehr).")

    def zuordnen(self, ziele, ziel, stufen, wer="", namen=None):
        """Ordnet Dateien (Einzelstücke) und Ordner (Unterebenen mit Stufe, Unterordner laut stufen) einer Box zu.
        Nur Erschlossenes; Ordner mit eigener Ebene brauchen eigenen Titel, Zeitraum, Form und Inhalt.
        namen: je Ordner die Stufe aus Anton (Halbbox), muss zur Stufe des Imports passen."""
        stufen = stufen or {}
        p = self.zuordnen_pruefen(ziele, ziel, stufen)
        if p["nicht_erschlossen"]:
            raise ValueError(f"{p['nicht_erschlossen']} Dateien sind noch nicht erschlossen (Titel und Entstehungszeitraum), "
                             "z. B. " + ", ".join(p["beispiele_offen"][:2]))
        if not p["dateien"]:
            raise ValueError("In der Auswahl ist nichts übernommen.")
        st = self.stufen()
        anton_stufen = {x["name"]: x["import"] for x in st["liste"]} | {st["einzelstueck"]: "item"}
        zeilen = []
        for o in p["ordner"]:
            s = stufen.get(f"{o['platte']}|{o['pfad']}", o["stufe"])
            if s not in ("class", "file", "item", ""):
                raise ValueError(f"Unbekannte Stufe {s!r}")
            if s and o["fehlt"]:
                raise ValueError(f"„{o['name']}“ als {STUFEN[s]} braucht noch: {', '.join(o['fehlt'])}. "
                                 "Im Editor ergänzen oder „Ordner auflösen“ wählen.")
            if o["tiefe"] == 0 and not s and not o["direkt"] and not any(x["tiefe"] > 0 for x in p["ordner"]):
                raise ValueError("Ein Ordner ohne eigene Ebene braucht Dateien oder Unterordner.")
            name = (namen or {}).get(f"{o['platte']}|{o['pfad']}") or ""
            if name and (not s or anton_stufen.get(name) != s):
                raise ValueError(f"Die Stufe „{name}“ passt nicht zu {STUFEN.get(s, s)}.")
            zeilen.append((o["platte"], o["pfad"], s, name))
        for platte, pfad in ziele:
            if (platte, pfad) in self.b.dateien and self.uebernommen(platte, pfad):
                zeilen.append((platte, pfad, "item", ""))
        jetzt = zeit()
        with self.b.sperre, self.b.schreibend() as con:
            for platte, pfad in ziele:                      # frühere Zuordnungen darunter ersetzen
                if (platte, pfad) in self.b.dateien:
                    con.execute("DELETE FROM zuordnung WHERE platte_id = ? AND pfad = ?", (platte, pfad))
                else:
                    con.execute(f"DELETE FROM zuordnung WHERE platte_id = ? AND {DARUNTER}", (platte, *darunter(pfad)))
            con.executemany("INSERT OR REPLACE INTO zuordnung (platte_id, pfad, ziel, stufe, wer, zeit, stufe_name) "
                            "VALUES (?,?,?,?,?,?,?)", [(pl, pf, ziel, s, wer.strip(), jetzt, n) for pl, pf, s, n in zeilen])
            for pl, pf, s, n in zeilen:
                con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                            (jetzt, "Erschließung", f"{pl}:{pf}", "zuordnung", "",
                             f"{p['ziel_name']} ({ziel}) als {n + ', Import ' if n else ''}{STUFEN[s]}"))
            self.verwaiste_loesen(con, jetzt)
        with self.b.sperre:
            self.b.stand = self.b.db_stand()
        return {"ok": True, "zugeordnet": len(zeilen), "dateien": p["dateien"]}

    def zuordnung_stufe(self, platte, pfad, stufe_name, wer=""):
        """Stufe einer Ordner-Einheit nachträglich ändern (Dropdown im Kopf): Name aus der Werteliste, Import class/file."""
        stufen = {x["name"]: x["import"] for x in self.stufen()["liste"]}
        if stufe_name not in stufen:
            raise ValueError(f"Unbekannte Stufe „{stufe_name}“.")
        jetzt = zeit()
        with self.b.sperre, self.b.schreibend() as con:
            alt = con.execute("SELECT stufe, stufe_name FROM zuordnung WHERE platte_id = ? AND pfad = ?", (platte, pfad)).fetchone()
            if alt is not None and alt[0] == "item":
                raise ValueError("Ein Einzelstück wird nicht zur Ebene umgestellt; dafür den Ordner neu zuordnen.")
            if alt is None or alt[0] not in ("class", "file"):
                raise ValueError("Dieser Ordner ist keine eigene Einheit.")
            con.execute("UPDATE zuordnung SET stufe = ?, stufe_name = ?, wer = ?, zeit = ? WHERE platte_id = ? AND pfad = ?",
                        (stufen[stufe_name], stufe_name, wer.strip(), jetzt, platte, pfad))
            con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                        (jetzt, "Erschließung", f"{platte}:{pfad}", "zuordnung.stufe", alt[1] or STUFEN.get(alt[0], alt[0]),
                         f"{stufe_name} (Import {stufen[stufe_name]})"))
        with self.b.sperre:
            self.b.stand = self.b.db_stand()
        return {"ok": True}

    def zuordnung_loesen(self, platte, pfad, wer=""):
        jetzt = zeit()
        with self.b.sperre, self.b.schreibend() as con:
            alt = con.execute("SELECT ziel, stufe FROM zuordnung WHERE platte_id = ? AND pfad = ?", (platte, pfad)).fetchone()
            if alt is None:
                raise ValueError("Dieses Element ist nicht selbst zugeordnet (vielleicht über einen Ordner darüber).")
            n = con.execute(f"DELETE FROM zuordnung WHERE platte_id = ? AND {DARUNTER}", (platte, *darunter(pfad))).rowcount
            con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                        (jetzt, "Erschließung", f"{platte}:{pfad}", "zuordnung", f"{alt[0]} als {STUFEN.get(alt[1], alt[1])}",
                         f"gelöst ({n} Einträge)"))
            self.verwaiste_loesen(con, jetzt)
        with self.b.sperre:
            self.b.stand = self.b.db_stand()
        return {"ok": True, "geloest": 1}

    def zuordnungen_loesen(self, ziele=None, ziel=None, platte=None, ordner=None, wer=""):
        """Mehrere Zuordnungen auf einmal lösen (Entscheidung 06.11.2026): die eigenen Zuordnungen der Elemente in ziele
        (mit allem darunter), oder alle Dateien aus ordner (Herkunftsgruppe einer Box), die selbst ziel zugeordnet sind.
        Nicht selbst Zugeordnetes bleibt (es hängt an einem Ordner darüber). Antwort: Zahl der gelösten Elemente."""
        jetzt = zeit()
        n = 0
        with self.b.sperre, self.b.schreibend() as con:
            if ziele is None:
                zeilen = [(z[0], z[1], z[2], z[3]) for z in con.execute(
                    "SELECT platte_id, pfad, ziel, stufe FROM zuordnung WHERE ziel = ? AND platte_id = ? AND stufe = 'item'",
                    (ziel, platte)) if (z[0], z[1]) in self.b.dateien and elternordner(z[1]) == ordner]
                for pl, pf, zi, st in zeilen:
                    con.execute("DELETE FROM zuordnung WHERE platte_id = ? AND pfad = ?", (pl, pf))
            else:
                zeilen = []
                for pl, pf in dict.fromkeys(ziele):
                    alt = con.execute("SELECT ziel, stufe FROM zuordnung WHERE platte_id = ? AND pfad = ?", (pl, pf)).fetchone()
                    if alt is None:
                        continue
                    con.execute(f"DELETE FROM zuordnung WHERE platte_id = ? AND {DARUNTER}", (pl, *darunter(pf)))
                    zeilen.append((pl, pf, alt[0], alt[1]))
            for pl, pf, zi, st in zeilen:
                con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                            (jetzt, "Erschließung", f"{pl}:{pf}", "zuordnung", f"{zi} als {STUFEN.get(st, st)}",
                             "gelöst" + (f" ({wer.strip()})" if wer.strip() else "")))
            n = len(zeilen)
            self.verwaiste_loesen(con, jetzt)
        with self.b.sperre:
            self.b.stand = self.b.db_stand()
        return {"ok": True, "geloest": n}

    @staticmethod
    def verwaiste_loesen(con, jetzt):
        """Dateien in einer Ordner-Einheit (Ziel „o:…“), deren Ordner keine eigene Ebene mehr ist (gelöst, aufgelöst,
        Einzelstück): Zuordnung entfernen und protokollieren, sonst fände der Export kein Ziel."""
        weg = con.execute("""SELECT z.platte_id, z.pfad, z.ziel FROM zuordnung z WHERE z.ziel LIKE 'o:%' AND NOT EXISTS (
            SELECT 1 FROM zuordnung o WHERE 'o:' || o.platte_id || '|' || o.pfad = z.ziel AND o.stufe IN ('class', 'file'))""").fetchall()
        for platte, pfad, ziel in weg:
            con.execute("DELETE FROM zuordnung WHERE platte_id = ? AND pfad = ?", (platte, pfad))
            con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                        (jetzt, "Erschließung", f"{platte}:{pfad}", "zuordnung", f"{ziel} als Einzelstück",
                         f"gelöst (Ordner-Einheit „{ziel[2:].replace('|', ':')}“ ist keine eigene Ebene mehr)"))
        return len(weg)

    # ---- neue Ebenen ----

    def ebene_anlegen(self, daten, wer=""):
        eltern = daten.get("eltern") or ""
        self.ziel_pruefen(eltern)
        titel = (daten.get("titel") or "").strip()
        signatur = " ".join((daten.get("signatur") or "").split())
        # Stufe: Name aus der Werteliste (Anton oder Vorgabe); gespeichert wird dazu, als was der API-Import sie anlegt
        stufen = {s["name"]: s["import"] for s in self.stufen()["liste"]}
        stufe_name = (daten.get("stufe_name") or "").strip() or next(iter(stufen))
        if stufe_name not in stufen:
            raise ValueError(f"Unbekannte Stufe „{stufe_name}“; bitte aus der Liste wählen.")
        stufe = stufen[stufe_name]
        if not titel:
            raise ValueError("Eine neue Verzeichnungseinheit braucht einen Titel.")
        if stufe not in ("class", "file"):
            raise ValueError("Einzelstücke entstehen aus Dateien, nicht als neue Ebene.")
        if norm(titel) == norm(self.ziel_name(eltern)):
            raise ValueError("Eine neue Verzeichnungseinheit darf nicht so heißen wie die Einheit darüber, sonst legt Anton sie mit ihr zusammen.")
        fehlt = [n for n, k in (("Entstehungszeitraum", "von"), ("Form und Inhalt", "inhalt")) if not (daten.get(k) or "").strip()]
        if fehlt:
            raise ValueError("Eine neue Verzeichnungseinheit braucht auch: " + ", ".join(fehlt) + ".")
        jetzt = zeit()
        with self.b.sperre, self.b.schreibend() as con:
            nr = con.execute("INSERT INTO ebene (eltern, titel, stufe, von, bis, ca, inhalt, wer, zeit, signatur, stufe_name) "
                             "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                             (eltern, titel, stufe, daten["von"].strip(), (daten.get("bis") or "").strip(),
                              int(bool(daten.get("ca"))), daten["inhalt"].strip(), wer.strip(), jetzt, signatur,
                              stufe_name)).lastrowid
            con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                        (jetzt, "Erschließung", f"Ebene {nr}", "ebene", "",
                         f"neu unter {eltern}: {titel} ({stufe_name}, Import {stufe})" + (f", Signatur {signatur}" if signatur else "")))
        with self.b.sperre:
            self.b.stand = self.b.db_stand()
        return {"ok": True, "ebene_id": nr}

    def ebene_entfernen(self, ebene_id):
        ziel = f"e:{int(ebene_id)}"
        con = self.b.verbinden()
        try:
            belegt = con.execute("SELECT COUNT(*) FROM zuordnung WHERE ziel = ?", (ziel,)).fetchone()[0]
            kinder = con.execute("SELECT COUNT(*) FROM ebene WHERE eltern = ?", (ziel,)).fetchone()[0]
        finally:
            con.close()
        if belegt or kinder:
            raise ValueError("Die Ebene ist nicht leer: erst die Zuordnungen lösen bzw. die Ebenen darunter entfernen.")
        jetzt = zeit()
        with self.b.sperre, self.b.schreibend() as con:
            z = con.execute("SELECT titel FROM ebene WHERE ebene_id = ?", (int(ebene_id),)).fetchone()
            con.execute("DELETE FROM ebene WHERE ebene_id = ?", (int(ebene_id),))
            con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                        (jetzt, "Erschließung", f"Ebene {ebene_id}", "ebene", z[0] if z else "", "entfernt"))
        with self.b.sperre:
            self.b.stand = self.b.db_stand()
        return {"ok": True}

    # ---- Vorlauf ----

    def vorlauf(self):
        d = self.daten()
        dateien = d["uebernommen"]
        menge = set(dateien)
        con = self.b.verbinden()
        try:
            voll = {tuple(z) for z in con.execute("SELECT sha256, endung FROM exif_voll")}
            texte = {tuple(z[:2]): z[2] for z in con.execute("SELECT sha256, endung, zeichen FROM volltext")}
            personen = {z[0] for z in con.execute("SELECT sha256 FROM personen")}
            stand = {z["schritt"]: dict(z) for z in con.execute("SELECT * FROM vorlauf_stand")}
            erledigt = Counter()
            for s, p, r in con.execute("SELECT schritt, platte_id, relpfad FROM vorlauf_erledigt"):
                erledigt[s] += (p, r) in menge
            urteile = Counter()
            for schritt, urteil, n in con.execute(
                    "SELECT v.schritt, u.urteil, COUNT(*) FROM vorschlag_urteil u JOIN vorschlag v USING "
                    "(platte_id, pfad, feld, wert) GROUP BY v.schritt, u.urteil"):
                urteile[(schritt, urteil)] = n
            vokabular = {z[0]: (z[1], z[2]) for z in con.execute(
                "SELECT art, COUNT(*), MIN(geholt_am) FROM anton_begriff GROUP BY art")}
            lauf = con.execute("SELECT lauf_id FROM lauf WHERE art = 'vorlauf' AND status NOT IN ('entfernt') "
                               "ORDER BY lauf_id DESC LIMIT 1").fetchone()
            lauf = self.erfassung.lauf_angaben(con, con.execute("SELECT * FROM lauf WHERE lauf_id = ?", (lauf[0],)).fetchone()) if lauf else None
        finally:
            con.close()
        fotos = dokumente = mit_voll = mit_text = text_gelesen = mit_personen = foto_geprueft = 0
        for platte, r in dateien:
            info = self.b.dateien[(platte, r)]
            end = os.path.splitext(r)[1].lower()
            mit_voll += (info["sha256"], end) in voll
            if end in TEXT_ENDUNGEN:
                dokumente += 1
                if (info["sha256"], end) in texte:
                    text_gelesen += 1
                    mit_text += bool(texte[(info["sha256"], end)])
            if info["mime"].startswith("image/"):
                fotos += 1
                foto_geprueft += info["sha256"] in personen
                mit_personen += bool(info["bildtyp"])
        n = len(dateien)
        vorhanden = [
            {"name": "Metadaten gelesen", "betrifft": n, "erledigt": mit_voll,
             "ergebnis": mit_voll, "einheit": "Dateien"},
            {"name": "Texte der Dokumente", "betrifft": dokumente,
             "erledigt": text_gelesen, "ergebnis": mit_text, "einheit": "Dokumente", "ergebnis_text": "mit Text"},
            {"name": "Personen auf Fotos", "betrifft": fotos,
             "erledigt": foto_geprueft, "ergebnis": mit_personen, "einheit": "Fotos", "ergebnis_text": "mit Personen"},
        ]
        einstellung = self.erfassung.info["einstellungen"].get("vorlauf") or {}
        an = einstellung.get("schritte") or {}
        schritte = []
        for s in VORLAUF_SCHRITTE:
            st = stand.get(s["k"])
            if st:
                st["kennzahlen"] = json.loads(st["kennzahlen"] or "{}")
            schritte.append({**s, "an": an.get(s["k"], True) if s["lauf"] else False, "stand": st,
                             "erledigt": erledigt[s["k"]], "offen": n - erledigt[s["k"]] if s["lauf"] else None,
                             "angenommen": urteile[(s["k"], "angenommen")], "verworfen": urteile[(s["k"], "verworfen")]})
        return {"uebernommen": n, "fotos": fotos, "dokumente": dokumente, "erschlossen": len(d["erschlossen"]),
                "vorhanden": vorhanden, "schritte": schritte, "umfang": einstellung.get("umfang", "uebernommen"),
                "alle_dateien": sum(1 for x in self.b.dateien.values() if not x["system"]),
                "vokabular": vokabular, "lauf": lauf, "anton_url": self.erfassung.info["einstellungen"]["anton"]["url"]}

    def vorlauf_einstellen(self, daten):
        alt = self.erfassung.info["einstellungen"].get("vorlauf") or {}
        neu = {"umfang": daten.get("umfang", alt.get("umfang", "uebernommen")),
               "schritte": {k: bool((daten.get("schritte") or {}).get(k, (alt.get("schritte") or {}).get(k, True)))
                            for k in SCHRITTE_IM_LAUF}}
        return self.erfassung.einstellungen_aendern({"vorlauf": neu})

    def vorlauf_starten(self, schritte=None):
        """Schreibt den Umfang (vorlauf_umfang) und reiht einen Lauf der Art „vorlauf“ ein (startet gleich, wenn
        keiner läuft). schritte: Kürzel; ohne Angabe die eingeschalteten."""
        einstellung = self.erfassung.info["einstellungen"].get("vorlauf") or {}
        if schritte is None:
            schritte = [k for k in SCHRITTE_IM_LAUF if (einstellung.get("schritte") or {}).get(k, True)]
        schritte = [k for k in SCHRITTE_IM_LAUF if k in set(schritte)]
        if not schritte:
            raise ValueError("Kein Schritt gewählt.")
        if self.vorlauf_eingereiht() or self.erfassung.laeuft("vorlauf"):
            raise ValueError("Der Vorlauf läuft schon oder ist eingereiht.")
        umfang = "uebernommen"                     # im Tool nur Übernommenes (Entscheidung 03.11.2026)
        d = self.daten()
        dateien = d["uebernommen"] if umfang == "uebernommen" else [k for k, x in self.b.dateien.items() if not x["system"]]
        if not dateien:
            raise ValueError("Noch nichts übernommen: erst in der Bewertung entscheiden.")
        with self.b.sperre, self.b.schreibend() as con:
            con.execute("DELETE FROM vorlauf_umfang")
            con.executemany("INSERT INTO vorlauf_umfang VALUES (?,?)", dateien)
            lauf_id = con.execute("INSERT INTO lauf (art, platte_id, auftrag, status, start) VALUES ('vorlauf', NULL, ?, "
                                  "'eingereiht', ?)", (json.dumps({"schritte": schritte, "umfang": umfang}), zeit())).lastrowid
            con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                        (zeit(), "Vorlauf", f"Lauf {lauf_id}", "start", "",
                         f"{', '.join(schritte)} für {len(dateien):,} Dateien ({umfang})"))
        with self.b.sperre:
            self.b.stand = self.b.db_stand()
        gestartet = self.erfassung.weiter()
        return {"ok": True, "lauf_id": lauf_id, "eingereiht": lauf_id not in gestartet, "dateien": len(dateien)}

    def vorlauf_eingereiht(self):
        con = self.b.verbinden()
        try:
            return con.execute("SELECT 1 FROM lauf WHERE art = 'vorlauf' AND status = 'eingereiht'").fetchone() is not None
        finally:
            con.close()

    # ---- Normdaten im Editor ----

    def begriffe(self, art, anfrage, grenze=15):
        """Anton-Begriffe aus dem zwischengespeicherten Vokabular (V8) zur Auswahl im Editor; Sprachen aus SPRACHEN."""
        if art == "language":
            q = norm(anfrage)
            treffer = [(0 if norm(n).startswith(q) or c == q else 1, {"code": c, "name": n, "typ": c})
                       for c, n in SPRACHEN if not q or q in norm(n) or c.startswith(q)
                       or (q == "deu" and c == "ger")]                  # ISO 639-2/T „deu“ = „ger“ bei Anton
            treffer.sort(key=lambda x: x[0])
            return {"treffer": [x for _, x in treffer[:grenze]], "vokabular": len(SPRACHEN)}
        if art not in ("keyword", "place", "actor"):
            raise ValueError("unbekannte Art")
        q = norm(anfrage)
        con = self.b.verbinden()
        try:
            zeilen = con.execute("SELECT anton_id, name, voll, typ, alternativ FROM anton_begriff WHERE art = ?", (art,)).fetchall()
            gesamt = len(zeilen)
        finally:
            con.close()
        treffer = []
        for z in zeilen:
            namen = [z["name"], z["voll"], *json.loads(z["alternativ"] or "[]")]
            formen = [norm(n) for n in namen if n]
            if not q or any(f.startswith(q) for f in formen):
                rang = 0
            elif any(q in f for f in formen):
                rang = 1
            else:
                continue
            treffer.append((rang, len(z["name"]), {"anton_id": z["anton_id"], "name": z["voll"] or z["name"], "typ": z["typ"]}))
        treffer.sort(key=lambda x: (x[0], x[1]))
        return {"treffer": [t for _, _, t in treffer[:grenze]], "vokabular": gesamt}

    # ---- Sprachmodell auf Abruf ----

    def sprachmodell(self, platte, pfad):
        dateien = self.uebernommene_unter(platte, pfad)
        if not dateien:
            raise ValueError("Nichts Übernommenes gewählt.")
        return self.erfassung.sprachmodell({"aktion": "vorschlag", "platte": platte, "pfad": pfad, "dateien": dateien[:200]})

    # ---- Bestandsboxen ----

    def boxen(self):
        """Bestandsboxen verschachtelt: je Box (aus Anton) die Unterverzeichnungseinheiten (neue Ebenen, Ordner mit
        eigener Stufe) und die Dateien je Herkunft (Platte + Ordner). Eine Datei liegt in der nächsten Einheit über
        ihr: einzeln zugeordnete Dateien direkt im Ziel, Dateien eines Ordners „ohne eigene Ebene“ eine Stufe höher."""
        d = self.daten()
        con = self.b.verbinden()
        try:
            boxen = [dict(z) for z in con.execute("SELECT * FROM bestandsbox ORDER BY reihenfolge, anton_id")]
            ebenen = [dict(z) for z in con.execute("SELECT * FROM ebene ORDER BY ebene_id")]
        finally:
            con.close()
        namen = {f"a:{b['anton_id']}": b["titel"] for b in boxen} | {f"e:{e['ebene_id']}": e["titel"] for e in ebenen}
        zuord = d["zuordnung"]
        je_ziel = defaultdict(list)
        for (platte, pfad), z in zuord.items():
            je_ziel[z["ziel"]].append((platte, pfad, z["stufe"]))

        def neue_einheit(**angaben):
            return {"herkunft": {}, "einheiten": [], "dateien": 0, **angaben}

        def ablegen(einheit, platte, relpfad, eigen):
            """Datei in die Herkunftsgruppe (Platte + Ordner) einer Einheit; die Liste ist auf 300 je Gruppe begrenzt."""
            ordner = elternordner(relpfad)
            g = einheit["herkunft"].setdefault((platte, ordner), {
                "platte": platte, "ordner": ordner, "anzahl": 0, "dateien": [], "eigen": 0,
                # lösbar: der Ordner ist selbst „ohne eigene Ebene“ zugeordnet (sonst löst man Datei oder Einheit)
                "loesbar": (zuord.get((platte, ordner)) or {}).get("stufe") == ""})
            g["anzahl"] += 1
            g["eigen"] += eigen              # einzeln zugeordnete Dateien: auf einmal lösbar („N lösen“)
            if len(g["dateien"]) < 300:
                g["dateien"].append({"pfad": relpfad, "name": relpfad.rsplit("/", 1)[-1], "eigen": eigen,
                                     "titel": self.wert_fuer_datei(platte, relpfad, "titel", d)})

        def fuellen(einheit, ziel):
            """Hängt an eine Box oder neue Ebene die Ordner-Einheiten und Dateien ihrer Zuordnungen."""
            zeilen = sorted(je_ziel.get(ziel, []), key=lambda x: (x[0], x[1].casefold()))
            ordner = {}
            for platte, pfad, stufe in zeilen:
                einzelstueck = stufe == "item" and (platte, pfad) not in self.b.dateien
                if stufe in ("class", "file") or einzelstueck:
                    ordner[(platte, pfad)] = neue_einheit(einzelstueck=einzelstueck, ziel=ordner_ziel(platte, pfad),
                        art="ordner", platte=platte, pfad=pfad, name=pfad.rsplit("/", 1)[-1] or platte,
                        titel=self.wert_fuer_datei(platte, pfad, "titel", d) or (pfad.rsplit("/", 1)[-1] or platte),
                        laufzeit=self.wert_fuer_datei(platte, pfad, "zeitraum", d),
                        stufe_name=zuord[(platte, pfad)].get("stufe_name") or STUFEN[stufe], import_name=STUFEN[stufe], neu=True)

            def behaelter(platte, pfad):
                """Nächste Einheit ab pfad aufwärts; eine Zuordnung zu einem anderen Ziel beendet die Suche."""
                for x in weg_nach_oben(pfad):
                    if (platte, x) in ordner:
                        return ordner[(platte, x)]
                    z = zuord.get((platte, x))
                    if z and z["ziel"] != ziel:
                        break
                return einheit

            for (platte, pfad), o in ordner.items():
                (behaelter(platte, elternordner(pfad)) if pfad else einheit)["einheiten"].append(o)
            for platte, pfad, stufe in zeilen:
                if stufe == "item" and (platte, pfad) in self.b.dateien:   # einzeln zugeordnet: direkt ins Ziel
                    if (platte, pfad) in self.b.dateien and self.uebernommen(platte, pfad):
                        ablegen(einheit, platte, pfad, True)
                    continue
                for r in self.uebernommene_unter(platte, pfad):
                    z = self.zuordnung_von(platte, r, d)
                    if z is None or z["pfad"] != pfad:   # eine tiefere Zuordnung gilt
                        continue
                    ablegen(behaelter(platte, pfad), platte, r, False)
            # Dateien von anderswo, die einer Ordner-Einheit selbst zugeordnet sind (Ziel „o:…“)
            for (platte, pfad), o in ordner.items():
                if o["einzelstueck"]:
                    continue
                for pl, pf, stufe in sorted(je_ziel.get(o["ziel"], []), key=lambda x: (x[0], x[1].casefold())):
                    if (pl, pf) in self.b.dateien and self.uebernommen(pl, pf):
                        ablegen(o, pl, pf, True)

        def ebenen_von(eltern):
            erg = []
            for e in ebenen:
                if e["eltern"] == eltern:
                    ziel = f"e:{e['ebene_id']}"
                    x = neue_einheit(art="ebene", ziel=ziel, ebene_id=e["ebene_id"], titel=e["titel"],
                                     laufzeit=zeitraum_text(json.dumps([e["von"] or "", e["bis"] or "", bool(e["ca"])])),
                                     signatur=e.get("signatur") or "", inhalt=e["inhalt"] or "",
                                     stufe_name=e.get("stufe_name") or STUFEN.get(e["stufe"], e["stufe"]),
                                     import_name=STUFEN.get(e["stufe"], e["stufe"]), neu=True)
                    x["einheiten"] = ebenen_von(ziel)
                    fuellen(x, ziel)
                    erg.append(x)
            return erg

        def abschliessen(x):
            """Herkunft als Liste, Dateien zählen (mit allem darunter), leer = darf entfernt werden."""
            x["herkunft"] = sorted(x["herkunft"].values(), key=lambda g: (g["platte"], g["ordner"].casefold()))
            for u in x["einheiten"]:
                abschliessen(u)
            x["dateien"] = sum(g["anzahl"] for g in x["herkunft"]) + sum(u["dateien"] for u in x["einheiten"])
            x["leer"] = not x["herkunft"] and not x["einheiten"]
            return x

        erg = []
        for b in boxen:
            ziel = f"a:{b['anton_id']}"
            x = neue_einheit(art="anton", ziel=ziel, anton_id=b["anton_id"], signatur=b["signatur"] or "",
                             titel=b["titel"] or "", laufzeit=b.get("laufzeit") or "", stufe_name=b["stufe"] or "",
                             # gesperrt None: vor dem 03.11. geladen, Zugang unbekannt
                             gesperrt=None if b.get("gesperrt") is None else bool(b["gesperrt"]),
                             link=b["link"] or "", anzahl=b["anzahl"],
                             eltern=json.loads(b["eltern"] or "[]"), zugang=b["zugang"] or "")
            x["einheiten"] = ebenen_von(ziel)
            fuellen(x, ziel)
            erg.append(abschliessen(x))
        return {"boxen": erg, "anton_url": self.erfassung.info["einstellungen"]["anton"]["url"], "namen": namen,
                "stufen": self.stufen()}

    # ---- Stufen aus Anton (Werteliste von /api/ai/schema, zwischengespeichert) ----

    STUFEN_VORGABE = [{"name": "Gliederungsebene", "import": "class"}, {"name": "Dossier", "import": "file"}]

    @staticmethod
    def stufe_import(name, schluessel=""):
        """Als was der API-Import eine Stufe anlegt: nur class, file, item (docs/anton_import.md, A5)."""
        n = norm(f"{name} {schluessel}")
        if re.search(r"\b(item|einzel|stueck|piece)", n):
            return "item"
        if re.search(r"\b(file|dossier|akte)", n):
            return "file"
        return "class"

    def stufen(self):
        """Stufen für neue Unterverzeichnungseinheiten: aus Anton, ohne Einzelstücke; sonst die Vorgabe."""
        con = self.b.verbinden()
        try:
            zeilen = [dict(z) for z in con.execute("SELECT * FROM anton_stufe ORDER BY reihenfolge")]
        finally:
            con.close()
        liste = [{"name": z["name"], "import": z["import"]} for z in zeilen if z["import"] != "item"]
        einzel = next((z["name"] for z in zeilen if z["import"] == "item"), "") if liste else ""
        return {"liste": liste or self.STUFEN_VORGABE, "aus_anton": bool(liste), "einzelstueck": einzel or "Einzelstück",
                "geholt_am": zeilen[0]["geholt_am"] if zeilen else ""}

    def stufen_holen(self, neu=False):
        """Holt die Werteliste aus Anton, wenn sie fehlt oder älter als 7 Tage ist (oder neu=True); Fehler ohne Abbruch."""
        s = self.stufen()
        # falsch gelesener Stand von vor dem 04.11.2026 (Schlüssel des JSON-Schemas statt der Werteliste): neu holen
        con = self.b.verbinden()
        try:
            falsch = con.execute("SELECT 1 FROM anton_stufe WHERE schluessel IN ('type', 'description', 'enum') "
                                 "OR schluessel NOT GLOB '[0-9]*'").fetchone()
        finally:
            con.close()
        neu = neu or bool(falsch)
        alt = s["geholt_am"] and time.time() - time.mktime(time.strptime(s["geholt_am"][:19], "%Y-%m-%dT%H:%M:%S")) > 7 * 86400
        if s["aus_anton"] and not alt and not neu:
            return {**s, "fehler": ""}
        try:
            antwort = self.erfassung.aufrufen("anton", "--daten", json.dumps({"aktion": "stufen"}))
        except (RuntimeError, ValueError) as fehler:
            return {**s, "fehler": str(fehler)}
        jetzt = zeit()
        with self.b.sperre, self.b.schreibend() as con:
            con.execute("DELETE FROM anton_stufe")
            con.executemany("INSERT OR REPLACE INTO anton_stufe VALUES (?,?,?,?,?)",
                            [(x["name"], x["schluessel"], self.stufe_import(x["name"], x["schluessel"]), i, jetzt)
                             for i, x in enumerate(antwort["stufen"])])
            con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                        (jetzt, "Erschließung", "Anton-Stufen", "anton_stufe", "", f"{len(antwort['stufen'])} Stufen geholt"))
        with self.b.sperre:
            self.b.stand = self.b.db_stand()
        return {**self.stufen(), "fehler": ""}

    def dashboard(self):
        """Erschließung und Zuordnung fürs Dashboard (Entscheidung 04.11.2026): Stand je Platte, gefüllte Felder,
        Ordner mit den meisten offenen Dateien, Bestand in Anton, Vorlauf."""
        d = self.daten()
        uebernommen = set(d["uebernommen"])
        platten = [{"id": p["platte_id"], **self.zaehlen(p["platte_id"], "", d)} for p in self.b.platten]
        felder = Counter()
        for (pl, pf), werte in d["werte"].items():
            if (pl, pf) in uebernommen:
                felder.update(werte.keys())
        namen = {**{k: f["name"] for k, f in FELDER.items()}, **{n: a["label"] for n, a in self.anton_felder().items()}}
        offen = []
        for p in self.b.platten:                       # Ordner bis zur zweiten Ebene mit offenen Dateien
            stapel = [(u, 1) for u in self.b.unterordner.get((p["platte_id"], ""), ())]
            while stapel:
                o, tiefe = stapel.pop()
                z = self.zaehlen(p["platte_id"], o, d)
                if z["uebernommen"] - z["erschlossen"] > 0:
                    offen.append({"platte": p["platte_id"], "ordner": o, **z, "offen": z["uebernommen"] - z["erschlossen"],
                                  "titel": self.wert_fuer_datei(p["platte_id"], o, "titel", d)})
                if tiefe < 2:
                    stapel += [(u, tiefe + 1) for u in self.b.unterordner.get((p["platte_id"], o), ())]
        offen.sort(key=lambda x: -x["offen"])

        def einheiten(x, tiefe=0):
            """Boxen und neue Einheiten flach, mit Tiefe (für die Tabelle)."""
            zeilen = [{"titel": ("› " * tiefe) + (x.get("titel") or ""), "signatur": x.get("signatur", ""),
                       "stufe": x.get("stufe_name", ""), "art": {"anton": "aus Anton", "ebene": "neu", "ordner": "neu (Ordner)"}[x["art"]],
                       "dateien": x["dateien"]}]
            for u in x["einheiten"]:
                zeilen += einheiten(u, tiefe + 1)
            return zeilen
        bestand = []
        for b in self.boxen()["boxen"]:
            bestand += einheiten(b)
        v = self.vorlauf()
        return {"platten": platten, "uebernommen": len(uebernommen), "erschlossen": len(d["erschlossen"]),
                "zugeordnet": sum(self.zuordnung_von(*k, d) is not None for k in uebernommen),
                "felder": [{"feld": namen.get(k, k), "dateien": n, "pflicht": FELDER.get(k, {}).get("pflicht", False)}
                           for k, n in felder.most_common()],
                "offen": offen[:20], "bestand": bestand,
                "vorlauf": [{"schritt": s["name"], "zeit": (s["stand"] or {}).get("zeit", ""), "ergebnis": (s["stand"] or {}).get("ergebnis"),
                             "angenommen": s["angenommen"], "verworfen": s["verworfen"]} for s in v["schritte"]]}

    # ---- Weitere Metadaten (Entscheidung 04.11.2026) ----

    @staticmethod
    def meta_angabe(schluessel):
        """„XMP:Creator“ → (Bezeichnung, Gruppe, vorgeschlagenes Feld) oder None, wenn kein beschreibender Tag.
        In PDF-Angaben ist „Creator“ das Programm, nicht die Person."""
        gruppe, _, tag = schluessel.partition(":")
        if gruppe in ("File", "ICC_Profile", "Composite", "System", "ExifTool"):
            return None
        for name, bez, feld in META_TAGS:
            if tag == name:
                if gruppe == "PDF" and tag == "Creator":
                    return "Programm", gruppe, ""
                return bez, gruppe, feld
        return None

    @staticmethod
    def meta_wert(w):
        if isinstance(w, list):
            w = "; ".join(str(x) for x in w if str(x).strip())
        w = " ".join(str(w if w is not None else "").split())
        return "" if not w or w.startswith("(Binary") or w.lower() in ("unknown", "none", "-", "0") else w[:300]

    def meta_je_datei(self, dateien):
        """{(platte, relpfad): {schlüssel: wert}} der beschreibenden Tags (exif_voll je Inhalt und Endung)."""
        import zlib
        bedarf = defaultdict(list)
        for k in dateien:
            sha = self.b.dateien[k]["sha256"]
            if sha:
                bedarf[(sha, os.path.splitext(k[1])[1].lower())].append(k)
        erg = {}
        con = self.b.verbinden()
        try:
            shas = list({s for s, _ in bedarf})
            for i in range(0, len(shas), 900):
                teil = shas[i:i + 900]
                for sha, end, daten in con.execute(f"SELECT sha256, endung, daten FROM exif_voll WHERE sha256 IN "
                                                   f"({','.join('?' * len(teil))})", teil):
                    if (sha, end) not in bedarf or not daten:
                        continue
                    try:
                        alles = json.loads(zlib.decompress(daten))
                    except (ValueError, zlib.error):
                        continue
                    werte = {s: self.meta_wert(w) for s, w in alles.items() if self.meta_angabe(s)}
                    werte = {s: w for s, w in werte.items() if w}
                    for k in bedarf[(sha, end)]:
                        erg[k] = werte
        finally:
            con.close()
        return erg

    def metadaten_uebersicht(self, ziele, grenze=3000):
        """Beschreibende Metadaten der Auswahl: je Tag Bezeichnung, Gruppe, Vorschlag fürs Feld, häufigste Werte und
        wie viele Dateien bzw. gewählte Elemente einen Wert haben."""
        d = self.daten()
        je_ziel = {(p, pf): self.uebernommene_unter(p, pf)[:grenze] for p, pf in ziele}
        dateien = list(dict.fromkeys((p, r) for (p, _), rs in je_ziel.items() for r in rs))[:grenze]
        werte = self.meta_je_datei(dateien)
        zaehler, mit_datei, mit_ziel = defaultdict(Counter), Counter(), Counter()
        for k in dateien:
            for s, w in werte.get(k, {}).items():
                zaehler[s][w] += 1
                mit_datei[s] += 1
        for z, rs in je_ziel.items():
            vorhanden = set().union(*(werte.get((z[0], r), {}).keys() for r in rs)) if rs else set()
            for s in vorhanden:
                mit_ziel[s] += 1
        reihen = {name: i for i, (name, _, _) in enumerate(META_TAGS)}
        zeilen = []
        for s, c in zaehler.items():
            bez, gruppe, feld = self.meta_angabe(s)
            zeilen.append({"schluessel": s, "name": bez, "gruppe": gruppe, "feld": feld, "werte": c.most_common(8),
                           "verschieden": len(c), "dateien": mit_datei[s], "elemente": mit_ziel[s]})
        zeilen.sort(key=lambda z: (reihen.get(z["schluessel"].partition(":")[2], 99), z["gruppe"]))
        return {"angaben": zeilen, "dateien": len(dateien), "elemente": len(ziele), "gekuerzt": len(dateien) >= grenze}

    def begriff_finden(self, feld, name):
        """Anton-Eintrag gleichen Namens (auch Alternativname) für Akteur:in, Ort, Schlagwort: anton_id oder None."""
        art = META_ART.get(feld)
        if not art or not name:
            return None
        con = self.b.verbinden()
        try:
            for anton_id, n, alt in con.execute("SELECT anton_id, name, alternativ FROM anton_begriff WHERE art = ?", (art,)):
                if norm(n) == norm(name) or norm(name) in {norm(x) for x in json.loads(alt or "[]")}:
                    return anton_id
        finally:
            con.close()
        return None

    def metadaten_uebernehmen(self, ziele, schluessel, feld, modus, wert="", nur_leere=False, wer=""):
        """Batch: Metadatenwert in ein Feld der gewählten Elemente. modus „je“: jedes Element seinen eigenen Wert
        (Datei: ihr Wert; Ordner: der häufigste seiner Dateien); „alle“: für alle wert. Schlagworte werden ergänzt,
        Akteur:in und Ort über den Namen mit Anton abgeglichen; nur_leere lässt vorhandene Werte stehen."""
        if not self.feld_gilt(feld) or self.feld_def(feld)["art"] == "zeitraum":
            raise ValueError("In dieses Feld lassen sich keine Metadaten übernehmen.")
        art = self.feld_def(feld)["art"]
        d = self.daten()
        werte = {}
        if modus == "je":
            for p, pf in ziele:
                rs = self.uebernommene_unter(p, pf)[:3000]
                je = self.meta_je_datei([(p, r) for r in rs])
                c = Counter(je[(p, r)][schluessel] for r in rs if schluessel in je.get((p, r), {}))
                if c:
                    werte[(p, pf)] = c.most_common(1)[0][0]
        else:
            werte = {(p, pf): " ".join((wert or "").split()) for p, pf in ziele if (wert or "").strip()}
        jetzt, n, gelassen = zeit(), 0, 0
        with self.b.sperre, self.b.schreibend() as con:
            for (p, pf), v in werte.items():
                alt = d["werte"].get((p, pf), {}).get(feld)
                if art == "begriffe":
                    liste = json.loads(alt["gleich"]) if alt and alt["gleich"] else []
                    for teil in re.split(r"\s*[;,]\s*", v):
                        if teil and not any(norm(x["name"]) == norm(teil) for x in liste):
                            liste.append({"name": teil, "anton_id": self.begriff_finden(feld, teil)})
                    gleich = json.dumps(liste, ensure_ascii=False)
                else:
                    if alt and nur_leere:
                        gelassen += 1
                        continue
                    gleich = (json.dumps({"name": v, "anton_id": self.begriff_finden(feld, v)}, ensure_ascii=False)
                              if art == "begriff" else v)
                if alt and alt["gleich"] == gleich:
                    continue
                con.execute("INSERT OR REPLACE INTO erschliessung VALUES (?,?,?,?,?,?,?,?)",
                            (p, pf, feld, gleich, (alt or {}).get("je_datei") or "", f"Metadaten: {schluessel}", wer.strip(), jetzt))
                con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                            (jetzt, "Erschließung", f"{p}:{pf}", feld, (alt or {}).get("gleich") or "", f"aus Metadaten {schluessel}: {gleich}"))
                n += 1
        with self.b.sperre:
            self.b.stand = self.b.db_stand()
        return {"ok": True, "geschrieben": n, "ohne_wert": len(ziele) - len(werte), "gelassen": gelassen}

    def vorschlag_mehrere(self, ziele, feld, vorschlag, modus="mit", ueberschreiben=False, wer=""):
        """Mehrfachauswahl (Entscheidung 04.11.2026, fünfte Runde): einen Normdaten-Vorschlag sofort schreiben, „mit“ =
        nur bei den Elementen, die ihn als Vorschlag haben, „alle“ = bei allen gewählten. Schlagworte werden ergänzt,
        Akteur:in und Ort nur in leere Felder (ueberschreiben: auch belegte). Wo er Vorschlag war: als angenommen."""
        if self.feld_def(feld)["art"] not in ("begriff", "begriffe"):
            raise ValueError("Für mehrere Elemente lassen sich nur Schlagworte, Akteur:innen und Orte übernehmen.")
        name = (vorschlag.get("anzeige") or vorschlag.get("wert") or "").strip()
        if not name:
            raise ValueError("Der Vorschlag hat keinen Wert.")
        anton_id = vorschlag.get("anton_id")
        k = anton_id or norm(vorschlag.get("wert") or name)
        d = self.daten()
        hat = {}                                             # Ziel → passender Vorschlag (für das Urteil)
        for p, pf in ziele:
            for v in self.vorschlaege(p, pf, d).get(feld, []):
                if (v["anton_id"] or norm(v["wert"])) == k:
                    hat[(p, pf)] = v
                    break
        betroffen = list(hat) if modus == "mit" else list(ziele)
        neu = {"name": name, "anton_id": anton_id}
        quelle = "Vorschlag: " + " + ".join(dict.fromkeys(vorschlag.get("quellen") or ["Vorlauf"]))
        jetzt, n, gelassen, schon = zeit(), 0, 0, 0
        with self.b.sperre, self.b.schreibend() as con:
            for p, pf in betroffen:
                alt = d["werte"].get((p, pf), {}).get(feld)
                if self.feld_def(feld)["art"] == "begriffe":
                    liste = json.loads(alt["gleich"]) if alt and alt["gleich"] else []
                    if any((anton_id and x.get("anton_id") == anton_id) or norm(x["name"]) == norm(name) for x in liste):
                        schon += 1
                        continue
                    gleich = json.dumps(liste + [neu], ensure_ascii=False)
                else:
                    if alt and alt["gleich"]:
                        if json.loads(alt["gleich"]).get("name") == name:
                            schon += 1
                            continue
                        if not ueberschreiben:
                            gelassen += 1
                            continue
                    gleich = json.dumps(neu, ensure_ascii=False)
                con.execute("INSERT OR REPLACE INTO erschliessung VALUES (?,?,?,?,?,?,?,?)",
                            (p, pf, feld, gleich, (alt or {}).get("je_datei") or "", quelle, wer.strip(), jetzt))
                con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                            (jetzt, "Erschließung", f"{p}:{pf}", feld, (alt or {}).get("gleich") or "", gleich))
                n += 1
            for (p, pf), v in hat.items():
                if (p, pf) in betroffen:
                    self.urteil_schreiben(con, p, pf, {"feld": v["feld"], "wert": v["wert"], "anton_id": v["anton_id"],
                                                       "beleg": (v.get("belege") or [""])[0]}, "angenommen", wer, jetzt)
        with self.b.sperre:
            self.b.stand = self.b.db_stand()
        return {"ok": True, "geschrieben": n, "gelassen": gelassen, "schon": schon, "mit": len(hat)}

    # ---- Übersetzungen der Sujet-Begriffe (V3, Entscheidung 04.11.2026) ----

    def uebersetzungen(self):
        """Allgemeine Sujet-Begriffe mit ihrer Übersetzung in der Sprache des Archivs (zum Prüfen im Vorlauf)."""
        e = {"weg": "sprachmodell", "sprache": "de", "email": "", **(self.erfassung.info["einstellungen"].get("uebersetzung") or {})}
        liste = []
        for ort in (self.erfassung.projekt / "vorgaben" / "sujet_begriffe.csv",
                    Path(__file__).resolve().parent.parent / "vorgaben" / "sujet_begriffe.csv"):
            if ort.exists():
                import csv
                with open(ort, encoding="utf-8") as f:
                    liste = [(z["begriff"].strip(), (z.get("gruppe") or "").strip()) for z in csv.DictReader(f) if z.get("begriff")]
                break
        con = self.b.verbinden()
        try:
            da = {z["text"]: dict(z) for z in con.execute("SELECT * FROM begriff_uebersetzung WHERE sprache = ?", (e["sprache"],))}
        finally:
            con.close()
        return {"einstellung": e, "begriffe": [{"en": b, "gruppe": g, "uebersetzung": (da.get(b) or {}).get("uebersetzung", ""),
                                                "weg": (da.get(b) or {}).get("weg", ""), "geprueft": bool((da.get(b) or {}).get("geprueft"))}
                                               for b, g in liste]}

    def uebersetzungen_speichern(self, liste, wer=""):
        """Übersetzungen von Hand bestätigen oder korrigieren: [{en, uebersetzung}] → geprüft (wird nie neu übersetzt).
        Wirkt auf Vorschläge beim nächsten Lauf von „Sujet“."""
        sprache = (self.erfassung.info["einstellungen"].get("uebersetzung") or {}).get("sprache") or "de"
        jetzt, n = zeit(), 0
        with self.b.sperre, self.b.schreibend() as con:
            for x in liste:
                en, neu = (x.get("en") or "").strip(), " ".join((x.get("uebersetzung") or "").split())
                if not en or not neu:
                    continue
                alt = con.execute("SELECT uebersetzung, geprueft FROM begriff_uebersetzung WHERE text = ? AND sprache = ?",
                                  (en, sprache)).fetchone()
                if alt and alt[0] == neu and alt[1]:
                    continue
                con.execute("INSERT OR REPLACE INTO begriff_uebersetzung VALUES (?,?,?,?,1,?)",
                            (en, sprache, neu, "hand" if not alt or alt[0] != neu else "geprüft", jetzt))
                con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                            (jetzt, "Vorlauf", f"Sujet-Begriff {en}", f"übersetzung {sprache}", alt[0] if alt else "", neu))
                n += 1
        with self.b.sperre:
            self.b.stand = self.b.db_stand()
        return {"ok": True, "geaendert": n}

    def felder_holen(self, neu=False):
        """Weitere Anton-Felder (Notizfelder, /api/import/mapping) in anton_feld, wenn sie fehlen, älter als 7 Tage
        sind oder neu=True. Antwort {felder, geholt_am, fehler}."""
        con = self.b.verbinden()
        try:
            alt = con.execute("SELECT MIN(geholt_am), COUNT(*) FROM anton_feld").fetchone()
        finally:
            con.close()
        frisch = alt[1] and alt[0] and time.time() - time.mktime(time.strptime(alt[0][:19], "%Y-%m-%dT%H:%M:%S")) < 7 * 86400
        fehler = ""
        if neu or not frisch:
            try:
                antwort = self.erfassung.aufrufen("anton", "--daten", json.dumps({"aktion": "felder"}))
                jetzt = zeit()
                with self.b.sperre, self.b.schreibend() as con:
                    con.execute("DELETE FROM anton_feld")
                    con.executemany("INSERT INTO anton_feld VALUES (?,?,?,?,?,?)",
                                    [(f["name"], f["label"], int(f["import"]), f.get("label_quelle", ""), i, jetzt)
                                     for i, f in enumerate(antwort["felder"])])
                    con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)", (jetzt, "Erschließung", "Anton-Felder",
                                "anton_feld", "", f"{len(antwort['felder'])} Notizfelder geholt"))
                with self.b.sperre:
                    self.b.stand = self.b.db_stand()
            except (RuntimeError, ValueError) as f:
                fehler = str(f)
        felder = self.anton_felder()
        return {"felder": [{"name": n, "label": a["label"], "import": bool(a["import"])} for n, a in felder.items()],
                "geholt_am": next(iter(felder.values()), {}).get("geholt_am", ""), "fehler": fehler}

    def box_laden(self, kennung, wer=""):
        e = self.erfassung.aufrufen("anton", "--daten", json.dumps({"aktion": "einheit", "kennung": str(kennung)}))
        jetzt = zeit()
        with self.b.sperre, self.b.schreibend() as con:
            reihe = con.execute("SELECT COALESCE(MAX(reihenfolge), 0) + 1 FROM bestandsbox").fetchone()[0]
            neu = con.execute("SELECT 1 FROM bestandsbox WHERE anton_id = ?", (e["id"],)).fetchone() is None
            con.execute("INSERT OR REPLACE INTO bestandsbox (anton_id, signatur, titel, stufe, objektart, anzahl, link, "
                        "eltern, zugang, geladen_am, reihenfolge, laufzeit, gesperrt) VALUES (?,?,?,?,?,?,?,?,?,?, COALESCE("
                        "(SELECT reihenfolge FROM bestandsbox WHERE anton_id = ?), ?), ?, ?)",
                        (e["id"], e["signatur"], e["titel"], e["stufe"], e["objektart"], e["anzahl"], e["link"],
                         json.dumps(e["eltern"], ensure_ascii=False), e["zugang"], jetzt, e["id"], reihe,
                         e.get("laufzeit") or "", int(bool(e.get("gesperrt")))))
            con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                        (jetzt, "Erschließung", f"Anton {e['id']}", "bestandsbox", "",
                         f"{'geladen' if neu else 'neu geladen'}: {e['signatur']} {e['titel']}"))
        with self.b.sperre:
            self.b.stand = self.b.db_stand()
        return {"ok": True, "box": e}

    def box_entfernen(self, anton_id):
        ziel = f"a:{int(anton_id)}"
        con = self.b.verbinden()
        try:
            belegt = con.execute("SELECT COUNT(*) FROM zuordnung WHERE ziel = ?", (ziel,)).fetchone()[0]
            ebenen = con.execute("SELECT COUNT(*) FROM ebene WHERE eltern = ?", (ziel,)).fetchone()[0]
        finally:
            con.close()
        if belegt or ebenen:
            raise ValueError("Die Box ist nicht leer: erst Zuordnungen lösen und neue Ebenen darin entfernen.")
        jetzt = zeit()
        with self.b.sperre, self.b.schreibend() as con:
            z = con.execute("SELECT signatur, titel FROM bestandsbox WHERE anton_id = ?", (anton_id,)).fetchone()
            if z is None:
                raise ValueError(f"Keine Box mit der Anton-ID {anton_id}")
            con.execute("DELETE FROM bestandsbox WHERE anton_id = ?", (anton_id,))
            con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                        (jetzt, "Erschließung", f"Anton {anton_id}", "bestandsbox", f"{z[0]} {z[1]}", "entfernt"))
        with self.b.sperre:
            self.b.stand = self.b.db_stand()
        return {"ok": True}

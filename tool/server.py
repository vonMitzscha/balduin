"""Balduin: schlankes lokales Web-Tool zum Sichten und Bewerten der Platten (docs/plan.md, Entscheidungen 28.10.2026).

Erfassung (Stufe 2 des Konzepts vom 29.10.2026): Datenträger wählen, Angaben machen, den ganzen Ablauf aus
Die Analyse als Lauf starten (erfassung/lauf.py), Fortschritt je Schritt ansehen, abbrechen, fortsetzen.

Bewertung: Bäume aller Platten mit Balken (Archivfähigkeit, Bewertungsstand, Dubletten),
Inspektor mit Metadaten, Vorschaubildern, gleichen Ordnern und Dateien anderswo; Entscheidungen
(übernehmen, kassieren, zurückstellen; Vorbehalt) mit Vererbung, Sperre, Protokoll und Schutzregel.

Projekte (Stufe 3, Entscheidungen 30.10.2026): Ohne geöffnetes Projekt zeigt die Oberfläche den Startbildschirm
(zuletzt geöffnet, anderes Projekt öffnen mit Finder-Dialog, neues Projekt mit Assistent). Ein Projekt ist ein Ordner
mit projekt.json und inventar.sqlite; angelegt und gelesen wird es über erfassung/lauf.py.

Start:  Doppelklick auf Balduin.command  oder  .venv/bin/python tool/server.py [--projekt Ordner]
Nur Python-Standardbibliothek; der Server ist nur auf diesem Mac erreichbar (127.0.0.1).
Geschrieben werden nur die Tabellen entscheidung, erschliessungshinweis, einstellung, protokoll, lauf, erschliessung und
bestandsbox (Modul 3, tool/erschliessung.py; Angaben zur Platte und
Herausnehmen über erfassung/lauf.py); Quellplatten liest nur der Hintergrundlauf (im venv, mit pandas,
Siegfried, ExifTool …), nie der Server selbst. Der Knopf „Datei zeigen“ im Inspektor markiert ein Original
im Dateimanager des Systems (macOS: Finder, `open -R`; nur auf schreibgeschützt eingehängten Platten), geöffnet wird nichts.
"""
import argparse
import base64
import fnmatch
import json
import mimetypes
import re
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.request
import webbrowser
from collections import defaultdict
from datetime import date
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

from erschliessung import SCHEMA as SCHEMA_ERSCHLIESSUNG, Erschliessung   # Vorlauf und Modul 3 (tool/)
from pakete import SCHEMA as SCHEMA_PAKETE, Pakete, tabellen_umstellen    # Modul 4 Bestand und Export (tool/)

# EINSTELLUNG: Pfade und Port (lassen sich beim Start mit --projekt, --port … überschreiben)
CODE = Path(__file__).resolve().parent.parent  # Ordner mit Tool und erfassung/ (im Git bzw. im Paket)
PORT = 8765
ARBEITSPLATTE = None                           # nur Tests: Datenträger für Vorschaubilder statt dem aus projekt.json

WEB = Path(__file__).resolve().parent / "web"


def version():
    """Versionszähler für die Kopfleiste: 0.<Zahl der Commits>; ohne Git nur „0“.
    Im öffentlichen Spiegel und im Paket steht er in der Datei VERSION, die vorgeht (Entscheidung 14.11.2026).
    safe.directory=*: Git verweigert sonst die Auskunft, wenn der Code-Ordner einem anderen Konto gehört (unter
    Windows häufig: anderes Konto, freigegebener Ordner; Feedback 14.11.2026). Gilt nur für diesen lesenden Aufruf."""
    try:
        datei = (CODE / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        datei = ""
    if re.fullmatch(r"\d+(\.\d+)+", datei):
        return datei
    try:
        zahl = subprocess.run([system.werkzeug("git"), "-c", "safe.directory=*", "-C", str(CODE), "rev-list", "--count",
                               "HEAD"], capture_output=True, text=True, timeout=5, **system.prozess_optionen()).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        zahl = ""
    return f"0.{zahl}" if zahl.isdigit() else "0"


# Hinweis auf eine neue Version (Entscheidung 14.11.2026): Release-Liste aus der Datei AKTUALISIERUNG, die nur der Bau
# im Workflow ins Paket legt (auslieferung/bauen.py); ohne sie (Code aus Git, Bau von Hand) keine Abfrage.
# BALDUIN_AKTUALISIERUNG_URL geht vor, leer schaltet ab (so in den Tests).
def aktualisierung_url():
    if "BALDUIN_AKTUALISIERUNG_URL" in os.environ:
        return os.environ["BALDUIN_AKTUALISIERUNG_URL"].strip()
    try:
        adresse = (CODE / "AKTUALISIERUNG").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return adresse if adresse.startswith("https://") else ""


AKTUALISIERUNG_URL = aktualisierung_url()


def _versionszahlen(text):
    """„0.92“ → (0, 92); None, wenn es keine Version ist."""
    return tuple(int(t) for t in text.split(".")) if re.fullmatch(r"\d+(\.\d+)+", text or "") else None


def neuere_version(eigene, releases):
    """Höchste Version unter den Releases (Tag v<Zahl>.<Zahl>, ohne Entwürfe), wenn sie höher ist als die eigene;
    sonst None. Ohne eigene Version („0“, Code ohne Git) kein Hinweis."""
    eigen = _versionszahlen(eigene)
    if not eigen:
        return None
    beste = None
    for r in releases if isinstance(releases, list) else []:
        if not isinstance(r, dict) or r.get("draft"):
            continue
        zahlen = _versionszahlen(str(r.get("tag_name") or "").removeprefix("v"))
        if zahlen and zahlen > eigen and (not beste or zahlen > beste[0]):
            beste = (zahlen, r)
    if not beste:
        return None
    adresse = str(beste[1].get("html_url") or "")
    return {"version": ".".join(map(str, beste[0])), "adresse": adresse if adresse.startswith("https://") else "",
            "datum": beste[1].get("published_at") or ""}


def aktualisierung(adresse=None):
    """Neuere Version oder None. Die Antwort steht einen Tag in aktualisierung.json neben zuletzt.json; ein Fehler
    (offline, gesperrt) bleibt still und wird ebenfalls einen Tag gemerkt, damit der Start nicht wartet.
    Hinaus geht nur die Abfrage selbst, keine Angaben aus Projekten."""
    adresse = AKTUALISIERUNG_URL if adresse is None else adresse
    if not adresse:
        return None
    merk = Path(ZULETZT).parent / "aktualisierung.json"
    try:
        d = json.loads(merk.read_text(encoding="utf-8"))
        if d.get("adresse") == adresse and time.time() - float(d.get("zeit", 0)) < 86400:
            return neuere_version(VERSION, d.get("releases"))
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    try:
        anfrage = urllib.request.Request(adresse, headers={"Accept": "application/vnd.github+json",
                                                           "User-Agent": f"Balduin/{VERSION}"})
        with urllib.request.urlopen(anfrage, timeout=3) as antwort:
            releases = json.loads(antwort.read(2_000_000))
        # nur, was der Vergleich braucht
        releases = [{k: r.get(k) for k in ("tag_name", "draft", "html_url", "published_at")}
                    for r in releases if isinstance(r, dict)] if isinstance(releases, list) else []
    except (OSError, ValueError):
        releases = []
    try:
        merk.parent.mkdir(parents=True, exist_ok=True)
        merk.write_text(json.dumps({"adresse": adresse, "zeit": time.time(), "releases": releases}), encoding="utf-8")
    except OSError:
        pass
    return neuere_version(VERSION, releases)


# Lizenztexte für „Über Balduin“ (AGPL-3.0-or-later, Zusatz nach § 7; LIZENZ-ZUSATZ.md)
LIZENZTEXTE = {"/lizenz": "LICENSE", "/lizenz/zusatz": "LIZENZ-ZUSATZ.md"}


def system_modul():
    """erfassung/system.py (Plattformabhängiges) ohne das Paket erfassung mit seinen Rechenbibliotheken."""
    global _SYSTEM
    if _SYSTEM is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("erfassung_system", Path(__file__).resolve().parent.parent / "erfassung" / "system.py")
        _SYSTEM = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_SYSTEM)
    return _SYSTEM


_SYSTEM = None
system = system_modul()                        # Plattformabhängiges (Datenträger, Prozesse, Dialoge) nur über system
VERSION = version()                            # einmal beim Start ermitteln
PROJEKTE = system.projekte_vorgabe()           # Git: Projekte/ neben dem Code; Paket: Dokumente/Balduin-Projekte
ZULETZT = system.zuletzt_datei()               # zuletzt geöffnete Projekte (macOS ~/Library/Application Support/Balduin)
VOLUMES = system.VOLUMES                       # macOS /Volumes, Windows die Laufwerksbuchstaben (Tests: ein Ordner)
# Eastereggs (Entscheidungen 05. und 13.11.2026): Die Seite trägt lang="de-AT" bzw. "de-CH", sprache.js zeigt dann
# „skartieren“ statt „kassieren“ bzw. „ss“ statt „ß“
SPRACHE = {"AT": "de-AT", "CH": "de-CH"}.get(system_modul().systemregion(), "de")
ARTEN = ("exakt", "variante", "beinahe")
AMPELN = ("grün", "gelb", "rot")
F5_KENNUNG = "yolox_s+yunet"      # Modelle von F5 wie KENNUNG in erfassung/personen.py; ältere Ergebnisse gelten als offen

# Verwaltungsdateien von macOS und Windows gehören nicht zum Bestand
SYSTEMDATEIEN = {".DS_Store", "Thumbs.db", "desktop.ini", ".localized"}


def ist_systemdatei(relpfad):
    name = relpfad.rsplit("/", 1)[-1]
    # __MACOSX/ legt das Archivprogramm des Mac in ZIPs an (wie ist_systemdatei in erfassung/basis.py)
    return name in SYSTEMDATEIEN or name.startswith("._") or "__MACOSX/" in relpfad


# Endungen der Archivdateien, die Balduin wie Ordner auflöst (wie art_von in erfassung/archivdateien.py)
ARCHIV_ENDUNG = re.compile(r".\.(zip|tar|tgz|tbz2?|txz|gz|bz2|xz)$", re.I)


# Archivdateien, die noch kein Schnellscan geprüft hat (vor dem 06.11.2026 gelesen): C bleibt offen
# (gleiche Abfrage wie ARCHIVE_UNGEPRUEFT in erfassung/schnellscan.py, dort je Platte)
ARCHIVE_UNGEPRUEFT_SQL = """SELECT s.platte_id, COUNT(*) FROM schnellscan s
    WHERE s.archiv IS NULL AND NOT EXISTS (SELECT 1 FROM archivdatei a WHERE a.platte_id = s.platte_id AND a.relpfad = s.relpfad)
      AND (s.name LIKE '%_.zip' OR s.name LIKE '%_.tar' OR s.name LIKE '%_.tgz' OR s.name LIKE '%_.tbz'
           OR s.name LIKE '%_.tbz2' OR s.name LIKE '%_.txz' OR s.name LIKE '%_.gz' OR s.name LIKE '%_.bz2'
           OR s.name LIKE '%_.xz') AND substr(s.name, 1, 2) != '._'
    GROUP BY s.platte_id"""


def archivdatei_darueber(wurzel, relpfad):
    """Pfad der Archivdatei auf der Platte, in der eine Datei liegt (Entscheidung 06.11.2026), oder None.
    Nur lesend: prüft, welcher Teil des Pfads auf der Platte eine Datei ist."""
    teile = relpfad.split("/")
    for i in range(1, len(teile)):
        kopf = "/".join(teile[:i])
        for form in (kopf, unicodedata.normalize("NFD", kopf)):
            pfad = Path(wurzel) / form
            if pfad.is_file():
                return pfad if ARCHIV_ENDUNG.search(teile[i - 1]) else None
    return None


def nfc(text):
    return unicodedata.normalize("NFC", text)


def kennung_pruefen(platte_id):
    """Kennung eines Datenträgers: 1–20 Zeichen, nur Buchstaben, Ziffern, - und _."""
    platte_id = str(platte_id or "").strip()
    if not platte_id or len(platte_id) > 20 or not all(z.isalnum() or z in "-_" for z in platte_id):
        raise ValueError("Kennung fehlt oder enthält andere Zeichen als Buchstaben, Ziffern, - und _.")
    return platte_id


def beschreibbar_gesperrt(q, zugestimmt, echte_datentraeger):
    """„Datei zeigen“ auf einem beschreibbar eingehängten Datenträger nur nach Zustimmung zum Lesen ohne Schreibschutz
    (Entscheidung 13.11.2026); in den Tests sind die Datenträger gewöhnliche Ordner."""
    return echte_datentraeger and not q["schreibgeschuetzt"] and not zugestimmt


def elternordner(relpfad):
    return relpfad.rsplit("/", 1)[0] if "/" in relpfad else ""


def im_ordner(relpfad, ordner):
    """Liegt relpfad in ordner (mit Unterordnern)? Ordner "" ist die ganze Platte."""
    return ordner == "" or relpfad.startswith(ordner + "/")


# Voraussetzungen der Schritte der Analyse, wie „braucht“ in SCHRITTE von tool/web/erfassung.js
BRAUCHT = {"C": [], "D1": ["C"], "D2": ["D1"], "D3": ["D1"], "E": ["D1", "D3"], "E4": ["D1", "D3"],
           "F": ["D2", "D3"], "F5": ["F"], "G": ["D1", "E", "F"], "G5": ["D1"], "H": ["D2", "D3", "E", "F", "G"]}


def erledigte_schritte(offen, chips, ausstehend=()):
    """Schritte, deren Chip grün ist (Feedback 06.11.2026): nichts mehr offen (0), alle Voraussetzungen erledigt
    (sonst stünden etwa Formate und Virenscan auf 0, solange D1 noch Prüfsummen rechnet) und nicht mehr ausstehend
    im laufenden Lauf der Platte (sonst wären Texte ohne Dokumente grün, bevor E4 dran war)."""
    erledigt = []
    # Fehlen nach dem Schnellscan nur ungeöffnete Archivdateien, bleibt C offen, gilt für die Folgeschritte aber als
    # erfüllt (Entscheidung 06.11.2026): sonst fiele eine ältere, fertig analysierte Platte auf 0 %
    erfuellt = {"C"} if offen.get("C") and offen.get("C") == offen.get("C_archive") else set()
    for k in chips:
        if offen.get(k) == 0 and k not in ausstehend and all(v in erledigt or v in erfuellt for v in BRAUCHT.get(k, [])):
            erledigt.append(k)
    return erledigt


def kette_nach_oben(relpfad):
    """Alle Ordner über einer Datei bis zur Platte (""), unterster zuerst."""
    kette = [elternordner(relpfad)]
    while kette[-1]:
        kette.append(elternordner(kette[-1]))
    return kette


# Entscheidungen und ihr Schlüssel in den Zählern; offen = keine Entscheidung
ENTSCHEIDUNGEN = {"übernehmen": "uebernehmen", "kassieren": "kassieren", "zurückstellen": "zurueckgestellt"}
SCHEMA = """
CREATE TABLE IF NOT EXISTS entscheidung (
    platte_id TEXT, pfad TEXT, art TEXT, entscheidung TEXT, vorbehalt INTEGER DEFAULT 0,
    begruendung TEXT, wer TEXT, zeit TEXT,
    PRIMARY KEY (platte_id, pfad));
-- Ideen zur späteren Erschließung je Platte, Ordner oder Datei; unabhängig von der Entscheidung
CREATE TABLE IF NOT EXISTS erschliessungshinweis (
    platte_id TEXT, pfad TEXT, hinweis TEXT, wer TEXT, zeit TEXT,
    PRIMARY KEY (platte_id, pfad));
CREATE TABLE IF NOT EXISTS protokoll (
    zeit TEXT, abschnitt TEXT, objekt TEXT, feld TEXT, alt TEXT, neu TEXT);
-- Ohne Schreibschutz lesen (Entscheidung 13.11.2026): Zustimmung je Datenträger und wann er zuerst so gelesen wurde
CREATE TABLE IF NOT EXISTS schreibschutz_verzicht (
    platte_id TEXT PRIMARY KEY, zugestimmt_am TEXT, gelesen_am TEXT);
CREATE TABLE IF NOT EXISTS einstellung (schluessel TEXT PRIMARY KEY, wert TEXT);
-- E1: vollständige ExifTool-Ausgabe je Inhalt und Endung (zlib-komprimiertes JSON ohne Fundortangaben);
-- E4: Text der Dokumente (zlib-komprimiert) mit Titelkandidaten (JSON); dieselben Tabellen legt erfassung/basis.py an
CREATE TABLE IF NOT EXISTS exif_voll (
    sha256 TEXT, endung TEXT, daten BLOB, felder INTEGER, exiftool TEXT, fehler TEXT, gelesen_am TEXT, quelle TEXT,
    PRIMARY KEY (sha256, endung));
CREATE TABLE IF NOT EXISTS volltext (
    sha256 TEXT, endung TEXT, text BLOB, zeichen INTEGER, seiten INTEGER, weg TEXT, titel TEXT, fehler TEXT,
    gelesen_am TEXT, quelle TEXT,
    PRIMARY KEY (sha256, endung));
-- F5 Personen und Gesichter auf Fotos (erfassung/personen.py); dieselbe Tabelle legt erfassung/basis.py an
CREATE TABLE IF NOT EXISTS personen (
    sha256 TEXT PRIMARY KEY, anzahl INTEGER, score REAL, modell TEXT, fehler TEXT, erkannt_am TEXT,
    gesichter INTEGER, gesicht_anteil REAL, person_anteil REAL, bildtyp TEXT);
-- Läufe der Erfassung; dieselben Tabellen legt erfassung/basis.py an
CREATE TABLE IF NOT EXISTS lauf (
    lauf_id INTEGER PRIMARY KEY AUTOINCREMENT, art TEXT, platte_id TEXT, auftrag TEXT, status TEXT,
    pid INTEGER, start TEXT, ende TEXT, abbrechen INTEGER DEFAULT 0, meldung TEXT, log TEXT);
CREATE TABLE IF NOT EXISTS lauf_schritt (
    lauf_id INTEGER, schritt TEXT, titel TEXT, status TEXT, anteil REAL, text TEXT, start TEXT, ende TEXT,
    PRIMARY KEY (lauf_id, schritt));
"""

# Globale Einstellungen: diese Dateien werden automatisch kassiert (Vorrang hat nur eine eigene Entscheidung an der Datei)
EINSTELLUNGEN = {
    "systemdateien": "Systemdateien kassieren (.DS_Store, Thumbs.db, ._…)",
    "leere": "Leere Dateien (0 Byte) kassieren",
    "anton": "Dateien, die schon in Anton liegen (gleiche MD5), kassieren",
}
# Zeilen herausgenommener Platten auslassen ({} = Kürzel der Tabelle)
LAUF_NAMEN = {"anton": "Bestand aus Anton", "vorlauf": "Vorlauf", "export": "Export"}      # Läufe ohne Platte (wie erfassung/lauf.py)
HERAUSGENOMMEN = "{}.platte_id NOT IN (SELECT platte_id FROM platte WHERE deaktiviert_am IS NOT NULL)"
AUTO = "\x00"          # Kennung einer automatischen Entscheidung in der Quelle; kommt in keinem Pfad vor

# Regeln im Editor: Werkzeuge, die passende Dateien der Auswahl einzeln kassieren oder zurückstellen
REGELN = {
    "rot": ("Archiv rot kassieren", "Dateien mit roter Ampel (Format nicht archivfähig oder Datei nicht lesbar)."),
    "varianten": ("Varianten: nur beste Fassung behalten",
                  "Gleiche Aufnahme in mehreren Formaten (z. B. TIF neben JPG): behalten wird die Leitdatei, sonst "
                  "die archivfähigste, bei Gleichstand die mit den meisten Pixeln, dann die größte Datei. Liegt die "
                  "kassierte in einem anderen Ordner, erhält die behaltene einen Erschließungshinweis."),
    "exakt": ("Exakte Kopien: nur eine behalten", "Bitgleiche Dateien in der Auswahl; behalten wird die Leitdatei, "
              "sonst die erste nach Pfad."),
    "klein": ("Kleine Bilder kassieren", "Bilder, deren lange Seite kürzer ist als die Mindestgröße (Icons, Webschnipsel)."),
    "software": ("Programme und Treiber kassieren", "Installations- und Programmdateien (.exe, .dmg, .app …)."),
    "stichprobe": ("Stichprobe", "In jedem gewählten Ordner werden alle Dateien samt Unterordnern nach Pfad sortiert "
                   "durchgezählt; jedes x. Element wird übernommen (beginnend mit dem ersten), die übrigen kassiert. "
                   "Einzeln gewählte Dateien zählen zusammen als eine Reihe. Für gleichförmige Serien, von denen ein "
                   "Querschnitt genügt."),
}
SOFTWARE = {".exe", ".msi", ".dmg", ".pkg", ".mpkg", ".dll", ".sys", ".inf", ".drv", ".bat", ".cmd", ".com",
            ".jar", ".apk", ".so", ".dylib", ".bin", ".cab", ".vxd", ".ocx", ".cpl", ".scr"}
AMPEL_RANG = {"grün": 3, "gelb": 2, "rot": 1}
FASSUNG_NAME = {"variante": "der Formatvariante", "exakt": "der bitgleichen Kopie"}   # für Erschließungshinweise


def endung(relpfad):
    name = relpfad.rsplit("/", 1)[-1]
    return "." + name.rsplit(".", 1)[-1].lower() if "." in name.lstrip(".") else "(ohne)"


def zaehler_schluessel(wirksam):
    return ENTSCHEIDUNGEN[wirksam[0]] if wirksam else "offen"


def neuer_zaehler():
    return {"dateien": 0, "bytes": 0, **{a: 0 for a in AMPELN}, "ohne_ampel": 0,
            **{a: 0 for a in ARTEN}, **{"stark_" + a: 0 for a in ARTEN}, "in_anton": 0,
            **{k: 0 for k in ENTSCHEIDUNGEN.values()}, "offen": 0, "vorbehalt": 0, "personen": 0}


class SchreibVerbindung:
    """`with bestand.schreibend() as con:` speichert am Ende, verwirft bei einem Fehler alles und schließt."""

    def __init__(self, con, nach_dem_speichern=None):
        self.con, self.nach_dem_speichern = con, nach_dem_speichern

    def __enter__(self):
        return self.con

    def __exit__(self, fehler, *_):
        try:
            if fehler is None:
                self.con.commit()
                if self.nach_dem_speichern:
                    self.nach_dem_speichern()
            else:
                self.con.rollback()
        finally:
            self.con.close()


class Bestand:
    """Hält Baum, Zähler und Duplikatgruppen im Speicher. Wird neu geladen, wenn sich die Datenbank ändert."""

    def __init__(self, db_pfad, vorschauen):
        self.db_pfad = Path(db_pfad)
        self.vorschau_ordner = Path(vorschauen)       # Ordner der Vorschaubilder (im Projekt oder auf der Arbeitsplatte)
        self.sperre = threading.Lock()
        self.stand = None
        self.schreibzaehler = 0                         # eigene Schreibvorgänge (Teil des Stands, siehe db_stand)
        wal = sqlite3.connect(self.db_pfad, timeout=15)   # Schreibprotokoll wie erfassung.basis.wal_einschalten
        try:
            wal.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            pass
        finally:
            wal.close()
        with self.schreibend() as con:
            tabellen_umstellen(con)                       # Modul 4: Pakettabellen vom 05.11.2026 (export/schema.py)
            con.executescript(SCHEMA + SCHEMA_ERSCHLIESSUNG + SCHEMA_PAKETE)
            # wie datenbank_einrichten in erfassung/basis.py, falls das Tool vor dem ersten Lauf startet
            spalten = {z[1] for z in con.execute("PRAGMA table_info(platte)")}
            if spalten and "deaktiviert_am" not in spalten:
                con.execute("ALTER TABLE platte ADD COLUMN deaktiviert_am TEXT")
            if spalten and "traeger" not in spalten:          # Art des Datenträgers (05.11.2026)
                con.execute("ALTER TABLE platte ADD COLUMN traeger TEXT")
            if spalten and "verschluesselt" not in spalten:   # verschlüsseltes APFS-Volume (13.11.2026)
                con.execute("ALTER TABLE platte ADD COLUMN verschluesselt INTEGER")
            spalten = {z[1] for z in con.execute("PRAGMA table_info(personen)")}
            for spalte, typ in (("gesichter", "INTEGER"), ("gesicht_anteil", "REAL"), ("person_anteil", "REAL"),
                                ("bildtyp", "TEXT")):
                if spalte not in spalten:
                    con.execute(f"ALTER TABLE personen ADD COLUMN {spalte} {typ}")
            for tabelle, spalte, typ in (("bestandsbox", "laufzeit", "TEXT"), ("bestandsbox", "gesperrt", "INTEGER"),
                                         ("ebene", "signatur", "TEXT"), ("ebene", "stufe_name", "TEXT"),
                                         ("zuordnung", "stufe_name", "TEXT")):
                if spalte not in {z[1] for z in con.execute(f"PRAGMA table_info({tabelle})")}:
                    con.execute(f"ALTER TABLE {tabelle} ADD COLUMN {spalte} {typ}")
            # Archivdateien wie Ordner (06.11.2026): C zeigt ältere Platten mit Archivdateien als offen
            spalten = {z[1] for z in con.execute("PRAGMA table_info(schnellscan)")}
            if spalten and "archiv" not in spalten:
                con.execute("ALTER TABLE schnellscan ADD COLUMN archiv TEXT")
            con.execute("""CREATE TABLE IF NOT EXISTS archivdatei (
                platte_id TEXT, relpfad TEXT, art TEXT, status TEXT, meldung TEXT, dateien INTEGER,
                bytes_entpackt INTEGER, groesse INTEGER, mtime REAL, sha256 TEXT, md5 TEXT, lauf_id INTEGER, zeit TEXT,
                PRIMARY KEY (platte_id, relpfad))""")             # wie in erfassung/basis.py
        self.laden()

    def verbinden(self):
        """Nur lesend; geschrieben wird allein über schreibend()."""
        con = sqlite3.connect(f"file:{quote(str(self.db_pfad))}?mode=ro", uri=True, check_same_thread=False)
        con.row_factory = sqlite3.Row
        return con

    def schreibend(self):
        """Verbindung zum Schreiben; mit `with` gilt: alles oder nichts. Wartet bis 15 s, falls ein Lauf schreibt."""
        con = sqlite3.connect(self.db_pfad, timeout=15)
        con.row_factory = sqlite3.Row
        return SchreibVerbindung(con, self.geschrieben)

    def geschrieben(self):
        self.schreibzaehler += 1

    def db_stand(self):
        """Wann sich die Datenbank geändert hat: Änderungsdatum und Größe von inventar.sqlite und -wal, dazu die
        eigenen Schreibvorgänge. Unter Windows wird das Änderungsdatum grob fortgeschrieben (Takt ~15 ms); ohne Zähler
        sahen zwei schnelle Speichervorgänge gleich aus (Windows-VM, 12.11.2026)."""
        teile = []
        for p in (self.db_pfad, f"{self.db_pfad}-wal"):
            try:
                st = os.stat(p)
                teile += [st.st_mtime, st.st_size]
            except OSError:
                teile += [0, 0]
        return (*teile, self.schreibzaehler)

    def aktuell_halten(self):
        if self.db_stand() != self.stand:
            with self.sperre:
                if self.db_stand() != self.stand:
                    self.laden()

    def laden(self):
        start = time.time()
        stand = self.db_stand()
        con = self.verbinden()
        try:
            # aus dem Projekt genommene Platten (Analyse, Inspektor) bleiben in der Datenbank, hier aber außen vor
            self.platten = [dict(z) for z in con.execute(
                "SELECT * FROM platte WHERE deaktiviert_am IS NULL ORDER BY platte_id")]
            for p in self.platten:                           # Art des Datenträgers fürs Icon (05.11.2026)
                p["traeger"] = system_modul().traeger_der_platte(p)
            dateien = con.execute(f"""
                SELECT s.platte_id, s.relpfad, s.groesse, d.sha256, d.mime, d.format, a.ampel, ab.status AS anton,
                       m.breite, m.hoehe
                FROM schnellscan s
                LEFT JOIN datei d USING (platte_id, relpfad)
                LEFT JOIN metadaten m USING (platte_id, relpfad)
                LEFT JOIN archiv a USING (platte_id, relpfad)
                LEFT JOIN anton_abgleich ab USING (platte_id, relpfad)
                WHERE {HERAUSGENOMMEN.format("s")}""").fetchall()
            gruppen = con.execute("SELECT art, gruppe_id, platte_id, relpfad, leitdatei FROM gruppe g "
                                  f"WHERE {HERAUSGENOMMEN.format('g')}").fetchall()
            self.vorschauen = {z[0]: z[1] for z in con.execute(
                "SELECT sha256, datei FROM vorschau WHERE datei IS NOT NULL AND datei != ''")}
            # F5: Fotos mit erkannten Personen oder Gesichtern (nur Anzeige: Symbol und Anzeige-Option der Galerie);
            # Bildtyp porträt/personen, ältere Ergebnisse ohne Bildtyp (nur YOLOX) gelten als personen
            self.personen = {z[0]: (z[1] or 0, z[2] or 0, z[3] or "personen") for z in con.execute(
                "SELECT sha256, anzahl, gesichter, bildtyp FROM personen WHERE anzahl > 0 OR gesichter > 0")}
            self.ordnergruppen = [tuple(z) for z in con.execute(
                f"SELECT gruppe_id, platte_id, ordner FROM ordnergruppe o WHERE {HERAUSGENOMMEN.format('o')}")]
            self.regeln = {(z["platte_id"], z["pfad"]): dict(z) for z in con.execute("SELECT * FROM entscheidung")}
            self.einstellungen = {k: True for k in EINSTELLUNGEN}       # Standard: alle an
            self.einstellungen.update({z["schluessel"]: z["wert"] == "1" for z in con.execute("SELECT * FROM einstellung")
                                       if z["schluessel"] in EINSTELLUNGEN})
        finally:
            con.close()

        # Duplikatgruppen: je Datei ihre Gruppen, je Gruppe ihre Mitglieder
        self.gruppen_von = defaultdict(list)          # (platte, relpfad) -> [(art, gruppe_id, leit)]
        self.mitglieder = defaultdict(list)           # gruppe_id -> [(platte, relpfad)]
        self.leit = {}                                # gruppe_id -> Leitdatei (H2), Maßstab für „beste Fassung“
        for g in gruppen:
            schluessel = (g["platte_id"], g["relpfad"])
            self.gruppen_von[schluessel].append((g["art"], g["gruppe_id"], bool(g["leitdatei"])))
            self.mitglieder[g["gruppe_id"]].append(schluessel)
            if g["leitdatei"]:
                self.leit[g["gruppe_id"]] = schluessel

        # Baum: je Platte und Ordner die Unterordner, Dateien und Zähler (mit allen Unterordnern)
        self.dateien = {}                             # (platte, relpfad) -> Angaben
        self.unterordner = defaultdict(set)           # (platte, ordner) -> {Unterordnerpfade}
        self.dateien_in = defaultdict(list)           # (platte, ordner) -> [relpfad] (nur direkt darin)
        self.zaehler = defaultdict(neuer_zaehler)     # (platte, ordner) -> Zähler ohne Systemdateien
        self.gleicher_inhalt = defaultdict(list)      # sha256 -> [(platte, relpfad)] ohne Systemdateien (bitgleich)
        for p in self.platten:
            self.zaehler[(p["platte_id"], "")]
        for z in dateien:
            platte, relpfad = z["platte_id"], z["relpfad"]
            system = ist_systemdatei(relpfad)
            arten = {a for a, _, _ in self.gruppen_von.get((platte, relpfad), [])}
            self.dateien[(platte, relpfad)] = {
                "groesse": z["groesse"] or 0, "sha256": z["sha256"], "ampel": z["ampel"],
                "anton": z["anton"], "system": system, "arten": sorted(arten, key=ARTEN.index),
                "mime": z["mime"] or "", "format": z["format"] or "", "breite": z["breite"], "hoehe": z["hoehe"],
                **dict(zip(("personen", "gesichter", "bildtyp"), self.personen.get(z["sha256"], (0, 0, ""))))}
            kette = kette_nach_oben(relpfad)
            self.dateien_in[(platte, kette[0])].append(relpfad)
            # Ordnerkette nach oben registrieren und zählen
            for kind, eltern in zip(kette, kette[1:]):
                self.unterordner[(platte, eltern)].add(kind)
            if system:
                continue
            if z["sha256"]:
                self.gleicher_inhalt[z["sha256"]].append((platte, relpfad))
            for o in kette:
                zz = self.zaehler[(platte, o)]
                zz["dateien"] += 1
                zz["bytes"] += z["groesse"] or 0
                zz[z["ampel"] if z["ampel"] in AMPELN else "ohne_ampel"] += 1
                for a in arten:
                    zz[a] += 1
                if arten:                             # für den Balken jede Datei nur einmal, nach stärkster Art
                    zz["stark_" + min(arten, key=ARTEN.index)] += 1
                zz["in_anton"] += z["anton"] == "in Anton"
                zz["personen"] += bool(self.dateien[(platte, relpfad)]["bildtyp"])
                zz["offen"] += 1                      # unten umgebucht, wenn eine Entscheidung gilt

        # Wirksame Entscheidung je Datei: die nächste auf dem Weg von der Datei zur Platte
        self.wirksam_je_datei = {}                    # (platte, relpfad) -> (entscheidung, vorbehalt, quelle)
        for (platte, relpfad), d in self.dateien.items():
            if not d["system"]:
                w = self.wirksam(platte, relpfad)
                if w:
                    self.wirksam_je_datei[(platte, relpfad)] = w
                    self.umbuchen(platte, relpfad, None, w)

        # Suchliste: erst alle Ordner, dann alle Dateien, je nach Platte und Pfad sortiert
        ordner = {(p, o) for (p, _), kinder in self.unterordner.items() for o in kinder}
        self.suchliste = [(p, o, "ordner", o.casefold(), o.rsplit("/", 1)[-1].casefold()) for p, o in sorted(ordner)]
        self.suchliste += [(p, r, "datei", r.casefold(), r.rsplit("/", 1)[-1].casefold()) for p, r in sorted(self.dateien)]

        # Gruppen ohne Leitdatei (G lief, H danach nicht): Die Prüfung der Fassungen nimmt dann den Ersatzmaßstab
        arten_von = {gid: a for ks in self.gruppen_von.values() for a, gid, _ in ks}
        self.ohne_leitdatei = sum(1 for gid in self.mitglieder if gid not in self.leit
                                  and arten_von.get(gid) in ("exakt", "variante"))

        self.stand = stand
        self.geladen_am = time.strftime("%d.%m.%Y %H:%M:%S")
        print(f"Datenbank geladen: {len(self.dateien):,} Dateien, {len(self.mitglieder):,} Dublettengruppen "
              f"in {time.time() - start:.1f} s", flush=True)

    # ---- Entscheidungen ----

    def wirksam(self, platte, pfad, regeln=None):
        """Nächste Entscheidung auf dem Weg von pfad (Datei oder Ordner) zur Platte: (entscheidung, vorbehalt, quelle).
        Eine Entscheidung „offen“ setzt bewusst zurück: Darunter gilt nichts von weiter oben."""
        regeln = self.regeln if regeln is None else regeln
        p = pfad
        if (platte, pfad) in self.dateien:            # Datei: eigene Entscheidung, dann globale Einstellung
            r = regeln.get((platte, pfad))
            if r:
                return None if r["entscheidung"] == "offen" else (r["entscheidung"], bool(r["vorbehalt"]), pfad)
            grund = self.automatisch(platte, pfad)
            if grund:
                return ("kassieren", False, AUTO + grund)
            p = elternordner(pfad)
        while True:
            r = regeln.get((platte, p))
            if r:
                return None if r["entscheidung"] == "offen" else (r["entscheidung"], bool(r["vorbehalt"]), p)
            if p == "":
                return None
            p = elternordner(p)

    def automatisch(self, platte, relpfad):
        """Greift eine globale Einstellung? Gibt ihren Schlüssel zurück oder None."""
        d = self.dateien[(platte, relpfad)]
        for schluessel, trifft in (("systemdateien", d["system"]), ("leere", d["groesse"] == 0),
                                   ("anton", d["anton"] == "in Anton")):
            if trifft and self.einstellungen[schluessel]:
                return schluessel
        return None

    def alles_neu_berechnen(self):
        """Nach einer geänderten Einstellung: wirksame Entscheidung aller Dateien prüfen und Zähler nachführen."""
        for k, d in self.dateien.items():
            if d["system"]:
                continue
            alt, neu = self.wirksam_je_datei.get(k), self.wirksam(*k)
            if (alt or ())[:2] != (neu or ())[:2]:
                self.umbuchen(*k, alt, neu)
            if neu:
                self.wirksam_je_datei[k] = neu
            else:
                self.wirksam_je_datei.pop(k, None)

    def einstellung_setzen(self, schluessel, an):
        if schluessel not in EINSTELLUNGEN:
            raise ValueError(f"unbekannte Einstellung {schluessel!r}")
        with self.sperre:
            alt = self.einstellungen[schluessel]
            with self.schreibend() as con:
                con.execute("INSERT OR REPLACE INTO einstellung VALUES (?, ?)", (schluessel, "1" if an else "0"))
                if alt != bool(an):
                    con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                                (time.strftime("%Y-%m-%dT%H:%M:%S"), "Bewertung", "Einstellung", schluessel,
                                 "an" if alt else "aus", "an" if an else "aus"))
            self.einstellungen[schluessel] = bool(an)
            self.alles_neu_berechnen()
            self.stand = self.db_stand()
        return {"ok": True}

    def einstellungen_json(self):
        anzahl = {"systemdateien": 0, "leere": 0, "anton": 0}
        for d in self.dateien.values():
            anzahl["systemdateien"] += d["system"]
            anzahl["leere"] += d["groesse"] == 0 and not d["system"]
            anzahl["anton"] += d["anton"] == "in Anton" and not d["system"]
        return [{"schluessel": k, "text": t, "an": self.einstellungen[k], "dateien": anzahl[k]}
                for k, t in EINSTELLUNGEN.items()]

    def umbuchen(self, platte, relpfad, alt, neu):
        """Zähler aller Ordner über einer Datei von der alten auf die neue Entscheidung umstellen."""
        for o in kette_nach_oben(relpfad):
            zz = self.zaehler[(platte, o)]
            zz[zaehler_schluessel(alt)] -= 1
            zz[zaehler_schluessel(neu)] += 1
            zz["vorbehalt"] += (bool(neu and neu[1]) - bool(alt and alt[1]))

    def betroffene(self, platte, pfad):
        """Dateien (ohne Systemdateien), deren wirksame Entscheidung von einer Entscheidung an pfad abhängen kann."""
        pfade = [pfad] if (platte, pfad) in self.dateien else self.dateien_unter(platte, pfad)
        return [(platte, r) for r in pfade if not self.dateien[(platte, r)]["system"]]

    def urteil(self, platte, pfad):
        w = self.wirksam(platte, pfad)
        if not w:
            return None
        if w[2].startswith(AUTO):
            return {"entscheidung": w[0], "vorbehalt": False, "eigen": False, "quelle": None,
                    "automatisch": EINSTELLUNGEN[w[2][1:]]}
        return {"entscheidung": w[0], "vorbehalt": w[1], "eigen": w[2] == pfad, "quelle": w[2]}

    def schutz_pruefen(self, betroffen, regeln_neu):
        """Schutzregel: Inhalte, deren exakte Kopien danach alle kassiert wären (und die nicht schon in Anton liegen)."""
        simuliert = {k: self.wirksam(*k, regeln=regeln_neu) for k in betroffen}
        jetzt_von = lambda k: simuliert[k] if k in simuliert else self.wirksam_je_datei.get(k)
        geprueft, verletzt = set(), []
        for k, w in simuliert.items():
            if not w or w[0] != "kassieren" or (self.wirksam_je_datei.get(k) or ("",))[0] == "kassieren":
                continue
            for art, gid, _ in self.gruppen_von.get(k, []):
                if art != "exakt" or gid in geprueft:
                    continue
                geprueft.add(gid)
                kopien = [m for m in self.mitglieder[gid] if m in self.dateien and not self.dateien[m]["system"]]
                if any(self.dateien[m]["anton"] == "in Anton" for m in kopien):
                    continue
                if all((jetzt_von(m) or ("",))[0] == "kassieren" for m in kopien):
                    verletzt.append(k)
        # Einzelstücke (ohne Kopie) dürfen ohne Rückfrage kassiert werden: Das ist eine bewusste Bewertung.
        return {"inhalte": len(verletzt), "beispiele": [f"{p} / {r}" for p, r in verletzt[:5]]}

    # ---- Prüfung der Fassungen (plan.md, Entscheidungen 30.10.2026) ----

    def status(self, k, simuliert=None):
        """Wirksame Entscheidung einer Datei als Wort; simuliert: geplante neue Werte für einen Teil der Dateien."""
        w = simuliert[k] if simuliert is not None and k in simuliert else self.wirksam_je_datei.get(k)
        return (w or ("offen",))[0]

    def bitgleich(self, a, b):
        return self.dateien[a]["sha256"] is not None and self.dateien[a]["sha256"] == self.dateien[b]["sha256"]

    def fassung_rang(self, k):
        """Ersatzmaßstab, wenn die Leitdatei fehlt (wie die Regel „Varianten“): Ampel, dann Pixel, dann Größe."""
        d = self.dateien[k]
        return AMPEL_RANG.get(d["ampel"], 0), (d["breite"] or 0) * (d["hoehe"] or 0), d["groesse"]

    def beste_fassung(self, gid):
        """Leitdatei aus H2; fehlt sie (H noch nicht gelaufen), die nach fassung_rang beste."""
        leit = self.leit.get(gid)
        if leit in self.dateien and not self.dateien[leit]["system"]:
            return leit
        kandidaten = [m for m in self.mitglieder[gid] if m in self.dateien and not self.dateien[m]["system"]]
        return max(kandidaten, key=self.fassung_rang, default=None)

    def fassungen_paare(self, ziele, entscheidung):
        """Formatvarianten, nur wenn alle Ziele einzelne Dateien sind: je Fall Paare aus gewählter und anderer Fassung.
        besser: (datei, beste) · weitere: (beste, andere) · beste_kassiert: (beste, übernommene).
        Bitgleiche Paare zählen hier nicht (gleich gut, dafür mehrfach_paare), „beinahe gleich“ auch nicht."""
        paare = {"besser": [], "weitere": [], "beste_kassiert": []}
        if entscheidung not in ("übernehmen", "kassieren") or not ziele \
                or any(k not in self.dateien or self.dateien[k]["system"] for k in ziele):
            return paare
        gewaehlt, gesehen = set(ziele), set()
        for k in ziele:
            for art, gid, _ in self.gruppen_von.get(k, []):
                beste = self.beste_fassung(gid) if art == "variante" else None
                if beste is None:
                    continue
                andere = [m for m in self.mitglieder[gid] if m in self.dateien and m not in gewaehlt
                          and not self.dateien[m]["system"]]
                if entscheidung == "übernehmen" and k != beste and beste not in gewaehlt:
                    fall, neu = "besser", [(k, beste)]
                elif entscheidung == "übernehmen" and k == beste:
                    fall, neu = "weitere", [(k, m) for m in andere if self.status(m) != "kassieren"]
                elif entscheidung == "kassieren" and k == beste:
                    fall, neu = "beste_kassiert", [(k, m) for m in andere if self.status(m) == "übernehmen"]
                else:
                    continue
                for a, b in neu:
                    if not self.bitgleich(a, b) and (fall, a, b) not in gesehen:
                        gesehen.add((fall, a, b))
                        paare[fall].append((a, b))
        return paare

    def mehrfach_paare(self, betroffen, regeln_neu):
        """Schutzregel in die andere Richtung: Inhalte (SHA-256), die nach der Entscheidung öfter übernommen wären als
        vorher und mindestens zweimal. Je Inhalt (behalten, [übrige übernommene Kopien]); behalten wird eine Kopie aus
        dieser Entscheidung, unter mehreren die Leitdatei, sonst die erste nach Pfad. Braucht weder G noch H."""
        simuliert = {k: self.wirksam(*k, regeln=regeln_neu) for k in betroffen}
        neu = defaultdict(list)
        for k, w in simuliert.items():
            if w and w[0] == "übernehmen" and self.dateien[k]["sha256"]:
                neu[self.dateien[k]["sha256"]].append(k)
        ergebnis = []
        for sha, eigene in neu.items():
            kopien = self.gleicher_inhalt[sha]
            nachher = [m for m in kopien if self.status(m, simuliert) == "übernehmen"]
            if len(nachher) < 2 or len(nachher) <= sum(self.status(m) == "übernehmen" for m in kopien):
                continue
            leit = {self.leit.get(gid) for art, gid, _ in self.gruppen_von.get(eigene[0], []) if art == "exakt"}
            behalten = min(eigene, key=lambda m: (m not in leit, m))
            ergebnis.append((behalten, [m for m in nachher if m != behalten]))
        return ergebnis

    def ersatz_hinweise(self, paare, verb="übernommen"):
        """Erschließungshinweise für die behaltene Fassung, wenn die kassierte in einem anderen Ordner oder auf einer
        anderen Platte liegt: Fundort der kassierten samt den Hinweisen dort. paare: (behalten, kassiert, art)."""
        paare = [(b, k, a) for b, k, a in paare if b[0] != k[0] or elternordner(b[1]) != elternordner(k[1])]
        if not paare:
            return {}
        con = self.verbinden()
        try:
            vorhanden = {(z[0], z[1]): z[2] for z in con.execute("SELECT platte_id, pfad, hinweis FROM erschliessungshinweis")}
        finally:
            con.close()
        texte = defaultdict(list)
        for behalten, (p, r), art in paare:
            text = (f"Statt {FASSUNG_NAME[art]} {p} / {r} {verb} (dort kassiert). "
                    "Möglicherweise dort verwendet; bei Zuordnung und Erschließung prüfen.")
            for ort in [r, *kette_nach_oben(r)]:
                if (p, ort) in vorhanden:
                    wo = "dort" if ort == r else (f"zu {p} / {ort}" if ort else f"zum Datenträger {p}")
                    text += f" Erschließungshinweis {wo}: „{vorhanden[(p, ort)]}“"
            if text not in texte[behalten]:
                texte[behalten].append(text)
        return {b: "\n".join(t) for b, t in texte.items()}

    def fassung_kurz(self, k):
        d = self.dateien[k]
        return {**self.datei_kurz(*k), "format": d["format"], "breite": d["breite"], "hoehe": d["hoehe"],
                "eigen": k in self.regeln}

    def fassungen_pruefen(self, ziele, entscheidung, betroffen, regeln_neu):
        """Für den Dialog: je Fall Anzahl, Beispiele und der vorgeschlagene Erschließungshinweis. {} = nichts zu fragen."""
        paare = self.fassungen_paare(ziele, entscheidung)
        mehrfach = [(b, m) for b, ms in self.mehrfach_paare(betroffen, regeln_neu) for m in ms]
        if not any(paare.values()) and not mehrfach:
            return {}
        def fall(liste, ersetzt=(), art="variante", beispiele=8):
            if not liste:
                return None
            hinweise = self.ersatz_hinweise([(b, k, art) for b, k in ersetzt])
            return {"anzahl": len(liste), "dateien": len({a for a, _ in liste}),
                    "paare": [{"datei": self.fassung_kurz(a), "andere": self.fassung_kurz(b)} for a, b in liste[:beispiele]],
                    "in_anton": sum(self.dateien[b]["anton"] == "in Anton" for _, b in liste),
                    "eigen": sum(b in self.regeln for _, b in liste),
                    "hinweise": len(hinweise), "hinweis": next(iter(hinweise.values()), "")}
        besser, weitere = paare["besser"], paare["weitere"]
        return {"besser": fall(besser, [(b, a) for a, b in besser if self.dateien[b]["anton"] != "in Anton"]),
                "weitere": fall(weitere, [p for p in weitere if p[1] not in self.regeln]),
                "beste_kassiert": fall(paare["beste_kassiert"]),
                "mehrfach": fall(mehrfach, mehrfach, "exakt") | {"inhalte": len({b for b, _ in mehrfach})}
                if mehrfach else None}

    def eintrag(self, p, pf, entscheidung, vorbehalt, begruendung, wer, zeit):
        """Zeile der Tabelle entscheidung."""
        return {"platte_id": p, "pfad": pf, "entscheidung": entscheidung, "vorbehalt": int(vorbehalt),
                "art": "datei" if (p, pf) in self.dateien else ("platte" if pf == "" else "ordner"),
                "begruendung": begruendung.strip(), "wer": wer.strip(), "zeit": zeit}

    def fassungen_wahl(self, ziele, entscheidung, wahl, begruendung, betroffen, regeln_neu, vorbehalt, wer, zeit):
        """Wahl aus dem Dialog als zusätzliche Einzelentscheidungen in regeln_neu eintragen; gibt die geänderten Dateien
        und die Erschließungshinweise zurück. wahl: besser = diese | bessere | beide · weitere = nur_diese | kassieren ·
        mehrfach = trotzdem | eine · hinweis_<fall> = True (Vorschlag), False (keiner) oder Text (bei genau einem)."""
        paare = self.fassungen_paare(ziele, entscheidung)
        zusatz, hinweise = [], {}
        def setzen(k, e, grund):
            regeln_neu[k] = self.eintrag(*k, e, vorbehalt and e == "übernehmen", grund, wer, zeit)
            zusatz.append(k)
        def mit_hinweis(ersetzt, schalter, art="variante"):
            vorschlag = self.ersatz_hinweise([(b, k, art) for b, k in ersetzt])
            if isinstance(schalter, str) and len(vorschlag) == 1:
                vorschlag = {b: schalter.strip() for b in vorschlag} if schalter.strip() else {}
            elif schalter is False:
                vorschlag = {}
            for b, t in vorschlag.items():
                hinweise[b] = f"{hinweise[b]}\n{t}" if b in hinweise else t
        ersetzt = []
        for k, beste in paare["besser"]:
            if self.dateien[beste]["anton"] == "in Anton":
                continue                                  # schon archiviert: nur „trotzdem diese“
            if wahl.get("besser") == "bessere":
                setzen(beste, "übernehmen", begruendung or f"Statt {k[0]} / {k[1]} übernommen (bessere Fassung)")
                setzen(k, "kassieren", f"Bessere Fassung übernommen: {beste[0]} / {beste[1]}")
                ersetzt.append((beste, k))
            elif wahl.get("besser") == "beide":
                setzen(beste, "übernehmen", begruendung)
        mit_hinweis(ersetzt, wahl.get("hinweis_besser", True))
        if wahl.get("weitere") == "kassieren":
            ersetzt = [(k, m) for k, m in paare["weitere"] if m not in self.regeln]   # eigene Entscheidungen bleiben
            for k, m in ersetzt:
                setzen(m, "kassieren", f"Bessere Fassung übernommen: {k[0]} / {k[1]}")
            mit_hinweis(ersetzt, wahl.get("hinweis_weitere", True))
        if wahl.get("mehrfach") == "eine":                # nach den Varianten: sie können weitere Kopien übernehmen
            ersetzt = [(b, m) for b, ms in self.mehrfach_paare(list(dict.fromkeys([*betroffen, *zusatz])), regeln_neu)
                       for m in ms]
            for b, m in ersetzt:
                setzen(m, "kassieren", f"Bitgleiche Kopie übernommen: {b[0]} / {b[1]}")
            mit_hinweis(ersetzt, wahl.get("hinweis_mehrfach", True), "exakt")
        return zusatz, hinweise

    def hinweise_anhaengen(self, con, hinweise, wer, zeit):
        """Erschließungshinweise an vorhandene anhängen (nie ersetzen), protokolliert; in der Transaktion des Aufrufers."""
        for (p, pf), text in hinweise.items():
            alt = con.execute("SELECT hinweis FROM erschliessungshinweis WHERE platte_id = ? AND pfad = ?", (p, pf)).fetchone()
            alt = alt[0] if alt else ""
            if not text or text in alt:
                continue                                  # schon vermerkt (z. B. Regel zweimal angewandt)
            neu = f"{alt}\n{text}" if alt else text
            con.execute("INSERT OR REPLACE INTO erschliessungshinweis VALUES (?,?,?,?,?)", (p, pf, neu, wer.strip(), zeit))
            con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                        (zeit, "Bewertung", f"{p}:{pf}", "erschliessungshinweis",
                         f"Erschließungshinweis: {alt}" if alt else "", f"Erschließungshinweis: {neu}"))

    def entscheiden(self, ziele, entscheidung, vorbehalt=False, begruendung="", wer="", bestaetigt=False,
                    mit_ausnahmen=False, fassungen=None, hinweise=None):
        """Setzt die Entscheidung an allen Zielen. entscheidung=None hebt die eigene auf (dann gilt die übergeordnete),
        "offen" setzt auf unentschieden zurück; mit_ausnahmen entfernt dabei auch alle Entscheidungen darunter.
        fassungen: None = Fassungen prüfen und bei Bedarf fragen, False = nicht prüfen (Regeln), dict = Wahl aus dem
        Dialog; hinweise: {(platte, pfad): Text} werden mitgeschrieben (angehängt).
        Antwortet mit einer Rückfrage statt zu schreiben, wenn Fassungen zu klären sind oder die Schutzregel greift
        und nicht bestätigt ist."""
        if entscheidung is not None and entscheidung != "offen" and entscheidung not in ENTSCHEIDUNGEN:
            raise ValueError(f"unbekannte Entscheidung {entscheidung!r}")
        vorbehalt = bool(vorbehalt) and entscheidung == "übernehmen"
        ziele = [(p, nfc(pf)) for p, pf in ziele]
        for k in ziele:
            if k not in self.dateien and k not in self.zaehler:
                raise ValueError(f"{k[0]} / {k[1]} ist nicht im Inventar")
        with self.sperre:
            zeit = time.strftime("%Y-%m-%dT%H:%M:%S")
            regeln_neu = dict(self.regeln)
            for p, pf in ziele:
                if mit_ausnahmen and entscheidung == "offen":
                    for k in [k for k in regeln_neu if k[0] == p and k[1] != pf and im_ordner(k[1], pf)]:
                        del regeln_neu[k]
            for p, pf in ziele:
                regeln_neu.pop((p, pf), None)
                if entscheidung is None or (entscheidung == "offen" and self.wirksam(p, pf, regeln_neu) is None):
                    pass                                  # ohne übergeordnete Entscheidung reicht Löschen
                else:
                    regeln_neu[(p, pf)] = self.eintrag(p, pf, entscheidung, vorbehalt, begruendung, wer, zeit)
            betroffen = list(dict.fromkeys(k for p, pf in ziele for k in self.betroffene(p, pf)))
            hinweise, zusatz = dict(hinweise or {}), []
            if fassungen is None:                         # erst fragen, dann (mit der Wahl) schreiben
                frage = self.fassungen_pruefen(ziele, entscheidung, betroffen, regeln_neu)
                if frage:
                    return {"fassungen": frage}
            elif fassungen:
                zusatz, mehr = self.fassungen_wahl(ziele, entscheidung, fassungen, begruendung.strip(), betroffen,
                                                   regeln_neu, vorbehalt, wer, zeit)
                for k, t in mehr.items():
                    hinweise[k] = f"{hinweise[k]}\n{t}" if k in hinweise else t
                betroffen = list(dict.fromkeys([*betroffen, *zusatz]))
            if not bestaetigt:
                schutz = self.schutz_pruefen(betroffen, regeln_neu)
                if schutz["inhalte"]:
                    return {"warnung": schutz}

            # Datenbank: Entscheidungen schreiben und jede Änderung protokollieren (alles oder nichts)
            beschreibe = lambda r: "" if not r else "; ".join(filter(None, [
                r["entscheidung"], "Vorbehalt" if r["vorbehalt"] else "",
                f"Begründung: {r['begruendung']}" if r["begruendung"] else "", f"von {r['wer']}" if r["wer"] else ""]))
            geaendert = [k for k in dict.fromkeys([*ziele, *self.regeln, *regeln_neu])
                         if self.regeln.get(k) != regeln_neu.get(k)]
            with self.schreibend() as con:
                for p, pf in geaendert:
                    alt, neu = self.regeln.get((p, pf)), regeln_neu.get((p, pf))
                    if neu:
                        con.execute(f"INSERT OR REPLACE INTO entscheidung ({', '.join(neu)}) VALUES ({', '.join('?' * len(neu))})",
                                    list(neu.values()))
                    else:
                        con.execute("DELETE FROM entscheidung WHERE platte_id = ? AND pfad = ?", (p, pf))
                    if beschreibe(alt) != beschreibe(neu):
                        con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                                    (zeit, "Bewertung", f"{p}:{pf}", "entscheidung", beschreibe(alt),
                                     beschreibe(neu) or "aufgehoben"))
                self.hinweise_anhaengen(con, hinweise, wer, zeit)
            self.regeln = regeln_neu

            # Zähler nachführen, nur für die betroffenen Dateien
            for k in betroffen:
                alt, neu = self.wirksam_je_datei.get(k), self.wirksam(*k)
                if (alt or ())[:2] != (neu or ())[:2]:
                    self.umbuchen(*k, alt, neu)
                if neu:
                    self.wirksam_je_datei[k] = neu
                else:
                    self.wirksam_je_datei.pop(k, None)
            self.stand = self.db_stand()                # eigene Änderung: kein Neuladen nötig
        return {"ok": True, "ziele": len(ziele), "dateien": len(betroffen), "zusatz": len(zusatz),
                "hinweise": len(hinweise)}

    def bereich(self, ziele):
        """Alle Dateien (ohne Systemdateien) der Auswahl, ohne Doppelte."""
        return list(dict.fromkeys(k for p, pf in ziele for k in self.betroffene(p, pf)))

    def frei(self, k):
        """Datei ohne eigene Entscheidung und ohne automatische Kassation: nur solche ändern Regeln."""
        return k not in self.regeln and not self.automatisch(*k)

    def stichprobe(self, ziele, jedes):
        """Jedes x. Element (das 1., x+1., …) behalten, die übrigen kassieren; nur freie Dateien.
        Reihen: je gewählter Ordner (oder Platte) alle Dateien samt Unterordnern, nach Pfad sortiert;
        einzeln gewählte Dateien zusammen eine Reihe. Übergeordnete Ziele zuerst, damit eine Datei
        in einem mitgewählten Unterordner zur Reihe des oberen Ordners zählt."""
        reihen, lose, gesehen = [], [], set()
        for p, pf in sorted(ziele, key=lambda z: (z[0], len(z[1]))):
            ks = [k for k in self.betroffene(p, pf) if k not in gesehen and self.frei(k)]
            gesehen.update(ks)
            if (p, pf) in self.dateien:
                lose += ks
            else:
                reihen.append(ks)
        behalten, kassieren = [], []
        for reihe in [*reihen, lose]:
            for i, k in enumerate(sorted(reihe, key=lambda k: (k[0], k[1].casefold()))):
                (behalten if i % jedes == 0 else kassieren).append(k)
        return behalten, kassieren

    def regel_treffer(self, bereich, regel, endungen=(), grenze=300, behalten_von=None):
        """Dateien der Auswahl, die eine Regel kassieren würde (ohne Rücksicht auf eigene Entscheidungen).
        behalten_von (dict) erhält bei Varianten und exakten Kopien je kassierter Datei die behaltene."""
        d = self.dateien
        if regel == "rot":
            return [k for k in bereich if d[k]["ampel"] == "rot"]
        if regel == "formate":
            return [k for k in bereich if endung(k[1]) in endungen]
        if regel == "klein":
            return [k for k in bereich if d[k]["mime"].startswith("image/") and d[k]["breite"] and d[k]["hoehe"]
                    and max(d[k]["breite"], d[k]["hoehe"]) < grenze]
        if regel == "software":
            return [k for k in bereich if endung(k[1]) in SOFTWARE or ".app/" in k[1].lower()]
        if regel in ("varianten", "exakt"):
            art = "variante" if regel == "varianten" else "exakt"
            im_bereich, gruppen = set(bereich), defaultdict(list)
            for k in bereich:
                for a, gid, leit in self.gruppen_von.get(k, []):
                    if a == art:
                        gruppen[gid].append((k, leit))
            treffer = []
            for mitglieder in gruppen.values():
                if len(mitglieder) < 2:
                    continue
                if regel == "varianten":   # beste Fassung: Leitdatei (H2), sonst Ampel, dann Pixel, dann Größe
                    beste = max(mitglieder, key=lambda m: (m[1], *self.fassung_rang(m[0])))
                else:                      # exakt gleich: Leitdatei, sonst die erste nach Pfad
                    beste = min(mitglieder, key=lambda m: (not m[1], m[0]))
                neu = [k for k, _ in mitglieder if k != beste[0] and k in im_bereich]
                treffer += neu
                if behalten_von is not None:
                    behalten_von.update({k: beste[0] for k in neu})
            return treffer
        raise ValueError(f"unbekannte Regel {regel!r}")

    def regeln_angaben(self, ziele, grenze=300, jedes=10):
        """Für den Editor: welche Regeln in der Auswahl etwas treffen, mit Anzahl und Größe."""
        bereich = self.bereich(ziele)
        def zahlen(ks):
            f = [k for k in ks if self.frei(k)]
            return {"dateien": len(f), "bytes": sum(self.dateien[k]["groesse"] for k in f), "schon": len(ks) - len(f)}
        regeln = [{"regel": r, "titel": t, "erklaerung": e, **zahlen(self.regel_treffer(bereich, r, grenze=grenze))}
                  for r, (t, e) in REGELN.items() if r != "stichprobe"]
        frei_bereich = [k for k in bereich if self.frei(k)]
        behalten, kassieren = self.stichprobe(ziele, jedes)
        if len(frei_bereich) > 1:
            regeln.append({"regel": "stichprobe", "titel": REGELN["stichprobe"][0], "erklaerung": REGELN["stichprobe"][1],
                           "dateien": len(kassieren), "behalten": len(behalten),
                           "bytes": sum(self.dateien[k]["groesse"] for k in kassieren),
                           "schon": len(bereich) - len(frei_bereich)})
        je_endung = defaultdict(list)
        for k in bereich:
            je_endung[endung(k[1])].append(k)
        def ampeln(ks):
            # Archivfähigkeit je Endung: Zahl je Ampel; angezeigt wird die schlechteste (rot vor gelb vor grün)
            n = defaultdict(int)
            for k in ks:
                a = self.dateien[k]["ampel"]
                n[a if a in AMPELN else "ohne_ampel"] += 1
            schlechteste = min((a for a in AMPELN if n[a]), key=AMPEL_RANG.get, default="")
            return {"ampel": schlechteste, "ampeln": dict(n)}
        formate = sorted(({"endung": e, "format": max((self.dateien[k]["format"] for k in ks), key=len, default=""),
                           **zahlen(ks), "gesamt": len(ks), **ampeln(ks)} for e, ks in je_endung.items()),
                         key=lambda f: -f["gesamt"])
        angewandt = defaultdict(int)
        for k in bereich:
            r = self.regeln.get(k)
            if r and (r["begruendung"] or "").startswith("Regel:"):
                angewandt[(r["begruendung"], r["entscheidung"])] += 1
        return {"dateien": len(bereich), "grenze": grenze, "jedes": jedes,
                "regeln": [r for r in regeln if r["dateien"] or r["schon"]], "formate": formate,
                "angewandt": [{"begruendung": b, "entscheidung": e, "dateien": n} for (b, e), n in sorted(angewandt.items())]}

    def regel_anwenden(self, ziele, regel, entscheidung="kassieren", endungen=(), grenze=300, wer="", bestaetigt=False,
                       jedes=10):
        # Regeln kassieren oder stellen zurück; nur die Formatwahl darf auch übernehmen
        erlaubt = ("kassieren", "zurückstellen", "übernehmen") if regel == "formate" else ("kassieren", "zurückstellen")
        if entscheidung not in erlaubt:
            raise ValueError("Diese Regel kassiert oder stellt zurück" if regel != "formate"
                             else "Formate: übernehmen, kassieren oder zurückstellen")
        if regel == "stichprobe":
            if jedes < 2:
                raise ValueError("Stichprobe: mindestens jedes 2. Element")
            behalten, kassieren = self.stichprobe(ziele, jedes)
            begruendung = f"Regel: Stichprobe, jedes {jedes}. Element"
            # erst kassieren (mit Schutzregel); nur wenn das durchgeht, die Stichprobe übernehmen
            ergebnis = self.entscheiden(kassieren, "kassieren", begruendung=begruendung, wer=wer, bestaetigt=bestaetigt,
                                        fassungen=False)
            if "warnung" in ergebnis:
                return ergebnis
            self.entscheiden(behalten, "übernehmen", begruendung=begruendung, wer=wer, bestaetigt=True, fassungen=False)
            return {"ok": True, "ziele": len(behalten) + len(kassieren), "dateien": len(behalten) + len(kassieren)}
        behalten_von = {}
        treffer = [k for k in self.regel_treffer(self.bereich(ziele), regel, set(endungen), grenze, behalten_von)
                   if self.frei(k)]
        if not treffer:
            return {"ok": True, "ziele": 0, "dateien": 0}
        titel = ("Formate " + ", ".join(sorted(endungen)) if regel == "formate"
                 else REGELN[regel][0] + (f" (unter {grenze} px)" if regel == "klein" else ""))
        # Varianten: Fundort der kassierten an der behaltenen vermerken, wenn sie anderswo liegt
        hinweise = (self.ersatz_hinweise([(behalten_von[k], k, "variante") for k in treffer], verb="behalten")
                    if regel == "varianten" else {})
        return self.entscheiden(treffer, entscheidung, begruendung=f"Regel: {titel}", wer=wer, bestaetigt=bestaetigt,
                                fassungen=False, hinweise=hinweise)

    def regel_zuruecknehmen(self, ziele, begruendung):
        """Alle Einzelentscheidungen der Auswahl mit dieser Begründung aufheben (dann gilt wieder die übergeordnete)."""
        treffer = [k for k in self.bereich(ziele) if (self.regeln.get(k) or {}).get("begruendung") == begruendung]
        return self.entscheiden(treffer, None, bestaetigt=True, fassungen=False) if treffer else {"ok": True, "ziele": 0}

    def hinweis_setzen(self, platte, pfad, hinweis, wer=""):
        """Erschließungshinweis eines Elements setzen; leer entfernt ihn. Die Entscheidung bleibt unberührt."""
        pfad, hinweis = nfc(pfad), (hinweis or "").strip()
        if (platte, pfad) not in self.dateien and (platte, pfad) not in self.zaehler:
            raise ValueError(f"{platte} / {pfad} ist nicht im Inventar")
        zeit = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self.sperre, self.schreibend() as con:
            alt = con.execute("SELECT hinweis FROM erschliessungshinweis WHERE platte_id = ? AND pfad = ?",
                              (platte, pfad)).fetchone()
            alt = alt[0] if alt else ""
            if alt == hinweis:
                return {"ok": True, "geaendert": False}
            if hinweis:
                con.execute("INSERT OR REPLACE INTO erschliessungshinweis VALUES (?,?,?,?,?)",
                            (platte, pfad, hinweis, wer.strip(), zeit))
            else:
                con.execute("DELETE FROM erschliessungshinweis WHERE platte_id = ? AND pfad = ?", (platte, pfad))
            con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                        (zeit, "Bewertung", f"{platte}:{pfad}", "erschliessungshinweis",
                         f"Erschließungshinweis: {alt}" if alt else "",
                         f"Erschließungshinweis: {hinweis}" if hinweis else "Erschließungshinweis entfernt"))
        with self.sperre:
            self.stand = self.db_stand()                    # eigene Änderung: kein Neuladen nötig
        return {"ok": True, "geaendert": True}

    def hinweise(self, platte, pfad):
        """Erschließungshinweis des Elements und die der Ordner darüber bis zur Platte (nächster zuerst)."""
        wege = [pfad, *kette_nach_oben(pfad)] if pfad else [""]
        con = self.verbinden()
        try:
            gefunden = {z["pfad"]: dict(z) for z in con.execute(
                f"SELECT pfad, hinweis, wer, zeit FROM erschliessungshinweis WHERE platte_id = ? "
                f"AND pfad IN ({', '.join('?' * len(wege))})", (platte, *wege))}
        finally:
            con.close()
        return {"eigen": gefunden.get(pfad), "darueber": [gefunden[w] for w in wege[1:] if w in gefunden]}

    def entscheidung_angaben(self, platte, pfad):
        """Für den Editor: eigene und wirksame Entscheidung, Ausnahmen darunter, Verlauf."""
        ausnahmen = [{"platte": p, "pfad": pf, "art": r["art"], "entscheidung": r["entscheidung"],
                      "vorbehalt": bool(r["vorbehalt"]), "begruendung": r["begruendung"]}
                     for (p, pf), r in sorted(self.regeln.items())
                     if p == platte and pf != pfad and im_ordner(pf, pfad)]
        # Einzelentscheidungen aus Regeln zeigt der Editor gesammelt unter „Angewandte Regeln“
        aus_regeln = sum((a["begruendung"] or "").startswith("Regel:") for a in ausnahmen)
        ausnahmen = [a for a in ausnahmen if not (a["begruendung"] or "").startswith("Regel:")]
        objekt = f"{platte}:{pfad}"
        con = self.verbinden()
        try:
            verlauf = [dict(z) for z in con.execute(
                "SELECT zeit, objekt, alt, neu FROM protokoll WHERE abschnitt = 'Bewertung' "
                "AND (objekt = ? OR objekt LIKE ?) ORDER BY zeit DESC, rowid DESC LIMIT 12",
                (objekt, objekt + ("%" if pfad == "" else "/%")))]
        finally:
            con.close()
        return {"urteil": self.urteil(platte, pfad), "eigen": self.regeln.get((platte, pfad)),
                "ausnahmen": ausnahmen[:100], "ausnahmen_gesamt": len(ausnahmen), "aus_regeln": aus_regeln,
                "verlauf": verlauf, "hinweis": self.hinweise(platte, pfad)}

    def knoten_angaben(self, platte, pfad):
        """Aktuelle Anzeige einer Zeile (Baum, Suche, Galerie), z. B. nach einer Entscheidung."""
        if (platte, pfad) in self.dateien:
            return {"art": "datei", **self.datei_kurz(platte, pfad)}
        return {"art": "platte" if pfad == "" else "ordner", "platte": platte, "pfad": pfad,
                "zaehler": self.zaehler[(platte, pfad)], "urteil": self.urteil(platte, pfad)}

    # ---- Abfragen für die Oberfläche ----

    def platte(self, platte_id):
        return next((p for p in self.platten if p["platte_id"] == platte_id), None)

    def dateien_unter(self, platte, ordner):
        """Alle Dateien eines Ordners mit Unterordnern (relpfade)."""
        stapel, ergebnis = [ordner], []
        while stapel:
            o = stapel.pop()
            ergebnis.extend(self.dateien_in.get((platte, o), []))
            stapel.extend(self.unterordner.get((platte, o), ()))
        return ergebnis

    def stand_json(self):
        return {
            "platten": [{"id": p["platte_id"], "volume": p["volume_name"], "etikett": p["etikett_text"] or "",
                         "kopie_von": p["kopie_von"], "traeger": p["traeger"], "zaehler": self.zaehler[(p["platte_id"], "")],
                         "urteil": self.urteil(p["platte_id"], "")}
                        for p in self.platten],
            "thumbs_ok": self.vorschau_ordner.is_dir(), "db": str(self.db_pfad), "geladen_am": self.geladen_am,
            "einstellungen": self.einstellungen_json(), "ohne_leitdatei": self.ohne_leitdatei}

    def kinder(self, platte, ordner, systemdateien=False, offset=0, anzahl=500):
        ordner_liste = sorted(self.unterordner.get((platte, ordner), ()), key=lambda o: o.casefold())
        dateien = sorted(self.dateien_in.get((platte, ordner), []), key=lambda r: r.casefold())
        if not systemdateien:
            dateien = [r for r in dateien if not self.dateien[(platte, r)]["system"]]
        teil = dateien[offset:offset + anzahl]
        return {
            "ordner": [{"pfad": o, "name": o.rsplit("/", 1)[-1], "zaehler": self.zaehler[(platte, o)],
                        "urteil": self.urteil(platte, o)} for o in ordner_liste],
            "dateien": [self.datei_kurz(platte, r) for r in teil],
            "weitere": max(0, len(dateien) - offset - anzahl), "offset": offset + len(teil)}

    def datei_kurz(self, platte, relpfad):
        d = self.dateien[(platte, relpfad)]
        return {"platte": platte, "pfad": relpfad, "name": relpfad.rsplit("/", 1)[-1], "ampel": d["ampel"],
                "arten": d["arten"], "anton": d["anton"], "system": d["system"], "groesse": d["groesse"],
                "thumb": self.vorschauen.get(d["sha256"]), "personen": d["personen"], "gesichter": d["gesichter"], "bildtyp": d["bildtyp"],
                "urteil": self.urteil(platte, relpfad)}

    def suche(self, anfrage, systemdateien=False, grenze=200):
        """Wörter müssen alle im Pfad vorkommen; Wörter mit * oder ? sind Muster für den Namen (z. B. *.tif)."""
        woerter = nfc(anfrage).casefold().split()
        muster = [w for w in woerter if "*" in w or "?" in w]
        teile = [w for w in woerter if w not in muster]
        if not woerter:
            return {"gesamt": 0, "treffer": []}
        treffer, gesamt = [], 0
        for platte, pfad, art, pfad_cf, name_cf in self.suchliste:
            if art == "datei" and not systemdateien and self.dateien[(platte, pfad)]["system"]:
                continue
            if all(t in pfad_cf for t in teile) and all(fnmatch.fnmatchcase(name_cf, m) for m in muster):
                gesamt += 1
                if len(treffer) < grenze:
                    treffer.append({"art": "ordner", "platte": platte, "pfad": pfad, "name": pfad.rsplit("/", 1)[-1],
                                    "zaehler": self.zaehler[(platte, pfad)], "urteil": self.urteil(platte, pfad)}
                                   if art == "ordner"
                                   else {"art": "datei", **self.datei_kurz(platte, pfad)})
        return {"gesamt": gesamt, "treffer": treffer}

    def gleiche_ordner(self, platte, ordner):
        """Ordner, die (mit allen Unterordnern) gleich sind. G1 speichert nur die oberste Ebene;
        liegt der Ordner darunter, wird der gleiche Unterordner in den anderen Fundorten gesucht."""
        if ordner == "":
            return []
        treffer = {}
        for gid, p, o in self.ordnergruppen:
            if p == platte and (ordner == o or ordner.startswith(o + "/")):
                rest = ordner[len(o):]
                for gid2, p2, o2 in self.ordnergruppen:
                    ziel = (p2, o2 + rest)
                    if gid2 != gid or (p2, o2) == (p, o) or ziel not in self.zaehler:
                        continue
                    # derselbe Fundort kann direkt und über einen Überordner gleich sein: direkt geht vor
                    if ziel not in treffer or not rest:
                        treffer[ziel] = {"platte": p2, "pfad": o2 + rest, "seit": o2 if rest else None,
                                         "zaehler": self.zaehler[ziel]}
        return sorted(treffer.values(), key=lambda t: (t["platte"], t["pfad"]))

    def anderswo_ordner(self, platte, ordner, arten):
        """Wo liegen Dateien dieses Ordners sonst noch? Gezählt je Ordner der Kopie."""
        eigene = [r for r in self.dateien_unter(platte, ordner) if not self.dateien[(platte, r)]["system"]]
        je_ort = defaultdict(lambda: {"dateien": set(), "arten": set()})
        mit_kopie = set()
        for r in eigene:
            for art, gid, _ in self.gruppen_von.get((platte, r), []):
                if art not in arten:
                    continue
                for p2, r2 in self.mitglieder[gid]:
                    if p2 == platte and im_ordner(r2, ordner):
                        continue
                    ort = je_ort[(p2, elternordner(r2))]
                    ort["dateien"].add(r)
                    ort["arten"].add(art)
                    mit_kopie.add(r)
        orte = sorted(je_ort.items(), key=lambda kv: (-len(kv[1]["dateien"]), kv[0]))
        return {
            "dateien": len(eigene), "mit_kopie": len(mit_kopie), "orte_gesamt": len(orte),
            "orte": [{"platte": p2, "pfad": o2, "anzahl": len(w["dateien"]),
                      "arten": sorted(w["arten"], key=ARTEN.index),
                      "dort": self.zaehler[(p2, o2)]["dateien"]}
                     for (p2, o2), w in orte[:200]]}

    def anderswo_datei(self, platte, relpfad, arten):
        ergebnis = []
        for art, gid, _ in self.gruppen_von.get((platte, relpfad), []):
            if art not in arten:
                continue
            for p2, r2 in self.mitglieder[gid]:
                if (p2, r2) == (platte, relpfad):
                    continue
                kurz = self.datei_kurz(p2, r2)
                kurz["art"] = art
                kurz["leit"] = any(g == gid and l for _, g, l in self.gruppen_von[(p2, r2)])
                ergebnis.append(kurz)
        return ergebnis

    def galerie(self, platte, ordner, offset=0, anzahl=48, nur_personen=False):
        """Vorschaubilder eines Ordners (mit Unterordnern), je Inhalt eines. nur_personen: Anzeige-Option der Galerie,
        nur Fotos mit erkannten Personen oder Porträts (F5); mit_personen zählt sie immer, damit die Option nur erscheint,
        wo es sie gibt."""
        gesehen, bilder, mit_personen = set(), [], 0
        for r in sorted(self.dateien_unter(platte, ordner), key=lambda r: r.casefold()):
            d = self.dateien[(platte, r)]
            if d["system"] or d["sha256"] not in self.vorschauen or d["sha256"] in gesehen:
                continue
            gesehen.add(d["sha256"])
            mit_personen += bool(d["bildtyp"])
            if d["bildtyp"] or not nur_personen:
                bilder.append(r)
        return {"gesamt": len(bilder), "offset": offset + len(bilder[offset:offset + anzahl]), "mit_personen": mit_personen,
                "bilder": [self.datei_kurz(platte, r) for r in bilder[offset:offset + anzahl]]}

    def ordner_angaben(self, platte, ordner):
        """Kennzahlen und Metadaten-Übersicht eines Ordners (mit Unterordnern)."""
        bereich = "platte_id = ? AND relpfad >= ? AND relpfad < ?" if ordner else "platte_id = ?"
        werte = (platte, ordner + "/", ordner + "0") if ordner else (platte,)   # "0" folgt auf "/"
        con = self.verbinden()
        try:
            zeitraum = con.execute(f"SELECT MIN(datum), MAX(datum) FROM metadaten WHERE {bereich} "
                                   "AND datum IS NOT NULL AND datum != ''", werte).fetchone()
            formate = con.execute(f"SELECT COALESCE(NULLIF(format, ''), 'unbekannt') AS f, COUNT(*) AS n FROM datei "
                                  f"WHERE {bereich} GROUP BY f ORDER BY n DESC LIMIT 8", werte).fetchall()
            kameras = con.execute(f"SELECT kamera, COUNT(*) AS n FROM metadaten WHERE {bereich} "
                                  "AND kamera IS NOT NULL AND kamera != '' GROUP BY kamera ORDER BY n DESC LIMIT 5",
                                  werte).fetchall()
        finally:
            con.close()
        p = self.platte(platte) or {}
        return {
            "platte": platte, "pfad": ordner, "name": ordner.rsplit("/", 1)[-1] or f"{platte} · {p.get('volume_name')}",
            "etikett": p.get("etikett_text") or "", "zaehler": self.zaehler[(platte, ordner)],
            "unterordner": len(self.unterordner.get((platte, ordner), ())),
            "zeitraum": [zeitraum[0], zeitraum[1]] if zeitraum and zeitraum[0] else None,
            "formate": [[f["f"], f["n"]] for f in formate], "kameras": [[k["kamera"], k["n"]] for k in kameras],
            "gleiche_ordner": self.gleiche_ordner(platte, ordner)}

    def datei_angaben(self, platte, relpfad):
        con = self.verbinden()
        try:
            teile = {}
            for tabelle in ("schnellscan", "datei", "metadaten", "archiv", "anton_abgleich"):
                z = con.execute(f"SELECT * FROM {tabelle} WHERE platte_id = ? AND relpfad = ?",
                                (platte, relpfad)).fetchone()
                teile[tabelle] = {k: z[k] for k in z.keys() if z[k] not in (None, "") and k not in
                                  ("platte_id", "relpfad", "lauf_id")} if z else {}
        finally:
            con.close()
        kurz = self.datei_kurz(platte, relpfad)
        p = self.platte(platte) or {}
        return {**kurz, **teile, "etikett": p.get("etikett_text") or ""}


class Erfassung:
    """Startet und beobachtet die Hintergrundläufe (erfassung/lauf.py). Liest nur lauf, lauf_schritt, platte, scanlauf."""

    SCHRITTE = {"schnellscan": "C", "pruefsummen": "D1", "siegfried": "D2", "virenscan": "D3", "metadaten": "E",
                "vorschau": "F"}
    CHIPS = ["C", "D1", "D2", "D3", "E", "E4", "F", "F5", "G", "G5", "H"]   # Stand je Platte, Reihenfolge der Schritte
    CHIP_NAMEN = {"C": "Verzeichnis", "D1": "Prüfsummen", "D2": "Formate", "D3": "Virenscan", "E": "Metadaten",
                  "E4": "Texte",
                  "F": "Vorschaubilder", "F5": "Personen", "G": "Duplikate", "G5": "Anton-Abgleich",
                  "H": "Archivfähigkeit"}   # wie erfassung.js
    MIT_PLATTE = {"C", "D1", "D2", "D3", "E", "E4", "F"}            # lesen die Platte (wie erfassung/lauf.py)
    # Endungen, deren Text E4 liest (wie TEXT_ENDUNGEN in erfassung/texte.py)
    TEXT_ENDUNGEN = {".pdf", ".doc", ".dot", ".docx", ".docm", ".dotx", ".ppt", ".pps", ".pot", ".pptx", ".ppsx",
                     ".pptm", ".odt", ".odp", ".rtf", ".txt", ".htm", ".html"}
    FOLGESCHRITTE = {"G": ["H"]}       # Pflichtfolgen einer Auswahl, wie erfassung/lauf.py (G löscht die Leitdateien aus H)

    # Was je Platte noch fehlt, aus den Daten bestimmt (wie die Schritte selbst auswählen, was offen ist)
    SYSTEM = ("(d.relpfad LIKE '%.DS_Store' OR d.relpfad LIKE '%Thumbs.db' OR d.relpfad LIKE '%desktop.ini' "
              "OR d.relpfad LIKE '%.localized' OR d.relpfad LIKE '._%' OR d.relpfad LIKE '%/._%')")
    OFFEN = f"""
        SELECT d.platte_id, COUNT(*) AS dateien,
               SUM(d.sha256 IS NULL AND d.hash_fehler IS NULL) AS D1,
               SUM(d.sha256 IS NOT NULL AND d.sf_am IS NULL AND instr(d.relpfad, char(10)) = 0
                   AND instr(d.relpfad, char(13)) = 0) AS D2,
               SUM(d.sha256 IS NOT NULL AND d.groesse > 0 AND (v.sha256 IS NULL OR v.befund = 'Fehler')) AS D3,
               SUM(d.groesse > 0 AND m.relpfad IS NULL AND NOT {SYSTEM} AND COALESCE(v.befund, '') != 'Fund'
                   AND instr(d.relpfad, char(10)) = 0) AS E
        FROM datei d LEFT JOIN virenscan v ON v.sha256 = d.sha256
        LEFT JOIN metadaten m ON m.platte_id = d.platte_id AND m.relpfad = d.relpfad
        GROUP BY d.platte_id"""

    def __init__(self, bestand, info):
        self.bestand = bestand
        self.info = info                                        # Antwort von „erfassung.lauf projekt“
        self.projekt = Path(info["ordner"])
        self.offen_stand, self.offen_cache = None, {}
        self.gleich_stand, self.gleich_cache = None, {}
        self.gesucht = time.monotonic()
        self.quellen, self.quellen_zeit, self.quellen_sperre = {}, 0.0, threading.Lock()

    def aufrufen(self, befehl, *weitere, eingabe=None, timeout=180):
        return lauf_aufrufen(befehl, *projekt_argumente(self.projekt), *weitere, eingabe=eingabe, timeout=timeout)

    def arbeitsplatte(self):
        """Mountpunkt der Arbeitsplatte (leer: Vorschaubilder im Projekt) und ob sie angeschlossen ist. Fehlt sie, wird
        höchstens alle 30 s im Hintergrund neu gesucht (über die UUID; sie kann unter anderem Namen wieder auftauchen)."""
        pfad = self.info["arbeitsplatte"]
        if not pfad or Path(pfad).is_dir():
            return pfad, True
        if time.monotonic() - self.gesucht > 30:
            self.gesucht = time.monotonic()

            def suchen():
                try:
                    self.info = self.aufrufen("projekt")
                    self.bestand.vorschau_ordner = Path(self.info["vorschauen"])
                except (RuntimeError, ValueError, subprocess.TimeoutExpired):
                    pass
            threading.Thread(target=suchen, daemon=True).start()
        return pfad, False

    def einstellungen_aendern(self, daten):
        """Projekteinstellungen ändern (Zahnrad des Projekts vorn in der Kopfleiste und Zahnrad an Registrierung/Analyse); erfassung/basis.py prüft und protokolliert."""
        antwort = self.aufrufen("einstellungen", "--daten", json.dumps(daten, ensure_ascii=False))
        geaendert = antwort.pop("geaendert")
        self.info = antwort
        self.bestand.vorschau_ordner = Path(antwort["vorschauen"])
        if "name" in geaendert:
            zuletzt_merken(self.projekt, antwort["name"])
        return {"ok": True, "geaendert": geaendert}

    def quellpfad_pruefen(self, mountpunkt, platte_id=None, art=None):
        """Wurzel einer Quelle: ein angeschlossener Datenträger, eine registrierte Ordner-Quelle oder
        (art "ordner", neue Registrierung) ein Ordner, den erfassung/platte.py als Quelle zulässt (05.11.2026)."""
        if system.ist_geraet(mountpunkt):                 # Mac-Platte unter Windows (Entscheidung 09.11.2026)
            return system.geraet_name(mountpunkt)
        mountpunkt = Path(mountpunkt)
        arbeitsplatte = self.info["arbeitsplatte"]
        if (system.ist_datentraeger(mountpunkt, VOLUMES) and not (arbeitsplatte and mountpunkt == Path(arbeitsplatte))
                and mountpunkt.is_dir()):
            return mountpunkt
        if art in ("ordner", "abbild"):
            return Path(self.aufrufen("quellordner", "--daten", json.dumps(
                {"aktion": "pruefen" if art == "ordner" else "abbild_pruefen", "pfad": str(mountpunkt),
                 "platte_id": platte_id}, ensure_ascii=False))["pfad"])
        con = self.bestand.verbinden()
        try:
            ordner = {z[0] for z in con.execute("SELECT quellordner FROM platte WHERE art IN ('ordner', 'abbild')")}
        finally:
            con.close()
        if nfc(str(mountpunkt)) in ordner and mountpunkt.exists():
            return mountpunkt
        raise ValueError(f"{mountpunkt} ist kein angeschlossener Quelldatenträger und keine registrierte Ordner-Quelle")

    def macgeraet_pruefen(self, daten):
        """Mac-Platte an einem Windows-Rechner lesen (fragt einmal nach Administratorrechten): Gerät und Volumes."""
        return self.aufrufen("quellordner", "--daten", json.dumps(
            {"aktion": "macgeraet_pruefen", "geraet": daten.get("geraet", "")}, ensure_ascii=False), timeout=300)

    def abbild_pruefen(self, daten):
        """Abbild eines Mac-Datenträgers (Entscheidung 09.11.2026): taugt die Datei, welche Volumes trägt sie?"""
        return self.aufrufen("quellordner", "--daten", json.dumps(
            {"aktion": "abbild_pruefen", "pfad": daten.get("pfad", "")}, ensure_ascii=False))

    def passwort_pruefen(self, daten):
        """Passwort eines verschlüsselten Volumes vor dem Lauf prüfen (Feedback 14.11.2026): öffnet es einmal zur Probe;
        das Passwort geht nur über stdin an die Abfrage und wird nirgends gespeichert. Antwort {ok, meldung}."""
        passwort = daten.get("passwort") or ""
        if not passwort:
            raise ValueError("Bitte das Passwort eingeben.")
        platte_id = kennung_pruefen(daten.get("platte_id"))
        mountpunkt = daten.get("mountpunkt")
        if not mountpunkt:                                 # registrierte Platte (Fortsetzen, Packen): dort, wo sie hängt
            q = self.angeschlossen().get(platte_id)
            if not q:
                raise ValueError(f"{platte_id} ist nicht angeschlossen.")
            mountpunkt = q["mountpunkt"]
        wurzel = self.quellpfad_pruefen(mountpunkt, platte_id, daten.get("art"))
        return self.aufrufen("quellordner", "--daten", json.dumps(
            {"aktion": "passwort_pruefen", "wurzel": str(wurzel), "platte_id": platte_id,
             "volume_uuid": daten.get("volume_uuid")}, ensure_ascii=False), eingabe=passwort + "\n", timeout=300)

    def quellordner(self, daten):
        """Ordner als Quelle (Entscheidung 05.11.2026): prüfen (vor dem Registrieren) oder verlegen (neuer Ort)."""
        aktion = "verlegen" if daten.get("platte_id") and daten.get("verlegen") else "pruefen"
        antwort = self.aufrufen("quellordner", "--daten", json.dumps(
            {"aktion": aktion, "pfad": daten.get("pfad", ""), "platte_id": daten.get("platte_id")}, ensure_ascii=False))
        if aktion == "verlegen":
            self.quellen_zeit = 0                          # Liste der angeschlossenen Quellen neu holen
        return antwort

    def unterordner(self, mountpunkt, pfad, volume_uuid=None):
        """Ordner einer angeschlossenen Quelle für die Wahl des Umfangs (nur lesen); bei einem Abbild mit mehreren
        Volumes im gewählten (13.11.2026)."""
        wurzel = self.quellpfad_pruefen(mountpunkt)
        return self.aufrufen("quellordner", "--daten", json.dumps(
            {"aktion": "unterordner", "wurzel": str(wurzel), "pfad": pfad, "volume_uuid": volume_uuid}, ensure_ascii=False))

    # ---- Original im Dateimanager zeigen (Inspektor der Bewertung) ----

    def angeschlossen(self):
        """Kennung → Mountpunkt und Schreibschutz der angeschlossenen registrierten Platten (über die Volume-UUID wie
        in der Analyse). Die Abfrage dauert etwa eine Sekunde und wird höchstens alle 10 s wiederholt, sofort, wenn
        eine bekannte Platte verschwunden ist."""
        with self.quellen_sperre:
            if time.monotonic() - self.quellen_zeit > 10 or any(not Path(q["mountpunkt"]).is_dir()
                                                                 for q in self.quellen.values()):
                quellen = {}
                antwort = self.aufrufen("datentraeger")
                for d in antwort["angeschlossen"]:
                    for kennung in d.get("kennungen", []):
                        quellen[kennung] = {"mountpunkt": d["mountpunkt"], "schreibgeschuetzt": d["schreibgeschuetzt"]}
                for o in antwort.get("ordner", []):        # Ordner und Abbilder als Quelle: nur lesen
                    if o["da"] and o.get("art") == "macplatte":   # Mac-Platte unter Windows: nur lesend über die Leseschicht
                        quellen[o["platte_id"]] = {"mountpunkt": o["pfad"], "schreibgeschuetzt": True, "macplatte": True}
                    elif o["da"]:
                        quellen[o["platte_id"]] = {"mountpunkt": o["pfad"], "schreibgeschuetzt": False, "ordner": True,
                                                   "abbild": o.get("art") == "abbild"}
                self.quellen, self.quellen_zeit = quellen, time.monotonic()
            return self.quellen

    def ohne_schreibschutz(self, platte_id):
        """Zeitpunkt der Zustimmung zum Lesen ohne Schreibschutz für diesen Datenträger oder None."""
        con = self.bestand.verbinden()
        try:
            z = con.execute("SELECT zugestimmt_am FROM schreibschutz_verzicht WHERE platte_id = ?", (platte_id,)).fetchone()
        finally:
            con.close()
        return z[0] if z else None

    def ohne_schreibschutz_zustimmen(self, platte_id):
        """Zustimmung zum Lesen ohne Schreibschutz (Rückfrage in Balduin, Entscheidung 13.11.2026): einmal je
        Datenträger, protokolliert; gilt für Analyse, Packen und „Datei zeigen“."""
        platte_id = kennung_pruefen(platte_id)
        zeit = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self.bestand.schreibend() as con:
            neu = con.execute("INSERT OR IGNORE INTO schreibschutz_verzicht (platte_id, zugestimmt_am) VALUES (?, ?)",
                              (platte_id, zeit)).rowcount
            if neu:
                con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                            (zeit, "B", platte_id, "ohne Schreibschutz lesen", "", "zugestimmt"))
        return {"ok": True, "platte_id": platte_id, "zugestimmt_am": self.ohne_schreibschutz(platte_id)}

    def quelle(self, platte, relpfad):
        """Lässt sich Datei, Ordner oder Platte im Dateimanager zeigen? {"pfad"} oder {"grund"} für den Hinweis."""
        b = self.bestand
        datei = (platte, relpfad) in b.dateien
        if not datei and (platte, relpfad) not in b.zaehler:
            raise ValueError("nicht im Inventar")
        q = self.angeschlossen().get(platte)
        if q is None:
            return {"grund": f"Datenträger {platte} ist nicht angeschlossen."}
        if q.get("macplatte"):       # ohne Laufwerksbuchstaben gibt es keinen Pfad im Dateimanager (09.11.2026)
            return {"grund": f"{platte} ist ein Mac-Datenträger ohne Laufwerksbuchstaben; Dateien darauf lassen sich nicht "
                             "im Dateimanager zeigen. Die Vorschau in Balduin zeigt sie."}
        if q.get("abbild"):          # Dateien in einem Abbild haben keinen Pfad im Dateimanager (09.11.2026)
            return {"grund": f"{platte} ist ein Abbild; Dateien darin lassen sich nicht im Dateimanager zeigen. Die "
                             f"Vorschau in Balduin zeigt sie. Abbild: {q['mountpunkt']}"}
        if q.get("ordner"):          # harte Regel 1: der Finder legte dort .DS_Store an (Entscheidung 05.11.2026)
            return {"grund": f"{platte} ist ein Ordner als Quelle und lässt sich nicht schreibgeschützt öffnen; der Dateimanager "
                             f"würde dort eigene Dateien anlegen. Balduin zeigt ihn deshalb nicht im {system.systemwoerter()['dateimanager']}. "
                             f"Er liegt unter {Path(q['mountpunkt']) / relpfad}"}
        if beschreibbar_gesperrt(q, self.ohne_schreibschutz(platte), system.standard_volumes(VOLUMES)):
            return {"grund": f"Datenträger {platte} ist beschreibbar eingehängt (der Dateimanager würde dort eigene Dateien anlegen). "
                             "Zuerst unter Registrierung/Analyse schreibgeschützt einhängen oder dem Lesen ohne "
                             "Schreibschutz zustimmen."}
        wurzel = Path(q["mountpunkt"])
        pfad = wurzel / relpfad
        if not os.path.lexists(pfad) and os.path.lexists(wurzel / unicodedata.normalize("NFD", relpfad)):
            pfad = wurzel / unicodedata.normalize("NFD", relpfad)          # wie quellpfad() in erfassung/basis.py
        if not os.path.lexists(pfad):
            archiv = archivdatei_darueber(wurzel, relpfad)
            if archiv is None:
                return {"grund": "Unter diesem Pfad liegt auf dem Datenträger nichts mehr."}
            pfad = archiv                    # der Dateimanager schaut nicht in Archive: die Archivdatei zeigen
        if datei:
            con = b.verbinden()
            try:
                fund = con.execute("SELECT v.meldung FROM datei d JOIN virenscan v ON v.sha256 = d.sha256 WHERE "
                                   "d.platte_id = ? AND d.relpfad = ? AND v.befund = 'Fund'", (platte, relpfad)).fetchone()
            finally:
                con.close()
            if fund:     # der Dateimanager liest den Inhalt für seine Vorschau
                return {"grund": f"Der Virenscan hat hier etwas gefunden ({fund[0]}). Die Datei wird nicht gezeigt."}
        return {"pfad": str(pfad)}

    def original_zeigen(self, platte, relpfad):
        """Markiert das Original im Dateimanager (macOS Finder, Windows Explorer); geöffnet oder gestartet wird nichts,
        der Server liest es nicht."""
        q = self.quelle(platte, relpfad)
        if "grund" in q:
            raise ValueError(q["grund"])
        system.im_dateimanager_zeigen(q["pfad"])
        return {"ok": True}

    @staticmethod
    def lebt(pid):
        """Läuft der Prozess noch? (system.lebt; unter Windows ohne os.kill, das dort beendet)"""
        return system.lebt(pid)

    def lauf_angaben(self, con, z):
        if z is None:
            return None
        lauf = dict(z)
        lauf["auftrag"] = json.loads(lauf["auftrag"] or "{}")
        lauf["auftrag"].pop("foto", None)
        lauf["name"] = LAUF_NAMEN.get(lauf["art"]) or lauf["platte_id"]
        lauf["aktiv"] = lauf["status"] in ("wartet", "läuft") and (lauf["status"] == "wartet" or self.lebt(lauf["pid"]))
        if lauf["status"] == "läuft" and not lauf["aktiv"]:
            lauf["status"], lauf["meldung"] = "abgebrochen", "Der Lauf wurde beendet (z. B. Rechner neu gestartet)."
        lauf["schritte"] = [dict(s) for s in con.execute(
            "SELECT * FROM lauf_schritt WHERE lauf_id = ? ORDER BY rowid", (lauf["lauf_id"],))]
        lauf["log_ende"] = ""
        if lauf["log"]:
            try:
                with open(self.projekt / lauf["log"], "rb") as f:
                    f.seek(max(0, os.path.getsize(self.projekt / lauf["log"]) - 6000))
                    lauf["log_ende"] = "\n".join(f.read().decode("utf-8", "replace").splitlines()[-25:])
            except OSError:
                pass
        return lauf

    LAEUFE_ZULETZT = 6                                   # so viele beendete Läufe zeigt die Übersicht „Läufe“

    def laeufe_kurz(self, con):
        """Übersicht für die dritte Spalte: laufender Lauf und die zuletzt beendeten, je mit aktuellem bzw. letztem
        Schritt; ein gescheiterter verschwindet so nicht, wenn danach der nächste eingereihte beginnt."""
        liste = []
        for z in con.execute("SELECT lauf_id, art, platte_id, status, pid, start, ende, meldung, abbrechen FROM lauf "
                             "WHERE status NOT IN ('eingereiht', 'entfernt') ORDER BY lauf_id DESC LIMIT ?",
                             (self.LAEUFE_ZULETZT + 1,)):
            l = dict(z)
            l["name"] = LAUF_NAMEN.get(l["art"]) or l["platte_id"]
            l["aktiv"] = l["status"] == "wartet" or (l["status"] == "läuft" and self.lebt(l["pid"]))
            if l["status"] == "läuft" and not l["aktiv"]:
                l["status"] = "abgebrochen"
            s = con.execute("SELECT schritt, titel, status, anteil, text FROM lauf_schritt WHERE lauf_id = ? AND status != 'wartet' "
                            "AND status != 'übersprungen' ORDER BY rowid DESC LIMIT 1", (l["lauf_id"],)).fetchone()
            l["schritt"] = dict(s) if s else None
            l.pop("pid")
            liste.append(l)
        aktiv = [l for l in liste if l["aktiv"]]
        return aktiv + [l for l in liste if not l["aktiv"]][:self.LAEUFE_ZULETZT]

    def stand(self, platte_id=None, lauf_id=None):
        """Registrierte Platten mit erledigten Schritten und ein Lauf mit Einzelheiten: der verlangte (lauf_id), sonst
        der laufende (der gewählten Platte, sonst nicht der Anton-Abruf), sonst der letzte der gewählten Platte; dazu die
        Übersicht der letzten Läufe und die eingereihten in ihrer Reihenfolge."""
        self.weiter()
        con = self.bestand.verbinden()
        try:
            platten = [dict(z) for z in con.execute("""
                SELECT p.platte_id, p.volume_name, p.etikett_text, p.notiz, p.kopie_von, p.etikett_foto,
                       p.dateisystem, p.kapazitaet_bytes, COALESCE(p.volume_uuid, '') != '' AS uuid, p.smart_status,
                       p.registriert_am, p.modell, p.anschluss, p.deaktiviert_am, p.art, p.quellordner, p.umfang, p.traeger,
                       COALESCE(p.verschluesselt, 0) AS verschluesselt,
                       (SELECT COUNT(*) FROM schnellscan s WHERE s.platte_id = p.platte_id) AS dateien,
                       (SELECT SUM(groesse) FROM schnellscan s WHERE s.platte_id = p.platte_id) AS bytes,
                       (SELECT COUNT(*) FROM datei d WHERE d.platte_id = p.platte_id AND d.sha256 IS NULL) AS ohne_pruefsumme,
                       (SELECT v.zugestimmt_am FROM schreibschutz_verzicht v WHERE v.platte_id = p.platte_id) AS ohne_schreibschutz
                FROM platte p ORDER BY p.platte_id""")]
            offen = self.offen_je_platte(con)
            gleich = self.gleich_je_platte(con)
            viren_aus = not self.info["einstellungen"]["virenscan"]
            personen_aus = not self.info["einstellungen"].get("personen")
            ausstehend = self.ausstehende_schritte(con)
            for p in platten:
                p["traeger"] = system_modul().traeger_der_platte(p)      # Icon der Datenträgerart (05.11.2026)
                p["offen"] = dict(offen.get(p["platte_id"], {}))
                if viren_aus:                                # im Projekt ausgeschaltet: zählt als erledigt
                    p["offen"].update({"D3": 0, "D3_aus": True})
                if personen_aus:                             # F5 ebenso
                    p["offen"].update({"F5": 0, "F5_aus": True})
                p["erledigt"] = erledigte_schritte(p["offen"], self.CHIPS, ausstehend.get(p["platte_id"], set()))
                # nur mit vollständigen Prüfsummen; sonst wäre der Anteil zu klein
                p["gleich"] = gleich.get(p["platte_id"], {}) if p["offen"].get("D1") == 0 else {}
            lauf = self.lauf_angaben(con, con.execute(
                "SELECT * FROM lauf WHERE lauf_id = ? AND status NOT IN ('eingereiht', 'entfernt')", (lauf_id,)).fetchone()
                if lauf_id else con.execute(
                "SELECT * FROM lauf WHERE status IN ('wartet', 'läuft') "      # zwei Spuren: die der Platte, sonst nicht Anton
                "ORDER BY COALESCE(platte_id = ?, 0) DESC, art = 'anton', lauf_id DESC LIMIT 1", (platte_id,)).fetchone())
            if not lauf_id and not (lauf and lauf["aktiv"]):
                z = con.execute("SELECT * FROM lauf WHERE platte_id = ? AND status NOT IN ('eingereiht', 'entfernt') "
                                "ORDER BY lauf_id DESC LIMIT 1", (platte_id,)).fetchone() if platte_id else None
                lauf = self.lauf_angaben(con, z)
            registriert = {p["platte_id"] for p in platten}
            warteschlange = []
            for z in con.execute("SELECT lauf_id, art, platte_id, auftrag, start FROM lauf WHERE status = 'eingereiht' "
                                 "ORDER BY lauf_id"):
                a = json.loads(z["auftrag"] or "{}")
                anton = z["art"] == "anton"
                warteschlange.append({"lauf_id": z["lauf_id"], "platte_id": z["platte_id"], "eingereiht": z["start"],
                                      "art": z["art"], "name": LAUF_NAMEN.get(z["art"]) or z["platte_id"],
                                      "modus": "holen und abgleichen" if anton else "Vorschläge rechnen"
                                      if z["art"] == "vorlauf" else ("Pakete " + (z["platte_id"] or "ohne Datenträger"))
                                      if z["art"] == "export" else a.get("modus")
                                      or ("neu registrieren" if z["platte_id"] not in registriert else "fortsetzen"),
                                      "schritte": a.get("schritte"), "mountpunkt": a.get("mountpunkt")})
            aktive = [p for p in platten if not p["deaktiviert_am"]]     # herausgenommene zählen nicht mit
            schritte = len(self.CHIPS) * len(aktive)
            erledigt = sum(len(p["erledigt"]) for p in aktive)
            vollstaendig = sum(len(p["erledigt"]) == len(self.CHIPS) for p in aktive)
            modul = {"anteil": erledigt / schritte if schritte else 0, "fertig": bool(aktive) and erledigt == schritte,
                     "text": f"{vollstaendig} von {len(aktive)} Datenträgern vollständig analysiert"}
            arbeitsplatte, da = self.arbeitsplatte()
            # Platzbedarf der Vorschaubilder für die Rückfrage vor einer Analyse (Entscheidung 12.11.2026):
            # je Platte höchstens eins je Datei, solange F offen ist; für eine neue Platte nur der Richtwert
            platz = {"frei": shutil.disk_usage(self.info["ordner"]).free,
                     "reserve": float(self.info["einstellungen"]["speicher"]["min_frei_gb"]) * 1e9,
                     "arbeitsplatte": bool(arbeitsplatte),
                     "arbeitsplatte_frei": shutil.disk_usage(arbeitsplatte).free if arbeitsplatte and da else None}
            for p in platten:
                p["platz"] = platz_schaetzen(0 if p["offen"].get("F") == 0 else p["dateien"] or None, **platz)
            return {"platten": platten, "lauf": lauf, "laeufe": self.laeufe_kurz(con), "warteschlange": warteschlange,
                    "modul": modul, "platz_neu": platz_schaetzen(None, **platz),
                    "arbeitsplatte": arbeitsplatte, "arbeitsplatte_da": da, "virenscan": self.info["einstellungen"]["virenscan"],
                    "anton": self.anton_stand(con)}
        finally:
            con.close()

    ANTON_ALT_TAGE = 30                                  # ab so vielen Tagen erinnert das Tool an einen neuen Abruf

    def anton_stand(self, con):
        """Geladener Bestand aus Anton (Datum, Alter, Zugang …) und der letzte Lauf „Bestand aus Anton holen“."""
        z = con.execute("SELECT stand, quelle, dateien, nur_platten, zugang, eingelesen_am FROM anton_stand "
                        "WHERE aktuell = 1").fetchone()
        stand = dict(z) if z else None
        if stand:
            datum = stand["stand"].split("/")[0]
            stand["datum"] = datum
            try:
                stand["alter_tage"] = (date.today() - date.fromisoformat(datum)).days
            except ValueError:
                stand["alter_tage"] = None
        l = con.execute("SELECT lauf_id, status, meldung, start, ende FROM lauf WHERE art = 'anton' "
                        "AND status NOT IN ('entfernt') ORDER BY lauf_id DESC LIMIT 1").fetchone()
        return {"stand": stand, "lauf": dict(l) if l else None, "url": self.info["einstellungen"]["anton"]["url"],
                "token": self.info.get("anton_token", ""), "alt_ab": self.ANTON_ALT_TAGE}

    def ausstehende_schritte(self, con):
        """Je Platte die Schritte, die ihr laufender Analyselauf noch ausführen wird (wartet oder läuft): gewählt
        (samt Folgeschritten) und, ohne angeschlossene Platte, nur die Schritte ohne Platte."""
        ausstehend = defaultdict(set)
        for z in con.execute("""SELECT l.platte_id, l.auftrag, s.schritt FROM lauf l JOIN lauf_schritt s USING (lauf_id)
                                WHERE l.art = 'erfassen' AND l.status IN ('wartet', 'läuft')
                                  AND s.status IN ('wartet', 'läuft')"""):
            try:
                auftrag = json.loads(z["auftrag"] or "{}")
            except ValueError:
                auftrag = {}
            gewaehlt = set(auftrag.get("schritte") or [])
            for k in list(gewaehlt):
                gewaehlt.update(self.FOLGESCHRITTE.get(k, []))
            if gewaehlt and z["schritt"] not in gewaehlt:
                continue
            if not auftrag.get("mountpunkt") and z["schritt"] in self.MIT_PLATTE:
                continue
            ausstehend[z["platte_id"]].add(z["schritt"])
        return ausstehend

    def offen_je_platte(self, con):
        """Je Platte und Schritt die Anzahl offener Dateien (0 = erledigt). C: vollständiger Schnellscan;
        D1–E aus den Daten; F aus den Läufen (welche Dateien ein Vorschaubild bekommen, entscheidet erst F selbst).
        Wird nur neu berechnet, wenn sich die Datenbank geändert hat (rund 0,3 s bei 85.000 Dateien)."""
        stand = self.bestand.db_stand()
        if stand == self.offen_stand:
            return self.offen_cache
        offen = defaultdict(dict)
        schnell = dict(con.execute("SELECT platte_id, COUNT(*) FROM schnellscan GROUP BY platte_id").fetchall())
        fertig_c = {z[0] for z in con.execute("SELECT platte_id FROM scanlauf WHERE art = 'schnellscan' AND ende IS NOT NULL")}
        try:                         # ältere Datenbank ohne Spalte archiv oder Tabelle archivdatei: nichts geprüft
            ungeprueft = dict(con.execute(ARCHIVE_UNGEPRUEFT_SQL).fetchall())
        except sqlite3.OperationalError:
            ungeprueft = {}
        for p, n in schnell.items():
            offen[p]["C"] = ungeprueft.get(p, 0) if p in fertig_c else n
            if p in fertig_c and ungeprueft.get(p):      # nur Archivdateien fehlen (Text am Chip, erledigte_schritte)
                offen[p]["C_archive"] = ungeprueft[p]
        for z in con.execute(self.OFFEN):
            offen[z["platte_id"]].update({"D1": z["D1"] + max(0, schnell.get(z["platte_id"], 0) - z["dateien"]),
                                          "D2": z["D2"], "D3": z["D3"], "E": z["E"]})
        for p, n in schnell.items():                     # Dateiliste noch nicht übernommen
            offen[p].setdefault("D1", n)
        # E: Datei ohne Zeile in metadaten oder ihr Inhalt (SHA-256 + Endung) ohne vollständige ExifTool-Ausgabe;
        # E4: Dokumente ohne Text (wie erfassung/metadaten.py und erfassung/texte.py auswählen)
        voll = {tuple(z) for z in con.execute("SELECT sha256, endung FROM exif_voll")}
        texte = {tuple(z) for z in con.execute("SELECT sha256, endung FROM volltext")}
        gelesen = {tuple(z) for z in con.execute("SELECT platte_id, relpfad FROM metadaten")}
        fund = {z[0] for z in con.execute("SELECT sha256 FROM virenscan WHERE befund = 'Fund'")}
        e, e4 = defaultdict(int), defaultdict(int)
        for p, r, s in con.execute("SELECT platte_id, relpfad, sha256 FROM datei WHERE groesse > 0"):
            name = r.rsplit("/", 1)[-1]
            if (s and s in fund) or "\n" in r or name.startswith("._") or name in (".DS_Store", "Thumbs.db",
                                                                                    "desktop.ini", ".localized"):
                continue
            endung = os.path.splitext(r)[1].lower()
            e[p] += (p, r) not in gelesen or (s is not None and (s, endung) not in voll)
            e4[p] += s is not None and endung in self.TEXT_ENDUNGEN and (s, endung) not in texte
        for p in schnell:
            if "E" in offen[p]:
                offen[p]["E"] = e.get(p, 0)
            offen[p]["E4"] = e4.get(p, 0) if offen[p].get("D1") == 0 else None
        # F: gelaufen (scanlauf); nach neuen Prüfsummen (D1 offen) gilt F wieder als offen
        f_fertig = {z[0] for z in con.execute("SELECT platte_id FROM scanlauf WHERE art = 'vorschau' AND ende IS NOT NULL")}
        f_fertig |= {z[0] for z in con.execute("SELECT l.platte_id FROM lauf_schritt s JOIN lauf l USING (lauf_id) "
                                               "WHERE s.schritt = 'F' AND s.status = 'fertig'")}
        for p in schnell:
            offen[p]["F"] = 0 if p in f_fertig and not offen[p].get("D1") else None
        # F5: Vorschaubilder von Fotos ohne (aktuelle) Personenerkennung; offen, solange F nicht erledigt ist
        f5 = dict(con.execute("""
            SELECT d.platte_id, COUNT(DISTINCT v.sha256) FROM datei d JOIN vorschau v ON v.sha256 = d.sha256
            LEFT JOIN personen pe ON pe.sha256 = v.sha256
            WHERE v.art IN ('bild', 'raw') AND v.datei IS NOT NULL AND v.datei != ''
              AND (pe.sha256 IS NULL OR pe.modell != ? OR pe.erkannt_am < v.erstellt_am) GROUP BY d.platte_id""",
            (F5_KENNUNG,)).fetchall())
        for p in schnell:
            offen[p]["F5"] = f5.get(p, 0) if offen[p]["F"] == 0 else None

        # G: alle drei Duplikatarten nach der letzten Änderung der Platte (Prüfsummen, Metadaten, Vorschaubilder) berechnet
        g_zeit = dict(con.execute("SELECT objekt, MAX(zeit) FROM protokoll WHERE abschnitt = 'G' AND feld = 'gruppen' "
                                  "GROUP BY objekt").fetchall())
        g_letzte = min((g_zeit.get(a) for a in ("exakt", "variante", "beinahe")), key=lambda z: z or "") or ""
        for z in con.execute("""
                SELECT d.platte_id, SUM(COALESCE(d.gehasht_am, '') > :g OR COALESCE(m.gelesen_am, '') > :g
                                        OR COALESCE(v.erstellt_am, '') > :g) AS neu
                FROM datei d LEFT JOIN metadaten m ON m.platte_id = d.platte_id AND m.relpfad = d.relpfad
                LEFT JOIN vorschau v ON v.sha256 = d.sha256
                WHERE d.sha256 IS NOT NULL GROUP BY d.platte_id""", {"g": g_letzte}):
            offen[z["platte_id"]]["G"] = z["neu"] if g_letzte else None
        # Platte herausgenommen oder wieder aufgenommen: Die Gruppen stimmen erst nach einem neuen Abgleich
        wechsel = con.execute("SELECT MAX(zeit) FROM protokoll WHERE feld = 'deaktiviert_am'").fetchone()[0] or ""
        if g_letzte and wechsel > g_letzte:
            for p in offen:
                if offen[p].get("G") is not None:
                    offen[p]["G"], offen[p]["G_platten"] = max(offen[p]["G"], 1), True

        # H: Ampel vorhanden und jünger als alles, was in sie eingeht (D1, D2, D3, E, F), und jede Duplikatgruppe der
        # Platte hat eine Leitdatei (H2; G schreibt die Gruppen neu und löscht sie, bis H wieder läuft)
        for z in con.execute("""
                SELECT d.platte_id, SUM(a.relpfad IS NULL OR a.bewertet_am < MAX(COALESCE(d.gehasht_am, ''),
                           COALESCE(d.sf_am, ''), COALESCE(m.gelesen_am, ''), COALESCE(v.erstellt_am, ''),
                           COALESCE(vs.geprueft_am, ''))) AS neu
                FROM datei d LEFT JOIN archiv a ON a.platte_id = d.platte_id AND a.relpfad = d.relpfad
                LEFT JOIN metadaten m ON m.platte_id = d.platte_id AND m.relpfad = d.relpfad
                LEFT JOIN vorschau v ON v.sha256 = d.sha256 LEFT JOIN virenscan vs ON vs.sha256 = d.sha256
                GROUP BY d.platte_id"""):
            offen[z["platte_id"]]["H"] = z["neu"]
        for z in con.execute("""
                SELECT platte_id, COUNT(*) FROM gruppe WHERE art IN ('exakt', 'variante') AND gruppe_id NOT IN
                       (SELECT gruppe_id FROM gruppe WHERE leitdatei = 1) GROUP BY platte_id"""):
            if z[0] in offen and offen[z[0]].get("H") is not None:
                offen[z[0]]["H"] += z[1]
                offen[z[0]]["H_leit"] = z[1]

        # G5: mit dem aktuellen Bestand aus Anton abgeglichen (wie G5c auswählt); „nicht geprüft“ zählt als offen
        anton = con.execute("SELECT stand, quelle FROM anton_stand WHERE aktuell = 1").fetchone()
        for p in schnell:
            offen[p]["G5"] = None
        if anton:
            for z in con.execute("""
                    SELECT d.platte_id, SUM(a.relpfad IS NULL OR a.stand != :s OR a.md5 != d.md5) AS neu,
                           COALESCE(SUM(a.stand = :s AND a.md5 = d.md5 AND a.status = 'nicht geprüft'), 0) AS ungeprueft
                    FROM datei d LEFT JOIN anton_abgleich a ON a.platte_id = d.platte_id AND a.relpfad = d.relpfad
                    WHERE d.md5 IS NOT NULL GROUP BY d.platte_id""", {"s": anton["stand"]}):
                offen[z["platte_id"]].update({"G5": z["neu"] + z["ungeprueft"], "G5_neu": z["neu"],
                                              "G5_ungeprueft": z["ungeprueft"], "G5_stand": anton["stand"].split("/")[0]})
        self.offen_stand, self.offen_cache = stand, dict(offen)
        return self.offen_cache

    def gleich_je_platte(self, con):
        """Je Platte A und andere Platte B: wie viele Dateien von A bitgleich (gleiche SHA-256) auch auf B liegen.
        Dateien ab 1 KB ohne Systemdateien; nur Platten im Projekt.
        Für den Hinweis „als Kopie vermerken“; neu gerechnet, wenn sich die Datenbank geändert hat."""
        stand = self.bestand.db_stand()
        if stand == self.gleich_stand:
            return self.gleich_cache
        inhalte = defaultdict(list)
        for z in con.execute(f"""SELECT d.platte_id, d.sha256 FROM datei d JOIN platte p ON p.platte_id = d.platte_id
                                 WHERE d.sha256 IS NOT NULL AND d.groesse >= 1024 AND p.deaktiviert_am IS NULL
                                 AND NOT {self.SYSTEM}"""):
            inhalte[z[0]].append(z[1])
        mengen = {p: set(s) for p, s in inhalte.items()}
        ergebnis = {}
        for a, liste in inhalte.items():
            ergebnis[a] = {}
            for b, menge in mengen.items():
                n = sum(s in menge for s in liste) if b != a else 0
                if n:
                    ergebnis[a][b] = {"anteil": n / len(liste), "dateien": n, "von": len(liste)}
        self.gleich_stand, self.gleich_cache = stand, ergebnis
        return ergebnis

    def dashboard(self):
        """Daten für Dashboard und Bericht: Auswertung aus erfassung/dashboard.py (zwischengespeichert, bis sich die
        Datenbank ändert), Zähler der Bewertung aus dem Speicher, Stand der Analyse."""
        b = self.bestand
        b.aktuell_halten()
        stand = b.db_stand()
        if stand != getattr(self, "dashboard_stand", None):
            self.dashboard_cache, self.dashboard_stand = self.aufrufen("dashboard"), stand
        erfassung = self.stand()
        erfassung["platten"] = [p for p in erfassung["platten"] if not p["deaktiviert_am"]]
        es = getattr(self, "erschliessung", None)          # Vorlauf und Modul 3 (tool/erschliessung.py)
        return {"analyse": self.dashboard_cache, "erfassung": erfassung, "erschliessung": es.dashboard() if es else None,
                "schritte": [{"k": k, "name": self.CHIP_NAMEN[k]} for k in self.CHIPS],
                "bewertung": {"geladen_am": b.geladen_am,
                              "platten": [{"id": p["platte_id"], "zaehler": b.zaehler[(p["platte_id"], "")]} for p in b.platten]}}

    def bericht_speichern(self):
        """Schnappschuss des Dashboards als eine HTML-Datei in berichte/: Stil, Darstellung und Daten eingebettet."""
        daten = self.dashboard()
        daten["erfassung"]["lauf"] = None if not (daten["erfassung"]["lauf"] or {}).get("aktiv") else daten["erfassung"]["lauf"]
        jetzt = time.strftime("%Y-%m-%d_%H%M")
        json_text = json.dumps(daten, ensure_ascii=False, default=str).replace("</", "<\\/")
        titel = f"Bericht {self.info['name']} · {time.strftime('%d.%m.%Y %H:%M')}"
        skript = (WEB / "dashboard.js").read_text(encoding="utf-8")
        # Icons ohne Server: nur die Symbole aus dem Lucide-Sprite, die dashboard.js mit icon("…") verwendet
        namen = set(re.findall(r'icon\("([a-z0-9-]+)"', skript))
        sprite = (WEB / "vendor" / "lucide" / "sprite.svg").read_text(encoding="utf-8")
        symbole = "".join(m.group(0) for m in re.finditer(r'<symbol id="([a-z0-9-]+)".*?</symbol>', sprite, re.S)
                          if m.group(1) in namen)
        # Stil mit eingebetteter Schrift Inter (data:-URL), damit der Bericht ohne Server gleich aussieht
        stil = re.sub(r'url\("/web/vendor/inter/([a-z-]+\.woff2)"\)', lambda m: 'url("data:font/woff2;base64,' + base64.b64encode(
            (WEB / "vendor" / "inter" / m.group(1)).read_bytes()).decode() + '")', (WEB / "app.css").read_text(encoding="utf-8"))
        seite = f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{titel}</title><style>{stil}</style></head>
<body class="bericht-seite"><header class="bericht-kopf"><h1>{titel}</h1>
<div class="leise">Schnappschuss des Dashboards aus dem Tool Balduin; {len(daten["bewertung"]["platten"])} Platten, Datenbank
{self.bestand.db_pfad.name}. Die Datei braucht keinen Server und kein Internet.</div></header>
<main id="db-inhalt" class="bericht-inhalt"></main>
<script id="bericht-daten" type="application/json">{json_text}</script>
<svg hidden><defs>{symbole}</defs></svg>
<script>window.ICON_QUELLE = "";</script><script>{(WEB / "icons.js").read_text(encoding="utf-8")}</script>
<script>{skript}</script>
<script>Dash.rendern(JSON.parse(document.getElementById("bericht-daten").textContent), document.getElementById("db-inhalt"));</script>
</body></html>"""
        ordner = self.projekt / "berichte"
        ordner.mkdir(exist_ok=True)
        ziel = ordner / f"bericht_{jetzt}.html"
        ziel.write_text(seite, encoding="utf-8")
        return {"ok": True, "datei": ziel.name, "pfad": str(ziel.relative_to(self.projekt)),
                "groesse": ziel.stat().st_size}

    def bericht_zeigen(self, datei):
        """Gespeicherten Bericht im Dateimanager markieren (nur Dateien aus berichte/)."""
        ziel = (self.projekt / "berichte" / Path(datei).name)
        if not ziel.is_file():
            raise ValueError(f"{datei} gibt es nicht in berichte/")
        try:
            system.im_dateimanager_zeigen(ziel)
        except RuntimeError:
            pass
        return {"ok": True}

    def aktiver_lauf(self):
        lauf = self.stand()["lauf"]
        return lauf if lauf and lauf["aktiv"] else None

    def aktive_laeufe(self):
        """Alle Läufe, die warten oder leben (bis zu zwei: Anton neben einem anderen, Entscheidung 05.11.2026)."""
        con = self.bestand.verbinden()
        try:
            zeilen = con.execute("SELECT lauf_id, art, platte_id, status, pid FROM lauf WHERE status IN ('wartet', 'läuft')").fetchall()
        finally:
            con.close()
        return [dict(z) for z in zeilen if z["status"] == "wartet" or self.lebt(z["pid"])]

    def laeuft(self, art=None, platte_id=None):
        return any((art is None or l["art"] == art) and (platte_id is None or l["platte_id"] == platte_id)
                   for l in self.aktive_laeufe())

    def passwort_klaeren(self, platte_id, passwort, mountpunkt):
        """Verschlüsseltes Volume (13.11.2026): ein Lauf mit Datenträger braucht das Passwort; es geht nur über stdin an
        den Lauf und wird nirgends gespeichert. Ein solcher Lauf wird nie eingereiht: wer ihn später startete, kennte das
        Passwort nicht. Antwort: das Passwort oder None."""
        if not mountpunkt:
            return None
        con = self.bestand.verbinden()
        try:
            z = con.execute("SELECT verschluesselt FROM platte WHERE platte_id = ?", (platte_id,)).fetchone()
            belegt = con.execute("SELECT 1 FROM lauf WHERE art != 'anton' AND status IN ('eingereiht', 'wartet', 'läuft') "
                                 "LIMIT 1").fetchone()
        finally:
            con.close()
        if not passwort:
            if z and z["verschluesselt"]:
                raise ValueError(f"{platte_id} ist verschlüsselt: Bitte das Passwort eingeben (es wird nicht gespeichert).")
            return None
        if belegt:
            raise ValueError("Ein verschlüsselter Datenträger startet nur, wenn kein anderer Lauf läuft oder eingereiht ist "
                             "(das Passwort wird nicht gespeichert). Danach erneut starten.")
        return passwort

    def starten(self, auftrag):
        """Reiht den Lauf ein und startet ihn gleich, wenn keiner läuft (sonst nach dem laufenden, siehe weiter)."""
        passwort = auftrag.pop("passwort", None) or None    # nie in den Auftrag (er steht in der Datenbank)
        platte_id = kennung_pruefen(auftrag.get("platte_id"))
        # Auswahl einzelner Schritte: samt Pflicht-Folgeschritten (G → H); Schritte, die die Platte lesen, brauchen sie
        schritte = auftrag.get("schritte")
        if schritte is not None:
            if not schritte or not set(schritte) <= set(self.CHIPS):
                raise ValueError("Keine oder unbekannte Schritte gewählt.")
            schritte = set(schritte) | {f for k in schritte for f in self.FOLGESCHRITTE.get(k, [])}
            auftrag = {**auftrag, "schritte": [k for k in self.CHIPS if k in schritte]}
            if schritte & self.MIT_PLATTE and not auftrag.get("mountpunkt"):
                raise ValueError("Die gewählten Schritte brauchen den Datenträger, er ist aber nicht angeschlossen.")
        # Registrieren und Neu analysieren brauchen die Platte; Fortsetzen ohne sie lässt die Schritte mit Platte aus
        if auftrag.get("modus") != "fortsetzen" and not auftrag.get("mountpunkt"):
            raise ValueError("Der Datenträger ist nicht angeschlossen.")
        if auftrag.get("art") == "ordner" and not (auftrag.get("etikett") or "").strip():
            raise ValueError("Bitte die Herkunft des Ordners angeben (woher, von wem, seit wann).")
        if auftrag.get("art") == "abbild" and not (auftrag.get("etikett") or "").strip():
            raise ValueError("Bitte die Herkunft des Abbilds angeben (von welchem Datenträger, wer hat es wann erstellt).")
        if auftrag.get("umfang") is not None and not isinstance(auftrag["umfang"], list):
            raise ValueError("Der Umfang ist eine Liste von Ordnern.")
        auftrag = {**auftrag, "platte_id": platte_id,
                   "mountpunkt": str(self.quellpfad_pruefen(auftrag["mountpunkt"], platte_id, auftrag.get("art")))
                                 if auftrag.get("mountpunkt") else None}
        if auftrag.get("umfang") is not None and auftrag["mountpunkt"]:   # sofort ablehnen, nicht erst im Lauf
            auftrag["umfang"] = self.aufrufen("quellordner", "--daten", json.dumps(
                {"aktion": "umfang", "platte_id": platte_id, "umfang": auftrag["umfang"],
                 "wurzel": auftrag["mountpunkt"], "volume_uuid": auftrag.get("volume_uuid")}, ensure_ascii=False))["umfang"]
        con = self.bestand.verbinden()
        try:
            eingereiht = con.execute("SELECT 1 FROM lauf WHERE platte_id = ? AND status = 'eingereiht'",
                                     (platte_id,)).fetchone()
            herausgenommen = con.execute("SELECT 1 FROM platte WHERE platte_id = ? AND deaktiviert_am IS NOT NULL",
                                         (platte_id,)).fetchone()
        finally:
            con.close()
        if herausgenommen:
            raise ValueError(f"{platte_id} ist aus dem Projekt genommen. Erst wieder aufnehmen, dann analysieren.")
        if eingereiht:
            raise ValueError(f"{platte_id} ist schon eingereiht. Den eingereihten Lauf erst entfernen.")
        if self.laeuft(platte_id=platte_id):
            raise ValueError(f"{platte_id} wird gerade analysiert. Erst abwarten oder abbrechen.")
        passwort = self.passwort_klaeren(platte_id, passwort, auftrag.get("mountpunkt"))
        if passwort:
            auftrag["mit_passwort"] = True
        # ohne Schreibschutz lesen: einmal je Datenträger zugestimmt, gilt danach für jeden Lauf (13.11.2026)
        if auftrag.get("beschreibbar_ok"):
            self.ohne_schreibschutz_zustimmen(platte_id)
        elif self.ohne_schreibschutz(platte_id):
            auftrag["beschreibbar_ok"] = True
        foto = self.foto_ablegen(auftrag.pop("foto_daten", None))
        if foto:                                           # B kopiert es nach data/etiketten/
            auftrag["foto"] = foto
        with self.bestand.schreibend() as con:
            lauf_id = con.execute("INSERT INTO lauf (art, platte_id, auftrag, status, start) VALUES ('erfassen', ?, ?, 'eingereiht', ?)",
                                  (platte_id, json.dumps(auftrag, ensure_ascii=False),
                                   time.strftime("%Y-%m-%dT%H:%M:%S"))).lastrowid
        gestartet = self.weiter({lauf_id: passwort} if passwort else None)
        return {"ok": True, "lauf_id": lauf_id, "eingereiht": lauf_id not in gestartet}

    # Wie NAECHSTEN_UEBERNEHMEN in erfassung/lauf.py: je Spur höchstens einer („anton“ neben allen übrigen)
    UEBERNEHMEN = """
    UPDATE lauf SET status = 'wartet' WHERE lauf_id IN (
        SELECT MIN(l.lauf_id) FROM lauf l WHERE l.status = 'eingereiht'
        AND NOT EXISTS (SELECT 1 FROM lauf x WHERE x.status IN ('wartet', 'läuft') AND (x.art = 'anton') = (l.art = 'anton'))
        GROUP BY l.art = 'anton')
    RETURNING lauf_id"""

    def weiter(self, eingaben=None):
        """Startet je Spur den ältesten eingereihten Lauf, wenn dort keiner läuft (Antwort: gestartete lauf_id). Meist
        tut das schon der beendete Lauf selbst; hier
        für den ersten Lauf und für Läufe, die hart beendet wurden (Mac neu gestartet): Die werden als abgebrochen vermerkt."""
        con = self.bestand.verbinden()
        try:
            if not con.execute("SELECT 1 FROM lauf WHERE status = 'eingereiht' LIMIT 1").fetchone():
                return []
            laufend = con.execute("SELECT lauf_id, pid FROM lauf WHERE status = 'läuft'").fetchall()
        finally:
            con.close()
        tot = [z["lauf_id"] for z in laufend if not self.lebt(z["pid"])]
        with self.bestand.schreibend() as con:
            con.executemany("UPDATE lauf SET status = 'abgebrochen', ende = ?, meldung = ? WHERE lauf_id = ?",
                            [(time.strftime("%Y-%m-%dT%H:%M:%S"),
                              "Der Lauf wurde beendet (z. B. Rechner neu gestartet).", i) for i in tot])
            uebernommen = [z[0] for z in con.execute(self.UEBERNEHMEN).fetchall()]
        for lauf_id in uebernommen:                     # eingaben: Passwort eines Laufs, nur über stdin (13.11.2026)
            system.hintergrund_starten(system.lauf_befehl("erfassen", *projekt_argumente(self.projekt), "--lauf", lauf_id),
                                       cwd=CODE, eingabe=(eingaben or {}).get(lauf_id))
        return uebernommen

    def entfernen(self, lauf_id):
        """Eingereihten Lauf aus der Warteschlange nehmen (markiert als entfernt); ein gestarteter bleibt, wie er ist."""
        with self.bestand.schreibend() as con:
            z = con.execute("UPDATE lauf SET status = 'entfernt', ende = ? WHERE lauf_id = ? AND status = 'eingereiht' "
                            "RETURNING auftrag", (time.strftime("%Y-%m-%dT%H:%M:%S"), lauf_id)).fetchone()
        if z is None:
            raise ValueError("Der Lauf ist nicht mehr eingereiht (vielleicht eben gestartet).")
        foto = json.loads(z["auftrag"] or "{}").get("foto")      # temporäres Etikettfoto, noch nicht kopiert
        if foto and Path(foto).name.startswith("etikett_") and Path(foto).parent == Path(tempfile.gettempdir()):
            Path(foto).unlink(missing_ok=True)
        return {"ok": True}

    def datentraeger(self):
        """Angeschlossene Datenträger; die nächste freie Kennung überspringt eingereihte neue Platten. Dazu je neuer
        Platte, ob sie in einem anderen bekannten Projekt registriert ist (zuletzt geöffnete und die im Ordner der
        Projekte; deren Datenbanken werden nur gelesen)."""
        andere = {e["pfad"] for e in zuletzt_lesen()["liste"]}
        for ort in {Path(PROJEKTE), vorgabe_ablageort()}:
            if ort.is_dir():
                andere |= {str(o) for o in ort.iterdir() if (o / "projekt.json").is_file()}
        andere.discard(str(self.projekt))
        antwort = self.aufrufen("datentraeger", "--daten", json.dumps({"andere": sorted(andere)}, ensure_ascii=False))
        con = self.bestand.verbinden()
        try:
            belegt = {z[0] for z in con.execute("SELECT platte_id FROM lauf WHERE status IN ('eingereiht', 'wartet', 'läuft')")}
        finally:
            con.close()
        kuerzel = antwort["kennung"]
        while antwort["naechste"] in belegt and re.fullmatch(re.escape(kuerzel) + r"\d\d", antwort["naechste"]):
            antwort["naechste"] = f"{kuerzel}{int(antwort['naechste'][len(kuerzel):]) + 1:02d}"
        return antwort

    @staticmethod
    def foto_ablegen(foto):
        """Foto des Etiketts aus dem Browser (data-URL) als temporäre Datei; erfassung kopiert es ins Projekt."""
        if not foto:
            return None
        endung = Path(foto.get("name", "")).suffix.lower() or ".jpg"
        fd, pfad = tempfile.mkstemp(prefix="etikett_", suffix=endung)
        with os.fdopen(fd, "wb") as f:
            f.write(base64.b64decode(foto["daten"].split(",")[-1]))
        return pfad

    def angaben_aendern(self, daten):
        """Etikett, Foto, Notiz und Kopie-Vermerk einer registrierten Platte ändern (auch ohne angeschlossene Platte)."""
        werte = {k: daten.get(k) for k in ("platte_id", "etikett", "notiz", "kopie_von")}
        werte["foto"] = self.foto_ablegen(daten.get("foto_daten"))
        try:
            return self.aufrufen("angaben", "--daten", json.dumps(werte, ensure_ascii=False))
        finally:
            if werte["foto"]:
                os.unlink(werte["foto"])

    def herausnehmen(self, daten):
        """Platte aus dem Projekt nehmen (nur mit eingetippter Kennung) oder wieder aufnehmen. Gelöscht wird nichts,
        erfassung/platte.py setzt nur platte.deaktiviert_am; nicht während die Platte läuft oder eingereiht ist."""
        platte_id, herausnehmen = daten.get("platte_id"), bool(daten.get("herausnehmen", True))
        if herausnehmen and (daten.get("bestaetigung") or "").strip() != platte_id:
            raise ValueError(f"Zum Bestätigen genau „{platte_id}“ eintippen.")
        con = self.bestand.verbinden()
        try:
            eingereiht = con.execute("SELECT 1 FROM lauf WHERE platte_id = ? AND status = 'eingereiht'",
                                     (platte_id,)).fetchone()
        finally:
            con.close()
        if herausnehmen and (eingereiht or self.laeuft(platte_id=platte_id)):
            raise ValueError(f"{platte_id} wird gerade analysiert oder ist eingereiht. Erst abbrechen bzw. entfernen.")
        antwort = self.aufrufen("herausnehmen", "--daten",
                                json.dumps({"platte_id": platte_id, "herausnehmen": herausnehmen}, ensure_ascii=False))
        self.bestand.aktuell_halten()
        return {"ok": True, **antwort}

    def abbrechen(self, lauf_id):
        """Wie Ctrl+C: Der laufende Schritt hört an seiner nächsten Prüfstelle auf, Ergebnisse bleiben gespeichert.
        Auf dem Mac zuerst das Signal: Der Lauf hält beim Schreiben oft die Sperre der Datenbank, die Marke käme dann zu
        spät. Unter Windows gibt es kein solches Signal; dort liest die Abbruchwache des Laufs die Marke (erfassung/lauf.py),
        darum wird sie notfalls wiederholt geschrieben, bis die Datenbank frei ist."""
        con = self.bestand.verbinden()
        try:
            z = con.execute("SELECT pid, status FROM lauf WHERE lauf_id = ?", (lauf_id,)).fetchone()
        finally:
            con.close()
        if z and z["status"] in ("wartet", "läuft"):
            system.unterbrechen(z["pid"])

        def marke():                                     # für die Wache, die Anzeige und falls der Lauf noch nicht lief
            ende = time.monotonic() + 120
            while time.monotonic() < ende:
                try:
                    with self.bestand.schreibend() as con:
                        con.execute("UPDATE lauf SET abbrechen = 1 WHERE lauf_id = ?", (lauf_id,))
                    return
                except sqlite3.OperationalError:
                    time.sleep(0.5)
        threading.Thread(target=marke, daemon=True).start()
        return {"ok": True}

    def anton_starten(self, modus="", seit=None):
        """Lauf „Bestand aus Anton holen“ (G5b über die API, danach G5c für alle Platten) in die Warteschlange.
        modus "fortsetzen": ein Bestand, der seit „seit“ (Beginn des ersten Laufs) vollständig geholt ist, gilt."""
        if self.anton_eingereiht() or self.laeuft("anton"):
            raise ValueError("Der Bestand aus Anton wird schon geholt oder ist eingereiht.")
        with self.bestand.schreibend() as con:
            lauf_id = con.execute("INSERT INTO lauf (art, platte_id, auftrag, status, start) VALUES ('anton', NULL, ?, "
                                  "'eingereiht', ?)", (json.dumps({"modus": modus, "seit": seit}), time.strftime("%Y-%m-%dT%H:%M:%S"))
                                  ).lastrowid
        gestartet = self.weiter()
        return {"ok": True, "lauf_id": lauf_id, "eingereiht": lauf_id not in gestartet}

    def anton_eingereiht(self):
        con = self.bestand.verbinden()
        try:
            return con.execute("SELECT 1 FROM lauf WHERE art = 'anton' AND status = 'eingereiht'").fetchone() is not None
        finally:
            con.close()

    def sprachmodell(self, daten):
        """Sprachmodell auf Abruf (vorlauf/sprachmodell.py, nur lokal): Modelle abfragen oder Vorschlag holen (~30 s)."""
        return lauf_aufrufen("sprachmodell", *projekt_argumente(self.projekt), "--daten",
                             json.dumps(daten, ensure_ascii=False), timeout=330)

    def anton_aktion(self, daten):
        """Token ablegen oder entfernen, Verbindung prüfen. Der Token geht über stdin an erfassung.lauf, nie als Argument."""
        aktion = daten.get("aktion")
        if aktion not in ("pruefen", "token_speichern", "token_entfernen"):
            raise ValueError("unbekannte Aktion")
        antwort = self.aufrufen("anton", "--daten", json.dumps({"aktion": aktion}),
                                eingabe=daten.get("token", "") if aktion == "token_speichern" else "")
        self.info["anton_token"] = antwort["token"]
        return {"ok": True, **antwort}

    def fortsetzen(self, lauf_id, passwort=None):
        """Neuer Lauf mit demselben Auftrag; jeder Schritt macht nur, was noch fehlt (das Etikettfoto ist schon kopiert).
        passwort: bei einem verschlüsselten Volume (wird nicht gespeichert)."""
        con = self.bestand.verbinden()
        try:
            z = con.execute("SELECT art, auftrag, start FROM lauf WHERE lauf_id = ?", (lauf_id,)).fetchone()
        finally:
            con.close()
        if z is None:
            raise ValueError(f"Lauf {lauf_id} unbekannt")
        if z["art"] == "anton":
            return self.anton_starten("fortsetzen", json.loads(z["auftrag"]).get("seit") or z["start"])
        if z["art"] == "export":                          # Modul 4: gleicher Auftrag, die Platte neu gesucht
            a = json.loads(z["auftrag"])
            return self.pakete.starten({"platte_id": a.get("platte_id") or "", "beschreibbar_ok": a.get("beschreibbar_ok"),
                                        "passwort": passwort})
        if z["art"] == "vorlauf":                         # gleicher Auftrag; der Umfang steht noch in vorlauf_umfang
            con = self.bestand.verbinden()
            try:
                belegt = con.execute("SELECT 1 FROM lauf WHERE art = 'vorlauf' AND status = 'eingereiht'").fetchone()
            finally:
                con.close()
            if belegt or self.laeuft("vorlauf"):
                raise ValueError("Der Vorlauf läuft schon oder ist eingereiht.")
            with self.bestand.schreibend() as con:
                neu_id = con.execute("INSERT INTO lauf (art, platte_id, auftrag, status, start) VALUES ('vorlauf', NULL, ?, "
                                     "'eingereiht', ?)", (z["auftrag"], time.strftime("%Y-%m-%dT%H:%M:%S"))).lastrowid
            gestartet = self.weiter()
            return {"ok": True, "lauf_id": neu_id, "eingereiht": neu_id not in gestartet}
        auftrag = {**json.loads(z["auftrag"]), "modus": "fortsetzen", "passwort": passwort}
        auftrag.pop("mit_passwort", None)                 # gilt nur, wenn diesmal eins mitkommt
        if auftrag.get("foto") and not Path(auftrag["foto"]).exists():
            auftrag.pop("foto")
        return self.starten(auftrag)

    def platte_starten(self, daten):
        """Lauf für eine registrierte Platte: modus "fortsetzen" (Ausstehendes nachholen; ohne Mountpunkt nur die
        Schritte ohne Platte; mit „schritte“ nur diese samt Pflichtfolgen) oder "neu" (neu analysieren, braucht die Platte).
        Etikett, Notiz und Kopie-Vermerk bleiben, wie sie sind."""
        if daten.get("modus") not in ("fortsetzen", "neu"):
            raise ValueError("modus muss fortsetzen oder neu sein")
        if daten["modus"] == "neu" and not daten.get("mountpunkt"):
            raise ValueError("Neu analysieren braucht den Datenträger: anschließen und schreibgeschützt einhängen.")
        con = self.bestand.verbinden()
        try:
            bekannt = con.execute("SELECT 1 FROM platte WHERE platte_id = ?", (daten.get("platte_id"),)).fetchone()
        finally:
            con.close()
        if not bekannt:
            raise ValueError(f"{daten.get('platte_id')} ist nicht registriert.")
        auftrag = {k: daten.get(k) for k in ("platte_id", "mountpunkt", "modus", "beschreibbar_ok")}
        if daten.get("umfang") is not None:                # Umfang erweitern (Entscheidung 05.11.2026); braucht die Platte
            if not daten.get("mountpunkt"):
                raise ValueError("Den Umfang erweitern geht nur mit angeschlossenem Datenträger.")
            auftrag["umfang"] = daten["umfang"]
        if daten.get("schritte"):                         # Auswahl: nur diese, jeder macht nur, was fehlt
            if daten["modus"] != "fortsetzen":
                raise ValueError("Eine Auswahl läuft nur im Modus fortsetzen.")
            auftrag["schritte"] = list(daten["schritte"])
        return self.starten(auftrag | {"passwort": daten.get("passwort")})


# ---------- Projekte: öffnen, anlegen, zuletzt geöffnet ----------

def projekt_argumente(projekt):
    """Projekt und Test-Überschreibungen für erfassung/lauf.py."""
    return (["--projekt", str(projekt), "--volumes", str(VOLUMES)]
            + (["--arbeitsplatte", str(ARBEITSPLATTE)] if ARBEITSPLATTE else []))


def lauf_aufrufen(befehl, *weitere, timeout=180, eingabe=None):
    """Kurze Abfrage über erfassung/lauf.py (dieselben Funktionen wie die Läufe); Antwort als JSON.
    eingabe: Text für stdin (Geheimes wie der Anton-Token, damit es in keiner Prozessliste steht)."""
    ergebnis = subprocess.run(system.lauf_befehl(befehl, *weitere),
                              cwd=CODE, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout,
                              input=eingabe, stdin=None if eingabe is not None else subprocess.DEVNULL,
                              **system.prozess_optionen())
    if ergebnis.returncode != 0:
        letzte = [z for z in ergebnis.stderr.strip().splitlines() if z.strip()]
        meldung = letzte[-1] if letzte else f"erfassung.lauf {befehl} ist gescheitert"
        raise RuntimeError(re.sub(r"^\w+(Error|Exception): ", "", meldung))     # „ValueError: …“ → „…“
    zeilen = [z for z in ergebnis.stdout.splitlines() if z.strip()]   # die Antwort steht in der letzten Zeile
    return json.loads(zeilen[-1])


def zuletzt_lesen():
    try:
        d = json.loads(ZULETZT.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"projekt": None, "liste": [], "ablageort": None}
    liste = d.get("liste") or ([{"pfad": d["projekt"], "name": Path(d["projekt"]).name}] if d.get("projekt") else [])
    return {"projekt": d.get("projekt"), "liste": liste, "ablageort": d.get("ablageort")}


def zuletzt_schreiben(projekt, liste, ablageort=None):
    """Schreibt zuletzt.json; der gemerkte Ablageort bleibt erhalten, wenn kein neuer kommt."""
    ablageort = ablageort or zuletzt_lesen()["ablageort"]
    d = {"projekt": projekt, "liste": liste, **({"ablageort": str(ablageort)} if ablageort else {})}
    ZULETZT.parent.mkdir(parents=True, exist_ok=True)
    ZULETZT.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def vorgabe_ablageort():
    """Wohin der Assistent neue Projekte vorschlägt (Entscheidung 06.11.2026): der in zuletzt.json gemerkte Ort, sonst
    (oder wenn es ihn nicht mehr gibt) Projekte/ neben dem Code."""
    gemerkt = zuletzt_lesen()["ablageort"]
    return Path(gemerkt) if gemerkt and Path(gemerkt).is_dir() else Path(PROJEKTE)


# Module, die sich Balduin je Projekt merkt (data-ansicht in index.html); ohne gemerktes beginnt es mit Modul 1
ANSICHTEN = ("erfassung", "bewertung", "vorlauf", "erschliessung", "export")


def zuletzt_merken(pfad, name):
    """Geöffnetes Projekt an den Anfang der Liste; „projekt“ = zuletzt geöffnet.
    Das zuletzt genutzte Modul des Projekts bleibt erhalten."""
    alte = zuletzt_lesen()["liste"]
    vorher = next((e for e in alte if e["pfad"] == str(pfad)), {})
    liste = [e for e in alte if e["pfad"] != str(pfad)]
    eintrag = {"pfad": str(pfad), "name": name, "geoeffnet_am": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if vorher.get("ansicht") in ANSICHTEN:
        eintrag["ansicht"] = vorher["ansicht"]
    liste.insert(0, eintrag)
    zuletzt_schreiben(str(pfad), liste[:12])


def ansicht_merken(pfad, ansicht):
    """Merkt beim Projekt, in welchem Modul zuletzt gearbeitet wurde (Entscheidung 05.11.2026); beim nächsten Öffnen
    oder Start beginnt Balduin dort. Im Server statt im Browser, weil der Browserspeicher nur je Adresse gilt."""
    if ansicht not in ANSICHTEN:
        raise ValueError(f"Unbekanntes Modul: {ansicht}")
    z, pfad = zuletzt_lesen(), str(Path(pfad).resolve())
    for e in z["liste"]:
        if e["pfad"] == pfad:
            e["ansicht"] = ansicht
    zuletzt_schreiben(z["projekt"], z["liste"])
    return {"ok": True}


def projekt_vergessen(pfad):
    """Nimmt ein Projekt aus der Liste „Zuletzt geöffnet“; der Ordner bleibt (Entscheidung 04.11.2026)."""
    z = zuletzt_lesen()
    liste = [e for e in z["liste"] if e["pfad"] != str(pfad)]
    projekt = z["projekt"] if z["projekt"] != str(pfad) else (liste[0]["pfad"] if liste else None)
    zuletzt_schreiben(projekt, liste)
    return {"ok": True}


def projekt_verlegen(alt, pfad):
    """Gibt einem nicht gefundenen Projekt der Liste den neuen Ort (Entscheidung 13.11.2026): Der Eintrag behält Stelle
    und gemerktes Modul, Name aus projekt.json. Geöffnet wird nicht; Ordner werden nur gelesen."""
    pfad = Path(pfad).expanduser().resolve()
    if not ist_projekt(pfad):
        raise ValueError(f"{pfad} ist kein Projektordner (projekt.json fehlt).")
    name = json.loads((pfad / "projekt.json").read_text(encoding="utf-8")).get("name") or pfad.name
    z, neu = zuletzt_lesen(), nfc(str(pfad))
    liste = [e for e in z["liste"] if e["pfad"] != neu or e["pfad"] == str(alt)]   # schon gelistet: nur einmal
    for e in liste:
        if e["pfad"] == str(alt):
            e.update(pfad=neu, name=name)
    projekt = neu if z["projekt"] == str(alt) else z["projekt"]
    zuletzt_schreiben(projekt, liste)
    return {"ok": True, "pfad": neu, "name": name}


def projekt_loeschen(pfad, name):
    """Legt einen Projektordner in den Papierkorb (wiederherstellbar) und nimmt ihn aus der Liste. Nicht das geöffnete
    Projekt, nichts auf einem eingehängten Datenträger (harte Regel 1) und nur, wenn der eingetippte Name passt."""
    pfad = Path(pfad).expanduser().resolve()
    if not ist_projekt(pfad):
        raise ValueError(f"{pfad} ist kein Projektordner (projekt.json fehlt); aus der Liste entfernen geht trotzdem.")
    if Anfrage.erfassung is not None and Path(Anfrage.erfassung.projekt).resolve() == pfad:
        raise ValueError("Das geöffnete Projekt lässt sich nicht löschen. Erst ein anderes öffnen.")
    if system.datentraeger_von(pfad, VOLUMES) is not None or system.datentraeger_von(pfad) is not None:
        raise ValueError("Projekte auf einem eingehängten Datenträger löscht Balduin nicht; nur aus der Liste entfernen.")
    echt = json.loads((pfad / "projekt.json").read_text(encoding="utf-8")).get("name") or pfad.name
    if (name or "").strip() != echt:
        raise ValueError(f"Zum Bestätigen genau den Namen „{echt}“ eintippen.")
    system.in_papierkorb(pfad)
    projekt_vergessen(pfad)
    return {"ok": True, "pfad": str(pfad)}


def ist_projekt(pfad):
    return (Path(pfad) / "projekt.json").is_file()


def projekt_oeffnen(pfad):
    """Öffnet ein Projekt für alle Ansichten. erfassung legt dabei fehlende Arbeitsordner und Tabellen an."""
    pfad = Path(pfad).expanduser().resolve()
    if not ist_projekt(pfad):
        raise ValueError(f"{pfad} ist kein Projektordner (projekt.json fehlt).")
    info = lauf_aufrufen("projekt", *projekt_argumente(pfad))
    bestand = Bestand(pfad / "inventar.sqlite", info["vorschauen"])
    with Anfrage.sperre:
        Anfrage.bestand, Anfrage.erfassung = bestand, Erfassung(bestand, info)
        Anfrage.erschliessung = Erschliessung(bestand, Anfrage.erfassung)
        Anfrage.erfassung.erschliessung = Anfrage.erschliessung      # fürs Dashboard (Reiter Erschließung)
        Anfrage.pakete = Pakete(bestand, Anfrage.erfassung, Anfrage.erschliessung)
        Anfrage.erfassung.pakete = Anfrage.pakete                    # Fortsetzen eines Exportlaufs
    zuletzt_merken(pfad, info["name"])
    print(f"Projekt geöffnet: {info['name']} ({pfad})", flush=True)
    return {"ok": True, "name": info["name"]}


def projekte_json():
    e = Anfrage.erfassung
    zuletzt = [{**z, "vorhanden": ist_projekt(z["pfad"])} for z in zuletzt_lesen()["liste"]]
    offen = None
    if e:
        offen = {k: e.info[k] for k in ("name", "ordner", "einstellungen", "vorschauen")}
        offen["anton_token"] = e.info.get("anton_token", "")
        eintrag = next((z for z in zuletzt if z["pfad"] == str(Path(e.info["ordner"]).resolve())), {})
        offen["ansicht"] = eintrag.get("ansicht") if eintrag.get("ansicht") in ANSICHTEN else "erfassung"
        con = e.bestand.verbinden()
        try:                                          # frisch gezählt: das Kürzel ist nur ohne Platten änderbar
            offen["platten"] = con.execute("SELECT COUNT(*) FROM platte").fetchone()[0]
        finally:
            con.close()
        offen["arbeitsplatte"], offen["arbeitsplatte_da"] = e.arbeitsplatte()
        offen["speicher"] = speicher_angaben(Path(e.info["ordner"]), offen["arbeitsplatte"] if offen["arbeitsplatte_da"] else "",
                                             e.bestand)
    return {"offen": offen,
            "zuletzt": zuletzt, "ablageort": str(vorgabe_ablageort())}


# Rund so viel braucht ein Vorschaubild (JPEG 400 px oder kurzes WebP); nur für die Schätzung vor einer Analyse
VORSCHAU_JE_DATEI = 35_000


def gb_text(b):
    """Bytes als „3,5 GB“ (unter 0,1 GB in MB), wie im Assistenten."""
    if b < 1e8:
        return f"{max(1, round(b / 1e6))} MB"
    gb = round(b / 1e9, 1)
    return f"{gb:g} GB".replace(".", ",")


def platz_schaetzen(dateien, frei, reserve, arbeitsplatte=False, arbeitsplatte_frei=None):
    """Was die Vorschaubilder einer Analyse höchstens brauchen und ob der Platz reicht (Entscheidung 12.11.2026).
    dateien: Dateien ohne Vorschaubild (None = noch unbekannt, etwa vor dem ersten Lesen); frei/reserve in Bytes auf dem
    Laufwerk des Projekts; auf einer Arbeitsplatte bleibt 1 GB frei (wie erfassung/vorschau.py). Ergebnis mit Text für
    die Rückfrage vor dem Start; knapp = der Lauf hielte wohl bei den Vorschaubildern an."""
    wo = "auf dem Datenträger für Vorschaubilder" if arbeitsplatte else "am Speicherort des Projekts"
    ort_frei, rest = (arbeitsplatte_frei, 1e9) if arbeitsplatte else (frei, reserve)
    frei_text = (f"frei sind {gb_text(ort_frei)}" if ort_frei is not None
                 else "der Datenträger für Vorschaubilder ist nicht angeschlossen")
    if dateien is None:
        return {"bedarf": None, "knapp": False,
                "text": f"Vorschaubilder brauchen etwa {VORSCHAU_JE_DATEI // 1000} KB je Bild (100 000 Bilder rund "
                        f"{gb_text(100_000 * VORSCHAU_JE_DATEI)}) {wo}; {frei_text}."}
    bedarf = dateien * VORSCHAU_JE_DATEI
    if not bedarf:
        return {"bedarf": 0, "knapp": False, "text": ""}
    text = f"Die Vorschaubilder brauchen höchstens etwa {gb_text(bedarf)} {wo}; {frei_text}."
    knapp = ort_frei is not None and ort_frei - bedarf < rest
    if knapp:
        text += (f" Das wird knapp: Bitte vorher dort etwa {gb_text(rest + bedarf - ort_frei)} freiräumen"
                 f"{'' if arbeitsplatte else f' ({gb_text(reserve)} bleiben als Reserve frei)'}, sonst hält die "
                 "Analyse bei den Vorschaubildern an.")
    return {"bedarf": bedarf, "knapp": knapp, "text": text}


def speicher_angaben(ordner, arbeitsplatte, bestand):
    """Platz für das Zahnrad (Feedback 04.11.2026): frei auf dem Laufwerk des Projekts, vom Projektordner belegt, frei
    auf der Arbeitsplatte, Zahl der Vorschaubilder (nur Größen dieses Rechners; nichts geht hinaus)."""
    belegt = 0
    for wurzel, _, dateien in os.walk(ordner):
        for d in dateien:
            try:
                belegt += os.lstat(os.path.join(wurzel, d)).st_size
            except OSError:
                pass
    con = bestand.verbinden()
    try:
        vorschauen = con.execute("SELECT COUNT(*) FROM vorschau WHERE datei IS NOT NULL AND datei != ''").fetchone()[0]
    except sqlite3.OperationalError:
        vorschauen = 0
    finally:
        con.close()
    return {"frei": shutil.disk_usage(ordner).free, "belegt": belegt, "vorschauen": vorschauen,
            "arbeitsplatte_frei": shutil.disk_usage(arbeitsplatte).free if arbeitsplatte else None}


def ordnername(name):
    """Ordnername aus dem Projektnamen: ohne / und : (macOS), ohne Punkt am Anfang."""
    return re.sub(r"[/:\x00-\x1f]+", "-", nfc(name or "")).strip().lstrip(".").strip()


def zielordner(ablageort, name):
    """Wohin ein neues Projekt kommt und ob das geht (Assistent, Schritt Ablageort)."""
    vorgabe = vorgabe_ablageort()
    ablageort, ordner = Path(ablageort or vorgabe).expanduser(), ordnername(name)
    pfad = ablageort / ordner if ordner else None
    fehler = None
    if not ordner:
        fehler = "Erst einen Namen eingeben."
    elif not ablageort.is_dir() and ablageort != vorgabe:
        fehler = f"Den Speicherort {ablageort} gibt es nicht."
    elif pfad.exists() and (ist_projekt(pfad) or any(x.name != ".DS_Store" for x in pfad.iterdir())):
        fehler = f"Den Ordner „{ordner}“ gibt es dort schon. Bitte einen anderen Namen wählen."
    vorhanden = next((x for x in [ablageort, *ablageort.parents] if x.exists()), Path("/"))
    return {"pfad": str(pfad) if pfad else "", "ablageort": str(ablageort), "fehler": fehler,
            "frei": shutil.disk_usage(vorhanden).free}


def projekt_anlegen(daten):
    """Neues Projekt aus den Angaben des Assistenten anlegen (erfassung/basis.py) und gleich öffnen."""
    ziel = zielordner(daten.get("ablageort"), daten.get("name"))
    if ziel["fehler"]:
        raise ValueError(ziel["fehler"])
    v = daten.get("vorschaubilder") or {}
    if v.get("ort") == "arbeitsplatte" and not system.ist_datentraeger(Path(v.get("mountpunkt") or ""), VOLUMES):
        raise ValueError("Bitte einen angeschlossenen Datenträger für Vorschaubilder wählen.")
    angaben = {k: daten[k] for k in ("name", "kennung", "vorschaubilder", "film", "pdf", "virenscan",
                                      "personen", "referenzprojekte", "anton") if k in daten}
    lauf_aufrufen("anlegen", "--volumes", str(VOLUMES), "--daten",
                  json.dumps({"ordner": ziel["pfad"], **angaben}, ensure_ascii=False))
    antwort = projekt_oeffnen(ziel["pfad"])
    zuletzt_schreiben(zuletzt_lesen()["projekt"], zuletzt_lesen()["liste"], ziel["ablageort"])   # neue Vorgabe
    return antwort


def ordner_waehlen(daten):
    """Nativer Dialog „Ordner wählen“ (system.ordner_waehlen; die Webseite kann keinen Pfad abfragen). zweck "projekt": der
    Ordner muss ein Projekt sein; "ablageort": irgendein Ordner."""
    vorgabe = vorgabe_ablageort()
    start = Path(daten.get("start") or (vorgabe if vorgabe.is_dir() else Path.home()))
    if not start.is_dir():
        start = Path.home()
    text = {"projekt": "Projektordner wählen (enthält projekt.json)",
            "ablageort": "Speicherort für das neue Projekt wählen",
            "quelle": "Ordner wählen, der als Quelle eingelesen wird (er wird nur gelesen)"}.get(daten.get("zweck"), "Ordner wählen")
    gewaehlt = system.ordner_waehlen(text, start)
    if gewaehlt is None:                                         # Abbrechen im Dialog
        return {"abgebrochen": True}
    pfad = nfc(gewaehlt)
    if daten.get("zweck") == "projekt" and not ist_projekt(pfad):
        raise ValueError(f"{pfad} ist kein Projektordner (projekt.json fehlt).")
    return {"pfad": pfad, "name": Path(pfad).name}


def abbild_waehlen():
    """Nativer Dialog „Datei wählen“ für ein Abbild eines Mac-Datenträgers (system.datei_waehlen)."""
    gewaehlt = system.datei_waehlen("Abbild eines Datenträgers wählen (.dmg unkomprimiert, .img, .dd, .iso)",
                                    Path.home())
    if gewaehlt is None:
        return {"abgebrochen": True}
    return {"pfad": nfc(gewaehlt), "name": Path(gewaehlt).name}


def fehlertext(e):
    """Verständliche Meldungen (ValueError, RuntimeError) ohne Fehlertyp, alles andere mit Typ für die Fehlersuche."""
    return str(e) if type(e) in (ValueError, RuntimeError) else f"{type(e).__name__}: {e}"


class Anfrage(BaseHTTPRequestHandler):
    bestand: Bestand = None                           # beide None, solange kein Projekt geöffnet ist
    erfassung: Erfassung = None
    erschliessung: Erschliessung = None             # Vorlauf und Modul 3 (tool/erschliessung.py)
    pakete: Pakete = None                           # Modul 4 Bestand und Export (tool/pakete.py)
    sperre = threading.Lock()
    port = PORT
    # Sitzungs-Cookie, bei jedem Start neu: fremde Webseiten im Browser können es weder lesen noch mitschicken
    token = secrets.token_urlsafe(32)

    def log_message(self, *args):
        pass                                          # keine Zeile je Anfrage im Terminal

    def cookie_name(self):
        return f"bewertung_{self.port}"

    def zugelassen(self, url, post=False):
        """Schutz gegen fremde Webseiten (CSRF, DNS-Rebinding): nur eigene Adresse, eigenes Cookie, eigener Origin."""
        eigene = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        if self.headers.get("Host", "") not in eigene:
            return "fremde Adresse"
        if post:
            origin = self.headers.get("Origin")
            if origin is not None and origin not in {"http://" + h for h in eigene}:
                return "fremder Origin"
            if not self.headers.get("Content-Type", "").startswith("application/json"):
                return "nur JSON"
        if url.path == "/" or url.path.startswith("/web/"):
            return None                               # Startseite und Oberfläche: setzen bzw. brauchen kein Cookie
        cookies = SimpleCookie(self.headers.get("Cookie", ""))
        wert = cookies[self.cookie_name()].value if self.cookie_name() in cookies else ""
        if not secrets.compare_digest(wert, self.token):
            return "Sitzung abgelaufen, bitte die Seite neu laden"
        return None

    def abweisen(self, grund):
        self.json({"fehler": grund}, 403)

    def senden(self, status, inhalt, art="application/json; charset=utf-8", cookie=False):
        self.send_response(status)
        self.send_header("Content-Type", art)
        self.send_header("Content-Length", str(len(inhalt)))
        # Vorschaubilder ändern sich nicht und dürfen zwischengespeichert werden; Oberfläche und Daten immer frisch
        self.send_header("Cache-Control", "max-age=3600" if art.startswith("image/") else "no-store")
        if cookie:
            self.send_header("Set-Cookie", f"{self.cookie_name()}={self.token}; Path=/; HttpOnly; SameSite=Strict")
        self.end_headers()
        self.wfile.write(inhalt)

    def json(self, daten, status=200):
        self.senden(status, json.dumps(daten, ensure_ascii=False, default=str).encode())

    def datei_senden(self, wurzel, rel, cookie=False):
        """Liefert eine Datei aus wurzel; Pfade außerhalb (z. B. mit ..) werden abgewiesen."""
        wurzel = Path(wurzel).resolve()
        pfad = (wurzel / rel).resolve()
        if not pfad.is_relative_to(wurzel) or not pfad.is_file():
            return self.senden(404, b"nicht gefunden", "text/plain; charset=utf-8")
        art = mimetypes.guess_type(pfad.name)[0] or "application/octet-stream"
        if art.startswith("text/") or art in ("application/javascript",):
            art += "; charset=utf-8"
        self.senden(200, pfad.read_bytes(), art, cookie)

    def do_GET(self):
        url = urlparse(self.path)
        if grund := self.zugelassen(url):
            return self.abweisen(grund)
        q = {k: nfc(v[0]) for k, v in parse_qs(url.query, keep_blank_values=True).items()}
        b = self.bestand
        try:
            if url.path == "/":                       # Startseite mit eingesetzter Version
                seite = (WEB / "index.html").read_text(encoding="utf-8").replace("{{VERSION}}", VERSION) \
                    .replace('<html lang="de">', f'<html lang="{SPRACHE}">', 1) \
                    .replace("{{SYSTEMWOERTER}}", json.dumps(system.systemwoerter(), ensure_ascii=False))
                return self.senden(200, seite.encode(), "text/html; charset=utf-8", cookie=True)
            if url.path.startswith("/web/"):
                return self.datei_senden(WEB, unquote(url.path[5:]))
            if url.path in LIZENZTEXTE:              # „Über Balduin“: Lizenz und Zusatz nach § 7 (Entscheidung 12.11.2026)
                return self.senden(200, (CODE / LIZENZTEXTE[url.path]).read_bytes(), "text/plain; charset=utf-8")
            if url.path == "/api/projekte":
                return self.json(projekte_json())
            if url.path == "/api/aktualisierung":            # neue Version auf der Startseite (Entscheidung 14.11.2026)
                return self.json({"neu": aktualisierung(), "installiert": VERSION})
            if url.path == "/api/arbeitsplatten":
                return self.json(lauf_aufrufen("arbeitsplatten", "--volumes", str(VOLUMES)))
            if url.path == "/api/zielordner":
                return self.json(zielordner(q.get("ablageort"), q.get("name")))
            if b is None:
                return self.json({"fehler": "Kein Projekt geöffnet.", "kein_projekt": True}, 409)
            if url.path.startswith("/thumbs/"):
                return self.datei_senden(b.vorschau_ordner, unquote(url.path[8:]))
            if url.path.startswith("/etiketten/"):
                return self.datei_senden(self.erfassung.projekt / "etiketten", unquote(url.path[11:]))
            if url.path == "/api/stand":
                b.aktuell_halten()
                return self.json(b.stand_json())
            if url.path == "/api/suche":
                return self.json(b.suche(q.get("q", ""), q.get("system") == "1"))
            if url.path == "/api/erfassung":
                return self.json(self.erfassung.stand(q.get("platte") or None,
                                                     int(q["lauf"]) if q.get("lauf", "").isdigit() else None))
            if url.path == "/api/dashboard":
                return self.json(self.erfassung.dashboard())
            if url.path == "/api/datentraeger":
                return self.json(self.erfassung.datentraeger())
            if url.path == "/api/unterordner":                # Umfang wählen (Entscheidung 05.11.2026)
                return self.json(self.erfassung.unterordner(q.get("mountpunkt", ""), q.get("pfad", ""), q.get("volume_uuid")))
            # Vorlauf und Erschließung (tool/erschliessung.py)
            if url.path == "/api/vorlauf":
                b.aktuell_halten()
                return self.json(self.erschliessung.vorlauf())
            if url.path == "/api/es_platten":
                b.aktuell_halten()
                return self.json(self.erschliessung.platten())
            if url.path == "/api/boxen":
                return self.json(self.erschliessung.boxen())
            # Modul 4 Bestand und Export (tool/pakete.py)
            if url.path == "/api/export":
                b.aktuell_halten()
                return self.json(self.pakete.stand())
            if url.path == "/api/export_eintraege":
                return self.json(self.pakete.eintraege(int(q.get("paket") or 0)))
            if url.path == "/api/export_ablagen":
                return self.json(self.pakete.ablagen())
            if url.path == "/api/export_abweichungen":
                return self.json(self.pakete.abweichungen())
            if url.path == "/api/anton_stufen":
                return self.json(self.erschliessung.stufen_holen(q.get("neu") == "1"))
            if url.path == "/api/sujet_uebersetzungen":       # Übersetzungen der Sujet-Begriffe prüfen (04.11.2026)
                return self.json(self.erschliessung.uebersetzungen())
            if url.path == "/api/es_felder":                  # weitere Anton-Felder fürs Dropdown (Entscheidung 04.11.2026)
                return self.json(self.erschliessung.felder_holen(q.get("neu") == "1"))
            if url.path == "/api/es_begriffe":
                return self.json(self.erschliessung.begriffe(q.get("art", ""), q.get("q", "")))
            if url.path == "/api/es_sprachmodell":
                return self.json(self.erfassung.sprachmodell({"aktion": "modelle"}))

            platte, pfad = q.get("platte", ""), q.get("pfad", "")
            if b.platte(platte) is None:
                return self.json({"fehler": f"Datenträger {platte!r} unbekannt"}, 404)
            arten = [a for a in q.get("arten", "exakt").split(",") if a in ARTEN]
            if url.path == "/api/kinder":
                return self.json(b.kinder(platte, pfad, q.get("system") == "1", int(q.get("offset", 0))))
            if url.path == "/api/es_kinder":
                return self.json(self.erschliessung.kinder(platte, pfad, int(q.get("offset", 0))))
            if url.path == "/api/ordner":
                return self.json(b.ordner_angaben(platte, pfad))
            if url.path == "/api/quelle":
                return self.json(self.erfassung.quelle(platte, pfad))
            if url.path == "/api/galerie":
                return self.json(b.galerie(platte, pfad, int(q.get("offset", 0)), nur_personen=q.get("personen") == "1"))
            if url.path == "/api/anderswo":
                if (platte, pfad) in b.dateien:
                    return self.json({"art": "datei", "kopien": b.anderswo_datei(platte, pfad, arten)})
                return self.json({"art": "ordner", **b.anderswo_ordner(platte, pfad, arten)})
            if url.path == "/api/datei":
                if (platte, pfad) not in b.dateien:
                    return self.json({"fehler": "Datei nicht im Inventar"}, 404)
                return self.json(b.datei_angaben(platte, pfad))
            self.senden(404, b"nicht gefunden", "text/plain; charset=utf-8")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:                        # Fehler in der Oberfläche anzeigen statt abzubrechen
            self.json({"fehler": fehlertext(e)}, 500)

    def do_POST(self):
        """Schreiben und Abfragen mit Listen: Daten kommen als JSON im Rumpf."""
        url = urlparse(self.path)
        if grund := self.zugelassen(url, post=True):
            return self.abweisen(grund)
        b = self.bestand
        try:
            daten = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            ziele = [(z["platte"], nfc(z["pfad"])) for z in daten.get("ziele", [])]
            if url.path == "/api/projekt_oeffnen":
                return self.json(projekt_oeffnen(daten["pfad"]))
            if url.path == "/api/projekt_vergessen":           # Projektliste (Entscheidung 04.11.2026)
                return self.json(projekt_vergessen(daten["pfad"]))
            if url.path == "/api/projekt_verlegen":            # nicht gefundenes Projekt neu zuordnen
                try:
                    return self.json(projekt_verlegen(daten["alt"], daten["pfad"]))
                except ValueError as f:
                    return self.json({"fehler": str(f)}, 400)
            if url.path == "/api/projekt_loeschen":
                return self.json(projekt_loeschen(daten["pfad"], daten.get("name", "")))
            if url.path == "/api/projekt_anlegen":
                return self.json(projekt_anlegen(daten))
            if url.path == "/api/ordner_waehlen":
                return self.json(ordner_waehlen(daten))
            if b is None:
                return self.json({"fehler": "Kein Projekt geöffnet.", "kein_projekt": True}, 409)
            if url.path == "/api/ansicht_merken":              # zuletzt genutztes Modul je Projekt
                try:
                    return self.json(ansicht_merken(self.erfassung.info["ordner"], daten.get("ansicht")))
                except ValueError as f:
                    return self.json({"fehler": str(f)}, 400)
            if url.path == "/api/projekt_einstellungen":
                return self.json(self.erfassung.einstellungen_aendern(daten))
            if url.path == "/api/entscheiden":
                return self.json(b.entscheiden(ziele, daten.get("entscheidung"), daten.get("vorbehalt", False),
                                               daten.get("begruendung", ""), daten.get("wer", ""),
                                               daten.get("bestaetigt", False), daten.get("mit_ausnahmen", False),
                                               daten.get("fassungen")))
            if url.path == "/api/hinweis":
                return self.json(b.hinweis_setzen(daten["platte"], daten["pfad"], daten.get("hinweis", ""),
                                                  daten.get("wer", "")))
            if url.path == "/api/erfassen":
                return self.json(self.erfassung.starten(daten))
            if url.path == "/api/bericht":
                return self.json(self.erfassung.bericht_speichern())
            if url.path == "/api/bericht_zeigen":
                return self.json(self.erfassung.bericht_zeigen(daten.get("datei", "")))
            if url.path == "/api/platte_lauf":
                return self.json(self.erfassung.platte_starten(daten))
            if url.path == "/api/platte_angaben":
                return self.json(self.erfassung.angaben_aendern(daten))
            if url.path == "/api/platte_herausnehmen":
                return self.json(self.erfassung.herausnehmen(daten))
            if url.path == "/api/abbrechen":
                return self.json(self.erfassung.abbrechen(int(daten["lauf_id"])))
            if url.path == "/api/fortsetzen":
                return self.json(self.erfassung.fortsetzen(int(daten["lauf_id"]), daten.get("passwort")))
            if url.path == "/api/entfernen":
                return self.json(self.erfassung.entfernen(int(daten["lauf_id"])))
            if url.path == "/api/anton_holen":
                return self.json(self.erfassung.anton_starten())
            if url.path == "/api/anton":
                return self.json(self.erfassung.anton_aktion(daten))
            if url.path == "/api/macgeraet_pruefen":
                return self.json(self.erfassung.macgeraet_pruefen(daten))
            if url.path == "/api/abbild_pruefen":
                return self.json(self.erfassung.abbild_pruefen(daten))
            if url.path == "/api/passwort_pruefen":
                return self.json(self.erfassung.passwort_pruefen(daten))
            if url.path == "/api/abbild_waehlen":
                return self.json(abbild_waehlen())
            if url.path in ("/api/quellordner_pruefen", "/api/quellordner_verlegen"):
                return self.json(self.erfassung.quellordner({**daten, "verlegen": url.path.endswith("verlegen")}))
            if url.path == "/api/ohne_schreibschutz":
                return self.json(self.erfassung.ohne_schreibschutz_zustimmen(daten.get("platte_id")))
            if url.path == "/api/einhaengen":
                mp = self.erfassung.quellpfad_pruefen(daten["mountpunkt"])
                return self.json(self.erfassung.aufrufen("einhaengen", "--mountpunkt", str(mp)))
            if url.path == "/api/zeigen":
                return self.json(self.erfassung.original_zeigen(daten["platte"], nfc(daten["pfad"])))
            if url.path == "/api/einstellung":
                return self.json(b.einstellung_setzen(daten["schluessel"], bool(daten["an"])))
            if url.path == "/api/regeln":
                return self.json(b.regeln_angaben(ziele, int(daten.get("grenze", 300)), max(2, int(daten.get("jedes", 10)))))
            if url.path == "/api/regel_anwenden":
                return self.json(b.regel_anwenden(ziele, daten["regel"], daten.get("entscheidung", "kassieren"),
                                                  daten.get("endungen", []), int(daten.get("grenze", 300)),
                                                  daten.get("wer", ""), daten.get("bestaetigt", False),
                                                  int(daten.get("jedes", 10))))
            if url.path == "/api/regel_zuruecknehmen":
                return self.json(b.regel_zuruecknehmen(ziele, daten["begruendung"]))
            if url.path == "/api/knoten":
                return self.json([b.knoten_angaben(p, pf) for p, pf in ziele
                                  if (p, pf) in b.dateien or (p, pf) in b.zaehler])
            if url.path == "/api/es_angaben":
                return self.json(self.erschliessung.angaben(ziele))
            if url.path == "/api/es_speichern":
                return self.json(self.erschliessung.speichern(ziele, daten.get("felder", {}), daten.get("wer", ""),
                                                              daten.get("angenommen", []), set(daten.get("nur_leere", []))))
            if url.path == "/api/es_metadaten":                # weitere Metadaten (Entscheidung 04.11.2026)
                return self.json(self.erschliessung.metadaten_uebersicht(ziele))
            if url.path == "/api/es_metadaten_uebernehmen":
                return self.json(self.erschliessung.metadaten_uebernehmen(
                    ziele, daten["schluessel"], daten["feld"], daten.get("modus", "je"), daten.get("wert", ""),
                    bool(daten.get("nur_leere")), daten.get("wer", "")))
            if url.path == "/api/es_vorschlag_mehrere":        # fünfte Feedbackrunde (04.11.2026)
                return self.json(self.erschliessung.vorschlag_mehrere(
                    ziele, daten["feld"], daten["vorschlag"], daten.get("modus", "mit"),
                    bool(daten.get("ueberschreiben")), daten.get("wer", "")))
            if url.path in ("/api/es_vererben_pruefen", "/api/es_vererben"):      # Entscheidung 04.11.2026
                platte, pfad, umfang = daten["platte"], nfc(daten["pfad"]), daten.get("umfang", {})
                if url.path == "/api/es_vererben_pruefen":
                    return self.json(self.erschliessung.vererben_pruefen(platte, pfad, daten.get("felder", []), umfang))
                return self.json(self.erschliessung.vererben(platte, pfad, daten.get("felder", []), umfang,
                                                             bool(daten.get("ueberschreiben")), daten.get("wer", ""),
                                                             daten.get("zeitraum_je_datei")))
            if url.path == "/api/es_verwerfen":
                return self.json(self.erschliessung.verwerfen(daten["platte"], nfc(daten["pfad"]), daten["vorschlag"]))
            if url.path == "/api/es_suche":
                b.aktuell_halten()
                return self.json(self.erschliessung.suche(daten))
            if url.path == "/api/es_abgleichen":
                return self.json(self.erschliessung.abgleichen(
                    {"platte": daten["quelle"]["platte"], "pfad": nfc(daten["quelle"]["pfad"])},
                    [{"platte": z["platte"], "pfad": nfc(z["pfad"])} for z in daten.get("gewaehlt", [])],
                    [{"platte": z["platte"], "pfad": nfc(z["pfad"])} for z in daten.get("abgewaehlt", [])],
                    daten.get("felder", ["titel"])))
            if url.path == "/api/es_zuordnen_pruefen":
                return self.json(self.erschliessung.zuordnen_pruefen(ziele, daten.get("ziel", ""), daten.get("stufen", {})))
            if url.path == "/api/es_zuordnen":
                return self.json(self.erschliessung.zuordnen(ziele, daten.get("ziel", ""), daten.get("stufen", {}),
                                                              namen=daten.get("namen", {})))
            if url.path == "/api/es_zuordnung_stufe":
                return self.json(self.erschliessung.zuordnung_stufe(daten["platte"], nfc(daten["pfad"]), daten.get("stufe_name", "")))
            if url.path == "/api/es_zuordnung_loesen":       # ein Element, eine Auswahl (ziele) oder eine Herkunftsgruppe
                if "ziele" in daten:
                    return self.json(self.erschliessung.zuordnungen_loesen(ziele=ziele))
                if "ziel" in daten:
                    return self.json(self.erschliessung.zuordnungen_loesen(
                        ziel=daten["ziel"], platte=daten["platte"], ordner=nfc(daten.get("ordner", ""))))
                return self.json(self.erschliessung.zuordnung_loesen(daten["platte"], nfc(daten["pfad"])))
            if url.path == "/api/ebene_anlegen":
                return self.json(self.erschliessung.ebene_anlegen(daten))
            if url.path == "/api/ebene_entfernen":
                return self.json(self.erschliessung.ebene_entfernen(int(daten["ebene_id"])))
            if url.path == "/api/es_sprachmodell":
                return self.json(self.erschliessung.sprachmodell(daten["platte"], nfc(daten["pfad"])))
            if url.path == "/api/sujet_uebersetzungen":
                return self.json(self.erschliessung.uebersetzungen_speichern(daten.get("liste", [])))
            if url.path == "/api/es_einstellungen":
                return self.json(self.erfassung.einstellungen_aendern(
                    {k: daten[k] for k in ("sprachmodell", "uebersetzung") if k in daten}))
            if url.path == "/api/vorlauf_einstellungen":
                return self.json(self.erschliessung.vorlauf_einstellen(daten))
            if url.path == "/api/export_planen":
                return self.json(self.pakete.planen(bool(daten.get("verwerfen_ok")), daten.get("wer", "")))
            if url.path == "/api/export_starten":
                return self.json(self.pakete.starten(daten))
            if url.path == "/api/export_zeigen":
                return self.json(self.pakete.zeigen(daten.get("paket_id"), bool(daten.get("bericht"))))
            if url.path == "/api/export_einstellungen":
                return self.json(self.pakete.einstellen(daten))
            if url.path == "/api/export_ablage":
                return self.json(self.pakete.ablage_setzen(daten.get("mountpunkt", "")))
            if url.path == "/api/export_quittieren":
                return self.json(self.pakete.quittieren(daten.get("platte_id", ""), daten.get("wer", "")))
            if url.path == "/api/export_importformat":
                return self.json(self.pakete.importformat_abfragen())
            if url.path == "/api/export_uebergeben":
                return self.json(self.pakete.uebergeben(daten))
            if url.path == "/api/export_zuruecknehmen":
                return self.json(self.pakete.zuruecknehmen(daten.get("paket_id")))
            if url.path == "/api/export_kontrolle":
                return self.json(self.pakete.kontrolle())
            if url.path == "/api/export_datei_loeschen":
                return self.json(self.pakete.datei_loeschen(daten.get("paket_id")))
            if url.path == "/api/export_bericht":
                return self.json(self.pakete.bericht())
            if url.path == "/api/vorlauf_starten":
                return self.json(self.erschliessung.vorlauf_starten(daten.get("schritte")))
            if url.path == "/api/box_laden":
                return self.json(self.erschliessung.box_laden(daten.get("kennung", "")))
            if url.path == "/api/box_entfernen":
                return self.json(self.erschliessung.box_entfernen(int(daten["anton_id"])))
            if url.path == "/api/editor":
                angaben = [{"platte": p, "pfad": pf, "urteil": b.urteil(p, pf),
                            "darueber": b.urteil(p, elternordner(pf)) if pf else None} for p, pf in ziele]
                einzeln = b.entscheidung_angaben(*ziele[0]) if len(ziele) == 1 else None
                return self.json({"ziele": angaben, "einzeln": einzeln})
            self.senden(404, b"nicht gefunden", "text/plain; charset=utf-8")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as e:
            self.json({"fehler": fehlertext(e)}, 500)


class BalduinServer(ThreadingHTTPServer):
    """HTTP-Server nur auf 127.0.0.1. Unter Windows belegt er den Port exklusiv: mit SO_REUSEADDR könnten dort zwei
    Balduins denselben Port öffnen, und der zweite Doppelklick fände den ersten nicht."""

    def server_bind(self):
        if system.port_exklusiv(self.socket):
            self.allow_reuse_address = False
        super().server_bind()


def main():
    global ARBEITSPLATTE, VOLUMES, PROJEKTE, ZULETZT
    parser = argparse.ArgumentParser(description="Balduin starten")
    parser.add_argument("--projekt", type=Path, help="dieses Projekt gleich öffnen (sonst Startbildschirm)")
    parser.add_argument("--port", default=PORT, type=int)
    parser.add_argument("--arbeitsplatte", type=Path, help="Tests: Datenträger für Vorschaubilder statt dem aus projekt.json")
    parser.add_argument("--volumes", default=VOLUMES, type=Path, help="Tests: Ordner mit den Datenträgern")
    parser.add_argument("--projekte", default=PROJEKTE, type=Path, help="Tests: Vorgabe-Speicherort neuer Projekte")
    parser.add_argument("--zuletzt", default=ZULETZT, type=Path, help="Tests: Liste der zuletzt geöffneten Projekte")
    parser.add_argument("--kein-browser", action="store_true", help="Browser nicht automatisch öffnen")
    args = parser.parse_args()
    for name, wert in system.paket_umgebung().items():    # Paket: Siegfried und ClamAV finden ihre Dateien in bin/
        os.environ.setdefault(name, wert)
    ARBEITSPLATTE, VOLUMES, PROJEKTE, ZULETZT = args.arbeitsplatte, args.volumes, args.projekte, args.zuletzt
    Anfrage.port = args.port
    if args.projekt:
        try:
            projekt_oeffnen(args.projekt)
        except (ValueError, RuntimeError) as e:
            raise SystemExit(str(e))
        if not Anfrage.bestand.vorschau_ordner.is_dir():
            print(f"⚠ Vorschaubilder nicht erreichbar ({Anfrage.bestand.vorschau_ordner}). Ist der Datenträger für Vorschaubilder angeschlossen?")
    adresse = f"http://127.0.0.1:{args.port}/"
    try:
        server = BalduinServer(("127.0.0.1", args.port), Anfrage)
    except OSError as e:
        if not system.port_belegt(e):
            raise
        # Port belegt: Läuft dort schon Balduin (zweiter Doppelklick, altes Fenster), nur den Browser dorthin öffnen.
        try:
            with urllib.request.urlopen(adresse, timeout=3) as antwort:
                laeuft_schon = b"<title>Balduin</title>" in antwort.read(2000)
        except OSError:
            laeuft_schon = False
        if not laeuft_schon:
            raise SystemExit(f"Port {args.port} ist von einem anderen Programm belegt. Bitte das Programm beenden "
                             f"oder Balduin mit --port <Nummer> starten.")
        print(f"Balduin läuft bereits: {adresse}  (im anderen Terminalfenster). Der Browser wird dorthin geöffnet.")
        if not args.kein_browser:
            webbrowser.open(adresse)
        return
    print(f"Balduin läuft: {adresse}  (beenden mit Ctrl+C oder Fenster schließen)")
    if not args.kein_browser:
        webbrowser.open(adresse)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBeendet.")


if __name__ == "__main__":
    main()

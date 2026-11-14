"""Grundlagen der Erfassung (bisher Notebook 1, Abschnitt A): Projekt, Datenbank, Hilfsfunktionen, Speicherplatz.

Alle Schritte des Pakets arbeiten mit dem Projekt, das `oeffnen()` einstellt (Objekt `P`, Pfade als Attribute).
Die übrigen Dateien holen sich alles von hier mit `from .basis import *`, wie früher Abschnitt A im Notebook.
"""
import csv
import hashlib
import json
import os
import random
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
import unicodedata
from contextlib import closing, contextmanager
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
import urllib.error
import urllib.request

import numpy as np
import pandas as pd

from vorlauf.schema import SCHEMA_VORLAUF
from erfassung import system
from export.schema import SCHEMA_EXPORT, tabellen_umstellen

CODE = Path(__file__).resolve().parent.parent        # Ordner mit Tool, Notebooks und vorgaben/ (im Git)
MODELLE = CODE / "modelle"                           # Modelle der Bildanalyse (nicht im Git; werkzeuge/modelle_laden.py)
PROJEKTE = system.projekte_vorgabe()                 # Vorgabe-Speicherort für Projekte (Git: neben dem Code)
ZULETZT = system.zuletzt_datei()                     # zuletzt geöffnete Projekte; schreibt das Tool
PROJEKT_DATEI = "projekt.json"

# Ordner, die der Scan überspringt (Verwaltungsordner von macOS und Windows)
SYSTEMORDNER = {".Spotlight-V100", ".fseventsd", ".Trashes", ".TemporaryItems",
                ".DocumentRevisions-V100", "$RECYCLE.BIN", "System Volume Information"}
# Dateien, die beim Plattenvergleich nicht mitzählen
SYSTEMDATEIEN = {".DS_Store", "Thumbs.db", "desktop.ini", ".localized"}
MIN_GROESSE_VERGLEICH = 1024          # Bytes; kleinere Dateien zählen beim Vergleich nicht
# Änderungsdaten vor 1980 oder nach heute gelten als defekte Zeitstempel (z. B. Jahr 60000)
MTIME_AB = datetime(1980, 1, 1).timestamp()
VOLUMES = system.VOLUMES               # macOS /Volumes, Windows die Laufwerksbuchstaben (Übersicht in B)

# Ordner neuer Projekte auf Arbeitsplatte und Ablage (<ARBEITSORDNER>/<Projekt>/vorschauen bzw. …/export);
# bestehende Projekte behalten den in projekt.json gespeicherten Ordner (Entscheidung 12.11.2026)
ARBEITSORDNER = "Balduin-Projekte"

# Einstellungen eines neuen Projekts (projekt.json); der Assistent im Tool fragt sie ab
VORGABEN_PROJEKT = {
    "format": 1,
    "name": "",
    "angelegt_am": "",
    "kennung": "HD",                                  # Kennungen der Datenträger: Kürzel + zwei Ziffern (HD01, HD02 …)
    "vorschaubilder": {"ort": "projekt"},             # oder {"ort": "arbeitsplatte", "volume_uuid", "volume_name", "ordner"}
    "film": {"art": "webp", "bilder": 10},            # animiertes WebP mit n Bildern oder "raster" (2 × 2 Standbilder)
    "pdf": {"art": "seite", "seiten": 10, "bereich": "1–5"},   # "seite" (erste Seite als JPEG), "webp" (n Seiten über das
                                                      # Dokument verteilt) oder "bereich" (Seiten von–bis), beide animiertes WebP
    "speicher": {"min_frei_gb": 10},                   # feste Reserve auf dem Laufwerk des Projekts, nicht im Tool
                                                      # einstellbar (Entscheidung 12.11.2026; Tests: 1)
    "virenscan": True,
    "personen": False,                                # F5 Personen auf Fotos erkennen (Vorschaubilder, vor der Bewertung)
    "referenzprojekte": [],                           # [{"pfad", "name"}]; der Abgleich mit ihnen folgt
    "anton": {"url": "", "testinstanz": False},       # Anton-Server (Pflicht, keine Vorgabe); Token im Schlüsselbund;
                                                  # testinstanz: Übergaben dorthin gelten als Probe (Entscheidung 12.11.2026)
    # Vorlauf (Einstellungen direkt in seiner Ansicht): Schritte an/aus, Umfang "uebernommen" oder "alles"
    "vorlauf": {"umfang": "uebernommen", "schritte": {"V5": True, "V7": True, "V8": True, "V10": True}},
    # Sprachmodell auf Abruf in der Erschließung (Zahnrad); nur lokal, Cloud gesperrt bis zur Freigabe (Regel 6)
    "sprachmodell": {"anbieter": "ollama", "adresse": "http://127.0.0.1:11434", "modell": "qwen2.5:14b"},
    # Übersetzung der allgemeinen Sujet-Begriffe (V3, Entscheidung 04.11.2026): weg „sprachmodell“ (Einstellung oben,
    # Vorgabe Ollama lokal) oder „mymemory“ (kostenlos; mit E-Mail 50.000 Zeichen am Tag); sprache = Sprache des Archivs
    "uebersetzung": {"weg": "sprachmodell", "sprache": "de", "email": ""},
    # Modul 4 (Entscheidung 05.11.2026): Ablage der Pakete (ort "" = noch nicht gewählt, "projekt" = export/ im
    # Projekt, "platte" = beschreibbarer Datenträger mit volume_uuid, volume_name, ordner); je Paket höchstens so viele
    # Dateien (100–10000) und, wenn gb_je_paket > 0, höchstens so viele GB
    "export": {"ablage": {"ort": ""}, "dateien_je_paket": 5000, "gb_je_paket": 0},
}


def datentraeger_info(pfad):
    """Angaben zur Platte mit den Schlüsseln von diskutil (erfassung/system.py, auch für Windows)."""
    return system.datentraeger_info(pfad)


def volume_uuid(pfad):
    info = datentraeger_info(pfad)
    return info.get("VolumeUUID") or info.get("DiskUUID") or ""


def arbeitsplatte_finden(angaben, volumes=VOLUMES):
    """Mountpunkt der Arbeitsplatte, wiedergefunden über die Volume-UUID (gleichnamige Platten hängt macOS z. B. als
    „Arbeit 1“ ein); ohne UUID über den Namen. Nicht angeschlossen: der vermutete Pfad, der dann nicht existiert."""
    vermutet = system.vermuteter_mountpunkt(angaben.get("volume_name", "Arbeitsplatte"), volumes)
    uuid = angaben.get("volume_uuid")
    if not uuid:
        return vermutet
    andere = [e for e in system.datentraeger_liste(volumes) if e != vermutet]
    for eintrag in [vermutet, *andere]:
        if eintrag.is_dir() and not eintrag.is_symlink() and uuid in system.kennungen(datentraeger_info(eintrag)):
            return eintrag
    return vermutet


def einstellungen_mischen(vorgabe, angaben):
    """Ergänzt fehlende Einstellungen aus den Vorgaben (auch in verschachtelten Angaben wie speicher)."""
    ergebnis = json.loads(json.dumps(vorgabe))       # tiefe Kopie: Änderungen dürfen die Vorgaben nicht verändern
    for k, v in (angaben or {}).items():
        ergebnis[k] = einstellungen_mischen(vorgabe[k], v) if isinstance(v, dict) and isinstance(vorgabe.get(k), dict) else v
    return ergebnis


class Projekt:
    """Pfade und Einstellungen des geöffneten Projekts (projekt.json). Ein Projekt ist ein Ordner mit eigener Datenbank,
    eigener Kopie der Regeltabellen und eigenen Arbeitsordnern (Entscheidungen 29. und 30.10.2026)."""

    def setze(self, ordner, arbeitsplatte=None, volumes=VOLUMES):
        self.ordner = Path(ordner).expanduser().resolve()
        datei = self.ordner / PROJEKT_DATEI
        if not datei.is_file():
            raise FileNotFoundError(f"{self.ordner} ist kein Projektordner ({PROJEKT_DATEI} fehlt).")
        self.einstellungen = einstellungen_mischen(VORGABEN_PROJEKT, json.loads(datei.read_text(encoding="utf-8")))
        e = self.einstellungen
        self.name = e["name"] or self.ordner.name
        self.db_pfad = self.ordner / "inventar.sqlite"
        self.berichte = self.ordner / "berichte"
        self.logs = self.ordner / "logs"
        self.etiketten = self.ordner / "etiketten"       # Fotos der Plattenetiketten
        self.anton = self.ordner / "anton"               # Bestand aus Anton für den Abgleich (G5)
        self.siegfried = self.ordner / "siegfried"       # begrenzter Signatursatz für Siegfried (D2), von roy gebaut
        # Regeltabellen (archivformate.csv, nara/): Kopie im Projekt vom Anlegen, sonst die aus dem Git
        eigene = self.ordner / "vorgaben"
        self.vorgaben = eigene if (eigene / "archivformate.csv").exists() else CODE / "vorgaben"
        self.volumes = Path(volumes)                     # Datenträger des Rechners (system.VOLUMES; Tests: ein Ordner)
        # Vorschaubilder: im Projekt oder auf einer Arbeitsplatte (kein Quellbestand, dort nur im eigenen Ordner schreiben)
        v = e["vorschaubilder"]
        self.arbeitsplatte_test = Path(arbeitsplatte) if arbeitsplatte else None    # nur Tests: statt der UUID-Suche
        if v["ort"] == "arbeitsplatte":
            self.arbeitsplatte = self.arbeitsplatte_test or arbeitsplatte_finden(v, self.volumes)
            self.vorschauen = self.arbeitsplatte / v["ordner"]
        else:
            self.arbeitsplatte = None
            self.vorschauen = self.ordner / "vorschauen"
        # so viel bleibt auf dem Laufwerk des Projekts frei; ältere projekt.json nennen noch budget_gb und
        # arbeitsplatte_gb, die nicht mehr gelten (Entscheidung 12.11.2026)
        self.min_frei_gb = float(e["speicher"]["min_frei_gb"])
        self.virenscan = bool(e["virenscan"])
        self.personen = bool(e["personen"])
        self.film_art, self.film_bilder = e["film"]["art"], int(e["film"]["bilder"])
        self.pdf_art, self.pdf_seiten = e["pdf"]["art"], int(e["pdf"]["seiten"])
        self.pdf_bereich = seitenbereich(e["pdf"].get("bereich") or "1–5")        # (von, bis)
        self.kennung = e["kennung"]
        self.anton_url = e["anton"]["url"].rstrip("/")
        self.sicherungen = self.ordner / "sicherungen"   # Sicherung der Datenbank vor jedem Export (Modul 4)
        # Ablage der Pakete (Modul 4): None = nicht gewählt; auf einer Platte nur im eigenen Ordner schreiben
        a = e["export"]["ablage"]
        if a.get("ort") == "platte":
            wurzel = arbeitsplatte_finden(a, self.volumes)
            self.export = wurzel / a["ordner"]
            self.export_wurzel = wurzel
        elif a.get("ort") == "projekt":
            self.export, self.export_wurzel = self.ordner / "export", self.ordner
        else:
            self.export = self.export_wurzel = None

    def __repr__(self):
        return f"Projekt({getattr(self, 'ordner', 'nicht geöffnet')})"


P = Projekt()


def zuletzt_geoeffnet():
    """Projektordner, der zuletzt im Tool offen war."""
    try:
        return Path(json.loads(ZULETZT.read_text(encoding="utf-8"))["projekt"])
    except (OSError, ValueError, KeyError):
        raise FileNotFoundError("Noch kein Projekt in Balduin geöffnet. Projekt in Balduin anlegen oder öffnen, "
                                "oder den Projektordner angeben.") from None


def oeffnen(ordner=None, arbeitsplatte=None, volumes=VOLUMES):
    """Öffnet ein Projekt für alle Schritte: legt die Arbeitsordner und die Tabellen an (fehlende Spalten werden
    nachgerüstet). ordner=None: das zuletzt im Tool geöffnete Projekt. arbeitsplatte: nur für Tests (statt der
    Arbeitsplatte aus projekt.json)."""
    P.setze(ordner or zuletzt_geoeffnet(), arbeitsplatte, volumes)
    for ordner in (P.berichte, P.logs, P.etiketten, P.anton):
        ordner.mkdir(parents=True, exist_ok=True)
    if P.arbeitsplatte is None:
        P.vorschauen.mkdir(exist_ok=True)
    datenbank_einrichten()
    return P


# Namen, die nur auf diesem Rechner auflösen (Entscheidung 06.11.2026): dorthin darf Anton auch über http.
# Steht in erfassung/system.py, damit auch der Server (nur Standardbibliothek) sie nutzen kann.
LOKALE_NAMEN, LOKALE_ENDUNGEN, nur_lokal = system.LOKALE_NAMEN, system.LOKALE_ENDUNGEN, system.nur_lokal


def einstellungen_pruefen(e):
    """Prüft Einstellungen wie in projekt.json; Fehler als ValueError mit verständlichem Text."""
    if not (e["name"] or "").strip():
        raise ValueError("Das Projekt braucht einen Namen.")
    if not re.fullmatch(r"[A-Za-z]{1,6}", e["kennung"] or ""):
        raise ValueError("Das Kürzel der Kennungen besteht aus 1 bis 6 Buchstaben (z. B. HD).")
    if e["film"]["art"] not in ("webp", "raster") or not 2 <= int(e["film"]["bilder"]) <= 60:
        raise ValueError("Filmvorschau: animiertes WebP mit 2 bis 60 Bildern oder Raster.")
    if e["pdf"]["art"] not in ("seite", "webp", "bereich") or not 2 <= int(e["pdf"]["seiten"]) <= 60:
        raise ValueError("PDF-Vorschau: erste Seite, animiertes WebP mit 2 bis 60 Seiten oder ein Seitenbereich.")
    if e["pdf"]["art"] == "bereich":
        seitenbereich(e["pdf"].get("bereich"))           # wirft mit verständlichem Text
    if float(e["speicher"]["min_frei_gb"]) <= 0:
        raise ValueError("Die Reserve an freiem Platz (speicher.min_frei_gb) muss größer als 0 sein.")
    if not (e["anton"]["url"] or "").strip():
        raise ValueError("Anton-Server: bitte die Adresse angeben, z. B. https://archiv.example.org.")
    url = urlparse(e["anton"]["url"])
    if not (url.hostname and (url.scheme == "https" or (url.scheme == "http" and nur_lokal(url.hostname)))
            and url.path in ("", "/") and not (url.query or url.username)):
        raise ValueError("Anton-Server: Adresse wie https://archiv.example.org, ohne Pfad; http nur für eine "
                         "Testinstanz auf diesem Rechner (localhost, *.test, *.ddev.site).")
    if e["vorlauf"]["umfang"] not in ("uebernommen", "alles"):
        raise ValueError("Umfang des Vorlaufs: nur Übernommenes oder alles.")
    s = e["sprachmodell"]
    if s["anbieter"] != "ollama" or urlparse(s["adresse"] or "").hostname not in ("127.0.0.1", "localhost"):
        raise ValueError("Sprachmodell: nur Ollama auf diesem Rechner (Cloud-Modelle erst nach Freigabe durch das Archiv).")
    if not (s["modell"] or "").strip():
        raise ValueError("Sprachmodell: bitte ein Modell wählen.")
    x = e["export"]
    if not 100 <= int(x["dateien_je_paket"]) <= 10000:
        raise ValueError("Export: 100 bis 10000 Dateien je Paket (Absprache mit dem Betreiber der Anton-Instanz).")
    if not (float(x["gb_je_paket"]) == 0 or 1 <= float(x["gb_je_paket"]) <= 5000):
        raise ValueError("Export: Größe je Paket 0 (ohne Grenze) oder 1 bis 5000 GB.")
    if x["ablage"].get("ort") not in ("", "projekt", "platte"):
        raise ValueError("Export: Ablage nur im Projekt oder auf einem Datenträger.")


# im Tool änderbar (Zahnrad des Projekts vorn in der Kopfleiste: Name, Kürzel, Anton; Zahnrad an Registrierung/Analyse: das Übrige;
# Vorlauf in seiner Ansicht, Sprachmodell im Zahnrad der
# Erschließung); der Ort der Vorschaubilder nicht
AENDERBAR = ("name", "kennung", "film", "pdf", "virenscan", "personen", "referenzprojekte", "anton",
             "vorlauf", "sprachmodell", "uebersetzung", "export")


def einstellungen_aendern(aenderungen):
    """Ändert Einstellungen des geöffneten Projekts in projekt.json; jede geänderte Angabe kommt ins Protokoll.
    Das Kürzel nur, solange keine Platte registriert ist (sonst passten Kennungen und Kürzel nicht mehr zusammen)."""
    fremd = set(aenderungen) - set(AENDERBAR)
    if fremd:
        raise ValueError(f"Nicht in Balduin änderbar: {', '.join(sorted(fremd))}")
    alt = P.einstellungen
    neu = einstellungen_mischen(alt, aenderungen)
    neu["name"] = (neu["name"] or "").strip()
    neu["kennung"] = (neu["kennung"] or "").strip().upper()
    neu["film"]["bilder"] = int(neu["film"]["bilder"])
    neu["pdf"]["seiten"] = int(neu["pdf"]["seiten"])
    neu["pdf"]["bereich"] = "–".join(map(str, seitenbereich(neu["pdf"].get("bereich") or "1–5")))
    neu["virenscan"] = bool(neu["virenscan"])
    neu["personen"] = bool(neu["personen"])
    neu["anton"]["url"] = (neu["anton"]["url"] or "").strip().rstrip("/")
    neu["anton"]["testinstanz"] = bool(neu["anton"].get("testinstanz"))
    neu["vorlauf"]["schritte"] = {str(k): bool(v) for k, v in neu["vorlauf"]["schritte"].items()}
    neu["sprachmodell"] = {k: str(neu["sprachmodell"][k] or "").strip() for k in ("anbieter", "adresse", "modell")}
    neu["uebersetzung"] = {k: str(neu["uebersetzung"].get(k) or "").strip() for k in ("weg", "sprache", "email")}
    if neu["uebersetzung"]["weg"] not in ("sprachmodell", "mymemory"):
        raise ValueError("Übersetzung: nur „sprachmodell“ oder „mymemory“")
    neu["uebersetzung"]["sprache"] = (neu["uebersetzung"]["sprache"] or "de").lower()[:5]
    neu["export"] = {"ablage": alt["export"]["ablage"], "dateien_je_paket": int(neu["export"]["dateien_je_paket"]),
                     "gb_je_paket": round(float(neu["export"]["gb_je_paket"]), 1)}   # die Ablage nur über export_ablage_setzen
    neu["referenzprojekte"] = [{"pfad": str(r["pfad"]), "name": r.get("name") or Path(r["pfad"]).name}
                               for r in neu["referenzprojekte"] if Path(r["pfad"]).resolve() != P.ordner]
    einstellungen_pruefen(neu)
    if neu["kennung"] != alt["kennung"]:
        with db() as con:
            if con.execute("SELECT COUNT(*) FROM platte").fetchone()[0]:
                raise ValueError("Das Kürzel lässt sich nur ändern, solange kein Datenträger registriert ist.")
    geaendert = [k for k in AENDERBAR if neu[k] != alt[k]]
    if geaendert:
        datei = P.ordner / PROJEKT_DATEI
        zwischen = datei.with_suffix(".tmp")
        zwischen.write_text(json.dumps(neu, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(zwischen, datei)
        for k in geaendert:
            protokolliere("Projekt", P.name, k, json.dumps(alt[k], ensure_ascii=False), json.dumps(neu[k], ensure_ascii=False))
        P.setze(P.ordner, P.arbeitsplatte_test, P.volumes)
    return {"geaendert": geaendert}


def seitenbereich(text):
    """„1–5“, „3-7“ oder „4“ → (von, bis); höchstens 60 Seiten (PDF-Vorschau, Entscheidung 04.11.2026)."""
    m = re.fullmatch(r"\s*(\d{1,4})\s*(?:[-–—]\s*(\d{1,4}))?\s*", str(text or ""))
    von, bis = (int(m[1]), int(m[2] or m[1])) if m else (0, 0)
    if not m or not 1 <= von <= bis or bis - von >= 60:
        raise ValueError("PDF-Seitenbereich bitte wie „1–5“ angeben (ab Seite 1, höchstens 60 Seiten).")
    return von, bis


def vorschaubilder_verlegen(mountpunkt):
    """Nachträglich eine Arbeitsplatte für die Vorschaubilder wählen (Entscheidung 04.11.2026), nur solange im Projekt
    noch keine Vorschaubilder entstanden sind; das Verlegen vorhandener folgt als eigener Hintergrundlauf."""
    if P.arbeitsplatte is not None:
        raise ValueError("Die Vorschaubilder liegen schon auf einem eigenen Datenträger.")
    with db() as con:
        n = con.execute("SELECT COUNT(*) FROM vorschau WHERE datei IS NOT NULL AND datei != ''").fetchone()[0]
    vorhanden = P.vorschauen.is_dir() and any(x.is_file() for x in P.vorschauen.rglob("*"))
    if n or vorhanden:
        raise ValueError("Es gibt schon Vorschaubilder im Projekt. Sie auf einen anderen Datenträger zu verlegen, folgt "
                         "in einer späteren Fassung.")
    mountpunkt = Path(mountpunkt or "")
    if not mountpunkt.is_dir() or not os.access(mountpunkt, os.W_OK):
        raise ValueError(f"Der Datenträger {mountpunkt} ist nicht angeschlossen oder nicht beschreibbar.")
    info = datentraeger_info(mountpunkt)
    alt = P.einstellungen["vorschaubilder"]
    neu_v = {"ort": "arbeitsplatte", "volume_uuid": info.get("VolumeUUID") or info.get("DiskUUID") or "",
             "volume_name": info.get("VolumeName") or mountpunkt.name, "ordner": f"{ARBEITSORDNER}/{P.ordner.name}/vorschauen"}
    neu = {**P.einstellungen, "vorschaubilder": neu_v}
    datei = P.ordner / PROJEKT_DATEI
    zwischen = datei.with_suffix(".tmp")
    zwischen.write_text(json.dumps(neu, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(zwischen, datei)
    protokolliere("Projekt", P.name, "vorschaubilder", json.dumps(alt, ensure_ascii=False), json.dumps(neu_v, ensure_ascii=False))
    P.setze(P.ordner, P.arbeitsplatte_test, P.volumes)
    return {"ok": True, "vorschaubilder": neu_v}


def projekt_anlegen(ordner, angaben):
    """Legt einen Projektordner an: projekt.json, Kopie der Regeltabellen, Arbeitsordner und leere Datenbank.
    angaben: Einstellungen wie VORGABEN_PROJEKT; für eine Arbeitsplatte genügt {"ort": "arbeitsplatte", "mountpunkt"}."""
    ordner = Path(ordner).expanduser().resolve()
    if (ordner / PROJEKT_DATEI).exists():
        raise ValueError(f"In {ordner} liegt schon ein Projekt.")
    if ordner.exists() and any(x.name != ".DS_Store" for x in ordner.iterdir()):
        raise ValueError(f"{ordner} ist nicht leer. Bitte einen neuen Ordnernamen oder einen leeren Ordner wählen.")
    e = einstellungen_mischen(VORGABEN_PROJEKT, angaben)
    e["name"] = (e["name"] or "").strip()
    e["anton"]["url"] = (e["anton"]["url"] or "").strip().rstrip("/")
    e["angelegt_am"] = jetzt()
    einstellungen_pruefen(e)
    v = e["vorschaubilder"]
    if v.get("ort") == "arbeitsplatte":
        mountpunkt = Path(v.get("mountpunkt") or "")
        if not mountpunkt.is_dir() or not os.access(mountpunkt, os.W_OK):
            raise ValueError(f"Der Datenträger {mountpunkt} ist nicht angeschlossen oder nicht beschreibbar.")
        info = datentraeger_info(mountpunkt)
        e["vorschaubilder"] = {"ort": "arbeitsplatte", "volume_uuid": info.get("VolumeUUID") or info.get("DiskUUID") or "",
                               "volume_name": info.get("VolumeName") or mountpunkt.name,
                               "ordner": v.get("ordner") or f"{ARBEITSORDNER}/{ordner.name}/vorschauen"}
    else:
        e["vorschaubilder"] = {"ort": "projekt"}
    e["referenzprojekte"] = [{"pfad": str(r["pfad"]), "name": r.get("name") or Path(r["pfad"]).name}
                             for r in e["referenzprojekte"] if (Path(r["pfad"]) / PROJEKT_DATEI).is_file()]
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "vorgaben").mkdir()
    shutil.copy2(CODE / "vorgaben" / "archivformate.csv", ordner / "vorgaben")
    shutil.copytree(CODE / "vorgaben" / "nara", ordner / "vorgaben" / "nara")
    (ordner / PROJEKT_DATEI).write_text(json.dumps(e, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    oeffnen(ordner)
    protokolliere("Projekt", e["name"], "angelegt", "", json.dumps(e, ensure_ascii=False))
    return P


SCHEMA = """
CREATE TABLE IF NOT EXISTS platte (
    platte_id TEXT PRIMARY KEY, volume_name TEXT, volume_uuid TEXT, geraet TEXT,
    modell TEXT, anschluss TEXT, dateisystem TEXT, kapazitaet_bytes INTEGER,
    frei_bytes INTEGER, smart_status TEXT, kopie_von TEXT, registriert_am TEXT, notiz TEXT,
    etikett_text TEXT, etikett_foto TEXT, deaktiviert_am TEXT,
    art TEXT, quellordner TEXT, umfang TEXT, traeger TEXT, verschluesselt INTEGER);
CREATE TABLE IF NOT EXISTS scanlauf (
    lauf_id INTEGER PRIMARY KEY AUTOINCREMENT, platte_id TEXT, art TEXT,
    start TEXT, ende TEXT, dateien INTEGER, bytes INTEGER, fehler INTEGER, umfang TEXT);
CREATE TABLE IF NOT EXISTS schnellscan (
    platte_id TEXT, relpfad TEXT, name TEXT, groesse INTEGER, mtime REAL, lauf_id INTEGER,
    archiv TEXT,                     -- Datei in einer Archivdatei: deren Pfad auf der Platte (äußerste), sonst leer
    PRIMARY KEY (platte_id, relpfad));
-- Archivdateien (ZIP, tar, gz) auf der Platte und darin (Entscheidung 06.11.2026): aufgelöste stehen in schnellscan
-- als Ordner (ihre Dateien unter <relpfad>/…), nicht auflösbare als gewöhnliche Datei; status nennt, welches
CREATE TABLE IF NOT EXISTS archivdatei (
    platte_id TEXT, relpfad TEXT, art TEXT, status TEXT, meldung TEXT, dateien INTEGER, bytes_entpackt INTEGER,
    groesse INTEGER, mtime REAL, sha256 TEXT, md5 TEXT, lauf_id INTEGER, zeit TEXT,
    PRIMARY KEY (platte_id, relpfad));
CREATE TABLE IF NOT EXISTS scanfehler (
    platte_id TEXT, lauf_id INTEGER, relpfad TEXT, fehler TEXT);
CREATE TABLE IF NOT EXISTS stichprobe_hash (
    paar TEXT, platte_id TEXT, name TEXT, groesse INTEGER, relpfad TEXT, sha256 TEXT, zeit TEXT,
    PRIMARY KEY (paar, platte_id, name, groesse));
CREATE TABLE IF NOT EXISTS protokoll (
    zeit TEXT, abschnitt TEXT, objekt TEXT, feld TEXT, alt TEXT, neu TEXT);
-- Ohne Schreibschutz lesen (Entscheidung 13.11.2026): Zustimmung je Datenträger und wann er zuerst so gelesen wurde
CREATE TABLE IF NOT EXISTS schreibschutz_verzicht (
    platte_id TEXT PRIMARY KEY, zugestimmt_am TEXT, gelesen_am TEXT);
CREATE TABLE IF NOT EXISTS datei (
    platte_id TEXT, relpfad TEXT, groesse INTEGER, mtime REAL,
    sha256 TEXT, md5 TEXT, gehasht_am TEXT, hash_fehler TEXT,
    puid TEXT, format TEXT, formatversion TEXT, mime TEXT,
    sf_basis TEXT, sf_warnung TEXT, sf_fehler TEXT, sf_am TEXT, sf_quelle TEXT,
    PRIMARY KEY (platte_id, relpfad));
CREATE INDEX IF NOT EXISTS datei_sha256 ON datei (sha256);
CREATE INDEX IF NOT EXISTS datei_md5 ON datei (md5);
CREATE TABLE IF NOT EXISTS metadaten (
    platte_id TEXT, relpfad TEXT, dateityp TEXT, aufnahme TEXT, erstellt TEXT, datum_xmp TEXT,
    hersteller TEXT, kamera TEXT, seriennummer TEXT, breite INTEGER, hoehe INTEGER, bittiefe TEXT,
    farbraum TEXT, farbprofil TEXT, ausrichtung INTEGER, gps_breite REAL, gps_laenge REAL,
    urheber TEXT, copyright TEXT, titel TEXT, beschreibung TEXT, schlagworte TEXT, software TEXT,
    seiten INTEGER, dauer REAL, warnung TEXT, fehler TEXT, gelesen_am TEXT,
    datum TEXT, datum_quelle TEXT, quelle TEXT,
    PRIMARY KEY (platte_id, relpfad));
CREATE TABLE IF NOT EXISTS vorschau (
    sha256 TEXT PRIMARY KEY, datei TEXT, art TEXT, quelle TEXT, breite INTEGER, hoehe INTEGER,
    phash TEXT, einfarbig INTEGER, fehler TEXT, erstellt_am TEXT);
CREATE TABLE IF NOT EXISTS gruppe (
    art TEXT, gruppe_id TEXT, platte_id TEXT, relpfad TEXT, abstand REAL, leitdatei INTEGER DEFAULT 0,
    PRIMARY KEY (art, platte_id, relpfad));
CREATE INDEX IF NOT EXISTS gruppe_id ON gruppe (gruppe_id);
CREATE TABLE IF NOT EXISTS archiv (
    platte_id TEXT, relpfad TEXT, ampel TEXT, grund TEXT, massnahme TEXT, bewertet_am TEXT,
    nara_id TEXT, nara_kategorie TEXT, nara_risiko TEXT, nara_massnahme TEXT, nara_plan TEXT, nara_stand TEXT,
    PRIMARY KEY (platte_id, relpfad));
CREATE TABLE IF NOT EXISTS ordnergruppe (
    gruppe_id TEXT, platte_id TEXT, ordner TEXT, dateien INTEGER, bytes INTEGER,
    PRIMARY KEY (gruppe_id, platte_id, ordner));
CREATE TABLE IF NOT EXISTS anton_stand (
    stand TEXT PRIMARY KEY, quelle TEXT, csv TEXT, dateien INTEGER, nur_platten TEXT, eingelesen_am TEXT,
    aktuell INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS anton_datei (
    stand TEXT, md5 TEXT, dateiname TEXT, signatur TEXT, titel TEXT, anton_datei TEXT, link TEXT,
    altsignatur TEXT);                         -- identifier_old des Objekts (Kontrolle nach dem Import, 14.11.2026)
CREATE INDEX IF NOT EXISTS anton_datei_md5 ON anton_datei (md5);
CREATE TABLE IF NOT EXISTS anton_abgleich (
    platte_id TEXT, relpfad TEXT, md5 TEXT, stand TEXT, status TEXT, treffer INTEGER,
    signatur TEXT, titel TEXT, link TEXT, abgeglichen_am TEXT,
    PRIMARY KEY (platte_id, relpfad));
CREATE TABLE IF NOT EXISTS virenscan (
    sha256 TEXT PRIMARY KEY, befund TEXT, meldung TEXT, geprueft_an TEXT, clamav TEXT, geprueft_am TEXT);
-- E1: vollständige ExifTool-Ausgabe je Inhalt und Endung (zlib-komprimiertes JSON ohne Fundortangaben);
-- E4: Text der Dokumente (zlib-komprimiert) mit Titelkandidaten (JSON); dieselben Tabellen legt tool/server.py an
CREATE TABLE IF NOT EXISTS exif_voll (
    sha256 TEXT, endung TEXT, daten BLOB, felder INTEGER, exiftool TEXT, fehler TEXT, gelesen_am TEXT, quelle TEXT,
    PRIMARY KEY (sha256, endung));
CREATE TABLE IF NOT EXISTS volltext (
    sha256 TEXT, endung TEXT, text BLOB, zeichen INTEGER, seiten INTEGER, weg TEXT, titel TEXT, fehler TEXT,
    gelesen_am TEXT, quelle TEXT,
    PRIMARY KEY (sha256, endung));
-- Modul 3 Erschließung (Felder je Platte + Pfad + Feld) und Bestandsboxen (Anton-Einheiten);
-- dieselben Tabellen legt tool/erschliessung.py für den Server an
CREATE TABLE IF NOT EXISTS erschliessung (
    platte_id TEXT, pfad TEXT, feld TEXT, gleich TEXT, je_datei TEXT, quelle TEXT, wer TEXT, zeit TEXT,
    PRIMARY KEY (platte_id, pfad, feld));
CREATE TABLE IF NOT EXISTS bestandsbox (
    anton_id INTEGER PRIMARY KEY, signatur TEXT, titel TEXT, stufe TEXT, objektart TEXT, anzahl INTEGER, link TEXT,
    eltern TEXT, zugang TEXT, geladen_am TEXT, reihenfolge INTEGER, laufzeit TEXT, gesperrt INTEGER);
-- F5: Personen und Gesichter auf dem Vorschaubild eines Fotos, Bildtyp porträt/personen/leer;
-- dieselbe Tabelle legt tool/server.py an
CREATE TABLE IF NOT EXISTS personen (
    sha256 TEXT PRIMARY KEY, anzahl INTEGER, score REAL, modell TEXT, fehler TEXT, erkannt_am TEXT,
    gesichter INTEGER, gesicht_anteil REAL, person_anteil REAL, bildtyp TEXT);
""" + """
-- Läufe der Erfassung im Tool (lauf.py); dieselben Tabellen legt tool/server.py an
CREATE TABLE IF NOT EXISTS lauf (
    lauf_id INTEGER PRIMARY KEY AUTOINCREMENT, art TEXT, platte_id TEXT, auftrag TEXT, status TEXT,
    pid INTEGER, start TEXT, ende TEXT, abbrechen INTEGER DEFAULT 0, meldung TEXT, log TEXT);
CREATE TABLE IF NOT EXISTS lauf_schritt (
    lauf_id INTEGER, schritt TEXT, titel TEXT, status TEXT, anteil REAL, text TEXT, start TEXT, ende TEXT,
    PRIMARY KEY (lauf_id, schritt));
"""


SCHEMA += SCHEMA_VORLAUF                 # Vorlauf und Erschließung, Stufe 2 (vorlauf/schema.py, auch im Server)
SCHEMA += SCHEMA_EXPORT                  # Modul 4 Bestand und Export (export/schema.py, auch im Server)

# So lange wartet ein Schritt, wenn gerade ein anderer Zugriff schreibt (Vorgabe von sqlite3 wären 5 s)
WARTEN_SPERRE = 60


def wal_einschalten(pfad):
    """Schreibprotokoll (WAL): Lesen und Schreiben sperren sich nicht mehr gegenseitig. Sonst scheitert ein Lauf, der
    schreibt, mit „database is locked“, solange das Tool liest (alle 1,5 s, Dashboard mehrere Sekunden). Bleibt in der
    Datei gespeichert; daneben liegen dann inventar.sqlite-wal und -shm (gehören zur Datenbank, nicht löschen)."""
    con = sqlite3.connect(pfad, timeout=WARTEN_SPERRE)
    try:
        con.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass                                   # gerade gesperrt: beim nächsten Öffnen wieder versucht
    finally:
        con.close()


def datenbank_einrichten():
    wal_einschalten(P.db_pfad)
    with db() as con:
        tabellen_umstellen(con)                         # Modul 4: Aufbau vom 05.11.2026 (export/schema.py)
        con.executescript(SCHEMA)
        # Spalten, die in späteren Versionen dazugekommen sind, in einer bestehenden Datenbank ergänzen
        nachruesten = {"platte": ["etikett_text", "etikett_foto", "deaktiviert_am",
                                  "art", "quellordner", "umfang",           # Umfang und Ordner als Quelle (05.11.2026)
                                  "traeger",                                # Art des Datenträgers (05.11.2026)
                                  "verschluesselt INTEGER"],                # verschlüsseltes APFS-Volume (13.11.2026)
                       "scanlauf": ["umfang"], "datei": ["sf_quelle"],
                       "schnellscan": ["archiv"],                           # Archivdateien wie Ordner (06.11.2026)
                       "metadaten": ["quelle"],
                       "anton_stand": ["zugang"],
                       "anton_datei": ["altsignatur"],                    # identifier_old aus Anton (14.11.2026)
                       "bestandsbox": ["laufzeit", "gesperrt INTEGER"],
                       "ebene": ["signatur", "stufe_name"], "zuordnung": ["stufe_name"],
                       "archiv": ["nara_id", "nara_kategorie", "nara_risiko", "nara_massnahme", "nara_plan", "nara_stand"],
                       "personen": ["gesichter INTEGER", "gesicht_anteil REAL", "person_anteil REAL", "bildtyp"]}
        for tabelle, spalten in nachruesten.items():
            vorhanden = {z[1] for z in con.execute(f"PRAGMA table_info({tabelle})")}
            for spalte in spalten:
                name, _, typ = spalte.partition(" ")            # ohne Typ: TEXT
                if name not in vorhanden:
                    con.execute(f"ALTER TABLE {tabelle} ADD COLUMN {name} {typ or 'TEXT'}")


@contextmanager
def db():
    """Öffnet die Datenbank des Projekts: `with db() as con: …` speichert am Ende und schließt wieder."""
    if not hasattr(P, "db_pfad"):
        raise RuntimeError("Kein Projekt geöffnet: erst erfassung.oeffnen(…) aufrufen (Notebook 1, A1).")
    con = sqlite3.connect(P.db_pfad, timeout=WARTEN_SPERRE)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def jetzt():
    return datetime.now().isoformat(timespec="seconds")


def nfc(text):
    """macOS speichert Umlaute in Dateinamen oft zerlegt (NFD), Windows zusammengesetzt (NFC).
    Für Vergleiche wird alles auf NFC gebracht, sonst wären „Müller“ und „Müller“ verschieden."""
    return unicodedata.normalize("NFC", text)


def pfad_schluessel(pfad, pfadmodul=os.path):
    """Vergleichbare Form eines Pfads im Dateisystem: Werkzeuge melden Pfade teils anders, als Balduin sie übergab
    (ExifTool unter Windows mit „/“ statt „\\“); Windows unterscheidet Groß- und Kleinschreibung nicht."""
    return pfadmodul.normcase(pfadmodul.normpath(str(pfad)))


def relpfad_von(pfad, wurzel, pfadmodul=os.path):
    """Pfad relativ zur Wurzel, wie Balduin ihn speichert: in NFC und mit „/“ auf jedem System (unter Windows gibt
    os.path.relpath „A\\1.txt“; der Schlüssel einer Datei ist Platte + Pfad). pfadmodul nur für Tests (ntpath)."""
    return nfc(pfadmodul.relpath(pfad, wurzel).replace(pfadmodul.sep, "/"))


def ist_systemdatei(relpfad):
    """Verwaltungsdateien von macOS und Windows (.DS_Store, Thumbs.db, AppleDouble „._…“) gehören nicht zum Bestand."""
    name = os.path.basename(relpfad)
    # __MACOSX/ legt das Archivprogramm des Mac in ZIPs an (Ressourcen und AppleDouble), nur in Archivdateien
    return name in SYSTEMDATEIEN or name.startswith("._") or "__MACOSX/" in relpfad


def ohne_systemdateien(df):
    """Lässt aus einer Tabelle mit Spalte relpfad die Systemdateien weg."""
    return df[~df.relpfad.map(ist_systemdatei).astype(bool)]


def deaktivierte_platten():
    """Kennungen der Platten, die im Tool aus dem Projekt genommen wurden (platte.deaktiviert_am gesetzt).
    Ihre Daten bleiben stehen, zählen aber bei Duplikaten und Übersicht nicht mit (Entscheidung 30.10.2026)."""
    with db() as con:
        return {k for (k,) in con.execute("SELECT platte_id FROM platte WHERE deaktiviert_am IS NOT NULL")}


def nur_aktive(df):
    """Lässt aus einer Tabelle mit Spalte platte_id die Zeilen herausgenommener Platten weg."""
    weg = deaktivierte_platten()
    return df[~df.platte_id.isin(weg)] if weg else df


def quellpfad(wurzel, relpfad):
    """Pfad einer Datei auf der Platte. Gespeichert ist der Pfad in NFC; manche Dateisysteme
    finden die Datei nur in der zerlegten Schreibweise (NFD), dann wird die genommen."""
    pfad = Path(wurzel) / relpfad
    if not pfad.exists():
        nfd = Path(wurzel) / unicodedata.normalize("NFD", relpfad)
        if nfd.exists():
            return nfd
    return pfad


def vorlagen_waehlen(offen, fertig):
    """Sucht zu jeder offenen Datei eine schon bearbeitete mit gleichem Inhalt (SHA-256) und gleicher Endung,
    deren Ergebnis übernommen werden kann (D2, E1). Siegfried und ExifTool werten die Endung mit aus, daher muss sie passen.
    offen: relpfad, sha256 · fertig: platte_id, relpfad, sha256, direkt (1 = selbst gelesen, 0 = selbst übernommen).
    Ergebnis: relpfad mit vorlage_platte und vorlage_relpfad; selbst gelesene Vorlagen gehen vor."""
    endung = lambda pfade: pfade.map(lambda r: os.path.splitext(r)[1].lower())
    fertig = (fertig.assign(endung=endung(fertig.relpfad))
                    .sort_values(["direkt", "platte_id", "relpfad"], ascending=[False, True, True])
                    .drop_duplicates(["sha256", "endung"])
                    .rename(columns={"platte_id": "vorlage_platte", "relpfad": "vorlage_relpfad"}))
    return (offen.assign(endung=endung(offen.relpfad))
                 .merge(fertig, on=["sha256", "endung"])[["relpfad", "vorlage_platte", "vorlage_relpfad"]])


def csv_lesen(pfad):
    """Liest eine CSV-Datei aus Numbers oder Excel: Komma oder Semikolon, alles als Text."""
    return pd.read_csv(pfad, sep=None, engine="python", encoding="utf-8-sig", dtype=str, keep_default_na=False)


def virenfunde(platte_id):
    """Anzahl der Dateien einer Platte, deren Inhalt der Virenscan (D3) als befallen meldet; E und F lesen sie nicht."""
    with db() as con:
        return con.execute("SELECT COUNT(*) FROM datei d JOIN virenscan v ON v.sha256 = d.sha256 "
                           "WHERE d.platte_id = ? AND v.befund = 'Fund'", (platte_id,)).fetchone()[0]


def protokolliere(abschnitt, objekt, feld, alt, neu):
    """Jede Änderung in der Datenbank wird mit altem und neuem Wert festgehalten."""
    with db() as con:
        con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                    (jetzt(), abschnitt, objekt, feld, str(alt), str(neu)))


# --- Ausgabe: im Notebook Tabellen und Diagramme, im Hintergrundlauf nur Text ---

def im_notebook():
    try:
        from IPython import get_ipython
    except ImportError:
        return False
    return get_ipython() is not None


def zeige(*objekte):
    """Zeigt Tabellen, HTML oder Diagramme im Notebook; außerhalb (Hintergrundlauf des Tools) geschieht nichts."""
    if im_notebook():
        from IPython.display import display
        display(*objekte)


def kuerzen(text, laenge=42):
    return text if len(text) <= laenge else text[:laenge - 1] + "…"


MELDER = None          # im Hintergrundlauf (lauf.py): Funktion(anteil, text), die den Fortschritt in die Datenbank schreibt


def restzeit(minuten):
    """Geschätzte Restzeit als Text: „noch ca. 40 s“, „noch ca. 12 Min.“, „noch ca. 2 Std. 5 Min.“."""
    sekunden = max(minuten * 60, 0)
    if sekunden < 60:
        return f"noch ca. {max(round(sekunden / 10) * 10, 10):.0f} s"
    minuten = round(sekunden / 60)
    if minuten < 60:
        return f"noch ca. {minuten} Min."
    return f"noch ca. {minuten // 60} Std. {minuten % 60} Min."


def fortschritt(anteil, text=""):
    """Fortschrittsbalken als Textzeile, z. B. [██████████░░░░░░░░░░░░░░░░░░░░]  33 % · 1.2/3.6 GB"""
    anteil = min(max(anteil, 0), 1)
    if MELDER:
        MELDER(anteil, text)
    voll = round(anteil * 30)
    print(f"[{'█' * voll}{'░' * (30 - voll)}] {anteil:4.0%} · {text}   ", end="\r")


# --- Speicherplatz: feste Reserve statt Budget (docs/plan.md, Entscheidung 12.11.2026) ---

def ordnergroesse(ordner):
    """Summe aller Dateigrößen unter einem Ordner, in Bytes."""
    summe = 0
    for wurzel, _, dateien in os.walk(ordner):
        for d in dateien:
            try:
                summe += os.lstat(os.path.join(wurzel, d)).st_size
            except OSError:
                pass
    return summe


def speicherstand():
    """Freier Platz auf dem Laufwerk des Projekts und belegter Platz im Projektordner, in GB."""
    # export/ zählt nicht mit: Dort liegen nur Pakete bis zur Übergabe, geprüft mit export_platz_pruefen
    return shutil.disk_usage(P.ordner).free / 1e9, (ordnergroesse(P.ordner) - ordnergroesse(P.ordner / "export")) / 1e9


def menge(gb):
    """Speichermenge lesbar: unter 0,1 GB in MB, damit kleine Bedarfe nicht als „0.0 GB“ erscheinen."""
    if gb < 0.001:
        return "unter 1 MB"
    return f"{gb * 1000:.0f} MB" if gb < 0.1 else f"{gb:.1f} GB"


def export_ablage_setzen(mountpunkt):
    """Ablage der Exportpakete wählen (Entscheidung 05.11.2026): "projekt" oder der Mountpunkt eines beschreibbaren
    Datenträgers, der keine registrierte Quellplatte ist. Nicht, solange Pakete gebaut, aber noch nicht übergeben sind."""
    with db() as con:
        offen = con.execute("SELECT COUNT(*) FROM paket WHERE status = 'gebaut' OR (status IN ('geplant', 'Fehler') "
                            "AND paket_id IN (SELECT paket_id FROM paket_eintrag WHERE tar_ende IS NOT NULL))").fetchone()[0]
        quellen = [dict(zip(("platte_id", "volume_uuid", "volume_name"), z))
                   for z in con.execute("SELECT platte_id, volume_uuid, volume_name FROM platte")]
    if offen:
        raise ValueError(f"{offen} Pakete liegen schon (ganz oder teilweise) auf der bisherigen Ablage und sind noch "
                         "nicht übergeben. Erst übergeben oder neu planen.")
    if mountpunkt == "projekt":
        neu_a = {"ort": "projekt"}
    else:
        mountpunkt = Path(mountpunkt or "")
        if not system.ist_datentraeger(mountpunkt, P.volumes) or not mountpunkt.is_dir():
            raise ValueError(f"{mountpunkt} ist kein angeschlossener Datenträger.")
        from erfassung.platte import ist_schreibgeschuetzt      # erfassung.platte importiert basis
        if ist_schreibgeschuetzt(mountpunkt) or not os.access(mountpunkt, os.W_OK):
            raise ValueError(f"{mountpunkt.name} ist schreibgeschützt eingehängt; als Ablage braucht es einen beschreibbaren Datenträger.")
        # in Tests stehen gewöhnliche Ordner für Datenträger; diskutil nennt dort die UUID des Mac-Laufwerks, die auch
        # die Testplatten tragen: dann nur über den Namen wiederfinden, sonst landete die Ablage auf einer Quellplatte
        info = datentraeger_info(mountpunkt) if system.standard_volumes(P.volumes) else {}
        uuid = info.get("VolumeUUID") or info.get("DiskUUID") or ""
        alle = system.kennungen(info)                    # auch die frühere Form (FAT/exFAT unter Windows/Linux)
        for q in quellen:                                # nie auf eine Quellplatte schreiben (harte Regel 1)
            if (uuid and q["volume_uuid"] in alle) or (not uuid and q["volume_name"] == mountpunkt.name):
                raise ValueError(f"{mountpunkt.name} ist die Quellplatte {q['platte_id']}; dort schreibt Balduin nie.")
        neu_a = {"ort": "platte", "volume_uuid": uuid, "volume_name": info.get("VolumeName") or mountpunkt.name,
                 "ordner": f"{ARBEITSORDNER}/{P.ordner.name}/export"}
    alt_a = P.einstellungen["export"]["ablage"]
    neu = {**P.einstellungen, "export": {**P.einstellungen["export"], "ablage": neu_a}}
    datei = P.ordner / PROJEKT_DATEI
    zwischen = datei.with_suffix(".tmp")
    zwischen.write_text(json.dumps(neu, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(zwischen, datei)
    protokolliere("Projekt", P.name, "export.ablage", json.dumps(alt_a, ensure_ascii=False), json.dumps(neu_a, ensure_ascii=False))
    P.setze(P.ordner, P.arbeitsplatte_test, P.volumes)
    return {"ok": True, "ablage": neu_a}


def laufwerk_von(ordner):
    """Wie das Laufwerk eines Ordners in Meldungen heißt: externe Platte mit Namen, sonst der Rechner."""
    wurzel = system.datentraeger_von(Path(ordner).resolve())
    return f"dem Datenträger „{wurzel.name or wurzel}“" if wurzel else f"{system.rechnername()} (interner Speicher)"


def platz_pruefen(bedarf_gb=0):
    """Vor platzintensiven Schritten aufrufen; bricht ab, bevor der Schritt die feste Reserve auf dem Laufwerk des
    Projekts angreifen würde (ein volles Laufwerk gefährdet die Datenbank). Keine Obergrenze für das Projekt selbst
    (Entscheidung 12.11.2026)."""
    frei, belegt = speicherstand()
    if frei - bedarf_gb < P.min_frei_gb:
        raise RuntimeError(
            f"Zu wenig Platz auf {laufwerk_von(P.ordner)}, wo das Projekt liegt: {frei:.1f} GB frei, dieser Schritt "
            f"braucht etwa {menge(bedarf_gb)}, und {P.min_frei_gb:g} GB sollen frei bleiben, damit der Rechner und die "
            f"Datenbank sicher weiterlaufen. Bitte dort mindestens {menge(P.min_frei_gb + bedarf_gb - frei)} "
            f"freiräumen und dann „Alles Offene fortsetzen“.")
    print(f"✓ Platz reicht: {frei:.1f} GB frei, Projekt {belegt:.1f} GB, Bedarf {menge(bedarf_gb)}.")


def speicher_melden():
    frei, belegt = speicherstand()
    print(f"Frei am Speicherort des Projekts: {frei:.1f} GB (davon bleiben {P.min_frei_gb:g} GB als Reserve frei)")
    print(f"Projektordner:    {belegt:.1f} GB, {P.ordner}")
    if P.arbeitsplatte is not None:
        da = P.arbeitsplatte.exists()
        print(f"Vorschaubilder:   {P.vorschauen}" + ("" if da else " (Datenträger für Vorschaubilder nicht angeschlossen)"))
    if frei < P.min_frei_gb:
        print("⚠ Weniger frei als die Reserve. Platzintensive Schritte starten nicht.")

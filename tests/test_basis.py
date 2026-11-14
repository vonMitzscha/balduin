"""Grundlagen in erfassung/basis.py ohne Platten: Hilfsfunktionen, Einstellungen, Projekt anlegen, Datenbank nachrüsten.
Schnell (unter einer Sekunde je Test); läuft auch mit  pytest -m "not integration"."""
import json
import sqlite3
import unicodedata

import pytest

from erfassung import basis


# ---------- Hilfsfunktionen ----------

def test_nfc_setzt_zerlegte_umlaute_zusammen():
    zerlegt = unicodedata.normalize("NFD", "Müller Jubiläum")
    assert zerlegt != "Müller Jubiläum"
    assert basis.nfc(zerlegt) == "Müller Jubiläum"


@pytest.mark.parametrize("pfad, erwartet", [
    (".DS_Store", True), ("Fotos/.DS_Store", True), ("Fotos/Thumbs.db", True), ("a/desktop.ini", True),
    ("Fotos/._IMG_0001.JPG", True), ("Fotos/IMG_0001.JPG", False), ("Fotos/DS_Store.txt", False),
])
def test_systemdateien(pfad, erwartet):
    assert basis.ist_systemdatei(pfad) is erwartet


@pytest.mark.parametrize("text, erwartet", [("1–5", (1, 5)), ("3-7", (3, 7)), (" 4 ", (4, 4)), ("1—60", (1, 60))])
def test_seitenbereich(text, erwartet):
    assert basis.seitenbereich(text) == erwartet


@pytest.mark.parametrize("text", ["0-3", "5-2", "1-61", "abc", "", None, "1–5–7"])
def test_seitenbereich_ungueltig(text):
    with pytest.raises(ValueError, match="Seitenbereich"):
        basis.seitenbereich(text)


# ---------- Einstellungen ----------

def test_einstellungen_mischen_veraendert_die_vorgaben_nicht():
    vorher = json.dumps(basis.VORGABEN_PROJEKT, sort_keys=True)
    e = basis.einstellungen_mischen(basis.VORGABEN_PROJEKT, {"film": {"bilder": 3}, "name": "X"})
    assert e["film"] == {**basis.VORGABEN_PROJEKT["film"], "bilder": 3}
    e["film"]["art"] = "raster"
    assert json.dumps(basis.VORGABEN_PROJEKT, sort_keys=True) == vorher


def gueltig(**aenderungen):
    return basis.einstellungen_mischen(basis.VORGABEN_PROJEKT, {"name": "Test", "anton": {"url": "https://archives.example.com"},
                                                                **aenderungen})


def test_keine_anton_adresse_vorgegeben():
    """Balduin ist nicht für ein bestimmtes Archiv: keine Instanz voreinstellen (Entscheidung 06.11.2026)."""
    assert basis.VORGABEN_PROJEKT["anton"]["url"] == ""
    with pytest.raises(ValueError, match="Anton-Server"):
        basis.einstellungen_pruefen(gueltig(anton={"url": ""}))


def test_vorgaben_mit_namen_sind_gueltig():
    basis.einstellungen_pruefen(gueltig())


@pytest.mark.parametrize("aenderung, meldung", [
    ({"name": "  "}, "Namen"),
    ({"kennung": "G1"}, "Kürzel"),
    ({"kennung": "SIEBENX"}, "Kürzel"),
    ({"film": {"art": "gif"}}, "Filmvorschau"),
    ({"pdf": {"art": "bereich", "bereich": "9-1"}}, "Seitenbereich"),
    ({"speicher": {"min_frei_gb": 0}}, "Reserve"),
    ({"anton": {"url": "http://archives.example.com"}}, "Anton-Server"),         # unverschlüsselt nach außen
    ({"anton": {"url": "https://archives.example.com/api"}}, "Anton-Server"),    # mit Pfad
    ({"anton": {"url": "https://nutzer@archives.example.com"}}, "Anton-Server"),
    ({"anton": {"url": "http://ddev.site.example.com"}}, "Anton-Server"),       # nur die Endung zählt
    ({"anton": {"url": "http://192.168.1.20"}}, "Anton-Server"),                # anderer Rechner im Netz
    ({"vorlauf": {"umfang": "teilweise"}}, "Umfang"),
])
def test_ungueltige_einstellungen(aenderung, meldung):
    with pytest.raises(ValueError, match=meldung):
        basis.einstellungen_pruefen(gueltig(**aenderung))


@pytest.mark.parametrize("url", ["https://archiv.example.org", "http://127.0.0.1:8080", "http://localhost",
                                 "http://muster.anton.ddev.site", "http://anton.test:8080", "http://anton.localhost",
                                 "https://muster.anton.ddev.site"])
def test_erlaubte_anton_adressen(url):
    basis.einstellungen_pruefen(gueltig(anton={"url": url}))


@pytest.mark.parametrize("sprachmodell", [
    {"anbieter": "openai", "adresse": "https://api.openai.com", "modell": "gpt-4o"},
    {"anbieter": "ollama", "adresse": "http://192.168.1.20:11434", "modell": "qwen2.5:14b"},   # anderer Rechner
    {"anbieter": "ollama", "adresse": "https://ollama.example.com", "modell": "qwen2.5:14b"},
])
def test_sprachmodell_nur_lokal(sprachmodell):
    """Harte Regel 6: Cloud-Modelle erst nach Freigabe durch das Archiv."""
    with pytest.raises(ValueError, match="Cloud"):
        basis.einstellungen_pruefen(gueltig(sprachmodell=sprachmodell))


# ---------- Projekt anlegen und öffnen ----------

def test_projekt_anlegen(leeres_projekt):
    o = leeres_projekt.ordner
    assert json.loads((o / "projekt.json").read_text(encoding="utf-8"))["name"] == "Leer"
    assert (o / "inventar.sqlite").is_file()
    assert (o / "vorgaben" / "archivformate.csv").is_file()        # eigene Kopie der Regeltabellen
    assert leeres_projekt.vorgaben == o / "vorgaben"
    assert leeres_projekt.vorschauen == o / "vorschauen"
    with sqlite3.connect(o / "inventar.sqlite") as con:
        assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        protokoll = con.execute("SELECT abschnitt, objekt, feld FROM protokoll").fetchall()
    assert protokoll == [("Projekt", "Leer", "angelegt")]


def test_projekt_nicht_in_vollen_ordner(tmp_path):
    (tmp_path / "voll").mkdir()
    (tmp_path / "voll" / "etwas.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="nicht leer"):
        basis.projekt_anlegen(tmp_path / "voll", {"name": "X"})


def test_projekt_nicht_doppelt(leeres_projekt):
    with pytest.raises(ValueError):
        basis.projekt_anlegen(leeres_projekt.ordner, {"name": "Nochmal"})


def test_kein_projektordner(tmp_path):
    with pytest.raises(FileNotFoundError, match="kein Projektordner"):
        basis.oeffnen(tmp_path)


def test_datenbank_alter_fassung_wird_nachgeruestet(leeres_projekt):
    """Eine Datenbank von früher ohne die später dazugekommenen Spalten: Öffnen ergänzt sie, Daten bleiben."""
    db = leeres_projekt.db_pfad
    with sqlite3.connect(db) as con:
        con.execute("DROP TABLE platte")
        con.execute("CREATE TABLE platte (platte_id TEXT PRIMARY KEY, volume_name TEXT, notiz TEXT)")
        con.execute("INSERT INTO platte VALUES ('HD01', 'Alt', 'von früher')")
    basis.oeffnen(leeres_projekt.ordner, volumes=leeres_projekt.volumes)
    with sqlite3.connect(db) as con:
        spalten = {z[1] for z in con.execute("PRAGMA table_info(platte)")}
        zeile = con.execute("SELECT platte_id, notiz, etikett_text, deaktiviert_am FROM platte").fetchone()
    assert {"etikett_text", "etikett_foto", "deaktiviert_am"} <= spalten
    assert zeile == ("HD01", "von früher", None, None)


def test_einstellungen_aendern_wird_protokolliert(leeres_projekt):
    antwort = basis.einstellungen_aendern({"name": "Neuer Name", "virenscan": True})
    assert set(antwort["geaendert"]) == {"name", "virenscan"}
    assert basis.P.name == "Neuer Name"
    assert json.loads((leeres_projekt.ordner / "projekt.json").read_text(encoding="utf-8"))["name"] == "Neuer Name"
    with sqlite3.connect(leeres_projekt.db_pfad) as con:
        zeilen = con.execute("SELECT feld, alt, neu FROM protokoll WHERE abschnitt = 'Projekt' AND feld != 'angelegt' "
                             "ORDER BY feld").fetchall()
    assert zeilen == [("name", '"Leer"', '"Neuer Name"'), ("virenscan", "false", "true")]


def test_ort_der_vorschaubilder_nicht_ueber_einstellungen(leeres_projekt):
    with pytest.raises(ValueError, match="Nicht in Balduin änderbar"):
        basis.einstellungen_aendern({"vorschaubilder": {"ort": "arbeitsplatte"}})


def test_kuerzel_nur_ohne_registrierte_platte(leeres_projekt):
    basis.einstellungen_aendern({"kennung": "ab"})
    assert basis.P.kennung == "AB"                                 # groß geschrieben
    with sqlite3.connect(leeres_projekt.db_pfad) as con:
        con.execute("INSERT INTO platte (platte_id) VALUES ('AB01')")
    with pytest.raises(ValueError, match="solange kein Datenträger"):
        basis.einstellungen_aendern({"kennung": "XY"})


def test_neue_projekte_ohne_bezug_auf_ein_archiv():
    """Vorgaben neuer Projekte (Entscheidung 12.11.2026): Kürzel HD, Arbeitsordner „Balduin-Projekte“, keine Testinstanz."""
    assert basis.VORGABEN_PROJEKT["kennung"] == "HD"
    assert basis.ARBEITSORDNER == "Balduin-Projekte"
    assert basis.VORGABEN_PROJEKT["anton"]["testinstanz"] is False


def test_testinstanz_im_projekt_vermerken(leeres_projekt):
    assert basis.P.einstellungen["anton"]["testinstanz"] is False            # auch ältere projekt.json ohne den Schlüssel
    r = basis.einstellungen_aendern({"anton": {"url": "https://archiv.example.org", "testinstanz": 1}})
    assert "anton" in r["geaendert"] and basis.P.einstellungen["anton"]["testinstanz"] is True

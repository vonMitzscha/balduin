"""Modul 1 Registrierung/Analyse als Ganzes: Die Testplatten HD01 und HD02 laufen durch B–I (Fixture „analysiert“),
dann wird das Ergebnis in der Datenbank gegen die Dateien auf den Platten geprüft."""
import hashlib
import os
import unicodedata
from pathlib import Path

import pytest

from conftest import abfrage, fingerabdruck, lauf_ausfuehren, projekt_kopieren

pytestmark = pytest.mark.integration

SYSTEMORDNER = {".Spotlight-V100", ".fseventsd", ".Trashes", ".TemporaryItems", ".DocumentRevisions-V100",
                "$RECYCLE.BIN", "System Volume Information"}


def dateien_auf(wurzel):
    """Alle Dateien einer Testplatte (relativer Pfad in NFC, wie in der Datenbank) → Bytes."""
    ergebnis = {}
    for ordner, unter, dateien in os.walk(wurzel):
        unter[:] = [u for u in unter if u not in SYSTEMORDNER]
        for name in dateien:
            pfad = os.path.join(ordner, name)
            rel = unicodedata.normalize("NFC", Path(os.path.relpath(pfad, wurzel)).as_posix())
            with open(pfad, "rb") as f:
                ergebnis[rel] = f.read()
    return ergebnis


@pytest.mark.parametrize("platte", ["HD01", "HD02"])
def test_alle_schritte_ohne_fehler(analysiert, platte):
    schritte = analysiert.laeufe[platte]["schritte"]
    assert {k: s["status"] for k, s in schritte.items() if s["status"] not in ("fertig", "übersprungen")} == {}
    for pflicht in ("B", "C", "D1", "D2", "E", "E4", "F", "G", "H"):
        assert schritte[pflicht]["status"] == "fertig", pflicht


@pytest.mark.parametrize("platte", ["HD01", "HD02"])
def test_jede_datei_mit_richtigen_pruefsummen(analysiert, platte):
    """Schnellscan und Prüfsummen erfassen jede Datei der Platte genau einmal, SHA-256 und MD5 stimmen."""
    auf_platte = dateien_auf(analysiert.volumes / platte)
    in_db = {z["relpfad"]: z for z in abfrage(analysiert.ordner, "SELECT relpfad, groesse, sha256, md5 FROM datei "
                                                                  "WHERE platte_id = ?", platte)}
    assert set(in_db) == set(auf_platte)
    for rel, inhalt in auf_platte.items():
        assert in_db[rel]["groesse"] == len(inhalt), rel
        assert in_db[rel]["sha256"] == hashlib.sha256(inhalt).hexdigest(), rel
        assert in_db[rel]["md5"] == hashlib.md5(inhalt).hexdigest(), rel


def test_pfade_in_nfc_auch_von_nfd_platte(analysiert):
    """HD02 trägt „Müller Jubiläum“ in macOS-Schreibweise (NFD); gespeichert wird NFC (CLAUDE.md, Konventionen)."""
    pfade = [z["relpfad"] for z in abfrage(analysiert.ordner, "SELECT relpfad FROM schnellscan")]
    assert all(p == unicodedata.normalize("NFC", p) for p in pfade)
    assert any("Müller Jubiläum" in p for p in pfade if p.startswith("Backup 2012/"))


def test_formate_erkannt(analysiert):
    formate = {z["relpfad"]: z["puid"] for z in abfrage(analysiert.ordner, "SELECT relpfad, puid FROM datei "
                                                                            "WHERE platte_id = 'HD01'")}
    assert formate["Formate/verlauf_rot.png"].startswith("fmt/")       # PNG
    assert formate["Formate/punkt.gif"].startswith("fmt/")             # GIF


def test_abgeschnittenes_jpeg_wird_markiert(analysiert):
    """Ein abgeschnittenes JPEG (kaputt.jpg) markiert H1, unabhängig von der Formatprüfung in Anton, die es als gültig
    durchlässt (Befund 14.11.2026, docs/issues/anton_formatpruefung_jpeg.md)."""
    z = abfrage(analysiert.ordner, "SELECT ampel, grund FROM archiv WHERE platte_id = 'HD01' AND relpfad = ?",
                "Fotos/Kamera 2003/kaputt.jpg")[0]
    assert z["ampel"] == "rot", z                     # Siegfried erkennt das Format nicht (wie in Anton: unknown)


def test_jede_datei_hat_eine_ampel(analysiert):
    ohne = abfrage(analysiert.ordner, "SELECT d.platte_id, d.relpfad FROM datei d LEFT JOIN archiv a USING (platte_id, "
                                      "relpfad) WHERE a.ampel IS NULL OR a.ampel NOT IN ('grün', 'gelb', 'rot')")
    assert ohne == []


def test_exakte_kopien_als_gruppe(analysiert):
    """titelbild.png ist eine Kopie von verlauf_rot.png auf derselben Platte und von HD02 (Backup)."""
    zeilen = abfrage(analysiert.ordner, "SELECT gruppe_id, platte_id, relpfad FROM gruppe WHERE art = 'exakt'")
    gruppe = {z["gruppe_id"] for z in zeilen if z["relpfad"] == "Fotos/Auswahl/titelbild.png"}
    assert len(gruppe) == 1
    mitglieder = {(z["platte_id"], z["relpfad"]) for z in zeilen if z["gruppe_id"] in gruppe}
    assert {("HD01", "Formate/verlauf_rot.png"), ("HD02", "Backup 2012/Formate/verlauf_rot.png")} <= mitglieder


def test_plattenetikett_gespeichert(analysiert):
    """Das Etikett gehört zur Überlieferung (Bestandsgeschichte)."""
    etiketten = {z["platte_id"]: z["etikett_text"] for z in abfrage(analysiert.ordner, "SELECT * FROM platte")}
    assert etiketten == {"HD01": "Etikett HD01", "HD02": "Etikett HD02"}


def test_abgleich_mit_anton(analysiert):
    """punkt.gif liegt im nachgebauten Anton (gleiche MD5) und wird als „in Anton“ erkannt, andere nicht."""
    status = {(z["platte_id"], z["relpfad"]): z["status"] for z in abfrage(analysiert.ordner, "SELECT * FROM anton_abgleich")}
    assert status[("HD01", "Formate/punkt.gif")] == "in Anton"
    assert status[("HD02", "Backup 2012/Formate/punkt.gif")] == "in Anton"
    assert status[("HD01", "Formate/verlauf_rot.png")] == "nicht in Anton"


def test_quellplatten_bleiben_unveraendert(analysiert, testplatten):
    """Harte Regel 1: Nach der ganzen Analyse ist jede Testplatte bitgleich, auch Zeitstempel und Ordner."""
    for platte, vorher in testplatten.abdruck.items():
        assert fingerabdruck(testplatten.volumes / platte) == vorher, platte


def test_fortsetzen_ist_idempotent(analysiert, tmp_path):
    """Ein zweiter Lauf („fortsetzen“) macht nur, was fehlt: keine doppelten Zeilen, gleiche Ergebnisse."""
    kopie = projekt_kopieren(analysiert.ordner, tmp_path / "Kopie")
    tabellen = ("schnellscan", "datei", "metadaten", "vorschau", "gruppe", "archiv", "anton_abgleich", "volltext")

    def stand():
        return {t: sorted(tuple(z.values()) for z in abfrage(kopie, f"SELECT * FROM {t}")) for t in tabellen}

    def ohne_zeit(s):            # Zeitstempel einer Neuberechnung dürfen sich ändern, Inhalte nicht
        return {t: [tuple(x for x in z if not (isinstance(x, str) and x[:2] == "20" and "T" in x)) for z in zeilen]
                for t, zeilen in s.items()}

    vorher = stand()
    lauf_ausfuehren(kopie, analysiert.volumes, "erfassen", {
        "platte_id": "HD01", "mountpunkt": str(analysiert.volumes / "HD01"), "beschreibbar_ok": True,
        "modus": "fortsetzen"}, "HD01")
    nachher = stand()
    for t in tabellen:
        assert len(nachher[t]) == len(vorher[t]), t
    assert ohne_zeit(nachher) == ohne_zeit(vorher)

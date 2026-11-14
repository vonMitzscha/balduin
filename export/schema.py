"""Tabellen von Modul 4 Bestand und Export (Entscheidungen 04. und 05.11.2026 in docs/plan.md). Nur ein Text, ohne
Abhängigkeiten: erfassung/basis.py (Hintergrundläufe) und tool/pakete.py (Server, nur Standardbibliothek) legen sie an."""

SCHEMA_EXPORT = """
-- feste UUID je Einheit des Exports, einmal erzeugt (auch über neues Planen hinweg); schluessel:
-- e:<ebene_id> (neue Ebene aus Modul 3), o:<Platte>|<Ordner> (Ordner als eigene Ebene), d:<Platte>|<relpfad> (Datei
-- als Einzelstück); datei_uuid = UUID des Mediums (files[].uuid)
CREATE TABLE IF NOT EXISTS export_einheit (
    schluessel TEXT PRIMARY KEY, uuid TEXT UNIQUE, datei_uuid TEXT, erzeugt_am TEXT);
-- Pakete: art „ebenen“ (neue Ebenen einer Bestandsbox, ohne Dateien und ohne Platte) oder „teil“ (Platte + Ziel);
-- ziel = Anton-ID der Bestandsbox; braucht = JSON-Liste der paket_id, deren Ebenen dieses Paket voraussetzt;
-- status: geplant, Fehler, gebaut (tar auf der Ablage, nachgeprüft: geprueft_am), übergeben (an K&R),
-- importiert (Kontrolle: alles da), unvollständig (Kontrolle: etwas fehlt); datei = Pfad des tar auf der Ablage
CREATE TABLE IF NOT EXISTS paket (
    paket_id INTEGER PRIMARY KEY AUTOINCREMENT, art TEXT, platte_id TEXT, ziel INTEGER, teil INTEGER, name TEXT,
    eintraege INTEGER, dateien INTEGER, bytes INTEGER, braucht TEXT, status TEXT, geplant_am TEXT, fehler TEXT,
    gebaut_am TEXT, geprueft_am TEXT, datei TEXT, datei_bytes INTEGER, datei_sha256 TEXT, datei_geloescht_am TEXT,
    uebergeben_am TEXT, uebergabe TEXT, kontrolle_am TEXT, kontrolle TEXT, importiert_am TEXT);
-- Einträge der metadata.json je Paket in ihrer Reihenfolge (Eltern vor Kindern), je Eintrag das JSON nach dem Schema
-- des Anton-Importformats; bei Einzelstücken die Datei auf der Platte mit MD5, SHA-256 und Größe für das Bauen.
-- tar_ende = Stelle im tar nach dieser Datei (zum Fortsetzen); anton = Ergebnis der Kontrolle (da, fehlt, name, mehrfach)
CREATE TABLE IF NOT EXISTS paket_eintrag (
    paket_id INTEGER, nr INTEGER, schluessel TEXT, eintrag TEXT, platte_id TEXT, relpfad TEXT, md5 TEXT,
    sha256 TEXT, groesse INTEGER, tar_ende INTEGER, anton TEXT, anton_signatur TEXT, anton_link TEXT,
    PRIMARY KEY (paket_id, nr));
-- Freigabe: quittierte Lesefehler je Platte (punkt „lesefehler:<Platte>“, wert = Zahl der quittierten Pfade),
-- letzte Abfrage von GET /api/import-format (punkt „importformat“, wert = JSON)
CREATE TABLE IF NOT EXISTS export_freigabe (
    punkt TEXT PRIMARY KEY, wert TEXT, wer TEXT, zeit TEXT);
"""


def tabellen_umstellen(con):
    """Die Pakettabellen vom 04.11.2026 (ZIP, Upload) auf den Aufbau vom 05.11.2026 bringen. Mit dem alten Aufbau
    ist nie etwas an Anton gegangen (nur Tests am nachgebauten Anton); die festen UUIDs in export_einheit bleiben."""
    spalten = {z[1] for z in con.execute("PRAGMA table_info(paket)")}
    if "zip" in spalten:
        con.execute("DROP TABLE paket")
        con.execute("DROP TABLE IF EXISTS paket_eintrag")
        con.executescript(SCHEMA_EXPORT)

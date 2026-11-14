"""Tabellen von Vorlauf und Erschließung (Stufe 2, docs/plan.md 03.11.2026). Nur ein Text, ohne Abhängigkeiten:
erfassung/basis.py (Hintergrundläufe) und tool/erschliessung.py (Server, nur Standardbibliothek) legen sie beide an."""

SCHEMA_VORLAUF = """
-- Umfang des nächsten Vorlaufs (vom Tool vor dem Start geschrieben: nur der Server kennt die wirksamen Entscheidungen)
CREATE TABLE IF NOT EXISTS vorlauf_umfang (
    platte_id TEXT, relpfad TEXT, PRIMARY KEY (platte_id, relpfad));
-- je Schritt und Datei: im letzten Lauf des Schritts berücksichtigt (für „offen“ = neu Übernommenes seither)
CREATE TABLE IF NOT EXISTS vorlauf_erledigt (
    schritt TEXT, platte_id TEXT, relpfad TEXT, PRIMARY KEY (schritt, platte_id, relpfad));
-- je Schritt der letzte Lauf: Umfang, Dateien, mit Ergebnis, Kennzahlen (JSON), Zeit, Dauer in s
CREATE TABLE IF NOT EXISTS vorlauf_stand (
    schritt TEXT PRIMARY KEY, umfang TEXT, dateien INTEGER, ergebnis INTEGER, kennzahlen TEXT, zeit TEXT, dauer REAL);
-- Vorschläge je Platte + Pfad (Datei, Ordner), Feld und Wert: titel, zeitraum (JSON [von, bis, ca]), inhalt,
-- akteur, ort, schlagwort; begriff = Kandidat aus Pfaden für den Normdatenabgleich (nicht angezeigt).
-- Jeder Schritt ersetzt nur seine eigenen Zeilen; anton_id/anton_name: Treffer im Anton-Vokabular (V8)
CREATE TABLE IF NOT EXISTS vorschlag (
    platte_id TEXT, pfad TEXT, feld TEXT, wert TEXT, quelle TEXT, score REAL, beleg TEXT, schritt TEXT,
    anton_id INTEGER, anton_name TEXT, zeit TEXT,
    PRIMARY KEY (platte_id, pfad, feld, wert, schritt));
CREATE INDEX IF NOT EXISTS vorschlag_ort ON vorschlag (platte_id, pfad);
CREATE INDEX IF NOT EXISTS vorschlag_feld ON vorschlag (feld, anton_id);
-- Urteile über Vorschläge (angenommen/verworfen); bleiben, wenn der Vorlauf neu rechnet
CREATE TABLE IF NOT EXISTS vorschlag_urteil (
    platte_id TEXT, pfad TEXT, feld TEXT, wert TEXT, urteil TEXT, wer TEXT, zeit TEXT,
    PRIMARY KEY (platte_id, pfad, feld, wert));
-- Anton-Vokabular (öffentliche API, nur gelesen): art keyword/place/actor
CREATE TABLE IF NOT EXISTS anton_begriff (
    art TEXT, anton_id INTEGER, name TEXT, voll TEXT, typ TEXT, alternativ TEXT, wikidata TEXT, gnd TEXT,
    breite REAL, laenge REAL, geholt_am TEXT, PRIMARY KEY (art, anton_id));
-- Gelerntes aus Bestätigungen: Wort (normalisiert) → Anton-Begriff (Synonym) oder Ausschluss (1)
CREATE TABLE IF NOT EXISTS begriff_gelernt (
    art TEXT, wort TEXT, anton_id INTEGER, name TEXT, ausschluss INTEGER, wer TEXT, zeit TEXT,
    PRIMARY KEY (art, wort, anton_id));
-- Verwandte Ordner (V10): Paar a < b, Grund (duplikate, tag_kamera, name), Score, Beleg
CREATE TABLE IF NOT EXISTS verwandt (
    platte_a TEXT, pfad_a TEXT, platte_b TEXT, pfad_b TEXT, grund TEXT, score REAL, beleg TEXT,
    PRIMARY KEY (platte_a, pfad_a, platte_b, pfad_b, grund));
CREATE INDEX IF NOT EXISTS verwandt_b ON verwandt (platte_b, pfad_b);
-- im Abgleich abgewählt: erscheinen nicht wieder
CREATE TABLE IF NOT EXISTS nicht_verwandt (
    platte_a TEXT, pfad_a TEXT, platte_b TEXT, pfad_b TEXT, wer TEXT, zeit TEXT,
    PRIMARY KEY (platte_a, pfad_a, platte_b, pfad_b));
-- neue Ebenen unter einer Bestandsbox (eltern "a:<Anton-ID>" oder "e:<ebene_id>"); stufe class oder file (was der
-- API-Import kennt), stufe_name die in Anton gewählte Stufe (Werteliste aus anton_stufe), Signatur optional
CREATE TABLE IF NOT EXISTS ebene (
    ebene_id INTEGER PRIMARY KEY AUTOINCREMENT, eltern TEXT, titel TEXT, stufe TEXT, von TEXT, bis TEXT,
    ca INTEGER, inhalt TEXT, wer TEXT, zeit TEXT, signatur TEXT, stufe_name TEXT);
-- Stufen der Anton-Instanz (GET /api/ai/schema, nur gelesen): Name, Schlüssel, import = class/file/item
CREATE TABLE IF NOT EXISTS anton_stufe (
    name TEXT PRIMARY KEY, schluessel TEXT, import TEXT, reihenfolge INTEGER, geholt_am TEXT);
-- weitere Anton-Felder für das Dropdown im Editor (Notizfelder aus /api/import/mapping, Labels ggf. aus /api/ai/schema);
-- import = 1, wenn der API-Import das Feld übernimmt (Entscheidung 04.11.2026)
CREATE TABLE IF NOT EXISTS anton_feld (
    name TEXT PRIMARY KEY, label TEXT, import INTEGER, label_quelle TEXT, reihenfolge INTEGER, geholt_am TEXT);
-- V3 Sujet (Entscheidung 04.11.2026): Bildmerkmale je Inhalt (OpenCLIP, float16), Textmerkmale je Begriff,
-- englische Bezeichnung der Anton-Schlagworte aus Wikidata (leer = keine) und Sujet als Kontext (JSON [[Begriff, Score]])
CREATE TABLE IF NOT EXISTS sujet_bild (
    sha256 TEXT PRIMARY KEY, vektor BLOB, modell TEXT, fehler TEXT, zeit TEXT);
CREATE TABLE IF NOT EXISTS sujet_text (
    text TEXT PRIMARY KEY, modell TEXT, vektor BLOB);
CREATE TABLE IF NOT EXISTS begriff_englisch (
    art TEXT, anton_id INTEGER, wikidata TEXT, englisch TEXT, geholt_am TEXT, PRIMARY KEY (art, anton_id));
-- Übersetzung der allgemeinen Sujet-Begriffe je Zielsprache (Weg: sprachmodell/mymemory/hand); geprüft = 1, wenn
-- von Hand bestätigt oder korrigiert (wird dann nie neu übersetzt)
CREATE TABLE IF NOT EXISTS begriff_uebersetzung (
    text TEXT, sprache TEXT, uebersetzung TEXT, weg TEXT, geprueft INTEGER, zeit TEXT, PRIMARY KEY (text, sprache));
CREATE TABLE IF NOT EXISTS sujet (
    sha256 TEXT PRIMARY KEY, begriffe TEXT, modell TEXT, zeit TEXT);
-- Zuordnung eines Ordners oder einer Datei zu einer Box oder Ebene (ziel "a:<Anton-ID>" / "e:<ebene_id>").
-- Stufe: item (Datei), file oder class (Ordner als Unterebene), "" (Ordner ohne eigene Ebene, Dateien nach oben).
-- Unterordner eines zugeordneten Ordners stehen mit eigener Zeile und demselben Ziel darunter; stufe_name: die in Anton
-- gewählte Stufe (Ordner auf die Halbbox gezogen), sonst leer
CREATE TABLE IF NOT EXISTS zuordnung (
    platte_id TEXT, pfad TEXT, ziel TEXT, stufe TEXT, wer TEXT, zeit TEXT, stufe_name TEXT, PRIMARY KEY (platte_id, pfad));
"""

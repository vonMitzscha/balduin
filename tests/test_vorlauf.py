"""Vorlauf ohne Platten: V8 Normdaten gegen ein kleines Anton-Vokabular in der Datenbank (ohne Netz: das Vokabular ist
frisch, vokabular_holen fragt Anton dann nicht). Läuft auch mit  pytest -m "not integration"."""
import pytest

from erfassung.basis import db, jetzt
from vorlauf import normdaten
from vorlauf.schema import SCHEMA_VORLAUF

VOKABULAR = [("actor", 7447, "Hunger, Nik", "Hunger, Nik", "Person"),
             ("actor", 12, "Müller, Hans Peter", "Müller, Hans Peter", "Person"),
             ("place", 154, "Zürich", "Zürich (ZH)", "Stadt, Dorf, …"),
             ("place", 79, "Zürich (Kanton)", "Zürich (Kanton) (ZH)", "Staat, Land, Region …"),
             ("keyword", 5, "Stahl", "Stahl", "")]


@pytest.fixture
def vorlauf(leeres_projekt):
    with db() as con:
        con.executescript(SCHEMA_VORLAUF)
        con.executemany("INSERT INTO anton_begriff VALUES (?,?,?,?,?,'[]',NULL,NULL,NULL,NULL,?)",
                        [(*z, jetzt()) for z in VOKABULAR])
        con.execute("INSERT INTO vorlauf_umfang VALUES ('HD01', 'Fotos/a.jpg')")
    return leeres_projekt


def kandidat(feld, wert, quelle="Metadaten (Urheber:in)", pfad="Fotos/a.jpg"):
    with db() as con:
        con.execute("INSERT INTO vorschlag (platte_id, pfad, feld, wert, quelle, score, beleg, schritt) "
                    "VALUES ('HD01', ?, ?, ?, ?, 0.6, 'x', 'V7')", (pfad, feld, wert, quelle))


def treffer():
    normdaten.normdaten_abgleichen()
    with db() as con:
        return {(f, a) for f, a in con.execute("SELECT feld, anton_id FROM vorschlag WHERE schritt = 'V8'")}


def test_urheber_mit_ort_wird_in_person_und_ort_zerlegt(vorlauf):
    """Corporate USB Test (05.11.2026): EXIF-Urheber „nik hunger, zuerich“ = Person und Ort in einem Wert."""
    kandidat("akteur", "nik hunger, zuerich")
    assert {("akteur", 7447), ("ort", 154)} <= treffer()


@pytest.mark.parametrize("wert", ["Hunger, Nik", "Nik Hunger", "© Nik Hunger", "Foto: Nik Hunger", "Nik Hunger / Zürich"])
def test_personen_in_beiden_namensfolgen_und_mit_vorsatz(vorlauf, wert):
    kandidat("akteur", wert)
    assert ("akteur", 7447) in treffer()


def test_ordnername_mit_person_und_ort(vorlauf):
    kandidat("begriff", "Hans Peter Müller", quelle="Ordnername", pfad="Fotos")
    kandidat("begriff", "Zuerich", quelle="Ordnername", pfad="Fotos")
    assert {("akteur", 12), ("ort", 154)} <= treffer()


def test_ohne_treffer_bleibt_der_ganze_wert_als_neu(vorlauf):
    kandidat("akteur", "Erika Muster, Basel")
    with db() as con:
        normdaten.normdaten_abgleichen()
        neu = con.execute("SELECT wert FROM vorschlag WHERE schritt = 'V8' AND anton_id IS NULL").fetchall()
    assert [z[0] for z in neu] == ["Erika Muster, Basel"]


@pytest.mark.parametrize("roh, erwartet", [
    ("Erika Muster", "Muster, Erika"),
    ("Hans Peter Meier", "Meier, Hans Peter"),
    ("erika muster", "Muster, Erika"),
    ("Vincent van Gogh", "Gogh, Vincent van"),
    ("Johann Wolfgang von Goethe", "Goethe, Johann Wolfgang von"),
    ("Martin Luther King Jr.", "King Jr., Martin Luther"),
    ("Muster, Erika", "Muster, Erika"),
    ("Muster", "Muster"),
    ("Muster AG", "Muster AG"),
    ("Studio 42", "Studio 42"),
    ("Meier & Söhne", "Meier & Söhne"),
])
def test_nachname_vorname(roh, erwartet):
    assert normdaten.nachname_vorname(roh) == erwartet


def test_neue_person_wird_als_nachname_vorname_vorgeschlagen(vorlauf):
    kandidat("akteur", "© Erika Muster")
    with db() as con:
        normdaten.normdaten_abgleichen()
        neu = con.execute("SELECT wert, beleg FROM vorschlag WHERE schritt = 'V8' AND feld = 'akteur'").fetchall()
    assert [z[0] for z in neu] == ["Muster, Erika"]
    assert "© Erika Muster" in neu[0][1]                # Beleg zeigt weiter den Originalwert

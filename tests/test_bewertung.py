"""Modul 2 Bewertung über die Server-API: Vererbung, eigene Entscheidungen, Aufheben, Schutzregel, Protokoll.
Jede Testdatei hat ihre eigene Projektkopie und ihren eigenen Server; die Tests hier nutzen je eigene Ordner."""
import pytest

from conftest import abfrage

pytestmark = pytest.mark.integration


def ziel(platte, pfad):
    return {"platte": platte, "pfad": pfad}


def entscheiden(balduin, ziele, entscheidung, **mehr):
    return balduin.post("/api/entscheiden", {"ziele": ziele, "entscheidung": entscheidung, "fassungen": False, **mehr})


def urteil(balduin, platte, pfad):
    return balduin.post("/api/knoten", {"ziele": [ziel(platte, pfad)]})[0]["urteil"]


def test_ordnerentscheidung_gilt_fuer_alle_dateien_darin(balduin):
    antwort = entscheiden(balduin, [ziel("HD01", "Fotos/2001")], "übernehmen")
    assert antwort["ok"] and antwort["dateien"] == 30
    u = urteil(balduin, "HD01", "Fotos/2001/Messe 2001/IMG_0005.JPG")
    assert u == {"entscheidung": "übernehmen", "vorbehalt": False, "eigen": False, "quelle": "Fotos/2001"}
    # gespeichert wird nur die eine Entscheidung am Ordner, nicht je Datei
    zeilen = abfrage(balduin.projekt, "SELECT pfad FROM entscheidung WHERE platte_id = 'HD01' AND pfad LIKE 'Fotos/2001%'")
    assert [z["pfad"] for z in zeilen] == ["Fotos/2001"]


def test_eigene_entscheidung_einer_datei_hat_vorrang(balduin):
    entscheiden(balduin, [ziel("HD01", "Fotos/2001")], "übernehmen")
    entscheiden(balduin, [ziel("HD01", "Fotos/2001/Messe 2001/IMG_0007.JPG")], "kassieren", begruendung="unscharf")
    assert urteil(balduin, "HD01", "Fotos/2001/Messe 2001/IMG_0007.JPG")["entscheidung"] == "kassieren"
    assert urteil(balduin, "HD01", "Fotos/2001/Messe 2001/IMG_0008.JPG")["entscheidung"] == "übernehmen"
    zaehler = balduin.post("/api/knoten", {"ziele": [ziel("HD01", "Fotos/2001")]})[0]["zaehler"]
    assert (zaehler["uebernehmen"], zaehler["kassieren"], zaehler["offen"]) == (29, 1, 0)


def test_aufheben_laesst_wieder_den_ordner_gelten(balduin):
    entscheiden(balduin, [ziel("HD01", "Fotos/2001")], "übernehmen")
    entscheiden(balduin, [ziel("HD01", "Fotos/2001/Messe 2001/IMG_0009.JPG")], "kassieren")
    entscheiden(balduin, [ziel("HD01", "Fotos/2001/Messe 2001/IMG_0009.JPG")], None)
    assert urteil(balduin, "HD01", "Fotos/2001/Messe 2001/IMG_0009.JPG") == {
        "entscheidung": "übernehmen", "vorbehalt": False, "eigen": False, "quelle": "Fotos/2001"}
    p = abfrage(balduin.projekt, "SELECT alt, neu FROM protokoll WHERE objekt = 'HD01:Fotos/2001/Messe 2001/IMG_0009.JPG' "
                                 "ORDER BY rowid")
    assert [z["neu"] for z in p] == ["kassieren", "aufgehoben"]


def test_vorbehalt_nur_beim_uebernehmen(balduin):
    entscheiden(balduin, [ziel("HD01", "Fotos/2003")], "übernehmen", vorbehalt=True)
    assert urteil(balduin, "HD01", "Fotos/2003")["vorbehalt"] is True
    entscheiden(balduin, [ziel("HD01", "Fotos/2003")], "zurückstellen", vorbehalt=True)
    assert urteil(balduin, "HD01", "Fotos/2003") == {"entscheidung": "zurückstellen", "vorbehalt": False, "eigen": True,
                                                     "quelle": "Fotos/2003"}


def test_jede_entscheidung_steht_im_protokoll(balduin):
    entscheiden(balduin, [ziel("HD01", "Fotos/2004")], "übernehmen", begruendung="Messe vollständig", wer="Test")
    entscheiden(balduin, [ziel("HD01", "Fotos/2004")], "kassieren", wer="Test")
    p = abfrage(balduin.projekt, "SELECT abschnitt, feld, alt, neu FROM protokoll WHERE objekt = 'HD01:Fotos/2004' "
                                 "ORDER BY rowid")
    assert p == [
        {"abschnitt": "Bewertung", "feld": "entscheidung", "alt": "",
         "neu": "übernehmen; Begründung: Messe vollständig; von Test"},
        {"abschnitt": "Bewertung", "feld": "entscheidung", "alt": "übernehmen; Begründung: Messe vollständig; von Test",
         "neu": "kassieren; von Test"},
    ]


def test_schutzregel_fragt_bevor_die_letzte_kopie_kassiert_wird(balduin):
    """Texte liegen auf HD01 und (als Backup) auf HD02. Die erste Platte darf ohne Rückfrage kassieren; wer danach auch
    die letzte Kopie kassiert, bekommt eine Warnung, und es wird nichts geschrieben, bis sie bestätigt ist."""
    assert entscheiden(balduin, [ziel("HD02", "Backup 2012/Texte")], "kassieren").get("ok")
    antwort = entscheiden(balduin, [ziel("HD01", "Texte")], "kassieren")
    assert antwort["warnung"]["inhalte"] == 4
    assert abfrage(balduin.projekt, "SELECT * FROM entscheidung WHERE platte_id = 'HD01' AND pfad = 'Texte'") == []
    assert entscheiden(balduin, [ziel("HD01", "Texte")], "kassieren", bestaetigt=True).get("ok")
    assert urteil(balduin, "HD01", "Texte/Bericht_2001.docx")["entscheidung"] == "kassieren"


def test_falsche_angaben_werden_abgewiesen(balduin):
    status, antwort = balduin.roh("POST", "/api/entscheiden", {"ziele": [ziel("HD01", "Fotos")], "entscheidung": "löschen"})
    assert status == 500 and "unbekannte Entscheidung" in antwort["fehler"]
    status, antwort = balduin.roh("POST", "/api/entscheiden", {"ziele": [ziel("HD01", "gibt/es/nicht.jpg")],
                                                               "entscheidung": "kassieren"})
    assert status == 500 and "nicht im Inventar" in antwort["fehler"]


def test_erschliessungshinweis_bleibt_unabhaengig_von_der_entscheidung(balduin):
    balduin.post("/api/hinweis", {"platte": "HD01", "pfad": "Formate", "hinweis": "zu Messe 2003 stellen", "wer": "Test"})
    entscheiden(balduin, [ziel("HD01", "Formate")], "kassieren", bestaetigt=True)
    entscheiden(balduin, [ziel("HD01", "Formate")], None)
    assert abfrage(balduin.projekt, "SELECT hinweis FROM erschliessungshinweis WHERE platte_id = 'HD01' AND "
                                    "pfad = 'Formate'") == [{"hinweis": "zu Messe 2003 stellen"}]


def test_formattabelle_zeigt_die_archivfaehigkeit_je_endung(balduin):
    """Regel-Editor, Formate: je Endung die schlechteste Ampel der Dateien darin und die Zahl je Ampel (Tooltip)."""
    d = balduin.post("/api/regeln", {"ziele": [ziel("HD01", "")], "grenze": 300, "jedes": 10})
    ampeln = {z["relpfad"].rsplit(".", 1)[-1].lower(): z["ampel"] for z in abfrage(balduin.projekt,
              "SELECT s.relpfad, a.ampel FROM schnellscan s JOIN archiv a USING (platte_id, relpfad) "
              "WHERE s.platte_id = 'HD01'")}
    assert ampeln, "Testplatte ohne Ampeln"
    rang = {"rot": 0, "gelb": 1, "grün": 2}
    for f in d["formate"]:
        assert set(f["ampeln"]) <= {"grün", "gelb", "rot", "ohne_ampel"}
        assert sum(f["ampeln"].values()) == f["gesamt"]
        bekannt = [a for a in ("rot", "gelb", "grün") if f["ampeln"].get(a)]
        assert f["ampel"] == (min(bekannt, key=rang.get) if bekannt else "")
    assert any(f["ampel"] for f in d["formate"])

"""Modul 3 Erschließung über die Server-API: Werte am Element, Vererben, nur Übernommenes, Bestandsboxen aus dem
nachgebauten Anton, Zuordnen. Vorher wird HD01/Fotos übernommen (einmal für diese Datei)."""
import json

import pytest

from conftest import abfrage

pytestmark = pytest.mark.integration

MESSE = "Fotos/2002/Messe 2002"
BILD = "Fotos/2001/Messe 2001/IMG_0001.JPG"


def ziel(platte, pfad):
    return {"platte": platte, "pfad": pfad}


def werte(balduin, platte, pfad):
    """Eigene Werte eines Elements aus der Datenbank: {feld: (gleich, je_datei, quelle)}."""
    return {z["feld"]: (z["gleich"], z["je_datei"], z["quelle"]) for z in abfrage(
        balduin.projekt, "SELECT * FROM erschliessung WHERE platte_id = ? AND pfad = ?", platte, pfad)}


def speichern(balduin, ziele, felder, erwartet=200, **mehr):
    return balduin.post("/api/es_speichern", {"ziele": ziele, "felder": felder, "wer": "Test", **mehr}, erwartet)


# Laufzeit wie in der Oberfläche: [von, bis, ca_von, ca_bis], Daten als „TT.MM.JJJJ“, „MM.JJJJ“ oder „JJJJ“
TITEL_UND_ZEITRAUM = {"titel": {"gleich": "Messestand der Muster AG"},
                      "zeitraum": {"gleich": ["01.05.2001", "03.05.2001", False, False]}}


@pytest.fixture(scope="module", autouse=True)
def fotos_uebernommen(balduin):
    balduin.post("/api/entscheiden", {"ziele": [ziel("HD01", "Fotos")], "entscheidung": "übernehmen", "fassungen": False})


def test_titel_und_zeitraum_machen_eine_datei_erschlossen(balduin):
    antwort = speichern(balduin, [ziel("HD01", BILD)], TITEL_UND_ZEITRAUM)
    assert antwort["geaendert"] == 2
    assert werte(balduin, "HD01", BILD) == {
        "titel": ("Messestand der Muster AG", "", "eigen"),
        "zeitraum": (json.dumps(["01.05.2001", "03.05.2001", False, False]), "", "eigen")}
    kinder = {d["pfad"]: d for d in balduin.get("/api/es_kinder", platte="HD01", pfad="Fotos/2001/Messe 2001")["dateien"]}
    assert kinder[BILD]["erschlossen"] and kinder[BILD]["titel"] == "Messestand der Muster AG"
    assert not kinder["Fotos/2001/Messe 2001/IMG_0002.JPG"]["erschlossen"]
    p = abfrage(balduin.projekt, "SELECT feld, neu FROM protokoll WHERE abschnitt = 'Erschließung' AND objekt = ?",
                f"HD01:{BILD}")
    assert {z["feld"] for z in p} == {"titel", "zeitraum"}


@pytest.mark.parametrize("von, bis", [
    ("2001-05-01", "2001-05-03"),          # ISO statt TT.MM.JJJJ
    ("03.05.2001", "01.05.2001"),          # Ende vor dem Anfang
    ("01.13.2001", ""),                    # Monat 13
    ("", "2001"),                          # Anfang fehlt
])
def test_ungueltige_laufzeit_zaehlt_nicht_als_erschlossen(balduin, von, bis):
    pfad = "Fotos/2001/Messe 2001/IMG_0006.JPG"
    speichern(balduin, [ziel("HD01", pfad)], {"titel": {"gleich": "Stand"}, "zeitraum": {"gleich": [von, bis, False, False]}})
    kinder = {d["pfad"]: d for d in balduin.get("/api/es_kinder", platte="HD01", pfad="Fotos/2001/Messe 2001")["dateien"]}
    assert not kinder[pfad]["erschlossen"]


def test_unveraendert_speichern_schreibt_nichts(balduin):
    speichern(balduin, [ziel("HD01", BILD)], TITEL_UND_ZEITRAUM)
    vorher = abfrage(balduin.projekt, "SELECT COUNT(*) AS n FROM protokoll")[0]["n"]
    assert speichern(balduin, [ziel("HD01", BILD)], TITEL_UND_ZEITRAUM)["geaendert"] == 0
    assert abfrage(balduin.projekt, "SELECT COUNT(*) AS n FROM protokoll")[0]["n"] == vorher


def test_leeres_feld_entfernt_den_wert(balduin):
    pfad = "Fotos/2001/Messe 2001/IMG_0004.JPG"
    speichern(balduin, [ziel("HD01", pfad)], {"inhalt": {"gleich": "Besucher am Stand"}})
    speichern(balduin, [ziel("HD01", pfad)], {"inhalt": {"gleich": ""}})
    assert "inhalt" not in werte(balduin, "HD01", pfad)
    assert abfrage(balduin.projekt, "SELECT neu FROM protokoll WHERE objekt = ? AND feld = 'inhalt' ORDER BY rowid",
                   f"HD01:{pfad}")[-1]["neu"] == "entfernt"


def test_ordnerwerte_gelten_nur_am_ordner(balduin):
    """Seit 04.11.2026 erbt nichts still: Ein Titel am Ordner erschließt die Dateien darin nicht."""
    speichern(balduin, [ziel("HD01", MESSE)], TITEL_UND_ZEITRAUM)
    dateien = balduin.get("/api/es_kinder", platte="HD01", pfad=MESSE)["dateien"]
    assert len(dateien) == 30 and not any(d["erschlossen"] or d["titel"] for d in dateien)


def test_vererben_fuellt_die_dateien_mit_herkunft(balduin):
    speichern(balduin, [ziel("HD01", MESSE)], {"titel": {"gleich": "Messe 2002", "je_datei": "Bild {laufnummer}"},
                                               "zeitraum": {"gleich": ["2002", "2002", False, False]}})
    umfang = {"dateien": True, "ordner": False, "tief": True}
    pruefung = balduin.post("/api/es_vererben_pruefen", {"platte": "HD01", "pfad": MESSE, "felder": ["titel", "zeitraum"],
                                                         "umfang": umfang})
    assert pruefung["dateien"] == 30
    balduin.post("/api/es_vererben", {"platte": "HD01", "pfad": MESSE, "felder": ["titel", "zeitraum"], "umfang": umfang,
                                      "wer": "Test"})
    dateien = balduin.get("/api/es_kinder", platte="HD01", pfad=MESSE)["dateien"]
    assert all(d["erschlossen"] for d in dateien)
    w = werte(balduin, "HD01", f"{MESSE}/IMG_0003.JPG")
    assert w["titel"][2] == w["zeitraum"][2] == f"vererbt:HD01:{MESSE}"
    titel = sorted(d["titel"] for d in dateien)
    assert len(set(titel)) == 30 and all(t.startswith("Messe 2002") for t in titel)   # Teil je Datei aufgelöst


def test_vererben_ueberschreibt_nur_auf_wunsch(balduin):
    eigen = f"{MESSE}/IMG_0010.JPG"
    speichern(balduin, [ziel("HD01", MESSE)], {"inhalt": {"gleich": "Stand und Besucher"}})
    speichern(balduin, [ziel("HD01", eigen)], {"inhalt": {"gleich": "Nur der Stand"}})
    umfang = {"dateien": True, "ordner": False, "tief": True}
    balduin.post("/api/es_vererben", {"platte": "HD01", "pfad": MESSE, "felder": ["inhalt"], "umfang": umfang})
    assert werte(balduin, "HD01", eigen)["inhalt"][0] == "Nur der Stand"
    assert werte(balduin, "HD01", f"{MESSE}/IMG_0011.JPG")["inhalt"][0] == "Stand und Besucher"
    balduin.post("/api/es_vererben", {"platte": "HD01", "pfad": MESSE, "felder": ["inhalt"], "umfang": umfang,
                                      "ueberschreiben": True})
    assert werte(balduin, "HD01", eigen)["inhalt"][0] == "Stand und Besucher"


def test_nur_uebernommenes_wird_erschlossen(balduin):
    """HD02 ist nicht bewertet: Dort lässt sich nichts erschließen, und es wird nichts geschrieben."""
    status, antwort = balduin.roh("POST", "/api/es_speichern", {"ziele": [ziel("HD02", "Backup 2012/Fotos/2001")],
                                                                "felder": TITEL_UND_ZEITRAUM})
    assert status == 500 and "nichts Übernommenes" in antwort["fehler"]
    assert abfrage(balduin.projekt, "SELECT * FROM erschliessung WHERE platte_id = 'HD02'") == []


def test_bestandsbox_aus_anton_mit_eltern(balduin):
    box = balduin.post("/api/box_laden", {"kennung": "MA-FOTO-1"})["box"]
    assert (box["id"], box["titel"], box["laufzeit"], box["gesperrt"]) == (200, "Fotosammlung", "1950–2010", False)
    assert [e["id"] for e in box["eltern"]] == [100]
    z = abfrage(balduin.projekt, "SELECT anton_id, signatur, eltern FROM bestandsbox WHERE anton_id = 200")[0]
    assert z["signatur"] == "MA-FOTO-1" and json.loads(z["eltern"])[0]["signatur"] == "MA"


def test_interne_box_nur_mit_token_und_als_gesperrt_markiert(balduin):
    box = balduin.post("/api/box_laden", {"kennung": "300"})["box"]
    assert box["zugang"] == "intern" and box["gesperrt"] is True


def test_unbekannte_box_wird_verstaendlich_abgewiesen(balduin):
    status, antwort = balduin.roh("POST", "/api/box_laden", {"kennung": "MA-GIBT-ES-NICHT"})
    assert status == 500 and "keine Einheit" in antwort["fehler"]


def test_zuordnen_nur_erschlossener_dateien(balduin):
    balduin.post("/api/box_laden", {"kennung": "MA-FOTO-1"})
    speichern(balduin, [ziel("HD01", BILD)], TITEL_UND_ZEITRAUM)
    status, antwort = balduin.roh("POST", "/api/es_zuordnen", {"ziele": [ziel("HD01", "Fotos/2001/Messe 2001/IMG_0020.JPG")],
                                                               "ziel": "a:200"})
    assert status == 500 and "nicht erschlossen" in antwort["fehler"]
    assert balduin.post("/api/es_zuordnen", {"ziele": [ziel("HD01", BILD)], "ziel": "a:200"})["zugeordnet"] == 1
    assert abfrage(balduin.projekt, "SELECT ziel, stufe FROM zuordnung WHERE platte_id = 'HD01' AND pfad = ?",
                   BILD) == [{"ziel": "a:200", "stufe": "item"}]


def test_box_mit_zuordnung_laesst_sich_nicht_entfernen(balduin):
    balduin.post("/api/box_laden", {"kennung": "MA-FOTO-1"})
    speichern(balduin, [ziel("HD01", BILD)], TITEL_UND_ZEITRAUM)
    balduin.post("/api/es_zuordnen", {"ziele": [ziel("HD01", BILD)], "ziel": "a:200"})
    status, antwort = balduin.roh("POST", "/api/box_entfernen", {"anton_id": 200})
    assert status == 500 and "nicht leer" in antwort["fehler"]


def test_stufen_kommen_aus_anton_ohne_einzelstueck(balduin):
    stufen = balduin.get("/api/anton_stufen")
    assert stufen["aus_anton"]
    assert {s["name"]: s["import"] for s in stufen["liste"]} == {
        "Archiv": "class", "Bestandsgruppe": "class", "Bestand": "class", "Klasse": "class", "Serie": "class",
        "Dossier": "file"}


# ---- Ordner als ein Einzelstück mit mehreren Medien (Entscheidung 05.11.2026) ----

EINZEL = "Fotos/2003"                    # mit Unterordner „Messe 2003“; in diesem Modul sonst nicht angefasst


def test_stufen_nennen_das_einzelstueck_fuer_ordner(balduin):
    assert balduin.get("/api/anton_stufen")["einzelstueck"] == "Einzelstück"


def test_ordner_als_einzelstueck_braucht_nur_eigene_werte(balduin):
    balduin.post("/api/box_laden", {"kennung": "MA-FOTO-1"})
    stufen = {f"HD01|{EINZEL}": "item"}
    p = balduin.post("/api/es_zuordnen_pruefen", {"ziele": [ziel("HD01", EINZEL)], "ziel": "a:200", "stufen": stufen})
    assert [o["pfad"] for o in p["ordner"]] == [EINZEL]          # Unterordner werden keine Ebenen
    assert p["nicht_erschlossen"] == 0 and p["dateien"] > 1      # Dateien darin brauchen keine eigenen Werte
    assert p["ordner"][0]["fehlt"] == ["eigener Titel", "Entstehungszeitraum"]
    status, antwort = balduin.roh("POST", "/api/es_zuordnen", {"ziele": [ziel("HD01", EINZEL)], "ziel": "a:200",
                                                               "stufen": stufen})
    assert status == 500 and "eigener Titel" in antwort["fehler"]
    speichern(balduin, [ziel("HD01", EINZEL)], TITEL_UND_ZEITRAUM)
    r = balduin.post("/api/es_zuordnen", {"ziele": [ziel("HD01", EINZEL)], "ziel": "a:200", "stufen": stufen,
                                          "namen": {f"HD01|{EINZEL}": "Einzelstück"}})
    assert r["zugeordnet"] == 1 and r["dateien"] == p["dateien"]
    assert abfrage(balduin.projekt, "SELECT pfad, stufe, stufe_name FROM zuordnung WHERE platte_id = 'HD01' AND pfad LIKE ?",
                   EINZEL + "%") == [{"pfad": EINZEL, "stufe": "item", "stufe_name": "Einzelstück"}]
    dateien = balduin.get("/api/es_kinder", platte="HD01", pfad=f"{EINZEL}/Messe 2003")["dateien"]
    assert dateien and all(f["erschlossen"] and f["zugeordnet"] for f in dateien)
    assert not werte(balduin, "HD01", dateien[0]["pfad"])        # erschlossen über den Ordner, ohne eigene Werte


def test_einzelstueck_laesst_sich_nicht_zur_ebene_umstellen(balduin):
    status, antwort = balduin.roh("POST", "/api/es_zuordnung_stufe", {"platte": "HD01", "pfad": EINZEL, "stufe_name": "Dossier"})
    assert status == 500 and "neu zuordnen" in antwort["fehler"]


def test_einzelstueck_steht_mit_seinen_medien_in_der_box(balduin):
    box = next(b for b in balduin.get("/api/boxen")["boxen"] if b["anton_id"] == 200)
    e = next(u for u in box["einheiten"] if u.get("pfad") == EINZEL)
    assert e["einzelstueck"] and e["stufe_name"] == "Einzelstück" and e["titel"] == "Messestand der Muster AG"
    assert e["dateien"] > 1 and {g["ordner"] for g in e["herkunft"]} >= {f"{EINZEL}/Messe 2003"}


def test_tagesdatum_ohne_ende_bleibt_ohne_ende(balduin):
    """Das Importformat verlangt kein Ende (Feedback 05.11.2026): ein einzelnes Datum wird gespeichert, wie es ist."""
    pfad = "Fotos/2001/Messe 2001/IMG_0007.JPG"
    speichern(balduin, [ziel("HD01", pfad)], {"titel": {"gleich": "Stand"},
                                              "zeitraum": {"gleich": ["02.05.2001", "", False, False]}})
    assert json.loads(werte(balduin, "HD01", pfad)["zeitraum"][0])[:2] == ["02.05.2001", ""]
    kinder = {d["pfad"]: d for d in balduin.get("/api/es_kinder", platte="HD01", pfad="Fotos/2001/Messe 2001")["dateien"]}
    assert kinder[pfad]["erschlossen"]


def test_register_fuer_akteure_und_orte_neben_dem_ereignis(balduin):
    """Akteur:in und Ort der Entstehung (je einer, am Ereignis) und daneben Listen im Register (05.11.2026)."""
    pfad = "Fotos/2001/Messe 2001/IMG_0008.JPG"
    speichern(balduin, [ziel("HD01", pfad)], {
        "akteur": {"gleich": {"name": "Hunger, Nik", "anton_id": 7447}},
        "akteure": {"gleich": [{"name": "Muster, Erika", "anton_id": 12}, {"name": "Neu, Person", "anton_id": None}]},
        "orte": {"gleich": [{"name": "Zürich", "anton_id": 154}]}})
    w = werte(balduin, "HD01", pfad)
    assert json.loads(w["akteur"][0]) == {"name": "Hunger, Nik", "anton_id": 7447}
    assert [x["name"] for x in json.loads(w["akteure"][0])] == ["Muster, Erika", "Neu, Person"]
    assert json.loads(w["orte"][0]) == [{"name": "Zürich", "anton_id": 154}]
    angaben = balduin.post("/api/es_angaben", {"ziele": [ziel("HD01", pfad)]})
    assert {"akteure", "orte"} <= set(angaben["felder"])


def test_sprachen_aus_der_festen_liste(balduin):
    """Sprache (Entscheidung 14.11.2026): Suche in Balduins Liste der ISO-639-2-Codes, wie Anton sie speichert;
    gespeichert werden Name und Code."""
    treffer = balduin.get("/api/es_begriffe", art="language", q="deu")["treffer"]
    assert treffer[0]["code"] == "ger" and treffer[0]["name"] == "Deutsch"
    assert balduin.get("/api/es_begriffe", art="language", q="fre")["treffer"][0]["code"] == "fre"   # auch über den Code
    pfad = "Fotos/2001/Messe 2001/IMG_0009.JPG"
    speichern(balduin, [ziel("HD01", pfad)], {"sprachen": {"gleich": [{"name": "Deutsch", "code": "ger"}]}})
    assert json.loads(werte(balduin, "HD01", pfad)["sprachen"][0]) == [{"name": "Deutsch", "code": "ger"}]
    assert "sprachen" in balduin.post("/api/es_angaben", {"ziele": [ziel("HD01", pfad)]})["felder"]


def test_gespeicherte_laufzeit_steht_wieder_im_editor(balduin):
    """Fehler 05.11.2026: ein übernommener Datumsvorschlag war nach dem Speichern wieder weg."""
    for pfad in ("Fotos/2001/Messe 2001/IMG_0009.JPG", "Fotos/2001/Messe 2001"):
        for zeitraum in (["02.05.2001", "", False, False], ["05.2001", "05.2001", False, False], ["2001", "2002", True, False]):
            speichern(balduin, [ziel("HD01", pfad)], {"zeitraum": {"gleich": zeitraum}})
            f = balduin.post("/api/es_angaben", {"ziele": [ziel("HD01", pfad)]})["felder"]["zeitraum"]
            assert f["eigen"] and json.loads(f["eigen"]["gleich"])[0] == zeitraum[0], (pfad, zeitraum, f)

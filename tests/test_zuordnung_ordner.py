"""Zuordnen in eine Ordner-Einheit und gesammelt lösen (Entscheidung 06.11.2026).

Ein Ordner, der eine eigene Ebene geworden ist, nimmt auch einzelne Dateien von anderswo auf (Ziel „o:<Platte>|<Ordner>“);
im Export hängen sie unter der Einheit des Ordners. Zuordnungen lassen sich je Herkunftsgruppe oder für eine ganze
Auswahl auf einmal lösen. Die Tests bauen aufeinander auf."""
import json
import shutil

import pytest

from conftest import abfrage

pytestmark = pytest.mark.integration

ORDNER = "Fotos/2002/Messe 2002"
O_ZIEL = f"o:HD01|{ORDNER}"
HERKUNFT = "Fotos/2001/Messe 2001"
FREMD = [f"{HERKUNFT}/IMG_0001.JPG", f"{HERKUNFT}/IMG_0002.JPG"]
TITEL = "Messe 2002, Stand"


def ziel(platte, pfad):
    return {"platte": platte, "pfad": pfad}


def zuordnung(balduin, pfad):
    return abfrage(balduin.projekt, "SELECT ziel, stufe FROM zuordnung WHERE platte_id = 'HD01' AND pfad = ?", pfad)


def ordner_einheit(balduin):
    box = next(b for b in balduin.get("/api/boxen")["boxen"] if b["anton_id"] == 200)
    return next(u for u in box["einheiten"] if u.get("pfad") == ORDNER)


@pytest.fixture(scope="module", autouse=True)
def vorbereitet(balduin):
    """HD01/Fotos übernehmen, den Ordner und alle Dateien darin sowie FREMD erschließen, den Ordner als Dossier
    der Box MA-FOTO-1 zuordnen."""
    balduin.post("/api/entscheiden", {"ziele": [ziel("HD01", "Fotos")], "entscheidung": "übernehmen", "fassungen": False})
    balduin.post("/api/box_laden", {"kennung": "MA-FOTO-1"})
    dateien = [z["relpfad"] for z in abfrage(balduin.projekt, "SELECT relpfad FROM datei WHERE platte_id = 'HD01' "
                                             "AND relpfad LIKE ?", ORDNER + "/%")]
    zeitraum = {"gleich": ["05.2002", "", False, False]}
    balduin.post("/api/es_speichern", {"ziele": [ziel("HD01", ORDNER)], "felder": {
        "titel": {"gleich": TITEL}, "zeitraum": zeitraum, "inhalt": {"gleich": "Aufnahmen vom Stand"}}})
    balduin.post("/api/es_speichern", {"ziele": [ziel("HD01", p) for p in dateien + FREMD], "felder": {
        "titel": {"gleich": "Messestand"}, "zeitraum": zeitraum}})
    r = balduin.post("/api/es_zuordnen", {"ziele": [ziel("HD01", ORDNER)], "ziel": "a:200",
                                          "stufen": {f"HD01|{ORDNER}": "file"}, "namen": {f"HD01|{ORDNER}": "Dossier"}})
    assert r["zugeordnet"] >= 1


def test_ordner_einheit_ist_ein_ziel(balduin):
    e = ordner_einheit(balduin)
    assert e["ziel"] == O_ZIEL and not e["einzelstueck"]


def test_datei_laesst_sich_in_die_ordner_einheit_zuordnen(balduin):
    p = balduin.post("/api/es_zuordnen_pruefen", {"ziele": [ziel("HD01", FREMD[0])], "ziel": O_ZIEL})
    assert p["ziel_name"] == TITEL and p["nicht_erschlossen"] == 0
    assert balduin.post("/api/es_zuordnen", {"ziele": [ziel("HD01", FREMD[0])], "ziel": O_ZIEL})["zugeordnet"] == 1
    assert zuordnung(balduin, FREMD[0]) == [{"ziel": O_ZIEL, "stufe": "item"}]
    kinder = {f["pfad"]: f for f in balduin.get("/api/es_kinder", platte="HD01", pfad=HERKUNFT)["dateien"]}
    assert kinder[FREMD[0]]["zugeordnet"] and kinder[FREMD[0]]["zuordnung"]["name"] == TITEL


def test_ordner_einheit_zeigt_die_datei_von_anderswo(balduin):
    gruppe = next(g for g in ordner_einheit(balduin)["herkunft"] if g["ordner"] == HERKUNFT)
    assert [f["pfad"] for f in gruppe["dateien"]] == [FREMD[0]] and gruppe["eigen"] == 1


def test_ordner_lassen_sich_nicht_in_eine_ordner_einheit_ziehen(balduin):
    status, antwort = balduin.roh("POST", "/api/es_zuordnen", {"ziele": [ziel("HD01", HERKUNFT)], "ziel": O_ZIEL})
    assert status == 500 and "nur einzelne Dateien" in antwort["fehler"]


def test_ordner_ohne_eigene_ebene_ist_kein_ziel(balduin):
    status, antwort = balduin.roh("POST", "/api/es_zuordnen", {"ziele": [ziel("HD01", FREMD[1])], "ziel": f"o:HD01|{HERKUNFT}"})
    assert status == 500 and "gibt es nicht" in antwort["fehler"]


def test_export_haengt_die_datei_unter_den_ordner(balduin, projekt):
    ablage = projekt.volumes / "Ablage-Ordner"
    ablage.mkdir()
    try:
        balduin.post("/api/export_ablage", {"mountpunkt": str(ablage)})
        r = balduin.post("/api/export_planen", {"wer": "Test", "verwerfen_ok": True})
        assert r["ok"] and r["schemafehler"] == 0
        eintraege = {z["schluessel"]: json.loads(z["eintrag"]) for z in abfrage(
            projekt.ordner, "SELECT schluessel, eintrag FROM paket_eintrag WHERE eintrag IS NOT NULL")}
        ordner = eintraege[f"o:HD01|{ORDNER}"]
        assert ordner["type"] == "collection" and ordner["title"] == {"de": TITEL}
        assert eintraege[f"d:HD01|{FREMD[0]}"]["parent"] == {"uuid": ordner["uuid"]}
    finally:
        shutil.rmtree(ablage, ignore_errors=True)


def test_herkunftsgruppe_auf_einmal_loesen(balduin):
    balduin.post("/api/es_zuordnen", {"ziele": [ziel("HD01", p) for p in FREMD], "ziel": O_ZIEL})
    r = balduin.post("/api/es_zuordnung_loesen", {"ziel": O_ZIEL, "platte": "HD01", "ordner": HERKUNFT})
    assert r["geloest"] == 2
    assert all(not zuordnung(balduin, p) for p in FREMD)
    assert zuordnung(balduin, ORDNER) == [{"ziel": "a:200", "stufe": "file"}]     # die Einheit selbst bleibt


def test_auswahl_auf_einmal_loesen(balduin):
    balduin.post("/api/es_zuordnen", {"ziele": [ziel("HD01", p) for p in FREMD], "ziel": "a:200"})
    a = balduin.post("/api/es_angaben", {"ziele": [ziel("HD01", p) for p in FREMD] + [ziel("HD01", "Fotos/2003")]})
    assert a["selbst_zugeordnet"] == 2                     # der Editor bietet „2 Zuordnungen lösen“ an
    r = balduin.post("/api/es_zuordnung_loesen", {"ziele": [ziel("HD01", p) for p in FREMD] + [ziel("HD01", "Fotos/2003")]})
    assert r["geloest"] == 2                               # nicht selbst Zugeordnetes zählt nicht
    assert all(not zuordnung(balduin, p) for p in FREMD)
    p = abfrage(balduin.projekt, "SELECT neu FROM protokoll WHERE objekt = ? AND feld = 'zuordnung' ORDER BY rowid",
                f"HD01:{FREMD[1]}")
    assert p[-1]["neu"].startswith("gelöst")


def test_loesen_der_ordner_einheit_loest_die_dateien_darin(balduin):
    balduin.post("/api/es_zuordnen", {"ziele": [ziel("HD01", FREMD[0])], "ziel": O_ZIEL})
    balduin.post("/api/es_zuordnung_loesen", {"platte": "HD01", "pfad": ORDNER})
    assert not zuordnung(balduin, ORDNER) and not zuordnung(balduin, FREMD[0])
    p = abfrage(balduin.projekt, "SELECT neu FROM protokoll WHERE objekt = ? AND feld = 'zuordnung' ORDER BY rowid",
                f"HD01:{FREMD[0]}")
    assert "Ordner-Einheit" in p[-1]["neu"]


def test_ordner_als_einzelstueck_loest_die_dateien_darin(balduin):
    stufen = {f"HD01|{ORDNER}": "file"}
    balduin.post("/api/es_zuordnen", {"ziele": [ziel("HD01", ORDNER)], "ziel": "a:200", "stufen": stufen})
    balduin.post("/api/es_zuordnen", {"ziele": [ziel("HD01", FREMD[0])], "ziel": O_ZIEL})
    balduin.post("/api/es_zuordnen", {"ziele": [ziel("HD01", ORDNER)], "ziel": "a:200", "stufen": {f"HD01|{ORDNER}": "item"}})
    assert not zuordnung(balduin, FREMD[0])

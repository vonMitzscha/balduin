"""Modul 4 mit einem Ordner als Einzelstück (Entscheidung 05.11.2026): ein record mit allen Dateien des Ordners als
Medien (files[]), im tar je Datei unter data/content/, Kontrolle je Datei. Die Tests bauen aufeinander auf."""
import json
import shutil
import tarfile

import pytest

from conftest import abfrage
from export import bauen

pytestmark = pytest.mark.integration

ORDNER = "Fotos/2001"                      # mit Unterordner „Messe 2001“


def ziel(platte, pfad):
    return {"platte": platte, "pfad": pfad}


@pytest.fixture(scope="module")
def ablage(balduin, projekt):
    ordner = projekt.volumes / "Ablage"
    ordner.mkdir()
    yield ordner
    shutil.rmtree(ordner, ignore_errors=True)


@pytest.fixture(scope="module")
def dateien(balduin, projekt, ablage):
    """HD01/Fotos/2001 übernehmen, nur den Ordner erschließen und als Einzelstück der Box MA-FOTO-1 zuordnen."""
    balduin.post("/api/entscheiden", {"ziele": [ziel("HD01", ORDNER)], "entscheidung": "übernehmen", "fassungen": False})
    pfade = [z["relpfad"] for z in abfrage(projekt.ordner, "SELECT relpfad FROM datei WHERE platte_id = 'HD01' AND "
                                           "relpfad LIKE ? AND relpfad NOT LIKE '%.DS_Store' ORDER BY relpfad", ORDNER + "/%")]
    assert len(pfade) > 1
    balduin.post("/api/es_speichern", {"ziele": [ziel("HD01", ORDNER)], "wer": "Test", "felder": {
        "titel": {"gleich": "Messe 2001, Bildfolge"}, "zeitraum": {"gleich": ["05.2001", "", False, False]},
        "inhalt": {"gleich": "Aufnahmen vom Messestand"},
        "akteur": {"gleich": {"name": "Hunger, Nik", "anton_id": 7447}},
        "orte": {"gleich": [{"name": "Zürich", "anton_id": 154}]},
        "akteure": {"gleich": [{"name": "Muster, Erika", "anton_id": 12}, {"name": "Neu, Nina"}]},
        "sprachen": {"gleich": [{"name": "Deutsch", "code": "ger"}, {"name": "Französisch", "code": "fre"}]}}})
    balduin.post("/api/box_laden", {"kennung": "MA-FOTO-1"})
    balduin.post("/api/es_zuordnen", {"ziele": [ziel("HD01", ORDNER)], "ziel": "a:200", "stufen": {f"HD01|{ORDNER}": "item"}})
    balduin.post("/api/export_importformat")
    s = balduin.get("/api/export")
    for p in next(p for p in s["freigabe"]["punkte"] if p["punkt"] == "lesefehler")["platten"]:
        if p["anzahl"] and not p["quittiert"]:
            balduin.post("/api/export_quittieren", {"platte_id": p["platte_id"]})
    balduin.post("/api/export_ablage", {"mountpunkt": str(ablage)})
    return pfade


def test_ordner_wird_ein_record_mit_allen_dateien(balduin, projekt, dateien):
    s = balduin.get("/api/export")
    assert s["exportierbar"] == len(dateien), s["fehler"] if "fehler" in s else s
    r = balduin.post("/api/export_planen", {"wer": "Test"})
    assert r["ok"] and r["schemafehler"] == 0 and r["dateien"] == len(dateien)
    paket = balduin.get("/api/export")["pakete"][0]
    assert paket["dateien"] == len(dateien) and paket["eintraege"] == 1
    zeilen = abfrage(projekt.ordner, "SELECT eintrag, relpfad FROM paket_eintrag ORDER BY nr")
    eintraege = [json.loads(z["eintrag"]) for z in zeilen if z["eintrag"]]
    assert len(eintraege) == 1
    e = eintraege[0]
    assert e["type"] == "record" and e["level_of_description"] == "item" and "parent" not in e
    assert e["title"] == {"de": "Messe 2001, Bildfolge"} and e["identifier_old"] == f"HD01:{ORDNER}"
    assert sorted(f["file_path"] for f in e["files"]) == dateien
    assert len({f["uuid"] for f in e["files"]}) == len(dateien)
    assert sorted(z["relpfad"] for z in zeilen) == dateien          # je Datei eine Zeile fürs Bauen und die Kontrolle


def test_laufzeit_akteur_und_register_orte_im_eintrag(balduin, projekt, dateien):
    """Laufzeit mit Anfang und Ende (ein Monat → beide gleich), Akteur:in am Entstehungsereignis, Orte des Registers als
    places[]; Akteur:innen des Registers als actors[] (Format 0.8): bekannte als ID, unbekannte mit Namen."""
    e = next(json.loads(z["eintrag"]) for z in abfrage(projekt.ordner, "SELECT eintrag FROM paket_eintrag ORDER BY nr")
             if z["eintrag"])
    ereignis = e["events"][0]
    assert ereignis["date_start"] == ereignis["date_end"] and ereignis["actor"] == {"id": 7447}
    assert e["places"] == [{"id": 154}]
    assert e["actors"] == [{"id": 12}, {"label": {"de": "Neu, Nina"}}]


def test_sprachen_und_urspruengliche_dateinamen_im_eintrag(balduin, projekt, dateien):
    """Entscheidung 14.11.2026: Sprache als languages[] (ISO 639-2); Anton benennt Dateien beim Import um, darum geht
    der Name auf dem Datenträger als Notiz source_filename mit (beim Einzelstück je Datei eine Zeile)."""
    e = next(json.loads(z["eintrag"]) for z in abfrage(projekt.ordner, "SELECT eintrag FROM paket_eintrag ORDER BY nr")
             if z["eintrag"])
    assert e["languages"] == ["ger", "fre"]
    notiz = [n for n in e["notes"] if n["type"] == "source_filename"]
    assert notiz == [{"type": "source_filename", "locale": "de", "text": "\n".join(p.rsplit("/", 1)[-1] for p in dateien)}]


def test_packen_schreibt_alle_medien_ins_tar(balduin, projekt, dateien, ablage):
    balduin.post("/api/export_starten", {"platte_id": "HD01", "beschreibbar_ok": True})
    lauf = [x for x in balduin.laeufe_abwarten() if x["art"] == "export"][-1]
    assert lauf["status"] == "fertig", lauf["meldung"]
    p = balduin.get("/api/export")["pakete"][0]
    tar = ablage / "Balduin-Projekte" / "Testprojekt" / "export" / p["name"]
    erwartet = {z["relpfad"]: (z["md5"], z["sha256"]) for z in abfrage(
        projekt.ordner, "SELECT relpfad, md5, sha256 FROM paket_eintrag WHERE relpfad IS NOT NULL")}
    assert len(erwartet) == len(dateien) and bauen.bag_pruefen(tar, erwartet)[0] == []
    with tarfile.open(tar) as t:                           # der Nachbau liest 0.6: actors[] bleibt draußen
        md = json.load(t.extractfile(next(n for n in t.getnames() if n.endswith("data/meta/metadata.json"))))
    assert md["version"] == "0.6" and all("actors" not in e for e in md["entries"])


def test_kontrolle_je_datei(balduin, projekt, anton, dateien):
    balduin.post("/api/export_uebergeben", {"pakete": [balduin.get("/api/export")["pakete"][0]["paket_id"]], "notiz": "Test"})
    medien = [{"id": 9300 + i, "md5sum": z["md5"], "file_name": z["relpfad"].rsplit("/", 1)[-1], "size": z["groesse"],
               "mime_type": "image/jpeg"} for i, z in enumerate(abfrage(
                   projekt.ordner, "SELECT relpfad, md5, groesse FROM paket_eintrag WHERE relpfad IS NOT NULL"))]
    neu = {"id": 460, "identifier": "MA-FOTO-1-3", "title": "Messe 2001, Bildfolge", "level_of_description": "Einzelstück",
           "parent_id": 200, "permalink": "http://anton.test/objects/460", "media": medien}
    anton.objekte.append(neu)
    try:
        balduin.post("/api/anton_holen")
        balduin.laeufe_abwarten()
        r = balduin.post("/api/export_kontrolle")
    finally:
        anton.objekte.remove(neu)
    assert r.get("fehlt", 0) == 0 and r["da"] == len(dateien)
    assert balduin.get("/api/export")["pakete"][0]["status"] == "importiert"

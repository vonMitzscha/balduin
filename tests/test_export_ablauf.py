"""Modul 4 Bestand und Export über die Server-API, der ganze Weg (Entscheidung 05.11.2026): Übersicht → Freigabe →
Ablage und Pakete → HD01 packen (Lauf X0–X2) → Übergabe → Kontrolle in Anton → Abschlussbericht.

Planen und Packen gehen vor der Freigabe; die Übergabe an eine produktive Instanz braucht sie, an eine Testinstanz (hier der
Nachbau) wird ohne sie als Probe übergeben. Die Ablage ist ein eigener Ordner neben den Testplatten (gilt als beschreibbarer Datenträger), Anton der Nachbau.
Die Tests bauen aufeinander auf und laufen in dieser Reihenfolge."""
import re
import shutil

import pytest

from conftest import abfrage, fingerabdruck
from export import bauen
from hilfen.oberflaeche import export_zeichnen, node_da

pytestmark = pytest.mark.integration

ORDNER = "Fotos/2001"
PAKETNAME = re.compile(r"^[A-Za-z0-9_]+-agate-\d+\.tar$")


def ziel(platte, pfad):
    return {"platte": platte, "pfad": pfad}


def stand(balduin):
    return balduin.get("/api/export")


def gezeichnet(balduin):
    """Oberfläche von Modul 4 mit dem aktuellen Stand zeichnen (Node, ohne Browser)."""
    if not node_da():
        pytest.skip("node fehlt")
    return export_zeichnen(stand(balduin))


def punkt(s, name):
    return next(p for p in s["freigabe"]["punkte"] if p["punkt"] == name)


@pytest.fixture(scope="module")
def ablage(balduin, projekt):
    """Beschreibbarer „Datenträger“ für die Pakete; nach den Tests wieder weg (andere Tests zählen die Datenträger)."""
    ordner = projekt.volumes / "Ablage"
    ordner.mkdir()
    yield ordner
    shutil.rmtree(ordner, ignore_errors=True)


@pytest.fixture(scope="module")
def dateien(balduin, projekt):
    """HD01/Fotos/2001 übernehmen, jede Datei erschließen und der Bestandsbox MA-FOTO-1 (Anton-ID 200) zuordnen."""
    balduin.post("/api/entscheiden", {"ziele": [ziel("HD01", ORDNER)], "entscheidung": "übernehmen", "fassungen": False})
    pfade = [z["relpfad"] for z in abfrage(projekt.ordner, "SELECT relpfad FROM datei WHERE platte_id = 'HD01' AND "
                                           "relpfad LIKE ? AND relpfad NOT LIKE '%.DS_Store' ORDER BY relpfad", ORDNER + "/%")]
    assert pfade
    balduin.post("/api/es_speichern", {"ziele": [ziel("HD01", p) for p in pfade], "wer": "Test", "felder": {
        "titel": {"gleich": "Messestand der Muster AG"}, "zeitraum": {"gleich": ["01.05.2001", "03.05.2001", False, False]}}})
    balduin.post("/api/box_laden", {"kennung": "MA-FOTO-1"})
    assert balduin.post("/api/es_zuordnen", {"ziele": [ziel("HD01", p) for p in pfade], "ziel": "a:200"})["zugeordnet"] == len(pfade)
    return pfade


def test_uebersicht_zeigt_je_platte_was_bereit_ist(balduin, dateien):
    s = stand(balduin)
    hd01 = next(p for p in s["platten"] if p["platte_id"] == "HD01")
    assert hd01["bereit"] == len(dateien) and hd01["uebernommen"] >= len(dateien)
    assert s["exportierbar"] == len(dateien)


def test_uebersicht_nach_platten_und_nach_bestaenden(balduin, dateien):
    """Je Platte die Bestände, in die sie liefert, je Bestand die Platten, die er braucht (Feedback 05.11.2026)."""
    s = stand(balduin)
    hd01 = next(p for p in s["platten"] if p["platte_id"] == "HD01")
    b = next(x for x in hd01["bestaende"] if x["anton_id"] == 200)
    assert b["bereit"] == b["erschlossen"] == b["uebernommen"] == len(dateien) and b["signatur"] == "MA-FOTO-1"
    box = next(x for x in s["bestaende"] if x["anton_id"] == 200)
    assert [p["platte_id"] for p in box["platten"]] == ["HD01"] and box["platten"][0]["bereit"] == len(dateien)
    assert box["bereit"] == len(dateien) and box["aufgaben"] == []


def test_uebersicht_sagt_was_zu_tun_ist(balduin, dateien):
    """Übernommen, aber nicht zugeordnet: als Aufgabe mit dem Modul, das sie löst, je Platte und beim Bestand „ohne Box“."""
    balduin.post("/api/entscheiden", {"ziele": [ziel("HD01", "Fotos/2002")], "entscheidung": "übernehmen", "fassungen": False})
    try:
        s = stand(balduin)
        hd01 = next(p for p in s["platten"] if p["platte_id"] == "HD01")
        auf = {x["schluessel"]: x for x in hd01["aufgaben"]}
        assert auf["nicht_zugeordnet"]["ansicht"] == "erschliessung" and auf["nicht_zugeordnet"]["tun"]
        ohne = next(x for x in s["bestaende"] if x["anton_id"] is None)
        assert ohne["platten"][0]["platte_id"] == "HD01"
        assert {x["schluessel"] for x in ohne["aufgaben"]} >= {"nicht_zugeordnet"}
        assert all(f["tun"] and f["ansicht"] for f in s["kontrolle"]["fehler"])
    finally:
        balduin.post("/api/entscheiden", {"ziele": [ziel("HD01", "Fotos/2002")], "entscheidung": "kassieren", "fassungen": False})


def test_oberflaeche_anfangs_mit_erster_aufgabe_ablage_waehlen(balduin, dateien):
    html = gezeichnet(balduin)
    assert "MA-FOTO-1" in html and "Ablage und Paketgröße wählen" in html and "Packen beginnen" not in html


def test_freigabe_ist_anfangs_offen(balduin, dateien):
    s = stand(balduin)
    assert not punkt(s, "importformat")["ok"] and not s["freigabe"]["ok"]
    assert s["probe"]                                           # Nachbau auf 127.0.0.1, keine produktive Instanz


def test_quellplatte_ist_keine_ablage(balduin, projekt, ablage):
    angebot = {a["mountpunkt"] for a in balduin.get("/api/export_ablagen")["ablagen"]}
    assert str(ablage) in angebot and "projekt" in angebot
    assert str(projekt.volumes / "HD01") not in angebot and str(projekt.volumes / "HD02") not in angebot
    status, antwort = balduin.roh("POST", "/api/export_ablage", {"mountpunkt": str(projekt.volumes / "HD01")})
    assert status >= 400


def test_planen_vor_der_freigabe_braucht_nur_die_ablage(balduin, dateien, ablage):
    status, antwort = balduin.roh("POST", "/api/export_planen", {})
    assert status >= 400 and "Ablage" in antwort["fehler"]
    balduin.post("/api/export_ablage", {"mountpunkt": str(ablage)})
    # Teilbestand: ein weiterer Ordner ist übernommen, aber noch nicht erschlossen; er bleibt draußen
    balduin.post("/api/entscheiden", {"ziele": [ziel("HD01", "Fotos/2002")], "entscheidung": "übernehmen", "fassungen": False})
    s = stand(balduin)
    assert not s["freigabe"]["ok"] and not punkt(s, "erschliessung")["ok"]
    r = balduin.post("/api/export_planen", {"wer": "Test"})
    assert r["ok"] and r["schemafehler"] == 0 and r["dateien"] == len(dateien)
    pakete = stand(balduin)["pakete"]
    assert [p["art"] for p in pakete] == ["teil"]
    assert all(PAKETNAME.match(p["name"]) and p["name"].endswith("-agate-200.tar") for p in pakete)
    assert pakete[0]["dateien"] == len(dateien) and pakete[0]["status"] == "geplant"
    # für die spätere Freigabe wieder heraus (in der Bewertung entschieden)
    balduin.post("/api/entscheiden", {"ziele": [ziel("HD01", "Fotos/2002")], "entscheidung": "kassieren", "fassungen": False})


def test_hd01_packen_schreibt_ein_geprueftes_tar_auf_die_ablage(balduin, projekt, testplatten, dateien, ablage):
    balduin.post("/api/export_starten", {"platte_id": "HD01", "beschreibbar_ok": True})
    lauf = [x for x in balduin.laeufe_abwarten() if x["art"] == "export"][-1]
    assert lauf["status"] == "fertig", lauf["meldung"]
    schritte = {z["schritt"]: z["status"] for z in abfrage(projekt.ordner, "SELECT schritt, status FROM lauf_schritt "
                                                                          "WHERE lauf_id = ?", lauf["lauf_id"])}
    assert schritte == {"X0": "fertig", "X1": "fertig", "X2": "fertig"}
    p = stand(balduin)["pakete"][0]
    assert p["status"] == "gebaut" and p["geprueft_am"]
    ordner = ablage / "Balduin-Projekte" / "Testprojekt" / "export"
    tar = ordner / p["name"]
    assert tar.is_file() and not list(ordner.glob("*.teil"))
    erwartet = {z["relpfad"]: (z["md5"], z["sha256"]) for z in abfrage(
        projekt.ordner, "SELECT relpfad, md5, sha256 FROM paket_eintrag WHERE relpfad IS NOT NULL")}
    assert bauen.bag_pruefen(tar, erwartet)[0] == []
    assert (ordner / "lieferung.csv").read_text(encoding="utf-8").count(p["name"]) == 1
    assert (ordner / "SHA256SUMS").read_text(encoding="utf-8").startswith(p["datei_sha256"])
    assert list((projekt.ordner / "sicherungen").glob("inventar_*.sqlite"))      # Datenbank vor dem Export gesichert
    assert fingerabdruck(projekt.volumes / "HD01") == testplatten.abdruck["HD01"]  # Quellplatte unverändert


def test_lieferschein_nennt_die_aufrufe_mit_ziel(balduin, ablage):
    """Weg C (Entscheidung 14.11.2026): sip:import-file liest das Ziel nicht aus dem Dateinamen; der Lieferschein nennt
    je Paket in Importreihenfolge erst den Trockenlauf, dann den Import, jeweils mit --parent aus dem Namen."""
    text = (ablage / "Balduin-Projekte" / "Testprojekt" / "export" / "LIESMICH.txt").read_text(encoding="utf-8")
    name = stand(balduin)["pakete"][0]["name"]
    trocken = f"php artisan sip:import-file --env=<Mandant> <Ordner>/{name} --parent=200 --dry-run"
    echt = f"php artisan sip:import-file --env=<Mandant> <Ordner>/{name} --parent=200 --user=<Konto>"
    assert trocken in text and echt in text and text.index(trocken) < text.index(echt)


def test_oberflaeche_nach_dem_packen_fuehrt_zur_uebergabe(balduin, dateien):
    html = gezeichnet(balduin)
    assert "Ablage an den Betreiber der Anton-Instanz" in html and 'data-ex-schritt="uebergabe"' in html
    assert "nachgeprüft" in html                                  # rechts unter „Pakete“


def anton_adresse(balduin, url, testinstanz=False):
    alt = stand(balduin)["einstellungen"]["anton_url"]
    balduin.post("/api/projekt_einstellungen", {"anton": {"url": url, "testinstanz": testinstanz}})
    return alt


def test_uebergabe_an_eine_produktive_instanz_braucht_die_freigabe(balduin, dateien):
    p = stand(balduin)["pakete"][0]
    alt = anton_adresse(balduin, "https://archiv.example.org")
    try:
        assert not stand(balduin)["probe"]
        status, antwort = balduin.roh("POST", "/api/export_uebergeben", {"pakete": [p["paket_id"]]})
        assert status >= 400 and "Freigabe" in antwort["fehler"]
    finally:
        anton_adresse(balduin, alt)
    assert stand(balduin)["pakete"][0]["status"] == "gebaut"


def test_als_testinstanz_markiert_gilt_als_probe(balduin, dateien):
    """Jede Adresse gilt als produktiv, außer lokal oder im Projekt als Testinstanz markiert (Entscheidung 12.11.2026)."""
    alt = anton_adresse(balduin, "https://archiv.example.org", testinstanz=True)
    try:
        assert stand(balduin)["probe"]
    finally:
        anton_adresse(balduin, alt)


def test_uebergabe_an_die_testinstanz_ohne_freigabe_ist_probe(balduin, dateien):
    p = stand(balduin)["pakete"][0]
    r = balduin.post("/api/export_uebergeben", {"pakete": [p["paket_id"]], "notiz": "Test: Ablage an K&R"})
    assert r["probe"]
    s = stand(balduin)
    assert s["pakete"][0]["status"] == "übergeben" and s["pakete"][0]["uebergabe"]["probe"]
    assert s["exportierbar"] == 0 and s["geliefert"] == len(dateien)
    alt = anton_adresse(balduin, "https://archiv.example.org")
    try:                                                        # für eine produktive Instanz ist nichts geliefert
        s = stand(balduin)
        assert s["exportierbar"] == len(dateien) and s["geliefert"] == 0
    finally:
        anton_adresse(balduin, alt)


def test_freigabe_mit_importformat_und_quittierten_lesefehlern(balduin, dateien):
    a = balduin.post("/api/export_importformat")
    assert a["reads"] == "0.6" and a["version"] == "0.6"
    for p in punkt(stand(balduin), "lesefehler")["platten"]:
        if p["anzahl"] and not p["quittiert"]:
            balduin.post("/api/export_quittieren", {"platte_id": p["platte_id"]})
    s = stand(balduin)
    assert s["freigabe"]["ok"], [(p["punkt"], p["text"]) for p in s["freigabe"]["punkte"] if not p["ok"]]


def test_formatrichtlinie_reject_haelt_die_freigabe_auf(balduin, anton, dateien):
    """K&R Frage 6: Bei „reject“ scheitert heute ein ganzes Paket an einer abgelehnten Datei."""
    alt = dict(anton.formatrichtlinie)
    anton.formatrichtlinie["FORMAT_VALIDATION_INVALID"] = "reject"
    try:
        balduin.post("/api/export_importformat")
        p = punkt(stand(balduin), "importformat")
        assert not p["ok"] and "reject" in p["text"]
    finally:
        anton.formatrichtlinie.clear()
        anton.formatrichtlinie.update(alt)
    balduin.post("/api/export_importformat")
    p = punkt(stand(balduin), "importformat")
    assert p["ok"] and p["formatrichtlinie"] == alt


def test_bestandsbox_im_akzessionsarchiv_wird_gewarnt(balduin, anton, dateien):
    anton.objekte.append({"id": 250, "identifier": "MA-AKZ", "title": "Akzessionsarchiv 2026", "level_of_description": "Bestand",
                          "parent_id": 100, "object_type": "", "permalink": "http://anton.test/objects/250", "media": []})
    try:
        balduin.post("/api/box_laden", {"kennung": "MA-AKZ"})
        warnung = stand(balduin)["kontrolle"]["akzession"]
        assert [b["anton_id"] for b in warnung] == [250]
        if node_da():
            assert "liegt wohl im Akzessionsarchiv" in gezeichnet(balduin)
    finally:
        balduin.post("/api/box_entfernen", {"anton_id": 250})
        anton.objekte.pop()
    assert stand(balduin)["kontrolle"]["akzession"] == []


def test_kontrolle_nur_mit_frischem_bestand(balduin, dateien):
    status, antwort = balduin.roh("POST", "/api/export_kontrolle", {})
    assert status >= 400 and "älter als" in antwort["fehler"]


def test_was_in_anton_fehlt_wird_wieder_offen(balduin, dateien):
    balduin.post("/api/anton_holen")
    balduin.laeufe_abwarten()
    r = balduin.post("/api/export_kontrolle")
    assert r["fehlt"] == len(dateien)
    s = stand(balduin)
    assert s["pakete"][0]["status"] == "unvollständig"
    assert s["exportierbar"] == len(dateien)                  # gleiche UUID, neu zu planen
    assert len(balduin.get("/api/export_abweichungen")["abweichungen"]) == len(dateien)


def test_von_anton_umbenannte_dateien_findet_die_kontrolle_ueber_die_altsignatur(balduin, projekt, anton, dateien):
    """Anton benennt Dateien beim Import nach der Signatur um (gesehen an einer Testinstanz 14.11.2026: IMG_0000.JPG →
    anl_18_6_1-0001.jpg) und führt den alten Namen nicht; wiedererkannt wird jede Datei an MD5 und identifier_old."""
    zeilen = abfrage(projekt.ordner, "SELECT platte_id, relpfad, md5, groesse FROM paket_eintrag WHERE relpfad IS NOT NULL")
    neu = [{"id": 460 + i, "identifier": f"MA-FOTO-1.{i + 1}", "identifier_old": f"{z['platte_id']}:{z['relpfad']}",
            "title": "Messestand", "level_of_description": "Einzelstück", "parent_id": 200,
            "permalink": f"http://anton.test/objects/{460 + i}",
            "media": [{"id": 9200 + i, "md5sum": z["md5"], "file_name": f"ma_foto_1_{i + 1}-0001.jpg", "size": z["groesse"],
                       "mime_type": "image/jpeg"}]} for i, z in enumerate(zeilen)]
    anton.objekte.extend(neu)
    try:
        balduin.post("/api/anton_holen")
        balduin.laeufe_abwarten()
        r = balduin.post("/api/export_kontrolle")
    finally:
        for o in neu:
            anton.objekte.remove(o)
    assert r.get("name", 0) == 0 and r.get("da") == len(dateien), r
    assert stand(balduin)["pakete"][0]["status"] == "importiert"


def test_angekommene_dateien_machen_das_paket_importiert(balduin, projekt, anton, dateien):
    medien = [{"id": 9100 + i, "md5sum": z["md5"], "file_name": z["relpfad"].rsplit("/", 1)[-1], "size": z["groesse"],
               "mime_type": "image/jpeg"} for i, z in enumerate(abfrage(
                   projekt.ordner, "SELECT relpfad, md5, groesse FROM paket_eintrag WHERE relpfad IS NOT NULL"))]
    neu = {"id": 450, "identifier": "MA-FOTO-1-2", "title": "Messestand", "level_of_description": "Einzelstück",
           "parent_id": 200, "permalink": "http://anton.test/objects/450", "media": medien}
    anton.objekte.append(neu)
    try:
        balduin.post("/api/anton_holen")
        balduin.laeufe_abwarten()
        r = balduin.post("/api/export_kontrolle")
    finally:
        anton.objekte.remove(neu)
    assert r.get("fehlt", 0) == 0 and r["da"] == len(dateien)
    s = stand(balduin)
    assert s["pakete"][0]["status"] == "importiert" and s["exportierbar"] == 0
    assert s["modul"]["in_anton"] == len(dateien)


def test_abschlussbericht_und_paketdatei_loeschen(balduin, projekt, ablage):
    r = balduin.post("/api/export_bericht")
    text = (projekt.ordner / "berichte" / r["datei"]).read_text(encoding="utf-8")
    assert "Abschlussbericht" in text and "kassiert" in text and "übernommen" in text
    p = stand(balduin)["pakete"][0]
    assert stand(balduin)["ablage"]["belegt"] == p["datei_bytes"]
    balduin.post("/api/export_datei_loeschen", {"paket_id": p["paket_id"]})
    assert not (ablage / "Balduin-Projekte" / "Testprojekt" / "export" / p["name"]).exists()
    assert stand(balduin)["pakete"][0]["status"] == "importiert"


def test_oberflaeche_am_ende_mit_kontrolle_und_bericht(balduin):
    html = gezeichnet(balduin)
    assert "in Anton" in html and "Abschlussbericht speichern" in html and "ex-nach-gesperrt" not in html

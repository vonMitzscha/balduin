"""Die harten Regeln aus CLAUDE.md als Tests. Bricht einer davon, ist eine Zusage von Balduin an das Archiv verletzt.

Regel 1  Quellplatten nur lesen               → test_quellplatten_*, Schutzwache (test_schutzwache.py);
         auch Ordner als Quelle (05.11.2026)   → test_quellordner_*, dazu test_quellen.py
         Ablage nur im eigenen Ordner          → test_export_schreibt_*
Regel 3  jede Änderung protokolliert          → test_schreibende_aufrufe_*, dazu test_bewertung/test_erschliessung
Regel 4  Kassieren heißt markieren            → test_kassieren_*
         Paket erst nach der Kontrolle löschen → test_uebergebenes_paket_*, test_unvollstaendiges_paket_*,
                                                 test_paket_wird_frei_*
Regel 6  Inhaltsanalyse bleibt lokal           → test_sprachmodell_*, test_anton_*, test_vorlauf_schickt_*,
         nichts nach Anton hochladen           → test_export_liest_*
Regel 7  Vorschläge nie automatisch           → test_vorschlaege_*
dazu     Anton-Token nie in Dateien oder URLs, Server nur für die eigene Oberfläche
"""
import json
import re
import shutil

import pytest

from conftest import TOKEN, abfrage, fingerabdruck

pytestmark = pytest.mark.integration


def ziel(platte, pfad):
    return {"platte": platte, "pfad": pfad}


@pytest.fixture(scope="module")
def vorlauf_gelaufen(balduin, anton):
    """HD01/Fotos übernommen, dann der Vorlauf mit V5, V7, V8, V10 als Hintergrundlauf über das Tool."""
    balduin.post("/api/entscheiden", {"ziele": [ziel("HD01", "Fotos")], "entscheidung": "übernehmen", "fassungen": False})
    vorher = len(anton.anfragen)
    erschliessung_vorher = abfrage(balduin.projekt, "SELECT * FROM erschliessung")
    balduin.post("/api/vorlauf_starten", {"schritte": ["V5", "V7", "V8", "V10"]})
    laeufe = balduin.laeufe_abwarten()
    return {"lauf": [l for l in laeufe if l["art"] == "vorlauf"][-1], "anfragen": anton.anfragen[vorher:],
            "erschliessung_vorher": erschliessung_vorher}


# ---------- Server nur für die eigene Oberfläche ----------

def test_ohne_sitzungscookie_keine_daten(balduin):
    status, antwort = balduin.roh("GET", "/api/stand", cookie=False)
    assert status == 403 and "Sitzung" in antwort["fehler"]


def test_fremde_adresse_wird_abgewiesen(balduin):
    """Schutz gegen DNS-Rebinding: Eine fremde Webseite, die auf 127.0.0.1 zeigt, schickt ihren eigenen Host."""
    status, antwort = balduin.roh("GET", "/api/stand", kopf={"Host": f"boese.example:{balduin.port}"})
    assert status == 403 and antwort["fehler"] == "fremde Adresse"


def test_fremder_origin_darf_nicht_schreiben(balduin):
    status, antwort = balduin.roh("POST", "/api/entscheiden", {"ziele": [ziel("HD01", "Fotos")], "entscheidung": "kassieren"},
                                  kopf={"Origin": "http://boese.example"})
    assert status == 403 and antwort["fehler"] == "fremder Origin"
    assert abfrage(balduin.projekt, "SELECT * FROM entscheidung WHERE entscheidung = 'kassieren' AND pfad = 'Fotos'") == []


def test_schreiben_nur_mit_json(balduin):
    """Ein Formular einer fremden Seite kann kein application/json schicken (CSRF)."""
    status, antwort = balduin.roh("POST", "/api/hinweis", b"platte=HD01", kopf={"Content-Type": "text/plain"})
    assert status == 403 and antwort["fehler"] == "nur JSON"


@pytest.mark.parametrize("adresse", ["/web/%2e%2e/%2e%2e/inventar.sqlite", "/web/..%2f..%2fprojekt.json",
                                     "/thumbs/%2e%2e/inventar.sqlite", "/etiketten/%2e%2e/projekt.json"])
def test_keine_dateien_ausserhalb_der_freigegebenen_ordner(balduin, adresse):
    status, _ = balduin.roh("GET", adresse)
    assert status == 404


# ---------- Regel 4: Kassieren heißt markieren ----------

def test_kassieren_der_ganzen_platte_loescht_nichts(balduin, testplatten):
    vorher = abfrage(balduin.projekt, "SELECT COUNT(*) AS n FROM datei WHERE platte_id = 'HD02'")[0]["n"]
    balduin.post("/api/entscheiden", {"ziele": [ziel("HD02", "")], "entscheidung": "kassieren", "fassungen": False,
                                      "bestaetigt": True})
    assert fingerabdruck(testplatten.volumes / "HD02") == testplatten.abdruck["HD02"]
    assert abfrage(balduin.projekt, "SELECT COUNT(*) AS n FROM datei WHERE platte_id = 'HD02'")[0]["n"] == vorher
    assert abfrage(balduin.projekt, "SELECT entscheidung FROM entscheidung WHERE platte_id = 'HD02' AND pfad = ''") == [
        {"entscheidung": "kassieren"}]


# ---------- Regel 3: jede Änderung im Protokoll ----------

@pytest.mark.parametrize("adresse, daten", [
    ("/api/entscheiden", {"ziele": [ziel("HD01", "Formate")], "entscheidung": "zurückstellen", "fassungen": False}),
    ("/api/hinweis", {"platte": "HD01", "pfad": "Formate", "hinweis": "prüfen"}),
    ("/api/box_laden", {"kennung": "MA-FOTO-1"}),
    ("/api/projekt_einstellungen", {"film": {"art": "raster", "bilder": 4}}),
])
def test_schreibende_aufrufe_hinterlassen_einen_protokolleintrag(balduin, adresse, daten):
    vorher = abfrage(balduin.projekt, "SELECT COUNT(*) AS n FROM protokoll")[0]["n"]
    balduin.post(adresse, daten)
    assert abfrage(balduin.projekt, "SELECT COUNT(*) AS n FROM protokoll")[0]["n"] > vorher


# ---------- Regel 6: Inhaltsanalyse bleibt lokal ----------

@pytest.mark.parametrize("sprachmodell", [
    {"anbieter": "openai", "adresse": "https://api.openai.com", "modell": "gpt-4o"},
    {"anbieter": "ollama", "adresse": "https://ollama.example.com", "modell": "qwen2.5:14b"},
])
def test_sprachmodell_in_der_cloud_ist_gesperrt(balduin, sprachmodell):
    vorher = (balduin.projekt / "projekt.json").read_text(encoding="utf-8")
    status, antwort = balduin.roh("POST", "/api/es_einstellungen", {"sprachmodell": sprachmodell})
    assert status == 500 and "Cloud" in antwort["fehler"]
    assert (balduin.projekt / "projekt.json").read_text(encoding="utf-8") == vorher


def test_vorlauf_schickt_nur_vokabularabfragen_hinaus(vorlauf_gelaufen):
    """V8 holt nur das öffentliche Anton-Vokabular, seitenweise und ohne Token; nie Pfade, Titel oder Inhalte."""
    assert vorlauf_gelaufen["lauf"]["status"] == "fertig", vorlauf_gelaufen["lauf"]["meldung"]
    anfragen = vorlauf_gelaufen["anfragen"]
    assert anfragen, "V8 hat das Vokabular nicht geholt"
    for a in anfragen:
        assert a["pfad"] in ("/api/keywords", "/api/places", "/api/actors", "/api/levels-of-description"), a
        assert re.fullmatch(r"(page=\d+&perPage=\d+)?", a["abfrage"]), a
        assert not a["token"], a


def test_anton_token_nur_im_header(anton, vorlauf_gelaufen):
    assert anton.anfragen and not any(a["token_in_url"] for a in anton.anfragen)


def test_anton_token_steht_in_keiner_datei_des_projekts(balduin, vorlauf_gelaufen):
    """Nach Analyse, Abruf aus Anton (mit Token), Boxen und Vorlauf: Der Token steht nirgends im Projektordner,
    weder in der Datenbank noch in Logs, CSV oder projekt.json."""
    balduin.post("/api/box_laden", {"kennung": "MA-INT-1"})
    gefunden = [p.relative_to(balduin.projekt).as_posix() for p in balduin.projekt.rglob("*")
                if p.is_file() and TOKEN.encode() in p.read_bytes()]
    assert gefunden == []


# ---------- Regel 7: Vorschläge nie automatisch ----------

def test_vorschlaege_entstehen_aber_werden_nicht_uebernommen(balduin, vorlauf_gelaufen):
    vorschlaege = abfrage(balduin.projekt, "SELECT * FROM vorschlag")
    assert vorschlaege, "Der Vorlauf hat keine Vorschläge erzeugt"
    assert all(v["quelle"] and v["score"] is not None for v in vorschlaege)       # Quelle und Score zu jedem
    messe = [v for v in vorschlaege if v["feld"] == "schlagwort" and v["anton_id"] == 501]
    assert messe, "V8 schlägt das Anton-Schlagwort „Messe“ für die Messeordner nicht vor"
    assert abfrage(balduin.projekt, "SELECT * FROM erschliessung") == vorlauf_gelaufen["erschliessung_vorher"]
    assert abfrage(balduin.projekt, "SELECT * FROM vorschlag_urteil") == []


def test_angenommener_vorschlag_wird_erst_beim_speichern_wirksam(balduin, vorlauf_gelaufen):
    v = abfrage(balduin.projekt, "SELECT * FROM vorschlag WHERE feld = 'schlagwort' AND anton_id = 501 LIMIT 1")[0]
    wert = {"gleich": [{"name": v["anton_name"] or v["wert"], "anton_id": 501}], "quelle": f"Vorschlag: {v['quelle']}"}
    balduin.post("/api/es_speichern", {"ziele": [ziel(v["platte_id"], v["pfad"])], "felder": {"schlagworte": wert},
                                       "angenommen": [{"feld": "schlagwort", "wert": v["wert"], "anton_id": 501,
                                                       "beleg": v["beleg"]}]})
    gespeichert = abfrage(balduin.projekt, "SELECT gleich, quelle FROM erschliessung WHERE platte_id = ? AND pfad = ? "
                                           "AND feld = 'schlagworte'", v["platte_id"], v["pfad"])
    assert json.loads(gespeichert[0]["gleich"])[0]["anton_id"] == 501
    assert gespeichert[0]["quelle"].startswith("Vorschlag")
    assert abfrage(balduin.projekt, "SELECT urteil FROM vorschlag_urteil") == [{"urteil": "angenommen"}]


# ---------- Modul 4: Export (Regel 1 Ablage, Regel 4, Regel 6, Token) ----------

@pytest.fixture(scope="module")
def export_gelaufen(balduin, projekt, anton):
    """HD01/Fotos/2001 übernommen, erschlossen, der Box MA-FOTO-1 zugeordnet, gepackt (Lauf X0–X2), Importformat
    abgefragt, als Probe übergeben und Abschlussbericht gespeichert. Die Ablage ist ein leerer „Datenträger“."""
    ablage = projekt.volumes / "Ablage"
    ablage.mkdir()
    vorher = len(anton.anfragen)
    balduin.post("/api/entscheiden", {"ziele": [ziel("HD01", "Fotos/2001")], "entscheidung": "übernehmen", "fassungen": False})
    pfade = [z["relpfad"] for z in abfrage(projekt.ordner, "SELECT relpfad FROM datei WHERE platte_id = 'HD01' AND "
                                           "relpfad LIKE 'Fotos/2001/%' AND relpfad NOT LIKE '%.DS_Store'")]
    balduin.post("/api/es_speichern", {"ziele": [ziel("HD01", p) for p in pfade], "wer": "Test", "felder": {
        "titel": {"gleich": "Messestand"}, "zeitraum": {"gleich": ["01.05.2001", "03.05.2001", False, False]}}})
    balduin.post("/api/box_laden", {"kennung": "MA-FOTO-1"})
    balduin.post("/api/es_zuordnen", {"ziele": [ziel("HD01", p) for p in pfade], "ziel": "a:200"})
    balduin.post("/api/export_ablage", {"mountpunkt": str(ablage)})
    balduin.post("/api/export_planen", {"wer": "Test"})
    balduin.post("/api/export_starten", {"platte_id": "HD01", "beschreibbar_ok": True})
    lauf = [x for x in balduin.laeufe_abwarten() if x["art"] == "export"][-1]
    assert lauf["status"] == "fertig", lauf["meldung"]
    balduin.post("/api/export_importformat")
    pakete = balduin.get("/api/export")["pakete"]
    balduin.post("/api/export_uebergeben", {"pakete": [p["paket_id"] for p in pakete], "notiz": "Test"})
    balduin.post("/api/export_bericht")
    yield {"ablage": ablage, "export": ablage / "Balduin-Projekte" / "Testprojekt" / "export",
           "pakete": balduin.get("/api/export")["pakete"], "anfragen_ab": vorher}
    shutil.rmtree(ablage, ignore_errors=True)


def test_export_schreibt_auf_der_ablage_nur_in_den_eigenen_ordner(export_gelaufen):
    """Ausnahme zu Regel 1: Auf der Ablage nur unter Balduin-Projekte/<Projekt>/export, sonst nichts."""
    export = export_gelaufen["export"]
    assert [p["name"] for p in export_gelaufen["pakete"]] and all((export / p["name"]).is_file()
                                                                 for p in export_gelaufen["pakete"])
    fremd = [p.relative_to(export_gelaufen["ablage"]).as_posix() for p in export_gelaufen["ablage"].rglob("*")
             if p.is_file() and export not in p.parents]
    assert fremd == []


def test_uebergebenes_paket_wird_vor_der_kontrolle_nicht_geloescht(balduin, export_gelaufen):
    """Regel 4: Ein Paket wird erst gelöscht, wenn die Kontrolle es in Anton gefunden hat."""
    p = export_gelaufen["pakete"][0]
    assert p["status"] == "übergeben"
    status, antwort = balduin.roh("POST", "/api/export_datei_loeschen", {"paket_id": p["paket_id"]})
    assert status >= 400 and "Kontrolle" in antwort["fehler"]
    assert (export_gelaufen["export"] / p["name"]).is_file()
    assert balduin.get("/api/export")["pakete"][0]["status"] == "übergeben"


def test_anton_token_steht_in_keinem_paket_und_keinem_bericht(balduin, export_gelaufen):
    """Nach dem Export: Token weder auf der Ablage (tar, Lieferschein, Prüfsummen) noch im Projekt (Bericht, Logs,
    Sicherung der Datenbank)."""
    orte = [export_gelaufen["ablage"], balduin.projekt]
    gefunden = [str(p) for o in orte for p in o.rglob("*") if p.is_file() and TOKEN.encode() in p.read_bytes()]
    assert gefunden == []


def test_export_liest_aus_anton_nur_und_laedt_nichts_hoch(balduin, anton, export_gelaufen):
    """Balduin schreibt nie in Anton: Pakete gehen über die Ablage an K&R. Auch Kontrolle und Abruf nur mit GET,
    Token nur im Header."""
    balduin.post("/api/anton_holen")
    balduin.laeufe_abwarten()
    balduin.post("/api/export_kontrolle")
    anfragen = anton.anfragen[export_gelaufen["anfragen_ab"]:]
    assert anfragen, "weder Importformat noch Bestand aus Anton abgefragt"
    assert [a for a in anfragen if a["methode"] != "GET"] == []
    assert not any(a["token_in_url"] for a in anfragen)


def test_unvollstaendiges_paket_wird_nicht_geloescht(balduin, export_gelaufen):
    """Regel 4 (Entscheidung 06.11.2026): Fand die Kontrolle nicht alles in Anton, bleibt die Paketdatei liegen."""
    p = balduin.get("/api/export")["pakete"][0]
    assert p["status"] == "unvollständig"                      # die Kontrolle im Test davor fand nichts in Anton
    status, antwort = balduin.roh("POST", "/api/export_datei_loeschen", {"paket_id": p["paket_id"]})
    assert status >= 400 and "Kontrolle" in antwort["fehler"]
    assert (export_gelaufen["export"] / p["name"]).is_file()


def test_paket_wird_frei_sobald_alles_in_anton_ist(balduin, projekt, anton, export_gelaufen):
    """Kommt das Fehlende an (hier: alle Dateien im Nachbau), wird das Paket importiert und die Datei löschbar."""
    medien = [{"id": 9300 + i, "md5sum": z["md5"], "file_name": z["relpfad"].rsplit("/", 1)[-1], "size": z["groesse"],
               "mime_type": "image/jpeg"} for i, z in enumerate(abfrage(
                   projekt.ordner, "SELECT relpfad, md5, groesse FROM paket_eintrag WHERE relpfad IS NOT NULL"))]
    neu = {"id": 460, "identifier": "MA-FOTO-1-3", "title": "Messestand", "level_of_description": "Einzelstück",
           "parent_id": 200, "permalink": "http://anton.test/objects/460", "media": medien}
    anton.objekte.append(neu)
    try:
        balduin.post("/api/anton_holen")
        balduin.laeufe_abwarten()
        balduin.post("/api/export_kontrolle")
    finally:
        anton.objekte.remove(neu)
    p = balduin.get("/api/export")["pakete"][0]
    assert p["status"] == "importiert"
    balduin.post("/api/export_datei_loeschen", {"paket_id": p["paket_id"]})
    assert not (export_gelaufen["export"] / p["name"]).exists()


# ---------- Regel 1 am Ende dieser Datei noch einmal ----------

def test_quellplatten_nach_allen_schritten_unveraendert(balduin, testplatten, vorlauf_gelaufen):
    for platte, vorher in testplatten.abdruck.items():
        assert fingerabdruck(testplatten.volumes / platte) == vorher, platte


def test_quellordner_nach_der_analyse_unveraendert(quellen):
    """Ein Ordner als Quelle lässt sich nicht schreibgeschützt einhängen; Balduin liest ihn trotzdem nur (B–I)."""
    assert quellen.laeufe["HD05"]["lauf"]["status"] == "fertig"
    assert fingerabdruck(quellen.quellordner) == quellen.abdruck


def test_quellordner_nicht_im_projekt_oder_in_der_ablage(quellen):
    """Wo Balduin schreibt (Projekt, Vorschaubilder, Ablage), darf keine Quelle liegen, und umgekehrt."""
    from conftest import lauf_aufrufen
    for pfad in (quellen.ordner, quellen.ordner / "berichte", quellen.ordner.parent):
        e = __import__("subprocess").run(
            [__import__("sys").executable, "-m", "erfassung.lauf", "quellordner", "--projekt", str(quellen.ordner),
             "--volumes", str(quellen.volumes), "--daten",
             json.dumps({"aktion": "pruefen", "pfad": str(pfad)})], capture_output=True, text=True,
            cwd=__import__("conftest").CODE)
        assert e.returncode != 0 and "überschneidet sich" in e.stderr, pfad
    assert lauf_aufrufen("quellordner", "--projekt", quellen.ordner, "--volumes", quellen.volumes, "--daten",
                         json.dumps({"aktion": "pruefen", "pfad": str(quellen.quellordner), "platte_id": "HD05"}))

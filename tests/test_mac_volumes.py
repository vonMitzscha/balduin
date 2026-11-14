"""Seltene Fälle bei Mac-Datenträgern (13.11.2026, docs/plan.md): mehrere Volumes, verschlüsselte APFS-Volumes mit
Passwort (nie gespeichert, über stdin an den Lauf), ein verschobenes Abbild an neuem Ort.

Testabbild mac_apfs_zwei.img (werkzeuge/mac_testabbilder_erzeugen.py --zwei): APFS-Container mit MAC_ZWEI und dem
verschlüsselten GEHEIM, beide leer."""
import json
import shutil

import pytest

from conftest import Balduin, abfrage, lauf_ausfuehren
from erfassung import lauf, macplatte, platte, quelle
from erfassung.basis import db


def geheim(abbild):
    return next(v for v in macplatte.volumes(abbild) if v["gesperrt"])


def zeile(platte_id):
    with db() as con:
        con.row_factory = __import__("sqlite3").Row
        return dict(con.execute("SELECT * FROM platte WHERE platte_id = ?", (platte_id,)).fetchone())


@pytest.fixture
def zwei(leeres_projekt, mac_abbilder):
    yield mac_abbilder.zwei
    quelle.schliessen()
    quelle.WAHL.clear()


# ---------- Volume und Passwort am Anfang jedes Laufs ----------

def test_verschluesseltes_volume_nur_mit_passwort(zwei, mac_abbilder):
    g = geheim(zwei)
    lauf.leseschicht_vorbereiten({"platte_id": "HD08", "mountpunkt": str(zwei), "art": "abbild",
                                  "volume_uuid": g["uuid"]}, None)
    with pytest.raises(ValueError, match="verschlüsselt"):
        platte.registrieren("HD08", zwei, etikett="Testabbild", art="abbild")
    lauf.leseschicht_vorbereiten({"platte_id": "HD08", "mountpunkt": str(zwei), "art": "abbild",
                                  "volume_uuid": g["uuid"]}, mac_abbilder.passwort)
    platte.registrieren("HD08", zwei, etikett="Testabbild", art="abbild")
    z = zeile("HD08")
    assert z["volume_name"] == "GEHEIM" and z["volume_uuid"] == g["uuid"] and z["verschluesselt"] == 1


def test_lauf_oeffnet_das_registrierte_volume_nicht_das_erste(zwei, mac_abbilder):
    """Fortsetzen und Packen tragen keine Volume-UUID im Auftrag; der Lauf nimmt die registrierte (vorher öffnete die
    Leseschicht bei Mac-Platten dann das erste Volume, und B lehnte ab)."""
    g = geheim(zwei)
    lauf.leseschicht_vorbereiten({"platte_id": "HD08", "mountpunkt": str(zwei), "art": "abbild",
                                  "volume_uuid": g["uuid"]}, mac_abbilder.passwort)
    platte.registrieren("HD08", zwei, etikett="Testabbild", art="abbild")
    quelle.schliessen()
    quelle.WAHL.clear()
    lauf.leseschicht_vorbereiten({"platte_id": "HD08", "mountpunkt": str(zwei)}, mac_abbilder.passwort)
    assert quelle.volume(zwei).info["VolumeName"] == "GEHEIM"


def test_passwort_kommt_ueber_stdin_und_wird_nirgends_gespeichert(zwei, mac_abbilder, leeres_projekt):
    g = geheim(zwei)
    auftrag = {"platte_id": "HD08", "mountpunkt": str(zwei), "art": "abbild", "volume_uuid": g["uuid"],
               "etikett": "Testabbild", "mit_passwort": True, "schritte": ["B", "C"]}
    lauf_ausfuehren(leeres_projekt.ordner, leeres_projekt.volumes, "erfassen", auftrag, "HD08",
                    eingabe=mac_abbilder.passwort + "\n")
    assert zeile("HD08")["volume_name"] == "GEHEIM"
    for datei in leeres_projekt.ordner.rglob("*"):                   # Datenbank, Logs, projekt.json …
        if datei.is_file():
            assert mac_abbilder.passwort.encode() not in datei.read_bytes(), datei


def test_lauf_ohne_passwort_scheitert_verstaendlich(zwei, mac_abbilder, leeres_projekt):
    g = geheim(zwei)
    auftrag = {"platte_id": "HD08", "mountpunkt": str(zwei), "art": "abbild", "volume_uuid": g["uuid"],
               "etikett": "Testabbild", "mit_passwort": True, "schritte": ["B"]}
    with pytest.raises(AssertionError, match="Passwort"):
        lauf_ausfuehren(leeres_projekt.ordner, leeres_projekt.volumes, "erfassen", auftrag, "HD08", eingabe="")


# ---------- Abbild an neuem Ort ----------

def test_abbild_verlegen(leeres_projekt, mac_abbilder, tmp_path):
    alt = tmp_path / "alt" / "Nachlass.img"
    alt.parent.mkdir()
    shutil.copy2(mac_abbilder.hfs, alt)
    platte.registrieren("HD07", alt, etikett="Nachlass", art="abbild")
    from erfassung import schnellscan
    schnellscan.schnellscan("HD07", alt)
    quelle.schliessen()
    neu = tmp_path / "neu" / "Nachlass kopiert.img"
    neu.parent.mkdir()
    shutil.move(alt, neu)
    with pytest.raises(ValueError, match="anderer Datenträger"):              # ein anderes Abbild taugt nicht
        platte.quelle_verlegen("HD07", mac_abbilder.apfs)
    a = platte.quelle_verlegen("HD07", neu)
    assert a["pfad"] == str(neu.resolve()) and zeile("HD07")["quellordner"] == str(neu.resolve())
    with db() as con:
        assert con.execute("SELECT COUNT(*) FROM protokoll WHERE objekt = 'HD07' AND feld = 'quellordner'").fetchone()[0] == 1
    platte.angeschlossene_platte_pruefen("HD07", neu)                      # wird dort wiedererkannt


# ---------- Server: Passwort nur weiterreichen, nie einreihen ----------

def test_server_reicht_das_passwort_weiter_und_reiht_nicht_ein(zwei, mac_abbilder, leeres_projekt, tmp_path):
    b = Balduin(leeres_projekt.ordner, leeres_projekt.volumes, tmp_path)
    try:
        g = geheim(zwei)
        b.post("/api/erfassen", {"platte_id": "HD08", "mountpunkt": str(zwei), "art": "abbild", "volume_uuid": g["uuid"],
                                 "etikett": "Testabbild", "passwort": mac_abbilder.passwort})
        laeufe = b.laeufe_abwarten()
        assert laeufe[-1]["status"] == "fertig", laeufe[-1]["meldung"]
        assert json.loads(laeufe[-1]["auftrag"])["mit_passwort"] is True
        assert mac_abbilder.passwort not in laeufe[-1]["auftrag"]
        assert b.get("/api/erfassung")["platten"][0]["verschluesselt"] == 1
        # Fortsetzen ohne Passwort: klare Meldung, kein Lauf
        status, antwort = b.roh("POST", "/api/platte_lauf", {"platte_id": "HD08", "modus": "fortsetzen",
                                                              "mountpunkt": str(zwei)})
        assert status != 200 and "Passwort" in json.dumps(antwort, ensure_ascii=False)
        # mit Passwort, während ein anderer Lauf eingereiht wäre: nicht einreihen (der Lauf, der ihn später startet,
        # kennt das Passwort nicht)
        with db() as con:
            con.execute("INSERT INTO lauf (art, platte_id, auftrag, status, start, pid) VALUES "
                        "('erfassen', 'HD99', '{}', 'läuft', datetime('now'), ?)", (__import__("os").getpid(),))
        status, antwort = b.roh("POST", "/api/platte_lauf", {"platte_id": "HD08", "modus": "fortsetzen",
                                                              "mountpunkt": str(zwei), "passwort": mac_abbilder.passwort})
        assert status != 200 and "anderer Lauf" in json.dumps(antwort, ensure_ascii=False)
    finally:
        b.beenden()
    assert not abfrage(leeres_projekt.ordner, "SELECT * FROM lauf WHERE auftrag LIKE ?", f"%{mac_abbilder.passwort}%")


def test_passwort_vor_dem_lauf_pruefen(zwei, mac_abbilder, leeres_projekt, tmp_path):
    """Feedback 14.11.2026: Ein falsches Passwort fiel erst im Lauf auf. „Prüfen“ öffnet das Volume ohne Lauf; das
    Passwort geht nur über stdin und landet nirgends."""
    b = Balduin(leeres_projekt.ordner, leeres_projekt.volumes, tmp_path)
    try:
        g = geheim(zwei)
        frage = {"platte_id": "HD08", "mountpunkt": str(zwei), "art": "abbild", "volume_uuid": g["uuid"]}
        falsch = b.post("/api/passwort_pruefen", {**frage, "passwort": "falsch-geraten"})
        assert falsch["ok"] is False and "stimmt nicht" in falsch["meldung"]
        assert b.post("/api/passwort_pruefen", {**frage, "passwort": mac_abbilder.passwort})["ok"] is True
        status, antwort = b.roh("POST", "/api/passwort_pruefen", {**frage, "passwort": ""})
        assert status != 200 and "Passwort" in json.dumps(antwort, ensure_ascii=False)
        assert not abfrage(leeres_projekt.ordner, "SELECT * FROM lauf")                # kein Lauf, keine Platte
        assert not abfrage(leeres_projekt.ordner, "SELECT * FROM platte")
    finally:
        b.beenden()
    for datei in leeres_projekt.ordner.rglob("*"):
        if datei.is_file():
            assert mac_abbilder.passwort.encode() not in datei.read_bytes(), datei


def test_registrierte_platte_passwort_pruefen(zwei, mac_abbilder, leeres_projekt, tmp_path):
    """Registrierte Platte ohne Volume-UUID in der Anfrage: geprüft wird das registrierte Volume."""
    g = geheim(zwei)
    lauf.leseschicht_vorbereiten({"platte_id": "HD08", "mountpunkt": str(zwei), "art": "abbild",
                                  "volume_uuid": g["uuid"]}, mac_abbilder.passwort)
    platte.registrieren("HD08", zwei, etikett="Testabbild", art="abbild")
    quelle.schliessen()
    quelle.WAHL.clear()
    b = Balduin(leeres_projekt.ordner, leeres_projekt.volumes, tmp_path)
    try:
        frage = {"platte_id": "HD08", "mountpunkt": str(zwei)}
        assert b.post("/api/passwort_pruefen", {**frage, "passwort": "falsch"})["ok"] is False
        assert b.post("/api/passwort_pruefen", {**frage, "passwort": mac_abbilder.passwort})["ok"] is True
        # ohne Mountpunkt (Fortsetzen eines Laufs, Packen): Balduin sucht die Platte selbst
        assert b.post("/api/passwort_pruefen", {"platte_id": "HD08", "passwort": "falsch"})["ok"] is False
        assert b.post("/api/passwort_pruefen", {"platte_id": "HD08", "passwort": mac_abbilder.passwort})["ok"] is True
    finally:
        b.beenden()


def test_falsches_passwort_beim_registrieren_laesst_neu_versuchen(zwei, mac_abbilder, leeres_projekt, tmp_path):
    """Feedback 14.11.2026: Nach einem falschen Passwort musste die Platte gelöscht und neu registriert werden. Der
    gescheiterte Lauf hinterlässt keine Platte; ein neuer Versuch mit dem richtigen Passwort registriert sie."""
    b = Balduin(leeres_projekt.ordner, leeres_projekt.volumes, tmp_path)
    try:
        g = geheim(zwei)
        auftrag = {"platte_id": "HD08", "mountpunkt": str(zwei), "art": "abbild", "volume_uuid": g["uuid"],
                   "etikett": "Testabbild"}
        b.post("/api/erfassen", {**auftrag, "passwort": "falsch"})
        laeufe = b.laeufe_abwarten()
        assert laeufe[-1]["status"] == "Fehler" and "stimmt nicht" in laeufe[-1]["meldung"]
        assert not abfrage(leeres_projekt.ordner, "SELECT * FROM platte")
        b.post("/api/erfassen", {**auftrag, "passwort": mac_abbilder.passwort})
        laeufe = b.laeufe_abwarten()
        assert laeufe[-1]["status"] == "fertig", laeufe[-1]["meldung"]
    finally:
        b.beenden()


def test_leerer_datentraeger_laeuft_durch(leeres_projekt, tmp_path):
    """Gefunden am leeren verschlüsselten Testvolume (13.11.2026): ohne Dateien meldete D1 „keinen Schnellscan“,
    obwohl er gelaufen war. Ein leerer Datenträger ist ein Befund, kein Fehler."""
    leer = tmp_path / "Leere Übergabe"
    leer.mkdir()
    r = lauf_ausfuehren(leeres_projekt.ordner, leeres_projekt.volumes, "erfassen",
                        {"platte_id": "HD09", "mountpunkt": str(leer), "art": "ordner", "etikett": "leer",
                         "schritte": ["B", "C", "D1", "H"]}, "HD09")
    assert r["schritte"]["D1"]["status"] in ("fertig", "übersprungen")


# ---------- Oberfläche (Rauchtest in Node, ohne Browser) ----------

def zeichnen(faelle):
    import subprocess
    from conftest import CODE
    if not shutil.which("node"):
        pytest.skip("node fehlt")
    r = subprocess.run(["node", str(CODE / "tests" / "hilfen" / "erfassung_zeichnen.js"),
                        str(CODE / "tool" / "web" / "erfassung.js"), json.dumps(faelle)], capture_output=True, text=True,
                       timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


VOLUMES = [{"name": "MAC_ZWEI", "dateisystem": "APFS", "uuid": "U1", "gesperrt": False, "groesse": 1},
           {"name": "GEHEIM", "dateisystem": "APFS", "uuid": "U2", "gesperrt": True, "groesse": 1}]
DT = {"naechste": "HD08", "angeschlossen": [], "ordner": [], "mac_geraete": [], "arbeitsplatte_da": True}
STAND = {"platten": [], "virenscan": True, "warteschlange": [], "laeufe": [], "platz_neu": {}}


def test_formular_mit_volumes_passwort_und_umfang():
    abbild = {"mountpunkt": "/x/zwei.img", "name": "zwei.img", "ordner": True, "abbild": True, "volumes": VOLUMES,
              "schreibgeschuetzt": True, "kennungen": []}
    basis = {"stand": STAND, "dt": DT, "platte": None, "quelle": abbild, "gewaehlt": "/x/zwei.img"}
    mac = {**abbild, "macplatte": True, "mountpunkt": "PD2"}
    h = zeichnen([{"name": "offen", "erf": {**basis, "volume": "U1"}},
                  {"name": "geheim", "erf": {**basis, "volume": "U2"}},
                  {"name": "mac", "erf": {**basis, "quelle": mac, "gewaehlt": "PD2", "volume": "U1"}},
                  {"name": "lange", "ziel": "#dt-hinweis", "erf": {"dt": {**DT, "lange_pfade_aus": True}}},
                  {"name": "kurz", "ziel": "#dt-hinweis", "erf": {"dt": DT}}])
    assert 'id="f-volume"' in h["offen"] and "umfang-modus" in h["offen"] and 'id="f-passwort"' not in h["offen"]
    assert 'id="f-passwort"' in h["geheim"] and "umfang-modus" not in h["geheim"]
    assert "umfang-modus" not in h["mac"] and 'data-traeger="festplatte"' in h["mac"]      # Mac-Platte: ohne Umfang
    assert "260 Zeichen" in h["lange"] and h["kurz"] == ""


def test_panel_eines_verschluesselten_abbilds():
    p = {"platte_id": "HD08", "volume_name": "GEHEIM", "art": "abbild", "quellordner": "/x/zwei.img",
         "dateisystem": "APFS", "verschluesselt": 1, "umfang": None, "dateien": 0, "bytes": 0, "uuid": 1,
         "traeger": "image", "registriert_am": "2026-11-13T19:00", "erledigt": ["B", "C"], "offen": {}, "gleich": None,
         "etikett_text": "", "notiz": "", "kopie_von": None, "deaktiviert_am": None}
    stand = {**STAND, "platten": [p], "lauf": None}
    ordner = lambda da: [{"platte_id": "HD08", "pfad": "/x/zwei.img", "name": "zwei.img", "art": "abbild", "da": da}]  # noqa: E731
    h = zeichnen([{"name": "da", "erf": {"stand": stand, "dt": {**DT, "ordner": ordner(True)}, "platte": "HD08"}},
                  {"name": "weg", "erf": {"stand": stand, "dt": {**DT, "ordner": ordner(False)}, "platte": "HD08"}}])
    assert "Verschlüsselt" in h["da"] and "abbild-verlegen" not in h["da"] and "Ordner als Quelle" not in h["da"]
    assert 'id="abbild-verlegen"' in h["weg"]

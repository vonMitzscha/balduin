"""Quellen außer ganzen Datenträgern (Entscheidungen 05.11.2026, docs/plan.md):

Fall 1  Teile einer Platte: Die Platte wird registriert, aber nur ein Umfang (Ordner der Platte) gelesen; die Pfade
        bleiben plattenrelativ, der Umfang kann nur wachsen.
Fall 2  Ordner als Quelle: ein gewöhnlicher Ordner ohne eigenen Datenträger, mit Herkunft statt Etikett; nur lesen,
        nicht im Finder zeigen, nicht im Projekt, in der Ablage, den Vorschaubildern oder auf einer registrierten Platte.
"""
import json
import shutil
from pathlib import Path

import pytest

from conftest import CODE, Balduin, abfrage, fingerabdruck, lauf_ausfuehren


def anlegen(wurzel, pfade):
    """Kleine Testdateien mit verschiedenem Inhalt unter wurzel."""
    for i, p in enumerate(pfade):
        ziel = Path(wurzel) / p
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text(f"Datei {i}: {p}\n" * (i + 1), encoding="utf-8")
    return Path(wurzel).resolve()


@pytest.fixture
def stick(leeres_projekt):
    """Ein „Datenträger“ unter den Test-Volumes mit Ordnern A, B, C."""
    return anlegen(leeres_projekt.volumes / "STICK",
                   ["A/1.txt", "A/tief/2.txt", "B/3.txt", "C/x/4.txt", "C/y/5.txt", "wurzel.txt"])


@pytest.fixture
def quellordner(leeres_projekt, tmp_path):
    return anlegen(tmp_path / "quellen" / "Übergabe Marketing", [f"Ordner {k}/datei_{k}_{i}.txt" for k in "abc" for i in range(4)])


def pfade(platte_id):
    from erfassung.basis import db
    with db() as con:
        return {r for (r,) in con.execute("SELECT relpfad FROM schnellscan WHERE platte_id = ?", (platte_id,))}


def zeile(platte_id):
    from erfassung.basis import db
    with db() as con:
        con.row_factory = __import__("sqlite3").Row
        return dict(con.execute("SELECT * FROM platte WHERE platte_id = ?", (platte_id,)).fetchone())


# ---------- Fall 1: Umfang ----------

def test_umfang_normalisieren():
    from erfassung import platte
    assert platte.umfang_normalisieren(["C/x", "A", "A/tief", "C/x/", "A"]) == ["A", "C/x"]
    assert platte.umfang_normalisieren(["A", ""]) == []            # „“ = ganze Platte
    assert platte.umfang_normalisieren(None) == []
    for falsch in (["../x"], ["A/../B"], ["/A"]):
        with pytest.raises(ValueError):
            platte.umfang_normalisieren(falsch)


def test_umfang_enthaelt():
    from erfassung import platte
    assert platte.umfang_enthaelt(["A"], ["A", "B"])
    assert platte.umfang_enthaelt(["A/tief"], ["A"])
    assert platte.umfang_enthaelt(["A"], [])                       # ganze Platte enthält alles
    assert not platte.umfang_enthaelt([], ["A"])
    assert not platte.umfang_enthaelt(["A", "B"], ["A"])


def test_schnellscan_liest_nur_den_umfang(stick):
    from erfassung import platte, schnellscan
    platte.registrieren("HD01", stick, umfang=["A", "C/x"])
    schnellscan.schnellscan("HD01", stick)
    assert pfade("HD01") == {"A/1.txt", "A/tief/2.txt", "C/x/4.txt"}          # plattenrelativ
    assert json.loads(zeile("HD01")["umfang"]) == ["A", "C/x"]


def test_umfang_kann_nur_wachsen(stick):
    from erfassung import platte
    platte.registrieren("HD01", stick, umfang=["A"])
    platte.registrieren("HD01", stick, umfang=["A", "B"])
    assert platte.umfang_lesen("HD01") == ["A", "B"]
    platte.registrieren("HD01", stick)                                      # ohne Angabe: bleibt
    assert platte.umfang_lesen("HD01") == ["A", "B"]
    with pytest.raises(ValueError, match="wachsen"):
        platte.registrieren("HD01", stick, umfang=["B"])
    platte.registrieren("HD01", stick, umfang=[])                           # ganze Platte
    assert platte.umfang_lesen("HD01") == []
    with pytest.raises(ValueError, match="wachsen"):
        platte.registrieren("HD01", stick, umfang=["A"])


def test_umfang_ordner_muss_es_geben(stick):
    from erfassung import platte
    with pytest.raises(ValueError, match="gibt es nicht"):
        platte.registrieren("HD01", stick, umfang=["Fehlt"])


def test_umfang_kommt_ins_protokoll(stick):
    from erfassung import platte
    from erfassung.basis import db
    platte.registrieren("HD01", stick, umfang=["A"])
    platte.registrieren("HD01", stick, umfang=["A", "B"])
    with db() as con:
        eintraege = con.execute("SELECT alt, neu FROM protokoll WHERE objekt = 'HD01' AND feld = 'umfang'").fetchall()
    assert ("", '["A"]') in eintraege and ('["A"]', '["A", "B"]') in eintraege


# ---------- Fall 2: Ordner als Quelle ----------

def test_ordner_registrieren(quellordner):
    from erfassung import platte
    platte.registrieren("HD01", quellordner, etikett="Übergabe per Download, 2026", art="ordner")
    z = zeile("HD01")
    assert z["art"] == "ordner" and z["quellordner"] == str(quellordner)
    assert z["volume_uuid"] == "" and z["dateisystem"] == "Ordner" and z["volume_name"] == "Übergabe Marketing"
    assert z["etikett_text"] == "Übergabe per Download, 2026"


def test_ordner_braucht_herkunft(quellordner):
    from erfassung import platte
    with pytest.raises(ValueError, match="Herkunft"):
        platte.registrieren("HD01", quellordner, etikett="  ", art="ordner")


@pytest.mark.parametrize("wo", ["projekt", "im_projekt", "ueber_projekt", "code", "home", "wurzel", "vorschauen",
                                "datentraeger", "fehlt"])
def test_unzulaessige_ordner(leeres_projekt, stick, wo):
    from erfassung import platte
    P = leeres_projekt
    P.vorschauen.mkdir(parents=True, exist_ok=True)
    ziel = {"projekt": P.ordner, "im_projekt": P.ordner / "berichte", "ueber_projekt": P.ordner.parent,
            "code": CODE / "tool", "home": Path.home(), "wurzel": Path("/"), "vorschauen": P.vorschauen,
            "datentraeger": stick, "fehlt": P.ordner.parent / "gibt es nicht"}[wo]
    with pytest.raises(ValueError):
        platte.quellordner_pruefen(ziel)


def test_ordner_auf_registrierter_platte_nur_als_umfang(stick):
    from erfassung import platte
    assert platte.quellordner_pruefen(stick / "B") == stick / "B"          # Datenträger nicht registriert: geht
    platte.registrieren("HD01", stick, umfang=["A"])
    with pytest.raises(ValueError, match="Umfang"):
        platte.quellordner_pruefen(stick / "B")


def test_ordner_ueberschneiden_sich_nicht(quellordner):
    from erfassung import platte
    platte.registrieren("HD01", quellordner, etikett="Herkunft", art="ordner")
    for ziel in (quellordner, quellordner / "Ordner a", quellordner.parent):
        with pytest.raises(ValueError, match="HD01"):
            platte.quellordner_pruefen(ziel)
    assert platte.quellordner_pruefen(quellordner, platte_id="HD01") == quellordner   # derselbe für sich selbst


def test_kennung_eines_datentraegers_nicht_fuer_ordner(stick, quellordner):
    from erfassung import platte
    platte.registrieren("HD01", stick)
    with pytest.raises(ValueError, match="Datenträger"):
        platte.registrieren("HD01", quellordner, etikett="Herkunft", art="ordner")


def test_ordner_wiedererkennen_und_verlegen(quellordner, tmp_path):
    from erfassung import platte, schnellscan
    platte.registrieren("HD01", quellordner, etikett="Herkunft", art="ordner")
    schnellscan.schnellscan("HD01", quellordner)
    platte.angeschlossene_platte_pruefen("HD01", quellordner)
    neu = tmp_path / "Archiv" / "Übergabe Marketing"
    neu.parent.mkdir()
    shutil.move(quellordner, neu)                      # eigene Testdaten im Temp-Ordner
    with pytest.raises(ValueError, match="neuen Ort"):
        platte.angeschlossene_platte_pruefen("HD01", neu)
    platte.ordner_verlegen("HD01", neu)
    assert zeile("HD01")["quellordner"] == str(neu.resolve())
    platte.angeschlossene_platte_pruefen("HD01", neu)
    anderer = anlegen(tmp_path / "Anderes", ["z.txt"])
    with pytest.raises(ValueError, match="Stichprobe"):
        platte.ordner_verlegen("HD01", anderer)


def test_ordner_ist_in_der_liste_der_quellen(quellordner):
    from erfassung import platte
    platte.registrieren("HD01", quellordner, etikett="Herkunft", art="ordner")
    assert platte.quellordner_liste() == [{"platte_id": "HD01", "pfad": str(quellordner), "name": "Übergabe Marketing",
                                           "art": "ordner", "da": True}]
    shutil.rmtree(quellordner)
    assert platte.quellordner_liste()[0]["da"] is False


# ---------- Ganzer Ablauf (Hintergrundlauf B–I, Server) ----------

@pytest.mark.integration
def test_platte_mit_umfang_durch_die_analyse(quellen):
    schritte = quellen.laeufe["HD03"]["schritte"]
    assert {k: s["status"] for k, s in schritte.items() if s["status"] not in ("fertig", "übersprungen")} == {}
    dateien = {z["relpfad"] for z in abfrage(quellen.ordner, "SELECT relpfad FROM datei WHERE platte_id = 'HD03'")}
    assert dateien and all(p.startswith("Alt/") for p in dateien)


@pytest.mark.integration
def test_ordner_durch_die_analyse(quellen):
    schritte = quellen.laeufe["HD05"]["schritte"]
    assert {k: s["status"] for k, s in schritte.items() if s["status"] not in ("fertig", "übersprungen")} == {}
    for pflicht in ("B", "C", "D1", "D2", "E", "F", "G", "H"):
        assert schritte[pflicht]["status"] == "fertig", pflicht
    auf_platte = {p.relative_to(quellen.quellordner).as_posix() for p in quellen.quellordner.rglob("*") if p.is_file()}
    in_db = {z["relpfad"] for z in abfrage(quellen.ordner, "SELECT relpfad FROM datei WHERE platte_id = 'HD05' "
                                                           "AND sha256 IS NOT NULL")}
    assert in_db == {__import__("unicodedata").normalize("NFC", p) for p in auf_platte}
    assert fingerabdruck(quellen.quellordner) == quellen.abdruck


@pytest.fixture(scope="module")
def server(quellen, tmp_path_factory):
    b = Balduin(quellen.ordner, quellen.volumes, tmp_path_factory.mktemp("server_quellen"))
    yield b
    b.beenden()


@pytest.mark.integration
def test_server_kennt_den_ordner(server, quellen):
    ordner = server.get("/api/datentraeger")["ordner"]
    assert {"platte_id": "HD05", "pfad": str(quellen.quellordner), "name": "Übergabe 2026", "art": "ordner", "da": True} in ordner
    platten = {p["platte_id"]: p for p in server.get("/api/erfassung", platte="HD05")["platten"]}
    assert platten["HD05"]["art"] == "ordner" and platten["HD05"]["quellordner"] == str(quellen.quellordner)
    assert json.loads(platten["HD03"]["umfang"]) == ["Alt"]


@pytest.mark.integration
def test_ordner_wird_nicht_im_finder_gezeigt(server):
    datei = abfrage(server.projekt, "SELECT relpfad FROM datei WHERE platte_id = 'HD05' LIMIT 1")[0]["relpfad"]
    antwort = server.get("/api/quelle", platte="HD05", pfad=datei)
    from erfassung import system
    assert "pfad" not in antwort and system.systemwoerter()["dateimanager"] in antwort["grund"]


@pytest.mark.integration
def test_quellordner_pruefen_ueber_den_server(server, quellen, tmp_path):
    status, antwort = server.roh("POST", "/api/quellordner_pruefen", {"pfad": str(server.projekt)})
    assert status == 500 and antwort["fehler"]
    neu = anlegen(tmp_path / "Neu", ["a.txt"])
    antwort = server.post("/api/quellordner_pruefen", {"pfad": str(neu)})
    assert antwort["pfad"] == str(neu) and antwort["name"] == "Neu"


@pytest.mark.integration
def test_unterordner_einer_platte(server, quellen):
    antwort = server.get("/api/unterordner", mountpunkt=str(quellen.volumes / "HD03"), pfad="")
    namen = [o["name"] for o in antwort["ordner"]]
    assert "Alt" in namen and "Projekte" in namen
    tief = server.get("/api/unterordner", mountpunkt=str(quellen.volumes / "HD03"), pfad="Alt")
    assert [o["pfad"] for o in tief["ordner"]] == ["Alt/2003"]
    status, _ = server.roh("GET", "/api/unterordner?mountpunkt=" + str(quellen.volumes / "HD03") + "&pfad=..")
    assert status == 500
    status, _ = server.roh("GET", "/api/unterordner?mountpunkt=" + str(server.projekt) + "&pfad=")
    assert status == 500                                # nur angeschlossene Quellen


@pytest.mark.integration
def test_umfang_erweitern_und_fortsetzen(server, quellen):
    vorher = {z["relpfad"]: z["sha256"] for z in abfrage(server.projekt, "SELECT relpfad, sha256 FROM datei "
                                                                          "WHERE platte_id = 'HD03'")}
    server.post("/api/platte_lauf", {"platte_id": "HD03", "mountpunkt": str(quellen.volumes / "HD03"),
                                     "modus": "fortsetzen", "beschreibbar_ok": True, "umfang": ["Alt", "Projekte"]})
    lauf = server.laeufe_abwarten()[-1]
    assert lauf["status"] == "fertig", lauf["meldung"]
    schritte = {z["schritt"]: z["status"] for z in abfrage(server.projekt, "SELECT schritt, status FROM lauf_schritt "
                                                                           "WHERE lauf_id = ?", lauf["lauf_id"])}
    assert schritte["C"] == "fertig"                   # neuer Umfang: Schnellscan noch einmal
    nachher = {z["relpfad"]: z["sha256"] for z in abfrage(server.projekt, "SELECT relpfad, sha256 FROM datei "
                                                                           "WHERE platte_id = 'HD03'")}
    assert any(p.startswith("Projekte/") for p in nachher) and all(nachher[p] == s for p, s in vorher.items())
    status, antwort = server.roh("POST", "/api/platte_lauf", {"platte_id": "HD03", "modus": "fortsetzen",
                                                              "mountpunkt": str(quellen.volumes / "HD03"),
                                                              "beschreibbar_ok": True, "umfang": ["Alt"]})
    assert status == 500 and "wachsen" in antwort["fehler"]


@pytest.mark.integration
def test_ordner_fortsetzen_ueber_den_server(server, quellen):
    server.post("/api/platte_lauf", {"platte_id": "HD05", "mountpunkt": str(quellen.quellordner), "modus": "fortsetzen"})
    lauf = server.laeufe_abwarten()[-1]
    assert lauf["status"] == "fertig", lauf["meldung"]
    assert fingerabdruck(quellen.quellordner) == quellen.abdruck


def test_ordner_packen_ohne_schreibschutz_aber_nie_in_die_ablage(quellordner, monkeypatch):
    """Modul 4 liest einen Ordner wie eine Platte; schreibgeschützt eingehängt kann er nicht sein. Liegt die Ablage im
    oder über dem Ordner, bricht das Packen ab (harte Regel 1)."""
    from erfassung import platte, schnellscan
    from export import bauen
    platte.registrieren("HD01", quellordner, etikett="Herkunft", art="ordner")
    schnellscan.schnellscan("HD01", quellordner)
    bauen.platte_pruefen("HD01", quellordner)
    monkeypatch.setattr(bauen.P, "export", quellordner / "export")
    monkeypatch.setattr(bauen.P, "export_wurzel", quellordner.parent)
    with pytest.raises((RuntimeError, ValueError), match="Ablage"):
        bauen.platte_pruefen("HD01", quellordner)

"""Ohne Schreibschutz lesen nach Rückfrage (Entscheidung 13.11.2026): Unter Windows kann Balduin einen Datenträger nicht
schreibgeschützt einhängen. Zugestimmt wird einmal je Datenträger; die Zustimmung steht in der Datenbank und im Protokoll,
das Lesen ohne Schreibschutz in der Bestandsgeschichte; „Datei zeigen“ ist danach erlaubt."""
from pathlib import Path

import pytest

import pakete
import server
from conftest import abfrage
from erfassung import system
from export import bauen


# ---------- Wörter für die Oberfläche ----------

def test_windows_nennt_fehlenden_schreibschutz(monkeypatch):
    monkeypatch.setattr(system, "windows", lambda: True)
    monkeypatch.setattr(system, "mac", lambda: False)
    monkeypatch.setattr(system, "linux", lambda: False)
    assert "nicht schreibgeschützt" in system.systemwoerter()["kein_schreibschutz"]


@pytest.mark.parametrize("plattform", ["mac", "linux"])
def test_mac_und_linux_haengen_schreibgeschuetzt_ein(monkeypatch, plattform):
    for name in ("windows", "mac", "linux"):
        monkeypatch.setattr(system, name, lambda n=name: n == plattform)
    assert system.systemwoerter()["kein_schreibschutz"] == ""


# ---------- Bestandsgeschichte ----------

def test_bestandsgeschichte_nennt_lesen_ohne_schreibschutz():
    platte = {"platte_id": "HD01", "etikett_text": "Fotos 2001"}
    ohne = pakete.herkunft_text(platte, "2026-11-13T10:00:00")
    assert ohne.startswith("Übernommen von Datenträger HD01, Etikett: „Fotos 2001“.")
    assert "ohne Schreibschutz gelesen (erstmals am 13.11.2026)" in ohne
    assert "ohne Schreibschutz" not in pakete.herkunft_text(platte, None)


# ---------- „Datei zeigen“ ----------

def test_datei_zeigen_nach_zustimmung_erlaubt():
    q = {"mountpunkt": "E:\\", "schreibgeschuetzt": False}
    assert server.beschreibbar_gesperrt(q, zugestimmt=False, echte_datentraeger=True)
    assert not server.beschreibbar_gesperrt(q, zugestimmt=True, echte_datentraeger=True)
    assert not server.beschreibbar_gesperrt({**q, "schreibgeschuetzt": True}, zugestimmt=False, echte_datentraeger=True)
    assert not server.beschreibbar_gesperrt(q, zugestimmt=False, echte_datentraeger=False)    # Tests: gewöhnliche Ordner


# ---------- Packen: auch an echten Datenträgern, nur nach Zustimmung ----------

def test_packen_ohne_schreibschutz_nur_nach_zustimmung(leeres_projekt, monkeypatch, tmp_path):
    from erfassung import platte as platte_modul
    wurzel = tmp_path / "E"
    wurzel.mkdir()
    monkeypatch.setattr(platte_modul, "angeschlossene_platte_pruefen", lambda *a: None)
    monkeypatch.setattr(platte_modul, "art_der_quelle", lambda *a: None)
    monkeypatch.setattr(platte_modul, "ist_ordner", lambda *a: False)
    monkeypatch.setattr(platte_modul, "bereit", lambda *a: False)
    monkeypatch.setattr(system, "standard_volumes", lambda *a: True)          # wie an einem echten Rechner
    with pytest.raises(RuntimeError, match="beschreibbar"):
        bauen.platte_pruefen("HD07", wurzel)
    bauen.platte_pruefen("HD07", wurzel, beschreibbar_ok=True)
    ordner = leeres_projekt.db_pfad.parent
    zeile = abfrage(ordner, "SELECT * FROM schreibschutz_verzicht WHERE platte_id = 'HD07'")[0]
    assert zeile["zugestimmt_am"] and zeile["gelesen_am"]
    assert abfrage(ordner, "SELECT * FROM protokoll WHERE objekt = 'HD07' AND feld = 'ohne Schreibschutz gelesen'")


# ---------- Analyse und Server ----------

def test_analyse_ohne_schreibschutz_steht_in_der_datenbank(projekt):
    # die Testplatten sind gewöhnliche, beschreibbare Ordner; analysiert wurde mit beschreibbar_ok
    zeilen = {z["platte_id"]: z for z in abfrage(projekt.ordner, "SELECT * FROM schreibschutz_verzicht")}
    assert zeilen["HD01"]["gelesen_am"] and zeilen["HD02"]["gelesen_am"]


def test_zustimmung_einmal_je_datentraeger_mit_protokoll(balduin, projekt):
    balduin.post("/api/ohne_schreibschutz", {"platte_id": "HD09"})
    balduin.post("/api/ohne_schreibschutz", {"platte_id": "HD09"})            # zweimal: nur eine Zustimmung
    zeilen = abfrage(projekt.ordner, "SELECT * FROM schreibschutz_verzicht WHERE platte_id = 'HD09'")
    assert len(zeilen) == 1 and zeilen[0]["zugestimmt_am"] and not zeilen[0]["gelesen_am"]
    protokoll = abfrage(projekt.ordner, "SELECT * FROM protokoll WHERE objekt = 'HD09' "
                                        "AND feld = 'ohne Schreibschutz lesen'")
    assert len(protokoll) == 1 and protokoll[0]["neu"] == "zugestimmt"
    platten = {p["platte_id"]: p for p in balduin.get("/api/erfassung")["platten"]}
    assert platten["HD01"]["ohne_schreibschutz"]                              # aus der Analyse


def test_kennung_wird_geprueft(balduin):
    status, antwort = balduin.roh("POST", "/api/ohne_schreibschutz", {"platte_id": "../x"})
    assert status != 200 and "Kennung" in antwort["fehler"]


def test_stand_des_exports_kennt_die_zustimmung(balduin):
    platten = {p["platte_id"]: p for p in balduin.get("/api/export")["platten"]}
    assert platten["HD01"]["ohne_schreibschutz"] is True

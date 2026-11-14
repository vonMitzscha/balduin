"""Lesen aus Anton (erfassung/anton.py): Laufzeit und Sperre aus einer Antwort, Bestandsbox mit Eltern, Token nur im
Header. Gegen den nachgebauten Anton (tests/hilfen/anton_nachbau.py), im Testprozess, ohne Platten."""
import pytest

from erfassung import anton, basis
from hilfen.anton_nachbau import AntonNachbau


# ---------- reine Funktionen ----------

@pytest.mark.parametrize("von, bis, erwartet", [
    ("1950-01-01", "2010-12-31", "1950–2010"),                  # ganze Jahre nur als Jahr
    ("1950-03-01", "1950-03-31", "01.03.1950–31.03.1950"),
    ("1950-01-01", "1950-12-31", "1950"),                      # gleiches Jahr nur einmal
    ("1950", "", "1950"),
])
def test_zeitspanne(von, bis, erwartet):
    assert anton.zeitspanne(von, bis) == erwartet


@pytest.mark.parametrize("objekt, erwartet", [
    ({"date": "um 1900"}, "um 1900"),
    ({"dates": {"text": "1950–1960"}}, "1950–1960"),
    ({"date_from": "1950-01-01", "date_to": "1959-12-31"}, "1950–1959"),
    ({"events": [{"type": "creation", "date_text": "ca. 1920"}]}, "ca. 1920"),
    ({"events": [{"type": "accumulation", "date_text": "1999"}]}, ""),
    ({}, ""),
])
def test_laufzeit_aus_verschiedenen_feldern(objekt, erwartet):
    assert anton.laufzeit(objekt) == erwartet


@pytest.mark.parametrize("objekt, gesperrt", [
    ({"is_public": False}, True), ({"is_public": True}, False), ({"restricted": True}, True),
    ({"access": "intern"}, True), ({"access": "öffentlich"}, False), ({}, False),
])
def test_sperrfeld(objekt, gesperrt):
    assert anton.sperrfeld(objekt) is gesperrt


# ---------- gegen den Nachbau ----------

@pytest.fixture
def mit_anton(tmp_path):
    """Leeres Projekt, dessen Anton-Adresse auf einen eigenen Nachbau zeigt."""
    with AntonNachbau() as a:
        volumes = tmp_path / "volumes"
        volumes.mkdir()
        basis.projekt_anlegen(tmp_path / "P", {"name": "P", "anton": {"url": a.url}})
        basis.oeffnen(tmp_path / "P", volumes=volumes)
        yield a


def test_einheit_ueber_signatur_mit_eltern(mit_anton):
    e = anton.einheit_holen("  MA-FOTO-1 ")
    assert (e["id"], e["titel"], e["laufzeit"], e["zugang"]) == (200, "Fotosammlung", "1950–2010", "intern")
    assert e["eltern"] == [{"id": 100, "signatur": "MA", "titel": "Musterarchiv", "stufe": "Archiv"}]


def test_interne_einheit_wird_als_gesperrt_erkannt(mit_anton):
    """Mit Token sichtbar, ohne Token nicht: also nicht öffentlich."""
    assert anton.einheit_holen("300")["gesperrt"] is True


def test_ohne_token_nur_oeffentliches(mit_anton, monkeypatch):
    monkeypatch.delenv("ANTON_TOKEN")
    monkeypatch.setattr(anton.system, "geheimnis_lesen", lambda dienst: "")
    with pytest.raises(ValueError, match="ohne Token nur öffentliche"):
        anton.einheit_holen("MA-INT-1")


def test_falscher_token_wird_klar_gemeldet(mit_anton, monkeypatch):
    monkeypatch.setenv("ANTON_TOKEN", "falscher-token-123")
    with pytest.raises(RuntimeError, match="lehnt das API-Token ab"):
        anton.einheit_holen("MA-FOTO-1")


def test_token_geht_nur_im_header(mit_anton):
    anton.einheit_holen("MA-FOTO-1")
    assert mit_anton.anfragen and all(a["token"] and not a["token_in_url"] for a in mit_anton.anfragen[:1])
    assert not any(a["token_in_url"] for a in mit_anton.anfragen)


def test_stufen_aus_anton(mit_anton):
    s = anton.stufen_holen()
    assert s["quelle"] == "levels-of-description"
    assert [x["name"] for x in s["stufen"]][-2:] == ["Dossier", "Einzelstück"]


@pytest.mark.parametrize("kennung", ["", "   ", "x" * 101])
def test_leere_oder_zu_lange_kennung(mit_anton, kennung):
    with pytest.raises(ValueError):
        anton.einheit_holen(kennung)

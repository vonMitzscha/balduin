"""Speicherplatz (Entscheidung 12.11.2026): keine Obergrenzen mehr für Projektordner und Arbeitsplatte, nur eine feste
Reserve auf dem Laufwerk des Projekts; vor einer Analyse eine Schätzung, was die Vorschaubilder brauchen."""
from pathlib import Path

import pytest

import server
from erfassung import basis

CODE = Path(__file__).resolve().parents[1]
GB = 10 ** 9


# ---------- Reserve statt Budget ----------

def test_vorgabe_ist_nur_eine_reserve_von_10_gb():
    assert basis.VORGABEN_PROJEKT["speicher"] == {"min_frei_gb": 10}


def test_alte_obergrenzen_in_projekt_json_stoeren_nicht(leeres_projekt):
    """Vorhandene Projekte tragen noch budget_gb und arbeitsplatte_gb: sie werden nicht mehr gelesen."""
    assert not hasattr(leeres_projekt, "budget_gb")
    assert not hasattr(leeres_projekt, "arbeitsplatte_gb")
    e = basis.einstellungen_mischen(basis.VORGABEN_PROJEKT,
                                    {"name": "Alt", "anton": {"url": "https://archiv.example.org"},
                                     "speicher": {"budget_gb": 10, "min_frei_gb": 20, "arbeitsplatte_gb": 50}})
    basis.einstellungen_pruefen(e)


def test_grosser_projektordner_haelt_nichts_an(leeres_projekt, monkeypatch):
    """Ohne Budget: belegt das Projekt viel, reicht es, dass die Reserve frei bleibt."""
    monkeypatch.setattr(basis, "speicherstand", lambda: (500.0, 400.0))   # 500 GB frei, Projekt 400 GB
    basis.platz_pruefen(50)


def test_reserve_haelt_an_mit_verstaendlicher_meldung(leeres_projekt, monkeypatch):
    leeres_projekt.min_frei_gb = 10
    monkeypatch.setattr(basis, "speicherstand", lambda: (12.0, 1.0))
    with pytest.raises(RuntimeError) as fehler:
        basis.platz_pruefen(5)
    text = str(fehler.value)
    assert "3.0 GB" in text or "3,0 GB" in text            # 10 + 5 − 12 freiräumen
    assert "projekt.json" not in text and "min_frei_gb" not in text


def test_speicher_nicht_mehr_im_tool_aenderbar(leeres_projekt):
    with pytest.raises(ValueError, match="Nicht in Balduin änderbar"):
        basis.einstellungen_aendern({"speicher": {"min_frei_gb": 5}})


def test_oberflaeche_ohne_speicherbudget():
    for datei in ("projekt.js", "erfassung.js"):
        text = (CODE / "tool" / "web" / datei).read_text(encoding="utf-8")
        assert "budget_gb" not in text and "arbeitsplatte_gb" not in text and "Speicherbudget" not in text, datei


# ---------- Schätzung vor der Analyse ----------

def test_schaetzung_mit_bekannter_zahl():
    s = server.platz_schaetzen(100_000, frei=120 * GB, reserve=10 * GB)
    assert s["bedarf"] == 100_000 * server.VORSCHAU_JE_DATEI
    assert not s["knapp"]
    assert "3,5 GB" in s["text"] and "120 GB" in s["text"]


def test_schaetzung_ohne_zahl_nennt_den_richtwert():
    s = server.platz_schaetzen(None, frei=120 * GB, reserve=10 * GB)
    assert s["bedarf"] is None and not s["knapp"]
    assert "35 KB" in s["text"] and "120 GB" in s["text"]


def test_schaetzung_ohne_offene_vorschaubilder_sagt_nichts():
    assert server.platz_schaetzen(0, frei=120 * GB, reserve=10 * GB)["text"] == ""


def test_schaetzung_warnt_wenn_die_reserve_angegriffen_wird():
    s = server.platz_schaetzen(100_000, frei=12 * GB, reserve=10 * GB)
    assert s["knapp"]
    assert "knapp" in s["text"] and "1,5 GB" in s["text"]      # 10 + 3,5 − 12 freiräumen


def test_schaetzung_fuer_die_arbeitsplatte():
    s = server.platz_schaetzen(100_000, frei=120 * GB, reserve=10 * GB, arbeitsplatte=True, arbeitsplatte_frei=2 * GB)
    assert s["knapp"] and "Datenträger für Vorschaubilder" in s["text"]
    nicht_da = server.platz_schaetzen(100_000, frei=120 * GB, reserve=10 * GB, arbeitsplatte=True, arbeitsplatte_frei=None)
    assert not nicht_da["knapp"] and "nicht angeschlossen" in nicht_da["text"]

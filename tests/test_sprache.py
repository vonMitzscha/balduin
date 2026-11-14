"""Österreichisch: „skartieren“ statt „kassieren“, still im Hintergrund (Entscheidung 05.11.2026, docs/plan.md).

Signal ist die Systemregion des Rechners (erfassung/system.py) oder die Browsersprache de-AT; nur die Anzeige
ändert sich (tool/web/sprache.js), die Datenbank schreibt weiter „kassieren“.
"""
import json
import shutil
import subprocess

import pytest

from conftest import CODE, Balduin

from erfassung import system


@pytest.mark.parametrize("text, region", [
    ("de_AT", "AT"), ("de_AT@currency=EUR", "AT"), ("de-AT", "AT"), ("de_AT.UTF-8", "AT"),
    ("de_DE", "DE"), ("de_CH.UTF-8", "CH"), ("de", ""), ("", ""), (None, ""), ("C", ""),
])
def test_region_aus_dem_gebietsschema(text, region):
    assert system.region_aus(text) == region


def test_systemregion_laesst_sich_fuer_tests_vorgeben(monkeypatch):
    monkeypatch.setenv("BALDUIN_REGION", "AT")
    assert system.systemregion() == "AT"
    monkeypatch.setenv("BALDUIN_REGION", "de_CH")
    assert system.systemregion() == "CH"


@pytest.fixture
def server_in(tmp_path):
    """Startet den Server auf einem leeren Projekt mit vorgegebener Systemregion."""
    from erfassung import basis
    volumes = tmp_path / "volumes"
    volumes.mkdir()
    basis.projekt_anlegen(tmp_path / "Leer", {"name": "Leer", "kennung": "HD", "virenscan": False,
                                              "anton": {"url": "http://127.0.0.1:9"}})
    gestartet = []

    def starten(region):
        ordner = tmp_path / f"server_{region}"
        ordner.mkdir()
        b = Balduin(tmp_path / "Leer", volumes, ordner, umgebung={"BALDUIN_REGION": region})
        gestartet.append(b)
        return b
    yield starten
    for b in gestartet:
        b.beenden()


def test_seite_traegt_de_at_nur_in_oesterreich(server_in):
    status, seite = server_in("AT").roh("GET", "/")
    assert status == 200 and b'<html lang="de-AT">' in seite
    status, seite = server_in("DE").roh("GET", "/")
    assert status == 200 and b'<html lang="de">' in seite


def test_seite_traegt_de_ch_in_der_schweiz(server_in):
    status, seite = server_in("CH").roh("GET", "/")
    assert status == 200 and b'<html lang="de-CH">' in seite


def test_seite_kennt_die_systemwoerter(server_in):
    status, seite = server_in("DE").roh("GET", "/")
    assert status == 200 and b"window.SYSTEMWOERTER" in seite and b'"dateimanager"' in seite


def test_sprache_js_wird_vor_den_modulen_geladen():
    seite = (CODE / "tool" / "web" / "index.html").read_text(encoding="utf-8")
    assert "/web/sprache.js" in seite
    assert seite.index("/web/sprache.js") < seite.index("/web/app.js")


@pytest.mark.skipif(not shutil.which("node"), reason="node fehlt")
@pytest.mark.parametrize("vorher, nachher", [
    ("kassieren", "skartieren"),
    ("Kassieren", "Skartieren"),
    ("Archiv rot kassieren", "Archiv rot skartieren"),
    ("3 kassiert, 2 übernommen", "3 skartiert, 2 übernommen"),
    ("Kassiertes ausblenden", "Skartiertes ausblenden"),
    ("kassierte Kopien", "skartierte Kopien"),
    ("ohne automatische Kassation", "ohne automatische Skartierung"),
    ("Kassationen", "Skartierungen"),
    ("KASSIEREN", "SKARTIEREN"),
    # bleibt, wie es ist
    ("es ist nichts passiert", "es ist nichts passiert"),
    ("Kasse", "Kasse"),
    ("übernehmen", "übernehmen"),
])
def test_skartieren_ersetzt_nur_die_woerter_des_kassierens(vorher, nachher):
    skript = (f"const s = require({json.dumps(str(CODE / 'tool' / 'web' / 'sprache.js'))});"
              f"process.stdout.write(s.skartieren({json.dumps(vorher)}));")
    r = subprocess.run(["node", "-e", skript], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert r.stdout == nachher


@pytest.mark.skipif(not shutil.which("node"), reason="node fehlt")
@pytest.mark.parametrize("vorher, nachher", [
    ("Größe", "Grösse"), ("Straße und Maß", "Strasse und Mass"), ("GROẞ", "GROSS"), ("ohne", "ohne"),
])
def test_schweiz_ersetzt_eszett(vorher, nachher):
    skript = (f"const s = require({json.dumps(str(CODE / 'tool' / 'web' / 'sprache.js'))});"
              f"process.stdout.write(s.schweizern({json.dumps(vorher)}));")
    r = subprocess.run(["node", "-e", skript], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    assert r.stdout == nachher

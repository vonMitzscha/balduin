"""Hinweis auf eine neue Version auf der Startseite (Entscheidung 14.11.2026): Releases des öffentlichen Spiegels
höchstens einmal am Tag abfragen, nur eine höhere Version melden, Fehler bleiben still."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import server

RELEASES = [
    {"tag_name": "testbau", "draft": True, "html_url": "x"},
    {"tag_name": "v0.92", "draft": False, "prerelease": True, "html_url": "https://beispiel/v0.92",
     "published_at": "2026-11-20T10:00:00Z"},
    {"tag_name": "v0.90", "draft": False, "html_url": "https://beispiel/v0.90"},
    {"tag_name": "v0.100", "draft": True, "html_url": "https://beispiel/v0.100"},   # Entwurf zählt nicht
]


@pytest.mark.parametrize("eigene, erwartet", [("0.85", "0.92"), ("0.92", None), ("0.100", None), ("0", None)])
def test_neuere_version(eigene, erwartet):
    neu = server.neuere_version(eigene, RELEASES)
    assert (neu or {}).get("version") == erwartet
    if neu:
        assert neu["adresse"] == "https://beispiel/v0.92" and neu["datum"] == "2026-11-20T10:00:00Z"


def test_versionen_als_zahlen_verglichen():
    assert server.neuere_version("0.99", [{"tag_name": "v0.100", "html_url": "u"}])["version"] == "0.100"
    assert server.neuere_version("0.85", [{"tag_name": "kaputt"}, "unsinn", {}]) is None


@pytest.fixture
def releases_server():
    """Nachgebaute Release-Liste auf 127.0.0.1; zählt die Abfragen."""
    abfragen = []

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            abfragen.append(self.path)
            daten = json.dumps(RELEASES).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(daten)

        def log_message(self, *a):
            pass

    s = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{s.server_port}/releases", abfragen
    s.shutdown()


def test_aktualisierung_fragt_hoechstens_einmal_am_tag(tmp_path, releases_server, monkeypatch):
    adresse, abfragen = releases_server
    monkeypatch.setattr(server, "ZULETZT", tmp_path / "zuletzt.json")
    monkeypatch.setattr(server, "VERSION", "0.85")
    assert server.aktualisierung(adresse)["version"] == "0.92"
    assert server.aktualisierung(adresse)["version"] == "0.92"
    assert len(abfragen) == 1                                  # zweites Mal aus aktualisierung.json
    merk = tmp_path / "aktualisierung.json"
    d = json.loads(merk.read_text(encoding="utf-8"))
    d["zeit"] = time.time() - 2 * 86400                        # älter als ein Tag: neu fragen
    merk.write_text(json.dumps(d), encoding="utf-8")
    server.aktualisierung(adresse)
    assert len(abfragen) == 2


def test_aktualisierung_still_bei_fehler_und_abgeschaltet(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ZULETZT", tmp_path / "zuletzt.json")
    monkeypatch.setattr(server, "VERSION", "0.85")
    assert server.aktualisierung("http://127.0.0.1:9/nichts") is None
    assert server.aktualisierung("") is None                   # abgeschaltet
    assert not (tmp_path / "aktualisierung.json").exists() or \
        json.loads((tmp_path / "aktualisierung.json").read_text(encoding="utf-8"))["releases"] == []


def test_link_nur_https():
    neu = server.neuere_version("0.1", [{"tag_name": "v0.2", "html_url": "javascript:alert(1)"}])
    assert neu["version"] == "0.2" and neu["adresse"] == ""

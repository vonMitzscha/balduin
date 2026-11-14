"""Dashboard und „Als Bericht speichern“ an den analysierten Testplatten (HD01, HD02): Daten aus erfassung/dashboard.py,
Bericht als eigenständige HTML-Datei ohne Server und ohne plotly (Entscheidung 14.11.2026)."""
import pytest

pytestmark = pytest.mark.integration


def test_dashboard_liefert_alle_teile(balduin):
    d = balduin.get("/api/dashboard")["analyse"]
    assert d["dateien_gesamt"] > 0
    assert d["bestand"]["formatgruppen"] and d["bestand"]["stufen"]
    assert d["duplikate"]["treemap"]["dateien"]                       # Treemap: jede Datei ein Rechteck
    assert {"HD01", "HD02"} <= set(d["ordnerbaum"])                   # Ordnerbaum je Datenträger
    assert d["duplikate"]["arten"]                                    # die Testplatten enthalten exakte Kopien


def test_bericht_ist_eigenstaendig_und_ohne_plotly(balduin, projekt):
    antwort = balduin.post("/api/bericht")
    datei = projekt.ordner / antwort["pfad"]
    html = datei.read_text(encoding="utf-8")
    assert "plotly" not in html.lower()
    assert "<script src=" not in html                                  # alles eingebettet, kein Nachladen
    assert '"ordnerbaum"' in html and "HD01" in html

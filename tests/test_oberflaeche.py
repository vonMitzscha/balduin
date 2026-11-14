"""Oberfläche: Skripte in tool/web/ teilen sich ohne Kapselung einen globalen Namensraum.

Definieren zwei ungekapselte Skripte dieselbe Funktion, gewinnt die zuletzt geladene, und das andere Modul ruft
fremden Code auf (Fehler 05.11.2026: projekt.js überschrieb `einstellungenAenderungen` der Bewertung, der Baum
meldete „null is not an object … pe-film“).
"""
import re
from collections import defaultdict

from conftest import CODE

WEB = CODE / "tool" / "web"
OBERSTE_NAMEN = re.compile(r"^(?:async\s+)?(?:function\*?|class|const|let|var)\s+([A-Za-z_$][\w$]*)", re.M)


def _skripte():
    """Eigene Skripte in der Reihenfolge von index.html (ohne vendor/)."""
    html = (WEB / "index.html").read_text(encoding="utf-8")
    return [WEB / n for n in re.findall(r'<script src="/web/([\w.]+\.js)', html)]


def _globaler_teil(text):
    """Nur, was außerhalb der Kapselung (() => { … })(); steht; ungekapselte Dateien ganz."""
    m = re.search(r"^\((?:\(\)\s*=>|function\s*\(\))\s*\{.*?^\}\)\(\);", text, flags=re.S | re.M)
    return text[:m.start()] + text[m.end():] if m else text


def test_keine_doppelten_globalen_namen():
    gefunden = defaultdict(list)
    for datei in _skripte():
        text = _globaler_teil(datei.read_text(encoding="utf-8"))
        for name in set(OBERSTE_NAMEN.findall(text)):
            gefunden[name].append(datei.name)
    doppelt = {n: d for n, d in gefunden.items() if len(d) > 1}
    assert not doppelt, f"gleiche globale Namen in mehreren Skripten: {doppelt}"


def test_modul4_hat_ein_zahnrad_am_knopf():
    """Ablage und Paketgröße liegen im Zahnrad am Knopf „Bestand und Export“ (Entscheidung 05.11.2026)."""
    html = (WEB / "index.html").read_text(encoding="utf-8")
    knopf, zahnrad = html.index('data-ansicht="export"'), html.index('id="ex-einstellungen-knopf"')
    assert 0 < zahnrad - knopf < 400 and 'id="ex-einstellungen"' in html

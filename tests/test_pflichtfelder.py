"""Pflichtfelder überall gleich wie in der Erschließung (Feedback 14.11.2026): kurze Bezeichnung mit rotem Stern
(`PFLICHT` aus tool/web/icons.js), Erklärung darunter statt „(Pflicht: …)“ im Text der Bezeichnung. Dazu: Symbole
in den Erklärtexten des Assistenten erscheinen als Symbol, nicht als Quelltext."""
import re

import pytest

from test_mac_volumes import DT, STAND, VOLUMES, zeichnen
from conftest import CODE

WEB = CODE / "tool" / "web"
PROJEKT = (WEB / "projekt.js").read_text(encoding="utf-8")


def test_eine_marke_fuer_alle():
    assert re.search(r'const PFLICHT = `<span class="pflicht"', (WEB / "icons.js").read_text(encoding="utf-8"))
    css = (WEB / "app.css").read_text(encoding="utf-8")
    assert re.search(r"\.pflicht\s*\{[^}]*color:\s*var\(--a-rot\)", css)
    assert "es-pflicht\"" not in (WEB / "erschliessung.js").read_text(encoding="utf-8")   # Erschließung nutzt dieselbe


def test_kein_pflicht_im_bezeichnungstext():
    for datei in WEB.glob("*.js"):
        assert "(Pflicht" not in datei.read_text(encoding="utf-8"), datei.name
    assert "(Pflicht" not in (WEB / "index.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("feld", ["a-name", "a-kennung", "a-anton", "pe-name", "pe-kennung"])
def test_pflichtfelder_in_assistent_und_einstellungen(feld):
    vor = PROJEKT[:PROJEKT.index(f'id="{feld}"')]
    bezeichnung = vor[vor.rindex("<label"):]
    assert "${PFLICHT}" in bezeichnung, bezeichnung


def test_neue_verzeichnungseinheit_titel():
    es = (WEB / "erschliessung.js").read_text(encoding="utf-8")
    assert '<label><span>Titel${PFLICHT}</span> <input name="titel"' in es


def test_registrieren_zeigt_pflichtfelder():
    platte = {"mountpunkt": "/x/STICK", "name": "STICK", "schreibgeschuetzt": True, "kennungen": []}
    ordner = {"mountpunkt": "/x/Übergabe", "name": "Übergabe", "ordner": True, "schreibgeschuetzt": False, "kennungen": []}
    abbild = {"mountpunkt": "/x/zwei.img", "name": "zwei.img", "ordner": True, "abbild": True, "volumes": VOLUMES,
              "schreibgeschuetzt": True, "kennungen": []}
    basis = {"stand": STAND, "dt": DT, "platte": None}
    h = zeichnen([{"name": "platte", "erf": {**basis, "quelle": None, "gewaehlt": "/x/STICK", "dt": {**DT, "angeschlossen": [platte]}}},
                  {"name": "ordner", "erf": {**basis, "quelle": ordner, "gewaehlt": "/x/Übergabe"}},
                  {"name": "geheim", "erf": {**basis, "quelle": abbild, "gewaehlt": "/x/zwei.img", "volume": "U2"}}])
    marke = '<span class="pflicht"'
    kennung = lambda html: html[:html.index('id="f-kennung"')]  # noqa: E731
    for fall in h.values():
        assert marke in kennung(fall)[kennung(fall).rindex("<label"):]
    herkunft = h["ordner"][:h["ordner"].index('id="f-etikett"')]
    assert marke in herkunft[herkunft.rindex("<label"):] and "Pflicht:" not in h["ordner"]
    passwort = h["geheim"][:h["geheim"].index('id="f-passwort"')]
    assert marke in passwort[passwort.rindex("<label"):]
    assert 'id="f-passwort-pruefen"' in h["geheim"]                          # Passwort vor dem Lauf prüfen
    etikett = h["platte"][:h["platte"].index('id="f-etikett"')]               # Etikett einer Platte: freiwillig
    assert marke not in etikett[etikett.rindex("<label"):]


def test_symbole_im_erklaertext_des_assistenten():
    """Die Erklärung eines Schritts wird als Text gesetzt; ein ${icon(…)} darin erschien als <svg …>-Quelltext."""
    schritte = PROJEKT[PROJEKT.index("const SCHRITTE_NEU"):PROJEKT.index("function assistentZeichnen")]
    for text in re.findall(r"text:(.*?)html:", schritte, flags=re.S):
        assert "icon(" not in text, text
    assert "{zahnrad}" in schritte
    assert 'esc(s.text).replaceAll("{zahnrad}", icon("settings"))' in PROJEKT

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


# ---- Roter Rahmen um leere Pflichtfelder (Feedback 14.11.2026) ----
import json
import shutil
import subprocess

FAKE_DOM = """
globalThis.window = {};
const eingabe = (value, { disabled = false, freiwillig = false, vorschlag = false } = {}) => {
  const k = new Set();
  return { value, disabled, dataset: freiwillig ? { freiwillig: "" } : {}, k,
           classList: { toggle: (n, an) => { an ? k.add(n) : k.delete(n); } },
           closest: (s) => (vorschlag && s === ".es-vorschlaege" ? {} : null) };
};
const feld = (eingaben) => ({ querySelectorAll: () => eingaben });
const marke = (f) => ({ closest: () => f });
"""


def markieren(faelle):
    """faelle: JS-Ausdruck, der eine Liste von Eingabelisten liefert; Antwort je Fall, welche rot sind."""
    code = FAKE_DOM + (WEB / "icons.js").read_text(encoding="utf-8") + f"""
const faelle = {faelle};
pflichtMarkieren({{ querySelectorAll: () => faelle.map((e) => marke(feld(e))) }});
process.stdout.write(JSON.stringify(faelle.map((e) => e.map((x) => x.k.has("pflicht-leer")))));
"""
    r = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30)
    assert not r.returncode, r.stderr
    return json.loads(r.stdout)


@pytest.mark.skipif(not shutil.which("node"), reason="node fehlt")
def test_leeres_pflichtfeld_rot_bis_etwas_drinsteht():
    assert markieren('[[eingabe("")], [eingabe("  ")], [eingabe("AB")]]') == [[True], [True], [False]]


@pytest.mark.skipif(not shutil.which("node"), reason="node fehlt")
def test_ein_wert_genuegt_freiwilliges_und_gesperrtes_bleibt_ohne():
    # Laufzeit: Tag, Monat, Jahr „von“; „bis“ ist freiwillig; gesperrtes Feld (Kürzel nach Registrierung) nie rot
    assert markieren('[[eingabe(""), eingabe(""), eingabe(""), eingabe("", { freiwillig: true })],'
                     ' [eingabe(""), eingabe("1987"), eingabe("", { freiwillig: true })],'
                     ' [eingabe("", { disabled: true })], [eingabe("", { vorschlag: true })]]') == [
        [True, True, True, False], [False, False, False], [False], [False]]


def test_rahmen_in_css_und_laufend_nachgefuehrt():
    css = (WEB / "app.css").read_text(encoding="utf-8")
    assert re.search(r"\.pflicht-leer[^{]*\{[^}]*var\(--a-rot\)", css)
    icons = (WEB / "icons.js").read_text(encoding="utf-8")
    assert "MutationObserver" in icons and '"input"' in icons
    es = (WEB / "erschliessung.js").read_text(encoding="utf-8")
    assert 'seite === "bis" ? " data-freiwillig' in es                 # „bis“ der Laufzeit ist kein Pflichtteil

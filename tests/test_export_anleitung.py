"""Modul 4, Packen als Anleitung (Entscheidung 05.11.2026, docs/Feedback/Export-Interface.md): Welcher Schritt ist dran,
welche Platte ist anzuschließen, wann startet ein Lauf von selbst, wann sind die Aktionen nach dem Import frei.

Die Regeln stehen als reine Funktionen in tool/web/export.js und werden hier mit Node ausgeführt."""
import json
import shutil
import subprocess

import pytest

from conftest import CODE

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="node fehlt")
SKRIPT = CODE / "tool" / "web" / "export.js"


def js(ausdruck, s, **opt):
    """Wertet `ausdruck` mit s (Stand von /api/export) und opt aus; versucht als Liste → Set."""
    code = (f"const m = require({json.dumps(str(SKRIPT))});"
            f"const s = {json.dumps(s)}; const o = {json.dumps(opt)}; o.versucht = new Set(o.versucht || []);"
            f"process.stdout.write(JSON.stringify({ausdruck}));")
    r = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def platte(pid, offen=1, da=False, ro=True, **mehr):
    return {"platte_id": pid, "noetig": True, "pakete": 1, "offen": offen, "ungeprueft": 0, "angeschlossen": da,
            "schreibgeschuetzt": da and ro, "ordner": False, "etikett": "", **mehr}


def paket(pid, status="geplant", art="teil", **mehr):
    return {"art": art, "platte_id": pid, "status": status, "bytes": 100, "geprueft_am": None, **mehr}


def stand(**mehr):
    s = {"ablage": {"ort": "datentraeger", "da": True, "frei": 10**12, "min_frei": 10**9, "name": "Arbeit"},
         "veraltet": False, "exportierbar": 10, "lauf": None,
         "pakete": [paket("HD02"), paket("HD01")], "platten": [platte("HD02"), platte("HD01")]}
    s.update(mehr)
    return s


def aktuell(s, **opt):
    liste = js("m.exAnleitung(s, o)", s, **opt)
    dran = [x["k"] for x in liste if x["zustand"] == "aktuell"]
    assert len(dran) <= 1, liste
    return dran[0] if dran else None, liste


def test_ohne_ablage_zuerst_die_einstellungen():
    assert aktuell(stand(ablage={"ort": "", "da": False}))[0] == "einstellungen"


def test_mit_ablage_ohne_pakete_planen():
    assert aktuell(stand(pakete=[], platten=[]))[0] == "planen"


def test_geaenderte_erschliessung_heisst_neu_planen_ausser_man_packt_trotzdem():
    assert aktuell(stand(veraltet=True))[0] == "planen"
    assert aktuell(stand(veraltet=True), veraltetOk=True)[0] == "platte:HD01"


def test_aenderung_nach_dem_schreiben_haelt_die_anleitung_nicht_auf():
    s = stand(veraltet=True, platten=[platte("HD01", offen=0)], pakete=[paket("HD01", "gebaut", geprueft_am="x")])
    assert aktuell(s)[0] == "fertig"


def test_ablage_nicht_angeschlossen():
    assert aktuell(stand(ablage={"ort": "datentraeger", "da": False, "name": "Arbeit"}))[0] == "ablage"


def test_platten_der_reihe_nach_die_erste_offene_ist_dran():
    dran, liste = aktuell(stand())
    assert dran == "platte:HD01"
    assert [x["k"] for x in liste if x["k"].startswith("platte:")] == ["platte:HD01", "platte:HD02"]
    s = stand(platten=[platte("HD01", offen=0), platte("HD02")], pakete=[paket("HD01", "gebaut", geprueft_am="x"), paket("HD02")])
    assert aktuell(s)[0] == "platte:HD02"


def test_alles_geschrieben_dann_an_kr():
    s = stand(platten=[platte("HD01", offen=0)], pakete=[paket("HD01", "gebaut", geprueft_am="x")])
    assert aktuell(s)[0] == "fertig"


def test_nur_ebenen_ohne_platte():
    s = stand(platten=[], pakete=[paket(None, art="ebenen")])
    assert aktuell(s)[0] == "ebenen"
    assert js("m.exAutostart(s, o)", s, gefuehrt=True) == ""


def test_autostart_erst_nach_packen_beginnen_und_nur_schreibgeschuetzt():
    da = stand(platten=[platte("HD01", da=True), platte("HD02")])
    assert js("m.exAutostart(s, o)", stand(), gefuehrt=True) is None                 # HD01 nicht angeschlossen
    assert js("m.exAutostart(s, o)", da, gefuehrt=False) is None                     # nicht begonnen
    assert js("m.exAutostart(s, o)", da, gefuehrt=True) == "HD01"
    beschreibbar = stand(platten=[platte("HD01", da=True, ro=False), platte("HD02")])
    assert js("m.exAutostart(s, o)", beschreibbar, gefuehrt=True) is None
    ordner = stand(platten=[platte("HD01", da=True, ro=False, ordner=True)])
    assert js("m.exAutostart(s, o)", ordner, gefuehrt=True) == "HD01"               # Ordner als Quelle: nur gelesen


def test_kein_autostart_bei_verschluesseltem_volume():
    """Verschlüsselt (13.11.2026): Balduin speichert das Passwort nicht; ein Lauf ohne es scheiterte sofort."""
    s = stand(platten=[platte("HD01", da=True, verschluesselt=True), platte("HD02")])
    assert js("m.exAutostart(s, o)", s, gefuehrt=True) is None
    # ohne Schreibschutz nach Zustimmung (Entscheidung 13.11.2026; unter Windows der Normalfall)
    zugestimmt = stand(platten=[platte("HD01", da=True, ro=False, ohne_schreibschutz=True), platte("HD02")])
    assert js("m.exAutostart(s, o)", zugestimmt, gefuehrt=True) == "HD01"


def test_autostart_je_platte_nur_einmal_und_nicht_neben_einem_lauf():
    da = stand(platten=[platte("HD01", da=True)])
    assert js("m.exAutostart(s, o)", da, gefuehrt=True, versucht=["HD01"]) is None
    assert js("m.exAutostart(s, o)", {**da, "lauf": {"aktiv": True}}, gefuehrt=True) is None


def test_autostart_nicht_ohne_platz_auf_der_ablage():
    s = stand(platten=[platte("HD01", da=True)], ablage={"ort": "datentraeger", "da": True, "frei": 10**9, "min_frei": 10**9})
    assert js("m.exAutostart(s, o)", s, gefuehrt=True) is None


def test_aktionen_nach_dem_import_erst_wenn_alles_uebergeben():
    assert js("m.exNachImportFrei(s)", stand(pakete=[])) is False
    assert js("m.exNachImportFrei(s)", stand(pakete=[paket("HD01", "übergeben"), paket("HD02", "gebaut")])) is False
    assert js("m.exNachImportFrei(s)", stand(pakete=[paket("HD01", "übergeben"), paket("HD02", "importiert")])) is True

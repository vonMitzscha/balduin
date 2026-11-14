"""Rückfragen und Meldungen (Entscheidung 13.11.2026): keine Browserdialoge (confirm, alert, prompt) in der
Oberfläche, sondern die gemeinsamen Dialoge aus tool/web/dialoge.js. Deren Verhalten wird mit Node an einem
nachgebauten Dialog geprüft."""
import json
import re
import shutil
import subprocess

import pytest

from conftest import CODE

WEB = CODE / "tool" / "web"
BROWSERDIALOG = re.compile(r"(?<![\w.$])(?:window\.)?(confirm|alert|prompt)\s*\(")


def _ohne_kommentare(zeile):
    """Zeilenkommentar abschneiden (grob: „//“ außerhalb von Adressen wie http://)."""
    return re.split(r"(?<!:)//", zeile, maxsplit=1)[0]


def test_keine_browserdialoge_in_der_oberflaeche():
    funde = []
    for datei in sorted(WEB.glob("*.js")) + [WEB / "index.html"]:
        for nr, zeile in enumerate(datei.read_text(encoding="utf-8").splitlines(), 1):
            if BROWSERDIALOG.search(_ohne_kommentare(zeile)):
                funde.append(f"{datei.name}:{nr}: {zeile.strip()[:100]}")
    assert not funde, "Browserdialog statt rueckfrage()/meldung():\n" + "\n".join(funde)


def test_dialoge_werden_vor_den_modulen_geladen():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'id="frage-dialog"' in html
    skripte = re.findall(r'<script src="/web/(\w+)\.js', html)
    assert "dialoge" in skripte
    assert skripte.index("dialoge") < min(skripte.index(m) for m in ("app", "erfassung", "erschliessung", "projekt"))


# Nachgebauter Dialog: Knöpfe mit onclick, showModal/close zählen mit
NACHBAU = """
const el = (id) => ({ id, textContent: "", hidden: false, onclick: null, focus() {}, addEventListener() {} });
const teile = { "frage-dialog": Object.assign(el("frage-dialog"), { offen: false, gezeigt: [], oncancel: null,
                  showModal() { this.offen = true; this.gezeigt.push(teile["frage-titel"].textContent); },
                  close() { this.offen = false; } }),
                "frage-titel": el("frage-titel"), "frage-text": el("frage-text"),
                "frage-ok": el("frage-ok"), "frage-abbrechen": el("frage-abbrechen") };
globalThis.document = { getElementById: (id) => teile[id] };
const d = require(%s);
const klick = (id) => teile[id].onclick({ preventDefault() {} });
const warten = () => new Promise((r) => setTimeout(r, 0));
"""


def _node(ablauf):
    if not shutil.which("node"):
        pytest.skip("node fehlt")
    code = NACHBAU % json.dumps(str(WEB / "dialoge.js")) + f"(async () => {{ {ablauf} }})();"
    r = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_rueckfrage_ja_nein_und_esc():
    erg = _node("""
      const a = d.rueckfrage("Löschen?", "Weg ist weg.", "Löschen"); await warten();
      const titel = teile["frage-titel"].textContent, text = teile["frage-text"].textContent;
      const knopf = teile["frage-ok"].textContent, ab = teile["frage-abbrechen"].hidden;
      klick("frage-ok");
      const b = d.rueckfrage("Nochmal?"); await warten(); klick("frage-abbrechen");
      const c = d.rueckfrage("Esc?"); await warten(); teile["frage-dialog"].oncancel({ preventDefault() {} });
      process.stdout.write(JSON.stringify({ titel, text, knopf, ab, a: await a, b: await b, c: await c,
                                            offen: teile["frage-dialog"].offen }));""")
    assert erg == {"titel": "Löschen?", "text": "Weg ist weg.", "knopf": "Löschen", "ab": False,
                   "a": True, "b": False, "c": False, "offen": False}


def test_meldung_hat_nur_ok_und_wartet_auf_die_vorige():
    erg = _node("""
      const a = d.meldung("Erster Fehler", "Fehler"); const b = d.meldung("Zweiter");
      await warten();
      const vorher = teile["frage-dialog"].gezeigt.slice(), ab = teile["frage-abbrechen"].hidden;
      klick("frage-ok"); await a; await warten();
      const danach = teile["frage-dialog"].gezeigt.slice(), text = teile["frage-text"].textContent;
      klick("frage-ok"); await b;
      process.stdout.write(JSON.stringify({ vorher, danach, ab, text }));""")
    assert erg == {"vorher": ["Fehler"], "danach": ["Fehler", "Hinweis"], "ab": True, "text": "Zweiter"}

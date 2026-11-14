"""Rauchtest der Oberfläche ohne Browser: Node lädt ein Skript aus tool/web/ mit einfachen Ersatzfunktionen für
app.js, icons.js und erfassung.js und zeichnet mit echten Antworten des Servers. Gefunden werden Laufzeitfehler
(undefined, falsche Feldnamen); wie es aussieht, prüft ein Mensch."""
import json
import shutil
import subprocess
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "tool" / "web"
ERSATZ = """
globalThis.$ = () => ({ textContent: "", innerHTML: "", hidden: true, setAttribute() {} });
globalThis.esc = (t) => String(t ?? "").replace(/[&<>"]/g, (z) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[z]);
globalThis.zahl = (n) => { if (n == null || Number.isNaN(Number(n))) throw new Error("zahl(" + n + ")"); return String(n); };
globalThis.bytes = (n) => { if (n == null || Number.isNaN(Number(n))) throw new Error("bytes(" + n + ")"); return n + " B"; };
globalThis.icon = (name) => `<i data-icon="${name}"></i>`;
globalThis.systemwort = (name) => ({ dateimanager: "Dateimanager" })[name] || name;   // wie in app.js
globalThis.STATUS_KLASSE = {}; globalThis.SCHRITT_ZEICHEN = {}; globalThis.dauer = () => "1 s";
"""


def node_da():
    return bool(shutil.which("node"))


def export_zeichnen(stand):
    """Zeichnet Modul 4 mit dem Stand von /api/export: beide Übersichten (alle Zeilen aufgeklappt), jede Aktion
    aufgeklappt, Lauf, Pakete und Zahnrad. Antwort: das HTML aller Teile (wirft bei einem Fehler)."""
    code = ERSATZ + f"""
const m = require({json.dumps(str(WEB / 'export.js'))});
const s = {json.dumps(stand)};
const teile = [];
for (const sicht of ["platten", "bestaende"]) {{
  m.ex.sicht = sicht;
  for (const p of s.platten) m.ex.auf.add("p:" + p.platte_id);
  for (const b of s.bestaende) m.ex.auf.add("b:" + (b.anton_id ?? "ohne"));
  teile.push(m.exUebersicht(s));
}}
for (const k of ["freigabe", "packen", "uebergabe", "kontrolle", "bericht"]) {{ m.ex.schritt = k; teile.push(m.exAktionenHtml(s), m.exDetailHtml(s)); }}
m.ex.gefuehrt = true; m.ex.schritt = "packen"; teile.push(m.exAktionenHtml(s), m.exDetailHtml(s));
for (const p of s.pakete) {{ m.ex.offen = p.paket_id; teile.push(m.exDetailHtml(s)); }}
m.ex.offen = null;
teile.push(m.exLaeufe(s), m.exPaketeUebersicht(s), m.exEinstellungenHtml(s, "zahnrad"));
process.stdout.write(teile.join("\\n"));
"""
    r = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise AssertionError(r.stderr)
    return r.stdout

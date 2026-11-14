// Rauchtest von Registrierung/Analyse ohne Browser (tests/test_mac_volumes.py): lädt tool/web/erfassung.js mit
// Ersatzfunktionen für app.js, icons.js und dialoge.js und zeichnet Formular und Panel für die Fälle aus argv[3]
// (JSON). Ausgabe: je Fall das HTML von #angaben bzw. #dt-hinweis; Laufzeitfehler brechen ab.
const fs = require("fs"), vm = require("vm");
const elemente = new Map();
const el = (sel) => {
  if (!elemente.has(sel)) elemente.set(sel, { innerHTML: "", textContent: "", hidden: false, value: "", dataset: {},
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } }, addEventListener() {}, setAttribute() {},
    querySelector: () => null, querySelectorAll: () => [], focus() {}, style: {} });
  return elemente.get(sel);
};
const ctx = { console, setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0, Set, Map, Math, JSON, Date, Number,
  String, Promise, window: {}, location: { hash: "" }, $: el, $$: () => [],
  document: { addEventListener() {}, querySelector: el, querySelectorAll: () => [], getElementById: el },
  esc: (t) => String(t ?? "").replace(/[&<>"]/g, (z) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[z]),
  zahl: (n) => { if (n == null) throw new Error("zahl(" + n + ")"); return String(n); },
  bytes: (n) => { if (n == null) throw new Error("bytes(" + n + ")"); return n + " B"; },
  icon: (n) => `<i data-icon="${n}"></i>`, traegerIcon: (a) => `<i data-traeger="${a}"></i>`, systemwort: (n) => n,
  anteilProzent: (x) => x, holen: async () => ({}), senden: async () => ({}), meldung: async () => {},
  rueckfrage: async () => true, passwortFragen: async () => "", passwortGeprueft: async () => null,
  PFLICHT: `<span class="pflicht" title="Pflichtfeld">*</span>` };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8") + "\n;globalThis.__erf = erf;", ctx, { filename: "erfassung.js" });
const erf = ctx.__erf;
const aus = {};
for (const fall of JSON.parse(process.argv[3])) {
  Object.assign(erf, fall.erf);
  vm.runInContext(fall.ziel === "#dt-hinweis" ? "datentraegerZeichnen()" : "angabenZeichnen()", ctx);
  aus[fall.name] = el(fall.ziel || "#angaben").innerHTML;
}
process.stdout.write(JSON.stringify(aus));

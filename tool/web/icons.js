// Icons aus Lucide (vendor/lucide/sprite.svg, offline); Namen auf https://lucide.dev/icons.
// Im gespeicherten Bericht stehen die Symbole in der Seite selbst (ICON_QUELLE = "").
// Namen immer als Text in icon("…") schreiben: der Bericht sucht so heraus, welche er einbetten muss.
const ICON_QUELLE = window.ICON_QUELLE ?? "/web/vendor/lucide/sprite.svg";
function icon(name, klasse = "") {
  return `<svg class="icon${klasse ? " " + klasse : ""}" aria-hidden="true"><use href="${ICON_QUELLE}#${name}"/></svg>`;
}

// Pflichtfeld (Feedback 14.11.2026): überall dieselbe Marke hinter der kurzen Bezeichnung, wie in der Erschließung;
// was das Feld verlangt, steht leise darunter, nicht in Klammern in der Bezeichnung
const PFLICHT = `<span class="pflicht" title="Pflichtfeld" aria-label="Pflichtfeld">*</span>`;

// Leeres Pflichtfeld (Feedback 14.11.2026): roter Rahmen um seine Eingaben, bis in einer davon etwas steht.
// Das Feld ist das <label> oder die Editorzeile (.es-zeile) mit der Marke; data-freiwillig (z. B. „bis“ der
// Laufzeit), gesperrte Eingaben und Vorschläge zählen nicht mit.
const PFLICHT_EINGABEN = "input:not([type=checkbox]):not([type=radio]):not([type=file]):not([type=hidden]):not([data-begriff-suche]), textarea, select";
function pflichtMarkieren(wurzel = document) {
  for (const marke of wurzel.querySelectorAll(".pflicht")) {
    const feld = marke.closest(".es-zeile, label");
    if (!feld) continue;
    const eingaben = [...feld.querySelectorAll(PFLICHT_EINGABEN)]
      .filter((e) => !e.disabled && !("freiwillig" in e.dataset) && !e.closest(".es-vorschlaege"));
    const leer = eingaben.every((e) => !String(e.value ?? "").trim());
    for (const e of eingaben) e.classList.toggle("pflicht-leer", leer);
  }
}
// Nachführen bei Eingaben und neu gezeichneten Teilen (beobachtet nur Kinder, nicht Klassen: keine Schleife)
if (typeof document !== "undefined" && typeof MutationObserver !== "undefined") {
  let geplant = false;
  const bald = () => {
    if (geplant) return;
    geplant = true;
    requestAnimationFrame(() => { geplant = false; pflichtMarkieren(); });
  };
  document.addEventListener("input", bald, true);
  document.addEventListener("change", bald, true);
  new MutationObserver(bald).observe(document.documentElement, { childList: true, subtree: true });
}

// Art des Datenträgers (Entscheidung 05.11.2026): Schlüssel aus erfassung/system.py → traegerart / traeger_der_platte.
// Eine Sehhilfe, kein Befund: USB-Stick und USB-Platte trennt nur das Merkmal Wechselmedium.
const TRAEGER = {
  cd: ["CD/DVD", icon("disc")],
  karte: ["Speicherkarte", icon("memory-stick")],
  usb: ["USB-Stick (Wechselmedium)", icon("usb")],
  image: ["Image-Datei", icon("disc-album")],
  festplatte: ["Festplatte/SSD", icon("hard-drive")],
  ordner: ["Ordner als Quelle", icon("folder")],
  "": ["Datenträger (Art unbekannt)", icon("hard-drive")],
};
// Archivdateien (ZIP, tar, gz) erscheinen als Ordner (Entscheidung 06.11.2026); im Baum mit eigenem Symbol, damit die
// andere Herkunft sichtbar bleibt. Ein Ordner mit dieser Endung kann nur eine aufgelöste Archivdatei sein (Endungen wie
// art_von in erfassung/archivdateien.py; nicht auflösbare Archive bleiben Dateien).
const ARCHIV_ENDUNG = /.\.(zip|tar|tgz|tbz2?|txz|gz|bz2|xz)$/i;
function ordnerIcon(name, klasse = "") {
  if (!ARCHIV_ENDUNG.test(name || "")) return icon("folder", klasse);
  const titel = "Archivdatei, wie ein Ordner aufgelöst";
  return icon("folder-archive", klasse).replace('aria-hidden="true">', `role="img" aria-label="${titel}"><title>${titel}</title>`);
}

function traegerIcon(art, anschluss = "", klasse = "") {
  const [text, svg] = TRAEGER[art || ""] || TRAEGER[""];
  const titel = (text + (anschluss && art !== "ordner" ? ` · Anschluss ${anschluss}` : "")).replace(/[<>&"]/g, "");
  return svg.replace('class="icon"', `class="icon traeger${klasse ? " " + klasse : ""}"`)
            .replace('aria-hidden="true">', `role="img" aria-label="${titel}"><title>${titel}</title>`);
}

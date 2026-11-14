// Bewertung, Stufe 1: Bäume, Inspektor, Editor (nur lesen)
"use strict";

const zustand = {
  platten: [],
  aktiv: null,                  // {platte, pfad, art: "platte" | "ordner" | "datei"}
  angaben: null,                // zuletzt geladene Angaben zum aktiven Element (für den Editor)
  auswahl: new Map(),           // "platte|pfad" -> {platte, pfad, art}
  anker: null,                  // zuletzt angeklickt {k, an}: Ausgangspunkt für Umschalt+Klick
  grenze: 300,                  // Mindestgröße der Regel „kleine Bilder“ (px, lange Seite)
  jedes: 10,                    // Stichprobe: jedes x. Element übernehmen
  formateOffen: false,
  vergleich: "ordner",          // "ordner" = gleiche Ordner, "dateien" = Dateien anderswo
  alleArten: false,             // false = nur exakt gleich, true = auch Varianten und beinahe gleich
  einstellungen: [],            // globale Einstellungen laut Server (vor „Anwenden“)
  thumbsOk: null,               // Ordner der Vorschaubilder erreichbar (false: Platzhalter statt Bild, siehe bild())
};

// ---------- Hilfen ----------
const $ = (sel, wurzel = document) => wurzel.querySelector(sel);
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (z) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[z]));
const zahl = (n) => (n ?? 0).toLocaleString("de-CH");
// Wörter je Betriebssystem (Dateimanager, Schlüsselspeicher …) aus erfassung/system.py → systemwoerter(); die Seite
// bringt sie als window.SYSTEMWOERTER mit (Wording, Entscheidung 13.11.2026). Nie „Finder“ o. Ä. fest in den Text.
const systemwort = (name) => ((typeof window !== "undefined" && window.SYSTEMWOERTER) || {})[name]
  || { system: "dem System", dateimanager: "Dateimanager", schluesselspeicher: "Schlüsselspeicher des Systems",
       im_schluesselspeicher: "im Schlüsselspeicher des Systems", aus_dem_schluesselspeicher: "aus dem Schlüsselspeicher des Systems",
       adminfrage: "das System fragt einmal nach Administratorrechten", formatierwarnung: "", kein_schreibschutz: "" }[name];

// Ohne Schreibschutz lesen (Entscheidung 13.11.2026): Rückfrage einmal je Datenträger, dann beim Server vermerkt
// (/api/ohne_schreibschutz, protokolliert, in der Bestandsgeschichte). Unter Windows geht es nicht anders; auf dem
// Mac und unter Linux ist „Schreibgeschützt einhängen“ der bessere Weg. Antwort: zugestimmt?
async function ohneSchreibschutzFragen(kennung) {
  const grund = systemwort("kein_schreibschutz")
    || "Der Datenträger ist beschreibbar eingehängt. Besser ist es, ihn vorher schreibgeschützt einzuhängen.";
  return rueckfrage(`${kennung} ohne Schreibschutz lesen?`,
    `${grund} Beim Anschließen kann das Betriebssystem eigene kleine Dateien darauf anlegen, etwa einen Index oder einen `
    + "Papierkorb. Die Dateien des Bestands bleiben unverändert; Balduin selbst schreibt nie auf den Datenträger und führt "
    + "solche Dateien als Systemdateien.\n\nWer ganz sauber arbeiten will, schließt den Datenträger über einen Writeblocker "
    + "an (ein Gerät zwischen Datenträger und Rechner, das jedes Schreiben verhindert). Dann ist er schreibgeschützt, und "
    + "Balduin fragt nicht.\n\nDie Zustimmung gilt für diesen Datenträger. Sie wird protokolliert und in der "
    + "Bestandsgeschichte jeder Datei vermerkt.", "Ohne Schreibschutz lesen");
}
const prozent = (teil, ganz) => (ganz ? Math.round((100 * teil) / ganz) : 0) + " %";
function bytes(n) {
  const e = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1000 && i < e.length - 1) { n /= 1000; i++; }
  return (i ? n.toFixed(n < 10 ? 1 : 0).replace(".", ",") : n) + " " + e[i];
}
const schluessel = (platte, pfad) => platte + "|" + pfad;
const thumbUrl = (t) => "/thumbs/" + t.split("/").map(encodeURIComponent).join("/");
const zeigeAttr = (platte, pfad) => `data-zeige="${esc(platte)}|${esc(pfad)}"`;

// Nach einem Neustart von Balduin gilt der Sitzungsschlüssel eines offenen Tabs nicht mehr: Seite einmal neu laden
// (holt den neuen Schlüssel). Höchstens alle 10 Sekunden, damit nichts endlos neu lädt.
function sitzungPruefen(antwort, daten) {
  if (antwort.status !== 403 || !String(daten.fehler || "").startsWith("Sitzung abgelaufen")) return;
  let zuletzt = 0;
  try { zuletzt = Number(sessionStorage.getItem("neu_geladen") || 0); } catch { /* ohne Speicher: trotzdem laden */ }
  if (Date.now() - zuletzt < 10000) return;
  try { sessionStorage.setItem("neu_geladen", String(Date.now())); } catch { /* egal */ }
  location.reload();
}

async function holen(pfad, werte = {}) {
  const antwort = await fetch(pfad + "?" + new URLSearchParams(werte));
  const daten = await antwort.json();
  sitzungPruefen(antwort, daten);
  if (!antwort.ok || daten.fehler) throw new Error(daten.fehler || antwort.statusText);
  return daten;
}

async function senden(pfad, daten) {
  const antwort = await fetch(pfad, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(daten) });
  const ergebnis = await antwort.json();
  sitzungPruefen(antwort, ergebnis);
  if (!antwort.ok || ergebnis.fehler) throw new Error(ergebnis.fehler || antwort.statusText);
  return ergebnis;
}

// Platzhalter in Größe des Vorschaubilds, wenn es (noch) nicht zu sehen ist: Arbeitsplatte nicht angeschlossen
// oder Bild nicht ladbar. So bleibt Galerie, Inspektor und Liste gleich aufgebaut.
const PLATZHALTER_TITEL = "Vorschaubild nicht erreichbar (ist der Datenträger für Vorschaubilder angeschlossen?)";
// data-thumb und data-alt: damit lässt sich der Platzhalter wieder gegen das Bild tauschen (bilderNachholen)
const platzhalter = (klasse, thumb = "", alt = "") => `<div class="ohne platzhalter ${klasse}" title="${PLATZHALTER_TITEL}"
  data-thumb="${esc(thumb)}" data-alt="${esc(alt)}" data-klasse="${esc(klasse)}">${icon("image-off")}</div>`;

function bild(thumb, alt, klasse = "") {
  if (!thumb) return `<div class="ohne ${klasse}">keine Vorschau</div>`;
  if (zustand.thumbsOk === false) return platzhalter(klasse, thumb, alt);    // Arbeitsplatte fehlt: gar nicht erst laden
  return `<img class="${klasse}" loading="lazy" src="${thumbUrl(thumb)}" alt="${esc(alt)}"
           onerror="bildFehlt(this)">`;
}

// Bild ließ sich nicht laden: Platzhalter an seine Stelle (mit Bild-Angaben, für einen späteren Versuch)
function bildFehlt(img) {
  img.outerHTML = platzhalter(img.className, decodeURIComponent(new URL(img.src).pathname.slice(8)), img.alt);
}

// Platzhalter wieder gegen Bilder tauschen (Arbeitsplatte angeschlossen)
function bilderNachholen() {
  document.querySelectorAll(".platzhalter[data-thumb]").forEach((el) => {
    if (el.dataset.thumb) el.outerHTML = bild(el.dataset.thumb, el.dataset.alt, el.dataset.klasse);
  });
}

const SYMBOL = {
  platte: icon("hard-drive", "symbol"),
  ordner: icon("folder", "symbol"),
  datei: icon("file", "symbol"),
};

// ---------- Balken und Punkte ----------
const AMPEL = [["grün", "a-gruen", "grün"], ["gelb", "a-gelb", "gelb"], ["rot", "a-rot", "rot"], ["ohne_ampel", "a-ohne", "ohne Ampel"]];
const BEWERTUNG = [["uebernehmen", "e-ueb", "übernommen"], ["kassieren", "e-kas", "kassiert"],
                   ["zurueckgestellt", "e-zur", "zurückgestellt"], ["offen", "e-offen", "offen"]];
const DUBLETTEN = [["stark_exakt", "d-exakt", "exakt gleich"], ["stark_variante", "d-variante", "Variante"],
                   ["stark_beinahe", "d-beinahe", "beinahe gleich"]];
const ART_NAME = { exakt: "exakt gleich", variante: "Formatvariante", beinahe: "beinahe gleich" };

function balken(z, teile, gross = false) {
  const ganz = z.dateien || 0;
  const stuecke = teile.filter(([k]) => z[k]).map(([k, klasse]) =>
    `<i class="${klasse}" style="width:${(100 * z[k]) / ganz}%"></i>`).join("");
  return `<span class="balken${gross ? " gross" : ""}">${stuecke}</span>`;
}
function teileText(z, teile) {
  return teile.filter(([k]) => z[k]).map(([k, , n]) => `${n} ${zahl(z[k])}`).join(" · ") || "keine";
}
function balkenDrei(z) {
  const titel = `${zahl(z.dateien)} Dateien, ${bytes(z.bytes)}\nArchivfähigkeit: ${teileText(z, AMPEL)}\n`
              + `Bewertung: ${teileText(z, BEWERTUNG)}\nDubletten: ${teileText(z, DUBLETTEN)}`;
  return `<span class="rechts" title="${esc(titel)}">${balken(z, AMPEL)}${balken(z, BEWERTUNG)}${balken(z, DUBLETTEN)}</span>`;
}
// Entscheidung eines Elements: Farbe, kurze und lange Bezeichnung
const URTEIL = { "übernehmen": ["e-ueb", "übern.", "übernommen"], "kassieren": ["e-kas", "kassiert", "kassiert"],
                 "zurückstellen": ["e-zur", "zurückg.", "zurückgestellt"], "offen": ["e-offen", "offen", "unentschieden"] };
const SCHLOSS = icon("lock", "schloss");
// F5: Symbol an Fotos, auf deren Vorschaubild Menschen erkannt wurden (nur Hinweis, keine Entscheidung):
// Gesicht = Porträt (ein großes Gesicht), Gruppe = Personen allgemein. d: Datei mit personen, gesichter, bildtyp
const anzahlText = (n, eins, mehr) => (n === 1 ? `1 ${eins}` : `${zahl(n)} ${mehr}`);
const personenArt = (d) => (d.bildtyp === "porträt" ? "Porträt" : "Personen");
const personenAnzahl = (d) => [d.personen ? anzahlText(d.personen, "Person", "Personen") : "",
                               d.gesichter ? anzahlText(d.gesichter, "Gesicht", "Gesichter") : ""].filter(Boolean).join(", ");
const personenText = (d) => `${personenArt(d)} (${personenAnzahl(d)}) · automatisch erkannt, auf dem Vorschaubild`;
const personMarke = (d) => (d.bildtyp
  ? `<span class="person-marke" title="${esc(personenText(d))}">${d.bildtyp === "porträt" ? icon("user") : icon("users")}</span>` : "");
function urteilText(u) {
  if (!u) return "offen";
  if (u.automatisch) return URTEIL[u.entscheidung][2] + " (automatisch: " + u.automatisch + ")";
  return URTEIL[u.entscheidung][2] + (u.vorbehalt ? " mit Vorbehalt" : "") + (u.eigen ? " (hier entschieden)" : ` (geerbt von ${u.quelle || "ganzem Datenträger"})`);
}
function urteilMarke(u) {
  if (!u) return `<span class="urteil"></span>`;
  const [klasse, kurz] = URTEIL[u.entscheidung];
  return `<span class="urteil"><span class="u-marke ${klasse}${u.eigen ? " eigen" : " geerbt"}${u.automatisch ? " auto" : ""}" title="${esc(urteilText(u))}">`
       + `${SCHLOSS}${kurz}${u.vorbehalt ? '<b class="vb">V</b>' : ""}</span></span>`;
}
function punkte(d) {
  const ampel = { "grün": "a-gruen", "gelb": "a-gelb", "rot": "a-rot" }[d.ampel] || "a-ohne";
  const dub = d.arten.length ? "d-" + d.arten[0] : "leer";
  const titel = [`Archivfähigkeit: ${d.ampel || "ohne"}`, `Bewertung: ${urteilText(d.urteil)}`,
                 `Dubletten: ${d.arten.length ? d.arten.map((a) => ART_NAME[a]).join(", ") : "keine"}`,
                 d.anton ? `Anton: ${d.anton}` : ""].filter(Boolean).join("\n");
  const bew = d.urteil ? URTEIL[d.urteil.entscheidung][0] : "leer";
  return `<span class="punkte" title="${esc(titel)}">
    <i class="punkt ${ampel}"></i><i class="punkt ${bew}"></i><i class="punkt ${dub}"></i>
    ${d.anton === "in Anton" ? '<span class="marke-a">A</span>' : ""}</span>`;
}

// ---------- Ankreuzen: ein Zustand für Baum, Suchtreffer und Galerie ----------
function kreuz(platte, pfad) {
  const k = schluessel(platte, pfad);
  return `<input type="checkbox" data-k="${esc(k)}" ${zustand.auswahl.has(k) ? "checked" : ""} aria-label="auswählen">`;
}

function ankreuzen(eintraege, an) {
  for (const { platte, pfad, art } of eintraege) {
    const k = schluessel(platte, pfad);
    if (an) zustand.auswahl.set(k, { platte, pfad, art });
    else zustand.auswahl.delete(k);
    document.querySelectorAll(`input[data-k="${CSS.escape(k)}"]`).forEach((c) => {
      c.checked = an;
      c.closest(".kachel")?.classList.toggle("angekreuzt", an);
    });
  }
  alleKreuzZeichnen();
  bewertungAuswahlFaerben();
  editorZeichnen();
}
const auswahlAufheben = () => { if (zustand.auswahl.size) ankreuzen([...zustand.auswahl.values()], false); };

// Auswahl über alle Ebenen sichtbar (Feedback 05.11.2026, für Bewertung und Erschließung): angekreuzte Zeilen
// eingefärbt, Ordner und Platten mit der Zahl der angekreuzten Elemente darunter; dazu die Marke „N angekreuzt ✕“
// neben dem Kästchen der Kopfzeile (marke), die die Auswahl aufhebt
function auswahlFaerben(listen, auswahl, marke) {
  const werte = [...auswahl.values()];
  for (const liste of listen) {
    for (const li of liste.querySelectorAll("li[data-art]")) {
      const zeile = li.querySelector(":scope > .zeile");
      if (!zeile) continue;
      const { platte, pfad, art } = li.dataset;
      zeile.classList.toggle("angekreuzt", auswahl.has(schluessel(platte, pfad)));
      const n = art === "datei" || !werte.length ? 0 : werte.filter((v) => v.platte === platte && v.pfad !== pfad
        && (!pfad || v.pfad.startsWith(pfad + "/"))).length;
      let zahlMarke = zeile.querySelector(".auswahl-zahl");
      if (!n) { zahlMarke?.remove(); continue; }
      if (!zahlMarke) {
        zahlMarke = document.createElement("span");
        zahlMarke.className = "auswahl-zahl";
        zeile.querySelector(".name")?.after(zahlMarke);
      }
      zahlMarke.textContent = `${zahl(n)} darin`;
      zahlMarke.title = `${zahl(n)} ${n === 1 ? "Element" : "Elemente"} darunter ausgewählt`;
    }
  }
  if (marke) {
    marke.hidden = !auswahl.size;
    marke.innerHTML = `${zahl(auswahl.size)} ausgewählt ${icon("x")}`;
    marke.title = "Auswahl aufheben (auch Esc oder Klick ins Leere)";
  }
}
// Marke neben dem Kästchen der Kopfzeile eines Baums
function auswahlMarkeAnlegen(kasten, aufheben) {
  const marke = document.createElement("button");
  marke.type = "button";
  marke.className = "auswahl-marke";
  marke.hidden = true;
  marke.addEventListener("click", aufheben);
  kasten.parentElement.append(marke);
  return marke;
}
const bewertungMarke = auswahlMarkeAnlegen($("#alle-kreuz"), () => auswahlAufheben());
const bewertungAuswahlFaerben = () => auswahlFaerben([$("#baum"), $("#treffer")], zustand.auswahl, bewertungMarke);
// Klick ins Leere des Baums: nur, wenn er keine Zeile, keinen Knopf und kein Feld trifft
const insLeere = (e) => !e.target.closest(".zeile, button, input, label, select, a, .mehr-zeile");
// Esc hebt die Auswahl der sichtbaren Ansicht auf, außer in Eingabefeldern und Dialogen
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape" || e.target.closest("input, textarea, select, dialog")) return;
  if (!$("#bewertung").hidden) auswahlAufheben();
});

// Mehrfachauswahl mit Tastatur (Baum, Suchtreffer, Galerie): Strg/⌘+Klick nimmt ein Element auf oder heraus,
// Umschalt+Klick (auch mit Strg) kreuzt alle sichtbaren Elemente seit dem letzten Klick an (oder ab).
// Dieselben Regeln gelten im Baum der Erschließung: sie übergibt ihre eigene Auswahl als Parameter a
// ({auswahl: Map, anker, ankreuzen(eintraege, an)}); ohne Parameter gilt die der Bewertung.
const mitStrg = (e) => e.ctrlKey || e.metaKey;
const elSchluessel = (el) => schluessel(el.dataset.platte, el.dataset.pfad);
const eintragVon = (el) => ({ platte: el.dataset.platte, pfad: el.dataset.pfad, art: el.dataset.art || "datei" });
const bewertungAuswahl = {
  get auswahl() { return zustand.auswahl; },
  get anker() { return zustand.anker; },
  set anker(wert) { zustand.anker = wert; },
  ankreuzen: (eintraege, an) => ankreuzen(eintraege, an),
};
const ankerSetzen = (el, an, a = bewertungAuswahl) => { a.anker = { k: elSchluessel(el), an }; };

function mehrfachKlick(e, el, liste, a = bewertungAuswahl) {
  if (!e.shiftKey && !mitStrg(e)) return false;
  const k = elSchluessel(el);
  if (e.shiftKey && a.anker) {
    const i = liste.indexOf(el), j = liste.findIndex((x) => elSchluessel(x) === a.anker.k);
    if (i >= 0 && j >= 0) {
      a.ankreuzen(liste.slice(Math.min(i, j), Math.max(i, j) + 1).map(eintragVon), a.anker.an);
      return true;                                              // Anker bleibt: weitere Umschalt+Klicks vom selben Punkt
    }
  }
  const an = e.shiftKey || !a.auswahl.has(k);                   // Umschalt ohne Anker in dieser Liste: nur dieses ankreuzen
  a.ankreuzen([eintragVon(el)], an);
  ankerSetzen(el, an, a);
  return true;
}

// Sichtbare Zeilen in Reihenfolge (zugeklappte Ordner ausgenommen)
const baumZeilen = () => [...document.querySelectorAll("#baum li[data-art]")].filter((li) => !li.closest("ul[hidden]"));
const trefferZeilen = () => [...$("#treffer").children].filter((li) => li.dataset.art);
const galerieKacheln = () => [...document.querySelectorAll("#inspektor .kachel")];

// Auf dem Mac löst Strg+Klick das Kontextmenü aus statt eines Klicks: dort abfangen.
// Umschalt+Klick soll keinen Text markieren.
let kontextKlick = 0;
const nachKontextKlick = (e) => e.ctrlKey && Date.now() - kontextKlick < 500;   // folgender Klick (Firefox) zählt nicht doppelt
function tastaturAuswahl(container, finden, liste, a = bewertungAuswahl) {
  container.addEventListener("contextmenu", (e) => {
    const el = e.ctrlKey && finden(e.target);
    if (!el) return;
    e.preventDefault();
    kontextKlick = Date.now();
    mehrfachKlick(e, el, liste(), a);
  });
  container.addEventListener("mousedown", (e) => { if (e.shiftKey && finden(e.target)) e.preventDefault(); });
}
const zeileVon = (t) => t.closest(".zeile")?.parentElement;
tastaturAuswahl($("#baum"), zeileVon, baumZeilen);
tastaturAuswahl($("#treffer"), zeileVon, trefferZeilen);
tastaturAuswahl($("#inspektor"), (t) => t.closest(".kachel"), galerieKacheln);

// Kästchen in der Kopfzeile: im Baum alle Platten (= der ganze Bestand, Ordner und Dateien erben),
// bei laufender Suche alle gezeigten Treffer. Abwählen hebt die ganze Auswahl auf.
const sucheAktiv = () => !$("#treffer").hidden;
function obersteZeilen() {
  return [...(sucheAktiv() ? $("#treffer") : $("#baum")).children].filter((li) => li.dataset.art)
    .map(({ dataset: { platte, pfad, art } }) => ({ platte, pfad, art }));
}
function alleKreuzZeichnen() {
  const kasten = $("#alle-kreuz");
  if (!kasten) return;
  const ziele = obersteZeilen();
  const alle = ziele.length > 0 && ziele.every((z) => zustand.auswahl.has(schluessel(z.platte, z.pfad)));
  kasten.checked = alle;
  kasten.indeterminate = !alle && zustand.auswahl.size > 0;     // teilweise angekreuzt
  kasten.disabled = !ziele.length && !zustand.auswahl.size;
  kasten.title = alle || zustand.auswahl.size ? "Auswahl aufheben"
    : sucheAktiv() ? "Alle gezeigten Treffer auswählen" : "Alles auswählen (alle Datenträger)";
}
$("#alle-kreuz").addEventListener("change", (e) => {
  if (!e.target.checked || zustand.auswahl.size) {             // auch bei „teilweise“: erst einmal alles abwählen
    ankreuzen([...zustand.auswahl.values()], false);
    return;
  }
  ankreuzen(obersteZeilen(), true);
});

// ---------- Baum ----------
function zellenRechts(art, z, urteil) {
  return `<span class="groesse">${bytes(art === "datei" ? z.groesse : z.bytes)}</span>${urteilMarke(urteil)}`
       + (art === "datei" ? punkte(z) : balkenDrei(z));
}

// Nach einer Entscheidung: alle sichtbaren Zeilen und Galeriebilder mit dem neuen Stand zeichnen
async function zeilenAktualisieren() {
  const zeilen = [...document.querySelectorAll("#baum li[data-art], #treffer li[data-art]")];
  const kacheln = [...document.querySelectorAll("#inspektor .kachel")];
  const ziele = new Map([...zeilen, ...kacheln].map((x) => [schluessel(x.dataset.platte, x.dataset.pfad),
                                                            { platte: x.dataset.platte, pfad: x.dataset.pfad }]));
  if (!ziele.size) return;
  const je = new Map((await senden("/api/knoten", { ziele: [...ziele.values()] })).map((d) => [schluessel(d.platte, d.pfad), d]));
  for (const li of zeilen) {
    const d = je.get(schluessel(li.dataset.platte, li.dataset.pfad));
    if (!d) continue;
    const zeile = li.querySelector(":scope > .zeile");
    while (zeile.lastElementChild && !zeile.lastElementChild.classList.contains("links")) zeile.lastElementChild.remove();
    zeile.insertAdjacentHTML("beforeend", zellenRechts(li.dataset.art, d.art === "datei" ? d : d.zaehler, d.urteil));
  }
  for (const k of kacheln) {
    const d = je.get(schluessel(k.dataset.platte, k.dataset.pfad));
    if (d) k.querySelector(".kachel-urteil").innerHTML = urteilMarke(d.urteil);
  }
}

function knoten(art, platte, pfad, name, z, tiefe, extra = "", urteil = z.urteil) {
  const li = document.createElement("li");
  Object.assign(li.dataset, { art, platte, pfad, tiefe });
  li.setAttribute("role", "treeitem");
  li.innerHTML = `<div class="zeile${art === "platte" ? " plattenzeile" : ""}" style="--tiefe:${tiefe}">
      <span class="links">
        ${kreuz(platte, pfad)}
        <span class="pfeil">${art === "datei" ? "" : icon("chevron-right")}</span>
        ${art === "ordner" ? ordnerIcon(name, "symbol") : SYMBOL[art]}
        <span class="name" title="${esc(pfad || name)}">${esc(name)}${extra}</span>${art === "datei" ? personMarke(z) : ""}
      </span>
      ${zellenRechts(art, z, urteil)}
    </div>`;
  return li;
}

async function kinderLaden(li, offset = 0) {
  let ul = li.querySelector(":scope > ul");
  if (!ul) { ul = document.createElement("ul"); ul.setAttribute("role", "group"); li.append(ul); }
  const tiefe = Number(li.dataset.tiefe) + 1;
  const d = await holen("/api/kinder", { platte: li.dataset.platte, pfad: li.dataset.pfad, offset,
                                         system: $("#systemdateien").checked ? 1 : 0 });
  ul.querySelector(":scope > .mehr-zeile")?.remove();
  if (!offset) {
    for (const o of d.ordner) ul.append(knoten("ordner", li.dataset.platte, o.pfad, o.name, o.zaehler, tiefe, "", o.urteil));
  }
  for (const f of d.dateien) ul.append(knoten("datei", f.platte, f.pfad, f.name, f, tiefe));
  if (d.weitere) {
    const mehr = document.createElement("li");
    mehr.className = "mehr-zeile";
    mehr.innerHTML = `<button type="button" class="knopf-leise">${zahl(d.weitere)} weitere Dateien laden</button>`;
    mehr.querySelector("button").onclick = () => kinderLaden(li, d.offset);
    ul.append(mehr);
  }
  li.dataset.geladen = "1";
  bewertungAuswahlFaerben();
}

async function aufklappen(li, offen = !li.classList.contains("offen")) {
  if (li.dataset.art === "datei") return;
  li.classList.toggle("offen", offen);
  li.setAttribute("aria-expanded", offen);
  if (offen && !li.dataset.geladen) await kinderLaden(li);
  const ul = li.querySelector(":scope > ul");
  if (ul) ul.hidden = !offen;
}

function baumZeichnen() {
  const baum = $("#baum");
  baum.innerHTML = "";
  for (const p of zustand.platten) {
    const extra = `<small>${esc(p.volume)}${p.kopie_von ? " · Kopie von " + esc(p.kopie_von) : ""}</small>`;
    const li = knoten("platte", p.id, "", p.id, p.zaehler, 0, extra, p.urteil);
    li.querySelector(".symbol").outerHTML = traegerIcon(p.traeger, "", "symbol");   // Art des Datenträgers
    if (p.etikett) li.querySelector(".name").title = "Etikett:\n" + p.etikett;
    baum.append(li);
  }
  alleKreuzZeichnen();
  bewertungAuswahlFaerben();
}

// Klick im Baum: Pfeil klappt auf, Kästchen merkt die Auswahl, Zeile öffnet Inspektor und Editor
$("#baum").addEventListener("click", (ereignis) => {
  const zeile = ereignis.target.closest(".zeile");
  if (!zeile) { if (insLeere(ereignis)) auswahlAufheben(); return; }
  const li = zeile.parentElement;
  const { art, platte, pfad } = li.dataset;
  if (nachKontextKlick(ereignis)) return;
  if (mehrfachKlick(ereignis, li, baumZeilen())) return;
  if (ereignis.target.matches("input[type=checkbox]")) {
    ankreuzen([{ platte, pfad, art }], ereignis.target.checked);
    ankerSetzen(li, ereignis.target.checked);
    return;
  }
  if (ereignis.target.closest(".pfeil")) { aufklappen(li); return; }
  if (auswahlKlick(li)) return;
  ankerSetzen(li, true);
  waehlen(li);
  if (art !== "datei" && !li.classList.contains("offen")) aufklappen(li, true);
});

// Ist etwas angekreuzt, kreuzt ein einfacher Klick weitere an oder ab (wie die Chips der Analyse)
function auswahlKlick(li, a = bewertungAuswahl) {
  if (!a.auswahl.size) return false;
  const an = !a.auswahl.has(elSchluessel(li));
  a.ankreuzen([eintragVon(li)], an);
  ankerSetzen(li, an, a);
  return true;
}

// ---------- Suche ----------
let suchZeitgeber = null;
function sucheZeigen(an) {
  $("#treffer").hidden = !an;
  $("#suche-info").hidden = !an;
  $("#baum").hidden = an;
  alleKreuzZeichnen();
}
async function suchen() {
  const q = $("#suche").value.trim();
  if (q.length < 2) { sucheZeigen(false); return; }
  const d = await holen("/api/suche", { q, system: $("#systemdateien").checked ? 1 : 0 });
  if ($("#suche").value.trim() !== q) return;                 // inzwischen weitergetippt
  const liste = $("#treffer");
  liste.innerHTML = "";
  for (const t of d.treffer) {
    const ort = `<span class="trefferpfad">${esc(t.platte)} / ${esc(t.pfad.split("/").slice(0, -1).join("/") || "(oberste Ebene)")}</span>`;
    liste.append(knoten(t.art, t.platte, t.pfad, t.name, t.art === "datei" ? t : t.zaehler, 0, ort, t.urteil));
  }
  $("#suche-info").textContent = !d.gesamt ? "Keine Treffer."
    : `${zahl(d.gesamt)} Treffer${d.gesamt > d.treffer.length ? `, die ersten ${d.treffer.length} gezeigt (Suche genauer fassen)` : ""}. `
      + "Klick auf einen Treffer zeigt ihn im Baum; Esc beendet die Suche.";
  sucheZeigen(true);
  bewertungAuswahlFaerben();
}
$("#suche").addEventListener("input", () => { clearTimeout(suchZeitgeber); suchZeitgeber = setTimeout(suchen, 250); });
$("#suche").addEventListener("focus", () => { if ($("#suche").value.trim().length >= 2) sucheZeigen(true); });
$("#suche").addEventListener("keydown", (e) => {
  if (e.key === "Escape") { $("#suche").value = ""; sucheZeigen(false); }
});
$("#treffer").addEventListener("click", (ereignis) => {
  const zeile = ereignis.target.closest(".zeile");
  if (!zeile) { if (insLeere(ereignis)) auswahlAufheben(); return; }
  const li = zeile.parentElement;
  const { art, platte, pfad } = li.dataset;
  if (nachKontextKlick(ereignis)) return;
  if (mehrfachKlick(ereignis, li, trefferZeilen())) return;
  if (ereignis.target.matches("input[type=checkbox]")) {
    ankreuzen([{ platte, pfad, art }], ereignis.target.checked);
    ankerSetzen(li, ereignis.target.checked);
    return;
  }
  if (auswahlKlick(li)) return;
  sucheZeigen(false);                                          // Suchtext bleibt; Fokus ins Feld zeigt die Treffer wieder
  zeigeImBaum(platte, pfad);
});

function waehlen(li) {
  document.querySelectorAll(".zeile.gewaehlt").forEach((z) => z.classList.remove("gewaehlt"));
  li.querySelector(":scope > .zeile").classList.add("gewaehlt");
  const { platte, pfad, art } = li.dataset;
  zustand.aktiv = { platte, pfad, art };
  inspektorZeichnen();
}

// Ein Element in den Bäumen zeigen: Ordner von oben nach unten aufklappen, dann auswählen
async function zeigeImBaum(platte, pfad) {
  sucheZeigen(false);
  let li = [...$("#baum").children].find((x) => x.dataset.platte === platte);
  if (!li) return;
  const teile = pfad ? pfad.split("/") : [];
  for (let i = 0; i < teile.length; i++) {
    const ziel = teile.slice(0, i + 1).join("/");
    await aufklappen(li, true);
    const ul = li.querySelector(":scope > ul");
    let kind = [...ul.children].find((x) => x.dataset.pfad === ziel);
    // Datei liegt hinter „weitere laden“: nachladen, bis sie da ist
    while (!kind && ul.querySelector(":scope > .mehr-zeile")) {
      await kinderLaden(li, ul.querySelectorAll(":scope > li[data-art=datei]").length);
      kind = [...ul.children].find((x) => x.dataset.pfad === ziel);
    }
    if (!kind) return;
    li = kind;
  }
  waehlen(li);
  li.querySelector(":scope > .zeile").scrollIntoView({ block: "center", behavior: "smooth" });
}

// ---------- Inspektor ----------
async function inspektorZeichnen() {
  const ins = $("#inspektor");
  const { platte, pfad, art } = zustand.aktiv;
  ins.innerHTML = `<div class="leer-hinweis">Lade …</div>`;
  try {
    zustand.angaben = await holen(art === "datei" ? "/api/datei" : "/api/ordner", { platte, pfad });
  } catch (e) {
    ins.innerHTML = `<div class="inhalt fehler">Fehler: ${esc(e.message)}</div>`;
    return;
  }
  ins.innerHTML = art === "datei" ? dateiHtml(zustand.angaben) : ordnerHtml(zustand.angaben);
  ins.scrollTop = 0;
  editorZeichnen();
  vergleichLaden();
  quelleLaden();
}

function pfadleiste(platte, pfad) {
  const teile = pfad ? pfad.split("/") : [];
  const glieder = [`<a href="#" ${zeigeAttr(platte, "")}>${esc(platte)}</a>`];
  teile.forEach((t, i) => glieder.push(i === teile.length - 1 ? `<b>${esc(t)}</b>`
    : `<a href="#" ${zeigeAttr(platte, teile.slice(0, i + 1).join("/"))}>${esc(t)}</a>`));
  return `<div class="pfadleiste">${glieder.join(" / ")}</div>`;
}
function kopfHtml(d) {
  return `${pfadleiste(d.platte, d.pfad)}
    <div class="titel-zeile"><h2 class="titel-gross">${esc(d.name)}</h2>
      <button type="button" id="zeigen-knopf" class="knopf-leise" disabled>${icon("folder-search")} ${{ datei: "Datei", ordner: "Ordner", platte: "Datenträger" }[zustand.aktiv.art] || "Datei"} zeigen</button></div>
    <div id="zeigen-hinweis" class="leise zeigen-hinweis">Prüfe, ob der Datenträger angeschlossen ist …</div>
    ${d.etikett ? `<div class="etikett">${esc(d.etikett)}</div>` : ""}`;
}

// Original im Dateimanager markieren: nur wenn die Platte angeschlossen und schreibgeschützt eingehängt ist (server.py, quelle)
async function quelleLaden() {
  const { platte, pfad } = zustand.aktiv;
  let q;
  try { q = await holen("/api/quelle", { platte, pfad }); }
  catch (e) { q = { grund: e.message }; }
  if (zustand.aktiv.platte !== platte || zustand.aktiv.pfad !== pfad || !$("#zeigen-knopf")) return;
  $("#zeigen-knopf").disabled = !!q.grund;
  $("#zeigen-knopf").title = q.grund || `auf dem Datenträger im ${systemwort("dateimanager")} zeigen (nichts wird geöffnet)`;
  $("#zeigen-hinweis").textContent = q.grund || "";
}
async function originalZeigen() {
  const { platte, pfad } = zustand.aktiv;
  try { await senden("/api/zeigen", { platte, pfad }); }
  catch (e) { $("#zeigen-hinweis").textContent = e.message; quelleLaden(); }
}
const kennzahl = (bez, wert, klein = false) =>
  `<div class="kennzahl"><div class="bez">${bez}</div><div class="wert${klein ? " klein" : ""}">${wert}</div></div>`;
const zeitraumText = (z) => !z ? "–" : z[0] === z[1] ? z[0] : `${z[0]} – ${z[1]}`;

function uebersichtHtml(z) {
  const dub = z.stark_exakt + z.stark_variante + z.stark_beinahe;
  return `<h3>Übersicht</h3>
    <div class="balkenblock">
      <span>Archivfähigkeit</span>${balken(z, AMPEL, true)}<span class="zahlen">${teileText(z, AMPEL)}</span>
      <span>Bewertung</span>${balken(z, BEWERTUNG, true)}
      <span class="zahlen">${teileText(z, BEWERTUNG)}${z.vorbehalt ? ` · davon mit Vorbehalt ${zahl(z.vorbehalt)}` : ""}</span>
      <span>Dubletten</span>${balken(z, DUBLETTEN, true)}
      <span class="zahlen">${zahl(dub)} von ${zahl(z.dateien)} Dateien (${prozent(dub, z.dateien)}) · exakt ${zahl(z.exakt)} · Variante ${zahl(z.variante)} · beinahe ${zahl(z.beinahe)}</span>
      <span>In Anton</span><span class="zahlen" style="margin:0">${zahl(z.in_anton)} Dateien schon in Anton (gleiche MD5)</span>
    </div>`;
}

function ordnerHtml(d) {
  const z = d.zaehler;
  const liste = (paare) => `<table class="angaben">${paare.map(([k, n]) => `<tr><th>${esc(k)}</th><td>${zahl(n)}</td></tr>`).join("")}</table>`;
  return `<div class="inhalt">
    ${kopfHtml(d)}
    <div class="kennzahlen">
      ${kennzahl("Dateien", zahl(z.dateien))}
      ${kennzahl("Größe", bytes(z.bytes))}
      ${kennzahl("Exakte Dubletten", prozent(z.exakt, z.dateien))}
      ${kennzahl("Unterordner", zahl(d.unterordner))}
      ${kennzahl("Zeitraum", esc(zeitraumText(d.zeitraum)), true)}
    </div>
    <div class="abschnitt" id="uebersicht">${uebersichtHtml(z)}</div>
    <details class="abschnitt galerie" ontoggle="if (this.open && !this.dataset.geladen) galerieLaden(this)">
      <summary><span class="galerie-kopf">${icon("images")}<span class="galerie-titel">Vorschaubilder</span></span></summary><div class="kacheln"></div>
    </details>
    <div class="abschnitt">
      <div class="abschnitt-kopf"><h3>Liegt auch anderswo</h3>
        <div class="umschalter" role="tablist">
          <button type="button" data-vergleich="ordner">Gleiche Ordner · ${d.gleiche_ordner.length}</button>
          <button type="button" data-vergleich="dateien">Dateien anderswo</button>
        </div>
      </div>
      <div id="vergleich" data-gleiche='${esc(JSON.stringify(d.gleiche_ordner))}'></div>
    </div>
    ${d.formate.length || d.kameras.length ? `<div class="abschnitt"><div class="zweispaltig">
      <div><h3 class="leise" style="margin-bottom:6px">Formate</h3>${liste(d.formate)}</div>
      <div><h3 class="leise" style="margin-bottom:6px">Kameras</h3>${d.kameras.length ? liste(d.kameras) : '<span class="leise">keine</span>'}</div>
    </div></div>` : ""}
  </div>`;
}

const FELDER = {
  datei: [["format", "Format"], ["formatversion", "Version"], ["puid", "PRONOM"], ["mime", "MIME"],
          ["sha256", "SHA-256"], ["md5", "MD5"], ["sf_warnung", "Siegfried-Warnung"], ["sf_fehler", "Siegfried-Fehler"],
          ["sf_quelle", "Format übernommen von"]],
  metadaten: [["datum", "Bestes Datum"], ["datum_quelle", "Datum aus"], ["aufnahme", "Aufnahme"], ["erstellt", "Erstellt"],
              ["hersteller", "Hersteller"], ["kamera", "Kamera"], ["breite", "Breite"], ["hoehe", "Höhe"],
              ["farbprofil", "Farbprofil"], ["seiten", "Seiten"], ["dauer", "Dauer (s)"], ["urheber", "Urheber"],
              ["copyright", "Copyright"], ["titel", "Titel"], ["beschreibung", "Beschreibung"], ["schlagworte", "Schlagworte"],
              ["software", "Software"], ["gps_breite", "GPS Breite"], ["gps_laenge", "GPS Länge"], ["warnung", "ExifTool-Warnung"]],
  archiv: [["ampel", "Ampel"], ["grund", "Grund"], ["massnahme", "Maßnahme"], ["nara_risiko", "NARA-Risiko"],
           ["nara_massnahme", "NARA-Maßnahme"], ["nara_plan", "NARA-Plan"]],
  anton_abgleich: [["status", "Status"], ["signatur", "Signatur"], ["titel", "Titel"], ["link", "Link"], ["stand", "Stand"]],
};
function tabelle(teil, felder) {
  const zeilen = felder.filter(([k]) => teil[k] !== undefined).map(([k, n]) => {
    const wert = k === "link" ? String(teil[k]).split(" | ").map((l) => `<a href="${esc(l)}" target="_blank" rel="noopener">${esc(l)}</a>`).join("<br>")
               : esc(teil[k]);
    return `<tr><th>${n}</th><td class="${["sha256", "md5"].includes(k) ? "mono" : ""}">${wert}</td></tr>`;
  }).join("");
  return zeilen ? `<table class="angaben">${zeilen}</table>` : `<div class="leise">keine Angaben</div>`;
}

function dateiHtml(d) {
  const geaendert = d.schnellscan.mtime ? new Date(d.schnellscan.mtime * 1000).toLocaleDateString("de-CH") : "–";
  return `<div class="inhalt">
    ${kopfHtml(d)}
    ${bild(d.thumb, d.name, "vorschau-gross")}
    <div class="kennzahlen">
      ${kennzahl("Größe", bytes(d.groesse))}
      ${kennzahl("Bestes Datum", esc(d.metadaten.datum || "–"), true)}
      ${kennzahl("Geändert", esc(geaendert), true)}
      ${kennzahl("Ampel · Bewertung · Dublette", punkte(d), true)}
      ${d.bildtyp ? kennzahl(personenArt(d), `${personMarke(d)} ${esc(personenAnzahl(d))}`, true) : ""}
    </div>
    <div class="abschnitt"><h3>Dieselbe Datei anderswo</h3>
      <label class="schalter"><input type="checkbox" id="alle-arten" ${zustand.alleArten ? "checked" : ""}> auch Varianten und beinahe gleiche</label>
      <div id="vergleich"></div>
    </div>
    <div class="abschnitt"><h3>Archivfähigkeit</h3>${tabelle(d.archiv, FELDER.archiv)}</div>
    <div class="abschnitt"><h3>Anton</h3>${tabelle(d.anton_abgleich, FELDER.anton_abgleich)}</div>
    <div class="abschnitt"><h3>Format</h3>${tabelle(d.datei, FELDER.datei)}</div>
    <div class="abschnitt"><h3>Metadaten</h3>${tabelle(d.metadaten, FELDER.metadaten)}</div>
  </div>`;
}

async function galerieLaden(details, offset = 0) {
  details.dataset.geladen = "1";
  const { platte, pfad } = zustand.aktiv;
  const nurPersonen = details.querySelector(".nur-personen")?.checked;
  const d = await holen("/api/galerie", { platte, pfad, offset, personen: nurPersonen ? 1 : 0 });
  const kacheln = details.querySelector(".kacheln");
  details.querySelector(".mehr-galerie")?.remove();
  if (!offset) {
    details.querySelector(".galerie-titel").textContent = `Vorschaubilder · ${zahl(d.gesamt)} ${nurPersonen ? "mit Personen oder Porträts" : "verschiedene"}`;
    kacheln.innerHTML = "";
    if (!details.querySelector(".galerie-knoepfe")) {
      // Anzeige-Option nur, wo Personen erkannt sind (F5); gilt für diesen Ordner, bis ein anderer gewählt wird
      kacheln.insertAdjacentHTML("beforebegin", `<div class="galerie-knoepfe">
        <span class="leise">Klick auf ein Bild wählt es aus, Umschalt+Klick alle bis dorthin; ↗ zeigt es im Baum.</span>
        ${d.mit_personen ? `<label class="schalter" title="Fotos, auf deren Vorschaubild automatisch Personen oder ein Porträt erkannt wurden">
          <input type="checkbox" class="nur-personen"> nur Fotos mit Personen (${zahl(d.mit_personen)})</label>` : ""}
        <button type="button" class="knopf-leise" data-galerie="an">Alle gezeigten auswählen</button>
        <button type="button" class="knopf-leise" data-galerie="aus">Alle gezeigten abwählen</button></div>`);
      const schalter = details.querySelector(".nur-personen");
      if (schalter) schalter.onchange = () => galerieLaden(details);
    }
  }
  kacheln.insertAdjacentHTML("beforeend", d.bilder.map((b) => {
    const an = zustand.auswahl.has(schluessel(b.platte, b.pfad));
    return `<div class="kachel${an ? " angekreuzt" : ""}" data-platte="${esc(b.platte)}" data-pfad="${esc(b.pfad)}" title="${esc(b.pfad)}">
       ${kreuz(b.platte, b.pfad)}<button type="button" class="zum-baum" title="im Baum zeigen" ${zeigeAttr(b.platte, b.pfad)}>↗</button>
       <div class="kachel-urteil">${urteilMarke(b.urteil)}</div>${personMarke(b)}
       ${bild(b.thumb, b.name)}<div class="unter">${esc(b.name)}</div></div>`;
  }).join(""));
  if (d.offset < d.gesamt) {
    kacheln.insertAdjacentHTML("afterend", `<button type="button" class="mehr-galerie knopf-leise">weitere ${zahl(Math.min(48, d.gesamt - d.offset))} laden</button>`);
    details.querySelector(".mehr-galerie").onclick = () => galerieLaden(details, d.offset);
  }
}

// Vergleich: gleiche Ordner oder Dateien anderswo (Ordner), Kopien (Datei)
async function vergleichLaden() {
  const ziel = $("#vergleich");
  if (!ziel) return;
  const { platte, pfad, art } = zustand.aktiv;
  document.querySelectorAll("[data-vergleich]").forEach((b) => b.classList.toggle("an", b.dataset.vergleich === zustand.vergleich));
  if (art !== "datei" && zustand.vergleich === "ordner") {
    const gleiche = JSON.parse(ziel.dataset.gleiche || "[]");
    ziel.innerHTML = gleiche.length ? `<div class="leise">Mit allen Unterordnern gleich: dieselben Dateien in derselben Struktur.</div>
      <ul class="liste">${gleiche.map((g) => `<li><div><div class="titelzeile">${esc(g.platte)} / ${esc(g.pfad)}</div>
        <div class="unter">${zahl(g.zaehler.dateien)} Dateien · ${bytes(g.zaehler.bytes)}${g.seit ? " · gleich als Teil von " + esc(g.seit) : ""}</div></div>
        <button type="button" ${zeigeAttr(g.platte, g.pfad)}>Zeigen</button></li>`).join("")}</ul>`
      : `<div class="leise">Kein gleicher Ordner gefunden.</div>`;
    return;
  }
  const schalter = art === "datei" ? "" : `<label class="schalter"><input type="checkbox" id="alle-arten" ${zustand.alleArten ? "checked" : ""}> auch Varianten und beinahe gleiche</label>`;
  ziel.innerHTML = schalter + `<div class="leise">Lade …</div>`;
  const arten = zustand.alleArten ? "exakt,variante,beinahe" : "exakt";
  let d;
  try { d = await holen("/api/anderswo", { platte, pfad, arten }); }
  catch (e) { ziel.innerHTML = schalter + `<div class="fehler">${esc(e.message)}</div>`; return; }
  if (zustand.aktiv.pfad !== pfad || zustand.aktiv.platte !== platte) return;   // inzwischen anderes gewählt

  if (d.art === "datei") {
    ziel.innerHTML = d.kopien.length ? `<ul class="liste">${d.kopien.map((k) => `<li class="mit-bild">
        ${bild(k.thumb, k.name)}
        <div><div class="titelzeile">${esc(k.platte)} / ${esc(k.pfad)}${k.leit ? '<span class="leitmarke" title="Leitdatei der Gruppe (H2)">Leitdatei</span>' : ""}</div>
          <div class="unter">${ART_NAME[k.art]} · ${bytes(k.groesse)} ${punkte(k)}</div>
          <div class="kopie-entscheidung">${[["übernehmen", "Übernehmen"], ["kassieren", "Kassieren"]].map(([w, t]) =>
            `<button type="button" class="knopf-leise" data-kopie-entscheiden="${w}" data-platte="${esc(k.platte)}" data-pfad="${esc(k.pfad)}"
              title="nur diese Kopie ${esc(URTEIL[w][2])}">${t}</button>`).join("")}</div></div>
        <button type="button" ${zeigeAttr(k.platte, k.pfad)}>Zeigen</button></li>`).join("")}</ul>`
      : `<div class="leise" style="margin-top:8px">Keine ${zustand.alleArten ? "Kopien oder ähnlichen Dateien" : "exakten Kopien"} gefunden.</div>`;
    return;
  }
  const artText = (a) => a.map((x) => ({ exakt: "exakt", variante: "Variante", beinahe: "beinahe" }[x])).join(", ");
  ziel.innerHTML = schalter + `<div class="hinweis"><b>${zahl(d.mit_kopie)} von ${zahl(d.dateien)} Dateien</b> (${prozent(d.mit_kopie, d.dateien)})
      liegen auch außerhalb dieses Ordners, in ${zahl(d.orte_gesamt)} Ordnern${d.orte_gesamt > d.orte.length ? ` (die ${d.orte.length} größten gezeigt)` : ""}.</div>
    <ul class="liste">${d.orte.map((o) => `<li><div><div class="titelzeile">${esc(o.platte)} / ${esc(o.pfad || "(oberste Ebene)")}</div>
      <div class="unter">${zahl(o.anzahl)} Dateien von hier · ${artText(o.arten)} · dort ${zahl(o.dort)} Dateien</div></div>
      <button type="button" ${zeigeAttr(o.platte, o.pfad)}>Zeigen</button></li>`).join("")}</ul>`;
}

// Sprünge in den Baum aus Inspektor und Editor
for (const spalte of ["#inspektor", "#editor"]) {
  $(spalte).addEventListener("click", (e) => {
    const knopf = e.target.closest("[data-vergleich]");
    if (knopf) { zustand.vergleich = knopf.dataset.vergleich; vergleichLaden(); return; }
    const kopie = e.target.closest("[data-kopie-entscheiden]");       // eine Kopie anderswo direkt bewerten
    if (kopie) { entscheiden(kopie.dataset.kopieEntscheiden, false, null, [{ platte: kopie.dataset.platte, pfad: kopie.dataset.pfad }]); return; }
    if (e.target.closest("#zeigen-knopf")) { originalZeigen(); return; }
    const zeige = e.target.closest("[data-zeige]");
    if (zeige) {
      e.preventDefault();
      const [p, ...rest] = zeige.dataset.zeige.split("|");
      zeigeImBaum(p, rest.join("|"));
      return;
    }
    if (e.target.id === "auswahl-leeren") { ankreuzen([...zustand.auswahl.values()], false); return; }
    // Galerie: Bild anklicken kreuzt an, Knöpfe kreuzen alle gezeigten an oder ab
    const sammel = e.target.closest("[data-galerie]");
    if (sammel) {
      const alle = [...document.querySelectorAll("#inspektor .kachel")].map((k) => ({ ...k.dataset, art: "datei" }));
      ankreuzen(alle, sammel.dataset.galerie === "an");
      return;
    }
    const kachel = e.target.closest(".kachel");
    if (kachel) {
      if (nachKontextKlick(e) || mehrfachKlick(e, kachel, galerieKacheln())) return;
      const kaestchen = kachel.querySelector("input");
      const an = e.target === kaestchen ? kaestchen.checked : !kaestchen.checked;
      ankreuzen([eintragVon(kachel)], an);
      ankerSetzen(kachel, an);
    }
  });
}
$("#inspektor").addEventListener("change", (e) => {
  if (e.target.id === "alle-arten") { zustand.alleArten = e.target.checked; vergleichLaden(); }
});

// ---------- Editor ----------
function zusammenfassung(d, art) {
  if (!d) return "";
  if (art === "datei") return [bytes(d.groesse), d.metadaten?.datum, d.datei?.format].filter(Boolean).map(esc).join(" · ");
  const formate = d.formate.slice(0, 3).map(([f]) => f).join(", ");
  return [`${zahl(d.zaehler.dateien)} Dateien`, bytes(d.zaehler.bytes), d.zeitraum ? zeitraumText(d.zeitraum) : "", formate]
    .filter(Boolean).map(esc).join(" · ");
}

// Ziele des Editors: die angekreuzten Elemente, sonst das gewählte
const editorZiele = () => zustand.auswahl.size ? [...zustand.auswahl.values()] : zustand.aktiv ? [zustand.aktiv] : [];
const zieleSchluessel = (ziele) => ziele.map((z) => schluessel(z.platte, z.pfad)).sort().join("\n");
let editorLauf = 0;

async function editorZeichnen() {
  const ziele = editorZiele();
  if (!ziele.length) return;
  const lauf = ++editorLauf;
  let d;
  try { d = await senden("/api/editor", { ziele: ziele.map(({ platte, pfad }) => ({ platte, pfad })) }); }
  catch (e) { $("#editor").innerHTML = `<div class="inhalt fehler">Fehler: ${esc(e.message)}</div>`; return; }
  if (lauf !== editorLauf) return;                                  // inzwischen etwas anderes gewählt

  const a = zustand.aktiv;
  const mehrere = zustand.auswahl.size > 0;
  const einzel = !mehrere || ziele.length === 1 ? d.ziele[0] : null;
  const e = d.einzeln;                                              // nur bei einem Ziel: eigene, Ausnahmen, Verlauf
  const entschieden = d.ziele.filter((z) => z.urteil).length;
  const gesperrt = entschieden > 0 && zustand.entsperrt !== zieleSchluessel(ziele);
  // „Wie übergeordneter Ordner“ nur, wenn hier selbst entschieden ist und darüber etwas anderes gilt
  const wieDarueber = einzel?.urteil?.eigen && einzel.darueber ? einzel.darueber : null;
  const ausnahmenDa = e ? e.ausnahmen_gesamt + e.aus_regeln > 0 : ziele.some((z) => z.art !== "datei");
  const bez = { platte: "Datenträger", ordner: "Ordner", datei: "Datei" };
  let wer = "";
  try { wer = localStorage.getItem("bewertung-wer") || ""; } catch { /* privates Fenster */ }

  // Kopf: einzelnes Element oder Auswahl
  let kopf;
  if (!mehrere && a) {
    kopf = `<h2 class="titel-gross">${esc(a.pfad.split("/").pop() || a.platte)}</h2>
      <div class="pfad mono leise">${esc(a.platte)} / ${esc(a.pfad || "")}</div>
      <div class="zusammenfassung">${zusammenfassung(zustand.angaben, a.art)}</div>`;
  } else {
    const zaehl = {};
    for (const z of d.ziele) { const k = z.urteil ? URTEIL[z.urteil.entscheidung][2] : "offen"; zaehl[k] = (zaehl[k] || 0) + 1; }
    kopf = `<h2 class="titel-gross">${ziele.length} ausgewählt${ziele.length === 1 ? "es Element" : "e Elemente"}</h2>
      <div class="zusammenfassung">${Object.entries(zaehl).map(([k, n]) => `${n} ${k}`).join(" · ")}</div>
      ${a && !zustand.auswahl.has(schluessel(a.platte, a.pfad)) ? `<div class="hinweis">Die Entscheidung gilt für die ausgewählten Elemente, nicht für das geöffnete „${esc(a.pfad.split("/").pop() || a.platte)}“.</div>` : ""}`;
  }

  // Stand der Entscheidung
  let stand = "";
  if (einzel) {
    const u = einzel.urteil;
    stand = !u ? `<div class="stand">${e?.eigen?.entscheidung === "offen"
        ? "Hier bewusst auf unentschieden gesetzt; die Entscheidung darüber gilt hier nicht." : "Noch nicht bewertet."}</div>`
      : u.automatisch ? `<div class="stand">${urteilMarke(u)} automatisch (globale Einstellung: ${esc(u.automatisch)})</div>`
      : `<div class="stand">${urteilMarke(u)} ${u.eigen ? "hier entschieden"
          : `geerbt von <a href="#" ${zeigeAttr(einzel.platte, u.quelle)}>${esc(u.quelle || einzel.platte + " (ganzer Datenträger)")}</a>`}</div>`;
  }
  const aktuell = einzel?.urteil?.eigen ? einzel.urteil : null;
  const knopf = (wert, text) => `<button type="button" data-entscheiden="${wert}" class="${aktuell?.entscheidung === wert ? "gesetzt " + URTEIL[wert][0] : ""}" ${gesperrt ? "disabled" : ""}>${text}</button>`;

  $("#editor").innerHTML = `<div class="inhalt">
    ${kopf}
    <section class="eblock">
      <div class="ueberschrift">Entscheidung</div>
      ${stand}
      <div class="entscheidung">${knopf("übernehmen", "Übernehmen")}${knopf("kassieren", "Kassieren")}${knopf("zurückstellen", "Zurückstellen")}</div>
      ${!gesperrt && (entschieden || ausnahmenDa) ? `<div class="ruecknahme">
        <button type="button" data-entscheiden="offen">Zurücksetzen: wieder unentschieden</button>
        ${wieDarueber ? `<button type="button" class="knopf-leise" data-entscheiden="aufheben">Wie übergeordneter Ordner (${esc(URTEIL[wieDarueber.entscheidung][2])})</button>` : ""}
        ${ausnahmenDa ? `<label class="schalter"><input type="checkbox" id="mit-ausnahmen"> auch ${e ? e.ausnahmen_gesamt + e.aus_regeln + " " : ""}Ausnahmen darunter zurücksetzen (auch aus Regeln)</label>` : ""}
      </div>` : ""}
      ${gesperrt ? `<div class="sperre">${SCHLOSS}<span>${einzel ? "Gesperrt" : `${entschieden} von ${ziele.length} haben schon eine Entscheidung`}. Für eine neue Entscheidung oder zum Zurücksetzen zuerst entsperren.</span>
          <button type="button" id="entsperren">Entsperren</button></div>` : ""}
      <label class="vorbehalt"><input type="checkbox" id="vorbehalt" ${aktuell?.vorbehalt ? "checked" : ""} ${gesperrt ? "disabled" : ""}>
        <span><b>Vorbehalt: Nachbewertung nach Inhaltsanalyse</b><br>
        <span class="leise">Nur bei „Übernehmen“. Z. B. Eventfotos: Bilder mit Menschen übernehmen, Stimmungsbilder nach der Inhaltsanalyse gezielt kassieren.</span></span></label>
      <div class="felder">
        <label>Begründung (optional)<input type="text" id="begruendung" value="${esc(e?.eigen?.begruendung || "")}" ${gesperrt ? "disabled" : ""}></label>
        <label>Bearbeitet von<input type="text" id="wer" value="${esc(wer)}" placeholder="Name"></label>
        ${e ? `<label>Erschließungshinweis (optional, wird beim Verlassen des Feldes gespeichert)
          <textarea id="hinweis" rows="3" data-platte="${esc(einzel.platte)}" data-pfad="${esc(einzel.pfad)}" placeholder="Ideen, wie und wo dieser Bestand später im Archiv erschlossen werden soll">${esc(e.hinweis.eigen?.hinweis || "")}</textarea>
          <span class="leise" id="hinweis-stand">${e.hinweis.eigen ? `zuletzt ${esc(e.hinweis.eigen.zeit.replace("T", " ").slice(0, 16))}${e.hinweis.eigen.wer ? ` von ${esc(e.hinweis.eigen.wer)}` : ""}` : ""}</span></label>`
        : `<div class="leise">Einen Erschließungshinweis gibt es nur für ein einzelnes Element.</div>`}
      </div>
      ${e && e.hinweis.darueber.length ? `<div class="ueberschrift">Erschließungshinweise darüber</div>
        <ul class="liste">${e.hinweis.darueber.map((h) => `<li><div><div class="titelzeile">${esc(h.pfad || einzel.platte + " (ganzer Datenträger)")}</div>
          <div class="unter">${esc(h.hinweis)}</div></div>
          <button type="button" ${zeigeAttr(einzel.platte, h.pfad)}>Zeigen</button></li>`).join("")}</ul>` : ""}
    </section>

    ${ziele.some((z) => z.art !== "datei") ? `<div id="regeln"><section class="eblock"><div class="ueberschrift">Regeln für diese Auswahl</div><div class="leise">Lade …</div></section></div>` : ""}

    ${e && e.ausnahmen_gesamt ? `<section class="eblock"><div class="ueberschrift">Ausnahmen darunter · ${e.ausnahmen_gesamt}</div>
      <ul class="liste">${e.ausnahmen.map((x) => `<li><div><div class="titelzeile">${esc(x.pfad.slice(einzel?.pfad ? einzel.pfad.length + 1 : 0) || x.pfad)}</div>
        <div class="unter">${urteilMarke({ ...x, eigen: true })}${x.begruendung ? esc(x.begruendung) : ""}</div></div>
        <button type="button" ${zeigeAttr(x.platte, x.pfad)}>Zeigen</button></li>`).join("")}</ul></section>` : ""}

    ${mehrere ? `<section class="eblock"><div class="ueberschrift">Angekreuzt · ${ziele.length}</div>
      <ul class="liste">${d.ziele.map((x, i) => `<li><div><div class="titelzeile">${esc(x.platte)} / ${esc(x.pfad || "(ganzer Datenträger)")}</div>
        <div class="unter">${bez[ziele[i].art] || ""} ${urteilMarke(x.urteil)}</div></div>
        <button type="button" ${zeigeAttr(x.platte, x.pfad)}>Zeigen</button></li>`).join("")}</ul>
      <button type="button" id="auswahl-leeren" class="knopf-leise" style="margin-top:10px">Auswahl aufheben</button></section>` : ""}

    ${e && e.verlauf.length ? `<section class="eblock"><div class="ueberschrift">Verlauf</div>
      <ul class="verlauf">${e.verlauf.map((v) => `<li><span class="leise">${esc(v.zeit.replace("T", " ").slice(0, 16))}</span>
        ${esc(v.objekt.split(":").slice(1).join(":").slice(einzel?.pfad ? einzel.pfad.length + 1 : 0) || "hier")}: ${esc(v.neu)}</li>`).join("")}</ul></section>` : ""}

    ${mehrere ? "" : `<div class="leise tipp">Tipp: Mit den Kästchen in Baum, Suche und Galerie lassen sich mehrere Elemente über alle Datenträger hinweg auf einmal bewerten. Ist etwas ausgewählt, wählt ein Klick weitere aus oder ab, Umschalt+Klick einen ganzen Bereich; Esc oder ein Klick ins Leere hebt die Auswahl auf, nach einer Entscheidung geschieht das von selbst.</div>`}
  </div>`;
  if ($("#regeln")) regelnLaden(lauf);
}

// ---------- Regeln: Werkzeuge, die passende Dateien der Auswahl einzeln kassieren oder zurückstellen ----------
async function regelnLaden(lauf) {
  const ziele = editorZiele().map(({ platte, pfad }) => ({ platte, pfad }));
  let d;
  try { d = await senden("/api/regeln", { ziele, grenze: zustand.grenze, jedes: zustand.jedes }); }
  catch (e) { $("#regeln").innerHTML = `<div class="fehler">${esc(e.message)}</div>`; return; }
  if (lauf !== editorLauf || !$("#regeln")) return;
  const menge = (x) => `${zahl(x.dateien)} Dateien · ${bytes(x.bytes)}${x.schon ? ` <span class="leise">(${zahl(x.schon)} schon einzeln entschieden, bleiben)</span>` : ""}`;
  const regeln = d.regeln.map((r) => r.regel === "stichprobe" ? `<div class="regel">
      <div><b>Stichprobe: jedes <input type="number" id="jedes" class="zahlfeld" min="2" max="1000" value="${d.jedes}">. Element übernehmen</b>
        <div class="leise">${esc(r.erklaerung)}</div>
        <div class="menge">übernimmt ${zahl(r.behalten)} · kassiert ${zahl(r.dateien)} Dateien (${bytes(r.bytes)})${r.schon ? ` <span class="leise">(${zahl(r.schon)} schon entschieden, bleiben außen vor)</span>` : ""}</div></div>
      <button type="button" data-regel="stichprobe" ${r.dateien ? "" : "disabled"}>Anwenden</button></div>`
    : `<div class="regel">
      <div><b>${esc(r.titel)}</b>
        ${r.regel === "klein" ? `<label class="grenze">unter <input type="number" id="grenze" class="zahlfeld" min="16" max="4000" step="10" value="${d.grenze}"> px</label>` : ""}
        <div class="leise">${esc(r.erklaerung)}</div><div class="menge">${menge(r)}</div></div>
      <button type="button" data-regel="${r.regel}" ${r.dateien ? "" : "disabled"}>Kassieren</button></div>`).join("");
  // Archivfähigkeit je Endung wie die Ampel im Baum: schlechteste der Dateien, Zahlen im Tooltip
  const ampelPunkt = (f) => `<i class="punkt ${{ "grün": "a-gruen", "gelb": "a-gelb", "rot": "a-rot" }[f.ampel] || "a-ohne"}"
    title="Archivfähigkeit: ${esc(teileText(f.ampeln, AMPEL))}"></i>`;
  const formate = d.formate.length > 1 || d.formate.some((f) => f.dateien) ? `<details class="formate"${zustand.formateOffen ? " open" : ""}>
      <summary><b>Formate</b> <span class="leise">· ${d.formate.length} Endungen</span></summary>
      <table class="angaben formattabelle"><tr><th></th><th>Endung</th><th>Dateien</th><th>Größe</th></tr>
      ${d.formate.map((f) => `<tr title="${esc(f.format)}"><td><input type="checkbox" class="format-wahl" value="${esc(f.endung)}" ${f.dateien ? "" : "disabled"}></td>
        <td>${esc(f.endung)} ${ampelPunkt(f)}</td><td>${zahl(f.gesamt)}${f.schon ? ` <span class="leise">(${zahl(f.schon)} entschieden)</span>` : ""}</td><td>${bytes(f.bytes)}</td></tr>`).join("")}</table>
      <div class="knopfzeile"><button type="button" data-formate="übernehmen">Gewählte übernehmen</button>
        <button type="button" data-formate="kassieren">Gewählte kassieren</button>
        <button type="button" data-formate="zurückstellen">Gewählte zurückstellen</button></div></details>` : "";
  const angewandt = d.angewandt.length ? `<section class="eblock"><div class="ueberschrift">Angewandte Regeln</div>
    <ul class="liste">${d.angewandt.map((a) => `<li><div><div>${esc(a.begruendung.replace(/^Regel: /, ""))}</div>
      <div class="unter">${zahl(a.dateien)} Dateien ${URTEIL[a.entscheidung][2]}</div></div>
      <button type="button" data-zuruecknehmen="${esc(a.begruendung)}">Zurücknehmen</button></li>`).join("")}</ul></section>` : "";
  $("#regeln").innerHTML = `<section class="eblock"><div class="ueberschrift">Regeln für diese Auswahl</div>
    <div class="leise" style="margin-bottom:8px">Eine Regel entscheidet die passenden Dateien einzeln; Dateien mit eigener Entscheidung und automatisch kassierte bleiben unberührt. ${zahl(d.dateien)} Dateien in der Auswahl.</div>
    ${regeln || `<div class="leise">Keine Regel trifft hier etwas.</div>`}${formate}</section>${angewandt}`;
}

async function regelAnwenden(daten, bestaetigt = false) {
  const ziele = editorZiele().map(({ platte, pfad }) => ({ platte, pfad }));
  const wer = $("#wer")?.value.trim() || "";
  let r;
  try { r = await senden("/api/regel_anwenden", { ziele, wer, bestaetigt, grenze: zustand.grenze, jedes: zustand.jedes, ...daten }); }
  catch (e) { meldung(e.message, "Die Regel wurde nicht angewendet"); return; }
  if (r.warnung) {
    const w = r.warnung;
    if (await rueckfrage("Schutzregel Dubletten: trotzdem anwenden?", `Von ${zahl(w.inhalte)} Inhalten wäre danach keine `
      + "einzige exakte Kopie mehr übernommen (und sie liegen nicht schon in Anton). Bei Varianten ist das oft gewollt, "
      + `weil die bessere Fassung bleibt. Beispiele:\n\n${w.beispiele.join("\n")}`, "Trotzdem anwenden"))
      return regelAnwenden(daten, true);
    return;
  }
  await nachEntscheidung();
}

$("#editor").addEventListener("click", async (e) => {
  const regel = e.target.closest("[data-regel]");
  if (regel && !regel.disabled) { regelAnwenden({ regel: regel.dataset.regel }); return; }
  const formate = e.target.closest("[data-formate]");
  if (formate) {
    const endungen = [...document.querySelectorAll(".format-wahl:checked")].map((c) => c.value);
    if (!endungen.length) { meldung("Zuerst Endungen auswählen."); return; }
    zustand.formateOffen = true;
    regelAnwenden({ regel: "formate", endungen, entscheidung: formate.dataset.formate });
    return;
  }
  const zurueck = e.target.closest("[data-zuruecknehmen]");
  if (zurueck) {
    const ziele = editorZiele().map(({ platte, pfad }) => ({ platte, pfad }));
    try { await senden("/api/regel_zuruecknehmen", { ziele, begruendung: zurueck.dataset.zuruecknehmen }); }
    catch (err) { meldung(err.message, "Fehler"); return; }
    await nachEntscheidung();
  }
});
$("#editor").addEventListener("change", (e) => {
  if (e.target.id === "hinweis") hinweisSpeichern(e.target.dataset.platte, e.target.dataset.pfad, e.target.value);
  if (e.target.id === "grenze") { zustand.grenze = Number(e.target.value) || 300; regelnLaden(editorLauf); }
  if (e.target.id === "jedes") { zustand.jedes = Math.max(2, Number(e.target.value) || 10); regelnLaden(editorLauf); }
});

// Erschließungshinweis: nur für ein einzelnes Element, unabhängig von der Entscheidung und der Sperre
async function hinweisSpeichern(platte, pfad, hinweis) {
  const wer = $("#wer")?.value.trim() || "";
  let r;
  try { r = await senden("/api/hinweis", { platte, pfad, hinweis, wer }); }
  catch (e) { meldung(e.message, "Der Erschließungshinweis wurde nicht gespeichert"); return; }
  if (r.geaendert && $("#hinweis-stand")) $("#hinweis-stand").textContent = hinweis.trim() ? "gespeichert" : "entfernt";
}

// fassungen: null = Server prüft die Fassungen und fragt bei Bedarf; sonst die Wahl aus dem Dialog
// fest: Ziele außerhalb des Editors (Knöpfe je Fundort in „Dieselbe Datei anderswo“), ohne Vorbehalt und Begründung
async function entscheiden(wert, bestaetigt = false, fassungen = null, fest = null) {
  const ziele = fest || editorZiele().map(({ platte, pfad }) => ({ platte, pfad }));
  const wer = $("#wer")?.value.trim() || "";
  try { localStorage.setItem("bewertung-wer", wer); } catch { /* privates Fenster */ }
  let r;
  try {
    r = await senden("/api/entscheiden", {
      ziele, entscheidung: wert === "aufheben" ? null : wert, vorbehalt: !fest && wert === "übernehmen" && $("#vorbehalt")?.checked,
      begruendung: fest ? "" : $("#begruendung")?.value || "", wer, bestaetigt, mit_ausnahmen: !fest && !!$("#mit-ausnahmen")?.checked, fassungen });
  } catch (e) { meldung(e.message, "Die Entscheidung wurde nicht gespeichert"); return; }
  if (r.fassungen) {
    const wahl = await fassungenFragen(r.fassungen);
    if (wahl) return entscheiden(wert, bestaetigt, wahl, fest);
    return;
  }
  if (r.warnung) {
    const w = r.warnung;
    const erklaerung = `Von ${zahl(w.inhalte)} Inhalten wäre danach keine einzige Kopie mehr übernommen `
      + `(und sie liegen nicht schon in Anton). Beispiele:\n\n${w.beispiele.join("\n")}`;
    if (await rueckfrage("Schutzregel Dubletten: trotzdem alle kassieren?", erklaerung, "Trotzdem kassieren"))
      return entscheiden(wert, true, fassungen, fest);
    return;
  }
  zustand.entsperrt = null;
  if (!fest) auswahlAufheben();       // entschieden: die nächste Auswahl beginnt leer (Feedback 05.11.2026)
  await nachEntscheidung();
}

// ---------- Prüfung der Fassungen (plan.md, 30.10.2026) ----------
// Formatvarianten: beste = Leitdatei aus H2 (fehlt sie: Ampel, Pixel, Größe). Bitgleiche Kopien: nur „mehrfach
// übernommen“. Ohne Wahl im Dialog wird nichts gespeichert. Antwort: die Wahl für den Server oder null (abgebrochen).
function fassungZeile(f, vorne = "") {
  const mass = f.breite && f.hoehe ? ` · ${zahl(f.breite)} × ${zahl(f.hoehe)} px` : "";
  return `<li class="mit-bild">${bild(f.thumb, f.name)}
    <div><div class="titelzeile">${vorne}${esc(f.platte)} / ${esc(f.pfad)}</div>
      <div class="unter">${esc(f.format || "Format unbekannt")}${mass} · ${bytes(f.groesse)} · ${esc(urteilText(f.urteil))}${
        f.anton === "in Anton" ? " · liegt schon in Anton" : ""}</div></div></li>`;
}

function fassungHinweisHtml(fall, name) {
  if (!fall.hinweise) return "";
  const feld = fall.hinweise === 1
    ? `<label class="dialog-feld">Erschließungshinweis an der übernommenen Fassung (änderbar, leer = keiner)
         <textarea id="hinweis-${name}">${esc(fall.hinweis)}</textarea></label>`
    : `<label class="schalter"><input type="checkbox" id="hinweis-${name}" checked> Erschließungshinweise an
         ${zahl(fall.hinweise)} übernommenen Fassungen setzen</label><div class="leise">Zum Beispiel: ${esc(fall.hinweis)}</div>`;
  return `<div class="fassung-hinweis" data-hinweis-fuer="${name}" hidden>
    <div class="leise" style="margin-bottom:6px">Die kassierte Datei liegt in einem anderen Ordner. Ihr Fundort geht sonst
    für die Erschließung verloren.</div>${feld}</div>`;
}

function fassungenFragen(f) {
  const dlg = $("#fassung-dialog");
  const mehr = (fall) => fall.anzahl > fall.paare.length ? `<div class="leise">… und ${zahl(fall.anzahl - fall.paare.length)} weitere</div>` : "";
  const teile = [];
  const b = f.besser, w = f.weitere, k = f.beste_kassiert;
  if (b) {
    const einzeln = b.anzahl === 1, alleInAnton = b.in_anton === b.anzahl;
    teile.push(`<section class="fassung-fall">
      <p class="dialog-text">${einzeln ? "Für diese Datei gibt es eine bessere Formatvariante:"
        : `Für ${zahl(b.dateien)} der gewählten Dateien gibt es eine bessere Formatvariante:`}</p>
      <ul class="liste">${b.paare.map((p) => (einzeln ? "" : fassungZeile(p.datei, "gewählt: ")) + fassungZeile(p.andere, einzeln ? "" : "besser: ")).join("")}</ul>${mehr(b)}
      ${b.in_anton ? `<div class="hinweis">${alleInAnton ? "Die bessere Fassung liegt schon in Anton."
        : `Bei ${zahl(b.in_anton)} liegt die bessere Fassung schon in Anton; dort bleibt es bei der gewählten.`}</div>` : ""}
      <div class="wahl">
        <label><input type="radio" name="f-besser" value="diese" checked> Trotzdem ${einzeln ? "diese" : "die gewählten"} übernehmen</label>
        ${alleInAnton ? "" : `<label><input type="radio" name="f-besser" value="bessere"> Stattdessen ${einzeln ? "die bessere" : "jeweils die bessere"} übernehmen;
          ${einzeln ? "diese wird" : "die gewählten werden"} kassiert</label>
        <label><input type="radio" name="f-besser" value="beide"> Beide übernehmen</label>`}
      </div>${fassungHinweisHtml(b, "besser")}</section>`);
  }
  if (w) {
    teile.push(`<section class="fassung-fall">
      <p class="dialog-text">${w.dateien === 1 ? "Das ist die beste Formatvariante." : `${zahl(w.dateien)} der gewählten Dateien sind die beste Formatvariante.`}
        ${zahl(w.anzahl)} ${w.anzahl === 1 ? "schlechtere ist" : "schlechtere sind"} noch offen oder übernommen:</p>
      <ul class="liste">${w.paare.map((p) => fassungZeile(p.andere)).join("")}</ul>${mehr(w)}
      <div class="wahl">
        <label><input type="radio" name="f-weitere" value="nur_diese" checked> Nur ${w.dateien === 1 ? "diese" : "die gewählten"} übernehmen, die anderen bleiben, wie sie sind</label>
        ${w.eigen < w.anzahl ? `<label><input type="radio" name="f-weitere" value="kassieren"> Die anderen kassieren${w.eigen
          ? ` (${zahl(w.anzahl - w.eigen)}; ${zahl(w.eigen)} mit eigener Entscheidung bleiben)` : ""}</label>`
          : `<div class="leise">Alle haben eine eigene Entscheidung und bleiben, wie sie sind.</div>`}
      </div>${fassungHinweisHtml(w, "weitere")}</section>`);
  }
  if (k) {
    teile.push(`<section class="fassung-fall">
      <p class="dialog-text">Sie kassieren die beste Formatvariante. ${zahl(k.anzahl)} schlechtere ${k.anzahl === 1 ? "bleibt" : "bleiben"} übernommen:</p>
      <ul class="liste">${k.paare.map((p) => fassungZeile(p.andere)).join("")}</ul>${mehr(k)}</section>`);
  }
  // Bitgleiche Kopien sind gleich gut: Es geht nur darum, einen Inhalt nicht mehrfach zu übernehmen
  const m = f.mehrfach;
  if (m) {
    teile.push(`<section class="fassung-fall">
      <p class="dialog-text">${zahl(m.inhalte)} ${m.inhalte === 1 ? "Inhalt wäre" : "Inhalte wären"} danach mehrfach übernommen.
        Bitgleiche Kopien sind gleich gut, Anton nimmt je MD5 aber nur eine Datei an. Schon übernommen ${m.anzahl === 1 ? "ist" : "sind"}:</p>
      <ul class="liste">${m.paare.map((p) => fassungZeile(p.andere)).join("")}</ul>${mehr(m)}
      <div class="wahl">
        <label><input type="radio" name="f-mehrfach" value="trotzdem" checked> Trotzdem mehrfach übernehmen</label>
        <label><input type="radio" name="f-mehrfach" value="eine"> Je Inhalt nur ${m.inhalte === 1 && m.anzahl === 1 ? "die hier gewählte" : "eine"} übernehmen
          (die hier gewählte); ${zahl(m.anzahl)} ${m.anzahl === 1 ? "andere Kopie wird" : "andere Kopien werden"} kassiert${m.eigen
            ? `, davon ${zahl(m.eigen)} mit eigener Entscheidung` : ""}</label>
      </div>${fassungHinweisHtml(m, "mehrfach")}</section>`);
  }
  $("#fassung-titel").textContent = b ? "Es gibt eine bessere Formatvariante" : m ? "Schon übernommen"
    : w ? "Weitere Formatvarianten vorhanden" : "Beste Formatvariante kassieren?";
  $("#fassung-inhalt").innerHTML = teile.join("");
  $("#fassung-ok").textContent = b || w || m ? "Speichern" : "Trotzdem kassieren";
  // Hinweisfeld nur zeigen, wenn die Wahl eine Fassung anderswo kassiert
  const sichtbar = () => {
    const gewaehlt = (name) => $("#fassung-inhalt").querySelector(`[name=f-${name}]:checked`)?.value;
    const zeigt = { besser: "bessere", weitere: "kassieren", mehrfach: "eine" };
    for (const el of $("#fassung-inhalt").querySelectorAll("[data-hinweis-fuer]")) {
      el.hidden = gewaehlt(el.dataset.hinweisFuer) !== zeigt[el.dataset.hinweisFuer];
    }
  };
  $("#fassung-inhalt").onchange = sichtbar;
  sichtbar();
  return new Promise((fertig) => {
    let wahl = null;
    const hinweis = (name) => {
      const el = $(`#hinweis-${name}`);
      return !el ? true : el.type === "checkbox" ? el.checked : el.value;
    };
    $("#fassung-form").onsubmit = (e) => {
      e.preventDefault();
      wahl = { besser: $("#fassung-inhalt").querySelector("[name=f-besser]:checked")?.value || "diese",
               weitere: $("#fassung-inhalt").querySelector("[name=f-weitere]:checked")?.value || "nur_diese",
               mehrfach: $("#fassung-inhalt").querySelector("[name=f-mehrfach]:checked")?.value || "trotzdem",
               hinweis_besser: hinweis("besser"), hinweis_weitere: hinweis("weitere"), hinweis_mehrfach: hinweis("mehrfach"),
               beste_kassiert: k ? "trotzdem" : undefined };
      dlg.close();
    };
    $("#fassung-abbrechen").onclick = () => dlg.close();
    dlg.addEventListener("close", () => fertig(wahl), { once: true });
    dlg.showModal();
  });
}

async function nachEntscheidung() {
  await Promise.all([kopfLaden(), zeilenAktualisieren()]);
  const a = zustand.aktiv;
  if (a?.art === "datei") return inspektorZeichnen();               // zeichnet auch den Editor
  if (a) {
    zustand.angaben = await holen("/api/ordner", { platte: a.platte, pfad: a.pfad });
    const block = $("#uebersicht");
    if (block) block.innerHTML = uebersichtHtml(zustand.angaben.zaehler);
  }
  editorZeichnen();
}

$("#editor").addEventListener("click", (e) => {
  const knopf = e.target.closest("[data-entscheiden]");
  if (knopf && !knopf.disabled) { entscheiden(knopf.dataset.entscheiden); return; }
  if (e.target.closest("#entsperren")) { zustand.entsperrt = zieleSchluessel(editorZiele()); editorZeichnen(); }
});

// Arbeitsplatte wieder angeschlossen? Beim Zurückkehren ins Fenster nachfragen; dann die Ansicht mit Bildern neu zeichnen
window.addEventListener("focus", async () => {
  if (zustand.thumbsOk !== false || !zustand.platten.length) return;
  await kopfLaden().catch(() => {});
  if (zustand.thumbsOk) bilderNachholen();
});

// ---------- Start ----------
async function standLaden() {
  await kopfLaden();
  baumZeichnen();
}

async function kopfLaden() {
  const d = await holen("/api/stand");
  zustand.platten = d.platten;
  const summe = (k) => d.platten.reduce((s, p) => s + p.zaehler[k], 0);
  const dateien = summe("dateien"), offen = summe("offen");
  const ids = d.platten.map((p) => p.id);
  $("#projekt-zeile").textContent = `${ids.length > 1 ? ids[0] + "–" + ids.at(-1) : ids[0] || "kein Datenträger"} · `
    + `${zahl(dateien)} Dateien · ${bytes(summe("bytes"))}`;
  zustand.thumbsOk = d.thumbs_ok;
  zustand.bewertung = { bewertet: dateien - offen, dateien };      // Ring bzw. Balken in der Kopfleiste (erfassung.js)
  if (typeof modulKopf === "function") modulKopf();
  $("#db-zustand").innerHTML = `<span class="pille ${d.thumbs_ok ? "gut" : "schlecht"}">${d.thumbs_ok ? "Vorschaubilder verbunden"
    : "Vorschaubilder nicht erreichbar (Datenträger für Vorschaubilder anschließen)"}</span>${d.ohne_leitdatei ? ` <span class="pille schlecht"
    title="Die Prüfung der Formatvarianten nimmt solange Ampel, Pixel und Größe statt der Leitdatei">Leitdateien fehlen in
    ${zahl(d.ohne_leitdatei)} Dublettengruppen: in Registrierung/Analyse „Alles Offene fortsetzen“</span>` : ""} · Datenbank geladen ${esc(d.geladen_am)}`;
  $("#db-zustand").title = d.db;
  zustand.einstellungen = d.einstellungen;
  einstellungenZeichnen();
}

// Globale Einstellungen: Häkchen nur vormerken, erst „Anwenden“ schreibt in die Datenbank
function einstellungenZeichnen() {
  $("#einstellungen-liste").innerHTML = zustand.einstellungen.map((x) => `<label class="einstellung">
      <input type="checkbox" data-einstellung="${x.schluessel}" ${x.an ? "checked" : ""}>
      <span>${esc(x.text)}<br><span class="leise">${zahl(x.dateien)} Dateien</span></span></label>`).join("");
  einstellungenGeaendert();
}
function einstellungenAenderungen() {
  return zustand.einstellungen.filter((x) => $(`#einstellungen [data-einstellung="${x.schluessel}"]`).checked !== x.an);
}
function einstellungenGeaendert() {
  const geaendert = einstellungenAenderungen();
  for (const x of zustand.einstellungen) {
    $(`#einstellungen [data-einstellung="${x.schluessel}"]`).closest(".einstellung").classList.toggle("geaendert", geaendert.includes(x));
  }
  $("#einstellungen-anwenden").disabled = $("#einstellungen-verwerfen").disabled = !geaendert.length;
}
$("#einstellungen-knopf").onclick = () => {
  const zu = $("#einstellungen").hidden;
  einstellungenZeichnen();                                        // nicht angewandte Häkchen verfallen
  $("#einstellungen").hidden = !zu;
};
document.addEventListener("click", (e) => {
  if (!e.target.closest("#einstellungen, #einstellungen-knopf")) $("#einstellungen").hidden = true;
});
$("#einstellungen").addEventListener("change", (e) => { if (e.target.dataset.einstellung) einstellungenGeaendert(); });
$("#einstellungen-verwerfen").onclick = () => einstellungenZeichnen();
$("#einstellungen-anwenden").onclick = async () => {
  const geaendert = einstellungenAenderungen();
  if (!geaendert.length) return;
  const zeilen = geaendert.map((x) => `${x.an ? "Nicht mehr kassieren" : "Automatisch kassieren"}: ${x.text} (${zahl(x.dateien)} Dateien)`);
  if (!(await rueckfrage("Einstellungen anwenden?", `${zeilen.join("\n")}\n\nFür nicht mehr kassierte Dateien gilt wieder `
    + "die eigene oder die vom Ordner geerbte Entscheidung, sonst sind sie offen.", "Anwenden"))) return;
  $("#einstellungen-anwenden").disabled = true;
  try {
    for (const x of geaendert) await senden("/api/einstellung", { schluessel: x.schluessel, an: !x.an });
  } catch (err) { meldung(err.message, "Fehler"); }
  await nachEntscheidung();                                       // lädt den Kopf und zeichnet die Einstellungen neu
};
$("#neu-laden").onclick = () => standLaden();
$("#systemdateien").onchange = () => standLaden();
// Gestartet wird erst, wenn ein Projekt offen ist (projekt.js)
// Über Balduin: Klick auf das Zeichen in der Kopfleiste zeigt Urheber und Lizenz (LIZENZ-ZUSATZ.md, § 7 b)
$("#ueber-knopf").onclick = () => $("#ueber-dialog").showModal();

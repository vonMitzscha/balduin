// Projekte: Startbildschirm (zuletzt geöffnet, anderes Projekt öffnen, neues Projekt) und Assistent „Neues Projekt“
// (docs/plan.md, Entscheidungen 30.10.2026). Nutzt die Hilfen aus app.js ($, esc, zahl, bytes, holen, senden) und
// startet Bewertung (standLaden) und Registrierung/Analyse (erfassungStarten), sobald ein Projekt offen ist.
"use strict";

const prj = {
  daten: null,                  // Antwort von /api/projekte: offen, zuletzt, ablageort
  loeschen: null,               // Pfad des Projekts, dessen Löschen gerade bestätigt wird
  schritt: 0,                   // Schritt im Assistenten
  angaben: null,                // Angaben des Assistenten (wie projekt.json)
  ziel: null,                   // Antwort von /api/zielordner
  platten: null,                // mögliche Arbeitsplatten (/api/arbeitsplatten)
};

const datum = (iso) => (iso ? new Date(iso).toLocaleString("de-CH", { dateStyle: "medium", timeStyle: "short" }) : "");

// ---------- Start ----------
async function projektStart() {
  try {
    prj.daten = await holen("/api/projekte");
  } catch (e) {
    $("#start").hidden = false;
    $("#start").innerHTML = `<div class="start-karte"><div class="fehler">${esc(e.message)}</div></div>`;
    return;
  }
  if (!prj.daten.offen) return startZeigen();
  $("#projekt-name").textContent = prj.daten.offen.name;
  document.title = `${prj.daten.offen.name} · Balduin`;
  document.body.classList.remove("ohne-projekt");
  standLaden().catch((e) => { $("#baum").innerHTML = `<li class="fehler" style="padding:20px">Fehler: ${esc(e.message)}</li>`; });
  erfassungStarten();
}

function startZeigen() {
  const offen = prj.daten.offen;
  document.body.classList.toggle("ohne-projekt", !offen);
  $("#bewertung").hidden = $("#erfassung").hidden = $("#vorlauf").hidden = $("#erschliessung").hidden = $("#export").hidden = true;
  $("#dashboard").hidden = true;
  $("#start").hidden = false;
  // je Eintrag: öffnen; daneben aus der Liste entfernen und (nicht das geöffnete) in den Papierkorb legen
  const liste = prj.daten.zuletzt.map((z) => `<li class="projekt-zeile"><button type="button" class="projekt-eintrag${offen?.ordner === z.pfad ? " offen" : ""}"
      data-oeffnen="${esc(z.pfad)}" ${z.vorhanden ? "" : "disabled"}>
      ${icon(z.vorhanden ? "folder-open" : "folder-x")}<b>${esc(z.name)}</b>
      <span class="leise">${offen?.ordner === z.pfad ? "geöffnet" : z.vorhanden ? esc(datum(z.geoeffnet_am)) : "nicht gefunden"}</span>
      <span class="pfad mono">${esc(z.pfad)}</span></button>
      <span class="projekt-knoepfe">
        ${z.vorhanden ? "" : `<button type="button" class="knopf-mini" data-verlegen="${esc(z.pfad)}" title="Neuen Ort wählen … (Projektordner verschoben oder umbenannt)">${icon("folder-search")}</button>`}
        <button type="button" class="knopf-mini" data-vergessen="${esc(z.pfad)}" title="Aus der Liste entfernen (der Ordner bleibt)">${icon("x")}</button>
        ${z.vorhanden && offen?.ordner !== z.pfad ? `<button type="button" class="knopf-mini" data-loeschen="${esc(z.pfad)}" data-name="${esc(z.name)}" title="Projekt löschen (Ordner in den Papierkorb) …">${icon("trash")}</button>` : ""}
      </span>
      ${prj.loeschen === z.pfad ? `<form class="projekt-loeschen" data-loeschen-form="${esc(z.pfad)}">
        <div>Den Ordner <span class="mono">${esc(z.pfad)}</span> mit Datenbank, Berichten und Regeln in den Papierkorb legen?
          Wiederherstellen geht aus dem Papierkorb. Zum Bestätigen den Namen <b>${esc(z.name)}</b> eintippen.</div>
        <div class="knopfzeile"><input name="name" autocomplete="off" spellcheck="false" aria-label="Name zum Bestätigen">
          <button type="button" data-loeschen-ab>Abbrechen</button><button type="submit" class="gefahr">In den Papierkorb</button></div></form>` : ""}</li>`).join("");
  $("#start").innerHTML = `<div class="start-karte">
    <h1>${offen ? "Projekt wechseln" : "Willkommen"}</h1>
    <p class="erklaerung">Ein Projekt ist ein Ordner mit eigener Datenbank, eigenen Regeltabellen und eigenen Berichten,
      zum Beispiel für einen Bestand oder eine Abgabe. Die Datenträger selbst werden nur gelesen.</p>
    ${liste ? `<div class="ueberschrift">Zuletzt geöffnet</div><ul class="projektliste">${liste}</ul>` : ""}
    <div id="start-meldung" class="leise"></div>
    <div class="knopfzeile start-knoepfe">
      ${offen ? `<button type="button" id="start-zurueck" class="knopf-leise">${icon("arrow-left")} Zurück zu ${esc(offen.name)}</button>` : ""}
      <span class="platzhalter"></span>
      <button type="button" id="start-anderes">${icon("folder-search")} Anderes Projekt öffnen …</button>
      <button type="button" id="start-neu" class="haupt">${icon("folder-plus")} Neues Projekt</button>
    </div></div>`;
}

async function projektOeffnen(pfad) {
  const meldung = $("#start-meldung");
  document.querySelectorAll("#start button").forEach((b) => (b.disabled = true));
  meldung.className = "leise";
  meldung.textContent = "Projekt wird geöffnet; bei großen Projekten dauert das einige Sekunden …";
  try {
    await senden("/api/projekt_oeffnen", { pfad });
    location.reload();                                     // frischer Zustand für Bewertung und Analyse
  } catch (e) {
    meldung.className = "fehler";
    meldung.textContent = e.message;
    document.querySelectorAll("#start button:not(.projekt-eintrag[disabled])").forEach((b) => (b.disabled = false));
  }
}

$("#start").addEventListener("click", async (e) => {
  const weg = e.target.closest("[data-vergessen]");
  if (weg) {
    try { await senden("/api/projekt_vergessen", { pfad: weg.dataset.vergessen }); prj.daten = await holen("/api/projekte"); startZeigen(); }
    catch (err) { $("#start-meldung").className = "fehler"; $("#start-meldung").textContent = err.message; }
    return;
  }
  const verlegen = e.target.closest("[data-verlegen]");
  if (verlegen) {                                          // nicht gefundenes Projekt: neuen Ort wählen
    try {
      const alt = verlegen.dataset.verlegen;
      const start = alt.replace(/[\\/][^\\/]*$/, "");
      const r = await senden("/api/ordner_waehlen", { zweck: "projekt", start });
      if (r.abgebrochen) return;
      const neu = await senden("/api/projekt_verlegen", { alt, pfad: r.pfad });
      prj.daten = await holen("/api/projekte");
      startZeigen();
      $("#start-meldung").className = "leise";
      $("#start-meldung").textContent = `„${neu.name}“ liegt jetzt unter ${neu.pfad}.`;
    } catch (err) { $("#start-meldung").className = "fehler"; $("#start-meldung").textContent = err.message; }
    return;
  }
  const lo = e.target.closest("[data-loeschen]");
  if (lo) { prj.loeschen = lo.dataset.loeschen; startZeigen(); return document.querySelector("[data-loeschen-form] input")?.focus(); }
  if (e.target.closest("[data-loeschen-ab]")) { prj.loeschen = null; return startZeigen(); }
  const eintrag = e.target.closest("[data-oeffnen]");
  if (eintrag) {
    if (prj.daten.offen?.ordner === eintrag.dataset.oeffnen) return startVerlassen();
    return projektOeffnen(eintrag.dataset.oeffnen);
  }
  const id = e.target.closest("button")?.id;
  if (id === "start-zurueck") return startVerlassen();
  if (id === "start-neu") return assistentStarten();
  if (id === "start-anderes") {
    try {
      const r = await senden("/api/ordner_waehlen", { zweck: "projekt" });
      if (!r.abgebrochen) projektOeffnen(r.pfad);
    } catch (err) { $("#start-meldung").className = "fehler"; $("#start-meldung").textContent = err.message; }
    return;
  }
  assistentKlick(e);
});

$("#start").addEventListener("submit", async (e) => {
  const f = e.target.closest("[data-loeschen-form]");
  if (!f) return;
  e.preventDefault();
  try {
    await senden("/api/projekt_loeschen", { pfad: f.dataset.loeschenForm, name: f.elements.name.value });
    prj.loeschen = null;
    prj.daten = await holen("/api/projekte");
    startZeigen();
    $("#start-meldung").className = "leise";
    $("#start-meldung").textContent = "Projekt liegt im Papierkorb.";
  } catch (err) { $("#start-meldung").className = "fehler"; $("#start-meldung").textContent = err.message; }
});

function startVerlassen() {
  $("#start").hidden = true;
  ansichtZeigen(erf.ansicht);
}
$("#projekt-knopf").onclick = async () => {
  prj.daten = await holen("/api/projekte").catch(() => prj.daten);
  startZeigen();
};

// ---------- Assistent „Neues Projekt“ ----------
// Jeder Schritt: Titel, Erklärung, Felder (html), Prüfen beim Weitergehen (lesen gibt einen Fehlertext oder nichts zurück).
// Die Erklärung ist Text (wird maskiert); das Zahnrad steht darin als {zahnrad} und wird danach als Symbol eingesetzt.
const SCHRITTE_NEU = [
  { titel: "Name des Projekts", text: "Wie heißt der Bestand oder die Abgabe? Der Name wird auch zum Namen des Projektordners. "
      + "Das Kürzel steht vor den Nummern der Datenträger (HD01, HD02 …).",
    html: () => `<div class="felder">
      <label><span>Name${PFLICHT}</span><input id="a-name" value="${esc(prj.angaben.name)}" maxlength="80" autocomplete="off" placeholder="z. B. Nachlass Muster"></label>
      <label><span>Kürzel für die Kennungen der Datenträger${PFLICHT}</span>
        <input id="a-kennung" value="${esc(prj.angaben.kennung)}" maxlength="6" autocomplete="off" class="kurz">
        <span class="leise">1 bis 6 Buchstaben; der erste Datenträger heißt dann <b id="a-kennung-bsp"></b>.</span></label></div>`,
    nachher: () => kennungBeispiel(),
    lesen: () => {
      prj.angaben.name = $("#a-name").value.trim();
      prj.angaben.kennung = $("#a-kennung").value.trim().toUpperCase();
      if (!prj.angaben.name) return "Bitte einen Namen eingeben.";
      if (!/^[A-Za-z]{1,6}$/.test(prj.angaben.kennung)) return "Das Kürzel besteht aus 1 bis 6 Buchstaben.";
    } },
  { titel: "Speicherort", text: "Wo soll der Projektordner liegen? Vorgabe ist der Ordner „Projekte“ neben dem Programm. "
      + `Ein Projekt lässt sich später im ${systemwort("dateimanager")} als Ganzes verschieben; Balduin findet es über „Anderes Projekt öffnen“.`,
    html: () => `<div class="ablage">
      <div class="leise">Speicherort</div><div class="mono">${esc(prj.angaben.ablageort)}</div>
      <div class="knopfzeile"><button type="button" id="a-ablage-waehlen">${icon("folder-search")} Anderen Ort wählen …</button>
        ${prj.angaben.ablageort !== prj.daten.ablageort ? `<button type="button" id="a-ablage-vorgabe" class="knopf-leise">Vorgabe: Projekte</button>` : ""}</div>
      <div class="ueberschrift">Das Projekt wird angelegt in</div><div id="a-ziel" class="mono">…</div>
      <div id="a-ziel-info" class="leise"></div></div>`,
    vorher: () => zielPruefen(),
    lesen: () => (prj.ziel?.fehler || (!prj.ziel ? "Speicherort wird noch geprüft." : undefined)) },
  { titel: "Vorschaubilder", text: "Für jedes Bild, jedes Dokument und jeden Film entsteht ein kleines Vorschaubild, eines je Inhalt "
      + "(etwa 35 KB, 100 000 Bilder brauchen rund 3,5 GB). Sie liegen im Projektordner oder auf einem eigenen Datenträger "
      + "für Vorschaubilder, einem externen Datenträger ohne Quellbestand.",
    html: () => `${prj.ziel?.frei != null ? `<div class="speicher-info">${icon("hard-drive")} Am Speicherort des Projekts
          sind zurzeit <b>${bytes(prj.ziel.frei)}</b> frei.</div>` : ""}
      ${wahl("a-ort", "projekt", prj.angaben.vorschaubilder.ort, "Im Projektordner",
             "Alles beisammen am Speicherort des Projekts.")}
      ${wahl("a-ort", "arbeitsplatte", prj.angaben.vorschaubilder.ort, "Auf einem Datenträger für Vorschaubilder",
             "Das Projekt bleibt klein; Vorschaubilder sind nur sichtbar, solange der Datenträger angeschlossen ist. "
             + "Er wird an seiner UUID wiedererkannt, auch unter anderem Namen.")}
      <div id="a-platten" ${prj.angaben.vorschaubilder.ort === "arbeitsplatte" ? "" : "hidden"}></div>`,
    nachher: () => { if (prj.angaben.vorschaubilder.ort === "arbeitsplatte") plattenLaden(); },
    lesen: () => {
      const v = prj.angaben.vorschaubilder;
      v.ort = document.querySelector('input[name="a-ort"]:checked').value;
      if (v.ort === "arbeitsplatte") {
        v.mountpunkt = document.querySelector('input[name="a-platte"]:checked')?.value || "";
        if (!v.mountpunkt) return "Bitte einen Datenträger für Vorschaubilder wählen oder die Vorschaubilder im Projektordner ablegen.";
      }
    } },
  { titel: "Film- und PDF-Vorschau", text: "Wie sollen Filme und mehrseitige PDFs in der Vorschau erscheinen? Die Bilder "
      + "werden gleichmäßig über die Dauer bzw. das Dokument verteilt genommen.",
    html: () => `
      <div class="wahl-titel">Filme</div>
      ${wahl("a-film", "webp", prj.angaben.film.art, "Bewegtes Vorschaubild (animiertes WebP)",
             `Zeigt den Ablauf des Films in einer Schleife, jedes Bild 0,7 Sekunden. Etwa 25 KB je Bild.
              <span class="film-zahl">Bilder <input type="number" id="a-film-bilder" min="2" max="60" value="${prj.angaben.film.bilder}"></span>`)}
      ${wahl("a-film", "raster", prj.angaben.film.art, "Vier Standbilder als Raster",
             "Ein JPEG mit 2 × 2 Bildern, etwa 35 KB; so wie im bisherigen Projekt.")}
      <div class="wahl-titel">PDFs</div>
      ${wahl("a-pdf", "seite", prj.angaben.pdf.art, "Erste Seite",
             "Ein JPEG der ersten Seite, etwa 35 KB; so wie im bisherigen Projekt.")}
      ${wahl("a-pdf", "webp", prj.angaben.pdf.art, "Mehrere Seiten (animiertes WebP)",
             `Seite 1 und weitere Seiten über das Dokument verteilt, in einer Schleife, jede 0,7 Sekunden. Etwa 25 KB je Seite;
              PDFs mit nur einer Seite bleiben ein JPEG.
              <span class="film-zahl">Seiten <input type="number" id="a-pdf-seiten" min="2" max="60" value="${prj.angaben.pdf.seiten}"></span>`)}
      ${wahl("a-pdf", "bereich", prj.angaben.pdf.art, "Bestimmte Seiten (animiertes WebP)",
             `Nur die Seiten eines festen Bereichs, etwa die ersten fünf; kürzere PDFs bis zur letzten Seite.
              <span class="film-zahl">Seiten <input id="a-pdf-bereich" class="kurz" value="${esc(prj.angaben.pdf.bereich)}" placeholder="1–5"></span>`)}`,
    lesen: () => {
      const f = prj.angaben.film, d = prj.angaben.pdf;
      f.art = document.querySelector('input[name="a-film"]:checked').value;
      f.bilder = Number($("#a-film-bilder").value);
      if (f.art === "webp" && !(Number.isInteger(f.bilder) && f.bilder >= 2 && f.bilder <= 60)) return "Bitte 2 bis 60 Bilder wählen.";
      d.art = document.querySelector('input[name="a-pdf"]:checked').value;
      d.seiten = Number($("#a-pdf-seiten").value);
      if (d.art === "webp" && !(Number.isInteger(d.seiten) && d.seiten >= 2 && d.seiten <= 60)) return "Bitte 2 bis 60 Seiten wählen.";
      d.bereich = $("#a-pdf-bereich").value.trim();
      if (d.art === "bereich") return seitenbereichFehler(d.bereich);
    } },
  { titel: "Virenscan", text: "Bevor Balduin Metadaten liest und Vorschaubilder erzeugt, kann es jeden Inhalt einmal auf Schadsoftware "
      + "prüfen. Funde werden nur markiert und nicht weiter geöffnet.",
    html: () => `
      ${wahl("a-viren", "an", prj.angaben.virenscan ? "an" : "aus", "Virenscan einschalten (empfohlen)",
             "Kostet Zeit (etwa 25 MB/s je Prüfung), gleiche Inhalte nur einmal.")}
      ${wahl("a-viren", "aus", prj.angaben.virenscan ? "an" : "aus", "Ohne Virenscan",
             "Nur, wenn der Bestand schon geprüft ist oder aus einer sicheren Quelle stammt.")}`,
    lesen: () => { prj.angaben.virenscan = document.querySelector('input[name="a-viren"]:checked').value === "an"; } },
  { titel: "Personen auf Fotos", text: "Auf Wunsch erkennt Balduin Personen und Gesichter auf den Vorschaubildern der Fotos "
      + "(lokal, ohne den Datenträger, keine Identität). Die Bewertung zeigt dann Porträts mit einem Gesicht und andere Fotos mit "
      + "Personen mit einer Gruppe; filtern lässt sich nach „nur Fotos mit Personen“.",
    html: () => `
      ${wahl("a-personen", "aus", prj.angaben.personen ? "an" : "aus", "Ohne Personenerkennung",
             `Vorgabe. Lässt sich später in den Einstellungen (${icon("settings")} an „Registrierung/Analyse“) einschalten.`)}
      ${wahl("a-personen", "an", prj.angaben.personen ? "an" : "aus", "Personen und Gesichter erkennen",
             "Eigener Schritt „Personen“ nach den Vorschaubildern, etwa 15–20 Minuten je 30 000 Fotos.")}`,
    lesen: () => { prj.angaben.personen = document.querySelector('input[name="a-personen"]:checked').value === "an"; } },
  { titel: "Anton", text: "Mit welchem Anton gleicht das Projekt ab? Über die Prüfsumme erkennt Balduin Dateien, "
      + `die dort schon liegen. Das API-Token für nicht öffentliche Bestände kommt später in die Einstellungen des Projekts ({zahnrad} vor „Registrierung/Analyse“).`,
    html: () => `<div class="felder">
      <label><span>Adresse des Anton-Servers${PFLICHT}</span><input id="a-anton" value="${esc(prj.angaben.anton.url)}" placeholder="https://…"
          autocomplete="off" spellcheck="false">
        <span class="leise">z. B. ${esc(ANTON_BEISPIEL)}</span></label></div>`,
    lesen: () => {
      prj.angaben.anton.url = $("#a-anton").value.trim().replace(/\/+$/, "");
      return antonUrlFehler(prj.angaben.anton.url);
    } },
  { titel: "Andere Projekte (freiwillig)", text: "Was in Anton liegt, erkennt jedes Projekt ohnehin. Wer zusätzlich wissen möchte, "
      + "ob ein Inhalt schon in einem anderen Projekt bewertet wurde (zum Beispiel dort kassiert), wählt dieses hier. "
      + "Die Auswahl wird gespeichert; der Abgleich selbst folgt in einer späteren Fassung.",
    html: () => {
      const andere = prj.daten.zuletzt.filter((z) => z.vorhanden);
      const gewaehlt = new Set(prj.angaben.referenzprojekte.map((r) => r.pfad));
      const alle = [...andere, ...prj.angaben.referenzprojekte.filter((r) => !andere.some((z) => z.pfad === r.pfad))];
      return `${alle.length ? alle.map((z) => `<label class="option"><input type="checkbox" data-referenz="${esc(z.pfad)}"
          data-name="${esc(z.name)}" ${gewaehlt.has(z.pfad) ? "checked" : ""}><span>${esc(z.name)}
          <span class="leise mono">${esc(z.pfad)}</span></span></label>`).join("")
        : `<div class="leise">Noch keine anderen Projekte bekannt.</div>`}
        <div class="knopfzeile"><button type="button" id="a-referenz-waehlen">${icon("folder-search")} Weiteres Projekt wählen …</button></div>`;
    },
    lesen: () => {
      prj.angaben.referenzprojekte = [...document.querySelectorAll("[data-referenz]:checked")]
        .map((c) => ({ pfad: c.dataset.referenz, name: c.dataset.name }));
    } },
  { titel: "Zusammenfassung", text: "Bitte prüfen. Bis auf den Ort der Vorschaubilder lässt sich alles später ändern "
      + `(Name, Projektkürzel und Anton in den Einstellungen des Projekts, {zahnrad} vor „Registrierung/Analyse“; das Übrige in den Einstellungen an „Registrierung/Analyse“).`,
    html: () => {
      const a = prj.angaben, v = a.vorschaubilder;
      const platte = (prj.platten || []).find((p) => p.mountpunkt === v.mountpunkt);
      const zeilen = [
        ["Name", esc(a.name)], ["Kennungen", `${esc(a.kennung)}01, ${esc(a.kennung)}02 …`],
        ["Projektordner", `<span class="mono">${esc(prj.ziel?.pfad)}</span>`],
        ["Vorschaubilder", v.ort === "projekt" ? "im Projektordner" : `auf dem Datenträger ${esc(platte?.name || v.mountpunkt)}`],
        ["Filmvorschau", a.film.art === "webp" ? `bewegt (animiertes WebP), ${a.film.bilder} Bilder` : "vier Standbilder als Raster"],
        ["PDF-Vorschau", a.pdf.art === "webp" ? `mehrere Seiten (animiertes WebP), bis zu ${a.pdf.seiten} Seiten`
          : a.pdf.art === "bereich" ? `Seiten ${esc(a.pdf.bereich)} (animiertes WebP)` : "erste Seite"],
        ["Virenscan", a.virenscan ? "ein" : "aus"],
        ["Personen auf Fotos", a.personen ? "erkennen" : "aus"],
        ["Anton", esc(a.anton.url)],
        ["Andere Projekte", a.referenzprojekte.map((r) => esc(r.name)).join(", ") || "keine"],
      ];
      return `<table class="angaben">${zeilen.map(([k, w]) => `<tr><th>${k}</th><td>${w}</td></tr>`).join("")}</table>`;
    } },
];

const ANTON_BEISPIEL = "https://archiv.example.org";   // nur Beispiel, keine Vorgabe (Entscheidung 06.11.2026)
// wie nur_lokal und einstellungen_pruefen in erfassung/basis.py: http nur für Namen, die auf diesem Rechner auflösen
function antonLokal(host) {
  const h = host.toLowerCase().replace(/\.$/, "");
  return ["127.0.0.1", "[::1]", "localhost"].includes(h) || [".localhost", ".test", ".ddev.site"].some((e) => h.endsWith(e));
}
function antonUrlFehler(url) {
  if (!url) return `Bitte die Adresse des Anton-Servers eingeben, z. B. ${ANTON_BEISPIEL}.`;
  let u;
  try { u = new URL(url); } catch { return `Bitte eine Adresse wie ${ANTON_BEISPIEL} eingeben.`; }
  if (!(u.protocol === "https:" || (u.protocol === "http:" && antonLokal(u.hostname))) || u.pathname !== "/" || u.search || u.username)
    return `Bitte eine Adresse wie ${ANTON_BEISPIEL} eingeben (ohne Pfad; http nur für eine Testinstanz auf diesem Rechner, `
      + "z. B. http://localhost oder http://…ddev.site).";
}

// wie seitenbereich() in erfassung/basis.py
function seitenbereichFehler(text) {
  const m = /^\s*(\d{1,4})\s*(?:[-–—]\s*(\d{1,4}))?\s*$/.exec(text || "");
  const von = m ? Number(m[1]) : 0, bis = m ? Number(m[2] || m[1]) : 0;
  if (!m || von < 1 || bis < von || bis - von >= 60) return "PDF-Seitenbereich bitte wie „1–5“ angeben (ab Seite 1, höchstens 60 Seiten).";
}
function wahl(name, wert, aktuell, titel, text) {
  return `<label class="wahl"><input type="radio" name="${name}" value="${wert}" ${wert === aktuell ? "checked" : ""}>
    <span><b>${titel}</b><span class="leise">${text}</span></span></label>`;
}

function kennungBeispiel() {
  const k = ($("#a-kennung").value.trim() || "HD").toUpperCase();
  $("#a-kennung-bsp").textContent = k + "01";
}

function assistentStarten() {
  prj.schritt = 0;
  prj.ziel = null;
  prj.platten = null;
  prj.angaben = { name: "", kennung: "HD", ablageort: prj.daten.ablageort, vorschaubilder: { ort: "projekt", mountpunkt: "" },
                  film: { art: "webp", bilder: 10 }, pdf: { art: "seite", seiten: 10, bereich: "1–5" },
                  virenscan: true, personen: false, referenzprojekte: [], anton: { url: "", testinstanz: false } };
  assistentZeichnen();
}

function assistentZeichnen() {
  const s = SCHRITTE_NEU[prj.schritt], letzter = prj.schritt === SCHRITTE_NEU.length - 1;
  const punkte = SCHRITTE_NEU.map((_, i) => `<i class="${i < prj.schritt ? "erledigt" : i === prj.schritt ? "aktiv" : ""}"></i>`).join("");
  $("#start").innerHTML = `<div class="start-karte assistent">
    <div class="assistent-kopf"><span class="leise">Neues Projekt · Schritt ${prj.schritt + 1} von ${SCHRITTE_NEU.length}</span>
      <span class="assistent-punkte" aria-hidden="true">${punkte}</span></div>
    <h1>${esc(s.titel)}</h1>
    <p class="erklaerung">${esc(s.text).replaceAll("{zahnrad}", icon("settings"))}</p>
    <div class="assistent-feld">${s.html()}</div>
    <div id="a-fehler" class="fehler" role="alert"></div>
    <div class="knopfzeile start-knoepfe">
      <button type="button" id="a-abbrechen" class="knopf-leise">Abbrechen</button>
      <span class="platzhalter"></span>
      ${prj.schritt ? `<button type="button" id="a-zurueck">Zurück</button>` : ""}
      <button type="button" id="a-weiter" class="haupt">${letzter ? "Projekt anlegen" : "Weiter"}</button>
    </div></div>`;
  s.nachher?.();
  if (s.vorher) s.vorher();
  $("#start .assistent-feld input:not([type=radio]):not([type=checkbox])")?.focus();
}

async function zielPruefen() {
  prj.ziel = null;
  try {
    prj.ziel = await holen("/api/zielordner", { ablageort: prj.angaben.ablageort, name: prj.angaben.name });
  } catch (e) { $("#a-ziel-info").innerHTML = `<span class="fehler">${esc(e.message)}</span>`; return; }
  if (!$("#a-ziel")) return;
  $("#a-ziel").textContent = prj.ziel.pfad;
  $("#a-ziel-info").innerHTML = prj.ziel.fehler ? `<span class="fehler">${esc(prj.ziel.fehler)}</span>`
    : `Frei auf diesem Datenträger: ${bytes(prj.ziel.frei)}`;
}

async function plattenLaden() {
  const box = $("#a-platten");
  box.hidden = false;
  box.innerHTML = `<div class="leise">Angeschlossene Datenträger werden gelesen …</div>`;
  try {
    prj.platten = await holen("/api/arbeitsplatten");
  } catch (e) { box.innerHTML = `<div class="fehler">${esc(e.message)}</div>`; return; }
  const gewaehlt = prj.angaben.vorschaubilder.mountpunkt;
  box.innerHTML = `<div class="ueberschrift">Datenträger für Vorschaubilder</div>`
    + (prj.platten.length ? prj.platten.map((p) => `<label class="option"><input type="radio" name="a-platte" value="${esc(p.mountpunkt)}"
        ${p.mountpunkt === gewaehlt || prj.platten.length === 1 ? "checked" : ""}><span>${icon("hard-drive")} <b>${esc(p.name)}</b>
        <span class="leise">${esc(p.dateisystem)}, ${bytes(p.frei)} frei von ${bytes(p.groesse)}${p.uuid ? "" : ", ohne UUID (wird am Namen erkannt)"}</span></span></label>`).join("")
      : `<div class="leise">Kein beschreibbarer externer Datenträger angeschlossen. Datenträger anschließen und aktualisieren.</div>`)
    + `<div class="knopfzeile"><button type="button" id="a-platten-neu" class="knopf-leise">Aktualisieren</button></div>`;
}

async function assistentKlick(e) {
  const id = e.target.closest("button")?.id;
  if (!id && e.target.name === "a-ort") {                 // Arbeitsplatte gewählt: Datenträger zeigen
    if (e.target.value === "arbeitsplatte") plattenLaden(); else $("#a-platten").hidden = true;
    return;
  }
  if (id === "a-abbrechen") return startZeigen();
  if (id === "a-platten-neu") return plattenLaden();
  if (id === "a-ablage-vorgabe") { prj.angaben.ablageort = prj.daten.ablageort; return assistentZeichnen(); }
  if (id === "a-ablage-waehlen" || id === "a-referenz-waehlen") {
    const referenz = id === "a-referenz-waehlen";
    try {
      const r = await senden("/api/ordner_waehlen", { zweck: referenz ? "projekt" : "ablageort",
                                                      start: referenz ? "" : prj.angaben.ablageort });
      if (r.abgebrochen) return;
      if (referenz) {
        SCHRITTE_NEU[prj.schritt].lesen();
        if (!prj.angaben.referenzprojekte.some((x) => x.pfad === r.pfad)) prj.angaben.referenzprojekte.push({ pfad: r.pfad, name: r.name });
      } else prj.angaben.ablageort = r.pfad;
      assistentZeichnen();
    } catch (err) { $("#a-fehler").textContent = err.message; }
    return;
  }
  if (id === "a-zurueck") {
    SCHRITTE_NEU[prj.schritt].lesen();                    // Eingaben behalten, auch unvollständige
    prj.schritt--;
    return assistentZeichnen();
  }
  if (id !== "a-weiter") return;
  const fehler = SCHRITTE_NEU[prj.schritt].lesen?.();
  if (fehler) { $("#a-fehler").textContent = fehler; return; }
  if (prj.schritt < SCHRITTE_NEU.length - 1) {
    prj.schritt++;
    return assistentZeichnen();
  }
  const knopf = $("#a-weiter");
  knopf.disabled = true;
  $("#a-fehler").className = "leise";
  $("#a-fehler").textContent = "Projekt wird angelegt …";
  try {
    await senden("/api/projekt_anlegen", prj.angaben);
    location.reload();
  } catch (err) {
    $("#a-fehler").className = "fehler";
    $("#a-fehler").textContent = err.message;
    knopf.disabled = false;
  }
}
$("#start").addEventListener("input", (e) => { if (e.target.id === "a-kennung") kennungBeispiel(); });
$("#start").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.target.matches(".assistent-feld input")) { e.preventDefault(); $("#a-weiter")?.click(); }
});

// ---------- Einstellungen: zwei Zahnräder, ein projekt.json (Entscheidung 05.11.2026) ----------
// „projekt“ (vorn in der Modulleiste, vor „Registrierung/Analyse“): was für alle Module gilt, Name, Kürzel, Anton-Instanz und Token.
// „analyse“ (am Knopf „Registrierung/Analyse“): nur, was die Analyse betrifft.
// Wie bei der Bewertung: Änderungen gelten erst nach „Anwenden“; Verwerfen oder Schließen lässt alles beim Alten.
// Token und „Verbindung prüfen“ wirken sofort, sie gehören nicht zu projekt.json.
const PE_NAMEN = { name: "Name", kennung: "Kürzel", film: "Filmvorschau", pdf: "PDF-Vorschau", virenscan: "Virenscan",
                   personen: "Personen auf Fotos",
                   referenzprojekte: "andere Projekte", anton: "Anton-Instanz" };
const TOKEN_TEXT = { "Schlüsselbund": `${systemwort("im_schluesselspeicher")} hinterlegt`, "Umgebungsvariable": "aus der Umgebungsvariablen ANTON_TOKEN",
                     "": "keiner hinterlegt: nur öffentliche Bestände" };
const EINST_TEILE = ["projekt", "analyse"];
const einst = (teil, was = "") => $(`#${teil}-einstellungen${was ? "-" + was : ""}`);

function projektEinstellungenFormular() {
  const o = prj.daten.offen, e = o.einstellungen;
  einst("projekt", "inhalt").innerHTML = `
    <div class="felder">
      <label><span>Name${PFLICHT}</span><input id="pe-name" value="${esc(e.name)}" maxlength="80" autocomplete="off"></label>
      <label><span>Projektkürzel${PFLICHT}</span><input id="pe-kennung" class="kurz" value="${esc(e.kennung)}" maxlength="6" autocomplete="off"
        ${o.platten ? "disabled" : ""}><span class="leise">${o.platten
          ? `nicht mehr änderbar: ${zahl(o.platten)} Datenträger sind schon registriert` : "1 bis 6 Buchstaben"}</span></label>
    </div>
    <div class="einst-gruppe"><span class="leise">Anton-Instanz (Abgleich, Erschließung, Export)</span>
      <div class="felder"><label>Adresse des Servers<input id="pe-anton-url" value="${esc(e.anton.url)}" autocomplete="off" spellcheck="false"></label></div>
      <label class="schalter" title="Übergaben an eine Testinstanz gelten als Probe und brauchen keine vollständige Freigabe. Lokale Instanzen (localhost, *.test, *.ddev.site) sind immer Testinstanzen.">
        <input type="checkbox" id="pe-anton-test" ${e.anton.testinstanz ? "checked" : ""}> Testinstanz (Übergaben gelten als Probe)</label>
      <div class="anton-token"><span class="leise">API-Token:</span> <span id="pe-token-stand">${esc(TOKEN_TEXT[o.anton_token] ?? o.anton_token)}</span></div>
      <div class="felder"><label>Neues API-Token (eines internen Kontos, z. B. editor)
        <input id="pe-token" type="password" autocomplete="off" spellcheck="false" placeholder="einfügen"></label></div>
      <div class="knopfzeile">
        <button type="button" class="knopf-leise" id="pe-token-speichern" disabled>API-Token speichern</button>
        ${o.anton_token === "Schlüsselbund" ? `<button type="button" class="knopf-leise" id="pe-token-entfernen">API-Token entfernen</button>` : ""}
        <button type="button" class="knopf-leise" id="pe-anton-pruefen">Verbindung prüfen</button></div>
      <div id="pe-anton-info" class="leise">Das API-Token gilt für den Server, nicht nur für dieses Projekt, und liegt
        ${systemwort("im_schluesselspeicher")}; Balduin zeigt und speichert es sonst nirgends. Speichern und Prüfen wirken sofort und
        nutzen die gespeicherte Adresse.</div></div>
    <div class="leise mono" style="margin-top:8px">${esc(o.ordner)}/projekt.json</div>`;
  einst("projekt", "fehler").textContent = "";
  einstellungenGeprueft("projekt");
}

function analyseEinstellungenFormular() {
  const o = prj.daten.offen, e = o.einstellungen, v = e.vorschaubilder;
  const arbeitsplatte = v.ort === "arbeitsplatte";
  const andere = prj.daten.zuletzt.filter((z) => z.vorhanden && z.pfad !== o.ordner);
  const alle = [...andere, ...e.referenzprojekte.filter((r) => !andere.some((z) => z.pfad === r.pfad))];
  const gewaehlt = new Set(e.referenzprojekte.map((r) => r.pfad));
  einst("analyse", "inhalt").innerHTML = `
    <div class="einst-gruppe" style="margin-top:0"><span class="leise">Vorschaubilder (nur Anzeige)</span>
      ${arbeitsplatte ? `auf dem Datenträger für Vorschaubilder <b>${esc(v.volume_name)}</b>, Ordner ${esc(v.ordner)}
        <span class="${o.arbeitsplatte_da ? "leise" : "warnung-text"}">${o.arbeitsplatte_da ? "angeschlossen" : "nicht angeschlossen"}</span>`
        : `im Projektordner (vorschauen/)${!o.speicher?.vorschauen
          ? ` <button type="button" class="knopf-mini knopf-text" id="pe-ap-waehlen">Doch auf einem Datenträger für Vorschaubilder ablegen …</button>
             <div id="pe-ap-liste"></div>`
          : `<div class="leise">${zahl(o.speicher.vorschauen)} Vorschaubilder sind schon entstanden; sie auf einen anderen Datenträger zu verlegen, folgt.</div>`}`}</div>
    <div class="einst-gruppe"><span class="leise">Filmvorschau; gilt für Vorschaubilder, die ab jetzt entstehen</span>
      ${wahl("pe-film", "webp", e.film.art, "Bewegt (animiertes WebP)",
             `<span class="film-zahl">Bilder <input type="number" id="pe-film-bilder" min="2" max="60" value="${e.film.art === "webp" ? e.film.bilder : 10}"></span>`)}
      ${wahl("pe-film", "raster", e.film.art, "Vier Standbilder als Raster", "ein JPEG mit 2 × 2 Bildern")}</div>
    <div class="einst-gruppe"><span class="leise">PDF-Vorschau; gilt für Vorschaubilder, die ab jetzt entstehen</span>
      ${wahl("pe-pdf", "seite", e.pdf.art, "Erste Seite", "ein JPEG")}
      ${wahl("pe-pdf", "webp", e.pdf.art, "Mehrere Seiten (animiertes WebP)",
             `<span class="film-zahl">Seiten <input type="number" id="pe-pdf-seiten" min="2" max="60" value="${e.pdf.seiten}"></span>`)}
      ${wahl("pe-pdf", "bereich", e.pdf.art, "Bestimmte Seiten (animiertes WebP)",
             `<span class="film-zahl">Seiten <input id="pe-pdf-bereich" class="kurz" value="${esc(e.pdf.bereich || "1–5")}" placeholder="1–5"></span>`)}</div>
    ${o.speicher ? `<div class="einst-gruppe"><span class="leise">Speicherplatz (nur Anzeige)</span>
      <div class="speicher-info">${icon("hard-drive")} Frei am Speicherort des Projekts: <b>${bytes(o.speicher.frei)}</b>
        · Projektordner belegt: <b>${bytes(o.speicher.belegt)}</b>${o.speicher.arbeitsplatte_frei != null
          ? ` · frei auf dem Datenträger für Vorschaubilder: <b>${bytes(o.speicher.arbeitsplatte_frei)}</b>` : ""}</div>
      <div class="leise">Vor jedem großen Schritt prüft Balduin, ob der Platz reicht, und hält rechtzeitig an, statt den
        Datenträger vollzuschreiben.</div></div>` : ""}
    <label class="einstellung"><input type="checkbox" id="pe-viren" ${e.virenscan ? "checked" : ""}>
      <span>Virenscan<br><span class="leise">gilt ab der nächsten Analyse</span></span></label>
    <label class="einstellung"><input type="checkbox" id="pe-personen" ${e.personen ? "checked" : ""}>
      <span>Personen und Gesichter auf Fotos erkennen (Schritt „Personen“)<br><span class="leise">rechnet auf den
        Vorschaubildern, ohne den Datenträger, ca. 15–20 Minuten je 30.000 Fotos; die Bewertung zeigt Porträts mit einem
        Gesicht, andere Fotos mit Personen mit einer Gruppe.
        Gilt ab der nächsten Analyse („Alles Offene fortsetzen“)</span></span></label>
    <div class="einst-gruppe"><span class="leise">Andere Projekte (gespeichert; der Abgleich folgt)</span>
      ${alle.length ? alle.map((z) => `<label class="option"><input type="checkbox" data-pe-referenz="${esc(z.pfad)}"
          data-name="${esc(z.name)}" ${gewaehlt.has(z.pfad) ? "checked" : ""}><span>${esc(z.name)}</span></label>`).join("")
        : `<div class="leise">Keine anderen Projekte bekannt.</div>`}</div>
    <div class="leise" style="margin-top:8px">Projektname, Projektkürzel und Anton stehen in den Einstellungen des Projekts (${icon("settings")} vor „Registrierung/Analyse“).</div>`;
  einst("analyse", "fehler").textContent = "";
  einstellungenGeprueft("analyse");
}

const EINST_FORMULAR = { projekt: projektEinstellungenFormular, analyse: analyseEinstellungenFormular };

// Eingaben eines Zahnrads im Aufbau von projekt.json, mit der Frage, ob sie vom Gespeicherten abweichen
function zahnradEingaben(teil) {
  const e = prj.daten.offen.einstellungen;
  const gleich = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  if (teil === "projekt") {
    const neu = { name: $("#pe-name").value.trim(), kennung: $("#pe-kennung").value.trim().toUpperCase(),
                  anton: { url: $("#pe-anton-url").value.trim().replace(/\/+$/, ""), testinstanz: $("#pe-anton-test").checked } };
    return { neu, anders: { name: neu.name !== e.name, kennung: neu.kennung !== e.kennung,
                            anton: neu.anton.url !== e.anton.url || neu.anton.testinstanz !== !!e.anton.testinstanz } };
  }
  const filmArt = document.querySelector('input[name="pe-film"]:checked').value;
  const pdfArt = document.querySelector('input[name="pe-pdf"]:checked').value;
  const neu = {
    film: { art: filmArt, bilder: filmArt === "webp" ? Number($("#pe-film-bilder").value) : e.film.bilder },
    pdf: { art: pdfArt, seiten: pdfArt === "webp" ? Number($("#pe-pdf-seiten").value) : e.pdf.seiten,
           bereich: pdfArt === "bereich" ? $("#pe-pdf-bereich").value.trim().replace("-", "–") : e.pdf.bereich || "1–5" },
    virenscan: $("#pe-viren").checked,
    personen: $("#pe-personen").checked,
    referenzprojekte: [...document.querySelectorAll("[data-pe-referenz]:checked")]
      .map((c) => ({ pfad: c.dataset.peReferenz, name: c.dataset.name })),
  };
  return { neu, anders: {
    film: !gleich(neu.film, e.film),
    pdf: !gleich(neu.pdf, { art: e.pdf.art, seiten: e.pdf.seiten, bereich: e.pdf.bereich || "1–5" }),
    virenscan: neu.virenscan !== e.virenscan,
    personen: neu.personen !== Boolean(e.personen),
    referenzprojekte: !gleich(neu.referenzprojekte.map((r) => r.pfad).sort(), e.referenzprojekte.map((r) => r.pfad).sort()),
  } };
}

// Nur die geänderten Angaben eines Zahnrads
function zahnradAenderungen(teil) {
  const { neu, anders } = zahnradEingaben(teil);
  return Object.fromEntries(Object.keys(neu).filter((k) => anders[k]).map((k) => [k, neu[k]]));
}

function einstellungenGeprueft(teil) {
  if (teil === "projekt") $("#pe-token-speichern").disabled = !$("#pe-token").value.trim();
  const aenderungen = zahnradAenderungen(teil), n = Object.keys(aenderungen).length;
  // Seitenbereich gleich hier prüfen, mit Erklärung statt eines späteren Fehlers im Lauf
  const fehler = (aenderungen.pdf?.art === "bereich" && seitenbereichFehler(aenderungen.pdf.bereich)) || "";
  const meldung = einst(teil, "fehler");
  if (fehler || meldung.dataset.pruefung) { meldung.className = "fehler"; meldung.textContent = fehler; meldung.dataset.pruefung = fehler ? "1" : ""; }
  einst(teil, "anwenden").disabled = !n || !!fehler;
  einst(teil, "verwerfen").disabled = !n;
}

// Nachträglich eine Arbeitsplatte wählen, solange noch kein Vorschaubild entstanden ist (Entscheidung 04.11.2026)
async function arbeitsplatteNachtraeglich() {
  const box = $("#pe-ap-liste");
  box.innerHTML = `<div class="leise">Angeschlossene Datenträger werden gelesen …</div>`;
  let platten;
  try { platten = await holen("/api/arbeitsplatten"); } catch (err) { box.innerHTML = `<div class="fehler">${esc(err.message)}</div>`; return; }
  box.innerHTML = platten.length
    ? platten.map((p) => `<label class="option"><input type="radio" name="pe-ap-platte" value="${esc(p.mountpunkt)}">
        <span>${icon("hard-drive")} <b>${esc(p.name)}</b> <span class="leise">${bytes(p.frei)} frei von ${bytes(p.groesse)}</span></span></label>`).join("")
      + `<div class="knopfzeile"><button type="button" class="knopf-leise" id="pe-ap-uebernehmen">Diesen Datenträger verwenden</button></div>`
    : `<div class="leise">Kein beschreibbarer externer Datenträger angeschlossen. Datenträger anschließen und erneut wählen.</div>`;
}
einst("analyse").addEventListener("click", async (e) => {
  const id = e.target.closest("button")?.id;
  if (id === "pe-ap-waehlen") return arbeitsplatteNachtraeglich();
  if (id !== "pe-ap-uebernehmen") return;
  const mp = document.querySelector('input[name="pe-ap-platte"]:checked')?.value;
  if (!mp) return;
  if (!(await rueckfrage(`Vorschaubilder künftig auf ${mp} ablegen (Ordner Balduin-Projekte/…/vorschauen)?`,
    "Das Projekt findet den Datenträger an seiner UUID wieder. Die Änderung wird protokolliert.", "Übernehmen"))) return;
  const meldung = () => einst("analyse", "fehler");
  try {
    await senden("/api/projekt_einstellungen", { vorschaubilder_auf: mp });
    prj.daten = await holen("/api/projekte");
    analyseEinstellungenFormular();
    meldung().className = "leise";
    meldung().textContent = "Vorschaubilder kommen ab jetzt auf den gewählten Datenträger.";
    standErfassung();
  } catch (err) { meldung().className = "fehler"; meldung().textContent = err.message; }
});

function einstellungenSchliessen(teil) {
  einst(teil).hidden = true;
  einst(teil, "knopf").setAttribute("aria-expanded", "false");
}

for (const teil of EINST_TEILE) {
  einst(teil, "knopf").onclick = async () => {
    if (!einst(teil).hidden) return einstellungenSchliessen(teil);
    prj.daten = await holen("/api/projekte").catch(() => prj.daten);    // frisch: Zahl der Platten, Arbeitsplatte, Token
    EINST_FORMULAR[teil]();                                              // nicht angewandte Änderungen verfallen
    einst(teil).hidden = false;
    einst(teil, "knopf").setAttribute("aria-expanded", "true");
  };
  einst(teil).addEventListener("input", () => einstellungenGeprueft(teil));
  einst(teil).addEventListener("change", () => einstellungenGeprueft(teil));
  einst(teil, "verwerfen").onclick = () => EINST_FORMULAR[teil]();
  einst(teil, "anwenden").onclick = () => einstellungenAnwenden(teil);
}
document.addEventListener("click", (e) => {
  for (const teil of EINST_TEILE) {
    if (!e.target.closest(`#${teil}-einstellungen, #${teil}-einstellungen-knopf`)) einstellungenSchliessen(teil);
  }
});

// Anton: Token und Verbindung wirken sofort (nicht erst mit „Anwenden“), sie gehören nicht zu projekt.json
einst("projekt").addEventListener("click", async (e) => {
  const id = e.target.closest("button")?.id;
  if (!["pe-token-speichern", "pe-token-entfernen", "pe-anton-pruefen"].includes(id)) return;
  const info = $("#pe-anton-info"), knopf = $("#" + id);
  if (id === "pe-token-entfernen" && !(await rueckfrage(`API-Token ${systemwort("aus_dem_schluesselspeicher")} entfernen?`,
    "Danach sieht der Abgleich nur noch öffentliche Bestände.", "Entfernen"))) return;
  knopf.disabled = true;
  info.className = "leise";
  info.textContent = id === "pe-anton-pruefen" ? "Anton wird gefragt …" : "…";
  try {
    const daten = { aktion: { "pe-token-speichern": "token_speichern", "pe-token-entfernen": "token_entfernen",
                              "pe-anton-pruefen": "pruefen" }[id] };
    if (id === "pe-token-speichern") daten.token = $("#pe-token").value.trim();
    const r = await senden("/api/anton", daten);
    prj.daten.offen.anton_token = r.token;
    if (id !== "pe-anton-pruefen") {
      projektEinstellungenFormular();
      standErfassung();
    }
    $("#pe-token-stand").textContent = TOKEN_TEXT[r.token] ?? r.token;
    const meldung = $("#pe-anton-info");
    meldung.className = id === "pe-anton-pruefen" && r.zugang === "öffentlich" ? "warnung-text" : "leise";
    meldung.textContent = id === "pe-anton-pruefen"
      ? `${r.url}: ${zahl(r.gesamt)} Objekte sichtbar (öffentlich ${zahl(r.oeffentlich)}), Zugang ${r.zugang}.`
        + (r.zugang === "intern" ? "" : r.token ? " Das API-Token sieht nicht mehr als öffentlich: Entweder ist alles öffentlich (dann vollständig), oder dem Konto fehlt in Anton eine interne Rolle."
          : " Ohne API-Token fehlen nicht öffentliche Bestände; sie erschienen fälschlich als „nicht in Anton“.")
      : id === "pe-token-speichern" ? `API-Token ${systemwort("im_schluesselspeicher")} abgelegt. „Verbindung prüfen“ zeigt, was es sieht.`
      : "API-Token entfernt.";
  } catch (err) {
    info.className = "fehler";
    info.textContent = err.message;
  }
  if (document.body.contains(knopf)) knopf.disabled = false;
  einstellungenGeprueft("projekt");
});

async function einstellungenAnwenden(teil) {
  const aenderungen = zahnradAenderungen(teil);
  const namen = Object.keys(aenderungen).map((k) => PE_NAMEN[k]);
  if (!namen.length) return;
  const vorschau = aenderungen.film && aenderungen.pdf ? "Film- und PDF-Vorschau" : aenderungen.film ? "Filmvorschau" : "PDF-Vorschau";
  const film = aenderungen.film || aenderungen.pdf
    ? `\n\nDie ${vorschau} gilt für Vorschaubilder, die ab jetzt entstehen; vorhandene bleiben.` : "";
  const was = teil === "projekt" ? "Einstellungen des Projekts" : "Einstellungen der Analyse";
  if (!(await rueckfrage(`${was} ändern: ${namen.join(", ")}?`, `${film.trim()}${film ? "\n\n" : ""}Die Änderung wird protokolliert.`,
    "Ändern"))) return;
  const knopf = einst(teil, "anwenden");
  knopf.disabled = true;
  try {
    await senden("/api/projekt_einstellungen", aenderungen);
    prj.daten = await holen("/api/projekte");
    $("#projekt-name").textContent = prj.daten.offen.name;
    document.title = `${prj.daten.offen.name} · Balduin`;
    EINST_FORMULAR[teil]();
    einst(teil, "fehler").className = "leise";
    einst(teil, "fehler").textContent = "Gespeichert.";
    standErfassung();                                       // Virenscan, Kennung und Anton in der Analyse nachführen
    if (aenderungen.kennung) datentraegerLaden();
  } catch (err) {
    einst(teil, "fehler").className = "fehler";
    einst(teil, "fehler").textContent = err.message;
    knopf.disabled = false;
  }
}

projektStart();

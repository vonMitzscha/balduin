// Vorlauf und Modul 3 Erschließung, Stufe 2 (Entscheidungen 03.11.2026, docs/plan.md).
// Server: tool/erschliessung.py. Hilfen ($, esc, zahl, holen, senden, thumbUrl, icon, modulKopf) aus app.js und icons.js;
// der Baum nutzt die Bausteine der Bewertung (SYMBOL, urteilMarke, balken, personMarke, mehrfachKlick, tastaturAuswahl).
"use strict";
// Alles in einem eigenen Gültigkeitsbereich: app.js, erfassung.js und dashboard.js teilen sich den globalen Namensraum
// (eine gleichnamige Funktion, z. B. baumZeichnen, würde sonst die der Bewertung ersetzen). Nach außen gehen nur
// vorlaufZeigen, erschliessungZeigen (für ansichtZeigen) und esStand (für den Ring in modulKopf).
window.esStand = null;           // {uebernommen, erschlossen} für den Ring in der Kopfleiste
(() => {

const es = {
  platten: [],
  offen: new Set(),              // aufgeklappte Ordner "platte|pfad"
  kinder: new Map(),             // "platte|pfad" -> Antwort von /api/es_kinder
  auswahl: new Map(),            // angekreuzt: "platte|pfad" -> {platte, pfad, art} (nie neu zuweisen, esAuswahl hält sie)
  aktiv: null,                   // zuletzt gewählte Zeile {platte, pfad, art}; der Editor nimmt sie, wenn nichts angekreuzt ist
  angaben: null,
  kassiertAus: false,
  filter: { q: "", nur: "", ansicht: "baum" },   // ansicht: Treffer als baum (Struktur) oder liste; dazu Facetten: jahr, art, platte, stand, schlagwort, ort, personen, hinweis, duplikate
  treffer: null,                 // Antwort von /api/es_suche
  trefferZu: new Set(),          // im Trefferbaum zugeklappte Ordner "platte|pfad"
  ursprung: null,                // Formularwerte beim Zeichnen (gespeichert werden nur geänderte Felder)
  metaOffen: false,              // Abschnitt „Weitere Metadaten“ aufgeklappt (bleibt beim Wechsel)
  meta: null,                    // Antwort von /api/es_metadaten
  zusatz: new Set(),             // im Dropdown hinzugefügte Anton-Felder (note.*), noch ohne Wert
  bestesAn: false,               // „bestes Datum“ übernommen (Vorschlag grün)
  entwurf: null,                 // Begriffsfelder im Editor: {akteur, ort, schlagworte, akteure, orte}
  angenommen: new Map(),         // Feld -> übernommener Vorschlag (bis zum Speichern)
  boxen: null,
  herkunftOffen: new Set(),      // aufgeklappte Herkunft in einer Box "ziel#platte|ordner"
  neuOffen: null,                // Ziel, unter dem die Halbbox „Neue Unterverzeichnungseinheit“ offen ist
  neuStufe: null,                // zuletzt gewählte Stufe dort
  ziehen: null,                  // gezogene Elemente [{platte, pfad, art}]
  zuordnen: null,                // offener Zuordnen-Dialog {ziele, ziel, pruefung}
};
const esKey = (platte, pfad) => platte + "|" + pfad;
const teilen = (k) => { const [platte, ...rest] = k.split("|"); return { platte, pfad: rest.join("|") }; };
const tag = (iso) => (iso || "").replace(/^(\d{4})-(\d{2})-(\d{2}).*/, "$3.$2.$1");
const zeitraumText = (w) => { try { const [von, bis, ca] = JSON.parse(w); return [von, bis].filter(Boolean).join("–") + (ca ? " (ca.)" : ""); } catch { return w || ""; } };
const datumZeit = (iso) => (iso ? `${tag(iso)} ${iso.slice(11, 16)}` : "");
const sichtbar = (id) => !$(id).hidden;

// ======================================================================================================
// Vorlauf
// ======================================================================================================
let vlTakt = null;
async function vorlaufZeigen() {
  const ziel = $("#vl-inhalt");
  clearTimeout(vlTakt);
  try {
    const [v, ue] = await Promise.all([holen("/api/vorlauf"), holen("/api/sujet_uebersetzungen").catch(() => null)]);
    v.uebersetzung = ue;
    window.esStand = { uebernommen: v.uebernommen, erschlossen: v.erschlossen };
    modulKopf();
    if ($("#vl-marke")) $("#vl-marke").hidden = !v.lauf?.aktiv;
    ziel.innerHTML = vorlaufHtml(v);
    if ((v.lauf?.aktiv || v.lauf?.status === "eingereiht") && sichtbar("#vorlauf")) vlTakt = setTimeout(vorlaufZeigen, 1500);
  } catch (err) {
    ziel.innerHTML = `<div class="fehler">${esc(err.message)}</div>`;
  }
}

// Kennzahlen eines Schritts als kurzer Text
function ergebnisText(s) {
  const k = s.stand?.kennzahlen || {};
  if (!s.stand) return "";
  if (s.k === "V5") return `${zahl(k.titel)} von ${zahl(k.ordner)} Ordnern mit Titelvorschlag, ${zahl(k.datum)} mit Datum`;
  if (s.k === "V7") return `${zahl(s.stand.ergebnis)} Dateien mit Vorschlag`;
  if (s.k === "V8") return `${zahl(k.treffer)} von ${zahl(k.kandidaten)} Begriffen in Anton gefunden`;
  if (s.k === "V3") return `${zahl(k.fotos)} Fotos, ${zahl(k.mit_vorschlag)} mit Schlagwortvorschlag (${zahl(k.anton_englisch)} Anton-Schlagworte englisch über Wikidata)`;
  if (s.k === "V10") return `${zahl(k.ordner_mit)} von ${zahl(k.ordner)} Ordnern mit verwandten Ordnern`;
  return "";
}

// Eine Zeile im Aufbau der Schrittliste aus Registrierung/Analyse (.schritt-zeile): Zeichen · Name, Text, Spur · rechts
const vlZeile = (st, zeichen, inhalt, rechts) => `<li class="schritt-zeile st-${st}">
  <span class="st-zeichen">${zeichen}</span><span>${inhalt}</span><span class="leise">${rechts}</span></li>`;
const vlSpur = (anteil) => (anteil != null ? `<span class="st-spur"><i style="width:${(100 * anteil).toFixed(1)}%"></i></span>`
  : `<span class="st-spur unbestimmt"><i></i></span>`);

let vlDaten = null;                                    // letzter Stand vom Server; Chips schalten darin lokal um
function vorlaufHtml(v) {
  vlDaten = v;
  const lauf = v.lauf;
  const aktiv = !!lauf?.aktiv;
  const laufSchritte = new Map((lauf?.schritte || []).map((s) => [s.schritt, s]));

  // Block 1: was Registrierung/Analyse schon erledigt hat; offen mit Spur und Anzahl
  const grundlage = (z) => {
    const fertig = z.erledigt >= z.betrifft;
    return vlZeile(fertig ? "fertig" : "wartet", fertig ? SCHRITT_ZEICHEN.fertig : "",
      `<b>${esc(z.name)}</b>
       <span class="st-text">${zahl(z.erledigt)} von ${zahl(z.betrifft)} ${esc(z.einheit)}${z.ergebnis_text ? ` · ${zahl(z.ergebnis)} ${esc(z.ergebnis_text)}` : ""}</span>
       ${fertig ? "" : vlSpur(z.betrifft ? z.erledigt / z.betrifft : 0)}`,
      fertig ? "erledigt" : `${zahl(z.betrifft - z.erledigt)} offen`);
  };

  // Block 2: Schritte des Vorlaufs; während des Laufs dessen Stand (wie Modul 1), sonst der Stand aus den Daten
  const schritt = (s) => {
    const ls = laufSchritte.get(s.k);
    const kopf = `<b>${esc(s.name)}</b>`;
    if (!s.lauf) return vlZeile("wartet", "", `${kopf}<span class="st-text">${esc(s.was)}</span>`, s.k === "V4" ? "in Registrierung/Analyse" : "folgt");
    if (ls && !aktiv && ls.status === "fertig") {       // letzter Lauf fertig: Ergebnis und Dauer wie in Modul 1
      return vlZeile("fertig", SCHRITT_ZEICHEN.fertig,
        `${kopf}<span class="st-text">${esc(ergebnisText(s) || ls.text || "")}</span>`,
        dauer(ls.start, ls.ende) + (s.offen ? `<br>${zahl(s.offen)} offen` : ""));
    }
    if (ls && ls.status !== "übersprungen" && (aktiv || ls.status !== "wartet")) {
      const laeuft = ls.status === "läuft";
      return vlZeile(STATUS_KLASSE[ls.status] || "wartet", laeuft ? '<i class="drehen"></i>' : SCHRITT_ZEICHEN[ls.status] ?? "",
        `${kopf}<span class="st-text">${esc(ls.text && ls.status !== "wartet" ? ls.text : laeuft ? "wird vorbereitet …" : s.was)}</span>
         ${laeuft ? vlSpur(ls.anteil) : ""}`,
        ls.status === "wartet" ? "wartet" : laeuft ? dauer(ls.start) : ls.status === "fertig" ? dauer(ls.start, ls.ende) : esc(ls.status));
    }
    const fertig = s.stand && !s.offen;
    const rechts = s.stand ? datumZeit(s.stand.zeit) + (s.offen ? `<br>${zahl(s.offen)} offen` : "") : `noch nicht gelaufen · ${esc(s.dauer)}`;
    return vlZeile(fertig ? "fertig" : "wartet", fertig ? SCHRITT_ZEICHEN.fertig : "",
      `${kopf}<span class="st-text">${esc(s.stand ? ergebnisText(s) : s.was)}</span>`, rechts);
  };

  // Block 3: Anton-Vokabular im Aufbau von „Bestand aus Anton“ (Registrierung/Analyse)
  const vok = v.vokabular || {};
  const geholt = vok.keyword?.[1];
  const alter = geholt ? Math.floor((Date.now() - new Date(geholt)) / 864e5) : null;
  const vokabular = geholt
    ? `<div><b>Stand ${esc(tag(geholt))}</b> <span class="leise">(${esc(tageText(alter))})</span>
         · ${zahl(vok.keyword?.[0] || 0)} Schlagworte · ${zahl(vok.place?.[0] || 0)} Orte · ${zahl(vok.actor?.[0] || 0)} Akteur:innen</div>
       <div class="leise">${esc(v.anton_url)}</div>`
    : `<div class="leise">Noch nicht aus ${esc(v.anton_url)} geholt; „Normdaten abgleichen“ holt es.</div>`;

  const ab = lauf && (!!lauf.abbrechen || vlAbbruch === lauf.lauf_id);
  const eingereiht = lauf?.status === "eingereiht";
  const status = aktiv ? (ab ? "wird abgebrochen …" : "läuft") : eingereiht ? "eingereiht" : lauf?.status;
  const laufbar = v.schritte.filter((s) => s.lauf);
  const offenVorher = v.vorhanden.some((z) => z.erledigt < z.betrifft);
  return `
    <p class="vl-kopf">Sammelt die Metadaten der übernommenen Dateien und analysiert den bewerteten Bestand.
      Daraus entstehen nur Vorschläge; übernommen wird erst in der Erschließung.
      <span class="leise">${zahl(v.uebernommen)} übernommene Dateien</span></p>

    <div class="ueberschrift">Aus Registrierung/Analyse</div>
    <ul class="schritt-liste">${v.vorhanden.map(grundlage).join("")}</ul>
    ${offenVorher ? `<div class="leise tipp">Offenes holt Registrierung/Analyse nach.</div>` : ""}

    <div class="ueberschrift">Schritte des Vorlaufs</div>
    <div class="chips gross">${laufbar.map((s) =>
      `<button type="button" class="chip${s.stand && !s.offen ? " erledigt" : ""}${s.an ? " gewaehlt" : ""}" data-vl-schritt="${s.k}"
         aria-pressed="${s.an}" ${aktiv || eingereiht ? "disabled" : ""} title="${esc(s.was)}">${esc(s.name)}</button>`).join("")}</div>
    ${lauf ? `<div class="lauf-titel vl-lauf"><span class="pille ${lauf.status === "fertig" ? "gut" : aktiv || eingereiht ? "" : "warnung"}">${esc(status)}</span>
      <span class="leise">${lauf.lauf_id ? `Vorlauf ${lauf.lauf_id} · gestartet ${datumZeit(lauf.start)}` : "wird gestartet …"}${!aktiv && lauf.ende ? ` · ${dauer(lauf.start, lauf.ende)}` : ""}</span></div>
      ${lauf.meldung && !aktiv && lauf.status !== "fertig" ? `<div class="hinweis warnung">${esc(lauf.meldung)}</div>` : ""}` : ""}
    <ul class="schritt-liste">${v.schritte.map(schritt).join("")}</ul>
    <div class="knopfzeile">
      ${aktiv || eingereiht ? (lauf.lauf_id && aktiv ? `<button type="button" id="vl-abbrechen" data-lauf="${lauf.lauf_id}" ${ab ? "disabled" : ""}>${ab ? "Wird abgebrochen …" : "Abbrechen"}</button>` : "")
        : `<button type="button" id="vl-start" class="haupt" ${laufbar.some((s) => s.an) ? "" : "disabled"}>Ausgewählte ausführen</button>`}
    </div>
    ${eingereiht ? `<div class="leise tipp">Startet, sobald der laufende Lauf in Registrierung/Analyse fertig ist.</div>` : ""}
    ${aktiv ? `<div class="leise tipp">Der Vorlauf geht weiter, wenn dieses Fenster oder der Browser geschlossen wird.</div>` : ""}

    ${v.uebersetzung ? (() => {
      const b = v.uebersetzung.begriffe, ueb = b.filter((x) => x.uebersetzung).length, gep = b.filter((x) => x.geprueft).length;
      return `<div class="ueberschrift">Sujet-Begriffe (${esc(v.uebersetzung.einstellung.sprache)})</div>
        <div class="anton-stand"><div>${zahl(ueb)} von ${zahl(b.length)} übersetzt · ${zahl(gep)} geprüft
          <span class="leise">· Weg: ${v.uebersetzung.einstellung.weg === "mymemory" ? "MyMemory" : "Sprachmodell"} (Einstellungen der Erschließung)</span></div>
          <div class="leise">${ueb ? "Ungeprüfte Übersetzungen können falsch sein; korrigierte gelten ab dem nächsten Lauf von „Sujet“." : "Übersetzt wird zu Beginn des nächsten Laufs von „Sujet“ (oben auswählen und starten; mit dem Sprachmodell einmalig rund 12 min, auch ohne Datenträger für Vorschaubilder)."}</div>
          ${ueb ? `<div class="knopfzeile"><button type="button" id="vl-uebersetzung">Übersetzungen prüfen …</button></div>` : ""}</div>`;
    })() : ""}
    <div class="ueberschrift">Anton-Vokabular</div>
    <div class="anton-stand">${vokabular}</div>`;
}

// Übersetzungen der Sujet-Begriffe prüfen und korrigieren (Entscheidung 04.11.2026)
async function uebersetzungPruefen() {
  const u = await holen("/api/sujet_uebersetzungen");
  const zeilen = u.begriffe.filter((x) => x.uebersetzung);
  $("#es-frage-titel").textContent = "Übersetzungen der Sujet-Begriffe prüfen";
  $("#es-frage-inhalt").innerHTML = `<p class="dialog-text">Korrigieren, was nicht passt; gespeichert werden alle Zeilen als geprüft. Ein Schlagwort sollte ohne Artikel stehen.</p>
    <input type="search" class="db-suche" id="ue-filter" placeholder="Filtern …">
    <div class="es-tabelle-halter"><table class="vl-tabelle"><thead><tr><th>Englisch</th><th>Gruppe</th><th>${esc(u.einstellung.sprache)}</th><th></th></tr></thead><tbody>
    ${zeilen.map((x, i) => `<tr><td>${esc(x.en)}</td><td class="leise">${esc(x.gruppe)}</td>
      <td><input data-ue="${i}" value="${esc(x.uebersetzung)}" spellcheck="false"></td><td class="leise">${x.geprueft ? icon("check") : ""}</td></tr>`).join("")}</tbody></table></div>`;
  $("#ue-filter").oninput = (e) => document.querySelectorAll("#es-frage-inhalt tbody tr").forEach((tr) =>
    (tr.hidden = !!e.target.value && !tr.textContent.toLowerCase().includes(e.target.value.toLowerCase()) && !tr.querySelector("input").value.toLowerCase().includes(e.target.value.toLowerCase())));
  $("#es-frage-ok").textContent = "Alle als geprüft speichern";
  const liste = await frageDialog(() => zeilen.map((x, i) => ({ en: x.en, uebersetzung: document.querySelector(`[data-ue="${i}"]`).value })));
  if (!liste) return;
  try { await senden("/api/sujet_uebersetzungen", { liste }); } catch (err) { meldung(err.message, "Fehler"); }
  vorlaufZeigen();
}

let vlAbbruch = null;                                  // eben geklickt: Knopf bleibt gesperrt, bis der Server es meldet
const vlAuswahl = () => Object.fromEntries((vlDaten?.schritte || []).filter((s) => s.lauf).map((s) => [s.k, !!s.an]));

$("#vl-neu").addEventListener("click", vorlaufZeigen);
$("#vl-inhalt").addEventListener("click", async (ev) => {
  // Chip: sofort umschalten und neu zeichnen, die Einstellung geht im Hintergrund an den Server (ohne neue Abfrage)
  const chip = ev.target.closest("[data-vl-schritt]");
  if (chip && vlDaten) {
    const s = vlDaten.schritte.find((x) => x.k === chip.dataset.vlSchritt);
    s.an = !s.an;
    $("#vl-inhalt").innerHTML = vorlaufHtml(vlDaten);
    senden("/api/vorlauf_einstellungen", { schritte: vlAuswahl() }).catch((err) => { meldung(err.message, "Fehler"); vorlaufZeigen(); });
    return;
  }
  if (ev.target.closest("#vl-start")) {
    vlDaten.lauf = { lauf_id: 0, aktiv: true, status: "wartet", start: "",
      schritte: vlDaten.schritte.filter((s) => s.lauf && s.an).map((s) => ({ schritt: s.k, status: "wartet" })) };
    $("#vl-inhalt").innerHTML = vorlaufHtml(vlDaten);
    try { await senden("/api/vorlauf_starten", {}); } catch (err) { meldung(err.message, "Fehler"); }
    if (typeof standErfassung === "function") standErfassung().then(() => typeof taktStellen === "function" && taktStellen()).catch(() => {});
    return vorlaufZeigen();
  }
  if (ev.target.closest("#vl-uebersetzung")) return uebersetzungPruefen();
  const ab = ev.target.closest("#vl-abbrechen");
  if (ab) {
    ab.disabled = true;
    vlAbbruch = Number(ab.dataset.lauf);
    try { await senden("/api/abbrechen", { lauf_id: vlAbbruch }); } catch (err) { meldung(err.message, "Fehler"); }
    setTimeout(vorlaufZeigen, 800);
  }
});

// ======================================================================================================
// Erschließung: Baum und Facetten
// ======================================================================================================
let feldlisteGeholt = false;
async function erschliessungZeigen() {
  try {
    const d = await holen("/api/es_platten");
    es.platten = d.platten;
    window.esStand = d.platten.reduce((s, p) => ({ uebernommen: s.uebernommen + p.uebernommen, erschlossen: s.erschlossen + p.erschlossen }),
                               { uebernommen: 0, erschlossen: 0 });
    modulKopf();
    for (const k of [...es.offen]) {             // aufgeklappte Ordner neu laden
      try { es.kinder.set(k, await holen("/api/es_kinder", teilen(k))); } catch { es.offen.delete(k); }
    }
    baumZeichnen();
    if (filterAktiv()) sucheLaden();
    else facettenZeichnen();
    boxenLaden();
    if (!feldlisteGeholt) {                        // weitere Anton-Felder einmal je Sitzung (höchstens alle 7 Tage neu)
      feldlisteGeholt = true;
      holen("/api/es_felder").then((r) => { if (es.angaben && r.felder.length && !es.angaben.anton_felder.length) { es.angaben.anton_felder = r.felder; felderBehalten(editorZeichnen); } }).catch(() => {});
    }
    await angabenLaden();                          // ohne Ziele: Hinweis statt alter Mehrfachauswahl
  } catch (err) {
    $("#es-baum").innerHTML = `<li class="fehler">${esc(err.message)}</li>`;
  }
}

// ---- Baum: gleicher Aufbau und gleiche Auswahl wie in der Bewertung (app.js: knoten, mehrfachKlick) ----
// Spalten: Name · Größe · Entscheidung · Erschließung. Kästchen kreuzen an (Strg/⌘+Klick einzeln, Umschalt+Klick
// Bereich), ein einfacher Klick wählt eine Zeile; der Editor zeigt die angekreuzten Elemente, sonst die gewählte Zeile.
// Nicht Übernommenes bleibt sichtbar (grau, durchgestrichen), lässt sich aber weder wählen noch ankreuzen.
// Ziele des Editors: angekreuzte, sonst die gewählte Zeile
const esZiele = () => (es.auswahl.size ? [...es.auswahl.values()] : es.aktiv ? [es.aktiv] : []);
// Nach dem Speichern und nach jeder Aktion: Auswahl ganz aufheben wie in der Bewertung, der Editor zeigt danach
// wieder die gewählte Zeile (Entscheidung 06.11.2026; ersetzt „Editor bleibt bei denselben Elementen“ vom 04.11.)
function auswahlNachAktion() {
  if (!es.auswahl.size) return;
  es.auswahl.clear();
  document.querySelectorAll("#es-baum input[data-k], #es-treffer input[data-k]").forEach((c) => { c.checked = false; });
  auswahlInfo();
}
// Aktion fertig: Auswahl aufheben, Baum, Boxen und Editor neu
async function nachAktion() {
  auswahlNachAktion();
  await erschliessungZeigen();
}
// Auswahl aufheben ohne Speichern (Esc, Klick ins Leere, Marke „N angekreuzt ✕“); fragt bei offenen Änderungen nach
const esAuswahlAufheben = () => { if (es.auswahl.size) esAnkreuzen([...es.auswahl.values()], false); };
const esMarke = auswahlMarkeAnlegen($("#es-alle-kreuz"), () => esAuswahlAufheben());
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape" || e.target.closest("input, textarea, select, dialog")) return;
  if (!$("#erschliessung").hidden) esAuswahlAufheben();
});
const zieleText = (ziele) => ziele.map((z) => esKey(z.platte, z.pfad)).sort().join("\n");
// Sichtbare, wählbare Zeilen in Reihenfolge (für Umschalt+Klick); zugeklappte Ordner haben keine Kinder im DOM
const esZeilen = (liste) => [...$(liste).querySelectorAll("li[data-art]")].filter((li) => !li.classList.contains("aus"));
const waehlbar = (t) => { const li = zeileVon(t); return li && li.dataset.art && !li.classList.contains("aus") ? li : null; };
const esAuswahl = { auswahl: es.auswahl, anker: null, ankreuzen: (eintraege, an) => esAnkreuzen(eintraege, an) };

// Letzte Spalte wie in der Bewertung (app.js: balkenDrei, punkte): Ordner und Platten zwei Balken über die
// übernommenen Dateien (1 erschlossen, 2 in den Anton-Bestand eingereiht = zugeordnet), Dateien je Balken ein Punkt
const ES_ERSCHLOSSEN = [["erschlossen", "a-gruen", "erschlossen"]];
const ES_EINGEREIHT = [["zugeordnet", "violett", "eingereiht"]];
function standZelle(art, e) {
  if (!e.uebernommen) return `<span class="rechts"></span>`;
  const ziel = e.zuordnung ? ` (${e.zuordnung.name} als ${e.zuordnung.stufe})` : "";
  if (art === "datei") {
    const titel = `Erschließung: ${e.erschlossen ? "erschlossen" : "noch nicht erschlossen"}\n`
                + `Anton-Bestand: ${e.zugeordnet ? "eingereiht" + ziel : "noch nicht eingereiht"}`;
    return `<span class="punkte" title="${esc(titel)}">
      <i class="punkt ${e.erschlossen ? "a-gruen" : "leer"}"></i><i class="punkt ${e.zugeordnet ? "violett" : "leer"}"></i></span>`;
  }
  const z = { dateien: e.uebernommen, erschlossen: e.erschlossen, zugeordnet: e.zugeordnet };
  const titel = `${zahl(e.uebernommen)} übernommen\nErschließung: ${zahl(e.erschlossen)} erschlossen\n`
              + `Anton-Bestand: ${zahl(e.zugeordnet)} eingereiht${ziel}`;
  return `<span class="rechts" title="${esc(titel)}">${balken(z, ES_ERSCHLOSSEN)}${balken(z, ES_EINGEREIHT)}</span>`;
}

// inListe: Zeile der Trefferliste (klappt nicht über es.offen auf); offen: im Trefferbaum der eigene Zustand
function esKnoten(art, platte, pfad, name, e, tiefe, extra = "", kinderHtml = "", inListe = false, offen = null) {
  const k = esKey(platte, pfad);
  const aus = !e.uebernommen;
  const auf = offen !== null ? offen && art !== "datei" : !inListe && art !== "datei" && !aus && es.offen.has(k);
  const z = e.zaehler || {};
  const aktiv = es.aktiv && esKey(es.aktiv.platte, es.aktiv.pfad) === k;
  return `<li role="treeitem" data-art="${art}" data-platte="${esc(platte)}" data-pfad="${esc(pfad)}" data-tiefe="${tiefe}"
      class="${auf ? "offen" : ""}${aus ? " aus" : ""}"${art !== "datei" && !aus ? ` aria-expanded="${auf}"` : ""}>
    <div class="zeile${art === "platte" ? " plattenzeile" : ""}${aktiv ? " gewaehlt" : ""}" style="--tiefe:${tiefe}"${aus ? "" : ' draggable="true"'}>
      <span class="links">
        <input type="checkbox" data-k="${esc(k)}" ${es.auswahl.has(k) ? "checked" : ""} ${aus ? "disabled" : ""} aria-label="auswählen">
        <span class="pfeil">${art === "datei" || aus || (inListe && offen === null) ? "" : icon("chevron-right")}</span>
        ${art === "platte" ? traegerIcon(e.traeger, "", "symbol") : art === "ordner" ? ordnerIcon(name, "symbol") : SYMBOL[art]}
        <span class="name${e.titel ? " mit-titel" : ""}" title="${esc(e.titel ? `${name}\n${pfad}` : pfad || name)}">${esc(e.titel || name)}${extra}</span>${e.hinweis ? icon("info", "es-hinweis") : ""}${art === "datei" ? personMarke(e) : ""}
      </span>
      <span class="groesse">${bytes(art === "datei" ? e.groesse : z.bytes)}</span>${urteilMarke(e.urteil)}${standZelle(art, e)}
    </div>${auf ? `<ul role="group">${kinderHtml}</ul>` : ""}</li>`;
}

function kinderHtml(platte, k, tiefe) {
  const kinder = es.kinder.get(k);
  if (!kinder) return `<li class="mehr-zeile leise">Lädt …</li>`;
  let html = "";
  for (const o of kinder.ordner) {
    if (es.kassiertAus && !o.uebernommen) continue;
    html += ordnerKnoten("ordner", platte, o.pfad, o.name, o, tiefe);
  }
  for (const f of kinder.dateien) {
    if (es.kassiertAus && !f.uebernommen) continue;
    html += esKnoten("datei", platte, f.pfad, f.name, f, tiefe);
  }
  if (kinder.weitere) html += `<li class="mehr-zeile"><button type="button" class="knopf-leise" data-mehr="${esc(k)}">${zahl(kinder.weitere)} weitere Dateien laden</button></li>`;
  return html;
}
function ordnerKnoten(art, platte, pfad, name, e, tiefe, extra = "") {
  const k = esKey(platte, pfad);
  const kinder = e.uebernommen && es.offen.has(k) ? kinderHtml(platte, k, tiefe + 1) : "";
  return esKnoten(art, platte, pfad, name, e, tiefe, extra, kinder);
}

function baumZeichnen() {
  const platten = es.platten.filter((p) => !(es.kassiertAus && !p.uebernommen));
  $("#es-baum").innerHTML = platten.length
    ? platten.map((p) => {
        const extra = `<small>${esc(p.volume || "")}${p.kopie_von ? " · Kopie von " + esc(p.kopie_von) : ""}</small>`;
        return ordnerKnoten("platte", p.id, "", p.id, p, 0, extra);
      }).join("")
    : `<li class="leer-hinweis">Noch nichts übernommen. Erst in der Bewertung entscheiden.</li>`;
  $("#es-baum").querySelectorAll(":scope > li[data-art=platte]").forEach((li) => {
    const p = es.platten.find((x) => x.id === li.dataset.platte);
    if (p?.etikett) li.querySelector(".name").title = "Etikett:\n" + p.etikett;
  });
  auswahlInfo();
}

function auswahlInfo() {
  const n = es.auswahl.size;
  auswahlFaerben([$("#es-baum"), $("#es-treffer")], es.auswahl, esMarke);
  $("#es-auswahl-info").textContent = n
    ? `${zahl(n)} ausgewählt · Klick wählt weitere aus oder ab, Umschalt+Klick Bereich, Esc hebt auf`
    : es.aktiv ? "Zeile geöffnet · auswählen, um mehrere zu erschließen" : "Zeile öffnen oder auswählen; Strg/⌘ und Umschalt für mehrere.";
  const boxen = (es.boxen?.boxen || []).length;
  $("#es-zuordnen-knopf").disabled = !esZiele().length || !boxen;
  $("#es-zuordnen-knopf").title = !boxen ? "Erst rechts eine Verzeichnungseinheit aus Anton laden" : "Auswahl einer Box zuordnen (oder auf eine Box ziehen)";
  esAlleKreuzZeichnen();
}

// Ankreuzen: ein Zustand für Baum und Trefferliste (wie ankreuzen in app.js)
function esAnkreuzen(eintraege, an) {
  const vorher = zieleText(esZiele());
  for (const { platte, pfad, art } of eintraege) {
    const k = esKey(platte, pfad);
    if (an) es.auswahl.set(k, { platte, pfad, art });
    else es.auswahl.delete(k);
    document.querySelectorAll(`#es-baum input[data-k="${CSS.escape(k)}"], #es-treffer input[data-k="${CSS.escape(k)}"]`)
      .forEach((c) => { c.checked = an; });
  }
  zieleGeaendert(vorher);
}
async function zieleGeaendert(vorher) {
  auswahlInfo();
  if (zieleText(esZiele()) === vorher) return;
  // ungespeicherte Änderungen am bisherigen Element nicht still verlieren (Entscheidung 04.11.2026, fünfte Runde)
  if (es.angaben && $("#es-speichern") && zieleText(es.angaben.ziele) === vorher && geaenderteFelder().length) {
    const n = es.angaben.ziele.length;
    $("#es-frage-titel").textContent = "Ungespeicherte Änderungen";
    $("#es-frage-inhalt").innerHTML = `<p class="dialog-text">An <b>${esc(n > 1 ? `${zahl(n)} gewählten Elementen` : es.angaben.name)}</b>
      gibt es ungespeicherte Änderungen (${esc(geaenderteFelder().map(feldName).join(", "))}).</p>`;
    $("#es-frage-ok").textContent = "Speichern";
    $("#es-frage-abbrechen").textContent = "Verwerfen";
    const sichern = await frageDialog(() => true);
    $("#es-frage-abbrechen").textContent = "Abbrechen";
    if (sichern) {
      try { await speichern({ still: true, loesen: false }); } catch (err) { meldung(err.message, "Speichern ging nicht"); }
      es.angenommen.clear(); es.bestesAn = false;
      return erschliessungZeigen();
    }
  }
  es.angenommen.clear();
  es.bestesAn = false;
  angabenLaden();
}
const feldName = (k) => es.angaben?.felder[k]?.name || k;
// Vor einer Batch-Aktion: offene Eingaben zuerst speichern (Auswahl bleibt). false = abgebrochen
async function offeneSichern() {
  if (!$("#es-speichern") || !geaenderteFelder().length) return true;
  try {
    const r = await speichern({ still: true, loesen: false });
    return r !== null;
  } catch (err) { meldung(err.message, "Speichern ging nicht"); return false; }
}

// Kästchen im Spaltenkopf: im Baum alle Platten (Ordner und Dateien erben), bei Filtern alle gezeigten Treffer
const esListe = () => (filterAktiv() ? "#es-treffer" : "#es-baum");
function esOberste() {
  const b = filterAktiv() && es.treffer?.baum;
  if (b) {                     // Trefferbaum: nur die Treffer selbst (Dateien; bei „nur Ordner“ die untersten Ordner)
    const dateien = b.knoten.filter((n) => n.art === "datei");
    const eltern = new Set(b.knoten.filter((n) => n.art === "ordner").map((n) => esKey(n.platte, n.eltern)));
    const liste = dateien.length ? dateien : b.knoten.filter((n) => n.art === "ordner" && !eltern.has(esKey(n.platte, n.pfad)));
    return liste.map((n) => ({ platte: n.platte, pfad: n.pfad, art: n.art }));
  }
  return [...$(esListe()).children].filter((li) => li.dataset.art && !li.classList.contains("aus")).map(eintragVon);
}
function esAlleKreuzZeichnen() {
  const kasten = $("#es-alle-kreuz");
  const ziele = esOberste();
  const alle = ziele.length > 0 && ziele.every((z) => es.auswahl.has(esKey(z.platte, z.pfad)));
  kasten.checked = alle;
  kasten.indeterminate = !alle && es.auswahl.size > 0;
  kasten.disabled = !ziele.length && !es.auswahl.size;
  kasten.title = alle || es.auswahl.size ? "Auswahl aufheben" : filterAktiv() ? "Alle gezeigten Treffer auswählen" : "Alles auswählen (alle Datenträger)";
}
$("#es-alle-kreuz").addEventListener("change", (ev) => {
  if (!ev.target.checked || es.auswahl.size) return esAnkreuzen([...es.auswahl.values()], false);
  esAnkreuzen(esOberste(), true);
});

function waehlen(li) {
  const vorher = zieleText(esZiele());
  document.querySelectorAll("#es-baum .zeile.gewaehlt, #es-treffer .zeile.gewaehlt").forEach((z) => z.classList.remove("gewaehlt"));
  li.querySelector(":scope > .zeile").classList.add("gewaehlt");
  es.aktiv = eintragVon(li);
  zieleGeaendert(vorher);
}

async function aufklappen(k, offen = !es.offen.has(k)) {
  if (!offen) { es.offen.delete(k); return baumZeichnen(); }
  es.offen.add(k);
  if (!es.kinder.has(k)) {
    baumZeichnen();                                         // zeigt „Lädt …“
    try { es.kinder.set(k, await holen("/api/es_kinder", teilen(k))); }
    catch (err) { meldung(err.message, "Fehler"); es.offen.delete(k); }
  }
  baumZeichnen();
}
async function mehrLaden(k) {
  const alt = es.kinder.get(k);
  try {
    const d = await holen("/api/es_kinder", { ...teilen(k), offset: alt.offset });
    es.kinder.set(k, { ...alt, dateien: alt.dateien.concat(d.dateien), weitere: d.weitere, offset: d.offset });
  } catch (err) { meldung(err.message, "Fehler"); }
  baumZeichnen();
}

// Klick in Baum oder Trefferliste: wie in der Bewertung. Pfeil klappt auf, Kästchen kreuzt an,
// Strg/⌘ und Umschalt kreuzen mehrere an, ein einfacher Klick wählt die Zeile (Ordner klappen dabei auf)
function zeileKlick(ev) {
  const mehr = ev.target.closest("[data-mehr]");
  if (mehr) return mehrLaden(mehr.dataset.mehr);
  const li = waehlbar(ev.target);
  if (!li) { if (insLeere(ev) && !zeileVon(ev.target)) esAuswahlAufheben(); return; }
  if (nachKontextKlick(ev)) return;
  if (mehrfachKlick(ev, li, esZeilen("#" + ev.currentTarget.id), esAuswahl)) return;
  if (ev.target.matches("input[type=checkbox]")) {
    esAnkreuzen([eintragVon(li)], ev.target.checked);
    ankerSetzen(li, ev.target.checked, esAuswahl);
    return;
  }
  const k = esKey(li.dataset.platte, li.dataset.pfad);
  const imBaum = ev.currentTarget === $("#es-baum");
  if (!imBaum && es.treffer?.baum && ev.target.closest(".pfeil") && li.dataset.art !== "datei") {
    if (es.trefferZu.has(k)) es.trefferZu.delete(k); else es.trefferZu.add(k);  // Trefferbaum auf- und zuklappen
    return trefferZeichnen();
  }
  if (imBaum && ev.target.closest(".pfeil") && li.dataset.art !== "datei") return aufklappen(k);
  if (auswahlKlick(li, esAuswahl)) return;              // etwas angekreuzt: Klick kreuzt an oder ab
  ankerSetzen(li, true, esAuswahl);
  waehlen(li);
  if (imBaum && li.dataset.art !== "datei" && !es.offen.has(k)) aufklappen(k, true);
}
$("#es-baum").addEventListener("click", zeileKlick);
$("#es-treffer").addEventListener("click", zeileKlick);
tastaturAuswahl($("#es-baum"), waehlbar, () => esZeilen("#es-baum"), esAuswahl);
tastaturAuswahl($("#es-treffer"), waehlbar, () => esZeilen("#es-treffer"), esAuswahl);
$("#es-kassiert-aus").addEventListener("change", (ev) => { es.kassiertAus = ev.target.checked; baumZeichnen(); });
$("#es-neu").addEventListener("click", erschliessungZeigen);

// ---- Facetten ----
const FACETTEN = [
  ["jahr", "Jahr", "calendar"], ["art", "Art", "image"], ["platte", "Datenträger", "archive"], ["stand", "Stand", "circle-dot"],
  ["schlagwort", "Schlagwort (Vorschlag)", "tag"], ["ort", "Ort (Vorschlag)", "map-pin"],
];
const SCHALTER = [["personen", "mit Personen", "users"], ["hinweis", "mit Hinweis", "info"], ["duplikate", "mit Dubletten", "copy"]];
const filterAktiv = () => !!(es.filter.q || es.filter.nur || FACETTEN.some(([k]) => es.filter[k]) || SCHALTER.some(([k]) => es.filter[k]));

function facettenZeichnen() {
  const t = es.treffer;
  const gewaehlt = (k) => es.filter[k];
  const chips = [];
  for (const [k, name, sym] of FACETTEN) {
    if (gewaehlt(k)) chips.push(`<button type="button" class="es-facette an" data-facette="${k}" data-wert="">${icon(sym)}${esc(name)}: ${esc(es.filter[k])} ${icon("x")}</button>`);
  }
  for (const [k, name, sym] of SCHALTER) {
    const n = t?.schalter?.[k];
    chips.push(`<button type="button" class="es-facette${gewaehlt(k) ? " an" : ""}" data-schalter="${k}">${icon(sym)}${esc(name)}${n != null ? ` <span class="leise">${zahl(n)}</span>` : ""}</button>`);
  }
  let auswahl = "";
  if (t) {
    auswahl = FACETTEN.filter(([k]) => !gewaehlt(k) && (t.facetten[k] || []).length > (k === "platte" || k === "stand" ? 1 : 0))
      .map(([k, name]) => `<label class="es-facette-wahl">${esc(name)}<select data-facette-wahl="${k}"><option value="">alle</option>
        ${t.facetten[k].map(([w, n]) => `<option value="${esc(w)}">${esc(w)} (${zahl(n)})</option>`).join("")}</select></label>`).join("");
  } else {
    auswahl = `<button type="button" class="knopf-leise" id="es-facetten-zeigen">${icon("search")} Facetten zeigen</button>`;
  }
  $("#es-facetten").innerHTML = chips.join("") + auswahl
    + (filterAktiv() ? `<button type="button" class="knopf-leise" id="es-filter-weg">Filter zurücksetzen</button>` : "");
  document.querySelectorAll(".es-nur [data-nur]").forEach((b) => { b.classList.toggle("aktiv", es.filter.nur === "ordner"); b.setAttribute("aria-pressed", es.filter.nur === "ordner"); });
  document.querySelectorAll(".es-nur [data-ansicht]").forEach((b) => b.classList.toggle("aktiv", b.dataset.ansicht === es.filter.ansicht));
}

let sucheTakt = null;
async function sucheLaden() {
  try {
    es.treffer = await senden("/api/es_suche", es.filter);
  } catch (err) {
    $("#es-treffer").innerHTML = `<li class="fehler">${esc(err.message)}</li>`;
    return;
  }
  facettenZeichnen();
  trefferZeichnen();
}

function trefferZeichnen() {
  const aktiv = filterAktiv();
  $("#es-baum").hidden = aktiv;
  $("#es-treffer").hidden = !aktiv;
  if (!aktiv || !es.treffer) return;
  const t = es.treffer;
  if (t.baum) return trefferbaumZeichnen(t);
  const kopf = `<li class="es-treffer-kopf leise">${zahl(t.gesamt)} übernommene Dateien passen${t.ordner ? `, in ${zahl(t.ordner.length)} Ordnern` : t.dateien.length < t.gesamt ? `, die ersten ${zahl(t.dateien.length)} gezeigt` : ""}</li>`;
  // gleiche Zeilen wie im Baum (esKnoten), darunter der Fundort wie in der Suche der Bewertung
  const ort = (platte, ordner, zusatz = "") => `<span class="trefferpfad">${esc(platte)} / ${esc(ordner || "(oberste Ebene)")}${zusatz}</span>`;
  const zeilen = t.ordner
    ? t.ordner.map((o) => esKnoten(o.pfad ? "ordner" : "platte", o.platte, o.pfad, o.name, o, 0,
        ort(o.platte, o.pfad.split("/").slice(0, -1).join("/"), ` · ${zahl(o.treffer)} Treffer`), "", true))
    : t.dateien.map((f) => esKnoten("datei", f.platte, f.pfad, f.name,
        { ...f, uebernommen: true, erschlossen: f.stand !== "offen", zugeordnet: f.stand === "zugeordnet" }, 0, ort(f.platte, f.ordner), "", true));
  $("#es-treffer").innerHTML = kopf + (zeilen.join("") || `<li class="leer-hinweis">Nichts gefunden.</li>`);
  auswahlInfo();
}

// Treffer mit Struktur (Entscheidung 04.11.2026): Platten und Ordner mit Treffern, aufklappbar, alles andere aus
function trefferbaumZeichnen(t) {
  const kinder = new Map();                                  // "platte|eltern" -> Knoten
  for (const n of t.baum.knoten) {
    if (n.art === "platte") continue;
    const k = esKey(n.platte, n.eltern);
    if (!kinder.has(k)) kinder.set(k, []);
    kinder.get(k).push(n);
  }
  const zeichne = (n, tiefe) => {
    const k = esKey(n.platte, n.pfad);
    if (n.art === "datei") return esKnoten("datei", n.platte, n.pfad, n.name, n, tiefe, "", "", true);
    const auf = !es.trefferZu.has(k);
    const unten = auf ? (kinder.get(k) || []).sort((a, b) => (a.art === "datei") - (b.art === "datei")).map((x) => zeichne(x, tiefe + 1)).join("") : "";
    const extra = `<small>${n.art === "platte" && n.volume ? esc(n.volume) + " · " : ""}${zahl(n.treffer)} Treffer</small>`;
    return esKnoten(n.art, n.platte, n.pfad, n.name, n, tiefe, extra, unten, true, auf);
  };
  const wurzeln = t.baum.knoten.filter((n) => n.art === "platte");
  const gekuerzt = t.baum.dateien_gekuerzt || t.baum.ordner_gekuerzt;
  $("#es-treffer").innerHTML = `<li class="es-treffer-kopf leise">${zahl(t.gesamt)} übernommene Dateien passen${gekuerzt ? " (gekürzt; Filter enger fassen oder die Liste nehmen)" : ""}</li>`
    + (wurzeln.map((n) => zeichne(n, 0)).join("") || `<li class="leer-hinweis">Nichts gefunden.</li>`);
  auswahlInfo();
}

function filterGeaendert() {
  if (!filterAktiv()) {
    es.treffer = null;
    $("#es-baum").hidden = false;
    $("#es-treffer").hidden = true;
    facettenZeichnen();
    auswahlInfo();
    return;
  }
  sucheLaden();
}
$("#es-q").addEventListener("input", (ev) => {
  es.filter.q = ev.target.value.trim();
  clearTimeout(sucheTakt);
  sucheTakt = setTimeout(filterGeaendert, 300);
});
document.querySelectorAll(".es-nur").forEach((g) => g.addEventListener("click", (ev) => {
  const b = ev.target.closest("[data-nur], [data-ansicht]");
  if (!b) return;
  if (b.dataset.ansicht) { es.filter.ansicht = b.dataset.ansicht; es.trefferZu.clear(); }
  else es.filter.nur = es.filter.nur === "ordner" ? "" : "ordner";   // Schalter „nur Ordner“
  filterGeaendert();
}));
$("#es-facetten").addEventListener("click", (ev) => {
  if (ev.target.closest("#es-facetten-zeigen")) return sucheLaden();
  if (ev.target.closest("#es-filter-weg")) {
    es.filter = { q: "", nur: "", ansicht: es.filter.ansicht };
    $("#es-q").value = "";
    return filterGeaendert();
  }
  const f = ev.target.closest("[data-facette]");
  if (f) { es.filter[f.dataset.facette] = ""; return filterGeaendert(); }
  const s = ev.target.closest("[data-schalter]");
  if (s) { es.filter[s.dataset.schalter] = !es.filter[s.dataset.schalter]; return filterGeaendert(); }
});
$("#es-facetten").addEventListener("change", (ev) => {
  const w = ev.target.closest("[data-facette-wahl]");
  if (w && w.value) { es.filter[w.dataset.facetteWahl] = w.value; filterGeaendert(); }
});

// ======================================================================================================
// Erschließung: Editor
// ======================================================================================================
async function angabenLaden() {
  const ziel = $("#es-editor");
  if (!esZiele().length) {
    ziel.innerHTML = `<div class="leer-hinweis">Links einen übernommenen Ordner oder Dateien wählen.</div>`;
    return;
  }
  ziel.innerHTML = `<div class="leer-hinweis">Lädt …</div>`;
  try {
    es.angaben = await senden("/api/es_angaben", { ziele: esZiele() });
    entwurfSetzen();
    editorZeichnen();
  } catch (err) {
    ziel.innerHTML = `<div class="kartentext fehler">${esc(err.message)}</div>`;
  }
}

// Begriffsfelder aus den gespeicherten Werten (der Editor ändert sie bis zum Speichern nur hier)
function entwurfSetzen() {
  const f = es.angaben.felder;
  const lesen = (e, liste) => { try { return e?.gleich ? JSON.parse(e.gleich) : liste ? [] : null; } catch { return liste ? [] : null; } };
  es.entwurf = { akteur: lesen(f.akteur.eigen), ort: lesen(f.ort.eigen) };
  for (const k of LISTEN) es.entwurf[k] = lesen(f[k]?.eigen, true);
}
// Begriffsfelder mit mehreren Werten: Schlagworte und das Register (Akteur:innen, Orte; Entscheidung 05.11.2026),
// Sprachen (Entscheidung 14.11.2026: aus Balduins Liste, mit ISO-639-2-Code statt Anton-ID)
const LISTEN = ["schlagworte", "akteure", "orte", "sprachen"];
const istListe = (feld) => LISTEN.includes(feld);
const BEGRIFF_ICON = { akteur: "user", akteure: "user", ort: "map-pin", orte: "map-pin", schlagworte: "tag", sprachen: "languages" };
const BEGRIFF_SUCHE = { akteur: "Akteur:in", akteure: "Akteur:in", ort: "Ort", orte: "Ort", schlagworte: "Schlagwort", sprachen: "Sprache" };

// ---- Laufzeit wie in Anton: je Seite „ca.“ und Tag · Monat · Jahr (gespeichert als [von, bis, ca_von, ca_bis]) ----
const zeitraumTeile = (gleich) => {
  try {
    const w = JSON.parse(gleich);
    return [w[0] || "", w[1] || "", !!w[2], w.length > 3 ? !!w[3] : !!w[2]];
  } catch { return ["", "", false, false]; }
};
// „TT.MM.JJJJ“, „MM.JJJJ“, „JJJJ“ (auch ISO) → [Tag, Monat, Jahr] als Text
function datumTeile(text) {
  const iso = /^(\d{4})-(\d{2})-(\d{2})/.exec(text || "");
  if (iso) return [iso[3], iso[2], iso[1]];
  const t = (text || "").split(".").map((x) => x.trim());
  return t.length === 3 ? t : t.length === 2 ? ["", t[0], t[1]] : ["", "", t[0] || ""];
}
// [Tag, Monat, Jahr] → Text und ob gültig (leere Teile und 0 gelten als unbekannt, wie in Anton)
function datumAus(tag, monat, jahr) {
  const z = (x) => (x && Number(x) ? String(Number(x)).padStart(2, "0") : "");
  const [t, m, j] = [z(tag), z(monat), (jahr || "").trim()];
  if (!t && !m && !j) return { text: "", ok: true, leer: true };
  const ok = /^\d{4}$/.test(j) && (!m || Number(m) <= 12) && (!t || (m && Number(t) <= 31)) && !/\D/.test((tag || "") + (monat || ""));
  return { text: [t, m, j].filter(Boolean).join("."), ok, leer: false };
}
const vergleichbar = (text) => { const [t, m, j] = datumTeile(text); return `${j.padStart(4, "0")}${(m || "0").padStart(2, "0")}${(t || "0").padStart(2, "0")}`; };
function zeitraumLesen() {
  const wert = (id) => $("#" + id)?.value || "";
  const von = datumAus(wert("es-von-t"), wert("es-von-m"), wert("es-von-j"));
  const bis = datumAus(wert("es-bis-t"), wert("es-bis-m"), wert("es-bis-j"));
  const caVon = !!$("#es-ca-von")?.checked, caBis = !!$("#es-ca-bis")?.checked;
  const reihenfolge = von.leer || bis.leer || vergleichbar(von.text) <= vergleichbar(bis.text);
  return { von: von.text, bis: bis.text, caVon, caBis, leer: von.leer && bis.leer,
           ok: von.ok && bis.ok && !von.leer && reihenfolge,
           fehler: von.leer && !bis.leer ? "Anfang fehlt" : !von.ok || !bis.ok ? "Datum nicht lesbar (Jahr vierstellig, Monat bis 12)" : !reihenfolge ? "Ende liegt vor dem Anfang" : "" };
}
function zeitraumSetzen(von, bis, caVon, caBis) {
  const [vt, vm, vj] = datumTeile(von), [bt, bm, bj] = datumTeile(bis);
  for (const [id, w] of [["es-von-t", vt], ["es-von-m", vm], ["es-von-j", vj], ["es-bis-t", bt], ["es-bis-m", bm], ["es-bis-j", bj]]) if ($("#" + id)) $("#" + id).value = w;
  if ($("#es-ca-von")) $("#es-ca-von").checked = !!caVon;
  if ($("#es-ca-bis")) $("#es-ca-bis").checked = !!caBis;
}
function datumFelder(seite, text, ca) {
  const [t, m, j] = datumTeile(text);
  const frei = seite === "bis" ? " data-freiwillig" : "";   // Pflicht ist nur „von“ (kein roter Rahmen um „bis“)
  return `<label class="es-ca"><span>ca.</span><input type="checkbox" id="es-ca-${seite}" ${ca ? "checked" : ""}></label>
    <input class="es-tag" id="es-${seite}-t" value="${esc(t)}" placeholder="T" inputmode="numeric" aria-label="Tag"${frei}>.
    <input class="es-tag" id="es-${seite}-m" value="${esc(m)}" placeholder="M" inputmode="numeric" aria-label="Monat"${frei}>.
    <input class="es-jahr" id="es-${seite}-j" value="${esc(j)}" placeholder="JJJJ" inputmode="numeric" aria-label="Jahr"${frei}>`;
}

// ---- Zustand je Feld: Häkchen (gefüllt und gültig), Warnung (gefüllt, aber nicht gültig), leerer Kreis ----
function feldZustand(feld) {
  const a = es.angaben;
  const text = (id) => ($("#" + id)?.value || "").trim();
  if (feld === "titel") {
    const t = text("es-titel") || (a.art !== "ordner" && a.art !== "platte" ? text("es-titel-je") : "");
    return t ? ["ok", "Titel gesetzt"] : ["leer", "Pflichtfeld: noch leer"];
  }
  if (feld === "zeitraum") {
    const z = zeitraumLesen();
    return z.leer ? ["leer", "Pflichtfeld: noch leer"] : z.ok ? ["ok", "Laufzeit lesbar"] : ["warn", z.fehler];
  }
  if (feld === "inhalt") return text("es-inhalt") ? ["ok", "Beschreibung gesetzt"] : ["leer", "empfohlen, noch leer"];
  if (feld === "akteur") {
    const w = es.entwurf.akteur;
    return !w ? ["leer", "noch leer"] : w.anton_id ? ["ok", `Anton-Eintrag #${w.anton_id}`]
      : ["warn", "Nicht in Anton: Der Import bricht bei unbekannter Akteur:in ab. Erst in Anton anlegen lassen oder einen Anton-Eintrag wählen."];
  }
  if (feld === "ort") {
    const w = es.entwurf.ort;
    return !w ? ["leer", "noch leer"] : w.anton_id ? ["ok", `Anton-Eintrag #${w.anton_id}`] : ["warn", "Nicht in Anton: wie der Import einen unbekannten Ort behandelt, ist noch offen"];
  }
  if (feld === "schlagworte") return es.entwurf.schlagworte.length ? ["ok", `${es.entwurf.schlagworte.length} Schlagworte`] : ["leer", "noch leer"];
  if (feld === "orte") return es.entwurf.orte.length ? ["ok", `${es.entwurf.orte.length} Orte im Register`] : ["leer", "noch leer"];
  if (feld === "akteure") return es.entwurf.akteure.length
    ? ["ok", `${es.entwurf.akteure.length} im Register; gehen als actors[] mit, sobald die Anton-Instanz das Importformat 0.8 liest`]
    : ["leer", "noch leer"];
  if (feld.startsWith("note.")) return text(notizId(feld)) ? ["ok", "gesetzt"] : ["leer", "noch leer"];
  return ["leer", ""];
}
const ZEICHEN = { ok: "check", warn: "triangle-alert", leer: "" };
function zustandKnopf(feld) {
  const [z, text] = feldZustand(feld);
  const f = es.angaben.felder[feld] || { an: !!(es.angaben.anton_felder.find((x) => x.name === feld) || {}).import };
  const grau = z === "ok" && !f.an;                     // gültig, kommt aber mit dem API-Import nicht an
  return `<button type="button" class="es-zustand ${z}${grau ? " grau" : ""}" data-zustand="${feld}" title="${esc(text)}" aria-label="${esc(text)}">${ZEICHEN[z] ? icon(ZEICHEN[z]) : ""}</button>`;
}
function zustandAuffrischen() {
  document.querySelectorAll("#es-editor [data-zustand]").forEach((b) => { b.outerHTML = zustandKnopf(b.dataset.zustand); });
  pflichtstandZeichnen();
}
// Hinweis beim Klick auf das Zeichen: Zustand und wie das Feld nach Anton kommt
function zustandHinweis(knopf) {
  const alt = $("#es-zustand-hinweis");
  const feld = knopf.dataset.zustand;
  if (alt) { alt.remove(); if (alt.dataset.feld === feld) return; }
  const [z, text] = feldZustand(feld);
  const f = es.angaben.felder[feld] || { an: false, import: "Notizfeld; ankommen tut es nur, wenn es einen Wert hat (nach dem Speichern genauer)" };
  const div = document.createElement("div");
  div.id = "es-zustand-hinweis";
  div.className = "es-zustand-hinweis";
  div.dataset.feld = feld;
  div.innerHTML = `<div class="es-zh-kopf ${z}">${icon(z === "ok" ? "circle-check" : z === "warn" ? "triangle-alert" : "circle-dashed")} ${esc(text)}</div>
    <div>${icon(f.an ? "arrow-right" : "info")} Nach Anton: ${esc(f.import)}</div>`;
  knopf.closest(".es-zeile").appendChild(div);
}

// ---- Schlagworte als bunte Clips: Farbton fest aus dem Namen (gleicher Begriff, gleiche Farbe) ----
function farbton(name) {
  let h = 0;
  for (const z of (name || "").toLowerCase()) h = (h * 31 + z.codePointAt(0)) % 3600;
  return Math.round(h / 10);
}

// Wert aus einem Ordner darüber (wirkt nicht mehr von selbst; Entscheidung 04.11.2026): Hinweis mit „übernehmen“
function darueberText(feld) {
  const f = es.angaben.felder[feld];
  if (!f?.geerbt || !es.angaben.einzeln) return "";
  const kurz = (f.geerbt.text || "").length > 60 ? f.geerbt.text.slice(0, 57) + " …" : f.geerbt.text || "";
  return `<div class="es-geerbt"><button type="button" class="knopf-leise es-erben" data-darueber="${feld}"
    title="aus ${esc(f.geerbt.ort ? "Ordner „" + f.geerbt.ort.split("/").pop() + "“" : "dem Datenträger")}; danach Speichern">${icon("arrow-up-left")}
    Wert „${esc(kurz)}“ aus übergeordneter Einheit erben</button></div>`;
}
function beispiele(f) {
  const liste = (f.beispiele || []).filter((b) => b.wert);
  return !es.angaben.einzeln && liste.length
    ? `<div class="es-beispiele leise">${liste.map((b) => `<span>${esc(b.name)} → ${esc(b.wert)}</span>`).join("")}</div>` : "";
}

// Vorschläge eines Felds als Chips: ✓ übernehmen (ins Feld, gespeichert mit „Speichern“), ✗ verwerfen (sofort)
function vorschlaegeHtml(feld) {
  const liste = es.angaben.vorschlaege?.[feld] || [];
  if (!liste.length) return "";
  return `<div class="es-vorschlaege">${liste.map((v, i) => {
    const beleg = v.belege.filter(Boolean).join(" · ");
    const anton = v.anton_id ? `Anton #${v.anton_id}` : BEGRIFF_ICON[feld] ? "nicht in Anton" : "";
    const an = v.angenommen || es.angenommen.has(feld + "|" + v.wert);
    return `<span class="es-vorschlag${an ? " angenommen" : ""}${!v.anton_id && anton ? " neu" : ""}" title="${esc(beleg)}">
      <span class="es-vorschlag-wert">${esc(v.anzeige)}</span>
      <span class="leise">${esc([...new Set(v.quellen)].join(" + "))}${anton ? " · " + anton : ""} · ${v.score.toFixed(2).replace(".", ",")}</span>
      <button type="button" class="knopf-mini" data-vorschlag="${feld}|${i}" title="übernehmen">${icon("check")}</button>
      ${es.angaben.einzeln ? `<button type="button" class="knopf-mini" data-verwerfen="${feld}|${i}" title="verwerfen (kommt nicht wieder)">${icon("x")}</button>` : ""}</span>`;
  }).join("")}</div>`;
}

function begriffHtml(feld) {
  const f = es.angaben.felder[feld];
  const werte = istListe(feld) ? es.entwurf[feld] : es.entwurf[feld] ? [es.entwurf[feld]] : [];
  const chips = werte.map((w, i) => `<span class="es-begriff${w.anton_id || w.code ? "" : " neu"}${feld === "schlagworte" ? " bunt" : ""}"${feld === "schlagworte" ? ` style="--ton:${farbton(w.name)}"` : ""}>${icon(BEGRIFF_ICON[feld])}
    ${esc(w.name)} <span class="leise">${w.code ? esc(w.code) : w.anton_id ? "#" + w.anton_id : "neu"}</span>
    <button type="button" class="knopf-mini" data-begriff-weg="${feld}|${i}" title="entfernen">${icon("x")}</button></span>`).join("");
  const darfMehr = istListe(feld) || !es.entwurf[feld];
  return `${chips ? `<div class="es-begriffe">${chips}</div>` : ""}
    ${darfMehr ? `<div class="es-begriff-suche"><input data-begriff-suche="${feld}" data-art="${f.anton}" placeholder="${BEGRIFF_SUCHE[feld]}${f.anton === "language" ? "" : " in Anton"} suchen …" autocomplete="off" spellcheck="false">
      <ul class="es-begriff-treffer" data-begriff-liste="${feld}" hidden></ul></div>` : ""}`;
}

// Eine Zeile wie in der Bearbeitungsmaske von Anton: Bezeichnung links, Eingabe rechts, Zeichen und Vererben ganz rechts
function zeile(feld, bez, inhalt, { pflicht = false, nurAnzeige = false, unter = false } = {}) {
  const a = es.angaben;
  const vererbbar = !nurAnzeige && a.einzeln && a.art !== "datei";
  return `<div class="es-zeile${nurAnzeige ? " anzeige" : ""}${unter ? " unter" : ""}"${feld ? ` data-feld="${feld}"` : ""}>
    <div class="es-bez">${esc(bez)}${pflicht ? PFLICHT : ""}</div>
    <div class="es-wert">${inhalt}</div>
    <div class="es-rand">${feld && !nurAnzeige ? zustandKnopf(feld) : ""}
      ${vererbbar ? `<button type="button" class="knopf-mini es-vererben-knopf" data-vererben="${feld}" title="An Dateien und Unterordner darunter vererben …">${icon("corner-down-right")}</button>` : ""}</div>
  </div>`;
}

// Fundort eines Elements: Datei/Ordner auf der Platte zeigen; fehlt die Platte, welche anzuschließen ist
function plattenHinweis(platte) {
  const p = es.platten.find((x) => x.id === platte) || {};
  return `Zum Zeigen Datenträger ${platte}${p.volume ? ` („${p.volume}“)` : ""} anschließen${p.etikett ? `, Etikett: ${p.etikett.split("\n")[0]}` : ""}.`;
}
async function fundortPruefen(platte, pfad, knopf, hinweis) {
  let q;
  try { q = await holen("/api/quelle", { platte, pfad }); } catch (err) { q = { grund: err.message }; }
  if (!knopf.isConnected) return;
  knopf.disabled = !!q.grund;
  knopf.title = q.grund || `auf dem Datenträger im ${systemwort("dateimanager")} zeigen (nichts wird geöffnet)`;
  hinweis.textContent = !q.grund ? "" : /nicht angeschlossen/.test(q.grund) ? plattenHinweis(platte) : q.grund;
}
async function fundortZeigen(platte, pfad, hinweis) {
  try { await senden("/api/zeigen", { platte, pfad }); } catch (err) { hinweis.textContent = err.message; }
}

function editorZeichnen() {
  const a = es.angaben;
  const f = a.felder;
  const ordner = a.einzeln && a.art !== "datei";
  const [von, bis, caVon, caBis] = zeitraumTeile(f.zeitraum.eigen?.gleich);
  const bestes = a.zeitraum ? (a.zeitraum[0] === a.zeitraum[1] ? tag(a.zeitraum[0]) : `${tag(a.zeitraum[0])}–${tag(a.zeitraum[1])}`) : "";
  const h = a.hinweise;
  const hinweise = h && (h.eigen || h.darueber.length)
    ? `<div class="es-hinweise">${icon("info")} <b>Erschließungshinweise</b>
        ${h.eigen ? `<div>hier: ${esc(h.eigen.hinweis)}</div>` : ""}
        ${h.darueber.map((x) => `<div><span class="leise">${esc(x.pfad || "Datenträger")}:</span> ${esc(x.hinweis)}</div>`).join("")}</div>` : "";
  const kannLlm = a.einzeln && (a.art === "ordner" || (a.art === "datei" && a.dokumente));
  const llmKnopf = kannLlm ? `<button type="button" class="knopf-leise es-llm" data-llm>${icon("sparkles")} Vorschlag vom Sprachmodell</button>` : "";
  const verwandte = a.verwandte?.length
    ? `<div><span class="leise">Verwandte</span> ${a.verwandte.slice(0, 3).map((v) => `${esc(v.platte)} „${esc(v.name)}“ <span class="leise">(${esc(v.gruende.map((g) => GRUND[g.grund] || g.grund).join(", "))})</span>`).join(", ")}
        ${a.verwandte.length > 3 ? ` … ${zahl(a.verwandte.length)} Fundorte` : ""} <button type="button" class="knopf-mini knopf-text" data-verwandte>abgleichen …</button></div>` : "";
  const keinVorlauf = !Object.keys(a.vorlauf || {}).length;
  const mehrere = a.sujet_fotos > 1;
  const sujet = a.sujet?.length ? `<div class="es-sujet-zeile">${icon("image")} <span class="leise">Bildinhalt (Sujet, nur Hilfe; Vorschläge oben übernehmen${mehrere ? `; Anteil der ${zahl(a.sujet_fotos)} Fotos` : ""}):</span>
      ${a.sujet.map((s) => `<span class="es-sujet" title="${mehrere ? "Anteil" : "Score"} ${mehrere ? Math.round(100 * s[1]) + " %" : s[1].toFixed(2).replace(".", ",")}">${esc(s[0])}</span>`).join(" ")}</div>` : "";
  const fundort = a.einzeln ? `<div class="es-fundort"><span class="leise">${esc(a.ziele[0].platte)}${a.ziele[0].pfad ? " / " + esc(a.ziele[0].pfad) : ""}</span>
      <button type="button" class="knopf-mini knopf-text" id="es-fundort-knopf" disabled>${icon("folder-search")} ${{ datei: "Datei", ordner: "Ordner", platte: "Datenträger" }[a.art] || ""} zeigen</button>
      <span id="es-fundort-hinweis" class="leise"></span></div>` : "";
  // Titel: beim Ordner der Titel des Ordners und der Zusatz je Datei fürs Vererben; bei Mehrfachauswahl je Datei
  const jeTeil = ordner || !a.einzeln;
  const titel = `<input id="es-titel" value="${esc(f.titel.eigen?.gleich || "")}" placeholder="${a.einzeln ? "" : `für alle ${zahl(a.ziele.length)} gleich`}">
    ${jeTeil ? `<div class="es-je"><label>${ordner ? "Zusatz je Datei beim Vererben" : "Zusatz je Datei"}<input id="es-titel-je" value="${esc(f.titel.eigen?.je_datei || "")}" placeholder="z. B. – Nr. {laufnummer}"${ordner ? " data-freiwillig" : ""}></label>
      <span class="es-bausteine leise">${["{laufnummer}", "{datum}", "{dateiname}"].map((b) => `<button type="button" class="knopf-leise" data-baustein="${b}">${b}</button>`).join("")}</span></div>` : ""}
    <div class="es-zeile-fuss">${llmKnopf}</div>
    ${vorschlaegeHtml("titel")}${darueberText("titel")}${beispiele(f.titel)}`;
  // Laufzeit wie in Anton; bei Mehrfachauswahl gilt die Eingabe für alle, „je Eintrag das beste Datum“ nur als
  // Batch-Aktion mit Rückfrage (Entscheidung 04.11.2026)
  const j = a.datum_je_eintrag;
  const modus = !a.einzeln && j.mit ? `<div class="es-zeile-fuss"><button type="button" class="knopf-leise" id="es-bestes-batch">${icon("calendar")}
      Bestes Datum je Eintrag …</button><span class="leise">${zahl(j.mit)} von ${zahl(j.von)} haben eines</span></div>` : "";
  const bestesChip = a.einzeln && bestes ? `<div class="es-vorschlaege"><span class="es-vorschlag${es.bestesAn ? " angenommen" : ""}"><span class="es-vorschlag-wert">${esc(bestes)}</span>
        <span class="leise">bestes Datum${ordner ? " der Dateien" : ""} (Metadaten)</span><button type="button" class="knopf-mini" id="es-zeitraum-vorschlag" title="übernehmen">${icon("check")}</button></span></div>` : "";
  const laufzeit = `<div class="es-laufzeit">${datumFelder("von", von, caVon)}<span class="es-bis">–</span>${datumFelder("bis", bis, caBis)}</div>
    ${!a.einzeln ? `<div class="leise">${f.zeitraum.belegt ? `${zahl(f.zeitraum.belegt)} von ${zahl(a.ziele.length)} haben schon eine Laufzeit; Überschreiben nur nach Rückfrage.` : "Gilt für alle gewählten Einträge."}</div>` : ""}
    ${modus}${bestesChip}${vorschlaegeHtml("zeitraum")}${darueberText("zeitraum")}${beispiele(f.zeitraum)}`;
  const begriffZeile = (feld, bez) => zeile(feld, bez, `${begriffHtml(feld)}${vorschlaegeHtml(feld)}${darueberText(feld)}`);
  const stufe = a.stufe || (ordner ? "entsteht beim Zuordnen (neue Verzeichnungseinheit)" : a.art === "auswahl" ? "je Element" : "");

  $("#es-editor").innerHTML = `
    <div class="kartenkopf es-kopf">
      <div class="es-streifen">${a.bilder.slice(0, 4).map((b, i) => `<button type="button" class="es-bild-knopf" data-bild="${i}" title="${esc(b.name)} · vergrößern">${bild(b.thumb, b.name)}</button>`).join("")}
        ${a.bilder.length > 4 ? `<button type="button" class="es-bild-mehr" data-bild="4" title="alle Vorschaubilder">+${zahl(a.bilder.length - 4)}</button>` : ""}</div>
      <div class="es-kopf-text">
        <h2>${esc(a.name)}</h2>
        <div class="leise">${zahl(a.dateien)} übernommen${a.fotos ? ` · ${zahl(a.fotos)} Fotos` : ""}${a.dokumente ? ` · ${zahl(a.dokumente)} Dokumente` : ""}
          ${bestes ? ` · ${esc(bestes)}` : ""}${a.kameras.length ? ` · ${esc(a.kameras.map((k) => k[0]).join(", "))}` : ""}
          ${a.personen ? ` · ${zahl(a.personen)} mit Personen` : ""}</div>
        ${fundort}
      </div>
    </div>
    <div class="kartentext es-felder">
      ${hinweise}
      <div class="es-kontext">
        ${a.zuordnung ? `<div>${icon("package")} <span class="leise">zugeordnet</span> <b>${esc(a.zuordnung.name)}</b> als ${esc(a.zuordnung.stufe_name)}
            ${a.zuordnung.pfad === a.ziele[0].pfad ? `<button type="button" class="knopf-mini knopf-text" data-loesen>lösen</button>` : `<span class="leise">(über ${esc(a.zuordnung.pfad || "Datenträger")})</span>`}</div>
          ${a.zuordnung.stufe === "item" && a.zuordnung.pfad !== a.ziele[0].pfad ? `<div class="leise">${icon("layers")} Medium des Einzelstücks „${esc(a.zuordnung.pfad.split("/").pop())}“: Titel und Laufzeit kommen vom Ordner, eigene Werte gehen nicht nach Anton.</div>` : ""}` : ""}
        ${!a.einzeln && a.selbst_zugeordnet ? `<div>${icon("package")} <span class="leise">zugeordnet</span> ${zahl(a.selbst_zugeordnet)} von ${zahl(a.ziele.length)} gewählten Elementen
            <button type="button" class="knopf-mini knopf-text" data-loesen-alle title="Zuordnung aller gewählten Elemente lösen, die selbst zugeordnet sind">${icon("unlink")} ${a.selbst_zugeordnet === 1 ? "Zuordnung" : `${zahl(a.selbst_zugeordnet)} Zuordnungen`} lösen</button></div>` : ""}
        ${a.etikett ? `<div><span class="leise">Etikett des Datenträgers</span> „${esc(a.etikett)}“</div>` : ""}
        ${a.kassierte_kopien ? `<div><span class="leise">Kassierte Kopien</span> ${zahl(a.kassierte_kopien)} an anderen Fundorten (nur Kontext)</div>` : ""}
        ${verwandte}
        ${keinVorlauf || !a.einzeln ? `<div class="leise">${keinVorlauf ? "Vorschläge: Der Vorlauf ist noch nicht gelaufen. " : ""}${!a.einzeln ? "Vorschläge erscheinen bei Wahl eines einzelnen Elements." : ""}</div>` : ""}
        ${ordner ? `<div class="leise">${icon("corner-down-right")} Die Angaben gelten für den ${a.art === "platte" ? "Datenträger" : "Ordner"} selbst. An Dateien und Unterordner gehen sie nur über „Vererben“.</div>` : ""}
      </div>

      <div class="es-abschnitt">
        <div class="es-abschnitt-kopf">Identifikation</div>
        ${zeile("", "Signatur", `<span class="leise">vergibt Anton beim Import</span>`, { nurAnzeige: true })}
        ${zeile("titel", "Titel (DE)", titel, { pflicht: true })}
        ${zeile("zeitraum", "Laufzeit", laufzeit, { pflicht: true })}
        ${zeile("akteur", "Akteur:in", `${begriffHtml("akteur")}${vorschlaegeHtml("akteur")}${darueberText("akteur")}`, { unter: true })}
        ${zeile("ort", "Ort", `${begriffHtml("ort")}${vorschlaegeHtml("ort")}${darueberText("ort")}`, { unter: true })}
        ${stufe ? zeile("", "Verzeichnungsstufe", esc(stufe), { nurAnzeige: true }) : ""}
        ${zeile("", "Umfang (Stückzahl)", a.art === "datei" ? "1" : `${zahl(a.dateien)} <span class="leise">übernommene Dateien</span>`, { nurAnzeige: true })}
      </div>
      <div class="es-abschnitt">
        <div class="es-abschnitt-kopf">Inhalt und innere Ordnung</div>
        ${zeile("inhalt", "Form und Inhalt (DE)", `<textarea id="es-inhalt" rows="3" placeholder="Kurz beschreiben, was zu sehen oder zu lesen ist">${esc(f.inhalt.eigen?.gleich || "")}</textarea>
          ${vorschlaegeHtml("inhalt")}${darueberText("inhalt")}${sujet}`)}
        ${begriffZeile("sprachen", "Sprachen")}
      </div>
      <div class="es-abschnitt">
        <div class="es-abschnitt-kopf">Schlagworte</div>
        ${begriffZeile("schlagworte", "Schlagworte")}
        ${begriffZeile("akteure", "Akteur:innen")}
        ${begriffZeile("orte", "Orte")}
      </div>
      ${weitereFelderHtml()}
      <details class="es-abschnitt es-meta" id="es-meta"${es.metaOffen ? " open" : ""}>
        <summary class="es-abschnitt-kopf">Weitere Metadaten <span class="leise" id="es-meta-zahl"></span></summary>
        <div id="es-meta-inhalt"><div class="leer-hinweis">Lädt …</div></div></details>
    </div>
    <div class="es-editor-fuss">
      <span id="es-pflichtstand" class="es-pflichtstand"></span>
      <span id="es-speicher-info" class="leise"></span>
      ${ordner ? `<button type="button" class="knopf-leise" data-vererben="">${icon("corner-down-right")} Vererben …</button>` : ""}
      <button type="button" id="es-verwerfen">Verwerfen</button>
      <button type="button" id="es-speichern" class="haupt">Speichern</button>
    </div>`;
  es.ursprung = formWerte();
  zustandAuffrischen();
  $("#es-meta")?.addEventListener("toggle", (e) => { es.metaOffen = e.target.open; if (e.target.open) metadatenLaden(); });
  if (es.metaOffen) metadatenLaden();
  if (a.einzeln) fundortPruefen(a.ziele[0].platte, a.ziele[0].pfad, $("#es-fundort-knopf"), $("#es-fundort-hinweis"));
}
const GRUND = { duplikate: "gleiche Inhalte", tag_kamera: "gleicher Tag + Kamera", name: "Ordnername" };

// Weitere Anton-Felder (Notizfelder mit festem Namen, Entscheidung 04.11.2026): Felder mit Wert und hinzugefügte
// erscheinen als Zeilen; das Dropdown bietet die übrigen an, die mit dem API-Import ankommenden zuerst
const notizen = () => Object.keys(es.angaben.felder).filter((k) => k.startsWith("note."));
const notizId = (feld) => "es-" + feld.replace(".", "-");
function weitereFelderHtml() {
  const a = es.angaben;
  const da = new Set([...notizen(), ...es.zusatz]);
  const zeilen = [...da].map((feld) => {
    const f = a.felder[feld] || { name: (a.anton_felder.find((x) => x.name === feld) || {}).label || feld };
    const leer = !f.eigen;
    return zeile(feld, f.name, `<textarea id="${notizId(feld)}" data-notiz="${feld}" rows="2">${esc(f.eigen?.gleich || "")}</textarea>
      ${leer ? `<button type="button" class="knopf-mini knopf-text es-notiz-weg" data-notiz-weg="${feld}">Feld wieder ausblenden</button>` : ""}${darueberText(feld)}`);
  }).join("");
  const frei = a.anton_felder.filter((x) => !da.has(x.name));
  const gruppe = (an) => frei.filter((x) => x.import === an).map((x) => `<option value="${esc(x.name)}">${esc(x.label)}</option>`).join("");
  const wahl = a.anton_felder.length
    ? `<select id="es-feld-wahl" aria-label="Weiteres Anton-Feld hinzufügen"><option value="">Weiteres Anton-Feld hinzufügen …</option>
        <optgroup label="kommt mit dem API-Import an">${gruppe(true)}</optgroup>
        <optgroup label="kommt an, sobald Anton den API-Import erweitert">${gruppe(false)}</optgroup></select>`
    : `<button type="button" class="knopf-leise" id="es-felder-holen">${icon("download")} Felder aus Anton holen</button>`;
  return `<div class="es-abschnitt">
      <div class="es-abschnitt-kopf">Weitere Felder</div>
      ${zeilen}
      <div class="es-zeile anzeige"><div class="es-bez"></div><div class="es-wert">${wahl}
        <span class="leise" id="es-felder-info">Notizfelder aus der Anton-Instanz; welche ein Formular zeigt, liefert die API nicht.</span></div><div></div></div>
    </div>`;
}

// Stand unten im Editor: Pflichtfelder der Auswahl und wie viele Dateien erschlossen sind
function pflichtstandZeichnen() {
  const a = es.angaben, ziel = $("#es-pflichtstand");
  if (!ziel) return;
  const fertig = a.erschlossen === a.dateien;
  const ordner = a.einzeln && a.art !== "datei";
  ziel.className = "es-pflichtstand" + (fertig ? " fertig" : "");
  ziel.innerHTML = `${icon(fertig ? "circle-check" : "circle-dashed")}
    ${ordner ? `${a.art === "platte" ? "Datenträger" : "Ordner"} ${a.ordner_erschlossen ? "erschlossen" : "noch offen"} · ` : ""}${zahl(a.erschlossen)} von ${zahl(a.dateien)} Dateien erschlossen${a.zugeordnet ? ` · ${zahl(a.zugeordnet)} zugeordnet` : ""}`;
  ziel.title = "Erschlossen = Titel und Laufzeit gesetzt und gültig; beides sind Pflichtfelder";
}

// ---- Weitere Metadaten (Entscheidung 04.11.2026): was die Dateien noch mitbringen, übernehmbar in ein Feld ----
const META_ZIELE = [["titel", "Titel"], ["inhalt", "Form und Inhalt"], ["akteur", "Akteur:in (Entstehung)"], ["ort", "Ort (Entstehung)"],
  ["schlagworte", "Schlagworte"], ["akteure", "Akteur:innen (Register)"], ["orte", "Orte (Register)"]];
async function metadatenLaden() {
  const ziel = $("#es-meta-inhalt");
  if (!ziel) return;
  const fuer = zieleText(esZiele());
  try {
    const m = await senden("/api/es_metadaten", { ziele: esZiele() });
    if (zieleText(esZiele()) !== fuer || !$("#es-meta-inhalt")) return;
    es.meta = m;
    metadatenZeichnen();
  } catch (err) { ziel.innerHTML = `<div class="fehler">${esc(err.message)}</div>`; }
}
function metadatenZeichnen() {
  const m = es.meta, a = es.angaben;
  $("#es-meta-zahl").textContent = `${zahl(m.angaben.length)} Angaben`;
  if (!m.angaben.length) { $("#es-meta-inhalt").innerHTML = `<div class="kartentext leise">Keine beschreibenden Metadaten in den Dateien.</div>`; return; }
  const ziele = [...META_ZIELE, ...a.anton_felder.map((f) => [f.name, f.label])];
  $("#es-meta-inhalt").innerHTML = m.angaben.map((x, i) => {
    const anteil = a.einzeln && a.art === "datei" ? "" : a.einzeln ? `${zahl(x.dateien)} von ${zahl(m.dateien)} Dateien` : `${zahl(x.elemente)} von ${zahl(m.elemente)} Elementen`;
    return `<div class="es-zeile es-meta-zeile" data-meta="${i}">
      <div class="es-bez">${esc(x.name)}<div class="leise">${esc(x.gruppe)}</div></div>
      <div class="es-wert"><div class="es-meta-werte">${x.werte.map(([w, n], j) => `<label class="es-meta-wert" title="${esc(w)}">
          <input type="radio" name="meta-${i}" value="${j}" ${j ? "" : "checked"}><span>${esc(w.length > 80 ? w.slice(0, 77) + " …" : w)}</span>${x.werte.length > 1 || anteil ? ` <span class="leise">${zahl(n)}</span>` : ""}</label>`).join("")}
          ${x.verschieden > x.werte.length ? `<span class="leise">… ${zahl(x.verschieden - x.werte.length)} weitere Werte</span>` : ""}</div>
        <div class="es-meta-aktion">${anteil ? `<span class="leise">${anteil}</span>` : ""}
          <select data-meta-feld="${i}" aria-label="übernehmen in">${ziele.map(([k, n]) => `<option value="${esc(k)}" ${k === x.feld ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>
          <button type="button" class="knopf-leise" data-meta-uebernehmen="${i}">übernehmen</button></div></div><div></div></div>`;
  }).join("") + (m.gekuerzt ? `<div class="kartentext leise">Gezählt die ersten ${zahl(m.dateien)} Dateien.</div>` : "");
}
async function metadatumUebernehmen(i) {
  const a = es.angaben, x = es.meta.angaben[i];
  const feld = document.querySelector(`[data-meta-feld="${i}"]`).value;
  const wert = x.werte[Number(document.querySelector(`[name="meta-${i}"]:checked`)?.value || 0)][0];
  const art = { akteur: "actor", akteure: "actor", ort: "place", orte: "place", schlagworte: "keyword" }[feld] || "";
  if (a.einzeln) {                                         // ein Element: ins Feld, gespeichert wird mit „Speichern“
    let begriff = { name: wert, anton_id: null };
    if (art) {
      try {
        const r = await holen("/api/es_begriffe", { art, q: wert });
        const gleich = (r.treffer || []).find((t) => t.name.toLowerCase() === wert.toLowerCase());
        if (gleich) begriff = { name: gleich.name, anton_id: gleich.anton_id };
      } catch { /* ohne Anton-Treffer */ }
    }
    if (feld === "titel") $("#es-titel").value = wert;
    else if (feld === "inhalt") $("#es-inhalt").value = wert;
    else if (istListe(feld)) wert.split(/\s*[;,]\s*/).filter(Boolean).forEach((w) => {
      if (!es.entwurf[feld].some((s) => s.name.toLowerCase() === w.toLowerCase())) es.entwurf[feld].push(w === wert ? begriff : { name: w, anton_id: null });
    });
    else if (feld === "akteur" || feld === "ort") es.entwurf[feld] = begriff;
    else { es.zusatz.add(feld); felderBehalten(editorZeichnen); $("#" + notizId(feld)).value = wert; }
    felderBehalten(editorZeichnen);
    $("#es-speicher-info").textContent = `„${x.name}“ übernommen; zum Sichern „Speichern“`;
    return;
  }
  // mehrere: je Element sein eigener Wert oder für alle derselbe; vorhandene Werte nur nach Rückfrage
  const zielName = ([...META_ZIELE, ...a.anton_felder.map((f) => [f.name, f.label])].find(([k]) => k === feld) || [, feld])[1];
  const belegt = a.felder[feld]?.belegt || 0;
  $("#es-frage-titel").textContent = `„${x.name}“ in „${zielName}“ übernehmen`;
  $("#es-frage-inhalt").innerHTML = `
    <div class="es-vb-gruppe"><label><input type="radio" name="meta-modus" value="je" checked> je Element sein eigener Wert
      <span class="leise">(${zahl(x.elemente)} von ${zahl(a.ziele.length)} haben einen; Ordner: der häufigste darin)</span></label></div>
    <div class="es-vb-gruppe"><label><input type="radio" name="meta-modus" value="alle"> für alle: „${esc(wert)}“</label></div>
    ${belegt && !istListe(feld) ? `<div class="es-vb-gruppe"><span class="leise">${zahl(belegt)} haben schon einen Wert</span>
      <label><input type="radio" name="meta-ueber" value="0" checked> nur leere füllen</label>
      <label><input type="radio" name="meta-ueber" value="1"> überschreiben</label></div>` : ""}
    ${istListe(feld) ? `<div class="leise">Werte werden ergänzt, vorhandene bleiben.</div>` : ""}`;
  $("#es-frage-ok").textContent = "Übernehmen";
  const w = await frageDialog(() => ({ modus: document.querySelector('[name="meta-modus"]:checked').value,
                                       nur_leere: document.querySelector('[name="meta-ueber"]:checked')?.value !== "1" }));
  if (!w || !(await offeneSichern())) return;
  try {
    const r = await senden("/api/es_metadaten_uebernehmen", { ziele: esZiele(), schluessel: x.schluessel, feld, wert, ...w });
    await nachAktion();
    $("#es-speicher-info").textContent = `übernommen: ${zahl(r.geschrieben)} Elemente${r.ohne_wert ? `, ${zahl(r.ohne_wert)} ohne Wert` : ""}${r.gelassen ? `, ${zahl(r.gelassen)} behalten` : ""}`;
  } catch (err) { meldung(err.message, "Fehler"); }
}

// Werte des Formulars (für „was hat sich geändert“: gespeichert werden nur geänderte Felder)
function formWerte() {
  const z = zeitraumLesen();
  return {
    titel: JSON.stringify([$("#es-titel")?.value || "", $("#es-titel-je")?.value || ""]),
    zeitraum: JSON.stringify([z.von, z.bis, z.caVon, z.caBis]),
    inhalt: JSON.stringify($("#es-inhalt")?.value || ""),
    akteur: JSON.stringify(es.entwurf.akteur), ort: JSON.stringify(es.entwurf.ort),
    ...Object.fromEntries(LISTEN.map((k) => [k, JSON.stringify(es.entwurf[k])])),
    ...Object.fromEntries([...document.querySelectorAll("#es-editor [data-notiz]")].map((x) => [x.dataset.notiz, JSON.stringify(x.value)])),
  };
}
const geaenderteFelder = () => { const jetzt = formWerte(); return Object.keys(jetzt).filter((k) => jetzt[k] !== es.ursprung?.[k]); };

// Vorschlag übernehmen: ins Feld setzen; gespeichert (und als bestätigt vermerkt) wird mit „Speichern“
function vorschlagUebernehmen(feld, v) {
  // einwertige Felder: ein früher angenommener Vorschlag desselben Felds gilt nicht mehr
  if (!istListe(feld)) for (const k of [...es.angenommen.keys()]) if (k.startsWith(feld + "|")) es.angenommen.delete(k);
  es.angenommen.set(feld + "|" + v.wert, { ...v, ziel: feld });
  if (feld === "titel") $("#es-titel").value = v.wert;
  else if (feld === "inhalt") $("#es-inhalt").value = v.wert;
  else if (feld === "zeitraum") { const [von, bis, cv, cb] = zeitraumTeile(v.wert); zeitraumSetzen(von, bis, cv, cb); es.bestesAn = false; }
  else {
    const wert = { name: v.anzeige, anton_id: v.anton_id || null };
    if (istListe(feld)) {
      if (!es.entwurf[feld].some((x) => (x.anton_id && x.anton_id === wert.anton_id) || x.name === wert.name)) es.entwurf[feld].push(wert);
    } else es.entwurf[feld] = wert;
    felderBehalten(editorZeichnen);
    return;
  }
  felderBehalten(editorZeichnen);                       // zeichnet den angenommenen Vorschlag grün
}

// Mehrfachauswahl: Vorschlag sofort schreiben, bei den Elementen, die ihn haben, oder bei allen (fünfte Runde)
async function vorschlagMehrere(feld, v) {
  const a = es.angaben, n = a.ziele.length, einwertig = !istListe(feld);
  const belegt = einwertig ? a.felder[feld]?.belegt || 0 : 0;
  $("#es-frage-titel").textContent = `„${v.anzeige}“ übernehmen`;
  $("#es-frage-inhalt").innerHTML = `
    <div class="es-vb-gruppe"><span class="leise">${esc(feldName(feld))}</span>
      <label><input type="radio" name="vm-modus" value="mit" checked> nur bei den ${zahl(v.anzahl || 0)} Elementen, die ihn als Vorschlag haben</label>
      <label><input type="radio" name="vm-modus" value="alle"> bei allen ${zahl(n)} gewählten</label></div>
    ${belegt ? `<div class="es-vb-gruppe"><span class="leise">${zahl(belegt)} haben schon einen Wert</span>
      <label><input type="radio" name="vm-ueber" value="0" checked> nur leere füllen</label>
      <label><input type="radio" name="vm-ueber" value="1"> überschreiben</label></div>` : ""}
    <div class="leise">${einwertig ? "" : "Werte werden ergänzt, vorhandene bleiben. "}Wird sofort gespeichert${geaenderteFelder().length ? ", zusammen mit den offenen Eingaben" : ""}.</div>`;
  $("#es-frage-ok").textContent = "Übernehmen";
  const w = await frageDialog(() => ({ modus: document.querySelector('[name="vm-modus"]:checked').value,
                                       ueberschreiben: document.querySelector('[name="vm-ueber"]:checked')?.value === "1" }));
  if (!w || !(await offeneSichern())) return;
  try {
    const r = await senden("/api/es_vorschlag_mehrere", { ziele: a.ziele, feld, ...w,
      vorschlag: { feld: v.feld, wert: v.wert, anzeige: v.anzeige, anton_id: v.anton_id, quellen: v.quellen } });
    es.angenommen.set(feld + "|" + v.wert, { ...v, ziel: feld });
    await nachAktion();
    $("#es-speicher-info").textContent = `„${v.anzeige}“ übernommen: ${zahl(r.geschrieben)} Elemente`
      + `${r.schon ? `, ${zahl(r.schon)} hatten ihn schon` : ""}${r.gelassen ? `, ${zahl(r.gelassen)} behalten` : ""}`;
  } catch (err) { meldung(err.message, "Fehler"); }
}

// Neuzeichnen, ohne Getipptes zu verlieren (der Vergleichsstand für „geändert“ bleibt der alte)
function felderBehalten(zeichnen) {
  const ids = ["es-titel", "es-titel-je", "es-von-t", "es-von-m", "es-von-j", "es-bis-t", "es-bis-m", "es-bis-j", "es-inhalt"];
  const werte = Object.fromEntries(ids.map((id) => [id, $("#" + id)?.value]));
  const ca = [$("#es-ca-von")?.checked, $("#es-ca-bis")?.checked];
  const notizWerte = [...document.querySelectorAll("#es-editor [data-notiz]")].map((x) => [notizId(x.dataset.notiz), x.value]);
  const ursprung = es.ursprung;
  zeichnen();
  es.ursprung = ursprung;
  for (const [id, w] of notizWerte) if ($("#" + id)) $("#" + id).value = w;
  for (const [id, w] of Object.entries(werte)) if ($("#" + id) && w != null) $("#" + id).value = w;
  if ($("#es-ca-von")) { $("#es-ca-von").checked = ca[0]; $("#es-ca-bis").checked = ca[1]; }
  zustandAuffrischen();
}

$("#es-editor").addEventListener("click", async (ev) => {
  const zk = ev.target.closest("[data-zustand]");
  if (zk) return zustandHinweis(zk);
  if (!ev.target.closest("#es-zustand-hinweis")) $("#es-zustand-hinweis")?.remove();
  const bk = ev.target.closest("[data-bild]");
  if (bk) return bildZeigen(Number(bk.dataset.bild));
  if (ev.target.closest("#es-fundort-knopf")) return fundortZeigen(es.angaben.ziele[0].platte, es.angaben.ziele[0].pfad, $("#es-fundort-hinweis"));
  const vk0 = ev.target.closest("[data-vererben]");
  if (vk0) return vererbenOeffnen(vk0.dataset.vererben);
  const baustein = ev.target.closest("[data-baustein]");
  if (baustein) {
    const feld = $("#es-titel-je");
    feld.value = (feld.value ? feld.value + " " : "") + baustein.dataset.baustein;
    return feld.focus();
  }
  if (ev.target.closest("#es-zeitraum-vorschlag")) {
    const z = es.angaben.zeitraum;
    zeitraumSetzen(z[0], z[1] !== z[0] ? z[1] : "", false, false);   // ein Tag: nur der Anfang (kein Ende nötig)
    for (const k of [...es.angenommen.keys()]) if (k.startsWith("zeitraum|")) es.angenommen.delete(k);
    es.bestesAn = true;
    return felderBehalten(editorZeichnen);
  }
  if (ev.target.closest("#es-bestes-batch")) return bestesBatch();
  const mu = ev.target.closest("[data-meta-uebernehmen]");
  if (mu) return metadatumUebernehmen(Number(mu.dataset.metaUebernehmen));
  const dr = ev.target.closest("[data-darueber]");
  if (dr) {                                              // Wert des Ordners darüber in dieses Feld übernehmen
    const feld = dr.dataset.darueber, g = es.angaben.felder[feld].geerbt;
    if (feld === "titel") $("#es-titel").value = g.gleich || "";
    else if (feld === "inhalt") $("#es-inhalt").value = g.gleich || "";
    else if (feld.startsWith("note.")) $("#" + notizId(feld)).value = g.gleich || "";
    else if (feld === "zeitraum") { const [von, bis, cv, cb] = zeitraumTeile(g.gleich); zeitraumSetzen(von, bis, cv, cb); }
    else { try { es.entwurf[feld] = JSON.parse(g.gleich); } catch { /* ungültig */ } return felderBehalten(editorZeichnen); }
    return zustandAuffrischen();
  }
  const vk = ev.target.closest("[data-vorschlag]");
  if (vk) {
    const [feld, i] = vk.dataset.vorschlag.split("|");
    const v = es.angaben.vorschlaege[feld][Number(i)];
    return es.angaben.einzeln ? vorschlagUebernehmen(feld, v) : vorschlagMehrere(feld, v);
  }
  const vw = ev.target.closest("[data-verwerfen]");
  if (vw) {
    const [feld, i] = vw.dataset.verwerfen.split("|");
    const v = es.angaben.vorschlaege[feld][Number(i)];
    const z = es.angaben.ziele[0];
    try {
      await senden("/api/es_verwerfen", { ...z, vorschlag: { feld: v.feld, wert: v.wert, anton_id: v.anton_id, beleg: v.belege[0] } });
      es.angaben.vorschlaege[feld].splice(Number(i), 1);
      felderBehalten(editorZeichnen);
    } catch (err) { meldung(err.message, "Fehler"); }
    return;
  }
  const weg = ev.target.closest("[data-begriff-weg]");
  if (weg) {
    const [feld, i] = weg.dataset.begriffWeg.split("|");
    if (istListe(feld)) es.entwurf[feld].splice(Number(i), 1);
    else es.entwurf[feld] = null;
    return felderBehalten(editorZeichnen);
  }
  const treffer = ev.target.closest("[data-begriff-wahl]");
  if (treffer) {
    const feld = treffer.closest("[data-begriff-liste]").dataset.begriffListe;
    const wert = JSON.parse(treffer.dataset.begriffWahl);
    if (istListe(feld)) { if (!es.entwurf[feld].some((x) => x.name === wert.name)) es.entwurf[feld].push(wert); }
    else es.entwurf[feld] = wert;
    return felderBehalten(editorZeichnen);
  }
  if (ev.target.closest("[data-llm]")) return sprachmodellFragen(ev.target.closest("[data-llm]"));
  if (ev.target.closest("[data-verwandte]")) return verwandteDialog(es.angaben.verwandte, es.angaben.ziele[0], false);
  if (ev.target.closest("[data-loesen]")) {
    const z = es.angaben.ziele[0];
    try { await senden("/api/es_zuordnung_loesen", z); await nachAktion(); } catch (err) { meldung(err.message, "Fehler"); }
    return;
  }
  if (ev.target.closest("[data-loesen-alle]")) {         // Mehrfachauswahl: alle eigenen Zuordnungen auf einmal
    const ziele = es.angaben.ziele.map((z) => ({ platte: z.platte, pfad: z.pfad }));
    try {
      const r = await senden("/api/es_zuordnung_loesen", { ziele });
      await nachAktion();
      $("#es-speicher-info").textContent = `gelöst: ${zahl(r.geloest)} Zuordnungen`;
    } catch (err) { meldung(err.message, "Fehler"); }
    return;
  }
  const nw = ev.target.closest("[data-notiz-weg]");
  if (nw) { es.zusatz.delete(nw.dataset.notizWeg); return felderBehalten(editorZeichnen); }
  if (ev.target.closest("#es-felder-holen")) {
    $("#es-felder-info").textContent = "wird aus Anton geholt …";
    const r = await holen("/api/es_felder", { neu: 1 }).catch((err) => ({ felder: [], fehler: err.message }));
    if (!r.felder.length) { $("#es-felder-info").textContent = r.fehler || "Anton lieferte keine Felder."; return; }
    es.angaben.anton_felder = r.felder;
    return felderBehalten(editorZeichnen);
  }
  if (ev.target.closest("#es-verwerfen")) { es.angenommen.clear(); es.bestesAn = false; entwurfSetzen(); return editorZeichnen(); }
  if (ev.target.closest("#es-speichern")) return speichern();
});

// Begriffe in Anton suchen (zwischengespeichertes Vokabular), mit kurzer Verzögerung; sonst Zeichen nachführen
let begriffTakt = null;
$("#es-editor").addEventListener("input", (ev) => {
  const feld = ev.target.closest("[data-begriff-suche]");
  if (!feld) return zustandAuffrischen();
  clearTimeout(begriffTakt);
  begriffTakt = setTimeout(async () => {
    const liste = document.querySelector(`[data-begriff-liste="${feld.dataset.begriffSuche}"]`);
    const q = feld.value.trim();
    if (!q) { liste.hidden = true; return; }
    try {
      const r = await holen("/api/es_begriffe", { art: feld.dataset.art, q });
      const neu = { name: q, anton_id: null };
      if (feld.dataset.art === "language") {           // Sprachen nur aus der Liste, nie neu
        liste.innerHTML = r.treffer.map((t) => `<li><button type="button" data-begriff-wahl="${esc(JSON.stringify({ name: t.name, code: t.code }))}">
            ${esc(t.name)} <span class="leise">${esc(t.code)}</span></button></li>`).join("") || `<li class="leise">Keine Sprache gefunden.</li>`;
        liste.hidden = false;
        return;
      }
      liste.innerHTML = (r.vokabular ? r.treffer.map((t) => `<li><button type="button" data-begriff-wahl="${esc(JSON.stringify({ name: t.name, anton_id: t.anton_id }))}">
          ${esc(t.name)} <span class="leise">${esc(t.typ || "")} · #${t.anton_id}</span></button></li>`).join("")
          : `<li class="leise">Anton-Vokabular noch nicht geholt (Vorlauf: Normdaten abgleichen).</li>`)
        + `<li><button type="button" data-begriff-wahl="${esc(JSON.stringify(neu))}">„${esc(q)}“ als neu <span class="leise">(entsteht erst im Import)</span></button></li>`;
      liste.hidden = false;
    } catch (err) { liste.innerHTML = `<li class="fehler">${esc(err.message)}</li>`; liste.hidden = false; }
  }, 250);
});
$("#es-editor").addEventListener("change", (ev) => {
  if (ev.target.id === "es-feld-wahl" && ev.target.value) {        // weiteres Anton-Feld als Zeile zeigen
    es.zusatz.add(ev.target.value);
    const id = notizId(ev.target.value);
    felderBehalten(editorZeichnen);
    return $("#" + id)?.focus();
  }
  if (ev.target.matches("input[type=checkbox], select")) zustandAuffrischen();
});

// Speichern: nur geänderte Felder (bei Mehrfachauswahl bleiben unberührte Felder der einzelnen Elemente erhalten).
// still: ohne Abgleich-Dialog und ohne Neuaufbau (vor dem Vererben)
async function speichern({ still = false, loesen = !still } = {}) {
  const knopf = $("#es-speichern");
  const geaendert = geaenderteFelder();
  if (!geaendert.length) { if (!still) $("#es-speicher-info").textContent = "nichts geändert"; return { geaendert: 0 }; }
  const z = zeitraumLesen();
  if (geaendert.includes("zeitraum") && !z.leer && !z.ok) {
    const text = `Laufzeit: ${z.fehler}`;
    $("#es-speicher-info").textContent = text;
    if (still) throw new Error(text);
    return null;
  }
  knopf.disabled = true;
  try {
    const alle = {
      titel: { gleich: $("#es-titel").value, je_datei: $("#es-titel-je")?.value || "" },
      zeitraum: { gleich: [z.von, z.bis, z.caVon, z.caBis], je_datei: es.angaben.felder.zeitraum.eigen?.je_datei || "" },
      inhalt: { gleich: $("#es-inhalt").value },
      akteur: { gleich: es.entwurf.akteur },
      ort: { gleich: es.entwurf.ort },
      ...Object.fromEntries(LISTEN.map((k) => [k, { gleich: es.entwurf[k] }])),
      ...Object.fromEntries([...document.querySelectorAll("#es-editor [data-notiz]")].map((x) => [x.dataset.notiz, { gleich: x.value }])),
    };
    const felder = Object.fromEntries(geaendert.filter((k) => alle[k]).map((k) => [k, alle[k]]));
    // übernommene Vorschläge, die noch im Feld stehen: Quelle mitgeben und als bestätigt vermerken
    const angenommen = [];
    for (const v of es.angenommen.values()) {
      const feld = v.ziel || { schlagwort: "schlagworte" }[v.feld] || v.feld;
      const noch = feld === "titel" ? alle.titel.gleich === v.wert : feld === "inhalt" ? alle.inhalt.gleich === v.wert
        : feld === "zeitraum" ? (() => { const [a, b] = zeitraumTeile(v.wert); return a === z.von && b === z.bis; })()
        : istListe(feld) ? es.entwurf[feld].some((x) => x.name === v.anzeige)
        : es.entwurf[feld]?.name === v.anzeige;
      if (!noch) continue;
      angenommen.push({ feld: v.feld, wert: v.wert, anton_id: v.anton_id, beleg: v.belege[0] });
      if (felder[feld] && !felder[feld].quelle) felder[feld].quelle = "Vorschlag: " + [...new Set(v.quellen)].join(" + ");
    }
    const ziele = es.angaben.ziele.map((z) => ({ platte: z.platte, pfad: z.pfad }));   // die Elemente im Editor
    // Mehrfachauswahl: Felder, die bei gewählten Elementen schon einen Wert haben, nur nach Rückfrage überschreiben
    let nur_leere = [];
    const belegt = es.angaben.einzeln ? [] : Object.keys(felder).filter((k) => es.angaben.felder[k]?.belegt);
    if (belegt.length) {
      const wahl = await ueberschreibenFragen(belegt);
      if (!wahl) { knopf.disabled = false; $("#es-speicher-info").textContent = "nicht gespeichert"; return null; }
      nur_leere = wahl;
    }
    const r = await senden("/api/es_speichern", { ziele, felder, angenommen, nur_leere });
    if (loesen) auswahlNachAktion();
    es.angenommen.clear();
    es.bestesAn = false;
    if (still) { es.ursprung = formWerte(); knopf.disabled = false; return r; }
    await erschliessungZeigen();
    $("#es-speicher-info").textContent = r.geaendert ? `gespeichert (${r.geaendert} Änderungen)` : "nichts geändert";
    if (r.verwandte?.length) verwandteDialog(r.verwandte, ziele[0], true);
    return r;
  } catch (err) {
    knopf.disabled = false;
    if (still) throw err;
    meldung(err.message, "Fehler");
    return null;
  }
}

// Rückfrage je Feld: überschreiben oder nur leere füllen. Antwort: Liste der Felder „nur leere“ oder null (abgebrochen)
function ueberschreibenFragen(felder) {
  const a = es.angaben, n = a.ziele.length;
  $("#es-frage-titel").textContent = "Vorhandene Werte überschreiben?";
  $("#es-frage-inhalt").innerHTML = `<p class="dialog-text">Einige der ${zahl(n)} gewählten Elemente haben in diesen Feldern schon einen eigenen Wert.</p>
    ${felder.map((k) => `<div class="es-vb-gruppe"><span><b>${esc(a.felder[k].name)}</b><br><span class="leise">${zahl(a.felder[k].belegt)} von ${zahl(n)} belegt</span></span>
      <label><input type="radio" name="ue-${esc(k)}" value="leer" checked> nur leere füllen</label>
      <label><input type="radio" name="ue-${esc(k)}" value="ueber"> überschreiben</label></div>`).join("")}`;
  $("#es-frage-ok").textContent = "Speichern";
  return frageDialog(() => felder.filter((k) => document.querySelector(`[name="ue-${CSS.escape(k)}"]:checked`)?.value !== "ueber"));
}
// Allgemeiner Rückfrage-Dialog: auswerten() liefert beim Bestätigen die Antwort, Abbrechen ergibt null
function frageDialog(auswerten) {
  return new Promise((fertig) => {
    const dlg = $("#es-frage-dialog");
    const zu = (wert) => { dlg.close(); $("#es-frage-ok").onclick = $("#es-frage-abbrechen").onclick = dlg.oncancel = null; fertig(wert); };
    $("#es-frage-ok").onclick = (ev) => { ev.preventDefault(); zu(auswerten()); };
    $("#es-frage-abbrechen").onclick = () => zu(null);
    dlg.oncancel = () => zu(null);
    dlg.showModal();
  });
}

// Batch: jedem gewählten Eintrag sein eigenes bestes Datum (Datei: Aufnahmedatum, Ordner: frühestes–spätestes)
async function bestesBatch() {
  const a = es.angaben, j = a.datum_je_eintrag, belegt = a.felder.zeitraum.belegt;
  $("#es-frage-titel").textContent = "Bestes Datum je Eintrag";
  $("#es-frage-inhalt").innerHTML = `<p class="dialog-text">Jeder der ${zahl(j.von)} gewählten Einträge bekommt sein eigenes bestes Datum
      aus den Metadaten (Datei: Aufnahmedatum; Ordner: frühestes bis spätestes Datum darin).</p>
    <ul class="dialog-text"><li>${zahl(j.mit)} haben ein Datum und werden gesetzt.</li>
      ${j.mit < j.von ? `<li>${zahl(j.von - j.mit)} haben keines und bleiben unverändert.</li>` : ""}</ul>
    ${belegt ? `<label class="es-vb-gruppe"><input type="checkbox" id="es-bestes-ueber"> ${zahl(belegt)} haben schon eine Laufzeit: überschreiben</label>` : ""}`;
  $("#es-frage-ok").textContent = "Setzen";
  const wahl = await frageDialog(() => ({ ueber: !!$("#es-bestes-ueber")?.checked }));
  if (!wahl || !(await offeneSichern())) return;
  try {
    const r = await senden("/api/es_speichern", { ziele: esZiele(), nur_leere: wahl.ueber ? [] : ["zeitraum"],
      felder: { zeitraum: { gleich: ["", "", false, false], je_eintrag: true, quelle: "Metadaten: bestes Datum je Eintrag" } } });
    await nachAktion();
    $("#es-speicher-info").textContent = `gespeichert; bestes Datum gesetzt: ${zahl(r.geaendert)} Einträge`;
  } catch (err) { meldung(err.message, "Fehler"); }
}

// ---- Vererben (Entscheidung 04.11.2026): Werte des Ordners an Dateien und Unterordner darunter ----
const FELD_NAMEN = [["titel", "Titel"], ["zeitraum", "Laufzeit"], ["akteur", "Akteur:in (Entstehung)"], ["ort", "Ort (Entstehung)"], ["inhalt", "Form und Inhalt"],
  ["schlagworte", "Schlagworte"], ["akteure", "Akteur:innen (Register)"], ["orte", "Orte (Register)"]];
let vbQuelle = null;
async function vererbenOeffnen(feld) {
  vbQuelle = { ...es.angaben.ziele[0] };
  try { await speichern({ still: true }); }                 // Getipptes zuerst speichern: vererbt wird der gespeicherte Wert
  catch (err) { meldung(err.message, "Vor dem Vererben speichern ging nicht"); return; }
  try { es.angaben = await senden("/api/es_angaben", { ziele: esZiele() }); entwurfSetzen(); editorZeichnen(); } catch { /* bleibt */ }
  const f = es.angaben.felder;
  const namen = [...FELD_NAMEN, ...notizen().map((k) => [k, f[k].name])];
  const gefuellt = namen.filter(([k]) => f[k].eigen);
  if (!gefuellt.length) { meldung("Erst ausfüllen, dann vererben.", "Hier ist noch kein Feld gesetzt"); return; }
  $("#es-vererben-inhalt").innerHTML = `
    <p class="dialog-text">Die Angaben von <b>${esc(es.angaben.name)}</b> werden als eigene Werte in die Elemente darunter geschrieben.
      Erst dann sind die Dateien erschlossen und lassen sich zuordnen.</p>
    <div class="es-vb-gruppe"><span class="leise">Felder</span>
      ${namen.map(([k, n]) => `<label><input type="checkbox" data-vb-feld="${k}" ${!f[k].eigen ? "disabled" : (feld ? k === feld : true) ? "checked" : ""}> ${n}</label>`).join("")}</div>
    <div class="es-vb-gruppe"><span class="leise">An</span>
      <label><input type="checkbox" data-vb-umfang="dateien" checked> Dateien (Einzelstücke)</label>
      <label><input type="checkbox" data-vb-umfang="ordner"> Unterordner (für spätere neue Verzeichnungseinheiten)</label></div>
    <div class="es-vb-gruppe"><span class="leise">Tiefe</span>
      <label><input type="radio" name="vb-tief" value="1" checked> alle Ebenen darunter</label>
      <label><input type="radio" name="vb-tief" value="0"> nur direkt enthaltene</label></div>
    ${f.zeitraum.eigen ? `<div class="es-vb-gruppe"><span class="leise">Laufzeit</span>
      <label><input type="radio" name="vb-zeitraum" value="0" ${f.zeitraum.eigen.je_datei === "datum" ? "" : "checked"}> die des Ordners für alle</label>
      <label><input type="radio" name="vb-zeitraum" value="1" ${f.zeitraum.eigen.je_datei === "datum" ? "checked" : ""}> je Datei das beste Datum (sonst die des Ordners)</label></div>` : ""}
    <div class="es-vb-gruppe"><span class="leise">Vorhandene Werte</span>
      <label><input type="radio" name="vb-ueber" value="0" checked> nur leere Felder füllen</label>
      <label><input type="radio" name="vb-ueber" value="1"> überschreiben</label></div>
    <div id="es-vb-stand" class="es-vb-stand leise">…</div>
    <div class="leise">Der Zusatz je Datei beim Titel wird je Datei aufgelöst ({laufnummer} zählt in diesem Ordner).</div>`;
  $("#es-vererben-fehler").textContent = "";
  $("#es-vererben-dialog").showModal();
  vererbenPruefen();
}
function vererbenAuswahl() {
  return {
    felder: [...document.querySelectorAll("[data-vb-feld]:checked")].map((x) => x.dataset.vbFeld),
    umfang: { dateien: !!document.querySelector('[data-vb-umfang="dateien"]:checked'), ordner: !!document.querySelector('[data-vb-umfang="ordner"]:checked'),
              tief: document.querySelector('[name="vb-tief"]:checked').value === "1" },
    ueberschreiben: document.querySelector('[name="vb-ueber"]:checked').value === "1",
    zeitraum_je_datei: document.querySelector('[name="vb-zeitraum"]:checked') ? document.querySelector('[name="vb-zeitraum"]:checked').value === "1" : null,
  };
}
async function vererbenPruefen() {
  const w = vererbenAuswahl();
  try {
    const r = await senden("/api/es_vererben_pruefen", { ...vbQuelle, felder: w.felder, umfang: w.umfang });
    const teile = [w.umfang.dateien ? `${zahl(r.dateien)} Dateien` : "", w.umfang.ordner ? `${zahl(r.ordner)} Unterordner` : ""].filter(Boolean);
    $("#es-vb-stand").textContent = !teile.length ? "Bitte Dateien oder Unterordner wählen."
      : `Betrifft ${teile.join(" und ")}${r.belegt ? `; ${zahl(r.belegt)} davon haben schon eigene Werte (${w.ueberschreiben ? "werden überschrieben" : "bleiben"})` : ""}.`;
    $("#es-vererben-ok").disabled = !w.felder.length || !teile.length || !(r.dateien + r.ordner);
  } catch (err) { $("#es-vb-stand").textContent = err.message; }
}
$("#es-vererben-inhalt").addEventListener("change", vererbenPruefen);
$("#es-vererben-abbrechen").addEventListener("click", () => $("#es-vererben-dialog").close());
$("#es-vererben-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const w = vererbenAuswahl();
  $("#es-vererben-ok").disabled = true;
  try {
    const r = await senden("/api/es_vererben", { ...vbQuelle, ...w });
    $("#es-vererben-dialog").close();
    await nachAktion();
    $("#es-speicher-info").textContent = `vererbt: ${zahl(r.geschrieben)} Werte${r.uebersprungen ? `, ${zahl(r.uebersprungen)} vorhandene behalten` : ""}`;
  } catch (err) { $("#es-vererben-fehler").textContent = err.message; $("#es-vererben-ok").disabled = false; }
});

// ---- Vorschaubild groß, mit Blättern und Fundort ----
let bildNr = 0;
function bildZeigen(i) {
  const liste = es.angaben?.bilder || [];
  if (!liste.length) return;
  bildNr = (i + liste.length) % liste.length;
  const b = liste[bildNr];
  $("#es-bild-inhalt").innerHTML = `
    <div class="es-bild-gross">${bild(b.thumb, b.name, "vorschau-gross")}</div>
    <div class="es-bild-text"><b>${esc(b.name)}</b> <span class="leise">${esc(b.platte)} / ${esc(b.pfad.split("/").slice(0, -1).join(" / ") || "(oberste Ebene)")} · ${bildNr + 1} von ${zahl(liste.length)}${liste.length >= 60 ? "+" : ""}</span></div>
    <div class="es-bild-fundort"><button type="button" class="knopf-leise" id="es-bild-zeigen" disabled>${icon("folder-search")} Datei zeigen</button>
      <span id="es-bild-hinweis" class="leise">Prüfe, ob der Datenträger angeschlossen ist …</span></div>`;
  $("#es-bild-zurueck").disabled = $("#es-bild-vor").disabled = liste.length < 2;
  if (!$("#es-bild-dialog").open) $("#es-bild-dialog").showModal();
  fundortPruefen(b.platte, b.pfad, $("#es-bild-zeigen"), $("#es-bild-hinweis"));
}
$("#es-bild-dialog").addEventListener("click", (ev) => {
  if (ev.target === $("#es-bild-dialog") || ev.target.closest("#es-bild-zu")) return $("#es-bild-dialog").close();
  if (ev.target.closest("#es-bild-zurueck")) return bildZeigen(bildNr - 1);
  if (ev.target.closest("#es-bild-vor")) return bildZeigen(bildNr + 1);
  if (ev.target.closest("#es-bild-zeigen")) { const b = es.angaben.bilder[bildNr]; fundortZeigen(b.platte, b.pfad, $("#es-bild-hinweis")); }
});
$("#es-bild-dialog").addEventListener("keydown", (ev) => {
  if (ev.key === "ArrowLeft") bildZeigen(bildNr - 1);
  if (ev.key === "ArrowRight") bildZeigen(bildNr + 1);
});

async function sprachmodellFragen(knopf) {
  const z = es.angaben.ziele[0];
  knopf.disabled = true;
  knopf.innerHTML = `<i class="drehen"></i> Sprachmodell rechnet (rund 30 s) …`;
  try {
    const r = await senden("/api/es_sprachmodell", z);
    const neu = await senden("/api/es_angaben", { ziele: esZiele() });
    felderBehalten(() => { es.angaben = neu; editorZeichnen(); });
    const verworfen = r.verworfen?.length ? ` · ${r.verworfen.length} verworfen (${r.verworfen.map((v) => `${v.feld}: ${v.grund}`).join("; ")})` : "";
    $("#es-speicher-info").textContent = `Sprachmodell ${r.modell}: ${Object.keys(r.vorschlaege).length} Vorschläge in ${String(r.dauer).replace(".", ",")} s${verworfen}`;
  } catch (err) {
    meldung(err.message, "Fehler");
    knopf.disabled = false;
    knopf.innerHTML = `${icon("sparkles")} Vorschlag vom Sprachmodell`;
  }
}

// ---- Abgleich mit Verwandten ----
let vwQuelle = null, vwListe = [];
function verwandteDialog(liste, quelle, nachSpeichern) {
  vwQuelle = quelle;
  vwListe = liste;
  const titel = $("#es-titel")?.value || es.angaben?.felder?.titel?.eigen?.gleich || "";
  $("#es-verwandte-inhalt").innerHTML = `
    <p class="dialog-text">An diesen Orten liegen Ordner, die vermutlich ${titel ? `zu „${esc(titel)}“` : "zum selben Thema"} gehören.
      Sollen sie die eben eingetragenen Angaben ebenfalls bekommen?</p>
    <div class="es-vw-felder"><span class="leise">Übernehmen:</span>
      ${FELD_NAMEN
        .map(([k, n]) => `<label><input type="checkbox" data-vw-feld="${k}" ${k === "titel" ? "checked" : ""}> ${n}</label>`).join("")}</div>
    <div class="es-vw-alle"><button type="button" class="knopf-leise" data-vw-alle="1">alle an</button><button type="button" class="knopf-leise" data-vw-alle="0">alle ab</button></div>
    <div class="es-tabelle-halter"><table class="vl-tabelle es-vw-tabelle"><thead><tr><th></th><th>Fundort</th><th>Grund</th><th>Score</th><th>Bisher</th></tr></thead>
      <tbody>${liste.map((v, i) => {
        const kassiert = !v.uebernommen;
        const vor = !kassiert && !v.titel_eigen;
        return `<tr class="${kassiert ? "vl-aus" : ""}">
          <td><input type="checkbox" data-vw="${i}" ${vor ? "checked" : ""} ${kassiert ? "disabled" : ""}></td>
          <td><div class="es-vw-ort">${v.thumbs.slice(0, 2).map((t) => bild(t, "")).join("")}
            <span><b>${esc(v.platte)}</b> / ${esc(v.pfad)} <span class="leise">(${zahl(v.uebernommen)} von ${zahl(v.dateien)} übernommen)</span></span></div></td>
          <td>${v.gruende.map((g) => `<div>${esc(GRUND[g.grund] || g.grund)} <span class="leise">${esc(g.beleg)}</span></div>`).join("")}</td>
          <td>${v.score.toFixed(2).replace(".", ",")}</td>
          <td>${kassiert ? `<span class="leise">nicht übernommen · nur Kontext</span>` : v.titel_eigen ? `„${esc(v.titel)}“ ${v.erschlossen >= v.uebernommen ? "erschlossen" : ""}` : `<span class="leise">offen</span>`}</td></tr>`;
      }).join("")}</tbody></table></div>
    <div class="leise">Abgewählte Treffer merkt sich das Projekt als „nicht verwandt“; sie erscheinen nicht wieder. Schon erschlossene sind nicht vorgewählt; nicht Übernommenes (kassiert, zurückgestellt, offen) wird nie geändert.</div>`;
  $("#es-verwandte-nein").textContent = nachSpeichern ? "Nur hier speichern" : "Schließen";
  $("#es-verwandte-fehler").textContent = "";
  $("#es-verwandte-dialog").showModal();
}
$("#es-verwandte-inhalt").addEventListener("click", (ev) => {
  const alle = ev.target.closest("[data-vw-alle]");
  if (alle) document.querySelectorAll("[data-vw]:not([disabled])").forEach((x) => (x.checked = alle.dataset.vwAlle === "1"));
});
$("#es-verwandte-nein").addEventListener("click", () => $("#es-verwandte-dialog").close());
$("#es-verwandte-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const felder = [...document.querySelectorAll("[data-vw-feld]:checked")].map((x) => x.dataset.vwFeld);
  const gewaehlt = [], abgewaehlt = [];
  document.querySelectorAll("[data-vw]").forEach((x) => {
    const v = vwListe[Number(x.dataset.vw)];
    if (x.disabled) return;
    (x.checked ? gewaehlt : abgewaehlt).push({ platte: v.platte, pfad: v.pfad });
  });
  if (!felder.length && gewaehlt.length) { $("#es-verwandte-fehler").textContent = "Bitte mindestens ein Feld wählen."; return; }
  try {
    const r = await senden("/api/es_abgleichen", { quelle: vwQuelle, gewaehlt, abgewaehlt, felder });
    $("#es-verwandte-dialog").close();
    await nachAktion();
    $("#es-speicher-info").textContent = `abgeglichen: ${zahl(r.geschrieben)} Werte in ${zahl(gewaehlt.length)} Ordnern`;
  } catch (err) { $("#es-verwandte-fehler").textContent = err.message; }
});

// ======================================================================================================
// Bestandsboxen (Entscheidung 03.11.2026): Box aus Anton, angedockte Unterverzeichnungseinheiten, Dateien je Herkunft
// verschachtelt; unten an jeder Box eine Halbbox für eine neue Einheit. Zuordnen per Ziehen oder Knopf.
// ======================================================================================================
const zugangGeprueft = new Set();   // Anton-IDs, deren Zugang in dieser Sitzung nachgeprüft wurde
const clip = (text, art, titel = "") => `<span class="es-clip ${art}"${titel ? ` title="${esc(titel)}"` : ""}>${text}</span>`;

// Stufe einer Ordner-Einheit: Dropdown mit den Stufen aus Anton (ändert die Zuordnung)
function stufeWahl(x) {
  const liste = es.boxen?.stufen?.liste || [];
  const namen = liste.map((s) => s.name);
  if (!namen.includes(x.stufe_name)) namen.unshift(x.stufe_name);
  return `<select class="es-stufe-wahl" data-stufe-aendern="${esc(esKey(x.platte, x.pfad))}" aria-label="Stufe">
    ${namen.map((n) => `<option ${n === x.stufe_name ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>`;
}
// Stufe für einen auf die Halbbox gezogenen Ordner: zuletzt gewählte, sonst Dossier, sonst die erste
function halbboxStufe() {
  const liste = es.boxen?.stufen?.liste || [];
  return liste.find((s) => s.name === es.neuStufe) || liste.find((s) => s.import === "file") || liste[0];
}

// Kopf einer Einheit: Signatur und Stufe klein, Titel, Laufzeit klein; Clips gesperrt/neu; rechts die Knöpfe
function einheitKopf(x) {
  const knoepfe = [];
  if (x.art === "anton" && x.link) knoepfe.push(`<a class="knopf-mini" href="${esc(x.link)}" target="_blank" rel="noopener" title="In Anton öffnen">${icon("external-link")}</a>`);
  if (x.art === "ordner") knoepfe.push(`<button type="button" class="knopf-mini" data-loesen-el="${esc(esKey(x.platte, x.pfad))}" title="Zuordnung des Ordners lösen">${icon("unlink")}</button>`);
  if (x.art === "anton" && x.leer) knoepfe.push(`<button type="button" class="knopf-mini" data-box-weg="${esc(x.anton_id)}" title="Box entfernen">${icon("x")}</button>`);
  if (x.art === "ebene" && x.leer) knoepfe.push(`<button type="button" class="knopf-mini" data-ebene-weg="${esc(x.ebene_id)}" title="Einheit entfernen">${icon("x")}</button>`);
  const pfad = x.art === "anton" && x.eltern.length ? x.eltern.map((e) => e.signatur || e.titel).join(" › ") : "";
  const meta = [x.laufzeit, x.dateien ? `${zahl(x.dateien)} ${x.dateien === 1 ? "Datei" : "Dateien"}` : ""].filter(Boolean);
  const herkunft = x.art === "ordner" ? `aus ${x.platte} › ${x.pfad}` : x.art === "ebene" && x.import_name !== x.stufe_name ? `Import: ${x.import_name}` : "";
  return `<div class="es-einheit-kopf">
      ${pfad ? `<div class="es-einheit-pfad" title="Verortung im Archivbestand (Einheiten darüber in Anton)">${esc(pfad)}</div>` : ""}
      <div class="es-einheit-oben">
        ${x.signatur ? `<span class="es-signatur">${esc(x.signatur)}</span>` : ""}
        ${x.art === "ordner" && !x.einzelstueck ? stufeWahl(x) : x.stufe_name ? `<span class="es-stufe-klein">${esc(x.stufe_name)}</span>` : ""}
        ${x.art !== "anton" ? "" : x.gesperrt ? clip(`${icon("lock")} intern`, "gesperrt", "gesperrt: nur intern sichtbar (mit Token), öffentlich nicht abrufbar")
          : x.gesperrt === false ? clip("öffentlich", "oeffentlich", "öffentlich in Anton abrufbar")
          : zugangGeprueft.has(x.anton_id) ? clip("Zugang unbekannt", "oeffentlich", "Anton nicht erreichbar oder Einheit nicht gefunden; oben die ID neu laden")
          : clip("Zugang wird geprüft …", "oeffentlich", "Box vor der Prüfung des Zugangs geladen; wird einmal neu aus Anton geholt")}
        ${x.neu ? clip("neu", "neu", "entsteht in Anton erst mit dem Import") : ""}
        <span class="es-einheit-knoepfe">${knoepfe.join("")}</span>
      </div>
      <div class="es-einheit-titel" title="${esc(pfad)}">${esc(x.titel || "(ohne Titel)")}</div>
      ${meta.length ? `<div class="es-einheit-meta">${esc(meta.join(" · "))}</div>` : ""}
      ${herkunft ? `<div class="es-einheit-meta">${esc(herkunft)}</div>` : ""}
      ${x.einzelstueck ? `<div class="es-einheit-meta">${icon("layers")} ein Objekt: alle ${zahl(x.dateien)} Dateien als Medien dieses Einzelstücks</div>` : ""}
    </div>`;
}

// Dateien je Herkunft (Platte › Ordner) als helleres Kästchen; Klick klappt die Liste auf
const herkunftKey = (x, g) => `${x.ziel || esKey(x.platte, x.pfad)}#${esKey(g.platte, g.ordner)}`;
function herkunftHtml(x) {
  return x.herkunft.map((g) => {
    const k = herkunftKey(x, g);
    const auf = es.herkunftOffen.has(k);
    const liste = auf ? `<ul class="es-herkunft-liste">${g.dateien.map((f) => `<li>
        <button type="button" class="es-datei" data-datei="${esc(esKey(g.platte, f.pfad))}" title="In Editor und Baum öffnen">
          ${icon("file")}<span class="es-name">${esc(f.name)}</span>${f.titel ? `<span class="es-name leise">${esc(f.titel)}</span>` : ""}</button>
        ${f.eigen ? `<button type="button" class="knopf-mini" data-loesen-el="${esc(esKey(g.platte, f.pfad))}" title="Zuordnung lösen">${icon("unlink")}</button>` : ""}</li>`).join("")}
        ${g.anzahl > g.dateien.length ? `<li class="leise">… und ${zahl(g.anzahl - g.dateien.length)} weitere</li>` : ""}</ul>` : "";
    return `<div class="es-herkunft${auf ? " offen" : ""}">
        <div class="es-herkunft-zeile">
          <button type="button" class="es-herkunft-kopf" data-herkunft="${esc(k)}" aria-expanded="${auf}">
            ${icon(auf ? "chevron-down" : "chevron-right")}${icon("folder-open")}
            <span class="es-name">aus <b>${esc(g.platte)}</b>${g.ordner ? ` › ${esc(g.ordner)}` : ""}</span>
            <span class="es-zahl">${zahl(g.anzahl)}</span></button>
          ${g.eigen && x.ziel ? `<button type="button" class="knopf-mini knopf-text" data-loesen-gruppe="${esc(x.ziel)}" data-platte="${esc(g.platte)}" data-ordner="${esc(g.ordner)}"
              title="Die ${zahl(g.eigen)} einzeln zugeordneten Dateien aus diesem Ordner auf einmal lösen">${icon("unlink")} ${zahl(g.eigen)}</button>` : ""}
          ${g.loesbar ? `<button type="button" class="knopf-mini" data-loesen-el="${esc(esKey(g.platte, g.ordner))}" title="Zuordnung des Ordners lösen">${icon("unlink")}</button>` : ""}
        </div>${liste}</div>`;
  }).join("");
}

// Halbbox unter einer Box oder neuen Einheit: neue Unterverzeichnungseinheit anlegen (Stufe aus Anton)
function halbboxHtml(x) {
  if (es.neuOffen !== x.ziel) {
    return `<button type="button" class="es-halbbox" data-neu="${esc(x.ziel)}" data-halbbox="${esc(x.ziel)}">${icon("plus")} Neue Verzeichnungseinheit
      <span class="es-halbbox-ziehen">oder Ordner hierher ziehen</span></button>`;
  }
  const st = es.boxen?.stufen || { liste: [] };
  const wahl = st.liste.find((s) => s.name === es.neuStufe) || st.liste[0];
  const IMPORT = { class: "Gliederungsebene", file: "Dossier" };
  return `<form class="es-halbbox offen" data-neu-form="${esc(x.ziel)}" data-halbbox="${esc(x.ziel)}">
      <div class="es-neu-zeile">
        <label>Stufe <select name="stufe_name">${st.liste.map((s) => `<option ${s === wahl ? "selected" : ""}>${esc(s.name)}</option>`).join("")}</select></label>
        <label>Signatur <input name="signatur" placeholder="optional" autocomplete="off" spellcheck="false"></label>
      </div>
      <div class="es-neu-hinweis leise">${st.aus_anton ? "Stufen aus Anton" : "Stufen aus Anton nicht verfügbar (API-Token?); Vorgabe"}${wahl && IMPORT[wahl.import] !== wahl.name ? ` · der Import legt sie als ${IMPORT[wahl.import]} an` : ""}</div>
      <label><span>Titel${PFLICHT}</span> <input name="titel" autocomplete="off" required></label>
      <label>Laufzeit <span class="es-zeitraum"><input name="von" placeholder="von (JJJJ, MM.JJJJ, TT.MM.JJJJ)">–<input name="bis" placeholder="bis">
        <span class="es-ca"><input type="checkbox" name="ca"> ca.</span></span></label>
      <label>Form und Inhalt <textarea name="inhalt" rows="2"></textarea></label>
      <div class="fehler" data-neu-fehler></div>
      <div class="es-neu-knoepfe"><button type="button" class="knopf-leise" data-neu-zu>Abbrechen</button><button type="submit" class="haupt">Anlegen</button></div>
    </form>`;
}

// Eine Einheit: Karte mit allem, was sie enthält (Dateien je Herkunft, darunter die enthaltenen Einheiten als
// Kästchen in der Karte, Entscheidung 04.11.2026); außer bei Ordnern schließt unten die Halbbox an
function einheitHtml(x) {
  // Ordner mit eigener Ebene nehmen einzelne Dateien von anderswo auf (Ziel „o:…“, Entscheidung 06.11.2026), Einzelstücke nicht
  const ziel = x.art === "ordner" && x.einzelstueck ? "" : ` data-ziel="${esc(x.ziel)}"`;
  const leer = !x.herkunft.length && !x.einheiten.length;
  const leerHinweis = x.art !== "ordner" && leer ? `<div class="es-ablage-hinweis">${icon("package")} Erschlossene Dateien oder Ordner hierher ziehen</div>` : "";
  return `<div class="es-einheit es-${x.art}">
      <div class="es-einheit-karte${ziel ? " es-ablage" : ""}"${ziel}>
        ${einheitKopf(x)}
        ${x.herkunft.length ? `<div class="es-herkuenfte">${herkunftHtml(x)}</div>` : ""}
        ${x.einheiten.length ? `<div class="es-enthalten">${x.einheiten.map(einheitHtml).join("")}</div>` : ""}${leerHinweis}
      </div>
      ${x.art === "ordner" ? "" : halbboxHtml(x)}
    </div>`;
}

let stufenGeholt = false;
async function boxenLaden() {
  try {
    const d = await holen("/api/boxen");
    es.boxen = d;
    boxenZeichnen();
    auswahlInfo();
    // Boxen von vor der Zugangsprüfung (gesperrt unbekannt): einmal je Sitzung neu aus Anton holen
    const unbekannt = d.boxen.filter((b) => b.gesperrt == null && !zugangGeprueft.has(b.anton_id));
    if (unbekannt.length) {
      unbekannt.forEach((b) => zugangGeprueft.add(b.anton_id));
      Promise.allSettled(unbekannt.map((b) => senden("/api/box_laden", { kennung: String(b.anton_id) }))).then(boxenLaden);
    }
    if (!stufenGeholt) {                       // einmal je Sitzung: Stufen aus Anton holen (höchstens alle 7 Tage neu)
      stufenGeholt = true;
      holen("/api/anton_stufen").then((s) => { es.boxen.stufen = s; if (es.neuOffen) boxenZeichnen(); }).catch(() => {});
    }
  } catch (err) {
    $("#es-boxen").innerHTML = `<div class="fehler">${esc(err.message)}</div>`;
  }
}
function boxenZeichnen() {
  const d = es.boxen;
  $("#es-boxen").innerHTML = d.boxen.length ? d.boxen.map(einheitHtml).join("")
    : `<div class="leer-hinweis">Noch keine bestehende Verzeichnungseinheit geladen. Oben die Anton-ID oder Signatur einer Verzeichnungseinheit in Anton eingeben (${esc(d.anton_url)}).</div>`;
}
$("#es-box-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const kennung = $("#es-box-kennung").value.trim();
  if (!kennung) return;
  $("#es-box-fehler").textContent = "";
  const knopf = ev.target.querySelector("button");
  knopf.disabled = true;
  try {
    await senden("/api/box_laden", { kennung });
    $("#es-box-kennung").value = "";
    await boxenLaden();
  } catch (err) {
    $("#es-box-fehler").textContent = err.message;
  } finally {
    knopf.disabled = false;
  }
});

// Datei aus einer Box in Editor und Baum: Filter weg, Ordner bis dorthin aufklappen, Zeile wählen
async function inBaumZeigen(platte, pfad) {
  if (filterAktiv()) {
    es.filter = { q: "", nur: "", ansicht: es.filter.ansicht };
    $("#es-q").value = "";
    $("#es-treffer").hidden = true;
    $("#es-baum").hidden = false;
    es.treffer = null;
    facettenZeichnen();
  }
  es.auswahl.clear();
  const teile = pfad.split("/");
  const ordner = teile.slice(0, -1).map((_, i) => teile.slice(0, i + 1).join("/"));
  try {
    for (const o of ["", ...ordner]) {
      const k = esKey(platte, o);
      es.offen.add(k);
      if (!es.kinder.has(k)) es.kinder.set(k, await holen("/api/es_kinder", { platte, pfad: o }));
    }
    const k = esKey(platte, ordner.length ? ordner.at(-1) : "");
    for (let i = 0; i < 50; i++) {             // Datei hinter „weitere laden“: nachladen, bis sie da ist
      const kinder = es.kinder.get(k);
      if (kinder.dateien.some((f) => f.pfad === pfad) || !kinder.weitere) break;
      const mehr = await holen("/api/es_kinder", { ...teilen(k), offset: kinder.offset });
      es.kinder.set(k, { ...kinder, dateien: kinder.dateien.concat(mehr.dateien), weitere: mehr.weitere, offset: mehr.offset });
    }
  } catch (err) { meldung(err.message, "Fehler"); }
  baumZeichnen();
  const li = $("#es-baum").querySelector(`li[data-platte="${CSS.escape(platte)}"][data-pfad="${CSS.escape(pfad)}"]`);
  if (li) {
    waehlen(li);
    li.scrollIntoView({ block: "center" });
  } else {
    es.aktiv = { platte, pfad, art: "datei" };
    es.angenommen.clear();
    angabenLaden();
  }
}

$("#es-boxen").addEventListener("click", async (ev) => {
  const fehler = (err) => meldung(err.message, "Fehler");
  const weg = ev.target.closest("[data-box-weg]");
  if (weg) return senden("/api/box_entfernen", { anton_id: weg.dataset.boxWeg }).then(boxenLaden, fehler);
  const ew = ev.target.closest("[data-ebene-weg]");
  if (ew) return senden("/api/ebene_entfernen", { ebene_id: ew.dataset.ebeneWeg }).then(boxenLaden, fehler);
  const le = ev.target.closest("[data-loesen-el]");
  if (le) return senden("/api/es_zuordnung_loesen", teilen(le.dataset.loesenEl)).then(nachAktion, fehler);
  const lg = ev.target.closest("[data-loesen-gruppe]");
  if (lg) {
    return senden("/api/es_zuordnung_loesen", { ziel: lg.dataset.loesenGruppe, platte: lg.dataset.platte, ordner: lg.dataset.ordner })
      .then(nachAktion, fehler);
  }
  const h = ev.target.closest("[data-herkunft]");
  if (h) {
    if (!es.herkunftOffen.delete(h.dataset.herkunft)) es.herkunftOffen.add(h.dataset.herkunft);
    return boxenZeichnen();
  }
  const datei = ev.target.closest("[data-datei]");
  if (datei) {
    const { platte, pfad } = teilen(datei.dataset.datei);
    return inBaumZeigen(platte, pfad);
  }
  const neu = ev.target.closest("[data-neu]");
  if (neu) {
    es.neuOffen = neu.dataset.neu;
    boxenZeichnen();
    return $("#es-boxen").querySelector("[data-neu-form] [name=titel]")?.focus();
  }
  if (ev.target.closest("[data-neu-zu]")) { es.neuOffen = null; boxenZeichnen(); }
});
$("#es-boxen").addEventListener("change", (ev) => {
  const sa = ev.target.closest("[data-stufe-aendern]");
  if (sa) {
    es.neuStufe = sa.value;
    return senden("/api/es_zuordnung_stufe", { ...teilen(sa.dataset.stufeAendern), stufe_name: sa.value })
      .then(boxenLaden, (err) => { meldung(err.message, "Fehler"); boxenLaden(); });
  }
  if (ev.target.name !== "stufe_name" || !ev.target.closest("[data-neu-form]")) return;
  es.neuStufe = ev.target.value;                // Hinweis zum Import passt sich an; Eingaben bleiben stehen
  const form = ev.target.closest("form");
  const st = es.boxen.stufen.liste.find((s) => s.name === es.neuStufe);
  const IMPORT = { class: "Gliederungsebene", file: "Dossier" };
  form.querySelector(".es-neu-hinweis").textContent = (es.boxen.stufen.aus_anton ? "Stufen aus Anton" : "Stufen aus Anton nicht verfügbar (API-Token?); Vorgabe")
    + (st && IMPORT[st.import] !== st.name ? ` · der Import legt sie als ${IMPORT[st.import]} an` : "");
});
$("#es-boxen").addEventListener("submit", async (ev) => {
  const form = ev.target.closest("[data-neu-form]");
  if (!form) return;
  ev.preventDefault();
  const f = new FormData(form);
  try {
    await senden("/api/ebene_anlegen", { eltern: form.dataset.neuForm, titel: f.get("titel"), stufe_name: f.get("stufe_name"),
                                         signatur: f.get("signatur"), von: f.get("von"), bis: f.get("bis"), ca: !!f.get("ca"),
                                         inhalt: f.get("inhalt") });
    es.neuOffen = null;
    boxenLaden();
  } catch (err) { form.querySelector("[data-neu-fehler]").textContent = err.message; }
});

// ---- Ziehen aus Baum oder Trefferliste auf eine Box oder Einheit ----
function ziehenStart(ev) {
  const li = ev.target.closest(".zeile[draggable]")?.parentElement;
  if (!li) return;
  const k = esKey(li.dataset.platte, li.dataset.pfad);
  es.ziehen = es.auswahl.has(k) ? [...es.auswahl.values()] : [eintragVon(li)];
  ev.dataTransfer.effectAllowed = "move";
  ev.dataTransfer.setData("text/plain", k);
  document.body.classList.add("es-zieht");
}
function ziehenEnde() { document.body.classList.remove("es-zieht"); document.querySelectorAll("#es-boxen .drueber").forEach((x) => x.classList.remove("drueber")); }
$("#es-baum").addEventListener("dragstart", ziehenStart);
$("#es-treffer").addEventListener("dragstart", ziehenStart);
document.addEventListener("dragend", ziehenEnde);
$("#es-boxen").addEventListener("dragover", (ev) => {
  const ablage = ev.target.closest(".es-ablage[data-ziel], [data-halbbox]");
  if (!ablage || !es.ziehen) return;
  ev.preventDefault();
  document.querySelectorAll("#es-boxen .drueber").forEach((x) => x !== ablage && x.classList.remove("drueber"));
  ablage.classList.add("drueber");
});
$("#es-boxen").addEventListener("dragleave", (ev) => {
  const ablage = ev.target.closest(".es-ablage, [data-halbbox]");
  if (ablage && !ablage.contains(ev.relatedTarget)) ablage.classList.remove("drueber");
});
$("#es-boxen").addEventListener("drop", async (ev) => {
  const halbbox = ev.target.closest("[data-halbbox]");
  const ablage = halbbox || ev.target.closest(".es-ablage[data-ziel]");
  if (!ablage || !es.ziehen) return;
  ev.preventDefault();
  ziehenEnde();
  const ziele = es.ziehen;
  es.ziehen = null;
  if (halbbox && ziele.some((z) => z.art !== "datei")) return ordnerAlsEinheit(ziele, halbbox.dataset.halbbox);
  if (!halbbox && ablage.dataset.ziel.startsWith("o:") && ziele.some((z) => z.art !== "datei")) {
    meldung("Ordner auf die Verzeichnungseinheit oder auf „Neue Verzeichnungseinheit“ ziehen.",
            "In einen Ordner, der eine eigene Einheit ist, lassen sich nur einzelne Dateien ziehen");
    return;
  }
  // nur Dateien und alles in Ordnung: gleich zuordnen; Ordner (Stufen) oder Probleme: Dialog
  if (ziele.every((z) => z.art === "datei")) {
    try {
      const p = await senden("/api/es_zuordnen_pruefen", { ziele, ziel: ablage.dataset.ziel });
      if (!p.ordner.length && !p.nicht_erschlossen && p.dateien) {
        await senden("/api/es_zuordnen", { ziele, ziel: ablage.dataset.ziel, stufen: {} });
        return nachAktion();
      }
    } catch { /* der Dialog zeigt den Fehler */ }
  }
  zuordnenDialog(ziele, ablage.dataset.ziel);
});
// Ordner auf der Halbbox: sofort Unterverzeichnungseinheit(en) mit der Stufe der Halbbox; Unterordner eine Stufe
// tiefer (Vorgabe des Servers). Fehlt etwas, öffnet sich der Zuordnen-Dialog mit dieser Stufe vorbelegt.
// Stufen aus Anton (ohne Einzelstück); "" = Ordner auflösen. Unterordner: Vorgabe die nächste Stufe darunter.
// Einzelstück (Entscheidung 05.11.2026): der Ordner wird ein Objekt, alle Dateien darunter seine Medien
const stufenListe = () => es.boxen?.stufen?.liste || [];
const einzelName = () => es.boxen?.stufen?.einzelstueck || "Einzelstück";
const stufeImport = (name) => (!name ? "" : name === einzelName() ? "item" : stufenListe().find((s) => s.name === name)?.import || "");
const dossierName = () => (stufenListe().find((s) => s.import === "file") || stufenListe().at(-1) || {}).name || "";
function stufeDarunter(name) {
  if (!name) return "";
  const liste = stufenListe(), i = liste.findIndex((s) => s.name === name);
  if (i < 0 || liste[i].import === "file") return dossierName();       // Dossier bleibt Dossier
  return (liste[i + 1] || {}).name || dossierName();
}
// Stufe je Ordner: gewählt, sonst oben die Vorgabe, darunter eine Stufe tiefer als der Ordner darüber
function stufenNamen(ordner, gewaehlt, oben) {
  const namen = {};
  for (const o of [...ordner].sort((a, b) => a.tiefe - b.tiefe)) {
    const k = esKey(o.platte, o.pfad);
    if (k in gewaehlt) { namen[k] = gewaehlt[k]; continue; }
    const eltern = ordner.find((x) => x.platte === o.platte && x.pfad === o.pfad.split("/").slice(0, -1).join("/") && x.tiefe === o.tiefe - 1);
    namen[k] = o.tiefe === 0 || !eltern ? oben : stufeDarunter(namen[esKey(eltern.platte, eltern.pfad)]);
  }
  return namen;
}

async function ordnerAlsEinheit(ziele, ziel) {
  const stufe = halbboxStufe();
  let p;
  try { p = await senden("/api/es_zuordnen_pruefen", { ziele, ziel }); }
  catch { return zuordnenDialog(ziele, ziel); }
  const namen = stufenNamen(p.ordner, {}, stufe?.name || dossierName());
  const stufen = Object.fromEntries(Object.entries(namen).map(([k, n]) => [k, stufeImport(n)]));
  const probleme = p.ordner.some((o) => stufen[esKey(o.platte, o.pfad)] && o.fehlt.length);
  if (!probleme && !p.nicht_erschlossen && p.dateien) {
    try {
      await senden("/api/es_zuordnen", { ziele, ziel, stufen, namen });
      return nachAktion();
    } catch { /* Dialog zeigt den Fehler */ }
  }
  zuordnenDialog(ziele, ziel, { namen: Object.fromEntries(p.ordner.filter((o) => o.tiefe === 0).map((o) => [esKey(o.platte, o.pfad), namen[esKey(o.platte, o.pfad)]])) });
}

$("#es-zuordnen-knopf").addEventListener("click", () => {
  const ziele = (es.boxen?.boxen || []).map((b) => b.ziel);
  if (ziele.length && esZiele().length) zuordnenDialog(esZiele(), ziele[0]);
});

// ---- Zuordnen-Dialog ----
function zielOptionen(gewaehlt) {
  const opts = [];
  const nurDateien = (es.zuordnen?.ziele || []).every((z) => z.art === "datei");
  const option = (e, tiefe, text) => opts.push(`<option value="${esc(e.ziel)}" ${e.ziel === gewaehlt ? "selected" : ""}>${"  ".repeat(tiefe)}› ${text}</option>`);
  // neue Ebenen und, nur für Dateien, Ordner mit eigener Ebene (nicht Einzelstücke)
  const ebenen = (liste, tiefe) => liste.forEach((e) => {
    if (e.art === "ebene") option(e, tiefe, `${esc(e.titel)} (neu, ${esc(e.stufe_name)})`);
    else if (e.art === "ordner" && !e.einzelstueck && nurDateien) option(e, tiefe, `${esc(e.titel)} (Ordner, ${esc(e.stufe_name)})`);
    else return;
    ebenen(e.einheiten, tiefe + 1);
  });
  (es.boxen?.boxen || []).forEach((b) => {
    opts.push(`<option value="${b.ziel}" ${b.ziel === gewaehlt ? "selected" : ""}>${esc(b.signatur ? b.signatur + " " : "")}${esc(b.titel)} (Anton ${b.anton_id})</option>`);
    ebenen(b.einheiten, 1);
  });
  return opts.join("");
}
async function zuordnenDialog(ziele, ziel, vorgabe = {}) {
  es.zuordnen = { ziele, ziel, pruefung: null, gewaehlt: { ...(vorgabe.namen || {}) } };
  $("#es-zuordnen-fehler").textContent = "";
  $("#es-zuordnen-inhalt").innerHTML = `<div class="leer-hinweis">Prüft …</div>`;
  $("#es-zuordnen-dialog").showModal();
  await zuordnenPruefen();
}
async function zuordnenPruefen() {
  const z = es.zuordnen;
  const stufen = Object.fromEntries(Object.entries(z.gewaehlt).map(([k, n]) => [k, stufeImport(n)]));
  try { z.pruefung = await senden("/api/es_zuordnen_pruefen", { ziele: z.ziele, ziel: z.ziel, stufen }); }
  catch (err) { $("#es-zuordnen-inhalt").innerHTML = ""; $("#es-zuordnen-fehler").textContent = err.message; $("#es-zuordnen-ok").disabled = true; return; }
  zuordnenZeichnen();
}
const zuordnenNamen = () => stufenNamen(es.zuordnen.pruefung.ordner, es.zuordnen.gewaehlt, dossierName());
function zuordnenZeichnen() {
  const p = es.zuordnen.pruefung;
  const namen = zuordnenNamen();
  const stufeVon = (o) => stufeImport(namen[esKey(o.platte, o.pfad)]);
  const probleme = p.ordner.filter((o) => stufeVon(o) && o.fehlt.length);
  const optionen = (gewaehlt) => stufenListe().map((s) => `<option ${s.name === gewaehlt ? "selected" : ""}>${esc(s.name)}</option>`).join("")
    + `<option ${gewaehlt === einzelName() ? "selected" : ""}>${esc(einzelName())}</option>`
    + `<option value="" ${gewaehlt ? "" : "selected"}>Ordner auflösen</option>`;
  const einzelstuecke = p.ordner.filter((o) => stufeVon(o) === "item");
  const zeilen = p.ordner.map((o) => {
    const s = stufeVon(o);
    return `<tr><td style="padding-left:${8 + o.tiefe * 18}px">${icon("folder")} ${esc(o.name)}${o.titel ? ` <span class="leise">„${esc(o.titel)}“</span>` : ""}</td>
      <td><select data-stufe="${esc(esKey(o.platte, o.pfad))}" aria-label="Stufe">${optionen(namen[esKey(o.platte, o.pfad)])}</select></td>
      <td>${stufeVon(o) === "item" ? `${zahl(o.dateien)} Dateien` : `${zahl(o.direkt)} Einzelstücke${o.dateien > o.direkt ? ` <span class="leise">(${zahl(o.dateien)} mit Unterordnern)</span>` : ""}`}</td>
      <td>${s && o.fehlt.length ? `<span class="es-warnung-text">${icon("triangle-alert")} fehlt: ${esc(o.fehlt.join(", "))}</span>` : s === "item" ? `<span class="es-ok">${icon("circle-check")}</span> <span class="leise">${zahl(o.dateien)} Medien in einem Objekt</span>` : s ? `<span class="es-ok">${icon("circle-check")}</span>` : `<span class="leise">Dateien einzeln eine Ebene höher</span>`}</td></tr>`;
  }).join("");
  $("#es-zuordnen-titel").textContent = es.zuordnen.ziele.length === 1 ? `„${es.zuordnen.ziele[0].pfad.split("/").pop() || es.zuordnen.ziele[0].platte}“ zuordnen` : `${zahl(es.zuordnen.ziele.length)} Elemente zuordnen`;
  $("#es-zuordnen-inhalt").innerHTML = `
    <label class="dialog-feld">Unter <select id="es-zuordnen-ziel">${zielOptionen(es.zuordnen.ziel)}</select></label>
    <p class="dialog-text">Ordner werden dort Unterebenen, ihre Dateien Einzelstücke${p.einzeldateien ? `; ${zahl(p.einzeldateien)} einzeln gewählte Dateien werden Einzelstücke direkt darunter` : ""}.</p>
    ${p.ordner.length ? `<div class="es-tabelle-halter"><table class="vl-tabelle"><thead><tr><th>Ordner</th><th>wird</th><th>Dateien</th><th></th></tr></thead><tbody>${zeilen}</tbody></table></div>` : ""}
    ${einzelstuecke.length ? `<div class="es-einzelstueck-hinweis">${icon("layers")} <div><b>Einzelstück: alle Medien in einem Objekt.</b>
      ${einzelstuecke.map((o) => `„${esc(o.titel || o.name)}“ wird in Anton <b>ein</b> Einzelstück; alle ${zahl(o.dateien)} Dateien darin${o.dateien > o.direkt ? " (auch aus Unterordnern)" : ""} werden als Medien dieses einen Objekts verlinkt, nicht als eigene Einzelstücke.`).join(" ")}
      Titel und Laufzeit kommen vom Ordner; die Dateien brauchen keine eigene Erschließung.</div></div>` : ""}
    <details class="es-erklaerung"><summary>${icon("info")} Was bedeutet die Stufe?</summary>
      <ul><li><b>Eine Stufe</b> (z. B. ${esc(stufenListe().map((s) => s.name).slice(-3).join(", "))}): Der Ordner wird in Anton eine neue Verzeichnungseinheit dieser Stufe,
        mit Titel, Laufzeit sowie Form und Inhalt des Ordners; seine Dateien werden Einzelstücke darin. Dafür braucht der Ordner diese Angaben selbst.</li>
      <li><b>${esc(einzelName())}</b>: Der Ordner wird in Anton <b>ein</b> Objekt, alle Dateien darin (auch aus Unterordnern) dessen Medien, z. B. ein Brief oder eine Broschüre als Folge von Scans. Braucht Titel und Laufzeit am Ordner.</li>
      <li><b>Ordner auflösen</b>: Den Ordner gibt es in Anton nicht; seine Dateien werden je ein Einzelstück direkt in der Einheit darüber.</li>
      <li>Ein Unterordner bekommt als Vorgabe die nächste Stufe darunter; ein Dossier darunter bleibt Dossier.</li>
      <li>Der Import legt ein Dossier als Dossier an, jede andere Stufe als Gliederungsebene; den genauen Namen der Stufe übernimmt er nicht. Nach dem Zuordnen lässt sich die Stufe im Kopf der Einheit ändern.</li></ul></details>
    <div class="${p.nicht_erschlossen ? "es-warnung" : "es-ok"}">${icon(p.nicht_erschlossen ? "triangle-alert" : "circle-check")}
      ${p.nicht_erschlossen ? `${zahl(p.nicht_erschlossen)} von ${zahl(p.dateien)} Dateien sind noch nicht erschlossen (z. B. ${esc(p.beispiele_offen.slice(0, 2).join(", "))}). Zuordnen geht erst, wenn alle erschlossen sind.`
        : `Alle ${zahl(p.dateien)} Dateien erschlossen${probleme.length ? `, aber ${zahl(probleme.length)} Ebenen brauchen noch Angaben` : ""}.`}</div>`;
  $("#es-zuordnen-ok").disabled = !!p.nicht_erschlossen || !!probleme.length || !p.dateien;
}
$("#es-zuordnen-inhalt").addEventListener("change", (ev) => {
  const s = ev.target.closest("[data-stufe]");
  if (s) {                                        // gewählt; Unterordner ohne eigene Wahl folgen eine Stufe tiefer
    const vorher = stufeImport(zuordnenNamen()[s.dataset.stufe]);
    es.zuordnen.gewaehlt[s.dataset.stufe] = s.value;
    return vorher === "item" || stufeImport(s.value) === "item" ? zuordnenPruefen() : zuordnenZeichnen();
  }
  if (ev.target.id === "es-zuordnen-ziel") { es.zuordnen.ziel = ev.target.value; zuordnenPruefen(); }
});
$("#es-zuordnen-abbrechen").addEventListener("click", () => $("#es-zuordnen-dialog").close());
$("#es-zuordnen-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const z = es.zuordnen;
  const alle = zuordnenNamen();
  const stufen = Object.fromEntries(Object.entries(alle).map(([k, n]) => [k, stufeImport(n)]));
  const namen = Object.fromEntries(Object.entries(alle).filter(([, n]) => n));
  try {
    await senden("/api/es_zuordnen", { ziele: z.ziele, ziel: z.ziel, stufen, namen });
    $("#es-zuordnen-dialog").close();
    await nachAktion();
  } catch (err) { $("#es-zuordnen-fehler").textContent = err.message; }
});

// ======================================================================================================
// Zahnrad der Erschließung: Schnittstelle zum Sprachmodell
// ======================================================================================================
async function einstellungenLaden() {
  const ziel = $("#es-einstellungen-inhalt");
  try {
    const [m, u] = await Promise.all([holen("/api/es_sprachmodell"), holen("/api/sujet_uebersetzungen")]);
    const ue = u.einstellung;
    ziel.innerHTML = `
      <div class="leise">Vorschläge vom Sprachmodell gibt es nur auf Abruf im Editor (für einen Ordner oder ein Dokument, rund 30 s).
        Eingabe sind nur Pfadabschnitte, Dateinamen, Daten, Titel und bei Dokumenten der Textanfang.</div>
      <label class="dialog-feld">Anbieter <select id="es-llm-anbieter"><option value="ollama" selected>Ollama auf diesem Rechner</option>
        <option disabled>Cloud-Modell (gesperrt bis zur Freigabe durch das Archiv)</option></select></label>
      <label class="dialog-feld">Adresse <input id="es-llm-adresse" value="${esc(m.adresse)}" spellcheck="false"></label>
      <label class="dialog-feld">Modell ${m.modelle.length ? `<select id="es-llm-modell">${m.modelle.map((n) => `<option ${n === m.modell ? "selected" : ""}>${esc(n)}</option>`).join("")}</select>`
        : `<input id="es-llm-modell" value="${esc(m.modell)}" spellcheck="false">`}</label>
      <div class="${m.erreichbar ? "es-ok" : "es-warnung"}">${icon(m.erreichbar ? "circle-check" : "triangle-alert")}
        ${m.erreichbar ? `Ollama erreichbar · ${zahl(m.modelle.length)} Modelle` : `Ollama nicht erreichbar (${esc(m.fehler || "")}). Ollama starten, dann neu öffnen.`}</div>
      <div class="ueberschrift">Übersetzung der Sujet-Begriffe</div>
      <div class="leise">Das Sujet vergleicht Bilder mit einer englischen Begriffsliste; für Vorschläge wird die Liste einmal in die Sprache
        des Archivs übersetzt (nie einzelne Treffer). Prüfen und korrigieren im Vorlauf.</div>
      <label class="dialog-feld">Weg <select id="es-ue-weg">
        <option value="sprachmodell" ${ue.weg === "sprachmodell" ? "selected" : ""}>Sprachmodell oben (lokal, einmalig rund 12 min)</option>
        <option value="mymemory" ${ue.weg === "mymemory" ? "selected" : ""}>MyMemory (kostenlos, online, rund 2 min, ungenauer)</option></select></label>
      <label class="dialog-feld">Sprache des Archivs <input id="es-ue-sprache" value="${esc(ue.sprache)}" spellcheck="false" placeholder="de"></label>
      <label class="dialog-feld">E-Mail für MyMemory (optional, höheres Tageskontingent) <input id="es-ue-email" value="${esc(ue.email)}" spellcheck="false"></label>
      <div id="es-llm-fehler" class="fehler"></div>
      <div class="einstellungen-knoepfe"><button type="button" id="es-llm-speichern">Speichern</button></div>`;
  } catch (err) {
    ziel.innerHTML = `<div class="fehler">${esc(err.message)}</div>`;
  }
}
$("#es-einstellungen-knopf").addEventListener("click", (ev) => {
  ev.stopPropagation();
  const zu = $("#es-einstellungen").hidden;
  $("#es-einstellungen").hidden = !zu;
  if (zu) einstellungenLaden();
});
document.addEventListener("click", (ev) => {
  if (!ev.target.closest("#es-einstellungen") && !$("#es-einstellungen").hidden) $("#es-einstellungen").hidden = true;
  if (!ev.target.closest(".es-begriff-suche")) document.querySelectorAll("[data-begriff-liste]").forEach((l) => (l.hidden = true));
});
$("#es-einstellungen").addEventListener("click", async (ev) => {
  if (!ev.target.closest("#es-llm-speichern")) return;
  try {
    await senden("/api/es_einstellungen", { sprachmodell: { anbieter: "ollama", adresse: $("#es-llm-adresse").value.trim(), modell: $("#es-llm-modell").value.trim() },
      uebersetzung: { weg: $("#es-ue-weg").value, sprache: $("#es-ue-sprache").value.trim() || "de", email: $("#es-ue-email").value.trim() } });
    $("#es-llm-fehler").textContent = "";
    einstellungenLaden();
  } catch (err) { $("#es-llm-fehler").textContent = err.message; }
});

window.vorlaufZeigen = vorlaufZeigen;
window.erschliessungZeigen = erschliessungZeigen;
})();

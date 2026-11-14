// Modul 4 Bestand und Export in drei Spalten (Entscheidung 05.11.2026, docs/Feedback/Export-Interface.md; Server:
// tool/pakete.py, Rechencode: export/):
//   links   Übersicht, immer sichtbar: nach Platten oder nach Beständen, je Zeile Stand der Erschließung und was zu tun ist
//   Mitte   Aktionen untereinander wie die Platten der Analyse: Freigabe → Packen → Übergabe an K&R; darunter, erst nach
//           der Übergabe aller Pakete, Kontrolle in Anton und Abschlussbericht. Ein Klick wählt die Aktion
//   rechts  oben die Details der gewählten Aktion (beim Packen mit dem Lauf) oder des gewählten Pakets, darunter
//           kleiner alle Pakete als Liste wie die Datenträger der Analyse (Feedback 05.11.2026)
// Packen ist eine Anleitung (exAnleitung): Ablage und Größe, planen, Ablage anschließen, Platte für Platte anschließen;
// nach „Packen beginnen“ startet der Lauf einer Platte von selbst, sobald sie erkannt ist (exAutostart).
// Nutzt die Hilfen aus app.js ($, esc, zahl, bytes, holen, senden), icons.js (icon) und erfassung.js (SCHRITT_ZEICHEN,
// STATUS_KLASSE, dauer, ansichtZeigen, modulKopf). Die reinen Regeln oben laufen auch in Node (tests/test_export_anleitung.py).
"use strict";

const ex = { daten: null, sicht: "platten", auf: new Set(), schritt: null, offen: null, eintraege: {}, ablagen: null,
             abweichungen: null, fehler: "", takt: null, wahl: new Set(), notiz: "",
             gefuehrt: false,              // „Packen beginnen“ geklickt: Platten starten von selbst, sobald erkannt
             versucht: new Set(),          // Platten (bzw. "" für Ebenen), die in dieser Sitzung schon von selbst starteten
             veraltetOk: false };          // „mit dem bisherigen Plan weiterpacken“, obwohl sich etwas geändert hat
let exStand = null;                                // für den Ring im Kopf (erfassung.js, modulKopf)

const EX_STATUS = { geplant: ["geplant", ""], Fehler: ["Fehler", "warnung"], gebaut: ["geschrieben", ""],
                    "übergeben": ["übergeben", ""], importiert: ["in Anton", "gut"], "unvollständig": ["in Anton unvollständig", "warnung"] };
const EX_FERTIG = ["übergeben", "importiert", "unvollständig"];
const EX_MODUL = { erfassung: "Zur Analyse", bewertung: "Zur Bewertung", erschliessung: "Zur Erschließung" };

// ---------- Regeln (ohne DOM) ----------
// Paket noch zu schreiben oder nachzuprüfen?
const exPaketOffen = (x) => ["geplant", "Fehler"].includes(x.status) || (x.status === "gebaut" && !x.geprueft_am);
// Platten, die etwas zu packen haben, in fester Reihenfolge
const exPackPlatten = (s) => (s.platten || []).filter((x) => x.noetig && x.pakete)
  .sort((a, b) => a.platte_id.localeCompare(b.platte_id));
const exPlatteFertig = (x) => !x.offen && !x.ungeprueft;

// Schritte der Anleitung „Packen“; der erste nicht erledigte ist „aktuell“, die übrigen „offen“
function exAnleitung(s, o = {}) {
  const a = s.ablage || {}, p = s.pakete || [];
  const geplant = p.filter((x) => !EX_FERTIG.includes(x.status));
  // Eine Änderung nach dem Planen hält nur auf, solange noch etwas zu schreiben ist (sonst nur Hinweis beim Planen)
  const aufhalten = s.veraltet && !o.veraltetOk && geplant.some((x) => ["geplant", "Fehler"].includes(x.status));
  const liste = [{ k: "einstellungen", titel: "Ablage und Paketgröße wählen", erledigt: !!a.ort }];
  liste.push({ k: "planen", titel: aufhalten ? "Pakete neu planen" : "Pakete planen",
               erledigt: geplant.length ? !aufhalten : p.length > 0 && !s.exportierbar });
  if (a.ort && a.ort !== "projekt") liste.push({ k: "ablage", titel: `Ablage ${a.name || ""} anschließen`, erledigt: !!a.da });
  const platten = exPackPlatten(s);
  const ebenenOffen = p.some((x) => x.art === "ebenen" && exPaketOffen(x));
  if (ebenenOffen && platten.every(exPlatteFertig)) liste.push({ k: "ebenen", titel: "Neue Verzeichnungseinheiten schreiben (ohne Datenträger)", erledigt: false });
  for (const pl of platten) {
    liste.push({ k: `platte:${pl.platte_id}`, titel: `${pl.platte_id} ${pl.ordner ? "bereitstellen" : "anschließen"} und packen`,
                 platte: pl, erledigt: exPlatteFertig(pl) });
  }
  liste.push({ k: "fertig", titel: "Ablage an den Betreiber der Anton-Instanz geben", erledigt: false });
  let dran = false;
  for (const x of liste) {
    x.zustand = x.erledigt ? "erledigt" : dran ? "offen" : "aktuell";
    if (!x.erledigt) dran = true;
  }
  return liste;
}

// Was jetzt von selbst starten darf: Platten-ID, "" (nur Ebenen) oder null
function exAutostart(s, o = {}) {
  if (!o.gefuehrt || s.lauf?.aktiv) return null;
  const a = s.ablage || {};
  const dran = exAnleitung(s, o).find((x) => x.zustand === "aktuell");
  if (!dran || !a.da || !(dran.k === "ebenen" || dran.platte)) return null;
  const pid = dran.platte ? dran.platte.platte_id : "";
  const bedarf = (s.pakete || []).filter((x) => ["geplant", "Fehler"].includes(x.status) && (x.art === "ebenen" || x.platte_id === pid))
    .reduce((n, x) => n + (x.bytes || 0), 0);
  if (a.frei != null && a.frei - bedarf < (a.min_frei || 0)) return null;
  if (o.versucht?.has(pid)) return null;
  // Ordner als Quelle zählt als schreibgeschützt (Balduin liest ihn nur), ebenso ein Datenträger, für den dem Lesen
  // ohne Schreibschutz zugestimmt ist (Entscheidung 13.11.2026)
  const pl = dran.platte;
  if (pl && !(pl.angeschlossen && (pl.schreibgeschuetzt || pl.ordner || pl.ohne_schreibschutz))) return null;
  if (pl?.verschluesselt) return null;                // braucht das Passwort, das niemand gespeichert hat (13.11.2026)
  return pid;
}

// Packen von einem verschlüsselten Volume (13.11.2026): Passwort nur für diesen Lauf. Antwort: Passwort, undefined
// (nicht nötig) oder null (abgebrochen).
async function exPasswort(platteId) {
  const pl = (ex.daten?.platten || []).find((x) => x.platte_id === platteId);
  if (!pl?.verschluesselt) return undefined;
  return passwortGeprueft(`Passwort für ${platteId}`,
    "Der Datenträger ist verschlüsselt. Balduin speichert das Passwort nicht; es gilt nur für diesen Lauf.",
    (passwort) => senden("/api/passwort_pruefen", { platte_id: platteId, passwort }));
}

// Kontrolle und Abschlussbericht erst, wenn jedes Paket als übergeben vermerkt ist
const exNachImportFrei = (s) => (s.pakete || []).length > 0 && s.pakete.every((x) => EX_FERTIG.includes(x.status));

// für die Tests (tests/test_export_anleitung.py, Rauchtest tests/hilfen/oberflaeche.py)
if (typeof module !== "undefined") {
  module.exports = { ex, exAnleitung, exAutostart, exNachImportFrei, exAntonFrisch, exUebersicht, exAktionenHtml, exDetailHtml, exLaeufe,
                     exPaketeUebersicht, exEinstellungenHtml };
}

// ---------- Anzeige ----------
const exPille = (status) => `<span class="pille ${EX_STATUS[status]?.[1] || ""}">${esc(EX_STATUS[status]?.[0] || status)}</span>`;
const exZeit = (iso) => (iso ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)} ${iso.slice(11, 16)}` : "");
const exSichtbar = () => !$("#export").hidden;
const exAktiv = () => !!ex.daten?.lauf?.aktiv;
const exStunden = (b) => { const h = b * 8 / 100e6 / 3600; return h < 1 ? `${Math.max(1, Math.round(h * 60))} min` : `${h.toFixed(h < 10 ? 1 : 0).replace(".", ",")} h`; };
const exPakete = (n) => `${zahl(n)} ${n === 1 ? "Paket" : "Pakete"}`;
const exEtikett = (p) => (p.etikett ? `„${esc(p.etikett.split("\n")[0])}“` : "");

async function exportZeigen() {
  clearTimeout(ex.takt);
  try {
    const s = await holen("/api/export");
    ex.daten = s;
    exStand = s.modul;
    modulKopf();
    $("#ex-marke").hidden = !s.lauf?.aktiv;
    // von selbst starten (nur, wenn das Modul offen ist und „Packen beginnen“ geklickt wurde)
    const auto = exSichtbar() ? exAutostart(s, ex) : null;
    if (auto !== null) {
      ex.versucht.add(auto);
      ex.schritt = "packen";
      return exAusfuehren(() => senden("/api/export_starten", { platte_id: auto }));
    }
    const aktionen = exAktionen(s);
    if (ex.schritt === undefined || (ex.schritt && !aktionen.some((x) => x.k === ex.schritt && x.zustand !== "gesperrt"))) {
      ex.schritt = (aktionen.find((x) => x.zustand === "offen") || aktionen[0]).k;
    }
    exZeichnen();
    const warten = ex.gefuehrt && ex.schritt === "packen";       // auf die nächste Platte warten
    if ((s.lauf?.aktiv || s.anton_lauf?.aktiv || warten) && exSichtbar()) ex.takt = setTimeout(exportZeigen, warten && !s.lauf?.aktiv ? 3000 : 2000);
  } catch (err) {
    $("#ex-links").innerHTML = `<div class="fehler">${esc(err.message)}</div>`;
  }
}
ex.schritt = undefined;                            // beim ersten Öffnen: die erste offene Aktion aufklappen

function exZeichnen() {
  const s = ex.daten;
  exSetzen("#ex-links", exUebersicht(s));
  document.querySelectorAll("#ex-sicht [data-ex-sicht]").forEach((b) => b.classList.toggle("an", b.dataset.exSicht === ex.sicht));
  exSetzen("#ex-mitte", exAktionenHtml(s));
  $("#ex-detail-titel").textContent = exDetailTitel(s);
  exSetzen("#ex-detail", exDetailHtml(s) + `<div id="ex-fehler" class="fehler">${esc(ex.fehler)}</div>`);
  exSetzen("#ex-pakete", exPaketeUebersicht(s));
  $("#ex-pakete-kopf").textContent = s.pakete.length ? `${exPakete(s.pakete.length)}` : "";
  if (!$("#ex-einstellungen").hidden) $("#ex-einstellungen-inhalt").innerHTML = exEinstellungenHtml(s, "zahnrad");
}
// Neu zeichnen, ohne dass Aufgeklapptes zuklappt oder der Bildlauf springt (der Stand wird alle 2–3 s neu gezeichnet)
function exSetzen(sel, html) {
  const el = $(sel);
  const offen = new Set([...el.querySelectorAll("details[open] > summary")].map((x) => x.textContent.trim()));
  const oben = el.scrollTop;
  el.innerHTML = html;
  el.querySelectorAll("details > summary").forEach((x) => { if (offen.has(x.textContent.trim())) x.parentElement.open = true; });
  el.scrollTop = oben;
}

// ======================================================================================================
// Spalte 1: Übersicht nach Platten oder nach Beständen
// ======================================================================================================
function exStandHtml(z) {
  const u = z.uebernommen || 0, e = z.erschlossen || 0;
  if (!u) return `<div class="leise">nichts übernommen</div>`;
  return `<div class="ex-stand"><span>erschlossen <b>${zahl(e)}</b> von ${zahl(u)}</span>
      <span class="ex-spur ${e >= u ? "voll" : ""}"><i style="width:${(100 * e / u).toFixed(1)}%"></i></span></div>
    <div class="leise">${zahl(z.bereit || 0)} bereit${z.bereit_bytes ? ` · ${bytes(z.bereit_bytes)}` : ""} · ${zahl(z.geliefert || 0)} geliefert</div>`;
}

// Nur, was ausschließt oder eine Handlung braucht; reine Hinweise stehen unten gesammelt
const exWichtig = (f) => f.art === "fehler" || f.schluessel === "nicht_zugeordnet" || f.schluessel === "akteur_neu";
function exAufgabenHtml(liste) {
  const wichtig = (liste || []).filter(exWichtig);
  if (!wichtig.length) return "";
  return `<ul class="ex-aufgaben">${wichtig.map((f) => `<li class="${f.art === "fehler" ? "ex-muss" : "ex-kann"}">
      ${icon(f.art === "fehler" ? "circle-alert" : "info")}
      <span><b>${zahl(f.anzahl)}</b> ${esc(f.text)}<span class="ex-tun">→ ${esc(f.tun)}</span></span>
      ${f.ansicht ? `<button type="button" class="knopf-leise" data-ex-ansicht="${esc(f.ansicht)}">${esc(EX_MODUL[f.ansicht] || f.ansicht)}</button>` : ""}</li>`).join("")}</ul>`;
}

function exUebersicht(s) {
  const zahlen = `<div class="ex-zahlen">
      <div><b>${zahl(s.uebernommen)}</b><span class="leise">übernommen</span></div>
      <div><b>${zahl(s.exportierbar)}</b><span class="leise">bereit · ${bytes(s.bytes)}</span></div>
      <div><b>${zahl(s.modul.in_anton)}</b><span class="leise">in Anton</span></div></div>`;
  const zeilen = ex.sicht === "platten" ? exNachPlatten(s) : exNachBestaenden(s);
  const k = s.kontrolle;
  const nebenbei = k.hinweise.filter((f) => !exWichtig(f));
  return `${zahlen}
    <div class="leise">${ex.sicht === "platten" ? "Je Datenträger die Bestände, in die er liefert; anklicken für die Zahlen je Bestand."
      : "Je Bestand in Anton die Datenträger, die er braucht; anklicken für die Zahlen je Datenträger."}
      „Bereit“ heißt: übernommen, erschlossen, zugeordnet und ohne Fehler.</div>
    <ul class="erf-liste ex-uebersicht">${zeilen}</ul>
    ${(k.akzession || []).map((b) => `<div class="hinweis warnung">${icon("circle-alert")} <b>${esc(b.signatur || "")} ${esc(b.titel)}</b>
        liegt wohl im Akzessionsarchiv (Titel enthält „Akzession“) und ist kein Ziel für ein Paket. In der Erschließung einer anderen
        bestehenden Verzeichnungseinheit zuordnen oder mit dem Betreiber der Anton-Instanz klären.</div>`).join("")}
    ${k.mehrere_platten.length || nebenbei.length ? `<div class="ueberschrift">Hinweise</div>` : ""}
    ${k.mehrere_platten.length ? `<details class="ex-befund"><summary><b>${zahl(k.mehrere_platten.length)}</b> Einheiten bekommen
        Dateien von mehreren Datenträgern: Anton zählt die Signaturen in der Reihenfolge der Pakete, sie mischen sich. Wenn möglich je
        Einheit nur einen Datenträger zuordnen.</summary><ul>${k.mehrere_platten.slice(0, 20).map((m) => `<li>${esc(m.einheit)}
        <span class="leise">${m.platten.map(esc).join(", ")}</span></li>`).join("")}</ul></details>` : ""}
    ${exBefunde(nebenbei, "")}`;
}

function exNachPlatten(s) {
  if (!s.platten.length) return `<li class="leise">Kein Datenträger im Projekt.</li>`;
  return s.platten.map((p) => {
    const auf = ex.auf.has(`p:${p.platte_id}`);
    const bestaende = p.bestaende || [];
    return `<li class="dt ex-zeile ${auf ? "gewaehlt" : ""}" data-ex-auf="p:${esc(p.platte_id)}">
      <div class="dt-zeile">${icon(auf ? "chevron-down" : "chevron-right")}<span class="pille kennung">${esc(p.platte_id)}</span>
        <span class="leise">${esc(p.volume || "")}</span>${p.angeschlossen ? `<span class="pille gut">${p.abbild ? "Abbild da" : p.ordner ? "Ordner da" : "angeschlossen"}</span>` : ""}</div>
      ${p.etikett ? `<div class="leise">${exEtikett(p)}</div>` : ""}
      ${exStandHtml(p)}
      ${bestaende.length ? `<div class="ex-klein">${icon("layers")} ${bestaende.map((b) => esc(b.signatur || b.titel)).join(" · ")}</div>` : ""}
      ${exAufgabenHtml(p.aufgaben)}
      ${auf ? `<ul class="ex-unterliste">${bestaende.map((b) => `<li>
          <div class="dt-zeile"><b>${esc(b.signatur || "")}</b> ${esc(b.titel)}</div>
          ${exStandHtml(b)}${exAufgabenHtml(b.aufgaben)}</li>`).join("") || `<li class="leise">Noch keinem Bestand zugeordnet.</li>`}</ul>` : ""}
    </li>`;
  }).join("");
}

function exNachBestaenden(s) {
  const da = Object.fromEntries(s.platten.map((p) => [p.platte_id, p]));
  if (!s.bestaende.length) return `<li class="leise">Noch keine bestehende Verzeichnungseinheit geladen (in der Erschließung, rechte Spalte).</li>`;
  return s.bestaende.map((b) => {
    const schluessel = `b:${b.anton_id ?? "ohne"}`;
    const auf = ex.auf.has(schluessel);
    return `<li class="dt ex-zeile ${auf ? "gewaehlt" : ""} ${b.anton_id == null ? "ex-ohne" : ""}" data-ex-auf="${esc(schluessel)}">
      <div class="dt-zeile">${icon(auf ? "chevron-down" : "chevron-right")}${b.signatur ? `<b>${esc(b.signatur)}</b>` : ""} ${esc(b.titel)}
        ${b.link ? `<a class="leise" href="${esc(b.link)}" target="_blank" rel="noopener" title="In Anton öffnen">${icon("external-link")}</a>` : ""}</div>
      ${exStandHtml(b)}
      ${b.platten.length ? `<div class="ex-klein">${icon("hard-drive")} braucht ${b.platten.map((p) => `${esc(p.platte_id)}${da[p.platte_id]?.angeschlossen ? " (angeschlossen)" : ""}`).join(" · ")}</div>`
        : `<div class="leise">Noch nichts zugeordnet.</div>`}
      ${exAufgabenHtml(b.aufgaben)}
      ${auf ? `<ul class="ex-unterliste">${b.platten.map((p) => `<li>
          <div class="dt-zeile"><span class="pille kennung">${esc(p.platte_id)}</span>
            ${da[p.platte_id]?.angeschlossen ? `<span class="pille gut">angeschlossen</span>` : ""}</div>
          ${exStandHtml(p)}${exAufgabenHtml(p.aufgaben)}</li>`).join("") || `<li class="leise">Kein Datenträger liefert hierher.</li>`}</ul>` : ""}
    </li>`;
  }).join("");
}

function exBefunde(eintraege, klasse) {
  return eintraege.map((f) => `<details class="ex-befund ${klasse}">
      <summary><b>${zahl(f.anzahl)}</b> ${esc(f.text)}</summary>
      <ul>${f.beispiele.map((b) => `<li><span class="pille kennung">${esc(b.platte)}</span> ${esc(b.pfad)}</li>`).join("")}
        ${f.anzahl > f.beispiele.length ? `<li class="leise">… und ${zahl(f.anzahl - f.beispiele.length)} weitere</li>` : ""}</ul>
    </details>`).join("");
}

// ======================================================================================================
// Spalte 2: Aktionen
// ======================================================================================================
function exAktionen(s) {
  const p = s.pakete;
  const gebaut = p.filter((x) => x.status === "gebaut");
  const uebergeben = p.filter((x) => EX_FERTIG.includes(x.status));
  const erfuellt = s.freigabe.punkte.filter((x) => x.ok).length;
  const dran = exAnleitung(s, ex).find((x) => x.zustand === "aktuell");
  const frei = exNachImportFrei(s);
  return [
    { k: "freigabe", nr: 1, titel: "Freigabe", zustand: s.freigabe.ok ? "erledigt" : "offen",
      info: `${erfuellt} von ${s.freigabe.punkte.length} Punkten erfüllt${s.freigabe.ok ? "" : s.probe ? " · Testinstanz: Probe möglich" : " · nötig für die Übergabe"}` },
    { k: "packen", nr: 2, titel: "Packen", zustand: dran?.k === "fertig" && p.length ? "erledigt" : "offen",
      info: dran?.k === "fertig" ? (p.length ? `${exPakete(p.length)} geschrieben` : "nichts zu packen")
        : `als Nächstes: ${dran?.titel || ""}${ex.gefuehrt ? " · Anleitung läuft" : ""}` },
    { k: "uebergabe", nr: 3, titel: "Übergabe an den Betreiber", zustand: gebaut.length ? "offen" : uebergeben.length ? "erledigt" : "gesperrt",
      info: gebaut.length ? `${exPakete(gebaut.length)} bereit · ${bytes(gebaut.reduce((n, x) => n + (x.datei_bytes || 0), 0))}`
        : uebergeben.length ? `${exPakete(uebergeben.length)} übergeben` : "noch nichts geschrieben" },
    { k: "kontrolle", nr: 4, titel: "Kontrolle in Anton", nach: true,
      zustand: !frei ? "gesperrt" : uebergeben.every((x) => x.status === "importiert") ? "erledigt" : "offen",
      info: frei ? `${zahl(s.modul.in_anton)} von ${zahl(s.modul.gesamt)} Dateien in Anton` : "nach dem Import aller Pakete" },
    { k: "bericht", nr: 5, titel: "Abschlussbericht", nach: true, zustand: !frei ? "gesperrt" : s.bericht ? "erledigt" : "offen",
      info: s.bericht ? `gespeichert ${new Date(s.bericht.zeit * 1000).toLocaleDateString("de-CH")}` : "für das Archiv: erfasst, kassiert, übernommen" },
  ];
}

function exAktionenHtml(s) {
  const liste = exAktionen(s);
  const frei = exNachImportFrei(s);
  const zeichen = { erledigt: icon("check"), gesperrt: icon("lock") };
  const zeile = (x) => {
    const gewaehlt = ex.schritt === x.k && x.zustand !== "gesperrt" && ex.offen == null;
    return `<li class="dt ex-schritt ex-${x.zustand} ${gewaehlt ? "gewaehlt" : ""}" ${x.zustand === "gesperrt" ? "" : `data-ex-schritt="${x.k}"`}>
        <div class="dt-zeile"><span class="ex-nr">${zeichen[x.zustand] || x.nr}</span><b>${esc(x.titel)}</b>
          <span class="ex-klapp">${x.zustand === "gesperrt" ? "" : icon("chevron-right")}</span></div>
        <div class="leise">${esc(x.info)}</div></li>`;
  };
  return `<ul class="erf-liste ex-aktionen">${liste.filter((x) => !x.nach).map(zeile).join("")}</ul>
    <div class="ueberschrift ex-nach-kopf">Nach dem Import in Anton</div>
    ${frei ? "" : `<div class="leise">Frei, sobald jedes Paket an den Betreiber der Anton-Instanz übergeben und hier als übergeben vermerkt ist.</div>`}
    <ul class="erf-liste ex-aktionen ${frei ? "" : "ex-nach-gesperrt"}">${liste.filter((x) => x.nach).map(zeile).join("")}</ul>`;
}

// ======================================================================================================
// Spalte 3 oben: Details der gewählten Aktion oder des gewählten Pakets
// ======================================================================================================
const EX_PANEL = { freigabe: exFreigabe, packen: exPacken, uebergabe: exUebergabe, kontrolle: exKontrolle, bericht: exBericht };
function exDetailTitel(s) {
  const p = ex.offen != null && s.pakete.find((x) => x.paket_id === ex.offen);
  if (p) return p.name;
  return exAktionen(s).find((x) => x.k === ex.schritt)?.titel || "Details";
}
function exDetailHtml(s) {
  const p = ex.offen != null && s.pakete.find((x) => x.paket_id === ex.offen);
  if (p) return exPaketHtml(p, true);
  const x = exAktionen(s).find((a) => a.k === ex.schritt && a.zustand !== "gesperrt");
  if (!x) return `<div class="leer-hinweis">Links in der Mitte eine Aktion wählen.</div>`;
  // Beim Packen und während eines Laufs gehört der Lauf dazu (wie die Läufe in der Analyse)
  const lauf = (x.k === "packen" || s.lauf?.aktiv) && s.lauf ? `<div class="ueberschrift">Lauf</div>${exLaeufe(s)}` : "";
  return EX_PANEL[x.k](s) + lauf;
}

// ---------- Freigabe ----------
function exFreigabe(s) {
  const f = s.freigabe;
  const anton = s.anton_lauf?.aktiv;
  const knopf = (x) => {
    if (x.punkt === "erschliessung") return x.ok ? "" : `<button type="button" class="knopf-leise" data-ex-ansicht="erschliessung">Zur Erschließung</button>`;
    if (x.punkt === "dubletten" || x.punkt === "dateien") return x.ok ? "" : `<button type="button" class="knopf-leise" data-ex-ansicht="bewertung">Zur Bewertung</button>`;
    if (x.punkt === "anton") return `<button type="button" class="knopf-leise" data-ex-anton ${anton ? "disabled" : ""}>${icon("refresh-cw")}
      ${anton ? "Bestand aus Anton wird geholt …" : "Bestand aus Anton holen"}</button>`;
    if (x.punkt === "importformat") return `<button type="button" class="knopf-leise" data-ex-importformat>${icon("refresh-cw")} Jetzt abfragen</button>`;
    return "";
  };
  const lese = (x) => (x.platten || []).filter((p) => p.anzahl).map((p) => `<details class="ex-befund ${p.quittiert ? "" : "fehler-befund"}">
      <summary><span class="pille kennung">${esc(p.platte_id)}</span> <b>${zahl(p.anzahl)}</b> nicht lesbare Pfade
        ${p.quittiert ? `<span class="pille gut">quittiert ${esc(exZeit(p.quittiert_am))}</span>` : ""}</summary>
      <ul>${p.beispiele.map((b) => `<li>${esc(b.pfad)} <span class="leise">${esc(b.fehler)}</span></li>`).join("")}
        ${p.anzahl > p.beispiele.length ? `<li class="leise">… und ${zahl(p.anzahl - p.beispiele.length)} weitere</li>` : ""}</ul>
      ${p.quittiert ? "" : `<div class="knopfzeile"><button type="button" class="knopf-leise" data-ex-quittieren="${esc(p.platte_id)}">${icon("check")}
        Gesehen, quittieren</button></div>`}</details>`).join("");
  return `<div class="leise">Bevor der Bestand an Anton geht, muss er feststehen (Absprache mit dem Betreiber der Anton-Instanz). Jeder Punkt
      wird aus den Daten bestimmt; was bei der Erschließung fehlt, zeigt die Übersicht links.</div>
    <ul class="erf-liste ex-freigabe">${f.punkte.map((x) => `<li class="${x.ok ? "ex-ok" : "ex-nein"}">
      <div class="dt-zeile"><span class="ex-nr">${x.ok ? icon("check") : icon("circle-alert")}</span><b>${esc(x.titel)}</b></div>
      <div class="leise">${esc(x.text)}</div>${x.punkt === "lesefehler" ? lese(x) : ""}
      <div class="knopfzeile">${knopf(x)}</div></li>`).join("")}</ul>
    ${f.ok ? "" : `<div class="hinweis">Packen geht schon jetzt: mit kommt, was bereit ist, der Rest bleibt vorerst draußen.
      ${s.probe ? `Anton-Adresse ist eine Testinstanz (${esc(s.einstellungen.anton_url)}): Die Übergabe geht auch ohne volle
      Freigabe und wird als <b>Probe</b> vermerkt.` : "<b>Als übergeben vermerken</b> an eine produktive Anton-Instanz geht erst, wenn alle Punkte erfüllt sind."}</div>`}`;
}

// ---------- Packen: Anleitung ----------
function exPacken(s) {
  const liste = exAnleitung(s, ex);
  return `<ol class="ex-anleitung">${liste.map((x, i) => `<li class="ex-a-${x.zustand}">
      <span class="ex-nr">${x.zustand === "erledigt" ? icon("check") : i + 1}</span>
      <div><b>${esc(x.titel)}</b>${x.zustand === "aktuell" ? exSchrittJetzt(s, x, liste[i - 1]) : exSchrittKurz(s, x)}</div></li>`).join("")}</ol>`;
}

// Kurzzeile für erledigte und spätere Schritte
function exSchrittKurz(s, x) {
  const a = s.ablage, e = s.einstellungen;
  const geplant = s.pakete.filter((p) => !EX_FERTIG.includes(p.status));
  if (x.k === "einstellungen") {
    return x.erledigt ? `<div class="leise">${esc(a.name)} · höchstens ${zahl(e.dateien_je_paket)} Dateien${e.gb_je_paket ? ` und ${zahl(e.gb_je_paket)} GB` : ""} je Paket ·
      ändern in den Einstellungen (${icon("settings")} am Knopf „Bestand und Export“)</div>` : "";
  }
  if (x.k === "planen") {
    return x.erledigt && geplant.length ? `<div class="leise">${exPakete(geplant.length)} · ${zahl(geplant.reduce((n, p) => n + (p.dateien || 0), 0))} Dateien ·
      ${bytes(geplant.reduce((n, p) => n + (p.bytes || 0), 0))}${s.geplant_am ? ` · geplant ${esc(exZeit(s.geplant_am))}` : ""}
      <button type="button" class="knopf-leise knopf-klein" id="ex-planen">neu planen</button></div>
      ${s.veraltet ? `<div class="leise warnung-text">Bewertung oder Erschließung haben sich seither geändert; die geschriebenen Pakete
        enthalten das noch nicht. Neu planen verwirft sie.</div>` : ""}` : "";
  }
  if (x.k === "ablage") return x.erledigt ? `<div class="leise">angeschlossen · ${bytes(a.frei)} frei</div>` : "";
  if (x.platte) {
    const pl = x.platte;
    return x.erledigt ? `<div class="leise">${exPakete(pl.pakete)} geschrieben und nachgeprüft${pl.angeschlossen && !pl.ordner ? " · kann abgezogen werden" : ""}</div>`
      : `<div class="leise">${exPakete(pl.offen + pl.ungeprueft)} · ${zahl(pl.offen_dateien || 0)} Dateien · ${bytes(pl.offen_bytes || 0)}${pl.etikett ? ` · ${exEtikett(pl)}` : ""}</div>`;
  }
  return "";
}

// Ausführlich für den Schritt, der dran ist
function exSchrittJetzt(s, x, vorher) {
  const a = s.ablage;
  if (x.k === "einstellungen") {
    return `<div class="leise">Beim ersten Packen: Wohin sollen die Pakete, und wie groß darf eines werden? Später in den Einstellungen
      (${icon("settings")} am Knopf „Bestand und Export“) änderbar.</div>${exEinstellungenHtml(s, "schritt")}`;
  }
  if (x.k === "planen") {
    const geplant = s.pakete.some((p) => !EX_FERTIG.includes(p.status));
    return `<div class="leise">Balduin teilt alles Bereite in Pakete: je Datenträger und Bestand in Anton, geteilt nach der Paketgröße. Dafür
      braucht es keinen Datenträger; übergebene Pakete bleiben stehen.</div>
      ${s.veraltet && geplant ? `<div class="hinweis warnung">Bewertung oder Erschließung haben sich seit dem letzten Planen geändert.</div>` : ""}
      ${!s.freigabe.ok ? `<div class="hinweis">Die Freigabe ist noch offen: Geplant werden die ${zahl(s.exportierbar)} bereiten Dateien,
        der Rest kommt bei einem späteren Planen dazu.</div>` : ""}
      <div class="knopfzeile"><button type="button" id="ex-planen" class="haupt" ${s.exportierbar ? "" : "disabled"}>${icon("layers")}
        ${geplant ? "Neu planen" : "Pakete planen"}</button>
        ${s.veraltet && geplant ? `<button type="button" class="knopf-leise" data-ex-veraltet-ok>Mit dem bisherigen Plan weiterpacken</button>` : ""}</div>
      ${s.exportierbar ? "" : `<div class="leise tipp">Nichts bereit: Die Übersicht links zeigt, was zu tun ist.</div>`}`;
  }
  if (x.k === "ablage") {
    return `<div class="ex-jetzt">${icon("plug")} Ablage <b>${esc(a.name)}</b> anschließen. Balduin erkennt sie von selbst.</div>`;
  }
  if (x.k === "fertig") {
    const gebaut = s.pakete.filter((p) => p.status === "gebaut").length;
    return gebaut ? `<div class="ex-jetzt">${icon("send")} Alle Pakete sind geschrieben und nachgeprüft. Ablage
        <b>${esc(a.name)}</b> an den Betreiber der Anton-Instanz geben und unter „Übergabe an den Betreiber“ vermerken.</div>
        ${vorher?.platte?.angeschlossen && !vorher.platte.ordner ? `<div class="leise">${esc(vorher.platte.platte_id)} kann abgezogen werden.</div>` : ""}
        <div class="knopfzeile"><button type="button" class="haupt" data-ex-schritt="uebergabe">Zur Übergabe ${icon("arrow-right")}</button></div>`
      : s.pakete.length ? `<div class="leise">Alles gepackt und übergeben. Was neu bereit wird, kommt beim nächsten Planen dazu.</div>`
      : `<div class="leise">Nichts zu packen.</div>`;
  }
  // Ebenen oder eine Platte
  const pl = x.platte;
  const l = s.lauf;
  const laeuft = l?.aktiv && (pl ? l.platte_id === pl.platte_id : !l.platte_id);
  const ebenenMit = pl && s.pakete.some((p) => p.art === "ebenen" && exPaketOffen(p));
  const pid = pl ? pl.platte_id : "";
  const bedarf = s.pakete.filter((p) => ["geplant", "Fehler"].includes(p.status) && (p.art === "ebenen" || p.platte_id === pid))
    .reduce((n, p) => n + (p.bytes || 0), 0);
  const gesperrt = exAktiv() && !laeuft ? "Gerade läuft ein anderer Export (rechts)."
    : !a.da ? `Die Ablage ${a.name || ""} ist nicht angeschlossen.`
    : pl && !pl.angeschlossen ? "" : pl && !pl.schreibgeschuetzt && !pl.ordner && !pl.ohne_schreibschutz ? "beschreibbar"
    : a.frei != null && a.frei - bedarf < a.min_frei ? `Auf der Ablage ist zu wenig frei (${bytes(a.frei)}, nötig ${bytes(bedarf)}).` : "";
  const abziehen = vorher?.platte?.angeschlossen && !vorher.platte.ordner
    ? `<div class="ex-jetzt">${icon("unplug")} <b>${esc(vorher.platte.platte_id)}</b> abziehen.</div>` : "";
  let jetzt;
  if (laeuft) {
    jetzt = `<div class="ex-jetzt">${icon("package")} ${pl ? `<b>${esc(pl.platte_id)}</b> wird gepackt` : "Die neuen Ebenen werden geschrieben"}
      (Fortschritt rechts). ${pl && !pl.ordner ? "Den Datenträger angeschlossen lassen, bis der Lauf fertig ist." : ""}</div>`;
  } else if (pl && !pl.angeschlossen && pl.ordner) {
    jetzt = `<div class="hinweis warnung">${pl.abbild ? "Das Abbild" : "Den Ordner"} von ${esc(pl.platte_id)} gibt es nicht mehr unter <span class="mono">${esc(pl.quellordner || "")}</span>;
      unter Registrierung/Analyse den neuen Ort wählen. <button type="button" class="knopf-leise" data-ex-ansicht="erfassung">Zur Analyse</button></div>`;
  } else if (pl && !pl.angeschlossen) {
    jetzt = `${abziehen}<div class="ex-jetzt">${icon("plug")} <b>${esc(pl.platte_id)}</b> anschließen${pl.etikett ? ` (Etikett ${exEtikett(pl)})` : ""}.
        Balduin erkennt sie an ihrer UUID${ex.gefuehrt ? " und beginnt dann von selbst" : ""}.</div>`;
  } else if (gesperrt === "beschreibbar") {
    // unter Windows lässt sich nicht schreibgeschützt einhängen: nur die Rückfrage (Entscheidung 13.11.2026)
    const kein = systemwort("kein_schreibschutz");
    jetzt = `${abziehen}<div class="hinweis warnung">${esc(pl.platte_id)} ist beschreibbar eingehängt. ${kein ? esc(kein) + " " : ""}Gepackt wird
      ${kein ? "nach Zustimmung ohne Schreibschutz oder über einen Writeblocker." : "schreibgeschützt oder nach Zustimmung ohne Schreibschutz."}
      <div class="knopfzeile">${kein ? "" : `<button type="button" class="knopf-leise" data-ex-einhaengen="${esc(pl.mountpunkt)}">Schreibgeschützt einhängen</button>`}
        <button type="button" class="knopf-leise" data-ex-ohne-schutz="${esc(pl.platte_id)}">Ohne Schreibschutz lesen …</button></div></div>`;
  } else {
    jetzt = pl ? `${abziehen}<div class="ex-jetzt">${icon("check")} ${pl.ordner ? `Der Ordner von <b>${esc(pl.platte_id)}</b> ist da.`
      : pl.schreibgeschuetzt ? `<b>${esc(pl.platte_id)}</b> ist schreibgeschützt angeschlossen.`
      : `<b>${esc(pl.platte_id)}</b> ist angeschlossen und wird ohne Schreibschutz gelesen (zugestimmt).`}</div>` : "";
  }
  const knoepfe = laeuft ? "" : !ex.gefuehrt
    ? `<button type="button" class="haupt" data-ex-beginnen ${a.da ? "" : "disabled"}>${icon("play")} Packen beginnen</button>`
    : `${pl?.angeschlossen && ex.versucht.has(pid) && !gesperrt ? `<button type="button" class="haupt" data-ex-starten="${esc(pid)}">${icon("package")} ${esc(pid)} packen</button>` : ""}
       ${!pl && ex.versucht.has("") && !gesperrt ? `<button type="button" class="haupt" data-ex-starten="">${icon("package")} Ebenen schreiben</button>` : ""}
       <button type="button" class="knopf-leise" data-ex-anhalten>${icon("pause")} Anleitung anhalten</button>`;
  return `${jetzt}
    <div class="leise">${exPakete(s.pakete.filter((p) => exPaketOffen(p) && (pl ? p.platte_id === pid : p.art === "ebenen")).length)} ·
      ${bytes(bedarf)}${bedarf ? ` · ca. ${exStunden(bedarf * 2)} mit rund 100 MB/s, Nachprüfen eingeschlossen` : ""}</div>
    ${ebenenMit ? `<div class="leise">Die neuen Ebenen (ohne Dateien) werden dabei mitgeschrieben.</div>` : ""}
    ${gesperrt && gesperrt !== "beschreibbar" ? `<div class="leise tipp">${esc(gesperrt)}</div>` : ""}
    <div class="knopfzeile">${knoepfe}</div>
    ${!ex.gefuehrt && !laeuft ? `<div class="leise tipp">Ab „Packen beginnen“ startet jeder Datenträger von selbst, sobald er schreibgeschützt
      (oder nach Zustimmung ohne Schreibschutz) angeschlossen ist: Balduin liest jede Datei einmal (MD5 und SHA-256 gegen die Analyse), schreibt sie ins Paket auf der Ablage und
      prüft das Paket nach. Abbrechen geht jederzeit; „Fortsetzen“ macht nach der letzten Datei weiter.</div>` : ""}
    ${ex.gefuehrt && ex.versucht.has(pid) && !laeuft && s.lauf && s.lauf.status !== "fertig" ? `<div class="leise tipp">Der letzte Lauf ist
      nicht fertig geworden (rechts): fortsetzen oder neu starten.</div>` : ""}`;
}

// Ablage und Paketgröße: im Schritt Packen beim ersten Mal und im Zahnrad (wo = "schritt" | "zahnrad")
function exEinstellungenHtml(s, wo) {
  const a = s.ablage, e = s.einstellungen;
  const je = [1000, 2000, 5000, 10000];
  if (!je.includes(e.dateien_je_paket)) je.push(e.dateien_je_paket);
  const gb = [0, 50, 100, 250, 500, 1000];
  if (!gb.includes(e.gb_je_paket)) gb.push(e.gb_je_paket);
  const bedarf = s.pakete.filter((p) => !EX_FERTIG.includes(p.status)).reduce((n, p) => n + (p.bytes || 0), 0) || s.bytes;
  const wahl = ex.ablagen ? `<div class="ex-ablagen">${ex.ablagen.map((x) => `<label class="option"><input type="radio" name="ex-ablage-${wo}"
        value="${esc(x.mountpunkt)}" ${x.mountpunkt === (a.ort === "projekt" ? "projekt" : a.wurzel) ? "checked" : ""}>
        <span><b>${esc(x.name)}</b>${x.arbeitsplatte ? ` <span class="pille">für Vorschaubilder</span>` : ""}
        <span class="leise">${bytes(x.frei)} frei${x.frei < bedarf ? " · reicht nicht für alles auf einmal" : ""}</span></span></label>`).join("")}
      <div class="knopfzeile"><button type="button" class="haupt" data-ex-ablage-ok="${wo}">Als Ablage nehmen</button>
        ${a.ort ? `<button type="button" data-ex-ablage-zu>Abbrechen</button>` : `<button type="button" class="knopf-leise" data-ex-ablagen>${icon("refresh-cw")} Neu suchen</button>`}</div>
      <div class="leise">Registrierte Datenträger stehen nicht zur Wahl. Auf einem Datenträger schreibt Balduin nur in <span class="mono">…/&lt;Projekt&gt;/export</span>.</div></div>`
    : `<div class="leise">Angeschlossene Datenträger werden gesucht …</div>`;
  return `<div class="ex-einstellungen-block">
    <div class="ueberschrift">Ablage</div>
    <div class="leise">Wohin die Pakete geschrieben werden. Dieser Datenträger (oder der Ordner) geht danach an den Betreiber der Anton-Instanz.</div>
    ${a.ort ? `<dl class="angaben-liste">
      <dt>Ablage</dt><dd><b>${esc(a.name)}</b> ${a.da ? `<span class="pille gut">angeschlossen</span>` : `<span class="pille warnung">nicht angeschlossen</span>`}</dd>
      <dt>Ordner</dt><dd class="mono">${esc(a.ordner || "")}</dd>
      ${a.da ? `<dt>Frei</dt><dd>${bytes(a.frei)} · Pakete dort ${bytes(a.belegt)}</dd>` : ""}
      <dt>Bedarf</dt><dd>${bytes(bedarf)} für alles noch nicht Übergebene</dd></dl>` : ""}
    ${!a.ort || ex.ablagen ? wahl : `<div class="knopfzeile"><button type="button" class="knopf-leise" data-ex-ablagen>${icon("hard-drive")} Andere Ablage wählen …</button>
      ${a.da ? `<button type="button" class="knopf-leise" data-ex-zeigen="">${icon("folder-open")} Im ${systemwort("dateimanager")} zeigen</button>` : ""}</div>`}
    <div class="ueberschrift">Größe eines Pakets</div>
    <div class="ex-einstellungen">
      <label>Höchstens <select data-ex-groesse="dateien">${je.sort((x, y) => x - y).map((n) => `<option value="${n}" ${n === e.dateien_je_paket ? "selected" : ""}>${zahl(n)}</option>`).join("")}</select> Dateien je Paket</label>
      <label>und höchstens <select data-ex-groesse="gb">${gb.sort((x, y) => x - y).map((n) => `<option value="${n}" ${n === e.gb_je_paket ? "selected" : ""}>${n ? `${zahl(n)} GB` : "ohne Grenze"}</option>`).join("")}</select></label>
      <div class="leise">Abgesprochen sind höchstens 10'000 Dateien; jedes Paket löst bei Anton eine Sicherung aus, und ein Import muss in
        ein Zeitfenster passen. Titel und Notizen in der Sprache <b>${esc(e.sprache)}</b> · Ziel ${esc(e.anton_url)}</div>
    </div></div>`;
}

// ---------- Übergabe an K&R ----------
function exUebergabe(s) {
  const bereit = s.pakete.filter((p) => p.status === "gebaut");
  const ungeprueft = bereit.filter((p) => !p.geprueft_am);
  for (const id of [...ex.wahl]) if (!bereit.some((p) => p.paket_id === id && p.geprueft_am)) ex.wahl.delete(id);
  const gewaehlt = bereit.filter((p) => ex.wahl.has(p.paket_id));
  const summe = gewaehlt.reduce((n, p) => n + (p.datei_bytes || 0), 0);
  const gesperrt = !s.probe && !s.freigabe.ok;
  return `${s.probe ? `<div class="hinweis">Anton-Adresse ist eine Testinstanz (${esc(s.einstellungen.anton_url)}): Die Übergabe wird als
      <b>Probe</b> vermerkt. Steht die Adresse später auf einer produktiven Instanz, zählen Probe-Übergaben nicht als geliefert.</div>` : ""}
    ${gesperrt ? `<div class="hinweis warnung">Übergabe an eine produktive Instanz erst nach vollständiger Freigabe.
      <button type="button" class="knopf-leise" data-ex-schritt="freigabe">Zur Freigabe</button></div>` : ""}
    <div class="leise">Die Ablage <b>${esc(s.ablage.name || "")}</b> mit den Paketen geht an den Betreiber der Anton-Instanz. Dort kommen sie per
      SSH in den Ordner <span class="mono">sips</span> der Instanz, und der Import läuft in einem abgesprochenen
      Zeitfenster (in Anton erfasst dann niemand). Auf der Ablage liegen dazu <span class="mono">lieferung.csv</span> (Reihenfolge),
      <span class="mono">SHA256SUMS</span> und <span class="mono">LIESMICH.txt</span>. Wie der Import per SSH abläuft, beschreibt die
      <a href="https://documentation.anton.ch/admin/agate-sip/" target="_blank" rel="noopener">Anton-Dokumentation „agate SIP-Import“</a>.</div>
    ${s.ablage.da ? `<div class="knopfzeile"><button type="button" class="knopf-leise" data-ex-zeigen="">${icon("folder-open")} Ablage im ${systemwort("dateimanager")} zeigen</button></div>` : ""}
    ${bereit.length ? `<ul class="erf-liste ex-wahlliste">${bereit.map((p) => `<li><label class="option"><input type="checkbox" data-ex-wahl="${p.paket_id}"
        ${ex.wahl.has(p.paket_id) ? "checked" : ""} ${p.geprueft_am ? "" : "disabled"}><span><b>${esc(p.name)}</b>
        <span class="leise">${zahl(p.dateien)} Dateien · ${bytes(p.datei_bytes || 0)}${p.geprueft_am ? "" : " · noch nicht nachgeprüft"}</span></span></label></li>`).join("")}</ul>
      <div class="knopfzeile"><button type="button" class="knopf-leise" data-ex-alle>Alle nachgeprüften wählen</button></div>
      <div class="felder"><label>Wie übergeben (Notiz, z. B. „Datenträger per Post, 06.11.“)<input id="ex-notiz" value="${esc(ex.notiz)}"></label></div>
      <div class="knopfzeile"><button type="button" class="haupt" data-ex-uebergeben ${gewaehlt.length && !gesperrt ? "" : "disabled"}>${icon("send")}
        ${gewaehlt.length ? `${exPakete(gewaehlt.length)} als ${s.probe ? "Probe " : ""}übergeben vermerken` : "Als übergeben vermerken"}</button></div>
      ${gewaehlt.length ? `<div class="leise">${bytes(summe)}; über eine Leitung mit 100 Mbit/s rund ${exStunden(summe)}.</div>` : ""}
      ${ungeprueft.length ? `<div class="leise tipp">Noch nicht nachgeprüft: ${exPakete(ungeprueft.length)} (Lauf des Datenträgers fortsetzen).</div>` : ""}`
    : `<div class="leise">Kein geschriebenes Paket wartet. Übergebene Pakete stehen rechts unter „Pakete“.</div>`}`;
}

// ---------- Kontrolle in Anton ----------
// Taugt der Bestand aus Anton für die Kontrolle? Vollständig, mit internem Zugang und nach der letzten Übergabe geholt;
// der Hinweis nennt den richtigen Grund (Fehler 06.11.2026: nur öffentlich hieß fälschlich „älter als die letzte Übergabe“)
function exAntonFrisch(st, spaet) {
  if (!st) return { frisch: false, hinweis: "" };
  const hinweis = st.zugang === "öffentlich" ? "ohne Token, nur öffentliche Bestände"
    : st.nur_platten ? "nur einzelne Datenträger"
    : (st.geholt_am || "") < spaet ? "älter als die letzte Übergabe" : "";
  return { frisch: !hinweis, hinweis };
}

function exKontrolle(s) {
  const uebergeben = s.pakete.filter((p) => EX_FERTIG.includes(p.status));
  const spaet = uebergeben.reduce((m, p) => ((p.uebergeben_am || "") > m ? p.uebergeben_am : m), "");
  const st = s.anton_stand;
  const { frisch, hinweis } = exAntonFrisch(st, spaet);
  const anton = s.anton_lauf?.aktiv;
  const abw = ex.abweichungen;
  return `<div class="leise">Nachdem der Betreiber den Import gemeldet hat: Bestand aus Anton holen (mit API-Token, vollständig), dann vergleicht
      Balduin jede übergebene Datei über MD5, Name und Anzahl mit der Datenbank. Was fehlt, gilt wieder als offen und kommt beim
      nächsten Packen in ein neues Paket.</div>
    <dl class="angaben-liste"><dt>Bestand aus Anton</dt><dd>${st ? esc(exZeit(st.geholt_am)) : "noch nie geholt"}
      ${hinweis ? ` · <span class="warnung-text">${esc(hinweis)}</span>` : ""}</dd></dl>
    <div class="knopfzeile">
      <button type="button" data-ex-anton ${anton ? "disabled" : ""}>${icon("refresh-cw")} ${anton ? "Bestand wird geholt …" : "Bestand aus Anton holen"}</button>
      <button type="button" class="haupt" data-ex-kontrolle ${frisch && !anton ? "" : "disabled"}>${icon("list-checks")} Kontrolle ausführen</button>
      <button type="button" class="knopf-leise" data-ex-abweichungen>${icon("list")} Abweichungen</button></div>
    ${abw ? `<div class="tabelle-rahmen"><table class="vl-tabelle"><thead><tr><th>Paket</th><th>Datei</th><th>Befund</th><th>in Anton</th></tr></thead>
        <tbody>${abw.length ? abw.map((z) => `<tr><td>${esc(z.paket)}</td><td><span class="pille kennung">${esc(z.platte_id)}</span> ${esc(z.relpfad)}</td>
          <td class="warnung-text">${esc({ fehlt: "fehlt", name: "anderer Name", mehrfach: "mehrfach" }[z.anton] || z.anton)}</td>
          <td>${z.anton_link ? `<a href="${esc(z.anton_link)}" target="_blank" rel="noopener">${esc(z.anton_signatur || "öffnen")}</a>` : esc(z.anton_signatur || "")}</td></tr>`).join("")
          : `<tr><td colspan="4" class="leise">Keine Abweichungen.</td></tr>`}</tbody></table></div>` : ""}
    <div class="leise">Das Ergebnis je Paket steht rechts unter „Pakete“.</div>`;
}

// ---------- Abschlussbericht ----------
function exBericht(s) {
  return `<div class="leise">Bericht für das Archiv als eigenständige HTML-Datei in <span class="mono">berichte/</span> des Projekts: je Datenträger
      erfasst, kassiert, zurückgestellt, übernommen (Anzahl und Größe), dazu der Export nach Anton und alle Pakete mit ihrem Stand.</div>
    <div class="knopfzeile"><button type="button" class="haupt" data-ex-bericht>${icon("file-text")} Abschlussbericht speichern</button></div>
    ${s.bericht ? `<div class="leise">Zuletzt gespeichert: ${esc(s.bericht.datei)}</div>
      <div class="knopfzeile"><button type="button" class="knopf-leise" data-ex-bericht-zeigen>${icon("folder-open")} Im ${systemwort("dateimanager")} zeigen</button></div>` : ""}`;
}

// ======================================================================================================
// Spalte 3: Lauf und Pakete
// ======================================================================================================
function exLaeufe(s) {
  const l = s.lauf;
  if (!l) return `<div class="leer-hinweis">Noch kein Export gelaufen.</div>`;
  const zeilen = (l.schritte || []).map((st) => {
    const laeuft = st.status === "läuft";
    return `<li class="schritt-zeile st-${STATUS_KLASSE[st.status] || "wartet"}">
      <span class="st-zeichen">${laeuft ? '<i class="drehen"></i>' : SCHRITT_ZEICHEN[st.status] ?? ""}</span>
      <span><b>${esc(st.titel)}</b>${st.text && st.status !== "wartet" ? `<span class="st-text">${esc(st.text)}</span>` : ""}
        ${laeuft ? `<span class="st-spur"><i style="width:${(100 * (st.anteil || 0)).toFixed(1)}%"></i></span>` : ""}</span>
      <span class="leise">${st.status === "wartet" ? "wartet" : laeuft ? dauer(st.start) : st.status === "fertig" ? dauer(st.start, st.ende) : esc(st.status)}</span></li>`;
  }).join("") || `<li class="leise">Der Lauf startet …</li>`;
  const frueher = s.laeufe.slice(1).map((x) => `<li class="lauf-zeile st-${STATUS_KLASSE[x.status] || "wartet"}">
      <span class="st-zeichen">${SCHRITT_ZEICHEN[x.status] ?? ""}</span>
      <span><b>${esc(x.platte_id || "Ebenen")}</b> <span class="st-text">${esc(x.meldung || "")}</span></span>
      <span class="leise">${esc(x.status)} · ${esc(exZeit(x.ende || x.start))}</span></li>`).join("");
  return `<div class="lauf-einzeln">
      <div class="lauf-titel"><span class="titel-gross">Export ${esc(l.platte_id || "Ebenen")}</span>
        <span class="leise">Lauf ${l.lauf_id} · ${esc(exZeit(l.start))}</span>
        <span class="pille ${l.status === "fertig" ? "gut" : l.aktiv ? "" : "warnung"}">${esc(l.aktiv ? "läuft" : l.status)}</span></div>
      ${l.meldung && !l.aktiv ? `<div class="hinweis ${l.status === "fertig" ? "" : "warnung"}">${esc(l.meldung)}</div>` : ""}
      <ul class="schritt-liste">${zeilen}</ul>
      <div class="knopfzeile">
        ${l.aktiv ? `<button type="button" data-ex-abbrechen="${l.lauf_id}">Abbrechen</button>` : ""}
        ${!l.aktiv && l.status !== "fertig" ? `<button type="button" class="haupt" data-ex-fortsetzen="${l.lauf_id}">Fortsetzen</button>` : ""}
      </div>
      ${l.aktiv ? `<div class="leise tipp">Der Lauf geht weiter, wenn dieses Fenster oder der Browser geschlossen wird.</div>` : ""}
    </div>
    ${frueher ? `<ul class="lauf-liste"><li class="lauf-gruppe">Frühere Läufe</li>${frueher}</ul>` : ""}`;
}

// Alle Pakete als flache Liste wie die Datenträger der Analyse; ein Klick zeigt das Paket oben in den Details
const EX_PAKET_FOLGE = ["Fehler", "gebaut", "geplant", "unvollständig", "übergeben", "importiert"];
function exPaketeUebersicht(s) {
  if (!s.pakete.length) return `<div class="leer-hinweis">Noch nichts geplant.</div>`;
  const zaehl = (st) => s.pakete.filter((p) => p.status === st).length;
  const liste = [...s.pakete].sort((a, b) => EX_PAKET_FOLGE.indexOf(a.status) - EX_PAKET_FOLGE.indexOf(b.status));
  return `<div class="leise">${EX_PAKET_FOLGE.filter(zaehl).map((st) => `${zahl(zaehl(st))} ${EX_STATUS[st][0]}`).join(" · ")}</div>
    <ul class="erf-liste ex-paketliste">${liste.map((p) => `<li class="dt ${ex.offen === p.paket_id ? "gewaehlt" : ""}" data-ex-paket="${p.paket_id}">
      <div class="dt-zeile"><b>${esc(p.name)}</b>${exPille(p.status)}${p.uebergabe?.probe ? `<span class="pille">Probe</span>` : ""}
        ${p.status === "gebaut" ? (p.geprueft_am ? `<span class="pille gut">nachgeprüft</span>` : `<span class="pille">nicht nachgeprüft</span>`) : ""}</div>
      <div class="leise">${esc(p.art === "ebenen" ? "Neue Ebenen" : p.platte_id)} → ${esc(p.signatur || p.box)} · ${p.dateien ? `${zahl(p.dateien)} Dateien · ${bytes(p.bytes)}` : `${zahl(p.eintraege)} Einträge`}</div></li>`).join("")}</ul>`;
}

// Ein Paket im Einzelnen (oben in den Details): Angaben, Aktionen, Einträge
function exPaketHtml(p) {
  const geschrieben = p.status === "geplant" && p.geschrieben ? ` · ${zahl(p.geschrieben)} von ${zahl(p.dateien)} Dateien geschrieben` : "";
  const braucht = p.braucht.length ? `<div class="leise">nach: ${p.braucht.map((b) => `${esc(b.name)} (${esc(EX_STATUS[b.status]?.[0] || b.status)})`).join(", ")}</div>` : "";
  const a = p.anton;
  const anton = p.kontrolle_am && a ? `<div class="leise">Kontrolle ${esc(exZeit(p.kontrolle_am))}: ${zahl((a.da || 0) + (a.name || 0) + (a.mehrfach || 0))} in Anton
      ${a.fehlt ? ` · <span class="warnung-text">${zahl(a.fehlt)} fehlen</span>` : ""}${a.name ? ` · ${zahl(a.name)} mit anderem Namen` : ""}
      ${a.mehrfach ? ` · ${zahl(a.mehrfach)} mehrfach` : ""}</div>` : "";
  const knoepfe = [
    p.datei && !p.datei_geloescht_am ? `<button type="button" class="knopf-leise" data-ex-zeigen="${p.paket_id}">${icon("folder-open")} Im ${systemwort("dateimanager")}</button>` : "",
    EX_FERTIG.includes(p.status) && !(a && (a.da || a.name || a.mehrfach)) ? `<button type="button" class="knopf-leise" data-ex-zurueck="${p.paket_id}">${icon("undo-2")} Übergabe zurücknehmen</button>` : "",
    p.datei && !p.datei_geloescht_am && ["importiert", "gebaut"].includes(p.status) ? `<button type="button" class="knopf-leise" data-ex-loeschen="${p.paket_id}" data-status="${esc(p.status)}">${icon("trash")} Paketdatei löschen</button>` : "",
  ].join("");
  return `<div class="ex-paket">
    <div class="dt-zeile">${exPille(p.status)}${p.uebergabe?.probe ? `<span class="pille">Probe</span>` : ""}${p.status === "gebaut" ? (p.geprueft_am ? `<span class="pille gut">nachgeprüft</span>` : `<span class="pille">nicht nachgeprüft</span>`) : ""}
      <button type="button" class="knopf-leise ex-zurueck-knopf" data-ex-paket-zu>${icon("x")} Paket schließen</button></div>
    <div class="leise">unter ${esc(p.signatur ? p.signatur + " · " : "")}${esc(p.box)} · ${zahl(p.eintraege)} Einträge${p.dateien ? ` · ${zahl(p.dateien)} Dateien · ${bytes(p.bytes)}` : ""}${geschrieben}</div>
    ${braucht}
    ${p.fehler ? `<div class="st-text fehler">${esc(p.fehler)}</div>` : ""}
    ${p.uebergeben_am ? `<div class="leise">übergeben ${esc(exZeit(p.uebergeben_am))}${p.uebergabe?.notiz ? ` · ${esc(p.uebergabe.notiz)}` : ""}</div>` : ""}
    ${anton}
    ${knoepfe ? `<div class="knopfzeile">${knoepfe}</div>` : ""}
    <div class="ueberschrift">Einträge</div>
    <div class="ex-eintraege">${exEintraegeHtml(p.paket_id)}</div>
  </div>`;
}

function exEintraegeHtml(paketId) {
  const e = ex.eintraege[paketId];
  if (!e) return `<div class="leise">wird geladen …</div>`;
  const stufe = { item: "Einzelstück", file: "Dossier", class: "Gliederungsebene" };
  const anton = { da: "in Anton", fehlt: "fehlt", name: "anderer Name", mehrfach: "mehrfach" };
  return `<div class="tabelle-rahmen"><table class="vl-tabelle">
      <thead><tr><th>#</th><th>Stufe</th><th>Titel</th><th>Datei</th><th>Anton</th><th></th></tr></thead>
      <tbody>${e.eintraege.map((z) => `<tr><td>${z.nr + 1}</td><td>${esc(stufe[z.stufe] || z.stufe || z.typ)}</td>
        <td>${esc(z.titel)}</td><td class="leise">${esc(z.pfad)}${z.groesse ? ` · ${bytes(z.groesse)}` : ""}${z.geschrieben ? " ✓" : ""}${z.medien ? ` <b>+ ${zahl(z.medien - 1)} weitere Medien</b>` : ""}</td>
        <td class="${z.anton && z.anton !== "da" ? "warnung-text" : "leise"}">${esc(anton[z.anton] || "")}${z.signatur ? ` · ${esc(z.signatur)}` : ""}</td>
        <td><details><summary class="leise">JSON</summary><pre class="ex-json">${esc(JSON.stringify(z.eintrag, null, 1))}</pre></details></td></tr>`).join("")}
      </tbody></table></div>
    ${e.gesamt > e.eintraege.length ? `<div class="leise">Gezeigt ${zahl(e.eintraege.length)} von ${zahl(e.gesamt)}.</div>` : ""}`;
}

// ---------- Rückfrage ----------
function exFrage(titel, html, ok) {
  return new Promise((fertig) => {
    $("#ex-frage-titel").textContent = titel;
    $("#ex-frage-inhalt").innerHTML = html;
    $("#ex-frage-ok").textContent = ok;
    const dlg = $("#ex-frage-dialog");
    const zu = (wert) => { dlg.close(); $("#ex-frage-ok").onclick = $("#ex-frage-abbrechen").onclick = dlg.oncancel = null; fertig(wert); };
    $("#ex-frage-ok").onclick = (ev) => { ev.preventDefault(); zu(true); };
    $("#ex-frage-abbrechen").onclick = () => zu(false);
    dlg.oncancel = () => zu(false);
    dlg.showModal();
  });
}

// ---------- Aktionen ----------
async function exAusfuehren(arbeit) {
  ex.fehler = "";
  try {
    await arbeit();
  } catch (err) {
    ex.fehler = err.message;
  }
  await exportZeigen();
  if (ex.fehler && $("#ex-fehler")) $("#ex-fehler").textContent = ex.fehler;
}

async function exPlanen() {
  let r = await senden("/api/export_planen", {});
  if (r.rueckfrage) {
    const ja = await exFrage("Geschriebene Pakete verwerfen?", `<p class="dialog-text">${esc(r.rueckfrage)}</p>
      <ul class="dialog-text">${r.gebaut.slice(0, 10).map((n) => `<li>${esc(n)}</li>`).join("")}</ul>`, "Verwerfen und neu planen");
    if (!ja) return;
    r = await senden("/api/export_planen", { verwerfen_ok: true });
  }
  ex.veraltetOk = false;
  ex.fehler = r.schemafehler ? `${r.schemafehler} Pakete passen nicht zum Schema des Anton-Importformats (Fehler beim Paket).` : "";
}

// Datenträger für die Ablage suchen (beim ersten Packen von selbst)
async function exAblagenLaden() {
  ex.ablagen = (await holen("/api/export_ablagen")).ablagen;
}

function exAenderung(e) {
  const g = e.target.closest("[data-ex-groesse]");
  if (g) {
    const block = g.closest(".ex-einstellungen-block");
    const wert = (art) => Number(block.querySelector(`[data-ex-groesse="${art}"]`).value);
    return exAusfuehren(() => senden("/api/export_einstellungen", { dateien_je_paket: wert("dateien"), gb_je_paket: wert("gb") }));
  }
  const w = e.target.closest("[data-ex-wahl]");
  if (w) {
    const id = Number(w.dataset.exWahl);
    if (w.checked) ex.wahl.add(id); else ex.wahl.delete(id);
    exZeichnen();
  }
}

async function exKlick(e) {
  const z = (sel) => e.target.closest(sel);
  if (z("#ex-neu")) return exportZeigen();
  const sicht = z("[data-ex-sicht]");
  if (sicht) { ex.sicht = sicht.dataset.exSicht; return exZeichnen(); }
  const ansicht = z("[data-ex-ansicht]");
  if (ansicht) { $("#ex-einstellungen").hidden = true; return ansichtZeigen(ansicht.dataset.exAnsicht); }
  const auf = z("[data-ex-auf]");
  if (auf && !z(".ex-unterliste, button, a, details")) {
    const k = auf.dataset.exAuf;
    if (ex.auf.has(k)) ex.auf.delete(k); else ex.auf.add(k);
    return exZeichnen();
  }
  const schritt = z("[data-ex-schritt]");
  if (schritt) {
    // Aktion wählen: ihre Details stehen rechts (Feedback 05.11.2026); ein gewähltes Paket tritt zurück
    ex.schritt = schritt.dataset.exSchritt;
    ex.offen = null;
    ex.abweichungen = null;
    exZeichnen();
    if (ex.schritt === "packen" && !ex.daten.ablage.ort && !ex.ablagen) exAusfuehren(exAblagenLaden);
    if (ex.schritt === "packen" && ex.gefuehrt) exportZeigen();    // Warten auf die nächste Platte wieder aufnehmen
    return;
  }
  if (z("#ex-planen")) return exAusfuehren(exPlanen);
  if (z("[data-ex-veraltet-ok]")) { ex.veraltetOk = true; return exportZeigen(); }
  if (z("[data-ex-beginnen]")) { ex.gefuehrt = true; ex.versucht.clear(); return exportZeigen(); }
  if (z("[data-ex-anhalten]")) { ex.gefuehrt = false; clearTimeout(ex.takt); return exZeichnen(); }
  if (z("[data-ex-ablagen]")) return exAusfuehren(exAblagenLaden);
  if (z("[data-ex-ablage-zu]")) { ex.ablagen = null; return exZeichnen(); }
  const ablageOk = z("[data-ex-ablage-ok]");
  if (ablageOk) {
    const wahl = ablageOk.closest(".ex-einstellungen-block").querySelector(`input[name=ex-ablage-${ablageOk.dataset.exAblageOk}]:checked`);
    if (!wahl) return;
    return exAusfuehren(async () => { await senden("/api/export_ablage", { mountpunkt: wahl.value }); ex.ablagen = null; });
  }
  const quitt = z("[data-ex-quittieren]");
  if (quitt) {
    if (!(await exFrage("Lesefehler quittieren?", `<p class="dialog-text">Die nicht lesbaren Pfade von ${esc(quitt.dataset.exQuittieren)}
        fehlen im Export. Quittieren heißt: gesehen und so gewollt. Kommen später neue Lesefehler dazu, ist erneut zu quittieren.</p>`, "Quittieren"))) return;
    return exAusfuehren(() => senden("/api/export_quittieren", { platte_id: quitt.dataset.exQuittieren }));
  }
  if (z("[data-ex-anton]")) return exAusfuehren(() => senden("/api/anton_holen", {}));
  if (z("[data-ex-importformat]")) return exAusfuehren(() => senden("/api/export_importformat", {}));
  const einh = z("[data-ex-einhaengen]");
  if (einh) {
    if (!(await exFrage("Schreibgeschützt einhängen?", `<p class="dialog-text">${esc(einh.dataset.exEinhaengen)} wird ausgehängt und
        schreibgeschützt wieder eingehängt. Danach kann das Betriebssystem keine eigenen Dateien mehr darauf schreiben.</p>`, "Einhängen"))) return;
    return exAusfuehren(() => senden("/api/einhaengen", { mountpunkt: einh.dataset.exEinhaengen }));
  }
  const ohneSchutz = z("[data-ex-ohne-schutz]");
  if (ohneSchutz) {
    if (!(await ohneSchreibschutzFragen(ohneSchutz.dataset.exOhneSchutz))) return;
    return exAusfuehren(() => senden("/api/ohne_schreibschutz", { platte_id: ohneSchutz.dataset.exOhneSchutz }));
  }
  const start = z("[data-ex-starten]");
  if (start) {
    const passwort = await exPasswort(start.dataset.exStarten);
    if (passwort === null) return;
    return exAusfuehren(() => senden("/api/export_starten", { platte_id: start.dataset.exStarten, passwort }));
  }
  const abbrechen = z("[data-ex-abbrechen]");
  if (abbrechen) {
    ex.gefuehrt = false;                               // wer abbricht, will nicht, dass gleich die nächste Platte startet
    return exAusfuehren(() => senden("/api/abbrechen", { lauf_id: Number(abbrechen.dataset.exAbbrechen) }));
  }
  const fortsetzen = z("[data-ex-fortsetzen]");
  if (fortsetzen) {
    const l = (ex.daten?.laeufe || []).find((x) => x.lauf_id === Number(fortsetzen.dataset.exFortsetzen));
    const passwort = await exPasswort(l?.platte_id);
    if (passwort === null) return;
    return exAusfuehren(() => senden("/api/fortsetzen", { lauf_id: Number(fortsetzen.dataset.exFortsetzen), passwort }));
  }
  const zeigen = z("[data-ex-zeigen]");
  if (zeigen) return exAusfuehren(() => senden("/api/export_zeigen", { paket_id: Number(zeigen.dataset.exZeigen) || null }));
  if (z("[data-ex-alle]")) {
    ex.daten.pakete.filter((p) => p.status === "gebaut" && p.geprueft_am).forEach((p) => ex.wahl.add(p.paket_id));
    return exZeichnen();
  }
  if (z("[data-ex-uebergeben]")) {
    const ids = [...ex.wahl];
    if (!(await exFrage("Als übergeben vermerken?", `<p class="dialog-text">Danach gelten ${exPakete(ids.length)} als an den Betreiber der Anton-Instanz
        übergeben. Die Dateien bleiben auf der Ablage, bis die Kontrolle in Anton sie gefunden hat.</p>`, "Vermerken"))) return;
    return exAusfuehren(async () => { await senden("/api/export_uebergeben", { pakete: ids, notiz: ex.notiz }); ex.wahl.clear(); ex.notiz = ""; });
  }
  const zurueck = z("[data-ex-zurueck]");
  if (zurueck) {
    if (!(await exFrage("Übergabe zurücknehmen?", `<p class="dialog-text">Das Paket gilt wieder als geschrieben, nicht übergeben. Nur wählen,
        wenn es falsch vermerkt wurde oder bei Anton nicht angekommen ist.</p>`, "Zurücknehmen"))) return;
    return exAusfuehren(() => senden("/api/export_zuruecknehmen", { paket_id: Number(zurueck.dataset.exZurueck) }));
  }
  const loeschen = z("[data-ex-loeschen]");
  if (loeschen) {
    const nochNicht = loeschen.dataset.status === "gebaut";
    const text = nochNicht ? "Das Paket ist noch nicht übergeben: Es muss danach mit angeschlossenem Datenträger neu geschrieben werden."
      : "Die Kontrolle hat das Paket in Anton gefunden; die Datei auf der Ablage wird nicht mehr gebraucht.";
    if (!(await exFrage("Paketdatei löschen?", `<p class="dialog-text">${text} Die Originale bleiben auf dem Datenträger.</p>`, "Löschen"))) return;
    return exAusfuehren(() => senden("/api/export_datei_loeschen", { paket_id: Number(loeschen.dataset.exLoeschen) }));
  }
  if (z("[data-ex-kontrolle]")) {
    return exAusfuehren(async () => {
      const r = await senden("/api/export_kontrolle", {});
      ex.abweichungen = (r.fehlt || r.name || r.mehrfach) ? (await holen("/api/export_abweichungen")).abweichungen : null;
    });
  }
  if (z("[data-ex-abweichungen]")) return exAusfuehren(async () => { ex.abweichungen = (await holen("/api/export_abweichungen")).abweichungen; });
  if (z("[data-ex-bericht]")) return exAusfuehren(() => senden("/api/export_bericht", {}));
  if (z("[data-ex-bericht-zeigen]")) return exAusfuehren(() => senden("/api/export_zeigen", { bericht: true }));
  if (z("[data-ex-paket-zu]")) { ex.offen = null; return exZeichnen(); }
  const paket = z("[data-ex-paket]");
  if (paket) {
    const id = Number(paket.dataset.exPaket);
    ex.offen = ex.offen === id ? null : id;
    exZeichnen();
    if (ex.offen != null && !ex.eintraege[id]) {
      try { ex.eintraege[id] = await holen("/api/export_eintraege", { paket: id }); } catch (err) { ex.eintraege[id] = { eintraege: [], gesamt: 0 }; ex.fehler = err.message; }
      exZeichnen();
    }
  }
}

// Zahnrad am Knopf „Bestand und Export“: Ablage und Paketgröße
async function exZahnrad(ev) {
  ev.stopPropagation();
  const panel = $("#ex-einstellungen");
  panel.hidden = !panel.hidden;
  $("#ex-einstellungen-knopf").setAttribute("aria-expanded", String(!panel.hidden));
  if (panel.hidden) return;
  $("#ex-einstellungen-inhalt").innerHTML = `<div class="leise">…</div>`;
  try {
    if (!ex.daten) await exportZeigen();
    if (!ex.daten.ablage.ort && !ex.ablagen) await exAblagenLaden();
    $("#ex-einstellungen-inhalt").innerHTML = exEinstellungenHtml(ex.daten, "zahnrad");
  } catch (err) {
    $("#ex-einstellungen-inhalt").innerHTML = `<div class="fehler">${esc(err.message)}</div>`;
  }
}

if (typeof document !== "undefined") {
  for (const ort of ["#export", "#ex-einstellungen"]) {
    $(ort).addEventListener("click", exKlick);
    $(ort).addEventListener("change", exAenderung);
  }
  $("#export").addEventListener("input", (e) => { if (e.target.id === "ex-notiz") ex.notiz = e.target.value; });
  $("#ex-einstellungen-knopf").addEventListener("click", exZahnrad);
  document.addEventListener("click", (ev) => {
    // neu gezeichnete Teile hängen nicht mehr im Dokument: dann war der Klick im Zahnrad
    if (ev.target.isConnected && !ev.target.closest("#ex-einstellungen, #ex-einstellungen-knopf")) {
      $("#ex-einstellungen").hidden = true;
      $("#ex-einstellungen-knopf").setAttribute("aria-expanded", "false");
    }
  });
}

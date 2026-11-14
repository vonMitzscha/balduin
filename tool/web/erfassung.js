// Registrierung/Analyse (Code: Erfassung): Datenträger wählen, Angaben machen, den Ablauf aus Notebook 1 im Hintergrund starten und verfolgen.
// Nutzt die Hilfen aus app.js ($, esc, zahl, bytes, holen, senden, standLaden).
"use strict";

const erf = {
  ansicht: "erfassung",
  dt: null,                     // Antwort von /api/datentraeger
  stand: null,                  // Antwort von /api/erfassung (Platten, letzter Lauf)
  gewaehlt: null,               // Mountpunkt des gewählten Datenträgers
  platte: null,                 // Kennung der gewählten registrierten Platte (statt eines Datenträgers)
  auswahl: new Set(),           // in der Plattenansicht gewählte Schritte (Kürzel C, D1 …)
  foto: null,                   // {name, daten} als data-URL
  takt: null,
  warLauf: null,                // Nummer des laufenden Laufs bei der letzten Abfrage
  laufWahl: null,               // rechts in „Läufe“ angeklickter Lauf; null = der laufende, sonst der letzte der Platte
  frage: null,                  // offene Rückfrage in „Läufe“: {art: "abbrechen" | "entfernen", lauf_id}
  vorgemerkt: {},               // lauf_id → "abbrechen" | "entfernen": sofort so zeigen, bis der Server es bestätigt
  abfrageNr: 0,                 // Nummer der letzten Abfrage; ältere Antworten (vor einem Klick gestartet) gelten nicht
  zeigerUnten: false,           // Maustaste in „Läufe“ gedrückt: nicht neu zeichnen, sonst ginge der Klick verloren
  quelle: null,                 // gewählter Ordner als Quelle (noch nicht registriert), wie ein Eintrag der Datenträger
  umfang: null,                 // Wahl des Umfangs (Teile einer Platte): {wurzel, modus, gewaehlt, fest, offen, kinder}
  umfangOffen: false,           // im Panel einer registrierten Platte: „Umfang erweitern“ aufgeklappt
};

// Läufe, die gerade rechnen, unabhängig davon, welcher rechts im Einzelnen gezeigt wird. Zwei Spuren (Entscheidung
// 05.11.2026): „Bestand aus Anton holen“ läuft neben einem anderen Lauf; Analyse, Vorlauf und Export hintereinander.
const laufende = () => (erf.stand?.laeufe || []).filter((l) => l.aktiv);
const laufend = () => laufende().find((l) => l.art !== "anton") || laufende()[0] || null;
const laeuftArt = (art) => laufende().some((l) => l.art === art);
const hauptspurBelegt = () => laufende().find((l) => l.art !== "anton") || null;

const STATUS_KLASSE = { "fertig": "fertig", "läuft": "laeuft", "wartet": "wartet", "übersprungen": "uebersprungen",
                        "abgebrochen": "abgebrochen", "Fehler": "fehler" };
const SCHRITT_ZEICHEN = { "fertig": icon("check"), "läuft": "", "wartet": "", "übersprungen": icon("minus"), "abgebrochen": icon("square"), "Fehler": icon("x") };
const zeit = (iso) => (iso ? iso.slice(11, 16) : "");
function dauer(start, ende) {
  if (!start) return "";
  const s = Math.max(0, ((ende ? new Date(ende) : new Date()) - new Date(start)) / 1000);
  return s < 60 ? `${Math.round(s)} s` : s < 3600 ? `${Math.round(s / 60)} Min.` : `${Math.floor(s / 3600)} Std. ${Math.round((s % 3600) / 60)} Min.`;
}

// ---------- Kopfleiste: Ring je Modul, Balken für das aktuelle ----------
function ring(anteil, fertig) {
  if (fertig) return `<svg class="ring fertig" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10.5"/>`
    + `<path d="M7 12.5l3.2 3.2L17 9"/></svg>`;
  const umfang = 2 * Math.PI * 9;
  return `<svg class="ring" viewBox="0 0 24 24" aria-hidden="true"><circle class="spur" cx="12" cy="12" r="9"/>`
    + `<circle class="wert" cx="12" cy="12" r="9" stroke-dasharray="${(umfang * Math.min(anteil, 1)).toFixed(1)} ${umfang.toFixed(1)}"/></svg>`;
}

function modulKopf() {
  const b = zustand.bewertung, a = erf.stand?.modul;
  const module = [
    { ansicht: "erfassung", nummer: 1, kurz: "Registrierung/Analyse", wort: "Analysiert", anteil: a?.anteil ?? 0, fertig: !!a?.fertig,
      text: a ? esc(a.text) : "…" },
    { ansicht: "bewertung", nummer: 2, kurz: "Bewertung", wort: "Bewertet", anteil: b && b.dateien ? b.bewertet / b.dateien : 0,
      fertig: !!b && b.dateien > 0 && b.bewertet === b.dateien,
      text: b ? `${zahl(b.bewertet)} von ${zahl(b.dateien)} Dateien` : "…" },
    // Stand aus tool/web/erschliessung.js (esStand), sobald Vorlauf oder Erschließung einmal geladen waren
    { ansicht: "erschliessung", nummer: 3, kurz: "Erschließung", wort: "Erschlossen",
      anteil: typeof esStand !== "undefined" && esStand?.uebernommen ? esStand.erschlossen / esStand.uebernommen : 0,
      fertig: typeof esStand !== "undefined" && !!esStand?.uebernommen && esStand.erschlossen === esStand.uebernommen,
      text: typeof esStand !== "undefined" && esStand ? `${zahl(esStand.erschlossen)} von ${zahl(esStand.uebernommen)} übernommenen Dateien` : "…" },
    // Stand aus tool/web/export.js (exStand), sobald Modul 4 einmal geladen war
    { ansicht: "export", nummer: 4, kurz: "Bestand und Export", wort: "In Anton",
      anteil: typeof exStand !== "undefined" && exStand ? exStand.anteil : 0,
      fertig: typeof exStand !== "undefined" && !!exStand?.fertig,
      text: typeof exStand !== "undefined" && exStand ? `${zahl(exStand.in_anton)} von ${zahl(exStand.gesamt)} Dateien` : "…" },
  ];
  $("#module").innerHTML = module.map((m) => {
    const p = Math.round(100 * m.anteil);
    if (m.ansicht === erf.ansicht) {
      return `<div class="modul-balken"><div class="leise">${m.wort}: <b>${m.fertig ? "100" : p} %</b> · ${m.text}</div>
        <div class="fortschritt-spur"><i style="width:${m.fertig ? 100 : p}%"></i></div></div>`;
    }
    const titel = `${m.kurz}: ${m.ansicht ? (m.fertig ? "erledigt" : p + " %") + " · " : ""}${m.text.replace(/<[^>]+>/g, "")}`;
    const innen = `${ring(m.anteil, m.fertig)}${m.fertig ? "" : `<span>${m.nummer}</span>`}`;
    return m.ansicht
      ? `<button type="button" class="modul-ring" data-ansicht="${m.ansicht}" title="${esc(titel)}" aria-label="${esc(titel)}">${innen}</button>`
      : `<span class="modul-ring aus" title="${esc(titel)}">${innen}</span>`;
  }).join("");
}
$("#module").addEventListener("click", (e) => {
  const knopf = e.target.closest("[data-ansicht]");
  if (knopf) ansichtZeigen(knopf.dataset.ansicht);
});

// ---------- Ansicht wechseln ----------
function ansichtZeigen(ansicht) {
  erf.ansicht = ansicht;
  $("#start").hidden = true;
  $("#bewertung").hidden = ansicht !== "bewertung";
  $("#erfassung").hidden = ansicht !== "erfassung";
  $("#vorlauf").hidden = ansicht !== "vorlauf";
  $("#erschliessung").hidden = ansicht !== "erschliessung";
  $("#export").hidden = ansicht !== "export";
  document.querySelectorAll(".schritte [data-ansicht]").forEach((b) => b.classList.toggle("aktiv", b.dataset.ansicht === ansicht));
  // je Projekt im Server merken (nicht im Browser: dessen Speicher gilt nur je Adresse und Port), Entscheidung 05.11.2026
  if (prj.daten?.offen && prj.daten.offen.ansicht !== ansicht) {
    prj.daten.offen.ansicht = ansicht;
    senden("/api/ansicht_merken", { ansicht }).catch(() => { /* nur Bequemlichkeit: Fehler nicht melden */ });
  }
  modulKopf();
  if (ansicht === "erfassung") {
    standErfassung();
    if (!erf.dt) datentraegerLaden();
  }
  if (ansicht === "vorlauf" && typeof vorlaufZeigen === "function") vorlaufZeigen();
  if (ansicht === "erschliessung" && typeof erschliessungZeigen === "function") erschliessungZeigen();
  if (ansicht === "export" && typeof exportZeigen === "function") exportZeigen();
  taktStellen();
}
document.querySelectorAll(".schritte [data-ansicht]").forEach((b) => (b.onclick = () => ansichtZeigen(b.dataset.ansicht)));

// Fortschritt abfragen, solange die Erfassung offen ist oder ein Lauf läuft
function taktStellen() {
  const noetig = erf.ansicht === "erfassung" || !!laufend() || !$("#dashboard").hidden;
  if (noetig && !erf.takt) erf.takt = setInterval(standErfassung, 1500);
  if (!noetig && erf.takt) { clearInterval(erf.takt); erf.takt = null; }
}

// ---------- Daten holen ----------
async function datentraegerLaden() {
  $("#dt-liste").innerHTML = `<li class="leise">Datenträger werden gelesen …</li>`;
  try {
    erf.dt = await holen("/api/datentraeger");
  } catch (e) {
    $("#dt-liste").innerHTML = `<li class="fehler">${esc(e.message)}</li>`;
    return;
  }
  datentraegerZeichnen();
  angabenZeichnen();
}

// Kennung der gewählten Platte (registrierte Platte oder bekannter Datenträger); ihr letzter Lauf steht rechts
const gewaehltePlatte = () => erf.platte || gewaehlterDt()?.kennungen?.[0] || "";

async function standErfassung() {
  const platte = gewaehltePlatte(), wahl = erf.laufWahl, nr = ++erf.abfrageNr;
  const werte = {};
  if (platte) werte.platte = platte;
  if (wahl) werte.lauf = wahl;
  let stand;
  try {
    stand = await holen("/api/erfassung", werte);    // holen hängt die Werte selbst an
  } catch (e) {
    $("#lauf").innerHTML = `<div class="fehler">${esc(e.message)}</div>`;
    return;
  }
  if (nr !== erf.abfrageNr) return;                    // inzwischen neuer gefragt (Klick, Auswahl): die neuere Antwort gilt
  erf.stand = stand;
  // Vormerkungen lösen sich, sobald der Server sie zeigt: entfernt = nicht mehr eingereiht, abgebrochen = Marke gesetzt oder beendet
  for (const [id, art] of Object.entries(erf.vorgemerkt)) {
    const l = stand.laeufe.find((x) => x.lauf_id === Number(id));
    if (art === "entfernen" ? !stand.warteschlange.some((w) => w.lauf_id === Number(id)) : !l?.aktiv || l.abbrechen)
      delete erf.vorgemerkt[id];
  }
  const laufNr = laufende().map((l) => l.lauf_id).join(",") || null;     // Wechsel in einer der Spuren: neu einlesen
  $("#lauf-marke").hidden = !laufende().some((l) => l.art !== "vorlauf");
  if ($("#vl-marke")) $("#vl-marke").hidden = !laeuftArt("vorlauf");
  if (erf.warLauf && erf.warLauf !== laufNr) {          // Lauf zu Ende (oder der nächste eingereihte begonnen): neu einlesen
    standLaden().catch(() => {});
    datentraegerLaden();
  }
  erf.warLauf = laufNr;
  modulKopf();
  if (typeof dashboardLauf === "function") dashboardLauf();
  if (erf.ansicht === "erfassung") {
    plattenZeichnen();
    antonZeichnen();
    laufZeichnen();
    erfassenKnopf();
  }
  taktStellen();
}

// ---------- Datenträger ----------
// Angeschlossene Datenträger und ein gewählter Ordner als Quelle (Entscheidung 05.11.2026)
// Mac-Platten, die das System nicht einbindet (Windows, Linux; Entscheidungen 09. und 13.11.2026): erst nach „lesen“ eine Quelle
const macGeraete = () => (erf.dt?.mac_geraete || []).filter((g) => g.geraet !== erf.quelle?.mountpunkt)
  .map((g) => ({ mountpunkt: g.geraet, name: g.modell || "Datenträger", macgeraet: true, groesse: g.groesse,
                 anschluss: g.anschluss, kennungen: [] }));
const dtListe = () => [...(erf.dt?.angeschlossen || []), ...macGeraete(), ...(erf.quelle ? [erf.quelle] : [])];

function datentraegerZeichnen() {
  // Windows ohne lange Pfade (Entscheidung 13.11.2026): Hinweis über der Liste
  $("#dt-hinweis").innerHTML = erf.dt?.lange_pfade_aus
    ? `<div class="hinweis warnung">Auf diesem Rechner sind lange Pfade ausgeschaltet: Dateien, deren Pfad länger als
      260 Zeichen ist, lassen sich nicht lesen. ${esc(systemwort("lange_pfade"))}</div>` : "";
  const liste = dtListe();
  if (!liste.length) {
    $("#dt-liste").innerHTML = `<li class="leise">Kein Datenträger angeschlossen.</li>`;
    return;
  }
  $("#dt-liste").innerHTML = liste.map((d) => {
    if (d.fehler) return `<li class="dt"><b>${esc(d.name)}</b> <span class="fehler">${esc(d.fehler)}</span></li>`;
    if (d.macgeraet) return `<li class="dt gesperrt" data-mountpunkt="${esc(d.mountpunkt)}">
      <div class="dt-zeile">${traegerIcon(d.anschluss === "USB" ? "usb" : "festplatte", d.anschluss)} <b>${esc(d.name)}</b>
        <span class="pille">nicht eingebunden</span></div>
      <div class="leise">${bytes(d.groesse)} · vermutlich ein Mac-Datenträger (HFS+ oder APFS). ${esc(systemwort("formatierwarnung"))}</div>
      <button type="button" class="knopf-leise" data-macgeraet="${esc(d.mountpunkt)}"
        title="Liest den Datenträger nur, ohne ihn einzubinden; ${esc(systemwort("adminfrage"))}">Mac-Datenträger lesen …</button></li>`;
    if (d.ordner) return `<li class="dt${d.mountpunkt === erf.gewaehlt ? " gewaehlt" : ""}" data-mountpunkt="${esc(d.mountpunkt)}">
      <div class="dt-zeile">${d.abbild ? traegerIcon("image") : icon("folder")} <b>${esc(d.name)}</b><span class="pille">${d.abbild ? "Abbild" : "Ordner"}</span><span class="pille">neu</span></div>
      <div class="leise">${esc(d.mountpunkt)} · wird nur gelesen</div></li>`;
    const marken = [
      d.arbeitsplatte ? `<span class="pille">für Vorschaubilder</span>`
        : d.schreibgeschuetzt ? `<span class="pille gut">schreibgeschützt</span>` : `<span class="pille warnung">beschreibbar</span>`,
      d.arbeitsplatte ? "" : d.kennungen.length ? `<span class="pille kennung">${esc(d.kennungen.join(", "))}</span>`
        : `<span class="pille">neu</span>`,
      (d.andere_projekte || []).length ? `<span class="pille warnung" title="${esc(anderswoText(d))}">schon in ${esc(d.andere_projekte[0].projekt)}</span>` : "",
    ].join("");
    // unter Windows lässt sich nicht schreibgeschützt einhängen (Entscheidung 13.11.2026): Rückfrage beim Start
    const einhaengen = !d.arbeitsplatte && !d.schreibgeschuetzt && !systemwort("kein_schreibschutz")
      ? `<button type="button" class="knopf-leise" data-einhaengen="${esc(d.mountpunkt)}">Schreibgeschützt einhängen</button>` : "";
    const gewaehlt = d.mountpunkt === erf.gewaehlt || (erf.platte && d.kennungen.includes(erf.platte));
    return `<li class="dt${d.arbeitsplatte ? " gesperrt" : ""}${gewaehlt ? " gewaehlt" : ""}"
                data-mountpunkt="${esc(d.mountpunkt)}">
      <div class="dt-zeile">${traegerIcon(d.traeger, d.anschluss)} <b>${esc(d.name)}</b>${marken}</div>
      <div class="leise">${esc(d.mountpunkt)} · ${bytes(d.groesse)} · ${esc(d.dateisystem || "Dateisystem unbekannt")}
        · ${d.uuid ? "mit UUID" : "ohne UUID (Ersatzprüfung)"}</div>${einhaengen}</li>`;
  }).join("");
}

$("#dt-liste").addEventListener("click", async (e) => {
  const mac = e.target.closest("[data-macgeraet]");
  if (mac) {
    mac.disabled = true;
    mac.textContent = `wird gelesen (${systemwort("adminfrage")}) …`;
    try {
      const a = await senden("/api/macgeraet_pruefen", { geraet: mac.dataset.macgeraet });
      if (a.erkannt) {                  // schon registriert, hing woanders: Balduin hat das Gerät nachgetragen (13.11.2026)
        meldung(`Das ist ${a.erkannt}. Balduin hat den registrierten Datenträger an seiner Volume-UUID wiedererkannt.`,
          "Wiedererkannt");
        erf.platte = a.erkannt;
        await datentraegerLaden();
        await standErfassung();
        plattenZeichnen();
        angabenZeichnen();
        return;
      }
      erf.quelle = { mountpunkt: a.geraet, name: a.modell || "Mac-Datenträger", ordner: true, abbild: true, macplatte: true,
                     volumes: a.volumes, schreibgeschuetzt: true, kennungen: [], anschluss: a.anschluss,
                     dateisystem: a.volumes.map((v) => v.dateisystem).join(", ") };
      erf.gewaehlt = a.geraet;
      erf.platte = null;
      erf.umfang = null;
      datentraegerZeichnen();
      plattenZeichnen();
      angabenZeichnen();
    } catch (err) { meldung(err.message, "Fehler"); datentraegerZeichnen(); }
    return;
  }
  const knopf = e.target.closest("[data-einhaengen]");
  if (knopf) {
    if (!(await rueckfrage(`${knopf.dataset.einhaengen} aushängen und schreibgeschützt wieder einhängen?`,
      "Danach kann das Betriebssystem keine eigenen Dateien (etwa Indexdateien) mehr auf den Datenträger schreiben.",
      "Schreibgeschützt einhängen"))) return;
    knopf.disabled = true;
    knopf.textContent = "wird eingehängt …";
    try {
      const r = await senden("/api/einhaengen", { mountpunkt: knopf.dataset.einhaengen });
      if (erf.gewaehlt === knopf.dataset.einhaengen) erf.gewaehlt = r.mountpunkt;
    } catch (err) { meldung(err.message, "Fehler"); }
    return datentraegerLaden();
  }
  const li = e.target.closest("li.dt[data-mountpunkt]");
  if (!li || li.classList.contains("gesperrt")) return;
  const d = dtListe().find((x) => x.mountpunkt === li.dataset.mountpunkt);
  const bekannt = d?.kennungen?.length && erf.stand?.platten.some((p) => p.platte_id === d.kennungen[0]);
  if (!bekannt && d && !d.ordner) umfangZuruecksetzen(d.mountpunkt);
  erf.gewaehlt = bekannt ? null : li.dataset.mountpunkt;     // bekannte Platte: Angaben und Fortsetzen statt Formular
  erf.auswahl.clear();
  erf.platte = bekannt ? d.kennungen[0] : null;
  erf.laufWahl = null;
  erf.foto = null;
  datentraegerZeichnen();
  plattenZeichnen();
  angabenZeichnen();
  standErfassung();
});
$("#dt-neu").onclick = () => datentraegerLaden();

// Ordner als Quelle (Fall 2, Entscheidung 05.11.2026): im Finder wählen, Balduin prüft, ob er taugt
$("#ordner-einlesen").onclick = async () => {
  try {
    const r = await senden("/api/ordner_waehlen", { zweck: "quelle" });
    if (r.abgebrochen) return;
    const q = await senden("/api/quellordner_pruefen", { pfad: r.pfad });
    erf.quelle = { mountpunkt: q.pfad, name: q.name, ordner: true, schreibgeschuetzt: true, kennungen: [],
                   dateisystem: "Ordner" };
    erf.gewaehlt = q.pfad;
    erf.platte = null;
    erf.laufWahl = null;
    erf.foto = null;
    erf.umfang = null;
    datentraegerZeichnen();
    plattenZeichnen();
    angabenZeichnen();
  } catch (e) { meldung(e.message, "Fehler"); }
};

// Abbild eines Mac-Datenträgers (Entscheidung 09.11.2026): Datei wählen, Balduin prüft, ob ein HFS+ oder APFS darin liegt
$("#abbild-einlesen").onclick = async () => {
  try {
    const r = await senden("/api/abbild_waehlen", {});
    if (r.abgebrochen) return;
    const q = await senden("/api/abbild_pruefen", { pfad: r.pfad });
    erf.quelle = { mountpunkt: q.pfad, name: q.name, ordner: true, abbild: true, volumes: q.volumes,
                   schreibgeschuetzt: true, kennungen: [], dateisystem: q.volumes.map((v) => v.dateisystem).join(", ") };
    erf.gewaehlt = q.pfad;
    erf.platte = null;
    erf.laufWahl = null;
    erf.foto = null;
    erf.umfang = null;
    datentraegerZeichnen();
    plattenZeichnen();
    angabenZeichnen();
  } catch (e) { meldung(e.message, "Fehler"); }
};

// ---------- Registrierte Platten ----------
function plattenZeichnen() {
  const platten = erf.stand.platten.filter((p) => !p.deaktiviert_am);
  const raus = erf.stand.platten.filter((p) => p.deaktiviert_am);
  $("#platten-raus-box").hidden = !raus.length;
  $("#platten-raus-zahl").textContent = raus.length;
  if (raus.some((p) => p.platte_id === erf.platte)) $("#platten-raus-box").open = true;
  $("#platten-raus").innerHTML = raus.map((p) => `<li class="platte-zeile herausgenommen${p.platte_id === erf.platte ? " gewaehlt" : ""}"
      data-platte="${esc(p.platte_id)}">
      <div class="dt-zeile">${traegerIcon(p.traeger, p.anschluss)} <b>${esc(p.platte_id)}</b> <span class="leise">${esc(p.volume_name || "")}</span></div>
      <div class="leise">herausgenommen am ${esc(datumZeit(p.deaktiviert_am))} · ${zahl(p.dateien)} Dateien · ${bytes(p.bytes || 0)}</div></li>`).join("");
  $("#platten-liste").innerHTML = platten.length ? platten.map((p) => {
    const chips = chipsHtml(p);
    const etikett = (p.etikett_text || "").split("\n")[0];
    const da = angeschlossenAls(p.platte_id);
    return `<li class="platte-zeile${p.platte_id === erf.platte ? " gewaehlt" : ""}" data-platte="${esc(p.platte_id)}">
      <div class="dt-zeile">${traegerIcon(p.traeger, p.anschluss)} <b>${esc(p.platte_id)}</b>
        <span class="leise">${esc(p.volume_name || "")}${p.kopie_von ? " · Kopie von " + esc(p.kopie_von) : ""}</span>
        ${da ? `<span class="pille gut">angeschlossen</span>` : ""}</div>
      <div class="leise">${etikett ? "„" + esc(etikett) + "“ · " : ""}${zahl(p.dateien)} Dateien · ${bytes(p.bytes || 0)}
        ${p.ohne_pruefsumme ? ` · <span class="warnung-text">${zahl(p.ohne_pruefsumme)} ohne Prüfsumme</span>` : ""}</div>
      <div class="chips">${chips}</div></li>`;
  }).join("") : `<li class="leise">${raus.length ? "Alle registrierten Datenträger sind aus dem Projekt genommen."
                                                 : "Noch kein Datenträger registriert."}</li>`;
}
const datumZeit = (iso) => (iso || "").slice(0, 16).replace("T", " ");

function angeschlossenAls(kennung) {
  const o = (erf.dt?.ordner || []).find((x) => x.platte_id === kennung);
  if (o?.art === "macplatte") return o.da ? { mountpunkt: o.pfad, name: o.name, schreibgeschuetzt: true, macplatte: true,
                                             kennungen: [kennung] } : null;
  if (o) return o.da ? { mountpunkt: o.pfad, name: o.name, ordner: true, abbild: o.art === "abbild", schreibgeschuetzt: true,
                         kennungen: [kennung] } : null;
  return erf.dt?.angeschlossen.find((d) => (d.kennungen || []).includes(kennung));
}

// ---------- Verschlüsselte Datenträger (13.11.2026) ----------
const VERSCHLUESSELT_HINWEIS = "Verschlüsselte Datenträger entsperrt Balduin mit dem Passwort; es wird nicht gespeichert und "
  + "vor jedem Lauf mit dem Datenträger erneut erfragt.";

// Vor einem Lauf mit dem Datenträger: Passwort erfragen, wenn er verschlüsselt ist. Antwort: das Passwort,
// undefined (nicht nötig) oder null (abgebrochen).
async function passwortFuer(platteId, mitPlatte) {
  const p = erf.stand?.platten.find((x) => x.platte_id === platteId);
  if (!p?.verschluesselt || !mitPlatte) return undefined;
  return passwortGeprueft(`Passwort für ${platteId}`,
    "Der Datenträger ist verschlüsselt. Balduin speichert das Passwort nicht; es gilt nur für diesen Lauf.",
    (passwort) => senden("/api/passwort_pruefen", { platte_id: platteId, passwort }));
}

// ---------- Umfang: nur Teile einer Platte lesen (Fall 1, Entscheidung 05.11.2026) ----------
function umfangZuruecksetzen(wurzel, fest = []) {
  erf.umfang = { wurzel, modus: fest.length ? "teil" : "ganz", gewaehlt: new Set(fest), fest: new Set(fest),
                 offen: new Set(), kinder: new Map(), fehler: "" };
}
const enthalten = (menge, pfad) => [...menge].some((g) => pfad === g || pfad.startsWith(g + "/"));
const umfangListe = () => [...erf.umfang.gewaehlt].filter((p) => !enthalten(new Set([...erf.umfang.gewaehlt].filter((g) => g !== p)), p)).sort();

async function umfangLaden(pfad) {
  const u = erf.umfang;
  if (!u || u.kinder.has(pfad)) return;
  try {
    u.kinder.set(pfad, (await holen("/api/unterordner", { mountpunkt: u.wurzel, pfad,
                                                          ...(u.volume ? { volume_uuid: u.volume } : {}) })).ordner);
  } catch (e) { u.fehler = e.message; u.kinder.set(pfad, []); }
  if (erf.umfang === u) erf.platte ? angabenZeichnen() : angabenZeichnenBehalten();
}

function umfangZweige(pfad, tiefe) {
  const u = erf.umfang, kinder = u.kinder.get(pfad);
  if (!kinder) { umfangLaden(pfad); return `<li class="leise" style="padding-left:${tiefe * 18}px">wird gelesen …</li>`; }
  if (!kinder.length) return tiefe ? "" : `<li class="leise">Keine Ordner auf oberster Ebene.</li>`;
  return kinder.map((o) => {
    const drin = enthalten(u.gewaehlt, o.pfad), fest = enthalten(u.fest, o.pfad);
    const unter = drin && !u.gewaehlt.has(o.pfad);           // schon über einen Ordner darüber gewählt
    const offen = u.offen.has(o.pfad);
    return `<li style="padding-left:${tiefe * 18}px"><div class="umfang-zeile">
        ${o.unterordner ? `<button type="button" class="umfang-auf" data-umfang-auf="${esc(o.pfad)}" aria-expanded="${offen}"
          title="${offen ? "zuklappen" : "Unterordner zeigen"}">${icon(offen ? "chevron-down" : "chevron-right")}</button>`
          : `<span class="umfang-auf"></span>`}
        <label><input type="checkbox" data-umfang="${esc(o.pfad)}" ${drin ? "checked" : ""} ${fest || unter ? "disabled" : ""}>
          ${icon("folder")} ${esc(o.name)}${fest && u.fest.has(o.pfad) ? ` <span class="leise">bisher</span>` : ""}</label></div></li>
      ${offen ? umfangZweige(o.pfad, tiefe + 1) : ""}`;
  }).join("");
}

function umfangHtml(erweitern) {
  const u = erf.umfang;
  const teil = u.modus === "teil";
  return `${erweitern ? "" : `<label class="option"><input type="radio" name="umfang-modus" value="ganz" ${teil ? "" : "checked"}>
      <span>Ganzer Datenträger</span></label>
    <label class="option"><input type="radio" name="umfang-modus" value="teil" ${teil ? "checked" : ""}>
      <span>Nur ausgewählte Ordner <span class="leise">der Datenträger wird trotzdem als Ganzes registriert; der Umfang lässt sich
      später erweitern, aber nicht verkleinern</span></span></label>`}
    ${teil || erweitern ? `<ul class="umfang-baum">${umfangZweige("", 0)}</ul>
      ${u.fehler ? `<div class="fehler">${esc(u.fehler)}</div>` : ""}
      <div class="leise">${u.gewaehlt.size ? "Gewählt: " + umfangListe().map(esc).join(", ") : "Noch kein Ordner gewählt."}</div>` : ""}`;
}

function platteWaehlen(e) {
  const li = e.target.closest("li[data-platte]");
  if (!li) return;
  erf.platte = li.dataset.platte;
  erf.laufWahl = null;                                   // rechts wieder den laufenden bzw. den Lauf dieser Platte
  erf.gewaehlt = null;
  erf.auswahl.clear();
  erf.foto = null;
  datentraegerZeichnen();
  plattenZeichnen();
  angabenZeichnen();
  standErfassung();
}
$("#platten-liste").addEventListener("click", platteWaehlen);
$("#platten-raus").addEventListener("click", platteWaehlen);

// ---------- Bestand aus Anton: Stand, holen (Hintergrundlauf), fortsetzen ----------
const tageText = (n) => (n == null ? "" : n <= 0 ? "heute" : n === 1 ? "gestern" : `vor ${n} Tagen`);

function antonZeichnen() {
  const a = erf.stand.anton, s = a.stand, l = a.lauf;
  const host = (() => { try { return new URL(a.url).host; } catch { return a.url; } })();
  const laeuft = laeuftArt("anton");
  const eingereiht = erf.stand.warteschlange.some((w) => w.art === "anton");
  const fehlgeschlagen = !laeuft && !eingereiht && l && l.status !== "fertig" && l.status !== "eingereiht";
  const zeilen = [];
  if (s) {
    zeilen.push(`<div><b>Stand ${esc(datumDe(s.datum))}</b> <span class="leise">(${esc(tageText(s.alter_tage))})</span>
      · ${zahl(s.dateien)} Anton-Dateien · Zugang ${esc(s.zugang || "?")}</div>
      <div class="leise">${esc(host)}${s.quelle && !s.quelle.endsWith("_api.csv") ? ` · aus ${esc(s.quelle)}` : ""}</div>`);
    if (s.alter_tage != null && s.alter_tage >= a.alt_ab)
      zeilen.push(`<div class="hinweis warnung">Der Bestand ist ${s.alter_tage} Tage alt. Neu holen, wenn seither in Anton importiert
        wurde, und auf jeden Fall vor dem Export.</div>`);
    if (s.zugang === "öffentlich")
      zeilen.push(`<div class="hinweis warnung">Nur öffentliche Bestände: Dateien in nicht öffentlichen Beständen erscheinen
        fälschlich als „nicht in Anton“. API-Token in den Einstellungen des Projekts (${icon("settings")} vor „Registrierung/Analyse“) hinterlegen und neu holen.</div>`);
    if (s.zugang === "mit Token")
      zeilen.push(`<div class="leise">Mit API-Token geholt, das API-Token sieht aber nicht mehr als öffentlich: vollständig, wenn alles
        öffentlich ist; sonst dem Konto in Anton eine interne Rolle geben.</div>`);
    if (s.nur_platten)
      zeilen.push(`<div class="hinweis warnung">Kein vollständiger Bestand (Auszug): „nicht in Anton“ gilt nur für
        ${esc(s.nur_platten)}. Neu holen gibt einen vollständigen Stand.</div>`);
  } else {
    zeilen.push(`<div class="leise">Noch kein Bestand aus ${esc(host)} geladen. Ohne ihn bleibt der Anton-Abgleich offen.</div>`);
  }
  if (!a.token) zeilen.push(`<div class="leise">Kein API-Token hinterlegt: Es kämen nur öffentliche Bestände (Einstellungen des Projekts, ${icon("settings")} vor „Registrierung/Analyse“).</div>`);
  if (fehlgeschlagen)
    zeilen.push(`<div class="hinweis warnung">Letzter Abruf ${esc(l.status === "läuft" ? "abgebrochen" : l.status)}
      (${esc(datumZeit(l.ende || l.start))})${l.meldung ? ": " + esc(l.meldung) : ""}</div>`);
  const wort = "holen";                                  // eigene Spur: startet sofort, auch neben einer Analyse
  zeilen.push(`<div class="knopfzeile">
    ${laeuft ? `<span class="leise">wird gerade geholt (Fortschritt rechts)</span>`
      : eingereiht ? `<span class="leise">eingereiht (Warteschlange rechts)</span>`
      : `${fehlgeschlagen ? `<button type="button" class="haupt" data-anton="fortsetzen">Fortsetzen</button>` : ""}
         <button type="button" ${fehlgeschlagen || s ? "" : 'class="haupt"'} data-anton="holen">Bestand aus Anton ${wort}</button>`}</div>`);
  $("#anton-stand").innerHTML = zeilen.join("");
}
const datumDe = (iso) => (iso ? iso.split("-").reverse().join(".") : "");

$("#anton-stand").addEventListener("click", async (e) => {
  const knopf = e.target.closest("[data-anton]");
  if (!knopf) return;
  const a = erf.stand.anton;
  if (knopf.dataset.anton === "holen" && !(await rueckfrage(`Den ganzen Bestand aus Anton (${a.url}) neu holen?`,
    "Das dauert etwa 15–20 Minuten und braucht Internet; danach werden alle Datenträger abgeglichen. Ein Abbruch lässt sich "
    + "am selben Tag fortsetzen. Eine Analyse kann daneben weiterlaufen." + (a.token ? "" : "\n\nOhne API-Token kommen nur öffentliche Bestände."),
    "Bestand holen"))) return;
  knopf.disabled = true;
  try {
    if (knopf.dataset.anton === "holen") await senden("/api/anton_holen", {});
    else await senden("/api/fortsetzen", { lauf_id: a.lauf.lauf_id });
  } catch (err) { meldung(err.message, "Fehler"); }
  standErfassung();
});

// Vor einer Analyse (Feedback 04.11.2026): fehlt der Bestand aus Anton oder ist er alt, fragen, ob er zuerst geholt
// werden soll; „holen“ startet den Abruf in seiner eigenen Spur, die Analyse beginnt gleichzeitig (Entscheidung 05.11.2026).
// Antwort: true = weiter, false = abgebrochen
function antonVorab() {
  const a = erf.stand.anton, s = a.stand;
  const schon = laeuftArt("anton") || erf.stand.warteschlange.some((w) => w.art === "anton");
  const alt = s && s.alter_tage != null && s.alter_tage >= a.alt_ab;
  if (schon || (s && !alt)) return Promise.resolve(true);
  $("#an-inhalt").innerHTML = `<p class="dialog-text">${s ? `Der Bestand aus Anton ist <b>${s.alter_tage} Tage alt</b>.`
      : "Es liegt <b>noch kein Bestand aus Anton</b> vor."} Ohne aktuellen Bestand bleibt der Anton-Abgleich (G5) offen oder
      zeigt Dateien fälschlich als „nicht in Anton“; er lässt sich später nachholen.</p>
    <p class="dialog-text leise">Holen dauert etwa 15–20 Minuten und braucht Internet${a.token ? "" : "; ohne API-Token kommen nur öffentliche Bestände"}.
      Die Analyse startet gleichzeitig; was sie vor dem Ende des Abrufs abgleicht, gleicht der Abruf danach für alle Datenträger nach.</p>`;
  return new Promise((fertig) => {
    const dlg = $("#an-dialog");
    dlg.onclick = async (ev) => {
      const k = ev.target.closest("[data-an]");
      if (!k) return;
      dlg.onclick = dlg.oncancel = null;
      dlg.close();
      if (k.dataset.an === "holen") {
        try { await senden("/api/anton_holen", {}); } catch (err) { meldung(err.message, "Fehler"); return fertig(false); }
      }
      fertig(!!k.dataset.an);
    };
    dlg.oncancel = () => { dlg.onclick = dlg.oncancel = null; fertig(false); };
    dlg.showModal();
  });
}

// ---------- Registrierte Platte: Angaben ansehen und ändern ----------
// Schritte je Platte, gleiche Namen wie erfassung/lauf.py; nb = Abschnitt in Notebook 1; platte = liest die Platte;
// braucht = Voraussetzungen (Hinweis); folgt = Pflicht-Folgeschritte einer Auswahl (wie FOLGESCHRITTE in erfassung/lauf.py)
const SCHRITTE = [
  { k: "C", name: "Verzeichnis", nb: "C1", platte: true, braucht: [], hilfe: "liest nur das Verzeichnis des Datenträgers (Pfad, Größe, Datum)" },
  { k: "D1", name: "Prüfsummen", nb: "D1", platte: true, braucht: ["C"], hilfe: "liest jede Datei einmal ganz (SHA-256, MD5)" },
  { k: "D2", name: "Formate", nb: "D2", platte: true, braucht: ["D1"], hilfe: "erkennt das Format am Inhalt (PRONOM)" },
  { k: "D3", name: "Virenscan", nb: "D3", platte: true, braucht: ["D1"], hilfe: "prüft jeden Inhalt einmal auf Schadsoftware; gilt für alle Datenträger mit diesem Inhalt" },
  { k: "E", name: "Metadaten", nb: "E", platte: true, braucht: ["D1", "D3"], hilfe: "liest alle eingebetteten Metadaten, speichert sie vollständig und bestimmt das beste Datum" },
  { k: "E4", name: "Texte", nb: "E4", platte: true, braucht: ["D1", "D3"], hilfe: "liest den Text der Dokumente (PDF, Word, PowerPoint, OpenDocument, RTF, HTML, Text) und mögliche Titel; ohne Texterkennung, Bild-PDFs bleiben ohne Text" },
  { k: "F", name: "Vorschaubilder", nb: "F", platte: true, braucht: ["D2", "D3"], hilfe: "erzeugt die Vorschaubilder (im Projektordner oder auf dem Datenträger für Vorschaubilder)" },
  { k: "F5", name: "Personen", nb: "F5", platte: false, braucht: ["F"], hilfe: "erkennt Personen und Gesichter (Porträts) auf den Vorschaubildern der Fotos (optional, in den Einstellungen an „Registrierung/Analyse“ einschalten)" },
  { k: "G", name: "Dubletten", nb: "G1–G4", platte: false, braucht: ["D1", "E", "F"], folgt: ["H"], hilfe: "vergleicht alle Datenträger: exakte Kopien, Formatvarianten, beinahe gleiche Bilder" },
  { k: "G5", name: "Anton-Abgleich", nb: "G5", platte: false, braucht: ["D1"], hilfe: "gleicht die MD5 jeder Datei mit dem geladenen Bestand aus Anton ab" },
  { k: "H", name: "Archivfähigkeit", nb: "H", platte: false, braucht: ["D2", "D3", "E", "F", "G"], hilfe: "Ampel je Datei, NARA-Risiko daneben, Leitdatei je Dublettengruppe" },
];
const SCHRITT = Object.fromEntries(SCHRITTE.map((s) => [s.k, s]));

function offenText(p, k) {
  const n = p.offen?.[k], o = p.offen || {};
  if ((k === "D3" && o.D3_aus) || (k === "F5" && o.F5_aus)) return "übersprungen, im Projekt ausgeschaltet";
  // 0 offen, aber noch nicht grün: eine Voraussetzung fehlt oder der laufende Lauf ist noch nicht so weit (server.py,
  // erledigte_schritte)
  if (n === 0 && !p.erledigt?.includes(k)) {
    const fehlt = (SCHRITT[k]?.braucht || []).filter((v) => !p.erledigt?.includes(v)).map((v) => SCHRITT[v].name);
    return fehlt.length ? `wartet auf ${fehlt.join(", ")}` : "kommt im laufenden Lauf noch dran";
  }
  if (n === 0) return k === "G5" ? `erledigt (Bestand aus Anton vom ${o.G5_stand})` : "erledigt";
  if (k === "G5" && n == null) return "noch kein Bestand aus Anton geladen (links „Bestand aus Anton holen“)";
  if (k === "F5" && n == null) return "wartet auf die Vorschaubilder";
  if (n == null) return "noch nicht gelaufen";
  if (k === "C" && o.C_archive) return `${zahl(o.C_archive)} ${o.C_archive === 1 ? "Archivdatei" : "Archivdateien"} (ZIP, tar, gz) noch nicht geöffnet: Datenträger anschließen und „Alles Offene fortsetzen“`;
  if (k === "F5") return `${zahl(n)} Fotos noch nicht auf Personen geprüft`;
  if (k === "E4" && n == null) return "wartet auf die Prüfsummen";
  if (k === "E4") return `${zahl(n)} Dokumente noch ohne Text`;
  if (k === "G" && o.G_platten) return "Datenträger wurden aus dem Projekt genommen oder wieder aufgenommen: neu abgleichen";
  if (k === "G") return `${zahl(n)} Dateien seit dem letzten Abgleich neu oder geändert`;
  if (k === "G5") return [o.G5_neu ? `${zahl(o.G5_neu)} Dateien noch nicht abgeglichen` : "",
    o.G5_ungeprueft ? `${zahl(o.G5_ungeprueft)} nicht geprüft, weil der Bestand aus Anton (${o.G5_stand}) diesen Datenträger nicht abdeckt` : ""]
    .filter(Boolean).join(", ");
  if (k === "H") return [n - (o.H_leit || 0) ? `${zahl(n - (o.H_leit || 0))} Dateien ohne aktuelle Ampel` : "",
    o.H_leit ? `in ${zahl(o.H_leit)} Dublettengruppen fehlt die Leitdatei (Dubletten wurden neu abgeglichen)` : ""].filter(Boolean).join(", ");
  return `${zahl(n)} Dateien offen`;
}
// Klassen eines Chips: erledigt; im Projekt ausgeschaltet (Virenscan, Personen) zusätzlich übersprungen (gestrichelt)
const ausgeschaltet = (p, k) => (k === "D3" && p.offen?.D3_aus) || (k === "F5" && p.offen?.F5_aus);
function chipKlasse(p, k) {
  return (p.erledigt.includes(k) ? " erledigt" : "") + (ausgeschaltet(p, k) ? " uebersprungen" : "");
}
function chipsHtml(p) {
  return SCHRITTE.map((s) => `<span class="chip${chipKlasse(p, s.k)}"
    title="${esc(s.name + ": " + offenText(p, s.k))}">${esc(s.name)}</span>`).join("");
}

// Was noch offen ist, je Schritt mit Grund; „Alles Offene fortsetzen“ holt es in der Reihenfolge nach
function offenInfo(p) {
  const offen = SCHRITTE.filter((s) => !p.erledigt.includes(s.k) && !ausgeschaltet(p, s.k));
  const tipp = `<div class="leise">Schritte anklicken, um nur diese auszuführen.</div>`;
  if (!offen.length) return `<div class="leise">Alle ${SCHRITTE.length} Schritte erledigt.</div>${tipp}`;
  return `<ul class="auswahl-liste">${offen.map((s) => `<li><b>${esc(s.name)}</b>
      <span class="leise">${s.platte ? "braucht den Datenträger" : "läuft ohne Datenträger"}</span>
      <div>${esc(offenText(p, s.k))} · <span class="leise">${esc(s.hilfe)}</span></div></li>`).join("")}</ul>${tipp}`;
}

// Gewählte Schritte samt Pflicht-Folgeschritten (G → H), in der festen Reihenfolge
function auswahlMitFolgen() {
  const alle = new Set(erf.auswahl);
  for (const k of erf.auswahl) (SCHRITT[k].folgt || []).forEach((f) => alle.add(f));
  return SCHRITTE.filter((s) => alle.has(s.k));
}

// Was die Auswahl tut: je Schritt Stand, Pflichtfolgen, offene Voraussetzungen (nur Hinweis) und ob sie die Platte braucht
function auswahlInfo(p, bereit) {
  const liste = auswahlMitFolgen();
  const zeilen = liste.map((s) => {
    const wegen = SCHRITTE.filter((x) => erf.auswahl.has(x.k) && (x.folgt || []).includes(s.k)).map((x) => x.name);
    const folge = !erf.auswahl.has(s.k);
    const offen = s.braucht.filter((b) => !p.erledigt.includes(b) && !erf.auswahl.has(b) && !ausgeschaltet(p, b));
    const hinweise = offen.length ? `<div class="warnung-text">setzt ${offen.map((b) => esc(SCHRITT[b].name)).join(", ")} voraus
        (noch offen; gerechnet wird mit dem, was da ist) <button type="button" class="knopf-leise" data-mit="${offen.join(",")}">mit auswählen</button></div>` : "";
    const stand = ausgeschaltet(p, s.k) ? "im Projekt ausgeschaltet, wird übersprungen"
      : p.erledigt.includes(s.k) ? "erledigt, nichts offen (für alles neu: „Neu analysieren“)" : offenText(p, s.k);
    return `<li><b>${esc(s.name)}</b> <span class="leise">${folge ? `kommt mit (nach ${esc(wegen.join(", "))} nötig) · ` : ""}${s.platte ? "braucht den Datenträger" : "läuft ohne Datenträger"}</span>
      <div>${esc(stand)} · <span class="leise">${esc(s.hilfe)}</span></div>${hinweise}</li>`;
  }).join("");
  const mitPlatte = liste.filter((s) => s.platte);
  const platteHinweis = mitPlatte.length && !bereit
    ? `<div class="hinweis warnung">${mitPlatte.map((s) => esc(s.name)).join(", ")} ${mitPlatte.length > 1 ? "brauchen" : "braucht"}
        den Datenträger: anschließen${systemwort("kein_schreibschutz") ? "" : ", schreibgeschützt einhängen"} und links „Aktualisieren“ wählen.</div>` : "";
  return `<ul class="auswahl-liste">${zeilen}</ul>${platteHinweis}
    <button type="button" class="knopf-leise" id="auswahl-leeren">Auswahl aufheben</button>`;
}

// Es läuft immer nur eine Analyse, weitere werden eingereiht; je Platte höchstens ein Lauf laufend oder eingereiht
function belegtText(kennung) {
  if (laufende().some((l) => l.platte_id === kennung)) return "Dieser Datenträger wird gerade analysiert (Fortschritt rechts).";
  if ((erf.stand?.warteschlange || []).some((w) => w.platte_id === kennung))
    return "Dieser Datenträger ist schon eingereiht; rechts in der Warteschlange lässt sich der Lauf entfernen.";
  return "";
}
const einreihen = () => !!hauptspurBelegt();            // der Anton-Abruf hält eine Analyse nicht auf
const einreihenText = () => `Gerade läuft ${hauptspurBelegt().name}. Ein Start reiht diesen Lauf ein; `
  + "er beginnt von selbst, sobald die laufenden und vorher eingereihten fertig sind.";
const einreihenFrage = () => (einreihen() ? `\n\nGerade läuft ${hauptspurBelegt().name}: Der Lauf wird eingereiht `
  + "und startet danach von selbst. Bis dahin muss der Datenträger angeschlossen bleiben." : "");

// Herausgenommene Platte: nur ansehen und wieder aufnehmen; ihre Daten sind vollständig erhalten
function herausgenommenPanel(p) {
  $("#angaben").innerHTML = `
    <div class="titel-gross">${esc(p.platte_id)}</div>
    <div class="leise">${esc(p.volume_name || "")}</div>
    <div class="hinweis warnung">Am ${esc(datumZeit(p.deaktiviert_am))} aus dem Projekt genommen. Bewertung, Dashboard und
      Dubletten lassen ihn aus; Analysen sind gesperrt.</div>
    <dl class="angaben-liste">
      <dt>Dateien</dt><dd>${zahl(p.dateien)} · ${bytes(p.bytes || 0)}</dd>
      ${p.etikett_text ? `<dt>Etikett</dt><dd>${esc(p.etikett_text)}</dd>` : ""}
      ${p.notiz ? `<dt>Notiz</dt><dd>${esc(p.notiz)}</dd>` : ""}
    </dl>
    <div class="ueberschrift">Analyse (erhalten)</div>
    <div class="chips">${chipsHtml(p)}</div>
    <div class="knopfzeile"><button type="button" class="haupt" id="wieder-aufnehmen">${icon("archive-restore")} Wieder ins Projekt aufnehmen</button></div>
    <div class="leise tipp">Alles Berechnete ist noch da und gilt sofort wieder. Danach „Alles Offene fortsetzen“ wählen
      (geht ohne Datenträger), damit er wieder in den Dublettengruppen steht.</div>`;
}

// Ohne Schreibschutz lesen (Entscheidung 13.11.2026): schon zugestimmt? Sonst nachfragen. Antwort: weiter?
const ohneSchutzZugestimmt = (kennung) => !!erf.stand?.platten.find((p) => p.platte_id === kennung)?.ohne_schreibschutz;
async function ohneSchutzKlaeren(dt, kennung) {
  if (!dt || dt.schreibgeschuetzt || ohneSchutzZugestimmt(kennung)) return true;
  return ohneSchreibschutzFragen(kennung);
}

// Hinweis bei einem beschreibbar eingehängten Datenträger; unter Windows ohne „Schreibgeschützt einhängen“
function beschreibbarHinweis(kennung) {
  const kein = systemwort("kein_schreibschutz");
  if (kennung && ohneSchutzZugestimmt(kennung)) {
    return `<div class="hinweis">Beschreibbar eingehängt; dem Lesen ohne Schreibschutz ist zugestimmt (protokolliert).</div>`;
  }
  return kein
    ? `<div class="hinweis warnung">${esc(kein)} Vor dem Lesen fragt Balduin deshalb nach. Wer ganz sauber arbeiten will,
        schließt den Datenträger über einen Writeblocker an.</div>`
    : `<div class="hinweis warnung">Beschreibbar eingehängt: Das Betriebssystem kann dann eigene Dateien (etwa Indexdateien)
        anlegen. Besser links „Schreibgeschützt einhängen“ wählen; sonst fragt Balduin vor dem Lesen nach.</div>`;
}

function plattePanel(p) {
  if (p.deaktiviert_am) return herausgenommenPanel(p);
  const dt = angeschlossenAls(p.platte_id);
  const bereit = !!dt;                     // beschreibbar: Rückfrage beim Start (13.11.2026)
  const belegt = belegtText(p.platte_id);
  const wort = einreihen() && !belegt ? " einreihen" : "";
  // Fortsetzen geht auch ohne Platte (dann nur Duplikate, Anton-Abgleich, Archivfähigkeit); Neu analysieren nicht
  const sperre = belegt;
  const sperreNeu = belegt || (!dt ? "Neu analysieren braucht den Datenträger: anschließen und links „Aktualisieren“ wählen." : "");
  const sperreAuswahl = belegt || (auswahlMitFolgen().some((s) => s.platte) && !bereit
    ? "Die gewählten Schritte brauchen den Datenträger." : "");
  const ohnePlatte = !dt && !belegt ? "Datenträger nicht angeschlossen: „Alles Offene fortsetzen“ holt nur Dubletten, "
    + "Anton-Abgleich und Archivfähigkeit nach. Für die übrigen Schritte den Datenträger anschließen und links „Aktualisieren“ wählen." : "";
  const andere = erf.stand.platten.filter((x) => x.platte_id !== p.platte_id && (!x.deaktiviert_am || x.platte_id === p.kopie_von));
  const foto = p.etikett_foto ? `/etiketten/${encodeURIComponent(p.etikett_foto.split("/").pop())}?t=${Date.now()}` : null;
  const zeile = (name, wert) => (wert ? `<dt>${name}</dt><dd>${wert}</dd>` : "");
  const ordner = p.art === "ordner" || p.art === "abbild";
  const abbild = p.art === "abbild";
  const umfang = p.umfang ? JSON.parse(p.umfang) : [];
  if (erf.umfangOffen && (!erf.umfang || erf.umfang.wurzel !== dt?.mountpunkt)) {
    if (dt) umfangZuruecksetzen(dt.mountpunkt, umfang); else erf.umfangOffen = false;
  }
  $("#angaben").innerHTML = `
    <div class="titel-gross">${esc(p.platte_id)}</div>
    <div class="leise">${esc(p.volume_name || "")}${dt ? ` · ${ordner ? "liegt" : "angeschlossen"} unter ${esc(dt.mountpunkt)}`
      : ordner ? ` · <span class="warnung-text">nicht gefunden unter ${esc(p.quellordner || "")}</span>` : " · nicht angeschlossen"}</div>
    <dl class="angaben-liste">
      ${zeile("Dateien", `${zahl(p.dateien)} · ${bytes(p.bytes || 0)}`)}
      ${ordner ? zeile("Quelle", `${abbild ? `Abbild (${esc(p.dateisystem || "")})` : "Ordner"} ${esc(p.quellordner || "")}`)
        : zeile("Datenträger", esc([p.modell, p.anschluss, p.dateisystem].filter(Boolean).join(" · ")) + (p.kapazitaet_bytes ? ` · ${bytes(p.kapazitaet_bytes)}` : ""))}
      ${ordner && !abbild ? "" : zeile("Umfang", umfang.length ? umfang.map(esc).join(", ") : "ganzer Datenträger")}
      ${p.verschluesselt ? zeile("Verschlüsselt", "ja; vor jedem Lauf fragt Balduin nach dem Passwort (es wird nicht gespeichert)") : ""}
      ${zeile("Erkannt an", abbild ? "Ort, Volume-UUID und Stichprobe von Dateien" : ordner ? "Ort und Stichprobe von Dateien (Ordner ohne UUID)"
        : p.uuid ? "Volume-UUID" : "Name, Dateisystem, Größe und Stichprobe (keine UUID)")}
      ${zeile("SMART", esc(p.smart_status || ""))}
      ${zeile("Registriert", esc((p.registriert_am || "").slice(0, 16).replace("T", " ")))}
    </dl>
    <div class="ueberschrift">Analyse</div>
    <div class="chips gross">${SCHRITTE.map((s) =>
      `<button type="button" class="chip${chipKlasse(p, s.k)}${erf.auswahl.has(s.k) ? " gewaehlt" : ""}"
         data-chip="${s.k}" aria-pressed="${erf.auswahl.has(s.k)}" title="${esc(s.name + ": " + offenText(p, s.k))}">${esc(s.name)}</button>`).join("")}</div>
    <div class="chip-info">${erf.auswahl.size ? auswahlInfo(p, bereit) : offenInfo(p)}</div>
    ${antonHinweis(p)}
    ${kopieHinweis(p)}
    ${abbild ? `<div class="hinweis">Abbild: Balduin liest es nur, ohne es einzubinden.${dt ? "" : ` Ist es verschoben,
      den neuen Ort wählen; Balduin prüft die Volume-UUID und eine Stichprobe.<div class="knopfzeile"><button type="button"
      id="abbild-verlegen">${icon("folder-search")} Neuen Ort wählen …</button></div>`}</div>`
    : ordner ? `<div class="hinweis">Ordner als Quelle: Balduin liest ihn nur. Er lässt sich nicht schreibgeschützt öffnen;
      deshalb zeigt Balduin seine Dateien nicht im ${systemwort("dateimanager")}.${dt ? "" : ` Ist er verschoben, den neuen Ort wählen; Balduin prüft
      ihn an einer Stichprobe.<div class="knopfzeile"><button type="button" id="ordner-verlegen">${icon("folder-search")} Neuen Ort wählen …</button></div>`}</div>` : ""}
    ${(!ordner || (abbild && !p.verschluesselt)) && umfang.length ? `<div class="ueberschrift">Umfang</div>
      ${erf.umfangOffen && dt ? `${umfangHtml(true)}
        <div class="knopfzeile"><button type="button" class="haupt" id="umfang-erweitern" ${belegt || !bereit
          || umfangListe().join("|") === umfang.join("|") ? "disabled" : ""}>Erweitern und fortsetzen</button>
          <button type="button" id="umfang-zu">Abbrechen</button></div>
        <div class="leise tipp">Danach liest „Fortsetzen“ das Inhaltsverzeichnis neu; was schon analysiert ist, bleibt.</div>`
      : `<div class="leise">Gelesen wird nur ${umfang.map((u) => "„" + esc(u) + "“").join(", ")}.</div>
        <div class="knopfzeile"><button type="button" id="umfang-auf" ${dt ? "" : "disabled"}
          title="${dt ? "Weitere Ordner des Datenträgers aufnehmen" : "Dafür den Datenträger anschließen"}">${icon("folder-plus")} Umfang erweitern …</button>
          <button type="button" id="umfang-ganz" ${dt && bereit && !belegt ? "" : "disabled"}>Ganzen Datenträger lesen …</button></div>`}` : ""}
    ${dt && !dt.schreibgeschuetzt ? beschreibbarHinweis(p.platte_id) : ""}
    <div class="knopfzeile">
      ${erf.auswahl.size ? `<button type="button" class="haupt" data-platte-lauf="auswahl" ${sperreAuswahl ? "disabled" : ""}
        title="Nur die gewählten Schritte (samt Pflichtfolgen); jeder macht nur, was fehlt">Auswahl ${wort ? "einreihen" : "ausführen"} (${auswahlMitFolgen().length})</button>` : ""}
      <button type="button" class="${erf.auswahl.size ? "" : "haupt"}" data-platte-lauf="fortsetzen" ${sperre ? "disabled" : ""}
        title="Abgebrochenes weiterführen und alles Offene nachholen, Schritt für Schritt in der Reihenfolge">Alles Offene fortsetzen${wort}</button>
      <button type="button" data-platte-lauf="neu" ${sperreNeu ? "disabled" : ""}
        title="Prüfsummen, Formate, Virenscan und Metadaten dieses Datenträgers neu bestimmen; liest den ganzen Datenträger">Neu analysieren${wort}</button></div>
    ${erf.auswahl.size && belegt ? `<div class="leise tipp">${esc(belegt)}</div>`
      : !erf.auswahl.size && (sperre || sperreNeu || ohnePlatte) ? `<div class="leise tipp">${esc(sperre || ohnePlatte || sperreNeu)}</div>`
      : wort ? `<div class="leise tipp">${esc(einreihenText())}</div>` : ""}
    <div class="ueberschrift">Angaben</div>
    <div class="felder">
      <label>${ordner ? "Herkunft (woher, von wem, seit wann)" : "Etikett (so abschreiben, wie es dasteht)"}
        <textarea id="f-etikett" rows="4">${esc(p.etikett_text || "")}</textarea></label>
      <label>Foto des ${ordner ? "Begleitschreibens (optional)" : "Etiketts"} ${foto ? "" : "(noch keines)"}
        ${foto ? `<img class="etikett-foto" src="${foto}" alt="Etikett von ${esc(p.platte_id)}">` : ""}
        <input id="f-foto" type="file" accept="image/*"></label>
      <label>Notiz (Herkunft, Zustand)
        <input id="f-notiz" value="${esc(p.notiz || "")}"></label>
      <label>Kopie von (Backup oder Klon eines anderen Datenträgers)
        <select id="f-kopie"><option value="">–</option>${andere.map((x) =>
          `<option ${p.kopie_von === x.platte_id ? "selected" : ""}>${esc(x.platte_id)}</option>`).join("")}</select></label>
    </div>
    <div class="knopfzeile"><button type="button" id="speichern">Angaben zum Datenträger speichern</button>
      <span id="gespeichert" class="leise"></span></div>
    <div class="leise tipp">Etikett und Foto gehören zur Überlieferung (Bestandsgeschichte); jede Änderung kommt ins Protokoll.</div>
    <div class="ueberschrift">Aus dem Projekt nehmen</div>
    <div class="leise">Der Datenträger verschwindet aus Bewertung, Dashboard und Dubletten. Gelöscht wird nichts: Prüfsummen,
      Formate, Metadaten, Vorschaubilder und Entscheidungen bleiben erhalten, der Datenträger lässt sich jederzeit wieder aufnehmen.</div>
    <div class="knopfzeile"><button type="button" class="gefahr" id="herausnehmen" ${belegt ? "disabled" : ""}>
      ${icon("archive-x")} ${esc(p.platte_id)} aus dem Projekt nehmen …</button></div>
    ${belegt ? `<div class="leise tipp">${esc(belegt)}</div>` : ""}`;
}

// Liegen fast alle Dateien bitgleich auch auf einer anderen Platte (Prüfsummen), ist sie vermutlich ein Backup oder Klon
const KOPIE_AB = 0.95;
const anteilProzent = (x) => `${Math.floor(100 * x)} %`;          // abgerundet: 94,9 % bleibt unter 95 %
// Prüfsummen liegen vor, aber ohne Bestand aus Anton bleibt der Abgleich offen (der Lauf überspringt G5 dann);
// bleibt sichtbar, bis der Bestand geholt ist, damit es nach einer langen Analyse nicht untergeht
function antonHinweis(p) {
  if (p.offen?.G5 != null || !p.erledigt.includes("D1")) return "";
  return `<div class="hinweis warnung">Anton-Abgleich steht aus: Es liegt noch kein Bestand aus Anton vor, deshalb wurde er
    übersprungen. Links „Bestand aus Anton holen“ wählen; danach werden alle Datenträger abgeglichen.</div>`;
}

function kopieHinweis(p) {
  const g = p.gleich || {};
  const teile = [];
  if (p.kopie_von) {
    const info = g[p.kopie_von];
    teile.push(`<div class="leise tipp">Als Kopie von ${esc(p.kopie_von)} vermerkt${info
      ? `; ${anteilProzent(info.anteil)} der Dateien (${zahl(info.dateien)} von ${zahl(info.von)}) liegen dort bitgleich` : ""}.</div>`);
  }
  // nicht vorschlagen, wenn schon umgekehrt vermerkt ist (die andere Platte ist eine Kopie von dieser)
  const kopienHiervon = new Set(erf.stand.platten.filter((x) => x.kopie_von === p.platte_id).map((x) => x.platte_id));
  const kandidaten = Object.entries(g).filter(([b, i]) => b !== p.kopie_von && !kopienHiervon.has(b) && i.anteil >= KOPIE_AB)
    .sort((x, y) => y[1].anteil - x[1].anteil);
  for (const [b, i] of kandidaten) {
    const zurueck = erf.stand.platten.find((x) => x.platte_id === b)?.gleich?.[p.platte_id];
    const beide = zurueck && zurueck.anteil >= KOPIE_AB;
    teile.push(`<div class="hinweis">${anteilProzent(i.anteil)} der Dateien von ${esc(p.platte_id)} (${zahl(i.dateien)} von
      ${zahl(i.von)}, ab 1 KB) liegen bitgleich auch auf ${esc(b)}. Ist ${esc(p.platte_id)} ein Backup oder Klon?
      ${beide ? `<div class="leise">Umgekehrt liegen auch ${anteilProzent(zurueck.anteil)} von ${esc(b)} auf ${esc(p.platte_id)}:
        Beide enthalten fast dasselbe. Als Kopie gilt der Datenträger, der später entstanden ist (Etikett, Datum).</div>` : ""}
      <div class="knopfzeile"><button type="button" class="knopf-leise" data-kopie="${esc(b)}">${esc(p.platte_id)} als Kopie
        von ${esc(b)} vermerken</button></div></div>`);
  }
  return teile.join("");
}
$("#angaben").addEventListener("click", async (e) => {
  const knopf = e.target.closest("[data-kopie]");
  if (!knopf || !erf.platte) return;
  const original = knopf.dataset.kopie;
  if (!(await rueckfrage(`${erf.platte} als Kopie von ${original} vermerken?`, "Der Vermerk geht in die Bestandsgeschichte; "
    + "die Archivfähigkeit bevorzugt danach als Leitdatei die Datei auf dem Original (dafür „Archivfähigkeit“ neu ausführen). "
    + "Die Änderung wird protokolliert.", "Als Kopie vermerken"))) return;
  knopf.disabled = true;
  try {
    await senden("/api/platte_angaben", { platte_id: erf.platte, kopie_von: original });
  } catch (err) { meldung(err.message, "Fehler"); knopf.disabled = false; return; }
  await standErfassung();
  angabenZeichnen();
});

// Bestätigung im Dialog: erst wenn die Kennung genau eingetippt ist
function herausnehmenFragen(p) {
  const dlg = $("#raus-dialog");
  const verweise = erf.stand.platten.filter((x) => x.kopie_von === p.platte_id && !x.deaktiviert_am).map((x) => x.platte_id);
  $("#raus-titel").textContent = `${p.platte_id} aus dem Projekt nehmen?`;
  $("#raus-text").innerHTML = `${zahl(p.dateien)} Dateien (${bytes(p.bytes || 0)}) fallen aus Bewertung, Dashboard und
    Dubletten heraus. Die Daten bleiben in der Datenbank; „Wieder ins Projekt aufnehmen“ macht das rückgängig.
    Danach Dubletten (G) neu abgleichen.${verweise.length ? `<br><span class="warnung-text">${esc(verweise.join(", "))}
    ${verweise.length > 1 ? "sind" : "ist"} als Kopie dieses Datenträgers vermerkt; der Vermerk bleibt.</span>` : ""}`;
  $("#raus-kennung").textContent = p.platte_id;
  $("#raus-eingabe").value = "";
  $("#raus-fehler").textContent = "";
  $("#raus-ok").disabled = true;
  dlg.dataset.platte = p.platte_id;
  dlg.showModal();
  $("#raus-eingabe").focus();
}
$("#raus-eingabe").addEventListener("input", (e) => {
  $("#raus-ok").disabled = e.target.value.trim() !== $("#raus-dialog").dataset.platte;
});
$("#raus-abbrechen").onclick = () => $("#raus-dialog").close();
$("#raus-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const platte = $("#raus-dialog").dataset.platte;
  if ($("#raus-eingabe").value.trim() !== platte) return;
  $("#raus-ok").disabled = true;
  try {
    await senden("/api/platte_herausnehmen", { platte_id: platte, herausnehmen: true, bestaetigung: $("#raus-eingabe").value });
  } catch (err) {
    $("#raus-fehler").textContent = err.message;
    $("#raus-ok").disabled = false;
    return;
  }
  $("#raus-dialog").close();
  nachHerausnehmen();
});

async function nachHerausnehmen() {
  erf.auswahl.clear();
  await standErfassung();
  angabenZeichnen();
  standLaden().catch(() => {});                       // Bäume der Bewertung ohne bzw. wieder mit der Platte
}

// ---------- Angaben ----------
function gewaehlterDt() {
  return dtListe().find((d) => d.mountpunkt === erf.gewaehlt);
}

function angabenZeichnen() {
  const p = erf.platte && erf.stand?.platten.find((x) => x.platte_id === erf.platte);
  if (p) return plattePanel(p);
  const d = gewaehlterDt();
  if (!d) {
    $("#angaben").innerHTML = `<div class="leer-hinweis">Links einen Datenträger wählen.</div>`;
    return;
  }
  const kennung = d.kennungen[0] || erf.dt.naechste;
  const bekannt = erf.stand?.platten.find((p) => p.platte_id === kennung);
  const andere = (erf.stand?.platten || []).filter((p) => p.platte_id !== kennung && !p.deaktiviert_am);
  if (d.ordner) return ordnerFormular(d, kennung);
  if (!erf.umfang || erf.umfang.wurzel !== d.mountpunkt) umfangZuruecksetzen(d.mountpunkt);
  $("#angaben").innerHTML = `
    <div class="titel-gross">${esc(d.name)}</div>
    <div class="leise mono">${esc(d.mountpunkt)}</div>
    ${anderswoHinweis(d)}
    ${d.schreibgeschuetzt ? "" : beschreibbarHinweis()}
    <div class="felder">
      <label><span>Kennung${PFLICHT}</span>
        <input id="f-kennung" value="${esc(kennung)}" maxlength="20" autocomplete="off">
        <span class="leise" id="f-kennung-info"></span></label>
      <label>Etikett (so abschreiben, wie es dasteht)
        <textarea id="f-etikett" rows="4">${esc(bekannt?.etikett_text || "")}</textarea></label>
      <label>Foto des Etiketts ${bekannt?.etikett_foto ? `<span class="leise">(vorhanden: ${esc(bekannt.etikett_foto)})</span>` : "(optional)"}
        <input id="f-foto" type="file" accept="image/*"></label>
      <label>Notiz (Herkunft, Zustand)
        <input id="f-notiz" value="${esc(bekannt?.notiz || "")}"></label>
      <label>Kopie von (Backup oder Klon eines anderen Datenträgers, nach dem Vergleich)
        <select id="f-kopie"><option value="">–</option>${andere.map((p) =>
          `<option ${bekannt?.kopie_von === p.platte_id ? "selected" : ""}>${esc(p.platte_id)}</option>`).join("")}</select></label>
    </div>
    <div class="ueberschrift">Umfang</div>
    ${umfangHtml(false)}
    <div class="ueberschrift">Ablauf</div>
    <div class="leise option-info">Virenscan mit ClamAV: ${erf.stand?.virenscan === false ? "im Projekt ausgeschaltet"
      : "an (Einstellung des Projekts); jeder Inhalt einmal, Funde werden nur markiert"}</div>
    <label class="option"><input type="checkbox" id="f-uuid"><span>Gleiche UUID oder gleiche Merkmale sind gewollt
      <span class="leise">nur bei einem Klon oder einem zweiten Exemplar derselben CD; in der Notiz vermerken</span></span></label>
    <div class="knopfzeile"><button id="erfassen" type="button" class="haupt">Registrieren und analysieren</button></div>
    <div class="leise tipp" id="erfassen-sperre" hidden></div>
    <div class="leise tipp">Liest jede Datei einmal ganz (an USB 3 etwa 15–20 Minuten je 100 GB, dazu Virenscan und Vorschaubilder).
      Der Lauf geht weiter, wenn dieses Fenster geschlossen wird; abbrechen und fortsetzen geht jederzeit.
      ${erf.dt.arbeitsplatte_da ? "" : `<br><span class="warnung-text">Datenträger für Vorschaubilder ${esc(erf.dt.arbeitsplatte)} nicht angeschlossen:
      Vorschaubilder (F) entfallen und lassen sich später nachholen.</span>`}</div>`;
  kennungPruefen();
}

// Platte schon in einem anderen Projekt registriert (Feedback 05.11.2026): Warnung, kein Verbot (ein zweites
// Projekt kann dieselbe Platte bewusst noch einmal brauchen)
function anderswoText(d) {
  return (d.andere_projekte || []).map((x) => `${x.projekt} als ${x.platte_id}`
    + `${x.registriert_am ? ", registriert am " + x.registriert_am.slice(0, 10).split("-").reverse().join(".") : ""}`
    + `${x.analysiert ? `, ${zahl(x.analysiert)} Dateien analysiert` : ", noch nicht analysiert"}`).join("; ");
}
function anderswoHinweis(d) {
  return (d.andere_projekte || []).length ? `<div class="hinweis warnung"><b>Dieser Datenträger ist schon in einem anderen Projekt registriert:</b>
    ${esc(anderswoText(d))}. Bitte prüfen, ob er hier wirklich noch einmal erfasst werden soll (z. B. wenn die Projekte
    getrennt bleiben müssen); sonst dort weiterarbeiten.</div>` : "";
}

// Formular für einen Ordner als Quelle (Fall 2): Kennung, Herkunft als Pflichtfeld statt Etikett, Notiz
function ordnerFormular(d, kennung) {
  const andere = (erf.stand?.platten || []).filter((p) => !p.deaktiviert_am);
  const vs = d.volumes || [];
  const hinweis = d.macplatte
    ? `Mac-Datenträger (${esc(vs.map((v) => `${v.name}, ${v.dateisystem}`).join("; "))}): ${esc(systemwort("system"))} bindet ihn nicht ein;
      Balduin liest ihn selbst und schreibt nie darauf. Für jede Analyse und jedes Packen gilt: ${esc(systemwort("adminfrage"))}.
      Empfohlen: über einen Writeblocker anschließen. ${esc(systemwort("formatierwarnung"))}`
      + (vs.some((v) => v.gesperrt) ? ` ${VERSCHLUESSELT_HINWEIS}` : "")
    : d.abbild
    ? `Abbild eines Mac-Datenträgers (${esc(vs.map((v) => `${v.name}, ${v.dateisystem}`).join("; "))}): Balduin liest es
      selbst, ohne es einzubinden, und schreibt nie hinein. Es durchläuft dieselbe Analyse wie ein Datenträger; Dateien darin
      zeigt Balduin in seiner Vorschau, nicht im Dateimanager. Bitte das Abbild bis zum Export nicht ändern; verschoben findet
      Balduin es über „Neuen Ort wählen …“ wieder.`
      + (vs.some((v) => v.gesperrt) ? ` ${VERSCHLUESSELT_HINWEIS}` : "")
    : `Ordner als Quelle: Er durchläuft dieselbe Analyse wie ein Datenträger und wird nur gelesen.
      Anders als ein Datenträger lässt er sich nicht schreibgeschützt öffnen; Balduin zeigt seine Dateien deshalb nicht im ${systemwort("dateimanager")}.
      Bitte während der Analyse und bis zum Export nichts darin ändern (beim Packen prüft Balduin jede Prüfsumme).`;
  const gewaehlt = vs.find((v) => v.uuid === erf.volume) || vs[0];
  const wahl = d.abbild && vs.length > 1 ? `<label>${d.macplatte ? "Teil des Datenträgers" : "Teil des Abbilds"} (enthält mehrere Datenträger)
        <select id="f-volume">${vs.map((v) => `<option value="${esc(v.uuid)}"${v === gewaehlt ? " selected" : ""}>${esc(v.name)}
          · ${esc(v.dateisystem)}${v.gesperrt ? " · verschlüsselt" : ""}</option>`).join("")}</select></label>` : "";
  // verschlüsselt (13.11.2026): Passwort nur für diesen Lauf, nie gespeichert
  // „Prüfen“ öffnet das Volume zur Probe, damit ein falsches Passwort vor dem Lauf auffällt (Feedback 14.11.2026)
  const passwort = gewaehlt?.gesperrt ? `<label><span>Passwort von „${esc(gewaehlt.name)}“${PFLICHT}</span>
        <span class="feld-mit-knopf"><input id="f-passwort" type="password" autocomplete="off" spellcheck="false">
          <button type="button" id="f-passwort-pruefen" class="knopf-leise">Prüfen</button></span>
        <span class="leise" id="f-passwort-info">Wird nicht gespeichert; vor jedem weiteren Lauf fragt Balduin erneut.</span></label>` : "";
  // Umfang (nur Teile lesen) für Abbilder; bei Mac-Platten nicht: jeder Blick in den Ordnerbaum fragt nach Rechten
  const mitUmfang = d.abbild && !d.macplatte && !gewaehlt?.gesperrt;
  if (mitUmfang && (!erf.umfang || erf.umfang.wurzel !== d.mountpunkt || erf.umfang.volume !== gewaehlt?.uuid)) {
    umfangZuruecksetzen(d.mountpunkt);
    erf.umfang.volume = gewaehlt?.uuid;
  }
  $("#angaben").innerHTML = `
    <div class="titel-gross">${d.macplatte ? traegerIcon("festplatte") : d.abbild ? traegerIcon("image") : icon("folder")} ${esc(d.name)}</div>
    <div class="leise mono">${esc(d.mountpunkt)}</div>
    <div class="hinweis">${hinweis}</div>
    <div class="felder">
      <label><span>Kennung${PFLICHT}</span>
        <input id="f-kennung" value="${esc(kennung)}" maxlength="20" autocomplete="off">
        <span class="leise" id="f-kennung-info"></span></label>
      ${wahl}
      ${passwort}
      <label>${d.macplatte ? "Etikett (so abschreiben, wie es dasteht)" : `<span>Herkunft${PFLICHT}</span>`}
        <textarea id="f-etikett" rows="4"></textarea>
        ${d.macplatte ? "" : `<span class="leise">${d.abbild
          ? "Etikett des Datenträgers, von wem, wer hat das Abbild wann womit erstellt; steht in der Bestandsgeschichte."
          : "Woher, von wem, seit wann; steht an Stelle des Etiketts in der Bestandsgeschichte."}</span>`}</label>
      <label>Notiz (Zustand, Besonderheiten)
        <input id="f-notiz" value=""></label>
      <label>Kopie von (Backup einer registrierten Quelle, nach dem Vergleich)
        <select id="f-kopie"><option value="">–</option>${andere.map((p) => `<option>${esc(p.platte_id)}</option>`).join("")}</select></label>
    </div>
    ${mitUmfang ? `<div class="ueberschrift">Umfang</div>${umfangHtml(false)}` : ""}
    <div class="knopfzeile"><button id="erfassen" type="button" class="haupt">Registrieren und analysieren</button>
      <button id="quelle-weg" type="button">Abbrechen</button></div>
    <div class="leise tipp" id="erfassen-sperre" hidden></div>`;
  kennungPruefen();
}

// Formular neu zeichnen (z. B. Ordnerbaum des Umfangs aufgeklappt), ohne Eingaben und Bildlauf zu verlieren
function angabenZeichnenBehalten() {
  const felder = ["#f-kennung", "#f-etikett", "#f-notiz", "#f-kopie", "#f-volume"].map((s) => [s, $(s)?.value]);
  const haken = ["#f-uuid"].map((s) => [s, $(s)?.checked]);
  const oben = $("#angaben").scrollTop;
  angabenZeichnen();
  for (const [s, v] of felder) if (v != null && $(s)) $(s).value = v;
  for (const [s, v] of haken) if (v != null && $(s)) $(s).checked = v;
  $("#angaben").scrollTop = oben;
  kennungPruefen();
}

function angabenGueltig() {
  const d = gewaehlterDt();
  const k = $("#f-kennung")?.value.trim() || "";
  const raus = erf.stand?.platten.some((p) => p.platte_id === k && p.deaktiviert_am);
  if (!d || raus || !/^[A-Za-z0-9_-]{1,20}$/.test(k)) return false;
  if (d.ordner) return d.macplatte || !!$("#f-etikett")?.value.trim();
  if (erf.umfang?.modus === "teil" && !erf.umfang.gewaehlt.size) return false;
  return true;                             // beschreibbar: Rückfrage beim Start (13.11.2026)
}

function kennungPruefen() {
  const d = gewaehlterDt();
  const k = $("#f-kennung").value.trim();
  const bekannt = erf.stand?.platten.find((p) => p.platte_id === k);
  let info = bekannt ? `bekannt: ${esc(bekannt.volume_name || "")}, ${zahl(bekannt.dateien)} Dateien; fehlende Schritte werden nachgeholt`
                     : `neu (nächste freie Kennung: ${esc(erf.dt.naechste)})`;
  if (bekannt && (d.ordner || !d.kennungen.includes(k))) info = `<span class="warnung-text">${esc(k)} gehört zu einem anderen Datenträger (${esc(bekannt.volume_name || "")}).</span>`;
  else if (bekannt?.deaktiviert_am) info = `<span class="warnung-text">${esc(k)} ist aus dem Projekt genommen. Erst links unter
    „Aus dem Projekt genommen“ wieder aufnehmen.</span>`;
  $("#f-kennung-info").innerHTML = info;
  erfassenKnopf();
}

function erfassenKnopf() {
  if (!$("#erfassen")) return;
  const belegt = belegtText($("#f-kennung")?.value.trim());
  $("#erfassen").disabled = !!belegt || !angabenGueltig();
  $("#erfassen").textContent = einreihen() && !belegt ? "Registrieren und einreihen" : "Registrieren und analysieren";
  $("#erfassen-sperre").hidden = !belegt && !einreihen();
  $("#erfassen-sperre").textContent = belegt || (einreihen() ? einreihenText() : "");
}

// Passwort im Formular zur Probe prüfen; Antwort true, wenn es stimmt (Ergebnis steht unter dem Feld)
async function formPasswortPruefen() {
  const d = gewaehlterDt(), info = $("#f-passwort-info"), pw = $("#f-passwort").value;
  if (!pw) {
    info.innerHTML = `<span class="warnung-text">Bitte das Passwort eingeben.</span>`;
    return false;
  }
  info.textContent = "Wird geprüft …";
  try {
    const r = await senden("/api/passwort_pruefen", { platte_id: $("#f-kennung").value.trim(), mountpunkt: d.mountpunkt,
      art: d.macplatte ? "macplatte" : d.abbild ? "abbild" : undefined, volume_uuid: $("#f-volume")?.value, passwort: pw });
    info.innerHTML = r.ok ? `<span class="gut-text">${icon("check")} ${esc(r.meldung)}</span>`
                          : `<span class="warnung-text">${esc(r.meldung)}</span>`;
    return r.ok;
  } catch (err) {
    info.innerHTML = `<span class="warnung-text">${esc(err.message)}</span>`;
    return false;
  }
}

$("#angaben").addEventListener("input", (e) => {
  if (e.target.id === "f-passwort") $("#f-passwort-info").textContent = "Wird nicht gespeichert; vor jedem weiteren Lauf fragt Balduin erneut.";
  if (e.target.id === "f-kennung" || (e.target.id === "f-etikett" && gewaehlterDt()?.ordner)) kennungPruefen();
});
$("#angaben").addEventListener("change", (e) => {
  if (e.target.name === "umfang-modus") {
    erf.umfang.modus = e.target.value;
    return erf.platte ? angabenZeichnen() : angabenZeichnenBehalten();
  }
  if (e.target.id === "f-volume") {                    // anderes Volume: Passwortfeld und Ordnerbaum neu
    erf.volume = e.target.value;
    return angabenZeichnenBehalten();
  }
  if (e.target.dataset.umfang != null) {
    const pfad = e.target.dataset.umfang, u = erf.umfang;
    if (e.target.checked) {
      for (const g of [...u.gewaehlt]) if (g.startsWith(pfad + "/") && !u.fest.has(g)) u.gewaehlt.delete(g);   // Ordner darüber genügt
      u.gewaehlt.add(pfad);
    } else u.gewaehlt.delete(pfad);
    return erf.platte ? angabenZeichnen() : (angabenZeichnenBehalten(), kennungPruefen());
  }
  if (e.target.id === "f-foto") {
    const datei = e.target.files[0];
    erf.foto = null;
    if (!datei) return;
    const leser = new FileReader();
    leser.onload = () => (erf.foto = { name: datei.name, daten: leser.result });
    leser.readAsDataURL(datei);
  }
});
$("#angaben").addEventListener("click", async (e) => {
  if (e.target.closest("#f-passwort-pruefen")) {
    const knopf = e.target.closest("#f-passwort-pruefen");
    knopf.disabled = true;
    await formPasswortPruefen();
    knopf.disabled = false;
    return;
  }
  const auf = e.target.closest("[data-umfang-auf]");
  if (auf) {
    const u = erf.umfang, pfad = auf.dataset.umfangAuf;
    if (u.offen.has(pfad)) u.offen.delete(pfad); else u.offen.add(pfad);
    return erf.platte ? angabenZeichnen() : angabenZeichnenBehalten();
  }
  if (e.target.closest("#quelle-weg")) {
    erf.quelle = null;
    erf.gewaehlt = null;
    datentraegerZeichnen();
    return angabenZeichnen();
  }
  if (e.target.closest("#umfang-auf")) { erf.umfangOffen = true; erf.umfang = null; return angabenZeichnen(); }
  if (e.target.closest("#umfang-zu")) { erf.umfangOffen = false; erf.umfang = null; return angabenZeichnen(); }
  const erweitern = e.target.closest("#umfang-erweitern, #umfang-ganz");
  if (erweitern) {
    const dt = angeschlossenAls(erf.platte);
    const neu = erweitern.id === "umfang-ganz" ? [] : umfangListe();
    if (!(await rueckfrage(`${erf.platte}: ${neu.length ? "Umfang erweitern auf " + neu.join(", ") : "künftig den ganzen Datenträger lesen"}?`,
      "Danach wird das Inhaltsverzeichnis neu gelesen und alles Offene fortgesetzt. Verkleinern lässt sich der Umfang nicht mehr."
      + einreihenFrage(), neu.length ? "Umfang erweitern" : "Ganzen Datenträger lesen"))) return;
    if (!(await ohneSchutzKlaeren(dt, erf.platte))) return;
    const passwort = await passwortFuer(erf.platte, true);
    if (passwort === null) return;
    erweitern.disabled = true;
    try {
      await senden("/api/platte_lauf", { platte_id: erf.platte, mountpunkt: dt.mountpunkt, modus: "fortsetzen",
                                         beschreibbar_ok: !dt.schreibgeschuetzt, umfang: neu, passwort });
      erf.umfangOffen = false;
      erf.umfang = null;
    } catch (err) { meldung(err.message, "Fehler"); erweitern.disabled = false; }
    await standErfassung();
    return angabenZeichnen();
  }
  if (e.target.closest("#abbild-verlegen")) {            // verschobenes Abbild (13.11.2026)
    try {
      const r = await senden("/api/abbild_waehlen", {});
      if (r.abgebrochen) return;
      const v = await senden("/api/quellordner_verlegen", { platte_id: erf.platte, pfad: r.pfad });
      meldung(`${erf.platte} liegt jetzt unter ${v.pfad}`
        + (v.geprueft ? ` (Volume-UUID und Stichprobe von ${v.geprueft} Dateien stimmen).` : " (Volume-UUID stimmt)."),
        "Neuer Ort übernommen");
    } catch (err) { meldung(err.message, "Fehler"); }
    await datentraegerLaden();
    await standErfassung();
    return angabenZeichnen();
  }
  if (e.target.closest("#ordner-verlegen")) {
    try {
      const r = await senden("/api/ordner_waehlen", { zweck: "quelle" });
      if (r.abgebrochen) return;
      const v = await senden("/api/quellordner_verlegen", { platte_id: erf.platte, pfad: r.pfad });
      meldung(`${erf.platte} liegt jetzt unter ${v.pfad} (Stichprobe von ${v.geprueft} Dateien stimmt).`, "Neuer Ort übernommen");
    } catch (err) { meldung(err.message, "Fehler"); }
    await datentraegerLaden();
    await standErfassung();
    return angabenZeichnen();
  }
  const chip = e.target.closest("[data-chip]");
  if (chip) {
    const k = chip.dataset.chip;
    if (erf.auswahl.has(k)) erf.auswahl.delete(k); else erf.auswahl.add(k);
    return angabenZeichnen();
  }
  const mit = e.target.closest("[data-mit]");
  if (mit) {
    mit.dataset.mit.split(",").forEach((k) => erf.auswahl.add(k));
    return angabenZeichnen();
  }
  if (e.target.id === "auswahl-leeren") {
    erf.auswahl.clear();
    return angabenZeichnen();
  }
  if (e.target.closest("#herausnehmen")) {
    return herausnehmenFragen(erf.stand.platten.find((x) => x.platte_id === erf.platte));
  }
  if (e.target.closest("#wieder-aufnehmen")) {
    const knopf = e.target.closest("#wieder-aufnehmen");
    knopf.disabled = true;
    try {
      await senden("/api/platte_herausnehmen", { platte_id: erf.platte, herausnehmen: false });
    } catch (err) { meldung(err.message, "Fehler"); knopf.disabled = false; return; }
    return nachHerausnehmen();
  }
  const lauf = e.target.closest("[data-platte-lauf]");
  if (lauf) {
    const modus = lauf.dataset.platteLauf, dt = angeschlossenAls(erf.platte);
    const mitPlatte = !!dt;
    const namen = auswahlMitFolgen().map((s) => s.name);
    // Platzbedarf der Vorschaubilder, wenn der Lauf sie erzeugt (Entscheidung 12.11.2026)
    const pl = erf.stand.platten.find((p) => p.platte_id === erf.platte)?.platz;
    const platz = pl?.text && mitPlatte && (modus !== "auswahl" || auswahlMitFolgen().some((s) => s.k === "F")) ? `\n\n${pl.text}` : "";
    const [frage, erklaerung, ja] = modus === "auswahl"
      ? [`${erf.platte}: ${namen.join(", ")} ausführen?`, "Jeder Schritt macht nur, was noch fehlt.", "Ausführen"]
      : modus === "neu"
      ? [`${erf.platte} neu analysieren?`, "Prüfsummen, Formate, Metadaten und Virenscan dieses Datenträgers werden verworfen "
        + "und neu bestimmt; dafür wird der ganze Datenträger noch einmal gelesen. Entscheidungen und Angaben bleiben.", "Neu analysieren"]
      : [`${erf.platte} fortsetzen?`, "Abgebrochene Schritte gehen weiter, Ausstehendes wird nachgeholt."
        + (mitPlatte ? "" : "\n\nDer Datenträger ist nicht angeschlossen: Es laufen nur Dubletten, Anton-Abgleich und Archivfähigkeit."),
        "Fortsetzen"];
    if ((modus === "neu" && !mitPlatte) || (modus === "auswahl" && auswahlMitFolgen().some((s) => s.platte) && !mitPlatte)
        || !(await rueckfrage(frage, erklaerung + platz + einreihenFrage(), ja))) return;
    if (mitPlatte && !(await ohneSchutzKlaeren(dt, erf.platte))) return;
    if ((modus !== "auswahl" || auswahlMitFolgen().some((s) => s.k === "G5")) && !(await antonVorab())) return;
    const passwort = await passwortFuer(erf.platte, mitPlatte);
    if (passwort === null) return;
    lauf.disabled = true;
    try {
      await senden("/api/platte_lauf", { platte_id: erf.platte, mountpunkt: mitPlatte ? dt.mountpunkt : null,
                                         modus: modus === "auswahl" ? "fortsetzen" : modus, beschreibbar_ok: mitPlatte && !dt.schreibgeschuetzt,
                                         schritte: modus === "auswahl" ? [...erf.auswahl] : undefined, passwort });
      if (modus === "auswahl") erf.auswahl.clear();
    } catch (err) { meldung(err.message, "Fehler"); }
    await standErfassung();
    return angabenZeichnen();
  }
  if (e.target.id === "speichern") {
    e.target.disabled = true;
    try {
      const r = await senden("/api/platte_angaben", { platte_id: erf.platte, etikett: $("#f-etikett").value,
        notiz: $("#f-notiz").value, kopie_von: $("#f-kopie").value, foto_daten: erf.foto });
      erf.foto = null;
      await standErfassung();
      angabenZeichnen();
      $("#gespeichert").textContent = r.geaendert.length ? "Gespeichert." : "Keine Änderung.";
    } catch (err) { meldung(err.message, "Fehler"); e.target.disabled = false; }
    return;
  }
  if (e.target.id !== "erfassen") return;
  const d = gewaehlterDt();
  const auftrag = {
    platte_id: $("#f-kennung").value.trim(), mountpunkt: d.mountpunkt, etikett: $("#f-etikett").value,
    notiz: $("#f-notiz").value, kopie_von: $("#f-kopie").value, foto_daten: erf.foto,
    gleiche_uuid_ok: !!$("#f-uuid")?.checked,
    beschreibbar_ok: !d.ordner && !d.schreibgeschuetzt,
  };
  if (d.ordner) auftrag.art = d.macplatte ? "macplatte" : d.abbild ? "abbild" : "ordner";
  if (erf.umfang?.modus === "teil" && (!d.ordner || (d.abbild && !d.macplatte))) auftrag.umfang = umfangListe();
  if (d.abbild && $("#f-volume")) auftrag.volume_uuid = $("#f-volume").value;
  if ($("#f-passwort")) {                              // verschlüsselt: nur mit geprüftem Passwort starten
    if (!(await formPasswortPruefen())) return $("#f-passwort").focus();
    auftrag.passwort = $("#f-passwort").value;
  }
  const was = d.macplatte ? `Der Datenträger wird nur gelesen (${systemwort("adminfrage")}).`
    : d.abbild ? "Das Abbild wird nur gelesen." : d.ordner ? "Der Ordner wird nur gelesen."
    : auftrag.umfang ? `Gelesen wird nur ${auftrag.umfang.join(", ")}; der Datenträger wird nur gelesen.` : "Der Datenträger wird nur gelesen.";
  const anderswo = (d.andere_projekte || []).length ? `\n\nAchtung: schon registriert in ${anderswoText(d)}.` : "";
  const platz = erf.stand.platz_neu?.text ? `\n\n${erf.stand.platz_neu.text}` : "";
  if (!(await rueckfrage(`${auftrag.platte_id} unter ${d.mountpunkt} registrieren und analysieren?`,
    `${was}${anderswo}${platz}${einreihenFrage()}`, "Registrieren und analysieren"))) return;
  if (!d.ordner && !(await ohneSchutzKlaeren(d, auftrag.platte_id))) return;
  if (!(await antonVorab())) return;
  e.target.disabled = true;
  try {
    await senden("/api/erfassen", auftrag);
    if ($("#f-passwort")) $("#f-passwort").value = "";   // nicht im Formular stehen lassen
    erf.foto = null;
    if ($("#f-foto")) $("#f-foto").value = "";
    if (d.ordner) {                                     // registriert: erscheint jetzt unter den registrierten Quellen
      erf.quelle = null;
      erf.gewaehlt = null;
      erf.platte = auftrag.platte_id;
      await datentraegerLaden();
    }
  } catch (err) { meldung(err.message, "Fehler"); }
  standErfassung();
});

// ---------- Fortschritt: oben alle Läufe (laufend, eingereiht, zuletzt beendet), darunter der gewählte im Einzelnen ----------
function laufZeichnen() {
  if (erf.zeigerUnten) return;                         // gleich kommt ein Klick; die nächste Abfrage zeichnet nach
  const l = erf.stand.lauf;
  // Rückfrage verfällt, wenn ihr Lauf nicht mehr läuft bzw. nicht mehr eingereiht ist
  if (erf.frage && !(erf.frage.art === "abbrechen" ? laufende().some((x) => x.lauf_id === erf.frage.lauf_id)
    : erf.stand.warteschlange.some((w) => w.lauf_id === erf.frage.lauf_id))) erf.frage = null;
  const uebersicht = laeufeHtml(l?.lauf_id);
  if (!l) {
    const platte = gewaehltePlatte();
    const eingereiht = erf.stand.warteschlange.some((w) => w.platte_id === platte);
    $("#lauf-kopf").textContent = "";
    $("#lauf").innerHTML = uebersicht + (platte && !eingereiht
      ? `<div class="leer-hinweis">Für ${esc(platte)} wurde noch keine Analyse gestartet.</div>` : "");
    return;
  }
  const offenDetails = $("#lauf details")?.open;
  $("#lauf-kopf").textContent = `Lauf ${l.lauf_id} · gestartet ${zeit(l.start)}`;
  const schritte = l.schritte.length ? l.schritte.map((s) => {
    const laeuft = s.status === "läuft";
    const anteil = laeuft && s.anteil != null ? s.anteil : null;
    return `<li class="schritt-zeile st-${STATUS_KLASSE[s.status] || "wartet"}">
      <span class="st-zeichen">${laeuft ? '<i class="drehen"></i>' : SCHRITT_ZEICHEN[s.status] ?? ""}</span>
      <span><b>${esc(s.titel)}</b>
        ${s.text && s.status !== "wartet" ? `<span class="st-text">${esc(s.text)}</span>`
          : laeuft ? `<span class="st-text">wird vorbereitet …</span>` : ""}
        ${anteil != null ? `<span class="st-spur"><i style="width:${(100 * anteil).toFixed(1)}%"></i></span>`
          : laeuft ? `<span class="st-spur unbestimmt"><i></i></span>` : ""}</span>
      <span class="leise">${s.status === "wartet" ? "wartet" : laeuft ? dauer(s.start) : s.status === "fertig" ? dauer(s.start, s.ende) : esc(s.status)}</span></li>`;
  }).join("") : `<li class="leise">Der Lauf startet …</li>`;
  const ab = wirdAbgebrochen(l);
  const status = l.aktiv ? (ab ? "wird abgebrochen …" : "läuft") : l.status;
  // Fortsetzen nur für den letzten Lauf seiner Platte; ein älterer wäre längst überholt
  const juengster = !erf.stand.laeufe.some((x) => x.lauf_id > l.lauf_id && x.platte_id === l.platte_id && x.art === l.art);
  $("#lauf").innerHTML = uebersicht + `
    <div class="lauf-einzeln">
    <div class="lauf-titel"><span class="titel-gross">${esc(l.name)}</span>
      <span class="pille ${l.status === "fertig" ? "gut" : l.aktiv ? "" : "warnung"}">${esc(status)}</span></div>
    <div class="leise mono">${esc(l.auftrag.mountpunkt || "")}</div>
    ${l.meldung && !l.aktiv ? `<div class="hinweis ${l.status === "fertig" ? "" : "warnung"}">${esc(l.meldung)}</div>` : ""}
    ${l.aktiv ? "" : uebersprungenHtml(l)}
    <ul class="schritt-liste">${schritte}</ul>
    <div class="knopfzeile">
      ${l.aktiv ? (erf.frage?.art === "abbrechen" && erf.frage.lauf_id === l.lauf_id ? rueckfrageHtml(
        `Analyse von ${esc(l.name)} abbrechen? Was erledigt ist, bleibt gespeichert; „Fortsetzen“ macht mit dem Rest weiter.`
        + (erf.stand.warteschlange.length ? ` Danach startet der nächste eingereihte Lauf.` : ""), "Ja, abbrechen")
        : `<button type="button" data-frage="abbrechen" data-lauf="${l.lauf_id}" ${ab ? "disabled" : ""}>${ab ? "Wird abgebrochen …" : "Abbrechen"}</button>`) : ""}
      ${!l.aktiv && l.status !== "fertig" && juengster ? `<button type="button" id="fortsetzen" class="haupt">Fortsetzen</button>` : ""}
      ${!l.aktiv && l.status === "fertig" ? `<button type="button" id="zur-bewertung" class="haupt">Zur Bewertung</button>` : ""}
    </div>
    ${l.aktiv ? `<div class="leise tipp">Der Lauf geht weiter, wenn dieses Fenster oder der Browser geschlossen wird.</div>` : ""}
    <details ${offenDetails ? "open" : ""}><summary>Meldungen</summary>
      <pre class="log">${esc(l.log_ende || "")}</pre><div class="leise mono">${esc(l.log || "")}</div></details>
    </div>`;
}

// Abbrechen verlangt (Marke im Server oder eben geklickt); der Lauf hört erst an seiner nächsten Prüfstelle auf
const wirdAbgebrochen = (l) => !!l.abbrechen || erf.vorgemerkt[l.lauf_id] === "abbrechen";

// Rückfrage direkt in der Spalte statt eines Dialogs: bleibt beim Neuzeichnen stehen und geht auch, wenn der Browser Dialoge unterdrückt
const rueckfrageHtml = (text, ja) => `<div class="lauf-frage"><span>${text}</span>
  <button type="button" class="haupt" data-ja>${ja}</button><button type="button" data-nein>Nein</button></div>`;

// Was ein eingereihter Lauf tun wird
const warteWas = (w) => (w.art === "anton" ? w.modus : w.schritte ? w.schritte.map((k) => SCHRITT[k]?.name || k).join(", ")
  : { neu: "neu analysieren", fortsetzen: "alles Offene fortsetzen" }[w.modus] || w.modus);

// Eine Zeile je Lauf: der laufende mit Schritt und Balken, eingereihte in ihrer Reihenfolge, beendete mit Ergebnis.
// Klick zeigt den Lauf darunter im Einzelnen; eingereihte haben noch keine Einzelheiten, nur „Entfernen“.
function laeufeHtml(gezeigt) {
  const aktiv = erf.stand.laeufe.filter((l) => l.aktiv), beendet = erf.stand.laeufe.filter((l) => !l.aktiv);
  const warte = erf.stand.warteschlange;
  if (!aktiv.length && !warte.length && !beendet.length) return "";
  const zeile = (l) => {
    const s = l.schritt, name = s ? s.titel || SCHRITT[s.schritt]?.name || s.schritt : "";
    const st = l.aktiv ? "laeuft" : STATUS_KLASSE[l.status] || "wartet";
    const rechts = l.aktiv ? (wirdAbgebrochen(l) ? "wird abgebrochen …" : dauer(l.start))
      : `${esc(l.status)} · ${zeit(l.ende || l.start)}`;
    const text = l.aktiv ? (s?.text ? `${esc(name)} · ${esc(s.text)}` : esc(name || "startet …"))
      : l.status === "fertig" ? esc(name ? `bis ${name}` : "") : esc(l.meldung || name);
    return `<li class="lauf-zeile st-${st}${l.lauf_id === gezeigt ? " gewaehlt" : ""}" data-lauf-wahl="${l.lauf_id}">
      <span class="st-zeichen">${l.aktiv ? '<i class="drehen"></i>' : SCHRITT_ZEICHEN[l.status] ?? ""}</span>
      <span><b>${esc(l.name)}</b> <span class="st-text">${text}</span>
        ${l.aktiv ? (s?.anteil != null ? `<span class="st-spur"><i style="width:${(100 * s.anteil).toFixed(1)}%"></i></span>`
          : `<span class="st-spur unbestimmt"><i></i></span>`) : ""}</span>
      <span class="leise">${rechts}</span></li>`;
  };
  const wartezeile = (w, i) => erf.vorgemerkt[w.lauf_id] === "entfernen"
    ? `<li class="lauf-zeile st-wartet weg"><span class="st-zeichen leise">${i + 1}</span>
        <span><b>${esc(w.name)}</b> <span class="st-text">wird entfernt …</span></span><span></span></li>`
    : `<li class="lauf-zeile st-wartet">
      <span class="st-zeichen leise">${i + 1}</span>
      <span><b>${esc(w.name)}</b> <span class="st-text">${esc(warteWas(w))} · eingereiht ${esc(zeit(w.eingereiht))}</span>
        ${w.mountpunkt ? `<span class="leise mono">${esc(w.mountpunkt)}</span>` : ""}</span>
      ${erf.frage?.art === "entfernen" && erf.frage.lauf_id === w.lauf_id ? ""
        : `<button type="button" class="knopf-leise" data-frage="entfernen" data-lauf="${w.lauf_id}">Entfernen</button>`}
      ${erf.frage?.art === "entfernen" && erf.frage.lauf_id === w.lauf_id
        ? `<span class="lauf-frage-zeile">${rueckfrageHtml(`Lauf für ${esc(w.name)} entfernen? Er startet dann nicht.`, "Ja, entfernen")}</span>` : ""}</li>`;
  return `<ul class="lauf-liste">
      ${aktiv.length ? `<li class="lauf-gruppe">Läuft</li>${aktiv.map(zeile).join("")}` : ""}
      ${warte.length ? `<li class="lauf-gruppe">Eingereiht (${warte.length})</li>${warte.map(wartezeile).join("")}` : ""}
      ${beendet.length ? `<li class="lauf-gruppe">Zuletzt beendet</li>${beendet.map(zeile).join("")}` : ""}
    </ul>
    ${warte.length ? `<div class="leise tipp">Eingereihte starten von selbst nacheinander, auch wenn der laufende abbricht. Ihre Datenträger
      müssen bis dahin angeschlossen bleiben; fehlt einer, endet sein Lauf mit einem Fehler und der nächste beginnt.</div>` : ""}
    ${erf.laufWahl ? `<button type="button" class="knopf-leise" id="lauf-aktuell">Zurück zum aktuellen Lauf</button>` : ""}`;
}

// Nach dem Lauf: Schritte, die mit Begründung übersprungen wurden (nicht die abgewählten), damit sie nicht untergehen
function uebersprungenHtml(l) {
  const liste = l.schritte.filter((s) => s.status === "übersprungen" && s.text && s.text !== "nicht gewählt");
  if (!liste.length) return "";
  return `<div class="hinweis warnung"><b>Übersprungen:</b> ${liste.map((s) => `${esc(s.titel)} (${esc(s.text)})`).join("; ")}</div>`;
}

$("#lauf").addEventListener("click", async (e) => {
  const l = erf.stand?.lauf;
  const wahl = e.target.closest("[data-lauf-wahl]");
  if (wahl || e.target.id === "lauf-aktuell") {
    erf.laufWahl = wahl ? Number(wahl.dataset.laufWahl) : null;
    if (wahl && erf.stand?.lauf?.aktiv && erf.stand.lauf.lauf_id === erf.laufWahl) erf.laufWahl = null;   // ohnehin die Vorgabe
    return standErfassung();
  }
  const frage = e.target.closest("[data-frage]");
  if (frage) {                                           // erster Klick: Rückfrage zeigen
    erf.frage = { art: frage.dataset.frage, lauf_id: Number(frage.dataset.lauf) };
    return laufZeichnen();
  }
  if (e.target.closest("[data-nein]")) { erf.frage = null; return laufZeichnen(); }
  if (e.target.closest("[data-ja]") && erf.frage) {      // bestätigt: ausführen
    const { art, lauf_id } = erf.frage;
    erf.frage = null;
    erf.vorgemerkt[lauf_id] = art;                       // sofort zeigen, nicht erst nach der Antwort
    erf.abfrageNr++;                                     // Abfragen von vor dem Klick verwerfen
    laufZeichnen();
    try { await senden(art === "abbrechen" ? "/api/abbrechen" : "/api/entfernen", { lauf_id }); }
    catch (err) { delete erf.vorgemerkt[lauf_id]; meldung(err.message, "Fehler"); }
    await standErfassung();
    return art === "entfernen" ? angabenZeichnen() : undefined;
  }
  if (!l) return;
  try {
    if (e.target.id === "fortsetzen") {
      const passwort = await passwortFuer(l.platte_id, true);      // verschlüsselt: Passwort nur für diesen Lauf
      if (passwort === null) return;
      e.target.disabled = true;
      await senden("/api/fortsetzen", { lauf_id: l.lauf_id, passwort });
    } else if (e.target.id === "zur-bewertung") {
      return ansichtZeigen("bewertung");
    } else return;
  } catch (err) { meldung(err.message, "Fehler"); }
  standErfassung();
});

// Solange die Maustaste in „Läufe“ gedrückt ist, nicht neu zeichnen (pointerup kommt vor click, also rechtzeitig zurück)
$("#lauf").addEventListener("pointerdown", () => { erf.zeigerUnten = true; });
document.addEventListener("pointerup", () => { erf.zeigerUnten = false; }, true);
document.addEventListener("pointercancel", () => { erf.zeigerUnten = false; }, true);

// ---------- Start (projekt.js ruft das auf, sobald ein Projekt offen ist) ----------
function erfassungStarten() {
  const gemerkt = prj.daten?.offen?.ansicht || "erfassung";   // zuletzt genutztes Modul des Projekts, sonst Modul 1
  ansichtZeigen(gemerkt);
  if (gemerkt !== "erfassung") standErfassung();        // zeigt im Kopf, ob gerade eine Erfassung läuft
}

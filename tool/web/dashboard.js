// Dashboard und Bericht aus einer Quelle (docs/plan.md, Entscheidung 29.10.2026).
// Dash.rendern(daten, wurzel) zeichnet alle Reiter; dieselbe Datei läuft im Tool (live, über jeder Ansicht
// einblendbar) und im gespeicherten Bericht (eine HTML-Datei ohne Server, Daten eingebettet). Keine Fremdbibliotheken.
// daten: analyse (erfassung/dashboard.py), bewertung (Zähler je Datenträger), erfassung (Stand je Schritt, Lauf), schritte.
"use strict";

(() => {
  // ---------- Hilfen (eigene, damit der Bericht ohne app.js auskommt) ----------
  const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (z) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[z]));
  const zahl = (n) => (n ?? 0).toLocaleString("de-CH");
  const prozent = (teil, ganz) => (ganz ? Math.round((100 * teil) / ganz) : 0) + " %";
  function bytes(n) {
    const e = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    n = n || 0;
    while (n >= 1000 && i < e.length - 1) { n /= 1000; i++; }
    return (i ? n.toFixed(n < 10 ? 1 : 0).replace(".", ",") : n) + " " + e[i];
  }
  const zeit = (iso) => (iso ? String(iso).slice(0, 16).replace("T", " ") : "");
  function ring(anteil, fertig) {
    if (fertig) return `<svg class="ring fertig" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10.5"/><path d="M7 12.5l3.2 3.2L17 9"/></svg>`;
    const u = 2 * Math.PI * 9;
    return `<svg class="ring" viewBox="0 0 24 24" aria-hidden="true"><circle class="spur" cx="12" cy="12" r="9"/>`
      + `<circle class="wert" cx="12" cy="12" r="9" stroke-dasharray="${(u * Math.min(anteil || 0, 1)).toFixed(1)} ${u.toFixed(1)}"/></svg>`;
  }

  // Farben als Rollen aus app.css; je Teil: Schlüssel, Farbe, Name
  const AMPEL = [["grün", "var(--a-gruen)", "grün"], ["gelb", "var(--a-gelb)", "gelb"], ["rot", "var(--a-rot)", "rot"],
                 ["ohne_ampel", "var(--a-ohne)", "ohne Ampel"]];
  const BEWERTUNG = [["uebernehmen", "var(--e-ueb)", "übernommen"], ["kassieren", "var(--e-kas)", "kassiert"],
                     ["zurueckgestellt", "var(--e-zur)", "zurückgestellt"], ["offen", "var(--e-offen)", "offen"]];
  const DUBLETTEN = [["stark_exakt", "var(--d-exakt)", "exakt gleich"], ["stark_variante", "var(--d-variante)", "Variante"],
                     ["stark_beinahe", "var(--d-beinahe)", "beinahe gleich"], ["einmalig", "var(--spur)", "ohne Dublette"]];
  const ANTON = [["in Anton", "var(--fokus)", "in Anton"], ["gleicher Name, andere Datei", "var(--a-gelb)", "gleicher Name, andere Datei"],
                 ["nicht in Anton", "var(--a-ohne)", "nicht in Anton"], ["nicht geprüft", "var(--spur)", "nicht geprüft"],
                 ["noch nicht abgeglichen", "var(--e-kas)", "noch nicht abgeglichen"], ["leere Datei", "var(--linie-stark)", "leere Datei"]];
  const NARA = [["Low", "var(--a-gruen)", "Low"], ["Moderate", "var(--a-gelb)", "Moderate"], ["High", "var(--a-rot)", "High"],
                ["Unknown", "var(--a-ohne)", "Unknown"]];
  const STUFEN = { "eingebettete Metadaten": "var(--e-ueb)", "Datei- oder Ordnername": "var(--d-variante)", "Dateisystem": "var(--a-ohne)" };
  const REITER = ["Überblick", "Analyse", "Bestand", "Archivfähigkeit", "Dubletten", "Anton", "Ordner", "Erschließung", "Probleme", "Datenträger und Protokoll"];
  let bestandAnsicht = "formate";                  // Reiter Bestand: „formate“ (Platten je Format) oder „platten“ (Formate je Datenträger)
  // Erschließung (Entscheidung 04.11.2026): erschlossen und zugeordnet als Anteil der übernommenen Dateien
  const ERSCHLIESSUNG = [["zugeordnet", "var(--violett)", "erschlossen und zugeordnet"], ["nur_erschlossen", "var(--a-gruen)", "erschlossen"],
                         ["offen", "var(--spur)", "noch offen"]];
  const esTeile = (z) => ({ zugeordnet: Math.min(z.zugeordnet, z.erschlossen), nur_erschlossen: Math.max(0, z.erschlossen - z.zugeordnet),
                            offen: Math.max(0, z.uebernommen - z.erschlossen) });
  const mitEinmalig = (z) => ({ ...z, einmalig: (z.dateien || 0) - (z.stark_exakt || 0) - (z.stark_variante || 0) - (z.stark_beinahe || 0) });

  // ---------- Bausteine ----------
  const karte = (titel, inhalt, breit = false, text = "") => `<section class="karte db-karte${breit ? " db-breit" : ""}">
      <div class="kartenkopf"><h2>${esc(titel)}</h2></div><div class="kartentext">${text ? `<div class="leise db-text">${esc(text)}</div>` : ""}${inhalt}</div></section>`;
  const kachel = (wert, name, zusatz, anteil, fertig) => `<div class="db-kachel">
      ${anteil != null ? `<span class="db-kachel-ring">${ring(anteil, fertig)}</span>` : ""}
      <div class="wert">${wert}</div><div class="name">${esc(name)}</div><div class="leise">${zusatz}</div></div>`;
  const legende = (teile) => `<div class="db-legende leise">${teile.map(([, farbe, name]) =>
    `<span><i class="feld" style="background:${farbe}"></i>${esc(name)}</span>`).join("")}</div>`;

  // Gestapelte Balken: zeilen = [{name, werte: {schlüssel: zahl}}]; rechts der Anteil des ersten Teils (oder rechts())
  function stapel(zeilen, teile, { einheit = (n) => zahl(n), rechts } = {}) {
    if (!zeilen.length) return `<div class="leise">Keine Daten.</div>`;
    return legende(teile) + zeilen.map((z) => {
      const ganz = teile.reduce((s, [k]) => s + (z.werte[k] || 0), 0);
      const stuecke = teile.filter(([k]) => z.werte[k] > 0).map(([k, farbe, name]) =>
        `<i style="width:${(100 * z.werte[k]) / ganz}%;background:${farbe}" title="${esc(`${z.name}: ${name} ${einheit(z.werte[k])} (${prozent(z.werte[k], ganz)})`)}"></i>`).join("");
      return `<div class="db-zeile"><span class="db-platte" title="${esc(z.name)}">${esc(z.name)}</span><span class="db-balken">${stuecke}</span>
        <span class="leise zahl">${rechts ? rechts(z, ganz) : prozent(z.werte[teile[0][0]] || 0, ganz)}</span></div>`;
    }).join("");
  }

  // Tabelle mit Suchfeld; spalten = [[schlüssel, titel, art]] mit art: "zahl", "bytes", "zeit" oder leer
  function tabelle(spalten, zeilen, { suche = zeilen.length > 15, gesamt } = {}) {
    const zelle = (wert, art) => art === "zahl" ? `<td class="zahl">${wert == null ? "" : zahl(wert)}</td>`
      : art === "bytes" ? `<td class="zahl">${wert == null ? "" : bytes(wert)}</td>`
      : art === "zeit" ? `<td class="nowrap">${esc(zeit(wert))}</td>`
      : `<td>${esc(wert ?? "").replace(/\n/g, "<br>")}</td>`;
    return `${suche ? `<input type="search" class="db-suche" placeholder="Filtern …" aria-label="Tabelle filtern">` : ""}
      <div class="db-tabelle-rahmen"><table class="db-tabelle"><thead><tr>${spalten.map(([, t, art]) =>
        `<th${art === "zahl" || art === "bytes" ? ' class="zahl"' : ""}>${esc(t)}</th>`).join("")}</tr></thead>
      <tbody>${zeilen.map((z) => `<tr>${spalten.map(([k, , art]) => zelle(z[k], art)).join("")}</tr>`).join("")}</tbody></table></div>
      ${gesamt && gesamt > zeilen.length ? `<div class="leise tipp">${zahl(zeilen.length)} von ${zahl(gesamt)} Zeilen.</div>` : ""}`;
  }

  function chips(d, p) {
    return d.schritte.map((s) => {
      const n = p.offen?.[s.k];
      const aus = s.k === "D3" && p.offen?.D3_aus;         // im Projekt ausgeschaltet: übersprungen
      const text = aus ? "übersprungen, im Projekt ausgeschaltet" : n === 0 ? "erledigt" : n == null ? (s.k === "G5" ? "kein Bestand aus Anton geladen" : "noch nicht gelaufen") : `${zahl(n)} Dateien offen`;
      return `<span class="chip${n === 0 ? " erledigt" : ""}${aus ? " uebersprungen" : ""}" title="${esc(s.name + ": " + text)}">${esc(s.name)}</span>`;
    }).join("");
  }

  // ---------- Reiter ----------
  function ueberblick(d) {
    const pl = d.bewertung.platten, summe = (k) => pl.reduce((s, p) => s + (p.zaehler[k] || 0), 0);
    const dateien = summe("dateien"), bewertet = dateien - summe("offen"), modul = d.erfassung.modul;
    const mitDup = summe("stark_exakt") + summe("stark_variante") + summe("stark_beinahe");
    const bestandKacheln = [
      kachel(zahl(pl.length), "Datenträger", esc(pl.map((p) => p.id).join(", "))),
      kachel(zahl(dateien), "Dateien", `${bytes(summe("bytes"))}, ohne Systemdateien`),
      kachel(prozent(summe("grün"), dateien), "archivfähig (grün)", `gelb ${prozent(summe("gelb"), dateien)}, rot ${prozent(summe("rot"), dateien)}`),
      kachel(prozent(mitDup, dateien), "mit Dublette", `${zahl(mitDup)} Dateien in Dublettengruppen`),
      kachel(zahl(summe("in_anton")), "schon in Anton", `${prozent(summe("in_anton"), dateien)} der Dateien`),
    ].join("");
    const kacheln = [
      kachel(Math.round(100 * (modul?.anteil || 0)) + " %", "analysiert", esc(modul?.text || ""), modul?.anteil || 0, !!modul?.fertig),
      kachel(prozent(bewertet, dateien), "bewertet", `${zahl(bewertet)} von ${zahl(dateien)} Dateien`, dateien ? bewertet / dateien : 0,
             dateien > 0 && bewertet === dateien),
      ...(d.erschliessung ? [
        kachel(prozent(d.erschliessung.erschlossen, d.erschliessung.uebernommen), "erschlossen",
               `${zahl(d.erschliessung.erschlossen)} von ${zahl(d.erschliessung.uebernommen)} übernommenen Dateien`,
               d.erschliessung.uebernommen ? d.erschliessung.erschlossen / d.erschliessung.uebernommen : 0,
               d.erschliessung.uebernommen > 0 && d.erschliessung.erschlossen === d.erschliessung.uebernommen),
        kachel(prozent(d.erschliessung.zugeordnet, d.erschliessung.uebernommen), "zugeordnet",
               `${zahl(d.erschliessung.zugeordnet)} Dateien in den Anton-Bestand eingereiht`,
               d.erschliessung.uebernommen ? d.erschliessung.zugeordnet / d.erschliessung.uebernommen : 0,
               d.erschliessung.uebernommen > 0 && d.erschliessung.zugeordnet === d.erschliessung.uebernommen)] : []),
    ].join("");
    const je = (umbau = (z) => z) => pl.map((p) => ({ name: p.id, werte: umbau({ ...p.zaehler }) }));
    const a = d.analyse.anton;
    return `<h3 class="db-abschnitt">Bestand</h3><div class="db-kennzahlen">${bestandKacheln}</div>
      <h3 class="db-abschnitt">Fortschritt</h3><div class="db-kennzahlen">${kacheln}</div>${laufBlock(d)}
      <div class="db-raster">
        ${karte("Analyse je Datenträger", analyseTabelle(d), true)}
        ${karte("Bewertung", stapel(je(), BEWERTUNG))}
        ${d.erschliessung ? karte("Erschließung", stapel(d.erschliessung.platten.filter((p) => p.uebernommen).map((p) => ({ name: p.id, werte: esTeile(p) })),
          ERSCHLIESSUNG, { rechts: (z, ganz) => prozent((z.werte.zugeordnet || 0) + (z.werte.nur_erschlossen || 0), ganz) }), false,
          "Übernommene Dateien je Datenträger; rechts der Anteil erschlossen.") : ""}
        ${karte("Archivfähigkeit", stapel(je(), AMPEL), true)}
      </div>
      <div class="db-raster">
        ${karte("Dubletten", stapel(je(mitEinmalig), DUBLETTEN), false, "Je Datei die stärkste Art, über alle Datenträger.")}
        ${karte("Schon in Anton", stapel(pl.map((p) => ({ name: p.id, werte: a.je_platte?.[p.id] || {} })), ANTON),
                false, a.stand ? `Bestand aus Anton vom ${a.stand.stand.split("/")[0]}` : "Noch kein Bestand aus Anton geladen.")}
      </div>`;
  }

  function laufBlock(d) {
    const l = d.erfassung.lauf;
    if (!l?.aktiv) return "";
    const s = l.schritte.find((x) => x.status === "läuft");
    return `<div class="db-lauf"><i class="drehen"></i>
      <div><b>Analyse läuft: ${esc(l.name || l.platte_id)}</b>${s ? ` · ${esc(s.titel)}` : " · startet"}${s?.anteil != null ? ` · ${Math.round(100 * s.anteil)} %` : ""}
        <div class="leise">${esc(s?.text || "")} · gestartet ${esc(zeit(l.start))}</div>
        ${s?.anteil != null ? `<div class="st-spur"><i style="width:${(100 * s.anteil).toFixed(1)}%"></i></div>` : ""}</div>
      ${d.live ? `<button type="button" class="knopf-leise" data-aktion="zum-lauf">Zum Fortschritt</button>` : ""}</div>`;
  }

  function analyseTabelle(d) {
    const l = d.erfassung.lauf;
    return `<div class="db-tabelle-rahmen"><table class="db-tabelle"><thead><tr><th>Datenträger</th><th>Etikett</th><th class="zahl">Dateien</th>
        <th>Schritte</th><th>Stand</th></tr></thead><tbody>${d.erfassung.platten.map((p) => {
      const offen = d.schritte.length - p.erledigt.length, jetzt = l?.aktiv && l.platte_id === p.platte_id;
      return `<tr${jetzt ? ' class="laeuft"' : ""}><td><b>${esc(p.platte_id)}</b><div class="leise">${esc(p.volume_name || "")}</div></td>
        <td class="etikett">${esc((p.etikett_text || "").split("\n")[0])}</td>
        <td class="zahl">${zahl(p.dateien)}<div class="leise">${bytes(p.bytes)}</div></td>
        <td><div class="chips">${chips(d, p)}</div></td>
        <td class="nowrap">${jetzt ? "läuft" : offen ? `${offen} von ${d.schritte.length} offen` : '<span class="gut-text">vollständig</span>'}</td></tr>`;
    }).join("")}</tbody></table></div>`;
  }

  function analyse(d) {
    const kopf = d.schritte.map((s) => `<th class="zahl">${esc(s.name)}</th>`).join("");
    const zeilen = d.erfassung.platten.map((p) => `<tr><td><b>${esc(p.platte_id)}</b></td>${d.schritte.map((s) => {
      const n = p.offen?.[s.k];
      return `<td class="zahl">${n === 0 ? `<span class="gut-text" title="erledigt">${icon("check")}</span>` : n == null ? "–" : zahl(n)}</td>`;
    }).join("")}</tr>`).join("");
    return `${laufBlock(d)}<div class="db-raster">
      ${karte("Offene Dateien je Schritt", `<div class="db-tabelle-rahmen"><table class="db-tabelle"><thead><tr><th>Datenträger</th>${kopf}</tr></thead>
        <tbody>${zeilen}</tbody></table></div>`, true, "Haken = erledigt · Zahl = offene Dateien · – = noch nicht gelaufen bzw. kein Bestand aus Anton geladen")}
      ${karte("Stand je Datenträger", analyseTabelle(d), true)}</div>`;
  }

  function bestand(d) {
    const b = d.analyse.bestand, ids = d.bewertung.platten.map((p) => p.id);
    const reihe = ids.map((p, i) => [p, `var(--reihe-${i % 8})`, p]);
    const gruppenFarben = b.formatgruppen.map((g, i) => [g.gruppe, `var(--reihe-${i % 8})`, g.gruppe]);
    const gruppen = (bestandAnsicht === "platten"
      ? stapel(ids.map((p) => ({ name: p, werte: Object.fromEntries(b.formatgruppen.map((g) => [g.gruppe, g.je_platte[p] || 0])) })),
               gruppenFarben, { rechts: (z, ganz) => zahl(ganz) })
      : stapel(b.formatgruppen.map((g) => ({ name: g.gruppe, werte: g.je_platte })), reihe, { rechts: (z, ganz) => zahl(ganz) }));
    const umschalt = `<div class="umschalter db-umschalter" role="tablist">${[["formate", "Datenträger je Format"], ["platten", "Formate je Datenträger"]].map(([k, n]) =>
      `<button type="button" data-bestand-ansicht="${k}" class="${bestandAnsicht === k ? "aktiv" : ""}" aria-selected="${bestandAnsicht === k}">${n}</button>`).join("")}</div>`;
    const hoechst = Math.max(1, ...b.jahre.map((j) => b.stufen.reduce((s, k) => s + j[k], 0)));
    const saeulen = b.jahre.length ? `${legende(b.stufen.map((s) => [s, STUFEN[s], s]))}<div class="db-saeulen">${b.jahre.map((j) => {
      const summe = b.stufen.reduce((s, k) => s + j[k], 0);
      return `<div class="db-saeule" title="${esc(`${j.jahr}: ${zahl(summe)} Dateien`)}">${b.stufen.map((k) => j[k]
        ? `<i style="height:${(100 * j[k]) / hoechst}%;background:${STUFEN[k]}"></i>` : "").join("")}</div>`;
    }).join("")}</div><div class="db-achse leise"><span>${b.jahre[0].jahr}</span><span>${b.jahre.at(-1).jahr}</span></div>`
      : `<div class="leise">Noch keine Daten.</div>`;
    const quellen = b.datumsquellen.map((q) => ({ quelle: q.quelle, ...q.je_platte }));
    return `<div class="db-raster">
      ${karte("Formatgruppen und Datenträger", umschalt + gruppen, false, bestandAnsicht === "platten"
        ? "Dateien je Datenträger, aufgeteilt nach Formatgruppe; rechts die Summe." : "Dateien je Formatgruppe, aufgeteilt nach Datenträger; rechts die Summe.")}
      ${karte("Zeitraum", saeulen, false, "Dateien je Jahr nach Herkunft des Datums; dunkel = eingebettet und verlässlich.")}
      ${karte("Alle Formate (Siegfried)", tabelle([["gruppe", "Gruppe"], ["format", "Format"], ["version", "Version"], ["puid", "PRONOM"],
        ["dateien", "Dateien", "zahl"], ["bytes", "Umfang", "bytes"], ["ampel", "Ampel"], ["endungen", "Endungen"], ["platten", "Datenträger"]], b.formate), true)}
      ${karte("Datumsquellen je Datenträger", tabelle([["quelle", "Quelle"], ...ids.map((p) => [p, p, "zahl"])], quellen, { suche: false }), true)}
    </div>`;
  }

  // Archivfähigkeit in zwei Teilen: eigene Regeln (Ampel) und NARA (Risiko des Formats)
  function archiv(d) {
    const e = d.analyse.archiv.eigene, n = d.analyse.archiv.nara, pl = d.bewertung.platten;
    const ohneDup = ["ohne_duplikate", "davon ohne Dubletten", "zahl"];
    const zwei = "Dieselbe Einteilung zweimal: gezählt nach Anzahl der Dateien und gewichtet nach Datenmenge. Viele kleine Dateien wiegen links schwer, wenige große (Filme, Rohdaten) rechts.";
    return `<div class="db-zweispaltig"><div class="db-spalte">
      <h3 class="db-abschnitt">Eigene Regeln</h3>
      <div class="leise db-text">Ampel aus <span class="mono">vorgaben/archivformate.csv</span>: Format, Lesbarkeit, leere Dateien, System- und Programmdateien.
        grün: archivfähig · gelb: umwandeln oder prüfen · rot: nicht lesbar, leer, unbekannt, System- oder Programmdatei.</div>
      <div class="db-raster">
      ${karte("Ampel je Datenträger nach Anzahl der Dateien", stapel(pl.map((p) => ({ name: p.id, werte: p.zaehler })), AMPEL), true, zwei)}
      ${karte("Ampel je Datenträger nach Datenmenge", stapel(pl.map((p) => ({ name: p.id, werte: e.bytes_je_platte[p.id] || {} })), AMPEL.slice(0, 3), { einheit: bytes }), true)}
      ${karte("Maßnahmen", tabelle([["ampel", "Ampel"], ["massnahme", "Maßnahme"], ["dateien", "Dateien", "zahl"], ohneDup, ["bytes", "Umfang", "bytes"],
        ["formate", "häufigste Formate"]], e.massnahmen), true, "„davon ohne Dubletten“: so viele bleiben, wenn überzählige Kopien wegfallen; das ist der eigentliche Aufwand.")}
      ${karte("Gründe für Gelb und Rot", tabelle([["ampel", "Ampel"], ["grund", "Grund"], ["dateien", "Dateien", "zahl"], ["bytes", "Umfang", "bytes"]], e.gruende), true)}
      </div></div><div class="db-spalte">
      <h3 class="db-abschnitt">NARA</h3>
      <div class="leise db-text">Digital Preservation Framework der NARA, wie in Anton. NARA bewertet nur das Format; Unknown = nicht bei NARA oder nicht identifiziert.</div>
      <div class="db-raster">
      ${karte("NARA-Risiko je Datenträger nach Anzahl der Dateien", stapel(pl.map((p) => ({ name: p.id, werte: n.dateien_je_platte[p.id] || {} })), NARA), true, zwei)}
      ${karte("NARA-Risiko je Datenträger nach Datenmenge", stapel(pl.map((p) => ({ name: p.id, werte: n.bytes_je_platte[p.id] || {} })), NARA, { einheit: bytes }), true)}
      ${karte("Eigene Ampel je NARA-Risiko", stapel(NARA.filter(([r]) => n.ampel_je_risiko[r]).map(([r, , name]) => ({ name, werte: n.ampel_je_risiko[r] })),
        AMPEL.slice(0, 3), { rechts: (z, ganz) => zahl(ganz) }), true,
        "Dateien je NARA-Risiko, gefärbt nach eigener Ampel; rechts die Summe. Die eigene Ampel prüft zusätzlich Lesbarkeit und Systemdateien; Abweichungen lohnen einen Blick.")}
      ${karte("NARA-Maßnahmen", tabelle([["nara_risiko", "Risiko"], ["nara_massnahme", "Maßnahme"], ["nara_plan", "Plan"], ["dateien", "Dateien", "zahl"], ohneDup,
        ["bytes", "Umfang", "bytes"], ["ampel", "eigene Ampel"], ["formate", "häufigste Formate"]], n.massnahmen), true,
        "Maßnahme und Plan nach NARA, daneben die eigene Ampel derselben Dateien.")}
      </div></div></div>`;
  }

  function duplikate(d) {
    const u = d.analyse.duplikate, pl = d.bewertung.platten, ids = Object.keys(u.matrix);
    const kacheln = u.arten.map((a) => kachel(zahl(a.gruppen), `Gruppen ${a.art}`, `${zahl(a.ueberzaehlig)} überzählige Dateien, ${bytes(a.bytes)}`)).join("");
    const matrix = ids.length ? `<div class="db-tabelle-rahmen"><table class="db-tabelle db-matrix"><thead><tr><th></th>${ids.map((b) =>
      `<th class="zahl">${esc(b)}</th>`).join("")}</tr></thead><tbody>${ids.map((a) => `<tr><th>${esc(a)}</th>${ids.map((b) => {
        const w = u.matrix[a][b] || 0;
        return a === b ? `<td class="zahl leise">–</td>` : `<td class="zahl" style="background:color-mix(in srgb, var(--fokus) ${Math.round(w * 75)}%, transparent);${w > .55 ? "color:#fff" : ""}"
          title="${esc(`${prozent(w, 1)} der Inhalte von ${a} liegen auch auf ${b}`)}">${prozent(w, 1)}</td>`;
      }).join("")}</tr>`).join("")}</tbody></table></div>` : `<div class="leise">Erst ab zwei Datenträgern.</div>`;
    const ordner = u.ordner.map((o) => ({ ...o, fundorte: o.fundorte.join("\n") }));
    return `<div class="db-kennzahlen">${kacheln}</div><div class="db-raster">
      ${karte("Dubletten je Datenträger", stapel(pl.map((p) => ({ name: p.id, werte: mitEinmalig(p.zaehler) })), DUBLETTEN),
        false, "Je Datei die stärkste Art: exakt gleich vor Variante vor beinahe gleich.")}
      ${karte("Gemeinsame Inhalte zwischen Datenträgern", matrix, false, "Zeile A, Spalte B: Anteil der Inhalte von A, die auch auf B liegen; 100 % = Backup oder Klon.")}
      ${karte("Wo liegen die Dubletten?", u.treemap ? `<div data-baustein="treemap"></div>` : `<div class="leise">Noch keine Daten.</div>`, true,
        "Jede Datei ist ein Kästchen (Fläche = Größe), Ordner sind umrandet; gefärbt sind zunächst nur überzählige Kopien. "
        + "Ein einfarbiger Block: ganzer Ordner doppelt; verstreute Flecken: einzelne Dateien. Maus auf eine Datei: die anderen "
        + "Exemplare ihrer Gruppe werden rot umrandet. Klick: in den Ordner zoomen; zurück über die Pfadleiste.")}
      ${karte("Ordner, die als Ganzes mehrfach vorliegen", tabelle([["kopien", "Kopien", "zahl"], ["dateien", "Dateien", "zahl"],
        ["bytes", "Umfang", "bytes"], ["ueberzaehlig", "überzählig", "bytes"], ["fundorte", "Fundorte"]], ordner, { gesamt: u.ordner_gesamt }), true,
        "Gleicher Inhalt mit allen Unterordnern, egal unter welchem Namen; nur die oberste Ebene.")}
    </div>`;
  }

  function ordner(d) {
    const text = "Ordner aufklappen per Klick. Je Ordner mit allen Unterordnern: Anteil der Dateien, deren Inhalt auch in einem anderen "
      + "Ordner dieses Datenträgers liegt (außerhalb des Ordners), und Anteil, der auch auf einem anderen Datenträger liegt; daneben, auf welchen. "
      + "Beides kann zugleich zutreffen. Dubletten innerhalb desselben Ordners zählen nicht, leere Dateien und Systemdateien auch nicht. "
      + "100 % auf anderen Datenträgern heißt: der ganze Ordner ist anderswo vorhanden.";
    const da = Object.keys(d.analyse.ordnerbaum || {}).length;
    return `<div class="db-raster">${karte("Ordnerbaum je Datenträger", da ? `<div data-baustein="baum"></div>` : `<div class="leise">Noch keine Daten.</div>`,
      true, text)}</div>`;
  }

  // ---------- Bausteine mit eigener Bedienung: Treemap und Ordnerbaum ----------
  // Ihr Zustand (Zoom, aufgeklappte Ordner, Schalter) bleibt beim Wechsel der Reiter erhalten.
  const farbeAus = (el, name) => getComputedStyle(el).getPropertyValue(name).trim();
  const umschalter = (zustand, schluessel, titel, optionen) => `<span class="leise">${esc(titel)}</span><span class="umschalter">${optionen.map(([w, t]) =>
    `<button type="button" data-schalter="${schluessel}" data-wert="${esc(w)}" class="${String(zustand[schluessel]) === String(w) ? "an" : ""}">${esc(t)}</button>`).join("")}</span>`;

  function squarify(eintraege, x, y, w, h, ablegen) {
    // eintraege absteigend nach wert sortiert; legt Zeilen entlang der kürzeren Seite (Bruls u. a. 2000)
    let rest = eintraege.reduce((s, e) => s + e.wert, 0);
    let i = 0;
    while (i < eintraege.length && w > 0 && h > 0 && rest > 0) {
      const kurz = Math.min(w, h), faktor = (w * h) / rest;
      const start = i;
      let flaeche = 0, bisher = Infinity;
      while (i < eintraege.length) {
        const a = eintraege[i].wert * faktor, s = flaeche + a, groesste = eintraege[start].wert * faktor;
        const verhaeltnis = Math.max((kurz * kurz * groesste) / (s * s), (s * s) / (kurz * kurz * a));
        if (i > start && verhaeltnis > bisher) break;
        flaeche = s; bisher = verhaeltnis; i++;
      }
      const dicke = flaeche / kurz;
      let pos = 0;
      for (let k = start; k < i; k++) {
        const laenge = (eintraege[k].wert * faktor) / dicke;
        if (w >= h) ablegen(eintraege[k], x, y + pos, dicke, laenge);
        else ablegen(eintraege[k], x + pos, y, laenge, dicke);
        pos += laenge;
      }
      if (w >= h) { x += dicke; w -= dicke; } else { y += dicke; h -= dicke; }
      rest -= flaeche / faktor;
    }
  }

  // Treemap: daten.dateien = [[Ordnernummer, Name, Bytes, Art, überzählig, Gruppennummer]];
  // Art 0 ohne Duplikat, 1 exakt gleich, 2 Variante, 3 beinahe gleich, 4 Systemdatei
  const TM_TEILE = [["--spur", "ohne Dublette"], ["--d-exakt", "exakt gleich"], ["--d-variante", "Variante"],
                    ["--d-beinahe", "beinahe gleich"], ["--violett", "Systemdatei"]];
  const tm = { flaeche: "groesse", faerben: "ueberzaehlig", pfad: null };
  let aufraeumen = [];                                   // Beobachter der Bausteine im zuletzt gezeichneten Reiter

  function treemap(behaelter, daten) {
    const dateien = daten.dateien;
    const wurzel = { name: "alle Datenträger", kinder: new Map(), dateien: [], eltern: null };
    const knotenJeOrdner = daten.ordner.map((pfad) => {
      let k = wurzel;
      pfad.split("/").forEach((teil) => {
        if (!k.kinder.has(teil)) k.kinder.set(teil, { name: teil, kinder: new Map(), dateien: [], eltern: k });
        k = k.kinder.get(teil);
      });
      return k;
    });
    const mitglieder = new Map();
    dateien.forEach((d, i) => {
      knotenJeOrdner[d[0]].dateien.push(i);
      if (d[5] >= 0) {
        if (!mitglieder.has(d[5])) mitglieder.set(d[5], []);
        mitglieder.get(d[5]).push(i);
      }
    });
    const pfadVon = (k) => { const t = []; for (let n = k; n && n !== wurzel; n = n.eltern) t.unshift(n); return t; };
    let aktuell = wurzel;                                 // gemerkten Ausschnitt wiederfinden
    for (const name of tm.pfad || []) { const k = aktuell.kinder.get(name); if (!k) break; aktuell = k; }
    if (!tm.pfad && wurzel.kinder.size === 1) aktuell = [...wurzel.kinder.values()][0];

    behaelter.innerHTML = `<div class="db-werkzeuge">
        ${umschalter(tm, "flaeche", "Fläche", [["groesse", "Größe"], ["anzahl", "Anzahl"]])}
        ${umschalter(tm, "faerben", "Einfärben", [["alle", "alle Exemplare"], ["ueberzaehlig", "nur überzählige"]])}
        ${legende(TM_TEILE.map(([v, n]) => [, `var(${v})`, n]))}</div>
      <nav class="db-pfad"></nav>
      <div class="db-buehne"><canvas></canvas><canvas class="db-auflage"></canvas><div class="db-hinweis" hidden></div></div>`;
    const pfadleiste = behaelter.querySelector(".db-pfad"), buehne = behaelter.querySelector(".db-buehne");
    const [leinwand, auflage] = buehne.querySelectorAll("canvas"), hinweis = buehne.querySelector(".db-hinweis");

    const wert = (i) => (tm.flaeche === "groesse" ? dateien[i][2] : 1);
    function summen(k) {
      let s = 0;
      k.dateien.forEach((i) => { s += wert(i); });
      k.kinder.forEach((c) => { s += summen(c); });
      return (k.summe = s);
    }
    summen(wurzel);
    let farben = [], linie = {};
    const farbe = (i) => {
      const d = dateien[i];
      return farben[tm.faerben === "ueberzaehlig" && d[3] >= 1 && d[3] <= 3 && !d[4] ? 0 : d[3]];
    };

    let blaetter = [], ordnerFelder = [], feldJeDatei = new Map();
    function zeichnen() {
      const breite = buehne.clientWidth, hoehe = buehne.clientHeight;
      if (!breite) return;
      farben = TM_TEILE.map(([v]) => farbeAus(behaelter, v));          // Farben aus dem Thema (hell oder dunkel)
      linie = { stark: farbeAus(behaelter, "--text-2"), leicht: farbeAus(behaelter, "--linie-stark"), grund: farbeAus(behaelter, "--karte"),
                andere: farbeAus(behaelter, "--a-rot"), selbst: farbeAus(behaelter, "--text") };
      const dpr = window.devicePixelRatio || 1;
      [leinwand, auflage].forEach((c) => {
        c.width = breite * dpr; c.height = hoehe * dpr;
        c.style.width = breite + "px"; c.style.height = hoehe + "px";
        c.getContext("2d").setTransform(dpr, 0, 0, dpr, 0, 0);
      });
      const ctx = leinwand.getContext("2d");
      ctx.fillStyle = linie.grund;
      ctx.fillRect(0, 0, breite, hoehe);
      blaetter = []; ordnerFelder = []; feldJeDatei = new Map();
      knoten(ctx, aktuell, 0, 0, breite, hoehe, 0);
      auflage.getContext("2d").clearRect(0, 0, breite, hoehe);
      pfadZeigen();
    }

    function knoten(ctx, k, x, y, w, h, tiefe) {
      const eintraege = [];
      k.kinder.forEach((c) => { if (c.summe > 0) eintraege.push({ wert: c.summe, knoten: c }); });
      k.dateien.forEach((i) => { const v = wert(i); if (v > 0) eintraege.push({ wert: v, datei: i }); });
      eintraege.sort((a, b) => b.wert - a.wert);
      squarify(eintraege, x, y, w, h, (e, x, y, w, h) => {
        if (e.datei !== undefined) {
          ctx.fillStyle = farbe(e.datei);
          if (w > 2.5 && h > 2.5) ctx.fillRect(x + 0.5, y + 0.5, w - 1, h - 1);
          else ctx.fillRect(x, y, w, h);
          feldJeDatei.set(e.datei, blaetter.length);
          blaetter.push([x, y, w, h, e.datei]);
        } else {
          if (tiefe === 0) ordnerFelder.push([x, y, w, h, e.knoten]);
          const rand = w > 8 && h > 8 ? 1.5 : 0;
          knoten(ctx, e.knoten, x + rand, y + rand, w - 2 * rand, h - 2 * rand, tiefe + 1);
          if (w > 12 && h > 12) {
            ctx.strokeStyle = tiefe === 0 ? linie.stark : linie.leicht;
            ctx.lineWidth = tiefe === 0 ? 1.5 : 1;
            ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);
          }
        }
      });
    }

    function pfadZeigen() {
      const kette = [wurzel, ...pfadVon(aktuell)];
      pfadleiste.innerHTML = kette.map((k, i) => k === aktuell ? `<b>${esc(k.name)}</b>`
        : `<button type="button" class="db-pfadknopf" data-tiefe="${i}">${esc(k.name)}</button>`).join(" / ")
        + ` <span class="leise">· ${tm.flaeche === "groesse" ? bytes(aktuell.summe) : zahl(aktuell.summe) + " Dateien"} · Klick auf einen Ordner zoomt hinein</span>`;
    }
    function zoomen(k) {
      aktuell = k;
      tm.pfad = pfadVon(k).map((n) => n.name);
      hinweis.hidden = true; zuletzt = -1;
      zeichnen();
    }

    const treffer = (liste, mx, my) => {
      for (let k = liste.length - 1; k >= 0; k--) {
        const f = liste[k];
        if (mx >= f[0] && mx < f[0] + f[2] && my >= f[1] && my < f[1] + f[3]) return f;
      }
      return null;
    };
    const pfadDatei = (i) => daten.ordner[dateien[i][0]] + "/" + dateien[i][1];

    let zuletzt = -1;
    buehne.addEventListener("mousemove", (ev) => {
      const r = buehne.getBoundingClientRect(), mx = ev.clientX - r.left, my = ev.clientY - r.top;
      const f = treffer(blaetter, mx, my);
      if (!f) { hinweis.hidden = true; return; }
      const i = f[4], d = dateien[i];
      if (i !== zuletzt) {
        zuletzt = i;
        const ctx = auflage.getContext("2d");
        ctx.clearRect(0, 0, buehne.clientWidth, buehne.clientHeight);
        ctx.lineWidth = 2;
        (d[5] >= 0 ? mitglieder.get(d[5]) : [i]).forEach((j) => {
          const b = feldJeDatei.get(j);
          if (b === undefined) return;
          const [x, y, w, h] = blaetter[b];
          ctx.strokeStyle = j === i ? linie.selbst : linie.andere;
          ctx.strokeRect(x - 1, y - 1, Math.max(w, 3) + 2, Math.max(h, 3) + 2);
        });
        const dup = d[3] >= 1 && d[3] <= 3 ? (d[4] ? " · überzählig" : " · Leitdatei") : "";
        let html = `<b>${esc(pfadDatei(i))}</b><div>${bytes(d[2])} · ${esc(TM_TEILE[d[3]][1])}${dup}</div>`;
        if (d[5] >= 0) {
          const liste = mitglieder.get(d[5]);
          html += `<div class="leise">Gruppe ${esc(daten.gruppen[d[5]])}: ${liste.length} Exemplare (rot umrandet, soweit im Ausschnitt)</div>`
            + liste.slice(0, 8).map((j) => `<div class="mono">${dateien[j][4] ? "· " : "★ "}${esc(pfadDatei(j))}</div>`).join("")
            + (liste.length > 8 ? `<div class="leise">… und ${liste.length - 8} weitere</div>` : "");
        }
        hinweis.innerHTML = html;
      }
      hinweis.hidden = false;
      const rechts = mx + 16 + hinweis.offsetWidth > buehne.clientWidth;
      hinweis.style.left = Math.max(0, rechts ? mx - 16 - hinweis.offsetWidth : mx + 16) + "px";
      hinweis.style.top = Math.max(0, Math.min(my + 16, buehne.clientHeight - hinweis.offsetHeight - 4)) + "px";
    });
    buehne.addEventListener("mouseleave", () => {
      hinweis.hidden = true; zuletzt = -1;
      auflage.getContext("2d").clearRect(0, 0, buehne.clientWidth, buehne.clientHeight);
    });
    buehne.addEventListener("click", (ev) => {
      const r = buehne.getBoundingClientRect();
      const f = treffer(ordnerFelder, ev.clientX - r.left, ev.clientY - r.top);
      if (f) zoomen(f[4]);
    });
    behaelter.addEventListener("click", (ev) => {
      const s = ev.target.closest("[data-schalter]"), p = ev.target.closest("[data-tiefe]");
      if (p) zoomen([wurzel, ...pfadVon(aktuell)][+p.dataset.tiefe]);
      if (!s) return;
      tm[s.dataset.schalter] = s.dataset.wert;
      s.parentElement.querySelectorAll("button").forEach((b) => b.classList.toggle("an", b === s));
      if (s.dataset.schalter === "flaeche") summen(wurzel);
      zeichnen();
    });
    const beobachter = new ResizeObserver(() => zeichnen());
    beobachter.observe(buehne);
    aufraeumen.push(() => beobachter.disconnect());
  }

  // Ordnerbaum je Datenträger: ordner = [[Name, Eltern, Dateien, direkt, Bytes, ex_gleich, ex_gleich_b, ex_andere, ex_andere_b,
  //   al_gleich, al_gleich_b, al_andere, al_andere_b, ex_platten, al_platten], …]; Eltern vor Kindern (erfassung/uebersicht.py).
  // ex = nur exakt gleich, al = alle Duplikatarten; gleich = anderer Ordner dieser Platte, andere = andere Platten; _b = Bytes
  const bz = { platte: null, art: "al", mass: "dateien", sortierung: "name", offen: {} };

  function baum(behaelter, d) {
    const alle = d.analyse.ordnerbaum, ids = Object.keys(alle).sort();
    if (!ids.includes(bz.platte)) bz.platte = ids[0];
    const ordner = alle[bz.platte];
    const kinder = ordner.map(() => []), tiefe = ordner.map(() => 0);
    ordner.forEach((o, i) => { if (o[1] >= 0) { kinder[o[1]].push(i); tiefe[i] = tiefe[o[1]] + 1; } });
    const offen = (bz.offen[bz.platte] ||= new Set([0]));
    const etikett = (d.analyse.platten.find((p) => p.platte_id === bz.platte)?.etikett_text || "").trim();

    behaelter.innerHTML = `<div class="db-werkzeuge">${umschalter(bz, "platte", "Datenträger", ids.map((p) => [p, p]))}</div>
      <div class="db-werkzeuge">
        ${umschalter(bz, "art", "Dubletten", [["al", "alle Arten"], ["ex", "nur exakt gleich"]])}
        ${umschalter(bz, "mass", "Anteil nach", [["dateien", "Dateien"], ["bytes", "Größe"]])}
        <select class="db-auswahl" aria-label="Sortierung">${[["name", "nach Name"], ["groesse", "nach Größe"], ["gleich", "nach % andere Ordner"],
          ["andere", "nach % andere Datenträger"]].map(([w, t]) => `<option value="${w}"${bz.sortierung === w ? " selected" : ""}>${t}</option>`).join("")}</select>
        <span class="umschalter db-rechts">${[[1, "zuklappen"], [2, "2 Ebenen"], [3, "3 Ebenen"]].map(([n, t]) =>
          `<button type="button" data-ebenen="${n}">${t}</button>`).join("")}</span></div>
      ${etikett ? `<div class="leise db-text">Etikett: „${esc(etikett.split("\n").join(" / "))}“</div>` : ""}
      <div class="db-baum"><div class="db-baum-zeile db-baum-kopf"><div>Ordner</div><div class="zahl">Dateien</div><div class="zahl">Umfang</div>
        <div>auch in anderen Ordnern dieses Datenträgers</div><div>auch auf anderen Datenträgern</div><div>welche Datenträger</div></div><div class="db-baum-rumpf"></div></div>`;
    const rumpf = behaelter.querySelector(".db-baum-rumpf");

    function werte(i) {
      const o = ordner[i], basis = bz.art === "ex" ? 5 : 9, b = bz.mass === "bytes" ? 1 : 0;
      return { gesamt: b ? o[4] : o[2], gleich: o[basis + b], andere: o[basis + 2 + b], platten: o[bz.art === "ex" ? 13 : 14] };
    }
    const anteil = (teil, ganz) => (ganz && teil ? (100 * teil) / ganz : 0);
    const anteilText = (p) => (p === 0 ? "–" : p < 1 ? "< 1 %" : p > 99 && p < 100 ? "> 99 %" : Math.round(p) + " %");
    const balken = (p, klasse) => `<div class="db-baum-anteil"><span class="db-baum-balken"><i class="${klasse}" style="width:${p}%"></i></span>
      <span class="zahl">${anteilText(p)}</span></div>`;
    const pfad = (i) => { const t = []; for (let k = i; k >= 0; k = ordner[k][1]) t.unshift(ordner[k][0]); return t.join("/"); };
    function sortiert(liste) {
      const s = bz.sortierung;
      if (s === "name") return [...liste].sort((a, b) => ordner[a][0].localeCompare(ordner[b][0], "de", { numeric: true }));
      const schluessel = (i) => { const w = werte(i); return s === "groesse" ? ordner[i][4] : anteil(s === "gleich" ? w.gleich : w.andere, w.gesamt); };
      return [...liste].sort((a, b) => schluessel(b) - schluessel(a));
    }
    function zeile(i) {
      const o = ordner[i], w = werte(i), auf = offen.has(i), mitKindern = kinder[i].length > 0;
      const titel = `${pfad(i)}\n${zahl(o[2])} Dateien, davon ${zahl(o[3])} direkt im Ordner, ${kinder[i].length} Unterordner`;
      return `<div class="db-baum-zeile${mitKindern ? " klickbar" : ""}" data-ordner="${i}" title="${esc(titel)}">
        <div class="db-baum-name" style="padding-left:${tiefe[i] * 18}px"><span class="db-baum-pfeil">${mitKindern ? (auf ? icon("chevron-down") : icon("chevron-right")) : ""}</span>${tiefe[i] === 0 ? `<b>${esc(o[0])}</b>` : esc(o[0])}</div>
        <div class="zahl">${zahl(o[2])}</div><div class="zahl">${bytes(o[4])}</div>
        ${balken(anteil(w.gleich, w.gesamt), "db-baum-gleich")}${balken(anteil(w.andere, w.gesamt), "db-baum-andere")}
        <div class="leise">${esc(w.platten)}</div></div>`;
    }
    function zeichnen() {
      const zeilen = [];
      (function anhaengen(i) {
        zeilen.push(zeile(i));
        if (offen.has(i)) sortiert(kinder[i]).forEach(anhaengen);
      })(0);
      rumpf.innerHTML = zeilen.join("");                // der Rahmen bleibt, damit die Scrollposition erhalten bleibt
    }
    zeichnen();

    behaelter.onclick = (ev) => {
      const s = ev.target.closest("[data-schalter]"), e = ev.target.closest("[data-ebenen]"), z = ev.target.closest(".db-baum-zeile.klickbar");
      if (s) { bz[s.dataset.schalter] = s.dataset.wert; return baum(behaelter, d); }     // neu aufbauen (andere Platte, andere Schalter)
      if (e) { offen.clear(); ordner.forEach((_, i) => { if (tiefe[i] < +e.dataset.ebenen) offen.add(i); }); return zeichnen(); }
      if (z) { const i = +z.dataset.ordner; if (offen.has(i)) offen.delete(i); else offen.add(i); zeichnen(); }
    };
    behaelter.querySelector(".db-auswahl").onchange = (ev) => { bz.sortierung = ev.target.value; zeichnen(); };
  }

  const BAUSTEINE = { treemap: (el, d) => treemap(el, d.analyse.duplikate.treemap), baum };

  function anton(d) {
    const a = d.analyse.anton;
    if (!a.stand) return `<div class="db-raster">${karte("Anton", `<div class="leise">Noch kein Bestand aus Anton geholt (Registrierung/Analyse: „Bestand aus Anton holen“).</div>`, true)}</div>`;
    const s = a.stand;
    return `<div class="db-raster">
      ${karte("Abgleich je Datenträger", stapel(d.bewertung.platten.map((p) => ({ name: p.id, werte: a.je_platte?.[p.id] || {} })), ANTON), true,
        `Bestand aus Anton vom ${s.stand.split("/")[0]} (${s.quelle}, ${s.zugang || "Auszug"})` + (s.nur_platten ? `; vollständig abgeglichen nur ${s.nur_platten.replace(",", ", ")}` : ""))}
      ${karte("Wo in Anton? Bestände", tabelle([["bestand", "Bestand"], ["dateien", "Dateien", "zahl"], ["inhalte", "verschiedene Inhalte", "zahl"],
        ["platten", "Datenträger"]], a.bestaende || []), true, "Bestand = Signatur bis zur ersten Zahl, z. B. GFA 59.")}
    </div>`;
  }

  function erschliessung(d) {
    const e = d.erschliessung;
    if (!e) return `<div class="db-raster">${karte("Erschließung", `<div class="leise">Keine Angaben (älterer Bericht).</div>`, true)}</div>`;
    const kacheln = [
      kachel(zahl(e.uebernommen), "übernommen", "Dateien, die erschlossen werden"),
      kachel(prozent(e.erschlossen, e.uebernommen), "erschlossen", `${zahl(e.erschlossen)} Dateien mit Titel und Laufzeit`,
             e.uebernommen ? e.erschlossen / e.uebernommen : 0, e.uebernommen > 0 && e.erschlossen === e.uebernommen),
      kachel(prozent(e.zugeordnet, e.uebernommen), "zugeordnet", `${zahl(e.zugeordnet)} Dateien im Anton-Bestand eingereiht`,
             e.uebernommen ? e.zugeordnet / e.uebernommen : 0, e.uebernommen > 0 && e.zugeordnet === e.uebernommen),
      kachel(zahl(e.bestand.filter((x) => x.art !== "aus Anton").length), "neue Einheiten", "entstehen in Anton erst mit dem Import"),
    ].join("");
    return `<div class="db-kennzahlen">${kacheln}</div><div class="db-raster">
      ${karte("Stand je Datenträger", stapel(e.platten.filter((p) => p.uebernommen).map((p) => ({ name: p.id, werte: esTeile(p) })), ERSCHLIESSUNG,
        { rechts: (z, ganz) => prozent((z.werte.zugeordnet || 0) + (z.werte.nur_erschlossen || 0), ganz) }), false, "Übernommene Dateien; rechts der Anteil erschlossen.")}
      ${karte("Gefüllte Felder", tabelle([["feld", "Feld"], ["dateien", "Dateien", "zahl"]], e.felder, { suche: false }), false,
        "Wie viele übernommene Dateien einen eigenen Wert haben (auch vererbt).")}
      ${karte("Bestand in Anton", e.bestand.length ? tabelle([["titel", "Einheit"], ["signatur", "Signatur"], ["stufe", "Stufe"], ["art", "Herkunft"],
        ["dateien", "Dateien", "zahl"]], e.bestand) : `<div class="leise">Noch keine Verzeichnungseinheit aus Anton geladen.</div>`, true,
        "Geladene Boxen und neue Einheiten darunter mit den zugeordneten Dateien (einschließlich der Einheiten darin).")}
      ${karte("Am meisten offen", tabelle([["platte", "Datenträger"], ["ordner", "Ordner"], ["titel", "Titel"], ["uebernommen", "übernommen", "zahl"],
        ["erschlossen", "erschlossen", "zahl"], ["offen", "offen", "zahl"]], e.offen), true, "Ordner der ersten beiden Ebenen mit den meisten noch nicht erschlossenen Dateien.")}
      ${karte("Vorlauf", tabelle([["schritt", "Schritt"], ["zeit", "zuletzt", "zeit"], ["ergebnis", "mit Ergebnis", "zahl"],
        ["angenommen", "Vorschläge angenommen", "zahl"], ["verworfen", "verworfen", "zahl"]], e.vorlauf, { suche: false }), true)}
    </div>`;
  }

  function probleme(d) {
    const p = d.analyse.probleme, ids = d.bewertung.platten.map((x) => x.id);
    return `<div class="db-raster">
      ${karte("Befunde je Bereich", stapel(p.bereiche.map((b) => ({ name: b.bereich, werte: b.je_platte })),
        ids.map((id, i) => [id, `var(--reihe-${i % 8})`, id]), { rechts: (z, ganz) => zahl(ganz) }), true,
        "Dateien mit Befund je Schritt, aufgeteilt nach Datenträger; Systemdateien ausgelassen; eine Datei kann mehrere Befunde haben.")}
      ${karte("Alle Befunde", tabelle([["platte_id", "Datenträger"], ["bereich", "Bereich"], ["relpfad", "Pfad"], ["meldung", "Meldung"]], p.liste,
        { gesamt: p.gesamt }), true)}
    </div>`;
  }

  function platten(d) {
    const a = d.analyse;
    return `<div class="db-raster">
      ${karte("Datenträger", tabelle([["platte_id", "Datenträger"], ["volume_name", "Name"], ["dateisystem", "Dateisystem"], ["kapazitaet_bytes", "Größe", "bytes"],
        ["kopie_von", "Kopie von"], ["etikett_text", "Etikett"], ["notiz", "Notiz"], ["smart_status", "SMART"], ["registriert_am", "registriert", "zeit"]],
        a.platten, { suche: false }), true, "Etikett und Kopie-Vermerk gehören zur Überlieferung (Bestandsgeschichte).")}
      ${karte("Leseläufe", tabelle([["platte_id", "Datenträger"], ["art", "Art"], ["start", "Start", "zeit"], ["ende", "Ende", "zeit"],
        ["dateien", "Dateien", "zahl"], ["fehler", "Fehler", "zahl"]], a.scanlaeufe))}
      ${karte("Protokoll", tabelle([["zeit", "Zeit", "zeit"], ["abschnitt", "Abschnitt"], ["objekt", "Objekt"], ["feld", "Feld"], ["alt", "alt"],
        ["neu", "neu"]], a.protokoll), false, "Jede Änderung in der Datenbank, neueste zuerst (die letzten 200).")}
    </div>`;
  }

  const ZEICHNER = { "Überblick": ueberblick, "Analyse": analyse, "Bestand": bestand, "Archivfähigkeit": archiv,
                     "Dubletten": duplikate, "Ordner": ordner, "Anton": anton, "Erschließung": erschliessung, "Probleme": probleme, "Datenträger und Protokoll": platten };
  let reiter = "Überblick";

  function rendern(d, wurzel) {
    aufraeumen.forEach((f) => f());
    aufraeumen = [];
    wurzel.innerHTML = `<nav class="db-reiter" role="tablist">${REITER.map((r) =>
      `<button type="button" role="tab" data-reiter="${esc(r)}" aria-selected="${r === reiter}" class="${r === reiter ? "aktiv" : ""}">${esc(r)}</button>`).join("")}</nav>
      <div class="db-seite">${ZEICHNER[reiter](d)}</div>`;
    wurzel.querySelectorAll("[data-baustein]").forEach((el) => BAUSTEINE[el.dataset.baustein](el, d));
    wurzel.onclick = (e) => {
      const r = e.target.closest("[data-reiter]");
      if (r) { reiter = r.dataset.reiter; rendern(d, wurzel); }
      const b = e.target.closest("[data-bestand-ansicht]");
      if (b) { bestandAnsicht = b.dataset.bestandAnsicht; rendern(d, wurzel); }
    };
    wurzel.oninput = (e) => {                      // Suchfeld filtert die Zeilen der Tabelle darunter
      if (!e.target.classList.contains("db-suche")) return;
      const wort = e.target.value.toLocaleLowerCase("de");
      e.target.nextElementSibling.querySelectorAll("tbody tr").forEach((tr) =>
        (tr.hidden = !!wort && !tr.textContent.toLocaleLowerCase("de").includes(wort)));
    };
  }

  window.Dash = { rendern, zeit };

  // ---------- Im Tool: einblenden, live nachführen, als Bericht speichern ----------
  if (!document.getElementById("dashboard-knopf")) return;       // im gespeicherten Bericht endet es hier
  const dash = { daten: null, warAktiv: false };

  // Das Dashboard beginnt unter der Kopfleiste; deren Höhe hängt von der Fensterbreite ab
  function kopfHoehe() {
    document.documentElement.style.setProperty("--kopf-hoehe", document.querySelector(".kopf").offsetHeight + "px");
  }
  window.addEventListener("resize", kopfHoehe);

  function oeffnen(auf) {
    kopfHoehe();
    $("#dashboard").hidden = !auf;
    $("#dashboard-knopf").setAttribute("aria-expanded", String(auf));
    $("#dashboard-knopf").classList.toggle("aktiv", auf);
    if (auf) laden();
    taktStellen();                                  // Analyse live nachführen, solange das Dashboard offen ist
  }

  async function laden() {
    $("#db-stand").textContent = "wird berechnet …";
    try {
      dash.daten = { ...(await holen("/api/dashboard")), live: true };
    } catch (e) {
      $("#db-stand").innerHTML = `<span class="fehler">${esc(e.message)}</span>`;
      return;
    }
    $("#db-stand").textContent = `Stand ${zeit(dash.daten.analyse.erstellt)}`;
    rendern(dash.daten, $("#db-inhalt"));
  }

  // Von erfassung.js nach jeder Abfrage des Laufs aufgerufen: Analysestand live, am Ende des Laufs alles neu
  window.dashboardLauf = () => {
    if ($("#dashboard").hidden || !dash.daten || !erf.stand) return;
    const aktiv = !!laufend();
    if (dash.warAktiv && !aktiv) laden();
    dash.warAktiv = aktiv;
    dash.daten = { ...dash.daten, erfassung: erf.stand };
    if (["Überblick", "Analyse"].includes(reiter) && !document.activeElement?.classList.contains("db-suche")) rendern(dash.daten, $("#db-inhalt"));
  };

  async function berichtSpeichern(knopf) {
    knopf.disabled = true;
    knopf.textContent = "wird gespeichert …";
    try {
      const r = await senden("/api/bericht", {});
      $("#db-bericht-info").innerHTML = `Gespeichert: <span class="mono">${esc(r.pfad)}</span>
        <button type="button" class="knopf-leise" data-aktion="finder">Im ${systemwort("dateimanager")} zeigen</button>`;
      $("#db-bericht-info").dataset.datei = r.datei;
    } catch (e) { meldung(e.message, "Fehler"); }
    knopf.disabled = false;
    knopf.textContent = "Als Bericht speichern";
  }

  $("#dashboard-knopf").onclick = () => oeffnen($("#dashboard").hidden);
  $("#db-zu").onclick = () => oeffnen(false);
  $("#db-neu").onclick = () => laden();
  $("#db-bericht").onclick = (e) => berichtSpeichern(e.currentTarget);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#dashboard").hidden) oeffnen(false); });
  $("#dashboard").addEventListener("click", async (e) => {
    const aktion = e.target.closest("[data-aktion]")?.dataset.aktion;
    if (aktion === "zum-lauf") { oeffnen(false); ansichtZeigen("erfassung"); }
    if (aktion === "finder") await senden("/api/bericht_zeigen", { datei: $("#db-bericht-info").dataset.datei }).catch((err) => meldung(err.message, "Fehler"));
    if (e.target === $("#dashboard")) oeffnen(false);                  // Klick neben die Fläche schließt
  });
})();

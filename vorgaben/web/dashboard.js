// Dashboard von Balduin (Notebook 1, I9 bettet diese Datei ein)
// - Tabellen: Suche, Sortieren per Klick auf die Spalte, Filter nach Platte, seitenweise; Links (z. B. nach Anton) anklickbar
// - Gruppen-Explorer: Klick auf eine Gruppe zeigt alle Dateien mit Vorschaubild
// - Ordnerbaum je Platte: aufklappbar, mit Anteil der Dateien, die auch in anderen Ordnern oder auf anderen Platten liegen
// - Diagramme in Reitern beim Umschalten an die Breite anpassen
(function () {
  "use strict";
  const ZEILEN_JE_SEITE = 50;
  const zahl = new Intl.NumberFormat("de-DE", { maximumFractionDigits: 2 });

  function element(tag, klasse, text) {
    const e = document.createElement(tag);
    if (klasse) e.className = klasse;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }

  function anzeigen(wert, istZahl) {
    if (wert === null || wert === undefined) return "";
    return istZahl && typeof wert === "number" ? zahl.format(wert) : String(wert);
  }

  // Tabellenzelle; Text, der mit https:// beginnt, wird zum Link (mehrere mit „ | “ getrennt, z. B. Fundstellen in Anton)
  function zelle(wert, istZahl) {
    if (typeof wert !== "string" || !wert.startsWith("https://")) {
      return element("td", istZahl ? "text-end" : "bd-text", anzeigen(wert, istZahl));
    }
    const td = element("td", "bd-text");
    wert.split(" | ").forEach((url, k) => {
      if (k) td.append(" | ");
      const objekt = url.match(/\/objects\/(\d+)/);
      const a = element("a", null, objekt ? "Objekt " + objekt[1] : url);
      a.href = url;
      a.target = "_blank";
      a.rel = "noopener";
      a.addEventListener("click", (e) => e.stopPropagation());
      td.appendChild(a);
    });
    return td;
  }

  function tabelle(behaelter) {
    const daten = JSON.parse(document.getElementById(behaelter.dataset.quelle).textContent);
    const spalten = daten.spalten, zahlen = daten.zahlen;
    const zeilen = daten.zeilen.map((z) => ({ z: z, text: z.join(" ").toLowerCase() }));
    const plattenSpalte = spalten.indexOf("Platte");
    const zustand = { suche: "", platte: "", sortiert: -1, aufsteigend: true, seite: 0 };

    const leiste = element("div", "d-flex flex-wrap gap-2 align-items-center mb-2");
    const suche = element("input", "form-control form-control-sm bd-suche");
    suche.type = "search";
    suche.placeholder = "Suchen …";
    leiste.appendChild(suche);
    let auswahl = null;
    if (plattenSpalte >= 0) {
      const platten = [...new Set(daten.zeilen.map((z) => z[plattenSpalte]))].sort();
      if (platten.length > 1) {
        auswahl = element("select", "form-select form-select-sm bd-auswahl");
        auswahl.appendChild(new Option("alle Platten", ""));
        platten.forEach((p) => auswahl.appendChild(new Option(p, p)));
        leiste.appendChild(auswahl);
      }
    }
    const zaehler = element("span", "text-body-secondary small ms-auto");
    leiste.appendChild(zaehler);

    const rahmen = element("div", "table-responsive bd-rahmen");
    const tab = element("table", "table table-sm table-hover align-middle mb-1 bd-tabelle");
    const kopf = element("thead");
    const kopfzeile = element("tr");
    spalten.forEach((s, i) => {
      const th = element("th", zahlen[i] ? "text-end" : "", s);
      th.title = "Klicken zum Sortieren";
      th.addEventListener("click", () => {
        zustand.aufsteigend = zustand.sortiert === i ? !zustand.aufsteigend : !zahlen[i];
        zustand.sortiert = i;
        zustand.seite = 0;
        zeichnen();
      });
      kopfzeile.appendChild(th);
    });
    kopf.appendChild(kopfzeile);
    const rumpf = element("tbody");
    tab.append(kopf, rumpf);
    rahmen.appendChild(tab);

    const blaettern = element("div", "d-flex gap-2 align-items-center small");
    const zurueck = element("button", "btn btn-sm btn-outline-secondary", "‹ zurück");
    const vor = element("button", "btn btn-sm btn-outline-secondary", "weiter ›");
    const seite = element("span", "text-body-secondary");
    blaettern.append(zurueck, seite, vor);
    behaelter.append(leiste, rahmen, blaettern);

    function gefiltert() {
      let liste = zeilen;
      if (zustand.suche) liste = liste.filter((r) => r.text.includes(zustand.suche));
      if (zustand.platte) liste = liste.filter((r) => r.z[plattenSpalte] === zustand.platte);
      if (zustand.sortiert >= 0) {
        const i = zustand.sortiert, f = zustand.aufsteigend ? 1 : -1;
        liste = [...liste].sort((a, b) => {
          const x = a.z[i], y = b.z[i];
          if (x === y) return 0;
          if (x === null || x === undefined) return 1;
          if (y === null || y === undefined) return -1;
          return (zahlen[i] ? x - y : String(x).localeCompare(String(y), "de")) * f;
        });
      }
      return liste;
    }

    function zeichnen() {
      const liste = gefiltert();
      const seiten = Math.max(1, Math.ceil(liste.length / ZEILEN_JE_SEITE));
      zustand.seite = Math.min(zustand.seite, seiten - 1);
      rumpf.replaceChildren();
      liste.slice(zustand.seite * ZEILEN_JE_SEITE, (zustand.seite + 1) * ZEILEN_JE_SEITE).forEach((r) => {
        const tr = element("tr");
        r.z.forEach((wert, i) => tr.appendChild(zelle(wert, zahlen[i])));
        if (daten.klick === "gruppe") {
          tr.classList.add("bd-klickbar");
          tr.addEventListener("click", () => {
            rumpf.querySelectorAll("tr.table-active").forEach((t) => t.classList.remove("table-active"));
            tr.classList.add("table-active");
            gruppeZeigen(r.z[0], behaelter);
          });
        }
        rumpf.appendChild(tr);
      });
      kopfzeile.querySelectorAll("th").forEach((th, i) => {
        th.dataset.sortiert = i === zustand.sortiert ? (zustand.aufsteigend ? "auf" : "ab") : "";
      });
      zaehler.textContent = zahl.format(liste.length) + " von " + zahl.format(zeilen.length) + " Zeilen";
      seite.textContent = "Seite " + (zustand.seite + 1) + " von " + seiten;
      zurueck.disabled = zustand.seite === 0;
      vor.disabled = zustand.seite >= seiten - 1;
      blaettern.hidden = seiten === 1;
    }

    suche.addEventListener("input", () => { zustand.suche = suche.value.trim().toLowerCase(); zustand.seite = 0; zeichnen(); });
    if (auswahl) auswahl.addEventListener("change", () => { zustand.platte = auswahl.value; zustand.seite = 0; zeichnen(); });
    zurueck.addEventListener("click", () => { zustand.seite--; zeichnen(); });
    vor.addEventListener("click", () => { zustand.seite++; zeichnen(); });
    zeichnen();
  }

  // Gruppen-Explorer: Mitglieder einer Duplikatgruppe mit Vorschaubild
  let gruppen = null;
  function gruppeZeigen(gruppeId, behaelter) {
    if (!gruppen) gruppen = JSON.parse(document.getElementById("gruppen-daten").textContent);
    const g = gruppen.mitglieder[gruppeId] || [];
    let feld = behaelter.querySelector(".bd-gruppe");
    if (!feld) {
      feld = element("div", "bd-gruppe mt-3");
      behaelter.appendChild(feld);
    }
    feld.replaceChildren(element("h3", "h6 mb-2", "Gruppe " + gruppeId + ": " + g.length + " Dateien"));
    const raster = element("div", "bd-kacheln");
    g.forEach((m) => {
      // m = [Platte, Pfad, Format, MB, Pixel, Ampel, Leitdatei, Vorschau]
      const kachel = element("figure", "bd-kachel" + (m[6] ? " bd-leit" : ""));
      if (m[7]) {
        const bild = element("img");
        bild.loading = "lazy";
        bild.src = gruppen.thumbs + "/" + m[7];
        bild.alt = "";
        bild.addEventListener("error", () => bild.replaceWith(element("div", "bd-ohne", "Vorschau nicht erreichbar (Arbeitsplatte angeschlossen?)")));
        kachel.appendChild(bild);
      } else {
        kachel.appendChild(element("div", "bd-ohne", "keine Vorschau"));
      }
      const text = element("figcaption");
      if (m[6]) text.appendChild(element("span", "badge text-bg-primary me-1", "Leitdatei"));
      if (m[5]) text.appendChild(element("span", "badge bd-ampel-" + m[5] + " me-1", m[5]));
      text.appendChild(element("div", "fw-semibold", m[0] + ": " + m[1]));
      text.appendChild(element("div", "text-body-secondary", [m[2], m[3] + " MB", m[4]].filter(Boolean).join(" · ")));
      kachel.appendChild(text);
      raster.appendChild(kachel);
    });
    feld.appendChild(raster);
    feld.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // Treemap wie GrandPerspective: jede Datei ein Rechteck, Fläche = Größe (oder 1 je Datei), Farbe = Duplikatart.
  // Daten: ordner = ["HD01/Bilder/2005", …], dateien = [[Ordnernummer, Name, Bytes, Art, überzählig, Gruppennummer], …]
  // Art: 0 einmalig, 1 exakt gleich, 2 Formatvariante, 3 beinahe gleich, 4 Systemdatei
  const TM_FARBEN = ["#dcdbd6", "#2a78d6", "#eb6834", "#1baf7a", "#9a9893"];
  const TM_NAMEN = ["einmalig", "exakt gleich", "Formatvariante", "beinahe gleich", "Systemdatei"];

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

  function treemap(behaelter) {
    const daten = JSON.parse(document.getElementById(behaelter.dataset.quelle).textContent);
    const dateien = daten.dateien;
    const wurzel = { name: "alle Platten", kinder: new Map(), dateien: [], eltern: null };
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
    const zustand = { flaeche: "groesse", faerben: "ueberzaehlig", aktuell: wurzel };
    if (wurzel.kinder.size === 1 && wurzel.dateien.length === 0) zustand.aktuell = [...wurzel.kinder.values()][0];

    // Bedienleiste, Pfadleiste, Legende, Zeichenfläche
    const leiste = element("div", "d-flex flex-wrap gap-3 align-items-center mb-2 small");
    function schalter(titel, optionen, schluessel) {
      const gruppe = element("div", "btn-group btn-group-sm");
      gruppe.setAttribute("role", "group");
      leiste.appendChild(element("span", "text-body-secondary", titel));
      Object.entries(optionen).forEach(([wert, text]) => {
        const knopf = element("button", "btn btn-outline-secondary" + (zustand[schluessel] === wert ? " active" : ""), text);
        knopf.addEventListener("click", () => {
          zustand[schluessel] = wert;
          gruppe.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === knopf));
          if (schluessel === "flaeche") summen(wurzel);
          zeichnen();
        });
        gruppe.appendChild(knopf);
      });
      leiste.appendChild(gruppe);
    }
    schalter("Fläche:", { groesse: "Größe", anzahl: "Anzahl" }, "flaeche");
    schalter("Einfärben:", { alle: "alle Exemplare", ueberzaehlig: "nur überzählige" }, "faerben");
    const legende = element("div", "d-flex flex-wrap gap-3 ms-auto");
    TM_NAMEN.forEach((n, i) => {
      const eintrag = element("span", "bd-legende");
      const feld = element("span", "bd-farbfeld");
      feld.style.background = TM_FARBEN[i];
      eintrag.append(feld, document.createTextNode(n));
      legende.appendChild(eintrag);
    });
    leiste.appendChild(legende);
    const pfadleiste = element("nav", "bd-pfadleiste small mb-2");
    const buehne = element("div", "bd-buehne");
    const leinwand = element("canvas"), auflage = element("canvas", "bd-auflage");
    const hinweis = element("div", "bd-hinweis");
    hinweis.hidden = true;
    buehne.append(leinwand, auflage, hinweis);
    behaelter.append(leiste, pfadleiste, buehne);

    function wert(i) { return zustand.flaeche === "groesse" ? dateien[i][2] : 1; }
    function summen(k) {
      let s = 0;
      k.dateien.forEach((i) => { s += wert(i); });
      k.kinder.forEach((c) => { s += summen(c); });
      k.summe = s;
      return s;
    }
    summen(wurzel);

    function farbe(i) {
      const d = dateien[i];
      if (zustand.faerben === "ueberzaehlig" && d[3] >= 1 && d[3] <= 3 && !d[4]) return TM_FARBEN[0];
      return TM_FARBEN[d[3]];
    }

    let blaetter = [], ordnerFelder = [], feldJeDatei = new Map();
    function zeichnen() {
      const breite = buehne.clientWidth, hoehe = buehne.clientHeight;
      if (!breite) return;
      const dpr = window.devicePixelRatio || 1;
      [leinwand, auflage].forEach((c) => {
        c.width = breite * dpr; c.height = hoehe * dpr;
        c.style.width = breite + "px"; c.style.height = hoehe + "px";
        c.getContext("2d").setTransform(dpr, 0, 0, dpr, 0, 0);
      });
      const ctx = leinwand.getContext("2d");
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, breite, hoehe);
      blaetter = []; ordnerFelder = []; feldJeDatei = new Map();
      knoten(ctx, zustand.aktuell, 0, 0, breite, hoehe, 0);
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
            ctx.strokeStyle = tiefe === 0 ? "#52514e" : "#a9a8a2";
            ctx.lineWidth = tiefe === 0 ? 1.5 : 1;
            ctx.strokeRect(x + 0.5, y + 0.5, w - 1, h - 1);
          }
        }
      });
    }

    function pfadVon(k) {
      const teile = [];
      for (let n = k; n && n !== wurzel; n = n.eltern) teile.unshift(n);
      return teile;
    }
    function pfadZeigen() {
      pfadleiste.replaceChildren();
      const kette = [wurzel, ...pfadVon(zustand.aktuell)];
      kette.forEach((k, i) => {
        if (i) pfadleiste.appendChild(document.createTextNode(" / "));
        if (k === zustand.aktuell) pfadleiste.appendChild(element("strong", "", k.name));
        else {
          const a = element("a", "", k.name);
          a.href = "#";
          a.addEventListener("click", (ev) => { ev.preventDefault(); zustand.aktuell = k; zeichnen(); });
          pfadleiste.appendChild(a);
        }
      });
      pfadleiste.appendChild(element("span", "text-body-secondary ms-2",
        "· " + (zustand.flaeche === "groesse" ? zahl.format(zustand.aktuell.summe / 1e9) + " GB" : zahl.format(zustand.aktuell.summe) + " Dateien")
        + " · Klick auf einen Ordner zoomt hinein"));
    }

    function treffer(liste, mx, my) {
      for (let k = liste.length - 1; k >= 0; k--) {
        const f = liste[k];
        if (mx >= f[0] && mx < f[0] + f[2] && my >= f[1] && my < f[1] + f[3]) return f;
      }
      return null;
    }
    function pfadDatei(i) { return daten.ordner[dateien[i][0]] + "/" + dateien[i][1]; }

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
        const andere = d[5] >= 0 ? mitglieder.get(d[5]) : [i];
        ctx.lineWidth = 2;
        andere.forEach((j) => {
          const b = feldJeDatei.get(j);
          if (b === undefined) return;
          const [x, y, w, h] = blaetter[b];
          ctx.strokeStyle = j === i ? "#0b0b0b" : "#e34948";
          ctx.strokeRect(x - 1, y - 1, Math.max(w, 3) + 2, Math.max(h, 3) + 2);
        });
        hinweis.replaceChildren(element("div", "fw-semibold", pfadDatei(i)),
          element("div", "", zahl.format(d[2] / 1e6) + " MB · " + TM_NAMEN[d[3]] + (d[3] >= 1 && d[3] <= 3 ? (d[4] ? " · überzählig" : " · Leitdatei") : "")));
        if (d[5] >= 0) {
          const liste = mitglieder.get(d[5]);
          hinweis.appendChild(element("div", "mt-1 text-body-secondary", "Gruppe " + daten.gruppen[d[5]] + ": " + liste.length + " Exemplare (rot umrandet, soweit im Ausschnitt)"));
          liste.slice(0, 8).forEach((j) => hinweis.appendChild(element("div", "bd-hinweis-pfad", (dateien[j][4] ? "· " : "★ ") + pfadDatei(j))));
          if (liste.length > 8) hinweis.appendChild(element("div", "text-body-secondary", "… und " + (liste.length - 8) + " weitere"));
        }
      }
      hinweis.hidden = false;
      const rechts = mx + 16 + hinweis.offsetWidth > buehne.clientWidth;
      hinweis.style.left = (rechts ? mx - 16 - hinweis.offsetWidth : mx + 16) + "px";
      hinweis.style.top = Math.min(my + 16, buehne.clientHeight - hinweis.offsetHeight - 4) + "px";
    });
    buehne.addEventListener("mouseleave", () => {
      hinweis.hidden = true; zuletzt = -1;
      auflage.getContext("2d").clearRect(0, 0, buehne.clientWidth, buehne.clientHeight);
    });
    buehne.addEventListener("click", (ev) => {
      const r = buehne.getBoundingClientRect();
      const f = treffer(ordnerFelder, ev.clientX - r.left, ev.clientY - r.top);
      if (f) { zustand.aktuell = f[4]; hinweis.hidden = true; zuletzt = -1; zeichnen(); }
    });
    new ResizeObserver(() => zeichnen()).observe(buehne);
  }

  // Ordnerbaum je Platte: aufklappbar; je Ordner (mit Unterordnern) Anteil der Dateien, die auch anderswo liegen.
  // Daten: ordner = [[Name, Eltern, Dateien, direkt, Bytes, ex_gleich, ex_gleich_b, ex_andere, ex_andere_b,
  //                   al_gleich, al_gleich_b, al_andere, al_andere_b, ex_platten, al_platten], …]; Eltern vor Kindern.
  // ex = nur exakt gleich, al = alle Duplikatarten; gleich = anderer Ordner dieser Platte, andere = andere Platten; _b = Bytes
  function ordnerbaum(behaelter) {
    const ordner = JSON.parse(document.getElementById(behaelter.dataset.quelle).textContent).ordner;
    const kinder = ordner.map(() => []), tiefe = ordner.map(() => 0);
    ordner.forEach((o, i) => { if (o[1] >= 0) { kinder[o[1]].push(i); tiefe[i] = tiefe[o[1]] + 1; } });
    const zustand = { art: "al", mass: "dateien", sortierung: "name", offen: new Set([0]) };

    const leiste = element("div", "d-flex flex-wrap gap-3 align-items-center mb-2 small");
    function schalter(titel, optionen, schluessel) {
      const gruppe = element("div", "btn-group btn-group-sm");
      leiste.appendChild(element("span", "text-body-secondary", titel));
      Object.entries(optionen).forEach(([wert, text]) => {
        const knopf = element("button", "btn btn-outline-secondary" + (zustand[schluessel] === wert ? " active" : ""), text);
        knopf.addEventListener("click", () => {
          zustand[schluessel] = wert;
          gruppe.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b === knopf));
          zeichnen();
        });
        gruppe.appendChild(knopf);
      });
      leiste.appendChild(gruppe);
    }
    schalter("Duplikate:", { al: "alle Arten", ex: "nur exakt gleich" }, "art");
    schalter("Anteil nach:", { dateien: "Dateien", bytes: "Größe" }, "mass");
    const sortierung = element("select", "form-select form-select-sm bd-auswahl");
    [["name", "nach Name"], ["groesse", "nach Größe"], ["gleich", "nach % andere Ordner"], ["andere", "nach % andere Platten"]]
      .forEach(([wert, text]) => sortierung.appendChild(new Option(text, wert)));
    sortierung.addEventListener("change", () => { zustand.sortierung = sortierung.value; zeichnen(); });
    leiste.appendChild(sortierung);
    const ebenen = element("div", "btn-group btn-group-sm ms-auto");
    [[1, "zuklappen"], [2, "2 Ebenen"], [3, "3 Ebenen"]].forEach(([n, text]) => {
      const knopf = element("button", "btn btn-outline-secondary", text);
      knopf.addEventListener("click", () => {
        zustand.offen = new Set(ordner.map((_, i) => i).filter((i) => tiefe[i] < n));
        zeichnen();
      });
      ebenen.appendChild(knopf);
    });
    leiste.appendChild(ebenen);

    const rahmen = element("div", "bd-baum");
    const kopf = element("div", "bd-baum-zeile bd-baum-kopf");
    ["Ordner", "Dateien", "GB", "auch in anderen Ordnern dieser Platte", "auch auf anderen Platten", "welche Platten"]
      .forEach((s, i) => kopf.appendChild(element("div", i === 1 || i === 2 ? "text-end" : "", s)));
    const rumpf = element("div");
    rahmen.append(kopf, rumpf);
    behaelter.append(leiste, rahmen);

    function werte(i) {
      const o = ordner[i], basis = zustand.art === "ex" ? 5 : 9, b = zustand.mass === "bytes" ? 1 : 0;
      return { gesamt: b ? o[4] : o[2], gleich: o[basis + b], andere: o[basis + 2 + b], platten: o[zustand.art === "ex" ? 13 : 14] };
    }
    function prozent(teil, gesamt) {
      if (!gesamt || !teil) return 0;
      return (100 * teil) / gesamt;
    }
    function prozentText(p) {
      if (p === 0) return "–";
      if (p < 1) return "< 1 %";
      if (p > 99 && p < 100) return "> 99 %";
      return Math.round(p) + " %";
    }
    function anteil(p, klasse) {
      const zelle = element("div", "bd-baum-anteil");
      const balken = element("div", "bd-baum-balken"), fuellung = element("div", klasse);
      fuellung.style.width = p + "%";
      balken.appendChild(fuellung);
      zelle.append(balken, element("span", "", prozentText(p)));
      return zelle;
    }
    function pfad(i) {
      const teile = [];
      for (let k = i; k >= 0; k = ordner[k][1]) teile.unshift(ordner[k][0]);
      return teile.join("/");
    }
    function sortiert(liste) {
      const s = zustand.sortierung;
      if (s === "name") return [...liste].sort((a, b) => ordner[a][0].localeCompare(ordner[b][0], "de", { numeric: true }));
      const schluessel = (i) => {
        const w = werte(i);
        return s === "groesse" ? ordner[i][4] : prozent(s === "gleich" ? w.gleich : w.andere, w.gesamt);
      };
      return [...liste].sort((a, b) => schluessel(b) - schluessel(a));
    }

    function zeile(i) {
      const o = ordner[i], w = werte(i), offen = zustand.offen.has(i), hatKinder = kinder[i].length > 0;
      const z = element("div", "bd-baum-zeile" + (hatKinder ? " bd-klickbar" : ""));
      z.title = pfad(i) + "\n" + zahl.format(o[2]) + " Dateien, davon " + zahl.format(o[3]) + " direkt im Ordner, "
        + kinder[i].length + " Unterordner";
      const name = element("div", "bd-baum-name");
      name.style.paddingLeft = tiefe[i] * 18 + "px";
      name.append(element("span", "bd-baum-pfeil", hatKinder ? (offen ? "▾" : "▸") : ""),
        element("span", tiefe[i] === 0 ? "fw-semibold" : "", o[0]));
      const gb = o[4] > 0 && o[4] < 5e6 ? "< 0,01" : zahl.format(o[4] / 1e9);
      z.append(name, element("div", "text-end", zahl.format(o[2])), element("div", "text-end", gb),
        anteil(prozent(w.gleich, w.gesamt), "bd-baum-gleich"), anteil(prozent(w.andere, w.gesamt), "bd-baum-andere"),
        element("div", "text-body-secondary", w.platten));
      if (hatKinder) {
        z.addEventListener("click", () => {
          if (offen) zustand.offen.delete(i); else zustand.offen.add(i);
          zeichnen();
        });
      }
      return z;
    }
    function zeichnen() {
      const zeilen = [];
      (function anhaengen(i) {
        zeilen.push(zeile(i));
        if (zustand.offen.has(i)) sortiert(kinder[i]).forEach(anhaengen);
      })(0);
      rumpf.replaceChildren(...zeilen);
    }
    zeichnen();
  }

  document.querySelectorAll(".bd-tabelle-behaelter").forEach(tabelle);
  document.querySelectorAll(".bd-treemap").forEach(treemap);
  document.querySelectorAll(".bd-baum-behaelter").forEach(ordnerbaum);

  // Diagramme in verborgenen Reitern haben noch keine Breite: beim Anzeigen neu berechnen
  document.querySelectorAll('button[data-bs-toggle="tab"]').forEach((knopf) => {
    knopf.addEventListener("shown.bs.tab", () => {
      const ziel = document.querySelector(knopf.dataset.bsTarget);
      ziel.querySelectorAll(".js-plotly-plot").forEach((d) => window.Plotly.Plots.resize(d));
    });
  });
})();

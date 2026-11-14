// Eastereggs der Sprachvarianten (Entscheidungen 05. und 13.11.2026, docs/plan.md): Österreich „skartieren“ statt
// „kassieren“, Schweiz „ss“ statt „ß“.
// Still im Hintergrund, ohne Schalter: gilt, wenn der Server die Seite als lang="de-AT" ausliefert (Systemregion
// Österreich) oder der Browser de-AT unter seinen Sprachen nennt. Geändert wird nur angezeigter Text (auch Meldungen
// des Servers und Rückfragen), nie Werte: Eingabefelder, value und data-* bleiben, die Datenbank schreibt „kassieren“.
// Erster Baustein einer Internationalisierung: weitere Wörter kommen als Zeilen in WOERTER dazu.

// Wortstamm → österreichische Entsprechung (ohne Anfangsbuchstaben „k“, der wird zu „s“ + Rest)
const WOERTER = [
  [/k(assier)/gi, "kartier"],            // kassieren, kassiert, Kassiertes, kassierte …
  [/k(assation)/gi, "kartierung"],       // Kassation, Kassationen, Kassationsliste …
];

// Ersetzt in einem Text; Groß- und Kleinschreibung wie im Original (Kassieren → Skartieren, KASSIEREN → SKARTIEREN)
function skartieren(text) {
  if (!text || !/kass/i.test(text)) return text;
  for (const [muster, ersatz] of WOERTER) {
    text = text.replace(muster, (treffer, rest) => {
      const gross = rest === rest.toUpperCase();
      return (treffer[0] === "K" ? "S" : "s") + (gross ? ersatz.toUpperCase() : ersatz);
    });
  }
  return text;
}

// Schweiz: kein ß (auch nicht das große ẞ)
function schweizern(text) {
  if (!text || !/[ßẞ]/.test(text)) return text;
  return text.replace(/ß/g, "ss").replace(/ẞ/g, "SS");
}

if (typeof module !== "undefined") module.exports = { skartieren, schweizern };   // für die Tests (tests/test_sprache.py)

if (typeof document !== "undefined") (() => {
  const sprachen = navigator.languages || [navigator.language || ""];
  const lang = document.documentElement.lang;
  const variante = (v) => lang === v || sprachen.some((l) => l.toLowerCase() === v.toLowerCase());
  // Österreich vor der Schweiz, falls der Browser beide nennt
  const ersetzen = variante("de-AT") ? skartieren : variante("de-CH") ? schweizern : null;
  if (!ersetzen) return;
  const betroffen = ersetzen === skartieren ? /kass/i : /[ßẞ]/;

  const UNBERUEHRT = new Set(["SCRIPT", "STYLE", "TEXTAREA", "INPUT"]);   // Werte und Eingaben bleiben
  const ATTRIBUTE = ["title", "placeholder", "aria-label"];

  const knotenText = (n) => {
    if (n.parentNode && (UNBERUEHRT.has(n.parentNode.nodeName) || n.parentNode.isContentEditable)) return;
    const neu = ersetzen(n.nodeValue);
    if (neu !== n.nodeValue) n.nodeValue = neu;
  };
  const element = (el) => {
    if (UNBERUEHRT.has(el.nodeName)) return;
    for (const a of ATTRIBUTE) {
      const alt = el.getAttribute(a);
      if (alt && betroffen.test(alt)) el.setAttribute(a, ersetzen(alt));
    }
  };
  const durchgehen = (wurzel) => {
    if (wurzel.nodeType === Node.TEXT_NODE) return knotenText(wurzel);
    if (wurzel.nodeType !== Node.ELEMENT_NODE) return;
    element(wurzel);
    const gang = document.createTreeWalker(wurzel, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    for (let n = gang.nextNode(); n; n = gang.nextNode()) n.nodeType === Node.TEXT_NODE ? knotenText(n) : element(n);
  };

  // Was die Module später einsetzen (innerHTML, textContent), wird beim Einfügen angepasst
  new MutationObserver((aenderungen) => {
    for (const a of aenderungen) {
      if (a.type === "childList") a.addedNodes.forEach(durchgehen);
      else if (a.type === "characterData") knotenText(a.target);
      else if (a.type === "attributes") element(a.target);
    }
  }).observe(document.documentElement, { childList: true, subtree: true, characterData: true,
                                         attributes: true, attributeFilter: ATTRIBUTE });

  // Rückfragen und Meldungen (dialoge.js) sind Seitentext und laufen über den Beobachter oben

  const start = () => { durchgehen(document.body); document.title = ersetzen(document.title); };
  document.readyState === "loading" ? document.addEventListener("DOMContentLoaded", start) : start();
})();

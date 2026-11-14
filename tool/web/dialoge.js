// Rückfragen und Meldungen im Stil von Balduin statt confirm()/alert() des Browsers (Entscheidung 13.11.2026).
// Sie sehen in allen Modulen gleich aus, nennen Balduin statt „127.0.0.1 meldet“ und gehen auch dort, wo der
// Browser oder ein eingebettetes Programmfenster eigene Dialoge unterdrückt. Beide geben ein Promise zurück:
// was nach der Antwort geschehen soll, steht hinter „await“.
//   if (!(await rueckfrage("Löschen?", "Erklärung …", "Löschen"))) return;
//   meldung(err.message, "Fehler");

let dialogKette = Promise.resolve();     // mehrere zugleich: nacheinander zeigen, nie einen überschreiben

function dialogZeigen({ titel, text, ja, nein, eingabe = false }) {
  const zeigen = () => new Promise((fertig) => {
    const teil = (id) => document.getElementById(id);
    const dlg = teil("frage-dialog"), ok = teil("frage-ok"), ab = teil("frage-abbrechen"), feld = teil("frage-eingabe");
    teil("frage-titel").textContent = titel;
    teil("frage-text").textContent = text || "";           // Text, kein HTML; Zeilenumbrüche zeigt das CSS
    teil("frage-text").hidden = !text;
    ok.textContent = ja;
    ab.textContent = nein || "";
    ab.hidden = !nein;
    if (feld) {
      feld.value = "";                                           // nie einen früheren Wert zeigen
      feld.hidden = !eingabe;
    }
    const zu = (wert) => {
      ok.onclick = ab.onclick = dlg.oncancel = null;
      const text = feld ? feld.value : "";
      if (feld) feld.value = "";                                 // Passwort nicht im Feld stehen lassen
      dlg.close();
      fertig(eingabe ? (wert ? text : null) : wert);
    };
    ok.onclick = (ev) => { ev.preventDefault(); zu(true); };
    ab.onclick = () => zu(false);
    dlg.oncancel = (ev) => { ev.preventDefault(); zu(false); };   // Esc = Abbrechen
    dlg.showModal();
    if (eingabe && feld) feld.focus();
    else if (!nein) ok.focus();                                  // Meldung: Eingabetaste schließt
  });
  const p = dialogKette.then(zeigen);
  dialogKette = p.catch(() => {});
  return p;
}

// Rückfrage: Frage als Titel, Erklärung darunter; true = Hauptknopf, false = Abbrechen oder Esc
function rueckfrage(frage, erklaerung = "", ja = "OK", nein = "Abbrechen") {
  return dialogZeigen({ titel: frage, text: erklaerung, ja, nein });
}

// Meldung (Fehler, Hinweis) mit nur „OK“; das Promise erfüllt sich beim Schließen
function meldung(text, titel = "Hinweis") {
  return dialogZeigen({ titel, text: String(text ?? ""), ja: "OK" }).then(() => undefined);
}

// Passwort eines verschlüsselten Datenträgers (13.11.2026): Antwort der eingegebene Text oder null (Abbrechen).
// Balduin speichert es nicht; es geht nur an den einen Lauf.
function passwortFragen(frage, erklaerung = "") {
  return dialogZeigen({ titel: frage, text: erklaerung, ja: "Entsperren und starten", nein: "Abbrechen", eingabe: true });
}

// Passwort erfragen und gleich prüfen (Feedback 14.11.2026): Ein falsches fällt hier auf, nicht erst im Lauf; dann
// fragt Balduin noch einmal. Antwort: das geprüfte Passwort oder null (abgebrochen). pruefen(pw) → {ok, meldung}.
async function passwortGeprueft(frage, erklaerung, pruefen) {
  let hinweis = "";
  for (;;) {
    const pw = await passwortFragen(frage, hinweis + erklaerung);
    if (!pw) return null;
    let antwort;
    try { antwort = await pruefen(pw); }
    catch (err) { await meldung(err.message, "Passwort nicht geprüft"); return null; }
    if (antwort.ok) return pw;
    hinweis = `${antwort.meldung} Bitte noch einmal eingeben.\n\n`;
  }
}

// Klicks und Tasten im Dialog nicht an die Seite weiterreichen: sonst schließen Einstellungen dahinter (Klick
// außerhalb) oder Esc hebt nebenbei die Auswahl im Baum auf
if (typeof window !== "undefined") {
  window.addEventListener("DOMContentLoaded", () => {
    const dlg = document.getElementById("frage-dialog");
    for (const art of ["click", "pointerdown", "keydown"]) dlg?.addEventListener(art, (ev) => ev.stopPropagation());
  });
}

if (typeof module !== "undefined") module.exports = { rueckfrage, meldung, passwortFragen, passwortGeprueft };

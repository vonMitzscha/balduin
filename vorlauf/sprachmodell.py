"""Vorschlag vom Sprachmodell auf Abruf (Erschließung, kein Lauf; Entscheidungen 03.11.2026 in docs/plan.md).

Für einen Ordner: Pfadabschnitte, Namen der übernommenen Dateien (Auswahl), Daten und eingebettete Titel. Für ein
Dokument zusätzlich die Titelkandidaten und der Anfang des Textes (E4). Das Modell antwortet nach festem JSON-Schema
mit Temperatur 0; jeder Wert braucht einen **wörtlichen Beleg** aus der Eingabe, sonst verwirft ihn der Code, ebenso
Wertungen und Füllwörter. Ergebnis: Vorschläge (schritt „LLM“) am Ordner bzw. an der Datei, nie Werte.

Nur lokal (harte Regel 6): Anbieter „ollama“ unter 127.0.0.1/localhost; Cloud-Anbieter bleiben gesperrt, bis das
Archiv sie freigibt. Jede Anfrage steht im Protokoll (Abschnitt „Sprachmodell“, Anbieter und Modell).
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from erfassung.basis import P, db, jetzt, protokolliere
from erfassung.texte import text_holen
from .gemeinsam import TEXT_ENDUNGEN, bereinigen, datum_deutsch, endung, name_von, norm
from .metadaten import dokumenttitel

VORGABE = {"anbieter": "ollama", "adresse": "http://127.0.0.1:11434", "modell": "qwen2.5:14b"}
LOKAL = {"127.0.0.1", "localhost", "::1"}
VERBOTEN = {"impressionen", "eindruecke", "verschiedene", "diverse", "diverses", "sonstiges", "allgemein",
            "unbekannt", "various", "impressions", "miscellaneous", "schoene", "tolle", "wunderbare", "spannende"}
MAX_DATEIEN = 40
MAX_TEXT = 2500

SCHEMA = {"type": "object", "properties": {
    "titel": {"type": "string"}, "beleg_titel": {"type": "string"},
    "inhalt": {"type": "string"}, "beleg_inhalt": {"type": "string"},
    "datum": {"type": "string"}, "beleg_datum": {"type": "string"}},
    "required": ["titel", "beleg_titel", "inhalt", "beleg_inhalt", "datum", "beleg_datum"]}

ANWEISUNG = """Du hilfst bei der Erschließung in einem Archiv. Du bekommst Angaben zu einem Ordner oder Dokument von
einem Datenträger. Antworte nur mit JSON nach dem Schema. Regeln:
- titel: kurzer, konkreter deutscher Titel (höchstens 10 Wörter), z. B. Anlass, Ort, Jahr. Keine Wertungen, keine
  Füllwörter wie „Impressionen“ oder „verschiedene“. Wenn nichts Konkretes erkennbar ist: "".
- inhalt: ein sachlicher Satz, was zu sehen oder zu lesen ist, nur aus den Angaben. Sonst "".
- datum: TT.MM.JJJJ, MM.JJJJ oder JJJJ, nur wenn es in den Angaben steht. Sonst "".
- beleg_…: die Stelle aus den Angaben, wörtlich kopiert, auf die sich der Wert stützt.
Erfinde nichts. Lieber "" als eine Vermutung."""


def einstellung():
    e = {**VORGABE, **(P.einstellungen.get("sprachmodell") or {})}
    host = urllib.parse.urlparse(e["adresse"]).hostname or ""
    if e["anbieter"] != "ollama" or host not in LOKAL:
        raise ValueError("Nur ein lokales Sprachmodell (Ollama auf diesem Rechner) ist freigegeben; Cloud-Modelle "
                         "bleiben gesperrt, bis das Archiv sie freigibt.")
    return e


def modelle():
    """Verfügbare Modelle des lokalen Ollama (für das Zahnrad)."""
    e = einstellung()
    try:
        with urllib.request.urlopen(e["adresse"].rstrip("/") + "/api/tags", timeout=10) as a:
            namen = [m["name"] for m in json.load(a).get("models", [])]
    except (urllib.error.URLError, TimeoutError, OSError) as f:
        return {"erreichbar": False, "fehler": str(getattr(f, "reason", f)), "modelle": [], **e}
    return {"erreichbar": True, "modelle": namen, **e}


def eingabe_bauen(platte, pfad, dateien):
    """Text der Anfrage: nur Pfadabschnitte, Dateinamen, Daten, Titel und (bei Dokumenten) der Textanfang."""
    with db() as con:
        etikett = (con.execute("SELECT etikett_text FROM platte WHERE platte_id = ?", (platte,)).fetchone() or [""])[0]
        zeilen = [f"Datenträger: {platte}" + (f", Etikett „{etikett}“" if etikett else ""),
                  "Pfad: " + (" / ".join(pfad.split("/")) if pfad else "(oberste Ebene)")]
        auswahl = dateien[:MAX_DATEIEN]
        if dateien == [pfad]:                               # ein Dokument
            r = dateien[0]
            sha = (con.execute("SELECT sha256 FROM datei WHERE platte_id = ? AND relpfad = ?", (platte, r)).fetchone() or [None])[0]
            z = con.execute("SELECT titel FROM volltext WHERE sha256 = ? AND endung = ?", (sha, endung(r))).fetchone()
            kandidaten = dokumenttitel(z[0]) if z else []
            if kandidaten:
                zeilen.append("Titelkandidaten: " + " | ".join(t for t, _, _ in kandidaten))
            text = text_holen(sha, endung(r)) if sha and endung(r) in TEXT_ENDUNGEN else None
            if text:
                zeilen.append("Textanfang: " + " ".join(text.split())[:MAX_TEXT])
        else:
            zeilen.append(f"Dateien ({len(dateien)}, Auswahl): " + ", ".join(name_von(r) for r in auswahl))
        daten, titel = [], []
        for r in auswahl:
            z = con.execute("SELECT datum, datum_quelle, titel FROM metadaten WHERE platte_id = ? AND relpfad = ?",
                            (platte, r)).fetchone()
            if z and z[0]:
                daten.append((z[0][:10], z[1]))
            if z and bereinigen(z[2]):
                titel.append(bereinigen(z[2]))
    if daten:
        tage = sorted(d for d, _ in daten)
        zeilen.append(f"Daten der Dateien: {datum_deutsch(tage[0])} bis {datum_deutsch(tage[-1])} "
                      f"(Quelle meist {max(set(q for _, q in daten), key=[q for _, q in daten].count)})")
    if titel:
        zeilen.append("Eingebettete Titel: " + " | ".join(dict.fromkeys(titel)))
    return "\n".join(zeilen)


def belegt(wert, beleg, eingabe):
    """Beleg wörtlich in der Eingabe und mindestens ein inhaltliches Wort des Werts im Beleg oder in der Eingabe."""
    if not wert or not beleg or norm(beleg) not in norm(eingabe):
        return False
    worte = [w for w in norm(wert).replace(",", " ").split() if len(w) >= 4]
    return bool(worte) and sum(w in norm(eingabe) for w in worte) >= max(1, len(worte) // 2)


def vorschlag(platte, pfad, dateien):
    """Fragt das lokale Modell; schreibt geprüfte Werte als Vorschläge (schritt LLM) und gibt alles zurück."""
    e = einstellung()
    eingabe = eingabe_bauen(platte, pfad, dateien)
    anfrage = {"model": e["modell"], "stream": False, "format": SCHEMA, "options": {"temperature": 0},
               "messages": [{"role": "system", "content": ANWEISUNG}, {"role": "user", "content": eingabe}]}
    beginn = time.time()
    protokolliere("Sprachmodell", f"{platte}:{pfad}", "anfrage", "", f"{e['anbieter']} {e['modell']} (lokal)")
    try:
        req = urllib.request.Request(e["adresse"].rstrip("/") + "/api/chat", data=json.dumps(anfrage).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as a:
            antwort = json.loads(json.load(a)["message"]["content"])
    except (urllib.error.URLError, TimeoutError, OSError) as f:
        raise RuntimeError(f"Ollama antwortet nicht ({e['adresse']}): {getattr(f, 'reason', f)}. "
                           "Läuft Ollama? (Programm öffnen oder „ollama serve“)") from None
    except (ValueError, KeyError) as f:
        raise RuntimeError(f"Antwort des Modells nicht lesbar: {f}") from None
    dauer = round(time.time() - beginn, 1)
    ergebnis, verworfen, zeilen = {}, [], []
    quelle = f"Sprachmodell ({e['modell']})"
    for feld in ("titel", "inhalt", "datum"):
        wert = " ".join(str(antwort.get(feld) or "").split())
        beleg = " ".join(str(antwort.get(f"beleg_{feld}") or "").split())
        if not wert:
            continue
        if any(w in VERBOTEN for w in norm(wert).split()):
            verworfen.append({"feld": feld, "wert": wert, "grund": "Wertung oder Füllwort"})
            continue
        if feld != "datum" and not belegt(wert, beleg, eingabe):
            verworfen.append({"feld": feld, "wert": wert, "grund": "ohne wörtlichen Beleg in den Angaben"})
            continue
        if feld == "datum":
            if not wert.replace(".", "").isdigit() or norm(wert) not in norm(eingabe).replace("-", "."):
                if not (len(wert) == 4 and wert in eingabe):
                    verworfen.append({"feld": feld, "wert": wert, "grund": "Datum steht so nicht in den Angaben"})
                    continue
            ziel, wert_db = "zeitraum", json.dumps([wert, "", False], ensure_ascii=False)
        else:
            ziel, wert_db = feld, wert
        ergebnis[ziel] = {"wert": wert, "beleg": beleg}
        zeilen.append((platte, pfad, ziel, wert_db, quelle, 0.55, f"Beleg: „{beleg}“" if beleg else "", "LLM", None, None, jetzt()))
    with db() as con:
        con.execute("DELETE FROM vorschlag WHERE schritt = 'LLM' AND platte_id = ? AND pfad = ?", (platte, pfad))
        con.executemany("INSERT OR REPLACE INTO vorschlag (platte_id, pfad, feld, wert, quelle, score, beleg, schritt, "
                        "anton_id, anton_name, zeit) VALUES (?,?,?,?,?,?,?,?,?,?,?)", zeilen)
    protokolliere("Sprachmodell", f"{platte}:{pfad}", "antwort", "",
                  f"{len(zeilen)} Vorschläge, {len(verworfen)} verworfen, {dauer} s")
    return {"vorschlaege": ergebnis, "verworfen": verworfen, "dauer": dauer, "modell": e["modell"], "eingabe": eingabe}

"""V3 Sujet: Bildinhalte auf den Vorschaubildern der übernommenen Fotos erkennen (Entscheidung 04.11.2026).

OpenCLIP ViT-B/32 (LAION-2B, ONNX-Export von Immich, modelle/clip_bild.onnx und clip_text.onnx) vergleicht jedes
Vorschaubild mit englischen Texten „a photo of …“. Zwei Arten von Texten:
- Anton-Schlagworte mit Wikidata-Verknüpfung: ihre englische Bezeichnung kommt von Wikidata (hinaus gehen nur die
  Wikidata-IDs, harte Regel 6, jede Abfrage protokolliert). Ein Treffer wird **Schlagwortvorschlag** mit Score
  (Datei; Ordner, wenn die meisten Fotos darin ihn teilen).
- eine allgemeine englische Begriffsliste (vorgaben/sujet_begriffe.csv): die besten Treffer stehen als **Sujet**
  (englisch, Kontext, kein Vorschlag) in der Tabelle sujet.
Rechnet nur auf Vorschaubildern (keine Quellplatte nötig). Bildmerkmale je Inhalt (SHA-256) bleiben gespeichert;
ein neuer Vokabularstand rechnet nur die Texte neu. Unterbrechbar (KeyboardInterrupt), danach fortsetzbar.
"""
import csv
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

import numpy as np
from PIL import Image

from erfassung.basis import MODELLE, P, db, fortschritt, jetzt, protokolliere, zeige
from .gemeinsam import elternordner, stand_schreiben, umfang, vorschlaege_ersetzen

# EINSTELLUNG V3
KENNUNG = "openclip-vit-b-32-laion2b"   # steht in sujet_bild.modell; ändert sie sich, rechnet V3 alle Bilder neu
ARTEN = ("bild", "raw")                  # Vorschau-Arten der Fotos (wie F5)
VORLAGE = "a photo of {}"                # Text, mit dem jeder Begriff verglichen wird
SKALA = 100.0                            # CLIP-Logit-Skala (Softmax über alle Texte)
SUJET_MIN, SUJET_ANZAHL = 0.08, 5        # Sujet als Kontext (Softmax nur über die allgemeine Liste): Anteil mindestens,
                                         # höchstens so viele je Bild; der beste Begriff steht immer da
SUJET_VORSCHLAG = 0.15                   # Sujet deutsch als Vorschlag (Schlagwort, Form und Inhalt) ab diesem Anteil
VORSCHLAG_MIN, VORSCHLAG_RANG = 0.20, 3  # Schlagwortvorschlag: Anteil mindestens und unter den besten so vielen
ANTEIL_ORDNER = 0.6                      # Ordnervorschlag, wenn so viele der Fotos direkt darin ihn teilen (mind. 2)
WIKIDATA = "https://www.wikidata.org/w/api.php"
BEGRIFFE = "sujet_begriffe.csv"          # allgemeine Liste in vorgaben/ (Projektkopie geht vor)
MITTEL = np.array([0.48145466, 0.4578275, 0.40821073], np.float32)
STREUUNG = np.array([0.26862954, 0.26130258, 0.27577711], np.float32)


# ---------- Tokenizer (CLIP-BPE aus modelle/clip_tokenizer.json, ohne zusätzliches Paket) ----------

def _bytes_zu_zeichen():
    """Byte → Unicode-Zeichen wie im byte-level BPE von GPT-2/CLIP (druckbare Bytes bleiben, die übrigen werden verschoben)."""
    bs = list(range(ord("!"), ord("~") + 1)) + list(range(ord("¡"), ord("¬") + 1)) + list(range(ord("®"), ord("ÿ") + 1))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return dict(zip(bs, map(chr, cs)))


class Tokenizer:
    START, ENDE, LAENGE = 49406, 49407, 77
    # wie der Pre-Tokenizer von CLIP: Endungen 's 't …, Buchstabenfolgen, einzelne Ziffern, übrige Zeichenfolgen
    MUSTER = re.compile(r"'s|'t|'re|'ve|'m|'ll|'d|[^\W\d_]+|\d|[^\s\w]+|_+", re.UNICODE)

    def __init__(self, pfad):
        t = json.loads(pfad.read_text(encoding="utf-8"))
        self.vokabular = t["model"]["vocab"]
        merges = [tuple(m.split()) if isinstance(m, str) else tuple(m) for m in t["model"]["merges"]]
        self.rang = {m: i for i, m in enumerate(merges)}
        self.zeichen = _bytes_zu_zeichen()
        self.zwischen = {}

    def bpe(self, wort):
        if wort in self.zwischen:
            return self.zwischen[wort]
        teile = list(wort[:-1]) + [wort[-1] + "</w>"]
        while len(teile) > 1:
            paare = [(self.rang.get((a, b), 1 << 30), i) for i, (a, b) in enumerate(zip(teile, teile[1:]))]
            r, i = min(paare)
            if r == 1 << 30:
                break
            a, b = teile[i], teile[i + 1]
            neu, j = [], 0
            while j < len(teile):                       # alle Vorkommen des Paars zusammenziehen
                if j < len(teile) - 1 and teile[j] == a and teile[j + 1] == b:
                    neu.append(a + b)
                    j += 2
                else:
                    neu.append(teile[j])
                    j += 1
            teile = neu
        self.zwischen[wort] = teile
        return teile

    def __call__(self, text):
        text = " ".join(html.unescape(text).split()).lower()
        ids = []
        for wort in self.MUSTER.findall(text):
            w = "".join(self.zeichen[b] for b in wort.encode("utf-8"))
            ids += [self.vokabular[t] for t in self.bpe(w) if t in self.vokabular]
        ids = [self.START] + ids[:self.LAENGE - 2] + [self.ENDE]
        return np.array([ids + [0] * (self.LAENGE - len(ids))], np.int32)


# ---------- Modelle ----------

def sitzungen():
    from erfassung.personen import sitzung          # gleiche Wahl des Rechenwerks wie F5 (CoreML, DirectML, CPU)
    for name in ("clip_bild.onnx", "clip_text.onnx", "clip_tokenizer.json"):
        if not (MODELLE / name).exists():
            raise FileNotFoundError(f"Modell {name} fehlt. Laden mit: .venv/bin/python werkzeuge/modelle_laden.py")
    return sitzung("clip_bild"), sitzung("clip_text"), Tokenizer(MODELLE / "clip_tokenizer.json")


def bild_vorbereiten(bild):
    """Kürzere Seite auf 224 (bikubisch), Mitte 224 × 224 ausschneiden, normalisieren, CHW."""
    bild = bild.convert("RGB")
    f = 224 / min(bild.width, bild.height)
    bild = bild.resize((max(224, round(bild.width * f)), max(224, round(bild.height * f))), Image.Resampling.BICUBIC)
    links, oben = (bild.width - 224) // 2, (bild.height - 224) // 2
    a = np.asarray(bild.crop((links, oben, links + 224, oben + 224)), np.float32) / 255.0
    return ((a - MITTEL) / STREUUNG).transpose(2, 0, 1)[None]


def normiert(v):
    v = np.asarray(v, np.float32).reshape(-1)
    return v / (np.linalg.norm(v) + 1e-9)


# ---------- Englische Bezeichnungen aus Wikidata (nur IDs gehen hinaus) ----------

def wikidata_englisch():
    """Holt für Anton-Schlagworte mit Wikidata-Verknüpfung die englische Bezeichnung, soweit sie fehlt.
    Gibt die Zahl der Abfragen zurück; ohne Netz geht es mit dem Vorhandenen weiter."""
    with db() as con:
        offen = {}
        for anton_id, wd in con.execute(
                "SELECT b.anton_id, b.wikidata FROM anton_begriff b LEFT JOIN begriff_englisch e "
                "ON e.art = b.art AND e.anton_id = b.anton_id WHERE b.art = 'keyword' AND b.wikidata IS NOT NULL "
                "AND b.wikidata != '' AND e.anton_id IS NULL"):
            m = re.search(r"Q\d+", wd or "")
            if m:
                offen[anton_id] = m[0]
    if not offen:
        return 0
    ids = sorted(set(offen.values()))
    labels, abfragen, gefragt = {}, 0, set()
    for i in range(0, len(ids), 50):
        teil = ids[i:i + 50]
        fortschritt(0.02 + 0.08 * i / len(ids), f"Englische Bezeichnungen aus Wikidata · {i:,} von {len(ids):,}")
        adresse = WIKIDATA + "?" + urllib.parse.urlencode({"action": "wbgetentities", "ids": "|".join(teil),
                                                            "props": "labels", "languages": "en", "format": "json"})
        d = None
        for versuch in range(4):              # Wikidata drosselt schnelle Folgen (HTTP 429): warten und wiederholen
            try:
                anfrage = urllib.request.Request(adresse, headers={"User-Agent": "Balduin (Archiv, Erschliessung; lokal)"})
                with urllib.request.urlopen(anfrage, timeout=30) as r:
                    d = json.load(r)
                break
            except urllib.error.HTTPError as f:
                if f.code not in (429, 503) or versuch == 3:
                    break
                time.sleep(min(60, int(f.headers.get("Retry-After") or 0) or 5 * (versuch + 1)))
            except OSError:
                break
        if d is None:
            zeige("Wikidata nicht erreichbar oder lehnt ab; es geht mit den vorhandenen Bezeichnungen weiter "
                  "(beim nächsten Lauf werden die übrigen nachgeholt).")
            break
        time.sleep(1)                         # höflicher Abstand zwischen den Abfragen
        abfragen += 1
        gefragt.update(teil)
        protokolliere("V3", "Wikidata", "abfrage", "", f"{len(teil)} IDs ({teil[0]} …), nur IDs, englische Bezeichnungen")
        for q, e in (d.get("entities") or {}).items():
            label = ((e.get("labels") or {}).get("en") or {}).get("value")
            if label:
                labels[q] = label
    zeit = jetzt()
    with db() as con:
        con.executemany("INSERT OR REPLACE INTO begriff_englisch VALUES (?,?,?,?,?)",
                        [("keyword", a, q, labels.get(q, ""), zeit) for a, q in offen.items() if q in gefragt])
    return abfragen


def allgemeine_begriffe():
    """Allgemeine englische Begriffsliste (Kopie im Projekt geht vor): {englisch: Gruppe}."""
    for ort in (P.ordner / "vorgaben" / BEGRIFFE, MODELLE.parent / "vorgaben" / BEGRIFFE):
        if ort.exists():
            with open(ort, encoding="utf-8") as f:
                return {z["begriff"].strip(): (z.get("gruppe") or "").strip() for z in csv.DictReader(f)
                        if (z.get("begriff") or "").strip()}
    return {}


# ---------- Übersetzung der Begriffsliste (Entscheidung 04.11.2026) ----------
# Übersetzt wird immer die ganze allgemeine Liste, nie einzelne Treffer: so verrät keine Anfrage etwas über den Bestand.
SPRACHEN = {"de": "German", "fr": "French", "it": "Italian", "en": "English", "es": "Spanish", "nl": "Dutch"}
ARTIKEL = re.compile(r"^(der|die|das|ein|eine|einen|einem|einer|eines|den|dem|des|le|la|les|un|une|il|lo|gli|una)\s+", re.I)


def aufraeumen(text):
    """Antwort als Schlagwort: ohne Artikel, Satzzeichen am Rand und Klammerzusätze; erster Buchstabe groß."""
    t = re.sub(r"\s+", " ", re.sub(r"[\[\]\(\)\"„“?!.,;:•…]+", " ", text or "")).strip(" -")
    t = ARTIKEL.sub("", t).strip()
    return t[:1].upper() + t[1:] if t else ""


def mit_sprachmodell(begriffe, sprache, sichern=None, fortschritt_von=0.02, fortschritt_bis=0.1):
    """Übersetzt Begriffe mit der Schnittstelle des Sprachmodells (Zahnrad der Erschließung; nur lokal freigegeben)."""
    from . import sprachmodell
    e = sprachmodell.einstellung()
    schema = {"type": "object", "properties": {"t": {"type": "array", "items": {"type": "object", "properties": {
        "en": {"type": "string"}, "ziel": {"type": "string"}}, "required": ["en", "ziel"]}}}, "required": ["t"]}
    erg = {}
    for i in range(0, len(begriffe), 40):
        teil = begriffe[i:i + 40]
        fortschritt(fortschritt_von + (fortschritt_bis - fortschritt_von) * i / len(begriffe),
                    f"Sujet-Begriffe übersetzen ({e['modell']}) · {i:,} von {len(begriffe):,}")
        aufgabe = (f"Translate each English image-content term into a {SPRACHEN.get(sprache, sprache)} archival keyword: "
                   "a noun or short noun phrase as used in library and archive catalogues, no article, normal spelling "
                   "with spaces between words, singular unless the term is plural. Return JSON "
                   "{\"t\": [{\"en\": …, \"ziel\": …}]} with every term exactly once.\n" + "\n".join(teil))
        anfrage = {"model": e["modell"], "stream": False, "format": schema, "options": {"temperature": 0},
                   "messages": [{"role": "user", "content": aufgabe}]}
        req = urllib.request.Request(e["adresse"].rstrip("/") + "/api/chat", data=json.dumps(anfrage).encode(),
                                     headers={"Content-Type": "application/json"})
        block = {}
        with urllib.request.urlopen(req, timeout=900) as a:
            for x in json.loads(json.load(a)["message"]["content"]).get("t", []):
                if x.get("en", "").strip() in teil:
                    block[x["en"].strip()] = aufraeumen(x.get("ziel"))
        erg.update(block)
        if sichern:                                      # jeder fertige Block sofort: ein Abbruch verliert nichts
            sichern(block, f"sprachmodell:{e['modell']}")
    return erg, f"sprachmodell:{e['modell']}"


def mit_mymemory(begriffe, sprache, email="", sichern=None):
    """Übersetzt Begriffe einzeln mit MyMemory (kostenlos, ohne Schlüssel; mit E-Mail höheres Tageskontingent)."""
    erg = {}
    for i, b in enumerate(begriffe):
        if i % 20 == 0:
            if sichern and i:
                sichern({b_: erg[b_] for b_ in begriffe[i - 20:i] if b_ in erg}, "mymemory")
            fortschritt(0.02 + 0.08 * i / len(begriffe), f"Sujet-Begriffe übersetzen (MyMemory) · {i:,} von {len(begriffe):,}")
        q = {"q": b, "langpair": f"en|{sprache}", **({"de": email} if email else {})}
        anfrage = urllib.request.Request("https://api.mymemory.translated.net/get?" + urllib.parse.urlencode(q),
                                         headers={"User-Agent": "Balduin (Archiv, Erschliessung)"})
        with urllib.request.urlopen(anfrage, timeout=30) as a:
            d = json.load(a)
        if str(d.get("responseStatus")) == "200":
            erg[b] = aufraeumen(d["responseData"]["translatedText"])
        time.sleep(0.3)
    return erg, "mymemory"


def uebersetzungen(begriffe):
    """{englisch: Übersetzung} für die Begriffsliste in der Sprache des Archivs; fehlende werden übersetzt und
    gespeichert (geprüfte bleiben). Englisch als Zielsprache: die Begriffe selbst ohne Artikel."""
    e = {"weg": "sprachmodell", "sprache": "de", "email": "", **(P.einstellungen.get("uebersetzung") or {})}
    sprache = e["sprache"] or "de"
    if sprache == "en":
        return {b: aufraeumen(b) for b in begriffe}
    with db() as con:
        da = {z[0]: z[1] for z in con.execute("SELECT text, uebersetzung FROM begriff_uebersetzung WHERE sprache = ?",
                                               (sprache,))}
    fehlt = [b for b in begriffe if b not in da]
    if fehlt:
        gesichert = Counter()

        def sichern(teil, weg):
            teil = {b: w for b, w in teil.items() if w}
            if not teil:
                return
            with db() as con:
                con.executemany("INSERT OR IGNORE INTO begriff_uebersetzung VALUES (?,?,?,?,0,?)",
                                [(b, sprache, w, weg, jetzt()) for b, w in teil.items()])
            da.update(teil)
            gesichert[weg] += len(teil)
        try:
            neu, weg = (mit_mymemory(fehlt, sprache, e["email"], sichern) if e["weg"] == "mymemory"
                        else mit_sprachmodell(fehlt, sprache, sichern))
            sichern(neu, weg)                                # Rest (INSERT OR IGNORE: schon Gesichertes bleibt)
        except (OSError, ValueError, KeyError, RuntimeError) as f:
            zeige(f"Übersetzung der Sujet-Begriffe nicht vollständig ({f}); der Rest folgt beim nächsten Lauf.")
        for weg, n in gesichert.items():
            protokolliere("V3", "Übersetzung", sprache, "", f"{n} Begriffe der allgemeinen Liste über {weg}")
    return {b: da[b] for b in begriffe if da.get(b)}


def anton_schlagworte():
    """Anton-Schlagworte nach normalisiertem Namen und Alternativnamen → (anton_id, name)."""
    from .gemeinsam import norm
    erg = {}
    with db() as con:
        for i, n, alt in con.execute("SELECT anton_id, name, alternativ FROM anton_begriff WHERE art = 'keyword'"):
            for x in [n] + json.loads(alt or "[]"):
                erg.setdefault(norm(x), (i, n))
    return erg


def textmerkmale(s_text, tok, texte):
    """Merkmale je Text, zwischengespeichert in sujet_text (nur neue Texte werden gerechnet)."""
    with db() as con:
        da = {t: np.frombuffer(v, np.float16).astype(np.float32) for t, v in con.execute(
            "SELECT text, vektor FROM sujet_text WHERE modell = ?", (KENNUNG,))}
    neu = [t for t in texte if t not in da]
    for i, t in enumerate(neu):
        if i % 50 == 0:
            fortschritt(0.1 + 0.05 * i / len(neu), f"Texte für den Vergleich · {i:,} von {len(neu):,}")
        da[t] = normiert(s_text.run(None, {"text": tok(VORLAGE.format(t))})[0])
    if neu:
        with db() as con:
            con.executemany("INSERT OR REPLACE INTO sujet_text VALUES (?,?,?)",
                            [(t, KENNUNG, da[t].astype(np.float16).tobytes()) for t in neu])
    return np.stack([da[t] for t in texte]) if texte else np.zeros((0, 512), np.float32)


# ---------- Ablauf ----------

def sujet_erkennen(umfang_art=""):
    """V3: Bildmerkmale der übernommenen Fotos (soweit neu), dann Vergleich mit Anton-Schlagworten (englisch über
    Wikidata) und der allgemeinen Liste; schreibt Sujet (Kontext) und Schlagwortvorschläge."""
    beginn = time.time()
    dateien = umfang()
    with db() as con:
        vorschau = {}
        for sha, datei in con.execute(f"SELECT sha256, datei FROM vorschau WHERE art IN ({','.join('?' * len(ARTEN))}) "
                                      "AND datei IS NOT NULL AND datei != ''", ARTEN):
            vorschau[sha] = datei
        sha_von = {}
        for p, r, sha in con.execute("SELECT platte_id, relpfad, sha256 FROM datei"):
            sha_von[(p, r)] = sha
        # fertig nur mit Merkmalen: Bilder, die beim letzten Mal nicht lesbar waren, kommen wieder dran
        fertig = {z[0] for z in con.execute("SELECT sha256 FROM sujet_bild WHERE modell = ? AND vektor IS NOT NULL",
                                            (KENNUNG,))}
    fotos = [(p, r, sha_von.get((p, r))) for p, r in dateien if sha_von.get((p, r)) in vorschau]
    shas = sorted({sha for _, _, sha in fotos})
    offen = [s for s in shas if s not in fertig]
    zeige(f"V3 Sujet: {len(fotos):,} Fotos ({len(shas):,} Inhalte), davon {len(offen):,} noch ohne Bildmerkmale.")
    # zuerst übersetzen: braucht keine Vorschaubilder, bleibt also auch bei fehlender Arbeitsplatte gespeichert
    allgemein = list(allgemeine_begriffe())
    deutsch = uebersetzungen(allgemein)          # englisch → Sprache des Archivs (Name „deutsch“ der Kürze halber)
    if offen and not P.vorschauen.is_dir():         # Arbeitsplatte fehlt: abbrechen statt jedes Bild als Fehler
        ort = P.arbeitsplatte.name if getattr(P, "arbeitsplatte", None) else "Projektordner"
        raise RuntimeError(f"Die Vorschaubilder sind nicht erreichbar ({P.vorschauen}). Bitte den Datenträger "
                           f"„{ort}“ anschließen und den Schritt „Sujet“ erneut ausführen.")
    s_bild, s_text, tok = sitzungen()

    # 1 Texte: allgemeine Liste und Anton-Schlagworte mit englischer Bezeichnung
    abfragen = wikidata_englisch()
    with db() as con:
        anton = [(a, n, en) for a, n, en in con.execute(
            "SELECT b.anton_id, b.name, e.englisch FROM anton_begriff b JOIN begriff_englisch e ON e.art = b.art "
            "AND e.anton_id = b.anton_id WHERE b.art = 'keyword' AND e.englisch != ''")]
    texte = list(dict.fromkeys(allgemein + [en for _, _, en in anton]))
    t_merkmale = textmerkmale(s_text, tok, texte)
    index = {t: i for i, t in enumerate(texte)}
    anton_je_text = defaultdict(list)
    for a, n, en in anton:
        anton_je_text[en].append((a, n))
    allgemein_menge = set(allgemein)

    # 2 Bilder: Merkmale je Inhalt, gespeichert (unterbrechbar)
    erledigt = fehler = 0
    start = letzte = time.monotonic()
    unterbrochen = False
    with db() as con:
        try:
            for sha in offen:
                text_fehler, vektor = None, None
                try:
                    with Image.open(P.vorschauen / vorschau[sha]) as bild:
                        vektor = normiert(s_bild.run(None, {"image": bild_vorbereiten(bild)})[0])
                except (OSError, ValueError) as f:
                    text_fehler, fehler = str(f)[:200] or type(f).__name__, fehler + 1
                con.execute("INSERT OR REPLACE INTO sujet_bild VALUES (?,?,?,?,?)",
                            (sha, vektor.astype(np.float16).tobytes() if vektor is not None else None, KENNUNG,
                             text_fehler, jetzt()))
                erledigt += 1
                if time.monotonic() - letzte > 2:
                    con.commit()
                    letzte = time.monotonic()
                    rest = (letzte - start) / erledigt * (len(offen) - erledigt) / 60
                    fortschritt(0.15 + 0.75 * erledigt / len(offen),
                                f"{erledigt:,}/{len(offen):,} Fotos · noch etwa {max(1, round(rest))} min")
        except KeyboardInterrupt:
            unterbrochen = True
    if unterbrochen:
        protokolliere("V3", "Sujet", "bilder", "", f"{erledigt} Fotos, unterbrochen")
        raise KeyboardInterrupt

    # 3 Vergleich: Sujet (Kontext) je Inhalt, Schlagwortvorschläge je Datei und Ordner
    fortschritt(0.92, "Vergleiche Bilder mit den Begriffen")
    with db() as con:
        b_merkmale = {s: np.frombuffer(v, np.float16).astype(np.float32) for s, v in con.execute(
            "SELECT sha256, vektor FROM sujet_bild WHERE modell = ? AND vektor IS NOT NULL", (KENNUNG,)) if s in set(shas)}
    sujet_zeilen, treffer_je_sha = [], {}
    if texte and b_merkmale:
        reihen = list(b_merkmale)
        matrix = np.stack([b_merkmale[s] for s in reihen]) @ t_merkmale.T * SKALA
        matrix = np.exp(matrix - matrix.max(1, keepdims=True))
        matrix /= matrix.sum(1, keepdims=True)
        # Kontext für sich: Softmax nur über die allgemeine Liste (sonst verdrängen die vielen Anton-Begriffe sie)
        nur = [index[t] for t in allgemein if t in index]
        allg = np.stack([b_merkmale[s] for s in reihen]) @ t_merkmale[nur].T * SKALA if nur else None
        if allg is not None:
            allg = np.exp(allg - allg.max(1, keepdims=True))
            allg /= allg.sum(1, keepdims=True)
        for nr, (zeile, sha) in enumerate(zip(matrix, reihen)):
            beste = np.argsort(-zeile)[:VORSCHLAG_RANG * 3]
            kontext = []
            if allg is not None:
                for j, i in enumerate(np.argsort(-allg[nr])[:SUJET_ANZAHL]):
                    if j == 0 or allg[nr][i] >= SUJET_MIN:
                        en = texte[nur[i]]
                        kontext.append((en, round(float(allg[nr][i]), 3), deutsch.get(en, "")))
            sujet_zeilen.append((sha, json.dumps(kontext, ensure_ascii=False), KENNUNG, jetzt()))
            treffer_je_sha[sha] = [(texte[i], float(zeile[i])) for i in beste[:VORSCHLAG_RANG]
                                   if texte[i] in anton_je_text and zeile[i] >= VORSCHLAG_MIN]
    with db() as con:
        con.execute("DELETE FROM sujet WHERE modell != ?", (KENNUNG,))
        con.executemany("INSERT OR REPLACE INTO sujet VALUES (?,?,?,?)", sujet_zeilen)

    zeilen, je_ordner, fotos_je_ordner = [], defaultdict(Counter), Counter()
    # Sujet deutsch als Vorschlag (Entscheidung 04.11.2026): Schlagworte (Anton-Treffer über den Namen, sonst neu) und
    # Form und Inhalt „Bildinhalt: …“; je Datei aus dem Kontext, je Ordner, wenn die meisten Fotos ihn teilen
    # Jedes übersetzte Sujetwort des Kontexts wird gegen die Anton-Schlagworte abgeglichen (gelernt, exakt,
    # Alternativname, Wortform wie V8); ein Treffer ist Vorschlag auch unter der Schwelle für neue Begriffe
    from .normdaten import Vokabular
    vok = Vokabular()
    in_anton = {}
    for de in set(deutsch.values()):
        t_ = vok.treffer("keyword", de)
        if t_:
            in_anton[de] = (t_[0][0], vok.name("keyword", t_[0][0]))
    kontext_je = {s[0]: json.loads(s[1]) for s in sujet_zeilen}
    sujet_ordner = defaultdict(Counter)
    for p, r, sha in fotos:
        kontext = [(en, sc, de) for en, sc, de in kontext_je.get(sha, []) if de]
        gut = [(en, sc, de) for en, sc, de in kontext if sc >= SUJET_VORSCHLAG][:3]
        for en, sc, de in kontext:
            a_id, a_name = in_anton.get(de, (None, None))
            if not a_id and (en, sc, de) not in gut:
                continue
            zeilen.append((p, r, "schlagwort", a_name or de, "Sujet", round(sc, 2), f"Bildinhalt: „{de}“ ({en})", a_id, a_name))
            sujet_ordner[(p, elternordner(r))][(de, en)] += 1
        if gut:
            zeilen.append((p, r, "inhalt", "Bildinhalt: " + ", ".join(de for _, _, de in gut), "Sujet",
                           round(gut[0][1], 2), "Bildinhalt (Sujet, OpenCLIP)"))
    for p, r, sha in fotos:
        fotos_je_ordner[(p, elternordner(r))] += 1
        for en, score in treffer_je_sha.get(sha, []):
            for anton_id, name in anton_je_text[en]:
                zeilen.append((p, r, "schlagwort", name, "Sujet", round(score, 2),
                               f"Bildinhalt: „{en}“ (Wikidata)", anton_id, name))
                je_ordner[(p, elternordner(r))][(anton_id, name, en)] += 1
    for (p, o), zaehler in je_ordner.items():
        for (anton_id, name, en), n in zaehler.items():
            if n >= 2 and n / fotos_je_ordner[(p, o)] >= ANTEIL_ORDNER:
                zeilen.append((p, o, "schlagwort", name, "Sujet", round(n / fotos_je_ordner[(p, o)], 2),
                               f"Bildinhalt: „{en}“ auf {n} von {fotos_je_ordner[(p, o)]} Fotos", anton_id, name))
    for (p, o), zaehler in sujet_ordner.items():
        gemeinsam = [(de, en, n) for (de, en), n in zaehler.most_common(3)
                     if n >= 2 and n / fotos_je_ordner[(p, o)] >= ANTEIL_ORDNER]
        for de, en, n in gemeinsam:
            a_id, a_name = in_anton.get(de, (None, None))
            zeilen.append((p, o, "schlagwort", a_name or de, "Sujet", round(n / fotos_je_ordner[(p, o)], 2),
                           f"Bildinhalt: „{en}“ auf {n} von {fotos_je_ordner[(p, o)]} Fotos", a_id, a_name))
        if gemeinsam:
            zeilen.append((p, o, "inhalt", "Bildinhalt: " + ", ".join(de for de, _, _ in gemeinsam), "Sujet",
                           round(gemeinsam[0][2] / fotos_je_ordner[(p, o)], 2), "Bildinhalt der meisten Fotos (Sujet)"))
    geschrieben = vorschlaege_ersetzen("V3", zeilen)
    mit = len({(p, r) for p, r, *_ in zeilen if (p, r) in set(dateien)})
    kennzahlen = {"fotos": len(fotos), "neu": erledigt, "fehler": fehler, "mit_vorschlag": mit,
                  "anton_englisch": len(anton), "allgemein": len(allgemein), "wikidata_abfragen": abfragen}
    stand_schreiben("V3", [(p, r) for p, r, _ in fotos], mit, kennzahlen, beginn, umfang_art)
    protokolliere("V3", "Sujet", "lauf", "", json.dumps(kennzahlen, ensure_ascii=False))
    zeige(f"V3 fertig: {len(fotos):,} Fotos, {erledigt:,} neu gerechnet, {geschrieben:,} Schlagwortvorschläge "
          f"({len(anton):,} Anton-Schlagworte mit englischer Bezeichnung).")
    return kennzahlen

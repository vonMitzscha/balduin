"""V7 Metadaten verteilen: Vorschläge für Titel, Form und Inhalt, Urheber:in, Ort und Schlagworte aus dem, was
Registrierung/Analyse gespeichert hat (metadaten, exif_voll, Titelkandidaten aus E4). Liest keine Originale.

Regeln (allgemein, keine bestandsbezogenen Listen):
- Unbrauchbares verwirft gemeinsam.bereinigen (Kameratexte, Platzhalter, Dateinamen, Benutzerkürzel, Software-Copyright).
- Ein Titel oder eine Beschreibung, die in mehr als VORLAGE_ORDNER Ordnern vorkommt, gilt als Vorlage (Intranetseiten,
  Präsentationsvorlagen) und wird verworfen.
- Dokumente: bester Titelkandidat aus E4 (eingebettet, größte Schrift auf Seite 1, Folie, Überschrift, Lesezeichen,
  HTML-Titel, erste Zeile), höchstens drei.
- Schlagwortlisten mit mehr als KURZE_LISTE Einträgen (Bildagenturen) liefern nur Kandidaten für V8, die dort einen
  Anton-Treffer brauchen.
- Ordner: ein Wert, den mindestens ANTEIL_ORDNER der Dateien direkt darin teilen (mind. 2), wird auch Vorschlag am Ordner.
"""
import json
import time
import zlib
from collections import Counter, defaultdict

from erfassung.basis import db, fortschritt, zeige
from .gemeinsam import (TEXT_ENDUNGEN, bereinigen, elternordner, endung, norm, stand_schreiben, umfang,
                        vorschlaege_ersetzen)

VORLAGE_ORDNER = 15
VORLAGE_INHALTE = 20          # gleicher Dokumenttitel in mehr als so vielen verschiedenen Inhalten: Vorlage
ROLLEN = {"fotografie", "fotograf", "fotografin", "photography", "photographer", "photo", "foto", "design", "grafik",
          "graphic", "illustration", "text", "layout", "agentur", "agency"}
KURZE_LISTE = 8
ANTEIL_ORDNER = 0.6
# Orte aus IPTC/XMP (Reihenfolge: genauer zuerst); Sub-location oft eine Adresse, daher nur als Beleg
ORT_FELDER = ["IPTC:City", "XMP:City", "XMP:Location", "IPTC:Sub-location", "IPTC:Province-State", "XMP:State",
              "IPTC:Country-PrimaryLocationName", "XMP:Country"]
# Score je Quelle eines Dokumenttitels (E4, erfassung/texte.py)
TITEL_QUELLE = {"eingebettet": (0.7, "eingebetteter Titel"), "schrift": (0.65, "größte Schrift, Seite 1"),
                "folie": (0.6, "Titel der ersten Folie"), "ueberschrift": (0.6, "Formatvorlage Überschrift"),
                "lesezeichen": (0.55, "erstes Lesezeichen"), "html_titel": (0.5, "HTML-Titel"),
                "erste_zeile": (0.4, "erste Zeile")}


def personname(text):
    """Urheber:in: erster Teil vor „;“, ohne „Foto:“/„©“, nur mit Buchstaben und höchstens fünf Wörtern."""
    t = bereinigen(text)
    if not t:
        return ""
    t = t.split(";")[0].strip()
    if "," in t and norm(t.rsplit(",", 1)[1]).strip() in ROLLEN:     # „Markus Bertschi, Fotografie“
        t = t.rsplit(",", 1)[0].strip()
    for vorsatz in ("foto:", "photo:", "fotos:", "©", "(c)", "copyright"):
        if norm(t).startswith(vorsatz):
            t = t[len(vorsatz):].strip(" :,")
    return t if t and len(t.split()) <= 5 and len(t) <= 60 else ""


def dokumenttitel(titel_json):
    """Titelkandidaten aus volltext.titel → [(titel, score, beleg)], beste zuerst, höchstens drei."""
    try:
        kandidaten = json.loads(titel_json or "[]")
    except ValueError:
        return []
    erg = []
    for k in kandidaten:
        q = k.get("quelle")
        if q not in TITEL_QUELLE:
            continue
        t = bereinigen(k.get("text"))
        if not t or len(t) < 4 or len(t) > 160 or len(t.split()) > 18:
            continue
        score, beleg = TITEL_QUELLE[q]
        if q == "schrift" and k.get("groesse"):
            score = min(score + min(float(k["groesse"]) / 400, 0.1), 0.75)
        erg.append((t, round(score, 2), beleg))
    erg.sort(key=lambda x: -x[1])
    gesehen, beste = set(), []
    for t, s, b in erg:
        if norm(t) not in gesehen:
            gesehen.add(norm(t))
            beste.append((t, s, b))
    return beste[:3]


def metadaten_verteilen(umfang_art=""):
    beginn = time.time()
    dateien = umfang()
    menge = set(dateien)
    with db() as con:
        meta = {(z[0], z[1]): z[2:] for z in con.execute(
            "SELECT platte_id, relpfad, titel, beschreibung, urheber, schlagworte, gps_breite, gps_laenge, kamera, hersteller "
            "FROM metadaten")
            if (z[0], z[1]) in menge}
        info = {(z[0], z[1]): (z[2], z[3] or "") for z in con.execute("SELECT platte_id, relpfad, sha256, mime FROM datei")
                if (z[0], z[1]) in menge}
    # Werte je Datei sammeln: (feld, wert, quelle, score, beleg)
    roh = defaultdict(list)
    for (p, r), m in meta.items():
        titel, beschreibung, urheber, schlagworte, breite, laenge, kamera, hersteller = m
        geraet = [norm(x) for x in (kamera, hersteller) if x and len(x) >= 4]
        t = bereinigen(titel)
        if t and endung(r) not in TEXT_ENDUNGEN:            # Dokumente: Titel aus E4 (enthält den eingebetteten)
            roh[(p, r)].append(("titel", t, "Metadaten (Titel)", 0.5, "eingebetteter Titel"))
        b = bereinigen(beschreibung)
        if b and any(g in norm(b) for g in geraet):        # Kameramodell statt Beschreibung
            b = ""
        if b and len(b.split()) >= 3:
            roh[(p, r)].append(("inhalt", b, "Metadaten (Beschreibung)", 0.6, "eingebettete Beschreibung"))
        u = personname(urheber)
        if u:
            roh[(p, r)].append(("akteur", u, "Metadaten (Urheber:in)", 0.5, f"Urheber:in „{u}“"))
        liste = [w.strip() for w in (schlagworte or "").replace(",", ";").split(";") if bereinigen(w.strip())]
        quelle = "Metadaten (Schlagworte)" if len(liste) <= KURZE_LISTE else "Metadaten (lange Schlagwortliste)"
        for w in liste[:80]:
            roh[(p, r)].append(("schlagwort", w, quelle, 0.5 if len(liste) <= KURZE_LISTE else 0.3, "eingebettetes Schlagwort"))
        if breite is not None and laenge is not None:
            roh[(p, r)].append(("gps", json.dumps([round(breite, 5), round(laenge, 5)]), "GPS", 0.6, "GPS-Position"))
    # Orte aus der vollständigen ExifTool-Ausgabe (nur Bilder; je Inhalt einmal entpackt)
    bilder = defaultdict(list)
    for k, (sha, mime) in info.items():
        if sha and mime.startswith("image/"):
            bilder[(sha, endung(k[1]))].append(k)
    dokumente = defaultdict(list)
    for k, (sha, _) in info.items():
        if sha and endung(k[1]) in TEXT_ENDUNGEN:
            dokumente[(sha, endung(k[1]))].append(k)
    with db() as con:
        for i, z in enumerate(con.execute("SELECT sha256, endung, daten FROM exif_voll")):
            ziele = bilder.get((z[0], z[1]))
            if not ziele or not z[2]:
                continue
            if i % 2000 == 0:
                fortschritt(0.3, f"Orte aus den Metadaten · {i:,}")
            d = json.loads(zlib.decompress(z[2]))
            for feld in ORT_FELDER:
                o = bereinigen(d.get(feld))
                if o:
                    ort = o.split(",")[0].strip()
                    for k in ziele:
                        roh[k].append(("ort", ort, f"Metadaten ({feld.split(':')[1]})", 0.6, f"{feld} „{o}“"))
                    break
        fortschritt(0.6, "Titel der Dokumente")
        for sha, end, titel in con.execute("SELECT sha256, endung, titel FROM volltext WHERE titel IS NOT NULL"):
            ziele = dokumente.get((sha, end))
            if not ziele:
                continue
            for t, s, b in dokumenttitel(titel):
                for k in ziele:
                    roh[k].append(("titel", t, "Text des Dokuments", s, b))
    # Vorlagen: gleicher Titel/gleiche Beschreibung in vielen Ordnern
    ordner_je_wert = defaultdict(set)
    for (p, r), werte in roh.items():
        for feld, wert, *_ in werte:
            if feld in ("titel", "inhalt"):
                ordner_je_wert[(feld, norm(wert))].add((p, elternordner(r)))
    vorlage = {k for k, o in ordner_je_wert.items() if len(o) > VORLAGE_ORDNER}
    inhalte_je_titel = defaultdict(set)                  # Dokumenttitel: in wie vielen verschiedenen Inhalten
    for (p, r), werte in roh.items():
        for feld, wert, quelle, *_ in werte:
            if feld == "titel" and quelle == "Text des Dokuments":
                inhalte_je_titel[norm(wert)].add(info[(p, r)][0])
    vorlage |= {("titel", w) for w, s in inhalte_je_titel.items() if len(s) > VORLAGE_INHALTE}
    zeilen, mit_ergebnis, verworfen = [], 0, 0
    je_ordner = defaultdict(Counter)
    dateien_je_ordner = Counter((p, elternordner(r)) for p, r in dateien)
    for (p, r), werte in roh.items():
        brauchbar = False
        for feld, wert, quelle, score, beleg in werte:
            if (feld, norm(wert)) in vorlage:
                verworfen += 1
                continue
            zeilen.append((p, r, feld, wert, quelle, score, beleg))
            brauchbar = brauchbar or feld != "gps"
            if feld in ("akteur", "ort", "schlagwort", "titel", "inhalt"):
                je_ordner[(p, elternordner(r))][(feld, wert, quelle)] += 1
        mit_ergebnis += brauchbar
    # gemeinsame Werte der Dateien eines Ordners auch am Ordner vorschlagen
    for (p, o), zaehler in je_ordner.items():
        n = dateien_je_ordner[(p, o)]
        for (feld, wert, quelle), k in zaehler.items():
            if k >= 2 and k / n >= ANTEIL_ORDNER and not (feld == "titel" and quelle == "Text des Dokuments"):
                zeilen.append((p, o, feld, wert, quelle, round(0.6 * k / n, 2), f"{k} von {n} Dateien im Ordner"))
    n = vorschlaege_ersetzen("V7", zeilen)
    fortschritt(1, f"{len(dateien):,} Dateien")
    zeige(f"V7: {len(dateien):,} Dateien, {mit_ergebnis:,} mit Vorschlag, {verworfen:,} Vorlagenwerte verworfen; {n:,} Vorschläge")
    stand_schreiben("V7", dateien, mit_ergebnis, {"vorschlaege": n, "vorlagen": verworfen,
                                                  "felder": dict(Counter(z[2] for z in zeilen))}, beginn, umfang_art)
    return {"dateien": len(dateien), "mit_ergebnis": mit_ergebnis}

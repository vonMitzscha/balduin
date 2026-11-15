"""F5 Personen auf Fotos: erkennt Menschen und Gesichter auf den Vorschaubildern (vor der Bewertung, optional je Projekt).

Rechnet nur auf den Vorschaubildern von Fotos (Art bild und raw, 400 px), nicht auf den Originalen; die Quellplatte
muss dafür nicht angeschlossen sein. Zwei Modelle über ONNX Runtime (auf dem Mac mit CoreML, sonst auf der CPU):
YOLOX-s findet Personen, YuNet Gesichter. Daraus folgt der Bildtyp: „porträt“ (ein großes Gesicht), „personen“
(sonst Menschen im Bild) oder leer. Ergebnis je Inhalt (SHA-256) in der Tabelle personen; die Bewertung zeigt daraus
nur ein Symbol und eine Anzeige-Option, entschieden wird nichts (docs/plan.md, Entscheidungen 30.10. und 03.11.2026).
Keine Identität: gespeichert werden nur Anzahlen und Größen.
"""
from PIL import Image

from .basis import *  # noqa: F401,F403

# EINSTELLUNG F5
MODELL = "yolox_s"           # Datei modelle/<MODELL>.onnx (werkzeuge/modelle_laden.py)
GESICHT_MODELL = "yunet"     # Datei modelle/<GESICHT_MODELL>.onnx
KENNUNG = f"{MODELL}+{GESICHT_MODELL}"   # steht in personen.modell; ändert sie sich, rechnet F5 alles neu
EINGABE = 640                # Kantenlänge, mit der beide Modelle rechnen
SCHWELLE = 0.5               # ab diesem Score zählt eine Person
UEBERLAPPUNG = 0.45          # stärker überlappende Rahmen gelten als dieselbe Person (Non-Maximum Suppression)
SCHWELLE_GESICHT = 0.9       # ab diesem Score zählt ein Gesicht (Vorgabe von OpenCV für YuNet)
UEBERLAPPUNG_GESICHT = 0.3   # wie UEBERLAPPUNG, für Gesichter
PORTRAET_HOEHE = 0.12        # Porträt: größtes Gesicht mindestens so hoch, als Anteil an der Bildhöhe …
PORTRAET_ABSTAND = 0.5       # … und kein zweites Gesicht höher als dieser Anteil des größten
ARTEN = ("bild", "raw")      # nur Fotos und Scans; Filme, PDFs und Grafiken nicht
# Rechenwerke in dieser Reihenfolge, soweit vorhanden: Mac (Neural Engine/GPU), Windows (jede GPU), NVIDIA, CPU
ANBIETER = ["CoreMLExecutionProvider", "DmlExecutionProvider", "CUDAExecutionProvider", "CPUExecutionProvider"]


def sitzung(name=MODELL):
    """Lädt ein Modell. Fehlt es, steht im Fehler, wie man es holt."""
    import onnxruntime as ort
    pfad = MODELLE / f"{name}.onnx"
    if not pfad.exists():
        raise FileNotFoundError(f"Modell {pfad.name} fehlt. Laden mit: .venv/bin/python werkzeuge/modelle_laden.py")
    optionen = ort.SessionOptions()
    optionen.log_severity_level = 3          # nur Fehler; CoreML meldet sonst jede nicht übernommene Rechenoperation
    vorhanden = ort.get_available_providers()
    return ort.InferenceSession(str(pfad), optionen, providers=[a for a in ANBIETER if a in vorhanden])


# Gitter der drei Ausgabeebenen (Schrittweite 8, 16, 32), bei YOLOX und YuNet gleich: je Zelle Spalte, Zeile, Schritt
_gitter, _schritte = [], []
for _s in (8, 16, 32):
    _n = EINGABE // _s
    _y, _x = np.meshgrid(np.arange(_n), np.arange(_n), indexing="ij")
    _gitter.append(np.stack((_x, _y), 2).reshape(-1, 2))
    _schritte.append(np.full((_n * _n, 1), _s))
GITTER, SCHRITTE = np.concatenate(_gitter), np.concatenate(_schritte)


def vorbereiten(bild, fuellung):
    """Bild auf 640 × 640 bringen: Seitenverhältnis bleibt, Bild oben links, Rest in der Füllfarbe, BGR, 0–255.
    Gibt das Feld und Breite, Höhe des verkleinerten Bildes darin zurück."""
    bild = bild.convert("RGB")
    faktor = min(EINGABE / bild.width, EINGABE / bild.height)
    bild = bild.resize((max(1, round(bild.width * faktor)), max(1, round(bild.height * faktor))), Image.Resampling.BILINEAR)
    feld = np.full((EINGABE, EINGABE, 3), fuellung, np.float32)
    feld[:bild.height, :bild.width] = np.asarray(bild)[:, :, ::-1]
    return feld.transpose(2, 0, 1)[None], bild.width, bild.height


def rahmen_behalten(rahmen, scores, ueberlappung):
    """Non-Maximum Suppression: Rahmen nach Score, jeder stark überlappende schwächere fällt weg.
    Gibt die Nummern der behaltenen Rahmen zurück, stärkster zuerst."""
    reihenfolge = np.argsort(-scores)
    behalten = []
    flaeche = lambda r: (r[..., 2] - r[..., 0]) * (r[..., 3] - r[..., 1])
    while reihenfolge.size:
        i, rest = reihenfolge[0], reihenfolge[1:]
        behalten.append(i)
        x1 = np.maximum(rahmen[i, 0], rahmen[rest, 0])
        y1 = np.maximum(rahmen[i, 1], rahmen[rest, 1])
        x2 = np.minimum(rahmen[i, 2], rahmen[rest, 2])
        y2 = np.minimum(rahmen[i, 3], rahmen[rest, 3])
        schnitt = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
        iou = schnitt / (flaeche(rahmen[i]) + flaeche(rahmen[rest]) - schnitt + 1e-9)
        reihenfolge = rest[iou <= ueberlappung]
    return behalten


def rahmen_aus(versatz, groesse, maske):
    """Rahmen (x1, y1, x2, y2) aus der Ausgabe je Gitterzelle: Mitte = (Zelle + Versatz) × Schritt,
    Größe = exp(Wert) × Schritt (bei YOLOX und YuNet gleich)."""
    mitte = (versatz[maske] + GITTER[maske]) * SCHRITTE[maske]
    ausdehnung = np.exp(groesse[maske]) * SCHRITTE[maske]
    return np.concatenate([mitte - ausdehnung / 2, mitte + ausdehnung / 2], axis=1)


def personen_finden(s, bild):
    """Personen (YOLOX-s): (Anzahl ab SCHWELLE, höchster Score, Fläche der größten Person als Anteil am Bild)."""
    feld, breite, hoehe = vorbereiten(bild, 114)          # grau wie beim Training von YOLOX
    aus = s.run(None, {s.get_inputs()[0].name: feld})[0][0]
    scores = aus[:, 4] * aus[:, 5]                       # „ein Objekt“ × „ist Klasse 0 (Person)“
    treffer = scores >= SCHWELLE
    if not treffer.any():
        return 0, float(scores.max()), 0.0
    rahmen = rahmen_aus(aus[:, :2], aus[:, 2:4], treffer)
    behalten = rahmen_behalten(rahmen, scores[treffer], UEBERLAPPUNG)
    r = rahmen[behalten]
    # nur der Teil im Bild zählt (Rahmen können über den Rand reichen)
    flaechen = (np.clip(r[:, 2], 0, breite) - np.clip(r[:, 0], 0, breite)) * (np.clip(r[:, 3], 0, hoehe) - np.clip(r[:, 1], 0, hoehe))
    return len(behalten), float(scores.max()), float(flaechen.max() / (breite * hoehe))


def gesichter_finden(s, bild):
    """Gesichter (YuNet): Höhen der Gesichter ab SCHWELLE_GESICHT als Anteil an der Bildhöhe, größtes zuerst."""
    feld, _, hoehe = vorbereiten(bild, 0)                 # YuNet: schwarz aufgefüllt wie in OpenCV
    aus = dict(zip([o.name for o in s.get_outputs()], s.run(None, {s.get_inputs()[0].name: feld})))
    stufen = (8, 16, 32)
    klasse = np.concatenate([aus[f"cls_{k}"][0, :, 0] for k in stufen])
    objekt = np.concatenate([aus[f"obj_{k}"][0, :, 0] for k in stufen])
    box = np.concatenate([aus[f"bbox_{k}"][0] for k in stufen])
    scores = np.sqrt(np.clip(klasse, 0, 1) * np.clip(objekt, 0, 1))
    treffer = scores >= SCHWELLE_GESICHT
    if not treffer.any():
        return []
    rahmen = rahmen_aus(box[:, :2], box[:, 2:4], treffer)
    behalten = rahmen_behalten(rahmen, scores[treffer], UEBERLAPPUNG_GESICHT)
    return sorted((float((rahmen[i, 3] - rahmen[i, 1]) / hoehe) for i in behalten), reverse=True)


def bildtyp_bestimmen(anzahl, gesichter):
    """Feste Regel: „porträt“, wenn ein Gesicht groß genug ist und kein zweites ähnlich groß; „personen“, wenn sonst
    jemand im Bild ist; sonst leer. gesichter: Höhen als Anteil an der Bildhöhe, größtes zuerst."""
    if gesichter and gesichter[0] >= PORTRAET_HOEHE and (len(gesichter) == 1 or gesichter[1] <= PORTRAET_ABSTAND * gesichter[0]):
        return "porträt"
    return "personen" if anzahl or gesichter else ""


def portraet_text(n):
    return f"{n:,} Porträt" + ("" if n == 1 else "s")


def erkennen(s, s_gesicht, bild):
    """Personen und Gesichter auf einem Bild: Angaben für eine Zeile der Tabelle personen."""
    anzahl, score, person_anteil = personen_finden(s, bild)
    gesichter = gesichter_finden(s_gesicht, bild)
    return {"anzahl": anzahl, "score": score, "gesichter": len(gesichter),
            "gesicht_anteil": round(gesichter[0], 4) if gesichter else 0.0, "person_anteil": round(person_anteil, 4),
            "bildtyp": bildtyp_bestimmen(anzahl, gesichter)}


def personen_erkennen(platte_id):
    """F5 Erkennt Personen und Gesichter auf den Vorschaubildern der Fotos einer Platte, soweit noch nicht geschehen
    (oder mit anderen Modellen, oder das Vorschaubild ist neuer). Jeder Inhalt nur einmal, auch wenn er auf mehreren
    Platten liegt. Unterbrechbar."""
    with db() as con:
        offen = con.execute(f"""
            SELECT DISTINCT v.sha256, v.datei FROM vorschau v JOIN datei d ON d.sha256 = v.sha256
            LEFT JOIN personen p ON p.sha256 = v.sha256
            WHERE d.platte_id = ? AND v.art IN ({",".join("?" * len(ARTEN))}) AND v.datei IS NOT NULL AND v.datei != ''
              AND (p.sha256 IS NULL OR p.modell != ? OR p.erkannt_am < v.erstellt_am)
            ORDER BY v.sha256""", (platte_id, *ARTEN, KENNUNG)).fetchall()
    if not offen:
        print(f"Für {platte_id} sind alle Fotos auf Personen geprüft.")
        return
    s, s_gesicht = sitzung(MODELL), sitzung(GESICHT_MODELL)
    print(f"Offen: {len(offen):,} Fotos; Modelle {MODELL} und {GESICHT_MODELL}, "
          f"Rechenwerk {s.get_providers()[0].replace('ExecutionProvider', '')}.")
    erledigt = mit = portraets = fehler = 0
    letzte = time.monotonic()
    schaetzer = Restzeit(len(offen))
    unterbrochen = False
    with db() as con:
        try:
            for sha, datei in offen:
                w = dict.fromkeys(("anzahl", "score", "gesichter", "gesicht_anteil", "person_anteil", "bildtyp"))
                text = None
                try:
                    with Image.open(P.vorschauen / datei) as bild:
                        w = erkennen(s, s_gesicht, bild)
                    mit += bool(w["bildtyp"])
                    portraets += w["bildtyp"] == "porträt"
                except (OSError, ValueError) as e:
                    text, fehler = str(e)[:200] or type(e).__name__, fehler + 1
                con.execute("""INSERT OR REPLACE INTO personen (sha256, anzahl, score, modell, fehler, erkannt_am,
                               gesichter, gesicht_anteil, person_anteil, bildtyp) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                            (sha, w["anzahl"], w["score"], KENNUNG, text, jetzt(),
                             w["gesichter"], w["gesicht_anteil"], w["person_anteil"], w["bildtyp"]))
                erledigt += 1
                if time.monotonic() - letzte > 2:
                    con.commit()
                    letzte = time.monotonic()
                    fortschritt(erledigt / len(offen), f"{erledigt:,}/{len(offen):,} · mit Personen {mit:,} "
                                f"(Porträts {portraets:,}) · {schaetzer.text(erledigt)}")
        except KeyboardInterrupt:
            unterbrochen = True
    protokolliere("F5", platte_id, "personen", "", f"{erledigt} Fotos, {mit} mit Personen, davon {portraet_text(portraets)}, "
                  f"{fehler} nicht lesbar" + (", unterbrochen" if unterbrochen else ""))
    print(f"\n{'Unterbrochen' if unterbrochen else 'Fertig'}: {erledigt:,} Fotos, davon {mit:,} mit Personen "
          f"({portraet_text(portraets)})" + (f", {fehler:,} Vorschaubilder nicht lesbar" if fehler else "") + ".")

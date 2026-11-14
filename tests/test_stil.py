"""Gestaltungsregeln der Oberfläche (tool/web/app.css, Entscheidung 13.11.2026).

Festgehalten wird, was beim Feinschliff vereinbart wurde:
- keine Versalien mit Sperrung (einzige Ausnahme: Eingabefeld des Projektkürzels), kein Kursiv als Betonung
- Gewichte höchstens 600, Hierarchie über Größe und Farbe
- Schriftgrößen aus einer festen Skala
- Abstände auf dem 4px-Raster (0–2 px für Feinkorrekturen, 6 px als Schritt in kleinen Bedienelementen)
- Radien aus einer festen Reihe
- Schrift auf Farbflächen erreicht 4,5 : 1 in hell und dunkel; Weiß nur über Farbrollen, nie fest
"""
import re
from pathlib import Path

CSS = (Path(__file__).resolve().parent.parent / "tool" / "web" / "app.css").read_text(encoding="utf-8")
# Kommentare weg, damit Erklärtexte nicht mitzählen
REGELN = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)

SKALA = {11, 12, 13, 14, 15, 18, 22}
RADIEN = {0, 4, 8, 12, 999}


def _deklarationen(eigenschaft_muster):
    return re.findall(r"(?<![-\w])(" + eigenschaft_muster + r")\s*:\s*([^;}]+)", REGELN)


def test_keine_versalien():
    treffer = [z for z in REGELN.splitlines() if "uppercase" in z and "input.kurz" not in z]
    assert not treffer, treffer


def test_kein_kursiv():
    assert "italic" not in REGELN


def test_gewichte_hoechstens_600():
    zu_schwer = [w for _, w in _deklarationen("font-weight") if w.strip().isdigit() and int(w) > 600]
    zu_schwer += [w for _, w in _deklarationen("font-weight") if w.strip() == "bold"]
    assert not zu_schwer, zu_schwer
    # Überschriften und <b> sind im Browser fett (700): einmal zentral auf 600
    assert re.search(r"h1, h2, h3[^{]*\{[^}]*font-weight:\s*600", REGELN)
    assert re.search(r"\bb, strong\s*\{[^}]*font-weight:\s*600", REGELN)


def test_schriftgroessen_aus_der_skala():
    groessen = [float(g) for g in re.findall(r"font-size:\s*([\d.]+)px", REGELN)]
    groessen += [float(g) for g in re.findall(r"font:\s*([\d.]+)px", REGELN)]
    fremd = sorted({g for g in groessen if g not in SKALA})
    assert not fremd, fremd


def test_abstaende_auf_dem_raster():
    fremd = []
    for eig, wert in _deklarationen(r"padding(?:-[a-z]+)?|margin(?:-[a-z]+)?|gap|row-gap|column-gap"):
        if "calc(" in wert or "var(" in wert:
            continue
        for zahl in re.findall(r"-?([\d.]+)px", wert):
            n = float(zahl)
            if not (n <= 2 or n == 6 or n % 4 == 0):
                fremd.append(f"{eig}: {wert.strip()}")
    assert not fremd, fremd


def test_radien_aus_der_reihe():
    fremd = []
    for _, wert in _deklarationen("border-radius"):
        for zahl in re.findall(r"([\d.]+)px", wert):
            if float(zahl) not in RADIEN:
                fremd.append(wert.strip())
    assert not fremd, fremd


# ---------- Kontrast ----------

def _block(selektor_muster):
    m = re.search(selektor_muster + r"\s*\{(.*?)\}", REGELN, flags=re.S)
    assert m, selektor_muster
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", m.group(1)))


def _hell():
    return _block(r"(?m)^:root")


def _dunkel():
    werte = dict(_hell())
    werte.update(_block(r':root\[data-theme="dark"\]'))
    return werte


def _luminanz(hexwert):
    h = hexwert.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    kanaele = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in kanaele]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _kontrast(a, b):
    la, lb = sorted((_luminanz(a), _luminanz(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# Farbfläche → Schrift darauf
PAARE = [
    ("--fokus", "--auf-farbe"),          # Auswahlmarke, Leitdatei, aktueller Schritt
    ("--e-ueb", "--auf-farbe"),          # übernehmen
    ("--violett", "--auf-farbe"),        # zugeordnet
    ("--a-rot", "--auf-farbe"),          # Fehler
    ("--e-kas", "--auf-orange"),         # kassieren
    ("--e-zur", "--auf-gelb"),           # zurückstellen
    ("--dunkel", "--auf-dunkel"),        # Hauptknopf, aktives Modul
    # Farbe als Schrift auf der Karte
    ("--karte", "--orange-stark"),       # Warnung
    ("--karte", "--a-rot"),              # Fehler
    ("--karte", "--fokus"),              # Links, Auswahl
]


# Grün bleibt im vertrauten Ton (Entscheidung 13.11.2026: der dunklere war zu grell); geprüft wird es gegen 3 : 1,
# die Schwelle für Symbole und kräftige Farbflächen
PAARE_GRUEN = [
    ("--a-gruen", "--auf-gruen"),        # erledigt, fertig (Chips, Haken, Ringe)
    ("--karte", "--a-gruen"),            # gut, fertig als Schrift
]


def test_gruen_mindestens_3_zu_1():
    schwach = []
    for name, werte in (("hell", _hell()), ("dunkel", _dunkel())):
        for flaeche, schrift in PAARE_GRUEN:
            k = _kontrast(werte[flaeche], werte[schrift])
            if k < 3:
                schwach.append(f"{name}: {flaeche} / {schrift} = {k:.2f}")
    assert not schwach, schwach


def test_orange_als_schrift_nur_in_der_starken_rolle():
    schwach = re.findall(r"(?<![-\w])color:\s*var\(--e-kas\)", REGELN)
    assert not schwach, schwach


def test_dunkle_werte_in_beiden_dunkelbloecken_gleich():
    medien = _block(r'@media \(prefers-color-scheme: dark\)\s*\{\s*:root:not\(\[data-theme="light"\]\)')
    assert medien == _block(r':root\[data-theme="dark"\]')


def test_schrift_auf_farbflaechen_lesbar():
    schwach = []
    for name, werte in (("hell", _hell()), ("dunkel", _dunkel())):
        for flaeche, schrift in PAARE:
            k = _kontrast(werte[flaeche], werte[schrift])
            if k < 4.5:
                schwach.append(f"{name}: {flaeche} / {schrift} = {k:.2f}")
    assert not schwach, schwach


def test_weiss_nur_ueber_farbrollen():
    # #fff fest im Text heißt fast immer: Weiß auf einer Farbe, die im Dunkelmodus hell wird
    ausserhalb = [z.strip() for z in REGELN.splitlines()
                  if re.search(r"#fff\b|#ffffff\b", z, flags=re.I) and "--" not in z.split(":")[0]]
    assert not ausserhalb, ausserhalb

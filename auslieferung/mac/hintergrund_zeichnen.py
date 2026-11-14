"""Hintergrund des Mac-Abbilds (.dmg) zeichnen: hintergrund.png (660 × 420) und hintergrund@2x.png.

Einmal von Hand, wenn sich Gestaltung oder Text ändern; die Bilder liegen im Repo, der Bau nutzt sie nur.
Die Lage der Symbole (APP, PROGRAMME) muss zu dmg_einstellungen.py passen.

    .venv/bin/python auslieferung/mac/hintergrund_zeichnen.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HIER = Path(__file__).resolve().parent
SCHRIFT = HIER.parent.parent / "tool" / "web" / "vendor" / "inter" / "inter-latin.woff2"
BREITE, HOEHE = 660, 420
APP, PROGRAMME = (170, 200), (490, 200)          # Mitte der Symbole im Fenster (Punkte), wie in dmg_einstellungen.py

PAPIER_OBEN, PAPIER_UNTEN = (252, 249, 242), (240, 234, 221)   # wie das Symbol
TINTE, TINTE_2, TINTE_3 = (23, 32, 51), (75, 85, 99), (120, 113, 100)
LINIE = (214, 205, 186)


def schrift(groesse, gewicht=400):
    f = ImageFont.truetype(str(SCHRIFT), groesse)
    f.set_variation_by_axes([gewicht])
    return f


def zeichnen(massstab):
    b, h = BREITE * massstab, HOEHE * massstab
    s = lambda wert: int(round(wert * massstab))
    bild = Image.new("RGB", (1, h))
    for y in range(h):                                           # Papier, leicht nach unten dunkler
        t = y / (h - 1)
        bild.putpixel((0, y), tuple(int(PAPIER_OBEN[i] * (1 - t) + PAPIER_UNTEN[i] * t) for i in range(3)))
    bild = bild.resize((b, h))
    d = ImageDraw.Draw(bild)

    # Kopf: Name und Zweck
    d.text((s(40), s(34)), "Balduin", font=schrift(s(26), 650), fill=TINTE)
    d.text((s(40), s(68)), "Datenträger registrieren, bewerten, erschließen und für Anton packen",
           font=schrift(s(12.5)), fill=TINTE_2)
    d.line((s(40), s(98), b - s(40), s(98)), fill=LINIE, width=max(1, s(1)))

    # Pfeil von Balduin zum Ordner „Programme“ (Symbole selbst zeichnet der Finder)
    y = s(APP[1])
    x0, x1 = s(APP[0] + 78), s(PROGRAMME[0] - 78)
    for x in range(x0, x1 - s(14), s(9)):                        # gestrichelt wie eine Stichlinie
        d.line((x, y, min(x + s(5), x1 - s(14)), y), fill=TINTE_3, width=s(2))
    d.polygon([(x1, y), (x1 - s(14), y - s(7)), (x1 - s(14), y + s(7))], fill=TINTE_3)

    # Anleitung unter den Symbolen
    mitte = b // 2
    text = "Zum Installieren Balduin in den Ordner „Programme“ ziehen."
    f = schrift(s(14), 550)
    d.text((mitte - d.textlength(text, font=f) / 2, s(300)), text, font=f, fill=TINTE)

    # Fuß: erster Start ohne Signatur
    d.line((s(40), s(340), b - s(40), s(340)), fill=LINIE, width=max(1, s(1)))
    fuss = ["Erster Start: Balduin im Ordner „Programme“ mit Rechtsklick und „Öffnen“ starten; meldet das",
            "System eine Sperre, unter Systemeinstellungen › Datenschutz & Sicherheit „Dennoch öffnen“ wählen."]
    f = schrift(s(11))
    for i, zeile in enumerate(fuss):
        d.text((mitte - d.textlength(zeile, font=f) / 2, s(354 + i * 17)), zeile, font=f, fill=TINTE_2)
    return bild


if __name__ == "__main__":
    zeichnen(1).save(HIER / "hintergrund.png", optimize=True)
    zeichnen(2).save(HIER / "hintergrund@2x.png", optimize=True)
    print("hintergrund.png und hintergrund@2x.png geschrieben")

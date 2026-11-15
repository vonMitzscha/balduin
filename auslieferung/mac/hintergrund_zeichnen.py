"""Hintergrund des Mac-Abbilds (.dmg) zeichnen: hintergrund.png (720 × 540) und hintergrund@2x.png.

Aufbau auf weißem Grund: links Name und Zweck, in der Mitte blass der ganze Elefant, dessen Kopf genau unter dem
Kopf im App-Symbol liegt (der Finder zeichnet das Symbol darüber, der Elefant wächst aus ihm heraus), rechts der
Ordner „Programme“. Darunter die Anleitung und der erste Start in drei Schritten mit nachgezeichneten
Bedienelementen des Systems (Meldung, Seitenleiste der Systemeinstellungen, Knopf „Dennoch öffnen“).

Einmal von Hand, wenn sich Gestaltung oder Text ändern; die Bilder liegen im Repo, der Bau nutzt sie nur.
Lage und Größe der Symbole (APP, PROGRAMME, SYMBOL) müssen zu dmg_einstellungen.py passen.

    .venv/bin/python auslieferung/mac/hintergrund_zeichnen.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HIER = Path(__file__).resolve().parent
SCHRIFT = HIER.parent.parent / "tool" / "web" / "vendor" / "inter" / "inter-latin.woff2"
ELEFANT = HIER / "symbol_ebenen" / "elefant_ganz.png"   # ganzer Elefant: schwarze Linien, freigestellt
BREITE, HOEHE = 720, 540
APP, PROGRAMME = (300, 150), (610, 150)          # Mitte der Symbole im Fenster (Punkte), wie in dmg_einstellungen.py
SYMBOL = 128                                     # Größe der Symbole (Punkte), icon_size in dmg_einstellungen.py
FEIN = 4                                         # erst so viel größer zeichnen, dann verkleinern (glatte Kanten)

# Lage des Originals im App-Symbol (symbol_ebenen/elefant.png, 1024 px): Maßstab und linke obere Ecke,
# ermittelt durch Abgleich der beiden Bilder (Korrelation 0,84). Ändert sich das Symbol, hier nachziehen.
IM_SYMBOL_MASSSTAB, IM_SYMBOL_ECKE = 0.908, (233, -103)
ELEFANT_DECKUNG = 0.22                           # blass: Anteil der Linien gegenüber dem Symbol

GRUND = (255, 255, 255)
TINTE, TINTE_2, TINTE_3 = (23, 32, 51), (75, 85, 99), (120, 124, 132)
LINIE = (222, 225, 230)
# Farben der nachgezeichneten Bedienelemente (helle Darstellung, Akzentfarbe Blau wie ab Werk)
SYS_BLAU = (0, 122, 255)
SYS_TEXT, SYS_TEXT_2 = (29, 29, 31), (110, 110, 115)
SYS_GRUPPE, SYS_LEISTE, SYS_KNOPF = (244, 244, 246), (236, 236, 238), (226, 226, 230)
SYS_RAND = (210, 210, 214)


def schrift(groesse, gewicht=400):
    f = ImageFont.truetype(str(SCHRIFT), groesse)
    f.set_variation_by_axes([gewicht])
    return f


def elefant_zeichnen(bild, massstab):
    """Den ganzen Elefanten blass so einsetzen, dass er mit dem Kopf im App-Symbol deckungsgleich ist."""
    linien = Image.open(ELEFANT).getchannel("A")                 # Deckung der Linien
    # Bildpunkte je Pixel des Originals im Fenster, und wo seine linke obere Ecke liegt (auf Bruchteile genau)
    k = IM_SYMBOL_MASSSTAB * SYMBOL / 1024 * massstab
    ox = (APP[0] - SYMBOL / 2 + IM_SYMBOL_ECKE[0] * SYMBOL / 1024) * massstab
    oy = (APP[1] - SYMBOL / 2 + IM_SYMBOL_ECKE[1] * SYMBOL / 1024) * massstab
    x0, y0 = int(ox), int(oy)
    x1, y1 = -int(-(ox + linien.width * k)), -int(-(oy + linien.height * k))
    rand = 8                                                     # Rand, damit der Ausschnitt nie übers Bild hinausgeht
    gross = Image.new("L", (linien.width + 2 * rand, linien.height + 2 * rand), 0)
    gross.paste(linien, (rand, rand))
    kasten = ((x0 - ox) / k + rand, (y0 - oy) / k + rand, (x1 - ox) / k + rand, (y1 - oy) / k + rand)
    maske = gross.resize((x1 - x0, y1 - y0), Image.LANCZOS, box=kasten)
    maske = maske.point(lambda a: round(a * ELEFANT_DECKUNG))
    bild.paste(Image.new("RGB", maske.size, (0, 0, 0)), (x0, y0), maske)


class Zeichner:
    """Zeichnet in Punkten des Fensters; s() rechnet in Bildpunkte um."""

    def __init__(self, bild, massstab):
        self.bild, self.m = bild, massstab
        self.d = ImageDraw.Draw(bild)

    def s(self, wert):
        return wert * self.m

    def r(self, *werte):
        return tuple(self.s(w) for w in werte)

    def f(self, groesse, gewicht=400):
        return schrift(self.s(groesse), gewicht)

    def text(self, xy, text, groesse, gewicht=400, farbe=TINTE, anker="la"):
        self.d.text(self.r(*xy), text, font=self.f(groesse, gewicht), fill=farbe, anchor=anker)

    def breite(self, text, groesse, gewicht=400):
        return self.d.textlength(text, font=self.f(groesse, gewicht)) / self.m

    def umbrechen(self, text, groesse, gewicht, breite):
        zeilen, zeile = [], ""
        for wort in text.split():
            probe = f"{zeile} {wort}".strip()
            if zeile and self.breite(probe, groesse, gewicht) > breite:
                zeilen.append(zeile)
                zeile = wort
            else:
                zeile = probe
        return zeilen + [zeile]

    def kasten(self, x, y, b, h, radius, fuellung, rand=None):
        self.d.rounded_rectangle(self.r(x, y, x + b, y + h), radius=self.s(radius), fill=fuellung,
                                 outline=rand, width=max(1, round(self.s(0.5))) if rand else 0)

    def schatten(self, x, y, b, h, radius, weich=6, staerke=40):
        """Weicher Schatten unter einem Fenster oder einer Meldung."""
        ebene = Image.new("L", self.bild.size, 0)
        ImageDraw.Draw(ebene).rounded_rectangle(self.r(x, y + 2, x + b, y + h + 2), radius=self.s(radius),
                                                fill=staerke)
        ebene = ebene.filter(ImageFilter.GaussianBlur(self.s(weich)))
        self.bild.paste(Image.new("RGB", self.bild.size, (0, 0, 0)), (0, 0), ebene)
        self.d = ImageDraw.Draw(self.bild)


def kopf(z):
    """Links: Name, darunter was Balduin mit Datenträgern tut."""
    x = 40
    z.text((x, 100), "Balduin", 40, 700, anker="ls")
    z.text((x, 138), "Datenträger", 16, 650, anker="ls")
    for i, wort in enumerate(("analysieren", "bewerten", "erschließen")):
        z.text((x, 162 + i * 22), "↓" + wort, 16, 400, anker="ls")


def hand(z, x, y, groesse, farbe):
    """Hand des Symbols „Datenschutz & Sicherheit“: vier Finger, Daumen, Handfläche."""
    e = groesse / 16
    for i, (fx, oben) in enumerate(((4.6, 3.2), (6.9, 2.2), (9.2, 2.6), (11.4, 4.0))):
        z.kasten(x + fx * e, y + oben * e, 1.8 * e, (10 - oben) * e, 0.9 * e, farbe)
    z.d.polygon([z.r(x + 2.6 * e, y + 8.0 * e), z.r(x + 3.9 * e, y + 7.2 * e), z.r(x + 6.0 * e, y + 10.5 * e),
                 z.r(x + 4.8 * e, y + 11.6 * e)], fill=farbe)                       # Daumen
    z.kasten(x + 4.4 * e, y + 8.4 * e, 9.0 * e, 5.6 * e, 2.6 * e, farbe)             # Handfläche


def fingerabdruck(z, mx, my):
    """Fingerabdruck des Symbols „Touch ID & Passwort“: ineinanderliegende, unten offene Bögen um (mx, my)."""
    farbe, staerke = (236, 64, 96), max(1, round(z.s(0.75)))
    # Halbachsen und Bogen (Grad, 0 = rechts, im Uhrzeigersinn); innen fast geschlossen, außen weiter offen
    for rx, von, bis in ((1.0, 90, 430), (2.2, 120, 420), (3.4, 140, 410), (4.6, 160, 390), (5.8, 185, 355)):
        ry = rx * 1.15 + 0.4
        z.d.arc(z.r(mx - rx, my - ry + 0.6, mx + rx, my + ry + 0.6), von, bis, fill=farbe, width=staerke)


def meldung(z, x, y):
    """Meldung beim ersten Öffnen: „Balduin“ nicht geöffnet, Knopf „Fertig“."""
    b, h = 168, 104
    z.schatten(x, y, b, h, 18)
    z.kasten(x, y, b, h, 18, (248, 248, 249), SYS_RAND)
    # Symbol des Tresors mit Warnzeichen, vereinfacht
    z.kasten(x + 14, y + 12, 24, 24, 6, (214, 216, 222))
    z.d.ellipse(z.r(x + 18.5, y + 16.5, x + 33.5, y + 31.5), fill=(70, 72, 78))
    z.d.ellipse(z.r(x + 22.5, y + 20.5, x + 29.5, y + 27.5), fill=(150, 154, 162))
    z.d.polygon([z.r(x + 33, y + 27), z.r(x + 40, y + 39), z.r(x + 26, y + 39)], fill=(246, 196, 48),
                outline=(255, 255, 255))
    z.text((x + 33, y + 37.6), "!", 7, 800, (40, 40, 40), anker="ms")
    z.text((x + 14, y + 50), "„Balduin“ nicht geöffnet", 10, 700, SYS_TEXT, anker="ls")
    z.text((x + 14, y + 64), "Apple konnte nicht überprüfen, ob …", 8.5, 400, SYS_TEXT_2, anker="ls")
    z.kasten(x + 12, y + 76, b - 24, 18, 9, SYS_BLAU)
    z.text((x + b / 2, y + 88.5), "Fertig", 9.5, 550, (255, 255, 255), anker="ms")


def seitenleiste(z, x, y):
    """Ausschnitt der Seitenleiste der Systemeinstellungen mit „Datenschutz & Sicherheit“ ausgewählt."""
    b, h = 188, 86
    z.kasten(x, y, b, h, 14, SYS_LEISTE)
    zeilen = [("Bildschirm sperren", (28, 28, 30), False), ("Datenschutz & Sicherheit", SYS_BLAU, True),
              ("Touch ID & Passwort", (255, 255, 255), False)]
    for i, (name, farbe, gewaehlt) in enumerate(zeilen):
        zy = y + 8 + i * 24
        if gewaehlt:
            z.kasten(x + 6, zy, b - 12, 22, 7, SYS_BLAU)
        z.kasten(x + 13, zy + 3.5, 15, 15, 4, (255, 255, 255) if gewaehlt else farbe,
                 None if (gewaehlt or name != "Touch ID & Passwort") else SYS_RAND)
        if gewaehlt:
            hand(z, x + 13.5, zy + 4, 14, SYS_BLAU)
        elif name == "Bildschirm sperren":                          # Schloss
            z.kasten(x + 17.5, zy + 9.5, 6, 5, 1, (255, 255, 255))
            z.d.arc(z.r(x + 18.5, zy + 6.5, x + 22.5, zy + 12), 180, 360, fill=(255, 255, 255),
                    width=round(z.s(1.2)))
        else:
            fingerabdruck(z, x + 20.5, zy + 11)
        z.text((x + 35, zy + 15), name, 10.5, 600 if gewaehlt else 450,
               (255, 255, 255) if gewaehlt else SYS_TEXT, anker="ls")


def sicherheit(z, x, y):
    """Abschnitt „Sicherheit“ in „Datenschutz & Sicherheit“ mit dem Knopf „Dennoch öffnen“."""
    b = 248
    z.text((x + 4, y + 10), "Sicherheit", 10.5, 700, SYS_TEXT, anker="ls")
    z.kasten(x, y + 18, b, 68, 12, SYS_GRUPPE)
    z.text((x + 10, y + 39), "„Balduin“ wurde blockiert …", 9, 450, SYS_TEXT, anker="ls")
    kb = z.breite("Dennoch öffnen", 9.5, 450) + 18
    z.kasten(x + b - 8 - kb, y + 25, kb, 20, 6, SYS_KNOPF)
    z.text((x + b - 8 - kb / 2, y + 39), "Dennoch öffnen", 9.5, 450, SYS_TEXT, anker="ms")
    z.d.line(z.r(x + 10, y + 52, x + b - 10, y + 52), fill=(226, 226, 230), width=max(1, round(z.s(0.5))))
    z.text((x + 10, y + 66), "Apple konnte nicht überprüfen, ob „Balduin“", 8, 400, SYS_TEXT_2, anker="ls")
    z.text((x + 10, y + 77), "frei von Schadsoftware ist, …", 8, 400, SYS_TEXT_2, anker="ls")


def erster_start(z, y):
    """Drei Schritte für den ersten Start ohne Beglaubigung, je mit dem Bedienelement, das man sieht."""
    z.text((40, y), "Erster Start", 12, 650, TINTE, anker="ls")
    spalten = [(40, 172, "Balduin öffnen; die Meldung mit „Fertig“ schließen.", meldung),
               (228, 190, "Systemeinstellungen öffnen und „Datenschutz & Sicherheit“ wählen.", seitenleiste),
               (432, 248, "Unter „Sicherheit“ „Dennoch öffnen“ wählen und mit dem Passwort bestätigen.",
                sicherheit)]
    for nummer, (x, b, text, element) in enumerate(spalten, 1):
        z.d.ellipse(z.r(x, y + 10, x + 16, y + 26), fill=TINTE)
        z.text((x + 8, y + 22), str(nummer), 9.5, 700, (255, 255, 255), anker="ms")
        for i, zeile in enumerate(z.umbrechen(text, 11, 400, b - 24)):
            z.text((x + 24, y + 22 + i * 15), zeile, 11, 400, TINTE_2, anker="ls")
        element(z, x, y + 64)


def zeichnen_fein(massstab):
    b, h = round(BREITE * massstab), round(HOEHE * massstab)
    bild = Image.new("RGB", (b, h), GRUND)
    elefant_zeichnen(bild, massstab)
    z = Zeichner(bild, massstab)
    kopf(z)
    # Anleitung unter den Symbolen, mit Abstand zu den Füßen des Elefanten
    text = "Zum Installieren Balduin in den Ordner „Programme“ ziehen."
    z.text((BREITE / 2, 300), text, 14, 550, TINTE, anker="ms")
    z.d.line(z.r(40, 320, BREITE - 40, 320), fill=LINIE, width=max(1, round(z.s(1))))
    erster_start(z, 346)
    return bild


def zeichnen(massstab):
    return zeichnen_fein(massstab * FEIN).resize((BREITE * massstab, HOEHE * massstab), Image.LANCZOS)


if __name__ == "__main__":
    zeichnen(1).save(HIER / "hintergrund.png", optimize=True)
    zeichnen(2).save(HIER / "hintergrund@2x.png", optimize=True)
    print("hintergrund.png und hintergrund@2x.png geschrieben")

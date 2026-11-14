"""Legt vier simulierte Festplatten unter testplatten/ an, um das Tool gefahrlos auszuprobieren.

HD01  Original (Fotos 2001–2004, Texte, einige echte Formate: PNG, GIF, PDF, HTML; ein PNG doppelt;
      Dokumente mit Text für E4: PDF, DOCX, PPTX, ODT, RTF, TXT;
      Kamerabilder mit EXIF, dazu TIFF-Variante, verkleinerte Webfassung, kaputtes JPEG, kurzes Video,
      AppleDouble- und Thumbs.db-Dateien)
HD02  Backup von HD01 in einem Unterordner „Backup 2012“, Umlaute in macOS-Schreibweise (NFD)
HD03  eigene Dateien plus eine Kopie des Ordners Fotos/2003 von HD01
HD04  1:1-Klon von HD01, eine Datei mit gleicher Größe, aber anderem Inhalt

Aufruf im Projektordner:  python werkzeuge/testplatten_erzeugen.py [Zielordner]
                          (ohne Angabe testplatten/ im Code-Ordner; die automatischen Tests geben einen Ordner im
                          Temp-Verzeichnis an, tests/conftest.py)
Im Tool dann:             ./Balduin.command --volumes "$PWD/testplatten"
(Notebook 1, B1:          MOUNTPUNKT = Path("testplatten/HD01"))
"""
import os
import random
import shutil
import struct
import subprocess
import sys
import unicodedata
import zipfile
import zlib
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from erfassung import system  # noqa: E402  (Werkzeuge auch aus BALDUIN_WERKZEUGE, z. B. unter Windows)

# Zielordner: erstes Argument, sonst testplatten/ neben dem Code
ZIEL = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "testplatten"
zufall = random.Random(1)


def datei(pfad, groesse):
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_bytes(zufall.randbytes(groesse))


def png(breite, hoehe, farbe):
    """Kleines echtes PNG mit Farbverlauf, damit Formaterkennung und Vorschaubilder etwas zu tun haben."""
    zeilen = b"".join(b"\x00" + bytes(v for x in range(breite) for v in (farbe[0], x * 255 // breite, y * 255 // hoehe))
                      for y in range(hoehe))
    def block(art, daten):
        return struct.pack(">I", len(daten)) + art + daten + struct.pack(">I", zlib.crc32(art + daten))
    return (b"\x89PNG\r\n\x1a\n" + block(b"IHDR", struct.pack(">IIBBBBB", breite, hoehe, 8, 2, 0, 0, 0))
            + block(b"IDAT", zlib.compress(zeilen)) + block(b"IEND", b""))


def echte_formate(ordner):
    (ordner / "Formate").mkdir(parents=True, exist_ok=True)
    (ordner / "Formate" / "verlauf_rot.png").write_bytes(png(64, 48, (200, 0, 0)))
    (ordner / "Formate" / "verlauf_blau.png").write_bytes(png(64, 48, (20, 0, 0)))
    (ordner / "Formate" / "punkt.gif").write_bytes(
        b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00"
        b",\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")
    (ordner / "Formate" / "Jahresbericht 2003.pdf").write_bytes(
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")
    (ordner / "Formate" / "index.htm").write_text(
        "<!DOCTYPE html>\n<html><head><title>Muster Messe</title></head><body><p>Messe 2003</p></body></html>\n", encoding="utf-8")
    # dieselbe Datei unter anderem Namen in einem anderen Ordner (Duplikat auf derselben Platte)
    (ordner / "Fotos" / "Auswahl").mkdir(parents=True, exist_ok=True)
    shutil.copy2(ordner / "Formate" / "verlauf_rot.png", ordner / "Fotos" / "Auswahl" / "titelbild.png")


def pdf_mit_text(zeilen, titel):
    """Einseitiges PDF mit Textebene; zeilen = [(Schriftgröße, y, Text)], titel = Dokumenteigenschaft Title."""
    inhalt = "".join(f"BT /F1 {g} Tf 40 {y} Td ({t}) Tj ET\n" for g, y, t in zeilen).encode("latin-1")
    objekte = [b"<</Type/Catalog/Pages 2 0 R/Outlines 6 0 R>>", b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
               b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>",
               b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica/Encoding/WinAnsiEncoding>>",
               b"<</Length %d>>stream\n" % len(inhalt) + inhalt + b"endstream",
               b"<</Type/Outlines/First 7 0 R/Last 7 0 R/Count 1>>",
               b"<</Title(" + titel.encode("latin-1") + b")/Parent 6 0 R/Dest[3 0 R/Fit]>>",
               b"<</Title(" + titel.encode("latin-1") + b")>>"]
    pdf, versatz = b"%PDF-1.4\n", []
    for i, o in enumerate(objekte, 1):
        versatz.append(len(pdf))
        pdf += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(pdf)
    pdf += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objekte) + 1) + b"".join(b"%010d 00000 n \n" % v for v in versatz)
    pdf += b"trailer<</Size %d/Root 1 0 R/Info 8 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (len(objekte) + 1, xref)
    return pdf


def dokumente(ordner):
    """Echte Dokumente mit Text für E4 (Texte): PDF, DOCX, PPTX, ODT, RTF, TXT; die Berichte unter Texte/ sind
    absichtlich kaputt (Zufallsbytes) und prüfen den Fehlerweg. Alte .doc/.ppt lassen sich hier nicht erzeugen."""
    import docx
    import pptx
    d = ordner / "Dokumente"
    d.mkdir(parents=True, exist_ok=True)
    (d / "090009_GF_GB_03_d.pdf").write_bytes(pdf_mit_text(
        [(9, 800, "Muster AG"), (24, 700, "Geschäftsbericht 2003"), (14, 670, "Konzernrechnung"),
         (10, 600, "Der Umsatz stieg im Berichtsjahr um vier Prozent."), (10, 586, "Schaffhausen, im März 2004")],
        "GB03_032_042_d.qxp"))
    w = docx.Document()
    w.core_properties.title = "Microsoft Word - Pressemitteilung.doc"
    w.add_heading("Eröffnung des Werks in Suzhou", level=1)
    w.add_paragraph("Am 25. Oktober 2005 wurde das neue Werk eröffnet.")
    w.save(d / "Pressemitteilung Suzhou.docx")
    p = pptx.Presentation()
    folie = p.slides.add_slide(p.slide_layouts[0])
    folie.shapes.title.text = "Technology Day 2007"
    folie.placeholders[1].text = "Programm und Referenten"
    p.save(d / "TechDay_2007.pptx")
    meta = ('<?xml version="1.0"?><office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/"><office:meta><dc:title>Protokoll Sitzung</dc:title>'
            '</office:meta></office:document-meta>')
    inhalt = ('<?xml version="1.0"?><office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
              'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:text>'
              '<text:h>Protokoll der Sitzung vom 3. Mai 2004</text:h><text:p>Anwesend: alle.</text:p>'
              '</office:text></office:body></office:document-content>')
    with zipfile.ZipFile(d / "Protokoll.odt", "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        z.writestr("content.xml", inhalt)
        z.writestr("meta.xml", meta)
    (d / "Brief.rtf").write_bytes(rb"{\rtf1\ansi{\fonttbl{\f0 Arial;}}\f0 Sehr geehrte Damen und Herren,\par "
                                  rb"wir danken f\'fcr Ihren Besuch.\par}")
    (d / "liesmich.txt").write_bytes("Übersicht der Bilder\nAufgenommen in Schaffhausen\n".encode("cp1252"))


def kamerabilder(ordner):
    """Echte Fotos mit EXIF für E (Metadaten), F (Vorschauen), G (Varianten, beinahe gleich) und H (kaputt)."""
    kamera = ordner / "Fotos" / "Kamera 2003"
    kamera.mkdir(parents=True, exist_ok=True)
    for k, ausschnitt in enumerate([(-1.9, -0.4, 0.6, 1.3), (-0.8, -0.3, -0.5, 0.0)], start=1):
        grau = Image.effect_mandelbrot((640, 480), ausschnitt, 60)
        bild = Image.merge("RGB", (grau, grau.rotate(180), Image.linear_gradient("L").resize((640, 480))))
        bild.save(kamera / f"DSC_000{k}.JPG", quality=90)
        if k == 1:
            bild.save(kamera / "DSC_0001.TIF")                                   # Formatvariante derselben Aufnahme
            bild.resize((320, 240)).save(ordner / "Fotos" / "Auswahl" / "messe_web.jpg", quality=60)  # beinahe gleich
            daten = (kamera / "DSC_0001.JPG").read_bytes()
            (kamera / "kaputt.jpg").write_bytes(daten[: len(daten) // 2])        # abgeschnitten
            (kamera / "._DSC_0001.JPG").write_bytes(b"\x00\x05\x16\x07" + bytes(4092))  # AppleDouble
    if system.werkzeug_pfad("exiftool"):
        subprocess.run([system.werkzeug("exiftool"), "-q", "-overwrite_original", "-DateTimeOriginal=2003:05:12 14:22:01",
                        "-Make=NIKON CORPORATION", "-Model=NIKON D70", "-SerialNumber=2046123",
                        "-Artist=Muster Fotodienst", "-Keywords=Messe", "-Keywords=Stand",
                        str(kamera / "DSC_0001.JPG"), str(kamera / "DSC_0001.TIF")], check=True)
        subprocess.run([system.werkzeug("exiftool"), "-q", "-overwrite_original", "-DateTimeOriginal=2003:05:12 15:01:44",
                        "-Make=NIKON CORPORATION", "-Model=NIKON D70", str(kamera / "DSC_0002.JPG")], check=True)
    Image.effect_mandelbrot((200, 150), (-2.0, -1.2, 1.0, 1.2), 30).save(ordner / "Fotos" / "20020615_Empfang.png")
    (ordner / "Fotos" / "Thumbs.db").write_bytes(zufall.randbytes(3000))
    if system.werkzeug_pfad("ffmpeg"):
        (ordner / "Filme").mkdir(exist_ok=True)
        subprocess.run([system.werkzeug("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=10",
                        "-pix_fmt", "yuv420p", str(ordner / "Filme" / "Clip.mp4")], check=True)


shutil.rmtree(ZIEL, ignore_errors=True)

for jahr in range(2001, 2005):
    for k in range(30):
        datei(ZIEL / "HD01" / "Fotos" / str(jahr) / f"Messe {jahr}" / f"IMG_{k:04d}.JPG", zufall.randint(2000, 9000))
    datei(ZIEL / "HD01" / "Texte" / f"Bericht_{jahr}.docx", 5000 + jahr)
datei(ZIEL / "HD01" / "Fotos" / "Müller Jubiläum" / "bild.jpg", 4321)
echte_formate(ZIEL / "HD01")
dokumente(ZIEL / "HD01")
kamerabilder(ZIEL / "HD01")

shutil.copytree(ZIEL / "HD01", ZIEL / "HD02" / "Backup 2012")
fotos = ZIEL / "HD02" / "Backup 2012" / "Fotos"
os.rename(fotos / "Müller Jubiläum", fotos / unicodedata.normalize("NFD", "Müller Jubiläum"))

for k in range(40):
    datei(ZIEL / "HD03" / "Projekte" / "Bau" / f"plan_{k}.tif", zufall.randint(3000, 8000))
shutil.copytree(ZIEL / "HD01" / "Fotos" / "2003", ZIEL / "HD03" / "Alt" / "2003")

shutil.copytree(ZIEL / "HD01", ZIEL / "HD04")
veraendert = ZIEL / "HD04" / "Fotos" / "2001" / "Messe 2001" / "IMG_0000.JPG"
veraendert.write_bytes(zufall.randbytes(veraendert.stat().st_size))

print("Testplatten angelegt in", ZIEL)

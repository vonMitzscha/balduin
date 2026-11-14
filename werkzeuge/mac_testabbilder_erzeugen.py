"""Erzeugt kleine Abbilder von Mac-Datenträgern (HFS+ und APFS) für die automatischen Tests (Entscheidung 09.11.2026).

Die Abbilder liegen gepackt in tests/daten/ (gzip), damit die Tests auch dort laufen, wo es kein hdiutil gibt (Windows,
Linux); tests/conftest.py entpackt sie in den Temp-Ordner. Neu erzeugen nur, wenn sich der Inhalt ändern soll, und nur
auf einem Mac:  .venv/bin/python werkzeuge/mac_testabbilder_erzeugen.py

Inhalt (gleich in beiden Abbildern; Volume-Namen MAC_HFS und MAC_APFS):
  Fotos/Zürich 1998/Übergabe/Bild ä.png   Umlaute (auf dem Mac in NFD gespeichert)
  Fotos/Zürich 1998/bunt.png
  Texte/Notiz 12:30.txt                   Doppelpunkt im Namen (im Finder „12/30“)
  Texte/leer.txt                          leere Datei
  Texte/Brief.pdf                         kleines PDF mit Text
  Archiv/alt.zip                          Archivdatei mit zwei Dateien (wird wie ein Ordner aufgelöst)
  Alt/Mit Resource Fork                   Datenzweig und Resource Fork
dazu legt macOS seine Verwaltungsordner an (.fseventsd u. a.), die Balduin auslässt.

Drittes Abbild mac_apfs_zwei.img (13.11.2026): ein APFS-Container mit zwei leeren Volumes, MAC_ZWEI und das
verschlüsselte GEHEIM (Passwort „Geheim-7f3a9c“), für die Wahl des Volumes und das Entsperren. APFS erlaubt je 512 MB
Container ein Volume, daher 1,1 GB (fast nur Nullen, gepackt rund 1 MB). Ohne Einhängen erzeugt: hdiutil legt Abbild
und erstes Volume an, diskutil fügt das zweite hinzu, während das Abbild ohne Einhängen angeschlossen ist.

hdiutil hängt die Abbilder beim Erzeugen kurz unter /Volumes ein; es berührt keine Quellplatte.
"""
import gzip
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path

from PIL import Image

CODE = Path(__file__).resolve().parent.parent
ZIEL = CODE / "tests" / "daten"

PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
       b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>"
       b"endobj\n4 0 obj<</Length 44>>stream\nBT /F1 12 Tf 20 50 Td (Brief aus Zuerich) Tj ET\nendstream endobj\n"
       b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")


def bestand(ordner):
    nfd = lambda s: unicodedata.normalize("NFD", s)
    fotos = ordner / nfd("Fotos/Zürich 1998")
    (fotos / nfd("Übergabe")).mkdir(parents=True)
    Image.new("RGB", (64, 48), (200, 30, 30)).save(fotos / nfd("Übergabe/Bild ä.png"))
    Image.new("RGB", (80, 60), (30, 120, 200)).save(fotos / "bunt.png")
    (ordner / "Texte").mkdir()
    (ordner / "Texte" / "Notiz 12:30.txt").write_text("Doppelpunkt im Namen\n", encoding="utf-8")
    (ordner / "Texte" / "leer.txt").write_bytes(b"")
    (ordner / "Texte" / "Brief.pdf").write_bytes(PDF)
    (ordner / "Archiv").mkdir()
    with zipfile.ZipFile(ordner / "Archiv" / "alt.zip", "w") as z:
        z.writestr("innen/eins.txt", "eins\n")
        z.writestr("innen/zwei.txt", "zwei zwei\n")
    (ordner / "Alt").mkdir()
    fork = ordner / "Alt" / "Mit Resource Fork"
    fork.write_text("Datenzweig\n", encoding="utf-8")
    subprocess.run(["xattr", "-wx", "com.apple.ResourceFork", ("RSRC" * 16).encode().hex(), str(fork)], check=True)


def main():
    if sys.platform != "darwin":
        raise SystemExit("Die Testabbilder lassen sich nur auf einem Mac erzeugen (hdiutil).")
    ZIEL.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        bestand(tmp / "bestand")
        for fs, name, datei in (("HFS+", "MAC_HFS", "mac_hfs.img"), ("APFS", "MAC_APFS", "mac_apfs.img")):
            dmg = tmp / f"{datei}.dmg"
            subprocess.run(["hdiutil", "create", "-quiet", "-srcfolder", str(tmp / "bestand"), "-fs", fs, "-format",
                            "UDRW", "-volname", name, str(dmg)], check=True)
            with open(dmg, "rb") as quelle, gzip.open(ZIEL / f"{datei}.gz", "wb", compresslevel=9) as ziel:
                shutil.copyfileobj(quelle, ziel)
            print(f"{datei}.gz: {dmg.stat().st_size / 1e6:.1f} MB, gepackt "
                  f"{(ZIEL / f'{datei}.gz').stat().st_size / 1e3:.0f} KB")



def zwei_volumes(ziel_gz):
    """mac_apfs_zwei.img: zwei Volumes, eines verschlüsselt (siehe oben); nichts wird eingehängt."""
    with tempfile.TemporaryDirectory() as tmp:
        dmg = Path(tmp) / "zwei.dmg"
        subprocess.run(["hdiutil", "create", "-quiet", "-size", "1100m", "-fs", "APFS", "-layout", "GPTSPUD",
                        "-volname", "MAC_ZWEI", "-type", "UDIF", str(dmg)], check=True)
        aus = subprocess.run(["diskutil", "image", "attach", "--noMount", str(dmg)], capture_output=True, text=True,
                             check=True).stdout.split("\n")
        abbild = aus[0].split()[0]
        container = next(z.split()[0] for z in aus if "Apple_APFS_Container" in z)
        try:
            info = subprocess.run(["diskutil", "info", container], capture_output=True, text=True).stdout
            if "Disk Image" not in info:                     # nie etwas anderes als das eben erzeugte Abbild ändern
                raise SystemExit(f"{container} ist kein Abbild")
            subprocess.run(["diskutil", "apfs", "addVolume", container, "APFS", "GEHEIM", "-passphrase", "Geheim-7f3a9c",
                            "-nomount"], check=True, capture_output=True)
        finally:
            subprocess.run(["diskutil", "eject", abbild], check=True, capture_output=True)
        with open(dmg, "rb") as quelle, gzip.open(ziel_gz, "wb", compresslevel=9) as ziel:
            shutil.copyfileobj(quelle, ziel)
    print(f"{ziel_gz.name}: gepackt {ziel_gz.stat().st_size / 1e3:.0f} KB")


if __name__ == "__main__":
    if "--zwei" in sys.argv:                                 # nur das dritte Abbild neu erzeugen
        zwei_volumes(ZIEL / "mac_apfs_zwei.img.gz")
        raise SystemExit
    main()

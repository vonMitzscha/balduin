"""Vorschau für Office-Dateien ohne Quick Look (Entscheidung 12.11.2026, docs/plan.md): eingebettete Vorschau aus der
Datei, sonst LibreOffice, wenn es installiert ist."""
import io
import sys
import zipfile

import pytest
from PIL import Image

from test_vorschau_pdf import PDF


def bild(format_, farbe=(200, 30, 30), groesse=(256, 181)):
    puffer = io.BytesIO()
    Image.new("RGB", groesse, farbe).save(puffer, format_)
    return puffer.getvalue()


def zipdatei(pfad, eintraege):
    with zipfile.ZipFile(pfad, "w") as z:
        for name, daten in eintraege.items():
            z.writestr(name, daten)
    return pfad


@pytest.mark.parametrize("name, eintraege", [
    ("Bericht.docx", {"[Content_Types].xml": b"<x/>", "word/document.xml": b"<x/>", "docProps/thumbnail.jpeg": bild("JPEG")}),
    ("Folien.pptx", {"[Content_Types].xml": b"<x/>", "docProps/thumbnail.png": bild("PNG")}),
    ("Text.odt", {"mimetype": b"application/vnd.oasis.opendocument.text", "Thumbnails/thumbnail.png": bild("PNG")}),
    ("Brief.pages", {"Index/Document.iwa": b"x", "preview.jpg": bild("JPEG")}),
    ("Alt.key", {"index.apxl": b"<x/>", "QuickLook/Thumbnail.jpg": bild("JPEG")}),
])
def test_eingebettete_vorschau(leeres_projekt, tmp_path, name, eintraege):
    from erfassung import vorschau
    vb, _ = vorschau.office_vorschau(zipdatei(tmp_path / name, eintraege))
    assert vb.mode == "RGB" and vb.size == (256, 181)               # nicht vergrößert
    assert vb.getpixel((10, 10))[0] > 150                           # das Bild aus der Datei


def test_ohne_eingebettete_vorschau(leeres_projekt, tmp_path):
    from erfassung import vorschau
    datei = zipdatei(tmp_path / "Bericht.docx", {"word/document.xml": b"<x/>"})
    with pytest.raises(RuntimeError, match="keine eingebettete"):
        vorschau.office_vorschau(datei)
    kein_zip = tmp_path / "Alt.doc"
    kein_zip.write_bytes(b"\xd0\xcf\x11\xe0 kein zip")
    with pytest.raises(RuntimeError):
        vorschau.office_vorschau(kein_zip)


def test_reihenfolge_fuer_office(leeres_projekt):
    from erfassung import vorschau
    assert [w.__name__ for w in vorschau.wege("dokument", "Bericht.docx")] == [
        "quicklook", "office_vorschau", "libreoffice", "eingebettet"]


def test_libreoffice_wenn_installiert(leeres_projekt, tmp_path, monkeypatch):
    """Ersatz-soffice schreibt ein PDF nach --outdir; Balduin rendert dessen erste Seite (Poppler)."""
    from erfassung import system, vorschau
    from hilfen.plattform import ersatzprogramm
    if not system.werkzeug_pfad("pdftoppm"):
        pytest.skip("Poppler fehlt")
    (tmp_path / "beispiel.pdf").write_bytes(PDF)
    soffice = ersatzprogramm(tmp_path / "lo", "soffice", f"""
import shutil, sys
from pathlib import Path
a = sys.argv[1:]
assert "--headless" in a and "--convert-to" in a and any(x.startswith("-env:UserInstallation=") for x in a)
ziel = Path(a[a.index("--outdir") + 1])
shutil.copy({str(tmp_path / 'beispiel.pdf')!r}, ziel / (Path(a[-1]).stem + ".pdf"))
""")
    echt_pfad, echt = vorschau.system.werkzeug_pfad, vorschau.system.werkzeug
    monkeypatch.setattr(vorschau.system, "werkzeug_pfad", lambda n: soffice if n == "soffice" else echt_pfad(n))
    monkeypatch.setattr(vorschau.system, "werkzeug", lambda n: soffice if n == "soffice" else echt(n))
    doc = tmp_path / "Bericht.doc"
    doc.write_bytes(b"\xd0\xcf\x11\xe0 alt")
    vb, _ = vorschau.libreoffice(doc)
    assert vb.mode == "RGB" and vb.size[0] > vb.size[1]


def test_ohne_libreoffice_klare_meldung(leeres_projekt, tmp_path, monkeypatch):
    from erfassung import vorschau
    monkeypatch.setattr(vorschau.system, "werkzeug_pfad", lambda name: None)
    with pytest.raises(RuntimeError, match="LibreOffice"):
        vorschau.libreoffice(tmp_path / "Bericht.doc")


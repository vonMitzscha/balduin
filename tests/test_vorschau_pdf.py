"""PDF-Vorschau „erste Seite“ über Poppler auf allen Systemen (Entscheidung 12.11.2026, docs/plan.md): Unter Windows
gibt es kein Quick Look; PDFs blieben dort ohne Vorschaubild."""
import pytest

PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
       b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 100]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>"
       b"endobj\n4 0 obj<</Length 44>>stream\nBT /F1 12 Tf 20 50 Td (Brief aus Zuerich) Tj ET\nendstream endobj\n"
       b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")


@pytest.fixture
def seite(leeres_projekt, monkeypatch):
    monkeypatch.setattr(leeres_projekt, "pdf_art", "seite")
    return leeres_projekt


def test_pdf_erste_seite_kommt_zuerst_ueber_poppler(seite):
    from erfassung import vorschau
    namen = [w.__name__ for w in vorschau.wege("dokument", "Texte/Brief.pdf")]
    assert namen[0] == "pdf_erste_seite" and "quicklook" in namen          # Quick Look nur noch Rückfall (Mac)


def test_andere_dokumente_bleiben_wie_bisher(seite):
    from erfassung import vorschau
    assert vorschau.wege("dokument", "Texte/Brief.docx")[0].__name__ == "quicklook"


def test_pdf_erste_seite_rendert_ein_bild(seite, tmp_path):
    from erfassung import system, vorschau
    if not system.werkzeug_pfad("pdftoppm"):
        pytest.skip("Poppler fehlt")
    pdf = tmp_path / "Brief.pdf"
    pdf.write_bytes(PDF)
    bild, groesse = vorschau.pdf_erste_seite(pdf)
    assert bild.mode == "RGB" and max(bild.size) <= vorschau.VORSCHAU_PX and bild.size[0] > bild.size[1]

"""D3 Virenscan: verständliche Meldungen, wenn ClamAV nicht startet oder freshclam scheitert.
Anlass (06.11.2026): ClamAV 1.5.4_1 mit OpenSSL 4 verwarf jede Signaturdatei; die Meldung sagte nur
„clamd startet nicht, Meldungen im Log“ und „ohne Internet?“, obwohl das Internet da war."""
import pytest

from erfassung import virenscan as v


def _programm(tmp_path, name, text, code):
    """Kleines Ersatzprogramm, das text auf stderr schreibt und mit code endet (macOS und Windows)."""
    from hilfen.plattform import ersatzprogramm
    text = text.encode().decode("unicode_escape")              # „\\n“ in den Aufrufen steht für einen Zeilenumbruch
    return ersatzprogramm(tmp_path, name, f"import sys\nsys.stderr.write({text!r})\nsys.exit({code})\n")


def test_clamd_fehler_nennt_ursache_und_logdatei(tmp_path, monkeypatch):
    clamd = _programm(tmp_path, "clamd", "LibClamAV Error: Can't load daily.cld: Malformed database\\n"
                                         "ERROR: Malformed database\\n", 1)
    monkeypatch.setattr(v, "clamav_programm", lambda name: clamd)
    logdatei = tmp_path / "clamav_T01_test.log"
    with open(logdatei, "w", encoding="utf-8") as log, pytest.raises(RuntimeError) as fehler:
        v.Clamd(1, log)
    meldung = str(fehler.value)
    assert "Malformed database" in meldung
    assert "clamav_T01_test.log" in meldung


def test_freshclam_fehler_wird_genannt(tmp_path, monkeypatch, capsys):
    freshclam = _programm(tmp_path, "freshclam", "ERROR: Database test FAILED.\\nERROR: Update failed.\\n", 1)
    monkeypatch.setattr(v, "clamav_programm", lambda name: freshclam)
    monkeypatch.setattr(v.system, "signaturen_selbst_auffrischen", lambda: True)   # Linux: sonst der Dienst
    monkeypatch.setattr(v, "clamav_stand", lambda: "ClamAV 1.5.4/28174/Thu Nov  5 07:26:24 2026")
    v.signaturen_auffrischen(hoechstens_tage=0)
    ausgabe = capsys.readouterr().out
    assert "Database test FAILED" in ausgabe
    assert "ohne Internet?" not in ausgabe

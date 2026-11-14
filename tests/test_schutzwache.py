"""Die Schutzwache selbst (tests/schutz/schutzwache.py): Sie muss jeden Zugriff auf /Volumes erkennen.
Geprüft wird nur die Prüffunktion; kein Test greift dafür wirklich auf /Volumes zu."""
import os
import subprocess

import pytest
import schutzwache

from conftest import PYTHON, SCHUTZ_PROTOKOLL


def test_wache_ist_im_testprozess_eingeschaltet():
    assert schutzwache.aktiv()


@pytest.mark.parametrize("ereignis, args", [
    ("open", ("/Volumes/HD01/Fotos/a.jpg", "r", os.O_RDONLY)),          # auch Lesen ist in Tests gesperrt
    ("open", ("/Volumes/HD01/neu.txt", "w", os.O_WRONLY | os.O_CREAT)),
    ("open", (b"/Volumes/HD01/a", None, os.O_RDWR)),
    ("os.remove", ("/Volumes/HD01/a.jpg", -1)),
    ("os.rename", ("/Volumes/HD01/a.jpg", "/Volumes/HD01/b.jpg", -1, -1)),
    ("os.mkdir", ("/Volumes/HD01/neu", 0o777, -1)),
    ("os.utime", ("/Volumes/HD01/a.jpg", None, None, -1)),
    ("os.listdir", ("/Volumes",)),
    ("shutil.rmtree", ("/Volumes/HD01",)),
    ("shutil.copyfile", ("/tmp/a", "/Volumes/HD01/a")),
    ("subprocess.Popen", ("touch", ["touch", "/Volumes/HD01/x"], None, None)),
    ("subprocess.Popen", ("/bin/sh", ["/bin/sh", "-c", "ls /Volumes/HD01"], None, None)),
    ("os.system", ("rm -rf /Volumes/HD01/tmp",)),
])
def test_zugriffe_auf_volumes_werden_abgewiesen(ereignis, args, monkeypatch, tmp_path):
    monkeypatch.setenv("BALDUIN_SCHUTZ_PROTOKOLL", str(tmp_path / "eigenes.log"))   # nicht das echte Protokoll füllen
    with pytest.raises(PermissionError, match="Schutzwache"):
        schutzwache.pruefen(ereignis, args)
    assert "Volumes" in (tmp_path / "eigenes.log").read_text(encoding="utf-8")


@pytest.mark.parametrize("ereignis, args", [
    ("open", ("/private/tmp/a.txt", "w", os.O_WRONLY | os.O_CREAT)),
    ("open", ("/Users/test/Volumes/a.txt", "w", os.O_WRONLY)),          # „Volumes“ nur als Teil eines Namens
    ("open", ("/VolumesX/a", "r", os.O_RDONLY)),
    ("open", (3, "r", os.O_RDONLY)),                                     # Dateideskriptor statt Pfad
    ("os.remove", ("/private/tmp/a", -1)),
    ("subprocess.Popen", ("sf", ["sf", "-json", "/private/tmp/volumes/HD01"], None, None)),
])
def test_andere_pfade_bleiben_erlaubt(ereignis, args):
    schutzwache.pruefen(ereignis, args)


def test_wache_laeuft_auch_in_unterprozessen(tmp_path):
    """Jeder Python-Unterprozess der Tests (Server, Hintergrundläufe) lädt die Wache über sitecustomize."""
    e = subprocess.run([PYTHON, "-c", "import schutzwache; print(schutzwache.aktiv())"], capture_output=True,
                       text=True, env={**os.environ, "BALDUIN_SCHUTZ_PROTOKOLL": str(tmp_path / "eigenes.log")})
    assert e.stdout.strip() == "True", e.stderr


def test_verstoss_im_unterprozess_wird_auch_abgefangen_gemeldet(tmp_path):
    """Fängt der Code den Fehler selbst ab, steht der Verstoß trotzdem im Protokoll (dort prüft conftest.py)."""
    log = tmp_path / "eigenes.log"
    code = ("import schutzwache\ntry:\n    schutzwache.pruefen('os.remove', ('/Volumes/HD01/a', -1))\n"
            "except PermissionError:\n    pass\n")
    subprocess.run([PYTHON, "-c", code], env={**os.environ, "BALDUIN_SCHUTZ_PROTOKOLL": str(log)}, check=True)
    assert "/Volumes/HD01/a" in log.read_text(encoding="utf-8")
    assert SCHUTZ_PROTOKOLL.read_text(encoding="utf-8") == ""          # das gemeinsame Protokoll bleibt leer


# ---------- Windows (Test in der VM vom 12.11.2026) ----------

@pytest.mark.parametrize("pfad", ["C:\\Volumes\\HD01\\a.jpg", "c:/Volumes/HD01", "\\Volumes\\HD01\\a"])
def test_volumes_auch_in_windows_schreibweise(pfad, monkeypatch, tmp_path):
    monkeypatch.setenv("BALDUIN_SCHUTZ_PROTOKOLL", str(tmp_path / "eigenes.log"))
    with pytest.raises(PermissionError, match="Schutzwache"):
        schutzwache.pruefen("open", (pfad, "r", os.O_RDONLY))


def test_fremde_laufwerke_unter_windows_gesperrt(monkeypatch, tmp_path):
    """Unter Windows hängen Datenträger als Laufwerksbuchstaben: gesperrt sind alle außer System, Temp, Code und
    Python (schutzwache.einschalten bestimmt sie)."""
    monkeypatch.setenv("BALDUIN_SCHUTZ_PROTOKOLL", str(tmp_path / "eigenes.log"))
    monkeypatch.setattr(schutzwache, "GESPERRTE_LAUFWERKE", {"E:"})
    for verboten in ("E:\\Fotos\\a.jpg", "e:/x", "E:"):
        with pytest.raises(PermissionError, match="Schutzwache"):
            schutzwache.pruefen("open", (verboten, "r", os.O_RDONLY))
    with pytest.raises(PermissionError):
        schutzwache.pruefen("subprocess.Popen", ("sf", ["sf", "E:\\Fotos"], None, None))
    schutzwache.pruefen("open", ("C:\\Users\\balduin\\a.txt", "r", os.O_RDONLY))


def test_gesperrte_laufwerke_ohne_system_temp_und_code(monkeypatch):
    monkeypatch.setattr(schutzwache.sys, "platform", "win32")
    monkeypatch.setattr(schutzwache, "alle_laufwerke", lambda: ["C:\\", "D:\\", "E:\\", "F:\\"])
    monkeypatch.setattr(schutzwache, "erlaubte_orte", lambda: ["C:\\Windows", "D:\\a\\balduin", "c:\\Temp"])
    assert schutzwache.gesperrte_laufwerke() == {"E:", "F:"}

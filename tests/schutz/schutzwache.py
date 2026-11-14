"""Schutzwache für die automatischen Tests: Kein Test darf echte Datenträger unter /Volumes berühren (harte Regel 1);
unter Linux ebenso /media, /run/media, /mnt und Gerätedateien von Platten (/dev/sd…, /dev/nvme…, auf dem Mac /dev/disk…).

Python meldet heikle Vorgänge (Datei öffnen, löschen, umbenennen, Programm starten …) als „Audit-Ereignis“
(sys.addaudithook, PEP 578). Die Wache prüft jedes dieser Ereignisse: Zeigt es auf einen Pfad unter /Volumes,
bricht sie mit PermissionError ab. Auch Lesen ist gesperrt; Tests arbeiten nur mit Testplatten im Temp-Ordner.

Eingeschaltet wird sie
- im Testprozess von tests/conftest.py,
- in jedem Python-Unterprozess (Server, Hintergrundläufe) über tests/schutz/sitecustomize.py, weil conftest.py
  diesen Ordner in PYTHONPATH setzt.
Fängt der Code einen solchen Fehler selbst ab, ginge er unter. Deshalb schreibt die Wache jeden Verstoß zusätzlich in
die Datei aus BALDUIN_SCHUTZ_PROTOKOLL; conftest.py lässt den Testlauf scheitern, wenn dort etwas steht.
"""
import os
import posixpath
import re
import sys

GESPERRT = "/Volumes"
# Linux (Entscheidung 13.11.2026): Mountpunkte von Datenträgern und Gerätedateien von Platten (auch /dev/disk* des Mac)
GESPERRT_LINUX = ("/media", "/run/media", "/mnt")
GERAETE = re.compile(r"/dev/(r?disk\d|sd[a-z]|nvme\d|mmcblk\d|hd[a-z]|vd[a-z])")
MARKEN = ("Volumes", "/media", "/mnt", "/dev/")
# Schreib-Bits von os.open: wer eines davon setzt, will schreiben oder anlegen
SCHREIBEN = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

# Ereignisse, deren Argumente Pfade sind (die übrigen Argumente sind Zahlen oder Flags)
PFAD_EREIGNISSE = {
    "open", "os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.chown", "os.utime", "os.truncate", "os.link",
    "os.symlink", "os.rename", "os.listdir", "os.scandir", "os.chdir", "os.setxattr", "os.removexattr",
    "shutil.rmtree", "shutil.copyfile", "shutil.copytree", "shutil.move", "shutil.copymode", "shutil.copystat",
    "shutil.chown", "shutil.make_archive", "shutil.unpack_archive",
}
BEFEHL_EREIGNISSE = {"subprocess.Popen", "os.system", "os.posix_spawn", "os.exec", "os.spawn"}

_aktiv = False
# Windows: Datenträger hängen als Laufwerksbuchstaben; gesperrt sind alle außer denen von System, Temp, Code und Python
GESPERRTE_LAUFWERKE = set()


def unter_volumes(wert):
    """Ist wert (Text, Bytes oder Pfad) ein Pfad unter /Volumes? Relative Pfade gelten vom aktuellen Ordner aus."""
    if isinstance(wert, int) or wert is None:
        return False
    try:
        text = os.fsdecode(os.fspath(wert))
    except TypeError:
        return False
    if not text:
        return False
    # „\\“ und „/“ gelten gleich, ebenso C:\\Volumes; Windows: gesperrte Laufwerke
    text = text.replace("\\", "/")
    laufwerk = re.match(r"([A-Za-z]):", text)
    if laufwerk:
        if laufwerk.group(1).upper() + ":" in GESPERRTE_LAUFWERKE:
            return True
        text = text[2:] or "/"
    elif text.startswith("//"):                        # Netz- und Gerätepfade (\\server, \\.\\…) nicht hier
        return False
    if not text.startswith("/"):
        hier = re.sub(r"^[A-Za-z]:", "", os.getcwd().replace("\\", "/"))
        text = hier.rstrip("/") + "/" + text
    pfad = posixpath.normpath(text)
    return (any(pfad == g or pfad.startswith(g + "/") for g in (GESPERRT, *GESPERRT_LINUX))
            or GERAETE.match(pfad) is not None)


def texte_in(wert):
    """Alle Texte in einem Argument eines Befehls (Listen werden aufgefaltet)."""
    if isinstance(wert, (list, tuple)):
        for x in wert:
            yield from texte_in(x)
    elif isinstance(wert, (str, bytes, os.PathLike)):
        yield os.fsdecode(os.fspath(wert))


def pruefen(ereignis, args):
    """Wirft PermissionError, wenn ein Ereignis /Volumes berührt; sonst nichts. Allein aufrufbar (für Tests)."""
    if ereignis in PFAD_EREIGNISSE:
        for a in args:
            if unter_volumes(a):
                verstoss(ereignis, a)
    elif ereignis in BEFEHL_EREIGNISSE:
        for text in texte_in(list(args[:3])):
            # Befehlszeilen und Argumente: jeder Teil, der mit /Volumes beginnt oder es enthält
            if (any(m in text for m in MARKEN) or GESPERRTE_LAUFWERKE) and any(unter_volumes(t) for t in text.split() + [text]):
                verstoss(ereignis, text)


def verstoss(ereignis, wert):
    meldung = f"Schutzwache: {ereignis} auf {os.fsdecode(os.fspath(wert)) if not isinstance(wert, str) else wert} " \
              f"(Tests dürfen /Volumes nicht berühren)"
    protokoll = os.environ.get("BALDUIN_SCHUTZ_PROTOKOLL")
    if protokoll:
        try:
            # direkt über os.open, damit das Schreiben selbst nicht wieder geprüft wird (liegt nie unter /Volumes)
            fd = os.open(protokoll, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(fd, (f"{os.getpid()}\t{meldung}\n").encode())
            finally:
                os.close(fd)
        except OSError:
            pass
    raise PermissionError(meldung)


def _haken(ereignis, args):
    if ereignis in PFAD_EREIGNISSE or ereignis in BEFEHL_EREIGNISSE:
        pruefen(ereignis, args)


def alle_laufwerke():
    return os.listdrives() if hasattr(os, "listdrives") else []


def erlaubte_orte():
    """Orte, die Tests brauchen: System, Temp, Code, Python (und das venv)."""
    import tempfile
    return [os.environ.get("SystemDrive", "C:") + "\\", tempfile.gettempdir(), os.getcwd(), sys.prefix,
            sys.base_prefix, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]


def gesperrte_laufwerke():
    """Windows: alle Laufwerke außer denen der erlaubten Orte; sonst keine."""
    if sys.platform != "win32":
        return set()
    erlaubt = {o[:2].upper() for o in erlaubte_orte() if re.match(r"[A-Za-z]:", o)}
    return {w[:2].upper() for w in alle_laufwerke()} - erlaubt


def einschalten():
    """Wache im laufenden Prozess einschalten (einmal; Audit-Haken lassen sich nicht wieder entfernen)."""
    global _aktiv, GESPERRTE_LAUFWERKE
    if not _aktiv:
        GESPERRTE_LAUFWERKE = gesperrte_laufwerke()
        sys.addaudithook(_haken)
        _aktiv = True


def aktiv():
    return _aktiv

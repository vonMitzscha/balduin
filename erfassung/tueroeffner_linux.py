"""Türöffner für physische Platten unter Linux (Entscheidung 13.11.2026, docs/plan.md).

Linux lässt eine ganze Platte (/dev/sdX) meist nur root oder die Gruppe „disk“ lesen. Damit nicht der ganze Lauf (mit
ExifTool, ffmpeg und den Dateisystem-Bibliotheken über fremden Daten) als root läuft, startet erfassung/system.py nur
dieses kleine Skript über pkexec (Rückfrage nach dem Administratorpasswort). Es
1. prüft den Auftrag (nur ganze Platten, nur ein Socket mit absolutem Pfad),
2. öffnet die Platte nur zum Lesen und prüft, dass es ein Blockgerät ist,
3. reicht den Zugriff über den Unix-Socket an den Lauf weiter, der es gerufen hat (SCM_RIGHTS), und beendet sich.
Es liest keine Daten und schreibt nichts. Der Socket liegt in einem Ordner, den nur der Benutzer und root öffnen.
Aufruf (nur von system.py):
    pkexec python -I erfassung/tueroeffner_linux.py /dev/sdX <Socket>
Nur Standardbibliothek; wird als Skript gestartet, nicht über das Paket erfassung.
"""
import os
import re
import socket
import stat
import sys

MUSTER = re.compile(r"/dev/(sd[a-z]{1,3}|nvme\d+n\d+|mmcblk\d+|vd[a-z]{1,3}|hd[a-z])")


def auftrag_pruefen(argumente):
    """(Gerät, Socket) oder ValueError."""
    if len(argumente) != 2:
        raise ValueError("Aufruf: tueroeffner_linux.py /dev/sdX <Socket>")
    geraet, adresse = argumente
    if not MUSTER.fullmatch(geraet):
        raise ValueError(f"Nur ganze Datenträger (/dev/sdX, /dev/nvmeNnM, /dev/mmcblkN), nicht {geraet!r}.")
    if not os.path.isabs(adresse) or ".." in adresse.split("/"):
        raise ValueError("Der Socket braucht einen absoluten Pfad.")
    return geraet, adresse


def ist_blockgeraet(fd):
    return stat.S_ISBLK(os.fstat(fd).st_mode)


def main(argumente=None):
    geraet, adresse = auftrag_pruefen(sys.argv[1:] if argumente is None else argumente)
    fd = None
    try:
        fd = os.open(geraet, os.O_RDONLY | os.O_CLOEXEC)
        if not ist_blockgeraet(fd):
            raise OSError(f"{geraet} ist kein Blockgerät.")
        nachricht, weiter = b"ok", [fd]
    except OSError as e:
        nachricht, weiter = f"{geraet} lässt sich nicht öffnen: {e}".encode(), []
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.connect(adresse)
            socket.send_fds(s, [nachricht], weiter)
    finally:
        if fd is not None:
            os.close(fd)                  # der weitergereichte Zugriff im Lauf bleibt gültig


if __name__ == "__main__":
    main()

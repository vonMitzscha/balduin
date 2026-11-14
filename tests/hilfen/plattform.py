"""Hilfen, damit die Tests auf macOS und Windows laufen (Windows-Test vom 12.11.2026, docs/test_windows.md)."""
import os
import sys
from pathlib import Path


def ersatzprogramm(ordner, name, python_code):
    """Legt ein ausführbares Ersatzprogramm an, das python_code mit demselben Python ausführt (Argumente in sys.argv).
    macOS/Linux: Shell-Skript; Windows: .bat (shutil.which findet es über PATHEXT). Antwort: Pfad als Text."""
    ordner = Path(ordner)
    ordner.mkdir(parents=True, exist_ok=True)
    skript = ordner / f"{name}_ersatz.py"
    skript.write_text(python_code, encoding="utf-8")
    if sys.platform == "win32":
        datei = ordner / f"{name}.bat"
        datei.write_text(f'@"{sys.executable}" "{skript}" %*\r\n', encoding="utf-8")
    else:
        datei = ordner / name
        datei.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{skript}" "$@"\n', encoding="utf-8")
        datei.chmod(0o755)
    return str(datei)


def gleicher_pfad(a, b):
    """Gleicher Pfad trotz Groß-/Kleinschreibung (Windows meldet Endungen aus PATHEXT groß: .BAT)."""
    return os.path.normcase(os.path.abspath(str(a))) == os.path.normcase(os.path.abspath(str(b)))


def git_repo(ordner):
    """Gibt es Git und ist ordner ein Git-Repo? (Die Windows-VM bekommt den Code als Archiv, ohne Git.)"""
    import shutil
    return shutil.which("git") is not None and (Path(ordner) / ".git").exists()


def kann_verknuepfen(ordner):
    """Darf dieser Prozess symbolische Verknüpfungen anlegen? (Windows nur mit Administratorrechten oder
    Entwicklermodus)"""
    ziel, verweis = Path(ordner) / "_ziel", Path(ordner) / "_verweis"
    ziel.mkdir(exist_ok=True)
    try:
        verweis.symlink_to(ziel, target_is_directory=True)
    except OSError:
        return False
    finally:
        if verweis.is_symlink():
            verweis.unlink()
        ziel.rmdir()
    return True

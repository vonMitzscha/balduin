"""Plattformabhängiges an einer Stelle (erfassung/system.py; Entscheidungen 30.10. und 09.11.2026, docs/plan.md).

Die Mac-Seite läuft echt (auf Ordnern im Temp-Ordner statt /Volumes). Die Windows-Seite wird hier mit
nachgestellten Antworten der Win32-Schicht (system._win_…) geprüft: Welche Funktion wird gerufen, was kommt
heraus, und vor allem, dass nichts Gefährliches passiert (os.kill(pid, 0) beendet unter Windows einen Prozess).
Echt geprüft wird Windows erst auf einem Windows-Rechner."""
import json
import os
import signal
import socket
import sqlite3
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from erfassung import system

ECHT_PLATTE_HINTER = system._win_platte_hinter


@pytest.fixture
def windows(monkeypatch):
    """Tut so, als liefe Balduin unter Windows (nur system.windows/mac; die Win32-Schicht stellt der Test nach)."""
    monkeypatch.setattr(system, "windows", lambda: True)
    monkeypatch.setattr(system, "mac", lambda: False)
    monkeypatch.setattr(system, "linux", lambda: False)
    monkeypatch.setattr(system, "_win_platte_hinter", lambda wurzel: {})   # Tests, die sie brauchen, stellen sie nach
    return monkeypatch


@pytest.fixture
def macos(monkeypatch):
    """Tut so, als liefe Balduin auf dem Mac (Gegenstück zu windows): prüft den Mac-Zweig auch unter Windows."""
    monkeypatch.setattr(system, "windows", lambda: False)
    monkeypatch.setattr(system, "mac", lambda: True)
    monkeypatch.setattr(system, "linux", lambda: False)
    return monkeypatch


NUR_MAC = pytest.mark.skipif(sys.platform != "darwin", reason="braucht echte Mac-Systemfunktionen")
NICHT_WINDOWS = pytest.mark.skipif(sys.platform == "win32", reason="gibt es unter Windows nicht")


def verboten(*a, **k):
    raise AssertionError("darf unter Windows nicht gerufen werden")


# ---------- Prozesse (Fehler 1–3) ----------

def test_lebt_auf_dem_mac():
    assert system.lebt(os.getpid())
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    assert not system.lebt(p.pid)
    assert not system.lebt(None) and not system.lebt(0) and not system.lebt("x")


def test_lebt_unter_windows_ohne_os_kill(windows):
    """Fehler 1: os.kill(pid, 0) ruft unter Windows TerminateProcess; lebt() fragt dort nur nach."""
    windows.setattr(system.os, "kill", verboten)
    windows.setattr(system, "_win_prozess_lebt", lambda pid: pid == 4711)
    assert system.lebt(4711) is True
    assert system.lebt(4712) is False


@NICHT_WINDOWS
def test_unterbrechen_schickt_sigint_auf_dem_mac(tmp_path):
    skript = tmp_path / "warten.py"
    skript.write_text(textwrap.dedent("""
        import sys, time
        print("bereit", flush=True)
        try:
            time.sleep(30)
        except KeyboardInterrupt:
            print("unterbrochen", flush=True)
    """), encoding="utf-8")
    p = subprocess.Popen([sys.executable, str(skript)], stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "bereit"
    assert system.unterbrechen(p.pid) is True
    assert p.communicate(timeout=10)[0].strip() == "unterbrochen"


def test_unterbrechen_unter_windows_schickt_nichts(windows):
    """Fehler 2: os.kill(pid, SIGINT) wäre unter Windows ein harter Abbruch; dort gilt nur die Marke lauf.abbrechen."""
    windows.setattr(system.os, "kill", verboten)
    windows.setattr(system, "_win_prozess_lebt", lambda pid: True)
    assert system.unterbrechen(4711) is False


def test_hintergrund_starten_eigene_sitzung_auf_dem_mac(tmp_path, monkeypatch, macos):
    gesehen = {}
    monkeypatch.setattr(system.subprocess, "Popen", lambda befehl, **k: gesehen.update(k) or "prozess")
    assert system.hintergrund_starten(["x"], cwd=tmp_path) == "prozess"
    assert gesehen["start_new_session"] is True and "creationflags" not in gesehen
    assert gesehen["stdin"] == gesehen["stdout"] == gesehen["stderr"] == subprocess.DEVNULL


def test_hintergrund_starten_unter_windows_eigene_prozessgruppe_ohne_fenster(windows, tmp_path):
    """Fehler 3: start_new_session wirkt unter Windows nicht; dort eigene Prozessgruppe ohne Konsolenfenster."""
    gesehen = {}
    windows.setattr(system.subprocess, "Popen", lambda befehl, **k: gesehen.update(k) or "prozess")
    system.hintergrund_starten(["x"], cwd=tmp_path)
    assert "start_new_session" not in gesehen
    assert gesehen["creationflags"] == system.CREATE_NEW_PROCESS_GROUP | system.CREATE_NO_WINDOW
    assert system.prozess_optionen() == {"creationflags": system.CREATE_NO_WINDOW}


def test_prozess_optionen_auf_dem_mac_leer(macos):
    assert system.prozess_optionen() == {}


def test_lauf_befehl():
    """Läufe im UTF-8-Modus von Python: unter Windows wäre sonst cp1252 die Kodierung von Dateien und Konsole."""
    assert system.lauf_befehl("erfassen", "--lauf", 3) == [sys.executable, "-X", "utf8", "-m", "erfassung.lauf",
                                                           "erfassen", "--lauf", "3"]


# ---------- Abbruchwache (Fehler 2, plattformneutral) ----------

def test_abbruchwache_unterbricht_den_lauf_ueber_die_marke(tmp_path):
    """Ohne Signal: Die Wache liest lauf.abbrechen und unterbricht den Lauf wie Ctrl+C (so bricht Windows ab)."""
    db = tmp_path / "inventar.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE lauf (lauf_id INTEGER PRIMARY KEY, abbrechen INTEGER DEFAULT 0)")
    con.execute("INSERT INTO lauf (lauf_id) VALUES (1)")
    con.commit()
    con.close()
    skript = tmp_path / "lauf.py"
    skript.write_text(textwrap.dedent(f"""
        import signal, sys, time
        sys.path.insert(0, {str(Path(system.__file__).parent.parent)!r})
        from erfassung import lauf
        signal.signal(signal.SIGINT, lauf.unterbrechen)
        wache = lauf.abbruchwache({str(db)!r}, 1, takt=0.1)
        print("bereit", flush=True)
        try:
            for _ in range(300):
                time.sleep(0.1)
            print("nicht unterbrochen", flush=True)
        except KeyboardInterrupt:
            print("unterbrochen", lauf.ABBRUCH, flush=True)
        wache.set()
    """), encoding="utf-8")
    p = subprocess.Popen([sys.executable, str(skript)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         cwd=tmp_path)
    assert p.stdout.readline().strip() == "bereit", p.stderr.read()
    with sqlite3.connect(db) as con:
        con.execute("UPDATE lauf SET abbrechen = 1")
    aus, fehler = p.communicate(timeout=20)
    assert aus.strip() == "unterbrochen True", fehler


def test_spaetes_unterbrechen_nach_dem_lauf_wirft_nicht(monkeypatch):
    """Kommt Signal oder Wache erst, wenn der Lauf schon abschließt, bleibt es bei der Marke (kein KeyboardInterrupt
    mitten im Schreiben des Endstands)."""
    from erfassung import lauf
    monkeypatch.setattr(lauf, "ENDE", True)
    monkeypatch.setattr(lauf, "ABBRUCH", False)
    lauf.unterbrechen(signal.SIGINT, None)
    assert lauf.ABBRUCH is True
    monkeypatch.setattr(lauf, "ENDE", False)
    with pytest.raises(KeyboardInterrupt):
        lauf.unterbrechen(signal.SIGINT, None)


# ---------- Schreibschutz (Fehler 5) ----------

def test_schreibschutz_auf_dem_mac(tmp_path):
    assert system.ist_schreibgeschuetzt(tmp_path) is False


def test_schreibschutz_unter_windows_ueber_volumeangaben(windows, tmp_path):
    """Fehler 5: os.statvfs gibt es unter Windows nicht; dort das Kennzeichen FILE_READ_ONLY_VOLUME des Laufwerks."""
    windows.setattr(system.os, "statvfs", verboten, raising=False)
    flags = {"E:\\": system.FILE_READ_ONLY_VOLUME | 0x2, "F:\\": 0x2}
    windows.setattr(system, "_win_volume", lambda wurzel: ("NAME", 0x1234ABCD, flags[wurzel], "NTFS"))
    windows.setattr(system, "_wurzel", lambda pfad: str(pfad))
    assert system.ist_schreibgeschuetzt("E:\\") is True
    assert system.ist_schreibgeschuetzt("F:\\") is False


# ---------- Datenträger ----------

def test_datentraeger_liste_in_tests_unterordner(tmp_path):
    (tmp_path / "HD01").mkdir()
    (tmp_path / "HD02").mkdir()
    (tmp_path / ".versteckt").mkdir()
    (tmp_path / "datei.txt").write_text("x", encoding="utf-8")
    from hilfen.plattform import kann_verknuepfen
    if kann_verknuepfen(tmp_path):                      # Windows: Verknüpfungen nur mit besonderen Rechten
        (tmp_path / "Verweis").symlink_to(tmp_path / "HD01")
    assert [p.name for p in system.datentraeger_liste(tmp_path)] == ["HD01", "HD02"]
    assert system.datentraeger_liste(tmp_path / "fehlt") == []


def test_ist_datentraeger_und_datentraeger_von_in_tests(tmp_path):
    assert system.ist_datentraeger(tmp_path / "HD01", tmp_path)
    assert not system.ist_datentraeger(tmp_path / "HD01" / "Fotos", tmp_path)
    assert system.datentraeger_von(tmp_path / "HD01" / "Fotos" / "a.jpg", tmp_path) == tmp_path / "HD01"
    assert system.datentraeger_von(Path.home() / "x", tmp_path) is None


@NUR_MAC
def test_datentraeger_auf_dem_mac():
    assert system.VOLUMES == Path("/Volumes")
    assert system.ist_datentraeger(Path("/Volumes/Arbeit"))
    assert not system.ist_datentraeger(Path("/Volumes/Arbeit/Daten"))
    assert system.datentraeger_von(Path("/Volumes/Arbeit/Daten/x")) == Path("/Volumes/Arbeit")
    assert system.datentraeger_von(Path("/Users/x")) is None


def test_datentraeger_unter_windows_sind_laufwerksbuchstaben(windows):
    from pathlib import PureWindowsPath as W
    windows.setattr(system, "Path", W)
    windows.setattr(system, "_win_laufwerke", lambda: ["C:\\", "D:\\", "E:\\", "Z:\\"])
    windows.setattr(system, "_win_laufwerkstyp", lambda w: {"Z:\\": system.DRIVE_REMOTE}.get(w, system.DRIVE_FIXED))
    windows.setattr(system, "_systemlaufwerk", lambda: "C:")
    windows.setattr(system.os.path, "isdir", lambda p: True)
    assert [str(p) for p in system.datentraeger_liste(system.VOLUMES)] == ["D:\\", "E:\\"]
    assert system.ist_datentraeger(W("E:\\"))
    assert not system.ist_datentraeger(W("C:\\"))              # Systemlaufwerk ist kein Quelldatenträger
    assert not system.ist_datentraeger(W("E:\\Fotos"))
    assert system.datentraeger_von(W("E:\\Fotos\\a.jpg")) == W("E:\\")
    assert system.datentraeger_von(W("C:\\Users\\x")) is None


def test_datentraeger_info_unter_windows_mit_schluesseln_von_diskutil(windows):
    windows.setattr(system, "_wurzel", lambda pfad: "E:\\")
    windows.setattr(system, "_win_volume", lambda w: ("HD01", 0x1234ABCD, system.FILE_READ_ONLY_VOLUME, "NTFS"))
    windows.setattr(system, "_win_laufwerkstyp", lambda w: system.DRIVE_REMOVABLE)
    windows.setattr(system.shutil, "disk_usage", lambda w: (1000, 400, 600))
    info = system.datentraeger_info("E:\\")
    assert info["VolumeName"] == "HD01" and info["VolumeUUID"] == "1234-ABCD"
    assert info["FilesystemName"] == "NTFS" and info["TotalSize"] == 1000 and info["FreeSpace"] == 600
    assert info["DeviceIdentifier"] == "E:" and info["MountPoint"] == "E:\\"
    assert system.traegerart(info) == "usb"
    windows.setattr(system, "_win_laufwerkstyp", lambda w: system.DRIVE_CDROM)
    assert system.traegerart(system.datentraeger_info("E:\\")) == "cd"
    windows.setattr(system, "_win_laufwerkstyp", lambda w: system.DRIVE_FIXED)
    assert system.traegerart(system.datentraeger_info("E:\\")) == "festplatte"


def test_datentraeger_info_unter_windows_ohne_laufwerk_leer(windows):
    windows.setattr(system, "_wurzel", lambda pfad: "E:\\")

    def fehlt(w):
        raise OSError("kein Datenträger")
    windows.setattr(system, "_win_volume", fehlt)
    assert system.datentraeger_info("E:\\") == {}


def test_einhaengen_unter_windows_meldet_writeblocker(windows):
    windows.setattr(system.subprocess, "run", verboten)
    with pytest.raises(RuntimeError, match="Writeblocker"):
        system.nur_lesend_einhaengen("E:\\")


def test_unsichtbare_mounts_nur_auf_dem_mac(windows):
    windows.setattr(system.subprocess, "run", verboten)
    assert system.unsichtbare_mounts() == set()


# ---------- Werkzeuge ----------

def ausfuehrbar(ordner, name):
    from hilfen.plattform import ersatzprogramm
    return ersatzprogramm(ordner, name, "print('ok')\n")


def test_werkzeug_zuerst_aus_balduin_werkzeuge(tmp_path, monkeypatch):
    """Das spätere Paket legt die Werkzeuge mit; sie gehen dem Suchpfad (Homebrew) vor."""
    eigen = ausfuehrbar(tmp_path / "paket", "exiftool")
    ausfuehrbar(tmp_path / "pfad", "exiftool")
    monkeypatch.setenv("BALDUIN_WERKZEUGE", str(tmp_path / "paket"))
    monkeypatch.setenv("PATH", str(tmp_path / "pfad"))
    from hilfen.plattform import gleicher_pfad
    assert gleicher_pfad(system.werkzeug_pfad("exiftool"), eigen)
    assert gleicher_pfad(system.werkzeug("exiftool"), eigen)


def test_werkzeug_aus_dem_suchpfad_und_homebrew(tmp_path, monkeypatch):
    monkeypatch.delenv("BALDUIN_WERKZEUGE", raising=False)
    monkeypatch.setattr(system, "CODE", tmp_path / "code")
    monkeypatch.setenv("PATH", str(tmp_path / "pfad"))
    from hilfen.plattform import gleicher_pfad
    pfad = ausfuehrbar(tmp_path / "pfad", "sf")
    assert gleicher_pfad(system.werkzeug_pfad("sf"), pfad)
    sbin = ausfuehrbar(tmp_path / "sbin", "clamd")              # wie /opt/homebrew/sbin: nicht im Suchpfad
    monkeypatch.setattr(system, "ZUSATZ_ORDNER", [str(tmp_path / "sbin")])
    assert gleicher_pfad(system.werkzeug_pfad("clamd"), sbin)
    assert system.werkzeug_pfad("gibtsnicht") is None
    assert system.werkzeug("gibtsnicht") == "gibtsnicht"


def test_werkzeug_auch_in_unterordnern_von_bin(tmp_path, monkeypatch):
    """Im Paket liegen Werkzeuge mit eigenen Bibliotheken in Unterordnern von bin/ (bin/clamav/, bin/poppler/), damit
    sich gleichnamige Bibliotheken nicht stören (Entscheidung 14.11.2026); bin/ selbst geht vor."""
    monkeypatch.delenv("BALDUIN_WERKZEUGE", raising=False)
    monkeypatch.setattr(system, "CODE", tmp_path / "code")
    monkeypatch.setenv("PATH", str(tmp_path / "leer"))
    monkeypatch.setattr(system, "ZUSATZ_ORDNER", [])
    from hilfen.plattform import gleicher_pfad
    oben = ausfuehrbar(tmp_path / "code" / "bin", "sf")
    ausfuehrbar(tmp_path / "code" / "bin" / "aaa", "sf")
    clamd = ausfuehrbar(tmp_path / "code" / "bin" / "clamav", "clamd")
    assert gleicher_pfad(system.werkzeug_pfad("sf"), oben)
    assert gleicher_pfad(system.werkzeug_pfad("clamd"), clamd)
    assert system.werkzeug_pfad("pdftotext") is None


def test_projekte_vorgabe_im_git_und_im_paket(tmp_path, monkeypatch):
    """Im Git liegen neue Projekte neben dem Code; im Paket wäre das im Programm (App-Bundle, C:\\Program Files), also
    dort unter Dokumente/Balduin-Projekte bzw. im persönlichen Ordner (Entscheidung 14.11.2026)."""
    monkeypatch.setattr(system, "CODE", tmp_path / "app" / "balduin")
    monkeypatch.setattr(system.Path, "home", classmethod(lambda cls: tmp_path / "ich"))
    assert system.projekte_vorgabe() == tmp_path / "app" / "Projekte"
    (tmp_path / "app" / "balduin" / "python").mkdir(parents=True)
    assert system.projekte_vorgabe() == tmp_path / "ich" / "Balduin-Projekte"
    (tmp_path / "ich" / "Documents").mkdir(parents=True)
    assert system.projekte_vorgabe() == tmp_path / "ich" / "Documents" / "Balduin-Projekte"


def test_paket_umgebung(tmp_path, monkeypatch):
    """Im Paket: Siegfried findet seine Signaturdatei, ClamAV das Zertifikat für die Signaturen in bin/."""
    monkeypatch.setattr(system, "CODE", tmp_path)
    assert system.paket_umgebung() == {}
    (tmp_path / "bin" / "siegfried").mkdir(parents=True)
    (tmp_path / "bin" / "clamav" / "certs").mkdir(parents=True)
    assert system.paket_umgebung() == {"SIEGFRIED_HOME": str(tmp_path / "bin" / "siegfried"),
                                       "CVD_CERTS_DIR": str(tmp_path / "bin" / "clamav" / "certs")}


def test_clamav_konfiguration_je_system(windows):
    from pathlib import PureWindowsPath as W
    windows.setattr(system, "Path", W)
    konf, vorlage = system.clamav_konfiguration("C:\\Programme\\ClamAV\\freshclam.exe")
    assert konf == W("C:\\Programme\\ClamAV\\freshclam.conf")
    assert vorlage == W("C:\\Programme\\ClamAV\\conf_examples\\freshclam.conf.sample")


def test_clamav_konfiguration_mac(macos):
    konf, vorlage = system.clamav_konfiguration("/opt/homebrew/bin/freshclam")
    assert konf == Path("/opt/homebrew/etc/clamav/freshclam.conf")
    assert vorlage == Path("/opt/homebrew/etc/clamav/freshclam.conf.sample")


# ---------- clamd über einen lokalen Socket (Fehler 4) ----------

@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="kein Unix-Socket auf diesem System")
def test_dienst_adresse_unix_auf_dem_mac(tmp_path, macos):
    a = system.dienst_adresse(tmp_path)
    assert a["familie"] == socket.AF_UNIX and a["konf"].startswith("LocalSocket ")


def test_dienst_adresse_tcp_unter_windows(windows, tmp_path):
    """Fehler 4: clamd kennt unter Windows keinen Unix-Socket, nur TCP; Balduin bindet ihn an 127.0.0.1."""
    a = system.dienst_adresse(tmp_path)
    assert a["familie"] == socket.AF_INET and a["adresse"][0] == "127.0.0.1"
    assert f"TCPSocket {a['adresse'][1]}" in a["konf"] and "TCPAddr 127.0.0.1" in a["konf"]


def test_clamd_ueber_tcp(windows, tmp_path):
    """Der Virenscan spricht mit clamd über TCP, wenn das System keinen Unix-Socket hat (Ersatz-clamd in Python)."""
    from erfassung import virenscan as v
    skript = tmp_path / "clamd.py"
    skript.write_text(textwrap.dedent("""
        import re, socket, sys
        konf = open(sys.argv[2]).read()
        port = int(re.search(r"TCPSocket (\\d+)", konf).group(1))
        s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port)); s.listen(); s.settimeout(60)
        while True:                                 # nach dem ersten Prüfauftrag fertig (unter Windows beendet
            c, _ = s.accept()                       # terminate() nur die .bat, nicht dieses Python)
            daten = c.recv(65536)
            if daten.startswith(b"zPING"):
                c.sendall(b"PONG\\0")
                c.close()
            else:
                pfad = daten[6:].rstrip(b"\\0")
                c.sendall(pfad + b": OK\\0")
                c.close()
                break
    """), encoding="utf-8")
    from hilfen.plattform import ersatzprogramm
    ersatz = ersatzprogramm(tmp_path, "clamd", skript.read_text(encoding="utf-8"))
    windows.setattr(v, "clamav_programm", lambda name: ersatz)
    with open(tmp_path / "clamd.log", "w", encoding="utf-8") as log:
        clamd = v.Clamd(1, log)
        try:
            assert clamd.pruefe(str(tmp_path / "a.txt")) == "OK"
        finally:
            clamd.beenden()


# ---------- Schlüsselbund ----------

def test_geheimnis_unter_windows_in_der_anmeldeinformationsverwaltung(windows):
    speicher = {}
    windows.setattr(system.subprocess, "run", verboten)
    windows.setattr(system, "_win_cred_schreiben", lambda d, k, w: speicher.__setitem__(d, w) or True)
    windows.setattr(system, "_win_cred_lesen", lambda d: speicher.get(d))
    windows.setattr(system, "_win_cred_loeschen", lambda d: speicher.pop(d, None) is not None)
    assert system.geheimnis_lesen("Anton-API x") == "" and not system.geheimnis_vorhanden("Anton-API x")
    assert system.geheimnis_speichern("Anton-API x", "anton", "abc123token") is True
    assert system.geheimnis_lesen("Anton-API x") == "abc123token" and system.geheimnis_vorhanden("Anton-API x")
    assert system.geheimnis_entfernen("Anton-API x") is True
    assert system.geheimnis_lesen("Anton-API x") == ""


def test_geheimnis_auf_dem_mac_ueber_security_mit_eigenem_schluesselbund(monkeypatch, macos):
    """Tests nutzen den Schlüsselbund aus ANTON_SCHLUESSELBUND, nie den echten; der Wert geht über stdin."""
    aufrufe = []

    def run(befehl, **k):
        aufrufe.append((befehl, k.get("input")))
        return subprocess.CompletedProcess(befehl, 0, "geheim\n", "")
    monkeypatch.setattr(system.subprocess, "run", run)
    monkeypatch.setenv("ANTON_SCHLUESSELBUND", "/tmp/test.keychain")
    assert system.geheimnis_lesen("Anton-API x") == "geheim"
    assert aufrufe[-1][0] == ["security", "find-generic-password", "-s", "Anton-API x", "-w", "/tmp/test.keychain"]
    system.geheimnis_speichern("Anton-API x", "anton", "abc123token")
    befehl, eingabe = aufrufe[-1]
    assert befehl == ["security", "-i"] and "abc123token" not in " ".join(befehl)
    assert "-w \"abc123token\"" in eingabe and "/tmp/test.keychain" in eingabe


# ---------- Dialog, Dateimanager, Papierkorb ----------

def test_ordnerdialog_unter_windows_ueber_powershell(windows, tmp_path):
    gesehen = {}

    def run(befehl, **k):
        gesehen.update(befehl=befehl, env=k.get("env"))
        return subprocess.CompletedProcess(befehl, 0, "D:\\Bestand\\Übergabe\r\n", "")
    windows.setattr(system.subprocess, "run", run)
    assert system.ordner_waehlen("Ordner wählen", tmp_path) == "D:\\Bestand\\Übergabe"
    assert gesehen["befehl"][0] == "powershell" and "-STA" in gesehen["befehl"]
    assert gesehen["env"]["BALDUIN_TITEL"] == "Ordner wählen"          # Text nicht im Befehl (keine Anführungszeichen)
    windows.setattr(system.subprocess, "run", lambda b, **k: subprocess.CompletedProcess(b, 2, "", ""))
    assert system.ordner_waehlen("x", tmp_path) is None                  # abgebrochen


def test_ordnerdialog_mac_abbrechen(monkeypatch, tmp_path, macos):
    monkeypatch.setattr(system.subprocess, "run",
                        lambda b, **k: subprocess.CompletedProcess(b, 1, "", "User canceled. (-128)"))
    assert system.ordner_waehlen("x", tmp_path) is None
    monkeypatch.setattr(system.subprocess, "run",
                        lambda b, **k: subprocess.CompletedProcess(b, 0, "/Users/x/Projekte/A/\n", ""))
    assert system.ordner_waehlen("x", tmp_path) == "/Users/x/Projekte/A"


def test_dateimanager_unter_windows_explorer_select(windows, tmp_path):
    gesehen = []
    windows.setattr(system.subprocess, "run", lambda b, **k: gesehen.append(b) or subprocess.CompletedProcess(b, 1))
    windows.setattr(system, "_absolut", lambda p: str(p))
    system.im_dateimanager_zeigen("E:\\Fotos\\a b.jpg")                   # Explorer meldet auch bei Erfolg 1
    assert gesehen == ['explorer /select,"E:\\Fotos\\a b.jpg"']


def test_papierkorb_unter_windows_ueber_die_shell(windows, tmp_path):
    ordner = tmp_path / "Projekt"
    ordner.mkdir()
    gesehen = []
    windows.setattr(system, "_win_papierkorb", lambda p: gesehen.append(p) or 0)
    system.in_papierkorb(ordner)
    assert gesehen == [str(ordner.resolve())]
    windows.setattr(system, "_win_papierkorb", lambda p: 5)
    with pytest.raises(RuntimeError, match="Papierkorb"):
        system.in_papierkorb(ordner)


# ---------- Ordner der App, Vorschau, Verknüpfung, Port ----------

def test_app_daten_je_system(windows, tmp_path):
    windows.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert system.app_daten() == tmp_path / "Roaming" / "Balduin"


def test_app_daten_mac(macos):
    assert system.app_daten() == Path.home() / "Library" / "Application Support" / "Balduin"


def test_zuletzt_zieht_einmal_aus_dem_alten_ordner_um(monkeypatch, tmp_path, macos):
    """Bisher hieß der Ordner „GF-Bewertung“; die Liste der Projekte wird beim ersten Mal kopiert (das Alte bleibt).
    HOME zeigt auf einen leeren Temp-Ordner: der Test berührt nie die echte zuletzt.json."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))                     # Path.home() unter Windows
    assert Path.home() == tmp_path
    alt = tmp_path / "Library" / "Application Support" / "GF-Bewertung" / "zuletzt.json"
    neu = tmp_path / "Library" / "Application Support" / "Balduin" / "zuletzt.json"
    alt.parent.mkdir(parents=True)
    alt.write_text(json.dumps({"projekt": "/x/A", "liste": []}), encoding="utf-8")
    assert system.zuletzt_datei() == neu
    assert json.loads(neu.read_text(encoding="utf-8"))["projekt"] == "/x/A" and alt.exists()
    alt.write_text(json.dumps({"projekt": "/x/B"}), encoding="utf-8")
    system.zuletzt_datei()                                               # nur einmal: Neues wird nicht überschrieben
    assert json.loads(neu.read_text(encoding="utf-8"))["projekt"] == "/x/A"


def test_schnellvorschau_gibt_es_nur_auf_dem_mac(windows, tmp_path):
    windows.setattr(system.subprocess, "run", verboten)
    assert system.schnellvorschau(tmp_path / "a.docx", 400, tmp_path) is None


def test_verknuepfen_unter_windows_kopiert_wenn_verweise_fehlen(windows, tmp_path):
    """Verknüpfungen brauchen unter Windows Administratorrechte; dann eine Kopie (Siegfried liest nur)."""
    def ohne_rechte(self, ziel, target_is_directory=False):
        raise OSError("Symbolische Verknüpfung: Rechte fehlen")
    windows.setattr(Path, "symlink_to", ohne_rechte)
    (tmp_path / "pronom").mkdir()
    (tmp_path / "pronom" / "x.xml").write_text("x", encoding="utf-8")
    (tmp_path / "a.xml").write_text("a", encoding="utf-8")
    ziel = tmp_path / "home"
    ziel.mkdir()
    system.verknuepfen(tmp_path / "pronom", ziel / "pronom")
    system.verknuepfen(tmp_path / "a.xml", ziel / "a.xml")
    assert (ziel / "pronom" / "x.xml").read_text(encoding="utf-8") == "x" and (ziel / "a.xml").read_text(encoding="utf-8") == "a"


def test_port_belegt_erkennt_alle_systeme():
    assert system.port_belegt(OSError(48, "Address already in use")) == (48 == __import__("errno").EADDRINUSE)
    fehler = OSError(10048, "WSAEADDRINUSE")
    fehler.winerror = 10048
    assert system.port_belegt(fehler)
    fehler = OSError(10013, "WSAEACCES")                                 # exklusiv belegt (SO_EXCLUSIVEADDRUSE)
    fehler.winerror = 10013
    assert system.port_belegt(fehler)
    assert not system.port_belegt(OSError(2, "No such file"))


def test_server_belegt_den_port_nicht_doppelt():
    """Ein zweiter Server auf demselben Port scheitert (unter Windows sorgt SO_EXCLUSIVEADDRUSE dafür)."""
    import server
    erster = server.BalduinServer(("127.0.0.1", 0), server.Anfrage)
    try:
        with pytest.raises(OSError) as fehler:
            server.BalduinServer(("127.0.0.1", erster.server_address[1]), server.Anfrage)
        assert system.port_belegt(fehler.value)
    finally:
        erster.server_close()


def test_maske_fuer_mountpfade():
    import re
    muster = re.compile(system.MOUNTPFAD_MUSTER)
    assert muster.sub("(Datei)", "Fehler bei '/Volumes/HD01/Fotos/a b.jpg'") == "Fehler bei (Datei)"
    assert muster.sub("(Datei)", "Fehler bei 'E:\\Fotos\\a b.jpg'") == "Fehler bei (Datei)"


# ---------- Keine Systemaufrufe mehr außerhalb von system.py ----------

# Programme des Systems: verboten, wo sie aufgerufen werden (in einer Befehlsliste "…"); dazu Ausdrücke, die überall
# auf ein bestimmtes System festlegen
SYSTEMPROGRAMME = ("diskutil", "qlmanage", "textutil", "osascript", "security", "open", "mount", "defaults", "explorer",
                   "powershell", "lsblk", "udisksctl", "secret-tool", "zenity", "kdialog", "gdbus", "gio", "xdg-open",
                   "pkexec", "kioclient5", "kioclient")
IMMER_VERBOTEN = ("os.statvfs", "start_new_session", "os.kill(", "/opt/homebrew", "/usr/local/sbin", '"Library"',
                  'Path("/Volumes")', "AF_UNIX", "symlink_to(", "windll")


def test_systemaufrufe_nur_in_system_py():
    """Entscheidung 30.10.2026: Plattformabhängiges nur in erfassung/system.py (Kommentare zählen nicht)."""
    code = Path(system.__file__).resolve().parent.parent
    funde = []
    for datei in [*code.glob("erfassung/*.py"), *code.glob("tool/*.py"), *code.glob("vorlauf/*.py"),
                  *code.glob("export/*.py"), *code.glob("werkzeuge/*.py")]:
        if datei.name in ("system.py", "tueroeffner.py", "tueroeffner_linux.py"):   # Türöffner: eigene Skripte ohne erfassung
            continue
        if datei.name == "mac_testabbilder_erzeugen.py":   # erzeugt Testdaten, läuft nur auf dem Mac, nicht Teil von Balduin
            continue
        for nr, zeile in enumerate(datei.read_text(encoding="utf-8").splitlines(), 1):
            z = zeile.split("  #")[0]
            if z.lstrip().startswith("#"):
                continue
            treffer = [b for b in IMMER_VERBOTEN if b in z] + [b for b in SYSTEMPROGRAMME if f'["{b}"' in z]
            if treffer:
                funde.append(f"{datei.relative_to(code)}:{nr}: {zeile.strip()[:120]}")
    assert not funde, "Systemaufrufe außerhalb von system.py:\n" + "\n".join(funde)


def test_dateidialog_mac(monkeypatch, tmp_path, macos):
    gesehen = []
    monkeypatch.setattr(system.subprocess, "run", lambda b, **k: gesehen.append(b)
                        or subprocess.CompletedProcess(b, 0, "/Users/x/Abbilder/HD07.dmg\n", ""))
    assert system.datei_waehlen("Abbild wählen", tmp_path) == "/Users/x/Abbilder/HD07.dmg"
    assert gesehen[0][0] == "osascript" and "choose file" in " ".join(gesehen[0])
    monkeypatch.setattr(system.subprocess, "run",
                        lambda b, **k: subprocess.CompletedProcess(b, 1, "", "User canceled. (-128)"))
    assert system.datei_waehlen("x", tmp_path) is None


def test_dateidialog_windows(windows, tmp_path):
    gesehen = {}

    def run(befehl, **k):
        gesehen.update(befehl=befehl, env=k.get("env"))
        return subprocess.CompletedProcess(befehl, 0, "D:\\Abbilder\\HD07.img\r\n", "")
    windows.setattr(system.subprocess, "run", run)
    assert system.datei_waehlen("Abbild wählen", tmp_path) == "D:\\Abbilder\\HD07.img"
    assert gesehen["befehl"][0] == "powershell" and "OpenFileDialog" in gesehen["befehl"][-1]
    assert gesehen["env"]["BALDUIN_TITEL"] == "Abbild wählen"


# ---------- Physische Mac-Platten unter Windows (Entscheidung 09.11.2026) ----------

def test_geraet_nur_unter_windows(windows):
    assert system.ist_geraet("\\\\.\\PhysicalDrive2")
    assert system.ist_geraet("\\\\.\\physicaldrive10")
    assert not system.ist_geraet("E:\\")


def test_geraet_auf_dem_mac_nie(macos):
    assert not system.ist_geraet("\\\\.\\PhysicalDrive2")
    assert system.physische_datentraeger() == []


def test_physische_datentraeger_ohne_laufwerksbuchstaben(windows):
    """Ohne Administratorrechte: Modell, Seriennummer, Größe; Systemplatte fällt weg, Platten ohne Buchstaben markiert."""
    angaben = {0: {"modell": "Samsung SSD", "seriennummer": "S0", "anschluss": "NVMe", "wechselmedium": False, "groesse": 512e9},
               2: {"modell": "Muster Rugged", "seriennummer": "NA8X", "anschluss": "USB", "wechselmedium": False, "groesse": 2e12},
               3: {"modell": "SanDisk", "seriennummer": "4C53", "anschluss": "USB", "wechselmedium": True, "groesse": 64e9}}

    def geraet(pfad):
        nr = int(pfad.lower().rsplit("physicaldrive", 1)[1])
        if nr not in angaben:
            raise OSError("kein Gerät")
        return angaben[nr]
    windows.setattr(system, "_win_geraet_angaben", geraet)
    windows.setattr(system, "_win_laufwerke", lambda: ["C:\\", "F:\\"])
    windows.setattr(system, "_systemlaufwerk", lambda: "C:")
    windows.setattr(system, "_win_geraetenummer", lambda pfad: {"\\\\.\\C:": 0, "\\\\.\\F:": 3}[pfad])
    liste = {d["nummer"]: d for d in system.physische_datentraeger()}
    assert set(liste) == {2, 3}                                         # 0 ist die Systemplatte
    assert liste[2]["geraet"] == "\\\\.\\PhysicalDrive2" and liste[2]["laufwerksbuchstaben"] is False
    assert liste[3]["laufwerksbuchstaben"] is True and liste[2]["seriennummer"] == "NA8X"


def test_cd_laufwerk_belegt_keine_platte_mit_gleicher_nummer(windows):
    """Windows nummeriert CD-Laufwerke (CdRomN) und Platten (PhysicalDriveN) getrennt. Ein CD-Laufwerk E: mit Nummer 1
    darf PhysicalDrive1 nicht als „hat Laufwerksbuchstaben“ markieren (gefunden in der Windows-VM am 13.11.2026: die
    Mac-Platte bekam so keinen Knopf „Mac-Datenträger lesen …“)."""
    nummern = {"\\\\.\\C:": (7, 0), "\\\\.\\E:": (2, 1)}               # (Gerätetyp, Nummer); 7 Platte, 2 CD-ROM

    def ioctl(griff, code, eingabe=b"", laenge=1024):
        assert code == system.IOCTL_STORAGE_GET_DEVICE_NUMBER
        typ, nr = nummern[griff]
        return typ.to_bytes(4, "little") + nr.to_bytes(4, "little") + (0).to_bytes(4, "little")
    windows.setattr(system, "_win_geraet_griff", lambda pfad, zugriff=0: pfad)
    windows.setattr(system, "_win_ioctl", ioctl)
    windows.setattr(system, "_win_schliessen", lambda griff: None)
    windows.setattr(system, "_win_laufwerke", lambda: ["C:\\", "E:\\"])
    windows.setattr(system, "_systemlaufwerk", lambda: "C:")
    windows.setattr(system, "_win_geraet_angaben", lambda g: {"modell": "QEMU HARDDISK", "seriennummer": "",
                                                               "anschluss": "USB", "wechselmedium": False,
                                                               "groesse": 3e8} if g.endswith("1") else
                    (_ for _ in ()).throw(OSError("kein Gerät")))
    liste = {d["nummer"]: d for d in system.physische_datentraeger()}
    assert liste[1]["laufwerksbuchstaben"] is False


def test_geraet_oeffnen_mit_administratorrechten_direkt(windows):
    windows.setattr(system, "ist_admin", lambda: True)
    windows.setattr(system, "_win_geraet_griff", lambda g: 77)
    windows.setattr(system, "_win_tueroeffner", lambda g: (_ for _ in ()).throw(AssertionError("kein Türöffner nötig")))
    windows.setattr(system, "_griff_als_datei", lambda griff: f"datei:{griff}")
    windows.setattr(system, "_win_geraet_angaben", lambda g: {"groesse": 2_000_000})
    assert system.geraet_oeffnen("\\\\.\\PhysicalDrive2") == ("datei:77", 2_000_000, 4096)


def test_geraet_oeffnen_ohne_administratorrechte_ueber_den_tueroeffner(windows):
    windows.setattr(system, "ist_admin", lambda: False)
    windows.setattr(system, "_win_geraet_griff", verboten)
    windows.setattr(system, "_win_tueroeffner", lambda g: 88)
    windows.setattr(system, "_griff_als_datei", lambda griff: f"datei:{griff}")
    windows.setattr(system, "_win_geraet_angaben", lambda g: {"groesse": 5})
    assert system.geraet_oeffnen("\\\\.\\PhysicalDrive2")[0] == "datei:88"


def test_geraet_oeffnen_nimmt_nur_physische_platten(windows):
    for falsch in ("C:\\Windows\\x", "\\\\.\\C:", "\\\\.\\PhysicalDrive2\\..\\x", "\\\\server\\freigabe"):
        with pytest.raises(ValueError):
            system.geraet_oeffnen(falsch)


def test_tueroeffner_prueft_den_auftrag(monkeypatch):
    """Der Hilfsprozess läuft mit Administratorrechten: er nimmt nur \\\\.\\PhysicalDriveN und eine lokale Adresse."""
    from erfassung import tueroeffner
    for argumente in (["C:\\x", "1", "127.0.0.1:5000", "ab" * 16], ["\\\\.\\PhysicalDrive1", "x", "127.0.0.1:5000", "ab" * 16],
                      ["\\\\.\\PhysicalDrive1", "1", "10.0.0.1:5000", "ab" * 16]):
        with pytest.raises(ValueError):
            tueroeffner.auftrag_pruefen(argumente)
    assert tueroeffner.auftrag_pruefen(["\\\\.\\PhysicalDrive3", "4711", "127.0.0.1:5000", "ab" * 16]) == (
        "\\\\.\\PhysicalDrive3", 4711, ("127.0.0.1", 5000), bytes.fromhex("ab" * 16))


def test_tueroeffner_reicht_den_griff_weiter(monkeypatch):
    """Ablauf ohne Windows nachgestellt: Griff öffnen (nur lesend), in den Lauf verdoppeln, über die Verbindung melden."""
    from multiprocessing.connection import Listener
    import threading
    from erfassung import tueroeffner
    geoeffnet = []
    monkeypatch.setattr(tueroeffner, "nur_lesend_oeffnen", lambda g: geoeffnet.append(g) or 5)
    monkeypatch.setattr(tueroeffner, "verdoppeln", lambda griff, pid: griff * 100 + pid)
    monkeypatch.setattr(tueroeffner, "schliessen", lambda griff: None)
    schluessel = b"0123456789abcdef"
    with Listener(("127.0.0.1", 0), authkey=schluessel) as hoerer:
        port = hoerer.address[1]
        t = threading.Thread(target=tueroeffner.main, args=(["\\\\.\\PhysicalDrive3", "7", f"127.0.0.1:{port}",
                                                             schluessel.hex()],))
        t.start()
        with hoerer.accept() as verbindung:
            antwort = verbindung.recv()
        t.join(5)
    assert geoeffnet == ["\\\\.\\PhysicalDrive3"] and antwort == {"griff": 507}


def test_tueroeffner_erreicht_den_lauf_eines_anderen_kontos(monkeypatch):
    """Gefunden in der Windows-VM am 13.11.2026: Arbeitet jemand ohne Administratorrechte und bestätigt die Rückfrage
    mit einem anderen Konto, darf der Türöffner den Lauf nicht öffnen (Fehler 5: der Lauf gehört nicht ihm). Dann
    schaltet er das Recht SeDebugPrivilege ein, das jedes erhöhte Administratorkonto hat, und versucht es noch einmal."""
    from erfassung import tueroeffner
    versuche, recht = [], []
    monkeypatch.setattr(tueroeffner, "_prozess_oeffnen", lambda pid: versuche.append(pid) or ((1234, 0) if recht else (0, 5)))
    monkeypatch.setattr(tueroeffner, "debugrecht_einschalten", lambda: recht.append(True))
    assert tueroeffner.prozess_oeffnen(4711) == 1234
    assert versuche == [4711, 4711] and recht == [True]


def test_tueroeffner_meldet_andere_fehler_ohne_weiteres_recht(monkeypatch):
    from erfassung import tueroeffner
    recht = []
    monkeypatch.setattr(tueroeffner, "_prozess_oeffnen", lambda pid: (0, 87))
    monkeypatch.setattr(tueroeffner, "debugrecht_einschalten", lambda: recht.append(True))
    with pytest.raises(OSError, match="Fehler 87"):
        tueroeffner.prozess_oeffnen(4711)
    assert recht == []


def test_geraet_name_fest_auch_durch_pathlib(windows):
    """pathlib unter Windows macht aus \\\\.\\PhysicalDrive2 den Pfad \\\\.\\PhysicalDrive2\\ (Gerätepfad mit Trenner)."""
    from pathlib import PureWindowsPath
    assert system.geraet_name(str(PureWindowsPath("\\\\.\\PhysicalDrive2"))) == "\\\\.\\PhysicalDrive2"
    assert system.geraet_name("//./physicaldrive2/") == "\\\\.\\PhysicalDrive2"
    assert system.ist_geraet(PureWindowsPath("\\\\.\\PhysicalDrive2"))
    assert system.geraet_name("E:\\") is None


def test_textdateien_immer_mit_kodierung():
    """Unter Windows liest und schreibt Python Text ohne Angabe als cp1252 (Fehler „'charmap' codec can't decode“,
    gefunden am 12.11.2026 beim Start in der VM). Jeder Textzugriff (read_text, write_text, open im Textmodus) nennt
    deshalb encoding; geprüft über die Syntax, auch über mehrere Zeilen."""
    import ast
    code = Path(system.__file__).resolve().parent.parent
    funde = []
    for datei in [*code.glob("erfassung/*.py"), *code.glob("tool/*.py"), *code.glob("vorlauf/*.py"),
                  *code.glob("export/*.py"), *code.glob("werkzeuge/*.py"), *code.glob("tests/*.py"),
                  *code.glob("tests/hilfen/*.py"), *code.glob("tests/schutz/*.py")]:
        for n in ast.walk(ast.parse(datei.read_text(encoding="utf-8"))):
            if not isinstance(n, ast.Call) or any(k.arg == "encoding" for k in n.keywords):
                continue
            f = n.func
            text = isinstance(f, ast.Attribute) and f.attr in ("read_text", "write_text")
            datei_text = (isinstance(f, ast.Name) and f.id == "open" and len(n.args) >= 2
                          and isinstance(n.args[1], ast.Constant) and "b" not in str(n.args[1].value))
            if text or datei_text:
                funde.append(f"{datei.relative_to(code)}:{n.lineno}")
    assert not funde, "Textzugriff ohne encoding: " + ", ".join(funde)


def test_relpfad_immer_mit_schraegstrich():
    """Schlüssel einer Datei ist Platte + Pfad: unter Windows gab os.path.relpath „A\\1.txt“ (gefunden am 12.11.2026
    in der VM). relpfad_von gibt auf jedem System „A/1.txt“ in NFC."""
    import ntpath
    import posixpath
    from erfassung.basis import relpfad_von
    assert relpfad_von("C:\\Quelle\\A\\Zu\u0308rich\\1.txt", "C:\\Quelle", ntpath) == "A/Zürich/1.txt"
    assert relpfad_von("/Volumes/HD01/A/1.txt", "/Volumes/HD01", posixpath) == "A/1.txt"
    assert relpfad_von("C:\\Quelle", "C:\\Quelle", ntpath) == "."


def test_relpath_nur_ueber_relpfad_von():
    import ast
    code = Path(system.__file__).resolve().parent.parent
    funde = []
    for datei in [*code.glob("erfassung/*.py"), *code.glob("tool/*.py"), *code.glob("vorlauf/*.py"), *code.glob("export/*.py")]:
        for n in ast.walk(ast.parse(datei.read_text(encoding="utf-8"))):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "relpath"
                    and not (datei.name == "basis.py")):
                funde.append(f"{datei.relative_to(code)}:{n.lineno}")
    assert not funde, "os.path.relpath statt relpfad_von: " + ", ".join(funde)


def test_datentraeger_info_unter_windows_nur_fuer_die_wurzel_eines_laufwerks(windows):
    """Wie diskutil auf dem Mac: Angaben nur für die Wurzel eines Laufwerks, nicht für einen Ordner darauf. Sonst
    trugen unter Windows alle Ordner auf C: dieselbe „Volume-UUID“ (Testplatten in der VM, 12.11.2026)."""
    windows.setattr(system, "_win_volume", lambda w: ("DATEN", 0x1234ABCD, 0, "NTFS"))
    windows.setattr(system, "_win_laufwerkstyp", lambda w: system.DRIVE_FIXED)
    windows.setattr(system.shutil, "disk_usage", lambda w: (1000, 400, 600))
    windows.setattr(system, "_wurzel", lambda pfad: str(pfad)[:2] + "\\")
    assert system.datentraeger_info("E:\\")["VolumeUUID"] == "1234-ABCD"
    assert system.datentraeger_info("E:")["VolumeUUID"] == "1234-ABCD"
    assert system.datentraeger_info("C:\\Users\\balduin\\Temp\\volumes\\HD01") == {}
    assert system.datentraeger_info("E:\\Fotos") == {}


def test_pfad_schluessel_gleicht_trenner_und_schreibweise_an():
    """ExifTool meldet SourceFile unter Windows mit „/“ (C:/Users/…); Balduin übergibt „\\“. Ohne Angleichen fand E1
    keine Antwort, und jede Datei galt als „von ExifTool nicht gelesen“ (Windows-VM, 12.11.2026)."""
    import ntpath
    import posixpath
    from erfassung.basis import pfad_schluessel
    assert pfad_schluessel("C:/Users/balduin/Müller Übergabe.jpg", ntpath) == \
        pfad_schluessel("C:\\Users\\balduin\\Müller Übergabe.jpg", ntpath)
    assert pfad_schluessel("c:\\users\\X.JPG", ntpath) == pfad_schluessel("C:\\Users\\x.jpg", ntpath)
    assert pfad_schluessel("/Volumes/HD01/A.jpg", posixpath) != pfad_schluessel("/Volumes/HD01/a.jpg", posixpath)


def test_metadaten_ordnet_antworten_mit_schraegstrich_zu():
    """E1 findet die Antwort von ExifTool auch, wenn SourceFile anders geschrieben ist als der übergebene Pfad."""
    import ntpath
    from erfassung import metadaten
    pfade = {"C:\\Quelle\\Müller\\a.jpg": "Müller/a.jpg", "C:\\Quelle\\b.jpg": "b.jpg"}
    antworten = [{"SourceFile": "C:/Quelle/Müller/a.jpg", "EXIF:Make": "Testkamera"}, {"SourceFile": "C:/anderswo/x.jpg"}]
    assert metadaten.antworten_zuordnen(pfade, antworten, ntpath) == {"Müller/a.jpg": antworten[0]}


def test_code_ohne_syntaxwarnungen():
    """Ungültige Escape-Sequenzen (z. B. „\\P“ in einem Docstring) meldet Python nur beim ersten Übersetzen; auf dem
    Mac fiel es wegen der .pyc-Dateien nicht auf, in der Windows-VM schon (12.11.2026)."""
    import warnings
    code = Path(system.__file__).resolve().parent.parent
    funde = []
    for datei in [*code.glob("erfassung/*.py"), *code.glob("tool/*.py"), *code.glob("vorlauf/*.py"),
                  *code.glob("export/*.py"), *code.glob("werkzeuge/*.py"), *code.glob("tests/**/*.py")]:
        with warnings.catch_warnings():
            warnings.simplefilter("error", SyntaxWarning)
            try:
                compile(datei.read_text(encoding="utf-8"), str(datei), "exec")
            except SyntaxWarning as w:
                funde.append(f"{datei.relative_to(code)}: {w}")
    assert not funde, "\n".join(funde)


# ---------- Wörter je System (Wording, Entscheidung 13.11.2026) ----------

def test_systemwoerter_mac(macos):
    w = system.systemwoerter()
    assert w["dateimanager"] == "Finder" and w["schluesselspeicher"] == "Schlüsselbund"
    assert w["im_schluesselspeicher"] == "im Schlüsselbund" and w["aus_dem_schluesselspeicher"] == "aus dem Schlüsselbund"
    assert w["system"] == "macOS"


def test_systemwoerter_windows(windows):
    w = system.systemwoerter()
    assert w["dateimanager"] == "Explorer" and w["schluesselspeicher"] == "Anmeldeinformationsverwaltung"
    assert w["im_schluesselspeicher"] == "in der Anmeldeinformationsverwaltung"
    assert w["system"] == "Windows"


def test_systemwoerter_sonst(monkeypatch):
    monkeypatch.setattr(system, "windows", lambda: False)
    monkeypatch.setattr(system, "mac", lambda: False)
    monkeypatch.setattr(system, "linux", lambda: False)
    w = system.systemwoerter()
    assert w["dateimanager"] == "Dateimanager"
    assert w["schluesselspeicher"] == "Schlüssel- und Zertifikatsverwaltung des Systems"


def test_installationshinweis_je_system(macos):
    assert "brew install exiftool" in system.installationshinweis("exiftool")
    assert "brew install clamav" in system.installationshinweis("clamav")
    assert "richardlehane/digipres/siegfried" in system.installationshinweis("sf")


def test_installationshinweis_windows_ohne_brew(windows):
    hinweis = system.installationshinweis("exiftool")
    assert "brew" not in hinweis and "Balduin" in hinweis


def test_ablage_im_projektordner_nennt_den_mac_nur_auf_dem_mac(windows):
    """Gefunden in der Windows-VM am 13.11.2026: die Ablage hieß dort „Projektordner auf dem Mac“."""
    from tool import pakete
    assert pakete.ablage_projekt_name() == "Projektordner auf diesem Rechner"
    windows.setattr(system, "mac", lambda: True)
    windows.setattr(system, "windows", lambda: False)
    assert pakete.ablage_projekt_name() == "Projektordner auf dem Mac"


# ---- Kennung von FAT/exFAT wie auf dem Mac (UTM-Test 13.11.2026) ----
# macOS bildet die VolumeUUID eines FAT-/exFAT-Volumes wie bei HFS+: MD5 aus dem HFS-Namensraum und der 4-Byte-
# Seriennummer des Volumes (little endian). Wert gemessen an einem exFAT-Abbild: diskutil info → Volume UUID.
EXFAT_SERIE, EXFAT_MAC_UUID = 0x6AF7488F, "95FFE3E2-90D6-3F22-BEC7-9FF7216DB2EC"


def test_fat_uuid_wie_macos():
    from erfassung import macplatte
    assert macplatte.fat_uuid(EXFAT_SERIE) == EXFAT_MAC_UUID
    assert macplatte.fat_uuid(0) == ""


def test_exfat_unter_windows_mit_derselben_kennung_wie_auf_dem_mac(windows):
    windows.setattr(system, "_wurzel", lambda pfad: "E:\\")
    windows.setattr(system, "_win_volume", lambda w: ("STICK", EXFAT_SERIE, 0, "exFAT"))
    windows.setattr(system, "_win_laufwerkstyp", lambda w: system.DRIVE_REMOVABLE)
    windows.setattr(system.shutil, "disk_usage", lambda w: (1000, 400, 600))
    info = system.datentraeger_info("E:\\")
    assert info["VolumeUUID"] == EXFAT_MAC_UUID and info["VolumeUUIDAlt"] == "6AF7-488F"
    assert system.kennungen(info) == [EXFAT_MAC_UUID, "6AF7-488F"]
    windows.setattr(system, "_win_volume", lambda w: ("DATEN", EXFAT_SERIE, 0, "NTFS"))   # NTFS bleibt, wie es war
    assert system.datentraeger_info("E:\\")["VolumeUUID"] == "6AF7-488F"
    assert system.kennungen(system.datentraeger_info("E:\\")) == ["6AF7-488F"]


def test_registriert_mit_der_alten_windows_kennung_wird_wiedererkannt():
    """Ein Stick, der vor dem 13.11.2026 unter Windows registriert wurde, trägt in der Datenbank „6AF7-488F“."""
    import pandas as pd
    from erfassung import platte
    registriert = pd.DataFrame([{"platte_id": "HD09", "volume_uuid": "6AF7-488F", "volume_name": "STICK",
                                 "dateisystem": "exFAT", "kapazitaet_bytes": 1000}])
    info = {"volume_uuid": EXFAT_MAC_UUID, "volume_kennungen": [EXFAT_MAC_UUID, "6AF7-488F"],
            "volume_name": "STICK", "dateisystem": "exFAT", "kapazitaet_bytes": 1000}
    assert platte.registriert_als(info, registriert) == ["HD09"]


# ---- Mac-Platten an der Kennung der Partitionstabelle wiedererkennen (UTM-Test 13.11.2026, Punkt 5.7) ----
# Gehäuse ohne Seriennummer: Windows bzw. QEMU melden dann den Anschlussort; nach dem Umstecken hielt Balduin eine
# andere Platte für die registrierte. Die GPT-Kennung (bzw. MBR-Signatur) liegt auf der Platte und ist ohne
# Administratorrechte lesbar (IOCTL_DISK_GET_DRIVE_LAYOUT_EX mit Zugriff 0).

def test_tabellenkennung_aus_dem_layout():
    import uuid
    gpt = (1).to_bytes(4, "little") + bytes(4) + uuid.UUID("b80225af-d204-43ea-9214-c1e4ee8d95bd").bytes_le
    assert system.tabelle_kennung(gpt) == "GPT:B80225AF-D204-43EA-9214-C1E4EE8D95BD"
    assert system.tabelle_kennung((0).to_bytes(4, "little") + bytes(4) + (0x1234ABCD).to_bytes(4, "little")) == "MBR:1234ABCD"
    assert system.tabelle_kennung((0).to_bytes(4, "little") + bytes(8)) == ""          # MBR ohne Signatur
    assert system.tabelle_kennung((2).to_bytes(4, "little") + bytes(20)) == ""         # RAW


def test_mac_platten_nach_dem_umstecken_an_der_tabelle_erkannt(monkeypatch, leeres_projekt):
    """Nachgestellt wie in der VM: MT03 hing an Anschluss …4.3; nach dem Umstecken hängt dort MT04 und MT03 an …4.5."""
    from erfassung import platte
    from erfassung.basis import db
    with db() as con:
        con.execute("INSERT INTO platte (platte_id, volume_name, art, geraet) VALUES "
                    "('MT03', 'MAC_APFS', 'macplatte', 'GPT:B80225AF-D204-43EA-9214-C1E4EE8D95BD'), "
                    "('MT04', 'MAC_HFS', 'macplatte', '1-0000:00:04.0-4.4')")       # alt: nur die Seriennummer
    monkeypatch.setattr(platte.system, "physische_datentraeger", lambda: [
        {"geraet": "\\\\.\\PhysicalDrive1", "seriennummer": "1-0000:00:04.0-4.3",
         "tabelle": "GPT:078BAE5E-E202-4979-8359-20E8220EC9AB", "laufwerksbuchstaben": False},
        {"geraet": "\\\\.\\PhysicalDrive2", "seriennummer": "1-0000:00:04.0-4.5",
         "tabelle": "GPT:B80225AF-D204-43EA-9214-C1E4EE8D95BD", "laufwerksbuchstaben": False}])
    liste = {m["platte_id"]: m for m in platte.macplatten_liste()}
    assert liste["MT03"]["da"] and liste["MT03"]["pfad"] == "\\\\.\\PhysicalDrive2"
    assert not liste["MT04"]["da"]                   # alte Seriennummer passt zu keinem Gerät mehr: lieber nicht da
    assert platte.geraet_kennung({"tabelle": "GPT:X", "seriennummer": "S"}) == "GPT:X"
    assert platte.geraet_kennung({"tabelle": "", "seriennummer": "S"}) == "S"


def test_mac_platte_beim_lesen_wiedererkannt_und_kennung_nachgetragen(monkeypatch, leeres_projekt):
    """Nach „Mac-Datenträger lesen …“ kennt Balduin die Volume-UUID; gehört sie zu einer registrierten Mac-Platte, ist
    es diese (nicht neu registrieren), und die Kennung des Geräts wird nachgetragen (protokolliert)."""
    from erfassung import platte
    from erfassung.basis import db
    with db() as con:
        con.execute("INSERT INTO platte (platte_id, volume_name, volume_uuid, art, geraet) VALUES "
                    "('MT03', 'MAC_APFS', 'FDD9EDCB-82D7-485A-8B7C-71563DF68531', 'macplatte', '1-0000:00:04.0-4.3')")
    geraet = {"geraet": "\\\\.\\PhysicalDrive2", "seriennummer": "1-0000:00:04.0-4.5", "modell": "QEMU",
              "tabelle": "GPT:B80225AF-D204-43EA-9214-C1E4EE8D95BD", "anschluss": "USB", "groesse": 3,
              "laufwerksbuchstaben": False}
    monkeypatch.setattr(platte.system, "physische_datentraeger", lambda: [geraet])
    monkeypatch.setattr(platte.system, "ist_geraet", lambda g: True)
    monkeypatch.setattr(platte.macplatte, "volumes", lambda g: [
        {"name": "MAC_APFS", "dateisystem": "APFS", "uuid": "FDD9EDCB-82D7-485A-8B7C-71563DF68531", "gesperrt": False,
         "groesse": 3}])
    a = platte.macgeraet_pruefen("\\\\.\\PhysicalDrive2")
    assert a["erkannt"] == "MT03"
    with db() as con:
        assert con.execute("SELECT geraet FROM platte WHERE platte_id = 'MT03'").fetchone()[0] == geraet["tabelle"]
        assert con.execute("SELECT COUNT(*) FROM protokoll WHERE objekt = 'MT03' AND feld = 'geraet'").fetchone()[0] == 1
    assert [m["pfad"] for m in platte.macplatten_liste() if m["da"]] == ["\\\\.\\PhysicalDrive2"]


def test_anschluss_unter_windows_von_der_platte_hinter_dem_laufwerk(windows):
    """UTM-Test 13.11.2026: eine USB-Platte (Laufwerkstyp „fest“) hatte keinen Anschluss; jetzt fragt Balduin die
    physische Platte hinter dem Laufwerksbuchstaben (Bus, Modell, Wechselmedium; ohne Administratorrechte)."""
    windows.setattr(system, "_wurzel", lambda pfad: "D:\\")
    windows.setattr(system, "_win_volume", lambda w: ("STICK", 0x6AF7488F, 0, "exFAT"))
    windows.setattr(system, "_win_laufwerkstyp", lambda w: system.DRIVE_FIXED)
    windows.setattr(system.shutil, "disk_usage", lambda w: (1000, 400, 600))
    windows.setattr(system, "_win_platte_hinter", ECHT_PLATTE_HINTER)        # die echte, mit nachgestellter Platte
    windows.setattr(system, "_win_geraetenummer", lambda pfad: {"\\\\.\\D:": 1}[pfad])
    windows.setattr(system, "_win_geraet_angaben", lambda g: {
        "\\\\.\\PhysicalDrive1": {"modell": "SanDisk Cruzer", "seriennummer": "4C53", "anschluss": "USB",
                                  "wechselmedium": True, "groesse": 1000, "tabelle": "MBR:1CF642E8"}}[g])
    info = system.datentraeger_info("D:\\")
    assert info["BusProtocol"] == "USB" and info["MediaName"] == "SanDisk Cruzer" and info["RemovableMedia"] is True
    assert system.traegerart(info) == "usb"
    windows.setattr(system, "_win_geraet_angaben", lambda g: {"modell": "Muster Rugged", "anschluss": "USB",
                                                               "wechselmedium": False, "groesse": 1000})
    assert system.traegerart(system.datentraeger_info("D:\\")) == "festplatte"    # USB-Festplatte
    windows.setattr(system, "_win_geraetenummer", lambda pfad: (_ for _ in ()).throw(OSError("CD")))
    assert system.datentraeger_info("D:\\")["BusProtocol"] == ""                   # ohne Platte wie bisher


# ---- Lange Pfade unter Windows (Entscheidung 13.11.2026: Installer richtet ein, Balduin prüft beim Start) ----

def test_lange_pfade_unter_windows_aus_der_registry(windows):
    windows.setattr(system, "_win_registry_dword", lambda schluessel, name: 1)
    assert system.lange_pfade() is True
    windows.setattr(system, "_win_registry_dword", lambda schluessel, name: 0)
    assert system.lange_pfade() is False
    windows.setattr(system, "_win_registry_dword", lambda schluessel, name: None)       # Wert fehlt: aus
    assert system.lange_pfade() is False


def test_lange_pfade_ohne_grenze_auf_mac_und_linux(macos):
    assert system.lange_pfade() is None


def test_datentraegerliste_meldet_fehlende_lange_pfade(windows, leeres_projekt):
    from erfassung import lauf
    windows.setattr(system, "_win_registry_dword", lambda schluessel, name: 0)
    windows.setattr(lauf, "mac_geraete", lambda: [])
    windows.setattr(lauf.platte, "angeschlossene", lambda *a: [])
    assert lauf.datentraeger()["lange_pfade_aus"] is True
    windows.setattr(system, "_win_registry_dword", lambda schluessel, name: 1)
    assert lauf.datentraeger()["lange_pfade_aus"] is False

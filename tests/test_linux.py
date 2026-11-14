"""Linux neben Mac und Windows (Entscheidung 13.11.2026, docs/plan.md).

Wie die Windows-Seite in test_system.py wird die Linux-Seite hier mit nachgestellten Antworten der Systemprogramme
geprüft (lsblk, udisksctl, secret-tool, zenity, gdbus, gio …): welcher Befehl gerufen wird, was herauskommt und vor
allem, dass nichts Gefährliches passiert (kein Einhängen, bei dem ein Journal nachgespielt würde). Echt geprüft wird
Linux erst auf einem Linux-Rechner."""
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from erfassung import system


# Teile der Linux-Seite lassen sich nur auf einem POSIX-Rechner (Mac, Linux) nachstellen: Pfade wie /media/… werden
# unter Windows zu \media\…, es gibt dort keine Unix-Sockets (AF_UNIX für den Türöffner), keine Dateirechte 0600 und
# keine Dateinamen, die nicht in UTF-8 vorliegen. Unter Windows geprüft am 13.11.2026 (UTM): nur diese Fälle scheitern.
nur_posix = pytest.mark.skipif(os.name == "nt", reason="Linux lässt sich hier nur auf einem POSIX-Rechner nachstellen")


@pytest.fixture
def linux(monkeypatch):
    """Tut so, als liefe Balduin unter Linux (nur system.windows/mac/linux; die Programme stellt der Test nach)."""
    monkeypatch.setattr(system, "windows", lambda: False)
    monkeypatch.setattr(system, "mac", lambda: False)
    monkeypatch.setattr(system, "linux", lambda: True)
    return monkeypatch


class Aufrufe:
    """Ersatz für subprocess.run: merkt sich jeden Befehl und antwortet nach einer Tabelle (erstes Wort → Antwort)."""

    def __init__(self, antworten=None):
        self.befehle, self.eingaben, self.antworten = [], [], antworten or {}

    def __call__(self, befehl, **k):
        befehl = [str(x) for x in befehl] if isinstance(befehl, (list, tuple)) else befehl
        self.befehle.append(befehl)
        self.eingaben.append(k.get("input"))
        name = Path(befehl[0]).name if isinstance(befehl, list) else befehl
        antwort = self.antworten.get(name, (0, "", ""))
        if callable(antwort):
            antwort = antwort(befehl)
        code, aus, fehler = antwort
        return SimpleNamespace(returncode=code, stdout=aus, stderr=fehler)


def programme(linux, *namen):
    """Diese Programme gelten als installiert (unter /usr/bin), alle anderen fehlen."""
    linux.setattr(system, "werkzeug_pfad", lambda n: f"/usr/bin/{n}" if n in namen else None)


# ---------- Grundlagen ----------

def test_linux_erkennt_das_system(monkeypatch):
    monkeypatch.setattr(system.sys, "platform", "linux")
    assert system.linux() and not system.mac() and not system.windows()
    monkeypatch.setattr(system.sys, "platform", "darwin")
    assert not system.linux()


def test_app_daten_unter_linux_nach_xdg(linux, tmp_path):
    linux.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert system.app_daten() == tmp_path / "balduin"


def test_systemwoerter_linux(linux):
    w = system.systemwoerter()
    assert w["system"] == "Linux" and w["dateimanager"] == "Dateimanager"
    assert w["im_schluesselspeicher"] == "im Passwortspeicher"
    assert "Administratorpasswort" in w["adminfrage"] and w["formatierwarnung"] == ""


def test_systemwoerter_windows_mit_adminfrage(monkeypatch):
    monkeypatch.setattr(system, "windows", lambda: True)
    monkeypatch.setattr(system, "mac", lambda: False)
    monkeypatch.setattr(system, "linux", lambda: False)
    w = system.systemwoerter()
    assert "Administratorrechten" in w["adminfrage"] and "formatieren" in w["formatierwarnung"]


# ---------- Werkzeuge, Installationshinweise, ClamAV ----------

def test_installationshinweis_linux_mit_paketnamen(linux):
    assert "apt install libimage-exiftool-perl" in system.installationshinweis("exiftool")
    assert "apt install poppler-utils" in system.installationshinweis("pdftotext")
    assert "apt install clamav-daemon" in system.installationshinweis("clamd")
    assert "brew" not in system.installationshinweis("ffmpeg")
    assert "github.com/richardlehane/siegfried" in system.installationshinweis("sf")


@nur_posix
def test_werkzeug_unter_linux_auch_in_sbin(linux, tmp_path):
    sbin = tmp_path / "sbin"
    sbin.mkdir()
    programm = sbin / "clamd"
    programm.write_text("#!/bin/sh\n", encoding="utf-8")
    programm.chmod(0o755)
    linux.setenv("PATH", str(tmp_path / "leer"))
    linux.setenv("BALDUIN_WERKZEUGE", "")
    linux.setattr(system, "ZUSATZ_ORDNER", system.zusatz_ordner())
    assert "/usr/sbin" in system.ZUSATZ_ORDNER and "/opt/homebrew/bin" not in system.ZUSATZ_ORDNER
    linux.setattr(system, "ZUSATZ_ORDNER", [str(sbin)])
    assert system.werkzeug_pfad("clamd") == str(programm)


def test_clamav_konfiguration_linux_vom_system(linux):
    konf, vorlage = system.clamav_konfiguration("/usr/bin/freshclam")
    assert konf == vorlage == Path("/etc/clamav/freshclam.conf")


def test_signaturen_pflegt_unter_linux_der_dienst(linux, tmp_path):
    """Ohne Schreibrecht auf den Ordner der Signaturen ruft Balduin freshclam nicht (es scheiterte nur)."""
    linux.setattr(system, "CLAMAV_SIGNATUREN", tmp_path / "fehlt")
    assert system.signaturen_selbst_auffrischen() is False
    linux.setattr(system, "CLAMAV_SIGNATUREN", tmp_path)
    assert system.signaturen_selbst_auffrischen() is True


def test_signaturen_auf_dem_mac_immer_selbst(monkeypatch):
    monkeypatch.setattr(system, "linux", lambda: False)
    assert system.signaturen_selbst_auffrischen() is True


def test_virenscan_ruft_freshclam_unter_linux_nicht(linux, monkeypatch):
    from erfassung import virenscan
    monkeypatch.setattr(virenscan, "clamav_stand", lambda: "ClamAV 1.4.1/27500/Thu Nov 12 08:00:00 2026")
    monkeypatch.setattr(system, "signaturen_selbst_auffrischen", lambda: False)
    monkeypatch.setattr(virenscan.subprocess, "run", lambda *a, **k: pytest.fail("freshclam darf nicht laufen"))
    assert virenscan.signaturen_auffrischen(hoechstens_tage=0).startswith("ClamAV 1.4.1/27500")


def test_virenscan_ohne_signaturen_unter_linux_mit_hinweis(linux, monkeypatch):
    from erfassung import virenscan
    monkeypatch.setattr(virenscan, "clamav_stand", lambda: "ClamAV 1.4.1")
    monkeypatch.setattr(system, "signaturen_selbst_auffrischen", lambda: False)
    with pytest.raises(RuntimeError, match="clamav-freshclam"):
        virenscan.signaturen_auffrischen()


# ---------- Passwortspeicher (Anton-Token) ----------

def test_geheimnis_unter_linux_ueber_secret_tool(linux):
    linux.delenv("ANTON_SCHLUESSELBUND", raising=False)
    programme(linux, "secret-tool")
    gespeichert = {}

    def antwort(befehl):
        if befehl[1] == "store":
            gespeichert["wert"] = aufrufe.eingaben[-1]
            return 0, "", ""
        if befehl[1] == "lookup":
            return (0, gespeichert["wert"], "") if "wert" in gespeichert else (1, "", "")
        if befehl[1] == "clear":
            gespeichert.clear()
            return 0, "", ""
    aufrufe = Aufrufe({"secret-tool": antwort})
    linux.setattr(system.subprocess, "run", aufrufe)
    assert system.geheimnis_lesen("Anton-API x") == "" and not system.geheimnis_vorhanden("Anton-API x")
    assert system.geheimnis_speichern("Anton-API x", "balduin", "geheim") is True
    store = next(b for b in aufrufe.befehle if b[1] == "store")
    assert "geheim" not in store                               # nie als Argument, nur über stdin
    assert store[-4:] == ["service", "Anton-API x", "account", "balduin"]
    assert system.geheimnis_lesen("Anton-API x") == "geheim" and system.geheimnis_vorhanden("Anton-API x")
    assert system.geheimnis_entfernen("Anton-API x") is True
    assert system.geheimnis_entfernen("Anton-API x") is False


def test_geheimnis_unter_linux_ohne_secret_tool(linux):
    linux.delenv("ANTON_SCHLUESSELBUND", raising=False)
    programme(linux)
    linux.setattr(system.subprocess, "run", lambda *a, **k: pytest.fail("kein Aufruf ohne secret-tool"))
    assert system.geheimnis_lesen("x") == "" and system.geheimnis_speichern("x", "k", "w") is False


@nur_posix
def test_geheimnis_unter_linux_in_tests_im_eigenen_speicher(linux, tmp_path):
    """Tests nennen ANTON_SCHLUESSELBUND; dann bleibt der Passwortspeicher des Rechners unberührt."""
    linux.setenv("ANTON_SCHLUESSELBUND", str(tmp_path / "test.keychain"))
    linux.setattr(system.subprocess, "run", lambda *a, **k: pytest.fail("Passwortspeicher des Rechners berührt"))
    assert system.geheimnis_speichern("d", "k", "w1") is True
    assert system.geheimnis_lesen("d") == "w1" and system.geheimnis_vorhanden("d")
    datei = Path(str(tmp_path / "test.keychain") + ".json")
    assert oct(datei.stat().st_mode & 0o777) == "0o600"
    assert system.geheimnis_entfernen("d") is True and system.geheimnis_lesen("d") == ""


# ---------- Dialoge ----------

def test_ordnerdialog_linux_ueber_zenity(linux, tmp_path):
    programme(linux, "zenity", "kdialog")
    aufrufe = Aufrufe({"zenity": (0, f"{tmp_path}/Wahl/\n", "")})
    linux.setattr(system.subprocess, "run", aufrufe)
    assert system.ordner_waehlen("Ordner wählen", tmp_path) == f"{tmp_path}/Wahl"
    b = aufrufe.befehle[0]
    assert b[:2] == ["/usr/bin/zenity", "--file-selection"] and "--directory" in b
    assert b[b.index("--filename") + 1] == f"{tmp_path}/"


def test_ordnerdialog_linux_abbrechen(linux, tmp_path):
    programme(linux, "zenity")
    linux.setattr(system.subprocess, "run", Aufrufe({"zenity": (1, "", "")}))
    assert system.ordner_waehlen("x", tmp_path) is None


def test_dateidialog_linux_ueber_kdialog(linux, tmp_path):
    programme(linux, "kdialog")
    aufrufe = Aufrufe({"kdialog": (0, f"{tmp_path}/a.dmg\n", "")})
    linux.setattr(system.subprocess, "run", aufrufe)
    assert system.datei_waehlen("Abbild wählen", tmp_path) == f"{tmp_path}/a.dmg"
    assert aufrufe.befehle[0][1:4] == ["--title", "Abbild wählen", "--getopenfilename"]


def test_dialog_linux_rueckfall_tk(linux, tmp_path):
    programme(linux)
    aufrufe = Aufrufe({"python": (0, f"{tmp_path}\n", "")})
    linux.setattr(system.sys, "executable", "/x/python")
    linux.setattr(system.subprocess, "run", aufrufe)
    assert system.ordner_waehlen("x", tmp_path) == str(tmp_path)
    assert aufrufe.befehle[0][0] == "/x/python" and "tkinter" in aufrufe.befehle[0][2]
    linux.setattr(system.subprocess, "run", Aufrufe({"python": (0, "\n", "")}))
    assert system.datei_waehlen("x", tmp_path) is None


def test_dialog_linux_fehler(linux, tmp_path):
    programme(linux, "zenity")
    linux.setattr(system.subprocess, "run", Aufrufe({"zenity": (5, "", "kaputt")}))
    with pytest.raises(RuntimeError, match="kaputt"):
        system.ordner_waehlen("x", tmp_path)


# ---------- Dateimanager, Papierkorb ----------

def test_dateimanager_linux_showitems(linux, tmp_path):
    programme(linux, "gdbus", "xdg-open")
    datei = tmp_path / "a b.txt"
    datei.write_text("x", encoding="utf-8")
    aufrufe = Aufrufe()
    linux.setattr(system.subprocess, "run", aufrufe)
    system.im_dateimanager_zeigen(datei)
    b = aufrufe.befehle[0]
    assert b[0] == "/usr/bin/gdbus" and "org.freedesktop.FileManager1.ShowItems" in b
    assert f"['{datei.resolve().as_uri()}']" in b and len(aufrufe.befehle) == 1


def test_dateimanager_linux_rueckfall_xdg_open(linux, tmp_path):
    programme(linux, "gdbus", "xdg-open")
    datei = tmp_path / "a.txt"
    datei.write_text("x", encoding="utf-8")
    aufrufe = Aufrufe({"gdbus": (1, "", "kein Dienst")})
    linux.setattr(system.subprocess, "run", aufrufe)
    linux.setattr(system.subprocess, "Popen", lambda befehl, **k: aufrufe.befehle.append(befehl))
    system.im_dateimanager_zeigen(datei)
    assert aufrufe.befehle[-1] == ["/usr/bin/xdg-open", str(tmp_path.resolve())]


def test_dateimanager_linux_ohne_programme(linux, tmp_path):
    programme(linux)
    with pytest.raises(RuntimeError):
        system.im_dateimanager_zeigen(tmp_path)


def test_papierkorb_linux_ueber_gio(linux, tmp_path):
    programme(linux, "gio")
    ordner = tmp_path / "Projekt"
    ordner.mkdir()
    aufrufe = Aufrufe()
    linux.setattr(system.subprocess, "run", aufrufe)
    system.in_papierkorb(ordner)
    assert aufrufe.befehle == [["/usr/bin/gio", "trash", str(ordner.resolve())]]


def test_papierkorb_linux_ueber_kde(linux, tmp_path):
    programme(linux, "kioclient5")
    aufrufe = Aufrufe()
    linux.setattr(system.subprocess, "run", aufrufe)
    system.in_papierkorb(tmp_path)
    assert aufrufe.befehle == [["/usr/bin/kioclient5", "move", str(tmp_path.resolve()), "trash:/"]]


def test_papierkorb_linux_fehler_und_ohne_programm(linux, tmp_path):
    programme(linux, "gio")
    linux.setattr(system.subprocess, "run", Aufrufe({"gio": (1, "", "nein")}))
    with pytest.raises(RuntimeError, match="nein"):
        system.in_papierkorb(tmp_path)
    programme(linux)
    with pytest.raises(RuntimeError, match="von Hand"):
        system.in_papierkorb(tmp_path)


# ---------- Start ----------

def test_startskript_fuer_linux():
    code = Path(system.CODE)
    skript = code / "balduin.sh"
    assert skript.is_file() and os.access(skript, os.X_OK)
    text = skript.read_text(encoding="utf-8")
    assert text.startswith("#!/bin/sh") and ".venv/bin/python" in text and "tool/server.py" in text
    desktop = (code / "Balduin.desktop").read_text(encoding="utf-8")
    assert "[Desktop Entry]" in desktop and "balduin.sh" in desktop and "Terminal=true" in desktop


# ---------- Datenträger (lsblk) ----------
# Antwort von lsblk -J -b wie auf einem Rechner mit Systemplatte, USB-Stick, Mac-Platte (HFS+ eingebunden, ext4
# daneben), nicht eingebundener APFS-Platte, CD, Snap-Paket und eingebundenem Abbild. Ältere lsblk liefern Zahlen und
# Wahrheitswerte als Text; das kommt hier gemischt vor.
LSBLK = {"blockdevices": [
    {"name": "nvme0n1", "uuid": None, "label": None, "fstype": None, "size": 512110190592, "rm": False, "hotplug": False,
     "tran": "nvme", "type": "disk", "model": "Samsung SSD 980", "serial": "S1", "ro": False, "mountpoint": None,
     "children": [
         {"name": "nvme0n1p1", "uuid": "AAAA-BBBB", "label": None, "fstype": "vfat", "size": 536870912, "rm": False,
          "tran": None, "type": "part", "model": None, "serial": None, "ro": False, "mountpoint": "/boot/efi"},
         {"name": "nvme0n1p2", "uuid": "0b1c", "label": None, "fstype": "ext4", "size": 511000000000, "rm": False,
          "tran": None, "type": "part", "model": None, "serial": None, "ro": False, "mountpoint": "/"}]},
    {"name": "sdb", "size": "16008609792", "rm": "1", "tran": "usb", "type": "disk", "model": "Cruzer Blade",
     "serial": "4C53", "ro": "0", "mountpoint": None, "children": [
         {"name": "sdb1", "uuid": "1234-ABCD", "label": "STICK", "fstype": "vfat", "size": "16008593408", "rm": "1",
          "type": "part", "ro": "0", "mountpoint": "/media/marc/STICK"}]},
    {"name": "sdc", "size": 2000398934016, "rm": False, "tran": "usb", "type": "disk", "model": "Elements 25A2",
     "serial": "WX1", "ro": False, "mountpoint": None, "children": [
         {"name": "sdc1", "uuid": "0011223344556677", "label": "MAC07", "fstype": "hfsplus", "size": 1000000000000,
          "rm": False, "type": "part", "ro": True, "mountpoint": "/run/media/marc/MAC07"},
         {"name": "sdc2", "uuid": "e5f0c1d2-1111-2222-3333-444455556666", "label": "Daten", "fstype": "ext4",
          "size": 1000000000000, "rm": False, "type": "part", "ro": False, "mountpoint": "/media/marc/Daten"}]},
    {"name": "sdd", "size": 1000204886016, "rm": False, "tran": "usb", "type": "disk", "model": "My Passport",
     "serial": "WD123", "ro": False, "mountpoint": None, "pttype": "gpt",
     "ptuuid": "b80225af-d204-43ea-9214-c1e4ee8d95bd", "children": [
         {"name": "sdd1", "fstype": "vfat", "label": "EFI", "size": 209715200, "type": "part", "mountpoint": None},
         {"name": "sdd2", "fstype": "apfs", "label": None, "size": 999000000000, "type": "part", "mountpoint": None}]},
    {"name": "sr0", "uuid": "2001-01-01-00-00-00-00", "label": "CD1", "fstype": "iso9660", "size": 700000000,
     "rm": True, "tran": "sata", "type": "rom", "model": "DVD-RW", "serial": None, "ro": True,
     "mountpoint": "/media/marc/CD1"},
    {"name": "loop0", "fstype": "squashfs", "size": 1000, "rm": False, "tran": None, "type": "loop",
     "mountpoint": "/snap/core/17200"},
    {"name": "loop5", "uuid": "8899aabbccddeeff", "label": "Abbild", "fstype": "hfsplus", "size": 5000000,
     "rm": False, "tran": None, "type": "loop", "ro": True, "mountpoint": "/media/marc/Abbild"},
    {"name": "mmcblk0", "size": 64000000000, "rm": False, "tran": None, "type": "disk", "model": None,
     "serial": "0x1", "mountpoint": None, "children": [
         {"name": "mmcblk0p1", "uuid": "3333-4444", "label": "KAMERA", "fstype": "exfat", "size": 64000000000,
          "type": "part", "mountpoint": "/mnt/karte"}]},
]}
EINGEHAENGT = {"/media/marc/STICK", "/run/media/marc/MAC07", "/media/marc/Daten", "/media/marc/CD1", "/media/marc/Abbild",
               "/mnt/karte", "/boot/efi", "/", "/snap/core/17200"}


@pytest.fixture
def rechner(linux):
    """Linux-Rechner mit den Geräten aus LSBLK; Mountpunkte gelten als Ordner, Platz ist 1 TB / 400 GB frei."""
    linux.setattr(system, "VOLUMES", Path("/media"))            # wird beim Import je System festgelegt
    linux.setattr(system, "werkzeug_pfad", lambda n: f"/usr/bin/{n}")
    linux.setattr(system.subprocess, "run", Aufrufe({"lsblk": (0, json.dumps(LSBLK), "")}))
    linux.setattr(system.os.path, "ismount", lambda p: str(p) in EINGEHAENGT)
    linux.setattr(system.os.path, "isdir", lambda p: str(p) in EINGEHAENGT)
    linux.setattr(system.shutil, "disk_usage", lambda p: (10**12, 6 * 10**11, 4 * 10**11))
    return linux


def test_lsblk_wird_mit_festen_spalten_gerufen(rechner):
    geraete = system._linux_geraete()
    befehl = system.subprocess.run.befehle[0]
    assert befehl[:3] == ["/usr/bin/lsblk", "-J", "-b"] and "MOUNTPOINT" in befehl[befehl.index("-o") + 1]
    namen = [g["name"] for g in geraete]
    assert "sdb1" in namen and "nvme0n1p2" in namen and "sdd" in namen
    sdb1 = next(g for g in geraete if g["name"] == "sdb1")
    assert sdb1["disk"]["tran"] == "usb" and sdb1["size"] == 16008593408 and sdb1["rm"] is True


def test_volumes_unter_linux_ist_media():
    """Marke für „Datenträger des Rechners“ wie „Laufwerke“ unter Windows; gelesen wird über lsblk."""
    if sys.platform.startswith("linux"):
        assert system.VOLUMES == Path("/media")


@nur_posix
def test_datentraeger_liste_unter_linux(rechner):
    liste = system.datentraeger_liste(Path("/media"))
    assert [str(p) for p in liste] == ["/media/marc/Abbild", "/media/marc/CD1", "/media/marc/Daten", "/media/marc/STICK",
                                       "/mnt/karte", "/run/media/marc/MAC07"]


def test_datentraeger_liste_in_tests_bleibt_ein_ordner(linux, tmp_path):
    (tmp_path / "HD01").mkdir()
    linux.setattr(system.subprocess, "run", lambda *a, **k: pytest.fail("lsblk in Tests"))
    assert system.datentraeger_liste(tmp_path) == [tmp_path / "HD01"]


@nur_posix
def test_ist_datentraeger_und_datentraeger_von_unter_linux(rechner):
    v = Path("/media")
    assert system.ist_datentraeger(Path("/media/marc/STICK"), v)
    assert not system.ist_datentraeger(Path("/media/marc/STICK/Fotos"), v)
    assert not system.ist_datentraeger(Path("/"), v) and not system.ist_datentraeger(Path("/boot/efi"), v)
    assert system.datentraeger_von(Path("/media/marc/STICK/Fotos/a.jpg"), v) == Path("/media/marc/STICK")
    assert system.datentraeger_von(Path("/run/media/marc/MAC07/x"), v) == Path("/run/media/marc/MAC07")
    assert system.datentraeger_von(Path("/home/marc/Projekte/x"), v) is None


def test_vermuteter_mountpunkt_unter_linux(rechner):
    assert system.vermuteter_mountpunkt("MAC07", Path("/media")) == Path("/run/media/marc/MAC07")
    assert not system.vermuteter_mountpunkt("Fehlt", Path("/media")).exists()


@nur_posix
def test_datentraeger_info_unter_linux_mit_schluesseln_von_diskutil(rechner):
    i = system.datentraeger_info(Path("/media/marc/STICK"))
    from erfassung import macplatte                      # FAT/exFAT: Kennung wie auf dem Mac (13.11.2026)
    assert i["VolumeUUID"] == macplatte.fat_uuid(0x1234ABCD) and i["VolumeUUIDAlt"] == "1234-ABCD"
    assert i["VolumeName"] == "STICK" and i["DeviceIdentifier"] == "sdb1"
    assert i["DevicePath"] == "/dev/sdb1" and i["MediaName"] == "Cruzer Blade" and i["BusProtocol"] == "USB"
    assert i["FilesystemName"] == "FAT32" and i["RemovableMedia"] is True and i["MountPoint"] == "/media/marc/STICK"
    assert i["TotalSize"] == 10**12 and i["FreeSpace"] == 4 * 10**11
    assert system.traegerart(i) == "usb"


@nur_posix
def test_datentraeger_info_unter_linux_je_art(rechner):
    mac07 = system.datentraeger_info(Path("/run/media/marc/MAC07"))
    assert mac07["FilesystemName"] == "HFS+" and system.traegerart(mac07) == "festplatte"
    from erfassung import macplatte
    assert mac07["VolumeUUID"] == macplatte.hfs_uuid(bytes.fromhex("0011223344556677"))   # wie macOS sie nennt
    assert system.traegerart(system.datentraeger_info(Path("/media/marc/CD1"))) == "cd"
    assert system.traegerart(system.datentraeger_info(Path("/media/marc/Abbild"))) == "image"
    assert system.traegerart(system.datentraeger_info(Path("/mnt/karte"))) == "karte"
    assert system.datentraeger_info(Path("/media/marc/Daten"))["VolumeUUID"] == "E5F0C1D2-1111-2222-3333-444455556666"


def test_datentraeger_info_unter_linux_ordner_leer(rechner):
    assert system.datentraeger_info(Path("/media/marc/STICK/Fotos")) == {}
    assert system.datentraeger_info(Path("/home/marc")) == {}


def test_maske_fuer_mountpfade_unter_linux():
    import re
    muster = re.compile(system.MOUNTPFAD_MUSTER)
    for pfad in ("/media/marc/STICK/Fotos/a b.jpg", "/run/media/marc/MAC07/x.tif", "/mnt/karte/DCIM/1.jpg"):
        assert muster.sub("(Datei)", f"Fehler bei '{pfad}'") == "Fehler bei (Datei)"
    assert muster.sub("(Datei)", "Fehler bei '/Volumes/HD01/a.jpg'") == "Fehler bei (Datei)"


# ---------- Schreibgeschützt einhängen (harte Regel 1) ----------

@nur_posix
@pytest.mark.parametrize("pfad, optionen", [("/media/marc/STICK", "ro"), ("/media/marc/Daten", "ro,noload")])
def test_einhaengen_unter_linux_ueber_udisks(rechner, pfad, optionen):
    neu = pfad.replace("/media/", "/media/neu/")
    aufrufe = Aufrufe({"lsblk": (0, json.dumps(LSBLK), ""),
                       "udisksctl": lambda b: (0, f"Mounted {b[3]} at {neu}\n" if b[1] == "mount" else "Unmounted\n", "")})
    rechner.setattr(system.subprocess, "run", aufrufe)
    rechner.setattr(system, "ist_schreibgeschuetzt", lambda p: str(p) == neu)
    mountpunkt, meldungen = system.nur_lesend_einhaengen(Path(pfad))
    assert mountpunkt == neu and len(meldungen) == 2
    geraet = "/dev/" + system.datentraeger_info(Path(pfad))["DeviceIdentifier"]
    udisks = [b for b in aufrufe.befehle if b[0].endswith("udisksctl")]
    assert udisks == [["/usr/bin/udisksctl", "unmount", "-b", geraet],
                      ["/usr/bin/udisksctl", "mount", "-b", geraet, "-o", optionen]]


def test_einhaengen_ohne_journal_nachspielen():
    """ext3/ext4/XFS/Btrfs spielen beim Einhängen sonst ihr Journal nach, auch bei ro: sie würden schreiben."""
    assert system.nur_lesend_optionen("ext4") == "ro,noload" and system.nur_lesend_optionen("ext3") == "ro,noload"
    assert system.nur_lesend_optionen("xfs") == "ro,norecovery"
    assert system.nur_lesend_optionen("btrfs") == "ro,nologreplay"
    assert system.nur_lesend_optionen("vfat") == system.nur_lesend_optionen("hfsplus") == "ro"


@nur_posix
def test_einhaengen_unter_linux_scheitert_laut(rechner):
    aufrufe = Aufrufe({"lsblk": (0, json.dumps(LSBLK), ""),
                       "udisksctl": lambda b: (1, "", "Option noload nicht erlaubt") if b[1] == "mount" else (0, "", "")})
    rechner.setattr(system.subprocess, "run", aufrufe)
    with pytest.raises(RuntimeError, match="noload nicht erlaubt"):
        system.nur_lesend_einhaengen(Path("/media/marc/Daten"))
    # kein zweiter Versuch ohne noload
    assert [b for b in aufrufe.befehle if b[1] == "mount"] == [
        ["/usr/bin/udisksctl", "mount", "-b", "/dev/sdc2", "-o", "ro,noload"]]


@nur_posix
def test_einhaengen_unter_linux_prueft_den_schreibschutz(rechner):
    aufrufe = Aufrufe({"lsblk": (0, json.dumps(LSBLK), ""),
                       "udisksctl": lambda b: (0, "Mounted /dev/sdb1 at /media/marc/STICK.\n", "")})
    rechner.setattr(system.subprocess, "run", aufrufe)
    rechner.setattr(system, "ist_schreibgeschuetzt", lambda p: False)
    with pytest.raises(RuntimeError, match="nicht schreibgeschützt"):
        system.nur_lesend_einhaengen(Path("/media/marc/STICK"))


@nur_posix
def test_einhaengen_unter_linux_ohne_udisks(rechner):
    rechner.setattr(system, "werkzeug_pfad", lambda n: "/usr/bin/lsblk" if n == "lsblk" else None)
    with pytest.raises(RuntimeError, match="udisks2"):
        system.nur_lesend_einhaengen(Path("/media/marc/STICK"))


def test_smart_unter_linux(rechner):
    rechner.setattr(system.subprocess, "run", Aufrufe({"smartctl": (0, "SMART overall-health self-assessment test "
                                                                     "result: PASSED\n", "")}))
    assert system.smart_status("sdb1") == "PASSED"
    assert system.subprocess.run.befehle[0] == ["/usr/bin/smartctl", "-H", "/dev/sdb"]
    rechner.setattr(system.subprocess, "run", Aufrufe({"smartctl": (2, "Smartctl open device: /dev/nvme0 failed: "
                                                                     "Permission denied\n", "")}))
    assert "Administratorrechte" in system.smart_status("nvme0n1p2")
    assert system.subprocess.run.befehle[0] == ["/usr/bin/smartctl", "-H", "/dev/nvme0n1"]


# ---------- Mac-Datenträger ohne Einhängen ----------

@pytest.fixture
def kurzer_socket():
    """Socket-Pfade dürfen nur rund 100 Zeichen lang sein; der Temp-Ordner des Mac ist dafür zu tief."""
    import shutil
    import tempfile
    ordner = tempfile.mkdtemp(prefix="bt", dir="/tmp" if os.path.isdir("/tmp") else None)
    yield os.path.join(ordner, "s")
    shutil.rmtree(ordner, ignore_errors=True)


def test_geraet_name_unter_linux(linux):
    assert system.geraet_name("/dev/sdd") == "/dev/sdd" and system.ist_geraet("/dev/nvme1n1")
    assert system.geraet_name("/dev/sdd1") is None and system.geraet_name("/dev/../etc/passwd") is None
    assert system.geraet_name("/media/marc/STICK") is None and not system.ist_geraet(r"\\.\PhysicalDrive1")


def test_physische_datentraeger_unter_linux(rechner):
    liste = {d["geraet"]: d for d in system.physische_datentraeger()}
    assert "/dev/nvme0n1" not in liste                         # Systemplatte
    assert "/dev/sr0" not in liste and "/dev/loop5" not in liste
    sdd = liste["/dev/sdd"]
    assert sdd["laufwerksbuchstaben"] is False and sdd["modell"] == "My Passport" and sdd["seriennummer"] == "WD123"
    assert sdd["anschluss"] == "USB" and sdd["groesse"] == 1000204886016
    assert sdd["tabelle"] == "GPT:B80225AF-D204-43EA-9214-C1E4EE8D95BD"            # Wiedererkennen (13.11.2026)
    assert liste["/dev/sdb"]["laufwerksbuchstaben"] is True     # eingebunden: kein Fall für „Mac-Datenträger lesen“


def test_geraet_oeffnen_unter_linux_direkt_mit_leserecht(linux, tmp_path):
    abbild = tmp_path / "geraet"
    abbild.write_bytes(b"x" * 8192)
    linux.setattr(system, "geraet_name", lambda g: str(abbild))
    linux.setattr(system, "_linux_tueroeffner", lambda g: pytest.fail("kein Türöffner nötig"))
    f, groesse, sektor = system.geraet_oeffnen(str(abbild))
    with f:
        assert f.read(3) == b"xxx" and groesse == 8192 and sektor == 1 and f.mode == "rb"


def test_geraet_oeffnen_unter_linux_ueber_den_tueroeffner(linux, tmp_path):
    abbild = tmp_path / "geraet"
    abbild.write_bytes(b"y" * 4096)
    linux.setattr(system, "geraet_name", lambda g: str(abbild))
    linux.setattr(system.os, "access", lambda p, m: False)
    linux.setattr(system, "_linux_tueroeffner", lambda g: os.open(abbild, os.O_RDONLY))
    f, groesse, _ = system.geraet_oeffnen(str(abbild))
    with f:
        assert f.read(2) == b"yy" and groesse == 4096


@nur_posix
def test_tueroeffner_linux_prueft_den_auftrag():
    from erfassung import tueroeffner_linux as t
    assert t.auftrag_pruefen(["/dev/sdd", "/tmp/balduin-tuer-x/s"]) == ("/dev/sdd", "/tmp/balduin-tuer-x/s")
    for falsch in (["/dev/sdd1", "/tmp/s"], ["/etc/shadow", "/tmp/s"], ["/dev/sdd", "s"], ["/dev/sdd"]):
        with pytest.raises(ValueError):
            t.auftrag_pruefen(falsch)


@nur_posix
def test_tueroeffner_linux_gibt_nur_lesenden_zugriff_weiter(tmp_path, monkeypatch, kurzer_socket):
    """Ein Unterprozess wie unter pkexec: öffnet nur lesend und reicht den Zugriff über den Socket weiter."""
    from erfassung import tueroeffner_linux as t
    geraet = tmp_path / "platte"
    geraet.write_bytes(b"MACPLATTE")
    monkeypatch.setattr(t, "MUSTER", __import__("re").compile(".*"))
    monkeypatch.setattr(t, "ist_blockgeraet", lambda fd: True)
    import socket
    import threading
    adresse = kurzer_socket
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.bind(adresse)
        s.listen(1)
        threading.Thread(target=t.main, args=([str(geraet), adresse],)).start()
        verbindung, _ = s.accept()
        with verbindung:
            nachricht, fds, _, _ = socket.recv_fds(verbindung, 1024, 1)
    assert nachricht == b"ok" and len(fds) == 1
    with os.fdopen(fds[0], "rb") as f:
        assert f.read() == b"MACPLATTE"
        with pytest.raises(OSError):
            os.write(f.fileno(), b"x")


@nur_posix
def test_tueroeffner_linux_meldet_fehler(tmp_path, monkeypatch, kurzer_socket):
    from erfassung import tueroeffner_linux as t
    monkeypatch.setenv("BALDUIN_SCHUTZ_PROTOKOLL", str(tmp_path / "eigenes.log"))   # die Schutzwache weist /dev/sdzz ab
    import socket
    import threading
    adresse = kurzer_socket
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.bind(adresse)
        s.listen(1)
        threading.Thread(target=t.main, args=(["/dev/sdzz", adresse],)).start()
        verbindung, _ = s.accept()
        with verbindung:
            nachricht, fds, _, _ = socket.recv_fds(verbindung, 1024, 1)
    assert not fds and b"/dev/sdzz" in nachricht


# ---------- Schutzwache auch für Linux-Mountpunkte und Geräte ----------

@pytest.mark.parametrize("pfad", ["/media/marc/STICK/a.jpg", "/run/media/marc/MAC07", "/mnt/karte/x", "/dev/sdb",
                                  "/dev/nvme0n1p1", "/dev/disk4", "/dev/rdisk4"])
def test_schutzwache_sperrt_linux_orte(pfad, monkeypatch, tmp_path):
    import schutzwache
    monkeypatch.setenv("BALDUIN_SCHUTZ_PROTOKOLL", str(tmp_path / "eigenes.log"))   # nicht das echte Protokoll füllen
    assert schutzwache.unter_volumes(pfad)
    with pytest.raises(PermissionError):
        schutzwache.pruefen("open", (pfad, "r"))


@pytest.mark.parametrize("pfad", ["/mediathek/x", "/dev/null", "/dev/urandom", "/mntx", "/run/user/1000/x"])
def test_schutzwache_laesst_aehnliche_orte(pfad):
    import schutzwache
    assert not schutzwache.unter_volumes(pfad)


@pytest.fixture
def pkexec(linux, tmp_path, monkeypatch):
    """Nachgestelltes pkexec (führt den Befehl ohne Rückfrage aus oder lehnt ab); /dev/sdzz gibt es nicht."""
    import re
    import schutzwache
    monkeypatch.setattr(schutzwache, "GERAETE", re.compile("(?!)"))     # /dev/sdzz im Befehl erlauben (gibt es nicht)

    def einrichten(ablehnen=False):
        programm = tmp_path / "pkexec"
        programm.write_text("#!/bin/sh\n" + ("echo 'Not authorized' >&2; exit 126\n" if ablehnen else 'exec "$@"\n'),
                            encoding="utf-8")
        programm.chmod(0o755)
        linux.setattr(system, "werkzeug_pfad", lambda n: str(programm) if n == "pkexec" else None)
    return einrichten


@nur_posix
def test_linux_tueroeffner_abgelehnt(pkexec):
    pkexec(ablehnen=True)
    with pytest.raises(RuntimeError, match="abgelehnt.*Not authorized"):
        system._linux_tueroeffner("/dev/sdzz")


@nur_posix
def test_linux_tueroeffner_meldet_den_fehler_des_helfers(pkexec):
    pkexec()
    with pytest.raises(RuntimeError, match="/dev/sdzz lässt sich nicht öffnen"):
        system._linux_tueroeffner("/dev/sdzz")


def test_linux_tueroeffner_ohne_pkexec(linux):
    programme(linux)
    with pytest.raises(RuntimeError, match="Abbild"):
        system._linux_tueroeffner("/dev/sdd")


# ---------- Dateinamen, die nicht in UTF-8 vorliegen (nur unter Linux möglich) ----------

class FalscherEintrag:
    """Eintrag aus os.scandir mit einem Namen in Latin-1 (Python gibt die Bytes als „Surrogate“ weiter)."""

    def __init__(self, ordner, name, ist_ordner=False, vorlage=None):
        self.name, self.path, self._ordner, self._vorlage = name, os.path.join(ordner, name), ist_ordner, vorlage

    def is_symlink(self):
        return False

    def is_dir(self):
        return self._ordner

    def stat(self):
        return os.stat(self._vorlage)


@nur_posix
def test_dateiname_nicht_in_utf8_wird_lesefehler(tmp_path, monkeypatch):
    """SQLite nimmt solche Namen nicht an; still ersetzen hieße, die Datei später nicht wiederzufinden."""
    from erfassung import quelle
    (tmp_path / "gut.txt").write_text("x", encoding="utf-8")
    echt = os.scandir
    falsch = os.fsdecode(b"caf\xe9.txt")
    ordner = os.fsdecode(b"Gr\xfcn")

    def scandir(o):
        if str(o) != str(tmp_path):
            return echt(o)
        return [*echt(o), FalscherEintrag(str(tmp_path), falsch, vorlage=tmp_path / "gut.txt"),
                FalscherEintrag(str(tmp_path), ordner, ist_ordner=True)]
    monkeypatch.setattr(quelle.os, "scandir", scandir)
    eintraege = list(quelle.eintraege(tmp_path))
    assert [e[1] for e in eintraege if e[0] == "datei"] == ["gut.txt"]
    fehler = sorted(e for e in eintraege if e[0] == "fehler")
    assert [f[1] for f in fehler] == ["Gr�n", "caf�.txt"]
    assert all("nicht in UTF-8" in f[2] for f in fehler)
    assert "b'caf\\xe9.txt'" in fehler[1][2]
    for f in fehler:                                           # lässt sich speichern
        f[1].encode("utf-8"), f[2].encode("utf-8")


@nur_posix
def test_unterordner_ohne_namen_ausser_utf8(tmp_path, monkeypatch):
    from erfassung import quelle
    (tmp_path / "Gut").mkdir()
    echt = os.scandir
    monkeypatch.setattr(quelle.os, "scandir", lambda o: [*echt(o), FalscherEintrag(str(tmp_path), os.fsdecode(b"Gr\xfcn"),
                                                                                    ist_ordner=True)]
                        if str(o) == str(tmp_path) else echt(o))
    assert quelle.unterordner(tmp_path) == [("Gut", False)]

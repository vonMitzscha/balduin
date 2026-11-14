"""Plattformabhängiges an einer Stelle (Entscheidungen 30.10. und 09.11.2026: Entwicklung auf macOS, Auslieferung
für Mac und Windows).

Je Aufgabe eine Funktion; der übrige Code ruft nur diese Funktionen und nie selbst Systemwerkzeuge (diskutil,
qlmanage, security, osascript, open, explorer, powershell) oder feste Systempfade (/Volumes, /opt/homebrew,
~/Library). Nur Standardbibliothek, damit auch der Server (tool/server.py) dieses Modul laden kann, ohne das Paket
erfassung mit seinen Rechenbibliotheken zu importieren.

Windows wird über die Win32-API (ctypes) angesprochen. Diese Aufrufe stehen in den Funktionen _win_…; die Tests
stellen sie nach, weil sie auf dem Mac nicht laufen (tests/test_system.py). Echt geprüft wird Windows erst auf einem
Windows-Rechner.
"""
import errno
import json
import os
import plistlib
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent        # Ordner mit Tool und erfassung/ (im Git bzw. im Paket)


def windows():
    return sys.platform == "win32"


def mac():
    return sys.platform == "darwin"


def linux():
    """Linux (Entscheidung 13.11.2026); neue Zweige nur hierunter, Mac und Windows bleiben, wie sie sind.
    Fragt windows() und mac() mit, damit Tests, die eines davon nachstellen, auch unter Linux diesen Zweig prüfen."""
    return sys.platform.startswith("linux") and not windows() and not mac()


# ---------- Prozesse ----------
# Windows: Konstanten aus winbase.h (subprocess kennt sie nur unter Windows)
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


def lauf_befehl(*argumente):
    """Befehl für einen Aufruf von erfassung/lauf.py mit demselben Python (später auch im Paket), im UTF-8-Modus:
    Dateien, Konsole und Antworten an den Server sind dann überall UTF-8 (unter Windows sonst cp1252)."""
    return [sys.executable, "-X", "utf8", "-m", "erfassung.lauf", *map(str, argumente)]


def prozess_optionen():
    """Zusätzliche Angaben für kurze Aufrufe von Programmen: unter Windows ohne aufblitzendes Konsolenfenster."""
    return {"creationflags": CREATE_NO_WINDOW} if windows() else {}


def hintergrund_starten(befehl, cwd, eingabe=None):
    """Startet einen Hintergrundlauf, der weiterläuft, wenn Server, Terminal oder Browser zugehen.
    macOS: eigene Sitzung; Windows: eigene Prozessgruppe ohne Fenster (start_new_session wirkt dort nicht).
    eingabe: eine Zeile für stdin (Passwort eines verschlüsselten Volumes; so steht es in keiner Prozessliste)."""
    eigen = ({"creationflags": CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW} if windows()
             else {"start_new_session": True})
    prozess = subprocess.Popen(befehl, cwd=cwd, stdin=subprocess.PIPE if eingabe else subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **eigen)
    if eingabe:
        prozess.stdin.write((eingabe + "\n").encode("utf-8"))
        prozess.stdin.close()
    return prozess


def lebt(pid):
    """Läuft der Prozess noch? Unter Windows nur nachfragen: os.kill(pid, 0) beendet dort den Prozess."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return False
    if windows():
        return _win_prozess_lebt(pid)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def unterbrechen(pid):
    """Unterbricht einen Lauf wie Ctrl+C, damit er an seiner nächsten Prüfstelle aufhört. True = Signal geschickt.
    Unter Windows nichts (os.kill wäre dort ein harter Abbruch); dort hält der Lauf über die Marke lauf.abbrechen an,
    die seine Abbruchwache liest (erfassung/lauf.py)."""
    if windows() or not lebt(pid):
        return False
    os.kill(pid, signal.SIGINT)
    return True


def _win_prozess_lebt(pid):
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    griff = kernel32.OpenProcess(0x1000, False, pid)                  # PROCESS_QUERY_LIMITED_INFORMATION
    if not griff:
        return ctypes.get_last_error() == 5                           # Zugriff verweigert: es gibt ihn
    try:
        code = ctypes.c_ulong()
        return bool(kernel32.GetExitCodeProcess(griff, ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
    finally:
        kernel32.CloseHandle(griff)


# ---------- Datenträger ----------
# macOS hängt Datenträger unter /Volumes ein. Unter Windows sind es die Laufwerksbuchstaben; VOLUMES steht dort nur
# als Marke für „alle Laufwerke“ und wird nie als Ordner gelesen. In Tests ist volumes ein gewöhnlicher Ordner, dessen
# Unterordner als Datenträger gelten.
# Linux (Entscheidung 13.11.2026): /media steht nur als Marke für „alle Datenträger“; gelesen wird über lsblk und die
# Mountpunkte unter LINUX_MOUNTS.
VOLUMES = Path("Laufwerke") if windows() else Path("/media") if linux() else Path("/Volumes")
LINUX_MOUNTS = ("/media", "/run/media", "/mnt")
# Windows: GetDriveTypeW
DRIVE_REMOVABLE, DRIVE_FIXED, DRIVE_REMOTE, DRIVE_CDROM, DRIVE_RAMDISK = 2, 3, 4, 5, 6
FILE_READ_ONLY_VOLUME = 0x00080000
# Mountpfade in Meldungen (für Berichte durch „(Datei)“ ersetzt): /Volumes/<Platte>/…, E:\…, unter Linux
# /media/<Benutzer>/<Platte>/…, /run/media/<Benutzer>/<Platte>/… oder /mnt/<Platte>/…
MOUNTPFAD_MUSTER = (r"'?(?:/Volumes/[^/']+/|[A-Za-z]:\\|/media/[^/']+/[^/']+/|/run/media/[^/']+/[^/']+/|/mnt/[^/']+/)"
                    r"[^']*'?")


def standard_volumes(volumes):
    """Sind die echten Datenträger des Rechners gemeint (nicht ein Ordner aus den Tests)?"""
    return str(volumes).replace("\\", "/") == str(VOLUMES).replace("\\", "/")


def datentraeger_liste(volumes=VOLUMES):
    """Wurzeln der angeschlossenen Datenträger, wie der Dateimanager sie zeigt: sichtbar und wirklich eingehängt
    (macOS ohne Verweise wie „Macintosh HD“, ohne leere Reste unter /Volumes und versteckte Mounts; Windows ohne
    Systemlaufwerk und Netzlaufwerke). Gelesen werden nur Angaben, keine Dateien."""
    volumes = Path(volumes)
    if standard_volumes(volumes) and linux():
        return _linux_datentraeger_liste()
    if standard_volumes(volumes) and windows():
        system_lw = _systemlaufwerk().upper()
        return [Path(w) for w in _win_laufwerke()
                if w[:2].upper() != system_lw and _win_laufwerkstyp(w) in (DRIVE_REMOVABLE, DRIVE_FIXED, DRIVE_CDROM)
                and os.path.isdir(w)]
    if not volumes.is_dir():
        return []
    echt = standard_volumes(volumes)
    unsichtbar = unsichtbare_mounts() if echt else set()
    liste = []
    for eintrag in sorted(volumes.iterdir()):
        if eintrag.is_symlink() or not eintrag.is_dir() or eintrag.name.startswith("."):
            continue
        if echt and (not os.path.ismount(eintrag) or str(eintrag) in unsichtbar):
            continue
        liste.append(eintrag)
    return liste


def ist_datentraeger(pfad, volumes=VOLUMES):
    """Ist pfad die Wurzel eines Datenträgers (nicht ein Ordner darauf, nicht das Systemlaufwerk)?"""
    pfad = Path(pfad)
    if standard_volumes(volumes) and linux():
        return _linux_mountpunkt(pfad)
    if standard_volumes(volumes) and windows():
        return bool(pfad.anchor) and pfad == Path(pfad.anchor) and pfad.anchor[:2].upper() != _systemlaufwerk().upper()
    return pfad.parent == Path(volumes) and pfad != Path(volumes)


def datentraeger_von(pfad, volumes=VOLUMES):
    """Wurzel des Datenträgers, auf dem pfad liegt; None = internes Laufwerk des Rechners."""
    pfad = Path(pfad)
    if standard_volumes(volumes) and linux():
        return next((p for p in (pfad, *pfad.parents) if _linux_mountpunkt(p)), None)
    if standard_volumes(volumes) and windows():
        anker = pfad.anchor
        return Path(anker) if anker and anker[:2].upper() != _systemlaufwerk().upper() else None
    volumes = Path(volumes)
    if volumes in pfad.parents:
        return volumes / pfad.relative_to(volumes).parts[0]
    return None


def vermuteter_mountpunkt(name, volumes=VOLUMES):
    """Wo ein Datenträger dieses Namens eingehängt wäre (macOS: /Volumes/<Name>; Windows: Laufwerk mit dieser
    Bezeichnung). Nicht angeschlossen: ein Pfad, den es nicht gibt."""
    if standard_volumes(volumes) and windows():
        for wurzel in datentraeger_liste(volumes):
            if datentraeger_info(wurzel).get("VolumeName") == name:
                return wurzel
    if standard_volumes(volumes) and linux():
        for wurzel in datentraeger_liste(volumes):
            if wurzel.name == name:
                return wurzel
        return Path("/media") / os.environ.get("USER", "benutzer") / name
    return Path(volumes) / name


def rechnername():
    """Wie das interne Laufwerk in Meldungen heißt."""
    return "dem Mac" if mac() else "diesem Rechner"


def datentraeger_info(pfad):
    """Angaben zu einem Datenträger mit den Schlüsseln von `diskutil info -plist` (VolumeName, VolumeUUID,
    DeviceIdentifier, MediaName, BusProtocol, FilesystemName, TotalSize, FreeSpace, RemovableMedia, OpticalMediaType,
    MountPoint). Leer, wenn es keine Angaben gibt (z. B. ein gewöhnlicher Ordner wie testplatten/HD01).
    Windows und Linux: die Seriennummer des Volumes steht als VolumeUUID (sie liegt auf dem Datenträger selbst und ist
    damit auf jedem Rechner gleich). Bei FAT/exFAT rechnet Balduin sie in die UUID um, die macOS zeigt (VolumeUUID,
    die Seriennummer bleibt als VolumeUUIDAlt), damit ein auf dem Mac registrierter Stick wiedererkannt wird
    (13.11.2026); NTFS u. a. bleiben bei der Seriennummer."""
    if windows():
        if not _ist_laufwerkswurzel(pfad):              # wie diskutil: ein Ordner ist kein Datenträger
            return {}
        wurzel = _wurzel(pfad)
        try:
            name, seriennummer, _flags, dateisystem = _win_volume(wurzel)
        except OSError:
            return {}
        typ = _win_laufwerkstyp(wurzel)
        gesamt, _belegt, frei = shutil.disk_usage(wurzel)
        platte = _win_platte_hinter(wurzel)     # Bus, Modell, Wechselmedium (ohne Administratorrechte)
        return {"VolumeName": name, **_fat_kennung(dateisystem, seriennummer),
                "DeviceIdentifier": wurzel[:2].upper(), "MediaName": platte.get("modell") or "",
                "FilesystemName": dateisystem, "TotalSize": gesamt, "FreeSpace": frei, "MountPoint": wurzel,
                "BusProtocol": platte.get("anschluss") or ("USB" if typ == DRIVE_REMOVABLE else ""),
                "RemovableMedia": typ in (DRIVE_REMOVABLE, DRIVE_CDROM) or bool(platte.get("wechselmedium")),
                **({"OpticalMediaType": "CD/DVD"} if typ == DRIVE_CDROM else {})}
    if linux():
        return _linux_info(pfad)
    if not mac():
        return {}
    ergebnis = subprocess.run(["diskutil", "info", "-plist", str(pfad)], capture_output=True)
    if ergebnis.returncode != 0:
        return {}
    return plistlib.loads(ergebnis.stdout)


def ist_schreibgeschuetzt(pfad):
    """Ist der Datenträger von pfad schreibgeschützt eingehängt? (harte Regel 1)"""
    if windows():
        return bool(_win_volume(_wurzel(pfad))[2] & FILE_READ_ONLY_VOLUME)
    return bool(os.statvfs(pfad).f_flag & os.ST_RDONLY)


def nur_lesend_einhaengen(pfad):
    """Hängt einen Datenträger aus und schreibgeschützt wieder ein. Antwort: (neuer Mountpunkt, Meldungen).
    macOS: diskutil; Linux: udisksctl (ohne Root, Entscheidung 13.11.2026); unter Windows gibt es das ohne
    Administratorrechte nicht."""
    if linux():
        return _linux_nur_lesend_einhaengen(pfad)
    if not mac():
        raise RuntimeError("Auf diesem System kann Balduin einen Datenträger nicht schreibgeschützt einhängen. Bitte "
                           "einen Hardware-Schreibschutz (Writeblocker) oder den Schreibschutzschalter des Datenträgers "
                           "verwenden und ihn danach neu anschließen.")
    geraet = datentraeger_info(pfad)["DeviceIdentifier"]
    meldungen = []
    for befehl in (["diskutil", "unmount", str(pfad)], ["diskutil", "mount", "readOnly", geraet]):
        r = subprocess.run(befehl, capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"{' '.join(befehl[:2])} ist gescheitert: {(r.stderr or r.stdout).strip()}")
        meldungen.append(r.stdout.strip())
    return datentraeger_info(geraet).get("MountPoint"), meldungen


def unsichtbare_mounts():
    """Mountpunkte, die der Finder nicht zeigt (Option nobrowse, z. B. Schnappschüsse von Time Machine); nur macOS."""
    if not mac():
        return set()
    ausgabe = subprocess.run(["mount"], capture_output=True, text=True).stdout
    return {m[1] for m in re.finditer(r"^\S.* on (.+) \(([^)]*)\)$", ausgabe, re.M) if "nobrowse" in m[2]}


def smart_status(geraet):
    """SMART-Gesundheitswert über smartctl (smartmontools). Viele USB-Gehäuse reichen SMART nicht durch."""
    programm = werkzeug_pfad("smartctl")
    if not geraet or not programm:
        return "nicht geprüft (smartctl fehlt)"
    if linux():
        return _linux_smart(programm, geraet)
    treffer = re.match(r"disk\d+", geraet)
    if not treffer:                                    # Windows: Laufwerksbuchstabe; die Zuordnung folgt
        return "nicht geprüft (auf diesem System noch nicht)"
    ergebnis = subprocess.run([programm, "-H", "/dev/" + treffer.group(0)], capture_output=True, text=True,
                              **prozess_optionen())
    for zeile in ergebnis.stdout.splitlines():
        if "overall-health" in zeile or "Health Status" in zeile:
            return zeile.split(":", 1)[1].strip()
    return "nicht lesbar (USB-Gehäuse ohne SMART?)"


# ---------- Linux: Datenträger über lsblk und udisks2 (Entscheidung 13.11.2026) ----------
LSBLK_SPALTEN = "NAME,UUID,LABEL,FSTYPE,SIZE,RM,TRAN,TYPE,MODEL,SERIAL,RO,MOUNTPOINT,PTTYPE,PTUUID"
# Anzeige wie auf dem Mac (diskutil nennt das Dateisystem ausgeschrieben)
LINUX_DATEISYSTEME = {"hfsplus": "HFS+", "hfs": "HFS", "apfs": "APFS", "vfat": "FAT32", "exfat": "ExFAT",
                      "ntfs": "NTFS", "ntfs3": "NTFS", "iso9660": "ISO 9660", "udf": "UDF"}
LINUX_ANSCHLUSS = {"usb": "USB", "sata": "SATA", "ata": "ATA", "nvme": "NVMe", "mmc": "Secure Digital", "sas": "SAS",
                   "scsi": "SCSI", "ieee1394": "FireWire"}
# Einhängen ohne nachgespieltes Journal: ext3/ext4/XFS/Btrfs schreiben sonst beim Einhängen, auch mit ro
NUR_LESEND_ZUSATZ = {"ext3": "noload", "ext4": "noload", "xfs": "norecovery", "btrfs": "nologreplay"}
LINUX_GERAET = re.compile(r"/dev/(sd[a-z]{1,3}|nvme\d+n\d+|mmcblk\d+|vd[a-z]{1,3}|hd[a-z])")


def _wahr(wert):
    """lsblk ab 2.33 liefert true/false, ältere „1“/„0“."""
    return wert in (True, 1, "1", "true")


def _linux_geraete():
    """Alle Geräte aus lsblk als flache Liste; jedes mit „disk“ = die Platte, zu der es gehört (sie selbst für Platten)."""
    r = subprocess.run([werkzeug("lsblk"), "-J", "-b", "-o", LSBLK_SPALTEN], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return []
    liste = []

    def aufnehmen(geraet, platte):
        geraet = {**geraet, "size": int(geraet.get("size") or 0), "rm": _wahr(geraet.get("rm")),
                  "ro": _wahr(geraet.get("ro"))}
        kinder = geraet.pop("children", []) or []
        geraet["disk"] = platte or geraet
        liste.append(geraet)
        for kind in kinder:
            aufnehmen(kind, geraet["disk"])
    for geraet in json.loads(r.stdout or "{}").get("blockdevices", []):
        aufnehmen(geraet, None)
    return liste


def _unter_linux_mounts(pfad):
    text = str(pfad)
    return any(text.startswith(wurzel + "/") for wurzel in LINUX_MOUNTS)


def _linux_mountpunkt(pfad):
    """Ist pfad selbst der Mountpunkt eines Datenträgers (unter /media, /run/media oder /mnt)?"""
    return _unter_linux_mounts(pfad) and os.path.ismount(pfad)


def _linux_systemplatten(geraete):
    """Namen der Platten, auf denen etwas außerhalb der Datenträger-Orte eingehängt ist (/, /boot, /home …)."""
    return {g["disk"]["name"] for g in geraete if g.get("mountpoint") and not _unter_linux_mounts(g["mountpoint"])}


def _linux_datentraeger_liste():
    geraete = _linux_geraete()
    system_platten = _linux_systemplatten(geraete)
    return sorted(Path(g["mountpoint"]) for g in geraete
                  if g.get("mountpoint") and _unter_linux_mounts(g["mountpoint"])
                  and g["disk"]["name"] not in system_platten and os.path.isdir(g["mountpoint"]))


def _linux_info(pfad):
    if not _linux_mountpunkt(Path(pfad)):
        return {}
    g = next((g for g in _linux_geraete() if g.get("mountpoint") == str(Path(pfad))), None)
    if g is None:
        return {}
    platte = g["disk"]
    dateisystem = (g.get("fstype") or "").lower()
    uuid = (g.get("uuid") or "").upper()
    alt = {}
    if dateisystem == "hfsplus" and re.fullmatch(r"[0-9A-F]{16}", uuid):
        from .macplatte import hfs_uuid          # gleiche Kennung wie macOS (UUID v3 aus der Volume-ID)
        uuid = hfs_uuid(bytes.fromhex(uuid))
    elif re.fullmatch(r"[0-9A-F]{4}-[0-9A-F]{4}", uuid):
        alt = _fat_kennung(dateisystem, int(uuid.replace("-", ""), 16))
        uuid = alt.pop("VolumeUUID")
    if g.get("type") == "loop":
        anschluss = "Disk Image"
    elif platte["name"].startswith("mmcblk"):
        anschluss = "Secure Digital"
    else:
        tran = (platte.get("tran") or "").lower()
        anschluss = LINUX_ANSCHLUSS.get(tran, tran.upper())
    gesamt, _belegt, frei = shutil.disk_usage(pfad)
    return {"VolumeName": g.get("label") or Path(pfad).name, "VolumeUUID": uuid, **alt, "DeviceIdentifier": g["name"],
            "DevicePath": "/dev/" + g["name"], "MediaName": platte.get("model") or "", "BusProtocol": anschluss,
            "FilesystemName": LINUX_DATEISYSTEME.get(dateisystem, g.get("fstype") or ""),
            "FilesystemType": dateisystem, "TotalSize": gesamt, "FreeSpace": frei, "MountPoint": str(Path(pfad)),
            "RemovableMedia": platte["rm"], "Writable": not g["ro"],
            **({"OpticalMediaType": "CD/DVD"} if g.get("type") == "rom" else {})}


FAT_DATEISYSTEME = {"fat", "fat12", "fat16", "fat32", "exfat", "vfat", "msdos"}


def _fat_kennung(dateisystem, seriennummer):
    """VolumeUUID (und bei FAT/exFAT die Seriennummer als VolumeUUIDAlt) aus der Seriennummer eines Volumes."""
    serie = f"{seriennummer >> 16:04X}-{seriennummer & 0xFFFF:04X}"
    if (dateisystem or "").lower() in FAT_DATEISYSTEME and seriennummer:
        from .macplatte import fat_uuid
        return {"VolumeUUID": fat_uuid(seriennummer), "VolumeUUIDAlt": serie}
    return {"VolumeUUID": serie}


def kennungen(info):
    """Alle Kennungen eines Datenträgers aus datentraeger_info(): die übliche und eine frühere Form (FAT/exFAT unter
    Windows und Linux bis 13.11.2026: „XXXX-XXXX“). Vergleiche mit registrierten Platten nutzen alle."""
    return [k for k in (info.get("VolumeUUID") or info.get("DiskUUID"), info.get("VolumeUUIDAlt")) if k]


def nur_lesend_optionen(dateisystem):
    """Optionen fürs schreibgeschützte Einhängen unter Linux (harte Regel 1)."""
    zusatz = NUR_LESEND_ZUSATZ.get((dateisystem or "").lower())
    return "ro," + zusatz if zusatz else "ro"


def _linux_nur_lesend_einhaengen(pfad):
    info = datentraeger_info(pfad)
    if not info.get("DevicePath"):
        raise RuntimeError(f"Zu {pfad} gibt es keine Angaben zum Datenträger; er lässt sich nicht neu einhängen.")
    udisks = werkzeug_pfad("udisksctl")
    if not udisks:
        raise RuntimeError("Schreibgeschützt einhängen braucht udisksctl. " + installationshinweis("udisksctl"))
    geraet, optionen = info["DevicePath"], nur_lesend_optionen(info.get("FilesystemType"))
    meldungen = []
    for befehl in ([udisks, "unmount", "-b", geraet], [udisks, "mount", "-b", geraet, "-o", optionen]):
        r = subprocess.run(befehl, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            nachher = " Der Datenträger ist jetzt ausgehängt." if befehl[1] == "mount" else ""
            raise RuntimeError(f"udisksctl {befehl[1]} ist gescheitert: {(r.stderr or r.stdout).strip()}.{nachher}")
        meldungen.append(r.stdout.strip())
    treffer = re.search(r" at (.+?)\.?$", meldungen[-1], re.M)
    mountpunkt = treffer.group(1) if treffer else None
    if not mountpunkt or not ist_schreibgeschuetzt(mountpunkt):
        raise RuntimeError(f"{geraet} ist nach dem Einhängen nicht schreibgeschützt ({mountpunkt}); bitte auswerfen "
                           "und mit Writeblocker anschließen.")
    return mountpunkt, meldungen


def _linux_smart(programm, geraet):
    """SMART unter Linux: Partition (sdb1, nvme0n1p2, mmcblk0p1) → Platte; meist nur mit Administratorrechten."""
    name = re.sub(r"(?<=\d)p\d+$", "", geraet) if re.match(r"(nvme|mmcblk)", geraet) else re.sub(r"\d+$", "", geraet)
    if not re.fullmatch(r"sd[a-z]{1,3}|nvme\d+n\d+|mmcblk\d+|vd[a-z]{1,3}|hd[a-z]", name):
        return "nicht geprüft (Gerät unbekannt)"
    ergebnis = subprocess.run([programm, "-H", "/dev/" + name], capture_output=True, text=True, timeout=60)
    ausgabe = ergebnis.stdout + ergebnis.stderr
    for zeile in ausgabe.splitlines():
        if "overall-health" in zeile or "Health Status" in zeile:
            return zeile.split(":", 1)[1].strip()
    if "Permission denied" in ausgabe or "Operation not permitted" in ausgabe:
        return "nicht geprüft (braucht Administratorrechte)"
    return "nicht lesbar (USB-Gehäuse ohne SMART?)"


def _linux_physische_datentraeger():
    """Platten außer der Systemplatte, CD-Laufwerken und Abbildern; laufwerksbuchstaben = etwas darauf ist eingehängt
    (gleicher Schlüssel wie unter Windows: dann ist es kein Fall für „Mac-Datenträger lesen“)."""
    geraete = _linux_geraete()
    system_platten = _linux_systemplatten(geraete)
    liste = []
    for nr, platte in enumerate(g for g in geraete if g.get("type") == "disk"):
        if platte["name"] in system_platten or not LINUX_GERAET.fullmatch("/dev/" + platte["name"]):
            continue
        eingehaengt = any(g.get("mountpoint") for g in geraete if g["disk"] is platte)
        tran = (platte.get("tran") or "").lower()
        liste.append({"geraet": "/dev/" + platte["name"], "nummer": nr, "modell": platte.get("model") or "",
                      "seriennummer": platte.get("serial") or "", "tabelle": _linux_tabelle(platte),
                      "anschluss": LINUX_ANSCHLUSS.get(tran, tran.upper()),
                      "wechselmedium": platte["rm"], "groesse": platte["size"], "laufwerksbuchstaben": eingehaengt})
    return liste


def _linux_tabelle(platte):
    """Kennung der Partitionstabelle wie unter Windows (tabelle_kennung): aus PTTYPE und PTUUID von lsblk."""
    art, kennung = (platte.get("pttype") or "").lower(), (platte.get("ptuuid") or "").upper()
    if art == "gpt" and kennung:
        return f"GPT:{kennung}"
    if art == "dos" and kennung and int(kennung, 16):
        return f"MBR:{kennung}"
    return ""


def _linux_tueroeffner(geraet):
    """Startet erfassung/tueroeffner_linux.py über pkexec (fragt nach dem Administratorpasswort) und empfängt den nur
    lesenden Zugriff auf die Platte über einen Unix-Socket in einem eigenen Ordner (nur für diesen Benutzer und root).
    Antwort: Dateideskriptor; RuntimeError, wenn abgelehnt oder ohne Antwort."""
    import tempfile
    pkexec = werkzeug_pfad("pkexec")
    if not pkexec:
        raise RuntimeError("Diesen Datenträger darf nur ein Administrator lesen, und pkexec fehlt. Alternativ ein "
                           "Abbild des Datenträgers einlesen.")
    skript = Path(__file__).resolve().parent / "tueroeffner_linux.py"
    # kurzer Pfad: Sockets erlauben nur rund 100 Zeichen; der Ordner ist nur für diesen Benutzer (und root) offen
    with tempfile.TemporaryDirectory(prefix="balduin-tuer-", dir="/tmp" if os.path.isdir("/tmp") else None) as ordner:
        adresse = os.path.join(ordner, "s")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as hoerer:
            hoerer.bind(adresse)
            hoerer.listen(1)
            hoerer.settimeout(0.5)
            prozess = subprocess.Popen([pkexec, sys.executable, "-I", str(skript), geraet, adresse],
                                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            frist = time.monotonic() + 180
            while True:
                try:
                    verbindung, _ = hoerer.accept()
                    break
                except socket.timeout:
                    if prozess.poll() is not None:
                        fehler = (prozess.stderr.read() or b"").decode(errors="replace").strip()
                        raise RuntimeError("Die Rückfrage nach dem Administratorpasswort wurde abgelehnt; ohne sie "
                                           "liest Linux den Datenträger nicht. Alternativ ein Abbild einlesen."
                                           + (f" ({fehler})" if fehler else "")) from None
                    if time.monotonic() > frist:
                        prozess.kill()
                        raise RuntimeError("Der Türöffner hat nicht geantwortet.") from None
            with verbindung:
                nachricht, fds, _flags, _adresse = socket.recv_fds(verbindung, 4096, 1)
            prozess.wait(timeout=30)
    if not fds:
        raise RuntimeError(nachricht.decode(errors="replace") or "Der Türöffner hat keinen Zugriff geliefert.")
    return fds[0]


def _wurzel(pfad):
    """Windows: Wurzel des Laufwerks („E:\\“)."""
    return os.path.splitdrive(os.path.abspath(str(pfad)))[0] + "\\"


def _ist_laufwerkswurzel(pfad):
    """Windows: Ist pfad die Wurzel eines Laufwerks (E:, E:\\ oder E:/) und kein Ordner darauf?"""
    import ntpath
    laufwerk, rest = ntpath.splitdrive(str(pfad))
    return bool(laufwerk) and rest.strip("\\/") == ""


def _systemlaufwerk():
    return os.environ.get("SystemDrive", "C:")


def _win_laufwerke():
    import ctypes
    puffer = ctypes.create_unicode_buffer(512)
    n = ctypes.windll.kernel32.GetLogicalDriveStringsW(len(puffer), puffer)
    return [w for w in puffer[:n].split("\0") if w]


def _win_laufwerkstyp(wurzel):
    import ctypes
    return ctypes.windll.kernel32.GetDriveTypeW(str(wurzel))


def _win_volume(wurzel):
    """(Bezeichnung, Seriennummer, Kennzeichen, Dateisystem) eines Laufwerks; OSError, wenn keins eingelegt ist."""
    import ctypes
    name, dateisystem = ctypes.create_unicode_buffer(261), ctypes.create_unicode_buffer(261)
    seriennummer, laenge, flags = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_ulong()
    if not ctypes.windll.kernel32.GetVolumeInformationW(str(wurzel), name, 261, ctypes.byref(seriennummer),
                                                        ctypes.byref(laenge), ctypes.byref(flags), dateisystem, 261):
        raise OSError(f"keine Angaben zu {wurzel}")
    return name.value, seriennummer.value, flags.value, dateisystem.value


# ---------- Physische Platten ohne Laufwerksbuchstaben (Mac-Platten unter Windows, Entscheidung 09.11.2026) ----------
# Windows hängt HFS+ und APFS nicht ein; erfassung/macplatte.py liest sie von der physischen Platte. Auflisten geht ohne
# Administratorrechte, Lesen nur mit: dafür öffnet erfassung/tueroeffner.py die Platte (Benutzerkontensteuerung) und
# reicht den nur lesenden Zugriff an den Lauf weiter.
GERAET_MUSTER = re.compile(r"\\\\\.\\PhysicalDrive\d{1,3}", re.IGNORECASE)
IOCTL_STORAGE_QUERY_PROPERTY, IOCTL_DISK_GET_DRIVE_GEOMETRY_EX = 0x002D1400, 0x000700A0
IOCTL_STORAGE_GET_DEVICE_NUMBER = 0x002D1080
IOCTL_DISK_GET_DRIVE_LAYOUT_EX = 0x00070050      # Partitionstabelle; geht mit Zugriff 0
FILE_DEVICE_DISK = 7                     # Gerätetyp in STORAGE_DEVICE_NUMBER (2 wäre ein CD-Laufwerk)
BUS = {1: "SCSI", 3: "ATA", 7: "USB", 8: "RAID", 10: "SAS", 11: "SATA", 12: "SD", 13: "MMC", 17: "NVMe"}
SEKTOR_GERAET = 4096                   # Lesen in ganzen 4-KB-Blöcken passt auch zu Platten mit 512-Byte-Sektoren


def geraet_name(pfad):
    """Feste Schreibweise \\\\.\\PhysicalDriveN eines Gerätepfads (pathlib hängt unter Windows einen Trenner an,
    „/“ statt „\\“ ist auch erlaubt); None, wenn pfad keine physische Platte ist."""
    if linux():
        text = str(pfad)
        return text if LINUX_GERAET.fullmatch(text) else None
    text = str(pfad).replace("/", "\\").rstrip("\\")
    if not GERAET_MUSTER.fullmatch(text):
        return None
    return "\\\\.\\PhysicalDrive" + re.search(r"(\d+)$", text).group(1)


def ist_geraet(pfad):
    """Ist pfad eine physische Platte (Windows: \\\\.\\PhysicalDriveN)?"""
    return (windows() or linux()) and geraet_name(pfad) is not None


def physische_datentraeger():
    """Physische Platten außer der Systemplatte: [{geraet, nummer, modell, seriennummer, anschluss, wechselmedium,
    groesse, laufwerksbuchstaben}] (laufwerksbuchstaben False: Windows kennt das Dateisystem nicht, z. B. HFS+/APFS).
    Ohne Administratorrechte; Windows und Linux (auf dem Mac hängt macOS die Platten selbst ein)."""
    if linux():
        return _linux_physische_datentraeger()
    if not windows():
        return []
    belegt = set()
    for w in _win_laufwerke():
        try:
            belegt.add(_win_geraetenummer("\\\\.\\" + w[:2]))
        except OSError:
            pass
    try:
        system_nr = _win_geraetenummer("\\\\.\\" + _systemlaufwerk())
    except OSError:
        system_nr = None
    liste = []
    for nr in range(32):
        geraet = f"\\\\.\\PhysicalDrive{nr}"
        try:
            angaben = _win_geraet_angaben(geraet)
        except OSError:
            continue
        if nr == system_nr:
            continue
        liste.append({"geraet": geraet, "nummer": nr, **angaben, "laufwerksbuchstaben": nr in belegt})
    return liste


def tabelle_kennung(layout):
    """Kennung der Partitionstabelle aus DRIVE_LAYOUT_INFORMATION_EX: „GPT:<Disk-GUID>“ oder „MBR:<Signatur>“, sonst
    „“. Sie liegt auf der Platte, bleibt beim Umstecken gleich und ist ohne Administratorrechte lesbar; daran erkennt
    Balduin Mac-Platten wieder, auch wenn das Gehäuse keine Seriennummer meldet (UTM-Test 13.11.2026)."""
    import uuid as uuid_modul
    if len(layout) < 12:
        return ""
    stil = int.from_bytes(layout[0:4], "little")
    if stil == 1 and len(layout) >= 24:
        kennung = uuid_modul.UUID(bytes_le=bytes(layout[8:24]))
        return f"GPT:{str(kennung).upper()}" if kennung.int else ""
    if stil == 0:
        signatur = int.from_bytes(layout[8:12], "little")
        return f"MBR:{signatur:08X}" if signatur else ""
    return ""


def lange_pfade():
    """Lassen sich Pfade über 260 Zeichen lesen? Windows: nur mit LongPathsEnabled (richtet der Installer ein,
    Entscheidung 13.11.2026), gelesen ohne Administratorrechte; Mac und Linux kennen die Grenze nicht → None."""
    if not windows():
        return None
    return _win_registry_dword(r"SYSTEM\CurrentControlSet\Control\FileSystem", "LongPathsEnabled") == 1


def _win_registry_dword(schluessel, name):
    """Wert aus HKEY_LOCAL_MACHINE (nur lesen) oder None."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, schluessel) as k:
            return winreg.QueryValueEx(k, name)[0]
    except OSError:
        return None


def ist_admin():
    """Läuft dieser Prozess mit Administratorrechten?"""
    if windows():
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    return hasattr(os, "geteuid") and os.geteuid() == 0


def geraet_oeffnen(geraet):
    """Physische Platte nur lesend öffnen. Antwort: (Dateiobjekt, Größe in Bytes, Sektorgröße für das Lesen).
    Ohne Administratorrechte fragt Windows einmal nach (Türöffner); ValueError für alles außer \\\\.\\PhysicalDriveN."""
    if linux():
        if geraet_name(geraet) is None:
            raise ValueError(f"Nur ganze Datenträger (/dev/sdX, /dev/nvmeNnM, /dev/mmcblkN), nicht {geraet!r}.")
        geraet = geraet_name(geraet)
        fd = os.open(geraet, os.O_RDONLY) if os.access(geraet, os.R_OK) else _linux_tueroeffner(geraet)
        f = os.fdopen(fd, "rb", buffering=0)
        groesse = f.seek(0, os.SEEK_END)
        f.seek(0)
        return f, groesse, 1
    if geraet_name(geraet) is None or "\\.." in str(geraet):
        raise ValueError(f"Nur physische Datenträger (\\\\.\\PhysicalDriveN), nicht {geraet!r}.")
    geraet = geraet_name(geraet)
    if not windows():
        raise RuntimeError("Physische Platten liest Balduin nur unter Windows direkt; macOS hängt sie selbst ein.")
    griff = _win_geraet_griff(geraet) if ist_admin() else _win_tueroeffner(geraet)
    return _griff_als_datei(griff), int(_win_geraet_angaben(geraet)["groesse"]), SEKTOR_GERAET


def _griff_als_datei(griff):
    import msvcrt
    fd = msvcrt.open_osfhandle(griff, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    return os.fdopen(fd, "rb", buffering=0)


def _win_kernel32():
    import ctypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateFileW.restype = ctypes.c_void_p
    return ctypes, k


def _win_geraet_griff(geraet, zugriff=0x80000000):
    """CreateFileW: zugriff 0 = nur Angaben abfragen (ohne Administratorrechte), GENERIC_READ = lesen."""
    ctypes, k = _win_kernel32()
    griff = k.CreateFileW(str(geraet), zugriff, 0x3, None, 3, 0, None)
    if griff in (None, ctypes.c_void_p(-1).value):
        raise OSError(f"{geraet} lässt sich nicht öffnen (Fehler {ctypes.get_last_error()})")
    return griff


def _win_ioctl(griff, code, eingabe=b"", laenge=1024):
    ctypes, k = _win_kernel32()
    aus = ctypes.create_string_buffer(laenge)
    zurueck = ctypes.c_ulong()
    ein = ctypes.create_string_buffer(eingabe, len(eingabe)) if eingabe else None
    if not k.DeviceIoControl(ctypes.c_void_p(griff), code, ein, len(eingabe), aus, laenge, ctypes.byref(zurueck), None):
        raise OSError(f"DeviceIoControl {code:#x} (Fehler {ctypes.get_last_error()})")
    return aus.raw[:zurueck.value]


def _win_schliessen(griff):
    _ctypes, k = _win_kernel32()
    k.CloseHandle(_ctypes.c_void_p(griff))


def _win_geraetenummer(pfad):
    """Nummer der physischen Platte zu \\\\.\\E: (oder einer Platte selbst). OSError, wenn das Gerät keine Platte ist:
    CD-Laufwerke (CdRomN) zählen eigene Nummern, die sonst mit PhysicalDriveN verwechselt würden."""
    griff = _win_geraet_griff(pfad, 0)
    try:
        d = _win_ioctl(griff, IOCTL_STORAGE_GET_DEVICE_NUMBER, laenge=12)
    finally:
        _win_schliessen(griff)
    if int.from_bytes(d[0:4], "little") != FILE_DEVICE_DISK:
        raise OSError(f"{pfad} ist kein Datenträger mit Dateisystem (z. B. eine CD)")
    return int.from_bytes(d[4:8], "little")


def _win_platte_hinter(wurzel):
    """Angaben der physischen Platte hinter einem Laufwerksbuchstaben; {} bei CD-, Netz- und virtuellen Laufwerken."""
    try:
        return _win_geraet_angaben("\\\\.\\PhysicalDrive" + str(_win_geraetenummer("\\\\.\\" + str(wurzel)[:2])))
    except OSError:
        return {}


def _win_geraet_angaben(geraet):
    """Modell, Seriennummer, Anschluss, Wechselmedium und Größe einer physischen Platte (ohne Administratorrechte)."""
    griff = _win_geraet_griff(geraet, 0)
    try:
        d = _win_ioctl(griff, IOCTL_STORAGE_QUERY_PROPERTY, bytes(12))
        text = lambda stelle: (d[stelle:d.index(b"\0", stelle)].decode("ascii", "replace").strip() if stelle else "")  # noqa: E731
        zahl = lambda a: int.from_bytes(d[a:a + 4], "little")                                                          # noqa: E731
        geometrie = _win_ioctl(griff, IOCTL_DISK_GET_DRIVE_GEOMETRY_EX, laenge=256)
        try:
            tabelle = tabelle_kennung(_win_ioctl(griff, IOCTL_DISK_GET_DRIVE_LAYOUT_EX, laenge=4096))
        except OSError:
            tabelle = ""
        return {"modell": " ".join(x for x in (text(zahl(12)), text(zahl(16))) if x), "seriennummer": text(zahl(24)),
                "tabelle": tabelle,
                "anschluss": BUS.get(zahl(28), ""), "wechselmedium": bool(d[10]),
                "groesse": int.from_bytes(geometrie[24:32], "little")}
    finally:
        _win_schliessen(griff)


def _win_tueroeffner(geraet):
    """Startet erfassung/tueroeffner.py mit Administratorrechten (Benutzerkontensteuerung) und empfängt den nur
    lesenden Zugriff auf die Platte, gültig in diesem Prozess. RuntimeError, wenn abgelehnt oder ohne Antwort."""
    import ctypes
    import secrets
    import threading
    from ctypes import wintypes
    from multiprocessing.connection import Listener

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", wintypes.HWND),
                    ("lpVerb", wintypes.LPCWSTR), ("lpFile", wintypes.LPCWSTR), ("lpParameters", wintypes.LPCWSTR),
                    ("lpDirectory", wintypes.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", wintypes.HINSTANCE),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wintypes.LPCWSTR), ("hkeyClass", wintypes.HKEY),
                    ("dwHotKey", wintypes.DWORD), ("hIcon", wintypes.HANDLE), ("hProcess", wintypes.HANDLE)]

    schluessel = secrets.token_bytes(16)
    with Listener(("127.0.0.1", 0), authkey=schluessel) as hoerer:
        skript = Path(__file__).resolve().parent / "tueroeffner.py"
        parameter = f'"{skript}" "{geraet}" {os.getpid()} 127.0.0.1:{hoerer.address[1]} {schluessel.hex()}'
        info = SHELLEXECUTEINFOW(cbSize=ctypes.sizeof(SHELLEXECUTEINFOW), fMask=0x40, lpVerb="runas",
                                 lpFile=sys.executable, lpParameters=parameter, nShow=0)
        if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
            if ctypes.GetLastError() == 1223:
                raise RuntimeError("Die Rückfrage nach Administratorrechten wurde abgelehnt; ohne sie liest Windows "
                                   "den Datenträger nicht. Alternativ ein Abbild des Datenträgers einlesen.")
            raise RuntimeError(f"Der Türöffner startet nicht (Fehler {ctypes.GetLastError()}).")
        wecker = threading.Timer(180, hoerer.close)      # ohne Antwort nach 3 Minuten aufgeben
        wecker.start()
        try:
            with hoerer.accept() as verbindung:
                antwort = verbindung.recv()
        except OSError:
            raise RuntimeError("Der Türöffner hat nicht geantwortet.") from None
        finally:
            wecker.cancel()
    if "fehler" in antwort:
        raise RuntimeError(antwort["fehler"])
    return antwort["griff"]


# ---------- Art des Datenträgers (Entscheidung 05.11.2026) ----------
# Schlüssel: cd, karte, usb, image, festplatte, ordner; "" = unbestimmt. Das Tool zeigt daraus ein Icon.
OPTISCHE_DATEISYSTEME = {"cd9660", "udf", "cddafs", "iso 9660", "cd-rom", "audio-cd"}


def traegerart(info):
    """Art eines Datenträgers aus den Angaben von datentraeger_info() (Schlüssel wie diskutil; Windows: aus dem
    Laufwerkstyp). Unterscheidung USB-Stick/USB-Platte nur am Merkmal Wechselmedium, das manche Geräte falsch
    melden: eine Sehhilfe, kein Befund."""
    if not info:
        return ""
    anschluss = (info.get("BusProtocol") or "").lower()
    dateisystem = (info.get("FilesystemType") or info.get("FilesystemName") or "").lower()
    if info.get("OpticalMediaType") or info.get("OpticalDeviceType") or dateisystem in OPTISCHE_DATEISYSTEME:
        return "cd"
    if anschluss == "disk image":
        return "image"
    if anschluss in ("secure digital", "sd"):
        return "karte"
    if anschluss == "usb" and (info.get("RemovableMedia") or info.get("Removable")):
        return "usb"
    return "festplatte"


def traeger_der_platte(zeile):
    """Art einer registrierten Platte (Zeile der Tabelle platte): der gespeicherte Wert, sonst geschätzt aus Anschluss
    und Dateisystem (Platten, die vor dem 05.11.2026 registriert wurden)."""
    if zeile.get("traeger"):
        return zeile["traeger"]
    if zeile.get("art") == "ordner":
        return "ordner"
    anschluss = (zeile.get("anschluss") or "").lower()
    if (zeile.get("dateisystem") or "").lower() in OPTISCHE_DATEISYSTEME | {"udf"}:
        return "cd"
    return {"disk image": "image", "secure digital": "karte"}.get(anschluss, "")


# ---------- Werkzeuge (Siegfried, ExifTool, ffmpeg, Poppler, ClamAV, smartctl) ----------
# Gesucht wird zuerst, was das Paket von Balduin mitbringt (BALDUIN_WERKZEUGE, mehrere Ordner mit os.pathsep, oder
# bin/ neben dem Code), dann im Suchpfad, zuletzt in Ordnern, die oft nicht im Suchpfad stehen (Homebrew sbin).
def zusatz_ordner():
    """Ordner, in denen Werkzeuge oft liegen, ohne im Suchpfad zu stehen."""
    if windows():
        return [os.path.join(os.environ.get(v, ""), *teile) for v, teile in
                (("ProgramFiles", ("ClamAV",)), ("ProgramFiles", ("smartmontools", "bin")),
                 ("ProgramFiles", ("ExifTool",)), ("ProgramFiles", ("siegfried",)),
                 ("ProgramFiles", ("LibreOffice", "program")), ("ProgramFiles", ("Git", "cmd")))
                if os.environ.get(v)]
    if linux():                     # Debian/Ubuntu: clamd und smartctl in /usr/sbin, Snap-Pakete in /snap/bin
        return ["/usr/local/bin", "/usr/local/sbin", "/usr/sbin", "/sbin", "/snap/bin"]
    return ["/opt/homebrew/bin", "/opt/homebrew/sbin", "/usr/local/bin", "/usr/local/sbin",
            "/Applications/LibreOffice.app/Contents/MacOS"]                     # LibreOffice nur, wenn installiert


ZUSATZ_ORDNER = zusatz_ordner()


def werkzeug_pfad(name):
    """Pfad zu einem externen Programm oder None, wenn es fehlt."""
    eigene = [o for o in os.environ.get("BALDUIN_WERKZEUGE", "").split(os.pathsep) if o] + [str(CODE / "bin")]
    if (CODE / "bin").is_dir():               # Paket: Werkzeuge mit eigenen Bibliotheken in Unterordnern (bin/clamav/)
        eigene += sorted(str(o) for o in (CODE / "bin").iterdir() if o.is_dir())
    for ordner in eigene:
        if (pfad := shutil.which(name, path=ordner)):
            return pfad
    if (pfad := shutil.which(name)):
        return pfad
    for ordner in ZUSATZ_ORDNER:
        if (pfad := shutil.which(name, path=ordner)):
            return pfad
    return None


def im_paket():
    """Läuft Balduin aus dem Paket (Mac-App, Windows-Installer, Linux-Archiv) mit eigenem Python in python/?"""
    return (CODE / "python").is_dir()


def projekte_vorgabe():
    """Vorgabe-Speicherort neuer Projekte: im Git Projekte/ neben dem Code (Entscheidung 30.10.2026); im Paket wäre
    das im Programm selbst, dort also Dokumente/Balduin-Projekte (ohne Dokumente-Ordner im persönlichen Ordner)."""
    if not im_paket():
        return CODE.parent / "Projekte"
    dokumente = Path.home() / "Documents"
    return (dokumente if dokumente.is_dir() else Path.home()) / "Balduin-Projekte"


def paket_umgebung():
    """Umgebungsvariablen für die Werkzeuge im Paket (Entscheidung 14.11.2026): Siegfried findet seine Signaturdatei
    in bin/siegfried/, ClamAV das Zertifikat der Signaturen in bin/clamav/certs/. Ohne Paket leer."""
    umgebung = {}
    if (CODE / "bin" / "siegfried").is_dir():
        umgebung["SIEGFRIED_HOME"] = str(CODE / "bin" / "siegfried")
    if (CODE / "bin" / "clamav" / "certs").is_dir():
        umgebung["CVD_CERTS_DIR"] = str(CODE / "bin" / "clamav" / "certs")
    return umgebung


def werkzeug(name):
    """Programm zum Aufrufen: der gefundene Pfad oder der Name (dann meldet subprocess, dass es fehlt)."""
    return werkzeug_pfad(name) or name


# Linux: Ordner der Signaturen, den der Dienst clamav-freshclam der Distribution pflegt
CLAMAV_SIGNATUREN = Path("/var/lib/clamav")


def clamav_konfiguration(freshclam):
    """(freshclam.conf, Vorlage) zum Programm freshclam: Homebrew …/etc/clamav/, Windows neben dem Programm,
    Linux die Einstellung der Distribution (/etc/clamav/, schon eingerichtet)."""
    programm = Path(freshclam)
    if windows():
        return programm.parent / "freshclam.conf", programm.parent / "conf_examples" / "freshclam.conf.sample"
    if linux():
        return Path("/etc/clamav/freshclam.conf"), Path("/etc/clamav/freshclam.conf")
    ordner = programm.parent.parent / "etc" / "clamav"
    return ordner / "freshclam.conf", ordner / "freshclam.conf.sample"


def signaturen_selbst_auffrischen():
    """Darf Balduin die Virensignaturen selbst holen (freshclam)? Unter Linux gehört der Ordner der Signaturen dem
    Dienst clamav-freshclam; ohne Schreibrecht dort scheiterte freshclam nur."""
    if not linux():
        return True
    return CLAMAV_SIGNATUREN.is_dir() and os.access(CLAMAV_SIGNATUREN, os.W_OK)


def dienst_adresse(ordner):
    """Wie ein lokaler Dienst (clamd) erreichbar ist: Unix-Socket im Ordner oder, wo es den nicht gibt (Windows),
    TCP nur auf 127.0.0.1 mit einem freien Port. Antwort: {"konf" (Zeilen für die Einstellung), "familie", "adresse"}."""
    if windows() or not hasattr(socket, "AF_UNIX"):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        return {"konf": f"TCPSocket {port}\nTCPAddr 127.0.0.1\n", "familie": socket.AF_INET, "adresse": ("127.0.0.1", port)}
    pfad = os.path.join(str(ordner), "clamd.sock")
    return {"konf": f"LocalSocket {pfad}\n", "familie": socket.AF_UNIX, "adresse": pfad}


def verknuepfen(quelle, ziel):
    """Verweist von ziel auf quelle (symbolische Verknüpfung). Unter Windows brauchen Verknüpfungen Administratorrechte;
    dann eine Kopie (gelesen wird nur)."""
    quelle, ziel = Path(quelle), Path(ziel)
    try:
        ziel.symlink_to(quelle, target_is_directory=quelle.is_dir())
    except OSError:
        if not windows():
            raise
        if quelle.is_dir():
            shutil.copytree(quelle, ziel)
        else:
            shutil.copy2(quelle, ziel)


# ---------- Schlüsselbund (Anton-Token) ----------
# macOS: Schlüsselbund über `security`; Tests nennen in ANTON_SCHLUESSELBUND einen eigenen Schlüsselbund.
# Windows: Anmeldeinformationsverwaltung (Generic Credential mit dem Dienst als Zielname). Der Wert wird nie ausgegeben.

def _security(*befehl, eingabe=None):
    eigener = os.environ.get("ANTON_SCHLUESSELBUND", "")
    return subprocess.run(["security", *befehl, *([eigener] if eigener and eingabe is None else [])],
                          input=eingabe, capture_output=True, text=True, timeout=30)


def geheimnis_lesen(dienst):
    """Gespeicherter Wert oder „“."""
    if windows():
        return _win_cred_lesen(dienst) or ""
    if linux():
        return _linux_geheimnis("lesen", dienst) or ""
    if not mac():
        return ""
    return _security("find-generic-password", "-s", dienst, "-w").stdout.strip()


def geheimnis_vorhanden(dienst):
    """Gibt es einen Eintrag? (ohne den Wert zu lesen)"""
    if windows():
        return _win_cred_lesen(dienst) is not None
    if linux():
        return _linux_geheimnis("lesen", dienst) is not None
    return mac() and _security("find-generic-password", "-s", dienst).returncode == 0


def geheimnis_speichern(dienst, konto, wert):
    """Legt den Wert ab (ersetzt einen vorhandenen). macOS: über stdin an security, nicht als Befehlsargument,
    damit er in keiner Prozessliste erscheint. True = abgelegt."""
    if windows():
        return bool(_win_cred_schreiben(dienst, konto, wert))
    if linux():
        return bool(_linux_geheimnis("speichern", dienst, konto, wert))
    if not mac():
        return False
    befehl = f'add-generic-password -U -a "{konto}" -s "{dienst}" -w "{wert}"'
    if (eigener := os.environ.get("ANTON_SCHLUESSELBUND", "")):
        befehl += f' "{eigener}"'
    return _security("-i", eingabe=befehl + "\n").returncode == 0


def geheimnis_entfernen(dienst):
    """True = es gab einen Eintrag und er ist entfernt."""
    if windows():
        return bool(_win_cred_loeschen(dienst))
    if linux():
        return bool(_linux_geheimnis("entfernen", dienst))
    return mac() and _security("delete-generic-password", "-s", dienst).returncode == 0


def _linux_geheimnis(aktion, dienst, konto="", wert=""):
    """Linux: Secret Service (GNOME-Schlüsselbund, KWallet …) über secret-tool (libsecret); der Wert geht nur über
    stdin hinein. Tests nennen in ANTON_SCHLUESSELBUND einen eigenen Speicher: dann eine JSON-Datei daneben (nur für
    den Benutzer lesbar), damit der Passwortspeicher des Rechners unberührt bleibt.
    Antwort: lesen → Wert oder None; speichern/entfernen → True/False."""
    if (eigener := os.environ.get("ANTON_SCHLUESSELBUND", "")):
        datei = Path(eigener + ".json")
        try:
            daten = json.loads(datei.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            daten = {}
        if aktion == "lesen":
            return daten.get(dienst)
        if aktion == "entfernen" and dienst not in daten:
            return False
        if aktion == "speichern":
            daten[dienst] = wert
        else:
            daten.pop(dienst)
        datei.touch(mode=0o600)
        datei.chmod(0o600)
        datei.write_text(json.dumps(daten), encoding="utf-8")
        return True
    programm = werkzeug_pfad("secret-tool")
    if not programm:
        return None if aktion == "lesen" else False
    attribute = ["service", dienst]
    if aktion == "lesen":
        r = subprocess.run([programm, "lookup", *attribute], capture_output=True, text=True, timeout=30)
        return r.stdout if r.returncode == 0 and r.stdout else None
    if aktion == "speichern":
        r = subprocess.run([programm, "store", f"--label={dienst}", *attribute, "account", konto], input=wert,
                           capture_output=True, text=True, timeout=60)
        return r.returncode == 0
    if _linux_geheimnis("lesen", dienst) is None:
        return False
    return subprocess.run([programm, "clear", *attribute], capture_output=True, text=True, timeout=30).returncode == 0


def _win_credential():
    import ctypes
    from ctypes import wintypes

    class CREDENTIAL(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                    ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                    ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                    ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    return ctypes, CREDENTIAL, advapi32


def _win_cred_lesen(dienst):
    ctypes, CREDENTIAL, advapi32 = _win_credential()
    zeiger = ctypes.POINTER(CREDENTIAL)()
    if not advapi32.CredReadW(dienst, 1, 0, ctypes.byref(zeiger)):          # CRED_TYPE_GENERIC
        return None
    try:
        c = zeiger.contents
        return ctypes.string_at(c.CredentialBlob, c.CredentialBlobSize).decode("utf-16-le")
    finally:
        advapi32.CredFree(zeiger)


def _win_cred_schreiben(dienst, konto, wert):
    ctypes, CREDENTIAL, advapi32 = _win_credential()
    daten = wert.encode("utf-16-le")
    puffer = (ctypes.c_ubyte * len(daten)).from_buffer_copy(daten)
    c = CREDENTIAL(Type=1, TargetName=dienst, UserName=konto, CredentialBlobSize=len(daten),
                   CredentialBlob=ctypes.cast(puffer, ctypes.POINTER(ctypes.c_ubyte)), Persist=2)   # LOCAL_MACHINE
    return bool(advapi32.CredWriteW(ctypes.byref(c), 0))


def _win_cred_loeschen(dienst):
    _ctypes, _c, advapi32 = _win_credential()
    return bool(advapi32.CredDeleteW(dienst, 1, 0))


# ---------- Dialog, Dateimanager, Papierkorb, Vorschau ----------

def _applescript_text(text):
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'


def ordner_waehlen(titel, start):
    """Nativer Dialog „Ordner wählen“ (die Webseite selbst kann keinen Pfad abfragen). Antwort: Pfad ohne
    abschließenden Trenner oder None, wenn abgebrochen. macOS: Finder (osascript); Windows: FolderBrowserDialog über
    PowerShell (Titel und Startordner als Umgebungsvariablen, damit keine Anführungszeichen stören)."""
    if windows():
        skript = ("Add-Type -AssemblyName System.Windows.Forms; "
                  "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
                  "$d = New-Object System.Windows.Forms.FolderBrowserDialog; "
                  "$d.Description = $env:BALDUIN_TITEL; $d.SelectedPath = $env:BALDUIN_START; "
                  "$f = New-Object System.Windows.Forms.Form -Property @{TopMost = $true}; "
                  "if ($d.ShowDialog($f) -eq 'OK') { $d.SelectedPath } else { exit 2 }")
        r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", skript], capture_output=True, text=True,
                           encoding="utf-8", timeout=900, env={**os.environ, "BALDUIN_TITEL": str(titel),
                                                               "BALDUIN_START": str(start)}, **prozess_optionen())
        if r.returncode == 2:
            return None
        if r.returncode != 0:
            raise RuntimeError(f"Ordnerdialog: {(r.stderr or r.stdout).strip()}")
        pfad = r.stdout.strip()
        return pfad if pfad.endswith(":\\") else pfad.rstrip("\\")
    if linux():
        pfad = _linux_dialog("ordner", titel, start)
        return None if pfad is None else (pfad.rstrip("/") or "/")
    if not mac():
        raise RuntimeError("Einen Ordnerdialog gibt es auf diesem System noch nicht.")
    r = subprocess.run(["osascript", "-e", "activate", "-e",
                        f"POSIX path of (choose folder with prompt {_applescript_text(titel)} "
                        f"default location (POSIX file {_applescript_text(start)}))"],
                       capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        if "-128" in r.stderr:                                   # Abbrechen im Dialog
            return None
        raise RuntimeError(f"Finder-Dialog: {r.stderr.strip()}")
    return r.stdout.strip().rstrip("/") or "/"


def datei_waehlen(titel, start):
    """Nativer Dialog „Datei wählen“ (z. B. ein Abbild eines Datenträgers). Antwort: Pfad oder None, wenn abgebrochen.
    macOS: Finder (osascript); Windows: OpenFileDialog über PowerShell."""
    if windows():
        skript = ("Add-Type -AssemblyName System.Windows.Forms; "
                  "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
                  "$d = New-Object System.Windows.Forms.OpenFileDialog; "
                  "$d.Title = $env:BALDUIN_TITEL; $d.InitialDirectory = $env:BALDUIN_START; "
                  "$d.Filter = 'Abbilder (*.dmg;*.img;*.dd;*.raw;*.iso)|*.dmg;*.img;*.dd;*.raw;*.iso|Alle Dateien (*.*)|*.*'; "
                  "$f = New-Object System.Windows.Forms.Form -Property @{TopMost = $true}; "
                  "if ($d.ShowDialog($f) -eq 'OK') { $d.FileName } else { exit 2 }")
        r = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", skript], capture_output=True, text=True,
                           encoding="utf-8", timeout=900, env={**os.environ, "BALDUIN_TITEL": str(titel),
                                                               "BALDUIN_START": str(start)}, **prozess_optionen())
        if r.returncode == 2:
            return None
        if r.returncode != 0:
            raise RuntimeError(f"Dateidialog: {(r.stderr or r.stdout).strip()}")
        return r.stdout.strip()
    if linux():
        return _linux_dialog("datei", titel, start)
    if not mac():
        raise RuntimeError("Einen Dateidialog gibt es auf diesem System noch nicht.")
    r = subprocess.run(["osascript", "-e", "activate", "-e",
                        f"POSIX path of (choose file with prompt {_applescript_text(titel)} "
                        f"default location (POSIX file {_applescript_text(start)}))"],
                       capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        if "-128" in r.stderr:
            return None
        raise RuntimeError(f"Finder-Dialog: {r.stderr.strip()}")
    return r.stdout.strip()


# Rückfall ohne zenity und kdialog: Tk aus der Standardbibliothek in einem eigenen Prozess (der Server bleibt frei)
TK_DIALOG = """import sys, tkinter
from tkinter import filedialog
fenster = tkinter.Tk(); fenster.withdraw(); fenster.attributes("-topmost", True)
art, titel, start = sys.argv[1:4]
wahl = (filedialog.askdirectory if art == "ordner" else filedialog.askopenfilename)(title=titel, initialdir=start)
print(wahl or "")
"""


def _linux_dialog(art, titel, start):
    """Linux: Dialog zum Wählen eines Ordners oder einer Datei; Pfad oder None, wenn abgebrochen.
    zenity (GNOME und die meisten Desktops), sonst kdialog (KDE), sonst Tk."""
    ordner = art == "ordner"
    if (zenity := werkzeug_pfad("zenity")):
        befehl = [zenity, "--file-selection", "--title", str(titel), "--filename", str(start).rstrip("/") + "/",
                  *(["--directory"] if ordner else [])]
    elif (kdialog := werkzeug_pfad("kdialog")):
        befehl = [kdialog, "--title", str(titel), "--getexistingdirectory" if ordner else "--getopenfilename", str(start)]
    else:
        befehl = [sys.executable, "-c", TK_DIALOG, art, str(titel), str(start)]
    r = subprocess.run(befehl, capture_output=True, text=True, encoding="utf-8", timeout=900)
    if r.returncode == 1 and befehl[0] != sys.executable:          # zenity und kdialog: abgebrochen
        return None
    if r.returncode != 0:
        raise RuntimeError(f"{'Ordnerdialog' if ordner else 'Dateidialog'}: {(r.stderr or r.stdout).strip()}")
    return r.stdout.strip() or None


def systemwoerter():
    """Wörter, die vom System abhängen, für Texte der Oberfläche und Meldungen (Wording, Entscheidung 13.11.2026).
    Die Seite bekommt sie als window.SYSTEMWOERTER; fest im Text stehen „Finder“, „Schlüsselbund“ nie."""
    # adminfrage: wer beim Lesen einer Mac-Platte ohne Einhängen nach Rechten fragt; formatierwarnung: nur Windows
    # bietet an, eine Platte zu formatieren, die es nicht kennt
    # kein_schreibschutz: nur Windows hängt Datenträger nicht schreibgeschützt ein; Balduin liest dort nach Rückfrage
    # ohne Schreibschutz (Entscheidung 13.11.2026); lange_pfade: Abhilfe, wenn Windows lange Pfade nicht liest
    if mac():
        return {"system": "macOS", "dateimanager": "Finder", "schluesselspeicher": "Schlüsselbund",
                "im_schluesselspeicher": "im Schlüsselbund", "aus_dem_schluesselspeicher": "aus dem Schlüsselbund",
                "adminfrage": "", "formatierwarnung": "", "kein_schreibschutz": "", "lange_pfade": ""}
    if windows():
        return {"system": "Windows", "dateimanager": "Explorer", "schluesselspeicher": "Anmeldeinformationsverwaltung",
                "im_schluesselspeicher": "in der Anmeldeinformationsverwaltung",
                "aus_dem_schluesselspeicher": "aus der Anmeldeinformationsverwaltung",
                "adminfrage": "Windows fragt einmal nach Administratorrechten",
                "formatierwarnung": "Windows-Frage „Datenträger formatieren?“ unbedingt ablehnen.",
                "kein_schreibschutz": "Windows kann einen Datenträger nicht schreibgeschützt einhängen.",
                "lange_pfade": "Abhilfe: Balduin mit dem Installer neu einrichten oder die IT bitten, in Windows lange "
                               "Pfade einzuschalten (LongPathsEnabled); danach den Rechner neu starten."}
    if linux():
        return {"system": "Linux", "dateimanager": "Dateimanager", "schluesselspeicher": "Passwortspeicher",
                "im_schluesselspeicher": "im Passwortspeicher", "aus_dem_schluesselspeicher": "aus dem Passwortspeicher",
                "adminfrage": "das System fragt einmal nach dem Administratorpasswort", "formatierwarnung": "",
                "kein_schreibschutz": "", "lange_pfade": ""}
    speicher = "Schlüssel- und Zertifikatsverwaltung des Systems"
    return {"system": "dem System", "dateimanager": "Dateimanager", "schluesselspeicher": speicher,
            "im_schluesselspeicher": f"in der {speicher}", "aus_dem_schluesselspeicher": f"aus der {speicher}",
            "adminfrage": "", "formatierwarnung": "", "kein_schreibschutz": "", "lange_pfade": ""}


# Homebrew-Formel je Werkzeug (nur Mac); unter Windows gehören die Werkzeuge zur Auslieferung (bin/)
BREW = {"sf": "richardlehane/digipres/siegfried", "siegfried": "richardlehane/digipres/siegfried",
        "exiftool": "exiftool", "clamav": "clamav", "clamscan": "clamav", "freshclam": "clamav",
        "ffmpeg": "ffmpeg", "pdftoppm": "poppler", "pdftotext": "poppler", "smartctl": "smartmontools"}


# Paket je Werkzeug unter Debian/Ubuntu (andere Distributionen heißen ähnlich); Siegfried gibt es dort nicht
APT = {"exiftool": "libimage-exiftool-perl", "clamav": "clamav", "clamscan": "clamav", "freshclam": "clamav",
       "clamd": "clamav-daemon", "ffmpeg": "ffmpeg", "ffprobe": "ffmpeg", "pdftoppm": "poppler-utils",
       "pdftotext": "poppler-utils", "smartctl": "smartmontools", "soffice": "libreoffice", "zenity": "zenity",
       "secret-tool": "libsecret-tools", "udisksctl": "udisks2", "lsblk": "util-linux", "gio": "libglib2.0-bin"}


def installationshinweis(werkzeug):
    """Wie ein fehlendes Werkzeug auf diesem System nachkommt."""
    if mac():
        return f"Nachinstallieren mit: brew install {BREW.get(werkzeug, werkzeug)}"
    if windows():
        return "Es gehört zur Auslieferung von Balduin; Balduin bitte neu installieren."
    if linux():
        if werkzeug in ("sf", "siegfried"):
            return ("Siegfried als Paket von https://github.com/richardlehane/siegfried/releases installieren "
                    "oder das Programm sf in den Ordner bin/ neben Balduin legen.")
        return (f"Über die Paketverwaltung nachinstallieren, z. B. sudo apt install {APT.get(werkzeug, werkzeug)} "
                "(andere Distributionen: Paket mit ähnlichem Namen).")
    return "Über die Paketverwaltung des Systems nachinstallieren."


def _absolut(pfad):
    return str(Path(pfad).resolve())


def im_dateimanager_zeigen(pfad):
    """Markiert eine Datei oder einen Ordner im Dateimanager, ohne sie zu öffnen. macOS: Finder (open -R);
    Windows: Explorer (/select; meldet auch bei Erfolg den Rückgabewert 1)."""
    pfad = _absolut(pfad)
    if windows():
        subprocess.run(f'explorer /select,"{pfad}"', capture_output=True, timeout=30)
        return
    if linux():
        return _linux_dateimanager(pfad)
    if not mac():
        raise RuntimeError("Im Dateimanager zeigen gibt es auf diesem System noch nicht.")
    r = subprocess.run(["open", "-R", pfad], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError(f"Der Dateimanager konnte es nicht zeigen: {(r.stderr or r.stdout).strip()}")


def _linux_dateimanager(pfad):
    """Linux: Markieren über die Freedesktop-Schnittstelle FileManager1 (Nautilus, Dolphin, Nemo, Thunar …);
    sonst den Ordner darüber öffnen."""
    if (gdbus := werkzeug_pfad("gdbus")):
        r = subprocess.run([gdbus, "call", "--session", "--dest", "org.freedesktop.FileManager1", "--object-path",
                            "/org/freedesktop/FileManager1", "--method", "org.freedesktop.FileManager1.ShowItems",
                            "['" + Path(pfad).as_uri().replace("'", "%27") + "']", ""],
                           capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return
    if (xdg := werkzeug_pfad("xdg-open")):
        subprocess.Popen([xdg, str(Path(pfad).parent)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return
    raise RuntimeError("Im Dateimanager zeigen geht hier nicht: " + installationshinweis("xdg-open"))


def in_papierkorb(pfad):
    """Legt eine Datei oder einen Ordner in den Papierkorb (wiederherstellbar), statt zu löschen.
    macOS: über den Finder; Windows: Shell-API mit Rückgängig (SHFileOperationW, FOF_ALLOWUNDO)."""
    pfad = Path(pfad).resolve()
    if not pfad.exists():
        raise ValueError(f"{pfad} gibt es nicht.")
    if windows():
        if (code := _win_papierkorb(str(pfad))) != 0:
            raise RuntimeError(f"In den Papierkorb legen ging nicht (Fehler {code}).")
        return
    if mac():
        r = subprocess.run(["osascript", "-e", "on run argv", "-e",
                            'tell application "Finder" to delete (POSIX file (item 1 of argv) as alias)', "-e", "end run",
                            str(pfad)], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(f"In den Papierkorb legen ging nicht: {(r.stderr or r.stdout).strip()}")
        return
    if linux():
        befehl = ([gio, "trash", str(pfad)] if (gio := werkzeug_pfad("gio")) else
                  next(([k, "move", str(pfad), "trash:/"] for k in map(werkzeug_pfad, ("kioclient5", "kioclient"))
                        if k), None))
        if befehl:
            r = subprocess.run(befehl, capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                raise RuntimeError(f"In den Papierkorb legen ging nicht: {(r.stderr or r.stdout).strip()}")
            return
    raise RuntimeError("In den Papierkorb legen gibt es auf diesem System noch nicht; den Ordner bitte von Hand löschen.")


def _win_papierkorb(pfad):
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
    # FO_DELETE = 3; FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    op = SHFILEOPSTRUCTW(wFunc=3, pFrom=pfad + "\0", fFlags=0x40 | 0x10 | 0x04 | 0x400)
    return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))


def schnellvorschau(pfad, kante, ordner):
    """Vorschaubild des Systems (macOS: Quick Look, wie die Leertaste im Finder) als PNG in ordner; Pfad oder None,
    wenn das System keins liefert. Windows: noch keine (Office-Vorschau z. B. über LibreOffice folgt)."""
    if not mac():
        return None
    try:
        subprocess.run(["qlmanage", "-t", "-s", str(kante), "-o", str(ordner), str(pfad)], capture_output=True,
                       timeout=20)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Die Systemvorschau antwortet nicht (20 s)")
    return next(iter(Path(ordner).glob("*.png")), None)


# ---------- Ordner der App, Port ----------

def app_daten():
    """Ordner für die Einstellungen von Balduin auf diesem Rechner (zuletzt.json): macOS ~/Library/Application
    Support/Balduin, Windows %APPDATA%\\Balduin, sonst ~/.config/balduin."""
    if windows():
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Balduin"
    if mac():
        return Path.home() / "Library" / "Application Support" / "Balduin"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "balduin"


def zuletzt_datei():
    """zuletzt.json (zuletzt geöffnete Projekte, gemerkter Ablageort). Bis zum 09.11.2026 lag sie auf dem Mac unter
    „GF-Bewertung“; sie wird beim ersten Mal von dort kopiert, das Alte bleibt liegen."""
    neu = app_daten() / "zuletzt.json"
    alt = Path.home() / "Library" / "Application Support" / "GF-Bewertung" / "zuletzt.json"
    if mac() and not neu.exists() and alt.is_file():
        try:
            neu.parent.mkdir(parents=True, exist_ok=True)
            json.loads(alt.read_text(encoding="utf-8"))           # nur Gültiges übernehmen
            shutil.copy2(alt, neu)
        except (OSError, ValueError):
            pass
    return neu


def port_belegt(fehler):
    """Heißt dieser Fehler beim Öffnen des Servers, dass der Port belegt ist? (macOS/Linux EADDRINUSE; Windows
    WSAEADDRINUSE oder WSAEACCES, wenn ein anderes Programm ihn exklusiv hält)"""
    return fehler.errno == errno.EADDRINUSE or getattr(fehler, "winerror", None) in (10048, 10013)


def port_exklusiv(sock):
    """Windows: den Port exklusiv belegen; mit SO_REUSEADDR könnten dort zwei Programme denselben Port öffnen.
    Antwort: True = exklusiv gesetzt (dann ohne SO_REUSEADDR binden)."""
    if windows() and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        return True
    return False


# ---------- Region (für „skartieren“ in Österreich) ----------

def region_aus(gebietsschema):
    """Ländercode aus einem Gebietsschema: „de_AT“, „de-AT“, „de_AT.UTF-8“, „de_AT@currency=EUR“ → „AT“; sonst „“."""
    teile = re.split(r"[_-]", re.split(r"[.@]", (gebietsschema or "").strip())[0])
    return teile[1].upper() if len(teile) > 1 and re.fullmatch(r"[A-Za-z]{2}", teile[1]) else ""


# Namen, die nur auf diesem Rechner auflösen (Entscheidung 06.11.2026): dorthin darf Anton auch über http, der Token
# verlässt den Rechner nicht; solche Instanzen gelten außerdem immer als Testinstanz (Entscheidung 12.11.2026).
# .localhost und .test nach RFC 6761, .ddev.site für lokale DDEV-Instanzen.
LOKALE_NAMEN = ("127.0.0.1", "::1", "localhost")
LOKALE_ENDUNGEN = (".localhost", ".test", ".ddev.site")


def nur_lokal(hostname):
    h = (hostname or "").lower().rstrip(".")
    return h in LOKALE_NAMEN or h.endswith(LOKALE_ENDUNGEN)


def systemregion():
    """Region des Rechners als Ländercode („AT“, „CH“, „DE“ …; „“ = unbekannt), z. B. für „skartieren“ in Österreich.
    BALDUIN_REGION gibt sie vor (Tests, Ausprobieren); macOS: Systemeinstellung AppleLocale; Windows: Gebietsschema
    des Kontos; sonst LC_ALL/LANG."""
    if vorgabe := os.environ.get("BALDUIN_REGION"):
        return region_aus(vorgabe) or region_aus("x_" + vorgabe)
    try:
        if mac():
            r = subprocess.run(["defaults", "read", "-g", "AppleLocale"], capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and (region := region_aus(r.stdout)):
                return region
        elif windows():
            import ctypes
            puffer = ctypes.create_unicode_buffer(85)
            if ctypes.windll.kernel32.GetUserDefaultLocaleName(puffer, 85):
                return region_aus(puffer.value)
    except (OSError, subprocess.SubprocessError, AttributeError):
        pass
    return region_aus(os.environ.get("LC_ALL") or os.environ.get("LANG"))

"""Mac-Datenträger ohne Mac (Entscheidung 09.11.2026, docs/plan.md): HFS+ und APFS nur lesend selbst lesen.

Windows hängt HFS+ und APFS nicht ein. Balduin liest das Dateisystem deshalb selbst, aus einem Abbild (.dmg
unkomprimiert, .img, .dd, .iso) oder von der physischen Platte, ohne sie einzuhängen und ohne je zu schreiben:
- Partitionstabelle (GPT, MBR, Apple Partition Map) über pytsk3 (The Sleuth Kit),
- HFS+/HFSX über libfshfs, APFS über libfsapfs (libyal; auch verschlüsselte Volumes nach Passwort).
Auf dem Mac bleibt das Einhängen der Normalfall; diese Schicht dient dort für Abbilder.

Eine Quelle, deren Wurzel kein Ordner, sondern ein Abbild ist (ist_abbild), liest erfassung/quelle.py hierüber.
Die Kennung eines Volumes ist dieselbe, die macOS als VolumeUUID nennt (APFS: Kennung des Volumes; HFS+: UUID v3
aus der Volume-ID in der Finder-Info), damit eine auf dem Mac registrierte Platte wiedererkannt wird.
"""
import hashlib
import io
import os
import uuid as uuid_modul
from datetime import timezone
from pathlib import Path

from . import system
from .basis import SYSTEMORDNER, nfc

# Verwaltungseinträge von HFS+ (Wurzel), die nicht zum Bestand gehören; dazu SYSTEMORDNER wie beim Schnellscan
HFS_VERWALTUNG = {".HFS+ Private Directory Data\r", "\x00\x00\x00\x00HFS+ Private Data", "\u2400" * 4 + "HFS+ Private Data", ".journal",
                  ".journal_info_block", ".HFS+ Private Directory Data"}
# Namensraum, aus dem macOS die VolumeUUID einer HFS+-Platte bildet (UUID v3 aus der 8-Byte-Volume-ID)
HFS_NAMENSRAUM = uuid_modul.UUID("B3E20F39-F292-11D6-97A4-00306543ECAC")
ORDNER, DATEI, VERWEIS = 0o040000, 0o100000, 0o120000


def ist_abbild(wurzel):
    """Liest diese Schicht die Quelle? Ein Abbild (eine Datei) oder unter Windows eine physische Platte
    (\\\\.\\PhysicalDriveN), statt eines Ordners."""
    return system.ist_geraet(wurzel) or Path(wurzel).is_file()


class Ausschnitt(io.RawIOBase):
    """Nur lesendes Dateiobjekt auf einen Teil von f (eine Partition). sektor > 1: jeder Zugriff auf f beginnt und
    endet an einer Sektorgrenze (Windows liest physische Platten nur so)."""

    def __init__(self, f, start=0, laenge=None, sektor=1):
        super().__init__()
        self.f, self.start, self.sektor, self.pos = f, start, sektor, 0
        if laenge is None:
            f.seek(0, io.SEEK_END)
            laenge = f.tell() - start
        self.laenge = laenge

    def readable(self):
        return True

    def seekable(self):
        return True

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.laenge - self.pos
        n = max(0, min(n, self.laenge - self.pos))
        if n == 0:
            return b""
        von = self.start + self.pos
        if self.sektor > 1:
            a = von // self.sektor * self.sektor
            b = -(-(von + n) // self.sektor) * self.sektor
            self.f.seek(a)
            daten = self.f.read(b - a)[von - a:von - a + n]
        else:
            self.f.seek(von)
            daten = self.f.read(n)
        self.pos += len(daten)
        return daten

    def readinto(self, puffer):
        daten = self.read(len(puffer))
        puffer[:len(daten)] = daten
        return len(daten)

    def seek(self, pos, woher=io.SEEK_SET):
        self.pos = {io.SEEK_SET: pos, io.SEEK_CUR: self.pos + pos, io.SEEK_END: self.laenge + pos}[woher]
        return self.pos

    def tell(self):
        return self.pos

    def get_size(self):                     # libyal fragt die Größe so ab
        return self.laenge

    def get_offset(self):
        return self.pos


def fat_uuid(seriennummer):
    """VolumeUUID eines FAT-/exFAT-Volumes wie macOS sie bildet: wie bei HFS+ (MD5 aus demselben Namensraum), aus der
    4-Byte-Seriennummer des Volumes (little endian), die Windows als „XXXX-XXXX“ zeigt. Gemessen am 13.11.2026."""
    return hfs_uuid(int(seriennummer).to_bytes(4, "little"))


def hfs_uuid(volume_id):
    """VolumeUUID einer HFS+-Platte wie macOS sie bildet; leere oder fehlende Volume-ID → „“."""
    if not volume_id.strip(b"\0"):
        return ""
    h = bytearray(hashlib.md5(HFS_NAMENSRAUM.bytes + volume_id).digest())
    h[6] = (h[6] & 0x0F) | 0x30
    h[8] = (h[8] & 0x3F) | 0x80
    return str(uuid_modul.UUID(bytes=bytes(h))).upper()


def roh_oeffnen(quelle):
    """(Dateiobjekt, Größe, Sektorgröße) einer Quelle, nur lesend: ein Abbild als Datei oder eine physische Platte
    über system.geraet_oeffnen (Windows, ganze Sektoren)."""
    if system.ist_geraet(quelle):
        return system.geraet_oeffnen(quelle)
    return open(quelle, "rb"), os.path.getsize(quelle), 1


def partitionen(f, sektor=1, groesse=None):
    """Teile der Quelle, die ein Mac-Dateisystem tragen: [(start, länge, art)] mit art „HFS+“, „HFSX“, „HFS“ oder
    „APFS“. Ohne Partitionstabelle wird die ganze Quelle geprüft (Abbild einer einzelnen Partition)."""
    import pytsk3

    ganz = Ausschnitt(f, 0, groesse, sektor)

    class Bild(pytsk3.Img_Info):
        def __init__(self):
            super().__init__(url="", type=pytsk3.TSK_IMG_TYPE_EXTERNAL)

        def read(self, offset, size):
            ganz.seek(offset)
            return ganz.read(size)

        def get_size(self):
            return ganz.laenge

    kandidaten = []
    try:
        vs = pytsk3.Volume_Info(Bild())
        kandidaten = [(t.start * vs.info.block_size, t.len * vs.info.block_size) for t in vs
                      if t.flags == pytsk3.TSK_VS_PART_FLAG_ALLOC and t.len > 0]
    except OSError:
        pass
    kandidaten.append((0, ganz.laenge))
    gefunden = []
    for start, laenge in kandidaten:
        art = dateisystem_art(Ausschnitt(f, start, laenge, sektor))
        if art and not any(s == start for s, _, _ in gefunden):
            gefunden.append((start, laenge, art))
        if gefunden and start == 0 and laenge == ganz.laenge:
            break
    return [g for g in gefunden if not (g[0] == 0 and len(gefunden) > 1)]


def dateisystem_art(teil):
    """Art des Dateisystems am Anfang eines Teils anhand seiner Kennung, sonst „“."""
    teil.seek(0)
    kopf = teil.read(1100)
    if kopf[32:36] == b"NXSB":
        return "APFS"
    return {b"H+": "HFS+", b"HX": "HFSX", b"BD": "HFS"}.get(kopf[1024:1026], "")


def volumes(quelle):
    """Mac-Volumes einer Quelle: [{name, dateisystem, uuid, gesperrt, groesse, start, laenge, nr}]; leer, wenn die
    Quelle kein HFS+ oder APFS trägt. Gelesen werden nur Verwaltungsangaben."""
    f, groesse, sektor = roh_oeffnen(quelle)
    try:
        return _volumes(f, sektor, groesse)
    finally:
        f.close()


def _volumes(f, sektor, groesse=None):
    import pyfsapfs
    import pyfshfs

    liste = []
    for start, laenge, art in partitionen(f, sektor, groesse):
        teil = Ausschnitt(f, start, laenge, sektor)
        try:
            if art == "APFS":
                c = pyfsapfs.container()
                c.open_file_object(teil)
                for nr in range(c.number_of_volumes):
                    v = c.get_volume(nr)
                    liste.append({"name": v.name, "dateisystem": "APFS", "uuid": (v.identifier or "").upper(),
                                  "gesperrt": bool(v.is_locked()), "groesse": laenge, "start": start,
                                  "laenge": laenge, "nr": nr})
                c.close()
            else:
                v = pyfshfs.volume()
                v.open_file_object(teil)
                teil.seek(1024)
                kopf = teil.read(512)
                liste.append({"name": v.name, "dateisystem": art, "uuid": hfs_uuid(kopf[104:112]) if art != "HFS" else "",
                              "gesperrt": False, "groesse": int.from_bytes(kopf[40:44], "big") * int.from_bytes(kopf[44:48], "big"),
                              "start": start, "laenge": laenge, "nr": 0})
                v.close()
        except OSError as e:
            liste.append({"name": "", "dateisystem": art, "uuid": "", "gesperrt": False, "groesse": laenge,
                          "start": start, "laenge": laenge, "nr": 0, "fehler": str(e).splitlines()[0][:200]})
    return liste


def oeffne_volume(quelle, uuid=None, passwort=None):
    """Öffnet ein Volume der Quelle zum Lesen: das mit dieser Kennung oder, ohne Kennung, das einzige.
    ValueError mit verständlichem Grund (kein Mac-Dateisystem, nicht gefunden, mehrere, verschlüsselt)."""
    f, groesse, sektor = roh_oeffnen(quelle)
    try:
        vs = [v for v in _volumes(f, sektor, groesse) if "fehler" not in v]
        if not vs:
            raise ValueError(f"{Path(str(quelle)).name} enthält kein HFS+- oder APFS-Dateisystem, das sich lesen lässt.")
        if uuid:
            vs = [v for v in vs if v["uuid"] and v["uuid"].upper() == uuid.upper()]
            if not vs:
                raise ValueError(f"Der Datenträger {uuid} ist in {Path(str(quelle)).name} nicht zu finden.")
        elif len(vs) > 1:
            raise ValueError(f"{Path(str(quelle)).name} enthält mehrere Datenträger: "
                             + ", ".join(f"{v['name']} ({v['uuid']})" for v in vs) + ". Bitte eines wählen.")
        return Volume(quelle, f, sektor, vs[0], passwort)
    except BaseException:
        f.close()
        raise


class Volume:
    """Ein geöffnetes Mac-Volume: Dateien auflisten, Ordner zeigen, Inhalte als Datenstrom lesen. Pfade wie überall in
    Balduin: relativ zur Wurzel, in NFC, mit „/“."""

    def __init__(self, quelle, f, sektor, angaben, passwort=None):
        import pyfsapfs
        import pyfshfs

        self.quelle, self.f, self.angaben = quelle, f, angaben
        teil = Ausschnitt(f, angaben["start"], angaben["laenge"], sektor)
        self.container = None
        if angaben["dateisystem"] == "APFS":
            self.container = pyfsapfs.container()
            self.container.open_file_object(teil)
            self.v = self.container.get_volume(angaben["nr"])
            if self.v.is_locked():
                if not passwort:
                    raise ValueError(f"Der Datenträger {angaben['name']} ist verschlüsselt. Bitte das Passwort angeben.")
                self.v.set_password(passwort)
                if not self.v.unlock():
                    raise ValueError(f"Das Passwort für {angaben['name']} stimmt nicht.")
        else:
            self.v = pyfshfs.volume()
            self.v.open_file_object(teil)
        self.kinder = {}               # Ordner (relpfad) → {Name in NFC: (Kennung, Art)}
        self.fehler = []               # [(relpfad, Meldung)] beim Auflisten nicht lesbarer Ordner
        self.info = {"VolumeName": angaben["name"], "VolumeUUID": angaben["uuid"],
                     "FilesystemName": angaben["dateisystem"], "TotalSize": angaben["groesse"], "FreeSpace": None,
                     "DeviceIdentifier": "", "BusProtocol": "Disk Image", "MountPoint": str(quelle),
                     "Verschluesselt": bool(angaben.get("gesperrt"))}     # nur mit Passwort lesbar (13.11.2026)

    def __enter__(self):
        return self

    def __exit__(self, *fehler):
        self.close()

    def close(self):
        for obj in (self.v, self.container):
            try:
                if obj is not None:
                    obj.close()
            except (OSError, AttributeError):
                pass
        self.f.close()

    # ---- Navigation ----

    def _eintrag(self, kennung):
        return self.v.get_file_entry_by_identifier(kennung)

    @staticmethod
    def _art(eintrag):
        modus = (eintrag.file_mode or 0) & 0o170000
        if modus == 0:                   # HFS ohne Rechte: Ordner haben Einträge darunter
            return ORDNER if eintrag.number_of_sub_file_entries else DATEI
        return modus

    def _kinder(self, ordner):
        """{Name in NFC: (Kennung, Art)} eines Ordners (zwischengespeichert)."""
        if ordner not in self.kinder:
            e = self.v.root_directory if ordner == "" else self._pfad(ordner, ORDNER)
            liste = {}
            for kind in e.sub_file_entries:
                name = nfc(kind.name).replace("/", ":")
                if name in HFS_VERWALTUNG or (ordner == "" and name in SYSTEMORDNER):
                    continue
                liste[name] = (kind.identifier, self._art(kind))
            self.kinder[ordner] = liste
        return self.kinder[ordner]

    def _pfad(self, relpfad, art=None):
        """Eintrag zu einem relpfad; FileNotFoundError, wenn es ihn (in dieser Art) nicht gibt."""
        kopf, _, name = nfc(relpfad).rpartition("/")
        try:
            kennung, gefunden = self._kinder(kopf)[name]
        except (KeyError, FileNotFoundError):
            raise FileNotFoundError(f"{relpfad} gibt es auf {self.info['VolumeName']} nicht") from None
        if art is not None and gefunden != art:
            raise FileNotFoundError(f"{relpfad} ist auf {self.info['VolumeName']} kein "
                                    f"{'Ordner' if art == ORDNER else 'Datei'}")
        return self._eintrag(kennung)

    # ---- Abfragen ----

    def eintraege(self, umfang=None):
        """Alle Dateien (ohne Verweise und Verwaltungsordner): (relpfad, größe, Änderungszeit). umfang: nur diese Ordner."""
        stapel = list(reversed(umfang)) if umfang else [""]
        while stapel:
            ordner = stapel.pop()
            try:
                kinder = self._kinder(ordner)
            except (OSError, FileNotFoundError) as e:
                self.fehler.append((ordner, str(e).splitlines()[0][:200]))
                continue
            unterordner = []
            for name, (kennung, art) in sorted(kinder.items()):
                rel = f"{ordner}/{name}" if ordner else name
                if art == ORDNER:
                    if name not in SYSTEMORDNER:
                        unterordner.append(rel)
                elif art == DATEI:
                    try:
                        e = self._eintrag(kennung)
                        yield rel, e.size, zeit(e)
                    except OSError as fehler:
                        self.fehler.append((rel, str(fehler).splitlines()[0][:200]))
            stapel.extend(reversed(unterordner))

    def ordner(self, relpfad=""):
        """Namen der Unterordner eines Ordners, sortiert (für die Wahl des Umfangs)."""
        return sorted(n for n, (_, art) in self._kinder(nfc(relpfad).strip("/")).items()
                      if art == ORDNER and n not in SYSTEMORDNER)

    def ist_ordner(self, relpfad):
        try:
            self._pfad(relpfad, ORDNER)
            return True
        except FileNotFoundError:
            return False

    def ist_datei(self, relpfad):
        try:
            self._pfad(relpfad, DATEI)
            return True
        except FileNotFoundError:
            return False

    def stat(self, relpfad):
        """(größe, Änderungszeit) einer Datei; FileNotFoundError für Ordner und Fehlendes."""
        e = self._pfad(relpfad, DATEI)
        return e.size, zeit(e)

    def oeffnen(self, relpfad):
        """Datenzweig einer Datei als nur lesendes Dateiobjekt (read, seek, tell)."""
        return Datenstrom(self._pfad(relpfad, DATEI))


def zeit(eintrag):
    """Änderungszeit als Unix-Zeit (libyal liefert sie als datetime in UTC)."""
    t = eintrag.modification_time
    return t.replace(tzinfo=timezone.utc).timestamp() if t else None


class Datenstrom(io.RawIOBase):
    """Inhalt einer Datei im Volume, nur lesend, mit seek (zipfile und tarfile brauchen das)."""

    def __init__(self, eintrag):
        super().__init__()
        self.e, self.groesse, self.pos = eintrag, eintrag.size, 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def read(self, n=-1):
        if n is None or n < 0:
            n = self.groesse - self.pos
        n = max(0, min(n, self.groesse - self.pos))
        if n == 0:
            return b""
        daten = self.e.read_buffer_at_offset(n, self.pos)
        self.pos += len(daten)
        return daten

    def readinto(self, puffer):
        daten = self.read(len(puffer))
        puffer[:len(daten)] = daten
        return len(daten)

    def readall(self):
        return self.read(-1)

    def seek(self, pos, woher=io.SEEK_SET):
        self.pos = {io.SEEK_SET: pos, io.SEEK_CUR: self.pos + pos, io.SEEK_END: self.groesse + pos}[woher]
        return self.pos

    def tell(self):
        return self.pos

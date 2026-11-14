"""C2 Archivdateien (ZIP, tar, gz) wie Ordner (Entscheidung 06.11.2026, docs/plan.md).

Eine Archivdatei auf der Platte wird nicht als eine Datei erfasst, sondern ihr Inhalt: jede Datei darin bekommt den
Pfad <Archivdatei>/<Pfad darin>, als wäre die Archivdatei ein Ordner. So gelten Bäume, Entscheidungen, Vererbung und
Zuordnung unverändert. Gelesen wird nur (harte Regel 1): die Archivdatei wird geöffnet, nie auf der Platte entpackt.

Nur Formate, die die Python-Standardbibliothek auf jedem System liest: ZIP, tar (auch .tar.gz, .tgz, .tar.bz2,
.tar.xz) und einzeln gepackte Dateien (.gz, .bz2, .xz). StuffIt, RAR, .dmg und 7z bleiben eine gewöhnliche Datei.
Office-Dateien (.docx, .xlsx …) sind technisch ZIPs, werden aber nur an der Endung erkannt und darum nie aufgelöst.
"""
import bz2
import gzip
import lzma
import os
import re
import shutil
import tarfile
import tempfile
import time
import zipfile
import zlib
from collections import defaultdict, namedtuple
from contextlib import ExitStack, contextmanager
from pathlib import Path

from .basis import P, db, nfc, platz_pruefen, quellpfad, relpfad_von
from . import quelle

TIEFE = 3                          # Archive im Archiv: so viele Ebenen werden aufgelöst, tiefere bleiben Dateien
HOECHSTENS_ENTPACKT = 200 * 10**9  # Bytes je Archivdatei; mehr bleibt ganz (Schutz vor Zip-Bomben)

TAR_ENDUNGEN = (".tar", ".tgz", ".tar.gz", ".tbz", ".tbz2", ".tar.bz2", ".txz", ".tar.xz")
STROM_ENDUNGEN = {".gz": "gz", ".bz2": "bz2", ".xz": "xz"}
STROM_OEFFNEN = {"gz": gzip.GzipFile, "bz2": bz2.BZ2File, "xz": lzma.LZMAFile}
LESEFEHLER = (zipfile.BadZipFile, tarfile.TarError, EOFError, OSError, zlib.error, lzma.LZMAError, ValueError,
              NotImplementedError, RuntimeError)

Eintrag = namedtuple("Eintrag", "groesse mtime")


class ArchivFehler(Exception):
    """Die Archivdatei lässt sich nicht auflösen; status: defekt, verschlüsselt, zu groß."""

    def __init__(self, status, meldung):
        super().__init__(meldung)
        self.status, self.meldung = status, meldung


def art_von(name):
    """Art der Archivdatei nach der Endung (zip, tar, gz, bz2, xz) oder None. AppleDouble-Dateien („._alt.zip“, macOS
    auf FAT/exFAT und in ZIPs) sind Systemdateien, keine Archive (UTM-Test 13.11.2026)."""
    if name.startswith("._"):
        return None
    n = name.lower()
    if n.endswith(".zip"):
        return "zip"
    if n.endswith(TAR_ENDUNGEN):
        return "tar"
    for endung, art in STROM_ENDUNGEN.items():
        if n.endswith(endung) and len(n) > len(endung):
            return art
    return None


def sauberer_pfad(roh):
    """Pfad darin ohne „..“, „.“, führende oder doppelte „/“ (manche Archive enthalten „../x“ oder „/etc/x“)."""
    return nfc("/".join(t for t in roh.replace("\\", "/").split("/") if t not in ("", ".", "..")))


# ---------- Behälter: einheitlicher Zugriff auf ZIP, tar und einzeln gepackte Dateien ----------

class Zip:
    def __init__(self, f, name, mtime):
        try:
            self.z = zipfile.ZipFile(f)
        except LESEFEHLER as e:
            raise ArchivFehler("defekt", f"kein lesbares ZIP: {e}") from e
        self.mtime = mtime
        self.infos = {}
        for i in self.z.infolist():
            if i.is_dir():
                continue
            if i.flag_bits & 0x1:
                raise ArchivFehler("verschlüsselt", "Dateien darin sind verschlüsselt")
            innen = sauberer_pfad(self.zipname(i))
            if innen:
                self.infos[innen] = i

    @staticmethod
    def zipname(info):
        """Name im ZIP. Ohne UTF-8-Kennzeichen liest Python ihn als CP437; das Archivprogramm des Mac schreibt aber
        UTF-8 ohne Kennzeichen. Lässt sich der Name als UTF-8 lesen, ist er das."""
        name = info.filename
        if not info.flag_bits & 0x800:
            try:
                roh = name.encode("cp437")
                if not roh.isascii():
                    name = roh.decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
        return name

    def zeit(self, info):
        """Änderungsdatum im ZIP: Ortszeit ohne Zone (wie das System, das es geschrieben hat)."""
        try:
            return time.mktime((*info.date_time, 0, 0, -1))
        except (OverflowError, ValueError):
            return self.mtime

    def eintraege(self):
        return {innen: Eintrag(i.file_size, self.zeit(i)) for innen, i in self.infos.items()}

    def oeffnen(self, innen):
        return self.z.open(self.infos[innen])

    def der_reihe_nach(self, gewollt):
        for innen in self.infos:
            if gewollt(innen):
                with self.oeffnen(innen) as f:
                    yield innen, f

    def close(self):
        self.z.close()
        if getattr(self, "puffer", None):
            self.puffer.close()


class Tar:
    def __init__(self, f, name, mtime, strom=False):
        try:
            # strom: nur vorwärts lesen (der_reihe_nach), sonst mit Sprüngen (eintraege, oeffnen)
            self.t = tarfile.open(fileobj=f, mode="r|*" if strom else "r:*")
            self.mitglieder = {} if strom else {sauberer_pfad(m.name): m for m in self.t.getmembers() if m.isfile()}
        except LESEFEHLER as e:
            raise ArchivFehler("defekt", f"kein lesbares tar: {e}") from e
        self.mitglieder.pop("", None)

    def eintraege(self):
        return {innen: Eintrag(m.size, m.mtime) for innen, m in self.mitglieder.items()}

    def oeffnen(self, innen):
        return self.t.extractfile(self.mitglieder[innen])

    def der_reihe_nach(self, gewollt):
        for m in self.t:
            innen = sauberer_pfad(m.name)
            if m.isfile() and innen and gewollt(innen):
                yield innen, self.t.extractfile(m)

    def close(self):
        self.t.close()


class Strom:
    """Eine einzeln gepackte Datei (.gz, .bz2, .xz): darin genau eine Datei, Name ohne die Endung."""

    def __init__(self, f, name, mtime, art):
        self.f, self.art, self.mtime = f, art, mtime
        basis = name.rsplit("/", 1)[-1]
        self.innen = nfc(basis[: basis.lower().rfind(".")])
        self.groesse = None

    def eintraege(self):
        if self.groesse is None:                    # Größe nur durch Entpacken (gzip kennt sie nur modulo 4 GB)
            n = 0
            try:
                with self.oeffnen(self.innen) as s:
                    while stueck := s.read(4 * 1024 * 1024):
                        n += len(stueck)
                        if n > HOECHSTENS_ENTPACKT:
                            raise ArchivFehler("zu groß", f"entpackt mehr als {HOECHSTENS_ENTPACKT / 1e9:.0f} GB")
            except LESEFEHLER as e:
                raise ArchivFehler("defekt", f"kein lesbares {self.art}: {e}") from e
            self.groesse = n
        return {self.innen: Eintrag(self.groesse, self.mtime)}

    def oeffnen(self, innen):
        if innen != self.innen:
            raise KeyError(innen)
        if springbar(self.f):
            self.f.seek(0)
        return STROM_OEFFNEN[self.art](fileobj=self.f)

    def der_reihe_nach(self, gewollt):
        if gewollt(self.innen):
            with self.oeffnen(self.innen) as s:
                yield self.innen, s

    def close(self):
        pass


def springbar(f):
    """Lässt sich im Dateiobjekt springen? Eine Datei im tar-Strom („r|*“) wirft bei seekable() einen
    AttributeError statt False zu sagen (tarfile._Stream kennt es nicht)."""
    try:
        return f.seekable()
    except (AttributeError, OSError):
        return False


def behaelter(f, name, art, mtime=None, strom=False):
    if art == "zip":
        if not springbar(f):                        # ZIP im tar-Strom: ZIP braucht Sprünge, also zwischenpuffern
            puffer = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024)
            shutil.copyfileobj(f, puffer, 4 * 1024 * 1024)
            puffer.seek(0)
            z = Zip(puffer, name, mtime)
            z.puffer = puffer
            return z
        return Zip(f, name, mtime)
    if art == "tar":
        return Tar(f, name, mtime, strom)
    return Strom(f, name, mtime, art)


# ---------- C: Inhalt auflisten ----------

def auflisten(f, relpfad, art, mtime, tiefe=1):
    """Inhalt einer Archivdatei (Dateiobjekt f, Pfad relpfad auf der Platte oder im Archiv darüber).
    Antwort: (Dateien [(relpfad, groesse, mtime)], Archivdateien [Zeilen für die Tabelle archivdatei]).
    Wirft ArchivFehler, wenn sie sich nicht auflösen lässt; Archive darin, die sich nicht auflösen lassen,
    bleiben Dateien und stehen mit ihrem Status in der Liste der Archivdateien."""
    dateien, archive = [], []
    b = behaelter(f, relpfad, art, mtime)
    try:
        eintraege = b.eintraege()
        summe = sum(e.groesse for e in eintraege.values())
        if summe > HOECHSTENS_ENTPACKT:
            raise ArchivFehler("zu groß", f"entpackt {summe / 1e9:.0f} GB, mehr als {HOECHSTENS_ENTPACKT / 1e9:.0f} GB")
        for innen, e in eintraege.items():
            voll = f"{relpfad}/{innen}"
            kind_art = art_von(innen)
            if kind_art and tiefe < TIEFE:
                try:
                    with b.oeffnen(innen) as kind:
                        d, a = auflisten(kind, voll, kind_art, e.mtime, tiefe + 1)
                    dateien += d
                    archive += a
                    continue
                except ArchivFehler as fehler:
                    archive.append(archivzeile(voll, kind_art, fehler.status, fehler.meldung, groesse=e.groesse,
                                               mtime=e.mtime))
                except LESEFEHLER as fehler:
                    archive.append(archivzeile(voll, kind_art, "defekt", repr(fehler), groesse=e.groesse, mtime=e.mtime))
            dateien.append((voll, e.groesse, e.mtime))
    except LESEFEHLER as fehler:
        raise ArchivFehler("defekt", repr(fehler)) from fehler
    finally:
        b.close()
    archive.append(archivzeile(relpfad, art, "aufgelöst", "", len(eintraege), summe))
    return dateien, archive


def archivzeile(relpfad, art, status, meldung, dateien=None, bytes_entpackt=None, groesse=None, mtime=None):
    return {"relpfad": relpfad, "art": art, "status": status, "meldung": meldung, "dateien": dateien,
            "bytes_entpackt": bytes_entpackt, "groesse": groesse, "mtime": mtime}


# ---------- Lesen: eine Datei oder viele in einem Zug ----------

class _Lesen:
    """Dateiobjekt aus einem Archiv, das beim Schließen auch die Archive darüber schließt."""

    def __init__(self, f, stapel):
        self.f, self.stapel = f, stapel

    def read(self, *a):
        return self.f.read(*a)

    def close(self):
        self.stapel.close()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def aeusserste(wurzel, relpfad):
    """Pfad der äußersten Archivdatei auf der Platte, in der relpfad liegt, oder None."""
    teile = relpfad.split("/")
    for i in range(1, len(teile)):
        kopf = "/".join(teile[:i])
        if quelle.ist_datei(wurzel, kopf):
            return kopf if art_von(teile[i - 1]) else None
    return None


def oeffnen(wurzel, relpfad):
    """Öffnet eine Datei aus einer Archivdatei der Platte zum Lesen (auch Archive im Archiv). FileNotFoundError,
    wenn es sie nicht gibt."""
    archiv = aeusserste(wurzel, relpfad)
    if archiv is None:
        raise FileNotFoundError(f"{relpfad} liegt weder auf dem Datenträger noch in einer Archivdatei")
    stapel = ExitStack()
    try:
        f = stapel.enter_context(quelle.oeffnen(wurzel, archiv))
        name, rest = archiv, relpfad[len(archiv) + 1:].split("/")
        while True:
            b = behaelter(f, name, art_von(name.rsplit("/", 1)[-1]))
            stapel.callback(b.close)
            eintraege = b.eintraege()
            for k in range(len(rest), 0, -1):             # längster Teil des Pfads, der ein Eintrag ist
                innen = "/".join(rest[:k])
                if innen in eintraege and (k == len(rest) or art_von(innen)):
                    break
            else:
                raise FileNotFoundError(f"{relpfad}: nicht in {name}")
            f = stapel.enter_context(b.oeffnen(innen))
            if k == len(rest):
                return _Lesen(f, stapel)
            name, rest = f"{name}/{innen}", rest[k:]
    except ArchivFehler as e:
        stapel.close()
        raise OSError(f"{relpfad}: {e.meldung}") from e
    except BaseException:
        stapel.close()
        raise


def durchlaufen(wurzel, archiv, gesucht):
    """Liest die gesuchten Dateien (volle relpfade) aus der Archivdatei archiv in der Reihenfolge des Archivs, in
    einem Zug (auch aus Archiven darin). Liefert (relpfad, Dateiobjekt); das Dateiobjekt gilt nur bis zum nächsten."""
    gesucht = set(gesucht)
    darueber = {g.rsplit("/", k)[0] for g in gesucht for k in range(1, g.count("/") + 1)}
    with quelle.oeffnen(wurzel, archiv) as f:
        yield from _durchlaufen(f, archiv, gesucht, darueber)


def _durchlaufen(f, name, gesucht, darueber):
    b = behaelter(f, name, art_von(name.rsplit("/", 1)[-1]), strom=True)
    try:
        for innen, kind in b.der_reihe_nach(lambda i: f"{name}/{i}" in gesucht or f"{name}/{i}" in darueber):
            voll = f"{name}/{innen}"
            if voll in gesucht:
                yield voll, kind
            elif art_von(innen):
                yield from _durchlaufen(kind, voll, gesucht, darueber)
    finally:
        b.close()


# ---------- Bereitstellen für Werkzeuge, die einen Dateipfad brauchen (D2, D3, E, E4, F) ----------

class Pfade:
    """Aufrufbar: pfad(relpfad) → Pfad im Dateisystem (auf der Platte oder entpackt im Projekt);
    pfad.relpfad(pfad) → relpfad der Platte (für Werkzeuge, die Pfade zurückmelden, z. B. Siegfried)."""

    def __init__(self, wurzel, entpackt=None, ordner=None):
        self.wurzel, self.entpackt, self.ordner = Path(wurzel), entpackt or {}, ordner
        self.wurzel_abs = os.path.abspath(wurzel)
        # Bereitgestellte Dateien heißen nach einer laufenden Nummer; zurück über den Pfad
        self.zurueck = {os.path.normcase(os.path.abspath(p)): r for r, p in self.entpackt.items()}

    def __call__(self, relpfad):
        """Pfad im Dateisystem; bei einem Abbild nur für Bereitgestelltes (sonst FileNotFoundError)."""
        if relpfad in self.entpackt:
            return self.entpackt[relpfad]
        if quelle.ist_abbild(self.wurzel):
            raise FileNotFoundError(f"{relpfad} ist nicht bereitgestellt")
        return quellpfad(self.wurzel, relpfad)

    def relpfad(self, pfad):
        pfad = os.path.abspath(pfad)
        if os.path.normcase(pfad) in self.zurueck:
            return self.zurueck[os.path.normcase(pfad)]
        if self.ordner and pfad.startswith(str(self.ordner) + os.sep):
            return relpfad_von(pfad, self.ordner)
        return relpfad_von(pfad, self.wurzel_abs)


def bereit_name(nummer, relpfad):
    """Ort einer bereitgestellten Datei in entpackt/: ein nummerierter Ordner je Datei und darin ihr Name (Werkzeuge
    zeigen ihn und erkennen das Format auch an der Endung). Nicht der Pfad der Quelle: Mac-Namen dürfen „:“ und
    < > " | ? * enthalten, die Windows verbietet (NTFS machte aus „a:b“ still einen alternativen Datenstrom), und
    tiefe Pfade würden zu lang. Verbotene Zeichen werden „_“."""
    name = re.sub(r'[<>:"|?*\x00-\x1f\\]', "_", relpfad.rsplit("/", 1)[-1]).rstrip(" .") or "datei"
    return f"{nummer:06d}/{name}"


@contextmanager
def bereitstellen(platte_id, wurzel, relpfade):
    """Für Schritte mit Werkzeugen, die einen Dateipfad brauchen (Siegfried, ClamAV, ExifTool, Poppler, Quick Look,
    ffmpeg): Dateien in Archivdateien werden für die Dauer des Schritts in den Arbeitsordner entpackt/ im Projekt
    geschrieben (je Archivdatei in einem Zug, mit dem Änderungsdatum aus dem Archiv), frei liegende bleiben auf der
    Platte. Bei einem Abbild (erfassung/quelle.py) kommen auch die frei liegenden dorthin, es hat keine Pfade im
    Dateisystem. Danach wird der Arbeitsordner gelöscht. Liefert Pfade (siehe dort)."""
    gesucht = set(relpfade)
    abbild = quelle.ist_abbild(wurzel)
    with db() as con:
        darin = [(r, a, g, m) for r, a, g, m in con.execute(
            "SELECT relpfad, archiv, groesse, mtime FROM schnellscan WHERE platte_id = ? AND "
            + ("relpfad IS NOT NULL" if abbild else "archiv IS NOT NULL"), (platte_id,)) if r in gesucht]
    if not darin:
        yield Pfade(wurzel)
        return
    platz_pruefen(sum(g or 0 for _, _, g, _ in darin) / 1e9)
    basis = P.ordner / "entpackt"
    basis.mkdir(exist_ok=True)
    ordner = Path(tempfile.mkdtemp(prefix=f"{platte_id}-", dir=basis))
    try:
        je_archiv, zeit = defaultdict(set), {}
        for r, a, _, m in darin:
            je_archiv[a].add(r)
            zeit[r] = m
        entpackt = {}
        for r in sorted(je_archiv.pop(None, ())):        # frei liegend in einem Abbild
            ziel = ordner / bereit_name(len(entpackt), r)
            ziel.parent.mkdir(parents=True, exist_ok=True)
            try:
                with quelle.oeffnen(wurzel, r) as f, open(ziel, "wb") as aus:
                    shutil.copyfileobj(f, aus, 4 * 1024 * 1024)
            except LESEFEHLER as e:                      # was fehlt, meldet das Werkzeug als nicht lesbar
                print(f"⚠ {r}: nicht lesbar ({e!r})")
                continue
            if zeit[r]:
                os.utime(ziel, (zeit[r], zeit[r]))
            entpackt[r] = ziel
        for archiv, rs in je_archiv.items():
            try:
                for r, f in durchlaufen(wurzel, archiv, rs):
                    ziel = ordner / bereit_name(len(entpackt), r)
                    ziel.parent.mkdir(parents=True, exist_ok=True)
                    with open(ziel, "wb") as aus:
                        shutil.copyfileobj(f, aus, 4 * 1024 * 1024)
                    if zeit[r]:
                        os.utime(ziel, (zeit[r], zeit[r]))
                    entpackt[r] = ziel
            except LESEFEHLER as e:          # was fehlt, meldet das Werkzeug als nicht lesbar
                print(f"⚠ {archiv}: nicht vollständig lesbar ({e!r})")
        yield Pfade(wurzel, entpackt, ordner)
    finally:
        shutil.rmtree(ordner, ignore_errors=True)
        try:
            basis.rmdir()                     # nur, wenn leer (kein anderer Lauf entpackt gerade)
        except OSError:
            pass


def je_stapel(platte_id, wurzel, zeilen, stapel=200):
    """Für Schritte, die Datei für Datei arbeiten (E4, F): liefert (zeile, Pfad im Dateisystem) je Zeile, deren erstes
    Feld der relpfad ist; Dateien in Archivdateien werden je Stapel bereitgestellt (in einem Zug je Archivdatei)."""
    zeilen = list(zeilen)
    for i in range(0, len(zeilen), stapel):
        teil = zeilen[i:i + stapel]
        with bereitstellen(platte_id, wurzel, [z[0] for z in teil]) as pfad:
            for z in teil:
                yield z, pfad(z[0])

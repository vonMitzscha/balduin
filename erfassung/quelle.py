"""Lesen aus einer Quelle, gleich ob Ordner oder Abbild (Entscheidung 09.11.2026, docs/plan.md).

Die Schritte bekommen eine Wurzel: den Mountpunkt eines Datenträgers, einen Ordner als Quelle oder, neu, ein Abbild
eines Mac-Datenträgers (HFS+, APFS), das erfassung/macplatte.py liest, ohne es einzuhängen. Wo ein Schritt eine Datei
öffnet, prüft oder auflistet, ruft er diese Funktionen; sie entscheiden je Wurzel, wie gelesen wird. Geschrieben wird
nie (harte Regel 1).

Ein Abbild bleibt für die Dauer des Laufs geöffnet (VOLUMES); welches Volume gemeint ist, steht in der Registrierung
(platte.volume_uuid zu quellordner = Pfad des Abbilds) oder wird mit anmelden() vorgegeben.
"""
import os
from pathlib import Path

from . import macplatte, system
from .basis import SYSTEMORDNER, db, nfc, quellpfad, relpfad_von

VOLUMES = {}           # str(Wurzel) → geöffnetes macplatte.Volume
WAHL = {}              # str(Wurzel) → (Kennung des Volumes, Passwort) für Abbilder mit mehreren oder verschlüsselten Volumes


def ist_abbild(wurzel):
    return macplatte.ist_abbild(wurzel)


def schluessel_von(wurzel):
    """Gleicher Schlüssel für jede Schreibweise einer Wurzel (Gerätepfade über pathlib bekommen unter Windows einen
    Trenner angehängt)."""
    return system.geraet_name(wurzel) or str(wurzel)


def anmelden(wurzel, uuid=None, passwort=None):
    """Welches Volume eines Abbilds gelesen wird (und mit welchem Passwort); schließt ein schon geöffnetes."""
    WAHL[schluessel_von(wurzel)] = (uuid, passwort)
    v = VOLUMES.pop(schluessel_von(wurzel), None)
    if v is not None:
        v.close()


def volume(wurzel):
    """Das geöffnete Volume eines Abbilds (beim ersten Zugriff geöffnet)."""
    schluessel = schluessel_von(wurzel)
    if schluessel not in VOLUMES:
        uuid, passwort = WAHL.get(schluessel, (None, None))
        if uuid is None and not system.ist_geraet(wurzel):
            try:
                with db() as con:
                    z = con.execute("SELECT volume_uuid FROM platte WHERE art = 'abbild' AND quellordner = ?",
                                    (nfc(schluessel),)).fetchone()
                uuid = z[0] if z and z[0] else None
            except Exception:              # ohne geöffnetes Projekt (z. B. beim Prüfen vor dem Registrieren)
                uuid = None
        VOLUMES[schluessel] = macplatte.oeffne_volume(schluessel, uuid=uuid, passwort=passwort)
    return VOLUMES[schluessel]


def schliessen():
    """Schließt alle geöffneten Abbilder (Ende eines Laufs, Tests)."""
    while VOLUMES:
        VOLUMES.popitem()[1].close()


def oeffnen(wurzel, relpfad):
    """Datei der Quelle zum Lesen (frei liegend, nicht in einer Archivdatei). FileNotFoundError, wenn es sie nicht gibt."""
    if ist_abbild(wurzel):
        return volume(wurzel).oeffnen(relpfad)
    return open(quellpfad(wurzel, relpfad), "rb")


def ist_datei(wurzel, relpfad):
    if ist_abbild(wurzel):
        return volume(wurzel).ist_datei(relpfad)
    return quellpfad(wurzel, relpfad).is_file()


def ist_ordner(wurzel, relpfad):
    if ist_abbild(wurzel):
        return relpfad in ("", ".") or volume(wurzel).ist_ordner(relpfad)
    return (quellpfad(wurzel, relpfad) if relpfad not in ("", ".") else Path(wurzel)).is_dir()


def stat(wurzel, relpfad):
    """(Größe, Änderungszeit) einer Datei der Quelle; FileNotFoundError, wenn es sie nicht gibt."""
    if ist_abbild(wurzel):
        return volume(wurzel).stat(relpfad)
    st = os.stat(quellpfad(wurzel, relpfad))
    return st.st_size, st.st_mtime


def nicht_utf8(name):
    """Liegt der Name nicht in UTF-8 vor? Python reicht solche Bytes als „Surrogate“ weiter (nur unter Linux möglich,
    z. B. alte FAT- oder ISO-Datenträger in Latin-1; macOS und Windows speichern immer gültige Namen)."""
    return any("\udc80" <= z <= "\udcff" for z in name)


def lesbar(text):
    """Text mit Surrogaten für Meldungen: nicht lesbare Bytes als �."""
    return text.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def eintraege(wurzel, umfang=None):
    """Alle Dateien der Quelle (ohne Verweise und Systemordner), für den Schnellscan:
    ("datei", relpfad, name, größe, Änderungszeit) oder ("fehler", relpfad, Meldung) für nicht Lesbares."""
    if ist_abbild(wurzel):
        v = volume(wurzel)
        v.fehler.clear()
        for relpfad, groesse, mtime in v.eintraege(umfang):
            yield "datei", relpfad, relpfad.rsplit("/", 1)[-1], groesse, mtime
        for relpfad, meldung in v.fehler:
            yield "fehler", relpfad, meldung
        return
    wurzel = Path(wurzel)
    stapel = [str(quellpfad(wurzel, u)) for u in reversed(umfang or [])] or [str(wurzel)]
    while stapel:
        ordner = stapel.pop()
        try:
            liste = list(os.scandir(ordner))
        except OSError as e:
            yield "fehler", relpfad_von(ordner, wurzel), repr(e)
            continue
        for e in liste:
            if nicht_utf8(e.name):
                # SQLite nimmt den Namen nicht an, und still ersetzt fände ihn niemand wieder: als Lesefehler melden
                # (Entscheidung 13.11.2026); bei einem Ordner fehlt so auch alles darin
                yield ("fehler", lesbar(relpfad_von(e.path, wurzel)),
                       f"Dateiname nicht in UTF-8 ({os.fsencode(e.name)!r}); Balduin kann ihn nicht sicher speichern. "
                       "Den Datenträger mit passender Zeichenkodierung lesen oder den Namen in einer Kopie ändern.")
                continue
            try:
                if e.is_symlink():
                    continue
                if e.is_dir():
                    if e.name not in SYSTEMORDNER:
                        stapel.append(e.path)
                    continue
                st = e.stat()
            except OSError as err:
                yield "fehler", relpfad_von(e.path, wurzel), repr(err)
                continue
            yield "datei", relpfad_von(e.path, wurzel), nfc(e.name), st.st_size, st.st_mtime


def unterordner(wurzel, rel=""):
    """[(Name, hat Unterordner)] der Ordner direkt unter rel, ohne Systemordner und versteckte; nur lesen."""
    if ist_abbild(wurzel):
        v = volume(wurzel)
        namen = [n for n in v.ordner(rel) if not n.startswith(".")]
        return [(n, any(not x.startswith(".") for x in v.ordner(f"{rel}/{n}" if rel else n))) for n in namen]
    ordner = quellpfad(wurzel, rel) if rel else Path(wurzel)
    liste = []
    for e in sorted(os.scandir(ordner), key=lambda e: nfc(e.name).lower()):
        if e.name.startswith(".") or e.name in SYSTEMORDNER or nicht_utf8(e.name) or e.is_symlink() or not e.is_dir():
            continue
        try:
            unter = any(x.is_dir() and not x.name.startswith(".") and not x.is_symlink() for x in os.scandir(e.path))
        except OSError:
            unter = False
        liste.append((nfc(e.name), unter))
    return liste

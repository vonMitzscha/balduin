"""C1 Schnellscan: liest nur das Inhaltsverzeichnis der Platte (Pfad, Name, Größe, Änderungsdatum)."""
from .basis import *  # noqa: F401,F403
from . import archivdateien, quelle


EINFUEGEN = ("INSERT OR REPLACE INTO schnellscan (platte_id, relpfad, name, groesse, mtime, lauf_id, archiv) "
             "VALUES (?,?,?,?,?,?,?)")


# Archivdateien, die noch kein Schnellscan geprüft hat (Platten, die vor dem 06.11.2026 gelesen wurden); solange es sie
# gibt, ist C offen. Gleiche Abfrage in tool/server.py (ARCHIVE_UNGEPRUEFT_SQL), Endungen wie archivdateien.art_von.
ARCHIVE_UNGEPRUEFT = """SELECT s.platte_id, COUNT(*) FROM schnellscan s
    WHERE s.archiv IS NULL AND NOT EXISTS (SELECT 1 FROM archivdatei a WHERE a.platte_id = s.platte_id AND a.relpfad = s.relpfad)
      AND (s.name LIKE '%_.zip' OR s.name LIKE '%_.tar' OR s.name LIKE '%_.tgz' OR s.name LIKE '%_.tbz'
           OR s.name LIKE '%_.tbz2' OR s.name LIKE '%_.txz' OR s.name LIKE '%_.gz' OR s.name LIKE '%_.bz2'
           OR s.name LIKE '%_.xz') AND substr(s.name, 1, 2) != '._'
      AND s.platte_id = ?"""


def archive_ungeprueft(platte_id):
    """Zahl der Archivdateien der Platte, die noch nicht aufgelöst oder als nicht auflösbar vermerkt sind."""
    with db() as con:
        z = con.execute(ARCHIVE_UNGEPRUEFT, (platte_id,)).fetchone()
    return z[1] if z else 0


# C1a Funktion für den Schnellscan
def schnellscan(platte_id, wurzel):
    """Durchläuft alle Ordner der Platte und speichert je Datei Pfad, Name, Größe, Änderungsdatum.
    Hat die Platte einen Umfang (platte.umfang, Entscheidung 05.11.2026), nur diese Ordner; die Pfade bleiben
    relativ zur Wurzel der Platte. Der Umfang kommt mit in scanlauf, damit „Fortsetzen“ ein Erweitern bemerkt.
    Die Wurzel kann auch ein Abbild eines Mac-Datenträgers sein (erfassung/quelle.py, Entscheidung 09.11.2026)."""
    wurzel = Path(wurzel)
    with db() as con:
        z = con.execute("SELECT umfang FROM platte WHERE platte_id = ?", (platte_id,)).fetchone()
        umfang = json.loads(z[0]) if z and z[0] else []
        lauf_id = con.execute("INSERT INTO scanlauf (platte_id, art, start, umfang) VALUES (?,?,?,?)",
                              (platte_id, "schnellscan", jetzt(), json.dumps(umfang, ensure_ascii=False))).lastrowid
        con.execute("DELETE FROM schnellscan WHERE platte_id = ?", (platte_id,))
        # Prüfsummen der Archivdateien bleiben, wenn Größe und Datum gleich sind (sonst liest D1 sie neu)
        alte_summen = {r: (g, m, s, d) for r, g, m, s, d in con.execute(
            "SELECT relpfad, groesse, mtime, sha256, md5 FROM archivdatei WHERE platte_id = ?", (platte_id,))}
        con.execute("DELETE FROM archivdatei WHERE platte_id = ?", (platte_id,))

    zeilen, fehler, archive = [], [], []
    anzahl = volumen = 0
    if umfang:
        print(f"Umfang: {', '.join(umfang)}")
    with db() as con:
        for eintrag in quelle.eintraege(wurzel, umfang):
            if eintrag[0] == "fehler":
                fehler.append((platte_id, lauf_id, eintrag[1], eintrag[2]))
                continue
            _, relpfad, name, groesse, mtime = eintrag
            art = archivdateien.art_von(name)
            if art:                                      # C2: Archivdatei wie einen Ordner auflösen
                try:
                    with quelle.oeffnen(wurzel, relpfad) as f:
                        inhalt, darin = archivdateien.auflisten(f, relpfad, art, mtime)
                    darin[-1].update(groesse=groesse, mtime=mtime)
                    archive += darin
                    for r, g, m in inhalt:
                        zeilen.append((platte_id, r, nfc(r.rsplit("/", 1)[-1]), g, m, lauf_id, relpfad))
                        anzahl += 1
                        volumen += g
                    continue
                except archivdateien.ArchivFehler as f:      # bleibt eine gewöhnliche Datei
                    archive.append(archivdateien.archivzeile(relpfad, art, f.status, f.meldung,
                                                             groesse=groesse, mtime=mtime))
                except OSError as err:
                    fehler.append((platte_id, lauf_id, relpfad, repr(err)))
                    continue
            zeilen.append((platte_id, relpfad, name, groesse, mtime, lauf_id, None))
            anzahl += 1
            volumen += groesse
            if len(zeilen) >= 10_000:
                con.executemany(EINFUEGEN, zeilen)
                con.commit()
                zeilen.clear()
                print(f"{anzahl:>10,} Dateien, {volumen / 1e9:8.1f} GB …", end="\r")

        con.executemany(EINFUEGEN, zeilen)
        con.executemany("INSERT INTO scanfehler VALUES (?,?,?,?)", fehler)
        for a in archive:
            alt = alte_summen.get(a["relpfad"])
            gleich = alt and (alt[0], alt[1]) == (a["groesse"], a["mtime"])
            con.execute("""INSERT OR REPLACE INTO archivdatei (platte_id, relpfad, art, status, meldung, dateien,
                               bytes_entpackt, groesse, mtime, sha256, md5, lauf_id, zeit)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (platte_id, a["relpfad"], a["art"], a["status"], a["meldung"], a["dateien"],
                         a["bytes_entpackt"], a["groesse"], a["mtime"], alt[2] if gleich else None,
                         alt[3] if gleich else None, lauf_id, jetzt()))
        con.execute("UPDATE scanlauf SET ende = ?, dateien = ?, bytes = ?, fehler = ? WHERE lauf_id = ?",
                    (jetzt(), anzahl, volumen, len(fehler), lauf_id))
    aufgeloest = sum(a["status"] == "aufgelöst" for a in archive)
    protokolliere("C1", platte_id, "schnellscan", "", f"{anzahl} Dateien, {len(fehler)} Fehler"
                  + (f", {aufgeloest} von {len(archive)} Archivdateien aufgelöst" if archive else ""))
    print(f"Fertig: {anzahl:,} Dateien, {volumen / 1e9:.1f} GB, {len(fehler)} Lesefehler.")
    return lauf_id

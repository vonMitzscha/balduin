"""D1 Dateiliste aus dem Schnellscan übernehmen, SHA-256 und MD5 jeder Datei berechnen."""
from itertools import groupby

from .basis import *  # noqa: F401,F403
from . import archivdateien
from .platte import oeffne

# D1a Funktionen: Dateiliste übernehmen, Prüfsummen berechnen
def dateiliste_abgleichen(platte_id):
    """Übernimmt die Dateien aus dem Schnellscan in die Tabelle datei. Neue Dateien kommen dazu,
    geänderte (Größe oder Datum anders) werden neu geprüft, nicht mehr vorhandene entfernt."""
    with db() as con:
        neu = con.execute("""
            INSERT INTO datei (platte_id, relpfad, groesse, mtime)
            SELECT platte_id, relpfad, groesse, mtime FROM schnellscan s
            WHERE platte_id = ? AND NOT EXISTS
                  (SELECT 1 FROM datei d WHERE d.platte_id = s.platte_id AND d.relpfad = s.relpfad)""",
            (platte_id,)).rowcount
        geaendert = con.execute("""
            UPDATE datei SET groesse = s.groesse, mtime = s.mtime,
                   sha256 = NULL, md5 = NULL, gehasht_am = NULL, hash_fehler = NULL,
                   puid = NULL, format = NULL, formatversion = NULL, mime = NULL,
                   sf_basis = NULL, sf_warnung = NULL, sf_fehler = NULL, sf_am = NULL, sf_quelle = NULL
            FROM schnellscan s
            WHERE datei.platte_id = ? AND s.platte_id = datei.platte_id AND s.relpfad = datei.relpfad
              AND (s.groesse != datei.groesse OR s.mtime != datei.mtime)""", (platte_id,)).rowcount
        weg = con.execute("""
            DELETE FROM datei WHERE platte_id = ? AND NOT EXISTS
                  (SELECT 1 FROM schnellscan s WHERE s.platte_id = datei.platte_id AND s.relpfad = datei.relpfad)""",
            (platte_id,)).rowcount
    if neu or geaendert or weg:
        protokolliere("D1", platte_id, "datei", "", f"{neu} neu, {geaendert} geändert, {weg} entfernt")
    print(f"Dateiliste: {neu:,} neu, {geaendert:,} geändert, {weg:,} entfernt.")


def pruefsummen(wurzel, relpfad, block=4 * 1024 * 1024):
    """Liest die Datei einmal und berechnet SHA-256 und MD5 zugleich."""
    with oeffne(wurzel, relpfad) as f:
        return summen_lesen(f, block)


def summen_lesen(f, block=4 * 1024 * 1024):
    """SHA-256, MD5 und gelesene Bytes eines offenen Dateiobjekts."""
    sha, md5 = hashlib.sha256(), hashlib.md5()
    gelesen = 0
    while stueck := f.read(block):
        sha.update(stueck)
        md5.update(stueck)
        gelesen += len(stueck)
    return sha.hexdigest(), md5.hexdigest(), gelesen


def summen_der_reihe_nach(wurzel, offen):
    """Prüfsummen der offenen Dateien [(relpfad, groesse, archiv)] in Leseordnung: frei liegende einzeln, die in
    einer Archivdatei je Archivdatei in einem Zug (Entscheidung 06.11.2026). Liefert (relpfad, groesse, Ergebnis
    oder Fehler)."""
    for archiv, gruppe in groupby(offen, key=lambda z: z[2]):
        gruppe = list(gruppe)
        if not archiv:
            for relpfad, groesse, _ in gruppe:
                try:
                    yield relpfad, groesse, pruefsummen(wurzel, relpfad)
                except OSError as e:
                    yield relpfad, groesse, e
            continue
        groessen = {r: g for r, g, _ in gruppe}
        try:
            for relpfad, f in archivdateien.durchlaufen(wurzel, archiv, groessen):
                try:
                    yield relpfad, groessen.pop(relpfad), summen_lesen(f)
                except archivdateien.LESEFEHLER as e:
                    yield relpfad, groessen.pop(relpfad, 0), OSError(repr(e))
        except archivdateien.LESEFEHLER as e:
            fehler = e
        else:
            fehler = None
        for relpfad, groesse in groessen.items():           # nicht (mehr) im Archiv gefunden
            yield relpfad, groesse, OSError(f"in {archiv} nicht lesbar: {fehler!r}" if fehler else
                                            f"in {archiv} nicht gefunden")


def archivdateien_pruefsummen(platte_id, wurzel):
    """Prüfsummen der Archivdateien selbst (für die Bestandsgeschichte: „entpackt aus … (MD5 …)“). Nicht aufgelöste
    sind gewöhnliche Dateien und haben ihre Prüfsumme schon in datei."""
    with db() as con:
        con.execute("""UPDATE archivdatei SET sha256 = d.sha256, md5 = d.md5 FROM datei d
                       WHERE archivdatei.platte_id = ? AND archivdatei.sha256 IS NULL AND d.platte_id = archivdatei.platte_id
                         AND d.relpfad = archivdatei.relpfad AND d.sha256 IS NOT NULL""", (platte_id,))
        offen = [r for (r,) in con.execute("SELECT relpfad FROM archivdatei WHERE platte_id = ? AND sha256 IS NULL "
                                           "ORDER BY relpfad", (platte_id,))]
    for relpfad in offen:
        try:
            sha, md5, _ = pruefsummen(wurzel, relpfad)
        except OSError as e:
            print(f"⚠ Archivdatei {relpfad}: {e}")
            continue
        with db() as con:
            con.execute("UPDATE archivdatei SET sha256 = ?, md5 = ? WHERE platte_id = ? AND relpfad = ?",
                        (sha, md5, platte_id, relpfad))


def vollscan_pruefsummen(platte_id, wurzel):
    """Berechnet die Prüfsummen aller Dateien, die noch keine haben. Unterbrechbar und fortsetzbar."""
    with db() as con:
        offen = con.execute("""SELECT d.relpfad, d.groesse, s.archiv FROM datei d
                                   LEFT JOIN schnellscan s ON s.platte_id = d.platte_id AND s.relpfad = d.relpfad
                                   WHERE d.platte_id = ? AND d.sha256 IS NULL
                                   ORDER BY coalesce(s.archiv, ''), d.relpfad""", (platte_id,)).fetchall()
    if not offen:
        print(f"Für {platte_id} haben alle Dateien Prüfsummen.")
        archivdateien_pruefsummen(platte_id, wurzel)
        return
    gesamt = sum(g for _, g, _ in offen)
    print(f"Offen: {len(offen):,} Dateien, {gesamt / 1e9:.1f} GB.")

    with db() as con:
        lauf_id = con.execute("INSERT INTO scanlauf (platte_id, art, start) VALUES (?,?,?)",
                              (platte_id, "pruefsummen", jetzt())).lastrowid
    erledigt = volumen = fehler = 0
    start = letzte_ausgabe = time.monotonic()
    schaetzer = Restzeit(gesamt)
    unterbrochen = False
    with db() as con:
        try:
            for relpfad, groesse, ergebnis in summen_der_reihe_nach(wurzel, offen):
                if isinstance(ergebnis, OSError):
                    fehler += 1
                    con.execute("UPDATE datei SET hash_fehler = ? WHERE platte_id = ? AND relpfad = ?",
                                (repr(ergebnis), platte_id, relpfad))
                else:
                    sha, md5, gelesen = ergebnis
                    hinweis = None if gelesen == groesse else f"gelesen {gelesen} statt {groesse} Bytes"
                    con.execute("UPDATE datei SET sha256 = ?, md5 = ?, gehasht_am = ?, hash_fehler = ? "
                                "WHERE platte_id = ? AND relpfad = ?",
                                (sha, md5, jetzt(), hinweis, platte_id, relpfad))
                erledigt += 1
                volumen += groesse
                if time.monotonic() - letzte_ausgabe > 2:
                    con.commit()
                    letzte_ausgabe = time.monotonic()
                    rest = schaetzer.text(volumen)
                    fortschritt(volumen / max(gesamt, 1),
                                f"{erledigt:,}/{len(offen):,} Dateien · {volumen / 1e9:.1f}/{gesamt / 1e9:.1f} GB · "
                                f"{schaetzer.tempo / 1e6:.0f} MB/s · {rest}")
        except KeyboardInterrupt:
            unterbrochen = True
        con.execute("UPDATE scanlauf SET ende = ?, dateien = ?, bytes = ?, fehler = ? WHERE lauf_id = ?",
                    (jetzt(), erledigt, volumen, fehler, lauf_id))
    if not unterbrochen:
        archivdateien_pruefsummen(platte_id, wurzel)
    protokolliere("D1", platte_id, "pruefsummen", "",
                  f"{erledigt} Dateien, {fehler} Fehler" + (", unterbrochen" if unterbrochen else ""))
    dauer = (time.monotonic() - start) / 60
    if unterbrochen:
        print(f"\nUnterbrochen nach {erledigt:,} Dateien. Beim nächsten Start geht es mit den übrigen weiter.")
    else:
        print(f"\nFertig: {erledigt:,} Dateien, {volumen / 1e9:.1f} GB in {dauer:.0f} Min., {fehler} Lesefehler.")


def zuruecksetzen(platte_id):
    """Neu analysieren: Prüfsummen, Formate und Metadaten dieser Platte verwerfen; D1, D2 und E bestimmen sie neu.
    Die Dateiliste und alle Entscheidungen bleiben. Andere Platten, die ein Ergebnis von hier übernommen haben, behalten es
    (gleicher Inhalt, gleiches Ergebnis)."""
    with db() as con:
        n = con.execute("""UPDATE datei SET sha256 = NULL, md5 = NULL, gehasht_am = NULL, hash_fehler = NULL,
                               puid = NULL, format = NULL, formatversion = NULL, mime = NULL, sf_basis = NULL,
                               sf_warnung = NULL, sf_fehler = NULL, sf_am = NULL, sf_quelle = NULL
                           WHERE platte_id = ?""", (platte_id,)).rowcount
        m = con.execute("DELETE FROM metadaten WHERE platte_id = ?", (platte_id,)).rowcount
    protokolliere("D1", platte_id, "neu analysieren", f"Prüfsummen und Formate von {n} Dateien, Metadaten von {m} Dateien",
                  "verworfen, werden neu bestimmt")
    print(f"Neu analysieren: Prüfsummen und Formate von {n:,} Dateien und Metadaten von {m:,} Dateien verworfen.")

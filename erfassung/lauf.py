"""Hintergrundlauf der Erfassung für das Tool Balduin: führt die Schritte B bis I für eine Platte nacheinander aus.

Das Tool (tool/server.py) startet ihn in einer eigenen Sitzung; er läuft weiter, wenn Browser oder Terminal zugehen:
    python -m erfassung.lauf erfassen --projekt … --lauf 12
Den Auftrag (Platte, Mountpunkt, Etikett …) liest er aus der Tabelle lauf, den Fortschritt je Schritt schreibt er in
lauf_schritt, alle Ausgaben in logs/erfassung_<lauf>_<platte>.log. Abbrechen: Das Tool setzt lauf.abbrechen = 1 und
schickt auf dem Mac SIGINT (wie Ctrl+C); unter Windows liest die Abbruchwache des Laufs die Marke und unterbricht
ihn an derselben Stelle (Entscheidung 09.11.2026). Der laufende Schritt hört an seiner nächsten Prüfstelle auf, alles
bis dahin bleibt gespeichert. Ohne Mountpunkt (Fortsetzen, Platte nicht angeschlossen) entfallen die Schritte mit Platte (B bis F).
Auftrag „schritte“: nur diese Schritte (Kürzel), samt Pflicht-Folgeschritten (FOLGESCHRITTE, z. B. G → H); jeder macht
wie beim Fortsetzen nur, was fehlt. Sind Schritte mit Platte gewählt, läuft die Registrierung (B) als Prüfung mit.
Ist ein Lauf zu Ende, startet er den ältesten eingereihten (Status „eingereiht“, vom Tool angelegt). „Bestand aus Anton
holen“ hat eine eigene Spur und läuft neben einer Analyse (Entscheidung 05.11.2026).
Auftrag „umfang“: nur diese Ordner der Platte lesen (kann nur wachsen); „art“: "ordner" = gewöhnlicher Ordner als Quelle
(Entscheidungen 05.11.2026). Auftrag „modus“: leer = neue Platte; "fortsetzen" = jeder Schritt macht nur, was noch fehlt (ein vollständiger Schnellscan
wird nicht wiederholt); "neu" = Prüfsummen, Formate, Metadaten und Virenscan dieser Platte neu bestimmen.
Läufe der Art „anton“ (ohne Datenträger) holen den Bestand aus Anton über die API und gleichen danach alle Platten ab.
Läufe der Art „vorlauf“ (ohne Datenträger) rechnen die gewählten Schritte des Vorlaufs (Paket vorlauf/) für die Dateien in
vorlauf_umfang (vom Tool vor dem Start geschrieben); Auftrag {"schritte": ["V5", …], "umfang": "uebernommen"|"alles"}.
Läufe der Art „export“ (Modul 4, Paket export/) sichern die Datenbank (X0), schreiben die geplanten Pakete als tar auf
die Ablage (X1, mit eingehängter Platte nur lesend) und prüfen sie dort nach (X2); Auftrag {"platte_id", "mountpunkt"}.

Dazu kurze Abfragen, die das Tool abwartet und als JSON liest:
    python -m erfassung.lauf datentraeger …                angeschlossene Datenträger und nächste freie Kennung
    python -m erfassung.lauf einhaengen --mountpunkt …    schreibgeschützt neu einhängen
    python -m erfassung.lauf angaben --daten '{…}'          Etikett, Notiz, Kopie von, Foto einer Platte ändern
    python -m erfassung.lauf herausnehmen --daten '{…}'     Platte aus dem Projekt nehmen oder wieder aufnehmen
    python -m erfassung.lauf quellordner --daten '{…}'      Ordner als Quelle "pruefen", "verlegen"; "umfang"
                                                            prüfen; "unterordner" einer Quelle für den Umfang (Entscheidungen 05.11.2026)
    python -m erfassung.lauf dashboard                      Daten für Dashboard und Bericht (erfassung/dashboard.py)
    python -m erfassung.lauf projekt                        Name, Einstellungen und Orte des Projekts (Vorschaubilder)
    python -m erfassung.lauf einstellungen --daten '{…}'    Einstellungen des Projekts ändern (projekt.json)
    python -m erfassung.lauf anton --daten '{"aktion": …}'  Anton: "pruefen" (Verbindung), "token_entfernen",
                                                            "token_speichern" (Token kommt über stdin, nie als Argument),
                                                            "einheit" (Bestandsbox), "stufen" (Werteliste, /api/levels-of-description),
                                                            "felder" (Notizfelder, /api/import/mapping)
    python -m erfassung.lauf export --daten '{"aktion": …}' Modul 4: "pruefen" (geplante Pakete gegen das Schema),
                                                            "importformat" (GET /api/import-format), "lieferschein"
    python -m erfassung.lauf sprachmodell --daten '{…}'     Sprachmodell auf Abruf: "modelle" oder "vorschlag" für
                                                            {platte, pfad, dateien} (vorlauf/sprachmodell.py, nur lokal)
    python -m erfassung.lauf anlegen --daten '{…}'          neues Projekt anlegen (Assistent; ohne --projekt)
    python -m erfassung.lauf arbeitsplatten                 Datenträger, die als Arbeitsplatte taugen (ohne --projekt)
Einstellungen (Virenscan, Personen, Arbeitsplatte, Film- und PDF-Vorschau, Reserve) kommen aus projekt.json; --arbeitsplatte und --volumes
überschreiben nur für Tests.
"""
import _thread
import argparse
import io
import signal
import sys
import threading
import traceback
from contextlib import redirect_stdout

from . import basis
from .basis import *  # noqa: F401,F403
from . import anton, archiv, duplikate, formate, metadaten, personen, platte, pruefsummen, quelle, schnellscan, texte, \
    uebersicht, vergleich, virenscan, vorschau


class Uebersprungen(Exception):
    """Ein Schritt entfällt mit Begründung, z. B. weil die Arbeitsplatte nicht angeschlossen ist."""


# ---------- Schritte; a = Auftrag ----------

def schritt_b(a):
    mountpunkt = Path(a["mountpunkt"])
    art = a.get("art") or platte.art_der_quelle(a["platte_id"]) or None
    # Ordner und Abbilder lassen sich nicht schreibgeschützt einhängen; Balduin liest dort nur (Entscheidungen 05.11. und
    # 09.11.2026; die Leseschicht öffnet ein Abbild nur zum Lesen)
    if art not in ("ordner", "abbild", "macplatte") and not platte.bereit(mountpunkt):
        # ohne Schreibschutz nur nach Zustimmung (Rückfrage in Balduin; unter Windows geht es nicht anders, 13.11.2026)
        if not a.get("beschreibbar_ok"):
            raise RuntimeError("Der Datenträger ist beschreibbar eingehängt. Erst „Schreibgeschützt einhängen“ wählen "
                               "oder dem Lesen ohne Schreibschutz zustimmen.")
        platte.ohne_schreibschutz_gelesen(a["platte_id"])
    platte.registrieren(a["platte_id"], mountpunkt, a.get("notiz", ""), a.get("etikett", ""), a.get("foto"),
                        a.get("gleiche_uuid_ok", False), umfang=a.get("umfang"), art=art)
    with db() as con:
        alt = con.execute("SELECT kopie_von FROM platte WHERE platte_id = ?", (a["platte_id"],)).fetchone()[0]
    if a.get("kopie_von") and a["kopie_von"] != alt:
        vergleich.kopie_vermerken({a["platte_id"]: a["kopie_von"]})


def schritt_c(a):
    if a.get("modus") == "fortsetzen" and "C" not in (a.get("schritte") or []):    # ausdrücklich gewählt: neu lesen
        # gilt nur, wenn er mit dem heutigen Umfang gelesen wurde (Umfang erweitert: neu lesen)
        with db() as con:
            z = con.execute("SELECT umfang FROM scanlauf WHERE platte_id = ? AND art = 'schnellscan' "
                            "AND ende IS NOT NULL ORDER BY lauf_id DESC LIMIT 1", (a["platte_id"],)).fetchone()
        # und nur, wenn er schon jede Archivdatei aufgelöst hat (Platten, die vor dem 06.11.2026 gelesen wurden)
        if z is not None and (json.loads(z[0]) if z[0] else []) == platte.umfang_lesen(a["platte_id"]) \
                and not schnellscan.archive_ungeprueft(a["platte_id"]):
            raise Uebersprungen("vollständiger Schnellscan liegt vor")
    schnellscan.schnellscan(a["platte_id"], Path(a["mountpunkt"]))


def schritt_d1(a):
    platte.angeschlossene_platte_pruefen(a["platte_id"], Path(a["mountpunkt"]))
    if a.get("modus") == "neu":
        pruefsummen.zuruecksetzen(a["platte_id"])
    pruefsummen.dateiliste_abgleichen(a["platte_id"])
    pruefsummen.vollscan_pruefsummen(a["platte_id"], Path(a["mountpunkt"]))


def schritt_d2(a):
    formate.formate_uebernehmen(a["platte_id"])
    formate.siegfried(a["platte_id"], Path(a["mountpunkt"]))


def schritt_d3(a):
    if not P.virenscan:
        raise Uebersprungen("im Projekt ausgeschaltet")
    virenscan.virenscan(a["platte_id"], Path(a["mountpunkt"]), neu=a.get("modus") == "neu")


def schritt_e(a):
    metadaten.metadaten_uebernehmen(a["platte_id"])
    metadaten.metadaten_lesen(a["platte_id"], Path(a["mountpunkt"]))
    metadaten.bestes_datum()


def schritt_e4(a):
    texte.texte_lesen(a["platte_id"], Path(a["mountpunkt"]))


def schritt_f(a):
    if P.arbeitsplatte is not None and not P.arbeitsplatte.exists():
        raise Uebersprungen(f"Arbeitsplatte {P.arbeitsplatte} nicht angeschlossen; später mit „Fortsetzen“ nachholen")
    vorschau.arbeitsplatte_einbinden(Path(a["mountpunkt"]))
    platte.angeschlossene_platte_pruefen(a["platte_id"], Path(a["mountpunkt"]))
    vorschau.vorschauen_erzeugen(a["platte_id"], Path(a["mountpunkt"]), neu_versuchen=a.get("modus") == "neu")


def schritt_f5(a):
    # nur Vorschaubilder: läuft auch ohne Quellplatte, braucht aber die Arbeitsplatte
    if not P.personen:
        raise Uebersprungen("im Projekt ausgeschaltet")
    if P.arbeitsplatte is not None and not P.arbeitsplatte.exists():
        raise Uebersprungen(f"Arbeitsplatte {P.arbeitsplatte} nicht angeschlossen; später mit „Fortsetzen“ nachholen")
    personen.personen_erkennen(a["platte_id"])


def schritt_g(a):
    duplikate.exakte_duplikate()
    duplikate.formatvarianten()
    duplikate.beinahe_gleiche(4)


def schritt_g5b(a):
    # Fortsetzen: ein Abruf, der seit Beginn des ersten Laufs („seit“) fertig wurde, gilt; sonst holen (eine
    # unterbrochene Abfrage setzt am selben Tag bei der nächsten fehlenden Seite fort)
    heute = P.anton / f"anton_dateien_{datetime.now():%Y-%m-%d}_api.csv"
    fertig = heute.exists() and a.get("seit") and datetime.fromtimestamp(heute.stat().st_mtime).isoformat() >= a["seit"]
    anton.anton_laden("api", neu_abrufen=not (a.get("modus") == "fortsetzen" and fertig))


def schritt_g5(a):
    with db() as con:
        stand = con.execute("SELECT stand FROM anton_stand WHERE aktuell = 1").fetchone()
    if stand is None:
        raise Uebersprungen("noch kein Bestand aus Anton geladen („Bestand aus Anton holen“)")
    anton.anton_abgleichen()


def schritt_h(a):
    archiv.archivfaehigkeit()
    archiv.leitdateien()


def schritt_i(a):
    if not a.get("uebersicht"):
        raise Uebersprungen("nicht gewählt")
    uebersicht.dashboard_erstellen()


# Kürzel (intern, auch in Log und Protokoll), Name (im Tool, gleich wie in tool/web/erfassung.js), Funktion
SCHRITTE = [("B", "Registrierung", schritt_b), ("C", "Verzeichnis", schritt_c),
            ("D1", "Prüfsummen", schritt_d1), ("D2", "Formate", schritt_d2),
            ("D3", "Virenscan", schritt_d3), ("E", "Metadaten", schritt_e), ("E4", "Texte", schritt_e4),
            ("F", "Vorschaubilder", schritt_f), ("F5", "Personen", schritt_f5), ("G", "Duplikate", schritt_g),
            ("G5", "Anton-Abgleich", schritt_g5), ("H", "Archivfähigkeit", schritt_h),
            ("I", "Bericht (HTML)", schritt_i)]
MIT_PLATTE = {"C", "D1", "D2", "D3", "E", "E4", "F"}     # lesen die Platte; Registrierung prüft dann, ob sie da ist
# Pflicht-Folgeschritte einer Auswahl: G schreibt die Duplikatgruppen neu und löscht dabei die Leitdateien, die erst H
# setzt. Gleiche Angabe in tool/server.py und tool/web/erfassung.js (folgt)
FOLGESCHRITTE = {"G": ["H"]}


def auswahl_vervollstaendigen(schritte):
    """Gewählte Schritte samt Pflicht-Folgeschritten; leer oder None = alle Schritte."""
    gewaehlt = set(schritte or [])
    for k in list(gewaehlt):
        gewaehlt.update(FOLGESCHRITTE.get(k, []))
    if gewaehlt & MIT_PLATTE:
        gewaehlt.add("B")                                # prüft, ob die richtige Platte angeschlossen ist
    return gewaehlt
# Lauf der Art „anton“: Bestand holen (G5b über die API), dann alle Platten abgleichen
SCHRITTE_ANTON = [("G5b", "Bestand aus Anton holen", schritt_g5b), ("G5", "Anton-Abgleich", schritt_g5)]


# Lauf der Art „vorlauf“: Schritte aus vorlauf/ (nur Datenbank, Vorschaubilder, öffentliches Anton-Vokabular)
def schritt_v5(a):
    from vorlauf import pfade
    pfade.pfade_und_namen(a.get("umfang", ""))


def schritt_v7(a):
    from vorlauf import metadaten as vorlauf_metadaten
    vorlauf_metadaten.metadaten_verteilen(a.get("umfang", ""))


def schritt_v8(a):
    from vorlauf import normdaten
    normdaten.normdaten_abgleichen(a.get("umfang", ""))


def schritt_v10(a):
    from vorlauf import verwandte
    verwandte.verwandte_finden(a.get("umfang", ""))


def schritt_v3(a):
    from vorlauf import sujet
    sujet.sujet_erkennen(a.get("umfang", ""))


# V3 nach V8: braucht das Anton-Vokabular, das V8 holt
SCHRITTE_VORLAUF = [("V5", "Pfade und Namen", schritt_v5), ("V7", "Metadaten verteilen", schritt_v7),
                    ("V8", "Normdaten abgleichen", schritt_v8), ("V3", "Sujet", schritt_v3),
                    ("V10", "Verwandte finden", schritt_v10)]
# Lauf der Art „export“ (Modul 4, Paket export/): Auftrag {"platte_id", "mountpunkt" (leer: nur Ebenenpakete)};
# geplant hat der Server (Tabellen paket, paket_eintrag); geschrieben wird nur auf die Ablage (P.export)
def export_version():
    """Version des Importformats: höchstens, was die Instanz liest (GET /api/import-format), sonst die eigene höchste."""
    from export import bauen
    try:
        reads = bauen.importformat().get("reads")
        print(f"Anton liest das Importformat bis {reads}.")
    except RuntimeError as fehler:
        print(f"⚠ {fehler}; es gilt die höchste Version in vorgaben/anton_import/.")
        reads = None
    return bauen.schema_version(reads)


def schritt_x0(a):
    from export import bauen
    bauen.ablage()                                    # angeschlossen? sonst gar nicht erst anfangen
    bauen.datenbank_sichern(a.get("lauf_id"))


def schritt_x1(a):
    from export import bauen
    mountpunkt = a.get("mountpunkt")
    if mountpunkt:
        bauen.platte_pruefen(a["platte_id"], mountpunkt, a.get("beschreibbar_ok"))
    ids = bauen.zu_bauen(a.get("platte_id") if mountpunkt else None)
    if not ids:
        raise Uebersprungen("nichts zu schreiben" + ("" if mountpunkt else " ohne Datenträger"))
    version = export_version()
    fehler, gebaut = [], 0
    try:
        for pid in ids:
            try:
                bauen.paket_bauen(pid, mountpunkt, version)
                gebaut += 1
            except (ValueError, bauen.Abweichung) as f:   # dieses Paket stoppt, die übrigen gehen weiter
                print(f"✗ {f}")
                fehler.append(str(f))
            except RuntimeError as f:                     # Platz auf der Ablage reicht nicht: aufhören
                print(f"⚠ {f}")
                fehler.append(str(f))
                break
    finally:
        try:
            bauen.lieferschein()
        except (RuntimeError, OSError):
            pass
    print(f"{gebaut} von {len(ids)} Paketen geschrieben" + (f", {len(fehler)} mit Fehler" if fehler else "") + ".")
    if fehler:
        raise RuntimeError(f"{len(fehler)} Paket(e) nicht geschrieben: {fehler[0]}")


def schritt_x2(a):
    from export import bauen
    ids = bauen.zu_pruefen()
    if not ids:
        raise Uebersprungen("nichts nachzuprüfen")
    schlecht = [pid for pid in ids if bauen.paket_nachpruefen(pid)]
    bauen.lieferschein()
    if schlecht:
        raise RuntimeError(f"{len(schlecht)} Paket(e) beim Nachprüfen fehlerhaft und gelöscht; neu schreiben.")


SCHRITTE_EXPORT = [("X0", "Datenbank sichern", schritt_x0), ("X1", "Pakete schreiben", schritt_x1),
                   ("X2", "Pakete nachprüfen", schritt_x2)]
LAUF_NAMEN = {"anton": "Bestand aus Anton", "vorlauf": "Vorlauf", "export": "Export"}


# ---------- Fortschritt in die Datenbank ----------

def schreiben(sql, werte, warten=30):
    """Eine Änderung an lauf/lauf_schritt. Mit kurzem warten (Fortschritt) wird bei gesperrter Datenbank ausgelassen:
    Der Schritt selbst hält dann gerade eine Schreibsperre, der nächste Stand kommt eine Sekunde später."""
    try:
        with closing(sqlite3.connect(P.db_pfad, timeout=warten)) as con, con:
            con.execute(sql, werte)
        return True
    except sqlite3.OperationalError:
        if warten >= 1:
            raise
        return False


class Melder(io.TextIOBase):
    """Ersetzt stdout und stderr: Zeilen gehen ins Log, die letzte Zeile und der Anteil (fortschritt) in lauf_schritt.
    Höchstens eine Meldung je Sekunde; was dazwischen zurückgehalten wurde, liefert ein Takt im Hintergrund nach,
    damit das Tool auch dann den neuesten Stand zeigt, wenn der Schritt eine Weile nichts mehr ausgibt."""

    def __init__(self, lauf_id, log):
        self.lauf_id, self.log = lauf_id, log
        self.schritt, self.anteil, self.text, self.rest = None, None, "", ""
        self.gemeldet, self.offen = 0.0, False
        self.sperre = threading.Lock()          # Takt und Schritt melden nicht gleichzeitig
        threading.Thread(target=self.takt, daemon=True).start()

    def takt(self):
        while True:
            time.sleep(1)
            if self.offen:
                self.melden()

    def schritt_setzen(self, schritt):
        """Neuer Schritt (oder None am Ende eines Schritts): ab jetzt gilt nur noch dessen Stand."""
        with self.sperre:
            self.schritt, self.anteil, self.text, self.offen = schritt, None, "", False

    def write(self, s):
        for teil in re.split(r"([\r\n])", s):
            if teil == "\n":
                self.log.write(self.rest + "\n")
                self.log.flush()
                self.zeile(self.rest)
                self.rest = ""
            elif teil == "\r":                       # Fortschrittszeile: nur anzeigen, nicht ins Log
                self.zeile(self.rest)
                self.rest = ""
            else:
                self.rest += teil
        return len(s)

    def zeile(self, text):
        text = re.sub(r"^\[[█░]+\]\s*\d+\s*%\s*·\s*", "", text.strip())   # Balken aus fortschritt() weglassen
        if text:
            self.text = text
            self.melden()

    def fortschritt(self, anteil, text):
        self.anteil = anteil
        if text:                    # Text und Anteil zusammen, sonst zeigt der Balken den neuen Anteil zum alten Text
            self.text = text
        self.melden()

    def melden(self, sofort=False):
        self.offen = True
        with self.sperre:
            if self.schritt and (sofort or time.monotonic() - self.gemeldet >= 1):
                if schreiben("UPDATE lauf_schritt SET anteil = ?, text = ? WHERE lauf_id = ? AND schritt = ?",
                             (self.anteil, self.text[:500], self.lauf_id, self.schritt), warten=0.2):
                    self.gemeldet, self.offen = time.monotonic(), False

    def flush(self):
        self.log.flush()


ABBRUCH = False         # SIGINT vom Tool erhalten; gilt auch, wenn ein Schritt das Unterbrechen selbst abfängt
ENDE = False            # der Lauf schreibt seinen Endstand: ein spätes Unterbrechen setzt nur noch die Marke


def unterbrechen(signum, frame):
    global ABBRUCH
    ABBRUCH = True
    if not ENDE:
        raise KeyboardInterrupt


def abbruchwache(db_pfad, lauf_id, takt=1.0):
    """Liest im Hintergrund die Marke lauf.abbrechen; ist sie gesetzt, unterbricht sie den Lauf wie Ctrl+C (ruft
    unterbrechen() im Hauptfaden). So bricht ein Lauf auch unter Windows ab, wo das Tool kein Signal schicken kann.
    Antwort: Ereignis zum Beenden der Wache (set())."""
    fertig = threading.Event()

    def wache():
        while not fertig.wait(takt):
            try:
                with closing(sqlite3.connect(db_pfad, timeout=5)) as con:
                    gesetzt = con.execute("SELECT abbrechen FROM lauf WHERE lauf_id = ?", (lauf_id,)).fetchone()
            except sqlite3.Error:
                continue                                  # Datenbank gesperrt: beim nächsten Takt wieder
            if gesetzt and gesetzt[0] and not fertig.is_set():
                if not ABBRUCH:
                    _thread.interrupt_main(signal.SIGINT)
                return
    threading.Thread(target=wache, name="abbruchwache", daemon=True).start()
    return fertig


def abbrechen_verlangt(lauf_id):
    """Abbruch per Signal (sofort) oder per Marke in der Datenbank (falls das Signal den Prozess nicht erreicht hat)."""
    if ABBRUCH:
        return True
    with closing(sqlite3.connect(P.db_pfad, timeout=30)) as con:
        return bool(con.execute("SELECT abbrechen FROM lauf WHERE lauf_id = ?", (lauf_id,)).fetchone()[0])


def leseschicht_vorbereiten(a, passwort=None):
    """Abbild oder Mac-Platte: das Volume für diesen Lauf anmelden, für jeden Schritt (auch Fortsetzen und Packen, deren
    Auftrag keine Volume-UUID trägt): die gewählte beim Registrieren, sonst die registrierte; das Passwort eines
    verschlüsselten Volumes nur im Speicher (13.11.2026)."""
    if not a.get("mountpunkt") or not a.get("platte_id"):
        return
    art = a.get("art") or platte.art_der_quelle(a["platte_id"]) or None
    if art not in ("abbild", "macplatte"):
        return
    uuid = a.get("volume_uuid")
    if not uuid:
        with db() as con:
            z = con.execute("SELECT volume_uuid FROM platte WHERE platte_id = ?", (a["platte_id"],)).fetchone()
        uuid = z[0] if z and z[0] else None
    quelle.anmelden(a["mountpunkt"], uuid, passwort)


def passwort_lesen(a):
    """Passwort eines verschlüsselten Volumes: kommt nur über stdin (der Server reicht es weiter; nie in Auftrag, Log,
    Datenbank oder Prozessliste). RuntimeError, wenn es fehlt."""
    if not a.get("mit_passwort"):
        return None
    passwort = (sys.stdin.readline() if sys.stdin else "").rstrip("\r\n")
    if not passwort:
        raise RuntimeError("Das Passwort des verschlüsselten Datenträgers fehlt. Den Lauf in Balduin neu starten und das "
                           "Passwort eingeben (es wird nicht gespeichert).")
    return passwort


def erfassen(lauf_id):
    """Führt den Auftrag des Laufs aus. Ein Fehler oder Abbruch hält den Lauf an; spätere Schritte bauen aufeinander auf."""
    global ENDE
    signal.signal(signal.SIGINT, unterbrechen)
    with db() as con:
        art, auftrag = con.execute("SELECT art, auftrag FROM lauf WHERE lauf_id = ?", (lauf_id,)).fetchone()
    a = {**json.loads(auftrag), "lauf_id": lauf_id}
    try:
        passwort, passwort_fehlt = passwort_lesen(a), None
    except RuntimeError as e:
        passwort, passwort_fehlt = None, str(e)
    schritte = {"anton": SCHRITTE_ANTON, "vorlauf": SCHRITTE_VORLAUF, "export": SCHRITTE_EXPORT}.get(art, SCHRITTE)
    ohne_platte = art in LAUF_NAMEN
    logdatei = P.logs / f"erfassung_{lauf_id}_{a.get('platte_id') or art}.log"
    schreiben("UPDATE lauf SET status = 'läuft', pid = ?, start = ?, log = ? WHERE lauf_id = ?",
              (os.getpid(), jetzt(), str(logdatei.relative_to(P.ordner)), lauf_id))
    with db() as con:
        con.executemany("INSERT OR REPLACE INTO lauf_schritt (lauf_id, schritt, titel, status) VALUES (?,?,?,'wartet')",
                        [(lauf_id, k, t) for k, t, _ in schritte])
    status, meldung = "fertig", None
    with open(logdatei, "a", encoding="utf-8") as log:
        melder = Melder(lauf_id, log)
        basis.MELDER = melder.fortschritt
        sys.stdout = sys.stderr = melder
        print(f"Lauf {lauf_id}: {a.get('platte_id') or LAUF_NAMEN.get(art, art)}" + (f" unter {a['mountpunkt']}" if a.get("mountpunkt") else " (ohne Datenträger)")
              + (f", Schritte {', '.join(a['schritte'])}" if a.get("schritte") else "") + f", Projekt {P.ordner}")
        wache = abbruchwache(P.db_pfad, lauf_id)          # erst hier: ein Unterbrechen landet im try darunter
        try:
            leseschicht_vorbereiten(a, passwort)            # Abbild, Mac-Platte: Volume (und Passwort) für alle Schritte
            gewaehlt = (set(a.get("schritte") or []) if art == "vorlauf" else
                        set() if ohne_platte else auswahl_vervollstaendigen(a.get("schritte")))
            for kuerzel, titel, funktion in schritte:
                if gewaehlt and kuerzel not in gewaehlt:
                    schreiben("UPDATE lauf_schritt SET status = 'übersprungen', text = 'nicht gewählt' "
                              "WHERE lauf_id = ? AND schritt = ?", (lauf_id, kuerzel))
                    continue
                if not ohne_platte and not a.get("mountpunkt") and kuerzel in MIT_PLATTE | {"B"}:
                    schreiben("UPDATE lauf_schritt SET status = 'übersprungen', text = ? WHERE lauf_id = ? AND schritt = ?",
                              ("Platte nicht angeschlossen; später mit „Alles Offene fortsetzen“ nachholen",
                               lauf_id, kuerzel))
                    continue
                if abbrechen_verlangt(lauf_id):             # Abbruch zwischen zwei Schritten
                    status, meldung = "abgebrochen", f"vor {kuerzel} {titel}"
                    break
                print(f"\n=== {kuerzel} {titel} ===")
                schreiben("UPDATE lauf_schritt SET status = 'läuft', start = ? WHERE lauf_id = ? AND schritt = ?",
                          (jetzt(), lauf_id, kuerzel))
                melder.schritt_setzen(kuerzel)
                ergebnis, text = "fertig", None
                try:
                    if passwort_fehlt:                      # verschlüsselt, aber kein Passwort über stdin
                        raise RuntimeError(passwort_fehlt)
                    funktion(a)
                    if abbrechen_verlangt(lauf_id):         # die Schritte fangen das Unterbrechen selbst ab
                        ergebnis = "abgebrochen"
                except Uebersprungen as e:
                    ergebnis, text = "übersprungen", str(e)
                except KeyboardInterrupt:
                    ergebnis = "abgebrochen"
                except Exception as e:
                    traceback.print_exc()
                    ergebnis, text = "Fehler", f"{e}" if isinstance(e, (ValueError, RuntimeError, OSError)) else f"{type(e).__name__}: {e}"
                anteil, letzte = melder.anteil, melder.text
                melder.schritt_setzen(None)
                schreiben("UPDATE lauf_schritt SET status = ?, ende = ?, anteil = ?, text = ? WHERE lauf_id = ? AND schritt = ?",
                          (ergebnis, jetzt(), 1.0 if ergebnis == "fertig" else anteil,
                           (text or letzte)[:500], lauf_id, kuerzel))
                print(f"→ {ergebnis}" + (f": {text}" if text else ""))
                if ergebnis in ("abgebrochen", "Fehler"):
                    status, meldung = ergebnis, f"{kuerzel} {titel}: {text or ergebnis}"
                    break
        except KeyboardInterrupt:                           # zwischen zwei Schritten unterbrochen
            status, meldung = "abgebrochen", "zwischen zwei Schritten"
        finally:
            ENDE = True
            wache.set()
            quelle.schliessen()                         # offene Abbilder (unter Windows sonst gesperrt)
            sys.stdout, sys.stderr = sys.__stdout__, sys.__stderr__
            basis.MELDER = None
            schreiben("UPDATE lauf SET status = ?, ende = ?, meldung = ? WHERE lauf_id = ?",
                      (status, jetzt(), meldung, lauf_id))
            log.write(f"\nLauf {lauf_id}: {status}" + (f" ({meldung})" if meldung else "") + "\n")
    naechsten_starten()


# ---------- Warteschlange ----------

# Je Spur den ältesten eingereihten Lauf übernehmen, wenn in ihr keiner wartet oder läuft; die Bedingung steht in
# derselben Anweisung, damit Tool und beendeter Lauf nicht beide denselben (oder je einen) starten. Zwei Spuren
# (Entscheidung 05.11.2026): „anton“ (ohne Platte, nur Netz) neben allen übrigen. Gleiche Anweisung in tool/server.py.
NAECHSTEN_UEBERNEHMEN = """
    UPDATE lauf SET status = 'wartet' WHERE lauf_id IN (
        SELECT MIN(l.lauf_id) FROM lauf l WHERE l.status = 'eingereiht'
        AND NOT EXISTS (SELECT 1 FROM lauf x WHERE x.status IN ('wartet', 'läuft') AND (x.art = 'anton') = (l.art = 'anton'))
        GROUP BY l.art = 'anton')
    RETURNING lauf_id"""


def naechsten_starten():
    """Nach dem Ende eines Laufs (auch Fehler oder Abbruch) den nächsten eingereihten in eigener Sitzung starten."""
    with closing(sqlite3.connect(P.db_pfad, timeout=60)) as con, con:
        uebernommen = con.execute(NAECHSTEN_UEBERNEHMEN).fetchall()
    for z in uebernommen:
        system.hintergrund_starten(system.lauf_befehl("erfassen", *projekt_argumente(), "--lauf", z[0]), cwd=CODE)


def projekt_argumente():
    """Projekt und Test-Überschreibungen für einen weiteren Lauf, wie dieser gestartet wurde."""
    return (["--projekt", str(P.ordner), "--volumes", str(P.volumes)]
            + (["--arbeitsplatte", str(P.arbeitsplatte_test)] if P.arbeitsplatte_test else []))


# ---------- Abfragen für das Tool ----------

def arbeitsplatte_angaben():
    return {"arbeitsplatte": str(P.arbeitsplatte) if P.arbeitsplatte else "",
            "arbeitsplatte_da": P.arbeitsplatte is None or P.arbeitsplatte.exists(),
            # Ablage der Exportpakete (Modul 4): Ordner, Wurzel (Datenträger oder Projekt), ob angeschlossen
            "export_ablage": {**P.einstellungen["export"]["ablage"], "unterordner": P.einstellungen["export"]["ablage"].get("ordner", ""),
                              "ordner": str(P.export) if P.export else "", "wurzel": str(P.export_wurzel or ""),
                              "da": bool(P.export_wurzel and P.export_wurzel.is_dir())}}


def datentraeger(andere=()):
    """andere: Ordner weiterer Projekte; dort registrierte Platten werden gemeldet (nur gelesen)."""
    registriert = platte.registrierte_platten()
    return {"naechste": platte.naechste_kennung(registriert), "kennung": P.kennung,
            "angeschlossen": platte.angeschlossene(registriert, platte.in_anderen_projekten(andere)), "ordner": platte.quellordner_liste(),
            "mac_geraete": mac_geraete(), "lange_pfade_aus": system.lange_pfade() is False,
            **arbeitsplatte_angaben()}


def mac_geraete():
    """Physische Platten ohne Laufwerksbuchstaben, die noch nicht registriert sind (Windows: vermutlich Mac-Platten;
    Entscheidung 09.11.2026). Gelesen werden nur Angaben zum Gerät, ohne Administratorrechte."""
    with db() as con:
        bekannt = [s for (s,) in con.execute("SELECT geraet FROM platte WHERE art = 'macplatte' AND geraet != ''")]
    return [{k: d.get(k) for k in ("geraet", "modell", "seriennummer", "anschluss", "groesse")}
            for d in system.physische_datentraeger()
            if not d["laufwerksbuchstaben"] and not any(platte.passt_zum_geraet(s, d) for s in bekannt)]


def passwort_pruefen(daten):
    """Öffnet das verschlüsselte Volume einmal zur Probe, ohne Lauf und ohne etwas zu schreiben. Das Passwort kommt
    nur über stdin (wie beim Lauf). Volume: das gewählte (Registrieren) oder das registrierte. Antwort {ok, meldung}."""
    passwort = (sys.stdin.readline() if sys.stdin else "").rstrip("\r\n")
    if not passwort:
        raise ValueError("Bitte das Passwort eingeben.")
    wurzel, uuid = daten["wurzel"], daten.get("volume_uuid")
    if not uuid and daten.get("platte_id"):
        with db() as con:
            z = con.execute("SELECT volume_uuid FROM platte WHERE platte_id = ?", (daten["platte_id"],)).fetchone()
        uuid = z[0] if z and z[0] else None
    quelle.anmelden(wurzel, uuid, passwort)
    try:
        quelle.volume(wurzel)
    except ValueError as e:
        return {"ok": False, "meldung": str(e)}
    finally:
        quelle.schliessen()
        quelle.WAHL.clear()                               # das Passwort nicht länger im Speicher halten
    return {"ok": True, "meldung": "Das Passwort stimmt."}


def quellordner_aktion(daten):
    """Ordner als Quelle und Umfang (Entscheidungen 05.11.2026): "pruefen" (taugt der Ordner?), "verlegen" (neuer Ort
    einer verschobenen Ordner-Quelle), "unterordner" (Ordner einer Quelle für die Wahl des Umfangs, nur lesen)."""
    aktion = daten.get("aktion")
    if daten.get("volume_uuid") and daten.get("wurzel"):  # Abbild mit mehreren Volumes: das gewählte (13.11.2026)
        quelle.anmelden(daten["wurzel"], daten["volume_uuid"])
    if aktion == "pruefen":
        p = platte.quellordner_pruefen(daten["pfad"], daten.get("platte_id"))
        return {"pfad": str(p), "name": p.name}
    if aktion == "verlegen":
        return platte.quelle_verlegen(daten["platte_id"], daten["pfad"])
    if aktion == "umfang":
        return {"umfang": platte.umfang_pruefen(daten["platte_id"], daten["umfang"], Path(daten["wurzel"]))}
    if aktion == "unterordner":
        return {"ordner": platte.unterordner(daten["wurzel"], daten.get("pfad", ""))}
    if aktion == "macgeraet_pruefen":                    # Mac-Platte an einem Windows-Rechner (09.11.2026)
        return platte.macgeraet_pruefen(daten["geraet"])
    if aktion == "passwort_pruefen":                     # verschlüsseltes Volume vor dem Lauf prüfen (Feedback 14.11.2026)
        return passwort_pruefen(daten)
    if aktion == "abbild_pruefen":                       # Abbild eines Mac-Datenträgers (Entscheidung 09.11.2026)
        p, vs = platte.abbild_pruefen(daten["pfad"])
        return {"pfad": str(p), "name": p.name, "volumes": [{k: v[k] for k in ("name", "dateisystem", "uuid", "gesperrt",
                                                                               "groesse")} for v in vs]}
    raise ValueError(f"unbekannte Aktion {aktion!r}")


def projekt_angaben():
    with db() as con:
        platten = con.execute("SELECT COUNT(*) FROM platte").fetchone()[0]
    return {"ordner": str(P.ordner), "name": P.name, "einstellungen": P.einstellungen, "vorschauen": str(P.vorschauen),
            "platten": platten, "anton_token": anton.token_quelle(), **arbeitsplatte_angaben()}


def anton_aktion(daten):
    """Token im Schlüsselbund ablegen oder entfernen, Verbindung prüfen (Zahnrad des Projekts vorn in der Kopfleiste);
    eine Anton-Einheit für eine Bestandsbox holen (Modul 3)."""
    aktion = daten.get("aktion")
    if aktion == "token_speichern":
        anton.token_speichern(sys.stdin.read())
    elif aktion == "token_entfernen":
        anton.token_entfernen()
    elif aktion == "einheit":                            # Modul 3: Bestandsbox laden (nur lesend)
        return anton.einheit_holen(daten.get("kennung"))
    elif aktion == "stufen":                            # Modul 3: Stufen für neue Unterverzeichnungseinheiten
        return anton.stufen_holen()
    elif aktion == "felder":                            # Modul 3: weitere Anton-Felder (Notizfelder) für den Editor
        return anton.felder_holen()
    elif aktion != "pruefen":
        raise ValueError(f"unbekannte Aktion {aktion!r}")
    return anton.verbindung_pruefen() if aktion == "pruefen" else {"token": anton.token_quelle()}


def export_aktion(daten):
    """Modul 4 ohne Hintergrundlauf: geplante Pakete gegen das Schema prüfen, Importformat abfragen, Lieferschein."""
    from export import bauen
    aktion = daten.get("aktion")
    if aktion == "pruefen":
        return {"fehler": bauen.pruefen(daten.get("pakete"))}
    if aktion == "importformat":
        a = bauen.importformat()
        try:                                   # fehlt die Abfrage bei einer Instanz, bleibt es beim Hinweis
            richtlinie, richtlinie_fehler = bauen.formatrichtlinie(), ""
        except RuntimeError as fehler:
            richtlinie, richtlinie_fehler = None, str(fehler)
        return {"reads": a.get("reads"), "version": bauen.schema_version(a.get("reads")),
                "formatrichtlinie": richtlinie, "formatrichtlinie_fehler": richtlinie_fehler}
    if aktion == "lieferschein":
        return {"ordner": str(bauen.lieferschein())}
    raise ValueError(f"unbekannte Aktion {aktion!r}")


def einhaengen(mountpunkt):
    mountpunkt = Path(mountpunkt)
    if not system.ist_datentraeger(mountpunkt, P.volumes) or mountpunkt == P.arbeitsplatte:
        raise ValueError(f"{mountpunkt} ist kein Quelldatenträger unter {P.volumes}")
    return {"mountpunkt": platte.nur_lesend_einhaengen(mountpunkt)}


def main():
    parser = argparse.ArgumentParser(description="Erfassung im Hintergrund (von Balduin gestartet)")
    parser.add_argument("befehl", choices=["erfassen", "datentraeger", "einhaengen", "angaben", "herausnehmen",
                                                     "dashboard", "projekt", "einstellungen", "anlegen", "arbeitsplatten", "anton",
                                                     "sprachmodell", "export", "quellordner"])
    parser.add_argument("--projekt", type=Path, help="Projektordner; ohne Angabe das zuletzt im Tool geöffnete")
    parser.add_argument("--arbeitsplatte", type=Path, help="nur Tests: Datenträger für Vorschaubilder statt dem aus projekt.json")
    parser.add_argument("--volumes", type=Path, default=VOLUMES)
    parser.add_argument("--lauf", type=int)
    parser.add_argument("--mountpunkt", type=Path)
    parser.add_argument("--daten", type=json.loads, default={})
    args = parser.parse_args()
    with redirect_stdout(sys.stderr):                        # stdout bleibt frei für die JSON-Antwort
        if args.befehl == "arbeitsplatten":                  # ohne Projekt (Assistent)
            antwort = platte.arbeitsplatten_angebot(args.volumes)
        elif args.befehl == "anlegen":
            d = args.daten
            projekt_anlegen(d.pop("ordner"), d)
            antwort = projekt_angaben()
        else:
            oeffnen(args.projekt, arbeitsplatte=args.arbeitsplatte, volumes=args.volumes)
        if args.befehl in ("arbeitsplatten", "anlegen"):
            pass
        elif args.befehl == "erfassen":
            return erfassen(args.lauf)
        elif args.befehl == "dashboard":
            from . import dashboard
            antwort = dashboard.daten()
        elif args.befehl == "angaben":
            d = args.daten
            antwort = platte.angaben_aendern(d["platte_id"], d.get("etikett"), d.get("notiz"), d.get("kopie_von"), d.get("foto"))
        elif args.befehl == "projekt":
            antwort = projekt_angaben()
        elif args.befehl == "einstellungen":
            d = dict(args.daten)
            auf = d.pop("vorschaubilder_auf", None)          # nachträglich eine Arbeitsplatte (Entscheidung 04.11.2026)
            ablage = d.pop("export_ablage", None)           # Ablage der Exportpakete (Entscheidung 05.11.2026)
            if auf:
                vorschaubilder_verlegen(auf)
            if ablage:
                export_ablage_setzen(ablage)
            antwort = {**(einstellungen_aendern(d) if d else {"geaendert": []}), **projekt_angaben()}
            if auf:
                antwort["geaendert"] = ["vorschaubilder"] + antwort["geaendert"]
            if ablage:
                antwort["geaendert"] = ["export.ablage"] + antwort["geaendert"]
        elif args.befehl == "anton":
            antwort = anton_aktion(args.daten)
        elif args.befehl == "export":
            antwort = export_aktion(args.daten)
        elif args.befehl == "sprachmodell":
            from vorlauf import sprachmodell
            d = args.daten
            antwort = (sprachmodell.modelle() if d.get("aktion") == "modelle"
                       else sprachmodell.vorschlag(d["platte"], d["pfad"], d["dateien"]))
        elif args.befehl == "quellordner":
            antwort = quellordner_aktion(args.daten)
        elif args.befehl == "herausnehmen":
            antwort = platte.aus_projekt_nehmen(args.daten["platte_id"], bool(args.daten.get("herausnehmen", True)))
        else:
            antwort = (datentraeger(args.daten.get("andere", [])) if args.befehl == "datentraeger"
                       else einhaengen(args.mountpunkt))
    print(json.dumps(antwort, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()

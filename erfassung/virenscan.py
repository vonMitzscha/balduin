"""D3 Virenscan mit ClamAV: jeden Inhalt (SHA-256) einmal prüfen, Funde nur markieren."""
import itertools
import socket
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from .basis import *  # noqa: F401,F403
from . import archivdateien
from .platte import angeschlossene_platte_pruefen

# D3b Funktionen: ClamAV vorbereiten, jeden Inhalt einmal prüfen
CLAMAV_GRENZE = 2**31 - 1     # Bytes; größere Dateien kann ClamAV nicht prüfen
STAPEL = 500                  # Dateien je Stapel (Dateien in Archivdateien werden je Stapel entpackt)
MEDIEN_ENDUNGEN = {"mov", "mp4", "m4v", "avi", "mpg", "mpeg", "mxf", "wmv", "mts", "m2ts", "3gp", "flv", "mkv", "vob", "dv",
                   "wav", "aif", "aiff", "mp3", "m4a", "wma"}


def clamav_programm(name):
    """Pfad zu einem ClamAV-Programm (system.werkzeug_pfad sucht auch dort, wo Homebrew clamd ablegt: sbin)."""
    if (pfad := system.werkzeug_pfad(name)):
        return pfad
    raise RuntimeError("ClamAV fehlt. " + system.installationshinweis("clamav"))


def eigene_signaturen(programm):
    """Ordner für Signaturen und Einstellung, wenn ClamAV mit Balduin geliefert ist (bin/ im Paket): der Programmordner
    ist dort nicht beschreibbar, also im Datenordner der App (Entscheidung 14.11.2026). Sonst None (Vorgaben von
    ClamAV aus Homebrew, dem Installer oder der Paketverwaltung)."""
    try:
        Path(programm).resolve().relative_to((system.CODE / "bin").resolve())
    except ValueError:
        return None
    return system.app_daten() / "clamav"


def datenbank_option(programm):
    """Zusatz für clamscan: Signaturen aus dem eigenen Ordner lesen (nur bei mitgeliefertem ClamAV)."""
    ordner = eigene_signaturen(programm)
    return [f"--database={ordner / 'db'}"] if ordner else []


def datenbank_zeile(programm):
    """Zeile für clamd.conf: Signaturen aus dem eigenen Ordner lesen (nur bei mitgeliefertem ClamAV)."""
    ordner = eigene_signaturen(programm)
    return f"DatabaseDirectory {ordner / 'db'}\n" if ordner else ""


def clamav_stand():
    """„ClamAV 1.5.4/28168/Thu Oct 29 07:24:16 2026“ = Programm/Signaturversion/Datum; ohne Signaturen nur „ClamAV 1.5.4“."""
    clamscan = clamav_programm("clamscan")
    return subprocess.run([clamscan, *datenbank_option(clamscan), "--version"], capture_output=True, text=True).stdout.strip()


def signaturen_auffrischen(hoechstens_tage=1):
    """Holt mit freshclam neue Signaturen, wenn die vorhandenen älter als hoechstens_tage sind, und gibt den Stand zurück.
    Beim ersten Mal wird die Einstellung von freshclam aus der mitgelieferten Vorlage angelegt (offizieller Spiegel)."""
    stand = clamav_stand()
    teile = stand.split("/")
    alter = (datetime.now() - datetime.strptime(teile[2], "%a %b %d %H:%M:%S %Y")).days if len(teile) == 3 else None
    if alter is not None and alter < hoechstens_tage:
        return stand
    if not system.signaturen_selbst_auffrischen():
        # Linux: die Signaturen pflegt der Dienst clamav-freshclam der Distribution (Entscheidung 13.11.2026)
        if len(teile) < 3:
            raise RuntimeError("Keine Virensignaturen vorhanden. Unter Linux holt sie der Dienst clamav-freshclam; "
                               "ihn einrichten (" + system.installationshinweis("freshclam") + ") und starten.")
        return stand
    freshclam = clamav_programm("freshclam")
    befehl = [freshclam]
    if (eigen := eigene_signaturen(freshclam)):
        # mitgeliefertes ClamAV: eigene Einstellung mit Signaturen im Datenordner der App
        (eigen / "db").mkdir(parents=True, exist_ok=True)
        konf = eigen / "freshclam.conf"
        konf.write_text(f"DatabaseDirectory {eigen / 'db'}\nDatabaseMirror database.clamav.net\n", encoding="utf-8")
        befehl.append(f"--config-file={konf}")
    else:
        konf, vorlage = system.clamav_konfiguration(freshclam)
        if not konf.exists() and vorlage.exists():
            # die Vorlage ist mit der Zeile „Example“ gesperrt; ohne sie gelten die Standardwerte
            konf.write_text("".join(z for z in vorlage.read_text(encoding="utf-8").splitlines(True) if not z.startswith("Example")), encoding="utf-8")
    print("Signaturen auffrischen (freshclam) …")
    ergebnis = subprocess.run(befehl, capture_output=True, text=True)
    neu = clamav_stand()
    if ergebnis.returncode != 0:
        if len(neu.split("/")) < 3:
            raise RuntimeError("Keine Signaturen vorhanden und freshclam scheitert:\n" + (ergebnis.stdout + ergebnis.stderr)[-1500:])
        print(f"⚠ freshclam scheitert; es gelten die vorhandenen Signaturen ({alter} Tage alt).\n"
              + letzte_fehler(ergebnis.stdout + ergebnis.stderr))
    return neu


def letzte_fehler(text, zeilen=3):
    """Die letzten Fehlerzeilen einer Ausgabe von clamd oder freshclam (ohne Fehlerzeilen die letzten Zeilen)."""
    alle = [z.strip() for z in text.splitlines() if z.strip()]
    fehler = [z for z in alle if "ERROR" in z or "Error" in z] or alle
    return " · ".join(fehler[-zeilen:])


class Clamd:
    """Startet den ClamAV-Dienst clamd für die Dauer eines Laufs: with Clamd(4, log) as c: c.pruefe(pfad).
    Die Signaturen werden einmal geladen; clamd prüft so viele Dateien zugleich, wie Anfragen offen sind (höchstens parallel).
    Einstellung und Socket liegen in einem temporären Ordner auf dem Rechner; clamd liest die Dateien nur. Erreichbar
    ist clamd über einen Unix-Socket oder, wo es den nicht gibt (Windows), über TCP nur auf 127.0.0.1."""

    def __init__(self, parallel, log):
        self.ordner = tempfile.mkdtemp(prefix="clamd_")
        self.dienst = system.dienst_adresse(self.ordner)
        konf = Path(self.ordner) / "clamd.conf"
        clamd = clamav_programm("clamd")
        konf.write_text(f"{self.dienst['konf']}{datenbank_zeile(clamd)}Foreground yes\nMaxThreads {parallel}\n"
                        f"MaxFileSize {CLAMAV_GRENZE}\nMaxScanSize 4000M\n"
                        "AlertExceedsMax yes\nAlertEncrypted yes\nDisableCache yes\n", encoding="utf-8")
        self.prozess = subprocess.Popen([clamd, "-c", str(konf)], stdout=log, stderr=log)
        frist = time.monotonic() + 180
        try:
            while True:        # das Laden der Signaturen dauert einige Sekunden
                try:
                    if self.anfrage(b"zPING\0") == b"PONG":
                        break
                except OSError:
                    pass
                if self.prozess.poll() is not None or time.monotonic() > frist:
                    raise RuntimeError(self.startfehler(log))
                time.sleep(0.5)
        except BaseException:      # auch beim Unterbrechen während des Ladens clamd wieder beenden
            self.beenden()
            raise

    def startfehler(self, log):
        """Meldung, warum clamd nicht startet: die letzten Fehlerzeilen und die Logdatei mit allen Meldungen."""
        log.flush()
        try:
            text = Path(log.name).read_text(errors="replace", encoding="utf-8")
        except (OSError, TypeError):
            text = ""
        return (f"clamd startet nicht. {letzte_fehler(text)}\n"
                f"Alle Meldungen von clamd: logs/{Path(str(getattr(log, 'name', ''))).name}. "
                "Steht dort „Malformed database“ oder „Incorrect digital signature“, ClamAV erneuern "
                f"({system.installationshinweis('clamav')}) und danach „freshclam“ ausführen.")

    def anfrage(self, befehl):
        with socket.socket(self.dienst["familie"]) as s:
            s.connect(self.dienst["adresse"])
            s.sendall(befehl)
            antwort = b""
            while stueck := s.recv(65536):
                antwort += stueck
        return antwort.rstrip(b"\0")

    def pruefe(self, pfad):
        """Antwort von clamd ohne den vorangestellten Pfad: „OK“, „Eicar-Test-Signature FOUND“ oder „… ERROR“."""
        roh = os.fsencode(pfad)
        antwort = self.anfrage(b"zSCAN " + roh + b"\0")
        antwort = antwort[len(roh) + 2:] if antwort.startswith(roh + b": ") else antwort.rsplit(b": ", 1)[-1]
        return antwort.decode("utf-8", "replace")

    def beenden(self):
        if self.prozess.poll() is None:
            self.prozess.terminate()
            try:
                self.prozess.wait(10)
            except subprocess.TimeoutExpired:
                self.prozess.kill()
        shutil.rmtree(self.ordner, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *fehler):
        self.beenden()


def befund_aus(antwort):
    """Ordnet die Antwort von clamd einem Befund zu: (befund, meldung)."""
    if antwort == "OK":
        return "sauber", None
    if antwort.endswith(" FOUND"):
        name = antwort[:-6]
        if name.startswith("Heuristics.Limits.Exceeded"):
            return "nicht geprüft", f"Prüfgrenze überschritten ({name.rsplit('.', 1)[-1]}), nur teilweise geprüft"
        if name.startswith("Heuristics.Encrypted"):
            return "nicht geprüft", f"verschlüsselt ({name.rsplit('.', 1)[-1]})"
        return "Fund", name
    return "Fehler", antwort or "keine Antwort von clamd"


def virenscan(platte_id, wurzel, parallel=4, medien=True, max_mb=2048, neu=False):
    """Prüft jeden Inhalt dieser Platte, der noch keinen Befund hat, einmal mit ClamAV (je SHA-256 eine Datei).
    Befunde gelten für alle Dateien mit diesem Inhalt, auch auf anderen Platten. Unterbrechbar und fortsetzbar."""
    verworfen = 0
    with db() as con:
        if neu:
            verworfen = con.execute("DELETE FROM virenscan WHERE sha256 IN (SELECT sha256 FROM datei WHERE platte_id = ?)",
                                    (platte_id,)).rowcount
        offen = pd.read_sql("""SELECT relpfad, sha256, groesse, mime FROM datei d
                               WHERE platte_id = ? AND sha256 IS NOT NULL AND groesse > 0 AND NOT EXISTS
                                     (SELECT 1 FROM virenscan v WHERE v.sha256 = d.sha256 AND v.befund != 'Fehler')
                               ORDER BY relpfad""", con, params=(platte_id,)).drop_duplicates("sha256")
    if verworfen:
        protokolliere("D3", platte_id, "virenscan", f"{verworfen} Befunde", "verworfen, wird neu geprüft")
    medium = (offen.mime.fillna("").str.match(r"(video|audio)/")
              | offen.relpfad.map(lambda r: os.path.splitext(r)[1].lower().lstrip(".") in MEDIEN_ENDUNGEN))
    zu_gross = offen.groesse > CLAMAV_GRENZE
    ausgelassen = ~zu_gross & ((offen.groesse > max_mb * 1024**2) | (medium & (not medien)))
    pruefen = offen[~zu_gross & ~ausgelassen]
    gb = lambda df: df.groesse.sum() / 1e9
    print(f"Ohne Befund: {len(offen):,} Inhalte ({gb(offen):.1f} GB). Davon zu prüfen {len(pruefen):,} ({gb(pruefen):.1f} GB)"
          + (f", über 2 GB (kann ClamAV nicht prüfen) {zu_gross.sum():,}" if zu_gross.any() else "")
          + (f", per Einstellung ausgelassen {ausgelassen.sum():,} ({gb(offen[ausgelassen]):.1f} GB)" if ausgelassen.any() else "")
          + ".")
    if pruefen.empty and not zu_gross.any():
        print(f"Für {platte_id} ist nichts mehr zu prüfen.")
        return

    stand = signaturen_auffrischen() if len(pruefen) else clamav_stand()
    sql = "INSERT OR REPLACE INTO virenscan VALUES (?,?,?,?,?,?)"
    with db() as con:
        con.executemany(sql, [(s, "nicht geprüft", "größer als 2 GB, kann ClamAV nicht prüfen", f"{platte_id}:{r}", stand,
                               jetzt()) for r, s in zip(offen.relpfad[zu_gross], offen.sha256[zu_gross])])
        lauf_id = con.execute("INSERT INTO scanlauf (platte_id, art, start) VALUES (?,?,?)",
                              (platte_id, "virenscan", jetzt())).lastrowid
    zaehler = Counter({"nicht geprüft": int(zu_gross.sum())}) if zu_gross.any() else Counter()
    funde = []
    erledigt = volumen = 0
    gesamt = max(pruefen.groesse.sum(), 1)
    unterbrochen = False
    logdatei = P.logs / f"clamav_{platte_id}_{datetime.now():%Y-%m-%d_%H%M}.log"
    if len(pruefen):
        angeschlossene_platte_pruefen(platte_id, wurzel)
        print(f"Prüfe mit {stand}, {parallel} Dateien zugleich …")
    start = letzte = time.monotonic()
    schaetzer = Restzeit(gesamt)
    with open(logdatei, "w", encoding="utf-8") as log, db() as con:
        clamd = Clamd(parallel, log) if len(pruefen) else None
        pool = ThreadPoolExecutor(parallel)
        alle = list(pruefen[["relpfad", "sha256", "groesse"]].itertuples(index=False))
        try:
            # je Stapel: Dateien in Archivdateien kurz ins Projekt entpacken (Entscheidung 06.11.2026); der Stapel
            # wird erst gelöscht, wenn alle seine Prüfungen fertig sind
            for i in range(0, len(alle), STAPEL):
                teil = alle[i:i + STAPEL]
                with archivdateien.bereitstellen(platte_id, wurzel, [z.relpfad for z in teil]) as pfad:
                    warteschlange = iter(teil)
                    laufend = {}

                    def nachlegen():   # immer etwas mehr Aufträge als Prüfungen offen halten, damit clamd nie wartet
                        for z in itertools.islice(warteschlange, 2 * parallel - len(laufend)):
                            laufend[pool.submit(clamd.pruefe, pfad(z.relpfad))] = z

                    nachlegen()
                    while laufend:
                        fertig, _ = wait(laufend, return_when=FIRST_COMPLETED)
                        for auftrag in fertig:
                            relpfad, sha, groesse = laufend.pop(auftrag)
                            try:
                                befund, meldung = befund_aus(auftrag.result())
                            except OSError as e:
                                befund, meldung = "Fehler", repr(e)
                            con.execute(sql, (sha, befund, meldung, f"{platte_id}:{relpfad}", stand, jetzt()))
                            zaehler[befund] += 1
                            if befund == "Fund":
                                funde.append((relpfad, sha, meldung))
                            erledigt += 1
                            volumen += groesse
                        nachlegen()
                        if time.monotonic() - letzte > 2:
                            con.commit()
                            letzte = time.monotonic()
                            rest = schaetzer.text(volumen)
                            fortschritt(volumen / gesamt, f"{erledigt:,}/{len(pruefen):,} Inhalte · "
                                        f"{schaetzer.tempo / 1e6:.0f} MB/s · {rest} · Funde {zaehler['Fund']}")
        except KeyboardInterrupt:
            unterbrochen = True
        finally:
            if clamd:
                clamd.beenden()        # zuerst clamd beenden, dann warten laufende Prüfungen nicht bis zum Ende
            pool.shutdown(wait=True, cancel_futures=True)
        con.execute("UPDATE scanlauf SET ende = ?, dateien = ?, bytes = ?, fehler = ? WHERE lauf_id = ?",
                    (jetzt(), erledigt, volumen, zaehler["Fehler"], lauf_id))
    zusammen = ", ".join(f"{b} {zaehler[b]}" for b in ("sauber", "Fund", "nicht geprüft", "Fehler") if zaehler[b])
    protokolliere("D3", platte_id, "virenscan", "", f"{erledigt + int(zu_gross.sum())} Inhalte: {zusammen or 'keine'}; "
                  f"ausgelassen {int(ausgelassen.sum())}; {stand}" + (", unterbrochen" if unterbrochen else ""))
    for relpfad, sha, meldung in funde:
        protokolliere("D3", f"{platte_id}:{relpfad}", "virenfund", "", meldung)
    dauer = (time.monotonic() - start) / 60
    print(f"\n{'Unterbrochen' if unterbrochen else 'Fertig'}: {erledigt:,} Inhalte, {volumen / 1e9:.1f} GB in {dauer:.0f} Min. "
          f"({zusammen or 'nichts geprüft'}).")
    if funde:
        with db() as con:
            orte = pd.read_sql(f"SELECT platte_id, relpfad, sha256 FROM datei WHERE sha256 IN "
                               f"({','.join('?' * len(funde))})", con, params=[s for _, s, _ in funde])
        print(f"⚠ {len(funde)} Inhalte mit Fund, an {len(orte)} Stellen (alle Platten). Nicht öffnen; E und F lassen sie aus:")
        zeige(orte.merge(pd.DataFrame(funde, columns=["_", "sha256", "meldung"])[["sha256", "meldung"]], on="sha256")
                    [["platte_id", "relpfad", "meldung"]])
    if unterbrochen:
        print("Beim nächsten Start geht es mit den übrigen Inhalten weiter.")
    print("Meldungen von clamd:", logdatei.relative_to(P.ordner))

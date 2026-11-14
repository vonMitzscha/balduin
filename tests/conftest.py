"""Gemeinsame Vorbereitung aller Tests (Entscheidung 05.11.2026, docs/plan.md).

Sicherheit zuerst, bevor irgendein Code von Balduin geladen wird:
- Schutzwache (tests/schutz/): Zugriffe auf /Volumes brechen ab, im Testprozess und in allen Python-Unterprozessen.
- HOME, zuletzt.json und Schlüsselbund zeigen auf einen eigenen Temp-Ordner; der Anton-Token ist der des Nachbaus.
- Anton ist ein Nachbau auf 127.0.0.1 (tests/hilfen/anton_nachbau.py), nie die echte Instanz.

Fixtures (Bausteine, die Tests als Argument anfordern):
- testplatten      die vier Testplatten (werkzeuge/testplatten_erzeugen.py) in einem Temp-Ordner, mit Fingerabdruck
- anton            der nachgebaute Anton-Server
- analysiert       ein Projekt, in dem HD01 und HD02 durch B–I gelaufen sind und der Bestand aus Anton geholt ist
                   (einmal je Testlauf; Tests verändern es nicht, sondern arbeiten auf einer Kopie)
- projekt          Kopie von „analysiert“ je Testdatei, frei veränderbar
- balduin          der Server (tool/server.py) auf der Kopie, mit Sitzungs-Cookie; Methoden get/post/roh
- leeres_projekt   ein frisch angelegtes Projekt ohne Platten, im Testprozess geöffnet (für schnelle Tests)
"""
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from types import SimpleNamespace

import pytest

CODE = Path(__file__).resolve().parent.parent
SCHUTZ = CODE / "tests" / "schutz"
PYTHON = sys.executable                               # das Python des venv, mit dem pytest läuft

# ---------- Umgebung: vor jedem Import von Balduin-Code ----------
BASIS = Path(tempfile.mkdtemp(prefix="balduin-tests-")).resolve()
SCHUTZ_PROTOKOLL = BASIS / "schutzwache.log"
_mpl = os.environ.get("MPLCONFIGDIR") or str(Path.home() / ".matplotlib")   # nur der Schriftcache von matplotlib
(BASIS / "home").mkdir()
SCHUTZ_PROTOKOLL.touch()

sys.path.insert(0, str(CODE / "tests"))
from hilfen.anton_nachbau import AntonNachbau, TOKEN  # noqa: E402

os.environ.update({
    "HOME": str(BASIS / "home"),                       # ~/Library/… (zuletzt.json) landet im Temp-Ordner
    "APPDATA": str(BASIS / "home" / "AppData"),        # Windows: %APPDATA%\\Balduin (zuletzt.json) ebenso
    "ANTON_TOKEN": TOKEN,                              # Token des Nachbaus; der echte Schlüsselbund wird nie gefragt
    "ANTON_SCHLUESSELBUND": str(BASIS / "test.keychain"),
    "BALDUIN_SCHUTZ_PROTOKOLL": str(SCHUTZ_PROTOKOLL),
    "PYTHONPATH": os.pathsep.join([str(SCHUTZ), str(CODE), *filter(None, [os.environ.get("PYTHONPATH")])]),
    "MPLCONFIGDIR": _mpl,
    "PLOTLY_RENDERER": "json",                        # keine Diagramme im Browser
    "BROWSER": "true",                                # webbrowser.open öffnet nichts
    "BALDUIN_REGION": "CH",                           # Systemregion fest (Anzeige „kassieren“), unabhängig vom Rechner
})

sys.path.insert(0, str(SCHUTZ))
import schutzwache  # noqa: E402

schutzwache.einschalten()


def pytest_sessionfinish(session, exitstatus):
    if not os.environ.get("BALDUIN_TESTS_BEHALTEN"):   # zum Nachsehen: BALDUIN_TESTS_BEHALTEN=1
        shutil.rmtree(BASIS, ignore_errors=True)
    else:
        print(f"\nTestdaten behalten in {BASIS}")


@pytest.fixture(autouse=True)
def schutzwache_pruefen():
    """Nach jedem Test: Hat irgendein Prozess /Volumes berührt (auch wenn der Fehler abgefangen wurde)?"""
    vorher = SCHUTZ_PROTOKOLL.stat().st_size
    yield
    if SCHUTZ_PROTOKOLL.stat().st_size > vorher:
        with open(SCHUTZ_PROTOKOLL, encoding="utf-8") as f:
            f.seek(vorher)
            pytest.fail("Verstoß gegen harte Regel 1 (Zugriff auf /Volumes):\n" + f.read())


# ---------- Hilfen ----------

def fehlende_werkzeuge():
    from erfassung import system                       # sucht auch in BALDUIN_WERKZEUGE (Windows) und Homebrew
    return [w for w in ("sf", "exiftool") if not system.werkzeug_pfad(w)]


def integration_noetig():
    fehlt = fehlende_werkzeuge()
    if fehlt:
        pytest.skip(f"Werkzeuge fehlen: {', '.join(fehlt)} (brew install siegfried exiftool)")


def fingerabdruck(ordner):
    """Jede Datei unter ordner mit Größe, Änderungszeit und SHA-256; dazu die Ordner mit Änderungszeit.
    Zeigt jede Änderung an einer Quellplatte: neue, gelöschte, umbenannte oder veränderte Dateien."""
    ergebnis = {}
    for wurzel, ordner_liste, dateien in os.walk(ordner):
        for name in ordner_liste:
            p = Path(wurzel) / name
            ergebnis[p.relative_to(ordner).as_posix() + "/"] = p.lstat().st_mtime_ns
        for name in dateien:
            p = Path(wurzel) / name
            s = p.lstat()
            ergebnis[p.relative_to(ordner).as_posix()] = (s.st_size, s.st_mtime_ns, hashlib.sha256(p.read_bytes()).hexdigest())
    return ergebnis


def verbinden(projekt_ordner):
    """Nur lesend auf die Datenbank eines Projekts (Zeilen als dict-ähnliche Rows)."""
    con = sqlite3.connect(f"file:{Path(projekt_ordner) / 'inventar.sqlite'}?mode=ro", uri=True, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def abfrage(projekt_ordner, sql, *werte):
    con = verbinden(projekt_ordner)
    try:
        return [dict(z) for z in con.execute(sql, werte)]
    finally:
        con.close()


def lauf_aufrufen(*argumente, eingabe=None):
    """python -m erfassung.lauf … wie das Tool; Antwort als JSON."""
    e = subprocess.run([PYTHON, "-X", "utf8", "-m", "erfassung.lauf", *map(str, argumente)], cwd=CODE,
                       capture_output=True, text=True, encoding="utf-8", input=eingabe, timeout=600)
    assert e.returncode == 0, f"erfassung.lauf {argumente[0]} scheiterte:\n{e.stderr[-3000:]}"
    return json.loads(e.stdout) if e.stdout.strip() else None


def lauf_ausfuehren(projekt_ordner, volumes, art, auftrag, platte_id=None, eingabe=None):
    """Legt einen Lauf an und führt ihn im Vordergrund aus (wie der Hintergrundlauf aus dem Tool). Antwort: Lauf und
    Schritte aus der Datenbank. eingabe: stdin des Laufs (Passwort eines verschlüsselten Volumes)."""
    con = sqlite3.connect(Path(projekt_ordner) / "inventar.sqlite", timeout=30)
    try:
        lauf_id = con.execute("INSERT INTO lauf (art, platte_id, auftrag, status, start) VALUES (?,?,?, 'wartet', "
                              "datetime('now'))", (art, platte_id, json.dumps(auftrag))).lastrowid
        con.commit()
    finally:
        con.close()
    e = subprocess.run([PYTHON, "-X", "utf8", "-m", "erfassung.lauf", "erfassen", "--projekt", str(projekt_ordner),
                        "--volumes", str(volumes), "--lauf", str(lauf_id)], cwd=CODE, capture_output=True, text=True, encoding="utf-8",
                       timeout=900, input=eingabe)
    lauf = abfrage(projekt_ordner, "SELECT * FROM lauf WHERE lauf_id = ?", lauf_id)[0]
    schritte = {z["schritt"]: z for z in abfrage(projekt_ordner, "SELECT * FROM lauf_schritt WHERE lauf_id = ?", lauf_id)}
    assert lauf["status"] == "fertig", (f"Lauf {art} {platte_id or ''} endete mit {lauf['status']}: {lauf['meldung']}\n"
                                        f"{ {k: (s['status'], s['text']) for k, s in schritte.items()} }\n{e.stderr[-3000:]}")
    return {"lauf": lauf, "schritte": schritte, "ausgabe": e.stderr}


def projekt_kopieren(quelle, ziel):
    """Kopie eines Projekts; die Datenbank über SQLite-Backup (WAL-Dateien gehören dazu, CLAUDE.md)."""
    shutil.copytree(quelle, ziel, ignore=shutil.ignore_patterns("inventar.sqlite*"))
    alt = sqlite3.connect(Path(quelle) / "inventar.sqlite")
    neu = sqlite3.connect(Path(ziel) / "inventar.sqlite")
    try:
        alt.backup(neu)
    finally:
        alt.close()
        neu.close()
    return Path(ziel)


def freier_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------- Fixtures ----------

@pytest.fixture(scope="session")
def testplatten():
    """Die vier Testplatten in BASIS/volumes (gilt in den Tests als /Volumes), mit Fingerabdruck vom Anlegen."""
    integration_noetig()
    volumes = BASIS / "volumes"
    e = subprocess.run([PYTHON, str(CODE / "werkzeuge" / "testplatten_erzeugen.py"), str(volumes)], cwd=CODE,
                       capture_output=True, text=True, timeout=300)
    assert e.returncode == 0, e.stderr
    return SimpleNamespace(volumes=volumes, abdruck={p.name: fingerabdruck(p) for p in volumes.iterdir() if p.is_dir()})


@pytest.fixture(scope="session")
def mac_abbilder():
    """Abbilder von Mac-Datenträgern (HFS+ und APFS, werkzeuge/mac_testabbilder_erzeugen.py), entpackt in BASIS/abbilder.
    Gleicher Inhalt in beiden; Sollwerte der Kennungen wie diskutil sie nennt."""
    import gzip
    ordner = BASIS / "abbilder"
    ordner.mkdir(exist_ok=True)
    for name in ("mac_hfs.img", "mac_apfs.img", "mac_apfs_zwei.img"):
        if not (ordner / name).exists():
            with gzip.open(CODE / "tests" / "daten" / f"{name}.gz", "rb") as quelle, open(ordner / name, "wb") as ziel:
                while stueck := quelle.read(1 << 20):         # dünn: Nullblöcke überspringen (zwei ist 1,1 GB)
                    if stueck.count(0) == len(stueck):
                        ziel.seek(len(stueck), 1)
                    else:
                        ziel.write(stueck)
                ziel.truncate()
    return SimpleNamespace(
        hfs=ordner / "mac_hfs.img", apfs=ordner / "mac_apfs.img",
        zwei=ordner / "mac_apfs_zwei.img", passwort="Geheim-7f3a9c",     # MAC_ZWEI und GEHEIM (verschlüsselt, leer)
        uuid={"hfs": "0214787C-877A-3DF5-9D19-95263DC9120B", "apfs": "12DC088A-95F4-42B6-9D98-9C3B3E898805"},
        dateien={"Fotos/Zürich 1998/Übergabe/Bild ä.png", "Fotos/Zürich 1998/bunt.png", "Texte/Notiz 12:30.txt",
                 "Texte/leer.txt", "Texte/Brief.pdf", "Archiv/alt.zip", "Alt/Mit Resource Fork"})


@pytest.fixture(scope="session")
def anton(testplatten):
    """Nachgebauter Anton; punkt.gif von HD01 liegt dort schon (für den Abgleich G5)."""
    gif = testplatten.volumes / "HD01" / "Formate" / "punkt.gif"
    with AntonNachbau((hashlib.md5(gif.read_bytes()).hexdigest(), gif.name, gif.stat().st_size)) as a:
        yield a


@pytest.fixture(scope="session")
def analysiert(testplatten, anton):
    """Projekt „Testprojekt“ (Kürzel HD, ohne Virenscan und Personen): HD01 und HD02 durch B–I, Bestand aus Anton."""
    ordner = BASIS / "projekte" / "Testprojekt"
    lauf_aufrufen("anlegen", "--volumes", testplatten.volumes, "--daten", json.dumps({
        "ordner": str(ordner), "name": "Testprojekt", "kennung": "HD", "virenscan": False, "personen": False,
        "anton": {"url": anton.url},
        "speicher": {"min_frei_gb": 1}}))           # Testplatten sind klein: nicht am freien Platz des Rechners scheitern
    laeufe = {}
    for platte in ("HD01", "HD02"):
        laeufe[platte] = lauf_ausfuehren(ordner, testplatten.volumes, "erfassen", {
            "platte_id": platte, "mountpunkt": str(testplatten.volumes / platte), "beschreibbar_ok": True,
            "etikett": f"Etikett {platte}"}, platte)
    laeufe["anton"] = lauf_ausfuehren(ordner, testplatten.volumes, "anton", {"modus": ""})
    return SimpleNamespace(ordner=ordner, volumes=testplatten.volumes, laeufe=laeufe)


@pytest.fixture(scope="session")
def quellen(analysiert, testplatten):
    """Teile einer Platte und Ordner als Quelle (Entscheidungen 05.11.2026), auf einer eigenen Kopie von „analysiert“:
    HD03 nur mit dem Umfang „Alt“ registriert und analysiert; ein gewöhnlicher Ordner außerhalb von /Volumes
    („Übergabe 2026“, Kopie von HD03) als HD05 registriert und durch B–I gelaufen."""
    basis = BASIS / "quellen"
    ordner = projekt_kopieren(analysiert.ordner, basis / "Testprojekt")
    quellordner = basis / "Übergabe 2026"
    shutil.copytree(testplatten.volumes / "HD03", quellordner)
    abdruck = fingerabdruck(quellordner)
    laeufe = {
        "HD03": lauf_ausfuehren(ordner, testplatten.volumes, "erfassen", {
            "platte_id": "HD03", "mountpunkt": str(testplatten.volumes / "HD03"), "beschreibbar_ok": True,
            "etikett": "Etikett HD03", "umfang": ["Alt"]}, "HD03"),
        "HD05": lauf_ausfuehren(ordner, testplatten.volumes, "erfassen", {
            "platte_id": "HD05", "mountpunkt": str(quellordner), "art": "ordner",
            "etikett": "Übergabe per Download, Marketing, 2026"}, "HD05"),
    }
    return SimpleNamespace(ordner=ordner, volumes=testplatten.volumes, quellordner=quellordner, abdruck=abdruck,
                           laeufe=laeufe)


@pytest.fixture(scope="module")
def projekt(analysiert, tmp_path_factory):
    """Eigene Kopie des analysierten Projekts je Testdatei."""
    ziel = tmp_path_factory.mktemp("projekt") / "Testprojekt"
    return SimpleNamespace(ordner=projekt_kopieren(analysiert.ordner, ziel), volumes=analysiert.volumes)


class Balduin:
    """Der Server als Unterprozess auf einem Testprojekt, wie nach dem Doppelklick, aber nur mit Scratch-Pfaden."""

    def __init__(self, projekt, volumes, arbeitsordner, umgebung=None):
        self.projekt = Path(projekt)
        self.port = freier_port()
        self.adresse = f"http://127.0.0.1:{self.port}"
        self.log = open(arbeitsordner / "server.log", "w", encoding="utf-8")
        self.prozess = subprocess.Popen(
            [PYTHON, str(CODE / "tool" / "server.py"), "--projekt", str(projekt), "--port", str(self.port),
             "--volumes", str(volumes), "--projekte", str(arbeitsordner / "neue_projekte"),
             "--zuletzt", str(arbeitsordner / "zuletzt.json"), "--kein-browser"],
            cwd=CODE, stdout=self.log, stderr=subprocess.STDOUT, env={**os.environ, **(umgebung or {})})
        self.cookie = ""
        ende = time.monotonic() + 60
        while True:
            try:
                with urllib.request.urlopen(self.adresse + "/", timeout=5) as a:
                    self.cookie = a.headers["Set-Cookie"].split(";")[0]
                    break
            except (urllib.error.URLError, ConnectionError):
                if self.prozess.poll() is not None or time.monotonic() > ende:
                    raise RuntimeError("Server startet nicht:\n" + (arbeitsordner / "server.log").read_text(encoding="utf-8"))
                time.sleep(0.2)

    def roh(self, methode, pfad, daten=None, kopf=None, cookie=True):
        """Anfrage mit freien Kopfzeilen; Antwort (Status, JSON oder Text)."""
        k = {"Cookie": self.cookie} if cookie else {}
        rumpf = None
        if daten is not None:
            rumpf = json.dumps(daten).encode() if not isinstance(daten, bytes) else daten
            k["Content-Type"] = "application/json"
        k.update(kopf or {})
        a = urllib.request.Request(self.adresse + pfad, data=rumpf, method=methode, headers=k)
        try:
            with urllib.request.urlopen(a, timeout=120) as antwort:
                status, text = antwort.status, antwort.read()
        except urllib.error.HTTPError as f:
            status, text = f.code, f.read()
        try:
            return status, json.loads(text)
        except ValueError:
            return status, text

    def get(self, adresse, erwartet=200, **q):
        """GET mit Abfrage als Schlüsselwörter, z. B. get("/api/kinder", platte="HD01", pfad="Fotos")."""
        from urllib.parse import urlencode
        status, antwort = self.roh("GET", adresse + (("?" + urlencode(q)) if q else ""))
        assert status == erwartet, f"GET {adresse}: {status} {antwort}"
        return antwort

    def post(self, adresse, daten=None, erwartet=200):
        status, antwort = self.roh("POST", adresse, daten or {})
        assert status == erwartet, f"POST {adresse}: {status} {antwort}"
        return antwort

    def laeufe_abwarten(self, timeout=300):
        """Wartet, bis kein Lauf mehr eingereiht ist oder läuft; Antwort: alle Läufe."""
        ende = time.monotonic() + timeout
        while time.monotonic() < ende:
            offen = abfrage(self.projekt, "SELECT COUNT(*) AS n FROM lauf WHERE status IN ('eingereiht', 'wartet', 'läuft')")
            if offen[0]["n"] == 0:
                return abfrage(self.projekt, "SELECT * FROM lauf ORDER BY lauf_id")
            time.sleep(0.5)
        raise TimeoutError("Lauf wurde nicht fertig")

    def beenden(self):
        self.prozess.terminate()
        try:
            self.prozess.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.prozess.kill()
        self.log.close()


@pytest.fixture(scope="module")
def balduin(projekt, tmp_path_factory):
    b = Balduin(projekt.ordner, projekt.volumes, tmp_path_factory.mktemp("server"))
    yield b
    b.beenden()


@pytest.fixture
def leeres_projekt(tmp_path):
    """Frisch angelegtes Projekt ohne Platten, im Testprozess geöffnet (erfassung.basis.P zeigt darauf)."""
    from erfassung import basis
    volumes = tmp_path / "volumes"
    volumes.mkdir()
    basis.projekt_anlegen(tmp_path / "Leer", {"name": "Leer", "kennung": "HD", "virenscan": False,
                                              "anton": {"url": "http://127.0.0.1:9"},
                                              # wie die übrigen Testprojekte: nicht am freien Platz des Rechners
                                              # scheitern (Windows-VM mit 18,8 GB frei, 12.11.2026)
                                              "speicher": {"min_frei_gb": 1}})
    basis.oeffnen(tmp_path / "Leer", volumes=volumes)
    yield basis.P
    from erfassung import quelle
    quelle.schliessen()                                 # geöffnete Abbilder freigeben

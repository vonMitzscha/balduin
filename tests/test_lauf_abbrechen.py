"""Läufe halten den Rechner wach und lassen sich immer abbrechen (Entscheidung 14.11.2026, docs/plan.md).

Anlass: Unter Windows ging der Rechner während D2 Formate in den Ruhezustand. Danach hing die Formaterkennung, und
„Abbrechen“ wurde nie fertig: Die Unterbrechung der Abbruchwache kommt erst an, wenn der Lauf aus dem Warten auf das
Programm zurückkehrt. Geprüft wird
1. system.wach_halten (Ruhezustand verhindern) je System,
2. system.kinder_beenden / system.beenden (gestartete Programme und hängende Läufe beenden),
3. die Abbruchwache beendet die Programme, auf die der Lauf wartet,
4. der Server beendet einen Lauf hart, der auf „Abbrechen“ nicht reagiert."""
import os
import signal
import sqlite3
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from erfassung import system

NICHT_WINDOWS = pytest.mark.skipif(sys.platform == "win32", reason="prüft die Mac- und Linux-Seite echt")
NUR_MAC = pytest.mark.skipif(sys.platform != "darwin", reason="braucht caffeinate")


@pytest.fixture
def windows(monkeypatch):
    monkeypatch.setattr(system, "windows", lambda: True)
    monkeypatch.setattr(system, "mac", lambda: False)
    monkeypatch.setattr(system, "linux", lambda: False)
    return monkeypatch


@pytest.fixture
def macos(monkeypatch):
    monkeypatch.setattr(system, "windows", lambda: False)
    monkeypatch.setattr(system, "mac", lambda: True)
    monkeypatch.setattr(system, "linux", lambda: False)
    return monkeypatch


@pytest.fixture
def linux(monkeypatch):
    monkeypatch.setattr(system, "windows", lambda: False)
    monkeypatch.setattr(system, "mac", lambda: False)
    monkeypatch.setattr(system, "linux", lambda: True)
    return monkeypatch


def verboten(*a, **k):
    raise AssertionError("darf unter Windows nicht gerufen werden")


class Prozess:
    """Nachgestelltes Popen für die Wachhalter."""
    def __init__(self, befehl, **k):
        self.befehl, self.k, self.beendet = befehl, k, False

    def terminate(self):
        self.beendet = True

    def poll(self):
        return 0 if self.beendet else None

    def wait(self, timeout=None):
        return 0


# ---------- 1. Ruhezustand verhindern ----------

def test_wach_halten_unter_windows(windows):
    """SetThreadExecutionState: System wach (ES_SYSTEM_REQUIRED), dauerhaft (ES_CONTINUOUS), Bildschirm darf aus."""
    aufrufe = []
    windows.setattr(system, "_win_ausfuehrungszustand", lambda zustand: aufrufe.append(zustand) or True)
    windows.setattr(system.subprocess, "Popen", verboten)
    ende = system.wach_halten("Test")
    assert aufrufe == [system.ES_CONTINUOUS | system.ES_SYSTEM_REQUIRED]
    ende()
    assert aufrufe[-1] == system.ES_CONTINUOUS            # zurück: Ruhezustand wieder erlaubt
    ende()                                                 # zweimal schadet nicht
    assert len(aufrufe) == 2


def test_wach_halten_auf_dem_mac(macos):
    """caffeinate -i (kein Ruhezustand bei Untätigkeit) -w <pid>: endet von selbst mit dem Lauf, auch beim harten Ende."""
    gestartet = []
    macos.setattr(system, "werkzeug_pfad", lambda name: "/usr/bin/caffeinate" if name == "caffeinate" else None)
    macos.setattr(system.subprocess, "Popen", lambda befehl, **k: gestartet.append(Prozess(befehl, **k)) or gestartet[-1])
    ende = system.wach_halten("Test")
    (p,) = gestartet
    assert p.befehl == ["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())]
    assert p.k["stdin"] == p.k["stdout"] == p.k["stderr"] == subprocess.DEVNULL
    ende()
    assert p.beendet


def test_wach_halten_unter_linux(linux):
    """systemd-inhibit hält Ruhezustand und Untätigkeit an, solange der Lauf lebt (tail --pid endet mit ihm)."""
    gestartet = []
    linux.setattr(system, "werkzeug_pfad", lambda name: f"/usr/bin/{name}")
    linux.setattr(system.subprocess, "Popen", lambda befehl, **k: gestartet.append(Prozess(befehl, **k)) or gestartet[-1])
    ende = system.wach_halten("Analyse SLUB01")
    (p,) = gestartet
    assert p.befehl[0] == "/usr/bin/systemd-inhibit"
    assert "--what=sleep:idle" in p.befehl and "--who=Balduin" in p.befehl and "--why=Analyse SLUB01" in p.befehl
    assert p.befehl[-4:] == ["/usr/bin/tail", f"--pid={os.getpid()}", "-f", "/dev/null"]
    ende()
    assert p.beendet


def test_wach_halten_ohne_werkzeug_tut_nichts(linux):
    """Fehlt systemd-inhibit, läuft der Lauf trotzdem (nur ohne Schutz vor dem Ruhezustand)."""
    linux.setattr(system, "werkzeug_pfad", lambda name: None)
    linux.setattr(system.subprocess, "Popen", verboten)
    system.wach_halten("Test")()


def test_wach_halten_scheitert_nie(macos):
    """Ein Fehler beim Wachhalten darf keinen Lauf verhindern."""
    macos.setattr(system, "werkzeug_pfad", lambda name: "/usr/bin/caffeinate")

    def kaputt(*a, **k):
        raise OSError("geht nicht")
    macos.setattr(system.subprocess, "Popen", kaputt)
    system.wach_halten("Test")()


@NUR_MAC
def test_wach_halten_echt_auf_dem_mac():
    ende = system.wach_halten("Test")
    kinder = system.kinder(os.getpid())
    assert kinder, "caffeinate läuft nicht"
    ende()
    for _ in range(50):
        if not any(system.lebt(k) for k in kinder):
            break
        time.sleep(0.1)
    assert not any(system.lebt(k) for k in kinder)


# ---------- 2. Kinder beenden, hart beenden ----------

def skript_mit_enkel(tmp_path):
    """Kind, das ein Programm startet und auf dessen Ausgabe wartet (wie der Lauf auf die Formaterkennung)."""
    skript = tmp_path / "kind.py"
    skript.write_text(textwrap.dedent(f"""
        import signal, subprocess, sys
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        enkel = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdout=subprocess.PIPE)
        print(enkel.pid, flush=True)
        enkel.stdout.read()                 # wartet, bis das Programm etwas ausgibt oder endet
        enkel.wait()                        # beendetes Programm abholen (sonst bleibt es als Zombie sichtbar)
        print("weiter", flush=True)
        import time; time.sleep(60)
    """), encoding="utf-8")
    return subprocess.Popen([sys.executable, str(skript)], stdout=subprocess.PIPE, text=True)


@NICHT_WINDOWS
def test_kinder_beenden_echt(tmp_path):
    kind = skript_mit_enkel(tmp_path)
    try:
        enkel = int(kind.stdout.readline())
        assert enkel in system.kinder(kind.pid)
        assert system.kinder_beenden(kind.pid) == 1
        assert kind.stdout.readline().strip() == "weiter"      # das Warten endet
        assert system.lebt(kind.pid)                            # das Kind selbst bleibt
        for _ in range(50):
            if not system.lebt(enkel):
                break
            time.sleep(0.1)
        assert not system.lebt(enkel)
    finally:
        kind.kill()
        kind.wait()


@NICHT_WINDOWS
def test_beenden_echt(tmp_path):
    """Ein Lauf, der SIGINT nicht annimmt und auf ein Programm wartet: beenden() beendet beide."""
    kind = skript_mit_enkel(tmp_path)
    enkel = int(kind.stdout.readline())
    assert system.beenden(kind.pid) is True
    kind.wait(timeout=10)
    for _ in range(50):
        if not system.lebt(enkel):
            break
        time.sleep(0.1)
    assert not system.lebt(enkel)
    assert system.beenden(kind.pid) is False                   # schon beendet


def test_kinder_unter_windows_ohne_os_kill(windows):
    """Kinder und Enkel über die Prozessliste; nur jüngere Prozesse zählen (eine wiederverwendete Kennung eines
    längst beendeten Elternteils macht fremde Prozesse nicht zu Kindern)."""
    windows.setattr(system.os, "kill", verboten)
    liste = [(10, 1), (20, 10), (21, 10), (30, 20), (40, 99), (50, 10)]
    start = {10: 100.0, 20: 101.0, 21: 102.0, 30: 103.0, 40: 50.0, 50: 90.0}   # 50: älter als 10 → nicht sein Kind
    windows.setattr(system, "_win_prozesse", lambda: liste)
    windows.setattr(system, "_win_startzeit", lambda pid: start.get(pid))
    assert sorted(system.kinder(10)) == [20, 21, 30]
    beendet = []
    windows.setattr(system, "_win_beenden", lambda pid: beendet.append(pid) or True)
    windows.setattr(system, "_win_prozess_lebt", lambda pid: pid not in beendet)
    assert system.kinder_beenden(10) == 3
    assert sorted(beendet) == [20, 21, 30]
    beendet.clear()
    assert system.beenden(10) is True
    assert beendet[-1] == 10 and sorted(beendet[:-1]) == [20, 21, 30]       # Kinder zuerst, dann der Lauf


# ---------- 3. Abbruchwache beendet, worauf der Lauf wartet ----------

def test_abbruchwache_beendet_das_programm_auf_das_der_lauf_wartet(tmp_path):
    """Der Lauf wartet auf die Ausgabe eines Programms, das nichts mehr ausgibt (wie die Formaterkennung nach dem
    Ruhezustand). Die Unterbrechung allein erreicht ihn dort nicht; die Wache beendet das Programm, dann hält er an."""
    db = tmp_path / "inventar.sqlite"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE lauf (lauf_id INTEGER PRIMARY KEY, abbrechen INTEGER DEFAULT 0)")
        con.execute("INSERT INTO lauf (lauf_id) VALUES (1)")
    con.close()
    skript = tmp_path / "lauf.py"
    skript.write_text(textwrap.dedent(f"""
        import signal, subprocess, sys
        sys.path.insert(0, {str(Path(system.__file__).parent.parent)!r})
        from erfassung import lauf
        signal.signal(signal.SIGINT, lauf.unterbrechen)
        wache = lauf.abbruchwache({str(db)!r}, 1, takt=0.1, kinder_nach=0.5)
        programm = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdout=subprocess.PIPE)
        print(programm.pid, flush=True)
        try:
            for zeile in programm.stdout:       # wartet in der Leseoperation
                pass
            import time
            time.sleep(5)                       # hier kommt die Unterbrechung an
            print("nicht unterbrochen", flush=True)
        except KeyboardInterrupt:
            print("unterbrochen", lauf.ABBRUCH, flush=True)
        wache.set()
    """), encoding="utf-8")
    p = subprocess.Popen([sys.executable, str(skript)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                         cwd=tmp_path)
    programm = int(p.stdout.readline())
    with sqlite3.connect(db) as con:
        con.execute("UPDATE lauf SET abbrechen = 1")
    con.close()
    try:
        aus, fehler = p.communicate(timeout=20)
    finally:
        if p.poll() is None:
            p.kill()
        system.beenden(programm)
    assert aus.strip().splitlines()[-1] == "unterbrochen True", fehler
    assert "Programm(e) beendet" in aus


# ---------- 4. Server beendet einen hängenden Lauf hart ----------

def test_server_beendet_einen_haengenden_lauf_hart(leeres_projekt, tmp_path, monkeypatch):
    """Reagiert ein Lauf nicht auf „Abbrechen“ (SIGINT ignoriert, Marke nie gelesen), beendet ihn der Server nach
    HART_NACH Sekunden und vermerkt Lauf und laufenden Schritt als abgebrochen."""
    import server
    haenger = subprocess.Popen([sys.executable, "-c", "import signal, time; signal.signal(signal.SIGINT, signal.SIG_IGN); "
                                "print('bereit', flush=True); time.sleep(120)"], stdout=subprocess.PIPE, text=True)
    assert haenger.stdout.readline().strip() == "bereit"
    try:
        bestand = server.Bestand(leeres_projekt.db_pfad, leeres_projekt.vorschauen)
        with bestand.schreibend() as con:
            con.execute("INSERT INTO lauf (lauf_id, art, platte_id, auftrag, status, pid, start) "
                        "VALUES (7, 'erfassen', 'HD01', '{}', 'läuft', ?, '2026-11-14T20:00:00')", (haenger.pid,))
            con.execute("INSERT INTO lauf_schritt (lauf_id, schritt, titel, status) VALUES (7, 'D1', 'Prüfsummen', 'fertig')")
            con.execute("INSERT INTO lauf_schritt (lauf_id, schritt, titel, status) VALUES (7, 'D2', 'Formate', 'läuft')")
            con.execute("INSERT INTO lauf_schritt (lauf_id, schritt, titel, status) VALUES (7, 'D3', 'Virenscan', 'wartet')")
        erf = server.Erfassung(bestand, {"ordner": str(leeres_projekt.ordner)})
        monkeypatch.setattr(server.Erfassung, "HART_NACH", 0.5)
        assert erf.abbrechen(7) == {"ok": True}
        haenger.wait(timeout=15)
        for _ in range(100):
            con = sqlite3.connect(leeres_projekt.db_pfad)
            status = con.execute("SELECT status, meldung, ende FROM lauf WHERE lauf_id = 7").fetchone()
            schritte = dict(con.execute("SELECT schritt, status FROM lauf_schritt WHERE lauf_id = 7").fetchall())
            con.close()
            if status[0] != "läuft":
                break
            time.sleep(0.1)
        assert status[0] == "abgebrochen" and status[2]
        assert "beendet" in status[1]
        assert schritte == {"D1": "fertig", "D2": "abgebrochen", "D3": "wartet"}
    finally:
        if haenger.poll() is None:
            haenger.kill()


def test_server_laesst_einen_lauf_in_ruhe_der_selbst_anhaelt(leeres_projekt, monkeypatch):
    """Hält der Lauf rechtzeitig an, wird nichts hart beendet und sein eigener Endstand bleibt."""
    import server
    bestand = server.Bestand(leeres_projekt.db_pfad, leeres_projekt.vorschauen)
    with bestand.schreibend() as con:
        con.execute("INSERT INTO lauf (lauf_id, art, platte_id, auftrag, status, pid, start) "
                    "VALUES (8, 'erfassen', 'HD01', '{}', 'läuft', 4711, '2026-11-14T20:00:00')")
    erf = server.Erfassung(bestand, {"ordner": str(leeres_projekt.ordner)})
    monkeypatch.setattr(server.Erfassung, "HART_NACH", 0.3)
    lebendig = {"ja": True}
    monkeypatch.setattr(server.system, "lebt", lambda pid: lebendig["ja"])
    monkeypatch.setattr(server.system, "unterbrechen", lambda pid: True)
    monkeypatch.setattr(server.system, "beenden", verboten)
    erf.abbrechen(8)
    with bestand.schreibend() as con:                     # der Lauf schreibt seinen Endstand selbst
        con.execute("UPDATE lauf SET status = 'abgebrochen', meldung = 'D2 Formate: abgebrochen' WHERE lauf_id = 8")
    lebendig["ja"] = False
    time.sleep(1.0)
    con = sqlite3.connect(leeres_projekt.db_pfad)
    assert con.execute("SELECT meldung FROM lauf WHERE lauf_id = 8").fetchone()[0] == "D2 Formate: abgebrochen"
    con.close()


def test_lauf_haelt_den_rechner_wach(monkeypatch):
    """erfassen() hält den Rechner für die Dauer des Laufs wach und gibt ihn danach frei (auch bei Fehlern)."""
    quelle = (Path(system.__file__).parent / "lauf.py").read_text(encoding="utf-8")
    assert "system.wach_halten(" in quelle
    rumpf = quelle.split("def erfassen(", 1)[1].split("\ndef ", 1)[0]
    assert "wach_halten(" in rumpf and "wach()" in rumpf.split("finally:", 1)[1]

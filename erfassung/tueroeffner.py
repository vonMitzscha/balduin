"""Türöffner für physische Platten unter Windows (Entscheidung 09.11.2026, docs/plan.md).

Windows lässt eine physische Platte (\\\\.\\PhysicalDriveN) nur mit Administratorrechten lesen. Damit nicht der ganze
Lauf (mit ExifTool, ffmpeg und den Dateisystem-Bibliotheken über fremden Daten) mit diesen Rechten läuft, startet
erfassung/system.py nur dieses kleine Skript über die Benutzerkontensteuerung („Als Administrator ausführen“). Es
1. prüft den Auftrag (nur \\\\.\\PhysicalDriveN, nur eine Verbindung auf 127.0.0.1),
2. öffnet die Platte nur zum Lesen,
3. verdoppelt den Zugriff (DuplicateHandle, gleiche Rechte: nur lesen) in den Lauf, der es gerufen hat,
4. meldet ihn über die mit einem Schlüssel geschützte Verbindung und beendet sich.
Es liest keine Daten und schreibt nichts. Aufruf (nur von system.py):
    python erfassung/tueroeffner.py \\\\.\\PhysicalDrive2 <pid des Laufs> 127.0.0.1:<port> <schlüssel hex>
Nur Standardbibliothek; wird als Skript gestartet, nicht über das Paket erfassung.
"""
import re
import sys

MUSTER = re.compile(r"\\\\\.\\PhysicalDrive\d{1,3}", re.IGNORECASE)
GENERIC_READ, FILE_SHARE_READ_WRITE, OPEN_EXISTING = 0x80000000, 0x3, 3
PROCESS_DUP_HANDLE, DUPLICATE_SAME_ACCESS = 0x0040, 0x2


def auftrag_pruefen(argumente):
    """(Gerät, pid, (Adresse, Port), Schlüssel) oder ValueError."""
    if len(argumente) != 4:
        raise ValueError("Aufruf: tueroeffner.py <Gerät> <pid> 127.0.0.1:<port> <schlüssel>")
    geraet, pid, adresse, schluessel = argumente
    if not MUSTER.fullmatch(geraet):
        raise ValueError(f"Nur physische Datenträger (\\\\.\\PhysicalDriveN), nicht {geraet!r}.")
    if not pid.isdigit() or int(pid) <= 0:
        raise ValueError("Ungültige Prozessnummer.")
    host, _, port = adresse.rpartition(":")
    if host != "127.0.0.1" or not port.isdigit():
        raise ValueError("Die Verbindung muss auf 127.0.0.1 bleiben.")
    if not re.fullmatch(r"[0-9a-f]{32,128}", schluessel):
        raise ValueError("Ungültiger Schlüssel.")
    return geraet, int(pid), (host, int(port)), bytes.fromhex(schluessel)


def nur_lesend_oeffnen(geraet):
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = ctypes.c_void_p
    griff = kernel32.CreateFileW(geraet, GENERIC_READ, FILE_SHARE_READ_WRITE, None, OPEN_EXISTING, 0, None)
    if griff in (None, ctypes.c_void_p(-1).value):
        raise OSError(f"{geraet} lässt sich nicht öffnen (Fehler {ctypes.get_last_error()}).")
    return griff


def _prozess_oeffnen(pid):
    """OpenProcess nur zum Verdoppeln von Zugriffen; Antwort: (Griff oder 0, Fehlernummer)."""
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    ziel = kernel32.OpenProcess(PROCESS_DUP_HANDLE, False, pid)
    return (ziel or 0), (0 if ziel else ctypes.get_last_error())


def debugrecht_einschalten():
    """Schaltet SeDebugPrivilege für diesen Prozess ein. Jedes erhöhte Administratorkonto besitzt es, aber ausgeschaltet.
    Nötig, wenn der Lauf einem anderen Konto gehört (Arbeitskonto ohne Administratorrechte, die Rückfrage bestätigt ein
    Administrator): dessen Prozess lässt sich sonst auch von Administratoren nicht öffnen (Fehler 5)."""
    import ctypes
    from ctypes import wintypes

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class TOKEN_PRIVILEGES(ctypes.Structure):
        _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Luid", LUID), ("Attributes", wintypes.DWORD)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(ctypes.c_void_p(kernel32.GetCurrentProcess()), 0x0020 | 0x0008,  # ADJUST | QUERY
                                     ctypes.byref(token)):
        raise OSError(f"Rechte dieses Prozesses nicht lesbar (Fehler {ctypes.get_last_error()}).")
    try:
        luid = LUID()
        if not advapi32.LookupPrivilegeValueW(None, "SeDebugPrivilege", ctypes.byref(luid)):
            raise OSError(f"SeDebugPrivilege unbekannt (Fehler {ctypes.get_last_error()}).")
        neu = TOKEN_PRIVILEGES(1, luid, 0x2)                                                  # SE_PRIVILEGE_ENABLED
        ok = advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(neu), 0, None, None)
        fehler = ctypes.get_last_error()
        if not ok or fehler == 1300:                                                          # ERROR_NOT_ALL_ASSIGNED
            raise OSError(f"SeDebugPrivilege lässt sich nicht einschalten (Fehler {fehler}).")
    finally:
        kernel32.CloseHandle(token)


def prozess_oeffnen(pid):
    """Den Lauf zum Verdoppeln öffnen; gehört er einem anderen Konto (Fehler 5), mit SeDebugPrivilege noch einmal."""
    ziel, fehler = _prozess_oeffnen(pid)
    if not ziel and fehler == 5:
        debugrecht_einschalten()
        ziel, fehler = _prozess_oeffnen(pid)
    if not ziel:
        raise OSError(f"Der Lauf {pid} ist nicht erreichbar (Fehler {fehler}).")
    return ziel


def verdoppeln(griff, pid):
    """Zugriff in den Prozess pid verdoppeln (gleiche Rechte); Antwort: Griff, wie er dort gilt."""
    import ctypes
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    ziel = prozess_oeffnen(pid)
    try:
        neu = ctypes.c_void_p()
        if not kernel32.DuplicateHandle(ctypes.c_void_p(kernel32.GetCurrentProcess()), ctypes.c_void_p(griff),
                                        ctypes.c_void_p(ziel), ctypes.byref(neu), 0, False, DUPLICATE_SAME_ACCESS):
            raise OSError(f"Der Zugriff ließ sich nicht weitergeben (Fehler {ctypes.get_last_error()}).")
        return neu.value
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(ziel))


def schliessen(griff):
    import ctypes
    ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(griff))


def main(argumente=None):
    from multiprocessing.connection import Client
    geraet, pid, adresse, schluessel = auftrag_pruefen(sys.argv[1:] if argumente is None else argumente)
    try:
        griff = nur_lesend_oeffnen(geraet)
    except OSError as e:
        with Client(adresse, authkey=schluessel) as c:
            c.send({"fehler": str(e)})
        return
    try:
        antwort = {"griff": verdoppeln(griff, pid)}
    except OSError as e:
        antwort = {"fehler": str(e)}
    finally:
        schliessen(griff)                 # der verdoppelte Zugriff im Lauf bleibt gültig
    with Client(adresse, authkey=schluessel) as c:
        c.send(antwort)


if __name__ == "__main__":
    main()

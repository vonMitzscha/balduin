"""Kleine Hilfsfunktionen des Servers (tool/server.py), ohne ihn zu starten."""
import pytest

import server


def test_kette_nach_oben():
    assert server.kette_nach_oben("Fotos/2001/Messe/IMG.JPG") == ["Fotos/2001/Messe", "Fotos/2001", "Fotos", ""]
    assert server.kette_nach_oben("datei.txt") == [""]


@pytest.mark.parametrize("pfad, ordner, erwartet", [
    ("Fotos/a.jpg", "Fotos", True), ("Fotos/2001/a.jpg", "Fotos", True), ("Fotos 2/a.jpg", "Fotos", False),
    ("Fotosammlung/a.jpg", "Fotos", False), ("a.jpg", "", True),
])
def test_im_ordner(pfad, ordner, erwartet):
    assert server.im_ordner(pfad, ordner) is erwartet


@pytest.mark.parametrize("pfad, erwartet", [
    ("Fotos/IMG.JPG", ".jpg"), ("a/b.tar.gz", ".gz"), ("a/README", "(ohne)"), ("a/.bashrc", "(ohne)"),
])
def test_endung(pfad, erwartet):
    assert server.endung(pfad) == erwartet


def test_fehlertext_zeigt_typ_nur_bei_unerwarteten_fehlern():
    assert server.fehlertext(ValueError("Bitte einen Namen angeben.")) == "Bitte einen Namen angeben."
    assert server.fehlertext(KeyError("x")) == "KeyError: 'x'"


# Stand der Chips in der Analyse (Feedback 06.11.2026): grün nur, was wirklich gelaufen ist
CHIPS = ["C", "D1", "D2", "D3", "E", "E4", "F", "F5", "G", "G5", "H"]


def test_schritt_nicht_erledigt_solange_voraussetzung_offen():
    # D1 läuft: Formate, Virenscan, Metadaten zählen nur Dateien mit Prüfsumme und stünden auf 0
    offen = {"C": 0, "D1": 120, "D2": 0, "D3": 0, "E": 0, "E4": None, "G5": 0}
    assert server.erledigte_schritte(offen, CHIPS) == ["C"]


def test_texte_ohne_dokumente_erst_nach_virenscan():
    offen = {"C": 0, "D1": 0, "D2": 0, "D3": 5, "E": 0, "E4": 0}
    assert server.erledigte_schritte(offen, CHIPS) == ["C", "D1", "D2"]


def test_im_laufenden_lauf_noch_ausstehende_schritte_nicht_erledigt():
    offen = {"C": 0, "D1": 0, "D2": 0, "D3": 0, "E": 0, "E4": 0}
    assert server.erledigte_schritte(offen, CHIPS, ausstehend={"E", "E4"}) == ["C", "D1", "D2", "D3"]


def test_alles_erledigt():
    offen = {k: 0 for k in CHIPS}
    assert server.erledigte_schritte(offen, CHIPS) == CHIPS


def test_ungeoeffnete_archivdateien_halten_nur_c_offen():
    # Testinstanz 06.11.2026: Schnellscan gelaufen, nur 2 ZIPs noch nicht geöffnet; alles Übrige ist gelaufen
    offen = {k: 0 for k in CHIPS}
    offen.update({"C": 2, "C_archive": 2})
    assert server.erledigte_schritte(offen, CHIPS) == CHIPS[1:]


def test_schnellscan_nicht_gelaufen_haelt_alles_offen():
    offen = {k: 0 for k in CHIPS}
    offen["C"] = 190                                 # ohne C_archive: Verzeichnis selbst fehlt
    assert server.erledigte_schritte(offen, CHIPS) == []


def test_eigener_schreibvorgang_aendert_den_stand_auch_bei_grober_uhr(leeres_projekt, monkeypatch):
    """Unter Windows wird das Änderungsdatum grob fortgeschrieben (Takt ~15 ms): zwei schnelle Speichervorgänge sahen
    gleich aus, die Erschließung arbeitete mit veralteten Werten, und „Vererben“ überschrieb einen eigenen Wert
    (Windows-VM, 12.11.2026). Jeder Schreibvorgang des Servers ändert deshalb den Stand."""
    import os as _os
    b = server.Bestand(leeres_projekt.db_pfad, leeres_projekt.vorschauen)
    echt = _os.stat

    class Grob:                                   # immer dieselbe Uhrzeit, wie bei einem groben Takt
        def __init__(self, s):
            self.st_mtime, self.st_size = 1_000_000.0, s.st_size
    monkeypatch.setattr(server.os, "stat", lambda p, *a, **k: Grob(echt(p, *a, **k)))
    for _ in range(2):                            # das erste Schreiben legt -wal an; gemessen wird danach
        with b.schreibend() as con:
            con.execute("INSERT INTO protokoll VALUES ('2026-11-12', 'Test', 'x', 'y', '', 'z')")
        vorher = b.db_stand()
    with b.schreibend() as con:                   # gleich große Änderung: die -wal-Datei wächst nicht zwingend
        con.execute("UPDATE protokoll SET neu = 'zz' WHERE objekt = 'x'")
    assert b.db_stand() != vorher


def test_version_auch_wenn_git_dem_ordner_misstraut(monkeypatch):
    """Feedback 14.11.2026: Unter Windows stand links oben nur „v0“. Git verweigert die Auskunft, wenn der Code-Ordner
    einem anderen Konto gehört („dubious ownership“, z. B. anderes Konto oder freigegebener Ordner)."""
    monkeypatch.setenv("GIT_TEST_ASSUME_DIFFERENT_OWNER", "1")
    v = server.version()
    assert v.startswith("0.") and v[2:].isdigit(), v


def test_git_unter_windows_auch_ausserhalb_des_suchpfads(monkeypatch):
    from erfassung import system
    monkeypatch.setattr(system, "windows", lambda: True)
    monkeypatch.setattr(system, "linux", lambda: False)
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    assert any(o.endswith("Git" + __import__("os").sep + "cmd") for o in system.zusatz_ordner())

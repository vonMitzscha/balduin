"""Bau der Pakete (Entscheidung 14.11.2026, docs/plan.md): was ohne Netz und ohne Bau-Rechner prüfbar ist.
Den ganzen Bau prüft der Workflow .github/workflows/auslieferung.yml auf je einem Mac-, Windows- und Linux-Rechner."""
import re
import runpy

import pytest

from conftest import CODE
from hilfen.plattform import git_repo

AUS = CODE / "auslieferung"
bauen = runpy.run_path(str(AUS / "bauen.py"), run_name="test")


def test_jede_quelle_hat_eine_pruefsumme():
    for name, je_plattform in bauen["QUELLEN"].items():
        for plattform, (adresse, sha) in je_plattform.items():
            assert adresse.startswith("https://"), (name, plattform)
            assert re.fullmatch(r"[0-9a-f]{64}", sha), f"SHA-256 fehlt: {name} {plattform}"


def test_jede_plattform_hat_python_und_ffmpeg():
    for plattform in bauen["PLATTFORMEN"]:
        assert bauen["quelle"]("python", plattform)
        assert bauen["quelle"]("ffmpeg", plattform)
        assert bauen["quelle"]("exiftool", plattform)


def test_nichts_privates_im_paket():
    for muster in bauen["KOPIEREN"]:
        assert not muster.startswith(("docs", "CLAUDE", "tests", ".vscode", "1_analyse")), muster


@pytest.mark.skipif(not git_repo(CODE), reason="braucht den Code als Git-Repo")
def test_code_kopieren(tmp_path):
    bauen["code_kopieren"](tmp_path)
    assert (tmp_path / "tool" / "server.py").is_file() and (tmp_path / "erfassung" / "system.py").is_file()
    assert re.fullmatch(r"\d+\.\d+", (tmp_path / "VERSION").read_text(encoding="utf-8").strip())
    assert not (tmp_path / "tests").exists() and not (tmp_path / "docs").exists()
    assert not list(tmp_path.rglob("__pycache__"))


@pytest.mark.skipif(not git_repo(CODE), reason="braucht den Code als Git-Repo")
def test_adresse_der_releases_nur_im_paket(tmp_path, monkeypatch):
    """Neue Version (Entscheidung 14.11.2026): das Paket kennt die Release-Liste seines Repos, der Code selbst nicht."""
    monkeypatch.setenv("GITHUB_REPOSITORY", "konto/balduin")
    bauen["code_kopieren"](tmp_path)
    assert (tmp_path / "AKTUALISIERUNG").read_text(encoding="utf-8").strip() == \
        "https://api.github.com/repos/konto/balduin/releases?per_page=20"
    monkeypatch.delenv("GITHUB_REPOSITORY")
    (tmp_path / "AKTUALISIERUNG").unlink()
    bauen["code_kopieren"](tmp_path)
    assert not (tmp_path / "AKTUALISIERUNG").exists()          # Bau von Hand: keine Abfrage


def test_symbole_im_dmg_passen_zum_hintergrund():
    zeichnen = runpy.run_path(str(AUS / "mac" / "hintergrund_zeichnen.py"), run_name="test")
    text = (AUS / "mac" / "dmg_einstellungen.py").read_text(encoding="utf-8")
    assert f"os.path.basename(app): {zeichnen['APP']}" in text
    assert f'"Programme": {zeichnen["PROGRAMME"]}' in text
    assert (AUS / "mac" / "hintergrund.png").is_file() and (AUS / "mac" / "hintergrund@2x.png").is_file()


def test_starter_und_installer_teilen_die_sperre():
    """Inno Setup erkennt einen laufenden Balduin an derselben Sperre (AppMutex), die der Starter hält."""
    starter = (AUS / "windows" / "Starter.cs").read_text(encoding="utf-8")
    iss = (AUS / "windows" / "balduin.iss").read_bytes()
    sperre = re.search(r'SPERRE = "([^"]+)"', starter).group(1)
    assert f"AppMutex={sperre}".encode() in iss
    assert iss.startswith(b"\xef\xbb\xbf")                       # UTF-8 mit BOM, sonst falsche Umlaute
    assert (AUS / "windows" / "nach_der_installation.txt").read_bytes().startswith(b"\xef\xbb\xbf")
    assert b"LongPathsEnabled" in iss


def test_starter_nutzen_den_port_des_servers():
    import server
    adresse = f"http://127.0.0.1:{server.PORT}/"
    assert adresse in (AUS / "mac" / "Starter.swift").read_text(encoding="utf-8")
    assert adresse in (AUS / "windows" / "Starter.cs").read_text(encoding="utf-8")


def test_linux_ist_als_alpha_gekennzeichnet():
    assert "ALPHA" in (AUS / "linux" / "balduin.sh").read_text(encoding="utf-8")
    assert bauen["PLATTFORMEN"]["linux-x86_64"][1].endswith("alpha")


def test_starter_erkennen_ein_anderes_balduin():
    """Belegt ein Balduin außerhalb der App die Adresse, beendet sich der Server mit „läuft bereits“; die Starter
    erkennen das an diesem Text und erklären es, statt still zu verschwinden (Feedback 14.11.2026)."""
    assert "Balduin läuft bereits" in (CODE / "tool" / "server.py").read_text(encoding="utf-8")
    for starter in (AUS / "mac" / "Starter.swift", AUS / "windows" / "Starter.cs"):
        text = starter.read_text(encoding="utf-8")
        assert "läuft bereits" in text and "Balduin läuft schon in einem anderen Fenster." in text, starter


def test_installer_bietet_lange_pfade_auch_ohne_administratorrechte_an():
    """Installation „nur für mich“: die letzte Seite bietet lange Pfade an (fragt dann einmal nach
    Administratorrechten), nur wenn sie noch fehlen (Feedback 14.11.2026). Für alle: still gesetzt wie bisher."""
    iss = (AUS / "windows" / "balduin.iss").read_bytes().decode("utf-8-sig")
    lauf = [z for z in iss.splitlines() if "LongPathsEnabled" in z and z.startswith("Filename:")]
    assert lauf, "kein Eintrag unter [Run] für lange Pfade"
    assert "Verb: runas" in lauf[0] and "not IsAdminInstallMode" in lauf[0] and "not LangePfadeAn" in lauf[0]
    assert "function LangePfadeAn" in iss

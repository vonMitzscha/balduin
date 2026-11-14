"""Balduin ohne Notebook (Entscheidung 14.11.2026, docs/plan.md): im Repo und im Paket nur, was Balduin braucht."""
import subprocess
import sys

from conftest import CODE

NOTEBOOK_PAKETE = ("ipython", "matplotlib", "jinja2", "ipykernel", "nbformat", "nbstripout")


def _pakete(datei):
    namen = []
    for zeile in (CODE / datei).read_text(encoding="utf-8").splitlines():
        zeile = zeile.split("#")[0].strip()
        if zeile and not zeile.startswith("-"):
            namen.append(zeile.split("==")[0].split(">=")[0].strip().lower())
    return namen


def test_keine_notebook_dateien():
    assert not (CODE / "1_analyse.ipynb").exists()
    assert not (CODE / "erfassung" / "ergebnis.py").exists()
    assert not (CODE / "erfassung" / "anzeige.py").exists()
    assert not list(CODE.glob("*.ipynb"))


def test_keine_notebook_pakete():
    for datei in ("requirements.txt", "requirements-entwicklung.txt"):
        assert not set(_pakete(datei)) & set(NOTEBOOK_PAKETE), datei


def test_code_ohne_ipython_und_matplotlib():
    for ordner in ("erfassung", "vorlauf", "export", "tool"):
        for datei in (CODE / ordner).rglob("*.py"):
            text = datei.read_text(encoding="utf-8")
            assert "IPython" not in text and "matplotlib" not in text, datei


def test_laeufe_starten_ohne_notebook_pakete():
    """Alle Rechenmodule lassen sich laden, auch wenn IPython, matplotlib und jinja2 fehlen (wie im Paket)."""
    sperre = "import sys\nfor n in ('IPython', 'matplotlib', 'jinja2'): sys.modules[n] = None\n"
    laden = "import erfassung.lauf, vorlauf.sujet, vorlauf.normdaten, vorlauf.verwandte, export.bauen\nprint('ok')"
    r = subprocess.run([sys.executable, "-c", sperre + laden], cwd=CODE, capture_output=True, text=True,
                       encoding="utf-8")
    assert r.stdout.strip() == "ok", r.stderr[-2000:]


def test_zeige_schreibt_ins_log(capsys):
    """zeige() gibt Text und Tabellen als Text aus (im Lauf landet das im Log)."""
    import pandas as pd
    from erfassung.basis import zeige
    zeige("V5: 3 Ordner")
    zeige(pd.DataFrame({"a": [1, 2]}))
    aus = capsys.readouterr().out
    assert "V5: 3 Ordner" in aus and "a" in aus and "2" in aus

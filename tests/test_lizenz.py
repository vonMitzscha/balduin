"""Lizenz: AGPL-3.0-or-later mit Zusatz nach § 7, © Marc Eric Mitzscherling (Entscheidung 12.11.2026, docs/plan.md).

Geprüft wird, dass die Lizenztexte vollständig da sind, jede Datei im Git nach REUSE eine Lizenz hat und das Tool
Urheber und Lizenz in „Über Balduin“ zeigt (§ 7 b: diese Nennung muss in jeder Fassung erhalten bleiben).
"""
import re
import subprocess
import tomllib

import pytest

from conftest import CODE, Balduin

URHEBER = "Marc Eric Mitzscherling"


def _reuse():
    return tomllib.loads((CODE / "REUSE.toml").read_text(encoding="utf-8"))


def _muster(glob):
    """REUSE-Glob als regulärer Ausdruck: ** über Ordner hinweg, * innerhalb eines Ordners."""
    teile = re.split(r"(\*\*|\*)", glob)
    return re.compile("".join(".*" if t == "**" else "[^/]*" if t == "*" else re.escape(t) for t in teile) + r"\Z")


def _git_dateien():
    from hilfen.plattform import git_repo
    if not git_repo(CODE):
        pytest.skip("braucht Git und den Code als Git-Repo")
    r = subprocess.run(["git", "-C", str(CODE), "ls-files", "-z"], capture_output=True, text=True, check=True)
    return [p for p in r.stdout.split("\0") if p]


def test_license_ist_die_agpl():
    text = (CODE / "LICENSE").read_text(encoding="utf-8")
    assert "GNU AFFERO GENERAL PUBLIC LICENSE" in text and "Version 3, 19 November 2007" in text
    assert "END OF TERMS AND CONDITIONS" in text                   # vollständig, nicht gekürzt


def test_zusatz_nennt_urheber_und_paragraphen():
    text = (CODE / "LIZENZ-ZUSATZ.md").read_text(encoding="utf-8")
    assert URHEBER in text
    for absatz in ("7 b", "7 c", "7 e"):
        assert absatz in text
    assert "Über Balduin" in text


def test_reuse_nennt_urheber_und_lizenztexte_liegen_bei():
    angaben = _reuse()["annotations"]
    lizenzen = set()
    for a in angaben:
        lizenzen |= set(re.findall(r"[A-Za-z0-9.\-]+", a["SPDX-License-Identifier"])) - {"AND", "OR", "WITH"}
    for lizenz in lizenzen:
        assert (CODE / "LICENSES" / f"{lizenz}.txt").is_file(), f"Lizenztext fehlt: LICENSES/{lizenz}.txt"
    eigene = [a for a in angaben if "AGPL-3.0-or-later" in a["SPDX-License-Identifier"]]
    assert eigene and all(URHEBER in a["SPDX-FileCopyrightText"] for a in eigene)


def test_jede_datei_im_git_hat_eine_lizenz():
    """Wie `reuse lint`: jede Datei fällt unter eine Angabe in REUSE.toml (Lizenztexte selbst ausgenommen)."""
    muster = []
    for a in _reuse()["annotations"]:
        pfade = a["path"] if isinstance(a["path"], list) else [a["path"]]
        muster += [_muster(p) for p in pfade]
    ohne = [p for p in _git_dateien()
            if not p.startswith("LICENSES/") and p != "LICENSE" and not any(m.match(p) for m in muster)]
    assert not ohne, f"ohne Lizenzangabe in REUSE.toml: {ohne}"


def test_logo_ist_von_der_agpl_ausgenommen():
    for a in _reuse()["annotations"]:
        pfade = a["path"] if isinstance(a["path"], list) else [a["path"]]
        if "tool/web/balduin.png" in pfade:
            assert "Pixabay" in a["SPDX-License-Identifier"]
            return
    pytest.fail("tool/web/balduin.png fehlt in REUSE.toml")


def test_startseite_hat_ueber_balduin():
    html = (CODE / "tool" / "web" / "index.html").read_text(encoding="utf-8")
    assert 'id="ueber-dialog"' in html and 'id="ueber-knopf"' in html
    dialog = html[html.index('id="ueber-dialog"'):]
    dialog = dialog[:dialog.index("</dialog>")]
    assert URHEBER in dialog and "AGPL" in dialog and 'href="/lizenz"' in dialog


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    from erfassung import basis
    ordner = tmp_path_factory.mktemp("lizenz")
    (ordner / "volumes").mkdir()
    basis.projekt_anlegen(ordner / "Leer", {"name": "Leer", "kennung": "HD", "virenscan": False,
                                            "anton": {"url": "http://127.0.0.1:9"}})
    b = Balduin(ordner / "Leer", ordner / "volumes", ordner)
    yield b
    b.beenden()


@pytest.mark.parametrize("pfad, inhalt", [("/lizenz", b"GNU AFFERO GENERAL PUBLIC LICENSE"),
                                          ("/lizenz/zusatz", URHEBER.encode())])
def test_server_liefert_die_lizenztexte(server, pfad, inhalt):
    status, text = server.roh("GET", pfad)
    assert status == 200 and inhalt in (text if isinstance(text, bytes) else text.encode())


def test_startseite_zeigt_den_urheber(server):
    status, seite = server.roh("GET", "/")
    assert status == 200 and URHEBER.encode() in seite

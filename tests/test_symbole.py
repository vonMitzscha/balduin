"""Zeichen von Balduin: App-Symbol, Favicon und Logo der Oberfläche in hell und dunkel."""
import re
from pathlib import Path

from PIL import Image

CODE = Path(__file__).resolve().parent.parent
WEB = CODE / "tool" / "web"


def test_app_symbol_ist_quadratisch_und_freigestellt():
    bild = Image.open(CODE / "auslieferung" / "symbol.png")
    assert bild.size == (1024, 1024) and bild.mode == "RGBA"
    assert bild.getpixel((0, 0))[3] == 0                       # Ecken durchsichtig


def test_favicon_liegt_bereit_und_ist_eingebunden():
    ico = Image.open(WEB / "favicon.ico")
    assert {(16, 16), (32, 32), (48, 48)} <= set(ico.info["sizes"])
    assert Image.open(WEB / "favicon.png").size == (64, 64)
    seite = (WEB / "index.html").read_text(encoding="utf-8")
    assert 'rel="icon"' in seite and "/web/favicon.ico" in seite and "/web/favicon.png" in seite


def test_logo_hat_eine_fassung_fuer_die_dunkle_ansicht():
    assert (WEB / "balduin_dunkel.png").is_file()
    stil = (WEB / "app.css").read_text(encoding="utf-8")
    # in beiden dunklen Fällen (Systemeinstellung und Umschalter) das weiß hinterlegte Logo
    medien = stil.split("@media (prefers-color-scheme: dark)", 1)[1]
    assert re.search(r':root:not\(\[data-theme="light"\]\)[^{]*\.logo', medien)
    assert re.search(r':root\[data-theme="dark"\][^{]*\.logo', stil)
    assert stil.count("balduin_dunkel.png") >= 2

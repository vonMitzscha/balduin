# Einstellungen für dmgbuild (Mac-Abbild mit gestaltetem Hintergrund; auslieferung/bauen.py).
# Aufruf: dmgbuild -s dmg_einstellungen.py -D app=<Balduin.app> "Balduin 0.75" <Ziel.dmg>
# Lage der Symbole wie in hintergrund_zeichnen.py (APP, PROGRAMME).
import os.path

app = defines["app"]                              # noqa: F821 (stellt dmgbuild bereit)
hier = defines.get("hier", ".")                   # noqa: F821

format = "UDZO"
filesystem = "HFS+"
files = [app]
symlinks = {"Programme": "/Applications"}         # der Finder zeigt den Ordner in der Sprache des Systems
icon = os.path.join(hier, "Balduin.icns")
badge_icon = None
background = os.path.join(hier, "hintergrund.png")   # hintergrund@2x.png daneben wird für Retina mitgenommen
window_rect = ((200, 160), (660, 420))
default_view = "icon-view"
show_status_bar = show_tab_view = show_toolbar = show_pathbar = show_sidebar = False
icon_size = 128
text_size = 13
icon_locations = {os.path.basename(app): (170, 200), "Programme": (490, 200)}

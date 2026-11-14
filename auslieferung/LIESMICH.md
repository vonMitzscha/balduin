# Auslieferung: Balduin als Programm bauen

Balduin wird mit eigenem Python und allen Werkzeugen ausgeliefert, damit es sich ohne Python, Homebrew oder
Paketverwaltung installieren lässt (wie OpenRefine: Doppelklick, Arbeit im Browser).

| System | Ergebnis | Starter |
|---|---|---|
| Mac mit Apple-Chip / Intel | `Balduin-<v>-Mac-AppleChip.dmg`, `…-Mac-Intel.dmg` (Balduin in „Programme“ ziehen) | `mac/Starter.swift`: Symbol im Dock, „Beenden“ beendet den Server |
| Windows 10/11 x64 | `Balduin-<v>-Windows-Setup.exe` (Inno Setup, setzt `LongPathsEnabled`) | `windows/Starter.cs`: Symbol im Infobereich |
| Linux x86_64 (**Alpha**) | `Balduin-<v>-Linux-x86_64-alpha.tar.gz` | `linux/balduin.sh` im Terminal |

## Bauen über GitHub Actions

Der Workflow `.github/workflows/auslieferung.yml` baut auf je einem Mac- (Apple-Chip und Intel), Windows- und
Linux-Rechner. Von Hand gestartet („Run workflow“) liegen die Dateien als Entwurfs-Release „Testbau“ bereit (nur für Berechtigte sichtbar, schneller als die Artefakte am Lauf); bei einem Tag `v*`
entsteht ein Release (als Vorabversion, solange die Pakete nicht signiert sind; Text in `RELEASE.md`):

```bash
git tag v0.80 && git push github v0.80        # im Spiegel-Repo
```

## Von Hand bauen

Auf dem jeweiligen System, mit einem Python 3, in dem Pillow (und auf dem Mac `dmgbuild`) installiert ist; auf
dem Mac dazu Homebrew, Go und die Xcode-Befehlszeilenwerkzeuge, unter Windows Inno Setup 6 und 7-Zip:

```bash
python auslieferung/bauen.py                  # nach ../balduin-bau/ausgabe/
python auslieferung/bauen.py --nur-ordner     # nur den Programmordner (../balduin-bau/arbeit/balduin)
```

Alle Quellen stehen mit Adresse und SHA-256 in `QUELLEN` in `bauen.py`; bei einer neuen Version beides ändern.

## Inhalt des Programmordners

- Code (`erfassung/`, `vorlauf/`, `export/`, `tool/`, `vorgaben/`), lesbar und vorkompiliert, dazu `VERSION`
- `python/`: Python 3.13 aus *python-build-standalone* mit den Paketen aus `requirements.txt`
- `bin/`: Siegfried mit Signaturdateien (`bin/siegfried/`, über `SIEGFRIED_HOME`), ExifTool, ffmpeg/ffprobe,
  Poppler (`bin/poppler/`), ClamAV (`bin/clamav/`, Signaturen im Datenordner der App), smartctl; unter Linux
  Poppler, ClamAV und smartctl aus der Paketverwaltung. Lizenzen: `bin/LIZENZEN.md`
- `modelle/`: Modelle der Personenerkennung; die CLIP-Modelle für „Sujet“ sind nicht dabei

Neue Projekte schlägt Balduin im Paket unter `Dokumente/Balduin-Projekte` vor (`system.projekte_vorgabe`).

## Symbol und Gestaltung

- `symbol.png` (1024 × 1024): Grundlage für `.icns` (Mac), `.ico` (Windows) und `balduin.png` (Linux), erzeugt
  beim Bau; Elefantenkopf auf weißer Fläche im Mac-Raster (824 px Fläche, leichter Schatten). Das Favicon der
  Oberfläche (`tool/web/favicon.ico`, `favicon.png`) zeigt dieselbe Fläche ohne Rand.
- **Icon Composer** (macOS 26, Liquid Glass): Liegt `mac/Balduin.icon` vor, übersetzt der Bau sie mit `actool` in
  `Assets.car`; `Balduin.icns` bleibt Rückfall für ältere Systeme. Als Vordergrund-Ebene dient
  `mac/symbol_ebenen/elefant.png` (freigestellt), der Hintergrund wird in Icon Composer als Farbe gesetzt.
- `mac/hintergrund.png` und `@2x`: Hintergrund der dmg, gezeichnet von `mac/hintergrund_zeichnen.py`; die Lage der
  Symbole steht dort und in `mac/dmg_einstellungen.py`.

## Signatur

Noch ohne Signatur: Mac nur ad hoc signiert (erster Start über Rechtsklick › „Öffnen“), Windows ohne
Code-Signing (SmartScreen-Hinweis). Mit einer Apple Developer ID bzw. einem Windows-Zertifikat kommen Signatur und
Beglaubigung als weitere Schritte in `bauen.py` hinzu.

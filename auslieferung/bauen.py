"""Balduin als Programm für Mac, Windows oder Linux bauen (Entscheidungen 13. und 14.11.2026, docs/plan.md).

Läuft auf dem jeweiligen System (GitHub Actions: .github/workflows/auslieferung.yml, oder von Hand) mit einem Python 3,
in dem Pillow (Symbole) und auf dem Mac dmgbuild installiert sind:

    python auslieferung/bauen.py                      # Programmordner und Paket nach bau/ (neben dem Code)
    python auslieferung/bauen.py --ziel <Ordner>      # anderswohin
    python auslieferung/bauen.py --nur-ordner         # nur den Programmordner, ohne dmg/Installer/Archiv

Programmordner (= Code-Ordner im Paket; system.CODE zeigt darauf):
    erfassung/ vorlauf/ export/ tool/ vorgaben/  Code, lesbar und vorkompiliert
    python/      eigenes Python 3.13 (python-build-standalone) mit den Paketen aus requirements.txt
    bin/         Werkzeuge; mit eigenen Bibliotheken in Unterordnern (bin/clamav/, bin/poppler/), LIZENZEN.md
    modelle/     Modelle der Personenerkennung (F5); CLIP (V3) kommt später auf Abruf
    VERSION      Version wie in der Kopfleiste

Ergebnis: Mac Balduin-<v>-Mac-AppleChip.dmg bzw. -Mac-Intel.dmg, Windows Balduin-<v>-Windows-Setup.exe,
Linux Balduin-<v>-Linux-x86_64-alpha.tar.gz. Jede Datei aus dem Netz wird mit ihrer SHA-256 geprüft.
"""
import argparse
import hashlib
import json
import os
import platform
import plistlib
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
CODE = HIER.parent

# Was vom Code ins Paket geht (Ordner mit „/“); Tests, Werkzeuge, Notebook und Docs bleiben draußen
KOPIEREN = ["erfassung/", "vorlauf/", "export/", "tool/", "vorgaben/", "LICENSE", "LIZENZ-ZUSATZ.md", "LICENSES/",
            "REUSE.toml", "README.md", "requirements.txt", "modelle/LIESMICH.md"]
CODE_ORDNER = ["erfassung", "vorlauf", "export", "tool"]

PLATTFORMEN = {                                  # Name: (Ziel von python-build-standalone, Name im Paket)
    "mac-arm64": ("aarch64-apple-darwin", "Mac-AppleChip"),
    "mac-x86_64": ("x86_64-apple-darwin", "Mac-Intel"),
    "windows-x86_64": ("x86_64-pc-windows-msvc", "Windows"),
    "linux-x86_64": ("x86_64-unknown-linux-gnu", "Linux-x86_64-alpha"),
}

# ---------- Quellen mit Prüfsumme (bei neuer Version Adresse und SHA-256 zusammen ändern) ----------

PBS = "https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.13.18+20261026-{}-install_only_stripped.tar.gz"
SF = "https://github.com/richardlehane/siegfried/releases/download/v1.11.9/"
SIEGFRIED_VERSION = "v1.11.9"                    # Mac: aus dem Quelltext gebaut (Go), passend zur Architektur
FFMPEG_BTBN = "https://github.com/BtbN/FFmpeg-Builds/releases/download/autobuild-2026-10-31-12-59/"
FFMPEG_MAC = "https://ffmpeg.martin-riedl.de/download/macos/"
# ExifTool: exiftool.org verweist nur auf SourceForge; die Perl-Fassung (Mac, Linux) kommt schneller aus dem GitHub-Repo
EXIFTOOL = "https://sourceforge.net/projects/exiftool/files/"

QUELLEN = {
    "python": {
        "mac-arm64": (PBS.format("aarch64-apple-darwin"), "8392b6ea51d94391befb2c31ebe75463f045d0b69dfcf5e1bb3234e1f5fa3405"),
        "mac-x86_64": (PBS.format("x86_64-apple-darwin"), "7412c19d896c99431b74a18a5643e110449a7f9590fbab179c3e5ab27b9aa9e3"),
        "windows-x86_64": (PBS.format("x86_64-pc-windows-msvc"), "7369f7a35f261222a6ac8b3a87c1c88eeebee8af945d85346202591a64038dd3"),
        "linux-x86_64": (PBS.format("x86_64-unknown-linux-gnu"), "df15fe60d3ff55bf9dcf25824b5572756bb8816ff93865a273d3301d7066a8b7"),
    },
    "siegfried": {
        "windows-x86_64": (SF + "siegfried_1-11-9_win64.zip", "d9a6e284d888f7c04d56b43b4f495101dfa99c45b8cf451e5cea44823c4d93e0"),
        "linux-x86_64": (SF + "siegfried_1-11-9_linux64.zip", "a282f1cdec1fc9c3b50aa8ab20588f5a16ba60b730ff39b37b2020721e41dee4"),
    },
    "siegfried_daten": {"*": (SF + "data_1-11-9.zip", "1a284a57d102996ab99e393dc40e7e213039ab44e1573c55fa9d9935840515cf")},
    "exiftool": {
        "windows-x86_64": (EXIFTOOL + "exiftool-13.63_64.zip/download", "7a4bff4b1d6ee15adef882837847f76c0ed23228d294feed285939b6c9b293bd"),
        "*": ("https://github.com/exiftool/exiftool/archive/refs/tags/13.63.tar.gz",
              "a306420abf76dbfc5b4ca1a9de7bb2523bc93500a075c4fc9ce543b15f09195f"),
    },
    "ffmpeg": {
        "windows-x86_64": (FFMPEG_BTBN + "ffmpeg-n9.0.2-39-g7adfbe40dc-win64-gpl-9.0.zip",
                           "693f3e224bc184b40524a62ca47526cfebaf2504414021b92fe75f677ad868b9"),
        "linux-x86_64": (FFMPEG_BTBN + "ffmpeg-n9.0.2-39-g7adfbe40dc-linux64-gpl-9.0.tar.xz",
                         "73e29a56974ae5a651133a04584c7483b21afe941e17dc91d79814a758b608d3"),
        "mac-arm64": (FFMPEG_MAC + "arm64/1789931890_9.0.2/ffmpeg.zip", "c8ed4c4e6978a03c485edbfe4e0a5dc2380f8a30bba5150531b31b094492d924"),
        "mac-x86_64": (FFMPEG_MAC + "amd64/1789931006_9.0.2/ffmpeg.zip", "7c6b4125b191cbf773832dc51f424cf2b6bb7da43007d1e066f95909e47cacd4"),
    },
    "ffprobe": {
        "mac-arm64": (FFMPEG_MAC + "arm64/1789931890_9.0.2/ffprobe.zip", "fcbe839537485eaee7a7a8bc5cbc0f90d53617e80943e8a5b2e31cb851197ea6"),
        "mac-x86_64": (FFMPEG_MAC + "amd64/1789931006_9.0.2/ffprobe.zip", "2322438ed2f6319a691291b247d09c69dcaa3a982460d1f269a7e1af335cfdfd"),
    },
    "poppler": {
        "windows-x86_64": ("https://github.com/oschwartz10612/poppler-windows/releases/download/v26.09.0-0/Release-26.09.0-0.zip",
                           "7a6f256a0ddf7536182246a5733331bf4677cbcc34f4663774947ad34556c8d0"),
    },
    "clamav": {
        "windows-x86_64": ("https://github.com/Cisco-Talos/clamav/releases/download/clamav-1.5.4/clamav-1.5.4.win.x64.zip",
                           "0d9e0228b2674137ea1a2853566c98a0278ad52ab2582c3d6dbd75373848c395"),
    },
    "smartmontools": {
        "windows-x86_64": ("https://github.com/smartmontools/smartmontools/releases/download/RELEASE_7_5/smartmontools-7.5.win32-setup.exe",
                           "896337fcc253220614cf8cdbd5cf2321c5aa326a37a04160a672a281e6104c70"),
    },
}

# Für bin/LIZENZEN.md: Werkzeug, Lizenz, Quelltext
LIZENZEN = [
    ("Python 3.13 (python-build-standalone)", "PSF-2.0 und weitere", "https://github.com/astral-sh/python-build-standalone"),
    ("Siegfried 1.11.9 (sf, roy, Signaturdateien)", "Apache-2.0", "https://github.com/richardlehane/siegfried"),
    ("ExifTool 13.63", "Artistic-1.0-Perl oder GPL-1.0-or-later", "https://exiftool.org"),
    ("FFmpeg 9.0.2 (ffmpeg, ffprobe)", "GPL-3.0-or-later (Build mit GPL-Bibliotheken)",
     "https://ffmpeg.org/download.html (Builds: github.com/BtbN/FFmpeg-Builds, ffmpeg.martin-riedl.de)"),
    ("Poppler (pdftotext, pdftoppm, pdfinfo)", "GPL-2.0-or-later", "https://poppler.freedesktop.org"),
    ("ClamAV 1.5 (clamd, clamscan, freshclam)", "GPL-2.0-only", "https://github.com/Cisco-Talos/clamav"),
    ("smartmontools 7.5 (smartctl)", "GPL-2.0-or-later", "https://github.com/smartmontools/smartmontools"),
    ("YOLOX-s (modelle/yolox_s.onnx)", "Apache-2.0", "https://github.com/Megvii-BaseDetection/YOLOX"),
    ("YuNet (modelle/yunet.onnx)", "MIT", "https://github.com/opencv/opencv_zoo"),
]


# ---------- Hilfen ----------

def melden(text):
    print(f"▸ {text}", flush=True)


def ausfuehren(befehl, **k):
    print("  $", " ".join(map(str, befehl)), flush=True)
    k.setdefault("stdin", subprocess.DEVNULL)        # nie auf eine Eingabe warten (dylibbundler fragt sonst endlos)
    subprocess.run([str(b) for b in befehl], check=True, **k)


def plattform_hier():
    system, maschine = platform.system(), platform.machine().lower()
    arch = "arm64" if maschine in ("arm64", "aarch64") else "x86_64"
    return {"Darwin": f"mac-{arch}", "Windows": f"windows-{arch}", "Linux": f"linux-{arch}"}[system]


def quelle(name, plattform):
    """(Adresse, SHA-256) einer Quelle für diese Plattform, sonst None."""
    q = QUELLEN[name]
    return q.get(plattform) or q.get("*")


def laden(name, plattform, ablage):
    """Lädt eine Quelle (einmal je Bau, im Ordner ablage) und prüft ihre SHA-256."""
    adresse, sha = quelle(name, plattform)
    datei = ablage / (name + "_" + Path(adresse.removesuffix("/download")).name)
    for versuch in range(4):                       # SourceForge bricht gelegentlich ab
        if datei.exists() and pruefsumme(datei) == sha:
            break
        melden(f"lade {adresse}" + (f" (Versuch {versuch + 1})" if versuch else ""))
        anfrage = urllib.request.Request(adresse, headers={"User-Agent": "Balduin-Bau"})
        try:
            with urllib.request.urlopen(anfrage, timeout=600) as antwort, open(datei, "wb") as f:
                shutil.copyfileobj(antwort, f, 1 << 20)
        except OSError as e:
            print(f"  Fehler: {e}", flush=True)
    if (ist := pruefsumme(datei)) != sha:
        raise SystemExit(f"Prüfsumme von {adresse} stimmt nicht:\n  erwartet {sha}\n  erhalten {ist}")
    return datei


def pruefsumme(pfad):
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def auspacken(archiv, ziel):
    """ZIP, tar.gz oder tar.xz nach ziel (Ausführrechte bleiben erhalten)."""
    ziel.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archiv):
        with zipfile.ZipFile(archiv) as z:
            for eintrag in z.infolist():
                pfad = Path(z.extract(eintrag, ziel))
                if (modus := eintrag.external_attr >> 16) & 0o111:
                    pfad.chmod(modus & 0o777 | 0o200)
    else:
        with tarfile.open(archiv) as t:
            t.extractall(ziel, filter="tar")
    return ziel


def ausfuehrbar(pfad):
    pfad.chmod(pfad.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def finden(ordner, name):
    """Erste Datei dieses Namens unter ordner."""
    treffer = sorted(ordner.rglob(name), key=lambda p: len(p.parts))
    if not treffer:
        raise SystemExit(f"{name} nicht gefunden in {ordner}")
    return treffer[0]


def version():
    """Wie die Kopfleiste: VERSION (im Spiegel) vor der Zählung der Commits."""
    datei = CODE / "VERSION"
    if datei.is_file():
        return datei.read_text(encoding="utf-8").strip()
    try:
        zahl = subprocess.run(["git", "-C", str(CODE), "rev-list", "--count", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
        return f"0.{zahl}"
    except (OSError, subprocess.CalledProcessError):
        return "0"


# ---------- Schritte ----------

def code_kopieren(ziel):
    """Code aus dem Git (nur Committetes) bzw. ohne Git aus dem Ordner, ohne __pycache__."""
    melden("Code kopieren")
    try:
        dateien = subprocess.run(["git", "-C", str(CODE), "ls-files", "-z"], capture_output=True, check=True,
                                 ).stdout.decode().split("\0")
    except (OSError, subprocess.CalledProcessError):
        dateien = [p.relative_to(CODE).as_posix() for p in CODE.rglob("*") if p.is_file()]
    for rel in dateien:
        if not rel or "__pycache__" in rel or rel.endswith(".DS_Store"):
            continue
        if any(rel == m or (m.endswith("/") and rel.startswith(m)) for m in KOPIEREN):
            (ziel / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(CODE / rel, ziel / rel)
    (ziel / "VERSION").write_text(version() + "\n", encoding="utf-8")


def python_einrichten(ziel, plattform, ablage):
    """Eigenes Python mit den Paketen aus requirements.txt; der Code wird vorkompiliert."""
    melden("Python einrichten")
    auspacken(laden("python", plattform, ablage), ziel)          # das Archiv enthält den Ordner python/
    py = python_programm(ziel, plattform)
    umgebung = {**os.environ, "PYTHONNOUSERSITE": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    # nur fertige Pakete (keine Übersetzung beim Bau); auf Intel-Macs wählt pip so die letzte passende onnxruntime
    ausfuehren([py, "-m", "pip", "install", "--no-cache-dir", "--only-binary=:all:", "--no-warn-script-location",
                "-r", ziel / "requirements.txt"], env=umgebung)
    # checked-hash: auch nach dem Kopieren durch Installer oder Finder gültig, geänderter Code wird neu übersetzt
    ausfuehren([py, "-m", "compileall", "-q", "-j", "0", "--invalidation-mode", "checked-hash",
                *[ziel / o for o in CODE_ORDNER]], env=umgebung)
    ausfuehren([py, "-c", "import pandas, numpy, PIL, plotly, onnxruntime, pyfsapfs, pyfshfs, pytsk3, jsonschema; "
                          "print('Pakete vollständig')"], env=umgebung)


def python_programm(ziel, plattform):
    return ziel / "python" / ("python.exe" if plattform.startswith("windows") else "bin/python3")


def werkzeuge_einrichten(ziel, plattform, ablage):
    bin_ = ziel / "bin"
    bin_.mkdir(exist_ok=True)
    exe = ".exe" if plattform.startswith("windows") else ""
    tmp = Path(tempfile.mkdtemp(prefix="werkzeuge_", dir=ablage))

    melden("Siegfried")
    if plattform.startswith("mac"):
        if not shutil.which("go"):
            raise SystemExit("Go fehlt (Siegfried wird auf dem Mac für die Architektur gebaut)")
        for teil in ("sf", "roy"):
            ausfuehren(["go", "install", f"github.com/richardlehane/siegfried/cmd/{teil}@{SIEGFRIED_VERSION}"],
                       env={**os.environ, "GOBIN": str(bin_), "CGO_ENABLED": "0"})
    else:
        auspacken(laden("siegfried", plattform, ablage), tmp / "sf")
        for teil in ("sf", "roy"):
            shutil.copy2(finden(tmp / "sf", teil + exe), bin_ / (teil + exe))
            ausfuehrbar(bin_ / (teil + exe))
    auspacken(laden("siegfried_daten", plattform, ablage), bin_)    # bin/siegfried/ mit default.sig (SIEGFRIED_HOME)

    melden("ExifTool")
    auspacken(laden("exiftool", plattform, ablage), tmp / "exif")
    if plattform.startswith("windows"):
        programm = finden(tmp / "exif", "exiftool(-k).exe")
        shutil.copytree(programm.parent, bin_ / "exiftool")
        (bin_ / "exiftool" / programm.name).rename(bin_ / "exiftool" / "exiftool.exe")
    else:
        quelle_ = finden(tmp / "exif", "exiftool").parent            # Perl-Skript mit lib/
        (bin_ / "exiftool").mkdir()
        shutil.copy2(quelle_ / "exiftool", bin_ / "exiftool" / "exiftool")
        shutil.copytree(quelle_ / "lib", bin_ / "exiftool" / "lib")
        ausfuehrbar(bin_ / "exiftool" / "exiftool")

    melden("ffmpeg")
    if plattform.startswith("mac"):
        for teil in ("ffmpeg", "ffprobe"):
            auspacken(laden(teil, plattform, ablage), tmp / teil)
            shutil.copy2(finden(tmp / teil, teil), bin_ / teil)
            ausfuehrbar(bin_ / teil)
    else:
        auspacken(laden("ffmpeg", plattform, ablage), tmp / "ffmpeg")
        for teil in ("ffmpeg", "ffprobe"):
            shutil.copy2(finden(tmp / "ffmpeg", teil + exe), bin_ / (teil + exe))
            ausfuehrbar(bin_ / (teil + exe))

    if plattform.startswith("windows"):
        melden("Poppler, ClamAV, smartctl (Windows)")
        auspacken(laden("poppler", plattform, ablage), tmp / "poppler")
        shutil.copytree(finden(tmp / "poppler", "pdftotext.exe").parent, bin_ / "poppler")
        auspacken(laden("clamav", plattform, ablage), tmp / "clamav")
        shutil.copytree(finden(tmp / "clamav", "clamd.exe").parent, bin_ / "clamav")
        setup = laden("smartmontools", plattform, ablage)
        ausfuehren(["7z", "x", "-y", f"-o{tmp / 'smart'}", setup], stdout=subprocess.DEVNULL)
        shutil.copy2(finden(tmp / "smart", "smartctl.exe"), bin_ / "smartctl.exe")
    elif plattform.startswith("mac"):
        mac_homebrew_werkzeuge(bin_)
    # Linux (Alpha): Poppler, ClamAV und smartctl aus der Paketverwaltung (LIESMICH-ALPHA.txt)

    shutil.rmtree(tmp, ignore_errors=True)
    zeilen = ["# Werkzeuge und Modelle in diesem Paket", "",
              "Balduin (AGPL-3.0-or-later, siehe LICENSE) ruft diese Programme als eigenständige Programme auf.", "",
              "| Werkzeug | Lizenz | Quelltext |", "|---|---|---|"]
    zeilen += [f"| {w} | {l} | {q} |" for w, l, q in LIZENZEN]
    zeilen += ["", "Die Python-Pakete liegen mit ihren Lizenzdateien unter python/ (…/site-packages/*.dist-info)."]
    (bin_ / "LIZENZEN.md").write_text("\n".join(zeilen) + "\n", encoding="utf-8")


def mac_homebrew_werkzeuge(bin_):
    """Poppler, ClamAV und smartctl aus Homebrew mit ihren Bibliotheken (dylibbundler) in Unterordner von bin/."""
    melden("Poppler, ClamAV, smartctl (Homebrew, gebündelt)")
    ausfuehren(["brew", "install", "--quiet", "poppler", "clamav", "smartmontools", "dylibbundler"])
    praefix = lambda paket: Path(subprocess.run(["brew", "--prefix", *([paket] if paket else [])],
                                                capture_output=True, text=True, check=True).stdout.strip())
    def programm(paket, name):                   # je nach Formel in bin/ oder sbin/
        for teil in ("bin", "sbin"):
            if (pfad := praefix(paket) / teil / name).exists():
                return pfad
        raise SystemExit(f"{name} fehlt in Homebrew ({paket})")
    gruppen = {"poppler": [programm("poppler", n) for n in ("pdftotext", "pdftoppm", "pdfinfo")],
               "clamav": [programm("clamav", n) for n in ("clamscan", "freshclam", "clamd")],
               "smartmontools": [programm("smartmontools", "smartctl")]}
    for gruppe, programme in gruppen.items():
        ordner = bin_ / gruppe
        ordner.mkdir()
        for p in programme:
            shutil.copy2(p.resolve(), ordner / p.name)
            (ordner / p.name).chmod(0o755)
        # Suchpfade für Bibliotheken mit @rpath; ohne sie fragt dylibbundler nach (Eingabe ist geschlossen)
        suche = [praefix("") / "lib", *{p.parent.parent / "lib" for p in programme}]
        ausfuehren(["dylibbundler", "-of", "-b", "-cd", *sum((["-x", ordner / p.name] for p in programme), []),
                    *sum((["-s", s] for s in suche), []), "-d", ordner / "lib", "-p", "@executable_path/lib/"],
                   timeout=600)
    certs = Path(subprocess.run(["brew", "--prefix"], capture_output=True, text=True, check=True).stdout.strip()) \
        / "etc" / "clamav" / "certs"
    if certs.is_dir():
        shutil.copytree(certs, bin_ / "clamav" / "certs")


def modelle_laden(ziel, ablage):
    """Modelle der Personenerkennung (F5) mitliefern; CLIP (V3, rund 600 MB) nicht (Entscheidung 13.11.2026)."""
    melden("Modelle F5")
    sys.path.insert(0, str(CODE / "werkzeuge"))
    from modelle_laden import LISTE
    for name in ("yolox_s.onnx", "yunet.onnx"):
        adresse, sha, _ = LISTE[name]
        QUELLEN[name] = {"*": (adresse, sha)}
        shutil.copy2(laden(name, "*", ablage), ziel / "modelle" / name)


# ---------- Symbole ----------

def symbole(ablage):
    """Balduin.icns (Mac) und balduin.ico (Windows) aus auslieferung/symbol.png; Pillow nötig."""
    from PIL import Image
    bild = Image.open(HIER / "symbol.png").convert("RGBA")
    bild.save(ablage / "balduin.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    bild.resize((256, 256), Image.LANCZOS).save(ablage / "balduin.png")
    if platform.system() == "Darwin":
        satz = ablage / "Balduin.iconset"
        satz.mkdir(exist_ok=True)
        for groesse in (16, 32, 128, 256, 512):
            bild.resize((groesse, groesse), Image.LANCZOS).save(satz / f"icon_{groesse}x{groesse}.png")
            bild.resize((groesse * 2, groesse * 2), Image.LANCZOS).save(satz / f"icon_{groesse}x{groesse}@2x.png")
        ausfuehren(["iconutil", "-c", "icns", satz, "-o", ablage / "Balduin.icns"])


# ---------- Pakete je Plattform ----------

def mac_paket(ordner, plattform, ausgabe, ablage):
    """Balduin.app mit Starter (Swift) und dem Programmordner in Resources/balduin, ad hoc signiert, als .dmg."""
    v = version()
    app = ablage / "Balduin.app"
    shutil.rmtree(app, ignore_errors=True)
    inhalt = app / "Contents"
    (inhalt / "MacOS").mkdir(parents=True)
    (inhalt / "Resources").mkdir()
    melden("Starter übersetzen")
    arch = "arm64" if plattform == "mac-arm64" else "x86_64"
    ausfuehren(["swiftc", "-O", "-target", f"{arch}-apple-macos11", HIER / "mac" / "Starter.swift",
                "-o", inhalt / "MacOS" / "Balduin"])
    shutil.move(str(ordner), inhalt / "Resources" / "balduin")
    shutil.copy2(ablage / "Balduin.icns", inhalt / "Resources" / "Balduin.icns")
    info = {
        "CFBundleName": "Balduin", "CFBundleDisplayName": "Balduin", "CFBundleExecutable": "Balduin",
        "CFBundleIdentifier": "digital.mitzscherling.balduin", "CFBundlePackageType": "APPL",
        "CFBundleIconFile": "Balduin", "CFBundleShortVersionString": v, "CFBundleVersion": v,
        "CFBundleDevelopmentRegion": "de", "LSMinimumSystemVersion": mac_mindestversion(),
        "LSApplicationCategoryType": "public.app-category.productivity", "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "© 2026 Marc Eric Mitzscherling · AGPL-3.0-or-later",
        # Begründungen, wenn macOS nach dem Zugriff fragt (Balduin liest Datenträger nur)
        "NSRemovableVolumesUsageDescription": "Balduin liest angeschlossene Datenträger, um sie zu registrieren und zu analysieren; es schreibt nie darauf.",
        "NSNetworkVolumesUsageDescription": "Balduin liest Ordner auf Netzlaufwerken, wenn sie als Quelle registriert sind.",
        "NSDocumentsFolderUsageDescription": "Balduin legt Projekte standardmäßig unter Dokumente/Balduin-Projekte an.",
        "NSDesktopFolderUsageDescription": "Balduin liest oder speichert dort, wenn ein Ordner auf dem Schreibtisch gewählt ist.",
        "NSDownloadsFolderUsageDescription": "Balduin liest dort, wenn ein Ordner unter Downloads als Quelle gewählt ist.",
    }
    icon_composer(inhalt, info, ablage)
    with open(inhalt / "Info.plist", "wb") as f:
        plistlib.dump(info, f)
    melden("ad hoc signieren")
    for datei in sorted((p for p in app.rglob("*") if p.is_file() and not p.is_symlink()), key=lambda p: -len(p.parts)):
        if mach_o(datei):
            subprocess.run(["codesign", "--force", "--sign", "-", "--timestamp=none", str(datei)], check=True,
                           capture_output=True)
    ausfuehren(["codesign", "--force", "--sign", "-", "--timestamp=none", app])
    ausfuehren(["codesign", "--verify", "--deep", "--strict", app])

    melden("dmg mit Hintergrund")
    hier = ablage / "dmg"
    hier.mkdir(exist_ok=True)
    for name in ("hintergrund.png", "hintergrund@2x.png"):
        shutil.copy2(HIER / "mac" / name, hier / name)
    shutil.copy2(ablage / "Balduin.icns", hier / "Balduin.icns")
    ziel = ausgabe / f"Balduin-{v}-{PLATTFORMEN[plattform][1]}.dmg"
    ausfuehren([sys.executable, "-m", "dmgbuild", "-s", HIER / "mac" / "dmg_einstellungen.py", "-D", f"app={app}",
                "-D", f"hier={hier}", f"Balduin {v}", ziel])
    return ziel


def icon_composer(inhalt, info, ablage):
    """Liegt eine Datei aus Icon Composer bereit (auslieferung/mac/Balduin.icon), wird sie mit actool übersetzt
    (Assets.car für macOS 26 mit Liquid Glass); Balduin.icns bleibt der Rückfall für ältere Systeme."""
    quelle_ = HIER / "mac" / "Balduin.icon"
    if not quelle_.exists():
        return
    melden("Symbol aus Icon Composer übersetzen")
    teil = ablage / "actool.plist"
    ausfuehren(["xcrun", "actool", quelle_, "--compile", inhalt / "Resources", "--platform", "macosx",
                "--minimum-deployment-target", info["LSMinimumSystemVersion"], "--app-icon", "Balduin",
                "--output-partial-info-plist", teil])
    with open(teil, "rb") as f:
        info.update(plistlib.load(f))                 # CFBundleIconName (und CFBundleIconFile)


def mac_mindestversion():
    """Die Bibliotheken aus Homebrew sind für das macOS des Bau-Rechners übersetzt: ab dieser Hauptversion."""
    return platform.mac_ver()[0].split(".")[0] + ".0"


def mach_o(pfad):
    try:
        with open(pfad, "rb") as f:
            kopf = f.read(4)
    except OSError:
        return False
    return kopf in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xfe\xed\xfa\xcf")


def windows_paket(ordner, plattform, ausgabe, ablage):
    """Balduin.exe (Starter im Infobereich) in den Programmordner, dann der Installer mit Inno Setup."""
    melden("Starter übersetzen")
    csc = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
    ausfuehren([csc, "/nologo", "/target:winexe", "/optimize+", f"/win32icon:{ablage / 'balduin.ico'}",
                "/r:System.Windows.Forms.dll", "/r:System.Drawing.dll", "/r:System.Core.dll",
                f"/out:{ordner / 'Balduin.exe'}", HIER / "windows" / "Starter.cs"])
    melden("Installer")
    for name in ("balduin.iss", "nach_der_installation.txt"):
        shutil.copy2(HIER / "windows" / name, ablage / name)
    iscc = shutil.which("ISCC") or r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    ausfuehren([iscc, "/Qp", f"/DVersion={version()}", f"/DQuelle={ordner}", f"/DAusgabe={ausgabe}", ablage / "balduin.iss"])
    return ausgabe / f"Balduin-{version()}-Windows-Setup.exe"


def linux_paket(ordner, plattform, ausgabe, ablage):
    """Archiv mit Startskript und Hinweis auf die Alpha-Version."""
    for name in ("balduin.sh", "menue_eintrag.sh", "LIESMICH-ALPHA.txt"):
        shutil.copy2(HIER / "linux" / name, ordner / name)
    shutil.copy2(ablage / "balduin.png", ordner / "balduin.png")
    v = version()
    ziel = ausgabe / f"Balduin-{v}-{PLATTFORMEN[plattform][1]}.tar.gz"
    with tarfile.open(ziel, "w:gz") as t:
        t.add(ordner, arcname=f"Balduin-{v}-alpha")
    return ziel


# ---------- Ablauf ----------

def main():
    for strom in (sys.stdout, sys.stderr):           # Windows-Konsole (cp1252) kennt „▸“ und Umlaute sonst nicht
        strom.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--ziel", type=Path, default=CODE.parent / "balduin-bau", help="Arbeits- und Ausgabeordner")
    ap.add_argument("--nur-ordner", action="store_true", help="nur den Programmordner, kein Paket")
    a = ap.parse_args()
    plattform = plattform_hier()
    if plattform not in PLATTFORMEN:
        raise SystemExit(f"Keine Auslieferung für {plattform}")
    ziel = a.ziel.resolve()
    ablage, ausgabe = ziel / "arbeit", ziel / "ausgabe"
    ordner = ablage / "balduin"
    for o in (ablage, ausgabe):
        o.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(ordner, ignore_errors=True)
    shutil.rmtree(ablage / "Balduin.app", ignore_errors=True)
    ordner.mkdir()
    melden(f"Balduin {version()} für {plattform} nach {ziel}")

    code_kopieren(ordner)
    python_einrichten(ordner, plattform, ablage)
    werkzeuge_einrichten(ordner, plattform, ablage)
    modelle_laden(ordner, ablage)
    if a.nur_ordner:
        melden(f"Programmordner fertig: {ordner}")
        return
    symbole(ablage)
    paket = {"mac": mac_paket, "windows": windows_paket, "linux": linux_paket}[plattform.split("-")[0]](
        ordner, plattform, ausgabe, ablage)
    (ausgabe / (paket.name + ".sha256")).write_text(f"{pruefsumme(paket)}  {paket.name}\n", encoding="utf-8")
    melden(f"Fertig: {paket} ({paket.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()

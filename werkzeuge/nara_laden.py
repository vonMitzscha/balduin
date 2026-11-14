"""NARA Digital Preservation Framework neu laden: fileformats.ttl von archives.gov nach vorgaben/nara/.

Dieselbe Quelle wie das Anton-Paket kraenzle-ritter/nara-risk (config/nara.php, „fileformats“; Entscheidung
04.11.2026), damit Balduin und Anton für dieselbe Datei dasselbe Risiko zeigen. Die Datei heißt nach ihrem Stand
(Last-Modified des Servers): NARA_fileformats_JJJJMMTT.ttl. Danach in Modul 1 Schritt H neu ausführen.

    python werkzeuge/nara_laden.py
"""
import email.utils
import sys
import urllib.request
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE))
from erfassung.archiv import nara_lesen  # noqa: E402

URL = "https://www.archives.gov/files/lod/dpframework/fileformats.ttl"
ORDNER = CODE / "vorgaben" / "nara"


def main():
    with urllib.request.urlopen(URL, timeout=60) as antwort:
        inhalt = antwort.read()
        stand = email.utils.parsedate_to_datetime(antwort.headers["Last-Modified"]).strftime("%Y%m%d")
    ziel = ORDNER / f"NARA_fileformats_{stand}.ttl"
    alt = sorted(ORDNER.glob("NARA_fileformats_*.ttl"))
    if ziel.exists() and ziel.read_bytes() == inhalt:
        print(f"Unverändert: {ziel.name}")
        return
    ziel.write_bytes(inhalt)
    neu = nara_lesen(ziel)
    print(f"Gespeichert: {ziel.name} ({len(inhalt) / 1e6:.1f} MB, {len(neu)} PRONOM-IDs)")
    if alt and alt[-1] != ziel:
        vorher = nara_lesen(alt[-1])
        anders = [p for p in neu if p in vorher and neu[p]["nara_risiko"] != vorher[p]["nara_risiko"]]
        print(f"Gegenüber {alt[-1].name}: {len(set(neu) - set(vorher))} neu, {len(set(vorher) - set(neu))} entfallen, "
              f"{len(anders)} mit anderem Risiko. Die alte Datei kann weg (git rm), wenn alles passt.")


if __name__ == "__main__":
    main()

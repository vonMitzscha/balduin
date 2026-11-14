"""Prüfsumme einer Datei auf einem Datenträger (auch in Archivdateien) und Kopie vermerken (C3).
Den Plattenvergleich als Tabelle gibt es in Balduin nicht (Entscheidung 30.10.2026); der Hinweis „≥ 95 % bitgleich“
im Panel eines Datenträgers rechnet der Server selbst."""
from .basis import *  # noqa: F401,F403


def sha256(pfad, block=1024 * 1024):
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        while stueck := f.read(block):
            h.update(stueck)
    return h.hexdigest()


def sha256_auf_platte(wurzel, relpfad, block=1024 * 1024):
    """Wie sha256, aber für einen Pfad der Platte, auch in einer Archivdatei (Entscheidung 06.11.2026)."""
    from .platte import oeffne
    h = hashlib.sha256()
    with oeffne(wurzel, relpfad) as f:
        while stueck := f.read(block):
            h.update(stueck)
    return h.hexdigest()


def kopie_vermerken(kopie_von):
    """Vermerkt bestätigte Kopien, z. B. {"HD04": "HD01"} = HD04 ist eine Kopie von HD01."""
    for kopie, original in kopie_von.items():
        with db() as con:
            alt = con.execute("SELECT kopie_von FROM platte WHERE platte_id = ?", (kopie,)).fetchone()
            con.execute("UPDATE platte SET kopie_von = ? WHERE platte_id = ?", (original, kopie))
        protokolliere("C3", kopie, "kopie_von", alt[0] if alt else "", original)
        print(f"{kopie} als Kopie von {original} vermerkt.")

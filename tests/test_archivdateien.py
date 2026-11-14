"""Archivdateien (ZIP, tar, gz) werden wie Ordner behandelt (Entscheidung 06.11.2026, docs/plan.md).

C liest den Inhalt der Archivdatei nur lesend von der Platte; jede Datei darin wird ein eigener Eintrag mit dem Pfad
<Archivdatei>/<Pfad darin>, als wäre die Archivdatei ein Ordner. Die Archivdatei selbst steht in der Tabelle
archivdatei (Art, Status, Zahl der Dateien, Prüfsummen). Archive, die sich nicht auflösen lassen (defekt,
verschlüsselt), bleiben eine gewöhnliche Datei und tragen den Grund in archivdatei.
"""
import gzip
import hashlib
import io
import json
import tarfile
import time
import zipfile
from pathlib import Path

import pytest

from conftest import abfrage, fingerabdruck, integration_noetig, lauf_ausfuehren

MAC_NAME = "Gro\u0308sse.txt"     # so schreibt das Archivprogramm des Mac: NFD, UTF-8 ohne Kennzeichen
MAC_NFC = "Gr\u00f6sse.txt"       # so steht der Name in der Datenbank (nfc)


def zip_bytes(eintraege, datum=(2015, 10, 21, 14, 30, 0)):
    """ZIP im Speicher: eintraege = {Name: Inhalt (bytes)}; Namen mit „/“ am Ende sind Ordner."""
    puffer = io.BytesIO()
    with zipfile.ZipFile(puffer, "w", zipfile.ZIP_DEFLATED) as z:
        for name, inhalt in eintraege.items():
            z.writestr(zipfile.ZipInfo(name, date_time=datum), inhalt)
    return puffer.getvalue()


def verschluesseln(daten):
    """Setzt in jedem Eintrag das Bit „verschlüsselt“ (Python kann keine verschlüsselten ZIPs schreiben)."""
    b = bytearray(daten)
    for kopf, stelle in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        i = b.find(kopf)
        while i >= 0:
            b[i + stelle] |= 1
            i = b.find(kopf, i + 4)
    return bytes(b)


def mac_zip():
    """ZIP mit UTF-8-Namen ohne UTF-8-Kennzeichen (Archivprogramm des Mac): Python liest sie als CP437."""
    roh = MAC_NAME.encode("utf-8")
    platzhalter = b"X" * len(roh)
    daten = zip_bytes({platzhalter.decode(): b"mac\n"})
    return daten.replace(platzhalter, roh)


def tar_gz_bytes(eintraege):
    puffer = io.BytesIO()
    with tarfile.open(fileobj=puffer, mode="w:gz") as t:
        for name, inhalt in eintraege.items():
            info = tarfile.TarInfo(name)
            info.size, info.mtime = len(inhalt), 1_445_430_600     # 21.10.2015 12:30 UTC
            t.addfile(info, io.BytesIO(inhalt))
    return puffer.getvalue()


def jpeg_bytes():
    from PIL import Image
    puffer = io.BytesIO()
    Image.new("RGB", (320, 240), (200, 60, 30)).save(puffer, "JPEG")
    return puffer.getvalue()


FOTO = jpeg_bytes()

INHALT = {
    "Fotos.zip/Messe/foto.jpg": FOTO,
    "Lieferung.zip/bilder/a.txt": b"a" * 100,
    "Lieferung.zip/b.txt": b"bbb\n",
    "Lieferung.zip/__MACOSX/._b.txt": b"\x00\x05\x16\x07",
    "Lieferung.zip/innen.zip/c.txt": b"c im zip im zip\n",
    "paket.tar.gz/d/d.txt": b"d aus tar.gz\n",
    "notiz.txt.gz/notiz.txt": b"nur gzip\n",
    "Lieferung.zip/sicher/x.txt": b"zip-slip\n",            # im ZIP als „../sicher/x.txt“
    f"mac.zip/{MAC_NFC}": b"mac\n",
}


@pytest.fixture
def archivplatte(leeres_projekt):
    """Datenträger ARCH unter den Test-Volumes mit Archivdateien aller Fälle."""
    leeres_projekt.min_frei_gb = 1        # Testplatten sind klein: nicht am freien Platz des Rechners scheitern
    w = leeres_projekt.volumes / "ARCH"
    (w / "Ordner").mkdir(parents=True)
    (w / "Ordner" / "frei.txt").write_bytes(b"liegt frei\n")                 # Bytes: Windows schriebe \r\n
    (w / "Lieferung.zip").write_bytes(zip_bytes({
        "bilder/": b"", "bilder/a.txt": b"a" * 100, "b.txt": b"bbb\n", "__MACOSX/._b.txt": b"\x00\x05\x16\x07",
        "innen.zip": zip_bytes({"c.txt": b"c im zip im zip\n"}), "../sicher/x.txt": b"zip-slip\n"}))
    (w / "Fotos.zip").write_bytes(zip_bytes({"Messe/foto.jpg": FOTO}))
    (w / "paket.tar.gz").write_bytes(tar_gz_bytes({"d/d.txt": b"d aus tar.gz\n"}))
    (w / "notiz.txt.gz").write_bytes(gzip.compress(b"nur gzip\n"))
    (w / "mac.zip").write_bytes(mac_zip())
    (w / "defekt.zip").write_bytes(zip_bytes({"e.txt": b"e"})[:40])
    (w / "geheim.zip").write_bytes(verschluesseln(zip_bytes({"f.txt": b"geheim"})))
    (w / "Bericht.docx").write_bytes(zip_bytes({"word/document.xml": b"<w/>"}))   # Office ist ZIP, bleibt Datei
    return w.resolve()


def scannen(wurzel):
    from erfassung import platte, schnellscan
    platte.registrieren("HD01", wurzel)
    schnellscan.schnellscan("HD01", wurzel)


def zeilen(sql, *werte):
    from erfassung.basis import db
    with db() as con:
        return con.execute(sql, werte).fetchall()


# ---------- Erkennen ----------

@pytest.mark.parametrize("name, art", [
    ("a.zip", "zip"), ("A.ZIP", "zip"), ("a.tar", "tar"), ("a.tar.gz", "tar"), ("a.tgz", "tar"),
    ("a.tar.bz2", "tar"), ("a.tar.xz", "tar"), ("a.txt.gz", "gz"), ("a.bz2", "bz2"), ("a.xz", "xz"),
    ("a.docx", None), ("a.xlsx", None), ("a.sit", None), ("a.rar", None), ("a.dmg", None), ("a.7z", None),
    ("a.zip.txt", None),
])
def test_art_nach_endung(name, art):
    from erfassung import archivdateien
    assert archivdateien.art_von(name) == art


# ---------- C: Inhalt erfassen ----------

def test_schnellscan_erfasst_den_inhalt_wie_einen_ordner(archivplatte):
    scannen(archivplatte)
    pfade = {r for (r,) in zeilen("SELECT relpfad FROM schnellscan WHERE platte_id = 'HD01'")}
    assert set(INHALT) <= pfade
    assert "Ordner/frei.txt" in pfade and "Bericht.docx" in pfade
    # aufgelöste Archive sind keine Datei mehr, sondern ein Ordner
    for archiv in ("Lieferung.zip", "Lieferung.zip/innen.zip", "paket.tar.gz", "notiz.txt.gz", "mac.zip"):
        assert archiv not in pfade
    # nicht auflösbare bleiben Dateien
    assert {"defekt.zip", "geheim.zip"} <= pfade
    # Ordnereinträge des ZIP sind keine Dateien
    assert "Lieferung.zip/bilder" not in pfade


def test_groesse_datum_und_archiv_der_eintraege(archivplatte):
    scannen(archivplatte)
    z = {r: (g, m, a) for r, g, m, a in zeilen("SELECT relpfad, groesse, mtime, archiv FROM schnellscan")}
    assert z["Lieferung.zip/bilder/a.txt"][0] == 100
    # Datum aus dem ZIP (Ortszeit ohne Zone) und aus dem tar (UTC)
    assert z["Lieferung.zip/b.txt"][1] == time.mktime((2015, 10, 21, 14, 30, 0, 0, 0, -1))
    assert z["paket.tar.gz/d/d.txt"][1] == 1_445_430_600
    # archiv = die Archivdatei auf der Platte (äußerste), leer für frei liegende Dateien
    assert z["Lieferung.zip/innen.zip/c.txt"][2] == "Lieferung.zip"
    assert z["paket.tar.gz/d/d.txt"][2] == "paket.tar.gz"
    assert z["Ordner/frei.txt"][2] is None and z["defekt.zip"][2] is None


def test_tabelle_archivdatei(archivplatte):
    scannen(archivplatte)
    a = {r: dict(art=art, status=s, dateien=n) for r, art, s, n in
         zeilen("SELECT relpfad, art, status, dateien FROM archivdatei WHERE platte_id = 'HD01'")}
    assert a["Lieferung.zip"] == {"art": "zip", "status": "aufgelöst", "dateien": 5}
    assert a["Lieferung.zip/innen.zip"] == {"art": "zip", "status": "aufgelöst", "dateien": 1}
    assert a["paket.tar.gz"]["status"] == "aufgelöst"
    assert a["notiz.txt.gz"] == {"art": "gz", "status": "aufgelöst", "dateien": 1}
    assert a["defekt.zip"]["status"] == "defekt"
    assert a["geheim.zip"]["status"] == "verschlüsselt"
    assert "Bericht.docx" not in a
    groesse = zeilen("SELECT groesse FROM archivdatei WHERE relpfad = 'Lieferung.zip'")[0][0]
    assert groesse == (archivplatte / "Lieferung.zip").stat().st_size


def test_mac_namen_werden_richtig_gelesen(archivplatte):
    scannen(archivplatte)
    assert zeilen("SELECT name FROM schnellscan WHERE relpfad = ?", f"mac.zip/{MAC_NFC}") == [(MAC_NFC,)]


def test_macosx_gilt_als_systemdatei():
    from erfassung.basis import ist_systemdatei
    assert ist_systemdatei("Lieferung.zip/__MACOSX/bilder/._a.txt")
    assert ist_systemdatei("Lieferung.zip/__MACOSX/irgendwas.txt")
    assert not ist_systemdatei("Lieferung.zip/bilder/a.txt")


def test_neu_scannen_doppelt_nichts(archivplatte):
    scannen(archivplatte)
    vorher = zeilen("SELECT * FROM archivdatei ORDER BY relpfad")
    scannen(archivplatte)
    assert zeilen("SELECT * FROM archivdatei ORDER BY relpfad")[:] != []
    assert [z[:6] for z in zeilen("SELECT * FROM archivdatei ORDER BY relpfad")] == [z[:6] for z in vorher]


def test_quelle_bleibt_unveraendert(archivplatte):
    from erfassung import pruefsummen
    abdruck = fingerabdruck(archivplatte)
    scannen(archivplatte)
    pruefsummen.dateiliste_abgleichen("HD01")
    pruefsummen.vollscan_pruefsummen("HD01", archivplatte)
    assert fingerabdruck(archivplatte) == abdruck


# ---------- Lesen aus dem Archiv ----------

@pytest.mark.parametrize("relpfad", sorted(INHALT))
def test_oeffne_liest_aus_dem_archiv(archivplatte, relpfad):
    from erfassung.platte import oeffne
    scannen(archivplatte)
    with oeffne(archivplatte, relpfad) as f:
        assert f.read() == INHALT[relpfad]


def test_oeffne_frei_liegende_datei_wie_bisher(archivplatte):
    from erfassung.platte import oeffne
    with oeffne(archivplatte, "Ordner/frei.txt") as f:
        assert f.read() == b"liegt frei\n"


def test_oeffne_meldet_fehlende_datei(archivplatte):
    from erfassung.platte import oeffne
    with pytest.raises(OSError):
        oeffne(archivplatte, "Lieferung.zip/gibt-es-nicht.txt")


def test_durchlaufen_liefert_alle_gesuchten_in_einem_zug(archivplatte):
    from erfassung import archivdateien
    gesucht = {"Lieferung.zip/b.txt", "Lieferung.zip/innen.zip/c.txt", "Lieferung.zip/sicher/x.txt"}
    gefunden = {r: f.read() for r, f in archivdateien.durchlaufen(archivplatte, "Lieferung.zip", gesucht)}
    assert gefunden == {r: INHALT[r] for r in gesucht}


@pytest.mark.parametrize("innen, inhalt, erwartet", [
    ("innen.zip", zip_bytes({"c.txt": b"zip im tar\n"}), "innen.zip/c.txt"),
    ("notiz.txt.gz", gzip.compress(b"gz im tar\n"), "notiz.txt.gz/notiz.txt"),
])
def test_durchlaufen_liest_archive_im_tar_strom(leeres_projekt, innen, inhalt, erwartet):
    """Fehler vom 12.11.2026 (D1 an einem USB-Stick): Dateien im tar-Strom kennen kein seekable()."""
    from erfassung import archivdateien
    w = leeres_projekt.volumes / "TARSTROM"
    w.mkdir(parents=True)
    puffer = io.BytesIO()
    with tarfile.open(fileobj=puffer, mode="w") as t:
        info = tarfile.TarInfo(innen)
        info.size = len(inhalt)
        t.addfile(info, io.BytesIO(inhalt))
    (w / "paket.tar").write_bytes(puffer.getvalue())
    voll = f"paket.tar/{erwartet}"
    gefunden = {r: f.read() for r, f in archivdateien.durchlaufen(w.resolve(), "paket.tar", {voll})}
    assert gefunden == {voll: (b"zip im tar\n" if innen.endswith(".zip") else b"gz im tar\n")}


# ---------- D1: Prüfsummen ----------

def test_pruefsummen_der_eintraege_und_der_archivdatei(archivplatte):
    from erfassung import pruefsummen
    scannen(archivplatte)
    pruefsummen.dateiliste_abgleichen("HD01")
    pruefsummen.vollscan_pruefsummen("HD01", archivplatte)
    sha = dict(zeilen("SELECT relpfad, sha256 FROM datei WHERE platte_id = 'HD01'"))
    for relpfad, inhalt in INHALT.items():
        assert sha[relpfad] == hashlib.sha256(inhalt).hexdigest(), relpfad
    # Prüfsummen der Archivdatei selbst (für die Bestandsgeschichte: „entpackt aus … (MD5 …)“)
    md5 = dict(zeilen("SELECT relpfad, md5 FROM archivdatei WHERE platte_id = 'HD01' AND md5 IS NOT NULL"))
    assert md5["Lieferung.zip"] == hashlib.md5((archivplatte / "Lieferung.zip").read_bytes()).hexdigest()
    assert md5["geheim.zip"] == hashlib.md5((archivplatte / "geheim.zip").read_bytes()).hexdigest()
    assert "Lieferung.zip/innen.zip" in md5


# ---------- Stichprobe zum Wiedererkennen der Platte ----------

def test_stichprobe_nimmt_nur_frei_liegende_dateien(archivplatte):
    from erfassung import platte
    scannen(archivplatte)
    geprueft, abweichend = platte.stichprobe_pruefen("HD01", archivplatte, anzahl=100)
    assert abweichend == []
    assert geprueft == len(zeilen("SELECT 1 FROM schnellscan WHERE archiv IS NULL"))


def test_plattenvergleich_hasht_auch_dateien_in_archiven(archivplatte):
    from erfassung import vergleich
    scannen(archivplatte)
    assert vergleich.sha256_auf_platte(archivplatte, "Lieferung.zip/innen.zip/c.txt") == \
        hashlib.sha256(INHALT["Lieferung.zip/innen.zip/c.txt"]).hexdigest()


# ---------- Bereitstellen für Werkzeuge, die einen Dateipfad brauchen (D2, D3, E, E4, F) ----------

def test_bereitstellen_entpackt_nur_die_gesuchten_und_raeumt_auf(archivplatte):
    import os
    from erfassung import archivdateien
    from erfassung.basis import P, quellpfad
    scannen(archivplatte)
    gesucht = ["Ordner/frei.txt", "Lieferung.zip/innen.zip/c.txt", "paket.tar.gz/d/d.txt"]
    with archivdateien.bereitstellen("HD01", archivplatte, gesucht) as pfad:
        assert pfad("Ordner/frei.txt") == quellpfad(archivplatte, "Ordner/frei.txt")
        for r in gesucht[1:]:
            lokal = Path(pfad(r))
            assert lokal.read_bytes() == INHALT[r]
            assert lokal.name == r.rsplit("/", 1)[-1]                  # Name und Endung bleiben (Werkzeuge)
            assert P.ordner in lokal.parents                            # im Projekt, nie auf der Platte
            mtime = zeilen("SELECT mtime FROM schnellscan WHERE relpfad = ?", r)[0][0]
            assert os.stat(lokal).st_mtime == pytest.approx(mtime, abs=1)
            assert pfad.relpfad(lokal) == r                              # zurück zum Pfad der Platte
        ordner = Path(pfad(gesucht[1])).parent
        assert not (Path(pfad(gesucht[1])).parent / "b.txt").exists()   # nur, was gesucht war
    assert not ordner.exists()
    assert not (P.ordner / "entpackt").exists() or not any((P.ordner / "entpackt").iterdir())


def test_bereitstellen_ohne_archive_entpackt_nichts(archivplatte):
    from erfassung import archivdateien
    from erfassung.basis import P
    scannen(archivplatte)
    with archivdateien.bereitstellen("HD01", archivplatte, ["Ordner/frei.txt"]) as pfad:
        assert pfad.relpfad(pfad("Ordner/frei.txt")) == "Ordner/frei.txt"
        assert not (P.ordner / "entpackt").exists()


# ---------- Ganzer Analyselauf B–I über eine Platte mit Archivdateien ----------

def test_analyse_bis_i_auch_fuer_dateien_in_archiven(archivplatte, leeres_projekt):
    integration_noetig()
    abdruck = fingerabdruck(archivplatte)
    ordner = leeres_projekt.ordner
    einstellungen = json.loads((ordner / "projekt.json").read_text(encoding="utf-8"))
    einstellungen["speicher"]["min_frei_gb"] = 1          # Testplatten sind klein (wie die übrigen Testprojekte)
    (ordner / "projekt.json").write_text(json.dumps(einstellungen), encoding="utf-8")
    lauf_ausfuehren(ordner, leeres_projekt.volumes, "erfassen", {
        "platte_id": "HD01", "mountpunkt": str(archivplatte), "beschreibbar_ok": True, "etikett": "Archive"}, "HD01")
    assert fingerabdruck(archivplatte) == abdruck
    foto = "Fotos.zip/Messe/foto.jpg"
    d = abfrage(ordner, "SELECT * FROM datei WHERE platte_id = 'HD01' AND relpfad = ?", foto)[0]
    assert d["sha256"] == hashlib.sha256(FOTO).hexdigest() and not d["hash_fehler"]
    assert d["puid"] and d["puid"].startswith("fmt/") and "JPEG" in (d["format"] or "") and not d["sf_fehler"]
    # Pfade aus Siegfried kommen als Pfade der Platte zurück, nicht als Pfade im Arbeitsordner
    assert not abfrage(ordner, "SELECT relpfad FROM datei WHERE relpfad LIKE '%entpackt%'")
    m = abfrage(ordner, "SELECT * FROM metadaten WHERE platte_id = 'HD01' AND relpfad = ?", foto)[0]
    assert not m["fehler"] and m["breite"] == 320
    v = abfrage(ordner, "SELECT * FROM exif_voll WHERE sha256 = ?", d["sha256"])[0]
    assert not v["fehler"] and v["felder"] > 5
    assert "entpackt" not in __import__("zlib").decompress(v["daten"]).decode()   # kein Fundort aus dem Arbeitsordner
    assert abfrage(ordner, "SELECT 1 FROM vorschau WHERE sha256 = ? AND datei IS NOT NULL AND fehler IS NULL", d["sha256"])
    t = abfrage(ordner, "SELECT * FROM volltext WHERE sha256 = ?", hashlib.sha256(INHALT["Lieferung.zip/b.txt"]).hexdigest())[0]
    assert not t["fehler"] and t["zeichen"] == 3
    assert not (Path(ordner) / "entpackt").exists() or not any((Path(ordner) / "entpackt").iterdir())


def test_virenscan_prueft_dateien_in_archiven(archivplatte, monkeypatch):
    """D3 mit nachgebautem clamd: jede Datei im Archiv wird als echte Datei im Projekt geprüft, ein Fund trifft den
    Inhalt der Datei im Archiv (nicht die Archivdatei)."""
    from erfassung import pruefsummen, virenscan
    from erfassung.basis import P

    geprueft = {}

    class Nachbau:
        def __init__(self, parallel, log):
            pass

        def pruefe(self, pfad):
            pfad = Path(pfad)
            geprueft[pfad.name] = pfad.exists() and P.ordner in pfad.parents
            return "Test.Fund FOUND" if pfad.read_bytes() == INHALT["Lieferung.zip/b.txt"] else "OK"

        def beenden(self):
            pass

    monkeypatch.setattr(virenscan, "Clamd", Nachbau)
    monkeypatch.setattr(virenscan, "signaturen_auffrischen", lambda *a, **k: "ClamAV Nachbau")
    monkeypatch.setattr(virenscan, "angeschlossene_platte_pruefen", lambda *a: None)
    scannen(archivplatte)
    pruefsummen.dateiliste_abgleichen("HD01")
    pruefsummen.vollscan_pruefsummen("HD01", archivplatte)
    virenscan.virenscan("HD01", archivplatte, parallel=2)
    assert geprueft["c.txt"] is True and geprueft["foto.jpg"] is True     # entpackt im Projekt
    assert geprueft["frei.txt"] is False                                   # frei liegend: direkt auf der Platte
    befund = dict(zeilen("SELECT geprueft_an, befund FROM virenscan"))
    assert befund["HD01:Lieferung.zip/b.txt"] == "Fund"
    assert not (P.ordner / "entpackt").exists()


# ---------- Baum: eigenes Symbol für Archivdateien ----------

def test_baum_zeigt_archivdateien_mit_eigenem_symbol():
    """Ein Ordner, der eine aufgelöste Archivdatei ist, bekommt im Baum „folder-archive“ statt „folder“ (Wunsch
    06.11.2026); Bewertung und Erschließung nutzen dafür ordnerIcon aus tool/web/icons.js."""
    import shutil
    import subprocess
    from conftest import CODE
    if not shutil.which("node"):
        pytest.skip("node fehlt")
    web = CODE / "tool" / "web"
    skript = ("globalThis.window = {};\n" + (web / "icons.js").read_text(encoding="utf-8")
              + "\nconsole.log(JSON.stringify(['Lieferung.zip', 'paket.tar.gz', 'x.TGZ', 'Fotos', 'zip', 'a.zip.alt']"
                ".map((n) => ordnerIcon(n, 'symbol'))));")
    e = subprocess.run(["node", "-e", skript], capture_output=True, text=True, timeout=30)
    assert e.returncode == 0, e.stderr
    zip_, tar, tgz, ordner, nur_zip, alt = json.loads(e.stdout)
    for s in (zip_, tar, tgz):
        assert "#folder-archive" in s and "Archivdatei" in s and "symbol" in s
    for s in (ordner, nur_zip, alt):
        assert "#folder\"" in s and "Archivdatei" not in s
    for datei in ("app.js", "erschliessung.js"):
        assert "ordnerIcon(" in (web / datei).read_text(encoding="utf-8"), datei


# ---------- Server: Systemdateien und „Datei zeigen“ ----------

def test_server_kennt_macosx_als_systemdatei():
    import server
    assert server.ist_systemdatei("Lieferung.zip/__MACOSX/._b.txt")
    assert server.ist_systemdatei("Lieferung.zip/__MACOSX/b.txt")
    assert not server.ist_systemdatei("Lieferung.zip/b.txt")


def test_server_findet_die_archivdatei_ueber_einer_datei(archivplatte):
    """„Datei zeigen“: Der Finder kann nicht in ein Archiv schauen; gezeigt wird die Archivdatei auf der Platte."""
    import server
    assert server.archivdatei_darueber(archivplatte, "Lieferung.zip/innen.zip/c.txt") == archivplatte / "Lieferung.zip"
    assert server.archivdatei_darueber(archivplatte, "Ordner/frei.txt") is None
    assert server.archivdatei_darueber(archivplatte, "Ordner/fehlt.txt") is None


# ---------- Export: aus dem Archiv direkt ins Paket ----------

def test_paket_liest_dateien_direkt_aus_dem_archiv(archivplatte, tmp_path):
    from export import bauen
    from erfassung import pruefsummen
    scannen(archivplatte)
    pruefsummen.dateiliste_abgleichen("HD01")
    pruefsummen.vollscan_pruefsummen("HD01", archivplatte)
    abdruck = fingerabdruck(archivplatte)
    rel = ["Lieferung.zip/innen.zip/c.txt", "paket.tar.gz/d/d.txt", "Fotos.zip/Messe/foto.jpg", "Ordner/frei.txt"]
    werte = {r: z for r, *z in zeilen(f"SELECT relpfad, groesse, md5, sha256 FROM datei WHERE relpfad IN "
                                      f"({','.join('?' * len(rel))})", *rel)}
    dateien = [(i, r, *werte[r], None) for i, r in enumerate(rel, 1)]
    ziel = tmp_path / "HD01_1-agate-1.tar"
    bauen.tar_schreiben(ziel, ziel.name, {"generator": "Test", "entries": []}, dateien, archivplatte, platte_id="HD01")
    assert fingerabdruck(archivplatte) == abdruck
    fehler, anzahl, _ = bauen.bag_pruefen(ziel)
    assert not fehler and anzahl == len(rel) + 1           # mit metadata.json
    with tarfile.open(ziel) as t:
        for r in rel[:3]:
            m = t.getmember(f"data/content/{r}")
            assert t.extractfile(m).read() == INHALT[r]
            assert m.mtime == int(zeilen("SELECT mtime FROM schnellscan WHERE relpfad = ?", r)[0][0])


def test_paket_meldet_veraenderte_datei_im_archiv(archivplatte, tmp_path):
    from export import bauen
    scannen(archivplatte)
    groesse = len(INHALT["Lieferung.zip/b.txt"])
    dateien = [(1, "Lieferung.zip/b.txt", groesse, "0" * 32, "0" * 64, None)]
    with pytest.raises(bauen.Abweichung):
        bauen.tar_schreiben(tmp_path / "x.tar", "x.tar", {"generator": "Test", "entries": []}, dateien, archivplatte,
                            platte_id="HD01")
    dateien = [(1, "Lieferung.zip/fehlt.txt", 3, "0" * 32, "0" * 64, None)]
    with pytest.raises(bauen.Abweichung, match="nicht mehr"):
        bauen.tar_schreiben(tmp_path / "y.tar", "y.tar", {"generator": "Test", "entries": []}, dateien, archivplatte,
                            platte_id="HD01")


def test_bestandsgeschichte_nennt_die_archivdatei():
    """„Entpackt aus …“ mit der MD5 jeder Archivdatei auf dem Weg, von außen nach innen (für note.custod_hist)."""
    import pakete
    archive = {("HD01", "Lieferung.zip"): "a" * 32, ("HD01", "Lieferung.zip/innen.zip"): "b" * 32}
    assert pakete.archivherkunft("HD01", "Lieferung.zip/innen.zip/c.txt", archive) == (
        f"Entpackt aus der Archivdatei „Lieferung.zip“ (MD5 {'a' * 32}), darin „innen.zip“ (MD5 {'b' * 32}).")
    assert pakete.archivherkunft("HD01", "Lieferung.zip", archive) == (
        f"Entpackt aus der Archivdatei „Lieferung.zip“ (MD5 {'a' * 32}).")          # Ordner = Archiv (Einzelstück)
    assert pakete.archivherkunft("HD01", "Ordner/frei.txt", archive) == ""
    assert pakete.archivherkunft("HD02", "Lieferung.zip/b.txt", archive) == ""


# ---------- Ältere Platten: C ist offen, solange Archivdateien ungeprüft sind ----------

def alter_schnellscan(wurzel):
    """Stand vor dem 06.11.2026: Archivdateien als gewöhnliche Dateien, ohne Zeile in archivdatei."""
    from erfassung.basis import db
    scannen(wurzel)
    with db() as con:
        con.execute("DELETE FROM schnellscan WHERE archiv IS NOT NULL")
        con.execute("DELETE FROM archivdatei")
        for name in ("Lieferung.zip", "paket.tar.gz", "notiz.txt.gz"):
            con.execute("INSERT INTO schnellscan (platte_id, relpfad, name, groesse, mtime) VALUES ('HD01', ?, ?, 1, 0)",
                        (name, name))


def test_ungepruefte_archivdateien_halten_c_offen(archivplatte):
    from erfassung import lauf, schnellscan
    alter_schnellscan(archivplatte)
    assert schnellscan.archive_ungeprueft("HD01") == 3 + 2       # dazu defekt.zip und geheim.zip ohne Zeile
    auftrag = {"platte_id": "HD01", "mountpunkt": str(archivplatte), "modus": "fortsetzen"}
    lauf.schritt_c(auftrag)                                       # liest neu statt „übersprungen“
    assert schnellscan.archive_ungeprueft("HD01") == 0
    with pytest.raises(lauf.Uebersprungen):
        lauf.schritt_c(auftrag)


def test_server_zaehlt_ungepruefte_archivdateien_als_offen(archivplatte):
    import server
    from erfassung.basis import db
    alter_schnellscan(archivplatte)
    with db() as con:
        assert dict(con.execute(server.ARCHIVE_UNGEPRUEFT_SQL).fetchall()) == {"HD01": 5}
    scannen(archivplatte)
    with db() as con:
        assert dict(con.execute(server.ARCHIVE_UNGEPRUEFT_SQL).fetchall()) == {}


def test_server_ruestet_aeltere_datenbank_nach(leeres_projekt, tmp_path):
    """Startet das Tool vor dem ersten Lauf, legt es Spalte archiv und Tabelle archivdatei selbst an."""
    import sqlite3
    import server
    con = sqlite3.connect(leeres_projekt.db_pfad)
    con.execute("DROP TABLE archivdatei")
    con.execute("ALTER TABLE schnellscan DROP COLUMN archiv")         # Stand vor dem 06.11.2026
    con.execute("INSERT INTO schnellscan VALUES ('HD01', 'a.zip', 'a.zip', 1, 0, 1)")
    con.commit()
    con.close()
    server.Bestand(leeres_projekt.db_pfad, tmp_path / "vorschauen")
    con = sqlite3.connect(leeres_projekt.db_pfad)
    assert dict(con.execute(server.ARCHIVE_UNGEPRUEFT_SQL).fetchall()) == {"HD01": 1}
    con.close()


def test_appledouble_neben_einem_zip_ist_kein_archiv(archivplatte):
    """UTM-Test 13.11.2026: Ein Stick, der am Mac war, trägt zu jeder Datei eine AppleDouble-Datei („._alt.zip“).
    Sie ist eine Systemdatei, kein (defektes) Archiv, und hält C nicht offen."""
    from erfassung import schnellscan
    from erfassung.archivdateien import art_von
    assert art_von("._alt.zip") is None and art_von("._paket.tar.gz") is None
    (archivplatte / "._Fotos.zip").write_bytes(b"\x00\x05\x16\x07" + bytes(60))
    scannen(archivplatte)
    assert zeilen("SELECT relpfad FROM archivdatei WHERE relpfad LIKE '%._Fotos.zip'") == []
    assert zeilen(schnellscan.ARCHIVE_UNGEPRUEFT, "HD01")[0][1] == 0


def test_bereit_nennt_keine_zelle_des_notebooks(tmp_path, capsys, monkeypatch):
    """Die Meldung erscheint auch im Lauf in Balduin; dort gibt es keine Zelle UMSCHALTEN."""
    from erfassung import platte
    monkeypatch.setattr(platte, "ist_schreibgeschuetzt", lambda p: False)
    assert platte.bereit(tmp_path) is False
    assert "UMSCHALTEN" not in capsys.readouterr().out

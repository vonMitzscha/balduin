"""Modul 4, Paketbau ohne Projekt und ohne Platten (schnell): Aufbau des BagIt-tar, Manifeste, Schema, Abweichung der
Prüfsumme, Dubletten, Fortsetzen nach einem Abbruch (Antwort K&R vom 05.11.2026, „Tests für den Paketbau“)."""
import hashlib
import re
import sys
import tarfile
import uuid
from pathlib import Path

import pytest

from export import bauen

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tool"))
import pakete  # noqa: E402  (Planen im Server: Namen der Pakete)

INHALTE = {"Fotos/2001/IMG_0001.JPG": b"\xff\xd8 Bild eins " * 4000,
           "Fotos/2001/Müller Übergabe.jpg": b"\xff\xd8 Bild zwei " * 3000,        # Umlaute
           "Texte/" + ("sehr langer Ordnername " * 6).strip() + "/Bericht.pdf": b"%PDF-1.4 " * 9000}   # Pfad über 100
# Zeichen; der Ordnername endet nicht mit einem Leerzeichen, das schneidet Windows still ab (Windows-VM, 12.11.2026)


@pytest.fixture
def platte(tmp_path):
    """Kleine „Platte“ als Ordner mit drei Dateien; Angaben wie aus der Analyse (D1)."""
    wurzel = tmp_path / "HD09"
    dateien = []
    for nr, (relpfad, inhalt) in enumerate(INHALTE.items()):
        pfad = wurzel / relpfad
        pfad.parent.mkdir(parents=True, exist_ok=True)
        pfad.write_bytes(inhalt)
        dateien.append((nr, relpfad, len(inhalt), hashlib.md5(inhalt).hexdigest(), hashlib.sha256(inhalt).hexdigest(), None))
    return wurzel, dateien


def metadata(dateien):
    """metadata.json nach Schema 0.6: eine neue Ebene, darunter je Datei ein Einzelstück."""
    ebene = str(uuid.uuid4())
    eintraege = [{"uuid": ebene, "type": "collection", "level_of_description": "file", "title": {"de": "Messe 2001"}}]
    for _, relpfad, groesse, md5, _, _ in dateien:
        eintraege.append({"uuid": str(uuid.uuid4()), "type": "record", "level_of_description": "item",
                          "title": {"de": relpfad.rsplit("/", 1)[-1]}, "parent": {"uuid": ebene},
                          "files": [{"uuid": str(uuid.uuid4()), "name": relpfad.rsplit("/", 1)[-1], "file_path": relpfad,
                                     "mime_type": "image/jpeg", "md5sum": md5, "size_bytes": groesse}]})
    return {"version": "0.6", "generator": "balduin@0", "entries": eintraege}


def bauen_nach(ziel, platte, **mehr):
    wurzel, dateien = platte
    return bauen.tar_schreiben(ziel, ziel.name, metadata(dateien), dateien, wurzel, **mehr)


def test_paket_ist_bagit_im_tar_mit_allen_teilen(tmp_path, platte):
    ziel = tmp_path / "HD09_001-agate-200.tar"
    sha, groesse = bauen_nach(ziel, platte)
    with tarfile.open(ziel) as tar:
        namen = tar.getnames()
    assert {"bagit.txt", "bag-info.txt", "manifest-sha256.txt", "manifest-md5.txt", "tagmanifest-sha256.txt",
            "data/meta/metadata.json"} <= set(namen)
    assert {f"data/content/{p}" for p in INHALTE} <= set(namen)
    assert sha == hashlib.sha256(ziel.read_bytes()).hexdigest() and groesse == ziel.stat().st_size
    fehler, zahl, _ = bauen.bag_pruefen(ziel, {p: (d[3], d[4]) for p, d in zip(INHALTE, platte[1])})
    assert fehler == [] and zahl == len(INHALTE) + 1          # Dateien und metadata.json


def test_manifest_nennt_die_pruefsummen_der_dateien(tmp_path, platte):
    ziel = tmp_path / "p.tar"
    bauen_nach(ziel, platte)
    with tarfile.open(ziel) as tar:
        manifest = tar.extractfile("manifest-sha256.txt").read().decode()
        info = tar.extractfile("bag-info.txt").read().decode()
        metadata_bytes = tar.getmember("data/meta/metadata.json").size
    for relpfad, inhalt in INHALTE.items():
        assert f"{hashlib.sha256(inhalt).hexdigest()}  data/content/{relpfad}" in manifest
    nutz = sum(len(i) for i in INHALTE.values()) + metadata_bytes
    assert f"Payload-Oxum: {nutz}.{len(INHALTE) + 1}" in info


def test_veraenderte_datei_stoppt_das_paket(tmp_path, platte):
    wurzel, dateien = platte
    pfad = wurzel / "Fotos/2001/IMG_0001.JPG"
    pfad.write_bytes(b"X" * pfad.stat().st_size)                # gleiche Größe, anderer Inhalt
    with pytest.raises(bauen.Abweichung, match="Prüfsumme"):
        bauen_nach(tmp_path / "p.tar", platte)


def test_fehlende_oder_andere_groesse_stoppt_das_paket(tmp_path, platte):
    wurzel, _ = platte
    (wurzel / "Fotos/2001/IMG_0001.JPG").write_bytes(b"kurz")
    with pytest.raises(bauen.Abweichung, match="Größe"):
        bauen_nach(tmp_path / "p.tar", platte)
    (wurzel / "Fotos/2001/IMG_0001.JPG").unlink()
    with pytest.raises(bauen.Abweichung, match="nicht mehr auf dem Datenträger"):
        bauen_nach(tmp_path / "q.tar", platte)


def test_nachpruefen_findet_beschaedigtes_paket(tmp_path, platte):
    ziel = tmp_path / "p.tar"
    bauen_nach(ziel, platte)
    daten = bytearray(ziel.read_bytes())
    stelle = daten.find(b"Bild zwei")
    daten[stelle] ^= 0xFF                                       # ein Byte in den Nutzdaten kippen
    ziel.write_bytes(bytes(daten))
    fehler, _, _ = bauen.bag_pruefen(ziel)
    assert any("Prüfsumme weicht" in f for f in fehler)


def test_abgebrochener_bau_setzt_nach_der_letzten_datei_fort(tmp_path, platte, monkeypatch):
    wurzel, dateien = platte
    monkeypatch.setattr(bauen, "MERKEN_ALLE", 1)                # nach jeder Datei die Stelle sichern
    ziel = tmp_path / "p.tar"
    gemerkt, aufrufe = {}, [0]

    def merken_und_abbrechen(liste):
        gemerkt.update(dict(liste))
        aufrufe[0] += 1
        if aufrufe[0] == 2:                                     # nach der zweiten Datei: wie ■ im Tool
            raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        bauen.tar_schreiben(ziel, ziel.name, metadata(dateien), dateien, wurzel, merken=merken_und_abbrechen)
    assert len(gemerkt) == 2
    weiter = [(nr, r, g, m, s, gemerkt.get(nr)) for nr, r, g, m, s, _ in dateien]
    gelesen = []
    original = bauen.Leser.read

    def zaehlen(self, n=-1):
        gelesen.append(self.datei.name)
        return original(self, n)
    monkeypatch.setattr(bauen.Leser, "read", zaehlen)
    bauen.tar_schreiben(ziel, ziel.name, metadata(dateien), weiter, wurzel)
    assert all("Bericht.pdf" in n for n in gelesen)            # nur die dritte Datei wurde noch gelesen
    fehler, zahl, _ = bauen.bag_pruefen(ziel, {d[1]: (d[3], d[4]) for d in dateien})
    assert fehler == [] and zahl == len(INHALTE) + 1


def test_schema_prueft_metadata(platte):
    _, dateien = platte
    pruefer = bauen.pruefer("0.6")
    md = metadata(dateien)
    assert bauen.fehler_in(md, pruefer) == []
    del md["entries"][1]["files"][0]["md5sum"]
    assert any(f.startswith("Schema:") for f in bauen.fehler_in(md, pruefer))


def test_schema_version_hoechstens_was_die_instanz_liest():
    assert bauen.schema_version("0.6") == "0.6"
    assert bauen.schema_version("0.7") == "0.6"           # 0.7 liegt nicht vor
    assert bauen.schema_version("0.8") == "0.8"
    assert bauen.schema_version("0.9") == "0.8"


def test_actors_nur_ab_version_0_8(platte):
    """Das Register der Akteur:innen (actors[], Format 0.8) geht nur an Instanzen, die 0.8 lesen; ältere verwerfen es
    stillschweigend, darum nimmt Balduin es beim Bauen heraus (Entscheidung 06.11.2026)."""
    _, dateien = platte
    md = metadata(dateien)
    md["entries"][1]["actors"] = [{"id": 12}, {"label": {"de": "Neu, Nina"}}]
    neu = bauen.fuer_version(md["entries"], "0.8")
    assert neu[1]["actors"] == [{"id": 12}, {"label": {"de": "Neu, Nina"}}]
    assert bauen.fehler_in({**md, "version": "0.8", "entries": neu}, bauen.pruefer("0.8")) == []
    alt = bauen.fuer_version(md["entries"], "0.6")
    assert all("actors" not in e for e in alt)
    assert md["entries"][1]["actors"]                     # das Original bleibt unverändert
    md["entries"][1]["actors"] = [{"id": 12, "label": {"de": "gemischt"}}]
    assert any(f.startswith("Schema:") for f in bauen.fehler_in({**md, "version": "0.8"}, bauen.pruefer("0.8")))


def test_dubletten_und_doppelte_uuid_im_paket_werden_erkannt(platte):
    _, dateien = platte
    pruefer = bauen.pruefer("0.6")
    md = metadata(dateien)
    md["entries"][2]["files"][0]["md5sum"] = md["entries"][1]["files"][0]["md5sum"]
    md["entries"][3]["uuid"] = md["entries"][1]["uuid"]
    fehler = bauen.fehler_in(md, pruefer)
    assert any("Dublette" in f for f in fehler)
    assert any("doppelt" in f for f in fehler)


def test_eltern_stehen_vor_kindern_und_erster_eintrag_nicht_content(platte):
    _, dateien = platte
    pruefer = bauen.pruefer("0.6")
    md = metadata(dateien)
    md["entries"].append(md["entries"].pop(0))                  # Ebene ans Ende
    assert any("ParentNotFound" in f for f in bauen.fehler_in(md, pruefer))
    md = metadata(dateien)
    md["entries"][0]["title"] = {"de": "Content"}
    assert any("Content" in f for f in bauen.fehler_in(md, pruefer))


def test_paketname_hat_genau_drei_teile():
    assert pakete.namensteil("HD-01 alt") == "HD_01_alt"
    name = f"{pakete.namensteil('HD-01')}_001-agate-200.tar"
    assert len(name[:-4].split("-")) == 3


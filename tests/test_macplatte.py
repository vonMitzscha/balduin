"""Mac-Datenträger ohne Mac (Entscheidung 09.11.2026, docs/plan.md): HFS+ und APFS werden über eine eigene, nur
lesende Leseschicht gelesen (erfassung/macplatte.py), ohne sie einzuhängen. Geprüft an kleinen Abbildern aus
tests/daten/ (werkzeuge/mac_testabbilder_erzeugen.py); dieselben Tests laufen auch unter Windows."""
import hashlib
import io
import os
import time
import unicodedata
import zipfile

import pytest

from erfassung import macplatte

BUNT_PNG_GROESSE = None          # wird aus dem HFS+-Abbild gelesen und mit APFS verglichen


@pytest.fixture(params=["hfs", "apfs"])
def abbild(request, mac_abbilder):
    return request.param, getattr(mac_abbilder, request.param)


def test_ist_abbild(mac_abbilder, tmp_path):
    assert macplatte.ist_abbild(mac_abbilder.hfs)
    assert not macplatte.ist_abbild(tmp_path)                       # ein Ordner ist eine gewöhnliche Quelle
    assert not macplatte.ist_abbild(tmp_path / "fehlt.img")


def test_volumes_mit_name_dateisystem_und_kennung_wie_vom_mac(abbild, mac_abbilder):
    art, pfad = abbild
    vs = macplatte.volumes(pfad)
    assert len(vs) == 1
    v = vs[0]
    assert v["name"] == {"hfs": "MAC_HFS", "apfs": "MAC_APFS"}[art]
    assert v["dateisystem"] == {"hfs": "HFS+", "apfs": "APFS"}[art]
    assert v["uuid"] == mac_abbilder.uuid[art]                      # = VolumeUUID von diskutil: Wiedererkennung
    assert v["gesperrt"] is False and v["groesse"] > 0


def test_alle_dateien_mit_groesse_und_datum(abbild, mac_abbilder):
    _, pfad = abbild
    with macplatte.oeffne_volume(pfad) as v:
        eintraege = {e[0]: e for e in v.eintraege()}
    assert set(eintraege) == mac_abbilder.dateien                  # ohne .fseventsd und andere Verwaltungsordner
    for relpfad, (_, groesse, mtime) in eintraege.items():
        assert relpfad == unicodedata.normalize("NFC", relpfad)     # Namen in NFC wie überall in Balduin
        assert 1_600_000_000 < mtime <= time.time() + 60
    assert eintraege["Texte/leer.txt"][1] == 0
    assert eintraege["Texte/Notiz 12:30.txt"][1] == len("Doppelpunkt im Namen\n")


def test_inhalt_als_datenstrom_mit_seek(abbild):
    _, pfad = abbild
    with macplatte.oeffne_volume(pfad) as v:
        with v.oeffnen("Texte/Notiz 12:30.txt") as f:
            assert f.read() == b"Doppelpunkt im Namen\n"
            f.seek(0)
            assert f.read(11) == b"Doppelpunkt"
            assert f.seek(0, io.SEEK_END) == 21 and f.tell() == 21
        with v.oeffnen("Archiv/alt.zip") as f:                     # zipfile braucht seek/tell
            with zipfile.ZipFile(f) as z:
                assert z.read("innen/zwei.txt") == b"zwei zwei\n"
        with v.oeffnen("Alt/Mit Resource Fork") as f:
            assert f.read() == b"Datenzweig\n"                     # nur der Datenzweig (wie beim Lesen über den Mac)


def test_gleicher_inhalt_in_hfs_und_apfs(mac_abbilder):
    summen = []
    for pfad in (mac_abbilder.hfs, mac_abbilder.apfs):
        with macplatte.oeffne_volume(pfad) as v:
            summen.append({r: hashlib.sha256(v.oeffnen(r).read()).hexdigest() for r, _, _ in v.eintraege()})
    assert summen[0] == summen[1]


def test_unbekannter_pfad(abbild):
    _, pfad = abbild
    with macplatte.oeffne_volume(pfad) as v:
        with pytest.raises(FileNotFoundError):
            v.oeffnen("Texte/gibtsnicht.txt")
        with pytest.raises(FileNotFoundError):
            v.stat("Texte")                                          # ein Ordner ist keine Datei
        assert v.stat("Texte/Brief.pdf")[0] > 0
        assert v.ist_ordner("Fotos/Zürich 1998") and not v.ist_ordner("Texte/Brief.pdf")


def test_ordner_auflisten(abbild):
    _, pfad = abbild
    with macplatte.oeffne_volume(pfad) as v:
        assert v.ordner("") == ["Alt", "Archiv", "Fotos", "Texte"]
        assert v.ordner("Fotos/Zürich 1998") == ["Übergabe"]


def test_umfang_nur_diese_ordner(abbild):
    _, pfad = abbild
    with macplatte.oeffne_volume(pfad) as v:
        assert {e[0] for e in v.eintraege(["Texte"])} == {"Texte/Notiz 12:30.txt", "Texte/leer.txt", "Texte/Brief.pdf"}


def test_kennung_hfs_aus_volume_id():
    """macOS bildet die VolumeUUID einer HFS+-Platte als UUID v3 aus der 8-Byte-Volume-ID (Finder-Info)."""
    assert macplatte.hfs_uuid(bytes.fromhex("49397d1e67e3cdb2")) == "E57BF4A4-3F5B-3E29-8132-A1EA2EE0A5C2"


def test_sektorweise_lesen_fuer_geraete():
    """Windows liest physische Platten nur in ganzen Sektoren; die Leseschicht richtet jeden Zugriff aus."""
    daten = bytes(range(256)) * 64                                   # 16 KB

    class Geraet(io.BytesIO):
        def read(self, n=-1):
            assert self.tell() % 512 == 0 and n % 512 == 0, (self.tell(), n)
            return super().read(n)

    f = macplatte.Ausschnitt(Geraet(daten), start=1024, laenge=8000, sektor=512)
    f.seek(3)
    assert f.read(700) == daten[1027:1727]
    assert f.seek(0, io.SEEK_END) == 8000
    f.seek(7990)
    assert f.read(100) == daten[1024 + 7990:1024 + 8000]           # nicht über das Ende des Ausschnitts


def test_kein_mac_dateisystem(tmp_path):
    leer = tmp_path / "leer.img"
    leer.write_bytes(bytes(4 * 1024 * 1024))
    assert macplatte.volumes(leer) == []
    with pytest.raises(ValueError, match="kein HFS\\+- oder APFS"):
        macplatte.oeffne_volume(leer)


def test_wahl_des_volumes_ueber_die_kennung(mac_abbilder):
    with pytest.raises(ValueError, match="nicht"):
        macplatte.oeffne_volume(mac_abbilder.apfs, uuid="00000000-0000-0000-0000-000000000000")
    with macplatte.oeffne_volume(mac_abbilder.apfs, uuid=mac_abbilder.uuid["apfs"].lower()) as v:
        assert v.info["VolumeName"] == "MAC_APFS"
        assert v.info["VolumeUUID"] == mac_abbilder.uuid["apfs"] and v.info["FilesystemName"] == "APFS"


def test_nur_lesend_geoeffnet(mac_abbilder, monkeypatch):
    """Harte Regel 1: Abbild und Gerät werden nur zum Lesen geöffnet."""
    modi = []
    echt = open

    def merken(pfad, modus="r", *a, **k):
        modi.append((str(pfad), modus))
        return echt(pfad, modus, *a, **k)
    monkeypatch.setattr("builtins.open", merken)
    with macplatte.oeffne_volume(mac_abbilder.hfs) as v:
        v.oeffnen("Texte/Brief.pdf").read()
    eigene = [m for p, m in modi if p == str(mac_abbilder.hfs)]
    assert eigene and all(m == "rb" for m in eigene)


def test_gleiche_aenderungszeit_in_hfs_und_apfs(mac_abbilder):
    """Zeiten kommen in UTC an: dieselbe Datei hat in beiden Abbildern dieselbe Änderungszeit (HFS+: ganze Sekunden)."""
    zeiten = []
    for pfad in (mac_abbilder.hfs, mac_abbilder.apfs):
        with macplatte.oeffne_volume(pfad) as v:
            zeiten.append({r: m for r, _, m in v.eintraege()})
    assert all(abs(zeiten[0][r] - zeiten[1][r]) < 2 for r in zeiten[0])


def test_physische_platte_ueber_system_geoeffnet(mac_abbilder, monkeypatch):
    """Unter Windows kommt eine physische Platte als Dateiobjekt mit bekannter Größe über system.geraet_oeffnen; die
    Leseschicht liest sie in ganzen Sektoren (nachgestellt mit dem HFS+-Abbild)."""
    from erfassung import system
    daten = mac_abbilder.hfs.read_bytes()

    class Geraet(io.BytesIO):
        def read(self, n=-1):
            assert self.tell() % 4096 == 0 and n % 4096 == 0, (self.tell(), n)
            return super().read(n)

        def seek(self, pos, woher=0):
            assert woher == 0, "Geräte kennen kein Ende (SEEK_END)"
            return super().seek(pos)

    monkeypatch.setattr(system, "ist_geraet", lambda p: str(p) == "\\\\.\\PhysicalDrive2")
    monkeypatch.setattr(system, "geraet_oeffnen", lambda p: (Geraet(daten), len(daten), 4096))
    assert macplatte.ist_abbild("\\\\.\\PhysicalDrive2")
    vs = macplatte.volumes("\\\\.\\PhysicalDrive2")
    assert [(v["name"], v["uuid"]) for v in vs] == [("MAC_HFS", mac_abbilder.uuid["hfs"])]
    with macplatte.oeffne_volume("\\\\.\\PhysicalDrive2") as v:
        assert v.oeffnen("Texte/Notiz 12:30.txt").read() == b"Doppelpunkt im Namen\n"

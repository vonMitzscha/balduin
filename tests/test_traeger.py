"""Art des Datenträgers (Entscheidung 05.11.2026, docs/plan.md): CD/DVD, USB-Stick, Speicherkarte, Festplatte,
Image oder Ordner, abgeleitet aus den Angaben von diskutil (nur gelesen) und als Icon gezeigt. Die Zuordnung wird an
gespeicherten diskutil-Antworten geprüft, ohne einen Datenträger anzuschließen."""
import pytest

from conftest import Balduin

# Ausschnitte aus `diskutil info -plist` (nur die Schlüssel, die zählen)
INTERN = {"BusProtocol": "Apple Fabric", "Internal": True, "RemovableMedia": False, "SolidState": True,
          "FilesystemType": "apfs"}
USB_PLATTE = {"BusProtocol": "USB", "Internal": False, "RemovableMedia": False, "Removable": False,
              "SolidState": False, "FilesystemType": "hfs"}
USB_STICK = {"BusProtocol": "USB", "Internal": False, "RemovableMedia": True, "Removable": True,
             "FilesystemType": "msdos"}
SD_KARTE = {"BusProtocol": "Secure Digital", "Internal": True, "RemovableMedia": True, "FilesystemType": "exfat"}
CD_INTERN = {"BusProtocol": "ATAPI", "OpticalDeviceType": "DVD-RW", "OpticalMediaType": "CD-ROM",
             "RemovableMedia": True, "FilesystemType": "cd9660"}
CD_USB = {"BusProtocol": "USB", "OpticalMediaType": "DVD-ROM", "RemovableMedia": True, "FilesystemType": "udf"}
CD_OHNE_OPTIK = {"BusProtocol": "USB", "RemovableMedia": True, "FilesystemType": "cd9660"}
IMAGE = {"BusProtocol": "Disk Image", "Internal": False, "RemovableMedia": False, "FilesystemType": "hfs"}
THUNDERBOLT = {"BusProtocol": "PCI-Express", "Internal": False, "RemovableMedia": False, "SolidState": True}


@pytest.mark.parametrize("info, art", [
    (INTERN, "festplatte"), (USB_PLATTE, "festplatte"), (THUNDERBOLT, "festplatte"),
    (USB_STICK, "usb"), (SD_KARTE, "karte"),
    (CD_INTERN, "cd"), (CD_USB, "cd"), (CD_OHNE_OPTIK, "cd"),
    (IMAGE, "image"), ({}, ""),
])
def test_traegerart_aus_diskutil(info, art):
    from erfassung import system
    assert system.traegerart(info) == art


@pytest.mark.parametrize("zeile, art", [
    ({"traeger": "usb", "art": None}, "usb"),                                       # gespeichert gilt
    ({"traeger": None, "art": "ordner"}, "ordner"),
    ({"traeger": "", "art": "ordner"}, "ordner"),
    ({"traeger": None, "art": None, "dateisystem": "ISO 9660", "anschluss": "USB"}, "cd"),   # vor 05.11.2026 registriert
    ({"traeger": None, "art": None, "dateisystem": "UDF", "anschluss": ""}, "cd"),
    ({"traeger": None, "art": None, "dateisystem": "APFS", "anschluss": "Disk Image"}, "image"),
    ({"traeger": None, "art": None, "dateisystem": "ExFAT", "anschluss": "Secure Digital"}, "karte"),
    ({"traeger": None, "art": None, "dateisystem": "ExFAT", "anschluss": "USB"}, ""),   # Stick oder Platte: unklar
    ({}, ""),
])
def test_traeger_einer_registrierten_platte(zeile, art):
    from erfassung import system
    assert system.traeger_der_platte(zeile) == art


def test_platteninfo_und_angeschlossene_nennen_die_art(leeres_projekt, monkeypatch):
    from erfassung import platte
    stick = leeres_projekt.volumes / "STICK"
    (stick / "A").mkdir(parents=True)
    (stick / "A" / "1.txt").write_text("eins", encoding="utf-8")
    monkeypatch.setattr(platte, "datentraeger_info", lambda pfad: {**USB_STICK, "VolumeName": "STICK"})
    assert platte.platteninfo(stick)["traeger"] == "usb"
    d = {x["name"]: x for x in platte.angeschlossene(platte.registrierte_platten())}
    assert d["STICK"]["traeger"] == "usb"
    platte.registrieren("HD01", stick, etikett="Stick")
    from erfassung.basis import db
    with db() as con:
        assert con.execute("SELECT traeger FROM platte WHERE platte_id = 'HD01'").fetchone()[0] == "usb"


def test_ordner_als_quelle_hat_die_art_ordner(leeres_projekt, tmp_path):
    from erfassung import platte
    from erfassung.basis import db
    q = tmp_path / "quellen" / "Übergabe"
    q.mkdir(parents=True)
    (q / "a.txt").write_text("a", encoding="utf-8")
    platte.registrieren("HD01", q, etikett="Herkunft", art="ordner")
    with db() as con:
        assert con.execute("SELECT traeger FROM platte WHERE platte_id = 'HD01'").fetchone()[0] == "ordner"


@pytest.fixture(scope="module")
def server(quellen, tmp_path_factory):
    b = Balduin(quellen.ordner, quellen.volumes, tmp_path_factory.mktemp("server_traeger"))
    yield b
    b.beenden()


@pytest.mark.integration
def test_server_nennt_die_art_in_allen_modulen(server):
    erfassung = {p["platte_id"]: p for p in server.get("/api/erfassung")["platten"]}
    assert erfassung["HD05"]["traeger"] == "ordner"
    assert all("traeger" in p for p in erfassung.values())
    bewertung = {p["id"]: p for p in server.get("/api/stand")["platten"]}
    assert bewertung["HD05"]["traeger"] == "ordner"
    erschliessung = {p["id"]: p for p in server.get("/api/es_platten")["platten"]}
    assert erschliessung["HD05"]["traeger"] == "ordner"
    assert all("traeger" in d for d in server.get("/api/datentraeger")["angeschlossen"] if "fehler" not in d)

"""Abbild eines Mac-Datenträgers als Quelle (Entscheidung 09.11.2026, docs/plan.md): registrieren, analysieren (B–I)
und packen wie eine Platte, gelesen über die Leseschicht (erfassung/macplatte.py, erfassung/quelle.py), ohne
einzuhängen. Das Abbild wird nur gelesen (Fingerabdruck vorher/nachher)."""
import hashlib
import json
import shutil
from types import SimpleNamespace

import pytest

from conftest import BASIS, Balduin, abfrage, fingerabdruck, lauf_ausfuehren, projekt_kopieren

ZIP_INHALT = {"Archiv/alt.zip/innen/eins.txt", "Archiv/alt.zip/innen/zwei.txt"}


def zeile(platte_id):
    from erfassung.basis import db
    with db() as con:
        con.row_factory = __import__("sqlite3").Row
        return dict(con.execute("SELECT * FROM platte WHERE platte_id = ?", (platte_id,)).fetchone())


@pytest.fixture
def abbild(leeres_projekt, mac_abbilder, tmp_path):
    """Kopie des HFS+-Abbilds im Temp-Ordner (Tests dürfen sie nicht verändern; der Fingerabdruck zeigt es)."""
    ziel = tmp_path / "quellen" / "HD07 Nachlass.img"
    ziel.parent.mkdir()
    shutil.copy2(mac_abbilder.hfs, ziel)
    return ziel


# ---------- quelle.py: eine Weiche für Ordner und Abbilder ----------

def test_quelle_liest_ordner_und_abbild_gleich(leeres_projekt, abbild, tmp_path):
    from erfassung import quelle
    ordner = tmp_path / "ordner"
    (ordner / "Texte").mkdir(parents=True)
    (ordner / "Texte" / "Notiz 1230.txt").write_bytes(b"Doppelpunkt im Namen\n")   # „:“ gibt es unter Windows nicht
    for wurzel, name in ((ordner, "Texte/Notiz 1230.txt"), (abbild, "Texte/Notiz 12:30.txt")):
        assert quelle.ist_datei(wurzel, name) and not quelle.ist_datei(wurzel, "Texte")
        assert quelle.ist_ordner(wurzel, "Texte") and not quelle.ist_ordner(wurzel, "fehlt")
        assert quelle.stat(wurzel, name)[0] == 21
        with quelle.oeffnen(wurzel, name) as f:
            assert f.read() == b"Doppelpunkt im Namen\n"
        with pytest.raises(FileNotFoundError):
            quelle.oeffnen(wurzel, "Texte/fehlt.txt")
    quelle.schliessen()


def test_unterordner_eines_abbilds(leeres_projekt, abbild):
    from erfassung import platte
    assert [o["name"] for o in platte.unterordner(abbild)] == ["Alt", "Archiv", "Fotos", "Texte"]
    assert platte.unterordner(abbild, "Fotos") == [{"name": "Zürich 1998", "pfad": "Fotos/Zürich 1998",
                                                    "unterordner": True}]


def test_abbild_registrieren(leeres_projekt, abbild, mac_abbilder):
    from erfassung import platte
    platte.registrieren("HD07", abbild, etikett="Nachlass Muster, Abbild einer Platte 500 GB, FTK Imager, 2026",
                        art="abbild")
    z = zeile("HD07")
    assert z["art"] == "abbild" and z["quellordner"] == str(abbild)
    assert z["volume_uuid"] == mac_abbilder.uuid["hfs"] and z["volume_name"] == "MAC_HFS"
    assert z["dateisystem"] == "HFS+" and z["traeger"] == "image"


def test_abbild_braucht_herkunft(leeres_projekt, abbild):
    from erfassung import platte
    with pytest.raises(ValueError, match="Herkunft"):
        platte.registrieren("HD07", abbild, art="abbild")


def test_kein_mac_abbild(leeres_projekt, tmp_path):
    from erfassung import platte
    leer = tmp_path / "leer.img"
    leer.write_bytes(bytes(2 * 1024 * 1024))
    with pytest.raises(ValueError, match="kein HFS\\+- oder APFS"):
        platte.registrieren("HD07", leer, etikett="x", art="abbild")


def test_abbild_nicht_im_projekt(leeres_projekt, mac_abbilder):
    """Wie bei Ordnern: nie aus dem Projekt, dem Code oder den Vorschaubildern (dort liegt kein Quellbestand)."""
    from erfassung import platte
    from erfassung.basis import P
    im_projekt = P.ordner / "abbild.img"
    shutil.copy2(mac_abbilder.hfs, im_projekt)
    with pytest.raises(ValueError, match="überschneidet sich mit dem Projekt"):
        platte.registrieren("HD07", im_projekt, etikett="x", art="abbild")


def test_gleiche_kennung_wie_registrierte_platte(leeres_projekt, abbild, mac_abbilder, tmp_path):
    """Ein zweites Abbild derselben Platte (gleiche Volume-Kennung) wird erkannt."""
    from erfassung import platte
    platte.registrieren("HD07", abbild, etikett="erstes Abbild", art="abbild")
    zweites = tmp_path / "zweites.img"
    shutil.copy2(mac_abbilder.hfs, zweites)
    with pytest.raises(ValueError, match="dieselbe Volume-UUID wie HD07"):
        platte.registrieren("HD08", zweites, etikett="zweites Abbild", art="abbild")


def test_abbild_wiedererkennen(leeres_projekt, abbild, tmp_path):
    from erfassung import platte, schnellscan
    platte.registrieren("HD07", abbild, etikett="Nachlass", art="abbild")
    schnellscan.schnellscan("HD07", abbild)
    platte.angeschlossene_platte_pruefen("HD07", abbild)            # gleicher Ort, gleiche Kennung, Stichprobe
    anderswo = tmp_path / "anderswo.img"
    shutil.copy2(abbild, anderswo)
    with pytest.raises(ValueError, match="registriert"):
        platte.angeschlossene_platte_pruefen("HD07", anderswo)


def test_schnellscan_eines_abbilds(leeres_projekt, abbild, mac_abbilder):
    from erfassung import platte, schnellscan
    from erfassung.basis import db
    platte.registrieren("HD07", abbild, etikett="Nachlass", art="abbild")
    schnellscan.schnellscan("HD07", abbild)
    with db() as con:
        pfade = {r: a for r, a in con.execute("SELECT relpfad, archiv FROM schnellscan WHERE platte_id = 'HD07'")}
        archiv = con.execute("SELECT status, dateien FROM archivdatei WHERE platte_id = 'HD07'").fetchall()
    erwartet = (mac_abbilder.dateien - {"Archiv/alt.zip"}) | ZIP_INHALT     # ZIP wie ein Ordner aufgelöst
    assert set(pfade) == erwartet
    assert {r for r, a in pfade.items() if a} == ZIP_INHALT and archiv == [("aufgelöst", 2)]


def test_schnellscan_mit_umfang(leeres_projekt, abbild):
    from erfassung import platte, schnellscan
    from erfassung.basis import db
    platte.registrieren("HD07", abbild, etikett="Nachlass", art="abbild", umfang=["Texte"])
    schnellscan.schnellscan("HD07", abbild)
    with db() as con:
        assert {r for (r,) in con.execute("SELECT relpfad FROM schnellscan WHERE platte_id = 'HD07'")} == {
            "Texte/Notiz 12:30.txt", "Texte/leer.txt", "Texte/Brief.pdf"}


def test_bereitstellen_legt_auch_frei_liegende_dateien_bereit(leeres_projekt, abbild):
    """Werkzeuge (Siegfried, ExifTool, ffmpeg …) brauchen einen Dateipfad; aus einem Abbild kommt jede Datei kurz
    nach entpackt/ im Projekt, mit dem Änderungsdatum aus dem Abbild, und wird danach gelöscht."""
    from erfassung import archivdateien, platte, schnellscan
    from erfassung.basis import P
    platte.registrieren("HD07", abbild, etikett="Nachlass", art="abbild")
    schnellscan.schnellscan("HD07", abbild)
    gesucht = ["Texte/Brief.pdf", "Archiv/alt.zip/innen/eins.txt"]
    with archivdateien.bereitstellen("HD07", abbild, gesucht) as pfad:
        for r in gesucht:
            p = pfad(r)
            assert str(p).startswith(str(P.ordner / "entpackt")) and p.is_file()
            assert pfad.relpfad(p) == r
        assert pfad("Texte/Brief.pdf").read_bytes().startswith(b"%PDF")
    assert not (P.ordner / "entpackt").exists()


def test_bereitstellen_mit_namen_die_windows_verbietet(leeres_projekt, abbild):
    """Mac-Namen dürfen „:“ und < > " | ? * enthalten, Windows-Namen nicht (NTFS machte aus „Notiz 12:30.txt“ still
    einen alternativen Datenstrom). Bereitgestellt wird deshalb unter einer laufenden Nummer mit der Endung; Werkzeuge
    erkennen das Format weiter an der Endung, und pfad.relpfad führt zurück."""
    from erfassung import archivdateien, platte, schnellscan
    platte.registrieren("HD07", abbild, etikett="Nachlass", art="abbild")
    schnellscan.schnellscan("HD07", abbild)
    with archivdateien.bereitstellen("HD07", abbild, ["Texte/Notiz 12:30.txt", "Texte/Brief.pdf"]) as pfad:
        notiz, brief = pfad("Texte/Notiz 12:30.txt"), pfad("Texte/Brief.pdf")
        assert not any(z in notiz.name for z in ':<>"|?*') and notiz.suffix == ".txt" and brief.suffix == ".pdf"
        assert notiz.read_bytes() == b"Doppelpunkt im Namen\n"
        assert pfad.relpfad(str(notiz)) == "Texte/Notiz 12:30.txt" and pfad.relpfad(str(brief)) == "Texte/Brief.pdf"


# ---------- Ende zu Ende: Analyse B–I und Packen ----------

@pytest.fixture(scope="module")
def mac_projekt(analysiert, mac_abbilder):
    """Kopie von „analysiert“; HD07 = HFS+-Abbild, HD08 = APFS-Abbild, beide durch B–I."""
    basis = BASIS / "mac_projekt"
    ordner = projekt_kopieren(analysiert.ordner, basis / "Testprojekt")
    abbilder = {}
    for kennung, quelle in (("HD07", mac_abbilder.hfs), ("HD08", mac_abbilder.apfs)):
        ziel = basis / "abbilder" / f"{kennung}{quelle.suffix}"
        ziel.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(quelle, ziel)
        abbilder[kennung] = ziel
    abdruck = {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in abbilder.items()}
    laeufe = {k: lauf_ausfuehren(ordner, analysiert.volumes, "erfassen", {
        "platte_id": k, "mountpunkt": str(p), "art": "abbild", "etikett": f"Abbild {k} aus einem Nachlass"}, k)
        for k, p in abbilder.items()}
    return SimpleNamespace(ordner=ordner, volumes=analysiert.volumes, abbilder=abbilder, abdruck=abdruck, laeufe=laeufe)


@pytest.mark.integration
@pytest.mark.parametrize("kennung", ["HD07", "HD08"])
def test_abbild_durch_die_analyse(mac_projekt, mac_abbilder, kennung):
    schritte = mac_projekt.laeufe[kennung]["schritte"]
    assert {k: (s["status"], s["text"]) for k, s in schritte.items() if s["status"] not in ("fertig", "übersprungen")} == {}
    for pflicht in ("B", "C", "D1", "D2", "E", "E4", "F", "G", "H"):
        assert schritte[pflicht]["status"] == "fertig", (pflicht, schritte[pflicht]["text"])
    db = mac_projekt.ordner
    dateien = {z["relpfad"]: z for z in abfrage(db, "SELECT relpfad, sha256, md5, puid FROM datei WHERE platte_id = ?",
                                                 kennung)}
    assert set(dateien) == (mac_abbilder.dateien - {"Archiv/alt.zip"}) | ZIP_INHALT
    assert dateien["Texte/Notiz 12:30.txt"]["sha256"] == hashlib.sha256(b"Doppelpunkt im Namen\n").hexdigest()
    assert dateien["Texte/Brief.pdf"]["puid"].startswith("fmt/")                     # Siegfried hat gelesen
    vorschau = abfrage(db, "SELECT v.datei FROM vorschau v JOIN datei d ON d.sha256 = v.sha256 WHERE d.platte_id = ? "
                           "AND d.relpfad = 'Fotos/Zürich 1998/bunt.png'", kennung)
    assert vorschau and vorschau[0]["datei"]                                          # Vorschaubild aus dem Abbild
    text = abfrage(db, "SELECT t.zeichen FROM volltext t JOIN datei d ON d.sha256 = t.sha256 WHERE d.platte_id = ? "
                       "AND d.relpfad = 'Texte/Brief.pdf'", kennung)
    assert text and text[0]["zeichen"] > 0                                           # E4: Text aus dem PDF
    assert not (db / "entpackt").exists()


@pytest.mark.integration
def test_abbilder_bleiben_unveraendert(mac_projekt):
    assert {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in mac_projekt.abbilder.items()} == mac_projekt.abdruck


@pytest.mark.integration
def test_hfs_und_apfs_sind_bitgleich(mac_projekt):
    """Beide Abbilder tragen denselben Inhalt: G findet ihn als exakte Dubletten."""
    summen = {k: {z["relpfad"]: z["sha256"] for z in abfrage(mac_projekt.ordner, "SELECT relpfad, sha256 FROM datei "
                                                                                  "WHERE platte_id = ?", k)}
              for k in ("HD07", "HD08")}
    assert summen["HD07"] == summen["HD08"]


# ---------- Packen (Modul 4) ----------

def dateiliste(abbild, relpfade):
    """[(nr, relpfad, größe, md5, sha256, None)] wie aus der Analyse, gelesen über die Leseschicht."""
    from erfassung import platte
    liste = []
    for nr, r in enumerate(relpfade):
        with platte.oeffne(abbild, r) as f:                        # auch Dateien in Archivdateien
            daten = f.read()
        liste.append((nr, r, len(daten), hashlib.md5(daten).hexdigest(), hashlib.sha256(daten).hexdigest(), None))
    return liste


def test_packen_aus_dem_abbild(leeres_projekt, abbild, tmp_path):
    import tarfile
    from erfassung import platte, quelle, schnellscan
    from export import bauen
    from test_export_paketbau import metadata
    platte.registrieren("HD07", abbild, etikett="Nachlass", art="abbild")
    schnellscan.schnellscan("HD07", abbild)
    bauen.platte_pruefen("HD07", abbild)                             # Abbild erkannt, nicht in der Ablage
    relpfade = ["Fotos/Zürich 1998/bunt.png", "Texte/Notiz 12:30.txt", "Archiv/alt.zip/innen/zwei.txt"]
    dateien = dateiliste(abbild, relpfade)
    ziel = tmp_path / "HD07_001-agate-200.tar"
    bauen.tar_schreiben(ziel, ziel.name, metadata(dateien), dateien, abbild, platte_id="HD07")
    fehler, zahl, _ = bauen.bag_pruefen(ziel, {d[1]: (d[3], d[4]) for d in dateien})
    assert fehler == [] and zahl == len(relpfade) + 1
    with tarfile.open(ziel) as tar:
        info = tar.getmember("data/content/Texte/Notiz 12:30.txt")
        assert tar.extractfile(info).read() == b"Doppelpunkt im Namen\n"
        assert info.mtime == int(quelle.stat(abbild, "Texte/Notiz 12:30.txt")[1])     # Zeit aus dem Abbild


def test_packen_fragt_bei_der_leseschicht_nicht_nach_einem_pfad(leeres_projekt, abbild, tmp_path, monkeypatch):
    """Gefunden in der Windows-VM am 13.11.2026: Für eine Mac-Platte (\\\\.\\PhysicalDrive1) prüfte X1 zuerst den
    zusammengesetzten Pfad \\\\.\\PhysicalDrive1\\Alt\\… mit is_file(); Windows antwortet darauf mit Fehler 87 statt
    „nein“. Was die Leseschicht liest (Abbild, Mac-Platte), darf X1 nie als Pfad im Dateisystem befragen."""
    from pathlib import Path
    from erfassung import platte, schnellscan
    from export import bauen
    from test_export_paketbau import metadata
    platte.registrieren("HD07", abbild, etikett="Nachlass", art="abbild")
    schnellscan.schnellscan("HD07", abbild)
    dateien = dateiliste(abbild, ["Fotos/Zürich 1998/bunt.png"])
    echt = {name: getattr(Path, name) for name in ("is_file", "exists")}

    def wie_windows(name):
        def frage(p, *a, **k):
            if str(p).startswith(str(abbild) + "/") or str(p).startswith(str(abbild) + "\\"):
                raise OSError(22, "[WinError 87] Falscher Parameter", str(p))
            return echt[name](p, *a, **k)
        return frage
    for name in echt:
        monkeypatch.setattr(Path, name, wie_windows(name))
    ziel = tmp_path / "HD07_001-agate-200.tar"
    bauen.tar_schreiben(ziel, ziel.name, metadata(dateien), dateien, abbild, platte_id="HD07")
    for name in echt:
        monkeypatch.setattr(Path, name, echt[name])
    assert bauen.bag_pruefen(ziel, {d[1]: (d[3], d[4]) for d in dateien})[0] == []


def test_packen_aus_dem_abbild_stoppt_bei_abweichung(leeres_projekt, abbild, tmp_path):
    from erfassung import platte, schnellscan
    from export import bauen
    from test_export_paketbau import metadata
    platte.registrieren("HD07", abbild, etikett="Nachlass", art="abbild")
    schnellscan.schnellscan("HD07", abbild)
    nr, r, groesse, md5, sha, _ = dateiliste(abbild, ["Texte/Brief.pdf"])[0]
    falsch = [(nr, r, groesse + 1, md5, sha, None)]
    with pytest.raises(bauen.Abweichung, match="Größe"):
        bauen.tar_schreiben(tmp_path / "x-agate-1.tar", "x-agate-1.tar", metadata(falsch), falsch, abbild,
                            platte_id="HD07")


def test_abbild_nie_in_der_ablage(leeres_projekt, abbild, monkeypatch):
    from erfassung import platte, schnellscan
    from export import bauen
    platte.registrieren("HD07", abbild, etikett="Nachlass", art="abbild")
    schnellscan.schnellscan("HD07", abbild)
    monkeypatch.setattr(bauen.P, "export", abbild.parent / "export")
    monkeypatch.setattr(bauen.P, "export_wurzel", abbild.parent)
    with pytest.raises((RuntimeError, ValueError), match="Ablage"):
        bauen.platte_pruefen("HD07", abbild)


# ---------- Server ----------

@pytest.fixture(scope="module")
def server(mac_projekt, tmp_path_factory):
    b = Balduin(mac_projekt.ordner, mac_projekt.volumes, tmp_path_factory.mktemp("server_abbild"))
    yield b
    b.beenden()


@pytest.mark.integration
def test_server_kennt_die_abbilder(server, mac_projekt):
    quellen = {o["platte_id"]: o for o in server.get("/api/datentraeger")["ordner"]}
    assert quellen["HD07"]["art"] == "abbild" and quellen["HD07"]["da"] is True
    assert quellen["HD07"]["pfad"] == str(mac_projekt.abbilder["HD07"])
    platten = {p["platte_id"]: p for p in server.get("/api/erfassung", platte="HD07")["platten"]}
    assert platten["HD07"]["art"] == "abbild" and platten["HD07"]["traeger"] == "image"


@pytest.mark.integration
def test_abbild_pruefen_ueber_den_server(server, mac_abbilder, tmp_path):
    kopie = tmp_path / "neu.img"
    shutil.copy2(mac_abbilder.apfs, kopie)
    a = server.post("/api/abbild_pruefen", {"pfad": str(kopie)})
    assert a["pfad"] == str(kopie.resolve()) and a["name"] == "neu.img"
    assert [(v["name"], v["dateisystem"], v["gesperrt"]) for v in a["volumes"]] == [("MAC_APFS", "APFS", False)]
    leer = tmp_path / "leer.img"
    leer.write_bytes(bytes(1024 * 1024))
    status, antwort = server.roh("POST", "/api/abbild_pruefen", {"pfad": str(leer)})
    assert status >= 400 and "HFS" in json.dumps(antwort, ensure_ascii=False)


@pytest.mark.integration
def test_datei_im_abbild_wird_nicht_im_dateimanager_gezeigt(server):
    a = server.get("/api/quelle", platte="HD07", pfad="Texte/Brief.pdf")
    assert "Abbild" in a["grund"]


@pytest.mark.integration
def test_abbild_registrieren_braucht_herkunft_ueber_den_server(server, mac_abbilder, tmp_path):
    kopie = tmp_path / "ohne_herkunft.img"
    shutil.copy2(mac_abbilder.hfs, kopie)
    status, antwort = server.roh("POST", "/api/erfassen", {"platte_id": "HD09", "mountpunkt": str(kopie),
                                                          "art": "abbild", "etikett": " "})
    assert status >= 400 and "Herkunft" in json.dumps(antwort, ensure_ascii=False)


# ---------- Physische Mac-Platte unter Windows (nachgestellt mit dem HFS+-Abbild) ----------

GERAET = "\\\\.\\PhysicalDrive2"


@pytest.fixture
def mac_geraet(leeres_projekt, mac_abbilder, monkeypatch):
    """Tut so, als hinge an einem Windows-Rechner eine Mac-Platte ohne Laufwerksbuchstaben (Inhalt: HFS+-Abbild)."""
    import io
    from erfassung import system
    daten = mac_abbilder.hfs.read_bytes()
    angeschlossen = [{"geraet": GERAET, "nummer": 2, "modell": "Muster Rugged", "seriennummer": "NA8X1234",
                      "anschluss": "USB", "wechselmedium": False, "groesse": len(daten), "laufwerksbuchstaben": False}]
    monkeypatch.setattr(system, "linux", lambda: False)          # Gerätenamen wie unter Windows, auch auf Linux
    monkeypatch.setattr(system, "ist_geraet", lambda p: str(p) in (GERAET, "\\\\.\\PhysicalDrive5"))
    monkeypatch.setattr(system, "geraet_oeffnen", lambda p: (io.BytesIO(daten), len(daten), 4096))
    monkeypatch.setattr(system, "physische_datentraeger", lambda: angeschlossen)
    return SimpleNamespace(daten=daten, angeschlossen=angeschlossen)


def test_mac_platte_pruefen(mac_geraet, mac_abbilder):
    from erfassung import platte
    a = platte.macgeraet_pruefen(GERAET)
    assert a["modell"] == "Muster Rugged" and a["seriennummer"] == "NA8X1234"
    assert [(v["name"], v["uuid"]) for v in a["volumes"]] == [("MAC_HFS", mac_abbilder.uuid["hfs"])]
    with pytest.raises(ValueError):
        platte.macgeraet_pruefen("C:\\Windows")


def test_mac_platte_registrieren_und_lesen(mac_geraet, mac_abbilder):
    from erfassung import platte, schnellscan
    from erfassung.basis import db
    platte.registrieren("HD10", GERAET, etikett="Nachlass Muster, Platte", art="macplatte")
    z = zeile("HD10")
    assert z["art"] == "macplatte" and z["volume_uuid"] == mac_abbilder.uuid["hfs"]
    assert z["geraet"] == "NA8X1234" and z["modell"] == "Muster Rugged" and z["traeger"] == "festplatte"
    assert z["quellordner"] is None                               # die Gerätenummer wechselt bei jedem Anschließen
    schnellscan.schnellscan("HD10", GERAET)
    with db() as con:
        assert con.execute("SELECT COUNT(*) FROM schnellscan WHERE platte_id = 'HD10'").fetchone()[0] == 8
    platte.angeschlossene_platte_pruefen("HD10", GERAET)


def test_mac_platte_wird_an_der_seriennummer_wiedererkannt(mac_geraet):
    """Ohne Administratorrechte: Seriennummer und Größe; die Gerätenummer darf sich ändern."""
    from erfassung import platte
    platte.registrieren("HD10", GERAET, etikett="Platte", art="macplatte")
    mac_geraet.angeschlossen[0].update(geraet="\\\\.\\PhysicalDrive5", nummer=5)
    quellen = {q["platte_id"]: q for q in platte.quellordner_liste()}
    assert quellen["HD10"] == {"platte_id": "HD10", "pfad": "\\\\.\\PhysicalDrive5", "name": "MAC_HFS",
                               "art": "macplatte", "da": True}
    mac_geraet.angeschlossen.clear()
    assert platte.quellordner_liste()[0]["da"] is False


def test_neue_mac_platten_in_der_liste(mac_geraet):
    """Platten ohne Laufwerksbuchstaben, die noch nicht registriert sind, bietet Balduin zum Lesen an."""
    from erfassung import lauf, platte
    assert [g["geraet"] for g in lauf.mac_geraete()] == [GERAET]
    platte.registrieren("HD10", GERAET, etikett="Platte", art="macplatte")
    assert lauf.mac_geraete() == []


def test_original_bleibt_neu_analysierbar_wenn_eine_kopie_gleicher_kennung_registriert_ist(leeres_projekt, abbild):
    """Gefunden in der Windows-VM am 13.11.2026: Nach einer bewusst registrierten Kopie mit gleicher Volume-UUID lehnte
    B jeden neuen Lauf des Originals ab, weil „Neu analysieren“ die Zustimmung nicht mitgibt. Ist eine Kennung schon mit
    genau dieser UUID registriert, ist die Frage beantwortet."""
    from erfassung import platte
    platte.registrieren("HD07", abbild, etikett="Nachlass", art="abbild")
    platte.registrieren("HD08", abbild, etikett="Zweites Exemplar", art="abbild", gleiche_uuid_ok=True)
    platte.registrieren("HD07", abbild, art="abbild")                        # neu analysieren: ohne Rückfrage
    platte.registrieren("HD08", abbild, art="abbild")
    with pytest.raises(ValueError) as fehler:                               # eine dritte Kennung braucht die Zustimmung
        platte.registrieren("HD09", abbild, etikett="Drittes", art="abbild")
    assert "gleiche_uuid_ok" not in str(fehler.value) and "Gleiche UUID oder gleiche Merkmale sind gewollt" in str(fehler.value)

"""Projekte: Balduin öffnet ein Projekt im Modul, in dem zuletzt gearbeitet wurde (Entscheidung 05.11.2026).

Gemerkt wird je Projekt in zuletzt.json (nicht im Browser: dort gilt der Speicher nur je Adresse und Port und für
alle Projekte zusammen). Ohne gemerktes Modul beginnt Balduin mit Modul 1 Registrierung/Analyse.
"""
import json

import pytest

from conftest import Balduin


@pytest.fixture
def zwei_projekte(tmp_path):
    from erfassung import basis
    volumes = tmp_path / "volumes"
    volumes.mkdir()
    for name, kennung in (("Eins", "EA"), ("Zwei", "ZB")):
        basis.projekt_anlegen(tmp_path / name, {"name": name, "kennung": kennung, "virenscan": False,
                                                "anton": {"url": "http://127.0.0.1:9"}})
    server_ordner = tmp_path / "server"
    server_ordner.mkdir()
    b = Balduin(tmp_path / "Eins", volumes, server_ordner)
    yield b, tmp_path
    b.beenden()


def test_ohne_gemerktes_modul_beginnt_balduin_mit_der_analyse(zwei_projekte):
    b, _ = zwei_projekte
    assert b.get("/api/projekte")["offen"]["ansicht"] == "erfassung"


def test_modul_wird_je_projekt_gemerkt(zwei_projekte):
    b, ordner = zwei_projekte
    b.post("/api/ansicht_merken", {"ansicht": "erschliessung"})
    assert b.get("/api/projekte")["offen"]["ansicht"] == "erschliessung"

    b.post("/api/projekt_oeffnen", {"pfad": str(ordner / "Zwei")})
    assert b.get("/api/projekte")["offen"]["ansicht"] == "erfassung"          # anderes Projekt: eigener Stand
    b.post("/api/ansicht_merken", {"ansicht": "export"})

    b.post("/api/projekt_oeffnen", {"pfad": str(ordner / "Eins")})            # erneutes Öffnen behält das Modul
    assert b.get("/api/projekte")["offen"]["ansicht"] == "erschliessung"
    eintraege = json.loads((ordner / "server" / "zuletzt.json").read_text(encoding="utf-8"))["liste"]
    assert {e["name"]: e.get("ansicht") for e in eintraege} == {"Eins": "erschliessung", "Zwei": "export"}


def test_unbekanntes_modul_wird_abgewiesen(zwei_projekte):
    b, _ = zwei_projekte
    b.post("/api/ansicht_merken", {"ansicht": "irgendwas"}, erwartet=400)
    assert b.get("/api/projekte")["offen"]["ansicht"] == "erfassung"


# ---------- Zwei Zahnräder (Entscheidung 05.11.2026) ----------
# Projektweit (vorn in der Modulleiste, vor „Registrierung/Analyse“): Name, Kürzel, Anton-Adresse und Token. Am Knopf „Registrierung/Analyse“: nur, was die
# Analyse betrifft. Beide schreiben über /api/projekt_einstellungen nur ihre eigenen Angaben, jede protokolliert.

PROJEKTWEIT = {"name", "kennung", "anton"}
NUR_ANALYSE = {"film", "pdf", "virenscan", "personen", "referenzprojekte"}


def _protokoll_felder(ordner):
    import sqlite3
    con = sqlite3.connect(ordner / "inventar.sqlite")
    try:
        return {f for (f,) in con.execute("SELECT feld FROM protokoll WHERE abschnitt = 'Projekt' AND feld != 'angelegt'")}
    finally:
        con.close()


def test_projektweite_einstellungen_aendern_nur_ihre_angaben(zwei_projekte):
    b, ordner = zwei_projekte
    vorher = b.get("/api/projekte")["offen"]["einstellungen"]
    b.post("/api/projekt_einstellungen", {"name": "Eins neu", "kennung": "EN", "anton": {"url": "http://127.0.0.1:8/"}})
    nachher = b.get("/api/projekte")["offen"]["einstellungen"]
    assert (nachher["name"], nachher["kennung"], nachher["anton"]["url"]) == ("Eins neu", "EN", "http://127.0.0.1:8")
    assert {k: nachher[k] for k in NUR_ANALYSE} == {k: vorher[k] for k in NUR_ANALYSE}
    assert _protokoll_felder(ordner / "Eins") == PROJEKTWEIT


def test_einstellungen_der_analyse_aendern_nur_ihre_angaben(zwei_projekte):
    b, ordner = zwei_projekte
    vorher = b.get("/api/projekte")["offen"]["einstellungen"]
    b.post("/api/projekt_einstellungen", {"virenscan": True, "personen": True})
    nachher = b.get("/api/projekte")["offen"]["einstellungen"]
    assert nachher["virenscan"] and nachher["personen"]
    assert {k: nachher[k] for k in PROJEKTWEIT} == {k: vorher[k] for k in PROJEKTWEIT}
    assert _protokoll_felder(ordner / "Eins") == {"virenscan", "personen"}


def _kopfleiste():
    """Die Kopfleiste aus index.html als Baum (id → Eltern-Kette), ohne Browser."""
    from html.parser import HTMLParser
    from pathlib import Path

    class Leser(HTMLParser):
        LEER = {"input", "img", "br", "meta", "link", "use", "hr"}

        def __init__(self):
            super().__init__()
            self.stapel, self.ketten = [], {}

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if a.get("id"):
                self.ketten[a["id"]] = [x for x in self.stapel]
            if tag not in self.LEER:
                self.stapel.append((tag, a.get("id"), a.get("class") or ""))

        def handle_endtag(self, tag):
            if tag in self.LEER:
                return
            while self.stapel and self.stapel.pop()[0] != tag:
                pass

    leser = Leser()
    leser.feed((Path(__file__).resolve().parents[1] / "tool" / "web" / "index.html").read_text(encoding="utf-8"))
    return leser.ketten


def test_projektweites_zahnrad_steht_eigenstaendig_vor_der_analyse():
    """Eigener quadratischer Knopf vorn in der Modulleiste, nach dem Projektwechsel und vor „Registrierung/Analyse“;
    nicht am Dashboard (dessen Einstellungen sind es nicht) und nicht an einem Modulknopf."""
    from pathlib import Path
    ketten = _kopfleiste()
    for knopf in ("projekt-einstellungen-knopf", "projekt-einstellungen", "dashboard-knopf", "analyse-einstellungen-knopf"):
        assert knopf in ketten
    knopf = ketten["projekt-einstellungen-knopf"]
    assert ketten["projekt-einstellungen"] == knopf                         # Feld und Knopf im selben Halter
    assert knopf != ketten["dashboard-knopf"]
    assert knopf != ketten["analyse-einstellungen-knopf"]
    assert any(tag == "nav" for tag, _, _ in knopf)
    html = (Path(__file__).resolve().parents[1] / "tool" / "web" / "index.html").read_text(encoding="utf-8")
    stelle = html.index('id="projekt-einstellungen-knopf"')
    assert html.index('id="projekt-knopf"') < stelle < html.index('data-ansicht="erfassung"')
    # am Knopf „Registrierung/Analyse“ bleibt ein eigenes Zahnrad für die Analyse
    assert any(tag == "nav" for tag, _, _ in ketten["analyse-einstellungen-knopf"])
    assert any(tag == "nav" for tag, _, _ in ketten["analyse-einstellungen"])


# ---------- Platte schon in einem anderen Projekt (Feedback 05.11.2026) ----------

def test_warnung_wenn_die_platte_in_einem_anderen_projekt_registriert_ist(zwei_projekte):
    """Erkannt wie im eigenen Projekt (UUID, sonst Name, Dateisystem, Größe); das andere Projekt wird nur gelesen."""
    import sqlite3
    from erfassung import platte
    b, ordner = zwei_projekte
    fremd = ordner / "volumes" / "Fremde Platte"
    fremd.mkdir()
    (fremd / "a.txt").write_text("x", encoding="utf-8")
    info = platte.platteninfo(fremd)
    db = ordner / "Zwei" / "inventar.sqlite"
    with sqlite3.connect(db) as con:
        con.execute("INSERT INTO platte (platte_id, volume_name, volume_uuid, dateisystem, kapazitaet_bytes, registriert_am) "
                    "VALUES ('ZB01', ?, ?, ?, ?, '2026-11-01T10:00:00')",
                    (info["volume_name"], info["volume_uuid"], info["dateisystem"], info["kapazitaet_bytes"]))
    b.post("/api/projekt_oeffnen", {"pfad": str(ordner / "Zwei")})          # Zwei ist damit ein bekanntes Projekt
    b.post("/api/projekt_oeffnen", {"pfad": str(ordner / "Eins")})
    vorher = db.stat().st_mtime_ns
    eintrag = next(d for d in b.get("/api/datentraeger")["angeschlossen"] if d["mountpunkt"] == str(fremd))
    assert eintrag["kennungen"] == []
    assert [(x["projekt"], x["platte_id"]) for x in eintrag["andere_projekte"]] == [("Zwei", "ZB01")]
    assert db.stat().st_mtime_ns == vorher


def test_dasselbe_andere_projekt_zaehlt_nur_einmal(leeres_projekt, tmp_path):
    """Feedback 06.11.2026: Das andere Projekt stand doppelt im Hinweis, weil es unter zwei Schreibweisen bekannt
    war (zuletzt.json in NFD, Ordner der Projekte in NFC). Gleich ist, was auf denselben Ordner zeigt (auch über
    einen Verweis); das eigene Projekt zählt in keiner Schreibweise mit."""
    import unicodedata
    from erfassung import basis, platte
    eigen, volumes = leeres_projekt.ordner, leeres_projekt.volumes
    ordner = tmp_path / "Grüne Platten"
    basis.projekt_anlegen(ordner, {"name": "Grün", "kennung": "GR", "virenscan": False,
                                   "anton": {"url": "http://127.0.0.1:9"}})
    basis.oeffnen(eigen, volumes=volumes)                    # projekt_anlegen öffnet das neue Projekt
    from hilfen.plattform import kann_verknuepfen
    nfd = lambda p: unicodedata.normalize("NFD", str(p))
    pfade = [str(ordner), nfd(ordner), str(eigen), nfd(eigen)]
    if kann_verknuepfen(tmp_path):                       # Windows: Verknüpfungen nur mit besonderen Rechten
        verweis = tmp_path / "Verweis"
        verweis.symlink_to(ordner)
        pfade.append(str(verweis))
    gefunden = platte.in_anderen_projekten(pfade)
    assert [name for name, _, _ in gefunden] == ["Grün"]


# ---------- Vorgabe-Ablageort neuer Projekte (Entscheidung 06.11.2026) ----------
# Steht als „ablageort“ in zuletzt.json; fehlt er oder gibt es den Ordner nicht, gilt Projekte/ neben dem Code
# (in Tests: --projekte). Ein Projekt, das der Assistent anderswo anlegt, macht diesen Ort zur neuen Vorgabe.

@pytest.fixture
def mit_ablageort(tmp_path):
    """Server, dessen zuletzt.json schon einen Ablageort nennt (wie nach dem Umzug des Codes)."""
    from erfassung import basis
    volumes = tmp_path / "volumes"
    volumes.mkdir()
    basis.projekt_anlegen(tmp_path / "Eins", {"name": "Eins", "kennung": "EA", "virenscan": False,
                                              "anton": {"url": "http://127.0.0.1:9"}})
    ablage = tmp_path / "Projekte"
    ablage.mkdir()
    server_ordner = tmp_path / "server"
    server_ordner.mkdir()
    (server_ordner / "zuletzt.json").write_text(json.dumps({"projekt": None, "liste": [], "ablageort": str(ablage)}),
                                                encoding="utf-8")
    b = Balduin(tmp_path / "Eins", volumes, server_ordner)
    yield b, tmp_path, ablage
    b.beenden()


def test_ablageort_aus_zuletzt_ist_die_vorgabe(mit_ablageort):
    b, _, ablage = mit_ablageort
    assert b.get("/api/projekte")["ablageort"] == str(ablage)
    assert b.get("/api/zielordner", ablageort="", name="Neu")["pfad"] == str(ablage / "Neu")


def test_ablageort_bleibt_beim_schreiben_der_liste_erhalten(mit_ablageort):
    b, ordner, ablage = mit_ablageort
    b.post("/api/ansicht_merken", {"ansicht": "bewertung"})
    b.post("/api/projekt_vergessen", {"pfad": str(ordner / "Nirgends")})
    b.post("/api/projekt_oeffnen", {"pfad": str(ordner / "Eins")})
    z = json.loads((ordner / "server" / "zuletzt.json").read_text(encoding="utf-8"))
    assert z["ablageort"] == str(ablage)


def test_fehlender_ablageort_faellt_auf_projekte_neben_dem_code_zurueck(zwei_projekte):
    b, ordner = zwei_projekte
    assert b.get("/api/projekte")["ablageort"] == str(ordner / "server" / "neue_projekte")


def test_ablageort_den_es_nicht_mehr_gibt_faellt_zurueck(mit_ablageort):
    b, ordner, ablage = mit_ablageort
    ablage.rmdir()
    assert b.get("/api/projekte")["ablageort"] == str(ordner / "server" / "neue_projekte")


def test_neues_projekt_an_anderem_ort_wird_neue_vorgabe(mit_ablageort):
    b, ordner, _ = mit_ablageort
    anderswo = ordner / "Anderswo"
    anderswo.mkdir()
    b.post("/api/projekt_anlegen", {"name": "Drei", "kennung": "DR", "ablageort": str(anderswo), "virenscan": False,
                                    "vorschaubilder": {"ort": "projekt"}, "anton": {"url": "http://127.0.0.1:9"}})
    assert (anderswo / "Drei" / "projekt.json").is_file()
    assert b.get("/api/projekte")["ablageort"] == str(anderswo)


# ---------- Nicht gefundenes Projekt neu zuordnen (Entscheidung 13.11.2026) ----------

def test_verschobenes_projekt_bekommt_neuen_ort_und_behaelt_stelle_und_modul(zwei_projekte):
    b, ordner = zwei_projekte
    b.post("/api/projekt_oeffnen", {"pfad": str(ordner / "Zwei")})
    b.post("/api/ansicht_merken", {"ansicht": "bewertung"})
    b.post("/api/projekt_oeffnen", {"pfad": str(ordner / "Eins")})
    (ordner / "Zwei").rename(ordner / "Zwei verschoben")
    vorher = b.get("/api/projekte")["zuletzt"]
    alt = next(z for z in vorher if z["name"] == "Zwei")
    assert not alt["vorhanden"]

    b.post("/api/projekt_verlegen", {"alt": alt["pfad"], "pfad": str(ordner / "Zwei verschoben")})
    nachher = b.get("/api/projekte")["zuletzt"]
    neu = nachher[[z["name"] for z in vorher].index("Zwei")]                   # gleiche Stelle
    assert neu["pfad"] == str((ordner / "Zwei verschoben").resolve())
    assert neu["vorhanden"] and neu["ansicht"] == "bewertung"
    assert len(nachher) == len(vorher)


def test_neuer_ort_muss_ein_projekt_sein(zwei_projekte):
    b, ordner = zwei_projekte
    leer = ordner / "Leer"
    leer.mkdir()
    r = b.post("/api/projekt_verlegen", {"alt": str(ordner / "Zwei"), "pfad": str(leer)}, erwartet=400)
    assert "projekt.json" in r["fehler"]

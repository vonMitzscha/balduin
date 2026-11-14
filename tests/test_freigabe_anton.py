"""Modul 4, Freigabepunkt „Frischer Abruf aus Anton“: Nach jedem Abruf muss der Punkt sagen, wann zuletzt geholt wurde
und warum er noch nicht erfüllt ist (Fehler 06.11.2026: ein Abruf nur mit öffentlichem Zugang dauerte 1–2 s, der Text
blieb gleich, es sah aus, als passiere nichts). Ein Archiv mit nur öffentlichen Beständen ist mit Token vollständig:
Zugang „mit Token“ zählt (Hinweis 06.11.2026)."""
import sys
from datetime import datetime

from conftest import CODE

sys.path.insert(0, str(CODE / "tool"))
from pakete import anton_freigabe_punkt  # noqa: E402

JETZT = datetime(2026, 11, 6, 12, 20)


def stand(**mehr):
    return {"stand": "2026-11-06/77d58b84", "geholt_am": "2026-11-06T12:14:43", "nur_platten": "", "zugang": "intern", **mehr}


def test_vollstaendig_und_frisch_ist_erfuellt():
    p = anton_freigabe_punkt(stand(), JETZT)
    assert p["ok"] and p["punkt"] == "anton"
    assert "06.11.2026 12:14" in p["text"]


def test_zugang_aus_token_und_zahlen():
    from erfassung.anton import zugang_bestimmen
    assert zugang_bestimmen("", 95, 95) == "öffentlich"
    assert zugang_bestimmen("abc", 95, 95) == "mit Token"      # alles öffentlich oder Konto ohne interne Rolle
    assert zugang_bestimmen("abc", 120, 95) == "intern"


def test_mit_token_ohne_mehr_als_oeffentlich_ist_erfuellt():
    p = anton_freigabe_punkt(stand(zugang="mit Token"), JETZT)
    assert p["ok"] and "12:14" in p["text"] and "interne Rolle" in p["text"]   # Restrisiko benannt


def test_ohne_token_nennt_zeit_und_token():
    p = anton_freigabe_punkt(stand(zugang="öffentlich"), JETZT)
    assert not p["ok"]
    assert "06.11.2026 12:14" in p["text"]           # jeder Abruf ändert die Zeit: sichtbar, dass etwas geschah
    assert "ohne API-Token" in p["text"]
    assert p["grund"] == "oeffentlich"


def test_nur_einzelne_platten():
    p = anton_freigabe_punkt(stand(nur_platten="HD01"), JETZT)
    assert not p["ok"] and p["grund"] == "teil" and "HD01" in p["text"] and "12:14" in p["text"]


def test_zu_alt():
    p = anton_freigabe_punkt(stand(geholt_am="2026-10-20T09:00:00"), JETZT)
    assert not p["ok"] and p["grund"] == "alt" and "17 Tage" in p["text"]


def test_noch_nie_geholt():
    p = anton_freigabe_punkt(None, JETZT)
    assert not p["ok"] and p["grund"] == "fehlt" and "Noch kein Bestand" in p["text"]


def test_kontrolle_nennt_den_richtigen_grund():
    """Abschnitt „Kontrolle“ in export.js: nur öffentlich ist nicht „älter als die letzte Übergabe“."""
    import json
    import shutil
    import subprocess
    if not shutil.which("node"):
        return
    skript = CODE / "tool" / "web" / "export.js"

    def frisch(st, spaet):
        code = (f"const m = require({json.dumps(str(skript))});"
                f"process.stdout.write(JSON.stringify(m.exAntonFrisch({json.dumps(st)}, {json.dumps(spaet)})));")
        r = subprocess.run(["node", "-e", code], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)

    assert frisch(stand(), "2026-11-06T10:00:00") == {"frisch": True, "hinweis": ""}
    assert "älter" in frisch(stand(), "2026-11-06T13:00:00")["hinweis"]
    h = frisch(stand(zugang="öffentlich"), "2026-11-06T10:00:00")
    assert not h["frisch"] and "öffentlich" in h["hinweis"] and "älter" not in h["hinweis"]
    assert frisch(stand(zugang="mit Token"), "2026-11-06T10:00:00") == {"frisch": True, "hinweis": ""}
    assert "einzelne Datenträger" in frisch(stand(nur_platten="HD01"), "")["hinweis"]
    assert frisch(None, "") == {"frisch": False, "hinweis": ""}


def test_gleicher_bestand_mit_neuem_zugang_traegt_den_zugang_nach(leeres_projekt):
    """Fehler 06.11.2026 (Testinstanz): Erster Abruf ohne Token, später mit Token. Die Dateien sind dieselben, also „schon
    geladen“; der Zugang blieb „öffentlich“ und die Freigabe rot, obwohl der Token alles sah."""
    from erfassung import anton
    from erfassung.basis import db
    pfad = leeres_projekt.anton / "anton_dateien_2026-11-06_api.csv"
    pfad.parent.mkdir(parents=True, exist_ok=True)

    def abruf(zugang):
        pfad.write_text("md5,dateiname,signatur,titel,anton_datei,link,nur_platten,objekt_id,medien_id,groesse,mime,zugang\n"
                        f"a041fd7ca5e397e6e2e6ff124de1cf9a,a.jpg,ANL 1/2.1,Titel,a.jpg,http://x/id/1,,78,29,3,image/jpeg,{zugang}\n",
                        encoding="utf-8-sig")
        anton.anton_laden(pfad)
        with db() as con:
            return con.execute("SELECT stand, zugang FROM anton_stand WHERE aktuell = 1").fetchall()

    erst = abruf("öffentlich")
    dann = abruf("intern")
    assert len(dann) == 1 and dann[0][0] == erst[0][0]          # derselbe Stand, kein neuer
    assert dann[0][1] == "intern"

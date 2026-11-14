"""Modul 4 Bestand und Export im Server (Entscheidungen 04. und 05.11.2026 in docs/plan.md). Nur Standardbibliothek.

Oberfläche in drei Spalten (tool/web/export.js): Übersicht immer sichtbar, daneben die Aktionen ab der Freigabe,
Packen (3 und 4) als eine Anleitung. Die Rechenwege bleiben in dieser Reihenfolge:
1 Übersicht   was erfasst ist, je Platte die Bestände und je Bestand die Platten (uebersicht), was nach Anton kann und
              was nicht, und was dafür zu tun ist (FEHLER, HINWEISE, TUN)
2 Freigabe    Erschließung abgeschlossen, Dubletten bereinigt, Lesefehler quittiert, frischer Abruf aus Anton,
              Importformat der Instanz abgefragt; erst dann lässt sich planen
3 Ablage und Pakete: Ablage wählen (Arbeitsplatte, anderer Datenträger, Projekt), Pakete planen ohne Platte: je
              Bestandsbox ein Ebenenpaket mit den neuen Ebenen, je Platte und Ziel Teile bis zur Zahl der Dateien;
              die Einträge der metadata.json stehen danach in paket_eintrag, die UUIDs fest in export_einheit
4 Platten packen: Hintergrundlauf der Art „export“ (export/, erfassung/lauf.py) mit der Platte
5 Übergabe an K&R (vermerken), 6 Kontrolle in Anton (MD5, Name, Anzahl), 7 Abschlussbericht
Der Server liest die Quellplatten nie; er löscht nur Paketdateien in seiner Ablage.
"""
import html
import json
import mimetypes
import re
import shutil
import sqlite3
import sys
import time
import uuid as uuid_modul
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from export.schema import SCHEMA_EXPORT, tabellen_umstellen  # noqa: E402,F401  (nur Text und SQL)
from erfassung import system  # noqa: E402  (nur Standardbibliothek)
from erschliessung import datum_lesen, norm, ordner_ziel_teilen, weg_nach_oben, zeit, zeitraum_gueltig, zeitraum_teile  # noqa: E402

SCHEMA = SCHEMA_EXPORT
FERTIG = ("übergeben", "importiert", "unvollständig")   # diese Pakete bleiben beim neuen Planen stehen
ANTON_FRISCH_TAGE = 7                     # so alt darf der vollständige Abruf aus Anton zur Freigabe höchstens sein


def anton_freigabe_punkt(stand, jetzt=None):
    """Freigabepunkt „Frischer Abruf aus Anton“: erfüllt bei vollständigem Abruf (alle Platten, interner Zugang), höchstens
    ANTON_FRISCH_TAGE alt. Der Text nennt immer die Zeit des letzten Abrufs und den Grund, damit ein Klick auf
    „Bestand aus Anton holen“ sichtbar etwas ändert (Fehler 06.11.2026)."""
    jetzt = jetzt or datetime.now()
    nachher = " Danach Dubletten und Abgleich neu (läuft im Abruf mit)."
    if not stand or not stand.get("geholt_am"):
        return {"punkt": "anton", "titel": "Frischer Abruf aus Anton", "ok": False, "grund": "fehlt", "stand": stand,
                "alter_tage": None, "text": "Noch kein Bestand aus Anton geholt." + nachher}
    geholt = datetime.fromisoformat(stand["geholt_am"][:19])
    alter = (jetzt - geholt).days
    wann = geholt.strftime("%d.%m.%Y %H:%M")
    teil = stand.get("nur_platten") or ""
    if (stand.get("zugang") or "intern") == "öffentlich":
        grund, text = "oeffentlich", (f"Letzter Abruf am {wann} ohne API-Token: nur öffentliche Bestände. API-Token in den "
                                      "Einstellungen des Projekts hinterlegen („Verbindung prüfen“), dann neu holen.")
    elif teil:
        grund, text = "teil", f"Letzter Abruf am {wann} war nur ein Auszug für {teil}, nicht der ganze Bestand."
    elif alter > ANTON_FRISCH_TAGE:
        grund, text = "alt", f"Der letzte Abruf ({wann}) ist {alter} Tage alt; höchstens {ANTON_FRISCH_TAGE} Tage."
    elif stand.get("zugang") == "mit Token":
        grund, text = "", (f"Bestand aus Anton mit Token geholt am {wann}. Der Token sieht nicht mehr als öffentlich: "
                           "vollständig, wenn alles öffentlich ist; sonst dem Konto in Anton eine interne Rolle geben.")
    else:
        grund, text = "", f"Vollständiger Bestand aus Anton, geholt am {wann}."
    return {"punkt": "anton", "titel": "Frischer Abruf aus Anton", "ok": not grund, "grund": grund, "stand": stand,
            "alter_tage": alter, "text": text + nachher}
NARA_KATEGORIEN = {"Audio", "Video", "Cinema", "StillImage", "Geospatial", "NavCharts", "DesignVector", "Textual",
                   "Spreadsheets", "Presentation", "Code", "Email", "Web", "Databases", "StructuredData", "Calendars"}
# Akteur:in und Ort am Entstehungsereignis auch ohne Anton-Eintrag (nur Name): Früher brach ein unbekannter Name den
# Import ganz ab (docs/anton_import.md A7); seit anton#814 legt Anton ihn vorläufig an (unknown_authorities =
# provisional), an einer Testinstanz geprüft (14.11.2026)
NEUE_NORMDATEN_AM_EREIGNIS = True

# Fehler (schließen aus) und Hinweise der Kontrolle: Schlüssel → Text
FEHLER = {
    "nicht_erschlossen": "nicht erschlossen (Titel und Entstehungszeitraum fehlen)",
    "keine_pruefsumme": "keine Prüfsumme (MD5) aus der Analyse",
    "doppelt": "gleiche MD5 wie eine andere exportierte oder schon gelieferte Datei (in der Bewertung nur eine übernehmen)",
    "in_anton": "schon in Anton (gleiche MD5); in der Bewertung kassieren",
    "virus": "Virenfund",
    "ziel_fehlt": "die Box oder Ebene der Zuordnung gibt es nicht mehr",
    "ebene_titel": "liegt in einer Ebene ohne eigenen Titel",
    "ebene_gleich": "liegt in einer Ebene, die so heißt wie die Einheit darüber (Anton legte sie zusammen)",
    "ebene_content": "liegt in einer Ebene mit dem Titel „Content“ (verwirft Anton)",
}
HINWEISE = {
    "nicht_zugeordnet": "übernommen, aber noch keiner bestehenden Verzeichnungseinheit zugeordnet",
    "akteur_neu": "Akteur:in oder Ort ohne Anton-Eintrag: geht vorerst nicht mit (ein unbekannter Akteur brach den Import ab)",
    "begriff_neu": "Schlagwort ohne Anton-Eintrag: geht als Name mit; Anton warnt nach der Erweiterung",
    "ohne_mime": "Format unbekannt und Endung ohne MIME-Typ: geht als application/octet-stream",
}
# Was zu tun ist, damit ein Problem verschwindet, und in welchem Modul (Übersicht, Entscheidung 05.11.2026)
TUN = {
    "nicht_erschlossen": ("Titel und Laufzeit erfassen", "erschliessung"),
    "keine_pruefsumme": ("Datenträger anschließen und in der Analyse „Alles Offene fortsetzen“", "erfassung"),
    "doppelt": ("in der Bewertung nur eine Fassung übernehmen", "bewertung"),
    "in_anton": ("in der Bewertung kassieren, sie liegt schon in Anton", "bewertung"),
    "virus": ("in der Bewertung kassieren", "bewertung"),
    "ziel_fehlt": ("in der Erschließung neu zuordnen", "erschliessung"),
    "ebene_titel": ("der Ebene in der Erschließung einen Titel geben", "erschliessung"),
    "ebene_gleich": ("die Ebene in der Erschließung anders benennen", "erschliessung"),
    "ebene_content": ("die Ebene in der Erschließung anders benennen", "erschliessung"),
    "nicht_zugeordnet": ("in der Erschließung einer bestehenden Verzeichnungseinheit zuordnen", "erschliessung"),
    "akteur_neu": ("in der Erschließung einen Anton-Eintrag wählen, sonst bleibt das Feld leer", "erschliessung"),
    "begriff_neu": ("nichts nötig; wenn möglich ein Schlagwort aus Anton wählen", "erschliessung"),
    "ohne_mime": ("nichts nötig", ""),
}

# Für die Freigabe muss alles davon leer sein (Antwort K&R vom 05.11.2026: Freigabestand)
FREIGABE_ERSCHLIESSUNG = ("nicht_erschlossen", "ziel_fehlt", "ebene_titel", "ebene_gleich", "ebene_content")
FREIGABE_DUBLETTEN = ("doppelt", "in_anton")
FREIGABE_DATEIEN = ("keine_pruefsumme", "virus")
STATUS_TEXT = {"geplant": "geplant", "Fehler": "Fehler", "gebaut": "geschrieben", "übergeben": "übergeben",
               "importiert": "in Anton", "unvollständig": "in Anton unvollständig"}


def lehnt_ab(richtlinie):
    """Steht irgendwo in der Formatrichtlinie „reject“? (Form der Antwort nicht dokumentiert, darum jede Stelle.)"""
    if isinstance(richtlinie, dict):
        return any(lehnt_ab(w) for w in richtlinie.values())
    if isinstance(richtlinie, list):
        return any(lehnt_ab(w) for w in richtlinie)
    return isinstance(richtlinie, str) and richtlinie.strip().lower() == "reject"


def im_akzessionsarchiv(box):
    """Bestandsbox im Akzessionsarchiv? Solange offen ist, woran Anton es erkennbar macht (docs/plan.md): „Akzession“
    im Titel der Box oder einer Einheit darüber."""
    return "akzession" in f"{box.get('titel') or ''} {box.get('eltern') or ''}".lower()


def iso_datum(text, ende=False):
    """„TT.MM.JJJJ“, „MM.JJJJ“, „JJJJ“ oder ISO → „JJJJ-MM-TT“ mit 00 für Unbekanntes, wie im Anton-Importformat."""
    text = (text or "").strip()
    m = re.match(r"(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?", text)
    if m:
        return f"{m[1]}-{m[2] or '00'}-{m[3] or '00'}"
    teile = datum_lesen(text)
    return f"{teile[0]:04d}-{teile[1]:02d}-{teile[2]:02d}" if teile else ""


def tausend(n):
    return f"{n:,}".replace(",", "'")


def norm_titel(titel):
    return norm(titel).strip(" .")


def namensteil(text):
    """Erster Teil des Paketnamens: ohne Bindestriche (der Name hat genau drei Teile <x>-agate-<ID>)."""
    return re.sub(r"[^A-Za-z0-9_]", "_", text)


def archivherkunft(platte, pfad, archive):
    """Satz für die Bestandsgeschichte einer Datei (oder eines Einzelstücks), die aus einer Archivdatei stammt
    (Entscheidung 06.11.2026): jede aufgelöste Archivdatei auf dem Weg, von außen nach innen, mit ihrer MD5.
    archive: {(Platte, Pfad der Archivdatei): MD5}. Leer, wenn die Datei frei auf der Platte lag."""
    teile = pfad.split("/")
    wege = ["/".join(teile[:i]) for i in range(1, len(teile) + 1)]
    gefunden = [(w, archive[(platte, w)]) for w in wege if (platte, w) in archive]
    if not gefunden:
        return ""
    md5 = lambda m: f" (MD5 {m})" if m else ""  # noqa: E731
    (erste, m), *weitere = gefunden
    text = f"Entpackt aus der Archivdatei „{erste}“{md5(m)}"
    for w, m in weitere:
        text += f", darin „{w.rsplit('/', 1)[-1]}“{md5(m)}"
    return text + "."


def herkunft_text(platte, gelesen_ohne_schutz=None):
    """Satz für die Bestandsgeschichte (ISAD(G) 3.2.3): von welchem Datenträger mit welchem Etikett; dazu, wenn er
    ohne Schreibschutz gelesen wurde (Entscheidung 13.11.2026), seit wann. platte: Zeile mit platte_id, etikett_text."""
    etikett = (platte.get("etikett_text") or "").strip()
    text = f"Übernommen von Datenträger {platte['platte_id']}" + (f", Etikett: „{etikett}“" if etikett else "") + "."
    if gelesen_ohne_schutz:
        j, m, t = gelesen_ohne_schutz[:10].split("-")
        text += f" Der Datenträger wurde ohne Schreibschutz gelesen (erstmals am {t}.{m}.{j})."
    return text



def ablage_projekt_name():
    """Name der Ablage im Projektordner; „Mac“ nur auf dem Mac (Wording: keine festen Plattformwörter)."""
    return f"Projektordner auf {system.rechnername()}"


def von_hier(altsignatur, x):
    """Stammt die Datei aus diesem Eintrag? Balduin liefert identifier_old „Platte:Pfad“ (bei einem Ordner als
    Einzelstück der Ordner); Anton benennt Dateien beim Import nach der Signatur um (Testinstanz, 14.11.2026), führt aber
    identifier_old weiter."""
    platte, _, pfad = (altsignatur or "").partition(":")
    return bool(pfad) and platte == x["platte_id"] and (x["relpfad"] == pfad or x["relpfad"].startswith(pfad + "/"))

class Pakete:
    def __init__(self, bestand, erfassung, erschliessung):
        self.b, self.erfassung, self.es = bestand, erfassung, erschliessung
        self.cache_stand, self.cache = None, None
        self.ablage_gesucht = 0.0

    def nachziehen(self):
        """Nach eigenem Schreiben: der Bestand im Server ist weiter aktuell (nichts davon betrifft ihn)."""
        with self.b.sperre:
            self.b.stand = self.b.db_stand()

    # ---- Einstellungen und Ablage ----

    def einstellungen(self):
        e = self.erfassung.info["einstellungen"]
        sprache = str((e.get("uebersetzung") or {}).get("sprache") or "de").lower()[:2]
        x = e.get("export") or {}
        return {"dateien_je_paket": int(x.get("dateien_je_paket") or 5000), "gb_je_paket": float(x.get("gb_je_paket") or 0),
                "sprache": sprache if re.fullmatch(r"[a-z]{2}", sprache) else "de", "anton_url": e["anton"]["url"],
                "testinstanz": bool(e["anton"].get("testinstanz"))}

    def einstellen(self, daten):
        """Dateien und GB je Paket (projekt.json → export); erfassung/basis.py prüft und protokolliert."""
        alt = self.einstellungen()
        neu = {"dateien_je_paket": int(daten.get("dateien_je_paket", alt["dateien_je_paket"])),
               "gb_je_paket": float(daten.get("gb_je_paket", alt["gb_je_paket"]))}
        return self.erfassung.einstellungen_aendern({"export": neu})

    def produktiv(self):
        """Geht die Übergabe an eine produktive Anton-Instanz? Dann braucht sie die volle Freigabe. Produktiv ist jede
        Adresse außer lokalen Testinstanzen und solchen, die das Projekt als Testinstanz markiert; dorthin wird als
        Probe übergeben (Entscheidungen 05.11.2026 „Packen schon vor der Freigabe“ und 12.11.2026)."""
        e = self.einstellungen()
        return not (e["testinstanz"] or system.nur_lokal(urlparse(e["anton_url"]).hostname))

    def geliefert_sql(self, p="p"):
        """Bedingung „gilt als geliefert“: übergeben oder in Anton; Probe-Übergaben nicht, solange die Adresse eine
        produktive Instanz ist (dort sind sie nie angekommen). Antwort: (SQL, Werte)."""
        return (f"{p}.status IN ({','.join('?' * len(FERTIG))}) AND NOT (? AND "
                f"COALESCE(json_extract({p}.uebergabe, '$.probe'), 0))", (*FERTIG, int(self.produktiv())))

    def ablage(self):
        """Wo die Pakete hingehen: Ordner, ob angeschlossen, freier Platz. Fehlt der Datenträger, wird höchstens alle
        30 s neu gesucht (über die Volume-UUID; er kann unter anderem Namen wieder auftauchen)."""
        a = dict(self.erfassung.info.get("export_ablage") or {})
        if a.get("ort") and not (a.get("wurzel") and Path(a["wurzel"]).is_dir()) and time.monotonic() - self.ablage_gesucht > 30:
            self.ablage_gesucht = time.monotonic()
            try:
                self.erfassung.info = self.erfassung.aufrufen("projekt")
                a = dict(self.erfassung.info.get("export_ablage") or {})
            except (RuntimeError, ValueError):
                pass
        da = bool(a.get("wurzel")) and Path(a["wurzel"]).is_dir()
        a["da"] = da
        a["frei"] = shutil.disk_usage(a["wurzel"]).free if da else None
        a["name"] = (ablage_projekt_name() if a.get("ort") == "projekt" else a.get("volume_name") or "") if a.get("ort") else ""
        ordner = Path(a["ordner"]) if da and a.get("ordner") else None
        a["belegt"] = sum(f.stat().st_size for f in ordner.glob("*.tar*")) if ordner and ordner.is_dir() else 0
        a["min_frei"] = float(self.erfassung.info["einstellungen"]["speicher"]["min_frei_gb"]) * 1e9 if a.get("ort") == "projekt" else 1e9
        return a

    def ablagen(self):
        """Mögliche Ablagen: beschreibbare Datenträger, die keine registrierte Quellplatte sind, und das Projekt."""
        liste = []
        for d in self.erfassung.datentraeger()["angeschlossen"]:
            if d.get("fehler") or d.get("schreibgeschuetzt") or d.get("kennungen"):
                continue
            try:
                frei = shutil.disk_usage(d["mountpunkt"]).free
            except OSError:
                continue
            liste.append({"mountpunkt": d["mountpunkt"], "name": d["name"], "frei": frei, "groesse": d.get("groesse"),
                          "arbeitsplatte": bool(d.get("arbeitsplatte"))})
        liste.append({"mountpunkt": "projekt", "name": ablage_projekt_name(),
                      "frei": shutil.disk_usage(self.erfassung.projekt).free, "arbeitsplatte": False})
        return {"ablagen": liste}

    def ablage_setzen(self, mountpunkt):
        return self.erfassung.einstellungen_aendern({"export_ablage": mountpunkt or ""})

    # ---- Grunddaten ----

    def boxen_ebenen(self, con):
        boxen = {z["anton_id"]: dict(z) for z in con.execute("SELECT * FROM bestandsbox ORDER BY reihenfolge, anton_id")}
        ebenen = {z["ebene_id"]: dict(z) for z in con.execute("SELECT * FROM ebene")}
        return boxen, ebenen

    def kette(self, ziel, ebenen):
        """Ziel „a:<ID>“ oder „e:<ebene>“ → (Anton-ID der Box, [Ebenen von oben nach unten]) oder None."""
        kette, gesehen = [], set()
        while ziel and ziel.startswith("e:"):
            nr = int(ziel[2:]) if ziel[2:].isdigit() else None
            if nr not in ebenen or nr in gesehen:
                return None
            gesehen.add(nr)
            kette.insert(0, nr)
            ziel = ebenen[nr]["eltern"]
        if ziel and ziel.startswith("a:") and ziel[2:].isdigit():
            return int(ziel[2:]), kette
        return None

    def analyse(self):
        """Kontrolle aller übernommenen Dateien; je Datenbankstand einmal. Antwort: dict mit fehler, hinweise (je
        Schlüssel Liste der Dateien), export (je Datei Box, Ebenen, Ordner-Ebenen), mehrere_platten und Grunddaten."""
        d = self.es.daten()
        stand = (self.b.db_stand(), id(self.b.wirksam_je_datei), json.dumps(self.einstellungen()))
        if stand == self.cache_stand:
            return self.cache
        con = self.b.verbinden()
        try:
            boxen, ebenen = self.boxen_ebenen(con)
            dateidaten = {(z["platte_id"], z["relpfad"]): dict(z) for z in con.execute("""
                SELECT d.platte_id, d.relpfad, d.md5, d.sha256, d.mime, d.puid, d.groesse, a.nara_id, a.nara_kategorie,
                       a.nara_risiko, v.befund
                FROM datei d LEFT JOIN archiv a USING (platte_id, relpfad) LEFT JOIN virenscan v ON v.sha256 = d.sha256""")}
            # schon geliefert (übergeben oder in Anton): zählt nicht mehr als offen und nicht als „schon in Anton“;
            # was die Kontrolle in Anton nicht fand, ist wieder offen (gleiche UUID, Anton kennt sie nicht)
            bedingung, werte = self.geliefert_sql()
            geliefert, geliefert_box = {}, {}
            for z in con.execute("SELECT pe.platte_id, pe.relpfad, pe.md5, p.ziel FROM paket_eintrag pe JOIN paket p "
                                 f"USING (paket_id) WHERE {bedingung} AND pe.relpfad IS NOT NULL "
                                 "AND COALESCE(pe.anton, '') != 'fehlt'", werte):
                geliefert[(z[0], z[1])], geliefert_box[(z[0], z[1])] = z[2], z[3]
        finally:
            con.close()
        fehler, hinweise = defaultdict(list), defaultdict(list)
        ebene_fehler = {}                                # Schlüssel der Ebene → Fehlerschlüssel (gilt für alles darunter)
        export, md5_von = {}, defaultdict(list)
        platten_je_einheit = defaultdict(set)            # Einheit, in die Dateien direkt gehen → Platten
        box_von = {}                                     # Datei → Anton-ID der Bestandsbox (für die Übersicht)

        def titel_von(schluessel, box):
            if schluessel is None:
                return boxen.get(box, {}).get("titel") or ""
            if schluessel.startswith("e:"):
                return ebenen[int(schluessel[2:])]["titel"] or ""
            platte, ordner = schluessel[2:].split("|", 1)
            return self.es.wert_fuer_datei(platte, ordner, "titel", d) if d["werte"].get((platte, ordner), {}).get("titel") else ""

        def ebene_pruefen(schluessel, eltern, box):
            if schluessel in ebene_fehler:
                return ebene_fehler[schluessel]
            titel = titel_von(schluessel, box)
            f = ("ebene_titel" if not titel.strip() else "ebene_content" if norm_titel(titel) == "content"
                 else "ebene_gleich" if norm_titel(titel) == norm_titel(titel_von(eltern, box)) else None)
            ebene_fehler[schluessel] = f
            return f

        for k in d["uebernommen"]:
            platte, relpfad = k
            if k in geliefert:
                continue
            z = self.es.zuordnung_von(platte, relpfad, d)
            if z is None:
                hinweise["nicht_zugeordnet"].append(k)
                continue
            # Ordner mit eigener Ebene auf dem Weg nach oben, solange sie zur selben Zuordnung gehören, als
            # (Platte, Ordner); eine Datei in einer Ordner-Einheit (Ziel „o:…“) hängt unter deren Kette
            weg_platte, weg = platte, weg_nach_oben(relpfad)[1:]
            o_ziel = ordner_ziel_teilen(z["ziel"])
            if o_ziel:
                zo = d["zuordnung"].get(o_ziel)
                if not zo or zo["stufe"] not in ("class", "file"):
                    fehler["ziel_fehlt"].append(k)
                    continue
                z, (weg_platte, o) = zo, o_ziel
                weg = weg_nach_oben(o)
            ordner_ebenen = []
            for o in weg:
                zo = d["zuordnung"].get((weg_platte, o))
                if zo and zo["ziel"] != z["ziel"]:
                    break
                if zo and zo["stufe"] in ("class", "file"):
                    ordner_ebenen.insert(0, (weg_platte, o))
            kette = self.kette(z["ziel"], ebenen)
            if kette is None or kette[0] not in boxen:
                fehler["ziel_fehlt"].append(k)
                continue
            box, ebenen_kette = kette
            box_von[k] = box
            ebenen_schluessel = [f"e:{e}" for e in ebenen_kette] + [f"o:{p}|{o}" for p, o in ordner_ebenen]
            grund = None
            for i, s in enumerate(ebenen_schluessel):
                grund = grund or ebene_pruefen(s, ebenen_schluessel[i - 1] if i else None, box)
            x = dateidaten.get(k) or {}
            if grund:
                fehler[grund].append(k)
                continue
            if k not in d["erschlossen"]:
                fehler["nicht_erschlossen"].append(k)
                continue
            if not x.get("md5"):
                fehler["keine_pruefsumme"].append(k)
                continue
            if x.get("befund") == "Fund":
                fehler["virus"].append(k)
                continue
            if self.b.dateien[k]["anton"] == "in Anton":
                fehler["in_anton"].append(k)
                continue
            if not x.get("mime") and not mimetypes.guess_type(relpfad)[0]:
                hinweise["ohne_mime"].append(k)
            quelle = (platte, self.es.einzelstueck_von(platte, relpfad, d) or relpfad)   # Werte des Einzelstücks
            for feld in ("akteur", "ort"):
                e = d["werte"].get(quelle, {}).get(feld)
                if e and e["gleich"] and not (json.loads(e["gleich"]) or {}).get("anton_id"):
                    hinweise["akteur_neu"].append(k)
                    break
            for feld in ("schlagworte", "orte"):
                e = d["werte"].get(quelle, {}).get(feld)
                if e and e["gleich"] and any(not w.get("anton_id") for w in json.loads(e["gleich"]) or []):
                    hinweise["begriff_neu"].append(k)
                    break
            export[k] = {"box": box, "ebenen": ebenen_kette, "ordner": ordner_ebenen,
                         "einzelstueck": self.es.einzelstueck_von(platte, relpfad, d), **x}
            md5_von[x["md5"]].append(k)
            if not ordner_ebenen:                        # Ordner-Ebenen gehören meist zu einer Platte
                platten_je_einheit[f"e:{ebenen_kette[-1]}" if ebenen_kette else f"a:{box}"].add(platte)
            elif ordner_ebenen[-1][0] != platte:          # Datei von einer anderen Platte in einer Ordner-Einheit
                platten_je_einheit[ebenen_schluessel[-1]] |= {platte, ordner_ebenen[-1][0]}
        schon = set(geliefert.values())
        for md5, liste in md5_von.items():               # Anton wiese die zweite als Duplikat ab
            if len(liste) > 1 or md5 in schon:
                for k in liste:
                    fehler["doppelt"].append(k)
                    export.pop(k, None)
        # Anton vergibt Signaturen in Paketfolge: liefern mehrere Platten in dieselbe Einheit, mischen sie sich (K&R)
        mehrere = []
        for s, platten in platten_je_einheit.items():
            if len(platten) > 1:
                titel = (titel_von(None, int(s[2:])) if s.startswith("a:") else titel_von(s, None)) or s
                mehrere.append({"einheit": titel, "platten": sorted(platten)})
        self.cache_stand = stand
        self.cache = {"fehler": dict(fehler), "hinweise": dict(hinweise), "export": export, "boxen": boxen,
                      "ebenen": ebenen, "uebernommen": d["uebernommen"], "erschlossen": d["erschlossen"],
                      "geliefert": geliefert, "geliefert_box": geliefert_box, "box_von": box_von,
                      "mehrere_platten": mehrere}
        return self.cache

    # ---- Freigabe (Schritt 2) ----

    @staticmethod
    def anton_bestand(con):
        """Aktueller Bestand aus Anton und wann zuletzt geholt: Ein Abruf ohne Änderung legt keinen neuen Stand an,
        bestätigt ihn aber; dann zählt das Ende des letzten erfolgreichen Laufs „Bestand aus Anton“."""
        stand = con.execute("SELECT * FROM anton_stand WHERE aktuell = 1 ORDER BY eingelesen_am DESC LIMIT 1").fetchone()
        if not stand:
            return None
        stand = dict(stand)
        lauf = con.execute("SELECT MAX(ende) FROM lauf WHERE art = 'anton' AND status = 'fertig'").fetchone()[0]
        stand["geholt_am"] = max(stand.get("eingelesen_am") or "", lauf or "")
        return stand

    def lesefehler(self, con):
        """Je Platte im Projekt die nicht lesbaren Pfade (Schnellscan, Prüfsummen) und was davon quittiert ist."""
        aktiv = [p["platte_id"] for p in self.b.platten if not p.get("deaktiviert_am")]
        pfade = defaultdict(dict)
        for z in con.execute("SELECT platte_id, relpfad, fehler FROM scanfehler"):
            pfade[z[0]].setdefault(z[1], z[2] or "nicht lesbar")
        for z in con.execute("SELECT platte_id, relpfad, hash_fehler FROM datei WHERE hash_fehler IS NOT NULL"):
            pfade[z[0]].setdefault(z[1], z[2])
        quittiert = {z[0].split(":", 1)[1]: dict(z) for z in con.execute(
            "SELECT * FROM export_freigabe WHERE punkt LIKE 'lesefehler:%'")}
        liste = []
        for p in aktiv:
            n = len(pfade.get(p, {}))
            q = quittiert.get(p)
            liste.append({"platte_id": p, "anzahl": n, "quittiert": bool(q) and int(q["wert"]) == n,
                          "quittiert_am": q["zeit"] if q else None, "quittiert_anzahl": int(q["wert"]) if q else None,
                          "beispiele": [{"pfad": r, "fehler": f} for r, f in sorted(pfade.get(p, {}).items())[:12]]})
        return liste

    def freigabe(self, a=None):
        """Punkte der Freigabe (Antwort K&R vom 05.11.2026) mit ok, Text und Zahl. Alle ok → Planen erlaubt."""
        a = a or self.analyse()
        zahl = lambda schluessel: sum(len(a["fehler"].get(s, [])) for s in schluessel)  # noqa: E731
        con = self.b.verbinden()
        try:
            lese = self.lesefehler(con)
            stand = self.anton_bestand(con)
            fmt = con.execute("SELECT wert, zeit FROM export_freigabe WHERE punkt = 'importformat'").fetchone()
        finally:
            con.close()
        offen_zu = len(a["hinweise"].get("nicht_zugeordnet", []))
        n_er = zahl(FREIGABE_ERSCHLIESSUNG) + offen_zu
        punkte = [{"punkt": "erschliessung", "titel": "Erschließung abgeschlossen", "ok": n_er == 0, "anzahl": n_er,
                   "text": "Alles Übernommene ist erschlossen und einer bestehenden Verzeichnungseinheit zugeordnet." if not n_er else
                   f"{tausend(n_er)} übernommene Dateien sind nicht erschlossen, nicht zugeordnet oder liegen in einer "
                   "Ebene mit Fehler (Schritt Übersicht)."}]
        n_du = zahl(FREIGABE_DUBLETTEN)
        punkte.append({"punkt": "dubletten", "titel": "MD5 bereinigt", "ok": n_du == 0, "anzahl": n_du,
                       "text": "Jede Prüfsumme kommt nur einmal vor, über alle Datenträger und gegen Anton." if not n_du else
                       f"{tausend(n_du)} Dateien mit gleicher MD5 untereinander oder schon in Anton: in der Bewertung "
                       "nur eine übernehmen bzw. kassieren."})
        n_da = zahl(FREIGABE_DATEIEN)
        punkte.append({"punkt": "dateien", "titel": "Prüfsummen und Virenscan", "ok": n_da == 0, "anzahl": n_da,
                       "text": "Alle übernommenen Dateien haben eine Prüfsumme, kein Virenfund." if not n_da else
                       f"{tausend(n_da)} übernommene Dateien ohne Prüfsumme oder mit Virenfund."})
        offen_lese = [x for x in lese if x["anzahl"] and not x["quittiert"]]
        punkte.append({"punkt": "lesefehler", "titel": "Lesefehler quittiert", "ok": not offen_lese,
                       "anzahl": sum(x["anzahl"] for x in offen_lese), "platten": lese,
                       "text": "Keine offenen Lesefehler." if not offen_lese else
                       "Lesefehler auf " + ", ".join(x["platte_id"] for x in offen_lese) + " ansehen und quittieren."})
        punkte.append(anton_freigabe_punkt(stand))
        fmt_wert = json.loads(fmt["wert"]) if fmt else None
        fmt_alt = fmt and (datetime.now() - datetime.fromisoformat(fmt["zeit"][:19])) > timedelta(days=ANTON_FRISCH_TAGE)
        richtlinie = (fmt_wert or {}).get("formatrichtlinie")
        reject = lehnt_ab(richtlinie)
        text = (f"{self.einstellungen()['anton_url']} liest das Importformat bis {fmt_wert['reads']}; "
                f"Balduin schreibt {fmt_wert['version']} ({fmt['zeit'][:10]})." if fmt_wert else
                "GET /api/import-format noch nicht abgefragt.")
        if fmt_wert and reject:
            text += (" Die Formatrichtlinie der Instanz steht auf „reject“: Eine abgelehnte Datei lässt heute das ganze Paket "
                     "scheitern. Mit dem Betreiber der Anton-Instanz klären oder solche Formate kassieren.")
        elif fmt_wert and richtlinie is not None:
            text += " Formatrichtlinie ohne „reject“ (abgelehnte Formate kommen mit Warnung hinein)."
        elif fmt_wert:
            text += f" Formatrichtlinie nicht abfragbar ({fmt_wert.get('formatrichtlinie_fehler') or 'keine Antwort'})."
        punkte.append({"punkt": "importformat", "titel": "Importformat und Formatrichtlinie der Instanz abgefragt",
                       "ok": bool(fmt_wert) and not fmt_alt and not reject, "wert": fmt_wert, "formatrichtlinie": richtlinie,
                       "text": text + (" Neu abfragen." if fmt_alt else "")})
        return {"ok": all(p["ok"] for p in punkte), "punkte": punkte}

    def quittieren(self, platte_id, wer=""):
        """Lesefehler einer Platte quittieren (gesehen; die Dateien fehlen im Export). Neue Lesefehler heben das auf."""
        con = self.b.verbinden()
        try:
            x = next((p for p in self.lesefehler(con) if p["platte_id"] == platte_id), None)
        finally:
            con.close()
        if x is None:
            raise ValueError(f"{platte_id} ist kein Datenträger im Projekt.")
        with self.b.sperre, self.b.schreibend() as con:
            con.execute("INSERT OR REPLACE INTO export_freigabe VALUES (?,?,?,?)",
                        (f"lesefehler:{platte_id}", str(x["anzahl"]), wer.strip(), zeit()))
            con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                        (zeit(), "Export", platte_id, "lesefehler quittiert", str(x["quittiert_anzahl"] or ""),
                         f"{x['anzahl']} Pfade" + (f" ({wer.strip()})" if wer.strip() else "")))
        self.nachziehen()
        return {"ok": True}

    def importformat_abfragen(self):
        """GET /api/import-format der Instanz (über erfassung.lauf, mit Token falls hinterlegt) und vermerken."""
        a = self.erfassung.aufrufen("export", "--daten", json.dumps({"aktion": "importformat"}))
        with self.b.sperre, self.b.schreibend() as con:
            con.execute("INSERT OR REPLACE INTO export_freigabe VALUES ('importformat', ?, '', ?)",
                        (json.dumps(a, ensure_ascii=False), zeit()))
            con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                        (zeit(), "Export", "Anton", "importformat", "", f"liest {a.get('reads')}, schreibt {a.get('version')}"))
        self.nachziehen()
        return {"ok": True, **a}

    # ---- Einträge der metadata.json ----

    def ereignis(self, zeitraum, akteur=None, ort=None, sprache="de"):
        e = {"type": "creation"}
        if zeitraum:
            von, bis, ca_von, ca_bis = zeitraum
            if von:
                e.update({"date_start": von, "date_end": bis or von, "date_start_ca": bool(ca_von),
                          "date_end_ca": bool(ca_bis)})
        for feld, wert in (("actor", akteur), ("place", ort)):
            if wert and wert.get("anton_id"):
                e[feld] = {"id": int(wert["anton_id"])}
            elif wert and wert.get("name") and NEUE_NORMDATEN_AM_EREIGNIS:
                e[feld] = {"label": {sprache: wert["name"]}}
        return e if len(e) > 1 else None

    def zeitraum_element(self, platte, pfad, datei, d):
        e = d["werte"].get((platte, pfad), {}).get("zeitraum")
        if not e:
            return None
        if datei and e["je_datei"] == "datum" and d["datum"].get((platte, pfad)):
            x = iso_datum(d["datum"][(platte, pfad)])
            return x, x, False, False
        if not zeitraum_gueltig(e["gleich"]):
            return None
        von, bis, ca_von, ca_bis = zeitraum_teile(e["gleich"])
        return iso_datum(von), iso_datum(bis or von), ca_von, ca_bis

    def felder_element(self, platte, pfad, datei, d, sprache, etikett="", stueck=False):
        """Titel, Ereignis, Notizen, Schlagworte und Altsignatur einer Datei oder eines Ordners (alle erfassten Felder,
        Entscheidung 04.11.2026: nichts behelfsmäßig in internal_note)."""
        werte = d["werte"].get((platte, pfad), {})
        lesen = lambda feld: json.loads(werte[feld]["gleich"]) if werte.get(feld) and werte[feld]["gleich"] else None  # noqa: E731
        eintrag = {"title": {sprache: self.es.wert_fuer_datei(platte, pfad, "titel", d)},
                   "identifier_old": f"{platte}:{pfad}" if pfad else platte}
        ereignis = self.ereignis(self.zeitraum_element(platte, pfad, datei, d), lesen("akteur"), lesen("ort"), sprache)
        if ereignis:
            eintrag["events"] = [ereignis]
        notizen = []
        inhalt = self.es.wert_fuer_datei(platte, pfad, "inhalt", d)
        if inhalt:
            notizen.append({"type": "scopecontent", "locale": sprache, "text": inhalt})
        for feld in sorted(f for f in werte if f.startswith("note.")):
            text = self.es.wert_fuer_datei(platte, pfad, feld, d)
            if feld == "note.custod_hist" and etikett and etikett not in text:
                text = f"{text}\n{etikett}".strip()
            if text:
                notizen.append({"type": feld[5:], "locale": sprache, "text": text})
        if (datei or stueck) and etikett and "note.custod_hist" not in werte:   # Plattenetikett gehört zur Überlieferung
            notizen.append({"type": "custod_hist", "locale": sprache, "text": etikett})
        if notizen:
            eintrag["notes"] = notizen
        def verweise(feld):
            return [{"id": int(w["anton_id"])} if w.get("anton_id") else {"label": {sprache: w["name"]}}
                    for w in lesen(feld) or [] if w.get("anton_id") or w.get("name")]
        if verweise("schlagworte"):
            eintrag["keywords"] = verweise("schlagworte")
        if verweise("orte"):                             # Orte des Registers
            eintrag["places"] = verweise("orte")
        if verweise("akteure"):                          # Akteur:innen des Registers (Format 0.8; beim Bauen gefiltert)
            eintrag["actors"] = verweise("akteure")
        if sprachen := [w["code"] for w in lesen("sprachen") or [] if w.get("code")]:
            eintrag["languages"] = sprachen              # ISO 639-2 (Entscheidung 14.11.2026)
        return eintrag

    def ebene_eintrag(self, e, sprache):
        eintrag = {"type": "collection", "level_of_description": e["stufe"] if e["stufe"] in ("class", "file") else "class",
                   "title": {sprache: e["titel"]}}
        zeitraum = (iso_datum(e["von"]), iso_datum(e["bis"] or e["von"]), bool(e["ca"]), bool(e["ca"])) if e["von"] else None
        ereignis = self.ereignis(zeitraum if zeitraum and zeitraum[0] else None, sprache=sprache)
        if ereignis:
            eintrag["events"] = [ereignis]
        if (e["inhalt"] or "").strip():
            eintrag["notes"] = [{"type": "scopecontent", "locale": sprache, "text": e["inhalt"].strip()}]
        return eintrag

    def datei_medium(self, relpfad, x, datei_uuid):
        m = {"uuid": datei_uuid, "name": relpfad.rsplit("/", 1)[-1], "file_path": relpfad,
             "mime_type": x.get("mime") or mimetypes.guess_type(relpfad)[0] or "application/octet-stream", "md5sum": x["md5"], "size_bytes": int(x["groesse"] or 0)}
        if x.get("puid") and x["puid"] != "UNKNOWN":
            m["pronom_id"] = x["puid"]
        if x.get("nara_id") and (x.get("nara_risiko") or "").lower() in ("low", "moderate", "high"):
            m["nara_risk"] = x["nara_risiko"].lower()        # nur für Formate bei NARA (Entscheidung 04.11.2026)
            if x.get("nara_kategorie") in NARA_KATEGORIEN:
                m["nara_category"] = x["nara_kategorie"]
        return m

    # ---- Planen (Schritt 3) ----

    def uuids(self, con, schluessel):
        """Feste UUID je Einheit (und je Medium): vorhandene lesen, fehlende einmal erzeugen und speichern."""
        da = {z[0]: (z[1], z[2]) for z in con.execute("SELECT schluessel, uuid, datei_uuid FROM export_einheit")}
        neu = [(s, str(uuid_modul.uuid4()), str(uuid_modul.uuid4()) if s.startswith("d:") else None, zeit())
               for s in schluessel if s not in da]
        con.executemany("INSERT INTO export_einheit VALUES (?,?,?,?)", neu)
        da.update({s: (u, du) for s, u, du, _ in neu})
        return da

    def planen(self, verwerfen_ok=False, wer=""):
        """Plant alle Pakete neu, die noch nicht übergeben sind. Geschriebene Pakete werden dabei verworfen (Rückfrage).
        Geht auch vor der Freigabe (Entscheidung 05.11.2026): mit kommt, was bereit ist; die Freigabe sperrt erst die
        Übergabe an eine produktive Instanz."""
        a = self.analyse()
        ablage = self.ablage()
        if not ablage.get("ort"):
            raise ValueError("Erst eine Ablage für die Pakete wählen.")
        d = self.es.daten()
        e = self.einstellungen()
        sprache, je_paket = e["sprache"], e["dateien_je_paket"]
        bytes_je_paket = int(e["gb_je_paket"] * 1e9) or None
        if not a["export"]:
            raise ValueError("Nichts zu exportieren: erst übernehmen, erschließen und einer bestehenden Verzeichnungseinheit zuordnen.")
        con = self.b.verbinden()
        try:
            alt = [dict(z) for z in con.execute(
                "SELECT paket_id, name, status, datei, (SELECT COUNT(*) FROM paket_eintrag pe WHERE pe.paket_id = p.paket_id "
                "AND pe.tar_ende IS NOT NULL) AS geschrieben FROM paket p")]
            bedingung, werte = self.geliefert_sql()
            fertig_ids = [z[0] for z in con.execute(f"SELECT paket_id FROM paket p WHERE {bedingung}", werte)]
            erledigt = {z[0]: z[1] for z in con.execute(
                f"SELECT schluessel, paket_id FROM paket_eintrag WHERE paket_id IN ({','.join('?' * len(fertig_ids))}) "
                "AND COALESCE(anton, '') != 'fehlt'", fertig_ids)} if fertig_ids else {}
            teile_bisher = defaultdict(int)
            for z in con.execute(f"SELECT platte_id, ziel, MAX(teil) FROM paket WHERE status IN ({','.join('?' * len(FERTIG))}) "
                                 "AND art = 'teil' GROUP BY platte_id, ziel", FERTIG):
                teile_bisher[(z[0] or "", z[1])] = z[2] or 0
            try:                         # Archivdateien wie Ordner (06.11.2026); ältere Datenbanken ohne Tabelle
                archive = {(z[0], z[1]): z[2] for z in con.execute(
                    "SELECT platte_id, relpfad, md5 FROM archivdatei WHERE status = 'aufgelöst'")}
            except sqlite3.OperationalError:
                archive = {}
            ohne_schutz = {z[0]: z[1] for z in con.execute(       # Entscheidung 13.11.2026
                "SELECT platte_id, gelesen_am FROM schreibschutz_verzicht WHERE gelesen_am IS NOT NULL")}
            ebenen_bisher = defaultdict(int)
            for z in con.execute(f"SELECT ziel, COUNT(*) FROM paket WHERE art = 'ebenen' AND status IN "
                                 f"({','.join('?' * len(FERTIG))}) GROUP BY ziel", FERTIG):
                ebenen_bisher[z[0]] = z[1]
        finally:
            con.close()
        geschrieben = [p for p in alt if p["status"] not in FERTIG and (p["status"] == "gebaut" or p["geschrieben"])]
        if geschrieben and not verwerfen_ok:
            return {"rueckfrage": f"{len(geschrieben)} Pakete sind ganz oder teilweise auf die Ablage geschrieben, aber "
                                  "noch nicht übergeben. Neu planen löscht sie dort; die Platten müssen dafür wieder "
                                  "angeschlossen werden.", "gebaut": [p["name"] for p in geschrieben]}
        boxen, ebenen = a["boxen"], a["ebenen"]
        etiketten = {p["platte_id"]: herkunft_text(p, ohne_schutz.get(p["platte_id"])) for p in self.b.platten}

        def etikett(platte, pfad):       # Plattenetikett und, bei Dateien aus Archivdateien, woraus entpackt
            return " ".join(x for x in (etiketten.get(platte, ""), archivherkunft(platte, pfad, archive)) if x)
        offen = {k: x for k, x in a["export"].items() if f"d:{k[0]}|{k[1]}" not in erledigt}
        pakete = []                      # je Paket: dict mit art, platte, ziel, teil, eintraege [(schluessel, eintrag, eltern, [dateien])]
        # wo eine Einheit angelegt wird: Index in pakete (int) oder ("f", paket_id) eines Pakets, das schon übergeben ist
        erzeugt = {s: ("f", pid) for s, pid in erledigt.items()}

        # 1) Ebenenpakete: je Box die neuen Ebenen, die exportierte Dateien brauchen, Eltern vor Kindern
        for box in boxen:
            noetig = {n for x in offen.values() if x["box"] == box for n in x["ebenen"]}
            kette = set()
            for n in noetig:                                   # mit allen Ebenen darüber
                while n is not None and n in ebenen:
                    kette.add(n)
                    eltern = ebenen[n]["eltern"]
                    n = int(eltern[2:]) if eltern.startswith("e:") else None
            neu = [n for n in kette if f"e:{n}" not in erzeugt]
            if not neu:
                continue
            tiefe = lambda n: 0 if not ebenen[n]["eltern"].startswith("e:") else 1 + tiefe(int(ebenen[n]["eltern"][2:]))  # noqa: E731
            idx = len(pakete)
            ebenen_bisher[box] += 1
            pakete.append({"art": "ebenen", "platte": None, "ziel": box, "teil": ebenen_bisher[box], "eintraege": []})
            for n in sorted(neu, key=lambda n: (tiefe(n), n)):
                eltern = ebenen[n]["eltern"]
                pakete[idx]["eintraege"].append((f"e:{n}", self.ebene_eintrag(ebenen[n], sprache),
                                                 f"e:{eltern[2:]}" if eltern.startswith("e:") else None, []))
                erzeugt[f"e:{n}"] = idx

        # 2) Teile je Platte und Ziel in Baumreihenfolge, bis zur Zahl der Dateien (und den GB, falls gesetzt)
        gruppen = defaultdict(list)
        for k, x in offen.items():
            gruppen[(k[0], x["box"])].append(k)
        for (platte, box) in sorted(gruppen, key=lambda g: (g[0], list(boxen).index(g[1]))):
            dateien = sorted(gruppen[(platte, box)], key=lambda k: [t.casefold() for t in k[1].split("/")])
            # Stücke: eine Datei oder ein Ordner als Einzelstück mit allen seinen Dateien (wird nicht geteilt)
            stuecke, je_ordner = [], {}
            for k in dateien:
                o = offen[k]["einzelstueck"]
                if o is None:
                    stuecke.append([k])
                elif o in je_ordner:
                    je_ordner[o].append(k)
                else:
                    je_ordner[o] = [k]
                    stuecke.append(je_ordner[o])
            teile, jetzt_teil, n_dateien, groesse = [], [], 0, 0
            for stueck in stuecke:
                g = sum(int(offen[k]["groesse"] or 0) for k in stueck)
                if jetzt_teil and (n_dateien + len(stueck) > je_paket or (bytes_je_paket and groesse + g > bytes_je_paket)):
                    teile.append(jetzt_teil)
                    jetzt_teil, n_dateien, groesse = [], 0, 0
                jetzt_teil.append(stueck)
                n_dateien += len(stueck)
                groesse += g
            if jetzt_teil:
                teile.append(jetzt_teil)
            nr = teile_bisher[(platte, box)]
            for liste in teile:
                nr += 1
                idx = len(pakete)
                eintraege = []
                for stueck in liste:
                    k = stueck[0]
                    x = offen[k]
                    oben = f"e:{x['ebenen'][-1]}" if x["ebenen"] else None
                    for op, o in x["ordner"]:                      # Ordner-Ebenen von oben, beim ersten Bedarf
                        s = f"o:{op}|{o}"
                        if s not in erzeugt:
                            zo = d["zuordnung"][(op, o)]
                            eintrag = {"type": "collection", "level_of_description": zo["stufe"],
                                       **self.felder_element(op, o, False, d, sprache)}
                            eintraege.append((s, eintrag, oben, []))
                            erzeugt[s] = idx
                        oben = s
                    o = x["einzelstueck"]
                    if o is None:
                        s = f"d:{platte}|{k[1]}"
                        eintrag = {"type": "record", "level_of_description": "item",
                                   **self.felder_element(platte, k[1], True, d, sprache, etikett(platte, k[1]))}
                    else:                                          # Ordner als ein Einzelstück, Dateien als Medien
                        s = f"i:{platte}|{o}"
                        eintrag = {"type": "record", "level_of_description": "item",
                                   **self.felder_element(platte, o, False, d, sprache, etikett(platte, o), stueck=True)}
                    eintraege.append((s, eintrag, oben, stueck))
                    erzeugt[s] = idx
                pakete.append({"art": "teil", "platte": platte, "ziel": box, "teil": nr, "eintraege": eintraege})

        # UUIDs, Eltern, Abhängigkeiten, erster Eintrag; dann schreiben
        jetzt = zeit()
        alle_schluessel = [s for p in pakete for s, _, _, _ in p["eintraege"]]
        alle_schluessel += [f"d:{k[0]}|{k[1]}" for p in pakete for s, _, _, ks in p["eintraege"]
                            if s.startswith("i:") for k in ks]           # Medien im Einzelstück: feste UUID je Datei
        ordner = Path(ablage["ordner"]) if ablage.get("da") and ablage.get("ordner") else None
        with self.b.sperre, self.b.schreibend() as con:
            uuids = self.uuids(con, alle_schluessel)
            for p in alt:                                      # nicht Übergebenes verwerfen, Geschriebenes löschen
                if p["status"] not in FERTIG:
                    if ordner:
                        for n in (p["name"], p["name"] + ".teil"):
                            (ordner / n).unlink(missing_ok=True)
                    con.execute("DELETE FROM paket_eintrag WHERE paket_id = ?", (p["paket_id"],))
                    con.execute("DELETE FROM paket WHERE paket_id = ?", (p["paket_id"],))
            ids = []
            for i, p in enumerate(pakete):
                x = "Ebenen" if p["art"] == "ebenen" else namensteil(p["platte"])
                name = f"{x}_{p['teil']:03d}-agate-{p['ziel']}.tar"
                braucht, fertige, eintraege = set(), set(), []
                for s, eintrag, eltern, k in p["eintraege"]:
                    neu = {"uuid": uuids[s][0], **eintrag}
                    if eltern:
                        neu["parent"] = {"uuid": uuids[eltern][0]}
                        quelle = erzeugt[eltern]
                        if isinstance(quelle, tuple):
                            fertige.add(quelle[1])
                        elif quelle != i:
                            braucht.add(quelle)
                    if k:
                        neu["files"] = [self.datei_medium(x[1], offen[x], uuids[f"d:{x[0]}|{x[1]}"][1]) for x in k]
                        # Anton benennt Dateien beim Import um; der Name auf dem Datenträger geht als Notiz mit
                        # (Entscheidung 14.11.2026), beim Einzelstück mit mehreren Medien eine Zeile je Datei
                        neu["notes"] = [*neu.get("notes", []), {"type": "source_filename", "locale": sprache,
                                        "text": "\n".join(x[1].rsplit("/", 1)[-1] for x in k)}]
                    eintraege.append((s, neu, eltern, k))
                fehler = self.erster_eintrag(eintraege, p, boxen, uuids, i, erzeugt)
                p["braucht_idx"], p["fertige"] = braucht, fertige
                bytes_ = sum(int(offen[x]["groesse"] or 0) for _, _, _, k in eintraege for x in k)
                pid = con.execute(
                    "INSERT INTO paket (art, platte_id, ziel, teil, name, eintraege, dateien, bytes, braucht, status, "
                    "geplant_am, fehler) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (p["art"], p["platte"], p["ziel"], p["teil"], name, len(eintraege),
                     sum(len(x[3]) for x in eintraege), bytes_, "[]", "Fehler" if fehler else "geplant", jetzt, fehler)).lastrowid
                ids.append(pid)
                # je Eintrag eine Zeile, beim Einzelstück mit mehreren Medien je Datei eine (Bauen, Kontrolle, erledigt);
                # der Eintrag der metadata.json steht nur in der ersten, Schlüssel der Dateizeilen ist d:<Platte>|<Pfad>
                zeilen = []
                for s, e, _, ks in eintraege:
                    text = json.dumps(e, ensure_ascii=False)
                    for j, x in enumerate(ks or [None]):
                        zeilen.append((pid, len(zeilen), f"d:{x[0]}|{x[1]}" if x else s, text if j == 0 else None,
                                       x[0] if x else None, x[1] if x else None, offen[x]["md5"] if x else None,
                                       offen[x]["sha256"] if x else None, int(offen[x]["groesse"] or 0) if x else None))
                con.executemany("INSERT INTO paket_eintrag (paket_id, nr, schluessel, eintrag, platte_id, relpfad, md5, "
                                "sha256, groesse) VALUES (?,?,?,?,?,?,?,?,?)", zeilen)
            for i, pid in enumerate(ids):
                braucht = sorted({ids[j] for j in pakete[i]["braucht_idx"]} | pakete[i]["fertige"])
                con.execute("UPDATE paket SET braucht = ? WHERE paket_id = ?", (json.dumps(braucht), pid))
            con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                        (jetzt, "Export", "Pakete", "planen", f"{len([p for p in alt if p['status'] not in FERTIG])} verworfen",
                         f"{len(pakete)} Pakete, {len(offen):,} Dateien, höchstens {je_paket} Dateien"
                         + (f" und {e['gb_je_paket']:g} GB" if bytes_je_paket else "") + f" je Paket, Sprache {sprache}"
                         + (f" ({wer.strip()})" if wer.strip() else "")))
        self.nachziehen()
        # gegen das Schema prüfen (jsonschema im Hintergrundcode; dauert bei vielen Einträgen einige Sekunden)
        pruefung = self.erfassung.aufrufen("export", "--daten", json.dumps({"aktion": "pruefen", "pakete": ids}))
        mit_fehler = sum(1 for f in pruefung["fehler"].values() if f)
        return {"ok": True, "pakete": len(pakete), "dateien": len(offen), "schemafehler": mit_fehler}

    @staticmethod
    def erster_eintrag(eintraege, p, boxen, uuids, i, erzeugt):
        """Anton verwirft den ersten Eintrag, wenn er „Content“ heißt oder so wie seine Einheit darüber, und legt ihn
        mit ihr zusammen (docs/anton_import.md A5). Dann einen anderen Eintrag nach vorn holen, dessen Einheit darüber
        nicht erst im Paket entsteht; geht das nicht, ist das Paket fehlerhaft. Antwort: Fehlertext oder None."""
        titel = {s: next(iter(e["title"].values()), "") for s, e, _, _ in eintraege}

        def schlecht(j):
            s, e, eltern, _ = eintraege[j]
            t = norm_titel(titel[s])
            oben = titel.get(eltern) if eltern in titel else None
            if eltern is None:
                oben = boxen.get(p["ziel"], {}).get("titel") or ""
            return t == "content" or (oben is not None and t == norm_titel(oben))

        if not eintraege or not schlecht(0):
            return None
        for j in range(1, len(eintraege)):
            eltern = eintraege[j][2]
            if (eltern is None or erzeugt.get(eltern) != i) and not schlecht(j):
                eintraege.insert(0, eintraege.pop(j))
                return None
        return "Der erste Eintrag heißt „Content“ oder wie die Einheit darüber; Anton würde ihn verwerfen. Titel ändern."

    # ---- Stand für die Ansicht ----

    def stand(self):
        a = self.analyse()
        e = self.einstellungen()
        ablage = self.ablage()
        freigabe = self.freigabe(a)
        con = self.b.verbinden()
        try:
            pakete = [dict(z) for z in con.execute(
                "SELECT p.*, (SELECT COUNT(*) FROM paket_eintrag pe WHERE pe.paket_id = p.paket_id AND pe.tar_ende IS NOT NULL) "
                "AS geschrieben FROM paket p ORDER BY paket_id")]
            geplant_am = max((p["geplant_am"] for p in pakete if p["status"] not in FERTIG), default=None)
            geaendert = max((z[0] or "" for z in con.execute(
                "SELECT MAX(zeit) FROM erschliessung UNION ALL SELECT MAX(zeit) FROM zuordnung UNION ALL "
                "SELECT MAX(zeit) FROM ebene UNION ALL SELECT MAX(zeit) FROM entscheidung")), default="")
            laeufe = [dict(z) for z in con.execute(
                "SELECT lauf_id, status, platte_id, meldung, start, ende FROM lauf WHERE art = 'export' "
                "ORDER BY lauf_id DESC LIMIT 8")]
            for lauf in laeufe[:1]:
                lauf["schritte"] = [dict(s) for s in con.execute(
                    "SELECT schritt, titel, status, anteil, text, start, ende FROM lauf_schritt WHERE lauf_id = ? ORDER BY rowid",
                    (lauf["lauf_id"],))]
            for lauf in laeufe:
                lauf["aktiv"] = lauf["status"] in ("eingereiht", "wartet", "läuft")
            anton_je = {z[0]: dict(z) for z in con.execute(
                "SELECT paket_id, TOTAL(anton = 'da') AS da, TOTAL(anton = 'fehlt') AS fehlt, TOTAL(anton = 'name') AS name, "
                "TOTAL(anton = 'mehrfach') AS mehrfach FROM paket_eintrag WHERE relpfad IS NOT NULL GROUP BY paket_id")}
            stand_anton = self.anton_bestand(con)
            anton_lauf = con.execute("SELECT lauf_id, status, meldung, start, ende FROM lauf WHERE art = 'anton' "
                                     "ORDER BY lauf_id DESC LIMIT 1").fetchone()
            anton_lauf = dict(anton_lauf) if anton_lauf else None
            if anton_lauf:
                anton_lauf["aktiv"] = anton_lauf["status"] in ("eingereiht", "wartet", "läuft")
        finally:
            con.close()
        namen = {p["paket_id"]: p["name"] for p in pakete}
        status = {p["paket_id"]: p["status"] for p in pakete}
        for p in pakete:
            braucht = json.loads(p["braucht"] or "[]")
            p["braucht"] = [{"paket_id": b, "name": namen.get(b, str(b)), "status": status.get(b, "?")} for b in braucht]
            p["box"] = (a["boxen"].get(p["ziel"]) or {}).get("titel") or str(p["ziel"])
            p["signatur"] = (a["boxen"].get(p["ziel"]) or {}).get("signatur") or ""
            p["kontrolle"] = json.loads(p["kontrolle"]) if p["kontrolle"] else None
            p["anton"] = {k: int(v) for k, v in anton_je[p["paket_id"]].items() if k != "paket_id"} if p["paket_id"] in anton_je else None
            p["uebergabe"] = json.loads(p["uebergabe"]) if p["uebergabe"] else None

        # Übersicht je Platte: erfasst, übernommen, erschlossen, bereit, Probleme, Pakete
        angeschlossen = self.erfassung.angeschlossen()
        je = defaultdict(lambda: defaultdict(int))
        for k, x in self.b.dateien.items():
            if not x["system"]:
                je[k[0]]["dateien"] += 1
                je[k[0]]["bytes"] += x["groesse"] or 0
        for k in a["uebernommen"]:
            je[k[0]]["uebernommen"] += 1
            je[k[0]]["uebernommen_bytes"] += self.b.dateien[k]["groesse"] or 0
        for k in a["erschlossen"]:
            je[k[0]]["erschlossen"] += 1
        for k, x in a["export"].items():
            je[k[0]]["bereit"] += 1
            je[k[0]]["bereit_bytes"] += int(x["groesse"] or 0)
        for k in a["geliefert"]:
            je[k[0]]["geliefert"] += 1
        for liste in a["fehler"].values():
            for k in liste:
                je[k[0]]["probleme"] += 1
        for k in a["hinweise"].get("nicht_zugeordnet", []):
            je[k[0]]["nicht_zugeordnet"] += 1
        platten = []
        for pl in self.b.platten:
            pid = pl["platte_id"]
            if pl.get("deaktiviert_am"):
                continue
            eigene = [p for p in pakete if p["platte_id"] == pid]
            zaehl = defaultdict(int)
            for p in eigene:
                zaehl[p["status"]] += 1
            q = angeschlossen.get(pid)
            offen = [p for p in eigene if p["status"] in ("geplant", "Fehler")]
            platten.append({"platte_id": pid, "volume": pl["volume_name"], "etikett": pl["etikett_text"] or "",
                            **je[pid], "pakete": len(eigene), "status": dict(zaehl),
                            "offen": len(offen), "offen_bytes": sum((p["bytes"] or 0) for p in offen),
                            "offen_dateien": sum((p["dateien"] or 0) for p in offen),
                            "ungeprueft": sum(1 for p in eigene if p["status"] == "gebaut" and not p["geprueft_am"]),
                            "angeschlossen": bool(q), "mountpunkt": q["mountpunkt"] if q else "",
                            # Ordner als Quelle (05.11.2026): nicht einhängbar, Balduin liest ihn nur
                            "schreibgeschuetzt": bool(q and (q["schreibgeschuetzt"] or q.get("ordner"))),
                            # ohne Schreibschutz lesen: einmal je Datenträger zugestimmt (13.11.2026)
                            "ohne_schreibschutz": bool(self.erfassung.ohne_schreibschutz(pid)),
                            "ordner": pl.get("art") in ("ordner", "abbild"), "abbild": pl.get("art") == "abbild",
                            "verschluesselt": bool(pl.get("verschluesselt")),          # Passwort je Lauf (13.11.2026)
                            "quellordner": pl.get("quellordner") or "",
                            "noetig": bool(je[pid]["bereit"] or eigene)})
        beispiele = lambda v: [{"platte": p, "pfad": r} for p, r in v[:8]]  # noqa: E731
        befund = lambda s, v, art: {"schluessel": s, "art": art, "text": (FEHLER if art == "fehler" else HINWEISE)[s],  # noqa: E731
                                    "tun": TUN[s][0], "ansicht": TUN[s][1], "anzahl": len(v), "beispiele": beispiele(v)}
        kontrolle = {"fehler": [befund(s, v, "fehler") for s, v in a["fehler"].items()],
                     "hinweise": [befund(s, v, "hinweis") for s, v in a["hinweise"].items()],
                     "mehrere_platten": a["mehrere_platten"],
                     "akzession": [{"anton_id": b["anton_id"], "titel": b["titel"], "signatur": b["signatur"]}
                                   for b in a["boxen"].values() if im_akzessionsarchiv(b)]}
        uebersicht = self.uebersicht(a, befund)
        for pl in platten:
            pl.update(uebersicht["platten"].get(pl["platte_id"], {"bestaende": [], "aufgaben": []}))
        gesamt = len(a["export"]) + len(a["geliefert"])
        produktiv = self.produktiv()
        in_anton = sum((p["anton"] or {}).get("da", 0) + (p["anton"] or {}).get("name", 0) + (p["anton"] or {}).get("mehrfach", 0)
                       for p in pakete if p["status"] in FERTIG and not (produktiv and (p["uebergabe"] or {}).get("probe")))
        berichte = sorted((self.erfassung.projekt / "berichte").glob("Abschlussbericht_*.html"), reverse=True)
        return {"einstellungen": e, "ablage": ablage, "freigabe": freigabe,
                "uebernommen": len(a["uebernommen"]), "erschlossen": len(a["erschlossen"]),
                "exportierbar": len(a["export"]), "bytes": sum(int(x["groesse"] or 0) for x in a["export"].values()),
                "geliefert": len(a["geliefert"]), "kontrolle": kontrolle, "platten": platten, "pakete": pakete,
                "bestaende": uebersicht["bestaende"],
                "laeufe": laeufe, "lauf": laeufe[0] if laeufe else None,
                "geplant_am": geplant_am, "veraltet": bool(geplant_am and geaendert > geplant_am),
                "anton_stand": stand_anton, "anton_lauf": anton_lauf, "probe": not produktiv,
                "bericht": {"datei": berichte[0].name, "zeit": berichte[0].stat().st_mtime} if berichte else None,
                "modul": {"anteil": in_anton / gesamt if gesamt else 0, "fertig": bool(gesamt) and in_anton >= gesamt,
                          "in_anton": in_anton, "gesamt": gesamt}}

    def uebersicht(self, a, befund):
        """Übersicht in zwei Richtungen (Entscheidung 05.11.2026): je Platte die Bestandsboxen, in die sie liefert, je
        Bestandsbox die Platten, die sie braucht; je Paar übernommen, erschlossen, bereit, geliefert und die Aufgaben.
        Dateien ohne gültige Box stehen unter dem Bestand None („noch keiner Bestandsbox zugeordnet“)."""
        zahlen = defaultdict(lambda: defaultdict(int))   # (Platte, Box) → Kennzahl → Anzahl
        probleme = defaultdict(lambda: defaultdict(list))  # (Platte, Box) → (Art, Schlüssel) → Dateien
        for k in a["uebernommen"]:
            box = a["geliefert_box"].get(k) if k in a["geliefert"] else a["box_von"].get(k)
            z = zahlen[(k[0], box)]
            z["uebernommen"] += 1
            z["erschlossen"] += k in a["erschlossen"]
            if k in a["geliefert"]:
                z["geliefert"] += 1
            elif k in a["export"]:
                z["bereit"] += 1
                z["bereit_bytes"] += int(a["export"][k]["groesse"] or 0)
        for art, quelle in (("fehler", a["fehler"]), ("hinweis", a["hinweise"])):
            for s, liste in quelle.items():
                for k in liste:
                    probleme[(k[0], a["box_von"].get(k))][(art, s)].append(k)

        def aufgaben(paare):
            summe = defaultdict(list)
            for paar in paare:
                for schluessel, liste in probleme.get(paar, {}).items():
                    summe[schluessel].extend(liste)
            # zuerst, was ausschließt, dann die größten
            return [befund(s, v, art) for (art, s), v in sorted(summe.items(), key=lambda x: (x[0][0] != "fehler", -len(x[1])))]

        def werte(paare):
            w = defaultdict(int)
            for paar in paare:
                for n, v in zahlen.get(paar, {}).items():
                    w[n] += v
            return dict(w)

        boxen = a["boxen"]
        paare = set(zahlen) | set(probleme)
        reihenfolge = list(boxen) + sorted({b for _, b in paare if b is not None and b not in boxen}) + [None]
        kopf = lambda b: ({"anton_id": None, "titel": "Noch keiner bestehenden Verzeichnungseinheit zugeordnet", "signatur": ""} if b is None  # noqa: E731
                          else {"anton_id": b, "titel": (boxen.get(b) or {}).get("titel") or str(b),
                                "signatur": (boxen.get(b) or {}).get("signatur") or "", "link": (boxen.get(b) or {}).get("link") or ""})
        bestaende = []
        for b in reihenfolge:
            platten = sorted({p for p, x in paare if x == b})
            if b is None and not platten:
                continue
            bestaende.append({**kopf(b), **werte([(p, b) for p in platten]), "aufgaben": aufgaben([(p, b) for p in platten]),
                              "platten": [{"platte_id": p, **werte([(p, b)]), "aufgaben": aufgaben([(p, b)])} for p in platten]})
        je_platte = {}
        for p in sorted({p for p, _ in paare}):
            eigene = [b for b in reihenfolge if (p, b) in paare]
            je_platte[p] = {"aufgaben": aufgaben([(p, b) for b in eigene]),
                            "bestaende": [{**kopf(b), **werte([(p, b)]), "aufgaben": aufgaben([(p, b)])} for b in eigene]}
        return {"bestaende": bestaende, "platten": je_platte}

    # ---- Läufe (Schritt 4) ----

    def starten(self, daten):
        """Reiht einen Lauf der Art „export“ ein: mit Platte deren Teile (und die Ebenenpakete) schreiben, ohne Platte
        nur die Ebenenpakete; danach nachprüfen. Vorher sichert der Lauf die Datenbank."""
        platte = (daten.get("platte_id") or "").strip()
        ablage = self.ablage()
        if not ablage.get("ort"):
            raise ValueError("Erst eine Ablage für die Pakete wählen.")
        if not ablage["da"]:
            raise ValueError(f"Die Ablage {ablage['name']} ist nicht angeschlossen.")
        mountpunkt = None
        if platte:
            q = self.erfassung.angeschlossen().get(platte)
            if not q:
                raise ValueError(f"{platte} ist nicht angeschlossen.")
            mountpunkt = str(self.erfassung.quellpfad_pruefen(q["mountpunkt"]))
            if daten.get("beschreibbar_ok"):           # Rückfrage beantwortet: gilt für diesen Datenträger (13.11.2026)
                self.erfassung.ohne_schreibschutz_zustimmen(platte)
            if not q["schreibgeschuetzt"] and not q.get("ordner"):
                if not self.erfassung.ohne_schreibschutz(platte):
                    raise ValueError(f"{platte} ist beschreibbar eingehängt. Erst schreibgeschützt einhängen oder dem "
                                     "Lesen ohne Schreibschutz zustimmen.")
                daten = {**daten, "beschreibbar_ok": True}
        con = self.b.verbinden()
        try:
            belegt = con.execute("SELECT 1 FROM lauf WHERE art = 'export' AND status IN ('eingereiht', 'wartet', 'läuft')").fetchone()
            offen = con.execute("SELECT COUNT(*), COALESCE(SUM(bytes), 0) FROM paket WHERE (status IN ('geplant', 'Fehler') "
                                "AND (art = 'ebenen' OR platte_id = ?)) OR (status = 'gebaut' AND geprueft_am IS NULL)",
                                (platte,)).fetchone()
        finally:
            con.close()
        if belegt:
            raise ValueError("Ein Export läuft schon oder ist eingereiht.")
        if not offen[0]:
            raise ValueError("Für diese Auswahl ist nichts zu schreiben. Zuerst „Pakete planen“.")
        if ablage["frei"] is not None and ablage["frei"] - offen[1] < ablage["min_frei"]:
            raise ValueError(f"Auf der Ablage {ablage['name']} sind {ablage['frei'] / 1e9:.1f} GB frei; die Pakete brauchen "
                             f"{offen[1] / 1e9:.1f} GB (und {ablage['min_frei'] / 1e9:g} GB sollen frei bleiben).")
        auftrag = {"platte_id": platte or None, "mountpunkt": mountpunkt, "beschreibbar_ok": bool(daten.get("beschreibbar_ok"))}
        passwort = self.erfassung.passwort_klaeren(platte, daten.get("passwort"), mountpunkt)   # verschlüsselt (13.11.2026)
        if passwort:
            auftrag["mit_passwort"] = True
        with self.b.schreibend() as con:
            lauf_id = con.execute("INSERT INTO lauf (art, platte_id, auftrag, status, start) VALUES ('export', ?, ?, "
                                  "'eingereiht', ?)", (platte or None, json.dumps(auftrag, ensure_ascii=False), zeit())).lastrowid
            con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                        (zeit(), "Export", f"Lauf {lauf_id}", "start", "",
                         (f"Datenträger {platte}" if platte else "ohne Datenträger") + f", Ablage {ablage['name']}"))
        gestartet = self.erfassung.weiter({lauf_id: passwort} if passwort else None)
        return {"ok": True, "lauf_id": lauf_id, "eingereiht": lauf_id not in gestartet}

    # ---- Übergabe (Schritt 5), Kontrolle (Schritt 6) ----

    def uebergeben(self, daten):
        """Vermerkt geschriebene und nachgeprüfte Pakete als an K&R übergeben (wann, wie, Notiz)."""
        ids = [int(x) for x in daten.get("pakete") or []]
        notiz = (daten.get("notiz") or "").strip()
        con = self.b.verbinden()
        try:
            pakete = [dict(z) for z in con.execute(
                f"SELECT paket_id, name, status, geprueft_am FROM paket WHERE paket_id IN ({','.join('?' * len(ids))})", ids)] if ids else []
        finally:
            con.close()
        falsch = [p["name"] for p in pakete if p["status"] != "gebaut" or not p["geprueft_am"]]
        if not pakete or falsch:
            raise ValueError("Übergeben lassen sich nur geschriebene und nachgeprüfte Pakete" + (f": {', '.join(falsch[:5])}" if falsch else "."))
        probe = not self.produktiv()
        if not probe and not self.freigabe()["ok"]:
            raise ValueError("An eine produktive Instanz wird erst übergeben, wenn die Freigabe vollständig ist (Schritt 2). "
                             "Pakete lassen sich schon vorher planen und packen.")
        ablage = self.ablage()
        vermerk = json.dumps({"notiz": notiz, "ablage": ablage.get("name"), "wer": (daten.get("wer") or "").strip(),
                              "anton_url": self.einstellungen()["anton_url"], "probe": probe}, ensure_ascii=False)
        with self.b.sperre, self.b.schreibend() as con:
            for p in pakete:
                con.execute("UPDATE paket SET status = 'übergeben', uebergeben_am = ?, uebergabe = ? WHERE paket_id = ?",
                            (zeit(), vermerk, p["paket_id"]))
                con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                            (zeit(), "Export", p["name"], "status", "gebaut", "übergeben" + (" (Probe)" if probe else "")
                             + (f": {notiz}" if notiz else "")))
        self.nachziehen()
        self.lieferschein()
        return {"ok": True, "uebergeben": len(pakete), "probe": probe}

    def zuruecknehmen(self, paket_id):
        """Übergabe zurücknehmen (falsch vermerkt oder das Paket kam nicht an): wieder „geschrieben“, solange die Datei
        auf der Ablage liegt und die Kontrolle in Anton nichts davon gefunden hat."""
        con = self.b.verbinden()
        try:
            p = dict(con.execute("SELECT * FROM paket WHERE paket_id = ?", (int(paket_id),)).fetchone() or {})
            da = con.execute("SELECT COUNT(*) FROM paket_eintrag WHERE paket_id = ? AND anton IN ('da', 'name', 'mehrfach')",
                             (int(paket_id),)).fetchone()[0]
        finally:
            con.close()
        if p.get("status") not in FERTIG:
            raise ValueError("Nur übergebene Pakete lassen sich zurücknehmen.")
        if da:
            raise ValueError(f"{da} Dateien dieses Pakets sind schon in Anton; zurücknehmen geht nicht (eine UUID wird nie "
                             "zweimal geliefert). Fehlende Dateien kommen beim nächsten Planen in ein neues Paket.")
        a = self.ablage()
        if not (a["da"] and p.get("datei") and (Path(a["ordner"]) / p["datei"]).is_file()):
            raise ValueError("Die Paketdatei liegt nicht mehr auf der Ablage.")
        with self.b.sperre, self.b.schreibend() as con:
            con.execute("UPDATE paket SET status = 'gebaut', uebergeben_am = NULL, uebergabe = NULL, kontrolle = NULL, "
                        "kontrolle_am = NULL WHERE paket_id = ?", (int(paket_id),))
            con.execute("UPDATE paket_eintrag SET anton = NULL WHERE paket_id = ?", (int(paket_id),))
            con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)", (zeit(), "Export", p["name"], "status", p["status"], "gebaut"))
        self.nachziehen()
        return {"ok": True}

    def kontrolle(self):
        """Kontrolle nach dem Import: je übergebene Datei MD5, Name und Anzahl im aktuellen Bestand aus Anton (G5b).
        Braucht einen vollständigen Abruf mit Token, der jünger ist als die Übergabe."""
        con = self.b.verbinden()
        try:
            stand = self.anton_bestand(con)
            bedingung, werte = self.geliefert_sql()
            pakete = [dict(z) for z in con.execute(f"SELECT * FROM paket p WHERE {bedingung} ORDER BY paket_id", werte)]
            if not pakete:
                raise ValueError("Noch kein Paket übergeben" + (" (Probe-Übergaben zählen bei einer produktiven Instanz nicht)." if self.produktiv() else "."))
            spaet = max(p["uebergeben_am"] or "" for p in pakete)
            if not stand or (stand["nur_platten"] or "") or (stand["zugang"] or "intern") == "öffentlich":
                raise ValueError("Für die Kontrolle braucht es einen vollständigen Abruf aus Anton mit Token "
                                 "(„Bestand aus Anton holen“).")
            if stand["geholt_am"] < spaet:
                raise ValueError(f"Der Bestand aus Anton ist vom {stand['geholt_am'][:16].replace('T', ' ')}, älter als "
                                 "die letzte Übergabe. Erst „Bestand aus Anton holen“, nachdem der Betreiber den Import gemeldet hat.")
            in_anton = defaultdict(list)
            for z in con.execute("SELECT md5, dateiname, anton_datei, signatur, link, altsignatur FROM anton_datei WHERE stand = ?",
                                 (stand["stand"],)):
                in_anton[z[0]].append(dict(z))
            eintraege = defaultdict(list)
            for z in con.execute(f"SELECT paket_id, nr, platte_id, relpfad, md5, eintrag FROM paket_eintrag WHERE relpfad IS NOT NULL "
                                 f"AND paket_id IN ({','.join('?' * len(pakete))})", [p["paket_id"] for p in pakete]):
                eintraege[z[0]].append(dict(z))
        finally:
            con.close()
        neu_eintraege, neu_pakete, jetzt = [], [], zeit()
        for p in pakete:
            zaehl = defaultdict(int)
            for x in eintraege[p["paket_id"]]:
                treffer = in_anton.get(x["md5"], [])
                name = x["relpfad"].rsplit("/", 1)[-1]
                ergebnis = ("fehlt" if not treffer else "mehrfach" if len(treffer) > 1
                            else "da" if name in (treffer[0]["dateiname"], treffer[0]["anton_datei"])
                            or von_hier(treffer[0]["altsignatur"], x) else "name")
                zaehl[ergebnis] += 1
                t = treffer[0] if treffer else {}
                neu_eintraege.append((ergebnis, t.get("signatur"), t.get("link"), p["paket_id"], x["nr"]))
            neu_pakete.append([p, dict(zaehl)])
        # Ebenenpakete haben keine Dateien: angekommen, sobald ein Paket darauf in Anton Dateien hat
        angekommen = {p["paket_id"] for p, z in neu_pakete if sum(z.values()) - z.get("fehlt", 0) > 0}
        for p, z in neu_pakete:
            braucht_mich = [q for q, _ in neu_pakete if p["paket_id"] in json.loads(q["braucht"] or "[]")]
            if p["art"] == "ebenen":
                z["ebenen"] = p["eintraege"]
                p["neu"] = "importiert" if any(q["paket_id"] in angekommen for q in braucht_mich) else "übergeben"
            else:
                p["neu"] = "unvollständig" if z.get("fehlt") else "importiert"
        with self.b.sperre, self.b.schreibend() as con:
            con.executemany("UPDATE paket_eintrag SET anton = ?, anton_signatur = ?, anton_link = ? WHERE paket_id = ? AND nr = ?",
                            neu_eintraege)
            for p, z in neu_pakete:
                con.execute("UPDATE paket SET status = ?, kontrolle_am = ?, kontrolle = ?, importiert_am = COALESCE(importiert_am, "
                            "CASE WHEN ? = 'importiert' THEN ? END) WHERE paket_id = ?",
                            (p["neu"], jetzt, json.dumps(z), p["neu"], jetzt, p["paket_id"]))
                if p["neu"] != p["status"]:
                    con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)",
                                (jetzt, "Export", p["name"], "status", p["status"], f"{p['neu']} {json.dumps(z)}"))
        self.nachziehen()
        summe = defaultdict(int)
        for _, z in neu_pakete:
            for k, v in z.items():
                if k != "ebenen":
                    summe[k] += v
        return {"ok": True, "pakete": len(neu_pakete), **summe}

    def abweichungen(self, grenze=500):
        """Liste der Dateien, die die Kontrolle nicht wie erwartet in Anton fand (fehlt, Name anders, mehrfach)."""
        con = self.b.verbinden()
        try:
            zeilen = [dict(z) for z in con.execute(
                "SELECT p.name AS paket, pe.platte_id, pe.relpfad, pe.md5, pe.anton, pe.anton_signatur, pe.anton_link "
                "FROM paket_eintrag pe JOIN paket p USING (paket_id) WHERE pe.anton IN ('fehlt', 'name', 'mehrfach') "
                "ORDER BY pe.anton, p.paket_id, pe.nr LIMIT ?", (grenze,))]
        finally:
            con.close()
        return {"abweichungen": zeilen}

    # ---- Aktionen an Paketdateien ----

    def paketdatei(self, paket_id):
        con = self.b.verbinden()
        try:
            p = con.execute("SELECT * FROM paket WHERE paket_id = ?", (int(paket_id),)).fetchone()
        finally:
            con.close()
        if p is None:
            raise ValueError(f"Paket {paket_id} unbekannt")
        a = self.ablage()
        pfad = Path(a["ordner"]) / p["datei"] if a["da"] and p["datei"] else None
        return dict(p), pfad

    def datei_loeschen(self, paket_id):
        """Paketdatei auf der Ablage löschen: nur, wenn die Kontrolle alles in Anton gefunden hat (oder es noch nicht
        übergeben ist; dann muss es neu geschrieben werden). Harte Regel 4, Entscheidung 06.11.2026."""
        p, pfad = self.paketdatei(paket_id)
        if p["status"] == "übergeben":
            raise ValueError("Erst die Kontrolle in Anton abwarten; bis dahin bleibt die Datei als Sicherung liegen.")
        if p["status"] == "unvollständig":
            raise ValueError("Die Kontrolle hat nicht alle Dateien in Anton gefunden; die Datei bleibt als Sicherung "
                             "liegen, bis eine spätere Kontrolle alles findet.")
        if pfad and pfad.is_file() and pfad.parent.name == "export":
            pfad.unlink()
        neu = "geplant" if p["status"] == "gebaut" else p["status"]
        with self.b.sperre, self.b.schreibend() as con:
            con.execute("UPDATE paket SET status = ?, datei_geloescht_am = ?, datei = CASE WHEN ? = 'geplant' THEN NULL "
                        "ELSE datei END, geprueft_am = CASE WHEN ? = 'geplant' THEN NULL ELSE geprueft_am END "
                        "WHERE paket_id = ?", (neu, zeit(), neu, neu, int(paket_id)))
            if neu == "geplant":
                con.execute("UPDATE paket_eintrag SET tar_ende = NULL WHERE paket_id = ?", (int(paket_id),))
            con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)", (zeit(), "Export", p["name"], "datei gelöscht", p["status"], neu))
        self.nachziehen()
        self.lieferschein()
        return {"ok": True, "status": neu}

    def lieferschein(self):
        try:
            self.erfassung.aufrufen("export", "--daten", json.dumps({"aktion": "lieferschein"}))
        except (RuntimeError, ValueError):
            pass                                          # Ablage nicht angeschlossen: beim nächsten Mal

    def zeigen(self, paket_id=None, bericht=False):
        """Paketdatei, den Ordner der Ablage oder den letzten Abschlussbericht im Dateimanager zeigen."""
        if bericht:
            liste = sorted((self.erfassung.projekt / "berichte").glob("Abschlussbericht_*.html"))
            pfad = liste[-1] if liste else None
        elif paket_id:
            _, pfad = self.paketdatei(paket_id)
        else:
            a = self.ablage()
            pfad = Path(a["ordner"]) if a["da"] and a.get("ordner") else None
            if pfad:
                pfad.mkdir(parents=True, exist_ok=True)
        if not pfad or not pfad.exists():
            raise ValueError("Die Ablage ist nicht angeschlossen oder die Datei fehlt.")
        system.im_dateimanager_zeigen(pfad)
        return {"ok": True}

    def eintraege(self, paket_id, grenze=400):
        """Einträge eines Pakets für die Ansicht (Titel, Stufe, Datei, Kontrolle); die metadata.json bei Bedarf."""
        con = self.b.verbinden()
        try:
            zeilen = con.execute("SELECT nr, schluessel, eintrag, relpfad, groesse, tar_ende, anton, anton_signatur "
                                 "FROM paket_eintrag WHERE paket_id = ? ORDER BY nr LIMIT ?", (int(paket_id), grenze)).fetchall()
            gesamt = con.execute("SELECT COUNT(*) FROM paket_eintrag WHERE paket_id = ? AND eintrag IS NOT NULL", (int(paket_id),)).fetchone()[0]
        finally:
            con.close()
        liste = []
        for z in zeilen:
            if z["eintrag"] is None:                     # weiteres Medium eines Einzelstücks
                if liste:
                    liste[-1]["medien"] = liste[-1].get("medien", 1) + 1
                continue
            e = json.loads(z["eintrag"])
            liste.append({"nr": z["nr"], "titel": next(iter(e["title"].values()), ""), "stufe": e.get("level_of_description"),
                          "typ": e["type"], "pfad": z["relpfad"] or "", "groesse": z["groesse"], "geschrieben": z["tar_ende"] is not None,
                          "anton": z["anton"], "signatur": z["anton_signatur"], "eintrag": e})
        return {"eintraege": liste, "gesamt": gesamt}

    # ---- Abschlussbericht (Schritt 7) ----

    def bericht(self):
        """Abschlussbericht für das Archiv als eigenständige HTML-Datei in berichte/: je Platte erfasst, kassiert,
        zurückgestellt, übernommen (Anzahl und Größe), dazu Export und Stand in Anton."""
        s = self.stand()
        arten = ("übernehmen", "kassieren", "zurückstellen", "offen")
        je = defaultdict(lambda: defaultdict(lambda: [0, 0]))
        for k, x in self.b.dateien.items():
            w = self.b.wirksam_je_datei.get(k)
            art = "system" if x["system"] else (w[0] if w and w[0] in arten[:3] else "offen")
            for schluessel in (k[0], "Σ"):
                je[schluessel][art][0] += 1
                je[schluessel][art][1] += x["groesse"] or 0
                je[schluessel]["erfasst"][0] += 1
                je[schluessel]["erfasst"][1] += x["groesse"] or 0
        g = lambda n: f"{n / 1e9:,.1f} GB".replace(",", "'") if n >= 1e8 else f"{n / 1e6:,.0f} MB".replace(",", "'")  # noqa: E731
        z = tausend
        esc = html.escape
        platten = {p["platte_id"]: p for p in self.b.platten}
        reihen = [p for p in je if p != "Σ"] + ["Σ"]
        spalten = [("erfasst", "erfasst"), ("übernehmen", "übernommen"), ("kassieren", "kassiert"),
                   ("zurückstellen", "zurückgestellt"), ("offen", "unentschieden"), ("system", "Systemdateien")]
        kopf = "".join(f"<th>{t}</th>" for _, t in spalten)
        zeilen = "".join(
            f"<tr{' class=summe' if p == 'Σ' else ''}><td><b>{esc(p if p != 'Σ' else 'Alle Platten')}</b>"
            + (f"<div class=leise>{esc((platten.get(p, {}).get('etikett_text') or '').splitlines()[0] if (platten.get(p, {}).get('etikett_text') or '') else '')}</div>" if p != "Σ" else "")
            + "</td>" + "".join(f"<td>{z(je[p][k][0])}<div class=leise>{g(je[p][k][1])}</div></td>" for k, _ in spalten) + "</tr>"
            for p in reihen)
        export_zeilen = "".join(
            f"<tr><td>{esc(pl['platte_id'])}</td><td>{z(pl.get('uebernommen', 0))}</td><td>{z(pl.get('erschlossen', 0))}</td>"
            f"<td>{z(pl.get('geliefert', 0))}</td><td>{z(pl.get('bereit', 0))}</td><td>{z(pl.get('probleme', 0) + pl.get('nicht_zugeordnet', 0))}</td></tr>"
            for pl in s["platten"])
        paket_zeilen = "".join(
            f"<tr><td>{esc(p['name'])}</td><td>{esc(p['signatur'] + ' · ' if p['signatur'] else '')}{esc(p['box'])}</td>"
            f"<td>{z(p['dateien'] or 0)}</td><td>{g(p['bytes'] or 0)}</td><td>{esc(STATUS_TEXT.get(p['status'], p['status']))}{' (Probe)' if (p['uebergabe'] or {}).get('probe') else ''}</td>"
            f"<td>{esc((p['uebergeben_am'] or '')[:10])}</td><td>{esc((p['kontrolle_am'] or '')[:10])}"
            + (f" · {z((p['anton'] or {}).get('fehlt') or 0)} fehlen" if (p['anton'] or {}).get('fehlt') else "") + "</td></tr>"
            for p in s["pakete"])
        name = self.erfassung.info["name"]
        jetzt = datetime.now()
        inhalt = f"""<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Abschlussbericht {esc(name)}</title>
<style>body{{font:14px/1.45 -apple-system,"Segoe UI",Helvetica,Arial,sans-serif;color:#1d2433;max-width:1100px;margin:2rem auto;padding:0 1rem}}
h1{{font-size:1.6rem;margin:0}}h2{{font-size:1.1rem;margin-top:2rem;border-bottom:1px solid #d5dae3;padding-bottom:.3rem}}
table{{border-collapse:collapse;width:100%;margin-top:.5rem}}th,td{{text-align:left;padding:.35rem .5rem;border-bottom:1px solid #e6e9ef;vertical-align:top}}
th{{font-weight:600;background:#f4f6f9}}td+td,th+th{{text-align:right}}.leise{{color:#6b7385;font-size:.85em}}tr.summe td{{border-top:2px solid #1d2433;font-weight:600}}
.zahlen{{display:flex;gap:2rem;flex-wrap:wrap;margin-top:1rem}}.zahlen b{{display:block;font-size:1.4rem}}</style></head><body>
<h1>Abschlussbericht · {esc(name)}</h1>
<div class="leise">Erstellt am {jetzt:%d.%m.%Y %H:%M} mit Balduin · Anton: {esc(s['einstellungen']['anton_url'])}
{f" · Bestand aus Anton geholt am {esc(s['anton_stand']['geholt_am'][:10])}" if s['anton_stand'] else ""}</div>
<div class="zahlen"><div><b>{z(je['Σ']['erfasst'][0])}</b>Dateien erfasst · {g(je['Σ']['erfasst'][1])}</div>
<div><b>{z(je['Σ']['übernehmen'][0])}</b>übernommen · {g(je['Σ']['übernehmen'][1])}</div>
<div><b>{z(s['modul']['in_anton'])}</b>davon über Balduin in Anton</div></div>
<h2>Bewertung je Datenträger</h2>
<div class="leise">Wirksame Entscheidung je Datei (eigene Entscheidung, sonst globale Einstellung, sonst die des nächsten Ordners). Systemdateien (.DS_Store u. Ä.) werden nicht bewertet.</div>
<div style="overflow-x:auto"><table><thead><tr><th>Datenträger</th>{kopf}</tr></thead><tbody>{zeilen}</tbody></table></div>
<h2>Export nach Anton</h2>
<div style="overflow-x:auto"><table><thead><tr><th>Datenträger</th><th>übernommen</th><th>erschlossen</th><th>geliefert</th><th>noch offen</th><th>mit Problemen</th></tr></thead>
<tbody>{export_zeilen}</tbody></table></div>
<h2>Pakete</h2>
<div style="overflow-x:auto"><table><thead><tr><th>Paket</th><th>Ziel in Anton</th><th>Dateien</th><th>Größe</th><th>Stand</th><th>übergeben</th><th>Kontrolle</th></tr></thead>
<tbody>{paket_zeilen or '<tr><td colspan=7 class=leise>Noch keine Pakete.</td></tr>'}</tbody></table></div>
</body></html>"""
        ordner = self.erfassung.projekt / "berichte"
        ordner.mkdir(exist_ok=True)
        pfad = ordner / f"Abschlussbericht_{jetzt:%Y-%m-%d_%H%M}.html"
        pfad.write_text(inhalt, encoding="utf-8")
        with self.b.sperre, self.b.schreibend() as con:
            con.execute("INSERT INTO protokoll VALUES (?,?,?,?,?,?)", (zeit(), "Export", "Abschlussbericht", "gespeichert", "", pfad.name))
        self.nachziehen()
        return {"ok": True, "datei": pfad.name, "pfad": str(pfad)}

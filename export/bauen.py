"""Pakete bauen (X1) und nachprüfen (X2): metadata.json gegen das Schema prüfen, BagIt-Pakete als tar auf die Ablage.

Was in ein Paket gehört, steht schon in paket und paket_eintrag (geplant vom Server, tool/pakete.py). Hier wird nur
noch zusammengesetzt, geprüft und geschrieben (Entscheidung „Pakete auf eine Ablage“, 05.11.2026):
- Die Quellplatte wird nur gelesen (harte Regel 1): Datei für Datei direkt ins tar auf der Ablage, ohne Zwischenkopie.
- Beim Lesen werden MD5 und SHA-256 berechnet und mit der Datenbank verglichen (D1). Weicht eine ab, stoppt das
  Paket; die Datei hat sich seit der Analyse verändert oder ist nicht lesbar.
- Das tar (PAX) ist ein BagIt-Bag 1.0: bagit.txt und bag-info.txt im Wurzelverzeichnis, Manifeste SHA-256 und MD5
  über alles unter data/, data/meta/metadata.json, die Dateien unter data/content/<Pfad auf der Platte>. Die
  Nutzdaten stehen vorn, Metadaten und Manifeste am Ende (im tar ist die Reihenfolge gleichgültig).
- Nach jeder Datei merkt sich Balduin die Stelle im tar (paket_eintrag.tar_ende, gesichert mit fsync); ein
  abgebrochener Bau macht nach der letzten gemerkten Datei weiter.
- Nachprüfen liest das fertige tar von der Ablage und vergleicht jede Datei mit dem Manifest und der Datenbank.
- Auf der Ablage liegt ein Lieferschein für Kränzle & Ritter: lieferung.csv, SHA256SUMS, LIESMICH.txt.
"""
import csv
import io
import tarfile

import jsonschema

from erfassung.basis import *  # noqa: F401,F403
from erfassung import anton
from erfassung import platte as platte_modul
from erfassung import quelle as quellen

SCHEMA_ORDNER = CODE / "vorgaben" / "anton_import"
STUECK = 8 * 1024 * 1024                      # so viel wird auf einmal gelesen
FERTIG = ("übergeben", "importiert", "unvollständig")    # diese Pakete werden nie neu gebaut
HOECHSTENS_EINTRAEGE = 100_000                # Grenze bei Anton (ARCHIVE_MAX_ENTRIES), solange K&R sie nicht erhöht
MERKEN_ALLE = 20                              # so viele Dateien bzw.
MERKEN_S = 15                                 # so viele Sekunden, dann die Stelle im tar sichern


def generator():
    """Erzeugendes Werkzeug wie im Schema verlangt: <paket>@<version>, Version 0.<Zahl der Commits> wie im Tool."""
    try:
        zahl = subprocess.run(["git", "-C", str(CODE), "rev-list", "--count", "HEAD"],
                              capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        zahl = ""
    return f"balduin@0.{zahl}" if zahl.isdigit() else "balduin@0"


def importformat():
    """Welche Version des Importformats die Instanz liest: {"reads": "0.6", …} (GET /api/import-format)."""
    try:
        return anton.anton_holen("/import-format", anton.anton_token() or None, versuche=1, timeout=30)
    except (urllib.error.URLError, TimeoutError, ValueError) as fehler:
        raise RuntimeError(f"{P.anton_url} antwortet nicht auf /api/import-format: {getattr(fehler, 'reason', fehler)}") from None


def formatrichtlinie():
    """Formatrichtlinie der Instanz (GET /api/format-policy/switches): bei „reject“ scheitert heute ein ganzes Paket an
    einer abgelehnten Datei (K&R, 05.11.2026, Frage 6). Antwort wie von Anton geliefert."""
    try:
        return anton.anton_holen("/format-policy/switches", anton.anton_token() or None, versuche=1, timeout=30)
    except (urllib.error.URLError, TimeoutError, ValueError) as fehler:
        raise RuntimeError(f"{P.anton_url} antwortet nicht auf /api/format-policy/switches: "
                           f"{getattr(fehler, 'reason', fehler)}") from None


def schema_version(hoechstens=None):
    """Höchste Version des Schemas in vorgaben/anton_import/, die nicht über `hoechstens` (reads der Instanz) liegt."""
    versionen = []
    for d in SCHEMA_ORDNER.glob("anton-import-*.schema.json"):
        m = re.fullmatch(r"anton-import-(\d+)\.(\d+)\.schema\.json", d.name)
        if m:
            versionen.append((int(m[1]), int(m[2])))
    if hoechstens:
        grenze = tuple(int(x) for x in str(hoechstens).split(".")[:2])
        versionen = [v for v in versionen if v <= grenze]
    if not versionen:
        raise RuntimeError(f"Kein passendes Schema in {SCHEMA_ORDNER}" + (f" (Instanz liest {hoechstens})" if hoechstens else ""))
    return "%d.%d" % max(versionen)


def pruefer(version):
    schema = json.loads((SCHEMA_ORDNER / f"anton-import-{version}.schema.json").read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema, format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER)


# Felder der Einträge, die erst eine Version des Importformats kennt: Eine Instanz, die älter liest, verwirft sie
# stillschweigend, darum schreibt Balduin sie nur ab dieser Version (die Einträge werden beim Planen vollständig gespeichert)
FELDER_AB_VERSION = {"actors": (0, 8)}             # Akteur:innen des Registers (anton#825)


def fuer_version(eintraege, version):
    """Einträge ohne die Felder, die `version` noch nicht kennt (neue Liste, die übergebenen bleiben unverändert)."""
    v = tuple(int(x) for x in str(version).split(".")[:2])
    weg = {f for f, ab in FELDER_AB_VERSION.items() if v < ab}
    return [{k: w for k, w in e.items() if k not in weg} for e in eintraege] if weg else list(eintraege)


def metadata(con, paket_id, version):
    eintraege = [json.loads(z[0]) for z in con.execute(
        "SELECT eintrag FROM paket_eintrag WHERE paket_id = ? AND eintrag IS NOT NULL ORDER BY nr", (paket_id,))]
    return {"version": version, "generator": generator(), "entries": fuer_version(eintraege, version)}


def fehler_in(md, validator, grenze=12):
    """Verstöße gegen das Schema und gegen die Regeln aus docs/anton_import.md (A5, A9) und der Antwort von K&R
    (05.11.2026: UUID nie doppelt, gleiche MD5 nur einmal, höchstens 100000 Einträge), lesbar, höchstens grenze."""
    fehler = []
    for f in sorted(validator.iter_errors(md), key=lambda f: list(f.absolute_path)):
        ort = "/".join(str(x) for x in f.absolute_path) or "(oben)"
        fehler.append(f"Schema: {ort}: {f.message[:200]}")
        if len(fehler) >= grenze:
            return fehler
    eintraege = md.get("entries", [])
    if len(eintraege) > HOECHSTENS_EINTRAEGE:
        fehler.append(f"{len(eintraege)} Einträge; Anton nimmt höchstens {HOECHSTENS_EINTRAEGE} je Paket")
    stelle = {}
    for i, e in enumerate(eintraege):
        stelle.setdefault(e.get("uuid"), i)
    gesehen, md5_gesehen = set(), {}
    for i, e in enumerate(eintraege):
        uuid = e.get("uuid")
        if uuid in gesehen:
            fehler.append(f"entries/{i}: UUID {uuid} doppelt")
        gesehen.add(uuid)
        # Eltern vor Kindern; eine UUID, die nicht im Paket steht, ist eine Ebene aus einem früheren Paket
        eltern = (e.get("parent") or {}).get("uuid")
        if eltern and stelle.get(eltern, -1) >= i:
            fehler.append(f"entries/{i}: steht vor seiner Einheit darüber (Anton bricht mit ParentNotFound ab)")
        if e.get("files") and e.get("type") != "record":
            fehler.append(f"entries/{i}: Dateien nur an einem record")
        for d in e.get("files") or []:
            p = d.get("file_path", "")
            if p.startswith("/") or ".." in p.split("/"):
                fehler.append(f"entries/{i}: file_path {p!r} nicht relativ zu data/content/")
            if d.get("md5sum") in md5_gesehen:
                fehler.append(f"entries/{i}: gleiche MD5 wie entries/{md5_gesehen[d['md5sum']]} (Dublette)")
            md5_gesehen.setdefault(d.get("md5sum"), i)
    erster = (eintraege or [{}])[0]
    if any((t or "").strip().lower() == "content" for t in (erster.get("title") or {}).values()):
        fehler.append("entries/0: Titel „Content“ verwirft Anton")
    return fehler[:grenze]


def pruefen(paket_ids=None, version=None):
    """Prüft die metadata.json geplanter Pakete gegen das Schema (ohne Platte). Fehler kommen in paket.fehler,
    das Paket gilt dann als „Fehler“, bis neu geplant wird. Antwort: {paket_id: [Fehler]}."""
    version = version or schema_version()
    validator = pruefer(version)
    ergebnis = {}
    with db() as con:
        ids = paket_ids or [z[0] for z in con.execute("SELECT paket_id FROM paket WHERE status IN ('geplant', 'Fehler')")]
        for pid in ids:
            fehler = fehler_in(metadata(con, pid, version), validator)
            ergebnis[pid] = fehler
            con.execute("UPDATE paket SET status = ?, fehler = ? WHERE paket_id = ? AND status IN ('geplant', 'Fehler')",
                        ("Fehler" if fehler else "geplant", "\n".join(fehler) or None, pid))
    return ergebnis


# ---------- Ablage, Platz, Sicherung ----------

def ablage():
    """Ordner der Pakete auf der Ablage (angelegt); Fehler, wenn keine gewählt oder ihr Datenträger fehlt."""
    if P.export is None:
        raise RuntimeError("Noch keine Ablage für die Pakete gewählt (Bestand und Export → Ablage und Pakete).")
    if not P.export_wurzel.is_dir():
        raise RuntimeError(f"Die Ablage {P.einstellungen['export']['ablage'].get('volume_name', '')} ist nicht angeschlossen.")
    P.export.mkdir(parents=True, exist_ok=True)
    return P.export


def export_platz_pruefen(bedarf_bytes):
    """Reicht der Platz auf der Ablage? Im Projekt (Mac) bleibt die Untergrenze min_frei_gb frei, auf einer Platte 1 GB."""
    frei = shutil.disk_usage(ablage()).free
    rest = P.min_frei_gb * 1e9 if P.export_wurzel == P.ordner else 1e9
    if frei - bedarf_bytes < rest:
        raise RuntimeError(f"Zu wenig Platz auf der Ablage {laufwerk_von(P.export)}: {menge(frei / 1e9)} frei, das Paket "
                           f"braucht {menge(bedarf_bytes / 1e9)}, frei bleiben müssen {menge(rest / 1e9)}.")


def datenbank_sichern(lauf_id=None, behalten=5):
    """Sicherung der inventar.sqlite vor dem Export (SQLite-Backup, auch im WAL-Modus vollständig); die letzten
    `behalten` bleiben in sicherungen/ im Projekt."""
    platz_pruefen(P.db_pfad.stat().st_size / 1e9)
    P.sicherungen.mkdir(exist_ok=True)
    ziel = P.sicherungen / f"inventar_{datetime.now():%Y%m%d_%H%M%S}" f"{f'_lauf{lauf_id}' if lauf_id else ''}.sqlite"
    with closing(sqlite3.connect(P.db_pfad, timeout=WARTEN_SPERRE)) as quelle, closing(sqlite3.connect(ziel)) as aus:
        quelle.backup(aus)
    for alt in sorted(P.sicherungen.glob("inventar_*.sqlite"))[:-behalten]:
        alt.unlink()
    print(f"✓ Datenbank gesichert: {ziel.name} ({menge(ziel.stat().st_size / 1e9)})")
    return ziel


# ---------- BagIt im tar ----------

def bag_pfad(pfad):
    """Pfad in einem BagIt-Manifest: CR, LF und % werden kodiert (BagIt 1.0, Abschnitt 2.1.3)."""
    return pfad.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def bag_pfad_lesen(pfad):
    return pfad.replace("%0A", "\n").replace("%0D", "\r").replace("%25", "%")


class Abweichung(Exception):
    """Eine Datei auf der Platte stimmt nicht mehr mit der Datenbank überein (oder fehlt)."""


class Schreiber:
    """Schreibt ins tar und rechnet dabei die SHA-256 des ganzen Pakets mit (für den Lieferschein)."""

    def __init__(self, datei, sha=None):
        self.datei, self.sha = datei, sha or hashlib.sha256()

    def write(self, daten):
        self.sha.update(daten)
        return self.datei.write(daten)

    def tell(self):
        return self.datei.tell()

    def sichern(self):
        self.datei.flush()
        os.fsync(self.datei.fileno())


class Leser:
    """Liest eine Datei von der Platte für das tar und rechnet MD5 und SHA-256 mit; meldet den Fortschritt."""

    def __init__(self, datei, melden):
        self.datei, self.melden = datei, melden
        self.md5, self.sha = hashlib.md5(), hashlib.sha256()

    def read(self, n=-1):
        stueck = self.datei.read(n if n and n > 0 else STUECK)
        self.md5.update(stueck)
        self.sha.update(stueck)
        self.melden(len(stueck))
        return stueck


def tag_dateien(name, generator_text, manifest_sha, manifest_md5, nutz_bytes, nutz_zahl):
    """bagit.txt, bag-info.txt, Manifeste und Tag-Manifest als {Name: Text}."""
    tags = {
        "bagit.txt": "BagIt-Version: 1.0\nTag-File-Character-Encoding: UTF-8\n",
        "bag-info.txt": (f"Bagging-Date: {datetime.now():%Y-%m-%d}\nBag-Software-Agent: {generator_text}\n"
                         f"External-Identifier: {name}\nPayload-Oxum: {nutz_bytes}.{nutz_zahl}\n"
                         f"Bag-Size: {menge(nutz_bytes / 1e9)}\n"),
        "manifest-sha256.txt": "".join(f"{s}  {bag_pfad(p)}\n" for p, s in manifest_sha),
        "manifest-md5.txt": "".join(f"{s}  {bag_pfad(p)}\n" for p, s in manifest_md5),
    }
    tags["tagmanifest-sha256.txt"] = "".join(f"{hashlib.sha256(t.encode()).hexdigest()}  {n}\n" for n, t in tags.items())
    return tags


def tar_schreiben(pfad, name, md, dateien, mountpunkt, text="", merken=None, platte_id=None):
    """Schreibt das BagIt-tar nach pfad, Datei für Datei von der Platte. dateien: [(nr, relpfad, groesse, md5, sha256,
    tar_ende)] in der Reihenfolge der Einträge; tar_ende gesetzt = schon geschrieben (Fortsetzen: pfad wird dort
    abgeschnitten). merken([(nr, tar_ende)]) sichert die Stellen (nach fsync). Antwort: (SHA-256, Bytes des tar)."""
    pfad = Path(pfad)
    weiter_ab, erledigt = 0, 0                       # Stelle nach der letzten sicher geschriebenen Datei
    for nr, _, _, _, _, ende in dateien:
        if ende is None:
            break
        weiter_ab, erledigt = ende, erledigt + 1
    if weiter_ab and (not pfad.is_file() or pfad.stat().st_size < weiter_ab):
        weiter_ab, erledigt = 0, 0                   # Teildatei fehlt oder ist kürzer: von vorn
    sha_tar = hashlib.sha256()
    if weiter_ab:
        with open(pfad, "r+b") as f:
            f.truncate(weiter_ab)
            rest = weiter_ab
            while rest:                              # Prüfsumme des Pakets über den schon geschriebenen Teil
                stueck = f.read(min(STUECK, rest))
                sha_tar.update(stueck)
                rest -= len(stueck)
        print(f"{name}: setze nach {erledigt} von {len(dateien)} Dateien fort.")
    manifest_sha, manifest_md5, nutz_bytes = [], [], 0
    gesamt = sum(d[2] for d in dateien[erledigt:]) or 1
    gelesen = [0]

    def melden(n):
        gelesen[0] += n
        fortschritt(gelesen[0] / gesamt, f"{text or name} · {menge(gelesen[0] / 1e9)} von {menge(gesamt / 1e9)}")

    for _, relpfad, groesse, md5_db, sha_db, _ in dateien[:erledigt]:   # schon geschrieben und damals geprüft
        manifest_sha.append((f"data/content/{relpfad}", sha_db))
        manifest_md5.append((f"data/content/{relpfad}", md5_db))
        nutz_bytes += groesse
    with open(pfad, "r+b" if weiter_ab else "wb") as roh:
        roh.seek(weiter_ab)
        aus = Schreiber(roh, sha_tar)
        tar = tarfile.open(fileobj=aus, mode="w", format=tarfile.PAX_FORMAT, encoding="utf-8")
        tar.copybufsize = STUECK
        offen, zuletzt = [], time.monotonic()

        def sichern():
            nonlocal offen, zuletzt
            if offen and merken:
                aus.sichern()
                merken(offen)
            offen, zuletzt = [], time.monotonic()
        # Abbild oder Mac-Platte: nur über die Leseschicht, nie als Pfad befragen (unter Windows antwortet
        # \\.\PhysicalDriveN\… auf is_file() mit Fehler 87 statt „nein“; Windows-VM 13.11.2026)
        leseschicht = quellen.ist_abbild(mountpunkt)
        try:
            for nr, relpfad, groesse, md5_db, sha_db, _ in dateien[erledigt:]:
                quelle = None if leseschicht else quellpfad(mountpunkt, relpfad)
                info = tarfile.TarInfo(f"data/content/{relpfad}")
                if quelle is not None and quelle.is_file():
                    st = quelle.stat()
                    if st.st_size != groesse:
                        raise Abweichung(f"{relpfad}: Größe {st.st_size} statt {groesse} wie bei der Analyse (Datei verändert?)")
                    info.size, info.mtime, info.mode = groesse, int(st.st_mtime), 0o644
                    with open(quelle, "rb") as f:
                        leser = Leser(f, melden)
                        tar.addfile(info, leser)
                else:
                    # Datei in einer Archivdatei (Entscheidung 06.11.2026) oder in einem Abbild (09.11.2026): direkt
                    # aus dem Archiv bzw. über die Leseschicht lesen
                    zeit = None
                    if quellen.ist_abbild(mountpunkt) and quellen.ist_datei(mountpunkt, relpfad):
                        ist, zeit = quellen.stat(mountpunkt, relpfad)
                        if ist != groesse:
                            raise Abweichung(f"{relpfad}: Größe {ist} statt {groesse} wie bei der Analyse (Datei verändert?)")
                    try:
                        f = platte_modul.oeffne(mountpunkt, relpfad)
                    except OSError:
                        raise Abweichung(f"{relpfad}: nicht mehr auf dem Datenträger") from None
                    info.size, info.mode = groesse, 0o644
                    info.mtime = int(zeit) if zeit else archivzeit(platte_id, relpfad)
                    with f:
                        leser = Leser(f, melden)
                        try:
                            tar.addfile(info, leser)
                        except OSError as e:
                            if "unexpected end of data" not in str(e):
                                raise
                            raise Abweichung(f"{relpfad}: im Archiv kürzer als bei der Analyse (Datei verändert?)") from None
                if leser.md5.hexdigest() != md5_db or (sha_db and leser.sha.hexdigest() != sha_db):
                    raise Abweichung(f"{relpfad}: Prüfsumme weicht von der Analyse ab (Datei verändert?)")
                manifest_sha.append((info.name, leser.sha.hexdigest()))
                manifest_md5.append((info.name, md5_db))
                nutz_bytes += groesse
                offen.append((nr, tar.offset))
                if len(offen) >= MERKEN_ALLE or time.monotonic() - zuletzt > MERKEN_S:
                    sichern()
        except KeyboardInterrupt:                     # abgebrochen: Geschriebenes merken, beim nächsten Lauf weiter
            sichern()
            raise
        except OSError:                               # z. B. Ablage oder Platte abgezogen
            try:
                sichern()
            except OSError:
                pass
            raise
        inhalt = (json.dumps(md, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
        manifest_sha.append(("data/meta/metadata.json", hashlib.sha256(inhalt).hexdigest()))
        manifest_md5.append(("data/meta/metadata.json", hashlib.md5(inhalt).hexdigest()))
        tags = tag_dateien(name, md["generator"], manifest_sha, manifest_md5, nutz_bytes + len(inhalt), len(manifest_sha))
        for n, daten in [("data/meta/metadata.json", inhalt)] + [(n, t.encode("utf-8")) for n, t in tags.items()]:
            info = tarfile.TarInfo(n)
            info.size, info.mtime, info.mode = len(daten), int(time.time()), 0o644
            tar.addfile(info, io.BytesIO(daten))
        tar.close()                                   # Ende des Archivs (zwei leere Blöcke, aufgefüllt)
        aus.sichern()
        groesse_tar = roh.tell()
        roh.truncate(groesse_tar)
    return sha_tar.hexdigest(), groesse_tar


def archivzeit(platte_id, relpfad):
    """Änderungsdatum einer Datei in einer Archivdatei, wie C es aus dem Archiv gelesen hat (sonst jetzt)."""
    if platte_id:
        with db() as con:
            z = con.execute("SELECT mtime FROM schnellscan WHERE platte_id = ? AND relpfad = ?", (platte_id, relpfad)).fetchone()
        if z and z[0]:
            return int(z[0])
    return int(time.time())


def bag_pruefen(pfad, erwartet=None):
    """Liest ein BagIt-tar ganz und prüft: bagit.txt (1.0), jede Datei unter data/ gegen beide Manifeste, keine Datei
    zu viel oder zu wenig, Payload-Oxum, Tag-Manifest; erwartet {Pfad unter data/content: (md5, sha256)} aus der
    Datenbank. Antwort: (Fehler, Zahl der Nutzdateien, Bytes der Nutzdaten)."""
    nutz, tags, fehler = {}, {}, []
    gesamt, gelesen = Path(pfad).stat().st_size or 1, 0
    with tarfile.open(pfad, "r:", encoding="utf-8") as tar:
        for m in tar:
            if not m.isfile():
                continue
            f = tar.extractfile(m)
            if m.name.startswith("data/"):
                md5, sha = hashlib.md5(), hashlib.sha256()
                while stueck := f.read(STUECK):
                    md5.update(stueck)
                    sha.update(stueck)
                    gelesen += len(stueck)
                    fortschritt(gelesen / gesamt, f"{Path(pfad).name} nachprüfen · {menge(gelesen / 1e9)} von {menge(gesamt / 1e9)}")
                if m.name in nutz:
                    fehler.append(f"{m.name}: zweimal im Paket")
                nutz[m.name] = (md5.hexdigest(), sha.hexdigest(), m.size)
            elif "/" not in m.name:
                tags[m.name] = f.read().decode("utf-8")
            else:
                fehler.append(f"{m.name}: gehört nicht in ein BagIt-Paket")

    def manifest(name):
        eintraege = {}
        for zeile in tags.get(name, "").splitlines():
            if zeile.strip():
                summe, _, p = zeile.partition("  ")
                eintraege[bag_pfad_lesen(p)] = summe
        return eintraege
    if not tags.get("bagit.txt", "").startswith("BagIt-Version: 1.0"):
        fehler.append("bagit.txt fehlt oder ist nicht BagIt 1.0")
    for name, stelle in (("manifest-sha256.txt", 1), ("manifest-md5.txt", 0)):
        if name not in tags:
            fehler.append(f"{name} fehlt")
            continue
        m = manifest(name)
        for p, summe in m.items():
            if p not in nutz:
                fehler.append(f"{p}: steht in {name}, fehlt im Paket")
            elif nutz[p][stelle] != summe:
                fehler.append(f"{p}: Prüfsumme weicht von {name} ab")
        fehler += [f"{p}: im Paket, aber nicht in {name}" for p in nutz if p not in m]
    for n, summe in manifest("tagmanifest-sha256.txt").items():
        if hashlib.sha256(tags.get(n, "").encode("utf-8")).hexdigest() != summe:
            fehler.append(f"{n}: weicht vom Tag-Manifest ab")
    oxum = re.search(r"Payload-Oxum: (\d+)\.(\d+)", tags.get("bag-info.txt", ""))
    nutz_bytes = sum(x[2] for x in nutz.values())
    if not oxum or (int(oxum[1]), int(oxum[2])) != (nutz_bytes, len(nutz)):
        fehler.append("Payload-Oxum in bag-info.txt stimmt nicht")
    if "data/meta/metadata.json" not in nutz:
        fehler.append("data/meta/metadata.json fehlt")
    for p, (md5, sha) in (erwartet or {}).items():
        x = nutz.get(f"data/content/{p}")
        if x is None:
            fehler.append(f"{p}: fehlt im Paket")
        elif x[0] != md5 or (sha and x[1] != sha):
            fehler.append(f"{p}: Prüfsumme weicht von der Analyse ab")
    return fehler, len(nutz), nutz_bytes


# ---------- je Paket ----------

def paket_lesen(con, paket_id):
    con.row_factory = sqlite3.Row
    z = con.execute("SELECT * FROM paket WHERE paket_id = ?", (paket_id,)).fetchone()
    if z is None:
        raise ValueError(f"Paket {paket_id} unbekannt")
    return dict(z)


def setzen(paket_id, alt, **werte):
    with db() as con:
        con.execute(f"UPDATE paket SET {', '.join(k + ' = ?' for k in werte)} WHERE paket_id = ?", (*werte.values(), paket_id))
    if "status" in werte and werte["status"] != alt:
        protokolliere("Export", f"Paket {paket_id}", "status", alt, werte["status"]
                      + (f": {werte['fehler']}" if werte.get("fehler") else ""))


def paket_bauen(paket_id, mountpunkt=None, version=None):
    """Baut ein geplantes Paket auf die Ablage (oder setzt einen abgebrochenen Bau fort); Ebenenpakete brauchen keine
    Platte. Antwort: Pfad des tar. Fehler kommen in paket."""
    version = version or schema_version()
    with db() as con:
        p = paket_lesen(con, paket_id)
        md = metadata(con, paket_id, version)
        dateien = [tuple(z) for z in con.execute(
            "SELECT nr, relpfad, groesse, md5, sha256, tar_ende FROM paket_eintrag WHERE paket_id = ? "
            "AND relpfad IS NOT NULL ORDER BY nr", (paket_id,))]
    if p["status"] in FERTIG or p["status"] == "gebaut":
        raise ValueError(f"{p['name']} ist schon gebaut.")
    fehler = fehler_in(md, pruefer(version))
    if fehler:
        setzen(paket_id, p["status"], status="Fehler", fehler="\n".join(fehler))
        raise ValueError(f"{p['name']}: metadata.json passt nicht zum Schema: {fehler[0]}")
    if dateien and not mountpunkt:
        raise ValueError(f"{p['name']} braucht den Datenträger {p['platte_id']}.")
    ordner = ablage()
    ziel = ordner / p["name"]
    teil = ziel.with_name(ziel.name + ".teil")
    schon = next((d[5] for d in reversed(dateien) if d[5] is not None), 0) if teil.is_file() else 0
    export_platz_pruefen((p["bytes"] or 0) - schon + len(md["entries"]) * 2048 + 10 ** 6)
    print(f"{p['name']}: {len(md['entries'])} Einträge, {len(dateien)} Dateien, {menge((p['bytes'] or 0) / 1e9)} → {ordner}")

    def merken(liste):
        with db() as con:
            con.executemany("UPDATE paket_eintrag SET tar_ende = ? WHERE paket_id = ? AND nr = ?",
                            [(ende, paket_id, nr) for nr, ende in liste])

    try:
        sha, groesse = tar_schreiben(teil, p["name"], md, dateien, mountpunkt, p["name"], merken, p["platte_id"])
    except Abweichung as fehler:                      # stoppt das Paket: neu planen, nachdem die Ursache geklärt ist
        teil.unlink(missing_ok=True)
        with db() as con:
            con.execute("UPDATE paket_eintrag SET tar_ende = NULL WHERE paket_id = ?", (paket_id,))
        setzen(paket_id, p["status"], status="Fehler", fehler=str(fehler))
        raise
    os.replace(teil, ziel)
    setzen(paket_id, p["status"], status="gebaut", fehler=None, gebaut_am=jetzt(), geprueft_am=None, datei=ziel.name,
           datei_bytes=groesse, datei_sha256=sha)
    print(f"✓ {p['name']} geschrieben ({menge(groesse / 1e9)}), Prüfsummen stimmen mit der Analyse überein.")
    return ziel


def paket_nachpruefen(paket_id):
    """Liest das gebaute tar von der Ablage und prüft es (bag_pruefen, gegen die Datenbank). Antwort: Fehler."""
    with db() as con:
        p = paket_lesen(con, paket_id)
        erwartet = {z[0]: (z[1], z[2]) for z in con.execute(
            "SELECT relpfad, md5, sha256 FROM paket_eintrag WHERE paket_id = ? AND relpfad IS NOT NULL", (paket_id,))}
    pfad = ablage() / (p["datei"] or "")
    if not p["datei"] or not pfad.is_file():
        setzen(paket_id, p["status"], status="geplant", datei=None, fehler="Paketdatei fehlt auf der Ablage; neu bauen.")
        with db() as con:
            con.execute("UPDATE paket_eintrag SET tar_ende = NULL WHERE paket_id = ?", (paket_id,))
        return ["Paketdatei fehlt auf der Ablage"]
    fehler, zahl, _ = bag_pruefen(pfad, erwartet)
    sha = hashlib.sha256()
    with open(pfad, "rb") as f:                       # dieselbe Datei wie geschrieben (Lieferschein)?
        while stueck := f.read(STUECK):
            sha.update(stueck)
    if sha.hexdigest() != p["datei_sha256"]:
        fehler.append("Prüfsumme des Pakets weicht vom Schreiben ab")
    if fehler:
        pfad.unlink()
        with db() as con:
            con.execute("UPDATE paket_eintrag SET tar_ende = NULL WHERE paket_id = ?", (paket_id,))
        setzen(paket_id, p["status"], status="Fehler", datei=None, fehler="Nachprüfen: " + "; ".join(fehler[:5]))
        print(f"✗ {p['name']}: {fehler[0]}")
    else:
        setzen(paket_id, p["status"], geprueft_am=jetzt())
        print(f"✓ {p['name']} nachgeprüft: {zahl} Dateien stimmen mit Manifest und Analyse überein.")
    return fehler


def aufrufe(pakete):
    """Import auf dem Server (anton#818) je Paket in Reihenfolge: erst Trockenlauf, dann Import. sip:import-file liest
    das Ziel nicht aus dem Dateinamen, darum --parent aus <x>-agate-<ID>.tar (Entscheidung 14.11.2026, Weg C)."""
    zeilen = ["Import auf dem Server (<Ordner> = Ort der Pakete, <Mandant> und <Konto> ersetzen), Paket für Paket:",
              "erst prüfen, dann importieren; Exit-Code 2 = einzelne Dateien nicht angehängt (Bericht des Laufs),",
              "1 = abgebrochen (fortsetzen mit --resume=<Lauf>).", ""]
    for i, p in enumerate(pakete, 1):
        befehl = f"php artisan sip:import-file --env=<Mandant> <Ordner>/{p['datei']} --parent={p['ziel']}"
        zeilen += [f"# {i}. {p['datei']}", f"{befehl} --dry-run", f"{befehl} --user=<Konto>", ""]
    return "\n".join(zeilen)


def lieferschein():
    """Lieferschein auf der Ablage: lieferung.csv (Reihenfolge des Imports), SHA256SUMS, LIESMICH.txt."""
    ordner = ablage()
    with db() as con:
        con.row_factory = sqlite3.Row
        pakete = [dict(z) for z in con.execute(
            "SELECT p.*, b.signatur, b.titel AS ziel_titel FROM paket p LEFT JOIN bestandsbox b ON b.anton_id = p.ziel "
            "WHERE p.datei IS NOT NULL AND p.datei_geloescht_am IS NULL ORDER BY p.paket_id")]
    namen = {p["paket_id"]: p["name"] for p in pakete}
    puffer = io.StringIO()
    w = csv.writer(puffer)
    w.writerow(["reihenfolge", "paket", "ziel_id", "ziel_signatur", "ziel_titel", "eintraege", "dateien", "bytes",
                "sha256", "nach", "status", "nachgeprueft"])
    for i, p in enumerate(pakete, 1):
        w.writerow([i, p["datei"], p["ziel"], p["signatur"] or "", p["ziel_titel"] or "", p["eintraege"], p["dateien"],
                    p["datei_bytes"], p["datei_sha256"],
                    " ".join(namen.get(b, str(b)) for b in json.loads(p["braucht"] or "[]")), p["status"], p["geprueft_am"] or ""])
    (ordner / "lieferung.csv").write_text(puffer.getvalue(), encoding="utf-8")
    (ordner / "SHA256SUMS").write_text("".join(f"{p['datei_sha256']}  {p['datei']}\n" for p in pakete), encoding="utf-8")
    (ordner / "LIESMICH.txt").write_text(
        f"Lieferung von Balduin an Anton ({P.name}, Stand {datetime.now():%d.%m.%Y %H:%M})\n\n"
        f"{len(pakete)} Pakete im Anton-Importformat (BagIt 1.0 als tar, metadata.json nach dem Schema geprüft),\n"
        f"zusammen {menge(sum(p['datei_bytes'] or 0 for p in pakete) / 1e9)}.\n\n"
        "Bitte in der Reihenfolge von lieferung.csv importieren: Pakete mit einem Eintrag unter „nach“ bauen auf den\n"
        "Ebenen dieser Pakete auf (parent.uuid). Das Ziel steht im Dateinamen (<x>-agate-<Anton-ID>.tar).\n"
        "Prüfsummen der Pakete: SHA256SUMS (shasum -a 256 -c SHA256SUMS).\n\n" + aufrufe(pakete), encoding="utf-8")
    return ordner


def zu_bauen(platte_id=None):
    """Pakete, die als Nächstes zu bauen sind: Ebenenpakete und (mit Platte) die Teile dieser Platte, in Planfolge."""
    with db() as con:
        return [z[0] for z in con.execute(
            "SELECT paket_id FROM paket WHERE status IN ('geplant', 'Fehler') AND (art = 'ebenen' OR platte_id = ?) "
            "ORDER BY paket_id", (platte_id or "",))]


def zu_pruefen():
    with db() as con:
        return [z[0] for z in con.execute("SELECT paket_id FROM paket WHERE status = 'gebaut' AND geprueft_am IS NULL "
                                          "ORDER BY paket_id")]


def platte_pruefen(platte_id, mountpunkt, beschreibbar_ok=False):
    """Richtige Platte, schreibgeschützt eingehängt oder ohne Schreibschutz nach Zustimmung (beschreibbar_ok,
    Entscheidung 13.11.2026; Balduin schreibt dort trotzdem nie), und nicht zugleich die Ablage."""
    platte_modul.angeschlossene_platte_pruefen(platte_id, Path(mountpunkt))
    if platte_modul.art_der_quelle(platte_id) == "macplatte":
        return                                            # nur lesend über die Leseschicht, nie eine Ablage
    if platte_modul.art_der_quelle(platte_id) == "abbild":
        # Abbild (Entscheidung 09.11.2026): nur lesend geöffnet, aber nie in oder über der Ablage
        try:
            platte_modul.nicht_in_arbeitsorten(Path(mountpunkt).resolve())
        except ValueError as e:
            raise RuntimeError(f"{platte_id} kann so nicht gepackt werden: {e}") from None
        return
    if platte_modul.ist_ordner(platte_id):
        # Ordner als Quelle (Entscheidung 05.11.2026): nicht schreibgeschützt einhängbar, aber nie in oder über der Ablage
        try:
            platte_modul.quellordner_pruefen(mountpunkt, platte_id)
        except ValueError as e:
            raise RuntimeError(f"{platte_id} kann so nicht gepackt werden: {e}") from None
        return
    if not platte_modul.bereit(Path(mountpunkt)):
        # ohne Schreibschutz nur nach Zustimmung (Entscheidung 13.11.2026; unter Windows geht es nicht anders)
        if not beschreibbar_ok:
            raise RuntimeError("Der Datenträger ist beschreibbar eingehängt. Erst unter Registrierung/Analyse "
                               "„Schreibgeschützt einhängen“ wählen oder dem Lesen ohne Schreibschutz zustimmen.")
        platte_modul.ohne_schreibschutz_gelesen(platte_id)
    if P.export_wurzel is not None and Path(mountpunkt).resolve() == Path(P.export_wurzel).resolve():
        raise RuntimeError("Die Quellplatte ist zugleich als Ablage gewählt; dort schreibt Balduin nie.")

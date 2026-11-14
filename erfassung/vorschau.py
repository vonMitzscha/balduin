"""F Vorschaubilder (eines je Inhalt, im Projekt oder auf der Arbeitsplatte) und pHash für G3."""
import base64
import io

from PIL import Image, ImageOps

from .basis import *  # noqa: F401,F403
from . import archivdateien
from .platte import ist_schreibgeschuetzt, platteninfo

# EINSTELLUNG F1 (Vorgaben)
VORSCHAU_PX = 400            # längste Seite in Pixeln
JPEG_QUALITAET = 80
FILM_BILDDAUER_MS = 700      # animiertes WebP (Filme, PDFs): so lange steht jedes Bild (Art und Anzahl: projekt.json)
WEBP_QUALITAET = 70


# F2 Arbeitsplatte prüfen und Vorschau-Ordner einbinden
def arbeitsplatte_einbinden(mountpunkt=None):
    """F2 Ordner für die Vorschaubilder bereitstellen: im Projekt (vorschauen/) oder auf der Arbeitsplatte aus
    projekt.json; diese wird geprüft (angeschlossen, beschreibbar, keine Quellplatte). mountpunkt: angeschlossene Quellplatte."""
    if P.arbeitsplatte is None:
        P.vorschauen.mkdir(parents=True, exist_ok=True)
        print(f"✓ Vorschaubilder im Projekt: {P.vorschauen.relative_to(P.ordner)}/")
        return
    if not P.arbeitsplatte.exists():
        raise FileNotFoundError(f"Der Datenträger für Vorschaubilder {P.arbeitsplatte} ist nicht angeschlossen.")
    if ist_schreibgeschuetzt(P.arbeitsplatte):
        raise PermissionError(f"{P.arbeitsplatte} ist schreibgeschützt. Der Datenträger für Vorschaubilder muss beschreibbar sein (exFAT oder APFS).")
    # Sicherheitsnetz: Die Arbeitsplatte darf keine Quellplatte sein
    info = platteninfo(P.arbeitsplatte)
    with db() as con:
        quellen = {u for (u,) in con.execute("SELECT volume_uuid FROM platte WHERE volume_uuid != ''")}
    if info["volume_uuid"] in quellen or (mountpunkt and P.arbeitsplatte.resolve() == Path(mountpunkt).resolve()):
        raise ValueError(f"{P.arbeitsplatte} ist als Quelle registriert. Dort wird nicht geschrieben.")
    P.vorschauen.mkdir(parents=True, exist_ok=True)
    frei = shutil.disk_usage(P.arbeitsplatte).free / 1e9
    print(f"✓ Datenträger für Vorschaubilder {info['volume_name']} ({info['dateisystem']}), {frei:,.0f} GB frei.")
    print(f"  Vorschaubilder: {P.vorschauen}")


# F3a Funktionen: Vorschaubilder erzeugen
Image.MAX_IMAGE_PIXELS = 600_000_000      # große Scans erlauben (Pillow warnt sonst ab 89 Megapixeln)

BILD_ENDUNGEN = {"jpg", "jpeg", "jpe", "png", "gif", "tif", "tiff", "bmp", "psd", "pcx", "webp", "jp2", "pct", "pict"}
RAW_ENDUNGEN = {"nef", "cr2", "crw", "cr3", "dng", "orf", "arw", "srf", "raf", "rw2", "pef", "srw", "x3f", "mrw", "dcr", "kdc"}
VIDEO_ENDUNGEN = {"mov", "mp4", "m4v", "avi", "mpg", "mpeg", "wmv", "mts", "m2ts", "3gp", "flv", "mkv", "vob", "dv"}
DOKUMENT_ENDUNGEN = {"pdf", "eps", "ai", "ps", "doc", "docx", "rtf", "xls", "xlsx", "ppt", "pptx", "odt", "ods", "odp",
                     "pages", "key", "numbers", "qxd", "qxp", "indd", "fh9", "cdr", "wmf", "emf"}
QL_AUSSETZER = 3       # hängt Quick Look bei einem Format so oft hintereinander, wird es dafür übersprungen
DREHUNG = {3: Image.Transpose.ROTATE_180, 6: Image.Transpose.ROTATE_270, 8: Image.Transpose.ROTATE_90}

# Matrix für die diskrete Kosinustransformation (DCT) 32 × 32, Grundlage des pHash
_k = np.arange(32)
DCT = np.sqrt(2 / 32) * np.cos(np.pi * (2 * _k[None, :] + 1) * _k[:, None] / 64)
DCT[0] /= np.sqrt(2)


def vorschau_art(relpfad, mime, format_name=None):
    endung = Path(relpfad).suffix.lower().lstrip(".")
    mime, format_name = mime or "", format_name or ""
    # Quick Look kann PostScript seit macOS 14 nicht mehr darstellen und wartet bis zum Timeout
    if "Illustrator" in format_name or endung == "ai":
        return "illustrator"
    if "PostScript" in format_name or endung in ("eps", "ps"):
        return "postscript"
    if endung in RAW_ENDUNGEN:
        return "raw"
    if endung in VIDEO_ENDUNGEN or mime.startswith("video/"):
        return "video"
    if endung in DOKUMENT_ENDUNGEN or mime in ("application/pdf", "application/postscript"):
        return "dokument"
    if endung in BILD_ENDUNGEN or mime.startswith("image/"):
        return "bild"
    return None


def verkleinern(bild):
    """Bringt ein Bild in RGB (Transparenz auf Weiß, 16 Bit auf 8 Bit) und verkleinert es."""
    if bild.mode in ("I", "I;16", "I;16B", "I;16L", "F"):
        werte = np.asarray(bild, dtype=np.float64)
        bild = Image.fromarray((werte / max(werte.max(), 1) * 255).astype(np.uint8))
    if bild.mode in ("RGBA", "LA", "PA") or (bild.mode == "P" and "transparency" in bild.info):
        bild = bild.convert("RGBA")
        grund = Image.new("RGB", bild.size, "white")
        grund.paste(bild, mask=bild.getchannel("A"))
        bild = grund
    bild = bild.convert("RGB")
    bild.thumbnail((VORSCHAU_PX, VORSCHAU_PX), Image.Resampling.LANCZOS)
    return bild


def mit_pillow(pfad):
    with Image.open(pfad) as bild:
        groesse = bild.size
        bild.draft("RGB", (VORSCHAU_PX, VORSCHAU_PX))     # JPEG: gleich verkleinert dekodieren, spart Zeit
        bild.load()
        return verkleinern(ImageOps.exif_transpose(bild)), groesse


def eingebettet(pfad):
    """Vorschau, die in der Datei steckt (RAW, Photoshop, EPS, InDesign …), über ExifTool. Die größte gewinnt."""
    r = subprocess.run([system.werkzeug("exiftool"), "-json", "-b", "-n", "-JpgFromRaw", "-PreviewImage", "-ThumbnailImage",
                        "-PhotoshopThumbnail", "-TIFFPreview", "-Orientation", str(pfad)],
                       capture_output=True, timeout=120)
    angaben = json.loads(r.stdout or b"[{}]")[0]
    daten = [base64.b64decode(v[7:]) for v in angaben.values() if isinstance(v, str) and v.startswith("base64:")]
    if not daten:
        raise RuntimeError("keine eingebettete Vorschau")
    with Image.open(io.BytesIO(max(daten, key=len))) as bild:
        bild.load()
        if angaben.get("Orientation") in DREHUNG:
            bild = bild.transpose(DREHUNG[angaben["Orientation"]])
        return verkleinern(bild), None


def quicklook(pfad):
    """Vorschau des Systems (macOS: Quick Look, wie die Leertaste im Finder; erfassung/system.py). Das Bild entsteht
    in einem temporären Ordner auf dem Rechner."""
    with tempfile.TemporaryDirectory() as tmp:
        png = system.schnellvorschau(pfad, VORSCHAU_PX, tmp)
        if png is not None:
            with Image.open(png) as bild:
                bild.load()
                return verkleinern(bild), None
    raise RuntimeError("Die Systemvorschau liefert kein Bild" if system.mac() else "keine Vorschau des Systems")


def filmbilder(pfad, anzahl, kante):
    """Standbilder aus einem Film, gleichmäßig über die Dauer (bei 1/2n, 3/2n … der Dauer), gleich verkleinert auf
    höchstens kante Pixel; dazu die Originalgröße."""
    r = subprocess.run([system.werkzeug("ffprobe"), "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(pfad)],
                       capture_output=True, text=True, timeout=60)
    dauer = float(r.stdout.strip() or 0) if r.stdout.strip().replace(".", "", 1).isdigit() else 0
    bilder, groesse = [], None
    for k in range(anzahl):
        r = subprocess.run([system.werkzeug("ffmpeg"), "-v", "error", "-ss", f"{dauer * (2 * k + 1) / (2 * anzahl):.2f}", "-i", str(pfad),
                            "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, timeout=120)
        if r.stdout:
            b = Image.open(io.BytesIO(r.stdout)).convert("RGB")
            groesse = groesse or b.size
            b.thumbnail((kante, kante), Image.Resampling.LANCZOS)
            bilder.append(b)
    if not bilder:
        raise RuntimeError("ffmpeg: " + r.stderr.decode(errors="replace").strip()[:200])
    return bilder, groesse


def bildfolge(pfad):
    """Filmvorschau als animiertes WebP: so viele Bilder, wie projekt.json nennt (Vorgabe 10). Gibt eine Liste zurück;
    vorschauen_erzeugen speichert sie als Animation."""
    return filmbilder(pfad, P.film_bilder, VORSCHAU_PX)


def standbilder(pfad, anzahl=4):
    """Vier Standbilder aus einem Film (bei 1/8, 3/8, 5/8, 7/8 der Dauer) als 2 × 2-Raster."""
    bilder, groesse = filmbilder(pfad, anzahl, VORSCHAU_PX // 2)
    w, h = bilder[0].size
    raster = Image.new("RGB", (2 * w, h * ((len(bilder) + 1) // 2)), "black")
    for k, b in enumerate(bilder):
        raster.paste(b, ((k % 2) * w, (k // 2) * h))
    return raster, groesse


def ist_pdf(relpfad, mime=None):
    return Path(relpfad).suffix.lower() == ".pdf" or mime == "application/pdf"


def pdfseiten(pfad):
    """Mehrseitige PDF-Vorschau als animiertes WebP: Seite 1 und dann gleichmäßig verteilt, so viele Seiten, wie
    projekt.json nennt (Vorgabe 10), oder ein fester Seitenbereich (pdf.art „bereich“, z. B. 1–5), gerendert mit
    pdftoppm (Poppler). Bleibt nur eine Seite, ein einzelnes Bild."""
    r = subprocess.run([system.werkzeug("pdfinfo"), str(pfad)], capture_output=True, text=True, timeout=60)
    treffer = re.search(r"^Pages:\s+(\d+)", r.stdout, re.M)
    if not treffer:
        raise RuntimeError("pdfinfo: " + (" ".join(r.stderr.split())[:200] or "keine Seitenzahl"))
    gesamt, anzahl = int(treffer.group(1)), P.pdf_seiten
    if P.pdf_art == "bereich":                         # fester Bereich; reicht das PDF nicht so weit, bis zur letzten Seite
        von, bis = P.pdf_bereich
        seiten = range(min(von, gesamt), min(bis, gesamt) + 1)
    else:
        seiten = (range(1, gesamt + 1) if gesamt <= anzahl
                  else sorted({1 + round(k * (gesamt - 1) / (anzahl - 1)) for k in range(anzahl)}))
    bilder = seiten_rendern(pfad, seiten)
    return (bilder if len(bilder) > 1 else bilder[0]), None


def seiten_rendern(pfad, seiten):
    """Seiten eines PDF als Bilder (höchstens VORSCHAU_PX) über pdftoppm (Poppler); RuntimeError, wenn keine gelingt."""
    bilder = []
    for seite in seiten:
        r = subprocess.run([system.werkzeug("pdftoppm"), "-f", str(seite), "-l", str(seite), "-singlefile", "-png",
                            "-scale-to", str(VORSCHAU_PX), str(pfad)], capture_output=True, timeout=120)
        if r.stdout:
            bilder.append(verkleinern(Image.open(io.BytesIO(r.stdout))))
    if not bilder:
        raise RuntimeError("pdftoppm: " + " ".join(r.stderr.decode(errors="replace").split())[:200])
    return bilder


def pdf_erste_seite(pfad):
    """Erste Seite eines PDF über Poppler, auf allen Systemen gleich (Entscheidung 12.11.2026; bisher Quick Look, das
    es unter Windows nicht gibt)."""
    return seiten_rendern(pfad, [1])[0], None


# Eingebettete Vorschau in Office-Dateien (ZIP): OOXML, ODF, iWork; nur JPEG und PNG (EMF/WMF liest Pillow nicht überall)
OFFICE_VORSCHAU = ["docProps/thumbnail.jpeg", "docProps/thumbnail.jpg", "docProps/thumbnail.png",
                   "Thumbnails/thumbnail.png", "preview.jpg", "QuickLook/Thumbnail.jpg", "preview-web.jpg",
                   "QuickLook/Preview.jpg"]


def office_vorschau(pfad):
    """Vorschau, die Office-Programme in die Datei legen (Word/Excel/PowerPoint ab 2007, LibreOffice, Pages/Keynote/
    Numbers); ohne Werkzeug, auf allen Systemen gleich (Entscheidung 12.11.2026)."""
    import zipfile
    try:
        with zipfile.ZipFile(pfad) as z:
            namen = {n.lower(): n for n in z.namelist()}
            for gesucht in OFFICE_VORSCHAU:
                if gesucht.lower() in namen:
                    with Image.open(io.BytesIO(z.read(namen[gesucht.lower()]))) as bild:
                        bild.load()
                        return verkleinern(bild), None
    except (zipfile.BadZipFile, OSError) as e:
        raise RuntimeError(f"keine eingebettete Office-Vorschau ({type(e).__name__})") from None
    raise RuntimeError("keine eingebettete Office-Vorschau")


def libreoffice(pfad):
    """Erste Seite über LibreOffice (ohne Fenster in ein PDF umgewandelt, dann Poppler), nur wenn es installiert ist.
    Eigenes, leeres LibreOffice-Profil je Aufruf: ein offenes LibreOffice der Nutzenden stört nicht."""
    soffice = system.werkzeug_pfad("soffice")
    if not soffice:
        raise RuntimeError("LibreOffice ist nicht installiert")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        try:
            subprocess.run([soffice, f"-env:UserInstallation={(tmp / 'profil').as_uri()}", "--headless",
                            "--convert-to", "pdf", "--outdir", str(tmp), str(pfad)], capture_output=True, timeout=120,
                           **system.prozess_optionen())
        except subprocess.TimeoutExpired:
            raise RuntimeError("LibreOffice antwortet nicht (120 s)") from None
        pdf = next(tmp.glob("*.pdf"), None)
        if pdf is None:
            raise RuntimeError("LibreOffice konnte die Datei nicht umwandeln")
        return seiten_rendern(pdf, [1])[0], None


WEGE = {"bild": [mit_pillow, eingebettet, quicklook], "raw": [eingebettet, quicklook],
        "dokument": [quicklook, office_vorschau, libreoffice, eingebettet], "illustrator": [eingebettet, quicklook], "postscript": [eingebettet],
        "video": [standbilder]}             # oder bildfolge bzw. pdfseiten, je nach Projekteinstellung (wege)
ql_haenger = {}        # Format → wie oft Quick Look zuletzt hintereinander nicht geantwortet hat


def wege(art, relpfad=""):
    if art == "video" and P.film_art == "webp":
        return [bildfolge]
    if art == "dokument" and P.pdf_art in ("webp", "bereich") and ist_pdf(relpfad):
        return [pdfseiten, quicklook]
    if art == "dokument" and ist_pdf(relpfad):          # erste Seite: Poppler, Quick Look nur als Rückfall (Mac)
        return [pdf_erste_seite, quicklook, eingebettet]
    return WEGE[art]


def bedarf_bytes(art, relpfad="", mime=None):
    """Geschätzte Größe eines Vorschaubilds; ein animiertes WebP etwa 25 KB je Bild bzw. Seite."""
    if art == "video" and P.film_art == "webp":
        return P.film_bilder * 25_000
    if art == "dokument" and P.pdf_art == "webp" and ist_pdf(relpfad, mime):
        return P.pdf_seiten * 25_000
    if art == "dokument" and P.pdf_art == "bereich" and ist_pdf(relpfad, mime):
        return (P.pdf_bereich[1] - P.pdf_bereich[0] + 1) * 25_000
    return 35_000


def speichern(bild, sha):
    """Schreibt das Vorschaubild (JPEG, bei einer Bildfolge animiertes WebP); gibt den Pfad relativ zu vorschauen zurück."""
    datei = f"{sha[:2]}/{sha}.{'webp' if isinstance(bild, list) else 'jpg'}"
    ziel = P.vorschauen / datei
    ziel.parent.mkdir(exist_ok=True)
    zwischen = ziel.with_suffix(".tmp")
    if isinstance(bild, list):
        bild[0].save(zwischen, "WEBP", save_all=True, append_images=bild[1:], duration=FILM_BILDDAUER_MS, loop=0,
                     quality=WEBP_QUALITAET)
    else:
        bild.save(zwischen, "JPEG", quality=JPEG_QUALITAET)
    os.replace(zwischen, ziel)       # erst fertig schreiben, dann umbenennen
    return datei


def phash(bild):
    """Wahrnehmungs-Hash: 64 Bit, die den groben Bildeindruck beschreiben (16 Hex-Zeichen).
    Je weniger Bits sich zwischen zwei Bildern unterscheiden, desto ähnlicher sehen sie aus."""
    grau = np.asarray(bild.convert("L").resize((32, 32), Image.Resampling.LANCZOS), dtype=np.float64)
    tief = (DCT @ grau @ DCT.T)[:8, :8].flatten()
    return f"{int(''.join('1' if b else '0' for b in tief > np.median(tief)), 2):016x}"


def vorschau_machen(wurzel, relpfad, art, format_name=None, pfad=None):
    """Probiert die Wege für diese Art nacheinander. Gibt (bild, originalgröße, weg, fehler) zurück;
    Fehler früherer Wege werden auch dann vermerkt, wenn ein späterer Weg klappt (Hinweis auf Beschädigung).
    pfad: Pfad im Dateisystem, wenn die Datei woanders liegt (aus einer Archivdatei entpackt)."""
    pfad = pfad or quellpfad(wurzel, relpfad)
    fehler = []
    for weg in wege(art, relpfad):
        if weg is quicklook and ql_haenger.get(format_name, 0) >= QL_AUSSETZER:
            fehler.append("quicklook: übersprungen (hängt bei diesem Format)")
            continue
        try:
            bild, groesse = weg(pfad)
            if weg is quicklook:
                ql_haenger[format_name] = 0
            return bild, groesse, weg.__name__, "; ".join(fehler) or None
        except Exception as e:
            if weg is quicklook and "antwortet nicht" in str(e):
                ql_haenger[format_name] = ql_haenger.get(format_name, 0) + 1
            fehler.append(f"{weg.__name__}: {str(e)[:150] or type(e).__name__}")
    return None, None, None, "; ".join(fehler)


def vorschauen_erzeugen(platte_id, wurzel, neu_versuchen=False):
    """Erzeugt die fehlenden Vorschaubilder einer Platte, eines je Inhalt. Unterbrechbar und fortsetzbar."""
    if neu_versuchen:
        with db() as con:
            n = con.execute("DELETE FROM vorschau WHERE datei IS NULL AND sha256 IN "
                            "(SELECT sha256 FROM datei WHERE platte_id = ?)", (platte_id,)).rowcount
        print(f"{n:,} fehlgeschlagene Vorschauen werden neu versucht.")
    with db() as con:
        # nur Dateien, deren Format Siegfried erkannt hat; Zufallsdaten mit Bildendung bringen Quick Look zum Hängen
        k = pd.read_sql("""SELECT relpfad, sha256, mime, format FROM datei d WHERE platte_id = ? AND groesse > 0
                           AND sha256 IS NOT NULL AND puid IS NOT NULL AND puid != 'UNKNOWN' AND NOT EXISTS (SELECT 1 FROM vorschau v WHERE v.sha256 = d.sha256)
                           AND NOT EXISTS (SELECT 1 FROM virenscan vs WHERE vs.sha256 = d.sha256 AND vs.befund = 'Fund')
                           ORDER BY relpfad""", con, params=(platte_id,))
    k = ohne_systemdateien(k)
    k["art"] = [vorschau_art(r, m, f) for r, m, f in zip(k.relpfad, k.mime, k.format)]
    k = k[k.art.notna()].drop_duplicates("sha256")
    if k.empty:
        print(f"Für {platte_id} gibt es alle möglichen Vorschaubilder.")
        return
    bedarf = sum(map(bedarf_bytes, k.art, k.relpfad, k.mime)) / 1e9
    film = (f"Filme als animiertes WebP mit {P.film_bilder} Bildern" if P.film_art == "webp"
            else "Filme als 2 × 2-Raster")
    pdf = (f"PDFs als animiertes WebP mit bis zu {P.pdf_seiten} Seiten" if P.pdf_art == "webp"
           else f"PDFs als animiertes WebP mit den Seiten {P.pdf_bereich[0]}–{P.pdf_bereich[1]}" if P.pdf_art == "bereich"
           else "PDFs mit der ersten Seite")
    print(f"Offen: {len(k):,} Inhalte ({', '.join(f'{n:,} {a}' for a, n in k.art.value_counts().items())}), "
          f"ca. {bedarf:.1f} GB {'im Projekt' if P.arbeitsplatte is None else 'auf der Arbeitsplatte'}; {film}; {pdf}.")
    if P.arbeitsplatte is None:
        platz_pruefen(bedarf + len(k) * 500 / 1e9)
    else:
        frei_dort = shutil.disk_usage(P.arbeitsplatte).free / 1e9
        if frei_dort < bedarf + 1:
            raise RuntimeError(f"Zu wenig Platz auf dem Datenträger für Vorschaubilder {P.arbeitsplatte.name}: {frei_dort:.1f} GB frei, "
                               f"die Vorschaubilder brauchen ca. {menge(bedarf)} plus 1 GB Reserve. Bitte dort Platz "
                               f"freiräumen und dann „Alles Offene fortsetzen“.")
        platz_pruefen(len(k) * 500 / 1e9)       # Datenbankzeilen im Projektordner

    with db() as con:
        lauf_id = con.execute("INSERT INTO scanlauf (platte_id, art, start) VALUES (?,?,?)",
                              (platte_id, "vorschau", jetzt())).lastrowid
    erledigt = ohne = 0
    start = letzte = time.monotonic()
    unterbrochen = False
    with db() as con:
        try:
            # Dateien in Archivdateien je Stapel kurz ins Projekt entpacken (Entscheidung 06.11.2026)
            for (relpfad, sha, art, format_name), pfad in archivdateien.je_stapel(
                    platte_id, wurzel, zip(k.relpfad, k.sha256, k.art, k.format)):
                bild, groesse, weg, fehler = vorschau_machen(wurzel, relpfad, art, format_name, pfad)
                datei = hash_wert = einfarbig = None
                if bild is not None:
                    datei = speichern(bild, sha)
                    if art in ("bild", "raw"):           # pHash nur für Fotos und Scans
                        hash_wert = phash(bild)
                        einfarbig = int(np.asarray(bild.convert("L")).std() < 4)
                else:
                    ohne += 1
                con.execute("INSERT OR REPLACE INTO vorschau VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (sha, datei, art, weg, *(groesse or (None, None)), hash_wert, einfarbig, fehler, jetzt()))
                erledigt += 1
                if time.monotonic() - letzte > 2:
                    con.commit()
                    letzte = time.monotonic()
                    minuten = (letzte - start) / 60
                    fortschritt(erledigt / len(k), f"{erledigt:,}/{len(k):,} · ohne Vorschau {ohne:,} · "
                                f"{restzeit(minuten / erledigt * (len(k) - erledigt))}")
        except KeyboardInterrupt:
            unterbrochen = True
        con.execute("UPDATE scanlauf SET ende = ?, dateien = ?, fehler = ? WHERE lauf_id = ?",
                    (jetzt(), erledigt, ohne, lauf_id))
    protokolliere("F", platte_id, "vorschau", "", f"{erledigt} Inhalte, {ohne} ohne Vorschau"
                  + (", unterbrochen" if unterbrochen else ""))
    print(f"\n{'Unterbrochen' if unterbrochen else 'Fertig'}: {erledigt:,} Inhalte, davon {ohne:,} ohne Vorschau.")

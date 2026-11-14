"""E4 Text der Dokumente und Titelkandidaten (Textebene, keine Texterkennung). Liest die Platte.

Ergebnis je Inhalt und Endung (SHA-256 + Endung, wie die Übernahme in D2/E) in der Tabelle `volltext`: der Text
(zlib-komprimiert), Zeichen, Seiten, Weg und eine Liste von Titelkandidaten mit Quelle, Schriftgröße und Position,
damit die Regeln für Dokumenttitel später ohne Platte verfeinert werden können (Entscheidung 03.11.2026).

Nur plattformneutrale Werkzeuge: Poppler (`pdftotext`, wie die PDF-Vorschau in F), python-docx, python-pptx,
pdfminer.six (Lesezeichen), olefile (alte Binärformate .doc und .ppt) und die Standardbibliothek.
Was sich so nicht lesen lässt, bekommt einen Eintrag mit Fehler und bleibt ohne Text.
"""
import html.parser
import struct
import xml.etree.ElementTree as ET
import zipfile
import zlib

from .basis import *  # noqa: F401,F403
from . import archivdateien
from .platte import angeschlossene_platte_pruefen

# Endung → Leser (siehe LESER unten); Excel und Layoutformate (InDesign, Quark …) haben keinen auslesbaren Fließtext
TEXT_ENDUNGEN = {".pdf", ".doc", ".dot", ".docx", ".docm", ".dotx", ".ppt", ".pps", ".pot", ".pptx", ".ppsx", ".pptm",
                 ".odt", ".odp", ".rtf", ".txt", ".htm", ".html"}
MAX_ZEICHEN = 2_000_000          # längere Texte werden gekürzt (Platz; für Titel und Inhaltsangabe genügt der Anfang)
MAX_KANDIDATEN = 12
ZEITLIMIT_PDF = 120              # Sekunden je Aufruf von pdftotext, dann gilt die Datei als nicht lesbar


def endung(relpfad):
    """Endung wie bei der Übernahme gleicher Inhalte (basis.vorlagen_waehlen)."""
    return os.path.splitext(relpfad)[1].lower()


def sauber(text):
    """Leerraum zusammenfassen, Steuerzeichen entfernen."""
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text or "")
    return re.sub(r"[ \t\u00a0]+", " ", text).strip()


def kandidat(text, quelle, groesse=None, seite=None, position=None):
    text = sauber(text)[:300]
    return {"text": text, "quelle": quelle, "groesse": groesse, "seite": seite, "position": position} if text else None


def erste_zeilen(text, quelle, anzahl=3):
    zeilen = [z for z in (sauber(z) for z in text.splitlines()) if len(z) >= 3]
    return [kandidat(z, quelle, position=i) for i, z in enumerate(zeilen[:anzahl])]


# ---------- PDF ----------

def pdf_lesen(pfad):
    r = subprocess.run([system.werkzeug("pdftotext"), "-enc", "UTF-8", "-q", str(pfad), "-"], capture_output=True, timeout=ZEITLIMIT_PDF)
    text = r.stdout.decode("utf-8", errors="replace")
    if r.returncode != 0 and not text.strip():
        raise RuntimeError(f"pdftotext: Rückgabe {r.returncode}, kein Text (verschlüsselt oder beschädigt?)")
    seiten = text.count("\f") or None
    titel = pdf_schriftgroessen(pfad) + pdf_lesezeichen(pfad)
    if not text.strip():
        titel.append({"text": "", "quelle": "hinweis", "groesse": None, "seite": None,
                      "position": "keine Textebene (Bild-PDF oder Schrift in Pfaden)"})
    return text.replace("\f", "\n\n"), seiten, "pdftotext", titel


def pdf_schriftgroessen(pfad):
    """Zeilen auf Seite 1 mit ihrer Höhe (≈ Schriftgröße) aus `pdftotext -bbox-layout`; die größten zuerst."""
    r = subprocess.run([system.werkzeug("pdftotext"), "-bbox-layout", "-f", "1", "-l", "1", "-enc", "UTF-8", "-q", str(pfad), "-"],
                       capture_output=True, timeout=30)
    zeilen = []
    for m in re.finditer(r'<line xMin="([\d.]+)" yMin="([\d.]+)" xMax="[\d.]+" yMax="([\d.]+)">(.*?)</line>',
                         r.stdout.decode("utf-8", errors="replace"), re.S):
        woerter = [html.unescape(w) for w in re.findall(r"<word[^>]*>(.*?)</word>", m.group(4), re.S)]
        text = sauber(" ".join(woerter))
        if len(text) >= 3:
            zeilen.append((round(float(m.group(3)) - float(m.group(2)), 1), float(m.group(2)), text))
    if not zeilen:
        return []
    groessen = sorted(z[0] for z in zeilen)
    median = groessen[len(groessen) // 2]
    # benachbarte Zeilen gleicher Größe (zweizeiliger Titel) zusammenfassen
    gruppen = []
    for h, y, text in sorted(zeilen, key=lambda z: z[1]):
        if gruppen and abs(gruppen[-1][0] - h) < 0.6 and y - gruppen[-1][2] < h * 1.8:
            gruppen[-1] = (h, gruppen[-1][1], y, gruppen[-1][3] + " " + text)
        else:
            gruppen.append((h, y, y, text))
    gross = sorted((g for g in gruppen if g[0] >= median * 1.15), key=lambda g: (-g[0], g[1]))[:5]
    return [kandidat(t, "schrift", groesse=h, seite=1, position=round(y)) for h, y, _, t in gross]


def pdf_lesezeichen(pfad):
    """Oberste Lesezeichen (Inhaltsverzeichnis des PDF), sofern vorhanden."""
    try:
        from pdfminer.pdfdocument import PDFDocument, PDFNoOutlines
        from pdfminer.pdfparser import PDFParser
        with open(pfad, "rb") as f:
            dokument = PDFDocument(PDFParser(f))
            ergebnis = []
            for ebene, titel, *_ in dokument.get_outlines():
                if ebene == 1 and isinstance(titel, str):
                    ergebnis.append(kandidat(titel, "lesezeichen", position=len(ergebnis)))
                if len(ergebnis) >= 5:
                    break
            return ergebnis
    except Exception:            # keine Lesezeichen, verschlüsselt, beschädigt: dann eben keine
        return []


# ---------- Office Open XML (python-docx, python-pptx) ----------

UEBERSCHRIFT = re.compile(r"^(title|titel|heading 1|überschrift 1|heading1|titre|titolo)$", re.I)


def docx_lesen(pfad):
    import docx
    d = docx.Document(str(pfad))
    absaetze = [p for p in d.paragraphs]
    teile = [p.text for p in absaetze]
    for tabelle in d.tables:
        for zeile in tabelle.rows:
            teile.append("\t".join(z.text for z in zeile.cells))
    titel = [kandidat(d.core_properties.title or "", "eingebettet")]
    titel += [kandidat(p.text, "ueberschrift", position=i) for i, p in enumerate(absaetze)
              if p.style is not None and UEBERSCHRIFT.match(p.style.name or "")][:5]
    text = "\n".join(teile)
    return text, None, "python-docx", titel + erste_zeilen(text, "erste_zeile")


def pptx_lesen(pfad):
    import pptx
    p = pptx.Presentation(str(pfad))
    teile, titel = [], [kandidat(p.core_properties.title or "", "eingebettet")]
    for nr, folie in enumerate(p.slides, 1):
        for form in folie.shapes:
            if form.has_text_frame:
                teile.append(form.text_frame.text)
        try:
            folientitel = folie.shapes.title.text if folie.shapes.title is not None else ""
        except Exception:
            folientitel = ""
        if folientitel and nr <= 3:
            titel.append(kandidat(folientitel, "folie", seite=nr))
        teile.append("")
    return "\n".join(teile), len(p.slides), "python-pptx", titel


# ---------- OpenDocument (zip mit content.xml) ----------

def odf_lesen(pfad):
    ns = {"text": "urn:oasis:names:tc:opendocument:xmlns:text:1.0", "dc": "http://purl.org/dc/elements/1.1/",
          "office": "urn:oasis:names:tc:opendocument:xmlns:office:1.0"}
    with zipfile.ZipFile(pfad) as z:
        inhalt = ET.fromstring(z.read("content.xml"))
        meta = ET.fromstring(z.read("meta.xml")) if "meta.xml" in z.namelist() else None
    teile = ["".join(e.itertext()) for e in inhalt.iter() if e.tag in (f"{{{ns['text']}}}p", f"{{{ns['text']}}}h")]
    titel = []
    if meta is not None:
        t = meta.find(".//dc:title", ns)
        titel.append(kandidat(t.text if t is not None else "", "eingebettet"))
    titel += [kandidat("".join(e.itertext()), "ueberschrift", position=i)
              for i, e in enumerate(inhalt.iter(f"{{{ns['text']}}}h"))][:5]
    text = "\n".join(teile)
    return text, None, "odf", titel + erste_zeilen(text, "erste_zeile")


# ---------- alte Binärformate über olefile ----------

def ole_titel(ole):
    """Titel aus den Dokumenteigenschaften (SummaryInformation)."""
    try:
        t = ole.get_metadata().title
        return kandidat(t.decode("cp1252", errors="replace") if isinstance(t, bytes) else (t or ""), "eingebettet")
    except Exception:
        return None


def word_text(wd, tabelle):
    """Haupttext eines Word-97–2003-Dokuments über die Stückliste (Clx/PlcPcd) im Table-Stream ([MS-DOC] 2.4.1)."""
    ccp_text = struct.unpack_from("<i", wd, 0x4C)[0]                 # Zeichen im Haupttext (FibRgLw97.ccpText)
    fc_clx, lcb_clx = struct.unpack_from("<II", wd, 0x1A2)           # FibRgFcLcb97.fcClx / lcbClx
    clx = tabelle[fc_clx:fc_clx + lcb_clx]
    i = 0
    while i < len(clx) and clx[i] == 0x01:                           # Prc-Einträge (Formatierungen) überspringen
        i += 3 + struct.unpack_from("<h", clx, i + 1)[0]
    if i >= len(clx) or clx[i] != 0x02:
        raise RuntimeError("Word: keine Stückliste gefunden")
    lcb = struct.unpack_from("<I", clx, i + 1)[0]
    plc = clx[i + 5:i + 5 + lcb]
    n = (lcb - 4) // 12
    cps = struct.unpack_from(f"<{n + 1}I", plc, 0)
    teile = []
    for k in range(n):
        fc = struct.unpack_from("<I", plc, 4 * (n + 1) + 8 * k + 2)[0]
        anzahl = cps[k + 1] - cps[k]
        if fc & 0x40000000:                                          # komprimiert: 1 Byte je Zeichen (cp1252)
            start = (fc & 0x3FFFFFFF) // 2
            teile.append(wd[start:start + anzahl].decode("cp1252", errors="replace"))
        else:
            teile.append(wd[fc:fc + 2 * anzahl].decode("utf-16-le", errors="replace"))
        if cps[k + 1] >= ccp_text:
            break
    text = "".join(teile)[:max(ccp_text, 0)]
    text = re.sub(r"\x13[^\x13\x14\x15]*\x14?([^\x13\x15]*)\x15", r"\1", text)   # Feldfunktionen: nur das Ergebnis
    return text.replace("\r", "\n").replace("\x07", "\t").replace("\x0b", "\n").replace("\x0c", "\n")


def doc_lesen(pfad):
    import olefile
    with olefile.OleFileIO(str(pfad)) as ole:
        if not ole.exists("WordDocument"):
            raise RuntimeError("kein Word-97–2003-Dokument (Word 6/95 oder anderes Format)")
        wd = ole.openstream("WordDocument").read()
        if struct.unpack_from("<H", wd, 0)[0] != 0xA5EC:
            raise RuntimeError("Word: unbekannter Dateikopf")
        flags = struct.unpack_from("<H", wd, 0x0A)[0]
        if flags & 0x0100:
            raise RuntimeError("Word: verschlüsselt")
        stream = "1Table" if flags & 0x0200 else "0Table"
        if not ole.exists(stream):
            raise RuntimeError(f"Word: {stream} fehlt")
        text = word_text(wd, ole.openstream(stream).read())
        titel = [ole_titel(ole)] + erste_zeilen(text, "erste_zeile")
    return text, None, "olefile-doc", titel


PPT_TITELARTEN = {0, 6}        # TextHeaderAtom.textType: 0 = Titel, 6 = zentrierter Titel
PPT_OHNE = {0x03F8}             # MainMaster (auch Titelmaster): „Titelmasterformat durch Klicken bearbeiten“ …


def ppt_texte(daten):
    """Alle Textatome (TextCharsAtom, TextBytesAtom) mit der Art aus dem vorangehenden TextHeaderAtom, in Folge des Streams."""
    texte, art, stapel = [], None, [(0, len(daten), 0)]
    while stapel:
        pos, ende, tiefe = stapel.pop()
        while pos + 8 <= ende:
            ver_inst, typ, laenge = struct.unpack_from("<HHI", daten, pos)
            inhalt = pos + 8
            if inhalt + laenge > ende:
                break
            if ver_inst & 0x0F == 0x0F and tiefe < 20:                 # Container: Kinder später weiterlesen
                stapel.append((inhalt + laenge, ende, tiefe))
                if typ in PPT_OHNE:                                    # Masterfolien: nur Platzhaltertexte
                    break
                stapel.append((inhalt, inhalt + laenge, tiefe + 1))
                break
            if typ == 0x0F9F and laenge >= 4:                          # TextHeaderAtom
                art = struct.unpack_from("<I", daten, inhalt)[0]
            elif typ == 0x0FA0:                                        # TextCharsAtom (UTF-16)
                texte.append((art, daten[inhalt:inhalt + laenge].decode("utf-16-le", errors="replace")))
            elif typ == 0x0FA8:                                        # TextBytesAtom (8 Bit)
                texte.append((art, daten[inhalt:inhalt + laenge].decode("latin-1")))
            pos = inhalt + laenge
    return texte


def ppt_lesen(pfad):
    import olefile
    with olefile.OleFileIO(str(pfad)) as ole:
        if not ole.exists("PowerPoint Document"):
            raise RuntimeError("keine PowerPoint-97–2003-Präsentation")
        texte = ppt_texte(ole.openstream("PowerPoint Document").read())
        titel = [ole_titel(ole)]
    zeilen, vorher = [], None
    for art, t in texte:
        t = t.replace("\r", "\n").replace("\x0b", "\n")
        if t != vorher:                                                # Folienliste und Folie enthalten oft dasselbe
            zeilen.append(t)
        vorher = t
    titel += [kandidat(t, "folie", position=i) for i, (art, t) in enumerate(texte) if art in PPT_TITELARTEN][:3]
    return "\n".join(zeilen), None, "olefile-ppt", titel


# ---------- RTF, HTML, Text ----------

def rtf_lesen(pfad):
    roh = Path(pfad).read_bytes().decode("latin-1")
    roh = re.sub(r"\{\\\*[^{}]*(\{[^{}]*\}[^{}]*)*\}", "", roh)              # unsichtbare Gruppen ({\*\…})
    roh = re.sub(r"\{\\(fonttbl|colortbl|stylesheet|info)[^{}]*(\{[^{}]*\}[^{}]*)*\}", "", roh)
    roh = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes([int(m[1], 16)]).decode("cp1252", errors="replace"), roh)
    roh = re.sub(r"\\u(-?\d+)\??", lambda m: chr(int(m[1]) % 65536), roh)
    roh = re.sub(r"\\(par|line)\b ?", "\n", roh)
    roh = re.sub(r"\\tab\b ?", "\t", roh)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?|[{}]|\\\n", "", roh)
    return text, None, "rtf", erste_zeilen(text, "erste_zeile")


def dekodieren(roh, zeichensatz=None):
    for z in [zeichensatz, "utf-8-sig", "cp1252"]:
        if z:
            try:
                return roh.decode(z)
            except (UnicodeDecodeError, LookupError):
                pass
    return roh.decode("latin-1")


class HtmlText(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.teile, self.titel, self.h1, self._in, self._weg = [], "", [], None, 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._weg += 1
        elif tag in ("title", "h1"):
            self._in = tag
        elif tag in ("p", "br", "div", "li", "tr", "h1", "h2", "h3"):
            self.teile.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._weg = max(0, self._weg - 1)
        elif tag == self._in:
            self._in = None

    def handle_data(self, data):
        if self._weg:
            return
        if self._in == "title":
            self.titel += data
            return
        if self._in == "h1":
            self.h1.append(data)
        self.teile.append(data)


def html_lesen(pfad):
    roh = Path(pfad).read_bytes()
    m = re.search(rb'charset=["\']?([A-Za-z0-9_\-]+)', roh[:4096])
    p = HtmlText()
    p.feed(dekodieren(roh, m.group(1).decode() if m else None))
    text = re.sub(r"\n\s*\n+", "\n\n", "".join(p.teile))
    titel = [kandidat(p.titel, "html_titel")] + [kandidat(h, "ueberschrift", position=i) for i, h in enumerate(p.h1[:3])]
    return text, None, "html", titel


def txt_lesen(pfad):
    text = dekodieren(Path(pfad).read_bytes())
    return text, None, "text", erste_zeilen(text, "erste_zeile")


LESER = {".pdf": pdf_lesen, ".doc": doc_lesen, ".dot": doc_lesen, ".docx": docx_lesen, ".docm": docx_lesen,
         ".dotx": docx_lesen, ".ppt": ppt_lesen, ".pps": ppt_lesen, ".pot": ppt_lesen, ".pptx": pptx_lesen,
         ".ppsx": pptx_lesen, ".pptm": pptx_lesen, ".odt": odf_lesen, ".odp": odf_lesen, ".rtf": rtf_lesen,
         ".txt": txt_lesen, ".htm": html_lesen, ".html": html_lesen}


def lesen(pfad, end):
    """Text, Seiten, Weg und Titelkandidaten einer Datei; Fehler als Ausnahme."""
    text, seiten, weg, titel = LESER[end](pfad)
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text).strip()
    gesehen, liste = set(), []
    for k in titel:
        if k and (k["text"] or k["quelle"] == "hinweis") and (k["quelle"], k["text"]) not in gesehen:
            gesehen.add((k["quelle"], k["text"]))
            liste.append(k)
    return text[:MAX_ZEICHEN], seiten, weg, liste[:MAX_KANDIDATEN]


# ---------- Schritt E4 ----------

def texte_offen(con, platte_id):
    """Dokumente einer Platte, deren Inhalt (SHA-256 + Endung) noch keinen Eintrag in volltext hat."""
    d = pd.read_sql("""SELECT d.relpfad, d.sha256 FROM datei d WHERE d.platte_id = ? AND d.groesse > 0
                       AND d.sha256 IS NOT NULL
                       AND NOT EXISTS (SELECT 1 FROM virenscan v WHERE v.sha256 = d.sha256 AND v.befund = 'Fund')
                       ORDER BY d.relpfad""", con, params=(platte_id,))
    d = d[~d.relpfad.map(ist_systemdatei) & ~d.relpfad.str.contains("\n", regex=False)]
    d = d.assign(endung=d.relpfad.map(endung))
    d = d[d.endung.isin(TEXT_ENDUNGEN)]
    fertig = set(con.execute("SELECT sha256, endung FROM volltext").fetchall())
    d = d[[(s, e) not in fertig for s, e in zip(d.sha256, d.endung)]]
    return d.drop_duplicates(["sha256", "endung"])           # gleicher Inhalt auf derselben Platte: einmal lesen


def text_holen(sha256, end):
    """Gespeicherter Text eines Inhalts (für Vorlauf und Erschließung); None, wenn keiner vorliegt."""
    with db() as con:
        z = con.execute("SELECT text FROM volltext WHERE sha256 = ? AND endung = ?", (sha256, end)).fetchone()
    return zlib.decompress(z[0]).decode("utf-8") if z and z[0] else None


def texte_lesen(platte_id, wurzel):
    """E4 Liest den Text aller Dokumente der Platte, deren Inhalt noch keinen Eintrag hat (andere Platten mit gleichem
    Inhalt zählen mit). Abbrechbar; ein neuer Aufruf macht weiter, wo er aufgehört hat."""
    with db() as con:
        offen = texte_offen(con, platte_id)
    if offen.empty:
        print(f"Für {platte_id} liegen alle Texte vor.")
        return
    angeschlossene_platte_pruefen(platte_id, wurzel)
    platz_pruefen(0.5)
    print(f"Offen: {len(offen):,} Dokumente " + ", ".join(f"{e} {n}" for e, n in offen.endung.value_counts().items()))
    erledigt = mit_text = fehler = 0
    start = time.monotonic()
    unterbrochen = False
    sql = """INSERT OR REPLACE INTO volltext (sha256, endung, text, zeichen, seiten, weg, titel, fehler, gelesen_am, quelle)
             VALUES (?,?,?,?,?,?,?,?,?,?)"""
    with db() as con:
        try:
            # Dateien in Archivdateien je Stapel kurz ins Projekt entpacken (Entscheidung 06.11.2026)
            for (relpfad, sha, end), pfad in archivdateien.je_stapel(
                    platte_id, wurzel, offen[["relpfad", "sha256", "endung"]].itertuples(index=False)):
                try:
                    text, seiten, weg, titel = lesen(pfad, end)
                    zeile = (zlib.compress(text.encode("utf-8"), 6) if text else None, len(text), seiten, weg,
                             json.dumps(titel, ensure_ascii=False), None)
                    mit_text += bool(text)
                except KeyboardInterrupt:
                    raise
                except Exception as f:              # beschädigt, verschlüsselt, unbekannte Variante, Zeitlimit …
                    zeile = (None, 0, None, LESER[end].__name__, "[]", f"{type(f).__name__}: {f}"[:300])
                    fehler += 1
                con.execute(sql, (sha, end, *zeile, jetzt(), f"{platte_id}:{relpfad}"))
                erledigt += 1
                if erledigt % 20 == 0:
                    con.commit()
                    minuten = (time.monotonic() - start) / 60
                    fortschritt(erledigt / len(offen), f"{erledigt:,}/{len(offen):,} Dokumente · "
                                f"{restzeit(minuten / erledigt * (len(offen) - erledigt))}")
        except KeyboardInterrupt:
            unterbrochen = True
    protokolliere("E4", platte_id, "texte", "", f"{erledigt} Dokumente, {mit_text} mit Text, {fehler} nicht lesbar"
                  + (", unterbrochen" if unterbrochen else ""))
    print(f"\n{'Unterbrochen' if unterbrochen else 'Fertig'}: {erledigt:,} Dokumente gelesen, {mit_text:,} mit Text, "
          f"{fehler:,} nicht lesbar.")

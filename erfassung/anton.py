"""G5 Schon in Anton? Bestand von Anton holen (API) oder Auszug einlesen, Dateien über die MD5 abgleichen."""
import urllib.parse

from .basis import *  # noqa: F401,F403


# EINSTELLUNG G5a (Vorgaben); die Adresse des Anton-Servers steht in projekt.json (P.anton_url)
# Nur für einen Auszug mit anderen Spaltennamen: Spalte im Auszug → Spalte der CSV
# (md5, dateiname, signatur, titel, anton_datei, link, altsignatur), z. B. {"MD5": "md5", "Signatur": "signatur"}
ANTON_SPALTEN = {}


# G5b Bestand von Anton holen (API) oder Auszug einlesen
# altsignatur = identifier_old des Objekts: Balduin liefert dort „Platte:Pfad“, Anton benennt die Dateien beim Import um
# (gesehen an einer Testinstanz, 14.11.2026), die Kontrolle erkennt sie daran wieder
ANTON_CSV_SPALTEN = ["md5", "dateiname", "signatur", "titel", "anton_datei", "link", "altsignatur", "nur_platten"]
# Der API-Abruf schreibt zusätzlich Objekt- und Medien-ID, Größe, MIME und Zugang (intern/öffentlich)
ANTON_API_SPALTEN = ANTON_CSV_SPALTEN + ["objekt_id", "medien_id", "groesse", "mime", "zugang"]
ANTON_JE_SEITE = 1000                      # höchstens 1000 Objekte je Seite erlaubt die API


# Der Token liegt im Schlüsselbund des Systems (macOS Schlüsselbund, Windows Anmeldeinformationsverwaltung;
# erfassung/system.py). Tests nennen in ANTON_SCHLUESSELBUND einen eigenen Schlüsselbund.

def schluesselbund_eintrag():
    return f"Anton-API {urlparse(P.anton_url).hostname}"


def anton_token():
    """Token für die Anton-API: Umgebungsvariable ANTON_TOKEN, sonst Schlüsselbund (Eintrag „Anton-API <Server>“).
    Wird nie ausgegeben oder gespeichert; leer = nur öffentliche Bestände."""
    token = os.environ.get("ANTON_TOKEN", "").strip()
    if not token:
        token = system.geheimnis_lesen(schluesselbund_eintrag())
    return token


def token_quelle():
    """Woher der Token käme, ohne ihn zu lesen: Umgebungsvariable, Schlüsselbund oder leer (keiner)."""
    if os.environ.get("ANTON_TOKEN", "").strip():
        return "Umgebungsvariable"
    return "Schlüsselbund" if system.geheimnis_vorhanden(schluesselbund_eintrag()) else ""


def token_speichern(token):
    """Legt den Token im Schlüsselbund ab (ersetzt einen vorhandenen). Er erscheint in keiner Prozessliste
    (system.geheimnis_speichern)."""
    token = (token or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9|._~+/=-]{8,500}", token):
        raise ValueError("Das sieht nicht wie ein Anton-Token aus (nur Buchstaben, Ziffern und | . _ ~ + / = -).")
    konto = os.environ.get("USER") or os.environ.get("USERNAME") or "anton"
    if not system.geheimnis_speichern(schluesselbund_eintrag(), konto, token) or token_quelle() == "":
        raise RuntimeError(f"Das API-Token konnte nicht {system.systemwoerter()['im_schluesselspeicher']} abgelegt werden.")
    protokolliere("G5", schluesselbund_eintrag(), "token", "", f"{system.systemwoerter()['im_schluesselspeicher']} abgelegt")


def token_entfernen():
    if system.geheimnis_entfernen(schluesselbund_eintrag()):
        protokolliere("G5", schluesselbund_eintrag(), "token", system.systemwoerter()["im_schluesselspeicher"], "entfernt")


def zugang_bestimmen(token, gesamt, oeffentlich):
    """Zugang eines Abrufs: „intern“ = der Token sieht mehr als öffentlich; „mit Token“ = Token angenommen, sieht aber
    nicht mehr (alles ist öffentlich oder dem Konto fehlt eine interne Rolle; von außen nicht zu unterscheiden, zählt
    als vollständig, Hinweis 06.11.2026); „öffentlich“ = ohne Token. Ein abgelehnter Token bricht vorher ab (401/403)."""
    if not token:
        return "öffentlich"
    return "intern" if gesamt > oeffentlich else "mit Token"


def verbindung_pruefen():
    """Fragt Anton nach der Zahl der Objekte, ohne und mit Token; zeigt, ob der Token mehr sieht als öffentlich."""
    token = anton_token()
    try:
        oeffentlich = anton_holen("/objects?perPage=1", None, versuche=1, timeout=30)["meta"]["total"]
        gesamt = anton_holen("/objects?perPage=1", token, versuche=1, timeout=30)["meta"]["total"] if token else oeffentlich
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as fehler:
        raise RuntimeError(f"{P.anton_url} antwortet nicht wie Anton: {getattr(fehler, 'reason', fehler)}") from None
    return {"url": P.anton_url, "token": token_quelle(), "oeffentlich": oeffentlich, "gesamt": gesamt,
            "zugang": zugang_bestimmen(token, gesamt, oeffentlich)}


def einheit_holen(kennung):
    """Modul 3, Bestandsbox: eine Anton-Einheit über ihre ID (Zahl) oder Signatur, nur lesend, mit Token, wenn einer
    hinterlegt ist (interne Bestände); dazu die Eltern bis zur obersten Ebene (höchstens 10)."""
    kennung = str(kennung or "").strip()
    if not kennung or len(kennung) > 100:
        raise ValueError("Bitte eine Anton-ID oder Signatur angeben.")
    token = anton_token()
    feld = "ids" if kennung.isdigit() else "identifier"

    def objekt(feld, wert):
        try:
            daten = anton_holen(f"/objects?{feld}={urllib.parse.quote(wert)}&perPage=5", token, versuche=1, timeout=30)
        except (urllib.error.URLError, TimeoutError) as fehler:
            raise RuntimeError(f"{P.anton_url} antwortet nicht: {getattr(fehler, 'reason', fehler)}") from None
        # Anton antwortet je nach Filter verschieden: ?ids= gibt eine Liste, ?identifier= bei einem Treffer
        # ein einzelnes Objekt, ohne Treffer eine leere Liste.
        d = daten.get("data")
        if isinstance(d, dict):
            return d
        return d[0] if d else None

    kennung = " ".join(kennung.split())          # doppelte Leerzeichen aus dem Kopieren
    o = objekt(feld, kennung)
    if not o:
        raise ValueError(f"In Anton gibt es keine Einheit mit {'der ID' if feld == 'ids' else 'der Signatur'} {kennung}"
                         + ("" if token else " (ohne Token nur öffentliche Bestände)") + ".")
    eltern, p = [], o.get("parent_id")
    while p and len(eltern) < 10:
        e = objekt("ids", str(p))
        if not e:
            break
        eltern.append({"id": e.get("id"), "signatur": e.get("identifier") or "", "titel": e.get("title") or "",
                       "stufe": e.get("level_of_description") or ""})
        p = e.get("parent_id")
    # gesperrt: nur mit Token sichtbar. Mit Token wird dieselbe Einheit einmal ohne Token abgefragt; fehlt sie dort,
    # ist sie nicht öffentlich. Ohne Token ist alles Sichtbare öffentlich; ein Feld der Antwort zählt zusätzlich.
    gesperrt = sperrfeld(o)
    if token and not gesperrt:
        try:
            frei = anton_holen(f"/objects?ids={o.get('id')}&perPage=5", None, versuche=1, timeout=30).get("data")
            gesperrt = not (frei if isinstance(frei, dict) else frei and frei[0])
        except (urllib.error.URLError, TimeoutError, ValueError, RuntimeError):
            pass                                        # unbekannt: nicht als gesperrt markieren
    return {"id": o.get("id"), "signatur": o.get("identifier") or "", "titel": o.get("title") or "",
            "stufe": o.get("level_of_description") or "", "objektart": o.get("object_type") or "",
            "anzahl": o.get("object_count"), "link": o.get("permalink") or "", "eltern": eltern[::-1],
            "zugang": "intern" if token else "öffentlich", "laufzeit": laufzeit(o), "gesperrt": bool(gesperrt)}


def sperrfeld(o):
    """Ob die Antwort selbst eine Sperre nennt. Die Feldnamen sind in der Anton-Doku nicht beschrieben; geprüft
    werden die üblichen (an einer echten Antwort nachprüfen)."""
    for feld in ("is_public", "public", "published", "is_published"):
        if feld in o and o[feld] is not None:
            return not o[feld]
    for feld in ("restricted", "is_restricted", "locked", "is_locked"):
        if o.get(feld):
            return True
    zugang = str(o.get("access") or o.get("access_status") or "").casefold()
    return zugang in ("intern", "internal", "restricted", "gesperrt", "private")


def zeitspanne(von, bis):
    """Zwei Datumsangaben (ISO oder frei) als „TT.MM.JJJJ–TT.MM.JJJJ“; ganze Jahre (01.01. bis 31.12.) nur als Jahr."""
    def iso(x):
        m = re.match(r"(\d{4})-(\d{2})-(\d{2})", str(x or ""))
        return m.groups() if m else None
    a, b = iso(von), iso(bis)
    if a and b and a[1:] == ("01", "01") and b[1:] == ("12", "31"):
        teile = [a[0], b[0]]
    else:
        teile = [f"{x[2]}.{x[1]}.{x[0]}" if x else str(y or "")[:10] for x, y in ((a, von), (b, bis))]
    return "–".join(dict.fromkeys(x for x in teile if x))


def laufzeit(o):
    """Laufzeit einer Anton-Einheit als kurzer Text, aus dem ersten passenden Feld der Antwort (Feldnamen nicht
    dokumentiert: übliche Namen, dann das erste Entstehungsereignis wie im Importformat)."""
    for feld in ("date", "dates", "date_text", "datierung", "laufzeit", "creation_date"):
        w = o.get(feld)
        if isinstance(w, str) and w.strip():
            return w.strip()
        if isinstance(w, dict):
            text = w.get("text") or w.get("display") or ""
            if text:
                return str(text)
            von, bis = w.get("from") or w.get("start") or "", w.get("to") or w.get("end") or ""
            if von or bis:
                return zeitspanne(von, bis)
    von = o.get("date_from") or o.get("start_date") or ""
    bis = o.get("date_to") or o.get("end_date") or ""
    if von or bis:
        return zeitspanne(von, bis)
    for e in o.get("events") or []:
        if isinstance(e, dict) and (e.get("type") or "creation") == "creation":
            text = e.get("date_text") or e.get("date") or ""
            if isinstance(text, str) and text:
                return text
            von, bis = e.get("start_date") or e.get("from") or "", e.get("end_date") or e.get("to") or ""
            if von or bis:
                return zeitspanne(von, bis)
    return ""


def stufen_holen():
    """Modul 3: Werteliste der Stufen. Zuerst GET /api/levels-of-description (ohne Token, Sprache der Instanz; Antwort
    {"<term_id>": "<Label>"} in der Reihenfolge der Werteliste, Auskunft Kränzle & Ritter 04.11.2026); geht das nicht,
    der Rückfall über /api/ai/schema mit Token (stufen_aus_schema)."""
    try:
        liste = anton_holen("/levels-of-description", anton_token(), versuche=1, timeout=30)
        if isinstance(liste, dict) and liste and all(isinstance(v, str) for v in liste.values()):
            return {"stufen": [{"name": v.strip(), "schluessel": str(k)} for k, v in liste.items() if v.strip()],
                    "quelle": "levels-of-description"}
    except (urllib.error.URLError, TimeoutError, RuntimeError, ValueError):
        pass
    return stufen_aus_schema()


# Notizfelder, die der API-Import übernimmt (docs/anton_import.md, A7); scopecontent ist „Form und Inhalt“
NOTIZ_IMPORT = {"extent_text", "internal_note"}
NOTIZ_SCHON_DA = {"scopecontent", "import_settings"}
# Bezeichnungen wie in der Bearbeitungsmaske von Anton, sonst aus dem Mapping
BEZEICHNUNG = {"extent_text": "Umfang (Beschreibung)", "internal_note": "Archivinterne Bemerkungen"}


def felder_holen():
    """Modul 3, Dropdown „Weitere Anton-Felder“: Notizfelder mit festem technischem Namen aus GET /api/import/mapping
    ({Spaltenname: kanonischer Name}, z. B. "bestandsgeschichte": "note.custod_hist"), Labels aus /api/ai/schema, wenn
    ein Token da ist (sonst aus dem deutschen Spaltennamen). Nur lesend."""
    token = anton_token()
    try:
        mapping = anton_holen("/import/mapping", token, versuche=1, timeout=30)
    except (urllib.error.URLError, TimeoutError) as fehler:
        raise RuntimeError(f"{P.anton_url} antwortet nicht: {getattr(fehler, 'reason', fehler)}") from None
    spalten = {}
    for spalte, kanonisch in (mapping or {}).items():
        if isinstance(kanonisch, str) and kanonisch.startswith("note.") and spalte:
            spalten.setdefault(kanonisch[5:], []).append(spalte)
    labels = {}
    if token:                                            # Labels der Notizfelder aus dem JSON-Schema (mit Token)
        try:
            schema = anton_holen("/ai/schema", token, versuche=1, timeout=30)

            def suchen(x):
                if isinstance(x, dict):
                    for k, v in x.items():
                        if str(k).casefold() == "notes" and isinstance(v, dict):
                            innen = v.get("properties") if isinstance(v.get("properties"), dict) else v
                            for name, angabe in innen.items():
                                if isinstance(angabe, dict):
                                    text = angabe.get("title") or angabe.get("label") or angabe.get("description")
                                    if isinstance(text, dict):
                                        text = text.get("de") or next(iter(text.values()), "")
                                    if isinstance(text, str) and text.strip():
                                        labels[str(name).removeprefix("note.")] = text.strip()
                        suchen(v)
                elif isinstance(x, list):
                    for v in x:
                        suchen(v)
            suchen(schema)
        except (urllib.error.URLError, TimeoutError, RuntimeError):
            pass

    klein = {"und", "oder", "auf", "im", "in", "an", "am", "der", "die", "das", "des", "dem", "zur", "zum", "für", "mit",
             "von", "vom", "bei", "nach", "aus"}

    def lesbar(name, liste):
        """Deutscher Spaltenname als Bezeichnung: nicht der englische Name selbst, ohne _de/_en und „note.…“;
        Wörter groß außer kleinen Bindewörtern („Bezeichnung auf Blatt im Druck“)."""
        if name in BEZEICHNUNG:
            return BEZEICHNUNG[name]
        kandidaten = [s for s in liste if s != name and not s.startswith("note.") and not re.search(r"_(de|en|fr|it)$", s)]
        woerter = (kandidaten or [name])[0].replace("_", " ").split()
        return " ".join(w if i and w in klein else w[:1].upper() + w[1:] for i, w in enumerate(woerter))

    felder = [{"name": f"note.{n}", "label": labels.get(n) or lesbar(n, liste), "import": n in NOTIZ_IMPORT,
               "label_quelle": "ai/schema" if n in labels else "mapping"}
              for n, liste in spalten.items() if n not in NOTIZ_SCHON_DA]
    felder.sort(key=lambda f: (not f["import"], f["label"].casefold()))
    if not felder:
        raise ValueError("In /api/import/mapping keine Notizfelder gefunden.")
    return {"felder": felder}


def stufen_aus_schema():
    """Rückfall: Werteliste der Stufen (level_of_description) aus GET /api/ai/schema, nur lesend und nur mit Token.
    Gesucht wird der erste Eintrag unter einem Schlüssel mit „level“. In einer Instanz (gesehen 03.11.2026) ist er
    eine JSON-Schema-Beschreibung {"type": "string", "description": …, "enum": ["Archiv", …, "Einzelstück"]};
    dann zählt die Liste unter „enum“."""
    token = anton_token()
    if not token:
        raise ValueError("Für die Stufen aus Anton braucht es ein API-Token (Einstellungen des Projekts, vorn vor „Registrierung/Analyse“).")
    try:
        schema = anton_holen("/ai/schema", token, versuche=1, timeout=30)
    except (urllib.error.URLError, TimeoutError) as fehler:
        raise RuntimeError(f"{P.anton_url} antwortet nicht: {getattr(fehler, 'reason', fehler)}") from None

    def suchen(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if "level" in str(k).casefold() and isinstance(v, (list, dict)) and v:
                    return v
            for v in x.values():
                treffer = suchen(v)
                if treffer:
                    return treffer
        elif isinstance(x, list):
            for v in x:
                treffer = suchen(v)
                if treffer:
                    return treffer
        return None

    liste = suchen(schema) or []
    if isinstance(liste, dict) and isinstance(liste.get("enum"), list):    # JSON-Schema mit Werteliste
        liste = liste["enum"]
    elif isinstance(liste, dict) and isinstance(liste.get("items"), dict) and isinstance(liste["items"].get("enum"), list):
        liste = liste["items"]["enum"]
    if isinstance(liste, dict):                          # {schlüssel: name} oder {schlüssel: {…}}
        liste = [{"schluessel": k, **(v if isinstance(v, dict) else {"name": v})} for k, v in liste.items()]
    stufen = []
    for w in liste:
        if isinstance(w, str):
            name, schluessel = w, w
        elif isinstance(w, dict):
            name = w.get("label") or w.get("name") or w.get("title") or w.get("text") or w.get("value") or ""
            if isinstance(name, dict):                   # Sprachobjekt
                name = name.get("de") or next(iter(name.values()), "")
            schluessel = w.get("short_name") or w.get("schluessel") or w.get("key") or w.get("value") or w.get("id") or name
        else:
            continue
        if str(name).strip():
            stufen.append({"name": str(name).strip(), "schluessel": str(schluessel)})
    if not stufen:
        raise ValueError("In /api/ai/schema keine Werteliste der Stufen gefunden.")
    return {"stufen": stufen}


def anton_holen(pfad, token, versuche=4, timeout=180):
    """Eine Abfrage an die Anton-API, Antwort als JSON. Der Token geht nur im Header mit (in der URL lehnt Anton ab).
    Bei Netzfehlern bis zu vier Versuche mit wachsender Pause; ein abgelehnter Token bricht sofort ab."""
    anfrage = urllib.request.Request(P.anton_url + "/api" + pfad, headers={"Accept": "application/json"})
    if token:
        anfrage.add_header("Authorization", f"Bearer {token}")
    for versuch in range(versuche):
        try:
            with urllib.request.urlopen(anfrage, timeout=timeout) as antwort:
                return json.load(antwort)
        except urllib.error.HTTPError as fehler:
            if fehler.code in (401, 403):
                raise RuntimeError(f"Anton lehnt das API-Token ab (HTTP {fehler.code}): in Balduin unter Einstellungen des Projekts → Anton "
                                   "neu hinterlegen (oder EINRICHTUNG.md, Abschnitt 9).") from None
            if versuch == versuche - 1:
                raise
        except (urllib.error.URLError, TimeoutError):
            if versuch == versuche - 1:
                raise
        time.sleep(10 * (versuch + 1))


def anton_abrufen(datum):
    """Holt alle Objekte Seite für Seite und schreibt je Anton-Datei (media[]) eine Zeile.
    Jede Seite liegt zuerst einzeln in anton/abruf_<datum>/ (CSV der Medien, Liste der Objekt-IDs);
    ein unterbrochener Abruf setzt am selben Tag dort fort. Am Ende: jede Objekt-ID genau einmal und
    Gesamtzahl wie bei Anton, sonst hat sich Anton währenddessen verändert und der Abruf beginnt neu."""
    token = anton_token()
    oeffentlich = anton_holen("/objects?perPage=1", None)["meta"]["total"]
    gesamt = anton_holen("/objects?perPage=1", token)["meta"]["total"] if token else oeffentlich
    zugang = zugang_bestimmen(token, gesamt, oeffentlich)
    if not token:
        print(f"⚠ Kein API-Token gefunden ({system.systemwoerter()['schluesselspeicher']} oder ANTON_TOKEN): nur öffentliche Bestände.")
    elif zugang == "mit Token":
        print("Der Token sieht nicht mehr als öffentlich: Entweder ist alles öffentlich, oder dem Konto fehlt eine "
              "interne Rolle (dann fehlen nicht öffentliche Medien).")
    print(f"Anton: {gesamt:,} Objekte ({zugang}; öffentlich {oeffentlich:,}).")

    zwischen = P.anton / f"abruf_{datum}"
    for frueher in P.anton.glob("abruf_*"):      # abgebrochener Abruf eines anderen Tages: neu beginnen
        if frueher != zwischen:
            shutil.rmtree(frueher)
    zwischen.mkdir(exist_ok=True)
    seite, letzte, geholt = 1, -(-gesamt // ANTON_JE_SEITE), 0
    schaetzer = Restzeit(letzte)
    while seite <= letzte:
        teil, ids = zwischen / f"seite_{seite:04d}.csv", zwischen / f"seite_{seite:04d}.ids"
        if not ids.exists():
            antwort = anton_holen(f"/objects?page={seite}&perPage={ANTON_JE_SEITE}", token)
            letzte = antwort["meta"]["last_page"]
            zeilen = [{"md5": (m.get("md5sum") or "").strip().lower(), "dateiname": nfc(m.get("file_name") or ""),
                       "signatur": o.get("identifier") or "", "titel": o.get("title") or "",
                       "anton_datei": nfc(m.get("file_name") or ""), "link": o.get("permalink") or "",
                       "altsignatur": nfc(o.get("identifier_old") or ""), "nur_platten": "",
                       "objekt_id": o["id"], "medien_id": m["id"], "groesse": m.get("size") or "",
                       "mime": m.get("mime_type") or "", "zugang": zugang}
                      for o in antwort["data"] for m in (o.get("media") or [])]
            pd.DataFrame(zeilen, columns=ANTON_API_SPALTEN).to_csv(teil, index=False, encoding="utf-8")
            ids.write_text("\n".join(str(o["id"]) for o in antwort["data"]), encoding="utf-8")   # zuletzt: Seite gilt erst dann als fertig
            geholt += 1
            schaetzer.gesamt = geholt + letzte - seite          # schon geholte Seiten zählen nicht zum Tempo
            fortschritt(seite / letzte, f"Seite {seite} von {letzte} geholt · {schaetzer.text(geholt)}")
        seite += 1
    print()

    ids = [z for t in sorted(zwischen.glob("seite_*.ids")) for z in t.read_text(encoding="utf-8").split()]
    jetzt_gesamt = anton_holen("/objects?perPage=1", token)["meta"]["total"]
    if len(ids) != len(set(ids)) or len(set(ids)) != jetzt_gesamt:
        shutil.rmtree(zwischen)
        raise RuntimeError(f"Abruf ungültig: {len(set(ids)):,} verschiedene Objekte geholt ({len(ids) - len(set(ids)):,} doppelt), "
                           f"Anton meldet jetzt {jetzt_gesamt:,}. Anton hat sich während des Abrufs verändert. "
                           "G5b noch einmal ausführen (beginnt neu).")
    df = pd.concat([pd.read_csv(t, dtype=str, keep_default_na=False) for t in sorted(zwischen.glob("seite_*.csv"))],
                   ignore_index=True)
    ziel = P.anton / f"anton_dateien_{datum}_api.csv"
    df.to_csv(ziel, index=False, encoding="utf-8-sig")
    shutil.rmtree(zwischen)
    print(f"✓ {len(set(ids)):,} Objekte, {len(df):,} Anton-Dateien in {ziel.relative_to(P.ordner)}.")
    return ziel


def anton_aus_abgleich(pfad):
    """Excel des ersten Abgleichs (Blätter Hinweise, Ordner, Dateien). Anton-Angaben stehen nur bei Treffern:
    bei „in Anton“ ist die MD5 der Platte auch die der Anton-Datei, bei „gleicher Name, andere Datei“ ist sie unbekannt."""
    hinweise = pd.read_excel(pfad, sheet_name="Hinweise", header=None, dtype=str).fillna("")
    zeile = lambda name: " ".join(hinweise[hinweise[0] == name].iloc[0, 1:]) if (hinweise[0] == name).any() else ""
    x = pd.read_excel(pfad, sheet_name="Dateien", dtype=str)
    x = x[x["Anton-Signatur"].notna()]
    df = pd.DataFrame({"md5": x.md5.where(x.Status == "in Anton", ""), "dateiname": x.Dateiname, "signatur": x["Anton-Signatur"],
                       "titel": x["Anton-Titel"], "anton_datei": x["Anton-Datei"], "link": x["Anton-Link"]})
    df["nur_platten"] = ",".join(sorted(set(re.findall(rf"{re.escape(P.kennung)}\d\d", zeile("Inventar")))))     # welche Platten verglichen wurden
    datum = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", zeile("Anton"))                       # „Stand Datenbank 27.10.2026“
    return df, datum and f"{datum[3]}-{datum[2]}-{datum[1]}"


def anton_lesen(pfad):
    """Liest einen Auszug aus Anton: Excel des ersten Abgleichs, sonst eine Tabelle mit einer Zeile je Anton-Datei.
    Ergebnis: Tabelle mit ANTON_CSV_SPALTEN, das Datum des Dumps (aus der Datei oder dem Dateinamen) und der Zugang."""
    datum = re.search(r"\d{4}-\d{2}-\d{2}", pfad.name)
    datum = datum and datum.group()
    if pfad.name.endswith("_api.csv"):       # eigener API-Abruf: Komma, groß, deshalb direkt lesen
        df = pd.read_csv(pfad, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    elif pfad.suffix.lower() == ".csv":
        df = csv_lesen(pfad)
    elif {"Hinweise", "Dateien"} <= set(pd.ExcelFile(pfad).sheet_names):
        df, datum = anton_aus_abgleich(pfad)
    else:
        df = pd.read_excel(pfad, dtype=str)
    zugang = df.zugang.iloc[0] if "zugang" in df and len(df) else "Auszug"
    df = df.rename(columns=ANTON_SPALTEN)
    fehlt = {"md5", "signatur"} - set(df.columns)
    if fehlt:
        raise ValueError(f"Im Auszug fehlen die Spalten {sorted(fehlt)}. Vorhanden: {list(df.columns)}. "
                         "Zuordnung in G5a (ANTON_SPALTEN) ergänzen.")
    for spalte in ANTON_CSV_SPALTEN:
        if spalte not in df:
            df[spalte] = ""
    df = df[ANTON_CSV_SPALTEN].fillna("").astype(str)
    df["md5"] = df.md5.str.strip().str.lower()
    df["dateiname"] = df.dateiname.map(nfc)
    return df.drop_duplicates().sort_values(["signatur", "dateiname"], ignore_index=True), datum, zugang


def anton_laden(quelle="api", neu_abrufen=False):
    """G5b Bestand von Anton laden. quelle: "api" (vollständiger Abruf) oder Pfad eines Auszugs (Excel/CSV);
    neu_abrufen: True = neuen Stand von Anton holen (ca. 15–20 Minuten), sonst gilt der letzte Abruf."""
    if quelle == "api":
        abrufe = sorted(P.anton.glob("anton_dateien_*_api.csv"))
        if abrufe and not neu_abrufen:
            quelle = abrufe[-1]
            alter = (datetime.now() - datetime.strptime(quelle.name[14:24], "%Y-%m-%d")).days
            print(f"Letzter Abruf aus Anton: {quelle.name} ({alter} Tage alt). Neu holen: neu_abrufen = True in G5a.")
        else:
            platz_pruefen(0.1)                   # CSV und Zwischenseiten zusammen deutlich unter 100 MB
            quelle = anton_abrufen(datetime.now().strftime("%Y-%m-%d"))
    else:
        quelle = Path(quelle)

    df, datum, zugang = anton_lesen(quelle)
    datum = datum or datetime.fromtimestamp(quelle.stat().st_mtime).strftime("%Y-%m-%d")
    ziel = quelle if quelle.suffix.lower() == ".csv" and quelle.name.startswith("anton_dateien_") else P.anton / f"anton_dateien_{datum}.csv"
    if quelle != ziel:
        df.to_csv(ziel, index=False, encoding="utf-8-sig")
    # Stand = Datum und Prüfsumme des Inhalts: ein geänderter Dump gleichen Datums gilt als neuer Stand
    stand = f"{datum}/{hashlib.md5(df.to_csv(index=False).encode()).hexdigest()[:8]}"
    nur_platten = ",".join(sorted({p for w in df.nur_platten for p in w.split(",") if p}))

    zugang_alt = None
    with db() as con:
        alt, zugang_alt = con.execute("SELECT stand, zugang FROM anton_stand WHERE aktuell = 1").fetchone() or (None, None)
        if alt == stand and zugang_alt != zugang:
            # gleiche Dateien, anderer Zugang (z. B. erst ohne, dann mit Token): Zugang nachtragen (Fehler 06.11.2026)
            con.execute("UPDATE anton_stand SET zugang = ? WHERE stand = ?", (zugang, stand))
        if alt != stand:
            con.execute("DELETE FROM anton_datei")
            con.executemany("INSERT INTO anton_datei (stand, md5, dateiname, signatur, titel, anton_datei, link, altsignatur) "
                            "VALUES (?,?,?,?,?,?,?,?)",
                            [(stand, *z) for z in df[ANTON_CSV_SPALTEN[:-1]].itertuples(index=False)])
            con.execute("UPDATE anton_stand SET aktuell = 0")
            con.execute("""INSERT OR REPLACE INTO anton_stand (stand, quelle, csv, dateien, nur_platten, eingelesen_am, aktuell, zugang)
                           VALUES (?,?,?,?,?,?,1,?)""", (stand, nfc(quelle.name), ziel.name, len(df), nur_platten, jetzt(), zugang))
    if alt != stand:
        protokolliere("G5b", "Anton-Auszug", "stand", alt, f"{stand} ({zugang})")
    elif zugang_alt != zugang:
        protokolliere("G5b", "Anton-Auszug", "zugang", zugang_alt, zugang)
    print(f"Bestand aus Anton: {quelle.name}, Stand {stand}, Zugang {zugang} ({'neu geladen' if alt != stand else 'schon geladen'}).")
    print(f"Handliche CSV: {ziel.relative_to(P.ordner)}, {len(df):,} Anton-Dateien, davon {(df.md5 != '').sum():,} mit MD5.")
    if (df.md5 == "").any():
        print(f"  {(df.md5 == '').sum():,} Anton-Dateien ohne MD5 (in Anton nie berechnet): unbekannt, zählen nur beim Namensvergleich.")
    mehrfach = df[df.md5 != ""].md5.value_counts()
    if (mehrfach > 1).any():
        print(f"  {(mehrfach > 1).sum():,} MD5 liegen in Anton mehrfach vor (zusammen {mehrfach[mehrfach > 1].sum():,} Dateien).")
    print("Anton-Bestände:", ", ".join(f"{b} {n:,}" for b, n in
                                       df.signatur.str.extract(r"^(\D*\d+)", expand=False).value_counts().head(15).items()))
    if nur_platten:
        print(f"⚠ Kein vollständiger Dump: „nicht in Anton“ gilt nur für {nur_platten}; übrige Platten bleiben „nicht geprüft“.")
    if zugang == "öffentlich":
        print("⚠ Nur öffentliche Bestände: Dateien in nicht öffentlichen Beständen erscheinen fälschlich als „nicht in Anton“.")
    elif zugang == "mit Token":
        print("Mit Token geholt, aber nicht mehr als öffentlich: Hat das Konto eine interne Rolle, ist der Bestand vollständig.")


def anton_abgleichen():
    """G5c Dateien mit Anton abgleichen (nur neue Dateien, geänderte MD5 oder neuer Stand)."""
    with db() as con:
        aktuell = con.execute("SELECT stand, nur_platten FROM anton_stand WHERE aktuell = 1").fetchone()
        if aktuell is None:
            raise RuntimeError("Noch kein Auszug aus Anton geladen: erst G5a und G5b ausführen.")
        stand, nur_platten = aktuell
        anton = pd.read_sql("SELECT md5, dateiname, signatur, titel, link FROM anton_datei", con).fillna("")
        offen = pd.read_sql("""SELECT d.platte_id, d.relpfad, d.groesse, d.md5 FROM datei d
                               LEFT JOIN anton_abgleich a ON a.platte_id = d.platte_id AND a.relpfad = d.relpfad
                               WHERE d.md5 IS NOT NULL AND (a.stand IS NULL OR a.stand != ? OR a.md5 != d.md5)""",
                            con, params=(stand,))
        alt = dict(con.execute("SELECT status, COUNT(*) FROM anton_abgleich GROUP BY status").fetchall())


    def fundstellen(df, schluessel):
        """Je Schlüssel alle Fundstellen in Anton: Anzahl, Signaturen, Titel und Links (mehrere mit „ | “ getrennt)."""
        df = df.drop_duplicates([schluessel, "link"]).sort_values("signatur")
        return df.groupby(schluessel).agg(treffer=("link", "size"), signatur=("signatur", " | ".join),
                                          titel=("titel", " | ".join), link=("link", " | ".join))


    je_md5 = fundstellen(anton[anton.md5 != ""], "md5")
    je_name = fundstellen(anton[anton.dateiname != ""].assign(name=lambda x: x.dateiname.str.lower()), "name")
    offen["name"] = offen.relpfad.map(lambda p: nfc(os.path.basename(p)).lower())
    abgedeckt = offen.platte_id.isin(nur_platten.split(",")) if nur_platten else pd.Series(True, index=offen.index)
    offen["status"] = np.select(
        [offen.relpfad.map(ist_systemdatei).astype(bool), offen.groesse == 0, offen.md5.isin(je_md5.index),
         offen.name.isin(je_name.index), abgedeckt],
        ["Systemdatei", "leere Datei", "in Anton", "gleicher Name, andere Datei", "nicht in Anton"], "nicht geprüft")
    funde = pd.concat([offen[offen.status == "in Anton"].join(je_md5, on="md5"),
                       offen[offen.status == "gleicher Name, andere Datei"].join(je_name, on="name")])
    offen = offen.join(funde[["treffer", "signatur", "titel", "link"]])
    offen["treffer"] = offen.treffer.astype("Int64")
    werte = offen[["platte_id", "relpfad", "md5", "status", "treffer", "signatur", "titel", "link"]].astype(object)
    werte = werte.where(werte.notna(), None)

    with db() as con:
        con.executemany("INSERT OR REPLACE INTO anton_abgleich VALUES (?,?,?,?,?,?,?,?,?,?)",
                        [(p, r, m, stand, s, t, sig, ti, li, jetzt()) for p, r, m, s, t, sig, ti, li in werte.itertuples(index=False)])
        # Dateien, die nach einem neuen Scan nicht mehr in der Tabelle datei stehen, fallen heraus
        weg = con.execute("""DELETE FROM anton_abgleich WHERE NOT EXISTS (SELECT 1 FROM datei d
                             WHERE d.platte_id = anton_abgleich.platte_id AND d.relpfad = anton_abgleich.relpfad)""").rowcount
        neu = dict(con.execute("SELECT status, COUNT(*) FROM anton_abgleich GROUP BY status").fetchall())
    if len(offen) or weg:
        protokolliere("G5c", f"Anton {stand}", "anton_status", json.dumps(alt, ensure_ascii=False), json.dumps(neu, ensure_ascii=False))
    print(f"Abgeglichen: {len(offen):,} Dateien (alle übrigen sind schon mit Stand {stand} abgeglichen).")
    print("Alle Datenträger:", ", ".join(f"{s} {n:,}" for s, n in sorted(neu.items(), key=lambda x: -x[1])))

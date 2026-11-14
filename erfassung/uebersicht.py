"""I Übersicht über alle Platten: Dashboard (HTML mit Plotly, ohne Server) und Inventar-CSV je Datenträger."""
import base64
import io
from html import escape

from .basis import *  # noqa: F401,F403

# I1 Funktionen: Dashboard sammeln, Formatgruppen, Farben, interaktive Diagramme (Plotly)
import plotly.graph_objects as go
import plotly.io as pio
from PIL import Image, ImageOps
from plotly.offline import get_plotlyjs

TEXTFARBE, LINIENFARBE = "#52514e", "#e4e3df"          # Schrift und Gitter der Diagramme

# Farben: Reihen in fester Reihenfolge; Duplikatarten, Ampel und Datumsstufen überall gleich
FARBEN = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
ARTEN = {"exakt": "exakt gleich", "variante": "Formatvariante", "beinahe": "beinahe gleich"}
ARTFARBEN = {"exakt gleich": FARBEN[0], "Formatvariante": FARBEN[1], "beinahe gleich": FARBEN[2]}
STATUSFARBEN = {"einmalig oder Leitdatei": "#c4c3bd", "überzählig: exakt gleich": FARBEN[0],
                "überzählig: Formatvariante": FARBEN[1], "überzählig: beinahe gleich": FARBEN[2], "Systemdatei": "#8a8984"}
AMPELFARBEN = {"grün": "#0ca30c", "gelb": "#fab219", "rot": "#d03b3b"}
ANTONFARBEN = {"in Anton": FARBEN[2], "gleicher Name, andere Datei": FARBEN[3], "nicht in Anton": "#c4c3bd",
               "nicht geprüft": "#e4e3df", "noch nicht abgeglichen": FARBEN[7], "leere Datei": "#8a8984"}
DATUMSQUELLEN = ["EXIF", "XMP/IPTC", "Dokument", "Dateiname", "Ordnername", "Dateisystem"]
DATUMSSTUFE = {"EXIF": "eingebettete Metadaten", "XMP/IPTC": "eingebettete Metadaten", "Dokument": "eingebettete Metadaten",
               "Dateiname": "Datei- oder Ordnername", "Ordnername": "Datei- oder Ordnername", "Dateisystem": "Dateisystem"}
STUFENFARBEN = {"eingebettete Metadaten": "#104281", "Datei- oder Ordnername": "#3987e5", "Dateisystem": "#86b6ef"}
BLAU = [[0, "#f4f8fd"], [0.5, "#86b6ef"], [1, "#184f95"]]

# Formatgruppe: erste passende Zeile gilt (Suchmuster auf MIME-Typ und Formatname)
FORMATGRUPPEN = [
    ("Kamera-RAW", r"Raw|RAW|Digital Negative"),       # Groß-/Kleinschreibung zählt („Drawing“ ist kein RAW)
    ("Bild", r"^image/|Photoshop"),
    ("PDF", r"application/pdf|Portable Document"),
    ("Office", r"msword|ms-excel|ms-powerpoint|officedocument|opendocument|rtf|Word|Excel|Powerpoint"),
    ("Grafik und Layout", r"postscript|Quark|InDesign|Illustrator|Corel|FreeHand|PageMaker|AutoCAD|Visio"),
    ("Web", r"text/html|text/css|javascript|Front Page|MHTML"),
    ("Video und Audio", r"^video/|^audio/|MPEG|Quicktime|Windows Media|Interleaved|Waveform"),
    ("Archivdatei", r"zip|stuffit|rar|tar|gzip"),
    ("Text", r"^text/"),
    ("Schrift", r"font|Font"),
]

# Vorlage für alle Diagramme: ruhige Achsen, deutsche Zahlen (1.234,5), Legende oben links
pio.templates["balduin"] = go.layout.Template(layout=dict(
    font=dict(family="-apple-system, system-ui, sans-serif", size=12, color=TEXTFARBE),
    paper_bgcolor="#ffffff", plot_bgcolor="#ffffff", colorway=FARBEN, separators=",.",
    title=dict(font=dict(size=14, color="#1f1f1d"), x=0, xanchor="left"), margin=dict(l=10, r=10, t=70, b=10),
    xaxis=dict(gridcolor=LINIENFARBE, zeroline=False, automargin=True),
    yaxis=dict(gridcolor=LINIENFARBE, zeroline=False, automargin=True),
    legend=dict(orientation="h", x=0, y=1.0, yanchor="bottom", traceorder="normal"), bargap=0.3, hoverlabel=dict(font_size=12)))
pio.templates.default = "plotly_white+balduin"
KONFIG = {"displaylogo": False, "responsive": True}

REITER = ["Überblick", "Dubletten", "Anton", "Bestand", "Metadaten", "Archivfähigkeit", "Probleme", "Datenträger und Protokoll"]
dashboard = {r: {} for r in REITER}   # Reiter → Titel → (Text, HTML, breit); eine Zelle erneut ausführen ersetzt ihren Teil
beilagen = {}                         # Daten für Tabellen, Treemap und Gruppen-Explorer (JSON), I9 bettet sie ein


def de(zahl, stellen=0):
    """Zahl mit deutschen Trennzeichen: 12345.6 → „12.345,6“."""
    return f"{zahl:,.{stellen}f}".replace(",", " ").replace(".", ",").replace(" ", ".")


def als_json(daten):
    """JSON zum Einbetten in die Seite; „</“ wird maskiert, damit kein Dateiname das Skript beenden kann."""
    return json.dumps(daten, ensure_ascii=False, separators=(",", ":"), allow_nan=False,   # NaN ist kein gültiges JSON
                      default=lambda x: x.item() if hasattr(x, "item") else str(x)).replace("</", "<\\/")


def tabelle_html(df, schluessel, klick=None):
    """Interaktive Tabelle im Dashboard (Suche, Sortieren, Filter nach Spalte „Platte“); gezeichnet von dashboard.js."""
    if df.index.name or isinstance(df.index, pd.MultiIndex):
        df = df.reset_index()
    zeilen = df.astype(object).where(df.notna(), None).values.tolist()
    beilagen[schluessel] = als_json({"spalten": [str(s) for s in df.columns], "zeilen": zeilen, "klick": klick,
                                     "zahlen": [bool(pd.api.types.is_numeric_dtype(df[s])) for s in df.columns]})
    return f'<div class="bd-tabelle-behaelter" data-quelle="{schluessel}"></div>'


def teil(reiter, titel, inhalt, text="", breit=True, klick=None):
    """Merkt einen Teil für das Dashboard (I9) vor.
    inhalt: Plotly-Diagramm, Tabelle (DataFrame, im Dashboard durchsuchbar) oder HTML.
    breit=False: im Dashboard halbe Breite."""
    schluessel = "t" + hashlib.sha1(f"{reiter}|{titel}".encode()).hexdigest()[:10]
    if isinstance(inhalt, go.Figure):
        html = inhalt.to_html(full_html=False, include_plotlyjs=False, config=KONFIG, div_id=schluessel)
    elif isinstance(inhalt, pd.DataFrame):
        html = tabelle_html(inhalt, schluessel, klick)
    else:
        html = inhalt
    dashboard[reiter][titel] = (text, html, breit)


def kennzahlen(liste):
    """Kennzahlen als Kacheln; liste: (Wert, Name, Zusatz)."""
    kacheln = "".join(f'<div class="col-6 col-md-4 col-xl"><div class="bd-kennzahl"><div class="wert">{escape(str(w))}</div>'
                      f'<div class="name">{escape(n)}</div><div class="zusatz">{escape(z)}</div></div></div>'
                      for w, n, z in liste)
    return f'<div class="row g-3">{kacheln}</div>'


def formatgruppe(df):
    gruppe = pd.Series("Sonstiges", index=df.index)
    frei = pd.Series(True, index=df.index)
    for name, muster in FORMATGRUPPEN:
        treffer = frei & (df.mime.fillna("").str.contains(muster) | df.format.fillna("").str.contains(muster))
        gruppe[treffer] = name
        frei &= ~treffer
    gruppe[df.puid.isna() | (df.puid == "UNKNOWN")] = "nicht erkannt"
    gruppe[df.relpfad.map(ist_systemdatei).astype(bool)] = "Systemdatei"
    return gruppe


# Die folgenden Rechnungen nutzen das Dashboard hier und das Dashboard des Tools (erfassung/dashboard.py)
def duplikat_spalten(alle, gruppen):
    """Je Datei: zu welcher Gruppe gehört sie (exakt vor variante vor beinahe: dup_art, dup_gruppe, dup_leit),
    und wo ist sie überzählig (ueberz_art)? gruppen: Spalten art, gruppe_id, platte_id, relpfad, leitdatei."""
    rang = gruppen.assign(rang=gruppen.art.map({"exakt": 0, "variante": 1, "beinahe": 2})).sort_values("rang")
    mitglied = (rang.drop_duplicates(["platte_id", "relpfad"])
                .rename(columns={"art": "dup_art", "gruppe_id": "dup_gruppe", "leitdatei": "dup_leit"})
                [["platte_id", "relpfad", "dup_art", "dup_gruppe", "dup_leit"]])
    ueberzaehlig = (rang[rang.leitdatei == 0].drop_duplicates(["platte_id", "relpfad"])
                    .rename(columns={"art": "ueberz_art"})[["platte_id", "relpfad", "ueberz_art"]])
    return alle.merge(mitglied, on=["platte_id", "relpfad"], how="left").merge(ueberzaehlig, on=["platte_id", "relpfad"], how="left")


def treemap_daten(alle):
    """Treemap „Wo liegen die Duplikate?“: jede Datei ein Rechteck, Daten kompakt als Listen.
    alle braucht ordner, name, system und die Spalten aus duplikat_spalten(). Je Datei:
    [Ordnernummer, Name, Bytes, Art (0 einmalig, 1 exakt, 2 variante, 3 beinahe, 4 Systemdatei), überzählig, Gruppennummer]."""
    tm = alle[alle.groesse > 0]
    ordner_voll = tm.platte_id + tm.ordner.map(lambda o: "/" + o if o else "")
    ordnerliste = sorted(ordner_voll.unique())
    ordnernummer = {o: i for i, o in enumerate(ordnerliste)}
    gruppenliste = sorted(tm.dup_gruppe.dropna().unique())
    gruppennummer = {gid: i for i, gid in enumerate(gruppenliste)}
    art_code = tm.dup_art.map({"exakt": 1, "variante": 2, "beinahe": 3}).fillna(tm.system.map({True: 4, False: 0})).astype(int)
    return {"ordner": ordnerliste, "gruppen": [str(g) for g in gruppenliste],
            "dateien": [list(z) for z in zip(ordner_voll.map(ordnernummer).astype(int).tolist(), tm.name.tolist(),
                                             tm.groesse.astype(int).tolist(), art_code.tolist(),
                                             (tm.dup_art.notna() & (tm.dup_leit == 0)).astype(int).tolist(),
                                             tm.dup_gruppe.map(gruppennummer).fillna(-1).astype(int).tolist())]}


def gemeinsame_ebenen(a, b):
    """Wie viele Ordnerebenen zwei Pfade (als Tupel) von oben gemeinsam haben: ("A", "B") und ("A", "C") → 1."""
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def anderswo(mitglieder):
    """Je Datei (Platte, Pfad): Ebene, ab der ein anderes Exemplar derselben Platte außerhalb liegt, und die
    anderen Platten mit Exemplaren. Liegt das andere Exemplar in „A/C“ und die Datei in „A/B“, zählt sie für
    „A/B“ als anderswo vorhanden, für „A“ und die ganze Platte nicht (dort liegt beides drin): Ebene 1."""
    je_gruppe = {}
    for gid, p, r, teile in zip(mitglieder.gruppe_id, mitglieder.platte_id, mitglieder.relpfad, mitglieder.teile):
        je_gruppe.setdefault(gid, []).append((p, r, teile))
    ebene, platten = {}, {}
    for liste in je_gruppe.values():
        alle_platten = {p for p, _, _ in liste}
        ordner = {}
        for p, _, teile in liste:
            ordner.setdefault(p, set()).add(teile)
        ordner = {p: sorted(o) for p, o in ordner.items()}
        for p, r, teile in liste:
            if len(alle_platten) > 1:
                platten.setdefault((p, r), set()).update(alle_platten - {p})
            o = ordner[p]
            if len(o) > 1:
                # Sortiert teilt ein Ordner am wenigsten mit dem ersten oder letzten der übrigen Ordner
                uebrige = [x for x in (o[0], o[1], o[-2], o[-1]) if x != teile]
                k = min(gemeinsame_ebenen(teile, x) for x in uebrige)
                ebene[(p, r)] = min(k, ebene.get((p, r), k))
    return ebene, platten


BAUMSPALTEN = ["dateien", "direkt", "bytes", "ex_gleich", "ex_gleich_b", "ex_andere", "ex_andere_b",
               "al_gleich", "al_gleich_b", "al_andere", "al_andere_b"]


def ordnerbaum(bestand, gruppen):
    """Ordnerbaum je Datenträger: je Ordner (mit Unterordnern) Dateien, Bytes und wie viele davon auch in einem anderen
    Ordner derselben Platte (gleich) oder auf anderen Platten (andere) liegen; ex = nur exakt gleich, al = alle Arten,
    _b = Bytes. bestand ohne Systemdateien, mit Spalte ordner. Ergebnis: {Platte: (Tabelle, Einträge fürs Dashboard)};
    Einträge = [Name, Eltern, *BAUMSPALTEN, ex_platten, al_platten], Eltern stehen vor ihren Kindern."""
    dateien = bestand.loc[bestand.groesse > 0, ["platte_id", "relpfad", "ordner", "groesse"]].copy()   # wie G: leere Dateien zählen nicht
    dateien["teile"] = dateien.ordner.map(lambda o: tuple(o.split("/")) if o else ())
    m = gruppen[["art", "gruppe_id", "platte_id", "relpfad"]].merge(dateien, on=["platte_id", "relpfad"])
    schluessel = list(zip(dateien.platte_id, dateien.relpfad))
    for kurz, arten in (("ex", ["exakt"]), ("al", list(ARTEN))):       # nur exakt gleich / alle Duplikatarten
        ebene, andere_platten = anderswo(m[m.art.isin(arten)])
        dateien[f"{kurz}_ebene"] = [ebene.get(s, 999) for s in schluessel]
        dateien[f"{kurz}_platten"] = [andere_platten.get(s, set()) for s in schluessel]

    # Jede Datei zählt für ihren Ordner und alle Ordner darüber (Ebene 0 = ganze Platte)
    z = dateien.assign(e=dateien.teile.map(lambda t: list(range(len(t) + 1)))).explode("e")
    z["e"] = z.e.astype(int)
    z["ort"] = [t[:e] for t, e in zip(z.teile, z.e)]
    z["direkt"] = z.e == z.teile.map(len)
    spalten = {"dateien": ("relpfad", "size"), "direkt": ("direkt", "sum"), "bytes": ("groesse", "sum")}
    for kurz in ("ex", "al"):
        z[f"{kurz}_gleich"] = z[f"{kurz}_ebene"] < z.e                  # ein Exemplar liegt außerhalb dieses Ordners
        z[f"{kurz}_andere"] = z[f"{kurz}_platten"].map(bool)
        for wo in ("gleich", "andere"):
            z[f"{kurz}_{wo}_b"] = z.groesse * z[f"{kurz}_{wo}"]
            spalten[f"{kurz}_{wo}"] = (f"{kurz}_{wo}", "sum")
            spalten[f"{kurz}_{wo}_b"] = (f"{kurz}_{wo}_b", "sum")
        spalten[f"{kurz}_platten"] = (f"{kurz}_platten", lambda s: ", ".join(sorted(set().union(*s))))
    baum = z.groupby(["platte_id", "ort"]).agg(**spalten).reset_index()

    ergebnis = {}
    for platte_id, b in baum.groupby("platte_id"):
        b = b.sort_values("ort").reset_index(drop=True)              # Eltern stehen vor ihren Kindern
        nummer = {o: i for i, o in enumerate(b.ort)}
        eintraege = [[o[-1] if o else platte_id, nummer[o[:-1]] if o else -1, *map(int, zahlen), ex_p, al_p]
                     for o, zahlen, ex_p, al_p in zip(b.ort, b[BAUMSPALTEN].values, b.ex_platten, b.al_platten)]
        ergebnis[platte_id] = (b, eintraege)
    return ergebnis


def balken_plotly(tabellen, titel, farben=None, waagerecht=True, hoehe=None):
    """Gestapelte Balken. tabellen: {"Dateien": df, "GB": df}; Index = Balken, Spalten = Teile des Stapels.
    Bei mehreren Tabellen schalten Knöpfe oben rechts um. Eine Series zählt als Tabelle mit einem Teil."""
    tabellen = {n: (t.to_frame(n) if isinstance(t, pd.Series) else t) for n, t in tabellen.items()}
    namen = list(tabellen)
    erste = tabellen[namen[0]]
    teile = list(erste.columns)
    achse, wertachse = ("y", "x") if waagerecht else ("x", "y")
    beschriftung = [kuerzen(str(i), 50) for i in erste.index] if waagerecht else list(erste.index)

    def hinweis(teil_name, tabelle_name):
        zahl = "%{" + wertachse + (":,.2f}" if tabelle_name == "GB" else ":,.0f}")
        vorne = "%{" + achse + "}" + ("" if teil_name == tabelle_name else f"<br>{teil_name}")
        return f"{vorne}: {zahl} {tabelle_name}<extra></extra>"

    fig = go.Figure()
    for k, t in enumerate(teile):
        fig.add_bar(**{achse: beschriftung, wertachse: erste[t].fillna(0).values}, orientation="h" if waagerecht else "v",
                    name=str(t), hovertemplate=hinweis(t, namen[0]),
                    marker=dict(color=(farben or {}).get(t, FARBEN[k % len(FARBEN)]), line=dict(color="#ffffff", width=1)))
    if len(namen) > 1:
        knoepfe = [dict(label=n, method="restyle", args=[{wertachse: [tabellen[n][t].fillna(0).values for t in teile],
                                                          "hovertemplate": [hinweis(t, n) for t in teile]}]) for n in namen]
        fig.update_layout(updatemenus=[dict(type="buttons", direction="right", buttons=knoepfe, showactive=True,
                                            x=1, xanchor="right", y=1.0, yanchor="bottom", pad=dict(b=6))])
    fig.update_layout(title=titel, barmode="stack", showlegend=len(teile) > 1,
                      height=hoehe or (26 * len(beschriftung) + 130 if waagerecht else 380))
    if waagerecht:
        fig.update_yaxes(autorange="reversed", showgrid=False)
    else:
        fig.update_xaxes(showgrid=False)
    return fig


def waermebild(tabelle, titel, einheit="%", hoechstwert=100):
    """Tabelle als Farbfläche (hell = wenig, dunkel = viel) mit Zahlen in den Feldern."""
    fig = go.Figure(go.Heatmap(z=tabelle.values, x=[str(s) for s in tabelle.columns], y=[str(i) for i in tabelle.index],
                               colorscale=BLAU, zmin=0, zmax=hoechstwert, xgap=2, ygap=2, texttemplate="%{z:.0f}",
                               hovertemplate="%{y} · %{x}: %{z:.0f} " + einheit + "<extra></extra>",
                               colorbar=dict(thickness=10, title=einheit)))
    fig.update_layout(title=titel, height=34 * len(tabelle) + 160)
    fig.update_yaxes(autorange="reversed", showgrid=False)
    fig.update_xaxes(showgrid=False, side="top")
    return fig


def dashboard_erstellen():
    """I2–I9 Daten aller Platten laden, Dashboard und Inventar-CSV je Datenträger speichern. Ergebnis: Pfad des Dashboards."""
    dashboard.clear()
    beilagen.clear()
    dashboard.update({r: {} for r in REITER})
    with db() as con:
        alle = pd.read_sql("""
            SELECT d.platte_id, d.relpfad, d.groesse, d.mtime, d.sha256, d.md5, d.puid, d.format, d.formatversion, d.mime,
                   d.hash_fehler, d.sf_warnung, d.sf_fehler,
                   m.datum, m.datum_quelle, m.hersteller, m.kamera, m.urheber, m.copyright, m.titel, m.beschreibung,
                   m.schlagworte, m.aufnahme, m.software, m.gps_breite, m.gps_laenge, m.fehler AS exif_fehler,
                   COALESCE(m.breite, v.breite) AS breite, COALESCE(m.hoehe, v.hoehe) AS hoehe,
                   a.ampel, a.grund, a.massnahme, a.nara_id, a.nara_kategorie, a.nara_risiko, a.nara_massnahme, a.nara_plan,
                   v.datei AS vorschau, v.art AS v_art, v.quelle AS v_quelle, v.fehler AS v_fehler,
                   an.status AS anton_status, an.treffer AS anton_treffer, an.signatur AS anton_signatur,
                   an.titel AS anton_titel, an.link AS anton_link, vs.befund AS viren_befund, vs.meldung AS viren_meldung
            FROM datei d
            LEFT JOIN metadaten m ON m.platte_id = d.platte_id AND m.relpfad = d.relpfad
            LEFT JOIN archiv a ON a.platte_id = d.platte_id AND a.relpfad = d.relpfad
            LEFT JOIN vorschau v ON v.sha256 = d.sha256
            LEFT JOIN anton_abgleich an ON an.platte_id = d.platte_id AND an.relpfad = d.relpfad
            LEFT JOIN virenscan vs ON vs.sha256 = d.sha256""", con)
        platten = pd.read_sql("SELECT * FROM platte ORDER BY platte_id", con)
        gruppen = pd.read_sql("SELECT art, gruppe_id, platte_id, relpfad, leitdatei FROM gruppe", con)
        ordnergruppen = pd.read_sql("SELECT * FROM ordnergruppe", con)
        scanlaeufe = pd.read_sql("SELECT * FROM scanlauf ORDER BY lauf_id", con)
        scanfehler = pd.read_sql("SELECT * FROM scanfehler", con)
        protokoll = pd.read_sql("SELECT * FROM protokoll ORDER BY zeit DESC", con)
        anton_stand = pd.read_sql("SELECT * FROM anton_stand WHERE aktuell = 1", con)

    # herausgenommene Platten (Tool, Entscheidung 30.10.2026) zählen nicht mit; ihre Daten bleiben in der Datenbank
    platten = platten[platten.deaktiviert_am.isna()]
    alle, gruppen, ordnergruppen, scanfehler = (t[t.platte_id.isin(platten.platte_id)]
                                                for t in (alle, gruppen, ordnergruppen, scanfehler))
    alle["gruppe"] = formatgruppe(alle)
    alle["system"] = alle.gruppe == "Systemdatei"
    alle["ordner"] = alle.relpfad.map(os.path.dirname)
    alle["name"] = alle.relpfad.map(os.path.basename)
    alle["endung"] = (alle.name.str.extract(r"\.([^.]+)$", expand=False).str.lower().fillna("(ohne)")
                      .replace({"jpeg": "jpg", "tiff": "tif"}))

    # Duplikate je Datei: zu welcher Gruppe gehört sie (exakt vor variante vor beinahe), und wo ist sie überzählig?
    alle = duplikat_spalten(alle, gruppen)
    alle["status"] = np.where(alle.system, "Systemdatei",
                              np.where(alle.ueberz_art.notna(), "überzählig: " + alle.ueberz_art.map(ARTEN).fillna(""),
                                       "einmalig oder Leitdatei"))
    bestand = alle[~alle.system]
    print(f"{len(alle):,} Dateien auf {alle.platte_id.nunique()} Platten, {alle.groesse.sum() / 1e9:,.1f} GB; "
          f"{gruppen.gruppe_id.nunique():,} Dublettengruppen, {len(ordnergruppen.gruppe_id.unique()):,} mehrfach vorhandene Ordner.")
    gb = lambda s: s.sum() / 1e9
    exakt_weg = bestand[bestand.ueberz_art == "exakt"]
    kandidaten = bestand[bestand.ueberz_art.isin(["variante", "beinahe"])]
    bleibt = bestand[bestand.ueberz_art != "exakt"]
    ampel = bestand.ampel.value_counts(normalize=True) * 100
    datiert = bestand.datum_quelle.map(DATUMSSTUFE)
    zahlen = [
        (de(alle.platte_id.nunique()), "Platten", ", ".join(sorted(alle.platte_id.unique()))),
        (de(len(bestand)), "Dateien", f"{de(gb(bestand.groesse), 1)} GB, ohne {de(alle.system.sum())} Systemdateien"),
        (f"{de(gb(exakt_weg.groesse), 1)} GB", "bitgleiche Kopien", f"{de(len(exakt_weg))} überzählige Dateien"),
        (f"{de(gb(kandidaten.groesse), 1)} GB", "weitere Kandidaten", f"{de(len(kandidaten))} Formatvarianten und beinahe gleiche"),
        (f"{de(gb(bleibt.groesse), 1)} GB", "bleibt ohne bitgleiche Kopien", f"{de(len(bleibt))} Dateien"),
        (f"{de(ampel.get('grün', 0))} %", "archivfähig (grün)", f"gelb {de(ampel.get('gelb', 0))} %, rot {de(ampel.get('rot', 0))} %"),
        (f"{de((datiert != 'Dateisystem').mean() * 100 if datiert.notna().any() else 0)} %", "datiert aus Datei oder Name",
         "sonst nur Datum des Dateisystems"),
    ]
    if len(anton_stand):
        in_anton = bestand[bestand.anton_status == "in Anton"]
        zahlen.insert(4, (de(len(in_anton)), "schon in Anton",
                          f"{de(gb(in_anton.groesse), 1)} GB, Auszug vom {anton_stand.stand[0].split('/')[0]}"))
    teil("Überblick", "Kennzahlen", kennzahlen(zahlen))

    dateien = alle.pivot_table(index="platte_id", columns="status", values="relpfad", aggfunc="size", fill_value=0)
    volumen = alle.pivot_table(index="platte_id", columns="status", values="groesse", aggfunc="sum", fill_value=0) / 1e9
    reihenfolge = [s for s in STATUSFARBEN if s in dateien]
    teil("Überblick", "Was liegt auf jedem Datenträger?",
         balken_plotly({"GB": volumen[reihenfolge], "Dateien": dateien[reihenfolge]}, "Datenträger nach Dublettenstatus",
                       STATUSFARBEN, hoehe=60 * len(dateien) + 150),
         "Grau bleibt (einmalig oder Leitdatei ihrer Gruppe); farbig ist überzählig: Kopien ohne Leitdatei. "
         "Knöpfe oben rechts: GB oder Dateien.")

    formate = bestand.pivot_table(index="gruppe", columns="status", values="groesse", aggfunc="sum", fill_value=0) / 1e9
    formate = formate.loc[formate.sum(axis=1).sort_values(ascending=False).index]
    teil("Überblick", "Formatgruppen und Dubletten",
         balken_plotly({"GB": formate[[s for s in STATUSFARBEN if s in formate]]}, "GB je Formatgruppe", STATUSFARBEN))
    assert len(gruppen), "Noch keine Dublettengruppen: erst G und H ausführen."
    og_ordner = set(zip(ordnergruppen.platte_id, ordnergruppen.ordner))


    def in_ordnergruppe(platte_id, ordner):
        """Liegt der Ordner (oder einer darüber) als Ganzes mehrfach vor (G1)? "" steht für die ganze Platte."""
        teile = ordner.split("/") if ordner else []
        return any((platte_id, "/".join(teile[:i])) in og_ordner for i in range(len(teile) + 1))


    g = gruppen.merge(alle[["platte_id", "relpfad", "groesse", "endung", "format", "formatversion", "breite", "hoehe",
                            "ampel", "vorschau", "ordner", "name"]], on=["platte_id", "relpfad"])
    g["im_ordner"] = [in_ordnergruppe(p, o) for p, o in zip(g.platte_id, g.ordner)]
    g["masse"] = g.breite.astype("Int64").astype(str) + "×" + g.hoehe.astype("Int64").astype(str)
    g["ueberz"] = (g.leitdatei == 0).astype(int)
    g["ueberz_bytes"] = g.groesse * g.ueberz
    g["fundort"] = g.platte_id + ": " + g.relpfad

    je_gruppe = g.groupby(["art", "gruppe_id"]).agg(
        dateien=("relpfad", "size"), platten=("platte_id", lambda p: ", ".join(sorted(set(p)))), anzahl_platten=("platte_id", "nunique"),
        ordner=("ordner", "nunique"), namen=("name", "nunique"), im_ordner=("im_ordner", "all"), masse=("masse", "nunique"),
        formate=("endung", lambda e: " + ".join(sorted(set(e)))), anzahl_formate=("endung", "nunique"),
        ueberz_dateien=("ueberz", "sum"), ueberz_bytes=("ueberz_bytes", "sum")).reset_index()
    leit = g[g.leitdatei == 1].drop_duplicates(["art", "gruppe_id"]).set_index(["art", "gruppe_id"]).fundort
    je_gruppe["leitdatei"] = [leit.get((a, i), "") for a, i in zip(je_gruppe.art, je_gruppe.gruppe_id)]

    # Warum doppelt? Eine Antwort je Gruppe, die erste zutreffende Bedingung gilt
    exakt, variante = je_gruppe.art == "exakt", je_gruppe.art == "variante"
    je_gruppe["grund"] = np.select(
        [exakt & je_gruppe.im_ordner, exakt & (je_gruppe.anzahl_platten > 1), exakt & (je_gruppe.ordner == 1),
         exakt & (je_gruppe.namen == 1), exakt, variante, je_gruppe.anzahl_formate > 1, je_gruppe.masse > 1],
        ["ganzer Ordner mehrfach", "auf mehreren Datenträgern", "gleicher Ordner, anderer Name", "gleicher Name, anderer Ordner",
         "anderer Name und Ordner", "Formate " + je_gruppe.formate, "anderes Format: " + je_gruppe.formate, "andere Pixelgröße"],
        "gleiche Pixelgröße (neu gespeichert oder bearbeitet)")
    print(f"{len(je_gruppe):,} Gruppen beschrieben. Gründe:")
    zeige(je_gruppe.groupby(["art", "grund"]).size().rename("gruppen").sort_values(ascending=False).head(20).to_frame())
    gb = lambda s: s.sum() / 1e9
    gruppen_je_art = je_gruppe.groupby("art")
    zahlen = [(de(gruppen_je_art.size().get(a, 0)), f"Gruppen {ARTEN[a]}",
               f"{de(gruppen_je_art.ueberz_dateien.sum().get(a, 0))} überzählige Dateien, "
               f"{de(gruppen_je_art.ueberz_bytes.sum().get(a, 0) / 1e9, 1)} GB") for a in ARTEN]
    if len(ordnergruppen):
        og = ordnergruppen.groupby("gruppe_id").agg(kopien=("ordner", "size"), bytes=("bytes", "first"))
        zahlen.append((de(len(og)), "Ordner mehrfach", f"{de(((og.kopien - 1) * og.bytes).sum() / 1e9, 1)} GB überzählig"))
    teil("Dubletten", "Dubletten in Zahlen", kennzahlen(zahlen),
         "Stufen überschneiden sich (eine Datei kann exakt gleich und zugleich beinahe gleich sein), daher nicht addieren.")

    # Wo? Treemap: jede Datei ein Rechteck (gezeichnet von dashboard.js), Daten kompakt als Listen
    beilagen["treemap"] = als_json(treemap_daten(alle))

    je_ordner = (bestand.assign(ueberz=bestand.ueberz_art.notna(), ueberz_bytes=bestand.groesse * bestand.ueberz_art.notna())
                 .groupby(["platte_id", "ordner"]).agg(dateien=("relpfad", "size"), ueberz=("ueberz", "sum"),
                                                       gb=("groesse", gb), ueberz_gb=("ueberz_bytes", gb),
                                                       arten=("ueberz_art", lambda a: ", ".join(ARTEN[x] for x in sorted(set(a.dropna())))))
                 .reset_index().query("ueberz > 0"))
    je_ordner["Anteil %"] = (je_ordner.ueberz / je_ordner.dateien * 100).round(0)
    je_ordner = (je_ordner.sort_values("ueberz_gb", ascending=False)
                 .assign(gb=lambda x: x.gb.round(2), ueberz_gb=lambda x: x.ueberz_gb.round(2), ordner=lambda x: x.ordner.replace("", "(oberste Ebene)"))
                 [["platte_id", "ordner", "dateien", "ueberz", "Anteil %", "gb", "ueberz_gb", "arten"]]
                 .rename(columns={"platte_id": "Platte", "ordner": "Ordner", "dateien": "Dateien", "ueberz": "überzählig",
                                  "gb": "GB", "ueberz_gb": "überzählig GB", "arten": "Art"}))
    teil("Dubletten", "Wo liegen die Dubletten?", '<div class="bd-treemap" data-quelle="treemap"></div>',
         "Jede Datei ist ein Rechteck (Fläche = Größe), Ordner sind umrandet; gefärbt sind zunächst nur überzählige Kopien. "
         "Ein einfarbiger Block: ganzer Ordner doppelt; "
         "verstreute Flecken: einzelne Dateien. Maus auf eine Datei: die anderen Exemplare ihrer Gruppe werden rot umrandet. "
         "Klick: in den Ordner zoomen; zurück über die Pfadleiste.")
    teil("Dubletten", "Ordner mit überzähligen Dateien", je_ordner,
         "Je Ordner (ohne Unterordner): wie viele Dateien dort überzählig sind und warum. Spaltenkopf anklicken zum Sortieren.")

    # Warum? Gründe je Art; seltene Formatkombinationen zusammenfassen
    gruende = je_gruppe.copy()
    haeufig = gruende.groupby(["art", "grund"]).ueberz_dateien.sum().groupby(level=0, group_keys=False).nlargest(8).index
    gruende.loc[[(a, gr) not in haeufig for a, gr in zip(gruende.art, gruende.grund)], "grund"] = "übrige Kombinationen"
    gruende["Art"] = gruende.art.map(ARTEN)
    gruende["sortierung"] = gruende.art.map({"exakt": 0, "variante": 1, "beinahe": 2})
    zusammen = gruende.groupby(["sortierung", "Art", "grund"]).agg(
        gruppen=("gruppe_id", "size"), dateien=("ueberz_dateien", "sum"), gb=("ueberz_bytes", gb)).reset_index()
    zusammen = zusammen.sort_values(["sortierung", "dateien"], ascending=[True, False])
    zusammen["zeile"] = zusammen.grund
    doppelt = zusammen.duplicated("zeile", keep=False)        # z. B. „übrige Kombinationen“ bei zwei Arten: getrennte Balken
    zusammen.loc[doppelt, "zeile"] = zusammen.grund + " (" + zusammen.Art + ")"
    teil("Dubletten", "Warum doppelt?",
         balken_plotly({"Dateien": zusammen.pivot_table(index="zeile", columns="Art", values="dateien", sort=False),
                        "GB": zusammen.pivot_table(index="zeile", columns="Art", values="gb", sort=False)},
                       "Überzählige Dateien nach Grund", ARTFARBEN),
         "exakt gleich: wie die Kopie entstanden ist; Formatvariante: welche Formate derselben Aufnahme; "
         "beinahe gleich: was sich unterscheidet. Gezählt sind überzählige Dateien (ohne Leitdatei).", breit=False)
    teil("Dubletten", "Gründe als Tabelle",
         zusammen[["Art", "grund", "gruppen", "dateien", "gb"]].round({"gb": 2})
         .rename(columns={"grund": "Grund", "gruppen": "Gruppen", "dateien": "überzählige Dateien", "gb": "überzählig GB"}),
         breit=False)

    # Zwischen Platten: Anteil gemeinsamer Inhalte
    if bestand.platte_id.nunique() > 1:
        inhalte = bestand[bestand.sha256.notna() & (bestand.groesse > 0)].drop_duplicates(["platte_id", "sha256"])
        paare = inhalte[["platte_id", "sha256"]].merge(inhalte[["platte_id", "sha256"]], on="sha256")
        matrix = pd.crosstab(paare.platte_id_x, paare.platte_id_y)
        teil("Dubletten", "Gemeinsame Inhalte zwischen Datenträgern",
             waermebild(matrix.div(np.diag(matrix), axis=0) * 100, "Anteil der Inhalte von Zeile A, die auch auf Spalte B liegen"),
             "100 % in einer Zeile: dieser Datenträger liegt vollständig auch auf dem anderen (Backup oder Klon).")

    # Ganze Ordner, die mehrfach vorliegen (G1), und Ordnerpaare mit teilweise gleichem Inhalt
    if len(ordnergruppen):
        o = ordnergruppen.assign(fundort=ordnergruppen.platte_id + ": " + ordnergruppen.ordner.replace("", "(ganzer Datenträger)"))
        o = o.groupby("gruppe_id").agg(kopien=("fundort", "size"), dateien=("dateien", "first"), bytes=("bytes", "first"),
                                       fundorte=("fundort", lambda f: "\n".join(sorted(f)))).reset_index()
        o["GB"] = (o.bytes / 1e9).round(2)
        o["überzählig GB"] = (o.bytes * (o.kopien - 1) / 1e9).round(2)
        teil("Dubletten", "Ordner, die als Ganzes mehrfach vorliegen",
             o.sort_values("überzählig GB", ascending=False)[["kopien", "dateien", "GB", "überzählig GB", "fundorte"]]
             .rename(columns={"kopien": "Kopien", "dateien": "Dateien", "fundorte": "Fundorte"}),
             "Gleicher Inhalt mit allen Unterordnern, egal unter welchem Namen; nur die oberste Ebene.")

    ex = g[g.art == "exakt"].assign(ort=lambda x: x.platte_id + ": " + x.ordner.replace("", "(oberste Ebene)"))
    dateien_je_ort = (bestand.platte_id + ": " + bestand.ordner.replace("", "(oberste Ebene)")).value_counts()
    orte = ex.drop_duplicates(["gruppe_id", "ort"])
    orte = orte[orte.groupby("gruppe_id").ort.transform("size").between(2, 20)]        # sehr häufige Inhalte (Logos) auslassen
    op = orte[["gruppe_id", "ort"]].merge(orte[["gruppe_id", "ort"]], on="gruppe_id").query("ort_x < ort_y")
    if len(op):
        op = op.groupby(["ort_x", "ort_y"]).size().rename("gleich").reset_index().sort_values("gleich", ascending=False).head(500)
        op["Anteil A %"] = (op.gleich / op.ort_x.map(dateien_je_ort) * 100).round(0)
        op["Anteil B %"] = (op.gleich / op.ort_y.map(dateien_je_ort) * 100).round(0)
        teil("Dubletten", "Ordnerpaare mit gleichen Inhalten",
             op.rename(columns={"ort_x": "Ordner A", "ort_y": "Ordner B", "gleich": "gleiche Inhalte"}),
             "Je Paar: wie viele Inhalte beide Ordner (ohne Unterordner) gemeinsam haben; 100 % = vollständig auch im anderen.")

    # Gruppen-Explorer: alle Gruppen, Klick zeigt die Dateien mit Vorschaubild
    g["mb"] = (g.groesse / 1e6).round(1)
    g["format_text"] = (g.format.fillna("") + " " + g.formatversion.fillna("")).str.strip()
    g["masse_text"] = np.where(g.breite.notna(), g.masse.str.replace("×", " × ") + " px", "")
    mitglieder = {}
    for gid, t in g.sort_values(["leitdatei", "relpfad"], ascending=[False, True]).groupby("gruppe_id", sort=False):
        t = t[["platte_id", "relpfad", "format_text", "mb", "masse_text", "ampel", "leitdatei", "vorschau"]]
        mitglieder[gid] = t.astype(object).where(t.notna(), None).values.tolist()
    beilagen["gruppen-daten"] = als_json({"thumbs": relpfad_von(P.vorschauen, P.berichte), "mitglieder": mitglieder})
    explorer = (je_gruppe.assign(Art=je_gruppe.art.map(ARTEN), mb=(je_gruppe.ueberz_bytes / 1e6).round(1))
                .sort_values("ueberz_bytes", ascending=False)
                [["gruppe_id", "Art", "grund", "dateien", "platten", "formate", "mb", "leitdatei"]]
                .rename(columns={"gruppe_id": "Gruppe", "grund": "Grund", "dateien": "Dateien", "platten": "Platten",
                                 "formate": "Formate", "mb": "überzählig MB", "leitdatei": "Leitdatei"}))
    teil("Dubletten", "Gruppen-Explorer", explorer,
         "Alle Gruppen, größte Einsparung zuerst. Zeile anklicken: alle Dateien der Gruppe mit Vorschaubild "
         "(blau umrandet = Leitdatei). Vorschaubilder erscheinen, wenn ihr Ort (Projektordner oder Datenträger für Vorschaubilder) erreichbar ist.", klick="gruppe")
    gb = lambda s: s.sum() / 1e9
    if not len(anton_stand):
        print("Noch kein Abgleich mit Anton (G5).")
    else:
        an = bestand.assign(anton_status=bestand.anton_status.fillna("noch nicht abgeglichen"))
        st = anton_stand.iloc[0]
        hinweis = f"Abgleich über die MD5 mit dem Auszug {st.quelle} (Stand {st.stand.split('/')[0]}). Systemdateien sind ausgelassen."
        if st.get("zugang") == "öffentlich":
            hinweis += " Abgerufen ohne internen Zugang: Dateien in nicht öffentlichen Beständen erscheinen als „nicht in Anton“."
        if st.nur_platten:
            hinweis += (f" Der Auszug ist kein vollständiger Dump: Treffer gelten für alle Datenträger, „nicht in Anton“ nur für "
                        f"{st.nur_platten.replace(',', ', ')}; die übrigen Platten bleiben „nicht geprüft“.")
        if (an.anton_status == "noch nicht abgeglichen").any():
            hinweis += " „noch nicht abgeglichen“: G5 nach dem letzten Lesen wiederholen."
        reihenfolge = [s for s in ANTONFARBEN if s in set(an.anton_status)]
        dateien = an.pivot_table(index="platte_id", columns="anton_status", values="relpfad", aggfunc="size", fill_value=0)[reihenfolge]
        volumen = an.pivot_table(index="platte_id", columns="anton_status", values="groesse", aggfunc="sum", fill_value=0)[reihenfolge] / 1e9
        teil("Anton", "Was liegt schon in Anton?",
             balken_plotly({"Dateien": dateien, "GB": volumen}, "Datenträger nach Abgleich mit Anton", ANTONFARBEN, hoehe=60 * len(dateien) + 150),
             hinweis)

        treffer = an[an.anton_status == "in Anton"]
        if len(treffer):
            bestaende = treffer.assign(bestand=treffer.anton_signatur.str.split(" | ", regex=False)).explode("bestand")
            bestaende["bestand"] = bestaende.bestand.str.extract(r"^(\D*\d+)", expand=False)
            je_bestand = (bestaende.groupby("bestand").agg(dateien=("relpfad", "size"), inhalte=("md5", "nunique"),
                                                           gb=("groesse", gb), platten=("platte_id", lambda p: ", ".join(sorted(set(p)))))
                          .sort_values("dateien", ascending=False).round({"gb": 2}).reset_index())
            teil("Anton", "Wo in Anton? Bestände",
                 je_bestand.rename(columns={"bestand": "Bestand in Anton", "dateien": "Dateien", "inhalte": "verschiedene Inhalte",
                                            "gb": "GB", "platten": "Platten"}),
                 "Bestand = Signatur bis zur ersten Zahl, z. B. GFA 59. Liegt eine Datei an mehreren Stellen in Anton, zählt sie bei jedem Bestand.",
                 breit=False)

        je_ordner = (an.assign(in_anton=an.anton_status == "in Anton", name=an.anton_status == "gleicher Name, andere Datei",
                               anton_bytes=an.groesse * (an.anton_status == "in Anton"))
                     .groupby(["platte_id", "ordner"]).agg(dateien=("relpfad", "size"), in_anton=("in_anton", "sum"),
                                                           name=("name", "sum"), gb_anton=("anton_bytes", gb))
                     .reset_index().query("in_anton > 0 or name > 0"))
        if len(je_ordner):
            je_ordner["Anteil %"] = (je_ordner.in_anton / je_ordner.dateien * 100).round(0)
            teil("Anton", "Ordner mit Dateien in Anton",
                 je_ordner.sort_values(["in_anton", "name"], ascending=False).round({"gb_anton": 2})
                 .rename(columns={"platte_id": "Platte", "ordner": "Ordner", "dateien": "Dateien", "in_anton": "in Anton",
                                  "name": "gleicher Name", "gb_anton": "GB in Anton"}),
                 "Je Ordner ohne Unterordner. 100 % = alle Dateien des Ordners liegen schon in Anton.", breit=False)

        funde = an[an.anton_status.isin(["in Anton", "gleicher Name, andere Datei"])]
        if len(funde):
            teil("Anton", "Alle Treffer",
                 funde[["platte_id", "relpfad", "anton_status", "anton_signatur", "anton_titel", "anton_link"]].sort_values(
                     ["anton_status", "platte_id", "relpfad"])
                 .rename(columns={"platte_id": "Platte", "relpfad": "Pfad", "anton_status": "Status", "anton_signatur": "Signatur",
                                  "anton_titel": "Titel", "anton_link": "in Anton öffnen"}),
                 "Der Link öffnet das Objekt in Anton (Anmeldung nötig). Mehrere Fundstellen sind mit „|“ getrennt. "
                 "„gleicher Name, andere Datei“ ist nur ein Hinweis (andere Fassung oder Zufall) und von Hand zu prüfen.")
    gb = lambda s: s.sum() / 1e9
    reihenfolge = [g for g, _ in FORMATGRUPPEN] + ["Sonstiges", "nicht erkannt", "Systemdatei"]
    anzahl = alle.pivot_table(index="gruppe", columns="platte_id", values="relpfad", aggfunc="size", fill_value=0)
    volumen = alle.pivot_table(index="gruppe", columns="platte_id", values="groesse", aggfunc="sum", fill_value=0) / 1e9
    anzahl, volumen = anzahl.reindex(reihenfolge).dropna(how="all"), volumen.reindex(reihenfolge).dropna(how="all")
    teil("Bestand", "Formatgruppen", balken_plotly({"Dateien": anzahl, "GB": volumen}, "Formatgruppen je Datenträger"), breit=False)

    formatliste = (alle.assign(platte=alle.platte_id).groupby(["gruppe", "format", "formatversion", "puid"], dropna=False)
                   .agg(dateien=("relpfad", "size"), gb=("groesse", gb), ampel=("ampel", "first"),
                        endungen=("endung", lambda e: ", ".join(e.value_counts().index[:4])),
                        platten=("platte", lambda p: ", ".join(sorted(set(p)))))
                   .reset_index().sort_values("dateien", ascending=False).round({"gb": 2})
                   .rename(columns={"gruppe": "Formatgruppe", "format": "Format", "formatversion": "Version", "puid": "PRONOM",
                                    "dateien": "Dateien", "gb": "GB", "ampel": "Ampel", "endungen": "Endungen", "platten": "Platten"}))
    teil("Bestand", "Alle Formate (Siegfried)", formatliste, "Je Format und Version; Endungen = die häufigsten Dateiendungen.",
         breit=False)

    datiert = bestand[bestand.datum.notna() & bestand.datum_quelle.notna()].assign(jahr=lambda x: x.datum.str[:4].astype(int))
    if datiert.empty:
        print("Noch keine Daten aus Abschnitt E.")
    else:
        jahre = datiert.assign(stufe=datiert.datum_quelle.map(DATUMSSTUFE)).pivot_table(
            index="jahr", columns="stufe", values="relpfad", aggfunc="size", fill_value=0)
        jahre = jahre.reindex(range(jahre.index.min(), jahre.index.max() + 1), fill_value=0)
        jahre = jahre[[s for s in STUFENFARBEN if s in jahre]]
        teil("Bestand", "Zeitraum", balken_plotly({"Dateien": jahre}, "Dateien je Jahr nach Herkunft des Datums", STUFENFARBEN,
                                                  waagerecht=False),
             "Dunkel = verlässliche Quelle (in der Datei eingebettet), hell = unsicher (Datum des Dateisystems).", breit=False)
        quellen = datiert.pivot_table(index="datum_quelle", columns="platte_id", values="relpfad", aggfunc="size", fill_value=0)
        quellen = quellen.reindex([q for q in DATUMSQUELLEN if q in quellen.index]).rename_axis(index="Datumsquelle", columns=None)
        quellen.loc["ohne Datum"] = bestand[bestand.datum.isna()].platte_id.value_counts().reindex(quellen.columns, fill_value=0)
        teil("Bestand", "Datumsquellen je Datenträger", quellen, "Dateien je Quelle des besten Datums (E2).", breit=False)

    # Ordner: Umfang je Bereich (zwei Ebenen) und häufigste Wörter in Ordnernamen
    bereich = bestand.assign(bereich=bestand.ordner.map(lambda o: "/".join(o.split("/")[:2]) or "(oberste Ebene)"))
    bereiche = (bereich.groupby(["platte_id", "bereich"]).agg(dateien=("relpfad", "size"), gb=("groesse", gb),
                                                             ueberz=("ueberz_art", "count"),
                                                             von=("datum", "min"), bis=("datum", "max"),
                                                             formate=("gruppe", lambda f: ", ".join(f.value_counts().index[:3])))
                .reset_index().sort_values("gb", ascending=False).round({"gb": 2}))
    bereiche[["von", "bis"]] = bereiche[["von", "bis"]].apply(lambda s: s.str[:4])
    teil("Bestand", "Ordner (zwei Ebenen)",
         bereiche.rename(columns={"platte_id": "Platte", "bereich": "Ordner", "dateien": "Dateien", "gb": "GB",
                                  "ueberz": "überzählig", "von": "von", "bis": "bis", "formate": "häufigste Formate"}),
         "Umfang, Zeitraum und Formate je Ordner auf den ersten zwei Ebenen (mit Unterordnern).")

    FUELLWOERTER = {"und", "der", "die", "das", "von", "fuer", "für", "mit", "the", "and", "for", "neu", "neuer", "alt",
                    "ordner", "folder", "kopie", "copy", "files", "dateien", "vti", "cnf", "images", "img", "www"}
    # zusammengeschriebene Namen trennen: „AltesIntranet_FischerNet“ → altes, intranet, fischer, net
    woerter = (pd.Series(bestand.platte_id + "|" + bestand.ordner).drop_duplicates().str.split("|").str[1]
               .str.findall(r"[A-ZÄÖÜ]?[a-zäöüß]+|[A-ZÄÖÜ]{2,}(?![a-zäöüß])").explode().dropna().str.lower())
    woerter = woerter[(woerter.str.len() >= 3) & ~woerter.isin(FUELLWOERTER)].value_counts().head(30)
    teil("Bestand", "Häufigste Wörter in Ordnernamen", balken_plotly({"Ordner": woerter}, "Ordner je Wort"),
         "Gezählt werden Ordner, nicht Dateien. Hinweis auf Themen, Orte und Anlässe.", breit=False)
    tiefe = bestand.assign(tiefe=bestand.relpfad.str.count("/")).pivot_table(
        index="tiefe", columns="platte_id", values="relpfad", aggfunc="size", fill_value=0)
    teil("Bestand", "Ordnertiefe", balken_plotly({"Dateien": tiefe}, "Dateien je Ordnertiefe (0 = oberste Ebene)", waagerecht=False),
         breit=False)
    etikett = platten.set_index("platte_id").etikett_text.fillna("").str.strip()
    for platte_id, (_, eintraege) in ordnerbaum(bestand, gruppen).items():
        beilagen[f"baum-{platte_id}"] = als_json({"platte": platte_id, "ordner": eintraege})
        reiter = f"Ordner {platte_id}"
        dashboard.setdefault(reiter, {})
        text = ("Ordner aufklappen per Klick. Je Ordner mit allen Unterordnern: Anteil der Dateien, deren Inhalt auch in einem "
                "anderen Ordner dieses Datenträgers liegt (außerhalb des Ordners), und Anteil, der auch auf einem anderen Datenträger liegt. "
                "Beides kann zugleich zutreffen. Dubletten innerhalb desselben Ordners zählen nicht, leere Dateien und Systemdateien "
                "auch nicht. "
                "100 % auf anderen Datenträgern heißt: der ganze Ordner ist anderswo vorhanden.")
        if etikett.get(platte_id):
            text += f" Etikett des Datenträgers: „{' / '.join(etikett[platte_id].splitlines())}“."
        teil(reiter, f"Ordnerbaum {platte_id}", f'<div class="bd-baum-behaelter" data-quelle="baum-{platte_id}"></div>', text)
    felder = {"aufnahme": "Aufnahmedatum", "hersteller": "Kamera", "urheber": "Urheber", "copyright": "Copyright",
              "titel": "Titel", "beschreibung": "Beschreibung", "schlagworte": "Schlagworte", "gps_breite": "GPS"}
    bilder = bestand[bestand.gruppe.isin(["Bild", "Kamera-RAW"])]
    if bilder.datum_quelle.isna().all():
        print("Noch keine Daten aus Abschnitt E.")
    else:
        abdeckung = bilder.groupby("platte_id")[list(felder)].agg(lambda s: s.notna().mean() * 100).rename(columns=felder)
        teil("Metadaten", "Abdeckung bei Bildern",
             waermebild(abdeckung.rename_axis(index=None), "Anteil der Bilder, in denen das Feld gefüllt ist (%)"),
             "Je Platte und Feld; dunkel = fast immer vorhanden.")

        def werte_tabelle(spalten, namen):
            t = (bestand.dropna(subset=spalten[:1]).groupby(spalten, dropna=False)
                 .agg(dateien=("relpfad", "size"), platten=("platte_id", lambda p: ", ".join(sorted(set(p)))),
                      von=("datum", "min"), bis=("datum", "max"))
                 .reset_index().sort_values("dateien", ascending=False))
            t[["von", "bis"]] = t[["von", "bis"]].apply(lambda s: s.str[:10])
            return t.rename(columns=dict(zip(spalten, namen)) | {"dateien": "Dateien", "platten": "Platten"})

        teil("Metadaten", "Kameras", werte_tabelle(["hersteller", "kamera"], ["Hersteller", "Modell"]),
             "Mit Zeitraum der Aufnahmen: hilft beim Zuordnen zu Fotografen und Anlässen.", breit=False)
        teil("Metadaten", "Urheber", werte_tabelle(["urheber"], ["Urheber"]), breit=False)
        teil("Metadaten", "Copyright", werte_tabelle(["copyright"], ["Copyright"]), breit=False)
        teil("Metadaten", "Software", werte_tabelle(["software"], ["Software"]), "Programm, mit dem die Datei zuletzt gespeichert wurde.",
             breit=False)
        gps = bilder.dropna(subset=["gps_breite", "gps_laenge"]).drop_duplicates("sha256")
        if len(gps):
            fig = go.Figure(go.Scattergl(x=gps.gps_laenge, y=gps.gps_breite, mode="markers", text=gps.platte_id + ": " + gps.relpfad,
                                         marker=dict(size=8, color=FARBEN[0], opacity=0.7, line=dict(color="#ffffff", width=1)),
                                         hovertemplate="%{text}<br>%{y:.4f}, %{x:.4f}<extra></extra>"))
            fig.update_layout(title="Aufnahmeorte (Länge × Breite, ohne Hintergrundkarte)", height=460,
                              xaxis_title="Länge", yaxis_title="Breite")
            fig.update_yaxes(scaleanchor="x")
            teil("Metadaten", "Aufnahmeorte", fig, f"{len(gps):,} Bilder mit GPS-Koordinaten; Maus über einen Punkt zeigt die Datei.")
    gb = lambda s: s.sum() / 1e9
    if alle.ampel.isna().all():
        print("Noch keine Daten aus Abschnitt H.")
    else:
        farben = [a for a in AMPELFARBEN if a in set(alle.ampel)]
        dateien = alle.pivot_table(index="platte_id", columns="ampel", values="relpfad", aggfunc="size", fill_value=0)[farben]
        volumen = (alle.pivot_table(index="platte_id", columns="ampel", values="groesse", aggfunc="sum", fill_value=0) / 1e9)[farben]
        teil("Archivfähigkeit", "Ampel je Datenträger",
             balken_plotly({"Dateien": dateien, "GB": volumen}, "Archivfähigkeit je Datenträger", AMPELFARBEN, hoehe=60 * len(dateien) + 150),
             "grün: archivfähig · gelb: vor der Übernahme umwandeln oder prüfen · rot: nicht lesbar, leer, unbekannt, System- oder Programmdatei.")
        leitdateien = alle.ueberz_art.isna() & ~alle.system
        massnahmen = (alle.groupby(["ampel", "massnahme"])
                      .agg(dateien=("relpfad", "size"), gb=("groesse", gb), ohne_duplikate=("relpfad", lambda r: leitdateien[r.index].sum()),
                           formate=("format", lambda f: ", ".join(f.dropna().value_counts().index[:3])))
                      .reset_index().assign(stufe=lambda x: x.ampel.map({"rot": 0, "gelb": 1, "grün": 2}))
                      .sort_values(["stufe", "dateien"], ascending=[True, False]).drop(columns="stufe").round({"gb": 2}))
        teil("Archivfähigkeit", "Maßnahmen",
             massnahmen.rename(columns={"ampel": "Ampel", "massnahme": "Maßnahme", "dateien": "Dateien", "gb": "GB",
                                        "ohne_duplikate": "davon ohne Dubletten", "formate": "häufigste Formate"}),
             "„davon ohne Duplikate“: so viele bleiben, wenn überzählige Kopien wegfallen; das ist der eigentliche Aufwand.", breit=False)
        gruende = (alle[alle.ampel != "grün"].groupby(["ampel", "grund"]).agg(dateien=("relpfad", "size"), gb=("groesse", gb))
                   .reset_index().sort_values("dateien", ascending=False).round({"gb": 2})
                   .rename(columns={"ampel": "Ampel", "grund": "Grund", "dateien": "Dateien", "gb": "GB"}))
        teil("Archivfähigkeit", "Gründe für Gelb und Rot", gruende, breit=False)

        # NARA neben der eigenen Ampel (gleiche Grundlage wie Anton)
        if alle.nara_risiko.notna().any():
            stufen = [r for r in ["Low", "Moderate", "High", "Unknown"] if r in set(alle.nara_risiko)]
            je_risiko = lambda wert, f: alle.pivot_table(index="nara_risiko", columns="ampel", values=wert, aggfunc=f,
                                                         fill_value=0).reindex(index=stufen)[farben]
            teil("Archivfähigkeit", "Eigene Ampel je NARA-Risiko",
                 balken_plotly({"Dateien": je_risiko("relpfad", "size"), "GB": je_risiko("groesse", "sum") / 1e9},
                               "Dateien je NARA-Risiko, gefärbt nach eigener Ampel", AMPELFARBEN, hoehe=60 * len(stufen) + 150),
                 "NARA bewertet nur das Format (Low, Moderate, High; Unknown = nicht bei NARA oder nicht identifiziert). "
                 "Die eigene Ampel berücksichtigt zusätzlich Lesbarkeit und Systemdateien. Abweichungen lohnen einen Blick.",
                 breit=False)
            ohne_nara = {"nara_massnahme": "(nicht bei NARA)", "nara_plan": ""}     # PUID erkannt, aber nicht im NARA-Plan
            nara_plan = (alle.fillna(ohne_nara).groupby(["nara_risiko", "nara_massnahme", "nara_plan"])
                         .agg(dateien=("relpfad", "size"), gb=("groesse", gb), ohne_duplikate=("relpfad", lambda r: leitdateien[r.index].sum()),
                              ampel=("ampel", lambda a: ", ".join(f"{k} {v}" for k, v in a.value_counts().items())),
                              formate=("format", lambda f: ", ".join(f.dropna().value_counts().index[:3])))
                         .reset_index().assign(stufe=lambda x: x.nara_risiko.map({"High": 0, "Moderate": 1, "Low": 2, "Unknown": 3}))
                         .sort_values(["stufe", "dateien"], ascending=[True, False]).drop(columns="stufe").round({"gb": 2}))
            teil("Archivfähigkeit", "NARA-Maßnahmen",
                 nara_plan.rename(columns={"nara_risiko": "NARA-Risiko", "nara_massnahme": "NARA-Maßnahme", "nara_plan": "NARA-Plan",
                                           "dateien": "Dateien", "gb": "GB", "ohne_duplikate": "davon ohne Dubletten",
                                           "ampel": "eigene Ampel", "formate": "häufigste Formate"}),
                 "Maßnahme und Plan nach NARA Digital Preservation Framework, daneben die eigene Ampel derselben Dateien.",
                 breit=False)
    ohne_mountpunkt = lambda s: s.str.replace(system.MOUNTPFAD_MUSTER, "(Datei)", regex=True)
    gefuellt = lambda s: s.fillna("").str.strip() != ""      # Siegfried speichert „keine Warnung“ als leeren Text
    probleme = [scanfehler.assign(bereich="C Schnellscan: nicht lesbar", meldung=scanfehler.fehler)]
    for bedingung, bereich, meldung in [
            (gefuellt(alle.hash_fehler), "D1 Prüfsumme: Lesefehler", alle.hash_fehler),
            (gefuellt(alle.sf_fehler), "D2 Siegfried: Fehler", alle.sf_fehler),
            (gefuellt(alle.sf_warnung), "D2 Siegfried: Warnung", alle.sf_warnung),
            (alle.viren_befund == "Fund", "D3 Virenscan: Fund", alle.viren_meldung),
            (alle.viren_befund.isin(["nicht geprüft", "Fehler"]), "D3 Virenscan: nicht geprüft", alle.viren_meldung),
            (gefuellt(alle.exif_fehler), "E ExifTool: Fehler", alle.exif_fehler),
            (gefuellt(alle.v_fehler) & alle.vorschau.isna(), "F Vorschau: keine erzeugt", ohne_mountpunkt(alle.v_fehler.fillna(""))),
            (gefuellt(alle.v_fehler) & alle.vorschau.notna(), "F Vorschau: nur über Umweg", ohne_mountpunkt(alle.v_fehler.fillna(""))),
            (alle.ampel == "rot", "H Ampel rot", alle.grund)]:
        probleme.append(alle[bedingung].assign(bereich=bereich, meldung=meldung[bedingung]))
    probleme = pd.concat(probleme)[["platte_id", "bereich", "relpfad", "meldung"]]
    probleme = probleme[~(probleme.bereich.str.startswith("H") & probleme.meldung.str.contains("Systemdatei", na=False))]
    anzahl = probleme.groupby("bereich").size()
    teil("Probleme", "Befunde je Abschnitt", balken_plotly({"Dateien": anzahl}, "Dateien mit Befund"),
         "Systemdateien sind ausgelassen. Eine Datei kann mehrere Befunde haben.", breit=False)
    teil("Probleme", "Alle Befunde",
         probleme.rename(columns={"platte_id": "Platte", "bereich": "Bereich", "relpfad": "Pfad", "meldung": "Meldung"}),
         "Suchfeld filtert alle Spalten, z. B. „Siegfried“ oder einen Ordnernamen.")

    inhalte = alle[alle.v_art.notna()].drop_duplicates("sha256")
    vorschauen = pd.crosstab(inhalte.v_art, inhalte.v_quelle.fillna("keine Vorschau"), margins=True, margins_name="Summe")
    teil("Probleme", "Vorschaubilder nach Art und Weg", vorschauen.rename_axis(index="Art", columns=None),
         "Je Inhalt (SHA-256) ein Vorschaubild. Wege: mit_pillow (direkt), eingebettet (Vorschau in der Datei), "
         "quicklook (Systemvorschau), standbilder (Video).", breit=False)

    with db() as con:
        stand = pd.read_sql("SELECT platte_id, art, MAX(ende) AS ende FROM scanlauf WHERE ende IS NOT NULL GROUP BY platte_id, art", con)
    schritte = {"schnellscan": "C", "pruefsummen": "D1", "siegfried": "D2", "virenscan": "D3", "metadaten": "E", "vorschau": "F"}
    erledigt = stand[stand.art.isin(schritte)].assign(art=lambda s: s.art.map(schritte)).groupby("platte_id").art.agg(
        lambda a: " ".join(sorted(a)))
    umfang = alle.groupby("platte_id").agg(dateien=("relpfad", "size"), gb=("groesse", lambda s: round(s.sum() / 1e9, 1)))
    tabelle = (platten.set_index("platte_id")[["volume_name", "dateisystem", "kopie_von", "etikett_text", "notiz"]]
               .join(umfang).join(erledigt.rename("gelaufen")).reset_index()
               .rename(columns={"platte_id": "Platte", "volume_name": "Volume", "dateisystem": "Dateisystem", "kopie_von": "Kopie von",
                                "etikett_text": "Etikett", "notiz": "Notiz", "dateien": "Dateien", "gb": "GB", "gelaufen": "gelaufen"}))
    teil("Datenträger und Protokoll", "Datenträger", tabelle, "Etikett und Kopie-Vermerk gehören zur Überlieferung (Bestandsgeschichte).")
    fotos = ""
    for platte_id, foto in zip(platten.platte_id, platten.etikett_foto):
        if isinstance(foto, str) and foto and (P.ordner / foto).exists():     # ohne Foto steht dort None oder NaN
            with Image.open(P.ordner / foto) as bild:
                bild = ImageOps.exif_transpose(bild).convert("RGB")
                bild.thumbnail((360, 360))
                puffer = io.BytesIO()
                bild.save(puffer, "JPEG", quality=80)
            fotos += (f'<figure class="m-0"><img src="data:image/jpeg;base64,{base64.b64encode(puffer.getvalue()).decode()}" alt="">'
                      f'<figcaption class="small">{escape(platte_id)}</figcaption></figure>')
    if fotos:
        teil("Datenträger und Protokoll", "Etiketten", f'<div class="bd-etiketten">{fotos}</div>')
    teil("Datenträger und Protokoll", "Leseläufe", scanlaeufe.sort_values("lauf_id", ascending=False).rename(
         columns={"lauf_id": "Lauf", "platte_id": "Platte", "art": "Art", "start": "Start", "ende": "Ende", "dateien": "Dateien",
                  "bytes": "Bytes", "fehler": "Fehler"}), breit=False)
    teil("Datenträger und Protokoll", "Protokoll", protokoll.rename(
         columns={"zeit": "Zeit", "abschnitt": "Abschnitt", "objekt": "Objekt", "feld": "Feld", "alt": "alt", "neu": "neu"}),
         "Jede Änderung in der Datenbank, neueste zuerst.", breit=False)
    heute = datetime.now()
    web = CODE / "vorgaben" / "web"         # Bootstrap und die Skripte des Dashboards, im Git; werden eingebettet


    def einbetten(name):
        return (web / name).read_text(encoding="utf-8")


    def karte(titel, text, html, breit):
        hinweis = f'<p class="small text-body-secondary">{escape(text)}</p>' if text else ""
        return (f'<div class="{"col-12" if breit else "col-12 col-xxl-6"}"><div class="card h-100">'
                f'<div class="card-header">{escape(titel)}</div><div class="card-body">{hinweis}{html}</div></div></div>')


    knoepfe, seiten = "", ""
    for k, (reiter, teile) in enumerate((r, t) for r, t in dashboard.items() if t):
        aktiv = " active" if k == 0 else ""
        knoepfe += (f'<li class="nav-item"><button class="nav-link{aktiv}" data-bs-toggle="tab" data-bs-target="#reiter-{k}" '
                    f'type="button">{escape(reiter)}</button></li>')
        karten = "".join(karte(titel, text, html, breit) for titel, (text, html, breit) in teile.items())
        seiten += f'<div class="tab-pane{" show" + aktiv if aktiv else ""}" id="reiter-{k}"><div class="row g-3 mb-4">{karten}</div></div>'
    daten = "".join(f'<script type="application/json" id="{s}">{j}</script>' for s, j in beilagen.items())
    kopf = (f"Stand {heute:%d.%m.%Y %H:%M} · {alle.platte_id.nunique()} Datenträger · {de(len(alle))} Dateien · "
            f"{de(alle.groesse.sum() / 1e9, 1)} GB · Datenbank {P.db_pfad.name}")

    seite = f"""<!DOCTYPE html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Balduin Dashboard</title>
<style>{einbetten("bootstrap.min.css")}</style><style>{einbetten("dashboard.css")}</style>
<script>{get_plotlyjs()}</script></head>
<body><header class="bd-kopf px-3 py-3 mb-3"><h1 class="h4 mb-1">Balduin: Übersicht</h1>
<div class="small text-body-secondary">{escape(kopf)}</div></header>
<main class="px-3"><ul class="nav nav-tabs mb-3">{knoepfe}</ul><div class="tab-content">{seiten}</div></main>
{daten}<script>{einbetten("bootstrap.bundle.min.js")}</script><script>{einbetten("dashboard.js")}</script></body></html>"""
    datei = P.berichte / f"dashboard_{heute:%Y-%m-%d}.html"
    datei.write_text(seite, encoding="utf-8")
    print(f"Dashboard: {datei.relative_to(P.ordner)} ({datei.stat().st_size / 1e6:.1f} MB, "
          f"{sum(len(t) for t in dashboard.values())} Teile). Per Doppelklick in Safari oder Firefox öffnen.")

    # Inventar: eine Zeile je Datei, mit Gruppen und Leitdatei je Duplikatstufe
    breit = pd.DataFrame(index=pd.MultiIndex.from_tuples([], names=["platte_id", "relpfad"]))
    if len(gruppen):
        breit = gruppen.pivot_table(index=["platte_id", "relpfad"], columns="art", values=["gruppe_id", "leitdatei"],
                                    aggfunc="first")
        breit.columns = [f"{art}_{'gruppe' if wert == 'gruppe_id' else 'leitdatei'}" for wert, art in breit.columns]
        breit = breit[sorted(breit.columns, key=lambda s: (["exakt", "variante", "beinahe"].index(s.split("_")[0]), s))]
        breit[[s for s in breit if s.endswith("leitdatei")]] = breit[[s for s in breit if s.endswith("leitdatei")]].astype("Int64")
    spalten = ["platte_id", "relpfad", "groesse", "datum", "datum_quelle", "gruppe", "format", "formatversion", "puid",
               "ampel", "massnahme", "grund", "nara_risiko", "nara_massnahme", "nara_plan", "nara_id", "viren_befund", "viren_meldung",
               "anton_status", "anton_treffer", "anton_signatur", "anton_titel", "anton_link",
               "urheber", "copyright", "titel", "schlagworte", "breite", "hoehe",
               "sha256", "md5", "vorschau"]
    inventar = alle[spalten].join(breit, on=["platte_id", "relpfad"]).rename(columns={"gruppe": "formatgruppe"})
    # im Projekt relativ zum Projektordner, auf der Arbeitsplatte der volle Pfad
    ort = (lambda v: relpfad_von(P.vorschauen / v, P.ordner)) if P.arbeitsplatte is None else (lambda v: str(P.vorschauen / v))
    inventar["vorschau"] = inventar.vorschau.map(lambda v: ort(v) if isinstance(v, str) else "")
    for platte_id, teil_df in inventar.groupby("platte_id"):
        ziel = P.berichte / f"inventar_{platte_id}.csv"
        teil_df.sort_values("relpfad").to_csv(ziel, index=False, encoding="utf-8-sig")
        print(f"Inventar: {ziel.relative_to(P.ordner)} ({len(teil_df):,} Zeilen, {ziel.stat().st_size / 1e6:.1f} MB)")
    protokolliere("I9", "alle Datenträger", "dashboard", "", datei.name)
    return datei

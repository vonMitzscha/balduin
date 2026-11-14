"""Anzeige-Hilfen fürs Notebook (bisher A4): Tabelle mit Diagramm, Vorschaubilder als Kacheln."""
import base64
import io

import matplotlib
import matplotlib.pyplot as plt
from IPython.display import HTML

from .basis import *  # noqa: F401,F403

if not im_notebook():
    matplotlib.use("Agg")       # Hintergrundlauf: kein Fenster öffnen

# Farben: eine Datenfarbe, Text und Linien zurückhaltend, heller Hintergrund (lesbar auch im dunklen Editor)
DATENFARBE, TEXTFARBE, LINIENFARBE, HINTERGRUND = "#2a78d6", "#52514e", "#e4e3df", "#fcfcfb"


def _als_bild(fig):
    """Zeichnet ein Diagramm als PNG und gibt es als Text zum Einbetten zurück."""
    puffer = io.BytesIO()
    fig.savefig(puffer, format="png", facecolor=HINTERGRUND)
    plt.close(fig)
    return base64.b64encode(puffer.getvalue()).decode()


def _achsen(breite, hoehe, titel):
    fig, ax = plt.subplots(figsize=(breite, hoehe), dpi=110, layout="constrained")
    fig.patch.set_facecolor(HINTERGRUND)
    ax.set_facecolor(HINTERGRUND)
    ax.set_title(titel, loc="left", fontsize=9, color=TEXTFARBE)
    ax.tick_params(colors=TEXTFARBE, labelsize=8, length=0)
    for seite in ax.spines.values():
        seite.set_visible(False)
    ax.set_axisbelow(True)
    return fig, ax


def _tausender(x, _):
    """Achsenbeschriftung: 2500 → „2,5 Tsd.“, 800 → „800“."""
    if x < 1000:
        return f"{x:.0f}"
    return f"{x / 1000:.1f}".rstrip("0").rstrip(".").replace(".", ",") + " Tsd."


def balken(werte, titel):
    """Waagerechte Balken, größter Wert oben. werte: pandas Series (Index = Beschriftung)."""
    werte = werte.iloc[::-1]
    fig, ax = _achsen(4.6, 0.24 * len(werte) + 0.9, titel)
    # nach Position zeichnen, nicht nach Beschriftung: gleiche Beschriftungen würden sonst zusammengelegt
    ax.barh(range(len(werte)), werte.values, height=0.65, color=DATENFARBE)
    ax.set_yticks(range(len(werte)), [kuerzen(str(i)) for i in werte.index])
    ax.grid(axis="x", color=LINIENFARBE, linewidth=0.8)
    ax.locator_params(axis="x", nbins=5, steps=[1, 2, 5, 10])      # runde Teilung, nicht zu dicht
    ax.xaxis.set_major_formatter(_tausender)
    return _als_bild(fig)


def saeulen_jahre(werte, titel):
    """Säulen je Jahr; Jahre ohne Dateien bleiben als Lücke sichtbar. werte: Series mit Jahreszahlen als Index."""
    fig, ax = _achsen(4.6, 2.4, titel)
    ax.bar(werte.index.astype(int), werte.values, width=0.8, color=DATENFARBE)
    ax.grid(axis="y", color=LINIENFARBE, linewidth=0.8)
    ax.yaxis.set_major_formatter(_tausender)
    ax.xaxis.get_major_locator().set_params(integer=True)
    return _als_bild(fig)


def neben_html(tabelle, *bilder):
    """HTML für eine Tabelle und ein oder mehrere Diagramme nebeneinander (bei schmalem Fenster untereinander)."""
    html = "" if tabelle is None else tabelle.to_html() if hasattr(tabelle, "to_html") else str(tabelle)
    bilder_html = "".join(f'<img src="data:image/png;base64,{b}" style="max-width:100%">' for b in bilder)
    return (f'<div style="display:flex;gap:28px;align-items:flex-start;flex-wrap:wrap">'
            f'<div>{html}</div>{bilder_html}</div>')


def neben(tabelle, *bilder):
    """Zeigt eine Tabelle und ein oder mehrere Diagramme nebeneinander."""
    zeige(HTML(neben_html(tabelle, *bilder)))


def kacheln(eintraege, breite=150):
    """Zeigt Vorschaubilder als Kacheln mit Beschriftung. eintraege: Liste von (sha256, beschriftung).
    Die Bilder werden eingebettet, damit sie im Notebook ohne Server erscheinen; nötig ist die Arbeitsplatte."""
    if not P.vorschauen.exists():
        print(f"(Vorschaubilder nicht sichtbar: Datenträger für Vorschaubilder {P.arbeitsplatte} ist nicht angeschlossen.)")
        return
    teile = []
    for sha, text in eintraege:
        datei = next((P.vorschauen / sha[:2]).glob(f"{sha}.*"), None)     # JPEG, Filme und PDFs auch animiertes WebP
        art = "webp" if datei and datei.suffix == ".webp" else "jpeg"
        bild = (f'<img src="data:image/{art};base64,{base64.b64encode(datei.read_bytes()).decode()}" '
                f'style="max-width:{breite}px;max-height:{breite}px">' if datei else "<i>keine Vorschau</i>")
        teile.append(f'<figure style="margin:0;width:{breite}px;font-size:11px;color:{TEXTFARBE}">{bild}'
                     f'<figcaption style="word-break:break-all">{text}</figcaption></figure>')
    zeige(HTML(f'<div style="display:flex;gap:12px;flex-wrap:wrap;align-items:flex-end">{"".join(teile)}</div>'))

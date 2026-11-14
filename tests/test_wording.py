"""Wording (Entscheidung 13.11.2026, Regeln in CLAUDE.md): Was Nutzende sehen, nennt die Dinge einheitlich, ohne
Plattform- oder Projektbezug. Geprüft werden die angezeigten Texte (Oberfläche, Tooltips, Rückfragen, Meldungen von
Server und Läufen), gesammelt mit werkzeuge/texte.py; Bezeichner, Datenbankwerte und Kommentare zählen nicht.
"""
import re

import pytest

from werkzeuge import texte as tx

VERBOTEN = {
    "„Datenträger“ statt „Platte“": r"\b(Quell)?[Pp]latte(n|ns)?\b|\b\w+platte(n)?\b",
    "„Speicherort“ statt „Laufwerk“": r"\bLaufwerk\w*",
    "„Datenträger“ statt „Volume“ (außer Volume-UUID)": r"\bVolumes?\b(?!-UUID)",
    "„Speicherort“ statt „Ablageort“": r"\bAblageort",
    "„bestehende Verzeichnungseinheit“ statt „Bestandsbox“": r"Bestandsbox",
    "„neue Verzeichnungseinheit“ statt „Unterverzeichnungseinheit“": r"Unterverzeichnungseinheit",
    "„Dublette“ statt „Duplikat“": r"\bDuplikat\w*|duplikat",
    "„auswählen“ statt „ankreuzen“": r"\b(an)?kreuz(t|en|e)?\b|angekreuzt\w*|ankreuzen",
    "„Import“ statt „API-Import“": r"API-Import",
    "„Balduin“ statt „Tool“": r"\bTool\b",
    "Plattformwort aus system.systemwoerter()": r"\bFinder\b|Schlüsselbund|\bmacOS\b|\bExplorer\b",
    "keine Programmnamen in Erklärtexten": r"Quick Look|Apple Vision",
    "keine Projektinterna": r"Kränzle|K&R|K&amp;R",
    # Anrede: Imperativ („Geben Sie“) oder großes Sie/Ihr mitten im Satz; am Satzanfang ist es meist „sie“/„ihr“
    "keine Anrede": r"\b\w+en Sie\b|[a-zäöüß,] (Sie|Ihr(e|en|em|er)?)\b",
    "„Lauf“ statt „Hintergrundlauf“/„Scan“": r"Hintergrundl[aä]uf|\bScan(lauf|läufe)?\b",   # „Scans“ = gescannte Bilder
    "„in den Einstellungen (Zahnrad)“": r"^(?!.*Einstellungen).*Zahnrad",
}

# Fachwörter und Namen, die bleiben dürfen (Datei, Muster im Text)
ERLAUBT = [
    ("tool/web/index.html", r"Zahnrad"),                     # Alternativtext des Zahnrad-Icons
    ("tool/web/export.js", r"^platte:\$\{"),                 # Schlüssel eines Schritts der Anleitung
    ("tool/web/erschliessung.js", r"^li\[data-platte="),     # CSS-Selektor
    ("erfassung/system.py", r"Finder|Schlüsselbund"),        # hier entstehen die Systemwörter
    ("erfassung/basis.py", r"^System Volume Information$"),   # Name eines Windows-Systemordners
]


def _funde():
    for rel, _ in tx.dateien():
        quelltext = (tx.CODE / rel).read_text(encoding="utf-8")
        for f in tx.texte_der_datei(rel):
            if any(rel == d and re.search(m, f.text) for d, m in ERLAUBT):
                continue
            if tx.als_wert(f.text, quelltext):                 # Wert im Code (Vergleich, Schlüssel), keine Anzeige
                continue
            text = tx.PLATZHALTER.sub("‹…›", f.text)              # Variablen in ${…}/{…} sind kein Text
            for regel, muster in VERBOTEN.items():
                if re.search(muster, text, re.S):
                    yield f"{rel}:{f.zeile}: {regel}: {f.text[:100]!r}"


def test_angezeigte_texte_halten_die_wording_regeln_ein():
    funde = list(_funde())
    assert not funde, f"{len(funde)} Stellen:\n" + "\n".join(funde)


@pytest.mark.parametrize("text", ["Die Platte ist voll.", "Im Finder zeigen", "Übergabe an K&R",
                                  "Schließen Sie die Ablage an.", "Duplikate", "Arbeitsplatte wählen",
                                  "Eingereihte starten, Ihre Platten bleiben"])
def test_regeln_greifen(text):
    assert any(re.search(m, text) for m in VERBOTEN.values())


@pytest.mark.parametrize("text", ["Der Datenträger ist voll.", "Volume-UUID", "Plattformen", "Sie wird erkannt.",
                                  "in den Einstellungen (Zahnrad)", "Virenscan", "Dubletten",
                                  "Die Datei liegt anderswo. Ihr Fundort geht sonst verloren."])
def test_regeln_lassen_erlaubtes_stehen(text):
    assert not any(re.search(m, text) for m in VERBOTEN.values())

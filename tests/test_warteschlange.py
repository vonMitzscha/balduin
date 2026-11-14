"""Warteschlange der Hintergrundläufe (Entscheidung 05.11.2026): „Bestand aus Anton holen“ hat eine eigene Spur und
läuft neben einer Analyse; alle übrigen Läufe (Analyse, Vorlauf, Export) bleiben hintereinander. Geprüft wird die
Anweisung, mit der Tool und beendeter Lauf den nächsten übernehmen; sie steht gleich in erfassung/lauf.py und
tool/server.py. Ohne Platten, schnell."""
import re
import sqlite3

import pytest

from conftest import CODE


def anweisungen():
    lauf = (CODE / "erfassung" / "lauf.py").read_text(encoding="utf-8")
    server = (CODE / "tool" / "server.py").read_text(encoding="utf-8")
    a = re.search(r'NAECHSTEN_UEBERNEHMEN = """(.*?)"""', lauf, re.S)[1]
    b = re.search(r'UEBERNEHMEN = """(.*?)"""', server, re.S)[1]
    return " ".join(a.split()), " ".join(b.split())


def test_tool_und_lauf_nutzen_dieselbe_anweisung():
    a, b = anweisungen()
    assert a == b


def uebernehmen(laeufe):
    """laeufe: [(art, status)] in Reihenfolge → übernommene lauf_id (1-basiert)."""
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE lauf (lauf_id INTEGER PRIMARY KEY, art TEXT, status TEXT)")
    con.executemany("INSERT INTO lauf (art, status) VALUES (?, ?)", laeufe)
    return sorted(z[0] for z in con.execute(anweisungen()[0]).fetchall())


@pytest.mark.parametrize("laeufe, erwartet", [
    ([("erfassen", "eingereiht"), ("anton", "eingereiht")], [1, 2]),          # beide Spuren frei: beide starten
    ([("erfassen", "läuft"), ("anton", "eingereiht")], [2]),                  # Anton neben der Analyse
    ([("anton", "läuft"), ("erfassen", "eingereiht")], [2]),                  # Analyse neben Anton
    ([("erfassen", "läuft"), ("erfassen", "eingereiht")], []),                # Analysen hintereinander
    ([("anton", "wartet"), ("anton", "eingereiht")], []),                     # Anton nie zweimal
    ([("erfassen", "läuft"), ("vorlauf", "eingereiht"), ("export", "eingereiht")], []),
    ([("erfassen", "eingereiht"), ("vorlauf", "eingereiht")], [1]),           # in der Hauptspur der älteste
    ([("erfassen", "fertig"), ("export", "eingereiht"), ("anton", "eingereiht")], [2, 3]),
])
def test_spuren(laeufe, erwartet):
    assert uebernehmen(laeufe) == erwartet

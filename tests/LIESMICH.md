# Automatische Tests

Die Tests prüfen bei jeder Änderung, ob Balduin noch tut, was es zusagt. Was Balduin zusagt, steht in den Grundregeln im `README.md`.

## Ausführen

```sh
.venv/bin/python -m pip install -r requirements-entwicklung.txt     # einmalig, bringt pytest mit
.venv/bin/python -m pytest                              # alle Tests, rund 30 s
.venv/bin/python -m pytest -m "not integration"         # nur die schnellen, ohne Testplatten (rund 6 s)
.venv/bin/python -m pytest tests/test_bewertung.py -x   # eine Datei, beim ersten Fehler anhalten
BALDUIN_TESTS_BEHALTEN=1 .venv/bin/python -m pytest     # Testprojekte nach dem Lauf zum Nachsehen behalten
```

Die Integrationstests brauchen Siegfried und ExifTool (`brew install siegfried exiftool`). Fehlen die Werkzeuge, werden diese Tests übersprungen, nicht als Fehler gezählt.

## Sicherheit

Kein Test berührt echte Daten:

- **Schutzwache** (`schutz/`): Jeder Zugriff auf `/Volumes` bricht ab, auch reines Lesen. Das gilt im Testprozess und in jedem Server und Hintergrundlauf, den die Tests starten. Fängt der Code den Fehler selbst ab, fällt der Test trotzdem durch.
- Testplatten, Projekte, `HOME`, `zuletzt.json` und Schlüsselbund liegen in einem Temp-Ordner, der danach gelöscht wird.
- Anton ist ein **Nachbau** auf 127.0.0.1 (`hilfen/anton_nachbau.py`) mit erfundenen Daten und eigenem Token. Die echte Instanz wird nie angefragt.

## Aufbau

| Datei | prüft |
|---|---|
| `test_schutzwache.py` | die Schutzwache selbst |
| `test_basis.py` | Hilfsfunktionen, Einstellungen, Projekt anlegen, Nachrüsten alter Datenbanken (schnell) |
| `test_anton_lesen.py` | Lesen aus Anton: Laufzeit, Sperre, Bestandsbox, Token nur im Header (schnell) |
| `test_server_hilfen.py` | kleine Hilfen des Servers (schnell) |
| `test_analyse.py` | Modul 1: Testplatten durch B–I, Prüfsummen, Formate, Duplikate, Anton-Abgleich, Idempotenz |
| `test_bewertung.py` | Modul 2 über die Server-API: Vererbung, Vorrang, Aufheben, Vorbehalt, Schutzregel, Protokoll |
| `test_erschliessung.py` | Modul 3 über die Server-API: Werte am Element, Vererben, Laufzeit, Bestandsboxen, Zuordnen |
| `test_schutzregeln.py` | die Grundregeln aus dem `README.md`: Quellplatten bitgleich, Kassieren löscht nichts, Protokoll, nichts geht in die Cloud, Token in keiner Datei, Vorschläge nie automatisch, Server nur für die eigene Oberfläche; beim Export: auf der Ablage nur im eigenen Ordner, Paket erst nach der Kontrolle löschen, Token in keinem Paket, nichts nach Anton hochladen |
| `test_export*.py` | Modul 4 (Paketbau) |
| `test_archivdateien.py` | Archivdateien (ZIP, tar.gz, gz, ZIP im ZIP, defekt, verschlüsselt, Mac-Namen) wie Ordner: Schnellscan, Lesen, Prüfsummen, Bereitstellen für Werkzeuge, ganzer Lauf B–I, Virenscan, Symbol im Baum, Export ins Paket, Bestandsgeschichte, ältere Platten |
| `test_traeger.py` | Art des Datenträgers (CD/DVD, USB-Stick, Karte, Festplatte, Image, Ordner) aus gespeicherten `diskutil`-Antworten, gespeichert und über alle Module ausgeliefert |
| `test_lizenz.py` | Lizenz: vollständige Lizenztexte, jede Datei mit Lizenz nach REUSE, Urheber in „Über Balduin“ |

Gemeinsame Bausteine (Fixtures) stehen in `conftest.py`:

- `testplatten`, `anton`, `analysiert` entstehen einmal je Lauf.
- `projekt` und `balduin` (der laufende Server) gibt es je Testdatei als eigene Kopie, die frei verändert werden darf.

## Arbeitsweise: zuerst der Test

Jede neue Funktion und jede Fehlerbehebung beginnt mit einem Test:

1. **Rot:** Einen Test schreiben, der das gewünschte Verhalten beschreibt, und ihn laufen lassen. Er muss fehlschlagen. Bei einem Fehler zeigt er den Fehler.
2. **Grün:** Nur so viel Code ändern, dass er besteht.
3. **Aufräumen:** Den Code verbessern. Die Tests bleiben dabei grün.

Für bestehenden Code ohne Test gilt: Wer ihn anfasst, sichert zuerst das heutige Verhalten mit einem Test ab. Committet wird nur, wenn alle Tests bestehen.

Tests heißen wie das, was sie zusagen (`test_kassieren_der_ganzen_platte_loescht_nichts`). Sie sind auf Deutsch, wie der übrige Code.

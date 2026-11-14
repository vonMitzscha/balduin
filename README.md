# Balduin

Balduin ist ein lokales Web-Tool für Archive: Es registriert und analysiert Datenträger mit digitalen Beständen
(Festplatten, USB-Sticks, CDs, Ordner, Abbilder von Mac-Datenträgern), unterstützt Bewertung und Erschließung und
übergibt das Übernommene als geprüfte Pakete an die Archivsoftware [Anton](https://anton.ch). Bedienbar ohne
Technikkenntnisse, Start per Doppelklick auf `Balduin.command` (Mac), `balduin.sh` bzw. `Balduin.desktop` (Linux).
Entwickelt auf dem Mac; Windows und Linux sind vorbereitet und mit nachgestellten Systemantworten getestet.

| Modul | Zweck |
|---|---|
| 1 Registrierung/Analyse | Datenträger registrieren (mit Etikett), nur lesend scannen, Prüfsummen (SHA-256, MD5), Formate (Siegfried/PRONOM), Virenscan (ClamAV), Metadaten (ExifTool), Texte, Vorschaubilder, Personen auf Fotos (optional), Duplikate, Abgleich mit Anton, Archivfähigkeit (eigene Regeln und NARA), Bericht |
| 2 Bewertung | übernehmen / kassieren / zurückstellen mit Vorbehalt, Vererbung und Sperre, Regeln, Schutz vor verlorenen Dubletten, Erschließungshinweise |
| Vorlauf | Vorschläge für die Erschließung: Pfade und Namen, Metadaten, Sujet (OpenCLIP, lokal), Normdaten aus dem Anton-Vokabular, verwandte Ordner |
| 3 Erschließung | Titel, Laufzeit, Form und Inhalt, Akteur:innen, Orte, Schlagworte; Vorschläge bestätigen; Zuordnen in Einheiten aus Anton oder neue Ebenen darunter; Sprachmodell nur lokal und auf Abruf |
| 4 Bestand und Export | Freigabe, Pakete planen und packen (BagIt als tar mit `metadata.json` im [Anton-Importformat](https://github.com/kraenzle-ritter/anton-import-format), Prüfsummen gegen die Datenbank, fortsetzbar, nachgeprüft), Lieferschein, Übergabe, Kontrolle in Anton, Abschlussbericht |

Dazu ein Dashboard mit dem Gesamtstand, als eigenständiger HTML-Bericht speicherbar.

- **Einrichten und erste Schritte:** [EINRICHTUNG.md](EINRICHTUNG.md)
- **Tests:** [tests/LIESMICH.md](tests/LIESMICH.md)

## Grundregeln

Balduin sagt dem Archiv Folgendes zu; automatische Tests (`tests/test_schutzregeln.py`) prüfen es bei jeder Änderung.

1. **Quellen nur lesen.** Auf Quelldatenträgern und als Quelle registrierten Ordnern wird nichts geschrieben,
   verschoben, umbenannt oder gelöscht; Datenträger werden schreibgeschützt eingehängt. Unter Windows geht das nicht:
   Dort liest Balduin nach einer Rückfrage ohne Schreibschutz (das System kann dann eigene kleine Dateien anlegen,
   der Bestand bleibt unverändert; protokolliert und in der Bestandsgeschichte vermerkt) oder über einen
   Writeblocker. Geschrieben wird nur in den
   Projektordner, auf eine gewählte Arbeitsplatte für Vorschaubilder und in die Ablage der Exportpakete.
2. **Die Datenbank des Projekts (`inventar.sqlite`) ist die einzige Wahrheit.** CSV und HTML sind Arbeitsblätter
   oder Berichte.
3. **Jede Änderung wird protokolliert** (Zeit, Abschnitt, Objekt, Feld, alter und neuer Wert).
4. **Kassieren heißt markieren, nicht löschen.** Originale werden erst beim Export kopiert, direkt von der
   schreibgeschützten Quelle in Pakete, mit Prüfsummenvergleich und Nachprüfung.
5. **Speicher schonen:** Vor platzintensiven Schritten prüft Balduin den freien Platz und hält an, bevor das Laufwerk
   volläuft; vor einer Analyse nennt es, was die Vorschaubilder ungefähr brauchen.
6. **Inhaltsanalyse bleibt lokal** (ONNX Runtime, Ollama). Keine Bilder oder Texte an Cloud-Dienste; an
   Normdatendienste (GND, Wikidata) gehen nur einzelne Begriffe, Namen oder IDs, jede Abfrage protokolliert.
7. **Vorschläge werden nie automatisch übernommen;** sie tragen Quelle und Score und werden von Menschen bestätigt.

## Aufbau

| Pfad | Inhalt |
|---|---|
| `Balduin.command` | Start des Tools (Startbildschirm: Projekt öffnen oder neu anlegen) |
| `balduin.sh`, `Balduin.desktop` | Start unter Linux (Terminal bzw. Doppelklick im Dateimanager) |
| `tool/` | Web-Tool: Server (nur Python-Standardbibliothek, nur 127.0.0.1) und Oberfläche ohne Build-Schritt |
| `erfassung/` | Rechencode von Modul 1, je Schritt eine Datei; läuft als Hintergrundlauf, vom Tool gestartet |
| `vorlauf/` | Rechencode des Vorlaufs |
| `export/` | Rechencode von Modul 4 (Pakete bauen, prüfen, Lieferschein) |
| `vorgaben/` | Regeltabellen (Archivfähigkeit, Sujet-Begriffe, Unbrauchbares), Schema des Anton-Importformats, NARA Digital Preservation Framework, Skripte des HTML-Berichts |
| `modelle/` | Modelle der Bildanalyse (nicht im Repo; Herkunft und Lizenz in `modelle/LIESMICH.md`) |
| `werkzeuge/` | Testplatten erzeugen, Modelle und NARA-Daten laden, Testabbilder für Mac-Datenträger |
| `tests/` | automatische Tests mit pytest |

Projekte (Datenbank, Vorschaubilder, Berichte, Pakete) liegen nie im Code-Ordner, sondern je Projekt in einem eigenen
Ordner.

## Stand

Entwickelt und im Einsatz auf macOS; die Fassung für Windows ist vorbereitet (alles Plattformabhängige liegt in
`erfassung/system.py`), aber noch nicht an einem echten Windows-Rechner geprüft. Das Anton-Importformat ist bis
Version 1.0 nicht stabil; Balduin richtet sich nach der Version, die die Zielinstanz liest.

## Mitarbeiten

Fehlermeldungen und Vorschläge als Issue. Beiträge als Pull Request mit `Signed-off-by` in jedem Commit
(`git commit -s`, [Developer Certificate of Origin](https://developercertificate.org)): Damit bestätigst du, dass du
den Beitrag einbringen darfst und dass er unter der Lizenz von Balduin steht. Neue Funktionen kommen mit Tests
(`tests/`); vor dem Pull Request `.venv/bin/python -m pytest`.

## Lizenz

Balduin – © 2026 Marc Eric Mitzscherling

Der Code steht unter der **GNU Affero General Public License, Version 3 oder später** (`LICENSE`), mit
zusätzlichen Bestimmungen nach § 7 (`LIZENZ-ZUSATZ.md`): Die Nennung des Urhebers bleibt in den Urheberhinweisen und
in der Anzeige „Über Balduin“ jeder Fassung erhalten, veränderte Fassungen sind als solche gekennzeichnet, und Name
und Zeichen „Balduin“ gehören nicht zur Lizenz. Wer Balduin verändert weitergibt oder über ein Netz anbietet, macht
den Quelltext unter derselben Lizenz zugänglich.

Dokumentation und Regeltabellen stehen unter CC BY-SA 4.0. Fremdbestandteile behalten ihre Lizenz (Lucide ISC, Inter
OFL 1.1, Anton-Importschema MIT, NARA gemeinfrei, Zeichen Pixabay-Inhaltslizenz). Je Datei verzeichnet
`REUSE.toml` die Lizenz nach der REUSE-Spezifikation, die Texte liegen in `LICENSES/`.

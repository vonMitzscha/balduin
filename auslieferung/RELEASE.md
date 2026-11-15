> **Vorversion (Beta).** Balduin ist im Aufbau und noch nicht an allen Beständen erprobt. Vor dem Einsatz an einem echten Bestand mit einer Kopie oder einem kleinen Datenträger ausprobieren; Rückmeldungen und Fehler bitte als Issue melden.

**Neu in dieser Fassung** (seit 0.90)

- **Läufe halten den Rechner wach** und lassen sich immer abbrechen: Während einer Analyse geht der Rechner nicht in
  den Ruhezustand; „Abbrechen“ beendet auch Programme, auf die der Lauf wartet, und spätestens nach 60 Sekunden den
  Lauf selbst. Die Restzeit richtet sich nach dem Tempo der letzten zwei Minuten (unter Windows stieg sie nach dem
  Ruhezustand auf viele Stunden).
- **Pflichtfelder** sind rot umrahmt, solange sie leer sind (Assistent, Einstellungen, Registrieren, Erschließung).
- **Sicherheit:** Dateinamen mit Zeilenumbruch können beim Lesen der Metadaten keine Optionen mehr einschleusen;
  solche Dateien gelten als nicht gelesen. Beitrag von Andreas Kränzle.
- **Mac:** Ein API-Token mit Anführungszeichen oder Backslash wird jetzt im Schlüsselbund gespeichert. Beitrag von
  Andreas Kränzle.
- **Mac:** neues Fenster der dmg auf weißem Grund mit dem Elefanten, der aus dem App-Symbol wächst, und einer
  bebilderten Anleitung für den ersten Start.
- README überarbeitet; der Bau der Pakete übersteht kurze Netzausfälle.

**Herunterladen**

| System | Datei |
|---|---|
| Mac mit Apple-Chip (M1 und neuer) | `Balduin-…-Mac-AppleChip.dmg` |
| Mac mit Intel-Prozessor | `Balduin-…-Mac-Intel.dmg` |
| Windows 10/11 (64 Bit) | `Balduin-…-Windows-Setup.exe` |
| Linux x86_64 (**Alpha**) | `Balduin-…-Linux-x86_64-alpha.tar.gz` |

Zu jeder Datei liegt die SHA-256 als `.sha256` bei.

**Installieren**

- **Mac:** dmg öffnen, Balduin in den Ordner „Programme“ ziehen. Diese Fassung ist nicht von Apple beglaubigt: beim
  ersten Start meldet macOS „„Balduin“ nicht geöffnet“; die Meldung mit „Fertig“ schließen, dann unter
  Systemeinstellungen › Datenschutz & Sicherheit im Abschnitt „Sicherheit“ „Dennoch öffnen“ wählen und mit dem
  Passwort bestätigen (seit macOS 15 genügt Rechtsklick › „Öffnen“ nicht mehr). Balduin läuft danach mit einem
  Symbol im Dock.
- **Windows:** Installer ausführen. Er ist noch nicht signiert; meldet Windows „Der Computer wurde durch Windows
  geschützt“, über „Weitere Informationen“ › „Trotzdem ausführen“ fortfahren. Er richtet lange Pfade (über 260 Zeichen)
  ein; bei der Installation „nur für mich“ fragt er dafür einmal nach Administratorrechten. Balduin läuft danach mit einem Symbol im Infobereich.
- **Linux (Alpha):** Archiv entpacken, `./balduin.sh` starten; benötigte Pakete der Distribution nennt
  `LIESMICH-ALPHA.txt`.

Dabei sind Python, Siegfried, ExifTool, ffmpeg, Poppler, ClamAV und smartctl (Linux: teils aus der Paketverwaltung)
sowie die Modelle der Personenerkennung. Lizenzen der Werkzeuge: `bin/LIZENZEN.md` im Programmordner.

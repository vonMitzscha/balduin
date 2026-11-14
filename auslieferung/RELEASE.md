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
  ersten Start Balduin mit Rechtsklick › „Öffnen“ starten; meldet macOS eine Sperre, unter Systemeinstellungen ›
  Datenschutz & Sicherheit „Dennoch öffnen“ wählen. Balduin läuft danach mit einem Symbol im Dock.
- **Windows:** Installer ausführen. Er ist noch nicht signiert; meldet Windows „Der Computer wurde durch Windows
  geschützt“, über „Weitere Informationen“ › „Trotzdem ausführen“ fortfahren. Mit Administratorrechten richtet er
  lange Pfade (über 260 Zeichen) ein. Balduin läuft danach mit einem Symbol im Infobereich.
- **Linux (Alpha):** Archiv entpacken, `./balduin.sh` starten; benötigte Pakete der Distribution nennt
  `LIESMICH-ALPHA.txt`.

Dabei sind Python, Siegfried, ExifTool, ffmpeg, Poppler, ClamAV und smartctl (Linux: teils aus der Paketverwaltung)
sowie die Modelle der Personenerkennung. Lizenzen der Werkzeuge: `bin/LIZENZEN.md` im Programmordner.

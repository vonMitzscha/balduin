# Einrichtung

Abschnitte 1–8 beschreiben den Mac; Linux in Abschnitt 9.

## 1. Code, Python und Pakete

Balduin braucht Python 3.13 (nicht 3.15: zu neu für einige Pakete) und Git. Im Terminal:

```bash
git clone <Adresse dieses Repos> balduin
cd balduin
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-entwicklung.txt   # Laufzeit (requirements.txt) plus Tests
.venv/bin/python werkzeuge/modelle_laden.py   # Modelle der Bildanalyse nach modelle/ (nur nötig, wenn ein Projekt sie nutzt)
.venv/bin/python -m pytest -m "not integration"   # kurze Kontrolle
```

Die Modelle stehen nicht im Repo (Herkunft, Lizenz und Größe in `modelle/README.md`).

**Code verschieben:** Eine venv merkt sich ihren Ort und läuft nach dem Verschieben nicht mehr zuverlässig. Danach
`rm -rf .venv` und die venv wie oben neu anlegen. Projekte bleiben davon unberührt.

## 2. Werkzeuge über Homebrew

```bash
brew install smartmontools                      # optional (SMART-Werte der Platten)
brew install exiftool ffmpeg                    # Metadaten (E), Filmvorschau (F)
brew install poppler                            # Texte aus PDF (E4), mehrseitige PDF-Vorschau (F)
brew install richardlehane/digipres/siegfried   # Formaterkennung (D2); liegt nicht in Homebrew-Core
brew install clamav                             # Virenscan (D3); die Signaturen holt D3 selbst mit freshclam
```

Viele USB-Gehäuse reichen SMART unter macOS nicht durch; das Tool meldet dann „nicht lesbar“.

## 3. Tool starten

Doppelklick auf `Balduin.command`. Es öffnet sich ein Terminalfenster und der Browser mit dem Startbildschirm. Das
Terminalfenster offen lassen, solange gearbeitet wird; Schließen beendet das Tool. Analysen laufen im Hintergrund
weiter, auch wenn das Browserfenster zu ist.

Beim ersten Zugriff auf eine externe Platte fragt macOS, ob das Terminal auf „Dateien auf Wechselmedien“ zugreifen
darf: erlauben. Falls nicht gefragt wird: Systemeinstellungen → Datenschutz & Sicherheit → Dateien und Ordner →
Terminal → „Wechselmedien“.

## 4. Projekte

Arbeitsdaten liegen nicht im Code-Ordner, sondern je Projekt in einem eigenen Ordner (`projekt.json`,
`inventar.sqlite`, Kopie der Regeltabellen, Arbeitsordner). Neue Projekte entstehen dort, wo zuletzt eines angelegt
wurde, sonst in `Projekte/` neben dem Code. Gemerkt wird das in `zuletzt.json` im Datenordner der App
(`~/Library/Application Support/Balduin`).

Auf dem Startbildschirm: zuletzt geöffnetes Projekt anklicken, „Anderes Projekt öffnen …“ oder „Neues Projekt“
(Assistent: Name und Kürzel, Ablageort, Vorschaubilder im Projekt oder auf einer Arbeitsplatte, Film- und
PDF-Vorschau, Virenscan, Personenerkennung, andere Projekte). Später ändern: Zahnrad vorn in der
Modulleiste (Name, Kürzel, Anton) und Zahnrad am Knopf „Registrierung/Analyse“ (das Übrige).

## 5. Ausprobieren mit Testplatten

```bash
.venv/bin/python werkzeuge/testplatten_erzeugen.py
./Balduin.command --volumes "$PWD/testplatten"
```

Das Tool zeigt dann statt der echten Datenträger die Testplatten HD01 bis HD04. Dafür ein eigenes Projekt anlegen
(z. B. „Test“, Vorschaubilder im Projekt) und die Platten nacheinander registrieren und analysieren. Ergebnis: HD02
ist ein Backup von HD01 in einem Unterordner, HD04 ein Klon mit einer veränderten Datei, HD03 enthält einen Ordner von
HD01. Für die echte Arbeit das Tool danach wieder normal per Doppelklick starten.

## 6. Ablauf je Datenträger (Modul 1 Registrierung/Analyse)

1. Datenträger anschließen, im Tool „Registrierung/Analyse“ öffnen.
2. Datenträger wählen. Ist er beschreibbar eingehängt: „Schreibgeschützt einhängen“ (Mac, Linux). Unter Windows
   lässt sich ein Datenträger nicht schreibgeschützt einhängen: Balduin fragt vor dem ersten Lesen einmal je
   Datenträger, ob ohne Schreibschutz gelesen werden soll (protokolliert, in der Bestandsgeschichte vermerkt). Wer
   ganz sauber arbeiten will, schließt ihn über einen Writeblocker an; dann fragt Balduin nicht.
3. Angaben machen: Kennung (Vorschlag übernehmen), **Etikett** (Text, optional Foto), Notiz, ggf. „Kopie von“.
   Statt eines ganzen Datenträgers lassen sich auch einzelne Ordner, ein Ordner als Quelle oder das Abbild eines
   Mac-Datenträgers einlesen.
4. Analyse starten. Der Fortschritt steht je Schritt in der Ansicht; ein Lauf lässt sich abbrechen und später
   fortsetzen. Weitere Datenträger können in die Warteschlange.
5. Nach dem Lauf auswerfen, nächster Datenträger. Liegt einer fast vollständig auf einem anderen, zeigt das Tool
   einen Hinweis mit „als Kopie vermerken“.

Danach im Modul **Bewertung** entscheiden. Den Gesamtstand zeigt jederzeit der Knopf „Dashboard“, daraus „Als
Bericht speichern“ für eine eigenständige HTML-Datei.

## 7. Verbindung zu Anton

Adresse der Anton-Instanz und Token stehen im Zahnrad vorn in der Modulleiste. Für nicht öffentliche Bestände
braucht Balduin den API-Token eines internen Anton-Kontos; er kommt in den macOS-Schlüsselbund (Eintrag
„Anton-API <Servername>“), nie in eine Datei im Projekt. Im Tool: Token einfügen → „Token speichern“ →
„Verbindung prüfen“. Oder im Terminal:

```bash
security add-generic-password -a "$USER" -s "Anton-API <Servername>" -w
```

macOS fragt zweimal nach dem Wert; der Token erscheint beim Einfügen nicht auf dem Bildschirm. Für einzelne Läufe
geht auch die Umgebungsvariable `ANTON_TOKEN`.

**Abruf:** unter den registrierten Platten „Bestand aus Anton holen“ (abbrechbar). Neu holen bei Bedarf: vor dem
Export, nach einem Import in Anton oder wenn viel Neues in Anton liegt. Vor dem ersten Abruf empfiehlt sich eine
Sicherung der Datenbank im Projektordner: `sqlite3 inventar.sqlite ".backup 'inventar_vor-anton.sqlite'"`.

## 8. Entwicklung

- Tests: `.venv/bin/python -m pytest` (alle), `-m "not integration"` (schnell); mehr in `tests/README.md`. Tests
  berühren nie echte Datenträger und nie eine echte Anton-Instanz.
- Der Server nutzt nur die Python-Standardbibliothek; Rechenintensives läuft als Hintergrundlauf (`erfassung/lauf.py`).
- Plattformabhängiges steht nur in `erfassung/system.py`; die Oberfläche (`tool/web/`) kommt ohne Build-Schritt und
  ohne Fremdbibliotheken aus.
- Neue Fremddateien (Bibliotheken, Schriften, Bilder, Daten) mit Urheber und Lizenz in `REUSE.toml` eintragen.

## 9. Linux (Debian, Ubuntu und ähnliche)

Balduin läuft auch unter Linux; alles Systemabhängige steht in `erfassung/system.py`. Python und venv wie in
Abschnitt 1, danach die Werkzeuge über die Paketverwaltung:

```bash
sudo apt install python3-venv python3-dev build-essential   # venv; Compiler, falls Pakete aus dem Quelltext gebaut werden
sudo apt install libimage-exiftool-perl ffmpeg poppler-utils # Metadaten (E), Filmvorschau (F), Texte und PDF-Vorschau
sudo apt install clamav clamav-daemon                        # Virenscan (D3); Signaturen holt der Dienst clamav-freshclam
sudo apt install udisks2 zenity libsecret-tools              # schreibgeschützt einhängen, Dialoge, Passwortspeicher
sudo apt install smartmontools                               # optional (SMART braucht unter Linux Administratorrechte)
sudo apt install libreoffice                                 # optional (Vorschau von Office-Dateien ohne eingebettetes Bild)
```

Siegfried (Formaterkennung, D2) gibt es nicht in den Paketquellen: das `.deb` von
https://github.com/richardlehane/siegfried/releases installieren oder das Programm `sf` nach `bin/` neben den Code
legen. Unter KDE ersetzt `kdialog` zenity, `kioclient5` übernimmt den Papierkorb. Ohne zenity und kdialog öffnet
Balduin den Dialog über Tk (`sudo apt install python3-tk`).

**Start:** `./balduin.sh` im Terminal oder Doppelklick auf `Balduin.desktop` (im Dateimanager einmal „Ausführen
erlauben“). Der Datenordner der App ist `~/.config/balduin`.

**Datenträger:** Linux-Desktops hängen Datenträger von selbst **beschreibbar** unter `/media/<Benutzer>/` oder
`/run/media/<Benutzer>/` ein. Balduin zeigt sie als „beschreibbar“; „Schreibgeschützt einhängen“ hängt sie über
udisks2 ohne Root neu ein, bei ext3/ext4 mit `noload`, bei XFS mit `norecovery`, bei Btrfs mit `nologreplay`, damit
kein Journal nachgespielt wird. Das schon erfolgte erste Einhängen kann ein Journal aber bereits nachgespielt haben.
Für Quellbestände deshalb das automatische Einhängen ausschalten (GNOME:
`gsettings set org.gnome.desktop.media-handling automount false`) oder einen Writeblocker verwenden. HFS+ hängt Linux
nur lesend ein; APFS kennt Linux nicht. Solche Platten zeigt Balduin als „nicht eingebunden“ mit „Mac-Datenträger
lesen …“: Balduin liest sie selbst und fragt dafür einmal je Lauf nach dem Administratorpasswort (pkexec). Wer zur
Gruppe `disk` gehört, wird nicht gefragt.

**Wiedererkennen:** Eine HFS+-Platte trägt unter Linux dieselbe Kennung wie auf dem Mac. ExFAT-, FAT- und
APFS-Platten, die auf dem Mac registriert wurden, erkennt Linux an Name, Dateisystem, Größe und Stichprobe wieder,
nicht an der UUID; das gilt auch für den Datenträger für Vorschaubilder.

**Anton-Token:** im Passwortspeicher des Desktops (Secret Service: GNOME-Schlüsselbund, KWallet) über
`secret-tool`. Ohne Desktop (z. B. auf einem Server) geht die Umgebungsvariable `ANTON_TOKEN`.

**Dateinamen:** Namen, die nicht in UTF-8 vorliegen (alte FAT- oder ISO-Datenträger), meldet der Schnellscan als
Lesefehler; sie erscheinen in der Freigabe.

; Installer für Windows (Datei in UTF-8 mit BOM, sonst liest Inno Setup die Umlaute falsch)
; (Inno Setup 6; Entscheidungen 13. und 14.11.2026, docs/plan.md).
; Aufruf durch auslieferung/bauen.py:  ISCC /DVersion=0.75 /DQuelle=<Programmordner> /DAusgabe=<Ordner> balduin.iss
; Installiert für alle (Administratorrechte, setzt LongPathsEnabled) oder nur für das eigene Konto (ohne; Balduin
; weist dann in Registrierung/Analyse auf die fehlende Einstellung hin).

#ifndef Version
  #define Version "0"
#endif

[Setup]
AppId={{6B0C5E7A-2F43-4C55-9E0B-5A1D0B7A8C21}
AppName=Balduin
AppVersion={#Version}
AppVerName=Balduin {#Version}
AppPublisher=Marc Eric Mitzscherling
DefaultDirName={autopf}\Balduin
DefaultGroupName=Balduin
DisableProgramGroupPage=yes
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir={#Ausgabe}
OutputBaseFilename=Balduin-{#Version}-Windows-Setup
SetupIconFile=balduin.ico
UninstallDisplayIcon={app}\Balduin.exe
UninstallDisplayName=Balduin
LicenseFile={#Quelle}\LICENSE
InfoAfterFile=nach_der_installation.txt
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
AppMutex=BalduinStarter
CloseApplications=yes

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktop"; Description: "Verknüpfung auf dem Desktop anlegen"; GroupDescription: "Zusätzlich:"

[InstallDelete]
; Reste einer früheren Fassung entfernen (Projekte liegen nie im Programmordner)
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\bin"
Type: filesandordirs; Name: "{app}\erfassung"
Type: filesandordirs; Name: "{app}\vorlauf"
Type: filesandordirs; Name: "{app}\export"
Type: filesandordirs; Name: "{app}\tool"
Type: filesandordirs; Name: "{app}\vorgaben"

[Files]
Source: "{#Quelle}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Balduin"; Filename: "{app}\Balduin.exe"
Name: "{autodesktop}\Balduin"; Filename: "{app}\Balduin.exe"; Tasks: desktop

[Registry]
; Pfade über 260 Zeichen (Entscheidung 13.11.2026); gilt für den ganzen Rechner, bleibt beim Deinstallieren
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\FileSystem"; ValueType: dword; ValueName: "LongPathsEnabled"; ValueData: "1"; Check: IsAdminInstallMode

[Run]
; Installation „nur für mich“: lange Pfade auf der letzten Seite anbieten (fragt einmal nach Administratorrechten),
; nur wenn sie noch fehlen; „für alle“ setzt sie oben unter [Registry] ohne Rückfrage (Feedback 14.11.2026)
Filename: "{sys}\reg.exe"; Parameters: "add ""HKLM\SYSTEM\CurrentControlSet\Control\FileSystem"" /v LongPathsEnabled /t REG_DWORD /d 1 /f"; Description: "Lange Pfade (über 260 Zeichen) einrichten; fragt einmal nach Administratorrechten"; Flags: postinstall shellexec runhidden waituntilterminated skipifsilent; Verb: runas; Check: (not IsAdminInstallMode) and (not LangePfadeAn)
Filename: "{app}\Balduin.exe"; Description: "Balduin jetzt starten"; Flags: nowait postinstall skipifsilent

[Code]
// Sind lange Pfade auf diesem Rechner schon eingerichtet? (Lesen geht ohne Administratorrechte)
function LangePfadeAn: Boolean;
var
  Wert: Cardinal;
begin
  Result := RegQueryDWordValue(HKLM, 'SYSTEM\CurrentControlSet\Control\FileSystem', 'LongPathsEnabled', Wert) and (Wert = 1);
end;

[UninstallDelete]
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\bin"

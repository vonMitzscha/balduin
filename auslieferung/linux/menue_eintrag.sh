#!/bin/sh
# Legt einen Menüeintrag „Balduin“ für das eigene Konto an (~/.local/share/applications), mit Symbol.
# Nach dem Verschieben des Ordners erneut ausführen.
ORDNER="$(cd "$(dirname "$0")" && pwd)"
ZIEL="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$ZIEL"
cat > "$ZIEL/balduin.desktop" <<EINTRAG
[Desktop Entry]
Type=Application
Name=Balduin (Alpha)
Comment=Datenträger registrieren, bewerten, erschließen und für Anton packen
Exec="$ORDNER/balduin.sh"
Path=$ORDNER
Icon=$ORDNER/balduin.png
Terminal=true
Categories=Office;
EINTRAG
echo "Menüeintrag angelegt: $ZIEL/balduin.desktop"

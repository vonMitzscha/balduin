#!/bin/sh
# Balduin starten (Linux, Alpha-Version): im Terminal ./balduin.sh oder über den Menüeintrag (menue_eintrag.sh).
# Fenster offen lassen, solange gearbeitet wird; Schließen beendet Balduin (Läufe arbeiten weiter).
cd "$(dirname "$0")" || exit 1
echo "Balduin für Linux – ALPHA-VERSION: noch nicht an echten Linux-Arbeitsplätzen geprüft."
echo "Fehler bitte über die Issues der Projektseite melden."
echo
PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 exec ./python/bin/python3 -X utf8 tool/server.py "$@"

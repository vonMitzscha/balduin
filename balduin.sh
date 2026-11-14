#!/bin/sh
# Balduin unter Linux starten: im Terminal ./balduin.sh oder über Balduin.desktop (Doppelklick im Dateimanager).
# Fenster offen lassen, solange gearbeitet wird; Schließen beendet Balduin.
cd "$(dirname "$0")" || exit 1
exec .venv/bin/python tool/server.py "$@"

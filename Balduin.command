#!/bin/zsh
# Balduin starten: Doppelklick im Finder. Fenster offen lassen, solange gearbeitet wird; Schließen beendet das Tool.
cd "$(dirname "$0")"
exec .venv/bin/python tool/server.py "$@"

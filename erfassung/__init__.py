"""Erfassung der Platten (bisher Notebook 1, Abschnitte A–I): je Schritt eine Datei.

    import erfassung as e
    e.oeffnen()                                  # Projekt öffnen (A)
    e.platte.registrieren("HD07", Path("/Volumes/…"))
    e.schnellscan.schnellscan("HD07", Path("/Volumes/…"))
    …

Notebook 1 ruft diese Funktionen je Abschnitt auf; das Tool Balduin startet sie später im Hintergrund.
"""
from . import (anton, archiv, duplikate, formate, metadaten, personen, platte, pruefsummen, schnellscan, texte,
               uebersicht, vergleich, virenscan, vorschau)
from .basis import P, db, oeffnen, platz_pruefen, protokolliere, speicher_melden, virenfunde

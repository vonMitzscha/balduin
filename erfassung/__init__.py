"""Erfassung der Datenträger (Modul 1, Schritte B–I): je Schritt eine Datei.

    import erfassung as e
    e.oeffnen()                                  # Projekt öffnen (A)
    e.platte.registrieren("HD07", Path("/Volumes/…"))
    e.schnellscan.schnellscan("HD07", Path("/Volumes/…"))
    …

Balduin startet sie als Lauf im Hintergrund (erfassung/lauf.py).
"""
from . import (anton, archiv, duplikate, formate, metadaten, personen, platte, pruefsummen, schnellscan, texte,
               uebersicht, vergleich, virenscan, vorschau)
from .basis import P, db, oeffnen, platz_pruefen, protokolliere, speicher_melden, virenfunde

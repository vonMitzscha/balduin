"""Vorlauf: Vorverarbeitung für die Erschließung (Entscheidungen 03.11.2026 in docs/plan.md).

Liest nur die Datenbank, die Vorschaubilder und das öffentliche Anton-Vokabular, nie die Quellplatten. Läuft als
Hintergrundlauf der Art „vorlauf“ über erfassung/lauf.py (gleiche Warteschlange wie Modul 1); der Umfang (nur
Übernommenes oder alles) steht in der Tabelle vorlauf_umfang. Jeder Schritt schreibt nur Vorschläge (Tabelle vorschlag),
nie Werte der Erschließung, und ersetzt dabei nur seine eigenen; Urteile (vorschlag_urteil) bleiben.

    gemeinsam    Umfang, Textregeln, Liste des Unbrauchbaren, Vorschläge schreiben
    pfade        V5 Pfade und Namen: Datum, Wörter und Ordnertitel nach allgemeinen Mustern
    metadaten    V7 Metadaten verteilen: Titel, Inhalt, Urheber:in, Ort, Schlagworte aus den Daten von Modul 1
    normdaten    V8 Normdaten: Anton-Vokabular holen, Kandidaten zuordnen, gelernte Synonyme
    verwandte    V10 Verwandte Ordner: Duplikate, gleicher Tag + Kamera, Ordnername
    sprachmodell Vorschlag vom Sprachmodell auf Abruf (Erschließung), kein Lauf
"""

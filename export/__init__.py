"""Modul 4 Bestand und Export: Pakete im Anton-Importformat bauen und auf die Ablage schreiben (Entscheidungen 04. und
05.11.2026 in docs/plan.md). Den Import startet Kränzle & Ritter auf dem Server (SSH); Balduin lädt nichts hoch.

Was in ein Paket gehört, plant der Server (tool/pakete.py): Er kennt die wirksamen Entscheidungen und schreibt Pakete
und Einträge der metadata.json in die Tabellen paket und paket_eintrag. Dieses Paket rechnet nur damit:

    schema       Tabellen (auch vom Server angelegt)
    bauen        metadata.json gegen das Schema prüfen; BagIt-tar aus der eingehängten Platte (nur lesend) auf die
                 Ablage, dabei MD5 und SHA-256 jeder Datei gegen die Datenbank; fortsetzbar; nachprüfen; Lieferschein

Läuft als Hintergrundlauf der Art „export“ über erfassung/lauf.py (Schritte X0 Datenbank sichern, X1 Pakete
schreiben, X2 Pakete nachprüfen).
"""

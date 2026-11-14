# Anton-Importformat (JSON-Schema)

`anton-import-0.6.schema.json` ist eine unveränderte Kopie von `schema/anton-import.schema.json` aus
https://github.com/kraenzle-ritter/anton-import-format (Commit `4962c39`, 29.10.2026, `$id`
`https://kraenzle-ritter.ch/schemas/anton-import/0.6/schema.json`), Lizenz MIT, © Kraenzle & Ritter.

`anton-import-0.8.schema.json` ist ebenso eine unveränderte Kopie derselben Datei am Tag `v0.8.0` (Commit `e4173e9`,
06.11.2026, `$id` `https://kraenzle-ritter.ch/schemas/anton-import/0.8/schema.json`). Neu gegenüber 0.6: `actors[]` an
Collection- und Record-Einträgen (0.8, anton#825) und `resources[]` an Normdaten (0.7, GND/Wikidata; Balduin nutzt es
noch nicht). `actors[]` schreibt Balduin nur, wenn die Instanz 0.8 liest (`export/bauen.py` → `fuer_version`).

Gegen dieses Schema prüft Modul 4 jede `metadata.json`, bevor ein Paket entsteht (Python-Paket `jsonschema`,
Draft 2020-12 mit Formatprüfung). Dasselbe Schema nutzen agate und Anton (Entscheidung 04.11.2026, `docs/plan.md`).

Neue Version: Datei als `anton-import-<Version>.schema.json` daneben legen; Balduin nimmt die höchste Version, die
die Zielinstanz liest (`GET /api/import-format` → `reads`).

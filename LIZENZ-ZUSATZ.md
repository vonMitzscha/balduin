# Zusätzliche Bestimmungen nach § 7 der AGPL-3.0

Balduin – © 2026 Marc Eric Mitzscherling

Balduin ist freie Software: Sie dürfen es unter den Bedingungen der GNU Affero General Public License, wie von der
Free Software Foundation veröffentlicht, weitergeben und verändern, entweder gemäß Version 3 der Lizenz oder (nach
Ihrer Wahl) jeder späteren Version (`LICENSE`). Balduin wird in der Hoffnung verbreitet, dass es nützlich ist, aber
**ohne jede Gewährleistung**, sogar ohne die implizite Gewährleistung der Marktreife oder der Eignung für einen
bestimmten Zweck.

Für Balduin gelten nach § 7 der Lizenz folgende zusätzliche Bestimmungen. Sie sind Teil der Lizenz und gelten für
jede Weitergabe, auch veränderter Fassungen und von Werken, die Balduin ganz oder in Teilen enthalten.

## § 7 b – Nennung des Urhebers

1. Die Urheberangabe „Balduin – © Marc Eric Mitzscherling“ und der Hinweis auf diese Lizenz müssen in allen
   Urheberhinweisen des Quelltexts (`LICENSE`, `LIZENZ-ZUSATZ.md`, `REUSE.toml`, Kopfzeilen von Dateien) erhalten
   bleiben.
2. Die Oberfläche zeigt diese Urheberangabe und den Lizenzhinweis in der Anzeige **„Über Balduin“** (in der
   ursprünglichen Fassung: Klick auf das Zeichen in der Kopfleiste). Abgeleitete Fassungen müssen eine
   gleichwertige, für Nutzende ohne Umwege erreichbare Anzeige mit dieser Urheberangabe behalten, auch wenn sie die
   Oberfläche umgestalten. Weitere Beitragende dürfen dort zusätzlich genannt werden.

## § 7 c – Kennzeichnung veränderter Fassungen

Wer Balduin verändert weitergibt oder Nutzenden über ein Netz zugänglich macht, kennzeichnet seine Fassung in der
Anzeige „Über Balduin“ und in den Urheberhinweisen als verändert (wer, was, wann) und darf sie nicht als die
ursprüngliche Fassung des Urhebers ausgeben.

## § 7 e – Name und Zeichen

Die Lizenz gibt kein Recht, den Namen „Balduin“ oder das Zeichen des Tools (den Elefanten) als Namen oder Zeichen
einer veränderten Fassung, eines Produkts oder eines Dienstes zu verwenden, außer um wahrheitsgemäß die Herkunft zu
beschreiben (etwa „beruht auf Balduin von Marc Eric Mitzscherling“). Das Zeichen beruht auf einem Bild von Pixabay
und steht unter dessen Lizenz (`LICENSES/LicenseRef-Pixabay.txt`), nicht unter der AGPL.

## Was unter welcher Lizenz steht

Welche Datei unter welcher Lizenz steht, verzeichnet `REUSE.toml` (Lizenztexte in `LICENSES/`):

| Teil | Lizenz |
|---|---|
| Code (Python, JavaScript, HTML, CSS, Skripte, Tests) | AGPL-3.0-or-later mit diesem Zusatz |
| Dokumentation (`*.md`, `docs/`) und Regeltabellen (`vorgaben/*.csv`) | CC BY-SA 4.0, Namensnennung „Marc Eric Mitzscherling“ |
| Zeichen (`tool/web/balduin.png`, `docs/logo/`) | Pixabay-Inhaltslizenz |
| Lucide-Symbole (`tool/web/vendor/lucide/`) | ISC |
| Schrift Inter (`tool/web/vendor/inter/`) | SIL Open Font License 1.1 |
| Bootstrap (`vorgaben/web/bootstrap.*`) | MIT |
| JSON-Schema des Anton-Importformats (`vorgaben/anton_import/`) | MIT, © Kraenzle & Ritter |
| NARA Digital Preservation Framework (`vorgaben/nara/`) | gemeinfrei |

Externe Programme (Siegfried, ExifTool, ffmpeg, Poppler, ClamAV) und Python-Pakete gehören nicht zu Balduin und
stehen unter ihren eigenen Lizenzen; Balduin ruft sie auf, liefert sie aber nicht als Teil seines Quelltexts mit.

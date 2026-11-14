"""Nachgebauter Anton-Server für die Tests: beantwortet die Teile der Anton-API, die Balduin liest (Objekte mit Medien,
Stufen, Vokabular, Importformat), nur auf 127.0.0.1 und mit erfundenen Daten. Nie gegen die echte Instanz testen.

Jede Anfrage wird mitgeschrieben (Methode, Pfad, Abfrage, ob ein Token im Header kam), damit Tests prüfen können,
was Balduin hinausschickt (harte Regel 6, Token nur im Header).
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

TOKEN = "test-token-7f3a9c2e1b"          # gilt nur für diesen Nachbau; Tests prüfen, dass er in keiner Datei landet

STUFEN = {"10": "Archiv", "11": "Bestandsgruppe", "12": "Bestand", "13": "Klasse", "14": "Serie", "15": "Dossier",
          "16": "Einzelstück"}

VOKABULAR = {
    "keywords": [{"id": 501, "label": "Messe"}, {"id": 502, "label": "Jubiläum"}, {"id": 503, "label": "Empfang"}],
    "places": [{"id": 601, "label": "Schaffhausen", "location": "POINT(47.6959 8.6346)"}],
    "actors": [{"id": 701, "label": "Müller, Hans", "fullname": "Müller, Hans"}],
}


def objekte(md5_in_anton=None):
    """Bestand des Nachbaus. md5_in_anton: (md5, Dateiname, Größe) einer Datei, die „schon in Anton“ liegt."""
    o = [
        {"id": 100, "identifier": "MA", "title": "Musterarchiv", "level_of_description": "Archiv",
         "parent_id": None, "object_type": "", "permalink": "http://anton.test/objects/100", "media": []},
        {"id": 200, "identifier": "MA-FOTO-1", "title": "Fotosammlung", "level_of_description": "Bestand",
         "parent_id": 100, "object_type": "Fotografie", "object_count": 3, "date": "1950–2010",
         "permalink": "http://anton.test/objects/200", "media": []},
        {"id": 300, "identifier": "MA-INT-1", "title": "Interne Sammlung", "level_of_description": "Bestand",
         "parent_id": 100, "object_type": "", "permalink": "http://anton.test/objects/300", "media": [],
         "_intern": True},
    ]
    if md5_in_anton:
        md5, name, groesse = md5_in_anton
        o.append({"id": 400, "identifier": "MA-FOTO-1-1", "title": "Punkt", "level_of_description": "Einzelstück",
                  "parent_id": 200, "permalink": "http://anton.test/objects/400",
                  "media": [{"id": 9001, "md5sum": md5, "file_name": name, "size": groesse, "mime_type": "image/gif"}]})
    return o


class AntonNachbau:
    """`with AntonNachbau(...) as anton:` startet den Server in einem Faden; anton.url, anton.anfragen."""

    def __init__(self, md5_in_anton=None):
        self.objekte = objekte(md5_in_anton)
        # Formatrichtlinie (GET /api/format-policy/switches); Form der Antwort angenommen, Standard „warn“ (K&R Frage 6)
        self.formatrichtlinie = {"FORMAT_VALIDATION_INVALID": "warn"}
        self.reads = "0.6"                     # GET /api/import-format: Version, die die Instanz liest (Tests ändern sie)
        self.anfragen = []                     # [{methode, pfad, abfrage, token, token_in_url}]
        self.sperre = threading.Lock()
        nachbau = self

        class Anfrage(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def antwort(self, status, daten):
                inhalt = json.dumps(daten, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(inhalt)))
                self.end_headers()
                self.wfile.write(inhalt)

            def do_GET(self):
                url = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(url.query).items()}
                kopf = self.headers.get("Authorization", "")
                with nachbau.sperre:
                    nachbau.anfragen.append({"methode": "GET", "pfad": url.path, "abfrage": url.query,
                                             "token": bool(kopf), "token_in_url": TOKEN in self.path})
                if TOKEN in self.path:
                    return self.antwort(400, {"message": "Token gehört in den Header"})
                if kopf and kopf != f"Bearer {TOKEN}":
                    return self.antwort(401, {"message": "Unauthenticated."})
                intern = kopf == f"Bearer {TOKEN}"
                try:
                    return nachbau.beantworten(self, url.path, q, intern)
                except Exception as e:                # Fehler im Nachbau sichtbar machen statt still abzubrechen
                    return self.antwort(500, {"message": f"Nachbau: {type(e).__name__}: {e}"})

            def do_POST(self):
                url = urlparse(self.path)
                with nachbau.sperre:
                    nachbau.anfragen.append({"methode": "POST", "pfad": url.path, "abfrage": url.query,
                                             "token": bool(self.headers.get("Authorization")),
                                             "token_in_url": TOKEN in self.path})
                self.antwort(405, {"message": "Der Nachbau nimmt nichts an"})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Anfrage)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def sichtbar(self, intern):
        return [o for o in self.objekte if intern or not o.get("_intern")]

    @staticmethod
    def ohne_intern(o):
        return {k: v for k, v in o.items() if not k.startswith("_")}

    def beantworten(self, h, pfad, q, intern):
        if pfad == "/api/objects":
            liste = self.sichtbar(intern)
            if "ids" in q:
                ids = {int(x) for x in q["ids"].split(",") if x.strip().isdigit()}
                return h.antwort(200, {"data": [self.ohne_intern(o) for o in liste if o["id"] in ids],
                                       "meta": {"total": len(ids), "last_page": 1}})
            if "identifier" in q:                      # wie Anton: ein Treffer als einzelnes Objekt, sonst []
                treffer = [o for o in liste if o["identifier"] == q["identifier"]]
                return h.antwort(200, {"data": self.ohne_intern(treffer[0]) if treffer else [],
                                       "meta": {"total": len(treffer), "last_page": 1}})
            je_seite = max(1, int(q.get("perPage", 25)))
            seite = max(1, int(q.get("page", 1)))
            letzte = max(1, -(-len(liste) // je_seite))
            teil = liste[(seite - 1) * je_seite: seite * je_seite]
            return h.antwort(200, {"data": [self.ohne_intern(o) for o in teil],
                                   "meta": {"total": len(liste), "last_page": letzte, "current_page": seite}})
        if pfad == "/api/levels-of-description":
            return h.antwort(200, STUFEN)
        if pfad == "/api/import-format":
            return h.antwort(200, {"reads": self.reads})
        if pfad == "/api/format-policy/switches":
            return h.antwort(200, dict(self.formatrichtlinie))
        if pfad in ("/api/keywords", "/api/places", "/api/actors"):
            daten = VOKABULAR[pfad.rsplit("/", 1)[1]]
            return h.antwort(200, {"data": daten, "meta": {"total": len(daten), "last_page": 1}})
        return h.antwort(404, {"message": f"Nachbau kennt {pfad} nicht"})

    def __enter__(self):
        self.faden = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.faden.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()

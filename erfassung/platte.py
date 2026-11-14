"""B Platte registrieren: Angaben zur Platte, Wiedererkennung, Übersicht, schreibgeschützt einhängen."""
from .basis import *  # noqa: F401,F403
from . import macplatte, quelle, system


# B1 Hilfsfunktionen für Plattenangaben
def ist_schreibgeschuetzt(pfad):
    """Ist die Platte schreibgeschützt eingehängt? (erfassung/system.py, auch für Windows)"""
    return system.ist_schreibgeschuetzt(pfad)


def platteninfo(pfad):
    info = datentraeger_info(pfad)
    gesamt, _belegt, frei = shutil.disk_usage(pfad)
    return {
        "volume_name": info.get("VolumeName") or Path(pfad).name,
        "volume_uuid": info.get("VolumeUUID") or info.get("DiskUUID") or "",
        "volume_kennungen": system.kennungen(info),       # mit früherer Form (FAT/exFAT unter Windows/Linux)
        "geraet": info.get("DeviceIdentifier", ""),
        "modell": info.get("MediaName", ""),
        "anschluss": info.get("BusProtocol", ""),
        "dateisystem": info.get("FilesystemName") or info.get("FilesystemType", ""),
        "kapazitaet_bytes": info.get("TotalSize") or gesamt,
        "frei_bytes": info.get("FreeSpace") or info.get("APFSContainerFree") or frei,
        "traeger": system.traegerart(info),             # cd, usb, karte, image, festplatte; "" = unbekannt
    }


def ersatzmerkmale(info):
    """Merkmale, an denen ein Datenträger ohne Volume-UUID wiedererkannt wird (z. B. CD/DVD mit ISO 9660
    oder UDF): Volume-Name, Dateisystem und Gesamtgröße. Der freie Platz zählt nicht, er ändert sich.
    info: Ergebnis von platteninfo() oder eine Zeile der Tabelle platte."""
    def wert(schluessel):
        x = info.get(schluessel)
        return "" if x is None or pd.isna(x) else x
    return str(wert("volume_name")), str(wert("dateisystem")), int(wert("kapazitaet_bytes") or 0)


def merkmale_text(merkmale):
    name, dateisystem, groesse = merkmale
    return f"„{name}“, {dateisystem or 'Dateisystem unbekannt'}, {groesse / 1e9:.2f} GB"


def stichprobe_pruefen(platte_id, wurzel, anzahl=20):
    """Zieht zufällige Dateien aus dem Schnellscan und prüft, ob sie unter wurzel mit gleicher Größe liegen.
    Systemdateien zählen nicht mit (z. B. .DS_Store ändert sich auf beschreibbaren Sticks).
    Gibt die Zahl der geprüften Dateien und die Liste der fehlenden oder abweichenden Pfade zurück."""
    with db() as con:
        # nur frei liegende Dateien: die in Archivdateien lassen sich nicht über ihren Pfad finden
        proben = con.execute(f"SELECT relpfad, groesse FROM schnellscan WHERE platte_id = ? AND archiv IS NULL "
                             f"AND name NOT IN ({','.join('?' * len(SYSTEMDATEIEN))}) ORDER BY RANDOM() LIMIT ?",
                             (platte_id, *SYSTEMDATEIEN, anzahl)).fetchall()
    abweichend = []
    for relpfad, groesse in proben:
        try:
            if quelle.stat(wurzel, relpfad)[0] != groesse:
                abweichend.append(relpfad)
        except OSError:
            abweichend.append(relpfad)
    return len(proben), abweichend


def smart_status(geraet):
    """SMART-Gesundheitswert über smartctl (brew install smartmontools; erfassung/system.py).
    Viele USB-Gehäuse reichen SMART nicht durch; dann steht hier „nicht lesbar“."""
    return system.smart_status(geraet)


def angeschlossene_platte_pruefen(platte_id, wurzel):
    """Stellt sicher, dass unter MOUNTPUNKT die registrierte Platte hängt und ein Schnellscan vorliegt.
    Ohne Volume-UUID (z. B. CD/DVD) gilt die Ersatzprüfung: Name, Dateisystem, Größe und eine Stichprobe von Dateien.
    Wird von D, E und F vor dem Lesen aufgerufen."""
    with db() as con:
        z = con.execute("SELECT volume_uuid, volume_name, dateisystem, kapazitaet_bytes, art, quellordner FROM platte "
                        "WHERE platte_id = ?", (platte_id,)).fetchone()
        n = con.execute("SELECT COUNT(*) FROM schnellscan WHERE platte_id = ?", (platte_id,)).fetchone()[0]
        # ein leerer Datenträger hat einen fertigen Schnellscan ohne Dateien (13.11.2026)
        n = n or con.execute("SELECT COUNT(*) FROM scanlauf WHERE platte_id = ? AND art = 'schnellscan' "
                             "AND ende IS NOT NULL", (platte_id,)).fetchone()[0]
    if z is None:
        raise ValueError(f"{platte_id} ist nicht registriert. Erst Abschnitt B ausführen.")
    if n == 0:
        raise ValueError(f"Für {platte_id} gibt es keinen Schnellscan. Erst C1 ausführen.")
    if z[4] == "ordner":                                  # Ordner als Quelle: gespeicherter Ort und Stichprobe
        ordner_wiedererkennen(platte_id, wurzel, z[5])
        return
    if z[4] == "abbild":                                  # Abbild: gespeicherter Ort, Kennung und Stichprobe
        abbild_wiedererkennen(platte_id, wurzel, z[5], z[0])
        return
    if z[4] == "macplatte":                               # Mac-Platte unter Windows: Kennung des Volumes, Stichprobe
        gefunden = abbildinfo(wurzel)["volume_uuid"]
        if z[0] and gefunden != z[0]:
            raise ValueError(f"An {wurzel} hängt ein anderer Datenträger ({gefunden}) als {platte_id} ({z[0]}).")
        geprueft, abweichend = stichprobe_pruefen(platte_id, wurzel)
        if abweichend:
            raise ValueError(f"Auf {platte_id} fehlen {len(abweichend)} von {geprueft} Stichprobendateien oder haben "
                             f"eine andere Größe, z. B. {abweichend[0]}.")
        print(f"✓ {platte_id} ist ein Mac-Datenträger; erkannt an der Volume-UUID und {geprueft} Stichprobendateien. "
              "Sie wird nur gelesen.")
        return
    z = z[:4]
    info = platteninfo(wurzel)
    if z[0]:
        if z[0] not in (info["volume_kennungen"] or [info["volume_uuid"]]):
            raise ValueError(f"Unter {wurzel} hängt ein anderer Datenträger (UUID {info['volume_uuid']}) "
                             f"als {platte_id} (UUID {z[0]}).")
    else:
        erwartet = ersatzmerkmale(dict(zip(("volume_name", "dateisystem", "kapazitaet_bytes"), z[1:])))
        if ersatzmerkmale(info) != erwartet:
            raise ValueError(f"Unter {wurzel} hängt offenbar nicht {platte_id}: erwartet {merkmale_text(erwartet)}, "
                             f"gefunden {merkmale_text(ersatzmerkmale(info))}.")
        geprueft, abweichend = stichprobe_pruefen(platte_id, wurzel)
        if abweichend:
            raise ValueError(f"Unter {wurzel} fehlen {len(abweichend)} von {geprueft} Stichprobendateien von {platte_id} "
                             f"oder haben eine andere Größe, z. B. {abweichend[0]}. Liegt der richtige Datenträger ein?")
        print(f"✓ {platte_id} hat keine Volume-UUID; erkannt an Name, Dateisystem, Größe "
              f"und {geprueft} Stichprobendateien.")
    if not ist_schreibgeschuetzt(wurzel):
        print("⚠ Der Datenträger ist beschreibbar eingehängt. Empfohlen: in B5 schreibgeschützt einhängen.")


def oeffne(wurzel, relpfad):
    """Öffnet eine Datei der Platte zum Lesen (Pfad in NFC oder NFD, siehe quellpfad in A2), auch eine Datei in einer
    Archivdatei (Pfad <Archivdatei>/<Pfad darin>, Entscheidung 06.11.2026) oder in einem Abbild (erfassung/quelle.py)."""
    try:
        return quelle.oeffnen(wurzel, relpfad)
    except (FileNotFoundError, NotADirectoryError):
        from . import archivdateien
        return archivdateien.oeffnen(wurzel, relpfad)


# B6 Teile einer Platte (Umfang) und Ordner als Quelle (Entscheidungen 05.11.2026, docs/plan.md)

def umfang_normalisieren(umfang):
    """Liste relativer Ordner der Platte → sortiert, ohne Doppel und ohne Ordner, die in einem anderen schon enthalten
    sind. „“ oder „.“ heißt ganze Platte und ergibt []. Pfade mit „..“ oder absolute Pfade sind unzulässig."""
    teile = set()
    for u in umfang or []:
        u = nfc(str(u)).strip()
        if u.startswith("/") or "\\" in u:
            raise ValueError(f"„{u}“ ist kein Ordner relativ zum Datenträger.")
        u = u.strip("/")
        if u in ("", "."):
            return []
        if any(t in ("", ".", "..") for t in u.split("/")):
            raise ValueError(f"„{u}“ ist kein Ordner relativ zum Datenträger.")
        teile.add(u)
    return sorted(t for t in teile if not any(t.startswith(a + "/") for a in teile))


def umfang_enthaelt(alt, neu):
    """Liest der Umfang neu alles, was alt las? [] = ganze Platte."""
    if not neu:
        return True
    if not alt:
        return False
    return all(any(a == n or a.startswith(n + "/") for n in neu) for a in alt)


def umfang_text(umfang):
    return "den ganzen Datenträger" if not umfang else ", ".join(f"„{u}“" for u in umfang)


def umfang_pruefen(platte_id, umfang, wurzel, bisher=None):
    """Normalisierter neuer Umfang; ValueError, wenn er nicht alles Bisherige enthält (er kann nur wachsen) oder ein
    Ordner unter wurzel fehlt. bisher None: aus der Datenbank (bei einer neuen Platte nichts)."""
    if bisher is None:
        with db() as con:
            z = con.execute("SELECT umfang FROM platte WHERE platte_id = ?", (platte_id,)).fetchone()
        bisher = None if z is None else (json.loads(z[0]) if z[0] else [])
    neu = umfang_normalisieren(umfang)
    if bisher is not None and not umfang_enthaelt(bisher, neu):
        raise ValueError(f"Der Umfang von {platte_id} kann nur wachsen (bisher {umfang_text(bisher)}, neu "
                         f"{umfang_text(neu)}). Was nicht ins Archiv soll, in der Bewertung kassieren.")
    fehlt = [u for u in neu if not quelle.ist_ordner(wurzel, u)]
    if fehlt:
        raise ValueError(f"Den Ordner {fehlt[0]} gibt es nicht unter {wurzel}.")
    return neu


def umfang_lesen(platte_id):
    """Umfang einer registrierten Platte ([] = ganze Platte)."""
    with db() as con:
        z = con.execute("SELECT umfang FROM platte WHERE platte_id = ?", (platte_id,)).fetchone()
    return json.loads(z[0]) if z and z[0] else []


def ist_ordner(platte_id):
    with db() as con:
        z = con.execute("SELECT art FROM platte WHERE platte_id = ?", (platte_id,)).fetchone()
    return bool(z and z[0] == "ordner")


def art_der_quelle(platte_id):
    """„ordner“, „abbild“ oder „“ (Datenträger) einer registrierten Quelle; None = nicht registriert."""
    with db() as con:
        z = con.execute("SELECT art FROM platte WHERE platte_id = ?", (platte_id,)).fetchone()
    return None if z is None else (z[0] or "")


def ordnerinfo(pfad):
    """Angaben zu einem Ordner als Quelle in der Form von platteninfo(): ohne UUID, ohne diskutil (plattformneutral)."""
    return {"volume_name": Path(pfad).name, "volume_uuid": "", "geraet": "", "modell": "", "anschluss": "",
            "dateisystem": "Ordner", "kapazitaet_bytes": None, "frei_bytes": None, "smart_status": "",
            "traeger": "ordner"}


def ueberschneiden(a, b):
    """Ist a gleich b, in b enthalten oder enthält a b?"""
    return a == b or a in b.parents or b in a.parents


def nicht_in_arbeitsorten(p):
    """ValueError, wenn p im oder über Projekt, Code, Vorschaubildern, Arbeitsplatte oder Ablage liegt: dort liegt kein
    Quellbestand, und dort schreibt Balduin (Ordner und Abbilder als Quelle, harte Regel 1)."""
    geschuetzt = [("dem Projekt", P.ordner), ("dem Code von Balduin", CODE), ("den Vorschaubildern", P.vorschauen),
                  ("des Datenträgers für Vorschaubilder", P.arbeitsplatte), ("der Ablage der Pakete", P.export)]
    if P.export_wurzel is not None and Path(P.export_wurzel) != P.ordner:
        geschuetzt.append(("dem Datenträger der Ablage", P.export_wurzel))
    for name, g in geschuetzt:
        if g is not None and ueberschneiden(p, Path(nfc(str(Path(g).resolve())))):
            raise ValueError(f"{p} überschneidet sich mit {name} ({g}). Dort liegt kein Quellbestand.")


def abbild_pruefen(pfad):
    """Taugt pfad als Abbild-Quelle (Entscheidung 09.11.2026)? Eine Datei außerhalb der Arbeitsorte von Balduin mit
    einem lesbaren HFS+- oder APFS-Dateisystem. Antwort: (aufgelöster Pfad, Volumes); sonst ValueError mit Grund."""
    roh = Path(pfad)
    if not roh.is_absolute() or not roh.is_file():
        raise ValueError(f"{roh} gibt es nicht oder ist keine Datei.")
    p = Path(nfc(str(roh.resolve())))
    nicht_in_arbeitsorten(p)
    vs = [v for v in macplatte.volumes(p) if "fehler" not in v]
    if not vs:
        raise ValueError(f"{p.name} enthält kein HFS+- oder APFS-Dateisystem, das sich lesen lässt (komprimierte "
                         ".dmg vorher unkomprimiert speichern).")
    return p, vs


def macgeraet_pruefen(geraet):
    """Mac-Platte an einem Windows-Rechner (Entscheidung 09.11.2026): Angaben zum Gerät und seine Volumes. Liest die
    Platte (unter Windows mit Rückfrage nach Administratorrechten über den Türöffner)."""
    name = system.geraet_name(geraet)
    if name is None or not system.ist_geraet(name):
        raise ValueError(f"{geraet} ist kein physischer Datenträger.")
    angaben = next((d for d in system.physische_datentraeger() if d["geraet"] == name), {})
    vs = [v for v in macplatte.volumes(name) if "fehler" not in v]
    if not vs:
        raise ValueError(f"Auf {angaben.get('modell') or name} liegt kein HFS+- oder APFS-Dateisystem, das sich lesen "
                         "lässt.")
    return {"geraet": name, **{k: angaben.get(k) for k in ("modell", "seriennummer", "anschluss", "groesse")},
            "volumes": [{k: v[k] for k in ("name", "dateisystem", "uuid", "gesperrt", "groesse")} for v in vs],
            "erkannt": mac_wiedererkennen(angaben, [v["uuid"] for v in vs if v.get("uuid")])}


def mac_wiedererkennen(angaben, uuids):
    """Gehört ein Volume dieser Platte zu einer registrierten Mac-Platte, ist sie es: Kennung des Geräts nachtragen
    (sie hing vorher woanders oder ist mit der Seriennummer vom 09.–13.11.2026 registriert), protokolliert.
    Antwort: die Kennung im Projekt oder „“."""
    if not uuids:
        return ""
    with db() as con:
        z = con.execute(f"SELECT platte_id, geraet FROM platte WHERE art = 'macplatte' AND volume_uuid IN "
                        f"({','.join('?' * len(uuids))}) ORDER BY platte_id", uuids).fetchall()
    if len(z) != 1:                                   # keine oder mehrere (Klone): nicht raten
        return ""
    platte_id, alt = z[0]
    neu = geraet_kennung(angaben)
    if neu and neu != alt:
        with db() as con:
            con.execute("UPDATE platte SET geraet = ? WHERE platte_id = ?", (neu, platte_id))
        protokolliere("B", platte_id, "geraet", alt, neu)
    return platte_id


def geraet_kennung(geraet):
    """Woran eine Mac-Platte ohne Administratorrechte wiedererkannt wird (steht in platte.geraet): die Kennung der
    Partitionstabelle, sonst die Seriennummer. Die Seriennummer allein täuscht bei Gehäusen ohne eigene (UTM-Test
    13.11.2026: nach dem Umstecken galt eine andere Platte als die registrierte)."""
    return geraet.get("tabelle") or geraet.get("seriennummer") or ""


def passt_zum_geraet(gespeichert, geraet):
    """Hängt die mit gespeichert registrierte Platte an diesem Gerät? Bis 13.11.2026 stand dort die Seriennummer."""
    if not gespeichert:
        return False
    if gespeichert.startswith(("GPT:", "MBR:")):
        return gespeichert == geraet.get("tabelle")
    return gespeichert == geraet.get("seriennummer") and not geraet.get("tabelle")


def macplatten_liste():
    """Registrierte Mac-Platten (Windows, Linux) mit dem Gerät, an dem sie gerade hängen: wiedererkannt ohne
    Administratorrechte an der Kennung der Partitionstabelle (die Gerätenummer wechselt bei jedem Anschließen)."""
    with db() as con:
        zeilen = con.execute("SELECT platte_id, volume_name, geraet FROM platte WHERE art = 'macplatte' "
                             "ORDER BY platte_id").fetchall()
    geraete = system.physische_datentraeger() if zeilen else []
    liste = []
    for k, name, serie in zeilen:
        d = next((d for d in geraete if passt_zum_geraet(serie, d)), None)
        liste.append({"platte_id": k, "pfad": d["geraet"] if d else "", "name": name, "art": "macplatte", "da": bool(d)})
    return liste


def abbildinfo(pfad):
    """Angaben zum Volume eines Abbilds in der Form von platteninfo() (Kennung wie macOS sie nennt)."""
    i = quelle.volume(pfad).info
    return {"volume_name": i["VolumeName"], "volume_uuid": i["VolumeUUID"] or "", "geraet": "", "modell": "",
            "anschluss": "Disk Image", "dateisystem": i["FilesystemName"], "kapazitaet_bytes": i["TotalSize"],
            "frei_bytes": None, "smart_status": "", "traeger": "image", "verschluesselt": int(bool(i.get("Verschluesselt")))}


def abbild_wiedererkennen(platte_id, wurzel, gespeichert, uuid):
    """Vor D, E, F und dem Packen: Ist es das registrierte Abbild (Ort, Kennung des Volumes, Stichprobe)?"""
    wurzel = Path(nfc(str(Path(wurzel).resolve())))
    if Path(gespeichert) != wurzel:
        raise ValueError(f"{platte_id} ist als Abbild {gespeichert} registriert, nicht {wurzel}. Ist es verschoben, "
                         "zuerst in Balduin den neuen Ort wählen.")
    gefunden = abbildinfo(wurzel)["volume_uuid"]
    if uuid and gefunden != uuid:
        raise ValueError(f"In {wurzel.name} liegt ein anderer Datenträger ({gefunden}) als {platte_id} ({uuid}).")
    geprueft, abweichend = stichprobe_pruefen(platte_id, wurzel)
    if abweichend:
        raise ValueError(f"In {wurzel.name} fehlen {len(abweichend)} von {geprueft} Stichprobendateien von {platte_id} "
                         f"oder haben eine andere Größe, z. B. {abweichend[0]}.")
    print(f"✓ {platte_id} ist ein Abbild; erkannt am Ort, an der Kennung und an {geprueft} Stichprobendateien. "
          "Es wird nur gelesen.")


def quellordner_pruefen(pfad, platte_id=None):
    """Taugt pfad als Ordner-Quelle? Gibt den aufgelösten Pfad zurück oder wirft ValueError mit dem Grund.
    Nicht zulässig: was es nicht gibt, / und der Benutzerordner selbst, ein ganzer Datenträger (dafür „Datenträger“),
    Ordner im oder über Projekt, Code, Vorschaubildern, Arbeitsplatte oder Ablage, Überschneidung mit einer anderen
    registrierten Ordner-Quelle und Ordner auf einer registrierten Platte (dafür deren Umfang erweitern).
    Gelesen werden nur Angaben, keine Dateien."""
    roh = Path(pfad)
    if not roh.is_absolute() or not roh.is_dir():
        raise ValueError(f"{roh} gibt es nicht oder ist kein Ordner.")
    p = Path(nfc(str(roh.resolve())))
    if p == Path(p.anchor) or p == Path(nfc(str(Path.home().resolve()))):
        raise ValueError(f"{p} ist zu allgemein. Bitte den Ordner wählen, der den Bestand enthält.")
    volumes = P.volumes if system.standard_volumes(P.volumes) else Path(nfc(str(P.volumes.resolve())))
    if p == volumes or system.ist_datentraeger(p, volumes):
        raise ValueError(f"{p} ist ein ganzer Datenträger. Bitte links unter „Datenträger“ wählen.")
    nicht_in_arbeitsorten(p)
    with db() as con:
        quellen = con.execute("SELECT platte_id, quellordner FROM platte WHERE art = 'ordner'").fetchall()
    for kennung, q in quellen:
        if kennung != platte_id and q and ueberschneiden(p, Path(nfc(q))):
            raise ValueError(f"{p} überschneidet sich mit der Quelle {kennung} ({q}).")
    traeger = system.datentraeger_von(p, volumes)
    if traeger is not None:
        kennungen = registriert_als(platteninfo(traeger), registrierte_platten())
        if kennungen:
            raise ValueError(f"{p} liegt auf {kennungen[0]}, der schon registriert ist. Teile eines registrierten Datenträgers "
                             f"nimmt man über seinen Umfang auf: {kennungen[0]} wählen und „Umfang erweitern“.")
    return p


def quellordner_liste():
    """Registrierte Ordner- und Abbild-Quellen mit Pfad und ob sie gerade dort liegen (für Tool und Export)."""
    with db() as con:
        zeilen = con.execute("SELECT platte_id, quellordner, art FROM platte WHERE art IN ('ordner', 'abbild') "
                             "ORDER BY platte_id").fetchall()
    return [{"platte_id": k, "pfad": q, "name": Path(q).name, "art": a,
             "da": Path(q).is_file() if a == "abbild" else Path(q).is_dir()} for k, q, a in zeilen] + macplatten_liste()


def ordner_wiedererkennen(platte_id, wurzel, quellordner):
    """Vor D, E, F und dem Packen: Liegt die Ordner-Quelle am gespeicherten Ort, und stimmt die Stichprobe?"""
    wurzel = Path(nfc(str(Path(wurzel).resolve())))
    if Path(quellordner) != wurzel:
        raise ValueError(f"{platte_id} ist als Ordner {quellordner} registriert, nicht {wurzel}. Ist er verschoben, "
                         "zuerst in Balduin den neuen Ort wählen.")
    geprueft, abweichend = stichprobe_pruefen(platte_id, wurzel)
    if abweichend:
        raise ValueError(f"In {wurzel} fehlen {len(abweichend)} von {geprueft} Stichprobendateien von {platte_id} "
                         f"oder haben eine andere Größe, z. B. {abweichend[0]}. Hat sich der Ordner verändert?")
    print(f"✓ {platte_id} ist ein Ordner als Quelle; erkannt am Ort und an {geprueft} Stichprobendateien. "
          "Er wird nur gelesen.")


def quelle_verlegen(platte_id, pfad):
    """Neuer Ort einer verschobenen Ordner-Quelle oder eines verschobenen Abbilds (13.11.2026)."""
    with db() as con:
        z = con.execute("SELECT art FROM platte WHERE platte_id = ?", (platte_id,)).fetchone()
    return abbild_verlegen(platte_id, pfad) if z and z[0] == "abbild" else ordner_verlegen(platte_id, pfad)


def abbild_verlegen(platte_id, pfad):
    """Neuer Ort eines verschobenen Abbilds: nur, wenn dort dasselbe Volume liegt (Kennung) und die Stichprobe aus dem
    Schnellscan stimmt. Ein verschlüsseltes Volume wird nur an der Kennung erkannt (ohne Passwort keine Stichprobe)."""
    with db() as con:
        z = con.execute("SELECT quellordner, volume_uuid, verschluesselt FROM platte WHERE platte_id = ? AND art = 'abbild'",
                        (platte_id,)).fetchone()
    if z is None:
        raise ValueError(f"{platte_id} ist kein registriertes Abbild.")
    neu, vs = abbild_pruefen(pfad)
    if z[1] not in [v["uuid"] for v in vs]:
        raise ValueError(f"In {neu.name} liegt ein anderer Datenträger als {platte_id} ({z[1]}). Ist es das richtige Abbild?")
    quelle.anmelden(neu, z[1])
    geprueft = 0
    if not z[2]:
        geprueft, abweichend = stichprobe_pruefen(platte_id, neu)
        if abweichend:
            raise ValueError(f"Stichprobe: In {neu.name} fehlen {len(abweichend)} von {geprueft} Dateien von {platte_id} "
                             f"oder haben eine andere Größe, z. B. {abweichend[0]}. Ist es das richtige Abbild?")
    if str(neu) != z[0]:
        with db() as con:
            con.execute("UPDATE platte SET quellordner = ? WHERE platte_id = ?", (str(neu), platte_id))
        protokolliere("B", platte_id, "quellordner", z[0] or "", str(neu))
    print(f"{platte_id}: Abbild liegt jetzt unter {neu} (Kennung, Stichprobe {geprueft} Dateien).")
    return {"pfad": str(neu), "geprueft": geprueft}


def ordner_verlegen(platte_id, pfad):
    """Neuer Ort einer verschobenen Ordner-Quelle: nur, wenn die Stichprobe aus dem Schnellscan dort stimmt."""
    with db() as con:
        z = con.execute("SELECT art, quellordner FROM platte WHERE platte_id = ?", (platte_id,)).fetchone()
    if z is None or z[0] != "ordner":
        raise ValueError(f"{platte_id} ist kein registrierter Ordner.")
    neu = quellordner_pruefen(pfad, platte_id)
    geprueft, abweichend = stichprobe_pruefen(platte_id, neu)
    if abweichend:
        raise ValueError(f"Stichprobe: In {neu} fehlen {len(abweichend)} von {geprueft} Dateien von {platte_id} "
                         f"oder haben eine andere Größe, z. B. {abweichend[0]}. Ist es der richtige Ordner?")
    if str(neu) != z[1]:
        with db() as con:
            con.execute("UPDATE platte SET quellordner = ?, volume_name = ? WHERE platte_id = ?",
                        (str(neu), neu.name, platte_id))
        protokolliere("B", platte_id, "quellordner", z[1] or "", str(neu))
    print(f"{platte_id}: Ordner liegt jetzt unter {neu} (Stichprobe {geprueft} Dateien).")
    return {"pfad": str(neu), "geprueft": geprueft}


def unterordner(wurzel, relpfad=""):
    """Ordner direkt unter relpfad einer Quelle (für die Wahl des Umfangs), ohne Systemordner und versteckte; nur lesen."""
    rel = "/".join(umfang_normalisieren([relpfad])[0:1]) if relpfad not in ("", ".") else ""
    return [{"name": name, "pfad": f"{rel}/{name}" if rel else name, "unterordner": unter}
            for name, unter in quelle.unterordner(wurzel, rel)]


def ohne_schreibschutz_gelesen(platte_id):
    """Vermerkt, dass ein Lauf den Datenträger ohne Schreibschutz liest (Entscheidung 13.11.2026): Zustimmung, wenn
    noch keine dasteht, und das erste Lesen (für die Bestandsgeschichte); beides nur einmal, protokolliert."""
    zeit = jetzt()
    with db() as con:
        vorher = con.execute("SELECT zugestimmt_am, gelesen_am FROM schreibschutz_verzicht WHERE platte_id = ?",
                             (platte_id,)).fetchone()
        if vorher and vorher[1]:
            return
        con.execute("INSERT INTO schreibschutz_verzicht (platte_id, zugestimmt_am, gelesen_am) VALUES (?, ?, ?) "
                    "ON CONFLICT (platte_id) DO UPDATE SET gelesen_am = excluded.gelesen_am", (platte_id, zeit, zeit))
    protokolliere("B", platte_id, "ohne Schreibschutz gelesen", "", zeit)


def bereit(mountpunkt):
    """B4 Ist die Platte da und schreibgeschützt? Gibt True zurück, wenn sie schreibgeschützt eingehängt ist."""
    mountpunkt = Path(mountpunkt)
    if not mountpunkt.exists():
        vorhanden = [w.name or str(w) for w in system.datentraeger_liste(P.volumes)]
        raise FileNotFoundError(f"{mountpunkt} gibt es nicht. Angeschlossen sind: {vorhanden}")
    if ist_schreibgeschuetzt(mountpunkt):
        print("✓ Der Datenträger ist schreibgeschützt eingehängt.")
        return True
    print("⚠ Der Datenträger ist beschreibbar eingehängt. Das Betriebssystem legt dann eigene Dateien an.")
    print("  Ohne Schreibschutz liest Balduin ihn nur nach Zustimmung; sonst zuerst schreibgeschützt einhängen.")
    return False


def nur_lesend_einhaengen(pfad):
    """Hängt die Platte aus und schreibgeschützt wieder ein (nur macOS; erfassung/system.py)."""
    neu, meldungen = system.nur_lesend_einhaengen(pfad)
    for m in meldungen:
        print(m)
    print(f"Neu eingehängt unter {neu}. Falls der Pfad anders lautet, MOUNTPUNKT in B3 anpassen.")
    return neu


def registrierte_platten():
    """Registrierte Platten mit Anzahl der Dateien im Schnellscan und im Vollscan."""
    with db() as con:
        return pd.read_sql("""
            SELECT p.*,
                   (SELECT COUNT(*) FROM schnellscan s WHERE s.platte_id = p.platte_id) AS schnellscan_dateien,
                   (SELECT COUNT(*) FROM datei d WHERE d.platte_id = p.platte_id AND d.sha256 IS NOT NULL) AS vollscan_dateien
            FROM platte p ORDER BY p.platte_id""", con)


def naechste_kennung(registriert):
    """Nächste freie Kennung: Kürzel des Projekts (projekt.json, z. B. HD) und zwei Ziffern."""
    kuerzel = P.kennung
    nummern = [int(k[len(kuerzel):]) for k in registriert.platte_id if re.fullmatch(re.escape(kuerzel) + r"\d\d", k)]
    return f"{kuerzel}{max(nummern, default=0) + 1:02d}"


def registriert_als(info, registriert):
    """Kennungen der registrierten Platten zu einem angeschlossenen Datenträger: über die UUID, sonst über die Ersatzmerkmale."""
    if info["volume_uuid"]:
        treffer = registriert[registriert.volume_uuid.isin(info.get("volume_kennungen") or [info["volume_uuid"]])]
    else:
        gleich = [not u and ersatzmerkmale(z) == ersatzmerkmale(info)
                  for u, (_, z) in zip(registriert.volume_uuid.fillna(""), registriert.iterrows())]
        treffer = registriert.loc[pd.Series(gleich, index=registriert.index, dtype=bool)]
    return list(treffer.platte_id)


def ordner_kennung(ordner):
    """Gerät und Inode eines Ordners: gleich für jede Schreibweise desselben Ordners."""
    st = Path(ordner).stat()
    return st.st_dev, st.st_ino


def in_anderen_projekten(projekte):
    """Registrierte Platten anderer Projekte (Feedback 05.11.2026: Warnung, wenn eine Platte schon anderswo
    registriert ist). Die fremden Datenbanken werden nur lesend geöffnet. Antwort: [(Name, Ordner, Tabelle)]."""
    erg = []
    # Dasselbe Projekt kann unter mehreren Schreibweisen bekannt sein (zuletzt.json in NFD, Ordner der Projekte in
    # NFC, Verweise): gleich ist, was auf denselben Ordner zeigt (Gerät und Inode), nicht derselbe Text
    gesehen = {ordner_kennung(P.ordner)}
    for ordner in projekte:
        ordner = Path(ordner)
        db = ordner / "inventar.sqlite"
        if not db.is_file() or ordner_kennung(ordner) in gesehen:
            continue
        gesehen.add(ordner_kennung(ordner))
        try:
            name = json.loads((ordner / "projekt.json").read_text(encoding="utf-8")).get("name") or ordner.name
        except (OSError, ValueError):
            name = ordner.name
        try:
            con = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
            try:
                tabelle = pd.read_sql("""
                    SELECT p.*, (SELECT COUNT(*) FROM datei d WHERE d.platte_id = p.platte_id AND d.sha256 IS NOT NULL)
                           AS analysiert FROM platte p""", con)
            finally:
                con.close()
        except (sqlite3.Error, pd.errors.DatabaseError):
            continue
        if "art" in tabelle:                              # Ordner als Quelle sind keine Datenträger
            tabelle = tabelle[tabelle.art.fillna("") != "ordner"]
        erg.append((name, str(ordner), tabelle))
    return erg


def anderswo_registriert(info, andere):
    """Wo ein angeschlossener Datenträger in anderen Projekten registriert ist (Erkennung wie registriert_als)."""
    treffer = []
    for name, ordner, tabelle in andere:
        for k in registriert_als(info, tabelle):
            z = tabelle[tabelle.platte_id == k].iloc[0]
            treffer.append({"projekt": name, "pfad": ordner, "platte_id": k,
                            "registriert_am": str(z.get("registriert_am") or ""), "analysiert": int(z["analysiert"] or 0)})
    return treffer


def angeschlossene(registriert, andere=()):
    """Angeschlossene Datenträger mit Dateisystem, Größe, UUID, Schreibschutz und Kennung, falls schon registriert.
    Wie im Finder nur sichtbare, wirklich eingehängte Datenträger (system.datentraeger_liste). Gelesen werden nur die
    Angaben zum Datenträger, keine Dateien."""
    liste = []
    for eintrag in system.datentraeger_liste(P.volumes):
        try:
            info = platteninfo(eintrag)
        except OSError as e:
            liste.append({"mountpunkt": str(eintrag), "name": eintrag.name or str(eintrag),
                          "fehler": f"nicht lesbar ({e.strerror})"})
            continue
        arbeitsplatte = eintrag == P.arbeitsplatte
        kennungen = [] if arbeitsplatte else registriert_als(info, registriert)
        liste.append({
            "mountpunkt": str(eintrag), "name": info["volume_name"], "dateisystem": info["dateisystem"],
            "traeger": info["traeger"], "anschluss": info["anschluss"],
            "groesse": info["kapazitaet_bytes"], "uuid": bool(info["volume_uuid"]),
            "schreibgeschuetzt": ist_schreibgeschuetzt(eintrag), "arbeitsplatte": arbeitsplatte,
            "kennungen": kennungen,
            "andere_projekte": [] if arbeitsplatte or kennungen else anderswo_registriert(info, andere)})
    return liste


def arbeitsplatten_angebot(volumes=VOLUMES):
    """Datenträger, die sich als Arbeitsplatte für Vorschaubilder eignen (Assistent „Neues Projekt“): eingehängt,
    sichtbar und beschreibbar; schreibgeschützt eingehängte Quellplatten fallen weg. Gelesen werden nur Angaben."""
    liste = []
    for eintrag in system.datentraeger_liste(volumes):
        try:
            if ist_schreibgeschuetzt(eintrag) or not os.access(eintrag, os.W_OK):
                continue
            info = platteninfo(eintrag)
        except OSError:
            continue
        liste.append({"mountpunkt": str(eintrag), "name": info["volume_name"], "dateisystem": info["dateisystem"],
                      "groesse": info["kapazitaet_bytes"], "frei": shutil.disk_usage(eintrag).free,
                      "uuid": bool(info["volume_uuid"])})
    return liste


def uebersicht():
    """B2 Registrierte Platten (mit Stand der Scans), nächste freie Kennung und angeschlossene Datenträger."""
    registriert = registrierte_platten()
    naechste = naechste_kennung(registriert)
    if registriert.empty:
        print(f"Noch kein Datenträger registriert. Erste Kennung: {naechste}")
    else:
        tabelle = pd.DataFrame({
            "Kennung": registriert.platte_id,
            "Volume-Name": registriert.volume_name,
            "Dateisystem": registriert.dateisystem,
            "Größe (GB)": (registriert.kapazitaet_bytes / 1e9).round(1),
            "erkannt an": ["UUID" if u else "Name, Größe, Stichprobe" for u in registriert.volume_uuid.fillna("")],
            "Etikett (1. Zeile)": [kuerzen((t or "").strip().split("\n")[0], 40) for t in registriert.etikett_text],
            "registriert": registriert.registriert_am.str[:10],
            "Schnellscan": registriert.schnellscan_dateien,
            "Vollscan": registriert.vollscan_dateien,
        }).set_index("Kennung")
        print(f"Registriert: {len(tabelle)} Datenträger. Nächste freie Kennung: {naechste}")
        zeige(tabelle)

    angeschlossen = [{"MOUNTPUNKT": d["mountpunkt"], "registriert als": d["fehler"]} if "fehler" in d else {
        "MOUNTPUNKT": d["mountpunkt"],
        "Dateisystem": d["dateisystem"],
        "Größe (GB)": round(d["groesse"] / 1e9, 1),
        "UUID": "ja" if d["uuid"] else "keine (Ersatzprüfung)",
        "schreibgeschützt": "ja" if d["schreibgeschuetzt"] else "nein",
        "registriert als": "für Vorschaubilder (kein Quellbestand)" if d["arbeitsplatte"]
                           else ", ".join(d["kennungen"]) or "nicht registriert",
    } for d in angeschlossene(registriert)]
    print(f"\nAngeschlossen unter {P.volumes}:")
    zeige(pd.DataFrame(angeschlossen).set_index("MOUNTPUNKT") if angeschlossen else "keine Datenträger")


HAKEN_KLON = "„Gleiche UUID oder gleiche Merkmale sind gewollt“ wählen und in der Notiz vermerken"


def schon_so_registriert(vorher, info):
    """Ist diese Kennung schon mit genau dieser Volume-UUID registriert? Dann wurde die Frage nach einem Klon beim
    ersten Registrieren beantwortet; neue Läufe (neu analysieren, fortsetzen) fragen nicht noch einmal."""
    return bool(vorher.get("volume_uuid")) and vorher["volume_uuid"] == info.get("volume_uuid")


def registrieren(platte_id, mountpunkt, notiz="", etikett="", foto=None, gleiche_uuid_ok=False, umfang=None, art=None):
    """Trägt die angeschlossene Platte ein oder aktualisiert sie. etikett: Text des Plattenetiketts; foto: Pfad zu einem Foto davon.
    gleiche_uuid_ok: nur bei bewusst gleicher UUID (Klon) oder ohne UUID bei gleichen Merkmalen (zwei Exemplare derselben CD).
    umfang: nur diese Ordner der Platte lesen (Liste relativer Pfade, [] = ganze Platte, None = wie bisher); kann nur wachsen.
    art "ordner": mountpunkt ist ein gewöhnlicher Ordner als Quelle; etikett ist dann die Herkunft (Pflicht).
    Entscheidungen 05.11.2026 (docs/plan.md)."""
    with db() as con:
        vorhanden = pd.read_sql("SELECT * FROM platte", con)
    alt = vorhanden[vorhanden.platte_id == platte_id]
    vorher = {k: (None if pd.isna(v) else v) for k, v in alt.iloc[0].items()} if len(alt) else {}

    art = art or vorher.get("art") or None
    ordner, abbild, macgeraet = art == "ordner", art == "abbild", art == "macplatte"
    if vorher and (vorher.get("art") or None) != art:
        raise ValueError(f"{platte_id} ist schon für " + {"ordner": "einen Ordner", "abbild": "ein Abbild"}.get(
            vorher.get("art"), f"einen Datenträger ({vorher.get('volume_name')})") + " vergeben. Bitte eine andere "
            "Kennung wählen.")
    if macgeraet:
        wurzel = system.geraet_name(mountpunkt)
        if wurzel is None or not system.ist_geraet(wurzel):
            raise ValueError(f"{mountpunkt} ist kein physischer Datenträger.")
        geraet = next((d for d in system.physische_datentraeger() if d["geraet"] == wurzel), {})
        info = {**abbildinfo(wurzel), "geraet": geraet_kennung(geraet), "modell": geraet.get("modell") or "",
                "anschluss": geraet.get("anschluss") or "",
                "traeger": system.traegerart({"BusProtocol": geraet.get("anschluss"),
                                              "RemovableMedia": geraet.get("wechselmedium")}) or "festplatte"}
        if vorher.get("volume_uuid") and vorher["volume_uuid"] != info["volume_uuid"]:
            raise ValueError(f"{platte_id} ist schon für einen anderen Datenträger vergeben ({vorher['volume_name']}).")
        gleich = vorhanden[(vorhanden.platte_id != platte_id) & (vorhanden.volume_uuid == info["volume_uuid"])]
        if info["volume_uuid"] and len(gleich) and not (gleiche_uuid_ok or schon_so_registriert(vorher, info)):
            raise ValueError(f"Dieser Datenträger hat dieselbe Volume-UUID wie {gleich.platte_id.iloc[0]}: Es ist derselbe "
                             f"(dann diese Kennung nehmen) oder ein Klon (dann {HAKEN_KLON}).")
    elif abbild:
        wurzel, _ = abbild_pruefen(mountpunkt)
        if vorher.get("quellordner") and Path(vorher["quellordner"]) != wurzel:
            raise ValueError(f"{platte_id} ist als Abbild {vorher['quellordner']} registriert, nicht {wurzel}. "
                             "Ist es verschoben, zuerst den neuen Ort wählen.")
        if not (etikett.strip() or (vorher.get("etikett_text") or "").strip()):
            raise ValueError("Die Herkunft fehlt: Von welchem Datenträger stammt das Abbild (Etikett), wer hat es wann "
                             "erstellt? Sie steht in der Bestandsgeschichte.")
        info = abbildinfo(wurzel)
        if info["volume_uuid"]:
            gleich = vorhanden[(vorhanden.platte_id != platte_id) & (vorhanden.volume_uuid == info["volume_uuid"])]
            if len(gleich) and not (gleiche_uuid_ok or schon_so_registriert(vorher, info)):
                raise ValueError(f"Dieses Abbild hat dieselbe Volume-UUID wie {gleich.platte_id.iloc[0]}: Es ist "
                                 f"derselbe Datenträger (dann diese Kennung nehmen) oder ein Klon (dann {HAKEN_KLON}).")
    elif ordner:
        wurzel = quellordner_pruefen(mountpunkt, platte_id)
        if vorher.get("quellordner") and Path(vorher["quellordner"]) != wurzel:
            raise ValueError(f"{platte_id} ist als Ordner {vorher['quellordner']} registriert, nicht {wurzel}. "
                             "Ist er verschoben, zuerst den neuen Ort wählen.")
        if not (etikett.strip() or (vorher.get("etikett_text") or "").strip()):
            raise ValueError("Die Herkunft fehlt: Woher stammt der Ordner, von wem, seit wann? Sie steht an Stelle des "
                             "Etiketts in der Bestandsgeschichte.")
        info = ordnerinfo(wurzel)
    else:
        wurzel = Path(mountpunkt)
        info = platteninfo(mountpunkt)
        kennungen_jetzt = info.pop("volume_kennungen", None) or [info["volume_uuid"]]   # nicht in die Datenbank
        info["smart_status"] = smart_status(info["geraet"])
        andere_platten = vorhanden[vorhanden.art.fillna("") != "ordner"] if "art" in vorhanden else vorhanden
        ohne_uuid = andere_platten.volume_uuid.fillna("") == ""
        merkmale = ersatzmerkmale(info)
        if info["volume_uuid"]:
            andere = andere_platten[(andere_platten.platte_id != platte_id)
                                    & andere_platten.volume_uuid.isin(kennungen_jetzt)]
        else:
            # ohne UUID (z. B. CD/DVD): Wiedererkennung über Volume-Name, Dateisystem und Größe
            print(f"Hinweis: Dieser Datenträger hat keine Volume-UUID. Er wird an {merkmale_text(merkmale)} "
                  "und vor D, E und F zusätzlich an einer Stichprobe von Dateien wiedererkannt.")
            gleich = pd.Series([ersatzmerkmale(z) == merkmale for _, z in andere_platten.iterrows()],
                               index=andere_platten.index, dtype=bool)
            andere = andere_platten[(andere_platten.platte_id != platte_id) & ohne_uuid & gleich]

        schon = (vorher.get("volume_uuid") in kennungen_jetzt if info["volume_uuid"]
                 else bool(vorher) and ersatzmerkmale(vorher) == merkmale)
        if len(andere) and not (gleiche_uuid_ok or schon):
            merkmal = "dieselbe Volume-UUID" if info["volume_uuid"] else "denselben Namen, dasselbe Dateisystem und dieselbe Größe"
            raise ValueError(
                f"Dieser Datenträger hat {merkmal} wie {andere.platte_id.iloc[0]}. "
                "Entweder ist es derselbe (dann diese Kennung nehmen) oder ein Klon bzw. ein zweites Exemplar "
                f"(dann {HAKEN_KLON}).")
        if vorher.get("volume_uuid") and vorher["volume_uuid"] not in kennungen_jetzt:
            raise ValueError(f"{platte_id} ist schon für einen anderen Datenträger vergeben "
                             f"({vorher['volume_name']}). Bitte andere platte_id wählen (Übersicht in B2).")
        if vorher and not vorher.get("volume_uuid") and ersatzmerkmale(vorher) != merkmale:
            raise ValueError(f"{platte_id} ist schon für einen anderen Datenträger ohne UUID vergeben "
                             f"({merkmale_text(ersatzmerkmale(vorher))}). Bitte andere platte_id wählen (Übersicht in B2).")

    # Umfang (Teile der Platte): nur wachsen, jeder Ordner muss da sein
    alt_umfang = json.loads(vorher["umfang"]) if vorher.get("umfang") else []
    neu_umfang = alt_umfang if umfang is None else umfang_pruefen(platte_id, umfang, wurzel, alt_umfang if vorher else None)

    etikett_text = etikett.strip() or vorher.get("etikett_text") or ""
    etikett_foto = vorher.get("etikett_foto")
    if foto:
        ziel = P.etiketten / f"{platte_id}_etikett{Path(foto).suffix.lower()}"
        shutil.copy2(foto, ziel)
        etikett_foto = str(ziel.relative_to(P.ordner))

    zeile = {
        "platte_id": platte_id,
        **info,
        "etikett_text": etikett_text,
        "etikett_foto": etikett_foto,
        "kopie_von": vorher.get("kopie_von"),
        "registriert_am": vorher.get("registriert_am") or jetzt(),
        "notiz": notiz or vorher.get("notiz") or "",
        "deaktiviert_am": vorher.get("deaktiviert_am"),   # herausgenommen bleibt herausgenommen
        "art": art if ordner or abbild or macgeraet else None,
        "quellordner": str(wurzel) if ordner or abbild else None,
        "umfang": json.dumps(neu_umfang, ensure_ascii=False) if neu_umfang else None,
    }
    with db() as con:
        con.execute(f"INSERT OR REPLACE INTO platte ({', '.join(zeile)}) VALUES ({', '.join('?' * len(zeile))})",
                    list(zeile.values()))
    protokolliere("B", platte_id, "platte", "aktualisiert" if vorher else "neu", json.dumps(info, default=str))
    if vorher and (vorher.get("etikett_text") or "") != etikett_text:
        protokolliere("B", platte_id, "etikett_text", vorher.get("etikett_text") or "", etikett_text)
    if (vorher.get("umfang") or "") != (zeile["umfang"] or ""):
        protokolliere("B", platte_id, "umfang", vorher.get("umfang") or "", zeile["umfang"] or "")
    if neu_umfang:
        print(f"{platte_id}: gelesen wird nur {umfang_text(neu_umfang)}.")
    return pd.Series(zeile, name=platte_id).to_frame()


def angaben_aendern(platte_id, etikett=None, notiz=None, kopie_von=None, foto=None):
    """Ändert Etikett, Notiz, Kopie-Vermerk oder Etikettfoto einer registrierten Platte, ohne dass sie angeschlossen
    sein muss. None = unverändert; jede Änderung kommt ins Protokoll. foto: Pfad zu einem neuen Foto des Etiketts."""
    with db() as con:
        alt = con.execute("SELECT etikett_text, notiz, kopie_von, etikett_foto FROM platte WHERE platte_id = ?",
                          (platte_id,)).fetchone()
        if alt is None:
            raise ValueError(f"{platte_id} ist nicht registriert.")
        kennungen = {k for (k,) in con.execute("SELECT platte_id FROM platte")}
    if kopie_von and (kopie_von not in kennungen or kopie_von == platte_id):
        raise ValueError(f"„Kopie von“ muss ein anderer registrierter Datenträger sein, nicht {kopie_von}.")
    neu = dict(zip(("etikett_text", "notiz", "kopie_von", "etikett_foto"), alt))
    for feld, wert in (("etikett_text", etikett), ("notiz", notiz), ("kopie_von", kopie_von)):
        if wert is not None:
            neu[feld] = wert.strip() or None
    if foto:
        ziel = P.etiketten / f"{platte_id}_etikett{Path(foto).suffix.lower()}"
        shutil.copy2(foto, ziel)
        neu["etikett_foto"] = str(ziel.relative_to(P.ordner))
    geaendert = {f: (a, neu[f]) for f, a in zip(neu, alt) if (a or None) != (neu[f] or None) or (f == "etikett_foto" and foto)}
    if geaendert:
        with db() as con:
            con.execute("UPDATE platte SET etikett_text = ?, notiz = ?, kopie_von = ?, etikett_foto = ? WHERE platte_id = ?",
                        (*neu.values(), platte_id))
        for feld, (a, n) in geaendert.items():
            protokolliere("B", platte_id, feld, a or "", n or "")
    print(f"{platte_id}: " + (", ".join(geaendert) + " geändert." if geaendert else "keine Änderung."))
    return {"geaendert": list(geaendert)}


def aus_projekt_nehmen(platte_id, herausnehmen=True):
    """Nimmt eine registrierte Platte aus dem Projekt (herausnehmen=True) oder wieder auf. Gelöscht wird nichts:
    Nur platte.deaktiviert_am wird gesetzt bzw. geleert; Duplikate (G) danach neu abgleichen. Kommt ins Protokoll."""
    with db() as con:
        z = con.execute("SELECT deaktiviert_am FROM platte WHERE platte_id = ?", (platte_id,)).fetchone()
        if z is None:
            raise ValueError(f"{platte_id} ist nicht registriert.")
        alt = z[0]
        if bool(alt) == herausnehmen:
            return {"geaendert": False, "deaktiviert_am": alt}
        neu = jetzt() if herausnehmen else None
        con.execute("UPDATE platte SET deaktiviert_am = ? WHERE platte_id = ?", (neu, platte_id))
    protokolliere("B", platte_id, "deaktiviert_am", alt or "", neu or "")
    print(f"{platte_id}: " + ("aus dem Projekt genommen." if herausnehmen else "wieder ins Projekt aufgenommen."))
    return {"geaendert": True, "deaktiviert_am": neu}

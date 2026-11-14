# Tests für werkzeuge/texte.py: angezeigte Texte sammeln und Neufassungen zurückschreiben (Entscheidung 13.11.2026)
from werkzeuge import texte as tx


def _texte(funde):
    return [f.text for f in funde]


# ---------------------------------------------------------------- JavaScript

def test_js_einfache_zeichenketten_mit_text():
    js = 'const a = "Projekt öffnen";\nconst b = "chevron-down";\nlet c = \'Noch nichts zugeordnet.\';\n'
    funde = tx.js_texte(js)
    assert _texte(funde) == ["Projekt öffnen", "Noch nichts zugeordnet."]
    assert [f.zeile for f in funde] == [1, 3]


def test_js_kommentare_und_regex_werden_uebersprungen():
    js = ('// Kommentar mit "Text darin"\n/* Block "auch hier" */\n'
          'const m = /k(assier)/gi;\nconst t = "Echter Text";\n')
    assert _texte(tx.js_texte(js)) == ["Echter Text"]


def test_js_vorlage_trennt_html_und_behaelt_einfache_platzhalter():
    js = 'x = `<li class="leise">… und ${zahl(n - 1)} weitere</li>`;\n'
    assert _texte(tx.js_texte(js)) == ["… und ${zahl(n - 1)} weitere"]


def test_js_tooltips_und_platzhalter_attribute():
    js = 'x = `<a class="leise" href="${esc(l)}" title="In Anton öffnen">${icon("x")}</a><input placeholder="Suchen …">`;\n'
    funde = tx.js_texte(js)
    assert _texte(funde) == ["In Anton öffnen", "Suchen …"]
    assert [f.art for f in funde] == ["title", "placeholder"]


def test_js_verschachtelte_vorlagen():
    js = ('x = `<ul>${a ? `<li>Erster Punkt</li>` : ""}<li>Zweiter ${b} Punkt</li></ul>`;\n'
          'y = "Danach";\n')
    assert _texte(tx.js_texte(js)) == ["Erster Punkt", "Zweiter ${b} Punkt", "Danach"]


def test_js_prosa_mit_semikolon_und_gleichheitszeichen():
    js = 'a = "Später verschieben; Balduin findet es."; b = "leer = keiner"; c = "a;b"; d = \'[data-x="y"]\';\n'
    assert _texte(tx.js_texte(js)) == ["Später verschieben; Balduin findet es.", "leer = keiner"]


def test_js_klassen_und_selektoren_sind_kein_text():
    js = 'q(".ex-zeile"); el.classList.add("gewaehlt"); f("/api/stand"); g("data-ex-auf");\n'
    assert tx.js_texte(js) == []


def test_js_mehrzeiliger_text_hat_die_zeile_seines_anfangs():
    js = 'x = `\n  <p>Erste Zeile\n  geht weiter.</p>`;\n'
    funde = tx.js_texte(js)
    assert funde[0].zeile == 2 and funde[0].text.startswith("Erste Zeile")


# ---------------------------------------------------------------- HTML

def test_html_text_und_attribute_ohne_kommentare():
    html = ('<!-- Kommentar -->\n<button title="Über Balduin">Start</button>\n'
            '<script>const a = "Aus dem Skript";</script>\n')
    funde = tx.html_texte(html)
    assert _texte(funde) == ["Über Balduin", "Start", "Aus dem Skript"]


# ---------------------------------------------------------------- Python

def test_py_meldungen_ohne_docstrings_sql_und_bezeichner():
    py = ('"""Modul-Doku mit Text."""\n'
          'def f():\n    """Funktionsdoku."""\n'
          '    con.execute("SELECT pfad FROM datei WHERE platte_id = ?")\n'
          '    x = {"status": "fertig"}\n'
          '    return {"fehler": "Die Platte ist nicht angeschlossen."}\n')
    funde = tx.py_texte(py)
    assert _texte(funde) == ["Die Platte ist nicht angeschlossen."]
    assert funde[0].zeile == 6


def test_py_mehrzeiliges_sql_auch_in_folgezeilen():
    py = 'q = ("SELECT a, b "\n     "AS geschrieben FROM paket p ORDER BY paket_id")\n'
    assert tx.py_texte(py) == []


def test_js_attributteil_ausserhalb_eines_tags_ist_kein_text():
    js = 'x = `class="icon traeger${k ? " " + k : ""}"`;\n'
    assert tx.js_texte(js) == []


def test_py_fstring_behaelt_platzhalter_im_quelltext():
    py = 'm = f"{zahl(n)} Dateien gelesen, {fehler} Fehler"\n'
    assert _texte(tx.py_texte(py)) == ["{zahl(n)} Dateien gelesen, {fehler} Fehler"]


def test_werte_im_code_werden_erkannt():
    code = ('if s.status == "gleicher Name, andere Datei": pass\n'
            'FARBEN = {"nicht in Anton": "#ccc"}\n'
            "con.execute(\"SELECT * FROM lauf WHERE status = 'läuft'\")\n"
            'x = an[an.st.isin(["in Anton", "leer"])]\n'
            'meldung = "Bitte die Platte anschließen."\n')
    assert tx.als_wert("gleicher Name, andere Datei", code)
    assert tx.als_wert("nicht in Anton", code)
    assert tx.als_wert("läuft", code)
    assert tx.als_wert("in Anton", code)
    assert not tx.als_wert("Bitte die Platte anschließen.", code)
    # Dreiwertiger Ausdruck ist kein Schlüssel
    assert not tx.als_wert("Abbild da", 'x = ok ? "Abbild da" : "fehlt";\n')


# ---------------------------------------------------------------- Zurückschreiben

def test_einspielen_ersetzt_genau_die_stelle():
    alt = 'a = "Speichern";\nb = "Speichern";\n'
    neu, abgewiesen = tx.einspielen(alt, [(2, "Speichern", "Sichern")])
    assert neu == 'a = "Speichern";\nb = "Sichern";\n' and abgewiesen == []


def test_einspielen_findet_verschobene_zeilen():
    alt = '// neu eingefügt\n// noch eine\na = "Alter Text";\n'
    neu, abgewiesen = tx.einspielen(alt, [(1, "Alter Text", "Neuer Text")])
    assert 'a = "Neuer Text";' in neu and abgewiesen == []


def test_einspielen_weist_fehlende_platzhalter_ab():
    alt = 'x = `${n} Dateien`;\n'
    neu, abgewiesen = tx.einspielen(alt, [(1, "${n} Dateien", "Einige Dateien")])
    assert neu == alt and len(abgewiesen) == 1 and "Platzhalter" in abgewiesen[0][1]


def test_einspielen_weist_unbekannten_text_ab():
    alt = 'x = "Da";\n'
    neu, abgewiesen = tx.einspielen(alt, [(1, "Nicht da", "Neu")])
    assert neu == alt and "nicht gefunden" in abgewiesen[0][1]


def test_einspielen_mehrere_in_einer_zeile():
    alt = 'x = `<b title="Erster Hinweis">Erster Text</b>`;\n'
    neu, _ = tx.einspielen(alt, [(1, "Erster Text", "Zweiter Text"), (1, "Erster Hinweis", "Zweiter Hinweis")])
    assert neu == 'x = `<b title="Zweiter Hinweis">Zweiter Text</b>`;\n'

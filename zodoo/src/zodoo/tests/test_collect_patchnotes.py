"""Der Sammler, der aus Patchnote-Fragmenten den Changelog macht.

Der Anlass: die Release-Automatik las die Beschreibung per
`grep '^description:'`. Bei der Blockschreibweise `description: |` steht dort
nur ein Pipe-Zeichen - der Text darunter ging verloren. Am 06.09.2026 waren
36 der 308 Changelog-Eintraege deshalb leer.
"""
import importlib.machinery
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SKRIPT = Path(__file__).resolve().parents[4] / "scripts" / "collect_patchnotes.py"


def sammle(tmp_path):
    erg = subprocess.run(
        [sys.executable, str(SKRIPT), str(tmp_path)],
        capture_output=True, text=True,
    )
    assert erg.returncode == 0, erg.stderr
    return json.loads(erg.stdout)


def schreibe(tmp_path, name, inhalt):
    (tmp_path / name).write_text(inhalt)


def test_mehrzeilige_beschreibung_landet_vollstaendig_im_changelog(tmp_path):
    """Der Fall, der die 36 leeren Eintraege verursacht hat."""
    schreibe(tmp_path, "a.yml", """
type: fix
breaking: false
description: |
  Erste Zeile der Erklaerung.
  Zweite Zeile, die zum selben Absatz gehoert.

  Ein zweiter Absatz.
""".lstrip())
    d = sammle(tmp_path)
    assert len(d["entries"]) == 1
    eintrag = d["entries"][0]
    assert eintrag.startswith("- **Fix**: Erste Zeile der Erklaerung.")
    assert "Zweite Zeile" in eintrag
    assert "Ein zweiter Absatz." in eintrag
    assert "|" not in eintrag


def test_aufzaehlung_bleibt_eine_aufzaehlung(tmp_path):
    """Beim ersten Anlauf wurden die fuenf Spiegelstriche einer Patchnote zu
    einem einzigen Absatz zusammengezogen - im Changelog hintereinander weg."""
    schreibe(tmp_path, "a.yml", """
type: fix
description: |
  Dabei aufgefallen:

  - erster Punkt
  - zweiter Punkt, der ueber zwei Zeilen geht
    und hier weitergeht
  - dritter Punkt
""".lstrip())
    eintrag = sammle(tmp_path)["entries"][0]
    zeilen = [z.strip() for z in eintrag.split("\n") if z.strip()]
    # zeilen[0] ist der Spiegelstrich des Changelogs selbst ("- **Fix**: ...")
    spiegelstriche = [z for z in zeilen[1:] if z.startswith("- ")]
    assert len(spiegelstriche) == 3, zeilen
    # die Fortsetzung haengt an ihrem eigenen Punkt, nicht am naechsten
    assert "zweiter Punkt, der ueber zwei Zeilen geht und hier weitergeht" in eintrag
    assert "dritter Punkt" in spiegelstriche[2]


def test_nummerierte_aufzaehlung_ebenso(tmp_path):
    schreibe(tmp_path, "a.yml", """
type: fix
description: |
  1. eins
  2. zwei
""".lstrip())
    eintrag = sammle(tmp_path)["entries"][0]
    assert eintrag.count("\n") >= 1, eintrag


def test_fliesstext_wird_weiterhin_zusammengezogen(tmp_path):
    """Die Gegenrichtung: normale Zeilen duerfen NICHT zerfallen."""
    schreibe(tmp_path, "a.yml", """
type: fix
description: |
  Erste Zeile.
  Zweite Zeile.
""".lstrip())
    assert sammle(tmp_path)["entries"][0] == "- **Fix**: Erste Zeile. Zweite Zeile."


def test_einzeilige_beschreibung_funktioniert_weiter(tmp_path):
    schreibe(tmp_path, "a.yml", 'type: feature\ndescription: "Kurz und knapp"\nbreaking: false\n')
    d = sammle(tmp_path)
    assert d["entries"] == ["- **Feature**: Kurz und knapp"]
    assert d["bump"] == "minor"


def test_breaking_hebt_die_hauptversion(tmp_path):
    schreibe(tmp_path, "a.yml", """
type: breaking
breaking: true
description: "Etwas faellt weg"
breaking_description: |
  Wer X benutzt, muss auf Y wechseln.
""".lstrip())
    d = sammle(tmp_path)
    assert d["bump"] == "major"
    assert "**BREAKING**: Etwas faellt weg" in d["entries"][0]
    assert "Wer X benutzt" in d["entries"][0]


def test_vorlage_wird_uebersprungen(tmp_path):
    schreibe(tmp_path, "example.yml.template", "type: fix\ndescription: nicht mitzaehlen\n")
    assert sammle(tmp_path)["entries"] == []


def test_fragmente_in_unterordnern_zaehlen_mit(tmp_path):
    (tmp_path / "fix").mkdir()
    schreibe(tmp_path, "fix/a.yml", 'type: fix\ndescription: "aus dem Unterordner"\n')
    assert sammle(tmp_path)["entries"] == ["- **Fix**: aus dem Unterordner"]


def test_leere_beschreibung_bricht_ab(tmp_path):
    """Lieber ein roter Release-Lauf als ein leerer Changelog-Eintrag."""
    schreibe(tmp_path, "a.yml", "type: fix\ndescription:\n")
    erg = subprocess.run([sys.executable, str(SKRIPT), str(tmp_path)],
                         capture_output=True, text=True)
    assert erg.returncode != 0
    assert "description" in erg.stderr

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

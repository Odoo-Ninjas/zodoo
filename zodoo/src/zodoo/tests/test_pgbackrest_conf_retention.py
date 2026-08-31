"""Tests der erzeugten pgbackrest.conf - Schwerpunkt Aufbewahrung.

Warum ausgerechnet die: bis 2026-08-31 lief NIRGENDS ein `expire`. Die Instanz
liess die Aufbewahrung weg, weil sie beim Repo-Host "drueben" gehoere, und der
Repo-Host kann sie nicht durchsetzen - `expire` muss `backup.info` lesen, und
die ist verschluesselt. Eine Aufraeumung, die eingerichtet war und nie wirkte;
genau der Fehler, vor dem der Kommentar in `_retention_lines` warnt.
"""

import importlib.util
from pathlib import Path

import pytest

WURZEL = Path(__file__).resolve().parents[4]
QUELLE = WURZEL / "pgbackrest" / "__after_compose.py"


def _modul():
    if not QUELLE.exists():          # ausserhalb des Repos (installiertes Paket)
        pytest.skip(f"{QUELLE} nicht vorhanden")
    spec = importlib.util.spec_from_file_location("pgbr_after_compose", QUELLE)
    modul = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modul)
    return modul


BASIS = {
    "PGBR_REPO_HOST": "db.backup.zebroo.de",
    "PGBR_REPO_HOST_PORT": "443",
    "PGBR_CIPHER_PASS": "geheim",
    "PGBR_STANZA": "kunde-a",
}


def test_the_pusher_gets_retention():
    """Wer sichert, raeumt auch auf - und nur er kann es hier."""
    m = _modul()
    text = m._repo_section(dict(BASIS, PGBR_BACKUP_FROM="here"))
    assert "repo1-retention-full-type=time" in text
    assert "repo1-retention-full=14" in text


def test_retention_defaults_are_used_when_empty():
    """Leer heisst 'Vorgabe', niemals 'alles behalten'."""
    m = _modul()
    text = m._repo_section(dict(BASIS, PGBR_BACKUP_FROM="here",
                                PGBR_RETENTION_FULL="",
                                PGBR_RETENTION_FULL_TYPE=""))
    assert "repo1-retention-full=14" in text
    assert "repo1-retention-full-type=time" in text


def test_the_puller_does_not_get_retention():
    """Sichert der Repo-Host selbst, waere die Regel hier wirkungslos."""
    m = _modul()
    text = m._repo_section(dict(BASIS, PGBR_BACKUP_FROM="repo-host"))
    assert "repo1-retention" not in text


def test_a_local_repository_still_gets_retention():
    m = _modul()
    text = m._repo_section({"PGBR_CIPHER_PASS": "geheim"})
    assert "repo1-path=/var/lib/pgbackrest" in text
    assert "repo1-retention-full=14" in text


def test_the_pusher_never_gets_a_repo_path():
    """Der Pfad liegt auf der anderen Maschine und geht uns nichts an."""
    m = _modul()
    text = m._repo_section(dict(BASIS, PGBR_BACKUP_FROM="here"))
    assert "repo1-path" not in text
    assert "repo1-host=db.backup.zebroo.de" in text

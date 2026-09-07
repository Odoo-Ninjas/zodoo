"""Tests der Instanz-Kennzahlen zur WAL-Archivierung.

Diese Kennzahlen sind die einzige Rueckmeldung, die eine laufende Instanz
ueber ihre eigene Sicherung gibt. Entsprechend geht es hier weniger um
Formatierung als um die Faelle, in denen etwas NICHT gemeldet werden darf:
eine 0, die aussieht wie eine Messung, ist schlimmer als eine fehlende Zeile.
"""

import json
import subprocess
from unittest import mock

from zodoo import lib_backup_metrics as bm


class FakeConfig:
    project_name = "kunde"
    pgbr_stanza = "kunde"
    run_pgbackrest = "1"
    run_offsite = "0"
    dirs = {}






def test_archiver_row_is_parsed(monkeypatch):
    import zodoo.tools as tools
    monkeypatch.setattr(tools, "__dc_out",
                        lambda *a, **kw: "1234|0|1788000000|0\n",
                        raising=False)
    werte = bm._archiv_werte(FakeConfig())
    assert werte == {
        "archiviert": 1234,
        "gescheitert": 0,
        "zuletzt_archiviert": 1788000000,
        "zuletzt_gescheitert": 0,
    }


def test_an_unreadable_archiver_is_none_not_zero(monkeypatch):
    """Der entscheidende Fall: 0 bei 'gescheitert' saehe aus wie 'alles gut'."""
    import zodoo.tools as tools

    def kaputt(*a, **kw):
        raise subprocess.CalledProcessError(1, "psql")

    monkeypatch.setattr(tools, "__dc_out", kaputt, raising=False)
    assert bm._archiv_werte(FakeConfig()) is None


def test_a_short_row_is_none(monkeypatch):
    import zodoo.tools as tools
    monkeypatch.setattr(tools, "__dc_out", lambda *a, **kw: "1|2\n",
                        raising=False)
    assert bm._archiv_werte(FakeConfig()) is None


def test_spool_and_dropped_are_read(monkeypatch):
    import zodoo.tools as tools
    monkeypatch.setattr(tools, "__dc_out", lambda *a, **kw: "7\n3\n",
                        raising=False)
    warteschlange, verworfen = bm._spool_and_dropped(FakeConfig())
    assert warteschlange == 7
    assert verworfen == 3


def test_unreadable_spool_is_none(monkeypatch):
    import zodoo.tools as tools

    def kaputt(*a, **kw):
        raise OSError("kein Container")

    monkeypatch.setattr(tools, "__dc_out", kaputt, raising=False)
    assert bm._spool_and_dropped(FakeConfig()) == (None, None)


def test_the_check_state_is_read_from_the_run_dir(tmp_path):
    cfg = FakeConfig()
    cfg.dirs = {"run": tmp_path}
    (tmp_path / "pgbackrest-check.json").write_text(
        json.dumps({"ok": False, "at": 1788000000, "error": "kaputt"})
    )
    zustand = bm._check_zustand(cfg)
    assert zustand["ok"] is False
    assert zustand["at"] == 1788000000


def test_a_missing_check_file_is_none(tmp_path):
    cfg = FakeConfig()
    cfg.dirs = {"run": tmp_path}
    assert bm._check_zustand(cfg) is None

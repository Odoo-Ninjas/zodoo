"""Regression tests for postgres/__after_settings.py:_compute_max_connections.

The hook is a standalone settings module (not part of the zodoo package), so we
load it by path relative to this test file — that way it always exercises the
same repo's copy, whether run from a checkout or the installed images dir.
"""

import importlib.util
from pathlib import Path

import pytest

_HOOK_PATH = (
    Path(__file__).resolve().parents[4] / "postgres" / "__after_settings.py"
)


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    # The hook probes ~/.odoo/postgres.conf for a user max_connections
    # override; point HOME at an empty tmp dir so tests don't pick up the
    # developer's real config and stay deterministic.
    monkeypatch.setenv("HOME", str(tmp_path))
    yield


def _load_hook():
    if not _HOOK_PATH.is_file():
        pytest.skip(f"postgres hook not found at {_HOOK_PATH}")
    spec = importlib.util.spec_from_file_location(
        "_pg_after_settings", _HOOK_PATH
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _compute(settings):
    mod = _load_hook()
    mod._compute_max_connections(settings)
    return settings


def test_default_install_hits_min_floor():
    # 6 web + 2 cron + (root:1 → 1*2) queuejob = 10 procs;
    # ceil(10*3)+50 = 80 → floored to MIN_FLOOR=100.
    s = {}
    _compute(s)
    assert s["DB_MAXCONN"] == "100"
    assert "max_connections=100" in s["POSTGRES_CONFIG"]


def test_extra_db_conn_is_additive():
    s = {"EXTRA_DB_CONN": "25"}
    _compute(s)
    assert s["DB_MAXCONN"] == "125"


def test_user_override_keeps_db_maxconn_in_sync():
    # User pinned max_connections — DB_MAXCONN must track that value, not the
    # computed one, and POSTGRES_CONFIG must not get a second max_connections.
    s = {"POSTGRES_CONFIG": "max_connections=80"}
    _compute(s)
    assert s["DB_MAXCONN"] == "80"
    assert s["POSTGRES_CONFIG"].count("max_connections") == 1


def test_user_override_with_spaces():
    s = {"POSTGRES_CONFIG": "shared_buffers=256MB;max_connections = 64"}
    _compute(s)
    assert s["DB_MAXCONN"] == "64"


def test_malformed_input_falls_back_to_floor_never_unset():
    # A bad worker count must NOT leave DB_MAXCONN unset (that re-introduces
    # the unsubstituted __DB_MAXCONN__ crash) — it falls back to MIN_FLOOR.
    s = {"ODOO_WORKERS_WEB": "not-a-number"}
    _compute(s)
    assert s["DB_MAXCONN"] == "100"


def test_malformed_channels_falls_back_to_floor():
    s = {"ODOO_QUEUEJOBS_CHANNELS": "root"}  # missing ":n"
    _compute(s)
    assert s["DB_MAXCONN"] == "100"


def test_non_root_channels_drive_worker_count():
    # non-root channels sum = 4 → 4*2 = 8 queuejob workers;
    # total = 6 + 2 + 8 = 16; ceil(16*3)+50 = 98 → floored to 100.
    s = {"ODOO_QUEUEJOBS_CHANNELS": "root:1,mail:4"}
    _compute(s)
    assert s["DB_MAXCONN"] == "100"
    # Bump web workers so the formula clears the floor and we exercise the math.
    s2 = {"ODOO_QUEUEJOBS_CHANNELS": "root:1,mail:4", "ODOO_WORKERS_WEB": "20"}
    _compute(s2)
    # total = 20 + 2 + 8 = 30; ceil(30*3)+50 = 140.
    assert s2["DB_MAXCONN"] == "140"

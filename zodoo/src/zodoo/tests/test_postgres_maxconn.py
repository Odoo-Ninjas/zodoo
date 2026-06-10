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


# ---------------------------------------------------------------------------
# Basic computation
# ---------------------------------------------------------------------------


def test_default_install_hits_min_floor():
    # 6 web + 2 cron + (root:1 → 1*2) queuejob = 10 procs;
    # ceil(10*3)+50 = 80 → floored to MIN_FLOOR=100.
    s = {}
    _compute(s)
    assert s["DB_MAXCONN"] == "100"
    assert "max_connections=100" in s["POSTGRES_CONFIG"]
    # zodoo also reserves ~10% for superuser connections (min 3, max 20)
    assert "superuser_reserved_connections=10" in s["POSTGRES_CONFIG"]


def test_extra_db_conn_is_additive():
    s = {"EXTRA_DB_CONN": "25"}
    _compute(s)
    assert s["DB_MAXCONN"] == "125"
    assert "max_connections=125" in s["POSTGRES_CONFIG"]


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
    assert "max_connections=140" in s2["POSTGRES_CONFIG"]
    # reserved = max(3, min(20, ceil(140*0.1))) = 14
    assert "superuser_reserved_connections=14" in s2["POSTGRES_CONFIG"]


# ---------------------------------------------------------------------------
# User override via POSTGRES_CONFIG
# ---------------------------------------------------------------------------


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


def test_extra_db_conn_ignored_with_user_override():
    # EXTRA_DB_CONN only applies to the auto-computed value, not to a
    # user-pinned max_connections — otherwise DB_MAXCONN would diverge from
    # the postgres server's actual connection limit.
    s = {"POSTGRES_CONFIG": "max_connections=80", "EXTRA_DB_CONN": "25"}
    _compute(s)
    assert s["DB_MAXCONN"] == "80"  # 80, not 105


# ---------------------------------------------------------------------------
# Glue / idempotency
# ---------------------------------------------------------------------------


def test_existing_postgres_config_gets_semicolon_glue():
    """When POSTGRES_CONFIG already has settings, zodoo appends with ';'."""
    s = {"POSTGRES_CONFIG": "shared_buffers=256MB"}
    _compute(s)
    assert "shared_buffers=256MB;max_connections=" in s["POSTGRES_CONFIG"]


def test_trailing_semicolon_no_double_separator():
    """No double semicolon when POSTGRES_CONFIG already ends with ';'."""
    s = {"POSTGRES_CONFIG": "shared_buffers=256MB;"}
    _compute(s)
    assert ";;" not in s["POSTGRES_CONFIG"]
    assert "max_connections=" in s["POSTGRES_CONFIG"]


def test_idempotent_when_zodoo_values_persisted():
    """If POSTGRES_CONFIG was persisted with zodoo-auto-appended values from a
    prior run (e.g. via `odoo setting`), re-running must not accumulate
    duplicate entries."""
    s = {
        "POSTGRES_CONFIG": (
            "shared_buffers=256MB;"
            "max_connections=100;"
            "superuser_reserved_connections=10"
        )
    }
    # The persisted max_connections is treated as a user pin and kept.
    _compute(s)
    assert s["POSTGRES_CONFIG"].count("max_connections") == 1
    assert s["POSTGRES_CONFIG"].count("superuser_reserved_connections") == 1


# ---------------------------------------------------------------------------
# Partial-number / word-boundary edge cases
# ---------------------------------------------------------------------------


def test_partial_number_extracts_leading_digits():
    """The regex extracts the leading digit sequence from values like '123abc'.
    PostgreSQL rejects this at startup; zodoo uses the parsed integer so
    DB_MAXCONN is at least consistent with what postgres would attempt."""
    s = {"POSTGRES_CONFIG": "max_connections=123abc"}
    _compute(s)
    assert s["DB_MAXCONN"] == "123"


# ---------------------------------------------------------------------------
# Unparseable / error paths
# ---------------------------------------------------------------------------


def test_malformed_input_falls_back_to_floor_never_unset():
    # A bad worker count must NOT leave DB_MAXCONN unset (that re-introduces
    # the unsubstituted __DB_MAXCONN__ crash) — it falls back to MIN_FLOOR.
    s = {"ODOO_WORKERS_WEB": "not-a-number"}
    _compute(s)
    assert s["DB_MAXCONN"] == "100"


def test_malformed_channels_raises_and_falls_back_to_floor():
    # _parse_channels("root") raises ValueError (not enough values to unpack
    # "root" into k, v), which the outer except (ValueError, TypeError)
    # catches → falls back to MIN_FLOOR=100.
    s = {"ODOO_QUEUEJOBS_CHANNELS": "root"}  # missing ":n"
    _compute(s)
    assert s["DB_MAXCONN"] == "100"


def test_unparseable_user_override_aborts():
    # When the user sets max_connections but the value cannot be parsed as an
    # integer, zodoo must abort hard rather than silently falling back to the
    # computed value — the user's intent was to cap connections explicitly.
    with pytest.raises(SystemExit):
        _compute({"POSTGRES_CONFIG": "max_connections=not-a-number"})


def test_float_extra_db_conn_aborts():
    with pytest.raises(SystemExit):
        _compute({"EXTRA_DB_CONN": "1.5"})


def test_negative_extra_db_conn_aborts():
    with pytest.raises(SystemExit):
        _compute({"EXTRA_DB_CONN": "-1"})


# ---------------------------------------------------------------------------
# postgres.conf file override (project-specific beats global)
# ---------------------------------------------------------------------------


def test_project_postgres_conf_overrides_global(tmp_path):
    """Project-specific postgres.conf wins over ~/.odoo/postgres.conf."""
    odoo_dir = tmp_path / ".odoo"
    odoo_dir.mkdir()
    (odoo_dir / "postgres.conf").write_text("max_connections = 200\n")
    project_dir = odoo_dir / "testproject"
    project_dir.mkdir()
    (project_dir / "postgres.conf").write_text("max_connections = 150\n")
    s = {"PROJECT_NAME": "testproject"}
    _compute(s)
    assert s["DB_MAXCONN"] == "150"
    # User pinned it via postgres.conf → zodoo must not append max_connections
    # to POSTGRES_CONFIG (the key may not even be set in this code path).
    assert "max_connections" not in s.get("POSTGRES_CONFIG", "")


def test_global_postgres_conf_used_as_fallback(tmp_path):
    """~/.odoo/postgres.conf is used when no project-specific file exists."""
    odoo_dir = tmp_path / ".odoo"
    odoo_dir.mkdir()
    (odoo_dir / "postgres.conf").write_text("max_connections = 200\n")
    s = {"PROJECT_NAME": "no-such-project"}
    _compute(s)
    assert s["DB_MAXCONN"] == "200"


def test_postgres_conf_non_numeric_value_aborts(tmp_path):
    """A non-numeric max_connections in postgres.conf is treated as user
    intent; since zodoo cannot parse the value it aborts rather than
    silently ignoring the override."""
    odoo_dir = tmp_path / ".odoo"
    odoo_dir.mkdir()
    (odoo_dir / "postgres.conf").write_text("max_connections = notanumber\n")
    with pytest.raises(SystemExit):
        _compute({"PROJECT_NAME": "x"})


def test_postgres_conf_comment_lines_ignored(tmp_path):
    """Lines starting with '#' are comments and must not be interpreted as
    max_connections overrides."""
    odoo_dir = tmp_path / ".odoo"
    odoo_dir.mkdir()
    (odoo_dir / "postgres.conf").write_text(
        "# max_connections = 999\nshared_buffers = 256MB\n"
    )
    s = {}
    _compute(s)
    # No override detected → auto-computed → MIN_FLOOR=100
    assert s["DB_MAXCONN"] == "100"

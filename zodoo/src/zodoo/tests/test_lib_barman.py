"""Tests for the optional Barman service integration.

Fast unit tests cover the two compose-time hooks (no Docker needed):
- ``barman/__after_settings.py`` forces RUN_BARMAN off on DEVMODE machines
- ``barman/__after_compose.py`` injects WAL-streaming settings into postgres
  only when Barman is enabled.
Plus a smoke test that the ``odoo barman`` CLI group is wired up.

A slow end-to-end test (`-m slow`) proves point-in-time-recovery actually
undoes a change against a live stack.
"""

from __future__ import annotations

import importlib.util
import time
from pathlib import Path

import arrow
import pytest

from .conftest import requires_full_stack

# repo root: .../images/zodoo/src/zodoo/tests/test_lib_barman.py -> parents[4]
_BARMAN_DIR = Path(__file__).resolve().parents[4] / "barman"


def _load(name):
    spec = importlib.util.spec_from_file_location(
        f"barman_{name}", str(_BARMAN_DIR / f"__{name}.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def after_settings():
    return _load("after_settings").after_settings


@pytest.fixture(scope="module")
def after_compose():
    return _load("after_compose").after_compose


def test_devmode_forces_barman_off(after_settings):
    settings = {
        "DEVMODE": "1",
        "RUN_BARMAN": "1",
        "RUN_POSTGRES": "1",
        "BARMAN_FORCE_IN_DEVMODE": "0",
    }
    after_settings(settings, None)
    assert settings["RUN_BARMAN"] == "0"


def test_devmode_force_flag_keeps_barman_on(after_settings):
    settings = {
        "DEVMODE": "1",
        "RUN_BARMAN": "1",
        "RUN_POSTGRES": "1",
        "BARMAN_FORCE_IN_DEVMODE": "1",
    }
    after_settings(settings, None)
    assert settings["RUN_BARMAN"] == "1"


def test_no_devmode_leaves_barman_untouched(after_settings):
    settings = {"DEVMODE": "0", "RUN_BARMAN": "1", "RUN_POSTGRES": "1"}
    after_settings(settings, None)
    assert settings["RUN_BARMAN"] == "1"


def test_external_postgres_disables_barman(after_settings):
    settings = {"DEVMODE": "0", "RUN_BARMAN": "1", "RUN_POSTGRES": "0"}
    after_settings(settings, None)
    assert settings["RUN_BARMAN"] == "0"


def test_wal_settings_injected_when_enabled(after_compose):
    yml = {"services": {"postgres": {"environment": {}}}}
    after_compose(
        None,
        {"RUN_BARMAN": "1", "POSTGRES_CONFIG": "shared_buffers=2GB;"},
        yml,
        {},
    )
    pgconf = yml["services"]["postgres"]["environment"]["POSTGRES_CONFIG"]
    # existing config preserved, WAL settings appended
    assert "shared_buffers=2GB" in pgconf
    assert "wal_level=replica" in pgconf
    assert "max_replication_slots=10" in pgconf


def test_wal_settings_absent_when_disabled(after_compose):
    yml = {"services": {"postgres": {"environment": {}}}}
    after_compose(None, {"RUN_BARMAN": "0"}, yml, {})
    assert "POSTGRES_CONFIG" not in yml["services"]["postgres"]["environment"]


def test_slot_wal_keep_size_capped(after_compose):
    yml = {"services": {"postgres": {"environment": {}}}}
    after_compose(
        None,
        {"RUN_BARMAN": "1", "BARMAN_MAX_SLOT_WAL_KEEP_SIZE": "5GB"},
        yml,
        {},
    )
    pgconf = yml["services"]["postgres"]["environment"]["POSTGRES_CONFIG"]
    assert "max_slot_wal_keep_size=5GB" in pgconf


def test_slot_wal_keep_size_unlimited_when_zero(after_compose):
    yml = {"services": {"postgres": {"environment": {}}}}
    after_compose(
        None,
        {"RUN_BARMAN": "1", "BARMAN_MAX_SLOT_WAL_KEEP_SIZE": "0"},
        yml,
        {},
    )
    pgconf = yml["services"]["postgres"]["environment"]["POSTGRES_CONFIG"]
    assert "max_slot_wal_keep_size" not in pgconf


def test_slot_wal_keep_size_skipped_on_old_pg(after_compose):
    # max_slot_wal_keep_size only exists on PG >= 13
    yml = {"services": {"postgres": {"environment": {}}}}
    after_compose(
        None,
        {
            "RUN_BARMAN": "1",
            "BARMAN_MAX_SLOT_WAL_KEEP_SIZE": "5GB",
            "POSTGRES_VERSION": "12",
        },
        yml,
        {},
    )
    pgconf = yml["services"]["postgres"]["environment"]["POSTGRES_CONFIG"]
    assert "max_slot_wal_keep_size" not in pgconf
    assert "wal_level=replica" in pgconf


def test_list_environment_is_normalised(after_compose):
    yml = {"services": {"postgres": {"environment": ["FOO=bar"]}}}
    after_compose(None, {"RUN_BARMAN": "1"}, yml, {})
    env = yml["services"]["postgres"]["environment"]
    assert isinstance(env, dict)
    assert env["FOO"] == "bar"
    assert "wal_level=replica" in env["POSTGRES_CONFIG"]


def test_barman_cli_group_registered():
    from zodoo.cli import cli

    grp = cli.commands.get("barman")
    assert grp is not None
    assert {
        "backup",
        "list",
        "status",
        "check",
        "recover",
        "switch-wal",
    } <= set(grp.commands.keys())


def test_status_resolves_to_setup_status_not_barman():
    """`odoo status` must show the project info (setup status), not barman's
    server status. The original bug: AliasedGroup's subgroup search resolved
    the tie barman/status vs setup/status by registration order (barman
    imports first) — fixed by registering setup.status directly on the cli
    group so the exact top-level match wins before the subgroup search."""
    import click
    from zodoo.cli import cli
    from zodoo import lib_setup

    ctx = click.Context(cli)
    assert cli.get_command(ctx, "status") is lib_setup.status


def test_barman_status_toplevel_shortcut_registered():
    from zodoo.cli import cli
    from zodoo import lib_barman

    cmd = cli.commands.get("barman-status")
    assert cmd is not None
    assert cmd.name == "barman-status"
    assert cmd is lib_barman.barman_status_toplevel


def test_barman_prefix_still_resolves_to_barman_group():
    """`odoo bar` must keep resolving to the barman group even though the
    top-level `barman-status` shares the prefix — AliasedGroup picks the
    shortest matched name when it is a prefix of all other matches."""
    import click
    from zodoo.cli import cli

    ctx = click.Context(cli)
    for prefix in ("bar", "barm", "barma", "barman"):
        assert cli.get_command(ctx, prefix) is cli.commands["barman"], prefix
    assert cli.get_command(ctx, "barman-s") is cli.commands["barman-status"]


def test_guard_update_enabled():
    from zodoo import lib_barman as b

    class C:
        run_barman = "1"
        barman_guard_update = "1"

    class D:
        run_barman = "1"
        barman_guard_update = "0"

    class E:
        run_barman = "0"
        barman_guard_update = "1"

    assert b.guard_update_enabled(C()) is True
    assert b.guard_update_enabled(D()) is False
    assert b.guard_update_enabled(E()) is False


def test_parse_age_valid_is_in_past():
    from zodoo import lib_barman as b

    parsed = arrow.get(b._parse_age("2h"), "YYYY-MM-DD HH:mm:ssZZ")
    assert parsed < arrow.now()


def test_parse_age_invalid_aborts():
    from zodoo import lib_barman as b

    with pytest.raises(SystemExit):
        b._parse_age("soon")


def test_parse_target_time_valid():
    from zodoo import lib_barman as b

    assert b._parse_target_time("2026-05-31 14:25:00").startswith(
        "2026-05-31 14:25:00"
    )


def test_parse_target_time_future_aborts():
    from zodoo import lib_barman as b

    future = arrow.now().shift(days=1).format("YYYY-MM-DD HH:mm:ss")
    with pytest.raises(SystemExit):
        b._parse_target_time(future)


def test_parse_target_time_idempotent():
    # CLI passes a plain timestamp (no tz); the normalised, tz-aware result must
    # re-parse to itself so the backup auto-selection (which re-normalises) works.
    from zodoo import lib_barman as b

    once = b._parse_target_time(
        "2026-05-31 14:25:00"
    )  # plain, no tz (CLI form)
    assert (
        b._parse_target_time(once) == once
    )  # tz-aware result re-parses to self
    # _parse_age output (tz-aware) must also re-parse without error
    assert b._parse_target_time(b._parse_age("2h"))


def test_pick_backup_for_time(monkeypatch):
    from zodoo import lib_barman as b

    monkeypatch.setattr(
        b,
        "_list_backups",
        lambda config: [
            ("odoo 20260601T020000 - ...", "20260601T020000"),
            ("odoo 20260603T020000 - ...", "20260603T020000"),
        ],
    )
    target = arrow.get("2026-06-02 12:00:00", tzinfo="local").format(
        "YYYY-MM-DD HH:mm:ssZZ"
    )
    # newest backup at or before the target
    assert b._pick_backup_for_time(None, target) == "20260601T020000"


def test_pick_backup_for_time_none_when_all_after(monkeypatch):
    from zodoo import lib_barman as b

    monkeypatch.setattr(
        b,
        "_list_backups",
        lambda config: [("odoo 20260603T020000 - ...", "20260603T020000")],
    )
    target = arrow.get("2026-05-01 00:00:00", tzinfo="local").format(
        "YYYY-MM-DD HH:mm:ssZZ"
    )
    assert b._pick_backup_for_time(None, target) is None


# --------------------------------------------------------------------------- #
# Slow end-to-end: point-in-time-recovery actually undoes a change            #
# --------------------------------------------------------------------------- #


def _sql(project, sql, check=True):
    """Run a single SQL statement via `odoo psql --sql` and return stdout."""
    res = project.run("psql", "--sql", sql, check=check, timeout=120)
    return res.stdout or ""


def _retry(fn, *, timeout, interval=3.0, what="condition"):
    """Poll fn() until it returns truthy or timeout (seconds) elapses."""
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = fn()
            if last:
                return last
        except Exception as ex:  # noqa: BLE001 - surfaced on timeout
            last = ex
        time.sleep(interval)
    raise AssertionError(f"Timed out waiting for {what} (last={last!r})")


@pytest.mark.slow
@requires_full_stack
def test_e2e_pitr_undoes_a_change(barman_project):
    """Full PITR cycle: a change made after a restore point is rolled back.

    1. take a base backup
    2. write a row we want to KEEP, then create a named restore point
    3. write a row we want to UNDO (the "mistake"), after the restore point
    4. recover to the restore point
    5. assert the KEEP row survived, the UNDO row is gone, and postgres came
       back read-write (auto-promoted, not stuck in read-only recovery)
    """
    project = barman_project

    # Streaming must be up before a (pg_basebackup-based) backup can run.
    # `barman check` output is printed each attempt so a failure is diagnosable
    # from the CI log (which check — connection / slot / WAL streaming — fails).
    def _backup_ready():
        project.run("barman", "check", check=False, timeout=120)
        return (
            project.run(
                "barman", "backup", check=False, timeout=300
            ).returncode
            == 0
        )

    _retry(
        _backup_ready,
        timeout=300,
        interval=15,
        what="first barman backup to succeed (streaming ready)",
    )

    # KEEP data + restore point (the recovery target).
    _sql(project, "DROP TABLE IF EXISTS pitr_demo")
    _sql(project, "CREATE TABLE pitr_demo (note text)")
    _sql(project, "INSERT INTO pitr_demo VALUES ('keep')")
    _sql(project, "SELECT pg_create_restore_point('pitr_marker')")
    # Force the WAL segment holding the restore point to be completed + archived.
    project.run("barman", "switch-wal", check=False, timeout=180)

    # The change to undo, made strictly AFTER the restore point.
    _sql(project, "INSERT INTO pitr_demo VALUES ('undo_me')")
    project.run("barman", "switch-wal", check=False, timeout=180)

    # Recovery needs all WAL from the base backup up to the restore point in the
    # catalog. The barman container moves streamed WAL into the catalog on its
    # ~30s cron cycle, so wait for a couple of cycles before the (destructive,
    # one-shot) recover.
    time.sleep(75)

    # Recover to the named restore point (destructive: swaps the pg volume).
    project.run_force(
        "barman", "recover", "--target-name", "pitr_marker", timeout=300
    )

    # Postgres restarts, replays WAL to the restore point, then promotes.
    _retry(
        lambda: project.run(
            "psql", "--sql", "SELECT 1", check=False, timeout=60
        ).returncode
        == 0,
        timeout=180,
        interval=5,
        what="postgres to accept connections after recovery",
    )
    _retry(
        lambda: "f"
        in _sql(project, "SELECT pg_is_in_recovery()", check=False)
        .lower()
        .split(),
        timeout=120,
        interval=5,
        what="postgres to finish recovery and promote (read-write)",
    )

    # The KEEP row survived; the UNDO row was rolled back.
    notes = _sql(project, "SELECT string_agg(note, ',') FROM pitr_demo")
    assert (
        "keep" in notes
    ), f"expected the pre-restore-point row to survive: {notes!r}"
    assert (
        "undo_me" not in notes
    ), f"post-restore-point row should be gone: {notes!r}"

    # Promotion check: a write must succeed (not stuck in read-only recovery).
    project.run(
        "psql", "--sql", "CREATE TABLE pitr_promote_check (x int)", timeout=60
    )

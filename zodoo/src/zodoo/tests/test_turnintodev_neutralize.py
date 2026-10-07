"""Tests for running Odoo's official `odoo-bin neutralize` on restore.

zodoo used to collect the modules' data/neutralize.sql itself; now Odoo's own
command runs in a one-off odoo container, so every installed module (core,
enterprise, zSYNC, ...) is neutralized exactly the way Odoo does it and
database.is_neutralized is set. During a restore the database still lives as
<db>_restoring on a helper postgres container - the command must be pointed
there, not at the project's regular database.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from zodoo import lib_backup
from zodoo import lib_standard_image
from zodoo import lib_turnintodev as mod
from zodoo import odoo_config
from zodoo import tools

CONFIG_DIR = Path(mod.__file__).parents[3] / "odoo" / "config"


@pytest.fixture
def dcrun(monkeypatch):
    calls = []
    result = {"returncode": 0}

    def fake_dcrun(config, cmd, env={}, **kwargs):
        calls.append({"cmd": cmd, "env": dict(env)})
        return result["returncode"], ""

    monkeypatch.setattr(tools, "__dcrun", fake_dcrun)
    monkeypatch.setattr(mod, "table_exists", lambda conn, table: True)
    monkeypatch.setattr(odoo_config, "current_version", lambda: 19.0)
    monkeypatch.setattr(
        lib_standard_image, "is_standard_image", lambda config: False
    )
    return SimpleNamespace(calls=calls, result=result)


def _conn(dbname="odoo_restoring"):
    return SimpleNamespace(dbname=dbname)


def test_runs_odoo_neutralize_script_in_our_image(dcrun):
    mod._run_odoo_neutralize(SimpleNamespace(), _conn())

    (call,) = dcrun.calls
    assert call["cmd"] == [
        "odoo",
        "/odoolib/entrypoint.sh",
        "/odoolib/neutralize.py",
    ]
    assert call["env"] == {"DBNAME": "odoo_restoring"}


def test_restore_points_container_to_helper_postgres(dcrun):
    mod._run_odoo_neutralize(
        SimpleNamespace(), _conn(), db_host="postgres_1234"
    )

    (call,) = dcrun.calls
    assert call["env"] == {
        "DBNAME": "odoo_restoring",
        "DB_HOST": "postgres_1234",
    }


def test_standard_image_calls_odoo_cli_directly(dcrun, monkeypatch):
    monkeypatch.setattr(
        lib_standard_image, "is_standard_image", lambda config: True
    )

    mod._run_odoo_neutralize(
        SimpleNamespace(), _conn(), db_host="postgres_1234"
    )

    (call,) = dcrun.calls
    assert call["cmd"][:3] == ["odoo", "odoo", "neutralize"]
    assert call["cmd"][call["cmd"].index("-d") + 1] == "odoo_restoring"
    assert call["cmd"][-2:] == ["--db_host", "postgres_1234"]


def test_failure_aborts_loudly(dcrun):
    dcrun.result["returncode"] = 1

    with pytest.raises(SystemExit):
        mod._run_odoo_neutralize(SimpleNamespace(), _conn())


@pytest.mark.parametrize("version", [11.0, 15.0])
def test_skipped_before_odoo_16(dcrun, monkeypatch, version):
    monkeypatch.setattr(odoo_config, "current_version", lambda: version)

    mod._run_odoo_neutralize(SimpleNamespace(), _conn())

    assert dcrun.calls == []


def test_skipped_on_uninitialized_database(dcrun, monkeypatch):
    monkeypatch.setattr(mod, "table_exists", lambda conn, table: False)

    mod._run_odoo_neutralize(SimpleNamespace(), _conn())

    assert dcrun.calls == []


@pytest.fixture
def after_restore(monkeypatch):
    calls = []
    monkeypatch.setattr(
        mod,
        "__turn_into_devdb",
        lambda ctx, config, conn, db_host=None: calls.append(
            ("turn_into_dev", db_host)
        ),
    )
    monkeypatch.setattr(
        mod,
        "_run_odoo_neutralize",
        lambda config, conn, db_host=None: calls.append(
            ("neutralize", db_host)
        ),
    )
    monkeypatch.setattr(lib_backup, "remove_webassets", lambda conn: None)
    return calls


def test_devmode_restore_runs_full_dev_scripts(after_restore):
    config = SimpleNamespace(devmode=True)

    lib_backup._after_restore(
        None, _conn(), config, False, False, db_host="postgres_1234"
    )

    assert after_restore == [("turn_into_dev", "postgres_1234")]


def test_neutralize_option_without_devmode(after_restore):
    config = SimpleNamespace(devmode=False)

    lib_backup._after_restore(
        None, _conn(), config, False, False, neutralize=True, db_host="pg"
    )

    assert after_restore == [("neutralize", "pg")]


def test_plain_restore_without_devmode_stays_untouched(after_restore):
    config = SimpleNamespace(devmode=False)

    lib_backup._after_restore(None, _conn(), config, False, False)

    assert after_restore == []


@pytest.mark.parametrize("version", ["16", "17", "18", "19", "20"])
def test_turndb2dev_keeps_only_what_core_does_not_cover(version):
    sql = (CONFIG_DIR / version / "turndb2dev.sql").read_text()

    # covered by base/data/neutralize.sql, which keeps autovacuum running
    assert "update ir_cron" not in sql
    # not covered by Odoo core
    assert "set totp_secret = null" in sql
    assert "key = 'database.uuid'" in sql
    assert "database.enterprise_code" in sql


@pytest.mark.parametrize(
    "version, file, skipped",
    [
        (19.0, "addons/my_module/data/neutralize.sql", True),
        (16.0, "my_module/data/neutralize.sql", True),
        (19.0, "devscripts/extra_neutralize.sql", False),
        (15.0, "my_module/data/neutralize.sql", False),
    ],
)
def test_manifest_module_neutralize_sql_not_run_twice(
    monkeypatch, version, file, skipped
):
    monkeypatch.setattr(odoo_config, "current_version", lambda: version)

    assert mod._run_by_odoo_neutralize(file) is skipped

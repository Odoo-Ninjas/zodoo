"""Unit tests for `odoo_process_env` in `odoo/bin/odoo_env.py` (issue #258).

From Odoo 19 on, ODOO_<OPTION> in the environment beats the config file.
The container default ODOO_MAX_CRON_THREADS=2 made every odoo process -
web server, queue job runner, debug - start two cron threads although
zodoo writes max_cron_threads = 0 into their config files, so
RUN_ODOO_CRONJOBS=0 did not stop the cronjobs.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "odoo" / "bin"))

from odoo_env import config_file_env_names, odoo_process_env  # noqa: E402

CONTAINER_ENV = {
    "ODOO_MAX_CRON_THREADS": "2",
    "ODOO_LOG_LEVEL": "debug",
    "ODOO_DATA_DIR": "/opt/files",
    "ODOO_DBFILTER": "",
    # zodoo-only settings that Odoo does not know
    "ODOO_DEMO": "1",
    "ODOO_QUEUEJOBS_CHANNELS": "root:1",
    "RUN_ODOO_CRONJOBS": "0",
    "PATH": "/usr/bin",
}


@pytest.fixture
def role_config(tmp_path):
    path = tmp_path / "config_webserver"
    path.write_text(
        "[options]\n"
        "max_cron_threads = 0\n"
        "log_level = error\n"
        "data_dir = /opt/files\n"
        "dbfilter = \n"
        "\n"
        "[queue_job]\n"
        "channels = root:0\n"
    )
    return path


@pytest.mark.parametrize("version", [19.0, 20.0, "19.0"])
def test_config_file_beats_environment(role_config, version):
    env, removed = odoo_process_env(CONTAINER_ENV, role_config, version)
    assert removed == [
        "ODOO_DATA_DIR",
        "ODOO_DBFILTER",
        "ODOO_LOG_LEVEL",
        "ODOO_MAX_CRON_THREADS",
    ]
    for name in removed:
        assert name not in env


def test_unrelated_variables_are_kept(role_config):
    env, _ = odoo_process_env(CONTAINER_ENV, role_config, 19.0)
    assert env["ODOO_DEMO"] == "1"
    assert env["ODOO_QUEUEJOBS_CHANNELS"] == "root:1"
    assert env["RUN_ODOO_CRONJOBS"] == "0"
    assert env["PATH"] == "/usr/bin"


def test_other_sections_do_not_count(role_config):
    # [queue_job] channels is not an Odoo option -> ODOO_CHANNELS stays
    env, removed = odoo_process_env({"ODOO_CHANNELS": "x"}, role_config, 19.0)
    assert removed == []
    assert env == {"ODOO_CHANNELS": "x"}


@pytest.mark.parametrize("version", [16.0, 17.0, 18.0, "18.0"])
def test_older_versions_unchanged(role_config, version):
    env, removed = odoo_process_env(CONTAINER_ENV, role_config, version)
    assert removed == []
    assert env == CONTAINER_ENV


def test_caller_environment_is_not_modified(role_config):
    before = dict(CONTAINER_ENV)
    odoo_process_env(CONTAINER_ENV, role_config, 19.0)
    assert CONTAINER_ENV == before


def test_missing_config_file(tmp_path):
    env, removed = odoo_process_env(CONTAINER_ENV, tmp_path / "nope", 19.0)
    assert removed == []
    assert env == CONTAINER_ENV


@pytest.mark.parametrize("version", ["19", "20"])
@pytest.mark.parametrize(
    "role",
    ["config_webserver", "config_queuejob", "config_update", "config_debug"],
)
def test_shipped_role_configs_hide_cron_threads(version, role):
    """The roles that must not run the configured cron threads all set
    max_cron_threads themselves, so the container value is not passed on."""
    path = REPO_ROOT / "odoo" / "config" / version / "config" / role
    assert "ODOO_MAX_CRON_THREADS" in config_file_env_names(path)

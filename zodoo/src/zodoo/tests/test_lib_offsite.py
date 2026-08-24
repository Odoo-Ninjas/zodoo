"""Tests for zodoo.lib_offsite.

The backup run itself lives in the offsite container (restic) and is not
checked here. What matters here are the host-side parts where a mistake is
expensive:

* deriving the area name (an invalid name would otherwise only bounce off the
  backup server, and differently for every customer),
* enrolling against the backup server (filing the request, remembering the
  state, taking over the credentials) - including the cases where NOTHING may
  be written into the settings.
"""

from __future__ import annotations

import json

import click
import pytest

from zodoo import lib_offsite as mod
from zodoo.click_config import Config


class FakeConfig(Config):
    """As in test_lib_backup: bypass Config so no project is needed."""

    def __init__(self, **kwargs):
        self._project_name = kwargs.pop("project_name", "zodoo_unit_test")
        self._verbose = False
        self._host_run_dir = None
        self._WORKING_DIR = None
        self.force = False
        self.quiet = False
        self.restrict = {}
        self.dirs = {}
        self.files = {}
        self.commands = {}
        defaults = {
            "OFFSITE_PASSPHRASE": "",
            "OFFSITE_ENROLL_URL": "https://backup.invalid:8443",
        }
        defaults.update(kwargs)
        self.__dict__.update(defaults)


# ---------------------------------------------------------------------------
# _area_name
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "projectname,expected",
    [
        ("hpnprod17", "hpnprod17"),
        # Capitals and dots occur in project names, but not in area names.
        ("Logiston_Main", "logiston_main"),
        ("odoo.kunde", "odoo-kunde"),
        # Ticket names start with a letter, numeric prefixes do not: a letter
        # is then prepended instead of having the server reject the name.
        ("3dm", "p3dm"),
        # Duplicate and outer separators are collapsed.
        ("ZO--05123 Kunde ", "zo-05123-kunde"),
    ],
)
def test_area_name_derives_valid_names(projectname, expected):
    assert mod._area_name(FakeConfig(), projectname) == expected


def test_area_name_aborts_when_nothing_usable_remains():
    # Special characters only: no name can be formed from that. Better to
    # abort here than to file a broken request.
    with pytest.raises(SystemExit):
        mod._area_name(FakeConfig(), "!!!")


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


def _run_register(config, monkeypatch, answers, name=None, note=""):
    """Ruft die register-Logik mit vorgegebenen Serverantworten auf.

    answers: Liste von (methode, pfad-fragment, antwort) in Aufrufreihenfolge.
    """
    calls = []
    written = {}

    def fake_call(cfg, method, path, payload=None):
        calls.append((method, path, payload))
        expect_method, expect_fragment, answer = answers.pop(0)
        assert method == expect_method
        assert expect_fragment in path
        return answer

    monkeypatch.setattr(mod, "_enroll_call", fake_call)
    monkeypatch.setattr(
        "zodoo.tools.update_setting",
        lambda cfg, key, value, **kw: written.__setitem__(key, value),
    )
    # pass_config takes the config from the click context
    # (make_pass_decorator), hence a context with our FakeConfig as obj.
    ctx = click.Context(mod.offsite_register)
    ctx.obj = config
    with ctx:
        mod.offsite_register.callback(name=name, note=note)
    return calls, written


@pytest.fixture
def config_with_rundir(tmp_path):
    cfg = FakeConfig(project_name="testkunde")
    cfg._host_run_dir = tmp_path
    # So that the certificate is not fetched over the network.
    (tmp_path / "offsite").mkdir()
    (tmp_path / "offsite" / "rest-server.crt").write_text("PEM")
    return cfg


def test_register_first_call_creates_request_and_stores_state(
    config_with_rundir, monkeypatch
):
    calls, written = _run_register(
        config_with_rundir,
        monkeypatch,
        [
            (
                "POST",
                "/api/request",
                {
                    "request_id": "abc123",
                    "pickup_token": "tok",
                    "status": "pending",
                },
            )
        ],
    )
    # Beim ersten Aufruf darf noch NICHTS in die Settings wandern.
    assert written == {}
    state = json.loads(
        (
            config_with_rundir._host_run_dir / "offsite" / "enroll.json"
        ).read_text()
    )
    assert state == {
        "area": "testkunde",
        "request_id": "abc123",
        "token": "tok",
    }
    assert calls[0][2]["area"] == "testkunde"
    # Ohne eigene Passphrase soll der Server einen Repo-Key erzeugen.
    assert calls[0][2]["own_repo_key"] is False


def test_register_passes_own_repo_key_when_passphrase_exists(
    config_with_rundir, monkeypatch
):
    # Shop/zCICD legen die Passphrase je Projekt selbst ab. Dann darf der
    # Server keinen zweiten Schluessel erfinden.
    config_with_rundir.__dict__["OFFSITE_PASSPHRASE"] = "vom-backend"
    calls, _ = _run_register(
        config_with_rundir,
        monkeypatch,
        [("POST", "/api/request", {"request_id": "x", "pickup_token": "t"})],
    )
    assert calls[0][2]["own_repo_key"] is True


def test_register_pending_writes_no_settings(config_with_rundir, monkeypatch):
    edir = config_with_rundir._host_run_dir / "offsite"
    (edir / "enroll.json").write_text(
        json.dumps({"area": "testkunde", "request_id": "abc", "token": "tok"})
    )
    _, written = _run_register(
        config_with_rundir,
        monkeypatch,
        [("GET", "/api/status", {"status": "pending"})],
    )
    assert written == {}


def test_register_write_only_server_leaves_no_readable_key(
    config_with_rundir, monkeypatch
):
    """The current backup server issues no repository key at all.

    That is the whole point of the write-only path: the machine gets an upload
    account and two PUBLIC age keys, so it can encrypt and nothing else. If a
    passphrase ended up in the settings here, the machine could read its own
    history again and the exercise would be pointless - so this asserts the
    absence, not just the presence.
    """
    edir = config_with_rundir._host_run_dir / "offsite"
    (edir / "enroll.json").write_text(
        json.dumps({"area": "testkunde", "request_id": "abc", "token": "tok"})
    )
    _, written = _run_register(
        config_with_rundir,
        monkeypatch,
        [
            (
                "GET",
                "/api/status",
                {
                    "status": "approved",
                    "user": "testkunde",
                    "password": "zugang",
                    "wo_url": "https://10.222.0.106:8444/testkunde/",
                    "wo_recipient": "age1filestore",
                    "wo_db_recipient": "age1database",
                    "ca_cert": "PEM-NEU",
                },
            )
        ],
    )
    assert written["OFFSITE_REST_USER"] == "testkunde"
    assert written["OFFSITE_REST_PASSWORD"] == "zugang"
    assert written["OFFSITE_WO_URL"] == "https://10.222.0.106:8444/testkunde/"
    assert written["OFFSITE_WO_RECIPIENT"] == "age1filestore"
    assert written["OFFSITE_WO_DB_RECIPIENT"] == "age1database"
    assert written["RUN_OFFSITE"] == "1"
    # The two that must NOT appear.
    assert "OFFSITE_PASSPHRASE" not in written
    assert "OFFSITE_REPO" not in written


def test_register_approved_writes_settings_and_clears_state(
    config_with_rundir, monkeypatch
):
    edir = config_with_rundir._host_run_dir / "offsite"
    (edir / "enroll.json").write_text(
        json.dumps({"area": "testkunde", "request_id": "abc", "token": "tok"})
    )
    _, written = _run_register(
        config_with_rundir,
        monkeypatch,
        [
            (
                "GET",
                "/api/status",
                {
                    "status": "approved",
                    "user": "testkunde",
                    "password": "zugang",
                    "repo_key": "geheim",
                    "repo_url": "rest:https://10.222.0.106:8000/testkunde/",
                    "ca_cert": "PEM-NEU",
                },
            )
        ],
    )
    assert (
        written["OFFSITE_REPO"] == "rest:https://10.222.0.106:8000/testkunde/"
    )
    assert written["OFFSITE_REST_USER"] == "testkunde"
    assert written["OFFSITE_REST_PASSWORD"] == "zugang"
    assert written["OFFSITE_PASSPHRASE"] == "geheim"
    assert written["RUN_OFFSITE"] == "1"
    assert (edir / "rest-server.crt").read_text() == "PEM-NEU"
    # The request is done and must not linger as an open one.
    assert not (edir / "enroll.json").exists()


def test_register_keeps_own_passphrase_when_server_sends_none(
    config_with_rundir, monkeypatch
):
    config_with_rundir.__dict__["OFFSITE_PASSPHRASE"] = "vom-backend"
    edir = config_with_rundir._host_run_dir / "offsite"
    (edir / "enroll.json").write_text(
        json.dumps({"area": "testkunde", "request_id": "abc", "token": "tok"})
    )
    _, written = _run_register(
        config_with_rundir,
        monkeypatch,
        [
            (
                "GET",
                "/api/status",
                {
                    "status": "approved",
                    "user": "testkunde",
                    "password": "zugang",
                    "repo_key": "",
                    "repo_url": "rest:https://10.222.0.106:8000/testkunde/",
                },
            )
        ],
    )
    # Die Passphrase der Maschine bleibt stehen - sie ist die Wahrheit.
    assert "OFFSITE_PASSPHRASE" not in written


def test_register_rejected_aborts_and_drops_state(
    config_with_rundir, monkeypatch
):
    edir = config_with_rundir._host_run_dir / "offsite"
    (edir / "enroll.json").write_text(
        json.dumps({"area": "testkunde", "request_id": "abc", "token": "tok"})
    )
    with pytest.raises(SystemExit):
        _run_register(
            config_with_rundir,
            monkeypatch,
            [("GET", "/api/status", {"status": "rejected"})],
        )
    assert not (edir / "enroll.json").exists()


def test_register_delivered_does_not_overwrite_settings(
    config_with_rundir, monkeypatch
):
    # The server hands the data out exactly once. A second call must not run
    # over the settings with empty values.
    edir = config_with_rundir._host_run_dir / "offsite"
    (edir / "enroll.json").write_text(
        json.dumps({"area": "testkunde", "request_id": "abc", "token": "tok"})
    )
    with pytest.raises(SystemExit):
        _run_register(
            config_with_rundir,
            monkeypatch,
            [("GET", "/api/status", {"status": "delivered"})],
        )


# ---------------------------------------------------------------------------
# write-only filestore path
# ---------------------------------------------------------------------------
def test_wo_configured_needs_both_url_and_recipient():
    """Half a configuration is worse than none: a URL without a recipient would
    upload plaintext, a recipient without a URL uploads nowhere."""
    assert not mod._wo_configured(FakeConfig())
    assert not mod._wo_configured(
        FakeConfig(OFFSITE_WO_URL="https://x/y/", OFFSITE_WO_RECIPIENT="")
    )
    assert not mod._wo_configured(
        FakeConfig(OFFSITE_WO_URL="", OFFSITE_WO_RECIPIENT="age1abc")
    )
    assert mod._wo_configured(
        FakeConfig(OFFSITE_WO_URL="https://x/y/", OFFSITE_WO_RECIPIENT="age1abc")
    )


def test_wo_configured_ignores_whitespace_only_values():
    assert not mod._wo_configured(
        FakeConfig(OFFSITE_WO_URL="  ", OFFSITE_WO_RECIPIENT="  ")
    )


def test_state_dir_is_created(tmp_path):
    cfg = FakeConfig()
    cfg._host_run_dir = tmp_path
    d = mod._state_dir(cfg)
    assert d.is_dir()
    assert d == tmp_path / "offsite.state"


def test_state_dir_replaces_the_empty_file_docker_leaves_behind(tmp_path):
    """A bind-mount source that does not exist yet is created by docker, and it
    guesses - often as an empty file. The mount then succeeds and the ledger
    cannot be written, which is a confusing failure far from its cause."""
    cfg = FakeConfig()
    cfg._host_run_dir = tmp_path
    stray = tmp_path / "offsite.state"
    stray.touch()
    assert stray.is_file()

    d = mod._state_dir(cfg)

    assert d.is_dir()


def test_state_dir_refuses_to_delete_a_non_empty_file(tmp_path):
    """Only docker's empty artefact is disposable. Anything with content might
    be somebody's data, so we stop instead of guessing."""
    cfg = FakeConfig()
    cfg._host_run_dir = tmp_path
    stray = tmp_path / "offsite.state"
    stray.write_text("something someone cares about")

    with pytest.raises(SystemExit):
        mod._state_dir(cfg)

    assert stray.read_text() == "something someone cares about"


def test_filestore_command_aborts_without_a_write_only_target(tmp_path):
    """It must not fall back to anything: silently doing nothing would look
    like a successful backup."""
    cfg = FakeConfig()
    cfg._host_run_dir = tmp_path
    ctx = click.Context(mod.offsite_filestore)
    ctx.obj = cfg
    with ctx:
        with pytest.raises(SystemExit):
            mod.offsite_filestore.callback()


# ---------------------------------------------------------------------------
# offsite/__after_settings.py
# ---------------------------------------------------------------------------
def _after_settings():
    import importlib.util
    from pathlib import Path as _P

    path = _P(__file__).resolve().parents[4] / "offsite" / "__after_settings.py"
    spec = importlib.util.spec_from_file_location("offsite_after_settings", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.after_settings


def test_wal_cron_is_dropped_when_no_write_only_target():
    """1440 CLI starts a day for nothing is not free.

    The minutely WAL job only has work when a write-only database target is
    configured. Measured at 0.44 s per start, leaving it defined costs about ten
    minutes of CPU per day on every instance that does not use it - and an empty
    CRONJOB_* value is skipped by the cron daemon, so clearing it removes the job
    rather than breaking it.
    """
    after_settings = _after_settings()
    settings = {"CRONJOB_OFFSITE_WAL": "* * * * * odoo offsite wal"}
    after_settings(settings, None)
    assert settings["CRONJOB_OFFSITE_WAL"] == ""


def test_wal_cron_survives_when_the_target_is_configured():
    after_settings = _after_settings()
    settings = {
        "CRONJOB_OFFSITE_WAL": "* * * * * odoo offsite wal",
        "OFFSITE_WO_URL": "https://backup.invalid:8444/kunde/",
        "OFFSITE_WO_DB_RECIPIENT": "age1abc",
    }
    after_settings(settings, None)
    assert settings["CRONJOB_OFFSITE_WAL"] == "* * * * * odoo offsite wal"


def test_wal_cron_is_dropped_when_only_half_configured():
    """A URL without a recipient would upload plaintext - so it is not a
    configuration, and the job has nothing to do."""
    after_settings = _after_settings()
    settings = {
        "CRONJOB_OFFSITE_WAL": "* * * * * odoo offsite wal",
        "OFFSITE_WO_URL": "https://backup.invalid:8444/kunde/",
    }
    after_settings(settings, None)
    assert settings["CRONJOB_OFFSITE_WAL"] == ""

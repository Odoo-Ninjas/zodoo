"""`odoo robot run-all` exits non-zero when a suite fails on every retry.

`run_all` calls `run` with ``no_sysexit=True`` so that a failed attempt can be
retried. The result of the last attempt used to be dropped, so run-all always
exited with 0 (issue #270).
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from zodoo import lib_robot as mod
from zodoo import odoo_config
from zodoo import robo_helpers
from zodoo.click_config import Config


class FakeConfig(Config):
    def __init__(self):
        self._project_name = "zodoo_unit_test"
        self._verbose = False
        self._host_run_dir = None
        self._WORKING_DIR = None
        self.force = False
        self.quiet = False
        self.restrict = {}
        self.dirs = {}
        self.files = {}
        self.commands = {}
        self.__dict__.update({"devmode": True, "DEVMODE": True})


SUITES = ["tests/test_a.robot", "tests/test_b.robot"]


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(odoo_config, "customs_dir", lambda: tmp_path)
    monkeypatch.setattr(
        robo_helpers, "_get_run_all_robottest_files", lambda: SUITES
    )
    monkeypatch.setattr(mod, "_remove_service", lambda *a, **kw: None)
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    return tmp_path


def _run_all(monkeypatch, outcomes, args=None):
    """outcomes: file -> list of results per attempt."""
    calls = []

    def fake_run(file, timeout, no_sysexit):
        assert no_sysexit
        calls.append(file)
        result = outcomes[file].pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(mod, "run", fake_run)
    res = CliRunner().invoke(mod.run_all, args or ["--retry", "2"], obj=FakeConfig())
    return res, calls


def test_all_suites_pass_exits_zero(project, monkeypatch):
    res, calls = _run_all(
        monkeypatch, {"tests/test_a.robot": [True], "tests/test_b.robot": [True]}
    )
    assert res.exit_code == 0, res.output
    assert calls == SUITES
    assert "Failed: 0 of 2" in res.output


def test_failed_suite_exits_non_zero(project, monkeypatch):
    res, calls = _run_all(
        monkeypatch,
        {"tests/test_a.robot": [False, False], "tests/test_b.robot": [True]},
    )
    assert res.exit_code != 0
    # the failure does not stop the remaining suites
    assert calls == ["tests/test_a.robot", "tests/test_a.robot", "tests/test_b.robot"]
    assert "Failed: 1 of 2" in res.output
    assert "test_a.robot" in res.output.split("Failed: 1 of 2")[1]


def test_suite_passing_on_retry_counts_as_success(project, monkeypatch):
    res, _ = _run_all(
        monkeypatch,
        {"tests/test_a.robot": [False, True], "tests/test_b.robot": [True]},
    )
    assert res.exit_code == 0, res.output


def test_exception_on_every_attempt_counts_as_failure(project, monkeypatch):
    res, _ = _run_all(
        monkeypatch,
        {
            "tests/test_a.robot": [RuntimeError("boom")] * 2,
            "tests/test_b.robot": [True],
        },
    )
    assert res.exit_code != 0
    assert "Failed: 1 of 2" in res.output

"""Tests for zodoo.lib_command_log (.odoo-commands.log).

Covers what an entry contains, the outcome mapping (ok / error / aborted),
masking of secret-looking arguments, that a broken log never breaks the
command, that `update` and `restart` are wired up, and that the gitignore
rule really keeps the file out of git (checked with `git check-ignore`).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from zodoo import lib_command_log as mod
from zodoo.tests.test_lib_control import FakeConfig, _patch_lib_with_docker

TEMPLATES = (
    Path(__file__).resolve().parents[4] / "templates" / "customs_template"
)


def _entries(logdir):
    logfile = logdir / mod.LOG_FILENAME
    return [json.loads(line) for line in logfile.read_text().splitlines()]


def _command(body):
    @click.command()
    @mod.logged_command("dummy")
    def cmd():
        body()

    return cmd


@pytest.fixture
def argv(monkeypatch):
    def _set(*args):
        monkeypatch.setattr(
            sys, "argv", ["/home/someone/.local/bin/odoo", *args]
        )

    return _set


def test_successful_run_writes_one_entry(_command_log_to_tmp, argv):
    argv("update", "sale", "--no-dangling-check")
    res = CliRunner().invoke(_command(lambda: None))
    assert res.exit_code == 0
    [entry] = _entries(_command_log_to_tmp)
    assert entry["command"] == "dummy"
    assert entry["argv"] == ["update", "sale", "--no-dangling-check"]
    assert entry["result"] == "ok"
    assert entry["exit_code"] == 0
    assert entry["error_type"] is None
    assert entry["nested"] is False
    assert isinstance(entry["duration_s"], float)
    # local time with UTC offset, e.g. 2026-10-05T15:32:32+02:00
    assert "T" in entry["ts"] and entry["ts"][-6] in "+-"


def test_program_path_is_not_logged(_command_log_to_tmp, argv):
    argv("restart")
    CliRunner().invoke(_command(lambda: None))
    raw = (_command_log_to_tmp / mod.LOG_FILENAME).read_text()
    assert "/home/someone" not in raw


def test_runs_are_appended(_command_log_to_tmp, argv):
    argv("restart")
    for _ in range(3):
        CliRunner().invoke(_command(lambda: None))
    assert len(_entries(_command_log_to_tmp)) == 3


def test_exception_is_logged_as_error_without_message(
    _command_log_to_tmp, argv
):
    argv("update")

    def boom():
        raise ValueError("postgres://admin:geheim@db/x")

    res = CliRunner().invoke(_command(boom))
    assert isinstance(res.exception, ValueError)
    [entry] = _entries(_command_log_to_tmp)
    assert entry["result"] == "error"
    assert entry["exit_code"] == 1
    assert entry["error_type"] == "ValueError"
    assert "geheim" not in (_command_log_to_tmp / mod.LOG_FILENAME).read_text()


@pytest.mark.parametrize(
    "exc, result, code",
    [
        (SystemExit(4), "error", 4),
        (SystemExit(0), "ok", 0),
        (SystemExit(None), "ok", 0),
        (SystemExit("message"), "error", 1),
        (click.exceptions.Exit(2), "error", 2),
        (KeyboardInterrupt(), "aborted", 130),
        (click.Abort(), "aborted", 130),
    ],
)
def test_exit_paths(_command_log_to_tmp, argv, exc, result, code):
    argv("update")

    def leave():
        raise exc

    CliRunner().invoke(_command(leave))
    [entry] = _entries(_command_log_to_tmp)
    assert (entry["result"], entry["exit_code"]) == (result, code)


def test_nested_invocation_is_marked(_command_log_to_tmp, argv):
    argv("restore")
    inner = _command(lambda: None)

    @click.command()
    @mod.logged_command("outer")
    @click.pass_context
    def outer(ctx):
        ctx.invoke(inner)

    CliRunner().invoke(outer)
    entries = _entries(_command_log_to_tmp)
    assert [(e["command"], e["nested"]) for e in entries] == [
        ("dummy", True),
        ("outer", False),
    ]


@pytest.mark.parametrize(
    "args, expected",
    [
        (["--db-password=s3cret"], ["--db-password=***"]),
        (["--token", "abc", "sale"], ["--token", "***", "sale"]),
        (["-P", "sale"], ["-P", "sale"]),
        (
            ["--url=postgres://user:pw@host/db"],
            ["--url=postgres://***@host/db"],
        ),
        (["sale", "stock"], ["sale", "stock"]),
    ],
)
def test_sanitize_argv(args, expected):
    assert mod.sanitize_argv(args) == expected


def test_unwritable_log_only_warns(monkeypatch, argv):
    argv("update")

    def broken(*args, **kwargs):
        raise PermissionError("nope")

    monkeypatch.setattr(mod, "write_entry", broken)
    ran = []
    res = CliRunner().invoke(_command(lambda: ran.append(1)))
    assert res.exit_code == 0 and ran == [1]
    assert "could not write .odoo-commands.log" in res.output


def test_missing_project_dir_is_skipped(monkeypatch, argv):
    argv("update")
    monkeypatch.setattr(mod, "_log_directory", lambda: None)
    res = CliRunner().invoke(_command(lambda: None))
    assert res.exit_code == 0 and "WARNING" not in res.output


def test_update_and_restart_are_logged():
    from zodoo import lib_control, lib_module

    # functools.update_wrapper carries the marker through pass_config /
    # pass_context up to the click callback.
    assert lib_module.update.callback.logged_command == "update"
    assert lib_control.restart.callback.logged_command == "restart"


def test_restart_command_writes_entry(_command_log_to_tmp, argv, monkeypatch):
    from zodoo import lib_control

    argv("restart", "odoo")
    _patch_lib_with_docker(monkeypatch, restart=lambda *a, **kw: None)
    res = CliRunner().invoke(
        lib_control.restart,
        ["odoo"],
        obj=FakeConfig(project_name="myproj"),
        catch_exceptions=False,
    )
    assert res.exit_code == 0
    [entry] = _entries(_command_log_to_tmp)
    assert entry["command"] == "restart"
    assert entry["project"] == "myproj"
    assert entry["argv"] == ["restart", "odoo"]


# ---------------------------------------------------------------------------
# ignore protection
# ---------------------------------------------------------------------------

needs_git = pytest.mark.skipif(not shutil.which("git"), reason="needs git")


def _git(repo, *args, check=True):
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=check
    )


@needs_git
@pytest.mark.parametrize("existing", [None, "*.pyc\n", "*.pyc"])
def test_log_is_git_ignored_from_first_write(tmp_path, existing):
    repo = tmp_path / "project"
    repo.mkdir()
    _git(repo, "init", "-q")
    if existing is not None:
        (repo / ".gitignore").write_text(existing)

    mod.write_entry({"command": "update"}, directory=repo)
    mod.write_entry({"command": "restart"}, directory=repo)

    assert (
        _git(
            repo, "check-ignore", "-q", mod.LOG_FILENAME, check=False
        ).returncode
        == 0
    )
    status = _git(
        repo, "status", "--porcelain", "--untracked-files=all"
    ).stdout
    assert mod.LOG_FILENAME not in status
    rules = (repo / ".gitignore").read_text().splitlines()
    assert rules.count(mod.GITIGNORE_RULE) == 1
    if existing:
        assert "*.pyc" in rules


@needs_git
def test_rule_does_not_hide_files_in_subdirectories(tmp_path):
    """The rule is anchored: only the project-level log is ignored."""
    repo = tmp_path / "project"
    (repo / "addons").mkdir(parents=True)
    _git(repo, "init", "-q")
    mod.write_entry({"command": "update"}, directory=repo)
    nested = Path("addons") / mod.LOG_FILENAME
    (repo / nested).write_text("")
    assert (
        _git(repo, "check-ignore", "-q", str(nested), check=False).returncode
        == 1
    )


@pytest.mark.parametrize(
    "gitignore",
    sorted(TEMPLATES.glob("*/.gitignore")),
    ids=lambda p: p.parent.name,
)
def test_project_templates_ignore_runtime_logs(gitignore):
    rules = gitignore.read_text().splitlines()
    assert mod.GITIGNORE_RULE in rules
    assert "/update.log" in rules


def test_templates_found():
    assert len(list(TEMPLATES.glob("*/.gitignore"))) >= 10

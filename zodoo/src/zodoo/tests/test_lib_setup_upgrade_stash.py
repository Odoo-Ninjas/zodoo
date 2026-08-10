"""Tests for the stash handling of `odoo setup upgrade`.

`upgrade` stashes local changes in ~/.odoo/images before pulling and pops
them afterwards. When the upgrade touched the same file, the pop aborts —
that used to happen silently (`check=False`), so a locally patched
Dockerfile fragment looked gone while it was still in the stash.

These tests drive real git repositories; the point is exactly the git
behaviour, so faking subprocess would test nothing.
"""

from __future__ import annotations

import subprocess

from zodoo import lib_setup as mod


def _git(repo, *args):
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        encoding="utf-8",
        text=True,
        check=True,
    ).stdout


def _make_repo(tmp_path):
    repo = tmp_path / "images"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.email", "unit@test")
    _git(repo, "config", "user.name", "unit test")
    (repo / "config_common").write_text("dbfilter = .*\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "initial")
    return repo


def test_stashed_changes_are_restored_silently_on_success(tmp_path, capsys):
    repo = _make_repo(tmp_path)
    (repo / "config_common").write_text("dbfilter = ^mydb$\n")
    _git(repo, "stash", "--include-untracked")

    mod._restore_stashed_changes(repo)

    assert (repo / "config_common").read_text() == "dbfilter = ^mydb$\n"
    assert _git(repo, "stash", "list").strip() == ""
    assert "still in the stash" not in capsys.readouterr().out


def test_conflicting_stash_pop_is_reported_and_change_kept(tmp_path, capsys):
    """Regression: the pop failure was swallowed, so the local change looked
    lost. It must be named, and the stash entry must survive."""
    repo = _make_repo(tmp_path)
    (repo / "config_common").write_text("dbfilter = ^mydb$\n")
    _git(repo, "stash", "--include-untracked")

    # What the upgrade pulled in: the same line, changed upstream.
    (repo / "config_common").write_text("dbfilter = ^%d$\n")
    _git(repo, "commit", "--quiet", "-am", "upstream change")

    mod._restore_stashed_changes(repo)

    out = capsys.readouterr().out
    assert "still in the stash" in out
    assert "git stash pop" in out
    # Not lost: the entry is still there and holds the local change.
    assert "stash@{0}" in _git(repo, "stash", "list")
    assert "^mydb$" in _git(repo, "stash", "show", "-p")

"""update.log must be git-ignored before `odoo update` writes it.

Before, the rule was only added after a successful update (and not at all
with --no-progress), so an aborted first run left update.log untracked.
"""

from __future__ import annotations

import inspect
import shutil
import subprocess

import pytest

from zodoo import lib_module

needs_git = pytest.mark.skipif(not shutil.which("git"), reason="needs git")


def _git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True
    )


@needs_git
@pytest.mark.parametrize("existing", [None, "*.pyc", "*.pyc\n"])
def test_update_log_is_ignored_before_first_write(tmp_path, existing):
    _git(tmp_path, "init", "-q")
    if existing is not None:
        (tmp_path / ".gitignore").write_text(existing)

    lib_module._assure_update_log_ignored(tmp_path)
    (tmp_path / "update.log").write_text("")

    assert _git(tmp_path, "check-ignore", "-q", "update.log").returncode == 0
    assert "update.log" not in _git(tmp_path, "status", "--porcelain").stdout
    rules = (tmp_path / ".gitignore").read_text().splitlines()
    assert rules.count("/update.log") == 1
    if existing:
        assert "*.pyc" in rules


@pytest.mark.parametrize("rule", ["update.log", "/update.log"])
def test_existing_rule_is_not_duplicated(tmp_path, rule):
    """Projects carry either the old unanchored rule or the template one."""
    (tmp_path / ".gitignore").write_text(f"*.pyc\n{rule}\n")
    lib_module._assure_update_log_ignored(tmp_path)
    assert (tmp_path / ".gitignore").read_text() == f"*.pyc\n{rule}\n"


def test_update_ignores_log_before_truncating_it():
    source = inspect.getsource(inspect.unwrap(lib_module.update.callback))
    ensure = source.index("_assure_update_log_ignored(")
    truncate = source.index('update_log_file.write_text("")')
    assert ensure < truncate


@pytest.mark.parametrize(
    "existing, owner_uid, expected",
    [
        (None, 1000, [(1000, ".gitignore")]),  # created by a root run
        ("*.pyc\n", 1000, []),  # existing file keeps its owner
        (None, None, []),  # no OWNER_UID configured
    ],
)
def test_new_gitignore_is_handed_to_project_owner(
    tmp_path, monkeypatch, existing, owner_uid, expected
):
    from pathlib import Path

    from zodoo import tools

    calls = []
    monkeypatch.setattr(
        tools,
        "__try_to_set_owner",
        lambda uid, path, **kw: calls.append((uid, Path(path).name)),
    )
    if existing is not None:
        (tmp_path / ".gitignore").write_text(existing)
    lib_module._assure_update_log_ignored(tmp_path, owner_uid)
    assert calls == expected

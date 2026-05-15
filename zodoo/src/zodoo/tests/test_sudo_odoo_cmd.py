"""Unit tests for `sudo_odoo_cmd` in `odoo/bin/sudo_odoo.py`.

Would have caught the double-sudo-wrap bug fixed in
`fix/sudo-odoo-cmd-skip-when-already-odoo`: update_on_startup.py wraps
`/odoolib/odoo update` in `sudo -u odoo`, /odoolib/odoo then calls
exec_odoo() which called sudo_odoo_cmd() again — a second wrap that
fails with "odoo is not in the sudoers file" (only root can drop to
odoo; odoo itself is not a sudoer).
"""

import os
import sys
from pathlib import Path

import pytest

# sudo_odoo.py lives in odoo/bin/ — add that to sys.path so we can import it
# directly (the odoo/bin tree is only on PYTHONPATH inside the container).
REPO_ROOT = Path(__file__).resolve().parents[4]
ODOO_BIN = REPO_ROOT / "odoo" / "bin"
sys.path.insert(0, str(ODOO_BIN))

from sudo_odoo import should_wrap_for_odoo, sudo_odoo_cmd  # noqa: E402


class TestShouldWrapForOdoo:
    """Pure logic — no env, no syscalls."""

    def test_disabled_returns_false(self):
        # ODOO_SUDO_CMD is not "1" → never wrap
        assert should_wrap_for_odoo("odoo", None, 0) is False
        assert should_wrap_for_odoo("odoo", "", 0) is False
        assert should_wrap_for_odoo("odoo", "0", 0) is False

    def test_enabled_as_root_wraps(self):
        # root (uid 0) wants to run as odoo → wrap
        assert should_wrap_for_odoo("odoo", "1", 0) is True

    def test_enabled_as_odoo_does_not_wrap(self):
        # Already the odoo user → wrapping would fail with "not in sudoers"
        import pwd

        try:
            odoo_uid = pwd.getpwnam("nobody").pw_uid
        except KeyError:
            pytest.skip("nobody user not present")
        assert (
            should_wrap_for_odoo("nobody", "1", odoo_uid) is False
        ), "must not wrap — odoo is already odoo"

    def test_enabled_as_unknown_uid_wraps(self):
        # Unknown uid: safer to wrap (root-owned environment will succeed).
        assert should_wrap_for_odoo("odoo", "1", 987654321) is True


class TestSudoOdooCmd:
    """Integration with env vars and os.geteuid()."""

    def test_wraps_as_root(self, monkeypatch):
        monkeypatch.setenv("ODOO_SUDO_CMD", "1")
        monkeypatch.setenv("ODOO_USER", "odoo")
        monkeypatch.setattr(os, "geteuid", lambda: 0)
        result = sudo_odoo_cmd(["foo", "bar"])
        assert result == [
            "/usr/bin/sudo",
            "-E",
            "-H",
            "-u",
            "odoo",
            "foo",
            "bar",
        ]

    def test_does_not_wrap_when_disabled(self, monkeypatch):
        monkeypatch.setenv("ODOO_SUDO_CMD", "0")
        monkeypatch.setenv("ODOO_USER", "odoo")
        assert sudo_odoo_cmd(["foo"]) == ["foo"]

    def test_does_not_wrap_when_already_odoo(self, monkeypatch):
        # Core regression test for the double-sudo bug.
        import pwd

        monkeypatch.setenv("ODOO_SUDO_CMD", "1")
        # Use the test user's own uid and pass its name as "odoo_user".
        my_uid = os.getuid()
        my_name = pwd.getpwuid(my_uid).pw_name
        monkeypatch.setenv("ODOO_USER", my_name)
        monkeypatch.setattr(os, "geteuid", lambda: my_uid)
        assert sudo_odoo_cmd(["foo", "bar"]) == ["foo", "bar"]

    def test_explicit_odoo_user_parameter(self, monkeypatch):
        # odoo_user arg overrides ODOO_USER env var
        monkeypatch.setenv("ODOO_SUDO_CMD", "1")
        monkeypatch.delenv("ODOO_USER", raising=False)
        monkeypatch.setattr(os, "geteuid", lambda: 0)
        result = sudo_odoo_cmd(["foo"], odoo_user="bob")
        assert result[:5] == ["/usr/bin/sudo", "-E", "-H", "-u", "bob"]

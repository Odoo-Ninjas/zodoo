"""OWNER_UID must never end up as 0.

Where this comes from: `sudo -iu odoo` out of a root shell leaves
SUDO_USER=root behind. whoami() preferred SUDO_USER over the effective user,
so the settings got OWNER_UID=0, and the container's entrypoint then tried to
rename root - who owns PID 1. usermod refuses, the container exits 1, and the
message says nothing about OWNER_UID.

Three independent guards, one test class each.
"""

import sys
from pathlib import Path

import click
import pytest

from ..settings import _check_owner_uid
from ..tools import _sudo_vars_apply

# reuid.py lives in odoo/bin/ - only on PYTHONPATH inside the container
REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "odoo" / "bin"))

from reuid import owns_pid1  # noqa: E402


class TestSudoVarsApply:
    """whoami(): $SUDO_USER only counts when sudo took us to root."""

    def test_as_root_the_sudo_vars_apply(self, monkeypatch):
        monkeypatch.setattr("os.getuid", lambda: 0)
        assert _sudo_vars_apply() is True

    def test_as_a_normal_user_they_do_not(self, monkeypatch):
        # `sudo -iu odoo`: effective user is odoo, SUDO_USER is still root
        monkeypatch.setattr("os.getuid", lambda: 1001)
        assert _sudo_vars_apply() is False

    def test_whoami_ignores_sudo_user_when_not_root(self, monkeypatch):
        """The actual regression: SUDO_USER=root must not win here."""
        from .. import tools

        monkeypatch.setenv("SUDO_USER", "root")
        monkeypatch.setattr("os.getuid", lambda: 1001)
        monkeypatch.setattr(
            tools.subprocess, "check_output", lambda *a, **kw: "1001\n"
        )
        assert tools.whoami(id=True) == 1001

    def test_whoami_uses_sudo_user_when_root(self, monkeypatch):
        """Plain `sudo -i`: acting for the human who called sudo stays right."""
        from .. import tools

        monkeypatch.setenv("SUDO_USER", "marc")
        monkeypatch.setattr("os.getuid", lambda: 0)
        monkeypatch.setattr(
            tools.subprocess, "check_output", lambda *a, **kw: "1000\n"
        )
        assert tools.whoami(id=True) == 1000


class TestCheckOwnerUid:
    """The backstop in _export_settings - catches every other route in."""

    def test_zero_is_refused(self):
        with pytest.raises(click.ClickException) as ex:
            _check_owner_uid({"OWNER_UID": 0})
        assert "OWNER_UID" in str(ex.value)
        assert "su - " in str(ex.value), "must say how to fix it"

    def test_zero_as_string_is_refused(self):
        with pytest.raises(click.ClickException):
            _check_owner_uid({"OWNER_UID": "0"})

    def test_a_normal_uid_passes(self):
        _check_owner_uid({"OWNER_UID": 1000})

    def test_standard_image_may_keep_zero(self):
        """The official image does not run our entrypoint - nothing renames a
        user there, so a 0 is harmless and must not block the project."""
        _check_owner_uid({"OWNER_UID": 0, "ODOO_STANDARD_IMAGE": "1"})

    def test_missing_or_garbage_is_not_our_business(self):
        _check_owner_uid({})
        _check_owner_uid({"OWNER_UID": "nonsense"})


class TestOwnsPid1:
    """reuid.py refuses the rename instead of letting usermod fail blindly."""

    def test_matching_uid_is_detected(self, monkeypatch):
        monkeypatch.setattr(
            "os.stat", lambda path: type("S", (), {"st_uid": 0})()
        )
        assert owns_pid1(0) is True

    def test_other_uid_is_fine(self, monkeypatch):
        monkeypatch.setattr(
            "os.stat", lambda path: type("S", (), {"st_uid": 0})()
        )
        assert owns_pid1(1000) is False

    def test_no_procfs_does_not_raise(self, monkeypatch):
        def boom(path):
            raise OSError("no /proc here")

        monkeypatch.setattr("os.stat", boom)
        assert owns_pid1(0) is False

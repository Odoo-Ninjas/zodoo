"""Rootless docker: the container's root is the host user, not uid 0.

Under rootless docker, uid 0 inside a container maps to the unprivileged host
user who runs the daemon; every other container uid maps to a subuid range
nobody on the host owns. Our entrypoint renames `odoo` to OWNER_UID - with the
usual OWNER_UID=<host uid> that gives e.g. 1001 inside, which is subuid 166537
outside. The entrypoint's `chown -R` on /opt/run then hands the run directory
to that subuid, and the zodoo CLI on the host gets PermissionError on
~/.odoo/run/<project>/proxy_exchange.

The fix runs Odoo as root inside the container (OWNER_UID=0, no sudo to odoo)
and keeps the host side chowning to the real host user. Found on a pool VM
with one unix user per instance, 25.09.2026.
"""

import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from .. import lib_composer
from .. import settings as settings_mod
from ..settings import _apply_docker_rootless
from ..settings import _check_owner_uid
from ..settings import host_owner_uid

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "odoo" / "bin"))

from reuid import plan_uid_change  # noqa: E402


def _docker_info(monkeypatch, stdout="", returncode=0, raises=None):
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if raises:
            raise raises
        return subprocess.CompletedProcess(cmd, returncode, stdout, "")

    monkeypatch.setattr(settings_mod.subprocess, "run", fake_run)
    return calls


class TestApplyDockerRootless:
    def test_rootless_forces_container_root_and_no_sudo(self, monkeypatch):
        _docker_info(monkeypatch, raises=AssertionError("must not detect"))
        settings = {"DOCKER_ROOTLESS": "1", "OWNER_UID": 1001}
        _apply_docker_rootless(settings)
        assert str(settings["OWNER_UID"]) == "0"
        assert str(settings["ODOO_SUDO_CMD"]) == "0"

    def test_explicit_off_is_left_alone(self, monkeypatch):
        _docker_info(monkeypatch, raises=AssertionError("must not detect"))
        settings = {"DOCKER_ROOTLESS": "0", "OWNER_UID": 1000}
        _apply_docker_rootless(settings)
        assert settings["OWNER_UID"] == 1000
        assert "ODOO_SUDO_CMD" not in settings

    def test_detected_when_not_set(self, monkeypatch):
        calls = _docker_info(
            monkeypatch,
            stdout='["name=seccomp,profile=builtin","name=rootless","name=cgroupns"]\n',
        )
        settings = {"OWNER_UID": 1001}
        _apply_docker_rootless(settings)
        assert calls and calls[0][:2] == ["docker", "info"]
        assert settings["DOCKER_ROOTLESS"] == "1"
        assert str(settings["OWNER_UID"]) == "0"

    def test_rootful_daemon_detected_as_off(self, monkeypatch):
        _docker_info(
            monkeypatch,
            stdout='["name=apparmor","name=seccomp,profile=builtin"]\n',
        )
        settings = {"OWNER_UID": 1000}
        _apply_docker_rootless(settings)
        assert settings["DOCKER_ROOTLESS"] == "0"
        assert settings["OWNER_UID"] == 1000

    @pytest.mark.parametrize(
        "kw",
        [
            {"raises": FileNotFoundError("docker")},
            {"raises": subprocess.TimeoutExpired("docker", 15)},
            {"returncode": 1},
        ],
    )
    def test_no_answer_from_docker_means_off(self, monkeypatch, kw):
        _docker_info(monkeypatch, **kw)
        settings = {"OWNER_UID": 1000}
        _apply_docker_rootless(settings)
        assert settings["DOCKER_ROOTLESS"] == "0"
        assert settings["OWNER_UID"] == 1000


class TestCheckOwnerUidRootless:
    def test_zero_is_fine_under_rootless(self):
        _check_owner_uid({"OWNER_UID": 0, "DOCKER_ROOTLESS": "1"})


class TestHostOwnerUid:
    def test_rootless_host_side_is_the_calling_user(self, monkeypatch):
        monkeypatch.setattr(settings_mod.os, "getuid", lambda: 1001)
        assert (
            host_owner_uid({"OWNER_UID": "0", "DOCKER_ROOTLESS": "1"}) == 1001
        )

    def test_otherwise_it_is_owner_uid(self, monkeypatch):
        monkeypatch.setattr(settings_mod.os, "getuid", lambda: 4711)
        assert host_owner_uid({"OWNER_UID": "1000"}) == 1000


class TestPrepareFilesystem:
    """The one host-side chown that read OWNER_UID raw - with 0 that is a
    `sudo chown` to real root, which the pool user may not do."""

    def test_run_dirs_go_to_the_host_user(self, monkeypatch, tmp_path):
        settings_file = tmp_path / "settings"
        settings_file.write_text("OWNER_UID=0\nDOCKER_ROOTLESS=1\n")
        run_dir = tmp_path / "run"
        config = SimpleNamespace(
            files={"settings": settings_file}, dirs={"run": run_dir}
        )
        owners = []
        monkeypatch.setattr(
            lib_composer,
            "__try_to_set_owner",
            lambda uid, path: owners.append(uid),
        )
        monkeypatch.setattr(os, "getuid", lambda: 1001)
        lib_composer._prepare_filesystem(config)
        assert owners and set(owners) == {1001}


class TestPlanUidChange:
    """entrypoint.py: which uid `odoo` gets inside the container."""

    def test_zero_leaves_everything_as_is(self):
        # Rootless: Odoo runs as root, nothing is renamed. Renaming root
        # would also hit PID 1 (see reuid.owns_pid1).
        assert plan_uid_change(0, odoo_uid=1000) is None

    def test_host_uid_is_taken_over(self):
        assert plan_uid_change(1001, odoo_uid=1000) == (1000, 1001)

    def test_same_uid_is_a_noop(self):
        assert plan_uid_change(1000, odoo_uid=1000) is None

    def test_system_uids_are_shifted_out_of_the_way(self):
        # unchanged behaviour for uids below 1000
        assert plan_uid_change(501, odoo_uid=1000) == (501, 29499)

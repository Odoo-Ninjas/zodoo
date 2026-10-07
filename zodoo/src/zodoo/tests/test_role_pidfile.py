"""Unit tests for `odoo/bin/role_pidfile.py`.

A pidfile left in /tmp by the previous container run named a sibling role's
sh after the restart; kill_odoo() of the starting role signalled it, the
sibling's wrapper returned rc=0 while its odoo-bin kept the port, and the
wrapper then deleted the pidfile, so every respawn hit "Address already in
use". These tests pin down the ownership check that prevents both halves.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
ODOO_BIN = REPO_ROOT / "odoo" / "bin"
sys.path.insert(0, str(ODOO_BIN))

import role_pidfile  # noqa: E402


def _fake_proc(tmp_path, processes):
    """Build a fake procfs: {pid: [argv...]}."""
    proc = tmp_path / "proc"
    (proc / "self").mkdir(parents=True)
    for pid, argv in processes.items():
        d = proc / str(pid)
        d.mkdir()
        (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
    return proc


QUEUEJOBS = "/tmp/odoo.queuejobs.pid"
CRONJOBS = "/tmp/odoo.cronjobs.pid"


def _odoo_argv(pidfile):
    return [
        "/opt/venv/bin/python3",
        "/opt/src/odoo/odoo-bin",
        "-c",
        "/etc/odoo/config/config_queuejob",
        f"--pidfile={pidfile}",
    ]


def _sh_argv(pidfile):
    # exec_odoo runs odoo through `sh -c "<quoted cmd> || echo $? > f"`:
    # the whole command is one argv entry of the shell.
    return ["/bin/sh", "-c", f'"/usr/bin/sudo" "--pidfile={pidfile}" || true']


class TestPidIsRoleOdoo:
    def test_own_odoo_bin(self, tmp_path):
        proc = _fake_proc(tmp_path, {92: _odoo_argv(QUEUEJOBS)})
        assert role_pidfile.pid_is_role_odoo(92, QUEUEJOBS, proc=proc)

    def test_sibling_odoo_bin_is_not_ours(self, tmp_path):
        proc = _fake_proc(tmp_path, {92: _odoo_argv(QUEUEJOBS)})
        assert not role_pidfile.pid_is_role_odoo(92, CRONJOBS, proc=proc)

    def test_sibling_wrapper_shell_is_not_ours(self, tmp_path):
        # The case from the incident: the stale pid is the sibling's sh.
        proc = _fake_proc(tmp_path, {90: _sh_argv(QUEUEJOBS)})
        assert not role_pidfile.pid_is_role_odoo(90, QUEUEJOBS, proc=proc)
        assert not role_pidfile.pid_is_role_odoo(90, CRONJOBS, proc=proc)

    def test_gone_process(self, tmp_path):
        proc = _fake_proc(tmp_path, {})
        assert not role_pidfile.pid_is_role_odoo(4711, QUEUEJOBS, proc=proc)

    def test_without_procfs_keeps_old_behaviour(self, tmp_path):
        assert role_pidfile.pid_is_role_odoo(1, QUEUEJOBS, proc=tmp_path / "x")


class TestOwnedPidAndRemove:
    def test_stale_pid_of_sibling_is_not_owned(self, tmp_path):
        pidfile = tmp_path / "odoo.cronjobs.pid"
        pidfile.write_text("90\n")
        proc = _fake_proc(tmp_path, {90: _sh_argv("/tmp/odoo.queuejobs.pid")})
        assert role_pidfile.owned_pid(pidfile, proc=proc) is None

    def test_garbage_pidfile(self, tmp_path):
        pidfile = tmp_path / "odoo.web.pid"
        pidfile.write_text("")
        proc = _fake_proc(tmp_path, {})
        assert role_pidfile.owned_pid(pidfile, proc=proc) is None
        assert role_pidfile.remove_unless_alive(pidfile, proc=proc)
        assert not pidfile.exists()

    def test_keeps_pidfile_while_server_runs(self, tmp_path):
        pidfile = tmp_path / "odoo.queuejobs.pid"
        pidfile.write_text("92")
        proc = _fake_proc(tmp_path, {92: _odoo_argv(pidfile)})
        assert role_pidfile.owned_pid(pidfile, proc=proc) == 92
        assert not role_pidfile.remove_unless_alive(pidfile, proc=proc)
        assert pidfile.exists()

    def test_removes_pidfile_when_server_gone(self, tmp_path):
        pidfile = tmp_path / "odoo.queuejobs.pid"
        pidfile.write_text("92")
        proc = _fake_proc(tmp_path, {})
        assert role_pidfile.remove_unless_alive(pidfile, proc=proc)
        assert not pidfile.exists()


@pytest.mark.skipif(not Path("/proc/self/cmdline").exists(), reason="needs procfs")
def test_real_process(tmp_path):
    pidfile = tmp_path / "odoo.queuejobs.pid"
    other = tmp_path / "odoo.cronjobs.pid"
    p = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)", f"--pidfile={pidfile}"]
    )
    try:
        pidfile.write_text(str(p.pid))
        other.write_text(str(p.pid))
        assert role_pidfile.owned_pid(pidfile) == p.pid
        assert role_pidfile.owned_pid(other) is None
    finally:
        p.kill()
        p.wait()
    assert role_pidfile.owned_pid(pidfile) is None

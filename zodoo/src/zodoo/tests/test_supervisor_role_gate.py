"""Unit tests for the role gate / respawn policy in `odoo/bin/supervisor.py`.

Would have caught the cronjobs hot-respawn loop: `odoo update` ends with an
unconditional `supervisor.py start cronjobs`, so on an instance running with
RUN_ODOO_CRONJOBS=0 the role got want_running=True, its child exited
immediately ("Cronjobs shall not run. Good-bye!"), was reaped and respawned
about twice a second — for days, burning ~50% of a core. Every respawn also
runs kill_odoo(), so the loop keeps shooting at the live web workers.

Also covers the two ways a second supervisor could be started inside a
running container (`supervisor.py --help` fell through into daemon mode),
which kills the odoo processes of the one already running.
"""

from __future__ import annotations

import socket
import sys
import tempfile
from pathlib import Path

import pytest

# supervisor.py lives in odoo/bin/ — only on PYTHONPATH inside the container.
REPO_ROOT = Path(__file__).resolve().parents[4]
ODOO_BIN = REPO_ROOT / "odoo" / "bin"
sys.path.insert(0, str(ODOO_BIN))

import supervisor as sup  # noqa: E402


def _role(name):
    role = sup.Role.__new__(sup.Role)
    role.name = name
    role.spec = sup.ROLES[name]
    role.proc = None
    role.want_running = True
    role.backoff = sup.BACKOFF_INITIAL
    role.last_spawn = 0.0
    role.last_rc = None
    role.respawn_requested = False
    role._log_thread = None
    role._lock = None
    return role


class TestGateAllowsRunning:
    def test_env_gated_role_off_is_not_allowed(self, monkeypatch):
        monkeypatch.setenv("RUN_ODOO_CRONJOBS", "0")
        assert _role("cronjobs").gate_allows_running() is False

    def test_env_gated_role_on_is_allowed(self, monkeypatch):
        monkeypatch.setenv("RUN_ODOO_CRONJOBS", "1")
        assert _role("cronjobs").gate_allows_running() is True

    def test_probe_gated_role_is_asked_again(self, monkeypatch):
        answers = iter([True, False])
        monkeypatch.setitem(
            sup._PROBES, "queue_job_installed", lambda: next(answers)
        )
        role = _role("queuejobs")
        assert role.gate_allows_running() is True
        assert role.gate_allows_running() is False


class TestCleanEarlyExit:
    """restart: on-failure — a clean, immediate exit is not a crash."""

    def test_rc0_right_away_is_clean_early_exit(self):
        role = _role("cronjobs")
        role.last_rc = 0
        assert sup._is_clean_early_exit(role, 0.3) is True

    def test_rc0_after_long_uptime_is_a_crash_to_recover_from(self):
        role = _role("cronjobs")
        role.last_rc = 0
        uptime = sup.CLEAN_EXIT_MIN_UPTIME + 1
        assert sup._is_clean_early_exit(role, uptime) is False

    def test_failure_exit_is_respawned(self):
        role = _role("cronjobs")
        role.last_rc = 1
        assert sup._is_clean_early_exit(role, 0.3) is False


class TestControlSocketStart:
    def test_start_of_gated_off_role_is_a_noop_success(self, monkeypatch):
        """The host CLI must not read this as "supervisor cannot do it" —
        it would then fall back to compose-level ops on the legacy service
        names (odoo_cronjobs, …) which no longer exist."""
        monkeypatch.setenv("RUN_ODOO_CRONJOBS", "0")
        supervisor = sup.Supervisor.__new__(sup.Supervisor)
        role = _role("cronjobs")
        role.want_running = False

        def _boom():
            raise AssertionError("must not spawn a gated-off role")

        role.spawn = _boom
        supervisor.roles = {"cronjobs": role}

        resp = supervisor._handle_cmd("start cronjobs")
        assert resp["ok"] is True
        assert resp.get("noop") is True
        assert role.want_running is False


class TestMain:
    def test_unknown_argument_does_not_start_a_daemon(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["supervisor.py", "--help"])

        def _boom(*args, **kwargs):
            raise AssertionError(
                "unknown args must not fall through into daemon mode"
            )

        monkeypatch.setattr(sup, "Supervisor", _boom)
        with pytest.raises(SystemExit) as ex:
            sup.main()
        assert ex.value.code == 2

    def test_daemon_refuses_when_socket_answers(self, monkeypatch):
        # Not tmp_path: on macOS its path blows the 104-char AF_UNIX limit.
        sock_path = Path(tempfile.mkdtemp(prefix="sup")) / "s.sock"
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(sock_path))
        # Backlog > 1: nothing accepts here, and a full queue would make the
        # second connect() fail — which is what we are testing against.
        srv.listen(64)
        monkeypatch.setattr(sup, "SOCKET_PATH", str(sock_path))
        try:
            assert sup._daemon_already_running() is True
            monkeypatch.setattr(sys, "argv", ["supervisor.py"])

            def _boom(*args, **kwargs):
                raise AssertionError(
                    "a second daemon kills the running one's odoo processes"
                )

            monkeypatch.setattr(sup, "Supervisor", _boom)
            with pytest.raises(SystemExit) as ex:
                sup.main()
            assert ex.value.code == 3
        finally:
            srv.close()

    def test_stale_socket_file_is_not_a_running_daemon(self, monkeypatch):
        stale = Path(tempfile.mkdtemp(prefix="sup")) / "s.sock"
        stale.touch()
        monkeypatch.setattr(sup, "SOCKET_PATH", str(stale))
        assert sup._daemon_already_running() is False

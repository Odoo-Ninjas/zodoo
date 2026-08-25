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


class TestGateState:
    """A probe that cannot be evaluated (DB unreachable while postgres
    restarts) is not the same answer as "this role must not run"."""

    def test_env_off_is_a_definitive_off(self, monkeypatch):
        monkeypatch.setenv("RUN_ODOO_CRONJOBS", "0")
        assert sup._role_gate_state(sup.ROLES["cronjobs"]) == sup.GATE_OFF

    def test_probe_raising_is_unknown(self, monkeypatch):
        def _boom():
            raise RuntimeError("db down")

        monkeypatch.setitem(sup._PROBES, "queue_job_installed", _boom)
        assert sup._role_gate_state(sup.ROLES["queuejobs"]) == sup.GATE_UNKNOWN

    def test_unknown_still_keeps_the_role_off(self, monkeypatch):
        def _boom():
            raise RuntimeError("db down")

        monkeypatch.setitem(sup._PROBES, "queue_job_installed", _boom)
        assert _role("queuejobs").gate_allows_running() is False


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

    def test_start_with_unevaluable_gate_stays_an_error(self, monkeypatch):
        """Otherwise a queuejobs role silently never runs after an update:
        the probe hits a DB that is still coming back up, and a no-op
        success would hide that from the caller."""

        def _boom():
            raise RuntimeError("db down")

        monkeypatch.setitem(sup._PROBES, "queue_job_installed", _boom)
        supervisor = sup.Supervisor.__new__(sup.Supervisor)
        supervisor.roles = {"queuejobs": _role("queuejobs")}

        resp = supervisor._handle_cmd("start queuejobs")
        assert resp["ok"] is False
        assert "could not be evaluated" in resp["error"]


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

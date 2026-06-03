"""Behavioral tests for cronjobs/bin/restart_unhealthy_containers.sh.

The script is exercised end-to-end with a stubbed ``docker`` binary on
PATH — no Docker daemon needed, so these run with the fast unit tests.
The stub serves container state from a whitespace-separated table and
records ``docker restart`` calls to a log file.

Table line format:
  name status health restart_count started_at exit_code oom_killed finished_at
"""

from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from zodoo.tests.conftest import _resolve_images_dir

_IMAGES = _resolve_images_dir()
_SCRIPT = (
    _IMAGES / "cronjobs" / "bin" / "restart_unhealthy_containers.sh"
    if _IMAGES
    else None
)

pytestmark = pytest.mark.skipif(
    _SCRIPT is None or not _SCRIPT.exists() or shutil.which("flock") is None,
    reason="images repo or flock(1) not available",
)

_STUB_DOCKER = r"""#!/bin/bash
case "$1" in
  ps)
    echo "$@" >> "$TEST_PS_ARGS_LOG"
    awk '{print $1}' "$TEST_CONTAINERS"
    ;;
  inspect)
    awk -v n="$2" '$1==n {print $2, $3, $4, $5, $6, $7, $8}' "$TEST_CONTAINERS"
    ;;
  restart)
    if [ -n "$TEST_FAIL_RESTART" ] && [ "$2" = "$TEST_FAIL_RESTART" ]; then
      exit 1
    fi
    echo "$2" >> "$TEST_RESTART_LOG"
    ;;
esac
"""


def _ts(seconds_ago):
    dt = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000000000Z")


class Harness:
    def __init__(self, tmp_path: Path):
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        stub = self.bin / "docker"
        stub.write_text(_STUB_DOCKER)
        stub.chmod(0o755)
        self.state = tmp_path / "state"
        self.containers = tmp_path / "containers.txt"
        self.restart_log = tmp_path / "restarts.log"
        self.ps_args_log = tmp_path / "ps_args.log"

    def run(self, table, fail_restart=None, env=None):
        self.containers.write_text(
            "\n".join(table) + "\n" if table else ""
        )
        # fresh per run — assertions must reflect the last tick only
        self.restart_log.unlink(missing_ok=True)
        self.ps_args_log.unlink(missing_ok=True)
        full_env = dict(os.environ)
        full_env.update(
            PATH=f"{self.bin}:{os.environ['PATH']}",
            PROJECT_NAME="myproj",
            DEVMODE="0",
            FORCE_RESTART_UNHEALTHY_CONTAINERS="",
            RESTART_UNHEALTHY_STATE_DIR=str(self.state),
            TEST_CONTAINERS=str(self.containers),
            TEST_RESTART_LOG=str(self.restart_log),
            TEST_PS_ARGS_LOG=str(self.ps_args_log),
            TEST_FAIL_RESTART=fail_restart or "",
            # pin the thresholds: a developer's project settings may export
            # these and would otherwise change the test arithmetic
            RESTARTING_STUCK_SECS="300",
            STARTING_STUCK_SECS="300",
            EXITED_STUCK_SECS="300",
            LC_ALL="C",
        )
        full_env.update(env or {})
        return subprocess.run(
            ["bash", str(_SCRIPT)],
            capture_output=True,
            text=True,
            env=full_env,
            timeout=30,
        )

    def restarts(self):
        if not self.restart_log.exists():
            return []
        return self.restart_log.read_text().split()

    def state_file(self, container):
        return self.state / container


@pytest.fixture
def harness(tmp_path):
    return Harness(tmp_path)


def test_all_healthy_is_a_noop(harness):
    res = harness.run(
        [f"myproj_odoo running healthy 0 {_ts(400)} 0 false {_ts(400)}"]
    )
    assert res.returncode == 0
    assert harness.restarts() == []
    assert "look fine" in res.stdout


def test_unhealthy_running_container_is_restarted(harness):
    res = harness.run(
        [f"myproj_proxy running unhealthy 0 {_ts(400)} 0 false {_ts(400)}"]
    )
    assert harness.restarts() == ["myproj_proxy"]
    assert "unhealthy" in res.stdout


def test_stuck_in_starting_only_after_threshold(harness):
    harness.run(
        [f"myproj_redis running starting 0 {_ts(100)} 0 false {_ts(100)}"]
    )
    assert harness.restarts() == []
    res = harness.run(
        [f"myproj_redis running starting 0 {_ts(400)} 0 false {_ts(400)}"]
    )
    assert harness.restarts() == ["myproj_redis"]
    assert "stuck-in-starting" in res.stdout


def test_exited_crash_revived_after_threshold(harness):
    # recent crash → hands off (ops may be working on it)
    harness.run([f"myproj_odoo exited none 0 {_ts(100)} 1 false {_ts(100)}"])
    assert harness.restarts() == []
    # old crash → revived
    res = harness.run(
        [f"myproj_odoo exited none 0 {_ts(400)} 1 false {_ts(400)}"]
    )
    assert harness.restarts() == ["myproj_odoo"]
    assert "crashed (exit 1" in res.stdout


@pytest.mark.parametrize("exit_code", ["0", "130", "143"])
def test_exited_clean_stop_is_left_alone(harness, exit_code):
    """'odoo kill' / docker stop exit codes must never be revived."""
    harness.run(
        [f"myproj_odoo exited none 0 {_ts(400)} {exit_code} false {_ts(400)}"]
    )
    assert harness.restarts() == []


def test_exited_sigkill_only_revived_when_oom(harness):
    # manual `docker kill` (137 without OOMKilled) → hands off
    harness.run(
        [f"myproj_odoo exited none 0 {_ts(400)} 137 false {_ts(400)}"]
    )
    assert harness.restarts() == []
    # kernel OOM kill → revive
    res = harness.run(
        [f"myproj_odoo exited none 0 {_ts(400)} 137 true {_ts(400)}"]
    )
    assert harness.restarts() == ["myproj_odoo"]
    assert "OOM-killed" in res.stdout


def test_crashloop_episode_tracking(harness):
    row = f"myproj_odoo restarting none {{count}} {_ts(400)} 1 false {_ts(30)}"
    # first sighting: episode starts, no restart yet
    harness.run([row.format(count=3)])
    assert harness.restarts() == []
    state = harness.state_file("myproj_odoo")
    assert state.exists()
    # age the episode beyond the threshold, count keeps growing → fires
    first_epoch = int(time.time()) - 400
    state.write_text(f"{first_epoch} 3\n")
    res = harness.run([row.format(count=9)])
    assert harness.restarts() == ["myproj_odoo"]
    assert "crash-loop" in res.stdout
    # episode reset after the restart → next escalation needs a new episode
    assert not state.exists()


def test_stable_restart_count_ends_episode(harness):
    """A non-zero but stable RestartCount (old blip) never escalates;
    the episode ends after TWO consecutive stable ticks."""
    row = f"myproj_pg running healthy 5 {_ts(4000)} 0 false {_ts(4000)}"
    harness.run([row])
    assert harness.state_file("myproj_pg").exists()
    harness.run([row])  # first stable tick → episode kept (sampling luck)
    assert harness.state_file("myproj_pg").exists()
    harness.run([row])  # second stable tick → recovered
    assert not harness.state_file("myproj_pg").exists()
    assert harness.restarts() == []


def test_one_quiet_tick_does_not_reset_episode(harness):
    """A mature crash cycle (~62s: 60s backoff cap + runtime) vs the 60s
    tick means the count occasionally doesn't grow between two samples —
    one quiet tick must not reset the episode clock."""
    harness.state.mkdir()
    first_epoch = int(time.time()) - 400
    harness.state_file("myproj_odoo").write_text(f"{first_epoch} 3 0\n")
    row = f"myproj_odoo restarting none {{count}} {_ts(400)} 1 false {_ts(30)}"
    harness.run([row.format(count=3)])  # quiet tick: count unchanged
    assert harness.restarts() == []
    assert harness.state_file("myproj_odoo").exists()
    res = harness.run([row.format(count=9)])  # growth again → must fire
    assert harness.restarts() == ["myproj_odoo"]
    assert "crash-loop" in res.stdout


def test_corrupt_state_file_restarts_episode(harness):
    harness.state.mkdir()
    harness.state_file("myproj_odoo").write_text("garbage stuff\n")
    harness.run(
        [f"myproj_odoo restarting none 5 {_ts(400)} 1 false {_ts(30)}"]
    )
    assert harness.restarts() == []
    epoch, count, streak = harness.state_file("myproj_odoo").read_text().split()
    assert epoch.isdigit() and count == "5" and streak == "0"


def test_concurrent_instance_is_skipped(harness):
    harness.state.mkdir()
    lock = open(harness.state / ".lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        res = harness.run(
            [f"myproj_proxy running unhealthy 0 {_ts(400)} 0 false {_ts(400)}"]
        )
        assert res.returncode == 0
        assert harness.restarts() == []
        assert "Previous run still active" in res.stdout
    finally:
        lock.close()


def test_failed_restart_is_reported(harness):
    res = harness.run(
        [f"myproj_proxy running unhealthy 0 {_ts(400)} 0 false {_ts(400)}"],
        fail_restart="myproj_proxy",
    )
    assert harness.restarts() == []
    assert "FAILED" in res.stdout
    assert "1 failure" in res.stdout
    assert res.returncode != 0


def test_stale_state_cleaned_but_lock_survives(harness):
    harness.state.mkdir()
    harness.state_file("myproj_gone").write_text("123 4\n")
    harness.run(
        [f"myproj_pg running healthy 0 {_ts(400)} 0 false {_ts(400)}"]
    )
    assert not harness.state_file("myproj_gone").exists()
    assert (harness.state / ".lock").exists()


def test_ps_scopes_by_compose_project_label(harness):
    """Containers must be scoped by the compose project label (exact
    equality) — name-based matching is ambiguous: a prefix filter for
    project 'myproj' would also manage 'myproj_staging_odoo' of project
    'myproj_staging' on the same host."""
    harness.run(
        [f"myproj_odoo running healthy 0 {_ts(400)} 0 false {_ts(400)}"]
    )
    ps_args = harness.ps_args_log.read_text()
    assert "label=com.docker.compose.project=myproj" in ps_args


def test_multiple_containers_restarted_in_one_tick(harness):
    res = harness.run(
        [
            f"myproj_proxy running unhealthy 0 {_ts(400)} 0 false {_ts(400)}",
            f"myproj_pg running healthy 0 {_ts(400)} 0 false {_ts(400)}",
            f"myproj_odoo exited none 0 {_ts(400)} 1 false {_ts(400)}",
        ]
    )
    assert harness.restarts() == ["myproj_proxy", "myproj_odoo"]
    assert res.stdout.count("🔄 Restarting") == 2


def test_exited_that_never_ran_is_left_alone(harness):
    """FinishedAt=0001-01-01 (container never ran) must not fire the
    exited-crash branch despite a non-clean exit code."""
    harness.run(
        [
            "myproj_odoo exited none 0 0001-01-01T00:00:00Z 1 false "
            "0001-01-01T00:00:00Z"
        ]
    )
    assert harness.restarts() == []


@pytest.mark.skipif(
    os.geteuid() == 0, reason="root bypasses directory permissions"
)
def test_unwritable_state_dir_falls_back_and_still_works(harness, tmp_path):
    ro_dir = tmp_path / "ro_state"
    ro_dir.mkdir()
    ro_dir.chmod(0o555)
    try:
        res = harness.run(
            [f"myproj_proxy running unhealthy 0 {_ts(400)} 0 false {_ts(400)}"],
            env={"RESTART_UNHEALTHY_STATE_DIR": str(ro_dir)},
        )
        assert "not writable" in res.stdout
        assert harness.restarts() == ["myproj_proxy"]
    finally:
        ro_dir.chmod(0o755)


def test_devmode_skips_everything(harness):
    res = harness.run(
        [f"myproj_proxy running unhealthy 0 {_ts(400)} 0 false {_ts(400)}"],
        env={"DEVMODE": "1"},
    )
    assert harness.restarts() == []
    assert "Skipping" in res.stdout

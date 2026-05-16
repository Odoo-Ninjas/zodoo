"""Tests for the unified three-tier privilege escalation helper.

`run_root_cmd` in zodoo.tools wraps a command in three tiers:
  1. Try direct (works if we're root, or the op happens to work for us).
  2. On Linux with real Docker: privileged host-namespace helper container.
  3. Fall back to sudo with a one-time sudoers hint.

These tests stub out subprocess.run and the tier-availability probes so
that the dispatch logic itself is exercised, without touching real
docker/sudo.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from zodoo import tools as mod


def _ok_proc():
    return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")


def test_run_root_cmd_tier1_succeeds(monkeypatch):
    """Tier 1 (direct) success → no escalation, no sudo, no docker."""
    calls = []

    def fake_run(cmd, **kw):
        calls.append(cmd)
        return _ok_proc()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    # Pretend docker is available — must NOT be reached.
    monkeypatch.setattr(mod, "_docker_root_helper_available", lambda: True)
    monkeypatch.setattr(
        mod, "_docker_root_helper_base", lambda: ["docker", "run"]
    )

    mod.run_root_cmd(["chown", "1234", "/tmp/x"])

    assert calls == [["chown", "1234", "/tmp/x"]]


def test_run_root_cmd_escalates_to_docker_then_sudo(monkeypatch):
    """Tier 1 fails → Tier 2 (docker) tried. If Tier 2 fails → Tier 3 sudo."""
    calls = []

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        # Fail on direct + docker tiers; succeed only on sudo (3rd attempt).
        if len(calls) < 3:
            raise subprocess.CalledProcessError(returncode=1, cmd=cmd)
        return _ok_proc()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(
        mod, "platform", SimpleNamespace(system=lambda: "Linux")
    )
    monkeypatch.setattr(mod.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(mod, "_docker_root_helper_available", lambda: True)
    monkeypatch.setattr(
        mod,
        "_docker_root_helper_base",
        lambda: ["docker", "run", "--privileged"],
    )

    mod.run_root_cmd(["btrfs", "subvolume", "create", "/x"])

    # Three calls: direct, docker-wrapped, sudo-wrapped
    assert len(calls) == 3
    assert calls[0] == ["btrfs", "subvolume", "create", "/x"]
    assert calls[1][:3] == ["docker", "run", "--privileged"]
    assert calls[1][-4:] == ["btrfs", "subvolume", "create", "/x"]
    assert calls[2][0] == "sudo"
    assert calls[2][-4:] == ["btrfs", "subvolume", "create", "/x"]


def test_run_root_cmd_skips_docker_on_non_linux(monkeypatch):
    """macOS: no docker tier, only direct → sudo fallback."""
    calls = []

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        if len(calls) == 1:
            raise subprocess.CalledProcessError(returncode=1, cmd=cmd)
        return _ok_proc()

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(
        mod, "platform", SimpleNamespace(system=lambda: "Darwin")
    )
    # Docker probe must not even be called on non-Linux, but stub it
    # defensively in case the impl ever changes.
    monkeypatch.setattr(mod, "_docker_root_helper_available", lambda: False)

    mod.run_root_cmd(["chown", "501", "/tmp/x"])

    assert len(calls) == 2
    assert calls[0] == ["chown", "501", "/tmp/x"]
    assert calls[1][0] == "sudo"


def test_run_root_cmd_root_user_no_wrap(monkeypatch):
    """When already root, only Tier 1 is registered — no sudo fallback."""
    calls = []

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        # Even though it fails, we don't escalate (we're already root).
        raise subprocess.CalledProcessError(returncode=2, cmd=cmd)

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    monkeypatch.setattr(
        mod, "platform", SimpleNamespace(system=lambda: "Linux")
    )
    monkeypatch.setattr(mod.os, "geteuid", lambda: 0)

    with pytest.raises(subprocess.CalledProcessError):
        mod.run_root_cmd(["chown", "0", "/tmp/x"])

    assert calls == [["chown", "0", "/tmp/x"]]


def test_run_root_cmd_capture_returns_stdout(monkeypatch):
    def fake_run(cmd, **kw):
        return SimpleNamespace(returncode=0, stdout=b"hello\n", stderr=b"")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    # Without this, on Linux CI the tier-2 probe (_is_real_docker) calls the
    # patched subprocess.run, which returns bytes — the str/bytes mix inside
    # _is_real_docker would then explode before tier-1 even runs.
    monkeypatch.setattr(mod, "_docker_root_helper_available", lambda: False)

    out = mod.run_root_cmd(["echo", "hello"], capture=True)
    assert out == b"hello\n"


def test_run_root_cmd_propagates_last_exception(monkeypatch):
    """All tiers fail → the last CalledProcessError surfaces."""
    monkeypatch.setattr(
        mod.subprocess,
        "run",
        lambda *a, **kw: (_ for _ in ()).throw(
            subprocess.CalledProcessError(returncode=42, cmd=a[0])
        ),
    )
    monkeypatch.setattr(
        mod, "platform", SimpleNamespace(system=lambda: "Linux")
    )
    monkeypatch.setattr(mod.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(mod, "_docker_root_helper_available", lambda: False)

    with pytest.raises(subprocess.CalledProcessError) as excinfo:
        mod.run_root_cmd(["false"])
    assert excinfo.value.returncode == 42

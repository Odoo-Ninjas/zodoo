"""Tests for the docker cli plugin prechecks around `odoo build`.

A missing buildx plugin fails the build in a way that points at the wrong
thing: the base image is never built, so the *next* step reports
"pull access denied ... odoo_base_..." and people go looking at registry
credentials. These tests pin the detection and the wording, using the real
output captured on a fresh Ubuntu 26.04 (docker 29.1.3, no buildx).

Pure functions - no docker needed.
"""

from __future__ import annotations

import subprocess

import pytest

from ..lib_control_with_docker import (
    _BUILDX_MISSING_PATTERN,
    _check_docker_build_tooling,
    _docker_plugin_hint,
    _is_buildx_available,
    _is_docker_plugin_available,
)

# verbatim from an `odoo build` on Ubuntu 26.04 with docker.io but no buildx
REAL_BUILDX_FAILURE = """\
#1 [internal] load build definition from Dockerfile
ERROR: BuildKit is enabled but the buildx component is missing or broken.
       Install the buildx component to build images with BuildKit:
       https://docs.docker.com/go/buildx/
"""

# the misleading follow-up error from the same run
REAL_FOLLOWUP_FAILURE = """\
#2 ERROR: pull access denied, repository does not exist or may require \
authorization: server message: insufficient_scope: authorization failed
failed to solve: odoo_base_17_38b20f63d24f_amd64: failed to resolve source \
metadata for docker.io/library/odoo_base_17_38b20f63d24f_amd64:latest
"""


def test_pattern_matches_real_buildx_failure():
    assert _BUILDX_MISSING_PATTERN.search(REAL_BUILDX_FAILURE)


def test_pattern_ignores_the_misleading_followup():
    """The follow-up must not trigger the hint on its own - it also shows up
    for genuine registry problems."""
    assert not _BUILDX_MISSING_PATTERN.search(REAL_FOLLOWUP_FAILURE)


@pytest.mark.parametrize(
    "plugin,expected",
    [
        ("buildx", ("docker-buildx", "docker-buildx-plugin")),
        ("compose", ("docker-compose-v2", "docker-compose-plugin")),
    ],
)
def test_hint_names_both_package_flavours(plugin, expected):
    """Distro docker.io and docker's own repo use different package names and
    we run both."""
    hint = _docker_plugin_hint(plugin)
    assert f"docker {plugin}" in hint
    for package in expected:
        assert f"apt install {package}" in hint


def test_plugin_missing_when_docker_absent(monkeypatch):
    def _no_docker(*args, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(subprocess, "check_output", _no_docker)
    assert _is_docker_plugin_available("buildx") is False
    assert _is_buildx_available() is False


def test_plugin_missing_when_docker_rejects_it(monkeypatch):
    def _unknown_command(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    monkeypatch.setattr(subprocess, "check_output", _unknown_command)
    assert _is_docker_plugin_available("compose") is False


def test_plugin_present(monkeypatch):
    monkeypatch.setattr(
        subprocess, "check_output", lambda *a, **kw: b"buildx v0.30.1"
    )
    assert _is_docker_plugin_available("buildx") is True
    assert _is_buildx_available() is True


def _fake_plugins(monkeypatch, available):
    import zodoo.lib_control_with_docker as lcd

    monkeypatch.setattr(
        lcd,
        "_is_docker_plugin_available",
        lambda plugin: plugin in available,
    )
    return lcd


def test_missing_compose_aborts(monkeypatch):
    """Nothing works without compose, so stop right away."""
    _fake_plugins(monkeypatch, {"buildx"})
    with pytest.raises(SystemExit):
        _check_docker_build_tooling()


def test_missing_buildx_warns_but_continues(monkeypatch, capsys):
    """The fallback may still work on an older docker - warn, do not abort."""
    _fake_plugins(monkeypatch, {"compose"})
    _check_docker_build_tooling()
    out = capsys.readouterr().out
    assert "apt install docker-buildx" in out


def test_everything_present_is_quiet(monkeypatch, capsys):
    _fake_plugins(monkeypatch, {"compose", "buildx"})
    _check_docker_build_tooling()
    assert capsys.readouterr().out == ""

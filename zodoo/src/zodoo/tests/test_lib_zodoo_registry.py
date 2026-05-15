"""Tests for zodoo.lib_zodoo_registry — focuses on the interactive
``_get_registry_config`` flow that has historically broken CI bake
runs by aborting on a non-tty stdin.
"""

from __future__ import annotations

from types import SimpleNamespace

from zodoo import lib_zodoo_registry as mod


class _FakeConfig(SimpleNamespace):
    pass


def test_get_registry_config_returns_none_in_non_interactive_shell(
    monkeypatch,
):
    """CI / cron / scripted invocations have no tty — must NOT prompt
    (and must NOT call sys.exit) but silently fall through, leaving
    the build to continue without registry caching."""
    monkeypatch.setattr(mod, "_read_user_setting", lambda config, key: None)

    # Force non-tty.
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False)

    # If the code reached click.confirm we'd see an Abort -> SystemExit.
    def _boom(*a, **kw):  # pragma: no cover - guard
        raise AssertionError(
            "click.confirm must not be called when stdin is not a tty"
        )

    monkeypatch.setattr(mod.click, "confirm", _boom)
    monkeypatch.setattr(mod.click, "prompt", _boom)

    assert mod._get_registry_config(_FakeConfig()) is None


def test_get_registry_config_respects_suggested_zero(monkeypatch):
    """User previously declined: must not prompt, must return None."""
    monkeypatch.setattr(mod, "_read_user_setting", lambda config, key: "0")

    def _boom(*a, **kw):  # pragma: no cover - guard
        raise AssertionError("must not prompt when SUGGESTED=0")

    monkeypatch.setattr(mod.click, "confirm", _boom)
    assert mod._get_registry_config(_FakeConfig()) is None

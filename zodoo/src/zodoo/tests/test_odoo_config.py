"""Tests for zodoo.odoo_config helpers — primarily the queue_job
install probe that gates the supervisor's queuejobs role and the
server-wide-modules list.
"""

from __future__ import annotations

from contextlib import contextmanager

import time

import psycopg2
import pytest

from zodoo import odoo_config as mod


class _FakeCursor:
    """Minimal cursor stand-in for monkeypatching get_conn_autoclose."""

    def __init__(self, results):
        self._results = list(results)
        self._last = None
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append(sql)
        self._last = self._results.pop(0) if self._results else None

    def fetchone(self):
        return self._last


def _patch_get_conn(monkeypatch, results):
    """Replace get_conn_autoclose with a context manager yielding our fake."""

    cur = _FakeCursor(results)

    @contextmanager
    def fake_autoclose(*a, **kw):
        yield cur

    monkeypatch.setattr(mod, "get_conn_autoclose", fake_autoclose)
    return cur


def test_queue_job_installed_returns_true_when_module_row_exists(monkeypatch):
    cur = _patch_get_conn(
        monkeypatch,
        results=[(1,), (1,)],  # ir_module_module exists, queue_job row exists
    )
    assert mod._queue_job_installed() is True
    # both queries fired in order
    assert "information_schema.tables" in cur.executed[0]
    assert "queue_job" in cur.executed[1]


def test_queue_job_installed_returns_false_when_table_missing(monkeypatch):
    cur = _patch_get_conn(monkeypatch, results=[None])
    assert mod._queue_job_installed() is False
    assert len(cur.executed) == 1  # short-circuits before the second query


def test_queue_job_installed_returns_false_when_module_not_installed(
    monkeypatch,
):
    _patch_get_conn(monkeypatch, results=[(1,), None])
    assert mod._queue_job_installed() is False


def test_queue_job_installed_fail_soft_on_postgres_unreachable(monkeypatch):
    @contextmanager
    def fake_autoclose(*a, **kw):
        raise psycopg2.OperationalError("could not connect")
        yield  # noqa: unreachable, kept so it's a generator

    monkeypatch.setattr(mod, "get_conn_autoclose", fake_autoclose)
    assert mod._queue_job_installed() is False


def test_queue_job_installed_fail_soft_on_undefined_table(monkeypatch):
    # Importing `psycopg2.errors` is not done by default in some
    # psycopg2 builds, so reference the SQLSTATE-mapped exception via
    # the runtime-accessible path. We use the generic `psycopg2.Error`
    # to mimic any such DB-level failure here.
    @contextmanager
    def fake_autoclose(*a, **kw):
        raise psycopg2.Error("relation ir_module_module does not exist")
        yield

    monkeypatch.setattr(mod, "get_conn_autoclose", fake_autoclose)
    assert mod._queue_job_installed() is False


def test_queue_job_installed_fail_soft_on_unexpected_error(monkeypatch):
    @contextmanager
    def fake_autoclose(*a, **kw):
        raise RuntimeError("DNS down or whatever")
        yield

    monkeypatch.setattr(mod, "get_conn_autoclose", fake_autoclose)
    # The probe runs at every container start; a hard failure would
    # block the container — fail-soft to False instead.
    assert mod._queue_job_installed() is False


# --------------------------------------------------------------------------
# MANIFEST read robustness
#
# A MANIFEST read can land in the window where another process (rsync from a
# shared CI cache, git checkout, gimera) is rewriting the file, so it reads
# back empty. That used to abort the whole command after ~1s with the
# unhelpful message "Could not parse " and then cascade into unrelated
# follow-up errors ("somehow dbname is missing" during restore).
# --------------------------------------------------------------------------


def _manifest(path):
    """A MANIFEST_CLASS bound to `path` without running __init__.

    __init__ calls _apply_defaults(), which needs a real customs dir — we only
    want to exercise the read path here.
    """
    inst = object.__new__(mod.MANIFEST_CLASS)
    inst.path = path
    return inst


class _ScriptedPath:
    """Path stand-in whose first `empty_reads` reads return an empty file."""

    def __init__(self, content, empty_reads=0):
        self.content = content
        self.empty_reads = empty_reads
        self.reads = 0

    def read_text(self):
        self.reads += 1
        if self.reads <= self.empty_reads:
            return ""
        return self.content

    def stat(self):
        raise OSError("not a real file")


def _capture_abort(monkeypatch):
    seen = {}

    def fake_abort(msg, nr=1):
        seen["msg"] = msg
        raise SystemExit(nr)

    monkeypatch.setattr(mod, "abort", fake_abort)
    return seen


def test_manifest_read_timeout_default_env_and_garbage(monkeypatch):
    monkeypatch.delenv("ZODOO_MANIFEST_READ_TIMEOUT", raising=False)
    assert mod._manifest_read_timeout() == mod.MANIFEST_READ_TIMEOUT_DEFAULT
    monkeypatch.setenv("ZODOO_MANIFEST_READ_TIMEOUT", "3.5")
    assert mod._manifest_read_timeout() == 3.5
    # A typo must not make every config read explode.
    monkeypatch.setenv("ZODOO_MANIFEST_READ_TIMEOUT", "soon")
    assert mod._manifest_read_timeout() == mod.MANIFEST_READ_TIMEOUT_DEFAULT


def test_absent_manifest_returns_empty_without_burning_the_budget(
    tmp_path, monkeypatch
):
    # A project without MANIFEST is legitimate: there is nothing to wait for,
    # so this must be fast even with a long timeout configured.
    monkeypatch.setenv("ZODOO_MANIFEST_READ_TIMEOUT", "30")
    inst = _manifest(tmp_path / "MANIFEST")
    started = time.monotonic()
    assert inst._get_data() == {}
    assert time.monotonic() - started < 1.0


def test_empty_manifest_is_retried_until_content_appears(monkeypatch):
    monkeypatch.setenv("ZODOO_MANIFEST_READ_TIMEOUT", "10")
    path = _ScriptedPath("{'addons_paths': ['addons'], 'install': []}", 3)
    data = _manifest(path)._get_data()
    assert data["addons_paths"] == ["addons"]
    assert path.reads == 4  # 3 truncated reads were survived, not fatal


def test_unreadable_manifest_aborts_with_diagnostics(tmp_path, monkeypatch):
    monkeypatch.setenv("ZODOO_MANIFEST_READ_TIMEOUT", "0")
    seen = _capture_abort(monkeypatch)
    path = tmp_path / "MANIFEST"
    path.write_text("")  # exists, but empty for good
    with pytest.raises(SystemExit):
        _manifest(path)._get_data()
    msg = seen["msg"]
    # The old message was just "Could not parse " — the useful parts were
    # missing, which is what made this unreadable in CI logs.
    assert "Could not parse MANIFEST" in msg
    assert str(path) in msg
    assert "0 bytes" in msg
    assert "ZODOO_MANIFEST_READ_TIMEOUT" in msg


def test_manifest_without_addons_paths_is_not_delayed_by_the_full_timeout(
    monkeypatch,
):
    # _get_data() runs on every __getitem__, so a MANIFEST that simply has no
    # addons_paths must only pay the short grace period, never the long
    # unreadable-budget.
    monkeypatch.setenv("ZODOO_MANIFEST_READ_TIMEOUT", "30")
    started = time.monotonic()
    data = _manifest(_ScriptedPath("{'modules': []}"))._get_data()
    elapsed = time.monotonic() - started
    assert data == {"modules": []}
    assert elapsed < 5.0


def test_addons_paths_system_still_gets_prepended(monkeypatch):
    monkeypatch.setenv("ZODOO_MANIFEST_READ_TIMEOUT", "5")
    path = _ScriptedPath(
        "{'addons_paths': ['b'], 'addons_paths_system': ['a']}"
    )
    assert _manifest(path)._get_data()["addons_paths"] == ["a", "b"]

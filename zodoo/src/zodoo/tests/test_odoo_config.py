"""Tests for zodoo.odoo_config helpers — primarily the queue_job
install probe that gates the supervisor's queuejobs role and the
server-wide-modules list.
"""

from __future__ import annotations

from contextlib import contextmanager

import psycopg2

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

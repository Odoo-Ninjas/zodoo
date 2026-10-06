"""DEVMODE neutralization of the Outlook calendar sync (Odoo 19).

A restored production database still carries the users' Microsoft refresh
tokens and the app's client secrets. Without neutralization a dev copy keeps
writing into real Outlook calendars and Outlook sends the invitations.

The real ``odoo/config/19/turndb2dev.sql`` is fed through the line-by-line
executor with a recording fake for ``_execute_sql``, so no database is needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from zodoo import lib_turnintodev as mod

SQL_FILE = (
    Path(mod.__file__).parents[3] / "odoo" / "config" / "19" / "turndb2dev.sql"
)
ENV = {
    "TEST_MAIL_HOST": "mail",
    "TEST_MAIL_SMTP_PORT": "25",
    "TEST_MAIL_IMAP_PORT": "143",
}
execute_linebyline_sql = getattr(mod, "__execute_linebyline_sql")


def _run(monkeypatch, schema_present):
    executed = []

    def fake_execute_sql(conn, sql, fetchone=False, **kwargs):
        if sql.startswith("select count(*) from information_schema"):
            return (1 if schema_present else 0,)
        executed.append(sql)

    monkeypatch.setattr(mod, "_execute_sql", fake_execute_sql)
    execute_linebyline_sql(None, SQL_FILE.read_text(), ENV)
    return executed


def _matching(executed, needle):
    return [sql for sql in executed if needle in sql]


def test_refresh_tokens_are_removed(monkeypatch):
    executed = _run(monkeypatch, schema_present=True)
    (stmt,) = _matching(executed, "microsoft_calendar_rtoken")
    assert "microsoft_calendar_rtoken = null" in stmt
    assert "microsoft_calendar_token = null" in stmt


def test_sync_is_stopped_for_all_users(monkeypatch):
    executed = _run(monkeypatch, schema_present=True)
    (stmt,) = _matching(executed, "microsoft_synchronization_stopped")
    assert "update res_users_settings set" in stmt
    assert "microsoft_synchronization_stopped = true" in stmt
    assert " where " not in stmt.lower()


@pytest.mark.parametrize(
    "key",
    ["microsoft_calendar_client_secret", "microsoft_outlook_client_secret"],
)
def test_client_secrets_are_deleted(monkeypatch, key):
    executed = _run(monkeypatch, schema_present=True)
    assert any(
        sql.startswith("delete from ir_config_parameter") and key in sql
        for sql in executed
    )


def test_skipped_without_microsoft_modules(monkeypatch):
    """Databases without microsoft_account/microsoft_calendar must not fail."""
    executed = _run(monkeypatch, schema_present=False)
    assert not _matching(executed, "microsoft_calendar_rtoken")
    assert not _matching(executed, "microsoft_synchronization_stopped")
    # the parameter cleanup has no guard: ir_config_parameter always exists
    assert _matching(executed, "microsoft_calendar_client_secret")

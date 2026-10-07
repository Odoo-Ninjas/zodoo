"""DEVMODE: neutralized mail servers are recognizable by their name.

turn-into-dev points every ir.mail_server / fetchmail.server at the local
test mail container. The records kept their names ("Eingang", "Ausgang"), so
a customer looking at a dev copy took the real mail service for active.
Every version's ``turndb2dev.sql`` now prefixes the names with
"Test-Mailserver (" ... ")".

The real SQL files are fed through the line-by-line executor with a recording
fake for ``_execute_sql``, so no database is needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from zodoo import lib_turnintodev as mod

CONFIG_DIR = Path(mod.__file__).parents[3] / "odoo" / "config"
VERSIONS = sorted(p.parent.name for p in CONFIG_DIR.glob("*/turndb2dev.sql"))
TABLES = ["ir_mail_server", "fetchmail_server"]
PREFIX = "Test-Mailserver ("
ENV = {
    "TEST_MAIL_HOST": "mail",
    "TEST_MAIL_SMTP_PORT": "25",
    "TEST_MAIL_IMAP_PORT": "143",
    "DEFAULT_DEV_PASSWORD": "1",
}
execute_linebyline_sql = getattr(mod, "__execute_linebyline_sql")


def _run(monkeypatch, version, existing_tables):
    executed = []

    def fake_execute_sql(conn, sql, fetchone=False, **kwargs):
        if sql.startswith("select count(*) from information_schema.tables"):
            return (int(any(f"'{t}'" in sql for t in existing_tables)),)
        if sql.startswith("select count(*) from information_schema"):
            return (1,)
        executed.append(sql)

    monkeypatch.setattr(mod, "_execute_sql", fake_execute_sql)
    sql = (CONFIG_DIR / version / "turndb2dev.sql").read_text()
    execute_linebyline_sql(None, sql, ENV)
    return executed


def _renames(executed, table):
    return [
        sql
        for sql in executed
        if f"update {table} set name" in sql and PREFIX in sql
    ]


def test_all_versions_found():
    assert "9.0" in VERSIONS and "18" in VERSIONS and len(VERSIONS) >= 11


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("table", TABLES)
def test_mail_server_names_are_prefixed(monkeypatch, version, table):
    executed = _run(monkeypatch, version, existing_tables=TABLES)
    (stmt,) = _renames(executed, table)
    assert f"'{PREFIX}' || name || ')'" in stmt
    # running turn-into-dev twice must not stack the prefix
    assert f"not like '{PREFIX}%'" in stmt


@pytest.mark.parametrize("version", VERSIONS)
@pytest.mark.parametrize("table", TABLES)
def test_rename_is_skipped_without_table(monkeypatch, version, table):
    other = [t for t in TABLES if t != table]
    executed = _run(monkeypatch, version, existing_tables=other)
    assert not _renames(executed, table)


@pytest.mark.parametrize("version", [v for v in VERSIONS if float(v) >= 16])
@pytest.mark.parametrize("table", TABLES)
def test_translated_name_column_is_handled(monkeypatch, version, table):
    """From Odoo 16 on a translatable Char is a jsonb column; a module may
    make ``name`` translatable, so the rename must cope with both types."""
    executed = _run(monkeypatch, version, existing_tables=TABLES)
    (stmt,) = _renames(executed, table)
    assert "DO $$" in stmt
    assert f"table_name='{table}' and column_name='name'" in stmt
    assert "jsonb_each_text(name)" in stmt
    assert f"case when value like '{PREFIX}%' then value" in stmt


@pytest.mark.parametrize("version", [v for v in VERSIONS if float(v) >= 13])
def test_smtp_neutralization_does_not_depend_on_fetchmail(monkeypatch, version):
    """fetchmail is an optional module up to Odoo 16; without it the outgoing
    servers were left pointing at the real SMTP host."""
    executed = _run(monkeypatch, version, existing_tables=["ir_mail_server"])
    assert any(
        "update ir_mail_server set smtp_host='mail'" in sql
        for sql in executed
    )

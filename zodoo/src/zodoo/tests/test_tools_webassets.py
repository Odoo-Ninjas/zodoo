"""Tests for zodoo.tools.remove_webassets.

The command promises a cache purge ("assets are recreated when admin logs
in"), so what it deletes matters: bundle attachments yes, ir_asset never -
those come from the modules' manifests at install/update time and nothing
recreates them at runtime.
"""

from __future__ import annotations

import pytest

from zodoo import odoo_config
from zodoo import tools as mod


class FakeCursor:
    def __init__(self):
        self.queries = []

    def execute(self, query):
        self.queries.append(query)

    def close(self):
        pass


class FakePsycoConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def commit(self):
        pass

    def close(self):
        pass


class FakeDBConnection:
    def __init__(self, cursor):
        self._connection = FakePsycoConnection(cursor)

    def get_psyco_connection(self):
        return self._connection


@pytest.fixture
def executed(monkeypatch):
    def run(version):
        monkeypatch.setattr(
            odoo_config, "current_version", lambda *a, **kw: version
        )
        cursor = FakeCursor()
        mod.remove_webassets(FakeDBConnection(cursor))
        return cursor.queries

    return run


def test_never_deletes_ir_asset_on_17_plus(executed):
    queries = executed(18.0)

    assert not any("ir_asset" in query for query in queries)


def test_removes_bundle_attachments_by_url_on_17_plus(executed):
    queries = executed(18.0)

    assert any(
        "delete from ir_attachment where url like '/web/assets/%'" in query
        for query in queries
    )


def test_leaves_older_versions_untouched(executed):
    queries = executed(16.0)

    assert not any("ir_asset" in query for query in queries)
    assert not any("/web/assets/%" in query for query in queries)
    # the legacy name-based purge still runs
    assert any("name ilike '%assets_%'" in query for query in queries)


def test_preserves_custom_scss_attachments(executed):
    queries = executed(18.0)

    name_based = [q for q in queries if "name ilike '%assets_%'" in q]
    assert name_based
    assert all("url not like '/_custom/%'" in q for q in name_based)

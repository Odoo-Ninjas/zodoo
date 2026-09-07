"""Tests fuer das Warten auf postgres in `_execute_sql`.

Hintergrund: der @retry stand auf einer Funktion, die ihre Exception selbst
abgefangen hat. retrying sah damit nie einen Fehler und hat nie wiederholt -
der Schutz war wirkungslos. Am 07.09.2026 ist deshalb der bake-Test
gescheitert, weil postgres beim `db reset` gerade herunterfuhr.
"""

from __future__ import annotations

import pytest

from .. import tools
from ..tools import is_transient_pg_error

# wortgleich aus dem CI-Protokoll vom 07.09.2026
REAL_CI_ERROR = (
    'connection to server on socket "/home/runner/.odoo/run/baketest190/'
    'postgres.socket/.s.PGSQL.5432" failed: FATAL:  the database system is '
    "shutting down"
)


@pytest.mark.parametrize(
    "message",
    [
        REAL_CI_ERROR,
        "FATAL:  the database system is starting up",
        "FATAL:  the database system is in recovery mode",
        "the database system is not yet accepting connections",
        "could not connect to server: Connection refused",
        "server closed the connection unexpectedly",
        "FATAL:  terminating connection due to administrator command",
    ],
)
def test_transient_states_are_worth_waiting_for(message):
    assert is_transient_pg_error(Exception(message)) is True


@pytest.mark.parametrize(
    "message",
    [
        'FATAL:  password authentication failed for user "odoo"',
        'FATAL:  database "odoo" does not exist',
        'ERROR:  relation "res_partner" does not exist',
        "syntax error at or near",
        "",
    ],
)
def test_permanent_errors_are_not_retried(message):
    """Warten macht diese Fehler nie besser - sofort weiter, nicht 30s haengen."""
    assert is_transient_pg_error(Exception(message)) is False


def test_shutdown_is_waited_out(monkeypatch):
    """Der eigentliche Fall: zwei Fehlschlaege, dann bedient postgres wieder."""
    calls = []

    def fake_execute_sql(conn, sql, **kwargs):
        calls.append(sql)
        if len(calls) <= 2:
            raise Exception(REAL_CI_ERROR)

    monkeypatch.setattr(tools, "_execute_sql", fake_execute_sql)
    tools._try_connect(object())
    assert len(calls) == 3, "muss bis zum Erfolg wiederholen"


def test_permanent_error_is_not_hammered(monkeypatch):
    """Ein dauerhafter Fehler darf nicht 30 Sekunden lang wiederholt werden."""
    calls = []

    def fake_execute_sql(conn, sql, **kwargs):
        calls.append(sql)
        raise Exception('FATAL:  password authentication failed for user "x"')

    monkeypatch.setattr(tools, "_execute_sql", fake_execute_sql)
    tools._try_connect(object())
    assert len(calls) == 1, "genau ein Versuch, dann aufgeben"


def test_probe_uses_the_postgres_database(monkeypatch):
    """Geprobt wird auf 'postgres', nicht auf der Zieldatenbank - die kann
    beim reset gerade weg sein."""
    seen = {}

    class Conn:
        def clone(self, dbname=None):
            seen["dbname"] = dbname
            return self

    monkeypatch.setattr(
        tools,
        "_execute_sql",
        lambda conn, sql, **kw: seen.setdefault("ran", True),
    )
    tools._try_connect(Conn())
    assert seen["dbname"] == "postgres"
    assert seen["ran"] is True


def test_failure_does_not_propagate(monkeypatch):
    """Unveraendertes Verhalten nach aussen: melden, nicht abbrechen - der
    eigentliche Aufruf danach entscheidet."""

    def fake_execute_sql(conn, sql, **kwargs):
        raise Exception("FATAL:  something permanent")

    monkeypatch.setattr(tools, "_execute_sql", fake_execute_sql)
    tools._try_connect(object())  # darf nicht werfen


# ---------------------------------------------------------------------------
# der Verbindungsaufbau selbst
# ---------------------------------------------------------------------------


class _FakePsycopg2:
    """Minimaler psycopg2-Ersatz: liefert erst Fehler, dann eine Verbindung."""

    class OperationalError(Exception):
        pass

    def __init__(self, fehler, danach="CONN"):
        self.fehler = list(fehler)
        self.danach = danach
        self.versuche = 0

    def connect(self, **kwargs):
        self.versuche += 1
        if self.fehler:
            raise self.OperationalError(self.fehler.pop(0))
        return self.danach


def _connection(monkeypatch, fake):
    import sys

    monkeypatch.setitem(sys.modules, "psycopg2", fake)
    monkeypatch.setattr(tools.time, "sleep", lambda _s: None)
    return tools.DBConnection(
        dbname="odoo", host="postgres", port=5432, user="odoo", pwd="odoo"
    )


def test_connect_waits_out_a_shutdown(monkeypatch):
    """Der Fall aus dem bake-Test: postgres fahrt gerade herunter."""
    fake = _FakePsycopg2([REAL_CI_ERROR, REAL_CI_ERROR])
    conn = _connection(monkeypatch, fake)
    assert conn.get_psyco_connection() == "CONN"
    assert fake.versuche == 3


def test_connect_still_waits_out_a_startup(monkeypatch):
    """Das bisherige Verhalten muss erhalten bleiben."""
    fake = _FakePsycopg2(["FATAL:  the database system is starting up"])
    conn = _connection(monkeypatch, fake)
    assert conn.get_psyco_connection() == "CONN"
    assert fake.versuche == 2


def test_connect_does_not_swallow_a_real_error(monkeypatch):
    fake = _FakePsycopg2(
        ['FATAL:  password authentication failed for user "odoo"'] * 5
    )
    conn = _connection(monkeypatch, fake)
    with pytest.raises(fake.OperationalError):
        conn.get_psyco_connection()
    assert fake.versuche == 1, "kein Warten auf einen dauerhaften Fehler"


def test_connect_gives_up_eventually(monkeypatch):
    """Vorher war das ein `while True` - ein dauerhaftes 'starting up' hat
    fuer immer gewartet."""
    fake = _FakePsycopg2(["FATAL:  the database system is starting up"] * 500)
    monkeypatch.setenv("PSYCOPG_CONNECT_RETRY_SECONDS", "0")
    conn = _connection(monkeypatch, fake)
    with pytest.raises(fake.OperationalError):
        conn.get_psyco_connection()
    assert fake.versuche < 500, "muss nach der Frist aufgeben"

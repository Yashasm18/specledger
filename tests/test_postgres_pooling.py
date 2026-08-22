"""The connection pool must work behind a transaction pooler.

Supabase's pooler uses transaction pooling, which does not carry
session-level prepared statements: a pooled connection can be handed to a
different backend between statements. psycopg3 auto-prepares a statement
after it has been executed a few times, so under load production started
returning

    psycopg.errors.DuplicatePreparedStatement: prepared statement "_pg3_0" already exists
    psycopg.errors.InvalidSqlStatementName: prepared statement "_pg3_1" does not exist

which 500'd catalogue ingest and put the PDF extraction worker into a
failure loop. It is intermittent — it depends which pooled backend a
statement lands on — so an ingest that worked an hour earlier proves
nothing.

Disabling client-side prepared statements outright costs little at this
query volume and removes the failure mode. Detecting "am I behind a
pooler?" would be cleverer and would fail closed on a wrong guess, so
this deliberately does not try.
"""

import unittest
from contextlib import contextmanager

from backend.specledger import postgres_repository


class _FakeCursor:
    def execute(self, *args, **kwargs):
        return None

    def fetchone(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConnection:
    def cursor(self):
        return _FakeCursor()

    def commit(self):
        return None


class _FakePool:
    """Records how the real ConnectionPool would have been constructed."""

    last_kwargs: dict | None = None

    def __init__(self, conninfo, **kwargs):
        _FakePool.last_kwargs = kwargs
        self.conninfo = conninfo

    @contextmanager
    def connection(self):
        yield _FakeConnection()

    def close(self):
        return None


class PreparedStatementTests(unittest.TestCase):
    def setUp(self) -> None:
        import psycopg_pool
        self._real = psycopg_pool.ConnectionPool
        psycopg_pool.ConnectionPool = _FakePool
        _FakePool.last_kwargs = None

    def tearDown(self) -> None:
        import psycopg_pool
        psycopg_pool.ConnectionPool = self._real

    def test_pool_disables_client_side_prepared_statements(self) -> None:
        postgres_repository.PostgresRepository("postgresql://example/db")
        kwargs = _FakePool.last_kwargs or {}
        assert "kwargs" in kwargs, "connection kwargs were never passed to the pool"
        assert kwargs["kwargs"].get("prepare_threshold", "unset") is None


if __name__ == "__main__":
    unittest.main()

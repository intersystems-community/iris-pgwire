"""Spec 052 US7: READ COMMITTED is the default, and PGWIRE_DEFAULT_ISOLATION can change it.

The default reaches every place a session's level comes from: what the executor reports, what
the pool sets on a new connection, what a returned connection is reset to, and the server's
config. No IRIS: the statements are checked, not run.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from iris_pgwire.dbapi_connection_pool import IRISConnectionPool
from iris_pgwire.dbapi_executor import DBAPIExecutor
from iris_pgwire.models.backend_config import BackendConfig


def _executor(level: str | None) -> DBAPIExecutor:
    ex = object.__new__(DBAPIExecutor)
    ex.session_connections, ex.session_namespaces = {}, {}
    ex.session_transactions, ex.session_isolation = {}, {}
    ex.config = SimpleNamespace(txn_compat="strict")
    if level is not None:
        ex.config.default_isolation = level
    return ex


@pytest.mark.parametrize("level", ["read committed", "read uncommitted"])
def test_the_executor_reports_the_configured_default(level):
    ex = _executor(level)
    assert ex.default_isolation_level == level
    assert ex.get_default_isolation_level("s1") == level
    assert ex.get_isolation_level("s1") == level
    assert ex.get_isolation_level(None) == level


def test_a_config_without_the_setting_falls_back_to_read_committed():
    assert _executor(None).default_isolation_level == "read committed"


def test_a_session_override_still_wins():
    ex = _executor("read committed")
    ex.session_isolation["s1"] = "read uncommitted"
    assert ex.get_default_isolation_level("s1") == "read uncommitted"
    assert ex.get_default_isolation_level("s2") == "read committed"


@pytest.mark.parametrize(
    "level, iris_sql",
    [
        ("read committed", "SET TRANSACTION ISOLATION LEVEL READ COMMITTED"),
        ("read uncommitted", "SET TRANSACTION ISOLATION LEVEL READ UNCOMMITTED"),
    ],
)
def test_a_returned_connection_is_reset_to_the_configured_default(level, iris_sql):
    connection = MagicMock()
    cursor = connection.cursor.return_value
    assert DBAPIExecutor._reset_connection_sync(connection, level) is None
    sent = [c.args[0] for c in cursor.execute.call_args_list]
    assert sent[:2] == ["ROLLBACK", iris_sql]


def test_the_reset_restores_the_server_lock_timeout_when_given():
    connection = MagicMock()
    cursor = connection.cursor.return_value
    DBAPIExecutor._reset_connection_sync(connection, "read committed", lock_timeout_seconds=10)
    sent = [c.args[0] for c in cursor.execute.call_args_list]
    assert sent[-1] == "SET OPTION LOCK_TIMEOUT = 10"


@pytest.mark.parametrize(
    "level, statements",
    [
        ("read committed", ["SET TRANSACTION ISOLATION LEVEL READ COMMITTED"]),
        ("read uncommitted", []),  # IRIS's own default: nothing to send
    ],
)
def test_the_pool_sets_the_default_on_a_new_connection(level, statements):
    config = BackendConfig(backend_type="dbapi", iris_password="SYS", default_isolation=level)
    assert IRISConnectionPool(config).connection_setup_statements() == statements


class TestTheServerReadsTheSetting:
    """FR-024: PGWIRE_DEFAULT_ISOLATION reaches the executor (server.py builds its config by hand)."""

    def _config_passed(self, monkeypatch, value):
        from unittest.mock import patch

        import iris_pgwire.server as srv

        if value is None:
            monkeypatch.delenv("PGWIRE_DEFAULT_ISOLATION", raising=False)
        else:
            monkeypatch.setenv("PGWIRE_DEFAULT_ISOLATION", value)
        selector = MagicMock()
        with (
            patch.object(srv, "BackendSelector", return_value=selector),
            patch.object(srv, "enhance_iris_executor_with_integratedml", side_effect=lambda x: x),
        ):
            srv.PGWireServer(host="127.0.0.1", port=15432, backend_type="dbapi", auth_mode="trust")
        return selector.select_backend.call_args.args[0]

    def test_read_uncommitted_reaches_the_executor(self, monkeypatch):
        config = self._config_passed(monkeypatch, "read uncommitted")
        assert config.default_isolation == "read uncommitted"

    def test_read_committed_by_default(self, monkeypatch):
        assert self._config_passed(monkeypatch, None).default_isolation == "read committed"

    def test_an_unknown_level_stops_the_server(self, monkeypatch):
        with pytest.raises(ValueError, match="PGWIRE_DEFAULT_ISOLATION"):
            self._config_passed(monkeypatch, "serializable")


def test_a_new_connection_does_not_autocommit(monkeypatch):
    """Spec 052 US6 / FR-022: with the driver's default autocommit, a write whose client closed the
    connection (a cancel) still commits once its lock wait ends (measured 2026-11-14, n = 5); with
    autocommit off IRIS rolls it back (n = 0). PGWire commits explicitly after each statement of an
    autocommit session, so the driver's own autocommit is turned off on every pooled connection."""
    import asyncio
    import sys
    import types

    made = []

    class FakeConnection:
        def __init__(self):
            self.autocommit_calls = []
            made.append(self)

        def setAutoCommit(self, value):  # noqa: N802 - the driver's name
            self.autocommit_calls.append(value)

        def cursor(self):
            return MagicMock()

    fake_dbapi = types.SimpleNamespace(connect=lambda **kw: FakeConnection())
    monkeypatch.setitem(sys.modules, "iris.dbapi", fake_dbapi)
    monkeypatch.setitem(sys.modules, "iris", types.SimpleNamespace(dbapi=fake_dbapi))
    config = BackendConfig(backend_type="dbapi", iris_password="SYS")
    asyncio.run(IRISConnectionPool(config)._create_connection())
    assert made and made[0].autocommit_calls == [False]


def test_a_new_connection_records_its_iris_process(monkeypatch):
    """A cancel ends the session's IRIS process (`%SYSTEM.Process.Terminate`), so the pool records
    each connection's process number (`$JOB`) when it creates it."""
    import asyncio
    import sys
    import types

    sent = []

    class FakeCursor:
        def execute(self, sql, *a):
            sent.append(sql)

        def fetchone(self):
            return (48213,)

        def close(self):
            pass

    class FakeConnection:
        def setAutoCommit(self, value):  # noqa: N802 - the driver's name
            pass

        def cursor(self):
            return FakeCursor()

    fake_dbapi = types.SimpleNamespace(connect=lambda **kw: FakeConnection())
    monkeypatch.setitem(sys.modules, "iris.dbapi", fake_dbapi)
    monkeypatch.setitem(sys.modules, "iris", types.SimpleNamespace(dbapi=fake_dbapi))
    config = BackendConfig(backend_type="dbapi", iris_password="SYS")
    wrapper = asyncio.run(IRISConnectionPool(config)._create_connection())
    assert "SELECT $JOB" in sent
    assert wrapper.iris_process == 48213

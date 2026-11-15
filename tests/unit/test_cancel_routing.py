"""Spec 052 US6: a CancelRequest reaches the session it names, and its statement ends with 57014.

Research R9 measured the mechanism with the DBAPI driver: closing a connection from another
thread returns at once, the blocked call fails within the second, and IRIS rolls the
connection's transaction back. These tests pin the routing and the bookkeeping, with no IRIS.
"""

from __future__ import annotations

import asyncio
import struct
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest

from iris_pgwire.dbapi_executor import DBAPIExecutor
from iris_pgwire.protocol import PGWireProtocol


def _executor() -> DBAPIExecutor:
    ex = object.__new__(DBAPIExecutor)
    ex.session_connections, ex.session_namespaces = {}, {}
    ex.session_transactions, ex.session_isolation = {}, {}
    ex.config = MagicMock(
        txn_compat="strict", default_isolation="read committed", query_timeout=30.0
    )
    ex.pool = MagicMock(release=AsyncMock())
    ex._total_errors = 0
    return ex


def _wrapper(connection):
    wrapper = MagicMock()
    wrapper.connection = connection
    wrapper.is_healthy = True
    return wrapper


class TestTheServerFindsTheSession:
    def test_a_wrong_secret_finds_nothing(self):
        from iris_pgwire.server import PGWireServer

        server = object.__new__(PGWireServer)
        target = MagicMock()
        server.connection_registry = {4242: (target, 99)}
        assert server.find_connection_for_cancellation(4242, 99) is target
        assert server.find_connection_for_cancellation(4242, 98) is None
        assert server.find_connection_for_cancellation(1, 99) is None


class TestTheProtocolRoutesTheCancel:
    def _protocol(self, lookup):
        protocol = object.__new__(PGWireProtocol)
        protocol.connection_id = "canceller"
        protocol.reader = MagicMock(
            readexactly=AsyncMock(return_value=struct.pack("!II", 4242, 99))
        )
        protocol.writer = MagicMock(wait_closed=AsyncMock())
        protocol.iris_executor = MagicMock(cancel_query=AsyncMock(return_value=False))
        protocol.cancel_lookup = lookup
        return protocol

    def test_the_target_sessions_executor_is_asked_to_cancel_it(self):
        target = MagicMock(connection_id="victim")
        target.iris_executor.cancel_session = AsyncMock(return_value=True)
        protocol = self._protocol(
            lambda pid, secret: target if (pid, secret) == (4242, 99) else None
        )
        asyncio.run(protocol.handle_cancel_request())
        target.iris_executor.cancel_session.assert_awaited_once_with("victim")
        protocol.writer.close.assert_called_once()

    def test_an_unknown_session_changes_nothing(self):
        protocol = self._protocol(lambda pid, secret: None)
        asyncio.run(protocol.handle_cancel_request())
        protocol.writer.close.assert_called_once()


class TestTheExecutorCancelsARunningStatement:
    def test_no_statement_running_changes_nothing(self):
        ex = _executor()
        connection = MagicMock()
        ex.session_connections["s"] = _wrapper(connection)
        assert asyncio.run(ex.cancel_session("s")) is False
        connection.close.assert_not_called()
        assert "s" in ex.session_connections

    def test_a_running_statement_is_cancelled_and_the_session_starts_afresh(self):
        ex = _executor()
        connection = MagicMock()
        wrapper = _wrapper(connection)
        ex.session_connections["s"] = wrapper
        ex.session_transactions["s"] = True
        ex._statements_running["s"] = wrapper
        assert asyncio.run(ex.cancel_session("s")) is True
        connection.close.assert_called_once()
        wrapper.mark_failed.assert_called_once()
        assert "s" not in ex.session_connections
        assert "s" not in ex.session_transactions
        assert "s" in ex._statements_cancelled

    def test_the_cancelled_statement_reports_57014_and_its_connection_is_released(self):
        ex = _executor()
        released = threading.Event()

        class Blocking:
            def __init__(self):
                self.closed = threading.Event()

            def cursor(self):
                outer = self

                class Cursor:
                    description = None
                    rowcount = 0

                    def execute(self, *a):
                        outer.closed.wait(5)
                        raise RuntimeError("<COMMUNICATION LINK ERROR> Failed to receive message")

                    def close(self):
                        pass

                return Cursor()

            def close(self):
                self.closed.set()

            def commit(self):
                raise AssertionError("a cancelled statement must not be committed")

        connection = Blocking()
        wrapper = _wrapper(connection)
        ex.pool.acquire = AsyncMock(return_value=wrapper)
        ex.pool.release = AsyncMock(side_effect=lambda w: released.set())
        ex.catalog_router = MagicMock(handle_catalog_query=AsyncMock(return_value=None))
        ex.sql_interceptor = MagicMock()
        ex.sql_interceptor.intercept.return_value = MagicMock(intercepted=False)

        async def scenario():
            statement = asyncio.create_task(ex.execute_query("UPDATE t SET n = 5", session_id="s"))
            for _ in range(100):
                if "s" in ex._statements_running:
                    break
                await asyncio.sleep(0.01)
            assert await ex.cancel_session("s") is True
            return await statement

        result = asyncio.run(scenario())
        assert result["success"] is False
        assert result["sqlstate"] == "57014"
        assert result["error"] == "canceling statement due to user request"
        assert released.is_set()
        assert "s" not in ex._statements_cancelled


@pytest.mark.parametrize("attr", ["_statements_running", "_statements_cancelled"])
def test_the_bookkeeping_starts_empty(attr):
    assert not getattr(_executor(), attr)


def test_the_connection_is_marked_failed_before_close_returns():
    """Found by the slice 3 gate: the statement can finish and release its connection while the
    cancel's close() runs; marked failed only afterwards, the pool kept it and handed a closed
    connection to the next session (08000)."""
    ex = _executor()
    closing = threading.Event()
    seen_when_closing = {}

    class Connection:
        def close(self):
            seen_when_closing["failed"] = wrapper.mark_failed.called
            seen_when_closing["session_dropped"] = "s" not in ex.session_connections
            closing.set()

    wrapper = _wrapper(Connection())
    ex.session_connections["s"] = wrapper
    ex._statements_running["s"] = wrapper
    assert asyncio.run(ex.cancel_session("s")) is True
    assert closing.is_set()
    assert seen_when_closing == {"failed": True, "session_dropped": True}

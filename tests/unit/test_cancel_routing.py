"""Spec 052 US6: a CancelRequest reaches the session it names, and its statement ends with 57014.

The cancel ends the session's IRIS process from a separate control connection
(`%SYSTEM.Process.Terminate`): the blocked call fails at once with a communication error and IRIS
rolls the transaction back (40 of 40, 2026-11-15). Closing the connection from another thread,
the first design (research R9), crashed the server with a segmentation fault about once in 35
cancels, so the session's connection is never touched from the cancelling thread. These tests pin
the routing and the bookkeeping, with no IRIS.
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


def _wrapper(connection, process=4242):
    wrapper = MagicMock()
    wrapper.connection = connection
    wrapper.is_healthy = True
    wrapper.iris_process = process
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
        ex._terminate_iris_process = MagicMock(return_value=True)
        connection = MagicMock()
        wrapper = _wrapper(connection, process=777)
        ex.session_connections["s"] = wrapper
        ex.session_transactions["s"] = True
        ex._statements_running["s"] = wrapper
        assert asyncio.run(ex.cancel_session("s")) is True
        ex._terminate_iris_process.assert_called_once_with(777)
        connection.close.assert_not_called()
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
                raise AssertionError("the cancel must not close the connection from its thread")

            def commit(self):
                raise AssertionError("a cancelled statement must not be committed")

        connection = Blocking()
        wrapper = _wrapper(connection)
        ex._terminate_iris_process = lambda process: connection.closed.set() or True
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


def test_the_connection_is_marked_failed_before_the_process_is_ended():
    """Found by the slice 3 gate: the statement can finish and release its connection while the
    cancel waits; marked failed only afterwards, the pool kept it and handed a dead connection to
    the next session (08000)."""
    ex = _executor()
    seen_when_ending = {}

    def terminate(process):
        seen_when_ending["failed"] = wrapper.mark_failed.called
        seen_when_ending["session_dropped"] = "s" not in ex.session_connections
        return True

    ex._terminate_iris_process = terminate
    wrapper = _wrapper(MagicMock())
    ex.session_connections["s"] = wrapper
    ex._statements_running["s"] = wrapper
    assert asyncio.run(ex.cancel_session("s")) is True
    assert seen_when_ending == {"failed": True, "session_dropped": True}


def test_a_connection_with_no_known_process_is_not_cancelled():
    """Without its IRIS process number there is nothing safe to end: the cancel changes nothing
    (the statement runs to completion) rather than closing the connection from this thread."""
    ex = _executor()
    ex._terminate_iris_process = MagicMock()
    connection = MagicMock()
    wrapper = _wrapper(connection, process=None)
    ex.session_connections["s"] = wrapper
    ex._statements_running["s"] = wrapper
    assert asyncio.run(ex.cancel_session("s")) is False
    ex._terminate_iris_process.assert_not_called()
    connection.close.assert_not_called()
    assert "s" in ex.session_connections


def test_ending_the_process_uses_its_own_connection_and_the_native_api(monkeypatch):
    import sys
    import types

    calls = []

    class Native:
        def classMethodValue(self, *args):  # noqa: N802 - the driver's name
            calls.append(args)
            return 1

    control = MagicMock(name="control connection")
    fake_dbapi = types.SimpleNamespace(connect=lambda **kw: control)
    fake_iris = types.SimpleNamespace(dbapi=fake_dbapi, createIRIS=lambda conn: Native())
    monkeypatch.setitem(sys.modules, "iris", fake_iris)
    monkeypatch.setitem(sys.modules, "iris.dbapi", fake_dbapi)
    ex = _executor()
    ex.config.iris_hostname, ex.config.iris_port = "h", 1
    ex.config.iris_namespace, ex.config.iris_username, ex.config.iris_password = "USER", "u", "p"
    assert ex._terminate_iris_process(4711) is True
    assert calls == [("%SYSTEM.Process", "Terminate", 4711)]
    assert ex._terminate_iris_process(4712) is True
    assert len(calls) == 2  # the control connection is reused


def test_a_refused_terminate_is_reported_false(monkeypatch):
    import sys
    import types

    class Native:
        def classMethodValue(self, *args):  # noqa: N802
            return 0

    fake_dbapi = types.SimpleNamespace(connect=lambda **kw: MagicMock())
    monkeypatch.setitem(
        sys.modules, "iris", types.SimpleNamespace(dbapi=fake_dbapi, createIRIS=lambda c: Native())
    )
    monkeypatch.setitem(sys.modules, "iris.dbapi", fake_dbapi)
    ex = _executor()
    assert ex._terminate_iris_process(4711) is False

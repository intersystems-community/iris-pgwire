"""2.0.1: the pool reset on session close, the 08000 default, and the savepoint rewrite.

Each defect was measured by the isolation suite (tests/e2e/isolation, `make isolation`) and is
described in docs/investigations/mvcc-apps-on-iris-pgwire.md section 5. These are the unit-level
halves; the suite's h3/*, savepoints/* and pool_reset/* checks are the end-to-end halves.

1. `DBAPIExecutor.close_session` returned a disconnected client's IRIS connection to the pool with
   its transaction open and its isolation level unchanged. The next session ran inside the
   abandoned transaction, and a bare COMMIT made another client's uncommitted write permanent.
2. IRIS errors with no mapping reached the client as 08000 (connection_exception), which tells a
   client pool to discard a healthy connection. -375 is PostgreSQL's 3B001.
3. psycopg's `ROLLBACK TO "_pg3_1"` reached IRIS unrewritten on the DBAPI backend (IRIS requires
   `ROLLBACK TO SAVEPOINT`), failed with SQLCODE -1, psycopg ignored the failure, and a nested
   `transaction()` block committed its inner work.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from iris_pgwire.sql_translator.isolation import DEFAULT_ISOLATION_LEVEL
from iris_pgwire.sql_translator.sqlstate import classify_iris_error
from iris_pgwire.sql_translator.transaction_translator import (
    TransactionTranslator,
    rewrite_savepoint_verbs,
)

# The DBAPI driver's error when it is out of step with IRIS, as logged by the isolation suite.
LIST_ERROR = (
    "<LIST ERROR> Incorrect list format, unsupported type for IRISList; "
    "Details: type detected : 9"
)


def _connection(fail_on: str | None = None, error: Exception | None = None):
    """A DBAPI connection whose cursor records every statement it is given."""
    sent: list[str] = []
    cursor = MagicMock()

    def execute(sql, *args, **kwargs):
        sent.append(sql)
        if fail_on is not None and sql.upper().startswith(fail_on):
            raise error or RuntimeError("boom")

    cursor.execute.side_effect = execute
    cursor.description, cursor.rowcount = None, 0
    cursor.fetchall.return_value = []
    conn = MagicMock()
    conn.cursor.return_value = cursor
    return conn, sent


def _wrapper(conn, is_healthy=True):
    wrapper = MagicMock()
    wrapper.connection = conn
    wrapper.is_healthy = is_healthy

    def mark_failed(message):
        wrapper.is_healthy = False

    wrapper.mark_failed.side_effect = mark_failed
    return wrapper


@pytest.fixture
def executor():
    from iris_pgwire.dbapi_executor import DBAPIExecutor

    cfg = MagicMock()
    cfg.iris_hostname, cfg.iris_port, cfg.iris_namespace = "localhost", 1972, "USER"
    cfg.iris_username, cfg.iris_password = "_SYSTEM", "SYS"
    cfg.pool_size, cfg.pool_max_overflow, cfg.pool_timeout, cfg.pool_recycle = 5, 2, 30, 3600
    cfg.query_timeout, cfg.strict_single_connection, cfg.enable_otel = 30.0, False, False
    with (
        patch("iris_pgwire.dbapi_executor.IRISConnectionPool") as pool_cls,
        patch("iris_pgwire.dbapi_executor.CatalogRouter") as catalog_cls,
        patch("iris_pgwire.dbapi_executor.SQLPipeline"),
        patch("iris_pgwire.dbapi_executor.get_parser"),
    ):
        pool = MagicMock()
        pool.acquire, pool.release = AsyncMock(), AsyncMock()
        pool_cls.return_value = pool
        catalog = MagicMock()
        catalog.handle_catalog_query = AsyncMock(return_value=None)
        catalog_cls.return_value = catalog
        return DBAPIExecutor(cfg)


# ---------------------------------------------------------------------------
# 1. Pool reset on session close
# ---------------------------------------------------------------------------


class TestCloseSessionResetsTheConnection:
    def test_an_open_transaction_is_rolled_back_before_the_connection_is_released(self, executor):
        conn, sent = _connection()
        wrapper = _wrapper(conn)
        executor.session_connections["s1"] = wrapper
        executor.session_transactions["s1"] = True

        asyncio.run(executor.close_session("s1"))

        assert sent[0].upper() == "ROLLBACK"
        executor.pool.release.assert_awaited_once_with(wrapper)
        assert wrapper.is_healthy, "a clean reset keeps the connection for reuse"

    def test_rollback_is_sent_even_when_no_transaction_was_tracked(self, executor):
        """The bookkeeping is not the authority: a BEGIN it missed still holds locks in IRIS."""
        conn, sent = _connection()
        executor.session_connections["s1"] = _wrapper(conn)

        asyncio.run(executor.close_session("s1"))

        assert "ROLLBACK" in [s.upper() for s in sent]

    def test_the_isolation_level_goes_back_to_the_server_default(self, executor):
        conn, sent = _connection()
        executor.session_connections["s1"] = _wrapper(conn)
        executor.session_isolation["s1"] = "read committed"

        asyncio.run(executor.close_session("s1"))

        expected = f"SET TRANSACTION ISOLATION LEVEL {DEFAULT_ISOLATION_LEVEL.upper()}"
        assert [s.upper() for s in sent] == ["ROLLBACK", expected]
        # The ROLLBACK comes first: IRIS refuses a level change inside a transaction.

    def test_a_connection_whose_reset_fails_is_discarded_not_reused(self, executor):
        conn, _ = _connection(fail_on="ROLLBACK", error=RuntimeError(LIST_ERROR))
        wrapper = _wrapper(conn)
        executor.session_connections["s1"] = wrapper

        asyncio.run(executor.close_session("s1"))

        wrapper.mark_failed.assert_called_once()
        assert not wrapper.is_healthy
        # Released all the same: the pool removes an unhealthy connection instead of queueing it.
        executor.pool.release.assert_awaited_once_with(wrapper)

    def test_a_failed_level_reset_also_discards(self, executor):
        conn, _ = _connection(fail_on="SET TRANSACTION")
        wrapper = _wrapper(conn)
        executor.session_connections["s1"] = wrapper

        asyncio.run(executor.close_session("s1"))

        assert not wrapper.is_healthy

    def test_an_already_failed_connection_is_not_sent_anything(self, executor):
        conn, sent = _connection()
        wrapper = _wrapper(conn, is_healthy=False)
        executor.session_connections["s1"] = wrapper

        asyncio.run(executor.close_session("s1"))

        assert sent == []
        executor.pool.release.assert_awaited_once_with(wrapper)

    def test_session_state_is_still_forgotten(self, executor):
        conn, _ = _connection()
        executor.session_connections["s1"] = _wrapper(conn)
        executor.session_transactions["s1"] = True
        executor.session_namespaces["s1"] = "USER"
        executor.session_isolation["s1"] = "read committed"

        asyncio.run(executor.close_session("s1"))

        for store in (
            executor.session_connections,
            executor.session_transactions,
            executor.session_namespaces,
            executor.session_isolation,
        ):
            assert "s1" not in store


class TestADriverOutOfStepIsNotReused:
    """`<LIST ERROR> Incorrect list format` left the connection in the pool (connection_lost=False)."""

    def test_a_list_error_marks_the_connection_failed(self, executor):
        wrapper = _wrapper(_connection()[0])
        executor.session_connections["s1"] = wrapper

        executor._handle_execution_error(
            RuntimeError(LIST_ERROR), wrapper, "s1", "insert into t values (1)", "Query"
        )

        assert not wrapper.is_healthy

    def test_the_session_keeps_its_connection_until_it_closes(self, executor):
        """Swapping it mid-session would silently move the session out of its transaction."""
        wrapper = _wrapper(_connection()[0])
        executor.session_connections["s1"] = wrapper
        executor.session_transactions["s1"] = True

        executor._handle_execution_error(RuntimeError(LIST_ERROR), wrapper, "s1", "x", "Query")

        assert executor.session_connections["s1"] is wrapper
        assert executor.session_transactions["s1"] is True

    def test_an_ordinary_sql_error_does_not(self, executor):
        wrapper = _wrapper(_connection()[0])
        executor._handle_execution_error(
            RuntimeError("[SQLCODE: <-30>:<Table or view not found>]"), wrapper, "s1", "x", "Query"
        )
        assert wrapper.is_healthy


class TestRollbackToKeepsTheTransactionOpen:
    """`ROLLBACK TO SAVEPOINT` ends no transaction, so the next statement must not auto-commit."""

    @pytest.mark.parametrize(
        "sql", ['ROLLBACK TO SAVEPOINT "_pg3_1"', "ROLLBACK TO SAVEPOINT s", "rollback to s"]
    )
    def test_rollback_to_does_not_end_the_transaction(self, executor, sql):
        executor.session_transactions["s1"] = True
        executor._update_transaction_state("s1", sql.upper())
        assert executor.session_transactions.get("s1") is True

    @pytest.mark.parametrize("sql", ["ROLLBACK", "ROLLBACK WORK", "COMMIT", "END"])
    def test_the_real_ends_still_end_it(self, executor, sql):
        executor.session_transactions["s1"] = True
        executor._update_transaction_state("s1", sql)
        assert "s1" not in executor.session_transactions


# ---------------------------------------------------------------------------
# 2. SQLSTATE defaults
# ---------------------------------------------------------------------------


class TestUnmappedErrorsAreNotConnectionExceptions:
    def test_minus_375_is_invalid_savepoint_specification(self):
        message = "[SQLCODE: <-375>:<Cannot ROLLBACK to unestablished savepoint>]"
        assert classify_iris_error(message) == ("3B001", "invalid_savepoint_specification")

    @pytest.mark.parametrize("code", [-14, -51, -9999])
    def test_an_unmapped_sqlcode_is_xx000(self, code):
        assert classify_iris_error(f"[SQLCODE: <{code}>:<whatever>]")[0] == "XX000"

    def test_the_drivers_list_error_is_xx000(self):
        assert classify_iris_error(LIST_ERROR)[0] == "XX000"

    @pytest.mark.parametrize(
        "message",
        ["Communication link failure", "connection lost", "Socket error: broken pipe"],
    )
    def test_a_real_connection_failure_is_still_08000(self, message):
        """Only the transport failing is a connection exception."""
        assert classify_iris_error(message) == ("08000", "connection_exception")

    def test_no_protocol_error_site_defaults_to_08000(self):
        """Every IRIS error path used to pass default=08000 or hardcode it."""
        import inspect

        from iris_pgwire import protocol

        source = inspect.getsource(protocol)
        assert '"08000"' not in source, "an unconditional 08000 is back in protocol.py"


# ---------------------------------------------------------------------------
# 3. Savepoint verbs
# ---------------------------------------------------------------------------


class TestSavepointRewrite:
    @pytest.mark.parametrize(
        ("sql", "expected"),
        [
            ('ROLLBACK TO "_pg3_1"', 'ROLLBACK TO SAVEPOINT "_pg3_1"'),
            ('rollback to "_pg3_12";', 'ROLLBACK TO SAVEPOINT "_pg3_12"'),
            ('ROLLBACK TO "my savepoint"', 'ROLLBACK TO SAVEPOINT "my savepoint"'),
            ('ROLLBACK TO "a""b"', 'ROLLBACK TO SAVEPOINT "a""b"'),
            ("ROLLBACK TO s1", "ROLLBACK TO SAVEPOINT s1"),
            ('RELEASE "_pg3_1"', 'RELEASE SAVEPOINT "_pg3_1"'),
            ("release s1", "RELEASE SAVEPOINT s1"),
        ],
    )
    def test_the_savepoint_keyword_is_supplied(self, sql, expected):
        assert rewrite_savepoint_verbs(sql) == expected

    @pytest.mark.parametrize(
        "sql",
        [
            'ROLLBACK TO SAVEPOINT "_pg3_1"',
            "ROLLBACK TO SAVEPOINT s1",
            "RELEASE SAVEPOINT s1",
            'SAVEPOINT "_pg3_1"',
            "ROLLBACK",
            "select 'rollback to x'",
            "insert into release values (1)",
        ],
    )
    def test_everything_else_is_unchanged(self, sql):
        assert rewrite_savepoint_verbs(sql) == sql

    def test_the_embedded_translator_agrees(self):
        assert (
            TransactionTranslator().translate_transaction_command('ROLLBACK TO "my savepoint"')
            == 'ROLLBACK TO SAVEPOINT "my savepoint"'
        )

    def test_the_dbapi_backend_sends_the_rewritten_statement(self, executor):
        """The measured defect: the DBAPI path never applied the rewrite at all."""
        conn, sent = _connection()
        wrapper = _wrapper(conn)
        executor.pool.acquire = AsyncMock(return_value=wrapper)
        executor.session_connections["s1"] = wrapper
        executor.session_transactions["s1"] = True

        result = asyncio.run(
            executor.execute_query('ROLLBACK TO "_pg3_1"', session_id="s1", _skip_isolation=True)
        )

        assert result.get("success"), result
        assert any(s.rstrip(";").strip() == 'ROLLBACK TO SAVEPOINT "_pg3_1"' for s in sent), sent

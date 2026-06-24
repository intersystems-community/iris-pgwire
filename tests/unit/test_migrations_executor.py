"""Unit tests for MigrationExecutor (src/iris_pgwire/migrations/executor.py)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from iris_pgwire.config import DDLTranslationConfig
from iris_pgwire.migrations.executor import MigrationExecutor, MigrationResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_mock_connection(fetchone_returns=None):
    """Return a MagicMock that behaves like a DBAPI connection."""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.return_value = fetchone_returns
    conn.cursor.return_value = cursor
    return conn, cursor


def make_migration_file(
    content: str = "CREATE TABLE t (id INTEGER)",
    hash_value: str | None = None,
    statements: list[str] | None = None,
) -> SimpleNamespace:
    """Build a minimal migration file object."""
    mf = SimpleNamespace(content=content)
    if hash_value is not None:
        mf.hash = hash_value
    if statements is not None:
        mf.statements = statements
    return mf


# ---------------------------------------------------------------------------
# MigrationResult dataclass
# ---------------------------------------------------------------------------


class TestMigrationResult:
    def test_defaults(self):
        mf = make_migration_file()
        result = MigrationResult(migration_file=mf, success=True)
        assert result.statements_executed == 0
        assert result.already_applied is False
        assert result.warnings == ()
        assert result.execution_time_ms == 0.0
        assert result.error is None

    def test_failure_result(self):
        mf = make_migration_file()
        result = MigrationResult(
            migration_file=mf,
            success=False,
            error="something went wrong",
        )
        assert not result.success
        assert result.error == "something went wrong"


# ---------------------------------------------------------------------------
# MigrationExecutor construction
# ---------------------------------------------------------------------------


class TestMigrationExecutorInit:
    def test_default_config(self):
        conn, _ = make_mock_connection()
        executor = MigrationExecutor(connection=conn)
        assert executor._config.lock_timeout_seconds == 30

    def test_custom_config(self):
        conn, _ = make_mock_connection()
        config = DDLTranslationConfig(lock_timeout_seconds=10)
        executor = MigrationExecutor(connection=conn, config=config)
        assert executor._config.lock_timeout_seconds == 10


# ---------------------------------------------------------------------------
# _journal_table_exists
# ---------------------------------------------------------------------------


class TestJournalTableExists:
    def test_returns_true_when_row_found(self):
        conn, cursor = make_mock_connection(fetchone_returns=(1,))
        executor = MigrationExecutor(connection=conn)
        assert executor._journal_table_exists() is True

    def test_returns_false_when_no_row(self):
        conn, cursor = make_mock_connection(fetchone_returns=None)
        executor = MigrationExecutor(connection=conn)
        assert executor._journal_table_exists() is False

    def test_queries_information_schema(self):
        conn, cursor = make_mock_connection(fetchone_returns=None)
        executor = MigrationExecutor(connection=conn)
        executor._journal_table_exists()
        executed_sql = cursor.execute.call_args[0][0]
        assert "INFORMATION_SCHEMA" in executed_sql
        assert "__DRIZZLE_MIGRATIONS" in cursor.execute.call_args[0][1][0]


# ---------------------------------------------------------------------------
# create_journal_table
# ---------------------------------------------------------------------------


class TestCreateJournalTable:
    def test_creates_table_when_not_exists(self):
        conn, cursor = make_mock_connection(fetchone_returns=None)
        executor = MigrationExecutor(connection=conn)
        executor.create_journal_table()
        # cursor.execute should be called at least twice:
        # once for the check and once for CREATE TABLE
        assert cursor.execute.call_count >= 2

    def test_skips_create_when_table_exists(self):
        conn, cursor = make_mock_connection(fetchone_returns=(1,))
        executor = MigrationExecutor(connection=conn)
        executor.create_journal_table()
        # Only the check query should run; no CREATE TABLE
        assert cursor.execute.call_count == 1

    def test_double_call_does_not_error(self):
        """Calling create_journal_table twice should not raise."""
        # First call: table absent → create it
        # Second call: table present → skip
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        call_count = [0]

        def fetchone_side_effect():
            call_count[0] += 1
            if call_count[0] == 1:
                return None  # first _journal_table_exists check → absent
            return (1,)  # subsequent checks → present

        cursor.fetchone.side_effect = fetchone_side_effect
        executor = MigrationExecutor(connection=conn)
        executor.create_journal_table()
        executor.create_journal_table()  # should not raise


# ---------------------------------------------------------------------------
# is_migration_applied
# ---------------------------------------------------------------------------


class TestIsMigrationApplied:
    def test_returns_false_for_unknown_hash(self):
        conn, cursor = make_mock_connection(fetchone_returns=None)
        executor = MigrationExecutor(connection=conn)
        assert executor.is_migration_applied("nonexistent_hash") is False

    def test_returns_true_for_known_hash(self):
        conn, cursor = make_mock_connection(fetchone_returns=(1,))
        executor = MigrationExecutor(connection=conn)
        assert executor.is_migration_applied("abc123") is True

    def test_queries_correct_table(self):
        conn, cursor = make_mock_connection(fetchone_returns=None)
        executor = MigrationExecutor(connection=conn)
        executor.is_migration_applied("myhash")
        sql = cursor.execute.call_args[0][0]
        assert "__drizzle_migrations" in sql
        assert "hash" in sql


# ---------------------------------------------------------------------------
# record_migration
# ---------------------------------------------------------------------------


class TestRecordMigration:
    def test_inserts_hash_for_file_with_hash_attr(self):
        conn, cursor = make_mock_connection()
        executor = MigrationExecutor(connection=conn)
        mf = make_migration_file(hash_value="deadbeef")
        executor.record_migration(mf)
        sql = cursor.execute.call_args[0][0]
        params = cursor.execute.call_args[0][1]
        assert "INSERT INTO __drizzle_migrations" in sql
        assert params[0] == "deadbeef"

    def test_inserts_hash_from_content_when_no_hash_attr(self):
        import hashlib

        conn, cursor = make_mock_connection()
        executor = MigrationExecutor(connection=conn)
        mf = SimpleNamespace(content="CREATE TABLE x (id INTEGER)")
        executor.record_migration(mf)
        params = cursor.execute.call_args[0][1]
        expected_hash = hashlib.sha256(b"CREATE TABLE x (id INTEGER)").hexdigest()
        assert params[0] == expected_hash

    def test_inserts_hash_from_checksum_attr(self):
        conn, cursor = make_mock_connection()
        executor = MigrationExecutor(connection=conn)
        mf = SimpleNamespace(checksum="mycheck", content="irrelevant")
        executor.record_migration(mf)
        params = cursor.execute.call_args[0][1]
        assert params[0] == "mycheck"


# ---------------------------------------------------------------------------
# _get_migration_hash
# ---------------------------------------------------------------------------


class TestGetMigrationHash:
    def test_prefers_hash_attr(self):
        conn, _ = make_mock_connection()
        executor = MigrationExecutor(connection=conn)
        mf = SimpleNamespace(hash="preferred", checksum="ignored", content="also ignored")
        assert executor._get_migration_hash(mf) == "preferred"

    def test_falls_back_to_checksum(self):
        conn, _ = make_mock_connection()
        executor = MigrationExecutor(connection=conn)
        mf = SimpleNamespace(checksum="chk123", content="irrelevant")
        assert executor._get_migration_hash(mf) == "chk123"

    def test_computes_sha256_from_bytes_content(self):
        import hashlib

        conn, _ = make_mock_connection()
        executor = MigrationExecutor(connection=conn)
        raw = b"some bytes"
        mf = SimpleNamespace(content=raw)
        result = executor._get_migration_hash(mf)
        assert result == hashlib.sha256(raw).hexdigest()

    def test_computes_sha256_from_str_content(self):
        import hashlib

        conn, _ = make_mock_connection()
        executor = MigrationExecutor(connection=conn)
        mf = SimpleNamespace(content="hello world")
        result = executor._get_migration_hash(mf)
        assert result == hashlib.sha256(b"hello world").hexdigest()

    def test_raises_when_no_usable_attribute(self):
        conn, _ = make_mock_connection()
        executor = MigrationExecutor(connection=conn)
        mf = SimpleNamespace()
        with pytest.raises(AttributeError, match="hash.*checksum.*content"):
            executor._get_migration_hash(mf)


# ---------------------------------------------------------------------------
# Transaction helpers
# ---------------------------------------------------------------------------


class TestTransactionHelpers:
    def test_begin_transaction_executes_start(self):
        conn, cursor = make_mock_connection()
        executor = MigrationExecutor(connection=conn)
        executor._begin_transaction()
        cursor.execute.assert_called_with("START TRANSACTION")
        assert executor._transaction_active is True

    def test_begin_transaction_is_idempotent(self):
        conn, cursor = make_mock_connection()
        executor = MigrationExecutor(connection=conn)
        executor._begin_transaction()
        executor._begin_transaction()  # second call should be no-op
        assert cursor.execute.call_count == 1

    def test_commit_transaction(self):
        conn, _ = make_mock_connection()
        executor = MigrationExecutor(connection=conn)
        executor._transaction_active = True
        executor._commit_transaction()
        conn.commit.assert_called_once()
        assert executor._transaction_active is False

    def test_commit_when_no_active_transaction(self):
        conn, _ = make_mock_connection()
        executor = MigrationExecutor(connection=conn)
        executor._commit_transaction()  # should not raise
        conn.commit.assert_not_called()

    def test_rollback_transaction(self):
        conn, _ = make_mock_connection()
        executor = MigrationExecutor(connection=conn)
        executor._transaction_active = True
        executor._rollback_transaction()
        conn.rollback.assert_called_once()
        assert executor._transaction_active is False

    def test_rollback_when_no_active_transaction(self):
        conn, _ = make_mock_connection()
        executor = MigrationExecutor(connection=conn)
        executor._rollback_transaction()  # should not raise
        conn.rollback.assert_not_called()


# ---------------------------------------------------------------------------
# _cursor context manager
# ---------------------------------------------------------------------------


class TestCursorContextManager:
    def test_cursor_opened_and_closed(self):
        conn, cursor = make_mock_connection()
        executor = MigrationExecutor(connection=conn)
        with executor._cursor() as c:
            assert c is cursor
        cursor.close.assert_called_once()

    def test_cursor_closed_on_exception(self):
        conn, cursor = make_mock_connection()
        executor = MigrationExecutor(connection=conn)
        with pytest.raises(RuntimeError):
            with executor._cursor():
                raise RuntimeError("inside cursor")
        cursor.close.assert_called_once()


# ---------------------------------------------------------------------------
# _acquire_lock / _release_lock
# ---------------------------------------------------------------------------


class TestLockHelpers:
    def test_acquire_lock_executes_lock_table(self):
        conn, cursor = make_mock_connection()
        executor = MigrationExecutor(connection=conn)
        executor._acquire_lock(timeout_seconds=30)
        calls = [c[0][0] for c in cursor.execute.call_args_list]
        assert any("LOCK TABLE" in sql for sql in calls)

    def test_acquire_lock_handles_set_session_failure(self):
        """If SET SESSION fails (IRIS), lock acquisition should still proceed."""
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        call_count = [0]

        def execute_side_effect(sql, *args, **kwargs):
            call_count[0] += 1
            if "SET SESSION" in sql:
                raise Exception("IRIS does not support SET SESSION")

        cursor.execute.side_effect = execute_side_effect
        executor = MigrationExecutor(connection=conn)
        # Should not raise even when SET SESSION fails
        executor._acquire_lock(timeout_seconds=5)
        assert call_count[0] >= 2

    def test_release_lock_is_no_op(self):
        conn, cursor = make_mock_connection()
        executor = MigrationExecutor(connection=conn)
        executor._release_lock()  # should not raise or do anything


# ---------------------------------------------------------------------------
# execute_migration — already applied
# ---------------------------------------------------------------------------


class TestExecuteMigrationAlreadyApplied:
    def test_returns_already_applied_when_hash_found(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        call_count = [0]

        def fetchone_side_effect():
            call_count[0] += 1
            # First call: LOCK TABLE (no fetchone needed)
            # Second call: is_migration_applied check → return row (applied)
            return (1,)

        cursor.fetchone.side_effect = fetchone_side_effect

        executor = MigrationExecutor(connection=conn)
        mf = make_migration_file(hash_value="known_hash")
        result = executor.execute_migration(mf)
        assert result.already_applied is True
        assert result.success is True
        assert result.statements_executed == 0


# ---------------------------------------------------------------------------
# execute_migration — success path
# ---------------------------------------------------------------------------


class TestExecuteMigrationSuccess:
    def _build_executor_for_new_migration(self):
        """Executor where journal check returns None (migration not yet applied)."""
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        call_tracker = {"call_idx": 0}
        check_calls = set()

        def fetchone_side_effect():
            sql_calls = cursor.execute.call_args_list
            if not sql_calls:
                return None
            last_sql = sql_calls[-1][0][0] if sql_calls[-1][0] else ""
            if "WHERE hash" in last_sql:
                return None  # not yet applied
            return None

        cursor.fetchone.side_effect = fetchone_side_effect
        return conn, cursor

    def test_success_result_with_statements_list(self):
        conn, cursor = self._build_executor_for_new_migration()
        executor = MigrationExecutor(connection=conn)
        mf = make_migration_file(
            hash_value="new_hash",
            statements=["CREATE TABLE orders (id INTEGER NOT NULL)"],
        )
        result = executor.execute_migration(mf)
        assert result.success is True
        assert result.statements_executed >= 1

    def test_success_result_with_content(self):
        """When migration_file has no 'statements' attr, fall back to content as a raw SQL string."""
        conn, cursor = self._build_executor_for_new_migration()
        executor = MigrationExecutor(connection=conn)
        # Use a raw GRANT statement that the DDLParser will not recognize — it
        # takes the "execute raw" code path, which does not need table-name parsing.
        mf = make_migration_file(
            hash_value="new_hash2",
            content="GRANT SELECT ON some_table TO reader",
        )
        result = executor.execute_migration(mf)
        assert result.success is True

    def test_empty_statements_succeed(self):
        conn, cursor = self._build_executor_for_new_migration()
        executor = MigrationExecutor(connection=conn)
        mf = make_migration_file(hash_value="empty_hash", statements=[])
        result = executor.execute_migration(mf)
        assert result.success is True
        assert result.statements_executed == 0

    def test_execution_time_measured(self):
        conn, cursor = self._build_executor_for_new_migration()
        executor = MigrationExecutor(connection=conn)
        mf = make_migration_file(hash_value="t_hash", statements=[])
        result = executor.execute_migration(mf)
        assert result.execution_time_ms >= 0.0


# ---------------------------------------------------------------------------
# execute_migration — failure path
# ---------------------------------------------------------------------------


class TestExecuteMigrationFailure:
    def test_db_error_returns_failed_result(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor

        cursor.fetchone.return_value = None

        execute_call_count = [0]

        def execute_side_effect(sql, *args, **kwargs):
            execute_call_count[0] += 1
            # Let lock and check queries pass; fail on actual DDL execution
            if "CREATE TABLE" in sql and "drizzle" not in sql.lower():
                raise RuntimeError("DB error during DDL execution")

        cursor.execute.side_effect = execute_side_effect

        executor = MigrationExecutor(connection=conn)
        mf = make_migration_file(
            hash_value="fail_hash",
            statements=["CREATE TABLE orders (id INTEGER NOT NULL)"],
        )
        result = executor.execute_migration(mf)
        assert result.success is False
        assert result.error is not None

    def test_rollback_called_on_failure(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = None

        def execute_side_effect(sql, *args, **kwargs):
            if "START TRANSACTION" in sql:
                return  # succeed
            if "CREATE TABLE" in sql and "drizzle" not in sql.lower():
                raise RuntimeError("fail during DDL")

        cursor.execute.side_effect = execute_side_effect
        executor = MigrationExecutor(connection=conn)
        mf = make_migration_file(
            hash_value="rb_hash",
            statements=["CREATE TABLE orders (id INTEGER NOT NULL)"],
        )
        result = executor.execute_migration(mf)
        assert result.success is False
        conn.rollback.assert_called()

    def test_not_translatable_statement_fails(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = None

        executor = MigrationExecutor(connection=conn)
        # DROP TABLE is not translatable by DDLTranslator
        mf = make_migration_file(
            hash_value="drop_hash",
            statements=["DROP TABLE orders"],
        )
        result = executor.execute_migration(mf)
        assert result.success is False

    def test_unrecognized_sql_executed_raw(self):
        """Statements the DDLParser can't parse are executed raw."""
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = None

        executor = MigrationExecutor(connection=conn)
        # This is not a DDL statement the parser recognizes as CREATE/ALTER/DROP
        mf = make_migration_file(
            hash_value="raw_hash",
            statements=["GRANT SELECT ON orders TO reader"],
        )
        result = executor.execute_migration(mf)
        # Should succeed and execute the raw statement
        assert result.success is True
        assert result.statements_executed >= 1

    def test_empty_raw_statement_skipped(self):
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value = cursor
        cursor.fetchone.return_value = None

        executor = MigrationExecutor(connection=conn)
        mf = make_migration_file(
            hash_value="blank_hash",
            statements=["", "   ", "--just a comment"],
        )
        result = executor.execute_migration(mf)
        assert result.success is True

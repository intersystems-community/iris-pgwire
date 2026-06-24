"""
Unit tests for iris_pgwire.dbapi_executor.DBAPIExecutor

Strategy: mock IRISConnectionPool and catalog/sql dependencies so we can test
all code paths without a real IRIS connection.

Coverage targets (aiming for >75%):
- __init__ and initialization
- _translate_placeholders
- _convert_params_for_iris / _convert_value_for_iris / _convert_iso_timestamp
- execute_query (happy path, timeout, connection-lost, catalog result)
- execute_many / _execute_batch_loop
- _acquire_connection (pinned vs pool)
- _update_transaction_state / _is_transaction_control_sql / _maybe_auto_commit
- _execute_statement_sync / _execute_with_cursor
- _handle_conflict_exception (DO NOTHING, DO UPDATE)
- _build_result / _fetch_standard_results / _refine_column_types_from_rows
- _record_success / _handle_execution_error
- _map_dbapi_type_to_oid / _map_iris_type_to_oid / _infer_type_from_value / _serialize_value
- _determine_command_tag
- _extract_where_params / _translate_schema_references
- _fetch_with_cursor / _execute_with_new_cursor
- _fetch_last_identity / _get_primary_key_columns / _get_table_columns_from_schema
- _get_column_type_from_schema / _extract_insert_id_from_sql
- _build_metadata_from_description / _make_column_entry / _clean_column_name
- get_iris_type_mapping / has_returning_clause / get_returning_columns
- avg_query_time_ms / error_rate
- set_session_namespace / close_session
- cancel_query
"""

from __future__ import annotations

import asyncio
import datetime as dt
import sys
import types
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers to build connection mocks
# ---------------------------------------------------------------------------


def _make_cursor(
    rows=None,
    description=None,
    rowcount=0,
    side_effect=None,
):
    """Return a mock cursor that behaves like a DBAPI cursor."""
    cursor = MagicMock()
    cursor.description = description
    cursor.rowcount = rowcount
    if side_effect is not None:
        cursor.execute.side_effect = side_effect
    else:
        cursor.execute.return_value = None
    cursor.fetchall.return_value = rows or []
    cursor.fetchone.return_value = rows[0] if rows else None
    cursor.close.return_value = None
    return cursor


def _make_connection(cursor=None, commit_side_effect=None):
    """Return a mock DBAPI connection."""
    conn = MagicMock()
    conn.cursor.return_value = cursor or _make_cursor()
    conn.commit.return_value = None
    if commit_side_effect is not None:
        conn.commit.side_effect = commit_side_effect
    return conn


def _make_conn_wrapper(connection=None, is_healthy=True):
    """Return a mock connection wrapper (DBAPIConnection-like)."""
    wrapper = MagicMock()
    wrapper.connection = connection or _make_connection()
    wrapper.is_healthy = is_healthy
    wrapper.record_query_execution.return_value = None
    wrapper.mark_failed.return_value = None
    return wrapper


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config():
    """Minimal BackendConfig-like object for DBAPIExecutor."""
    cfg = MagicMock()
    cfg.iris_hostname = "localhost"
    cfg.iris_port = 1972
    cfg.iris_namespace = "USER"
    cfg.iris_username = "_SYSTEM"
    cfg.iris_password = "SYS"
    cfg.pool_size = 5
    cfg.pool_max_overflow = 2
    cfg.pool_timeout = 30
    cfg.pool_recycle = 3600
    cfg.query_timeout = 30.0
    cfg.strict_single_connection = False
    cfg.enable_otel = False
    return cfg


@pytest.fixture
def executor(config):
    """DBAPIExecutor with mocked pool, catalog router, and SQL pipeline."""
    from iris_pgwire.dbapi_executor import DBAPIExecutor

    with (
        patch("iris_pgwire.dbapi_executor.IRISConnectionPool") as MockPool,
        patch("iris_pgwire.dbapi_executor.CatalogRouter") as MockCatalog,
        patch("iris_pgwire.dbapi_executor.SQLPipeline") as MockPipeline,
        patch("iris_pgwire.dbapi_executor.get_parser"),
    ):
        mock_pool = MagicMock()
        mock_pool.acquire = AsyncMock()
        mock_pool.release = AsyncMock()
        mock_pool.close = AsyncMock()
        mock_pool.health_check = AsyncMock()
        mock_pool.pool_size = 5
        mock_pool.connections_available = 5
        MockPool.return_value = mock_pool

        mock_catalog = MagicMock()
        mock_catalog.handle_catalog_query = AsyncMock(return_value=None)
        MockCatalog.return_value = mock_catalog

        ex = DBAPIExecutor(config)
        # Expose pool mock for test access
        ex._mock_pool = mock_pool
        ex._mock_catalog = mock_catalog
        return ex


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestInit:
    def test_backend_type(self, executor):
        assert executor.backend_type == "dbapi"

    def test_initial_counters(self, executor):
        assert executor._total_queries == 0
        assert executor._total_query_time_ms == 0.0
        assert executor._total_errors == 0

    def test_session_dicts_empty(self, executor):
        assert executor.session_namespaces == {}
        assert executor.session_connections == {}
        assert executor.session_transactions == {}

    def test_strict_single_connection(self, config):
        from iris_pgwire.dbapi_executor import DBAPIExecutor

        config.strict_single_connection = True
        with (
            patch("iris_pgwire.dbapi_executor.IRISConnectionPool"),
            patch("iris_pgwire.dbapi_executor.CatalogRouter"),
            patch("iris_pgwire.dbapi_executor.SQLPipeline"),
            patch("iris_pgwire.dbapi_executor.get_parser"),
        ):
            ex = DBAPIExecutor(config)
        assert ex.strict_single_connection is True


# ---------------------------------------------------------------------------
# _translate_placeholders
# ---------------------------------------------------------------------------


class TestTranslatePlaceholders:
    def test_single_placeholder(self, executor):
        assert executor._translate_placeholders("SELECT $1") == "SELECT ?"

    def test_multiple_placeholders(self, executor):
        assert executor._translate_placeholders("SELECT $1, $2, $3") == "SELECT ?, ?, ?"

    def test_no_placeholders(self, executor):
        assert executor._translate_placeholders("SELECT 1") == "SELECT 1"

    def test_large_index(self, executor):
        assert executor._translate_placeholders("WHERE id = $10") == "WHERE id = ?"


# ---------------------------------------------------------------------------
# _convert_value_for_iris / _convert_params_for_iris
# ---------------------------------------------------------------------------


class TestConvertValueForIris:
    def test_none(self, executor):
        assert executor._convert_params_for_iris(None) is None

    def test_integer(self, executor):
        assert executor._convert_value_for_iris(42) == 42

    def test_string_passthrough(self, executor):
        assert executor._convert_value_for_iris("hello") == "hello"

    def test_datetime_with_tz(self, executor):
        val = dt.datetime(2024, 1, 15, 10, 30, 0, tzinfo=dt.timezone.utc)
        result = executor._convert_value_for_iris(val)
        assert "2024-01-15" in result
        assert isinstance(result, str)

    def test_datetime_without_tz(self, executor):
        val = dt.datetime(2024, 1, 15, 10, 30, 45, 123456)
        result = executor._convert_value_for_iris(val)
        assert result == "2024-01-15 10:30:45.123456"

    def test_date_value(self, executor):
        val = dt.date(2024, 6, 1)
        result = executor._convert_value_for_iris(val)
        assert result == "2024-06-01"

    def test_params_list(self, executor):
        result = executor._convert_params_for_iris([1, "hello", dt.date(2024, 1, 1)])
        assert result[0] == 1
        assert result[1] == "hello"
        assert result[2] == "2024-01-01"

    def test_params_tuple(self, executor):
        result = executor._convert_params_for_iris((10, 20))
        assert result == [10, 20]


class TestConvertIsoTimestamp:
    def test_plain_date_string(self, executor):
        assert executor._convert_iso_timestamp("not-a-timestamp") == "not-a-timestamp"

    def test_iso_with_z(self, executor):
        result = executor._convert_iso_timestamp("2024-01-15T10:30:00Z")
        assert result == "2024-01-15 10:30:00"

    def test_iso_with_offset(self, executor):
        result = executor._convert_iso_timestamp("2024-01-15T10:30:00+05:30")
        assert "2024-01-15" in result

    def test_iso_space_separator(self, executor):
        result = executor._convert_iso_timestamp("2024-01-15 10:30:00")
        assert result == "2024-01-15 10:30:00"

    def test_iso_with_fractions(self, executor):
        result = executor._convert_iso_timestamp("2024-01-15T10:30:00.123456")
        assert result == "2024-01-15 10:30:00.123456"


# ---------------------------------------------------------------------------
# Type mapping
# ---------------------------------------------------------------------------


class TestMapDbapiTypeToOid:
    def test_int_type(self, executor):
        assert executor._map_dbapi_type_to_oid("INTEGER") == 23

    def test_char_type(self, executor):
        assert executor._map_dbapi_type_to_oid("VARCHAR") == 1043

    def test_string_type(self, executor):
        assert executor._map_dbapi_type_to_oid("STRING") == 1043

    def test_date_type(self, executor):
        assert executor._map_dbapi_type_to_oid("DATE") == 1082

    def test_time_type(self, executor):
        assert executor._map_dbapi_type_to_oid("TIMESTAMP") == 1114

    def test_unknown_type(self, executor):
        assert executor._map_dbapi_type_to_oid("BLOB") == 1043

    def test_int_in_bigint(self, executor):
        assert executor._map_dbapi_type_to_oid("BIGINT") == 23


class TestMapIrisTypeToOid:
    def test_varchar(self, executor):
        assert executor._map_iris_type_to_oid("VARCHAR") == 1043

    def test_varchar_with_length(self, executor):
        assert executor._map_iris_type_to_oid("VARCHAR(255)") == 1043

    def test_integer(self, executor):
        assert executor._map_iris_type_to_oid("INTEGER") == 23

    def test_bigint(self, executor):
        assert executor._map_iris_type_to_oid("BIGINT") == 20

    def test_timestamp(self, executor):
        assert executor._map_iris_type_to_oid("TIMESTAMP") == 1114

    def test_date(self, executor):
        assert executor._map_iris_type_to_oid("DATE") == 1082

    def test_boolean(self, executor):
        assert executor._map_iris_type_to_oid("BOOLEAN") == 16

    def test_unknown(self, executor):
        assert executor._map_iris_type_to_oid("JSONB") == 1043


class TestInferTypeFromValue:
    def test_none_returns_varchar(self, executor):
        assert executor._infer_type_from_value(None) == 1043

    def test_bool(self, executor):
        assert executor._infer_type_from_value(True) == 16

    def test_int(self, executor):
        assert executor._infer_type_from_value(42) == 23

    def test_int_id_column(self, executor):
        assert executor._infer_type_from_value(42, "user_id") == 20

    def test_int_key_column(self, executor):
        assert executor._infer_type_from_value(99, "foreign_key") == 20

    def test_float(self, executor):
        assert executor._infer_type_from_value(3.14) == 701

    def test_decimal(self, executor):
        assert executor._infer_type_from_value(Decimal("10.5")) == 1700

    def test_datetime(self, executor):
        assert executor._infer_type_from_value(dt.datetime(2024, 1, 1)) == 1114

    def test_date(self, executor):
        assert executor._infer_type_from_value(dt.date(2024, 1, 1)) == 1082

    def test_str(self, executor):
        assert executor._infer_type_from_value("hello") == 1043

    def test_unknown_type(self, executor):
        assert executor._infer_type_from_value(b"bytes") == 1043


class TestSerializeValue:
    def test_none(self, executor):
        assert executor._serialize_value(None, 1043) is None

    def test_datetime_with_timestamp_oid(self, executor):
        val = dt.datetime(2024, 6, 1, 12, 0, 0)
        result = executor._serialize_value(val, 1114)
        assert "2024-06-01T12:00:00" in result

    def test_non_datetime_passthrough(self, executor):
        assert executor._serialize_value("hello", 1043) == "hello"

    def test_int_passthrough(self, executor):
        assert executor._serialize_value(42, 23) == 42


# ---------------------------------------------------------------------------
# _determine_command_tag
# ---------------------------------------------------------------------------


class TestDetermineCommandTag:
    def test_select(self, executor):
        assert executor._determine_command_tag("SELECT 1", 1) == "SELECT"

    def test_insert(self, executor):
        assert executor._determine_command_tag("INSERT INTO t VALUES (1)", 1) == "INSERT 0 1"

    def test_update(self, executor):
        assert executor._determine_command_tag("UPDATE t SET x=1", 3) == "UPDATE 3"

    def test_delete(self, executor):
        assert executor._determine_command_tag("DELETE FROM t", 2) == "DELETE 2"

    def test_create(self, executor):
        assert executor._determine_command_tag("CREATE TABLE t (id INT)", 0) == "CREATE"

    def test_empty_sql(self, executor):
        assert executor._determine_command_tag("", 0) == "UNKNOWN"

    def test_lowercase(self, executor):
        assert executor._determine_command_tag("select * from t", 5) == "SELECT"


# ---------------------------------------------------------------------------
# _refine_column_types_from_rows
# ---------------------------------------------------------------------------


class TestRefineColumnTypesFromRows:
    def test_empty_rows(self, executor):
        cols = [{"name": "x", "type_oid": 1043}]
        assert executor._refine_column_types_from_rows(cols, []) == cols

    def test_empty_columns(self, executor):
        assert executor._refine_column_types_from_rows([], [[1, 2]]) == []

    def test_bool_refines_to_16(self, executor):
        cols = [{"name": "flag", "type_oid": 1043}]
        rows = [[True]]
        result = executor._refine_column_types_from_rows(cols, rows)
        assert result[0]["type_oid"] == 16

    def test_int_refines_to_23(self, executor):
        cols = [{"name": "count", "type_oid": 1043}]
        rows = [[42]]
        result = executor._refine_column_types_from_rows(cols, rows)
        assert result[0]["type_oid"] == 23

    def test_float_refines_to_701(self, executor):
        cols = [{"name": "score", "type_oid": 1043}]
        rows = [[3.14]]
        result = executor._refine_column_types_from_rows(cols, rows)
        assert result[0]["type_oid"] == 701

    def test_string_stays_varchar(self, executor):
        cols = [{"name": "name", "type_oid": 1043}]
        rows = [["alice"]]
        result = executor._refine_column_types_from_rows(cols, rows)
        assert result[0]["type_oid"] == 1043

    def test_non_varchar_oid_not_touched(self, executor):
        cols = [{"name": "ts", "type_oid": 1114}]
        rows = [[dt.datetime(2024, 1, 1)]]
        result = executor._refine_column_types_from_rows(cols, rows)
        assert result[0]["type_oid"] == 1114

    def test_multiple_columns(self, executor):
        cols = [
            {"name": "a", "type_oid": 1043},
            {"name": "b", "type_oid": 1043},
        ]
        rows = [[True, "text"]]
        result = executor._refine_column_types_from_rows(cols, rows)
        assert result[0]["type_oid"] == 16
        assert result[1]["type_oid"] == 1043


# ---------------------------------------------------------------------------
# _build_metadata_from_description
# ---------------------------------------------------------------------------


class TestBuildMetadataFromDescription:
    def test_none_description(self, executor):
        assert executor._build_metadata_from_description(None) == []

    def test_empty_description(self, executor):
        assert executor._build_metadata_from_description([]) == []

    def test_basic_column(self, executor):
        desc = [("name", "VARCHAR", 255, None, None, None, None)]
        result = executor._build_metadata_from_description(desc)
        assert len(result) == 1
        assert result[0]["name"] == "name"
        assert result[0]["type_oid"] == 1043
        assert result[0]["format_code"] == 0

    def test_int_column(self, executor):
        desc = [("id", "INTEGER", 4, None, None, None, None)]
        result = executor._build_metadata_from_description(desc)
        assert result[0]["type_oid"] == 23

    def test_minimal_desc(self, executor):
        desc = [("col",)]
        result = executor._build_metadata_from_description(desc)
        assert result[0]["type_oid"] == 1043
        assert result[0]["type_size"] == -1

    def test_skips_none_entries(self, executor):
        desc = [None, ("col", "INTEGER", 4)]
        result = executor._build_metadata_from_description(desc)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _extract_where_params
# ---------------------------------------------------------------------------


class TestExtractWhereParams:
    def test_none_where(self, executor):
        assert executor._extract_where_params(None, [1, 2]) == []

    def test_none_params(self, executor):
        assert executor._extract_where_params("id = ?", None) == []

    def test_single_param(self, executor):
        assert executor._extract_where_params("id = ?", [1, 2, 3]) == [3]

    def test_two_params(self, executor):
        assert executor._extract_where_params("a = ? AND b = ?", [10, 20, 30]) == [20, 30]

    def test_no_placeholders(self, executor):
        assert executor._extract_where_params("id = 1", [1, 2]) == []

    def test_params_fewer_than_needed(self, executor):
        # Falls back to returning all params
        result = executor._extract_where_params("a = ? AND b = ?", [1])
        assert result == [1]


# ---------------------------------------------------------------------------
# _translate_schema_references
# ---------------------------------------------------------------------------


class TestTranslateSchemaReferences:
    def test_quoted_public_schema(self, executor):
        clause = '"public"."mytable"'
        result = executor._translate_schema_references(clause)
        assert '"public"' not in result

    def test_unquoted_public_schema(self, executor):
        clause = "public.\"mytable\""
        result = executor._translate_schema_references(clause)
        assert "public." not in result

    def test_no_schema(self, executor):
        clause = "id = 1"
        assert executor._translate_schema_references(clause) == clause


# ---------------------------------------------------------------------------
# _is_unique_violation
# ---------------------------------------------------------------------------


class TestIsUniqueViolation:
    def test_unique_keyword(self, executor):
        assert executor._is_unique_violation(Exception("unique constraint violation"))

    def test_duplicate_keyword(self, executor):
        assert executor._is_unique_violation(Exception("duplicate key value"))

    def test_constraint_keyword(self, executor):
        assert executor._is_unique_violation(Exception("constraint failed"))

    def test_other_error(self, executor):
        assert not executor._is_unique_violation(Exception("table not found"))


# ---------------------------------------------------------------------------
# _is_transaction_control_sql
# ---------------------------------------------------------------------------


class TestIsTransactionControlSql:
    def test_begin(self, executor):
        assert executor._is_transaction_control_sql("BEGIN")

    def test_start_transaction(self, executor):
        assert executor._is_transaction_control_sql("START TRANSACTION")

    def test_commit(self, executor):
        assert executor._is_transaction_control_sql("COMMIT")

    def test_rollback(self, executor):
        assert executor._is_transaction_control_sql("ROLLBACK")

    def test_end(self, executor):
        assert executor._is_transaction_control_sql("END")

    def test_select(self, executor):
        assert not executor._is_transaction_control_sql("SELECT 1")

    def test_none(self, executor):
        assert not executor._is_transaction_control_sql(None)


# ---------------------------------------------------------------------------
# _update_transaction_state
# ---------------------------------------------------------------------------


class TestUpdateTransactionState:
    def test_begin_sets_transaction(self, executor):
        executor._update_transaction_state("sess1", "BEGIN")
        assert executor.session_transactions.get("sess1") is True

    def test_start_transaction_sets_transaction(self, executor):
        executor._update_transaction_state("sess1", "START TRANSACTION")
        assert executor.session_transactions.get("sess1") is True

    def test_commit_removes_transaction(self, executor):
        executor.session_transactions["sess1"] = True
        executor._update_transaction_state("sess1", "COMMIT")
        assert "sess1" not in executor.session_transactions

    def test_rollback_removes_transaction(self, executor):
        executor.session_transactions["sess1"] = True
        executor._update_transaction_state("sess1", "ROLLBACK")
        assert "sess1" not in executor.session_transactions

    def test_no_session_no_op(self, executor):
        executor._update_transaction_state(None, "BEGIN")
        assert executor.session_transactions == {}

    def test_none_sql_no_op(self, executor):
        executor._update_transaction_state("sess1", None)
        assert executor.session_transactions == {}


# ---------------------------------------------------------------------------
# _maybe_auto_commit
# ---------------------------------------------------------------------------


class TestMaybeAutoCommit:
    def test_commits_for_dml(self, executor):
        conn = _make_connection()
        executor._maybe_auto_commit(conn, None, "INSERT INTO t VALUES (1)")
        conn.commit.assert_called_once()

    def test_no_commit_for_transaction_control(self, executor):
        conn = _make_connection()
        executor._maybe_auto_commit(conn, None, "BEGIN")
        conn.commit.assert_not_called()

    def test_no_commit_when_in_transaction(self, executor):
        executor.session_transactions["sess1"] = True
        conn = _make_connection()
        executor._maybe_auto_commit(conn, "sess1", "INSERT INTO t VALUES (1)")
        conn.commit.assert_not_called()

    def test_no_conn(self, executor):
        # Should not raise
        executor._maybe_auto_commit(None, None, "SELECT 1")

    def test_no_sql(self, executor):
        conn = _make_connection()
        executor._maybe_auto_commit(conn, None, None)
        conn.commit.assert_not_called()


# ---------------------------------------------------------------------------
# _acquire_connection
# ---------------------------------------------------------------------------


class TestAcquireConnection:
    async def test_acquires_new_from_pool(self, executor):
        wrapper = _make_conn_wrapper()
        executor.pool.acquire = AsyncMock(return_value=wrapper)
        conn, pinned = await executor._acquire_connection(None)
        assert conn is wrapper
        assert pinned is False

    async def test_session_without_existing_creates_and_pins(self, executor):
        wrapper = _make_conn_wrapper()
        executor.pool.acquire = AsyncMock(return_value=wrapper)
        conn, pinned = await executor._acquire_connection("sess1")
        assert conn is wrapper
        assert pinned is True
        assert executor.session_connections["sess1"] is wrapper

    async def test_returns_existing_session_connection(self, executor):
        wrapper = _make_conn_wrapper()
        executor.session_connections["sess1"] = wrapper
        conn, pinned = await executor._acquire_connection("sess1")
        assert conn is wrapper
        assert pinned is True
        executor.pool.acquire.assert_not_called()


# ---------------------------------------------------------------------------
# _fetch_standard_results
# ---------------------------------------------------------------------------


class TestFetchStandardResults:
    def test_no_description(self, executor):
        cursor = _make_cursor(description=None)
        rows, cols = executor._fetch_standard_results(cursor)
        assert rows == []
        assert cols == []

    def test_with_rows(self, executor):
        desc = [("id", "INTEGER", 4)]
        cursor = _make_cursor(rows=[(1,), (2,)], description=desc)
        rows, cols = executor._fetch_standard_results(cursor)
        assert rows == [(1,), (2,)]
        assert cols[0]["name"] == "id"

    def test_refines_types_from_rows(self, executor):
        desc = [("value", "VARCHAR", 255)]
        cursor = _make_cursor(rows=[(42,)], description=desc)
        rows, cols = executor._fetch_standard_results(cursor)
        # Should refine from VARCHAR (1043) to INT (23) based on value
        assert cols[0]["type_oid"] == 23


# ---------------------------------------------------------------------------
# _fetch_with_cursor
# ---------------------------------------------------------------------------


class TestFetchWithCursor:
    def test_basic_select(self, executor):
        desc = [("id", "INTEGER", 4)]
        cursor = _make_cursor(rows=[(1,)], description=desc)
        conn = _make_connection(cursor=cursor)
        rows, cols = executor._fetch_with_cursor(conn, "SELECT id FROM t")
        assert rows == [(1,)]
        assert cols[0]["name"] == "id"

    def test_with_params(self, executor):
        desc = [("id", "INTEGER", 4)]
        cursor = _make_cursor(rows=[(5,)], description=desc)
        conn = _make_connection(cursor=cursor)
        rows, cols = executor._fetch_with_cursor(conn, "SELECT id FROM t WHERE id = ?", [5])
        cursor.execute.assert_called_once_with("SELECT id FROM t WHERE id = ?", (5,))

    def test_cursor_close_on_exception(self, executor):
        cursor = _make_cursor(side_effect=Exception("DB error"))
        conn = _make_connection(cursor=cursor)
        with pytest.raises(Exception, match="DB error"):
            executor._fetch_with_cursor(conn, "SELECT 1")
        cursor.close.assert_called_once()

    def test_empty_result(self, executor):
        cursor = _make_cursor(rows=[], description=None)
        conn = _make_connection(cursor=cursor)
        rows, cols = executor._fetch_with_cursor(conn, "SELECT id FROM t WHERE 1=0")
        assert rows == []
        assert cols == []


# ---------------------------------------------------------------------------
# _execute_with_new_cursor
# ---------------------------------------------------------------------------


class TestExecuteWithNewCursor:
    def test_executes_with_params(self, executor):
        cursor = _make_cursor()
        conn = _make_connection(cursor=cursor)
        executor._execute_with_new_cursor(conn, "UPDATE t SET x=?", (1,))
        cursor.execute.assert_called_once_with("UPDATE t SET x=?", (1,))

    def test_executes_without_params(self, executor):
        cursor = _make_cursor()
        conn = _make_connection(cursor=cursor)
        executor._execute_with_new_cursor(conn, "DROP TABLE t")
        cursor.execute.assert_called_once_with("DROP TABLE t")

    def test_cursor_closes_even_on_error(self, executor):
        cursor = _make_cursor(side_effect=Exception("fail"))
        conn = _make_connection(cursor=cursor)
        with pytest.raises(Exception, match="fail"):
            executor._execute_with_new_cursor(conn, "BAD SQL")
        cursor.close.assert_called_once()


# ---------------------------------------------------------------------------
# _fetch_last_identity
# ---------------------------------------------------------------------------


class TestFetchLastIdentity:
    def test_returns_identity(self, executor):
        cursor = _make_cursor(rows=[(42,)])
        conn = _make_connection(cursor=cursor)
        assert executor._fetch_last_identity(conn) == 42

    def test_no_row(self, executor):
        cursor = _make_cursor(rows=[])
        conn = _make_connection(cursor=cursor)
        assert executor._fetch_last_identity(conn) is None

    def test_null_connection(self, executor):
        assert executor._fetch_last_identity(None) is None

    def test_exception_returns_none(self, executor):
        cursor = _make_cursor(side_effect=Exception("not supported"))
        conn = _make_connection(cursor=cursor)
        result = executor._fetch_last_identity(conn)
        assert result is None


# ---------------------------------------------------------------------------
# _get_primary_key_columns
# ---------------------------------------------------------------------------


class TestGetPrimaryKeyColumns:
    def test_returns_columns(self, executor):
        cursor = _make_cursor(rows=[("ID",), ("TENANT_ID",)])
        conn = _make_connection(cursor=cursor)
        result = executor._get_primary_key_columns("USERS", conn)
        assert result == ["ID", "TENANT_ID"]

    def test_empty_table(self, executor):
        assert executor._get_primary_key_columns("", None) == []

    def test_exception_returns_empty(self, executor):
        cursor = _make_cursor(side_effect=Exception("schema query failed"))
        conn = _make_connection(cursor=cursor)
        result = executor._get_primary_key_columns("USERS", conn)
        assert result == []


# ---------------------------------------------------------------------------
# _get_table_columns_from_schema
# ---------------------------------------------------------------------------


class TestGetTableColumnsFromSchema:
    def test_strict_single_connection_returns_empty(self, executor):
        executor.strict_single_connection = True
        result = executor._get_table_columns_from_schema("MYTABLE")
        assert result == []

    def test_no_cursor_returns_empty(self, executor):
        result = executor._get_table_columns_from_schema("MYTABLE", cursor=None)
        assert result == []

    def test_returns_columns(self, executor):
        cursor = _make_cursor(rows=[("ID",), ("NAME",), ("EMAIL",)])
        result = executor._get_table_columns_from_schema("USERS", cursor=cursor)
        assert result == ["ID", "NAME", "EMAIL"]

    def test_exception_returns_empty(self, executor):
        cursor = _make_cursor(side_effect=Exception("schema error"))
        result = executor._get_table_columns_from_schema("USERS", cursor=cursor)
        assert result == []


# ---------------------------------------------------------------------------
# _get_column_type_from_schema
# ---------------------------------------------------------------------------


class TestGetColumnTypeFromSchema:
    def test_strict_single_connection_returns_none(self, executor):
        executor.strict_single_connection = True
        result = executor._get_column_type_from_schema("t", "col")
        assert result is None

    def test_no_cursor_returns_none(self, executor):
        result = executor._get_column_type_from_schema("t", "col", cursor=None)
        assert result is None

    def test_returns_oid(self, executor):
        cursor = _make_cursor(rows=[("INTEGER",)])
        result = executor._get_column_type_from_schema("T", "ID", cursor=cursor)
        assert result == 23  # INTEGER OID

    def test_no_row_returns_none(self, executor):
        cursor = _make_cursor(rows=[])
        result = executor._get_column_type_from_schema("T", "ID", cursor=cursor)
        assert result is None

    def test_exception_returns_none(self, executor):
        cursor = _make_cursor(side_effect=Exception("schema error"))
        result = executor._get_column_type_from_schema("T", "ID", cursor=cursor)
        assert result is None


# ---------------------------------------------------------------------------
# _extract_insert_id_from_sql
# ---------------------------------------------------------------------------


class TestExtractInsertIdFromSql:
    def test_finds_id_column(self, executor):
        sql = "INSERT INTO users (id, name) VALUES (?, ?)"
        col, val = executor._extract_insert_id_from_sql(sql, [42, "alice"])
        assert col == "ID"
        assert val == 42

    def test_finds_uuid_column(self, executor):
        sql = "INSERT INTO items (uuid, label) VALUES (?, ?)"
        col, val = executor._extract_insert_id_from_sql(sql, ["abc-123", "item1"])
        assert col == "UUID"
        assert val == "abc-123"

    def test_no_id_column(self, executor):
        sql = "INSERT INTO t (name, value) VALUES (?, ?)"
        col, val = executor._extract_insert_id_from_sql(sql, ["x", 1])
        assert col is None
        assert val is None

    def test_no_match(self, executor):
        sql = "SELECT 1"
        col, val = executor._extract_insert_id_from_sql(sql, [])
        assert col is None

    def test_id_column_but_no_params(self, executor):
        sql = "INSERT INTO t (id, name) VALUES (?, ?)"
        col, val = executor._extract_insert_id_from_sql(sql, [])
        assert col is None
        assert val is None


# ---------------------------------------------------------------------------
# _map_insert_column_values
# ---------------------------------------------------------------------------


class TestMapInsertColumnValues:
    def test_basic_mapping(self, executor):
        from iris_pgwire.sql_translator.returning_plan import ReturningPlan

        plan = ReturningPlan.from_sql(
            "INSERT INTO users (id, name, email) VALUES (?, ?, ?) RETURNING id"
        )
        result = executor._map_insert_column_values(plan, [1, "alice", "a@b.com"])
        assert result.get("id") == 1
        assert result.get("name") == "alice"

    def test_no_params(self, executor):
        from iris_pgwire.sql_translator.returning_plan import ReturningPlan

        plan = ReturningPlan.from_sql(
            "INSERT INTO users (id, name) VALUES (?, ?) RETURNING id"
        )
        result = executor._map_insert_column_values(plan, None)
        assert result == {}


# ---------------------------------------------------------------------------
# has_returning_clause / get_returning_columns
# ---------------------------------------------------------------------------


class TestReturningHelpers:
    def test_has_returning_true(self, executor):
        assert executor.has_returning_clause("INSERT INTO t VALUES (1) RETURNING id")

    def test_has_returning_false(self, executor):
        assert not executor.has_returning_clause("INSERT INTO t VALUES (1)")

    def test_has_returning_empty(self, executor):
        assert not executor.has_returning_clause("")

    def test_get_returning_columns_single(self, executor):
        cols = executor.get_returning_columns("INSERT INTO t VALUES (1) RETURNING id")
        assert cols == ["id"]

    def test_get_returning_columns_multiple(self, executor):
        cols = executor.get_returning_columns("INSERT INTO t VALUES (1) RETURNING id, name")
        assert "id" in cols
        assert "name" in cols

    def test_get_returning_columns_star(self, executor):
        cols = executor.get_returning_columns("INSERT INTO t VALUES (1) RETURNING *")
        assert cols == ["*"]

    def test_get_returning_columns_no_match(self, executor):
        cols = executor.get_returning_columns("SELECT 1")
        assert cols == []


# ---------------------------------------------------------------------------
# get_iris_type_mapping
# ---------------------------------------------------------------------------


class TestGetIrisTypeMapping:
    def test_returns_dict(self, executor):
        mapping = executor.get_iris_type_mapping()
        assert isinstance(mapping, dict)
        assert "VARCHAR" in mapping
        assert "INTEGER" in mapping

    def test_varchar_oid(self, executor):
        assert executor.get_iris_type_mapping()["VARCHAR"]["oid"] == 1043

    def test_bigint_oid(self, executor):
        assert executor.get_iris_type_mapping()["BIGINT"]["oid"] == 20


# ---------------------------------------------------------------------------
# avg_query_time_ms / error_rate
# ---------------------------------------------------------------------------


class TestMetrics:
    def test_avg_query_time_no_queries(self, executor):
        assert executor.avg_query_time_ms() is None

    def test_avg_query_time_with_queries(self, executor):
        executor._total_queries = 2
        executor._total_query_time_ms = 100.0
        assert executor.avg_query_time_ms() == 50.0

    def test_error_rate_no_queries(self, executor):
        assert executor.error_rate() == 0.0

    def test_error_rate_with_errors(self, executor):
        executor._total_queries = 10
        executor._total_errors = 2
        assert executor.error_rate() == 20.0


# ---------------------------------------------------------------------------
# set_session_namespace / close_session
# ---------------------------------------------------------------------------


class TestSessionManagement:
    def test_set_session_namespace(self, executor):
        executor.set_session_namespace("sess1", "MYNS")
        assert executor.session_namespaces["sess1"] == "MYNS"

    async def test_close_session_with_connection(self, executor):
        wrapper = _make_conn_wrapper()
        executor.session_connections["sess1"] = wrapper
        executor.session_namespaces["sess1"] = "NS"
        executor.session_transactions["sess1"] = True
        executor.pool.release = AsyncMock()

        await executor.close_session("sess1")

        assert "sess1" not in executor.session_connections
        assert "sess1" not in executor.session_namespaces
        assert "sess1" not in executor.session_transactions
        executor.pool.release.assert_called_once_with(wrapper)

    async def test_close_session_without_connection(self, executor):
        executor.pool.release = AsyncMock()
        await executor.close_session("nonexistent")
        executor.pool.release.assert_not_called()


# ---------------------------------------------------------------------------
# cancel_query
# ---------------------------------------------------------------------------


class TestCancelQuery:
    async def test_returns_false(self, executor):
        result = await executor.cancel_query(1234, 5678)
        assert result is False


# ---------------------------------------------------------------------------
# _record_success
# ---------------------------------------------------------------------------


class TestRecordSuccess:
    def test_increments_counters(self, executor):
        wrapper = _make_conn_wrapper()
        executor._record_success(wrapper, 25.0)
        assert executor._total_queries == 1
        assert executor._total_query_time_ms == 25.0
        wrapper.record_query_execution.assert_called_once_with(
            acquisition_time_ms=25.0, success=True
        )


# ---------------------------------------------------------------------------
# _handle_execution_error
# ---------------------------------------------------------------------------


class TestHandleExecutionError:
    def test_increments_error_counter(self, executor):
        executor._handle_execution_error(
            Exception("some error"), None, None, "SELECT 1", "Query"
        )
        assert executor._total_errors == 1

    def test_connection_lost_marks_failed(self, executor):
        wrapper = _make_conn_wrapper()
        executor.session_connections["sess1"] = wrapper
        executor.session_transactions["sess1"] = True

        executor._handle_execution_error(
            Exception("connection lost"),
            wrapper,
            "sess1",
            "SELECT 1",
            "Query",
        )

        wrapper.mark_failed.assert_called_once()
        assert "sess1" not in executor.session_connections
        assert "sess1" not in executor.session_transactions

    def test_non_connection_error_records_failure(self, executor):
        wrapper = _make_conn_wrapper()
        executor._handle_execution_error(
            Exception("syntax error"), wrapper, None, "BAD SQL", "Query"
        )
        wrapper.record_query_execution.assert_called_once_with(
            acquisition_time_ms=0, success=False
        )


# ---------------------------------------------------------------------------
# execute_query (async, mocked)
# ---------------------------------------------------------------------------


class TestExecuteQuery:
    async def test_happy_path_select(self, executor):
        desc = [("id", "INTEGER", 4)]
        cursor = _make_cursor(rows=[(1,)], description=desc, rowcount=1)
        conn = _make_connection(cursor=cursor)
        wrapper = _make_conn_wrapper(connection=conn)

        executor.pool.acquire = AsyncMock(return_value=wrapper)
        executor.pool.release = AsyncMock()
        executor._mock_catalog.handle_catalog_query = AsyncMock(return_value=None)

        result = await executor.execute_query("SELECT id FROM t")

        assert result["success"] is True
        assert result["rows"] == [(1,)]
        assert result["command_tag"] == "SELECT"
        executor.pool.release.assert_called_once_with(wrapper)

    async def test_catalog_short_circuit(self, executor):
        catalog_result = {"success": True, "rows": [("catalog",)], "columns": []}
        executor._mock_catalog.handle_catalog_query = AsyncMock(return_value=catalog_result)

        result = await executor.execute_query("SELECT version()")
        assert result == catalog_result
        # Pool should NOT be used
        executor.pool.acquire.assert_not_called()

    async def test_query_with_params(self, executor):
        desc = [("id", "INTEGER", 4)]
        cursor = _make_cursor(rows=[(5,)], description=desc, rowcount=1)
        conn = _make_connection(cursor=cursor)
        wrapper = _make_conn_wrapper(connection=conn)

        executor.pool.acquire = AsyncMock(return_value=wrapper)
        executor.pool.release = AsyncMock()
        executor._mock_catalog.handle_catalog_query = AsyncMock(return_value=None)

        result = await executor.execute_query("SELECT id FROM t WHERE id = $1", params=(5,))
        assert result["success"] is True

    async def test_timeout_raises_runtime_error(self, executor):
        import asyncio as _asyncio

        executor._mock_catalog.handle_catalog_query = AsyncMock(return_value=None)
        wrapper = _make_conn_wrapper()
        executor.pool.acquire = AsyncMock(return_value=wrapper)
        executor.pool.release = AsyncMock()
        executor.config.query_timeout = 0.001  # 1ms timeout to force timeout

        # Make execute_in_thread block indefinitely
        async def slow_thread_mock(fn, **_kw):
            raise _asyncio.TimeoutError()

        with patch("asyncio.wait_for", side_effect=_asyncio.TimeoutError()):
            with pytest.raises(RuntimeError, match="timed out"):
                await executor.execute_query("SELECT SLEEP(1)")

        assert wrapper.is_healthy is False

    async def test_error_propagates(self, executor):
        executor._mock_catalog.handle_catalog_query = AsyncMock(return_value=None)
        cursor = _make_cursor(side_effect=Exception("syntax error"))
        conn = _make_connection(cursor=cursor)
        wrapper = _make_conn_wrapper(connection=conn)
        executor.pool.acquire = AsyncMock(return_value=wrapper)
        executor.pool.release = AsyncMock()

        with pytest.raises(Exception, match="syntax error"):
            await executor.execute_query("BAD SQL")

        assert executor._total_errors == 1

    async def test_session_connection_not_released(self, executor):
        """Pinned session connections should NOT be released back to pool."""
        desc = [("id", "INTEGER", 4)]
        cursor = _make_cursor(rows=[(1,)], description=desc, rowcount=1)
        conn = _make_connection(cursor=cursor)
        wrapper = _make_conn_wrapper(connection=conn)
        executor.session_connections["sess1"] = wrapper

        executor._mock_catalog.handle_catalog_query = AsyncMock(return_value=None)
        executor.pool.release = AsyncMock()

        await executor.execute_query("SELECT 1", session_id="sess1")
        executor.pool.release.assert_not_called()


# ---------------------------------------------------------------------------
# execute_many (async, mocked)
# ---------------------------------------------------------------------------


class TestExecuteMany:
    async def test_basic_execute_many(self, executor):
        desc = [("id", "INTEGER", 4)]
        cursor = _make_cursor(rows=[(1,)], description=desc, rowcount=1)
        conn = _make_connection(cursor=cursor)
        wrapper = _make_conn_wrapper(connection=conn)

        executor.pool.acquire = AsyncMock(return_value=wrapper)
        executor.pool.release = AsyncMock()

        result = await executor.execute_many(
            "INSERT INTO t (id) VALUES ($1)",
            params_list=[(1,), (2,), (3,)],
        )
        assert result["success"] is True
        assert result["batch_size"] == 3

    async def test_execute_many_error(self, executor):
        cursor = _make_cursor(side_effect=Exception("batch error"))
        conn = _make_connection(cursor=cursor)
        wrapper = _make_conn_wrapper(connection=conn)

        executor.pool.acquire = AsyncMock(return_value=wrapper)
        executor.pool.release = AsyncMock()

        with pytest.raises(Exception, match="batch error"):
            await executor.execute_many(
                "INSERT INTO t (id) VALUES ($1)",
                params_list=[(1,)],
            )


# ---------------------------------------------------------------------------
# _execute_with_cursor — conflict handling
# ---------------------------------------------------------------------------


class TestExecuteWithCursorConflict:
    def test_do_nothing_on_unique_violation(self, executor):
        from iris_pgwire.sql_translator.returning_plan import ReturningPlan

        plan = ReturningPlan.from_sql(
            "INSERT INTO t (id, val) VALUES (?, ?) ON CONFLICT (id) DO NOTHING"
        )
        cursor = _make_cursor(side_effect=Exception("unique constraint violation"))
        conn = _make_connection(cursor=cursor)

        rows, cols, count = executor._execute_with_cursor(cursor, conn, plan, [1, "x"], None, None)
        assert rows == []
        assert count == 0

    def test_non_conflict_error_raises(self, executor):
        from iris_pgwire.sql_translator.returning_plan import ReturningPlan

        plan = ReturningPlan.from_sql("INSERT INTO t (id) VALUES (?)")
        cursor = _make_cursor(side_effect=Exception("table not found"))
        conn = _make_connection(cursor=cursor)

        with pytest.raises(Exception, match="table not found"):
            executor._execute_with_cursor(cursor, conn, plan, [1], None, None)


# ---------------------------------------------------------------------------
# _clean_column_name / _make_column_entry
# ---------------------------------------------------------------------------


class TestStaticHelpers:
    def test_clean_column_name_strips_quotes(self, executor):
        assert executor._clean_column_name('"myCol"') == "myCol"

    def test_clean_column_name_table_qualified(self, executor):
        assert executor._clean_column_name("public.myCol") == "myCol"

    def test_make_column_entry(self):
        from iris_pgwire.dbapi_executor import DBAPIExecutor

        entry = DBAPIExecutor._make_column_entry("id", 23)
        assert entry["name"] == "id"
        assert entry["type_oid"] == 23
        assert entry["format_code"] == 0
        assert entry["type_size"] == -1


# ---------------------------------------------------------------------------
# _prepare_conflict_set_clause / _prepare_conflict_where_clause
# ---------------------------------------------------------------------------


class TestConflictClauses:
    def test_set_clause_replaces_excluded(self, executor):
        from iris_pgwire.sql_translator.returning_plan import ReturningPlan

        plan = ReturningPlan.from_sql(
            "INSERT INTO t (id, val) VALUES (?, ?) ON CONFLICT (id) DO UPDATE SET val = EXCLUDED.val"
        )
        col_vals = {"id": 1, "val": "new_val"}
        clause, params = executor._prepare_conflict_set_clause(plan, col_vals)
        assert "?" in clause
        assert "new_val" in params

    def test_where_clause_builds_correctly(self, executor):
        from iris_pgwire.sql_translator.returning_plan import ReturningPlan

        plan = ReturningPlan.from_sql(
            "INSERT INTO t (id, val) VALUES (?, ?) ON CONFLICT (id) DO UPDATE SET val = EXCLUDED.val"
        )
        col_vals = {"id": 99, "val": "x"}
        clause, params = executor._prepare_conflict_where_clause(plan, col_vals)
        assert '"ID" = ?' in clause
        assert 99 in params

    def test_empty_set_clause_when_no_conflict(self, executor):
        from iris_pgwire.sql_translator.returning_plan import ReturningPlan

        plan = ReturningPlan.from_sql("INSERT INTO t (id) VALUES (?)")
        clause, params = executor._prepare_conflict_set_clause(plan, {})
        assert clause == ""
        assert params == []


# ---------------------------------------------------------------------------
# close (async)
# ---------------------------------------------------------------------------


class TestClose:
    async def test_close_calls_pool_close(self, executor):
        executor.pool.close = AsyncMock()
        await executor.close()
        executor.pool.close.assert_called_once()

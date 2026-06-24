"""
Unit tests for iris_pgwire.iris_executor.IRISExecutor

Strategy: mock the `iris` module via sys.modules injection so we can test
all code paths without a real IRIS connection.

Coverage targets:
- MockResult
- IRISExecutor.__init__ (both embedded and non-embedded)
- _normalize_iris_null
- _normalize_parameters
- _infer_type_from_value
- _serialize_value
- _postprocess_rows
- _detect_cast_type_oid
- has_returning_clause / get_returning_columns
- _extract_table_name
- _split_multi_row_insert
- _is_unique_violation
- _map_insert_column_values
- test_connection (embedded and external)
- _test_vector_support (embedded and external)
- close
- set_session_namespace / _get_session_namespace
- _get_executor (with and without session_id)
- execute_query (embedded and external paths)
- _execute_embedded_async
- _split_sql_statements
- _determine_command_tag (via execute)
- _discover_metadata layers
- _materialize_embedded_result
"""

from __future__ import annotations

import asyncio
import datetime as dt
import sys
import types
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, Mock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# Build and inject fake iris module BEFORE importing iris_executor
# ---------------------------------------------------------------------------

def _make_iris_mock(embedded: bool = True):
    """Return a MagicMock that looks like the iris module."""
    iris_mod = MagicMock()
    if embedded:
        # Embedded: iris.sql.exec exists
        iris_mod.sql = MagicMock()
        iris_mod.sql.exec = MagicMock(return_value=iter([]))
        iris_mod.system = MagicMock()
        iris_mod.system.Process = MagicMock()
        iris_mod.system.Process.SetNamespace = MagicMock()
    else:
        # External: iris.sql exists but has no exec attribute
        del iris_mod.sql
    return iris_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def iris_mock():
    """Embedded iris mock in sys.modules for the duration of the test."""
    mock = _make_iris_mock(embedded=True)
    sys.modules["iris"] = mock
    yield mock
    # Restore
    sys.modules.pop("iris", None)


@pytest.fixture
def executor_embedded(iris_mock):
    """IRISExecutor in embedded mode, fully constructed."""
    from iris_pgwire.iris_executor import IRISExecutor

    config = {
        "host": "localhost",
        "port": 1972,
        "namespace": "USER",
        "username": "SuperUser",
        "password": "SYS",
    }
    ex = IRISExecutor(config)
    # Force embedded mode (detection may not fire correctly outside docker)
    ex.embedded_mode = True
    return ex


@pytest.fixture
def executor_external():
    """IRISExecutor in external (non-embedded) mode."""
    # Ensure iris is NOT in sys.modules or has no sql.exec
    sys.modules.pop("iris", None)
    from iris_pgwire.iris_executor import IRISExecutor

    config = {
        "host": "localhost",
        "port": 1972,
        "namespace": "USER",
        "username": "SuperUser",
        "password": "SYS",
    }
    ex = IRISExecutor(config)
    ex.embedded_mode = False
    return ex


# ---------------------------------------------------------------------------
# MockResult tests
# ---------------------------------------------------------------------------

class TestMockResult:
    def test_init_sets_attributes(self):
        from iris_pgwire.iris_executor import MockResult
        rows = [[1, "a"], [2, "b"]]
        meta = [{"name": "id"}, {"name": "val"}]
        r = MockResult(rows, meta)
        assert r.rowcount == 2
        assert r.description is meta
        assert r._meta is meta

    def test_none_rows_becomes_empty_list(self):
        from iris_pgwire.iris_executor import MockResult
        r = MockResult(None)
        assert r._rows == []
        assert r.rowcount == 0

    def test_iter(self):
        from iris_pgwire.iris_executor import MockResult
        rows = [[1], [2], [3]]
        r = MockResult(rows)
        assert list(r) == rows

    def test_fetchall(self):
        from iris_pgwire.iris_executor import MockResult
        rows = [[1, 2]]
        r = MockResult(rows)
        assert r.fetchall() == rows

    def test_fetchone_sequential(self):
        from iris_pgwire.iris_executor import MockResult
        rows = [[1], [2]]
        r = MockResult(rows)
        assert r.fetchone() == [1]
        assert r.fetchone() == [2]
        assert r.fetchone() is None

    def test_fetch(self):
        from iris_pgwire.iris_executor import MockResult
        rows = [[10]]
        r = MockResult(rows)
        assert r.fetch() == rows

    def test_close_noop(self):
        from iris_pgwire.iris_executor import MockResult
        r = MockResult([])
        r.close()  # should not raise


# ---------------------------------------------------------------------------
# _normalize_iris_null
# ---------------------------------------------------------------------------

class TestNormalizeIrisNull:
    def test_none_returns_none(self, executor_embedded):
        assert executor_embedded._normalize_iris_null(None) is None

    def test_empty_string_returns_none(self, executor_embedded):
        assert executor_embedded._normalize_iris_null("") is None

    def test_sys_python_marker_returns_none(self, executor_embedded):
        assert executor_embedded._normalize_iris_null("13@%SYS.Python") is None

    def test_regular_string_preserved(self, executor_embedded):
        assert executor_embedded._normalize_iris_null("hello") == "hello"

    def test_integer_preserved(self, executor_embedded):
        assert executor_embedded._normalize_iris_null(42) == 42

    def test_zero_preserved(self, executor_embedded):
        assert executor_embedded._normalize_iris_null(0) == 0

    def test_list_preserved(self, executor_embedded):
        v = [1, 2, 3]
        assert executor_embedded._normalize_iris_null(v) is v


# ---------------------------------------------------------------------------
# _normalize_parameters
# ---------------------------------------------------------------------------

class TestNormalizeParameters:
    def test_none_params_returns_empty(self, executor_embedded):
        assert executor_embedded._normalize_parameters(None) == []

    def test_empty_list_returns_empty(self, executor_embedded):
        assert executor_embedded._normalize_parameters([]) == []

    def test_datetime_with_tz_converted(self, executor_embedded):
        tz = dt.timezone(dt.timedelta(hours=5))
        val = dt.datetime(2023, 6, 15, 12, 0, 0, tzinfo=tz)
        result = executor_embedded._normalize_parameters([val])
        # Should be normalized to UTC string
        assert isinstance(result[0], str)
        assert "T" not in result[0]  # space separator
        assert "07:00:00" in result[0]  # 12:00 UTC+5 = 07:00 UTC

    def test_datetime_naive_formatted(self, executor_embedded):
        val = dt.datetime(2023, 1, 15, 10, 30, 0)
        result = executor_embedded._normalize_parameters([val])
        assert result[0] == "2023-01-15 10:30:00.000000"

    def test_date_formatted(self, executor_embedded):
        val = dt.date(2023, 6, 15)
        result = executor_embedded._normalize_parameters([val])
        assert result[0] == "2023-06-15"

    def test_timestamp_int_in_range_converted(self, executor_embedded):
        # Build an int in MIN_TIMESTAMP < x < MAX_TIMESTAMP range
        val = 600_000_000_000_000  # in range
        result = executor_embedded._normalize_parameters([val])
        assert isinstance(result[0], str)

    def test_int_out_of_range_unchanged(self, executor_embedded):
        val = 42
        result = executor_embedded._normalize_parameters([val])
        assert result[0] == 42

    def test_iso_timestamp_with_z_normalized(self, executor_embedded):
        result = executor_embedded._normalize_parameters(["2023-06-15T12:30:00Z"])
        assert result[0] == "2023-06-15 12:30:00"

    def test_iso_timestamp_with_offset_converted(self, executor_embedded):
        result = executor_embedded._normalize_parameters(["2023-06-15T12:30:00+05:00"])
        assert result[0] == "2023-06-15 07:30:00"

    def test_list_param_converted_to_vector_string(self, executor_embedded):
        result = executor_embedded._normalize_parameters([[1.0, 2.0, 3.0]])
        assert result[0] == "[1.0,2.0,3.0]"

    def test_non_timestamp_string_unchanged(self, executor_embedded):
        result = executor_embedded._normalize_parameters(["hello world"])
        assert result[0] == "hello world"

    def test_mixed_params(self, executor_embedded):
        params = [42, "hello", dt.date(2023, 1, 1)]
        result = executor_embedded._normalize_parameters(params)
        assert result[0] == 42
        assert result[1] == "hello"
        assert result[2] == "2023-01-01"


# ---------------------------------------------------------------------------
# _infer_type_from_value
# ---------------------------------------------------------------------------

class TestInferTypeFromValue:
    def test_none_returns_varchar(self, executor_embedded):
        assert executor_embedded._infer_type_from_value(None) == 1043

    def test_bool_returns_bool_oid(self, executor_embedded):
        assert executor_embedded._infer_type_from_value(True) == 16

    def test_int_small_returns_int4(self, executor_embedded):
        assert executor_embedded._infer_type_from_value(100) == 23

    def test_int_large_returns_int8(self, executor_embedded):
        assert executor_embedded._infer_type_from_value(3_000_000_000) == 20

    def test_int_id_column_returns_bigint(self, executor_embedded):
        assert executor_embedded._infer_type_from_value(1, "user_id") == 20

    def test_posixtime_int_returns_timestamp(self, executor_embedded):
        from iris_pgwire.iris_executor import POSIXTIME_OFFSET
        val = POSIXTIME_OFFSET + 1000
        assert executor_embedded._infer_type_from_value(val) == 1114

    def test_float_returns_float8(self, executor_embedded):
        assert executor_embedded._infer_type_from_value(3.14) == 701

    def test_decimal_returns_numeric(self, executor_embedded):
        assert executor_embedded._infer_type_from_value(Decimal("3.14")) == 1700

    def test_bytes_returns_bytea(self, executor_embedded):
        assert executor_embedded._infer_type_from_value(b"data") == 17

    def test_datetime_returns_timestamp(self, executor_embedded):
        assert executor_embedded._infer_type_from_value(dt.datetime(2023, 1, 1)) == 1114

    def test_date_returns_date(self, executor_embedded):
        assert executor_embedded._infer_type_from_value(dt.date(2023, 1, 1)) == 1082

    def test_string_returns_varchar(self, executor_embedded):
        assert executor_embedded._infer_type_from_value("hello") == 1043

    def test_unknown_type_returns_varchar(self, executor_embedded):
        class Weird:
            pass
        assert executor_embedded._infer_type_from_value(Weird()) == 1043


# ---------------------------------------------------------------------------
# _serialize_value
# ---------------------------------------------------------------------------

class TestSerializeValue:
    def test_none_returns_none(self, executor_embedded):
        assert executor_embedded._serialize_value(None, 1114) is None

    def test_posixtime_int(self, executor_embedded):
        from iris_pgwire.iris_executor import POSIXTIME_OFFSET
        result = executor_embedded._serialize_value(POSIXTIME_OFFSET, 1114)
        assert result == "1970-01-01 00:00:00.000000"

    def test_legacy_pg_int_timestamp(self, executor_embedded):
        result = executor_embedded._serialize_value(0, 1114)
        assert result == "2000-01-01 00:00:00.000000"

    def test_datetime_formatted(self, executor_embedded):
        ts = dt.datetime(2023, 6, 15, 12, 30, 45, 123456)
        result = executor_embedded._serialize_value(ts, 1114)
        assert result == "2023-06-15 12:30:45.123456"

    def test_digit_string_posixtime(self, executor_embedded):
        from iris_pgwire.iris_executor import POSIXTIME_OFFSET
        val = str(POSIXTIME_OFFSET + 2_000_000)
        result = executor_embedded._serialize_value(val, 1114)
        assert result == "1970-01-01 00:00:02.000000"

    def test_formatted_string_passthrough(self, executor_embedded):
        result = executor_embedded._serialize_value("2023-01-01 12:00:00", 1114)
        assert result == "2023-01-01 12:00:00.000000"

    def test_date_int_passthrough(self, executor_embedded):
        result = executor_embedded._serialize_value(42, 1082)
        assert result == 42

    def test_unrelated_oid_passthrough(self, executor_embedded):
        result = executor_embedded._serialize_value("hello", 25)
        assert result == "hello"

    def test_none_date_oid(self, executor_embedded):
        assert executor_embedded._serialize_value(None, 1082) is None


# ---------------------------------------------------------------------------
# _postprocess_rows
# ---------------------------------------------------------------------------

class TestPostprocessRows:
    def test_empty_rows_noop(self, executor_embedded):
        rows = []
        cols = [{"type_oid": 1114}]
        executor_embedded._postprocess_rows(rows, cols)  # no exception

    def test_empty_columns_noop(self, executor_embedded):
        rows = [[1]]
        cols = []
        executor_embedded._postprocess_rows(rows, cols)  # no exception

    def test_posixtime_detection_and_conversion(self, executor_embedded):
        from iris_pgwire.iris_executor import POSIXTIME_OFFSET
        val = POSIXTIME_OFFSET + 1_000_000
        rows = [[val]]
        cols = [{"type_oid": 23}]
        executor_embedded._postprocess_rows(rows, cols)
        assert cols[0]["type_oid"] == 1114
        assert "1970-01-01" in rows[0][0]

    def test_date_iso_string_converted(self, executor_embedded):
        rows = [["2000-01-02"]]
        cols = [{"type_oid": 1082}]
        executor_embedded._postprocess_rows(rows, cols)
        assert rows[0][0] == 1  # days since 2000-01-01

    def test_date_bad_value_kept(self, executor_embedded):
        rows = [["not-a-date"]]
        cols = [{"type_oid": 1082}]
        executor_embedded._postprocess_rows(rows, cols)
        assert rows[0][0] == "not-a-date"

    def test_col_idx_beyond_columns(self, executor_embedded):
        rows = [[1, 2, 3]]
        cols = [{"type_oid": 23}]
        executor_embedded._postprocess_rows(rows, cols)
        # Should not raise; extra values untouched
        assert rows[0][1] == 2


# ---------------------------------------------------------------------------
# _detect_cast_type_oid
# ---------------------------------------------------------------------------

class TestDetectCastTypeOid:
    def test_pg_style_bool_cast(self, executor_embedded):
        sql = "SELECT $1::bool AS flag"
        result = executor_embedded._detect_cast_type_oid(sql, "flag")
        assert result == 16

    def test_cast_function_int(self, executor_embedded):
        sql = "SELECT CAST(? AS INTEGER) AS num"
        result = executor_embedded._detect_cast_type_oid(sql, "num")
        assert result == 23

    def test_no_cast_returns_none(self, executor_embedded):
        sql = "SELECT id FROM users"
        result = executor_embedded._detect_cast_type_oid(sql, "id")
        assert result is None

    def test_pg_style_text_cast(self, executor_embedded):
        sql = "SELECT $1::text AS name"
        result = executor_embedded._detect_cast_type_oid(sql, "name")
        assert result == 25


# ---------------------------------------------------------------------------
# has_returning_clause / get_returning_columns
# ---------------------------------------------------------------------------

class TestReturningClause:
    def test_has_returning_true(self, executor_embedded):
        assert executor_embedded.has_returning_clause("INSERT INTO t VALUES (1) RETURNING id") is True

    def test_has_returning_false(self, executor_embedded):
        assert executor_embedded.has_returning_clause("INSERT INTO t VALUES (1)") is False

    def test_has_returning_empty(self, executor_embedded):
        assert executor_embedded.has_returning_clause("") is False

    def test_has_returning_none(self, executor_embedded):
        assert executor_embedded.has_returning_clause(None) is False

    def test_get_returning_columns_single(self, executor_embedded):
        sql = "INSERT INTO t VALUES (1) RETURNING id"
        assert executor_embedded.get_returning_columns(sql) == ["id"]

    def test_get_returning_columns_multiple(self, executor_embedded):
        sql = "INSERT INTO t VALUES (1) RETURNING id, name, age"
        cols = executor_embedded.get_returning_columns(sql)
        assert cols == ["id", "name", "age"]

    def test_get_returning_columns_star(self, executor_embedded):
        sql = "INSERT INTO t VALUES (1) RETURNING *"
        assert executor_embedded.get_returning_columns(sql) == ["*"]

    def test_get_returning_columns_no_clause(self, executor_embedded):
        sql = "INSERT INTO t VALUES (1)"
        assert executor_embedded.get_returning_columns(sql) == []


# ---------------------------------------------------------------------------
# _extract_table_name
# ---------------------------------------------------------------------------

class TestExtractTableName:
    def test_simple_insert(self, executor_embedded):
        assert executor_embedded._extract_table_name("INSERT INTO users (id) VALUES (1)") == "users"

    def test_no_match_returns_none(self, executor_embedded):
        assert executor_embedded._extract_table_name("SELECT 1") is None

    def test_case_insensitive(self, executor_embedded):
        assert executor_embedded._extract_table_name("insert into Orders (id) values (1)") == "Orders"


# ---------------------------------------------------------------------------
# _split_multi_row_insert
# ---------------------------------------------------------------------------

class TestSplitMultiRowInsert:
    def test_single_row_unchanged(self, executor_embedded):
        sql = "INSERT INTO t (a) VALUES (1)"
        result = executor_embedded._split_multi_row_insert(sql)
        assert result == [sql]

    def test_multi_row_split(self, executor_embedded):
        sql = "INSERT INTO t (a) VALUES (1), (2), (3)"
        result = executor_embedded._split_multi_row_insert(sql)
        assert len(result) == 3

    def test_no_insert_unchanged(self, executor_embedded):
        sql = "SELECT 1"
        result = executor_embedded._split_multi_row_insert(sql)
        assert result == [sql]


# ---------------------------------------------------------------------------
# _is_unique_violation
# ---------------------------------------------------------------------------

class TestIsUniqueViolation:
    def test_unique_keyword(self, executor_embedded):
        assert executor_embedded._is_unique_violation(Exception("unique constraint violated")) is True

    def test_duplicate_keyword(self, executor_embedded):
        assert executor_embedded._is_unique_violation(Exception("duplicate key")) is True

    def test_constraint_keyword(self, executor_embedded):
        assert executor_embedded._is_unique_violation(Exception("constraint failed")) is True

    def test_other_error(self, executor_embedded):
        assert executor_embedded._is_unique_violation(Exception("syntax error")) is False


# ---------------------------------------------------------------------------
# set_session_namespace / _get_session_namespace
# ---------------------------------------------------------------------------

class TestSessionNamespace:
    def test_set_and_get(self, executor_embedded):
        executor_embedded.set_session_namespace("sess1", "MYNS")
        assert executor_embedded._get_session_namespace("sess1") == "MYNS"

    def test_default_namespace(self, executor_embedded):
        assert executor_embedded._get_session_namespace("unknown_sess") == "USER"

    def test_none_session_returns_default(self, executor_embedded):
        assert executor_embedded._get_session_namespace(None) == "USER"


# ---------------------------------------------------------------------------
# _get_executor
# ---------------------------------------------------------------------------

class TestGetExecutor:
    def test_no_session_returns_thread_pool(self, executor_embedded):
        ex = executor_embedded._get_executor(None)
        assert ex is executor_embedded.thread_pool

    def test_session_creates_dedicated_executor(self, executor_embedded):
        ex = executor_embedded._get_executor("my_session")
        assert ex is not executor_embedded.thread_pool

    def test_same_session_same_executor(self, executor_embedded):
        ex1 = executor_embedded._get_executor("sess_a")
        ex2 = executor_embedded._get_executor("sess_a")
        assert ex1 is ex2


# ---------------------------------------------------------------------------
# _detect_iris_environment
# ---------------------------------------------------------------------------

class TestDetectIrisEnvironment:
    def test_embedded_detection_sets_flag(self, iris_mock):
        from iris_pgwire.iris_executor import IRISExecutor
        config = {"host": "localhost", "port": 1972, "namespace": "USER",
                  "username": "SuperUser", "password": "SYS"}
        ex = IRISExecutor(config)
        assert ex.embedded_mode is True

    def test_no_iris_module_sets_external(self):
        """When iris module has no sql.exec, embedded_mode is False."""
        # The iris package is installed as a wrapper that always exists.
        # To simulate "no embedded iris", we patch _import_iris to return a module
        # that has iris.sql but no iris.sql.exec attribute.
        mock = MagicMock()
        del mock.sql  # no sql attribute → external path
        from iris_pgwire.iris_executor import IRISExecutor
        config = {"host": "localhost", "port": 1972, "namespace": "USER",
                  "username": "SuperUser", "password": "SYS"}
        with patch.object(IRISExecutor, "_import_iris", return_value=mock):
            ex = IRISExecutor.__new__(IRISExecutor)
            ex.iris_config = config
            ex.embedded_mode = False
            result = ex._detect_iris_environment()
        assert result is False

    def test_iris_without_sql_exec_is_external(self):
        mock = MagicMock()
        # iris.sql exists but no exec attribute
        mock.sql = MagicMock(spec=[])  # no 'exec' attribute
        sys.modules["iris"] = mock
        try:
            from iris_pgwire.iris_executor import IRISExecutor
            config = {"host": "localhost", "port": 1972, "namespace": "USER",
                      "username": "SuperUser", "password": "SYS"}
            ex = IRISExecutor(config)
            assert ex.embedded_mode is False
        finally:
            sys.modules.pop("iris", None)


# ---------------------------------------------------------------------------
# test_connection
# ---------------------------------------------------------------------------

class TestTestConnection:
    @pytest.mark.asyncio
    async def test_embedded_mode_skips_test(self, executor_embedded):
        executor_embedded.embedded_mode = True
        with patch.object(executor_embedded, "_test_vector_support", new=AsyncMock()):
            await executor_embedded.test_connection()  # should not raise

    @pytest.mark.asyncio
    async def test_external_mode_calls_test_external(self, executor_external):
        executor_external.embedded_mode = False
        with (
            patch.object(executor_external, "_test_external_connection", new=AsyncMock()) as mock_ext,
            patch.object(executor_external, "_test_vector_support", new=AsyncMock()),
        ):
            await executor_external.test_connection()
            mock_ext.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connection_failure_raises_connection_error(self, executor_external):
        executor_external.embedded_mode = False
        with (
            patch.object(
                executor_external, "_test_external_connection",
                new=AsyncMock(side_effect=RuntimeError("connection refused"))
            ),
        ):
            with pytest.raises(ConnectionError, match="Cannot connect to IRIS"):
                await executor_external.test_connection()


# ---------------------------------------------------------------------------
# _test_vector_support
# ---------------------------------------------------------------------------

class TestVectorSupport:
    @pytest.mark.asyncio
    async def test_embedded_vector_success(self, executor_embedded, iris_mock):
        executor_embedded.embedded_mode = True
        iris_mock.sql.exec = MagicMock(return_value=iter([]))
        await executor_embedded._test_vector_support()
        assert executor_embedded.vector_support is True

    @pytest.mark.asyncio
    async def test_embedded_vector_failure(self, executor_embedded, iris_mock):
        executor_embedded.embedded_mode = True
        iris_mock.sql.exec = MagicMock(side_effect=Exception("not supported"))
        await executor_embedded._test_vector_support()
        assert executor_embedded.vector_support is False

    @pytest.mark.asyncio
    async def test_external_vector_success(self, executor_external):
        executor_external.embedded_mode = False
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1.0,)
        mock_conn.cursor.return_value = mock_cursor
        with patch.object(executor_external, "_get_pooled_connection", return_value=mock_conn):
            with patch.object(executor_external, "_return_connection"):
                await executor_external._test_vector_support()
        assert executor_external.vector_support is True

    @pytest.mark.asyncio
    async def test_external_vector_failure(self, executor_external):
        executor_external.embedded_mode = False
        with patch.object(
            executor_external, "_get_pooled_connection",
            side_effect=Exception("no connection")
        ):
            await executor_external._test_vector_support()
        assert executor_external.vector_support is False


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------

class TestClose:
    @pytest.mark.asyncio
    async def test_close_shuts_down_pool(self, executor_embedded):
        # Should not raise; thread pool should be shut down
        await executor_embedded.close()
        # Calling close again should not raise
        await executor_embedded.close()

    @pytest.mark.asyncio
    async def test_close_clears_session_connections(self, executor_embedded):
        mock_conn = MagicMock()
        executor_embedded.session_connections["sess1"] = mock_conn
        await executor_embedded.close()
        assert executor_embedded.session_connections == {}
        mock_conn.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_with_main_connection(self, executor_embedded):
        mock_conn = MagicMock()
        executor_embedded.connection = mock_conn
        await executor_embedded.close()
        mock_conn.close.assert_called_once()
        assert executor_embedded.connection is None

    @pytest.mark.asyncio
    async def test_close_handles_connection_close_error(self, executor_embedded):
        mock_conn = MagicMock()
        mock_conn.close.side_effect = Exception("already closed")
        executor_embedded.session_connections["sess1"] = mock_conn
        await executor_embedded.close()  # should not raise


# ---------------------------------------------------------------------------
# _split_sql_statements
# ---------------------------------------------------------------------------

class TestSplitSqlStatements:
    def test_single_statement(self, executor_embedded):
        stmts = executor_embedded._split_sql_statements("SELECT 1")
        assert len(stmts) >= 1
        assert any("SELECT 1" in s for s in stmts)

    def test_semicolon_stripped(self, executor_embedded):
        stmts = executor_embedded._split_sql_statements("SELECT 1;")
        # DdlSplitter strips trailing semicolons
        for s in stmts:
            assert not s.endswith(";")

    def test_multiple_statements(self, executor_embedded):
        sql = "CREATE TABLE a (id INT); CREATE TABLE b (id INT)"
        stmts = executor_embedded._split_sql_statements(sql)
        assert len(stmts) == 2


# ---------------------------------------------------------------------------
# _get_normalized_sql (cache behavior)
# ---------------------------------------------------------------------------

class TestGetNormalizedSql:
    def test_caching_enabled(self, executor_embedded):
        executor_embedded.enable_query_cache = True
        sql = "SELECT 1"
        r1 = executor_embedded._get_normalized_sql(sql)
        r2 = executor_embedded._get_normalized_sql(sql)
        assert r1 == r2

    def test_caching_disabled(self, executor_embedded):
        executor_embedded.enable_query_cache = False
        sql = "SELECT 1"
        r1 = executor_embedded._get_normalized_sql(sql)
        assert isinstance(r1, str)

    def test_cache_eviction_at_limit(self, executor_embedded):
        executor_embedded.enable_query_cache = True
        executor_embedded.query_cache_size = 2
        for i in range(5):
            executor_embedded._get_normalized_sql(f"SELECT {i}")
        # Should not raise even with overflow
        assert len(executor_embedded._query_cache) <= 3


# ---------------------------------------------------------------------------
# execute_query (embedded path)
# ---------------------------------------------------------------------------

class TestExecuteQueryEmbedded:
    @pytest.mark.asyncio
    async def test_returns_success_dict(self, executor_embedded, iris_mock):
        """execute_query returns a dict with 'success' key."""
        # Make iris.sql.exec return a simple iterable with _meta
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([[42]]))
        mock_result._meta = [{"name": "val", "type": "INTEGER"}]
        iris_mock.sql.exec.return_value = mock_result

        with patch.object(executor_embedded.catalog_router, "handle_catalog_query", new=AsyncMock(return_value=None)):
            with patch.object(executor_embedded.sql_interceptor, "intercept") as mock_intercept:
                mock_intercept.return_value = MagicMock(intercepted=False)
                result = await executor_embedded.execute_query("SELECT 42")

        assert isinstance(result, dict)
        assert "success" in result

    @pytest.mark.asyncio
    async def test_intercepted_query_returns_intercept_result(self, executor_embedded):
        """When sql_interceptor intercepts, returns intercept result immediately."""
        intercept_result = {"success": True, "rows": [], "columns": [], "row_count": 0}
        mock_intercept = MagicMock(intercepted=True, result=intercept_result)

        with patch.object(executor_embedded.catalog_router, "handle_catalog_query", new=AsyncMock(return_value=None)):
            with patch.object(executor_embedded.sql_interceptor, "intercept", return_value=mock_intercept):
                result = await executor_embedded.execute_query("SELECT 1")

        assert result is intercept_result

    @pytest.mark.asyncio
    async def test_catalog_query_returns_catalog_result(self, executor_embedded):
        """When catalog_router handles the query, returns catalog result."""
        catalog_result = {"success": True, "rows": [], "columns": [], "row_count": 0}
        with patch.object(
            executor_embedded.catalog_router, "handle_catalog_query",
            new=AsyncMock(return_value=catalog_result)
        ):
            result = await executor_embedded.execute_query("SELECT * FROM pg_catalog.pg_tables")

        assert result is catalog_result

    @pytest.mark.asyncio
    async def test_execute_query_embedded_path(self, executor_embedded, iris_mock):
        """execute_query with embedded_mode=True uses _execute_embedded_async."""
        executor_embedded.embedded_mode = True

        expected = {
            "success": True, "rows": [[1]], "columns": [{"name": "v", "type_oid": 23}],
            "row_count": 1, "command_tag": "SELECT 1"
        }
        with patch.object(executor_embedded, "_execute_embedded_async", new=AsyncMock(return_value=expected)):
            with patch.object(executor_embedded.catalog_router, "handle_catalog_query", new=AsyncMock(return_value=None)):
                with patch.object(executor_embedded.sql_interceptor, "intercept",
                                  return_value=MagicMock(intercepted=False)):
                    result = await executor_embedded.execute_query("SELECT 1")

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_query_external_path(self, executor_external):
        """execute_query with embedded_mode=False uses _execute_external_async."""
        executor_external.embedded_mode = False

        expected = {
            "success": True, "rows": [], "columns": [], "row_count": 0, "command_tag": "SELECT 0"
        }
        with patch.object(executor_external, "_execute_external_async", new=AsyncMock(return_value=expected)):
            with patch.object(executor_external.catalog_router, "handle_catalog_query", new=AsyncMock(return_value=None)):
                with patch.object(executor_external.sql_interceptor, "intercept",
                                  return_value=MagicMock(intercepted=False)):
                    result = await executor_external.execute_query("SELECT 1")

        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_query_ddl_idempotency(self, executor_embedded):
        """DDL errors that are idempotent (IF NOT EXISTS) return success."""
        fail_result = {"success": False, "error": "Table 'foo' already exists"}

        with patch.object(executor_embedded, "_execute_embedded_async", new=AsyncMock(return_value=fail_result)):
            with patch.object(executor_embedded.catalog_router, "handle_catalog_query", new=AsyncMock(return_value=None)):
                with patch.object(executor_embedded.sql_interceptor, "intercept",
                                  return_value=MagicMock(intercepted=False)):
                    with patch.object(executor_embedded.ddl_handler, "handle") as mock_handle:
                        mock_skipped = MagicMock(success=True, skipped=True, command="CREATE TABLE",
                                                  object_name="foo")
                        mock_handle.return_value = mock_skipped
                        result = await executor_embedded.execute_query(
                            "CREATE TABLE IF NOT EXISTS foo (id INT)"
                        )
        assert result["success"] is True


# ---------------------------------------------------------------------------
# _materialize_embedded_result
# ---------------------------------------------------------------------------

class TestMaterializeEmbeddedResult:
    def test_with_meta_and_rows(self, executor_embedded):
        mock_result = MagicMock()
        mock_result._meta = [{"name": "id", "type": "INTEGER", "size": 4}]
        mock_result.__iter__ = MagicMock(return_value=iter([[1], [2]]))

        rows, columns = executor_embedded._materialize_embedded_result(
            mock_result, "SELECT id FROM t", "SELECT ID FROM T", "SELECT id FROM t", None
        )
        assert len(rows) == 2
        assert len(columns) == 1
        assert columns[0]["name"] == "id"

    def test_without_meta_discovers_metadata(self, executor_embedded):
        mock_result = MagicMock()
        mock_result._meta = None
        mock_result.__iter__ = MagicMock(return_value=iter([[42]]))

        rows, columns = executor_embedded._materialize_embedded_result(
            mock_result, "SELECT 42", "SELECT 42", "SELECT 42", None
        )
        assert len(rows) == 1
        assert len(columns) >= 1

    def test_current_timestamp_type_override(self, executor_embedded):
        mock_result = MagicMock()
        mock_result._meta = [{"name": "ts", "type": "VARCHAR", "size": -1}]
        mock_result.__iter__ = MagicMock(return_value=iter([["2023-01-01 00:00:00.000000"]]))

        _, columns = executor_embedded._materialize_embedded_result(
            mock_result,
            "SELECT CURRENT_TIMESTAMP",
            "SELECT CURRENT_TIMESTAMP",
            "SELECT CURRENT_TIMESTAMP",
            None,
        )
        assert columns[0]["type_oid"] == 1114

    def test_fetch_error_handled_gracefully(self, executor_embedded):
        mock_result = MagicMock()
        mock_result._meta = None

        def bad_iter():
            raise RuntimeError("fetch failed")
            yield  # make it a generator

        mock_result.__iter__ = bad_iter

        # Should not raise
        rows, columns = executor_embedded._materialize_embedded_result(
            mock_result, "SELECT 1", "SELECT 1", "SELECT 1", None
        )
        assert rows == []


# ---------------------------------------------------------------------------
# _materialize_external_result
# ---------------------------------------------------------------------------

class TestMaterializeExternalResult:
    def test_none_cursor_returns_empty(self, executor_external):
        rows, cols = executor_external._materialize_external_result(
            None, "SELECT 1", "SELECT 1", "SELECT 1", None
        )
        assert rows == []
        assert cols == []

    def test_cursor_with_description_tuples(self, executor_external):
        mock_cursor = MagicMock()
        mock_cursor._meta = None
        mock_cursor.description = [("id", 4, 11, None, None, None, None)]
        mock_cursor.fetchall.return_value = [(1,), (2,)]

        rows, cols = executor_external._materialize_external_result(
            mock_cursor, "SELECT id FROM t", "SELECT ID FROM T", "SELECT id FROM t", None
        )
        assert len(rows) == 2
        assert cols[0]["name"] == "id"

    def test_cursor_with_dict_description(self, executor_external):
        mock_cursor = MagicMock()
        mock_cursor._meta = [{"name": "val", "type": "INTEGER", "size": 4}]
        mock_cursor.fetchall.return_value = [(42,)]

        rows, cols = executor_external._materialize_external_result(
            mock_cursor, "SELECT val FROM t", "SELECT VAL FROM T", "SELECT val FROM t", None
        )
        assert len(rows) == 1

    def test_fetch_error_logged(self, executor_external):
        mock_cursor = MagicMock()
        mock_cursor._meta = [{"name": "id", "type": "INTEGER", "size": 4}]
        mock_cursor.fetchall.side_effect = Exception("fetch error")

        rows, cols = executor_external._materialize_external_result(
            mock_cursor, "SELECT id FROM t", "SELECT ID FROM T", "SELECT id FROM t", None
        )
        assert rows == []


# ---------------------------------------------------------------------------
# _execute_embedded_async (direct)
# ---------------------------------------------------------------------------

class TestExecuteEmbeddedAsync:
    @pytest.mark.asyncio
    async def test_returns_dict_on_success(self, executor_embedded, iris_mock):
        executor_embedded.embedded_mode = True
        mock_result = MagicMock()
        mock_result._meta = [{"name": "one", "type": "INTEGER"}]
        mock_result.__iter__ = MagicMock(return_value=iter([[1]]))
        iris_mock.sql.exec.return_value = mock_result

        with patch.object(executor_embedded, "_get_iris_connection", return_value=None):
            result = await executor_embedded._execute_embedded_async("SELECT 1")

        assert result["success"] is True
        assert "rows" in result

    @pytest.mark.asyncio
    async def test_returns_error_dict_on_failure(self, executor_embedded, iris_mock):
        executor_embedded.embedded_mode = True
        iris_mock.sql.exec.side_effect = Exception("SQLCODE -5")

        with patch.object(executor_embedded, "_get_iris_connection", return_value=None):
            result = await executor_embedded._execute_embedded_async("SELECT bad_col FROM nonexistent")

        assert result["success"] is False
        assert "error" in result

    @pytest.mark.asyncio
    async def test_no_iris_module_returns_error(self, executor_embedded):
        """When _import_iris returns None, embedded execution returns error dict."""
        executor_embedded.embedded_mode = True

        with patch.object(executor_embedded, "_import_iris", return_value=None):
            with patch.object(executor_embedded, "_get_iris_connection", return_value=None):
                result = await executor_embedded._execute_embedded_async("SELECT 1")

        assert result["success"] is False
        assert "IRIS module not found" in result.get("error", "")

    @pytest.mark.asyncio
    async def test_show_command_intercepted(self, executor_embedded, iris_mock):
        executor_embedded.embedded_mode = True
        show_result = {"success": True, "rows": [["UTF8"]], "columns": [{"name": "standard_conforming_strings"}]}

        with patch.object(executor_embedded, "_get_iris_connection", return_value=None):
            with patch.object(executor_embedded, "_handle_show_command", return_value=show_result):
                result = await executor_embedded._execute_embedded_async("SHOW standard_conforming_strings")

        assert result is show_result


# ---------------------------------------------------------------------------
# _discover_metadata
# ---------------------------------------------------------------------------

class TestDiscoverMetadata:
    def test_layer3_fallback(self, executor_embedded, iris_mock):
        """With nothing available, falls back to layer 3 generic columns."""
        iris_mock.sql.exec.side_effect = Exception("fail")
        cols = executor_embedded._discover_metadata("SELECT 1", None, expected_count=1)
        assert len(cols) == 1

    def test_returning_clause_layer(self, executor_embedded):
        """RETURNING clause path in layer 0.5."""
        with patch.object(executor_embedded, "_get_column_type_from_schema", return_value=23):
            cols = executor_embedded._discover_metadata(
                "INSERT INTO t VALUES (1) RETURNING id",
                None,
                expected_count=1,
                rows=[[42]],
            )
        assert len(cols) >= 1

    def test_layer1_limit_zero(self, executor_embedded):
        """Layer 1: LIMIT 0 discovery."""
        mock_result = MagicMock()
        mock_result._meta = [{"name": "col1"}]

        with patch.object(
            executor_embedded,
            "_discover_metadata_with_limit_zero",
            return_value=["col1"],
        ):
            cols = executor_embedded._discover_metadata(
                "SELECT col1 FROM t", None, expected_count=1
            )
        assert any(c["name"] == "col1" for c in cols)


# ---------------------------------------------------------------------------
# execute_many
# ---------------------------------------------------------------------------

class TestExecuteMany:
    @pytest.mark.asyncio
    async def test_returns_success(self, executor_embedded, iris_mock):
        executor_embedded.embedded_mode = True
        iris_mock.sql.exec.return_value = iter([])

        with patch.object(
            executor_embedded, "_execute_many_native",
            new=AsyncMock(return_value={"success": True, "rows_affected": 2, "_execution_path": "dbapi_executemany"})
        ):
            result = await executor_embedded.execute_many(
                "INSERT INTO t (a) VALUES (?)", [[1], [2]]
            )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_fallback_on_native_failure(self, executor_embedded):
        executor_embedded.embedded_mode = True

        with patch.object(
            executor_embedded, "_execute_many_native",
            new=AsyncMock(side_effect=Exception("native failed"))
        ):
            with patch.object(
                executor_embedded, "_execute_many_inline_fallback",
                new=AsyncMock(return_value={"success": True, "rows_affected": 1, "_execution_path": "loop_fallback"})
            ):
                result = await executor_embedded.execute_many(
                    "INSERT INTO t (a) VALUES (?)", [[1]]
                )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_returning_clause_path(self, executor_embedded):
        with patch.object(
            executor_embedded, "_execute_many_with_returning",
            new=AsyncMock(return_value={
                "success": True, "rows": [[1]], "columns": [{"name": "id", "type_oid": 23}],
                "rows_affected": 1, "_execution_path": "execute_many_with_returning"
            })
        ):
            result = await executor_embedded.execute_many(
                "INSERT INTO t (id) VALUES (?) RETURNING id", [[1]]
            )
        assert result["success"] is True


# ---------------------------------------------------------------------------
# _map_insert_column_values
# ---------------------------------------------------------------------------

class TestMapInsertColumnValues:
    def test_maps_correctly(self, executor_embedded):
        from iris_pgwire.sql_translator.returning_plan import ReturningPlan

        plan = MagicMock(spec=ReturningPlan)
        plan.insert_columns = ["id", "name"]
        result = executor_embedded._map_insert_column_values(plan, [1, "Alice"])
        assert result == {"id": 1, "name": "Alice"}

    def test_no_params_returns_empty(self, executor_embedded):
        from iris_pgwire.sql_translator.returning_plan import ReturningPlan

        plan = MagicMock(spec=ReturningPlan)
        plan.insert_columns = ["id"]
        assert executor_embedded._map_insert_column_values(plan, None) == {}
        assert executor_embedded._map_insert_column_values(plan, []) == {}


# ---------------------------------------------------------------------------
# _extract_insert_id_from_sql
# ---------------------------------------------------------------------------

class TestExtractInsertIdFromSql:
    def test_extracts_id_from_params(self, executor_embedded):
        sql = "INSERT INTO users (id, name) VALUES (?, ?)"
        col, val = executor_embedded._extract_insert_id_from_sql(sql, ["abc-uuid", "Alice"])
        assert col == "ID"
        assert val == "abc-uuid"

    def test_no_id_column_returns_none(self, executor_embedded):
        sql = "INSERT INTO users (name, age) VALUES (?, ?)"
        col, val = executor_embedded._extract_insert_id_from_sql(sql, ["Alice", 30])
        assert col is None
        assert val is None

    def test_extracts_from_literal_values(self, executor_embedded):
        sql = "INSERT INTO users (id, name) VALUES ('my-uuid', 'Alice')"
        col, val = executor_embedded._extract_insert_id_from_sql(sql, None)
        assert col == "ID"
        assert val == "my-uuid"

    def test_no_columns_match_returns_none(self, executor_embedded):
        sql = "SELECT 1"
        col, val = executor_embedded._extract_insert_id_from_sql(sql, None)
        assert col is None
        assert val is None


# ---------------------------------------------------------------------------
# _close_cursor_if_possible
# ---------------------------------------------------------------------------

class TestCloseCursorIfPossible:
    def test_calls_close(self, executor_embedded):
        mock_cursor = MagicMock()
        executor_embedded._close_cursor_if_possible(mock_cursor)
        mock_cursor.close.assert_called_once()

    def test_none_cursor_noop(self, executor_embedded):
        executor_embedded._close_cursor_if_possible(None)  # no exception

    def test_close_error_swallowed(self, executor_embedded):
        mock_cursor = MagicMock()
        mock_cursor.close.side_effect = Exception("fail")
        executor_embedded._close_cursor_if_possible(mock_cursor)  # no exception


# ---------------------------------------------------------------------------
# _determine_command_tag
# ---------------------------------------------------------------------------

class TestDetermineCommandTag:
    def test_select(self, executor_embedded):
        assert executor_embedded._determine_command_tag("SELECT * FROM t", 5) == "SELECT"

    def test_insert(self, executor_embedded):
        assert executor_embedded._determine_command_tag("INSERT INTO t VALUES (1)", 1) == "INSERT 0 1"

    def test_update(self, executor_embedded):
        assert executor_embedded._determine_command_tag("UPDATE t SET x=1", 3) == "UPDATE 3"

    def test_delete(self, executor_embedded):
        assert executor_embedded._determine_command_tag("DELETE FROM t", 2) == "DELETE 2"

    def test_create(self, executor_embedded):
        assert executor_embedded._determine_command_tag("CREATE TABLE t (id INT)", 0) == "CREATE"

    def test_drop(self, executor_embedded):
        assert executor_embedded._determine_command_tag("DROP TABLE t", 0) == "DROP"

    def test_alter(self, executor_embedded):
        assert executor_embedded._determine_command_tag("ALTER TABLE t ADD COLUMN x INT", 0) == "ALTER"

    def test_truncate(self, executor_embedded):
        assert executor_embedded._determine_command_tag("TRUNCATE TABLE t", 0) == "TRUNCATE"

    def test_merge(self, executor_embedded):
        assert executor_embedded._determine_command_tag("MERGE INTO t ...", 5) == "MERGE 5"

    def test_empty_sql(self, executor_embedded):
        assert executor_embedded._determine_command_tag("", 0) == "UNKNOWN"

    def test_unknown_command(self, executor_embedded):
        assert executor_embedded._determine_command_tag("VACUUM", 0) == "UNKNOWN"

    def test_begin(self, executor_embedded):
        assert executor_embedded._determine_command_tag("BEGIN", 0) == "BEGIN"

    def test_commit(self, executor_embedded):
        assert executor_embedded._determine_command_tag("COMMIT", 0) == "COMMIT"

    def test_rollback(self, executor_embedded):
        assert executor_embedded._determine_command_tag("ROLLBACK", 0) == "ROLLBACK"


# ---------------------------------------------------------------------------
# _handle_show_command
# ---------------------------------------------------------------------------

class TestHandleShowCommand:
    def test_known_show_command(self, executor_embedded):
        result = executor_embedded._handle_show_command("SHOW server_version")
        assert result["success"] is True
        assert result["rows"] == [["16.0 (InterSystems IRIS)"]]

    def test_show_timezone(self, executor_embedded):
        result = executor_embedded._handle_show_command("SHOW timezone")
        assert result["success"] is True
        assert result["rows"] == [["UTC"]]

    def test_unknown_show_returns_empty(self, executor_embedded):
        result = executor_embedded._handle_show_command("SHOW unknown_setting")
        assert result["success"] is True
        assert result["rows"] == [[""]]

    def test_show_result_format(self, executor_embedded):
        result = executor_embedded._handle_show_command("SHOW standard_conforming_strings")
        assert "columns" in result
        assert len(result["columns"]) == 1
        assert result["command_tag"] == "SHOW"


# ---------------------------------------------------------------------------
# _normalize_iris_column_name
# ---------------------------------------------------------------------------

class TestNormalizeIrisColumnName:
    def test_numeric_literal_returns_qcolumn(self, executor_embedded):
        result = executor_embedded._normalize_iris_column_name("1", "SELECT 1", "VARCHAR")
        assert result == "?column?"

    def test_hostvar_returns_qcolumn(self, executor_embedded):
        result = executor_embedded._normalize_iris_column_name("HostVar_1", "SELECT ?", "VARCHAR")
        assert result == "?column?"

    def test_expression_with_int_cast(self, executor_embedded):
        result = executor_embedded._normalize_iris_column_name(
            "Expression_1", "SELECT CAST(? AS INTEGER)", "VARCHAR"
        )
        assert result == "int4"

    def test_aggregate_count(self, executor_embedded):
        result = executor_embedded._normalize_iris_column_name(
            "Aggregate_1", "SELECT COUNT(*) FROM t", "VARCHAR"
        )
        assert result == "count"

    def test_aggregate_sum(self, executor_embedded):
        result = executor_embedded._normalize_iris_column_name(
            "Aggregate_1", "SELECT SUM(x) FROM t", "VARCHAR"
        )
        assert result == "sum"

    def test_named_column_preserved(self, executor_embedded):
        result = executor_embedded._normalize_iris_column_name("MyColumn", "SELECT MyColumn FROM t", "VARCHAR")
        assert result == "mycolumn"

    def test_postgres_type_mapping_integer(self, executor_embedded):
        result = executor_embedded._normalize_iris_column_name("INTEGER", "SELECT CAST(x AS INTEGER)", "VARCHAR")
        assert result == "int4"

    def test_numeric_with_explicit_alias(self, executor_embedded):
        result = executor_embedded._normalize_iris_column_name("1", "SELECT 1 AS id", "VARCHAR")
        assert result == "id"


# ---------------------------------------------------------------------------
# _iris_type_to_pg_oid
# ---------------------------------------------------------------------------

class TestIrisTypeToPgOid:
    def test_int4_code(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid(4) == 23

    def test_int8_code(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid(-5) == 20

    def test_numeric_code(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid(2) == 1700

    def test_date_code(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid(9) == 1082

    def test_timestamp_code(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid(10) == 1114

    def test_unknown_int_defaults_varchar(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid(999) == 1043

    def test_varchar_string(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid("VARCHAR") == 1043

    def test_integer_string(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid("INTEGER") == 23

    def test_timestamp_string(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid("TIMESTAMP") == 1114

    def test_unknown_string_defaults_varchar(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid("UNKNOWN_TYPE") == 1043


# ---------------------------------------------------------------------------
# _map_iris_type_to_oid
# ---------------------------------------------------------------------------

class TestMapIrisTypeToOid:
    def test_int_maps(self, executor_embedded):
        assert executor_embedded._map_iris_type_to_oid("INT") == 23

    def test_varchar_maps(self, executor_embedded):
        assert executor_embedded._map_iris_type_to_oid("VARCHAR") == 1043

    def test_varchar_with_size(self, executor_embedded):
        assert executor_embedded._map_iris_type_to_oid("VARCHAR(100)") == 1043

    def test_date_maps(self, executor_embedded):
        assert executor_embedded._map_iris_type_to_oid("DATE") == 1082

    def test_unknown_defaults(self, executor_embedded):
        assert executor_embedded._map_iris_type_to_oid("NOTYPE") == 1043


# ---------------------------------------------------------------------------
# _get_pooled_connection / _return_connection
# ---------------------------------------------------------------------------

class TestConnectionPool:
    def test_get_pooled_creates_new_connection(self, executor_external):
        mock_conn = MagicMock()
        mock_iris = MagicMock()
        mock_iris.connect.return_value = mock_conn

        with patch.object(executor_external, "_import_iris", return_value=mock_iris):
            conn = executor_external._get_pooled_connection()

        assert conn is mock_conn
        assert executor_external._active_count == 1

    def test_get_pooled_uses_pool(self, executor_external):
        mock_conn = MagicMock()
        # Add to pool
        executor_external._connection_pool.append(mock_conn)
        # Make health check pass
        with patch.object(executor_external, "_is_connection_alive", return_value=True):
            conn = executor_external._get_pooled_connection()

        assert conn is mock_conn

    def test_return_connection_goes_to_pool(self, executor_external):
        mock_conn = MagicMock()
        executor_external._active_count = 1
        executor_external._return_connection(mock_conn)
        assert mock_conn in executor_external._connection_pool

    def test_return_connection_with_session_id_stays_active(self, executor_external):
        mock_conn = MagicMock()
        executor_external._return_connection(mock_conn, session_id="sess1")
        # Should NOT be added to pool; session connections stay active
        assert mock_conn not in executor_external._connection_pool

    def test_return_connection_closes_if_pool_full(self, executor_external):
        mock_conn = MagicMock()
        executor_external._active_count = 1
        # Fill pool to max
        executor_external._connection_pool = [MagicMock() for _ in range(executor_external._max_connections)]
        executor_external._return_connection(mock_conn)
        mock_conn.close.assert_called_once()

    def test_no_iris_module_raises(self, executor_external):
        with patch.object(executor_external, "_import_iris", return_value=None):
            with pytest.raises(RuntimeError, match="IRIS module not available"):
                executor_external._get_pooled_connection()


# ---------------------------------------------------------------------------
# _is_connection_alive
# ---------------------------------------------------------------------------

class TestIsConnectionAlive:
    def test_alive_connection(self, executor_external):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        assert executor_external._is_connection_alive(mock_conn) is True

    def test_dead_connection(self, executor_external):
        mock_conn = MagicMock()
        mock_conn.cursor.side_effect = Exception("connection dead")
        assert executor_external._is_connection_alive(mock_conn) is False


# ---------------------------------------------------------------------------
# close_session
# ---------------------------------------------------------------------------

class TestCloseSession:
    @pytest.mark.asyncio
    async def test_close_session_cleans_up(self, executor_embedded):
        mock_conn = MagicMock()
        executor_embedded.session_connections["s1"] = mock_conn
        executor_embedded.session_namespaces["s1"] = "MYNS"

        await executor_embedded.close_session("s1")

        assert "s1" not in executor_embedded.session_connections
        assert "s1" not in executor_embedded.session_namespaces

    @pytest.mark.asyncio
    async def test_close_session_shuts_down_executor(self, executor_embedded):
        mock_executor = MagicMock()
        executor_embedded.session_executors["s2"] = mock_executor

        await executor_embedded.close_session("s2")

        mock_executor.shutdown.assert_called_once_with(wait=False)
        assert "s2" not in executor_embedded.session_executors

    @pytest.mark.asyncio
    async def test_close_nonexistent_session_noop(self, executor_embedded):
        await executor_embedded.close_session("nonexistent")  # should not raise


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------

class TestShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_cleanly(self, executor_embedded):
        await executor_embedded.shutdown()  # Should not raise

    @pytest.mark.asyncio
    async def test_shutdown_with_error(self, executor_embedded):
        executor_embedded.thread_pool.shutdown = MagicMock(side_effect=Exception("pool error"))
        await executor_embedded.shutdown()  # Should not raise (error is caught)


# ---------------------------------------------------------------------------
# Transaction management
# ---------------------------------------------------------------------------

class TestTransactionManagement:
    @pytest.mark.asyncio
    async def test_begin_transaction_embedded(self, executor_embedded, iris_mock):
        executor_embedded.embedded_mode = True
        await executor_embedded.begin_transaction()
        iris_mock.sql.exec.assert_called_with("START TRANSACTION")

    @pytest.mark.asyncio
    async def test_commit_transaction_embedded(self, executor_embedded, iris_mock):
        executor_embedded.embedded_mode = True
        await executor_embedded.commit_transaction()
        iris_mock.sql.exec.assert_called_with("COMMIT")

    @pytest.mark.asyncio
    async def test_rollback_transaction_embedded(self, executor_embedded, iris_mock):
        executor_embedded.embedded_mode = True
        await executor_embedded.rollback_transaction()
        iris_mock.sql.exec.assert_called_with("ROLLBACK")

    @pytest.mark.asyncio
    async def test_begin_transaction_external(self, executor_external):
        executor_external.embedded_mode = False
        # External mode doesn't call iris.sql.exec, just runs the sync func
        await executor_external.begin_transaction()  # should not raise


# ---------------------------------------------------------------------------
# cancel_query
# ---------------------------------------------------------------------------

class TestCancelQuery:
    @pytest.mark.asyncio
    async def test_cancel_embedded_returns_true(self, executor_embedded):
        executor_embedded.embedded_mode = True
        result = await executor_embedded.cancel_query(1234, 5678)
        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_external_no_server_returns_false(self, executor_external):
        executor_external.embedded_mode = False
        executor_external.server = None
        result = await executor_external.cancel_query(1234, 5678)
        assert result is False


# ---------------------------------------------------------------------------
# get_iris_type_mapping / get_server_info
# ---------------------------------------------------------------------------

class TestInfoMethods:
    def test_get_iris_type_mapping_contains_key_types(self, executor_embedded):
        mapping = executor_embedded.get_iris_type_mapping()
        assert "INTEGER" in mapping
        assert "VARCHAR" in mapping
        assert "TIMESTAMP" in mapping

    def test_get_server_info(self, executor_embedded):
        info = executor_embedded.get_server_info()
        assert "server_version" in info
        assert info["embedded_mode"] == executor_embedded.embedded_mode


# ---------------------------------------------------------------------------
# _safe_execute (embedded and external paths)
# ---------------------------------------------------------------------------

class TestSafeExecute:
    def test_embedded_no_params(self, executor_embedded, iris_mock):
        iris_mock.sql.exec.return_value = iter([])
        result = executor_embedded._safe_execute("SELECT 1", None, is_embedded=True)
        iris_mock.sql.exec.assert_called()

    def test_embedded_with_params_no_none(self, executor_embedded, iris_mock):
        iris_mock.sql.exec.return_value = iter([])
        result = executor_embedded._safe_execute("SELECT ?", [42], is_embedded=True)
        iris_mock.sql.exec.assert_called()

    def test_embedded_with_none_params_inlines(self, executor_embedded, iris_mock):
        iris_mock.sql.exec.return_value = iter([])
        result = executor_embedded._safe_execute(
            "INSERT INTO t (a, b) VALUES (?, ?)", [1, None], is_embedded=True
        )
        # Should have been called with inlined SQL
        call_args = iris_mock.sql.exec.call_args
        assert call_args is not None

    def test_embedded_empty_sql_returns_noop(self, executor_embedded):
        from iris_pgwire._noop_cursor import NoopCursor
        result = executor_embedded._safe_execute("", None, is_embedded=True)
        assert isinstance(result, NoopCursor)

    def test_embedded_comment_only_returns_noop(self, executor_embedded):
        from iris_pgwire._noop_cursor import NoopCursor
        result = executor_embedded._safe_execute("-- this is a comment", None, is_embedded=True)
        assert isinstance(result, NoopCursor)

    def test_no_iris_module_raises(self, executor_embedded):
        with patch.object(executor_embedded, "_import_iris", return_value=None):
            with pytest.raises(RuntimeError, match="IRIS module not available"):
                executor_embedded._safe_execute("SELECT 1", None, is_embedded=True)

    def test_external_mode_with_connection(self, executor_external):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        result = executor_external._safe_execute(
            "SELECT 1", None, is_embedded=False, connection=mock_conn
        )
        mock_cursor.execute.assert_called_with("SELECT 1")
        assert result is mock_cursor

    def test_external_mode_with_params(self, executor_external):
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        result = executor_external._safe_execute(
            "SELECT ?", [42], is_embedded=False, connection=mock_conn
        )
        mock_cursor.execute.assert_called_with("SELECT ?", (42,))

    def test_ddl_idempotency_handled(self, executor_embedded, iris_mock):
        from iris_pgwire._noop_cursor import NoopCursor
        iris_mock.sql.exec.side_effect = Exception("Table already exists")
        mock_result = MagicMock(success=True, skipped=True)
        with patch.object(executor_embedded.ddl_handler, "handle", return_value=mock_result):
            result = executor_embedded._safe_execute(
                "CREATE TABLE t (id INT)", None, is_embedded=True
            )
        assert isinstance(result, NoopCursor)


# ---------------------------------------------------------------------------
# _expand_select_star
# ---------------------------------------------------------------------------

class TestExpandSelectStar:
    def test_returns_columns_from_schema(self, executor_embedded):
        with patch.object(executor_embedded, "_get_table_columns_from_schema", return_value=["id", "name"]):
            result = executor_embedded._expand_select_star("SELECT * FROM users", 0)
        assert result == ["id", "name"]

    def test_returns_none_when_no_columns(self, executor_embedded, iris_mock):
        with patch.object(executor_embedded, "_get_table_columns_from_schema", return_value=[]):
            iris_mock.sql.exec.side_effect = Exception("fail")
            result = executor_embedded._expand_select_star("SELECT * FROM nonexistent_table", 0)
        assert result is None

    def test_handles_returning_star(self, executor_embedded):
        with patch.object(executor_embedded, "_get_table_columns_from_schema", return_value=["id"]):
            result = executor_embedded._expand_select_star(
                "INSERT INTO users (id) VALUES (1) RETURNING *", 0
            )
        assert result == ["id"]

    def test_handles_exception_gracefully(self, executor_embedded):
        with patch.object(executor_embedded, "_get_table_columns_from_schema", side_effect=Exception("error")):
            result = executor_embedded._expand_select_star("SELECT * FROM t", 0)
        # Should return None, not raise
        assert result is None


# ---------------------------------------------------------------------------
# _extract_table_names_from_select
# ---------------------------------------------------------------------------

class TestExtractTableNamesFromSelect:
    def test_simple_from(self, executor_embedded):
        names = executor_embedded._extract_table_names_from_select("SELECT * FROM users")
        assert "users" in names

    def test_with_join(self, executor_embedded):
        names = executor_embedded._extract_table_names_from_select(
            "SELECT * FROM users JOIN orders ON users.id = orders.user_id"
        )
        assert "users" in names
        assert "orders" in names

    def test_no_from_returns_empty(self, executor_embedded):
        names = executor_embedded._extract_table_names_from_select("SELECT 1")
        assert names == []


# ---------------------------------------------------------------------------
# _discover_metadata_with_limit_zero
# ---------------------------------------------------------------------------

class TestDiscoverMetadataWithLimitZero:
    def test_returns_columns_from_meta(self, executor_embedded, iris_mock):
        mock_result = MagicMock()
        mock_result._meta = [{"name": "id"}, {"name": "name"}]
        iris_mock.sql.exec.return_value = mock_result

        result = executor_embedded._discover_metadata_with_limit_zero("SELECT id, name FROM t")
        assert result == ["id", "name"]

    def test_returns_columns_from_description(self, executor_embedded, iris_mock):
        mock_result = MagicMock()
        mock_result._meta = None
        mock_result.description = [("id", 4, 11, None), ("name", 12, -1, None)]
        iris_mock.sql.exec.return_value = mock_result

        result = executor_embedded._discover_metadata_with_limit_zero("SELECT id, name FROM t")
        assert result == ["id", "name"]

    def test_returns_none_on_exception(self, executor_embedded, iris_mock):
        iris_mock.sql.exec.side_effect = Exception("fail")
        result = executor_embedded._discover_metadata_with_limit_zero("SELECT * FROM t")
        assert result is None

    def test_returns_none_when_no_metadata(self, executor_embedded, iris_mock):
        mock_result = MagicMock()
        mock_result._meta = None
        mock_result.description = None
        iris_mock.sql.exec.return_value = mock_result

        result = executor_embedded._discover_metadata_with_limit_zero("SELECT * FROM t")
        assert result is None


# ---------------------------------------------------------------------------
# _execute_embedded_statement_sequence
# ---------------------------------------------------------------------------

class TestExecuteEmbeddedStatementSequence:
    def test_empty_statements_returns_noop(self, executor_embedded):
        from iris_pgwire._noop_cursor import NoopCursor
        result = executor_embedded._execute_embedded_statement_sequence([], None, None)
        assert isinstance(result, NoopCursor)

    def test_single_statement_executes(self, executor_embedded, iris_mock):
        iris_mock.sql.exec.return_value = iter([[1]])
        result = executor_embedded._execute_embedded_statement_sequence(
            ["SELECT 1"], None, None
        )
        iris_mock.sql.exec.assert_called()

    def test_multiple_statements_executes_all(self, executor_embedded, iris_mock):
        iris_mock.sql.exec.return_value = iter([])
        executor_embedded._execute_embedded_statement_sequence(
            ["CREATE TABLE a (id INT)", "CREATE TABLE b (id INT)"], None, None
        )
        assert iris_mock.sql.exec.call_count >= 2


# ---------------------------------------------------------------------------
# _prepare_conflict_set_clause / _prepare_conflict_where_clause
# ---------------------------------------------------------------------------

class TestConflictClauses:
    def test_prepare_conflict_set_clause_empty(self, executor_embedded):
        plan = MagicMock()
        plan.conflict_set_clause = None
        clause, params = executor_embedded._prepare_conflict_set_clause(plan, {})
        assert clause == ""
        assert params == []

    def test_prepare_conflict_where_clause(self, executor_embedded):
        plan = MagicMock()
        plan.conflict_target_columns = ["id"]
        plan.conflict_where_clause = None
        clause, params = executor_embedded._prepare_conflict_where_clause(plan, {"id": 42})
        assert '"ID" = ?' in clause
        assert 42 in params


# ---------------------------------------------------------------------------
# _execute_external_async
# ---------------------------------------------------------------------------

class TestExecuteExternalAsync:
    @pytest.mark.asyncio
    async def test_returns_success_dict(self, executor_external):
        executor_external.embedded_mode = False

        mock_cursor = MagicMock()
        mock_cursor._meta = [{"name": "val", "type": "INTEGER", "size": 4}]
        mock_cursor.fetchall.return_value = [(42,)]

        with patch.object(executor_external, "_get_pooled_connection", return_value=MagicMock()):
            with patch.object(executor_external, "_safe_execute", return_value=mock_cursor):
                with patch.object(executor_external, "_return_connection"):
                    result = await executor_external._execute_external_async("SELECT 42")

        assert isinstance(result, dict)
        assert "success" in result

    @pytest.mark.asyncio
    async def test_returns_error_on_exception(self, executor_external):
        executor_external.embedded_mode = False

        with patch.object(
            executor_external, "_get_pooled_connection",
            side_effect=Exception("connection failed")
        ):
            result = await executor_external._execute_external_async("SELECT 1")

        assert result["success"] is False
        assert "error" in result


# ---------------------------------------------------------------------------
# _get_normalized_sql cache size limit
# ---------------------------------------------------------------------------

class TestQueryCacheEviction:
    def test_cache_does_not_grow_unbounded(self, executor_embedded):
        executor_embedded.enable_query_cache = True
        executor_embedded.query_cache_size = 5
        for i in range(20):
            executor_embedded._get_normalized_sql(f"SELECT {i} FROM t WHERE id = {i}")
        # Cache should not exceed query_cache_size + a small buffer
        assert len(executor_embedded._query_cache) <= executor_embedded.query_cache_size + 2


# ---------------------------------------------------------------------------
# _get_table_columns_from_schema / _get_column_type_from_schema
# ---------------------------------------------------------------------------

class TestSchemaLookup:
    def test_get_table_columns_embedded(self, executor_embedded, iris_mock):
        executor_embedded.embedded_mode = True
        iris_mock.sql.exec.return_value = iter([["id"], ["name"]])

        cols = executor_embedded._get_table_columns_from_schema("users")
        assert cols == ["id", "name"]

    def test_get_table_columns_strict_mode_returns_empty(self, executor_embedded):
        executor_embedded.strict_single_connection = True
        cols = executor_embedded._get_table_columns_from_schema("users")
        assert cols == []

    def test_get_table_columns_exception_returns_empty(self, executor_embedded, iris_mock):
        executor_embedded.embedded_mode = True
        iris_mock.sql.exec.side_effect = Exception("sql error")
        cols = executor_embedded._get_table_columns_from_schema("users")
        assert cols == []

    def test_get_column_type_strict_mode_returns_none(self, executor_embedded):
        executor_embedded.strict_single_connection = True
        result = executor_embedded._get_column_type_from_schema("users", "id")
        assert result is None

    def test_get_column_type_embedded(self, executor_embedded, iris_mock):
        executor_embedded.embedded_mode = True
        # Return a row with type 'INTEGER'
        iris_mock.sql.exec.return_value = iter([["INTEGER"]])

        result = executor_embedded._get_column_type_from_schema("users", "id")
        assert result is not None  # should return some OID

    def test_get_column_type_exception_returns_none(self, executor_embedded, iris_mock):
        executor_embedded.embedded_mode = True
        iris_mock.sql.exec.side_effect = Exception("error")
        result = executor_embedded._get_column_type_from_schema("users", "id")
        assert result is None


# ---------------------------------------------------------------------------
# _resolve_embedded_returning_result
# ---------------------------------------------------------------------------

class TestResolveEmbeddedReturningResult:
    def test_no_returning_returns_original_result(self, executor_embedded):
        plan = MagicMock()
        plan.has_returning = False
        plan.columns = None

        original = MagicMock()
        result = executor_embedded._resolve_embedded_returning_result(
            original, plan, [], None, None, None, None
        )
        assert result is original

    def test_delete_returning_uses_prefetched_rows(self, executor_embedded):
        from iris_pgwire.iris_executor import MockResult

        plan = MagicMock()
        plan.has_returning = True
        plan.columns = ["id"]
        plan.operation = "DELETE"

        prefetched = [[1], [2]]
        prefetched_meta = [{"name": "id", "type_oid": 23}]

        result = executor_embedded._resolve_embedded_returning_result(
            MagicMock(), plan, prefetched, prefetched_meta, None, None, None
        )
        assert isinstance(result, MockResult)
        assert list(result) == prefetched

    def test_insert_returning_calls_emulate(self, executor_embedded):
        from iris_pgwire.iris_executor import MockResult

        plan = MagicMock()
        plan.has_returning = True
        plan.columns = ["id"]
        plan.operation = "INSERT"

        emulated_rows = [[42]]
        emulated_meta = [{"name": "id", "type_oid": 23}]

        with patch.object(executor_embedded, "_emulate_returning", return_value=(emulated_rows, emulated_meta)):
            result = executor_embedded._resolve_embedded_returning_result(
                MagicMock(), plan, [], None, None, None, None
            )

        assert isinstance(result, MockResult)


# ---------------------------------------------------------------------------
# _prepare_sql
# ---------------------------------------------------------------------------

class TestPrepareSql:
    def test_returns_tuple_of_four(self, executor_embedded):
        result = executor_embedded._prepare_sql("SELECT 1", None, "direct", None, None)
        assert len(result) == 4
        optimized_sql, optimized_params, plan, elapsed = result
        assert isinstance(optimized_sql, str)
        assert isinstance(optimized_params, list)
        assert elapsed >= 0

    def test_strips_semicolon(self, executor_embedded):
        sql, params, plan, _ = executor_embedded._prepare_sql("SELECT 1;", None, "direct")
        assert not sql.rstrip().endswith(";")

    def test_with_params(self, executor_embedded):
        sql, params, plan, _ = executor_embedded._prepare_sql(
            "SELECT ?", [42], "direct", None, None
        )
        assert 42 in params

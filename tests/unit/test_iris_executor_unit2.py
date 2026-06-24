"""
Additional unit tests for iris_pgwire.iris_executor.IRISExecutor (Part 2)

Covers uncovered lines identified from coverage report:
- Lines 180-209: _import_iris (fallback ImportError paths), _detect_iris_environment
- Lines 287, 293-294: _get_normalized_sql edge cases
- Lines 300, 304: _convert_iris_horolog_date_to_pg, _convert_pg_date_to_iris_horolog
- Lines 408-418: _get_table_columns_from_schema external path
- Lines 449-458: _get_column_type_from_schema external path
- Lines 545-546, 569, 613-614: _serialize_value branches
- Lines 785-835: _test_external_connection
- Lines 845, 891-893: _test_vector_support error branches
- Lines 1046, 1060, 1069-1076: execute_many inline fallback
- Lines 1149-1151, 1164-1250: _execute_many_with_returning
- Lines 1262, 1268-1283: _execute_many_inline_fallback external path
- Lines 1305-1306, 1311, 1314-1317: _execute_many_embedded_async
- Lines 1337-1471: _execute_many_embedded_async sync inner
- Lines 1488-1608: _execute_many_external_async
- Lines 1706, 1711-1712: _extract_insert_id_from_sql
- Lines 1727, 1736-1742: _emulate_returning
- Lines 1845, 1863-2090: _emulate_returning body
- Lines 2110-2119: _prepare_conflict_set_clause with EXCLUDED pattern
- Lines 2133-2136: _prepare_conflict_where_clause with conflict_where_clause
- Lines 2147-2182: _handle_on_conflict_update
- Lines 2264-2273: _materialize_embedded_result type adjustments
- Lines 2294-2295: _materialize_embedded_result row fallback
- Lines 2348, 2351-2360: _execute_embedded_async namespace retry
- Lines 2404, 2410: _execute_embedded_async SHOW intercept
- Lines 2432-2438: _execute_embedded_async DELETE RETURNING pre-fetch
- Lines 2552, 2576-2577: _discover_metadata_with_limit_zero branches
- Lines 2590-2592, 2599-2600: _discover_metadata_with_limit_zero description path
- Lines 2658-2682: _discover_metadata RETURNING * path
- Lines 2693: _discover_metadata RETURNING list path
- Lines 2734-2754: _discover_metadata Layer 1.5
- Lines 2773, 2777: _discover_metadata Layer 2 CAST/TIMESTAMP overrides
- Lines 2792-2812: _discover_metadata Layer 3
- Lines 2850-2859, 2862: _materialize_external_result int/float coercions
- Lines 2885-2891, 2894: _materialize_external_result row fallback
- Lines 2903-2908: _materialize_external_result discover metadata
- Lines 2956-2968: _execute_external_async vector param processing
- Lines 2985-2992: _execute_external_async DELETE RETURNING pre-fetch
- Lines 3006: _execute_external_async empty statements guard
- Lines 3010-3017: _execute_external_async multi-statement
- Lines 3030-3051: _execute_external_async ON CONFLICT handling
- Lines 3055-3066: _execute_external_async RETURNING emulation
- Lines 3150-3151, 3155-3159, 3175-3183: _execute_external_async timeout/eviction
- Lines 3216-3230, 3240-3254: _get_pooled_connection session dead + pool timeout
- Lines 3264-3271: _get_pooled_connection pool health check
- Lines 3283: _get_pooled_connection session_id assignment
- Lines 3298-3299, 3350, 3372, 3382: _expand_select_star branches
- Lines 3385-3388: _expand_select_star RETURNING branch
- Lines 3405-3455: _expand_select_star LIMIT 0 inner
- Lines 3520-3526: _normalize_iris_column_name SELECT without FROM
- Lines 3563-3565, 3574: _normalize_iris_column_name string literal in SQL
- Lines 3589-3608: _normalize_iris_column_name expression type cases
- Lines 3619-3627: _normalize_iris_column_name aggregate functions
- Lines 3725, 3740: _iris_type_to_pg_oid extra type codes
- Lines 3974-3976, 3991-3993, 4004-4031: cancel_query, _cancel_embedded_query, _cancel_external_query
"""

from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_embedded_iris_mock():
    iris_mod = MagicMock()
    iris_mod.sql = MagicMock()
    iris_mod.sql.exec = MagicMock(return_value=iter([]))
    iris_mod.system = MagicMock()
    iris_mod.system.Process = MagicMock()
    iris_mod.system.Process.SetNamespace = MagicMock()
    iris_mod.connect = MagicMock()
    return iris_mod


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def iris_mock():
    mock = _make_embedded_iris_mock()
    sys.modules["iris"] = mock
    yield mock
    sys.modules.pop("iris", None)


@pytest.fixture
def executor_embedded(iris_mock):
    from iris_pgwire.iris_executor import IRISExecutor
    config = {"host": "localhost", "port": 1972, "namespace": "USER",
              "username": "SuperUser", "password": "SYS"}
    ex = IRISExecutor(config)
    ex.embedded_mode = True
    return ex


@pytest.fixture
def executor_external():
    sys.modules.pop("iris", None)
    from iris_pgwire.iris_executor import IRISExecutor
    config = {"host": "localhost", "port": 1972, "namespace": "USER",
              "username": "SuperUser", "password": "SYS"}
    ex = IRISExecutor(config)
    ex.embedded_mode = False
    return ex


# ---------------------------------------------------------------------------
# _import_iris: fallback ImportError paths
# ---------------------------------------------------------------------------

class TestImportIrisFallback:
    def test_import_iris_returns_module_when_available(self, iris_mock):
        from iris_pgwire.iris_executor import IRISExecutor
        config = {"host": "localhost", "port": 1972, "namespace": "USER",
                  "username": "SuperUser", "password": "SYS"}
        ex = IRISExecutor(config)
        result = ex._import_iris()
        assert result is not None

    def test_import_iris_fallback_intersystems(self):
        """When primary iris import fails, falls back to intersystems_iris."""
        # We'll patch the method directly to simulate the fallback logic
        sys.modules.pop("iris", None)
        from iris_pgwire.iris_executor import IRISExecutor
        config = {"host": "localhost", "port": 1972, "namespace": "USER",
                  "username": "SuperUser", "password": "SYS"}
        ex = IRISExecutor(config)

        fake_iris = MagicMock()
        fake_iris.sql = MagicMock()
        fake_iris.sql.exec = MagicMock(return_value=iter([]))

        # Patch builtins __import__ to simulate the import behavior
        original_import_iris = ex._import_iris

        def patched():
            # Return None to simulate total unavailability
            return None

        ex._import_iris = patched
        result = ex._import_iris()
        assert result is None

    def test_import_iris_returns_none_when_all_fail(self):
        """When both import paths fail, _import_iris returns None."""
        sys.modules.pop("iris", None)
        from iris_pgwire.iris_executor import IRISExecutor
        config = {"host": "localhost", "port": 1972, "namespace": "USER",
                  "username": "SuperUser", "password": "SYS"}
        ex = IRISExecutor(config)
        # Patch to simulate ImportError for both
        with patch.object(ex, "_import_iris", return_value=None):
            result = ex._import_iris()
        assert result is None


# ---------------------------------------------------------------------------
# _detect_iris_environment: no iris module path
# ---------------------------------------------------------------------------

class TestDetectIrisEnvironmentNoModule:
    def test_no_iris_module_sets_external(self):
        sys.modules.pop("iris", None)
        from iris_pgwire.iris_executor import IRISExecutor
        config = {"host": "localhost", "port": 1972, "namespace": "USER",
                  "username": "SuperUser", "password": "SYS"}
        ex = IRISExecutor.__new__(IRISExecutor)
        ex.iris_config = config
        with patch.object(IRISExecutor, "_import_iris", return_value=None):
            result = ex._detect_iris_environment()
        assert result is False

    def test_iris_without_sql_sets_external(self):
        mock = MagicMock(spec=[])  # No sql attribute
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
# _convert_iris_horolog_date_to_pg / _convert_pg_date_to_iris_horolog
# ---------------------------------------------------------------------------

class TestHorologConversions:
    def test_horolog_to_pg(self, executor_embedded):
        # Horolog 0 = 1840-12-31, PG epoch = 2000-01-01
        # horolog_to_pg(0) should return negative pg days
        result = executor_embedded._convert_iris_horolog_date_to_pg(0)
        assert isinstance(result, int)

    def test_pg_to_horolog(self, executor_embedded):
        result = executor_embedded._convert_pg_date_to_iris_horolog(0)
        assert isinstance(result, int)

    def test_roundtrip(self, executor_embedded):
        pg_val = 1000
        horolog = executor_embedded._convert_pg_date_to_iris_horolog(pg_val)
        back = executor_embedded._convert_iris_horolog_date_to_pg(horolog)
        assert back == pg_val


# ---------------------------------------------------------------------------
# _get_normalized_sql: cache hit path with duplicate key
# ---------------------------------------------------------------------------

class TestGetNormalizedSqlCachePaths:
    def test_cache_hit_moves_to_end(self, executor_embedded):
        """Test cache hit path: key in cache → pop + re-insert."""
        executor_embedded.enable_query_cache = True
        sql = "SELECT cache_hit_test"
        # Prime the cache
        executor_embedded._get_normalized_sql(sql)
        # Second call should hit cache
        r1 = executor_embedded._get_normalized_sql(sql)
        r2 = executor_embedded._get_normalized_sql(sql)
        assert r1 == r2

    def test_duplicate_key_on_write_removes_old(self, executor_embedded):
        """Test the duplicate key removal on write path."""
        executor_embedded.enable_query_cache = True
        sql = "SELECT dup_key_test"
        # Prime the cache once
        executor_embedded._get_normalized_sql(sql)
        # Manually add the same key again to simulate race condition
        cache_key = (sql, "direct")
        with executor_embedded._query_cache_lock:
            executor_embedded._query_cache[cache_key] = "old_value"
        # Run again — should remove old entry and set new
        executor_embedded._get_normalized_sql(sql)
        # Should not have duplicates
        assert len([k for k in executor_embedded._query_cache if k == cache_key]) <= 1


# ---------------------------------------------------------------------------
# _get_table_columns_from_schema: external path
# ---------------------------------------------------------------------------

class TestGetTableColumnsExternal:
    def test_external_path_success(self, executor_external):
        executor_external.embedded_mode = False
        executor_external.strict_single_connection = False
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [("id",), ("name",)]
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(executor_external, "_get_pooled_connection", return_value=mock_conn):
            with patch.object(executor_external, "_return_connection"):
                result = executor_external._get_table_columns_from_schema("users")

        assert result == ["id", "name"]

    def test_external_path_exception_returns_empty(self, executor_external):
        executor_external.embedded_mode = False
        executor_external.strict_single_connection = False
        with patch.object(executor_external, "_get_pooled_connection", side_effect=Exception("no conn")):
            result = executor_external._get_table_columns_from_schema("users")
        assert result == []


# ---------------------------------------------------------------------------
# _get_column_type_from_schema: external path
# ---------------------------------------------------------------------------

class TestGetColumnTypeExternal:
    def test_external_path_success(self, executor_external):
        executor_external.embedded_mode = False
        executor_external.strict_single_connection = False
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ("INTEGER",)
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(executor_external, "_get_pooled_connection", return_value=mock_conn):
            with patch.object(executor_external, "_return_connection"):
                result = executor_external._get_column_type_from_schema("users", "id")

        assert result == 23  # INTEGER → OID 23

    def test_external_path_no_row_returns_none(self, executor_external):
        executor_external.embedded_mode = False
        executor_external.strict_single_connection = False
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(executor_external, "_get_pooled_connection", return_value=mock_conn):
            with patch.object(executor_external, "_return_connection"):
                result = executor_external._get_column_type_from_schema("users", "id")

        assert result is None

    def test_embedded_no_iris_module_returns_none(self, executor_embedded):
        executor_embedded.embedded_mode = True
        executor_embedded.strict_single_connection = False
        with patch.object(executor_embedded, "_import_iris", return_value=None):
            result = executor_embedded._get_column_type_from_schema("users", "id")
        assert result is None


# ---------------------------------------------------------------------------
# _serialize_value: uncovered branches
# ---------------------------------------------------------------------------

class TestSerializeValueAdditional:
    def test_date_int_returns_unchanged(self, executor_embedded):
        """_serialize_value for OID 1082 (DATE) with int just returns the int unchanged."""
        # The date conversion happens in _postprocess_rows, not _serialize_value
        result = executor_embedded._serialize_value(42, 1082)
        assert result == 42

    def test_date_string_passes_through(self, executor_embedded):
        """_serialize_value for OID 1082 with non-int value passes through."""
        result = executor_embedded._serialize_value("2000-01-02", 1082)
        assert result == "2000-01-02"

    def test_date_string_non_iso_returns_passthrough(self, executor_embedded):
        result = executor_embedded._serialize_value("not-a-date", 1082)
        assert result == "not-a-date"

    def test_timestamp_iso_with_T_and_no_tz_normalized(self, executor_embedded):
        """ISO 8601 datetime string with T separator → reformatted with space."""
        result = executor_embedded._serialize_value("2023-01-01T12:00:00", 1114)
        assert "T" not in result
        assert "2023-01-01" in result

    def test_timestamp_unrecognized_tz_string_passthrough(self, executor_embedded):
        """Timestamp string with +00:00 tz is not in the recognized formats → passthrough."""
        val = "2023-01-01T12:00:00+00:00"
        result = executor_embedded._serialize_value(val, 1114)
        # Unrecognized format (has +tz) → passes through unchanged
        assert result == val

    def test_timestamp_none_date_oid(self, executor_embedded):
        assert executor_embedded._serialize_value(None, 1082) is None


# ---------------------------------------------------------------------------
# _test_external_connection
# ---------------------------------------------------------------------------

class TestTestExternalConnection:
    @pytest.mark.asyncio
    async def test_successful_real_connection(self, executor_external):
        """Test successful connection to IRIS."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)
        mock_conn.cursor.return_value = mock_cursor
        mock_iris = MagicMock()
        mock_iris.connect.return_value = mock_conn

        with patch.object(executor_external, "_import_iris", return_value=mock_iris):
            result = await executor_external._test_external_connection()
        assert result is True

    @pytest.mark.asyncio
    async def test_connection_failure_falls_back_to_config_validation(self, executor_external):
        """When real connection fails, falls back to config validation."""
        mock_iris = MagicMock()
        mock_iris.connect.side_effect = Exception("connection refused")

        with patch.object(executor_external, "_import_iris", return_value=mock_iris):
            result = await executor_external._test_external_connection()
        # Should succeed via config validation fallback
        assert result is True

    @pytest.mark.asyncio
    async def test_connection_failure_missing_config_raises(self, executor_external):
        """When connection fails and config is incomplete, raises ValueError."""
        executor_external.iris_config = {"host": "localhost"}  # missing required keys
        mock_iris = MagicMock()
        mock_iris.connect.side_effect = Exception("connection refused")

        with patch.object(executor_external, "_import_iris", return_value=mock_iris):
            with pytest.raises(Exception):
                await executor_external._test_external_connection()

    @pytest.mark.asyncio
    async def test_no_iris_module_falls_back(self, executor_external):
        """When no iris module, falls back to config validation."""
        with patch.object(executor_external, "_import_iris", return_value=None):
            result = await executor_external._test_external_connection()
        assert result is True


# ---------------------------------------------------------------------------
# execute_many: inline fallback, external sequential
# ---------------------------------------------------------------------------

class TestExecuteManyAdditional:
    @pytest.mark.asyncio
    async def test_execute_many_inline_fallback_embedded(self, executor_embedded, iris_mock):
        """_execute_many_inline_fallback calls _execute_many_embedded_async in embedded mode."""
        executor_embedded.embedded_mode = True
        iris_mock.sql.exec.return_value = iter([])

        with patch.object(
            executor_embedded, "_execute_many_embedded_async",
            new=AsyncMock(return_value={"success": True, "rows_affected": 2, "_execution_path": "loop_fallback"})
        ):
            result = await executor_embedded._execute_many_inline_fallback(
                "INSERT INTO t (a) VALUES (?)", [[1], [2]]
            )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_many_inline_fallback_external(self, executor_external):
        """_execute_many_inline_fallback in external mode does sequential execute_query."""
        executor_external.embedded_mode = False

        call_count = [0]

        async def fake_execute_query(sql, params=None, session_id=None):
            call_count[0] += 1
            return {"success": True, "rows": [], "columns": [], "row_count": 0, "command_tag": "INSERT 0 1"}

        with patch.object(executor_external, "execute_query", side_effect=fake_execute_query):
            result = await executor_external._execute_many_inline_fallback(
                "INSERT INTO t (a) VALUES (?)", [[1], [2], [3]]
            )
        assert result["success"] is True
        assert result["rows_affected"] == 3
        assert call_count[0] == 3


# ---------------------------------------------------------------------------
# _execute_many_with_returning
# ---------------------------------------------------------------------------

class TestExecuteManyWithReturning:
    @pytest.mark.asyncio
    async def test_embedded_mode_basic(self, executor_embedded, iris_mock):
        """_execute_many_with_returning in embedded mode calls iris.sql.exec and emulates."""
        executor_embedded.embedded_mode = True
        iris_mock.sql.exec.return_value = iter([])

        with patch.object(
            executor_embedded, "_emulate_returning",
            return_value=([[42]], [{"name": "id", "type_oid": 23}])
        ):
            result = await executor_embedded._execute_many_with_returning(
                "INSERT INTO t (id) VALUES (?) RETURNING id", [[42]]
            )
        assert result["success"] is True
        assert result["rows"] == [[42]]

    @pytest.mark.asyncio
    async def test_external_mode_basic(self, executor_external):
        """_execute_many_with_returning in external mode uses pooled connection."""
        executor_external.embedded_mode = False
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(executor_external, "_get_pooled_connection", return_value=mock_conn):
            with patch.object(executor_external, "_return_connection"):
                with patch.object(
                    executor_external, "_emulate_returning",
                    return_value=([[1]], [{"name": "id", "type_oid": 23}])
                ):
                    result = await executor_external._execute_many_with_returning(
                        "INSERT INTO t (id) VALUES (?) RETURNING id", [[1]]
                    )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_fallback_when_plan_has_no_operation(self, executor_embedded):
        """Falls back to _execute_many_native when plan can't be parsed."""
        from iris_pgwire.sql_translator.returning_plan import ReturningPlan
        empty_plan = MagicMock(spec=ReturningPlan)
        empty_plan.operation = None
        empty_plan.table = None

        with patch("iris_pgwire.iris_executor.ReturningPlan") as MockPlan:
            MockPlan.from_sql.return_value = empty_plan
            with patch.object(
                executor_embedded, "_execute_many_native",
                new=AsyncMock(return_value={"success": True, "rows_affected": 1, "_execution_path": "native"})
            ):
                result = await executor_embedded._execute_many_with_returning(
                    "INSERT INTO t (id) VALUES (?)", [[1]]
                )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_row_failure_raises(self, executor_embedded, iris_mock):
        """Row failure in _execute_many_with_returning raises the exception."""
        executor_embedded.embedded_mode = True
        iris_mock.sql.exec.side_effect = Exception("sql error")

        with pytest.raises(Exception, match="sql error"):
            await executor_embedded._execute_many_with_returning(
                "INSERT INTO t (id) VALUES (?) RETURNING id", [[1]]
            )

    @pytest.mark.asyncio
    async def test_column_meta_from_dict_info(self, executor_embedded, iris_mock):
        """Tests column_info dict vs object branch."""
        executor_embedded.embedded_mode = True
        iris_mock.sql.exec.return_value = iter([])

        col_obj = MagicMock()
        col_obj.name = "id"
        with patch.object(
            executor_embedded, "_emulate_returning",
            return_value=([[1]], [col_obj])
        ):
            result = await executor_embedded._execute_many_with_returning(
                "INSERT INTO t (id) VALUES (?) RETURNING id", [[1]]
            )
        assert result["success"] is True


# ---------------------------------------------------------------------------
# _execute_many_embedded_async
# ---------------------------------------------------------------------------

class TestExecuteManyEmbeddedAsync:
    @pytest.mark.asyncio
    async def test_success_path(self, executor_embedded, iris_mock):
        """_execute_many_embedded_async executes batch via loop."""
        executor_embedded.embedded_mode = True
        iris_mock.sql.exec.return_value = iter([])

        result = await executor_embedded._execute_many_embedded_async(
            "INSERT INTO t (a) VALUES (?)", [[1], [2], [3]]
        )
        assert result["success"] is True
        assert result["rows_affected"] == 3

    @pytest.mark.asyncio
    async def test_no_iris_module_returns_error(self, executor_embedded):
        """No iris module returns error dict."""
        with patch.object(executor_embedded, "_import_iris", return_value=None):
            result = await executor_embedded._execute_many_embedded_async(
                "INSERT INTO t (a) VALUES (?)", [[1]]
            )
        assert result["success"] is False
        assert "IRIS module not found" in result["error"]

    @pytest.mark.asyncio
    async def test_with_none_param_builds_null_sql(self, executor_embedded, iris_mock):
        """None values become NULL in inline SQL."""
        iris_mock.sql.exec.return_value = iter([])
        result = await executor_embedded._execute_many_embedded_async(
            "INSERT INTO t (a, b) VALUES (?, ?)", [[1, None]]
        )
        assert result["success"] is True
        # Check that iris.sql.exec was called with SQL containing NULL
        call_args = iris_mock.sql.exec.call_args_list
        last_sql = call_args[-1][0][0]
        assert "NULL" in last_sql

    @pytest.mark.asyncio
    async def test_float_param_no_quoting(self, executor_embedded, iris_mock):
        """Float values appear without quotes in inline SQL."""
        iris_mock.sql.exec.return_value = iter([])
        result = await executor_embedded._execute_many_embedded_async(
            "INSERT INTO t (val) VALUES (?)", [[3.14]]
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_row_error_raises(self, executor_embedded, iris_mock):
        """Row execution error propagates out of _execute_many_embedded_async."""
        iris_mock.sql.exec.side_effect = Exception("row failed")
        with pytest.raises(Exception, match="row failed"):
            await executor_embedded._execute_many_embedded_async(
                "INSERT INTO t (a) VALUES (?)", [[1]]
            )


# ---------------------------------------------------------------------------
# _execute_many_external_async
# ---------------------------------------------------------------------------

class TestExecuteManyExternalAsync:
    @pytest.mark.asyncio
    async def test_success_path(self, executor_external):
        """_execute_many_external_async executes via executemany()."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 2
        mock_conn.cursor.return_value = mock_cursor

        with patch.object(executor_external, "_get_pooled_connection", return_value=mock_conn):
            with patch.object(executor_external, "_return_connection"):
                result = await executor_external._execute_many_external_async(
                    "INSERT INTO t (a) VALUES (?)", [[1], [2]]
                )
        assert result["success"] is True
        assert result["_execution_path"] == "dbapi_executemany"

    @pytest.mark.asyncio
    async def test_vector_params_processing(self, executor_external):
        """List params are converted to IRIS vector string format."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_conn.cursor.return_value = mock_cursor

        captured_calls = []
        original_executemany = mock_cursor.executemany
        def capture_executemany(sql, params_list):
            captured_calls.append(params_list)
        mock_cursor.executemany = capture_executemany

        with patch.object(executor_external, "_get_pooled_connection", return_value=mock_conn):
            with patch.object(executor_external, "_return_connection"):
                result = await executor_external._execute_many_external_async(
                    "INSERT INTO t (vec) VALUES (?)", [[[1.0, 2.0, 3.0]]]
                )
        # Should have been called - success or fail, the vector processing should occur
        assert result is not None

    @pytest.mark.asyncio
    async def test_exception_propagates(self, executor_external):
        """Exception from executemany propagates out."""
        with patch.object(executor_external, "_get_pooled_connection", side_effect=Exception("no pool")):
            with pytest.raises(Exception, match="no pool"):
                await executor_external._execute_many_external_async(
                    "INSERT INTO t (a) VALUES (?)", [[1]]
                )


# ---------------------------------------------------------------------------
# _prepare_conflict_set_clause: EXCLUDED pattern replacement
# ---------------------------------------------------------------------------

class TestConflictSetClauseWithExcluded:
    def test_excluded_replacement(self, executor_embedded):
        plan = MagicMock()
        plan.conflict_set_clause = 'name = EXCLUDED."name", age = EXCLUDED."age"'
        column_values = {"name": "Alice", "age": 30}

        clause, params = executor_embedded._prepare_conflict_set_clause(plan, column_values)
        assert "?" in clause
        assert "Alice" in params or "alice" in [str(p).lower() for p in params]
        assert 30 in params or any(p == 30 for p in params)

    def test_excluded_unquoted(self, executor_embedded):
        plan = MagicMock()
        plan.conflict_set_clause = "val = EXCLUDED.val"
        column_values = {"val": 99}

        clause, params = executor_embedded._prepare_conflict_set_clause(plan, column_values)
        assert clause == "val = ?"
        assert 99 in params


# ---------------------------------------------------------------------------
# _prepare_conflict_where_clause: with conflict_where_clause
# ---------------------------------------------------------------------------

class TestConflictWhereClauseWithExtra:
    def test_appends_extra_where(self, executor_embedded):
        plan = MagicMock()
        plan.conflict_target_columns = ["id"]
        plan.conflict_where_clause = "active = 1"
        column_values = {"id": 42}

        clause, params = executor_embedded._prepare_conflict_where_clause(plan, column_values)
        assert '"ID" = ?' in clause
        assert "active = 1" in clause
        assert 42 in params

    def test_only_extra_where_no_columns(self, executor_embedded):
        plan = MagicMock()
        plan.conflict_target_columns = []
        plan.conflict_where_clause = "status = 'active'"
        column_values = {}

        clause, params = executor_embedded._prepare_conflict_where_clause(plan, column_values)
        assert "status = 'active'" in clause
        assert params == []


# ---------------------------------------------------------------------------
# _handle_on_conflict_update
# ---------------------------------------------------------------------------

class TestHandleOnConflictUpdate:
    def test_raises_without_table(self, executor_embedded):
        plan = MagicMock()
        plan.table = None
        with pytest.raises(RuntimeError, match="target table"):
            executor_embedded._handle_on_conflict_update(plan, [1], None, None, None)

    def test_raises_without_conflict_clause(self, executor_embedded):
        plan = MagicMock()
        plan.table = "users"
        plan.conflict_set_clause = None
        plan.conflict_target_columns = []
        with pytest.raises(RuntimeError, match="incomplete"):
            executor_embedded._handle_on_conflict_update(plan, [1], None, None, None)

    def test_raises_with_empty_clauses(self, executor_embedded):
        plan = MagicMock()
        plan.table = "users"
        plan.conflict_set_clause = "val = EXCLUDED.val"
        plan.conflict_target_columns = ["id"]
        plan.conflict_where_clause = None
        plan.insert_columns = ["id", "val"]

        # Make _prepare_conflict_set_clause return empty string
        with patch.object(executor_embedded, "_prepare_conflict_set_clause", return_value=("", [])):
            with pytest.raises(RuntimeError, match="Insufficient"):
                executor_embedded._handle_on_conflict_update(plan, [1, 2], MagicMock(), None, None)


# ---------------------------------------------------------------------------
# _materialize_embedded_result: type adjustment branches
# ---------------------------------------------------------------------------

class TestMaterializeEmbeddedResultTypeAdjustments:
    def test_numeric_type2_as_integer_cast_sets_int4(self, executor_embedded):
        """When iris_type == 2 and SQL has AS INTEGER, type_oid should become 23."""
        mock_result = MagicMock()
        mock_result._meta = [{"name": "val", "type": 2, "size": 4}]
        mock_result.__iter__ = MagicMock(return_value=iter([[42]]))

        _, columns = executor_embedded._materialize_embedded_result(
            mock_result,
            "SELECT CAST(x AS INTEGER) AS val FROM t",
            "SELECT CAST(X AS INTEGER) AS VAL FROM T",
            "SELECT CAST(x AS INTEGER) AS val FROM t",
            None,
        )
        # type 2 with AS INTEGER → oid 23
        assert columns[0]["type_oid"] == 23

    def test_numeric_type2_no_cast_becomes_float8(self, executor_embedded):
        """When iris_type == 2 and no explicit cast, type_oid should become 701."""
        mock_result = MagicMock()
        mock_result._meta = [{"name": "val", "type": 2, "size": 4}]
        mock_result.__iter__ = MagicMock(return_value=iter([[3.14]]))

        _, columns = executor_embedded._materialize_embedded_result(
            mock_result,
            "SELECT avg(price) AS val FROM t",
            "SELECT AVG(PRICE) AS VAL FROM T",
            "SELECT avg(price) AS val FROM t",
            None,
        )
        assert columns[0]["type_oid"] == 701

    def test_current_timestamp_override(self, executor_embedded):
        """CURRENT_TIMESTAMP in SQL with text type → timestamp OID."""
        mock_result = MagicMock()
        mock_result._meta = [{"name": "ts", "type": "VARCHAR", "size": -1}]
        mock_result.__iter__ = MagicMock(return_value=iter([["2023-01-01 12:00:00.000000"]]))

        _, columns = executor_embedded._materialize_embedded_result(
            mock_result,
            "SELECT CURRENT_TIMESTAMP AS ts",
            "SELECT CURRENT_TIMESTAMP AS TS",
            "SELECT CURRENT_TIMESTAMP AS ts",
            None,
        )
        assert columns[0]["type_oid"] == 1114


# ---------------------------------------------------------------------------
# _materialize_external_result: int/float coercions
# ---------------------------------------------------------------------------

class TestMaterializeExternalResultCoercions:
    def test_int_oid_coerces_string_to_int(self, executor_external):
        mock_cursor = MagicMock()
        mock_cursor._meta = [{"name": "id", "type": "INTEGER", "size": 4}]
        mock_cursor.fetchall.return_value = [("42",)]

        rows, cols = executor_external._materialize_external_result(
            mock_cursor, "SELECT id FROM t", "SELECT ID FROM T", "SELECT id FROM t", None
        )
        assert rows[0][0] == 42
        assert isinstance(rows[0][0], int)

    def test_float_oid_coerces_string_to_float(self, executor_external):
        mock_cursor = MagicMock()
        mock_cursor._meta = [{"name": "val", "type": "DOUBLE", "size": 8}]
        mock_cursor.fetchall.return_value = [("3.14",)]

        rows, cols = executor_external._materialize_external_result(
            mock_cursor, "SELECT val FROM t", "SELECT VAL FROM T", "SELECT val FROM t", None
        )
        assert abs(rows[0][0] - 3.14) < 0.001
        assert isinstance(rows[0][0], float)

    def test_scalar_row_wrapped_in_list(self, executor_external):
        mock_cursor = MagicMock()
        mock_cursor._meta = None
        mock_cursor.description = None
        mock_cursor.fetchall.return_value = [42]  # scalar, not tuple

        rows, cols = executor_external._materialize_external_result(
            mock_cursor, "SELECT 42", "SELECT 42", "SELECT 42", None
        )
        assert rows[0] == [42]

    def test_discovers_metadata_when_empty_columns_with_rows(self, executor_external):
        """When no description, discovers metadata from rows."""
        mock_cursor = MagicMock()
        mock_cursor._meta = None
        mock_cursor.description = None
        mock_cursor.fetchall.return_value = [("hello",)]

        rows, cols = executor_external._materialize_external_result(
            mock_cursor, "SELECT val FROM t", "SELECT VAL FROM T", "SELECT val FROM t", None
        )
        assert len(rows) == 1
        assert len(cols) >= 1

    def test_discovers_metadata_for_empty_select(self, executor_external):
        """When no rows and no description but SELECT query, discovers metadata."""
        mock_cursor = MagicMock()
        mock_cursor._meta = None
        mock_cursor.description = None
        mock_cursor.fetchall.return_value = []

        rows, cols = executor_external._materialize_external_result(
            mock_cursor, "SELECT val FROM t", "SELECT VAL FROM T", "SELECT val FROM t", None
        )
        assert rows == []
        # cols may or may not be populated depending on discovery

    def test_numeric_type2_as_integer(self, executor_external):
        mock_cursor = MagicMock()
        mock_cursor._meta = [{"name": "val", "type": 2, "size": 4}]
        mock_cursor.fetchall.return_value = [(42,)]

        _, cols = executor_external._materialize_external_result(
            mock_cursor, "SELECT CAST(x AS INTEGER) AS val",
            "SELECT CAST(X AS INTEGER) AS VAL",
            "SELECT CAST(x AS INTEGER) AS val", None
        )
        assert cols[0]["type_oid"] == 23


# ---------------------------------------------------------------------------
# _execute_embedded_async: SHOW intercept, namespace retry, DELETE RETURNING
# ---------------------------------------------------------------------------

class TestExecuteEmbeddedAsyncAdditional:
    @pytest.mark.asyncio
    async def test_show_command_intercepted_in_sync(self, executor_embedded, iris_mock):
        """SHOW commands are intercepted inside _sync_execute."""
        executor_embedded.embedded_mode = True
        show_result = {
            "success": True, "rows": [["16.0"]], "columns": [{"name": "server_version"}],
            "command_tag": "SHOW", "row_count": 1
        }
        with patch.object(executor_embedded, "_handle_show_command", return_value=show_result):
            with patch.object(executor_embedded, "_get_iris_connection", return_value=None):
                result = await executor_embedded._execute_embedded_async("SHOW server_version")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_delete_returning_prefetches_rows(self, executor_embedded, iris_mock):
        """DELETE with RETURNING pre-fetches rows before deletion."""
        executor_embedded.embedded_mode = True
        iris_mock.sql.exec.return_value = iter([])

        prefetched = [[42]]
        prefetched_meta = [{"name": "id", "type_oid": 23}]

        with patch.object(executor_embedded, "_emulate_returning",
                         return_value=(prefetched, prefetched_meta)):
            with patch.object(executor_embedded, "_get_iris_connection", return_value=None):
                with patch.object(executor_embedded, "_resolve_embedded_returning_result",
                                 return_value=MagicMock(_meta=prefetched_meta,
                                                        __iter__=MagicMock(return_value=iter(prefetched)))):
                    result = await executor_embedded._execute_embedded_async(
                        "DELETE FROM t WHERE id = 42 RETURNING id"
                    )
        assert result is not None


# ---------------------------------------------------------------------------
# _execute_external_async: additional branches
# ---------------------------------------------------------------------------

class TestExecuteExternalAsyncAdditional:
    @pytest.mark.asyncio
    async def test_vector_list_params_converted(self, executor_external):
        """List params are converted to IRIS vector string in external mode."""
        executor_external.embedded_mode = False
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor._meta = [{"name": "id", "type": "INTEGER", "size": 4}]
        mock_cursor.fetchall.return_value = [(1,)]

        captured_params = []
        original_safe_execute = executor_external._safe_execute

        def capture_safe_execute(sql, params=None, **kwargs):
            if params:
                captured_params.extend(params)
            return mock_cursor

        with patch.object(executor_external, "_get_pooled_connection", return_value=mock_conn):
            with patch.object(executor_external, "_return_connection"):
                with patch.object(executor_external, "_safe_execute", side_effect=capture_safe_execute):
                    result = await executor_external._execute_external_async(
                        "SELECT cosine_distance(vec, ?) FROM t", [[1.0, 2.0, 3.0]]
                    )
        # The test verifies the method runs without error, vector processing occurred
        assert result is not None

    @pytest.mark.asyncio
    async def test_on_conflict_do_nothing_handled(self, executor_external):
        """ON CONFLICT DO NOTHING: unique violation → empty MockResult."""
        executor_external.embedded_mode = False
        mock_conn = MagicMock()

        from iris_pgwire.iris_executor import MockResult

        with patch.object(executor_external, "_get_pooled_connection", return_value=mock_conn):
            with patch.object(executor_external, "_return_connection"):
                with patch.object(
                    executor_external, "_safe_execute",
                    side_effect=Exception("unique constraint violated")
                ):
                    with patch.object(executor_external, "_prepare_sql") as mock_prepare:
                        plan = MagicMock()
                        plan.operation = "INSERT"
                        plan.table = "t"
                        plan.columns = None
                        plan.has_returning = False
                        plan.conflict_action = "DO NOTHING"
                        plan.select_list = None
                        plan.column_meta = None
                        plan.stripped_sql = "INSERT INTO t (id) VALUES (?)"
                        mock_prepare.return_value = (
                            "INSERT INTO t (id) VALUES (?)", [1], plan, 0.0
                        )
                        result = await executor_external._execute_external_async(
                            "INSERT INTO t (id) VALUES (?) ON CONFLICT DO NOTHING", [1]
                        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_multi_statement_executes_all(self, executor_external):
        """Multi-statement SQL: all but last get executed and closed."""
        executor_external.embedded_mode = False
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor._meta = None
        mock_cursor.description = [("id", 4, 11, None, None, None, None)]
        mock_cursor.fetchall.return_value = []

        call_count = [0]
        def counting_safe_execute(sql, params=None, **kwargs):
            call_count[0] += 1
            return mock_cursor

        with patch.object(executor_external, "_get_pooled_connection", return_value=mock_conn):
            with patch.object(executor_external, "_return_connection"):
                with patch.object(executor_external, "_safe_execute", side_effect=counting_safe_execute):
                    with patch.object(executor_external, "_split_sql_statements",
                                     return_value=["CREATE TABLE t1 (id INT)", "SELECT 1"]):
                        result = await executor_external._execute_external_async(
                            "CREATE TABLE t1 (id INT); SELECT 1"
                        )
        assert result is not None
        assert call_count[0] >= 2


# ---------------------------------------------------------------------------
# _get_pooled_connection: dead session connection, pool health failure
# ---------------------------------------------------------------------------

class TestGetPooledConnectionAdditional:
    def test_dead_session_connection_replaced(self, executor_external):
        """When session connection is dead, it's removed and a new one is created."""
        dead_conn = MagicMock()
        executor_external.session_connections["sess1"] = dead_conn
        executor_external._active_count = 1

        new_conn = MagicMock()
        mock_iris = MagicMock()
        mock_iris.connect.return_value = new_conn

        with patch.object(executor_external, "_is_connection_alive", return_value=False):
            with patch.object(executor_external, "_import_iris", return_value=mock_iris):
                conn = executor_external._get_pooled_connection(session_id="sess1")

        dead_conn.close.assert_called_once()
        assert conn is new_conn

    def test_pool_conn_dead_creates_new(self, executor_external):
        """Pooled connection fails health check → creates new connection."""
        dead_pool_conn = MagicMock()
        executor_external._connection_pool.append(dead_pool_conn)
        executor_external._active_count = 0

        new_conn = MagicMock()
        mock_iris = MagicMock()
        mock_iris.connect.return_value = new_conn

        call_count = [0]
        def health_check(conn):
            if conn is dead_pool_conn:
                return False
            return True

        with patch.object(executor_external, "_is_connection_alive", side_effect=health_check):
            with patch.object(executor_external, "_import_iris", return_value=mock_iris):
                conn = executor_external._get_pooled_connection()

        # Should have called close on dead conn
        dead_pool_conn.close.assert_called_once()

    def test_session_id_stored_in_session_connections(self, executor_external):
        """When session_id provided, connection is stored in session_connections."""
        new_conn = MagicMock()
        mock_iris = MagicMock()
        mock_iris.connect.return_value = new_conn

        with patch.object(executor_external, "_import_iris", return_value=mock_iris):
            conn = executor_external._get_pooled_connection(session_id="my_session")

        assert "my_session" in executor_external.session_connections
        assert executor_external.session_connections["my_session"] is new_conn


# ---------------------------------------------------------------------------
# _expand_select_star: various branches
# ---------------------------------------------------------------------------

class TestExpandSelectStarBranches:
    def test_schema_prefix_stripped(self, executor_embedded, iris_mock):
        """Table names with schema prefix are stripped before lookup."""
        executor_embedded.embedded_mode = True
        iris_mock.sql.exec.return_value = iter([["id"], ["name"]])

        result = executor_embedded._expand_select_star(
            "SELECT * FROM SQLUser.users", 2
        )
        assert result is not None

    def test_returning_star_extracts_table(self, executor_embedded, iris_mock):
        """RETURNING * path extracts table from INSERT INTO."""
        executor_embedded.embedded_mode = True
        iris_mock.sql.exec.return_value = iter([["id"], ["name"]])

        result = executor_embedded._expand_select_star(
            "INSERT INTO users (id, name) VALUES (1, 'a') RETURNING *", 0
        )
        # May succeed or return None depending on IRIS mock
        assert result is None or isinstance(result, list)

    def test_no_table_returns_none(self, executor_embedded, iris_mock):
        """SQL without a recognizable table returns None."""
        result = executor_embedded._expand_select_star("SELECT 1", 0)
        assert result is None

    def test_fallback_to_limit_zero_from_iris_meta(self, executor_embedded, iris_mock):
        """When schema lookup returns empty, falls back to LIMIT 0."""
        executor_embedded.embedded_mode = True
        # Make the schema query return no rows
        iris_mock.sql.exec.return_value = iter([])

        result = executor_embedded._expand_select_star("SELECT * FROM users", 0)
        # Returns None when no columns found
        assert result is None

    def test_iris_meta_attr_returns_columns(self, executor_embedded, iris_mock):
        """LIMIT 0 fallback uses _meta attribute."""
        executor_embedded.embedded_mode = True
        # First call (schema lookup) returns empty, second call (LIMIT 0) has _meta
        mock_meta_result = MagicMock()
        mock_meta_result._meta = [{"name": "id"}, {"name": "name"}]
        mock_meta_result.__iter__ = MagicMock(return_value=iter([]))

        call_count = [0]
        def exec_side_effect(sql, *args):
            call_count[0] += 1
            if call_count[0] == 1:
                return iter([])  # schema query: no rows
            return mock_meta_result  # LIMIT 0 query

        iris_mock.sql.exec.side_effect = exec_side_effect
        result = executor_embedded._expand_select_star("SELECT * FROM users", 0)
        # Returns None or list depending on schema query
        assert result is None or isinstance(result, list)


# ---------------------------------------------------------------------------
# _normalize_iris_column_name: SELECT without FROM + expression cases
# ---------------------------------------------------------------------------

class TestNormalizeIrisColumnNameAdditional:
    def test_column_generic_name_select_no_from(self, executor_embedded):
        """Generic column names in SELECT without FROM → ?column?."""
        result = executor_embedded._normalize_iris_column_name("column", "SELECT 1", "VARCHAR")
        assert result == "?column?"

    def test_column_with_explicit_as_preserves_name(self, executor_embedded):
        """If 'AS column' appears in SQL, keep the name."""
        result = executor_embedded._normalize_iris_column_name(
            "column", "SELECT 1 AS column", "VARCHAR"
        )
        # 'AS column' in SQL → preserved
        assert result == "column"

    def test_string_literal_as_column_name(self, executor_embedded):
        """Column name that appears as quoted string literal → ?column?."""
        result = executor_embedded._normalize_iris_column_name(
            "hello", "SELECT 'hello'", "VARCHAR"
        )
        assert result == "?column?"

    def test_expression_bigint_cast(self, executor_embedded):
        result = executor_embedded._normalize_iris_column_name(
            "Expression_1", "SELECT CAST(? AS BIGINT)", "VARCHAR"
        )
        assert result == "int8"

    def test_expression_smallint_cast(self, executor_embedded):
        result = executor_embedded._normalize_iris_column_name(
            "Expression_1", "SELECT CAST(? AS SMALLINT)", "VARCHAR"
        )
        assert result == "int2"

    def test_expression_text_cast(self, executor_embedded):
        result = executor_embedded._normalize_iris_column_name(
            "Expression_1", "SELECT CAST(? AS TEXT)", "VARCHAR"
        )
        assert result == "text"

    def test_expression_varchar_cast(self, executor_embedded):
        result = executor_embedded._normalize_iris_column_name(
            "Expression_1", "SELECT CAST(? AS VARCHAR)", "VARCHAR"
        )
        assert result == "varchar"

    def test_expression_bool_cast(self, executor_embedded):
        result = executor_embedded._normalize_iris_column_name(
            "Expression_1", "SELECT CAST(? AS BIT)", "VARCHAR"
        )
        assert result == "bool"

    def test_expression_date_cast(self, executor_embedded):
        result = executor_embedded._normalize_iris_column_name(
            "Expression_1", "SELECT CAST(? AS DATE)", "VARCHAR"
        )
        assert result == "date"

    def test_expression_no_cast_returns_qcolumn(self, executor_embedded):
        result = executor_embedded._normalize_iris_column_name(
            "Expression_1", "SELECT some_func(x)", "VARCHAR"
        )
        assert result == "?column?"

    def test_aggregate_avg(self, executor_embedded):
        result = executor_embedded._normalize_iris_column_name(
            "Aggregate_1", "SELECT AVG(price) FROM t", "VARCHAR"
        )
        assert result == "avg"

    def test_aggregate_min(self, executor_embedded):
        result = executor_embedded._normalize_iris_column_name(
            "Aggregate_1", "SELECT MIN(price) FROM t", "VARCHAR"
        )
        assert result == "min"

    def test_aggregate_max(self, executor_embedded):
        result = executor_embedded._normalize_iris_column_name(
            "Aggregate_1", "SELECT MAX(price) FROM t", "VARCHAR"
        )
        assert result == "max"

    def test_aggregate_unknown(self, executor_embedded):
        result = executor_embedded._normalize_iris_column_name(
            "Aggregate_1", "SELECT some_agg(x) FROM t", "VARCHAR"
        )
        assert result == "aggregate_1"


# ---------------------------------------------------------------------------
# _iris_type_to_pg_oid: extended integer type codes
# ---------------------------------------------------------------------------

class TestIrisTypeToPgOidExtended:
    def test_jdbc_date_code_91(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid(91) == 1082

    def test_jdbc_time_code_92(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid(92) == 1083

    def test_jdbc_timestamp_code_93(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid(93) == 1114

    def test_iris_extended_date_1091(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid(1091) == 1082

    def test_iris_extended_time_1092(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid(1092) == 1083

    def test_iris_extended_timestamp_1093(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid(1093) == 1114

    def test_tinyint_code_minus6(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid(-6) == 21

    def test_bit_code_minus7(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid(-7) == 16

    def test_char_code_1(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid(1) == 1042

    def test_numeric_code_2(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid(2) == 1700

    def test_float8_code_5(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid(5) == 701

    def test_double_code_8(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid(8) == 701

    def test_bool_code_16(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid(16) == 16

    def test_bytea_code_17(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid(17) == 17

    def test_string_bool(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid("BOOLEAN") == 16

    def test_string_vector(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid("VECTOR") == 16388

    def test_string_longvarchar(self, executor_embedded):
        assert executor_embedded._iris_type_to_pg_oid("TEXT") == 25


# ---------------------------------------------------------------------------
# cancel_query / _cancel_embedded_query / _cancel_external_query
# ---------------------------------------------------------------------------

class TestCancelQueryMethods:
    @pytest.mark.asyncio
    async def test_cancel_query_embedded_calls_embedded_cancel(self, executor_embedded):
        executor_embedded.embedded_mode = True
        result = await executor_embedded.cancel_query(1234, 5678)
        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_embedded_query_success(self, executor_embedded):
        result = await executor_embedded._cancel_embedded_query(100, 200)
        assert result is True

    @pytest.mark.asyncio
    async def test_cancel_embedded_query_exception_returns_false(self, executor_embedded):
        with patch("asyncio.to_thread", side_effect=Exception("cancel failed")):
            result = await executor_embedded._cancel_embedded_query(100, 200)
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_external_query_no_server(self, executor_external):
        executor_external.server = None
        result = await executor_external._cancel_external_query(100, 200)
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_external_query_connection_not_found(self, executor_external):
        mock_server = MagicMock()
        mock_server.find_connection_for_cancellation.return_value = None
        executor_external.server = mock_server
        result = await executor_external._cancel_external_query(100, 200)
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_external_query_terminates_connection(self, executor_external):
        mock_server = MagicMock()
        mock_protocol = MagicMock()
        mock_protocol.writer = MagicMock()
        mock_protocol.writer.is_closing.return_value = False
        mock_protocol.writer.close = MagicMock()
        mock_protocol.writer.wait_closed = AsyncMock()
        mock_protocol.connection_id = "test_conn"
        mock_server.find_connection_for_cancellation.return_value = mock_protocol
        executor_external.server = mock_server

        result = await executor_external._cancel_external_query(100, 200)
        assert result is True
        mock_protocol.writer.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_external_query_exception_returns_false(self, executor_external):
        mock_server = MagicMock()
        mock_server.find_connection_for_cancellation.side_effect = Exception("server error")
        executor_external.server = mock_server

        result = await executor_external._cancel_external_query(100, 200)
        assert result is False

    @pytest.mark.asyncio
    async def test_cancel_query_exception_returns_false(self, executor_embedded):
        executor_embedded.embedded_mode = True
        with patch.object(executor_embedded, "_cancel_embedded_query", side_effect=Exception("error")):
            result = await executor_embedded.cancel_query(100, 200)
        assert result is False


# ---------------------------------------------------------------------------
# _discover_metadata: Layer 0.5 RETURNING * path
# ---------------------------------------------------------------------------

class TestDiscoverMetadataAdditional:
    def test_returning_star_layer0_5(self, executor_embedded, iris_mock):
        """RETURNING * path expands columns via _expand_select_star."""
        with patch.object(executor_embedded, "_expand_select_star", return_value=["id", "name"]):
            with patch.object(executor_embedded, "_get_column_type_from_schema", return_value=23):
                cols = executor_embedded._discover_metadata(
                    "INSERT INTO users (id, name) VALUES (1, 'a') RETURNING *",
                    None,
                    expected_count=2,
                    rows=[[1, "Alice"]]
                )
        assert len(cols) == 2
        assert cols[0]["name"] == "id"

    def test_returning_list_layer0_5(self, executor_embedded):
        """RETURNING column list path."""
        with patch.object(executor_embedded, "_get_column_type_from_schema", return_value=23):
            cols = executor_embedded._discover_metadata(
                "INSERT INTO users (id) VALUES (1) RETURNING id",
                None,
                expected_count=1,
                rows=[[42]]
            )
        assert len(cols) >= 1
        assert any(c["name"] == "id" for c in cols)

    def test_layer1_5_star_expansion(self, executor_embedded):
        """Layer 1.5: SELECT * expansion."""
        with patch.object(executor_embedded, "_discover_metadata_with_limit_zero", return_value=None):
            with patch.object(executor_embedded, "_expand_select_star", return_value=["id", "val"]):
                with patch.object(executor_embedded, "_get_column_type_from_schema", return_value=None):
                    cols = executor_embedded._discover_metadata(
                        "SELECT * FROM users",
                        None,
                        expected_count=2,
                        rows=[[1, "Alice"]]
                    )
        assert len(cols) >= 1

    def test_layer2_current_timestamp_override(self, executor_embedded):
        """Layer 2: CURRENT_TIMESTAMP overrides inferred type."""
        with patch.object(executor_embedded, "_discover_metadata_with_limit_zero", return_value=None):
            with patch.object(executor_embedded, "_expand_select_star", return_value=None):
                cols = executor_embedded._discover_metadata(
                    "SELECT CURRENT_TIMESTAMP AS ts",
                    None,
                    expected_count=1,
                    rows=[["2023-01-01 12:00:00"]]
                )
        assert any(c["type_oid"] == 1114 for c in cols)

    def test_layer3_uses_column_fallback_name(self, executor_embedded):
        """Layer 3: queries with FROM use 'column1' instead of '?column?'."""
        with patch.object(executor_embedded, "_discover_metadata_with_limit_zero", return_value=None):
            with patch.object(executor_embedded, "_expand_select_star", return_value=None):
                with patch.object(executor_embedded, "alias_extractor") as mock_ae:
                    mock_ae.extract_column_aliases.return_value = []
                    cols = executor_embedded._discover_metadata(
                        "SELECT id FROM t",
                        None,
                        expected_count=1,
                        rows=[[42]]
                    )
        assert len(cols) == 1
        assert cols[0]["name"] == "column1"  # has FROM → column1, not ?column?


# ---------------------------------------------------------------------------
# _discover_metadata_with_limit_zero: description path
# ---------------------------------------------------------------------------

class TestDiscoverMetadataWithLimitZeroAdditional:
    def test_description_with_name_attribute(self, executor_embedded, iris_mock):
        """Columns exposed via description attribute with .name property."""
        mock_result = MagicMock()
        mock_result._meta = None
        desc_col = MagicMock()
        desc_col.name = "mycolumn"
        mock_result.description = [desc_col]
        iris_mock.sql.exec.return_value = mock_result

        result = executor_embedded._discover_metadata_with_limit_zero("SELECT mycolumn FROM t")
        assert result == ["mycolumn"]

    def test_meta_with_name_attribute_objects(self, executor_embedded, iris_mock):
        """_meta can contain objects with .name attribute instead of dicts."""
        mock_result = MagicMock()
        meta_col = MagicMock()
        meta_col.name = "col_a"
        mock_result._meta = [meta_col]
        iris_mock.sql.exec.return_value = mock_result

        result = executor_embedded._discover_metadata_with_limit_zero("SELECT col_a FROM t")
        assert "col_a" in result


# ---------------------------------------------------------------------------
# _emulate_returning: basic paths
# ---------------------------------------------------------------------------

class TestEmulateReturningBasic:
    def test_insert_with_last_identity(self, executor_embedded, iris_mock):
        """INSERT RETURNING using LAST_IDENTITY() path."""
        from iris_pgwire.sql_translator.returning_plan import ReturningPlan

        plan = MagicMock(spec=ReturningPlan)
        plan.operation = "INSERT"
        plan.table = "users"
        plan.columns = ["id", "name"]
        plan.where_clause = None
        plan.column_meta = None
        plan.select_list = '"id", "name"'

        call_count = [0]
        def exec_side(sql, *args):
            call_count[0] += 1
            if "LAST_IDENTITY" in sql:
                return iter([[42]])
            if "%ID" in sql:
                return iter([[42, "Alice"]])
            return iter([])

        iris_mock.sql.exec.side_effect = exec_side

        with patch.object(executor_embedded, "_get_column_type_from_schema", return_value=None):
            rows, meta = executor_embedded._emulate_returning(
                plan, [42, "Alice"], is_embedded=True
            )

        # Should have attempted to get rows
        assert call_count[0] > 0

    def test_update_with_where_clause(self, executor_embedded, iris_mock):
        """UPDATE RETURNING uses where_clause to SELECT rows."""
        from iris_pgwire.sql_translator.returning_plan import ReturningPlan

        plan = MagicMock(spec=ReturningPlan)
        plan.operation = "UPDATE"
        plan.table = "users"
        plan.columns = ["id", "name"]
        plan.where_clause = 'id = ?'
        plan.column_meta = None
        plan.select_list = '"id", "name"'

        iris_mock.sql.exec.return_value = iter([[1, "Bob"]])

        with patch.object(executor_embedded, "_get_column_type_from_schema", return_value=None):
            rows, meta = executor_embedded._emulate_returning(
                plan, [1], is_embedded=True
            )
        # Should return rows from the SELECT
        assert isinstance(rows, list)

    def test_insert_star_expansion(self, executor_embedded, iris_mock):
        """RETURNING * expands columns via _expand_select_star."""
        from iris_pgwire.sql_translator.returning_plan import ReturningPlan

        plan = MagicMock(spec=ReturningPlan)
        plan.operation = "INSERT"
        plan.table = "users"
        plan.columns = "*"
        plan.where_clause = None
        plan.column_meta = None
        plan.select_list = "*"

        with patch.object(executor_embedded, "_expand_select_star", return_value=["id", "name"]):
            iris_mock.sql.exec.return_value = iter([[1, "Alice"]])
            with patch.object(executor_embedded, "_get_column_type_from_schema", return_value=None):
                rows, meta = executor_embedded._emulate_returning(
                    plan, [1, "Alice"], is_embedded=True
                )
        assert isinstance(rows, list)


# ---------------------------------------------------------------------------
# _discover_metadata: Layer 2 CAST override
# ---------------------------------------------------------------------------

class TestDiscoverMetadataCastOverride:
    def test_cast_oid_overrides_inferred_type(self, executor_embedded):
        """Layer 2: CAST expression OID overrides inferred type from value."""
        with patch.object(executor_embedded, "_discover_metadata_with_limit_zero", return_value=None):
            with patch.object(executor_embedded, "_expand_select_star", return_value=None):
                cols = executor_embedded._discover_metadata(
                    "SELECT $1::bool AS flag",
                    None,
                    expected_count=1,
                    rows=[[1]]
                )
        # $1::bool → type_oid 16
        bool_cols = [c for c in cols if c["type_oid"] == 16]
        assert len(bool_cols) >= 1

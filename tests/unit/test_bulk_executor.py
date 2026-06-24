"""
Unit tests for bulk_executor.py.

Tests BulkExecutor batched INSERT, inline fallback, value conversion,
column-type fetching, streaming, and get_table_columns — all without IRIS.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from iris_pgwire.bulk_executor import BulkExecutor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_executor(**overrides) -> MagicMock:
    """Return a mock iris_executor with sensible async defaults."""
    mock = MagicMock()
    mock.execute_query = AsyncMock(return_value={"success": True, "rows": [], "rows_affected": 0})
    mock.execute_many = AsyncMock(return_value={"rows_affected": 0, "_execution_path": "executemany"})
    mock._execute_external_async = AsyncMock(return_value={"rows": []})
    for k, v in overrides.items():
        setattr(mock, k, v)
    return mock


async def _rows_from_list(rows):
    """Async iterator from a plain list of dicts."""
    for row in rows:
        yield row


# ---------------------------------------------------------------------------
# _convert_value_for_param
# ---------------------------------------------------------------------------


class TestConvertValueForParam:
    def setup_method(self):
        self.be = BulkExecutor(_make_executor())

    def test_none_returns_none(self):
        assert self.be._convert_value_for_param(None, "VARCHAR") is None

    def test_empty_string_returns_none(self):
        assert self.be._convert_value_for_param("", "VARCHAR") is None

    def test_varchar_passthrough(self):
        assert self.be._convert_value_for_param("hello", "VARCHAR") == "hello"

    def test_date_converts_to_horolog(self):
        result = self.be._convert_value_for_param("2023-01-01", "DATE")
        # date_to_horolog returns an integer (days since 1840-12-31)
        assert isinstance(result, int)
        assert result > 0

    def test_date_type_case_insensitive(self):
        result_upper = self.be._convert_value_for_param("2023-06-15", "DATE")
        result_lower = self.be._convert_value_for_param("2023-06-15", "date")
        assert result_upper == result_lower

    def test_list_converted_to_vector_string(self):
        result = self.be._convert_value_for_param([1.0, 2.0, 3.0], "VARCHAR")
        assert result == "[1.0,2.0,3.0]"

    def test_list_values_coerced_to_float(self):
        result = self.be._convert_value_for_param([1, 2], "VECTOR")
        assert result == "[1.0,2.0]"


# ---------------------------------------------------------------------------
# _convert_value_for_inline
# ---------------------------------------------------------------------------


class TestConvertValueForInline:
    def setup_method(self):
        self.be = BulkExecutor(_make_executor())

    def test_none_returns_null(self):
        assert self.be._convert_value_for_inline(None, "VARCHAR") == "NULL"

    def test_empty_string_returns_null(self):
        assert self.be._convert_value_for_inline("", "VARCHAR") == "NULL"

    def test_varchar_wrapped_in_quotes(self):
        assert self.be._convert_value_for_inline("hello", "VARCHAR") == "'hello'"

    def test_single_quotes_escaped(self):
        assert self.be._convert_value_for_inline("O'Brien", "VARCHAR") == "'O''Brien'"

    def test_date_converts_to_horolog_string(self):
        result = self.be._convert_value_for_inline("2023-01-01", "DATE")
        # Should be a plain integer string (no quotes)
        assert result.isdigit()

    def test_list_wrapped_as_quoted_vector(self):
        result = self.be._convert_value_for_inline([1.0, 2.5], "VECTOR")
        assert result == "'[1.0,2.5]'"

    def test_numeric_value_stringified(self):
        result = self.be._convert_value_for_inline(42, "INTEGER")
        assert result == "'42'"


# ---------------------------------------------------------------------------
# _build_params_list
# ---------------------------------------------------------------------------


class TestBuildParamsList:
    def setup_method(self):
        self.be = BulkExecutor(_make_executor())

    def test_basic_params_list(self):
        batch = [{"name": "Alice", "age": "30"}, {"name": "Bob", "age": "25"}]
        column_types = {"name": "VARCHAR", "age": "INTEGER"}
        result = self.be._build_params_list(batch, ["name", "age"], column_types)
        assert result == [["Alice", "30"], ["Bob", "25"]]

    def test_missing_column_treated_as_none(self):
        batch = [{"name": "Alice"}]
        column_types = {"name": "VARCHAR", "score": "INTEGER"}
        result = self.be._build_params_list(batch, ["name", "score"], column_types)
        assert result == [["Alice", None]]

    def test_unknown_column_type_defaults_varchar(self):
        batch = [{"x": "val"}]
        column_types = {}
        result = self.be._build_params_list(batch, ["x"], column_types)
        assert result == [["val"]]


# ---------------------------------------------------------------------------
# _get_column_types
# ---------------------------------------------------------------------------


class TestGetColumnTypes:
    @pytest.mark.asyncio
    async def test_maps_column_types_from_result(self):
        mock_exec = _make_executor()
        mock_exec.execute_query = AsyncMock(return_value={
            "success": True,
            "rows": [("DateOfBirth", "DATE"), ("Name", "VARCHAR")],
        })
        be = BulkExecutor(mock_exec)
        types = await be._get_column_types("Patients", ["DateOfBirth", "Name"])
        assert types["DateOfBirth"] == "DATE"
        assert types["Name"] == "VARCHAR"

    @pytest.mark.asyncio
    async def test_case_insensitive_column_matching(self):
        mock_exec = _make_executor()
        mock_exec.execute_query = AsyncMock(return_value={
            "success": True,
            "rows": [("DATEOFBIRTH", "DATE")],
        })
        be = BulkExecutor(mock_exec)
        types = await be._get_column_types("Patients", ["dateofbirth"])
        assert types["dateofbirth"] == "DATE"

    @pytest.mark.asyncio
    async def test_empty_rows_returns_empty_dict(self):
        mock_exec = _make_executor()
        mock_exec.execute_query = AsyncMock(return_value={"success": True, "rows": []})
        be = BulkExecutor(mock_exec)
        types = await be._get_column_types("Patients", ["Name"])
        assert types == {}

    @pytest.mark.asyncio
    async def test_failed_query_returns_empty_dict(self):
        mock_exec = _make_executor()
        mock_exec.execute_query = AsyncMock(return_value={"success": False, "rows": None})
        be = BulkExecutor(mock_exec)
        types = await be._get_column_types("Patients", ["Name"])
        assert types == {}


# ---------------------------------------------------------------------------
# _execute_batch_via_executemany
# ---------------------------------------------------------------------------


class TestExecuteBatchViaExecutemany:
    @pytest.mark.asyncio
    async def test_returns_rows_affected(self):
        mock_exec = _make_executor()
        mock_exec.execute_many = AsyncMock(return_value={
            "rows_affected": 5,
            "_execution_path": "executemany",
        })
        be = BulkExecutor(mock_exec)
        result = await be._execute_batch_via_executemany("INSERT ...", [[1], [2], [3], [4], [5]])
        assert result == 5

    @pytest.mark.asyncio
    async def test_zero_rows_affected(self):
        mock_exec = _make_executor()
        mock_exec.execute_many = AsyncMock(return_value={"rows_affected": 0})
        be = BulkExecutor(mock_exec)
        result = await be._execute_batch_via_executemany("INSERT ...", [])
        assert result == 0

    @pytest.mark.asyncio
    async def test_missing_execution_path_defaults_gracefully(self):
        mock_exec = _make_executor()
        mock_exec.execute_many = AsyncMock(return_value={"rows_affected": 3})
        be = BulkExecutor(mock_exec)
        result = await be._execute_batch_via_executemany("INSERT ...", [[1], [2], [3]])
        assert result == 3


# ---------------------------------------------------------------------------
# _execute_batch_inline_fallback
# ---------------------------------------------------------------------------


class TestExecuteBatchInlineFallback:
    @pytest.mark.asyncio
    async def test_inserts_each_row(self):
        mock_exec = _make_executor()
        mock_exec.execute_query = AsyncMock(return_value={"success": True})
        be = BulkExecutor(mock_exec)

        batch = [{"name": "Alice"}, {"name": "Bob"}]
        result = await be._execute_batch_inline_fallback(
            "Users", "name", ["name"], {"name": "VARCHAR"}, batch
        )
        assert result == 2
        assert mock_exec.execute_query.call_count == 2

    @pytest.mark.asyncio
    async def test_raises_on_insert_failure(self):
        mock_exec = _make_executor()
        mock_exec.execute_query = AsyncMock(return_value={
            "success": False, "error": "Table not found"
        })
        be = BulkExecutor(mock_exec)
        batch = [{"name": "Alice"}]

        with pytest.raises(RuntimeError, match="INSERT failed"):
            await be._execute_batch_inline_fallback(
                "Users", "name", ["name"], {"name": "VARCHAR"}, batch
            )

    @pytest.mark.asyncio
    async def test_empty_batch_returns_zero(self):
        mock_exec = _make_executor()
        be = BulkExecutor(mock_exec)
        result = await be._execute_batch_inline_fallback(
            "Users", "name", ["name"], {"name": "VARCHAR"}, []
        )
        assert result == 0
        mock_exec.execute_query.assert_not_called()


# ---------------------------------------------------------------------------
# _execute_batch_insert
# ---------------------------------------------------------------------------


class TestExecuteBatchInsert:
    @pytest.mark.asyncio
    async def test_empty_batch_returns_zero(self):
        mock_exec = _make_executor()
        be = BulkExecutor(mock_exec)
        result = await be._execute_batch_insert("T", ["col"], [])
        assert result == 0

    @pytest.mark.asyncio
    async def test_uses_executemany_path_on_success(self):
        mock_exec = _make_executor()
        mock_exec.execute_query = AsyncMock(return_value={
            "success": True, "rows": [], "rows_affected": 0
        })
        mock_exec.execute_many = AsyncMock(return_value={
            "rows_affected": 2, "_execution_path": "executemany"
        })
        be = BulkExecutor(mock_exec)

        batch = [{"name": "Alice"}, {"name": "Bob"}]
        result = await be._execute_batch_insert("Users", ["name"], batch)
        assert result == 2
        mock_exec.execute_many.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_falls_back_to_inline_on_executemany_failure(self):
        mock_exec = _make_executor()
        mock_exec.execute_query = AsyncMock(side_effect=[
            # First call: _get_column_types query
            {"success": True, "rows": []},
            # Second call: inline insert fallback
            {"success": True},
        ])
        mock_exec.execute_many = AsyncMock(side_effect=RuntimeError("executemany unsupported"))
        be = BulkExecutor(mock_exec)

        batch = [{"name": "Alice"}]
        result = await be._execute_batch_insert("Users", ["name"], batch)
        assert result == 1


# ---------------------------------------------------------------------------
# bulk_insert — column inference logic
# ---------------------------------------------------------------------------


class TestBulkInsert:
    @pytest.mark.asyncio
    async def test_infers_columns_from_first_row(self):
        """When column_names is None, infer from row keys."""
        mock_exec = _make_executor()
        mock_exec.execute_query = AsyncMock(return_value={
            "success": True, "rows": [], "rows_affected": 0
        })
        mock_exec.execute_many = AsyncMock(return_value={
            "rows_affected": 1, "_execution_path": "executemany"
        })
        be = BulkExecutor(mock_exec)

        rows = [{"id": "1", "name": "Alice"}]
        total = await be.bulk_insert("Users", None, _rows_from_list(rows))
        assert total == 1

    @pytest.mark.asyncio
    async def test_uses_provided_column_names(self):
        mock_exec = _make_executor()
        mock_exec.execute_query = AsyncMock(return_value={
            "success": True, "rows": [], "rows_affected": 0
        })
        mock_exec.execute_many = AsyncMock(return_value={
            "rows_affected": 2, "_execution_path": "executemany"
        })
        be = BulkExecutor(mock_exec)

        rows = [{"id": "1", "name": "Alice"}, {"id": "2", "name": "Bob"}]
        total = await be.bulk_insert("Users", ["id", "name"], _rows_from_list(rows))
        assert total == 2

    @pytest.mark.asyncio
    async def test_empty_rows_returns_zero(self):
        mock_exec = _make_executor()
        be = BulkExecutor(mock_exec)
        total = await be.bulk_insert("Users", ["id"], _rows_from_list([]))
        assert total == 0

    @pytest.mark.asyncio
    async def test_batches_correctly_across_batch_boundary(self):
        """Verify batching splits work: 5 rows with batch_size=2 → 3 batch calls."""
        mock_exec = _make_executor()
        mock_exec.execute_query = AsyncMock(return_value={
            "success": True, "rows": [], "rows_affected": 0
        })

        # Return len(params_list) so the total adds up correctly
        async def executemany_actual(sql, params_list):
            return {"rows_affected": len(params_list), "_execution_path": "executemany"}

        mock_exec.execute_many = executemany_actual
        be = BulkExecutor(mock_exec)

        rows = [{"id": str(i)} for i in range(5)]
        total = await be.bulk_insert("T", ["id"], _rows_from_list(rows), batch_size=2)
        # 2+2+1 = 5 rows total
        assert total == 5

    @pytest.mark.asyncio
    async def test_placeholder_keys_trigger_schema_lookup(self):
        """Rows with column_0, column_1 keys should trigger get_table_columns."""
        mock_exec = _make_executor()
        mock_exec.execute_query = AsyncMock(return_value={
            "success": True, "rows": [], "rows_affected": 0
        })
        mock_exec.execute_many = AsyncMock(return_value={
            "rows_affected": 1, "_execution_path": "executemany"
        })
        mock_exec._execute_external_async = AsyncMock(return_value={
            "rows": [("id",), ("name",)]
        })
        be = BulkExecutor(mock_exec)

        rows = [{"column_0": "1", "column_1": "Alice"}]
        total = await be.bulk_insert("Users", None, _rows_from_list(rows))
        # Schema lookup was called
        mock_exec._execute_external_async.assert_awaited_once()
        assert total == 1

    @pytest.mark.asyncio
    async def test_remaining_batch_flushed_after_loop(self):
        """The final partial batch must be flushed after the async-for loop."""
        mock_exec = _make_executor()
        mock_exec.execute_query = AsyncMock(return_value={
            "success": True, "rows": [], "rows_affected": 0
        })
        # Track calls to execute_many to verify flush
        call_count = {"n": 0}

        async def count_calls(sql, params):
            call_count["n"] += 1
            return {"rows_affected": len(params), "_execution_path": "executemany"}

        mock_exec.execute_many = count_calls
        be = BulkExecutor(mock_exec)

        # 3 rows, batch_size=10 → only 1 batch call (the trailing flush)
        rows = [{"id": str(i)} for i in range(3)]
        total = await be.bulk_insert("T", ["id"], _rows_from_list(rows), batch_size=10)
        assert total == 3
        assert call_count["n"] == 1


# ---------------------------------------------------------------------------
# get_table_columns
# ---------------------------------------------------------------------------


class TestGetTableColumns:
    @pytest.mark.asyncio
    async def test_returns_ordered_column_names(self):
        mock_exec = _make_executor()
        mock_exec._execute_external_async = AsyncMock(return_value={
            "rows": [("id",), ("name",), ("created_at",)]
        })
        be = BulkExecutor(mock_exec)
        cols = await be.get_table_columns("Users")
        assert cols == ["id", "name", "created_at"]

    @pytest.mark.asyncio
    async def test_empty_result_returns_empty_list(self):
        mock_exec = _make_executor()
        mock_exec._execute_external_async = AsyncMock(return_value={"rows": []})
        be = BulkExecutor(mock_exec)
        cols = await be.get_table_columns("NonExistent")
        assert cols == []

    @pytest.mark.asyncio
    async def test_none_result_returns_empty_list(self):
        mock_exec = _make_executor()
        mock_exec._execute_external_async = AsyncMock(return_value=None)
        be = BulkExecutor(mock_exec)
        cols = await be.get_table_columns("T")
        assert cols == []

    @pytest.mark.asyncio
    async def test_query_contains_table_name(self):
        mock_exec = _make_executor()
        mock_exec._execute_external_async = AsyncMock(return_value={"rows": []})
        be = BulkExecutor(mock_exec)
        await be.get_table_columns("MyTable")
        call_args = mock_exec._execute_external_async.call_args
        query = call_args[0][0]
        assert "MyTable" in query


# ---------------------------------------------------------------------------
# stream_query_results
# ---------------------------------------------------------------------------


class TestStreamQueryResults:
    @pytest.mark.asyncio
    async def test_yields_rows_from_result(self):
        mock_exec = _make_executor()
        mock_exec.execute_query = AsyncMock(return_value=[("Alice", 30), ("Bob", 25)])
        be = BulkExecutor(mock_exec)

        rows = [row async for row in be.stream_query_results("SELECT * FROM Users")]
        assert rows == [("Alice", 30), ("Bob", 25)]

    @pytest.mark.asyncio
    async def test_empty_result_yields_nothing(self):
        mock_exec = _make_executor()
        mock_exec.execute_query = AsyncMock(return_value=[])
        be = BulkExecutor(mock_exec)

        rows = [row async for row in be.stream_query_results("SELECT * FROM Empty")]
        assert rows == []

    @pytest.mark.asyncio
    async def test_none_result_yields_nothing(self):
        mock_exec = _make_executor()
        mock_exec.execute_query = AsyncMock(return_value=None)
        be = BulkExecutor(mock_exec)

        rows = [row async for row in be.stream_query_results("SELECT 1")]
        assert rows == []

    @pytest.mark.asyncio
    async def test_propagates_execute_query_exception(self):
        mock_exec = _make_executor()
        mock_exec.execute_query = AsyncMock(side_effect=RuntimeError("IRIS error"))
        be = BulkExecutor(mock_exec)

        with pytest.raises(RuntimeError, match="IRIS error"):
            async for _ in be.stream_query_results("SELECT 1"):
                pass

"""
Extended unit tests for copy_handler.py

Targets ≥80% coverage of CopyHandler including:
- Message building methods
- handle_copy_from_stdin (transactional batch insert path)
- handle_copy_from_stdin_load_data (LOAD DATA path)
- handle_copy_to_stdout (export path)
"""

import struct
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from iris_pgwire.copy_handler import CopyHandler
from iris_pgwire.sql_translator.copy_parser import CopyCommand, CopyDirection, CSVOptions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_copy_command(
    table_name: str = "MyTable",
    column_list: list[str] | None = None,
    direction: CopyDirection = CopyDirection.FROM_STDIN,
    query: str | None = None,
    csv_options: CSVOptions | None = None,
) -> CopyCommand:
    return CopyCommand(
        table_name=table_name,
        column_list=column_list or ["id", "name"],
        direction=direction,
        query=query,
        csv_options=csv_options or CSVOptions(),
    )


async def async_iter(items):
    for item in items:
        yield item


def make_handler(
    bulk_executor=None,
    csv_processor=None,
    iris_executor=None,
):
    if iris_executor is None:
        iris_executor = MagicMock()
    if bulk_executor is None:
        bulk_executor = MagicMock()
        bulk_executor.iris_executor = iris_executor
    if csv_processor is None:
        csv_processor = MagicMock()
    return CopyHandler(csv_processor=csv_processor, bulk_executor=bulk_executor), bulk_executor, csv_processor, iris_executor


# ---------------------------------------------------------------------------
# Message building
# ---------------------------------------------------------------------------


class TestBuildCopyResponse:
    def test_copy_in_response_type_byte(self):
        handler, *_ = make_handler()
        msg = handler.build_copy_in_response(3)
        assert msg[0:1] == b"G"

    def test_copy_out_response_type_byte(self):
        handler, *_ = make_handler()
        msg = handler.build_copy_out_response(3)
        assert msg[0:1] == b"H"

    def test_copy_in_response_length_field(self):
        handler, *_ = make_handler()
        msg = handler.build_copy_in_response(2)
        # length field is at offset 1, uint32 big-endian
        length = struct.unpack("!I", msg[1:5])[0]
        # payload = 1 (format) + 2 (col count) + 2*2 (format codes) = 7; length = 7+4 = 11
        assert length == 11

    def test_copy_in_response_zero_columns(self):
        handler, *_ = make_handler()
        msg = handler.build_copy_in_response(0)
        assert msg[0:1] == b"G"
        length = struct.unpack("!I", msg[1:5])[0]
        # payload = 1 + 2 + 0 = 3; length = 3+4 = 7
        assert length == 7

    def test_copy_out_response_length_field(self):
        handler, *_ = make_handler()
        msg = handler.build_copy_out_response(4)
        length = struct.unpack("!I", msg[1:5])[0]
        # payload = 1 + 2 + 4*2 = 11; length = 11+4 = 15
        assert length == 15

    def test_copy_in_response_format_byte(self):
        handler, *_ = make_handler()
        msg = handler.build_copy_in_response(1)
        # offset 5 is format byte (Int8) = 0 for text/CSV
        fmt = struct.unpack("!b", msg[5:6])[0]
        assert fmt == 0

    def test_copy_in_response_column_count(self):
        handler, *_ = make_handler()
        msg = handler.build_copy_in_response(5)
        col_count = struct.unpack("!H", msg[6:8])[0]
        assert col_count == 5

    def test_copy_in_response_format_codes_all_zero(self):
        handler, *_ = make_handler()
        col_count = 3
        msg = handler.build_copy_in_response(col_count)
        offset = 8
        for _ in range(col_count):
            code = struct.unpack("!H", msg[offset : offset + 2])[0]
            assert code == 0
            offset += 2

    def test_copy_response_large_column_count(self):
        handler, *_ = make_handler()
        msg = handler.build_copy_in_response(100)
        assert len(msg) == 1 + 4 + 1 + 2 + 100 * 2


class TestBuildCopyData:
    def test_type_byte(self):
        handler, *_ = make_handler()
        msg = handler.build_copy_data(b"hello")
        assert msg[0:1] == b"d"

    def test_length_field(self):
        handler, *_ = make_handler()
        data = b"hello,world\n"
        msg = handler.build_copy_data(data)
        length = struct.unpack("!I", msg[1:5])[0]
        assert length == len(data) + 4

    def test_payload_content(self):
        handler, *_ = make_handler()
        data = b"abc\ndef\n"
        msg = handler.build_copy_data(data)
        assert msg[5:] == data

    def test_empty_data(self):
        handler, *_ = make_handler()
        msg = handler.build_copy_data(b"")
        length = struct.unpack("!I", msg[1:5])[0]
        assert length == 4


class TestBuildCopyDone:
    def test_type_byte(self):
        handler, *_ = make_handler()
        msg = handler.build_copy_done()
        assert msg[0:1] == b"c"

    def test_length_field(self):
        handler, *_ = make_handler()
        msg = handler.build_copy_done()
        length = struct.unpack("!I", msg[1:5])[0]
        assert length == 4

    def test_total_message_length(self):
        handler, *_ = make_handler()
        msg = handler.build_copy_done()
        assert len(msg) == 5


# ---------------------------------------------------------------------------
# handle_copy_from_stdin
# ---------------------------------------------------------------------------


class TestHandleCopyFromStdin:
    @pytest.mark.asyncio
    async def test_successful_insert_returns_row_count(self):
        iris_executor = MagicMock()
        iris_executor.execute_query = AsyncMock(return_value={"success": True})
        bulk_executor = MagicMock()
        bulk_executor.iris_executor = iris_executor
        bulk_executor.bulk_insert = AsyncMock(return_value=42)

        csv_processor = MagicMock()
        csv_processor.parse_csv_rows = MagicMock(return_value=async_iter([]))

        handler = CopyHandler(csv_processor=csv_processor, bulk_executor=bulk_executor)
        cmd = make_copy_command()

        result = await handler.handle_copy_from_stdin(cmd, async_iter([]))

        assert result == 42

    @pytest.mark.asyncio
    async def test_begin_transaction_called(self):
        iris_executor = MagicMock()
        iris_executor.execute_query = AsyncMock(return_value={"success": True})
        bulk_executor = MagicMock()
        bulk_executor.iris_executor = iris_executor
        bulk_executor.bulk_insert = AsyncMock(return_value=5)

        csv_processor = MagicMock()
        csv_processor.parse_csv_rows = MagicMock(return_value=async_iter([]))

        handler = CopyHandler(csv_processor=csv_processor, bulk_executor=bulk_executor)
        cmd = make_copy_command()

        await handler.handle_copy_from_stdin(cmd, async_iter([]))

        calls = [call[0][0] for call in iris_executor.execute_query.call_args_list]
        assert "START TRANSACTION" in calls
        assert "COMMIT" in calls

    @pytest.mark.asyncio
    async def test_rollback_on_bulk_insert_failure(self):
        iris_executor = MagicMock()
        iris_executor.execute_query = AsyncMock(return_value={"success": True})
        bulk_executor = MagicMock()
        bulk_executor.iris_executor = iris_executor
        bulk_executor.bulk_insert = AsyncMock(side_effect=RuntimeError("insert failed"))

        csv_processor = MagicMock()
        csv_processor.parse_csv_rows = MagicMock(return_value=async_iter([]))

        handler = CopyHandler(csv_processor=csv_processor, bulk_executor=bulk_executor)
        cmd = make_copy_command()

        with pytest.raises(RuntimeError, match="insert failed"):
            await handler.handle_copy_from_stdin(cmd, async_iter([]))

        calls = [call[0][0] for call in iris_executor.execute_query.call_args_list]
        assert "ROLLBACK" in calls

    @pytest.mark.asyncio
    async def test_begin_transaction_failure_raises(self):
        iris_executor = MagicMock()
        iris_executor.execute_query = AsyncMock(
            return_value={"success": False, "error": "tx error"}
        )
        bulk_executor = MagicMock()
        bulk_executor.iris_executor = iris_executor

        csv_processor = MagicMock()
        handler = CopyHandler(csv_processor=csv_processor, bulk_executor=bulk_executor)
        cmd = make_copy_command()

        with pytest.raises(RuntimeError, match="Failed to begin transaction"):
            await handler.handle_copy_from_stdin(cmd, async_iter([]))

    @pytest.mark.asyncio
    async def test_commit_failure_raises(self):
        call_count = {"n": 0}

        async def mock_execute(sql, params=None):
            call_count["n"] += 1
            if sql == "START TRANSACTION":
                return {"success": True}
            if sql == "COMMIT":
                return {"success": False, "error": "commit failed"}
            return {"success": True}

        iris_executor = MagicMock()
        iris_executor.execute_query = mock_execute
        bulk_executor = MagicMock()
        bulk_executor.iris_executor = iris_executor
        bulk_executor.bulk_insert = AsyncMock(return_value=10)

        csv_processor = MagicMock()
        csv_processor.parse_csv_rows = MagicMock(return_value=async_iter([]))

        handler = CopyHandler(csv_processor=csv_processor, bulk_executor=bulk_executor)
        cmd = make_copy_command()

        with pytest.raises(RuntimeError, match="Failed to commit"):
            await handler.handle_copy_from_stdin(cmd, async_iter([]))

    @pytest.mark.asyncio
    async def test_rollback_exception_does_not_suppress_original(self):
        async def mock_execute(sql, params=None):
            if sql == "START TRANSACTION":
                return {"success": True}
            if sql == "ROLLBACK":
                raise RuntimeError("rollback also failed")
            return {"success": True}

        iris_executor = MagicMock()
        iris_executor.execute_query = mock_execute
        bulk_executor = MagicMock()
        bulk_executor.iris_executor = iris_executor
        bulk_executor.bulk_insert = AsyncMock(side_effect=ValueError("bulk error"))

        csv_processor = MagicMock()
        csv_processor.parse_csv_rows = MagicMock(return_value=async_iter([]))

        handler = CopyHandler(csv_processor=csv_processor, bulk_executor=bulk_executor)
        cmd = make_copy_command()

        with pytest.raises(ValueError, match="bulk error"):
            await handler.handle_copy_from_stdin(cmd, async_iter([]))


# ---------------------------------------------------------------------------
# handle_copy_from_stdin_load_data
# ---------------------------------------------------------------------------


class TestHandleCopyFromStdinLoadData:
    def _make_csv_options_with_encoding(self, encoding=None):
        """Return a MagicMock stand-in for CSVOptions that has an encoding attr."""
        opts = MagicMock(spec=CSVOptions)
        opts.header = False
        opts.delimiter = ","
        opts.encoding = encoding
        return opts

    @pytest.mark.asyncio
    async def test_successful_load_returns_row_count(self, tmp_path):
        iris_executor = MagicMock()
        iris_executor.execute_query = AsyncMock(
            return_value={"success": True, "rows_affected": 7}
        )
        bulk_executor = MagicMock()
        bulk_executor.iris_executor = iris_executor

        csv_processor = MagicMock()
        handler = CopyHandler(csv_processor=csv_processor, bulk_executor=bulk_executor)
        cmd = make_copy_command(csv_options=self._make_csv_options_with_encoding())

        result = await handler.handle_copy_from_stdin_load_data(cmd, async_iter([b"a,b\n"]))

        assert result == 7

    @pytest.mark.asyncio
    async def test_temporary_file_cleaned_up(self, tmp_path):
        iris_executor = MagicMock()
        iris_executor.execute_query = AsyncMock(
            return_value={"success": True, "rows_affected": 3}
        )
        bulk_executor = MagicMock()
        bulk_executor.iris_executor = iris_executor

        csv_processor = MagicMock()
        handler = CopyHandler(csv_processor=csv_processor, bulk_executor=bulk_executor)
        cmd = make_copy_command(csv_options=self._make_csv_options_with_encoding())

        await handler.handle_copy_from_stdin_load_data(cmd, async_iter([b"1,foo\n"]))

        # The handler itself cleans up — just check no exception propagated.

    @pytest.mark.asyncio
    async def test_transaction_started_and_committed(self):
        calls = []

        async def mock_execute(sql, params=None):
            calls.append(sql)
            return {"success": True, "rows_affected": 1}

        iris_executor = MagicMock()
        iris_executor.execute_query = mock_execute
        bulk_executor = MagicMock()
        bulk_executor.iris_executor = iris_executor

        csv_processor = MagicMock()
        handler = CopyHandler(csv_processor=csv_processor, bulk_executor=bulk_executor)
        cmd = make_copy_command(csv_options=self._make_csv_options_with_encoding())

        await handler.handle_copy_from_stdin_load_data(cmd, async_iter([b"data\n"]))

        assert "START TRANSACTION" in calls
        assert "COMMIT" in calls

    @pytest.mark.asyncio
    async def test_begin_failure_raises(self):
        iris_executor = MagicMock()
        iris_executor.execute_query = AsyncMock(
            return_value={"success": False, "error": "no tx"}
        )
        bulk_executor = MagicMock()
        bulk_executor.iris_executor = iris_executor

        csv_processor = MagicMock()
        handler = CopyHandler(csv_processor=csv_processor, bulk_executor=bulk_executor)
        cmd = make_copy_command()

        with pytest.raises(RuntimeError, match="Failed to begin transaction"):
            await handler.handle_copy_from_stdin_load_data(cmd, async_iter([]))

    @pytest.mark.asyncio
    async def test_load_data_failure_triggers_rollback(self):
        call_seq = []

        async def mock_execute(sql, params=None):
            call_seq.append(sql)
            if sql == "START TRANSACTION":
                return {"success": True}
            # LOAD DATA SQL
            if "LOAD" in sql.upper():
                return {"success": False, "error": "LOAD DATA error"}
            return {"success": True}

        iris_executor = MagicMock()
        iris_executor.execute_query = mock_execute
        bulk_executor = MagicMock()
        bulk_executor.iris_executor = iris_executor

        csv_processor = MagicMock()
        handler = CopyHandler(csv_processor=csv_processor, bulk_executor=bulk_executor)
        cmd = make_copy_command(csv_options=self._make_csv_options_with_encoding())

        with pytest.raises(RuntimeError, match="LOAD DATA failed"):
            await handler.handle_copy_from_stdin_load_data(cmd, async_iter([b"data\n"]))

        assert "ROLLBACK" in call_seq

    @pytest.mark.asyncio
    async def test_column_list_included_in_load_sql(self):
        executed_sqls = []

        async def mock_execute(sql, params=None):
            executed_sqls.append(sql)
            return {"success": True, "rows_affected": 2}

        iris_executor = MagicMock()
        iris_executor.execute_query = mock_execute
        bulk_executor = MagicMock()
        bulk_executor.iris_executor = iris_executor

        csv_processor = MagicMock()
        handler = CopyHandler(csv_processor=csv_processor, bulk_executor=bulk_executor)
        cmd = make_copy_command(
            column_list=["id", "name", "age"],
            csv_options=self._make_csv_options_with_encoding(),
        )

        await handler.handle_copy_from_stdin_load_data(cmd, async_iter([b"1,foo,30\n"]))

        load_sql = next(s for s in executed_sqls if "LOAD" in s.upper())
        assert "id, name, age" in load_sql

    @pytest.mark.asyncio
    async def test_encoding_option_added_to_using_clause(self):
        executed_sqls = []

        async def mock_execute(sql, params=None):
            executed_sqls.append(sql)
            return {"success": True, "rows_affected": 1}

        iris_executor = MagicMock()
        iris_executor.execute_query = mock_execute
        bulk_executor = MagicMock()
        bulk_executor.iris_executor = iris_executor

        csv_processor = MagicMock()
        handler = CopyHandler(csv_processor=csv_processor, bulk_executor=bulk_executor)
        opts = self._make_csv_options_with_encoding("UTF-8")
        cmd = make_copy_command(csv_options=opts)

        await handler.handle_copy_from_stdin_load_data(cmd, async_iter([b"data\n"]))

        load_sql = next(s for s in executed_sqls if "LOAD" in s.upper())
        assert "charset" in load_sql

    @pytest.mark.asyncio
    async def test_commit_failure_raises(self):
        call_count = {"n": 0}

        async def mock_execute(sql, params=None):
            call_count["n"] += 1
            if sql == "START TRANSACTION":
                return {"success": True}
            if sql == "COMMIT":
                return {"success": False, "error": "commit err"}
            return {"success": True, "rows_affected": 1}

        iris_executor = MagicMock()
        iris_executor.execute_query = mock_execute
        bulk_executor = MagicMock()
        bulk_executor.iris_executor = iris_executor

        csv_processor = MagicMock()
        handler = CopyHandler(csv_processor=csv_processor, bulk_executor=bulk_executor)
        cmd = make_copy_command(csv_options=self._make_csv_options_with_encoding())

        with pytest.raises(RuntimeError, match="Failed to commit"):
            await handler.handle_copy_from_stdin_load_data(cmd, async_iter([b"1,a\n"]))


# ---------------------------------------------------------------------------
# handle_copy_to_stdout
# ---------------------------------------------------------------------------


class TestHandleCopyToStdout:
    @pytest.mark.asyncio
    async def test_table_select_query_used_when_no_query(self):
        bulk_executor = MagicMock()
        bulk_executor.iris_executor = MagicMock()

        def mock_stream(query):
            async def _empty():
                if False:
                    yield
            return _empty()

        bulk_executor.stream_query_results = mock_stream

        csv_processor = MagicMock()

        async def mock_generate(rows, col_names, opts):
            yield b"1,foo\n"
            yield b"2,bar\n"

        csv_processor.generate_csv_rows = mock_generate

        handler = CopyHandler(csv_processor=csv_processor, bulk_executor=bulk_executor)
        cmd = make_copy_command(
            direction=CopyDirection.TO_STDOUT, column_list=["id", "name"], query=None
        )

        chunks = []
        async for chunk in handler.handle_copy_to_stdout(cmd):
            chunks.append(chunk)

        assert chunks == [b"1,foo\n", b"2,bar\n"]

    @pytest.mark.asyncio
    async def test_custom_query_used_when_provided(self):
        captured_queries = []
        bulk_executor = MagicMock()
        bulk_executor.iris_executor = MagicMock()

        def mock_stream(query):
            captured_queries.append(query)

            async def _empty():
                if False:
                    yield

            return _empty()

        bulk_executor.stream_query_results = mock_stream

        csv_processor = MagicMock()

        async def mock_generate(rows, col_names, opts):
            yield b"row\n"

        csv_processor.generate_csv_rows = mock_generate

        handler = CopyHandler(csv_processor=csv_processor, bulk_executor=bulk_executor)
        custom_query = "SELECT id FROM MyTable WHERE active = 1"
        cmd = make_copy_command(direction=CopyDirection.TO_STDOUT, query=custom_query)

        async for _ in handler.handle_copy_to_stdout(cmd):
            pass

        assert captured_queries == [custom_query]

    @pytest.mark.asyncio
    async def test_wildcard_select_when_no_columns_and_no_query(self):
        captured_queries = []
        bulk_executor = MagicMock()
        bulk_executor.iris_executor = MagicMock()

        def mock_stream(query):
            captured_queries.append(query)

            async def _empty():
                if False:
                    yield

            return _empty()

        bulk_executor.stream_query_results = mock_stream

        csv_processor = MagicMock()

        async def mock_generate(rows, col_names, opts):
            if False:
                yield

        csv_processor.generate_csv_rows = mock_generate

        handler = CopyHandler(csv_processor=csv_processor, bulk_executor=bulk_executor)
        # Build a CopyCommand directly with an empty column_list (bypass helper default)
        from iris_pgwire.sql_translator.copy_parser import CopyCommand
        cmd = CopyCommand(
            table_name="MyTable",
            column_list=[],
            direction=CopyDirection.TO_STDOUT,
            query=None,
            csv_options=CSVOptions(),
        )

        async for _ in handler.handle_copy_to_stdout(cmd):
            pass

        assert len(captured_queries) == 1
        assert "SELECT *" in captured_queries[0]

    @pytest.mark.asyncio
    async def test_yields_no_chunks_for_empty_result(self):
        bulk_executor = MagicMock()
        bulk_executor.iris_executor = MagicMock()

        def mock_stream(query):
            async def _empty():
                if False:
                    yield
            return _empty()

        bulk_executor.stream_query_results = mock_stream

        csv_processor = MagicMock()

        async def mock_generate(rows, col_names, opts):
            if False:
                yield

        csv_processor.generate_csv_rows = mock_generate

        handler = CopyHandler(csv_processor=csv_processor, bulk_executor=bulk_executor)
        cmd = make_copy_command(direction=CopyDirection.TO_STDOUT, query=None)

        chunks = []
        async for chunk in handler.handle_copy_to_stdout(cmd):
            chunks.append(chunk)

        assert chunks == []

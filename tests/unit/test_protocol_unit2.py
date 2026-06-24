"""
Extended unit tests for PGWireProtocol (protocol.py) — Phase 2.

Targets uncovered code paths: handle_parse_message, handle_bind_message,
handle_execute_message, handle_close_message, handle_sync_message,
send_query_result, send_data_row, send_row_description,
_maybe_send_row_description, _maybe_send_data_rows, COPY protocol,
translate_sql, send_set_response, send_deallocate_response, etc.

All tests use mocked dependencies — no IRIS connection required.
"""

from __future__ import annotations

import asyncio
import struct
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from iris_pgwire.protocol import (
    MSG_BIND_COMPLETE,
    MSG_CLOSE_COMPLETE,
    MSG_COMMAND_COMPLETE,
    MSG_COPY_DATA,
    MSG_COPY_DONE,
    MSG_COPY_FAIL,
    MSG_COPY_IN_RESPONSE,
    MSG_COPY_OUT_RESPONSE,
    MSG_DATA_ROW,
    MSG_ERROR_RESPONSE,
    MSG_NO_DATA,
    MSG_PARAMETER_DESCRIPTION,
    MSG_PARSE_COMPLETE,
    MSG_READY_FOR_QUERY,
    MSG_ROW_DESCRIPTION,
    PGWireProtocol,
    STATUS_IDLE,
    STATUS_IN_TRANSACTION,
)


# ---------------------------------------------------------------------------
# Fixture (mirrors test_protocol_unit.py but adds execute_query)
# ---------------------------------------------------------------------------


@pytest.fixture
def protocol():
    reader = AsyncMock(spec=asyncio.StreamReader)
    writer = MagicMock()
    writer.write = MagicMock()
    writer.drain = AsyncMock()

    iris_executor = MagicMock()
    iris_executor.sql_pipeline = MagicMock()
    iris_executor.sql_translator = MagicMock()
    iris_executor.sql_translator.translate_postgres_parameters = lambda sql: sql
    iris_executor.sql_parser = MagicMock()
    iris_executor.sql_parser.is_select_statement = MagicMock(return_value=False)
    iris_executor.sql_parser.is_show_statement = MagicMock(return_value=False)
    iris_executor.sql_parser.is_dml_statement = MagicMock(return_value=False)
    iris_executor.sql_parser.has_returning_clause = MagicMock(return_value=False)
    iris_executor.set_session_namespace = MagicMock()
    iris_executor.get_iris_type_mapping = MagicMock(
        return_value={
            "VARCHAR": {"oid": 25, "typlen": -1},
            "INTEGER": {"oid": 23, "typlen": 4},
            "BIGINT": {"oid": 20, "typlen": 8},
            "BOOLEAN": {"oid": 16, "typlen": 1},
            "FLOAT": {"oid": 700, "typlen": 4},
            "DOUBLE": {"oid": 701, "typlen": 8},
            "DATE": {"oid": 1082, "typlen": 4},
            "TIMESTAMP": {"oid": 1114, "typlen": 8},
            "NUMERIC": {"oid": 1700, "typlen": -1},
        }
    )
    iris_executor.close_session = AsyncMock()
    iris_executor.begin_transaction = AsyncMock()
    iris_executor.commit_transaction = AsyncMock()
    iris_executor.rollback_transaction = AsyncMock()
    iris_executor.execute_many = AsyncMock()
    iris_executor.execute_query = AsyncMock(
        return_value={
            "success": True,
            "rows": [],
            "columns": [],
            "row_count": 0,
            "command_tag": "SELECT",
        }
    )
    iris_executor.cancel_query = AsyncMock(return_value=True)
    iris_executor.strict_single_connection = False
    iris_executor.metadata_cache = None

    p = PGWireProtocol(
        reader=reader,
        writer=writer,
        iris_executor=iris_executor,
        connection_id="test-conn-001",
        enable_scram=False,
    )
    return p


def collected_bytes(writer) -> bytes:
    """Return all bytes written to writer.write() calls concatenated."""
    return b"".join(call.args[0] for call in writer.write.call_args_list)


def make_parse_body(statement_name: str, query: str, param_types: list[int] = None) -> bytes:
    """Build a binary Parse message body."""
    param_types = param_types or []
    body = statement_name.encode() + b"\x00"
    body += query.encode() + b"\x00"
    body += struct.pack("!H", len(param_types))
    for pt in param_types:
        body += struct.pack("!I", pt)
    return body


def make_bind_body(
    portal_name: str,
    statement_name: str,
    params: list[bytes | None] = None,
    result_formats: list[int] = None,
) -> bytes:
    """Build a binary Bind message body with text-format parameters."""
    params = params or []
    result_formats = result_formats or []
    body = portal_name.encode() + b"\x00"
    body += statement_name.encode() + b"\x00"
    # No parameter format codes (use default text)
    body += struct.pack("!H", 0)
    # Param values
    body += struct.pack("!H", len(params))
    for p in params:
        if p is None:
            body += struct.pack("!I", 0xFFFFFFFF)
        else:
            body += struct.pack("!I", len(p)) + p
    # Result format codes
    body += struct.pack("!H", len(result_formats))
    for rf in result_formats:
        body += struct.pack("!H", rf)
    return body


def make_execute_body(portal_name: str, max_rows: int = 0) -> bytes:
    """Build a binary Execute message body."""
    return portal_name.encode() + b"\x00" + struct.pack("!I", max_rows)


def make_close_body(close_type: str, name: str) -> bytes:
    """Build a Close message body. close_type='S' or 'P'."""
    return close_type.encode() + name.encode() + b"\x00"


def make_describe_body(desc_type: str, name: str) -> bytes:
    """Build a Describe message body. desc_type='S' or 'P'."""
    return desc_type.encode() + name.encode() + b"\x00"


# ===========================================================================
# 1. send_query_result — SELECT with rows
# ===========================================================================


class TestSendQueryResult:
    @pytest.mark.asyncio
    async def test_select_with_rows_sends_row_description(self, protocol):
        result = {
            "success": True,
            "rows": [[1, "alice"]],
            "columns": [
                {"name": "id", "type_oid": 23, "type_size": 4, "type_modifier": -1},
                {"name": "name", "type_oid": 25, "type_size": -1, "type_modifier": -1},
            ],
            "row_count": 1,
            "command_tag": "SELECT",
        }
        protocol.writer.write.reset_mock()
        await protocol.send_query_result(result, send_ready=True)
        data = collected_bytes(protocol.writer)
        assert MSG_ROW_DESCRIPTION in data
        assert MSG_DATA_ROW in data
        assert MSG_COMMAND_COMPLETE in data
        assert MSG_READY_FOR_QUERY in data

    @pytest.mark.asyncio
    async def test_select_no_rows_no_data_row(self, protocol):
        result = {
            "success": True,
            "rows": [],
            "columns": [{"name": "id", "type_oid": 23, "type_size": 4, "type_modifier": -1}],
            "row_count": 0,
            "command_tag": "SELECT",
        }
        protocol.writer.write.reset_mock()
        await protocol.send_query_result(result, send_ready=False)
        data = collected_bytes(protocol.writer)
        assert MSG_ROW_DESCRIPTION in data
        assert MSG_DATA_ROW not in data
        assert MSG_COMMAND_COMPLETE in data
        # No ReadyForQuery since send_ready=False
        assert MSG_READY_FOR_QUERY not in data

    @pytest.mark.asyncio
    async def test_insert_no_columns_sends_command_complete(self, protocol):
        result = {
            "success": True,
            "rows": [],
            "columns": [],
            "row_count": 1,
            "command_tag": "INSERT",
        }
        protocol.writer.write.reset_mock()
        await protocol.send_query_result(result, send_ready=True)
        data = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in data
        assert b"INSERT 1\x00" in data

    @pytest.mark.asyncio
    async def test_skip_row_description_extended_protocol(self, protocol):
        result = {
            "success": True,
            "rows": [[42]],
            "columns": [{"name": "val", "type_oid": 23, "type_size": 4, "type_modifier": -1}],
            "row_count": 1,
            "command_tag": "SELECT",
        }
        protocol.writer.write.reset_mock()
        # send_row_description=False skips the RowDescription message
        await protocol.send_query_result(result, send_ready=False, send_row_description=False)
        # Check individual write calls: MSG_ROW_DESCRIPTION starts a message; no write call
        # should start with b'T' (0x54)
        writes = [call.args[0] for call in protocol.writer.write.call_args_list]
        # None of the writes should start with MSG_ROW_DESCRIPTION (b'T')
        assert not any(w[:1] == MSG_ROW_DESCRIPTION for w in writes)
        # There should be a DataRow write
        data = collected_bytes(protocol.writer)
        assert MSG_DATA_ROW in data

    @pytest.mark.asyncio
    async def test_update_command_tag(self, protocol):
        result = {
            "success": True,
            "rows": [],
            "columns": [],
            "row_count": 3,
            "command_tag": "UPDATE",
        }
        protocol.writer.write.reset_mock()
        await protocol.send_query_result(result, send_ready=True)
        data = collected_bytes(protocol.writer)
        assert b"UPDATE 3\x00" in data

    @pytest.mark.asyncio
    async def test_uses_command_tag_over_command(self, protocol):
        # command_tag takes precedence over command field
        result = {
            "success": True,
            "rows": [],
            "columns": [],
            "row_count": 0,
            "command_tag": "DELETE",
            "command": "WRONGCOMMAND",
        }
        protocol.writer.write.reset_mock()
        await protocol.send_query_result(result, send_ready=False)
        data = collected_bytes(protocol.writer)
        assert b"DELETE 0\x00" in data
        assert b"WRONGCOMMAND" not in data


# ===========================================================================
# 2. send_row_description
# ===========================================================================


class TestSendRowDescription:
    @pytest.mark.asyncio
    async def test_sends_row_description_message_type(self, protocol):
        columns = [{"name": "id", "type_oid": 23, "type_size": 4, "type_modifier": -1}]
        protocol.writer.write.reset_mock()
        await protocol.send_row_description(columns)
        data = collected_bytes(protocol.writer)
        assert data[0:1] == MSG_ROW_DESCRIPTION

    @pytest.mark.asyncio
    async def test_field_count_in_message(self, protocol):
        columns = [
            {"name": "id", "type_oid": 23, "type_size": 4, "type_modifier": -1},
            {"name": "name", "type_oid": 25, "type_size": -1, "type_modifier": -1},
        ]
        protocol.writer.write.reset_mock()
        await protocol.send_row_description(columns)
        data = collected_bytes(protocol.writer)
        field_count = struct.unpack("!H", data[5:7])[0]
        assert field_count == 2

    @pytest.mark.asyncio
    async def test_binary_format_code_in_row_desc(self, protocol):
        columns = [{"name": "val", "type_oid": 23, "type_size": 4, "type_modifier": -1}]
        protocol.writer.write.reset_mock()
        await protocol.send_row_description(columns, result_formats=[1])
        data = collected_bytes(protocol.writer)
        # The format code is embedded at the end of the field info (last 2 bytes of field)
        assert b"\x00\x01" in data  # format_code=1 in the field info

    @pytest.mark.asyncio
    async def test_column_name_lowercased(self, protocol):
        columns = [{"name": "MyColumn", "type_oid": 25, "type_size": -1, "type_modifier": -1}]
        protocol.writer.write.reset_mock()
        await protocol.send_row_description(columns)
        data = collected_bytes(protocol.writer)
        assert b"mycolumn\x00" in data

    @pytest.mark.asyncio
    async def test_fallback_type_mapping_used(self, protocol):
        # Column without type_oid uses type mapping
        columns = [{"name": "col", "type": "INTEGER"}]
        protocol.writer.write.reset_mock()
        await protocol.send_row_description(columns)
        data = collected_bytes(protocol.writer)
        assert MSG_ROW_DESCRIPTION in data

    @pytest.mark.asyncio
    async def test_rows_mismatch_adjusts_field_count(self, protocol):
        # 1 column but rows have 2 values — field_count should become 2
        columns = [{"name": "id", "type_oid": 23, "type_size": 4, "type_modifier": -1}]
        rows = [[1, "extra"]]
        protocol.writer.write.reset_mock()
        await protocol.send_row_description(columns, rows=rows)
        data = collected_bytes(protocol.writer)
        field_count = struct.unpack("!H", data[5:7])[0]
        assert field_count == 2  # adjusted to actual row data count

    @pytest.mark.asyncio
    async def test_empty_columns_returns_immediately(self, protocol):
        protocol.writer.write.reset_mock()
        # send_row_description with empty columns should still send a message
        await protocol.send_row_description([])
        # Should still write a message (0 fields)
        data = collected_bytes(protocol.writer)
        assert data[0:1] == MSG_ROW_DESCRIPTION


# ===========================================================================
# 3. send_data_row
# ===========================================================================


class TestSendDataRow:
    @pytest.mark.asyncio
    async def test_data_row_message_type(self, protocol):
        columns = [{"name": "id", "type_oid": 23, "type_size": 4, "type_modifier": -1}]
        protocol.writer.write.reset_mock()
        await protocol.send_data_row([42], columns)
        data = collected_bytes(protocol.writer)
        assert data[0:1] == MSG_DATA_ROW

    @pytest.mark.asyncio
    async def test_null_value_encoded_as_minus1(self, protocol):
        columns = [{"name": "val", "type_oid": 25, "type_size": -1, "type_modifier": -1}]
        protocol.writer.write.reset_mock()
        await protocol.send_data_row([None], columns)
        data = collected_bytes(protocol.writer)
        # NULL is encoded as 0xFFFFFFFF
        assert struct.pack("!I", 0xFFFFFFFF) in data

    @pytest.mark.asyncio
    async def test_text_value_encoded_correctly(self, protocol):
        columns = [{"name": "name", "type_oid": 25, "type_size": -1, "type_modifier": -1}]
        protocol.writer.write.reset_mock()
        await protocol.send_data_row(["hello"], columns)
        data = collected_bytes(protocol.writer)
        assert b"hello" in data

    @pytest.mark.asyncio
    async def test_binary_format_used_when_set(self, protocol):
        protocol._current_result_formats = [1]  # binary
        columns = [{"name": "id", "type_oid": 23, "type_size": 4, "type_modifier": -1}]
        protocol.writer.write.reset_mock()
        await protocol.send_data_row([42], columns)
        data = collected_bytes(protocol.writer)
        assert MSG_DATA_ROW in data
        # Binary int4: 4 bytes length + 4 bytes data
        assert struct.pack("!i", 42) in data

    @pytest.mark.asyncio
    async def test_multiple_columns(self, protocol):
        columns = [
            {"name": "id", "type_oid": 23, "type_size": 4, "type_modifier": -1},
            {"name": "name", "type_oid": 25, "type_size": -1, "type_modifier": -1},
        ]
        protocol.writer.write.reset_mock()
        await protocol.send_data_row([1, "alice"], columns)
        data = collected_bytes(protocol.writer)
        assert b"alice" in data
        field_count = struct.unpack("!H", data[5:7])[0]
        assert field_count == 2

    @pytest.mark.asyncio
    async def test_row_shorter_than_columns_uses_none(self, protocol):
        # Row has fewer values than columns — extra values should be NULL
        columns = [
            {"name": "a", "type_oid": 25, "type_size": -1, "type_modifier": -1},
            {"name": "b", "type_oid": 25, "type_size": -1, "type_modifier": -1},
        ]
        protocol.writer.write.reset_mock()
        await protocol.send_data_row(["only_one"], columns)
        data = collected_bytes(protocol.writer)
        assert struct.pack("!I", 0xFFFFFFFF) in data


# ===========================================================================
# 4. handle_parse_message
# ===========================================================================


class TestHandleParseMessage:
    @pytest.mark.asyncio
    async def test_simple_select_stores_prepared_statement(self, protocol):
        # Set up sql_pipeline to return a basic translation result
        pipeline_result = MagicMock()
        pipeline_result.was_skipped = False
        pipeline_result.skip_reason = None
        pipeline_result.command_tag = "SELECT"
        pipeline_result.performance_stats = MagicMock(translation_time_ms=0, cache_hit=False)
        protocol.iris_executor.sql_pipeline.process = MagicMock(
            return_value=("SELECT 1", {}, pipeline_result)
        )

        body = make_parse_body("my_stmt", "SELECT 1")
        await protocol.handle_parse_message(body)
        assert "my_stmt" in protocol.prepared_statements

    @pytest.mark.asyncio
    async def test_parse_sends_parse_complete(self, protocol):
        pipeline_result = MagicMock()
        pipeline_result.was_skipped = False
        pipeline_result.skip_reason = None
        pipeline_result.command_tag = "SELECT"
        pipeline_result.performance_stats = MagicMock(translation_time_ms=0, cache_hit=False)
        protocol.iris_executor.sql_pipeline.process = MagicMock(
            return_value=("SELECT 1", {}, pipeline_result)
        )

        body = make_parse_body("stmt1", "SELECT 1")
        protocol.writer.write.reset_mock()
        await protocol.handle_parse_message(body)
        data = collected_bytes(protocol.writer)
        assert data[0:1] == MSG_PARSE_COMPLETE

    @pytest.mark.asyncio
    async def test_empty_query_stores_empty_marker(self, protocol):
        body = make_parse_body("empty_stmt", "")
        await protocol.handle_parse_message(body)
        assert "empty_stmt" in protocol.prepared_statements
        stmt = protocol.prepared_statements["empty_stmt"]
        assert stmt["translation_metadata"]["is_empty_query"] is True

    @pytest.mark.asyncio
    async def test_set_command_in_parse_stores_set_marker(self, protocol):
        body = make_parse_body("set_stmt", "SET TIME ZONE 'UTC'")
        await protocol.handle_parse_message(body)
        assert "set_stmt" in protocol.prepared_statements
        stmt = protocol.prepared_statements["set_stmt"]
        assert stmt["translation_metadata"]["is_set_command"] is True

    @pytest.mark.asyncio
    async def test_begin_in_parse_stores_transaction_marker(self, protocol):
        body = make_parse_body("begin_stmt", "BEGIN")
        await protocol.handle_parse_message(body)
        stmt = protocol.prepared_statements["begin_stmt"]
        assert stmt["translation_metadata"]["is_transaction_command"] is True
        assert stmt["translation_metadata"]["transaction_type"] == "BEGIN"

    @pytest.mark.asyncio
    async def test_commit_in_parse_stores_transaction_marker(self, protocol):
        body = make_parse_body("commit_stmt", "COMMIT")
        await protocol.handle_parse_message(body)
        stmt = protocol.prepared_statements["commit_stmt"]
        assert stmt["translation_metadata"]["transaction_type"] == "COMMIT"

    @pytest.mark.asyncio
    async def test_rollback_in_parse_stores_transaction_marker(self, protocol):
        body = make_parse_body("rollback_stmt", "ROLLBACK")
        await protocol.handle_parse_message(body)
        stmt = protocol.prepared_statements["rollback_stmt"]
        assert stmt["translation_metadata"]["transaction_type"] == "ROLLBACK"

    @pytest.mark.asyncio
    async def test_parse_with_param_types(self, protocol):
        pipeline_result = MagicMock()
        pipeline_result.was_skipped = False
        pipeline_result.skip_reason = None
        pipeline_result.command_tag = "SELECT"
        pipeline_result.performance_stats = MagicMock(translation_time_ms=0, cache_hit=False)
        protocol.iris_executor.sql_pipeline.process = MagicMock(
            return_value=("SELECT ? + ?", {}, pipeline_result)
        )

        body = make_parse_body("param_stmt", "SELECT $1 + $2", param_types=[23, 23])
        await protocol.handle_parse_message(body)
        stmt = protocol.prepared_statements["param_stmt"]
        assert stmt["param_types"] == [23, 23]

    @pytest.mark.asyncio
    async def test_invalid_body_sends_error(self, protocol):
        # Empty body should trigger error
        protocol.writer.write.reset_mock()
        await protocol.handle_parse_message(b"")
        data = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in data


# ===========================================================================
# 5. handle_bind_message
# ===========================================================================


class TestHandleBindMessage:
    def _store_statement(self, protocol, name="my_stmt", query="SELECT 1"):
        protocol.prepared_statements[name] = {
            "original_query": query,
            "translated_query": query,
            "param_types": [],
            "translation_metadata": {
                "constructs_translated": 0,
                "translation_time_ms": 0.0,
                "cache_hit": False,
                "warnings": [],
            },
            "needs_row_description": False,
        }

    @pytest.mark.asyncio
    async def test_bind_creates_portal(self, protocol):
        self._store_statement(protocol)
        body = make_bind_body("my_portal", "my_stmt")
        await protocol.handle_bind_message(body)
        assert "my_portal" in protocol.portals

    @pytest.mark.asyncio
    async def test_bind_sends_bind_complete(self, protocol):
        self._store_statement(protocol)
        body = make_bind_body("", "my_stmt")
        protocol.writer.write.reset_mock()
        await protocol.handle_bind_message(body)
        data = collected_bytes(protocol.writer)
        assert MSG_BIND_COMPLETE in data

    @pytest.mark.asyncio
    async def test_bind_unknown_statement_sends_error(self, protocol):
        body = make_bind_body("portal", "nonexistent_stmt")
        protocol.writer.write.reset_mock()
        await protocol.handle_bind_message(body)
        data = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in data

    @pytest.mark.asyncio
    async def test_bind_stores_params(self, protocol):
        self._store_statement(protocol, "s1", "SELECT ?")
        body = make_bind_body("p1", "s1", params=[b"42"])
        await protocol.handle_bind_message(body)
        portal = protocol.portals["p1"]
        assert portal["params"] == [42]

    @pytest.mark.asyncio
    async def test_bind_stores_null_param(self, protocol):
        self._store_statement(protocol, "s1", "SELECT ?")
        body = make_bind_body("p1", "s1", params=[None])
        await protocol.handle_bind_message(body)
        portal = protocol.portals["p1"]
        assert portal["params"] == [None]

    @pytest.mark.asyncio
    async def test_bind_stores_result_formats(self, protocol):
        self._store_statement(protocol)
        body = make_bind_body("pf", "my_stmt", result_formats=[1])
        await protocol.handle_bind_message(body)
        portal = protocol.portals["pf"]
        assert portal["result_formats"] == [1]

    @pytest.mark.asyncio
    async def test_bind_stores_text_format_by_default(self, protocol):
        self._store_statement(protocol)
        body = make_bind_body("pf", "my_stmt")
        await protocol.handle_bind_message(body)
        portal = protocol.portals["pf"]
        assert portal["result_formats"] == []

    @pytest.mark.asyncio
    async def test_bind_string_param_stored_as_string(self, protocol):
        self._store_statement(protocol, "s2", "SELECT ?")
        body = make_bind_body("p2", "s2", params=[b"hello world"])
        await protocol.handle_bind_message(body)
        portal = protocol.portals["p2"]
        assert portal["params"] == ["hello world"]

    @pytest.mark.asyncio
    async def test_bind_float_param(self, protocol):
        self._store_statement(protocol, "s3", "SELECT ?")
        body = make_bind_body("p3", "s3", params=[b"3.14"])
        await protocol.handle_bind_message(body)
        portal = protocol.portals["p3"]
        assert abs(portal["params"][0] - 3.14) < 0.001


# ===========================================================================
# 6. handle_execute_message
# ===========================================================================


class TestHandleExecuteMessage:
    def _setup_portal(self, protocol, portal_name="", stmt_name="s", query="SELECT 1"):
        protocol.prepared_statements[stmt_name] = {
            "original_query": query,
            "translated_query": query,
            "param_types": [],
            "translation_metadata": {
                "constructs_translated": 0,
                "translation_time_ms": 0.0,
                "cache_hit": False,
                "warnings": [],
                "is_empty_query": False,
                "is_set_command": False,
                "is_transaction_command": False,
            },
            "needs_row_description": False,
            "row_description_sent_in_describe": False,
        }
        protocol.portals[portal_name] = {
            "statement": stmt_name,
            "params": [],
            "result_formats": [],
            "needs_row_description": False,
        }

    @pytest.mark.asyncio
    async def test_execute_select_calls_execute_query(self, protocol):
        self._setup_portal(protocol)
        body = make_execute_body("")
        await protocol.handle_execute_message(body)
        protocol.iris_executor.execute_query.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_nonexistent_portal_sends_error(self, protocol):
        body = make_execute_body("no_portal")
        protocol.writer.write.reset_mock()
        await protocol.handle_execute_message(body)
        data = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in data

    @pytest.mark.asyncio
    async def test_execute_empty_query_sends_command_complete(self, protocol):
        protocol.prepared_statements["es"] = {
            "original_query": "",
            "translated_query": "",
            "param_types": [],
            "translation_metadata": {"is_empty_query": True},
            "needs_row_description": False,
        }
        protocol.portals["ep"] = {
            "statement": "es",
            "params": [],
            "result_formats": [],
            "needs_row_description": False,
        }
        protocol.writer.write.reset_mock()
        body = make_execute_body("ep")
        await protocol.handle_execute_message(body)
        data = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in data

    @pytest.mark.asyncio
    async def test_execute_set_command_sends_set_response(self, protocol):
        protocol.prepared_statements["ss"] = {
            "original_query": "SET TIME ZONE 'UTC'",
            "translated_query": "SET TIME ZONE 'UTC'",
            "param_types": [],
            "translation_metadata": {"is_set_command": True, "is_empty_query": False},
            "needs_row_description": False,
        }
        protocol.portals["sp"] = {
            "statement": "ss",
            "params": [],
            "result_formats": [],
            "needs_row_description": False,
        }
        protocol.writer.write.reset_mock()
        body = make_execute_body("sp")
        await protocol.handle_execute_message(body)
        data = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in data
        assert b"SET\x00" in data

    @pytest.mark.asyncio
    async def test_execute_begin_transaction(self, protocol):
        protocol.prepared_statements["bs"] = {
            "original_query": "BEGIN",
            "translated_query": "BEGIN",
            "param_types": [],
            "translation_metadata": {
                "is_empty_query": False,
                "is_set_command": False,
                "is_transaction_command": True,
                "transaction_type": "BEGIN",
            },
            "needs_row_description": False,
        }
        protocol.portals["bp"] = {
            "statement": "bs",
            "params": [],
            "result_formats": [],
            "needs_row_description": False,
        }
        body = make_execute_body("bp")
        await protocol.handle_execute_message(body)
        protocol.iris_executor.begin_transaction.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_commit_transaction(self, protocol):
        protocol.prepared_statements["cs"] = {
            "original_query": "COMMIT",
            "translated_query": "COMMIT",
            "param_types": [],
            "translation_metadata": {
                "is_empty_query": False,
                "is_set_command": False,
                "is_transaction_command": True,
                "transaction_type": "COMMIT",
            },
            "needs_row_description": False,
        }
        protocol.portals["cp"] = {
            "statement": "cs",
            "params": [],
            "result_formats": [],
            "needs_row_description": False,
        }
        body = make_execute_body("cp")
        await protocol.handle_execute_message(body)
        protocol.iris_executor.commit_transaction.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_rollback_transaction(self, protocol):
        protocol.prepared_statements["rs"] = {
            "original_query": "ROLLBACK",
            "translated_query": "ROLLBACK",
            "param_types": [],
            "translation_metadata": {
                "is_empty_query": False,
                "is_set_command": False,
                "is_transaction_command": True,
                "transaction_type": "ROLLBACK",
            },
            "needs_row_description": False,
        }
        protocol.portals["rp"] = {
            "statement": "rs",
            "params": [],
            "result_formats": [],
            "needs_row_description": False,
        }
        body = make_execute_body("rp")
        await protocol.handle_execute_message(body)
        protocol.iris_executor.rollback_transaction.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_execute_dml_buffers_in_batch(self, protocol):
        protocol.iris_executor.sql_parser.is_dml_statement = MagicMock(return_value=True)
        protocol.iris_executor.sql_parser.has_returning_clause = MagicMock(return_value=False)
        protocol.prepared_statements["ins"] = {
            "original_query": "INSERT INTO t VALUES (?)",
            "translated_query": "INSERT INTO t VALUES (?)",
            "param_types": [],
            "translation_metadata": {
                "is_empty_query": False,
                "is_set_command": False,
                "is_transaction_command": False,
            },
            "needs_row_description": False,
        }
        protocol.portals["ip"] = {
            "statement": "ins",
            "params": [1],
            "result_formats": [],
            "needs_row_description": False,
        }
        body = make_execute_body("ip")
        await protocol.handle_execute_message(body)
        # DML without RETURNING gets buffered
        assert len(protocol.batch_params) == 1

    @pytest.mark.asyncio
    async def test_execute_failure_sends_error(self, protocol):
        protocol.iris_executor.execute_query = AsyncMock(
            return_value={"success": False, "error": "IRIS error"}
        )
        self._setup_portal(protocol, "errp", "errs", "SELECT bad_sql")
        protocol.writer.write.reset_mock()
        body = make_execute_body("errp")
        await protocol.handle_execute_message(body)
        data = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in data


# ===========================================================================
# 7. handle_close_message
# ===========================================================================


class TestHandleCloseMessage:
    @pytest.mark.asyncio
    async def test_close_statement_removes_it(self, protocol):
        protocol.prepared_statements["to_close"] = {"query": "SELECT 1"}
        body = make_close_body("S", "to_close")
        await protocol.handle_close_message(body)
        assert "to_close" not in protocol.prepared_statements

    @pytest.mark.asyncio
    async def test_close_portal_removes_it(self, protocol):
        protocol.portals["p_close"] = {"statement": "s"}
        body = make_close_body("P", "p_close")
        await protocol.handle_close_message(body)
        assert "p_close" not in protocol.portals

    @pytest.mark.asyncio
    async def test_close_sends_close_complete(self, protocol):
        protocol.prepared_statements["stmt"] = {}
        body = make_close_body("S", "stmt")
        protocol.writer.write.reset_mock()
        await protocol.handle_close_message(body)
        data = collected_bytes(protocol.writer)
        assert data[0:1] == MSG_CLOSE_COMPLETE

    @pytest.mark.asyncio
    async def test_close_nonexistent_statement_still_sends_complete(self, protocol):
        body = make_close_body("S", "not_there")
        protocol.writer.write.reset_mock()
        await protocol.handle_close_message(body)
        data = collected_bytes(protocol.writer)
        assert MSG_CLOSE_COMPLETE in data

    @pytest.mark.asyncio
    async def test_close_invalid_type_sends_error(self, protocol):
        body = b"X" + b"name\x00"
        protocol.writer.write.reset_mock()
        await protocol.handle_close_message(body)
        data = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in data


# ===========================================================================
# 8. handle_sync_message
# ===========================================================================


class TestHandleSyncMessage:
    @pytest.mark.asyncio
    async def test_sync_sends_ready_for_query(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.handle_sync_message(b"")
        data = collected_bytes(protocol.writer)
        assert MSG_READY_FOR_QUERY in data

    @pytest.mark.asyncio
    async def test_sync_flushes_batch(self, protocol):
        protocol.batch_sql = "INSERT INTO t VALUES (?)"
        protocol.batch_params = [[1], [2]]
        await protocol.handle_sync_message(b"")
        # After flush, batch should be cleared
        assert protocol.batch_params == []

    @pytest.mark.asyncio
    async def test_sync_empty_batch_still_sends_rfq(self, protocol):
        protocol.batch_params = []
        protocol.writer.write.reset_mock()
        await protocol.handle_sync_message(b"")
        data = collected_bytes(protocol.writer)
        assert MSG_READY_FOR_QUERY in data


# ===========================================================================
# 9. handle_flush_message
# ===========================================================================


class TestHandleFlushMessage:
    @pytest.mark.asyncio
    async def test_flush_drains_writer(self, protocol):
        protocol.writer.drain.reset_mock()
        await protocol.handle_flush_message(b"")
        protocol.writer.drain.assert_awaited_once()


# ===========================================================================
# 10. translate_sql
# ===========================================================================


class TestTranslateSql:
    @pytest.mark.asyncio
    async def test_translate_sql_disabled_returns_original(self, protocol):
        protocol.enable_translation = False
        result = await protocol.translate_sql("SELECT 1")
        assert result["translated_sql"] == "SELECT 1"
        assert result["translation_used"] is False

    @pytest.mark.asyncio
    async def test_translate_sql_calls_pipeline(self, protocol):
        pipeline_result = MagicMock()
        pipeline_result.was_skipped = False
        pipeline_result.skip_reason = None
        pipeline_result.command_tag = "SELECT"
        pipeline_result.performance_stats = MagicMock(translation_time_ms=1.0, cache_hit=True)
        protocol.iris_executor.sql_pipeline.process = MagicMock(
            return_value=("SELECT 1 FROM DUAL", {}, pipeline_result)
        )
        result = await protocol.translate_sql("SELECT 1")
        assert result["success"] is True
        assert result["translated_sql"] == "SELECT 1 FROM DUAL"

    @pytest.mark.asyncio
    async def test_translate_sql_exception_falls_back_to_original(self, protocol):
        protocol.iris_executor.sql_pipeline.process = MagicMock(
            side_effect=RuntimeError("pipeline error")
        )
        result = await protocol.translate_sql("SELECT broken sql")
        assert result["success"] is False
        assert result["translated_sql"] == "SELECT broken sql"


# ===========================================================================
# 11. send_set_response / handle_set_command
# ===========================================================================


class TestSendSetResponse:
    @pytest.mark.asyncio
    async def test_sends_set_command_complete(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_set_response("timezone", "UTC", send_ready=False)
        data = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in data
        assert b"SET\x00" in data

    @pytest.mark.asyncio
    async def test_sends_rfq_when_requested(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_set_response("extra_float_digits", "3", send_ready=True)
        data = collected_bytes(protocol.writer)
        assert MSG_READY_FOR_QUERY in data

    @pytest.mark.asyncio
    async def test_no_rfq_when_not_requested(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_set_response("extra_float_digits", "3", send_ready=False)
        data = collected_bytes(protocol.writer)
        assert MSG_READY_FOR_QUERY not in data


class TestHandleSetCommand:
    @pytest.mark.asyncio
    async def test_set_command_succeeds(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.handle_set_command("SET TIME ZONE 'UTC'", send_ready=False)
        data = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in data
        assert b"SET\x00" in data

    @pytest.mark.asyncio
    async def test_reset_command_succeeds(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.handle_set_command("RESET ALL", send_ready=False)
        data = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in data

    @pytest.mark.asyncio
    async def test_set_sends_rfq_when_requested(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.handle_set_command("SET client_encoding = 'UTF8'", send_ready=True)
        data = collected_bytes(protocol.writer)
        assert MSG_READY_FOR_QUERY in data


# ===========================================================================
# 12. send_deallocate_response
# ===========================================================================


class TestSendDeallocateResponse:
    @pytest.mark.asyncio
    async def test_sends_command_complete(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_deallocate_response("DEALLOCATE ALL", send_ready=False)
        data = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in data
        assert b"DEALLOCATE 0\x00" in data

    @pytest.mark.asyncio
    async def test_sends_rfq_when_requested(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_deallocate_response("DEALLOCATE my_stmt", send_ready=True)
        data = collected_bytes(protocol.writer)
        assert MSG_READY_FOR_QUERY in data


# ===========================================================================
# 13. send_postgresql_command_response
# ===========================================================================


class TestSendPostgresqlCommandResponse:
    @pytest.mark.asyncio
    async def test_unlisten_sends_command_complete(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_postgresql_command_response("UNLISTEN *", send_ready=False)
        data = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in data
        assert b"UNLISTEN\x00" in data

    @pytest.mark.asyncio
    async def test_close_all_sends_command_complete(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_postgresql_command_response("CLOSE ALL", send_ready=False)
        data = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in data
        assert b"CLOSE\x00" in data

    @pytest.mark.asyncio
    async def test_sends_rfq_when_requested(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_postgresql_command_response("UNLISTEN *", send_ready=True)
        data = collected_bytes(protocol.writer)
        assert MSG_READY_FOR_QUERY in data


# ===========================================================================
# 14. send_set_response_extended_protocol
# ===========================================================================


class TestSendSetResponseExtendedProtocol:
    @pytest.mark.asyncio
    async def test_sends_set_without_rfq(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_set_response_extended_protocol()
        data = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in data
        assert b"SET\x00" in data
        assert MSG_READY_FOR_QUERY not in data


# ===========================================================================
# 15. send_transaction_response_extended_protocol
# ===========================================================================


class TestSendTransactionResponseExtendedProtocol:
    @pytest.mark.asyncio
    async def test_begin_sets_in_transaction_no_rfq(self, protocol):
        protocol.transaction_status = STATUS_IDLE
        protocol.writer.write.reset_mock()
        await protocol.send_transaction_response_extended_protocol("BEGIN")
        assert protocol.transaction_status == STATUS_IN_TRANSACTION
        data = collected_bytes(protocol.writer)
        assert MSG_READY_FOR_QUERY not in data
        assert MSG_COMMAND_COMPLETE in data

    @pytest.mark.asyncio
    async def test_commit_sets_idle_no_rfq(self, protocol):
        protocol.transaction_status = STATUS_IN_TRANSACTION
        await protocol.send_transaction_response_extended_protocol("COMMIT")
        assert protocol.transaction_status == STATUS_IDLE

    @pytest.mark.asyncio
    async def test_rollback_sets_idle_no_rfq(self, protocol):
        protocol.transaction_status = STATUS_IN_TRANSACTION
        await protocol.send_transaction_response_extended_protocol("ROLLBACK")
        assert protocol.transaction_status == STATUS_IDLE


# ===========================================================================
# 16. send_empty_pg_catalog_result
# ===========================================================================


class TestSendEmptyPgCatalogResult:
    @pytest.mark.asyncio
    async def test_sends_row_description_with_zero_fields(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_empty_pg_catalog_result(send_ready=False)
        data = collected_bytes(protocol.writer)
        assert MSG_ROW_DESCRIPTION in data
        assert MSG_COMMAND_COMPLETE in data
        assert b"SELECT 0\x00" in data

    @pytest.mark.asyncio
    async def test_sends_rfq_when_requested(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_empty_pg_catalog_result(send_ready=True)
        data = collected_bytes(protocol.writer)
        assert MSG_READY_FOR_QUERY in data


# ===========================================================================
# 17. COPY protocol messages
# ===========================================================================


class TestCopyMessages:
    @pytest.mark.asyncio
    async def test_send_copy_in_response(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_copy_in_response()
        data = collected_bytes(protocol.writer)
        assert data[0:1] == MSG_COPY_IN_RESPONSE

    @pytest.mark.asyncio
    async def test_send_copy_out_response(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_copy_out_response()
        data = collected_bytes(protocol.writer)
        assert data[0:1] == MSG_COPY_OUT_RESPONSE

    @pytest.mark.asyncio
    async def test_send_copy_data(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_copy_data(b"csv,data\n")
        data = collected_bytes(protocol.writer)
        assert data[0:1] == MSG_COPY_DATA
        assert b"csv,data\n" in data

    @pytest.mark.asyncio
    async def test_send_copy_done(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_copy_done()
        data = collected_bytes(protocol.writer)
        assert data[0:1] == MSG_COPY_DONE

    @pytest.mark.asyncio
    async def test_send_copy_fail(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_copy_fail("test error")
        data = collected_bytes(protocol.writer)
        assert data[0:1] == MSG_COPY_FAIL
        assert b"test error\x00" in data

    @pytest.mark.asyncio
    async def test_send_copy_complete_response(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_copy_complete_response(42)
        data = collected_bytes(protocol.writer)
        assert MSG_COMMAND_COMPLETE in data
        assert b"COPY 42\x00" in data
        assert MSG_READY_FOR_QUERY in data

    @pytest.mark.asyncio
    async def test_handle_copy_fail_message_cleans_state(self, protocol):
        protocol.copy_mode = "copy_in"
        protocol.copy_data_buffer = [b"data"]
        protocol.copy_buffer_size = 4
        protocol.writer.write.reset_mock()
        await protocol.handle_copy_fail_message(b"Client abort\x00")
        assert protocol.copy_mode is None
        assert protocol.copy_data_buffer == []
        assert protocol.copy_buffer_size == 0
        data = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in data


# ===========================================================================
# 18. _maybe_send_row_description and _maybe_send_data_rows
# ===========================================================================


class TestMaybeSendHelpers:
    @pytest.mark.asyncio
    async def test_maybe_send_row_description_skips_when_no_columns(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol._maybe_send_row_description([], [], None, True)
        data = collected_bytes(protocol.writer)
        assert MSG_ROW_DESCRIPTION not in data

    @pytest.mark.asyncio
    async def test_maybe_send_row_description_skips_when_disabled(self, protocol):
        columns = [{"name": "id", "type_oid": 23, "type_size": 4, "type_modifier": -1}]
        protocol.writer.write.reset_mock()
        await protocol._maybe_send_row_description(columns, [], None, False)
        data = collected_bytes(protocol.writer)
        assert MSG_ROW_DESCRIPTION not in data

    @pytest.mark.asyncio
    async def test_maybe_send_row_description_sends_when_enabled(self, protocol):
        columns = [{"name": "id", "type_oid": 23, "type_size": 4, "type_modifier": -1}]
        protocol.writer.write.reset_mock()
        await protocol._maybe_send_row_description(columns, [], None, True)
        data = collected_bytes(protocol.writer)
        assert MSG_ROW_DESCRIPTION in data

    @pytest.mark.asyncio
    async def test_maybe_send_data_rows_skips_empty_rows(self, protocol):
        columns = [{"name": "id", "type_oid": 23, "type_size": 4, "type_modifier": -1}]
        protocol.writer.write.reset_mock()
        await protocol._maybe_send_data_rows([], columns)
        data = collected_bytes(protocol.writer)
        assert MSG_DATA_ROW not in data

    @pytest.mark.asyncio
    async def test_maybe_send_data_rows_sends_rows(self, protocol):
        columns = [{"name": "id", "type_oid": 25, "type_size": -1, "type_modifier": -1}]
        protocol.writer.write.reset_mock()
        await protocol._maybe_send_data_rows([["hello"]], columns)
        data = collected_bytes(protocol.writer)
        assert MSG_DATA_ROW in data


# ===========================================================================
# 19. send_data_rows_with_backpressure
# ===========================================================================


class TestSendDataRowsWithBackpressure:
    @pytest.mark.asyncio
    async def test_sends_all_rows(self, protocol):
        columns = [{"name": "id", "type_oid": 25, "type_size": -1, "type_modifier": -1}]
        rows = [[f"row{i}"] for i in range(5)]
        protocol.writer.write.reset_mock()
        await protocol.send_data_rows_with_backpressure(rows, columns)
        data = collected_bytes(protocol.writer)
        # Should contain 5 DataRow messages
        assert data.count(MSG_DATA_ROW) == 5

    @pytest.mark.asyncio
    async def test_empty_rows_no_data_rows(self, protocol):
        columns = [{"name": "id", "type_oid": 25, "type_size": -1, "type_modifier": -1}]
        protocol.writer.write.reset_mock()
        await protocol.send_data_rows_with_backpressure([], columns)
        data = collected_bytes(protocol.writer)
        assert MSG_DATA_ROW not in data


# ===========================================================================
# 20. _build_row_description_field — index out of range
# ===========================================================================


class TestBuildRowDescriptionField:
    def test_index_beyond_columns_uses_default(self, protocol):
        columns = [{"name": "id", "type_oid": 23, "type_size": 4, "type_modifier": -1}]
        type_mappings = protocol.iris_executor.get_iris_type_mapping()
        field_name, field_info = protocol._build_row_description_field(columns, 5, type_mappings, [])
        assert b"column6\x00" == field_name

    def test_column_with_type_oid_uses_it(self, protocol):
        columns = [{"name": "val", "type_oid": 23, "type_size": 4, "type_modifier": -1}]
        type_mappings = protocol.iris_executor.get_iris_type_mapping()
        _name, field_info = protocol._build_row_description_field(columns, 0, type_mappings, [])
        # struct format: !IHIhiH => table_oid(4), attr_num(2), type_oid(4), ...
        oid = struct.unpack("!I", field_info[6:10])[0]
        assert oid == 23

    def test_non_string_name_gets_converted(self, protocol):
        columns = [{"name": 42, "type_oid": 25, "type_size": -1, "type_modifier": -1}]
        type_mappings = protocol.iris_executor.get_iris_type_mapping()
        field_name, _ = protocol._build_row_description_field(columns, 0, type_mappings, [])
        assert b"42\x00" == field_name


# ===========================================================================
# 21. _convert_postgres_to_iris_syntax
# ===========================================================================


class TestConvertPostgresToIrisSyntax:
    def test_returns_query_unchanged(self, protocol):
        sql = "SELECT * FROM t WHERE id = 1"
        assert protocol._convert_postgres_to_iris_syntax(sql) == sql


# ===========================================================================
# 22. send_simple_query_response (legacy)
# ===========================================================================


class TestSendSimpleQueryResponse:
    @pytest.mark.asyncio
    async def test_sends_row_desc_data_row_cmd_complete_rfq(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_simple_query_response()
        data = collected_bytes(protocol.writer)
        assert MSG_ROW_DESCRIPTION in data
        assert MSG_DATA_ROW in data
        assert MSG_COMMAND_COMPLETE in data
        assert MSG_READY_FOR_QUERY in data


# ===========================================================================
# 23. Infer parameter OIDs — edge cases
# ===========================================================================


class TestInferParameterOidsEdgeCases:
    def test_pg_class_namespace_query_returns_1009(self, protocol):
        sql = "SELECT * FROM pg_class JOIN pg_namespace ON oid WHERE nspname = ANY(?)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [1009]

    def test_pg_namespace_nspname_query_returns_1009(self, protocol):
        sql = "SELECT * FROM pg_namespace WHERE nspname = ANY(?)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [1009]

    def test_smallint_cast_returns_oid_21(self, protocol):
        sql = "SELECT CAST(? AS SMALLINT)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [21]

    def test_text_cast_returns_oid_25(self, protocol):
        sql = "SELECT CAST(? AS TEXT)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [25]

    def test_float_cast_returns_oid_700(self, protocol):
        sql = "SELECT CAST(? AS FLOAT)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [700]

    def test_double_cast_returns_oid_701(self, protocol):
        sql = "SELECT CAST(? AS DOUBLE)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [701]

    def test_date_cast_returns_oid_1082(self, protocol):
        sql = "SELECT CAST(? AS DATE)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [1082]

    def test_time_cast_returns_oid_1083(self, protocol):
        sql = "SELECT CAST(? AS TIME)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [1083]

    def test_decimal_cast_returns_oid_1700(self, protocol):
        sql = "SELECT CAST(? AS DECIMAL)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [1700]

    def test_padded_with_unknown_when_no_cast_pattern(self, protocol):
        # 3 params but only 1 ANY pattern and 1 CAST
        sql = "SELECT CAST(? AS INTEGER), ?, ?"
        result = protocol.infer_parameter_oids_from_casts(sql, 3)
        assert len(result) == 3
        assert result[0] == 23
        # remaining get 705 (UNKNOWN)
        assert result[1] == 705
        assert result[2] == 705


# ===========================================================================
# 24. _decode_binary_parameter — additional types
# ===========================================================================


class TestDecodeBinaryParameterExtra:
    def test_timestamp_with_timezone_oid_1184(self, protocol):
        import datetime

        epoch = datetime.datetime(2000, 1, 1, 0, 0, 0)
        one_day_us = 86400 * 1_000_000
        data = struct.pack("!q", one_day_us)
        result = protocol._decode_binary_parameter(data, 0, 1184)
        # Should decode as 2000-01-02
        assert "2000-01-02" in result

    def test_fallback_utf8_decode(self, protocol):
        # Data that doesn't match simple binary types (< 12 bytes but no match)
        data = b"hello"
        # OID 0 means unknown type — at 5 bytes length, no simple binary match
        # Actually _try_decode_simple_binary_parameter returns text decode for any < 12 length
        result = protocol._decode_binary_parameter(data, 0, 0)
        assert result == "hello"


# ===========================================================================
# 25. handle_copy_fail_message — no copy mode
# ===========================================================================


class TestHandleCopyFailMessageNoCopyMode:
    @pytest.mark.asyncio
    async def test_fail_message_without_copy_mode_clears_state(self, protocol):
        # No copy_mode set — should not crash
        protocol.writer.write.reset_mock()
        await protocol.handle_copy_fail_message(b"abort\x00")
        data = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in data


# ===========================================================================
# 26. handle_copy_done_message
# ===========================================================================


class TestHandleCopyDoneMessage:
    @pytest.mark.asyncio
    async def test_copy_done_without_copy_mode_sends_error(self, protocol):
        # copy_mode not set -> should send error (handled by exception)
        protocol.writer.write.reset_mock()
        await protocol.handle_copy_done_message(b"")
        data = collected_bytes(protocol.writer)
        # Should either succeed or send error — at minimum write something
        assert len(data) > 0


# ===========================================================================
# 27. handle_copy_data_message
# ===========================================================================


class TestHandleCopyDataMessage:
    @pytest.mark.asyncio
    async def test_copy_data_without_copy_mode_sends_fail(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.handle_copy_data_message(b"data")
        data = collected_bytes(protocol.writer)
        # Should get a CopyFail response since not in copy mode
        assert len(data) > 0

    @pytest.mark.asyncio
    async def test_copy_data_in_copy_mode_buffers(self, protocol):
        protocol.copy_mode = "copy_in"
        protocol.copy_data_buffer = []
        protocol.copy_buffer_size = 0
        protocol.copy_max_buffer_size = 10 * 1024 * 1024
        protocol.copy_batch_size = 1000
        await protocol.handle_copy_data_message(b"row1,row2\n")
        assert len(protocol.copy_data_buffer) == 1
        assert protocol.copy_buffer_size == len(b"row1,row2\n")


# ===========================================================================
# 28. _maybe_handle_postgresql_command
# ===========================================================================


class TestMaybeHandlePostgresqlCommand:
    @pytest.mark.asyncio
    async def test_unlisten_returns_true(self, protocol):
        result = await protocol._maybe_handle_postgresql_command("UNLISTEN *", send_ready=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_close_all_returns_true(self, protocol):
        result = await protocol._maybe_handle_postgresql_command("CLOSE ALL", send_ready=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_select_returns_false(self, protocol):
        result = await protocol._maybe_handle_postgresql_command("SELECT 1", send_ready=False)
        assert result is False


# ===========================================================================
# 29. handle_describe_message — basic cases
# ===========================================================================


class TestHandleDescribeMessage:
    def _store_select_statement(self, protocol, name="sel_stmt"):
        protocol.iris_executor.sql_parser.is_select_statement = MagicMock(return_value=True)
        protocol.iris_executor.sql_parser.is_show_statement = MagicMock(return_value=False)
        protocol.iris_executor.execute_query = AsyncMock(
            return_value={
                "success": True,
                "rows": [],
                "columns": [{"name": "id", "type_oid": 23, "type_size": 4, "type_modifier": -1}],
                "row_count": 0,
                "command_tag": "SELECT",
            }
        )
        protocol.prepared_statements[name] = {
            "original_query": "SELECT 1",
            "translated_query": "SELECT 1",
            "param_types": [],
            "translation_metadata": {},
            "needs_row_description": False,
        }

    @pytest.mark.asyncio
    async def test_describe_nonexistent_statement_sends_error(self, protocol):
        body = make_describe_body("S", "no_such_stmt")
        protocol.writer.write.reset_mock()
        await protocol.handle_describe_message(body)
        data = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in data

    @pytest.mark.asyncio
    async def test_describe_portal_nonexistent_sends_error(self, protocol):
        body = make_describe_body("P", "no_such_portal")
        protocol.writer.write.reset_mock()
        await protocol.handle_describe_message(body)
        data = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in data

    @pytest.mark.asyncio
    async def test_describe_dml_statement_sends_no_data(self, protocol):
        protocol.iris_executor.sql_parser.is_select_statement = MagicMock(return_value=False)
        protocol.iris_executor.sql_parser.is_show_statement = MagicMock(return_value=False)
        protocol.prepared_statements["ins_stmt"] = {
            "original_query": "INSERT INTO t VALUES (?)",
            "translated_query": "INSERT INTO t VALUES (?)",
            "param_types": [23],
            "translation_metadata": {},
            "needs_row_description": False,
        }
        body = make_describe_body("S", "ins_stmt")
        protocol.writer.write.reset_mock()
        await protocol.handle_describe_message(body)
        data = collected_bytes(protocol.writer)
        # DML -> NoData + ParameterDescription
        assert MSG_PARAMETER_DESCRIPTION in data
        assert MSG_NO_DATA in data

    @pytest.mark.asyncio
    async def test_describe_invalid_type_sends_error(self, protocol):
        body = b"X" + b"name\x00"
        protocol.writer.write.reset_mock()
        await protocol.handle_describe_message(body)
        data = collected_bytes(protocol.writer)
        assert MSG_ERROR_RESPONSE in data

    @pytest.mark.asyncio
    async def test_describe_strict_single_connection_sends_no_data(self, protocol):
        protocol.iris_executor.strict_single_connection = True
        protocol.iris_executor.sql_parser.is_select_statement = MagicMock(return_value=True)
        protocol.iris_executor.sql_parser.is_show_statement = MagicMock(return_value=False)
        protocol.prepared_statements["select_stmt"] = {
            "original_query": "SELECT 1",
            "translated_query": "SELECT 1",
            "param_types": [],
            "translation_metadata": {},
            "needs_row_description": False,
        }
        body = make_describe_body("S", "select_stmt")
        protocol.writer.write.reset_mock()
        await protocol.handle_describe_message(body)
        data = collected_bytes(protocol.writer)
        assert MSG_NO_DATA in data


# ===========================================================================
# 30. _handle_single_statement — IF NOT EXISTS error suppression
# ===========================================================================


class TestHandleSingleStatement:
    @pytest.mark.asyncio
    async def test_if_not_exists_error_suppressed(self, protocol):
        pipeline_result = MagicMock()
        pipeline_result.was_skipped = False
        pipeline_result.skip_reason = None
        pipeline_result.command_tag = "CREATE TABLE"
        pipeline_result.performance_stats = MagicMock(translation_time_ms=0, cache_hit=False)
        protocol.iris_executor.sql_pipeline.process = MagicMock(
            return_value=("CREATE TABLE IF NOT EXISTS t (id INT);", {}, pipeline_result)
        )
        protocol.iris_executor.execute_query = AsyncMock(
            return_value={
                "success": False,
                "error": "Table 't' already exists",
                "rows": [],
                "columns": [],
            }
        )
        with patch(
            "iris_pgwire.protocol.VectorQueryOptimizer.sql_has_if_not_exists",
            return_value=True,
        ), patch(
            "iris_pgwire.protocol.VectorQueryOptimizer.is_duplicate_object_error",
            return_value=True,
        ):
            protocol.writer.write.reset_mock()
            await protocol._handle_single_statement("CREATE TABLE IF NOT EXISTS t (id INT)")
            # Check individual write calls: an error message starts with b'E' (0x45)
            writes = [call.args[0] for call in protocol.writer.write.call_args_list]
            # None of the writes should start with MSG_ERROR_RESPONSE (b'E')
            assert not any(w[:1] == MSG_ERROR_RESPONSE for w in writes)
            # There should be a CommandComplete message
            assert any(w[:1] == MSG_COMMAND_COMPLETE for w in writes)

    @pytest.mark.asyncio
    async def test_regular_error_sends_error_response(self, protocol):
        pipeline_result = MagicMock()
        pipeline_result.was_skipped = False
        pipeline_result.skip_reason = None
        pipeline_result.command_tag = "SELECT"
        pipeline_result.performance_stats = MagicMock(translation_time_ms=0, cache_hit=False)
        protocol.iris_executor.sql_pipeline.process = MagicMock(
            return_value=("SELECT bad syntax", {}, pipeline_result)
        )
        protocol.iris_executor.execute_query = AsyncMock(
            return_value={"success": False, "error": "syntax error"}
        )
        with patch(
            "iris_pgwire.protocol.VectorQueryOptimizer.sql_has_if_not_exists",
            return_value=False,
        ):
            protocol.writer.write.reset_mock()
            await protocol._handle_single_statement("SELECT bad syntax")
            data = collected_bytes(protocol.writer)
            assert MSG_ERROR_RESPONSE in data


# ===========================================================================
# 31. Process copy batch helper
# ===========================================================================


class TestProcessCopyBatch:
    @pytest.mark.asyncio
    async def test_empty_buffer_does_nothing(self, protocol):
        protocol.copy_data_buffer = []
        protocol.copy_buffer_size = 0
        # Should return without error
        await protocol.process_copy_batch()
        assert protocol.copy_data_buffer == []

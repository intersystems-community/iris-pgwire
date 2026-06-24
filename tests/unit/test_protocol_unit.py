"""
Comprehensive unit tests for PGWireProtocol (protocol.py).

All tests use mocked dependencies — no IRIS connection required.
"""

from __future__ import annotations

import asyncio
import struct
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from iris_pgwire.protocol import (
    MSG_AUTHENTICATION,
    MSG_BACKEND_KEY_DATA,
    MSG_BIND_COMPLETE,
    MSG_CLOSE_COMPLETE,
    MSG_COMMAND_COMPLETE,
    MSG_ERROR_RESPONSE,
    MSG_NO_DATA,
    MSG_PARAMETER_DESCRIPTION,
    MSG_PARAMETER_STATUS,
    MSG_PARSE_COMPLETE,
    MSG_READY_FOR_QUERY,
    PGWireProtocol,
    STATUS_IDLE,
    STATUS_IN_TRANSACTION,
)


# ---------------------------------------------------------------------------
# Fixture
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


# ---------------------------------------------------------------------------
# Helper to collect all written bytes
# ---------------------------------------------------------------------------


def collected_bytes(writer) -> bytes:
    """Return all bytes written to writer.write() calls concatenated."""
    return b"".join(call.args[0] for call in writer.write.call_args_list)


# ===========================================================================
# 1. _format_text_value
# ===========================================================================


class TestFormatTextValue:
    def test_bool_oid_int_1_returns_t(self, protocol):
        assert protocol._format_text_value(1, 16) == "t"

    def test_bool_oid_string_1_returns_t(self, protocol):
        assert protocol._format_text_value("1", 16) == "t"

    def test_bool_oid_true_returns_t(self, protocol):
        assert protocol._format_text_value(True, 16) == "t"

    def test_bool_oid_str_t_returns_t(self, protocol):
        assert protocol._format_text_value("t", 16) == "t"

    def test_bool_oid_str_true_lower_returns_t(self, protocol):
        assert protocol._format_text_value("true", 16) == "t"

    def test_bool_oid_str_TRUE_upper_returns_t(self, protocol):
        assert protocol._format_text_value("TRUE", 16) == "t"

    def test_bool_oid_int_0_returns_f(self, protocol):
        assert protocol._format_text_value(0, 16) == "f"

    def test_bool_oid_string_0_returns_f(self, protocol):
        assert protocol._format_text_value("0", 16) == "f"

    def test_bool_oid_false_returns_f(self, protocol):
        assert protocol._format_text_value(False, 16) == "f"

    def test_bool_oid_str_f_returns_f(self, protocol):
        assert protocol._format_text_value("f", 16) == "f"

    def test_bool_oid_str_false_lower_returns_f(self, protocol):
        assert protocol._format_text_value("false", 16) == "f"

    def test_bool_oid_str_FALSE_upper_returns_f(self, protocol):
        assert protocol._format_text_value("FALSE", 16) == "f"

    def test_non_bool_oid_int_returns_str(self, protocol):
        assert protocol._format_text_value(42, 23) == "42"

    def test_non_bool_oid_float_returns_str(self, protocol):
        assert protocol._format_text_value(3.14, 701) == "3.14"

    def test_non_bool_oid_string_returns_str(self, protocol):
        assert protocol._format_text_value("hello", 25) == "hello"

    def test_non_bool_oid_none_returns_str_none(self, protocol):
        # None → str(None) = "None"
        assert protocol._format_text_value(None, 25) == "None"


# ===========================================================================
# 2. _determine_row_description_format_code
# ===========================================================================


class TestDetermineRowDescriptionFormatCode:
    def test_empty_list_returns_0(self, protocol):
        assert protocol._determine_row_description_format_code([], 0) == 0

    def test_empty_list_any_index_returns_0(self, protocol):
        assert protocol._determine_row_description_format_code([], 5) == 0

    def test_single_element_list_returns_that_element(self, protocol):
        assert protocol._determine_row_description_format_code([1], 0) == 1

    def test_single_element_list_any_index_returns_that_element(self, protocol):
        assert protocol._determine_row_description_format_code([1], 3) == 1

    def test_multi_element_list_in_range_returns_indexed_value(self, protocol):
        assert protocol._determine_row_description_format_code([0, 1, 0], 1) == 1

    def test_multi_element_list_out_of_range_returns_0(self, protocol):
        assert protocol._determine_row_description_format_code([1, 0], 5) == 0

    def test_multi_element_all_binary_first_column(self, protocol):
        assert protocol._determine_row_description_format_code([1, 1, 1], 0) == 1

    def test_multi_element_all_binary_last_column(self, protocol):
        assert protocol._determine_row_description_format_code([1, 1, 1], 2) == 1


# ===========================================================================
# 3. _get_data_row_format_code
# ===========================================================================


class TestGetDataRowFormatCode:
    def test_no_current_result_formats_attribute_returns_0(self, protocol):
        # Ensure attribute doesn't exist
        if hasattr(protocol, "_current_result_formats"):
            delattr(protocol, "_current_result_formats")
        assert protocol._get_data_row_format_code(0) == 0

    def test_empty_current_result_formats_returns_0(self, protocol):
        protocol._current_result_formats = []
        assert protocol._get_data_row_format_code(0) == 0

    def test_single_element_returns_it_for_any_index(self, protocol):
        protocol._current_result_formats = [1]
        assert protocol._get_data_row_format_code(99) == 1

    def test_multi_element_in_range(self, protocol):
        protocol._current_result_formats = [0, 1, 0]
        assert protocol._get_data_row_format_code(1) == 1

    def test_multi_element_out_of_range_returns_0(self, protocol):
        protocol._current_result_formats = [1, 0]
        assert protocol._get_data_row_format_code(10) == 0


# ===========================================================================
# 4. _transaction_flags
# ===========================================================================


class TestTransactionFlags:
    def test_idle_returns_false_true(self, protocol):
        protocol.transaction_status = STATUS_IDLE
        in_txn, autocommit = protocol._transaction_flags()
        assert in_txn is False
        assert autocommit is True

    def test_in_transaction_returns_true_false(self, protocol):
        protocol.transaction_status = STATUS_IN_TRANSACTION
        in_txn, autocommit = protocol._transaction_flags()
        assert in_txn is True
        assert autocommit is False


# ===========================================================================
# 5. infer_parameter_oids_from_casts
# ===========================================================================


class TestInferParameterOidsFromCasts:
    def test_cast_integer_returns_oid_23(self, protocol):
        sql = "SELECT CAST(? AS INTEGER)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [23]

    def test_cast_bigint_returns_oid_20(self, protocol):
        sql = "SELECT CAST(? AS BIGINT)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [20]

    def test_cast_varchar_returns_oid_1043(self, protocol):
        sql = "INSERT INTO t (name) VALUES (CAST(? AS VARCHAR))"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [1043]

    def test_cast_boolean_returns_oid_16(self, protocol):
        sql = "SELECT CAST(? AS BOOLEAN)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [16]

    def test_cast_timestamp_returns_oid_1114(self, protocol):
        sql = "SELECT CAST(? AS TIMESTAMP)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [1114]

    def test_cast_numeric_returns_oid_1700(self, protocol):
        sql = "SELECT CAST(? AS NUMERIC)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [1700]

    def test_multiple_casts_returns_ordered_list(self, protocol):
        sql = "INSERT INTO t VALUES (CAST(? AS INTEGER), CAST(? AS VARCHAR))"
        result = protocol.infer_parameter_oids_from_casts(sql, 2)
        assert result == [23, 1043]

    def test_unknown_type_returns_oid_705(self, protocol):
        sql = "SELECT CAST(? AS WEIRDTYPE)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [705]

    def test_no_casts_any_pattern_returns_1009(self, protocol):
        sql = "SELECT * FROM t WHERE nspname = ANY(?)"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [1009]

    def test_prisma_column_info_query_returns_single_param(self, protocol):
        sql = (
            "SELECT info.column_name, format_type(a, b) "
            "FROM information_schema.columns AS info "
            "WHERE info.table_name = ANY(?) AND info.column_name = ANY(?)"
        )
        result = protocol.infer_parameter_oids_from_casts(sql, 2)
        # Prisma special case → [1009]
        assert result == [1009]

    def test_result_capped_at_param_count(self, protocol):
        sql = "SELECT CAST(? AS INTEGER), CAST(? AS BIGINT), CAST(? AS TEXT)"
        result = protocol.infer_parameter_oids_from_casts(sql, 2)
        assert len(result) == 2

    def test_zero_params_returns_empty(self, protocol):
        sql = "SELECT 1"
        result = protocol.infer_parameter_oids_from_casts(sql, 0)
        assert result == []

    def test_cast_with_precision_still_matches(self, protocol):
        sql = "SELECT CAST(? AS NUMERIC(10, 2))"
        result = protocol.infer_parameter_oids_from_casts(sql, 1)
        assert result == [1700]


# ===========================================================================
# 6. _build_metadata_dummy_params
# ===========================================================================


class TestBuildMetadataDummyParams:
    def test_zero_params_returns_empty(self, protocol):
        result = protocol._build_metadata_dummy_params("SELECT 1", 0)
        assert result == []

    def test_negative_params_returns_empty(self, protocol):
        result = protocol._build_metadata_dummy_params("SELECT 1", -1)
        assert result == []

    def test_no_limit_offset_all_none(self, protocol):
        result = protocol._build_metadata_dummy_params("SELECT * FROM t WHERE id = ?", 1)
        assert result == [None]

    def test_limit_placeholder_gets_value_1(self, protocol):
        result = protocol._build_metadata_dummy_params("SELECT * FROM t LIMIT ?", 1)
        assert result[0] == 1

    def test_offset_placeholder_gets_value_0(self, protocol):
        result = protocol._build_metadata_dummy_params("SELECT * FROM t LIMIT 10 OFFSET ?", 1)
        assert result[0] == 0

    def test_limit_and_offset_together(self, protocol):
        result = protocol._build_metadata_dummy_params(
            "SELECT * FROM t LIMIT ? OFFSET ?", 2
        )
        assert result[0] == 1
        assert result[1] == 0

    def test_three_params_only_limit_changed(self, protocol):
        result = protocol._build_metadata_dummy_params(
            "SELECT * FROM t WHERE id = ? LIMIT ?", 2
        )
        assert result[0] is None  # WHERE param
        assert result[1] == 1  # LIMIT param


# ===========================================================================
# 7. _find_limit_offset_param_indexes
# ===========================================================================


class TestFindLimitOffsetParamIndexes:
    def test_no_limit_or_offset(self, protocol):
        limit_set, offset_set = protocol._find_limit_offset_param_indexes("SELECT 1")
        assert limit_set == set()
        assert offset_set == set()

    def test_limit_only(self, protocol):
        limit_set, offset_set = protocol._find_limit_offset_param_indexes(
            "SELECT * FROM t LIMIT ?"
        )
        assert 1 in limit_set
        assert offset_set == set()

    def test_offset_only(self, protocol):
        limit_set, offset_set = protocol._find_limit_offset_param_indexes(
            "SELECT * FROM t OFFSET ?"
        )
        assert 1 in offset_set
        assert limit_set == set()

    def test_limit_offset_together(self, protocol):
        limit_set, offset_set = protocol._find_limit_offset_param_indexes(
            "SELECT * FROM t LIMIT ? OFFSET ?"
        )
        assert 1 in limit_set
        assert 2 in offset_set

    def test_limit_comma_offset_style(self, protocol):
        # MySQL-style LIMIT ?,? (offset,limit)
        limit_set, offset_set = protocol._find_limit_offset_param_indexes(
            "SELECT * FROM t LIMIT ?, ?"
        )
        # First ? is offset, second is limit in LIMIT x,y syntax
        assert len(limit_set) > 0 or len(offset_set) > 0


# ===========================================================================
# 8. _split_query_statements
# ===========================================================================


class TestSplitQueryStatements:
    def test_single_statement_no_semicolon(self, protocol):
        stmts = protocol._split_query_statements("SELECT 1")
        assert len(stmts) == 1
        assert stmts[0].strip() == "SELECT 1"

    def test_two_statements_with_semicolon(self, protocol):
        stmts = protocol._split_query_statements("SELECT 1; SELECT 2")
        assert len(stmts) == 2

    def test_empty_string_returns_empty_list(self, protocol):
        stmts = protocol._split_query_statements("")
        assert stmts == [] or all(s.strip() == "" for s in stmts)

    def test_trailing_semicolon_no_extra_statement(self, protocol):
        stmts = protocol._split_query_statements("SELECT 1;")
        non_empty = [s for s in stmts if s.strip()]
        assert len(non_empty) == 1


# ===========================================================================
# 9. _serialize_column_value
# ===========================================================================


class TestSerializeColumnValue:
    def test_text_format_returns_length_prefixed_utf8(self, protocol):
        col = {"type_oid": 25}
        result = protocol._serialize_column_value("hello", col, 0, 0)
        length = struct.unpack("!I", result[:4])[0]
        assert length == 5
        assert result[4:] == b"hello"

    def test_binary_format_int4_returns_4_bytes(self, protocol):
        col = {"type_oid": 23}
        result = protocol._serialize_column_value(42, col, 1, 0)
        length = struct.unpack("!I", result[:4])[0]
        assert length == 4
        value = struct.unpack("!i", result[4:8])[0]
        assert value == 42

    def test_unknown_format_code_falls_back_to_str(self, protocol):
        col = {"type_oid": 25}
        result = protocol._serialize_column_value("test", col, 99, 0)
        length = struct.unpack("!I", result[:4])[0]
        assert length == 4
        assert result[4:] == b"test"

    def test_text_format_bool_true(self, protocol):
        col = {"type_oid": 16}
        result = protocol._serialize_column_value(True, col, 0, 0)
        length = struct.unpack("!I", result[:4])[0]
        assert result[4 : 4 + length] == b"t"

    def test_text_format_bool_false(self, protocol):
        col = {"type_oid": 16}
        result = protocol._serialize_column_value(False, col, 0, 0)
        length = struct.unpack("!I", result[:4])[0]
        assert result[4 : 4 + length] == b"f"


# ===========================================================================
# 10. _encode_binary_column_value
# ===========================================================================


class TestEncodeBinaryColumnValue:
    def test_int4_oid_23(self, protocol):
        data = protocol._encode_binary_column_value(23, 100, 0)
        assert struct.unpack("!i", data)[0] == 100

    def test_int4_negative(self, protocol):
        data = protocol._encode_binary_column_value(23, -1, 0)
        assert struct.unpack("!i", data)[0] == -1

    def test_int2_oid_21(self, protocol):
        data = protocol._encode_binary_column_value(21, 32767, 0)
        assert struct.unpack("!h", data)[0] == 32767

    def test_int8_oid_20(self, protocol):
        data = protocol._encode_binary_column_value(20, 2**40, 0)
        assert struct.unpack("!q", data)[0] == 2**40

    def test_float4_oid_700(self, protocol):
        data = protocol._encode_binary_column_value(700, 1.5, 0)
        assert len(data) == 4
        val = struct.unpack("!f", data)[0]
        assert abs(val - 1.5) < 0.001

    def test_float8_oid_701(self, protocol):
        data = protocol._encode_binary_column_value(701, 3.14159, 0)
        assert len(data) == 8
        val = struct.unpack("!d", data)[0]
        assert abs(val - 3.14159) < 1e-10

    def test_bool_true_oid_16(self, protocol):
        data = protocol._encode_binary_column_value(16, True, 0)
        assert struct.unpack("!?", data)[0] is True

    def test_bool_false_oid_16(self, protocol):
        data = protocol._encode_binary_column_value(16, False, 0)
        assert struct.unpack("!?", data)[0] is False

    def test_oid_26_unsigned_int(self, protocol):
        data = protocol._encode_binary_column_value(26, 12345, 0)
        assert struct.unpack("!I", data)[0] == 12345

    def test_oid_19_name_type_encodes_utf8(self, protocol):
        data = protocol._encode_binary_column_value(19, "pg_catalog", 0)
        assert data == b"pg_catalog"

    def test_date_oid_1082_encodes_int(self, protocol):
        data = protocol._encode_binary_column_value(1082, 0, 0)
        assert len(data) == 4

    def test_timestamp_oid_1114_from_string(self, protocol):
        data = protocol._encode_binary_column_value(1114, "2000-01-01 00:00:00", 0)
        assert len(data) == 8
        # PostgreSQL epoch → 0 microseconds
        assert struct.unpack("!q", data)[0] == 0

    def test_timestamp_oid_1114_from_datetime(self, protocol):
        import datetime

        dt = datetime.datetime(2000, 1, 1, 0, 0, 0)
        data = protocol._encode_binary_column_value(1114, dt, 0)
        assert len(data) == 8
        assert struct.unpack("!q", data)[0] == 0

    def test_numeric_oid_1700_decimal_positive(self, protocol):
        val = Decimal("123.45")
        data = protocol._encode_binary_column_value(1700, val, 0)
        # Should at least be non-empty
        assert len(data) > 0

    def test_numeric_oid_1700_non_decimal_falls_back_to_str(self, protocol):
        data = protocol._encode_binary_column_value(1700, "99.99", 0)
        assert data == b"99.99"

    def test_fallback_oid_returns_utf8(self, protocol):
        data = protocol._encode_binary_column_value(9999, "arbitrary", 0)
        assert data == b"arbitrary"

    def test_invalid_value_falls_back_to_text(self, protocol):
        # Float value for INT4 that can't be packed as int — passes via int()
        data = protocol._encode_binary_column_value(23, 7.9, 0)
        # int(7.9) == 7
        assert struct.unpack("!i", data)[0] == 7


# ===========================================================================
# 11. _decode_binary_parameter / _try_decode_simple_binary_parameter
# ===========================================================================


class TestDecodeBinaryParameter:
    def test_int2_2_bytes(self, protocol):
        data = struct.pack("!h", -300)
        result = protocol._decode_binary_parameter(data, 0, 21)
        assert result == -300

    def test_int4_4_bytes(self, protocol):
        data = struct.pack("!i", 42)
        result = protocol._decode_binary_parameter(data, 0, 23)
        assert result == 42

    def test_int8_8_bytes(self, protocol):
        data = struct.pack("!q", 10_000_000_000)
        result = protocol._decode_binary_parameter(data, 0, 20)
        assert result == 10_000_000_000

    def test_float4_4_bytes(self, protocol):
        data = struct.pack("!f", 1.5)
        result = protocol._decode_binary_parameter(data, 0, 700)
        assert abs(result - 1.5) < 0.001

    def test_float8_8_bytes(self, protocol):
        data = struct.pack("!d", 2.718281828)
        result = protocol._decode_binary_parameter(data, 0, 701)
        assert abs(result - 2.718281828) < 1e-9

    def test_bool_true_1_byte(self, protocol):
        data = b"\x01"
        result = protocol._decode_binary_parameter(data, 0, 16)
        assert result == 1

    def test_bool_false_1_byte(self, protocol):
        data = b"\x00"
        result = protocol._decode_binary_parameter(data, 0, 16)
        assert result == 0

    def test_date_4_bytes_pg_epoch(self, protocol):
        # PG epoch = 2000-01-01, days=0
        data = struct.pack("!i", 0)
        result = protocol._decode_binary_parameter(data, 0, 1082)
        assert result == "2000-01-01"

    def test_date_4_bytes_positive_days(self, protocol):
        # 1 day after epoch = 2000-01-02
        data = struct.pack("!i", 1)
        result = protocol._decode_binary_parameter(data, 0, 1082)
        assert result == "2000-01-02"

    def test_timestamp_8_bytes_epoch(self, protocol):
        data = struct.pack("!q", 0)
        result = protocol._decode_binary_parameter(data, 0, 1114)
        assert "2000-01-01" in result

    def test_simple_decode_returns_false_for_12_plus_bytes(self, protocol):
        data = b"\x00" * 12
        handled, _ = protocol._try_decode_simple_binary_parameter(data, 0, 0)
        assert handled is False


# ===========================================================================
# 12. _decode_array_binary_parameter
# ===========================================================================


class TestDecodeArrayBinaryParameter:
    def _make_array(self, elements, element_oid):
        """Build a minimal PostgreSQL binary array for a 1-D array."""
        ndim = 1
        has_null = 0
        dim_size = len(elements)
        lower_bound = 1
        header = struct.pack("!III", ndim, has_null, element_oid)
        header += struct.pack("!II", dim_size, lower_bound)
        body = b""
        for elem in elements:
            elem_bytes = struct.pack("!f", elem) if element_oid == 700 else struct.pack("!d", elem)
            body += struct.pack("!I", len(elem_bytes)) + elem_bytes
        return header + body

    def test_empty_array_ndim_0(self, protocol):
        data = struct.pack("!III", 0, 0, 700)  # ndim=0
        result = protocol._decode_array_binary_parameter(data, 0)
        assert result == "[]"

    def test_float4_vector(self, protocol):
        data = self._make_array([1.0, 2.0, 3.0], 700)
        result = protocol._decode_array_binary_parameter(data, 0)
        assert result.startswith("[")
        assert result.endswith("]")
        parts = result[1:-1].split(",")
        assert len(parts) == 3

    def test_float8_vector(self, protocol):
        data = self._make_array([0.5, 1.5], 701)
        result = protocol._decode_array_binary_parameter(data, 0)
        parts = result[1:-1].split(",")
        assert len(parts) == 2

    def test_null_element_encoded_as_NULL(self, protocol):
        # Build array with one NULL element
        ndim = 1
        element_oid = 700
        data = struct.pack("!III", ndim, 1, element_oid)  # has_null=1
        data += struct.pack("!II", 1, 1)  # dim_size=1, lb=1
        data += struct.pack("!I", 0xFFFFFFFF)  # NULL marker
        result = protocol._decode_array_binary_parameter(data, 0)
        assert "NULL" in result


# ===========================================================================
# 13. Async message-sending methods
# ===========================================================================


class TestSendAuthenticationOk:
    @pytest.mark.asyncio
    async def test_writes_authentication_ok_message(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_authentication_ok()
        data = collected_bytes(protocol.writer)
        assert data[0:1] == MSG_AUTHENTICATION
        msg_len = struct.unpack("!I", data[1:5])[0]
        assert msg_len == 8
        auth_code = struct.unpack("!I", data[5:9])[0]
        assert auth_code == 0  # AUTH_OK


class TestSendParameterStatusMessage:
    @pytest.mark.asyncio
    async def test_correct_message_format(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_parameter_status_message("server_version", "16.0")
        data = collected_bytes(protocol.writer)
        assert data[0:1] == MSG_PARAMETER_STATUS
        # Contains null-terminated name and value
        assert b"server_version\x00" in data
        assert b"16.0\x00" in data

    @pytest.mark.asyncio
    async def test_message_length_field(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_parameter_status_message("k", "v")
        data = collected_bytes(protocol.writer)
        msg_len = struct.unpack("!I", data[1:5])[0]
        # 4 (length field) + len("k\0") + len("v\0") = 4 + 2 + 2 = 8
        assert msg_len == 8


class TestSendBackendKeyData:
    @pytest.mark.asyncio
    async def test_writes_k_message(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_backend_key_data()
        data = collected_bytes(protocol.writer)
        assert data[0:1] == MSG_BACKEND_KEY_DATA
        msg_len = struct.unpack("!I", data[1:5])[0]
        assert msg_len == 12  # 4 + 4 PID + 4 secret

    @pytest.mark.asyncio
    async def test_contains_backend_pid(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_backend_key_data()
        data = collected_bytes(protocol.writer)
        pid = struct.unpack("!I", data[5:9])[0]
        assert pid == protocol.backend_pid


class TestSendReadyForQuery:
    @pytest.mark.asyncio
    async def test_idle_status(self, protocol):
        protocol.transaction_status = STATUS_IDLE
        protocol.writer.write.reset_mock()
        await protocol.send_ready_for_query()
        data = collected_bytes(protocol.writer)
        assert data[0:1] == MSG_READY_FOR_QUERY
        assert data[5:6] == STATUS_IDLE

    @pytest.mark.asyncio
    async def test_in_transaction_status(self, protocol):
        protocol.transaction_status = STATUS_IN_TRANSACTION
        protocol.writer.write.reset_mock()
        await protocol.send_ready_for_query()
        data = collected_bytes(protocol.writer)
        assert data[5:6] == STATUS_IN_TRANSACTION

    @pytest.mark.asyncio
    async def test_message_length_is_5(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_ready_for_query()
        data = collected_bytes(protocol.writer)
        msg_len = struct.unpack("!I", data[1:5])[0]
        assert msg_len == 5


class TestSendErrorResponse:
    @pytest.mark.asyncio
    async def test_writes_e_message_type(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_error_response("ERROR", "42000", "syntax_error", "bad sql")
        data = collected_bytes(protocol.writer)
        assert data[0:1] == MSG_ERROR_RESPONSE

    @pytest.mark.asyncio
    async def test_contains_severity_and_message(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_error_response("ERROR", "42000", "syntax_error", "bad sql")
        data = collected_bytes(protocol.writer)
        assert b"ERROR\x00" in data
        assert b"bad sql\x00" in data

    @pytest.mark.asyncio
    async def test_contains_sqlstate_code(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_error_response("ERROR", "42000", "syntax_error", "bad sql")
        data = collected_bytes(protocol.writer)
        assert b"42000\x00" in data


class TestSendTransactionResponse:
    @pytest.mark.asyncio
    async def test_begin_sets_in_transaction(self, protocol):
        protocol.transaction_status = STATUS_IDLE
        await protocol.send_transaction_response("BEGIN", send_ready=False)
        assert protocol.transaction_status == STATUS_IN_TRANSACTION

    @pytest.mark.asyncio
    async def test_commit_sets_idle(self, protocol):
        protocol.transaction_status = STATUS_IN_TRANSACTION
        await protocol.send_transaction_response("COMMIT", send_ready=False)
        assert protocol.transaction_status == STATUS_IDLE

    @pytest.mark.asyncio
    async def test_rollback_sets_idle(self, protocol):
        protocol.transaction_status = STATUS_IN_TRANSACTION
        await protocol.send_transaction_response("ROLLBACK", send_ready=False)
        assert protocol.transaction_status == STATUS_IDLE

    @pytest.mark.asyncio
    async def test_writes_command_complete_message(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_transaction_response("COMMIT", send_ready=False)
        data = collected_bytes(protocol.writer)
        assert data[0:1] == MSG_COMMAND_COMPLETE
        assert b"COMMIT\x00" in data

    @pytest.mark.asyncio
    async def test_send_ready_true_also_sends_rfq(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_transaction_response("BEGIN", send_ready=True)
        data = collected_bytes(protocol.writer)
        assert MSG_READY_FOR_QUERY in data


class TestSendCommandComplete:
    @pytest.mark.asyncio
    async def test_select_tag(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol._send_command_complete("SELECT", 5)
        data = collected_bytes(protocol.writer)
        assert data[0:1] == MSG_COMMAND_COMPLETE
        assert b"SELECT 5\x00" in data

    @pytest.mark.asyncio
    async def test_insert_tag(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol._send_command_complete("INSERT", 1)
        data = collected_bytes(protocol.writer)
        assert b"INSERT 1\x00" in data

    @pytest.mark.asyncio
    async def test_update_tag(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol._send_command_complete("UPDATE", 3)
        data = collected_bytes(protocol.writer)
        assert b"UPDATE 3\x00" in data


class TestMaybeHandleTransactionCommand:
    @pytest.mark.asyncio
    async def test_begin_returns_true(self, protocol):
        result = await protocol._maybe_handle_transaction_command("BEGIN", send_ready=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_start_transaction_returns_true(self, protocol):
        result = await protocol._maybe_handle_transaction_command(
            "START TRANSACTION", send_ready=False
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_commit_returns_true(self, protocol):
        result = await protocol._maybe_handle_transaction_command("COMMIT", send_ready=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_end_returns_true(self, protocol):
        result = await protocol._maybe_handle_transaction_command("END", send_ready=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_rollback_returns_true(self, protocol):
        result = await protocol._maybe_handle_transaction_command("ROLLBACK", send_ready=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_select_returns_false(self, protocol):
        result = await protocol._maybe_handle_transaction_command(
            "SELECT * FROM t", send_ready=False
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_begin_calls_begin_transaction(self, protocol):
        await protocol._maybe_handle_transaction_command("BEGIN", send_ready=False)
        protocol.iris_executor.begin_transaction.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_commit_calls_commit_transaction(self, protocol):
        await protocol._maybe_handle_transaction_command("COMMIT", send_ready=False)
        protocol.iris_executor.commit_transaction.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rollback_calls_rollback_transaction(self, protocol):
        await protocol._maybe_handle_transaction_command("ROLLBACK", send_ready=False)
        protocol.iris_executor.rollback_transaction.assert_awaited_once()


class TestMaybeHandleDeallocateCommand:
    @pytest.mark.asyncio
    async def test_deallocate_returns_true(self, protocol):
        result = await protocol._maybe_handle_deallocate_command(
            "DEALLOCATE ALL", send_ready=False
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_deallocate_stmt_name_returns_true(self, protocol):
        result = await protocol._maybe_handle_deallocate_command(
            "DEALLOCATE my_stmt", send_ready=False
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_select_returns_false(self, protocol):
        result = await protocol._maybe_handle_deallocate_command(
            "SELECT 1", send_ready=False
        )
        assert result is False


class TestMaybeHandleSetOrResetCommand:
    @pytest.mark.asyncio
    async def test_set_command_returns_true(self, protocol):
        result = await protocol._maybe_handle_set_or_reset_command(
            "SET TIME ZONE 'UTC'", send_ready=False
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_reset_command_returns_true(self, protocol):
        result = await protocol._maybe_handle_set_or_reset_command(
            "RESET ALL", send_ready=False
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_select_returns_false(self, protocol):
        result = await protocol._maybe_handle_set_or_reset_command(
            "SELECT 1", send_ready=False
        )
        assert result is False


class TestFlushBatch:
    @pytest.mark.asyncio
    async def test_empty_batch_does_nothing(self, protocol):
        protocol.batch_params = []
        await protocol.flush_batch()
        protocol.iris_executor.execute_many.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_empty_batch_calls_execute_many(self, protocol):
        protocol.batch_sql = "INSERT INTO t VALUES (?)"
        protocol.batch_params = [[1], [2], [3]]
        await protocol.flush_batch()
        protocol.iris_executor.execute_many.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_flush_clears_batch_state(self, protocol):
        protocol.batch_sql = "INSERT INTO t VALUES (?)"
        protocol.batch_params = [[1]]
        await protocol.flush_batch()
        assert protocol.batch_sql is None
        assert protocol.batch_params == []

    @pytest.mark.asyncio
    async def test_no_sql_does_not_call_execute_many(self, protocol):
        protocol.batch_sql = None
        protocol.batch_params = [[1]]
        await protocol.flush_batch()
        protocol.iris_executor.execute_many.assert_not_awaited()


class TestSendParseComplete:
    @pytest.mark.asyncio
    async def test_writes_parse_complete(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_parse_complete()
        data = collected_bytes(protocol.writer)
        assert data[0:1] == MSG_PARSE_COMPLETE
        msg_len = struct.unpack("!I", data[1:5])[0]
        assert msg_len == 4


class TestSendBindComplete:
    @pytest.mark.asyncio
    async def test_writes_bind_complete(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_bind_complete()
        data = collected_bytes(protocol.writer)
        assert data[0:1] == MSG_BIND_COMPLETE
        msg_len = struct.unpack("!I", data[1:5])[0]
        assert msg_len == 4


class TestSendCloseComplete:
    @pytest.mark.asyncio
    async def test_writes_close_complete(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_close_complete()
        data = collected_bytes(protocol.writer)
        assert data[0:1] == MSG_CLOSE_COMPLETE
        msg_len = struct.unpack("!I", data[1:5])[0]
        assert msg_len == 4


class TestSendNoData:
    @pytest.mark.asyncio
    async def test_writes_no_data_message(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_no_data()
        data = collected_bytes(protocol.writer)
        assert data[0:1] == MSG_NO_DATA
        msg_len = struct.unpack("!I", data[1:5])[0]
        assert msg_len == 4


class TestSendParameterDescription:
    @pytest.mark.asyncio
    async def test_empty_params(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_parameter_description([])
        data = collected_bytes(protocol.writer)
        assert data[0:1] == MSG_PARAMETER_DESCRIPTION
        count = struct.unpack("!H", data[5:7])[0]
        assert count == 0

    @pytest.mark.asyncio
    async def test_single_param(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_parameter_description([23])
        data = collected_bytes(protocol.writer)
        count = struct.unpack("!H", data[5:7])[0]
        assert count == 1
        oid = struct.unpack("!I", data[7:11])[0]
        assert oid == 23

    @pytest.mark.asyncio
    async def test_multiple_params(self, protocol):
        protocol.writer.write.reset_mock()
        await protocol.send_parameter_description([23, 25, 701])
        data = collected_bytes(protocol.writer)
        count = struct.unpack("!H", data[5:7])[0]
        assert count == 3


# ===========================================================================
# 14. Protocol initialization
# ===========================================================================


class TestProtocolInitialization:
    def test_transaction_status_idle_on_init(self, protocol):
        assert protocol.transaction_status == STATUS_IDLE

    def test_authenticated_false_on_init(self, protocol):
        assert protocol.authenticated is False

    def test_prepared_statements_empty_on_init(self, protocol):
        assert protocol.prepared_statements == {}

    def test_portals_empty_on_init(self, protocol):
        assert protocol.portals == {}

    def test_enable_scram_false(self, protocol):
        assert protocol.enable_scram is False

    def test_connection_id_stored(self, protocol):
        assert protocol.connection_id == "test-conn-001"

    def test_batch_params_empty_on_init(self, protocol):
        assert protocol.batch_params == []

    def test_batch_sql_none_on_init(self, protocol):
        assert protocol.batch_sql is None

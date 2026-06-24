"""Unit tests for _type_mapping.py.

No IRIS container required — pure logic tests.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from iris_pgwire._type_mapping import (
    POSIXTIME_MAX,
    POSIXTIME_OFFSET,
    detect_cast_type_oid,
    infer_type_from_value,
    iris_type_to_pg_oid,
    serialize_value,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_posixtime_offset_positive(self):
        assert POSIXTIME_OFFSET > 0

    def test_posixtime_max_greater_than_offset(self):
        assert POSIXTIME_MAX > POSIXTIME_OFFSET

    def test_posixtime_offset_value(self):
        assert POSIXTIME_OFFSET == 1152921504606846976


# ---------------------------------------------------------------------------
# iris_type_to_pg_oid — integer type codes
# ---------------------------------------------------------------------------


class TestIrisTypeToPgOidInt:
    def test_bit_negative7(self):
        assert iris_type_to_pg_oid(-7) == 16  # bool

    def test_tinyint_negative6(self):
        assert iris_type_to_pg_oid(-6) == 21  # int2

    def test_bigint_negative5(self):
        assert iris_type_to_pg_oid(-5) == 20  # int8

    def test_char_1(self):
        assert iris_type_to_pg_oid(1) == 1042  # bpchar

    def test_numeric_2(self):
        assert iris_type_to_pg_oid(2) == 1700

    def test_int4_code_4(self):
        assert iris_type_to_pg_oid(4) == 23

    def test_float8_code_5(self):
        assert iris_type_to_pg_oid(5) == 701

    def test_iris_double_8(self):
        assert iris_type_to_pg_oid(8) == 701

    def test_date_9(self):
        assert iris_type_to_pg_oid(9) == 1082

    def test_timestamp_10(self):
        assert iris_type_to_pg_oid(10) == 1114

    def test_varchar_12(self):
        assert iris_type_to_pg_oid(12) == 1043

    def test_bool_16(self):
        assert iris_type_to_pg_oid(16) == 16

    def test_bytea_17(self):
        assert iris_type_to_pg_oid(17) == 17

    def test_jdbc_date_91(self):
        assert iris_type_to_pg_oid(91) == 1082

    def test_jdbc_time_92(self):
        assert iris_type_to_pg_oid(92) == 1083

    def test_jdbc_timestamp_93(self):
        assert iris_type_to_pg_oid(93) == 1114

    def test_iris_extended_1091(self):
        assert iris_type_to_pg_oid(1091) == 1082

    def test_iris_extended_1092(self):
        assert iris_type_to_pg_oid(1092) == 1083

    def test_iris_extended_1093(self):
        assert iris_type_to_pg_oid(1093) == 1114

    def test_unknown_int_defaults_to_varchar(self):
        assert iris_type_to_pg_oid(9999) == 1043


# ---------------------------------------------------------------------------
# iris_type_to_pg_oid — string type names
# ---------------------------------------------------------------------------


class TestIrisTypeToPgOidStr:
    def test_int(self):
        assert iris_type_to_pg_oid("INT") == 23

    def test_integer(self):
        assert iris_type_to_pg_oid("INTEGER") == 23

    def test_bigint(self):
        assert iris_type_to_pg_oid("BIGINT") == 20

    def test_smallint(self):
        assert iris_type_to_pg_oid("SMALLINT") == 21

    def test_varchar(self):
        assert iris_type_to_pg_oid("VARCHAR") == 1043

    def test_char(self):
        assert iris_type_to_pg_oid("CHAR") == 1042

    def test_text(self):
        assert iris_type_to_pg_oid("TEXT") == 25

    def test_date(self):
        assert iris_type_to_pg_oid("DATE") == 1082

    def test_time(self):
        assert iris_type_to_pg_oid("TIME") == 1083

    def test_timestamp(self):
        assert iris_type_to_pg_oid("TIMESTAMP") == 1114

    def test_double(self):
        assert iris_type_to_pg_oid("DOUBLE") == 701

    def test_float(self):
        assert iris_type_to_pg_oid("FLOAT") == 700

    def test_numeric(self):
        assert iris_type_to_pg_oid("NUMERIC") == 1700

    def test_decimal(self):
        assert iris_type_to_pg_oid("DECIMAL") == 1700

    def test_bit(self):
        assert iris_type_to_pg_oid("BIT") == 1560

    def test_boolean(self):
        assert iris_type_to_pg_oid("BOOLEAN") == 16

    def test_binary(self):
        assert iris_type_to_pg_oid("BINARY") == 17

    def test_varbinary(self):
        assert iris_type_to_pg_oid("VARBINARY") == 17

    def test_vector(self):
        assert iris_type_to_pg_oid("VECTOR") == 16388

    def test_lowercase_normalised(self):
        # lowercase input should be uppercased internally
        assert iris_type_to_pg_oid("integer") == 23

    def test_with_precision_suffix_stripped(self):
        assert iris_type_to_pg_oid("VARCHAR(255)") == 1043
        assert iris_type_to_pg_oid("NUMERIC(10,2)") == 1700

    def test_unknown_string_defaults_to_varchar(self):
        assert iris_type_to_pg_oid("NOTATYPE") == 1043

    def test_empty_string_defaults_to_varchar(self):
        assert iris_type_to_pg_oid("") == 1043


# ---------------------------------------------------------------------------
# infer_type_from_value
# ---------------------------------------------------------------------------


class TestInferTypeFromValue:
    def test_none_returns_varchar(self):
        assert infer_type_from_value(None) == 1043

    def test_bool_true(self):
        assert infer_type_from_value(True) == 16

    def test_bool_false(self):
        assert infer_type_from_value(False) == 16

    def test_small_int_returns_int4(self):
        assert infer_type_from_value(42) == 23

    def test_int4_max_boundary(self):
        assert infer_type_from_value(2**31 - 1) == 23

    def test_int4_min_boundary(self):
        assert infer_type_from_value(-(2**31)) == 23

    def test_large_int_returns_bigint(self):
        assert infer_type_from_value(2**31) == 20  # just over int4 max

    def test_posixtime_int_returns_timestamp(self):
        # A value within POSIXTIME range should map to TIMESTAMP
        posixtime_val = POSIXTIME_OFFSET + 1000
        assert infer_type_from_value(posixtime_val) == 1114

    def test_posixtime_max_returns_timestamp(self):
        assert infer_type_from_value(POSIXTIME_MAX) == 1114

    def test_id_column_hint_returns_bigint(self):
        assert infer_type_from_value(100, column_name="user_id") == 20

    def test_key_column_hint_returns_bigint(self):
        assert infer_type_from_value(100, column_name="primary_key") == 20

    def test_no_column_hint_small_int_is_int4(self):
        assert infer_type_from_value(100) == 23

    def test_float_returns_float8(self):
        assert infer_type_from_value(3.14) == 701

    def test_decimal_returns_numeric(self):
        assert infer_type_from_value(Decimal("9.99")) == 1700

    def test_bytes_returns_bytea(self):
        assert infer_type_from_value(b"hello") == 17

    def test_datetime_returns_timestamp(self):
        assert infer_type_from_value(dt.datetime(2025, 1, 1, 12, 0, 0)) == 1114

    def test_date_returns_date(self):
        assert infer_type_from_value(dt.date(2025, 1, 1)) == 1082

    def test_string_returns_varchar(self):
        assert infer_type_from_value("hello") == 1043

    def test_list_returns_varchar(self):
        assert infer_type_from_value([1, 2, 3]) == 1043


# ---------------------------------------------------------------------------
# serialize_value
# ---------------------------------------------------------------------------


class TestSerializeValue:
    def test_none_returns_none(self):
        assert serialize_value(None, 1114) is None

    def test_non_timestamp_oid_passthrough(self):
        assert serialize_value(42, 23) == 42
        assert serialize_value("hello", 1043) == "hello"

    def test_datetime_serialized(self):
        val = dt.datetime(2025, 6, 15, 10, 30, 0)
        result = serialize_value(val, 1114)
        assert result == "2025-06-15 10:30:00.000000"

    def test_datetime_with_microseconds(self):
        val = dt.datetime(2025, 6, 15, 10, 30, 0, 123456)
        result = serialize_value(val, 1114)
        assert result == "2025-06-15 10:30:00.123456"

    def test_posixtime_int_converted(self):
        # POSIXTIME_OFFSET + 0 microseconds = 1970-01-01 00:00:00
        result = serialize_value(POSIXTIME_OFFSET, 1114)
        assert result == "1970-01-01 00:00:00.000000"

    def test_posixtime_int_one_second(self):
        # POSIXTIME_OFFSET + 1_000_000 microseconds = 1970-01-01 00:00:01
        result = serialize_value(POSIXTIME_OFFSET + 1_000_000, 1114)
        assert result == "1970-01-01 00:00:01.000000"

    def test_legacy_int_microseconds_since_2000(self):
        # value < POSIXTIME_OFFSET → legacy path (microseconds since 2000-01-01)
        result = serialize_value(0, 1114)
        assert result == "2000-01-01 00:00:00.000000"

    def test_timestamp_string_iso_with_space(self):
        result = serialize_value("2025-06-15 10:30:00", 1114)
        assert result == "2025-06-15 10:30:00.000000"

    def test_timestamp_string_iso_with_t(self):
        result = serialize_value("2025-06-15T10:30:00", 1114)
        assert result == "2025-06-15 10:30:00.000000"

    def test_timestamp_string_with_microseconds(self):
        result = serialize_value("2025-06-15 10:30:00.123456", 1114)
        assert result == "2025-06-15 10:30:00.123456"

    def test_timestamp_string_digit_only(self):
        # Numeric string treated as POSIXTIME (offset path)
        val_str = str(POSIXTIME_OFFSET)
        result = serialize_value(val_str, 1114)
        assert result == "1970-01-01 00:00:00.000000"

    def test_unrecognised_string_passthrough(self):
        # Non-parseable string should pass through unchanged
        result = serialize_value("not a timestamp", 1114)
        assert result == "not a timestamp"

    def test_non_timestamp_oid_int_passthrough(self):
        result = serialize_value(12345, 23)
        assert result == 12345


# ---------------------------------------------------------------------------
# detect_cast_type_oid
# ---------------------------------------------------------------------------


class TestDetectCastTypeOid:
    def test_pg_style_bool_cast(self):
        sql = "SELECT $1::bool AS active"
        assert detect_cast_type_oid(sql, "active") == 16

    def test_pg_style_int_cast(self):
        sql = "SELECT $1::integer AS count"
        assert detect_cast_type_oid(sql, "count") == 23

    def test_pg_style_bigint_cast(self):
        sql = "SELECT $1::bigint AS total"
        assert detect_cast_type_oid(sql, "total") == 20

    def test_pg_style_smallint_cast(self):
        sql = "SELECT $1::smallint AS num"
        assert detect_cast_type_oid(sql, "num") == 21

    def test_pg_style_text_cast(self):
        sql = "SELECT $2::text AS label"
        assert detect_cast_type_oid(sql, "label") == 25

    def test_pg_style_varchar_cast(self):
        sql = "SELECT $1::varchar AS name"
        assert detect_cast_type_oid(sql, "name") == 1043

    def test_pg_style_date_cast(self):
        sql = "SELECT $1::date AS created_at"
        assert detect_cast_type_oid(sql, "created_at") == 1082

    def test_pg_style_timestamp_cast(self):
        sql = "SELECT $1::timestamp AS updated_at"
        assert detect_cast_type_oid(sql, "updated_at") == 1114

    def test_pg_style_float_cast(self):
        sql = "SELECT $1::float AS score"
        assert detect_cast_type_oid(sql, "score") == 701

    def test_pg_style_double_cast(self):
        sql = "SELECT $1::double AS ratio"
        assert detect_cast_type_oid(sql, "ratio") == 701

    def test_sql_cast_bit(self):
        sql = "SELECT CAST(? AS BIT) AS flag"
        assert detect_cast_type_oid(sql, "flag") == 16

    def test_sql_cast_boolean(self):
        sql = "SELECT CAST(? AS BOOLEAN) AS enabled"
        assert detect_cast_type_oid(sql, "enabled") == 16

    def test_sql_cast_int(self):
        sql = "SELECT CAST(? AS INT) AS count"
        assert detect_cast_type_oid(sql, "count") == 23

    def test_sql_cast_bigint(self):
        sql = "SELECT CAST(? AS BIGINT) AS id"
        assert detect_cast_type_oid(sql, "id") == 20

    def test_no_matching_cast_returns_none(self):
        sql = "SELECT col FROM tbl WHERE x = 1"
        assert detect_cast_type_oid(sql, "col") is None

    def test_wrong_column_name_returns_none(self):
        sql = "SELECT $1::bool AS active"
        assert detect_cast_type_oid(sql, "inactive") is None

    def test_unknown_cast_type_returns_none(self):
        sql = "SELECT $1::jsonb AS data"
        assert detect_cast_type_oid(sql, "data") is None

    def test_case_insensitive_sql(self):
        # Column comparison is case-insensitive (sql_upper used internally)
        sql = "select $1::bool as active"
        assert detect_cast_type_oid(sql, "active") == 16

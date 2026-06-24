"""Unit tests for iris_pgwire._result_processing module.

Tests all branches of:
- serialize_value: None, TIMESTAMP (int POSIXTIME, int legacy, datetime, str digit, str formats),
  DATE (int passthrough), and passthrough
- convert_rows_dates_and_timestamps: empty input, POSIXTIME reclassification, DATE ISO strings,
  Horolog int dates, failed conversion, multi-row column OID update
- override_iris_type_oid: NUMERIC→FLOAT8, NUMERIC→INT4, NUMERIC kept, CURRENT_TIMESTAMP override
"""

from __future__ import annotations

import datetime as dt
from unittest.mock import MagicMock, patch

import pytest

from iris_pgwire._result_processing import (
    POSIXTIME_OFFSET,
    POSIXTIME_MAX,
    convert_rows_dates_and_timestamps,
    override_iris_type_oid,
    serialize_value,
)


# ---------------------------------------------------------------------------
# serialize_value
# ---------------------------------------------------------------------------


class TestSerializeValueNone:
    def test_none_returns_none(self):
        assert serialize_value(None, 1114) is None

    def test_none_date_oid_returns_none(self):
        assert serialize_value(None, 1082) is None

    def test_none_other_oid_returns_none(self):
        assert serialize_value(None, 25) is None


class TestSerializeValueTimestampInt:
    """OID 1114 + integer input."""

    def test_posixtime_int_converts(self):
        # POSIXTIME_OFFSET + 0 => 1970-01-01 00:00:00.000000
        result = serialize_value(POSIXTIME_OFFSET, 1114)
        assert result == "1970-01-01 00:00:00.000000"

    def test_posixtime_int_one_second(self):
        # +1_000_000 microseconds = +1 second
        val = POSIXTIME_OFFSET + 1_000_000
        result = serialize_value(val, 1114)
        assert result == "1970-01-01 00:00:01.000000"

    def test_posixtime_int_with_microseconds(self):
        val = POSIXTIME_OFFSET + 1_000_001
        result = serialize_value(val, 1114)
        assert result == "1970-01-01 00:00:01.000001"

    def test_legacy_pg_int_microseconds_from_2000(self):
        # Value below POSIXTIME_OFFSET: microseconds since 2000-01-01
        val = 1_000_000  # 1 second after 2000-01-01
        result = serialize_value(val, 1114)
        assert result == "2000-01-01 00:00:01.000000"

    def test_legacy_pg_int_zero(self):
        result = serialize_value(0, 1114)
        assert result == "2000-01-01 00:00:00.000000"

    def test_int_overflow_returns_original(self):
        # Force exception path by passing an int that causes timedelta to overflow
        # Use a very large value that will overflow timedelta
        import sys
        huge = sys.maxsize
        # Should return the original value (exception caught)
        result = serialize_value(huge, 1114)
        # May return the original value
        assert result == huge or isinstance(result, str)


class TestSerializeValueTimestampDatetime:
    """OID 1114 + datetime.datetime input."""

    def test_datetime_formats_correctly(self):
        ts = dt.datetime(2023, 6, 15, 12, 30, 45, 123456)
        result = serialize_value(ts, 1114)
        assert result == "2023-06-15 12:30:45.123456"

    def test_datetime_midnight(self):
        ts = dt.datetime(2000, 1, 1, 0, 0, 0, 0)
        result = serialize_value(ts, 1114)
        assert result == "2000-01-01 00:00:00.000000"


class TestSerializeValueTimestampString:
    """OID 1114 + string input."""

    def test_digit_string_posixtime(self):
        val = str(POSIXTIME_OFFSET + 2_000_000)  # +2 seconds
        result = serialize_value(val, 1114)
        assert result == "1970-01-01 00:00:02.000000"

    def test_digit_string_with_whitespace(self):
        val = "  " + str(POSIXTIME_OFFSET) + "  "
        result = serialize_value(val, 1114)
        assert result == "1970-01-01 00:00:00.000000"

    def test_preformatted_with_microseconds(self):
        result = serialize_value("2023-06-15 12:30:45.123456", 1114)
        assert result == "2023-06-15 12:30:45.123456"

    def test_preformatted_without_microseconds(self):
        result = serialize_value("2023-06-15 12:30:45", 1114)
        assert result == "2023-06-15 12:30:45.000000"

    def test_preformatted_iso_with_t_and_microseconds(self):
        result = serialize_value("2023-06-15T12:30:45.123456", 1114)
        assert result == "2023-06-15 12:30:45.123456"

    def test_preformatted_iso_with_t_no_microseconds(self):
        result = serialize_value("2023-06-15T12:30:45", 1114)
        assert result == "2023-06-15 12:30:45.000000"

    def test_string_with_trailing_z(self):
        result = serialize_value("2023-06-15T12:30:45Z", 1114)
        assert result == "2023-06-15 12:30:45.000000"

    def test_unrecognized_string_passthrough(self):
        result = serialize_value("not-a-timestamp", 1114)
        assert result == "not-a-timestamp"


class TestSerializeValueDateOid:
    """OID 1082 = DATE."""

    def test_int_date_passthrough(self):
        # Integer DATE values are handled elsewhere; just pass through
        result = serialize_value(42, 1082)
        assert result == 42

    def test_string_date_not_handled_by_serialize(self):
        # serialize_value only handles int for OID 1082; strings pass through
        result = serialize_value("2023-01-01", 1082)
        assert result == "2023-01-01"


class TestSerializeValuePassthrough:
    """Non-timestamp/date OIDs pass through unchanged."""

    def test_string_passthrough(self):
        assert serialize_value("hello", 25) == "hello"

    def test_int_passthrough_unknown_oid(self):
        assert serialize_value(99, 23) == 99

    def test_float_passthrough(self):
        assert serialize_value(3.14, 701) == 3.14

    def test_list_passthrough(self):
        v = [1, 2, 3]
        assert serialize_value(v, 1007) is v


# ---------------------------------------------------------------------------
# convert_rows_dates_and_timestamps
# ---------------------------------------------------------------------------


class TestConvertRowsDatesAndTimestampsEdgeCases:
    def test_empty_rows(self):
        rows = []
        columns = [{"type_oid": 1114, "name": "ts"}]
        # Should return without error
        convert_rows_dates_and_timestamps(rows, columns)
        assert rows == []

    def test_empty_columns(self):
        rows = [[1, 2]]
        columns = []
        convert_rows_dates_and_timestamps(rows, columns)
        assert rows == [[1, 2]]  # unchanged

    def test_col_idx_beyond_column_count(self):
        # Row has more values than columns — should skip gracefully
        rows = [[1, 2, 3]]
        columns = [{"type_oid": 25, "name": "a"}]
        convert_rows_dates_and_timestamps(rows, columns)
        # col 0 passes through (OID 25), cols 1 and 2 skipped
        assert rows[0][1] == 2
        assert rows[0][2] == 3


class TestConvertRowsTimestamp:
    def test_posixtime_int_reclassified_and_converted(self):
        val = POSIXTIME_OFFSET  # epoch
        rows = [[val]]
        columns = [{"type_oid": 23, "name": "ts"}]
        convert_rows_dates_and_timestamps(rows, columns)
        assert rows[0][0] == "1970-01-01 00:00:00.000000"
        assert columns[0]["type_oid"] == 1114

    def test_posixtime_on_int8_oid(self):
        val = POSIXTIME_OFFSET + 5_000_000
        rows = [[val]]
        columns = [{"type_oid": 20, "name": "ts"}]
        convert_rows_dates_and_timestamps(rows, columns)
        assert rows[0][0] == "1970-01-01 00:00:05.000000"
        assert columns[0]["type_oid"] == 1114

    def test_posixtime_column_oid_only_updated_on_row0(self):
        # Row 0 triggers OID update; row 1 uses the already-updated OID
        val = POSIXTIME_OFFSET + 1_000_000
        rows = [[val], [val]]
        columns = [{"type_oid": 23, "name": "ts"}]
        convert_rows_dates_and_timestamps(rows, columns)
        assert columns[0]["type_oid"] == 1114
        assert rows[0][0] == "1970-01-01 00:00:01.000000"
        assert rows[1][0] == "1970-01-01 00:00:01.000000"

    def test_non_posixtime_int4_not_reclassified(self):
        # A regular integer (not in POSIXTIME range)
        val = 42
        rows = [[val]]
        columns = [{"type_oid": 23, "name": "n"}]
        convert_rows_dates_and_timestamps(rows, columns)
        assert rows[0][0] == 42
        assert columns[0]["type_oid"] == 23

    def test_posixtime_max_boundary(self):
        rows = [[POSIXTIME_MAX]]
        columns = [{"type_oid": 23, "name": "ts"}]
        convert_rows_dates_and_timestamps(rows, columns)
        assert isinstance(rows[0][0], str)

    def test_timestamp_oid_datetime_input(self):
        ts = dt.datetime(2023, 1, 1, 0, 0, 0)
        rows = [[ts]]
        columns = [{"type_oid": 1114, "name": "ts"}]
        convert_rows_dates_and_timestamps(rows, columns)
        assert rows[0][0] == "2023-01-01 00:00:00.000000"


class TestConvertRowsDate:
    def test_date_iso_string_to_pg_days(self):
        # 2000-01-02 = day 1 since epoch
        rows = [["2000-01-02"]]
        columns = [{"type_oid": 1082, "name": "d"}]
        convert_rows_dates_and_timestamps(rows, columns)
        assert rows[0][0] == 1

    def test_date_epoch_itself(self):
        rows = [["2000-01-01"]]
        columns = [{"type_oid": 1082, "name": "d"}]
        convert_rows_dates_and_timestamps(rows, columns)
        assert rows[0][0] == 0

    def test_date_before_epoch(self):
        rows = [["1999-12-31"]]
        columns = [{"type_oid": 1082, "name": "d"}]
        convert_rows_dates_and_timestamps(rows, columns)
        assert rows[0][0] == -1

    def test_date_horolog_int(self):
        # horolog_to_pg is the real function from conversions; patch it to isolate
        with patch("iris_pgwire._result_processing.horolog_to_pg", return_value=9999) as mock_h:
            rows = [[12345]]
            columns = [{"type_oid": 1082, "name": "d"}]
            convert_rows_dates_and_timestamps(rows, columns)
            mock_h.assert_called_once_with(12345)
            assert rows[0][0] == 9999

    def test_date_null_value_skipped(self):
        rows = [[None]]
        columns = [{"type_oid": 1082, "name": "d"}]
        convert_rows_dates_and_timestamps(rows, columns)
        assert rows[0][0] is None

    def test_date_invalid_string_kept(self):
        # Invalid date string — exception caught, original value kept
        rows = [["not-a-date"]]
        columns = [{"type_oid": 1082, "name": "d"}]
        convert_rows_dates_and_timestamps(rows, columns)
        assert rows[0][0] == "not-a-date"

    def test_date_horolog_exception_kept(self):
        with patch("iris_pgwire._result_processing.horolog_to_pg", side_effect=ValueError("bad")):
            rows = [[99999]]
            columns = [{"type_oid": 1082, "name": "d"}]
            convert_rows_dates_and_timestamps(rows, columns)
            # Original value kept after exception
            assert rows[0][0] == 99999


class TestConvertRowsMultiColumn:
    def test_multiple_columns_different_types(self):
        ts_val = POSIXTIME_OFFSET + 1_000_000
        date_val = "2000-01-02"
        rows = [["hello", ts_val, date_val]]
        columns = [
            {"type_oid": 25, "name": "s"},
            {"type_oid": 20, "name": "ts"},
            {"type_oid": 1082, "name": "d"},
        ]
        convert_rows_dates_and_timestamps(rows, columns)
        assert rows[0][0] == "hello"
        assert rows[0][1] == "1970-01-01 00:00:01.000000"
        assert rows[0][2] == 1


# ---------------------------------------------------------------------------
# override_iris_type_oid
# ---------------------------------------------------------------------------


class TestOverrideIrisTypeOid:
    """Tests for override_iris_type_oid."""

    # --- iris_type == 2 (NUMERIC) ---

    def test_numeric_no_cast_returns_float8(self):
        result = override_iris_type_oid(2, 1700, "SELECT 3.14")
        assert result == 701

    def test_numeric_with_as_numeric_kept(self):
        result = override_iris_type_oid(2, 1700, "SELECT CAST(x AS NUMERIC)")
        assert result == 1700

    def test_numeric_with_as_decimal_kept(self):
        result = override_iris_type_oid(2, 1700, "SELECT CAST(x AS DECIMAL)")
        assert result == 1700

    def test_numeric_with_as_integer_returns_int4(self):
        result = override_iris_type_oid(2, 1700, "SELECT CAST(x AS INTEGER)")
        assert result == 23

    def test_numeric_with_as_int_returns_int4(self):
        result = override_iris_type_oid(2, 1700, "SELECT CAST(x AS INT)")
        assert result == 23

    def test_numeric_as_integer_takes_priority_over_as_decimal(self):
        # AS INTEGER appears first in the condition, so INT4 wins
        result = override_iris_type_oid(2, 1700, "SELECT CAST(x AS INTEGER) AS DECIMAL")
        assert result == 23

    # --- CURRENT_TIMESTAMP overrides ---

    def test_current_timestamp_text_oid_overridden(self):
        result = override_iris_type_oid(0, 25, "SELECT CURRENT_TIMESTAMP")
        assert result == 1114

    def test_current_timestamp_varchar_oid_overridden(self):
        result = override_iris_type_oid(0, 1043, "SELECT CURRENT_TIMESTAMP")
        assert result == 1114

    def test_current_timestamp_already_timestamp_oid_unchanged(self):
        # OID 1114 is not in (25, 1043) so not overridden
        result = override_iris_type_oid(0, 1114, "SELECT CURRENT_TIMESTAMP")
        assert result == 1114

    def test_current_timestamp_other_oid_unchanged(self):
        result = override_iris_type_oid(0, 23, "SELECT CURRENT_TIMESTAMP")
        assert result == 23

    def test_no_current_timestamp_no_change(self):
        result = override_iris_type_oid(0, 25, "SELECT 'hello'")
        assert result == 25

    # --- Non-special iris types ---

    def test_iris_type_1_passthrough(self):
        result = override_iris_type_oid(1, 23, "SELECT x FROM t")
        assert result == 23

    def test_iris_type_5_passthrough(self):
        result = override_iris_type_oid(5, 701, "SELECT x FROM t")
        assert result == 701

    def test_iris_type_2_original_oid_preserved_when_numeric_explicit(self):
        # AS NUMERIC in SQL → keep original OID (1700)
        result = override_iris_type_oid(2, 1700, "SELECT CAST(3.14 AS NUMERIC) FROM t")
        assert result == 1700

"""
Contract tests for POSIXTIME/TIMESTAMP fix (Feature 040).

These tests are pure unit tests — no IRIS container required.
They must FAIL before the fix is applied, PASS after.

Contract source: specs/040-fix-posixtime-timestamp/contracts/timestamp-fix-contract.md
"""

import datetime as dt
from datetime import timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers — import under test (patching heavy deps so no IRIS needed)
# ---------------------------------------------------------------------------


def _make_executor():
    """Construct a minimal IRISExecutor with all heavy deps mocked."""
    with (
        patch("iris_pgwire.iris_executor.CatalogRouter"),
        patch("iris_pgwire.iris_executor.SQLPipeline"),
        patch("iris_pgwire.iris_executor.TransactionTranslator"),
        patch("iris_pgwire.iris_executor.DdlSplitter"),
        patch("iris_pgwire.iris_executor.SQLInterceptor"),
    ):
        from iris_pgwire.iris_executor import POSIXTIME_OFFSET, IRISExecutor

        cfg = MagicMock()
        cfg.host = "localhost"
        cfg.port = 1972
        cfg.namespace = "USER"
        cfg.username = "SuperUser"
        cfg.password = "SYS"
        cfg.max_connections = 1
        cfg.connection_timeout = 5
        executor = IRISExecutor.__new__(IRISExecutor)
        # Patch heavy attributes so methods under test can run
        executor.ddl_splitter = MagicMock()
        executor.sql_interceptor = MagicMock()
        executor.sql_interceptor.intercept.return_value = MagicMock(intercepted=False)
        executor.catalog_router = MagicMock()
        executor.transaction_translator = MagicMock()
        executor.transaction_translator.translate_transaction_command.side_effect = lambda x: x
        return executor, POSIXTIME_OFFSET


def _make_dbapi_executor():
    """Construct a minimal DBAPIExecutor with all heavy deps mocked."""
    with (
        patch("iris_pgwire.dbapi_executor.CatalogRouter"),
        patch("iris_pgwire.dbapi_executor.SQLPipeline"),
        patch("iris_pgwire.dbapi_executor.IRISConnectionPool"),
    ):
        from iris_pgwire.dbapi_executor import DBAPIExecutor

        executor = DBAPIExecutor.__new__(DBAPIExecutor)
        executor.catalog_router = MagicMock()
        executor.sql_pipeline = MagicMock()
        return executor


# ===========================================================================
# _iris_type_to_pg_oid contracts
# ===========================================================================


class TestOidMapping:
    """Contract: _iris_type_to_pg_oid must map JDBC type codes to correct OIDs."""

    def test_oid_mapping_91_date(self):
        """type_code=91 (standard JDBC DATE) → OID 1082."""
        executor, _ = _make_executor()
        assert executor._iris_type_to_pg_oid(91) == 1082

    def test_oid_mapping_92_time(self):
        """type_code=92 (standard JDBC TIME) → OID 1083."""
        executor, _ = _make_executor()
        assert executor._iris_type_to_pg_oid(92) == 1083

    def test_oid_mapping_93_timestamp(self):
        """type_code=93 (standard JDBC TIMESTAMP) → OID 1114 (THE critical bug)."""
        executor, _ = _make_executor()
        assert executor._iris_type_to_pg_oid(93) == 1114

    def test_oid_mapping_1091_extended_date(self):
        """type_code=1091 (IRIS extended DATE) → OID 1082."""
        executor, _ = _make_executor()
        assert executor._iris_type_to_pg_oid(1091) == 1082

    def test_oid_mapping_1092_extended_time(self):
        """type_code=1092 (IRIS extended TIME) → OID 1083."""
        executor, _ = _make_executor()
        assert executor._iris_type_to_pg_oid(1092) == 1083

    def test_oid_mapping_1093_extended_timestamp(self):
        """type_code=1093 (IRIS extended TIMESTAMP) → OID 1114 (THE critical bug)."""
        executor, _ = _make_executor()
        assert executor._iris_type_to_pg_oid(1093) == 1114

    # Regression: pre-existing mappings must not change
    def test_oid_regression_int4(self):
        executor, _ = _make_executor()
        assert executor._iris_type_to_pg_oid(4) == 23  # INT4

    def test_oid_regression_varchar(self):
        executor, _ = _make_executor()
        assert executor._iris_type_to_pg_oid(12) == 1043  # VARCHAR

    def test_oid_regression_date_9(self):
        executor, _ = _make_executor()
        assert executor._iris_type_to_pg_oid(9) == 1082  # DATE pre-existing

    def test_oid_regression_timestamp_10(self):
        executor, _ = _make_executor()
        assert executor._iris_type_to_pg_oid(10) == 1114  # TIMESTAMP pre-existing

    def test_oid_unknown_defaults_varchar(self):
        executor, _ = _make_executor()
        assert executor._iris_type_to_pg_oid(9999) == 1043  # unknown → VARCHAR


# ===========================================================================
# _serialize_value contracts
# ===========================================================================


class TestSerializeValue:
    """Contract: _serialize_value(value, type_oid=1114) conversion rules."""

    POSIXTIME_OFFSET = 1152921504606846976
    # 2025-01-01 00:00:00 UTC in unix microseconds
    UNIX_US_2025 = 1735689600000000
    # IRIS POSIXTIME for 2025-01-01 00:00:00 UTC
    IRIS_TS_2025 = POSIXTIME_OFFSET + UNIX_US_2025

    def test_none_passthrough(self):
        executor, _ = _make_executor()
        assert executor._serialize_value(None, 1114) is None

    def test_int_posixtime_large(self):
        """POSIXTIME int ≥ POSIXTIME_OFFSET → PostgreSQL text wire format (space separator, no Z)."""
        executor, _ = _make_executor()
        result = executor._serialize_value(self.IRIS_TS_2025, 1114)
        assert isinstance(result, str)
        assert result.startswith("2025-01-01 00:00:00")
        assert "T" not in result
        assert not result.endswith("Z")

    def test_int_pg_epoch_small(self):
        """int < POSIXTIME_OFFSET treated as PG epoch microseconds."""
        executor, _ = _make_executor()
        # 2025-01-01 00:00:00 in PG epoch (microseconds since 2000-01-01)
        pg_us = 789004800000000  # 2025-01-01 00:00:00
        result = executor._serialize_value(pg_us, 1114)
        assert isinstance(result, str)
        assert result.startswith("2025-")

    def test_str_digit_posixtime(self):
        """All-digit string POSIXTIME → subtract POSIXTIME_OFFSET → PostgreSQL text wire format."""
        executor, _ = _make_executor()
        result = executor._serialize_value(str(self.IRIS_TS_2025), 1114)
        assert isinstance(result, str)
        assert result.startswith("2025-01-01 00:00:00")
        assert "T" not in result
        assert not result.endswith("Z")

    def test_str_datetime_plain(self):
        """Plain datetime string '2025-01-01 00:00:00' → PostgreSQL text wire format."""
        executor, _ = _make_executor()
        result = executor._serialize_value("2025-01-01 00:00:00", 1114)
        assert isinstance(result, str)
        assert result.startswith("2025-01-01 ")
        assert "T" not in result
        assert not result.endswith("Z")

    def test_str_iso_reformatted(self):
        """ISO Z string input → reformatted to PostgreSQL text wire format."""
        executor, _ = _make_executor()
        value = "2025-01-01T00:00:00.000000Z"
        result = executor._serialize_value(value, 1114)
        assert isinstance(result, str)
        assert result.startswith("2025-01-01 00:00:00")
        assert "T" not in result
        assert not result.endswith("Z")

    def test_str_unrecognised_passthrough(self):
        """Unrecognised string → pass through, no exception."""
        executor, _ = _make_executor()
        result = executor._serialize_value("not-a-date", 1114)
        assert result == "not-a-date"

    def test_datetime_object(self):
        """datetime.datetime object → PostgreSQL text wire format (space separator, no Z)."""
        executor, _ = _make_executor()
        value = dt.datetime(2025, 1, 1, 0, 0, 0)
        result = executor._serialize_value(value, 1114)
        assert result == "2025-01-01 00:00:00.000000"

    # Regression: non-timestamp OID passes value through
    def test_non_timestamp_oid_passthrough(self):
        executor, _ = _make_executor()
        assert executor._serialize_value(42, 23) == 42


# ===========================================================================
# _normalize_parameters contracts
# ===========================================================================


class TestNormalizeParameters:
    """Contract: _normalize_parameters([...]) → list of IRIS-compatible values."""

    def test_naive_datetime(self):
        """Naive datetime → plain datetime string."""
        executor, _ = _make_executor()
        value = dt.datetime(2025, 6, 15, 12, 30, 45, 123456)
        result = executor._normalize_parameters([value])
        assert result == ["2025-06-15 12:30:45.123456"]

    def test_utc_aware_datetime(self):
        """UTC-aware datetime → stripped to naive UTC."""
        executor, _ = _make_executor()
        value = dt.datetime(2025, 6, 15, 12, 30, 45, 0, tzinfo=dt.UTC)
        result = executor._normalize_parameters([value])
        assert result == ["2025-06-15 12:30:45.000000"]

    def test_offset_aware_datetime_plus8(self):
        """Offset-aware +08:00 → converted to UTC."""
        executor, _ = _make_executor()
        # 2025-01-01 08:00:00+08:00 == 2025-01-01 00:00:00 UTC
        tz_plus8 = timezone(timedelta(hours=8))
        value = dt.datetime(2025, 1, 1, 8, 0, 0, tzinfo=tz_plus8)
        result = executor._normalize_parameters([value])
        assert result == ["2025-01-01 00:00:00.000000"]

    def test_date_object(self):
        """date object → 'YYYY-MM-DD' string."""
        executor, _ = _make_executor()
        value = dt.date(2025, 6, 15)
        result = executor._normalize_parameters([value])
        assert result == ["2025-06-15"]

    def test_iso_string_with_z(self):
        """ISO 8601 string with Z → plain space-separated datetime."""
        executor, _ = _make_executor()
        result = executor._normalize_parameters(["2025-01-01T12:00:00.000000Z"])
        assert result == ["2025-01-01 12:00:00.000000"]

    def test_iso_string_with_nonzero_offset(self):
        """ISO 8601 string with +05:30 → converted to UTC."""
        executor, _ = _make_executor()
        result = executor._normalize_parameters(["2025-01-01T12:00:00+05:30"])
        # 12:00:00+05:30 == 06:30:00 UTC
        assert result == ["2025-01-01 06:30:00"]

    # Regression: pre-existing behaviors must not change
    def test_pg_timestamp_int_conversion(self):
        """PG timestamp int in range → IRIS datetime string (pre-existing)."""
        executor, _ = _make_executor()
        # 504921600000000 us = 2016-01-01 00:00:00 in PG epoch (since 2000-01-01)
        # Must be in range [500_000_000_000_000, 1_500_000_000_000_000]
        result = executor._normalize_parameters([504921600000000])
        assert len(result) == 1
        assert isinstance(result[0], str)
        assert "2016" in result[0]

    def test_vector_list_conversion(self):
        """Python list → IRIS vector string (pre-existing)."""
        executor, _ = _make_executor()
        result = executor._normalize_parameters([[1.0, 2.0, 3.0]])
        assert result == ["[1.0,2.0,3.0]"]


# ===========================================================================
# DBAPIExecutor._convert_value_for_iris parity contracts (C1 from analyze)
# ===========================================================================


class TestDBAPIExecutorParity:
    """
    Parity contract: DBAPIExecutor._convert_value_for_iris must produce the
    same string as IRISExecutor._normalize_parameters for datetime/date inputs.
    """

    def test_dbapi_naive_datetime(self):
        """Naive datetime → same string as iris_executor."""
        dbapi = _make_dbapi_executor()
        value = dt.datetime(2025, 6, 15, 12, 30, 45, 123456)
        result = dbapi._convert_value_for_iris(value)
        assert result == "2025-06-15 12:30:45.123456"

    def test_dbapi_utc_aware_datetime(self):
        """UTC-aware datetime → stripped UTC string."""
        dbapi = _make_dbapi_executor()
        value = dt.datetime(2025, 6, 15, 12, 30, 45, 0, tzinfo=dt.UTC)
        result = dbapi._convert_value_for_iris(value)
        assert result == "2025-06-15 12:30:45.000000"

    def test_dbapi_offset_aware_datetime(self):
        """Offset-aware datetime → UTC-converted string."""
        dbapi = _make_dbapi_executor()
        tz_plus8 = timezone(timedelta(hours=8))
        value = dt.datetime(2025, 1, 1, 8, 0, 0, tzinfo=tz_plus8)
        result = dbapi._convert_value_for_iris(value)
        assert result == "2025-01-01 00:00:00.000000"

    def test_dbapi_date_object(self):
        """date → 'YYYY-MM-DD' string."""
        dbapi = _make_dbapi_executor()
        value = dt.date(2025, 6, 15)
        result = dbapi._convert_value_for_iris(value)
        assert result == "2025-06-15"

    def test_dbapi_parity_with_iris_executor(self):
        """Parity invariant: both executors produce identical output."""
        iris_exec, _ = _make_executor()
        dbapi_exec = _make_dbapi_executor()

        test_values = [
            dt.datetime(2025, 1, 1, 12, 0, 0),
            dt.datetime(2025, 1, 1, 12, 0, 0, tzinfo=dt.UTC),
            dt.datetime(2025, 1, 1, 20, 0, 0, tzinfo=timezone(timedelta(hours=8))),
            dt.date(2025, 6, 15),
        ]

        for v in test_values:
            iris_result = iris_exec._normalize_parameters([v])[0]
            dbapi_result = dbapi_exec._convert_value_for_iris(v)
            assert iris_result == dbapi_result, (
                f"Parity failure for {v!r}: iris={iris_result!r} dbapi={dbapi_result!r}"
            )

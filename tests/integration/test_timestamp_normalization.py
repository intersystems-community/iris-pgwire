import pytest
import psycopg
from datetime import datetime


@pytest.mark.e2e
class TestTimestampNormalizationE2E:
    def test_insert_iso8601_timestamp_with_tz(self, pgwire_client):
        """FR-004: ISO 8601 timestamps with T/Z"""
        with pgwire_client.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS test_ts")
            cursor.execute("CREATE TABLE test_ts (id INT, ts TIMESTAMP)")

            # String literal with T and Z
            ts_str = "2024-01-16T12:34:56Z"
            cursor.execute(f"INSERT INTO test_ts (id, ts) VALUES (1, '{ts_str}')")

            cursor.execute("SELECT ts FROM test_ts WHERE id = 1")
            result = cursor.fetchone()[0]
            # IRIS might return it in ODBC format
            assert "2024-01-16 12:34:56" in str(result)

    def test_bind_timestamp_with_offset(self, pgwire_client):
        """FR-004: Bound timestamp with offset"""
        with pgwire_client.cursor() as cursor:
            cursor.execute("DROP TABLE IF EXISTS test_ts_bind")
            cursor.execute("CREATE TABLE test_ts_bind (id INT, ts TIMESTAMP)")

            # Psycopg might send it as binary or string; we want to test our normalization
            ts_val = "2024-01-16 12:34:56+05:00"
            cursor.execute("INSERT INTO test_ts_bind (id, ts) VALUES (1, %s)", (ts_val,))

            cursor.execute("SELECT ts FROM test_ts_bind WHERE id = 1")
            result = cursor.fetchone()[0]
            assert "2024-01-16 12:34:56" in str(result)

import datetime
import os
from datetime import timedelta, timezone

import psycopg
import pytest


def test_returning_type_mapping_uuid_repro(pgwire_client, iris_connection):
    """
    Reproduces Issue: VARCHAR column containing digits or UUIDs incorrectly mapped to INT4.
    """
    with iris_connection.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS test_type_map")
        cur.execute("CREATE TABLE test_type_map (id VARCHAR(255) PRIMARY KEY, name TEXT)")
        iris_connection.commit()

    try:
        with pgwire_client.cursor() as cur:
            # 1. Test with UUID-like string
            uuid_val = "550e8400-e29b-41d4-a716-446655440000"
            cur.execute(
                "INSERT INTO test_type_map (id, name) VALUES (%s, 'UUID Test') RETURNING id",
                (uuid_val,),
            )
            row = cur.fetchone()
            assert row is not None
            # If it's mapped to INT4, psycopg might try to parse it and fail or return something weird
            # The report says it returns NaN in JS. In Python/psycopg, it might raise DataError or return string if it falls back.
            assert isinstance(row[0], str)
            assert row[0] == uuid_val

            # 2. Test with numeric-only string
            numeric_id = "12345"
            cur.execute(
                "INSERT INTO test_type_map (id, name) VALUES (%s, 'Numeric Test') RETURNING id",
                (numeric_id,),
            )
            row = cur.fetchone()
            assert row is not None
            # This is where the bug is most likely: it returns int 12345 instead of str "12345"
            # because _infer_type_from_value sees the integer value.
            assert isinstance(row[0], str), f"Expected string, got {type(row[0])}"
            assert row[0] == numeric_id

    finally:
        with iris_connection.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS test_type_map")
            iris_connection.commit()


def test_returning_timestamp_posixtime_repro(pgwire_client, iris_connection):
    """
    Validates:
    1. IRIS POSIXTIME (large BIGINT) is correctly detected as TIMESTAMP (1114).
    2. TIMESTAMP serialization converts POSIXTIME to ISO8601 with Z.
    3. Multiple columns in RETURNING preserve their names.
    """
    with iris_connection.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS test_ts_map")
        cur.execute(
            "CREATE TABLE test_ts_map (id INT PRIMARY KEY, ts_val TIMESTAMP, name VARCHAR(255))"
        )
        iris_connection.commit()

    try:
        # Use a known IRIS POSIXTIME value
        # POSIXTIME_OFFSET = 1152921504606846976 (1970-01-01)
        # 2025-01-01 00:00:00 UTC in unix us = 1735689600000000
        # IRIS POSIXTIME = POSIXTIME_OFFSET + 1735689600000000
        posixtime_offset = 1152921504606846976
        unix_us = 1735689600000000
        iris_posixtime = posixtime_offset + unix_us

        with pgwire_client.cursor() as cur:
            # 1. Test RETURNING with multiple columns including TIMESTAMP
            cur.execute(
                "INSERT INTO test_ts_map (id, ts_val, name) VALUES (1, '2025-01-01 00:00:00', 'TS Test') RETURNING ts_val, name, id"
            )
            row = cur.fetchone()
            assert row is not None
            # Verify names are preserved
            names = [desc[0] for desc in cur.description]
            assert names == ["ts_val", "name", "id"]

            # Verify TIMESTAMP value is returned as datetime (psycopg handles ISO8601)
            import datetime

            assert isinstance(row[0], datetime.datetime)
            assert row[0].year == 2025

            # 2. Test direct query of POSIXTIME-like large integer
            # This tests _infer_type_from_value
            cur.execute(f"SELECT {iris_posixtime} AS ts_col")
            row = cur.fetchone()
            # If detected as TIMESTAMP, it should be a datetime (via ISO8601 string from PGWire)
            assert isinstance(row[0], datetime.datetime)
            assert row[0].year == 2025

    finally:
        with iris_connection.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS test_ts_map")
            iris_connection.commit()


def test_datetime_bind_param_insert(pgwire_client, iris_connection):
    """
    T010-a: Insert using a native datetime.datetime as a bind parameter.
    IRIS must accept it (no rejection) and the stored value must be readable
    back as a datetime.datetime object.
    """
    with iris_connection.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS test_dt_bind")
        cur.execute("CREATE TABLE test_dt_bind (id INT PRIMARY KEY, ts_val TIMESTAMP)")
        iris_connection.commit()

    try:
        naive_dt = datetime.datetime(2025, 1, 1, 12, 30, 45)
        with pgwire_client.cursor() as cur:
            cur.execute(
                "INSERT INTO test_dt_bind (id, ts_val) VALUES (%s, %s) RETURNING ts_val",
                (1, naive_dt),
            )
            row = cur.fetchone()
            assert row is not None
            assert isinstance(row[0], datetime.datetime)
            assert row[0].year == 2025
            assert row[0].month == 1
            assert row[0].day == 1
    finally:
        with iris_connection.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS test_dt_bind")
            iris_connection.commit()


def test_aware_datetime_bind_param(pgwire_client, iris_connection):
    """
    T010-b: Insert using a timezone-aware datetime (+08:00).
    IRIS must store the UTC equivalent: 2025-01-01 00:00:00.
    """
    with iris_connection.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS test_dt_aware")
        cur.execute("CREATE TABLE test_dt_aware (id INT PRIMARY KEY, ts_val TIMESTAMP)")
        iris_connection.commit()

    try:
        # 2025-01-01 08:00:00+08:00 == 2025-01-01 00:00:00 UTC
        tz_plus8 = timezone(timedelta(hours=8))
        aware_dt = datetime.datetime(2025, 1, 1, 8, 0, 0, tzinfo=tz_plus8)

        with pgwire_client.cursor() as cur:
            cur.execute(
                "INSERT INTO test_dt_aware (id, ts_val) VALUES (%s, %s) RETURNING ts_val",
                (1, aware_dt),
            )
            row = cur.fetchone()
            assert row is not None
            assert isinstance(row[0], datetime.datetime)
            # Should be stored as UTC: 2025-01-01 00:00:00
            assert row[0].year == 2025
            assert row[0].month == 1
            assert row[0].day == 1
            assert row[0].hour == 0
    finally:
        with iris_connection.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS test_dt_aware")
            iris_connection.commit()


def test_date_bind_param(pgwire_client, iris_connection):
    """
    T010-c: Insert using a native datetime.date into a DATE column.
    IRIS must accept it and return it as a datetime.date.
    """
    with iris_connection.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS test_date_bind")
        cur.execute("CREATE TABLE test_date_bind (id INT PRIMARY KEY, d_val DATE)")
        iris_connection.commit()

    try:
        date_val = datetime.date(2025, 6, 15)
        with pgwire_client.cursor() as cur:
            cur.execute(
                "INSERT INTO test_date_bind (id, d_val) VALUES (%s, %s) RETURNING d_val",
                (1, date_val),
            )
            row = cur.fetchone()
            assert row is not None
            assert isinstance(row[0], datetime.date)
            assert row[0].year == 2025
            assert row[0].month == 6
            assert row[0].day == 15
    finally:
        with iris_connection.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS test_date_bind")
            iris_connection.commit()

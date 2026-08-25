"""Integration tests for psycopg3 pipeline mode + executemany support.

Feature 049: per-row duplicate suppression when ON CONFLICT DO NOTHING is used.

These tests require a live IRIS container and psycopg3. They are skipped
automatically when IRIS is not available (no IRIS_HOST env var or psycopg3
not installed).

To run manually:
    IRIS_HOST=localhost IRIS_PORT=5432 pytest tests/integration/test_psycopg3_pipeline.py -v
"""

from __future__ import annotations

import os

import pytest

# Skip the entire module if no IRIS endpoint configured
IRIS_HOST = os.environ.get("IRIS_HOST", "")
IRIS_PORT = int(os.environ.get("IRIS_PORT", "5432"))
IRIS_USER = os.environ.get("IRIS_USER", "_SYSTEM")
IRIS_PASS = os.environ.get("IRIS_PASS", "SYS")
IRIS_DB = os.environ.get("IRIS_DB", "user")

pytestmark = pytest.mark.skipif(
    not IRIS_HOST,
    reason="IRIS_HOST not set — skipping psycopg3 pipeline integration tests",
)


@pytest.fixture
def pg_conn():
    """psycopg3 connection to iris-pgwire server."""
    psycopg = pytest.importorskip("psycopg")
    connstr = f"host={IRIS_HOST} port={IRIS_PORT} user={IRIS_USER} password={IRIS_PASS} dbname={IRIS_DB}"
    conn = psycopg.connect(connstr, autocommit=True)
    yield conn
    conn.close()


def test_executemany_on_conflict_do_nothing(pg_conn):
    """Batch with ON CONFLICT DO NOTHING must not raise; duplicates silently skipped."""
    with pg_conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS t_049_oc")
        cur.execute("CREATE TABLE t_049_oc (id INT PRIMARY KEY, v VARCHAR(64))")
        # 2 unique rows + 1 duplicate
        cur.executemany(
            "INSERT INTO t_049_oc VALUES (%s, %s) ON CONFLICT DO NOTHING",
            [(1, "a"), (1, "dup"), (2, "b")],
        )
        cur.execute("SELECT COUNT(*) FROM t_049_oc")
        count = cur.fetchone()[0]
        cur.execute("DROP TABLE t_049_oc")
    assert count == 2, f"Expected 2 rows, got {count}"


def test_executemany_row_count(pg_conn):
    """Row count in result must equal number of successfully inserted rows."""
    with pg_conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS t_049_rc")
        cur.execute("CREATE TABLE t_049_rc (id INT PRIMARY KEY)")
        cur.executemany(
            "INSERT INTO t_049_rc VALUES (%s)",
            [(i,) for i in range(100)],
        )
        cur.execute("SELECT COUNT(*) FROM t_049_rc")
        count = cur.fetchone()[0]
        cur.execute("DROP TABLE t_049_rc")
    assert count == 100, f"Expected 100 rows, got {count}"


def test_pipeline_sync_does_not_hang(pg_conn):
    """psycopg3 pipeline mode must complete without hanging."""
    psycopg = pytest.importorskip("psycopg")
    with pg_conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS t_049_pl")
        cur.execute("CREATE TABLE t_049_pl (id INT PRIMARY KEY)")

    with pg_conn.pipeline():
        with pg_conn.cursor() as cur:
            for i in range(3):
                cur.execute("INSERT INTO t_049_pl VALUES (%s)", (i,))

    with pg_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM t_049_pl")
        count = cur.fetchone()[0]
        cur.execute("DROP TABLE t_049_pl")

    assert count == 3, f"Expected 3 rows after pipeline sync, got {count}"

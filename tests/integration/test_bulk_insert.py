"""
Integration benchmark tests for fast bulk insert path.
"""

import random
import time

import psycopg
import pytest

from iris_pgwire.conversions.bulk_insert import BulkInsertJob

# Connection configuration (matches conftest.py defaults)
PGWIRE_CONN = "host=localhost port=5432 user=test_user password=test dbname=USER"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_bulk_insert_performance_simple(pgwire_client):
    """Benchmark test for bulk insert performance using standard executemany."""
    row_count = 5000

    # Pre-setup: Ensure table exists
    with pgwire_client.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS test_bulk")
        cur.execute("CREATE TABLE test_bulk (content TEXT, embedding VECTOR(128))")
        pgwire_client.commit()

    rows = [(f"content_{i}", [0.1] * 128) for i in range(row_count)]

    start_time = time.perf_counter()

    # Standard executemany() call.
    # With our protocol batching and executor optimizations, this should be fast.
    with pgwire_client.cursor() as cur:
        cur.executemany("INSERT INTO test_bulk (content, embedding) VALUES (%s, %s)", rows)
        pgwire_client.commit()

    duration = time.perf_counter() - start_time
    rows_per_sec = row_count / duration
    print(
        f"\n🚀 BATCHED EXECUTEMANY PERFORMANCE: {rows_per_sec:.2f} rows/sec ({row_count} rows in {duration:.2f}s)"
    )

    # Verify rows were inserted
    with pgwire_client.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM test_bulk")
        count = cur.fetchone()[0]
        assert int(count) == row_count

    assert rows_per_sec > 100


@pytest.mark.integration
@pytest.mark.benchmark
def test_bulk_insert_performance(benchmark, pgwire_client):
    """
    Benchmark bulk insert performance.
    Target: 10,000 rows in <= 30 seconds (>= 333 rows/sec)
    """
    # Generate 1000 rows for benchmark
    row_count = 1000
    rows = [(f"content_{i}", [random.random() for _ in range(128)]) for i in range(row_count)]

    def do_insert():
        with pgwire_client.cursor() as cur:
            cur.executemany("INSERT INTO test_bulk (content, embedding) VALUES (%s, %s)", rows)
            pgwire_client.commit()

    # Pre-setup: Ensure table exists
    with pgwire_client.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS test_bulk")
        cur.execute("CREATE TABLE test_bulk (content TEXT, embedding VECTOR(128))")
        pgwire_client.commit()

    # Run benchmark
    benchmark.pedantic(do_insert, iterations=1, rounds=5)

    # Verify rows were inserted
    with pgwire_client.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM test_bulk")
        count = cur.fetchone()[0]
        assert int(count) >= row_count


@pytest.mark.unit
def test_bulk_insert_job_tracking():
    """Test BulkInsertJob state tracking logic."""
    job = BulkInsertJob(table_name="test_table", total_rows=100)
    assert job.status == "pending"

    job.mark_started()
    assert job.status == "running"
    assert job.started_at is not None

    job.mark_completed(rows_inserted=100)
    assert job.status == "completed"
    assert job.inserted_rows == 100
    assert job.completed_at is not None
    assert job.rows_per_second() >= 0

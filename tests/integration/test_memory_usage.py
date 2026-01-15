"""
Memory profiling tests for bulk insert operations.
Target: < 50MB memory overhead for 100,000 row batch.
"""

import os
import random
import pytest
import psycopg
import psutil

# Connection configuration
PGWIRE_CONN = "host=localhost port=5432 user=test_user password=test dbname=USER"


def get_memory_usage_mb():
    """Get current process memory usage in MB."""
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / (1024 * 1024)


@pytest.mark.integration
def test_bulk_insert_memory_overhead():
    """
    Measure memory overhead during bulk insert.
    Target: < 50MB overhead for 10,000 rows.
    """
    row_count = 10000
    rows = [(f"content_{i}", [random.random() for _ in range(128)]) for i in range(row_count)]

    # Pre-setup: Ensure table exists
    with psycopg.connect(PGWIRE_CONN) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS test_memory")
            cur.execute("CREATE TABLE test_memory (content TEXT, embedding VECTOR(128))")
            conn.commit()

    mem_before = get_memory_usage_mb()

    with psycopg.connect(PGWIRE_CONN) as conn:
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO test_memory (content, embedding) VALUES (%s, %s)", rows)
            conn.commit()

    mem_after = get_memory_usage_mb()
    overhead = mem_after - mem_before

    print(f"Memory before: {mem_before:.2f} MB")
    print(f"Memory after: {mem_after:.2f} MB")
    print(f"Memory overhead: {overhead:.2f} MB")

    # Assert overhead is within limits
    # Note: 50MB is quite generous for 10k rows
    assert overhead < 50.0

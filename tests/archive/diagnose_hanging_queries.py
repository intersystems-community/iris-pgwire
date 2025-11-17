#!/usr/bin/env python3
"""
Identify which specific queries are hanging in PGWire.
Uses signal timeout to prevent infinite hangs.
"""

import signal
import sys
from contextlib import contextmanager

import psycopg


class TimeoutError(Exception):
    pass


@contextmanager
def timeout(seconds):
    """Context manager for timeout"""

    def timeout_handler(signum, frame):
        raise TimeoutError(f"Query timed out after {seconds}s")

    # Set the signal handler
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)  # Disable alarm


# Connect to PGWire
try:
    conn = psycopg.connect(host="localhost", port=5434, dbname="USER", connect_timeout=10)
    conn.autocommit = True
    cursor = conn.cursor()
    print("✅ Connected to PGWire\n")
except Exception as e:
    print(f"❌ Connection failed: {e}")
    sys.exit(1)

# Test vector (1024 dimensions)
test_vector = "[" + ",".join(["0.1"] * 1024) + "]"

# All query templates
test_queries = {
    # Simple queries
    "simple_select_all": "SELECT * FROM benchmark_vectors LIMIT 10",
    "simple_select_id": "SELECT * FROM benchmark_vectors WHERE id = 1",
    "simple_count": "SELECT COUNT(*) FROM benchmark_vectors",
    # Vector similarity queries (pgvector operators)
    "vector_cosine": f"SELECT id, embedding <=> '{test_vector}' AS distance FROM benchmark_vectors ORDER BY distance LIMIT 5",
    "vector_l2": f"SELECT id, embedding <-> '{test_vector}' AS distance FROM benchmark_vectors ORDER BY distance LIMIT 5",
    "vector_inner_product": f"SELECT id, (embedding <#> '{test_vector}') * -1 AS similarity FROM benchmark_vectors ORDER BY similarity DESC LIMIT 5",
    # Complex join queries
    "join_with_metadata": """
        SELECT v.id, v.embedding, m.label, m.created_at
        FROM benchmark_vectors v
        JOIN benchmark_metadata m ON v.id = m.vector_id
        WHERE m.label = 'vector_0'
        LIMIT 10
    """,
    "vector_similarity_with_filter": f"""
        SELECT v.id, v.embedding <=> '{test_vector}' AS distance, m.label
        FROM benchmark_vectors v
        JOIN benchmark_metadata m ON v.id = m.vector_id
        WHERE m.category = 'category_0'
        ORDER BY distance
        LIMIT 5
    """,
}

print(f"{'='*70}")
print("Testing Queries with 10s Timeout")
print(f"{'='*70}\n")

successes = []
timeouts = []
errors = []

for query_id, sql in test_queries.items():
    try:
        with timeout(10):  # 10 second timeout
            cursor.execute(sql)
            result = cursor.fetchall()
            successes.append(query_id)
            print(f"✅ {query_id:35s} - {len(result)} rows")
    except TimeoutError as e:
        timeouts.append((query_id, str(e)))
        print(f"⏱️  {query_id:35s} - TIMEOUT")
    except Exception as e:
        errors.append((query_id, str(e)))
        print(f"❌ {query_id:35s} - ERROR: {e}")

cursor.close()
conn.close()

print(f"\n{'='*70}")
print(f"Summary: {len(successes)} passed, {len(timeouts)} timed out, {len(errors)} errored")
print(f"{'='*70}\n")

if timeouts:
    print("⏱️  Timed out queries:")
    for query_id, error in timeouts:
        print(f"  - {query_id}")

if errors:
    print("\n❌ Failed queries:")
    for query_id, error in errors:
        print(f"  - {query_id}: {error}")

sys.exit(1 if (timeouts or errors) else 0)

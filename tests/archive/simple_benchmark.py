#!/usr/bin/env python3
"""
ULTRA-SIMPLE 3-way benchmark - no complexity, just raw timing.
"""
import time

import psycopg

# Test data already exists from previous setup
# PostgreSQL on 5433, PGWire on 5434, IRIS DBAPI on 1974


def time_query(name, connect_func, query, iterations=5):
    """Time a query with simple averaging."""
    times = []

    for i in range(iterations):
        conn = connect_func()
        cursor = conn.cursor()

        start = time.perf_counter()
        cursor.execute(query)
        result = cursor.fetchall()
        elapsed = (time.perf_counter() - start) * 1000  # ms

        times.append(elapsed)
        cursor.close()
        conn.close()

    avg = sum(times) / len(times)
    print(f"{name:20s} {avg:8.2f}ms  (min: {min(times):.2f}ms, max: {max(times):.2f}ms)")
    return avg


# Test vector for similarity queries (128D)
# IRIS format: comma-separated WITHOUT brackets
TEST_VECTOR = ",".join(["0.1"] * 128)

# Test queries
QUERIES = [
    ("COUNT(*)", "SELECT COUNT(*) FROM benchmark_vectors"),
    ("SELECT by ID", "SELECT * FROM benchmark_vectors WHERE id = 5"),
    ("SELECT 10 rows", "SELECT * FROM benchmark_vectors LIMIT 10"),
]

# Vector similarity queries (database-specific)
# NOTE: PGWire vector queries HANG (timeout after 30+ seconds)
# Works fine through IRIS DBAPI but not through PGWire protocol
VECTOR_QUERIES = {
    "PostgreSQL": f"SELECT id, embedding <=> '[{TEST_VECTOR}]' AS distance FROM benchmark_vectors ORDER BY distance LIMIT 5",
    "PGWire": f"SELECT id, VECTOR_COSINE(embedding, TO_VECTOR('{TEST_VECTOR}', FLOAT)) AS distance FROM benchmark_vectors ORDER BY distance LIMIT 5",
    "DBAPI": f"SELECT TOP 5 id, VECTOR_COSINE(embedding, TO_VECTOR('{TEST_VECTOR}', FLOAT)) AS distance FROM benchmark_vectors ORDER BY distance",
}

print("=" * 70)
print("SIMPLE 3-WAY BENCHMARK - 128D vectors, 100 rows, 5 iterations")
print("=" * 70)
print("Vector performance with connection pooling optimizations")
print("=" * 70)

for query_name, query in QUERIES:
    print(f"\n{query_name}:")

    # PostgreSQL
    time_query(
        "PostgreSQL",
        lambda: psycopg.connect(
            host="localhost", port=5433, dbname="benchmark", user="postgres", password="postgres"
        ),
        query,
    )

    # PGWire
    time_query(
        "IRIS + PGWire", lambda: psycopg.connect(host="localhost", port=5434, dbname="USER"), query
    )

    # IRIS DBAPI
    try:
        import iris

        def dbapi_conn():
            return iris.connect(
                hostname="localhost",
                port=1972,
                namespace="USER",
                username="_SYSTEM",
                password="SYS",
            )

        time_query("IRIS + DBAPI", dbapi_conn, query)
    except ImportError:
        print("IRIS + DBAPI        SKIPPED (no iris module)")

# Vector similarity queries
print("\n" + "=" * 70)
print("VECTOR SIMILARITY QUERIES")
print("=" * 70)

print("\nVector Cosine Similarity (k=5):")

# PostgreSQL with pgvector
time_query(
    "PostgreSQL",
    lambda: psycopg.connect(
        host="localhost", port=5433, dbname="benchmark", user="postgres", password="postgres"
    ),
    VECTOR_QUERIES["PostgreSQL"],
)

# PGWire
time_query(
    "IRIS + PGWire",
    lambda: psycopg.connect(host="localhost", port=5434, dbname="USER"),
    VECTOR_QUERIES["PGWire"],
)

# IRIS DBAPI
try:
    import iris

    def dbapi_conn():
        return iris.connect(
            hostname="localhost", port=1972, namespace="USER", username="_SYSTEM", password="SYS"
        )

    time_query("IRIS + DBAPI", dbapi_conn, VECTOR_QUERIES["DBAPI"])
except ImportError:
    print("IRIS + DBAPI        SKIPPED (no iris module)")

print("\n" + "=" * 70)
print("DONE")
print("=" * 70)

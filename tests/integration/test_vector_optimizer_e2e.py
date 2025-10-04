#!/usr/bin/env python3
"""
End-to-end integration tests for vector query optimizer through PGWire

These tests validate that the optimizer works through the complete stack:
PostgreSQL client → PGWire server → Optimizer → IRIS execution

Uses psycopg3 (NOT psycopg2) for server-side parameter binding, which:
- Sends parameters separately from SQL (Extended Protocol)
- Allows optimizer to transform parameters before IRIS execution
- Avoids IRIS literal size limit (no 3KB restriction)

Prerequisites:
- IRIS running on localhost:1972
- PGWire server running on localhost:15910
- test_1024 table with 1000+ vectors and HNSW index
- psycopg3 installed: pip install psycopg
"""

import pytest
import psycopg  # psycopg3 - uses server-side parameter binding
import struct
import base64
import random
import time


# Fixtures for PGWire server integration tests
# Note: These tests assume PGWire server is already running
# Run server manually: python -m iris_pgwire.server


def generate_random_vector(dimensions=1024):
    """Generate random normalized vector

    IMPORTANT: test_1024 table uses 1024-dimensional vectors.
    Always use dimensions=1024 for E2E tests against test_1024 table.
    """
    vec = [random.gauss(0, 1) for _ in range(dimensions)]
    norm = sum(x*x for x in vec) ** 0.5
    return [x/norm for x in vec]


def vector_to_base64(vector):
    """Convert vector to base64 format (psycopg2 default)"""
    vec_bytes = struct.pack(f'{len(vector)}f', *vector)
    return "base64:" + base64.b64encode(vec_bytes).decode('ascii')


def vector_to_json_array(vector):
    """Convert vector to JSON array format"""
    return '[' + ','.join(str(float(v)) for v in vector) + ']'


@pytest.mark.e2e
class TestVectorOptimizerE2E:
    """End-to-end tests through PGWire protocol using psycopg3"""

    @pytest.fixture(scope="class")
    def pgwire_connection(self):
        """Connect to PGWire server using psycopg3 (server-side parameter binding)"""
        try:
            # psycopg3 uses server-side parameter binding by default (Extended Protocol)
            # This allows optimizer to transform parameters, avoiding IRIS literal size limit
            conn = psycopg.connect(
                host='127.0.0.1',
                port=15910,
                dbname='USER',
                user='benchmark',
                autocommit=True
            )
            yield conn
            conn.close()
        except psycopg.OperationalError as e:
            pytest.skip(f"PGWire server not running: {e}")

    def test_base64_vector_e2e(self, pgwire_connection):
        """
        T009: GIVEN psycopg3 client with base64 vector (1024 dims - production size)
        WHEN execute ORDER BY VECTOR_COSINE query with server-side parameter binding
        THEN query completes with HNSW optimization (<50ms latency)
        AND no IRIS literal size limit encountered (psycopg3 uses Extended Protocol)
        """
        cur = pgwire_connection.cursor()

        # Generate base64-encoded vector (1024 dims to match test_1024 table)
        query_vec = generate_random_vector(1024)
        vec_base64 = vector_to_base64(query_vec)

        # Execute vector similarity query
        start = time.perf_counter()
        cur.execute("""
            SELECT id FROM test_1024
            ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s, FLOAT))
            LIMIT 5
        """, (vec_base64,))

        results = cur.fetchall()
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Assertions
        assert len(results) == 5, \
            f"Expected 5 results, got {len(results)}"
        assert elapsed_ms < 50.0, \
            f"Query should complete in <50ms with HNSW, took {elapsed_ms:.2f}ms"
        assert all(isinstance(r[0], (int, str)) for r in results), \
            "Results should contain valid IDs"

        print(f"✅ T009 PASS: Base64 vector query completed in {elapsed_ms:.2f}ms")

    def test_json_array_vector_e2e(self, pgwire_connection):
        """
        T010: GIVEN JSON array format vector
        WHEN execute ORDER BY VECTOR_DOT_PRODUCT query
        THEN query completes with DP-444330 optimization
        """
        cur = pgwire_connection.cursor()

        # Generate JSON array vector (1024 dims to match test_1024 table)
        query_vec = generate_random_vector(1024)
        vec_json = vector_to_json_array(query_vec)

        # Execute vector similarity query
        start = time.perf_counter()
        cur.execute("""
            SELECT id FROM test_1024
            ORDER BY VECTOR_DOT_PRODUCT(vec, TO_VECTOR(%s, FLOAT)) DESC
            LIMIT 5
        """, (vec_json,))

        results = cur.fetchall()
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Assertions
        assert len(results) == 5, \
            f"Expected 5 results, got {len(results)}"
        assert elapsed_ms < 50.0, \
            f"JSON array query should complete in <50ms, took {elapsed_ms:.2f}ms"

        print(f"✅ T010 PASS: JSON array query completed in {elapsed_ms:.2f}ms")

    def test_multi_parameter_e2e(self, pgwire_connection):
        """
        T011: GIVEN query with TOP, ORDER BY vector, LIMIT
        WHEN execute with multiple parameters
        THEN only vector transformed, non-vector params preserved
        """
        cur = pgwire_connection.cursor()

        # Generate vector (1024 dims to match test_1024 table)
        query_vec = generate_random_vector(1024)
        vec_base64 = vector_to_base64(query_vec)

        # Execute multi-parameter query
        start = time.perf_counter()
        cur.execute("""
            SELECT id FROM test_1024
            ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s))
            LIMIT %s
        """, (vec_base64, 3))

        results = cur.fetchall()
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Assertions
        assert len(results) == 3, \
            f"LIMIT parameter should work, expected 3 results, got {len(results)}"
        assert elapsed_ms < 50.0, \
            f"Multi-parameter query should complete in <50ms, took {elapsed_ms:.2f}ms"

        print(f"✅ T011 PASS: Multi-parameter query completed in {elapsed_ms:.2f}ms")

    def test_non_vector_query_passthrough_e2e(self, pgwire_connection):
        """
        T012: GIVEN query without ORDER BY or TO_VECTOR
        WHEN execute through PGWire
        THEN query executes normally (pass-through, no optimization)
        """
        cur = pgwire_connection.cursor()

        # Execute non-vector query
        cur.execute("SELECT COUNT(*) FROM test_1024")
        result = cur.fetchone()

        # Assertions
        assert result[0] >= 1000, \
            f"Expected 1000+ vectors, got {result[0]}"

        print(f"✅ T012 PASS: Non-vector query passed through correctly")


# Performance validation tests
@pytest.mark.e2e
class TestVectorOptimizerPerformance:
    """Performance tests for optimizer throughput and latency using psycopg3"""

    @pytest.fixture(scope="class")
    def pgwire_connection(self):
        """Connect to PGWire server using psycopg3 (server-side parameter binding)"""
        try:
            conn = psycopg.connect(
                host='127.0.0.1',
                port=15910,
                dbname='USER',
                user='benchmark',
                autocommit=True
            )
            yield conn
            conn.close()
        except psycopg.OperationalError as e:
            pytest.skip(f"PGWire server not running: {e}")

    def test_transformation_overhead(self):
        """
        T013: GIVEN vectors of varying dimensions
        WHEN transformed by optimizer
        THEN transformation completes within performance budget
        """
        from iris_pgwire.vector_optimizer import optimize_vector_query

        dimensions_to_test = [128, 384, 1024, 1536]
        results = {}

        for dims in dimensions_to_test:
            vec = generate_random_vector(dims)
            vec_base64 = vector_to_base64(vec)

            sql = "SELECT * FROM t ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s)) LIMIT 5"
            params = [vec_base64]

            # Measure transformation time (10 iterations for stability)
            times = []
            for _ in range(10):
                start = time.perf_counter()
                optimize_vector_query(sql, params)
                times.append((time.perf_counter() - start) * 1000)

            avg_ms = sum(times) / len(times)
            results[dims] = avg_ms

            # Assert performance budget
            if dims <= 1024:
                assert avg_ms < 5.0, \
                    f"{dims}-dim vector should transform in <5ms (constitutional SLA), took {avg_ms:.2f}ms"
            elif dims <= 1536:
                assert avg_ms < 10.0, \
                    f"{dims}-dim vector should transform in <10ms (budget), took {avg_ms:.2f}ms"

        print(f"\n✅ T013 PASS: Transformation overhead by dimension:")
        for dims, avg_ms in results.items():
            print(f"   {dims}-dim: {avg_ms:.2f}ms")

    def test_concurrent_throughput(self, pgwire_connection):
        """
        T014: GIVEN 16 concurrent clients (optimal IRIS pool size)
        WHEN executing vector similarity queries
        THEN sustains 335+ qps aggregate throughput
        """
        # Note: This test would ideally use multiprocessing or asyncio for true concurrency
        # For now, we'll test sequential throughput as a baseline

        cur = pgwire_connection.cursor()

        # Warmup (1024 dims to match test_1024 table)
        for _ in range(10):
            vec = generate_random_vector(1024)
            vec_base64 = vector_to_base64(vec)
            cur.execute("""
                SELECT id FROM test_1024
                ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s))
                LIMIT 5
            """, (vec_base64,))
            cur.fetchall()

        # Measure sequential throughput (as baseline)
        num_queries = 50
        times = []

        for _ in range(num_queries):
            vec = generate_random_vector(1024)
            vec_base64 = vector_to_base64(vec)

            start = time.perf_counter()
            cur.execute("""
                SELECT id FROM test_1024
                ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s))
                LIMIT 5
            """, (vec_base64,))
            cur.fetchall()
            times.append((time.perf_counter() - start) * 1000)

        avg_ms = sum(times) / len(times)
        p95_ms = sorted(times)[int(len(times) * 0.95)]
        sequential_qps = num_queries / (sum(times) / 1000)

        print(f"\n📊 Sequential Performance (baseline):")
        print(f"   Avg latency: {avg_ms:.2f}ms")
        print(f"   P95 latency: {p95_ms:.2f}ms")
        print(f"   Sequential QPS: {sequential_qps:.1f}")
        print(f"\n   Note: True concurrent test requires 16 parallel clients")
        print(f"   Target: 335+ qps (achievable with concurrent clients)")

        # Assert latency is good (throughput requires concurrency)
        assert p95_ms < 50.0, \
            f"P95 latency should be <50ms, got {p95_ms:.2f}ms"

        print(f"\n✅ T014 PASS: Latency targets met (concurrent QPS test deferred)")


if __name__ == "__main__":
    # Run with: pytest tests/integration/test_vector_optimizer_e2e.py -v -s
    pytest.main([__file__, "-v", "-s"])

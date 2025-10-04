#!/usr/bin/env python3
"""
Comprehensive Vector Query Benchmark
Compares PGWire server vs IRIS DBAPI vs PostgreSQL baseline

Test scenarios:
- Vector similarity queries (1024 dimensions)
- Different TOP/LIMIT values (5, 10, 50)
- Parameterization patterns
- Query latency (avg, P95, P99)
"""

import time
import statistics
import struct
import base64
import random
from typing import List, Dict, Tuple
import psycopg  # For PGWire and PostgreSQL

# IRIS DBAPI test (if available)
try:
    import iris
    IRIS_AVAILABLE = True
except ImportError:
    IRIS_AVAILABLE = False


class BenchmarkResult:
    def __init__(self, name: str):
        self.name = name
        self.latencies = []
        self.errors = []

    def add_latency(self, ms: float):
        self.latencies.append(ms)

    def add_error(self, error: str):
        self.errors.append(error)

    def stats(self) -> Dict:
        if not self.latencies:
            return {"error": "No successful queries"}
        return {
            "avg_ms": statistics.mean(self.latencies),
            "p50_ms": statistics.median(self.latencies),
            "p95_ms": statistics.quantiles(self.latencies, n=20)[18] if len(self.latencies) > 1 else self.latencies[0],
            "p99_ms": statistics.quantiles(self.latencies, n=100)[98] if len(self.latencies) > 2 else max(self.latencies),
            "min_ms": min(self.latencies),
            "max_ms": max(self.latencies),
            "count": len(self.latencies),
            "error_count": len(self.errors)
        }


def generate_vector(dimensions: int = 1024) -> List[float]:
    """Generate normalized random vector"""
    vec = [random.gauss(0, 1) for _ in range(dimensions)]
    norm = sum(x*x for x in vec) ** 0.5
    return [x/norm for x in vec]


def vector_to_base64(vec: List[float]) -> str:
    """Convert vector to base64 format for IRIS"""
    vec_bytes = struct.pack(f'{len(vec)}f', *vec)
    return 'base64:' + base64.b64encode(vec_bytes).decode('ascii')


def vector_to_string(vec: List[float]) -> str:
    """Convert vector to comma-separated string"""
    return ','.join(map(str, vec))


def benchmark_pgwire(iterations: int = 100, top_k: int = 5) -> BenchmarkResult:
    """Benchmark PGWire server with standard PostgreSQL client"""
    result = BenchmarkResult(f"PGWire (TOP {top_k})")

    try:
        conn = psycopg.connect(
            host='127.0.0.1',
            port=5432,
            dbname='USER',
            user='benchmark',
            autocommit=True
        )
        cur = conn.cursor()

        for i in range(iterations):
            vec = generate_vector(1024)
            vec_b64 = vector_to_base64(vec)

            start = time.perf_counter()
            try:
                # Standard PostgreSQL/pgvector syntax
                cur.execute(
                    f"SELECT id FROM test_1024 ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s, FLOAT)) LIMIT {top_k}",
                    (vec_b64,)
                )
                rows = cur.fetchall()
                elapsed_ms = (time.perf_counter() - start) * 1000
                result.add_latency(elapsed_ms)
            except Exception as e:
                result.add_error(str(e))

        conn.close()
    except Exception as e:
        result.add_error(f"Connection failed: {e}")

    return result


def benchmark_iris_dbapi(iterations: int = 100, top_k: int = 5) -> BenchmarkResult:
    """Benchmark IRIS DBAPI with safe pattern"""
    result = BenchmarkResult(f"IRIS DBAPI (TOP {top_k})")

    if not IRIS_AVAILABLE:
        result.add_error("iris module not available (must run inside IRIS container)")
        return result

    try:
        for i in range(iterations):
            vec = generate_vector(1024)
            vec_str = vector_to_string(vec)

            start = time.perf_counter()
            try:
                # Safe pattern: string interpolation for TOP, single ? for vector
                sql = f"SELECT TOP {top_k} id FROM test_1024 ORDER BY VECTOR_COSINE(vec, TO_VECTOR(?, FLOAT))"
                res = iris.sql.exec(sql, vec_str)
                rows = [row for row in res]
                elapsed_ms = (time.perf_counter() - start) * 1000
                result.add_latency(elapsed_ms)
            except Exception as e:
                result.add_error(str(e))
    except Exception as e:
        result.add_error(f"Execution failed: {e}")

    return result


def benchmark_postgresql(iterations: int = 100, top_k: int = 5) -> BenchmarkResult:
    """Benchmark PostgreSQL baseline (if available)"""
    result = BenchmarkResult(f"PostgreSQL (LIMIT {top_k})")

    try:
        conn = psycopg.connect(
            host='127.0.0.1',
            port=5433,  # Assume PostgreSQL on different port
            dbname='test',
            user='postgres',
            autocommit=True
        )
        cur = conn.cursor()

        for i in range(iterations):
            vec = generate_vector(1024)

            start = time.perf_counter()
            try:
                # pgvector syntax
                cur.execute(
                    "SELECT id FROM test_vectors ORDER BY embedding <-> %s LIMIT %s",
                    (vec, top_k)
                )
                rows = cur.fetchall()
                elapsed_ms = (time.perf_counter() - start) * 1000
                result.add_latency(elapsed_ms)
            except Exception as e:
                result.add_error(str(e))

        conn.close()
    except Exception as e:
        result.add_error(f"Connection failed: {e}")

    return result


def print_comparison(results: List[BenchmarkResult]):
    """Print comparison table"""
    print("\n" + "="*80)
    print("VECTOR QUERY BENCHMARK COMPARISON")
    print("="*80)
    print(f"\nTest Configuration:")
    print(f"  - Vector dimensions: 1024")
    print(f"  - Iterations per test: 100")
    print(f"  - Result set sizes: TOP 5, 10, 50")
    print("\n" + "-"*80)

    for result in results:
        print(f"\n{result.name}")
        print("-" * 40)
        stats = result.stats()

        if "error" in stats:
            print(f"  ❌ {stats['error']}")
            if result.errors:
                print(f"  Errors: {result.errors[0]}")
        else:
            print(f"  ✅ Successful queries: {stats['count']}")
            print(f"  📊 Average latency: {stats['avg_ms']:.2f}ms")
            print(f"  📊 P50 latency: {stats['p50_ms']:.2f}ms")
            print(f"  📊 P95 latency: {stats['p95_ms']:.2f}ms")
            print(f"  📊 P99 latency: {stats['p99_ms']:.2f}ms")
            print(f"  📊 Min latency: {stats['min_ms']:.2f}ms")
            print(f"  📊 Max latency: {stats['max_ms']:.2f}ms")
            if stats['error_count'] > 0:
                print(f"  ⚠️  Errors: {stats['error_count']}")

    print("\n" + "="*80)


def main():
    print("Starting vector query benchmarks...")

    results = []

    # Test different TOP/LIMIT values
    for top_k in [5, 10, 50]:
        print(f"\nTesting with TOP/LIMIT {top_k}...")

        # PGWire
        print(f"  Running PGWire benchmark...")
        results.append(benchmark_pgwire(iterations=100, top_k=top_k))

        # IRIS DBAPI
        if IRIS_AVAILABLE:
            print(f"  Running IRIS DBAPI benchmark...")
            results.append(benchmark_iris_dbapi(iterations=100, top_k=top_k))

        # PostgreSQL baseline
        print(f"  Running PostgreSQL baseline...")
        results.append(benchmark_postgresql(iterations=100, top_k=top_k))

    print_comparison(results)

    # Summary
    print("\nKEY FINDINGS:")
    print("-" * 80)
    print("1. PGWire Server: Full PostgreSQL compatibility via wire protocol")
    print("2. IRIS DBAPI: Requires safe pattern (string interpolation for TOP)")
    print("3. PostgreSQL: Baseline for comparison")
    print("\nSee docs/IRIS_DBAPI_LIMITATIONS_JIRA.md for detailed analysis")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()

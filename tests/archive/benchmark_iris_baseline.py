#!/usr/bin/env python3
"""
IRIS DBAPI Baseline Benchmark

Quick baseline benchmark of IRIS DBAPI performance for comparison.
This establishes the baseline before we test PGWire overhead.
"""

import statistics
import time

# Configuration
BENCHMARK_QUERIES = 1000
WARMUP_QUERIES = 100


def benchmark_iris_dbapi_simple():
    """Benchmark simple SELECT queries"""

    print("=" * 80)
    print("IRIS DBAPI Baseline Benchmark - Simple Queries")
    print("=" * 80)

    try:
        import iris
    except ImportError:
        print("❌ iris module not available")
        return

    # Connect
    try:
        conn = iris.connect(
            hostname="localhost", port=1972, namespace="USER", username="_SYSTEM", password="SYS"
        )
        print("✅ Connected to IRIS on localhost:1972")
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        return

    # Warmup
    print(f"\nWarmup ({WARMUP_QUERIES} queries)...")
    cursor = conn.cursor()
    for _ in range(WARMUP_QUERIES):
        cursor.execute("SELECT 1")
        cursor.fetchall()

    # Benchmark
    print(f"Benchmarking ({BENCHMARK_QUERIES} queries)...")
    latencies = []

    cursor = conn.cursor()
    start_total = time.perf_counter()

    for i in range(BENCHMARK_QUERIES):
        start = time.perf_counter()
        cursor.execute("SELECT ? AS id, ? AS name", (i, f"test_{i}"))
        cursor.fetchall()
        latencies.append((time.perf_counter() - start) * 1000)

    total_time = time.perf_counter() - start_total

    # Results
    qps = BENCHMARK_QUERIES / total_time
    avg_ms = statistics.mean(latencies)
    p50_ms = statistics.median(latencies)
    p95_ms = statistics.quantiles(latencies, n=20)[18] if len(latencies) > 20 else 0
    p99_ms = statistics.quantiles(latencies, n=100)[98] if len(latencies) > 100 else 0

    print(f"\n{'='*80}")
    print("RESULTS")
    print(f"{'='*80}")
    print(f"Total queries: {BENCHMARK_QUERIES}")
    print(f"Total time: {total_time:.2f}s")
    print(f"Throughput: {qps:.2f} QPS")
    print("\nLatency:")
    print(f"  Average: {avg_ms:.2f}ms")
    print(f"  P50: {p50_ms:.2f}ms")
    print(f"  P95: {p95_ms:.2f}ms")
    print(f"  P99: {p99_ms:.2f}ms")

    cursor.close()
    conn.close()

    return {"qps": qps, "avg_ms": avg_ms, "p50_ms": p50_ms, "p95_ms": p95_ms, "p99_ms": p99_ms}


if __name__ == "__main__":
    benchmark_iris_dbapi_simple()

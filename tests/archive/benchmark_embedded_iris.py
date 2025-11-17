#!/usr/bin/env python3
"""
IRIS Embedded Python Benchmark

Benchmark using iris.sql.exec() from embedded Python.
This is the baseline for PGWire performance comparison.

Tests with REALISTIC 1024-dimensional vectors!

Run with: docker exec iris-pgwire-db /usr/irissys/bin/irispython /tmp/benchmark_embedded_iris.py
"""

import random
import statistics
import time

# Configuration
BENCHMARK_QUERIES = 1000
WARMUP_QUERIES = 100
VECTOR_DIMENSIONS = 1024


def generate_random_vector(dimensions: int = VECTOR_DIMENSIONS) -> str:
    """Generate random vector as comma-separated string"""
    values = [str(random.uniform(-1.0, 1.0)) for _ in range(dimensions)]
    return ",".join(values)


def benchmark_simple_queries():
    """Benchmark simple SELECT queries using iris.sql.exec()"""

    import iris

    print("=" * 80)
    print("IRIS Embedded Python Benchmark - iris.sql.exec()")
    print("=" * 80)
    print(f"IRIS Version: {iris.system.Version.GetNumber()}")
    print(f"Queries: {BENCHMARK_QUERIES}")
    print(f"Warmup: {WARMUP_QUERIES}")

    # Warmup
    print(f"\nWarmup ({WARMUP_QUERIES} queries)...")
    for _ in range(WARMUP_QUERIES):
        result = iris.sql.exec("SELECT 1")
        list(result)

    # Benchmark
    print(f"Benchmarking ({BENCHMARK_QUERIES} queries)...")
    latencies = []

    start_total = time.perf_counter()

    for i in range(BENCHMARK_QUERIES):
        start = time.perf_counter()
        result = iris.sql.exec(f"SELECT {i} AS id, 'test_{i}' AS name")
        list(result)
        latencies.append((time.perf_counter() - start) * 1000)

    total_time = time.perf_counter() - start_total

    # Results
    qps = BENCHMARK_QUERIES / total_time
    avg_ms = statistics.mean(latencies)
    p50_ms = statistics.median(latencies)
    p95_ms = statistics.quantiles(latencies, n=20)[18] if len(latencies) > 20 else 0
    p99_ms = statistics.quantiles(latencies, n=100)[98] if len(latencies) > 100 else 0
    min_ms = min(latencies)
    max_ms = max(latencies)

    print(f"\n{'='*80}")
    print("RESULTS - iris.sql.exec() Baseline")
    print(f"{'='*80}")
    print(f"Total queries: {BENCHMARK_QUERIES}")
    print(f"Total time: {total_time:.2f}s")
    print(f"Throughput: {qps:.2f} QPS")
    print("\nLatency:")
    print(f"  Min:     {min_ms:.2f}ms")
    print(f"  Average: {avg_ms:.2f}ms")
    print(f"  P50:     {p50_ms:.2f}ms")
    print(f"  P95:     {p95_ms:.2f}ms")
    print(f"  P99:     {p99_ms:.2f}ms")
    print(f"  Max:     {max_ms:.2f}ms")

    return {
        "qps": qps,
        "avg_ms": avg_ms,
        "p50_ms": p50_ms,
        "p95_ms": p95_ms,
        "p99_ms": p99_ms,
        "min_ms": min_ms,
        "max_ms": max_ms,
    }


def benchmark_vector_queries():
    """Benchmark vector similarity queries with 1024-dimensional vectors"""

    import iris

    print("\n" + "=" * 80)
    print(f"IRIS Embedded Python Benchmark - Vector Queries ({VECTOR_DIMENSIONS}D)")
    print("=" * 80)

    # Generate realistic 1024-dimensional vectors
    print(f"Generating {VECTOR_DIMENSIONS}-dimensional vectors...")
    vector1 = generate_random_vector()
    vector2 = generate_random_vector()

    print(f"Vector size: {len(vector1)} characters")

    # Test vector query with realistic large vectors
    test_sql = f"SELECT VECTOR_DOT_PRODUCT(TO_VECTOR('{vector1}', FLOAT), TO_VECTOR('{vector2}', FLOAT)) AS score"

    # Warmup
    print(f"Warmup ({WARMUP_QUERIES} vector queries)...")
    for _ in range(WARMUP_QUERIES):
        result = iris.sql.exec(test_sql)
        list(result)

    # Benchmark
    print(f"Benchmarking ({BENCHMARK_QUERIES} vector queries)...")
    latencies = []

    start_total = time.perf_counter()

    for _ in range(BENCHMARK_QUERIES):
        start = time.perf_counter()
        result = iris.sql.exec(test_sql)
        list(result)
        latencies.append((time.perf_counter() - start) * 1000)

    total_time = time.perf_counter() - start_total

    # Results
    qps = BENCHMARK_QUERIES / total_time
    avg_ms = statistics.mean(latencies)
    p50_ms = statistics.median(latencies)
    p95_ms = statistics.quantiles(latencies, n=20)[18] if len(latencies) > 20 else 0
    p99_ms = statistics.quantiles(latencies, n=100)[98] if len(latencies) > 100 else 0

    print(f"\n{'='*80}")
    print("RESULTS - Vector Query Performance")
    print(f"{'='*80}")
    print(f"Total queries: {BENCHMARK_QUERIES}")
    print(f"Total time: {total_time:.2f}s")
    print(f"Throughput: {qps:.2f} QPS")
    print("\nLatency:")
    print(f"  Average: {avg_ms:.2f}ms")
    print(f"  P50:     {p50_ms:.2f}ms")
    print(f"  P95:     {p95_ms:.2f}ms")
    print(f"  P99:     {p99_ms:.2f}ms")

    return {"qps": qps, "avg_ms": avg_ms, "p50_ms": p50_ms, "p95_ms": p95_ms, "p99_ms": p99_ms}


if __name__ == "__main__":
    try:
        import iris
    except ImportError:
        print("ERROR: iris module not available - must run with irispython")
        print(
            "Usage: docker exec iris-pgwire-db /usr/irissys/bin/irispython /tmp/benchmark_embedded_iris.py"
        )
        exit(1)

    simple_results = benchmark_simple_queries()
    vector_results = benchmark_vector_queries()

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Simple queries: {simple_results['qps']:.2f} QPS (avg {simple_results['avg_ms']:.2f}ms)")
    print(f"Vector queries: {vector_results['qps']:.2f} QPS (avg {vector_results['avg_ms']:.2f}ms)")

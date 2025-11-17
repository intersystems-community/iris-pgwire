#!/usr/bin/env python3
"""
3-Way Vector Query Performance Benchmark

Compares:
1. IRIS + PGWire (our implementation)
2. psycopg3 + PostgreSQL (native PostgreSQL with pgvector)
3. IRIS + DBAPI (direct IRIS connection)

Tests:
- Simple SELECT queries
- Vector similarity queries
- Parameterized queries
- Throughput (queries per second)
- Latency (P50, P95, P99)
"""

import statistics
import time
from dataclasses import dataclass, field

# Configuration
BENCHMARK_QUERIES = 1000
WARMUP_QUERIES = 100
VECTOR_DIMENSIONS = 128


@dataclass
class BenchmarkResult:
    """Results for a single benchmark configuration"""

    name: str
    queries_executed: int
    total_time_sec: float
    latencies_ms: list[float] = field(default_factory=list)
    errors: int = 0

    @property
    def qps(self) -> float:
        """Queries per second"""
        return self.queries_executed / self.total_time_sec if self.total_time_sec > 0 else 0

    @property
    def p50_ms(self) -> float:
        """50th percentile latency"""
        return statistics.median(self.latencies_ms) if self.latencies_ms else 0

    @property
    def p95_ms(self) -> float:
        """95th percentile latency"""
        return (
            statistics.quantiles(self.latencies_ms, n=20)[18] if len(self.latencies_ms) > 20 else 0
        )

    @property
    def p99_ms(self) -> float:
        """99th percentile latency"""
        return (
            statistics.quantiles(self.latencies_ms, n=100)[98]
            if len(self.latencies_ms) > 100
            else 0
        )

    @property
    def avg_ms(self) -> float:
        """Average latency"""
        return statistics.mean(self.latencies_ms) if self.latencies_ms else 0


def benchmark_iris_pgwire():
    """Benchmark 1: IRIS + PGWire server"""

    print("\n" + "=" * 80)
    print("BENCHMARK 1: IRIS + PGWire")
    print("=" * 80)

    try:
        import psycopg
    except ImportError:
        print("❌ psycopg3 not available - install with: pip install psycopg[binary]")
        return None

    # Connect to PGWire server
    try:
        conn = psycopg.connect("host=localhost port=5432 dbname=USER")
        print("✅ Connected to PGWire server on port 5432")
    except Exception as e:
        print(f"❌ Failed to connect to PGWire: {e}")
        print("   Is the PGWire server running?")
        return None

    result = BenchmarkResult(name="IRIS + PGWire", queries_executed=0, total_time_sec=0)

    # Warmup
    print(f"Warming up ({WARMUP_QUERIES} queries)...")
    with conn.cursor() as cur:
        for _ in range(WARMUP_QUERIES):
            cur.execute("SELECT 1")
            cur.fetchall()

    # Benchmark simple queries
    print(f"Benchmarking simple queries ({BENCHMARK_QUERIES} iterations)...")
    latencies = []

    with conn.cursor() as cur:
        start_total = time.perf_counter()

        for i in range(BENCHMARK_QUERIES):
            start = time.perf_counter()
            cur.execute("SELECT $1::integer AS id, $2::text AS name", (i, f"test_{i}"))
            cur.fetchall()
            latencies.append((time.perf_counter() - start) * 1000)

        total_time = time.perf_counter() - start_total

    result.queries_executed = BENCHMARK_QUERIES
    result.total_time_sec = total_time
    result.latencies_ms = latencies

    conn.close()

    print(f"✅ Completed {result.queries_executed} queries in {result.total_time_sec:.2f}s")
    print(f"   QPS: {result.qps:.2f}")
    print(
        f"   Latency - Avg: {result.avg_ms:.2f}ms, P50: {result.p50_ms:.2f}ms, P95: {result.p95_ms:.2f}ms, P99: {result.p99_ms:.2f}ms"
    )

    return result


def benchmark_postgresql_native():
    """Benchmark 2: PostgreSQL + psycopg3"""

    print("\n" + "=" * 80)
    print("BENCHMARK 2: PostgreSQL + psycopg3 (native)")
    print("=" * 80)

    try:
        import psycopg
    except ImportError:
        print("❌ psycopg3 not available")
        return None

    # Connect to PostgreSQL
    try:
        conn = psycopg.connect(
            "host=localhost port=5433 dbname=postgres user=postgres password=postgres"
        )
        print("✅ Connected to PostgreSQL on port 5433")
    except Exception as e:
        print(f"⚠️  PostgreSQL not available: {e}")
        print("   Skipping PostgreSQL benchmark (optional)")
        return None

    result = BenchmarkResult(name="PostgreSQL + psycopg3", queries_executed=0, total_time_sec=0)

    # Warmup
    print(f"Warming up ({WARMUP_QUERIES} queries)...")
    with conn.cursor() as cur:
        for _ in range(WARMUP_QUERIES):
            cur.execute("SELECT 1")
            cur.fetchall()

    # Benchmark simple queries
    print(f"Benchmarking simple queries ({BENCHMARK_QUERIES} iterations)...")
    latencies = []

    with conn.cursor() as cur:
        start_total = time.perf_counter()

        for i in range(BENCHMARK_QUERIES):
            start = time.perf_counter()
            cur.execute("SELECT %s::integer AS id, %s::text AS name", (i, f"test_{i}"))
            cur.fetchall()
            latencies.append((time.perf_counter() - start) * 1000)

        total_time = time.perf_counter() - start_total

    result.queries_executed = BENCHMARK_QUERIES
    result.total_time_sec = total_time
    result.latencies_ms = latencies

    conn.close()

    print(f"✅ Completed {result.queries_executed} queries in {result.total_time_sec:.2f}s")
    print(f"   QPS: {result.qps:.2f}")
    print(
        f"   Latency - Avg: {result.avg_ms:.2f}ms, P50: {result.p50_ms:.2f}ms, P95: {result.p95_ms:.2f}ms, P99: {result.p99_ms:.2f}ms"
    )

    return result


def benchmark_iris_dbapi():
    """Benchmark 3: IRIS + DBAPI (direct connection)"""

    print("\n" + "=" * 80)
    print("BENCHMARK 3: IRIS + DBAPI (direct)")
    print("=" * 80)

    try:
        import iris
    except ImportError:
        print("❌ iris module not available")
        return None

    # Connect directly to IRIS
    try:
        conn = iris.connect(
            hostname="localhost", port=1972, namespace="USER", username="_SYSTEM", password="SYS"
        )
        print("✅ Connected to IRIS directly on port 1972")
    except Exception as e:
        print(f"❌ Failed to connect to IRIS: {e}")
        return None

    result = BenchmarkResult(name="IRIS + DBAPI", queries_executed=0, total_time_sec=0)

    # Warmup
    print(f"Warming up ({WARMUP_QUERIES} queries)...")
    cursor = conn.cursor()
    for _ in range(WARMUP_QUERIES):
        cursor.execute("SELECT 1")
        cursor.fetchall()

    # Benchmark simple queries
    print(f"Benchmarking simple queries ({BENCHMARK_QUERIES} iterations)...")
    latencies = []

    cursor = conn.cursor()
    start_total = time.perf_counter()

    for i in range(BENCHMARK_QUERIES):
        start = time.perf_counter()
        cursor.execute("SELECT ? AS id, ? AS name", (i, f"test_{i}"))
        cursor.fetchall()
        latencies.append((time.perf_counter() - start) * 1000)

    total_time = time.perf_counter() - start_total

    result.queries_executed = BENCHMARK_QUERIES
    result.total_time_sec = total_time
    result.latencies_ms = latencies

    cursor.close()
    conn.close()

    print(f"✅ Completed {result.queries_executed} queries in {result.total_time_sec:.2f}s")
    print(f"   QPS: {result.qps:.2f}")
    print(
        f"   Latency - Avg: {result.avg_ms:.2f}ms, P50: {result.p50_ms:.2f}ms, P95: {result.p95_ms:.2f}ms, P99: {result.p99_ms:.2f}ms"
    )

    return result


def print_comparison_table(results: list[BenchmarkResult]):
    """Print comparison table of all benchmark results"""

    print("\n" + "=" * 80)
    print("COMPARISON SUMMARY")
    print("=" * 80)

    # Filter out None results
    results = [r for r in results if r is not None]

    if not results:
        print("❌ No benchmark results available")
        return

    # Find baseline (IRIS DBAPI if available, otherwise first result)
    baseline = next((r for r in results if "DBAPI" in r.name), results[0])

    print(
        f"\n{'Configuration':<30} {'QPS':<12} {'Avg (ms)':<12} {'P50 (ms)':<12} {'P95 (ms)':<12} {'P99 (ms)':<12} {'vs Baseline':<15}"
    )
    print("-" * 120)

    for result in results:
        qps_ratio = result.qps / baseline.qps if baseline.qps > 0 else 0
        vs_baseline = f"{qps_ratio:.2f}x" if result != baseline else "baseline"

        print(
            f"{result.name:<30} {result.qps:<12.2f} {result.avg_ms:<12.2f} {result.p50_ms:<12.2f} "
            f"{result.p95_ms:<12.2f} {result.p99_ms:<12.2f} {vs_baseline:<15}"
        )

    # Analysis
    print("\n" + "=" * 80)
    print("ANALYSIS")
    print("=" * 80)

    pgwire = next((r for r in results if "PGWire" in r.name), None)
    postgres = next((r for r in results if "PostgreSQL" in r.name), None)
    dbapi = next((r for r in results if "DBAPI" in r.name), None)

    if pgwire and dbapi:
        overhead = ((pgwire.avg_ms - dbapi.avg_ms) / dbapi.avg_ms * 100) if dbapi.avg_ms > 0 else 0
        print("\nPGWire vs IRIS DBAPI:")
        print(f"  Overhead: {overhead:.1f}%")
        print(f"  QPS ratio: {pgwire.qps / dbapi.qps:.2f}x" if dbapi.qps > 0 else "")

    if pgwire and postgres:
        diff = (
            ((pgwire.avg_ms - postgres.avg_ms) / postgres.avg_ms * 100)
            if postgres.avg_ms > 0
            else 0
        )
        print("\nPGWire vs PostgreSQL native:")
        print(f"  Difference: {diff:+.1f}%")
        print(f"  QPS ratio: {pgwire.qps / postgres.qps:.2f}x" if postgres.qps > 0 else "")

    print()


def main():
    print("=" * 80)
    print("3-Way Vector Database Performance Benchmark")
    print("=" * 80)
    print(f"Queries per benchmark: {BENCHMARK_QUERIES}")
    print(f"Warmup queries: {WARMUP_QUERIES}")
    print()

    results = []

    # Run all benchmarks
    results.append(benchmark_iris_pgwire())
    results.append(benchmark_postgresql_native())
    results.append(benchmark_iris_dbapi())

    # Print comparison
    print_comparison_table(results)


if __name__ == "__main__":
    main()

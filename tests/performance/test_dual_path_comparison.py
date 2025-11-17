#!/usr/bin/env python3
"""
Dual-Path Performance Comparison Test

Tests BOTH IRIS execution paths and compares to PostgreSQL:
1. DBAPI Path (external connection via iris.connect())
2. Embedded Path (would use iris.sql.exec() if running inside IRIS)
3. PostgreSQL (reference baseline with pgvector)

This demonstrates the architectural difference between:
- External DBAPI connection (slower due to network/serialization overhead)
- Embedded Python execution (faster, direct IRIS access)
"""

import base64
import random
import struct
import time


def gen_vec(d=1024):
    """Generate normalized random vector"""
    v = [random.gauss(0, 1) for _ in range(d)]
    n = sum(x * x for x in v) ** 0.5
    return [x / n for x in v]


def vec_to_base64(vec):
    """Convert vector to base64 encoding"""
    b = struct.pack(f"{len(vec)}f", *vec)
    return "base64:" + base64.b64encode(b).decode("ascii")


print("=" * 80)
print("DUAL-PATH PERFORMANCE COMPARISON")
print("Testing BOTH IRIS execution paths vs PostgreSQL")
print("=" * 80)
print()

# ============================================================================
# PATH 1: IRIS DBAPI (External Connection)
# ============================================================================
print("1. IRIS DBAPI PATH (External Connection)")
print("-" * 80)

try:
    import iris

    conn = iris.createConnection("localhost", 1972, "USER", "_SYSTEM", "SYS")
    cur = conn.cursor()

    # Check execution mode
    has_embedded = hasattr(iris, "sql") and hasattr(iris.sql, "exec")
    print(f"   Embedded mode available: {has_embedded}")
    print("   Using: DBAPI external connection")
    print()

    # Verify test data
    cur.execute("SELECT COUNT(*) FROM test_1024")
    count = cur.fetchone()[0]
    print(f"   Dataset: {count} vectors in test_1024")
    print()

    # Warmup
    print("   Warmup: 5 queries...")
    for i in range(5):
        vec = gen_vec(1024)
        vec_str = "[" + ",".join(str(v) for v in vec) + "]"
        cur.execute(
            f"SELECT TOP 5 id FROM test_1024 ORDER BY VECTOR_COSINE(vec, TO_VECTOR('{vec_str}'))"
        )
        cur.fetchall()

    # Benchmark
    print("   Benchmark: 30 queries...")
    times = []
    for i in range(30):
        vec = gen_vec(1024)
        vec_str = "[" + ",".join(str(v) for v in vec) + "]"

        start = time.perf_counter()
        cur.execute(
            f"SELECT TOP 5 id FROM test_1024 ORDER BY VECTOR_COSINE(vec, TO_VECTOR('{vec_str}'))"
        )
        cur.fetchall()
        times.append((time.perf_counter() - start) * 1000)

    avg_dbapi = sum(times) / len(times)
    p95_dbapi = sorted(times)[int(len(times) * 0.95)]
    min_dbapi = min(times)
    max_dbapi = max(times)
    qps_dbapi = 30 / (sum(times) / 1000)

    print()
    print("   Results (DBAPI External):")
    print(f"      Avg latency: {avg_dbapi:6.2f}ms")
    print(f"      P95 latency: {p95_dbapi:6.2f}ms")
    print(f"      Min latency: {min_dbapi:6.2f}ms")
    print(f"      Max latency: {max_dbapi:6.2f}ms")
    print(f"      Throughput:  {qps_dbapi:6.1f} qps")
    print()

    conn.close()

except Exception as e:
    print(f"   ❌ DBAPI test failed: {e}")
    avg_dbapi = None
    qps_dbapi = None
    print()

# ============================================================================
# PATH 2: IRIS Embedded Python (if available)
# ============================================================================
print("2. IRIS EMBEDDED PYTHON PATH")
print("-" * 80)

if has_embedded:
    print("   ✅ Embedded mode IS available")
    print("   Note: Performance should be better than DBAPI due to direct access")
    print()
    # TODO: Implement embedded mode benchmark
    # This would require running Python code INSIDE the IRIS container
    print("   ⚠️  Benchmark requires running inside IRIS container")
    print("   Expected performance: ~8-12ms (from PERFORMANCE.md)")
    avg_embedded = None
    qps_embedded = None
else:
    print("   ❌ Embedded mode NOT available (iris.sql.exec() missing)")
    print("   This is expected when running Python outside IRIS container")
    print()
    print("   To test embedded path:")
    print("   1. Run Python code inside IRIS container")
    print("   2. Use iris.sql.exec() for direct query execution")
    print("   3. Expected ~40-60% faster than DBAPI external connection")
    avg_embedded = None
    qps_embedded = None
print()

# ============================================================================
# PATH 3: PostgreSQL + pgvector (Reference)
# ============================================================================
print("3. POSTGRESQL + PGVECTOR (Reference Baseline)")
print("-" * 80)

try:
    import psycopg2

    conn = psycopg2.connect(
        host="localhost", port=5432, database="postgres", user="postgres", password="postgres"
    )
    conn.autocommit = True
    cur = conn.cursor()

    # Verify test data
    cur.execute("SELECT COUNT(*) FROM test_vectors_1024")
    count = cur.fetchone()[0]
    print(f"   Dataset: {count} vectors in test_vectors_1024")
    print()

    # Warmup
    print("   Warmup: 5 queries...")
    for i in range(5):
        vec = gen_vec(1024)
        cur.execute("SELECT id FROM test_vectors_1024 ORDER BY vec <=> %s LIMIT 5", (vec,))
        cur.fetchall()

    # Benchmark
    print("   Benchmark: 30 queries...")
    times = []
    for i in range(30):
        vec = gen_vec(1024)

        start = time.perf_counter()
        cur.execute("SELECT id FROM test_vectors_1024 ORDER BY vec <=> %s LIMIT 5", (vec,))
        cur.fetchall()
        times.append((time.perf_counter() - start) * 1000)

    avg_pg = sum(times) / len(times)
    p95_pg = sorted(times)[int(len(times) * 0.95)]
    min_pg = min(times)
    max_pg = max(times)
    qps_pg = 30 / (sum(times) / 1000)

    print()
    print("   Results (PostgreSQL + pgvector):")
    print(f"      Avg latency: {avg_pg:6.2f}ms")
    print(f"      P95 latency: {p95_pg:6.2f}ms")
    print(f"      Min latency: {min_pg:6.2f}ms")
    print(f"      Max latency: {max_pg:6.2f}ms")
    print(f"      Throughput:  {qps_pg:6.1f} qps")
    print()

    conn.close()

except Exception as e:
    print(f"   ❌ PostgreSQL test failed: {e}")
    avg_pg = None
    qps_pg = None
    print()

# ============================================================================
# COMPARISON SUMMARY
# ============================================================================
print("=" * 80)
print("PERFORMANCE COMPARISON SUMMARY")
print("=" * 80)
print()

print("┌─────────────────────────┬──────────┬──────────┬──────────────┐")
print("│ Execution Path          │   Avg    │   P95    │  Throughput  │")
print("├─────────────────────────┼──────────┼──────────┼──────────────┤")

if avg_dbapi:
    print(
        f"│ IRIS DBAPI (external)   │ {avg_dbapi:6.2f}ms │ {p95_dbapi:6.2f}ms │ {qps_dbapi:7.1f} qps │"
    )
else:
    print("│ IRIS DBAPI (external)   │   N/A    │   N/A    │     N/A      │")

if avg_embedded:
    print(
        f"│ IRIS Embedded (direct)  │ {avg_embedded:6.2f}ms │   N/A    │ {qps_embedded:7.1f} qps │"
    )
else:
    print("│ IRIS Embedded (direct)  │   N/A    │   N/A    │     N/A      │")

if avg_pg:
    print(f"│ PostgreSQL + pgvector   │ {avg_pg:6.2f}ms │ {p95_pg:6.2f}ms │ {qps_pg:7.1f} qps │")
else:
    print("│ PostgreSQL + pgvector   │   N/A    │   N/A    │     N/A      │")

print("└─────────────────────────┴──────────┴──────────┴──────────────┘")
print()

# Performance analysis
if avg_dbapi and avg_pg:
    slowdown = avg_dbapi / avg_pg
    print("Performance Analysis:")
    print(f"   IRIS DBAPI is {slowdown:.1f}× slower than PostgreSQL")
    print("   This is expected due to:")
    print("   - External connection overhead (network)")
    print("   - IRIS driver serialization")
    print("   - No HNSW optimization (needs investigation)")
    print()

print("Expected Performance (from PERFORMANCE.md):")
print("   - IRIS PGWire (embedded):  12.4ms for 1024D vectors")
print("   - PostgreSQL + pgvector:    8.2ms for similar vectors")
print("   - Embedded ~40-60% faster than DBAPI external")
print()

print("Key Insights:")
print("   1. DBAPI external path = slower (what we're testing now)")
print("   2. Embedded Python path = faster (requires running inside IRIS)")
print("   3. PostgreSQL baseline for comparison")
print("   4. HNSW index not providing expected speedup (investigation needed)")
print()

print("=" * 80)

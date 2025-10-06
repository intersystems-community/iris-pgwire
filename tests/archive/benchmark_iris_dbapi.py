#!/usr/bin/env python3
"""
DBAPI Baseline Benchmark for Vector Similarity Queries

This benchmark establishes the performance baseline for HNSW-optimized
vector similarity queries using IRIS native DBAPI (without PGWire).

Target: 335+ qps, <50ms P95 latency
"""

import random
import math
import time


def normalize_vector(vec):
    """Normalize vector to unit length"""
    magnitude = math.sqrt(sum(x * x for x in vec))
    if magnitude == 0:
        return vec
    return [x / magnitude for x in vec]


def generate_random_vector(dimensions=1024):
    """Generate normalized random vector"""
    vec = [random.gauss(0, 1) for _ in range(dimensions)]
    return normalize_vector(vec)


def vector_to_iris_literal(vec):
    """Convert Python list to IRIS vector literal format"""
    return '[' + ','.join(str(float(v)) for v in vec) + ']'


def main():
    import iris

    print('='*70)
    print('DBAPI Baseline Benchmark - Vector Similarity Queries')
    print('='*70)

    # Warmup queries (10)
    print('\n📊 Warming up (10 queries)...')
    for i in range(10):
        vec = generate_random_vector(1024)
        vec_literal = vector_to_iris_literal(vec)

        iris.sql.exec(f'''
            SELECT TOP 5 id
            FROM test_1024
            ORDER BY VECTOR_DOT_PRODUCT(vec, TO_VECTOR('{vec_literal}', FLOAT)) DESC
        ''')

    print('   ✅ Warmup complete')

    # Benchmark queries (50)
    print('\n📊 Running benchmark (50 queries)...')
    times = []

    for i in range(50):
        vec = generate_random_vector(1024)
        vec_literal = vector_to_iris_literal(vec)

        start = time.perf_counter()
        iris.sql.exec(f'''
            SELECT TOP 5 id
            FROM test_1024
            ORDER BY VECTOR_DOT_PRODUCT(vec, TO_VECTOR('{vec_literal}', FLOAT)) DESC
        ''')
        elapsed = (time.perf_counter() - start) * 1000  # Convert to milliseconds
        times.append(elapsed)

        if (i + 1) % 10 == 0:
            print(f'   Completed {i + 1}/50 queries...')

    # Calculate metrics
    avg_ms = sum(times) / len(times)
    min_ms = min(times)
    max_ms = max(times)
    p50_ms = sorted(times)[int(len(times) * 0.50)]
    p95_ms = sorted(times)[int(len(times) * 0.95)]
    p99_ms = sorted(times)[int(len(times) * 0.99)]
    qps = 50 / (sum(times) / 1000)

    # Display results
    print('\n' + '='*70)
    print('BENCHMARK RESULTS')
    print('='*70)
    print(f'\n📈 Latency Metrics:')
    print(f'   Avg:    {avg_ms:6.2f} ms')
    print(f'   Min:    {min_ms:6.2f} ms')
    print(f'   P50:    {p50_ms:6.2f} ms')
    print(f'   P95:    {p95_ms:6.2f} ms')
    print(f'   P99:    {p99_ms:6.2f} ms')
    print(f'   Max:    {max_ms:6.2f} ms')

    print(f'\n🚀 Throughput:')
    print(f'   QPS:    {qps:6.1f} queries/second')

    print(f'\n🎯 Target Metrics:')
    print(f'   Throughput:  335+ qps')
    print(f'   P95 Latency: <50ms')

    print(f'\n📊 Status:')
    qps_pass = qps >= 335
    p95_pass = p95_ms < 50

    print(f'   Throughput:  {"✅ PASS" if qps_pass else "❌ FAIL"} ({qps:.1f} qps)')
    print(f'   P95 Latency: {"✅ PASS" if p95_pass else "❌ FAIL"} ({p95_ms:.2f} ms)')

    if qps_pass and p95_pass:
        print('\n✅ T003 SUCCESS: DBAPI baseline meets performance targets!')
    else:
        print('\n⚠️  T003 WARNING: Performance below target (may need HNSW optimization)')

    print('='*70)


if __name__ == '__main__':
    main()

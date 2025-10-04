#!/usr/bin/env python3
"""
Profile vector query execution to identify 16× overhead source.

Breaks down timing into:
1. Connection establishment
2. Query send (client → PGWire)
3. PGWire processing (protocol parsing, optimization)
4. IRIS execution (DBAPI call)
5. Result fetch and encoding
6. Response send (PGWire → client)
"""
import time
import psycopg
import iris

# Test vector (128D)
TEST_VECTOR = ','.join(['0.1'] * 128)

# Query to profile
QUERY_PGWIRE = f"SELECT id, VECTOR_COSINE(embedding, TO_VECTOR('{TEST_VECTOR}', FLOAT)) AS distance FROM benchmark_vectors ORDER BY distance LIMIT 5"
QUERY_DBAPI = f"SELECT TOP 5 id, VECTOR_COSINE(embedding, TO_VECTOR('{TEST_VECTOR}', FLOAT)) AS distance FROM benchmark_vectors ORDER BY distance"

def profile_pgwire(iterations=10):
    """Profile PGWire query execution"""
    print("=" * 80)
    print("PROFILING PGWIRE")
    print("=" * 80)

    timings = {
        'total': [],
        'connect': [],
        'execute': [],
        'fetch': [],
    }

    for i in range(iterations):
        # Connection time
        t_start = time.perf_counter()
        conn = psycopg.connect(host='localhost', port=5434, dbname='USER')
        cur = conn.cursor()
        t_connect = (time.perf_counter() - t_start) * 1000

        # Execution time (includes PGWire processing + IRIS exec)
        t_start = time.perf_counter()
        cur.execute(QUERY_PGWIRE)
        t_execute = (time.perf_counter() - t_start) * 1000

        # Fetch time (result serialization + network)
        t_start = time.perf_counter()
        result = cur.fetchall()
        t_fetch = (time.perf_counter() - t_start) * 1000

        cur.close()
        conn.close()

        t_total = t_connect + t_execute + t_fetch

        timings['total'].append(t_total)
        timings['connect'].append(t_connect)
        timings['execute'].append(t_execute)
        timings['fetch'].append(t_fetch)

    # Calculate averages
    print(f"\nResults over {iterations} iterations:")
    print(f"  Total:      {sum(timings['total'])/iterations:.2f}ms")
    print(f"  Connect:    {sum(timings['connect'])/iterations:.2f}ms  ({sum(timings['connect'])/sum(timings['total'])*100:.1f}%)")
    print(f"  Execute:    {sum(timings['execute'])/iterations:.2f}ms  ({sum(timings['execute'])/sum(timings['total'])*100:.1f}%)")
    print(f"  Fetch:      {sum(timings['fetch'])/iterations:.2f}ms  ({sum(timings['fetch'])/sum(timings['total'])*100:.1f}%)")

    return timings

def profile_dbapi(iterations=10):
    """Profile direct IRIS DBAPI execution"""
    print("\n" + "=" * 80)
    print("PROFILING IRIS DBAPI")
    print("=" * 80)

    timings = {
        'total': [],
        'connect': [],
        'execute': [],
        'fetch': [],
    }

    for i in range(iterations):
        # Connection time
        t_start = time.perf_counter()
        conn = iris.connect(hostname='localhost', port=1972, namespace='USER',
                           username='_SYSTEM', password='SYS')
        cur = conn.cursor()
        t_connect = (time.perf_counter() - t_start) * 1000

        # Execution time
        t_start = time.perf_counter()
        cur.execute(QUERY_DBAPI)
        t_execute = (time.perf_counter() - t_start) * 1000

        # Fetch time
        t_start = time.perf_counter()
        result = cur.fetchall()
        t_fetch = (time.perf_counter() - t_start) * 1000

        cur.close()
        conn.close()

        t_total = t_connect + t_execute + t_fetch

        timings['total'].append(t_total)
        timings['connect'].append(t_connect)
        timings['execute'].append(t_execute)
        timings['fetch'].append(t_fetch)

    # Calculate averages
    print(f"\nResults over {iterations} iterations:")
    print(f"  Total:      {sum(timings['total'])/iterations:.2f}ms")
    print(f"  Connect:    {sum(timings['connect'])/iterations:.2f}ms  ({sum(timings['connect'])/sum(timings['total'])*100:.1f}%)")
    print(f"  Execute:    {sum(timings['execute'])/iterations:.2f}ms  ({sum(timings['execute'])/sum(timings['total'])*100:.1f}%)")
    print(f"  Fetch:      {sum(timings['fetch'])/iterations:.2f}ms  ({sum(timings['fetch'])/sum(timings['total'])*100:.1f}%)")

    return timings

def compare_results(pgwire_timings, dbapi_timings):
    """Compare PGWire vs DBAPI performance"""
    print("\n" + "=" * 80)
    print("COMPARISON: PGWire vs IRIS DBAPI")
    print("=" * 80)

    iterations = len(pgwire_timings['total'])

    for phase in ['total', 'connect', 'execute', 'fetch']:
        pgwire_avg = sum(pgwire_timings[phase]) / iterations
        dbapi_avg = sum(dbapi_timings[phase]) / iterations
        overhead = pgwire_avg - dbapi_avg
        overhead_pct = (pgwire_avg / dbapi_avg - 1) * 100 if dbapi_avg > 0 else 0

        print(f"\n{phase.upper()}:")
        print(f"  PGWire:     {pgwire_avg:.2f}ms")
        print(f"  DBAPI:      {dbapi_avg:.2f}ms")
        print(f"  Overhead:   {overhead:.2f}ms ({overhead_pct:+.1f}%)")

if __name__ == '__main__':
    # Warmup
    print("Warming up connections...")
    try:
        conn = psycopg.connect(host='localhost', port=5434, dbname='USER')
        conn.close()
    except Exception as e:
        print(f"Warning: PGWire warmup failed: {e}")

    try:
        conn = iris.connect(hostname='localhost', port=1972, namespace='USER',
                           username='_SYSTEM', password='SYS')
        conn.close()
    except Exception as e:
        print(f"Warning: DBAPI warmup failed: {e}")

    print("\nStarting profiling...\n")

    # Profile both
    pgwire_timings = profile_pgwire(iterations=20)
    dbapi_timings = profile_dbapi(iterations=20)

    # Compare
    compare_results(pgwire_timings, dbapi_timings)

    print("\n" + "=" * 80)
    print("PROFILING COMPLETE")
    print("=" * 80)

#!/usr/bin/env python3
"""
Complete E2E Integration and Benchmark Test

Starts PGWire server, runs E2E tests with real PostgreSQL client,
and benchmarks performance vs DBAPI baseline.
"""

import sys
import os
import time
import subprocess
import socket
import signal
import random
import struct
import base64
import math

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def wait_for_port(host, port, timeout=30):
    """Wait for port to become available"""
    print(f"   Waiting for {host}:{port} to be ready...")
    start = time.time()
    while time.time() - start < timeout:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            if sock.connect_ex((host, port)) == 0:
                sock.close()
                print(f"   ✅ Port {port} is ready!")
                return True
        except:
            pass
        time.sleep(0.5)
    return False


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


def vector_to_base64(vec):
    """Convert vector to base64 format (psycopg2 encoding)"""
    vec_bytes = struct.pack(f'{len(vec)}f', *vec)
    return 'base64:' + base64.b64encode(vec_bytes).decode('ascii')


def main():
    print("="*70)
    print("E2E Integration & Benchmark Test")
    print("="*70)

    # Step 1: Start PGWire server
    print("\n1. Starting PGWire server...")

    # Use a non-standard port to avoid conflicts
    test_port = 15432

    env = os.environ.copy()
    env.update({
        'PGWIRE_HOST': '127.0.0.1',
        'PGWIRE_PORT': str(test_port),
        'IRIS_HOST': 'localhost',
        'IRIS_PORT': '1972',
        'IRIS_USERNAME': '_SYSTEM',
        'IRIS_PASSWORD': 'SYS',
        'IRIS_NAMESPACE': 'USER',
        'PGWIRE_DEBUG': 'false'
    })

    server_process = subprocess.Popen(
        [sys.executable, '-m', 'iris_pgwire.server'],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=os.path.join(os.path.dirname(__file__), '..')
    )

    # Wait for server to start
    if not wait_for_port('127.0.0.1', test_port, timeout=10):
        print("   ❌ Server failed to start!")
        server_process.kill()
        return False

    print(f"   ✅ PGWire server running on port {test_port}")

    try:
        # Step 2: Test connection with psycopg2
        print("\n2. Testing PostgreSQL client connection...")
        try:
            import psycopg2
        except ImportError:
            print("   ❌ psycopg2 not installed. Installing...")
            subprocess.run([sys.executable, '-m', 'pip', 'install', 'psycopg2-binary'], check=True)
            import psycopg2

        try:
            conn = psycopg2.connect(
                host='127.0.0.1',
                port=test_port,
                database='USER',
                user='_SYSTEM',
                password='SYS',
                connect_timeout=5
            )
            conn.autocommit = True
            print("   ✅ Connection established!")
        except Exception as e:
            print(f"   ❌ Connection failed: {e}")
            server_process.kill()
            return False

        # Step 3: Run E2E vector query tests
        print("\n3. Testing vector query optimizer (E2E)...")
        cur = conn.cursor()

        # Test 1: Simple vector query
        print("   Test 1: Base64 vector query...")
        vec = generate_random_vector(1024)
        vec_b64 = vector_to_base64(vec)

        start = time.perf_counter()
        cur.execute("""
            SELECT id FROM test_1024
            ORDER BY VECTOR_DOT_PRODUCT(vec, TO_VECTOR(%s, FLOAT)) DESC
            LIMIT 5
        """, (vec_b64,))
        results = cur.fetchall()
        elapsed_ms = (time.perf_counter() - start) * 1000

        if len(results) == 5:
            print(f"      ✅ Query succeeded! ({elapsed_ms:.2f}ms, {len(results)} results)")
        else:
            print(f"      ❌ Expected 5 results, got {len(results)}")
            conn.close()
            server_process.kill()
            return False

        # Test 2: JSON array vector
        print("   Test 2: JSON array vector query...")
        vec_json = '[' + ','.join(str(v) for v in vec) + ']'

        cur.execute("""
            SELECT id FROM test_1024
            ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s, FLOAT))
            LIMIT 5
        """, (vec_json,))
        results = cur.fetchall()

        if len(results) == 5:
            print(f"      ✅ Query succeeded! ({len(results)} results)")
        else:
            print(f"      ❌ Expected 5 results, got {len(results)}")

        # Test 3: Multi-parameter query
        print("   Test 3: Multi-parameter query...")
        vec = generate_random_vector(1024)
        vec_b64 = vector_to_base64(vec)

        cur.execute("""
            SELECT id FROM test_1024
            ORDER BY VECTOR_DOT_PRODUCT(vec, TO_VECTOR(%s, FLOAT)) DESC
            LIMIT %s
        """, (vec_b64, 10))
        results = cur.fetchall()

        if len(results) == 10:
            print(f"      ✅ Query succeeded! ({len(results)} results)")
        else:
            print(f"      ❌ Expected 10 results, got {len(results)}")

        # Step 4: Performance Benchmark
        print("\n4. Running performance benchmark (PGWire vs DBAPI)...")

        # Warmup
        print("   Warming up (10 queries)...")
        for _ in range(10):
            vec = generate_random_vector(1024)
            vec_b64 = vector_to_base64(vec)
            cur.execute("""
                SELECT id FROM test_1024
                ORDER BY VECTOR_DOT_PRODUCT(vec, TO_VECTOR(%s, FLOAT)) DESC
                LIMIT 5
            """, (vec_b64,))
            cur.fetchall()

        # Benchmark (50 queries)
        print("   Benchmarking (50 queries)...")
        times = []
        for i in range(50):
            vec = generate_random_vector(1024)
            vec_b64 = vector_to_base64(vec)

            start = time.perf_counter()
            cur.execute("""
                SELECT id FROM test_1024
                ORDER BY VECTOR_DOT_PRODUCT(vec, TO_VECTOR(%s, FLOAT)) DESC
                LIMIT 5
            """, (vec_b64,))
            results = cur.fetchall()
            elapsed = (time.perf_counter() - start) * 1000
            times.append(elapsed)

            if (i + 1) % 10 == 0:
                print(f"      Completed {i + 1}/50 queries...")

        # Calculate metrics
        avg_ms = sum(times) / len(times)
        min_ms = min(times)
        max_ms = max(times)
        p50_ms = sorted(times)[int(len(times) * 0.50)]
        p95_ms = sorted(times)[int(len(times) * 0.95)]
        p99_ms = sorted(times)[int(len(times) * 0.99)]
        qps = 50 / (sum(times) / 1000)

        # Display results
        print("\n" + "="*70)
        print("BENCHMARK RESULTS - PGWire + Optimizer")
        print("="*70)
        print(f"\n📈 Latency Metrics:")
        print(f"   Avg:    {avg_ms:6.2f} ms")
        print(f"   Min:    {min_ms:6.2f} ms")
        print(f"   P50:    {p50_ms:6.2f} ms")
        print(f"   P95:    {p95_ms:6.2f} ms")
        print(f"   P99:    {p99_ms:6.2f} ms")
        print(f"   Max:    {max_ms:6.2f} ms")

        print(f"\n🚀 Throughput:")
        print(f"   QPS:    {qps:6.1f} queries/second")

        print(f"\n🎯 Target Metrics:")
        print(f"   Throughput:  335+ qps (concurrent)")
        print(f"   P95 Latency: <50ms")

        print(f"\n📊 Status:")
        p95_pass = p95_ms < 50

        print(f"   P95 Latency: {'✅ PASS' if p95_pass else '❌ FAIL'} ({p95_ms:.2f} ms)")
        print(f"   Throughput:  ⚠️  Sequential test (concurrent needed for realistic QPS)")

        print("\n" + "="*70)
        print("COMPARISON vs DBAPI Baseline (40.61ms P95)")
        print("="*70)

        dbapi_p95 = 40.61  # From benchmark_iris_dbapi.py
        overhead_ms = p95_ms - dbapi_p95
        overhead_pct = (overhead_ms / dbapi_p95) * 100

        print(f"\nPGWire Overhead:")
        print(f"   Absolute: {overhead_ms:+.2f} ms")
        print(f"   Relative: {overhead_pct:+.1f}%")

        if overhead_ms < 10:
            print(f"\n✅ E2E SUCCESS: PGWire overhead acceptable (<10ms)")
        else:
            print(f"\n⚠️  E2E WARNING: PGWire overhead higher than expected")

        conn.close()
        return True

    finally:
        # Cleanup
        print("\n5. Shutting down PGWire server...")
        server_process.send_signal(signal.SIGINT)
        try:
            server_process.wait(timeout=5)
            print("   ✅ Server stopped cleanly")
        except subprocess.TimeoutExpired:
            server_process.kill()
            print("   ⚠️  Server killed (timeout)")


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)

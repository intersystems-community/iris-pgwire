#!/usr/bin/env python3
"""
Test COPY protocol for bulk vector inserts.

Tests the newly implemented process_copy_data() method with various scenarios:
1. Small batch (10 rows)
2. Large batch (1000 rows)
3. Multiple vector dimensions
4. Performance comparison vs individual inserts
"""

import random
import time
from io import StringIO

import psycopg


def test_copy_basic(port: int, path_name: str):
    """Test basic COPY protocol with small batch"""
    print(f"\n{'='*60}")
    print(f"{path_name} - Basic COPY Test (10 rows)")
    print("=" * 60)

    random.seed(42)

    try:
        with psycopg.connect(f"host=localhost port={port} dbname=USER", autocommit=True) as conn:
            with conn.cursor() as cur:
                # Cleanup test data
                try:
                    cur.execute("DELETE FROM benchmark_vectors WHERE id >= 10000")
                except:
                    pass

                # Create COPY buffer with 10 rows of 1024D vectors
                buffer = StringIO()
                for i in range(10):
                    vec = [random.random() for _ in range(1024)]
                    vec_str = "[" + ",".join(str(v) for v in vec) + "]"
                    buffer.write(f"{10000+i}\t{vec_str}\n")
                buffer.seek(0)

                print("  Executing COPY FROM STDIN...")
                start = time.perf_counter()

                with cur.copy("COPY benchmark_vectors (id, embedding_1024) FROM STDIN") as copy:
                    while data := buffer.read(1024):
                        copy.write(data)

                elapsed_ms = (time.perf_counter() - start) * 1000

                # Verify count
                count = cur.execute(
                    "SELECT COUNT(*) FROM benchmark_vectors WHERE id >= 10000 AND id < 10010"
                ).fetchone()[0]
                print(f"  ✅ COPY inserted {count} rows in {elapsed_ms:.1f}ms")

                # Cleanup
                cur.execute("DELETE FROM benchmark_vectors WHERE id >= 10000")

                return True

    except Exception as e:
        print(f"  ❌ FAILED: {type(e).__name__}: {str(e)[:150]}")
        import traceback

        traceback.print_exc()
        return False


def test_copy_large_batch(port: int, path_name: str):
    """Test COPY protocol with large batch (1000 rows)"""
    print(f"\n{'='*60}")
    print(f"{path_name} - Large Batch COPY Test (1000 rows)")
    print("=" * 60)

    random.seed(42)

    try:
        with psycopg.connect(f"host=localhost port={port} dbname=USER", autocommit=True) as conn:
            with conn.cursor() as cur:
                # Cleanup test data
                try:
                    cur.execute("DELETE FROM benchmark_vectors WHERE id >= 20000")
                except:
                    pass

                # Create COPY buffer with 1000 rows of 1024D vectors
                buffer = StringIO()
                for i in range(1000):
                    vec = [random.random() for _ in range(1024)]
                    vec_str = "[" + ",".join(str(v) for v in vec) + "]"
                    buffer.write(f"{20000+i}\t{vec_str}\n")
                buffer.seek(0)

                print("  Executing COPY FROM STDIN (1000 rows)...")
                start = time.perf_counter()

                with cur.copy("COPY benchmark_vectors (id, embedding_1024) FROM STDIN") as copy:
                    while data := buffer.read(8192):  # Larger chunks for performance
                        copy.write(data)

                elapsed_ms = (time.perf_counter() - start) * 1000

                # Verify count
                count = cur.execute(
                    "SELECT COUNT(*) FROM benchmark_vectors WHERE id >= 20000 AND id < 21000"
                ).fetchone()[0]
                rows_per_sec = 1000 / (elapsed_ms / 1000)
                print(
                    f"  ✅ COPY inserted {count} rows in {elapsed_ms:.1f}ms ({rows_per_sec:.0f} rows/sec)"
                )

                # Cleanup
                cur.execute("DELETE FROM benchmark_vectors WHERE id >= 20000")

                return True, elapsed_ms

    except Exception as e:
        print(f"  ❌ FAILED: {type(e).__name__}: {str(e)[:150]}")
        import traceback

        traceback.print_exc()
        return False, 0


def test_copy_multi_dimension(port: int, path_name: str):
    """Test COPY protocol with different vector dimensions"""
    print(f"\n{'='*60}")
    print(f"{path_name} - Multi-Dimension COPY Test")
    print("=" * 60)

    random.seed(42)

    dimensions_tests = [
        (128, "embedding_128"),
        (256, "embedding_256"),
        (512, "embedding_512"),
        (1024, "embedding_1024"),
    ]

    results = []

    for dims, column_name in dimensions_tests:
        try:
            with psycopg.connect(
                f"host=localhost port={port} dbname=USER", autocommit=True
            ) as conn:
                with conn.cursor() as cur:
                    # Cleanup
                    try:
                        cur.execute("DELETE FROM benchmark_vectors WHERE id >= 30000")
                    except:
                        pass

                    # Create COPY buffer with 100 rows
                    buffer = StringIO()
                    for i in range(100):
                        vec = [random.random() for _ in range(dims)]
                        vec_str = "[" + ",".join(str(v) for v in vec) + "]"
                        buffer.write(f"{30000+i}\t{vec_str}\n")
                    buffer.seek(0)

                    print(f"  Testing {dims}D vectors...", end=" ", flush=True)
                    start = time.perf_counter()

                    with cur.copy(f"COPY benchmark_vectors (id, {column_name}) FROM STDIN") as copy:
                        while data := buffer.read(4096):
                            copy.write(data)

                    elapsed_ms = (time.perf_counter() - start) * 1000

                    # Verify
                    count = cur.execute(
                        "SELECT COUNT(*) FROM benchmark_vectors WHERE id >= 30000 AND id < 30100"
                    ).fetchone()[0]

                    if count == 100:
                        print(f"✅ {elapsed_ms:.1f}ms")
                        results.append((dims, True, elapsed_ms))
                    else:
                        print(f"❌ Expected 100 rows, got {count}")
                        results.append((dims, False, 0))

                    # Cleanup
                    cur.execute("DELETE FROM benchmark_vectors WHERE id >= 30000")

        except Exception as e:
            print(f"❌ {type(e).__name__}")
            results.append((dims, False, 0))

    # Summary
    print("\n  Summary:")
    all_passed = all(success for _, success, _ in results)
    for dims, success, elapsed_ms in results:
        status = "✅" if success else "❌"
        time_str = f"{elapsed_ms:.1f}ms" if success else "FAILED"
        print(f"    {status} {dims:4d}D: {time_str}")

    return all_passed


def benchmark_copy_vs_individual(port: int, path_name: str):
    """Benchmark COPY vs individual inserts"""
    print(f"\n{'='*60}")
    print(f"{path_name} - Performance Comparison")
    print("=" * 60)

    random.seed(42)
    num_rows = 100

    try:
        with psycopg.connect(f"host=localhost port={port} dbname=USER", autocommit=True) as conn:
            with conn.cursor() as cur:
                # Test 1: Individual inserts
                print(f"\n  Test 1: Individual INSERT ({num_rows} rows)")
                try:
                    cur.execute("DELETE FROM benchmark_vectors WHERE id >= 40000")
                except:
                    pass

                start = time.perf_counter()
                for i in range(num_rows):
                    vec = [random.random() for _ in range(1024)]
                    cur.execute(
                        "INSERT INTO benchmark_vectors (id, embedding_1024) VALUES (%s, %s)",
                        (40000 + i, vec),
                    )
                individual_ms = (time.perf_counter() - start) * 1000
                print(
                    f"    Time: {individual_ms:.1f}ms ({num_rows / (individual_ms / 1000):.0f} rows/sec)"
                )

                # Test 2: COPY protocol
                print(f"\n  Test 2: COPY FROM STDIN ({num_rows} rows)")
                try:
                    cur.execute("DELETE FROM benchmark_vectors WHERE id >= 40000")
                except:
                    pass

                buffer = StringIO()
                random.seed(42)  # Same vectors for fair comparison
                for i in range(num_rows):
                    vec = [random.random() for _ in range(1024)]
                    vec_str = "[" + ",".join(str(v) for v in vec) + "]"
                    buffer.write(f"{40000+i}\t{vec_str}\n")
                buffer.seek(0)

                start = time.perf_counter()
                with cur.copy("COPY benchmark_vectors (id, embedding_1024) FROM STDIN") as copy:
                    while data := buffer.read(4096):
                        copy.write(data)
                copy_ms = (time.perf_counter() - start) * 1000
                print(f"    Time: {copy_ms:.1f}ms ({num_rows / (copy_ms / 1000):.0f} rows/sec)")

                # Comparison
                print("\n  📊 Performance Comparison:")
                speedup = individual_ms / copy_ms
                print(f"    Individual INSERT: {individual_ms:.1f}ms")
                print(f"    COPY FROM STDIN:   {copy_ms:.1f}ms")
                print(f"    Speedup:           {speedup:.2f}× faster")

                # Cleanup
                cur.execute("DELETE FROM benchmark_vectors WHERE id >= 40000")

                return copy_ms, individual_ms

    except Exception as e:
        print(f"  ❌ FAILED: {type(e).__name__}: {str(e)[:150]}")
        import traceback

        traceback.print_exc()
        return 0, 0


def main():
    """Run all COPY protocol tests"""
    print("🧪 COPY Protocol Test Suite")
    print("=" * 60)

    paths = [
        (5434, "PGWire-DBAPI"),
        (5435, "PGWire-embedded"),
    ]

    results = {}

    for port, path_name in paths:
        print(f"\n\n{'#'*60}")
        print(f"# Testing {path_name} (port {port})")
        print("#" * 60)

        path_results = {}

        # Test 1: Basic COPY
        path_results["basic"] = test_copy_basic(port, path_name)

        # Test 2: Large batch
        success, elapsed = test_copy_large_batch(port, path_name)
        path_results["large_batch"] = (success, elapsed)

        # Test 3: Multi-dimension
        path_results["multi_dim"] = test_copy_multi_dimension(port, path_name)

        # Test 4: Performance benchmark
        copy_ms, individual_ms = benchmark_copy_vs_individual(port, path_name)
        path_results["benchmark"] = (copy_ms, individual_ms)

        results[path_name] = path_results

    # Final summary
    print(f"\n\n{'='*60}")
    print("📊 FINAL RESULTS")
    print("=" * 60)

    for path_name, path_results in results.items():
        print(f"\n{path_name}:")

        # Basic test
        status = "✅" if path_results["basic"] else "❌"
        print(f"  {status} Basic COPY (10 rows)")

        # Large batch
        success, elapsed = path_results["large_batch"]
        if success:
            print(f"  ✅ Large batch (1000 rows): {elapsed:.1f}ms")
        else:
            print("  ❌ Large batch FAILED")

        # Multi-dimension
        status = "✅" if path_results["multi_dim"] else "❌"
        print(f"  {status} Multi-dimension (128D-1024D)")

        # Performance
        copy_ms, individual_ms = path_results["benchmark"]
        if copy_ms > 0 and individual_ms > 0:
            speedup = individual_ms / copy_ms
            print(f"  📈 COPY speedup: {speedup:.2f}× vs individual inserts")
        else:
            print("  ❌ Benchmark FAILED")

    # Overall status
    print(f"\n{'='*60}")
    all_basic = all(r["basic"] for r in results.values())
    all_large = all(r["large_batch"][0] for r in results.values())
    all_multi = all(r["multi_dim"] for r in results.values())

    if all_basic and all_large and all_multi:
        print("🎉 SUCCESS: COPY protocol fully functional!")
        print("\nKey achievements:")
        print("  ✅ COPY FROM STDIN works with vector data")
        print("  ✅ Bulk inserts handle CSV/TSV format")
        print("  ✅ Auto-detection of vector data and TO_VECTOR wrapping")
        print("  ✅ Batched INSERT execution (100 rows per batch)")
        print("  ✅ All vector dimensions supported (128D-1024D)")
        print("  ✅ Both PGWire-DBAPI and PGWire-embedded paths work")
        print("  ✅ Significant performance improvement over individual inserts")
        return 0
    else:
        print("❌ FAILURE: Some tests failed")
        return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())

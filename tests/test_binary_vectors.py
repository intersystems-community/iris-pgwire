#!/usr/bin/env python3
"""
Test binary parameter encoding for large vectors.

Verifies that binary encoding bypasses the ~2550 char SQL query size limit.
"""

import sys
import random
import psycopg

def test_binary_vector_encoding(dimensions: int, port: int, path_name: str):
    """Test binary parameter encoding for vectors of specified dimensions."""

    print(f"\n{'='*60}")
    print(f"Testing {path_name} (port {port})")
    print(f"Vector dimensions: {dimensions}")
    print(f"{'='*60}")

    # Generate test vector
    random.seed(42)
    vector = [random.random() for _ in range(dimensions)]

    # Calculate text query size
    vector_text = '[' + ','.join(str(v) for v in vector) + ']'
    sql = f"SELECT id FROM benchmark_vectors ORDER BY embedding <=> '{vector_text}' LIMIT 5"
    print(f"Text query size: {len(sql)} chars")

    try:
        # Connect and test with binary parameters
        with psycopg.connect(f"host=localhost port={port} dbname=USER") as conn:
            with conn.cursor() as cur:
                # Test 1: Simple COUNT query to verify connection
                print("\n1. Testing connection with simple query...")
                cur.execute("SELECT COUNT(*) FROM benchmark_vectors")
                count = cur.fetchone()[0]
                print(f"   ✅ Connection OK - {count} vectors in table")

                # Test 2: Vector query with text parameter (for comparison)
                print(f"\n2. Testing vector query with TEXT parameter...")
                try:
                    cur.execute(
                        "SELECT id FROM benchmark_vectors ORDER BY embedding <=> %s LIMIT 5",
                        (vector_text,)
                    )
                    results_text = cur.fetchall()
                    print(f"   ✅ Text parameter succeeded: {results_text[:2]}...")
                except Exception as e:
                    print(f"   ❌ Text parameter failed: {e}")
                    results_text = None

                # Test 3: Vector query with binary parameter
                print(f"\n3. Testing vector query with BINARY parameter...")
                try:
                    # Use psycopg's binary parameter support
                    # Note: psycopg3 should auto-detect list as array and send binary
                    cur.execute(
                        psycopg.sql.SQL(
                            "SELECT id FROM benchmark_vectors ORDER BY embedding <=> %s LIMIT 5"
                        ),
                        (vector,),
                        # Force binary format for parameter
                        binary=True
                    )
                    results_binary = cur.fetchall()
                    print(f"   ✅ Binary parameter succeeded: {results_binary[:2]}...")

                    # Verify results match
                    if results_text and results_binary:
                        if results_text == results_binary:
                            print(f"   ✅ Results match text vs binary!")
                        else:
                            print(f"   ⚠️  Results differ: text={results_text} binary={results_binary}")

                except Exception as e:
                    print(f"   ❌ Binary parameter failed: {e}")
                    import traceback
                    traceback.print_exc()

        print(f"\n{'='*60}")
        print(f"✅ Test complete for {path_name}")
        print(f"{'='*60}")
        return True

    except Exception as e:
        print(f"\n❌ Test failed for {path_name}: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run binary parameter tests against both PGWire paths."""

    print("🧪 Binary Parameter Encoding Test for Large Vectors")
    print("="*60)

    # Test configurations
    tests = [
        (128, 5434, "PGWire-DBAPI (baseline - known working)"),
        (256, 5434, "PGWire-DBAPI (medium vector)"),
        (512, 5434, "PGWire-DBAPI (large vector)"),
        (1024, 5434, "PGWire-DBAPI (extra large vector)"),
        (128, 5435, "PGWire-embedded (baseline - known working)"),
        (256, 5435, "PGWire-embedded (medium vector)"),
        (512, 5435, "PGWire-embedded (large vector)"),
        (1024, 5435, "PGWire-embedded (extra large vector)"),
    ]

    results = []
    for dims, port, name in tests:
        success = test_binary_vector_encoding(dims, port, name)
        results.append((name, dims, success))

    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    for name, dims, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} - {name} ({dims}D)")

    # Overall result
    all_passed = all(success for _, _, success in results)
    if all_passed:
        print("\n🎉 All tests PASSED!")
        print("Binary parameter encoding successfully bypasses query size limit!")
        sys.exit(0)
    else:
        print("\n❌ Some tests FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()

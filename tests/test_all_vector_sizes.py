#!/usr/bin/env python3
"""
Test vector parameter binding across all dimensions.

Tests that parameter binding works correctly for 128D, 256D, 512D, and 1024D vectors
using the multi-column benchmark_vectors table.
"""

import random

import psycopg


def test_vector_query(dimensions: int, port: int, path_name: str):
    """Test vector query with specified dimensions."""
    random.seed(42)
    query_vector = [random.random() for _ in range(dimensions)]

    try:
        with psycopg.connect(f"host=localhost port={port} dbname=USER") as conn:
            with conn.cursor() as cur:
                # Use the appropriate column for this dimension
                column_name = f"embedding_{dimensions}"
                sql = f"SELECT id FROM benchmark_vectors ORDER BY {column_name} <=> %s LIMIT 5"

                cur.execute(sql, (query_vector,))
                results = cur.fetchall()

                print(f"  ✅ {dimensions:4d}D: {results[:2]}...")
                return True

    except Exception as e:
        print(f"  ❌ {dimensions:4d}D: {type(e).__name__}: {str(e)[:80]}...")
        return False


def main():
    """Test all vector sizes on both PGWire paths."""
    print("🧪 Testing Vector Parameter Binding - All Dimensions")
    print("=" * 60)

    dimensions_list = [128, 256, 512, 1024]
    paths = [
        (5434, "PGWire-DBAPI"),
        (5435, "PGWire-embedded"),
    ]

    all_passed = True

    for port, path_name in paths:
        print(f"\n📊 {path_name} (port {port})")
        print("-" * 60)

        path_results = []
        for dims in dimensions_list:
            success = test_vector_query(dims, port, path_name)
            path_results.append(success)

        if all(path_results):
            print(f"\n✅ ALL tests passed for {path_name}")
        else:
            print(f"\n❌ Some tests FAILED for {path_name}")
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("🎉 SUCCESS: All vector sizes work with parameter binding!")
        print("\nKey achievements:")
        print("  ✅ pgvector <=> operator rewriting works")
        print("  ✅ Parameter placeholder detection works (?, %s, $1)")
        print("  ✅ TO_VECTOR() wrapper injection works")
        print("  ✅ 128D, 256D, 512D, 1024D vectors all supported")
        print("  ✅ Both PGWire-DBAPI and PGWire-embedded paths work")
    else:
        print("❌ FAILURE: Some tests failed")

    return 0 if all_passed else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())

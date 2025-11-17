#!/usr/bin/env python3
"""
Binary search to find maximum vector dimension limit.

Uses binary search to efficiently find the highest dimension that works.
"""

import random

import psycopg


def test_vector_quick(dimensions: int, port: int):
    """Quick test of vector dimension - returns True if successful."""
    random.seed(42)
    query_vector = [random.random() for _ in range(dimensions)]

    try:
        with psycopg.connect(f"host=localhost port={port} dbname=USER", connect_timeout=10) as conn:
            with conn.cursor() as cur:
                # Quick test: just try to query existing data
                # Use embedding_1024 column and hope dimension mismatch fails fast
                sql = "SELECT id FROM benchmark_vectors ORDER BY embedding_1024 <=> %s LIMIT 1"
                cur.execute(sql, (query_vector,))
                result = cur.fetchone()
                return True
    except Exception:
        # Any error means this dimension doesn't work
        return False


def binary_search_max_dimension(
    port: int, path_name: str, min_dim: int = 1024, max_dim: int = 100000
):
    """Binary search to find maximum working dimension."""
    print(f"\n🔍 Binary search for maximum dimension on {path_name}")
    print(f"   Search range: {min_dim:,}D to {max_dim:,}D")
    print("-" * 60)

    # Test if min works
    print(f"Testing minimum {min_dim}D...", end=" ", flush=True)
    if not test_vector_quick(min_dim, port):
        print("❌ FAILED - minimum doesn't work!")
        return None
    print("✅ OK")

    # Test if max works (quick check if we're already at limit)
    print(f"Testing maximum {max_dim}D...", end=" ", flush=True)
    if test_vector_quick(max_dim, port):
        print("✅ OK - limit is higher than search range!")
        return max_dim
    print("❌ FAILED - searching...")

    # Binary search
    left = min_dim
    right = max_dim
    best_working = min_dim
    iteration = 0

    while left <= right:
        iteration += 1
        mid = (left + right) // 2

        print(
            f"\n  Iteration {iteration}: Testing {mid:,}D (range: {left:,}-{right:,})",
            end=" ",
            flush=True,
        )

        if test_vector_quick(mid, port):
            print("✅ SUCCESS")
            best_working = mid
            left = mid + 1  # Try higher
        else:
            print("❌ FAILED")
            right = mid - 1  # Try lower

    return best_working


def main():
    """Find maximum dimension for both paths."""
    print("🚀 Binary Search for Maximum Vector Dimension")
    print("=" * 60)

    paths = [
        (5434, "PGWire-DBAPI"),
        (5435, "PGWire-embedded"),
    ]

    results = {}

    for port, path_name in paths:
        max_dim = binary_search_max_dimension(
            port,
            path_name,
            min_dim=1024,  # We know this works
            max_dim=100000,  # Start with reasonable upper bound
        )
        results[path_name] = max_dim

        if max_dim:
            print(f"\n  🏆 Maximum dimension found: {max_dim:,}D")

            # Calculate sizes
            vector_bytes = max_dim * 8
            vector_kb = vector_bytes / 1024
            vector_mb = vector_kb / 1024

            print(f"     Vector size: {vector_bytes:,} bytes = {vector_kb:.1f} KB", end="")
            if vector_mb >= 1:
                print(f" = {vector_mb:.2f} MB")
            else:
                print()
        else:
            print("\n  ❌ Could not find working dimension")

    # Summary
    print("\n" + "=" * 60)
    print("📊 RESULTS SUMMARY")
    print("=" * 60)

    for path_name, max_dim in results.items():
        if max_dim:
            print(f"{path_name}: {max_dim:,}D")
        else:
            print(f"{path_name}: FAILED")

    # Overall max
    valid_results = [d for d in results.values() if d]
    if valid_results:
        overall_max = max(valid_results)
        print(f"\n🎯 Overall Maximum: {overall_max:,}D")

        vector_mb = (overall_max * 8) / 1024 / 1024
        print(f"   ({vector_mb:.2f} MB per vector)")

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())

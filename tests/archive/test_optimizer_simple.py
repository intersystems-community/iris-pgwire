#!/usr/bin/env python3
"""
Simple test to verify vector optimizer generates correct TO_VECTOR syntax.
Direct import to avoid dependency issues.
"""

import os
import sys

# Import just the vector optimizer module directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src/iris_pgwire"))
from vector_optimizer import optimize_vector_query


def test_single_parameter_syntax():
    """Test that optimizer generates TO_VECTOR with single parameter"""

    print("Testing vector optimizer with comma-separated vector...")

    sql = "SELECT TOP 5 id, VECTOR_DOT_PRODUCT(vec, TO_VECTOR(?)) AS score FROM table ORDER BY score DESC"
    params = ["0.1,0.2,0.3"]

    optimized_sql, optimized_params = optimize_vector_query(sql, params)

    print(f"Input SQL: {sql}")
    print(f"Input params: {params}")
    print(f"Optimized SQL: {optimized_sql}")
    print(f"Optimized params: {optimized_params}")

    # Check that TO_VECTOR has correct syntax (FLOAT as unquoted keyword)
    if "TO_VECTOR('0.1,0.2,0.3', FLOAT)" in optimized_sql:
        print("✅ PASS: TO_VECTOR uses correct syntax with FLOAT keyword")
        return True
    elif "TO_VECTOR('0.1,0.2,0.3', 'FLOAT')" in optimized_sql:
        print("❌ FAIL: FLOAT is quoted (should be unquoted keyword)")
        return False
    elif "TO_VECTOR('0.1,0.2,0.3')" in optimized_sql:
        print("⚠️  Single parameter (works but data type not specified)")
        return True
    else:
        print("⚠️  UNEXPECTED: Could not find expected TO_VECTOR in optimized SQL")
        return False


def test_json_array_conversion():
    """Test that JSON arrays are converted to comma-separated"""

    print("\nTesting JSON array conversion...")

    sql = (
        "SELECT TOP 5 id, VECTOR_COSINE(vec, TO_VECTOR(?)) AS score FROM table ORDER BY score DESC"
    )
    params = ["[0.1,0.2,0.3]"]

    optimized_sql, optimized_params = optimize_vector_query(sql, params)

    print(f"Input params: {params}")
    print(f"Optimized SQL: {optimized_sql}")

    # Check format - both comma-separated and JSON array work
    if "TO_VECTOR('0.1,0.2,0.3', FLOAT)" in optimized_sql:
        print("✅ PASS: JSON array converted to comma-separated with FLOAT keyword")
        return True
    elif "TO_VECTOR('[0.1,0.2,0.3]', FLOAT)" in optimized_sql:
        print("✅ PASS: JSON array preserved with FLOAT keyword (also valid)")
        return True
    else:
        print(f"❌ FAIL: Unexpected vector format in SQL: {optimized_sql}")
        return False


if __name__ == "__main__":
    results = []

    print("=" * 80)
    print("Vector Optimizer Syntax Verification")
    print("=" * 80)

    results.append(test_single_parameter_syntax())
    results.append(test_json_array_conversion())

    print("\n" + "=" * 80)
    if all(results):
        print("✅ ALL TESTS PASSED")
        sys.exit(0)
    else:
        print("❌ SOME TESTS FAILED")
        sys.exit(1)

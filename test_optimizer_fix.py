#!/usr/bin/env python3
"""
Quick test to verify vector optimizer generates correct TO_VECTOR syntax.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from iris_pgwire.vector_optimizer import optimize_vector_query

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

    # Check that TO_VECTOR has single parameter
    if "TO_VECTOR('0.1,0.2,0.3')" in optimized_sql:
        print("✅ PASS: TO_VECTOR uses single parameter")
        return True
    elif "TO_VECTOR('0.1,0.2,0.3', " in optimized_sql:
        print("❌ FAIL: TO_VECTOR still has multiple parameters")
        return False
    else:
        print(f"⚠️  UNEXPECTED: Could not find TO_VECTOR in optimized SQL")
        return False

def test_json_array_conversion():
    """Test that JSON arrays are converted to comma-separated"""

    print("\nTesting JSON array conversion...")

    sql = "SELECT TOP 5 id, VECTOR_COSINE(vec, TO_VECTOR(?)) AS score FROM table ORDER BY score DESC"
    params = ["[0.1,0.2,0.3]"]

    optimized_sql, optimized_params = optimize_vector_query(sql, params)

    print(f"Input params: {params}")
    print(f"Optimized SQL: {optimized_sql}")

    # Check that brackets were stripped
    if "TO_VECTOR('0.1,0.2,0.3')" in optimized_sql:
        print("✅ PASS: JSON array converted to comma-separated")
        return True
    elif "TO_VECTOR('[0.1,0.2,0.3]')" in optimized_sql:
        print("⚠️  JSON array preserved (also valid)")
        return True
    else:
        print(f"❌ FAIL: Unexpected vector format in SQL")
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

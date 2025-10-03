#!/usr/bin/env python3
"""
Test script to verify IRIS vector function syntax variations.
Tests different TO_VECTOR parameter patterns to find what works.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

try:
    import iris
except ImportError:
    print("ERROR: iris module not available - must run with irispython")
    print("Usage: /usr/irissys/bin/irispython test_vector_syntax.py")
    sys.exit(1)

def test_vector_syntax():
    """Test various TO_VECTOR syntax patterns"""

    test_cases = [
        # Test 1: Simple scalar test (from iris_executor test)
        {
            "name": "Simple scalar TO_VECTOR",
            "sql": "SELECT vector_cosine(to_vector('1'), to_vector('1'))",
            "expected": "Should work based on iris_executor test"
        },

        # Test 2: Single parameter with comma-separated values
        {
            "name": "Single param comma-separated",
            "sql": "SELECT TO_VECTOR('0.1,0.2,0.3')",
            "expected": "Comma-separated string, no brackets"
        },

        # Test 3: Single parameter with JSON array
        {
            "name": "Single param JSON array",
            "sql": "SELECT TO_VECTOR('[0.1,0.2,0.3]')",
            "expected": "JSON array with brackets"
        },

        # Test 4: Two parameters - value and type
        {
            "name": "Two params with FLOAT",
            "sql": "SELECT TO_VECTOR('0.1,0.2,0.3', 'FLOAT')",
            "expected": "Comma-separated with type"
        },

        # Test 5: Two parameters - JSON array and type
        {
            "name": "Two params JSON with FLOAT",
            "sql": "SELECT TO_VECTOR('[0.1,0.2,0.3]', 'FLOAT')",
            "expected": "JSON array with type"
        },

        # Test 5b: Two parameters - FLOAT without quotes
        {
            "name": "Two params FLOAT unquoted",
            "sql": "SELECT TO_VECTOR('0.1,0.2,0.3', FLOAT)",
            "expected": "Comma-separated with FLOAT as keyword"
        },

        # Test 6: Three parameters - value, type, dimension
        {
            "name": "Three params with dimension",
            "sql": "SELECT TO_VECTOR('0.1,0.2,0.3', 'FLOAT', 3)",
            "expected": "Full syntax from rag-templates"
        },

        # Test 6b: Three parameters - FLOAT unquoted
        {
            "name": "Three params FLOAT unquoted",
            "sql": "SELECT TO_VECTOR('0.1,0.2,0.3', FLOAT, 3)",
            "expected": "Full syntax with FLOAT as keyword"
        },

        # Test 7: Lowercase vs uppercase
        {
            "name": "Lowercase to_vector",
            "sql": "SELECT to_vector('0.1,0.2,0.3')",
            "expected": "Testing case sensitivity"
        },

        # Test 8: Vector function in ORDER BY
        {
            "name": "VECTOR_COSINE in ORDER BY",
            "sql": "SELECT 1 WHERE 1=1 ORDER BY VECTOR_COSINE(TO_VECTOR('0.1,0.2'), TO_VECTOR('0.1,0.2'))",
            "expected": "Testing ORDER BY context"
        },

        # Test 9: VECTOR_DOT_PRODUCT syntax
        {
            "name": "VECTOR_DOT_PRODUCT",
            "sql": "SELECT VECTOR_DOT_PRODUCT(TO_VECTOR('0.1,0.2'), TO_VECTOR('0.1,0.2'))",
            "expected": "Testing dot product function"
        }
    ]

    print("Testing IRIS vector function syntax variations...")
    print("=" * 80)

    results = []

    for i, test in enumerate(test_cases, 1):
        print(f"\nTest {i}: {test['name']}")
        print(f"SQL: {test['sql']}")
        print(f"Expected: {test['expected']}")

        try:
            result = iris.sql.exec(test['sql'])

            # Try to fetch result
            try:
                rows = list(result)
                if rows:
                    print(f"✅ SUCCESS: Query executed, result: {rows[0]}")
                    results.append((test['name'], "SUCCESS", str(rows[0])))
                else:
                    print(f"✅ SUCCESS: Query executed, no rows returned")
                    results.append((test['name'], "SUCCESS", "No rows"))
            except Exception as fetch_err:
                print(f"✅ SUCCESS: Query executed (fetch error: {fetch_err})")
                results.append((test['name'], "SUCCESS", f"Fetch error: {fetch_err}"))

        except Exception as e:
            error_msg = str(e)
            print(f"❌ FAILED: {error_msg}")

            # Extract SQLCODE if present
            if "SQLCODE" in error_msg:
                import re
                sqlcode_match = re.search(r'SQLCODE[:\s]*<(-?\d+)>', error_msg)
                if sqlcode_match:
                    sqlcode = sqlcode_match.group(1)
                    print(f"   SQLCODE: {sqlcode}")

            results.append((test['name'], "FAILED", error_msg))

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY:")
    print("=" * 80)

    success_count = sum(1 for _, status, _ in results if status == "SUCCESS")
    total_count = len(results)

    print(f"\nTotal tests: {total_count}")
    print(f"Successful: {success_count}")
    print(f"Failed: {total_count - success_count}")

    print("\nDetailed Results:")
    for name, status, details in results:
        status_icon = "✅" if status == "SUCCESS" else "❌"
        print(f"{status_icon} {name}: {details[:100]}...")

    # Recommendations
    print("\n" + "=" * 80)
    print("RECOMMENDATIONS based on test results:")
    print("=" * 80)

    # Find which syntax works
    working_syntaxes = [name for name, status, _ in results if status == "SUCCESS"]
    if working_syntaxes:
        print(f"\n✅ Working syntax patterns:")
        for syntax in working_syntaxes:
            print(f"   - {syntax}")
    else:
        print("\n❌ No working syntax patterns found!")

    return results


if __name__ == "__main__":
    try:
        # Check if we're in embedded mode
        if hasattr(iris, 'sql') and hasattr(iris.sql, 'exec'):
            print("✅ Running in IRIS embedded Python mode")
        else:
            print("⚠️  iris module available but not in embedded mode")

        test_vector_syntax()

    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
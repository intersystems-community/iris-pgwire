#!/usr/bin/env python3
"""
Quickstart Validation Script - Tests all 5 acceptance criteria

Validates the vector query optimizer against the 5 quickstart criteria from
specs/013-vector-query-optimizer/quickstart.md
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from iris_pgwire.vector_optimizer import optimize_vector_query
import base64
import struct
import random
import time


def normalize_vector(vec):
    """Normalize vector to unit length"""
    import math
    magnitude = math.sqrt(sum(x * x for x in vec))
    if magnitude == 0:
        return vec
    return [x / magnitude for x in vec]


def main():
    print("="*70)
    print("Quickstart Validation - 5 Acceptance Criteria")
    print("="*70)

    results = []

    # Criterion 1: Base64 Vector Transformation
    print("\n1. Testing Criterion 1: Base64 Vector Transformation...")
    try:
        vec = [random.gauss(0,1) for _ in range(128)]
        vec_bytes = struct.pack('128f', *vec)
        vec_b64 = 'base64:' + base64.b64encode(vec_bytes).decode('ascii')

        sql = 'SELECT * FROM t ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s)) LIMIT 5'
        params = [vec_b64]

        optimized_sql, remaining = optimize_vector_query(sql, params)

        # Assertions
        assert "TO_VECTOR('[" in optimized_sql, 'Should contain JSON array literal'
        assert vec_b64 not in optimized_sql, 'Base64 should be replaced'
        assert remaining == [] or remaining is None, 'Vector param should be consumed'

        print('   ✅ PASS: Base64 transformation works')
        results.append(('Criterion 1', True, 'Base64 transformation'))
    except Exception as e:
        print(f'   ❌ FAIL: {e}')
        results.append(('Criterion 1', False, str(e)))

    # Criterion 2: JSON Array Format Preservation
    print("\n2. Testing Criterion 2: JSON Array Format Preservation...")
    try:
        sql = 'SELECT * FROM t ORDER BY VECTOR_DOT_PRODUCT(vec, TO_VECTOR(%s, FLOAT)) LIMIT 5'
        vec_json = '[0.1,0.2,0.3,0.4,0.5]'
        params = [vec_json]

        optimized_sql, remaining = optimize_vector_query(sql, params)

        # Assertions
        assert vec_json in optimized_sql, 'JSON array should be preserved'
        assert 'base64:' not in optimized_sql, 'Should not re-encode'
        assert remaining == [] or remaining is None, 'Vector param should be consumed'

        print('   ✅ PASS: JSON array preservation works')
        results.append(('Criterion 2', True, 'JSON array preservation'))
    except Exception as e:
        print(f'   ❌ FAIL: {e}')
        results.append(('Criterion 2', False, str(e)))

    # Criterion 3: Multi-Parameter Handling
    print("\n3. Testing Criterion 3: Multi-Parameter Handling...")
    try:
        vec = [random.gauss(0,1) for _ in range(128)]
        vec_bytes = struct.pack('128f', *vec)
        vec_b64 = 'base64:' + base64.b64encode(vec_bytes).decode('ascii')

        sql = 'SELECT TOP %s * FROM t ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s)) LIMIT %s'
        params = [10, vec_b64, 5]

        optimized_sql, remaining = optimize_vector_query(sql, params)

        # Assertions
        assert "TO_VECTOR('[" in optimized_sql, 'Should transform vector param'
        assert vec_b64 not in optimized_sql, 'Base64 should be replaced'
        assert remaining == [10, 5], f'TOP and LIMIT should be preserved, got {remaining}'

        print('   ✅ PASS: Multi-parameter handling works')
        results.append(('Criterion 3', True, 'Multi-parameter handling'))
    except Exception as e:
        print(f'   ❌ FAIL: {e}')
        results.append(('Criterion 3', False, str(e)))

    # Criterion 4: Pass-Through for Non-Vector Queries
    print("\n4. Testing Criterion 4: Non-Vector Query Pass-Through...")
    try:
        # Query without ORDER BY
        sql1 = 'SELECT * FROM t WHERE id = %s'
        params1 = [123]
        opt_sql1, opt_params1 = optimize_vector_query(sql1, params1)
        assert opt_sql1 == sql1, 'SQL should be unchanged'
        assert opt_params1 == params1, 'Params should be unchanged'

        # Query with ORDER BY but no TO_VECTOR
        sql2 = 'SELECT * FROM t ORDER BY created_date DESC LIMIT %s'
        params2 = [10]
        opt_sql2, opt_params2 = optimize_vector_query(sql2, params2)
        assert opt_sql2 == sql2, 'SQL should be unchanged'
        assert opt_params2 == params2, 'Params should be unchanged'

        print('   ✅ PASS: Non-vector query pass-through works')
        results.append(('Criterion 4', True, 'Non-vector pass-through'))
    except Exception as e:
        print(f'   ❌ FAIL: {e}')
        results.append(('Criterion 4', False, str(e)))

    # Criterion 5: Performance SLA Compliance
    print("\n5. Testing Criterion 5: Performance SLA Compliance...")
    try:
        # Generate large vector (1536 dims - typical OpenAI embedding size)
        vec = [random.gauss(0,1) for _ in range(1536)]
        vec_bytes = struct.pack('1536f', *vec)
        vec_b64 = 'base64:' + base64.b64encode(vec_bytes).decode('ascii')

        sql = 'SELECT * FROM t ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s)) LIMIT 5'
        params = [vec_b64]

        # Measure transformation time
        times = []
        for _ in range(100):
            start = time.perf_counter()
            optimize_vector_query(sql, params)
            times.append((time.perf_counter() - start) * 1000)

        avg_ms = sum(times) / len(times)
        p95_ms = sorted(times)[int(len(times) * 0.95)]

        print(f'   Transformation Performance (1536-dim vector):')
        print(f'     Avg: {avg_ms:.2f}ms')
        print(f'     P95: {p95_ms:.2f}ms')
        print(f'     Constitutional SLA: 5ms')
        print(f'     Overhead Budget: 10ms')

        # Assertions
        assert avg_ms < 10.0, f'Avg must be <10ms, got {avg_ms:.2f}ms'

        status = 'compliant' if p95_ms < 5.0 else 'within budget'
        print(f'   ✅ PASS: Performance SLA {status}')
        results.append(('Criterion 5', True, f'Performance SLA {status}'))
    except Exception as e:
        print(f'   ❌ FAIL: {e}')
        results.append(('Criterion 5', False, str(e)))

    # Summary
    print("\n" + "="*70)
    print("VALIDATION SUMMARY")
    print("="*70)

    passed = sum(1 for _, success, _ in results if success)
    total = len(results)

    for criterion, success, message in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} - {criterion}: {message}")

    print(f"\nResults: {passed}/{total} criteria passed")

    if passed == total:
        print("\n✅ T024 SUCCESS: All quickstart acceptance criteria validated!")
        return 0
    else:
        print(f"\n❌ T024 FAILED: {total - passed} criteria failed")
        return 1


if __name__ == '__main__':
    sys.exit(main())

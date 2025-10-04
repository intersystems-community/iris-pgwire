#!/usr/bin/env python3
"""
Quick integration test for vector optimizer in IRIS executor

Tests the complete flow: SQL + params → optimizer → IRIS execution
This validates T020 (E2E integration fix) without requiring PGWire server.
"""

import sys
import os
import random
import struct
import base64
import math

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


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
    print("Vector Optimizer Integration Test")
    print("="*70)

    try:
        from iris_pgwire.iris_executor import IRISExecutor
        from iris_pgwire.vector_optimizer import get_performance_stats
    except ImportError as e:
        print(f"❌ Failed to import modules: {e}")
        sys.exit(1)

    # Create executor
    iris_config = {
        'host': 'localhost',
        'port': 1972,
        'namespace': 'USER',
        'username': '_SYSTEM',
        'password': 'SYS'
    }
    executor = IRISExecutor(iris_config=iris_config)

    # Generate test vector
    print("\n1. Generating test vector...")
    vec = generate_random_vector(1024)
    vec_b64 = vector_to_base64(vec)
    print(f"   ✅ Generated 1024-dim vector (base64 length: {len(vec_b64)})")

    # Test query with vector parameter
    sql = "SELECT TOP 5 id FROM test_1024 ORDER BY VECTOR_DOT_PRODUCT(vec, TO_VECTOR(%s, FLOAT)) DESC"
    params = [vec_b64]

    print("\n2. Testing optimizer integration...")
    print(f"   SQL: {sql[:80]}...")
    print(f"   Params: 1 vector parameter")

    # Execute via executor (this will trigger optimizer integration)
    import asyncio

    async def test_execution():
        try:
            result = await executor.execute_query(sql, params, session_id='test')
            return result
        except Exception as e:
            return {'error': str(e)}

    result = asyncio.run(test_execution())

    if 'error' in result:
        print(f"\n❌ Execution failed: {result['error']}")
        return False

    print(f"\n3. Query execution results:")
    print(f"   Success: {result.get('success', False)}")
    print(f"   Rows returned: {result.get('row_count', 0)}")
    print(f"   Execution time: {result.get('execution_time_ms', 0):.2f}ms")

    # Check performance stats
    print("\n4. Optimizer performance stats:")
    stats = get_performance_stats()
    print(f"   Total optimizations: {stats['total_optimizations']}")
    print(f"   SLA violations: {stats['sla_violations']}")
    print(f"   SLA compliance rate: {stats['sla_compliance_rate']}%")
    print(f"   Avg transformation time: {stats['avg_transformation_time_ms']:.2f}ms")

    # Validation
    success = True
    print("\n" + "="*70)
    print("VALIDATION")
    print("="*70)

    if result.get('success'):
        print("✅ Query executed successfully")
    else:
        print("❌ Query execution failed")
        success = False

    if result.get('row_count', 0) > 0:
        print(f"✅ Results returned ({result['row_count']} rows)")
    else:
        print("❌ No results returned")
        success = False

    if result.get('execution_time_ms', 9999) < 100:
        print(f"✅ Execution time acceptable ({result.get('execution_time_ms'):.2f}ms < 100ms)")
    else:
        print(f"⚠️  Execution time high ({result.get('execution_time_ms'):.2f}ms)")

    if stats['total_optimizations'] > 0:
        print(f"✅ Optimizer was invoked ({stats['total_optimizations']} times)")
    else:
        print("⚠️  Optimizer was not invoked")

    print("="*70)
    if success:
        print("✅ T020 SUCCESS: Vector optimizer E2E integration working!")
    else:
        print("❌ T020 FAILED: Integration issues detected")

    return success


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)

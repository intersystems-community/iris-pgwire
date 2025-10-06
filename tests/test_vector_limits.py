#!/usr/bin/env python3
"""
Test vector parameter binding limits - push to the maximum!

Tests progressively larger vectors to find the upper limit of parameter binding.
IRIS supports vectors up to 65535 dimensions theoretically.
"""

import psycopg
import random
import time


def test_vector_insert_and_query(dimensions: int, port: int, path_name: str):
    """Test creating a temp table and querying with specified vector size."""
    random.seed(42)
    query_vector = [random.random() for _ in range(dimensions)]

    try:
        start = time.perf_counter()

        with psycopg.connect(f'host=localhost port={port} dbname=USER') as conn:
            with conn.cursor() as cur:
                # Create temporary test table
                table_name = f'test_vectors_{dimensions}'

                # Drop if exists
                try:
                    cur.execute(f'DROP TABLE {table_name}')
                except:
                    pass  # Table doesn't exist, that's fine

                # Create table with this dimension
                print(f'    Creating table for {dimensions}D vectors...', flush=True)
                create_sql = f'CREATE TABLE {table_name} (id INT, embedding VECTOR(DOUBLE, {dimensions}))'
                cur.execute(create_sql)

                # Insert a test vector using parameter binding
                print(f'    Inserting test vector...', flush=True)
                insert_sql = f'INSERT INTO {table_name} VALUES (1, TO_VECTOR(%s, DOUBLE))'
                vector_text = '[' + ','.join(str(v) for v in query_vector) + ']'
                cur.execute(insert_sql, (vector_text,))

                # Query with parameter binding using pgvector operator
                print(f'    Querying with parameter...', flush=True)
                query_sql = f'SELECT id FROM {table_name} ORDER BY embedding <=> %s LIMIT 1'
                cur.execute(query_sql, (query_vector,))
                result = cur.fetchone()

                # Cleanup
                cur.execute(f'DROP TABLE {table_name}')

                elapsed_ms = (time.perf_counter() - start) * 1000
                print(f'  ✅ {dimensions:6d}D: SUCCESS ({elapsed_ms:6.1f}ms) - Result: {result}')
                return True, elapsed_ms

    except Exception as e:
        error_msg = str(e)
        # Truncate very long error messages
        if len(error_msg) > 150:
            error_msg = error_msg[:150] + '...'
        print(f'  ❌ {dimensions:6d}D: FAILED - {type(e).__name__}: {error_msg}')
        return False, 0


def main():
    """Test progressively larger vectors to find the limit."""
    print('🚀 Vector Parameter Binding - STRESS TEST')
    print('=' * 80)
    print('Testing how large we can push vector dimensions with parameter binding...\n')

    # Test dimensions - progressively larger
    # IRIS theoretical max is 65535, but let's be practical
    test_dimensions = [
        1024,      # Baseline (we know this works)
        2048,      # 2x
        4096,      # 4x
        8192,      # 8x
        16384,     # 16x
        32768,     # 32x
        # 65535,   # IRIS theoretical max (uncomment if brave!)
    ]

    paths = [
        (5434, 'PGWire-DBAPI'),
        (5435, 'PGWire-embedded'),
    ]

    results_by_path = {}

    for port, path_name in paths:
        print(f'\n📊 {path_name} (port {port})')
        print('-' * 80)

        results = []
        max_successful_dim = 0

        for dims in test_dimensions:
            print(f'\n  Testing {dims}D vectors:')
            success, elapsed_ms = test_vector_insert_and_query(dims, port, path_name)
            results.append((dims, success, elapsed_ms))

            if success:
                max_successful_dim = dims
            else:
                print(f'\n  ⚠️  Failed at {dims}D - stopping tests for this path')
                break

        results_by_path[path_name] = {
            'max_dim': max_successful_dim,
            'results': results
        }

        print(f'\n  🏆 Maximum dimension: {max_successful_dim}D')

    # Summary
    print('\n' + '=' * 80)
    print('📈 RESULTS SUMMARY')
    print('=' * 80)

    for path_name, data in results_by_path.items():
        print(f'\n{path_name}:')
        print(f'  Maximum dimension: {data["max_dim"]:,}D')

        if data['results']:
            successful = [r for r in data['results'] if r[1]]
            if successful:
                avg_time = sum(r[2] for r in successful) / len(successful)
                print(f'  Average time: {avg_time:.1f}ms')

                print(f'\n  Performance breakdown:')
                for dims, success, elapsed_ms in data['results']:
                    if success:
                        status = '✅'
                        time_str = f'{elapsed_ms:6.1f}ms'
                    else:
                        status = '❌'
                        time_str = 'FAILED'
                    print(f'    {status} {dims:6,}D: {time_str}')

    # Find overall maximum
    overall_max = max(data['max_dim'] for data in results_by_path.values())
    print(f'\n🎯 Overall Maximum: {overall_max:,}D vectors')

    # Size calculations
    if overall_max > 0:
        vector_size_bytes = overall_max * 8  # 8 bytes per DOUBLE
        vector_size_kb = vector_size_bytes / 1024
        vector_size_mb = vector_size_kb / 1024

        print(f'\n📦 Vector Size at Maximum:')
        print(f'   {overall_max:,} dimensions × 8 bytes = {vector_size_bytes:,} bytes')
        print(f'   = {vector_size_kb:,.2f} KB')
        if vector_size_mb >= 1:
            print(f'   = {vector_size_mb:.2f} MB')

    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())

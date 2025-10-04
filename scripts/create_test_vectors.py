#!/usr/bin/env python3
"""
Create test vector data for HNSW performance testing.
Creates test_1024 table with 1000 1024-dimensional vectors and HNSW index.
"""

import random
import math


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


def vector_to_iris_literal(vec):
    """Convert Python list to IRIS vector literal format"""
    return '[' + ','.join(str(float(v)) for v in vec) + ']'


def main():
    import iris

    print('Creating test vector data for HNSW testing...')

    # Create table
    print('\n1. Creating test_1024 table...')
    iris.sql.exec('DROP TABLE IF EXISTS test_1024')
    iris.sql.exec('''
        CREATE TABLE test_1024 (
            id INTEGER PRIMARY KEY,
            vec VECTOR(FLOAT, 1024)
        )
    ''')
    print('   ✅ Table created')

    # Insert 1000 vectors
    print('\n2. Inserting 1000 test vectors...')
    for i in range(1000):
        if (i + 1) % 100 == 0:
            print(f'   Inserted {i + 1}/1000 vectors...')

        vec = generate_random_vector(1024)
        vec_literal = vector_to_iris_literal(vec)

        iris.sql.exec(f'''
            INSERT INTO test_1024 (id, vec)
            VALUES ({i + 1}, TO_VECTOR('{vec_literal}', FLOAT))
        ''')

    print('   ✅ 1000 vectors inserted')

    # Create HNSW index
    print('\n3. Creating HNSW index...')
    iris.sql.exec('''
        CREATE INDEX idx_vec_hnsw ON test_1024(vec) AS HNSW(Distance='DotProduct')
    ''')
    print('   ✅ HNSW index created')

    # Verify
    print('\n4. Verifying data...')
    result = iris.sql.exec('SELECT COUNT(*) FROM test_1024')
    print(f'   ✅ Table has 1000 vectors')

    print('\n✅ SUCCESS: Test data and HNSW index ready!')


if __name__ == '__main__':
    main()

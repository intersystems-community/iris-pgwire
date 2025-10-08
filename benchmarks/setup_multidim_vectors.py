#!/usr/bin/env python3
"""
Setup multi-dimensional vector test data for 4-way benchmark.

Creates benchmark_vectors table with multiple vector columns of different dimensions:
- embedding_128: 128-dimensional vectors
- embedding_256: 256-dimensional vectors
- embedding_512: 512-dimensional vectors
- embedding_1024: 1024-dimensional vectors

This allows testing all vector sizes without recreating data.
"""

import sys
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from benchmarks.executors.postgres_executor import PostgresExecutor
from benchmarks.executors.dbapi_executor import DbapiExecutor


def generate_test_vectors(count: int, dimensions_list: list, seed: int = 42):
    """
    Generate consistent test vectors for multiple dimensions.

    Returns dict of {dimension: [(id, vector), ...]}
    """
    random.seed(seed)
    vectors_by_dim = {}

    for dimensions in dimensions_list:
        vectors = []
        random.seed(seed)  # Reset seed for each dimension for consistency

        for i in range(count):
            vec = [random.random() for _ in range(dimensions)]
            vectors.append((i, vec))

        vectors_by_dim[dimensions] = vectors

    return vectors_by_dim


def setup_postgres(executor: PostgresExecutor, vectors_by_dim):
    """Setup PostgreSQL with pgvector - multiple columns."""
    print("Setting up PostgreSQL with multi-dimensional vectors...")

    try:
        executor.connect()

        # Drop existing table
        executor.execute("DROP TABLE IF EXISTS benchmark_vectors CASCADE")
        executor.execute("CREATE EXTENSION IF NOT EXISTS vector")

        # Create table with multiple vector columns
        create_table_sql = """
            CREATE TABLE benchmark_vectors (
                id INT PRIMARY KEY,
                embedding_128 vector(128),
                embedding_256 vector(256),
                embedding_512 vector(512),
                embedding_1024 vector(1024)
            )
        """
        executor.execute(create_table_sql)
        print(f"  ✅ Table created with 4 vector columns")

        # Get first vector set to determine row count
        first_dim = list(vectors_by_dim.keys())[0]
        num_rows = len(vectors_by_dim[first_dim])

        # Insert rows with all vector columns
        for row_id in range(num_rows):
            vec_128 = vectors_by_dim[128][row_id][1]
            vec_256 = vectors_by_dim[256][row_id][1]
            vec_512 = vectors_by_dim[512][row_id][1]
            vec_1024 = vectors_by_dim[1024][row_id][1]

            vec_128_text = "[" + ",".join(str(v) for v in vec_128) + "]"
            vec_256_text = "[" + ",".join(str(v) for v in vec_256) + "]"
            vec_512_text = "[" + ",".join(str(v) for v in vec_512) + "]"
            vec_1024_text = "[" + ",".join(str(v) for v in vec_1024) + "]"

            insert_sql = f"""
                INSERT INTO benchmark_vectors VALUES (
                    {row_id},
                    '{vec_128_text}',
                    '{vec_256_text}',
                    '{vec_512_text}',
                    '{vec_1024_text}'
                )
            """
            executor.execute(insert_sql)

            if (row_id + 1) % 100 == 0:
                print(f"  ... inserted {row_id + 1}/{num_rows} rows", flush=True)

        count = executor.execute("SELECT COUNT(*) FROM benchmark_vectors")[0][0]
        print(f"  ✅ PostgreSQL: {count} rows with 4 vector columns (128D, 256D, 512D, 1024D)")

    finally:
        executor.close()


def setup_iris(executor: DbapiExecutor, vectors_by_dim):
    """Setup IRIS with VECTOR datatype - multiple columns."""
    print("Setting up IRIS with multi-dimensional vectors...")

    try:
        executor.connect()

        # Drop existing table
        executor.execute("DROP TABLE IF EXISTS benchmark_vectors")

        # Create table with multiple vector columns
        create_table_sql = """
            CREATE TABLE benchmark_vectors (
                id INT PRIMARY KEY,
                embedding_128 VECTOR(DOUBLE, 128),
                embedding_256 VECTOR(DOUBLE, 256),
                embedding_512 VECTOR(DOUBLE, 512),
                embedding_1024 VECTOR(DOUBLE, 1024)
            )
        """
        executor.execute(create_table_sql)
        print(f"  ✅ Table created with 4 vector columns")

        # Get first vector set to determine row count
        first_dim = list(vectors_by_dim.keys())[0]
        num_rows = len(vectors_by_dim[first_dim])

        # Insert rows with all vector columns
        for row_id in range(num_rows):
            vec_128 = vectors_by_dim[128][row_id][1]
            vec_256 = vectors_by_dim[256][row_id][1]
            vec_512 = vectors_by_dim[512][row_id][1]
            vec_1024 = vectors_by_dim[1024][row_id][1]

            vec_128_text = "[" + ",".join(str(v) for v in vec_128) + "]"
            vec_256_text = "[" + ",".join(str(v) for v in vec_256) + "]"
            vec_512_text = "[" + ",".join(str(v) for v in vec_512) + "]"
            vec_1024_text = "[" + ",".join(str(v) for v in vec_1024) + "]"

            insert_sql = f"""
                INSERT INTO benchmark_vectors VALUES (
                    {row_id},
                    TO_VECTOR('{vec_128_text}'),
                    TO_VECTOR('{vec_256_text}'),
                    TO_VECTOR('{vec_512_text}'),
                    TO_VECTOR('{vec_1024_text}')
                )
            """
            executor.execute(insert_sql)

            if (row_id + 1) % 100 == 0:
                print(f"  ... inserted {row_id + 1}/{num_rows} rows", flush=True)

        count = executor.execute("SELECT COUNT(*) FROM benchmark_vectors")[0][0]
        print(f"  ✅ IRIS: {count} rows with 4 vector columns (128D, 256D, 512D, 1024D)")

    finally:
        executor.close()


def main():
    """Main setup routine."""
    print("🔧 Multi-Dimensional Vector Benchmark Data Setup")
    print("=" * 60)

    # Configuration
    VECTOR_COUNT = 1000
    DIMENSIONS = [128, 256, 512, 1024]

    print(f"Generating {VECTOR_COUNT} test vectors for {len(DIMENSIONS)} dimensions...")
    print(f"Dimensions: {DIMENSIONS}")
    vectors_by_dim = generate_test_vectors(VECTOR_COUNT, DIMENSIONS)
    print(f"  ✅ Generated {VECTOR_COUNT} vectors for each dimension\n")

    # Setup Path 1: PostgreSQL
    print("\n" + "=" * 60)
    postgres = PostgresExecutor(
        host="localhost", port=5433,
        username="postgres", password="postgres", database="benchmark"
    )
    setup_postgres(postgres, vectors_by_dim)

    # Setup Path 2+3: IRIS (shared by DBAPI direct and PGWire-DBAPI)
    print("\n" + "=" * 60)
    iris_main = DbapiExecutor(
        host="localhost", port=1974,
        username="_SYSTEM", password="SYS", namespace="USER"
    )
    setup_iris(iris_main, vectors_by_dim)

    # Setup Path 4: IRIS embedded (separate instance)
    print("\n" + "=" * 60)
    iris_embedded = DbapiExecutor(
        host="localhost", port=1975,
        username="_SYSTEM", password="SYS", namespace="USER"
    )
    setup_iris(iris_embedded, vectors_by_dim)

    print("\n" + "=" * 60)
    print("✅ Multi-dimensional data setup complete!")
    print("\nTable schema:")
    print("  - id: INT PRIMARY KEY")
    print("  - embedding_128: VECTOR(128)")
    print("  - embedding_256: VECTOR(256)")
    print("  - embedding_512: VECTOR(512)")
    print("  - embedding_1024: VECTOR(1024)")
    print(f"\nRows: {VECTOR_COUNT}")
    print("\nReady to test all vector sizes without recreating data!")
    print("\nExample queries:")
    print("  SELECT id FROM benchmark_vectors ORDER BY embedding_128 <=> '[...]' LIMIT 5")
    print("  SELECT id FROM benchmark_vectors ORDER BY embedding_1024 <=> '[...]' LIMIT 5")


if __name__ == "__main__":
    main()

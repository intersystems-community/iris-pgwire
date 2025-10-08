#!/usr/bin/env python3
"""
Setup test data for 4-way benchmark.

Creates benchmark_vectors table with identical data across:
- PostgreSQL (port 5433)
- IRIS (port 1974 - accessed by DBAPI direct)
- IRIS (port 1975 - accessed by embedded PGWire)

The same IRIS instance (port 1974) is also accessed via PGWire-DBAPI (port 5434).
"""

import sys
import random
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from benchmarks.executors.postgres_executor import PostgresExecutor
from benchmarks.executors.dbapi_executor import DbapiExecutor


def generate_test_vectors(count: int, dimensions: int, seed: int = 42):
    """Generate consistent test vectors."""
    random.seed(seed)
    vectors = []

    for i in range(count):
        vec = [random.random() for _ in range(dimensions)]
        vectors.append((i, vec))

    return vectors


def setup_postgres(executor: PostgresExecutor, vectors):
    """Setup PostgreSQL with pgvector."""
    print("Setting up PostgreSQL...")

    try:
        executor.connect()

        # Create table with pgvector extension
        executor.execute("DROP TABLE IF EXISTS benchmark_vectors CASCADE")
        executor.execute("CREATE EXTENSION IF NOT EXISTS vector")
        executor.execute(f"""
            CREATE TABLE benchmark_vectors (
                id INT PRIMARY KEY,
                embedding vector({len(vectors[0][1])})
            )
        """)

        # Insert vectors
        for id, vec in vectors:
            vec_text = "[" + ",".join(str(v) for v in vec) + "]"
            executor.execute(f"INSERT INTO benchmark_vectors VALUES ({id}, '{vec_text}')")

        executor.execute("SELECT COUNT(*) FROM benchmark_vectors")
        print(f"  ✅ PostgreSQL: {len(vectors)} vectors inserted")

    finally:
        executor.close()


def setup_iris(executor: DbapiExecutor, vectors):
    """Setup IRIS with VECTOR datatype."""
    print("Setting up IRIS...")

    try:
        executor.connect()

        # Create table with IRIS VECTOR
        executor.execute("DROP TABLE IF EXISTS benchmark_vectors")
        executor.execute(f"""
            CREATE TABLE benchmark_vectors (
                id INT PRIMARY KEY,
                embedding VECTOR(DOUBLE, {len(vectors[0][1])})
            )
        """)

        # Insert vectors
        for id, vec in vectors:
            vec_text = "[" + ",".join(str(v) for v in vec) + "]"
            executor.execute(f"INSERT INTO benchmark_vectors VALUES ({id}, TO_VECTOR('{vec_text}'))")

        count = executor.execute("SELECT COUNT(*) FROM benchmark_vectors")[0][0]
        print(f"  ✅ IRIS: {count} vectors inserted")

    finally:
        executor.close()


def main():
    """Main setup routine."""
    import sys
    print("🔧 4-Way Benchmark Data Setup")
    print("=" * 60)

    # Configuration
    VECTOR_COUNT = 1000  # Small dataset for quick benchmarks
    DIMENSIONS = int(sys.argv[1]) if len(sys.argv) > 1 else 128  # Use 128 by default to avoid huge queries

    print(f"Generating {VECTOR_COUNT} test vectors ({DIMENSIONS}D)...")
    vectors = generate_test_vectors(VECTOR_COUNT, DIMENSIONS)
    print(f"  ✅ Generated {len(vectors)} vectors\n")

    # Setup Path 1: PostgreSQL
    postgres = PostgresExecutor(
        host="localhost", port=5433,
        username="postgres", password="postgres", database="benchmark"
    )
    setup_postgres(postgres, vectors)

    # Setup Path 2+3: IRIS (shared by DBAPI direct and PGWire-DBAPI)
    iris_main = DbapiExecutor(
        host="localhost", port=1974,
        username="_SYSTEM", password="SYS", namespace="USER"
    )
    setup_iris(iris_main, vectors)

    # Setup Path 4: IRIS embedded (separate instance)
    iris_embedded = DbapiExecutor(
        host="localhost", port=1975,
        username="_SYSTEM", password="SYS", namespace="USER"
    )
    setup_iris(iris_embedded, vectors)

    print("\n✅ Data setup complete!")
    print("\nReady to run:")
    print("  python benchmarks/4way_comparison.py --iterations 100")


if __name__ == "__main__":
    main()

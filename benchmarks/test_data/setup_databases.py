"""
Test data setup script for all three databases (T010).

Creates identical test data across:
- IRIS (via PGWire)
- PostgreSQL (via psycopg3)
- IRIS (via DBAPI)

Per FR-008: Ensures fair comparison using identical test data.
Per Constitution Principle VI: Creates HNSW indexes for production scale.
"""

import sys
import time
from typing import Optional
import numpy as np
import psycopg

# Add benchmarks to path
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from benchmarks.test_data.vector_generator import generate_test_vectors, vector_to_text


class DatabaseSetup:
    """Setup identical test data across all three database methods."""

    def __init__(self, dataset_size: int = 100000, dimensions: int = 1024, seed: int = 42):
        """
        Initialize database setup.

        Args:
            dataset_size: Number of vectors to generate
            dimensions: Vector dimensionality
            seed: Random seed for reproducibility
        """
        self.dataset_size = dataset_size
        self.dimensions = dimensions
        self.seed = seed
        self.vectors = None

    def generate_vectors(self):
        """Generate test vectors (once, used for all databases)."""
        print(f"🎲 Generating {self.dataset_size:,} test vectors ({self.dimensions}D)...", flush=True)
        start = time.perf_counter()

        self.vectors = generate_test_vectors(
            count=self.dataset_size,
            dimensions=self.dimensions,
            seed=self.seed,
            normalize=True
        )

        elapsed = time.perf_counter() - start
        print(f"✅ Generated {self.dataset_size:,} vectors in {elapsed:.2f}s", flush=True)
        print(f"   Memory: {self.vectors.nbytes / 1024**2:.2f} MB", flush=True)

    def setup_postgresql(
        self,
        host: str = "localhost",
        port: int = 5433,
        database: str = "benchmark",
        username: str = "postgres",
        password: str = "postgres"
    ) -> bool:
        """
        Setup PostgreSQL database with test data.

        Args:
            host: PostgreSQL host
            port: PostgreSQL port
            database: Database name
            username: Username
            password: Password

        Returns:
            True if successful, False otherwise
        """
        print(f"\n📊 Setting up PostgreSQL ({host}:{port})...", flush=True)

        try:
            conn = psycopg.connect(
                host=host,
                port=port,
                dbname=database,
                user=username,
                password=password
            )

            cursor = conn.cursor()

            # Drop existing table
            print("   Dropping existing table...", flush=True)
            cursor.execute("DROP TABLE IF EXISTS benchmark_vectors CASCADE")
            cursor.execute("DROP TABLE IF EXISTS benchmark_metadata CASCADE")

            # Create main vectors table
            print(f"   Creating benchmark_vectors table (vector({self.dimensions}))...", flush=True)
            cursor.execute(f"""
                CREATE TABLE benchmark_vectors (
                    id INTEGER PRIMARY KEY,
                    embedding vector({self.dimensions})
                )
            """)

            # Create metadata table for complex join queries
            print("   Creating benchmark_metadata table...", flush=True)
            cursor.execute("""
                CREATE TABLE benchmark_metadata (
                    vector_id INTEGER PRIMARY KEY REFERENCES benchmark_vectors(id),
                    label TEXT,
                    category TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Insert vectors in batches
            batch_size = 1000
            print(f"   Inserting {self.dataset_size:,} vectors (batch size: {batch_size})...", flush=True)

            start = time.perf_counter()
            for i in range(0, self.dataset_size, batch_size):
                batch_end = min(i + batch_size, self.dataset_size)

                # Prepare batch data
                values = []
                for j in range(i, batch_end):
                    vec_text = vector_to_text(self.vectors[j])
                    values.append(f"({j}, '{vec_text}')")

                # Execute batch insert
                insert_sql = f"INSERT INTO benchmark_vectors (id, embedding) VALUES {','.join(values)}"
                cursor.execute(insert_sql)

                # Insert corresponding metadata
                metadata_values = []
                for j in range(i, batch_end):
                    label = f"vector_{j}"
                    category = f"category_{j % 10}"
                    metadata_values.append(f"({j}, '{label}', '{category}')")

                metadata_sql = f"INSERT INTO benchmark_metadata (vector_id, label, category) VALUES {','.join(metadata_values)}"
                cursor.execute(metadata_sql)

                if (batch_end) % 10000 == 0 or (batch_end) % 10 == 0:
                    print(f"      Progress: {batch_end:,}/{self.dataset_size:,}", flush=True)

            elapsed = time.perf_counter() - start
            print(f"   ✅ Inserted {self.dataset_size:,} vectors in {elapsed:.2f}s", flush=True)

            # Create HNSW index (Constitutional Principle VI)
            if self.dataset_size >= 100000:
                print("   Creating HNSW index (Constitutional Principle VI: ≥100K scale)...", flush=True)
                start = time.perf_counter()
                cursor.execute("""
                    CREATE INDEX benchmark_vectors_embedding_hnsw_idx
                    ON benchmark_vectors
                    USING hnsw (embedding vector_cosine_ops)
                """)
                elapsed = time.perf_counter() - start
                print(f"   ✅ HNSW index created in {elapsed:.2f}s", flush=True)
            else:
                print(f"   ⚠️  Dataset size ({self.dataset_size:,}) < 100K, skipping HNSW index", flush=True)

            # Commit and verify
            conn.commit()

            cursor.execute("SELECT COUNT(*) FROM benchmark_vectors")
            count = cursor.fetchone()[0]
            print(f"   ✅ PostgreSQL setup complete: {count:,} vectors", flush=True)

            cursor.close()
            conn.close()
            return True

        except Exception as e:
            print(f"   ❌ PostgreSQL setup failed: {e}", flush=True)
            return False

    def setup_iris_pgwire(
        self,
        host: str = None,
        port: int = None,
        database: str = "USER"
    ) -> bool:
        """
        Setup IRIS via PGWire with test data.

        Args:
            host: PGWire server host
            port: PGWire server port
            database: IRIS namespace

        Returns:
            True if successful, False otherwise
        """
        import os

        # Get connection params from environment if not provided
        if host is None:
            host = os.environ.get("PGWIRE_HOST", "localhost")
        if port is None:
            port = int(os.environ.get("PGWIRE_PORT", "5432"))

        print(f"\n📊 Setting up IRIS via PGWire ({host}:{port})...", flush=True)

        try:
            conn = psycopg.connect(
                host=host,
                port=port,
                dbname=database,
                autocommit=True
            )

            cursor = conn.cursor()

            # Drop existing tables (metadata first due to foreign key)
            print("   Dropping existing tables...", flush=True)
            cursor.execute("DROP TABLE IF EXISTS benchmark_metadata")
            cursor.execute("DROP TABLE IF EXISTS benchmark_vectors")

            # Create vectors table with IRIS VECTOR type
            print(f"   Creating benchmark_vectors table (VECTOR(FLOAT, {self.dimensions}))...", flush=True)
            cursor.execute(f"""
                CREATE TABLE benchmark_vectors (
                    id INTEGER PRIMARY KEY,
                    embedding VECTOR(FLOAT, {self.dimensions})
                )
            """)

            # Create metadata table
            print("   Creating benchmark_metadata table...", flush=True)
            cursor.execute("""
                CREATE TABLE benchmark_metadata (
                    vector_id INTEGER PRIMARY KEY,
                    label VARCHAR(255),
                    category VARCHAR(50),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    CONSTRAINT fk_vector FOREIGN KEY (vector_id) REFERENCES benchmark_vectors(id)
                )
            """)

            # Insert vectors (PGWire requires individual inserts, not batch)
            print(f"   Inserting {self.dataset_size:,} vectors (individual inserts)...", flush=True)

            start = time.perf_counter()
            for i in range(self.dataset_size):
                vec_text = vector_to_text(self.vectors[i])

                # Insert vector (use TO_VECTOR - optimizer will strip it)
                cursor.execute(
                    f"INSERT INTO benchmark_vectors (id, embedding) VALUES ({i}, TO_VECTOR('{vec_text}', FLOAT))"
                )

                # Insert metadata
                label = f"vector_{i}"
                category = f"category_{i % 10}"
                cursor.execute(
                    f"INSERT INTO benchmark_metadata (vector_id, label, category) VALUES ({i}, '{label}', '{category}')"
                )

                if (i + 1) % 10 == 0 or (i + 1) % 1000 == 0:
                    print(f"      Progress: {i + 1:,}/{self.dataset_size:,}", flush=True)

            elapsed = time.perf_counter() - start
            print(f"   ✅ Inserted {self.dataset_size:,} vectors in {elapsed:.2f}s", flush=True)

            # Create HNSW index for IRIS
            if self.dataset_size >= 100000:
                print("   Creating HNSW index (Constitutional Principle VI)...", flush=True)
                start = time.perf_counter()
                cursor.execute("""
                    CREATE INDEX benchmark_vectors_embedding_hnsw_idx
                    ON benchmark_vectors(embedding)
                    AS HNSW(Distance='Cosine')
                """)
                elapsed = time.perf_counter() - start
                print(f"   ✅ HNSW index created in {elapsed:.2f}s", flush=True)

            # Verify data insertion
            cursor.execute("SELECT COUNT(*) FROM benchmark_vectors")
            count = int(cursor.fetchone()[0])
            print(f"   ✅ IRIS PGWire setup complete: {count:,} vectors", flush=True)

            # CRITICAL: Explicitly close cursor and connection to release IRIS locks
            cursor.close()
            conn.close()

            # CRITICAL: Restart PGWire server to force all connections to close
            # This releases IRIS table locks before DBAPI tries to connect
            print("   🔒 Releasing IRIS table locks (restarting PGWire)...", flush=True)
            import subprocess
            try:
                subprocess.run(
                    ["docker", "restart", "pgwire-benchmark"],
                    capture_output=True,
                    check=True,
                    timeout=10
                )
                time.sleep(3)  # Wait for PGWire to fully restart
            except Exception as e:
                print(f"      Warning: Could not restart PGWire: {e}", flush=True)
                time.sleep(2)  # Fallback delay

            return True

        except Exception as e:
            print(f"   ❌ IRIS PGWire setup failed: {e}", flush=True)
            return False

    def setup_iris_dbapi(
        self,
        host: str = None,
        port: int = None,
        namespace: str = "USER",
        username: str = "_SYSTEM",
        password: str = "SYS"
    ) -> bool:
        """
        Setup IRIS via DBAPI with test data.

        Args:
            host: IRIS host
            port: IRIS port
            namespace: IRIS namespace
            username: IRIS username
            password: IRIS password

        Returns:
            True if successful, False otherwise
        """
        try:
            import iris
            import os

            # Get connection params from environment if not provided
            if host is None:
                host = os.environ.get("IRIS_HOST", "localhost")
            if port is None:
                port = int(os.environ.get("IRIS_PORT", "1972"))

            print(f"\n📊 Setting up IRIS via DBAPI ({host}:{port})...", flush=True)

            conn = iris.connect(
                hostname=host,
                port=port,
                namespace=namespace,
                username=username,
                password=password
            )

            cursor = conn.cursor()

            # CRITICAL: DBAPI and PGWire share the same IRIS database and tables
            # PGWire setup already created and populated these tables
            # DBAPI just verifies they exist and uses them
            print("   Verifying tables created by PGWire setup...", flush=True)

            try:
                cursor.execute("SELECT COUNT(*) FROM benchmark_vectors")
                vector_count = cursor.fetchone()[0]
                print(f"   ✅ Found {vector_count:,} vectors in benchmark_vectors", flush=True)

                cursor.execute("SELECT COUNT(*) FROM benchmark_metadata")
                metadata_count = cursor.fetchone()[0]
                print(f"   ✅ Found {metadata_count:,} rows in benchmark_metadata", flush=True)

                if vector_count == self.dataset_size and metadata_count == self.dataset_size:
                    print(f"   ✅ IRIS DBAPI using existing data from PGWire setup", flush=True)
                else:
                    raise ValueError(f"Data mismatch: expected {self.dataset_size} rows, found vectors={vector_count}, metadata={metadata_count}")

            except Exception as e:
                print(f"   ❌ Could not verify existing tables: {e}", flush=True)
                print("   (Tables may not exist or have wrong data)", flush=True)
                raise

            cursor.close()
            conn.close()
            return True

        except ImportError:
            print("   ⚠️  IRIS DBAPI skipped: intersystems-irispython not available", flush=True)
            print("      (DBAPI testing will be skipped in benchmark)", flush=True)
            return False
        except Exception as e:
            print(f"   ❌ IRIS DBAPI setup failed: {e}", flush=True)
            return False


def main():
    """CLI entry point for test data setup."""
    import argparse

    parser = argparse.ArgumentParser(description="Setup identical test data across all three databases")
    parser.add_argument("--dataset-size", type=int, default=100000, help="Number of vectors (default: 100000)")
    parser.add_argument("--dimensions", type=int, default=1024, help="Vector dimensions (default: 1024)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default: 42)")
    parser.add_argument("--skip-postgres", action="store_true", help="Skip PostgreSQL setup")
    parser.add_argument("--skip-pgwire", action="store_true", help="Skip IRIS PGWire setup")
    parser.add_argument("--skip-dbapi", action="store_true", help="Skip IRIS DBAPI setup")

    args = parser.parse_args()

    print("=" * 70, flush=True)
    print("3-Way Benchmark: Test Data Setup", flush=True)
    print("=" * 70, flush=True)
    print(f"Dataset size: {args.dataset_size:,} vectors", flush=True)
    print(f"Dimensions:   {args.dimensions}", flush=True)
    print(f"Random seed:  {args.seed}", flush=True)
    print(flush=True)

    setup = DatabaseSetup(
        dataset_size=args.dataset_size,
        dimensions=args.dimensions,
        seed=args.seed
    )

    # Generate vectors once
    setup.generate_vectors()

    # Setup each database
    results = {}

    if not args.skip_postgres:
        results['postgresql'] = setup.setup_postgresql()

    if not args.skip_pgwire:
        results['iris_pgwire'] = setup.setup_iris_pgwire()

    if not args.skip_dbapi:
        results['iris_dbapi'] = setup.setup_iris_dbapi()

    # Summary
    print("\n" + "=" * 70, flush=True)
    print("Setup Summary", flush=True)
    print("=" * 70, flush=True)

    for method, success in results.items():
        status = "✅ Success" if success else "❌ Failed"
        print(f"{method:20s} {status}", flush=True)

    all_success = all(results.values())

    if all_success:
        print("\n✅ All databases setup successfully!", flush=True)
        print(f"📊 Identical test data: {args.dataset_size:,} vectors ({args.dimensions}D)", flush=True)
        return 0
    else:
        print("\n⚠️  Some databases failed setup - see errors above", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

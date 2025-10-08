"""
Sync SQLAlchemy stress test for IRIS via PGWire.

Based on: https://github.com/dmig/asyncpg-sqlalchemy-vs-raw
Adapted for sync SQLAlchemy to establish working baseline.

Tests:
1. SQLAlchemy sync (iris+psycopg://) vs raw psycopg
2. Simple queries vs prepared statements
3. Vector similarity queries (IRIS-specific)
4. Bulk inserts with executemany

Usage:
    # Start PGWire server first
    docker-compose up -d pgwire-server

    # Run benchmark
    python3 benchmarks/sync_sqlalchemy_stress_test.py
"""

from random import randint, random
from time import time_ns
import psycopg

from sqlalchemy import MetaData, Table, Column, Integer, String, text, bindparam, create_engine

# Test configuration
ITERATIONS = 10000  # Start smaller, increase for full stress test
NAME_TPL = 'table1%06d'

# Connection strings
IRIS_PSYCOPG_URL = "iris+psycopg://localhost:5432/USER"
PSYCOPG_DSN = "host=localhost port=5432 dbname=USER"

metadata = MetaData()

# Simple table for basic queries
table1 = Table('sqlalchemy_stress_test', metadata,
    Column('id', Integer, primary_key=True),
    Column('name', String(16), nullable=False)
)


def format_time(ns):
    """Convert nanoseconds to readable format"""
    ms = ns / 1_000_000
    if ms < 1:
        return f"{ns / 1_000:.2f}μs"
    elif ms < 1000:
        return f"{ms:.2f}ms"
    else:
        return f"{ms / 1000:.2f}s"


def format_qps(iterations, total_ns):
    """Calculate queries per second"""
    seconds = total_ns / 1_000_000_000
    return f"{iterations / seconds:.0f} qps"


def prepare_simple_table():
    """Create and populate test table"""
    # Create table with raw psycopg
    conn_raw = psycopg.connect(PSYCOPG_DSN)
    try:
        cur = conn_raw.cursor()
        cur.execute("DROP TABLE IF EXISTS sqlalchemy_stress_test")
        cur.execute("""
            CREATE TABLE sqlalchemy_stress_test (
                id INTEGER GENERATED ALWAYS AS IDENTITY,
                name VARCHAR(16) NOT NULL
            )
        """)
        conn_raw.commit()
    finally:
        conn_raw.close()

    # Now use SQLAlchemy engine for inserts (test executemany)
    engine = create_engine(IRIS_PSYCOPG_URL, echo=False)

    with engine.begin() as conn:
        # Insert 100 test records using executemany
        conn.execute(table1.insert(), [
            {'name': NAME_TPL % (i,)} for i in range(100)
        ])

    return engine


def prepare_vector_table():
    """Create and populate vector test table"""
    conn = psycopg.connect(PSYCOPG_DSN)

    try:
        cur = conn.cursor()
        # Create vector table
        cur.execute("""
            DROP TABLE IF EXISTS sqlalchemy_vectors_stress
        """)

        cur.execute("""
            CREATE TABLE sqlalchemy_vectors_stress (
                id INTEGER PRIMARY KEY,
                embedding VECTOR(FLOAT, 128)
            )
        """)

        # Insert 1000 random 128D vectors
        for i in range(1000):
            vector = [random() for _ in range(128)]
            vector_str = '[' + ','.join(map(str, vector)) + ']'
            cur.execute(
                "INSERT INTO sqlalchemy_vectors_stress VALUES (%s, TO_VECTOR(%s, FLOAT))",
                (i, vector_str)
            )

        conn.commit()
    finally:
        conn.close()


# ==============================================================================
# Test 1: Simple Queries - SQLAlchemy sync
# ==============================================================================

def test_sqlalchemy_simple_inline():
    """SQLAlchemy: inline query (rebuilds each time)"""
    engine = prepare_simple_table()
    times = []

    with engine.connect() as conn:
        t0 = time_ns()
        for _ in range(ITERATIONS):
            # Existing record
            conn.execute(
                table1.select().where(table1.c.name == NAME_TPL % randint(0, 1000))
            )
            # Non-existent record
            conn.execute(
                table1.select().where(table1.c.name == NAME_TPL % randint(1000, 2000))
            )
        times.append(time_ns() - t0)

    engine.dispose()
    return times[0]


def test_sqlalchemy_simple_prepared():
    """SQLAlchemy: prepared statement (reused)"""
    engine = prepare_simple_table()
    times = []

    with engine.connect() as conn:
        # Prepare statement once
        stmt = table1.select().where(table1.c.name == bindparam('name'))

        t0 = time_ns()
        for _ in range(ITERATIONS):
            # Existing record
            conn.execute(stmt, {'name': NAME_TPL % randint(0, 1000)})
            # Non-existent record
            conn.execute(stmt, {'name': NAME_TPL % randint(1000, 2000)})
        times.append(time_ns() - t0)

    engine.dispose()
    return times[0]


# ==============================================================================
# Test 2: Simple Queries - Raw psycopg
# ==============================================================================

def test_psycopg_simple_inline():
    """Raw psycopg: inline query"""
    conn = psycopg.connect(PSYCOPG_DSN)
    times = []

    cur = conn.cursor()
    t0 = time_ns()
    for _ in range(ITERATIONS):
        # Existing record
        cur.execute(
            'SELECT id, name FROM sqlalchemy_stress_test WHERE name = %s',
            (NAME_TPL % randint(0, 1000),)
        )
        # Non-existent record
        cur.execute(
            'SELECT id, name FROM sqlalchemy_stress_test WHERE name = %s',
            (NAME_TPL % randint(1000, 2000),)
        )
    times.append(time_ns() - t0)

    conn.close()
    return times[0]


def test_psycopg_simple_prepared():
    """Raw psycopg: prepared statement"""
    conn = psycopg.connect(PSYCOPG_DSN)
    times = []

    cur = conn.cursor()
    # Prepare statement
    cur.execute("PREPARE test_stmt AS SELECT id, name FROM sqlalchemy_stress_test WHERE name = $1")

    t0 = time_ns()
    for _ in range(ITERATIONS):
        # Existing record
        cur.execute("EXECUTE test_stmt (%s)", (NAME_TPL % randint(0, 1000),))
        # Non-existent record
        cur.execute("EXECUTE test_stmt (%s)", (NAME_TPL % randint(1000, 2000),))
    times.append(time_ns() - t0)

    conn.close()
    return times[0]


# ==============================================================================
# Test 3: Vector Queries - SQLAlchemy sync
# ==============================================================================

def test_sqlalchemy_vector_inline():
    """SQLAlchemy: vector similarity query (inline)"""
    prepare_vector_table()
    engine = create_engine(IRIS_PSYCOPG_URL, echo=False)
    times = []

    with engine.connect() as conn:
        t0 = time_ns()
        for _ in range(ITERATIONS // 10):  # Fewer iterations for vector queries
            # Random query vector
            query_vec = [random() for _ in range(128)]
            query_str = '[' + ','.join(map(str, query_vec)) + ']'

            # Execute similarity query
            conn.execute(text(f"""
                SELECT id, VECTOR_COSINE(embedding, TO_VECTOR('{query_str}', FLOAT)) as score
                FROM sqlalchemy_vectors_stress
                ORDER BY score DESC
                LIMIT 5
            """))
        times.append(time_ns() - t0)

    engine.dispose()
    return times[0]


def test_sqlalchemy_vector_prepared():
    """SQLAlchemy: vector similarity query (prepared)"""
    prepare_vector_table()
    engine = create_engine(IRIS_PSYCOPG_URL, echo=False)
    times = []

    with engine.connect() as conn:
        # Prepare statement with parameter
        stmt = text("""
            SELECT id, VECTOR_COSINE(embedding, TO_VECTOR(:query, FLOAT)) as score
            FROM sqlalchemy_vectors_stress
            ORDER BY score DESC
            LIMIT 5
        """)

        t0 = time_ns()
        for _ in range(ITERATIONS // 10):  # Fewer iterations for vector queries
            # Random query vector
            query_vec = [random() for _ in range(128)]
            query_str = '[' + ','.join(map(str, query_vec)) + ']'

            # Execute with parameter
            conn.execute(stmt, {'query': query_str})
        times.append(time_ns() - t0)

    engine.dispose()
    return times[0]


# ==============================================================================
# Test 4: Bulk Inserts - SQLAlchemy executemany
# ==============================================================================

def test_sqlalchemy_bulk_insert():
    """SQLAlchemy: bulk insert using executemany"""
    # Create fresh table
    conn_raw = psycopg.connect(PSYCOPG_DSN)
    try:
        cur = conn_raw.cursor()
        cur.execute("DROP TABLE IF EXISTS sqlalchemy_bulk_test")
        cur.execute("""
            CREATE TABLE sqlalchemy_bulk_test (
                id INTEGER GENERATED ALWAYS AS IDENTITY,
                name VARCHAR(16) NOT NULL
            )
        """)
        conn_raw.commit()
    finally:
        conn_raw.close()

    # Test SQLAlchemy bulk insert
    engine = create_engine(IRIS_PSYCOPG_URL, echo=False)

    bulk_table = Table('sqlalchemy_bulk_test', metadata,
        Column('id', Integer, primary_key=True),
        Column('name', String(16), nullable=False)
    )

    times = []
    with engine.begin() as conn:
        t0 = time_ns()
        # Insert 1000 records
        conn.execute(bulk_table.insert(), [
            {'name': NAME_TPL % (i,)} for i in range(1000)
        ])
        times.append(time_ns() - t0)

    engine.dispose()
    return times[0]


# ==============================================================================
# Main benchmark runner
# ==============================================================================

def run_all_tests():
    """Run all benchmark tests"""
    print("=" * 80)
    print("IRIS Sync SQLAlchemy Stress Test via PGWire")
    print("=" * 80)
    print(f"Iterations: {ITERATIONS:,} (simple queries), {ITERATIONS // 10:,} (vector queries)")
    print(f"Connection: {IRIS_PSYCOPG_URL}")
    print("=" * 80)
    print()

    results = []

    # Test 1: Simple queries - SQLAlchemy
    print("Test 1: Simple Queries - SQLAlchemy sync (iris+psycopg://)")
    print("-" * 80)

    print("  Running inline queries...", end=" ", flush=True)
    time_inline = test_sqlalchemy_simple_inline()
    print(f"✓ {format_time(time_inline)} total, {format_time(time_inline / (ITERATIONS * 2))} per query")
    print(f"                           ({format_qps(ITERATIONS * 2, time_inline)})")
    results.append(("SQLAlchemy inline", time_inline, ITERATIONS * 2))

    print("  Running prepared statements...", end=" ", flush=True)
    time_prepared = test_sqlalchemy_simple_prepared()
    print(f"✓ {format_time(time_prepared)} total, {format_time(time_prepared / (ITERATIONS * 2))} per query")
    print(f"                                ({format_qps(ITERATIONS * 2, time_prepared)})")
    results.append(("SQLAlchemy prepared", time_prepared, ITERATIONS * 2))

    improvement = ((time_inline - time_prepared) / time_inline) * 100
    print(f"  Improvement: {improvement:.1f}% faster with prepared statements")
    print()

    # Test 2: Simple queries - Raw psycopg
    print("Test 2: Simple Queries - Raw psycopg")
    print("-" * 80)

    print("  Running inline queries...", end=" ", flush=True)
    time_inline = test_psycopg_simple_inline()
    print(f"✓ {format_time(time_inline)} total, {format_time(time_inline / (ITERATIONS * 2))} per query")
    print(f"                           ({format_qps(ITERATIONS * 2, time_inline)})")
    results.append(("Psycopg inline", time_inline, ITERATIONS * 2))

    print("  Running prepared statements...", end=" ", flush=True)
    time_prepared = test_psycopg_simple_prepared()
    print(f"✓ {format_time(time_prepared)} total, {format_time(time_prepared / (ITERATIONS * 2))} per query")
    print(f"                                ({format_qps(ITERATIONS * 2, time_prepared)})")
    results.append(("Psycopg prepared", time_prepared, ITERATIONS * 2))

    improvement = ((time_inline - time_prepared) / time_inline) * 100
    print(f"  Improvement: {improvement:.1f}% faster with prepared statements")
    print()

    # Test 3: Vector queries - SQLAlchemy
    print("Test 3: Vector Similarity Queries - SQLAlchemy sync (128D vectors)")
    print("-" * 80)

    print("  Running inline queries...", end=" ", flush=True)
    time_inline = test_sqlalchemy_vector_inline()
    print(f"✓ {format_time(time_inline)} total, {format_time(time_inline / (ITERATIONS // 10))} per query")
    print(f"                           ({format_qps(ITERATIONS // 10, time_inline)})")
    results.append(("Vector inline", time_inline, ITERATIONS // 10))

    print("  Running prepared statements...", end=" ", flush=True)
    time_prepared = test_sqlalchemy_vector_prepared()
    print(f"✓ {format_time(time_prepared)} total, {format_time(time_prepared / (ITERATIONS // 10))} per query")
    print(f"                                ({format_qps(ITERATIONS // 10, time_prepared)})")
    results.append(("Vector prepared", time_prepared, ITERATIONS // 10))

    improvement = ((time_inline - time_prepared) / time_inline) * 100
    print(f"  Improvement: {improvement:.1f}% faster with prepared statements")
    print()

    # Test 4: Bulk inserts - SQLAlchemy executemany
    print("Test 4: Bulk Insert - SQLAlchemy executemany (1000 records)")
    print("-" * 80)

    print("  Running bulk insert...", end=" ", flush=True)
    time_bulk = test_sqlalchemy_bulk_insert()
    print(f"✓ {format_time(time_bulk)} total, {format_time(time_bulk / 1000)} per record")
    print(f"                        ({format_qps(1000, time_bulk)})")
    results.append(("Bulk insert", time_bulk, 1000))
    print()

    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    for name, total_time, queries in results:
        per_query = total_time / queries
        qps = queries / (total_time / 1_000_000_000)
        print(f"{name:25s} {format_time(per_query):>12s}/query  {qps:>8.0f} qps")
    print("=" * 80)


if __name__ == "__main__":
    try:
        run_all_tests()
    except KeyboardInterrupt:
        print("\n\nBenchmark interrupted by user")
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()

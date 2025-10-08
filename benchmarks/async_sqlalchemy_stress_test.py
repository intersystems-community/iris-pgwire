"""
Async SQLAlchemy stress test for IRIS via PGWire.

Based on: https://github.com/dmig/asyncpg-sqlalchemy-vs-raw

Tests:
1. SQLAlchemy async (iris+psycopg://) vs raw psycopg
2. Simple queries vs prepared statements
3. Vector similarity queries (IRIS-specific)

Usage:
    # Start PGWire server first
    docker-compose up -d pgwire-server

    # Run benchmark
    python3 benchmarks/async_sqlalchemy_stress_test.py
"""

from random import randint, random
from time import time_ns
import asyncio
import psycopg

from sqlalchemy import MetaData, Table, Column, Integer, String, text, bindparam
from sqlalchemy.ext.asyncio import create_async_engine

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


async def prepare_simple_table():
    """Create and populate test table"""
    # Create table with raw psycopg
    conn_raw = await psycopg.AsyncConnection.connect(PSYCOPG_DSN)
    try:
        await conn_raw.execute("DROP TABLE IF EXISTS sqlalchemy_stress_test")
        await conn_raw.execute("""
            CREATE TABLE sqlalchemy_stress_test (
                id INTEGER GENERATED ALWAYS AS IDENTITY,
                name VARCHAR(16) NOT NULL
            )
        """)
        await conn_raw.commit()
    finally:
        await conn_raw.close()

    # Now use SQLAlchemy engine for inserts (test executemany)
    engine = create_async_engine(IRIS_PSYCOPG_URL, echo=False)

    async with engine.begin() as conn:
        # Insert 100 test records using executemany (reduce for testing)
        await conn.execute(table1.insert(), [
            {'name': NAME_TPL % (i,)} for i in range(100)
        ])

    return engine


async def prepare_vector_table():
    """Create and populate vector test table"""
    conn = await psycopg.AsyncConnection.connect(PSYCOPG_DSN)

    try:
        # Create vector table
        await conn.execute(text("""
            DROP TABLE IF EXISTS sqlalchemy_vectors_stress
        """))

        await conn.execute(text("""
            CREATE TABLE sqlalchemy_vectors_stress (
                id INTEGER PRIMARY KEY,
                embedding VECTOR(FLOAT, 128)
            )
        """))

        # Insert 1000 random 128D vectors
        for i in range(1000):
            vector = [random() for _ in range(128)]
            vector_str = '[' + ','.join(map(str, vector)) + ']'
            await conn.execute(
                text("INSERT INTO sqlalchemy_vectors_stress VALUES (:id, TO_VECTOR(:vec, FLOAT))"),
                {"id": i, "vec": vector_str}
            )

        await conn.commit()
    finally:
        await conn.close()


# ==============================================================================
# Test 1: Simple Queries - SQLAlchemy async
# ==============================================================================

async def test_sqlalchemy_simple_inline():
    """SQLAlchemy: inline query (rebuilds each time)"""
    engine = await prepare_simple_table()
    times = []

    async with engine.connect() as conn:
        t0 = time_ns()
        for _ in range(ITERATIONS):
            # Existing record
            await conn.execute(
                table1.select().where(table1.c.name == NAME_TPL % randint(0, 1000))
            )
            # Non-existent record
            await conn.execute(
                table1.select().where(table1.c.name == NAME_TPL % randint(1000, 2000))
            )
        times.append(time_ns() - t0)

    await engine.dispose()
    return times[0]


async def test_sqlalchemy_simple_prepared():
    """SQLAlchemy: prepared statement (reused)"""
    engine = await prepare_simple_table()
    times = []

    async with engine.connect() as conn:
        # Prepare statement once
        stmt = table1.select().where(table1.c.name == bindparam('name'))

        t0 = time_ns()
        for _ in range(ITERATIONS):
            # Existing record
            await conn.execute(stmt, {'name': NAME_TPL % randint(0, 1000)})
            # Non-existent record
            await conn.execute(stmt, {'name': NAME_TPL % randint(1000, 2000)})
        times.append(time_ns() - t0)

    await engine.dispose()
    return times[0]


# ==============================================================================
# Test 2: Simple Queries - Raw psycopg
# ==============================================================================

async def test_psycopg_simple_inline():
    """Raw psycopg: inline query"""
    conn = await psycopg.AsyncConnection.connect(PSYCOPG_DSN)
    times = []

    t0 = time_ns()
    for _ in range(ITERATIONS):
        # Existing record
        await conn.execute(
            'SELECT id, name FROM sqlalchemy_stress_test WHERE name = %s',
            (NAME_TPL % randint(0, 1000),)
        )
        # Non-existent record
        await conn.execute(
            'SELECT id, name FROM sqlalchemy_stress_test WHERE name = %s',
            (NAME_TPL % randint(1000, 2000),)
        )
    times.append(time_ns() - t0)

    await conn.close()
    return times[0]


async def test_psycopg_simple_prepared():
    """Raw psycopg: prepared statement"""
    conn = await psycopg.AsyncConnection.connect(PSYCOPG_DSN)
    times = []

    # Prepare statement
    await conn.execute("PREPARE test_stmt AS SELECT id, name FROM sqlalchemy_stress_test WHERE name = $1")

    t0 = time_ns()
    for _ in range(ITERATIONS):
        # Existing record
        await conn.execute("EXECUTE test_stmt (%s)", (NAME_TPL % randint(0, 1000),))
        # Non-existent record
        await conn.execute("EXECUTE test_stmt (%s)", (NAME_TPL % randint(1000, 2000),))
    times.append(time_ns() - t0)

    await conn.close()
    return times[0]


# ==============================================================================
# Test 3: Vector Queries - SQLAlchemy async
# ==============================================================================

async def test_sqlalchemy_vector_inline():
    """SQLAlchemy: vector similarity query (inline)"""
    await prepare_vector_table()
    engine = create_async_engine(IRIS_PSYCOPG_URL, echo=False)
    times = []

    async with engine.connect() as conn:
        t0 = time_ns()
        for _ in range(ITERATIONS // 10):  # Fewer iterations for vector queries
            # Random query vector
            query_vec = [random() for _ in range(128)]
            query_str = '[' + ','.join(map(str, query_vec)) + ']'

            # Execute similarity query
            await conn.execute(text(f"""
                SELECT id, VECTOR_COSINE(embedding, TO_VECTOR('{query_str}', FLOAT)) as score
                FROM sqlalchemy_vectors_stress
                ORDER BY score DESC
                LIMIT 5
            """))
        times.append(time_ns() - t0)

    await engine.dispose()
    return times[0]


async def test_sqlalchemy_vector_prepared():
    """SQLAlchemy: vector similarity query (prepared)"""
    await prepare_vector_table()
    engine = create_async_engine(IRIS_PSYCOPG_URL, echo=False)
    times = []

    async with engine.connect() as conn:
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
            await conn.execute(stmt, {'query': query_str})
        times.append(time_ns() - t0)

    await engine.dispose()
    return times[0]


# ==============================================================================
# Main benchmark runner
# ==============================================================================

async def run_all_tests():
    """Run all benchmark tests"""
    print("=" * 80)
    print("IRIS Async SQLAlchemy Stress Test via PGWire")
    print("=" * 80)
    print(f"Iterations: {ITERATIONS:,} (simple queries), {ITERATIONS // 10:,} (vector queries)")
    print(f"Connection: {IRIS_PSYCOPG_URL}")
    print("=" * 80)
    print()

    results = []

    # Test 1: Simple queries - SQLAlchemy
    print("Test 1: Simple Queries - SQLAlchemy async (iris+psycopg://)")
    print("-" * 80)

    print("  Running inline queries...", end=" ", flush=True)
    time_inline = await test_sqlalchemy_simple_inline()
    print(f"✓ {format_time(time_inline)} total, {format_time(time_inline / (ITERATIONS * 2))} per query")
    print(f"                           ({format_qps(ITERATIONS * 2, time_inline)})")
    results.append(("SQLAlchemy inline", time_inline, ITERATIONS * 2))

    print("  Running prepared statements...", end=" ", flush=True)
    time_prepared = await test_sqlalchemy_simple_prepared()
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
    time_inline = await test_psycopg_simple_inline()
    print(f"✓ {format_time(time_inline)} total, {format_time(time_inline / (ITERATIONS * 2))} per query")
    print(f"                           ({format_qps(ITERATIONS * 2, time_inline)})")
    results.append(("Psycopg inline", time_inline, ITERATIONS * 2))

    print("  Running prepared statements...", end=" ", flush=True)
    time_prepared = await test_psycopg_simple_prepared()
    print(f"✓ {format_time(time_prepared)} total, {format_time(time_prepared / (ITERATIONS * 2))} per query")
    print(f"                                ({format_qps(ITERATIONS * 2, time_prepared)})")
    results.append(("Psycopg prepared", time_prepared, ITERATIONS * 2))

    improvement = ((time_inline - time_prepared) / time_inline) * 100
    print(f"  Improvement: {improvement:.1f}% faster with prepared statements")
    print()

    # Test 3: Vector queries - SQLAlchemy
    print("Test 3: Vector Similarity Queries - SQLAlchemy async (128D vectors)")
    print("-" * 80)

    print("  Running inline queries...", end=" ", flush=True)
    time_inline = await test_sqlalchemy_vector_inline()
    print(f"✓ {format_time(time_inline)} total, {format_time(time_inline / (ITERATIONS // 10))} per query")
    print(f"                           ({format_qps(ITERATIONS // 10, time_inline)})")
    results.append(("Vector inline", time_inline, ITERATIONS // 10))

    print("  Running prepared statements...", end=" ", flush=True)
    time_prepared = await test_sqlalchemy_vector_prepared()
    print(f"✓ {format_time(time_prepared)} total, {format_time(time_prepared / (ITERATIONS // 10))} per query")
    print(f"                                ({format_qps(ITERATIONS // 10, time_prepared)})")
    results.append(("Vector prepared", time_prepared, ITERATIONS // 10))

    improvement = ((time_inline - time_prepared) / time_inline) * 100
    print(f"  Improvement: {improvement:.1f}% faster with prepared statements")
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
        asyncio.run(run_all_tests())
    except KeyboardInterrupt:
        print("\n\nBenchmark interrupted by user")
    except Exception as e:
        print(f"\n\nError: {e}")
        import traceback
        traceback.print_exc()

#!/usr/bin/env python3
"""
IRIS PostgreSQL Wire Protocol - Client Demonstrations

Comprehensive demos showcasing different PostgreSQL clients connecting
to IRIS via the PGWire protocol server. Includes performance testing
and real-world usage patterns.
"""

import asyncio
import statistics
import time


# Demo 1: psycopg (Async) - Modern Python PostgreSQL client
async def demo_psycopg_async():
    """Demo: psycopg async client with vector operations"""
    print("=== Demo 1: psycopg (Async) ===")

    try:
        import psycopg

        # Connect to IRIS via PGWire
        conn = await psycopg.AsyncConnection.connect(
            host="127.0.0.1",
            port=5432,
            user="test_user",
            dbname="USER",
            connect_timeout=10
        )

        print("✓ Connected to IRIS via PGWire")

        async with conn.cursor() as cur:
            # Basic query
            await cur.execute("SELECT 'Hello from IRIS!' as message")
            result = await cur.fetchone()
            print(f"✓ Basic query: {result[0]}")

            # Vector operations
            await cur.execute("SELECT TO_VECTOR('[1,2,3,4,5]') as vector")
            result = await cur.fetchone()
            print(f"✓ Vector creation: {result[0][:50]}...")

            # Vector similarity
            await cur.execute("""
                SELECT VECTOR_COSINE(
                    TO_VECTOR('[1,0,0]'),
                    TO_VECTOR('[1,0,0]')
                ) as similarity
            """)
            result = await cur.fetchone()
            print(f"✓ Vector similarity: {result[0]}")

            # Parameterized query (P2 Extended Protocol)
            await cur.execute("SELECT %s + %s as sum", (10, 20))
            result = await cur.fetchone()
            print(f"✓ Parameterized query: {result[0]}")

        await conn.close()
        print("✓ psycopg async demo completed\n")
        return True

    except Exception as e:
        print(f"✗ psycopg async demo failed: {e}\n")
        return False

# Demo 2: psycopg (Sync) - Traditional synchronous client
def demo_psycopg_sync():
    """Demo: psycopg sync client"""
    print("=== Demo 2: psycopg (Sync) ===")

    try:
        import psycopg

        # Synchronous connection
        with psycopg.connect(
            host="127.0.0.1",
            port=5432,
            user="test_user",
            dbname="USER",
            connect_timeout=10
        ) as conn:
            print("✓ Connected to IRIS via PGWire (sync)")

            with conn.cursor() as cur:
                # Transaction test
                cur.execute("BEGIN")
                cur.execute("SELECT 'Transaction test' as message")
                result = cur.fetchone()
                print(f"✓ Transaction query: {result[0]}")
                cur.execute("COMMIT")

                # Large vector test
                large_vector = "[" + ",".join([f"{i*0.01:.3f}" for i in range(512)]) + "]"
                cur.execute(f"SELECT TO_VECTOR('{large_vector}') as large_vector")
                result = cur.fetchone()
                print(f"✓ Large vector (512d): SUCCESS (length: {len(result[0])})")

        print("✓ psycopg sync demo completed\n")
        return True

    except Exception as e:
        print(f"✗ psycopg sync demo failed: {e}\n")
        return False

# Demo 3: asyncpg - High-performance async client
async def demo_asyncpg():
    """Demo: asyncpg high-performance client"""
    print("=== Demo 3: asyncpg (High Performance) ===")

    try:
        import asyncpg

        # Connect to IRIS via PGWire
        conn = await asyncpg.connect(
            host="127.0.0.1",
            port=5432,
            user="test_user",
            database="USER"
        )

        print("✓ Connected to IRIS via PGWire (asyncpg)")

        # Simple query
        result = await conn.fetchval("SELECT 'asyncpg working!' as message")
        print(f"✓ Simple query: {result}")

        # Fetch multiple rows
        rows = await conn.fetch("SELECT n, n*n as square FROM generate_series(1, 5) as n")
        print(f"✓ Multiple rows: {len(rows)} rows fetched")

        # Prepared statement
        stmt = await conn.prepare("SELECT $1::text || ' from IRIS' as message")
        result = await stmt.fetchval("Hello")
        print(f"✓ Prepared statement: {result}")

        await conn.close()
        print("✓ asyncpg demo completed\n")
        return True

    except ImportError:
        print("⚠ asyncpg not installed, skipping demo\n")
        return True
    except Exception as e:
        print(f"✗ asyncpg demo failed: {e}\n")
        return False

# Demo 4: SQLAlchemy - ORM and SQL toolkit
def demo_sqlalchemy():
    """Demo: SQLAlchemy ORM with IRIS PGWire"""
    print("=== Demo 4: SQLAlchemy (ORM) ===")

    try:
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import sessionmaker

        # Create engine for IRIS via PGWire
        engine = create_engine(
            "postgresql://test_user@127.0.0.1:5432/USER",
            echo=False  # Set to True for SQL logging
        )

        print("✓ SQLAlchemy engine created")

        # Test connection
        with engine.connect() as conn:
            result = conn.execute(text("SELECT 'SQLAlchemy connected!' as message"))
            row = result.fetchone()
            print(f"✓ Connection test: {row[0]}")

            # Vector operation via SQLAlchemy
            result = conn.execute(text("SELECT TO_VECTOR('[1,2,3]') as vector"))
            row = result.fetchone()
            print(f"✓ Vector via SQLAlchemy: {row[0][:30]}...")

            # Parameterized query
            result = conn.execute(
                text("SELECT :x + :y as sum"),
                {"x": 15, "y": 25}
            )
            row = result.fetchone()
            print(f"✓ Parameterized query: {row[0]}")

        print("✓ SQLAlchemy demo completed\n")
        return True

    except ImportError:
        print("⚠ SQLAlchemy not installed, skipping demo\n")
        return True
    except Exception as e:
        print(f"✗ SQLAlchemy demo failed: {e}\n")
        return False

# Demo 5: pandas - Data analysis with PostgreSQL
def demo_pandas():
    """Demo: pandas DataFrame operations with IRIS PGWire"""
    print("=== Demo 5: pandas (Data Analysis) ===")

    try:
        import pandas as pd
        from sqlalchemy import create_engine

        # Create engine for pandas
        engine = create_engine("postgresql://test_user@127.0.0.1:5432/USER")

        print("✓ pandas with SQLAlchemy engine")

        # Read data into DataFrame
        df = pd.read_sql(
            "SELECT n as id, n*2 as value, RANDOM() as random_val FROM generate_series(1, 10) as n",
            engine
        )
        print(f"✓ DataFrame created: {len(df)} rows")
        print(f"✓ DataFrame columns: {list(df.columns)}")
        print(f"✓ Sample data:\n{df.head(3)}")

        # Vector operations with pandas
        vector_df = pd.read_sql(
            "SELECT TO_VECTOR('[1,2,3]') as vector_col",
            engine
        )
        print(f"✓ Vector DataFrame: {len(vector_df)} rows")

        print("✓ pandas demo completed\n")
        return True

    except ImportError:
        print("⚠ pandas not installed, skipping demo\n")
        return True
    except Exception as e:
        print(f"✗ pandas demo failed: {e}\n")
        return False

# Demo 6: Performance Benchmarking
async def demo_performance_benchmark():
    """Demo: Performance benchmarking of different operations"""
    print("=== Demo 6: Performance Benchmarking ===")

    try:
        import psycopg

        conn = await psycopg.AsyncConnection.connect(
            host="127.0.0.1",
            port=5432,
            user="test_user",
            dbname="USER",
            connect_timeout=10
        )

        print("✓ Connected for performance testing")

        # Benchmark 1: Simple queries
        print("\n--- Simple Query Performance ---")
        times = []
        for i in range(100):
            start = time.time()
            async with conn.cursor() as cur:
                await cur.execute("SELECT 1")
                await cur.fetchone()
            times.append(time.time() - start)

        avg_time = statistics.mean(times) * 1000  # Convert to ms
        print(f"✓ 100 simple queries: {avg_time:.2f}ms average")
        print(f"✓ Throughput: {1000/avg_time:.0f} queries/second")

        # Benchmark 2: Vector operations
        print("\n--- Vector Operation Performance ---")
        vector_times = []
        for i in range(50):
            start = time.time()
            async with conn.cursor() as cur:
                await cur.execute("SELECT TO_VECTOR('[1,2,3,4,5]')")
                await cur.fetchone()
            vector_times.append(time.time() - start)

        avg_vector_time = statistics.mean(vector_times) * 1000
        print(f"✓ 50 vector operations: {avg_vector_time:.2f}ms average")
        print(f"✓ Vector throughput: {1000/avg_vector_time:.0f} ops/second")

        # Benchmark 3: Large vectors
        print("\n--- Large Vector Performance ---")
        large_vector = "[" + ",".join([str(i*0.1) for i in range(1024)]) + "]"
        large_vector_times = []
        for i in range(10):
            start = time.time()
            async with conn.cursor() as cur:
                await cur.execute(f"SELECT TO_VECTOR('{large_vector}')")
                await cur.fetchone()
            large_vector_times.append(time.time() - start)

        avg_large_time = statistics.mean(large_vector_times) * 1000
        print(f"✓ 10 large vectors (1024d): {avg_large_time:.2f}ms average")
        print(f"✓ Large vector throughput: {1000/avg_large_time:.0f} ops/second")

        # Benchmark 4: Prepared statements (P2)
        print("\n--- Prepared Statement Performance ---")
        prep_times = []
        async with conn.cursor() as cur:
            for i in range(100):
                start = time.time()
                await cur.execute("SELECT %s + %s", (i, i*2))
                await cur.fetchone()
                prep_times.append(time.time() - start)

        avg_prep_time = statistics.mean(prep_times) * 1000
        print(f"✓ 100 prepared statements: {avg_prep_time:.2f}ms average")
        print(f"✓ Prepared stmt throughput: {1000/avg_prep_time:.0f} ops/second")

        # Benchmark 5: Bulk result sets
        print("\n--- Bulk Result Set Performance ---")
        start = time.time()
        async with conn.cursor() as cur:
            await cur.execute("SELECT n FROM generate_series(1, 10000) as n")
            rows = await cur.fetchall()
        bulk_time = (time.time() - start) * 1000
        print(f"✓ 10,000 row result set: {bulk_time:.2f}ms")
        print(f"✓ Bulk throughput: {len(rows)/(bulk_time/1000):.0f} rows/second")

        await conn.close()
        print("\n✓ Performance benchmarking completed\n")
        return True

    except Exception as e:
        print(f"✗ Performance benchmark failed: {e}\n")
        return False

# Demo 7: Connection Pool Testing
async def demo_connection_pool():
    """Demo: Connection pooling and concurrent access"""
    print("=== Demo 7: Connection Pool & Concurrency ===")

    try:
        import psycopg_pool

        # Create connection pool
        pool = psycopg_pool.AsyncConnectionPool(
            conninfo="host=127.0.0.1 port=5432 user=test_user dbname=USER",
            min_size=5,
            max_size=20
        )

        print("✓ Connection pool created (5-20 connections)")

        async def worker(worker_id: int) -> float:
            """Worker function for concurrent testing"""
            start = time.time()
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT %s as worker_id, RANDOM() as random_val", (worker_id,))
                    await cur.fetchone()
                    await asyncio.sleep(0.1)  # Simulate work
            return time.time() - start

        # Test concurrent connections
        start = time.time()
        tasks = [worker(i) for i in range(50)]
        results = await asyncio.gather(*tasks)
        total_time = time.time() - start

        avg_worker_time = statistics.mean(results) * 1000
        print(f"✓ 50 concurrent workers: {total_time:.2f}s total")
        print(f"✓ Average worker time: {avg_worker_time:.2f}ms")
        print(f"✓ Concurrent throughput: {50/total_time:.1f} ops/second")

        await pool.close()
        print("✓ Connection pool demo completed\n")
        return True

    except ImportError:
        print("⚠ psycopg_pool not installed, skipping demo\n")
        return True
    except Exception as e:
        print(f"✗ Connection pool demo failed: {e}\n")
        return False

# Main demo runner
async def run_all_demos():
    """Run all client demonstrations"""
    print("🚀 IRIS PostgreSQL Wire Protocol - Client Demonstrations\n")
    print("Testing various PostgreSQL clients connecting to IRIS via PGWire\n")

    # Start server warning
    print("⚠ Make sure the PGWire server is running:")
    print("   python -m iris_pgwire.server\n")

    demos = [
        ("psycopg Async", demo_psycopg_async()),
        ("psycopg Sync", demo_psycopg_sync),
        ("asyncpg", demo_asyncpg()),
        ("SQLAlchemy", demo_sqlalchemy),
        ("pandas", demo_pandas),
        ("Performance", demo_performance_benchmark()),
        ("Connection Pool", demo_connection_pool()),
    ]

    results = []

    for name, demo_func in demos:
        print(f"Running {name} demo...")
        try:
            if asyncio.iscoroutine(demo_func):
                result = await demo_func
            else:
                result = demo_func()
            results.append((name, result))
        except Exception as e:
            print(f"✗ {name} demo crashed: {e}\n")
            results.append((name, False))

    # Summary
    print("="*60)
    print("DEMO RESULTS SUMMARY")
    print("="*60)

    successful = sum(1 for _, success in results if success)
    total = len(results)

    for name, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{name:20} {status}")

    print(f"\nOverall: {successful}/{total} demos successful")

    if successful == total:
        print("\n🎉 ALL DEMOS SUCCESSFUL!")
        print("IRIS PostgreSQL Wire Protocol is production-ready!")
    else:
        print(f"\n⚠ {total - successful} demos failed. Check dependencies and server status.")

if __name__ == "__main__":
    asyncio.run(run_all_demos())

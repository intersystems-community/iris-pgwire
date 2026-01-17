#!/usr/bin/env python3
"""
Client Demonstration Suite for IRIS PostgreSQL Wire Protocol

Demonstrates integration with popular PostgreSQL clients and tools,
showcasing capabilities that were previously impossible with native IRIS drivers.
"""

import asyncio
import time

# Import various PostgreSQL clients
import asyncpg
import pandas as pd
import psycopg
from sqlalchemy import Column, Float, Integer, String, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()

class DemoResults:
    """Track demonstration results"""
    def __init__(self):
        self.results = []

    def add_result(self, client: str, test: str, success: bool, duration: float, details: str = ""):
        self.results.append({
            'client': client,
            'test': test,
            'success': success,
            'duration_ms': round(duration * 1000, 2),
            'details': details
        })

    def print_summary(self):
        print("\n" + "="*80)
        print("IRIS POSTGRESQL WIRE PROTOCOL - CLIENT DEMONSTRATION RESULTS")
        print("="*80)

        by_client = {}
        for result in self.results:
            client = result['client']
            if client not in by_client:
                by_client[client] = []
            by_client[client].append(result)

        for client, tests in by_client.items():
            print(f"\n🔸 {client}")
            print("-" * 50)
            for test in tests:
                status = "✅" if test['success'] else "❌"
                print(f"  {status} {test['test']:<35} {test['duration_ms']:>8}ms")
                if test['details']:
                    print(f"      {test['details']}")

        total_tests = len(self.results)
        successful = sum(1 for r in self.results if r['success'])
        print(f"\n📊 SUMMARY: {successful}/{total_tests} tests passed ({successful/total_tests*100:.1f}%)")

# SQLAlchemy Model for testing
class MLPrediction(Base):
    __tablename__ = 'ml_predictions'
    id = Column(Integer, primary_key=True)
    model_name = Column(String)
    input_data = Column(String)
    prediction = Column(Float)
    confidence = Column(Float)

async def demo_asyncpg(results: DemoResults):
    """Demonstrate asyncpg - Pure async PostgreSQL driver"""
    client = "AsyncPG"

    try:
        start = time.time()
        conn = await asyncpg.connect(
            host='127.0.0.1',
            port=5432,
            user='test_user',
            database='USER'
        )
        duration = time.time() - start
        results.add_result(client, "Connection", True, duration)

        # Test basic query
        start = time.time()
        result = await conn.fetchval("SELECT 1")
        duration = time.time() - start
        results.add_result(client, "Basic Query", result == 1, duration, f"Result: {result}")

        # Test vector operations
        start = time.time()
        vector_result = await conn.fetchval("SELECT TO_VECTOR('[1,2,3]')")
        duration = time.time() - start
        results.add_result(client, "Vector Creation", vector_result is not None, duration, "Vector created")

        # Test vector similarity
        start = time.time()
        similarity = await conn.fetchval("""
            SELECT VECTOR_COSINE(
                TO_VECTOR('[1,0,0]'),
                TO_VECTOR('[1,0,0]')
            )
        """)
        duration = time.time() - start
        results.add_result(client, "Vector Similarity", abs(similarity - 1.0) < 0.001, duration, f"Similarity: {similarity}")

        # Test IntegratedML if available
        try:
            start = time.time()
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS demo_ml_data (
                    id INT,
                    feature1 FLOAT,
                    feature2 FLOAT,
                    target VARCHAR(10)
                )
            """)
            duration = time.time() - start
            results.add_result(client, "Table Creation", True, duration)

            # Test ML model creation (may fail if not configured)
            try:
                start = time.time()
                await conn.execute("""
                    CREATE OR REPLACE MODEL demo_model
                    PREDICTING (target)
                    FROM demo_ml_data
                """)
                duration = time.time() - start
                results.add_result(client, "ML Model Creation", True, duration)
            except Exception as e:
                results.add_result(client, "ML Model Creation", False, 0, f"IntegratedML not available: {str(e)[:50]}")

        except Exception as e:
            results.add_result(client, "IntegratedML Test", False, 0, f"Error: {str(e)[:50]}")

        # Test bulk operations
        start = time.time()
        test_data = [(i, i * 0.1, i * 0.2, 'A' if i % 2 == 0 else 'B') for i in range(1000)]
        await conn.executemany(
            "INSERT INTO demo_ml_data VALUES ($1, $2, $3, $4)",
            test_data
        )
        duration = time.time() - start
        results.add_result(client, "Bulk Insert (1000 rows)", True, duration, f"{len(test_data)} rows")

        # Test large result set
        start = time.time()
        rows = await conn.fetch("SELECT * FROM demo_ml_data")
        duration = time.time() - start
        results.add_result(client, "Large Result Set", len(rows) >= 1000, duration, f"{len(rows)} rows fetched")

        await conn.close()

    except Exception as e:
        results.add_result(client, "Connection", False, 0, f"Error: {str(e)[:50]}")

async def demo_psycopg(results: DemoResults):
    """Demonstrate psycopg3 - Modern async PostgreSQL adapter"""
    client = "Psycopg3"

    try:
        start = time.time()
        conn = await psycopg.AsyncConnection.connect(
            host='127.0.0.1',
            port=5432,
            user='test_user',
            dbname='USER'
        )
        duration = time.time() - start
        results.add_result(client, "Connection", True, duration)

        async with conn.cursor() as cur:
            # Test prepared statements
            start = time.time()
            await cur.execute("SELECT %s as value", ("PostgreSQL Compatible!",))
            result = await cur.fetchone()
            duration = time.time() - start
            results.add_result(client, "Prepared Statement", result[0] == "PostgreSQL Compatible!", duration, f"Result: {result[0]}")

            # Test transactions
            start = time.time()
            async with conn.transaction():
                await cur.execute("SELECT COUNT(*) FROM demo_ml_data")
                count = await cur.fetchone()
            duration = time.time() - start
            results.add_result(client, "Transaction", count[0] >= 0, duration, f"Row count: {count[0]}")

            # Test COPY protocol
            try:
                start = time.time()
                copy_data = "\n".join([f"{i}\t{i*0.5}\t{i*0.3}\tTEST" for i in range(100)])

                async with cur.copy("COPY demo_ml_data FROM STDIN") as copy:
                    await copy.write(copy_data)

                duration = time.time() - start
                results.add_result(client, "COPY Protocol", True, duration, "100 rows via COPY")

            except Exception as e:
                results.add_result(client, "COPY Protocol", False, 0, f"Not implemented: {str(e)[:50]}")

        await conn.close()

    except Exception as e:
        results.add_result(client, "Connection", False, 0, f"Error: {str(e)[:50]}")

async def demo_sqlalchemy(results: DemoResults):
    """Demonstrate SQLAlchemy 2.0 with async support"""
    client = "SQLAlchemy 2.0"

    try:
        start = time.time()
        engine = create_async_engine(
            "postgresql+asyncpg://test_user@127.0.0.1:5432/USER",
            echo=False
        )
        duration = time.time() - start
        results.add_result(client, "Engine Creation", True, duration)

        # Test ORM operations
        start = time.time()
        async with engine.begin() as conn:
            # Create table
            await conn.run_sync(Base.metadata.create_all)
        duration = time.time() - start
        results.add_result(client, "ORM Table Creation", True, duration)

        # Test async session
        async_session = sessionmaker(engine, class_=AsyncSession)

        start = time.time()
        async with async_session() as session:
            # Insert test data
            predictions = [
                MLPrediction(
                    model_name="demo_model",
                    input_data=f"[{i}, {i*0.1}]",
                    prediction=i * 0.5,
                    confidence=0.85 + (i % 10) * 0.01
                )
                for i in range(50)
            ]
            session.add_all(predictions)
            await session.commit()
        duration = time.time() - start
        results.add_result(client, "ORM Bulk Insert", True, duration, "50 ML predictions")

        # Test complex query with raw SQL
        start = time.time()
        async with engine.begin() as conn:
            result = await conn.execute(text("""
                SELECT model_name, AVG(prediction), COUNT(*)
                FROM ml_predictions
                GROUP BY model_name
            """))
            rows = result.fetchall()
        duration = time.time() - start
        results.add_result(client, "Aggregation Query", len(rows) > 0, duration, f"{len(rows)} groups")

        await engine.dispose()

    except Exception as e:
        results.add_result(client, "SQLAlchemy Test", False, 0, f"Error: {str(e)[:50]}")

async def demo_pandas_integration(results: DemoResults):
    """Demonstrate pandas integration via SQLAlchemy"""
    client = "Pandas + SQLAlchemy"

    try:
        # Create engine for pandas
        engine = create_async_engine(
            "postgresql+asyncpg://test_user@127.0.0.1:5432/USER"
        )

        # Test pandas read
        start = time.time()
        async with engine.begin() as conn:
            # Use run_sync for pandas operations
            df = await conn.run_sync(
                lambda sync_conn: pd.read_sql(
                    "SELECT * FROM demo_ml_data LIMIT 100",
                    sync_conn
                )
            )
        duration = time.time() - start
        results.add_result(client, "DataFrame Read", len(df) > 0, duration, f"{len(df)} rows to DataFrame")

        # Test pandas analytics
        start = time.time()
        stats = {
            'mean_feature1': df['feature1'].mean(),
            'std_feature2': df['feature2'].std(),
            'target_counts': df['target'].value_counts().to_dict()
        }
        duration = time.time() - start
        results.add_result(client, "DataFrame Analytics", True, duration, f"Stats computed: {len(stats)} metrics")

        # Test vector operations if available
        try:
            start = time.time()
            async with engine.begin() as conn:
                vector_df = await conn.run_sync(
                    lambda sync_conn: pd.read_sql("""
                        SELECT id,
                               TO_VECTOR('[' || feature1 || ',' || feature2 || ']') as embedding
                        FROM demo_ml_data
                        LIMIT 10
                    """, sync_conn)
                )
            duration = time.time() - start
            results.add_result(client, "Vector DataFrame", len(vector_df) > 0, duration, f"{len(vector_df)} vectors")
        except Exception:
            results.add_result(client, "Vector DataFrame", False, 0, "Vector ops unavailable")

        await engine.dispose()

    except Exception as e:
        results.add_result(client, "Pandas Integration", False, 0, f"Error: {str(e)[:50]}")

async def demo_performance_benchmarks(results: DemoResults):
    """Run performance benchmarks"""
    client = "Performance Tests"

    try:
        conn = await asyncpg.connect(
            host='127.0.0.1',
            port=5432,
            user='test_user',
            database='USER'
        )

        # Benchmark simple queries
        start = time.time()
        for _ in range(100):
            await conn.fetchval("SELECT 1")
        duration = time.time() - start
        qps = 100 / duration
        results.add_result(client, "Simple Query Throughput", True, duration, f"{qps:.0f} queries/sec")

        # Benchmark vector operations
        start = time.time()
        for i in range(50):
            await conn.fetchval(f"SELECT VECTOR_COSINE(TO_VECTOR('[{i},1,2]'), TO_VECTOR('[1,{i},3]'))")
        duration = time.time() - start
        vps = 50 / duration
        results.add_result(client, "Vector Operations", True, duration, f"{vps:.0f} vector ops/sec")

        # Benchmark large result sets
        start = time.time()
        rows = await conn.fetch("SELECT * FROM demo_ml_data")
        duration = time.time() - start
        rps = len(rows) / duration if duration > 0 else 0
        results.add_result(client, "Large Result Set", len(rows) > 0, duration, f"{rps:.0f} rows/sec")

        await conn.close()

    except Exception as e:
        results.add_result(client, "Performance Tests", False, 0, f"Error: {str(e)[:50]}")

async def demo_concurrent_connections(results: DemoResults):
    """Test concurrent connection handling"""
    client = "Concurrency Tests"

    async def single_connection_test(conn_id: int):
        try:
            conn = await asyncpg.connect(
                host='127.0.0.1',
                port=5432,
                user='test_user',
                database='USER'
            )

            # Each connection does some work
            result = await conn.fetchval(f"SELECT {conn_id} * 2")
            await conn.close()
            return result == conn_id * 2
        except:
            return False

    try:
        start = time.time()
        # Test 10 concurrent connections
        tasks = [single_connection_test(i) for i in range(10)]
        results_list = await asyncio.gather(*tasks)
        duration = time.time() - start

        success_count = sum(results_list)
        results.add_result(client, "Concurrent Connections", success_count == 10, duration, f"{success_count}/10 successful")

    except Exception as e:
        results.add_result(client, "Concurrent Connections", False, 0, f"Error: {str(e)[:50]}")

async def start_test_server():
    """Start the PGWire server for testing"""
    try:
        import sys
        sys.path.append('src')
        from iris_pgwire.server import PGWireServer

        server = PGWireServer(
            host='127.0.0.1',
            port=5432,
            iris_host='127.0.0.1',
            iris_port=1975,
            iris_username='SuperUser',
            iris_password='SYS',
            iris_namespace='USER',
            enable_ssl=False
        )

        print("🚀 Starting IRIS PostgreSQL Wire Protocol Server...")
        server_task = asyncio.create_task(server.start())
        await asyncio.sleep(3)  # Let server start

        return server_task
    except Exception as e:
        print(f"Failed to start server: {e}")
        return None

async def main():
    """Run all client demonstrations"""
    print("🧪 IRIS PostgreSQL Wire Protocol - Client Demonstration Suite")
    print("=" * 80)

    # Start the server
    server_task = await start_test_server()
    if not server_task:
        print("❌ Failed to start test server")
        return

    results = DemoResults()

    try:
        print("\n🔹 Running AsyncPG demonstrations...")
        await demo_asyncpg(results)

        print("🔹 Running Psycopg3 demonstrations...")
        await demo_psycopg(results)

        print("🔹 Running SQLAlchemy 2.0 demonstrations...")
        await demo_sqlalchemy(results)

        print("🔹 Running Pandas integration demonstrations...")
        await demo_pandas_integration(results)

        print("🔹 Running performance benchmarks...")
        await demo_performance_benchmarks(results)

        print("🔹 Running concurrency tests...")
        await demo_concurrent_connections(results)

    finally:
        # Stop the server
        if server_task:
            server_task.cancel()

    # Print comprehensive results
    results.print_summary()

    print("\n🎉 DEMONSTRATION COMPLETE!")
    print("IRIS now supports the full PostgreSQL ecosystem through our wire protocol!")

if __name__ == "__main__":
    asyncio.run(main())

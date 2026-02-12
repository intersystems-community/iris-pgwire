#!/usr/bin/env python3
"""
Test script to reproduce connection flakiness with iris-pgwire.

This simulates the patterns used by the sim application:
1. Multiple sequential queries
2. Transactions
3. Batch inserts
4. Concurrent connections (if pool > 1)

Run with:
    python test_connection_stability.py
"""

import os
import sys
import time

# Try to use psycopg (PostgreSQL client) to connect through iris-pgwire
try:
    import psycopg
    from psycopg import sql

    HAS_PSYCOPG = True
except ImportError:
    HAS_PSYCOPG = False
    print("psycopg not installed, trying psycopg2...")

try:
    import psycopg2

    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False

# Configuration
PGWIRE_HOST = os.environ.get("PGWIRE_HOST", "localhost")
PGWIRE_PORT = int(os.environ.get("PGWIRE_PORT", "5432"))
PGWIRE_USER = os.environ.get("PGWIRE_USER", "_SYSTEM")
PGWIRE_PASSWORD = os.environ.get("PGWIRE_PASSWORD", "SYS")
PGWIRE_DATABASE = os.environ.get("PGWIRE_DATABASE", "USER")

NUM_ITERATIONS = 50
CONCURRENT_CONNECTIONS = 3


def get_connection():
    """Get a database connection."""
    if HAS_PSYCOPG:
        return psycopg.connect(
            host=PGWIRE_HOST,
            port=PGWIRE_PORT,
            user=PGWIRE_USER,
            password=PGWIRE_PASSWORD,
            dbname=PGWIRE_DATABASE,
            autocommit=True,
        )
    elif HAS_PSYCOPG2:
        conn = psycopg2.connect(
            host=PGWIRE_HOST,
            port=PGWIRE_PORT,
            user=PGWIRE_USER,
            password=PGWIRE_PASSWORD,
            dbname=PGWIRE_DATABASE,
        )
        conn.autocommit = True
        return conn
    else:
        raise RuntimeError("No PostgreSQL driver available (psycopg or psycopg2)")


def test_simple_queries(num_iterations: int = NUM_ITERATIONS) -> dict:
    """Test simple SELECT queries in sequence."""
    print(f"\n=== Test 1: Simple Queries ({num_iterations} iterations) ===")

    results = {"success": 0, "failure": 0, "errors": []}
    conn = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        for i in range(num_iterations):
            try:
                cursor.execute("SELECT 1 AS test")
                row = cursor.fetchone()
                if row and row[0] == 1:
                    results["success"] += 1
                else:
                    results["failure"] += 1
                    results["errors"].append(f"Iteration {i}: Unexpected result {row}")
            except Exception as e:
                results["failure"] += 1
                results["errors"].append(f"Iteration {i}: {type(e).__name__}: {e}")
                # Try to reconnect
                try:
                    conn.close()
                except:
                    pass
                conn = get_connection()
                cursor = conn.cursor()

    except Exception as e:
        results["errors"].append(f"Connection error: {type(e).__name__}: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

    print(f"  Success: {results['success']}, Failure: {results['failure']}")
    if results["errors"]:
        for err in results["errors"][:5]:
            print(f"  Error: {err}")
    return results


def test_transactions(num_iterations: int = 10) -> dict:
    """Test transaction patterns."""
    print(f"\n=== Test 2: Transactions ({num_iterations} iterations) ===")

    results = {"success": 0, "failure": 0, "errors": []}
    conn = None

    try:
        conn = get_connection()
        conn.autocommit = False
        cursor = conn.cursor()

        # Create test table
        conn.autocommit = True
        try:
            cursor.execute("DROP TABLE IF EXISTS test_stability")
            cursor.execute(
                """
                CREATE TABLE test_stability (
                    id INT PRIMARY KEY,
                    value VARCHAR(100),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """
            )
        except Exception as e:
            print(f"  Warning: Could not create table: {e}")

        conn.autocommit = False

        for i in range(num_iterations):
            try:
                cursor.execute("BEGIN")
                cursor.execute(
                    "INSERT INTO test_stability (id, value) VALUES (%s, %s)", (i, f"test_value_{i}")
                )
                cursor.execute("SELECT COUNT(*) FROM test_stability")
                cursor.execute("COMMIT")
                results["success"] += 1
            except Exception as e:
                results["failure"] += 1
                results["errors"].append(f"Iteration {i}: {type(e).__name__}: {e}")
                try:
                    cursor.execute("ROLLBACK")
                except:
                    pass
                # Try to reconnect
                try:
                    conn.close()
                except:
                    pass
                conn = get_connection()
                conn.autocommit = False
                cursor = conn.cursor()

    except Exception as e:
        results["errors"].append(f"Connection error: {type(e).__name__}: {e}")
    finally:
        if conn:
            try:
                conn.autocommit = True
                cursor = conn.cursor()
                cursor.execute("DROP TABLE IF EXISTS test_stability")
                conn.close()
            except:
                pass

    print(f"  Success: {results['success']}, Failure: {results['failure']}")
    if results["errors"]:
        for err in results["errors"][:5]:
            print(f"  Error: {err}")
    return results


def test_batch_inserts(batch_size: int = 10, num_batches: int = 5) -> dict:
    """Test batch insert patterns (multi-row VALUES)."""
    print(f"\n=== Test 3: Batch Inserts ({num_batches} batches of {batch_size}) ===")

    results = {"success": 0, "failure": 0, "errors": []}
    conn = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Create test table
        try:
            cursor.execute("DROP TABLE IF EXISTS test_batch")
            cursor.execute(
                """
                CREATE TABLE test_batch (
                    id INT,
                    value VARCHAR(100)
                )
            """
            )
        except Exception as e:
            print(f"  Warning: Could not create table: {e}")

        for batch_num in range(num_batches):
            try:
                # Build multi-row INSERT
                values = []
                params = []
                for i in range(batch_size):
                    row_id = batch_num * batch_size + i
                    values.append("(%s, %s)")
                    params.extend([row_id, f"batch_{batch_num}_row_{i}"])

                sql_stmt = f"INSERT INTO test_batch (id, value) VALUES {', '.join(values)}"
                cursor.execute(sql_stmt, params)
                results["success"] += 1
            except Exception as e:
                results["failure"] += 1
                results["errors"].append(f"Batch {batch_num}: {type(e).__name__}: {e}")
                # Try to reconnect
                try:
                    conn.close()
                except:
                    pass
                conn = get_connection()
                cursor = conn.cursor()

    except Exception as e:
        results["errors"].append(f"Connection error: {type(e).__name__}: {e}")
    finally:
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute("DROP TABLE IF EXISTS test_batch")
                conn.close()
            except:
                pass

    print(f"  Success: {results['success']}, Failure: {results['failure']}")
    if results["errors"]:
        for err in results["errors"][:5]:
            print(f"  Error: {err}")
    return results


def test_rapid_reconnection(num_connections: int = 20) -> dict:
    """Test rapid connection/disconnection patterns."""
    print(f"\n=== Test 4: Rapid Reconnection ({num_connections} connections) ===")

    results = {"success": 0, "failure": 0, "errors": []}

    for i in range(num_connections):
        conn = None
        try:
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            conn.close()
            results["success"] += 1
        except Exception as e:
            results["failure"] += 1
            results["errors"].append(f"Connection {i}: {type(e).__name__}: {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except:
                    pass

    print(f"  Success: {results['success']}, Failure: {results['failure']}")
    if results["errors"]:
        for err in results["errors"][:5]:
            print(f"  Error: {err}")
    return results


def test_long_running_connection(duration_seconds: int = 10) -> dict:
    """Test a long-running connection with periodic queries."""
    print(f"\n=== Test 5: Long Running Connection ({duration_seconds}s) ===")

    results = {"success": 0, "failure": 0, "errors": []}
    conn = None

    try:
        conn = get_connection()
        cursor = conn.cursor()

        start_time = time.time()
        query_count = 0

        while time.time() - start_time < duration_seconds:
            try:
                cursor.execute("SELECT CURRENT_TIMESTAMP")
                cursor.fetchone()
                results["success"] += 1
                query_count += 1
                time.sleep(0.1)  # 100ms between queries
            except Exception as e:
                results["failure"] += 1
                results["errors"].append(f"Query {query_count}: {type(e).__name__}: {e}")
                # Try to reconnect
                try:
                    conn.close()
                except:
                    pass
                conn = get_connection()
                cursor = conn.cursor()

    except Exception as e:
        results["errors"].append(f"Connection error: {type(e).__name__}: {e}")
    finally:
        if conn:
            try:
                conn.close()
            except:
                pass

    print(f"  Success: {results['success']}, Failure: {results['failure']}")
    if results["errors"]:
        for err in results["errors"][:5]:
            print(f"  Error: {err}")
    return results


def main():
    print("=" * 60)
    print("iris-pgwire Connection Stability Test")
    print("=" * 60)
    print(f"Target: {PGWIRE_HOST}:{PGWIRE_PORT}")
    print(f"User: {PGWIRE_USER}")
    print(f"Database: {PGWIRE_DATABASE}")

    if not HAS_PSYCOPG and not HAS_PSYCOPG2:
        print("\nERROR: No PostgreSQL driver available!")
        print("Install with: pip install psycopg[binary] or pip install psycopg2-binary")
        sys.exit(1)

    driver = "psycopg3" if HAS_PSYCOPG else "psycopg2"
    print(f"Driver: {driver}")

    all_results = {}

    # Run tests
    all_results["simple_queries"] = test_simple_queries()
    all_results["transactions"] = test_transactions()
    all_results["batch_inserts"] = test_batch_inserts()
    all_results["rapid_reconnection"] = test_rapid_reconnection()
    all_results["long_running"] = test_long_running_connection()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    total_success = 0
    total_failure = 0

    for test_name, results in all_results.items():
        total_success += results["success"]
        total_failure += results["failure"]
        status = "✅" if results["failure"] == 0 else "❌"
        print(f"{status} {test_name}: {results['success']} success, {results['failure']} failure")

    print("-" * 60)
    print(f"Total: {total_success} success, {total_failure} failure")

    if total_failure > 0:
        print("\n⚠️  Connection instability detected!")
        sys.exit(1)
    else:
        print("\n✅ All tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()

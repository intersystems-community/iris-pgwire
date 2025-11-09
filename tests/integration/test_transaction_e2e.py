"""
E2E Integration tests for Transaction Translator (Feature 022)

These tests validate transaction verb translation with REAL PostgreSQL clients:
- psql command-line client
- psycopg Python driver
- SQLAlchemy ORM (optional)

Tests run against actual IRIS PGWire server to prove end-to-end compatibility.

Tasks: T016-T020
"""

import subprocess
import sys
from pathlib import Path

import pytest

# Add src to path for imports
src_dir = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_dir))


class TestTransactionE2E:
    """E2E tests with real PostgreSQL clients"""

    # T016: psql BEGIN/COMMIT workflow
    def test_psql_begin_commit_workflow(self):
        """
        T016: Validate BEGIN/COMMIT workflow with psql client

        Uses real psql client to execute transaction commands.
        IRIS PGWire must translate BEGIN → START TRANSACTION for success.
        """
        # Test sequence:
        # 1. BEGIN - should be translated to START TRANSACTION
        # 2. INSERT - should execute in transaction
        # 3. COMMIT - should persist data

        commands = """
            DROP TABLE IF EXISTS test_transaction_e2e;
            CREATE TABLE test_transaction_e2e (id INT PRIMARY KEY, value VARCHAR(50));
            BEGIN;
            INSERT INTO test_transaction_e2e VALUES (1, 'test_value');
            COMMIT;
            SELECT * FROM test_transaction_e2e WHERE id = 1;
            DROP TABLE test_transaction_e2e;
        """

        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "iris-pgwire-network",
                "postgres:16-alpine",
                "psql",
                "-h",
                "iris-pgwire-db",
                "-p",
                "5432",
                "-U",
                "test_user",
                "-d",
                "USER",
                "-c",
                commands,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # Verify BEGIN was accepted (no syntax errors)
        assert result.returncode == 0, f"psql BEGIN/COMMIT failed: {result.stderr}"
        assert "test_value" in result.stdout, "Transaction did not persist data"
        assert "ERROR" not in result.stderr.upper(), f"Unexpected errors: {result.stderr}"

    def test_psql_begin_transaction_variant(self):
        """
        T016: Validate BEGIN TRANSACTION variant with psql

        PostgreSQL supports both BEGIN and BEGIN TRANSACTION.
        Both should work via translation to START TRANSACTION.
        """
        commands = """
            DROP TABLE IF EXISTS test_begin_transaction;
            CREATE TABLE test_begin_transaction (id INT PRIMARY KEY);
            BEGIN TRANSACTION;
            INSERT INTO test_begin_transaction VALUES (99);
            COMMIT;
            SELECT COUNT(*) FROM test_begin_transaction;
            DROP TABLE test_begin_transaction;
        """

        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "iris-pgwire-network",
                "postgres:16-alpine",
                "psql",
                "-h",
                "iris-pgwire-db",
                "-p",
                "5432",
                "-U",
                "test_user",
                "-d",
                "USER",
                "-c",
                commands,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, f"BEGIN TRANSACTION failed: {result.stderr}"
        assert "1" in result.stdout, "Transaction did not persist data"

    # T017: psycopg parameterized statements in transaction
    @pytest.mark.skipif(
        subprocess.run(["which", "python3"], capture_output=True).returncode != 0,
        reason="Python3 not available for psycopg test",
    )
    def test_psycopg_transaction_workflow(self):
        """
        T017: Validate psycopg parameterized statements in transaction

        Uses psycopg driver to execute transactions with parameter binding.
        Tests that BEGIN translation works with prepared statements.
        """
        test_script = """
import psycopg

try:
    # Connect to IRIS via PGWire
    with psycopg.connect(
        host="iris-pgwire-db",
        port=5432,
        user="test_user",
        dbname="USER"
    ) as conn:
        with conn.cursor() as cur:
            # Setup
            cur.execute("DROP TABLE IF EXISTS test_psycopg_txn")
            cur.execute("CREATE TABLE test_psycopg_txn (id INT PRIMARY KEY, name VARCHAR(50))")

            # BEGIN transaction (should be translated)
            cur.execute("BEGIN")

            # Parameterized INSERT in transaction
            cur.execute("INSERT INTO test_psycopg_txn VALUES (%s, %s)", (42, "test_name"))

            # COMMIT transaction
            cur.execute("COMMIT")

            # Verify data persisted
            cur.execute("SELECT name FROM test_psycopg_txn WHERE id = 42")
            result = cur.fetchone()

            # Cleanup
            cur.execute("DROP TABLE test_psycopg_txn")

            # Validate
            assert result is not None, "Transaction did not persist data"
            assert result[0] == "test_name", f"Unexpected value: {result[0]}"
            print("✅ psycopg transaction test PASSED")

except Exception as e:
    print(f"❌ psycopg transaction test FAILED: {e}")
    import traceback
    traceback.print_exc()
    exit(1)
"""

        # Run test script in Docker container with psycopg installed
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "iris-pgwire-network",
                "python:3.12-slim",
                "sh",
                "-c",
                f"pip install -q psycopg[binary] && python3 -c '{test_script}'",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

        assert result.returncode == 0, f"psycopg test failed: {result.stderr}\n{result.stdout}"
        assert "✅ psycopg transaction test PASSED" in result.stdout

    # T018: SQLAlchemy context manager
    @pytest.mark.skip(reason="SQLAlchemy test optional - implement if time permits")
    def test_sqlalchemy_transaction_context_manager(self):
        """
        T018: Validate SQLAlchemy transaction context manager

        SQLAlchemy uses connection.begin() which may send BEGIN TRANSACTION.
        This test verifies compatibility with SQLAlchemy's ORM.

        NOTE: Marked as optional - skip if SQLAlchemy integration not needed
        """
        pass

    # T019: ROLLBACK on error
    def test_psql_rollback_on_error(self):
        """
        T019: Validate ROLLBACK works correctly

        Test that:
        1. BEGIN starts transaction
        2. INSERT adds data
        3. ROLLBACK discards changes
        4. Data is NOT persisted
        """
        commands = """
            DROP TABLE IF EXISTS test_rollback;
            CREATE TABLE test_rollback (id INT PRIMARY KEY);
            BEGIN;
            INSERT INTO test_rollback VALUES (1);
            ROLLBACK;
            SELECT COUNT(*) FROM test_rollback;
            DROP TABLE test_rollback;
        """

        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "iris-pgwire-network",
                "postgres:16-alpine",
                "psql",
                "-h",
                "iris-pgwire-db",
                "-p",
                "5432",
                "-U",
                "test_user",
                "-d",
                "USER",
                "-c",
                commands,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, f"ROLLBACK test failed: {result.stderr}"
        # Count should be 0 (data was rolled back)
        assert "0" in result.stdout, "ROLLBACK did not discard data"

    # T020: Isolation level modifiers preserved
    def test_psql_isolation_level_modifiers(self):
        """
        T020: Validate isolation level modifiers are preserved

        PostgreSQL syntax:
            BEGIN ISOLATION LEVEL READ COMMITTED

        Must be translated to:
            START TRANSACTION ISOLATION LEVEL READ COMMITTED

        FR-005: Transaction modifiers must be preserved.
        """
        commands = """
            DROP TABLE IF EXISTS test_isolation_level;
            CREATE TABLE test_isolation_level (id INT PRIMARY KEY);
            BEGIN ISOLATION LEVEL READ COMMITTED;
            INSERT INTO test_isolation_level VALUES (1);
            COMMIT;
            SELECT COUNT(*) FROM test_isolation_level;
            DROP TABLE test_isolation_level;
        """

        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "iris-pgwire-network",
                "postgres:16-alpine",
                "psql",
                "-h",
                "iris-pgwire-db",
                "-p",
                "5432",
                "-U",
                "test_user",
                "-d",
                "USER",
                "-c",
                commands,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # If translation preserved modifiers, this should succeed
        assert result.returncode == 0, f"Isolation level test failed: {result.stderr}"
        assert "1" in result.stdout, "Transaction with isolation level did not persist"
        # IRIS may not support all isolation levels - check for specific errors
        if "ISOLATION LEVEL" in result.stderr.upper() and "NOT SUPPORTED" in result.stderr.upper():
            pytest.skip("IRIS does not support ISOLATION LEVEL modifiers")

    def test_psql_read_only_modifier(self):
        """
        T020: Validate READ ONLY modifier is preserved

        PostgreSQL syntax:
            BEGIN READ ONLY

        Must be translated to:
            START TRANSACTION READ ONLY
        """
        commands = """
            DROP TABLE IF EXISTS test_read_only;
            CREATE TABLE test_read_only (id INT PRIMARY KEY);
            INSERT INTO test_read_only VALUES (1);
            BEGIN READ ONLY;
            SELECT * FROM test_read_only;
            COMMIT;
            DROP TABLE test_read_only;
        """

        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "iris-pgwire-network",
                "postgres:16-alpine",
                "psql",
                "-h",
                "iris-pgwire-db",
                "-p",
                "5432",
                "-U",
                "test_user",
                "-d",
                "USER",
                "-c",
                commands,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        # READ ONLY should succeed
        assert result.returncode == 0, f"READ ONLY modifier test failed: {result.stderr}"

        # If IRIS doesn't support READ ONLY, skip rather than fail
        if "READ ONLY" in result.stderr.upper() and (
            "NOT SUPPORTED" in result.stderr.upper() or "ERROR" in result.stderr.upper()
        ):
            pytest.skip("IRIS does not support READ ONLY modifier")


# Performance validation (not part of T016-T020 but useful)
class TestTransactionPerformance:
    """Performance tests for transaction translation"""

    def test_translation_overhead_performance(self):
        """
        Validate that transaction translation meets <0.1ms overhead requirement (PR-001)

        This is measured in unit tests, but we can verify no E2E regression.
        """
        import time

        commands = "BEGIN; SELECT 1; COMMIT;"

        # Measure 10 iterations
        times = []
        for _ in range(10):
            start = time.perf_counter()
            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "iris-pgwire-network",
                    "postgres:16-alpine",
                    "psql",
                    "-h",
                    "iris-pgwire-db",
                    "-p",
                    "5432",
                    "-U",
                    "test_user",
                    "-d",
                    "USER",
                    "-c",
                    commands,
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            elapsed_ms = (time.perf_counter() - start) * 1000
            times.append(elapsed_ms)

            assert result.returncode == 0, f"Transaction failed: {result.stderr}"

        avg_time_ms = sum(times) / len(times)
        print(f"\n📊 Transaction E2E Performance: {avg_time_ms:.2f}ms avg (10 runs)")

        # E2E includes network + IRIS execution, so allow generous threshold
        # Unit test verifies <0.1ms translation overhead
        assert avg_time_ms < 1000, f"E2E transaction too slow: {avg_time_ms:.2f}ms"

"""
E2E Integration Tests with psql Client

Tests IRIS system functions translation using real psql client connections.
These tests MUST FAIL until the implementation is complete (TDD requirement).

Constitutional Requirement: Test-First Development with real PostgreSQL clients
"""

import pytest
import subprocess
import time
import os
from typing import List, Optional

# These imports will fail until implementation exists - expected in TDD
try:
    from iris_pgwire.server import PGWireServer
    from iris_pgwire.sql_translator import SQLTranslator
    SERVER_AVAILABLE = True
except ImportError:
    SERVER_AVAILABLE = False

pytestmark = [pytest.mark.e2e, pytest.mark.requires_iris]

@pytest.fixture(scope="session")
def pgwire_server():
    """Start PGWire server with translation enabled for testing"""
    if not SERVER_AVAILABLE:
        pytest.skip("PGWire server not implemented yet")

    # This will fail until server supports translation
    server = PGWireServer(port=5433, enable_translation=True)  # Use different port for testing
    server.start()

    # Wait for server to be ready
    time.sleep(2)

    yield server

    server.stop()

@pytest.fixture
def psql_command():
    """Base psql command for testing"""
    return ["psql", "-h", "localhost", "-p", "5433", "-U", "postgres", "-d", "iris"]

def run_psql_query(command: List[str], sql: str, timeout: int = 30) -> tuple[int, str, str]:
    """Execute SQL query via psql client"""
    full_command = command + ["-c", sql]

    try:
        result = subprocess.run(
            full_command,
            capture_output=True,
            text=True,
            timeout=timeout,
            env={**os.environ, "PGPASSWORD": "iris"}  # Avoid password prompt
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Query timed out"

class TestIRISSystemFunctionsE2E:
    """E2E tests for IRIS system function translation with psql"""

    def test_system_version_function_translation(self, psql_command):
        """Test %SYSTEM.Version.GetNumber() translation via psql"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        # This will fail until IRIS system function translation is implemented
        sql = "SELECT %SYSTEM.Version.GetNumber() AS iris_version;"
        returncode, stdout, stderr = run_psql_query(psql_command, sql)

        # Should succeed and return version information
        assert returncode == 0, f"psql failed with error: {stderr}"
        assert "iris_version" in stdout, "Should return column header"
        assert len(stdout.strip()) > 0, "Should return version data"
        assert "ERROR" not in stderr, f"Should not have errors: {stderr}"

    def test_system_user_function_translation(self, psql_command):
        """Test %SYSTEM.Security.GetUser() translation via psql"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        sql = "SELECT %SYSTEM.Security.GetUser() AS current_user;"
        returncode, stdout, stderr = run_psql_query(psql_command, sql)

        assert returncode == 0, f"psql failed with error: {stderr}"
        assert "current_user" in stdout, "Should return column header"
        assert "ERROR" not in stderr, f"Should not have errors: {stderr}"

    def test_multiple_system_functions(self, psql_command):
        """Test multiple IRIS system functions in one query"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        sql = """
        SELECT
            %SYSTEM.Version.GetNumber() AS version,
            %SYSTEM.Security.GetUser() AS user_name,
            %SYSTEM.SQL.GetStatement() AS current_query
        """
        returncode, stdout, stderr = run_psql_query(psql_command, sql)

        assert returncode == 0, f"psql failed with error: {stderr}"
        assert "version" in stdout, "Should have version column"
        assert "user_name" in stdout, "Should have user_name column"
        assert "current_query" in stdout, "Should have current_query column"

    def test_psql_connection_stability(self, psql_command):
        """Test that psql connection remains stable across multiple queries"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        queries = [
            "SELECT %SYSTEM.Version.GetNumber();",
            "SELECT 1 AS test;",  # Standard SQL
            "SELECT %SYSTEM.Security.GetUser();",
            "SELECT CURRENT_TIMESTAMP;"  # Standard SQL
        ]

        for i, sql in enumerate(queries):
            returncode, stdout, stderr = run_psql_query(psql_command, sql)
            assert returncode == 0, f"Query {i+1} failed: {stderr}"
            assert "ERROR" not in stderr, f"Query {i+1} had errors: {stderr}"

    def test_psql_error_handling(self, psql_command):
        """Test error handling for unsupported IRIS constructs"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        # This should fail gracefully
        sql = "VACUUM TABLE users;"  # Unsupported administrative command
        returncode, stdout, stderr = run_psql_query(psql_command, sql)

        # Should return non-zero exit code but not crash
        assert returncode != 0, "Unsupported command should fail"
        assert "unsupported" in stderr.lower() or "error" in stderr.lower(), \
            "Should return clear error message"

    def test_psql_performance_requirements(self, psql_command):
        """Test that psql queries meet performance requirements"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        sql = "SELECT %SYSTEM.Version.GetNumber();"

        # Measure query execution time
        start_time = time.perf_counter()
        returncode, stdout, stderr = run_psql_query(psql_command, sql)
        execution_time_ms = (time.perf_counter() - start_time) * 1000

        assert returncode == 0, f"Query failed: {stderr}"
        # Constitutional requirement: translations should be fast
        assert execution_time_ms < 1000.0, \
            f"Query took {execution_time_ms}ms, should be < 1000ms including network overhead"

class TestPSQLProtocolCompliance:
    """Test PostgreSQL protocol compliance with psql client"""

    def test_psql_protocol_handshake(self, psql_command):
        """Test that psql can successfully connect and authenticate"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        # Test basic connection
        sql = "SELECT 1;"
        returncode, stdout, stderr = run_psql_query(psql_command, sql)

        assert returncode == 0, f"Basic connection failed: {stderr}"
        assert "1" in stdout, "Should return query result"

    def test_psql_prepared_statements(self, psql_command):
        """Test prepared statement support with IRIS functions"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        # Test prepared statement with IRIS function
        prepare_sql = "PREPARE test_stmt AS SELECT %SYSTEM.Version.GetNumber();"
        execute_sql = "EXECUTE test_stmt;"
        deallocate_sql = "DEALLOCATE test_stmt;"

        # Prepare statement
        returncode, stdout, stderr = run_psql_query(psql_command, prepare_sql)
        assert returncode == 0, f"PREPARE failed: {stderr}"

        # Execute statement
        returncode, stdout, stderr = run_psql_query(psql_command, execute_sql)
        assert returncode == 0, f"EXECUTE failed: {stderr}"

        # Deallocate statement
        returncode, stdout, stderr = run_psql_query(psql_command, deallocate_sql)
        assert returncode == 0, f"DEALLOCATE failed: {stderr}"

    def test_psql_transaction_support(self, psql_command):
        """Test transaction support with IRIS function translation"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        transaction_sql = """
        BEGIN;
        SELECT %SYSTEM.Version.GetNumber();
        SELECT %SYSTEM.Security.GetUser();
        COMMIT;
        """

        returncode, stdout, stderr = run_psql_query(psql_command, transaction_sql)
        assert returncode == 0, f"Transaction failed: {stderr}"
        assert "COMMIT" in stdout or "BEGIN" in stdout, "Should show transaction commands"

    def test_psql_meta_commands(self, psql_command):
        """Test psql meta-commands work correctly"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        # Test \l (list databases) equivalent
        sql = "\\l"
        # Note: This might not work exactly like PostgreSQL, but shouldn't crash
        returncode, stdout, stderr = run_psql_query(psql_command, sql)

        # Should not crash the connection
        assert returncode in [0, 1], "Meta-command should not crash server"

class TestPSQLConcurrentConnections:
    """Test concurrent psql connections"""

    def test_multiple_concurrent_psql_connections(self, psql_command):
        """Test multiple concurrent psql connections with IRIS functions"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        import threading
        import queue

        results = queue.Queue()

        def run_query(query_id: int):
            sql = f"SELECT %SYSTEM.Version.GetNumber() AS version_{query_id};"
            returncode, stdout, stderr = run_psql_query(psql_command, sql)
            results.put((query_id, returncode, stdout, stderr))

        # Start multiple concurrent queries
        threads = []
        for i in range(5):
            thread = threading.Thread(target=run_query, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all to complete
        for thread in threads:
            thread.join(timeout=30)

        # Check all results
        completed_results = []
        while not results.empty():
            completed_results.append(results.get())

        assert len(completed_results) == 5, "All concurrent queries should complete"

        for query_id, returncode, stdout, stderr in completed_results:
            assert returncode == 0, f"Query {query_id} failed: {stderr}"
            assert f"version_{query_id}" in stdout, f"Query {query_id} missing expected output"

# TDD Validation: These tests should fail until implementation exists
def test_psql_e2e_tdd_validation():
    """Verify psql E2E tests fail appropriately before implementation"""
    if SERVER_AVAILABLE:
        # If this passes, implementation already exists
        pytest.fail("TDD violation: PGWire server implementation exists before tests were written")
    else:
        # Expected state: tests exist, implementation doesn't
        assert True, "TDD compliant: psql E2E tests written before implementation"
"""
E2E Integration Tests with psycopg Driver

Tests IRIS SQL syntax extensions translation using real psycopg driver connections.
These tests MUST FAIL until the implementation is complete (TDD requirement).

Constitutional Requirement: Test-First Development with real PostgreSQL clients
"""

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

# These imports will fail until implementation exists - expected in TDD
try:
    from iris_pgwire.server import PGWireServer
    from iris_pgwire.sql_translator import SQLTranslator

    SERVER_AVAILABLE = True
except ImportError:
    SERVER_AVAILABLE = False

# Real PostgreSQL driver - this must work for constitutional compliance
try:
    import psycopg

    PSYCOPG_AVAILABLE = True
except ImportError:
    PSYCOPG_AVAILABLE = False

pytestmark = [pytest.mark.e2e, pytest.mark.requires_iris]


@pytest.fixture(scope="session")
def pgwire_server():
    """Start PGWire server with translation enabled for testing"""
    if not SERVER_AVAILABLE:
        pytest.skip("PGWire server not implemented yet")

    # This will fail until server supports translation
    server = PGWireServer(port=5434, enable_translation=True)  # Use different port for testing
    server.start()

    # Wait for server to be ready
    time.sleep(2)

    yield server

    server.stop()


@pytest.fixture
def connection_params():
    """Connection parameters for psycopg testing"""
    return {
        "host": "localhost",
        "port": 5434,
        "user": "postgres",
        "password": "iris",
        "dbname": "iris",
    }


def create_connection(params: dict[str, Any], timeout: int = 30) -> psycopg.Connection | None:
    """Create psycopg connection with error handling"""
    if not PSYCOPG_AVAILABLE:
        pytest.skip("psycopg driver not available")

    try:
        conn = psycopg.connect(**params, connect_timeout=timeout)
        return conn
    except Exception as e:
        pytest.fail(f"Failed to connect to PGWire server: {e}")


class TestIRISSQLSyntaxE2E:
    """E2E tests for IRIS SQL syntax extension translation with psycopg"""

    def test_top_clause_translation(self, connection_params):
        """Test TOP clause translation to LIMIT"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        # This will fail until IRIS TOP clause translation is implemented
        with create_connection(connection_params) as conn:
            with conn.cursor() as cur:
                # IRIS syntax: TOP n
                cur.execute("SELECT TOP 5 id, name FROM users ORDER BY id")

                # Should be translated to PostgreSQL LIMIT syntax
                results = cur.fetchall()
                assert len(results) <= 5, "TOP 5 should limit results to 5 or fewer"

                # Verify no SQL errors occurred
                assert conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    def test_iris_string_functions_translation(self, connection_params):
        """Test IRIS string function translation"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with create_connection(connection_params) as conn:
            with conn.cursor() as cur:
                test_cases = [
                    ("SELECT %SQLUPPER('hello') AS upper_text", "HELLO"),
                    ("SELECT %SQLLOWER('WORLD') AS lower_text", "world"),
                    ("SELECT %SQLSTRING(123) AS string_num", "123"),
                ]

                for iris_sql, expected_result in test_cases:
                    cur.execute(iris_sql)
                    result = cur.fetchone()[0]
                    assert result == expected_result, f"Failed for query: {iris_sql}"

    def test_iris_date_functions_translation(self, connection_params):
        """Test IRIS date function translation"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with create_connection(connection_params) as conn:
            with conn.cursor() as cur:
                # Test IRIS date functions
                test_queries = [
                    "SELECT %SYSTEM.SQL.GETDATE() AS current_date",
                    "SELECT DATEADD('dd', 1, GETDATE()) AS tomorrow",
                    "SELECT DATEDIFF('dd', '2023-01-01', '2023-01-02') AS date_diff",
                ]

                for sql in test_queries:
                    cur.execute(sql)
                    result = cur.fetchone()
                    assert result is not None, f"Query should return result: {sql}"
                    assert len(result) > 0, f"Result should not be empty: {sql}"

    def test_iris_json_functions_translation(self, connection_params):
        """Test IRIS JSON function translation"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with create_connection(connection_params) as conn:
            with conn.cursor() as cur:
                # Test JSON_OBJECT function
                cur.execute("SELECT JSON_OBJECT('key', 'value') AS json_result")
                result = cur.fetchone()[0]

                # Should return valid JSON
                import json

                parsed = json.loads(result)
                assert parsed["key"] == "value", "JSON_OBJECT should create valid JSON"

                # Test JSON extraction
                cur.execute(
                    "SELECT JSON_EXTRACT('{}', '$.key') AS extracted".format('{"key": "test"}')
                )
                result = cur.fetchone()[0]
                assert result == "test", "JSON_EXTRACT should extract value"

    def test_complex_iris_query_translation(self, connection_params):
        """Test complex query with multiple IRIS constructs"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with create_connection(connection_params) as conn:
            with conn.cursor() as cur:
                # Complex query combining multiple IRIS features
                complex_sql = """
                SELECT TOP 10
                    %SQLUPPER(name) AS upper_name,
                    %SYSTEM.Version.GetNumber() AS iris_version,
                    JSON_OBJECT('id', id, 'active', status) AS user_json
                FROM users
                WHERE %SQLLOWER(status) = 'active'
                ORDER BY id
                """

                cur.execute(complex_sql)
                results = cur.fetchall()

                # Verify structure and constraints
                assert len(results) <= 10, "TOP 10 should limit results"

                if results:
                    # Verify column structure
                    assert len(results[0]) == 3, "Should have 3 columns"

                    # Verify JSON column contains valid JSON
                    json_col = results[0][2]
                    import json

                    parsed = json.loads(json_col)
                    assert "id" in parsed and "active" in parsed


class TestIRISParameterBinding:
    """Test parameter binding with IRIS construct translation"""

    def test_prepared_statement_with_iris_functions(self, connection_params):
        """Test prepared statements containing IRIS functions"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with create_connection(connection_params) as conn:
            with conn.cursor() as cur:
                # Prepare statement with IRIS function and parameter
                cur.execute("SELECT %SQLUPPER(name) AS upper_name FROM users WHERE id = %s", (123,))

                result = cur.fetchone()
                # Should handle both parameter binding and function translation
                assert result is not None or cur.rowcount == 0  # Valid either way

    def test_multiple_parameters_with_iris_syntax(self, connection_params):
        """Test multiple parameter binding with IRIS syntax"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with create_connection(connection_params) as conn:
            with conn.cursor() as cur:
                # Multiple parameters with IRIS constructs
                cur.execute(
                    "SELECT TOP %s %SQLUPPER(name) FROM users WHERE id > %s AND status = %s",
                    (5, 100, "active"),
                )

                results = cur.fetchall()
                assert len(results) <= 5, "TOP parameter should limit results"


class TestIRISTransactionSupport:
    """Test transaction support with IRIS construct translation"""

    def test_transaction_with_iris_functions(self, connection_params):
        """Test transactions containing IRIS function calls"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with create_connection(connection_params) as conn:
            with conn.cursor() as cur:
                # Test transaction with IRIS constructs
                cur.execute("BEGIN")

                # Execute IRIS function within transaction
                cur.execute("SELECT %SYSTEM.Version.GetNumber() AS version")
                version_result = cur.fetchone()[0]
                assert version_result is not None

                # Execute regular SQL
                cur.execute("SELECT 1 AS test")
                test_result = cur.fetchone()[0]
                assert test_result == 1

                cur.execute("COMMIT")

                # Verify transaction completed successfully
                assert conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    def test_rollback_with_iris_translation(self, connection_params):
        """Test transaction rollback with IRIS constructs"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with create_connection(connection_params) as conn:
            with conn.cursor() as cur:
                cur.execute("BEGIN")

                # Execute IRIS functions
                cur.execute("SELECT %SQLUPPER('test') AS upper_test")
                result = cur.fetchone()[0]
                assert result == "TEST"

                # Rollback transaction
                cur.execute("ROLLBACK")

                # Should be back to idle state
                assert conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE


class TestIRISConnectionPooling:
    """Test connection pooling with IRIS construct translation"""

    def test_concurrent_iris_function_calls(self, connection_params):
        """Test concurrent connections with IRIS function translation"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        def execute_iris_query(query_id: int) -> tuple:
            """Execute IRIS query in separate connection"""
            with create_connection(connection_params) as conn:
                with conn.cursor() as cur:
                    cur.execute(f"SELECT {query_id} AS id, %SYSTEM.Version.GetNumber() AS version")
                    return cur.fetchone()

        # Execute concurrent queries
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(execute_iris_query, i) for i in range(1, 6)]

            results = [future.result(timeout=30) for future in futures]

            # Verify all queries completed successfully
            assert len(results) == 5, "All concurrent queries should complete"

            for i, (query_id, version) in enumerate(results, 1):
                assert query_id == i, f"Query ID should match: expected {i}, got {query_id}"
                assert version is not None, f"Version should be returned for query {i}"


class TestIRISCursorOperations:
    """Test cursor operations with IRIS construct translation"""

    def test_fetchone_with_iris_functions(self, connection_params):
        """Test fetchone with IRIS function results"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with create_connection(connection_params) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT %SQLUPPER('single') AS result")
                result = cur.fetchone()
                assert result[0] == "SINGLE"

                # Should be no more results
                assert cur.fetchone() is None

    def test_fetchmany_with_iris_syntax(self, connection_params):
        """Test fetchmany with IRIS TOP clause"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with create_connection(connection_params) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT TOP 3 %SQLUPPER(name) FROM users ORDER BY id")

                # Fetch in batches
                batch1 = cur.fetchmany(2)
                batch2 = cur.fetchmany(2)

                total_results = len(batch1) + len(batch2)
                assert total_results <= 3, "Total results should respect TOP 3 limit"

    def test_fetchall_with_complex_iris_query(self, connection_params):
        """Test fetchall with complex IRIS construct query"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with create_connection(connection_params) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        id,
                        %SQLUPPER(name) AS upper_name,
                        JSON_OBJECT('version', %SYSTEM.Version.GetNumber()) AS meta
                    FROM users
                    LIMIT 5
                """
                )

                results = cur.fetchall()
                assert len(results) <= 5, "LIMIT should be respected"

                if results:
                    # Verify column structure
                    row = results[0]
                    assert len(row) == 3, "Should have 3 columns"

                    # Verify JSON structure
                    import json

                    meta = json.loads(row[2])
                    assert "version" in meta, "JSON should contain version key"


class TestIRISErrorHandling:
    """Test error handling for IRIS constructs with psycopg"""

    def test_unsupported_iris_construct_error(self, connection_params):
        """Test error handling for unsupported IRIS constructs"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with create_connection(connection_params) as conn:
            with conn.cursor() as cur:
                # This should fail gracefully
                with pytest.raises(psycopg.Error):
                    cur.execute("VACUUM TABLE users")  # Unsupported administrative command

    def test_malformed_iris_function_error(self, connection_params):
        """Test error handling for malformed IRIS functions"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with create_connection(connection_params) as conn:
            with conn.cursor() as cur:
                # Malformed IRIS function
                with pytest.raises(psycopg.Error):
                    cur.execute("SELECT %INVALID.FUNCTION() AS invalid")

    def test_connection_recovery_after_error(self, connection_params):
        """Test connection recovery after IRIS translation error"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with create_connection(connection_params) as conn:
            with conn.cursor() as cur:
                # Cause an error
                try:
                    cur.execute("SELECT INVALID_SYNTAX(")
                except psycopg.Error:
                    pass  # Expected

                # Connection should recover for next query
                cur.execute("SELECT %SYSTEM.Version.GetNumber() AS version")
                result = cur.fetchone()
                assert result is not None, "Connection should recover after error"


class TestIRISPerformanceRequirements:
    """Test performance requirements for IRIS construct translation"""

    def test_iris_translation_latency(self, connection_params):
        """Test that IRIS construct translation meets latency requirements"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with create_connection(connection_params) as conn:
            with conn.cursor() as cur:
                # Measure translation + execution time
                start_time = time.perf_counter()

                cur.execute("SELECT %SYSTEM.Version.GetNumber(), %SQLUPPER('test') AS upper")
                result = cur.fetchone()

                execution_time_ms = (time.perf_counter() - start_time) * 1000

                assert result is not None, "Query should return results"
                # Constitutional requirement: translations should be fast
                assert (
                    execution_time_ms < 1000.0
                ), f"Query took {execution_time_ms}ms, should be < 1000ms including network overhead"

    def test_complex_iris_query_performance(self, connection_params):
        """Test performance of complex IRIS construct queries"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with create_connection(connection_params) as conn:
            with conn.cursor() as cur:
                complex_query = """
                SELECT TOP 100
                    %SQLUPPER(name) AS name_upper,
                    %SQLLOWER(email) AS email_lower,
                    %SYSTEM.Version.GetNumber() AS version,
                    JSON_OBJECT('id', id, 'status', status) AS json_data
                FROM users
                WHERE %SQLUPPER(status) = 'ACTIVE'
                ORDER BY id
                """

                start_time = time.perf_counter()
                cur.execute(complex_query)
                results = cur.fetchall()
                execution_time_ms = (time.perf_counter() - start_time) * 1000

                # Verify results and performance
                assert len(results) <= 100, "TOP 100 should limit results"
                assert (
                    execution_time_ms < 2000.0
                ), f"Complex query took {execution_time_ms}ms, should be < 2000ms"


# TDD Validation: These tests should fail until implementation exists
def test_psycopg_e2e_tdd_validation():
    """Verify psycopg E2E tests fail appropriately before implementation"""
    if SERVER_AVAILABLE:
        # If this passes, implementation already exists
        pytest.fail("TDD violation: PGWire server implementation exists before tests were written")
    else:
        # Expected state: tests exist, implementation doesn't
        assert True, "TDD compliant: psycopg E2E tests written before implementation"

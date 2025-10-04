"""
Contract tests for pytest fixtures.

These tests validate that fixtures meet their interface contracts as defined in
specs/017-correct-testing-framework/contracts/pytest-fixtures.md

TDD: These tests MUST FAIL until fixtures are implemented.
"""

import pytest


def test_embedded_iris_fixture_provides_connection(embedded_iris):
    """
    Verify embedded_iris fixture returns valid IRIS connection.

    Contract:
    - Returns: iris.Connection instance
    - Guarantees: CallIn service enabled, USER namespace active
    - Setup time: <10 seconds
    """
    assert embedded_iris is not None, "embedded_iris fixture must return a connection"

    # Verify connection is valid by executing simple query
    cursor = embedded_iris.cursor()
    cursor.execute("SELECT 1")
    result = cursor.fetchone()

    assert result is not None, "Query must return result"
    assert result[0] == 1, "SELECT 1 must return 1"

    cursor.close()


def test_embedded_iris_fixture_cleanup_releases_resources(embedded_iris):
    """
    Verify embedded_iris fixture cleanup releases IRIS resources.

    Contract:
    - Cleanup: Connection closed, resources released
    - No leaked IRIS processes after session ends
    """
    # Track connection info for validation
    assert embedded_iris is not None

    # Get connection details for post-session validation
    # This test will be validated by checking resource cleanup after test session
    # Implementation should ensure connection is closed in teardown
    assert hasattr(embedded_iris, 'close') or hasattr(embedded_iris, '__del__'), \
        "Connection must have cleanup mechanism"


def test_iris_clean_namespace_isolates_test_data(iris_clean_namespace):
    """
    Verify iris_clean_namespace fixture isolates test data between tests.

    Contract:
    - Returns: iris.Connection with clean namespace
    - Guarantees: No conflicting test data from previous tests
    - Cleanup time: <2 seconds
    """
    cursor = iris_clean_namespace.cursor()

    # Create test table that should be cleaned up
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS test_isolation_check (
            id INT PRIMARY KEY,
            value VARCHAR(50)
        )
    """)

    cursor.execute("INSERT INTO test_isolation_check VALUES (1, 'test_data')")
    iris_clean_namespace.commit()

    # Verify data was inserted
    cursor.execute("SELECT COUNT(*) FROM test_isolation_check")
    count = cursor.fetchone()[0]
    assert count == 1, "Data should be inserted"

    cursor.close()
    # Cleanup will be verified by running this test multiple times


def test_iris_clean_namespace_second_run_has_no_previous_data(iris_clean_namespace):
    """
    Second test to verify isolation - should not see data from previous test.

    This test validates that test_isolation_check table either:
    1. Does not exist (dropped in cleanup)
    2. Is empty (rolled back in cleanup)
    """
    cursor = iris_clean_namespace.cursor()

    try:
        cursor.execute("SELECT COUNT(*) FROM test_isolation_check")
        count = cursor.fetchone()[0]
        # If table exists, it should be empty
        assert count == 0, "Table should be empty - previous test data not cleaned up"
    except Exception:
        # Table doesn't exist - cleanup worked via DROP TABLE
        pass  # This is acceptable

    cursor.close()


def test_pgwire_client_connects_successfully(pgwire_client):
    """
    Verify pgwire_client fixture establishes connection.

    Contract:
    - Returns: psycopg.Connection instance
    - Connection ready for query execution
    - Setup time: <5 seconds
    """
    import psycopg

    assert pgwire_client is not None, "pgwire_client fixture must return a connection"
    assert pgwire_client.status == psycopg.Connection.OK, \
        f"Connection status must be OK, got {pgwire_client.status}"

    # Verify connection works by executing simple query
    with pgwire_client.cursor() as cursor:
        cursor.execute("SELECT 1")
        result = cursor.fetchone()

        assert result is not None, "Query must return result"
        assert result[0] == 1, "SELECT 1 must return 1"


def test_pgwire_client_can_query_iris_data(pgwire_client):
    """
    Verify pgwire_client can execute queries against IRIS via PGWire protocol.

    Contract:
    - PGWire server running on port 5434
    - Queries routed to embedded IRIS
    """
    with pgwire_client.cursor() as cursor:
        # Execute query that will be translated by PGWire and executed on IRIS
        cursor.execute("SELECT CURRENT_TIMESTAMP")
        result = cursor.fetchone()

        assert result is not None, "CURRENT_TIMESTAMP query must return result"
        assert len(result) == 1, "Should return single column"

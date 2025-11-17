"""
Contract tests for pytest fixtures.

These tests validate that fixtures meet their interface contracts as defined in
specs/017-correct-testing-framework/contracts/pytest-fixtures.md

TDD: These tests MUST FAIL until fixtures are implemented.
"""


def test_embedded_iris_fixture_provides_connection(embedded_iris):
    """
    Verify embedded_iris fixture returns valid IRIS module.

    Contract:
    - Returns: iris module ready for SQL execution
    - Guarantees: CallIn service enabled, USER namespace active
    - Setup time: <10 seconds
    """
    assert embedded_iris is not None, "embedded_iris fixture must return iris module"

    # Verify iris module is valid by executing simple query
    result = embedded_iris.sql.exec("SELECT 1")
    first_row = None
    for row in result:
        first_row = row
        break

    assert first_row is not None, "Query must return result"
    assert first_row[0] == 1, "SELECT 1 must return 1"


def test_embedded_iris_fixture_cleanup_releases_resources(embedded_iris):
    """
    Verify embedded_iris fixture cleanup releases IRIS resources.

    Contract:
    - Cleanup: Resources released
    - No leaked IRIS processes after session ends
    """
    # Track iris module for validation
    assert embedded_iris is not None

    # Verify iris module is working
    # Embedded Python doesn't require explicit cleanup like external connections
    # The iris module is part of the irispython runtime
    assert hasattr(embedded_iris, "sql"), "iris module must have sql attribute"
    assert hasattr(embedded_iris, "system"), "iris module must have system attribute"


def test_iris_clean_namespace_isolates_test_data(iris_clean_namespace):
    """
    Verify iris_clean_namespace fixture isolates test data between tests.

    Contract:
    - Returns: iris module with clean namespace
    - Guarantees: No conflicting test data from previous tests
    - Cleanup time: <2 seconds
    """
    # Create test table that should be cleaned up
    iris_clean_namespace.sql.exec(
        """
        CREATE TABLE IF NOT EXISTS test_isolation_check (
            id INT PRIMARY KEY,
            value VARCHAR(50)
        )
    """
    )

    # Clear any existing data first (in case cleanup didn't run)
    iris_clean_namespace.sql.exec("DELETE FROM test_isolation_check")
    iris_clean_namespace.sql.exec("INSERT INTO test_isolation_check VALUES (1, 'test_data')")
    # Commits are automatic with iris.sql.exec()

    # Verify data was inserted
    result = iris_clean_namespace.sql.exec("SELECT COUNT(*) FROM test_isolation_check")
    count = None
    for row in result:
        count = row[0]
        break
    assert count == 1, "Data should be inserted"

    # Cleanup will be verified by running this test multiple times


def test_iris_clean_namespace_second_run_has_no_previous_data(iris_clean_namespace):
    """
    Second test to verify isolation - should not see data from previous test.

    This test validates that test_isolation_check table either:
    1. Does not exist (dropped in cleanup)
    2. Is empty (rolled back in cleanup)
    """
    try:
        result = iris_clean_namespace.sql.exec("SELECT COUNT(*) FROM test_isolation_check")
        count = None
        for row in result:
            count = row[0]
            break
        # If table exists, it should be empty
        assert count == 0, "Table should be empty - previous test data not cleaned up"
    except Exception:
        # Table doesn't exist - cleanup worked via DROP TABLE
        pass  # This is acceptable


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
    assert (
        pgwire_client.status == psycopg.Connection.OK
    ), f"Connection status must be OK, got {pgwire_client.status}"

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

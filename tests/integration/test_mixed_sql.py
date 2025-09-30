"""
Integration Tests for Mixed IRIS/Standard SQL

Tests the translation and execution of queries that mix IRIS-specific constructs
with standard PostgreSQL SQL. These tests MUST FAIL until implementation is complete.

Constitutional Requirement: Test-First Development ensuring seamless SQL integration
"""

import pytest
import time
import json
from datetime import datetime, date
from typing import Any, Dict, List, Optional

# These imports will fail until implementation exists - expected in TDD
try:
    from iris_pgwire.server import PGWireServer
    from iris_pgwire.sql_translator import SQLTranslator
    from iris_pgwire.sql_translator.hybrid_processor import HybridSQLProcessor
    SERVER_AVAILABLE = True
except ImportError:
    SERVER_AVAILABLE = False

try:
    import psycopg
    PSYCOPG_AVAILABLE = True
except ImportError:
    PSYCOPG_AVAILABLE = False

pytestmark = [pytest.mark.integration, pytest.mark.requires_iris, pytest.mark.mixed_sql]

@pytest.fixture(scope="session")
def pgwire_server():
    """PGWire server with hybrid SQL translation enabled"""
    if not SERVER_AVAILABLE:
        pytest.skip("PGWire server not implemented yet")

    # This will fail until hybrid SQL processing is implemented
    server = PGWireServer(
        port=5436,  # Different port for mixed SQL testing
        enable_translation=True,
        enable_hybrid_mode=True,  # Key feature for mixed SQL
        fallback_strategy="PRESERVE_STANDARD"
    )
    server.start()

    time.sleep(2)

    yield server

    server.stop()

@pytest.fixture
def connection_params():
    """Connection parameters for mixed SQL testing"""
    return {
        "host": "localhost",
        "port": 5436,
        "user": "postgres",
        "password": "iris",
        "dbname": "iris"
    }

class TestMixedIRISStandardSQL:
    """Test queries that mix IRIS constructs with standard PostgreSQL SQL"""

    def test_standard_select_with_iris_functions(self, pgwire_server, connection_params):
        """Test standard SELECT with IRIS function calls"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with psycopg.connect(**connection_params) as conn:
            with conn.cursor() as cur:
                # Standard SQL structure with IRIS functions
                cur.execute("""
                    SELECT
                        id,
                        name,
                        %SQLUPPER(name) AS name_upper,
                        email,
                        created_at,
                        %SYSTEM.Version.GetNumber() AS iris_version
                    FROM users
                    WHERE id > 10
                    ORDER BY created_at DESC
                    LIMIT 5
                """)

                results = cur.fetchall()
                assert len(results) <= 5, "LIMIT should be respected"

                if results:
                    row = results[0]
                    assert len(row) == 6, "Should have 6 columns"
                    # Verify IRIS functions were processed
                    assert row[2] is not None, "IRIS function should return result"
                    assert row[5] is not None, "System function should return version"

    def test_standard_join_with_iris_constructs(self, pgwire_server, connection_params):
        """Test standard JOINs with IRIS construct translation"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with psycopg.connect(**connection_params) as conn:
            with conn.cursor() as cur:
                # Standard JOIN with IRIS functions
                cur.execute("""
                    SELECT
                        u.id,
                        %SQLUPPER(u.name) AS user_name,
                        p.title,
                        %SQLLOWER(p.status) AS post_status,
                        JSON_OBJECT('user', u.name, 'post', p.title) AS summary
                    FROM users u
                    INNER JOIN posts p ON u.id = p.user_id
                    WHERE %SQLUPPER(p.status) = 'PUBLISHED'
                    ORDER BY p.created_at DESC
                    LIMIT 10
                """)

                results = cur.fetchall()
                assert len(results) <= 10, "LIMIT should be respected"

                if results:
                    # Verify JSON construction worked
                    json_col = results[0][4]
                    parsed = json.loads(json_col)
                    assert 'user' in parsed and 'post' in parsed

    def test_standard_aggregation_with_iris_functions(self, pgwire_server, connection_params):
        """Test standard aggregation queries with IRIS functions"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with psycopg.connect(**connection_params) as conn:
            with conn.cursor() as cur:
                # Standard GROUP BY with IRIS functions
                cur.execute("""
                    SELECT
                        %SQLUPPER(status) AS status_upper,
                        COUNT(*) AS user_count,
                        MIN(created_at) AS first_created,
                        MAX(created_at) AS last_created,
                        JSON_OBJECT('status', status, 'count', COUNT(*)) AS status_summary
                    FROM users
                    WHERE created_at >= '2023-01-01'
                    GROUP BY status, %SQLUPPER(status)
                    HAVING COUNT(*) > 5
                    ORDER BY COUNT(*) DESC
                """)

                results = cur.fetchall()

                if results:
                    # Verify aggregation and IRIS functions work together
                    row = results[0]
                    assert row[1] > 5, "HAVING clause should filter for count > 5"

                    # Verify JSON aggregation
                    json_summary = json.loads(row[4])
                    assert json_summary['count'] == row[1], "JSON count should match actual count"

    def test_standard_window_functions_with_iris_constructs(self, pgwire_server, connection_params):
        """Test PostgreSQL window functions with IRIS constructs"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with psycopg.connect(**connection_params) as conn:
            with conn.cursor() as cur:
                # Window functions with IRIS constructs
                cur.execute("""
                    SELECT
                        id,
                        name,
                        %SQLUPPER(name) AS name_upper,
                        ROW_NUMBER() OVER (ORDER BY %SQLUPPER(name)) AS name_rank,
                        RANK() OVER (PARTITION BY %SQLUPPER(status) ORDER BY created_at) AS status_rank,
                        LAG(%SQLUPPER(name)) OVER (ORDER BY id) AS prev_name_upper
                    FROM users
                    ORDER BY id
                    LIMIT 10
                """)

                results = cur.fetchall()
                assert len(results) <= 10, "LIMIT should be respected"

                if len(results) >= 2:
                    # Verify window function behavior
                    first_row = results[0]
                    second_row = results[1]

                    assert first_row[3] == 1, "First row should have ROW_NUMBER = 1"
                    assert first_row[5] is None, "First row LAG should be NULL"
                    assert second_row[5] == first_row[2], "Second row LAG should equal first row name_upper"

class TestMixedSQLWithCTE:
    """Test Common Table Expressions (CTEs) with IRIS constructs"""

    def test_cte_with_iris_functions(self, pgwire_server, connection_params):
        """Test CTE containing IRIS function calls"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with psycopg.connect(**connection_params) as conn:
            with conn.cursor() as cur:
                # CTE with IRIS functions
                cur.execute("""
                    WITH user_summary AS (
                        SELECT
                            id,
                            %SQLUPPER(name) AS name_upper,
                            %SQLLOWER(email) AS email_lower,
                            %SYSTEM.Version.GetNumber() AS iris_version,
                            JSON_OBJECT('id', id, 'name', name) AS user_json
                        FROM users
                        WHERE created_at >= '2023-01-01'
                    )
                    SELECT
                        name_upper,
                        email_lower,
                        iris_version,
                        user_json
                    FROM user_summary
                    WHERE name_upper LIKE 'A%'
                    ORDER BY name_upper
                    LIMIT 5
                """)

                results = cur.fetchall()
                assert len(results) <= 5, "LIMIT should be respected"

                if results:
                    # Verify CTE processing worked
                    row = results[0]
                    assert row[0].startswith('A'), "Name should start with 'A'"
                    assert row[2] is not None, "IRIS version should be populated"

                    # Verify JSON from CTE
                    user_json = json.loads(row[3])
                    assert 'id' in user_json and 'name' in user_json

    def test_recursive_cte_with_iris_constructs(self, pgwire_server, connection_params):
        """Test recursive CTE with IRIS function calls"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with psycopg.connect(**connection_params) as conn:
            with conn.cursor() as cur:
                # Recursive CTE with IRIS functions
                cur.execute("""
                    WITH RECURSIVE category_hierarchy AS (
                        SELECT
                            id,
                            name,
                            parent_id,
                            %SQLUPPER(name) AS name_upper,
                            0 AS level
                        FROM categories
                        WHERE parent_id IS NULL

                        UNION ALL

                        SELECT
                            c.id,
                            c.name,
                            c.parent_id,
                            %SQLUPPER(c.name) AS name_upper,
                            ch.level + 1
                        FROM categories c
                        INNER JOIN category_hierarchy ch ON c.parent_id = ch.id
                        WHERE ch.level < 5
                    )
                    SELECT
                        id,
                        name_upper,
                        level,
                        JSON_OBJECT('id', id, 'name', name, 'level', level) AS category_json
                    FROM category_hierarchy
                    ORDER BY level, name_upper
                    LIMIT 20
                """)

                results = cur.fetchall()
                assert len(results) <= 20, "LIMIT should be respected"

                if results:
                    # Verify recursive structure
                    levels = [row[2] for row in results]
                    assert min(levels) == 0, "Should have root level categories"

                    # Verify JSON construction in recursive context
                    category_json = json.loads(results[0][3])
                    assert 'level' in category_json

class TestMixedSQLWithSubqueries:
    """Test subqueries mixing IRIS constructs with standard SQL"""

    def test_correlated_subquery_with_iris_functions(self, pgwire_server, connection_params):
        """Test correlated subqueries with IRIS function calls"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with psycopg.connect(**connection_params) as conn:
            with conn.cursor() as cur:
                # Correlated subquery with IRIS functions
                cur.execute("""
                    SELECT
                        u.id,
                        %SQLUPPER(u.name) AS name_upper,
                        (
                            SELECT COUNT(*)
                            FROM posts p
                            WHERE p.user_id = u.id
                            AND %SQLUPPER(p.status) = 'PUBLISHED'
                        ) AS published_count,
                        (
                            SELECT JSON_OBJECT('latest_post', MAX(p.title))
                            FROM posts p
                            WHERE p.user_id = u.id
                            AND %SQLUPPER(p.status) = 'PUBLISHED'
                        ) AS latest_post_info
                    FROM users u
                    WHERE EXISTS (
                        SELECT 1
                        FROM posts p
                        WHERE p.user_id = u.id
                        AND %SQLUPPER(p.status) = 'PUBLISHED'
                    )
                    ORDER BY published_count DESC
                    LIMIT 10
                """)

                results = cur.fetchall()
                assert len(results) <= 10, "LIMIT should be respected"

                if results:
                    # Verify correlated subquery results
                    row = results[0]
                    assert row[2] > 0, "Should have published posts (EXISTS condition)"

                    # Verify JSON from subquery
                    if row[3]:
                        latest_info = json.loads(row[3])
                        assert 'latest_post' in latest_info

    def test_scalar_subquery_with_iris_system_functions(self, pgwire_server, connection_params):
        """Test scalar subqueries with IRIS system functions"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with psycopg.connect(**connection_params) as conn:
            with conn.cursor() as cur:
                # Scalar subquery with IRIS system functions
                cur.execute("""
                    SELECT
                        id,
                        name,
                        (SELECT %SYSTEM.Version.GetNumber()) AS iris_version,
                        (SELECT COUNT(*) FROM users WHERE created_at >= CURRENT_DATE) AS today_users,
                        (
                            SELECT JSON_OBJECT(
                                'version', %SYSTEM.Version.GetNumber(),
                                'user_count', COUNT(*)
                            )
                            FROM users
                            WHERE created_at >= CURRENT_DATE
                        ) AS system_info
                    FROM users
                    WHERE id <= 5
                    ORDER BY id
                """)

                results = cur.fetchall()
                assert len(results) <= 5, "Should have max 5 users"

                if results:
                    # Verify scalar subqueries work
                    row = results[0]
                    assert row[2] is not None, "IRIS version should be returned"
                    assert isinstance(row[3], int), "Today users count should be integer"

                    # Verify complex JSON from subquery
                    system_info = json.loads(row[4])
                    assert 'version' in system_info and 'user_count' in system_info

class TestMixedSQLTransactionHandling:
    """Test transaction handling with mixed IRIS/standard SQL"""

    def test_transaction_with_mixed_sql_statements(self, pgwire_server, connection_params):
        """Test transaction containing both IRIS constructs and standard SQL"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with psycopg.connect(**connection_params) as conn:
            with conn.cursor() as cur:
                # Test transaction with mixed statements
                cur.execute("BEGIN")

                # Standard SQL statement
                cur.execute("SELECT COUNT(*) FROM users")
                initial_count = cur.fetchone()[0]

                # IRIS function call
                cur.execute("SELECT %SYSTEM.Version.GetNumber() AS version")
                version = cur.fetchone()[0]
                assert version is not None

                # Mixed SQL statement
                cur.execute("""
                    SELECT
                        COUNT(*) AS total_users,
                        %SYSTEM.Version.GetNumber() AS current_version,
                        JSON_OBJECT('count', COUNT(*), 'version', %SYSTEM.Version.GetNumber()) AS summary
                    FROM users
                    WHERE %SQLUPPER(status) = 'ACTIVE'
                """)
                result = cur.fetchone()
                assert result[0] >= 0, "Count should be non-negative"
                assert result[1] == version, "Version should be consistent"

                # Verify JSON construction
                summary = json.loads(result[2])
                assert summary['version'] == version

                cur.execute("COMMIT")

                # Verify transaction completed
                assert conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE

    def test_savepoint_with_iris_constructs(self, pgwire_server, connection_params):
        """Test savepoints in transactions with IRIS constructs"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with psycopg.connect(**connection_params) as conn:
            with conn.cursor() as cur:
                cur.execute("BEGIN")

                # Establish savepoint
                cur.execute("SAVEPOINT sp1")

                # Execute IRIS function
                cur.execute("SELECT %SQLUPPER('test') AS upper_test")
                result1 = cur.fetchone()[0]
                assert result1 == "TEST"

                # Another savepoint
                cur.execute("SAVEPOINT sp2")

                # Execute mixed SQL
                cur.execute("""
                    SELECT JSON_OBJECT('version', %SYSTEM.Version.GetNumber()) AS version_json
                """)
                result2 = cur.fetchone()[0]
                version_info = json.loads(result2)
                assert 'version' in version_info

                # Rollback to savepoint
                cur.execute("ROLLBACK TO sp1")

                # Should still be able to execute IRIS functions
                cur.execute("SELECT %SQLLOWER('ROLLBACK_TEST') AS lower_test")
                result3 = cur.fetchone()[0]
                assert result3 == "rollback_test"

                cur.execute("COMMIT")

class TestMixedSQLPerformance:
    """Test performance characteristics of mixed IRIS/standard SQL"""

    def test_mixed_sql_query_performance(self, pgwire_server, connection_params):
        """Test performance of queries mixing IRIS constructs with standard SQL"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with psycopg.connect(**connection_params) as conn:
            with conn.cursor() as cur:
                # Complex mixed query for performance testing
                complex_query = """
                    WITH user_stats AS (
                        SELECT
                            u.id,
                            %SQLUPPER(u.name) AS name_upper,
                            u.created_at,
                            COUNT(p.id) AS post_count,
                            JSON_OBJECT('user_id', u.id, 'name', u.name) AS user_json
                        FROM users u
                        LEFT JOIN posts p ON u.id = p.user_id
                        WHERE u.created_at >= '2023-01-01'
                        AND %SQLUPPER(u.status) = 'ACTIVE'
                        GROUP BY u.id, u.name, u.created_at
                    )
                    SELECT
                        us.name_upper,
                        us.post_count,
                        us.user_json,
                        %SYSTEM.Version.GetNumber() AS iris_version,
                        CASE
                            WHEN us.post_count > 10 THEN %SQLUPPER('prolific')
                            WHEN us.post_count > 5 THEN %SQLUPPER('active')
                            ELSE %SQLUPPER('casual')
                        END AS user_type,
                        ROW_NUMBER() OVER (ORDER BY us.post_count DESC) AS activity_rank
                    FROM user_stats us
                    ORDER BY us.post_count DESC
                    LIMIT 50
                """

                start_time = time.perf_counter()
                cur.execute(complex_query)
                results = cur.fetchall()
                execution_time_ms = (time.perf_counter() - start_time) * 1000

                # Verify results
                assert len(results) <= 50, "LIMIT should be respected"

                # Constitutional requirement: complex mixed queries should be reasonably fast
                assert execution_time_ms < 2000.0, \
                    f"Complex mixed query took {execution_time_ms}ms, should be < 2000ms"

                if results:
                    # Verify all elements processed correctly
                    row = results[0]
                    assert row[0] is not None, "Name upper should be processed"
                    assert row[3] is not None, "IRIS version should be returned"
                    assert row[4] in ['PROLIFIC', 'ACTIVE', 'CASUAL'], "User type should be uppercased"

                    # Verify JSON structure
                    user_json = json.loads(row[2])
                    assert 'user_id' in user_json and 'name' in user_json

    def test_batch_mixed_sql_performance(self, pgwire_server, connection_params):
        """Test performance of batch execution with mixed SQL"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with psycopg.connect(**connection_params) as conn:
            with conn.cursor() as cur:
                # Batch of mixed SQL queries
                queries = [
                    "SELECT %SQLUPPER('test') AS upper_test",
                    "SELECT COUNT(*) FROM users WHERE created_at >= CURRENT_DATE",
                    "SELECT %SYSTEM.Version.GetNumber() AS version",
                    "SELECT JSON_OBJECT('timestamp', CURRENT_TIMESTAMP) AS time_json",
                    "SELECT %SQLLOWER('BATCH') AS lower_test"
                ]

                start_time = time.perf_counter()

                for query in queries:
                    cur.execute(query)
                    result = cur.fetchone()
                    assert result is not None, f"Query should return result: {query}"

                execution_time_ms = (time.perf_counter() - start_time) * 1000

                # Batch execution should be efficient
                assert execution_time_ms < 1000.0, \
                    f"Batch mixed queries took {execution_time_ms}ms, should be < 1000ms"

class TestMixedSQLErrorHandling:
    """Test error handling in mixed IRIS/standard SQL scenarios"""

    def test_partial_iris_failure_in_mixed_query(self, pgwire_server, connection_params):
        """Test error handling when IRIS construct fails in mixed query"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with psycopg.connect(**connection_params) as conn:
            with conn.cursor() as cur:
                # Query with potential IRIS function failure
                try:
                    cur.execute("""
                        SELECT
                            id,
                            name,
                            %INVALID.FUNCTION() AS invalid_func,  -- This should fail
                            created_at
                        FROM users
                        LIMIT 1
                    """)
                    result = cur.fetchone()
                    # If no error, verify graceful handling
                    assert result is not None or cur.rowcount >= 0
                except psycopg.Error as e:
                    # Error is acceptable - verify meaningful message
                    assert "INVALID" in str(e) or "function" in str(e).lower()

    def test_mixed_sql_syntax_error_handling(self, pgwire_server, connection_params):
        """Test error handling for syntax errors in mixed SQL"""
        if not SERVER_AVAILABLE:
            pytest.skip("Implementation not available yet")

        with psycopg.connect(**connection_params) as conn:
            with conn.cursor() as cur:
                # Syntax error in mixed query
                with pytest.raises(psycopg.Error):
                    cur.execute("""
                        SELECT
                            %SQLUPPER(name) AS name_upper,
                            INVALID SYNTAX HERE,
                            COUNT(*) AS count
                        FROM users
                        GROUP BY name
                    """)

                # Connection should recover
                cur.execute("SELECT %SYSTEM.Version.GetNumber() AS version")
                result = cur.fetchone()
                assert result is not None, "Connection should recover after syntax error"

# TDD Validation: These tests should fail until implementation exists
def test_mixed_sql_tdd_validation():
    """Verify mixed SQL tests fail appropriately before implementation"""
    if SERVER_AVAILABLE:
        # If this passes, implementation already exists
        pytest.fail("TDD violation: Mixed SQL implementation exists before tests were written")
    else:
        # Expected state: tests exist, implementation doesn't
        assert True, "TDD compliant: Mixed SQL tests written before implementation"
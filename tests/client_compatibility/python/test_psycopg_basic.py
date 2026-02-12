#!/usr/bin/env python3
"""
psycopg3 Compatibility Tests - Basic Operations

Tests PostgreSQL wire protocol compatibility with psycopg3 driver.
Mirrors JDBC SimpleQueryTest and PreparedStatementTest functionality.

Test Coverage:
- Connection establishment
- Simple queries (Query message)
- Prepared statements (Parse/Bind/Execute)
- NULL handling
- Type inference
- Column metadata
- Transactions
"""

import os
from datetime import date

import psycopg
import pytest

os.environ["PGWIRE_USER"] = "test_user"
os.environ["PGWIRE_PASSWORD"] = "test"

psycopg_connection_string: str | None = None


def build_connection_string(connection_params: dict[str, str | int]) -> str:
    """Generate psycopg connection string from dynamic pgwire params"""

    return (
        f"host={connection_params['host']} "
        f"port={connection_params['port']} "
        f"user={connection_params['user']} "
        f"password={connection_params['password']} "
        f"dbname={connection_params['dbname']}"
    )


def get_psycopg_connection_string() -> str:
    if psycopg_connection_string is None:
        raise RuntimeError("psycopg connection string not initialized")
    return psycopg_connection_string


@pytest.fixture(autouse=True)
def psycopg_connection_info(pgwire_server, pgwire_connection_params):
    """Ensure pgwire server is running and compute connection string"""

    global psycopg_connection_string
    psycopg_connection_string = build_connection_string(pgwire_connection_params)
    yield


class TestPsycopgBasicConnection:
    """Test basic connection functionality"""

    def test_connection_establishment(self):
        """Test that psycopg can establish connection to PGWire server"""
        with psycopg.connect(get_psycopg_connection_string()) as conn:
            assert conn.info.status.name == "OK"
            print(f"✅ Connection established: {conn.info.status}")

    def test_server_version(self):
        """Test server version reporting"""
        with psycopg.connect(get_psycopg_connection_string()) as conn:
            version = conn.info.server_version
            print(f"Server version: {version}")
            assert version > 0  # Should return some version number

    def test_database_metadata(self, pgwire_connection_params):
        """Test connection metadata"""
        assert pgwire_connection_params is not None
        with psycopg.connect(get_psycopg_connection_string()) as conn:
            assert conn.info.dbname == pgwire_connection_params["dbname"]
            assert conn.info.user == pgwire_connection_params["user"]
            print(f"✅ Database: {conn.info.dbname}, User: {conn.info.user}")


class TestPsycopgSimpleQueries:
    """Test simple query execution (PostgreSQL Simple Query protocol)"""

    def test_select_constant(self):
        """Test SELECT with constant value"""
        with psycopg.connect(get_psycopg_connection_string()) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                result = cur.fetchone()
                assert result is not None
                assert result[0] == 1
                print(f"✅ SELECT 1 returned: {result[0]}")

    def test_select_multiple_columns(self):
        """Test SELECT with multiple columns and types"""
        with psycopg.connect(get_psycopg_connection_string()) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS num, 'hello' AS text, 3.14 AS float_val")
                result = cur.fetchone()
                assert result is not None

                assert result[0] == 1
                assert result[1] == "hello"
                assert abs(result[2] - 3.14) < 0.001
                print(f"✅ Multiple columns: num={result[0]}, text={result[1]}, float={result[2]}")

    def test_select_current_timestamp(self):
        """Test SELECT CURRENT_TIMESTAMP"""
        with psycopg.connect(get_psycopg_connection_string()) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT CURRENT_TIMESTAMP")
                result = cur.fetchone()
                assert result is not None
                assert result[0] is not None
                print(f"✅ CURRENT_TIMESTAMP: {result[0]}")

    def test_select_with_null(self):
        """Test NULL value handling in simple queries"""
        with psycopg.connect(get_psycopg_connection_string()) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT NULL AS null_col, 42 AS num_col")
                result = cur.fetchone()
                assert result is not None

                assert result[0] is None  # NULL should be Python None
                assert result[1] == 42
                print(f"✅ NULL handling: null_col={result[0]}, num_col={result[1]}")

    def test_multiple_queries_sequential(self):
        """Test executing multiple queries sequentially"""
        with psycopg.connect(get_psycopg_connection_string()) as conn:
            with conn.cursor() as cur:
                # First query
                cur.execute("SELECT 1")
                result1 = cur.fetchone()
                assert result1 is not None
                assert result1[0] == 1

                # Second query
                cur.execute("SELECT 'second query'")
                result2 = cur.fetchone()
                assert result2 is not None
                assert result2[0] == "second query"

                print(f"✅ Sequential queries: {result1[0]}, {result2[0]}")


class TestPsycopgColumnMetadata:
    """Test column metadata and type information"""

    def test_column_names(self):
        """Test that column names are preserved correctly"""
        with psycopg.connect(get_psycopg_connection_string()) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS id, 'test' AS name")

                # Check column names
                assert cur.description is not None
                assert cur.description[0].name == "id"
                assert cur.description[1].name == "name"
                print(f"✅ Column names: {[desc.name for desc in cur.description]}")

    def test_column_types(self):
        """Test that column types are correctly identified"""
        with psycopg.connect(get_psycopg_connection_string()) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 AS int_col, 'text' AS text_col")

                # psycopg exposes type OIDs
                assert cur.description is not None
                int_type_oid = cur.description[0].type_code
                text_type_oid = cur.description[1].type_code

                # PostgreSQL type OIDs: 23=int4, 25=text
                assert int_type_oid == 23  # INTEGER
                assert text_type_oid == 25  # TEXT/VARCHAR
                print(f"✅ Column types: int_col={int_type_oid}, text_col={text_type_oid}")

    def test_empty_result_set_metadata(self):
        """Test that empty result sets still have column metadata"""
        with psycopg.connect(get_psycopg_connection_string()) as conn:
            with conn.cursor() as cur:
                # Create temp table and ensure it's empty
                cur.execute("CREATE TABLE IF NOT EXISTS test_empty_psycopg (id INT)")
                cur.execute("DELETE FROM test_empty_psycopg")
                conn.commit()

                try:
                    # Query empty table
                    cur.execute("SELECT * FROM test_empty_psycopg")
                    rows = cur.fetchall()

                    assert len(rows) == 0  # No rows
                    assert cur.description is not None  # But metadata exists
                    assert len(cur.description) > 0
                    print(f"✅ Empty result set has metadata: {len(cur.description)} columns")
                finally:
                    cur.execute("DROP TABLE IF EXISTS test_empty_psycopg")
                    conn.commit()


class TestPsycopgPreparedStatements:
    """Test prepared statements (Extended Protocol)"""

    def test_prepared_with_single_param(self):
        """Test prepared statement with single parameter"""
        with psycopg.connect(get_psycopg_connection_string()) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT %s AS value", (42,))
                result = cur.fetchone()
                assert result is not None
                assert result[0] == 42
                print(f"✅ Single parameter: {result[0]}")

    def test_prepared_with_multiple_params(self):
        """Test prepared statement with multiple parameters"""
        with psycopg.connect(get_psycopg_connection_string()) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT %s AS num, %s AS text, %s AS flag", (123, "hello", True))
                result = cur.fetchone()
                assert result is not None

                assert result[0] == 123
                assert result[1] == "hello"
                assert result[2] is True
                print(f"✅ Multiple params: num={result[0]}, text={result[1]}, flag={result[2]}")

    def test_prepared_statement_reuse(self):
        """Test reusing prepared statement with different parameters"""
        with psycopg.connect(get_psycopg_connection_string()) as conn:
            with conn.cursor() as cur:
                # First execution
                cur.execute("SELECT %s * 2 AS doubled", (5,))
                result1 = cur.fetchone()
                assert result1 is not None
                assert result1[0] == 10

                # Second execution with different parameter
                cur.execute("SELECT %s * 2 AS doubled", (7,))
                result2 = cur.fetchone()
                assert result2 is not None
                assert result2[0] == 14

                print(f"✅ Reused statement: {result1[0]}, {result2[0]}")

    def test_prepared_with_null_param(self):
        """Test prepared statement with NULL parameter"""
        with psycopg.connect(get_psycopg_connection_string()) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT %s AS null_val", (None,))
                result = cur.fetchone()
                assert result is not None

                assert result[0] is None
                print(f"✅ NULL parameter: {result[0]}")

    def test_prepared_with_string_escaping(self):
        """Test prepared statement with special characters in string"""
        with psycopg.connect(get_psycopg_connection_string()) as conn:
            with conn.cursor() as cur:
                test_string = "O'Reilly's \"Book\""
                cur.execute("SELECT %s AS text", (test_string,))
                result = cur.fetchone()
                assert result is not None

                assert result[0] == test_string
                print(f"✅ String escaping: {result[0]}")

    def test_prepared_with_date_param(self):
        """Test prepared statement with date parameter"""
        with psycopg.connect(get_psycopg_connection_string()) as conn:
            with conn.cursor() as cur:
                test_date = date(2024, 1, 15)
                cur.execute("SELECT %s AS test_date", (test_date,))
                result = cur.fetchone()
                assert result is not None

                assert result[0] == test_date
                print(f"✅ Date parameter: {result[0]}")


class TestPsycopgTransactions:
    """Test transaction management"""

    def test_basic_commit(self):
        """Test basic transaction commit"""
        with psycopg.connect(get_psycopg_connection_string()) as conn:
            with conn.cursor() as cur:
                # Create test table
                cur.execute("CREATE TABLE IF NOT EXISTS test_commit (id INT, value VARCHAR(50))")
                conn.commit()

                try:
                    # Start transaction
                    cur.execute("DELETE FROM test_commit")
                    cur.execute("INSERT INTO test_commit VALUES (1, 'test')")
                    conn.commit()

                    # Verify data persisted
                    cur.execute("SELECT COUNT(*) FROM test_commit")
                    count_row = cur.fetchone()
                    assert count_row is not None
                    count = count_row[0]
                    assert count == 1
                    print(f"✅ Transaction commit: {count} row persisted")
                finally:
                    cur.execute("DROP TABLE IF EXISTS test_commit")
                    conn.commit()

    def test_basic_rollback(self):
        """Test basic transaction rollback"""
        with psycopg.connect(get_psycopg_connection_string()) as conn:
            with conn.cursor() as cur:
                # Create test table
                cur.execute("CREATE TABLE IF NOT EXISTS test_rollback (id INT, value VARCHAR(50))")
                conn.commit()

                try:
                    # Insert initial data
                    cur.execute("DELETE FROM test_rollback")
                    cur.execute("INSERT INTO test_rollback VALUES (1, 'initial')")
                    conn.commit()

                    # Start transaction and rollback
                    cur.execute("INSERT INTO test_rollback VALUES (2, 'rolled_back')")
                    conn.rollback()

                    # Verify rollback worked
                    cur.execute("SELECT COUNT(*) FROM test_rollback")
                    count_row = cur.fetchone()
                    assert count_row is not None
                    count = count_row[0]
                    assert count == 1  # Only initial row should remain
                    print(f"✅ Transaction rollback: {count} row (rollback successful)")
                finally:
                    cur.execute("DROP TABLE IF EXISTS test_rollback")
                    conn.commit()

    def test_autocommit_mode(self):
        """Test autocommit mode"""
        with psycopg.connect(get_psycopg_connection_string(), autocommit=True) as conn:
            with conn.cursor() as cur:
                # In autocommit mode, each statement commits immediately
                cur.execute("CREATE TABLE IF NOT EXISTS test_autocommit (id INT)")

                try:
                    cur.execute("INSERT INTO test_autocommit VALUES (1)")
                    # No explicit commit needed

                    cur.execute("SELECT COUNT(*) FROM test_autocommit")
                    count_row = cur.fetchone()
                    assert count_row is not None
                    count = count_row[0]
                    assert count == 1
                    print(f"✅ Autocommit mode: {count} row committed automatically")
                finally:
                    cur.execute("DROP TABLE IF EXISTS test_autocommit")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

#!/usr/bin/env python3
"""
asyncpg Compatibility Tests - Basic Operations

Tests PostgreSQL wire protocol compatibility with asyncpg driver.
Pure async driver requiring async/await patterns throughout.

Test Coverage:
- Connection establishment (async)
- Simple queries (fetchval, fetch, fetchrow)
- Prepared statements (prepare/execute)
- NULL handling
- Type inference
- Column metadata
- Transactions (async with conn.transaction())
"""

from datetime import date

import asyncpg
import pytest
import pytest_asyncio

# Connection configuration
PGWIRE_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "user": "test_user",
    "password": "test",
    "database": "USER",
}


@pytest_asyncio.fixture
async def conn():
    """Create async connection for each test"""
    connection = await asyncpg.connect(**PGWIRE_CONFIG)
    yield connection
    await connection.close()


@pytest_asyncio.fixture
async def pool():
    """Create connection pool for pool-specific tests"""
    pool = await asyncpg.create_pool(**PGWIRE_CONFIG, min_size=1, max_size=5)
    yield pool
    await pool.close()


@pytest.mark.asyncio
class TestAsyncpgBasicConnection:
    """Test basic connection functionality"""

    async def test_connection_establishment(self, conn):
        """Test that asyncpg can establish connection to PGWire server"""
        # Execute simple query to verify connection works
        result = await conn.fetchval("SELECT 1")
        assert result == 1
        print(f"✅ Connection established and query executed: {result}")

    async def test_connection_pool(self, pool):
        """Test connection pooling"""
        async with pool.acquire() as conn:
            result = await conn.fetchval("SELECT 2")
            assert result == 2
            print(f"✅ Pool connection works: {result}")

    async def test_server_version(self, conn):
        """Test server version reporting"""
        # asyncpg doesn't expose server_version directly like psycopg
        # We'll test by executing SHOW server_version
        version = await conn.fetchval("SHOW server_version")
        assert version is not None
        print(f"✅ Server version: {version}")

    async def test_database_metadata(self, conn):
        """Test connection metadata via queries"""
        # asyncpg doesn't have .info property, query database name
        db_name = await conn.fetchval("SELECT current_database()")
        assert db_name == "USER"
        print(f"✅ Database: {db_name}")


@pytest.mark.asyncio
class TestAsyncpgSimpleQueries:
    """Test simple query execution (PostgreSQL Simple Query protocol)"""

    async def test_fetchval_constant(self, conn):
        """Test fetchval with constant value"""
        result = await conn.fetchval("SELECT 1")
        assert result == 1
        print(f"✅ fetchval returned: {result}")

    async def test_fetchrow_multiple_columns(self, conn):
        """Test fetchrow with multiple columns and types"""
        result = await conn.fetchrow("SELECT 1 AS num, 'hello' AS text, 3.14 AS float_val")

        assert result["num"] == 1
        assert result["text"] == "hello"
        assert abs(result["float_val"] - 3.14) < 0.001
        print(
            f"✅ Multiple columns: num={result['num']}, text={result['text']}, float={result['float_val']}"
        )

    async def test_fetch_all_rows(self, conn):
        """Test fetch to retrieve all rows"""
        # Create temp table with multiple rows
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS test_fetch_asyncpg (id INT, value VARCHAR(50))"
        )
        await conn.execute("DELETE FROM test_fetch_asyncpg")
        await conn.execute("INSERT INTO test_fetch_asyncpg VALUES (1, 'first')")
        await conn.execute("INSERT INTO test_fetch_asyncpg VALUES (2, 'second')")

        try:
            rows = await conn.fetch("SELECT * FROM test_fetch_asyncpg ORDER BY id")
            assert len(rows) == 2
            assert rows[0]["id"] == 1
            assert rows[0]["value"] == "first"
            assert rows[1]["id"] == 2
            assert rows[1]["value"] == "second"
            print(f"✅ Fetched {len(rows)} rows")
        finally:
            await conn.execute("DROP TABLE IF EXISTS test_fetch_asyncpg")

    async def test_select_current_timestamp(self, conn):
        """Test SELECT CURRENT_TIMESTAMP"""
        result = await conn.fetchval("SELECT CURRENT_TIMESTAMP")
        assert result is not None
        print(f"✅ CURRENT_TIMESTAMP: {result}")

    async def test_select_with_null(self, conn):
        """Test NULL value handling in simple queries"""
        result = await conn.fetchrow("SELECT NULL AS null_col, 42 AS num_col")

        assert result["null_col"] is None  # NULL should be Python None
        assert result["num_col"] == 42
        print(f"✅ NULL handling: null_col={result['null_col']}, num_col={result['num_col']}")


@pytest.mark.asyncio
class TestAsyncpgColumnMetadata:
    """Test column metadata and type information"""

    async def test_column_names(self, conn):
        """Test that column names are preserved correctly"""
        result = await conn.fetchrow("SELECT 1 AS id, 'test' AS name")

        # asyncpg returns records with column names as keys
        assert "id" in result.keys()
        assert "name" in result.keys()
        print(f"✅ Column names: {list(result.keys())}")

    async def test_column_types_from_prepared(self, conn):
        """Test that column types are correctly identified via prepared statement"""
        stmt = await conn.prepare("SELECT 1 AS int_col, 'text' AS text_col")

        # asyncpg prepared statements expose get_attributes()
        attrs = stmt.get_attributes()
        assert len(attrs) == 2
        assert attrs[0].name == "int_col"
        assert attrs[1].name == "text_col"
        print(f"✅ Column metadata: {[(a.name, a.type.name) for a in attrs]}")

    async def test_empty_result_set_metadata(self, conn):
        """Test that empty result sets still work"""
        # Create temp table and ensure it's empty
        await conn.execute("CREATE TABLE IF NOT EXISTS test_empty_asyncpg (id INT)")
        await conn.execute("DELETE FROM test_empty_asyncpg")

        try:
            # Query empty table
            rows = await conn.fetch("SELECT * FROM test_empty_asyncpg")
            assert len(rows) == 0
            print(f"✅ Empty result set works: {len(rows)} rows")
        finally:
            await conn.execute("DROP TABLE IF EXISTS test_empty_asyncpg")


@pytest.mark.asyncio
class TestAsyncpgPreparedStatements:
    """Test prepared statements (Extended Protocol)"""

    async def test_prepared_with_single_param(self, conn):
        """Test prepared statement with single parameter

        NOTE: asyncpg requires explicit type casts for non-string parameters.
        Without ::int cast, PostgreSQL infers OID 25 (TEXT) for $1, and asyncpg
        rejects the integer value with: "invalid input for query argument $1: 42 (expected str, got int)"

        This is standard asyncpg behavior, validated against real PostgreSQL 16.
        See: https://www.cybertec-postgresql.com/en/query-parameter-data-types-performance/
        """
        result = await conn.fetchval("SELECT $1::int AS value", 42)
        assert result == 42
        print(f"✅ Single parameter: {result}")

    async def test_prepared_with_multiple_params(self, conn):
        """Test prepared statement with multiple parameters

        NOTE: asyncpg requires explicit type casts for non-string parameters.
        Without casts, PostgreSQL infers OID 25 (TEXT) for all untyped parameters,
        and asyncpg rejects non-string values client-side.

        This is standard asyncpg behavior, validated against real PostgreSQL 16.
        """
        result = await conn.fetchrow(
            "SELECT $1::int AS num, $2::text AS text, $3::bool AS flag", 123, "hello", True
        )

        assert result["num"] == 123
        assert result["text"] == "hello"
        assert result["flag"] is True
        print(
            f"✅ Multiple params: num={result['num']}, text={result['text']}, flag={result['flag']}"
        )

    async def test_prepared_statement_reuse(self, conn):
        """Test explicit prepared statement creation and reuse

        NOTE: asyncpg requires explicit type cast for integer parameter.
        """
        # Create prepared statement
        stmt = await conn.prepare("SELECT $1::int * 2 AS doubled")

        # First execution
        result1 = await stmt.fetchval(5)
        assert result1 == 10

        # Second execution with different parameter
        result2 = await stmt.fetchval(7)
        assert result2 == 14

        print(f"✅ Reused prepared statement: {result1}, {result2}")

    async def test_prepared_with_null_param(self, conn):
        """Test prepared statement with NULL parameter"""
        result = await conn.fetchval("SELECT $1 AS null_val", None)
        assert result is None
        print(f"✅ NULL parameter: {result}")

    async def test_prepared_with_string_escaping(self, conn):
        """Test prepared statement with special characters in string

        NOTE: String parameters don't need explicit ::text cast since PostgreSQL
        defaults to OID 25 (TEXT) for untyped parameters, and asyncpg accepts string values.
        """
        test_string = "O'Reilly's \"Book\""
        result = await conn.fetchval("SELECT $1 AS text", test_string)
        assert result == test_string
        print(f"✅ String escaping: {result}")

    async def test_prepared_with_date_param(self, conn):
        """Test prepared statement with date parameter

        NOTE: Date parameters require explicit ::date cast for asyncpg.
        Without cast, PostgreSQL infers OID 25 (TEXT) and asyncpg rejects date objects.
        """
        test_date = date(2024, 1, 15)
        result = await conn.fetchval("SELECT $1::date AS test_date", test_date)

        # Note: This may fail if IRIS doesn't convert dates properly
        assert result == test_date
        print(f"✅ Date parameter: {result}")


@pytest.mark.asyncio
class TestAsyncpgTransactions:
    """Test transaction management"""

    async def test_basic_commit(self, conn):
        """Test basic transaction commit"""
        # Create test table
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS test_commit_asyncpg (id INT, value VARCHAR(50))"
        )

        try:
            # Transaction context manager
            async with conn.transaction():
                await conn.execute("DELETE FROM test_commit_asyncpg")
                await conn.execute("INSERT INTO test_commit_asyncpg VALUES (1, 'test')")

            # Verify data persisted
            count = await conn.fetchval("SELECT COUNT(*) FROM test_commit_asyncpg")
            assert count == 1
            print(f"✅ Transaction commit: {count} row persisted")
        finally:
            await conn.execute("DROP TABLE IF EXISTS test_commit_asyncpg")

    async def test_basic_rollback(self, conn):
        """Test basic transaction rollback"""
        # Create test table
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS test_rollback_asyncpg (id INT, value VARCHAR(50))"
        )

        try:
            # Insert initial data
            await conn.execute("DELETE FROM test_rollback_asyncpg")
            await conn.execute("INSERT INTO test_rollback_asyncpg VALUES (1, 'initial')")

            # Transaction that will rollback
            try:
                async with conn.transaction():
                    await conn.execute(
                        "INSERT INTO test_rollback_asyncpg VALUES (2, 'rolled_back')"
                    )
                    # Force rollback by raising exception
                    raise Exception("Intentional rollback")
            except Exception:
                pass

            # Verify rollback worked
            count = await conn.fetchval("SELECT COUNT(*) FROM test_rollback_asyncpg")
            assert count == 1  # Only initial row should remain
            print(f"✅ Transaction rollback: {count} row (rollback successful)")
        finally:
            await conn.execute("DROP TABLE IF EXISTS test_rollback_asyncpg")

    async def test_nested_transactions(self, conn):
        """Test nested transaction support (savepoints)"""
        await conn.execute("CREATE TABLE IF NOT EXISTS test_nested_asyncpg (id INT)")

        try:
            async with conn.transaction():
                await conn.execute("DELETE FROM test_nested_asyncpg")
                await conn.execute("INSERT INTO test_nested_asyncpg VALUES (1)")

                # Nested transaction (savepoint)
                try:
                    async with conn.transaction():
                        await conn.execute("INSERT INTO test_nested_asyncpg VALUES (2)")
                        raise Exception("Rollback nested")
                except Exception:
                    pass

                await conn.execute("INSERT INTO test_nested_asyncpg VALUES (3)")

            # Should have rows 1 and 3 (row 2 rolled back)
            count = await conn.fetchval("SELECT COUNT(*) FROM test_nested_asyncpg")
            assert count == 2
            print(f"✅ Nested transactions: {count} rows (savepoint worked)")
        finally:
            await conn.execute("DROP TABLE IF EXISTS test_nested_asyncpg")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

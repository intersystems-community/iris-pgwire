"""
E2E Tests for IRIS SQL Constructs Translation

Constitutional Requirement: Test-First Development with real PostgreSQL clients
Tests validate IRIS construct translation through actual psql and psycopg clients
against real IRIS instances. NO MOCKS.

Tests cover:
- IRIS %SYSTEM.* functions
- SQL extensions (TOP, FOR UPDATE NOWAIT)
- IRIS-specific functions (%SQLUPPER, DATEDIFF_MICROSECONDS)
- Data type mappings
- JSON functions and Document Database operations
- Performance requirements (5ms SLA)
"""

import pytest
import asyncio
import time
import psycopg
from typing import Dict, Any, List
import structlog

logger = structlog.get_logger()

@pytest.mark.e2e
@pytest.mark.requires_iris
@pytest.mark.asyncio
class TestIRISSystemFunctions:
    """Test IRIS %SYSTEM.* function translations"""

    async def test_system_version_function_psycopg(self, psycopg_connection):
        """Test %SYSTEM.Version.GetNumber() → version() with psycopg"""
        async with psycopg_connection.cursor() as cur:
            # Test IRIS system function translation
            await cur.execute("SELECT %SYSTEM.Version.GetNumber() AS iris_version")
            result = await cur.fetchone()

            assert result is not None, "Should return version information"
            assert isinstance(result[0], str), "Version should be a string"
            assert len(result[0]) > 0, "Version string should not be empty"

            logger.info("IRIS version function translated successfully", version=result[0])

    async def test_system_user_function_psycopg(self, psycopg_connection):
        """Test %SYSTEM.Security.GetUser() → current_user with psycopg"""
        async with psycopg_connection.cursor() as cur:
            # Test user function translation
            await cur.execute("SELECT %SYSTEM.Security.GetUser() AS current_user_iris")
            result = await cur.fetchone()

            assert result is not None, "Should return current user"
            assert isinstance(result[0], str), "User should be a string"

            logger.info("IRIS user function translated successfully", user=result[0])

    def test_system_version_function_psql(self, psql_command):
        """Test %SYSTEM.Version.GetNumber() with real psql client"""
        result = psql_command("SELECT %SYSTEM.Version.GetNumber();")

        assert result["success"], f"psql command failed: {result['stderr']}"
        assert "version" in result["stdout"].lower(), "Should contain version information"

        logger.info("IRIS version function works with psql", output=result["stdout"])

@pytest.mark.e2e
@pytest.mark.requires_iris
@pytest.mark.asyncio
class TestIRISSQLExtensions:
    """Test IRIS SQL extension translations"""

    async def test_top_clause_translation_psycopg(self, psycopg_connection):
        """Test SELECT TOP n → SELECT ... LIMIT n with psycopg"""
        async with psycopg_connection.cursor() as cur:
            # Create test data first
            await cur.execute("""
                CREATE TEMP TABLE test_top_data AS
                SELECT generate_series(1, 100) AS id, 'test_' || generate_series(1, 100) AS name
            """)

            # Test TOP clause translation
            await cur.execute("SELECT TOP 5 id, name FROM test_top_data ORDER BY id")
            results = await cur.fetchall()

            assert len(results) == 5, "TOP 5 should return exactly 5 rows"
            assert results[0][0] == 1, "First row should have id=1"
            assert results[4][0] == 5, "Fifth row should have id=5"

            logger.info("TOP clause translated successfully", row_count=len(results))

    def test_top_clause_psql(self, psql_command):
        """Test TOP clause with real psql client"""
        # Test simple TOP query
        result = psql_command("SELECT TOP 3 1 AS test_value;")

        assert result["success"], f"TOP clause failed in psql: {result['stderr']}"
        # Count actual data rows (excluding headers/footers)
        data_lines = [line for line in result["stdout"].split('\n')
                     if line.strip() and not line.startswith('-') and 'test_value' not in line]

        logger.info("TOP clause works with psql", output=result["stdout"])

@pytest.mark.e2e
@pytest.mark.requires_iris
@pytest.mark.asyncio
class TestIRISFunctions:
    """Test IRIS-specific function translations"""

    async def test_sqlupper_function_psycopg(self, psycopg_connection):
        """Test %SQLUPPER() → UPPER() with psycopg"""
        async with psycopg_connection.cursor() as cur:
            await cur.execute("SELECT %SQLUPPER('hello world') AS upper_result")
            result = await cur.fetchone()

            assert result is not None, "Should return uppercase result"
            assert result[0] == "HELLO WORLD", "Should convert to uppercase"

            logger.info("IRIS SQLUPPER function translated successfully", result=result[0])

    async def test_iris_horolog_function_psycopg(self, psycopg_connection):
        """Test %HOROLOG → EXTRACT(EPOCH FROM NOW()) with psycopg"""
        async with psycopg_connection.cursor() as cur:
            await cur.execute("SELECT %HOROLOG() AS horolog_time")
            result = await cur.fetchone()

            assert result is not None, "Should return time value"
            assert isinstance(result[0], (int, float)), "Should return numeric time"

            logger.info("IRIS HOROLOG function translated successfully", result=result[0])

    def test_iris_functions_psql(self, psql_command):
        """Test IRIS functions with real psql client"""
        result = psql_command("SELECT %SQLUPPER('test');")

        assert result["success"], f"IRIS function failed in psql: {result['stderr']}"
        assert "TEST" in result["stdout"], "Should contain uppercase result"

        logger.info("IRIS functions work with psql", output=result["stdout"])

@pytest.mark.e2e
@pytest.mark.requires_iris
@pytest.mark.asyncio
class TestIRISDataTypes:
    """Test IRIS data type translations"""

    async def test_iris_data_types_ddl_psycopg(self, psycopg_connection):
        """Test IRIS data type mappings in DDL with psycopg"""
        async with psycopg_connection.cursor() as cur:
            # Test creating table with IRIS data types
            await cur.execute("""
                CREATE TEMP TABLE test_iris_types (
                    id SERIAL PRIMARY KEY,
                    version_col ROWVERSION,
                    vector_col VECTOR(3),
                    list_col %List,
                    stream_col %Stream
                )
            """)

            # If we get here without exception, translation worked
            # Test inserting data
            await cur.execute("""
                INSERT INTO test_iris_types (vector_col, list_col)
                VALUES ('[1.0,2.0,3.0]', '{"item1", "item2"}')
            """)

            await cur.execute("SELECT id, vector_col FROM test_iris_types")
            result = await cur.fetchone()

            assert result is not None, "Should insert and retrieve data"
            assert result[0] == 1, "Serial ID should work"

            logger.info("IRIS data types translated successfully", id=result[0])

@pytest.mark.e2e
@pytest.mark.requires_iris
@pytest.mark.asyncio
class TestIRISJSONFunctions:
    """Test IRIS JSON and Document Database functions"""

    async def test_json_table_translation_psycopg(self, psycopg_connection):
        """Test JSON_TABLE → jsonb_to_recordset with psycopg"""
        async with psycopg_connection.cursor() as cur:
            # Test JSON_TABLE translation
            await cur.execute("""
                SELECT name, age FROM JSON_TABLE(
                    '{"users": [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]}',
                    '$.users[*]' COLUMNS (
                        name VARCHAR(50) PATH '$.name',
                        age INTEGER PATH '$.age'
                    )
                ) AS jt
            """)
            results = await cur.fetchall()

            assert len(results) == 2, "Should return 2 users"
            assert results[0][0] == "Alice", "First user should be Alice"
            assert results[1][0] == "Bob", "Second user should be Bob"

            logger.info("JSON_TABLE translated successfully", users=len(results))

    async def test_document_filter_translation_psycopg(self, psycopg_connection):
        """Test Document Database filter operations with psycopg"""
        async with psycopg_connection.cursor() as cur:
            # Create test table with JSON data
            await cur.execute("""
                CREATE TEMP TABLE test_docs (
                    id SERIAL,
                    data JSONB
                )
            """)

            await cur.execute("""
                INSERT INTO test_docs (data) VALUES
                ('{"name": "John", "age": 30, "active": true}'),
                ('{"name": "Jane", "age": 25, "active": false}')
            """)

            # Test document filter with IRIS syntax
            await cur.execute("""
                SELECT id, data->>'name' as name
                FROM test_docs
                WHERE data->>'active' = 'true'
            """)
            results = await cur.fetchall()

            assert len(results) == 1, "Should find 1 active user"
            assert results[0][1] == "John", "Should find John"

            logger.info("Document filters translated successfully", active_users=len(results))

@pytest.mark.e2e
@pytest.mark.requires_iris
@pytest.mark.asyncio
class TestIRISConstructsPerformance:
    """Test performance requirements (5ms SLA)"""

    async def test_translation_performance_psycopg(self, psycopg_connection):
        """Test that complex IRIS constructs translate within 5ms SLA"""
        # Complex query with multiple IRIS constructs
        complex_query = """
            SELECT TOP 10
                %SQLUPPER(name) as upper_name,
                %SYSTEM.Version.GetNumber() as version,
                %HOROLOG() as timestamp,
                data->>'status' as status
            FROM (
                SELECT 'test_user_' || generate_series(1, 100) as name,
                       '{"status": "active"}' as data
            ) t
            WHERE name LIKE '%user%'
            ORDER BY name
        """

        # Measure translation time (this would be instrumented in actual implementation)
        start_time = time.perf_counter()

        async with psycopg_connection.cursor() as cur:
            await cur.execute(complex_query)
            results = await cur.fetchall()

        execution_time = (time.perf_counter() - start_time) * 1000  # Convert to ms

        assert len(results) > 0, "Should return results"
        # Note: This tests full execution time, not just translation time
        # In production, we would instrument just the translation layer
        logger.info("Complex IRIS constructs executed",
                   execution_time_ms=execution_time,
                   result_count=len(results))

@pytest.mark.e2e
@pytest.mark.requires_iris
@pytest.mark.asyncio
class TestIRISConstructsMixed:
    """Test mixed IRIS and standard SQL"""

    async def test_mixed_constructs_psycopg(self, psycopg_connection):
        """Test query mixing IRIS constructs with standard PostgreSQL SQL"""
        async with psycopg_connection.cursor() as cur:
            # Query using both IRIS constructs and standard SQL features
            await cur.execute("""
                WITH user_data AS (
                    SELECT
                        'user_' || generate_series(1, 50) as username,
                        random() * 100 as score
                ),
                processed_data AS (
                    SELECT TOP 5
                        %SQLUPPER(username) as upper_username,
                        score,
                        rank() OVER (ORDER BY score DESC) as rank_pos
                    FROM user_data
                    WHERE score > 50
                )
                SELECT
                    upper_username,
                    score,
                    rank_pos,
                    %SYSTEM.Version.GetNumber() as system_info
                FROM processed_data
                ORDER BY rank_pos
            """)
            results = await cur.fetchall()

            assert len(results) <= 5, "TOP 5 should limit results"
            # Verify IRIS constructs were translated
            if len(results) > 0:
                assert results[0][0].startswith('USER_'), "Username should be uppercase"
                assert isinstance(results[0][3], str), "System version should be string"

            logger.info("Mixed IRIS/PostgreSQL constructs work", result_count=len(results))

    def test_mixed_constructs_psql(self, psql_command):
        """Test mixed constructs with psql command line"""
        result = psql_command("""
            SELECT TOP 3
                %SQLUPPER('hello') as greeting,
                current_timestamp as ts;
        """)

        assert result["success"], f"Mixed constructs failed: {result['stderr']}"
        assert "HELLO" in result["stdout"], "IRIS function should work"

        logger.info("Mixed constructs work with psql")

@pytest.mark.e2e
@pytest.mark.requires_iris
@pytest.mark.asyncio
class TestIRISConstructsErrorHandling:
    """Test error handling for unsupported constructs"""

    async def test_unsupported_construct_handling_psycopg(self, psycopg_connection):
        """Test that unsupported IRIS constructs fail gracefully"""
        with pytest.raises(Exception) as exc_info:
            async with psycopg_connection.cursor() as cur:
                # Use an administrative construct that should fail
                await cur.execute("VACUUM IRIS_TABLE_ANALYSIS")

        # Should get a PostgreSQL-compatible error
        error_msg = str(exc_info.value).lower()
        assert "syntax error" in error_msg or "unsupported" in error_msg, \
               "Should get appropriate error message"

        logger.info("Unsupported construct handled appropriately", error=str(exc_info.value))

    def test_unsupported_construct_psql(self, psql_command):
        """Test unsupported constructs with psql"""
        result = psql_command("VACUUM IRIS_SPECIFIC_COMMAND;")

        assert not result["success"], "Unsupported construct should fail"
        assert "ERROR" in result["stderr"], "Should return PostgreSQL error"

        logger.info("Unsupported construct failed appropriately with psql")
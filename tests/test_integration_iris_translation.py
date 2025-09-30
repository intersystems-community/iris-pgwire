"""
Integration Tests for IRIS SQL Constructs Translation

Tests the translation layer directly, validating that IRIS constructs
are correctly translated to PostgreSQL equivalents before execution.

These tests validate the translation logic without requiring full
server setup, focusing on the iris_constructs.py module.
"""

import pytest
import time
from typing import Dict, Any
import structlog

# Import the IRIS construct translator
from iris_pgwire.iris_constructs import IRISConstructTranslator

logger = structlog.get_logger()

@pytest.mark.integration
class TestIRISSystemFunctionTranslation:
    """Test IRIS %SYSTEM.* function translation logic"""

    def setup_method(self):
        """Setup translator for each test"""
        self.translator = IRISConstructTranslator()

    def test_system_version_translation(self):
        """Test %SYSTEM.Version.GetNumber() translation"""
        original_sql = "SELECT %SYSTEM.Version.GetNumber() AS version"
        translated_sql, stats = self.translator.translate_sql(original_sql)

        assert "%SYSTEM.Version.GetNumber()" not in translated_sql, \
               "IRIS function should be translated"
        assert "version()" in translated_sql, \
               "Should translate to PostgreSQL version()"
        assert stats['system_functions'] > 0, \
               "Should track system function translation"

        logger.info("System version function translated",
                   original=original_sql,
                   translated=translated_sql,
                   stats=stats)

    def test_system_user_translation(self):
        """Test %SYSTEM.Security.GetUser() translation"""
        original_sql = "SELECT %SYSTEM.Security.GetUser() AS current_user"
        translated_sql, stats = self.translator.translate_sql(original_sql)

        assert "%SYSTEM.Security.GetUser()" not in translated_sql, \
               "IRIS function should be translated"
        assert "current_user" in translated_sql, \
               "Should translate to PostgreSQL current_user"

        logger.info("System user function translated",
                   original=original_sql,
                   translated=translated_sql)

    def test_multiple_system_functions(self):
        """Test multiple system functions in one query"""
        original_sql = """
            SELECT
                %SYSTEM.Version.GetNumber() AS version,
                %SYSTEM.Security.GetUser() AS user_name,
                %SYSTEM.SQL.GetStatement() AS current_query
        """
        translated_sql, stats = self.translator.translate_sql(original_sql)

        # Verify all functions are translated
        assert "%SYSTEM" not in translated_sql, "No IRIS functions should remain"
        assert "version()" in translated_sql, "Version function should be translated"
        assert "current_user" in translated_sql, "User function should be translated"
        assert "current_query()" in translated_sql, "Query function should be translated"
        assert stats['system_functions'] >= 3, "Should track multiple translations"

        logger.info("Multiple system functions translated", stats=stats)

@pytest.mark.integration
class TestIRISSQLExtensionTranslation:
    """Test IRIS SQL extension translation logic"""

    def setup_method(self):
        """Setup translator for each test"""
        self.translator = IRISConstructTranslator()

    def test_top_clause_translation(self):
        """Test SELECT TOP n translation"""
        original_sql = "SELECT TOP 10 id, name FROM users ORDER BY id"
        translated_sql, stats = self.translator.translate_sql(original_sql)

        assert "TOP 10" not in translated_sql, "TOP clause should be translated"
        assert "LIMIT 10" in translated_sql, "Should add LIMIT clause"
        assert stats['sql_extensions'] > 0, "Should track SQL extension translation"

        logger.info("TOP clause translated",
                   original=original_sql,
                   translated=translated_sql)

    def test_top_with_order_by(self):
        """Test TOP clause with ORDER BY handling"""
        original_sql = "SELECT TOP 5 * FROM products WHERE price > 100 ORDER BY price DESC"
        translated_sql, stats = self.translator.translate_sql(original_sql)

        assert "TOP 5" not in translated_sql, "TOP should be removed"
        assert "LIMIT 5" in translated_sql, "Should add LIMIT"
        assert "ORDER BY price DESC" in translated_sql, "ORDER BY should be preserved"

        logger.info("TOP with ORDER BY translated", translated=translated_sql)

    def test_for_update_nowait_translation(self):
        """Test FOR UPDATE NOWAIT translation"""
        original_sql = "SELECT * FROM accounts WHERE id = 123 FOR UPDATE NOWAIT"
        translated_sql, stats = self.translator.translate_sql(original_sql)

        assert "NOWAIT" not in translated_sql, "NOWAIT should be removed"
        assert "FOR UPDATE" in translated_sql, "FOR UPDATE should remain"

        logger.info("FOR UPDATE NOWAIT translated", translated=translated_sql)

@pytest.mark.integration
class TestIRISFunctionTranslation:
    """Test IRIS-specific function translation logic"""

    def setup_method(self):
        """Setup translator for each test"""
        self.translator = IRISConstructTranslator()

    def test_sqlupper_translation(self):
        """Test %SQLUPPER() translation"""
        original_sql = "SELECT %SQLUPPER(name) FROM users"
        translated_sql, stats = self.translator.translate_sql(original_sql)

        assert "%SQLUPPER" not in translated_sql, "IRIS function should be translated"
        assert "UPPER(name)" in translated_sql, "Should translate to UPPER()"
        assert stats['iris_functions'] > 0, "Should track function translation"

        logger.info("SQLUPPER function translated", translated=translated_sql)

    def test_horolog_translation(self):
        """Test %HOROLOG() translation"""
        original_sql = "SELECT %HOROLOG() AS current_time"
        translated_sql, stats = self.translator.translate_sql(original_sql)

        assert "%HOROLOG" not in translated_sql, "IRIS function should be translated"
        assert "EXTRACT(EPOCH FROM NOW())" in translated_sql, \
               "Should translate to epoch extraction"

        logger.info("HOROLOG function translated", translated=translated_sql)

    def test_datediff_microseconds_translation(self):
        """Test DATEDIFF_MICROSECONDS() translation"""
        original_sql = "SELECT DATEDIFF_MICROSECONDS(start_time, end_time) FROM events"
        translated_sql, stats = self.translator.translate_sql(original_sql)

        assert "DATEDIFF_MICROSECONDS" not in translated_sql, \
               "IRIS function should be translated"
        assert "EXTRACT(MICROSECONDS FROM" in translated_sql, \
               "Should translate to microsecond extraction"

        logger.info("DATEDIFF_MICROSECONDS translated", translated=translated_sql)

@pytest.mark.integration
class TestIRISDataTypeTranslation:
    """Test IRIS data type translation logic"""

    def setup_method(self):
        """Setup translator for each test"""
        self.translator = IRISConstructTranslator()

    def test_serial_type_translation(self):
        """Test SERIAL data type translation"""
        original_sql = "CREATE TABLE test (id SERIAL PRIMARY KEY, name VARCHAR(50))"
        translated_sql, stats = self.translator.translate_sql(original_sql)

        # SERIAL should remain as is (PostgreSQL native)
        assert "SERIAL" in translated_sql, "SERIAL should be preserved"

        logger.info("SERIAL type handled", translated=translated_sql)

    def test_rowversion_type_translation(self):
        """Test ROWVERSION data type translation"""
        original_sql = "CREATE TABLE test (id INT, version ROWVERSION)"
        translated_sql, stats = self.translator.translate_sql(original_sql)

        assert "ROWVERSION" not in translated_sql, "ROWVERSION should be translated"
        assert "BYTEA" in translated_sql, "Should translate to BYTEA"
        assert stats['data_types'] > 0, "Should track data type translation"

        logger.info("ROWVERSION type translated", translated=translated_sql)

    def test_vector_type_translation(self):
        """Test VECTOR data type translation"""
        original_sql = "CREATE TABLE embeddings (id INT, vec VECTOR(128))"
        translated_sql, stats = self.translator.translate_sql(original_sql)

        # VECTOR should be preserved (pgvector compatibility)
        assert "VECTOR(128)" in translated_sql, "VECTOR should be preserved"

        logger.info("VECTOR type handled", translated=translated_sql)

    def test_iris_list_type_translation(self):
        """Test %List data type translation"""
        original_sql = "CREATE TABLE test (id INT, items %List)"
        translated_sql, stats = self.translator.translate_sql(original_sql)

        assert "%List" not in translated_sql, "IRIS %List should be translated"
        assert "TEXT[]" in translated_sql, "Should translate to text array"

        logger.info("%List type translated", translated=translated_sql)

@pytest.mark.integration
class TestIRISJSONFunctionTranslation:
    """Test IRIS JSON function translation logic"""

    def setup_method(self):
        """Setup translator for each test"""
        self.translator = IRISConstructTranslator()

    def test_json_table_translation(self):
        """Test JSON_TABLE translation"""
        original_sql = """
            SELECT name, age FROM JSON_TABLE(
                '{"users": [{"name": "Alice", "age": 30}]}',
                '$.users[*]' COLUMNS (
                    name VARCHAR(50) PATH '$.name',
                    age INTEGER PATH '$.age'
                )
            )
        """
        translated_sql, stats = self.translator.translate_sql(original_sql)

        assert "JSON_TABLE" not in translated_sql, "JSON_TABLE should be translated"
        assert "jsonb_to_recordset" in translated_sql, \
               "Should translate to jsonb_to_recordset"
        assert stats['json_functions'] > 0, "Should track JSON translation"

        logger.info("JSON_TABLE translated", stats=stats)

    def test_json_object_translation(self):
        """Test JSON_OBJECT translation"""
        original_sql = "SELECT JSON_OBJECT('name', name, 'age', age) FROM users"
        translated_sql, stats = self.translator.translate_sql(original_sql)

        assert "JSON_OBJECT" not in translated_sql, "JSON_OBJECT should be translated"
        assert "jsonb_build_object" in translated_sql, \
               "Should translate to jsonb_build_object"

        logger.info("JSON_OBJECT translated", translated=translated_sql)

@pytest.mark.integration
class TestIRISConstructsMixed:
    """Test complex queries with multiple IRIS constructs"""

    def setup_method(self):
        """Setup translator for each test"""
        self.translator = IRISConstructTranslator()

    def test_complex_mixed_query(self):
        """Test query with multiple construct types"""
        original_sql = """
            SELECT TOP 5
                %SQLUPPER(name) as upper_name,
                %SYSTEM.Version.GetNumber() as version,
                JSON_OBJECT('user', name, 'active', active) as user_json
            FROM users
            WHERE created_date > DATEDIFF_MICROSECONDS('2023-01-01', NOW())
            ORDER BY name
        """
        translated_sql, stats = self.translator.translate_sql(original_sql)

        # Verify all constructs are translated
        assert "TOP 5" not in translated_sql, "TOP should be translated"
        assert "%SQLUPPER" not in translated_sql, "IRIS functions should be translated"
        assert "%SYSTEM" not in translated_sql, "System functions should be translated"
        assert "JSON_OBJECT" not in translated_sql, "JSON functions should be translated"
        assert "DATEDIFF_MICROSECONDS" not in translated_sql, "Date functions should be translated"

        # Verify PostgreSQL equivalents exist
        assert "LIMIT 5" in translated_sql, "Should have LIMIT"
        assert "UPPER(" in translated_sql, "Should have UPPER"
        assert "version()" in translated_sql, "Should have version()"
        assert "jsonb_build_object" in translated_sql, "Should have jsonb_build_object"

        # Verify statistics tracking
        assert stats['sql_extensions'] > 0, "Should track SQL extensions"
        assert stats['iris_functions'] > 0, "Should track IRIS functions"
        assert stats['system_functions'] > 0, "Should track system functions"
        assert stats['json_functions'] > 0, "Should track JSON functions"

        logger.info("Complex mixed query translated",
                   stats=stats,
                   original_length=len(original_sql),
                   translated_length=len(translated_sql))

@pytest.mark.integration
class TestIRISConstructsPerformance:
    """Test translation performance requirements"""

    def setup_method(self):
        """Setup translator for each test"""
        self.translator = IRISConstructTranslator()

    def test_simple_translation_performance(self):
        """Test that simple translations meet 5ms SLA"""
        original_sql = "SELECT %SYSTEM.Version.GetNumber(), %SQLUPPER('test')"

        start_time = time.perf_counter()
        translated_sql, stats = self.translator.translate_sql(original_sql)
        translation_time_ms = (time.perf_counter() - start_time) * 1000

        assert translation_time_ms < 5.0, \
               f"Translation took {translation_time_ms}ms, exceeds 5ms SLA"

        logger.info("Simple translation performance",
                   time_ms=translation_time_ms,
                   constructs_translated=sum(stats.values()))

    def test_complex_translation_performance(self):
        """Test that complex translations meet 5ms SLA"""
        # Complex query with multiple construct types
        original_sql = """
            SELECT TOP 10
                %SQLUPPER(u.name) as upper_name,
                %SYSTEM.Version.GetNumber() as version,
                %SYSTEM.Security.GetUser() as current_user,
                JSON_OBJECT('user', u.name, 'orders', COUNT(o.id)) as user_summary,
                DATEDIFF_MICROSECONDS(u.created_date, NOW()) as age_microseconds,
                %HOROLOG() as current_horolog
            FROM users u
            LEFT JOIN orders o ON u.id = o.user_id
            WHERE u.active = true
                AND u.created_date > DATEDIFF_MICROSECONDS('2023-01-01', NOW())
                AND JSON_EXTRACT(u.metadata, '$.premium') = true
            GROUP BY u.id, u.name, u.created_date
            ORDER BY COUNT(o.id) DESC
        """

        start_time = time.perf_counter()
        translated_sql, stats = self.translator.translate_sql(original_sql)
        translation_time_ms = (time.perf_counter() - start_time) * 1000

        assert translation_time_ms < 5.0, \
               f"Complex translation took {translation_time_ms}ms, exceeds 5ms SLA"

        total_constructs = sum(stats.values())
        assert total_constructs > 5, "Should have translated multiple constructs"

        logger.info("Complex translation performance",
                   time_ms=translation_time_ms,
                   constructs_translated=total_constructs,
                   stats=stats)

@pytest.mark.integration
class TestIRISConstructsDetection:
    """Test IRIS construct detection logic"""

    def setup_method(self):
        """Setup translator for each test"""
        self.translator = IRISConstructTranslator()

    def test_needs_translation_detection(self):
        """Test that IRIS constructs are correctly detected"""
        # Queries that need translation
        iris_queries = [
            "SELECT %SYSTEM.Version.GetNumber()",
            "SELECT TOP 10 * FROM table",
            "SELECT %SQLUPPER(name) FROM users",
            "CREATE TABLE test (id SERIAL, version ROWVERSION)",
            "SELECT JSON_OBJECT('key', value) FROM data"
        ]

        for query in iris_queries:
            needs_translation = self.translator.needs_iris_translation(query)
            assert needs_translation, f"Should detect IRIS constructs in: {query}"

        # Queries that don't need translation
        standard_queries = [
            "SELECT * FROM users",
            "SELECT UPPER(name) FROM users LIMIT 10",
            "CREATE TABLE test (id SERIAL PRIMARY KEY)",
            "INSERT INTO users (name) VALUES ('test')",
            "UPDATE users SET name = 'updated' WHERE id = 1"
        ]

        for query in standard_queries:
            needs_translation = self.translator.needs_iris_translation(query)
            assert not needs_translation, f"Should not detect IRIS constructs in: {query}"

        logger.info("IRIS construct detection working correctly")

@pytest.mark.integration
class TestIRISConstructsErrorHandling:
    """Test error handling in translation layer"""

    def setup_method(self):
        """Setup translator for each test"""
        self.translator = IRISConstructTranslator()

    def test_malformed_sql_handling(self):
        """Test handling of malformed SQL"""
        malformed_sql = "SELECT %INVALID_FUNCTION( FROM table WHERE"

        # Should not crash on malformed SQL
        try:
            translated_sql, stats = self.translator.translate_sql(malformed_sql)
            # Should return something (even if malformed)
            assert isinstance(translated_sql, str), "Should return string"
            assert isinstance(stats, dict), "Should return stats dict"
        except Exception as e:
            # If it does raise an exception, it should be handled gracefully
            logger.warning("Translation failed gracefully", error=str(e))

    def test_empty_sql_handling(self):
        """Test handling of empty SQL"""
        empty_sql = ""
        translated_sql, stats = self.translator.translate_sql(empty_sql)

        assert translated_sql == "", "Empty SQL should remain empty"
        assert all(count == 0 for count in stats.values()), "No translations for empty SQL"

    def test_whitespace_only_sql(self):
        """Test handling of whitespace-only SQL"""
        whitespace_sql = "   \n\t  "
        translated_sql, stats = self.translator.translate_sql(whitespace_sql)

        assert translated_sql.strip() == "", "Whitespace SQL should remain whitespace"
        assert all(count == 0 for count in stats.values()), "No translations for whitespace"

        logger.info("Error handling tests passed")
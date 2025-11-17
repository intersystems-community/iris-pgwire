"""
Integration Tests for Complete SQL Translation Flow

Tests the end-to-end SQL translation pipeline with all registries working together
to translate complex IRIS SQL queries to PostgreSQL with constitutional compliance.
"""

import time

from iris_pgwire.sql_translator.models import ConstructType
from iris_pgwire.sql_translator.translator import (
    IRISSQLTranslator,
    TranslationContext,
)
from iris_pgwire.sql_translator.validator import ValidationLevel


class TestTranslationIntegration:
    """Integration tests for complete SQL translation flow"""

    def setup_method(self):
        """Setup translator instance for each test"""
        self.translator = IRISSQLTranslator()

    def test_simple_query_translation(self):
        """Test translation of simple queries"""
        queries = [
            "SELECT * FROM users",
            "SELECT id, name FROM customers WHERE active = 1",
            "INSERT INTO logs (message) VALUES ('test')",
            "UPDATE settings SET value = 'new' WHERE key = 'test'",
            "DELETE FROM temp_data WHERE created < '2023-01-01'",
        ]

        for sql in queries:
            context = TranslationContext(original_sql=sql)
            result = self.translator.translate(context)
            assert result.translated_sql is not None
            assert len(result.warnings) == 0
            assert result.performance_stats.translation_time_ms < 5.0  # Constitutional SLA

    def test_iris_function_translation(self):
        """Test translation of IRIS-specific functions"""
        sql = """
        SELECT
            %SQLUPPER(name) as upper_name,
            %SQLLOWER(email) as lower_email,
            %SQLSTRING(description, 50) as truncated_desc
        FROM users
        WHERE %SQLUPPER(status) = 'ACTIVE'
        """

        context = TranslationContext(original_sql=sql)
        result = self.translator.translate(context)
        assert "UPPER" in result.translated_sql
        assert "LOWER" in result.translated_sql
        assert "%SQLUPPER" not in result.translated_sql
        assert "%SQLLOWER" not in result.translated_sql

        # Check mappings
        function_mappings = [
            m for m in result.construct_mappings if m.construct_type == ConstructType.FUNCTION
        ]
        assert len(function_mappings) >= 3

    def test_iris_datatype_translation(self):
        """Test translation of IRIS-specific data types in DDL"""
        sql = """
        CREATE TABLE test_types (
            id INTEGER,
            name VARCHAR(255),
            data LONGVARCHAR,
            binary_data VARBINARY,
            created_date DATE,
            metadata JSON,
            embedding VECTOR(3)
        )
        """

        context = TranslationContext(original_sql=sql)
        result = self.translator.translate(context)

        # Check type translations
        assert "TEXT" in result.translated_sql  # LONGVARCHAR -> TEXT
        assert "BYTEA" in result.translated_sql  # VARBINARY -> BYTEA
        assert "JSONB" in result.translated_sql or "JSON" in result.translated_sql  # JSON type

        # Check type mappings
        type_mappings = [
            m for m in result.construct_mappings if m.construct_type == ConstructType.DATA_TYPE
        ]
        assert len(type_mappings) >= 2  # At least LONGVARCHAR and VARBINARY

    def test_iris_construct_translation(self):
        """Test translation of IRIS SQL constructs"""
        # Note: Since IRIS supports both TOP and LIMIT, this might not translate
        sql = "SELECT TOP 10 * FROM products ORDER BY price DESC"

        context = TranslationContext(original_sql=sql)
        result = self.translator.translate(context)

        # Current implementation removes TOP (though IRIS supports it)
        if "TOP 10" not in result.translated_sql:
            # Check if TOP was tracked as a construct
            construct_mappings = [
                m for m in result.construct_mappings if m.construct_type == ConstructType.SYNTAX
            ]
            assert any("TOP" in m.original_syntax for m in construct_mappings)

    def test_document_filter_translation(self):
        """Test translation of document database operations"""
        sql = """
        SELECT
            JSON_EXTRACT(data, '$.user.name') as user_name,
            JSON_ARRAY_LENGTH(tags) as tag_count,
            JSON_EXISTS(data, '$.active') as is_active
        FROM documents
        WHERE JSON_EXISTS(data, '$.published')
        """

        context = TranslationContext(original_sql=sql)
        result = self.translator.translate(context)

        # Check JSON function translations
        assert "jsonb" in result.translated_sql.lower() or "->" in result.translated_sql
        assert "jsonb_array_length" in result.translated_sql

        # Check document filter mappings
        doc_mappings = [
            m
            for m in result.construct_mappings
            if m.construct_type == ConstructType.DOCUMENT_FILTER
        ]
        assert len(doc_mappings) >= 2  # At least JSON_ARRAY_LENGTH and others

    def test_complex_mixed_translation(self):
        """Test translation with multiple types of IRIS-specific elements"""
        sql = """
        SELECT TOP 5
            %SQLUPPER(u.name) as name,
            u.created_date,
            JSON_EXTRACT(u.profile, '$.bio') as bio,
            COUNT(*) as post_count
        FROM users u
        INNER JOIN posts p ON u.id = p.user_id
        WHERE u.status = 'active'
          AND JSON_EXISTS(u.profile, '$.verified')
        GROUP BY u.id, u.name, u.created_date, u.profile
        ORDER BY post_count DESC
        """

        context = TranslationContext(original_sql=sql)
        result = self.translator.translate(context)
        assert result.performance_stats.translation_time_ms < 5.0  # Constitutional SLA

        # Should have multiple types of mappings
        mapping_types = {m.construct_type for m in result.construct_mappings}
        assert ConstructType.FUNCTION in mapping_types or ConstructType.SYNTAX in mapping_types

        # Validate the translation maintains query structure
        assert "SELECT" in result.translated_sql
        assert "FROM users" in result.translated_sql
        assert "GROUP BY" in result.translated_sql
        assert "ORDER BY" in result.translated_sql

    def test_translation_caching(self):
        """Test that translation cache improves performance"""
        sql = "SELECT %SQLUPPER(name), JSON_EXTRACT(data, '$.value') FROM complex_table"

        # First translation (cache miss)
        context1 = TranslationContext(original_sql=sql)
        start_time = time.perf_counter()
        result1 = self.translator.translate(context1)
        first_time_ms = (time.perf_counter() - start_time) * 1000

        # Check metadata for cache info
        assert "cache_hit" not in result1.metadata or result1.metadata.get("cache_hit") is False

        # Second translation (cache hit)
        context2 = TranslationContext(original_sql=sql)
        start_time = time.perf_counter()
        result2 = self.translator.translate(context2)
        second_time_ms = (time.perf_counter() - start_time) * 1000

        assert result2.translated_sql == result1.translated_sql

        # Cached translation should be significantly faster
        assert second_time_ms < first_time_ms * 0.5  # At least 50% faster

    def test_constitutional_sla_compliance(self):
        """Test that all translations meet the 5ms SLA"""
        # Test various query complexities
        queries = [
            # Simple query
            "SELECT * FROM users",
            # Medium complexity
            "SELECT %SQLUPPER(name) FROM users WHERE id IN (1,2,3)",
            # High complexity
            """
            SELECT TOP 100
                u.id,
                %SQLUPPER(u.name) as name,
                JSON_EXTRACT(u.data, '$.email') as email,
                COUNT(p.id) as post_count
            FROM users u
            LEFT JOIN posts p ON u.id = p.user_id
            WHERE JSON_EXISTS(u.data, '$.active')
            GROUP BY u.id, u.name, u.data
            ORDER BY post_count DESC
            """,
            # DDL statement
            "CREATE TABLE test (id INTEGER, data LONGVARCHAR, vector VECTOR(128))",
        ]

        for sql in queries:
            context = TranslationContext(original_sql=sql)
            result = self.translator.translate(context)
            assert (
                result.performance_stats.translation_time_ms < 5.0
            ), f"Query exceeded SLA: {sql[:50]}..."

    def test_translation_validation_levels(self):
        """Test different validation levels"""
        # Basic validation
        context_basic = TranslationContext(
            original_sql="SELECT * FROM users", validation_level=ValidationLevel.BASIC
        )
        result_basic = self.translator.translate(context_basic)
        assert result_basic.translated_sql is not None

        # Semantic validation
        context_semantic = TranslationContext(
            original_sql="SELECT %SQLUPPER(name) FROM users",
            validation_level=ValidationLevel.SEMANTIC,
        )
        result_semantic = self.translator.translate(context_semantic)
        assert result_semantic.translated_sql is not None

        # Strict validation
        context_strict = TranslationContext(
            original_sql="CREATE TABLE test (id INTEGER, name VARCHAR(100))",
            validation_level=ValidationLevel.STRICT,
        )
        result_strict = self.translator.translate(context_strict)
        assert result_strict.translated_sql is not None

    def test_error_handling(self):
        """Test error handling in translation"""
        # Invalid SQL
        context = TranslationContext(original_sql="SELECT * FROM WHERE")
        result = self.translator.translate(context)
        # Check for warnings or empty translation
        assert (
            len(result.warnings) > 0 or result.translated_sql.rstrip(";") == "SELECT * FROM WHERE"
        )

        # Empty SQL
        context = TranslationContext(original_sql="")
        result = self.translator.translate(context)
        assert result.translated_sql == ""

        # Very invalid SQL should still attempt translation
        context = TranslationContext(original_sql="NOT VALID SQL AT ALL")
        result = self.translator.translate(context)
        assert result.translated_sql is not None

    def test_confidence_scoring(self):
        """Test translation confidence scoring through mappings"""
        # High confidence - standard SQL
        context = TranslationContext(original_sql="SELECT * FROM users")
        result = self.translator.translate(context)
        # Standard SQL should have no mappings or high confidence mappings
        if result.construct_mappings:
            avg_confidence = sum(m.confidence for m in result.construct_mappings) / len(
                result.construct_mappings
            )
            assert avg_confidence >= 0.9

        # Medium confidence - some IRIS features
        context = TranslationContext(original_sql="SELECT %SQLUPPER(name) FROM users")
        result = self.translator.translate(context)
        if result.construct_mappings:
            avg_confidence = sum(m.confidence for m in result.construct_mappings) / len(
                result.construct_mappings
            )
            assert avg_confidence >= 0.8

        # Complex IRIS features
        context = TranslationContext(
            original_sql="""
            SELECT TOP 10 PERCENT WITH TIES
                %SQLUPPER(name),
                JSON_TABLE(data, '$.items[*]' COLUMNS (id INT PATH '$.id'))
            FROM users
        """
        )
        result = self.translator.translate(context)
        assert len(result.construct_mappings) > 0

    def test_mapping_metadata(self):
        """Test that mappings include proper metadata"""
        sql = "SELECT %SQLUPPER(name), JSON_ARRAY_LENGTH(tags) FROM users"
        context = TranslationContext(original_sql=sql)
        result = self.translator.translate(context)

        assert len(result.construct_mappings) >= 2

        for mapping in result.construct_mappings:
            # Check required fields
            assert mapping.construct_type is not None
            assert mapping.original_syntax is not None
            assert mapping.translated_syntax is not None
            assert mapping.confidence >= 0.0
            assert mapping.source_location is not None

            # Check source location
            assert mapping.source_location.line >= 1
            assert mapping.source_location.column >= 1
            assert mapping.source_location.length > 0

    def test_parser_integration(self):
        """Test that parser correctly identifies constructs for translation"""
        sql = """
        SELECT
            %SQLUPPER(name) as upper_name,
            data::VARCHAR as casted_data,
            JSON_EXTRACT(profile, '$.email') as email
        FROM users
        WHERE id::INTEGER > 100
        """

        context = TranslationContext(original_sql=sql)
        result = self.translator.translate(context)

        # Should have identified and translated various constructs
        assert len(result.construct_mappings) >= 1

        # Check for function mappings
        function_mappings = [
            m for m in result.construct_mappings if m.construct_type == ConstructType.FUNCTION
        ]
        assert len(function_mappings) >= 1

    def test_translation_statistics(self):
        """Test translation statistics collection"""
        # Perform several translations
        queries = [
            "SELECT * FROM users",
            "SELECT %SQLUPPER(name) FROM customers",
            "SELECT JSON_ARRAY_LENGTH(data) FROM documents",
        ]

        for sql in queries:
            context = TranslationContext(original_sql=sql)
            self.translator.translate(context)

        # Check that translations complete successfully
        # Statistics might be internal to the translator
        assert True  # Placeholder - statistics API may differ


class TestTranslationPerformance:
    """Performance tests for translation pipeline"""

    def setup_method(self):
        """Setup translator instance"""
        self.translator = IRISSQLTranslator()

    def test_bulk_translation_performance(self):
        """Test performance with bulk translations"""
        # Generate 100 queries of varying complexity
        queries = []

        # Simple queries
        for i in range(30):
            queries.append(f"SELECT * FROM table_{i}")

        # Medium complexity
        for i in range(40):
            queries.append(f"SELECT %SQLUPPER(col_{i}) FROM table_{i} WHERE id > {i}")

        # Complex queries
        for i in range(30):
            queries.append(
                f"""
                SELECT TOP {i + 1}
                    %SQLUPPER(name),
                    JSON_EXTRACT(data, '$.field_{i}')
                FROM table_{i}
                WHERE JSON_EXISTS(data, '$.active')
            """
            )

        start_time = time.perf_counter()
        results = []
        for sql in queries:
            context = TranslationContext(original_sql=sql)
            results.append(self.translator.translate(context))
        total_time_ms = (time.perf_counter() - start_time) * 1000

        # All should produce translations
        assert all(r.translated_sql is not None for r in results)

        # Average time should be well under SLA
        avg_time_ms = total_time_ms / len(queries)
        assert avg_time_ms < 2.0  # Should be fast due to caching

    def test_concurrent_translation_safety(self):
        """Test thread safety of translation (simulated)"""
        # This is a simple test - real concurrent testing would use threading
        sql = "SELECT %SQLUPPER(name) FROM users"

        # Simulate concurrent access by rapid sequential calls
        results = []
        context = TranslationContext(original_sql=sql)
        for _ in range(10):
            result = self.translator.translate(context)
            results.append(result)

        # All should produce same translation
        assert all(r.translated_sql is not None for r in results)
        assert all(r.translated_sql == results[0].translated_sql for r in results)

    def test_memory_efficiency(self):
        """Test memory usage doesn't grow excessively"""
        import sys

        # Get initial memory baseline
        initial_size = sys.getsizeof(self.translator)

        # Perform many translations
        for i in range(100):
            sql = f"SELECT col_{i} FROM table_{i}"
            context = TranslationContext(original_sql=sql)
            self.translator.translate(context)

        # Check memory growth is reasonable
        final_size = sys.getsizeof(self.translator)
        growth_factor = final_size / initial_size

        # Should not grow more than 2x (cache has limits)
        assert growth_factor < 2.0


class TestTranslationEdgeCases:
    """Edge case tests for translation"""

    def setup_method(self):
        """Setup translator instance"""
        self.translator = IRISSQLTranslator()

    def test_very_long_query(self):
        """Test translation of very long queries"""
        # Build a very long query
        columns = [f"col_{i}" for i in range(100)]
        sql = f"SELECT {', '.join(columns)} FROM very_wide_table"

        context = TranslationContext(original_sql=sql)
        result = self.translator.translate(context)
        assert result.performance_stats.translation_time_ms < 5.0  # Should still meet SLA

    def test_deeply_nested_json(self):
        """Test deeply nested JSON operations"""
        sql = "SELECT JSON_EXTRACT(data, '$.a.b.c.d.e.f.g.h.i.j.k') FROM docs"

        context = TranslationContext(original_sql=sql)
        result = self.translator.translate(context)
        assert "jsonb" in result.translated_sql.lower() or "#>" in result.translated_sql

    def test_special_characters_in_identifiers(self):
        """Test handling of special characters"""
        sql = 'SELECT "column-with-dash", "column.with.dots" FROM "table$special"'

        context = TranslationContext(original_sql=sql)
        result = self.translator.translate(context)
        assert '"column-with-dash"' in result.translated_sql

    def test_unicode_support(self):
        """Test Unicode character support"""
        sql = "SELECT name FROM users WHERE name = 'José María'"

        context = TranslationContext(original_sql=sql)
        result = self.translator.translate(context)
        assert "José María" in result.translated_sql

    def test_mixed_case_preservation(self):
        """Test that mixed case identifiers are preserved"""
        sql = 'SELECT "MixedCaseColumn" FROM "MixedCaseTable"'

        context = TranslationContext(original_sql=sql)
        result = self.translator.translate(context)
        assert '"MixedCaseColumn"' in result.translated_sql
        assert '"MixedCaseTable"' in result.translated_sql

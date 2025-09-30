"""
Unit Tests for IRIS SQL Construct Registry

Tests the SQL construct mapping registry with comprehensive coverage of all IRIS SQL
construct mappings and PostgreSQL equivalents with constitutional compliance validation.
"""

import pytest
from unittest.mock import patch, MagicMock

from iris_pgwire.sql_translator.mappings.constructs import (
    IRISSQLConstructRegistry,
    get_construct_registry,
    translate_sql_constructs,
    has_sql_construct
)
from iris_pgwire.sql_translator.models import ConstructMapping, ConstructType


class TestIRISSQLConstructRegistry:
    """Test suite for IRIS SQL construct registry"""

    def setup_method(self):
        """Setup fresh registry for each test"""
        self.registry = IRISSQLConstructRegistry()

    def test_registry_initialization(self):
        """Test registry initializes with core IRIS SQL constructs"""
        # Should NOT have TOP clause constructs (IRIS supports TOP natively)
        assert not self.registry.has_construct('TOP_BASIC')

        # Should have construct patterns
        assert hasattr(self.registry, '_construct_patterns')
        assert len(self.registry._construct_patterns) > 0

    def test_top_clause_translation(self):
        """Test IRIS TOP clause handling - IRIS supports TOP natively"""
        sql = "SELECT TOP 10 * FROM users"
        translated_sql, mappings = self.registry.translate_constructs(sql)

        # IRIS supports TOP natively - should NOT be translated
        assert 'TOP 10' in translated_sql  # Should preserve TOP clause
        assert translated_sql == sql  # Should be unchanged

        # Should have no mappings since no translation occurred
        assert len(mappings) == 0

        # NOTE: Since IRIS supports both TOP and LIMIT natively,
        # this translation is unnecessary and has been removed

    def test_top_with_percent_translation(self):
        """Test IRIS TOP PERCENT clause handling - IRIS supports TOP natively"""
        sql = "SELECT TOP 25 PERCENT * FROM users"
        translated_sql, mappings = self.registry.translate_constructs(sql)

        # IRIS supports TOP PERCENT natively - should NOT be translated
        assert 'TOP 25 PERCENT' in translated_sql  # Should preserve TOP PERCENT clause
        assert translated_sql == sql  # Should be unchanged
        assert len(mappings) == 0  # No translation mappings

    def test_iris_specific_functions_translation(self):
        """Test IRIS-specific function translation"""
        # Skip JSON_TABLE test - not implemented in current registry
        # This is a placeholder for future JSON function support
        pass

    def test_multiple_constructs_in_single_query(self):
        """Test translation of multiple IRIS constructs in one query"""
        sql = "SELECT TOP 5 name FROM users WHERE data->'status' = 'active'"
        translated_sql, mappings = self.registry.translate_constructs(sql)

        # Should preserve TOP clause (IRIS supports it natively)
        assert 'TOP 5' in translated_sql

        # Should preserve JSON operators (already PostgreSQL compatible)
        assert "data->'status'" in translated_sql

        # Should be unchanged since no constructs need translation
        assert translated_sql == sql

    def test_case_insensitive_translation(self):
        """Test construct translation is case insensitive"""
        sql_upper = "SELECT TOP 10 * FROM users"
        sql_lower = "SELECT top 10 * FROM users"

        translated_upper, mappings_upper = self.registry.translate_constructs(sql_upper)
        translated_lower, mappings_lower = self.registry.translate_constructs(sql_lower)

        # Both should preserve TOP (IRIS supports it natively)
        assert 'TOP 10' in translated_upper
        assert 'top 10' in translated_lower

        # Should have no mappings (no translation needed)
        assert len(mappings_upper) == 0
        assert len(mappings_lower) == 0

    def test_no_constructs_passthrough(self):
        """Test SQL without IRIS constructs passes through unchanged"""
        sql = "SELECT * FROM users WHERE id = 1"
        translated_sql, mappings = self.registry.translate_constructs(sql)

        # Should remain unchanged
        assert translated_sql == sql
        assert len(mappings) == 0

    def test_complex_query_translation(self):
        """Test translation of complex queries with multiple constructs"""
        sql = """
        SELECT TOP 100 u.name, u.email
        FROM users u
        WHERE u.created_date > '2023-01-01'
        ORDER BY u.created_date DESC
        """

        translated_sql, mappings = self.registry.translate_constructs(sql)

        # Should preserve TOP clause (IRIS supports TOP natively)
        assert 'TOP 100' in translated_sql
        assert translated_sql.strip() == sql.strip()  # Should be unchanged

        # Should preserve the rest of the query structure
        assert 'FROM users u' in translated_sql
        assert 'ORDER BY u.created_date DESC' in translated_sql
        assert len(mappings) == 0  # No mappings needed

    def test_constitutional_compliance(self):
        """Test constitutional compliance requirements"""
        # Test that translation performance meets SLA
        import time

        sql = "SELECT TOP 50 * FROM large_table WHERE status = 'active'"

        start_time = time.perf_counter()
        translated_sql, mappings = self.registry.translate_constructs(sql)
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Should complete under constitutional 5ms SLA
        assert elapsed_ms < 5.0, f"Translation exceeded SLA: {elapsed_ms}ms"

        # All mappings should have high confidence
        for mapping in mappings:
            assert mapping.confidence >= 0.8, f"Low confidence mapping: {mapping.original_syntax}"

    def test_mapping_stats(self):
        """Test registry statistics collection"""
        stats = self.registry.get_mapping_stats()

        assert 'total_constructs' in stats
        assert 'confidence_distribution' in stats

        # Should have at least some constructs
        assert stats['total_constructs'] >= 1

    def test_construct_mapping_data_integrity(self):
        """Test construct mapping data integrity"""
        if hasattr(self.registry, '_construct_patterns'):
            for construct_name, construct_info in self.registry._construct_patterns.items():
                # Validate construct structure
                assert construct_name is not None and construct_name.strip() != ''
                assert 'pattern' in construct_info
                assert 'confidence' in construct_info
                assert isinstance(construct_info['confidence'], (int, float))
                assert 0.0 <= construct_info['confidence'] <= 1.0

    def test_registry_singleton(self):
        """Test global registry singleton behavior"""
        registry1 = get_construct_registry()
        registry2 = get_construct_registry()

        # Should be the same instance
        assert registry1 is registry2

    def test_convenience_functions(self):
        """Test module-level convenience functions"""
        # Test has_sql_construct - TOP_BASIC no longer exists (removed)
        assert not has_sql_construct('TOP_BASIC')

        # Test translate_sql_constructs
        sql = "SELECT TOP 10 * FROM users"
        translated = translate_sql_constructs(sql)
        # Should preserve TOP (IRIS supports it natively)
        assert 'TOP 10' in translated[0]
        assert translated[0] == sql  # Should be unchanged

    def test_edge_cases(self):
        """Test edge cases and error conditions"""
        # Empty string
        translated_sql, mappings = self.registry.translate_constructs("")
        assert translated_sql == ""
        assert len(mappings) == 0

        # None input handling (if supported)
        try:
            translated_sql, mappings = self.registry.translate_constructs(None)
            assert translated_sql is None or translated_sql == ""
        except (TypeError, AttributeError):
            # Expected for None input
            pass

        # Very long query
        long_sql = "SELECT TOP 10 * FROM " + "very_" * 1000 + "long_table_name"
        translated_sql, mappings = self.registry.translate_constructs(long_sql)
        assert 'TOP 10' in translated_sql  # Should preserve TOP clause
        assert translated_sql == long_sql  # Should be unchanged

    def test_nested_constructs(self):
        """Test handling of nested or complex IRIS constructs"""
        # Test subquery with TOP
        sql = """
        SELECT *
        FROM users
        WHERE id IN (SELECT TOP 5 user_id FROM recent_activity)
        """

        translated_sql, mappings = self.registry.translate_constructs(sql)

        # Should preserve nested TOP clause (IRIS supports TOP natively)
        assert 'TOP 5' in translated_sql
        assert translated_sql.strip() == sql.strip()  # Should be unchanged
        assert len(mappings) == 0  # No translations needed

    def test_construct_with_expressions(self):
        """Test constructs used with complex expressions"""
        sql = "SELECT TOP (10 + 5) * FROM users"
        translated_sql, mappings = self.registry.translate_constructs(sql)

        # Current pattern doesn't match expressions in parentheses
        # So TOP with expression should pass through unchanged
        assert 'TOP (10 + 5)' in translated_sql


class TestConstructMappingModel:
    """Test the ConstructMapping data model"""

    def test_construct_mapping_creation(self):
        """Test ConstructMapping model creation"""
        from iris_pgwire.sql_translator.models import SourceLocation

        source_loc = SourceLocation(line=1, column=1, length=10)
        mapping = ConstructMapping(
            construct_type=ConstructType.SYNTAX,
            original_syntax='TOP 10',
            translated_syntax='LIMIT 10',
            confidence=0.95,
            source_location=source_loc
        )

        assert mapping.original_syntax == 'TOP 10'
        assert mapping.translated_syntax == 'LIMIT 10'
        assert mapping.confidence == 0.95
        assert mapping.construct_type == ConstructType.SYNTAX


class TestSQLConstructRegistryIntegration:
    """Integration tests for SQL construct registry with other components"""

    def test_registry_with_parser_integration(self):
        """Test registry integration with SQL parser"""
        # This would test how the registry is used by the parser
        # to identify and translate IRIS SQL constructs
        pass  # Placeholder for integration tests

    def test_registry_with_complete_translation_pipeline(self):
        """Test registry as part of complete translation pipeline"""
        # Test with multiple types of translations in one query
        sql = "SELECT TOP 10 %SQLUPPER(name) FROM users WHERE id > 0"

        # This would need integration with function registry
        # to test complete translation
        translated_sql, mappings = get_construct_registry().translate_constructs(sql)

        # Should preserve the TOP clause (IRIS supports TOP natively)
        assert 'TOP 10' in translated_sql
        # Only function constructs get translated (not in this registry)

    def test_constitutional_compliance_reporting(self):
        """Test constitutional compliance reporting"""
        registry = get_construct_registry()
        stats = registry.get_mapping_stats()

        # Should report compliance metrics
        if 'constitutional_compliance' in stats:
            compliance = stats['constitutional_compliance']
            assert 'high_confidence_rate' in compliance
            assert compliance['high_confidence_rate'] >= 0.8  # 80% high confidence requirement


# Performance benchmark tests
class TestSQLConstructRegistryPerformance:
    """Performance tests for constitutional SLA compliance"""

    def test_bulk_translation_performance(self):
        """Test bulk construct translation performance"""
        registry = get_construct_registry()

        queries = [
            "SELECT TOP 10 * FROM users",
            "SELECT TOP 25 name FROM products WHERE active = 1",
            "SELECT TOP 100 id, email FROM customers ORDER BY created_date",
            "SELECT * FROM orders WHERE total > 100",  # No constructs
            "SELECT TOP 5 * FROM (SELECT TOP 20 * FROM large_table) subquery"
        ]

        import time
        start_time = time.perf_counter()

        for sql in queries:
            translated_sql, mappings = registry.translate_constructs(sql)
            assert translated_sql is not None

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Should complete well under constitutional 5ms SLA
        assert elapsed_ms < 5.0, f"Bulk translation exceeded SLA: {elapsed_ms}ms"

    def test_complex_query_performance(self):
        """Test performance with complex queries"""
        complex_sql = """
        SELECT TOP 50 u.id, u.name, p.title
        FROM users u
        INNER JOIN posts p ON u.id = p.user_id
        WHERE u.status = 'active'
          AND p.published_date > '2023-01-01'
          AND u.id IN (SELECT TOP 10 user_id FROM premium_users)
        ORDER BY p.published_date DESC
        """

        import time
        start_time = time.perf_counter()

        translated_sql, mappings = get_construct_registry().translate_constructs(complex_sql)

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Should complete under constitutional SLA even for complex queries
        assert elapsed_ms < 5.0, f"Complex query translation too slow: {elapsed_ms}ms"

        # Should preserve multiple TOP clauses (IRIS supports TOP natively)
        top_count_before = complex_sql.count('TOP')
        top_count_after = translated_sql.count('TOP')
        assert top_count_after == top_count_before  # Should preserve all TOP clauses

    def test_memory_usage(self):
        """Test registry memory usage is reasonable"""
        import sys
        registry = get_construct_registry()

        # Get approximate memory usage of construct mappings
        if hasattr(registry, '_construct_patterns'):
            registry_size = sys.getsizeof(registry._construct_patterns)
            # Should be reasonable (less than 256KB for construct mappings)
            assert registry_size < 256 * 1024, f"Registry too large: {registry_size} bytes"
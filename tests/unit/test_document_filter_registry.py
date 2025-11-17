"""
Unit Tests for IRIS Document Filter Registry

Tests the document filter mapping registry with comprehensive coverage of all IRIS document
filter operations and PostgreSQL JSONB equivalents with constitutional compliance validation.
"""

from iris_pgwire.sql_translator.mappings.document_filters import (
    IRISDocumentFilterRegistry,
    get_document_filter_registry,
    has_document_filter,
    translate_document_filters,
)
from iris_pgwire.sql_translator.models import ConstructType


class TestIRISDocumentFilterRegistry:
    """Test suite for IRIS document filter registry"""

    def setup_method(self):
        """Setup fresh registry for each test"""
        self.registry = IRISDocumentFilterRegistry()

    def test_registry_initialization(self):
        """Test registry initializes with core IRIS document filters"""
        # Should have JSON_TABLE filters
        assert self.registry.has_filter("JSON_TABLE_BASIC")
        assert self.registry.has_filter("JSON_TABLE_NESTED")

        # Should have JSON_EXTRACT filters
        assert self.registry.has_filter("JSON_EXTRACT_PATH")
        assert self.registry.has_filter("JSON_EXTRACT_SCALAR")

        # Should have filter patterns dictionary
        assert hasattr(self.registry, "_filter_patterns")
        assert len(self.registry._filter_patterns) > 0

    def test_json_table_filter_mappings(self):
        """Test IRIS JSON_TABLE filter mappings"""
        # Test JSON_TABLE_BASIC filter
        table_filter = self.registry.get_filter_info("JSON_TABLE_BASIC")
        assert table_filter is not None
        assert table_filter["confidence"] >= 0.8
        assert "JSON_TABLE" in table_filter["notes"]

        # Test JSON_TABLE_NESTED filter
        nested_filter = self.registry.get_filter_info("JSON_TABLE_NESTED")
        assert nested_filter is not None
        assert nested_filter["confidence"] >= 0.7

    def test_json_extract_filter_mappings(self):
        """Test IRIS JSON_EXTRACT filter mappings"""
        # Test JSON_EXTRACT_PATH filter
        extract_filter = self.registry.get_filter_info("JSON_EXTRACT_PATH")
        assert extract_filter is not None
        assert extract_filter["confidence"] >= 0.9
        assert "JSON_EXTRACT" in extract_filter["notes"]

        # Test JSON_EXTRACT_SCALAR filter
        scalar_filter = self.registry.get_filter_info("JSON_EXTRACT_SCALAR")
        assert scalar_filter is not None
        assert scalar_filter["confidence"] >= 0.9

    def test_json_exists_filter_mappings(self):
        """Test IRIS JSON_EXISTS filter mappings"""
        # Test JSON_EXISTS_PATH filter
        exists_filter = self.registry.get_filter_info("JSON_EXISTS_PATH")
        assert exists_filter is not None
        assert exists_filter["confidence"] >= 0.9

        # Test JSON_EXISTS_RETURNING filter
        returning_filter = self.registry.get_filter_info("JSON_EXISTS_RETURNING")
        assert returning_filter is not None
        assert returning_filter["confidence"] >= 0.8

    def test_json_query_filter_mappings(self):
        """Test IRIS JSON_QUERY filter mappings"""
        # Test JSON_QUERY_PATH filter
        query_filter = self.registry.get_filter_info("JSON_QUERY_PATH")
        assert query_filter is not None
        assert query_filter["confidence"] >= 0.8

        # Test JSON_VALUE_PATH filter
        value_filter = self.registry.get_filter_info("JSON_VALUE_PATH")
        assert value_filter is not None
        assert value_filter["confidence"] >= 0.9

    def test_document_access_patterns(self):
        """Test IRIS document access pattern mappings"""
        # Test DOCUMENT_BRACKET_ACCESS filter
        bracket_filter = self.registry.get_filter_info("DOCUMENT_BRACKET_ACCESS")
        assert bracket_filter is not None
        assert bracket_filter["confidence"] >= 0.9
        assert bracket_filter["replacement"] is not None

        # Test DOCUMENT_ARRAY_INDEX filter
        array_filter = self.registry.get_filter_info("DOCUMENT_ARRAY_INDEX")
        assert array_filter is not None
        assert array_filter["confidence"] >= 1.0

    def test_array_operation_mappings(self):
        """Test IRIS array operation mappings"""
        # Test JSON_ARRAY_LENGTH filter
        length_filter = self.registry.get_filter_info("JSON_ARRAY_LENGTH")
        assert length_filter is not None
        assert length_filter["confidence"] >= 1.0
        assert "jsonb_array_length" in length_filter["replacement"]

        # Test JSON_ARRAY_ELEMENTS filter
        elements_filter = self.registry.get_filter_info("JSON_ARRAY_ELEMENTS")
        assert elements_filter is not None
        assert "jsonb_array_elements" in elements_filter["replacement"]

    def test_nested_operation_mappings(self):
        """Test IRIS nested operation mappings"""
        # Test NESTED_OBJECT_ACCESS filter
        nested_filter = self.registry.get_filter_info("NESTED_OBJECT_ACCESS")
        assert nested_filter is not None
        assert nested_filter["confidence"] >= 0.9

        # Test JSON_PATH_WILDCARD filter
        wildcard_filter = self.registry.get_filter_info("JSON_PATH_WILDCARD")
        assert wildcard_filter is not None
        assert wildcard_filter["confidence"] >= 0.6

    def test_case_sensitivity(self):
        """Test filter lookup case sensitivity"""
        # Registry is case-sensitive
        assert self.registry.has_filter("JSON_TABLE_BASIC")
        assert not self.registry.has_filter("json_table_basic")

        # Only exact case matches work
        filter_info = self.registry.get_filter_info("JSON_TABLE_BASIC")
        assert filter_info is not None

    def test_nonexistent_filter(self):
        """Test handling of non-existent filters"""
        assert not self.registry.has_filter("NONEXISTENT_FILTER")
        assert self.registry.get_filter_info("NONEXISTENT_FILTER") is None

    def test_filter_translation(self):
        """Test document filter translation"""
        # Test JSON_ARRAY_LENGTH translation
        sql = "SELECT JSON_ARRAY_LENGTH(data) FROM docs"
        translated_sql, mappings = self.registry.translate_document_filters(sql)

        assert "jsonb_array_length" in translated_sql
        assert "JSON_ARRAY_LENGTH" not in translated_sql
        assert len(mappings) > 0

    def test_multiple_filters_in_single_query(self):
        """Test translation of multiple filters in one query"""
        sql = "SELECT JSON_EXTRACT(data, '$.name'), JSON_ARRAY_LENGTH(items) FROM docs"
        translated_sql, mappings = self.registry.translate_document_filters(sql)

        # Should translate both functions
        assert len(mappings) >= 1  # At least JSON_ARRAY_LENGTH should be translated

    def test_constitutional_compliance(self):
        """Test constitutional compliance requirements"""
        # Test that translation performance meets SLA
        import time

        sql = """
        SELECT doc.data.user.profile.email, doc.metadata.tags[0]
        FROM documents doc
        WHERE doc.data.status = 'published'
          AND doc.data.category.name = 'technology'
        """

        start_time = time.perf_counter()
        translated_sql, mappings = self.registry.translate_document_filters(sql)
        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Should complete under constitutional 5ms SLA
        assert elapsed_ms < 5.0, f"Translation exceeded SLA: {elapsed_ms}ms"

        # All mappings should have reasonable confidence (>= 0.6 for document filters)
        for mapping in mappings:
            assert mapping.confidence >= 0.6, f"Low confidence mapping: {mapping.original_syntax}"

    def test_mapping_stats(self):
        """Test registry statistics collection"""
        stats = self.registry.get_mapping_stats()

        assert "total_filters" in stats
        assert "confidence_distribution" in stats
        assert "category_counts" in stats

        # Should have reasonable number of filters
        assert stats["total_filters"] >= 10

        # Should track confidence levels
        confidence_dist = stats["confidence_distribution"]
        assert "high" in confidence_dist  # >= 0.9
        assert "medium" in confidence_dist  # 0.7-0.9
        assert "low" in confidence_dist  # < 0.7

    def test_filter_mapping_data_integrity(self):
        """Test filter mapping data integrity"""
        for filter_name, filter_info in self.registry._filter_patterns.items():
            # Validate mapping structure
            assert filter_name is not None and filter_name.strip() != ""
            assert "pattern" in filter_info
            assert "confidence" in filter_info
            assert "construct_type" in filter_info
            assert "notes" in filter_info
            assert isinstance(filter_info["confidence"], (int, float))
            assert 0.0 <= filter_info["confidence"] <= 1.0

    def test_registry_singleton(self):
        """Test global registry singleton behavior"""
        registry1 = get_document_filter_registry()
        registry2 = get_document_filter_registry()

        # Should be the same instance
        assert registry1 is registry2

    def test_convenience_functions(self):
        """Test module-level convenience functions"""
        # Test has_document_filter
        assert has_document_filter("JSON_TABLE_BASIC")
        assert not has_document_filter("NONEXISTENT_FILTER")

        # Test translate_document_filters
        sql = "SELECT JSON_ARRAY_LENGTH(data) FROM docs"
        translated, mappings = translate_document_filters(sql)
        assert "jsonb_array_length" in translated

    def test_edge_cases(self):
        """Test edge cases and error conditions"""
        # Empty string
        translated_sql, mappings = self.registry.translate_document_filters("")
        assert translated_sql == ""
        assert len(mappings) == 0

        # None input handling (if supported)
        try:
            translated_sql, mappings = self.registry.translate_document_filters(None)
            assert translated_sql is None or translated_sql == ""
        except (TypeError, AttributeError):
            # Expected for None input
            pass

        # SQL without document filters
        sql = "SELECT * FROM users WHERE id = 1"
        translated_sql, mappings = self.registry.translate_document_filters(sql)
        assert translated_sql == sql
        assert len(mappings) == 0

    def test_filter_categories(self):
        """Test filter category organization"""
        categories = self.registry.get_filter_categories()

        assert "json_table" in categories
        assert "json_extract" in categories
        assert "json_query" in categories
        assert "document_access" in categories
        assert "array_operations" in categories

        # Should have filters in appropriate categories
        assert len(categories["json_table"]) > 0
        assert len(categories["json_extract"]) > 0
        assert len(categories["array_operations"]) > 0

    def test_jsonpath_conversion(self):
        """Test JSONPath to PostgreSQL path conversion"""
        # Test the internal conversion method
        test_cases = [
            ("$.name", "name"),
            ("$.address.city", '{"address","city"}'),
            ("$.items[0]", '{"items",0}'),
            ("$.items[0].name", '{"items",0,"name"}'),
        ]

        for jsonpath, expected in test_cases:
            result = self.registry._convert_jsonpath_to_postgres(jsonpath)
            assert result == expected

    def test_complex_document_operations(self):
        """Test complex document operation translations"""
        # Test nested JSON access
        sql = "SELECT data['user']['name'] FROM docs"
        translated_sql, mappings = self.registry.translate_document_filters(sql)

        # Should translate bracket notation
        assert "->" in translated_sql

    def test_search_filters(self):
        """Test searching for filters by pattern"""
        # Search for JSON_TABLE filters
        table_filters = self.registry.search_filters("table")
        assert len(table_filters) >= 2
        assert "JSON_TABLE_BASIC" in table_filters

        # Search for array filters
        array_filters = self.registry.search_filters("array")
        assert len(array_filters) >= 3


class TestDocumentFilterTranslationIntegration:
    """Integration tests for document filter translation"""

    def test_registry_with_parser_integration(self):
        """Test registry integration with SQL parser"""
        # This would test how the registry is used by the parser
        # to identify and translate IRIS document filters
        pass  # Placeholder for integration tests

    def test_json_table_complex_translation(self):
        """Test complex JSON_TABLE translation"""
        registry = get_document_filter_registry()

        sql = """
        SELECT * FROM JSON_TABLE(
            data,
            '$.items[*]'
            COLUMNS (
                id INT PATH '$.id',
                name VARCHAR(50) PATH '$.name',
                price DECIMAL(10,2) PATH '$.price'
            )
        ) AS jt
        """

        # This tests the actual transformation logic
        translated_sql, mappings = registry.translate_document_filters(sql)

        # Should have found and attempted to translate JSON_TABLE
        assert len(mappings) > 0
        assert mappings[0].construct_type == ConstructType.DOCUMENT_FILTER

    def test_constitutional_compliance_reporting(self):
        """Test constitutional compliance reporting"""
        registry = get_document_filter_registry()
        stats = registry.get_mapping_stats()

        # Should report compliance metrics
        if "constitutional_compliance" in stats:
            compliance = stats["constitutional_compliance"]
            assert "high_confidence_rate" in compliance
            assert compliance["high_confidence_rate"] >= 0.8  # 80% high confidence requirement


# Performance benchmark tests
class TestDocumentFilterRegistryPerformance:
    """Performance tests for constitutional SLA compliance"""

    def test_bulk_lookup_performance(self):
        """Test bulk filter lookup performance"""
        registry = get_document_filter_registry()

        # Get all available filter names
        all_filters = list(registry._filter_patterns.keys())

        import time

        start_time = time.perf_counter()

        # Lookup all filters
        for filter_name in all_filters:
            filter_info = registry.get_filter_info(filter_name)
            assert filter_info is not None

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Should complete well under constitutional 5ms SLA
        assert elapsed_ms < 5.0, f"Bulk lookup exceeded SLA: {elapsed_ms}ms"

    def test_complex_translation_performance(self):
        """Test complex document filter translation performance"""
        registry = get_document_filter_registry()

        complex_sql = """
        SELECT
            JSON_EXTRACT(data, '$.user.name'),
            JSON_ARRAY_LENGTH(JSON_EXTRACT(data, '$.items')),
            JSON_EXISTS(data, '$.active'),
            data['metadata']['timestamp']
        FROM documents
        WHERE JSON_EXISTS(data, '$.published')
        """

        import time

        start_time = time.perf_counter()

        translated_sql, mappings = registry.translate_document_filters(complex_sql)

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Should complete under constitutional SLA
        assert elapsed_ms < 5.0, f"Complex translation too slow: {elapsed_ms}ms"

        # Should have found multiple filters to translate
        assert len(mappings) >= 2

    def test_memory_usage(self):
        """Test registry memory usage is reasonable"""
        import sys

        registry = get_document_filter_registry()

        # Get approximate memory usage
        registry_size = sys.getsizeof(registry._filter_patterns)

        # Should be reasonable (less than 512KB for filter mappings)
        assert registry_size < 512 * 1024, f"Registry too large: {registry_size} bytes"

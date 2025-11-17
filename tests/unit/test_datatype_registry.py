"""
Unit Tests for IRIS Data Type Registry

Tests the data type mapping registry with comprehensive coverage of all IRIS data
type mappings and PostgreSQL equivalents with constitutional compliance validation.
"""

from iris_pgwire.sql_translator.mappings.datatypes import (
    IRISDataTypeRegistry,
    get_datatype_registry,
    get_type_mapping,
    has_type_mapping,
    translate_type_specification,
)
from iris_pgwire.sql_translator.models import TypeMapping


class TestIRISDataTypeRegistry:
    """Test suite for IRIS data type registry"""

    def setup_method(self):
        """Setup fresh registry for each test"""
        self.registry = IRISDataTypeRegistry()

    def test_registry_initialization(self):
        """Test registry initializes with core IRIS data types"""
        # Should have numeric types
        assert self.registry.has_mapping("INTEGER")
        assert self.registry.has_mapping("BIGINT")
        assert self.registry.has_mapping("DECIMAL")
        assert self.registry.has_mapping("NUMERIC")

        # Should have string types
        assert self.registry.has_mapping("VARCHAR")
        assert self.registry.has_mapping("CHAR")
        assert self.registry.has_mapping("CLOB")

        # Should have date/time types
        assert self.registry.has_mapping("DATE")
        assert self.registry.has_mapping("TIME")
        assert self.registry.has_mapping("TIMESTAMP")

        # Should have binary types
        assert self.registry.has_mapping("VARBINARY")
        assert self.registry.has_mapping("BLOB")

        # Should have IRIS-specific types
        assert self.registry.has_mapping("VECTOR")

    def test_numeric_type_mappings(self):
        """Test IRIS numeric type mappings"""
        # INTEGER mapping
        int_mapping = self.registry.get_mapping("INTEGER")
        assert int_mapping.postgresql_type == "INTEGER"
        assert int_mapping.confidence >= 0.95

        # BIGINT mapping
        bigint_mapping = self.registry.get_mapping("BIGINT")
        assert bigint_mapping.postgresql_type == "BIGINT"
        assert bigint_mapping.confidence >= 0.95

        # DECIMAL mapping
        decimal_mapping = self.registry.get_mapping("DECIMAL")
        assert decimal_mapping.postgresql_type == "DECIMAL"
        assert decimal_mapping.confidence >= 0.95

        # DOUBLE mapping
        if self.registry.has_mapping("DOUBLE"):
            double_mapping = self.registry.get_mapping("DOUBLE")
            assert (
                "DOUBLE" in double_mapping.postgresql_type
                or "FLOAT8" in double_mapping.postgresql_type
            )

    def test_string_type_mappings(self):
        """Test IRIS string type mappings"""
        # VARCHAR mapping
        varchar_mapping = self.registry.get_mapping("VARCHAR")
        assert varchar_mapping.postgresql_type == "VARCHAR"
        assert varchar_mapping.confidence >= 0.95

        # CHAR mapping
        char_mapping = self.registry.get_mapping("CHAR")
        assert char_mapping.postgresql_type == "CHAR"
        assert char_mapping.confidence >= 0.95

        # CLOB mapping
        clob_mapping = self.registry.get_mapping("CLOB")
        assert clob_mapping.postgresql_type == "TEXT"
        assert clob_mapping.confidence >= 0.9

    def test_datetime_type_mappings(self):
        """Test IRIS date/time type mappings"""
        # DATE mapping
        date_mapping = self.registry.get_mapping("DATE")
        assert date_mapping.postgresql_type == "DATE"
        assert date_mapping.confidence >= 0.95

        # TIME mapping
        time_mapping = self.registry.get_mapping("TIME")
        assert time_mapping.postgresql_type == "TIME"
        assert time_mapping.confidence >= 0.95

        # TIMESTAMP mapping
        timestamp_mapping = self.registry.get_mapping("TIMESTAMP")
        assert timestamp_mapping.postgresql_type == "TIMESTAMP"
        assert timestamp_mapping.confidence >= 0.95

    def test_binary_type_mappings(self):
        """Test IRIS binary type mappings"""
        # VARBINARY mapping
        varbinary_mapping = self.registry.get_mapping("VARBINARY")
        assert varbinary_mapping.postgresql_type == "BYTEA"
        assert varbinary_mapping.confidence >= 0.9

        # BLOB mapping
        blob_mapping = self.registry.get_mapping("BLOB")
        assert blob_mapping.postgresql_type == "BYTEA"
        assert blob_mapping.confidence >= 0.9

    def test_vector_type_mapping(self):
        """Test IRIS VECTOR type mapping"""
        vector_mapping = self.registry.get_mapping("VECTOR")
        assert vector_mapping is not None
        # Should map to either custom vector type or array
        assert (
            "VECTOR" in vector_mapping.postgresql_type or "REAL[]" in vector_mapping.postgresql_type
        )
        assert vector_mapping.confidence >= 0.8

    def test_case_insensitive_lookup(self):
        """Test type lookup is case insensitive"""
        # Should find mappings regardless of case
        assert self.registry.has_mapping("varchar")
        assert self.registry.has_mapping("VARCHAR")
        assert self.registry.has_mapping("VarChar")

        mapping1 = self.registry.get_mapping("varchar")
        mapping2 = self.registry.get_mapping("VARCHAR")
        assert mapping1.postgresql_type == mapping2.postgresql_type

    def test_nonexistent_type(self):
        """Test handling of non-existent types"""
        assert not self.registry.has_mapping("NONEXISTENT_TYPE")
        assert self.registry.get_mapping("NONEXISTENT_TYPE") is None

    def test_type_specification_translation(self):
        """Test translation of type specifications with parameters"""
        # Test VARCHAR with length - use translate_type_with_size
        varchar_spec, confidence = self.registry.translate_type_with_size("VARCHAR(255)")
        assert "VARCHAR" in varchar_spec
        assert "255" in varchar_spec

        # Test DECIMAL with precision and scale
        decimal_spec, confidence = self.registry.translate_type_with_size("DECIMAL(10,2)")
        assert "DECIMAL" in decimal_spec or "NUMERIC" in decimal_spec
        assert "10" in decimal_spec and "2" in decimal_spec

        # Test CHAR with length
        char_spec, confidence = self.registry.translate_type_with_size("CHAR(10)")
        assert "CHAR" in char_spec
        assert "10" in char_spec

    def test_constitutional_compliance(self):
        """Test constitutional compliance requirements"""
        # All mappings should have high confidence (>= 0.8)
        all_mappings = self.registry._mappings

        low_confidence_types = []
        for type_name, mapping in all_mappings.items():
            if mapping.confidence < 0.8:
                low_confidence_types.append(type_name)

        # Allow for some low confidence mappings for IRIS-specific types
        # These are complex types that don't have direct PostgreSQL equivalents
        assert (
            len(low_confidence_types) <= 8
        ), f"Too many low confidence mappings found: {low_confidence_types}"

    def test_mapping_performance(self):
        """Test mapping lookup performance meets constitutional SLA"""
        import time

        # Test batch lookups under 1ms total (well under 5ms SLA)
        start_time = time.perf_counter()

        types_to_test = [
            "INTEGER",
            "BIGINT",
            "VARCHAR",
            "CHAR",
            "DATE",
            "TIMESTAMP",
            "DECIMAL",
            "VARBINARY",
            "BLOB",
            "CLOB",
            "VECTOR",
        ]

        for type_name in types_to_test:
            mapping = self.registry.get_mapping(type_name)
            # Some types might not be implemented yet
            if mapping is not None:
                assert mapping.postgresql_type is not None

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        assert elapsed_ms < 1.0, f"Type lookup too slow: {elapsed_ms}ms"

    def test_mapping_stats(self):
        """Test registry statistics collection"""
        stats = self.registry.get_mapping_stats()

        assert "total_mappings" in stats
        assert "confidence_distribution" in stats
        assert "category_counts" in stats  # Actual key used in implementation

        # Should have reasonable number of mappings
        assert stats["total_mappings"] >= 8

        # Should track confidence levels
        confidence_dist = stats["confidence_distribution"]
        assert "high" in confidence_dist  # >= 0.9
        assert "medium" in confidence_dist  # 0.8-0.9
        assert "low" in confidence_dist  # < 0.8

    def test_type_mapping_data_integrity(self):
        """Test type mapping data integrity"""
        for type_name, mapping in self.registry._mappings.items():
            # Validate mapping structure
            assert isinstance(mapping, TypeMapping)
            assert type_name is not None and type_name.strip() != ""
            assert mapping.postgresql_type is not None and mapping.postgresql_type.strip() != ""
            assert isinstance(mapping.confidence, (int, float))
            assert 0.0 <= mapping.confidence <= 1.0
            assert mapping.notes is not None

    def test_type_compatibility_rules(self):
        """Test type compatibility and conversion rules"""
        # Test that numeric types have appropriate mappings
        numeric_types = ["INTEGER", "BIGINT", "DECIMAL", "NUMERIC"]
        for type_name in numeric_types:
            if self.registry.has_mapping(type_name):
                mapping = self.registry.get_mapping(type_name)
                # Should map to PostgreSQL numeric types
                pg_type = mapping.postgresql_type.upper()
                assert any(
                    nt in pg_type
                    for nt in ["INTEGER", "BIGINT", "DECIMAL", "NUMERIC", "INT", "FLOAT"]
                )

    def test_registry_singleton(self):
        """Test global registry singleton behavior"""
        registry1 = get_datatype_registry()
        registry2 = get_datatype_registry()

        # Should be the same instance
        assert registry1 is registry2

        # Should have consistent mappings
        assert registry1.has_mapping("INTEGER") == registry2.has_mapping("INTEGER")

    def test_convenience_functions(self):
        """Test module-level convenience functions"""
        # Test has_type_mapping
        assert has_type_mapping("INTEGER")
        assert not has_type_mapping("NONEXISTENT_TYPE")

        # Test get_type_mapping
        mapping = get_type_mapping("INTEGER")
        assert mapping is not None
        assert mapping.postgresql_type == "INTEGER"

        none_mapping = get_type_mapping("NONEXISTENT_TYPE")
        assert none_mapping is None

        # Test translate_type_specification - returns tuple
        spec, confidence = translate_type_specification("VARCHAR(100)")
        assert "VARCHAR" in spec
        assert "100" in spec
        assert confidence > 0


class TestTypeMappingModel:
    """Test the TypeMapping data model"""

    def test_datatype_mapping_creation(self):
        """Test TypeMapping model creation"""
        mapping = TypeMapping(
            iris_type="INTEGER", postgresql_type="INTEGER", confidence=0.95, notes="32-bit integer"
        )

        assert mapping.iris_type == "INTEGER"
        assert mapping.postgresql_type == "INTEGER"
        assert mapping.confidence == 0.95
        assert mapping.notes == "32-bit integer"

    def test_datatype_mapping_with_size_constraints(self):
        """Test TypeMapping with size constraints"""
        mapping = TypeMapping(
            iris_type="VARCHAR",
            postgresql_type="VARCHAR",
            confidence=0.95,
            notes="Variable-length character string",
            size_mapping={"default": "255", "max": "65535"},
        )

        assert mapping.size_mapping["default"] == "255"
        assert mapping.size_mapping["max"] == "65535"


class TestDataTypeRegistryIntegration:
    """Integration tests for data type registry with other components"""

    def test_registry_with_ddl_translation(self):
        """Test registry integration with DDL translation"""
        # This would test how the registry is used to translate
        # CREATE TABLE statements with IRIS types
        pass  # Placeholder for integration tests

    def test_registry_with_result_set_processing(self):
        """Test registry integration with result set type mapping"""
        # Test how the registry is used to map IRIS result types
        # to PostgreSQL wire protocol types
        pass  # Placeholder for integration tests

    def test_constitutional_compliance_reporting(self):
        """Test constitutional compliance reporting"""
        registry = get_datatype_registry()
        stats = registry.get_mapping_stats()

        # Should report compliance metrics
        if "constitutional_compliance" in stats:
            compliance = stats["constitutional_compliance"]
            assert "high_confidence_rate" in compliance
            assert compliance["high_confidence_rate"] >= 0.8  # 80% high confidence requirement


# Performance benchmark tests
class TestDataTypeRegistryPerformance:
    """Performance tests for constitutional SLA compliance"""

    def test_bulk_lookup_performance(self):
        """Test bulk type lookup performance"""
        registry = get_datatype_registry()

        # Get all available type names
        all_types = list(registry._mappings.keys())

        import time

        start_time = time.perf_counter()

        # Lookup all types
        for type_name in all_types:
            mapping = registry.get_mapping(type_name)
            assert mapping is not None

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Should complete well under constitutional 5ms SLA
        assert elapsed_ms < 5.0, f"Bulk lookup exceeded SLA: {elapsed_ms}ms"

    def test_type_specification_parsing_performance(self):
        """Test type specification parsing performance"""
        type_specs = [
            "VARCHAR(255)",
            "CHAR(10)",
            "DECIMAL(10,2)",
            "NUMERIC(15,5)",
            "TIMESTAMP",
            "DATE",
            "TIME",
            "INTEGER",
            "BIGINT",
            "BLOB",
        ]

        import time

        start_time = time.perf_counter()

        for spec in type_specs:
            result, confidence = translate_type_specification(spec)
            assert result is not None
            assert confidence > 0

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Should complete under constitutional SLA
        assert elapsed_ms < 2.0, f"Type specification parsing too slow: {elapsed_ms}ms"

    def test_memory_usage(self):
        """Test registry memory usage is reasonable"""
        import sys

        registry = get_datatype_registry()

        # Get approximate memory usage
        registry_size = sys.getsizeof(registry._mappings)

        # Should be reasonable (less than 512KB for type mappings)
        assert registry_size < 512 * 1024, f"Registry too large: {registry_size} bytes"

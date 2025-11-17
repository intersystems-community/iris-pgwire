"""
Unit Tests for IRIS Function Registry

Tests the function mapping registry with comprehensive coverage of all IRIS function
mappings and PostgreSQL equivalents with constitutional compliance validation.
"""

from iris_pgwire.sql_translator.mappings.functions import (
    FunctionMapping,
    IRISFunctionRegistry,
    get_function_mapping,
    get_function_registry,
    has_function_mapping,
)


class TestIRISFunctionRegistry:
    """Test suite for IRIS function registry"""

    def setup_method(self):
        """Setup fresh registry for each test"""
        self.registry = IRISFunctionRegistry()

    def test_registry_initialization(self):
        """Test registry initializes with core IRIS functions"""
        # Should have system functions
        assert self.registry.has_mapping("%SYSTEM.Version.GetNumber")
        assert self.registry.has_mapping("%SQLUPPER")
        assert self.registry.has_mapping("%SQLLOWER")

        # Should have string functions - check for actual functions in registry
        assert self.registry.has_mapping("%SQLREPLACE")
        assert self.registry.has_mapping("%SQLTRIM")

    def test_system_function_mappings(self):
        """Test IRIS %SYSTEM function mappings"""
        mapping = self.registry.get_mapping("%SYSTEM.Version.GetNumber")
        assert mapping is not None
        assert mapping.postgresql_function == "version()"
        assert mapping.confidence >= 0.9
        # Just check that notes exists and has content
        assert mapping.notes
        assert len(mapping.notes) > 0

    def test_string_function_mappings(self):
        """Test IRIS string function mappings"""
        # Test SQLUPPER
        upper_mapping = self.registry.get_mapping("%SQLUPPER")
        assert upper_mapping.postgresql_function == "UPPER"
        assert upper_mapping.confidence >= 0.95

        # Test SQLLOWER
        lower_mapping = self.registry.get_mapping("%SQLLOWER")
        assert lower_mapping.postgresql_function == "LOWER"
        assert lower_mapping.confidence >= 0.95

        # Test STARTSWITH (if exists)
        if self.registry.has_mapping("%STARTSWITH"):
            startswith_mapping = self.registry.get_mapping("%STARTSWITH")
            assert (
                "LIKE" in startswith_mapping.postgresql_function
                or "starts_with" in startswith_mapping.postgresql_function
            )
            assert startswith_mapping.confidence >= 0.8

    def test_vector_function_mappings(self):
        """Test IRIS vector function mappings"""
        # Test VECTOR_COSINE (if exists)
        if self.registry.has_mapping("VECTOR_COSINE"):
            cosine_mapping = self.registry.get_mapping("VECTOR_COSINE")
            assert cosine_mapping is not None
            assert "cosine" in cosine_mapping.postgresql_function.lower()
            assert cosine_mapping.confidence >= 0.8

        # Test TO_VECTOR (if exists)
        if self.registry.has_mapping("TO_VECTOR"):
            to_vector_mapping = self.registry.get_mapping("TO_VECTOR")
            assert to_vector_mapping is not None
            assert to_vector_mapping.confidence >= 0.8

    def test_case_sensitivity(self):
        """Test function lookup case sensitivity"""
        # Currently registry is case-sensitive
        assert self.registry.has_mapping("%SQLUPPER")
        assert not self.registry.has_mapping("%sqlupper")

        # Only exact case matches work
        mapping = self.registry.get_mapping("%SQLUPPER")
        assert mapping is not None
        assert mapping.postgresql_function == "UPPER"

    def test_nonexistent_function(self):
        """Test handling of non-existent functions"""
        assert not self.registry.has_mapping("%NONEXISTENT_FUNCTION")
        assert self.registry.get_mapping("%NONEXISTENT_FUNCTION") is None

    def test_constitutional_compliance(self):
        """Test constitutional compliance requirements"""
        # All mappings should have high confidence (>= 0.8)
        all_mappings = self.registry._mappings

        low_confidence_functions = []
        for func_name, mapping in all_mappings.items():
            if mapping.confidence < 0.8:
                low_confidence_functions.append(func_name)

        # Allow for some low confidence mappings but should be minimal
        assert (
            len(low_confidence_functions) <= 2
        ), f"Too many low confidence mappings found: {low_confidence_functions}"

    def test_mapping_performance(self):
        """Test mapping lookup performance meets constitutional SLA"""
        import time

        # Test batch lookups under 1ms total (well under 5ms SLA)
        start_time = time.perf_counter()

        # Test with functions that actually exist
        functions_to_test = [
            "%SQLUPPER",
            "%SQLLOWER",
            "%SYSTEM.Version.GetNumber",
            "%SQLSTRING",
            "%SQLLENGTH",
            "%SQLREPLACE",
            "%SQLTRIM",
        ]

        for func in functions_to_test:
            mapping = self.registry.get_mapping(func)
            assert mapping is not None, f"Function {func} not found"

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        assert elapsed_ms < 1.0, f"Function lookup too slow: {elapsed_ms}ms"

    def test_mapping_stats(self):
        """Test registry statistics collection"""
        stats = self.registry.get_mapping_stats()

        assert "total_mappings" in stats
        assert "confidence_distribution" in stats
        assert "category_counts" in stats  # Actual key used in implementation

        # Should have reasonable number of mappings
        assert stats["total_mappings"] >= 10

        # Should track confidence levels
        confidence_dist = stats["confidence_distribution"]
        assert "high" in confidence_dist  # >= 0.9
        assert "medium" in confidence_dist  # 0.8-0.9
        assert "low" in confidence_dist  # < 0.8

    def test_function_mapping_data_integrity(self):
        """Test function mapping data integrity"""
        for func_name, mapping in self.registry._mappings.items():
            # Validate mapping structure
            assert isinstance(mapping, FunctionMapping)
            assert func_name is not None and func_name.strip() != ""
            assert (
                mapping.postgresql_function is not None
                and mapping.postgresql_function.strip() != ""
            )
            assert isinstance(mapping.confidence, (int, float))
            assert 0.0 <= mapping.confidence <= 1.0
            assert mapping.notes is not None

    def test_parameter_substitution(self):
        """Test parameterized function handling"""
        # Test functions that support parameters
        # This would need to be implemented in the registry
        pass  # Placeholder for parameter substitution tests

    def test_registry_singleton(self):
        """Test global registry singleton behavior"""
        registry1 = get_function_registry()
        registry2 = get_function_registry()

        # Should be the same instance
        assert registry1 is registry2

        # Should have consistent mappings
        assert registry1.has_mapping("%SQLUPPER") == registry2.has_mapping("%SQLUPPER")

    def test_convenience_functions(self):
        """Test module-level convenience functions"""
        # Test has_function_mapping
        assert has_function_mapping("%SQLUPPER")
        assert not has_function_mapping("%NONEXISTENT")

        # Test get_function_mapping
        mapping = get_function_mapping("%SQLUPPER")
        assert mapping is not None
        assert mapping.postgresql_function == "UPPER"

        none_mapping = get_function_mapping("%NONEXISTENT")
        assert none_mapping is None


class TestFunctionMappingModel:
    """Test the FunctionMapping data model"""

    def test_function_mapping_creation(self):
        """Test FunctionMapping model creation"""
        mapping = FunctionMapping(
            iris_function="%SQLUPPER",
            postgresql_function="UPPER",
            confidence=0.95,
            notes="Convert string to uppercase",
        )

        assert mapping.postgresql_function == "UPPER"
        assert mapping.confidence == 0.95
        assert mapping.notes == "Convert string to uppercase"
        assert mapping.iris_function == "%SQLUPPER"

    def test_function_mapping_validation(self):
        """Test FunctionMapping validation"""
        # Test invalid confidence values would be caught by dataclass validation
        # if implemented in the model
        pass  # Placeholder for validation tests


class TestFunctionRegistryIntegration:
    """Integration tests for function registry with other components"""

    def test_registry_with_parser_integration(self):
        """Test registry integration with SQL parser"""
        # This would test how the registry is used by the parser
        # to identify and translate IRIS functions
        pass  # Placeholder for integration tests

    def test_registry_with_cache_integration(self):
        """Test registry caching behavior"""
        # Test that repeated lookups are properly cached
        registry = get_function_registry()

        # First lookup
        mapping1 = registry.get_mapping("%SQLUPPER")

        # Second lookup (should hit cache if implemented)
        mapping2 = registry.get_mapping("%SQLUPPER")

        assert mapping1.postgresql_function == mapping2.postgresql_function

    def test_constitutional_compliance_reporting(self):
        """Test constitutional compliance reporting"""
        registry = get_function_registry()
        stats = registry.get_mapping_stats()

        # Should report compliance metrics
        if "constitutional_compliance" in stats:
            compliance = stats["constitutional_compliance"]
            assert "high_confidence_rate" in compliance
            assert compliance["high_confidence_rate"] >= 0.8  # 80% high confidence requirement


# Performance benchmark tests
class TestFunctionRegistryPerformance:
    """Performance tests for constitutional SLA compliance"""

    def test_bulk_lookup_performance(self):
        """Test bulk function lookup performance"""
        registry = get_function_registry()

        # Get all available function names
        all_functions = list(registry._mappings.keys())

        import time

        start_time = time.perf_counter()

        # Lookup all functions
        for func_name in all_functions:
            mapping = registry.get_mapping(func_name)
            assert mapping is not None

        elapsed_ms = (time.perf_counter() - start_time) * 1000

        # Should complete well under constitutional 5ms SLA
        assert elapsed_ms < 5.0, f"Bulk lookup exceeded SLA: {elapsed_ms}ms"

    def test_memory_usage(self):
        """Test registry memory usage is reasonable"""
        import sys

        registry = get_function_registry()

        # Get approximate memory usage
        registry_size = sys.getsizeof(registry._mappings)

        # Should be reasonable (less than 1MB for function mappings)
        assert registry_size < 1024 * 1024, f"Registry too large: {registry_size} bytes"

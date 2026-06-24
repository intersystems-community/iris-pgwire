"""
Extended Unit Tests for IRISDataTypeRegistry

Targets branches missed at 83% baseline:
- translate_type_with_size: unknown type returns (iris_type_spec, 0.0) — line 535
- _parse_type_specification: no-match branch — line 556; string param ValueError branch — lines 569-570
- _apply_size_mapping: empty params — line 579; single param with 'precision' key — line 585-586;
  two params non-precision/scale fallback — lines 594-595; default multi-param fallback — line 594-595
- get_all_iris_types — line 599
- get_mappings_by_confidence — line 603
- get_type_categories — lines 644-655 (each category branch)
- search_types — lines 644-655
- validate_type_conversion — all branches lines 659-684
"""

from iris_pgwire.sql_translator.mappings.datatypes import (
    IRISDataTypeRegistry,
    get_type_mapping,
    has_type_mapping,
    translate_type_specification,
)


class TestTranslateTypeWithSizeEdgeCases:
    """Cover lines 535, 542-543 in translate_type_with_size."""

    def setup_method(self):
        self.registry = IRISDataTypeRegistry()

    def test_unknown_type_returns_original_and_zero(self):
        """When no mapping exists, returns (iris_type_spec, 0.0) — line 535."""
        result, confidence = self.registry.translate_type_with_size("UNKNOWNTYPE(10)")
        assert confidence == 0.0
        assert "UNKNOWNTYPE" in result

    def test_known_type_without_params_no_size_mapping(self):
        """Type with no parameters and no size_mapping skips _apply_size_mapping."""
        # INTEGER has no size_mapping — parameters list is empty
        result, confidence = self.registry.translate_type_with_size("INTEGER")
        assert result == "INTEGER"
        assert confidence == 1.0

    def test_type_with_params_and_no_size_mapping_skips_apply(self):
        """Type with parameters but no size_mapping on the TypeMapping skips apply."""
        # BOOLEAN has no size_mapping; passing a param should still return the pg type
        result, confidence = self.registry.translate_type_with_size("BOOLEAN")
        assert result == "BOOLEAN"


class TestParseTypeSpecification:
    """Cover lines 555-570 in _parse_type_specification."""

    def setup_method(self):
        self.registry = IRISDataTypeRegistry()

    def test_no_match_returns_original_as_base_type(self):
        """Non-matching spec (e.g., with brackets) returns base_type=original, params=[]."""
        # A spec that the regex can't parse cleanly
        result = self.registry._parse_type_specification("123INVALID")
        assert result["base_type"] == "123INVALID"
        assert result["parameters"] == []

    def test_type_with_no_params(self):
        """Type without parentheses returns empty parameters."""
        result = self.registry._parse_type_specification("INTEGER")
        assert result["base_type"] == "INTEGER"
        assert result["parameters"] == []

    def test_type_with_integer_param(self):
        """VARCHAR(50) parses param as int 50."""
        result = self.registry._parse_type_specification("VARCHAR(50)")
        assert result["base_type"] == "VARCHAR"
        assert result["parameters"] == [50]

    def test_type_with_non_integer_param_falls_back_to_string(self):
        """Param that isn't a valid int falls back to string (lines 569-570)."""
        result = self.registry._parse_type_specification("SOME_TYPE(MAX)")
        assert result["base_type"] == "SOME_TYPE"
        assert result["parameters"] == ["MAX"]

    def test_type_with_two_params(self):
        """DECIMAL(10,2) parses as [10, 2]."""
        result = self.registry._parse_type_specification("DECIMAL(10,2)")
        assert result["parameters"] == [10, 2]

    def test_dotted_type_name(self):
        """Dotted type name like Foo.Bar is valid."""
        result = self.registry._parse_type_specification("Foo.Bar")
        assert result["base_type"] == "Foo.Bar"
        assert result["parameters"] == []


class TestApplySizeMapping:
    """Cover all branches in _apply_size_mapping (lines 574-595)."""

    def setup_method(self):
        self.registry = IRISDataTypeRegistry()

    def test_empty_parameters_returns_pg_type_unchanged(self):
        """Empty params returns the type unchanged (line 579)."""
        result = self.registry._apply_size_mapping("VARCHAR", [], {"length": "length"})
        assert result == "VARCHAR"

    def test_single_param_with_length_key(self):
        """Single param with 'length' in size_mapping appends it (line 584)."""
        result = self.registry._apply_size_mapping("VARCHAR", [100], {"length": "length"})
        assert result == "VARCHAR(100)"

    def test_single_param_with_precision_key(self):
        """Single param with 'precision' (not 'length') in size_mapping (lines 585-586)."""
        result = self.registry._apply_size_mapping("TIME", [6], {"precision": "precision"})
        assert result == "TIME(6)"

    def test_two_params_with_precision_and_scale(self):
        """Two params with precision+scale keys (line 591)."""
        result = self.registry._apply_size_mapping(
            "DECIMAL", [10, 2], {"precision": "precision", "scale": "scale"}
        )
        assert result == "DECIMAL(10,2)"

    def test_two_params_without_matching_keys_uses_default(self):
        """Two params but size_mapping lacks precision+scale uses default fallback (lines 594-595)."""
        result = self.registry._apply_size_mapping("FOO", [5, 3], {"length": "length"})
        assert result == "FOO(5,3)"

    def test_three_params_uses_default_fallback(self):
        """Three params always uses default join fallback (lines 594-595)."""
        result = self.registry._apply_size_mapping(
            "BAR", [1, 2, 3], {"precision": "precision", "scale": "scale"}
        )
        assert result == "BAR(1,2,3)"


class TestGetAllIrisTypes:
    """Cover get_all_iris_types — line 599."""

    def setup_method(self):
        self.registry = IRISDataTypeRegistry()

    def test_returns_set_of_strings(self):
        """Returns a non-empty set."""
        types = self.registry.get_all_iris_types()
        assert isinstance(types, set)
        assert len(types) > 0

    def test_contains_known_types(self):
        """Known types are present in the set."""
        types = self.registry.get_all_iris_types()
        assert "INTEGER" in types
        assert "VARCHAR" in types
        assert "DATE" in types


class TestGetMappingsByConfidence:
    """Cover get_mappings_by_confidence — line 603."""

    def setup_method(self):
        self.registry = IRISDataTypeRegistry()

    def test_default_returns_all_mappings(self):
        """min_confidence=0.0 returns all mappings."""
        all_mappings = self.registry.get_mappings_by_confidence(0.0)
        assert len(all_mappings) == len(self.registry._mappings)

    def test_high_confidence_filters_correctly(self):
        """Only mappings with confidence >= 0.9 returned."""
        high = self.registry.get_mappings_by_confidence(0.9)
        for m in high:
            assert m.confidence >= 0.9

    def test_perfect_confidence_filters_to_subset(self):
        """Confidence=1.0 returns a subset."""
        perfect = self.registry.get_mappings_by_confidence(1.0)
        all_mappings = self.registry.get_mappings_by_confidence(0.0)
        assert len(perfect) <= len(all_mappings)

    def test_returns_list(self):
        """Return type is list."""
        result = self.registry.get_mappings_by_confidence(0.5)
        assert isinstance(result, list)


class TestGetTypeCategories:
    """Cover all category branches in get_type_categories (lines 607-640)."""

    def setup_method(self):
        self.registry = IRISDataTypeRegistry()

    def test_returns_all_category_keys(self):
        """Returns dict with all expected category keys."""
        cats = self.registry.get_type_categories()
        assert "numeric" in cats
        assert "string" in cats
        assert "datetime" in cats
        assert "binary" in cats
        assert "boolean" in cats
        assert "iris_specific" in cats
        assert "collection" in cats

    def test_numeric_category_contains_integer(self):
        """INTEGER falls into numeric category."""
        cats = self.registry.get_type_categories()
        assert "INTEGER" in cats["numeric"]

    def test_string_category_contains_varchar(self):
        """VARCHAR falls into string category."""
        cats = self.registry.get_type_categories()
        assert "VARCHAR" in cats["string"]

    def test_datetime_category_contains_date(self):
        """DATE falls into datetime category."""
        cats = self.registry.get_type_categories()
        assert "DATE" in cats["datetime"]

    def test_binary_category_contains_varbinary(self):
        """VARBINARY falls into binary category."""
        cats = self.registry.get_type_categories()
        assert "VARBINARY" in cats["binary"]

    def test_boolean_category_contains_boolean(self):
        """BOOLEAN falls into boolean category."""
        cats = self.registry.get_type_categories()
        assert "BOOLEAN" in cats["boolean"]

    def test_iris_specific_contains_percent_types(self):
        """% types fall into iris_specific category."""
        cats = self.registry.get_type_categories()
        assert len(cats["iris_specific"]) > 0
        for t in cats["iris_specific"]:
            assert t.startswith("%")

    def test_collection_category_contains_json(self):
        """JSON falls into collection category."""
        cats = self.registry.get_type_categories()
        assert "JSON" in cats["collection"]

    def test_vector_in_collection_category(self):
        """VECTOR falls into collection category."""
        cats = self.registry.get_type_categories()
        assert "VECTOR" in cats["collection"]


class TestSearchTypes:
    """Cover search_types (lines 642-655)."""

    def setup_method(self):
        self.registry = IRISDataTypeRegistry()

    def test_search_by_iris_type_name(self):
        """Pattern matched against iris type name."""
        results = self.registry.search_types("INT")
        type_names = [m.iris_type for m in results]
        assert any("INT" in n.upper() for n in type_names)

    def test_search_by_postgresql_type(self):
        """Pattern matched against postgresql_type field."""
        results = self.registry.search_types("BYTEA")
        pg_types = [m.postgresql_type for m in results]
        assert any("BYTEA" in t for t in pg_types)

    def test_search_by_notes(self):
        """Pattern matched against notes field."""
        results = self.registry.search_types("pgvector")
        # VECTOR has 'pgvector' in its notes
        assert len(results) >= 1

    def test_no_match_returns_empty_list(self):
        """No matching pattern returns empty list."""
        results = self.registry.search_types("XYZZY_NONEXISTENT_9999")
        assert results == []

    def test_returns_list_of_type_mappings(self):
        """Return type is list of TypeMapping objects."""
        from iris_pgwire.sql_translator.models import TypeMapping

        results = self.registry.search_types("INTEGER")
        assert all(isinstance(r, TypeMapping) for r in results)


class TestValidateTypeConversion:
    """Cover all branches of validate_type_conversion (lines 657-689)."""

    def setup_method(self):
        self.registry = IRISDataTypeRegistry()

    def test_unknown_iris_type_returns_invalid(self):
        """Unknown IRIS type returns valid=False (lines 660-665)."""
        result = self.registry.validate_type_conversion("NOTATYPE", "INTEGER")
        assert result["valid"] is False
        assert result["confidence"] == 0.0
        assert any("No mapping found" in w for w in result["warnings"])

    def test_valid_type_returns_valid_true(self):
        """Known type returns valid=True."""
        result = self.registry.validate_type_conversion("INTEGER", "INTEGER")
        assert result["valid"] is True
        assert "recommended_type" in result

    def test_low_confidence_adds_warning(self):
        """confidence < 0.8 triggers low-confidence warning (lines 671-672)."""
        # %Stream has confidence 0.6
        result = self.registry.validate_type_conversion("%Stream", "TEXT")
        assert any("Low confidence" in w for w in result["warnings"])

    def test_tinyint_to_smallint_adds_range_warning(self):
        """TINYINT -> SMALLINT triggers specific range warning (lines 675-676)."""
        result = self.registry.validate_type_conversion("TINYINT", "SMALLINT")
        assert any("TINYINT" in w for w in result["warnings"])

    def test_money_type_adds_precision_warning(self):
        """MONEY type triggers precision warning (lines 678-679)."""
        result = self.registry.validate_type_conversion("MONEY", "MONEY")
        assert any("MONEY" in w for w in result["warnings"])

    def test_percent_type_adds_class_warning(self):
        """% IRIS class type adds class-mapping warning (lines 681-682)."""
        result = self.registry.validate_type_conversion("%Boolean", "BOOLEAN")
        assert any("IRIS class type" in w for w in result["warnings"])

    def test_recommended_type_matches_mapping(self):
        """recommended_type matches the registered postgresql_type."""
        result = self.registry.validate_type_conversion("VARCHAR", "VARCHAR")
        assert result["recommended_type"] == "VARCHAR"

    def test_high_confidence_type_no_low_confidence_warning(self):
        """High-confidence type (1.0) does not trigger low-confidence warning."""
        result = self.registry.validate_type_conversion("INTEGER", "INTEGER")
        assert not any("Low confidence" in w for w in result["warnings"])

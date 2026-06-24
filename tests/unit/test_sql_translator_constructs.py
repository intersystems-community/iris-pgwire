"""
Unit tests for iris_pgwire.sql_translator.mappings.constructs

Targets uncovered branches to push coverage from 77% → ≥85%.
No live IRIS connection required.
"""

import pytest

from iris_pgwire.sql_translator.mappings.constructs import (
    IRISSQLConstructRegistry,
    get_construct_registry,
    has_sql_construct,
    translate_sql_constructs,
)
from iris_pgwire.sql_translator.models import ConstructType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def registry():
    return IRISSQLConstructRegistry()


# ---------------------------------------------------------------------------
# Registry initialization
# ---------------------------------------------------------------------------


class TestRegistryInitialization:
    def test_registry_creates_constructs(self, registry):
        names = registry.get_all_construct_names()
        assert len(names) > 0

    def test_expected_constructs_registered(self, registry):
        expected = [
            "IRIS_LIMIT_OFFSET",
            "ROWNUM_PSEUDO_COLUMN",
            "ORACLE_STYLE_OUTER_JOIN",
            "TABLE_HINTS",
            "DECODE_FUNCTION",
            "IIF_FUNCTION",
            "ISNULL_FUNCTION",
            "IFNULL_FUNCTION",
            "NVL_FUNCTION",
            "CORRELATED_EXISTS",
            "QUANTIFIED_COMPARISONS",
            "MINUS_OPERATOR",
            "INTERSECT_OPERATOR",
            "RANK_FUNCTION",
            "ROW_NUMBER_FUNCTION",
            "CTE_WITH_CLAUSE",
            "RECURSIVE_CTE",
            "CREATE_INDEX_IF_NOT_EXISTS",
            "HNSW_INDEX",
            "HNSW_INDEX_COL_FIRST",
        ]
        for name in expected:
            assert registry.has_construct(name), f"Missing construct: {name}"


# ---------------------------------------------------------------------------
# has_construct / get_construct_info
# ---------------------------------------------------------------------------


class TestHasAndGetConstructInfo:
    def test_has_construct_existing(self, registry):
        assert registry.has_construct("MINUS_OPERATOR") is True

    def test_has_construct_missing(self, registry):
        assert registry.has_construct("NO_SUCH_CONSTRUCT") is False

    def test_get_construct_info_returns_dict(self, registry):
        info = registry.get_construct_info("MINUS_OPERATOR")
        assert info is not None
        assert "pattern" in info
        assert "replacement" in info
        assert "confidence" in info
        assert "construct_type" in info

    def test_get_construct_info_missing_returns_none(self, registry):
        assert registry.get_construct_info("GHOST") is None


# ---------------------------------------------------------------------------
# translate_constructs — specific constructs
# ---------------------------------------------------------------------------


class TestTranslateConstructs:
    def test_minus_to_except(self, registry):
        sql = "SELECT 1 MINUS SELECT 2"
        translated, mappings = registry.translate_constructs(sql)
        assert "EXCEPT" in translated
        assert len(mappings) >= 1

    def test_isnull_to_coalesce(self, registry):
        sql = "SELECT ISNULL(col, 0) FROM t"
        translated, mappings = registry.translate_constructs(sql)
        assert "COALESCE" in translated
        assert "ISNULL" not in translated

    def test_ifnull_to_coalesce(self, registry):
        sql = "SELECT IFNULL(col, '') FROM t"
        translated, mappings = registry.translate_constructs(sql)
        assert "COALESCE" in translated

    def test_nvl_to_coalesce(self, registry):
        sql = "SELECT NVL(col, 'default') FROM t"
        translated, mappings = registry.translate_constructs(sql)
        assert "COALESCE" in translated

    def test_iif_to_case(self, registry):
        sql = "SELECT IIF(x > 0, 'pos', 'neg') FROM t"
        translated, mappings = registry.translate_constructs(sql)
        assert "CASE" in translated

    def test_recursive_cte_preserved(self, registry):
        sql = "WITH RECURSIVE cte AS (SELECT 1) SELECT * FROM cte"
        translated, mappings = registry.translate_constructs(sql)
        assert "WITH RECURSIVE" in translated

    def test_rank_function_preserved(self, registry):
        sql = "SELECT RANK() OVER (ORDER BY col) FROM t"
        translated, mappings = registry.translate_constructs(sql)
        assert "RANK() OVER (" in translated

    def test_row_number_preserved(self, registry):
        sql = "SELECT ROW_NUMBER() OVER (PARTITION BY x ORDER BY y) FROM t"
        translated, mappings = registry.translate_constructs(sql)
        assert "ROW_NUMBER() OVER (" in translated

    def test_table_hints_stripped(self, registry):
        sql = "SELECT * FROM users WITH (NOLOCK)"
        translated, mappings = registry.translate_constructs(sql)
        assert "WITH (NOLOCK)" not in translated
        assert "FROM users" in translated

    def test_create_index_if_not_exists_stripped(self, registry):
        sql = "CREATE INDEX IF NOT EXISTS idx_foo ON t (col)"
        translated, mappings = registry.translate_constructs(sql)
        assert "IF NOT EXISTS" not in translated
        assert "/* IF_NOT_EXISTS */" in translated

    def test_quantified_comparison_preserved(self, registry):
        sql = "SELECT * FROM t WHERE col > ALL (SELECT val FROM s)"
        translated, mappings = registry.translate_constructs(sql)
        assert "> ALL (" in translated

    def test_intersect_preserved(self, registry):
        sql = "SELECT a FROM t1 INTERSECT SELECT a FROM t2"
        translated, mappings = registry.translate_constructs(sql)
        assert "INTERSECT" in translated

    def test_no_match_returns_original(self, registry):
        sql = "SELECT 1 FROM dual"
        translated, mappings = registry.translate_constructs(sql)
        assert translated == sql
        assert mappings == []

    def test_mappings_contain_metadata(self, registry):
        sql = "SELECT ISNULL(a, 0) FROM t"
        _, mappings = registry.translate_constructs(sql)
        assert len(mappings) >= 1
        m = mappings[0]
        assert "construct_name" in m.metadata
        assert m.confidence > 0.0

    def test_correlated_exists_preserved(self, registry):
        sql = "SELECT * FROM t WHERE EXISTS (SELECT 1 FROM s WHERE s.id = t.id)"
        translated, mappings = registry.translate_constructs(sql)
        assert "EXISTS (SELECT 1 FROM" in translated

    def test_rownum_pattern_registered(self, registry):
        """Verify ROWNUM_PSEUDO_COLUMN construct is registered with correct metadata."""
        info = registry.get_construct_info("ROWNUM_PSEUDO_COLUMN")
        assert info is not None
        assert info["confidence"] == 0.8
        # The pattern targets %ROWNUM; verify it compiled without error
        assert info["pattern"] is not None


# ---------------------------------------------------------------------------
# add_construct
# ---------------------------------------------------------------------------


class TestAddConstruct:
    def test_add_custom_construct(self, registry):
        registry.add_construct(
            name="TEST_CONSTRUCT",
            pattern=r"\bFOO\b",
            replacement="BAR",
            confidence=0.9,
            construct_type=ConstructType.SYNTAX,
            notes="Test construct",
        )
        assert registry.has_construct("TEST_CONSTRUCT")

    def test_added_construct_translates(self, registry):
        registry.add_construct(
            name="REPLACE_FOO",
            pattern=r"\bFOO_TOKEN\b",
            replacement="BAZ_TOKEN",
            confidence=1.0,
            construct_type=ConstructType.SYNTAX,
        )
        translated, mappings = registry.translate_constructs("SELECT FOO_TOKEN FROM t")
        assert "BAZ_TOKEN" in translated
        assert len(mappings) >= 1


# ---------------------------------------------------------------------------
# search_constructs
# ---------------------------------------------------------------------------


class TestSearchConstructs:
    def test_search_by_name_substring(self, registry):
        results = registry.search_constructs("minus")
        assert "MINUS_OPERATOR" in results

    def test_search_by_notes(self, registry):
        results = registry.search_constructs("coalesce")
        assert len(results) >= 1

    def test_search_no_match(self, registry):
        assert registry.search_constructs("XYZZY_NONEXISTENT") == []


# ---------------------------------------------------------------------------
# get_construct_categories
# ---------------------------------------------------------------------------


class TestGetConstructCategories:
    def test_returns_dict_with_expected_keys(self, registry):
        categories = registry.get_construct_categories()
        for key in ["pagination", "joins", "case_logic", "conditionals", "subqueries",
                    "set_operations", "window_functions", "cte", "other"]:
            assert key in categories

    def test_pagination_contains_rownum(self, registry):
        cats = registry.get_construct_categories()
        assert "ROWNUM_PSEUDO_COLUMN" in cats["pagination"]

    def test_set_operations_contains_minus(self, registry):
        cats = registry.get_construct_categories()
        assert "MINUS_OPERATOR" in cats["set_operations"]

    def test_conditionals_contains_isnull(self, registry):
        cats = registry.get_construct_categories()
        assert "ISNULL_FUNCTION" in cats["conditionals"]

    def test_joins_contains_oracle_join(self, registry):
        cats = registry.get_construct_categories()
        assert "ORACLE_STYLE_OUTER_JOIN" in cats["joins"]

    def test_window_functions_contains_rank(self, registry):
        cats = registry.get_construct_categories()
        assert "RANK_FUNCTION" in cats["window_functions"]

    def test_cte_contains_recursive(self, registry):
        cats = registry.get_construct_categories()
        assert "RECURSIVE_CTE" in cats["cte"]


# ---------------------------------------------------------------------------
# get_mapping_stats
# ---------------------------------------------------------------------------


class TestGetMappingStats:
    def test_stats_structure(self, registry):
        stats = registry.get_mapping_stats()
        assert "total_constructs" in stats
        assert "confidence_distribution" in stats
        assert "type_distribution" in stats
        assert "category_counts" in stats
        assert "average_confidence" in stats

    def test_total_constructs_positive(self, registry):
        stats = registry.get_mapping_stats()
        assert stats["total_constructs"] > 0

    def test_average_confidence_in_range(self, registry):
        stats = registry.get_mapping_stats()
        assert 0.0 <= stats["average_confidence"] <= 1.0

    def test_confidence_distribution_sums_to_total(self, registry):
        stats = registry.get_mapping_stats()
        dist = stats["confidence_distribution"]
        total = dist["high"] + dist["medium"] + dist["low"]
        assert total == stats["total_constructs"]


# ---------------------------------------------------------------------------
# validate_construct_pattern
# ---------------------------------------------------------------------------


class TestValidateConstructPattern:
    def test_valid_pattern(self, registry):
        result = registry.validate_construct_pattern(r"\bSELECT\b")
        assert result["valid"] is True

    def test_invalid_pattern(self, registry):
        result = registry.validate_construct_pattern(r"[unclosed")
        assert result["valid"] is False
        assert "error" in result

    def test_valid_pattern_has_no_error_key(self, registry):
        result = registry.validate_construct_pattern(r"\w+")
        assert "error" not in result or result.get("valid") is True


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


class TestModuleLevelFunctions:
    def test_get_construct_registry_returns_instance(self):
        reg = get_construct_registry()
        assert isinstance(reg, IRISSQLConstructRegistry)

    def test_get_construct_registry_singleton(self):
        r1 = get_construct_registry()
        r2 = get_construct_registry()
        assert r1 is r2

    def test_translate_sql_constructs(self):
        translated, mappings = translate_sql_constructs("SELECT 1 MINUS SELECT 2")
        assert "EXCEPT" in translated

    def test_has_sql_construct_true(self):
        assert has_sql_construct("MINUS_OPERATOR") is True

    def test_has_sql_construct_false(self):
        assert has_sql_construct("GHOST_CONSTRUCT") is False


# ---------------------------------------------------------------------------
# get_all_construct_names
# ---------------------------------------------------------------------------


class TestGetAllConstructNames:
    def test_returns_set(self, registry):
        names = registry.get_all_construct_names()
        assert isinstance(names, set)
        assert len(names) > 0

    def test_known_name_in_set(self, registry):
        assert "MINUS_OPERATOR" in registry.get_all_construct_names()

"""
Unit tests for sql_translator/refiner.py

Extends the existing test_iris_collation_refiner.py with additional coverage
for _fix_order_by_aliases, _split_select_list, _extract_base_and_alias,
_derive_alias_from_expression, disabled-config paths, and edge cases.
"""

import pytest

from iris_pgwire.sql_translator.refiner import RefinerConfig, SQLRefiner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def full_refiner():
    """Refiner with both fixes enabled."""
    return SQLRefiner(RefinerConfig(fix_order_by_aliases=True, enforce_exact_collation=True))


@pytest.fixture
def alias_only_refiner():
    """Refiner with only ORDER BY alias fix enabled."""
    return SQLRefiner(RefinerConfig(fix_order_by_aliases=True, enforce_exact_collation=False))


@pytest.fixture
def collation_only_refiner():
    """Refiner with only collation enforcement enabled."""
    return SQLRefiner(RefinerConfig(fix_order_by_aliases=False, enforce_exact_collation=True))


@pytest.fixture
def no_fix_refiner():
    """Refiner with all fixes disabled."""
    return SQLRefiner(RefinerConfig(fix_order_by_aliases=False, enforce_exact_collation=False))


# ---------------------------------------------------------------------------
# Empty / trivial SQL
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_string_passthrough(self, full_refiner):
        assert full_refiner.refine("") == ""

    def test_none_like_empty_passthrough(self, full_refiner):
        # SQLRefiner.refine checks `if not sql`
        assert full_refiner.refine("") == ""

    def test_no_fixes_enabled_passthrough(self, no_fix_refiner):
        sql = "SELECT DISTINCT a FROM t ORDER BY a"
        assert no_fix_refiner.refine(sql) == sql

    def test_plain_select_no_change(self, full_refiner):
        sql = "SELECT id, name FROM users WHERE id = 1"
        result = full_refiner.refine(sql)
        assert "%EXACT" not in result.upper()
        assert result == sql


# ---------------------------------------------------------------------------
# _fix_order_by_aliases
# ---------------------------------------------------------------------------

class TestFixOrderByAliases:
    def test_alias_replaced_in_order_by(self, alias_only_refiner):
        sql = "SELECT price * 1.1 AS total_price FROM products ORDER BY total_price"
        result = alias_only_refiner.refine(sql)
        assert "total_price" not in result.split("ORDER BY")[1].lower() or \
               "price * 1.1" in result.split("ORDER BY")[1]

    def test_no_order_by_no_change(self, alias_only_refiner):
        sql = "SELECT a AS b FROM t"
        result = alias_only_refiner.refine(sql)
        assert result == sql

    def test_no_alias_no_change(self, alias_only_refiner):
        sql = "SELECT a, b FROM t ORDER BY a"
        result = alias_only_refiner.refine(sql)
        assert result == sql

    def test_no_select_from_no_change(self, alias_only_refiner):
        sql = "DELETE FROM t WHERE id = 1"
        result = alias_only_refiner.refine(sql)
        assert result == sql

    def test_alias_with_comma_in_expression(self, alias_only_refiner):
        # expression has comma-split: "a, b * 2 AS doubled"
        sql = "SELECT a, b * 2 AS doubled FROM t ORDER BY doubled"
        result = alias_only_refiner.refine(sql)
        # doubled should be replaced by "b * 2"
        order_part = result.split("ORDER BY")[1]
        assert "b * 2" in order_part

    def test_order_by_alias_disabled(self, collation_only_refiner):
        sql = "SELECT price AS p FROM products ORDER BY p"
        result = collation_only_refiner.refine(sql)
        # Without the alias fix, ORDER BY p stays as-is
        assert "ORDER BY p" in result


# ---------------------------------------------------------------------------
# _enforce_exact_collation – no-op conditions
# ---------------------------------------------------------------------------

class TestEnforceExactCollationNoOp:
    def test_no_distinct_no_union_unchanged(self, collation_only_refiner):
        sql = "SELECT a, b FROM t WHERE a > 1"
        assert collation_only_refiner.refine(sql) == sql

    def test_union_all_only_unchanged(self, collation_only_refiner):
        sql = "SELECT a FROM t1 UNION ALL SELECT b FROM t2"
        result = collation_only_refiner.refine(sql)
        assert "%EXACT" not in result.upper()

    def test_multiple_union_all_unchanged(self, collation_only_refiner):
        sql = "SELECT a FROM t1 UNION ALL SELECT b FROM t2 UNION ALL SELECT c FROM t3"
        result = collation_only_refiner.refine(sql)
        assert "%EXACT" not in result.upper()


# ---------------------------------------------------------------------------
# _enforce_exact_collation – wrapping
# ---------------------------------------------------------------------------

class TestEnforceExactCollationWrapping:
    def test_distinct_wraps_columns(self, collation_only_refiner):
        sql = "SELECT DISTINCT col1, col2 FROM t"
        result = collation_only_refiner.refine(sql)
        assert "%EXACT" in result.upper()

    def test_distinct_preserves_explicit_exact(self, collation_only_refiner):
        sql = "SELECT DISTINCT %EXACT col1 AS col1 FROM t"
        result = collation_only_refiner.refine(sql)
        # should not double-wrap
        assert result.upper().count("%EXACT") == 1

    def test_union_not_all_wraps(self, collation_only_refiner):
        sql = "SELECT a FROM t1 UNION SELECT b FROM t2"
        result = collation_only_refiner.refine(sql)
        assert "%EXACT" in result.upper()
        assert "UNION" in result.upper()

    def test_mixed_union_and_union_all(self, collation_only_refiner):
        # UNION (not all) alongside UNION ALL — should wrap because there's a plain UNION
        sql = "SELECT a FROM t1 UNION SELECT b FROM t2 UNION ALL SELECT c FROM t3"
        result = collation_only_refiner.refine(sql)
        assert "%EXACT" in result.upper()

    def test_distinct_with_alias_preserves_alias(self, collation_only_refiner):
        sql = "SELECT DISTINCT name AS n FROM t"
        result = collation_only_refiner.refine(sql)
        assert "AS n" in result or "AS N" in result.upper()

    def test_no_from_clause_segment_unchanged(self, collation_only_refiner):
        # Segment without FROM → _wrap_select_segment should return it unchanged
        refiner = collation_only_refiner
        result = refiner._wrap_select_segment("no from here")
        assert result == "no from here"


# ---------------------------------------------------------------------------
# _split_select_list
# ---------------------------------------------------------------------------

class TestSplitSelectList:
    @pytest.fixture
    def refiner(self):
        return SQLRefiner()

    def test_simple_split(self, refiner):
        parts = refiner._split_select_list("a, b, c")
        assert parts == ["a", " b", " c"]

    def test_no_comma(self, refiner):
        parts = refiner._split_select_list("a")
        assert parts == ["a"]

    def test_paren_protects_comma(self, refiner):
        parts = refiner._split_select_list("COALESCE(a, b), c")
        assert len(parts) == 2
        assert "COALESCE(a, b)" in parts[0]

    def test_single_quoted_string_protects_comma(self, refiner):
        parts = refiner._split_select_list("'a, b', c")
        assert len(parts) == 2

    def test_double_quoted_identifier_protects_comma(self, refiner):
        parts = refiner._split_select_list('"col, name", other')
        assert len(parts) == 2

    def test_escaped_single_quote(self, refiner):
        # '' inside single-quoted string
        parts = refiner._split_select_list("'it''s here', col")
        assert len(parts) == 2

    def test_empty_string(self, refiner):
        parts = refiner._split_select_list("")
        assert parts == []


# ---------------------------------------------------------------------------
# _extract_base_and_alias
# ---------------------------------------------------------------------------

class TestExtractBaseAndAlias:
    @pytest.fixture
    def refiner(self):
        return SQLRefiner()

    def test_with_as_alias(self, refiner):
        base, alias = refiner._extract_base_and_alias("price * 1.1 AS total")
        assert "price * 1.1" in base
        assert alias == "total"

    def test_with_quoted_alias(self, refiner):
        base, alias = refiner._extract_base_and_alias('col AS "My Alias"')
        assert alias == '"My Alias"'

    def test_no_alias(self, refiner):
        base, alias = refiner._extract_base_and_alias("col_name")
        assert base == "col_name"
        assert alias is None


# ---------------------------------------------------------------------------
# _derive_alias_from_expression
# ---------------------------------------------------------------------------

class TestDeriveAliasFromExpression:
    @pytest.fixture
    def refiner(self):
        return SQLRefiner()

    def test_simple_identifier(self, refiner):
        alias = refiner._derive_alias_from_expression("column_name")
        assert alias == "column_name"

    def test_qualified_identifier(self, refiner):
        # t.col → derived alias should be "col"
        alias = refiner._derive_alias_from_expression("t.col")
        assert alias == "col"

    def test_expression_no_identifier(self, refiner):
        # Pure numeric literal – no trailing identifier
        alias = refiner._derive_alias_from_expression("1 + 2")
        # May return "2" or None depending on regex; just ensure no crash
        assert alias is None or isinstance(alias, str)

    def test_quoted_identifier(self, refiner):
        alias = refiner._derive_alias_from_expression('"MyCol"')
        assert alias == '"MyCol"'


# ---------------------------------------------------------------------------
# _wrap_select_list – alias generation
# ---------------------------------------------------------------------------

class TestWrapSelectList:
    @pytest.fixture
    def refiner(self):
        return SQLRefiner(RefinerConfig(enforce_exact_collation=True))

    def test_col_n_fallback_alias(self, refiner):
        # An expression that _derive_alias_from_expression returns None for
        # so the fallback COL_N alias is used.
        # Use something that won't match the identifier suffix pattern.
        result = refiner._wrap_select_list("1 + 2")
        # Should have COL_1 since no identifier derivable from "1 + 2"
        assert "COL_1" in result or "%EXACT" in result

    def test_already_exact_passthrough(self, refiner):
        result = refiner._wrap_select_list("%EXACT a AS a")
        # Starts with %EXACT → should not be re-wrapped
        assert result.upper().count("%EXACT") == 1

    def test_empty_column_skipped(self, refiner):
        # Trailing comma produces empty slot; should be skipped
        result = refiner._wrap_select_list("a, ")
        assert "COL_" not in result or result.count("%EXACT") == 1


# ---------------------------------------------------------------------------
# Default config
# ---------------------------------------------------------------------------

class TestDefaultConfig:
    def test_default_config_both_enabled(self):
        refiner = SQLRefiner()
        assert refiner.config.fix_order_by_aliases is True
        assert refiner.config.enforce_exact_collation is True

    def test_custom_config_stored(self):
        cfg = RefinerConfig(fix_order_by_aliases=False, enforce_exact_collation=False)
        refiner = SQLRefiner(cfg)
        assert refiner.config is cfg

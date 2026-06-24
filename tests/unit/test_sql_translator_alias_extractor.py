"""
Unit tests for sql_translator/alias_extractor.py — AliasExtractor.
Goal: ≥85% coverage.
"""

import pytest

from iris_pgwire.sql_translator.alias_extractor import AliasExtractor


@pytest.fixture
def extractor():
    return AliasExtractor()


# ---------------------------------------------------------------------------
# Basic AS alias extraction
# ---------------------------------------------------------------------------


class TestExplicitAliases:
    def test_single_as_alias(self, extractor):
        aliases = extractor.extract_column_aliases("SELECT 1 AS num")
        assert aliases == ["num"]

    def test_multiple_as_aliases(self, extractor):
        aliases = extractor.extract_column_aliases("SELECT 1 AS num, 'hello' AS greeting")
        assert aliases == ["num", "greeting"]

    def test_function_with_alias(self, extractor):
        aliases = extractor.extract_column_aliases("SELECT COUNT(*) AS total FROM users")
        assert aliases == ["total"]

    def test_expression_with_alias(self, extractor):
        aliases = extractor.extract_column_aliases("SELECT a + b AS sum_val FROM t")
        assert aliases == ["sum_val"]

    def test_cast_with_alias(self, extractor):
        """CAST(? AS INTEGER) AS num — should take the last AS (num)."""
        aliases = extractor.extract_column_aliases("SELECT CAST(? AS INTEGER) AS num FROM t")
        assert aliases == ["num"]

    def test_mixed_explicit_and_implicit(self, extractor):
        aliases = extractor.extract_column_aliases("SELECT id, name AS full_name FROM users")
        assert aliases == ["id", "full_name"]


# ---------------------------------------------------------------------------
# Implicit column names (no AS)
# ---------------------------------------------------------------------------


class TestImplicitAliases:
    def test_simple_column(self, extractor):
        aliases = extractor.extract_column_aliases("SELECT id FROM users")
        assert aliases == ["id"]

    def test_multiple_simple_columns(self, extractor):
        aliases = extractor.extract_column_aliases("SELECT id, name FROM users")
        assert aliases == ["id", "name"]

    def test_schema_qualified_column(self, extractor):
        """table.column → column name is extracted."""
        aliases = extractor.extract_column_aliases("SELECT users.id FROM users")
        assert aliases == ["id"]

    def test_quoted_prisma_style(self, extractor):
        """\"public\".\"test_users\".\"id\" → id."""
        aliases = extractor.extract_column_aliases(
            'SELECT "public"."test_users"."id" FROM "public"."test_users"'
        )
        assert aliases == ["id"]

    def test_star_returns_column(self, extractor):
        """SELECT * — the '*' character triggers fallback."""
        aliases = extractor.extract_column_aliases("SELECT * FROM t")
        # Should return something, not crash
        assert isinstance(aliases, list)


# ---------------------------------------------------------------------------
# Queries without FROM
# ---------------------------------------------------------------------------


class TestNoFromClause:
    def test_select_literal_no_from(self, extractor):
        aliases = extractor.extract_column_aliases("SELECT 1 AS num")
        assert aliases == ["num"]

    def test_select_multiple_literals_no_from(self, extractor):
        aliases = extractor.extract_column_aliases("SELECT 1 AS a, 2 AS b, 3 AS c")
        assert aliases == ["a", "b", "c"]

    def test_select_string_literal(self, extractor):
        aliases = extractor.extract_column_aliases("SELECT 'hello' AS greeting")
        assert aliases == ["greeting"]


# ---------------------------------------------------------------------------
# UNION queries — should only extract from first SELECT
# ---------------------------------------------------------------------------


class TestUnionQueries:
    def test_union_uses_first_select(self, extractor):
        sql = "SELECT id AS user_id FROM a UNION SELECT id FROM b"
        aliases = extractor.extract_column_aliases(sql)
        assert aliases == ["user_id"]


# ---------------------------------------------------------------------------
# Commas inside function calls / nested parens
# ---------------------------------------------------------------------------


class TestNestedParentheses:
    def test_function_with_multiple_args(self, extractor):
        """COALESCE(a, b) should not split on the internal comma."""
        aliases = extractor.extract_column_aliases("SELECT COALESCE(a, b) AS val FROM t")
        assert aliases == ["val"]

    def test_nested_function_calls(self, extractor):
        sql = "SELECT COALESCE(a, b) AS x, COUNT(DISTINCT c) AS y FROM t"
        aliases = extractor.extract_column_aliases(sql)
        assert aliases == ["x", "y"]

    def test_case_expression(self, extractor):
        sql = "SELECT CASE WHEN x > 0 THEN 'pos' ELSE 'neg' END AS sign FROM t"
        aliases = extractor.extract_column_aliases(sql)
        assert aliases == ["sign"]


# ---------------------------------------------------------------------------
# String literals with commas
# ---------------------------------------------------------------------------


class TestStringLiteralsWithCommas:
    def test_string_with_comma_not_split(self, extractor):
        """Comma inside a string literal must not split the column."""
        sql = "SELECT 'hello, world' AS greeting FROM t"
        aliases = extractor.extract_column_aliases(sql)
        assert aliases == ["greeting"]

    def test_escaped_single_quote_in_string(self, extractor):
        sql = "SELECT 'it''s fine' AS note FROM t"
        aliases = extractor.extract_column_aliases(sql)
        assert aliases == ["note"]


# ---------------------------------------------------------------------------
# Non-SELECT queries
# ---------------------------------------------------------------------------


class TestNonSelectQueries:
    def test_insert_returns_empty(self, extractor):
        aliases = extractor.extract_column_aliases("INSERT INTO t (id) VALUES (1)")
        assert aliases == []

    def test_update_returns_empty(self, extractor):
        aliases = extractor.extract_column_aliases("UPDATE t SET col = 1")
        assert aliases == []

    def test_delete_returns_empty(self, extractor):
        aliases = extractor.extract_column_aliases("DELETE FROM t WHERE id = 1")
        assert aliases == []

    def test_empty_string_returns_empty(self, extractor):
        aliases = extractor.extract_column_aliases("")
        assert aliases == []


# ---------------------------------------------------------------------------
# _split_select_columns directly
# ---------------------------------------------------------------------------


class TestSplitSelectColumns:
    def test_simple_split(self, extractor):
        cols = extractor._split_select_columns("a, b, c")
        assert cols == ["a", "b", "c"]

    def test_paren_depth_respected(self, extractor):
        cols = extractor._split_select_columns("f(a, b), c")
        assert cols == ["f(a, b)", "c"]

    def test_string_with_comma(self, extractor):
        cols = extractor._split_select_columns("'x, y', z")
        assert cols == ["'x, y'", "z"]

    def test_empty_string(self, extractor):
        cols = extractor._split_select_columns("")
        assert cols == []

    def test_single_item(self, extractor):
        cols = extractor._split_select_columns("abc")
        assert cols == ["abc"]


# ---------------------------------------------------------------------------
# _extract_single_alias directly
# ---------------------------------------------------------------------------


class TestExtractSingleAlias:
    def test_explicit_as(self, extractor):
        assert extractor._extract_single_alias("expr AS my_col") == "my_col"

    def test_no_as_simple_identifier(self, extractor):
        assert extractor._extract_single_alias("col_name") == "col_name"

    def test_table_qualified(self, extractor):
        result = extractor._extract_single_alias("t.col_name")
        assert result == "col_name"

    def test_string_literal_with_as(self, extractor):
        assert extractor._extract_single_alias("'hello' AS greeting") == "greeting"

    def test_multiple_as_takes_last(self, extractor):
        # CAST(? AS INTEGER) AS num → last AS → num
        result = extractor._extract_single_alias("CAST(? AS INTEGER) AS num")
        assert result == "num"

    def test_fully_qualified_quoted(self, extractor):
        result = extractor._extract_single_alias('"public"."users"."email"')
        assert result == "email"

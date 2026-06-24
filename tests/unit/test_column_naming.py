"""Unit tests for iris_pgwire._column_naming module.

Tests all branches of normalize_iris_column_name including:
- Numeric literal column names (with and without explicit aliases)
- SELECT without FROM: generic names and string literals
- HostVar_N → ?column?
- Expression_N → type name or ?column?
- Aggregate_N → function name
- PostgreSQL type name mapping
- Named columns (keep lowercase)
"""

from __future__ import annotations

import pytest

from iris_pgwire._column_naming import normalize_iris_column_name


class TestNumericLiteralColumns:
    """Test numeric literal column name handling."""

    def test_integer_literal_no_alias(self):
        result = normalize_iris_column_name("1", "SELECT 1", "integer")
        assert result == "?column?"

    def test_float_literal_no_alias(self):
        result = normalize_iris_column_name("3.14", "SELECT 3.14", "double")
        assert result == "?column?"

    def test_negative_literal_no_alias(self):
        result = normalize_iris_column_name("-5", "SELECT -5", "integer")
        assert result == "?column?"

    def test_integer_literal_with_explicit_alias(self):
        result = normalize_iris_column_name("1", "SELECT 1 AS id", "integer")
        assert result == "id"

    def test_float_literal_with_explicit_alias(self):
        result = normalize_iris_column_name("2.5", "SELECT 2.5 AS score", "double")
        assert result == "score"

    def test_numeric_alias_is_lowercased(self):
        result = normalize_iris_column_name("42", "SELECT 42 AS MyNum", "integer")
        assert result == "mynum"


    def test_numeric_literal_case_insensitive_as(self):
        result = normalize_iris_column_name("10", "SELECT 10 as total", "integer")
        assert result == "total"


class TestSelectWithoutFrom:
    """Test SELECT without FROM: generic names and string literals."""

    def test_generic_column_name_no_alias(self):
        # 'column' is in _GENERIC_COLUMN_NAMES
        result = normalize_iris_column_name("Column", "SELECT 'hello'", "varchar")
        assert result == "?column?"

    def test_generic_column1_no_alias(self):
        result = normalize_iris_column_name("column1", "SELECT 'x'", "varchar")
        assert result == "?column?"

    def test_generic_column2_no_alias(self):
        result = normalize_iris_column_name("column2", "SELECT 'x', 'y'", "varchar")
        assert result == "?column?"

    def test_generic_column3_no_alias(self):
        result = normalize_iris_column_name("column3", "SELECT 1, 2, 3", "integer")
        assert result == "?column?"

    def test_generic_column4_no_alias(self):
        result = normalize_iris_column_name("column4", "SELECT 1, 2, 3, 4", "integer")
        assert result == "?column?"

    def test_generic_column5_no_alias(self):
        result = normalize_iris_column_name("column5", "SELECT 1, 2, 3, 4, 5", "integer")
        assert result == "?column?"

    def test_generic_name_with_explicit_as_alias(self):
        # If SQL contains "AS column1", keep the name
        result = normalize_iris_column_name("column1", "SELECT x AS column1 FROM t", "integer")
        # Has FROM, so the SELECT-without-FROM branch is skipped; returns normalized name
        assert result == "column1"

    def test_generic_name_with_quoted_as_alias_no_from(self):
        # When no FROM clause, "column1" in quotes also matches the string-literal check,
        # so ?column? is returned (the quoted form triggers the literal branch)
        result = normalize_iris_column_name(
            "column1", 'SELECT expr AS "column1"', "integer"
        )
        assert result == "?column?"

    def test_generic_name_with_unquoted_as_alias_no_from(self):
        # Unquoted AS alias prevents the generic-name → ?column? substitution
        result = normalize_iris_column_name(
            "column1", "SELECT expr AS column1", "integer"
        )
        assert result == "column1"

    def test_string_literal_used_as_column_name(self):
        # IRIS gives name 'hello' (the string content) — should become ?column?
        result = normalize_iris_column_name("hello", "SELECT 'hello'", "varchar")
        assert result == "?column?"

    def test_string_literal_double_quoted(self):
        result = normalize_iris_column_name("world", 'SELECT "world"', "varchar")
        assert result == "?column?"

    def test_select_without_from_non_generic_non_literal(self):
        # A real expression alias in SELECT without FROM that isn't a string literal
        result = normalize_iris_column_name("myalias", "SELECT 1+1 AS myalias", "integer")
        assert result == "myalias"


class TestHostVarColumns:
    """Test HostVar_N → ?column? mapping."""

    def test_hostvar_1(self):
        result = normalize_iris_column_name("HostVar_1", "SELECT $1", "varchar")
        assert result == "?column?"

    def test_hostvar_10(self):
        result = normalize_iris_column_name("HostVar_10", "SELECT $10", "integer")
        assert result == "?column?"

    def test_hostvar_uppercase(self):
        result = normalize_iris_column_name("HOSTVAR_1", "SELECT $1", "integer")
        assert result == "?column?"


class TestExpressionColumns:
    """Test Expression_N → type name or ?column?."""

    def test_expression_double_colon_int(self):
        result = normalize_iris_column_name("Expression_1", "SELECT x::INT FROM t", "integer")
        assert result == "int4"

    def test_expression_double_colon_bigint(self):
        result = normalize_iris_column_name("Expression_1", "SELECT x::BIGINT FROM t", "integer")
        assert result == "int8"

    def test_expression_double_colon_smallint(self):
        result = normalize_iris_column_name("Expression_1", "SELECT x::SMALLINT FROM t", "integer")
        assert result == "int2"

    def test_expression_double_colon_text(self):
        result = normalize_iris_column_name("Expression_1", "SELECT x::TEXT FROM t", "varchar")
        assert result == "text"

    def test_expression_double_colon_varchar(self):
        result = normalize_iris_column_name("Expression_1", "SELECT x::VARCHAR FROM t", "varchar")
        assert result == "varchar"

    def test_expression_double_colon_bool(self):
        result = normalize_iris_column_name("Expression_1", "SELECT x::BOOL FROM t", "bit")
        assert result == "bool"

    def test_expression_double_colon_date(self):
        result = normalize_iris_column_name("Expression_1", "SELECT x::DATE FROM t", "date")
        assert result == "date"

    def test_expression_cast_as_integer(self):
        result = normalize_iris_column_name(
            "Expression_1", "SELECT CAST(x AS INTEGER) FROM t", "integer"
        )
        assert result == "int4"

    def test_expression_cast_as_bigint(self):
        result = normalize_iris_column_name(
            "Expression_1", "SELECT CAST(x AS BIGINT) FROM t", "integer"
        )
        assert result == "int8"

    def test_expression_cast_as_smallint(self):
        result = normalize_iris_column_name(
            "Expression_1", "SELECT CAST(x AS SMALLINT) FROM t", "integer"
        )
        assert result == "int2"

    def test_expression_cast_as_text(self):
        result = normalize_iris_column_name(
            "Expression_1", "SELECT CAST(x AS TEXT) FROM t", "varchar"
        )
        assert result == "text"

    def test_expression_cast_as_varchar(self):
        result = normalize_iris_column_name(
            "Expression_1", "SELECT CAST(x AS VARCHAR) FROM t", "varchar"
        )
        assert result == "varchar"

    def test_expression_cast_as_bool(self):
        result = normalize_iris_column_name(
            "Expression_1", "SELECT CAST(x AS BIT) FROM t", "bit"
        )
        assert result == "bool"

    def test_expression_cast_as_date(self):
        result = normalize_iris_column_name(
            "Expression_1", "SELECT CAST(x AS DATE) FROM t", "date"
        )
        assert result == "date"

    def test_expression_no_cast(self):
        result = normalize_iris_column_name(
            "Expression_1", "SELECT x + 1 FROM t", "integer"
        )
        assert result == "?column?"

    def test_expression_uppercase_iris_name(self):
        result = normalize_iris_column_name("EXPRESSION_2", "SELECT x::TEXT FROM t", "varchar")
        assert result == "text"


class TestAggregateColumns:
    """Test Aggregate_N → function name mapping."""

    def test_aggregate_count(self):
        result = normalize_iris_column_name("Aggregate_1", "SELECT COUNT(*) FROM t", "integer")
        assert result == "count"

    def test_aggregate_sum(self):
        result = normalize_iris_column_name("Aggregate_1", "SELECT SUM(x) FROM t", "integer")
        assert result == "sum"

    def test_aggregate_avg(self):
        result = normalize_iris_column_name("Aggregate_1", "SELECT AVG(x) FROM t", "double")
        assert result == "avg"

    def test_aggregate_min(self):
        result = normalize_iris_column_name("Aggregate_1", "SELECT MIN(x) FROM t", "integer")
        assert result == "min"

    def test_aggregate_max(self):
        result = normalize_iris_column_name("Aggregate_1", "SELECT MAX(x) FROM t", "integer")
        assert result == "max"

    def test_aggregate_no_known_function(self):
        # e.g. some custom aggregate — returns the lowercased IRIS name
        result = normalize_iris_column_name("Aggregate_1", "SELECT STDEV(x) FROM t", "double")
        assert result == "aggregate_1"

    def test_aggregate_uppercase(self):
        result = normalize_iris_column_name("AGGREGATE_2", "SELECT COUNT(*) FROM t", "integer")
        assert result == "count"


class TestPostgresTypeMapping:
    """Test IRIS type name → PostgreSQL short name mapping."""

    def test_integer_to_int4(self):
        result = normalize_iris_column_name("integer", "SELECT x FROM t", "integer")
        assert result == "int4"

    def test_bigint_to_int8(self):
        result = normalize_iris_column_name("bigint", "SELECT x FROM t", "bigint")
        assert result == "int8"

    def test_smallint_to_int2(self):
        result = normalize_iris_column_name("smallint", "SELECT x FROM t", "smallint")
        assert result == "int2"

    def test_real_to_float4(self):
        result = normalize_iris_column_name("real", "SELECT x FROM t", "real")
        assert result == "float4"

    def test_double_to_float8(self):
        result = normalize_iris_column_name("double", "SELECT x FROM t", "double")
        assert result == "float8"

    def test_double_precision_to_float8(self):
        result = normalize_iris_column_name("double precision", "SELECT x FROM t", "double")
        assert result == "float8"

    def test_character_varying_to_varchar(self):
        result = normalize_iris_column_name("character varying", "SELECT x FROM t", "varchar")
        assert result == "varchar"

    def test_character_to_char(self):
        result = normalize_iris_column_name("character", "SELECT x FROM t", "char")
        assert result == "char"


class TestNamedColumns:
    """Test that named columns are returned lowercased."""

    def test_simple_name(self):
        result = normalize_iris_column_name("MyColumn", "SELECT MyColumn FROM t", "varchar")
        assert result == "mycolumn"

    def test_already_lowercase(self):
        result = normalize_iris_column_name("name", "SELECT name FROM t", "varchar")
        assert result == "name"

    def test_mixed_case(self):
        result = normalize_iris_column_name("UserID", "SELECT UserID FROM t", "integer")
        assert result == "userid"

    def test_name_with_underscore(self):
        result = normalize_iris_column_name("first_name", "SELECT first_name FROM t", "varchar")
        assert result == "first_name"

    def test_with_from_clause_no_generic_rule(self):
        # Generic column names should NOT be mapped to ?column? when FROM is present
        result = normalize_iris_column_name("column1", "SELECT column1 FROM t", "varchar")
        assert result == "column1"

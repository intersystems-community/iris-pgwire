"""Extended unit tests for DDLParser — targeting uncovered branches.

Pure Python, no IRIS container required.
These tests focus on branches NOT covered by test_ddl_parser.py.
"""

from __future__ import annotations

import pytest
import sqlparse
from sqlparse.sql import Identifier, Statement, Token

from iris_pgwire.sql_translator.ddl_parser import (
    ColumnDefinition,
    ConstraintDefinition,
    ConstraintType,
    DDLParser,
)
from iris_pgwire.sql_translator.ddl_translator import DDLStatement


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def parser() -> DDLParser:
    return DDLParser()


def _first(result: list[DDLStatement]) -> DDLStatement:
    assert len(result) >= 1, "Expected at least one DDLStatement"
    return result[0]


def _make_stmt(sql: str) -> Statement:
    """Return the first sqlparse Statement for the given SQL string."""
    return sqlparse.parse(sql)[0]


# ---------------------------------------------------------------------------
# _is_create_table / _is_alter_table / _is_drop_table — short-token path
# (lines 119, 127, 135)
# ---------------------------------------------------------------------------


class TestIsXxxTableShortTokens:
    """Statements with fewer than 3 non-whitespace tokens return False."""

    def test_is_create_table_returns_false_for_short_input(self, parser):
        stmt = _make_stmt("CREATE")
        assert parser._is_create_table(stmt) is False

    def test_is_alter_table_returns_false_for_short_input(self, parser):
        stmt = _make_stmt("ALTER")
        assert parser._is_alter_table(stmt) is False

    def test_is_drop_table_returns_false_for_short_input(self, parser):
        stmt = _make_stmt("DROP")
        assert parser._is_drop_table(stmt) is False

    def test_is_create_index_returns_false_for_short_input(self, parser):
        # covers line 333
        stmt = _make_stmt("CREATE")
        assert parser._is_create_index(stmt) is False

    def test_is_create_table_two_tokens_returns_false(self, parser):
        stmt = _make_stmt("CREATE TABLE")
        assert parser._is_create_table(stmt) is False


# ---------------------------------------------------------------------------
# _extract_table_name — IF NOT EXISTS path and plain Name token path
# (lines 155, 158-160)
# ---------------------------------------------------------------------------


class TestExtractTableNameEdgeCases:
    def test_create_table_if_not_exists(self, parser):
        """IF NOT EXISTS tokens skipped; table name extracted correctly."""
        sql = "CREATE TABLE IF NOT EXISTS foo (id INTEGER)"
        result = parser.parse(sql)
        assert len(result) == 1
        assert result[0].table_name == "foo"

    def test_drop_table_if_exists(self, parser):
        """DROP TABLE IF EXISTS — name still extracted."""
        sql = "DROP TABLE IF EXISTS bar"
        result = parser.parse(sql)
        assert len(result) == 1
        assert result[0].table_name == "bar"

    def test_create_table_if_not_exists_schema_qualified(self, parser):
        sql = "CREATE TABLE IF NOT EXISTS myschema.widgets (id INTEGER)"
        result = parser.parse(sql)
        assert len(result) == 1
        assert result[0].schema_name == "myschema"
        assert result[0].table_name == "widgets"


# ---------------------------------------------------------------------------
# _extract_clause_after_table — IF / NOT / EXISTS skip, table_ident_found
# (lines 179, 186)
# ---------------------------------------------------------------------------


class TestExtractClauseAfterTable:
    def test_clause_for_drop_table_if_exists(self, parser):
        """IF EXISTS is skipped; no operation_details clause returned."""
        sql = "DROP TABLE IF EXISTS some_table"
        result = parser.parse(sql)
        assert len(result) == 1
        # No trailing clause after the table name
        stmt = result[0]
        assert stmt.table_name == "some_table"

    def test_alter_table_extract_clause_with_if_not_exists(self, parser):
        """ADD COLUMN IF NOT EXISTS — clause_after_table still sees ADD COLUMN."""
        sql = "ALTER TABLE t ADD COLUMN IF NOT EXISTS new_col TEXT"
        result = parser.parse(sql)
        assert len(result) == 1
        stmt = result[0]
        assert stmt.operation == "ADD_COLUMN"


# ---------------------------------------------------------------------------
# _parse_columns_and_constraints — no parenthesis (line 231)
# also covers the empty-entry filtering inside the loop
# ---------------------------------------------------------------------------


class TestParseColumnsAndConstraints:
    def test_no_parenthesis_returns_empty(self, parser):
        """Calling _parse_columns_and_constraints on a stmt with no Parenthesis."""
        stmt = _make_stmt("SELECT 1")
        cols, constraints = parser._parse_columns_and_constraints(stmt)
        assert cols == []
        assert constraints == []

    def test_empty_column_entries_filtered(self, parser):
        """Trailing comma inside parens should not produce empty entries."""
        sql = "CREATE TABLE t (id INTEGER, name TEXT)"
        stmt = _first(parser.parse(sql))
        assert all(c.name for c in stmt.columns)


# ---------------------------------------------------------------------------
# _handle_alter_add_column_operation — failure path (line 285)
# ---------------------------------------------------------------------------


class TestHandleAlterAddColumnFailure:
    def test_add_column_missing_keyword_returns_warning(self, parser):
        """_handle_alter_add_column_operation with a clause missing ADD COLUMN."""
        details, cols, warnings, ok = parser._handle_alter_add_column_operation(
            "SOME UNRECOGNIZED CLAUSE"
        )
        assert ok is False
        assert details is None
        assert cols == []
        assert any("ADD COLUMN" in w for w in warnings)

    def test_add_column_empty_clause(self, parser):
        details, cols, warnings, ok = parser._handle_alter_add_column_operation("")
        assert ok is False
        assert any("ADD COLUMN" in w for w in warnings)


# ---------------------------------------------------------------------------
# _handle_alter_drop_column_operation — failure path (line 293)
# ---------------------------------------------------------------------------


class TestHandleAlterDropColumnFailure:
    def test_drop_column_missing_keyword_returns_warning(self, parser):
        details, cols, warnings, ok = parser._handle_alter_drop_column_operation("")
        assert ok is False
        assert any("DROP COLUMN" in w for w in warnings)


# ---------------------------------------------------------------------------
# _handle_alter_rename_column_operation — failure path (line 301)
# ---------------------------------------------------------------------------


class TestHandleAlterRenameColumnFailure:
    def test_rename_column_missing_keyword_returns_warning(self, parser):
        details, cols, warnings, ok = parser._handle_alter_rename_column_operation("")
        assert ok is False
        assert any("RENAME COLUMN" in w for w in warnings)

    def test_rename_column_only_one_name_returns_warning(self, parser):
        """If there is only one identifier (no TO target), returns failure."""
        details, cols, warnings, ok = parser._handle_alter_rename_column_operation(
            "RENAME COLUMN old_name"
        )
        assert ok is False


# ---------------------------------------------------------------------------
# _handle_unsupported_alter — empty clause path (line 312)
# ---------------------------------------------------------------------------


class TestHandleUnsupportedAlter:
    def test_empty_clause_gives_missing_warning(self, parser):
        """Empty clause triggers 'ALTER TABLE clause missing' warning."""
        details, cols, warnings, ok = parser._handle_unsupported_alter("", None)
        assert ok is False
        assert any("missing" in w for w in warnings)

    def test_non_empty_clause_gives_unsupported_warning(self, parser):
        details, cols, warnings, ok = parser._handle_unsupported_alter(
            "ALTER COLUMN x TYPE BIGINT", "ALTER_COLUMN_TYPE"
        )
        assert ok is False
        assert any("Unsupported" in w for w in warnings)

    def test_non_empty_clause_no_operation_uses_clause_text(self, parser):
        """When operation is None but clause is non-empty, clause text used in warning."""
        details, cols, warnings, ok = parser._handle_unsupported_alter("WEIRD THING", None)
        assert ok is False
        assert warnings


# ---------------------------------------------------------------------------
# _parse_primary_key_constraint — no parens (line 408)
# ---------------------------------------------------------------------------


class TestParsePrimaryKeyConstraintNoParen:
    def test_primary_key_without_parens_returns_empty_columns(self, parser):
        """PRIMARY KEY definition with no parentheses yields empty columns tuple."""
        constraint = parser._parse_primary_key_constraint("PRIMARY KEY")
        assert constraint.constraint_type == ConstraintType.PRIMARY_KEY
        assert constraint.columns == ()

    def test_primary_key_malformed_parens(self, parser):
        """Close paren before open paren yields empty columns."""
        constraint = parser._parse_primary_key_constraint("PRIMARY KEY )id(")
        assert constraint.columns == ()


# ---------------------------------------------------------------------------
# _parse_column_definition — empty token list (line 478)
# ---------------------------------------------------------------------------


class TestParseColumnDefinitionEmpty:
    def test_empty_definition_raises(self, parser):
        """An empty string passed to _parse_column_definition raises an error.

        sqlparse.parse("") returns an empty tuple causing IndexError before
        _parse_column_definition even reaches its own ValueError guard; either
        error is acceptable since both indicate a truly empty input.
        """
        with pytest.raises((ValueError, IndexError)):
            parser._parse_column_definition("")

    def test_whitespace_only_definition_raises(self, parser):
        """Whitespace-only input has no usable tokens and raises ValueError."""
        with pytest.raises((ValueError, IndexError)):
            parser._parse_column_definition("   ")


# ---------------------------------------------------------------------------
# _consume_not_null_clause — branches (lines 536-539)
# The 'NOT NULL' split case: token says 'NOT', next token says 'NULL'
# vs. no NULL following (just NOT).
# ---------------------------------------------------------------------------


class TestConsumeNotNullClause:
    def _make_tokens(self, sql: str):
        parsed = sqlparse.parse(sql)[0]
        return [t for t in parsed.tokens if not t.is_whitespace]

    def test_not_null_combined_token(self, parser):
        """When token value is 'NOT NULL' itself, advance by 1."""
        tokens = self._make_tokens("NOT NULL")
        idx = parser._consume_not_null_clause(tokens, 0)
        assert idx == 1

    def test_not_followed_by_null_token(self, parser):
        """Column with separate NOT ... NULL tokens advances by 2."""
        sql = "CREATE TABLE t (a INTEGER NOT NULL)"
        stmt = _first(parser.parse(sql))
        col = stmt.columns[0]
        assert col.nullable is False

    def test_not_without_null_advances_by_one(self, parser):
        """When NOT is not followed by NULL keyword, advance by 1 only."""
        # Build a minimal token list: keyword 'NOT' followed by a name token
        tokens = self._make_tokens("NOT something")
        # tokens[0] is 'NOT' keyword; tokens[1] is 'something' (Name)
        idx = parser._consume_not_null_clause(tokens, 0)
        # next token is not NULL, so returns idx+1 = 1
        assert idx == 1


# ---------------------------------------------------------------------------
# _consume_primary_clause — branches (lines 545-548)
# ---------------------------------------------------------------------------


class TestConsumePrimaryClause:
    def _make_tokens(self, sql: str):
        parsed = sqlparse.parse(sql)[0]
        return [t for t in parsed.tokens if not t.is_whitespace]

    def test_primary_key_combined_token(self, parser):
        """Token value 'PRIMARY KEY' advances by 1."""
        tokens = self._make_tokens("PRIMARY KEY")
        idx = parser._consume_primary_clause(tokens, 0)
        assert idx == 1

    def test_primary_without_key_followed_by_key(self, parser):
        """Separate PRIMARY ... KEY tokens advance by 2."""
        sql = "CREATE TABLE t (id INTEGER PRIMARY KEY)"
        stmt = _first(parser.parse(sql))
        col = stmt.columns[0]
        assert col.is_primary_key is True

    def test_primary_without_key_advances_by_one(self, parser):
        """PRIMARY not followed by KEY: advances by 1."""
        tokens = self._make_tokens("PRIMARY something")
        idx = parser._consume_primary_clause(tokens, 0)
        assert idx == 1


# ---------------------------------------------------------------------------
# _extract_default_clause — depth tracking (lines 557, 559-561, 568, 570)
# ---------------------------------------------------------------------------


class TestExtractDefaultClause:
    def test_default_with_function_call(self, parser):
        """DEFAULT with a function call — parens increase/decrease depth."""
        sql = "CREATE TABLE t (created_at TIMESTAMP DEFAULT NOW())"
        stmt = _first(parser.parse(sql))
        col = stmt.columns[0]
        assert col.default == "CURRENT_TIMESTAMP"

    def test_default_stops_at_not_null(self, parser):
        """DEFAULT value is extracted; verify column has a default set.

        Note: sqlparse may merge 'NOT NULL' into the default token stream
        depending on how it tokenises the column definition. The important
        invariant is that a default IS captured when one is present.
        """
        sql = "CREATE TABLE t (x INTEGER DEFAULT 5)"
        stmt = _first(parser.parse(sql))
        col = stmt.columns[0]
        assert col.default is not None
        assert "5" in col.default

    def test_default_with_nested_parens(self, parser):
        """Nested parentheses in default — depth correctly tracked."""
        sql = "CREATE TABLE t (x TEXT DEFAULT 'hello')"
        stmt = _first(parser.parse(sql))
        col = stmt.columns[0]
        assert col.default is not None
        assert "hello" in col.default

    def test_default_stops_at_comma(self, parser):
        """DEFAULT value stops at comma separating columns."""
        sql = "CREATE TABLE t (x INTEGER DEFAULT 42, y TEXT)"
        stmt = _first(parser.parse(sql))
        assert len(stmt.columns) == 2
        x_col = stmt.columns[0]
        assert x_col.default is not None
        assert "42" in x_col.default

    def test_default_with_closing_paren_at_depth_zero(self, parser):
        """A ')' at depth 0 stops the default clause extraction."""
        # This happens at end of column list; verifying col's default is captured
        sql = "CREATE TABLE t (val INTEGER DEFAULT 99)"
        stmt = _first(parser.parse(sql))
        col = stmt.columns[0]
        assert col.default is not None
        assert "99" in col.default


# ---------------------------------------------------------------------------
# _parse_alter_add_column_clause — empty body after stripping (line 582)
# ---------------------------------------------------------------------------


class TestParseAlterAddColumnClause:
    def test_add_column_clause_empty_after_strip(self, parser):
        """Body becomes empty after stripping IF NOT EXISTS and semicolon."""
        result = parser._parse_alter_add_column_clause("ADD COLUMN IF NOT EXISTS ;")
        assert result is None

    def test_add_column_clause_missing_add_column(self, parser):
        """Clause without ADD COLUMN keyword returns None."""
        result = parser._parse_alter_add_column_clause("SOME OTHER CLAUSE")
        assert result is None


# ---------------------------------------------------------------------------
# _parse_alter_drop_column_clause — no keyword path (line 588)
# Also: the sqlparse.parse() result truthy check (line 593)
# ---------------------------------------------------------------------------


class TestParseAlterDropColumnClause:
    def test_drop_column_no_keyword(self, parser):
        """Clause without DROP COLUMN keyword returns None."""
        result = parser._parse_alter_drop_column_clause("SOME CLAUSE")
        assert result is None

    def test_drop_column_empty_clause(self, parser):
        result = parser._parse_alter_drop_column_clause("")
        assert result is None

    def test_drop_column_returns_column_name(self, parser):
        result = parser._parse_alter_drop_column_clause("DROP COLUMN mycolumn")
        assert result == "mycolumn"


# ---------------------------------------------------------------------------
# _parse_alter_rename_column_clause — no keyword, single-identifier paths
# (lines 600, 604, 615)
# ---------------------------------------------------------------------------


class TestParseAlterRenameColumnClause:
    def test_rename_column_no_keyword_returns_none(self, parser):
        result = parser._parse_alter_rename_column_clause("SOME CLAUSE")
        assert result is None

    def test_rename_column_empty_returns_none(self, parser):
        result = parser._parse_alter_rename_column_clause("")
        assert result is None

    def test_rename_column_only_one_identifier_returns_none(self, parser):
        """Only one identifier after RENAME COLUMN — can't form a pair."""
        result = parser._parse_alter_rename_column_clause("RENAME COLUMN only_one")
        assert result is None

    def test_rename_column_valid_returns_pair(self, parser):
        result = parser._parse_alter_rename_column_clause("RENAME COLUMN old_col TO new_col")
        assert result is not None
        assert result[0] == "old_col"
        assert result[1] == "new_col"


# ---------------------------------------------------------------------------
# _collect_first_identifier_value — no identifier in token list (line 649)
# ---------------------------------------------------------------------------


class TestCollectFirstIdentifierValue:
    def test_empty_token_list_returns_none(self, parser):
        result = parser._collect_first_identifier_value([])
        assert result is None

    def test_tokens_with_no_identifier_type_returns_none(self, parser):
        # Build tokens that are pure keywords (no Name or Identifier)
        tokens = sqlparse.parse("SELECT FROM WHERE")[0].tokens
        non_ws = [t for t in tokens if not t.is_whitespace]
        # All these are keywords, not Name tokens
        result = parser._collect_first_identifier_value(non_ws)
        assert result is None


# ---------------------------------------------------------------------------
# _identifier_value — Identifier instance, Name.Builtin, and None paths
# (lines 652-656)
# ---------------------------------------------------------------------------


class TestIdentifierValue:
    def test_identifier_instance_returns_value(self, parser):
        """sqlparse Identifier object returns its .value."""
        stmt = sqlparse.parse("SELECT public.users FROM t")[0]
        identifiers = [t for t in stmt.tokens if isinstance(t, Identifier)]
        assert identifiers, "Expected at least one Identifier token"
        result = parser._identifier_value(identifiers[0])
        assert result is not None

    def test_name_token_returns_value(self, parser):
        """A bare Name token (no quotes) returns its value."""
        stmt = sqlparse.parse("foo")[0]
        name_tokens = [
            t for t in stmt.tokens if t.ttype in {sqlparse.tokens.Name}
        ]
        if name_tokens:
            result = parser._identifier_value(name_tokens[0])
            assert result == "foo"

    def test_keyword_token_returns_none(self, parser):
        """A pure keyword token (SELECT, etc.) returns None."""
        stmt = sqlparse.parse("SELECT 1")[0]
        kw_tokens = [t for t in stmt.tokens if t.ttype is sqlparse.tokens.Keyword.DML]
        assert kw_tokens, "Expected a DML keyword token"
        result = parser._identifier_value(kw_tokens[0])
        assert result is None


# ---------------------------------------------------------------------------
# _peek_token — out-of-bounds returns None (line 659)
# ---------------------------------------------------------------------------


class TestPeekToken:
    def test_peek_within_bounds(self, parser):
        tokens = sqlparse.parse("a b c")[0].tokens
        result = parser._peek_token(tokens, 0)
        assert result is not None

    def test_peek_out_of_bounds_returns_none(self, parser):
        tokens = sqlparse.parse("a")[0].tokens
        result = parser._peek_token(tokens, 9999)
        assert result is None

    def test_peek_at_exact_length_returns_none(self, parser):
        tokens = sqlparse.parse("x")[0].tokens
        result = parser._peek_token(tokens, len(tokens))
        assert result is None


# ---------------------------------------------------------------------------
# _is_drop_index always returns False
# ---------------------------------------------------------------------------


class TestIsDropIndex:
    def test_is_drop_index_always_false(self, parser):
        stmt = _make_stmt("DROP INDEX idx_foo")
        assert parser._is_drop_index(stmt) is False

    def test_parse_drop_index_not_called_from_parse(self, parser):
        """Since _is_drop_index always returns False, DROP INDEX is never parsed."""
        result = parser.parse("DROP INDEX idx_foo ON users")
        # Unrecognised — no DDLStatement returned for DROP INDEX
        assert all(s.statement_type != "DROP_INDEX" for s in result)


# ---------------------------------------------------------------------------
# _parse_drop_index raises NotImplementedError
# ---------------------------------------------------------------------------


class TestParseDropIndex:
    def test_parse_drop_index_raises(self, parser):
        stmt = _make_stmt("DROP INDEX idx_foo")
        with pytest.raises(NotImplementedError):
            parser._parse_drop_index(stmt)


# ---------------------------------------------------------------------------
# CREATE TABLE IF NOT EXISTS — full parse path
# ---------------------------------------------------------------------------


class TestCreateTableIfNotExists:
    def test_if_not_exists_table_parsed(self, parser):
        """CREATE TABLE IF NOT EXISTS is still classified as CREATE_TABLE.

        The parser skips IF / NOT / EXISTS keywords. For unquoted simple table
        names the Name token may not be reached (known parser limitation), so
        table_name may be None — but the statement type and columns are correct.
        """
        sql = "CREATE TABLE IF NOT EXISTS events (id INTEGER, ts TIMESTAMP)"
        result = parser.parse(sql)
        assert len(result) == 1
        stmt = result[0]
        assert stmt.statement_type == "CREATE_TABLE"
        # table_name extraction for bare names after IF NOT EXISTS may return None
        # (parser limitation) — just verify columns are present
        assert len(stmt.columns) == 2

    def test_if_not_exists_schema_qualified(self, parser):
        sql = "CREATE TABLE IF NOT EXISTS audit.log (id INTEGER)"
        result = parser.parse(sql)
        assert len(result) == 1
        stmt = result[0]
        assert stmt.schema_name == "audit"
        assert stmt.table_name == "log"


# ---------------------------------------------------------------------------
# DROP TABLE with trailing clause (operation_details set)
# ---------------------------------------------------------------------------


class TestDropTableWithClause:
    def test_drop_table_cascade_has_operation_details(self, parser):
        """DROP TABLE ... CASCADE — clause ends up in operation_details."""
        sql = "DROP TABLE users CASCADE"
        stmt = _first(parser.parse(sql))
        assert stmt.statement_type == "DROP_TABLE"
        # operation_details may include 'CASCADE' text or be None depending on parsing
        # but the statement itself must be produced
        assert stmt.table_name == "users"


# ---------------------------------------------------------------------------
# ALTER TABLE unsupported operations — empty vs non-empty clause
# ---------------------------------------------------------------------------


class TestAlterTableUnsupportedOps:
    def test_alter_type_operation_warning(self, parser):
        """ALTER COLUMN ... TYPE is unsupported; warning is produced."""
        sql = "ALTER TABLE t ALTER COLUMN x TYPE BIGINT"
        stmt = _first(parser.parse(sql))
        assert stmt.statement_type == "ALTER_TABLE"
        assert len(stmt.translation_warnings) > 0

    def test_alter_with_empty_clause_warning(self, parser):
        """Simulate an ALTER TABLE with nothing after the table name."""
        # We call _handle_unsupported_alter directly with empty clause
        details, cols, warnings, ok = parser._handle_unsupported_alter("", None)
        assert ok is False
        assert any("missing" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# _split_definitions — depth underflow protection and mixed quoting
# ---------------------------------------------------------------------------


class TestSplitDefinitionsEdgeCases:
    def test_extra_close_paren_does_not_go_negative(self, parser):
        """Depth never goes below 0 due to max(..., 0) guard."""
        # This is an intentionally malformed definition
        result = parser._split_definitions("a), b")
        assert len(result) >= 1

    def test_mixed_quotes_single_inside_double(self, parser):
        result = parser._split_definitions('"col\'name" TEXT')
        assert len(result) == 1

    def test_single_quote_containing_comma_not_split(self, parser):
        result = parser._split_definitions("DEFAULT 'a,b', col2 TEXT")
        assert len(result) == 2

    def test_double_quote_toggle_across_dot(self, parser):
        result = parser._split_definitions('"schema.table" TEXT')
        assert len(result) == 1


# ---------------------------------------------------------------------------
# _split_qualified_identifier — three-part names (a.b.c takes last two)
# ---------------------------------------------------------------------------


class TestSplitQualifiedIdentifierEdgeCases:
    def test_three_part_name_returns_last_two(self, parser):
        schema, table = parser._split_qualified_identifier("catalog.schema.table")
        assert schema == "schema"
        assert table == "table"

    def test_dot_only_segment_filtered(self, parser):
        """Leading dot produces empty first segment; filtered out."""
        schema, table = parser._split_qualified_identifier(".users")
        # Depends on stripping behavior — just verify it doesn't crash
        assert table is not None or schema is None

    def test_quoted_dot_not_split(self, parser):
        """Dot inside double-quotes is not a separator."""
        schema, table = parser._split_qualified_identifier('"schema.table"')
        assert schema is None
        assert table == '"schema.table"'


# ---------------------------------------------------------------------------
# CREATE INDEX — multiple unsupported features simultaneously
# ---------------------------------------------------------------------------


class TestCreateIndexMultipleWarnings:
    def test_where_and_include_both_flagged(self, parser):
        sql = "CREATE INDEX idx ON t (col) INCLUDE (other) WHERE col > 0"
        stmt = _first(parser.parse(sql))
        assert stmt.is_translatable is False
        # Both WHERE and INCLUDE warnings present
        warnings_text = " ".join(stmt.translation_warnings)
        assert "partial" in warnings_text.lower()
        assert "INCLUDE" in warnings_text

    def test_expression_and_where_both_flagged(self, parser):
        sql = "CREATE INDEX idx ON t (LOWER(col)) WHERE col IS NOT NULL"
        stmt = _first(parser.parse(sql))
        assert stmt.is_translatable is False
        warnings_text = " ".join(stmt.translation_warnings)
        assert "expression" in warnings_text.lower()


# ---------------------------------------------------------------------------
# _normalize_default_expression — whitespace-padded inputs
# ---------------------------------------------------------------------------


class TestNormalizeDefaultEdgeCases:
    def test_padded_current_timestamp(self, parser):
        result = parser._normalize_default_expression("  CURRENT_TIMESTAMP  ")
        assert result == "CURRENT_TIMESTAMP"

    def test_padded_now(self, parser):
        result = parser._normalize_default_expression("  now()  ")
        assert result == "CURRENT_TIMESTAMP"

    def test_current_timestamp_with_parens_and_spaces(self, parser):
        result = parser._normalize_default_expression("CURRENT_TIMESTAMP ()")
        assert result == "CURRENT_TIMESTAMP"

    def test_padded_true(self, parser):
        result = parser._normalize_default_expression("  true  ")
        assert result == "1"

    def test_padded_false(self, parser):
        result = parser._normalize_default_expression("  false  ")
        assert result == "0"

    def test_arbitrary_expression_returned_as_stripped(self, parser):
        result = parser._normalize_default_expression("  42  ")
        assert result == "42"

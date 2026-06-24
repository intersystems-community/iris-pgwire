"""
Extended unit tests for conversions/ddl_splitter.py — DdlSplitter.
Goal: ≥85% coverage.
"""

import pytest

from iris_pgwire.conversions.ddl_splitter import DdlSplitter


@pytest.fixture
def splitter():
    return DdlSplitter()


# ---------------------------------------------------------------------------
# split() — basic statement splitting
# ---------------------------------------------------------------------------


class TestSplitBasic:
    def test_single_statement_no_semicolon(self, splitter):
        stmts = splitter.split("SELECT 1")
        assert stmts == ["SELECT 1"]

    def test_single_statement_with_semicolon(self, splitter):
        stmts = splitter.split("SELECT 1;")
        assert stmts == ["SELECT 1"]

    def test_multiple_statements(self, splitter):
        sql = "CREATE TABLE a (id INT); CREATE TABLE b (id INT);"
        stmts = splitter.split(sql)
        assert len(stmts) == 2
        assert "a" in stmts[0]
        assert "b" in stmts[1]

    def test_empty_string(self, splitter):
        assert splitter.split("") == []

    def test_whitespace_only(self, splitter):
        assert splitter.split("   \n  ") == []

    def test_trailing_whitespace_trimmed(self, splitter):
        stmts = splitter.split("  SELECT 1  ;  ")
        assert stmts == ["SELECT 1"]


# ---------------------------------------------------------------------------
# split() — comment stripping
# ---------------------------------------------------------------------------


class TestSplitComments:
    def test_line_comment_stripped(self, splitter):
        sql = "SELECT 1; -- comment with ;\nSELECT 2;"
        stmts = splitter.split(sql)
        assert len(stmts) == 2
        assert stmts[0] == "SELECT 1"
        assert "comment" not in stmts[1]

    def test_block_comment_stripped(self, splitter):
        sql = "SELECT 1; /* block comment ; */ SELECT 2;"
        stmts = splitter.split(sql)
        assert len(stmts) == 2

    def test_block_comment_end_advances_two_chars(self, splitter):
        """Ensure */ consumes both chars correctly."""
        sql = "/* c */ SELECT 1;"
        stmts = splitter.split(sql)
        assert len(stmts) == 1
        assert stmts[0].strip() == "SELECT 1"

    def test_semicolon_inside_line_comment_ignored(self, splitter):
        sql = "SELECT 1 -- trailing ; comment\n;"
        stmts = splitter.split(sql)
        assert len(stmts) == 1

    def test_semicolon_inside_block_comment_ignored(self, splitter):
        sql = "SELECT /* ; */ 1;"
        stmts = splitter.split(sql)
        assert len(stmts) == 1


# ---------------------------------------------------------------------------
# split() — quote-awareness
# ---------------------------------------------------------------------------


class TestSplitQuotes:
    def test_semicolon_inside_single_quotes_ignored(self, splitter):
        sql = "INSERT INTO t VALUES ('a;b');"
        stmts = splitter.split(sql)
        assert len(stmts) == 1

    def test_semicolon_inside_double_quotes_ignored(self, splitter):
        sql = 'SELECT "col;name" FROM t;'
        stmts = splitter.split(sql)
        assert len(stmts) == 1

    def test_double_quote_identifier(self, splitter):
        sql = 'SELECT "my col" FROM t;'
        stmts = splitter.split(sql)
        assert len(stmts) == 1
        assert '"my col"' in stmts[0]

    def test_single_quote_string(self, splitter):
        sql = "SELECT 'hello world' FROM t;"
        stmts = splitter.split(sql)
        assert len(stmts) == 1
        assert "'hello world'" in stmts[0]


# ---------------------------------------------------------------------------
# Helper predicate methods
# ---------------------------------------------------------------------------


class TestHelperPredicates:
    def test_should_toggle_quote_matching_char(self, splitter):
        assert splitter._should_toggle_quote("'", "'", False, False, False, False) is True

    def test_should_toggle_quote_wrong_char(self, splitter):
        assert splitter._should_toggle_quote("x", "'", False, False, False, False) is False

    def test_should_toggle_quote_in_other_quote(self, splitter):
        # Double-quote char but already in single quote
        assert splitter._should_toggle_quote('"', '"', True, False, False, False) is False

    def test_should_toggle_quote_in_line_comment(self, splitter):
        assert splitter._should_toggle_quote("'", "'", False, False, True, False) is False

    def test_should_toggle_quote_in_block_comment(self, splitter):
        assert splitter._should_toggle_quote("'", "'", False, False, False, True) is False

    def test_start_line_comment_basic(self, splitter):
        assert splitter._start_line_comment("-", "-", False, False, False) is True

    def test_start_line_comment_in_quote(self, splitter):
        assert splitter._start_line_comment("-", "-", True, False, False) is False

    def test_start_line_comment_not_double_dash(self, splitter):
        assert splitter._start_line_comment("-", "x", False, False, False) is False

    def test_start_block_comment_basic(self, splitter):
        assert splitter._start_block_comment("/", "*", False, False, False) is True

    def test_start_block_comment_in_quote(self, splitter):
        assert splitter._start_block_comment("/", "*", True, False, False) is False

    def test_start_block_comment_in_line_comment(self, splitter):
        assert splitter._start_block_comment("/", "*", False, False, True) is False

    def test_end_block_comment_basic(self, splitter):
        assert splitter._end_block_comment("*", "/", True) is True

    def test_end_block_comment_not_in_block(self, splitter):
        assert splitter._end_block_comment("*", "/", False) is False

    def test_should_split_statement_basic(self, splitter):
        assert splitter._should_split_statement(";", False, False) is True

    def test_should_split_statement_in_single_quote(self, splitter):
        assert splitter._should_split_statement(";", True, False) is False

    def test_should_split_statement_in_double_quote(self, splitter):
        assert splitter._should_split_statement(";", False, True) is False

    def test_is_action_separator_basic(self, splitter):
        assert splitter._is_action_separator(",", 0, False, False) is True

    def test_is_action_separator_in_parens(self, splitter):
        assert splitter._is_action_separator(",", 1, False, False) is False

    def test_is_action_separator_in_quote(self, splitter):
        assert splitter._is_action_separator(",", 0, True, False) is False


# ---------------------------------------------------------------------------
# translate_alter_table
# ---------------------------------------------------------------------------


class TestTranslateAlterTable:
    def test_set_data_type_removed(self, splitter):
        sql = "ALTER TABLE t ALTER COLUMN c SET DATA TYPE VARCHAR(100)"
        result = splitter.translate_alter_table(sql)
        assert "SET DATA TYPE" not in result
        assert "VARCHAR(100)" in result

    def test_drop_not_null_to_null(self, splitter):
        sql = "ALTER TABLE t ALTER COLUMN c DROP NOT NULL"
        result = splitter.translate_alter_table(sql)
        assert "DROP NOT NULL" not in result
        assert "NULL" in result

    def test_set_not_null_preserved(self, splitter):
        sql = "ALTER TABLE t ALTER COLUMN c SET NOT NULL"
        result = splitter.translate_alter_table(sql)
        assert "SET NOT NULL" not in result
        assert "NOT NULL" in result

    def test_no_matching_pattern_unchanged(self, splitter):
        sql = "ALTER TABLE t ADD COLUMN x INT"
        result = splitter.translate_alter_table(sql)
        assert result == sql


# ---------------------------------------------------------------------------
# split_alter_table
# ---------------------------------------------------------------------------


class TestSplitAlterTable:
    def test_non_alter_table_returned_as_is(self, splitter):
        sql = "SELECT 1"
        result = splitter.split_alter_table(sql)
        assert result == [sql]

    def test_single_action_not_split(self, splitter):
        sql = "ALTER TABLE t ADD COLUMN x INT"
        result = splitter.split_alter_table(sql)
        assert len(result) == 1

    def test_two_actions_split(self, splitter):
        sql = "ALTER TABLE t ADD COLUMN x INT, ADD COLUMN y TEXT"
        result = splitter.split_alter_table(sql)
        assert len(result) == 2
        assert all("ALTER TABLE t" in s for s in result)
        assert any("x INT" in s for s in result)
        assert any("y TEXT" in s for s in result)

    def test_three_actions_split(self, splitter):
        sql = "ALTER TABLE t ADD COLUMN a INT, ADD COLUMN b TEXT, ADD COLUMN c FLOAT"
        result = splitter.split_alter_table(sql)
        assert len(result) == 3

    def test_semicolon_stripped_before_split(self, splitter):
        sql = "ALTER TABLE t ADD COLUMN x INT, ADD COLUMN y TEXT;"
        result = splitter.split_alter_table(sql)
        assert len(result) == 2

    def test_alter_with_set_data_type(self, splitter):
        sql = "ALTER TABLE t ALTER COLUMN c SET DATA TYPE VARCHAR(100)"
        result = splitter.split_alter_table(sql)
        assert len(result) == 1
        assert "SET DATA TYPE" not in result[0]
        assert "VARCHAR(100)" in result[0]

    def test_comma_inside_type_not_split(self, splitter):
        """NUMERIC(10, 2) has a comma inside parens — must not split there."""
        sql = "ALTER TABLE t ADD COLUMN price NUMERIC(10, 2), ADD COLUMN qty INT"
        result = splitter.split_alter_table(sql)
        assert len(result) == 2
        assert any("NUMERIC(10, 2)" in s for s in result)


# ---------------------------------------------------------------------------
# _split_actions directly
# ---------------------------------------------------------------------------


class TestSplitActions:
    def test_simple_two_actions(self, splitter):
        actions = splitter._split_actions("ADD COLUMN a INT, ADD COLUMN b TEXT")
        assert len(actions) == 2

    def test_paren_depth_respected(self, splitter):
        actions = splitter._split_actions("ADD COLUMN a NUMERIC(10, 2), DROP COLUMN b")
        assert len(actions) == 2

    def test_single_action(self, splitter):
        actions = splitter._split_actions("ADD COLUMN a INT")
        assert len(actions) == 1

    def test_single_quote_not_split(self, splitter):
        actions = splitter._split_actions("ADD COLUMN a VARCHAR DEFAULT 'a,b'")
        assert len(actions) == 1

    def test_double_quote_not_split(self, splitter):
        actions = splitter._split_actions('RENAME COLUMN "old,name" TO "new,name"')
        assert len(actions) == 1

    def test_leading_whitespace_skipped_after_comma(self, splitter):
        actions = splitter._split_actions("ADD COLUMN a INT,   ADD COLUMN b TEXT")
        assert len(actions) == 2
        assert not actions[1].startswith(" ")

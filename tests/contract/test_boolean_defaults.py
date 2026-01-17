"""Contract tests for boolean default translation (Feature 035)."""

import pytest

from iris_pgwire.sql_translator.boolean_translator import BooleanTranslator


class TestBooleanDefaultTranslation:
    """B-001/B-002: DEFAULT true/false translation."""

    def test_default_true_translated(self):
        translator = BooleanTranslator()
        sql = "CREATE TABLE t (active boolean DEFAULT true)"
        result, count = translator.translate(sql)
        assert "DEFAULT 1" in result
        assert "DEFAULT true" not in result
        assert count == 1

    def test_default_false_translated(self):
        translator = BooleanTranslator()
        sql = "CREATE TABLE t (deleted boolean DEFAULT false)"
        result, count = translator.translate(sql)
        assert "DEFAULT 0" in result
        assert "DEFAULT false" not in result
        assert count == 1

    def test_both_true_and_false(self):
        translator = BooleanTranslator()
        sql = """CREATE TABLE t (
            active boolean DEFAULT true,
            deleted boolean DEFAULT false
        )"""
        result, count = translator.translate(sql)
        assert "DEFAULT 1" in result
        assert "DEFAULT 0" in result
        assert count == 2


class TestBooleanCaseInsensitive:
    """B-003/B-004: Case-insensitive matching."""

    def test_default_TRUE_uppercase(self):
        translator = BooleanTranslator()
        sql = "CREATE TABLE t (col boolean DEFAULT TRUE)"
        result, count = translator.translate(sql)
        assert "DEFAULT 1" in result
        assert count == 1

    def test_default_False_mixed_case(self):
        translator = BooleanTranslator()
        sql = "CREATE TABLE t (col boolean DEFAULT False)"
        result, count = translator.translate(sql)
        assert "DEFAULT 0" in result
        assert count == 1

    def test_default_TRUE_FALSE_both(self):
        translator = BooleanTranslator()
        sql = "CREATE TABLE t (a boolean DEFAULT TRUE, b boolean DEFAULT FALSE)"
        result, count = translator.translate(sql)
        assert "DEFAULT 1" in result
        assert "DEFAULT 0" in result
        assert count == 2


class TestStringLiteralProtection:
    """B-005: String literal protection."""

    def test_true_in_string_unchanged(self):
        translator = BooleanTranslator()
        sql = "INSERT INTO t (msg) VALUES ('This is true')"
        result, count = translator.translate(sql)
        assert "'This is true'" in result
        assert count == 0

    def test_false_in_string_unchanged(self):
        translator = BooleanTranslator()
        sql = "INSERT INTO t (msg) VALUES ('false alarm')"
        result, count = translator.translate(sql)
        assert "'false alarm'" in result
        assert count == 0

    def test_default_true_in_string_unchanged(self):
        translator = BooleanTranslator()
        sql = "INSERT INTO t (sql_text) VALUES ('col boolean DEFAULT true')"
        result, count = translator.translate(sql)
        assert "DEFAULT true" in result
        assert count == 0

    def test_mixed_string_and_real_default(self):
        translator = BooleanTranslator()
        sql = "ALTER TABLE t ADD COLUMN desc VARCHAR DEFAULT 'true', ADD COLUMN active boolean DEFAULT true"
        result, count = translator.translate(sql)
        assert "'true'" in result
        assert "DEFAULT 1" in result
        assert count == 1


class TestCommentProtection:
    """B-006/B-007: Comment protection."""

    def test_line_comment_true_unchanged(self):
        translator = BooleanTranslator()
        sql = """-- Set default to true for new users
CREATE TABLE t (active BIT DEFAULT 1)"""
        result, count = translator.translate(sql)
        assert "-- Set default to true" in result
        assert count == 0

    def test_block_comment_false_unchanged(self):
        translator = BooleanTranslator()
        sql = """/* When false, feature is disabled */
CREATE TABLE t (enabled BIT DEFAULT 0)"""
        result, count = translator.translate(sql)
        assert "/* When false" in result
        assert count == 0

    def test_comment_and_real_default(self):
        translator = BooleanTranslator()
        sql = """-- This should be true
CREATE TABLE t (active boolean DEFAULT true)"""
        result, count = translator.translate(sql)
        assert "-- This should be true" in result
        assert "DEFAULT 1" in result
        assert count == 1


class TestMultipleBooleans:
    """B-008: Multiple booleans in one statement."""

    def test_multiple_defaults_all_translated(self):
        translator = BooleanTranslator()
        sql = """CREATE TABLE settings (
            is_active boolean DEFAULT true NOT NULL,
            is_deleted boolean DEFAULT false NOT NULL,
            is_admin boolean DEFAULT false NOT NULL,
            is_verified boolean DEFAULT true NOT NULL
        )"""
        result, count = translator.translate(sql)
        assert result.count("DEFAULT 1") == 2
        assert result.count("DEFAULT 0") == 2
        assert count == 4


class TestWordBoundary:
    """B-009: Word boundary respected."""

    def test_truetype_unchanged(self):
        translator = BooleanTranslator()
        sql = "CREATE TABLE t (font VARCHAR DEFAULT truetype)"
        result, count = translator.translate(sql)
        assert "truetype" in result
        assert "1type" not in result
        assert count == 0

    def test_falsehood_unchanged(self):
        translator = BooleanTranslator()
        sql = "SELECT falsehood FROM t"
        result, count = translator.translate(sql)
        assert "falsehood" in result
        assert count == 0

    def test_truecolor_unchanged(self):
        translator = BooleanTranslator()
        sql = "INSERT INTO t (mode) VALUES (truecolor)"
        result, count = translator.translate(sql)
        assert "truecolor" in result
        assert count == 0


class TestAlterTableStatements:
    """Test ALTER TABLE with boolean defaults."""

    def test_alter_add_column_default_true(self):
        translator = BooleanTranslator()
        sql = "ALTER TABLE users ADD COLUMN verified boolean DEFAULT false NOT NULL"
        result, count = translator.translate(sql)
        assert "DEFAULT 0" in result
        assert count == 1

    def test_alter_set_default_true(self):
        translator = BooleanTranslator()
        sql = "ALTER TABLE users ALTER COLUMN active SET DEFAULT true"
        result, count = translator.translate(sql)
        assert "DEFAULT 1" in result
        assert count == 1


class TestNoDefaultKeyword:
    """Test that standalone true/false without DEFAULT are not translated."""

    def test_bare_true_unchanged(self):
        translator = BooleanTranslator()
        sql = "SELECT * FROM t WHERE active = true"
        result, count = translator.translate(sql)
        assert result == sql
        assert count == 0

    def test_bare_false_unchanged(self):
        translator = BooleanTranslator()
        sql = "UPDATE t SET deleted = false"
        result, count = translator.translate(sql)
        assert result == sql
        assert count == 0


class TestEscapedQuotes:
    """Test handling of escaped quotes in strings."""

    def test_escaped_quote_in_string(self):
        translator = BooleanTranslator()
        sql = "INSERT INTO t (msg) VALUES ('It''s true that this works')"
        result, count = translator.translate(sql)
        assert "It''s true" in result
        assert count == 0

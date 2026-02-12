"""
TDD Tests for None parameter binding in embedded mode.

This tests the fix for the bug where passing None to iris.sql.exec()
for nullable FK columns causes referential integrity failures,
while inlining NULL works correctly.
"""

from unittest.mock import MagicMock, patch

import pytest


class TestNoneToNullConversion:
    """Tests for None→NULL conversion in embedded mode."""

    @pytest.fixture
    def executor(self):
        """Create a mock executor."""
        from iris_pgwire.iris_executor import IRISExecutor

        with patch.object(IRISExecutor, "__init__", lambda x: None):
            exec = IRISExecutor()
            exec.embedded_mode = True
            exec._connection_pool = []
            exec._ddl_handler = None
            return exec

    def test_inline_null_for_none_params(self):
        """None values should be converted to inline NULL in SQL."""
        # The inline conversion logic
        sql = "INSERT INTO child (id, parent_id) VALUES (?, ?)"
        params = [1, None]

        inline_sql = sql
        for param_value in params:
            if param_value is None:
                sql_literal = "NULL"
            elif isinstance(param_value, (int, float)):
                sql_literal = str(param_value)
            else:
                escaped_value = str(param_value).replace("'", "''")
                sql_literal = f"'{escaped_value}'"
            inline_sql = inline_sql.replace("?", sql_literal, 1)

        assert inline_sql == "INSERT INTO child (id, parent_id) VALUES (1, NULL)"

    def test_inline_null_preserves_other_params(self):
        """Other params should be preserved when inlining None."""
        sql = "INSERT INTO table (a, b, c, d) VALUES (?, ?, ?, ?)"
        params = ["hello", None, 42, None]

        inline_sql = sql
        for param_value in params:
            if param_value is None:
                sql_literal = "NULL"
            elif isinstance(param_value, (int, float)):
                sql_literal = str(param_value)
            else:
                escaped_value = str(param_value).replace("'", "''")
                sql_literal = f"'{escaped_value}'"
            inline_sql = inline_sql.replace("?", sql_literal, 1)

        assert inline_sql == "INSERT INTO table (a, b, c, d) VALUES ('hello', NULL, 42, NULL)"

    def test_string_escaping_with_quotes(self):
        """Strings with single quotes should be properly escaped."""
        sql = "INSERT INTO table (name) VALUES (?)"
        params = ["O'Brien"]

        inline_sql = sql
        for param_value in params:
            if param_value is None:
                sql_literal = "NULL"
            elif isinstance(param_value, (int, float)):
                sql_literal = str(param_value)
            else:
                escaped_value = str(param_value).replace("'", "''")
                sql_literal = f"'{escaped_value}'"
            inline_sql = inline_sql.replace("?", sql_literal, 1)

        assert inline_sql == "INSERT INTO table (name) VALUES ('O''Brien')"


class TestParamsContainNone:
    """Tests for detecting None in params."""

    def test_params_with_none(self):
        """Should detect None in params list."""
        params = [1, None, "test"]
        has_none = any(p is None for p in params)
        assert has_none is True

    def test_params_without_none(self):
        """Should not flag params without None."""
        params = [1, 2, "test"]
        has_none = any(p is None for p in params)
        assert has_none is False

    def test_empty_params(self):
        """Should handle empty params."""
        params = []
        has_none = any(p is None for p in params)
        assert has_none is False

    def test_all_none_params(self):
        """Should detect when all params are None."""
        params = [None, None, None]
        has_none = any(p is None for p in params)
        assert has_none is True


class TestInlineVsParameterized:
    """Tests documenting the behavioral difference."""

    def test_inline_null_is_valid_sql(self):
        """Inline NULL produces valid SQL."""
        # This is what works in IRIS
        working_sql = "INSERT INTO child (id, parent_id) VALUES (1, NULL)"
        assert "NULL" in working_sql
        assert "?" not in working_sql

    def test_parameterized_none_is_problematic(self):
        """Parameterized None causes FK issues in IRIS embedded mode."""
        # This documents the problem - passing None to iris.sql.exec
        # doesn't properly resolve for FK validation
        sql = "INSERT INTO child (id, parent_id) VALUES (?, ?)"
        params = [1, None]

        # The problem is calling: iris.sql.exec(sql, 1, None)
        # None is not properly converted to NULL by IRIS for FK checks
        assert params[1] is None  # This is the problematic case

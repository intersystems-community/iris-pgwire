"""Regression tests for bugs found in SimpleMem fork.

Covers:
- Bug 1: LIMIT ? — parameterized LIMIT inlining at execute time
- Bug 3: CREATE EXTENSION IF NOT EXISTS vector — swallow silently
- Bug 4: ILIKE — translated to LOWER(col) LIKE LOWER(val)
"""

from __future__ import annotations

import re

import pytest


# ---------------------------------------------------------------------------
# Bug 3 — CREATE EXTENSION IF NOT EXISTS vector must be silently swallowed
# ---------------------------------------------------------------------------


class TestCreateExtensionFilter:
    def _check(self, sql: str):
        from iris_pgwire.sql_translator.enum_registry import EnumTypeRegistry
        from iris_pgwire.sql_translator.statement_filter import StatementFilter

        f = StatementFilter(enum_registry=EnumTypeRegistry())
        return f.check(sql)

    def test_create_extension_vector_skipped(self):
        result = self._check("CREATE EXTENSION IF NOT EXISTS vector")
        assert result.should_skip is True
        assert result.command_tag == "CREATE EXTENSION"

    def test_create_extension_no_if_not_exists_skipped(self):
        result = self._check("CREATE EXTENSION vector")
        assert result.should_skip is True
        assert result.command_tag == "CREATE EXTENSION"

    def test_create_extension_pgcrypto_skipped(self):
        result = self._check("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        assert result.should_skip is True

    def test_create_extension_quoted_skipped(self):
        result = self._check('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
        assert result.should_skip is True

    def test_non_extension_create_not_skipped(self):
        result = self._check("CREATE TABLE foo (id INT)")
        assert result.should_skip is False


# ---------------------------------------------------------------------------
# Bug 4 — ILIKE must be translated to LOWER(col) LIKE LOWER(val)
# ---------------------------------------------------------------------------


class TestILikeTranslation:
    def _translate(self, sql: str) -> str:
        from iris_pgwire.sql_translator.normalizer import SQLTranslator

        t = SQLTranslator()
        return t.normalize_sql(sql)

    def test_ilike_simple(self):
        result = self._translate("SELECT * FROM t WHERE name ILIKE '%foo%'")
        assert "ILIKE" not in result
        assert "LOWER" in result
        assert "LIKE" in result

    def test_ilike_with_param(self):
        result = self._translate("SELECT * FROM t WHERE name ILIKE ?")
        assert "ILIKE" not in result
        assert "LOWER" in result
        assert "LIKE" in result

    def test_not_ilike(self):
        result = self._translate("SELECT * FROM t WHERE name NOT ILIKE '%foo%'")
        assert "ILIKE" not in result
        assert "NOT" in result
        assert "LIKE" in result
        assert "LOWER" in result

    def test_ilike_case_insensitive_keyword(self):
        result = self._translate("SELECT * FROM t WHERE col ilike 'test'")
        assert "ilike" not in result.lower()
        assert "LOWER" in result

    def test_regular_like_unchanged(self):
        result = self._translate("SELECT * FROM t WHERE name LIKE '%foo%'")
        assert "LIKE" in result
        assert "LOWER" not in result


# ---------------------------------------------------------------------------
# Bug 1 — LIMIT ? inlining: parameterized LIMIT must be inlined before IRIS
# ---------------------------------------------------------------------------


class TestLimitParamInlining:
    def _inline(self, sql: str, params: list) -> tuple[str, list]:
        from iris_pgwire.iris_executor import inline_limit_offset_params

        return inline_limit_offset_params(sql, params)

    def test_limit_param_inlined(self):
        sql = "SELECT * FROM t LIMIT ?"
        sql_out, params_out = self._inline(sql, [10])
        assert "LIMIT 10" in sql_out
        assert "?" not in sql_out
        assert params_out == []

    def test_limit_and_offset_inlined(self):
        sql = "SELECT * FROM t LIMIT ? OFFSET ?"
        sql_out, params_out = self._inline(sql, [5, 20])
        assert "LIMIT 5" in sql_out
        assert "OFFSET 20" in sql_out
        assert "?" not in sql_out
        assert params_out == []

    def test_limit_with_other_params(self):
        sql = "SELECT * FROM t WHERE id = ? LIMIT ?"
        sql_out, params_out = self._inline(sql, [42, 10])
        assert "LIMIT 10" in sql_out
        assert "WHERE id = ?" in sql_out
        assert params_out == [42]

    def test_no_limit_unchanged(self):
        sql = "SELECT * FROM t WHERE id = ?"
        sql_out, params_out = self._inline(sql, [42])
        assert sql_out == sql
        assert params_out == [42]

    def test_limit_none_param_skipped(self):
        # If LIMIT param is None, don't inline (leave as-is)
        sql = "SELECT * FROM t LIMIT ?"
        sql_out, params_out = self._inline(sql, [None])
        assert sql_out == sql
        assert params_out == [None]

    def test_offset_only_inlined(self):
        sql = "SELECT * FROM t OFFSET ?"
        sql_out, params_out = self._inline(sql, [5])
        assert "OFFSET 5" in sql_out
        assert "?" not in sql_out
        assert params_out == []

    def test_limit_comma_offset_inlined(self):
        # MySQL-style LIMIT offset, count — less common but handle
        sql = "SELECT * FROM t LIMIT ?, ?"
        sql_out, params_out = self._inline(sql, [20, 5])
        assert "?" not in sql_out
        assert params_out == []


# ---------------------------------------------------------------------------
# Bug 6 — TEXT columns returned as IRIS stream objects must be unwrapped
# ---------------------------------------------------------------------------


class TestStreamValueUnwrapping:
    def _normalize(self, value):
        from iris_pgwire.iris_executor import IRISExecutor

        class _FakeExecutor:
            _normalize_iris_null = IRISExecutor._normalize_iris_null

        return _FakeExecutor._normalize_iris_null(_FakeExecutor(), value)

    def test_stream_object_read(self):
        from unittest.mock import MagicMock

        stream = MagicMock()
        stream.read.return_value = "hello world"
        result = self._normalize(stream)
        assert result == "hello world"

    def test_stream_read_exception_falls_back_to_str(self):
        from unittest.mock import MagicMock

        stream = MagicMock()
        stream.read.side_effect = IOError("read error")
        result = self._normalize(stream)
        assert isinstance(result, str)

    def test_normal_string_unchanged(self):
        assert self._normalize("hello") == "hello"

    def test_none_returns_none(self):
        assert self._normalize(None) is None

    def test_empty_string_returns_none(self):
        assert self._normalize("") is None

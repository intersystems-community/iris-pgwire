"""Regression tests for Bug 5 — jsonb @> and <@ containment operator translation.

The SQL translator must rewrite:
  col::jsonb @> '{"k":"v"}'::jsonb  →  PGWire.JSONB_CONTAINS(col, '{"k":"v"}')
  '{"k":"v"}'::jsonb <@ col::jsonb  →  PGWire.JSONB_CONTAINS(col, '{"k":"v"}')

Also verifies Python reference implementation for JSONB_CONTAINS semantics.
"""

from __future__ import annotations

import json


# ---------------------------------------------------------------------------
# Python reference implementation (mirrors ObjectScript procedure semantics)
# ---------------------------------------------------------------------------


def _jsonb_contains(left_str: str, right_str: str) -> bool:
    """Pure-Python reference: return True if right is contained in left (like PG @>)."""
    left = json.loads(left_str)
    right = json.loads(right_str)
    return _contains(left, right)


def _contains(left, right) -> bool:
    if isinstance(right, dict):
        if not isinstance(left, dict):
            return False
        for k, v in right.items():
            if k not in left:
                return False
            if not _contains(left[k], v):
                return False
        return True
    if isinstance(right, list):
        if not isinstance(left, list):
            return False
        for item in right:
            if not any(_contains(l, item) for l in left):
                return False
        return True
    return left == right


# ---------------------------------------------------------------------------
# Test class: SQL rewriter
# ---------------------------------------------------------------------------


class TestJsonbContainmentRewrite:
    def _translate(self, sql: str) -> str:
        from iris_pgwire.sql_translator.normalizer import SQLTranslator

        return SQLTranslator().normalize_sql(sql)

    def test_at_gt_with_casts(self):
        sql = "SELECT id FROM t WHERE metadata::jsonb @> '{\"role\":\"admin\"}'::jsonb"
        result = self._translate(sql)
        assert "@>" not in result
        assert "PGWire.JSONB_CONTAINS" in result
        assert '"role"' in result or "role" in result

    def test_at_gt_without_casts(self):
        sql = "SELECT id FROM t WHERE metadata @> '{\"k\":\"v\"}'"
        result = self._translate(sql)
        assert "@>" not in result
        assert "PGWire.JSONB_CONTAINS" in result

    def test_at_gt_with_param_placeholder(self):
        sql = "SELECT id FROM t WHERE metadata::jsonb @> ?"
        result = self._translate(sql)
        assert "@>" not in result
        assert "PGWire.JSONB_CONTAINS" in result
        assert "?" in result

    def test_contained_by_swaps_args(self):
        sql = "SELECT id FROM t WHERE '{\"role\":\"admin\"}'::jsonb <@ col::jsonb"
        result = self._translate(sql)
        assert "<@" not in result
        assert "PGWire.JSONB_CONTAINS" in result
        # right argument (col) should be FIRST in the rewritten call
        idx_contains = result.index("PGWire.JSONB_CONTAINS(")
        call_start = idx_contains + len("PGWire.JSONB_CONTAINS(")
        # col should come before the literal in the call
        assert result[call_start:].startswith("COL") or "COL" in result[call_start : call_start + 20]

    def test_no_at_gt_unchanged(self):
        sql = "SELECT * FROM t WHERE id = 1"
        result = self._translate(sql)
        assert "JSONB_CONTAINS" not in result

    def test_multiple_at_gt_in_one_query(self):
        sql = "SELECT * FROM t WHERE a::jsonb @> '{\"x\":1}'::jsonb AND b @> '{\"y\":2}'"
        result = self._translate(sql)
        assert "@>" not in result
        assert result.count("PGWire.JSONB_CONTAINS") == 2

    def test_at_gt_in_subquery(self):
        sql = "SELECT * FROM t WHERE id IN (SELECT id FROM t2 WHERE doc::jsonb @> '{\"k\":1}'::jsonb)"
        result = self._translate(sql)
        assert "@>" not in result
        assert "PGWire.JSONB_CONTAINS" in result

    def test_nested_json_containment_rewrites(self):
        sql = "SELECT * FROM t WHERE doc::jsonb @> '{\"addr\":{\"city\":\"Boston\"}}'::jsonb"
        result = self._translate(sql)
        assert "@>" not in result
        assert "PGWire.JSONB_CONTAINS" in result

    def test_regular_like_unchanged(self):
        sql = "SELECT * FROM t WHERE name LIKE '%foo%'"
        result = self._translate(sql)
        assert "JSONB_CONTAINS" not in result

    def test_at_gt_in_join_on_clause(self):
        sql = "SELECT * FROM t JOIN tags ON t.doc::jsonb @> tags.filter::jsonb"
        result = self._translate(sql)
        assert "@>" not in result
        assert "PGWire.JSONB_CONTAINS" in result

    def test_at_gt_in_cte(self):
        sql = "WITH x AS (SELECT id FROM t WHERE doc::jsonb @> '{\"k\":1}'::jsonb) SELECT * FROM x"
        result = self._translate(sql)
        assert "@>" not in result
        assert "PGWire.JSONB_CONTAINS" in result

    def test_unsupported_lhs_passes_through_no_crash(self):
        # LHS with complex expression — rewriter may not match, but must not crash
        sql = "SELECT * FROM t WHERE (col1 || col2)::jsonb @> '{\"k\":1}'::jsonb"
        result = self._translate(sql)
        # Must not raise; SQL is returned (may or may not be rewritten)
        assert result is not None


# ---------------------------------------------------------------------------
# Test class: Python reference implementation (mirrors ObjectScript semantics)
# ---------------------------------------------------------------------------


class TestJsonbContainsProcedure:
    def test_simple_key_value_match(self):
        assert _jsonb_contains('{"a":1,"b":2}', '{"a":1}') is True

    def test_simple_mismatch(self):
        assert _jsonb_contains('{"a":1}', '{"b":2}') is False

    def test_nested_match(self):
        assert _jsonb_contains('{"x":{"y":1}}', '{"x":{"y":1}}') is True

    def test_nested_mismatch(self):
        assert _jsonb_contains('{"x":{"y":1}}', '{"x":{"y":2}}') is False

    def test_empty_right_always_contained(self):
        assert _jsonb_contains('{"a":1}', '{}') is True

    def test_right_larger_than_left(self):
        assert _jsonb_contains('{"a":1}', '{"a":1,"b":2}') is False

    def test_array_containment(self):
        assert _jsonb_contains('[1,2,3]', '[1,2]') is True

    def test_array_mismatch(self):
        assert _jsonb_contains('[1,2]', '[1,3]') is False

    def test_scalar_match(self):
        assert _jsonb_contains('"hello"', '"hello"') is True

    def test_scalar_mismatch(self):
        assert _jsonb_contains('"hello"', '"world"') is False

"""T011b: boolean expressions used as projected values.

IRIS has no boolean type and allows `AND`/`OR`/comparisons only in a predicate,
never as a value. Prisma's table-introspection query projects two:

    (tbl.relhassubclass and tbl.relkind = 'p') as is_partition

which IRIS answers with `ERROR: ) expected, AND found`. Measured on IRIS 2026.2,
every spelling of a boolean value fails — `(a AND b)`, `(a = 'x')`, `a = 'x'`,
`NOT (a = 'x')` — and `CASE WHEN … THEN 1 ELSE 0 END` is the one that works.

Two rewrites are needed, not one. `CASE WHEN relhassubclass THEN …` *also*
fails, with SQLCODE -14 "A comparison operator is required here": a bare column
cannot stand alone as a predicate operand either. Prisma's first operand is
exactly that, so both fixes have to land together or the query still errors.

The result is `CAST(… AS BIT)` rather than a bare 1/0 so the driver reports it
as a boolean — the client asked for one.
"""

from __future__ import annotations

import pytest

from iris_pgwire.sql_translator.boolean_expr import (
    has_boolean_projection,
    rewrite_boolean_projections,
)

CASE = "CAST(CASE WHEN {} THEN 1 ELSE 0 END AS BIT)"


class TestPrismaQuery:
    """The shape that actually blocks introspection."""

    def test_the_failing_projection(self):
        sql = (
            "SELECT tbl.relname AS table_name, "
            "(tbl.relhassubclass and tbl.relkind = 'p') as is_partition "
            "FROM pg_class AS tbl"
        )
        rewritten = rewrite_boolean_projections(sql)
        assert CASE.format("tbl.relhassubclass <> 0 and tbl.relkind = 'p'") in rewritten
        assert "as is_partition" in rewritten, "the alias must survive"

    def test_both_of_prismas_boolean_projections(self):
        sql = (
            "SELECT (tbl.relhassubclass and tbl.relkind = 'p') as is_partition, "
            "(tbl.relhassubclass and tbl.relkind = 'r') as has_subclass "
            "FROM pg_class AS tbl"
        )
        rewritten = rewrite_boolean_projections(sql)
        assert rewritten.count("CASE WHEN") == 2
        assert "AND" not in rewritten.replace("<> 0 and", ""), "no bare AND may remain as a value"


class TestBareOperands:
    """SQLCODE -14: a column alone is not a predicate in IRIS."""

    @pytest.mark.parametrize(
        ("expression", "expected"),
        [
            ("(a AND b = 1)", "a <> 0 AND b = 1"),
            ("(a AND b)", "a <> 0 AND b <> 0"),
            ("(t.a AND t.b = 1)", "t.a <> 0 AND t.b = 1"),
            ('("A" AND "B" = 1)', '"A" <> 0 AND "B" = 1'),
            ("(a OR b)", "a <> 0 OR b <> 0"),
            ("(NOT a AND b = 1)", "NOT a <> 0 AND b = 1"),
        ],
    )
    def test_bare_columns_get_a_comparison(self, expression, expected):
        sql = f"SELECT {expression} AS x FROM t"
        assert CASE.format(expected) in rewrite_boolean_projections(sql)

    @pytest.mark.parametrize(
        "operand",
        ["a = 1", "a <> 1", "a > 1", "a LIKE 'x'", "a IS NULL", "a IS NOT NULL", "a IN (1, 2)"],
    )
    def test_operands_that_already_compare_are_untouched(self, operand):
        sql = f"SELECT ({operand} AND b = 2) AS x FROM t"
        assert CASE.format(f"{operand} AND b = 2") in rewrite_boolean_projections(sql)


class TestWhatMustNotBeTouched:
    """Every one of these is valid IRIS SQL already; rewriting would break it."""

    @pytest.mark.parametrize(
        "item",
        [
            "(1 + 2)",
            "(a + b)",
            "(a)",  # a bare column in parens is not necessarily boolean
            "(oid)",
            "(SELECT COUNT(*) FROM t2 WHERE k = 1)",
            "(CASE WHEN a = 1 THEN 1 ELSE 0 END)",
            "COUNT(*)",
            "a",
            "t.a",
            "SUM(a)",
            "MAX(a) - MIN(a)",
            "'literal with AND inside'",
            "'a = 1'",
        ],
    )
    def test_left_alone(self, item):
        sql = f"SELECT {item} AS x FROM t"
        assert rewrite_boolean_projections(sql) == sql

    def test_the_where_clause_is_not_rewritten(self):
        """Booleans are legal there; only the select list is the problem."""
        sql = "SELECT a FROM t WHERE (b = 1 AND c = 2)"
        assert rewrite_boolean_projections(sql) == sql

    def test_a_boolean_in_a_subquerys_select_list_is_still_found(self):
        """The construct is just as illegal one level down."""
        sql = "SELECT x FROM (SELECT (a = 1 AND b = 2) AS x FROM t) sub"
        rewritten = rewrite_boolean_projections(sql)
        assert "CASE WHEN" in rewritten

    def test_non_select_statements_are_untouched(self):
        for sql in (
            "UPDATE t SET a = 1 WHERE (b = 1 AND c = 2)",
            "INSERT INTO t (a) VALUES (1)",
            "DELETE FROM t WHERE (a = 1 AND b = 2)",
        ):
            assert rewrite_boolean_projections(sql) == sql


class TestDetection:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT (a AND b = 1) FROM t",
            "SELECT (a = 1) FROM t",
            "SELECT x, (a OR b) AS y FROM t",
        ],
    )
    def test_detected(self, sql):
        assert has_boolean_projection(sql)

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT a FROM t WHERE b = 1 AND c = 2",
            "SELECT (a + b) FROM t",
            "SELECT COUNT(*) FROM t",
            "SELECT (SELECT 1 FROM t2 WHERE k = 1) FROM t",
        ],
    )
    def test_not_detected(self, sql):
        assert not has_boolean_projection(sql)

    def test_detection_is_cheap_enough_to_run_on_every_query(self):
        """It gates the rewrite, so it runs on everything (5 ms budget)."""
        import time

        sql = "SELECT " + ", ".join(f"col{i}" for i in range(50)) + " FROM t WHERE a = 1"
        start = time.perf_counter()
        for _ in range(1000):
            has_boolean_projection(sql)
        per_call_ms = (time.perf_counter() - start) / 1000 * 1000
        assert per_call_ms < 0.5, f"{per_call_ms:.3f} ms per call is too slow for a gate"


class TestAliasHandling:
    @pytest.mark.parametrize(
        ("item", "alias"),
        [
            ("(a = 1) AS x", "AS x"),
            ("(a = 1) as x", "as x"),
            ("(a = 1) x", "x"),
            ("(a = 1)", ""),
        ],
    )
    def test_alias_forms(self, item, alias):
        rewritten = rewrite_boolean_projections(f"SELECT {item} FROM t")
        assert "CASE WHEN a = 1" in rewritten
        if alias:
            assert rewritten.rstrip().endswith(f"{alias} FROM t") or alias in rewritten


class TestBothExecutorsWireItUp:
    def test_both_backends_rewrite_boolean_projections(self):
        """Principle IV: a construct must not work on only one backend."""
        import inspect

        from iris_pgwire import dbapi_executor, iris_executor

        for module in (iris_executor, dbapi_executor):
            source = inspect.getsource(module)
            assert "rewrite_boolean_projections(" in source, (
                f"{module.__name__} never rewrites boolean projections; the query "
                "would reach IRIS as 'ERROR: ) expected, AND found' on this backend"
            )

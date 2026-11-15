"""GROUP BY <position> resolved to the select-list expression it names.

IRIS reads ``GROUP BY 1`` as the constant 1, so ``SELECT status, count(*) FROM orders GROUP BY 1``
returns one row covering every order (measured on IRIS 2026.2 through the DBAPI driver, no
error). PostgreSQL reads it as the first select-list column. These tests pin the rewrite that
gives IRIS the expression instead.
"""

import time

import pytest

from iris_pgwire.sql_translator import positional_group_by
from iris_pgwire.sql_translator.positional_group_by import resolve_group_by_positions
from iris_pgwire.sql_translator.refiner import SQLRefiner

R = resolve_group_by_positions


class TestSubstitution:
    def test_group_by_1_becomes_first_column(self):
        sql = "SELECT status, count(*) FROM orders GROUP BY 1"
        assert R(sql) == "SELECT status, count(*) FROM orders GROUP BY status"

    def test_group_by_2_on_three_column_select(self):
        sql = "SELECT count(*), status, sum(amt) FROM orders GROUP BY 2"
        assert R(sql) == "SELECT count(*), status, sum(amt) FROM orders GROUP BY status"

    def test_group_by_1_2_with_case_expression(self):
        sql = (
            "SELECT status, CASE WHEN amt > 50 THEN 1 ELSE 0 END AS big, count(*) "
            "FROM orders GROUP BY 1, 2"
        )
        assert R(sql).endswith("GROUP BY status, CASE WHEN amt > 50 THEN 1 ELSE 0 END")

    def test_mixed_name_and_position(self):
        sql = "SELECT region, status, count(*) FROM orders GROUP BY region, 2"
        assert R(sql).endswith("GROUP BY region, status")

    def test_function_with_commas_and_literal(self):
        sql = "SELECT coalesce(status, 'a,b'), count(*) FROM orders GROUP BY 1"
        assert R(sql).endswith("GROUP BY coalesce(status, 'a,b')")

    def test_literal_with_comma_does_not_shift_positions(self):
        sql = "SELECT 'a,b' AS tag, status, count(*) FROM orders GROUP BY 2"
        assert R(sql).endswith("GROUP BY status")

    def test_trailing_clauses_kept_and_order_by_untouched(self):
        sql = "SELECT status, count(*) FROM orders GROUP BY 1 HAVING count(*) > 3 ORDER BY 2 DESC"
        assert R(sql) == (
            "SELECT status, count(*) FROM orders GROUP BY status HAVING count(*) > 3 ORDER BY 2 DESC"
        )

    def test_ibis_shape(self):
        sql = 'SELECT t0.status, COUNT(*) AS "CountStar()" FROM orders AS t0 GROUP BY 1'
        assert R(sql).endswith("GROUP BY t0.status")

    def test_distinct_and_top_prefixes_are_not_columns(self):
        assert R("SELECT DISTINCT status, count(*) FROM o GROUP BY 1").endswith("GROUP BY status")
        assert R("SELECT TOP 5 status, count(*) FROM o GROUP BY 1").endswith("GROUP BY status")

    def test_lowercase_and_newlines(self):
        sql = "select status,\n  count(*)\nfrom orders\ngroup by\n  1"
        assert R(sql).endswith("group by\n  status")

    def test_extract_from_inside_select_list_is_not_the_from_clause(self):
        sql = "SELECT EXTRACT(year FROM ts), count(*) FROM orders GROUP BY 1"
        assert R(sql).endswith("GROUP BY EXTRACT(year FROM ts)")


class TestAliasesStripped:
    def test_as_alias(self):
        assert R("SELECT status AS s, count(*) FROM o GROUP BY 1").endswith("GROUP BY status")

    def test_quoted_alias(self):
        sql = 'SELECT upper(status) AS "Status", count(*) FROM o GROUP BY 1'
        assert R(sql).endswith("GROUP BY upper(status)")

    def test_bare_alias(self):
        assert R("SELECT upper(status) s, count(*) FROM o GROUP BY 1").endswith(
            "GROUP BY upper(status)"
        )

    def test_case_end_is_not_an_alias(self):
        sql = "SELECT CASE WHEN a > 1 THEN 'x' ELSE 'y' END, count(*) FROM o GROUP BY 1"
        assert R(sql).endswith("GROUP BY CASE WHEN a > 1 THEN 'x' ELSE 'y' END")

    def test_literal_containing_as_is_not_an_alias(self):
        sql = "SELECT coalesce(status, 'a AS b'), count(*) FROM o GROUP BY 1"
        assert R(sql).endswith("GROUP BY coalesce(status, 'a AS b')")


class TestLeftAlone:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT status, count(*) FROM orders GROUP BY 3",  # out of range
            "SELECT status, count(*) FROM orders GROUP BY 0",
            "SELECT status, count(*) FROM orders GROUP BY status",  # no position
            "SELECT status, count(*) FROM orders GROUP BY ROLLUP(1)",
            "SELECT status, count(*) FROM orders GROUP BY CUBE(1, 2)",
            "SELECT status, count(*) FROM orders GROUP BY GROUPING SETS ((1), ())",
            "SELECT status, count(*) FROM orders GROUP BY ROLLUP(status), 1",
        ],
    )
    def test_unchanged(self, sql):
        assert R(sql) == sql

    def test_select_star_is_left_and_logged_at_debug(self, monkeypatch):
        # Other unit tests configure structlog with cached loggers, so record the module
        # logger's calls directly rather than through structlog.testing.capture_logs.
        calls = []

        class Recorder:
            def debug(self, event, **kw):
                calls.append(("debug", event))

        monkeypatch.setattr(positional_group_by, "logger", Recorder())
        sql = "SELECT * FROM orders GROUP BY 1"
        assert R(sql) == sql
        assert calls and calls[0][0] == "debug" and "*" in calls[0][1]

    def test_qualified_star_is_left(self):
        sql = "SELECT t.*, count(*) FROM orders t GROUP BY 1"
        assert R(sql) == sql

    def test_parameter_in_expression_is_not_duplicated(self):
        sql = "SELECT substr(status, ?, 2), count(*) FROM orders GROUP BY 1"
        assert R(sql) == sql

    def test_dollar_parameter_is_not_duplicated(self):
        sql = "SELECT substr(status, $1, 2), count(*) FROM orders GROUP BY 1"
        assert R(sql) == sql

    def test_parameter_elsewhere_does_not_block(self):
        sql = "SELECT status, count(*) FROM orders WHERE amt > ? GROUP BY 1"
        assert R(sql) == "SELECT status, count(*) FROM orders WHERE amt > ? GROUP BY status"

    def test_question_mark_in_literal_is_not_a_parameter(self):
        sql = "SELECT coalesce(status, '?'), count(*) FROM orders GROUP BY 1"
        assert R(sql).endswith("GROUP BY coalesce(status, '?')")

    def test_no_group_by_returns_same_object(self):
        sql = "SELECT status FROM orders ORDER BY 1"
        assert R(sql) is sql


class TestAggregatePosition:
    # PostgreSQL rejects GROUP BY <position of an aggregate> (42803). Left as a number, IRIS
    # groups by a constant and answers silently; given count(*), IRIS raises SQLCODE -19
    # ("An aggregate function cannot be used in a WHERE or GROUP BY clause"). So the rewrite
    # substitutes the aggregate: an error, as PostgreSQL gives, instead of a wrong answer.
    def test_aggregate_is_substituted_so_iris_raises(self):
        sql = "SELECT status, count(*) FROM orders GROUP BY 2"
        assert R(sql).endswith("GROUP BY count(*)")


class TestScopes:
    def test_subquery_uses_its_own_select_list(self):
        sql = (
            "SELECT s, n FROM (SELECT status AS s, count(*) AS n FROM orders GROUP BY 1) x "
            "ORDER BY 1"
        )
        assert R(sql) == (
            "SELECT s, n FROM (SELECT status AS s, count(*) AS n FROM orders GROUP BY status) x "
            "ORDER BY 1"
        )

    def test_outer_query_over_derived_table(self):
        sql = "SELECT x.k, count(*) FROM (SELECT status AS k, amt FROM orders) x GROUP BY 1"
        assert R(sql).endswith(") x GROUP BY x.k")

    def test_inner_and_outer_both_resolved(self):
        sql = (
            "SELECT k, count(*) FROM (SELECT status AS k, region FROM orders GROUP BY 2, 1) x "
            "GROUP BY 1"
        )
        assert R(sql) == (
            "SELECT k, count(*) FROM (SELECT status AS k, region FROM orders "
            "GROUP BY region, status) x GROUP BY k"
        )

    def test_union_each_select_its_own_list(self):
        sql = (
            "SELECT status, count(*) FROM a GROUP BY 1 "
            "UNION ALL SELECT count(*), kind FROM b GROUP BY 2"
        )
        assert R(sql) == (
            "SELECT status, count(*) FROM a GROUP BY status "
            "UNION ALL SELECT count(*), kind FROM b GROUP BY kind"
        )

    def test_scalar_subquery_in_select_list_does_not_count_as_a_column(self):
        sql = "SELECT (SELECT max(x) FROM u), status, count(*) FROM orders GROUP BY 2"
        assert R(sql).endswith("GROUP BY status")


class TestLiteralsAndComments:
    def test_group_by_inside_string_literal_untouched(self):
        sql = "SELECT status, count(*) FROM orders WHERE note <> 'GROUP BY 1' GROUP BY 1"
        assert R(sql) == (
            "SELECT status, count(*) FROM orders WHERE note <> 'GROUP BY 1' GROUP BY status"
        )

    def test_only_literal_group_by_is_unchanged(self):
        sql = "SELECT status FROM orders WHERE note = 'x GROUP BY 1'"
        assert R(sql) == sql

    def test_group_by_inside_comments_untouched(self):
        sql = "SELECT status, count(*) FROM orders /* GROUP BY 1 */ -- GROUP BY 2\nGROUP BY 1"
        assert R(sql) == (
            "SELECT status, count(*) FROM orders /* GROUP BY 1 */ -- GROUP BY 2\nGROUP BY status"
        )

    def test_comment_in_select_item_not_copied(self):
        sql = "SELECT status -- the status\n, count(*) FROM orders GROUP BY 1 ORDER BY 2"
        assert R(sql).endswith("GROUP BY status ORDER BY 2")

    def test_comma_in_comment_does_not_shift_positions(self):
        sql = "SELECT /* a, b, */ status, count(*) FROM orders GROUP BY 1"
        assert R(sql).endswith("GROUP BY status")


class TestThroughRefiner:
    def test_exact_wrapping_applied_to_substituted_expression(self):
        refined = SQLRefiner().refine("SELECT status, count(*) FROM orders GROUP BY 1")
        assert refined == "SELECT status, count(*) FROM orders GROUP BY %EXACT(status)"

    def test_two_positions_both_wrapped(self):
        refined = SQLRefiner().refine("SELECT a, upper(b) AS ub, count(*) FROM t GROUP BY 1, 2")
        assert refined.endswith("GROUP BY %EXACT(a), %EXACT(upper(b))")

    def test_refine_is_idempotent(self):
        refiner = SQLRefiner()
        once = refiner.refine("SELECT DISTINCT status, count(*) FROM orders GROUP BY 1")
        assert refiner.refine(once) == once

    def test_through_the_pipeline_both_backends_use(self):
        from iris_pgwire.sql_translator import SQLPipeline

        sql, _, _ = SQLPipeline().process(
            'SELECT t0.status, COUNT(*) AS "CountStar()" FROM orders AS t0 GROUP BY 1'
        )
        assert sql.endswith("GROUP BY %EXACT(T0.STATUS)")


class TestCost:
    def test_large_statement_under_5ms(self):
        cols = ", ".join(f"coalesce(c{i}, 'v{i}') AS a{i}" for i in range(200))
        sql = f"SELECT {cols}, count(*) FROM wide WHERE note <> 'x' GROUP BY " + ", ".join(
            str(i) for i in range(1, 201)
        )
        R(sql)
        started = time.perf_counter()
        for _ in range(20):
            out = R(sql)
        elapsed_ms = (time.perf_counter() - started) * 1000 / 20
        assert "GROUP BY coalesce(c0, 'v0'), coalesce(c1, 'v1')" in out
        assert elapsed_ms < 5.0, elapsed_ms

    def test_statement_without_positions_is_cheap(self):
        sql = "SELECT a, b FROM t WHERE x = 1 GROUP BY a, b ORDER BY 1" * 50
        started = time.perf_counter()
        for _ in range(200):
            R(sql)
        assert (time.perf_counter() - started) * 1000 / 200 < 0.5

"""Spec 052 US3 (research R6): recognising row-locking clauses and planning the touch-update.

IRIS takes no lock for `SELECT ... FOR UPDATE`. PGWire locks the rows itself with a touch-update,
`UPDATE t SET pk = pk WHERE <the same predicate>`, measured to exclude exactly as PostgreSQL's
`FOR UPDATE` does, and only where the touch locks exactly the rows the SELECT returns: one base
table, a WHERE it can reuse. Every other shape is refused by name.

The executor hands `plan_locking` the statement after translation (upper-cased, schema-qualified,
`?` markers), so most cases here are written in that form.
"""

from __future__ import annotations

import pytest

from iris_pgwire.sql_translator.locking_clauses import plan_locking


def test_no_locking_clause_is_none():
    assert plan_locking("SELECT n FROM t WHERE id = 1") is None
    assert plan_locking("UPDATE t SET n = 1 WHERE id = 1") is None
    assert plan_locking("INSERT INTO t VALUES (1)") is None


def test_for_inside_a_string_or_comment_is_not_a_clause():
    assert plan_locking("SELECT 'for update' FROM t WHERE id = 1") is None
    assert plan_locking("SELECT n FROM t -- for update\nWHERE id = 1") is None
    assert plan_locking("SELECT n FROM t /* FOR UPDATE */ WHERE id = 1") is None
    assert plan_locking('SELECT "for update" FROM t') is None


def test_for_inside_parentheses_is_not_a_clause():
    assert plan_locking("SELECT SUBSTRING(s FROM 1 FOR 2) FROM t") is None


def test_single_table_for_update_is_emulated():
    plan = plan_locking('SELECT N FROM SQLUser."LOCK_C" WHERE ID = 1 FOR UPDATE')
    assert plan.refusal is None
    assert plan.strength == "update"
    assert not plan.nowait
    assert plan.select_sql == 'SELECT N FROM SQLUser."LOCK_C" WHERE ID = 1'
    assert plan.table.schema == "SQLUser"
    assert plan.table.name == "LOCK_C"
    assert plan.touch_sql('"id"') == 'UPDATE SQLUser."LOCK_C" SET "id" = "id" WHERE ID = 1'


def test_lower_case_and_unqualified():
    plan = plan_locking("select n from lock_c where id = 1 for update")
    assert plan.refusal is None
    assert plan.table.schema is None
    assert plan.table.name == "lock_c"
    assert plan.select_sql == "select n from lock_c where id = 1"
    assert plan.touch_sql("id") == "UPDATE lock_c SET id = id WHERE id = 1"


def test_no_where_touches_the_whole_table():
    plan = plan_locking("SELECT * FROM t FOR UPDATE")
    assert plan.refusal is None
    assert plan.touch_sql("k") == "UPDATE t SET k = k"


def test_alias_is_kept_so_the_predicate_still_resolves():
    plan = plan_locking('SELECT C.N FROM SQLUser."LOCK_C" C WHERE C.ID = 1 FOR UPDATE')
    assert plan.refusal is None
    assert plan.table.alias == "C"
    assert plan.touch_sql('"id"') == 'UPDATE SQLUser."LOCK_C" C SET "id" = "id" WHERE C.ID = 1'
    plan = plan_locking("SELECT a.n FROM t AS a WHERE a.id = 1 FOR UPDATE")
    assert plan.table.alias == "a"
    assert plan.touch_sql("id") == "UPDATE t a SET id = id WHERE a.id = 1"


def test_order_by_is_allowed_and_left_out_of_the_touch():
    plan = plan_locking("SELECT n FROM t WHERE id > ? ORDER BY n FOR UPDATE")
    assert plan.refusal is None
    assert plan.select_sql == "SELECT n FROM t WHERE id > ? ORDER BY n"
    assert plan.touch_sql("id") == "UPDATE t SET id = id WHERE id > ?"


def test_a_subquery_in_where_is_reused():
    plan = plan_locking("SELECT n FROM t WHERE id IN (SELECT id FROM u WHERE x = ?) FOR UPDATE")
    assert plan.refusal is None
    assert plan.touch_sql("id") == "UPDATE t SET id = id WHERE id IN (SELECT id FROM u WHERE x = ?)"


def test_parameters_of_the_predicate_keep_their_positions():
    plan = plan_locking("SELECT ?, n FROM t WHERE id = ? AND n < ? ORDER BY ? FOR UPDATE")
    assert plan.touch_params(("a", 1, 2, "b")) == (1, 2)
    plan = plan_locking("SELECT n FROM t WHERE id = ? FOR UPDATE")
    assert plan.touch_params([7]) == (7,)
    assert plan.touch_params(None) is None


def test_a_question_mark_in_a_literal_is_not_a_parameter():
    plan = plan_locking("SELECT '?' FROM t WHERE s = '?' AND id = ? FOR UPDATE")
    assert plan.touch_params((5,)) == (5,)


def test_nowait():
    plan = plan_locking("SELECT n FROM t WHERE id = 1 FOR UPDATE NOWAIT")
    assert plan.refusal is None
    assert plan.nowait
    assert plan.select_sql == "SELECT n FROM t WHERE id = 1"


def test_of_the_only_table_is_for_update():
    for sql in (
        "SELECT n FROM t WHERE id = 1 FOR UPDATE OF t",
        "SELECT a.n FROM t a WHERE a.id = 1 FOR UPDATE OF a NOWAIT",
    ):
        plan = plan_locking(sql)
        assert plan.refusal is None, sql
        assert "FOR" not in plan.select_sql.upper().split("WHERE")[-1]


@pytest.mark.parametrize(
    "sql, refusal",
    [
        ("SELECT n FROM t WHERE id = 1 FOR SHARE", "for_share"),
        ("SELECT n FROM t WHERE id = 1 FOR NO KEY UPDATE", "for_no_key_update"),
        ("SELECT n FROM t WHERE id = 1 FOR KEY SHARE", "for_key_share"),
        ("SELECT n FROM t WHERE id = 1 FOR UPDATE SKIP LOCKED", "skip_locked"),
        ("SELECT a.n FROM t a JOIN u b ON a.id = b.id FOR UPDATE", "join"),
        ("SELECT a.n FROM t a LEFT OUTER JOIN u b ON a.id = b.id FOR UPDATE OF a", "join"),
        ("SELECT a.n FROM t a, u b WHERE a.id = b.id FOR UPDATE", "join"),
        ("SELECT n FROM (SELECT n FROM t) x FOR UPDATE", "subquery_in_from"),
        ("SELECT k, COUNT(*) FROM t GROUP BY k FOR UPDATE", "aggregate"),
        ("SELECT k FROM t GROUP BY k FOR UPDATE", "group_by"),
        ("SELECT COUNT(*) FROM t FOR UPDATE", "aggregate"),
        ("SELECT DISTINCT k FROM t FOR UPDATE", "distinct"),
        ("SELECT n FROM t ORDER BY n LIMIT 5 FOR UPDATE", "limit"),
        ("SELECT n FROM t ORDER BY n OFFSET 5 FOR UPDATE", "limit"),
        ("SELECT n FROM t FOR UPDATE LIMIT 5", "limit"),
        ("SELECT TOP 5 n FROM t ORDER BY n FOR UPDATE", "limit"),
        ("SELECT n FROM t FETCH FIRST 1 ROWS ONLY FOR UPDATE", "limit"),
        ("SELECT n FROM t UNION SELECT n FROM u FOR UPDATE", "set_operation"),
        ("WITH x AS (SELECT n FROM t) SELECT n FROM x FOR UPDATE", "with"),
        ("SELECT n, ROW_NUMBER() OVER (ORDER BY n) FROM t FOR UPDATE", "window"),
        ("SELECT n FROM t FOR UPDATE OF t FOR SHARE OF t", "several_locking_clauses"),
        ("SELECT a.n FROM t a FOR UPDATE OF a, b", "of_several_tables"),
        ("SELECT n FROM t FOR UPDATE OF u", "of_unknown_table"),
    ],
)
def test_shapes_the_touch_cannot_lock_exactly_are_refused_by_name(sql, refusal):
    plan = plan_locking(sql)
    assert plan is not None, sql
    assert plan.refusal == refusal
    assert plan.message, refusal
    assert "IRIS" in plan.message


def test_the_strength_refusal_wins_over_the_shape():
    plan = plan_locking("SELECT a.n FROM t a JOIN u b ON a.id = b.id FOR SHARE")
    assert plan.refusal == "for_share"


def test_the_refusal_message_names_the_clause_and_a_workaround():
    plan = plan_locking("SELECT a.n FROM t a JOIN u b ON a.id = b.id FOR UPDATE")
    assert "FOR UPDATE" in plan.message
    assert "join" in plan.message
    assert "PGWIRE_TXN_COMPAT=permissive" in plan.message


def test_a_trailing_semicolon_is_dropped_with_the_clause():
    plan = plan_locking("SELECT n FROM t WHERE id = 1 FOR UPDATE;")
    assert plan.select_sql == "SELECT n FROM t WHERE id = 1"
    assert plan.touch_sql("id") == "UPDATE t SET id = id WHERE id = 1"


def test_a_select_without_from_locks_nothing():
    plan = plan_locking("SELECT 1 FOR UPDATE")
    assert plan.refusal is None
    assert plan.table is None
    assert plan.select_sql == "SELECT 1"

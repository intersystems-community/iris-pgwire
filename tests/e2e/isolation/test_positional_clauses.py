"""GROUP BY and ORDER BY by select-list position, the form Ibis, dbt and psql users write.

PostgreSQL reads ``GROUP BY 1`` as the first output column (SELECT, "GROUP BY Clause"). IRIS
reads it as the constant 1 and answers with one row covering every order, no error; PGWire now
resolves the position to the column (sql_translator/positional_group_by.py). IRIS honours
``ORDER BY <position>`` itself; those cases guard that it still does through PGWire.

Each query runs on both protocols, since the extended protocol translates the same statement at
Parse, Describe and Execute. The expectation is PostgreSQL's answer, which the reference server
checks; rows are compared, not counted.
"""

from __future__ import annotations

import pytest

from .harness import run_statement

ROWS = [
    (1, "new", 10),
    (2, "new", 20),
    (3, "new", 30),
    (4, "paid", 40),
    (5, "paid", 50),
    (6, "paid", 60),
    (7, "paid", 70),
    (8, "void", 80),
    (9, "void", 90),
    (10, "void", 100),
]

PER_STATUS = [["new", 3], ["paid", 4], ["void", 3]]

# name -> (sql, params, PostgreSQL's answer: rows, or "error")
CASES = {
    "group_by_1": (
        "select status, count(*) from pos_orders group by 1 order by 1",
        None,
        PER_STATUS,
    ),
    "group_by_2_of_3": (
        "select count(*), status, max(amt) from pos_orders group by 2 order by 2",
        None,
        [[3, "new", 30], [4, "paid", 70], [3, "void", 100]],
    ),
    "group_by_1_2": (
        "select status, case when amt > 50 then 1 else 0 end as big, count(*) "
        "from pos_orders group by 1, 2 order by 1, 2",
        None,
        [["new", 0, 3], ["paid", 0, 2], ["paid", 1, 2], ["void", 1, 3]],
    ),
    "group_by_aliased_column": (
        "select status as s, count(*) from pos_orders group by 1 order by 1",
        None,
        PER_STATUS,
    ),
    "group_by_alias_name": (
        "select status as s, count(*) from pos_orders group by s order by 1",
        None,
        PER_STATUS,
    ),
    "group_by_ibis_shape": (
        'select t0.status, count(*) as "CountStar()" from pos_orders as t0 group by 1 order by 1',
        None,
        PER_STATUS,
    ),
    "group_by_1_with_parameter": (
        "select status, count(*) from pos_orders where amt > %s group by 1 order by 1",
        (25,),
        [["new", 1], ["paid", 4], ["void", 3]],
    ),
    "group_by_1_order_by_2_desc": (
        "select status, count(*) from pos_orders group by 1 order by 2 desc, 1",
        None,
        [["paid", 4], ["new", 3], ["void", 3]],
    ),
    "group_by_1_having": (
        "select status, count(*) from pos_orders group by 1 having count(*) > 3",
        None,
        [["paid", 4]],
    ),
    "group_by_1_in_subquery": (
        "select s, n from (select status as s, count(*) as n from pos_orders group by 1) x "
        "order by 1",
        None,
        PER_STATUS,
    ),
    # PostgreSQL: 42803, "aggregate functions are not allowed in GROUP BY". PGWire substitutes
    # count(*) so IRIS refuses it too (SQLCODE -19) instead of grouping by a constant.
    "group_by_position_of_aggregate": (
        "select status, count(*) from pos_orders group by 2",
        None,
        "error",
    ),
    # PostgreSQL: 42P10, "GROUP BY position 3 is not in select list". Pinned: PGWire leaves it.
    "group_by_position_out_of_range": (
        "select status, count(*) from pos_orders group by 3",
        None,
        "error",
    ),
    "order_by_1_2": (
        "select status, id from pos_orders where id in (1, 4, 8, 9) order by 1, 2",
        None,
        [["new", 1], ["paid", 4], ["void", 8], ["void", 9]],
    ),
    "order_by_2_desc": (
        "select id, amt from pos_orders order by 2 desc limit 3",
        None,
        [[10, 100], [9, 90], [8, 80]],
    ),
    "distinct_order_by_1": (
        "select distinct status from pos_orders order by 1",
        None,
        [["new"], ["paid"], ["void"]],
    ),
    "distinct_order_by_1_desc": (
        "select distinct status from pos_orders order by 1 desc",
        None,
        [["void"], ["paid"], ["new"]],
    ),
}


@pytest.fixture
def table(target):
    with target.connect() as conn:
        for sql in (
            "drop table if exists pos_orders",
            "create table pos_orders (id int primary key, status varchar(10), amt int)",
        ):
            outcome = run_statement(conn, sql)
            assert outcome.ok, outcome.message
        for row in ROWS:
            outcome = run_statement(conn, "insert into pos_orders values (%s, %s, %s)", row)
            assert outcome.ok, outcome.message


@pytest.mark.parametrize("protocol", ["simple", "extended"])
def test_positional_answers(target, table, expect, protocol):
    with target.connect(protocol) as conn:
        for name, (sql, params, postgres) in CASES.items():
            outcome = run_statement(conn, sql, params)
            observed = "error" if outcome.sqlstate else [list(r) for r in outcome.rows]
            expect.check(f"{name}/{protocol}", observed, postgres, message=outcome.message)
    expect.done()

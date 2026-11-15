"""String comparisons on a table created through PGWire compare case-sensitively, as on PostgreSQL.

IRIS's default collation for string columns (`%SQLUPPER`) compares case-insensitively: `c = 'RED'`
matched `red` and `Red`, a unique key refused `'X'` after `'x'`, and `min(c)` returned a value not
in the table (measured 2026-11-15, investigation doc gotcha row 21). PGWire now declares the string
columns of a table it creates `COLLATE %EXACT`. Sorting then follows code points, as PostgreSQL's
`C` collation does; the reference server's database is `en_US.utf8`, so ordering is pinned.
"""

from __future__ import annotations

import os

from .harness import run_statement

_ROWS = [(1, "red"), (2, "Red"), (3, "RED"), (4, "blue")]


def _table(conn, name, columns="id int primary key, c varchar(20), ch char(4)"):
    for sql in (f"drop table if exists {name}", f"create table {name} ({columns})"):
        assert run_statement(conn, sql).ok, sql


def _rows(conn, sql, params=None):
    outcome = run_statement(conn, sql, params)
    return outcome.rows if outcome.ok else outcome.sqlstate


def test_comparisons_are_case_sensitive(target, expect):
    table = f"sc_cmp_{os.getpid()}"
    with target.connect("extended") as conn:
        _table(conn, table)
        for key, value in _ROWS:
            assert run_statement(
                conn, f"insert into {table} values (%s, %s, %s)", [key, value, value]
            ).ok
        observed = {
            "eq_literal": _rows(conn, f"select id from {table} where c = 'RED' order by id"),
            "eq_param": _rows(conn, f"select id from {table} where c = %s order by id", ["RED"]),
            "eq_char": _rows(conn, f"select id from {table} where ch = 'RED' order by id"),
            "not_equal": _rows(conn, f"select id from {table} where c <> 'red' order by id"),
            "in_list": _rows(
                conn, f"select id from {table} where c in ('RED', 'Blue') order by id"
            ),
            "like": _rows(conn, f"select id from {table} where c like 'R%' order by id"),
            "ilike": _rows(conn, f"select id from {table} where c ilike 'r%' order by id"),
            "case": _rows(
                conn, f"select id, case when c = 'RED' then 1 else 0 end from {table} order by id"
            ),
            "upper": _rows(conn, f"select id from {table} where upper(c) = 'RED' order by id"),
            "count_distinct": _rows(conn, f"select count(distinct c) from {table}"),
        }
        run_statement(conn, f"drop table {table}")
    expect.check(
        "comparisons",
        observed,
        {
            "eq_literal": [(3,)],
            "eq_param": [(3,)],
            "eq_char": [(3,)],
            "not_equal": [(2,), (3,), (4,)],
            "in_list": [(3,)],
            "like": [(2,), (3,)],
            "ilike": [(1,), (2,), (3,)],
            "case": [(1, 0), (2, 0), (3, 1), (4, 0)],
            "upper": [(1,), (2,), (3,)],
            "count_distinct": [(4,)],
        },
    )
    expect.done()


def test_a_unique_key_holds_values_that_differ_in_case(target, expect):
    table = f"sc_uq_{os.getpid()}"
    with target.connect("extended") as conn:
        _table(conn, table, "c varchar(20) unique")
        first = run_statement(conn, f"insert into {table} values ('x')")
        second = run_statement(conn, f"insert into {table} values ('X')")
        third = run_statement(conn, f"insert into {table} values ('x')")
        run_statement(conn, f"drop table {table}")
    expect.check(
        "unique_key",
        {
            "x": first.sqlstate or "ok",
            "X": second.sqlstate or "ok",
            "x_again": third.sqlstate or "ok",
        },
        {"x": "ok", "X": "ok", "x_again": "23505"},
    )
    expect.done()


def test_an_added_column_is_case_sensitive_too(target, expect):
    table = f"sc_add_{os.getpid()}"
    with target.connect("extended") as conn:
        _table(conn, table, "id int primary key")
        assert run_statement(conn, f"alter table {table} add column c varchar(20)").ok
        for key, value in _ROWS:
            assert run_statement(conn, f"insert into {table} values (%s, %s)", [key, value]).ok
        observed = _rows(conn, f"select id from {table} where c = 'RED' order by id")
        run_statement(conn, f"drop table {table}")
    expect.check("added_column", observed, [(3,)])
    expect.done()


def test_postgres_collate_clause_is_accepted(target, expect):
    """`COLLATE "C"` (DuckDB's catalog queries and `CREATE TABLE`s use it) is IRIS's %EXACT."""
    table = f"sc_cc_{os.getpid()}"
    with target.connect("extended") as conn:
        created = run_statement(
            conn, f'create table {table} (id int primary key, c varchar(20) collate "C")'
        )
        observed = {"create": created.sqlstate or "ok"}
        if created.ok:
            for key, value in _ROWS:
                run_statement(conn, f"insert into {table} values (%s, %s)", [key, value])
            observed["eq"] = _rows(conn, f"select id from {table} where c = 'RED' order by id")
        run_statement(conn, f"drop table if exists {table}")
    expect.check("collate_c", observed, {"create": "ok", "eq": [(3,)]})
    expect.done()


def test_ordering(target, expect):
    """Pinned: PGWire sorts by code point (PostgreSQL's "C"), the reference database by en_US."""
    table = f"sc_ord_{os.getpid()}"
    with target.connect("extended") as conn:
        _table(conn, table)
        for key, value in _ROWS:
            assert run_statement(
                conn, f"insert into {table} values (%s, %s, %s)", [key, value, value]
            ).ok
        observed = {
            "order_by": _rows(conn, f"select c from {table} order by c"),
            "min_max": _rows(conn, f"select min(c), max(c) from {table}"),
        }
        run_statement(conn, f"drop table {table}")
    expect.check(
        "ordering",
        observed,
        {
            "order_by": [("blue",), ("red",), ("Red",), ("RED",)],
            "min_max": [("blue", "RED")],
        },
    )
    expect.done()

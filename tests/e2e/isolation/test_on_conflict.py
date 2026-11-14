"""E3: ON CONFLICT on the paths PGWire takes, and which forms IRIS INSERT OR UPDATE expresses.

Part one plays PostgreSQL's ``INSERT ... ON CONFLICT`` against both targets. PGWire emulates it
as insert, catch, update (``dbapi_executor.py`` ``_handle_conflict_exception``); PostgreSQL's
answers come from the INSERT reference ("ON CONFLICT Clause") and the reference server.

Part two is the mapping question for spec 052 US3. For each ON CONFLICT form, PostgreSQL runs the
form itself and PGWire runs the IRIS ``INSERT OR UPDATE`` a translation would send. The form is
"exact" when the final table and the error agree; PostgreSQL's result is the answer either way.

The IRIS statements omit the optional ``INTO``: PGWire's schema rewrite turns ``INSERT OR UPDATE
INTO t`` into ``INSERT OR UPDATE SQLUser."INTO" T`` (SQLCODE -30), a translation bug of its own.

The embedded backend's ON CONFLICT path (E3 step 3) is not exercised: the suite runs on DBAPI
only, per the track 4 decisions.
"""

from __future__ import annotations

import threading
import time

import psycopg
import pytest

from .harness import run_statement


def _exec(conn, sql, params=None):
    return run_statement(conn, sql, params)


def _table(conn, ddl, *rows):
    name = ddl.split()[2]
    assert _exec(conn, f"drop table if exists {name}").ok
    created = _exec(conn, ddl)
    assert created.ok, created.message
    for row in rows:
        placeholders = ", ".join(["%s"] * len(row))
        assert _exec(conn, f"insert into {name} values ({placeholders})", row).ok


def _rows(conn, table, order="1"):
    return [list(r) for r in _exec(conn, f"select * from {table} order by {order}").rows]


UPSERT = "insert into oc_u (k, v) values (%s, %s) on conflict (k) do update set v = excluded.v"


def test_executemany_do_update(target, expect):
    with target.connect("extended") as conn:
        _table(conn, "create table oc_u (k int primary key, v int)", (1, 1))
        error = None
        try:
            with conn.cursor() as cur:
                cur.executemany(UPSERT, [(1, 99), (2, 2)])
        except psycopg.Error as e:
            error = e.sqlstate
        expect.check(
            "executemany_do_update",
            {"rows": _rows(conn, "oc_u"), "error": error},
            {"rows": [[1, 99], [2, 2]], "error": None},
        )
    expect.done()


def test_single_do_update(target, expect):
    with target.connect("extended") as conn:
        _table(conn, "create table oc_u (k int primary key, v int)", (1, 1))
        outcome = _exec(conn, UPSERT, (1, 99))
        expect.check(
            "single_do_update",
            {"rows": _rows(conn, "oc_u"), "error": outcome.sqlstate, "rowcount": outcome.rowcount},
            {"rows": [[1, 99]], "error": None, "rowcount": 1},
        )
    expect.done()


def test_do_nothing_does_not_hide_a_foreign_key_violation(target, expect):
    with target.connect("extended") as conn:
        _exec(conn, "drop table if exists oc_child")
        _table(conn, "create table oc_parent (id int primary key)", (1,))
        assert _exec(
            conn,
            "create table oc_child (id int primary key, parent int references oc_parent (id))",
        ).ok
        outcome = _exec(
            conn, "insert into oc_child (id, parent) values (1, 42) on conflict do nothing"
        )
        expect.check(
            "do_nothing_fk_violation",
            {"error": outcome.sqlstate, "rows": _rows(conn, "oc_child")},
            {"error": "23503", "rows": []},
            message=outcome.message,
        )
        _exec(conn, "drop table oc_child")
    expect.done()


def test_do_nothing_with_a_target_that_did_not_conflict(target, expect):
    """``ON CONFLICT (k) DO NOTHING`` when the row collides on a different unique key."""
    with target.connect("extended") as conn:
        _table(conn, "create table oc_two (k int primary key, u int unique, v int)", (1, 10, 1))
        outcome = _exec(conn, "insert into oc_two values (2, 10, 2) on conflict (k) do nothing")
        expect.check(
            "do_nothing_other_key",
            {"error": outcome.sqlstate, "rows": _rows(conn, "oc_two")},
            {"error": "23505", "rows": [[1, 10, 1]]},
            message=outcome.message,
        )
    expect.done()


@pytest.mark.parametrize("form", ["on_conflict", "insert_or_update"])
def test_upsert_racing_a_delete(target, expect, form):
    """Every upsert affects one row, whatever a concurrent DELETE does (E3 step 5).

    PostgreSQL always runs its ON CONFLICT; on PGWire, ``on_conflict`` is PGWire's emulation and
    ``insert_or_update`` the native statement a translation would send.
    """
    rounds = 1000
    sql = UPSERT
    if form == "insert_or_update" and not target.reference:
        sql = "insert or update oc_u (k, v) values (%s, %s)"
    with target.connect() as conn:
        _table(conn, "create table oc_u (k int primary key, v int)", (1, 1))
    zero_rows, errors, messages = [0], [], set()
    stop = threading.Event()

    def deleter():
        with target.connect("extended") as conn:
            while not stop.is_set():
                _exec(conn, "delete from oc_u where k = 1")

    thread = threading.Thread(target=deleter)
    thread.start()
    started = time.perf_counter()
    try:
        with target.connect("extended") as conn:
            for i in range(rounds):
                outcome = _exec(conn, sql, (1, i))
                if not outcome.ok:
                    errors.append(outcome.sqlstate)
                    messages.add(outcome.message)
                elif outcome.rowcount != 1:
                    zero_rows[0] += 1
    finally:
        stop.set()
        thread.join()
    expect.check(
        f"upsert_vs_delete/{form}",
        {"zero_row_upserts": zero_rows[0] > 0, "errors": sorted(set(errors))},
        {"zero_row_upserts": False, "errors": []},
        zero_row_upserts=zero_rows[0],
        error_count=len(errors),
        messages=sorted(messages)[:3],
        rounds=rounds,
        seconds=round(time.perf_counter() - started, 1),
    )
    expect.done()


# Part two: the form PostgreSQL runs, and the INSERT OR UPDATE a translation would send.
FORMS = [
    (
        "pk_only_set_all",
        "create table oc_m (k int primary key, v int, w int)",
        [(1, 1, 1)],
        "insert into oc_m values (1, 9, 9) on conflict (k) do update "
        "set v = excluded.v, w = excluded.w",
        "insert or update oc_m (k, v, w) values (1, 9, 9)",
    ),
    (
        "pk_only_set_subset",
        "create table oc_m (k int primary key, v int, w int)",
        [(1, 1, 1)],
        "insert into oc_m values (1, 9, 9) on conflict (k) do update set v = excluded.v",
        "insert or update oc_m (k, v, w) values (1, 9, 9)",
    ),
    (
        "pk_only_insert_path",
        "create table oc_m (k int primary key, v int, w int)",
        [(1, 1, 1)],
        "insert into oc_m values (2, 9, 9) on conflict (k) do update "
        "set v = excluded.v, w = excluded.w",
        "insert or update oc_m (k, v, w) values (2, 9, 9)",
    ),
    (
        "set_uses_existing_row",
        "create table oc_m (k int primary key, v int, w int)",
        [(1, 1, 1)],
        "insert into oc_m values (1, 9, 9) on conflict (k) do update set v = oc_m.v + excluded.v",
        "insert or update oc_m (k, v, w) values (1, 9, 9)",
    ),
    (
        "do_update_where_false",
        "create table oc_m (k int primary key, v int, w int)",
        [(1, 1, 1)],
        "insert into oc_m values (1, 9, 9) on conflict (k) do update "
        "set v = excluded.v, w = excluded.w where oc_m.v > 100",
        "insert or update oc_m (k, v, w) values (1, 9, 9)",
    ),
    (
        "second_unique_key_conflicts",
        "create table oc_m (k int primary key, v int unique, w int)",
        [(1, 1, 1)],
        "insert into oc_m values (2, 1, 9) on conflict (k) do update "
        "set v = excluded.v, w = excluded.w",
        "insert or update oc_m (k, v, w) values (2, 1, 9)",
    ),
    (
        "target_is_secondary_unique_key",
        "create table oc_m (k int primary key, v int unique, w int)",
        [(1, 1, 1)],
        "insert into oc_m values (1, 1, 9) on conflict (v) do update set w = excluded.w",
        "insert or update oc_m (k, v, w) values (1, 1, 9)",
    ),
    (
        "target_is_secondary_key_new_pk",
        "create table oc_m (k int primary key, v int unique, w int)",
        [(1, 1, 1)],
        "insert into oc_m values (5, 1, 9) on conflict (v) do update set w = excluded.w",
        "insert or update oc_m (k, v, w) values (5, 1, 9)",
    ),
]


@pytest.mark.parametrize(
    "name, ddl, seed, postgres_sql, iris_sql", FORMS, ids=[f[0] for f in FORMS]
)
def test_insert_or_update_expresses(target, expect, name, ddl, seed, postgres_sql, iris_sql):
    with target.connect("extended") as conn:
        _table(conn, ddl, *seed)
        sql = postgres_sql if target.reference else iris_sql
        outcome = _exec(conn, sql)
        expect.check(
            f"insert_or_update/{name}",
            {"rows": _rows(conn, "oc_m"), "error": outcome.sqlstate},
            EXPECTED_FORMS[name],
            sql=sql,
            message=outcome.message,
        )
    expect.done()


# PostgreSQL 16's answers (INSERT, "ON CONFLICT Clause"); the reference run asserts each.
EXPECTED_FORMS = {
    "pk_only_set_all": {"rows": [[1, 9, 9]], "error": None},
    "pk_only_set_subset": {"rows": [[1, 9, 1]], "error": None},
    "pk_only_insert_path": {"rows": [[1, 1, 1], [2, 9, 9]], "error": None},
    "set_uses_existing_row": {"rows": [[1, 10, 1]], "error": None},
    "do_update_where_false": {"rows": [[1, 1, 1]], "error": None},
    # The conflict is on v, not the arbiter k, so PostgreSQL raises a unique violation.
    "second_unique_key_conflicts": {"rows": [[1, 1, 1]], "error": "23505"},
    "target_is_secondary_unique_key": {"rows": [[1, 1, 9]], "error": None},
    "target_is_secondary_key_new_pk": {"rows": [[1, 1, 9]], "error": None},
}

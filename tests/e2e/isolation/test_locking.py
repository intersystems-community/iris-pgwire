"""E2 and the touch-update check: does a row lock exclude a second locker?

E2 asks whether ``SELECT ... FOR UPDATE`` takes a row lock on IRIS. IRIS documents ``FOR UPDATE``
on a cursor as performing no operation (DECLARE), so the question is whether a second
``FOR UPDATE``, or a writer, waits for the first. PostgreSQL's answer: both wait until the first
transaction ends (SELECT, "The Locking Clause").

The touch-update check asks the question spec 052's US4 depends on: if PGWire emulated
``FOR UPDATE`` as ``UPDATE t SET pk = pk WHERE ...``, would one such lock exclude another? On
PostgreSQL an UPDATE locks the row until the transaction ends, so the second one waits.

The lost-update counters run 4 workers that each increment one row ``ISOLATION_COUNTER_ITERATIONS``
times (default 250), retrying on 40001. PostgreSQL ends with the counter equal to the number of
committed increments; any shortfall is a lost update.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
import time

import pytest

from .harness import Session, run_statement

LEVELS = ("read committed", "read uncommitted")
HOLD = 2.0  # how long the first session holds its lock before committing
ITERATIONS = int(os.environ.get("ISOLATION_COUNTER_ITERATIONS", "250"))
WORKERS = 4


def _fresh(target, table="lock_c"):
    with target.connect() as conn:
        for sql in (
            f"drop table if exists {table}",
            f"create table {table} (id int primary key, n int)",
            f"insert into {table} (id, n) values (1, 0)",
        ):
            outcome = run_statement(conn, sql)
            assert outcome.ok, f"setup {sql}: {outcome.message}"


def _session(target, level):
    session = Session("s", target.connect("extended"))
    for sql in ("begin", f"set transaction isolation level {level}"):
        assert run_statement(session.conn, sql).ok
    return session


def _second_waits(target, level, first_sql, second_sql):
    """Run first_sql in A and hold; run second_sql in B. Did B wait for A's COMMIT?"""
    _fresh(target)
    a, b = _session(target, level), _session(target, level)
    try:
        held = run_statement(a.conn, first_sql)
        assert held.ok, f"A: {first_sql}: {held.sqlstate} {held.message}"
        future = b.submit(second_sql)
        time.sleep(HOLD)
        waited = not future.done()
        committed_at = time.monotonic()
        assert run_statement(a.conn, "commit").ok
        outcome = future.result(timeout=30)
        return {
            "waited_for_commit": waited and outcome.finished >= committed_at,
            "result": outcome.sqlstate or "ok",
        }, round(outcome.elapsed, 3)
    finally:
        a.close()
        b.close()


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize(
    "name, first, second",
    [
        (
            "for_update_vs_for_update",
            "select n from lock_c where id = 1 for update",
            "select n from lock_c where id = 1 for update",
        ),
        (
            "for_update_vs_update",
            "select n from lock_c where id = 1 for update",
            "update lock_c set n = 5 where id = 1",
        ),
        (
            "touch_pk_vs_touch_pk",
            "update lock_c set id = id where id = 1",
            "update lock_c set id = id where id = 1",
        ),
        (
            "touch_n_vs_touch_n",
            "update lock_c set n = n where id = 1",
            "update lock_c set n = n where id = 1",
        ),
        (
            "touch_pk_vs_update",
            "update lock_c set id = id where id = 1",
            "update lock_c set n = 5 where id = 1",
        ),
    ],
)
def test_second_locker_waits(target, expect, level, name, first, second):
    observed, elapsed = _second_waits(target, level, first, second)
    expect.check(
        f"{name}@{level}",
        observed,
        {"waited_for_commit": True, "result": "ok"},
        elapsed=elapsed,
    )
    expect.done()


def _counter(target, level, lock_sql):
    _fresh(target, "lock_counter")
    commits, gave_up, retries = [0], [0], [0]
    lock = threading.Lock()

    def worker():
        conn = target.connect("extended")
        try:
            for _ in range(ITERATIONS):
                for _attempt in range(30):
                    steps = ["begin", f"set transaction isolation level {level}"]
                    ok = all(run_statement(conn, s).ok for s in steps)
                    read = run_statement(conn, lock_sql)
                    if ok and read.ok and lock_sql.startswith("update"):
                        read = run_statement(conn, "select n from lock_counter where id = 1")
                    if not (ok and read.ok and read.rows):
                        run_statement(conn, "rollback")
                        with lock:
                            retries[0] += 1
                        continue
                    n = read.rows[0][0]
                    wrote = run_statement(conn, f"update lock_counter set n = {n + 1} where id = 1")
                    done = run_statement(conn, "commit") if wrote.ok else None
                    if wrote.ok and done.ok and done.status == "COMMIT":
                        with lock:
                            commits[0] += 1
                        break
                    run_statement(conn, "rollback")
                    with lock:
                        retries[0] += 1
                else:
                    with lock:
                        gave_up[0] += 1
        finally:
            conn.close()

    started = time.perf_counter()
    threads = [threading.Thread(target=worker) for _ in range(WORKERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with target.connect() as conn:
        final = run_statement(conn, "select n from lock_counter where id = 1").rows[0][0]
    return final, commits[0], retries[0], gave_up[0], time.perf_counter() - started


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize(
    "name, lock_sql",
    [
        ("for_update", "select n from lock_counter where id = 1 for update"),
        ("touch_pk", "update lock_counter set id = id where id = 1"),
    ],
)
def test_no_lost_updates(target, expect, level, name, lock_sql):
    final, commits, retries, gave_up, seconds = _counter(target, level, lock_sql)
    key = {"for_update": "counter_for_update", "touch_pk": "counter_touch_pk"}[name]
    expect.check(
        f"{key}@{level}",
        {"lost_updates": final != commits, "all_committed": commits == WORKERS * ITERATIONS},
        {"lost_updates": False, "all_committed": True},
        final=final,
        commits=commits,
        retries=retries,
        gave_up=gave_up,
        seconds=round(seconds, 1),
        attempted=WORKERS * ITERATIONS,
    )
    expect.done()


# Spec 052 US3: PGWire locks a single-table SELECT ... FOR UPDATE with a touch-update and refuses
# the shapes a touch cannot lock exactly. PostgreSQL's answers are the expectations; the refusals
# are pinned in known_differences.py with the reason.


def _shapes_fixture(target):
    with target.connect() as conn:
        for sql in (
            "drop view if exists lock_v",
            "drop table if exists lock_d",
            "drop table if exists lock_m",
            "create table lock_m (id int primary key, n int)",
            *(f"insert into lock_m (id, n) values ({i}, {i})" for i in range(1, 5)),
            "create table lock_d (id int primary key, m int)",
            "insert into lock_d (id, m) values (1, 10)",
            "insert into lock_d (id, m) values (2, 20)",
            "create view lock_v as select id, n from lock_m",
        ):
            outcome = run_statement(conn, sql)
            assert outcome.ok, f"setup {sql}: {outcome.message}"


def test_nowait_against_a_held_row(target, expect):
    """US3 scenario 2: NOWAIT on a row another session holds fails at once with 55P03.

    A table of its own, never recreated in this run: a pooled connection that had an error on a
    table since recreated gets the DBAPI driver's "<LIST ERROR>" for every later error on it,
    -110 included, so NOWAIT there reports XX000 (driver bug, measured 2026-11-14; its own check
    is failed_transaction/unique_violation_new_table).
    """
    table = f"lock_nw_{os.getpid()}"
    _fresh(target, table)
    a = Session("a", target.connect("extended"))
    b = target.connect("extended")
    try:
        assert run_statement(a.conn, "begin").ok
        assert run_statement(a.conn, f"update {table} set n = n where id = 1").ok
        assert run_statement(b, "begin").ok
        outcome = run_statement(b, f"select n from {table} where id = %s for update nowait", (1,))
        status = outcome.status_after
        run_statement(b, "rollback")
        run_statement(a.conn, "rollback")
        # And once the row is free, the same statement locks it and returns it.
        assert run_statement(b, "begin").ok
        free = run_statement(b, f"select n from {table} where id = %s for update nowait", (1,))
        run_statement(b, "rollback")
    finally:
        a.close()
        b.close()
        with target.connect() as conn:
            run_statement(conn, f"drop table if exists {table}")
    expect.check(
        "nowait_held_row",
        {
            "sqlstate": outcome.sqlstate,
            "within_1s": outcome.elapsed < 1.0,
            "status_after": status,
            "free_row": free.rows,
        },
        {"sqlstate": "55P03", "within_1s": True, "status_after": "INERROR", "free_row": [(0,)]},
        elapsed=round(outcome.elapsed, 3),
        message=outcome.message,
    )
    expect.done()


def test_for_update_with_parameters_locks(target, expect):
    """The touch reuses the WHERE with its bound parameters: a writer waits for COMMIT."""
    _fresh(target)
    a, b = _session(target, "read committed"), _session(target, "read committed")
    try:
        held = run_statement(a.conn, "select n from lock_c where id = %s for update", (1,))
        assert held.ok, held.message
        future = b.submit("update lock_c set n = 5 where id = 1")
        time.sleep(HOLD)
        waited = not future.done()
        assert run_statement(a.conn, "commit").ok
        outcome = future.result(timeout=30)
    finally:
        a.close()
        b.close()
    expect.check(
        "for_update_params_vs_update",
        {"rows": held.rows, "waited_for_commit": waited, "result": outcome.sqlstate or "ok"},
        {"rows": [(0,)], "waited_for_commit": True, "result": "ok"},
    )
    expect.done()


ROWS_SQL = "select id, n from lock_m where n >= %s order by id"


def test_rows_are_those_without_the_clause(target, expect):
    """US3 scenario 1 / FR-009: the rows returned are the rows the SELECT returns without it."""
    _shapes_fixture(target)
    with target.connect("extended") as conn:
        assert run_statement(conn, "begin").ok
        plain = run_statement(conn, ROWS_SQL, (2,)).rows
        locked = run_statement(conn, ROWS_SQL + " for update", (2,)).rows
        aliased = run_statement(
            conn, "select x.id from lock_m x where x.n >= %s order by x.id for update of x", (3,)
        ).rows
        run_statement(conn, "rollback")
    expect.check(
        "rows_as_without_clause",
        {"plain": plain, "locked": locked, "aliased": aliased},
        {"plain": [(2, 2), (3, 3), (4, 4)], "locked": [(2, 2), (3, 3), (4, 4)], "aliased": [(3,), (4,)]},
    )
    expect.done()


def test_for_update_in_autocommit(target, expect):
    """US3 scenario 6: outside a transaction FOR UPDATE returns the rows; the lock is the statement's."""
    _shapes_fixture(target)
    with target.connect("extended") as conn:
        outcome = run_statement(conn, "select id, n from lock_m where id = 2 for update")
    with target.connect("extended") as other:
        after = run_statement(other, "update lock_m set n = 2 where id = 2")
    expect.check(
        "autocommit_for_update",
        {"rows": outcome.rows, "error": outcome.sqlstate, "row_free_after": after.ok},
        {"rows": [(2, 2)], "error": None, "row_free_after": True},
    )
    expect.done()


REFUSED_SHAPES = {
    # PostgreSQL runs these; IRIS through PGWire refuses them in strict mode (pinned).
    "join": "select a.n from lock_m a join lock_d b on a.id = b.id for update",
    "subquery_in_from": "select n from (select n from lock_m) x for update",
    "limit": "select n from lock_m order by id limit 2 for update",
    "view": "select n from lock_v where id = 1 for update",
    "with": "with x as (select n from lock_m) select n from x for update",
    "several_locking_clauses": "select n from lock_m for update of lock_m for share of lock_m",
    # PostgreSQL: 42P01 (the relation is not in FROM); PGWire refuses it before IRIS sees it.
    "of_unknown_table": "select n from lock_m for update of lock_d",
    # PostgreSQL refuses these itself, with 0A000.
    "union": "select n from lock_m union select m from lock_d for update",
    "window": "select n, row_number() over (order by n) from lock_m for update",
    "group_by": "select n from lock_m group by n for update",
    "aggregate": "select count(*) from lock_m for update",
    "distinct": "select distinct n from lock_m for update",
}


def test_refused_shapes(target, expect):
    """US3 scenario 3 / FR-010: a shape the touch cannot lock exactly is refused with 0A000."""
    _shapes_fixture(target)
    for name, sql in REFUSED_SHAPES.items():
        with target.connect("extended") as conn:
            assert run_statement(conn, "begin").ok
            outcome = run_statement(conn, sql)
            run_statement(conn, "rollback")
        expected = {"group_by": "0A000", "aggregate": "0A000", "distinct": "0A000", "union": "0A000",
                    "window": "0A000", "of_unknown_table": "42P01"}.get(name, "ok")
        expect.check(
            f"refused/{name}", outcome.sqlstate or "ok", expected, message=outcome.message
        )
    expect.done()


@pytest.mark.parametrize("ddl", ["rv bigint", "rv rowversion"], ids=["plain", "rowversion"])
def test_refused_rowversion_table(target, expect, ddl):
    """A touch-update bumps a ROWVERSION column, so the emulation refuses such a table.

    PostgreSQL has no ROWVERSION type; its run uses a plain column, which is PostgreSQL's answer
    for the same statement.
    """
    if target.reference and "rowversion" in ddl:
        ddl = "rv bigint"
    with target.connect() as conn:
        for sql in ("drop table if exists lock_rv", f"create table lock_rv (id int primary key, {ddl})"):
            assert run_statement(conn, sql).ok, sql
    with target.connect("extended") as conn:
        assert run_statement(conn, "begin").ok
        outcome = run_statement(conn, "select id from lock_rv where id = 1 for update")
        run_statement(conn, "rollback")
    key = "refused/rowversion" if "rowversion" in ddl else "refused/plain_column"
    expect.check(key, outcome.sqlstate or "ok", "ok", message=outcome.message)
    expect.done()


@pytest.mark.permissive
def test_permissive_runs_a_refused_shape_and_warns_once(target, expect):
    """US3 scenario 5 / FR-026: permissive runs the shape as 2.0 did and warns once per shape."""
    _shapes_fixture(target)
    sql = "select a.n, b.m from lock_m a join lock_d b on a.id = b.id order by a.id for update"
    results = []
    with target.connect("extended") as conn:
        for _ in range(2):
            assert run_statement(conn, "begin").ok
            outcome = run_statement(conn, sql)
            results.append(outcome.rows if outcome.ok else outcome.sqlstate)
            run_statement(conn, "rollback")
    expect.check("permissive/join_runs", results, [[(1, 10), (2, 20)], [(1, 10), (2, 20)]])
    if not target.reference:
        log = Path(os.environ.get("ISOLATION_LOG", "build/isolation-server.log"))
        warned = [
            line
            for line in log.read_text(errors="replace").splitlines()
            if "strict mode refuses" in line and "LOCK_D" in line.upper()
        ]
        expect.check("permissive/warned_once", len(warned), 1)
    expect.done()


def test_locking_edge_shapes(target, expect):
    """A SELECT with no FROM locks nothing; a missing table keeps the database's own error."""
    _shapes_fixture(target)
    with target.connect("extended") as conn:
        assert run_statement(conn, "begin").ok
        no_from = run_statement(conn, "select 1 for update")
        run_statement(conn, "rollback")
        assert run_statement(conn, "begin").ok
        missing = run_statement(conn, "select n from lock_no_such_table where id = 1 for update")
        run_statement(conn, "rollback")
    expect.check(
        "edge/no_from_and_missing_table",
        {"no_from": no_from.rows, "missing_table": missing.sqlstate},
        {"no_from": [(1,)], "missing_table": "42P01"},
        message=missing.message,
    )
    expect.done()


def test_refused_update_trigger_table(target, expect):
    """A touch-update fires UPDATE triggers, so the emulation refuses a table that has one.

    PostgreSQL's run uses the same table without the trigger (IRIS's trigger syntax is its own),
    which is PostgreSQL's answer for the same statement.
    """
    with target.connect() as conn:
        for sql in ("drop table if exists lock_tr", "create table lock_tr (id int primary key, n int)"):
            assert run_statement(conn, sql).ok, sql
        if not target.reference:
            created = run_statement(
                conn,
                "create trigger lock_tr_upd after update on lock_tr language objectscript { set x = 1 }",
            )
            assert created.ok, created.message
    with target.connect("extended") as conn:
        assert run_statement(conn, "begin").ok
        outcome = run_statement(conn, "select id from lock_tr where id = 1 for update")
        run_statement(conn, "rollback")
    expect.check("refused/update_trigger", outcome.sqlstate or "ok", "ok", message=outcome.message)
    expect.done()


@pytest.mark.permissive
def test_permissive_runs_a_view_unlocked(target, expect):
    """Permissive mode runs a catalog-refused shape (a view) unlocked, as 2.0 did."""
    _shapes_fixture(target)
    with target.connect("extended") as conn:
        assert run_statement(conn, "begin").ok
        outcome = run_statement(conn, "select n from lock_v where id = 2 for update")
        run_statement(conn, "rollback")
    expect.check("permissive/view_runs", outcome.rows if outcome.ok else outcome.sqlstate, [(2,)])
    expect.done()

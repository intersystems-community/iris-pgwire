"""Gotcha row 4: why an accepted READ COMMITTED sometimes reads uncommitted data.

A writer holds row 1 of ``rc_t`` changed to 999 and uncommitted. PostgreSQL's answer for every
reader below is the committed value, at once: READ COMMITTED "sees only data committed before
the query began" and "reading never blocks writing" (13.1, 13.2.1).

Three hypotheses are tested, each reader repeated ``REPEATS`` times with the order alternated:

H1, the one track 4 asked about: the flaky reads used one of IRIS's documented READ COMMITTED
exceptions. IRIS's SELECT reference says a query with ``DISTINCT``, ``GROUP BY`` or an aggregate
"returns the current state of the data, including ... changes ... that have not been committed".
If H1 holds, the plain shapes wait and the exception shapes read dirty, every time.

H2: the outcome depends on how the reader asks for READ COMMITTED (``SET TRANSACTION`` inside or
outside a transaction, ``BEGIN ISOLATION LEVEL``, the session default) or on the protocol
(simple Query, or Parse/Bind/Describe/Execute, where PGWire runs a SELECT twice).

H3: PGWire's DBAPI backend returns a session's IRIS connection to its pool when the client
disconnects, without a ROLLBACK (``DBAPIExecutor.close_session``). A transaction a client
abandoned stays open on that connection, holding its locks, and the next session handed the
connection runs inside it. A reader inside the writer's transaction sees the writer's
uncommitted value at once, which is the flaky shape. PostgreSQL rolls an abandoned transaction
back when the connection ends (protocol "Termination").
"""

from __future__ import annotations

import os
import time

import pytest

from .harness import Session, run_statement

REPEATS = int(os.environ.get("ISOLATION_REPEATS", "5"))
COMMITTED, DIRTY = "committed", "dirty"

SHAPES = {
    # name: (sql, committed rows, dirty rows)
    "plain_pk": ("select n from rc_t where id = 1", [[100]], [[999]]),
    "plain_scan": ("select n from rc_t order by id", [[100], [200]], [[999], [200]]),
    "derived_table": (
        "select * from (select n from rc_t where id = 1) as w",
        [[100]],
        [[999]],
    ),
    "distinct": ("select distinct n from rc_t where id = 1", [[100]], [[999]]),
    "group_by": ("select g, sum(n) from rc_t group by g", [[1, 300]], [[1, 1199]]),
    "aggregate": ("select sum(n) from rc_t", [[300]], [[1199]]),
    "count_where": ("select count(*) from rc_t where n = 999", [[0]], [[1]]),
}

# How a client asks for READ COMMITTED before its read; each is a list of statements.
MODES = {
    "begin_then_set_transaction": ["begin", "set transaction isolation level read committed"],
    "begin_isolation_level": ["begin isolation level read committed"],
    "set_transaction_without_begin": ["set transaction isolation level read committed"],
    "session_characteristics": [
        "set session characteristics as transaction isolation level read committed"
    ],
    "default_then_begin": ["set default_transaction_isolation = 'read committed'", "begin"],
}


def classify(outcome, committed, dirty) -> str:
    if outcome.ok:
        rows = [list(r) for r in outcome.rows or []]
        if rows == committed:
            return COMMITTED
        if rows == dirty:
            return DIRTY
        return f"rows:{rows}"
    if outcome.sqlstate == "40001" and outcome.elapsed >= 5.0:
        return "timeout"
    return f"error:{outcome.sqlstate}"


def _fresh(target):
    with target.connect() as conn:
        for sql in (
            "drop table if exists rc_t",
            "create table rc_t (id int primary key, n int, g int)",
            "insert into rc_t values (1, 100, 1)",
            "insert into rc_t values (2, 200, 1)",
        ):
            outcome = run_statement(conn, sql)
            assert outcome.ok, f"{sql}: {outcome.message}"


@pytest.fixture
def writer(target):
    """Row 1 changed to 999 and held, uncommitted, for the length of the test."""
    _fresh(target)
    session = Session("W", target.connect("extended"))
    assert run_statement(session.conn, "begin").ok
    assert run_statement(session.conn, "update rc_t set n = 999 where id = 1").ok
    yield session
    session.close()


def _read(target, protocol, mode, sql):
    with target.connect(protocol) as conn:
        for statement in MODES[mode]:
            opened = run_statement(conn, statement)
            assert opened.ok, f"{statement}: {opened.sqlstate} {opened.message}"
        outcome = run_statement(conn, sql)
        run_statement(conn, "rollback")
    return outcome


def _alternating(names, run):
    return list(names) if run % 2 == 0 else list(reversed(list(names)))


@pytest.mark.parametrize("protocol", ["simple", "extended"])
def test_h1_documented_exceptions(target, writer, expect, protocol):
    seen: dict[str, list[str]] = {name: [] for name in SHAPES}
    elapsed: dict[str, list[float]] = {name: [] for name in SHAPES}
    for run in range(REPEATS):
        for name in _alternating(SHAPES, run):
            sql, committed, dirty = SHAPES[name]
            outcome = _read(target, protocol, "begin_then_set_transaction", sql)
            seen[name].append(classify(outcome, committed, dirty))
            elapsed[name].append(round(outcome.elapsed, 2))
    for name in SHAPES:
        expect.check(
            f"h1/{name}/{protocol}",
            sorted(set(seen[name])),
            [COMMITTED],
            runs=seen[name],
            elapsed=elapsed[name],
        )
    expect.done()


@pytest.mark.parametrize("protocol", ["simple", "extended"])
def test_h2_how_the_level_was_asked_for(target, writer, expect, protocol):
    sql, committed, dirty = SHAPES["plain_pk"]
    seen: dict[str, list[str]] = {mode: [] for mode in MODES}
    elapsed: dict[str, list[float]] = {mode: [] for mode in MODES}
    for run in range(REPEATS):
        for mode in _alternating(MODES, run):
            outcome = _read(target, protocol, mode, sql)
            seen[mode].append(classify(outcome, committed, dirty))
            elapsed[mode].append(round(outcome.elapsed, 2))
    for mode in MODES:
        expect.check(
            f"h2/{mode}/{protocol}",
            sorted(set(seen[mode])),
            [COMMITTED],
            runs=seen[mode],
            elapsed=elapsed[mode],
        )
    expect.done()


SWEEP = 10  # sequential sessions, enough to cycle through every connection PGWire has pooled
POLLUTERS = 4  # concurrent sessions that change their level and disconnect


def _wait_for_committed_value(target, deadline: float) -> float | None:
    """Seconds until a fresh session reads row 1's committed 100, or None if it never did."""
    started = time.monotonic()
    while time.monotonic() - started < deadline:
        with target.connect() as conn:
            outcome = run_statement(conn, "select n from rc_t where id = 1")
        if outcome.ok and outcome.rows == [(100,)]:
            return round(time.monotonic() - started, 3)
        time.sleep(0.05)
    return None


def test_h3_an_abandoned_transaction_is_rolled_back(target, expect):
    _fresh(target)
    abandoned = target.connect("extended")
    assert run_statement(abandoned, "begin").ok
    assert run_statement(abandoned, "update rc_t set n = 999 where id = 1").ok
    abandoned.close()  # Terminate, with the transaction still open

    # The server ends an abandoned transaction after the client has gone, asynchronously, as
    # PostgreSQL does. Until it has, a session at PGWire's default READ UNCOMMITTED legitimately
    # reads the uncommitted 999 (measured: a 70 ms reset). So wait for the end, bounded: before
    # 2.0.1 it never came, because the transaction stayed open on the pooled connection.
    ended_after = _wait_for_committed_value(target, deadline=5.0)

    def each_session(statements):
        out = []
        for _ in range(SWEEP):
            with target.connect() as conn:
                outcomes = [run_statement(conn, s) for s in statements]
            last = outcomes[-1]
            out.append(last.rows[0][0] if last.ok and last.rows else last.sqlstate or last.status)
        return out

    # Default level: on PGWire READ UNCOMMITTED, so an open transaction anywhere shows as 999.
    reads = each_session(["select n from rc_t where id = 1"])
    # A session that only says COMMIT. Handed the abandoned connection, it commits the 999.
    each_session(["commit"])
    after = each_session(["select n from rc_t where id = 1"])
    with target.connect() as conn:
        update = run_statement(conn, "update rc_t set n = 5 where id = 1")
        final = run_statement(conn, "select n from rc_t where id = 1").rows

    expect.check(
        "h3/abandoned_transaction",
        {
            "abandoned_transaction_ended_within_5s": ended_after is not None,
            "default_level_reads_saw_999": 999 in reads,
            "committed_by_another_session": 999 in after,
            "row_still_locked": update.sqlstate == "40001",
        },
        {
            "abandoned_transaction_ended_within_5s": True,
            "default_level_reads_saw_999": False,
            "committed_by_another_session": False,
            "row_still_locked": False,
        },
        ended_after_seconds=ended_after,
        reads=reads,
        after_commit_sweep=after,
        update=update.sqlstate or update.status,
        update_seconds=round(update.elapsed, 2),
        final=final,
    )
    expect.done()


def test_h3_read_committed_readers_after_an_abandoned_writer(target, expect):
    """The pinned disjunction, reproduced: each reader asks for READ COMMITTED, reads row 1.

    A reader handed the abandoned connection is inside the writer's transaction and reads 999 at
    once; any other reader waits on the abandoned lock. The first reader inside it rolls it back
    on its way out, so readers after that read the committed 100.
    """
    _fresh(target)
    abandoned = target.connect("extended")
    assert run_statement(abandoned, "begin").ok
    assert run_statement(abandoned, "update rc_t set n = 999 where id = 1").ok
    abandoned.close()

    sql, committed, dirty = SHAPES["plain_pk"]
    runs, elapsed = [], []
    for _ in range(6):
        outcome = _read(target, "extended", "begin_then_set_transaction", sql)
        runs.append(classify(outcome, committed, dirty))
        elapsed.append(round(outcome.elapsed, 2))
        if runs[-1] == DIRTY:
            break
    for _ in range(SWEEP):  # leave no abandoned transaction behind for later tests
        with target.connect() as conn:
            run_statement(conn, "rollback")
    expect.check(
        "h3/read_committed_after_abandoned_writer",
        {"an_accepted_read_committed_read_dirty_without_waiting": DIRTY in runs},
        {"an_accepted_read_committed_read_dirty_without_waiting": False},
        runs=runs,
        elapsed=elapsed,
    )
    expect.done()


def test_h3_a_reused_connection_reports_and_runs_at_the_default_level(target, writer, expect):
    """A session handed a pooled connection must start at the server's default level.

    Earlier clients set another level for their session and disconnect. PGWire forgot their
    level, so every later session reported the default, but the pooled IRIS connections kept
    the old level: a session reporting READ UNCOMMITTED waited out the lock timeout like a READ
    COMMITTED reader. Each later session here reports its level and reads the row ``writer``
    holds; at READ UNCOMMITTED it reads 999 at once, at READ COMMITTED (PostgreSQL's default)
    it reads 100 at once on PostgreSQL.
    """
    with target.connect() as probe:
        default = run_statement(probe, "show transaction_isolation").rows[0][0]
    other = "read committed" if default == "read uncommitted" else "read uncommitted"

    # Concurrent, so each holds a different pooled connection when it changes the level.
    polluters = [target.connect() for _ in range(POLLUTERS)]
    for conn in polluters:
        changed = run_statement(
            conn, f"set session characteristics as transaction isolation level {other}"
        )
        assert changed.ok, f"{other}: {changed.sqlstate} {changed.message}"
    for conn in polluters:
        conn.close()

    sql, committed, dirty = SHAPES["plain_pk"]
    expected_outcome = {"read uncommitted": DIRTY, "read committed": COMMITTED}[default]
    reported, runs, elapsed = [], [], []
    for _ in range(SWEEP):
        with target.connect() as conn:
            reported.append(run_statement(conn, "show transaction_isolation").rows[0][0])
            outcome = run_statement(conn, sql)
        runs.append(classify(outcome, committed, dirty))
        elapsed.append(round(outcome.elapsed, 2))
    expect.check(
        "h3/reused_connection_runs_at_the_default_level",
        {
            "every_session_reported_the_default": set(reported) == {default},
            "every_session_ran_at_it": set(runs) == {expected_outcome},
        },
        {"every_session_reported_the_default": True, "every_session_ran_at_it": True},
        default=default,
        polluted_with=other,
        reported=reported,
        runs=runs,
        elapsed=elapsed,
    )
    expect.done()

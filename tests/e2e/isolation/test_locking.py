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
    expect.check(
        f"counter_{name}@{level}",
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

"""Spec 052 US5: `lock_timeout` gives up on a lock as PostgreSQL does; `statement_timeout` is not enforced.

PostgreSQL's answers are the expectations. Where PostgreSQL would wait forever (`lock_timeout = 0`)
the holder releases its lock after a fixed time, so both servers finish and the check is how long
the writer waited. IRIS's lock timeout is whole seconds: `1500ms` gives up after 2 s there and
1.5 s on PostgreSQL, so that check bounds the wait instead of timing it exactly.
"""

from __future__ import annotations

import os
import threading
import time

from .harness import run_statement


def _table(target, name):
    with target.connect() as conn:
        for sql in (
            f"drop table if exists {name}",
            f"create table {name} (id int primary key, n int)",
            f"insert into {name} values (1, 0)",
        ):
            assert run_statement(conn, sql).ok, sql


def _contended_write(target, table, setup, release_after=None):
    """A holds row 1; B runs `setup`, then writes row 1. (outcome, seconds, SHOW lock_timeout)."""
    holder = target.connect("extended")
    writer = target.connect("extended")
    try:
        assert run_statement(holder, "begin").ok
        assert run_statement(holder, f"update {table} set n = n where id = 1").ok
        for sql in setup:
            outcome = run_statement(writer, sql)
            assert outcome.ok, f"{sql}: {outcome.sqlstate} {outcome.message}"
        shown = run_statement(writer, "show lock_timeout").rows
        if release_after is not None:
            threading.Timer(release_after, lambda: run_statement(holder, "commit")).start()
        started = time.monotonic()
        outcome = run_statement(writer, f"update {table} set n = 5 where id = 1")
        return outcome, time.monotonic() - started, shown
    finally:
        time.sleep(0.2)
        run_statement(holder, "rollback")
        holder.close()
        writer.close()


def test_lock_timeout_gives_up_with_55p03(target, expect):
    """US5 scenario 1: `2s`, `2000` and `2000ms` give up after about 2 seconds with 55P03."""
    table = f"to_lt_{os.getpid()}"
    _table(target, table)
    observed = {}
    for spelling in ("'2s'", "2000", "'2000ms'"):
        outcome, seconds, shown = _contended_write(
            target, table, [f"set lock_timeout = {spelling}"]
        )
        observed[spelling] = {
            "sqlstate": outcome.sqlstate,
            "between_1_8_and_3_5s": 1.8 <= seconds <= 3.5,
            "show": shown,
        }
    expected = {
        s: {"sqlstate": "55P03", "between_1_8_and_3_5s": True, "show": [("2s",)]} for s in observed
    }
    expect.check("lock_timeout/gives_up", observed, expected)
    expect.done()


def test_a_fraction_of_a_second_rounds_up(target, expect):
    """US5 scenario 2: `1500ms` gives up within 3 s with 55P03; SHOW reports what the client set."""
    table = f"to_fr_{os.getpid()}"
    _table(target, table)
    outcome, seconds, shown = _contended_write(target, table, ["set lock_timeout = '1500ms'"])
    expect.check(
        "lock_timeout/fraction",
        {
            "sqlstate": outcome.sqlstate,
            "between_1_4_and_3_s": 1.4 <= seconds <= 3.0,
            "show": shown,
        },
        {"sqlstate": "55P03", "between_1_4_and_3_s": True, "show": [("1500ms",)]},
        seconds=round(seconds, 2),
    )
    expect.done()


def test_zero_and_reset_restore_the_default_wait(target, expect):
    """US5 scenario 3: after `0` or RESET the writer waits for the holder (released after 4 s).

    PostgreSQL's 0 waits forever; PGWire restores IRIS's default wait (10 s), which outlasts the
    4 s hold, so both servers let the write through when the holder commits."""
    table = f"to_rs_{os.getpid()}"
    _table(target, table)
    observed = {}
    for reset in ("set lock_timeout = 0", "reset lock_timeout"):
        outcome, seconds, shown = _contended_write(
            target, table, ["set lock_timeout = '1s'", reset], release_after=4.0
        )
        observed[reset] = {
            "result": outcome.sqlstate or "ok",
            "waited_for_the_holder": seconds >= 3.5,
            "show": shown,
        }
    expected = {
        r: {"result": "ok", "waited_for_the_holder": True, "show": [("0",)]} for r in observed
    }
    expect.check("lock_timeout/zero_and_reset", observed, expected)
    expect.done()


def test_statement_timeout_is_not_enforced(target, expect):
    """US5 scenario 4: PostgreSQL cancels the write after 1 s (57014); IRIS through PGWire does not."""
    table = f"to_st_{os.getpid()}"
    _table(target, table)
    outcome, seconds, _ = _contended_write(
        target, table, ["set statement_timeout = '1s'"], release_after=3.0
    )
    with target.connect() as conn:
        shown = run_statement(conn, "set statement_timeout = '1s'")
        shown = run_statement(conn, "show statement_timeout").rows
    expect.check(
        "statement_timeout",
        {"result": outcome.sqlstate or "ok", "cancelled_within_2s": seconds < 2.0, "show": shown},
        {"result": "57014", "cancelled_within_2s": True, "show": [("1s",)]},
        seconds=round(seconds, 2),
    )
    expect.done()


def test_a_new_session_has_the_default_lock_timeout(target, expect):
    """A session's lock_timeout ends with it: later sessions (on reused pooled connections) wait
    for the holder (released after 3 s), and SHOW reports PostgreSQL's default."""
    table = f"to_ns_{os.getpid()}"
    _table(target, table)
    for _ in range(3):
        with target.connect() as conn:
            assert run_statement(conn, "set lock_timeout = '1s'").ok
    observed = []
    for _ in range(2):
        outcome, seconds, shown = _contended_write(target, table, [], release_after=3.0)
        observed.append(
            {
                "result": outcome.sqlstate or "ok",
                "waited_for_the_holder": seconds >= 2.5,
                "show": shown,
            }
        )
    expect.check(
        "lock_timeout/new_session_default",
        observed,
        [{"result": "ok", "waited_for_the_holder": True, "show": [("0",)]}] * 2,
    )
    expect.done()

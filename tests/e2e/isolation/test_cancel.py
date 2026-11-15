"""Does a CancelRequest reach IRIS on the DBAPI backend?

Session A holds a row lock. Session B's UPDATE of the same row waits on it. After one second
the client sends a CancelRequest for B (psycopg ``cancel_safe``). PostgreSQL's answer: B fails at
once with ``57014`` (query_canceled), and the UPDATE never happens, even after A ends
(protocol "Canceling Requests in Progress"; error codes appendix).

On PGWire the measurement is what B sees, how long it waits, and whether the UPDATE was applied
anyway once A let go of the row, which would mean the cancel was acknowledged but never reached
IRIS. A rolls back after HOLD seconds, well inside IRIS's 10 s lock timeout.
"""

from __future__ import annotations

import os
import socket
import struct
import time

from .harness import Session, run_statement

HOLD = 4.0


def test_cancel_a_statement_waiting_on_a_lock(target, expect):
    with target.connect() as conn:
        for sql in (
            "drop table if exists cancel_t",
            "create table cancel_t (id int primary key, n int)",
            "insert into cancel_t values (1, 0)",
        ):
            assert run_statement(conn, sql).ok
    a = Session("A", target.connect("extended"))
    b = Session("B", target.connect("extended"))
    try:
        assert run_statement(a.conn, "begin").ok
        assert run_statement(a.conn, "update cancel_t set n = 1 where id = 1").ok
        future = b.submit("update cancel_t set n = 5 where id = 1")
        time.sleep(1.0)
        cancelled_at = time.monotonic()
        b.conn.cancel_safe(timeout=5)
        time.sleep(HOLD - 1.0)
        released_at = time.monotonic()
        run_statement(a.conn, "rollback")
        outcome = future.result(timeout=30)
    finally:
        a.close()
        b.close()
    with target.connect() as conn:
        n = run_statement(conn, "select n from cancel_t where id = 1").rows[0][0]
    expect.check(
        "cancel_lock_wait",
        {
            "sqlstate": outcome.sqlstate,
            "answered_before_the_lock_was_released": outcome.finished < released_at,
            "update_applied": n == 5,
        },
        {
            "sqlstate": "57014",
            "answered_before_the_lock_was_released": True,
            "update_applied": False,
        },
        seconds_after_cancel=round(outcome.finished - cancelled_at, 3),
        message=outcome.message,
    )
    expect.done()


# Spec 052 US6: a cancel is never silently ignored. PostgreSQL's answers are the expectations.


CANCEL_REQUEST_CODE = 80877102


def _cancel_table(target, name):
    with target.connect() as conn:
        for sql in (
            f"drop table if exists {name}",
            f"create table {name} (id int primary key, n int)",
            f"insert into {name} values (1, 0)",
        ):
            assert run_statement(conn, sql).ok, sql


def _send_cancel(target, pid, secret):
    """A raw CancelRequest (protocol "Canceling Requests in Progress"), for a chosen secret."""
    params = dict(p.split("=", 1) for p in target.dsn.split())
    with socket.create_connection((params["host"], int(params["port"])), timeout=5) as s:
        s.sendall(struct.pack("!IIII", 16, CANCEL_REQUEST_CODE, pid, secret))
        s.settimeout(5)
        try:
            s.recv(1)
        except OSError:
            pass


def _wait_then_cancel(target, table, cancel, in_transaction=False):
    """B waits on A's row lock; `cancel(b_conn)` after 1 s; A releases at 4 s."""
    a = Session("A", target.connect("extended"))
    b = Session("B", target.connect("extended"))
    try:
        assert run_statement(a.conn, "begin").ok
        assert run_statement(a.conn, f"update {table} set n = 1 where id = 1").ok
        if in_transaction:
            assert run_statement(b.conn, "begin").ok
        future = b.submit(f"update {table} set n = 5 where id = 1")
        time.sleep(1.0)
        cancelled_at = time.monotonic()
        cancel(b.conn)
        time.sleep(HOLD - 1.0)
        released_at = time.monotonic()
        run_statement(a.conn, "rollback")
        outcome = future.result(timeout=30)
        after = {
            "status": b.conn.info.transaction_status.name,
            "next": None,
        }
        if in_transaction:
            after["next"] = run_statement(b.conn, "select 1").sqlstate
            run_statement(b.conn, "rollback")
        follow = run_statement(b.conn, "select 1")
        after["after_rollback"] = follow.rows
        return outcome, cancelled_at, released_at, after
    finally:
        a.close()
        b.close()


def _value(target, table):
    with target.connect() as conn:
        return run_statement(conn, f"select n from {table} where id = 1").rows[0][0]


def test_cancel_ten_times_within_a_second(target, expect):
    """SC-007: 10 of 10 cancels answered within 1 s with 57014, the write never applied."""
    table = f"cancel_ten_{os.getpid()}"
    trials = []
    for _ in range(10):
        _cancel_table(target, table)
        outcome, cancelled_at, _, after = _wait_then_cancel(
            target, table, lambda c: c.cancel_safe(timeout=5)
        )
        trials.append(
            {
                "sqlstate": outcome.sqlstate,
                "within_1s": outcome.finished - cancelled_at < 1.0,
                "applied": _value(target, table) == 5,
                "session_usable": after["after_rollback"] == [(1,)],
            }
        )
    expect.check(
        "cancel/ten_trials",
        trials,
        [{"sqlstate": "57014", "within_1s": True, "applied": False, "session_usable": True}] * 10,
    )
    expect.done()


def test_the_session_keeps_its_isolation_level(target, expect):
    """After a cancel the session's next statement runs at the level the session set."""
    table = f"cancel_lvl_{os.getpid()}"
    _cancel_table(target, table)
    a = Session("A", target.connect("extended"))
    b = Session("B", target.connect("extended"))
    try:
        assert run_statement(
            b.conn, "set session characteristics as transaction isolation level read uncommitted"
        ).ok
        assert run_statement(a.conn, "begin").ok
        assert run_statement(a.conn, f"update {table} set n = 1 where id = 1").ok
        future = b.submit(f"update {table} set n = 5 where id = 1")
        time.sleep(1.0)
        b.conn.cancel_safe(timeout=5)
        outcome = future.result(timeout=30)
        level = run_statement(b.conn, "show transaction_isolation").rows
        default = run_statement(b.conn, "show default_transaction_isolation").rows
        run_statement(a.conn, "rollback")
    finally:
        a.close()
        b.close()
    # PostgreSQL runs READ UNCOMMITTED as READ COMMITTED, so the reported level is the comparable
    # answer; that IRIS runs at it after the fresh connection is the resync's job (unit-tested).
    expect.check(
        "cancel/keeps_isolation_level",
        {"sqlstate": outcome.sqlstate, "level": level, "default": default},
        {
            "sqlstate": "57014",
            "level": [("read uncommitted",)],
            "default": [("read uncommitted",)],
        },
    )
    expect.done()


def test_cancel_with_nothing_running_or_a_wrong_secret_changes_nothing(target, expect):
    table = f"cancel_none_{os.getpid()}"
    _cancel_table(target, table)
    with target.connect("extended") as conn:
        conn.cancel_safe(timeout=5)  # nothing running
        idle = run_statement(conn, f"update {table} set n = 2 where id = 1")
    _cancel_table(target, table)
    outcome, _, released_at, _ = _wait_then_cancel(
        target,
        table,
        lambda c: _send_cancel(target, c.info.backend_pid, (c.info.backend_pid * 7 + 1) % 2**31),
    )
    expect.check(
        "cancel/no_effect",
        {
            "idle_session_then_writes": idle.sqlstate or "ok",
            "wrong_secret": outcome.sqlstate or "ok",
            "waited_for_the_holder": outcome.finished >= released_at,
            "applied": _value(target, table) == 5,
        },
        {
            "idle_session_then_writes": "ok",
            "wrong_secret": "ok",
            "waited_for_the_holder": True,
            "applied": True,
        },
    )
    expect.done()


def test_cancel_inside_a_transaction_aborts_it(target, expect):
    """US6 scenario 5: as on PostgreSQL, the cancelled statement aborts the transaction block."""
    table = f"cancel_txn_{os.getpid()}"
    _cancel_table(target, table)
    outcome, _, _, after = _wait_then_cancel(
        target, table, lambda c: c.cancel_safe(timeout=5), in_transaction=True
    )
    expect.check(
        "cancel/inside_transaction",
        {
            "sqlstate": outcome.sqlstate,
            "status": after["status"],
            "next_statement": after["next"],
            "after_rollback": after["after_rollback"],
            "applied": _value(target, table) == 5,
        },
        {
            "sqlstate": "57014",
            "status": "INERROR",
            "next_statement": "25P02",
            "after_rollback": [(1,)],
            "applied": False,
        },
    )
    expect.done()

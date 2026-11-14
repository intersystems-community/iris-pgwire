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

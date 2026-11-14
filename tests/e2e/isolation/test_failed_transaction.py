"""E5: an error inside a transaction, then more work, then COMMIT.

PostgreSQL aborts the transaction on any error: ReadyForQuery reports ``E`` (failed transaction),
every later statement is refused with ``25P02`` until the transaction ends, and ``COMMIT`` ends it
as a ROLLBACK (protocol "Message Flow"; COMMIT reference page). psycopg exposes the status byte as
``conn.info.transaction_status``.
"""

from __future__ import annotations

from psycopg.pq import TransactionStatus

from .harness import run_statement


def _fresh(conn):
    for sql in ("drop table if exists ft_t", "create table ft_t (id int primary key)"):
        assert run_statement(conn, sql).ok


def test_error_then_commit(target, expect):
    for protocol in ("simple", "extended"):
        with target.connect(protocol) as conn:
            _fresh(conn)
            steps, statuses = [], []
            for index, sql in enumerate(
                (
                    "begin",
                    "insert into ft_t values (1)",
                    "insert into ft_t values (1)",  # duplicate key
                    "insert into ft_t values (2)",
                    "commit",
                )
            ):
                outcome = run_statement(conn, sql)
                # The failed INSERT is recorded as "error": which SQLSTATE it carries is a separate
                # defect, measured by test_unique_violation_on_a_new_table below.
                steps.append(
                    "error"
                    if index == 2 and not outcome.ok
                    else (outcome.sqlstate or outcome.status)
                )
                statuses.append(TransactionStatus(conn.info.transaction_status).name)
            run_statement(conn, "rollback")
            ids = [r[0] for r in run_statement(conn, "select id from ft_t order by id").rows]
        expect.check(
            f"error_then_commit/{protocol}",
            {"steps": steps, "ready_for_query": statuses, "ids": ids},
            {
                "steps": ["BEGIN", "INSERT", "error", "25P02", "ROLLBACK"],
                "ready_for_query": ["INTRANS", "INTRANS", "INERROR", "INERROR", "IDLE"],
                "ids": [],
            },
        )
    expect.done()


def test_unique_violation_on_a_new_table(target, expect):
    """A duplicate key on a table created moments before must still be 23505.

    Measured on PGWire: on a recreated table the IRIS error reaches the DBAPI driver as
    "<LIST ERROR> Incorrect list format" (08000 before 2.0.1, XX000 since) on any connection that
    had a -119 on the table before; a fresh connection gets 23505. Ten trials, each recreating
    the table.
    """
    seen = []
    for _ in range(10):
        with target.connect() as conn:
            for sql in (
                "drop table if exists uv_t",
                "create table uv_t (id int primary key)",
                "insert into uv_t values (1)",
            ):
                assert run_statement(conn, sql).ok
            seen.append(run_statement(conn, "insert into uv_t values (1)").sqlstate)
    expect.check("unique_violation_new_table", sorted(set(seen)), ["23505"], runs=seen)
    expect.done()

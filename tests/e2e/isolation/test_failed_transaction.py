"""E5: an error inside a transaction, then more work, then COMMIT.

PostgreSQL aborts the transaction on any error: ReadyForQuery reports ``E`` (failed transaction),
every later statement is refused with ``25P02`` until the transaction ends, and ``COMMIT`` ends it
as a ROLLBACK (protocol "Message Flow"; COMMIT reference page). psycopg exposes the status byte as
``conn.info.transaction_status``.
"""

from __future__ import annotations

from psycopg.pq import TransactionStatus

from .harness import BOTH_SERVERS, run_statement


def _fresh(conn):
    for sql in ("drop table if exists ft_t", "create table ft_t (id int primary key)"):
        assert run_statement(conn, sql).ok


@BOTH_SERVERS
def test_error_then_commit(target, expect, server):
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


def _ids(conn):
    return [r[0] for r in run_statement(conn, "select id from ft_t order by id").rows]


def _script(conn, statements):
    """Run statements in order; each step is its SQLSTATE or command tag, plus the status after."""
    outcomes = [run_statement(conn, sql) for sql in statements]
    return [o.sqlstate or o.status for o in outcomes], [o.status_after for o in outcomes]


@BOTH_SERVERS
def test_rollback_ends_an_aborted_transaction(target, expect, server):
    """US1 scenario: ROLLBACK leaves the aborted state and the session is usable again."""
    for protocol in ("simple", "extended"):
        with target.connect(protocol) as conn:
            _fresh(conn)
            assert run_statement(conn, "insert into ft_t values (1)").ok
            steps, statuses = _script(
                conn,
                [
                    "begin",
                    "insert into ft_t values (1)",  # duplicate key
                    "rollback",
                    "insert into ft_t values (2)",
                ],
            )
            ids = _ids(conn)
        expect.check(
            f"rollback_recovers/{protocol}",
            {"steps": steps[2:], "statuses": statuses, "ids": ids},
            {
                "steps": ["ROLLBACK", "INSERT"],
                "statuses": ["INTRANS", "INERROR", "IDLE", "IDLE"],
                "ids": [1, 2],
            },
        )
    expect.done()


@BOTH_SERVERS
def test_rollback_to_a_savepoint_taken_before_the_error_recovers(target, expect, server):
    """US1 scenario 4: the work before the savepoint survives and the transaction is usable."""
    for protocol in ("simple", "extended"):
        with target.connect(protocol) as conn:
            _fresh(conn)
            steps, statuses = _script(
                conn,
                [
                    "begin",
                    "insert into ft_t values (1)",
                    "savepoint s",
                    "insert into ft_t values (1)",  # duplicate key
                    "rollback to savepoint s",
                    "insert into ft_t values (3)",
                    "commit",
                ],
            )
            ids = _ids(conn)
        expect.check(
            f"rollback_to_recovers/{protocol}",
            {"steps": [steps[0], steps[1], steps[2], steps[4], steps[5], steps[6]],
             "statuses": statuses, "ids": ids},
            {
                "steps": ["BEGIN", "INSERT", "SAVEPOINT", "ROLLBACK", "INSERT", "COMMIT"],
                "statuses": ["INTRANS", "INTRANS", "INTRANS", "INERROR", "INTRANS", "INTRANS", "IDLE"],
                "ids": [1, 3],
            },
        )
    expect.done()


def test_an_error_in_autocommit_changes_nothing(target, expect):
    """US1 scenario 5: with no explicit transaction the next statement runs normally."""
    for protocol in ("simple", "extended"):
        with target.connect(protocol) as conn:
            _fresh(conn)
            assert run_statement(conn, "insert into ft_t values (1)").ok
            steps, statuses = _script(
                conn, ["insert into ft_t values (1)", "insert into ft_t values (2)"]
            )
            ids = _ids(conn)
        expect.check(
            f"autocommit_error/{protocol}",
            {"second": steps[1], "statuses": statuses, "ids": ids},
            {"second": "INSERT", "statuses": ["IDLE", "IDLE"], "ids": [1, 2]},
        )
    expect.done()


@BOTH_SERVERS
def test_an_error_in_a_pipeline_discards_until_sync(target, expect, server):
    """FR-003a: after an error in the extended protocol, messages up to Sync are discarded."""
    import psycopg

    with target.connect("extended") as conn:
        _fresh(conn)
        assert run_statement(conn, "begin").ok
        error = None
        try:
            with conn.pipeline() as pipeline:
                conn.execute("insert into ft_t values (1)")
                conn.execute("insert into ft_t values (1)")  # duplicate key
                conn.execute("insert into ft_t values (2)")
                pipeline.sync()
        except psycopg.Error as e:
            error = "error" if e.sqlstate else type(e).__name__
        status = conn.info.transaction_status.name
        commit = run_statement(conn, "commit")
        ids = _ids(conn)
    expect.check(
        "pipeline_error",
        {"error": error, "status": status, "commit": commit.status, "ids": ids},
        {"error": "error", "status": "INERROR", "commit": "ROLLBACK", "ids": []},
    )
    expect.done()


TRIALS = 100


def test_a_failed_statement_never_commits_anything(target, expect):
    """SC-002: 0 rows committed in 100 of 100 trials, on both protocols."""
    for protocol in ("simple", "extended"):
        committed = 0
        with target.connect(protocol) as conn:
            _fresh(conn)
            assert run_statement(conn, "insert into ft_t values (0)").ok
            for trial in range(1, TRIALS + 1):
                for sql in (
                    "begin",
                    f"insert into ft_t values ({trial})",
                    "insert into ft_t values (0)",  # duplicate key
                    f"insert into ft_t values ({trial + 100000})",
                    "commit",
                ):
                    run_statement(conn, sql)
                run_statement(conn, "rollback")
            committed = len(_ids(conn)) - 1
        expect.check(f"never_commits/{protocol}", {"rows_committed": committed}, {"rows_committed": 0})
    expect.done()


def test_a_pipeline_of_different_statements_runs_each_one(target, expect):
    """Found while building FR-003a: the DML fast path kept only the first statement's SQL for a
    batch, so a pipeline of two different INSERTs before one Sync ran the first one twice."""
    with target.connect("extended") as conn:
        _fresh(conn)
        with conn.pipeline() as pipeline:
            conn.execute("insert into ft_t values (1)")
            conn.execute("insert into ft_t values (2)")
            conn.execute("update ft_t set id = 3 where id = 2")
            pipeline.sync()
        ids = _ids(conn)
    expect.check("pipeline_distinct_statements", {"ids": ids}, {"ids": [1, 3]})
    expect.done()

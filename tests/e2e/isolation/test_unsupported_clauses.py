"""Gotcha rows 10 to 12: what PGWire answers to locking clauses and advisory-lock functions.

PostgreSQL accepts every statement here (SELECT, "The Locking Clause"; 9.27.10 Advisory Lock
Functions). On PGWire each one's SQLSTATE is the measurement: spec 052 decides whether a clause is
emulated or refused, and today's answer is what applications see until then.
"""

from __future__ import annotations

import pytest

from .harness import run_statement

STATEMENTS = {
    "for_share": "select n from uc_t where id = 1 for share",
    "for_no_key_update": "select n from uc_t where id = 1 for no key update",
    "for_key_share": "select n from uc_t where id = 1 for key share",
    "for_update_nowait": "select n from uc_t where id = 1 for update nowait",
    "for_update_skip_locked": "select n from uc_t where id = 1 for update skip locked",
    "pg_advisory_lock": "select pg_advisory_lock(72707369)",
    "pg_try_advisory_lock": "select pg_try_advisory_lock(72707369)",
    "pg_advisory_xact_lock": "select pg_advisory_xact_lock(72707369)",
    "pg_advisory_unlock": "select pg_advisory_unlock(72707369)",
}


@pytest.fixture
def table(target):
    with target.connect() as conn:
        for sql in (
            "drop table if exists uc_t",
            "create table uc_t (id int primary key, n int)",
            "insert into uc_t values (1, 0)",
        ):
            assert run_statement(conn, sql).ok


def test_clause_and_function_answers(target, table, expect):
    for name, sql in STATEMENTS.items():
        with target.connect("extended") as conn:
            run_statement(conn, "begin")
            outcome = run_statement(conn, sql)
            run_statement(conn, "rollback")
        expect.check(f"answer/{name}", outcome.sqlstate or "ok", "ok", message=outcome.message)
    expect.done()

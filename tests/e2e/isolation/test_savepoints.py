"""E4: savepoints, with psycopg's own statements and with raw SQL.

PostgreSQL's answers: ``ROLLBACK TO s`` keeps ``s``; releasing or rolling back to a savepoint
that does not exist is an error, ``3B001``, which aborts the transaction (ROLLBACK, SAVEPOINT and
RELEASE SAVEPOINT reference pages). psycopg 3 rolls back a nested ``transaction()`` block with
``ROLLBACK TO "_pg3_n"`` followed by ``RELEASE "_pg3_n"``.
"""

from __future__ import annotations

from .harness import run_statement


class Boom(Exception):
    pass


def _fresh(conn):
    for sql in ("drop table if exists sp_t", "create table sp_t (id int primary key)"):
        assert run_statement(conn, sql).ok


def _ids(target):
    with target.connect() as conn:
        return [r[0] for r in run_statement(conn, "select id from sp_t order by id").rows]


def test_psycopg_nested_transaction_rolls_back_only_the_inner_block(target, expect):
    with target.connect() as setup:
        _fresh(setup)
    error = None
    conn = target.connect("extended", autocommit=False)
    try:
        with conn.transaction():
            conn.execute("insert into sp_t values (1)")
            try:
                with conn.transaction():
                    conn.execute("insert into sp_t values (2)")
                    raise Boom
            except Boom:
                pass
            conn.execute("insert into sp_t values (3)")
    except Exception as e:  # noqa: BLE001 - the error is the observation
        error = getattr(e, "sqlstate", None) or type(e).__name__
    finally:
        conn.close()
    expect.check(
        "psycopg_nested", {"ids": _ids(target), "error": error}, {"ids": [1, 3], "error": None}
    )
    expect.done()


def _script(target, statements):
    with target.connect() as setup:
        _fresh(setup)
    with target.connect() as conn:
        outcomes = [run_statement(conn, sql) for sql in statements]
        run_statement(conn, "rollback")
    return [o.sqlstate or o.status for o in outcomes], _ids(target)


def test_rollback_to_an_unknown_savepoint(target, expect):
    steps, ids = _script(
        target, ["begin", "insert into sp_t values (1)", "rollback to savepoint nosuch", "commit"]
    )
    expect.check(
        "rollback_to_unknown",
        {"steps": steps, "ids": ids},
        {"steps": ["BEGIN", "INSERT", "3B001", "ROLLBACK"], "ids": []},
    )
    expect.done()


def test_rollback_to_an_unknown_savepoint_while_another_exists(target, expect):
    steps, ids = _script(
        target,
        [
            "begin",
            "insert into sp_t values (1)",
            "savepoint a",
            "insert into sp_t values (2)",
            "rollback to savepoint nosuch",
            "commit",
        ],
    )
    expect.check(
        "rollback_to_unknown_with_savepoint",
        {"steps": steps, "ids": ids},
        {"steps": ["BEGIN", "INSERT", "SAVEPOINT", "INSERT", "3B001", "ROLLBACK"], "ids": []},
    )
    expect.done()


def test_rollback_to_keeps_the_savepoint(target, expect):
    steps, ids = _script(
        target,
        [
            "begin",
            "insert into sp_t values (1)",
            "savepoint s",
            "insert into sp_t values (2)",
            "rollback to savepoint s",
            "insert into sp_t values (3)",
            "rollback to savepoint s",
            "commit",
        ],
    )
    expect.check(
        "rollback_to_twice",
        {"steps": steps, "ids": ids},
        {
            "steps": [
                "BEGIN",
                "INSERT",
                "SAVEPOINT",
                "INSERT",
                "ROLLBACK",
                "INSERT",
                "ROLLBACK",
                "COMMIT",
            ],
            "ids": [1],
        },
    )
    expect.done()


def test_release_savepoint(target, expect):
    cases = {
        "existing": [
            "begin",
            "insert into sp_t values (1)",
            "savepoint s",
            "release savepoint s",
            "commit",
        ],
        "after_rollback_to": [
            "begin",
            "insert into sp_t values (1)",
            "savepoint s",
            "insert into sp_t values (2)",
            "rollback to savepoint s",
            "release savepoint s",
            "commit",
        ],
        "unknown": ["begin", "insert into sp_t values (1)", "release savepoint nosuch", "commit"],
    }
    postgres = {
        "existing": {"steps": ["BEGIN", "INSERT", "SAVEPOINT", "RELEASE", "COMMIT"], "ids": [1]},
        "after_rollback_to": {
            "steps": ["BEGIN", "INSERT", "SAVEPOINT", "INSERT", "ROLLBACK", "RELEASE", "COMMIT"],
            "ids": [1],
        },
        "unknown": {"steps": ["BEGIN", "INSERT", "3B001", "ROLLBACK"], "ids": []},
    }
    for name, statements in cases.items():
        steps, ids = _script(target, statements)
        expect.check(f"release/{name}", {"steps": steps, "ids": ids}, postgres[name])
    expect.done()

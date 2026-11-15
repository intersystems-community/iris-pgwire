"""E4: savepoints, with psycopg's own statements and with raw SQL.

PostgreSQL's answers: ``ROLLBACK TO s`` keeps ``s``; releasing or rolling back to a savepoint
that does not exist is an error, ``3B001``, which aborts the transaction (ROLLBACK, SAVEPOINT and
RELEASE SAVEPOINT reference pages). psycopg 3 rolls back a nested ``transaction()`` block with
``ROLLBACK TO "_pg3_n"`` followed by ``RELEASE "_pg3_n"``.
"""

from __future__ import annotations

import uuid

from .harness import BOTH_SERVERS, run_statement, sqlalchemy_engine, sqlstate_of


class Boom(Exception):
    pass


def _fresh(conn):
    for sql in ("drop table if exists sp_t", "create table sp_t (id int primary key)"):
        assert run_statement(conn, sql).ok


def _ids(target):
    with target.connect() as conn:
        return [r[0] for r in run_statement(conn, "select id from sp_t order by id").rows]


@BOTH_SERVERS
def test_psycopg_nested_transaction_rolls_back_only_the_inner_block(target, expect, server):
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


@BOTH_SERVERS
def test_rollback_to_an_unknown_savepoint(target, expect, server):
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


@BOTH_SERVERS
def test_rollback_to_keeps_the_savepoint(target, expect, server):
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


@BOTH_SERVERS
def test_release_savepoint(target, expect, server):
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


def _steps(target, statements, protocol="simple"):
    """Like _script, but with the transaction status after each step."""
    with target.connect() as setup:
        _fresh(setup)
    with target.connect(protocol) as conn:
        outcomes = [run_statement(conn, sql) for sql in statements]
        run_statement(conn, "rollback")
    return (
        [o.sqlstate or o.status for o in outcomes],
        [o.status_after for o in outcomes],
        _ids(target),
    )


@BOTH_SERVERS
def test_rolling_back_to_an_earlier_savepoint_drops_the_later_one(target, expect, server):
    steps, statuses, ids = _steps(
        target,
        [
            "begin",
            "insert into sp_t values (1)",
            "savepoint a",
            "insert into sp_t values (2)",
            "savepoint b",
            "insert into sp_t values (3)",
            "rollback to savepoint a",
            "rollback to savepoint b",
            "commit",
        ],
    )
    expect.check(
        "rollback_to_earlier_drops_later",
        {"steps": steps, "statuses": statuses, "ids": ids},
        {
            "steps": [
                "BEGIN", "INSERT", "SAVEPOINT", "INSERT", "SAVEPOINT", "INSERT", "ROLLBACK",
                "3B001", "ROLLBACK",
            ],
            "statuses": [
                "INTRANS", "INTRANS", "INTRANS", "INTRANS", "INTRANS", "INTRANS", "INTRANS",
                "INERROR", "IDLE",
            ],
            "ids": [],
        },
    )
    expect.done()


@BOTH_SERVERS
def test_a_duplicate_name_uses_the_most_recent(target, expect, server):
    steps, _, ids = _steps(
        target,
        [
            "begin",
            "savepoint a",
            "insert into sp_t values (1)",
            "savepoint a",
            "insert into sp_t values (2)",
            "rollback to savepoint a",
            "release savepoint a",
            "rollback to savepoint a",
            "commit",
        ],
    )
    expect.check(
        "duplicate_names",
        {"steps": steps, "ids": ids},
        {
            "steps": [
                "BEGIN", "SAVEPOINT", "INSERT", "SAVEPOINT", "INSERT", "ROLLBACK", "RELEASE",
                "ROLLBACK", "COMMIT",
            ],
            "ids": [],
        },
    )
    expect.done()


@BOTH_SERVERS
def test_savepoint_statements_outside_a_transaction(target, expect, server):
    """FR-007a: 25P01, as on PostgreSQL; nothing changes."""
    for name, sql in {
        "savepoint": "savepoint s",
        "rollback_to": "rollback to savepoint s",
        "release": "release savepoint s",
    }.items():
        with target.connect() as conn:
            outcome = run_statement(conn, sql)
        expect.check(
            f"outside_a_transaction/{name}",
            {"sqlstate": outcome.sqlstate, "status": outcome.status_after},
            {"sqlstate": "25P01", "status": "IDLE"},
        )
    expect.done()


def test_identifier_rules_for_names(target, expect):
    """FR-008: unquoted folds to lower case, quoted is exact."""
    steps, _, ids = _steps(
        target,
        [
            "begin",
            "savepoint S1",
            "insert into sp_t values (1)",
            'rollback to savepoint "s1"',  # the same savepoint
            'rollback to savepoint "S1"',  # a different, unknown one
            "commit",
        ],
    )
    expect.check(
        "identifier_rules",
        {"steps": steps, "ids": ids},
        {"steps": ["BEGIN", "SAVEPOINT", "INSERT", "ROLLBACK", "3B001", "ROLLBACK"], "ids": []},
    )
    expect.done()


def test_django_style_quoted_savepoints(target, expect):
    """Django's atomic(): SAVEPOINT "s<thread>_x<n>", RELEASE / ROLLBACK TO SAVEPOINT the same."""
    steps, _, ids = _steps(
        target,
        [
            "begin",
            "insert into sp_t values (1)",
            'SAVEPOINT "s123_x1"',
            "insert into sp_t values (2)",
            'RELEASE SAVEPOINT "s123_x1"',
            'SAVEPOINT "s123_x2"',
            "insert into sp_t values (3)",
            'ROLLBACK TO SAVEPOINT "s123_x2"',
            'RELEASE SAVEPOINT "s123_x2"',
            "commit",
        ],
    )
    expect.check(
        "django_style",
        {"steps": steps, "ids": ids},
        {
            "steps": [
                "BEGIN", "INSERT", "SAVEPOINT", "INSERT", "RELEASE", "SAVEPOINT", "INSERT",
                "ROLLBACK", "RELEASE", "COMMIT",
            ],
            "ids": [1, 2],
        },
    )
    expect.done()


def _nested(conn, plan):
    """psycopg transaction() blocks nested len(plan) deep; plan[i] says whether level i raises.

    Level i inserts row i + 1. A raising level's exception is caught by the level above it, so
    PostgreSQL keeps exactly the rows of levels that do not raise and whose parents do not either.
    """

    def level(i):
        with conn.transaction():
            conn.execute(f"insert into sp_t values ({i + 1})")
            if i + 1 < len(plan):
                try:
                    level(i + 1)
                except Boom:
                    pass
            if plan[i]:
                raise Boom

    try:
        level(0)
    except Boom:
        pass


def test_psycopg_nested_blocks_three_deep(target, expect):
    """SC-004: every combination of normal exit and exception at each of three levels."""
    for raises in [(a, b, c) for a in (False, True) for b in (False, True) for c in (False, True)]:
        with target.connect() as setup:
            _fresh(setup)
        conn = target.connect("extended", autocommit=False)
        error = None
        try:
            _nested(conn, raises)
        except Exception as e:  # noqa: BLE001 - the error is the observation
            error = getattr(e, "sqlstate", None) or type(e).__name__
        finally:
            conn.close()
        key = "".join("x" if r else "o" for r in raises)
        expect.check(f"psycopg_three_deep/{key}", {"ids": _ids(target), "error": error},
                     {"ids": _expected_three_deep(raises), "error": None})
    expect.done()


def _expected_three_deep(raises):
    kept = []
    for i, r in enumerate(raises):
        if r:
            break
        kept.append(i + 1)
    # A level whose parent is kept but which raises loses itself and everything below it.
    return kept if not raises[0] else []


@BOTH_SERVERS
def test_sqlalchemy_begin_nested(target, expect, server):
    """SQLAlchemy's Connection.begin_nested(): unquoted sa_savepoint_n, ROLLBACK TO / RELEASE."""
    from sqlalchemy import text

    with target.connect() as setup:
        _fresh(setup)
    engine = sqlalchemy_engine(target)
    error = None
    try:
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(text("insert into sp_t values (1)"))
                with conn.begin_nested():
                    conn.execute(text("insert into sp_t values (2)"))
                nested = conn.begin_nested()
                conn.execute(text("insert into sp_t values (3)"))
                nested.rollback()
                conn.execute(text("insert into sp_t values (4)"))
    except Exception as e:  # noqa: BLE001 - the error is the observation
        error = sqlstate_of(e)
    finally:
        engine.dispose()
    expect.check("sqlalchemy_begin_nested", {"ids": _ids(target), "error": error},
                 {"ids": [1, 2, 4], "error": None})
    expect.done()


@BOTH_SERVERS
def test_sqlalchemy_session_begin_nested(target, expect, server):
    """The ORM's Session.begin_nested(): a released savepoint keeps its row, a rolled-back one
    loses it, and a duplicate key caught inside one leaves the outer transaction able to commit,
    the pattern SQLAlchemy documents for "insert unless it exists"."""
    from sqlalchemy import Column, Integer, select
    from sqlalchemy.exc import IntegrityError
    from sqlalchemy.orm import DeclarativeBase, Session

    class Base(DeclarativeBase):
        pass

    # A table no connection has seen an error on: once a pooled DBAPI connection has had one on a
    # table that is then recreated, the driver reports "<LIST ERROR>" (XX000) instead of IRIS's
    # error, which would hide the 23505 this check is about.
    table = f"sp_sa_{uuid.uuid4().hex[:8]}"

    class Row(Base):
        __tablename__ = table
        id = Column(Integer, primary_key=True, autoincrement=False)

    engine = sqlalchemy_engine(target)
    error, duplicate, ids = None, None, None
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            session.add(Row(id=1))
            with session.begin_nested():
                session.add(Row(id=2))
            dropped = session.begin_nested()
            session.add(Row(id=3))
            session.flush()
            dropped.rollback()
            try:
                with session.begin_nested():
                    session.add(Row(id=1))
            except IntegrityError as e:
                duplicate = sqlstate_of(e)
            session.add(Row(id=4))
            session.commit()
        with Session(engine) as session:
            seen = list(session.scalars(select(Row.id).order_by(Row.id)))
        with target.connect() as conn:  # and through plain psycopg, outside SQLAlchemy
            ids = [r[0] for r in run_statement(conn, f"select id from {table} order by id").rows]
    except Exception as e:  # noqa: BLE001 - the error is the observation
        error, seen = sqlstate_of(e), None
    finally:
        try:
            Base.metadata.drop_all(engine)
        finally:
            engine.dispose()
    expect.check(
        "sqlalchemy_session_begin_nested",
        {"ids": ids, "seen": seen, "duplicate": duplicate, "error": error},
        {"ids": [1, 2, 4], "seen": [1, 2, 4], "duplicate": "23505", "error": None},
    )
    expect.done()


def test_the_iris_savepoint_limit_is_refused_loudly(target, expect):
    """FR-008a: 300 SAVEPOINT/RELEASE pairs in one transaction. IRIS keeps released savepoints
    and fails at 255 (-400), losing the work; PGWire refuses the 255th with 54000 instead."""
    with target.connect() as setup:
        _fresh(setup)
    with target.connect() as conn:
        assert run_statement(conn, "begin").ok
        assert run_statement(conn, "insert into sp_t values (1)").ok
        first_failure = None
        for i in range(1, 301):
            outcome = run_statement(conn, f"savepoint s{i}")
            if not outcome.ok:
                first_failure = (i, outcome.sqlstate, outcome.status_after)
                break
            assert run_statement(conn, f"release savepoint s{i}").ok
        commit = run_statement(conn, "commit")
    expect.check(
        "savepoint_limit",
        {"first_failure": first_failure, "commit": commit.status, "ids": _ids(target)},
        {"first_failure": None, "commit": "COMMIT", "ids": [1]},
    )
    expect.done()


def test_a_level_change_inside_a_savepoint_is_refused(target, expect):
    """The 25001 rule reads the savepoint stack: PostgreSQL refuses SET TRANSACTION ISOLATION LEVEL
    in a subtransaction ("must not be called in a subtransaction"), even before any query."""
    with target.connect() as conn:
        current = run_statement(conn, "show transaction_isolation").rows[0][0]
        other = "read committed" if current == "read uncommitted" else "read uncommitted"
        steps = [
            run_statement(conn, sql)
            for sql in ("begin", "savepoint s", f"set transaction isolation level {other}")
        ]
        run_statement(conn, "rollback")
    expect.check(
        "level_change_in_subtransaction",
        {"sqlstate": steps[-1].sqlstate, "status": steps[-1].status_after},
        {"sqlstate": "25001", "status": "INERROR"},
    )
    expect.done()

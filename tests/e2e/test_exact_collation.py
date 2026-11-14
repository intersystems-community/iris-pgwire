"""E2E: GROUP BY, DISTINCT and COUNT(DISTINCT) see stored values, as PostgreSQL does.

IRIS compares strings by its default collation, SQLUPPER, so through PGWire `GROUP BY name` put
'alpha' and 'Alpha' in one group and sent it back as 'ALPHA', `COUNT(DISTINCT name)` counted them
once, and `SELECT DISTINCT name ... ORDER BY name` failed with SQLCODE -12. Every answer here is
compared with a real PostgreSQL 16 given the same statements.

    PGWIRE_E2E_TARGETS="dbapi=127.0.0.1:5441" \
    PGWIRE_REFERENCE=127.0.0.1:55433:postgres:pgref:postgres \
    pytest tests/e2e/test_exact_collation.py

Row order is compared as a set: ORDER BY under a collation is a separate difference.
"""

from __future__ import annotations

import os

import psycopg
import pytest

from .test_copy_out import TARGETS, connect

pytestmark = pytest.mark.skipif(
    not (TARGETS and os.environ.get("PGWIRE_REFERENCE")),
    reason="set PGWIRE_E2E_TARGETS=name=host:port and PGWIRE_REFERENCE=host:port:user:pw:db",
)

TABLE = "t2_exact_collation"
SETUP = [
    f"DROP TABLE IF EXISTS {TABLE}",
    f"CREATE TABLE {TABLE} (id INT, name VARCHAR(20))",
    *(
        f"INSERT INTO {TABLE} VALUES ({i}, '{name}')"
        for i, name in enumerate(["alpha", "alpha", "Alpha", "Beta"], start=1)
    ),
]


def _setup(conn: psycopg.Connection) -> None:
    for statement in SETUP:
        conn.execute(statement)


@pytest.fixture
def reference():
    host, port, user, password, dbname = os.environ["PGWIRE_REFERENCE"].split(":")
    c = psycopg.connect(host=host, port=int(port), user=user, password=password,
                        dbname=dbname, autocommit=True)  # fmt: skip
    _setup(c)
    yield c
    c.execute(f"DROP TABLE IF EXISTS {TABLE}")
    c.close()


@pytest.fixture(params=TARGETS or [("none", "", 0)], ids=lambda t: t[0])
def conn(request):
    _, host, port = request.param
    c = connect(host, port)
    _setup(c)
    yield c
    c.execute(f"DROP TABLE IF EXISTS {TABLE}")
    c.close()


def rows(conn: psycopg.Connection, sql: str) -> list[tuple]:
    return sorted(conn.execute(sql).fetchall())


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        (
            f"SELECT name, count(*) FROM {TABLE} GROUP BY name",
            [("Alpha", 1), ("Beta", 1), ("alpha", 2)],
        ),
        (f"SELECT name FROM {TABLE} GROUP BY name", [("Alpha",), ("Beta",), ("alpha",)]),
        (f"SELECT COUNT(DISTINCT name) FROM {TABLE}", [(3,)]),
        (
            f"SELECT DISTINCT name FROM {TABLE} ORDER BY name",
            [("Alpha",), ("Beta",), ("alpha",)],
        ),
        (f"SELECT DISTINCT name FROM {TABLE}", [("Alpha",), ("Beta",), ("alpha",)]),
    ],
    ids=["group-by-count", "group-by", "count-distinct", "distinct-order-by", "distinct"],
)
def test_same_answer_as_postgresql(conn, reference, sql, expected):
    # The literal is what PostgreSQL 16 returned, so two equally wrong servers cannot agree.
    assert rows(reference, sql) == expected
    assert rows(conn, sql) == expected

"""E2E: a SELECT that projects a VECTOR column returns its rows, on every backend.

Until 2026-10-17 the embedded backend returned zero rows, with a normal CommandComplete, for any
SELECT whose projection held a VECTOR value (`specs/051-unified-executor/research.md` §R7). The
DBAPI backend returned the values. No test caught it, because none read a vector back. The
`pgwire_server` fixture also starts an in-process server on the host, where only the DBAPI backend
can run, so the e2e suite never exercised embedded at all.

These tests therefore run against servers that are already running, one per backend, and assert
the same things of each:

    PGWIRE_E2E_TARGETS="embedded=127.0.0.1:5433,dbapi=127.0.0.1:5441" pytest tests/e2e/test_vector_projection.py

The embedded server must run inside the IRIS container. To reach it from outside, run pytest in a
container that shares the IRIS container's network, with `--noconftest`, because nothing here
needs the shared fixtures:

    docker run --rm --network container:iris-pgwire-db -v "$PWD/tests/e2e:/w" python:3.12-slim \
        sh -c 'pip install -q "psycopg[binary]" pytest && cd /w && \
               PGWIRE_E2E_TARGETS=embedded=127.0.0.1:5433 pytest --noconftest -q test_vector_projection.py'

Unset, the module skips with the reason. That skip is CI portability only: the fix this guards
was verified by running it against both backends.
"""

import os
import random

import psycopg
import pytest


def _targets() -> list[tuple[str, str, int]]:
    spec = os.environ.get("PGWIRE_E2E_TARGETS", "")
    out = []
    for item in filter(None, (s.strip() for s in spec.split(","))):
        name, _, address = item.partition("=")
        host, _, port = address.rpartition(":")
        out.append((name, host, int(port)))
    return out


TARGETS = _targets()

pytestmark = pytest.mark.skipif(
    not TARGETS,
    reason="set PGWIRE_E2E_TARGETS=name=host:port[,...] to running pgwire servers",
)

DIM = 1024


@pytest.fixture(params=TARGETS or [("none", "", 0)], ids=lambda t: t[0])
def conn(request):
    name, host, port = request.param
    table = f"E2EVecProj{name.capitalize()}"
    c = psycopg.connect(
        host=host, port=port, user=os.environ.get("PGWIRE_USER", "_SYSTEM"),
        password=os.environ.get("PGWIRE_PASSWORD", "SYS"),
        dbname=os.environ.get("PGWIRE_DBNAME", "USER"), sslmode="disable", autocommit=True,
        connect_timeout=10,
    )
    try:
        c.execute(f"DROP TABLE {table}")
    except psycopg.Error:
        pass
    c.execute(
        f"CREATE TABLE {table} (id INT PRIMARY KEY, v VECTOR(DOUBLE, {DIM}), "
        f"f VECTOR(FLOAT, 2), n VARCHAR(20))"
    )
    c.table = table
    yield c
    c.execute(f"DROP TABLE {table}")
    c.close()


def _vector(seed: int) -> list[float]:
    rng = random.Random(seed)
    return [rng.uniform(-1.0, 1.0) for _ in range(DIM)]


def _text(v: list[float]) -> str:
    return "[" + ",".join(repr(x) for x in v) + "]"


def _parse(value: str) -> list[float]:
    # IRIS's ODBC form is '.1,.2' and pgvector's is '[0.1,0.2]'; accept either so this test
    # pins "the values come back", not the text form, which is a separate ledger entry.
    return [float(x) for x in value.strip("[]").split(",")]


def _insert(conn, rows: int = 3) -> list[list[float]]:
    vectors = [_vector(i) for i in range(rows)]
    for i, v in enumerate(vectors):
        conn.execute(
            f"INSERT INTO {conn.table} (id, v, f, n) VALUES (%s, TO_VECTOR(%s, DOUBLE, {DIM}), "
            f"TO_VECTOR('[1.5,2.5]', FLOAT), %s)",
            (i, _text(v), f"r{i}"),
        )
    conn.execute(f"INSERT INTO {conn.table} (id, n) VALUES (%s, %s)", (rows, "null-vectors"))
    return vectors


@pytest.mark.parametrize("binary", [False, True], ids=["text", "binary"])
def test_every_row_comes_back_with_its_vector(conn, binary):
    vectors = _insert(conn)
    cur = conn.cursor(binary=binary)
    cur.execute(f"SELECT id, v, f, n FROM {conn.table} ORDER BY id")
    rows = cur.fetchall()

    assert [r[0] for r in rows] == [0, 1, 2, 3], "rows were dropped"
    for (_, v, f, _), expected in zip(rows[:3], vectors, strict=True):
        assert _parse(v) == pytest.approx(expected, abs=1e-12)
        assert _parse(f) == [1.5, 2.5]
    assert rows[3][1] is None and rows[3][2] is None, "NULL vectors must read as NULL"
    assert rows[3][3] == "null-vectors"


def test_select_star_and_a_bound_predicate(conn):
    vectors = _insert(conn)
    rows = conn.execute(f"SELECT * FROM {conn.table} WHERE id = %s", (1,)).fetchall()
    assert len(rows) == 1
    assert _parse(rows[0][1]) == pytest.approx(vectors[1], abs=1e-12)


def test_a_computed_vector_expression(conn):
    rows = conn.execute("SELECT TO_VECTOR('[1,2]', DOUBLE) AS q").fetchall()
    assert len(rows) == 1
    assert _parse(rows[0][0]) == [1.0, 2.0]


def test_a_write_that_returns_a_vector_is_never_silently_empty(conn):
    # RETURNING is emulated, and the re-fetch must never re-run a write. Whatever the backend
    # does here, it must not report success with zero rows.
    try:
        cur = conn.execute(
            f"INSERT INTO {conn.table} (id, v) VALUES (%s, TO_VECTOR(%s, DOUBLE, {DIM})) RETURNING id, v",
            (10, _text(_vector(10))),
        )
    except psycopg.Error:
        return  # an error is an acceptable answer; silence is not
    rows = cur.fetchall()
    assert len(rows) == 1, "RETURNING reported success with no row"
    count = conn.execute(f"SELECT COUNT(*) FROM {conn.table} WHERE id = 10").fetchone()[0]
    assert count == 1, "the write ran more than once"

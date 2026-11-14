"""E2E: a text-format result carries PostgreSQL's text output, not Python's str().

The same table and SELECT run through PGWire (backed by IRIS) and through a real PostgreSQL 16, and
the raw DataRow field bytes must be identical. The server used to send str(value): a NUMERIC as
`1E+14`, a timestamp's half second as `.500000`.

    PGWIRE_E2E_TARGETS="dbapi=127.0.0.1:5441" \
    PGWIRE_REFERENCE=127.0.0.1:55433:postgres:pgref:postgres \
    pytest tests/e2e/test_text_format_values.py

Only types IRIS DDL accepts through PGWire today are used: BYTEA, JSONB and TIMESTAMPTZ columns are
not translated in CREATE TABLE, so those are covered by `tests/unit/test_row_encoding.py`.
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

TABLE = "t2_text_values"
SETUP = [
    f"DROP TABLE IF EXISTS {TABLE}",
    f"CREATE TABLE {TABLE} (id INT, n NUMERIC(20,2), big NUMERIC(30,0), d DOUBLE PRECISION,"
    " ts TIMESTAMP)",
    f"INSERT INTO {TABLE} VALUES (1, 12.50, 100000000000000, 1e20, '2026-11-14 12:34:56.5')",
]
QUERY = f"SELECT n, big, d, ts FROM {TABLE}"


def _setup(conn: psycopg.Connection) -> None:
    for statement in SETUP:
        conn.execute(statement)


def raw_text_row(conn: psycopg.Connection, sql: str) -> list[bytes]:
    with conn.cursor() as cur:
        cur.execute(sql)  # psycopg asks for text results by default
        result = cur.pgresult
        assert all(result.fformat(i) == 0 for i in range(result.nfields))
        return [result.get_value(0, i) for i in range(result.nfields)]


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
def target(request):
    name, host, port = request.param
    c = connect(host, port)
    _setup(c)
    yield name, c
    c.execute(f"DROP TABLE IF EXISTS {TABLE}")
    c.close()


# What PostgreSQL 16 sent for each column, so two equally wrong servers cannot agree.
COLUMNS = [
    ("n", b"12.50"),
    ("big", b"100000000000000"),
    ("d", b"1e+20"),
    ("ts", b"2026-11-14 12:34:56.5"),
]
# The embedded backend guesses a column's type from its values (spec 051 US3, T034-T038): it
# reports NUMERIC(20,2) as float8, so 12.50 goes out as 12.5. No text encoding can fix a wrong OID.
EMBEDDED_TYPE_GUESSES = {"n"}


@pytest.mark.parametrize(("column", "expected"), COLUMNS, ids=[c for c, _ in COLUMNS])
def test_text_field_is_byte_for_byte_postgresqls(target, reference, column, expected, request):
    name, conn = target
    if name == "embedded" and column in EMBEDDED_TYPE_GUESSES:
        request.applymarker(pytest.mark.xfail(strict=True, reason="spec 051 US3: types guessed"))
    sql = f"SELECT {column} FROM {TABLE}"
    assert raw_text_row(reference, sql) == [expected]
    assert raw_text_row(conn, sql) == [expected]

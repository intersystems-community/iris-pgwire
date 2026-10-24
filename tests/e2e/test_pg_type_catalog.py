"""E2E: pg_type as served by a real IRIS, queried the way clients query it.

The ADBC PostgreSQL driver runs a six-column pg_type query at connect and decodes every result
column from the `typreceive` it gets back, by name. The server used to answer with four columns of
its own choosing in its own order (and to ignore the WHERE).

    PGWIRE_E2E_TARGETS="embedded=127.0.0.1:5434,dbapi=127.0.0.1:5441" pytest tests/e2e/test_pg_type_catalog.py
"""

from __future__ import annotations

import os

import psycopg
import pytest


def _targets() -> list[tuple[str, str, int]]:
    out = []
    for item in filter(None, (s.strip() for s in os.environ.get("PGWIRE_E2E_TARGETS", "").split(","))):
        name, _, address = item.partition("=")
        host, _, port = address.rpartition(":")
        out.append((name, host, int(port)))
    return out


TARGETS = _targets()
pytestmark = pytest.mark.skipif(
    not TARGETS, reason="set PGWIRE_E2E_TARGETS=name=host:port[,...] to running pgwire servers"
)

# Verbatim from adbc-driver-postgresql 1.12.0 (read out of the shared library).
ADBC_TYPE_QUERY = (
    "SELECT oid, typname, typreceive, typbasetype, typrelid, typarray FROM pg_catalog.pg_type "
    "WHERE (typreceive != 0 OR typsend != 0) AND typtype != 'r' AND typreceive::TEXT != 'array_recv'"
)


@pytest.fixture(params=TARGETS or [("none", "", 0)], ids=lambda t: t[0])
def conn(request):
    _, host, port = request.param
    c = psycopg.connect(
        host=host, port=port, user=os.environ.get("PGWIRE_USER", "_SYSTEM"),
        password=os.environ.get("PGWIRE_PASSWORD", "SYS"), dbname="USER", sslmode="disable",
        autocommit=True, connect_timeout=30,
    )  # fmt: skip
    yield c
    c.close()


class TestTheAdbcTypeQuery:
    def test_it_returns_the_six_columns_it_asked_for_in_the_order_it_asked(self, conn):
        cur = conn.execute(ADBC_TYPE_QUERY)
        assert [d.name for d in cur.description] == [
            "oid", "typname", "typreceive", "typbasetype", "typrelid", "typarray"]  # fmt: skip

    def test_scalar_types_come_back_with_their_receive_functions(self, conn):
        rows = {r[1]: r for r in conn.execute(ADBC_TYPE_QUERY).fetchall()}
        assert (int(rows["int4"][0]), rows["int4"][2]) == (23, "int4recv")
        assert (int(rows["text"][0]), rows["text"][2]) == (25, "textrecv")
        assert rows["bool"][2] == "boolrecv"
        assert rows["timestamp"][2] == "timestamp_recv"
        assert rows["numeric"][2] == "numeric_recv"
        assert rows["uuid"][2] == "uuid_recv"

    def test_an_int4_row_points_at_its_array_type(self, conn):
        rows = {r[1]: r for r in conn.execute(ADBC_TYPE_QUERY).fetchall()}
        assert int(rows["int4"][5]) == 1007

    def test_array_types_are_excluded_as_the_where_clause_asks(self, conn):
        names = [r[1] for r in conn.execute(ADBC_TYPE_QUERY).fetchall()]
        assert not [n for n in names if n.startswith("_")]

    def test_there_are_enough_types_to_describe_what_the_server_sends(self, conn):
        assert len(conn.execute(ADBC_TYPE_QUERY).fetchall()) >= 20


class TestOrdinaryCatalogQueries:
    def test_a_lookup_by_name_returns_one_row(self, conn):
        rows = conn.execute("SELECT oid, typname FROM pg_type WHERE typname = 'int4'").fetchall()
        assert [(int(o), n) for o, n in rows] == [(23, "int4")]

    def test_a_lookup_by_oid(self, conn):
        rows = conn.execute("SELECT typname FROM pg_catalog.pg_type WHERE oid = 25").fetchall()
        assert rows == [("text",)]

    def test_the_where_clause_is_honoured_not_ignored(self, conn):
        everything = conn.execute("SELECT typname FROM pg_type").fetchall()
        one = conn.execute("SELECT typname FROM pg_type WHERE typname = 'float8'").fetchall()
        assert len(one) == 1 and len(everything) > 20

    def test_it_joins_to_pg_namespace(self, conn):
        rows = conn.execute(
            "SELECT t.typname FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace "
            "WHERE n.nspname = 'pg_catalog' AND t.typname = 'int4'"
        ).fetchall()
        assert rows == [("int4",)]

    def test_projection_order_is_the_selects_not_the_catalogs(self, conn):
        cur = conn.execute("SELECT typlen, typname FROM pg_type WHERE typname = 'int4'")
        assert [d.name for d in cur.description] == ["typlen", "typname"]
        assert [(int(a), b) for a, b in cur.fetchall()] == [(4, "int4")]

    def test_the_boolean_columns_are_declared_bool(self, conn):
        cur = conn.execute("SELECT typbyval, typnotnull FROM pg_type WHERE typname = 'int4'")
        assert [d.type_code for d in cur.description] == [16, 16]

    def test_pgvector_is_described(self, conn):
        rows = conn.execute("SELECT oid, typreceive FROM pg_type WHERE typname = 'vector'").fetchall()
        assert [(int(o), r) for o, r in rows] == [(16388, "vector_recv")]

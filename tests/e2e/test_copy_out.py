"""E2E: COPY (query) TO STDOUT in text, CSV and binary, against a real IRIS.

The expected chunks are what PostgreSQL 16.15 sent for the same statements, captured 2026-10-24
with the identical client, message boundaries included. The ADBC PostgreSQL driver reads a binary
COPY stream message by message, so the boundaries are part of the contract.

    PGWIRE_E2E_TARGETS="embedded=127.0.0.1:5434,dbapi=127.0.0.1:5441" pytest tests/e2e/test_copy_out.py
    PGWIRE_REFERENCE=127.0.0.1:55433:postgres:pgref:postgres   # optional live comparison

Start a server with `tests/e2e/_auth_server.py` (see test_auth_defaults.py). The embedded backend
runs inside the IRIS container, so run pytest in a container that shares its network.
"""

from __future__ import annotations

import os
import struct

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

QUERY = "SELECT 1 AS n, 'a' AS s"
HEADER = b"PGCOPY\n\xff\r\n\x00" + struct.pack("!ii", 0, 0)
# PostgreSQL's binary fields: int4 1 is 00000001, text 'a' is 61.
ROW = struct.pack("!h", 2) + struct.pack("!i", 4) + struct.pack("!i", 1) + struct.pack("!i", 1) + b"a"
TRAILER = struct.pack("!h", -1)


def connect(host: str, port: int) -> psycopg.Connection:
    return psycopg.connect(
        host=host, port=port, user=os.environ.get("PGWIRE_USER", "_SYSTEM"),
        password=os.environ.get("PGWIRE_PASSWORD", "SYS"), dbname="USER", sslmode="disable",
        autocommit=True, connect_timeout=30,
    )  # fmt: skip


@pytest.fixture(params=TARGETS or [("none", "", 0)], ids=lambda t: t[0])
def conn(request):
    _, host, port = request.param
    c = connect(host, port)
    yield c
    c.close()


def chunks(conn, sql: str) -> list[bytes]:
    with conn.cursor() as cur, cur.copy(sql) as copy:
        return [bytes(part) for part in copy]


class TestTheFormats:
    def test_text_is_the_default_and_is_tab_separated(self, conn):
        assert chunks(conn, f"COPY ({QUERY}) TO STDOUT") == [b"1\ta\n"]

    def test_csv_with_a_header_one_row_per_message(self, conn):
        assert chunks(conn, f"COPY ({QUERY}) TO STDOUT (FORMAT csv, HEADER)") == [
            b"n,s\n", b"1,a\n"]  # fmt: skip

    def test_binary_header_rides_with_the_first_row_and_the_trailer_is_alone(self, conn):
        assert chunks(conn, f"COPY ({QUERY}) TO STDOUT (FORMAT binary)") == [
            HEADER + ROW, TRAILER]  # fmt: skip

    def test_binary_with_no_rows_is_one_message(self, conn):
        assert chunks(conn, f"COPY ({QUERY} WHERE 1 = 0) TO STDOUT (FORMAT binary)") == [
            HEADER + TRAILER]  # fmt: skip

    def test_the_option_list_needs_no_with(self, conn):
        assert chunks(conn, f"COPY ({QUERY}) TO STDOUT (FORMAT csv)") == [b"1,a\n"]
        assert chunks(conn, f"COPY ({QUERY}) TO STDOUT WITH (FORMAT csv)") == [b"1,a\n"]

    def test_legacy_binary_keyword(self, conn):
        assert chunks(conn, f"COPY ({QUERY}) TO STDOUT BINARY") == [HEADER + ROW, TRAILER]


class TestTheDataIsTheResultNotTheDictionaryKeys:
    """This server used to send "success", "rows", "columns", ... as CSV characters."""

    def test_no_internal_key_names_reach_the_client(self, conn):
        data = b"".join(chunks(conn, f"COPY ({QUERY}) TO STDOUT"))
        for leaked in (b"success", b"rows", b"columns", b"row_count", b"command_tag"):
            assert leaked not in data

    def test_several_rows(self, conn):
        sql = "SELECT 1 AS n, 'a' AS s UNION ALL SELECT 2, 'b' UNION ALL SELECT 3, 'c'"
        assert sorted(chunks(conn, f"COPY ({sql}) TO STDOUT")) == [b"1\ta\n", b"2\tb\n", b"3\tc\n"]

    def test_the_command_tag_counts_rows_exactly(self, conn):
        sql = "SELECT 'x' AS s UNION ALL SELECT 'y'"
        with conn.cursor() as cur:
            with cur.copy(f"COPY ({sql}) TO STDOUT") as copy:
                list(copy)
            # psycopg exposes the CommandComplete tag "COPY 2" as rowcount (PostgreSQL does the same)
            assert cur.rowcount == 2

    def test_a_null_is_an_empty_field_in_csv_and_backslash_n_in_text(self, conn):
        sql = "SELECT CAST(NULL AS VARCHAR(5)) AS a, 'x' AS b"
        assert chunks(conn, f"COPY ({sql}) TO STDOUT (FORMAT csv)") == [b",x\n"]
        assert chunks(conn, f"COPY ({sql}) TO STDOUT") == [b"\\N\tx\n"]

    def test_a_null_in_binary_is_a_length_of_minus_one(self, conn):
        sql = "SELECT CAST(NULL AS VARCHAR(5)) AS a"
        first = chunks(conn, f"COPY ({sql}) TO STDOUT (FORMAT binary)")[0]
        assert first == HEADER + struct.pack("!h", 1) + struct.pack("!i", -1)


class TestErrors:
    def test_a_missing_table_is_an_error_and_the_connection_survives(self, conn):
        with pytest.raises(psycopg.errors.UndefinedTable):
            chunks(conn, "COPY (SELECT * FROM NoSuchTable051Copy) TO STDOUT")
        assert conn.execute("select 1").fetchone() == (1,)

    def test_text_only_options_are_refused_with_binary(self, conn):
        with pytest.raises(psycopg.errors.SyntaxError, match="binary"):
            chunks(conn, f"COPY ({QUERY}) TO STDOUT (FORMAT binary, HEADER)")
        assert conn.execute("select 1").fetchone() == (1,)

    def test_an_unknown_format_is_refused(self, conn):
        with pytest.raises(psycopg.errors.SyntaxError, match="format"):
            chunks(conn, f"COPY ({QUERY}) TO STDOUT (FORMAT parquet)")


@pytest.mark.skipif(
    not os.environ.get("PGWIRE_REFERENCE"), reason="set PGWIRE_REFERENCE=host:port:user:password:db"
)
class TestAgainstRealPostgresql:
    """The same statements against a live PostgreSQL, byte for byte."""

    @pytest.fixture
    def reference(self):
        host, port, user, password, dbname = os.environ["PGWIRE_REFERENCE"].split(":")
        c = psycopg.connect(host=host, port=int(port), user=user, password=password,
                            dbname=dbname, autocommit=True)  # fmt: skip
        yield c
        c.close()

    @pytest.mark.parametrize(
        "options", ["", "(FORMAT csv)", "(FORMAT csv, HEADER)", "(FORMAT binary)", "BINARY"]
    )
    def test_identical_chunks(self, conn, reference, options):
        sql = f"COPY ({QUERY}) TO STDOUT {options}"
        assert chunks(conn, sql) == chunks(reference, sql)

    def test_identical_chunks_for_an_empty_binary_result(self, conn, reference):
        sql = f"COPY ({QUERY} WHERE 1 = 0) TO STDOUT (FORMAT binary)"
        assert chunks(conn, sql) == chunks(reference, sql)

"""E2E: the stock ADBC PostgreSQL driver against iris-pgwire.

The goal is that `adbc-driver-postgresql` (apache/arrow-adbc, what pandas, Polars, DuckDB and dbt
Fusion's Postgres adapter use) connects to IRIS through this server and returns query results.
dbt Fusion never sets `adbc.postgresql.use_copy`, so every result it reads arrives as binary COPY;
the other fetch mode is plain binary result format. Both are covered.

Measured on 2026-10-24 with adbc-driver-postgresql 1.12.0, before this work, the driver could not
connect at all (`Expected 5 or 6 columns from type resolver pg_type query but got 4`), and once it
could, every result failed (`COPY` over the extended protocol went to IRIS as SQL).

Run it where the driver exists, which is a Linux container, against a running server:

    pip install adbc-driver-postgresql pyarrow pytest
    PGWIRE_E2E_TARGETS="embedded=127.0.0.1:5434,dbapi=host.docker.internal:5441" \\
        pytest --noconftest tests/e2e/test_adbc.py

Not covered here, by decision: `adbc_get_objects`, `adbc_get_table_schema` (catalog queries that
need `pg_database`, `regclass` and `unnest`) and bulk ingest. Those are deferred pending whether a
native IRIS ADBC driver replaces this route.
"""

from __future__ import annotations

import os

import pytest

adbc = pytest.importorskip("adbc_driver_postgresql.dbapi")
pa = pytest.importorskip("pyarrow")


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

USER = os.environ.get("PGWIRE_USER", "_SYSTEM")
PASSWORD = os.environ.get("PGWIRE_PASSWORD", "SYS")


@pytest.fixture(params=TARGETS or [("none", "", 0)], ids=lambda t: t[0])
def target(request):
    return request.param


@pytest.fixture
def conn(target):
    _, host, port = target
    c = adbc.connect(f"postgresql://{USER}:{PASSWORD}@{host}:{port}/USER?sslmode=disable")
    yield c
    c.close()


def fetch(conn, sql: str, use_copy: bool) -> pa.Table:
    with conn.cursor() as cur:
        cur.adbc_statement.set_options(**{"adbc.postgresql.use_copy": str(use_copy).lower()})
        cur.execute(sql)
        return cur.fetch_arrow_table()


FETCH_MODES = pytest.mark.parametrize("use_copy", [True, False], ids=["copy", "binary-result"])


class TestConnecting:
    def test_the_driver_connects_and_reports_the_server(self, conn):
        info = conn.adbc_get_info()
        assert info["vendor_name"] == "PostgreSQL"

    def test_the_table_types_are_listed(self, conn):
        assert "table" in conn.adbc_get_table_types()

    def test_a_wrong_password_is_refused(self, target):
        _, host, port = target
        with pytest.raises(Exception, match="(?i)password|authentication"):
            adbc.connect(f"postgresql://{USER}:definitely-wrong@{host}:{port}/USER?sslmode=disable")


# (label, sql, expected python rows, expected arrow type)
SCALARS = [
    ("integer", "SELECT CAST(5 AS INTEGER) AS v", [{"v": 5}], pa.int32()),
    ("bigint", "SELECT CAST(9007199254740993 AS BIGINT) AS v", [{"v": 9007199254740993}], pa.int64()),
    ("smallint", "SELECT CAST(7 AS SMALLINT) AS v", [{"v": 7}], pa.int16()),
    ("double", "SELECT CAST(2.5 AS DOUBLE) AS v", [{"v": 2.5}], pa.float64()),
    ("varchar", "SELECT CAST('héllo' AS VARCHAR(20)) AS v", [{"v": "héllo"}], pa.string()),
    ("date", "SELECT CAST('2026-10-24' AS DATE) AS v", [{"v": __import__("datetime").date(2026, 10, 24)}],
     pa.date32()),
    ("timestamp", "SELECT CAST('2026-10-24 12:34:56' AS TIMESTAMP) AS v",
     [{"v": __import__("datetime").datetime(2026, 10, 24, 12, 34, 56)}], pa.timestamp("us")),
    ("bit", "SELECT CAST(1 AS BIT) AS v", [{"v": True}], pa.bool_()),
    ("null", "SELECT CAST(NULL AS INTEGER) AS v", [{"v": None}], pa.int32()),
    ("two columns", "SELECT 1 AS a, 'x' AS b", [{"a": 1, "b": "x"}], None),
]  # fmt: skip


class TestResultsOverBothFetchModes:
    @FETCH_MODES
    @pytest.mark.parametrize("label,sql,rows,arrow_type", SCALARS, ids=[c[0] for c in SCALARS])
    def test_values_and_arrow_types(self, conn, use_copy, label, sql, rows, arrow_type):
        table = fetch(conn, sql, use_copy)
        assert table.to_pylist() == rows
        if arrow_type is not None:
            assert table.schema.types == [arrow_type]

    @FETCH_MODES
    def test_several_rows(self, conn, use_copy):
        sql = "SELECT 1 AS a, 'x' AS b UNION ALL SELECT 2, 'y' UNION ALL SELECT 3, 'z'"
        rows = sorted(fetch(conn, sql, use_copy).to_pylist(), key=lambda r: r["a"])
        assert rows == [{"a": 1, "b": "x"}, {"a": 2, "b": "y"}, {"a": 3, "b": "z"}]

    @FETCH_MODES
    def test_an_empty_result_keeps_its_schema(self, conn, use_copy):
        table = fetch(conn, "SELECT 1 AS n, 'a' AS s WHERE 1 = 0", use_copy)
        assert table.num_rows == 0 and table.schema.names == ["n", "s"]

    @FETCH_MODES
    def test_column_names_are_those_the_client_was_told(self, conn, use_copy):
        assert fetch(conn, "SELECT 1 AS Mixed", use_copy).schema.names == ["mixed"]

    @FETCH_MODES
    def test_the_connection_serves_many_statements(self, conn, use_copy):
        for i in range(10):
            assert fetch(conn, f"SELECT {i} AS n", use_copy).to_pylist() == [{"n": i}]


class TestKnownTypeDeclarationDefects:
    """Wrong *type declarations*, not wrong values: the result materialiser reports the type IRIS
    gives it rather than the type PostgreSQL would. They belong to feature 051 (US3), and are pinned
    here as strict xfails so they stay visible and cannot be fixed without removing the marker."""

    @FETCH_MODES
    def test_time_is_a_time(self, request, conn, use_copy):
        request.applymarker(
            pytest.mark.xfail(strict=True, reason="051 US3: TIME is declared varchar on both backends")
        )
        table = fetch(conn, "SELECT CAST('12:34:56' AS TIME) AS v", use_copy)
        assert table.schema.types == [pa.time64("us")]

    @FETCH_MODES
    def test_numeric_is_numeric_not_double(self, request, target, conn, use_copy):
        if target[0] != "dbapi":
            request.applymarker(
                pytest.mark.xfail(
                    strict=True, reason="051 US3: embedded declares NUMERIC as float8 (701)"
                )
            )
        table = fetch(conn, "SELECT CAST(12345.6789 AS NUMERIC(12,4)) AS v", use_copy)
        assert table.schema.types[0] != pa.float64()
        assert table.to_pylist() == [{"v": "12345.6789"}]


class TestTransactionsAndErrors:
    """The driver wraps work in `BEGIN TRANSACTION` and ends it with COMMIT or ROLLBACK."""

    @FETCH_MODES
    def test_commit_and_rollback_are_accepted(self, conn, use_copy):
        fetch(conn, "SELECT 1 AS n", use_copy)
        conn.commit()
        fetch(conn, "SELECT 2 AS n", use_copy)
        conn.rollback()

    @FETCH_MODES
    def test_a_failing_statement_raises_and_the_connection_recovers(self, conn, use_copy):
        with pytest.raises(adbc.ProgrammingError):
            fetch(conn, "SELECT * FROM NoSuchTable051Adbc", use_copy)
        conn.rollback()
        assert fetch(conn, "SELECT 1 AS n", use_copy).to_pylist() == [{"n": 1}]


class TestDescribeOfALargeResult:
    """Describe learns a statement's columns without reading its rows (2026-11-14).

    The DBAPI backend runs `SELECT TOP 1 * FROM (query)` for it, because its driver
    (intersystems-irispython 5.4.1) loses its place if a cursor is left with rows unread: the next
    statement fails with "Message out of order" and the connection is gone. A few thousand rows of
    text is enough to span several driver messages, which is when that happens. The embedded
    backend stops reading after one row.
    """

    ROWS = 8192

    @pytest.fixture
    def table(self, conn):
        name = "PgwE2eDescribe"
        with conn.cursor() as cur:
            try:
                cur.execute(f"DROP TABLE {name}")
            except adbc.Error:
                conn.rollback()
            cur.execute(f"CREATE TABLE {name} (id INT, s VARCHAR(100))")
            cur.execute(f"INSERT INTO {name} (id, s) VALUES (1, 'row text that takes some room')")
            count = 1
            while count < self.ROWS:  # double the table until it has ROWS rows
                cur.execute(f"INSERT INTO {name} (id, s) SELECT id + {count}, s FROM {name}")
                count *= 2
        conn.commit()
        yield name
        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE {name}")
        conn.commit()

    @FETCH_MODES
    def test_every_row_arrives_and_the_connection_still_works(self, conn, table, use_copy):
        rows = fetch(conn, f"SELECT id, s FROM {table}", use_copy).to_pylist()
        assert sorted(r["id"] for r in rows) == list(range(1, self.ROWS + 1))
        assert fetch(conn, "SELECT 42 AS n", use_copy).to_pylist() == [{"n": 42}]

    @FETCH_MODES
    def test_an_order_by_iris_will_not_wrap_still_describes(self, conn, table, use_copy):
        rows = fetch(conn, f"SELECT id FROM {table} ORDER BY id DESC", use_copy).to_pylist()
        # int(): embedded declares this column varchar (pinned in TestKnownTypeDeclarationDefects)
        assert [int(r["id"]) for r in rows[:3]] == [self.ROWS, self.ROWS - 1, self.ROWS - 2]
        assert len(rows) == self.ROWS
        assert fetch(conn, "SELECT 42 AS n", use_copy).to_pylist() == [{"n": 42}]

    @FETCH_MODES
    def test_bound_parameters_reach_the_query(self, conn, table, use_copy):
        with conn.cursor() as cur:
            cur.adbc_statement.set_options(**{"adbc.postgresql.use_copy": str(use_copy).lower()})
            cur.execute(f"SELECT id FROM {table} WHERE id > $1", parameters=(self.ROWS - 3,))
            rows = cur.fetch_arrow_table().to_pylist()
        assert sorted(r["id"] for r in rows) == [self.ROWS - 2, self.ROWS - 1, self.ROWS]

    @FETCH_MODES
    def test_an_int_column_is_declared_int4(self, request, target, conn, table, use_copy):
        if target[0] != "dbapi":
            request.applymarker(
                pytest.mark.xfail(
                    strict=True,
                    reason="051 US3: embedded guesses types from values; this INT column comes "
                    "back as string under ORDER BY and int64 without (found 2026-11-14, same at "
                    "3938502)",
                )
            )
        for sql in (f"SELECT id FROM {table} ORDER BY id DESC", f"SELECT id FROM {table}"):
            assert fetch(conn, sql, use_copy).schema.types == [pa.int32()], sql

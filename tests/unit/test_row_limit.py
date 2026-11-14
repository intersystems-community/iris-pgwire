"""Describe needs a statement's columns, not its rows.

Measured 2026-11-14 (IRIS 2026.2, 100,000 rows of 12 columns, adbc-driver-postgresql): Describe ran
the whole query to learn its column types, about 0.9 s of a 2.55 s read on the embedded backend,
and the Execute after it ran it again. On the DBAPI backend that showed up as fetchall() taking two
thirds of the server's time.

One row is fetched, not none: types are refined from the first row. The embedded backend stops
reading after it; the DBAPI backend cannot (see TestDbapiFetch), so it puts the cap in the SQL
instead (TestDescribeProbe).
"""

from __future__ import annotations

import asyncio
import struct
from unittest.mock import AsyncMock, MagicMock

import pytest

from iris_pgwire import row_limit
from iris_pgwire.dbapi_executor import DBAPIExecutor, describe_probe_sql
from iris_pgwire.iris_executor import IRISExecutor


class TestRowLimit:
    def test_no_limit_takes_every_row(self):
        assert list(row_limit.limited(iter(range(5)))) == [0, 1, 2, 3, 4]

    def test_within_at_most_only_that_many_rows_are_taken(self):
        with row_limit.at_most(1):
            assert list(row_limit.limited(iter(range(5)))) == [0]
        assert row_limit.current() is None

    def test_the_limit_reaches_a_worker_thread(self):
        async def run():
            with row_limit.at_most(1):
                return await asyncio.to_thread(row_limit.current)

        assert asyncio.run(run()) == 1


class _Result:
    """Iterates like an `iris.sql.exec` result and counts what was fetched."""

    _meta = None

    def __init__(self, n):
        self.n, self.fetched = n, 0

    def __iter__(self):
        for i in range(self.n):
            self.fetched += 1
            yield [i, f"r{i}"]


class TestEmbeddedMaterialiser:
    def test_under_a_limit_of_one_only_one_row_is_fetched(self, monkeypatch):
        executor = IRISExecutor.__new__(IRISExecutor)
        monkeypatch.setattr(
            executor, "_discover_metadata",
            lambda *a, **k: [
                {"name": "id", "type_oid": 23, "type_size": -1, "type_modifier": -1, "format_code": 0},
                {"name": "s", "type_oid": 1043, "type_size": -1, "type_modifier": -1, "format_code": 0},
            ],
            raising=False,
        )  # fmt: skip
        result = _Result(1000)
        sql = "SELECT id, s FROM t"
        with row_limit.at_most(1):
            rows, columns = executor._materialize_embedded_result(
                result, sql, sql.upper(), sql, None, executed_sql=sql, params=None
            )
        assert rows == [[0, "r0"]]
        assert result.fetched == 1
        assert [c["name"] for c in columns] == ["id", "s"]


class TestDbapiFetch:
    def test_under_a_limit_every_row_is_still_fetched(self):
        """The official driver loses its place if a large result is closed part-read
        (intersystems-irispython 5.4.1: "Message out of order" on the next statement), so the
        DBAPI backend reads to the end even at Describe."""
        executor = DBAPIExecutor.__new__(DBAPIExecutor)
        cursor = MagicMock()
        cursor.description = [("id", 4, None, None, None, None, None)]
        cursor.fetchall.return_value = [(7,), (8,)]
        cursor.fetchmany.side_effect = AssertionError("stopped part-way through the result")
        with row_limit.at_most(1):
            rows, _ = executor._fetch_standard_results(cursor)
        assert [tuple(r) for r in rows] == [(7,), (8,)]


def _protocol_with_select(name="s1"):
    from iris_pgwire.protocol import PGWireProtocol

    writer = MagicMock()
    writer.drain = AsyncMock()
    executor = MagicMock()
    executor.strict_single_connection = False
    executor.sql_parser.is_select_statement = MagicMock(return_value=True)
    executor.sql_parser.is_show_statement = MagicMock(return_value=False)
    executor.sql_parser.is_dml_statement = MagicMock(return_value=False)
    executor.metadata_cache = None
    seen = []

    async def execute_query(*args, **kwargs):
        seen.append(row_limit.current())
        return {"success": True, "rows": [[1]], "row_count": 1, "command_tag": "SELECT",
                "columns": [{"name": "id", "type_oid": 23, "type_size": 4, "type_modifier": -1}]}  # fmt: skip

    executor.execute_query = execute_query
    protocol = PGWireProtocol(MagicMock(), writer, executor, "c1")
    protocol.prepared_statements[name] = {
        "original_query": "SELECT id FROM t", "translated_query": "SELECT id FROM t",
        "param_types": [], "translation_metadata": {}, "needs_row_description": False,
    }  # fmt: skip
    return protocol, seen


class TestDescribeAsksForOneRow:
    @pytest.mark.asyncio
    async def test_describe_statement_runs_the_query_for_at_most_one_row(self):
        protocol, seen = _protocol_with_select()
        await protocol.handle_describe_message(b"S" + b"s1\x00")
        assert seen == [1]
        assert row_limit.current() is None

    @pytest.mark.asyncio
    async def test_describe_portal_runs_the_query_for_at_most_one_row(self):
        protocol, seen = _protocol_with_select()
        protocol.portals["p1"] = {"statement": "s1", "params": [], "result_formats": []}
        await protocol.handle_describe_message(b"P" + b"p1\x00")
        assert seen == [1]


class TestDescribeProbe:
    """At Describe the DBAPI backend runs `SELECT TOP n * FROM (query)` instead of the query.

    It cannot stop reading part-way (the driver desyncs), so the cap has to be in the SQL. IRIS
    gives the wrapped query the same description as the query itself (checked 2026-11-14 on
    2026.2 across 15 query shapes) but refuses the wrapper around an ORDER BY without TOP, a WITH
    and a FOR UPDATE; those, and anything else that is not a plain SELECT, run as they are.
    """

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT id FROM t",
            "  select id, n FROM t WHERE id = ?;",
            "SELECT TOP 5 * FROM t ORDER BY id DESC",
            "SELECT a FROM t UNION SELECT b FROM u",
            "SELECT s, COUNT(*) FROM t GROUP BY s",
        ],
    )
    def test_a_plain_select_is_wrapped(self, sql):
        body = sql.strip().rstrip(";")
        assert describe_probe_sql(sql, 1) == f"SELECT TOP 1 * FROM ({body}) AS pgwire_describe"

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM t ORDER BY id",
            "WITH c AS (SELECT 1 AS x) SELECT * FROM c",
            "SELECT id FROM t FOR UPDATE",
            "SELECT id INTO :x FROM t",
            "INSERT INTO t VALUES (1)",
            "UPDATE t SET a = 1",
            "CALL p()",
            "SHOW x",
            "",
        ],
    )
    def test_anything_else_runs_as_it_is(self, sql):
        assert describe_probe_sql(sql, 1) is None


class TestDbapiDescribeUsesTheProbe:
    def _executor(self):
        executor = DBAPIExecutor.__new__(DBAPIExecutor)
        return executor

    def _run(self, executor, cursor, sql, params=None):
        from iris_pgwire.sql_translator.returning_plan import ReturningPlan

        plan = ReturningPlan.from_sql(sql)
        return executor._execute_with_cursor(cursor, MagicMock(), plan, params, "s1", sql)

    def _cursor(self, rows):
        cursor = MagicMock()
        cursor.description = [("id", 4, None, None, 10, 0, 0)]
        cursor.fetchall.return_value = rows
        cursor.rowcount = len(rows)
        return cursor

    def test_under_a_limit_a_select_runs_wrapped_with_its_parameters(self):
        cursor = self._cursor([(7,)])
        with row_limit.at_most(1):
            rows, columns, _ = self._run(self._executor(), cursor, "SELECT id FROM t WHERE id > ?", [3])
        cursor.execute.assert_called_once_with(
            "SELECT TOP 1 * FROM (SELECT id FROM t WHERE id > ?) AS pgwire_describe", (3,)
        )
        assert [tuple(r) for r in rows] == [(7,)]
        assert [c["name"] for c in columns] == ["id"]

    def test_without_a_limit_the_query_runs_as_it_is(self):
        cursor = self._cursor([(7,), (8,)])
        rows, _, _ = self._run(self._executor(), cursor, "SELECT id FROM t")
        cursor.execute.assert_called_once_with("SELECT id FROM t")
        assert [tuple(r) for r in rows] == [(7,), (8,)]

    def test_if_iris_refuses_the_wrapper_the_query_runs_as_it_is(self):
        cursor = self._cursor([(7,), (8,)])
        calls = []

        def execute(sql, *args):
            calls.append(sql)
            if sql.startswith("SELECT TOP 1 * FROM ("):
                raise RuntimeError("[SQLCODE: <-1>:<Invalid SQL statement>]")

        cursor.execute.side_effect = execute
        with row_limit.at_most(1):
            rows, _, _ = self._run(self._executor(), cursor, "SELECT id FROM t WHERE x = 'ORDER'")
        assert calls == [
            "SELECT TOP 1 * FROM (SELECT id FROM t WHERE x = 'ORDER') AS pgwire_describe",
            "SELECT id FROM t WHERE x = 'ORDER'",
        ]
        assert [tuple(r) for r in rows] == [(7,), (8,)]

    def test_types_still_come_from_the_original_sql(self):
        # The SQL type resolver reads the statement; it must read the query, not the wrapper.
        cursor = self._cursor([(1,)])
        cursor.description = [("flag", 12, None, None, 50, 0, 1)]
        with row_limit.at_most(1):
            _, columns, _ = self._run(self._executor(), cursor, "SELECT CAST(1 AS BIT) AS flag FROM t")
        _, plain_columns, _ = self._run(self._executor(), self._cursor_like(cursor), "SELECT CAST(1 AS BIT) AS flag FROM t")
        assert columns == plain_columns

    @staticmethod
    def _cursor_like(cursor):
        other = MagicMock()
        other.description = cursor.description
        other.fetchall.return_value = [(1,)]
        other.rowcount = 1
        return other


class TestRowsBeforeAnEncodingErrorStillGoOut:
    """A value that cannot be encoded ends the result with an error, but the rows before it were
    sent first, as when each row was written as it was encoded."""

    def test_datarows(self):
        from iris_pgwire.protocol import PGWireProtocol
        from iris_pgwire.value_encoding import ValueEncodingError

        written = []
        writer = MagicMock()
        writer.write = written.append
        writer.drain = AsyncMock()
        protocol = PGWireProtocol(MagicMock(), writer, MagicMock(), "c1")
        protocol._current_result_formats = [1]
        rows = [(1,), (2,), ("not a number",), (4,)]
        with pytest.raises(ValueEncodingError):
            asyncio.run(protocol.send_data_rows_with_backpressure(rows, [{"type_oid": 23}]))
        sent = b"".join(written)
        assert sent == b"".join(
            b"D" + struct.pack("!IhI", 14, 1, 4) + struct.pack("!i", n) for n in (1, 2)
        )

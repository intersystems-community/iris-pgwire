"""COPY (query) TO STDOUT: the parser, the three formats, and the protocol flow.

Why this exists. The stock ADBC PostgreSQL driver, which dbt Fusion uses without ever setting
`adbc.postgresql.use_copy`, fetches every result with `COPY (query) TO STDOUT (FORMAT binary)`.
Measured on 2026-10-24, this server:

- did not parse an option list without WITH, so the statement failed outright;
- parsed FORMAT and then ignored it;
- sent the *key names of the result dictionary* ("success", "rows", "columns", ...) as CSV
  characters for every query, because the executor returns a dict and the export iterated it;
- sent CopyOutResponse before running the query, with a column count of 0 and always in text
  format, so a binary client was told the wrong thing before any data existed.

The binary framing here is PostgreSQL's (https://www.postgresql.org/docs/16/sql-copy.html): an
11-byte signature, a 4-byte flags word, a 4-byte header-extension length, then per row an int16 field
count and each field as an int32 length (-1 for NULL) and its bytes, and a trailer of int16 -1.
PostgreSQL puts the header in the first CopyData message with the first row and sends one row per
message; clients are written against that, so this does the same.
"""

from __future__ import annotations

import asyncio
import datetime
import struct
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from iris_pgwire.copy_export import (
    BINARY_HEADER,
    BINARY_TRAILER,
    ExportFormat,
    copy_out_response,
    export_messages,
    resolve_export_format,
)
from iris_pgwire.protocol import PGWireProtocol
from iris_pgwire.sql_translator.copy_parser import CopyCommandParser, CopyDirection


def parse(sql: str):
    return CopyCommandParser.parse(sql)


# ---------------------------------------------------------------------------
# parser
# ---------------------------------------------------------------------------


class TestParserAcceptsPostgresqlsOptionSyntax:
    """`[ WITH ] ( option [, ...] )`: the WITH is optional, and ADBC leaves it out."""

    def test_an_option_list_without_with(self):
        command = parse("COPY (SELECT 1 AS n) TO STDOUT (FORMAT binary)")
        assert command.direction == CopyDirection.TO_STDOUT
        assert command.query == "SELECT 1 AS n"
        assert command.csv_options.format == "BINARY"

    def test_with_still_works(self):
        command = parse("COPY (SELECT 1) TO STDOUT WITH (FORMAT csv, HEADER)")
        assert command.csv_options.format == "CSV" and command.csv_options.header

    def test_a_query_with_parentheses_inside(self):
        command = parse("COPY (SELECT (1 + 2) AS a, f(x) FROM t) TO STDOUT (FORMAT csv)")
        assert command.query == "SELECT (1 + 2) AS a, f(x) FROM t"

    def test_case_and_whitespace(self):
        command = parse("copy ( select 1 )  to   stdout   with  ( format  BINARY )")
        assert command.csv_options.format == "BINARY"

    def test_a_table_with_an_option_list_and_no_with(self):
        command = parse("COPY patients (id, name) TO STDOUT (FORMAT csv, DELIMITER ';')")
        assert command.table_name == "patients" and command.column_list == ["id", "name"]
        assert command.csv_options.delimiter == ";"

    def test_legacy_binary_keyword(self):
        assert parse("COPY (SELECT 1) TO STDOUT BINARY").csv_options.format == "BINARY"
        assert parse("COPY (SELECT 1) TO STDOUT WITH BINARY").csv_options.format == "BINARY"

    def test_with_no_options_the_format_is_not_explicit(self):
        command = parse("COPY (SELECT 1) TO STDOUT")
        assert "format" not in command.csv_options.explicit

    def test_explicit_options_are_recorded(self):
        command = parse("COPY (SELECT 1) TO STDOUT (FORMAT csv, DELIMITER '|', NULL 'x', HEADER)")
        assert {"format", "delimiter", "null", "header"} <= command.csv_options.explicit

    def test_from_stdin_is_unchanged(self):
        command = parse("COPY Patients FROM STDIN WITH (FORMAT CSV, HEADER)")
        assert command.direction == CopyDirection.FROM_STDIN and command.csv_options.header


# ---------------------------------------------------------------------------
# format resolution
# ---------------------------------------------------------------------------


def fmt(sql: str) -> ExportFormat:
    return resolve_export_format(parse(sql).csv_options)


class TestFormatDefaultsAreThoseOfPostgresql:
    def test_no_options_means_text_with_tabs_and_backslash_N(self):
        f = fmt("COPY (SELECT 1) TO STDOUT")
        assert (f.kind, f.delimiter, f.null) == ("text", "\t", "\\N")

    def test_csv_means_commas_and_an_empty_null(self):
        f = fmt("COPY (SELECT 1) TO STDOUT (FORMAT csv)")
        assert (f.kind, f.delimiter, f.null, f.quote) == ("csv", ",", "", '"')

    def test_csv_escape_defaults_to_the_quote_character(self):
        assert fmt("COPY (SELECT 1) TO STDOUT (FORMAT csv)").escape == '"'

    def test_explicit_options_win(self):
        f = fmt("COPY (SELECT 1) TO STDOUT (FORMAT csv, DELIMITER ';', NULL 'NA')")
        assert (f.delimiter, f.null) == (";", "NA")

    def test_binary(self):
        assert fmt("COPY (SELECT 1) TO STDOUT (FORMAT binary)").kind == "binary"

    @pytest.mark.parametrize(
        "options", ["HEADER", "DELIMITER ','", "NULL 'x'", "QUOTE '\"'", "ESCAPE '\\'"]
    )
    def test_binary_refuses_the_text_only_options_as_postgresql_does(self, options):
        with pytest.raises(ValueError, match="binary"):
            fmt(f"COPY (SELECT 1) TO STDOUT (FORMAT binary, {options})")

    def test_an_unknown_format_is_refused(self):
        with pytest.raises(ValueError, match="format"):
            fmt("COPY (SELECT 1) TO STDOUT (FORMAT parquet)")


# ---------------------------------------------------------------------------
# encoding
# ---------------------------------------------------------------------------

COLS = [
    {"name": "n", "type_oid": 23},
    {"name": "s", "type_oid": 25},
]


def run(sql: str, columns, rows) -> list[bytes]:
    return list(export_messages(fmt(sql), columns, rows))


class TestTextFormat:
    def test_rows_are_tab_separated_lines_with_backslash_N_for_null(self):
        out = run("COPY (SELECT 1) TO STDOUT", COLS, [(1, "a"), (2, None)])
        assert out == [b"1\ta\n", b"2\t\\N\n"]

    def test_the_escapes_postgresql_applies(self):
        out = run("COPY (SELECT 1) TO STDOUT", [{"name": "s", "type_oid": 25}],
                  [("a\tb\nc\\d\re",)])  # fmt: skip
        assert out == [b"a\\tb\\nc\\\\d\\re\n"]

    def test_booleans_dates_and_bytea_use_their_text_output(self):
        cols = [{"name": "b", "type_oid": 16}, {"name": "d", "type_oid": 1082},
                {"name": "y", "type_oid": 17}]  # fmt: skip
        out = run("COPY (SELECT 1) TO STDOUT", cols,
                  [(True, datetime.date(2026, 10, 24), b"\xde\xad")])  # fmt: skip
        assert out == [b"t\t2026-10-24\t\\\\xdead\n"]

    def test_header(self):
        out = run("COPY (SELECT 1) TO STDOUT (HEADER)", COLS, [(1, "a")])
        assert out == [b"n\ts\n", b"1\ta\n"]


class TestCsvFormat:
    def test_null_is_empty_and_an_empty_string_is_quoted_to_stay_distinct(self):
        out = run("COPY (SELECT 1) TO STDOUT (FORMAT csv)", COLS, [(1, ""), (2, None)])
        assert out == [b'1,""\n', b"2,\n"]

    def test_quoting_when_the_value_needs_it(self):
        out = run("COPY (SELECT 1) TO STDOUT (FORMAT csv)", [{"name": "s", "type_oid": 25}],
                  [('say "hi", ok',), ("line\nbreak",), ("plain",)])  # fmt: skip
        assert out == [b'"say ""hi"", ok"\n', b'"line\nbreak"\n', b"plain\n"]

    def test_a_value_equal_to_the_null_string_is_quoted(self):
        out = run("COPY (SELECT 1) TO STDOUT (FORMAT csv, NULL 'NA')",
                  [{"name": "s", "type_oid": 25}], [("NA",), (None,)])  # fmt: skip
        assert out == [b'"NA"\n', b"NA\n"]

    def test_header_and_delimiter(self):
        out = run("COPY (SELECT 1) TO STDOUT (FORMAT csv, HEADER, DELIMITER ';')", COLS, [(1, "a")])
        assert out == [b"n;s\n", b"1;a\n"]


class TestBinaryFormat:
    def test_the_framing_is_postgresqls(self):
        assert BINARY_HEADER == b"PGCOPY\n\xff\r\n\x00" + struct.pack("!ii", 0, 0)
        assert BINARY_TRAILER == struct.pack("!h", -1)

    def test_header_rides_with_the_first_row_one_row_per_message_trailer_alone(self):
        out = run("COPY (SELECT 1) TO STDOUT (FORMAT binary)", COLS, [(1, "a"), (2, "bc")])
        row1 = struct.pack("!h", 2) + struct.pack("!ii", 4, 1) + struct.pack("!i", 1) + b"a"
        row2 = struct.pack("!h", 2) + struct.pack("!ii", 4, 2) + struct.pack("!i", 2) + b"bc"
        assert out == [BINARY_HEADER + row1, row2, BINARY_TRAILER]

    def test_null_is_a_length_of_minus_one(self):
        out = run("COPY (SELECT 1) TO STDOUT (FORMAT binary)", COLS, [(None, None)])
        assert out[0] == BINARY_HEADER + struct.pack("!h", 2) + struct.pack("!ii", -1, -1)

    def test_no_rows_is_one_message_of_header_and_trailer(self):
        out = run("COPY (SELECT 1) TO STDOUT (FORMAT binary)", COLS, [])
        assert out == [BINARY_HEADER + BINARY_TRAILER]

    def test_values_use_the_shared_encoder_so_dates_and_numerics_are_structured(self):
        cols = [{"name": "d", "type_oid": 1082}, {"name": "x", "type_oid": 1700}]
        out = run("COPY (SELECT 1) TO STDOUT (FORMAT binary)", cols,
                  [(datetime.date(2026, 10, 24), Decimal("1.50"))])  # fmt: skip
        body = out[0][len(BINARY_HEADER):]
        assert body[2:10] == struct.pack("!ii", 4, 9793)  # date: int32 days since 2000-01-01
        # numeric 1.50: 8-byte header + two 2-byte digit groups = 12 bytes, 2 digit groups
        assert body[10:14] == struct.pack("!i", 12) and body[14:16] == struct.pack("!h", 2)

    def test_a_value_that_cannot_be_encoded_raises_rather_than_sending_text(self):
        from iris_pgwire.value_encoding import ValueEncodingError

        with pytest.raises(ValueEncodingError):
            run("COPY (SELECT 1) TO STDOUT (FORMAT binary)", COLS, [("not-an-int", "a")])


class TestCopyOutResponse:
    def test_text(self):
        assert copy_out_response(fmt("COPY (SELECT 1) TO STDOUT"), 2) == (
            b"H" + struct.pack("!I", 4 + 1 + 2 + 2 * 2) + b"\x00" + struct.pack("!H", 2)
            + struct.pack("!HH", 0, 0)
        )  # fmt: skip

    def test_binary_declares_binary_overall_and_for_every_column(self):
        message = copy_out_response(fmt("COPY (SELECT 1) TO STDOUT (FORMAT binary)"), 3)
        assert message[0:1] == b"H"
        assert message[5:6] == b"\x01"
        assert struct.unpack("!H", message[6:8])[0] == 3
        assert struct.unpack("!HHH", message[8:14]) == (1, 1, 1)


# ---------------------------------------------------------------------------
# the protocol flow
# ---------------------------------------------------------------------------


class Wire:
    def __init__(self):
        self.out = bytearray()

    def write(self, data):
        self.out += data

    async def drain(self):
        pass

    def close(self):
        pass

    async def wait_closed(self):
        pass

    def get_extra_info(self, name, default=None):
        return default


def messages(data: bytes) -> list[tuple[bytes, bytes]]:
    out, pos = [], 0
    while pos < len(data):
        kind = data[pos : pos + 1]
        (length,) = struct.unpack("!I", data[pos + 1 : pos + 5])
        out.append((kind, data[pos + 5 : pos + 1 + length]))
        pos += 1 + length
    return out


def make_protocol(result: dict):
    executor = MagicMock()
    executor.execute_query = AsyncMock(return_value=result)
    wire = Wire()
    protocol = PGWireProtocol(asyncio.StreamReader(), wire, executor, "unit-copy")
    return protocol, wire, executor


OK = {
    "success": True,
    "rows": [(1, "a"), (2, "bc")],
    "columns": [{"name": "n", "type_oid": 23}, {"name": "s", "type_oid": 25}],
    "row_count": 2,
    "command_tag": "SELECT",
}


class TestTheCopyFlow:
    async def test_binary_copy_sends_the_response_the_rows_then_done_complete_ready(self):
        protocol, wire, executor = make_protocol(OK)
        await protocol.handle_copy_command("COPY (SELECT n, s FROM t) TO STDOUT (FORMAT binary)")
        kinds = [k for k, _ in messages(bytes(wire.out))]
        assert kinds == [b"H", b"d", b"d", b"d", b"c", b"C", b"Z"]
        parsed = dict(messages(bytes(wire.out)))
        assert parsed[b"C"] == b"COPY 2\x00"
        executor.execute_query.assert_awaited_once()

    async def test_the_response_carries_the_real_column_count_and_format(self):
        protocol, wire, _ = make_protocol(OK)
        await protocol.handle_copy_command("COPY (SELECT n, s FROM t) TO STDOUT (FORMAT binary)")
        body = messages(bytes(wire.out))[0][1]
        assert body[0] == 1 and struct.unpack("!H", body[1:3])[0] == 2

    async def test_the_query_runs_before_anything_is_sent(self):
        protocol, wire, executor = make_protocol(OK)
        seen_before = []

        async def run(*args, **kwargs):
            seen_before.append(bytes(wire.out))
            return OK

        executor.execute_query = run
        await protocol.handle_copy_command("COPY (SELECT 1) TO STDOUT")
        assert seen_before == [b""], "CopyOutResponse must not precede the query"

    async def test_the_count_is_exact_not_counted_from_newlines(self):
        result = dict(OK, rows=[(1, "a\nb"), (2, "c\nd")])
        protocol, wire, _ = make_protocol(result)
        await protocol.handle_copy_command("COPY (SELECT 1) TO STDOUT (FORMAT csv)")
        assert dict(messages(bytes(wire.out)))[b"C"] == b"COPY 2\x00"

    async def test_a_failing_query_is_an_error_not_a_copy(self):
        failure = {"success": False, "error": "Table 'SQLUser.NOPE' not found"}
        protocol, wire, _ = make_protocol(failure)
        await protocol.handle_copy_command("COPY (SELECT * FROM nope) TO STDOUT (FORMAT binary)")
        kinds = [k for k, _ in messages(bytes(wire.out))]
        assert kinds == [b"E", b"Z"], "no CopyOutResponse for a query that never ran"

    async def test_an_unencodable_value_is_an_error_message_not_text_bytes(self):
        bad = dict(OK, rows=[("not-an-int", "a")])
        protocol, wire, _ = make_protocol(bad)
        await protocol.handle_copy_command("COPY (SELECT 1) TO STDOUT (FORMAT binary)")
        kinds = [k for k, _ in messages(bytes(wire.out))]
        assert kinds[-2:] == [b"E", b"Z"]
        assert b"c" not in kinds, "an aborted copy must not be reported as done"

    async def test_the_rows_before_an_unencodable_value_are_still_sent(self):
        # Rows go to the socket in batches; a bad value must not swallow the good rows batched
        # before it. They were sent when each row was written as it was encoded.
        bad = dict(OK, rows=[(1, "a"), (2, "b"), ("not-an-int", "c")])
        protocol, wire, _ = make_protocol(bad)
        await protocol.handle_copy_command("COPY (SELECT 1) TO STDOUT (FORMAT binary)")
        sent = messages(bytes(wire.out))
        assert [k for k, _ in sent] == [b"H", b"d", b"d", b"E", b"Z"]
        assert sent[1][1] == BINARY_HEADER + struct.pack("!hi", 2, 4) + struct.pack("!i", 1) + (
            struct.pack("!i", 1) + b"a"
        )

    async def test_text_copy_without_any_options_is_postgresql_text(self):
        protocol, wire, _ = make_protocol(OK)
        await protocol.handle_copy_command("COPY (SELECT n, s FROM t) TO STDOUT")
        data = [b for k, b in messages(bytes(wire.out)) if k == b"d"]
        assert data == [b"1\ta\n", b"2\tbc\n"]

    async def test_a_bad_option_is_a_syntax_error(self):
        protocol, wire, _ = make_protocol(OK)
        await protocol.handle_copy_command("COPY (SELECT 1) TO STDOUT (FORMAT binary, HEADER)")
        kinds = [k for k, _ in messages(bytes(wire.out))]
        assert kinds == [b"E", b"Z"]


class TestCopyOverTheExtendedProtocol:
    """The ADBC driver does not send COPY as a simple query. It sends Parse, Bind (with a binary
    result-format code), Describe, Execute, Sync. Measured on the wire, 2026-10-24: Describe on the
    portal answers NoData, then Execute handed the COPY text to IRIS, which refused it.

    PostgreSQL runs the copy at Execute and sends ReadyForQuery only after Sync, so the copy must
    not send one itself."""

    @staticmethod
    def stage(protocol, sql: str, result_formats=(1,)):
        protocol.prepared_statements[""] = {
            "query": sql,
            "original_query": sql,
            "translated_query": sql,
            "translation_metadata": {},
            "param_types": [],
        }
        protocol.portals[""] = {"statement": "", "params": [], "result_formats": list(result_formats)}

    async def test_execute_runs_the_copy_and_does_not_send_ready_for_query(self):
        protocol, wire, executor = make_protocol(OK)
        self.stage(protocol, "COPY (SELECT n, s FROM t) TO STDOUT (FORMAT binary)")
        await protocol.handle_execute_message(b"\x00" + struct.pack("!I", 0))
        kinds = [k for k, _ in messages(bytes(wire.out))]
        assert kinds == [b"H", b"d", b"d", b"d", b"c", b"C"], "no ReadyForQuery before Sync"
        assert dict(messages(bytes(wire.out)))[b"C"] == b"COPY 2\x00"

    async def test_the_copy_text_is_never_handed_to_iris_as_a_statement(self):
        protocol, _, executor = make_protocol(OK)
        self.stage(protocol, "COPY (SELECT n, s FROM t) TO STDOUT (FORMAT binary)")
        await protocol.handle_execute_message(b"\x00" + struct.pack("!I", 0))
        sent = [call.args[0] for call in executor.execute_query.await_args_list]
        assert all("COPY" not in sql.upper() for sql in sent), sent

    async def test_a_failing_query_is_an_error_without_ready_for_query(self):
        failure = {"success": False, "error": "Table 'SQLUser.NOPE' not found"}
        protocol, wire, _ = make_protocol(failure)
        self.stage(protocol, "COPY (SELECT * FROM nope) TO STDOUT (FORMAT binary)")
        await protocol.handle_execute_message(b"\x00" + struct.pack("!I", 0))
        assert [k for k, _ in messages(bytes(wire.out))] == [b"E"]

    async def test_a_bad_option_is_an_error_without_ready_for_query(self):
        protocol, wire, _ = make_protocol(OK)
        self.stage(protocol, "COPY (SELECT 1) TO STDOUT (FORMAT binary, HEADER)")
        await protocol.handle_execute_message(b"\x00" + struct.pack("!I", 0))
        assert [k for k, _ in messages(bytes(wire.out))] == [b"E"]


class TestColumnNamesAndExecutorFailureModes:
    async def test_the_header_names_columns_as_row_description_does(self):
        """IRIS returns `N`; RowDescription sends `n`. A COPY header that disagrees tells a
        client two different names for one column. (Found against the DBAPI backend.)"""
        result = dict(OK, columns=[{"name": "N", "type_oid": 23}, {"name": "S", "type_oid": 25}])
        protocol, wire, _ = make_protocol(result)
        await protocol.handle_copy_command("COPY (SELECT 1) TO STDOUT (FORMAT csv, HEADER)")
        data = [b for k, b in messages(bytes(wire.out)) if k == b"d"]
        assert data[0] == b"n,s\n"

    async def test_an_executor_that_raises_is_reported_with_its_sqlstate(self):
        """The embedded executor returns {"success": False}; the DBAPI executor re-raises. Both
        must reach the client as the same ErrorResponse, not as a dropped connection (08000)."""
        protocol, wire, executor = make_protocol(OK)
        executor.execute_query = AsyncMock(
            side_effect=RuntimeError("<SQL ERROR> [SQLCODE: <-30>:<Table or view not found>]")
        )
        await protocol.handle_copy_command("COPY (SELECT * FROM nope) TO STDOUT (FORMAT binary)")
        out = messages(bytes(wire.out))
        assert [k for k, _ in out] == [b"E", b"Z"]
        assert b"42P01" in out[0][1], "a missing table is 42P01, not a connection exception"
        assert b"08000" not in out[0][1]

    async def test_the_same_failure_in_the_extended_protocol_sends_no_ready_for_query(self):
        protocol, wire, executor = make_protocol(OK)
        executor.execute_query = AsyncMock(
            side_effect=RuntimeError("<SQL ERROR> [SQLCODE: <-30>:<Table or view not found>]")
        )
        TestCopyOverTheExtendedProtocol.stage(protocol, "COPY (SELECT * FROM nope) TO STDOUT")
        await protocol.handle_execute_message(b"\x00" + struct.pack("!I", 0))
        assert [k for k, _ in messages(bytes(wire.out))] == [b"E"]

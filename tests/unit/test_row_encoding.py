"""Whole-row encoding for DataRow and binary COPY, with and without psycopg's C encoders.

`row_encoding` builds the bytes of a result row once per row instead of once per value. When
psycopg's C extension is installed it hands rows to it, but psycopg encodes by type OID without
checking the value: it wraps an int4 of 2**31 to -2**31, takes the string 'f' for true and
re-quotes a JSON string. So it may only see a row whose every value is exactly the Python type it
expects, in range. These tests hold both paths to the bytes `encode_binary` gives, which are
PostgreSQL's (see `binary_value_fixtures.py`), and to its refusals.
"""

from __future__ import annotations

import datetime
import random
import struct
import uuid
from decimal import Decimal

import pytest

from iris_pgwire.row_encoding import BinaryRowEncoder, data_row_encoder, psycopg_available
from iris_pgwire.value_encoding import ValueEncodingError, encode_binary

from .binary_value_fixtures import CASES

PATHS = [
    pytest.param(False, id="python"),
    pytest.param(
        True,
        id="psycopg",
        marks=pytest.mark.skipif(not psycopg_available(), reason="psycopg[binary] not installed"),
    ),
]


def reference_body(oids, row):
    """PostgreSQL's tuple body: a field count, then each field's length and bytes (-1 for NULL)."""
    out = struct.pack("!h", len(oids))
    for oid, value in zip(oids, row, strict=True):
        if value is None:
            out += struct.pack("!i", -1)
        else:
            encoded = encode_binary(oid, value)
            out += struct.pack("!i", len(encoded)) + encoded
    return out


BENCH_OIDS = [23, 23, 20, 1700, 1700, 701, 701, 1043, 1043, 1114, 1082, 1043]


def bench_rows(n, seed=21):
    """Rows shaped like the DBAPI backend's: the types its driver returns, about 20% NULLs."""
    rng = random.Random(seed)
    words = ["alpha", "Zürich", "東京", "naïve", ""]
    t0 = datetime.datetime(2020, 1, 1)

    def maybe(value):
        return None if rng.random() < 0.2 else value

    return [
        (
            i,
            maybe(rng.randint(-(2**31), 2**31 - 1)),
            rng.randint(-(2**63), 2**63 - 1),
            maybe(Decimal(rng.randint(-(10**11), 10**11)).scaleb(-4)),
            Decimal(rng.randint(-(10**9), 10**9)).scaleb(-2),
            rng.uniform(-1e6, 1e6),
            maybe(rng.random()),
            rng.choice(words),
            " ".join(rng.choice(words) for _ in range(rng.randint(0, 6))),
            maybe(t0 + datetime.timedelta(microseconds=rng.randint(-(10**15), 10**15))),
            (t0 + datetime.timedelta(days=rng.randint(-700_000, 2_900_000))).date(),
            maybe(f"row {i} ✓"),
        )
        for i in range(n)
    ]


@pytest.mark.parametrize("accelerate", PATHS)
class TestBinaryRows:
    def test_bench_shaped_rows_give_postgresqls_bytes(self, accelerate):
        encoder = BinaryRowEncoder(BENCH_OIDS, accelerate=accelerate)
        assert encoder.accelerated is accelerate  # every bench column is one psycopg can take
        for row in bench_rows(5_000):
            assert encoder.encode(row) == reference_body(BENCH_OIDS, row), row

    @pytest.mark.parametrize("label,oid,expected_hex,values", CASES, ids=[c[0] for c in CASES])
    def test_every_captured_case_in_a_row(self, accelerate, label, oid, expected_hex, values):
        encoder = BinaryRowEncoder([23, oid], accelerate=accelerate)
        for value in values:
            body = encoder.encode((1, value))
            field = bytes.fromhex(expected_hex)
            assert body == struct.pack("!hi", 2, 4) + b"\x00\x00\x00\x01" + struct.pack(
                "!i", len(field)
            ) + field, (label, value)

    @pytest.mark.parametrize(
        "oid,value",
        [
            (23, "123"),  # a string in an integer column: psycopg refuses it, ours parses it
            (23, True),  # a bool is not an int here
            (16, "f"),  # psycopg would send true
            (114, '{"a": 1}'),  # psycopg would quote it again
            (1700, 7),  # psycopg lays an int out with different digits
            (1700, 1.5),
            (1083, "12:34:56"),
            (1082, 9793),  # the embedded backend's PostgreSQL day number
            (1114, datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC)),
            (2950, "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"),
            (20, -(2**63)),
        ],
    )
    def test_values_psycopg_would_misencode_still_get_our_bytes(self, accelerate, oid, value):
        encoder = BinaryRowEncoder([oid], accelerate=accelerate)
        assert encoder.encode((value,)) == reference_body([oid], (value,))

    @pytest.mark.parametrize(
        "oid,value",
        [
            (23, 2**31),  # psycopg wraps it to -2**31
            (23, -(2**31) - 1),
            (21, 2**15),  # psycopg wraps it
            (20, 2**63),
            (1700, Decimal("Infinity")),  # psycopg would send it; this server refuses
            (1700, Decimal("-Infinity")),
            (25, "a\udcffb"),
        ],
    )
    def test_refuses_what_encode_binary_refuses(self, accelerate, oid, value):
        encoder = BinaryRowEncoder([oid], accelerate=accelerate)
        with pytest.raises(ValueEncodingError):
            encoder.encode((value,))

    def test_one_bad_row_does_not_change_the_rows_after_it(self, accelerate):
        encoder = BinaryRowEncoder([23, 1043], accelerate=accelerate)
        rows = [(1, "a"), ("2", "b"), (3, "c")]
        assert [encoder.encode(r) for r in rows] == [reference_body([23, 1043], r) for r in rows]

    def test_all_null_and_empty_rows(self, accelerate):
        encoder = BinaryRowEncoder([23, 1700, 1043], accelerate=accelerate)
        assert encoder.encode((None, None, None)) == reference_body([23, 1700, 1043], [None] * 3)
        assert BinaryRowEncoder([], accelerate=accelerate).encode(()) == struct.pack("!h", 0)

    def test_uuid_bytes_bool_timestamptz(self, accelerate):
        oids = [2950, 17, 16, 1184]
        row = (uuid.uuid4(), b"\x00\xff", False, datetime.datetime(2026, 1, 1, 12))
        assert BinaryRowEncoder(oids, accelerate=accelerate).encode(row) == reference_body(oids, row)


class TestAcceleration:
    def test_off_when_asked(self):
        assert BinaryRowEncoder([23], accelerate=False).accelerated is False

    def test_a_column_psycopg_cannot_take_turns_it_off_for_the_result(self):
        # vector (16388) has no psycopg dumper; text arrays given as literals are ours alone.
        assert BinaryRowEncoder([23, 16388], accelerate=True).accelerated is False

    @pytest.mark.skipif(not psycopg_available(), reason="psycopg[binary] not installed")
    def test_on_by_default_when_installed_and_every_column_can_use_it(self):
        assert BinaryRowEncoder(BENCH_OIDS, accelerate=True).accelerated is True


class TestDataRow:
    """`data_row_encoder` gives the whole DataRow message, as `send_data_row` built it."""

    @pytest.mark.parametrize("accelerate", PATHS)
    def test_all_binary(self, accelerate):
        encode = data_row_encoder(BENCH_OIDS, [1], accelerate=accelerate)
        for row in bench_rows(500):
            body = reference_body(BENCH_OIDS, row)
            assert encode(row) == b"D" + struct.pack("!I", len(body) + 4) + body

    def test_text_format_is_strs_and_bools_as_t_or_f(self):
        encode = data_row_encoder([23, 16, 16, 1043, 701], [0])
        message = encode((42, 1, "false", "hé", 2.5))
        fields = [b"42", b"t", b"f", "hé".encode(), b"2.5"]
        body = struct.pack("!h", 5) + b"".join(struct.pack("!i", len(f)) + f for f in fields)
        assert message == b"D" + struct.pack("!I", len(body) + 4) + body

    def test_text_format_is_postgresqls_text_output(self):
        # Expected text captured from PostgreSQL 16 (iris-pgwire-pgref, TimeZone Etc/UTC):
        # SELECT '\xdead'::bytea, '{"a": 1}'::jsonb, ARRAY[1,2,3], ARRAY['a b','c'],
        #        1E+14::numeric, 'inf'::float8, '-inf'::float8, 'nan'::float8,
        #        '2026-11-14 12:34:56.5+00'::timestamptz, 1e20::float8, 12.50::numeric(10,2)
        oids = [17, 3802, 1007, 1009, 1700, 701, 701, 701, 1184, 701, 1700]
        row = (
            b"\xde\xad",
            {"a": 1},
            [1, 2, 3],
            ["a b", "c"],
            Decimal("1E+14"),
            float("inf"),
            float("-inf"),
            float("nan"),
            datetime.datetime(2026, 11, 14, 12, 34, 56, 500000, tzinfo=datetime.UTC),
            1e20,
            Decimal("12.50"),
        )
        fields = [
            b"\\xdead",
            b'{"a": 1}',
            b"{1,2,3}",
            b'{"a b",c}',
            b"100000000000000",
            b"Infinity",
            b"-Infinity",
            b"NaN",
            b"2026-11-14 12:34:56.5+00",
            b"1e+20",
            b"12.50",
        ]
        body = struct.pack("!h", len(fields)) + b"".join(
            struct.pack("!i", len(f)) + f for f in fields
        )
        assert data_row_encoder(oids, [0])(row) == b"D" + struct.pack("!I", len(body) + 4) + body

    def test_timestamps_given_as_strings_are_postgresqls_text_too(self):
        # The embedded backend returns a TIMESTAMP as a string with six fraction digits.
        # PostgreSQL 16 (TimeZone Etc/UTC) sends '2026-11-14 12:34:56.5'::timestamp as below.
        oids = [1114, 1114, 1184]
        row = (
            "2026-11-14 12:34:56.500000",
            "2026-11-14 12:34:56.000000",
            "2026-11-14 12:34:56.5+00",
        )
        fields = [b"2026-11-14 12:34:56.5", b"2026-11-14 12:34:56", b"2026-11-14 12:34:56.5+00"]
        body = struct.pack("!h", 3) + b"".join(struct.pack("!i", len(f)) + f for f in fields)
        assert data_row_encoder(oids, [0])(row) == b"D" + struct.pack("!I", len(body) + 4) + body

    def test_a_timestamp_string_that_does_not_parse_is_sent_as_it_is(self):
        message = data_row_encoder([1114], [0])(("infinity",))
        body = struct.pack("!h", 1) + struct.pack("!i", 8) + b"infinity"
        assert message == b"D" + struct.pack("!I", len(body) + 4) + body

    def test_mixed_formats_and_a_type_with_no_binary_form(self):
        # Per-column format codes; a binary column whose type has no binary form sends its text.
        encode = data_row_encoder([23, 23, 999_999], [0, 1, 1])
        message = encode((7, 7, "x"))
        fields = [b"7", struct.pack("!i", 7), b"x"]
        body = struct.pack("!h", 3) + b"".join(struct.pack("!i", len(f)) + f for f in fields)
        assert message == b"D" + struct.pack("!I", len(body) + 4) + body

    def test_short_rows_are_padded_with_nulls(self):
        message = data_row_encoder([23, 23], [0])((1,))
        body = struct.pack("!h", 2) + struct.pack("!i", 1) + b"1" + struct.pack("!i", -1)
        assert message == b"D" + struct.pack("!I", len(body) + 4) + body


class TestWhatTheOldDataRowPathDid:
    """Behaviour of the DataRow code this replaced (`send_data_row`), kept byte for byte."""

    def test_binary_on_a_type_with_no_binary_form_sends_its_text(self):
        # timetz (1266) has no binary encoder here: the old code sent str(value), not an error.
        message = data_row_encoder([1266, 23], [1])(("12:00:00+00", 5))
        fields = [b"12:00:00+00", struct.pack("!i", 5)]
        body = struct.pack("!h", 2) + b"".join(struct.pack("!i", len(f)) + f for f in fields)
        assert message == b"D" + struct.pack("!I", len(body) + 4) + body

    def test_an_unknown_format_code_sends_str_even_for_a_bool(self):
        message = data_row_encoder([16], [2])((True,))
        body = struct.pack("!h", 1) + struct.pack("!i", 4) + b"True"
        assert message == b"D" + struct.pack("!I", len(body) + 4) + body

    def test_the_field_count_is_unsigned(self):
        oids = [23] * 40_000
        message = data_row_encoder(oids, [0])((None,) * 40_000)
        assert message[5:7] == struct.pack("!H", 40_000)


@pytest.mark.skipif(not psycopg_available(), reason="psycopg[binary] not installed")
class TestPsycopgIsReallyUsed:
    def test_matching_rows_never_reach_our_encoder(self, monkeypatch):
        # If psycopg's internal function changed, every row would quietly fall back: slower, not
        # wrong, and invisible. This fails instead.
        encoder = BinaryRowEncoder(BENCH_OIDS)
        monkeypatch.setattr(encoder, "_encode_here", lambda row: pytest.fail(f"fell back: {row}"))
        for row in bench_rows(200):
            encoder.encode(row)


@pytest.mark.skipif(not psycopg_available(), reason="psycopg[binary] not installed")
class TestPsycopgSelfCheck:
    def test_a_psycopg_that_encodes_differently_is_not_used(self, monkeypatch):
        import iris_pgwire.row_encoding as module

        def wrong(row, transformer, buffer):
            buffer += b"not what we send"

        monkeypatch.setattr(module, "_format_row_binary", wrong)
        monkeypatch.setattr(module, "_agrees", None)
        assert module.psycopg_available() is False
        assert BinaryRowEncoder(BENCH_OIDS).accelerated is False

    def test_the_check_itself_passes_cleanly_on_an_installed_psycopg(self, monkeypatch):
        # It once recursed (the reference encoder asked psycopg_available again) and only came
        # out True because an outer call overwrote the inner failure.
        import iris_pgwire.row_encoding as module

        monkeypatch.setattr(module, "_agrees", None)
        warnings = []
        monkeypatch.setattr(module.logger, "warning", lambda *a, **k: warnings.append((a, k)))
        assert module._psycopg_agrees() is True
        assert warnings == []

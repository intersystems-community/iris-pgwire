"""Binary encoding of result values, checked against PostgreSQL's own bytes.

A binary-format client (the ADBC PostgreSQL driver, psycopg in binary mode, asyncpg) decodes each
field by the type OID it was told, with no recovery if the bytes are shaped wrong. The expected
bytes in `binary_value_fixtures.py` were captured from a real PostgreSQL 16 by
`scripts/capture_binary_values.py`, so a pass here means a client that decodes PostgreSQL's output
decodes ours.

Before this module the encoder handled integers, floats, bool and timestamp, and for everything
else (date, time, bytea, uuid, jsonb, arrays, vector, a numeric that was not already a Decimal) it
sent `str(value)` as if it were the binary form, and on any failure "fell back to text" with only a
log line. That is the silent degradation Constitution Principle I forbids.
"""

from __future__ import annotations

import datetime
import math
import uuid
from decimal import Decimal

import pytest

from iris_pgwire.value_encoding import (
    ValueEncodingError,
    binary_encoding_is_defined,
    encode_binary,
    encode_text,
)

from .binary_value_fixtures import CASES

ALL = [
    pytest.param(oid, value, expected, id=f"{label}|{value!r}"[:80])
    for label, oid, expected, values in CASES
    for value in values
]


@pytest.mark.parametrize("oid,value,expected_hex", ALL)
def test_encodes_exactly_as_postgresql_does(oid, value, expected_hex):
    assert encode_binary(oid, value).hex() == expected_hex


class TestWhatTheOracleCovers:
    def test_every_type_the_server_describes_as_binary_encodable_has_a_case(self):
        covered = {oid for _, oid, _, _ in CASES}
        # The scalar and array types a binary client is told about, minus the ones whose binary
        # form is the text bytes themselves.
        needing_a_case = {16, 17, 20, 21, 23, 26, 700, 701, 1082, 1083, 1114, 1184, 1700, 2950,
                          3802, 1007, 1009, 1016, 16388}  # fmt: skip
        assert needing_a_case <= covered


class TestRefusesToGuess:
    @pytest.mark.parametrize(
        "oid,value",
        [
            (23, "not a number"),
            (23, 2**40),
            (21, 2**20),
            (1082, "not a date"),
            (1083, "25:99:99"),
            (1114, "yesterday"),
            (2950, "not-a-uuid"),
            (1700, "twelve"),
            (1007, "{1,2"),
            (1007, [1, "x"]),
            (16388, "[a,b]"),
            (17, 12345),
            (3802, "{not json"),
        ],
    )
    def test_a_value_that_cannot_be_encoded_raises_instead_of_sending_text(self, oid, value):
        with pytest.raises(ValueEncodingError):
            encode_binary(oid, value)

    def test_the_error_names_the_type_and_the_value(self):
        with pytest.raises(ValueEncodingError, match=r"1082.*not a date"):
            encode_binary(1082, "not a date")


class TestTypesWhoseBinaryFormIsTheText:
    @pytest.mark.parametrize("oid", [25, 1043, 1042, 19, 705])
    def test_text_like_types_send_utf8(self, oid):
        assert encode_binary(oid, "héllo") == "héllo".encode()

    def test_an_unknown_oid_is_not_defined(self):
        assert not binary_encoding_is_defined(999999)
        assert binary_encoding_is_defined(23) and binary_encoding_is_defined(1007)
        assert binary_encoding_is_defined(25)


class TestNumericEdges:
    def test_nan_encodes_with_the_nan_sign(self):
        assert encode_binary(1700, float("nan")).hex() == encode_binary(1700, Decimal("NaN")).hex()

    def test_infinity_is_not_a_numeric(self):
        with pytest.raises(ValueEncodingError):
            encode_binary(1700, math.inf)

    def test_a_python_float_does_not_leak_binary_noise(self):
        # 0.1 is not exactly representable; the value IRIS meant is the shortest repr.
        assert encode_binary(1700, 0.1) == encode_binary(1700, Decimal("0.1"))


class TestTimestampsAreUtcNotLocal:
    def test_timestamptz_treats_a_naive_value_as_utc(self):
        naive = datetime.datetime(2026, 10, 24, 12, 34, 56)
        aware = naive.replace(tzinfo=datetime.UTC)
        assert encode_binary(1184, naive) == encode_binary(1184, aware)

    def test_an_offset_is_applied(self):
        plus_two = datetime.timezone(datetime.timedelta(hours=2))
        a = datetime.datetime(2026, 10, 24, 14, 34, 56, tzinfo=plus_two)
        b = datetime.datetime(2026, 10, 24, 12, 34, 56, tzinfo=datetime.UTC)
        assert encode_binary(1184, a) == encode_binary(1184, b)


class TestUuidAcceptsTheFormsIrisProduces:
    def test_sixteen_raw_bytes(self):
        u = uuid.UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11")
        assert encode_binary(2950, u.bytes) == u.bytes

    def test_braces_and_case_are_tolerated(self):
        assert encode_binary(2950, "{A0EEBC99-9C0B-4EF8-BB6D-6BB9BD380A11}") == bytes.fromhex(
            "a0eebc999c0b4ef8bb6d6bb9bd380a11"
        )


class TestTextForCopy:
    """The text form is what PostgreSQL's COPY text/CSV and a text DataRow carry."""

    @pytest.mark.parametrize(
        "oid,value,expected",
        [
            (16, True, "t"), (16, 0, "f"), (16, "t", "t"),
            (23, 5, "5"), (25, "abc", "abc"),
            (701, 2.5, "2.5"),
            (1082, datetime.date(2026, 10, 24), "2026-10-24"),
            (1082, 9793, "2026-10-24"),
            (1083, datetime.time(12, 34, 56), "12:34:56"),
            (1083, datetime.time(12, 34, 56, 789012), "12:34:56.789012"),
            (1114, datetime.datetime(2026, 10, 24, 12, 34, 56), "2026-10-24 12:34:56"),
            (1114, datetime.datetime(2026, 10, 24, 12, 34, 56, 5), "2026-10-24 12:34:56.000005"),
            (17, b"\xde\xad", "\\xdead"),
            (2950, uuid.UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"),
             "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"),
            (1700, Decimal("1.50"), "1.50"),
        ],
    )  # fmt: skip
    def test_text_form(self, oid, value, expected):
        assert encode_text(oid, value) == expected

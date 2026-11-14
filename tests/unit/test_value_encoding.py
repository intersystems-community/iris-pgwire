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
import random
import uuid
from decimal import Decimal

import pytest

from iris_pgwire.value_encoding import (
    ValueEncodingError,
    binary_encoder,
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


# ---------------------------------------------------------------------------------------------
# binary_encoder: the per-column encoder chosen once per result
# ---------------------------------------------------------------------------------------------


class TestPerColumnEncoder:
    """`binary_encoder(oid)` is what a result's columns use, once per column, instead of looking the
    type up for every value. It must give the same bytes as `encode_binary`, and refuse the same
    values, for every input; its fast paths are only allowed to be faster."""

    @pytest.mark.parametrize("oid,value,expected_hex", ALL)
    def test_gives_postgresqls_bytes(self, oid, value, expected_hex):
        assert binary_encoder(oid)(value).hex() == expected_hex

    @pytest.mark.parametrize(
        "oid,value",
        [
            (23, "not a number"),
            (23, 2**40),
            (23, 2**31),
            (21, 2**20),
            (20, 2**63),
            (1082, "not a date"),
            (1114, "yesterday"),
            (1700, "twelve"),
            (1700, Decimal("Infinity")),
            (701, "x"),
            (701, None.__class__),
            (25, "a\udcffb"),
            (1043, "a\udcffb"),
        ],
    )
    def test_refuses_what_encode_binary_refuses(self, oid, value):
        with pytest.raises(ValueEncodingError):
            binary_encoder(oid)(value)

    def test_an_oid_with_no_binary_form_still_raises(self):
        with pytest.raises(ValueEncodingError):
            binary_encoder(999_999)("x")

    def test_numeric_matches_encode_binary_across_scales_and_signs(self):
        rng = random.Random(51)
        values = [Decimal("0"), Decimal("-0"), Decimal("0.00"), Decimal("1E+14"), Decimal("1E-20"),
                  Decimal("-0.0001"), Decimal("10000"), Decimal("9999.9999"), Decimal("123E+3")]  # fmt: skip
        for _ in range(20_000):
            digits = rng.randint(0, 10 ** rng.randint(0, 30))
            values.append(Decimal(rng.choice((1, -1)) * digits).scaleb(-rng.randint(-6, 24)))
        encode = binary_encoder(1700)
        for value in values:
            assert encode(value) == encode_binary(1700, value), value

    def test_timestamps_and_dates_match_encode_binary(self):
        rng = random.Random(51)
        encode_ts, encode_date = binary_encoder(1114), binary_encoder(1082)
        for _ in range(20_000):
            moment = datetime.datetime(1, 1, 1) + datetime.timedelta(
                microseconds=rng.randint(0, 315_537_897_599_999_999)
            )
            assert encode_ts(moment) == encode_binary(1114, moment), moment
            assert encode_date(moment.date()) == encode_binary(1082, moment.date()), moment

    def test_an_aware_timestamp_still_goes_to_utc(self):
        moment = datetime.datetime(2026, 10, 24, 14, 34, 56, tzinfo=datetime.timezone(datetime.timedelta(hours=2)))
        assert binary_encoder(1114)(moment) == encode_binary(1114, moment)
        assert binary_encoder(1184)(moment) == encode_binary(1184, moment)

    def test_a_bool_is_not_taken_for_an_integer(self):
        assert binary_encoder(23)(True) == encode_binary(23, True)

    def test_subclasses_take_the_general_path_and_agree(self):
        class MyInt(int):
            pass

        class MyStr(str):
            pass

        assert binary_encoder(23)(MyInt(7)) == encode_binary(23, MyInt(7))
        assert binary_encoder(25)(MyStr("é")) == encode_binary(25, MyStr("é"))

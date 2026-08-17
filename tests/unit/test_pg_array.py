"""Tests for the PG_ARRAY encoding (feature 044, T011a).

`%INLIST` needs its match set as an IRIS `$LIST`. The first implementation
reproduced IRIS's `$LIST` byte format in Python, derived from the driver's
output. That format is undocumented, so it was replaced: the elements now
travel as one ordinary string and `PGWire.PG_ARRAY` builds the list inside IRIS
with `$LISTBUILD`.

What has to hold is that this encoder and the ObjectScript decoder agree
exactly. A length prefix wrong by one character slides the whole parse, and the
symptom would be a query returning the wrong rows rather than an error — so the
decoder is strict, and `decode_pg_array` mirrors it here.

The agreement itself is proved against real IRIS in the E2E suite; what is
pinned here is the format both sides implement.
"""

from __future__ import annotations

import pytest

from iris_pgwire.sql_translator.pg_array import decode_pg_array, encode_pg_array


class TestEncoding:
    @pytest.mark.parametrize(
        ("values", "expected"),
        [
            ([], "0|"),
            ([""], "1|0:"),
            (["public"], "1|6:public"),
            (["public", "pg_catalog"], "2|6:public10:pg_catalog"),
            ([None], "1|-1:"),
            (["a", None, "b"], "3|1:a-1:1:b"),
            ([2200], "1|4:2200"),
            ([True, False], "2|1:11:0"),
        ],
    )
    def test_known_encodings(self, values, expected):
        assert encode_pg_array(values) == expected

    @pytest.mark.parametrize(
        "values",
        [
            ["a,b"],
            ["has:colon"],
            ["has|bar"],
            ["10:fake"],  # looks like a length prefix
            ["}"],
            ["'quoted'"],
            ['say "hi"'],
            ["multi\nline"],
            ["4|2:xx"],  # looks like a whole encoded array
        ],
    )
    def test_no_value_needs_escaping(self, values):
        """Length-prefixed, not delimited — that is the point of the format."""
        assert decode_pg_array(encode_pg_array(values)) == values

    def test_lengths_are_counted_the_way_iris_counts_them(self):
        """IRIS counts UTF-16 code units; Python code points would desync.

        Measured on IRIS 2026.2: with code-point lengths, an array containing an
        astral character slid the parse and the query returned no rows at all —
        silently, which is the failure this project exists to remove.
        """
        assert encode_pg_array(["café"]) == "1|4:café"
        assert encode_pg_array(["x😀"]) == "1|3:x😀"  # 1 + surrogate pair
        assert encode_pg_array(["😀😀"]) == "1|4:😀😀"

    def test_everything_is_stringified(self):
        """One representation; IRIS compares a string element to a numeric column.

        Measured: `oid %INLIST $LB('2200')` matches `oid = 2200`, so encoding
        every element as text costs nothing and removes a class of type
        inference mistakes.
        """
        assert encode_pg_array([2200, "2200"]) == "2|4:22004:2200"


class TestRoundTrip:
    @pytest.mark.parametrize(
        "values",
        [
            [],
            [""],
            ["public"],
            ["public", "pg_catalog"],
            [None],
            ["a", None, ""],
            ["café", "x😀"],
            ["a" * 5000],
            ["", "", ""],
        ],
    )
    def test_round_trip(self, values):
        assert decode_pg_array(encode_pg_array(values)) == [
            None if v is None else str(v) for v in values
        ]

    def test_many_elements(self):
        values = [f"value-{i}" for i in range(500)]
        assert decode_pg_array(encode_pg_array(values)) == values


class TestStrictness:
    """The decoder must refuse a desynchronised parse, not return part of one."""

    @pytest.mark.parametrize(
        ("encoded", "reason"),
        [
            ("6:public", "missing element count"),
            ("1|6", "truncated element"),
            ("1|60:public", "element overruns input"),
            ("2|6:public", "declared 2 elements, parsed 1"),
            # Rejected for overrunning before the count is even checked — either
            # way it is refused rather than parsed into something plausible.
            ("1|6:public6:other", "element overruns input"),
            ("1|6:public5:other", "declared 1 elements, parsed 2"),
        ],
    )
    def test_malformed_input_raises(self, encoded, reason):
        with pytest.raises(ValueError, match=reason.split(",")[0]):
            decode_pg_array(encoded)

    def test_a_one_character_error_is_caught_rather_than_sliding(self):
        good = encode_pg_array(["public", "pg_catalog"])
        corrupted = good.replace("6:public", "5:public", 1)
        with pytest.raises(ValueError):
            decode_pg_array(corrupted)

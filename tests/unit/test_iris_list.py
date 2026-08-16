"""Parity tests for the IRIS `$LIST` encoder (feature 044, T011a).

`%INLIST` takes its match set as a single bound parameter in `$LIST` format, and
neither Python path can produce one: the DBAPI rejects both a Python list and
its own `IRISList` object with "Unsupported argument type", and the embedded
path accepts a Python list but silently matches nothing. Raw bytes are the one
representation both accept, so pgwire encodes the `$LIST` itself.

The reference implementation is `IRISList.getBuffer()` from the driver pgwire
already depends on — the same bytes IRIS itself writes. These tests compare
against it directly rather than against a table of expected values copied from
one run, so a driver change that moved the format would fail here instead of
silently producing lists IRIS reads as something else.

Where the driver is unavailable (it is an optional import on some CI images)
the parity tests skip and the format tests still run against literal bytes
captured from IRIS 2026.2.
"""

from __future__ import annotations

import random

import pytest

from iris_pgwire.sql_translator.iris_list import encode_element, encode_iris_list

driver = pytest.importorskip("iris", reason="intersystems-irispython not installed")
IRISList = getattr(driver, "IRISList", None)


def driver_encoding(values) -> bytes:
    lst = IRISList()
    for value in values:
        lst.add(value)
    return lst.getBuffer()


requires_driver_list = pytest.mark.skipif(
    IRISList is None,
    reason="iris.IRISList unavailable (embedded runtime resolves it to a class wrapper)",
)


class TestFormat:
    """Bytes captured from IRIS 2026.2, so the format is pinned even without the driver."""

    @pytest.mark.parametrize(
        ("values", "expected"),
        [
            ([], b""),
            ([""], b"\x02\x01"),
            (["public"], b"\x08\x01public"),
            (["public", "pg_catalog"], b"\x08\x01public\x0c\x01pg_catalog"),
            # latin-1 fits in the 8-bit string type; anything else goes UTF-16LE.
            (["café"], b"\x06\x01caf\xe9"),
            (["x😀"], b"\x08\x02x\x00=\xd8\x00\xde"),
            ([None], b"\x01"),
            ([42], b"\x03\x04\x2a"),
            # Minimal *signed* bytes, so a positive value with its top bit set
            # carries a trailing \x00.
            ([128], b"\x04\x04\x80\x00"),
            # Negative values drop sign-extension bytes; IRIS restores them.
            ([-7], b"\x03\x05\xf9"),
            ([-256], b"\x03\x05\x00"),
            ([-1], b"\x02\x05"),
            ([1.5], b"\n\x08\x00\x00\x00\x00\x00\x00\xf8?"),
        ],
    )
    def test_known_encodings(self, values, expected):
        assert encode_iris_list(values) == expected

    def test_empty_list_is_zero_bytes(self):
        """Callers must bind None instead: IRIS answers b"" with SQLCODE -400."""
        assert encode_iris_list([]) == b""

    @pytest.mark.parametrize(
        ("length", "header"),
        [
            # One-byte header counts itself; the wider forms do not.
            (253, b"\xff"),
            (254, b"\x00\xff\x00"),
            (65534, b"\x00\xff\xff"),
            (65535, b"\x00\x00\x00\x00\x00\x01\x00"),
        ],
    )
    def test_header_width_boundaries(self, length, header):
        encoded = encode_element("a" * length)
        assert encoded.startswith(header + b"\x01"), (
            f"a {length}-byte element got header {encoded[: len(header) + 1]!r}"
        )
        assert len(encoded) == len(header) + 1 + length


@requires_driver_list
class TestDriverParity:
    """Byte-for-byte agreement with the driver's own encoder."""

    @pytest.mark.parametrize(
        "values",
        [
            [],
            [""],
            ["public"],
            ["public", "pg_catalog"],
            ["café"],
            ["x😀"],
            ["a" * 252],
            ["a" * 253],
            ["a" * 254],
            ["a" * 255],
            ["a" * 300],
            ["a" * 65534],
            ["a" * 65535],
            ["a" * 70000],
            [0],
            [1],
            [42],
            [127],
            [128],
            [255],
            [256],
            [65535],
            [65536],
            [2**40],
            [2**62],
            [2**63 - 1],
            # Beyond signed 64-bit the driver stores decimal text.
            [2**63],
            [10**30],
            [-1],
            [-7],
            [-127],
            [-128],
            [-255],
            [-256],
            [-65536],
            [-(2**40)],
            [-(2**63)],
            [-(2**63) - 1],
            [1.5],
            [-0.25],
            [0.0],
            [1e300],
            [True],
            [False],
            [None],
            ["a", 1, None],
        ],
    )
    def test_matches_the_driver(self, values):
        assert encode_iris_list(values) == driver_encoding(values)

    def test_random_integers(self):
        rng = random.Random(7)
        for _ in range(200):
            values = [rng.randint(-(2**63), 2**63 - 1) for _ in range(5)]
            assert encode_iris_list(values) == driver_encoding(values), values

    def test_random_strings(self):
        rng = random.Random(11)
        for _ in range(100):
            text = "".join(chr(rng.randint(1, 3000)) for _ in range(rng.randint(0, 400)))
            assert encode_iris_list([text]) == driver_encoding([text])

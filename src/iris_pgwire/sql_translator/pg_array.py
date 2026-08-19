"""Encode an array parameter for `PGWire.PG_ARRAY`.

`%INLIST` wants its match set as an IRIS `$LIST`, and no Python path pgwire uses
can produce one. Rather than reproduce IRIS's undocumented `$LIST` byte layout
here, the elements travel as one ordinary string parameter and `PGWire.PG_ARRAY`
assembles the list inside IRIS with `$LISTBUILD` — documented API on both ends.

    ["public", "pg_catalog"]  ->  "2|6:public10:pg_catalog"
    ["a,b"]                   ->  "1|3:a,b"
    [None]                    ->  "1|-1:"
    []                        ->  "0|"

Length-prefixed, not delimited: no value needs escaping and no value can be
misread, which is what rules out `$LISTFROMSTRING`. The leading count lets the
decoder reject a desynchronised parse instead of silently returning wrong rows.

Lengths are counted in **UTF-16 code units**, because that is what IRIS's
`$EXTRACT` counts. Using Python's code-point length instead is wrong for
anything outside the BMP and fails silently: measured on IRIS 2026.2, an emoji
in the array slid the parse and the query returned no rows at all rather than
erroring.
"""

from __future__ import annotations

from typing import Any

NULL_ELEMENT = "-1:"


def _length_in_iris_characters(text: str) -> int:
    """Character count as IRIS sees it — UTF-16 code units, not code points."""
    return len(text.encode("utf-16-le")) // 2


def encode_element(value: Any) -> str:
    if value is None:
        return NULL_ELEMENT
    if isinstance(value, bool):
        # IRIS has no boolean type; comparisons are against 1/0.
        text = "1" if value else "0"
    else:
        text = str(value)
    return f"{_length_in_iris_characters(text)}:{text}"


def encode_pg_array(values: list | tuple) -> str:
    """Encode a sequence for PG_ARRAY.

    Every element is stringified. That is deliberate rather than lossy: IRIS
    compares a string element against a numeric column by value, so
    `oid %INLIST $LB('2200')` matches `oid = 2200` (measured), and keeping one
    representation removes a whole class of type-inference mistakes.

    An empty sequence encodes to `"0|"`, which builds an empty list and matches
    nothing — the same answer PostgreSQL gives for `x = ANY('{}')`.
    """
    elements = list(values)
    return f"{len(elements)}|" + "".join(encode_element(v) for v in elements)


def decode_pg_array(encoded: str) -> list[str | None]:
    """Inverse of `encode_pg_array`, for tests and diagnostics.

    Mirrors what PG_ARRAY does inside IRIS, including its strictness: anything
    that does not parse exactly raises rather than returning a partial list.
    """
    bar = encoded.find("|")
    if bar < 0:
        raise ValueError("missing element count")
    expected = int(encoded[:bar])

    values: list[str | None] = []
    pos = bar + 1
    while pos < len(encoded):
        colon = encoded.find(":", pos)
        if colon < 0:
            raise ValueError("truncated element")
        count = int(encoded[pos:colon])
        if count == -1:
            values.append(None)
            pos = colon + 1
            continue
        # Counts are in UTF-16 code units, so step through the encoded form the
        # same way IRIS does rather than slicing by code point.
        start = colon + 1
        end = start
        remaining = count
        while remaining > 0 and end < len(encoded):
            remaining -= _length_in_iris_characters(encoded[end])
            end += 1
        if remaining != 0:
            raise ValueError("element overruns input")
        values.append(encoded[start:end])
        pos = end

    if len(values) != expected:
        raise ValueError(f"declared {expected} elements, parsed {len(values)}")
    return values

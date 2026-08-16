"""Serialise Python values into IRIS `$LIST` wire format.

IRIS's `%INLIST` predicate takes the whole match set as one bound parameter, in
`$LIST` format. That is what makes it a viable target for PostgreSQL's
`col = ANY($1)`: one placeholder in, one placeholder out, so the parameter count
the client was told at Describe time still holds at Bind time.

Neither Python path pgwire uses can produce a `$LIST` for us:

* embedded — `iris.IRISList` resolves to an ObjectScript package wrapper and
  raises when called;
* DBAPI — `iris.IRISList` exists but the driver rejects it as a bind value
  ("Unsupported argument type"), as it does a plain Python list.

Both accept raw `bytes`, and IRIS reads those as a `$LIST`. So we encode here.
The format below was read off the driver's own `IRISList.getBuffer()` output
rather than inferred, and `tests/unit/test_iris_list.py` pins our output against
it for every case we encode.

Format — each element is `<header><type><data>`:

* header: total element length *including* the header and type bytes, as one
  byte while that fits in 255; otherwise `\\x00` + 2-byte little-endian length
  of `<type><data>`; and if that would overflow, `\\x00\\x00\\x00` + 4-byte
  little-endian length.
* type: 1 = latin-1 string, 2 = UTF-16LE string, 4 = unsigned little-endian
  integer, 5 = negative integer, 8 = IEEE-754 double.
* a NULL element is the single byte `\\x01` — a header with no type and no data.
"""

from __future__ import annotations

import struct
from typing import Any

_TYPE_STRING_8 = 1
_TYPE_STRING_16 = 2
_TYPE_INT = 4
_TYPE_NEGATIVE_INT = 5
_TYPE_DOUBLE = 8

# A single-byte header counts itself as well as the payload; the wider headers
# do not. Verified against IRISList.getBuffer() at each boundary — see
# tests/unit/test_iris_list.py.
_MAX_SINGLE_BYTE_PAYLOAD = 0xFF - 1
_MAX_TWO_BYTE_PAYLOAD = 0xFFFF


def _header(payload_length: int) -> bytes:
    """Encode the length prefix for `<type><data>` of `payload_length` bytes."""
    if payload_length <= _MAX_SINGLE_BYTE_PAYLOAD:
        return bytes([payload_length + 1])
    if payload_length <= _MAX_TWO_BYTE_PAYLOAD:
        return b"\x00" + struct.pack("<H", payload_length)
    return b"\x00\x00\x00" + struct.pack("<I", payload_length)


def _encode_int(value: int) -> bytes:
    if value == 0:
        return _header(1) + bytes([_TYPE_INT])

    # Outside signed 64-bit range the driver gives up on the numeric types and
    # stores the decimal text instead.
    if not (-(2**63) <= value < 2**63):
        return _encode_string(str(value))

    # Both signs use minimal *signed* little-endian bytes, so a positive value
    # whose top bit is set carries a trailing \x00 (128 is b"\x80\x00").
    width = max(1, (value.bit_length() + 8) // 8)
    data = value.to_bytes(width, "little", signed=True)

    if value > 0:
        type_byte = _TYPE_INT
    else:
        # Type 5 already says "negative", so sign-extension bytes are dropped
        # and IRIS restores them on read: -256 is b"\x00", -1 is empty.
        type_byte = _TYPE_NEGATIVE_INT
        while data and data[-1] == 0xFF:
            data = data[:-1]

    return _header(len(data) + 1) + bytes([type_byte]) + data


def _encode_string(value: str) -> bytes:
    try:
        data = value.encode("latin-1")
        type_byte = _TYPE_STRING_8
    except UnicodeEncodeError:
        data = value.encode("utf-16-le")
        type_byte = _TYPE_STRING_16
    return _header(len(data) + 1) + bytes([type_byte]) + data


def encode_element(value: Any) -> bytes:
    """Encode one value as a `$LIST` element."""
    if value is None:
        return b"\x01"
    if isinstance(value, bool):
        # IRIS has no boolean type; the driver stores True/False as 1/0.
        return _encode_int(1 if value else 0)
    if isinstance(value, int):
        return _encode_int(value)
    if isinstance(value, float):
        return _header(9) + bytes([_TYPE_DOUBLE]) + struct.pack("<d", value)
    if isinstance(value, bytes):
        return _header(len(value) + 1) + bytes([_TYPE_STRING_8]) + value
    return _encode_string(str(value))


def encode_iris_list(values: list | tuple) -> bytes:
    """Serialise a sequence as an IRIS `$LIST`.

    An empty sequence encodes to zero bytes, which IRIS reads as an empty list
    and `%INLIST` matches against nothing — the same answer PostgreSQL gives for
    `x = ANY('{}')`, and a real answer rather than a parse error.
    """
    return b"".join(encode_element(v) for v in values)

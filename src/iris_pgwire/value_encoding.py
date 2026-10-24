"""Encode result values the way PostgreSQL does, in binary and in text.

A binary-format client (the ADBC PostgreSQL driver, psycopg in binary mode, asyncpg) decodes each
field by the type OID it was told, and cannot recover from a field shaped wrong. The expected
bytes for every case in `tests/unit/binary_value_fixtures.py` were captured from a real
PostgreSQL 16, so a client that decodes PostgreSQL's output decodes this.

Failure policy. A value that cannot be encoded raises `ValueEncodingError`. The previous encoder
sent `str(value)` in its place and logged a warning, so a binary client received text bytes where it
expected, say, a 4-byte integer, and decoded garbage or failed somewhere less diagnosable. An
OID with no binary form defined here is reported by `binary_encoding_is_defined`, and the caller
decides what to do about it; this module never guesses.

The Python values accepted are the forms the executors in this repository actually produce, which
differ by backend: DBAPI returns `datetime` objects and `Decimal`s, the embedded backend returns
strings and logical integers (a DATE as PostgreSQL days after the result processor has run, a TIME
as seconds since midnight).
"""

from __future__ import annotations

import datetime
import json
import math
import struct
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

PG_EPOCH_DATE = datetime.date(2000, 1, 1)
PG_EPOCH_TS = datetime.datetime(2000, 1, 1)
_MICROSECOND = datetime.timedelta(microseconds=1)

# IRIS POSIXTIME: microseconds since 1970-01-01, offset by 2**60 so it sorts with the other integers.
_POSIXTIME_OFFSET = 1152921504606846976
_UNIX_EPOCH = datetime.datetime(1970, 1, 1)

# Types whose binary form is the text itself.
_TEXT_LIKE = frozenset({18, 19, 25, 705, 1042, 1043})

# array type oid -> element type oid
ARRAY_ELEMENT_OIDS: dict[int, int] = {
    199: 114, 1000: 16, 1001: 17, 1002: 18, 1003: 19, 1005: 21, 1007: 23, 1009: 25, 1014: 1042,
    1015: 1043, 1016: 20, 1021: 700, 1022: 701, 1028: 26, 1115: 1114, 1182: 1082, 1183: 1083,
    1185: 1184, 1231: 1700, 2951: 2950, 3807: 3802, 16389: 16388,
}  # fmt: skip

VECTOR_OID = 16388

_NUMERIC_NAN = 0xC000
_NUMERIC_NEG = 0x4000


class ValueEncodingError(ValueError):
    """A value cannot be represented in the requested type's wire format."""

    def __init__(self, type_oid: int, value: Any, reason: str):
        super().__init__(f"cannot encode {value!r} as type oid {type_oid}: {reason}")
        self.type_oid = type_oid
        self.value = value
        self.reason = reason


def binary_encoding_is_defined(type_oid: int) -> bool:
    return (
        type_oid in _TEXT_LIKE
        or type_oid in ARRAY_ELEMENT_OIDS
        or type_oid in _SCALAR_ENCODERS
        or type_oid in (114, 3802, VECTOR_OID)
    )


def encode_binary(type_oid: int, value: Any) -> bytes:
    """The binary wire form of `value` as type `type_oid`. Never returns text in its place."""
    try:
        if type_oid in ARRAY_ELEMENT_OIDS:
            return _encode_array(type_oid, value)
        encoder = _SCALAR_ENCODERS.get(type_oid)
        if encoder is not None:
            return encoder(type_oid, value)
        if type_oid in _TEXT_LIKE:
            return _text_bytes(type_oid, value)
        raise ValueEncodingError(type_oid, value, "no binary format is defined for this type")
    except ValueEncodingError:
        raise
    except (ValueError, TypeError, OverflowError, struct.error, InvalidOperation) as exc:
        raise ValueEncodingError(type_oid, value, str(exc) or type(exc).__name__) from exc


# ---------------------------------------------------------------------------------------------
# scalars
# ---------------------------------------------------------------------------------------------


def _text_bytes(type_oid: int, value: Any) -> bytes:
    if isinstance(value, bytes | bytearray | memoryview):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, bool | int | float | Decimal):
        return str(value).encode("utf-8")
    raise ValueEncodingError(type_oid, value, f"expected text, got {type(value).__name__}")


def _to_int(type_oid: int, value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value != value or value in (math.inf, -math.inf) or value != int(value):
            raise ValueEncodingError(type_oid, value, "not a whole number")
        return int(value)
    if isinstance(value, Decimal):
        if value != value.to_integral_value():
            raise ValueEncodingError(type_oid, value, "not a whole number")
        return int(value)
    if isinstance(value, str):
        return int(value.strip())
    raise ValueEncodingError(type_oid, value, f"expected an integer, got {type(value).__name__}")


def _int_encoder(fmt: str, low: int, high: int):
    def encode(type_oid: int, value: Any) -> bytes:
        number = _to_int(type_oid, value)
        if not low <= number <= high:
            raise ValueEncodingError(type_oid, value, f"out of range {low}..{high}")
        return struct.pack(fmt, number)

    return encode


def _encode_bool(type_oid: int, value: Any) -> bytes:
    if isinstance(value, bool):
        return b"\x01" if value else b"\x00"
    if isinstance(value, int) and value in (0, 1):
        return bytes([value])
    if isinstance(value, str):
        word = value.strip().lower()
        if word in ("t", "true", "1", "y", "yes", "on"):
            return b"\x01"
        if word in ("f", "false", "0", "n", "no", "off"):
            return b"\x00"
    raise ValueEncodingError(type_oid, value, "not a boolean")


def _encode_float(fmt: str):
    def encode(type_oid: int, value: Any) -> bytes:
        if isinstance(value, bool) or not isinstance(value, int | float | Decimal | str):
            raise ValueEncodingError(type_oid, value, "not a number")
        return struct.pack(fmt, float(value))

    return encode


def _encode_bytea(type_oid: int, value: Any) -> bytes:
    if isinstance(value, bytes | bytearray | memoryview):
        return bytes(value)
    if isinstance(value, str):
        if value.startswith("\\x"):
            return bytes.fromhex(value[2:])
        try:
            return value.encode("latin-1")
        except UnicodeEncodeError:
            return value.encode("utf-8")
    raise ValueEncodingError(type_oid, value, f"expected bytes, got {type(value).__name__}")


def _encode_uuid(type_oid: int, value: Any) -> bytes:
    if isinstance(value, uuid.UUID):
        return value.bytes
    if isinstance(value, bytes | bytearray) and len(value) == 16:
        return bytes(value)
    if isinstance(value, str):
        return uuid.UUID(value.strip().strip("{}")).bytes
    raise ValueEncodingError(type_oid, value, "not a uuid")


def _json_text(type_oid: int, value: Any) -> str:
    if isinstance(value, dict | list | int | float | bool) or value is None:
        return json.dumps(value)
    if isinstance(value, bytes | bytearray):
        value = bytes(value).decode("utf-8")
    if isinstance(value, str):
        json.loads(value)  # PostgreSQL refuses invalid JSON; so do we
        return value
    raise ValueEncodingError(type_oid, value, "not JSON")


def _encode_json(type_oid: int, value: Any) -> bytes:
    return _json_text(type_oid, value).encode("utf-8")


def _encode_jsonb(type_oid: int, value: Any) -> bytes:
    return b"\x01" + _json_text(type_oid, value).encode("utf-8")  # format version 1


def _days_since_pg_epoch(type_oid: int, value: Any) -> int:
    if isinstance(value, datetime.datetime):
        return (value.date() - PG_EPOCH_DATE).days
    if isinstance(value, datetime.date):
        return (value - PG_EPOCH_DATE).days
    if isinstance(value, int) and not isinstance(value, bool):
        return value  # PostgreSQL days, which is what the result processor leaves in the row
    if isinstance(value, str):
        return (datetime.date.fromisoformat(value.strip()[:10]) - PG_EPOCH_DATE).days
    raise ValueEncodingError(type_oid, value, f"not a date: {type(value).__name__}")


def _encode_date(type_oid: int, value: Any) -> bytes:
    return struct.pack("!i", _days_since_pg_epoch(type_oid, value))


def _microseconds_since_midnight(type_oid: int, value: Any) -> int:
    if isinstance(value, datetime.datetime):
        value = value.time()
    if isinstance(value, datetime.time):
        return (
            (value.hour * 60 + value.minute) * 60 + value.second
        ) * 1_000_000 + value.microsecond
    if isinstance(value, int | float | Decimal) and not isinstance(value, bool):
        # The embedded backend returns an IRIS TIME as seconds since midnight.
        if not 0 <= value <= 86400:
            raise ValueEncodingError(type_oid, value, "seconds since midnight out of range")
        return int(Decimal(str(value)) * 1_000_000)
    if isinstance(value, str):
        text = value.strip()
        head, _, fraction = text.partition(".")
        parts = head.split(":")
        if len(parts) not in (2, 3) or not all(p.isdigit() for p in parts):
            raise ValueEncodingError(type_oid, value, "not a time of day")
        hours, minutes = int(parts[0]), int(parts[1])
        seconds = int(parts[2]) if len(parts) == 3 else 0
        if hours > 24 or minutes > 59 or seconds > 59 or (hours == 24 and (minutes or seconds)):
            raise ValueEncodingError(type_oid, value, "not a time of day")
        micro = int((fraction + "000000")[:6]) if fraction else 0
        return ((hours * 60 + minutes) * 60 + seconds) * 1_000_000 + micro
    raise ValueEncodingError(type_oid, value, f"not a time: {type(value).__name__}")


def _encode_time(type_oid: int, value: Any) -> bytes:
    return struct.pack("!q", _microseconds_since_midnight(type_oid, value))


def _to_naive_utc(type_oid: int, value: Any) -> datetime.datetime:
    if isinstance(value, datetime.datetime):
        pass
    elif isinstance(value, datetime.date):
        value = datetime.datetime(value.year, value.month, value.day)
    elif isinstance(value, int) and not isinstance(value, bool):
        if value < _POSIXTIME_OFFSET:
            raise ValueEncodingError(type_oid, value, "an integer is not a timestamp")
        value = _UNIX_EPOCH + (value - _POSIXTIME_OFFSET) * _MICROSECOND
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("+00") or text.endswith("-00"):
            text += ":00"
        value = datetime.datetime.fromisoformat(text)
    else:
        raise ValueEncodingError(type_oid, value, f"not a timestamp: {type(value).__name__}")
    if value.tzinfo is not None:
        value = value.astimezone(datetime.UTC).replace(tzinfo=None)
    return value


def _encode_timestamp(type_oid: int, value: Any) -> bytes:
    return struct.pack("!q", (_to_naive_utc(type_oid, value) - PG_EPOCH_TS) // _MICROSECOND)


def _decimal_of(type_oid: int, value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueEncodingError(type_oid, value, "not a number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if value != value:
            return Decimal("NaN")
        # A float has no declared scale. Use its shortest representation without trailing zeros,
        # as PostgreSQL's float8 -> numeric cast does: 1.0 becomes 1, 100.0 becomes 100.
        shortest = Decimal(repr(value))
        return shortest.normalize() if shortest.is_finite() else shortest
    if isinstance(value, str):
        return Decimal(value.strip())
    raise ValueEncodingError(type_oid, value, f"not a number: {type(value).__name__}")


def _encode_numeric(type_oid: int, value: Any) -> bytes:
    number = _decimal_of(type_oid, value)
    if number.is_nan():
        return struct.pack("!hhHh", 0, 0, _NUMERIC_NAN, 0)
    if number.is_infinite():
        raise ValueEncodingError(type_oid, value, "numeric has no infinity")

    text = format(number, "f")
    negative = text.startswith("-")
    int_part, _, frac_part = text.lstrip("-").partition(".")
    dscale = len(frac_part)
    int_part = int_part.lstrip("0")

    int_padded = "0" * (-len(int_part) % 4) + int_part
    groups = [int(int_padded[i : i + 4]) for i in range(0, len(int_padded), 4)]
    weight = len(groups) - 1 if groups else -1
    frac_padded = frac_part + "0" * (-len(frac_part) % 4)
    groups += [int(frac_padded[i : i + 4]) for i in range(0, len(frac_padded), 4)]

    # Leading zero groups carry no digits, but they move the weight.
    while groups and groups[0] == 0:
        groups.pop(0)
        weight -= 1
    while groups and groups[-1] == 0:
        groups.pop()
    if not groups:
        return struct.pack("!hhHh", 0, 0, 0, dscale)

    header = struct.pack("!hhHh", len(groups), weight, _NUMERIC_NEG if negative else 0, dscale)
    return header + b"".join(struct.pack("!H", group) for group in groups)


def _vector_floats(value: Any) -> list[float]:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
        items: list[Any] = [part for part in text.split(",") if part.strip() != ""]
    else:
        items = list(value)
    return [float(item) for item in items]


def _encode_vector(type_oid: int, value: Any) -> bytes:
    floats = _vector_floats(value)
    if not 0 < len(floats) <= 16000:
        raise ValueEncodingError(type_oid, value, "a vector has 1 to 16000 dimensions")
    return struct.pack("!HH", len(floats), 0) + struct.pack(f"!{len(floats)}f", *floats)


_SCALAR_ENCODERS = {
    16: _encode_bool,
    17: _encode_bytea,
    20: _int_encoder("!q", -(2**63), 2**63 - 1),
    21: _int_encoder("!h", -(2**15), 2**15 - 1),
    23: _int_encoder("!i", -(2**31), 2**31 - 1),
    26: _int_encoder("!I", 0, 2**32 - 1),
    114: lambda oid, v: _encode_json(oid, v),
    700: _encode_float("!f"),
    701: _encode_float("!d"),
    1082: _encode_date,
    1083: _encode_time,
    1114: _encode_timestamp,
    1184: _encode_timestamp,
    1700: _encode_numeric,
    2950: _encode_uuid,
    3802: lambda oid, v: _encode_jsonb(oid, v),
    VECTOR_OID: _encode_vector,
}


# ---------------------------------------------------------------------------------------------
# arrays
# ---------------------------------------------------------------------------------------------


def _parse_array_literal(type_oid: int, text: str) -> list:
    """Parse a PostgreSQL array literal such as {1,"a b",NULL} into nested lists of str | None."""
    source = text.strip()
    position = 0

    def fail(reason: str):
        raise ValueEncodingError(type_oid, text, f"not a PostgreSQL array literal: {reason}")

    def parse_array() -> list:
        nonlocal position
        if position >= len(source) or source[position] != "{":
            fail("expected {")
        position += 1
        items: list = []
        while True:
            while position < len(source) and source[position] == " ":
                position += 1
            if position >= len(source):
                fail("unterminated")
            char = source[position]
            if char == "}":
                position += 1
                return items
            if char == ",":
                position += 1
                continue
            if char == "{":
                items.append(parse_array())
            elif char == '"':
                position += 1
                chars = []
                while position < len(source) and source[position] != '"':
                    if source[position] == "\\":
                        position += 1
                    chars.append(source[position])
                    position += 1
                if position >= len(source):
                    fail("unterminated quote")
                position += 1
                items.append("".join(chars))
            else:
                start = position
                while position < len(source) and source[position] not in ",}":
                    position += 1
                word = source[start:position].strip()
                items.append(None if word.upper() == "NULL" else word)

    result = parse_array()
    if source[position:].strip():
        fail("trailing characters")
    return result


def _array_shape(type_oid: int, value: Any) -> list[int]:
    if not isinstance(value, list | tuple):
        return []
    if not value:
        return [0]
    shapes = [_array_shape(type_oid, item) for item in value]
    if any(shape != shapes[0] for shape in shapes):
        raise ValueEncodingError(type_oid, value, "a multidimensional array must be rectangular")
    return [len(value), *shapes[0]]


def _flatten(value: Any) -> list:
    if not isinstance(value, list | tuple):
        return [value]
    out: list = []
    for item in value:
        out.extend(_flatten(item))
    return out


def _encode_array(array_oid: int, value: Any) -> bytes:
    element_oid = ARRAY_ELEMENT_OIDS[array_oid]
    if isinstance(value, str):
        value = _parse_array_literal(array_oid, value)
    if not isinstance(value, list | tuple):
        raise ValueEncodingError(array_oid, value, "expected a list or an array literal")

    shape = _array_shape(array_oid, value)
    elements = _flatten(value) if shape != [0] else []
    if shape == [0]:
        return struct.pack("!iii", 0, 0, element_oid)

    has_null = any(item is None for item in elements)
    out = struct.pack("!iii", len(shape), 1 if has_null else 0, element_oid)
    out += b"".join(struct.pack("!ii", size, 1) for size in shape)
    for item in elements:
        if item is None:
            out += struct.pack("!i", -1)
        else:
            encoded = encode_binary(element_oid, item)
            out += struct.pack("!i", len(encoded)) + encoded
    return out


# ---------------------------------------------------------------------------------------------
# text (COPY text and CSV, and anything else that wants PostgreSQL's text output)
# ---------------------------------------------------------------------------------------------


def encode_text(type_oid: int, value: Any) -> str:
    """PostgreSQL's text output for `value` as `type_oid`. Lenient: unknown shapes use str()."""
    if type_oid == 16:
        try:
            return "t" if _encode_bool(type_oid, value) == b"\x01" else "f"
        except ValueEncodingError:
            return "t" if value else "f"
    if type_oid in (1082,) and not isinstance(value, str):
        try:
            return (
                PG_EPOCH_DATE + datetime.timedelta(days=_days_since_pg_epoch(1082, value))
            ).isoformat()
        except ValueEncodingError:
            return str(value)
    if type_oid == 1083 and not isinstance(value, str):
        try:
            micro = _microseconds_since_midnight(1083, value)
        except ValueEncodingError:
            return str(value)
        seconds, micro = divmod(micro, 1_000_000)
        text = f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
        return f"{text}.{micro:06d}".rstrip("0") if micro else text
    if type_oid in (1114, 1184) and isinstance(value, datetime.datetime):
        local = _to_naive_utc(type_oid, value)
        text = local.isoformat(sep=" ")
        return text + "+00" if type_oid == 1184 else text
    if type_oid == 17 and isinstance(value, bytes | bytearray | memoryview):
        return "\\x" + bytes(value).hex()
    if type_oid == 2950 and isinstance(value, uuid.UUID):
        return str(value)
    if type_oid == 1700 and isinstance(value, Decimal):
        return (
            format(value, "f") if value.is_finite() else str(value).replace("Infinity", "Infinity")
        )
    if type_oid in (700, 701) and isinstance(value, float):
        if value != value:
            return "NaN"
        if value in (math.inf, -math.inf):
            return "Infinity" if value > 0 else "-Infinity"
        return repr(value)
    if type_oid in (114, 3802) and isinstance(value, dict | list):
        return json.dumps(value)
    if type_oid in ARRAY_ELEMENT_OIDS and isinstance(value, list | tuple):
        element_oid = ARRAY_ELEMENT_OIDS[type_oid]
        return _array_text(element_oid, value)
    return str(value)


def _array_text(element_oid: int, value: Any) -> str:
    if isinstance(value, list | tuple):
        return "{" + ",".join(_array_text(element_oid, item) for item in value) + "}"
    if value is None:
        return "NULL"
    text = encode_text(element_oid, value)
    needs_quotes = text == "" or text.upper() == "NULL" or any(ch in text for ch in ',{}"\\ \t\n\r')
    if needs_quotes:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text

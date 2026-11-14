"""Encoding a whole result row, for DataRow messages and for binary COPY.

Both carry the same tuple body: a 16-bit field count, then for each field a 32-bit length and the
bytes (-1 and no bytes for NULL). `BinaryRowEncoder` builds that body; `data_row_encoder` builds the
whole DataRow message, in whatever mix of text and binary columns the client asked for.

The encoders for each column are chosen once per result, not looked up per value, and the bytes are
always `value_encoding`'s, which were captured from a real PostgreSQL.

psycopg's C extension (`pip install iris-pgwire[fast]`) builds the same body several times faster,
and is used when it is installed. But it encodes by type OID without checking the value: it wraps
an int4 of 2**31 to -2**31, takes the string 'f' for true, re-quotes a JSON string, lays an `int`
NUMERIC out with different digits, and sends NUMERIC infinity, which this server refuses. So it only
sees a row whose every value is exactly the Python type it expects for its column, with int2 and
int4 values in range and NUMERICs finite: what the DBAPI backend returns. Any other row, and any row
psycopg raises on, is encoded here instead, so a client gets the same bytes and the same refusals
either way. Set PGWIRE_ROW_ENCODER=python to never use psycopg.
"""

from __future__ import annotations

import datetime
import os
import struct
import uuid
from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any

import structlog

from .value_encoding import binary_encoder, binary_encoding_is_defined

logger = structlog.get_logger(__name__)

try:  # optional: the [fast] extra
    from psycopg import pq as _pq
    from psycopg._cmodule import _psycopg  # the C implementation; None when psycopg is pure Python
    from psycopg.adapt import Transformer as _Transformer

    _format_row_binary = _psycopg.format_row_binary if _psycopg is not None else None
except Exception:  # noqa: BLE001 - absent or broken, either way we encode it ourselves
    _format_row_binary = None

_NoneType = type(None)
_NULL = struct.pack("!i", -1)
_LENGTH = struct.Struct("!i").pack
_COUNT = struct.Struct("!H").pack  # unsigned, as DataRow always packed it
_MESSAGE_HEADER = struct.Struct("!cI").pack


def _within(low: int, high: int) -> Callable[[Any], bool]:
    return lambda value: low <= value <= high


# For each type psycopg may encode: the exact Python type it must be given, and the check a value
# of that type must pass besides. A result with any other column type is encoded here throughout.
_PSYCOPG_TYPES: dict[int, tuple[type, Callable[[Any], bool] | None]] = {
    16: (bool, None),
    17: (bytes, None),
    20: (int, None),  # out of range raises in psycopg, and the row comes here
    21: (int, _within(-(2**15), 2**15 - 1)),
    23: (int, _within(-(2**31), 2**31 - 1)),
    25: (str, None),
    701: (float, None),
    1043: (str, None),
    1082: (datetime.date, None),
    1114: (datetime.datetime, None),  # an aware value raises in psycopg, and the row comes here
    1184: (datetime.datetime, None),  # a naive one does
    1700: (Decimal, Decimal.is_finite),
    2950: (uuid.UUID, None),
}


_SELF_CHECK_ROW = (
    True, b"\x00\xff", -(2**63), -(2**15), -(2**31), "héllo", -1.5, "v",
    datetime.date(1999, 12, 31), datetime.datetime(2026, 10, 24, 12, 34, 56, 789012),
    datetime.datetime(2026, 10, 24, 12, 34, 56, tzinfo=datetime.UTC), Decimal("-12345.6789"),
    uuid.UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"),
)  # fmt: skip
_agrees: bool | None = None


def _psycopg_agrees() -> bool:
    """Whether psycopg encodes a row of every type it may be given exactly as we do, checked once.

    `format_row_binary` is internal to psycopg. Should a release change what it does, the result
    must be a slower server, said in the log, not different bytes.
    """
    global _agrees
    if _agrees is None:
        oids = list(_PSYCOPG_TYPES)
        try:
            transformer = _Transformer()
            transformer.set_dumper_types(oids, _pq.Format.BINARY)
            buffer = bytearray()
            _format_row_binary(_SELF_CHECK_ROW, transformer, buffer)
            ours = BinaryRowEncoder(oids, accelerate=False).encode(_SELF_CHECK_ROW)
            _agrees = bytes(buffer) == ours
        except Exception as exc:  # noqa: BLE001 - any failure means: do not use it
            logger.warning("psycopg row encoding unusable; encoding rows here", error=str(exc))
            _agrees = False
        else:
            if not _agrees:
                logger.warning("psycopg encodes rows differently; encoding rows here")
    return _agrees


def psycopg_available() -> bool:
    if _format_row_binary is None or os.environ.get("PGWIRE_ROW_ENCODER") == "python":
        return False
    return _psycopg_agrees()


class BinaryRowEncoder:
    """The binary tuple body of each row of a result whose columns have these type OIDs."""

    def __init__(self, oids: Sequence[int], accelerate: bool = True):
        """`accelerate`: use psycopg where it can be used (`accelerated` says whether it is)."""
        self._oids = list(oids)
        self._encoders = [binary_encoder(oid) for oid in self._oids]
        self._count = _COUNT(len(self._oids))
        self.accelerated = (
            accelerate
            and all(oid in _PSYCOPG_TYPES for oid in self._oids)
            and psycopg_available()  # last: its self-check builds an encoder with accelerate=False
        )
        if self.accelerated:
            self._transformer = _Transformer()
            self._transformer.set_dumper_types(self._oids, _pq.Format.BINARY)
            self._expected = [_PSYCOPG_TYPES[oid][0] for oid in self._oids]
            self._checks = [
                (index, check)
                for index, oid in enumerate(self._oids)
                if (check := _PSYCOPG_TYPES[oid][1]) is not None
            ]
            self._verdicts: dict[tuple[type, ...], bool] = {}

    def encode(self, row: Sequence[Any]) -> bytes:
        if self.accelerated and len(row) == len(self._oids) and self._psycopg_may_take(row):
            buffer = bytearray()
            try:
                _format_row_binary(row if isinstance(row, tuple | list) else tuple(row),
                                   self._transformer, buffer)  # fmt: skip
                return bytes(buffer)
            except Exception:  # noqa: BLE001 - ours raises the right error, or encodes it
                pass
        return self._encode_here(row)

    def _psycopg_may_take(self, row: Sequence[Any]) -> bool:
        signature = tuple(map(type, row))
        verdict = self._verdicts.get(signature)
        if verdict is None:
            verdict = all(
                kind is _NoneType or kind is expected
                for kind, expected in zip(signature, self._expected, strict=True)
            )
            self._verdicts[signature] = verdict
        if not verdict:
            return False
        for index, check in self._checks:
            value = row[index]
            if value is not None and not check(value):
                return False
        return True

    def _encode_here(self, row: Sequence[Any]) -> bytes:
        parts = [self._count]
        if len(row) < len(self._encoders):  # a short row's missing values are NULL, as in DataRow
            row = [*row, *([None] * (len(self._encoders) - len(row)))]
        for encode, value in zip(self._encoders, row, strict=False):
            if value is None:
                parts.append(_NULL)
            else:
                encoded = encode(value)
                parts.append(_LENGTH(len(encoded)))
                parts.append(encoded)
        return b"".join(parts)


def text_value(value: Any, type_oid: int) -> str:
    """The text form this server sends for a value: str(), and a boolean as t or f."""
    if type_oid == 16:
        if value in (1, "1", True, "t", "true", "TRUE"):
            return "t"
        if value in (0, "0", False, "f", "false", "FALSE"):
            return "f"
        return "t" if value else "f"
    return str(value)


def _bool_text(value: Any) -> bytes:
    return text_value(value, 16).encode("utf-8")


def _plain_text(value: Any) -> bytes:
    return (value if type(value) is str else str(value)).encode("utf-8")


def _column_format(formats: Sequence[int], index: int) -> int:
    if not formats:
        return 0
    if len(formats) == 1:
        return formats[0]
    return formats[index] if index < len(formats) else 0


def data_row_encoder(
    oids: Sequence[int], formats: Sequence[int], accelerate: bool = True
) -> Callable[[Sequence[Any]], bytes]:
    """A function giving the DataRow message for a row, with each column in its format code.

    As the DataRow code this replaced did: format 0 is the text form (`text_value`); format 1 is
    the binary form, or the text if the type has none; any other code sends str(value). The two
    fallbacks are logged once per result, not per row.
    """
    codes = [_column_format(formats, index) for index in range(len(oids))]

    if codes and all(code == 1 for code in codes) and all(map(binary_encoding_is_defined, oids)):
        body = BinaryRowEncoder(oids, accelerate=accelerate).encode

        def all_binary(row: Sequence[Any]) -> bytes:
            encoded = body(row)
            return _MESSAGE_HEADER(b"D", len(encoded) + 4) + encoded

        return all_binary

    fields: list[Callable[[Any], bytes]] = []
    for index, (oid, code) in enumerate(zip(oids, codes, strict=True)):
        if code == 1 and binary_encoding_is_defined(oid):
            fields.append(binary_encoder(oid))
        elif code == 1:
            logger.warning("No binary format defined for this type; sending its text",
                           column_index=index, type_oid=oid)  # fmt: skip
            fields.append(_plain_text)
        elif code == 0:
            fields.append(_bool_text if oid == 16 else _plain_text)
        else:
            logger.warning("Unknown format code, sending text", column_index=index,
                           format_code=code)  # fmt: skip
            fields.append(_plain_text)
    count = _COUNT(len(oids))

    def mixed(row: Sequence[Any]) -> bytes:
        parts = [count]
        for index, encode in enumerate(fields):
            value = row[index] if index < len(row) else None
            if value is None:
                parts.append(_NULL)
            else:
                encoded = encode(value)
                parts.append(_LENGTH(len(encoded)))
                parts.append(encoded)
        encoded_row = b"".join(parts)
        return _MESSAGE_HEADER(b"D", len(encoded_row) + 4) + encoded_row

    return mixed

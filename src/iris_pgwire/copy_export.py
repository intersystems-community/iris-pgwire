"""COPY ... TO STDOUT: choosing a format and encoding rows in it.

Three formats, defaulted the way PostgreSQL defaults them:

    text    tab-separated, NULL as \\N, backslash escapes. What `COPY t TO STDOUT` produces when no
            FORMAT is given. This server used to default to CSV, which no PostgreSQL client expects.
    csv     comma-separated, NULL as the empty string, a value equal to the NULL string quoted so it
            stays distinguishable from NULL.
    binary  PostgreSQL's PGCOPY framing, with every field encoded by `value_encoding` (whose
            expected bytes were captured from a real PostgreSQL).

Message boundaries follow PostgreSQL, because clients are written against it: one row per CopyData
message, and for binary the file header travels with the first row and the trailer is its own
message (or rides with the header when there are no rows). The ADBC PostgreSQL driver reads a binary
COPY stream message by message.
"""

from __future__ import annotations

import struct
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from .sql_translator.copy_parser import CSVOptions
from .value_encoding import encode_binary, encode_text

BINARY_HEADER = b"PGCOPY\n\xff\r\n\x00" + struct.pack("!ii", 0, 0)  # signature, flags, extension
BINARY_TRAILER = struct.pack("!h", -1)

_FORMATS = ("text", "csv", "binary")
_TEXT_ONLY_OPTIONS = ("header", "delimiter", "null", "quote", "escape")

_TEXT_ESCAPES = {"\\": "\\\\", "\b": "\\b", "\f": "\\f", "\n": "\\n", "\r": "\\r", "\t": "\\t",
                 "\v": "\\v"}  # fmt: skip


@dataclass(frozen=True)
class ExportFormat:
    kind: str  # "text" | "csv" | "binary"
    delimiter: str = "\t"
    null: str = "\\N"
    quote: str = '"'
    escape: str = '"'
    header: bool = False


def resolve_export_format(options: CSVOptions) -> ExportFormat:
    """The effective format of a COPY TO, applying PostgreSQL's defaults to what was not given.

    Raises ValueError for what PostgreSQL refuses: an unknown format, or a text-only option with
    binary.
    """
    explicit = options.explicit
    kind = options.format.lower() if "format" in explicit else "text"
    if kind not in _FORMATS:
        raise ValueError(f'COPY format "{options.format}" not recognized (use text, csv or binary)')

    if kind == "binary":
        refused = [name for name in _TEXT_ONLY_OPTIONS if name in explicit]
        if refused:
            raise ValueError(
                f"COPY {refused[0]} available only in CSV or text mode, not in binary format"
            )
        return ExportFormat(kind="binary")

    csv = kind == "csv"
    delimiter = options.delimiter if "delimiter" in explicit else ("," if csv else "\t")
    null = options.null_string if "null" in explicit else ("" if csv else "\\N")
    quote = options.quote if "quote" in explicit else '"'
    escape = options.escape if "escape" in explicit else quote
    return ExportFormat(
        kind=kind,
        delimiter=delimiter,
        null=null,
        quote=quote,
        escape=escape,
        header=bool(options.header),
    )


def copy_out_response(fmt: ExportFormat, column_count: int) -> bytes:
    """CopyOutResponse: overall format, column count, and a format code for every column."""
    code = 1 if fmt.kind == "binary" else 0
    payload = struct.pack("!bH", code, column_count) + struct.pack("!H", code) * column_count
    return b"H" + struct.pack("!I", len(payload) + 4) + payload


def copy_data(payload: bytes) -> bytes:
    return b"d" + struct.pack("!I", len(payload) + 4) + payload


def export_messages(
    fmt: ExportFormat, columns: list[dict[str, Any]], rows: Iterable[Iterable[Any]]
) -> Iterator[bytes]:
    """The CopyData payloads for a result: one per row, in PostgreSQL's message boundaries."""
    oids = [column.get("type_oid", 25) for column in columns]
    if fmt.kind == "binary":
        yield from _binary_messages(oids, rows)
        return

    if fmt.header:
        yield _delimited_line(fmt, [column["name"] for column in columns], oids=None)
    for row in rows:
        yield _delimited_line(fmt, row, oids)


def _binary_messages(oids: list[int], rows: Iterable[Iterable[Any]]) -> Iterator[bytes]:
    pending = BINARY_HEADER
    for row in rows:
        values = list(row)
        parts = [struct.pack("!h", len(oids))]
        for oid, value in zip(oids, values, strict=False):
            if value is None:
                parts.append(struct.pack("!i", -1))
            else:
                encoded = encode_binary(oid, value)
                parts.append(struct.pack("!i", len(encoded)) + encoded)
        yield pending + b"".join(parts)
        pending = b""
    yield pending + BINARY_TRAILER


def _delimited_line(fmt: ExportFormat, values: Iterable[Any], oids: list[int] | None) -> bytes:
    fields = []
    for index, value in enumerate(values):
        if value is None:
            fields.append(fmt.null)
            continue
        text = value if oids is None else encode_text(oids[index], value)
        fields.append(_csv_field(fmt, str(text)) if fmt.kind == "csv" else _text_field(fmt, str(text)))
    return (fmt.delimiter.join(fields) + "\n").encode("utf-8")


def _text_field(fmt: ExportFormat, text: str) -> str:
    out = []
    for char in text:
        if char in _TEXT_ESCAPES:
            out.append(_TEXT_ESCAPES[char])
        elif char == fmt.delimiter:
            out.append("\\" + char)
        else:
            out.append(char)
    return "".join(out)


def _csv_field(fmt: ExportFormat, text: str) -> str:
    # A non-NULL value that equals the NULL string is quoted, or it would read back as NULL. With
    # PostgreSQL's default (an empty NULL string) that is also what makes '' distinct from NULL.
    needs_quotes = (
        text == fmt.null
        or fmt.delimiter in text
        or fmt.quote in text
        or "\n" in text
        or "\r" in text
    )
    if not needs_quotes:
        return text
    escaped = text.replace(fmt.escape, fmt.escape + fmt.escape) if fmt.escape != fmt.quote else text
    escaped = escaped.replace(fmt.quote, fmt.escape + fmt.quote)
    return fmt.quote + escaped + fmt.quote

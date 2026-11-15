"""Character columns PGWire creates compare case-sensitively, as PostgreSQL's do.

IRIS's default collation for a string column is `%SQLUPPER`, so `c = 'RED'` matches `red`, `IN`
and `LIKE` ignore case, `min(c)` returns the upper-cased form, and a unique key refuses `'X'` after
`'x'`. Every PostgreSQL collation compares case-sensitively. So in `CREATE TABLE` and
`ALTER TABLE ... ADD [COLUMN]`, each character column (`VARCHAR`, `CHAR`, `CHARACTER VARYING`,
`NVARCHAR`, ...) is declared `COLLATE %EXACT`. A PostgreSQL `COLLATE "name"` becomes `%EXACT` too
(IRIS has no named collations); an IRIS collation the client wrote (`%SQLUPPER`) is kept.

Sorting then follows code points, as PostgreSQL's `C` collation does, not a linguistic locale.
`TEXT` is left alone: IRIS stores it as a stream, which has no collation. Measured on IRIS
2026.2, 2026-11-15 (investigation doc gotcha row 21).

Pure: no I/O. A statement that is not `CREATE` or `ALTER` returns after one prefix check.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

_IDENT = r'(?:"(?:[^"]|"")*"|[\w$]+)'
_NAME = rf"{_IDENT}(?:\s*\.\s*{_IDENT})*"

_CREATE = re.compile(
    rf"^\s*CREATE\s+(?:(?:GLOBAL\s+|LOCAL\s+)?(?:TEMPORARY|TEMP)\s+|UNLOGGED\s+)?TABLE\s+"
    rf"(?:IF\s+NOT\s+EXISTS\s+)?{_NAME}\s*\(",
    re.IGNORECASE,
)
_ALTER_ADD = re.compile(
    rf"^\s*ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:ONLY\s+)?{_NAME}\s+ADD\s+(?:COLUMN\s+)?"
    rf"(?:IF\s+NOT\s+EXISTS\s+)?",
    re.IGNORECASE,
)
_NOT_A_COLUMN = re.compile(
    r"^(?:CONSTRAINT|PRIMARY|UNIQUE|FOREIGN|CHECK|KEY|INDEX|EXCLUDE|LIKE)\b", re.IGNORECASE
)
_COLUMN_START = re.compile(rf"\s*({_IDENT})\s+")
_STRING_TYPE = re.compile(
    r"(?:NATIONAL\s+CHAR(?:ACTER)?\s+VARYING|CHAR(?:ACTER)?\s+VARYING|NATIONAL\s+CHAR(?:ACTER)?"
    r"|NVARCHAR|NCHAR|VARCHAR2?|CHARACTER|CHAR|BPCHAR)\b(?:\s*\(\s*\d+\s*\))?",
    re.IGNORECASE,
)
_ARRAY = re.compile(r"\s*\[")
_COLLATE = re.compile(rf"\s+COLLATE\s+({_NAME}|%\w+)", re.IGNORECASE)
_EXACT = " COLLATE %EXACT"


def exact_string_collation(sql: str) -> str:
    head = sql[:16].lstrip()[:6].upper()
    if head == "CREATE":
        found = _CREATE.match(sql)
        if not found:
            return sql
        start = found.end()
        end = _closing_paren(sql, start)
        if end is None:
            return sql
        body = ",".join(_column(element) for element in _top_level_elements(sql[start:end]))
        return sql[:start] + body + sql[end:]
    if head[:5] == "ALTER":
        found = _ALTER_ADD.match(sql)
        if not found:
            return sql
        start = found.end()
        return sql[:start] + _column(sql[start:])
    return sql


def _column(element: str) -> str:
    """One column definition with the collation fixed; anything else unchanged."""
    if _NOT_A_COLUMN.match(element.lstrip()):
        return element
    name = _COLUMN_START.match(element)
    if not name:
        return element
    kind = _STRING_TYPE.match(element, name.end())
    if not kind:
        return element
    after = kind.end()
    if _ARRAY.match(element, after):
        return element
    written = _COLLATE.match(element, after)
    if written and written.group(1).startswith("%"):
        return element
    rest = written.end() if written else after
    return element[:after] + _EXACT + element[rest:]


def _scan(text: str, start: int = 0) -> Iterator[tuple[int, str, int]]:
    """(index, char, depth) for each character outside quotes, depth counting parentheses."""
    depth, i, n = 0, start, len(text)
    while i < n:
        ch = text[i]
        if ch in "'\"":
            close = text.find(ch, i + 1)
            while close != -1 and close + 1 < n and text[close + 1] == ch:
                close = text.find(ch, close + 2)
            i = n if close == -1 else close + 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        yield i, ch, depth
        i += 1


def _closing_paren(sql: str, start: int) -> int | None:
    for i, ch, depth in _scan(sql, start):
        if ch == ")" and depth == -1:
            return i
    return None


def _top_level_elements(body: str) -> list[str]:
    """The body split at its top-level commas, so joining with commas gives the body back."""
    elements, last = [], 0
    for i, ch, depth in _scan(body):
        if ch == "," and depth == 0:
            elements.append(body[last:i])
            last = i + 1
    elements.append(body[last:])
    return elements

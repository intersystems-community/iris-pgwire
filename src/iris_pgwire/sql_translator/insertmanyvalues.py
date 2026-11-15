"""Split SQLAlchemy 2's "insertmanyvalues" INSERT into one INSERT per row.

To flush several new ORM objects whose keys the database generates, SQLAlchemy 2.0 sends one
statement and matches the RETURNING rows to the objects by order::

    INSERT INTO t (a, b) SELECT p0::INTEGER, p1::VARCHAR
    FROM (VALUES ($1::INTEGER, $2::VARCHAR, 0), ($3::INTEGER, $4::VARCHAR, 1))
        AS imp_sen(p0, p1, sen_counter)
    ORDER BY sen_counter RETURNING t.id

IRIS has no VALUES list in FROM, so this fails to prepare. Inserting the rows one at a time in
sen_counter order is the same work, and it yields the RETURNING rows in the order SQLAlchemy
relies on. Only exactly this shape is split: the select list must be the VALUES columns in order
(each optionally cast) and the last VALUES column must be the integer counter.
"""

from __future__ import annotations

import itertools
import re

_SHAPE = re.compile(
    r"^\s*(?P<head>INSERT\s+INTO\s+.+?\(\s*[^()]*\))\s*SELECT\s+(?P<select>.+?)\s+FROM\s*\(\s*VALUES\s*"
    r"(?P<rows>.+)\)\s*AS\s+IMP_SEN\s*\((?P<names>[^()]*)\)\s*"
    r"(?:ORDER\s+BY\s+SEN_COUNTER\s*)?(?P<returning>RETURNING\s+.+?)?\s*;?\s*$",
    re.IGNORECASE | re.DOTALL,
)
_DOLLAR = re.compile(r"\$\d+")
_LITERAL = re.compile(r"('(?:[^']|'')*')")


def _split_top_level(text: str, separator: str = ",") -> list[str]:
    """Split on ``separator`` outside parentheses and single-quoted literals."""
    parts, depth, quoted, start = [], 0, False, 0
    i = 0
    while i < len(text):
        ch = text[i]
        if quoted:
            if ch == "'":
                if i + 1 < len(text) and text[i + 1] == "'":
                    i += 1
                else:
                    quoted = False
        elif ch == "'":
            quoted = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == separator and depth == 0:
            parts.append(text[start:i].strip())
            start = i + 1
        i += 1
    parts.append(text[start:].strip())
    return parts


def _placeholder_count(text: str) -> int:
    code = "".join(_LITERAL.split(text)[::2])  # the even pieces lie outside literals
    return code.count("?") + len(_DOLLAR.findall(code))


def _renumber(text: str) -> str:
    """Number a row's `$n` placeholders from $1, as its own statement needs."""
    counter = itertools.count(1)
    return "".join(
        p if p.startswith("'") else _DOLLAR.sub(lambda _m: f"${next(counter)}", p)
        for p in _LITERAL.split(text)
    )


def split_insertmanyvalues(sql: str, params) -> list[tuple[str, tuple | None]] | None:
    """``[(single_row_insert, its_params), ...]`` in sen_counter order, or None if not the shape."""
    upper = sql.upper()
    if "IMP_SEN" not in upper or "VALUES" not in upper:
        return None
    m = _SHAPE.match(sql)
    if m is None:
        return None

    names = [n.strip().upper() for n in m.group("names").split(",")]
    if len(names) < 2 or names[-1] != "SEN_COUNTER":
        return None
    selected = [
        re.sub(r"\s*::\s*\w+\s*$", "", s).strip().upper()
        for s in _split_top_level(m.group("select"))
    ]
    if selected != names[:-1]:
        return None

    rows = []
    for tuple_text in _split_top_level(m.group("rows")):
        if not (tuple_text.startswith("(") and tuple_text.endswith(")")):
            return None
        elements = _split_top_level(tuple_text[1:-1])
        if len(elements) != len(names) or not elements[-1].isdigit():
            return None
        rows.append((int(elements[-1]), elements[:-1]))

    params = tuple(params) if params else None
    counts = [sum(_placeholder_count(e) for e in elements) for _, elements in rows]
    if params is not None and sum(counts) != len(params):
        return None

    returning = f" {m.group('returning').strip()}" if m.group("returning") else ""
    head = m.group("head").strip()
    offset = 0
    pieces = []
    for (counter, elements), count in zip(rows, counts, strict=True):
        row_params = params[offset : offset + count] if params is not None else None
        offset += count
        values = _renumber(", ".join(elements))
        pieces.append((counter, (f"{head} VALUES ({values}){returning}", row_params)))
    return [statement for _, statement in sorted(pieces, key=lambda p: p[0])]

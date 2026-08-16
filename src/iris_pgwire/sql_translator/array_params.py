"""Expand PostgreSQL array parameters: `col = ANY($1)` → `col IN (...)`.

PostgreSQL clients bind a whole array to one placeholder and test membership
with `= ANY($n)`. IRIS SQL has no equivalent, so the placeholder has to be
expanded into an `IN` list using the bound values.

CatalogRouter has carried `has_array_param`/`translate_array_param` for a while
but nothing ever called them — catalog queries were intercepted wholesale
before the construct mattered. Once catalog tables moved to IRIS views
(feature 044) the queries reach IRIS for real, and Prisma's

    SELECT nspname FROM pg_namespace WHERE nspname = ANY($1)

failed with `SELECT expected, ? found`. The expansion belongs here, in the
translation pipeline, where it applies to every query rather than only to
intercepted ones.
"""

from __future__ import annotations

import re
from typing import Any

# `= ANY($1)` in PostgreSQL numbering, or `= ANY(?)` once placeholders have
# already been converted.
_ANY_PARAM = re.compile(r"=\s*ANY\s*\(\s*(?:\$(\d+)|\?)\s*\)", re.IGNORECASE)


def has_array_param(sql: str) -> bool:
    """True if the statement tests membership against a bound array."""
    return bool(_ANY_PARAM.search(sql))


def _literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def expand_array_params(sql: str, params: list | tuple | None) -> tuple[str, list]:
    """Rewrite each `= ANY($n)` into an `IN (...)` list of its bound values.

    Returns the rewritten SQL and the parameters that remain to be bound —
    expanded arrays are inlined, so their placeholders are consumed.

    An empty array becomes `IN (NULL)`, which matches nothing. That is the
    correct reading of "is this value in the empty set" and, importantly, it is
    a real answer rather than a silent empty result caused by a construct the
    database could not parse.
    """
    if not params or not has_array_param(sql):
        return sql, list(params or [])

    remaining = list(params)
    consumed: set[int] = set()
    positional = iter(range(len(remaining)))

    def replace(match: re.Match) -> str:
        if match.group(1) is not None:
            index = int(match.group(1)) - 1
        else:
            index = next(positional, -1)

        if index < 0 or index >= len(remaining):
            return match.group(0)

        value = remaining[index]
        if not isinstance(value, (list, tuple, set)):
            return match.group(0)

        consumed.add(index)
        values = list(value)
        if not values:
            return "IN (NULL)"
        return "IN (" + ", ".join(_literal(v) for v in values) + ")"

    rewritten = _ANY_PARAM.sub(replace, sql)
    surviving = [p for i, p in enumerate(remaining) if i not in consumed]
    return rewritten, surviving

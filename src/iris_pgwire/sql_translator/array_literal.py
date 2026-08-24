"""Rewrite PostgreSQL ARRAY[...] constructor syntax to brace-string literals.

IRIS cannot parse `ARRAY['a', 'b']` at all — it fails with SQLCODE -1 before
the query can be prepared. The rewrite converts the constructor to the
PostgreSQL array text format that clients already send as bound parameters:

    ARRAY['PERFORMANCE', 'SCHEMA']  →  '{PERFORMANCE,SCHEMA}'
    ARRAY['x']                      →  '{x}'
    ARRAY[]                         →  '{}'

The pattern only matches simple lists of single-quoted string literals, which
is the only form surp's splinter.sql uses. Complex expressions inside ARRAY[]
(integer literals, column refs, sub-expressions) are not matched and pass
through unchanged, so mis-rewriting a WHERE clause is not possible with surp's
query shapes.

Applied as the first rewrite pass in the pipeline so IRIS never sees the
constructor syntax.
"""

from __future__ import annotations

import re

# Match ARRAY[ ... ] where the content is zero or more single-quoted string
# literals separated by commas. Does not match ARRAY[expr] where expr is not
# a simple quoted string (integers, column references, etc.).
_ARRAY_LITERAL = re.compile(
    r"ARRAY\s*\[\s*((?:'[^']*'(?:\s*,\s*'[^']*')*)?)\s*\]",
    re.IGNORECASE,
)


def rewrite_array_literals(sql: str) -> str:
    """Rewrite ARRAY['a','b',...] constructor syntax to '{a,b,...}' literals."""
    if "ARRAY" not in sql.upper():
        return sql

    def _replace(match: re.Match) -> str:
        inner = match.group(1).strip()
        if not inner:
            return "'{}'"
        # Split on commas that are outside quotes (all elements are quoted here)
        elements = [e.strip().strip("'") for e in _split_elements(inner)]
        return "'{" + ",".join(elements) + "}'"

    return _ARRAY_LITERAL.sub(_replace, sql)


def _split_elements(text: str) -> list[str]:
    """Split a comma-separated list of single-quoted literals."""
    elements: list[str] = []
    current: list[str] = []
    in_quotes = False

    for char in text:
        if char == "'" and not in_quotes:
            in_quotes = True
            current.append(char)
        elif char == "'" and in_quotes:
            in_quotes = False
            current.append(char)
        elif char == "," and not in_quotes:
            elements.append("".join(current).strip())
            current = []
        else:
            current.append(char)

    if current:
        elements.append("".join(current).strip())
    return elements

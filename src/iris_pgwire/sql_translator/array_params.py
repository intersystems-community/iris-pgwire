"""Translate PostgreSQL array membership (`col = ANY($1)`) for IRIS.

PostgreSQL clients bind a whole array to one placeholder and test membership
with `= ANY($n)`. IRIS has the same idea under a different name — the `%INLIST`
predicate, which takes its whole match set as one bound value in `$LIST` format:

    col = ANY($1)   ->   col %INLIST $1        (bound as $LIST bytes)
    col <> ALL($1)  ->   NOT (col %INLIST $1)

The rewrite has to happen *before* preparation, not at execution. `Describe` on
a prepared statement discovers the row description by running the query with
placeholder values, so the statement must be preparable with nothing bound —
and IRIS cannot parse `ANY(?)` at all:

    SQLCODE -1: SELECT expected, ? found

That also rules out substituting the values at execute time, which is what this
module used to do: the failure happens before the values exist. `%INLIST` is the
only shape that keeps one placeholder in the source and one in the target, so
the parameter count the client was told at `Describe` still holds at `Bind`.

`specs/044-catalog-as-views/research-t011a.md` records the measurements behind
that choice, including why the alternatives were rejected.

Array *literals* (`= ANY('{a,b}')`) are a separate case: they arrive already
written into the SQL, there is no parameter to bind, and IRIS has no `$LIST`
literal syntax. Those become an ordinary `IN (…)` list.
"""

from __future__ import annotations

import re
from typing import Any

from .iris_list import encode_iris_list

# The operand has to be a placeholder. `ANY (SELECT …)` is standard SQL that
# IRIS understands natively and must not be touched.
_PLACEHOLDER = r"(\$\d+|\?)"

_ANY_PARAM = re.compile(rf"=\s*ANY\s*\(\s*{_PLACEHOLDER}\s*\)", re.IGNORECASE)

# `x <> ALL($1)` needs its left operand pulled into a NOT, so only a plain
# (optionally qualified, optionally quoted) column reference is rewritten.
# Anything more complex is left alone rather than mis-parsed.
_COLUMN = r'(?:"[^"]+"|[A-Za-z_][\w$]*)(?:\s*\.\s*(?:"[^"]+"|[A-Za-z_][\w$]*))*'
_ALL_PARAM = re.compile(rf"({_COLUMN})\s*(?:<>|!=)\s*ALL\s*\(\s*{_PLACEHOLDER}\s*\)", re.IGNORECASE)

# `= ANY('{a,b}')` — an array written out in the statement text.
_ANY_LITERAL = re.compile(r"=\s*ANY\s*\(\s*'(\{.*?\})'\s*\)", re.IGNORECASE | re.DOTALL)

# Placeholders already rewritten into a `%INLIST`, used to find which bound
# parameters have to be encoded as $LISTs.
_INLIST_PLACEHOLDER = re.compile(rf"%INLIST\s+{_PLACEHOLDER}", re.IGNORECASE)


def has_array_param(sql: str) -> bool:
    """True if the statement tests membership against an array."""
    return bool(_ANY_PARAM.search(sql) or _ALL_PARAM.search(sql) or _ANY_LITERAL.search(sql))


# ---------------------------------------------------------------------------
# Rewriting
# ---------------------------------------------------------------------------


def rewrite_any_to_inlist(sql: str) -> str:
    """Rewrite placeholder-operand `ANY`/`ALL` membership into `%INLIST`.

    Placeholder tokens are carried through unchanged — `$2` stays `$2` — so the
    later `$n` → `?` conversion still sees a consistent statement and parameter
    positions do not move.

    Applied unconditionally, without reference to the bound values, so that
    `Describe` and `Execute` prepare the same statement.
    """
    if "ANY" not in sql.upper() and "ALL" not in sql.upper():
        return sql

    sql = _ALL_PARAM.sub(lambda m: f"NOT ({m.group(1)} %INLIST {m.group(2)})", sql)
    return _ANY_PARAM.sub(lambda m: f"%INLIST {m.group(1)}", sql)


def expand_array_literals(sql: str) -> str:
    """Rewrite `= ANY('{a,b}')` into `IN ('a', 'b')`.

    An empty array becomes `IN (NULL)`, which matches nothing — the right
    reading of "is this value in the empty set", and a real answer rather than
    the silent empty result a construct IRIS cannot parse would produce.
    """

    def replace(match: re.Match) -> str:
        # The array text is inside a SQL string literal, so quotes reach us
        # doubled. Undouble before parsing and re-escape on the way out, or
        # `'{"O''Brien"}'` would come back as `'O''''Brien'`.
        values = parse_pg_array_literal(match.group(1).replace("''", "'"))
        if values is None:
            return match.group(0)
        if not values:
            return "IN (NULL)"
        return "IN (" + ", ".join(_sql_literal(v) for v in values) + ")"

    return _ANY_LITERAL.sub(replace, sql)


def _sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


# ---------------------------------------------------------------------------
# Parameter encoding
# ---------------------------------------------------------------------------


def inlist_param_indexes(sql: str) -> list[int]:
    """Zero-based positions of the bound parameters feeding a `%INLIST`."""
    indexes: list[int] = []
    for match in _INLIST_PLACEHOLDER.finditer(sql):
        token = match.group(1)
        if token == "?":
            # `?` placeholders are numbered by their order in the statement,
            # so count every one that precedes this occurrence.
            indexes.append(sql.count("?", 0, match.start(1)))
        else:
            indexes.append(int(token[1:]) - 1)
    return indexes


def encode_inlist_params(sql: str, params: list | tuple | None) -> list | None:
    """Encode every parameter feeding a `%INLIST` as IRIS `$LIST` bytes.

    Neither Python path can hand IRIS a list: the DBAPI rejects both a Python
    list and its own `IRISList` with "Unsupported argument type", and the
    embedded path accepts a Python list but silently matches nothing. Raw
    `$LIST` bytes are the one representation both accept.

    An empty array binds as `None`. An empty `$LIST` is zero bytes, and binding
    those fails with SQLCODE -400 (`<LIST>`), whereas a NULL operand returns no
    rows on both backends — which is what `= ANY('{}')` means.
    """
    if params is None:
        return None

    values = list(params)
    for index in inlist_param_indexes(sql):
        if not (0 <= index < len(values)):
            continue
        values[index] = _as_iris_list(values[index])
    return values


def _as_iris_list(value: Any) -> Any:
    if value is None or isinstance(value, bytes):
        return value

    if isinstance(value, (list, tuple, set)):
        elements: list | None = list(value)
    elif isinstance(value, str):
        parsed = parse_pg_array_literal(value)
        # A bare scalar bound against a membership test is a one-element set.
        elements = parsed if parsed is not None else [value]
    else:
        elements = [value]

    if not elements:
        return None
    return encode_iris_list(elements)


# ---------------------------------------------------------------------------
# PostgreSQL array text format
# ---------------------------------------------------------------------------


def parse_pg_array_literal(text: str) -> list | None:
    """Parse PostgreSQL's array text format into a list, or None if it isn't one.

    Handles the output form clients send: `{a,b}`, quoting for elements
    containing a delimiter or quote, backslash escapes inside quotes, and the
    unquoted word NULL. Nested/multidimensional arrays have no `%INLIST`
    equivalent, so they are declined rather than silently flattened.
    """
    if not isinstance(text, str):
        return None

    body = text.strip()
    if len(body) < 2 or not body.startswith("{") or not body.endswith("}"):
        return None
    body = body[1:-1]
    if not body.strip():
        return []
    if "{" in body or "}" in body:
        return None

    elements: list[Any] = []
    current: list[str] = []
    quoted = False
    in_quotes = False
    escaped = False

    for char in body:
        if escaped:
            current.append(char)
            escaped = False
        elif in_quotes and char == "\\":
            escaped = True
        elif char == '"':
            in_quotes = not in_quotes
            quoted = True
        elif char == "," and not in_quotes:
            elements.append(_array_element(("".join(current)), quoted))
            current, quoted = [], False
        else:
            current.append(char)

    if in_quotes:
        return None
    elements.append(_array_element("".join(current), quoted))
    return elements


def _array_element(raw: str, quoted: bool) -> Any:
    if quoted:
        return raw
    stripped = raw.strip()
    if stripped.upper() == "NULL":
        return None
    return stripped

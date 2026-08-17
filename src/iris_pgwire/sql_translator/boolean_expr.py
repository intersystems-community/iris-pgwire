"""Rewrite boolean expressions used as projected values.

PostgreSQL lets a predicate be a value: `SELECT (a AND b = 1) AS flag`. IRIS has
no boolean type and accepts `AND`/`OR`/comparisons only in a predicate, so the
same statement fails at parse time with `ERROR: ) expected, AND found`. Prisma's
table-introspection query projects two of these, which is what blocks
`prisma db pull` once catalog tables are served by real views.

Measured on IRIS 2026.2 — every spelling of a boolean value fails, and
`CASE WHEN … THEN 1 ELSE 0 END` is the one that works:

    (a AND b = 1)     SQLCODE -1   Invalid SQL statement
    (a = 1)           SQLCODE -1   Invalid SQL statement
    a = 1             SQLCODE -25  Input encountered after end of query
    NOT (a = 1)       SQLCODE -12  A term expected
    CASE WHEN … END   ✅

Two rewrites are needed, not one. A bare column cannot stand alone as a
predicate operand either — `CASE WHEN relhassubclass THEN …` fails with
SQLCODE -14, "A comparison operator is required here" — and Prisma's first
operand is exactly that. So each operand of an `AND`/`OR` that carries no
comparison of its own gets ` <> 0`, which is the right reading for a column IRIS
stores as 0/1.

The result is wrapped in `CAST(… AS BIT)` rather than left as 1/0 so the driver
hands back a real boolean and the client is told the column is one. It asked for
a boolean; an integer would make it either fail to parse or quietly show a
number.

Scope is deliberately narrow: only a select-list item that is *wholly*
parenthesised and *demonstrably* boolean is touched. `(a + b)`, `(a)`,
`(SELECT …)` and `(CASE …)` are all valid IRIS SQL already, so rewriting them
would break working queries. A predicate in a `WHERE` clause is legal where it
stands and is left alone.
"""

from __future__ import annotations

import re

from ..catalog.views.definitions import BOOLEAN_CATALOG_COLUMNS

_CAST_TEMPLATE = "CAST(CASE WHEN {} THEN 1 ELSE 0 END AS BIT)"

# A plain column reference: optionally qualified, optionally quoted, nothing else.
# Anything richer than this keeps its own comparison or is not our business.
_BARE_COLUMN = re.compile(
    r'^(?:NOT\s+)?(?:"[^"]+"|[A-Za-z_][\w$]*)(?:\s*\.\s*(?:"[^"]+"|[A-Za-z_][\w$]*))*$'
)

# Operators that make an expression a predicate rather than a value.
_COMPARISON = re.compile(
    r"(?:<=|>=|<>|!=|=|<|>)|\bLIKE\b|\bIS\s+(?:NOT\s+)?NULL\b|\bBETWEEN\b|\bIN\s*\(|%INLIST\b",
    re.IGNORECASE,
)
_CONNECTIVE = re.compile(r"\b(?:AND|OR)\b", re.IGNORECASE)

# Constructs that are already valid as a value and must not be wrapped.
_NOT_A_PREDICATE = re.compile(r"^\s*(?:SELECT|CASE)\b", re.IGNORECASE)


def _scan_top_level(text: str):
    """Yield (index, char, depth) with string literals and quoted names skipped.

    Depth counts parentheses. Characters inside '...' or "..." are reported at a
    negative depth so callers can ignore them wholesale — a literal containing
    the word AND must never look like an operator.
    """
    depth = 0
    quote: str | None = None
    for index, char in enumerate(text):
        if quote:
            if char == quote:
                # Doubled quote is an escape, not a terminator.
                quote = None
            yield index, char, -1
            continue
        if char in ("'", '"'):
            quote = char
            yield index, char, -1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        yield index, char, depth


def _top_level_positions(text: str, predicate) -> list[int]:
    return [i for i, char, depth in _scan_top_level(text) if depth == 0 and predicate(char)]


def _split_top_level_commas(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    for index in _top_level_positions(text, lambda c: c == ","):
        parts.append(text[start:index])
        start = index + 1
    parts.append(text[start:])
    return parts


def _masked(text: str) -> str:
    """`text` with literal contents and nested parens blanked out.

    Used for operator detection so only the top level of an expression counts.
    """
    out = []
    for _, char, depth in _scan_top_level(text):
        out.append(char if depth == 0 else " ")
    return "".join(out)


def _is_boolean_expression(inner: str) -> bool:
    if not inner.strip() or _NOT_A_PREDICATE.match(inner):
        return False
    surface = _masked(inner)
    return bool(_CONNECTIVE.search(surface) or _COMPARISON.search(surface))


def _fix_bare_operands(predicate: str) -> str:
    """Give every `AND`/`OR` operand a comparison, since IRIS requires one."""
    surface = _masked(predicate)
    boundaries: list[tuple[int, int]] = [
        (m.start(), m.end()) for m in _CONNECTIVE.finditer(surface)
    ]
    if not boundaries:
        return _fix_one_operand(predicate)

    pieces: list[str] = []
    cursor = 0
    for start, end in boundaries:
        pieces.append(_fix_one_operand(predicate[cursor:start]))
        pieces.append(predicate[start:end])
        cursor = end
    pieces.append(_fix_one_operand(predicate[cursor:]))
    return "".join(pieces)


def _fix_one_operand(operand: str) -> str:
    stripped = operand.strip()
    if not stripped:
        return operand
    if _COMPARISON.search(_masked(stripped)):
        return operand
    if not _BARE_COLUMN.match(stripped):
        return operand
    # Preserve the caller's whitespace so the statement reads as it did.
    leading = operand[: len(operand) - len(operand.lstrip())]
    trailing = operand[len(operand.rstrip()) :]
    return f"{leading}{stripped} <> 0{trailing}"


def _select_list_bounds(sql: str) -> tuple[int, int] | None:
    """Character range of the top-level select list, or None if there isn't one."""
    match = re.match(r"\s*SELECT\s+(?:(?:ALL|DISTINCT)\s+)?", sql, re.IGNORECASE)
    if not match:
        return None
    start = match.end()

    # TOP n / DISTINCT BY(...) sit between SELECT and the list.
    top = re.match(r"TOP\s+(?:\d+|\?|\$\d+)\s+", sql[start:], re.IGNORECASE)
    if top:
        start += top.end()

    surface = _masked(sql)
    for keyword in re.finditer(r"\bFROM\b", surface[start:], re.IGNORECASE):
        return start, start + keyword.start()
    # No FROM at all (`SELECT 1`), so the list runs to the end of the statement.
    return start, len(sql)


def _split_alias(item: str) -> tuple[str, str]:
    """Separate a select-list item into (expression, alias-suffix)."""
    surface = _masked(item)
    as_match = re.search(r"\s+AS\s+", surface, re.IGNORECASE)
    if as_match:
        return item[: as_match.start()], item[as_match.start() :]

    # A bare alias only follows a closing paren in the shapes this module cares
    # about; anything else is left as one expression.
    bare = re.search(r"\)\s+(?:\"[^\"]+\"|[A-Za-z_][\w$]*)\s*$", surface)
    if bare:
        cut = item.index(")", bare.start()) + 1
        return item[:cut], item[cut:]
    return item, ""


def _rewrite_item(item: str) -> str:
    expression, alias = _split_alias(item)
    stripped = expression.strip()
    if not (stripped.startswith("(") and stripped.endswith(")")):
        return item

    # Must be one set of parentheses wrapping the whole expression, not
    # `(a) + (b)`.
    depths = [depth for _, _, depth in _scan_top_level(stripped)]
    if any(depth == 0 for depth in depths[1:-1]):
        return item

    inner = stripped[1:-1]
    if not _is_boolean_expression(inner):
        return item

    leading = expression[: len(expression) - len(expression.lstrip())]
    return f"{leading}{_CAST_TEMPLATE.format(_fix_bare_operands(inner))}{alias}"


def has_boolean_projection(sql: str) -> bool:
    """True if any select-list item is a boolean expression IRIS would reject."""
    if "(" not in sql:
        return False
    bounds = _select_list_bounds(sql)
    if bounds is None:
        return False
    start, end = bounds
    for item in _split_top_level_commas(sql[start:end]):
        if _rewrite_item(item) != item:
            return True
    return False


def rewrite_boolean_projections(sql: str) -> str:
    """Rewrite every boolean select-list item into `CAST(CASE … AS BIT)`.

    Recurses into subqueries, where the construct is just as illegal. Statements
    other than SELECT are returned unchanged — a predicate in `WHERE`, `SET` or
    `VALUES` is legal where it stands.
    """
    if "(" not in sql:
        return sql

    bounds = _select_list_bounds(sql)
    if bounds is None:
        return _rewrite_subqueries(sql)

    start, end = bounds
    items = _split_top_level_commas(sql[start:end])
    rewritten = ",".join(_rewrite_item(item) for item in items)
    return sql[:start] + rewritten + _rewrite_subqueries(sql[end:])


def _rewrite_subqueries(remainder: str) -> str:
    """Apply the same rewrite to any parenthesised SELECT further along."""
    if not re.search(r"\(\s*SELECT\b", remainder, re.IGNORECASE):
        return remainder

    out = remainder
    for match in reversed(list(re.finditer(r"\(\s*SELECT\b", out, re.IGNORECASE))):
        open_at = match.start()
        depth = 0
        close_at = None
        for index, char, _ in _scan_top_level(out[open_at:]):
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    close_at = open_at + index
                    break
        if close_at is None:
            continue
        body = out[open_at + 1 : close_at]
        out = out[: open_at + 1] + rewrite_boolean_projections(body) + out[close_at:]
    return out


# ---------------------------------------------------------------------------
# Boolean literals compared against a catalog boolean column
# ---------------------------------------------------------------------------

# PostgreSQL's accepted boolean literals, quoted or bare, mapped to the 0/1 the
# catalog views actually hold.
_BOOLEAN_LITERALS: dict[str, str] = {
    "'t'": "1",
    "'f'": "0",
    "'true'": "1",
    "'false'": "0",
    "'y'": "1",
    "'n'": "0",
    "'yes'": "1",
    "'no'": "0",
    "'on'": "1",
    "'off'": "0",
    "true": "1",
    "false": "0",
}

_BOOLEAN_COMPARISON = re.compile(
    r"(?<![\w.])((?:\w+\s*\.\s*)?(" + "|".join(sorted(BOOLEAN_CATALOG_COLUMNS)) + r"))"
    r"(\s*(?:<>|!=|=)\s*)"
    r"('(?:[tTfFyYnN]|true|false|yes|no|on|off)'|\btrue\b|\bfalse\b)",
    re.IGNORECASE,
)


def has_boolean_literal_comparison(sql: str) -> bool:
    """True if a catalog boolean column is compared to a PostgreSQL boolean literal."""
    return bool(_BOOLEAN_COMPARISON.search(sql))


def rewrite_boolean_literal_comparisons(sql: str) -> str:
    """Turn `relispartition = 'f'` into `relispartition = 0`.

    The views hold 0/1 for the columns PostgreSQL declares as `bool`, so a client
    comparing one against a boolean literal is asking a question IRIS cannot
    answer as written. Worse than "cannot": comparing a constant-valued view
    column to the string 'f' inside a nested predicate group crashes IRIS with
    SQLCODE -400 rather than erroring cleanly — see BOOLEAN_CATALOG_COLUMNS for
    the measurements. With `= 0` the same query is fine.

    Only the columns we ourselves declare as boolean are touched, so a user
    column that happens to hold the string 'f' is left alone.
    """
    if not has_boolean_literal_comparison(sql):
        return sql

    def replace(match: re.Match) -> str:
        column, operator, literal = match.group(1), match.group(3), match.group(4)
        numeric = _BOOLEAN_LITERALS.get(literal.lower())
        if numeric is None:
            return match.group(0)
        return f"{column}{operator}{numeric}"

    return _BOOLEAN_COMPARISON.sub(replace, sql)

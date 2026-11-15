"""Resolve ``GROUP BY <position>`` to the select-list expression it names.

PostgreSQL reads ``GROUP BY 1`` as "the first output column". IRIS reads it as the constant 1:
``SELECT status, count(*) FROM orders GROUP BY 1`` returns one row covering every order, with no
error (measured on IRIS 2026.2 through the DBAPI driver). Ibis writes ``GROUP BY 1`` for every
aggregation, and so do psql users, dbt models and ORMs. IRIS does honour ``ORDER BY <position>``,
so only GROUP BY is rewritten.

Each positional item becomes the n-th expression of its own SELECT's list, alias stripped. An
item is left as it is (IRIS then groups by a constant) when it cannot be resolved safely:

- the select list has ``*`` or ``t.*`` (column positions unknown here);
- the position is out of range;
- the expression contains a parameter (``?``/``$n``): copying it would add a parameter;
- the expression contains its own GROUP BY (a scalar subquery);
- the clause uses ROLLUP, CUBE or GROUPING SETS (IRIS has none of them).

A position that names an aggregate IS substituted: IRIS then raises SQLCODE -19, as PostgreSQL
raises 42803, where leaving the number gives a silent one-row answer.
"""

from __future__ import annotations

import re

import structlog

logger = structlog.get_logger("iris_pgwire.sql_translator.positional_group_by")

# Cheap gate: GROUP BY with a bare number as its first item or after a comma.
_HINT = re.compile(r"\bGROUP\s+BY\s+(?:[^;]*?,\s*)?\d", re.IGNORECASE | re.DOTALL)

# String literals, quoted identifiers and comments, so structure is read outside them.
_OPAQUE = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|--[^\n]*|/\*.*?\*/", re.DOTALL)

_GROUP_BY = re.compile(r"\bGROUP\s+BY\s+", re.IGNORECASE)
_SELECT = re.compile(r"\bSELECT\b", re.IGNORECASE)
_FROM = re.compile(r"\bFROM\b", re.IGNORECASE)
_CLAUSE_END = re.compile(
    r"\b(HAVING|ORDER\s+BY|LIMIT|OFFSET|FETCH|UNION|INTERSECT|EXCEPT|FOR|WINDOW)\b", re.IGNORECASE
)
_GROUPING_SETS = re.compile(r"\b(ROLLUP|CUBE|GROUPING\s+SETS)\b", re.IGNORECASE)
_LIST_PREFIX = re.compile(r"\s*(?:(?:DISTINCT|ALL)\b\s*)?(?:TOP\s+(?:\d+|\(\s*\d+\s*\))\s+)?", re.I)
_DISTINCT_ON = re.compile(r"\s*DISTINCT\s+ON\b", re.IGNORECASE)
_STAR = re.compile(r"^(?:.*\.)?\*$", re.DOTALL)
_PARAMETER = re.compile(r"\?|\$\d")
_AS_ALIAS = re.compile(r"\s+AS\s+(?:\"x*\"|[A-Za-z_][\w$]*)\s*$", re.IGNORECASE)
_BARE_ALIAS = re.compile(r"(?<=[\w)\"\]])\s+(\"x*\"|[A-Za-z_][\w$]*)\s*$")
_WORD_BEFORE = re.compile(r"([A-Za-z_][\w$]*)\s*$")
# Words that can end an expression, or that cannot precede an alias.
_NOT_ALIAS = frozenset(
    "END NULL TRUE FALSE AND OR NOT IS IN LIKE ILIKE BETWEEN THEN ELSE WHEN CASE DISTINCT ALL "
    "SELECT AS ASC DESC COLLATE ESCAPE AT ZONE INTERVAL DATE TIME TIMESTAMP UNKNOWN".split()
)


def _masks(sql: str) -> tuple[str, str]:
    """Two strings the length of ``sql``. ``masked`` blanks literal and identifier contents (to
    ``x``) and comments (to spaces), for reading structure. ``clean`` blanks only comments, for
    copying an expression without carrying a ``--`` comment into the middle of a line."""
    masked: list[str] = []
    clean: list[str] = []
    last = 0
    for m in _OPAQUE.finditer(sql):
        text = m.group(0)
        masked.append(sql[last : m.start()])
        clean.append(sql[last : m.start()])
        if text[0] in "'\"":
            masked.append(text[0] + "x" * (len(text) - 2) + text[0])
            clean.append(text)
        else:
            blank = re.sub(r"[^\n]", " ", text)
            masked.append(blank)
            clean.append(blank)
        last = m.end()
    masked.append(sql[last:])
    clean.append(sql[last:])
    return "".join(masked), "".join(clean)


def _depth(masked: str, index: int) -> int:
    return masked.count("(", 0, index) - masked.count(")", 0, index)


def _split(masked: str, start: int, end: int) -> list[tuple[int, int]]:
    """Spans of the depth-0, comma-separated items of masked[start:end], whitespace trimmed."""
    spans = []
    depth = 0
    item_start = start
    for index in range(start, end + 1):
        char = masked[index] if index < end else ","
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            s, e = item_start, index
            while s < e and masked[s].isspace():
                s += 1
            while e > s and masked[e - 1].isspace():
                e -= 1
            spans.append((s, e))
            item_start = index + 1
    return spans


def _clause_end(masked: str, start: int) -> int:
    depth = 0
    for index in range(start, len(masked)):
        char = masked[index]
        if char == "(":
            depth += 1
        elif char == ")":
            if depth == 0:
                return index
            depth -= 1
        elif char == ";" and depth == 0:
            return index
        elif depth == 0 and char.isalpha() and _CLAUSE_END.match(masked, index):
            if index == 0 or not (masked[index - 1].isalnum() or masked[index - 1] in "_$"):
                return index
    return len(masked)


def _select_list(masked: str, group_by_at: int) -> list[tuple[int, int]] | None:
    """Spans of the select list owning the GROUP BY at ``group_by_at``, or None."""
    depth = _depth(masked, group_by_at)
    select = None
    for m in _SELECT.finditer(masked, 0, group_by_at):
        if _depth(masked, m.start()) == depth:
            select = m
    if select is None:
        return None
    from_at = None
    for m in _FROM.finditer(masked, select.end(), group_by_at):
        if _depth(masked, m.start()) == depth:
            from_at = m.start()
            break
    if from_at is None or _DISTINCT_ON.match(masked, select.end()):
        return None
    start = _LIST_PREFIX.match(masked, select.end()).end()
    return _split(masked, start, from_at)


def _strip_alias(masked: str, s: int, e: int) -> int:
    """End of the expression in masked[s:e] once a trailing alias is removed."""
    item = masked[s:e]
    m = _AS_ALIAS.search(item)
    if m:
        return s + m.start()
    m = _BARE_ALIAS.search(item)
    if m and m.start() > 0 and m.group(1).upper() not in _NOT_ALIAS:
        before = _WORD_BEFORE.search(item, 0, m.start())
        if before is None or before.group(1).upper() not in _NOT_ALIAS:
            return s + m.start()
    return e


def resolve_group_by_positions(sql: str) -> str:
    """Return ``sql`` with each positional GROUP BY item replaced by its select-list expression."""
    if not sql or not _HINT.search(sql):
        return sql

    masked, clean = _masks(sql)
    edits: list[tuple[int, int, str]] = []
    for group_by in _GROUP_BY.finditer(masked):
        start = group_by.end()
        end = _clause_end(masked, start)
        if _GROUPING_SETS.search(masked, start, end):
            continue
        positions = [(s, e) for s, e in _split(masked, start, end) if masked[s:e].isdigit()]
        if not positions:
            continue
        columns = _select_list(masked, group_by.start())
        if columns is None:
            logger.debug("GROUP BY position left as is: select list not found", sql=sql[:200])
            continue
        if any(_STAR.match(masked[s:e]) for s, e in columns):
            logger.debug("GROUP BY position left as is: select list has *", sql=sql[:200])
            continue
        for s, e in positions:
            n = int(masked[s:e])
            if not 1 <= n <= len(columns):
                continue
            col_s, col_e = columns[n - 1]
            col_e = _strip_alias(masked, col_s, col_e)
            expression_mask = masked[col_s:col_e]
            if _PARAMETER.search(expression_mask) or _GROUP_BY.search(expression_mask):
                logger.debug("GROUP BY position left as is: expression not copyable", position=n)
                continue
            expression = clean[col_s:col_e].strip()
            if expression:
                edits.append((s, e, expression))

    if not edits:
        return sql
    for s, e, expression in sorted(edits, reverse=True):
        sql = sql[:s] + expression + sql[e:]
    logger.debug("Resolved GROUP BY positions", count=len(edits))
    return sql

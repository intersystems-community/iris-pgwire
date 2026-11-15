"""ON CONFLICT statements, classified by whether IRIS's INSERT OR UPDATE expresses them (spec 052 US4).

IRIS's `INSERT OR UPDATE` inserts the row, or, when it collides with an existing row on any
unique key, updates that row with every supplied column. PostgreSQL's
`INSERT ... ON CONFLICT (target) DO UPDATE SET ...` is that statement only when:

- the target is the table's only unique key (primary key included), so "collides on any unique
  key" and "collides on the target" are the same thing;
- the update sets every inserted non-key column from EXCLUDED, so "every supplied column" and
  the SET list are the same thing;
- there is no `DO UPDATE ... WHERE`, which INSERT OR UPDATE cannot express.

The suite's E3 table measured every other form differing (research R7): a subset SET rewrote the
other columns, a second unique key let INSERT OR UPDATE match it and rewrite the primary key.
`classify_on_conflict` labels a statement `exact`, with the rewrite, or names its form so it can
be refused by name (FR-013, FR-014).

INSERT OR UPDATE takes one row of VALUES (multi-row VALUES fail with SQLCODE -25, measured
2026-11-14), so multi-row and INSERT ... SELECT upserts are inexact here too.

Pure: the table's unique keys and columns come from the caller (the executor reads the catalog).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .returning_plan import ReturningPlan

_INSERT_INTO = re.compile(r"^\s*INSERT\s+INTO\s+", re.IGNORECASE)
_EXCLUDED = re.compile(r'^EXCLUDED\s*\.\s*("(?:[^"]|"")+"|\w+)$', re.IGNORECASE)
_VALUES = re.compile(r"\bVALUES\b", re.IGNORECASE)

_FORMS = {
    "do_nothing": (
        "DO NOTHING",
        "IRIS has no insert that skips a conflicting row atomically",
        "check for the row first, or catch the unique violation (23505)",
    ),
    "set_subset": (
        "DO UPDATE that sets only some of the inserted columns",
        "IRIS's INSERT OR UPDATE writes every inserted column on the update path",
        "insert only the columns the update sets, or set every inserted column from EXCLUDED",
    ),
    "set_not_from_excluded": (
        "DO UPDATE whose SET is not `column = EXCLUDED.column`",
        "IRIS's INSERT OR UPDATE writes the inserted values and cannot read the existing row",
        "compute the new values in the client, or run the UPDATE yourself on conflict",
    ),
    "do_update_where": (
        "DO UPDATE ... WHERE",
        "IRIS's INSERT OR UPDATE always updates the conflicting row",
        "run the UPDATE ... WHERE yourself on conflict",
    ),
    "second_unique_key": (
        "on a table with more than one unique key",
        "IRIS's INSERT OR UPDATE matches a row on any unique key, and would update (and rewrite "
        "the key of) a row PostgreSQL would report as a unique violation",
        "upsert into a table whose only unique key is the conflict target",
    ),
    "target_not_the_key": (
        "whose target is not the table's unique key",
        "IRIS's INSERT OR UPDATE matches on the table's unique keys, not on the target",
        "make the conflict target the table's only unique key",
    ),
    "on_constraint": (
        "ON CONSTRAINT",
        "PGWire maps a target given as columns only",
        "name the conflict target's columns",
    ),
    "multi_row": (
        "with several rows of VALUES",
        "IRIS's INSERT OR UPDATE takes one row",
        "send one row per statement (executemany)",
    ),
    "insert_select": (
        "with INSERT ... SELECT",
        "IRIS's INSERT OR UPDATE takes one row of VALUES",
        "send one row per statement",
    ),
}


@dataclass(frozen=True)
class TableKeys:
    unique_keys: tuple[frozenset[str], ...]  # column sets, lower case, primary key included
    columns: tuple[str, ...]  # lower case, in table order


@dataclass(frozen=True)
class ConflictDecision:
    form: str  # "exact", or the name of the inexact form
    sql: str | None = None  # the INSERT OR UPDATE, for "exact"

    @property
    def message(self) -> str | None:
        if self.form == "exact":
            return None
        shape, why, instead = _FORMS[self.form]
        return (
            f"INSERT ... ON CONFLICT {shape} is not supported on IRIS through PGWire: {why}. "
            f"Instead, {instead}. (PGWIRE_TXN_COMPAT=permissive runs PGWire's 2.0 emulation, "
            "which is not atomic.)"
        )


def _name(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1].replace('""', '"').lower()
    return raw.lower()


def _row_count(values_sql: str) -> int:
    """Top-level parenthesised groups after VALUES (string literals skipped)."""
    groups, depth, quote = 0, 0, ""
    for ch in values_sql:
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            if depth == 0:
                groups += 1
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
    return groups


def insert_row_expressions(sql: str) -> list[str] | None:
    """The expressions of an INSERT's one row of VALUES, as written; None for any other shape."""
    values = _VALUES.search(sql)
    if values is None:
        return None
    rest = sql[values.end() :]
    if _row_count(rest) != 1:
        return None
    start = rest.index("(") + 1
    depth, quote, end = 1, "", start
    for end in range(start, len(rest)):
        ch = rest[end]
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                break
    return ReturningPlan._split_comma_separated(rest[start:end])


def classify_on_conflict(plan: ReturningPlan, keys: TableKeys) -> ConflictDecision | None:
    """The decision for an INSERT ... ON CONFLICT, or None for any other statement."""
    if plan.operation != "INSERT" or not plan.on_conflict_clause:
        return None
    if plan.conflict_action == "DO NOTHING":
        return ConflictDecision("do_nothing")
    if plan.conflict_constraint:
        return ConflictDecision("on_constraint")

    values = _VALUES.search(plan.stripped_sql)
    if values is None:
        return ConflictDecision("insert_select")
    if _row_count(plan.stripped_sql[values.end() :]) != 1:
        return ConflictDecision("multi_row")

    if len(keys.unique_keys) > 1:
        return ConflictDecision("second_unique_key")
    target = frozenset(plan.conflict_target_columns)
    if not keys.unique_keys or target != keys.unique_keys[0]:
        return ConflictDecision("target_not_the_key")
    if plan.conflict_where_clause:
        return ConflictDecision("do_update_where")

    inserted = set(plan.insert_columns or keys.columns)
    assigned: set[str] = set()
    for item in ReturningPlan._split_comma_separated(plan.conflict_set_clause or ""):
        column, _, value = item.partition("=")
        source = _EXCLUDED.match(value.strip())
        column = _name(column)
        if source is None or _name(source.group(1)) != column or column not in inserted:
            return ConflictDecision("set_not_from_excluded")
        assigned.add(column)
    if (inserted - target) - assigned:
        return ConflictDecision("set_subset")

    return ConflictDecision("exact", _INSERT_INTO.sub("INSERT OR UPDATE ", plan.stripped_sql, 1))

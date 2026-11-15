"""Row-locking clauses (`FOR UPDATE` and the rest) planned for IRIS (spec 052 US3, research R6).

IRIS accepts `SELECT ... FOR UPDATE` and takes no lock for it. An UPDATE does lock, until the
transaction ends, so PGWire locks the rows itself with a touch-update, `UPDATE t SET pk = pk
WHERE <the same predicate>`, and then runs the SELECT without the clause. Measured: the touch
excludes a second locker and a writer exactly as PostgreSQL's `FOR UPDATE` does, and a
read-then-write counter run that way reached 1000 of 1000.

The touch is exact only when it locks the rows the SELECT returns: one base table in FROM and a
WHERE it can reuse unchanged. `plan_locking` recognises the clause and the shape and either plans
the touch or names why it cannot. Whether the table is a view, or has an UPDATE trigger or a
ROWVERSION column, needs the catalog; the executor checks that.

Pure: no I/O, no IRIS. The input is the statement the executor is about to send (translated:
upper-cased, schema-qualified, `?` markers), but untranslated SQL works the same.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

# Cheap pre-check: every SELECT passes through here, and almost none has a locking clause.
_MAYBE = re.compile(r"\bFOR\s+(?:UPDATE|NO\s+KEY|SHARE|KEY\s+SHARE)\b", re.IGNORECASE)

_TOKEN = re.compile(
    r"""
      (?P<space>\s+)
    | (?P<comment>--[^\n]*|/\*.*?\*/)
    | (?P<string>'(?:[^']|'')*')
    | (?P<ident>"(?:[^"]|"")*")
    | (?P<param>\?)
    | (?P<word>[A-Za-z_%][\w$%]*)
    | (?P<number>\d+(?:\.\d*)?)
    | (?P<open>\()
    | (?P<close>\))
    | (?P<other>.)
    """,
    re.VERBOSE | re.DOTALL,
)

_AGGREGATES = {
    "COUNT",
    "SUM",
    "AVG",
    "MIN",
    "MAX",
    "STRING_AGG",
    "ARRAY_AGG",
    "LIST",
    "%DLIST",
    "BOOL_AND",
    "BOOL_OR",
    "EVERY",
    "STDDEV",
    "VARIANCE",
    "JSON_ARRAYAGG",
    "XMLAGG",
}
_JOIN_WORDS = {"JOIN", "INNER", "LEFT", "RIGHT", "FULL", "CROSS", "NATURAL", "LATERAL", "OUTER"}
_SET_OPERATIONS = {"UNION", "INTERSECT", "EXCEPT"}
# Clause keywords that end the FROM list or the WHERE predicate.
_CLAUSE_WORDS = {"WHERE", "GROUP", "HAVING", "ORDER", "LIMIT", "OFFSET", "FETCH", "FOR", "WINDOW"}

# Why a shape is refused: the shape, then what to do instead.
_REFUSALS = {
    "for_share": ("FOR SHARE", "IRIS has no shared row lock", "use FOR UPDATE"),
    "for_no_key_update": (
        "FOR NO KEY UPDATE",
        "IRIS has no weaker row lock than an update's",
        "use FOR UPDATE",
    ),
    "for_key_share": ("FOR KEY SHARE", "IRIS has no shared row lock", "use FOR UPDATE"),
    "skip_locked": (
        "SKIP LOCKED",
        "IRIS cannot skip rows another transaction holds",
        "claim rows with FOR UPDATE NOWAIT and retry on 55P03",
    ),
    "join": (
        "on a join",
        "PGWire locks rows with an UPDATE of one table",
        "lock each table's rows with its own single-table SELECT ... FOR UPDATE first",
    ),
    "subquery_in_from": (
        "on a subquery or function in FROM",
        "PGWire locks rows with an UPDATE of one base table",
        "lock the base table's rows with a single-table SELECT ... FOR UPDATE first",
    ),
    "group_by": (
        "with GROUP BY",
        "grouped rows cannot be locked",
        "lock the rows with a plain SELECT ... FOR UPDATE, then aggregate",
    ),
    "aggregate": (
        "with an aggregate function",
        "aggregated rows cannot be locked",
        "lock the rows with a plain SELECT ... FOR UPDATE, then aggregate",
    ),
    "distinct": (
        "with DISTINCT",
        "the rows behind a DISTINCT cannot be locked one for one",
        "lock the rows with a plain SELECT ... FOR UPDATE",
    ),
    "window": (
        "with a window function",
        "PostgreSQL does not allow it either",
        "lock the rows with a plain SELECT ... FOR UPDATE",
    ),
    "limit": (
        "with LIMIT, OFFSET, FETCH or TOP",
        "PGWire's lock would cover every row the WHERE matches, not only those returned",
        "narrow the WHERE to the rows you want (for example by key)",
    ),
    "set_operation": (
        "with UNION, INTERSECT or EXCEPT",
        "PostgreSQL does not allow it either",
        "lock each part with its own SELECT ... FOR UPDATE",
    ),
    "with": (
        "in a WITH query",
        "PGWire locks rows with an UPDATE of one base table",
        "lock the base table's rows with a single-table SELECT ... FOR UPDATE first",
    ),
    "several_locking_clauses": (
        "with more than one locking clause",
        "PGWire locks rows of one table only",
        "use one FOR UPDATE",
    ),
    "of_several_tables": (
        "OF several tables",
        "PGWire locks rows of one table only",
        "lock each table's rows with its own single-table SELECT ... FOR UPDATE",
    ),
    "of_unknown_table": (
        "OF a table that is not in FROM",
        "there is nothing to lock",
        "name the FROM table in OF",
    ),
    "from_shape": (
        "on this FROM clause",
        "PGWire locks rows of one plain table reference only",
        "write FROM as one table, optionally with an alias",
    ),
    # The executor's catalog checks.
    "view": (
        "on a view",
        "PGWire locks rows with an UPDATE of one base table",
        "select from the base table",
    ),
    "update_trigger": (
        "on a table with an UPDATE trigger",
        "PGWire's lock is an UPDATE, which would fire the trigger",
        "lock the rows another way, or drop the trigger",
    ),
    "generated_column": (
        "on a table with a ROWVERSION or generated column",
        "PGWire's lock is an UPDATE, which would change that column",
        "lock the rows another way",
    ),
    "no_lockable_column": (
        "on a table with no column PGWire can update in place",
        "PGWire's lock is an UPDATE that sets a column to itself",
        "add a primary key",
    ),
}


def refusal_message(refusal: str, clause: str) -> str:
    shape, why, instead = _REFUSALS[refusal]
    subject = shape if shape.isupper() else f"{clause} {shape}"
    return (
        f"{subject} is not supported on IRIS through PGWire: IRIS takes no row lock for a "
        f"locking clause, and {why}. Instead, {instead}. "
        "(PGWIRE_TXN_COMPAT=permissive runs it unlocked, as before 2.1.)"
    )


@dataclass(frozen=True)
class TableRef:
    text: str  # as written, e.g. `SQLUser."LOCK_C"`
    schema: str | None  # unquoted
    name: str  # unquoted
    alias: str | None


@dataclass(frozen=True)
class LockPlan:
    clause: str  # the locking clause as written, e.g. "FOR UPDATE NOWAIT"
    strength: str  # "update" | "no key update" | "share" | "key share"
    nowait: bool
    select_sql: str  # the statement without the clause
    refusal: str | None = None  # None: emulate
    table: TableRef | None = None
    where: str | None = None
    where_params: tuple[int, int] = (0, 0)  # (first, count) of the `?` markers in the WHERE

    @property
    def message(self) -> str | None:
        return refusal_message(self.refusal, self.clause_head) if self.refusal else None

    @property
    def clause_head(self) -> str:
        return "FOR " + self.strength.upper()

    def refused(self, refusal: str) -> LockPlan:
        return LockPlan(self.clause, self.strength, self.nowait, self.select_sql, refusal)

    def touch_sql(self, column: str) -> str:
        assert self.table is not None and self.refusal is None
        alias = f" {self.table.alias}" if self.table.alias else ""
        where = f" WHERE {self.where}" if self.where else ""
        return f"UPDATE {self.table.text}{alias} SET {column} = {column}{where}"

    def touch_params(self, params):
        if params is None:
            return None
        first, count = self.where_params
        return tuple(params)[first : first + count]


@dataclass(frozen=True)
class _Tok:
    kind: str
    text: str
    start: int
    end: int
    depth: int

    @property
    def up(self) -> str:
        return self.text.upper() if self.kind == "word" else ""


def _tokens(sql: str) -> list[_Tok]:
    out, depth = [], 0
    for m in _TOKEN.finditer(sql):
        kind = m.lastgroup
        if kind in ("space", "comment"):
            continue
        if kind == "close":
            depth = max(depth - 1, 0)
        out.append(_Tok(kind, m.group(), m.start(), m.end(), depth))
        if kind == "open":
            depth += 1
    return out


def _unquote(text: str) -> str:
    return text[1:-1].replace('""', '"') if text.startswith('"') else text


def _is_name(tok: _Tok) -> bool:
    return tok.kind in ("word", "ident")


def _dotted_name_end(toks: list[_Tok], k: int) -> int:
    """The index of the last part of the dotted name `a.b...` whose first part is toks[k]."""
    while k + 2 < len(toks) and toks[k + 1].text == "." and _is_name(toks[k + 2]):
        k += 2
    return k


def _parse_clause(toks: list[_Tok], i: int):
    """The locking clause starting at toks[i] (FOR): (strength, of_names, nowait, skip, end)."""
    words = [t.up for t in toks[i + 1 : i + 4]]
    if words[:1] == ["UPDATE"]:
        strength, j = "update", i + 2
    elif words[:3] == ["NO", "KEY", "UPDATE"]:
        strength, j = "no key update", i + 4
    elif words[:1] == ["SHARE"]:
        strength, j = "share", i + 2
    elif words[:2] == ["KEY", "SHARE"]:
        strength, j = "key share", i + 3
    else:
        return None
    of_names: list[str] = []
    if j < len(toks) and toks[j].up == "OF":
        j += 1
        while j < len(toks) and _is_name(toks[j]):
            # schema.table: the last part names it
            k = _dotted_name_end(toks, j)
            of_names.append(_unquote(toks[k].text))
            j = k + 1
            if j < len(toks) and toks[j].text == ",":
                j += 1
            else:
                break
    nowait = skip = False
    if j < len(toks) and toks[j].up == "NOWAIT":
        nowait, j = True, j + 1
    elif j + 1 < len(toks) and toks[j].up == "SKIP" and toks[j + 1].up == "LOCKED":
        skip, j = True, j + 2
    return strength, of_names, nowait, skip, j


def plan_locking(sql: str) -> LockPlan | None:
    """The plan for a statement with a row-locking clause, or None if it has none."""
    if not _MAYBE.search(sql):
        return None
    toks = _tokens(sql)
    top = [i for i, t in enumerate(toks) if t.depth == 0]

    clauses = []  # (start index, parsed)
    for i in top:
        if toks[i].up == "FOR":
            parsed = _parse_clause(toks, i)
            if parsed is not None:
                clauses.append((i, parsed))
    if not clauses:
        return None

    first_i, (strength, of_names, nowait, skip, end_j) = clauses[0]
    last_end_j = clauses[-1][1][4]
    cut_start = toks[first_i].start
    cut_end = toks[last_end_j - 1].end
    select_sql = (sql[:cut_start].rstrip() + " " + sql[cut_end:].strip()).strip()
    select_sql = select_sql.rstrip(";").rstrip()
    clause_text = sql[cut_start:cut_end]
    plan = LockPlan(clause_text, strength, nowait, select_sql)

    if strength != "update":
        return plan.refused("for_" + strength.replace(" ", "_"))
    if skip:
        return plan.refused("skip_locked")
    if len(clauses) > 1:
        return plan.refused("several_locking_clauses")

    # The statement's own top-level words, with the locking clause left out.
    body_idx = [i for i in top if not (first_i <= i < end_j)]
    body = [toks[i] for i in body_idx]
    words = [t.up for t in body]
    first_word = words[0] if words else ""
    if first_word == "WITH":
        return plan.refused("with")
    if first_word != "SELECT":
        return plan.refused("from_shape")
    if any(w in _SET_OPERATIONS for w in words):
        return plan.refused("set_operation")
    if len(words) > 1 and words[1] == "DISTINCT":
        return plan.refused("distinct")
    if any(w in ("LIMIT", "OFFSET", "FETCH", "TOP") for w in words):
        return plan.refused("limit")

    from_k = next((k for k, t in enumerate(body) if t.up == "FROM"), None)
    # `count(` at depth 0: the word is top level, its `(` opens at depth 0 too.
    for n in body_idx[1:from_k]:
        word = toks[n].up
        if word == "OVER":
            return plan.refused("window")
        if word in _AGGREGATES and n + 1 < len(toks) and toks[n + 1].kind == "open":
            return plan.refused("aggregate")
    if "GROUP" in words or "HAVING" in words:
        return plan.refused("group_by")
    if "WINDOW" in words:
        return plan.refused("window")

    if from_k is None:
        return plan  # nothing to lock: `SELECT 1 FOR UPDATE`

    # FROM list: from after FROM to the next clause keyword.
    from_end = next(
        (k for k in range(from_k + 1, len(body)) if body[k].up in _CLAUSE_WORDS), len(body)
    )
    from_list = body[from_k + 1 : from_end]
    if any(t.kind == "open" for t in from_list):
        return plan.refused("subquery_in_from")
    if any(t.text == "," for t in from_list) or any(t.up in _JOIN_WORDS for t in from_list):
        return plan.refused("join")
    table = _table_ref(sql, from_list)
    if table is None:
        return plan.refused("from_shape")

    if of_names:
        names = {n.lower() for n in of_names}
        if len(names) > 1:
            return plan.refused("of_several_tables")
        known = {table.name.lower()} | ({table.alias.lower()} if table.alias else set())
        if not names <= known:
            return plan.refused("of_unknown_table")

    where = None
    where_params = (0, 0)
    where_k = next((k for k in range(from_end, len(body)) if body[k].up == "WHERE"), None)
    if where_k is not None:
        where_end_k = next(
            (k for k in range(where_k + 1, len(body)) if body[k].up in _CLAUSE_WORDS), None
        )
        start = body[where_k].end
        # The predicate ends at the next clause keyword or at the locking clause, whichever is first.
        stop = body[where_end_k].start if where_end_k is not None else len(sql)
        if cut_start > start:
            stop = min(stop, cut_start)
        where = sql[start:stop].strip().rstrip(";").rstrip()
        before = sum(1 for t in toks if t.kind == "param" and t.start < start)
        inside = sum(1 for t in toks if t.kind == "param" and start <= t.start < stop)
        where_params = (before, inside)

    return replace(plan, table=table, where=where, where_params=where_params)


def _table_ref(sql: str, from_list: list[_Tok]) -> TableRef | None:
    """`[schema.]name [[AS] alias]`, or None for anything else."""
    if not from_list or not _is_name(from_list[0]):
        return None
    k = _dotted_name_end(from_list, 0)
    parts = from_list[0 : k + 1 : 2]
    if len(parts) > 2:
        return None
    rest = from_list[k + 1 :]
    if rest and rest[0].up == "AS":
        rest = rest[1:]
    alias = None
    if rest:
        if len(rest) != 1 or not _is_name(rest[0]):
            return None
        alias = rest[0].text
    text = sql[parts[0].start : parts[-1].end]
    schema = _unquote(parts[0].text) if len(parts) == 2 else None
    return TableRef(text, schema, _unquote(parts[-1].text), alias)

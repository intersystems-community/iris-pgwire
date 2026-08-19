"""What the SQL already says about each output column's PostgreSQL type.

A column's declared type must not depend on whether the query happened to return
rows — but on the `dbapi` backend it did. `DBAPIExecutor` took every type from
`cursor.description`, which arrived as varchar for every column, and then refined
the varchars from the *first row's Python value*.

(The varchars were our own doing, not the driver's: `_map_dbapi_type_to_oid`
stringified a numeric ODBC code and grepped it for `INT`/`CHAR`. Measured, IRIS
reports distinct correct codes and reports them identically at 0 rows — see
T015c. This module is still required regardless: no ODBC code can say that
`relrowsecurity`, stored 0/1 and reported as an integer, is a PostgreSQL `bool`.)

A statement Describe runs the query with dummy parameters, which match nothing, so
there was no first row and no refinement:

    Execute  (7 rows) -> is_partition 16,   has_row_level_security 23
    Describe (0 rows) -> is_partition 1043, has_row_level_security 1043

Prisma's driver reads the statement Describe and then decodes DataRow bytes that
were encoded per Execute, so it received one byte of bool under a varchar
declaration and gave up:

    Getting is_partition from ResultRow { types: [Text, …],
    values: [Text(Some("\\0")), …] } as bool failed

This module answers from the statement text alone, so Describe and Execute agree
by construction. It lives here, rather than in either executor, because the
original defect was precisely that the logic existed in **one of two** executors:
`backend_selector` builds `DBAPIExecutor` for the dbapi backend and `IRISExecutor`
for the embedded one, and T011g fixed only the latter.

`None` means "no opinion" — the caller keeps whatever IRIS reported. Guessing
would be worse than declining: a wrong declared type breaks a client that reads
binary results, which is the whole failure being fixed.
"""

from __future__ import annotations

import re

from .boolean_expr import select_list_items

# Cast target -> PostgreSQL type OID. IRIS spells boolean `BIT`.
CAST_TYPE_OIDS: dict[str, int] = {
    "bool": 16,
    "boolean": 16,
    "bit": 16,
    "int": 23,
    "integer": 23,
    "bigint": 20,
    "smallint": 21,
    "text": 25,
    "varchar": 1043,
    "date": 1082,
    "timestamp": 1114,
    "float": 701,
    "double": 701,
}

# A plain column reference: optionally qualified, optionally quoted, nothing else.
_PLAIN_COLUMN = re.compile(r'(?:(?:"[^"]+"|\w+)\s*\.\s*)?(?:"([^"]+)"|(\w+))')

_PG_CAST = r"\$\d+::(\w+)\s+AS\s+{}"
_CAST_TAIL = r"\bAS\s+(\w+)\s*\)\s+AS\s+{}\b"

# `select_list_items` returns the alias as written, keyword and quotes included —
# `AS table_name`. What is wanted here is the bare name.
_ALIAS_NAME = re.compile(r'^(?:AS\s+)?"?([^"\s]+)"?$', re.IGNORECASE)


def _alias_name(alias: str) -> str:
    match = _ALIAS_NAME.match(alias.strip())
    return match.group(1) if match else ""


def _encloses_a_cast(sql_upper: str, position: int) -> bool:
    """True if the parenthesis closing at/after `position` was opened by CAST.

    Walking back to the matching paren rather than trusting the shape: a
    subquery `(SELECT b AS c) AS flag` matches the same tail pattern and is not
    a cast.
    """
    depth = 0
    for index in range(position, -1, -1):
        char = sql_upper[index]
        if char == ")":
            depth += 1
        elif char == "(":
            if depth == 0:
                return sql_upper[:index].rstrip().endswith("CAST")
            depth -= 1
    return False


def cast_type_oid(sql: str, column_name: str) -> int | None:
    """The OID named by a cast producing `column_name`, if there is one.

    Covers `$1::bool AS flag` and `CAST(<anything> AS BIT) AS flag` — the second
    form is what the boolean-projection rewrite emits, and requiring a cast *of a
    parameter* is what made T011g's first attempt miss it.
    """
    if not sql or not column_name:
        return None
    sql_upper = sql.upper()
    escaped = re.escape(column_name.upper())

    match = re.search(_PG_CAST.format(escaped), sql_upper)
    if match:
        return CAST_TYPE_OIDS.get(match.group(1).lower())

    for match in re.finditer(_CAST_TAIL.format(escaped), sql_upper):
        # Start inside the type word: the closing paren belongs to the cast being
        # identified, so counting it would consume it.
        if _encloses_a_cast(sql_upper, match.end(1) - 1):
            return CAST_TYPE_OIDS.get(match.group(1).lower())

    return None


def catalog_column_type_oid(sql: str, item_index: int) -> int | None:
    """The OID of the catalog column at `item_index`, if the item is one.

    Resolves the output alias back to the expression behind it: clients rename
    these freely — Prisma writes `tbl.relrowsecurity as has_row_level_security` —
    and the type belongs to the column selected, not to the name given to it.

    Only a plain column reference counts. `COUNT(relrowsecurity)` is an int8, not
    that column, and claiming bool for it would be worse than saying nothing.
    """
    # Imported here: the catalog package reaches back into this one, and a
    # module-level import would close the cycle.
    from ..catalog.views.definitions import CATALOG_COLUMN_TYPE_OIDS

    items = select_list_items(sql)
    if not 0 <= item_index < len(items):
        return None

    match = _PLAIN_COLUMN.fullmatch(items[item_index][0].strip())
    if not match:
        return None

    column = (match.group(1) or match.group(2)).lower()
    return CATALOG_COLUMN_TYPE_OIDS.get(column)


def boolean_expression_type_oid(sql: str, item_index: int) -> int | None:
    """16 if the select-list item at `item_index` is a boolean expression.

    `(tbl.relhassubclass and tbl.relkind = 'p') AS is_partition` has no cast to
    read and is not a catalog column, so nothing else would type it. PostgreSQL
    declares it `bool`; before this, a Describe with no rows declared varchar.

    Delegates the "is this a predicate" judgement to the same code that decides
    whether to rewrite such an item for IRIS, so the two cannot disagree about
    what counts.
    """
    from .boolean_expr import _is_boolean_expression, _scan_top_level

    items = select_list_items(sql)
    if not 0 <= item_index < len(items):
        return None

    expression = items[item_index][0].strip()
    if not (expression.startswith("(") and expression.endswith(")")):
        return None

    # One set of parentheses wrapping the whole thing, not `(a) + (b)`.
    depths = [depth for _, _, depth in _scan_top_level(expression)]
    if any(depth == 0 for depth in depths[1:-1]):
        return None

    return 16 if _is_boolean_expression(expression[1:-1]) else None


def resolve_column_type_oids(sql: str) -> list[int | None]:
    """One entry per select-list item: its PostgreSQL type OID, or None.

    Precedence, strongest evidence first:

    1. an explicit cast — the client said so;
    2. a known catalog column — documented type, whatever value IRIS returns;
    3. a boolean expression — PostgreSQL declares these `bool`.

    Anything else is None, leaving the type IRIS reported in place.
    """
    items = select_list_items(sql)
    resolved: list[int | None] = []
    for index, (_expression, alias) in enumerate(items):
        name = _alias_name(alias)
        oid = cast_type_oid(sql, name) if name else None
        if oid is None:
            oid = catalog_column_type_oid(sql, index)
        if oid is None:
            oid = boolean_expression_type_oid(sql, index)
        resolved.append(oid)
    return resolved

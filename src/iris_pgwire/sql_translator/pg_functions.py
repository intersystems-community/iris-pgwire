"""Route PostgreSQL catalog function calls to their PGWire equivalents.

Clients call these unqualified — `obj_description(tbl.oid, 'pg_class')` — and
IRIS resolves an unqualified function against the default schema, so it answers
`User defined SQL function 'SQLUSER.OBJ_DESCRIPTION' does not exist`. Installing
ours into SQLUser would fix the lookup but would put PostgreSQL-named functions
in the user's own schema, so the call is rewritten to the PGWire schema instead.

Only *unqualified* calls are rewritten: `pg_catalog.obj_description(...)` is
already explicit about what it wants, and a user's own `myschema.obj_description`
is theirs.

This is the mechanism the remaining catalog functions will use as they are
needed. `catalog/catalog_functions.py` holds Python implementations of several
(`format_type`, …) written for feature 033, but nothing
calls it any more: it worked when a handler answered the whole query in Python,
which stopped being true once catalog tables became real IRIS views. Those will
have to be installed as SQL functions to be reachable from inside a query.

(Note for readers: `catalog/functions.py` is the registry of SQL functions
pgwire installs *into* IRIS. `catalog/catalog_functions.py` is the older,
unreachable Python emulation. Different things, unfortunately similar names.)
"""

from __future__ import annotations

import re

# PostgreSQL name -> PGWire SQL function name. The value is the SqlName as
# installed by catalog/functions.py.
PG_FUNCTION_MAP: dict[str, str] = {
    "obj_description": "PGWire.OBJ_DESCRIPTION",
    "pg_get_constraintdef": "PGWire.PG_GET_CONSTRAINTDEF",
    "format_type": "PGWire.FORMAT_TYPE",
    "pg_get_expr": "PGWire.PG_GET_EXPR",
    "col_description": "PGWire.COL_DESCRIPTION",
}

# `name(` not preceded by a dot or word character, so a qualified call
# (pg_catalog.obj_description) and a longer identifier are both left alone.
_CALL_PATTERNS: dict[str, re.Pattern[str]] = {
    name: re.compile(rf"(?<![\w.]){re.escape(name)}\s*\(", re.IGNORECASE)
    for name in PG_FUNCTION_MAP
}


def has_pg_function_call(sql: str) -> bool:
    """True if the statement calls a catalog function pgwire has to redirect."""
    if "(" not in sql:
        return False
    lowered = sql.lower()
    return any(name in lowered for name in PG_FUNCTION_MAP)


def rewrite_pg_function_calls(sql: str) -> str:
    """Qualify unqualified catalog function calls with the PGWire schema."""
    if not has_pg_function_call(sql):
        return sql

    for name, replacement in PG_FUNCTION_MAP.items():
        sql = _CALL_PATTERNS[name].sub(f"{replacement}(", sql)
    return sql

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

# Variadic functions that need argument-count-based dispatch (feature 047).
# format(pattern, arg)       -> PGWire.FORMAT2(pattern, arg)
# format(pattern, arg1, arg2)-> PGWire.FORMAT3(pattern, arg1, arg2)
# jsonb_build_object(k,v,k,v)  -> PGWire.JSONB_BUILD_OBJECT4(...)
# jsonb_build_object(k,v,k,v,k,v) -> PGWire.JSONB_BUILD_OBJECT6(...)
_FORMAT_CALL = re.compile(r"(?<![\w.])format\s*\(", re.IGNORECASE)
_JSONB_CALL = re.compile(r"(?<![\w.])jsonb_build_object\s*\(", re.IGNORECASE)

_VARIADIC_NAMES = {"format", "jsonb_build_object"}

# Dispatch tables: arg count -> replacement name (None = pass through)
_FORMAT_DISPATCH: dict[int, str | None] = {
    2: "PGWire.FORMAT2",
    3: "PGWire.FORMAT3",
}
_JSONB_DISPATCH: dict[int, str | None] = {
    4: "PGWire.JSONB_BUILD_OBJECT4",
    6: "PGWire.JSONB_BUILD_OBJECT6",
}


def _count_args(args_text: str) -> int:
    """Count top-level comma-separated arguments in a function arg list.

    Handles nested parentheses so commas inside sub-expressions are not
    counted as argument separators.
    """
    if not args_text.strip():
        return 0
    depth = 0
    count = 1
    for char in args_text:
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif char == "," and depth == 0:
            count += 1
    return count


def _rewrite_variadic_calls(sql: str) -> str:
    """Rewrite format() and jsonb_build_object() to fixed-arity PGWire variants."""
    for pattern, dispatch in ((_FORMAT_CALL, _FORMAT_DISPATCH), (_JSONB_CALL, _JSONB_DISPATCH)):
        result = []
        pos = 0
        for m in pattern.finditer(sql):
            result.append(sql[pos:m.start()])
            # Find the matching close-paren to extract the argument list text
            open_pos = m.end()  # position just after the '('
            depth = 1
            i = open_pos
            while i < len(sql) and depth > 0:
                if sql[i] == "(":
                    depth += 1
                elif sql[i] == ")":
                    depth -= 1
                i += 1
            close_pos = i - 1  # position of the matching ')'
            args_text = sql[open_pos:close_pos]
            n = _count_args(args_text)
            replacement = dispatch.get(n)
            if replacement is None:
                # Unsupported arity — pass through unchanged
                result.append(sql[m.start():i])
            else:
                result.append(f"{replacement}({args_text})")
            pos = i
        result.append(sql[pos:])
        sql = "".join(result)
    return sql


def has_pg_function_call(sql: str) -> bool:
    """True if the statement calls a catalog function pgwire has to redirect."""
    if "(" not in sql:
        return False
    lowered = sql.lower()
    return any(name in lowered for name in {**PG_FUNCTION_MAP, **{n: n for n in _VARIADIC_NAMES}})


def rewrite_pg_function_calls(sql: str) -> str:
    """Qualify unqualified catalog function calls with the PGWire schema."""
    if not has_pg_function_call(sql):
        return sql

    # Variadic dispatch first (produces qualified names, so simple-map pass won't touch them)
    sql = _rewrite_variadic_calls(sql)

    for name, replacement in PG_FUNCTION_MAP.items():
        sql = _CALL_PATTERNS[name].sub(f"{replacement}(", sql)
    return sql

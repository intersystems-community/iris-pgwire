"""Answer psycopg's ``TypeInfo.fetch()`` query from PGWire's own pg_type rows.

psycopg looks a type up by name with::

    SELECT typname AS name, oid, typarray AS array_oid,
        oid::regtype::text AS regtype, typdelim AS delimiter
    FROM pg_type t WHERE t.oid = to_regtype(%(name)s) ORDER BY t.oid

SQLAlchemy's psycopg dialect sends it for ``hstore`` on every new engine, and pgvector's
``register_vector`` sends it for ``vector``. IRIS has no ``regtype`` and no ``to_regtype()``, so
the statement used to fail and take ``engine.connect()`` with it. The answer here comes from
``pg_type_data``, the same rows the ``pg_catalog.pg_type`` view serves, so a client sees one
consistent catalog.

``to_regtype()`` is emulated for what clients pass: a type name, optionally schema-qualified,
optionally quoted, optionally with a type modifier or a trailing ``[]``, or one of PostgreSQL's
SQL-standard names (``integer``, ``double precision``, ...). A name PGWire's pg_type does not
hold gives no row, as ``to_regtype()`` gives NULL in PostgreSQL.
"""

from __future__ import annotations

import re

from iris_pgwire.catalog.pg_type_data import PG_TYPE_COLUMNS, PG_TYPE_ROWS

_PG_CATALOG_NAMESPACE = 11
_PUBLIC_NAMESPACE = 2200

_COL = {name: index for index, name in enumerate(PG_TYPE_COLUMNS)}
_BY_NAME = {row[_COL["typname"]]: row for row in PG_TYPE_ROWS}
_BY_OID = {row[_COL["oid"]]: row for row in PG_TYPE_ROWS}

# `oid::regtype::text` for the rows where PostgreSQL 16's display name is not the typname,
# measured on iris-pgwire-pgref (PostgreSQL 16.15) on 2026-11-14. Array types display as their
# element's name followed by [], which _display() derives.
_DISPLAY_NAMES = {
    "bool": "boolean",
    "char": '"char"',
    "int2": "smallint",
    "int4": "integer",
    "int8": "bigint",
    "float4": "real",
    "float8": "double precision",
    "bpchar": "character",
    "varchar": "character varying",
    "varbit": "bit varying",
    "time": "time without time zone",
    "timetz": "time with time zone",
    "timestamp": "timestamp without time zone",
    "timestamptz": "timestamp with time zone",
}

# Names to_regtype() accepts for a type besides its typname: the display names above, and the
# SQL-standard spellings PostgreSQL's grammar maps to them.
_ALIASES = {display: typname for typname, display in _DISPLAY_NAMES.items()}
_ALIASES.update({"int": "int4", "decimal": "numeric", "float": "float8", "char": "bpchar"})
# The quoted "char" is the one-byte internal type, not character(1).
_ALIASES.pop('"char"', None)

_TYPMOD = re.compile(r"\s*\([^)]*\)")
_SPACES = re.compile(r"\s+")

# The statement's columns and their PostgreSQL types: name, oid, oid, text, "char".
TYPE_INFO_COLUMNS = (
    ("name", 19, 64),
    ("oid", 26, 4),
    ("array_oid", 26, 4),
    ("regtype", 25, -1),
    ("delimiter", 18, 1),
)

# psycopg's query after any of PGWire's rewrites: `$1` or `?`, `oid::regtype::text` or what the
# pipeline leaves of it, pg_type optionally qualified and quoted, an optional trailing semicolon.
_TYPE_INFO_QUERY = re.compile(
    r"^\s*SELECT\s+TYPNAME\s+AS\s+NAME\s*,\s*OID\s*,\s*TYPARRAY\s+AS\s+ARRAY_OID\s*,\s*"
    r"OID\s*(?:::\s*REGTYPE\s*)?::\s*TEXT\s+AS\s+REGTYPE\s*,\s*TYPDELIM\s+AS\s+DELIMITER\s+"
    r"FROM\s+(?:PG_CATALOG\s*\.\s*)?\"?PG_TYPE\"?\s+T\s+"
    r"WHERE\s+T\s*\.\s*OID\s*=\s*TO_REGTYPE\s*\(\s*(?:\$1|\?|%S)\s*\)\s*"
    r"ORDER\s+BY\s+T\s*\.\s*OID\s*;?\s*$",
    re.IGNORECASE,
)


def is_type_info_query(sql: str) -> bool:
    """True for psycopg's TypeInfo lookup (and only that shape of to_regtype() query)."""
    return "TO_REGTYPE" in sql.upper() and bool(_TYPE_INFO_QUERY.match(sql))


def _display(row) -> str:
    typname = row[_COL["typname"]]
    element = row[_COL["typelem"]]
    if typname.startswith("_") and element in _BY_OID:
        return _display(_BY_OID[element]) + "[]"
    return _DISPLAY_NAMES.get(typname, typname)


def resolve_regtype(name: str | None):
    """The pg_type row ``to_regtype(name)`` would find, or None."""
    text = (name or "").strip()
    if not text:
        return None
    is_array = text.endswith("[]")
    if is_array:
        text = text[:-2].rstrip()
    text = _TYPMOD.sub("", text)

    namespace = None
    if "." in text:
        qualifier, _, text = text.partition(".")
        qualifier = qualifier.strip().strip('"').lower()
        namespace = {"pg_catalog": _PG_CATALOG_NAMESPACE, "public": _PUBLIC_NAMESPACE}.get(
            qualifier
        )
        if namespace is None:
            return None
        text = text.strip()

    if text.startswith('"') and text.endswith('"') and len(text) >= 2:
        typname = text[1:-1]  # quoted: exact, case-sensitive, no aliases
    else:
        lowered = _SPACES.sub(" ", text.lower())
        typname = _ALIASES.get(lowered, lowered)

    row = _BY_NAME.get(typname)
    if row is None:
        return None
    if namespace is not None and row[_COL["typnamespace"]] != namespace:
        return None
    if is_array:
        row = _BY_OID.get(row[_COL["typarray"]])
    return row


def type_info_rows(params) -> list[list]:
    """Rows for the TypeInfo query with ``params`` bound (none when nothing is bound yet)."""
    if not params:
        return []
    name = params[0]
    if isinstance(name, bytes | bytearray):
        name = bytes(name).decode("utf-8", "replace")
    row = resolve_regtype(name if isinstance(name, str) else None)
    if row is None:
        return []
    return [
        [
            row[_COL["typname"]],
            row[_COL["oid"]],
            row[_COL["typarray"]],
            _display(row),
            row[_COL["typdelim"]],
        ]
    ]

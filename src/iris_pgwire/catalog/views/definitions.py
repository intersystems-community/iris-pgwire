"""PostgreSQL catalog tables projected as IRIS views.

Rationale (see docs/orm-introspection-findings.md and specs/044-catalog-as-views):
the previous emulation matched *query shapes* in Python, so any shape a handler
did not recognise returned zero rows rather than an error. Three of six known
defects came from that, all failing silently. Exposing the catalog as real views
hands projections, aliases, joins, WHERE predicates and CTEs back to IRIS, which
already implements them correctly.

Each view is defined once here. `installer.py` creates them idempotently and the
router declines any table listed in VIEW_BACKED_TABLES so exactly one path
answers a given catalog table (spec FR-011).
"""

from __future__ import annotations

from dataclasses import dataclass

from iris_pgwire.schema_mapper import IRIS_SCHEMA

# The IRIS schema holding the emulated catalog. IRIS accepts a schema named
# `pg_catalog`, so clients can address these objects exactly as they would on
# PostgreSQL — bare or schema-qualified (spec FR-002).
CATALOG_SCHEMA = "pg_catalog"

# Well-known namespace OIDs, matching PostgreSQL so clients recognise them.
PG_CATALOG_OID = 11
PUBLIC_OID = 2200
INFORMATION_SCHEMA_OID = 11323


@dataclass(frozen=True)
class CatalogView:
    """One catalog table exposed as a view.

    `columns` is the PostgreSQL column list in PostgreSQL's order. Clients read
    results by name, but order is kept faithful so positional access also works
    (spec FR-004).
    """

    name: str
    columns: tuple[str, ...]
    body: str

    @property
    def qualified_name(self) -> str:
        return f"{CATALOG_SCHEMA}.{self.name}"

    def create_sql(self) -> str:
        return f"CREATE VIEW {self.qualified_name} AS {self.body}"

    def drop_sql(self) -> str:
        return f"DROP VIEW {self.qualified_name}"


# --- pg_namespace ------------------------------------------------------------
# Static: the three schemas a PostgreSQL client expects to exist. `public` must
# be present or introspection concludes the database is empty and tries to
# CREATE SCHEMA "public" (spec FR-005; the original defect 1).
#
# `public` comes from PGWire.PG_PUBLIC_SCHEMA() rather than a literal: the SQL
# translation layer rewrites a literal 'public' to the IRIS schema name as the
# DDL goes in, so the view would report 'SQLUser' to clients.
_PG_NAMESPACE_BODY = f"""
SELECT {PG_CATALOG_OID} AS oid, 'pg_catalog' AS nspname, 10 AS nspowner, NULL AS nspacl
UNION ALL
SELECT {PUBLIC_OID}, PGWire.PG_PUBLIC_SCHEMA(), 10, NULL
UNION ALL
SELECT {INFORMATION_SCHEMA_OID}, 'information_schema', 10, NULL
""".strip()

PG_NAMESPACE = CatalogView(
    name="pg_namespace",
    columns=("oid", "nspname", "nspowner", "nspacl"),
    body=_PG_NAMESPACE_BODY,
)


# --- pg_class ----------------------------------------------------------------
# Sourced from INFORMATION_SCHEMA.TABLES at query time, so a table created after
# server start is visible immediately with no cache to invalidate (spec FR-003).
#
# relkind: 'r' = ordinary table, 'v' = view.
# Names are lowercased because PostgreSQL folds unquoted identifiers to lower
# case and clients compare against that.
_PG_CLASS_BODY = f"""
SELECT
    PGWire.PG_OID('{IRIS_SCHEMA.lower()}:table:' || LOWER(t.TABLE_NAME)) AS oid,
    LOWER(t.TABLE_NAME) AS relname,
    {PUBLIC_OID} AS relnamespace,
    -- Every table has a composite row type, and `reltype` is *that* object's OID
    -- — a different object from the table, so a different identity string.
    --
    -- This was 0, and Prisma's columns query filters its pg_class subquery on
    -- `reltype > 0`. Measured: 0 of 9 rows survived, so the columns query
    -- returned nothing however correct pg_attribute and format_type were. Nothing
    -- downstream of it was observable until this stopped being a constant.
    PGWire.PG_OID('{IRIS_SCHEMA.lower()}:rowtype:' || LOWER(t.TABLE_NAME)) AS reltype,
    0 AS reloftype,
    10 AS relowner,
    0 AS relam,
    0 AS relfilenode,
    0 AS reltablespace,
    0 AS relpages,
    0 AS reltuples,
    0 AS relallvisible,
    0 AS reltoastrelid,
    0 AS relhasindex,
    0 AS relisshared,
    'p' AS relpersistence,
    CASE WHEN t.TABLE_TYPE = 'VIEW' THEN 'v' ELSE 'r' END AS relkind,
    0 AS relnatts,
    0 AS relchecks,
    0 AS relhasrules,
    0 AS relhastriggers,
    0 AS relhassubclass,
    0 AS relrowsecurity,
    0 AS relforcerowsecurity,
    1 AS relispopulated,
    'd' AS relreplident,
    0 AS relispartition,
    0 AS relrewrite,
    0 AS relfrozenxid,
    0 AS relminmxid,
    NULL AS relacl,
    NULL AS reloptions
FROM INFORMATION_SCHEMA.TABLES t
WHERE t.TABLE_SCHEMA = '{IRIS_SCHEMA}'
  AND t.TABLE_TYPE IN ('BASE TABLE', 'VIEW')
""".strip()

PG_CLASS = CatalogView(
    name="pg_class",
    columns=(
        "oid",
        "relname",
        "relnamespace",
        "reltype",
        "reloftype",
        "relowner",
        "relam",
        "relfilenode",
        "reltablespace",
        "relpages",
        "reltuples",
        "relallvisible",
        "reltoastrelid",
        "relhasindex",
        "relisshared",
        "relpersistence",
        "relkind",
        "relnatts",
        "relchecks",
        "relhasrules",
        "relhastriggers",
        "relhassubclass",
        "relrowsecurity",
        "relforcerowsecurity",
        "relispopulated",
        "relreplident",
        "relispartition",
        "relrewrite",
        "relfrozenxid",
        "relminmxid",
        "relacl",
        "reloptions",
    ),
    body=_PG_CLASS_BODY,
)


# --- pg_constraint -----------------------------------------------------------
# One row per constraint (spec FR-016…FR-021). Sources, measured on IRIS 2026.2:
#
#   TABLE_CONSTRAINTS        one row per constraint: name, type, table, deferrability
#   KEY_COLUMN_USAGE         one row per constrained column, plus the REFERENCED_* side
#   REFERENTIAL_CONSTRAINTS  UPDATE_RULE, DELETE_RULE, MATCH_OPTION, referenced table
#   COLUMNS                  ORDINAL_POSITION — the number pg_attribute.attnum reports
#
# Two things here are easy to get wrong and were verified against real metadata:
#
# * `conkey` must carry **table-relative** column positions. IRIS's
#   KEY_COLUMN_USAGE.ORDINAL_POSITION is the position *within the constraint* — 1
#   for every single-column key, whatever the column's place in the table — so the
#   position comes from INFORMATION_SCHEMA.COLUMNS instead. Measured: the foreign
#   key on T015Child.parent_id (the table's 2nd column) yields conkey {2}, which
#   ORDINAL_POSITION alone would have reported as {1} (spec FR-018).
#
# * IRIS has no `LIST_AGG`. `LIST()` exists and joins with commas, which is exactly
#   what PostgreSQL's int2[] text format needs inside braces.
#
# IRIS 2026.2 rejects `CONSTRAINT c CHECK (…)` outright (SQLCODE -1), so no CHECK
# rows can exist. The 'c' mapping is kept because the code belongs to the wire
# contract, and a client asking only for check constraints then gets zero rows —
# an answer, not an error (spec FR-021, the CHK045 rule).
_PG_CONSTRAINT_BODY = f"""
SELECT
    PGWire.PG_OID('{IRIS_SCHEMA.lower()}:constraint:' || LOWER(tc.CONSTRAINT_NAME)) AS oid,
    tc.CONSTRAINT_NAME AS conname,
    {PUBLIC_OID} AS connamespace,
    CASE tc.CONSTRAINT_TYPE
        WHEN 'PRIMARY KEY' THEN 'p'
        WHEN 'FOREIGN KEY' THEN 'f'
        WHEN 'UNIQUE' THEN 'u'
        WHEN 'CHECK' THEN 'c'
        ELSE 'x'
    END AS contype,
    CASE WHEN tc.IS_DEFERRABLE = 'YES' THEN 1 ELSE 0 END AS condeferrable,
    CASE WHEN tc.INITIALLY_DEFERRED = 'YES' THEN 1 ELSE 0 END AS condeferred,
    1 AS convalidated,
    PGWire.PG_OID('{IRIS_SCHEMA.lower()}:table:' || LOWER(tc.TABLE_NAME)) AS conrelid,
    0 AS contypid,
    0 AS conindid,
    0 AS conparentid,
    CASE WHEN rc.UNIQUE_CONSTRAINT_TABLE IS NULL THEN 0
         ELSE PGWire.PG_OID('{IRIS_SCHEMA.lower()}:table:' || LOWER(rc.UNIQUE_CONSTRAINT_TABLE))
    END AS confrelid,
    CASE rc.UPDATE_RULE
        WHEN 'CASCADE' THEN 'c'
        WHEN 'SET NULL' THEN 'n'
        WHEN 'SET DEFAULT' THEN 'd'
        WHEN 'RESTRICT' THEN 'r'
        ELSE 'a'
    END AS confupdtype,
    CASE rc.DELETE_RULE
        WHEN 'CASCADE' THEN 'c'
        WHEN 'SET NULL' THEN 'n'
        WHEN 'SET DEFAULT' THEN 'd'
        WHEN 'RESTRICT' THEN 'r'
        ELSE 'a'
    END AS confdeltype,
    CASE rc.MATCH_OPTION
        WHEN 'FULL' THEN 'f'
        WHEN 'PARTIAL' THEN 'p'
        ELSE 's'
    END AS confmatchtype,
    1 AS conislocal,
    0 AS coninhcount,
    1 AS connoinherit,
    (SELECT '{{' || LIST(col.ORDINAL_POSITION) || '}}'
       FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE k
       JOIN INFORMATION_SCHEMA.COLUMNS col
         ON col.TABLE_SCHEMA = k.TABLE_SCHEMA
        AND col.TABLE_NAME = k.TABLE_NAME
        AND col.COLUMN_NAME = k.COLUMN_NAME
      WHERE k.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA
        AND k.CONSTRAINT_NAME = tc.CONSTRAINT_NAME) AS conkey,
    (SELECT '{{' || LIST(col.ORDINAL_POSITION) || '}}'
       FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE k
       JOIN INFORMATION_SCHEMA.COLUMNS col
         ON col.TABLE_SCHEMA = k.REFERENCED_TABLE_SCHEMA
        AND col.TABLE_NAME = k.REFERENCED_TABLE_NAME
        AND col.COLUMN_NAME = k.REFERENCED_COLUMN_NAME
      WHERE k.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA
        AND k.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
        AND k.REFERENCED_COLUMN_NAME IS NOT NULL) AS confkey,
    NULL AS conpfeqop,
    NULL AS conppeqop,
    NULL AS conffeqop,
    NULL AS confdelsetcols,
    NULL AS conexclop,
    NULL AS conbin
FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
LEFT JOIN INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc
       ON rc.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA
      AND rc.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
WHERE tc.TABLE_SCHEMA = '{IRIS_SCHEMA}'
""".strip()

PG_CONSTRAINT = CatalogView(
    name="pg_constraint",
    columns=(
        "oid",
        "conname",
        "connamespace",
        "contype",
        "condeferrable",
        "condeferred",
        "convalidated",
        "conrelid",
        "contypid",
        "conindid",
        "conparentid",
        "confrelid",
        "confupdtype",
        "confdeltype",
        "confmatchtype",
        "conislocal",
        "coninhcount",
        "connoinherit",
        "conkey",
        "confkey",
        "conpfeqop",
        "conppeqop",
        "conffeqop",
        "confdelsetcols",
        "conexclop",
        "conbin",
    ),
    body=_PG_CONSTRAINT_BODY,
)


# --- pg_views ----------------------------------------------------------------
# PostgreSQL's pg_views is itself a view, over pg_class and pg_rewrite: four
# columns, measured against postgres:15-alpine. IRIS keeps the same facts in
# INFORMATION_SCHEMA.VIEWS, VIEW_DEFINITION included.
#
# `schemaname` comes from PGWire.PG_PUBLIC_SCHEMA() for the same reason
# pg_namespace does: a literal 'public' in view DDL is rewritten to the IRIS
# schema name on its way in, so the view would report 'SQLUser' to clients.
#
# The TABLE_SCHEMA filter is not incidental. The instance genuinely contains
# pg_catalog.pg_class, pg_catalog.pg_constraint and pg_catalog.pg_namespace —
# pgwire's own emulation — and without the filter an ORM would generate models
# for them.
_PG_VIEWS_BODY = f"""
SELECT
    PGWire.PG_PUBLIC_SCHEMA() AS schemaname,
    LOWER(v.TABLE_NAME) AS viewname,
    'irisowner' AS viewowner,
    v.VIEW_DEFINITION AS definition
FROM INFORMATION_SCHEMA.VIEWS v
WHERE v.TABLE_SCHEMA = '{IRIS_SCHEMA}'
""".strip()

PG_VIEWS = CatalogView(
    name="pg_views",
    columns=("schemaname", "viewname", "viewowner", "definition"),
    body=_PG_VIEWS_BODY,
)


# --- pg_attribute ------------------------------------------------------------
# One row per user column, over INFORMATION_SCHEMA.COLUMNS. 26 columns, measured
# against postgres:15-alpine.
#
# `atttypmod` is not a free choice — `format_type` decodes it, and the encoding
# was measured rather than recalled: `varchar(100)` is `104` (length + 4) and
# `numeric(10,2)` is `655366` (precision × 65536 + scale + 4). Types without a
# modifier report -1. A wrong value here makes a client report the wrong column
# width, silently.
#
# `attname` is lowercased because PostgreSQL folds unquoted identifiers and
# because Prisma joins `att.attname = info.column_name` — both sides have to fold
# the same way or every column disappears from the join.
#
# `attlen` and `attbyval` follow from the type: fixed-size types have a positive
# length and are passed by value, varlena types are -1 and by reference.
_PG_ATTRIBUTE_BODY = f"""
SELECT
    PGWire.PG_OID('{IRIS_SCHEMA.lower()}:table:' || LOWER(c.TABLE_NAME)) AS attrelid,
    LOWER(c.COLUMN_NAME) AS attname,
    CASE UPPER(c.DATA_TYPE)
        WHEN 'INTEGER' THEN 23
        WHEN 'INT' THEN 23
        WHEN 'BIGINT' THEN 20
        WHEN 'SMALLINT' THEN 21
        WHEN 'TINYINT' THEN 21
        WHEN 'VARCHAR' THEN 1043
        WHEN 'CHARACTER VARYING' THEN 1043
        WHEN 'CHAR' THEN 1042
        WHEN 'LONGVARCHAR' THEN 25
        WHEN 'NUMERIC' THEN 1700
        WHEN 'DECIMAL' THEN 1700
        WHEN 'DOUBLE' THEN 701
        WHEN 'FLOAT' THEN 701
        WHEN 'BIT' THEN 16
        WHEN 'DATE' THEN 1082
        WHEN 'TIME' THEN 1083
        WHEN 'TIMESTAMP' THEN 1114
        WHEN 'POSIXTIME' THEN 1114
        ELSE 1043
    END AS atttypid,
    -1 AS attstattarget,
    CASE UPPER(c.DATA_TYPE)
        WHEN 'INTEGER' THEN 4
        WHEN 'INT' THEN 4
        WHEN 'BIGINT' THEN 8
        WHEN 'SMALLINT' THEN 2
        WHEN 'TINYINT' THEN 2
        WHEN 'DOUBLE' THEN 8
        WHEN 'FLOAT' THEN 8
        WHEN 'BIT' THEN 1
        WHEN 'DATE' THEN 4
        WHEN 'TIME' THEN 8
        WHEN 'TIMESTAMP' THEN 8
        WHEN 'POSIXTIME' THEN 8
        ELSE -1
    END AS attlen,
    c.ORDINAL_POSITION AS attnum,
    0 AS attndims,
    -1 AS attcacheoff,
    CASE
        WHEN UPPER(c.DATA_TYPE) IN ('VARCHAR', 'CHARACTER VARYING', 'CHAR')
             AND c.CHARACTER_MAXIMUM_LENGTH IS NOT NULL
            THEN c.CHARACTER_MAXIMUM_LENGTH + 4
        WHEN UPPER(c.DATA_TYPE) IN ('NUMERIC', 'DECIMAL')
             AND c.NUMERIC_PRECISION IS NOT NULL
            THEN (c.NUMERIC_PRECISION * 65536) + COALESCE(c.NUMERIC_SCALE, 0) + 4
        ELSE -1
    END AS atttypmod,
    CASE UPPER(c.DATA_TYPE)
        WHEN 'VARCHAR' THEN 0
        WHEN 'CHARACTER VARYING' THEN 0
        WHEN 'CHAR' THEN 0
        WHEN 'LONGVARCHAR' THEN 0
        WHEN 'NUMERIC' THEN 0
        WHEN 'DECIMAL' THEN 0
        ELSE 1
    END AS attbyval,
    'i' AS attalign,
    'p' AS attstorage,
    '' AS attcompression,
    CASE WHEN UPPER(c.IS_NULLABLE) = 'NO' THEN 1 ELSE 0 END AS attnotnull,
    CASE WHEN c.COLUMN_DEFAULT IS NULL THEN 0 ELSE 1 END AS atthasdef,
    0 AS atthasmissing,
    '' AS attidentity,
    '' AS attgenerated,
    0 AS attisdropped,
    1 AS attislocal,
    0 AS attinhcount,
    0 AS attcollation,
    NULL AS attacl,
    NULL AS attoptions,
    NULL AS attfdwoptions,
    NULL AS attmissingval
FROM INFORMATION_SCHEMA.COLUMNS c
WHERE UPPER(c.TABLE_SCHEMA) = '{IRIS_SCHEMA.upper()}'
""".strip()

PG_ATTRIBUTE = CatalogView(
    name="pg_attribute",
    columns=(
        "attrelid",
        "attname",
        "atttypid",
        "attstattarget",
        "attlen",
        "attnum",
        "attndims",
        "attcacheoff",
        "atttypmod",
        "attbyval",
        "attalign",
        "attstorage",
        "attcompression",
        "attnotnull",
        "atthasdef",
        "atthasmissing",
        "attidentity",
        "attgenerated",
        "attisdropped",
        "attislocal",
        "attinhcount",
        "attcollation",
        "attacl",
        "attoptions",
        "attfdwoptions",
        "attmissingval",
    ),
    body=_PG_ATTRIBUTE_BODY,
)


# --- pg_attrdef --------------------------------------------------------------
# Column defaults, one row per column that has one. PostgreSQL stores a parse
# tree in `adbin` and renders it with `pg_get_expr`; we have the expression text
# and no parse tree, so `adbin` carries the text and `pg_get_expr` returns it.
# That is an honest rendering of what IRIS knows, and it is what a client writes
# into a generated schema.
_PG_ATTRDEF_BODY = f"""
SELECT
    PGWire.PG_OID('{IRIS_SCHEMA.lower()}:attrdef:' || LOWER(c.TABLE_NAME)
        || ':' || LOWER(c.COLUMN_NAME)) AS oid,
    PGWire.PG_OID('{IRIS_SCHEMA.lower()}:table:' || LOWER(c.TABLE_NAME)) AS adrelid,
    c.ORDINAL_POSITION AS adnum,
    c.COLUMN_DEFAULT AS adbin
FROM INFORMATION_SCHEMA.COLUMNS c
WHERE UPPER(c.TABLE_SCHEMA) = '{IRIS_SCHEMA.upper()}'
  AND c.COLUMN_DEFAULT IS NOT NULL
""".strip()

PG_ATTRDEF = CatalogView(
    name="pg_attrdef",
    columns=("oid", "adrelid", "adnum", "adbin"),
    body=_PG_ATTRDEF_BODY,
)


# Ordered so dependencies are created first. pg_namespace has no dependencies;
# the rest reference its OIDs or its schema name by value.
CATALOG_VIEWS: tuple[CatalogView, ...] = (
    PG_NAMESPACE,
    PG_CLASS,
    PG_CONSTRAINT,
    PG_VIEWS,
    PG_ATTRIBUTE,
    PG_ATTRDEF,
)

# Tables now served by views. CatalogRouter declines these so exactly one path
# answers any catalog table (spec FR-011). Adding a view without adding its name
# here would leave the old handler intercepting and the view unreachable.
VIEW_BACKED_TABLES: frozenset[str] = frozenset(view.name for view in CATALOG_VIEWS)

# The catalog columns PostgreSQL declares as `bool`. Clients compare them
# against PostgreSQL boolean literals — Prisma writes `relispartition = 'f'` —
# and the views expose them as 0/1 integers, so the literal has to be translated
# (sql_translator/boolean_expr.rewrite_boolean_literal_comparisons).
#
# This is not cosmetic. Comparing one of these constant-valued columns to the
# string 'f' *crashes* IRIS with SQLCODE -400 when it sits inside a nested
# predicate group — `((relkind='r' AND relispartition='f') OR relkind='p')`,
# which is exactly the shape Prisma emits. Flat, the same comparison is fine;
# with `= 0` the nested form is fine; over a real table the nested form is fine.
# Measured on IRIS 2026.2, with and without pgwire in the path.
BOOLEAN_CATALOG_COLUMNS: frozenset[str] = frozenset(
    {
        "relhasindex",
        "relisshared",
        "relhasrules",
        "relhastriggers",
        "relhassubclass",
        "relrowsecurity",
        "relforcerowsecurity",
        "relispopulated",
        "relispartition",
        "nspacl",
        "attnotnull",
        "atthasdef",
        "attisdropped",
        "attislocal",
        "attgenerated",
        "indisunique",
        "indisprimary",
        "indisexclusion",
        "indimmediate",
        "indisclustered",
        "indisvalid",
        "condeferrable",
        "condeferred",
        "convalidated",
        "conislocal",
        "connoinherit",
    }
)


# The PostgreSQL type of each catalog column whose type the views cannot convey.
#
# The views hold 0/1 for booleans and NULL for the array-valued columns, and the
# embedded backend infers a column's type from the value it got back — which is a
# Python int even for a CAST(… AS BIT) column (measured). So without this the
# columns go out as int4/varchar and a client reading them at their documented
# types gets the wrong width: bool is one byte in binary format, int4 is four.
#
# Keyed by the catalog column name, looked up through the expression behind an
# output alias, because clients rename these freely — Prisma writes
# `tbl.relrowsecurity as has_row_level_security`.
CATALOG_COLUMN_TYPE_OIDS: dict[str, int] = {
    **{column: 16 for column in BOOLEAN_CATALOG_COLUMNS},
    # text[] in PostgreSQL. Always NULL here, but the declared type still has to
    # match or a typed client refuses the column.
    "reloptions": 1009,
    "relacl": 1009,
    "nspacl": 1009,
    "relpartbound": 1009,
    "indoption": 1009,
    # int2[], not text[]: these carry column positions. Declaring 1009 for them
    # would hand a typed client the wrong element type.
    "indkey": 1005,
    "conkey": 1005,
    "confkey": 1005,
    # `"char"` — a single byte, not a string. PostgreSQL declares contype and the
    # foreign-key action codes this way, and a client decodes one byte for it.
    "contype": 18,
    "confupdtype": 18,
    "confdeltype": 18,
    "confmatchtype": 18,
    "relpersistence": 18,
    "relkind": 18,
    "relreplident": 18,
}

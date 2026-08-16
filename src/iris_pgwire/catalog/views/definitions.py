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
    0 AS reltype,
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


# Ordered so dependencies are created first. pg_namespace has no dependencies;
# pg_class references its OIDs by value.
CATALOG_VIEWS: tuple[CatalogView, ...] = (
    PG_NAMESPACE,
    PG_CLASS,
)

# Tables now served by views. CatalogRouter declines these so exactly one path
# answers any catalog table (spec FR-011). Adding a view without adding its name
# here would leave the old handler intercepting and the view unreachable.
VIEW_BACKED_TABLES: frozenset[str] = frozenset(view.name for view in CATALOG_VIEWS)

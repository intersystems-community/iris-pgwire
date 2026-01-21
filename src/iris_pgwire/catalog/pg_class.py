"""
pg_class Catalog Emulation

Emulates PostgreSQL pg_catalog.pg_class system table.
Provides table/view/index metadata for Prisma introspection.

relkind values:
- 'r' = ordinary table
- 'i' = index
- 'S' = sequence
- 'v' = view
- 'm' = materialized view
- 'c' = composite type
- 'f' = foreign table
- 'p' = partitioned table
"""

from dataclasses import dataclass
from typing import Any, Literal

from iris_pgwire.schema_mapper import IRIS_SCHEMA
from .oid_generator import OIDGenerator

RelKind = Literal["r", "i", "S", "v", "m", "c", "f", "p"]


@dataclass
class PgClass:
    """
    pg_catalog.pg_class row.

    PostgreSQL Documentation:
    https://www.postgresql.org/docs/current/catalog-pg-class.html
    """

    oid: int  # Table OID
    relname: str  # Relation name
    relnamespace: int  # Namespace OID (pg_namespace.oid)
    reltype: int  # OID of data type for this relation's row type
    reloftype: int  # OID of composite type, 0 if not based on type
    relowner: int  # Owner OID
    relam: int  # Access method OID (0 for tables)
    relfilenode: int  # File node (not relevant for IRIS)
    reltablespace: int  # Tablespace OID (0 for default)
    relpages: int  # Estimated pages (statistics)
    reltuples: float  # Estimated rows (statistics)
    relallvisible: int  # Pages marked all-visible
    reltoastrelid: int  # TOAST table OID (0 for IRIS)
    relhasindex: bool  # True if has any indexes
    relisshared: bool  # True if shared across databases
    relpersistence: str  # 'p' = permanent, 'u' = unlogged, 't' = temp
    relkind: RelKind  # Relation kind
    relnatts: int  # Number of user columns
    relchecks: int  # Number of CHECK constraints
    relhasrules: bool  # Has rewrite rules
    relhastriggers: bool  # Has triggers
    relhassubclass: bool  # Has inheritance children
    relrowsecurity: bool  # Has row security
    relforcerowsecurity: bool  # Force row security
    relispopulated: bool  # True if materialized view is populated
    relreplident: str  # Replica identity
    relispartition: bool  # Is a partition
    relrewrite: int  # Rewriting xid
    relfrozenxid: int  # Frozen transaction ID
    relminmxid: int  # Minimum multixact ID
    relacl: str | None  # Access privileges
    reloptions: str | None  # Access method options


class PgClassEmulator:
    """
    Emulate pg_class from IRIS INFORMATION_SCHEMA.TABLES.

    Query source:
    SELECT TABLE_NAME, TABLE_TYPE
    FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_SCHEMA = '{IRIS_SCHEMA}'
    """

    def __init__(self, oid_generator: OIDGenerator):
        """
        Initialize pg_class emulator.

        Args:
            oid_generator: OIDGenerator for deterministic OIDs
        """
        self.oid_gen = oid_generator
        self._tables: list[PgClass] = []
        self._by_name: dict[str, PgClass] = {}
        self._by_oid: dict[int, PgClass] = {}

    def from_iris_table(
        self, table_name: str, table_type: str, schema: str = IRIS_SCHEMA
    ) -> PgClass:
        """
        Convert IRIS table metadata to pg_class row.

        Args:
            table_name: Table name
            table_type: IRIS table type ('BASE TABLE', 'VIEW')
            schema: IRIS schema name (e.g., '{IRIS_SCHEMA}')

        Returns:
            PgClass instance
        """
        # Determine relkind from TABLE_TYPE
        relkind: RelKind = "r" if table_type == "BASE TABLE" else "v"

        table_oid = self.oid_gen.get_table_oid(table_name, schema)

        namespace_oid = self.oid_gen.get_namespace_oid("public")

        return PgClass(
            oid=table_oid,
            relname=table_name.lower(),  # PostgreSQL uses lowercase
            relnamespace=namespace_oid,
            reltype=0,  # No row type
            reloftype=0,
            relowner=10,  # postgres superuser
            relam=0,  # No access method for tables
            relfilenode=table_oid,  # Use OID as filenode
            reltablespace=0,  # Default tablespace
            relpages=1,  # Estimate
            reltuples=0,  # Unknown
            relallvisible=0,
            reltoastrelid=0,  # No TOAST
            relhasindex=False,  # Will be updated
            relisshared=False,
            relpersistence="p",  # Permanent
            relkind=relkind,
            relnatts=0,  # Will be updated
            relchecks=0,
            relhasrules=False,
            relhastriggers=False,
            relhassubclass=False,
            relrowsecurity=False,
            relforcerowsecurity=False,
            relispopulated=True,
            relreplident="d",  # Default
            relispartition=False,
            relrewrite=0,
            relfrozenxid=0,
            relminmxid=0,
            relacl=None,
            reloptions=None,
        )

    def create_index_entry(
        self,
        table_name: str,
        index_name: str,
        num_columns: int,
        schema: str = IRIS_SCHEMA,
    ) -> PgClass:
        """
        Create pg_class entry for an index.

        Args:
            table_name: Parent table name
            index_name: Index name
            num_columns: Number of columns in index
            schema: Schema name

        Returns:
            PgClass for index
        """
        index_oid = self.oid_gen.get_index_oid(index_name, schema)

        namespace_oid = self.oid_gen.get_namespace_oid("public")

        return PgClass(
            oid=index_oid,
            relname=f"{table_name.lower()}_{index_name.lower()}_idx",
            relnamespace=namespace_oid,
            reltype=0,
            reloftype=0,
            relowner=10,
            relam=403,  # btree access method
            relfilenode=index_oid,
            reltablespace=0,
            relpages=1,
            reltuples=0,
            relallvisible=0,
            reltoastrelid=0,
            relhasindex=False,
            relisshared=False,
            relpersistence="p",
            relkind="i",  # index
            relnatts=num_columns,
            relchecks=0,
            relhasrules=False,
            relhastriggers=False,
            relhassubclass=False,
            relrowsecurity=False,
            relforcerowsecurity=False,
            relispopulated=True,
            relreplident="n",
            relispartition=False,
            relrewrite=0,
            relfrozenxid=0,
            relminmxid=0,
            relacl=None,
            reloptions=None,
        )

    def add_table(self, pg_class: PgClass) -> None:
        """
        Add a table/view/index to the emulator.

        Args:
            pg_class: PgClass instance to add
        """
        self._tables.append(pg_class)
        self._by_name[pg_class.relname] = pg_class
        self._by_oid[pg_class.oid] = pg_class

    def get_all(self) -> list[PgClass]:
        """
        Return all relations.

        Returns:
            List of PgClass objects
        """
        return self._tables

    def get_all_as_rows(self) -> list[tuple[Any, ...]]:
        """
        Return all relations as query result rows.

        Returns:
            List of tuples matching pg_class column order
        """
        return [self._to_row(t) for t in self._tables]

    def get_by_name(self, name: str) -> PgClass | None:
        """
        Get relation by name.

        Args:
            name: Relation name (lowercase)

        Returns:
            PgClass if found, None otherwise
        """
        return self._by_name.get(name.lower())

    def get_by_oid(self, oid: int) -> PgClass | None:
        """
        Get relation by OID.

        Args:
            oid: Relation OID

        Returns:
            PgClass if found, None otherwise
        """
        return self._by_oid.get(oid)

    def _to_row(self, pg_class: PgClass) -> tuple[Any, ...]:
        """
        Convert PgClass to query result row.

        Args:
            pg_class: PgClass instance

        Returns:
            Tuple of values matching pg_class column order
        """
        return (
            pg_class.oid,
            pg_class.relname,
            pg_class.relnamespace,
            pg_class.reltype,
            pg_class.reloftype,
            pg_class.relowner,
            pg_class.relam,
            pg_class.relfilenode,
            pg_class.reltablespace,
            pg_class.relpages,
            pg_class.reltuples,
            pg_class.relallvisible,
            pg_class.reltoastrelid,
            pg_class.relhasindex,
            pg_class.relisshared,
            pg_class.relpersistence,
            pg_class.relkind,
            pg_class.relnatts,
            pg_class.relchecks,
            pg_class.relhasrules,
            pg_class.relhastriggers,
            pg_class.relhassubclass,
            pg_class.relrowsecurity,
            pg_class.relforcerowsecurity,
            pg_class.relispopulated,
            pg_class.relreplident,
            pg_class.relispartition,
            pg_class.relrewrite,
            pg_class.relfrozenxid,
            pg_class.relminmxid,
            pg_class.relacl,
            pg_class.reloptions,
        )

    @staticmethod
    def get_column_definitions() -> list[dict[str, Any]]:
        """
        Get PostgreSQL column definitions for pg_class.

        Returns:
            List of column metadata dicts
        """
        return [
            {"name": "oid", "type_oid": 26, "type_name": "oid"},
            {"name": "relname", "type_oid": 19, "type_name": "name"},
            {"name": "relnamespace", "type_oid": 26, "type_name": "oid"},
            {"name": "reltype", "type_oid": 26, "type_name": "oid"},
            {"name": "reloftype", "type_oid": 26, "type_name": "oid"},
            {"name": "relowner", "type_oid": 26, "type_name": "oid"},
            {"name": "relam", "type_oid": 26, "type_name": "oid"},
            {"name": "relfilenode", "type_oid": 26, "type_name": "oid"},
            {"name": "reltablespace", "type_oid": 26, "type_name": "oid"},
            {"name": "relpages", "type_oid": 23, "type_name": "int4"},
            {"name": "reltuples", "type_oid": 700, "type_name": "float4"},
            {"name": "relallvisible", "type_oid": 23, "type_name": "int4"},
            {"name": "reltoastrelid", "type_oid": 26, "type_name": "oid"},
            {"name": "relhasindex", "type_oid": 16, "type_name": "bool"},
            {"name": "relisshared", "type_oid": 16, "type_name": "bool"},
            {"name": "relpersistence", "type_oid": 18, "type_name": "char"},
            {"name": "relkind", "type_oid": 18, "type_name": "char"},
            {"name": "relnatts", "type_oid": 21, "type_name": "int2"},
            {"name": "relchecks", "type_oid": 21, "type_name": "int2"},
            {"name": "relhasrules", "type_oid": 16, "type_name": "bool"},
            {"name": "relhastriggers", "type_oid": 16, "type_name": "bool"},
            {"name": "relhassubclass", "type_oid": 16, "type_name": "bool"},
            {"name": "relrowsecurity", "type_oid": 16, "type_name": "bool"},
            {"name": "relforcerowsecurity", "type_oid": 16, "type_name": "bool"},
            {"name": "relispopulated", "type_oid": 16, "type_name": "bool"},
            {"name": "relreplident", "type_oid": 18, "type_name": "char"},
            {"name": "relispartition", "type_oid": 16, "type_name": "bool"},
            {"name": "relrewrite", "type_oid": 26, "type_name": "oid"},
            {"name": "relfrozenxid", "type_oid": 28, "type_name": "xid"},
            {"name": "relminmxid", "type_oid": 28, "type_name": "xid"},
            {"name": "relacl", "type_oid": 1034, "type_name": "aclitem[]"},
            {"name": "reloptions", "type_oid": 1009, "type_name": "text[]"},
        ]

"""
pg_index Catalog Emulation

Emulates PostgreSQL pg_catalog.pg_index system table.
Provides index metadata for Prisma introspection.

Note: IRIS INFORMATION_SCHEMA doesn't directly expose indexes.
We generate index entries for primary key and unique constraints,
which is sufficient for Prisma introspection.
"""

from dataclasses import dataclass, field
from typing import Any

from iris_pgwire.schema_mapper import IRIS_SCHEMA
from .oid_generator import OIDGenerator
from .pg_class import PgClass


@dataclass
class PgIndex:
    """
    pg_catalog.pg_index row.

    PostgreSQL Documentation:
    https://www.postgresql.org/docs/current/catalog-pg-index.html
    """

    indexrelid: int  # Index OID (pg_class.oid)
    indrelid: int  # Table OID (pg_class.oid)
    indnatts: int  # Total columns in index
    indnkeyatts: int  # Key columns (excluding INCLUDE)
    indisunique: bool  # Is unique index
    indisprimary: bool  # Is primary key index
    indisexclusion: bool  # Is exclusion constraint
    indimmediate: bool  # Unique check enforced immediately
    indisclustered: bool  # Table was clustered on this index
    indisvalid: bool  # Index is valid
    indcheckxmin: bool  # Check xmin
    indisready: bool  # Index is ready
    indislive: bool  # Index is live
    indisreplident: bool  # Is replica identity
    indkey: list[int] = field(default_factory=list)  # Column numbers (attnum array)
    indcollation: list[int] = field(default_factory=list)  # Collation OIDs
    indclass: list[int] = field(default_factory=list)  # Operator class OIDs
    indoption: list[int] = field(default_factory=list)  # Per-column flags
    indexprs: str | None = None  # Expression trees (expression indexes)
    indpred: str | None = None  # Partial index predicate


class PgIndexEmulator:
    """
    Emulate pg_index from IRIS metadata.

    Note: IRIS INFORMATION_SCHEMA doesn't directly expose indexes.
    We generate index entries for primary key constraints and
    unique constraints, which is sufficient for Prisma introspection.
    """

    def __init__(self, oid_generator: OIDGenerator):
        """
        Initialize pg_index emulator.

        Args:
            oid_generator: OIDGenerator for deterministic OIDs
        """
        self.oid_gen = oid_generator
        self._indexes: list[tuple[PgClass, PgIndex]] = []
        self._by_table: dict[int, list[PgIndex]] = {}

    def from_primary_key(
        self,
        table_name: str,
        constraint_name: str,
        column_positions: list[int],
        schema: str = IRIS_SCHEMA,
    ) -> tuple[PgClass, PgIndex]:
        """
        Generate pg_class and pg_index entries for a primary key.

        Returns both the index relation (pg_class) and index details (pg_index).

        Args:
            table_name: Table name
            constraint_name: PK constraint name
            column_positions: Column positions (attnum values)
            schema: Schema name

        Returns:
            Tuple of (PgClass for index, PgIndex entry)
        """
        return self._create_index(
            table_name=table_name,
            index_name=f"{table_name}_{constraint_name}_idx",
            column_positions=column_positions,
            is_unique=True,
            is_primary=True,
            schema=schema,
        )

    def from_unique_constraint(
        self,
        table_name: str,
        constraint_name: str,
        column_positions: list[int],
        schema: str = IRIS_SCHEMA,
    ) -> tuple[PgClass, PgIndex]:
        """
        Generate pg_class and pg_index entries for a unique constraint.

        Args:
            table_name: Table name
            constraint_name: Unique constraint name
            column_positions: Column positions (attnum values)
            schema: Schema name

        Returns:
            Tuple of (PgClass for index, PgIndex entry)
        """
        return self._create_index(
            table_name=table_name,
            index_name=f"{table_name}_{constraint_name}_idx",
            column_positions=column_positions,
            is_unique=True,
            is_primary=False,
            schema=schema,
        )

    def _create_index(
        self,
        table_name: str,
        index_name: str,
        column_positions: list[int],
        is_unique: bool,
        is_primary: bool,
        schema: str = IRIS_SCHEMA,
    ) -> tuple[PgClass, PgIndex]:
        """
        Create pg_class and pg_index entries for an index.

        Args:
            table_name: Table name
            index_name: Index name
            column_positions: Column positions
            is_unique: Is unique index
            is_primary: Is primary key index
            schema: Schema name

        Returns:
            Tuple of (PgClass, PgIndex)
        """
        table_oid = self.oid_gen.get_table_oid(table_name, schema)
        index_oid = self.oid_gen.get_index_oid(index_name, schema)
        namespace_oid = self.oid_gen.get_namespace_oid("public")

        # Create pg_class entry for the index
        index_class = PgClass(
            oid=index_oid,
            relname=index_name.lower(),
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
            relnatts=len(column_positions),
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

        # Create pg_index entry
        pg_index = PgIndex(
            indexrelid=index_oid,
            indrelid=table_oid,
            indnatts=len(column_positions),
            indnkeyatts=len(column_positions),
            indisunique=is_unique,
            indisprimary=is_primary,
            indisexclusion=False,
            indimmediate=True,
            indisclustered=False,
            indisvalid=True,
            indcheckxmin=False,
            indisready=True,
            indislive=True,
            indisreplident=False,
            indkey=column_positions,
            indcollation=[0] * len(column_positions),
            indclass=[1978] * len(column_positions),  # int4_ops
            indoption=[0] * len(column_positions),
            indexprs=None,
            indpred=None,
        )

        return index_class, pg_index

    def add_index(self, index_class: PgClass, pg_index: PgIndex) -> None:
        """
        Add an index to the emulator.

        Args:
            index_class: PgClass entry for the index
            pg_index: PgIndex entry
        """
        self._indexes.append((index_class, pg_index))

        # Index by table OID
        if pg_index.indrelid not in self._by_table:
            self._by_table[pg_index.indrelid] = []
        self._by_table[pg_index.indrelid].append(pg_index)

    def get_all_indexes(self) -> list[PgIndex]:
        """
        Return all pg_index entries.

        Returns:
            List of PgIndex objects
        """
        return [idx for _, idx in self._indexes]

    def get_all_index_classes(self) -> list[PgClass]:
        """
        Return all pg_class entries for indexes.

        Returns:
            List of PgClass objects
        """
        return [cls for cls, _ in self._indexes]

    def get_all_as_rows(self) -> list[tuple[Any, ...]]:
        """
        Return all indexes as query result rows.

        Returns:
            List of tuples matching pg_index column order
        """
        return [self._to_row(idx) for _, idx in self._indexes]

    def get_by_table_oid(self, table_oid: int) -> list[PgIndex]:
        """
        Get all indexes for a table.

        Args:
            table_oid: Table OID

        Returns:
            List of PgIndex for the table
        """
        return self._by_table.get(table_oid, [])

    def get_by_table_oid_as_rows(self, table_oid: int) -> list[tuple[Any, ...]]:
        """
        Get indexes for a table as rows.

        Args:
            table_oid: Table OID

        Returns:
            List of tuples
        """
        return [self._to_row(idx) for idx in self.get_by_table_oid(table_oid)]

    def _to_row(self, pg_index: PgIndex) -> tuple[Any, ...]:
        """
        Convert PgIndex to query result row.

        Args:
            pg_index: PgIndex instance

        Returns:
            Tuple of values matching pg_index column order
        """
        return (
            pg_index.indexrelid,
            pg_index.indrelid,
            pg_index.indnatts,
            pg_index.indnkeyatts,
            pg_index.indisunique,
            pg_index.indisprimary,
            pg_index.indisexclusion,
            pg_index.indimmediate,
            pg_index.indisclustered,
            pg_index.indisvalid,
            pg_index.indcheckxmin,
            pg_index.indisready,
            pg_index.indislive,
            pg_index.indisreplident,
            pg_index.indkey,
            pg_index.indcollation,
            pg_index.indclass,
            pg_index.indoption,
            pg_index.indexprs,
            pg_index.indpred,
        )

    @staticmethod
    def get_column_definitions() -> list[dict[str, Any]]:
        """
        Get PostgreSQL column definitions for pg_index.

        Returns:
            List of column metadata dicts
        """
        return [
            {"name": "indexrelid", "type_oid": 26, "type_name": "oid"},
            {"name": "indrelid", "type_oid": 26, "type_name": "oid"},
            {"name": "indnatts", "type_oid": 21, "type_name": "int2"},
            {"name": "indnkeyatts", "type_oid": 21, "type_name": "int2"},
            {"name": "indisunique", "type_oid": 16, "type_name": "bool"},
            {"name": "indisprimary", "type_oid": 16, "type_name": "bool"},
            {"name": "indisexclusion", "type_oid": 16, "type_name": "bool"},
            {"name": "indimmediate", "type_oid": 16, "type_name": "bool"},
            {"name": "indisclustered", "type_oid": 16, "type_name": "bool"},
            {"name": "indisvalid", "type_oid": 16, "type_name": "bool"},
            {"name": "indcheckxmin", "type_oid": 16, "type_name": "bool"},
            {"name": "indisready", "type_oid": 16, "type_name": "bool"},
            {"name": "indislive", "type_oid": 16, "type_name": "bool"},
            {"name": "indisreplident", "type_oid": 16, "type_name": "bool"},
            {"name": "indkey", "type_oid": 22, "type_name": "int2vector"},
            {"name": "indcollation", "type_oid": 30, "type_name": "oidvector"},
            {"name": "indclass", "type_oid": 30, "type_name": "oidvector"},
            {"name": "indoption", "type_oid": 22, "type_name": "int2vector"},
            {"name": "indexprs", "type_oid": 194, "type_name": "pg_node_tree"},
            {"name": "indpred", "type_oid": 194, "type_name": "pg_node_tree"},
        ]

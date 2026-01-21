"""
pg_constraint Catalog Emulation

Emulates PostgreSQL pg_catalog.pg_constraint system table.
Provides constraint metadata (PK, FK, UNIQUE, CHECK) for Prisma introspection.

contype values:
- 'c' = check constraint
- 'f' = foreign key
- 'p' = primary key
- 'u' = unique
- 't' = trigger constraint
- 'x' = exclusion constraint
"""

from dataclasses import dataclass, field
from typing import Any, Literal

from iris_pgwire.schema_mapper import IRIS_SCHEMA
from .oid_generator import OIDGenerator

ConstraintType = Literal["c", "f", "p", "u", "t", "x"]


@dataclass
class PgConstraint:
    """
    pg_catalog.pg_constraint row.

    PostgreSQL Documentation:
    https://www.postgresql.org/docs/current/catalog-pg-constraint.html
    """

    oid: int  # Constraint OID
    conname: str  # Constraint name
    connamespace: int  # Namespace OID
    contype: ConstraintType  # Constraint type
    condeferrable: bool  # Is deferrable
    condeferred: bool  # Is deferred by default
    convalidated: bool  # Has been validated
    conrelid: int  # Table OID (0 if not table constraint)
    contypid: int  # Domain OID (0 if not domain constraint)
    conindid: int  # Index OID for UNIQUE/PK (0 otherwise)
    conparentid: int  # Parent constraint OID (partitioning)
    confrelid: int  # Referenced table OID (FK only)
    confupdtype: str  # FK update action
    confdeltype: str  # FK delete action
    confmatchtype: str  # FK match type
    conislocal: bool  # Locally defined
    coninhcount: int  # Inheritance count
    connoinherit: bool  # No inherit
    conkey: list[int] = field(default_factory=list)  # Constrained columns
    confkey: list[int] = field(default_factory=list)  # Referenced columns (FK only)
    conpfeqop: list[int] = field(default_factory=list)  # PK=FK equality operators
    conppeqop: list[int] = field(default_factory=list)  # PK=PK equality operators
    conffeqop: list[int] = field(default_factory=list)  # FK=FK equality operators
    conexclop: list[int] = field(default_factory=list)  # Exclusion operators
    conbin: str | None = None  # CHECK expression (internal)


class PgConstraintEmulator:
    """
    Emulate pg_constraint from IRIS metadata.

    Query sources:
    - INFORMATION_SCHEMA.TABLE_CONSTRAINTS
    - INFORMATION_SCHEMA.KEY_COLUMN_USAGE
    - INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS
    """

    def __init__(self, oid_generator: OIDGenerator):
        """
        Initialize pg_constraint emulator.

        Args:
            oid_generator: OIDGenerator for deterministic OIDs
        """
        self.oid_gen = oid_generator
        self._constraints: list[PgConstraint] = []
        self._by_table: dict[int, list[PgConstraint]] = {}
        self._by_referenced_table: dict[int, list[PgConstraint]] = {}

    def from_iris_constraint(
        self,
        table_name: str,
        constraint_name: str,
        constraint_type: str,
        column_positions: list[int],
        ref_table_name: str | None = None,
        ref_column_positions: list[int] | None = None,
        schema: str = IRIS_SCHEMA,
    ) -> PgConstraint:
        """
        Convert IRIS constraint metadata to pg_constraint row.

        Args:
            table_name: Table name
            constraint_name: Constraint name
            constraint_type: 'PRIMARY KEY', 'FOREIGN KEY', 'UNIQUE', 'CHECK'
            column_positions: Column positions (attnum values)
            ref_table_name: Referenced table (FK only)
            ref_column_positions: Referenced column positions (FK only)
            schema: IRIS schema name (e.g., '{IRIS_SCHEMA}')

        Returns:
            PgConstraint instance
        """
        constraint_oid = self.oid_gen.get_constraint_oid(constraint_name, schema)
        table_oid = self.oid_gen.get_table_oid(table_name, schema)
        namespace_oid = self.oid_gen.get_namespace_oid("public")

        # Map constraint type
        contype: ConstraintType = "p"  # Default primary key
        if constraint_type == "FOREIGN KEY":
            contype = "f"
        elif constraint_type == "UNIQUE":
            contype = "u"
        elif constraint_type == "CHECK":
            contype = "c"

        # FK-specific fields
        confrelid = 0
        confkey: list[int] = []
        if contype == "f" and ref_table_name:
            confrelid = self.oid_gen.get_table_oid(ref_table_name, schema)
            confkey = ref_column_positions or []

        return PgConstraint(
            oid=constraint_oid,
            conname=constraint_name.lower(),
            connamespace=namespace_oid,
            contype=contype,
            condeferrable=False,
            condeferred=False,
            convalidated=True,
            conrelid=table_oid,
            contypid=0,
            conindid=0,  # Will be set if backing index exists
            conparentid=0,
            confrelid=confrelid,
            confupdtype="a" if contype == "f" else " ",  # no action
            confdeltype="a" if contype == "f" else " ",  # no action
            confmatchtype="s" if contype == "f" else " ",  # simple
            conislocal=True,
            coninhcount=0,
            connoinherit=True,
            conkey=column_positions,
            confkey=confkey,
            conpfeqop=[],
            conppeqop=[],
            conffeqop=[],
            conexclop=[],
            conbin=None,
        )

    def add_constraint(self, constraint: PgConstraint) -> None:
        """
        Add a constraint to the emulator.

        Args:
            constraint: PgConstraint instance
        """
        self._constraints.append(constraint)

        # Index by table OID
        if constraint.conrelid not in self._by_table:
            self._by_table[constraint.conrelid] = []
        self._by_table[constraint.conrelid].append(constraint)

        # Index by referenced table (for FK)
        if constraint.confrelid != 0:
            if constraint.confrelid not in self._by_referenced_table:
                self._by_referenced_table[constraint.confrelid] = []
            self._by_referenced_table[constraint.confrelid].append(constraint)

    def get_all(self) -> list[PgConstraint]:
        """
        Return all constraints.

        Returns:
            List of PgConstraint objects
        """
        return self._constraints

    def get_all_as_rows(self) -> list[tuple[Any, ...]]:
        """
        Return all constraints as query result rows.

        Returns:
            List of tuples matching pg_constraint column order
        """
        return [self._to_row(c) for c in self._constraints]

    def get_by_table_oid(self, table_oid: int) -> list[PgConstraint]:
        """
        Get all constraints for a table.

        Args:
            table_oid: Table OID

        Returns:
            List of PgConstraint for the table
        """
        return self._by_table.get(table_oid, [])

    def get_by_table_oid_as_rows(self, table_oid: int) -> list[tuple[Any, ...]]:
        """
        Get constraints for a table as rows.

        Args:
            table_oid: Table OID

        Returns:
            List of tuples
        """
        return [self._to_row(c) for c in self.get_by_table_oid(table_oid)]

    def get_by_referenced_table(self, ref_table_oid: int) -> list[PgConstraint]:
        """
        Get FK constraints referencing a table.

        Args:
            ref_table_oid: Referenced table OID

        Returns:
            List of PgConstraint (FKs) referencing the table
        """
        return self._by_referenced_table.get(ref_table_oid, [])

    def _to_row(self, constraint: PgConstraint) -> tuple[Any, ...]:
        """
        Convert PgConstraint to query result row.

        Args:
            constraint: PgConstraint instance

        Returns:
            Tuple of values matching pg_constraint column order
        """
        return (
            constraint.oid,
            constraint.conname,
            constraint.connamespace,
            constraint.contype,
            constraint.condeferrable,
            constraint.condeferred,
            constraint.convalidated,
            constraint.conrelid,
            constraint.contypid,
            constraint.conindid,
            constraint.conparentid,
            constraint.confrelid,
            constraint.confupdtype,
            constraint.confdeltype,
            constraint.confmatchtype,
            constraint.conislocal,
            constraint.coninhcount,
            constraint.connoinherit,
            constraint.conkey,
            constraint.confkey,
            constraint.conpfeqop,
            constraint.conppeqop,
            constraint.conffeqop,
            constraint.conexclop,
            constraint.conbin,
        )

    @staticmethod
    def get_column_definitions() -> list[dict[str, Any]]:
        """
        Get PostgreSQL column definitions for pg_constraint.

        Returns:
            List of column metadata dicts
        """
        return [
            {"name": "oid", "type_oid": 26, "type_name": "oid"},
            {"name": "conname", "type_oid": 19, "type_name": "name"},
            {"name": "connamespace", "type_oid": 26, "type_name": "oid"},
            {"name": "contype", "type_oid": 18, "type_name": "char"},
            {"name": "condeferrable", "type_oid": 16, "type_name": "bool"},
            {"name": "condeferred", "type_oid": 16, "type_name": "bool"},
            {"name": "convalidated", "type_oid": 16, "type_name": "bool"},
            {"name": "conrelid", "type_oid": 26, "type_name": "oid"},
            {"name": "contypid", "type_oid": 26, "type_name": "oid"},
            {"name": "conindid", "type_oid": 26, "type_name": "oid"},
            {"name": "conparentid", "type_oid": 26, "type_name": "oid"},
            {"name": "confrelid", "type_oid": 26, "type_name": "oid"},
            {"name": "confupdtype", "type_oid": 18, "type_name": "char"},
            {"name": "confdeltype", "type_oid": 18, "type_name": "char"},
            {"name": "confmatchtype", "type_oid": 18, "type_name": "char"},
            {"name": "conislocal", "type_oid": 16, "type_name": "bool"},
            {"name": "coninhcount", "type_oid": 23, "type_name": "int4"},
            {"name": "connoinherit", "type_oid": 16, "type_name": "bool"},
            {"name": "conkey", "type_oid": 1005, "type_name": "int2[]"},
            {"name": "confkey", "type_oid": 1005, "type_name": "int2[]"},
            {"name": "conpfeqop", "type_oid": 1028, "type_name": "oid[]"},
            {"name": "conppeqop", "type_oid": 1028, "type_name": "oid[]"},
            {"name": "conffeqop", "type_oid": 1028, "type_name": "oid[]"},
            {"name": "conexclop", "type_oid": 1028, "type_name": "oid[]"},
            {"name": "conbin", "type_oid": 194, "type_name": "pg_node_tree"},
        ]

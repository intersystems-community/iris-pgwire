"""
pg_attrdef Catalog Emulation

Emulates PostgreSQL pg_catalog.pg_attrdef system table.
Provides column default value metadata for Prisma introspection.

PostgreSQL Documentation:
https://www.postgresql.org/docs/current/catalog-pg-attrdef.html
"""

from dataclasses import dataclass
from typing import Any

from iris_pgwire.schema_mapper import IRIS_SCHEMA
from .oid_generator import OIDGenerator


@dataclass
class PgAttrdef:
    """
    pg_catalog.pg_attrdef row.

    Stores default values for columns.
    """

    oid: int  # Row OID
    adrelid: int  # Table OID (pg_class.oid)
    adnum: int  # Column number (pg_attribute.attnum)
    adbin: str  # Default expression (pg_node_tree format, but we use text)


class PgAttrdefEmulator:
    """
    Emulate pg_attrdef from IRIS metadata.

    Query source: INFORMATION_SCHEMA.COLUMNS (COLUMN_DEFAULT)
    """

    def __init__(self, oid_generator: OIDGenerator):
        """
        Initialize pg_attrdef emulator.

        Args:
            oid_generator: OIDGenerator for deterministic OIDs
        """
        self.oid_gen = oid_generator
        self._defaults: list[PgAttrdef] = []
        self._by_table: dict[int, list[PgAttrdef]] = {}
        self._by_column: dict[tuple[int, int], PgAttrdef] = {}

    def from_iris_default(
        self,
        table_name: str,
        column_name: str,
        column_position: int,
        default_value: str,
        schema: str = IRIS_SCHEMA,
    ) -> PgAttrdef:
        """
        Convert IRIS column default to pg_attrdef row.

        Args:
            table_name: Table name
            column_name: Column name
            column_position: Column position (attnum, 1-based)
            default_value: Default value expression from IRIS
            schema: IRIS schema name (e.g., '{IRIS_SCHEMA}')

        Returns:
            PgAttrdef instance
        """
        table_oid = self.oid_gen.get_table_oid(table_name, schema)
        # Generate unique OID for this default
        default_key = f"{schema}:{table_name}:{column_name}:default"
        default_oid = self.oid_gen.get_oid("default", default_key, schema)

        # Translate IRIS default to PostgreSQL expression
        adbin = self._translate_default(default_value, schema, table_name, column_name)

        return PgAttrdef(
            oid=default_oid,
            adrelid=table_oid,
            adnum=column_position,
            adbin=adbin,
        )

    def _translate_default(
        self,
        iris_default: str,
        schema: str,
        table_name: str,
        column_name: str,
    ) -> str:
        """
        Translate IRIS default expression to PostgreSQL format.

        Args:
            iris_default: IRIS default value
            schema: Schema name (for sequence naming)
            table_name: Table name (for sequence naming)
            column_name: Column name (for sequence naming)

        Returns:
            PostgreSQL-formatted default expression
        """
        if iris_default is None:
            return ""

        upper_default = iris_default.upper().strip()

        # Handle IRIS auto-increment ($IDENTITY)
        if "$IDENTITY" in upper_default or "IDENTITY" in upper_default:
            # Generate PostgreSQL nextval() expression
            seq_name = f"{table_name}_{column_name}_seq"
            return f"nextval('{seq_name}'::regclass)"

        # Handle timestamp defaults
        if any(
            ts in upper_default for ts in ["CURRENT_TIMESTAMP", "NOW()", "GETDATE()", "SYSDATE"]
        ):
            return "CURRENT_TIMESTAMP"

        if "CURRENT_DATE" in upper_default:
            return "CURRENT_DATE"

        if "CURRENT_TIME" in upper_default:
            return "CURRENT_TIME"

        # Handle NULL default
        if upper_default == "NULL":
            return "NULL"

        # String literals - ensure proper quoting
        if iris_default.startswith("'") and iris_default.endswith("'"):
            return iris_default

        # Numeric literals - check before booleans since 0/1 are valid numbers
        try:
            float(iris_default)
            return iris_default
        except ValueError:
            pass

        # Handle boolean defaults (only quoted strings, not bare 0/1)
        if upper_default in ("TRUE", "'1'"):
            return "true"
        if upper_default in ("FALSE", "'0'"):
            return "false"

        # Default: return as-is (may be function call or expression)
        return iris_default

    def add_default(self, attrdef: PgAttrdef) -> None:
        """
        Add a default to the emulator.

        Args:
            attrdef: PgAttrdef instance
        """
        self._defaults.append(attrdef)

        # Index by table OID
        if attrdef.adrelid not in self._by_table:
            self._by_table[attrdef.adrelid] = []
        self._by_table[attrdef.adrelid].append(attrdef)

        # Index by (table_oid, column_num)
        key = (attrdef.adrelid, attrdef.adnum)
        self._by_column[key] = attrdef

    def get_all(self) -> list[PgAttrdef]:
        """
        Return all defaults.

        Returns:
            List of PgAttrdef objects
        """
        return self._defaults

    def get_all_as_rows(self) -> list[tuple[Any, ...]]:
        """
        Return all defaults as query result rows.

        Returns:
            List of tuples matching pg_attrdef column order
        """
        return [self._to_row(d) for d in self._defaults]

    def get_by_table_oid(self, table_oid: int) -> list[PgAttrdef]:
        """
        Get all defaults for a table.

        Args:
            table_oid: Table OID

        Returns:
            List of PgAttrdef for the table
        """
        return self._by_table.get(table_oid, [])

    def get_by_table_oid_as_rows(self, table_oid: int) -> list[tuple[Any, ...]]:
        """
        Get defaults for a table as rows.

        Args:
            table_oid: Table OID

        Returns:
            List of tuples
        """
        return [self._to_row(d) for d in self.get_by_table_oid(table_oid)]

    def get_by_column(self, table_oid: int, column_num: int) -> PgAttrdef | None:
        """
        Get default for a specific column.

        Args:
            table_oid: Table OID
            column_num: Column number (attnum)

        Returns:
            PgAttrdef if exists, None otherwise
        """
        return self._by_column.get((table_oid, column_num))

    def _to_row(self, attrdef: PgAttrdef) -> tuple[Any, ...]:
        """
        Convert PgAttrdef to query result row.

        Args:
            attrdef: PgAttrdef instance

        Returns:
            Tuple of values matching pg_attrdef column order
        """
        return (
            attrdef.oid,
            attrdef.adrelid,
            attrdef.adnum,
            attrdef.adbin,
        )

    @staticmethod
    def get_column_definitions() -> list[dict[str, Any]]:
        """
        Get PostgreSQL column definitions for pg_attrdef.

        Returns:
            List of column metadata dicts
        """
        return [
            {"name": "oid", "type_oid": 26, "type_name": "oid"},
            {"name": "adrelid", "type_oid": 26, "type_name": "oid"},
            {"name": "adnum", "type_oid": 21, "type_name": "int2"},
            {"name": "adbin", "type_oid": 194, "type_name": "pg_node_tree"},
        ]

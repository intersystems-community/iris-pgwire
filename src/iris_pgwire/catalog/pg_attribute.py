"""
pg_attribute Catalog Emulation

Emulates PostgreSQL pg_catalog.pg_attribute system table.
Provides column metadata for Prisma introspection.

Key fields:
- attrelid: Table OID
- attname: Column name
- atttypid: Type OID
- attnum: Column position (1-indexed)
- attnotnull: NOT NULL constraint
- atthasdef: Has default value
- atttypmod: Type modifier (e.g., VARCHAR length)
"""

from dataclasses import dataclass
from typing import Any

from iris_pgwire.schema_mapper import IRIS_SCHEMA
from .oid_generator import OIDGenerator


@dataclass
class PgAttribute:
    """
    pg_catalog.pg_attribute row.

    PostgreSQL Documentation:
    https://www.postgresql.org/docs/current/catalog-pg-attribute.html
    """

    attrelid: int  # Table OID (pg_class.oid)
    attname: str  # Column name
    atttypid: int  # Data type OID (pg_type.oid)
    attstattarget: int  # Statistics target (default -1)
    attlen: int  # Type length (-1 for variable length)
    attnum: int  # Column number (1-indexed for user columns)
    attndims: int  # Array dimensions (0 if not array)
    attcacheoff: int  # Cache offset (-1)
    atttypmod: int  # Type modifier (e.g., varchar(255) -> 255+4)
    attbyval: bool  # Passed by value
    attstorage: str  # Storage strategy ('p', 'e', 'm', 'x')
    attalign: str  # Alignment ('c', 's', 'i', 'd')
    attnotnull: bool  # NOT NULL constraint
    atthasdef: bool  # Has default value
    atthasmissing: bool  # Has missing value
    attidentity: str  # Identity column type ('' = not identity)
    attgenerated: str  # Generated column type ('' = not generated)
    attisdropped: bool  # Column is dropped
    attislocal: bool  # Locally defined (not inherited)
    attinhcount: int  # Inheritance count
    attcollation: int  # Collation OID
    attacl: str | None  # Column privileges
    attoptions: str | None  # Attribute options
    attfdwoptions: str | None  # FDW options
    attmissingval: str | None  # Missing value


class PgAttributeEmulator:
    """
    Emulate pg_attribute from IRIS INFORMATION_SCHEMA.COLUMNS.

    Query source:
    SELECT COLUMN_NAME, DATA_TYPE, ORDINAL_POSITION, IS_NULLABLE, COLUMN_DEFAULT
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = '{IRIS_SCHEMA}' AND TABLE_NAME = ?
    ORDER BY ORDINAL_POSITION
    """

    # IRIS type to PostgreSQL type OID mapping
    TYPE_OID_MAP = {
        "BIGINT": 20,  # int8
        "BIT": 16,  # bool
        "CHAR": 1042,  # bpchar
        "DATE": 1082,  # date
        "DECIMAL": 1700,  # numeric
        "DOUBLE": 701,  # float8
        "INTEGER": 23,  # int4
        "INT": 23,  # int4 (alias)
        "NUMERIC": 1700,  # numeric
        "SMALLINT": 21,  # int2
        "TIME": 1083,  # time
        "TIMESTAMP": 1114,  # timestamp
        "TINYINT": 21,  # int2
        "VARBINARY": 17,  # bytea
        "VARCHAR": 1043,  # varchar
        "LONGVARCHAR": 25,  # text
        "LONGVARBINARY": 17,  # bytea
        "TEXT": 25,  # text
        "BOOLEAN": 16,  # bool
        "REAL": 700,  # float4
        "FLOAT": 701,  # float8
    }

    # Type length mapping
    TYPE_LEN_MAP = {
        "BIGINT": 8,
        "BIT": 1,
        "BOOLEAN": 1,
        "DATE": 4,
        "DOUBLE": 8,
        "FLOAT": 8,
        "INTEGER": 4,
        "INT": 4,
        "REAL": 4,
        "SMALLINT": 2,
        "TIME": 8,
        "TIMESTAMP": 8,
        "TINYINT": 2,
    }

    def __init__(self, oid_generator: OIDGenerator):
        """
        Initialize pg_attribute emulator.

        Args:
            oid_generator: OIDGenerator for deterministic OIDs
        """
        self.oid_gen = oid_generator
        self._attributes: list[PgAttribute] = []
        self._by_table: dict[int, list[PgAttribute]] = {}

    def from_iris_column(
        self,
        table_name: str,
        column_name: str,
        data_type: str,
        ordinal_position: int,
        is_nullable: str,
        column_default: str | None,
        schema: str = IRIS_SCHEMA,
    ) -> PgAttribute:
        """
        Convert IRIS column metadata to pg_attribute row.

        Args:
            table_name: Table name
            column_name: Column name
            data_type: IRIS data type (e.g., 'VARCHAR(255)')
            ordinal_position: Column position (1-indexed)
            is_nullable: 'YES' or 'NO'
            column_default: Default value expression or None
            schema: IRIS schema name (e.g., '{IRIS_SCHEMA}')

        Returns:
            PgAttribute instance
        """
        table_oid = self.oid_gen.get_table_oid(table_name, schema)

        # Parse data type (handle VARCHAR(255) etc.)
        base_type = data_type.split("(")[0].upper()
        type_oid = self.TYPE_OID_MAP.get(base_type, 25)  # Default to text
        type_len = self.TYPE_LEN_MAP.get(base_type, -1)  # Default to variable

        # Calculate type modifier for VARCHAR(n), CHAR(n)
        atttypmod = -1
        if "(" in data_type:
            try:
                size_str = data_type.split("(")[1].rstrip(")").split(",")[0]
                size = int(size_str)
                if base_type in ("VARCHAR", "CHAR"):
                    atttypmod = size + 4  # PostgreSQL adds 4 to varchar length
            except (ValueError, IndexError):
                pass

        return PgAttribute(
            attrelid=table_oid,
            attname=column_name.lower(),
            atttypid=type_oid,
            attstattarget=-1,
            attlen=type_len,
            attnum=ordinal_position,
            attndims=0,
            attcacheoff=-1,
            atttypmod=atttypmod,
            attbyval=type_len in (1, 2, 4, 8) and type_len > 0,
            attstorage="p" if type_len > 0 else "x",
            attalign="d" if type_len == 8 else "i",
            attnotnull=(is_nullable.upper() == "NO"),
            atthasdef=(column_default is not None),
            atthasmissing=False,
            attidentity="",
            attgenerated="",
            attisdropped=False,
            attislocal=True,
            attinhcount=0,
            attcollation=0,
            attacl=None,
            attoptions=None,
            attfdwoptions=None,
            attmissingval=None,
        )

    def add_attribute(self, attr: PgAttribute) -> None:
        """
        Add an attribute to the emulator.

        Args:
            attr: PgAttribute instance
        """
        self._attributes.append(attr)

        # Index by table OID
        if attr.attrelid not in self._by_table:
            self._by_table[attr.attrelid] = []
        self._by_table[attr.attrelid].append(attr)

    def get_all(self) -> list[PgAttribute]:
        """
        Return all attributes.

        Returns:
            List of PgAttribute objects
        """
        return self._attributes

    def get_all_as_rows(self) -> list[tuple[Any, ...]]:
        """
        Return all attributes as query result rows.

        Returns:
            List of tuples matching pg_attribute column order
        """
        return [self._to_row(a) for a in self._attributes]

    def get_by_table_oid(self, table_oid: int) -> list[PgAttribute]:
        """
        Get all attributes for a table.

        Args:
            table_oid: Table OID

        Returns:
            List of PgAttribute for the table, ordered by attnum
        """
        attrs = self._by_table.get(table_oid, [])
        return sorted(attrs, key=lambda a: a.attnum)

    def get_by_table_oid_as_rows(self, table_oid: int) -> list[tuple[Any, ...]]:
        """
        Get attributes for a table as rows.

        Args:
            table_oid: Table OID

        Returns:
            List of tuples
        """
        return [self._to_row(a) for a in self.get_by_table_oid(table_oid)]

    def _to_row(self, attr: PgAttribute) -> tuple[Any, ...]:
        """
        Convert PgAttribute to query result row.

        Args:
            attr: PgAttribute instance

        Returns:
            Tuple of values matching pg_attribute column order
        """
        return (
            attr.attrelid,
            attr.attname,
            attr.atttypid,
            attr.attstattarget,
            attr.attlen,
            attr.attnum,
            attr.attndims,
            attr.attcacheoff,
            attr.atttypmod,
            attr.attbyval,
            attr.attstorage,
            attr.attalign,
            attr.attnotnull,
            attr.atthasdef,
            attr.atthasmissing,
            attr.attidentity,
            attr.attgenerated,
            attr.attisdropped,
            attr.attislocal,
            attr.attinhcount,
            attr.attcollation,
            attr.attacl,
            attr.attoptions,
            attr.attfdwoptions,
            attr.attmissingval,
        )

    @staticmethod
    def get_column_definitions() -> list[dict[str, Any]]:
        """
        Get PostgreSQL column definitions for pg_attribute.

        Returns:
            List of column metadata dicts
        """
        return [
            {"name": "attrelid", "type_oid": 26, "type_name": "oid"},
            {"name": "attname", "type_oid": 19, "type_name": "name"},
            {"name": "atttypid", "type_oid": 26, "type_name": "oid"},
            {"name": "attstattarget", "type_oid": 23, "type_name": "int4"},
            {"name": "attlen", "type_oid": 21, "type_name": "int2"},
            {"name": "attnum", "type_oid": 21, "type_name": "int2"},
            {"name": "attndims", "type_oid": 23, "type_name": "int4"},
            {"name": "attcacheoff", "type_oid": 23, "type_name": "int4"},
            {"name": "atttypmod", "type_oid": 23, "type_name": "int4"},
            {"name": "attbyval", "type_oid": 16, "type_name": "bool"},
            {"name": "attstorage", "type_oid": 18, "type_name": "char"},
            {"name": "attalign", "type_oid": 18, "type_name": "char"},
            {"name": "attnotnull", "type_oid": 16, "type_name": "bool"},
            {"name": "atthasdef", "type_oid": 16, "type_name": "bool"},
            {"name": "atthasmissing", "type_oid": 16, "type_name": "bool"},
            {"name": "attidentity", "type_oid": 18, "type_name": "char"},
            {"name": "attgenerated", "type_oid": 18, "type_name": "char"},
            {"name": "attisdropped", "type_oid": 16, "type_name": "bool"},
            {"name": "attislocal", "type_oid": 16, "type_name": "bool"},
            {"name": "attinhcount", "type_oid": 23, "type_name": "int4"},
            {"name": "attcollation", "type_oid": 26, "type_name": "oid"},
            {"name": "attacl", "type_oid": 1034, "type_name": "aclitem[]"},
            {"name": "attoptions", "type_oid": 1009, "type_name": "text[]"},
            {"name": "attfdwoptions", "type_oid": 1009, "type_name": "text[]"},
            {"name": "attmissingval", "type_oid": 2277, "type_name": "anyarray"},
        ]

"""
pg_type Catalog Emulation

Emulates PostgreSQL pg_catalog.pg_type system table.
Required for Drizzle ORM and other clients that introspect data types.
"""

from dataclasses import dataclass
from typing import Any
from .oid_generator import OIDGenerator


@dataclass
class PgType:
    """
    pg_catalog.pg_type row.

    PostgreSQL Documentation:
    https://www.postgresql.org/docs/current/catalog-pg-type.html
    """

    oid: int  # Type OID
    typname: str  # Type name
    typnamespace: int  # Namespace OID (pg_catalog = 11)
    typowner: int  # Owner OID (10 = postgres)
    typlen: int  # Internal storage size
    typbyval: bool  # Passed by value?
    typtype: str  # Type category (b=base, c=composite, etc.)
    typcategory: str  # Category code (A=array, B=boolean, N=numeric, etc.)
    typispreferred: bool  # Preferred type?
    typisdefined: bool  # Type is defined?
    typdelim: str  # Delimiter
    typrelid: int  # Relation OID (for composite types)
    typelem: int  # Element type
    typarray: int  # Array type OID
    typinput: str  # Input function
    typoutput: str  # Output function
    typnotnull: bool  # Not null?


class PgTypeEmulator:
    """
    Emulate pg_type with standard PostgreSQL types.
    """

    # Standard PostgreSQL types mapping for IRIS
    # (typname, oid, typlen, typcategory)
    TYPES = [
        ("bool", 16, 1, "B"),
        ("bytea", 17, -1, "U"),
        ("char", 18, 1, "S"),
        ("name", 19, 64, "S"),
        ("int8", 20, 8, "N"),
        ("int2", 21, 2, "N"),
        ("int4", 23, 4, "N"),
        ("text", 25, -1, "S"),
        ("oid", 26, 4, "N"),
        ("float4", 700, 4, "N"),
        ("float8", 701, 8, "N"),
        ("bpchar", 1042, -1, "S"),
        ("varchar", 1043, -1, "S"),
        ("date", 1082, 4, "D"),
        ("time", 1083, 8, "D"),
        ("timestamp", 1114, 8, "D"),
        ("timestamptz", 1184, 8, "D"),
        ("bit", 1560, -1, "V"),
        ("numeric", 1700, -1, "N"),
        ("uuid", 2950, 16, "U"),
        ("vector", 16388, -1, "U"),  # pgvector support
    ]

    def __init__(self, oid_generator: OIDGenerator):
        self.oid_gen = oid_generator
        self._types: list[PgType] = []

        pg_catalog_oid = 11  # standard OID for pg_catalog

        for name, oid, size, category in self.TYPES:
            self._types.append(
                PgType(
                    oid=oid,
                    typname=name,
                    typnamespace=pg_catalog_oid,
                    typowner=10,
                    typlen=size,
                    typbyval=True if size > 0 and size <= 8 else False,
                    typtype="b",
                    typcategory=category,
                    typispreferred=False,
                    typisdefined=True,
                    typdelim=",",
                    typrelid=0,
                    typelem=0,
                    typarray=0,
                    typinput=f"{name}in",
                    typoutput=f"{name}out",
                    typnotnull=False,
                )
            )

    def get_all(self) -> list[PgType]:
        return self._types

    def get_all_as_rows(self) -> list[tuple[Any, ...]]:
        return [self._to_row(t) for t in self._types]

    def get_by_name(self, name: str) -> PgType | None:
        for t in self._types:
            if t.typname == name:
                return t
        return None

    def get_by_oid(self, oid: int) -> PgType | None:
        for t in self._types:
            if t.oid == oid:
                return t
        return None

    def get_oid_for_iris_type(self, iris_type: str) -> int:
        """
        Map IRIS data type to PostgreSQL OID.
        If unknown, returns default 'text' OID (25).
        """
        # Simple mapping for common IRIS types
        mapping = {
            "BOOLEAN": 16,
            "INTEGER": 23,
            "BIGINT": 20,
            "VARCHAR": 1043,
            "DOUBLE": 701,
            "TIMESTAMP": 1114,
            "DATE": 1082,
            "VECTOR": 16388,
        }
        return mapping.get(iris_type.upper(), 25)  # Default to text (OID 25)

    def _to_row(self, t: PgType) -> tuple[Any, ...]:
        return (
            t.oid,
            t.typname,
            t.typnamespace,
            t.typowner,
            t.typlen,
            t.typbyval,
            t.typtype,
            t.typcategory,
            t.typispreferred,
            t.typisdefined,
            t.typdelim,
            t.typrelid,
            t.typelem,
            t.typarray,
            t.typinput,
            t.typoutput,
            t.typnotnull,
        )

    @staticmethod
    def get_column_definitions() -> list[dict[str, Any]]:
        return [
            {"name": "oid", "type_oid": 26, "type_name": "oid"},
            {"name": "typname", "type_oid": 19, "type_name": "name"},
            {"name": "typnamespace", "type_oid": 26, "type_name": "oid"},
            {"name": "typowner", "type_oid": 26, "type_name": "oid"},
            {"name": "typlen", "type_oid": 21, "type_name": "int2"},
            {"name": "typbyval", "type_oid": 16, "type_name": "bool"},
            {"name": "typtype", "type_oid": 18, "type_name": "char"},
            {"name": "typcategory", "type_oid": 18, "type_name": "char"},
            {"name": "typispreferred", "type_oid": 16, "type_name": "bool"},
            {"name": "typisdefined", "type_oid": 16, "type_name": "bool"},
            {"name": "typdelim", "type_oid": 18, "type_name": "char"},
            {"name": "typrelid", "type_oid": 26, "type_name": "oid"},
            {"name": "typelem", "type_oid": 26, "type_name": "oid"},
            {"name": "typarray", "type_oid": 26, "type_name": "oid"},
            {"name": "typinput", "type_oid": 26, "type_name": "regproc"},
            {"name": "typoutput", "type_oid": 26, "type_name": "regproc"},
            {"name": "typnotnull", "type_oid": 16, "type_name": "bool"},
        ]

"""
pg_namespace Catalog Emulation

Emulates PostgreSQL pg_catalog.pg_namespace system table.
Provides schema/namespace metadata for Prisma introspection.

Standard PostgreSQL namespace OIDs:
- pg_catalog: 11
- public: 2200
- information_schema: 11323
"""

from iris_pgwire.schema_mapper import IRIS_SCHEMA
from dataclasses import dataclass
from typing import Any


@dataclass
class PgNamespace:
    """
    pg_catalog.pg_namespace row.

    PostgreSQL Documentation:
    https://www.postgresql.org/docs/current/catalog-pg-namespace.html
    """

    oid: int  # Namespace OID
    nspname: str  # Namespace name (e.g., 'public')
    nspowner: int  # Owner OID (use 10 for postgres superuser)
    nspacl: str | None  # Access privileges (NULL = default)


class PgNamespaceEmulator:
    """
    Emulate pg_namespace from IRIS metadata.

    Maps:
    - 'public' -> {IRIS_SCHEMA} (configurable via schema_mapper)
    - 'pg_catalog' -> system types namespace
    - 'information_schema' -> SQL standard schema

    Since IRIS typically uses a single user schema ({IRIS_SCHEMA}),
    we provide static namespaces matching PostgreSQL expectations.
    """

    # Standard PostgreSQL namespaces with well-known OIDs
    STATIC_NAMESPACES = [
        PgNamespace(oid=11, nspname="pg_catalog", nspowner=10, nspacl=None),
        PgNamespace(oid=2200, nspname="public", nspowner=10, nspacl=None),
        PgNamespace(oid=11323, nspname="information_schema", nspowner=10, nspacl=None),
    ]

    def __init__(self):
        """Initialize pg_namespace emulator."""
        self._namespaces = list(self.STATIC_NAMESPACES)

    def get_all(self) -> list[PgNamespace]:
        """
        Return all namespaces.

        Returns:
            List of PgNamespace objects
        """
        return self._namespaces

    def get_all_as_rows(self) -> list[tuple[Any, ...]]:
        """
        Return all namespaces as query result rows.

        Returns:
            List of tuples: (oid, nspname, nspowner, nspacl)
        """
        return [(ns.oid, ns.nspname, ns.nspowner, ns.nspacl) for ns in self._namespaces]

    def get_by_name(self, name: str) -> PgNamespace | None:
        """
        Get namespace by name.

        Args:
            name: Namespace name (e.g., 'public')

        Returns:
            PgNamespace if found, None otherwise
        """
        for ns in self._namespaces:
            if ns.nspname == name:
                return ns
        return None

    def get_by_oid(self, oid: int) -> PgNamespace | None:
        """
        Get namespace by OID.

        Args:
            oid: Namespace OID

        Returns:
            PgNamespace if found, None otherwise
        """
        for ns in self._namespaces:
            if ns.oid == oid:
                return ns
        return None

    def add_namespace(self, namespace: PgNamespace) -> None:
        """
        Add a custom namespace.

        Args:
            namespace: PgNamespace to add
        """
        # Check for duplicate
        if not self.get_by_oid(namespace.oid) and not self.get_by_name(namespace.nspname):
            self._namespaces.append(namespace)

    @staticmethod
    def get_column_definitions() -> list[dict[str, Any]]:
        """
        Get PostgreSQL column definitions for pg_namespace.

        Returns:
            List of column metadata dicts
        """
        return [
            {"name": "oid", "type_oid": 26, "type_name": "oid"},
            {"name": "nspname", "type_oid": 19, "type_name": "name"},
            {"name": "nspowner", "type_oid": 26, "type_name": "oid"},
            {"name": "nspacl", "type_oid": 1034, "type_name": "aclitem[]"},
        ]

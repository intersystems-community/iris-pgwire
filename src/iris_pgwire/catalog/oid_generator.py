"""
OID Generator for PostgreSQL Catalog Emulation

Generates stable, deterministic Object Identifiers (OIDs) for IRIS database objects
to satisfy PostgreSQL catalog requirements. Uses SHA-256 hashing for determinism.

OID Ranges:
- System OIDs: 0-16383 (reserved for PostgreSQL system objects)
- User OIDs: 16384-4294967295 (generated for IRIS objects)

Well-known namespace OIDs:
- pg_catalog: 11
- public: 2200
- information_schema: 11323
"""

from iris_pgwire.schema_mapper import IRIS_SCHEMA
import hashlib
from dataclasses import dataclass
from typing import Literal

ObjectType = Literal["namespace", "table", "column", "constraint", "index", "type", "default"]


@dataclass
class ObjectIdentity:
    """Identity tuple for OID generation."""

    object_name: str  # Fully qualified name (e.g., 'users' or 'users.id')
    namespace: str = IRIS_SCHEMA  # Schema name (e.g., '{IRIS_SCHEMA}')
    object_type: ObjectType = "table"  # Object category

    @property
    def identity_string(self) -> str:
        """Return the canonical identity string for hashing."""
        return f"{self.namespace}:{self.object_type}:{self.object_name}"


class OIDGenerator:
    """
    Generate stable, deterministic OIDs for IRIS database objects.

    PostgreSQL reserves OIDs 0-16383 for system use.
    User objects should use OIDs >= 16384.

    Usage:
        gen = OIDGenerator()
        table_oid = gen.get_oid('{IRIS_SCHEMA}', 'table', 'users')
        column_oid = gen.get_oid('{IRIS_SCHEMA}', 'column', 'users.id')
    """

    # Well-known namespace OIDs (match PostgreSQL)
    WELL_KNOWN_NAMESPACES = {
        "pg_catalog": 11,
        "public": 2200,
        "information_schema": 11323,
    }

    # Reserved OID ranges
    SYSTEM_OID_MAX = 16383
    USER_OID_START = 16384

    def __init__(self):
        """Initialize OID generator with empty cache."""
        self._cache: dict[str, int] = {}

    def get_oid(self, object_type: str, object_name: str, namespace: str = IRIS_SCHEMA) -> int:
        """
        Generate deterministic OID for an object.

        Args:
            object_type: Object category ('table', 'column', 'constraint', etc.)
            object_name: Object name (e.g., 'users' or 'users.id' for columns)
            namespace: Schema name (e.g., '{IRIS_SCHEMA}')

        Returns:
            Deterministic OID in user range (>= 16384)
        """
        # Normalize inputs to lowercase for case-insensitive matching
        key = f"{namespace.lower()}:{object_type.lower()}:{object_name.lower()}"

        if key not in self._cache:
            self._cache[key] = self._generate_oid(key)

        return self._cache[key]

    def get_oid_from_identity(self, identity: ObjectIdentity) -> int:
        """
        Generate OID from ObjectIdentity dataclass.

        Args:
            identity: ObjectIdentity instance

        Returns:
            Deterministic OID
        """
        return self.get_oid(identity.object_type, identity.object_name, identity.namespace)

    def _generate_oid(self, identity_string: str) -> int:
        """
        Generate deterministic OID from identity string using SHA-256.

        Args:
            identity_string: Canonical identity string

        Returns:
            32-bit OID in user range
        """
        # SHA-256 hash of identity
        hash_bytes = hashlib.sha256(identity_string.encode()).digest()

        # Extract 32-bit value from first 4 bytes
        raw_oid = int.from_bytes(hash_bytes[:4], byteorder="big")

        # Ensure OID is in valid user range
        if raw_oid < self.USER_OID_START:
            raw_oid += self.USER_OID_START

        return raw_oid

    def get_namespace_oid(self, namespace: str) -> int:
        """
        Get OID for a namespace/schema.

        Well-known namespaces return standard PostgreSQL OIDs:
        - pg_catalog: 11
        - public: 2200
        - information_schema: 11323

        Other namespaces get generated OIDs.

        Args:
            namespace: Namespace name

        Returns:
            Namespace OID
        """
        ns_lower = namespace.lower()
        if ns_lower in self.WELL_KNOWN_NAMESPACES:
            return self.WELL_KNOWN_NAMESPACES[ns_lower]

        # Generate OID for custom namespace
        return self.get_oid("namespace", namespace, "")

    def get_table_oid(self, table_name: str, schema: str = IRIS_SCHEMA) -> int:
        """
        Convenience method to get OID for a table.

        Args:
            table_name: Table name (e.g., 'users')
            schema: Schema name (e.g., '{IRIS_SCHEMA}')

        Returns:
            Table OID
        """
        return self.get_oid("table", table_name, schema)

    def get_column_oid(self, table_name: str, column_name: str, schema: str = IRIS_SCHEMA) -> int:
        """
        Convenience method to get OID for a column.

        Args:
            table_name: Table name
            column_name: Column name
            schema: Schema name

        Returns:
            Column OID
        """
        return self.get_oid("column", f"{table_name}.{column_name}", schema)

    def get_constraint_oid(self, constraint_name: str, schema: str = IRIS_SCHEMA) -> int:
        """
        Convenience method to get OID for a constraint.

        Args:
            constraint_name: Constraint name
            schema: Schema name

        Returns:
            Constraint OID
        """
        return self.get_oid("constraint", constraint_name, schema)

    def get_index_oid(self, index_name: str, schema: str = IRIS_SCHEMA) -> int:
        """
        Convenience method to get OID for an index.

        Args:
            index_name: Index name
            schema: Schema name

        Returns:
            Index OID
        """
        return self.get_oid("index", index_name, schema)

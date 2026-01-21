"""
Catalog Router

Routes pg_catalog and information_schema queries to appropriate emulators.
Handles query parsing, array parameter translation, and regclass resolution.
"""

import re
from dataclasses import dataclass, field
from typing import Any

from iris_pgwire.schema_mapper import IRIS_SCHEMA
from .oid_generator import OIDGenerator


@dataclass
class CatalogQueryResult:
    """
    Result from a catalog query execution.

    Matches the format expected by iris_executor.py.
    """

    success: bool
    rows: list[tuple[Any, ...]] = field(default_factory=list)
    columns: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    command_tag: str = "SELECT"
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary format expected by iris_executor."""
        return {
            "success": self.success,
            "rows": self.rows,
            "columns": self.columns,
            "row_count": self.row_count,
            "command_tag": self.command_tag,
            "error": self.error,
        }


class CatalogRouter:
    """
    Route catalog queries to emulators.

    Responsibilities:
    - Detect pg_catalog/information_schema queries
    - Extract referenced catalog tables
    - Translate array parameters (ANY($1) → IN)
    - Resolve regclass casts
    """

    # PostgreSQL catalog tables we emulate
    CATALOG_TABLES = {
        "pg_class",
        "pg_namespace",
        "pg_attribute",
        "pg_constraint",
        "pg_index",
        "pg_attrdef",
        "pg_type",
        "pg_proc",
        "pg_description",
        "pg_depend",
        "pg_am",
        "pg_collation",
        "pg_database",
        "pg_enum",
        "pg_extension",
        "pg_foreign_table",
        "pg_inherits",
        "pg_roles",
        "pg_settings",
        "pg_stat_user_tables",
        "pg_trigger",
        "pg_views",
        "pg_indexes",
    }

    # information_schema tables
    INFO_SCHEMA_TABLES = {
        "tables",
        "columns",
        "table_constraints",
        "key_column_usage",
        "referential_constraints",
        "schemata",
        "views",
    }

    def __init__(self, oid_generator: OIDGenerator | None = None):
        """
        Initialize catalog router.

        Args:
            oid_generator: Optional OIDGenerator for regclass resolution
        """
        self.oid_gen = oid_generator or OIDGenerator()

        # Patterns for query detection
        self._pg_catalog_pattern = re.compile(r"\bpg_catalog\.(\w+)\b", re.IGNORECASE)
        self._pg_table_pattern = re.compile(r"\bpg_(\w+)\b", re.IGNORECASE)
        self._info_schema_pattern = re.compile(r"\binformation_schema\.(\w+)\b", re.IGNORECASE)
        self._any_param_pattern = re.compile(r"=\s*ANY\s*\(\s*\$(\d+)\s*\)", re.IGNORECASE)
        self._regclass_pattern = re.compile(r"'([^']+)'::regclass", re.IGNORECASE)

    def can_handle(self, query: str) -> bool:
        """
        Check if query targets pg_catalog or information_schema.

        Args:
            query: SQL query string

        Returns:
            True if query targets system catalogs
        """
        upper_query = query.upper()

        # Check for explicit pg_catalog prefix
        if "PG_CATALOG." in upper_query:
            return True

        # Check for information_schema prefix
        if "INFORMATION_SCHEMA." in upper_query:
            return True

        # Check for pg_* tables without prefix
        tables = self.extract_catalog_tables(query)
        return len(tables) > 0

    def extract_catalog_tables(self, query: str) -> set[str]:
        """
        Extract catalog table names from query.

        Args:
            query: SQL query string

        Returns:
            Set of catalog table names (lowercase)
        """
        tables: set[str] = set()

        # Find pg_catalog.xxx references
        for match in self._pg_catalog_pattern.finditer(query):
            table_name = match.group(1).lower()
            if table_name in self.CATALOG_TABLES or table_name.startswith("pg_"):
                tables.add(table_name)

        # Find pg_xxx without prefix
        for match in self._pg_table_pattern.finditer(query):
            full_name = f"pg_{match.group(1).lower()}"
            if full_name in self.CATALOG_TABLES:
                tables.add(full_name)

        # Find information_schema tables
        for match in self._info_schema_pattern.finditer(query):
            table_name = match.group(1).lower()
            if table_name in self.INFO_SCHEMA_TABLES:
                tables.add(f"information_schema.{table_name}")

        return tables

    def has_array_param(self, query: str) -> bool:
        """
        Check if query contains ANY($n) array parameter pattern.

        Args:
            query: SQL query string

        Returns:
            True if query contains array parameter
        """
        return bool(self._any_param_pattern.search(query))

    def translate_array_param(self, query: str, values: list[Any], param_index: int = 1) -> str:
        """
        Translate ANY($n) to IN (value1, value2, ...).

        Args:
            query: SQL query with ANY($n) pattern
            values: List of values to expand
            param_index: Parameter index (default 1)

        Returns:
            Query with IN clause instead of ANY
        """
        if not values:
            # Empty array - use impossible condition
            return re.sub(
                rf"=\s*ANY\s*\(\s*\${param_index}\s*\)",
                "IN (NULL)",
                query,
                flags=re.IGNORECASE,
            )

        # Format values for IN clause
        formatted_values = []
        for v in values:
            if isinstance(v, str):
                # Escape single quotes and wrap in quotes
                escaped = v.replace("'", "''")
                formatted_values.append(f"'{escaped}'")
            elif v is None:
                formatted_values.append("NULL")
            else:
                formatted_values.append(str(v))

        in_clause = f"IN ({', '.join(formatted_values)})"

        return re.sub(
            rf"=\s*ANY\s*\(\s*\${param_index}\s*\)",
            in_clause,
            query,
            flags=re.IGNORECASE,
        )

    def has_regclass_cast(self, query: str) -> bool:
        """
        Check if query contains ::regclass cast.

        Args:
            query: SQL query string

        Returns:
            True if query contains regclass cast
        """
        return bool(self._regclass_pattern.search(query))

    def resolve_regclass(self, table_name: str, schema: str = IRIS_SCHEMA) -> int:
        """
        Resolve table name to OID (like ::regclass).

        Args:
            table_name: Table name (may include schema prefix)
            schema: Default schema if not specified in name

        Returns:
            Table OID
        """
        # Handle schema.table format
        if "." in table_name:
            parts = table_name.split(".", 1)
            schema = parts[0]
            table_name = parts[1]

        # Handle quoted identifiers
        table_name = table_name.strip('"')

        return self.oid_gen.get_table_oid(table_name, schema)

    def translate_regclass_casts(self, query: str, schema: str = IRIS_SCHEMA) -> str:
        """
        Replace 'tablename'::regclass with resolved OID.

        Args:
            query: SQL query with regclass casts
            schema: Default schema for resolution

        Returns:
            Query with OIDs instead of regclass casts
        """

        def replace_regclass(match: re.Match) -> str:
            table_name = match.group(1)
            oid = self.resolve_regclass(table_name, schema)
            return str(oid)

        return self._regclass_pattern.sub(replace_regclass, query)

    def get_target_catalog(self, query: str) -> str | None:
        """
        Get primary catalog table targeted by query.

        Args:
            query: SQL query string

        Returns:
            Primary catalog table name or None
        """
        tables = self.extract_catalog_tables(query)
        if not tables:
            return None

        # Priority order for Prisma queries
        priority = [
            "pg_class",
            "pg_attribute",
            "pg_namespace",
            "pg_constraint",
            "pg_index",
            "pg_attrdef",
            "pg_type",
        ]

        for table in priority:
            if table in tables:
                return table

        # Return first found
        return next(iter(tables))

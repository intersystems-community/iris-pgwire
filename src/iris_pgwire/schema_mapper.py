"""
PostgreSQL public schema to IRIS schema mapping.

Maps PostgreSQL 'public' schema references to IRIS schema bidirectionally
to enable ORM introspection tools (Prisma, SQLAlchemy) to discover IRIS tables.

Feature: 030-pg-schema-mapping

Configuration:
    PGWIRE_IRIS_SCHEMA: Environment variable to set the IRIS schema name.
                        Default: 'SQLUser' (standard IRIS user schema)
                        Example: export PGWIRE_IRIS_SCHEMA=MyAppSchema
"""

import os
import re
import time
from typing import Any

import structlog

logger = structlog.get_logger()

# Runtime-configurable IRIS schema name
# Default to 'SQLUser' which is the standard IRIS schema for user tables
IRIS_SCHEMA = os.environ.get("PGWIRE_IRIS_SCHEMA", "SQLUser")

# Log the configured schema at module load
logger.info(
    "Schema mapper initialized",
    iris_schema=IRIS_SCHEMA,
    source="PGWIRE_IRIS_SCHEMA" if "PGWIRE_IRIS_SCHEMA" in os.environ else "default",
)

# Schema mapping configuration (dynamically built from IRIS_SCHEMA)
SCHEMA_MAP = {"public": IRIS_SCHEMA}
REVERSE_MAP = {IRIS_SCHEMA: "public"}

# Column names that contain schema names in information_schema results
SCHEMA_COLUMNS = frozenset({"table_schema", "schema_name", "nspname"})


def translate_input_schema(sql: str) -> str:
    """
    Replace 'public' with configured IRIS schema in incoming queries.

    Handles:
    - WHERE table_schema = 'public' (case-insensitive)
    - FROM public.tablename
    - public. prefix in identifiers

    Args:
        sql: SQL query string

    Returns:
        SQL with 'public' schema references replaced with IRIS_SCHEMA
    """
    if not sql:
        return sql

    result = sql

    # Pattern 1: Schema name in string literals (e.g., table_schema = 'public')
    # Case-insensitive match for 'public', 'PUBLIC', 'Public', etc.
    result = re.sub(
        r"=\s*'public'",
        f"= '{IRIS_SCHEMA}'",
        result,
        flags=re.IGNORECASE,
    )

    # Pattern 2: Schema-qualified table names (e.g., public.tablename)
    # Match public. followed by identifier (word chars) but not inside single quotes
    # This is a simplified approach - we process the SQL outside of string literals
    result = re.sub(
        r'\bpublic\.(\w+)',
        rf'{IRIS_SCHEMA}.\1',
        result,
        flags=re.IGNORECASE,
    )

    # Pattern 3: Double-quoted schema (e.g., "public".tablename)
    result = re.sub(
        r'"public"\.(\w+)',
        rf'{IRIS_SCHEMA}.\1',
        result,
        flags=re.IGNORECASE,
    )

    return result


def translate_output_schema(
    rows: list[tuple[Any, ...]], columns: list[str]
) -> list[tuple[Any, ...]]:
    """
    Replace configured IRIS schema with 'public' in result sets.

    Only modifies values in columns that contain schema names
    (table_schema, schema_name, nspname).

    Args:
        rows: List of result tuples
        columns: List of column names (lowercase)

    Returns:
        Modified rows with IRIS_SCHEMA replaced by 'public' in schema columns
    """
    if not rows or not columns:
        return rows

    # Find indices of schema columns (case-insensitive matching)
    schema_column_indices = []
    for i, col in enumerate(columns):
        if col.lower() in SCHEMA_COLUMNS:
            schema_column_indices.append(i)

    # If no schema columns, return rows unchanged
    if not schema_column_indices:
        return rows

    # Transform rows
    result = []
    for row in rows:
        row_list = list(row)
        for idx in schema_column_indices:
            if idx < len(row_list):
                value = row_list[idx]
                # Only translate IRIS_SCHEMA (case-insensitive) to public
                # Don't translate system schemas (%SYS, %Library, etc.)
                if isinstance(value, str) and value.upper() == IRIS_SCHEMA.upper():
                    row_list[idx] = "public"
        result.append(tuple(row_list))

    return result


def get_schema_config() -> dict[str, str]:
    """
    Get the current schema mapping configuration.

    Returns:
        Dictionary with schema configuration:
        {
            'iris_schema': str,      # Current IRIS schema (e.g., 'SQLUser')
            'postgres_schema': str,  # PostgreSQL schema (always 'public')
            'source': str            # Configuration source ('env' or 'default')
        }
    """
    return {
        "iris_schema": IRIS_SCHEMA,
        "postgres_schema": "public",
        "source": "env" if "PGWIRE_IRIS_SCHEMA" in os.environ else "default",
    }


def configure_schema(iris_schema: str | None = None, mapping: dict[str, str] | None = None) -> None:
    """
    Configure the schema mapping at runtime.

    This allows programmatic configuration (e.g., from config file or API)
    in addition to the environment variable.

    Args:
        iris_schema: Simple case - IRIS schema name to map 'public' to
        mapping: Advanced case - dict of {pg_schema: iris_schema} mappings
                 Example: {"public": "MyAppSchema", "analytics": "ReportSchema"}

    Note:
        This modifies module-level globals. Thread safety is the caller's
        responsibility if called from multiple threads.

    Examples:
        # Simple: map public to custom schema
        configure_schema(iris_schema="MyAppSchema")

        # Advanced: custom mapping dict
        configure_schema(mapping={"public": "MyAppSchema"})
    """
    global IRIS_SCHEMA, SCHEMA_MAP, REVERSE_MAP

    old_schema = IRIS_SCHEMA

    if mapping is not None:
        # Use provided mapping dict
        SCHEMA_MAP = mapping.copy()
        REVERSE_MAP = {v: k for k, v in mapping.items()}
        # Set IRIS_SCHEMA to the first mapping's target for backwards compat
        IRIS_SCHEMA = next(iter(mapping.values()), "SQLUser")
    elif iris_schema is not None:
        # Simple case - just set the IRIS schema
        IRIS_SCHEMA = iris_schema
        SCHEMA_MAP = {"public": IRIS_SCHEMA}
        REVERSE_MAP = {IRIS_SCHEMA: "public"}
    else:
        raise ValueError("Must provide either iris_schema or mapping argument")

    logger.info(
        "Schema mapping reconfigured",
        old_schema=old_schema,
        new_schema=IRIS_SCHEMA,
        schema_map=SCHEMA_MAP,
    )

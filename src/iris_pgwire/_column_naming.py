"""Column name normalization from IRIS conventions to PostgreSQL conventions.

IRIS generates generic names like HostVar_1, Expression_1, Aggregate_1
when no explicit alias is provided. PostgreSQL uses different conventions
(e.g., ?column? for unnamed expressions). This module handles the mapping.
"""

from __future__ import annotations

import re

import structlog

logger = structlog.get_logger()

# IRIS type names → PostgreSQL short type names
_POSTGRES_TYPE_MAP: dict[str, str] = {
    "integer": "int4",
    "bigint": "int8",
    "smallint": "int2",
    "real": "float4",
    "double": "float8",
    "double precision": "float8",
    "character varying": "varchar",
    "character": "char",
}

# Cast pattern: (sql_upper_fragment, cast_keyword, pg_type_name)
_CAST_PATTERNS: list[tuple[str, str, str]] = [
    ("::INT", "AS INTEGER", "int4"),
    ("::BIGINT", "AS BIGINT", "int8"),
    ("::SMALLINT", "AS SMALLINT", "int2"),
    ("::TEXT", "AS TEXT", "text"),
    ("::VARCHAR", "AS VARCHAR", "varchar"),
    ("::BOOL", "AS BIT", "bool"),
    ("::DATE", "AS DATE", "date"),
]

_GENERIC_COLUMN_NAMES = frozenset(f"column{suffix}" for suffix in ("", "1", "2", "3", "4", "5"))


def normalize_iris_column_name(iris_name: str, sql: str, iris_type: str | int) -> str:
    """Normalize IRIS-generated column names to PostgreSQL-compatible names.

    Args:
        iris_name: Original column name from IRIS.
        sql: Original SQL query for context.
        iris_type: IRIS type code for type-specific naming.

    Returns:
        PostgreSQL-compatible column name.
    """
    normalized = iris_name.lower()
    sql_upper = sql.upper()
    sql_lower = sql.lower()

    def _find_explicit_alias(literal_val: str) -> str | None:
        """Check if SQL contains 'literal_val AS alias' and return the alias."""
        if literal_val.replace(".", "").replace("-", "").isdigit():
            # Numeric literal: match "1 AS id", "2.5 AS score"
            pattern = rf"\b{re.escape(literal_val)}\s+AS\s+(\w+)"
            match = re.search(pattern, sql, re.IGNORECASE)
            if match:
                return match.group(1).lower()
        else:
            # String literal: match "'first' AS name" or '"hello" AS greeting'
            match = re.search(
                rf"'{re.escape(literal_val)}'\s+AS\s+(\w+)", sql, re.IGNORECASE
            ) or re.search(rf'"{re.escape(literal_val)}"\s+AS\s+(\w+)', sql, re.IGNORECASE)
            if match:
                return match.group(1).lower()
        return None

    # --- Numeric literal column names (e.g., '1', '42', '3.14', '-5') ---
    try:
        float(normalized)
        explicit_alias = _find_explicit_alias(normalized)
        if explicit_alias:
            logger.debug(
                "numeric literal with explicit alias",
                iris_name=iris_name,
                alias=explicit_alias,
            )
            return explicit_alias
        return "?column?"
    except ValueError:
        pass

    # --- SELECT without FROM: generic names → ?column? ---
    if "SELECT" in sql_upper and "FROM" not in sql_upper:
        if normalized in _GENERIC_COLUMN_NAMES:
            if f" as {normalized}" not in sql_lower and f' as "{normalized}"' not in sql_lower:
                return "?column?"

        # String literal used as column name → ?column?
        unquoted = normalized.replace("'", "").replace('"', "").strip()
        if f"'{unquoted}'" in sql_lower or f'"{unquoted}"' in sql_lower:
            return "?column?"

    # --- HostVar_N (unnamed literals) → ?column? ---
    if normalized.startswith("hostvar_"):
        return "?column?"

    # --- Expression_N (casts/expressions) → type name or ?column? ---
    if normalized.startswith("expression_"):
        for shorthand, cast_keyword, pg_type in _CAST_PATTERNS:
            if shorthand in sql_upper or ("CAST" in sql_upper and cast_keyword in sql_upper):
                return pg_type
        return "?column?"

    # --- Aggregate_N (aggregate functions) → function name ---
    if normalized.startswith("aggregate_"):
        for func in ("COUNT", "SUM", "AVG", "MIN", "MAX"):
            if f"{func}(" in sql_upper:
                return func.lower()
        return normalized

    # --- PostgreSQL type name mapping (INTEGER → int4, etc.) ---
    if normalized in _POSTGRES_TYPE_MAP:
        return _POSTGRES_TYPE_MAP[normalized]

    # --- Named columns: keep lowercased ---
    return normalized

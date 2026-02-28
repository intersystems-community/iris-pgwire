"""Type translation utilities for PostgreSQL → IRIS."""

from __future__ import annotations

from dataclasses import dataclass

from .ddl_parser import ColumnDefinition
from .ddl_translator import DDLTranslationError


@dataclass(frozen=True)
class TypeMappingEntry:
    pg_type: str
    iris_type: str
    requires_precision: bool = False
    max_precision: int | None = None
    max_scale: int | None = None


DDL_TYPE_MAPPINGS: dict[str, TypeMappingEntry] = {
    "text": TypeMappingEntry("text", "VARCHAR(32767)", False),
    "boolean": TypeMappingEntry("boolean", "BIT", False),
    "uuid": TypeMappingEntry("uuid", "UUID", False),
    "jsonb": TypeMappingEntry("jsonb", "JSON", False),
    "json": TypeMappingEntry("json", "JSON", False),
    "jsonpath": TypeMappingEntry("jsonpath", "VARCHAR(*)", False),
    "timestamp": TypeMappingEntry("timestamp", "TIMESTAMP", False),
    "timestamp without time zone": TypeMappingEntry(
        "timestamp without time zone", "TIMESTAMP", False
    ),
    "timestamp with time zone": TypeMappingEntry("timestamp with time zone", "TIMESTAMP", False),
    "timestamptz": TypeMappingEntry("timestamptz", "TIMESTAMP", False),
    "numeric": TypeMappingEntry("numeric", "NUMERIC", True, 38, 19),
    "decimal": TypeMappingEntry("decimal", "NUMERIC", True, 38, 19),
    "money": TypeMappingEntry("money", "NUMERIC", True, 19, 4),
    "integer": TypeMappingEntry("integer", "INTEGER", False),
    "int": TypeMappingEntry("int", "INTEGER", False),
    "int4": TypeMappingEntry("int4", "INTEGER", False),
    "smallint": TypeMappingEntry("smallint", "SMALLINT", False),
    "bigint": TypeMappingEntry("bigint", "BIGINT", False),
    "serial": TypeMappingEntry("serial", "INTEGER", False),
    "smallserial": TypeMappingEntry("smallserial", "SMALLINT", False),
    "bigserial": TypeMappingEntry("bigserial", "BIGINT", False),
    "varchar": TypeMappingEntry("varchar", "VARCHAR", True, 32767, None),
    "character varying": TypeMappingEntry("character varying", "VARCHAR", True, 32767, None),
    "char": TypeMappingEntry("char", "CHAR", True, 32767, None),
    "character": TypeMappingEntry("character", "CHAR", True, 32767, None),
    "date": TypeMappingEntry("date", "DATE", False),
    "time": TypeMappingEntry("time", "TIME", False),
    "time with time zone": TypeMappingEntry("time with time zone", "TIME", False),
    "interval": TypeMappingEntry("interval", "INTERVAL", False),
    "bytea": TypeMappingEntry("bytea", "VARBINARY", True, 32767, None),
    "varbinary": TypeMappingEntry("varbinary", "VARBINARY", True, 32767, None),
    "bit": TypeMappingEntry("bit", "BIT", False),
    "bit varying": TypeMappingEntry("bit varying", "VARBINARY", True, 32767, None),
    "real": TypeMappingEntry("real", "REAL", False),
    "double precision": TypeMappingEntry("double precision", "DOUBLE", False),
    "float4": TypeMappingEntry("float4", "REAL", False),
    "float8": TypeMappingEntry("float8", "DOUBLE", False),
}

IDENTITY_TYPES = {"serial", "smallserial", "bigserial"}

TYPE_PRECISION_LIMITS: dict[str, dict[str, int]] = {
    "NUMERIC": {"max_precision": 38, "max_scale": 19},
    "VARCHAR": {"max_length": 32767},
    "CHAR": {"max_length": 32767},
    "VARBINARY": {"max_length": 32767},
}


class TypeTranslator:
    """Maps PostgreSQL types to IRIS-compatible types."""

    def __init__(self, use_alter_table_syntax: bool = False) -> None:
        """Initialize TypeTranslator.

        Args:
            use_alter_table_syntax: If True, use %Library.String(MAXLEN=n) for ALTER TABLE context
                                   to work around IRIS ALTER TABLE bug with VARCHAR(32767).
        """
        self.use_alter_table_syntax = use_alter_table_syntax

    def translate_type(self, pg_type: str) -> str:
        """Translate a PostgreSQL type into its IRIS equivalent."""
        base_type = self._extract_base_type(pg_type)
        mapping = DDL_TYPE_MAPPINGS.get(base_type)
        if mapping is None:
            raise DDLTranslationError(
                error_code="UNSUPPORTED_TYPE",
                message=f"PostgreSQL type '{base_type}' not supported",
                suggested_fix=f"Use one of: {', '.join(DDL_TYPE_MAPPINGS.keys())}",
                original_sql=pg_type,
            )

        iris_type = mapping.iris_type
        if mapping.requires_precision:
            precision, scale = self._extract_precision(pg_type)
            if precision is not None:
                self._validate_precision(mapping.iris_type, precision, scale, pg_type)
                if scale is not None:
                    iris_type = f"{mapping.iris_type}({precision},{scale})"
                else:
                    iris_type = f"{mapping.iris_type}({precision})"

        # WORKAROUND: IRIS ALTER TABLE bug - VARCHAR(32767) fails with "MAXLEN must be positive integer"
        # Use native %Library.String(MAXLEN=n) syntax for ALTER TABLE context
        if self.use_alter_table_syntax and iris_type.upper().startswith("VARCHAR"):
            if "(" in iris_type:
                # Extract length from VARCHAR(n) or VARCHAR(*)
                start = iris_type.find("(")
                end = iris_type.find(")", start)
                if start != -1 and end != -1:
                    length = iris_type[start + 1 : end].strip()
                    # Convert VARCHAR(*) to actual max length
                    if length == "*":
                        length = "32767"
                    iris_type = f"%Library.String(MAXLEN={length})"

        # WORKAROUND: IRIS DDL requires native class types for JSON (both CREATE and ALTER)
        # JSON doesn't have a User.JSON class, needs %Library.DynamicObject
        if iris_type.upper() == "JSON":
            iris_type = "%Library.DynamicObject"

        # WORKAROUND: IRIS DDL requires native class types for UUID (both CREATE and ALTER)
        # UUID doesn't have a User.UUID class, needs %Library.UniqueIdentifier
        # Note: DEFAULT gen_random_uuid() is skipped earlier in parsing (see ddl_parser.py)
        if iris_type.upper() == "UUID":
            iris_type = "%Library.UniqueIdentifier"

        if base_type in IDENTITY_TYPES:
            iris_type = f"{iris_type} IDENTITY(1,1)"

        return iris_type

    def translate_column(self, column: ColumnDefinition) -> ColumnDefinition:
        """Translate a ColumnDefinition into an IRIS-compatible column definition."""

        iris_type = self.translate_type(column.pg_type)
        return ColumnDefinition(
            name=column.name,
            pg_type=column.pg_type,
            iris_type=iris_type,
            nullable=column.nullable,
            default=column.default,
            is_primary_key=column.is_primary_key,
        )

    def _extract_base_type(self, pg_type: str) -> str:
        normalized = pg_type.strip().lower()
        paren_idx = normalized.find("(")
        if paren_idx != -1:
            normalized = normalized[:paren_idx]
        return normalized.strip()

    def _extract_precision(self, pg_type: str) -> tuple[int | None, int | None]:
        start = pg_type.find("(")
        end = pg_type.find(")", start + 1)
        if start == -1 or end == -1:
            return (None, None)

        inner = pg_type[start + 1 : end].strip()
        if not inner:
            return (None, None)

        parts = [part.strip() for part in inner.split(",") if part.strip()]
        if not parts:
            return (None, None)

        precision: int | None = None
        scale: int | None = None

        # Handle VARCHAR(*) - map "*" to maximum length
        if parts[0] == "*":
            precision = TYPE_PRECISION_LIMITS.get("VARCHAR", {}).get("max_length", 32767)
        else:
            try:
                precision = int(parts[0])
            except ValueError:
                precision = None

        if len(parts) > 1:
            try:
                scale = int(parts[1])
            except ValueError:
                scale = None

        return precision, scale

    def _validate_precision(
        self,
        iris_type: str,
        precision: int,
        scale: int | None,
        original_sql: str,
    ) -> None:
        if iris_type == "NUMERIC":
            limits = TYPE_PRECISION_LIMITS.get("NUMERIC", {})
            max_precision = limits.get("max_precision")
            max_scale = limits.get("max_scale")
            if max_precision is not None and precision > max_precision:
                raise DDLTranslationError(
                    error_code="PRECISION_EXCEEDED",
                    message=f"NUMERIC precision {precision} exceeds IRIS maximum of {max_precision}",
                    suggested_fix=f"Use NUMERIC({max_precision},{max_scale}) or smaller",
                    original_sql=original_sql,
                )
            if scale is not None and max_scale is not None and scale > max_scale:
                raise DDLTranslationError(
                    error_code="SCALE_EXCEEDED",
                    message=f"NUMERIC scale {scale} exceeds IRIS maximum of {max_scale}",
                    suggested_fix=f"Use scale <= {max_scale}",
                    original_sql=original_sql,
                )
        elif iris_type in {"VARCHAR", "CHAR", "VARBINARY"}:
            limits = TYPE_PRECISION_LIMITS.get(iris_type, {})
            max_length = limits.get("max_length")
            if max_length is not None and precision > max_length:
                raise DDLTranslationError(
                    error_code="LENGTH_EXCEEDED",
                    message=f"{iris_type} length {precision} exceeds IRIS maximum of {max_length}",
                    suggested_fix=f"Use {iris_type}({max_length}) or smaller",
                    original_sql=original_sql,
                )


__all__ = [
    "TypeMappingEntry",
    "DDL_TYPE_MAPPINGS",
    "TYPE_PRECISION_LIMITS",
    "TypeTranslator",
]

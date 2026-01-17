"""
Configurable Type Mapping for IRIS → PostgreSQL Type Translation

This module provides configurable type mapping between IRIS SQL types and PostgreSQL types.
PostgreSQL has a very flexible type system with user-defined types, domains, and type aliases.
IRIS has different types that need to be mapped for ORM compatibility.

Configuration can be done via:
1. Environment variables (PGWIRE_TYPE_MAP_<IRIS_TYPE>=<pg_type>:<udt_name>)
2. Programmatic API (configure_type_mapping())
3. Configuration file (type_mapping.json in working directory)

Default mappings follow PostgreSQL conventions expected by ORMs like Prisma, SQLAlchemy, etc.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path

import structlog

logger = structlog.get_logger()


@dataclass
class TypeMapping:
    """Represents a mapping from IRIS type to PostgreSQL type."""
    iris_type: str           # IRIS type name (e.g., 'INTEGER', 'VARCHAR')
    pg_data_type: str        # SQL standard name (e.g., 'integer', 'character varying')
    pg_udt_name: str         # PostgreSQL internal name (e.g., 'int4', 'varchar')
    pg_type_oid: int = 0     # PostgreSQL type OID (0 = auto-detect)
    description: str = ""    # Optional description


# Default IRIS → PostgreSQL type mappings
# These mappings follow PostgreSQL conventions and are compatible with:
# - Prisma (expects udt_name for type resolution)
# - SQLAlchemy (uses data_type and udt_name)
# - node-postgres (uses type_oid)
DEFAULT_TYPE_MAPPINGS: dict[str, tuple[str, str, int]] = {
    # Numeric types
    'INTEGER': ('integer', 'int4', 23),
    'BIGINT': ('bigint', 'int8', 20),
    'SMALLINT': ('smallint', 'int2', 21),
    'TINYINT': ('smallint', 'int2', 21),
    'NUMERIC': ('numeric', 'numeric', 1700),
    'DECIMAL': ('numeric', 'numeric', 1700),

    # Floating point
    'DOUBLE': ('double precision', 'float8', 701),
    'FLOAT': ('double precision', 'float8', 701),
    'REAL': ('real', 'float4', 700),

    # Character types
    'VARCHAR': ('character varying', 'varchar', 1043),
    'CHAR': ('character', 'bpchar', 1042),
    'TEXT': ('text', 'text', 25),
    'LONGVARCHAR': ('text', 'text', 25),

    # Date/Time types
    'DATE': ('date', 'date', 1082),
    'TIME': ('time without time zone', 'time', 1083),
    'TIMESTAMP': ('timestamp without time zone', 'timestamp', 1114),
    'TIMESTAMPTZ': ('timestamp with time zone', 'timestamptz', 1184),

    # Boolean (IRIS uses BIT for boolean)
    'BOOLEAN': ('boolean', 'bool', 16),
    'BIT': ('boolean', 'bool', 16),

    # Binary types
    'VARBINARY': ('bytea', 'bytea', 17),
    'BINARY': ('bytea', 'bytea', 17),
    'LONGVARBINARY': ('bytea', 'bytea', 17),

    # Auto-increment/Serial
    'SERIAL': ('integer', 'int4', 23),
    'BIGSERIAL': ('bigint', 'int8', 20),

    # JSON types
    'JSON': ('json', 'json', 114),
    'JSONB': ('jsonb', 'jsonb', 3802),

    # UUID
    'UUID': ('uuid', 'uuid', 2950),
    'UNIQUEIDENTIFIER': ('uuid', 'uuid', 2950),

    # Vector types (IRIS-specific, mapped to pgvector extension type)
    'VECTOR': ('vector', 'vector', 16388),
    'EMBEDDING': ('vector', 'vector', 16388),
}

# Global type mapping registry
_type_mappings: dict[str, tuple[str, str, int]] = DEFAULT_TYPE_MAPPINGS.copy()


def get_type_mapping(iris_type: str) -> tuple[str, str, int]:
    """
    Get PostgreSQL type mapping for an IRIS type.

    Args:
        iris_type: IRIS type name (case-insensitive)

    Returns:
        Tuple of (pg_data_type, pg_udt_name, pg_type_oid)
        Returns ('text', 'text', 25) for unknown types
    """
    return _type_mappings.get(iris_type.upper(), ('text', 'text', 25))


def configure_type_mapping(
    iris_type: str,
    pg_data_type: str,
    pg_udt_name: str,
    pg_type_oid: int = 0
) -> None:
    """
    Configure a custom type mapping.

    Args:
        iris_type: IRIS type name (will be uppercased)
        pg_data_type: PostgreSQL SQL standard type name
        pg_udt_name: PostgreSQL internal type name (used by ORMs)
        pg_type_oid: PostgreSQL type OID (optional, 0 = auto-detect)

    Example:
        configure_type_mapping('MYTYPE', 'text', 'text', 25)
    """
    _type_mappings[iris_type.upper()] = (pg_data_type, pg_udt_name, pg_type_oid)
    logger.info(
        "Configured custom type mapping",
        iris_type=iris_type.upper(),
        pg_data_type=pg_data_type,
        pg_udt_name=pg_udt_name,
        pg_type_oid=pg_type_oid,
    )


def configure_type_mappings(mappings: dict[str, tuple[str, str, int]]) -> None:
    """
    Configure multiple type mappings at once.

    Args:
        mappings: Dictionary of {IRIS_TYPE: (pg_data_type, pg_udt_name, pg_type_oid)}
    """
    for iris_type, (pg_data_type, pg_udt_name, pg_type_oid) in mappings.items():
        configure_type_mapping(iris_type, pg_data_type, pg_udt_name, pg_type_oid)


def load_type_mappings_from_env() -> None:
    """
    Load type mappings from environment variables.

    Environment variable format:
        PGWIRE_TYPE_MAP_INTEGER=integer:int4:23
        PGWIRE_TYPE_MAP_MYTYPE=text:text:25

    Format: <pg_data_type>:<pg_udt_name>[:<pg_type_oid>]
    """
    prefix = "PGWIRE_TYPE_MAP_"
    for key, value in os.environ.items():
        if key.startswith(prefix):
            iris_type = key[len(prefix):]
            try:
                parts = value.split(':')
                if len(parts) >= 2:
                    pg_data_type = parts[0]
                    pg_udt_name = parts[1]
                    pg_type_oid = int(parts[2]) if len(parts) > 2 else 0
                    configure_type_mapping(iris_type, pg_data_type, pg_udt_name, pg_type_oid)
                    logger.info(f"Loaded type mapping from env: {iris_type} → {pg_data_type}/{pg_udt_name}")
            except Exception as e:
                logger.warning(f"Failed to parse type mapping env var {key}={value}: {e}")


def load_type_mappings_from_file(path: str | Path | None = None) -> None:
    """
    Load type mappings from a JSON configuration file.

    Args:
        path: Path to JSON file. If None, looks for 'type_mapping.json' in current directory.

    JSON format:
    {
        "type_mappings": {
            "INTEGER": {"pg_data_type": "integer", "pg_udt_name": "int4", "pg_type_oid": 23},
            "MYTYPE": {"pg_data_type": "text", "pg_udt_name": "text", "pg_type_oid": 25}
        }
    }
    """
    if path is None:
        path = Path("type_mapping.json")
    else:
        path = Path(path)

    if not path.exists():
        logger.debug(f"Type mapping config file not found: {path}")
        return

    try:
        with open(path) as f:
            config = json.load(f)

        mappings = config.get("type_mappings", {})
        for iris_type, mapping in mappings.items():
            configure_type_mapping(
                iris_type=iris_type,
                pg_data_type=mapping.get("pg_data_type", "text"),
                pg_udt_name=mapping.get("pg_udt_name", "text"),
                pg_type_oid=mapping.get("pg_type_oid", 0),
            )

        logger.info(f"Loaded {len(mappings)} type mappings from {path}")
    except Exception as e:
        logger.warning(f"Failed to load type mappings from {path}: {e}")


def reset_type_mappings() -> None:
    """Reset type mappings to defaults."""
    global _type_mappings
    _type_mappings = DEFAULT_TYPE_MAPPINGS.copy()
    logger.info("Reset type mappings to defaults")


def get_all_type_mappings() -> dict[str, tuple[str, str, int]]:
    """Get all currently configured type mappings."""
    return _type_mappings.copy()


def dump_type_mappings_to_json(path: str | Path) -> None:
    """
    Export current type mappings to a JSON file.

    Args:
        path: Output path for JSON file
    """
    path = Path(path)

    config = {
        "type_mappings": {
            iris_type: {
                "pg_data_type": pg_data_type,
                "pg_udt_name": pg_udt_name,
                "pg_type_oid": pg_type_oid,
            }
            for iris_type, (pg_data_type, pg_udt_name, pg_type_oid) in _type_mappings.items()
        }
    }

    with open(path, 'w') as f:
        json.dump(config, f, indent=2)

    logger.info(f"Exported type mappings to {path}")


# OID → Type reverse lookup (T003)
# Maps PostgreSQL type OID to (pg_data_type, pg_udt_name, iris_type)
# Used by format_type() to convert OID back to type name
OID_TO_TYPE: dict[int, tuple[str, str]] = {
    # Build from DEFAULT_TYPE_MAPPINGS
    oid: (pg_data_type, pg_udt_name)
    for iris_type, (pg_data_type, pg_udt_name, oid) in DEFAULT_TYPE_MAPPINGS.items()
}

# Add PostgreSQL-specific types not in DEFAULT_TYPE_MAPPINGS
OID_TO_TYPE.update({
    1266: ('time with time zone', 'timetz'),      # TIMETZ
    1560: ('bit', 'bit'),                         # BIT fixed-length
    1562: ('bit varying', 'varbit'),              # BIT VARYING
})


def get_type_by_oid(type_oid: int) -> tuple[str, str] | None:
    """
    Get PostgreSQL type info from OID (T004).

    Args:
        type_oid: PostgreSQL type OID

    Returns:
        Tuple of (pg_data_type, pg_udt_name) or None if unknown

    Example:
        get_type_by_oid(23) returns ('integer', 'int4')
        get_type_by_oid(1043) returns ('character varying', 'varchar')
        get_type_by_oid(99999) returns None
    """
    return OID_TO_TYPE.get(type_oid)


class TypeModifier:
    """
    Type Modifier (typmod) decoder for parameterized PostgreSQL types (T005).

    PostgreSQL encodes type parameters (length, precision, scale) in a single
    integer called typmod. This class decodes those values back to human-readable
    format for format_type() output.

    References:
        - PostgreSQL src/backend/utils/adt/format_type.c
        - contracts/format_type_contract.md
    """

    @staticmethod
    def decode_char_length(typmod: int) -> int | None:
        """
        Decode character type length from typmod.

        Character types (CHAR, VARCHAR) encode length as: typmod = length + 4

        Args:
            typmod: Type modifier value

        Returns:
            Length in characters, or None if unlimited (-1)

        Example:
            decode_char_length(259) returns 255  # varchar(255)
            decode_char_length(-1) returns None  # varchar (unlimited)
        """
        if typmod < 0:
            return None
        return typmod - 4

    @staticmethod
    def decode_numeric_precision(typmod: int) -> tuple[int, int] | None:
        """
        Decode NUMERIC precision and scale from typmod.

        NUMERIC encodes as: typmod = ((precision << 16) + scale) + 4

        Args:
            typmod: Type modifier value

        Returns:
            Tuple of (precision, scale), or None if no modifier

        Example:
            decode_numeric_precision(655366) returns (10, 2)  # numeric(10,2)
            decode_numeric_precision(-1) returns None  # numeric (no limit)
        """
        if typmod < 0:
            return None

        packed = typmod - 4
        precision = packed >> 16
        scale = packed & 0xFFFF
        return (precision, scale)

    @staticmethod
    def decode_timestamp_precision(typmod: int) -> int | None:
        """
        Decode timestamp/time fractional seconds precision.

        Timestamp types encode as: typmod = precision + 4

        Args:
            typmod: Type modifier value

        Returns:
            Precision (0-6), or None for default (6)

        Example:
            decode_timestamp_precision(7) returns 3  # timestamp(3)
            decode_timestamp_precision(-1) returns None  # timestamp (default 6)
        """
        if typmod < 0:
            return None
        return typmod - 4

    @staticmethod
    def decode_bit_length(typmod: int) -> int | None:
        """
        Decode BIT/BIT VARYING length from typmod.

        Bit types encode as: typmod = length + 4

        Args:
            typmod: Type modifier value

        Returns:
            Bit length, or None if unlimited

        Example:
            decode_bit_length(36) returns 32  # bit(32)
            decode_bit_length(-1) returns None  # bit varying (unlimited)
        """
        if typmod < 0:
            return None
        return typmod - 4


# Initialize type mappings from environment on module load
load_type_mappings_from_env()

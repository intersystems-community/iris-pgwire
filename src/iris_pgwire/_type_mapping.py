"""Internal type-mapping helpers for IRIS ↔ PostgreSQL OID conversion.

Pure functions with no logging or external dependencies beyond stdlib + Decimal.
"""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from typing import Any

# IRIS POSIXTIME: microseconds since 1970-01-01 with a large offset added.
POSIXTIME_OFFSET = 1152921504606846976
POSIXTIME_MAX = POSIXTIME_OFFSET + 7258118400000000  # ~2200-01-01

# ---------------------------------------------------------------------------
# Integer type-code → OID  (IRIS JDBC / ODBC codes)
# ---------------------------------------------------------------------------
_INT_TYPE_TO_OID: dict[int, int] = {
    -7: 16,  # BIT → bool
    -6: 21,  # TINYINT → int2
    -5: 20,  # BIGINT → int8
    1: 1042,  # CHAR → bpchar
    2: 1700,  # NUMERIC
    3: 20,  # → int8
    4: 23,  # → int4
    5: 701,  # → float8
    8: 701,  # IRIS DOUBLE → float8
    9: 1082,  # → date
    10: 1114,  # → timestamp
    12: 1043,  # → varchar
    16: 16,  # → bool
    17: 17,  # → bytea
    # JDBC standard codes
    91: 1082,  # JDBC DATE
    92: 1083,  # JDBC TIME
    93: 1114,  # JDBC TIMESTAMP
    # IRIS extended codes (returned for TIMESTAMP/POSIXTIME columns)
    1091: 1082,
    1092: 1083,
    1093: 1114,
}

# ---------------------------------------------------------------------------
# String type-name → OID  (union of both original mappings)
# ---------------------------------------------------------------------------
_STR_TYPE_TO_OID: dict[str, int] = {
    "INT": 23,
    "INTEGER": 23,
    "BIGINT": 20,
    "SMALLINT": 21,
    "VARCHAR": 1043,
    "CHAR": 1042,
    "TEXT": 25,
    "DATE": 1082,
    "TIME": 1083,
    "TIMESTAMP": 1114,
    "DOUBLE": 701,
    "FLOAT": 700,
    "NUMERIC": 1700,
    "DECIMAL": 1700,
    "BIT": 1560,
    "BOOLEAN": 16,
    "BINARY": 17,
    "VARBINARY": 17,
    "VECTOR": 16388,
}

_DEFAULT_OID = 1043  # VARCHAR


def iris_type_to_pg_oid(iris_type: str | int) -> int:
    """Convert an IRIS type (integer code or string name) to a PostgreSQL OID.

    Handles both JDBC/ODBC integer type codes and SQL string type names
    such as ``"VARCHAR"`` or ``"INTEGER(10)"``.  Unknown types default to
    VARCHAR (1043).
    """
    if isinstance(iris_type, int):
        return _INT_TYPE_TO_OID.get(iris_type, _DEFAULT_OID)

    # Strip size/precision suffix: "VARCHAR(255)" → "VARCHAR"
    normalized = str(iris_type).upper().split("(")[0].strip()
    return _STR_TYPE_TO_OID.get(normalized, _DEFAULT_OID)


# ---------------------------------------------------------------------------
# Value-based type inference
# ---------------------------------------------------------------------------

_INT4_MIN = -(2**31)
_INT4_MAX = 2**31 - 1
_ID_HINTS = ("id", "key")


def infer_type_from_value(value: Any, column_name: str | None = None) -> int:
    """Infer a PostgreSQL OID from a Python value.

    Uses POSIXTIME range detection for large integers and column-name hints
    (``id`` / ``key``) to choose BIGINT over INTEGER.
    """
    if value is None:
        return 1043  # VARCHAR — most flexible for NULL

    if isinstance(value, bool):
        return 16  # BOOL

    if isinstance(value, int):
        if POSIXTIME_OFFSET <= value <= POSIXTIME_MAX:
            return 1114  # TIMESTAMP
        if column_name and any(k in column_name.lower() for k in _ID_HINTS):
            return 20  # BIGINT
        if _INT4_MIN <= value <= _INT4_MAX:
            return 23  # INTEGER
        return 20  # BIGINT

    if isinstance(value, float):
        return 701  # FLOAT8

    if isinstance(value, Decimal):
        return 1700  # NUMERIC

    if isinstance(value, bytes):
        return 17  # BYTEA

    if isinstance(value, dt.datetime):
        return 1114  # TIMESTAMP

    if isinstance(value, dt.date):
        return 1082  # DATE

    return 1043  # VARCHAR (default for str and everything else)


# ---------------------------------------------------------------------------
# Value serialisation
# ---------------------------------------------------------------------------

_TIMESTAMP_PARSE_FORMATS = (
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
)

_PG_TIMESTAMP_FMT = "%Y-%m-%d %H:%M:%S.%f"

_EPOCH_1970 = dt.datetime(1970, 1, 1)
_EPOCH_2000 = dt.datetime(2000, 1, 1)


def serialize_value(value: Any, type_oid: int) -> Any:
    """Serialize a Python value for the PostgreSQL wire protocol.

    Converts IRIS-specific representations (e.g. POSIXTIME microsecond
    integers) into the text format PostgreSQL clients expect.
    """
    if value is None:
        return None

    if type_oid == 1114:  # TIMESTAMP
        return _serialize_timestamp(value)

    return value


def _serialize_timestamp(value: Any) -> Any:
    """Convert various timestamp representations to PG text format."""
    if isinstance(value, int):
        try:
            if value >= POSIXTIME_OFFSET:
                unix_us = value - POSIXTIME_OFFSET
                ts = _EPOCH_1970 + dt.timedelta(microseconds=unix_us)
            else:
                # Legacy: microseconds since 2000-01-01
                ts = _EPOCH_2000 + dt.timedelta(microseconds=value)
            return ts.strftime(_PG_TIMESTAMP_FMT)
        except Exception:
            return value

    if isinstance(value, dt.datetime):
        return value.strftime(_PG_TIMESTAMP_FMT)

    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            unix_us = int(stripped) - POSIXTIME_OFFSET
            ts = _EPOCH_1970 + dt.timedelta(microseconds=unix_us)
            return ts.strftime(_PG_TIMESTAMP_FMT)

        # Try known datetime string formats
        for fmt in _TIMESTAMP_PARSE_FORMATS:
            try:
                ts = dt.datetime.strptime(stripped.rstrip("Z"), fmt)
                return ts.strftime(_PG_TIMESTAMP_FMT)
            except ValueError:
                continue

    return value  # unrecognised — pass through


# ---------------------------------------------------------------------------
# SQL CAST detection
# ---------------------------------------------------------------------------

_CAST_TYPE_MAP: dict[str, int] = {
    "bool": 16,
    "boolean": 16,
    "bit": 16,  # IRIS uses BIT for boolean
    "int": 23,
    "integer": 23,
    "bigint": 20,
    "smallint": 21,
    "text": 25,
    "varchar": 1043,
    "date": 1082,
    "timestamp": 1114,
    "float": 701,
    "double": 701,
}


def detect_cast_type_oid(sql: str, column_name: str) -> int | None:
    """Detect a PostgreSQL OID from CAST expressions targeting *column_name*.

    Recognises two patterns:
    - ``$1::bool AS column_name``   (PostgreSQL-style cast)
    - ``CAST(? AS BIT) AS column_name``  (SQL-standard cast)

    Returns ``None`` if no matching cast is found.
    """
    sql_upper = sql.upper()
    col_escaped = re.escape(column_name.upper())

    # Pattern 1: $N::type AS column
    match = re.search(rf"\$\d+::(\w+)\s+AS\s+{col_escaped}", sql_upper)
    if match:
        return _CAST_TYPE_MAP.get(match.group(1).lower())

    # Pattern 2: CAST(? AS type) AS column
    match = re.search(rf"CAST\(\?\s+AS\s+(\w+)\)\s+AS\s+{col_escaped}", sql_upper)
    if match:
        return _CAST_TYPE_MAP.get(match.group(1).lower())

    return None

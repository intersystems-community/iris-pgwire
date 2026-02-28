"""
Row/column post-processing for IRIS result sets.

Extracted from duplicated logic in iris_executor._sync_execute (embedded)
and iris_executor._sync_external_execute (external) to provide a single
implementation for date/timestamp conversion and IRIS type OID overrides.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import structlog

from .conversions import horolog_to_pg

logger = structlog.get_logger(__name__)

# IRIS POSIXTIME constants (canonical source: iris_executor module-level)
POSIXTIME_OFFSET: int = 1152921504606846976
POSIXTIME_MAX: int = POSIXTIME_OFFSET + 7258118400000000  # ~2200-01-01

# PostgreSQL J2000 epoch
_PG_EPOCH = dt.date(2000, 1, 1)


def serialize_value(value: Any, type_oid: int) -> Any:
    """Serialize a single cell value for PostgreSQL wire protocol compatibility.

    Converts IRIS-specific types (POSIXTIME microsecond integers, datetime
    objects, digit-string timestamps) into the PostgreSQL text wire format
    expected by client drivers such as psycopg.

    Returns the value unchanged when no conversion applies.
    """
    if value is None:
        return None

    # OID 1114 = TIMESTAMP
    # PostgreSQL text wire format: "YYYY-MM-DD HH:MM:SS.ffffff"
    # (space separator, no trailing Z/timezone -- psycopg TimestampLoader requires this)
    if type_oid == 1114:
        if isinstance(value, int):
            try:
                if value >= POSIXTIME_OFFSET:
                    # IRIS POSIXTIME (microseconds since 1970-01-01)
                    unix_us = value - POSIXTIME_OFFSET
                    ts_obj = dt.datetime(1970, 1, 1) + dt.timedelta(microseconds=unix_us)
                else:
                    # PostgreSQL legacy/IRIS microsecond integer (microseconds since 2000-01-01)
                    ts_obj = dt.datetime(2000, 1, 1) + dt.timedelta(microseconds=value)
                return ts_obj.strftime("%Y-%m-%d %H:%M:%S.%f")
            except Exception:
                return value

        if isinstance(value, dt.datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S.%f")

        if isinstance(value, str):
            stripped = value.strip()
            if stripped.isdigit():
                # POSIXTIME encoded as digit string
                unix_us = int(stripped) - POSIXTIME_OFFSET
                ts_obj = dt.datetime(1970, 1, 1) + dt.timedelta(microseconds=unix_us)
                return ts_obj.strftime("%Y-%m-%d %H:%M:%S.%f")

            # Pre-decoded datetime string from IRIS driver -- parse and reformat
            for fmt in (
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M:%S.%f",
                "%Y-%m-%dT%H:%M:%S",
            ):
                try:
                    ts_obj = dt.datetime.strptime(stripped.rstrip("Z"), fmt)
                    return ts_obj.strftime("%Y-%m-%d %H:%M:%S.%f")
                except ValueError:
                    continue
            return value  # unrecognised format -- pass through unchanged

    # OID 1082 = DATE (integer Horolog already converted elsewhere; safety passthrough)
    if type_oid == 1082 and isinstance(value, int):
        return value

    return value


# ---------------------------------------------------------------------------
# Row / column post-processing
# ---------------------------------------------------------------------------


def convert_rows_dates_and_timestamps(
    rows: list[list[Any]],
    columns: list[dict[str, Any]],
) -> None:
    """Convert IRIS date/timestamp values in *rows* to PostgreSQL wire format.

    Mutates *rows* and *columns* in-place:

    1. Builds a ``column_type_oids`` lookup from *columns*.
    2. For integer columns (OID 20/23) whose value falls within the POSIXTIME
       range, reclassifies the column as TIMESTAMP (OID 1114) and serializes
       the value accordingly.
    3. Runs :func:`serialize_value` on every cell for TIMESTAMP formatting.
    4. Converts DATE (OID 1082) ISO strings (``YYYY-MM-DD``) to PostgreSQL
       integer days since 2000-01-01.
    5. Converts Horolog integer dates to PostgreSQL days via
       :func:`~iris_pgwire.conversions.horolog_to_pg`.
    """
    if not rows or not columns:
        return

    column_type_oids = [col["type_oid"] for col in columns]

    for row_idx, row in enumerate(rows):
        for col_idx, value in enumerate(row):
            if col_idx >= len(column_type_oids):
                continue

            type_oid = column_type_oids[col_idx]

            # Detect POSIXTIME integers masquerading as INT8/INT4
            if type_oid in (20, 23) and isinstance(value, int):
                if POSIXTIME_OFFSET <= value <= POSIXTIME_MAX:
                    type_oid = 1114
                    if row_idx == 0:
                        columns[col_idx]["type_oid"] = 1114

            # Robust serialization (TIMESTAMP, etc.)
            rows[row_idx][col_idx] = serialize_value(rows[row_idx][col_idx], type_oid)
            value = rows[row_idx][col_idx]

            # OID 1082 = DATE
            if type_oid == 1082 and value is not None:
                try:
                    if isinstance(value, str):
                        # IRIS returns dates as ISO strings (YYYY-MM-DD)
                        date_obj = dt.datetime.strptime(value, "%Y-%m-%d").date()
                        pg_days = (date_obj - _PG_EPOCH).days
                        rows[row_idx][col_idx] = pg_days
                        logger.debug(
                            "Converted date string to PostgreSQL format",
                            row=row_idx,
                            col=col_idx,
                            iris_string=value,
                            pg_days=pg_days,
                            date_obj=str(date_obj),
                        )
                    elif isinstance(value, int):
                        pg_date = horolog_to_pg(value)
                        rows[row_idx][col_idx] = pg_date
                        logger.debug(
                            "Converted Horolog date to PostgreSQL format",
                            row=row_idx,
                            col=col_idx,
                            iris_horolog=value,
                            pg_days=pg_date,
                        )
                except Exception as date_err:
                    logger.warning(
                        "Failed to convert date value",
                        row=row_idx,
                        col=col_idx,
                        value=value,
                        value_type=type(value).__name__,
                        error=str(date_err),
                    )
                    # Keep original value if conversion fails


# ---------------------------------------------------------------------------
# IRIS type OID overrides
# ---------------------------------------------------------------------------


def override_iris_type_oid(iris_type: int, type_oid: int, sql_upper: str) -> int:
    """Apply IRIS-specific type OID corrections for PostgreSQL compatibility.

    Handles two cases where IRIS returns an incorrect or sub-optimal type OID:

    * **IRIS type code 2 (NUMERIC)** -- decimal literals like ``3.14`` are
      reported as NUMERIC.  For client drivers that distinguish NUMERIC from
      FLOAT (e.g. node-postgres), we override to FLOAT8 (OID 701) unless the
      SQL contains an explicit ``CAST … AS NUMERIC`` / ``AS DECIMAL`` / ``AS
      INTEGER`` / ``AS INT``.  An explicit ``AS INTEGER`` / ``AS INT`` cast
      produces INT4 (OID 23).

    * **CURRENT_TIMESTAMP** -- IRIS returns OID 25 (TEXT) or 1043 (VARCHAR)
      for ``CURRENT_TIMESTAMP``.  Both are overridden to 1114 (TIMESTAMP) so
      that client drivers (Npgsql, psycopg) handle the value correctly.

    Returns the (possibly corrected) *type_oid*.
    """
    if iris_type == 2:
        if "AS INTEGER" in sql_upper or "AS INT" in sql_upper:
            logger.debug(
                "Overriding IRIS type code 2 (NUMERIC) to INT4 for explicit INTEGER cast",
                original_oid=type_oid,
            )
            return 23  # INT4
        if "AS NUMERIC" not in sql_upper and "AS DECIMAL" not in sql_upper:
            logger.debug(
                "Overriding IRIS type code 2 (NUMERIC) to FLOAT8 for decimal literal",
                original_oid=type_oid,
            )
            return 701  # FLOAT8

    if "CURRENT_TIMESTAMP" in sql_upper and type_oid in (25, 1043):
        logger.debug(
            "Overriding CURRENT_TIMESTAMP type to TIMESTAMP",
            original_oid=type_oid,
        )
        return 1114  # TIMESTAMP

    return type_oid

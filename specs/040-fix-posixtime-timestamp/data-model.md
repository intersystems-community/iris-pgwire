# Data Model: Fix POSIXTIME/TIMESTAMP Handling

**Branch**: `040-fix-posixtime-timestamp` | **Date**: 2026-02-18

## Overview

This feature introduces **no new entities, no schema changes, and no new persistent state**. It is a pure translation-layer bug fix. The "data model" here describes the value transformation contracts between representations.

---

## Value Transformation Map

### Inbound (Client → IRIS)

| Client Input Type | Example | Gateway Output to IRIS |
|---|---|---|
| `datetime.datetime` (naive) | `datetime(2025, 1, 1, 12, 0, 0)` | `'2025-01-01 12:00:00.000000'` |
| `datetime.datetime` (UTC-aware) | `datetime(2025, 1, 1, 12, tzinfo=UTC)` | `'2025-01-01 12:00:00.000000'` |
| `datetime.datetime` (offset-aware, e.g. +08:00) | `datetime(2025, 1, 1, 20, tzinfo=+8h)` | `'2025-01-01 12:00:00.000000'` (UTC equiv) |
| `datetime.date` | `date(2025, 1, 1)` | `'2025-01-01'` |
| `str` ISO 8601 with `Z` | `'2025-01-01T12:00:00Z'` | `'2025-01-01 12:00:00'` |
| `str` ISO 8601 with offset | `'2025-01-01T20:00:00+08:00'` | `'2025-01-01 12:00:00'` (UTC equiv) |
| `str` ISO 8601 naive | `'2025-01-01T12:00:00'` | `'2025-01-01 12:00:00'` |
| `str` already plain | `'2025-01-01 12:00:00'` | `'2025-01-01 12:00:00'` (unchanged) |

### Outbound (IRIS → Client)

| IRIS Output Type | Example | Gateway OID | Wire Value Sent |
|---|---|---|---|
| `int` POSIXTIME (type_code=1093) | `1154692939441846976` | `1114` | `'2026-02-18T17:13:55.000000Z'` |
| `str` digit string (POSIXTIME as str) | `'1154692939441846976'` | `1114` | `'2026-02-18T17:13:55.000000Z'` |
| `str` datetime string | `'2025-01-01 12:00:00'` | `1114` | `'2025-01-01T12:00:00.000000Z'` |
| `str` ISO 8601 with Z | `'2025-01-01T12:00:00Z'` | `1114` | `'2025-01-01T12:00:00Z'` (pass-through) |
| `datetime.datetime` | `datetime(2025,1,1,12)` | `1114` | `'2025-01-01T12:00:00.000000Z'` |
| `None` | `NULL` | any | `None` |

### Type Code → OID Mapping (complete for date/time types)

| IRIS JDBC `type_code` | Description | PostgreSQL OID | Type Name |
|---|---|---|---|
| `9` | IRIS DATE (internal) | `1082` | `date` |
| `10` | IRIS TIMESTAMP (internal) | `1114` | `timestamp` |
| `91` | Standard JDBC DATE | `1082` | `date` |
| `92` | Standard JDBC TIME | `1083` | `time` |
| `93` | Standard JDBC TIMESTAMP | `1114` | `timestamp` |
| `1091` | IRIS extended DATE | `1082` | `date` |
| `1092` | IRIS extended TIME | `1083` | `time` |
| `1093` | IRIS extended TIMESTAMP | `1114` | `timestamp` |

---

## Constants

| Constant | Value | Location | Usage |
|---|---|---|---|
| `POSIXTIME_OFFSET` | `1152921504606846976` (= 2^60) | `iris_executor.py` (line 46) | Detection range lower bound; subtracted during decoding |
| `POSIXTIME_MAX` | `POSIXTIME_OFFSET + 7258118400000000` | `iris_executor.py` (line 47) | Detection range upper bound (~year 2200) |

Both constants imported (not redefined) in `dbapi_executor.py` after this fix.

---

## Invariants

1. `NULL` input → `None` output; no conversion attempted at any stage.
2. All timezone-aware inputs → UTC-normalized before storage; no local time stored.
3. All TIMESTAMP wire outputs → ISO 8601 with `Z` suffix (UTC); psycopg decodes as `datetime.datetime`.
4. OID `1114` (TIMESTAMP) is the canonical outbound type for all POSIXTIME values, regardless of how IRIS returns them (int, digit string, or datetime string).
5. POSIXTIME detection range `[POSIXTIME_OFFSET, POSIXTIME_MAX]` is exclusive for integers; integers outside this range are treated as normal INT4/INT8.

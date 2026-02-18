# Feature Specification: Fix POSIXTIME/TIMESTAMP Handling

**Feature Branch**: `040-fix-posixtime-timestamp`  
**Created**: 2026-02-18  
**Status**: Draft  

## Background

IRIS stores timestamps internally as `%PosixTime` — a large `BIGINT` encoding microseconds since the Unix epoch with a fixed offset (`POSIXTIME_OFFSET = 1152921504606846976`, i.e. 2^60). The gateway must handle timestamps bidirectionally:

1. **Inbound** (client → IRIS): Convert ISO 8601 strings or Python `datetime` objects to the plain `YYYY-MM-DD HH:MM:SS[.fff]` form that IRIS accepts for `%PosixTime`/`TIMESTAMP` columns.
2. **Outbound** (IRIS → client): Detect `%PosixTime`-encoded values and convert them back to ISO 8601 datetimes that psycopg/postgres clients expect as `datetime.datetime`.

Three confirmed bugs plus one structural gap, all within `iris_executor.py`:

### Bug 1 — Missing IRIS JDBC type codes in `_iris_type_to_pg_oid()`
`int_type_mapping` does not include IRIS extended JDBC type codes `1091` (DATE), `1092` (TIME), `1093` (TIMESTAMP). When `cursor.description` returns `type_code=1093` for a TIMESTAMP column, the method falls through to the default and returns OID `1043` (VARCHAR). **Impact**: RowDescription sent to postgres.js / Drizzle ORM has `type_oid=1043`; the client receives a plain string instead of a parsed `Date` object.

### Bug 2 — Wrong conversion formula for PosixTime returned as a string
When IRIS returns a POSIXTIME-encoded value as a **digit string** (e.g., `'1154692939441846976'`), `_serialize_value()` has no `str` branch for OID `1114` and falls through to `return value` — returning the raw string. If any caller applies an ad-hoc conversion, the formula `int(value) // 10**9` is incorrect; the correct formula is `unix_us = int(value) - POSIXTIME_OFFSET` (same as the existing `int` branch).

### Bug 3 — Inbound `datetime.datetime` objects not normalized
`_normalize_parameters` handles ISO 8601 strings but not Python `datetime.datetime` or `datetime.date` objects. Drivers (psycopg3) that bind native datetime objects cause IRIS to reject the query.

### Structural gap — DBAPI executor parity
`dbapi_executor.py` has its own `_convert_value_for_iris` with the same `datetime` object gap, and it duplicates POSIXTIME constant knowledge.

---

## Clarifications

### Session 2026-02-18

- Q: How should ISO 8601 strings with non-UTC timezone offsets (e.g., `+08:00`) be handled inbound? → A: Convert to UTC, then format as `YYYY-MM-DD HH:MM:SS[.fff]` (UTC-equivalent time, offset stripped).
- Q: How should backward compatibility of the OID change (1043→1114 for JDBC type_code 1093) be handled? → A: Fix is correct; update all tests to expect OID `1114` / `datetime.datetime` — no compatibility shim.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 – Round-trip TIMESTAMP via RETURNING (Priority: P1)

A developer using Drizzle ORM (or any ORM) inserts a row with a `TIMESTAMP` column and reads it back via `RETURNING`. They expect a proper `datetime` object, not a raw string or integer.

**Why this priority**: Core ORM compatibility. Drizzle, Prisma, and SQLAlchemy all depend on `RETURNING` returning typed values. Bug 1 (wrong OID) and Bug 2 (string POSIXTIME not converted) both manifest here.

**Independent Test**: `test_returning_timestamp_posixtime_repro` in `tests/protocol/test_type_mapping_repro.py`.

**Acceptance Scenarios**:

1. **Given** a table with a `TIMESTAMP` column and a row inserted via `'2025-01-01 00:00:00'`, **When** the client executes `INSERT ... RETURNING ts_val`, **Then** `row[0]` is a `datetime.datetime` with `year == 2025`.
2. **Given** an IRIS `%PosixTime` integer (`type_code=1093`) in a result column, **When** the gateway looks up the OID via `_iris_type_to_pg_oid(1093)`, **Then** it returns `1114` (TIMESTAMP), not `1043` (VARCHAR).
3. **Given** IRIS returns a POSIXTIME value as the digit string `'1154692939441846976'`, **When** serialized with OID `1114`, **Then** the gateway converts it using `unix_us = int(value) - POSIXTIME_OFFSET` and returns an ISO 8601 string (e.g., `'2026-02-18T17:13:55.000000Z'`).
4. **Given** multiple columns in `RETURNING` (`ts_val, name, id`), **When** fetched, **Then** column names match exactly and each value has the correct Python type.

---

### User Story 2 – Inbound `datetime.datetime` parameter normalization (Priority: P1)

A developer passes a Python `datetime.datetime` object as a bind parameter to an `INSERT` or `SELECT WHERE ts_col = %s`.

**Why this priority**: psycopg3 and other drivers send `datetime` objects directly; IRIS rejects them unless converted to plain `'YYYY-MM-DD HH:MM:SS'` strings. This blocks any ORM that uses native date types.

**Independent Test**: Execute `INSERT INTO t (ts_col) VALUES (%s)` with `(datetime.datetime(2025, 1, 1),)` and verify no IRIS error and the row is inserted correctly.

**Acceptance Scenarios**:

1. **Given** a naive `datetime.datetime(2025, 1, 1, 0, 0, 0)` bind parameter, **When** passed through `_normalize_parameters`, **Then** IRIS receives `'2025-01-01 00:00:00.000000'`.
2. **Given** a timezone-aware `datetime.datetime(2025, 1, 1, 8, 0, 0, tzinfo=timezone(+8h))`, **When** normalized, **Then** IRIS receives `'2025-01-01 00:00:00.000000'` (converted to UTC, tzinfo stripped).
3. **Given** an ISO 8601 string `'2025-01-01T00:00:00.000Z'` as a bind parameter, **When** normalized, **Then** IRIS receives `'2025-01-01 00:00:00.000'` (no `T`, no `Z`).
4. **Given** an ISO 8601 string with a non-UTC offset `'2025-01-01T08:00:00+08:00'`, **When** normalized, **Then** IRIS receives `'2025-01-01 00:00:00'` (converted to UTC equivalent).
5. **Given** a `datetime.date(2025, 1, 1)` bind parameter, **When** normalized, **Then** IRIS receives `'2025-01-01'`.

---

### User Story 3 – Direct `SELECT` of POSIXTIME-encoded integer (Priority: P2)

A developer or BI tool runs a raw `SELECT` that returns a TIMESTAMP column stored as a POSIXTIME integer.

**Independent Test**: `SELECT {posixtime_integer} AS ts_col` returns `datetime.datetime`, not `int` or string.

**Acceptance Scenarios**:

1. **Given** a literal POSIXTIME integer in a `SELECT`, **When** the gateway infers its OID via `_infer_type_from_value`, **Then** OID is `1114` and the result is an ISO 8601 string that psycopg decodes as `datetime.datetime`.
2. **Given** a normal integer (outside `[POSIXTIME_OFFSET, POSIXTIME_MAX]`), **When** OID is inferred, **Then** it is `23` (INT4) or `20` (INT8) — no false-positive TIMESTAMP.
3. **Given** a `NULL` value in a TIMESTAMP column, **When** serialized, **Then** `None` is returned with no conversion attempted.

---

### Edge Cases

- `NULL` TIMESTAMP value → return `None` unchanged.
- POSIXTIME integer at or near `POSIXTIME_MAX` → still detected as TIMESTAMP.
- Integer just below `POSIXTIME_OFFSET` → treated as normal integer (no false positive).
- IRIS returns POSIXTIME as a **digit string** (e.g., `'1154692939441846976'`) → `_serialize_value` must detect this and apply `int(value) - POSIXTIME_OFFSET` conversion, **not** `int(value) // 10**9`.
- IRIS returns a pre-decoded datetime string (e.g., `'2026-02-18 17:13:55'`) for OID 1114 → `_serialize_value` must reformat to ISO 8601 with `Z` suffix.
- `datetime.date` (no time component) as bind param → converted to `'YYYY-MM-DD'` string.
- Timezone-aware `datetime` in non-UTC zone → converted to UTC, tzinfo stripped.

---

## Requirements *(mandatory)*

### Functional Requirements

**Bug fixes (must ship together — all are in the TIMESTAMP code path):**

- **FR-001**: `_iris_type_to_pg_oid()` MUST map IRIS JDBC type codes `91` → `1082`, `92` → `1083`, `93` → `1114`, `1091` → `1082`, `1092` → `1083`, `1093` → `1114` in `int_type_mapping`.
- **FR-002**: `_serialize_value()` for OID `1114` MUST add a `str` branch that:
  - If the string is a pure digit string (POSIXTIME encoded as string): apply `unix_us = int(value) - POSIXTIME_OFFSET`, then `datetime(1970,1,1) + timedelta(microseconds=unix_us)`, format as ISO 8601 with `Z`.
  - If the string already looks like a datetime (`'YYYY-MM-DD HH:MM:SS...'`): parse and reformat to `'YYYY-MM-DDTHH:MM:SS.ffffffZ'`.
  - If the string is already ISO 8601 with `Z`: pass through unchanged.
- **FR-003**: `_normalize_parameters` MUST convert `datetime.datetime` objects to `'YYYY-MM-DD HH:MM:SS.ffffff'` strings; timezone-aware values MUST be converted to UTC first, then tzinfo stripped.
- **FR-004**: `_normalize_parameters` MUST convert `datetime.date` objects to `'YYYY-MM-DD'` strings.
- **FR-005**: `_normalize_parameters` MUST strip ISO 8601 `T` separator, trailing `Z`, and timezone offset from string parameters, converting non-UTC offsets to UTC equivalent.
- **FR-006**: `dbapi_executor.py`'s `_convert_value_for_iris` MUST handle `datetime.datetime` and `datetime.date` objects identically to FR-003/FR-004.
- **FR-007**: `POSIXTIME_OFFSET` and `POSIXTIME_MAX` constants MUST be defined in exactly one place (`iris_executor.py`) and imported by `dbapi_executor.py` — no duplication.
- **FR-008**: No compatibility shim or feature flag is required. The OID change (1043→1114 for JDBC `type_code=1093`) is a bug fix; existing tests asserting the old incorrect OID or string return type MUST be updated to expect `1114` and `datetime.datetime`.

### Key Entities

- **`POSIXTIME_OFFSET`** (`1152921504606846976` = 2^60): The fixed integer offset IRIS uses for `%PosixTime`. Module constant in `iris_executor.py`.
- **`POSIXTIME_MAX`** (`POSIXTIME_OFFSET + 7258118400000000`): Upper bound (~year 2200) for detection.
- **Normalization pipeline**: `client param → gateway normalize → IRIS → gateway serialize → wire bytes → client decode`.
- **Affected methods**: `_iris_type_to_pg_oid`, `_serialize_value`, `_normalize_parameters` (in `iris_executor.py`); `_convert_value_for_iris` (in `dbapi_executor.py`).

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: `_iris_type_to_pg_oid(1093)` returns `1114`; `_iris_type_to_pg_oid(1091)` returns `1082`; `_iris_type_to_pg_oid(1092)` returns `1083`.
- **SC-002**: `_serialize_value('1154692939441846976', 1114)` returns `'2026-02-18T17:13:55.000000Z'` (or correct UTC equivalent).
- **SC-003**: `test_returning_timestamp_posixtime_repro` passes end-to-end: `RETURNING` a TIMESTAMP column yields `datetime.datetime` objects with correct date.
- **SC-004**: Inserting with a `datetime.datetime` bind parameter raises no IRIS errors; row is stored correctly.
- **SC-005**: Inserting with a timezone-aware `datetime.datetime` bind parameter stores the UTC-equivalent time.
- **SC-006**: `SELECT {posixtime_integer}` returns `datetime.datetime`, not `int` or `str`.
- **SC-007**: No regression in existing timestamp tests (`tests/protocol/`, `tests/integration/`).
- **SC-008**: Both DBAPI and Embedded executor paths produce identical outputs for timestamp round-trips.
- **SC-009**: `POSIXTIME_OFFSET` appears as a definition in exactly one file.
- **SC-010**: No test is left asserting OID `1043` or a plain `str` return type for a `TIMESTAMP` column — all such tests are updated to reflect the corrected behavior.

---

## Implementation Notes

### Files to Modify

| File | Change |
|---|---|
| `src/iris_pgwire/iris_executor.py` | `_iris_type_to_pg_oid`: add 6 missing JDBC type code entries |
| `src/iris_pgwire/iris_executor.py` | `_serialize_value` OID 1114: add `str` branch (digit string → POSIXTIME formula; datetime string → reformat) |
| `src/iris_pgwire/iris_executor.py` | `_normalize_parameters`: add `datetime.datetime` / `datetime.date` → string branches; UTC conversion for aware datetimes |
| `src/iris_pgwire/dbapi_executor.py` | `_convert_value_for_iris`: add `datetime.datetime` / `datetime.date` handling; import `POSIXTIME_OFFSET` from `iris_executor` |
| `tests/protocol/test_type_mapping_repro.py` | Extend with: type_code 1093 OID test, digit-string POSIXTIME serialization, datetime param normalization, UTC-aware datetime param, boundary tests |

### Fix 1: `_iris_type_to_pg_oid` — add missing codes

```python
int_type_mapping = {
    # ... existing entries ...
    91:   1082,  # IRIS DATE → pg date
    92:   1083,  # IRIS TIME → pg time
    93:   1114,  # IRIS TIMESTAMP → pg timestamp
    1091: 1082,  # IRIS extended DATE → pg date
    1092: 1083,  # IRIS extended TIME → pg time
    1093: 1114,  # IRIS extended TIMESTAMP → pg timestamp
}
```

### Fix 2: `_serialize_value` — add str branch for OID 1114

```python
if type_oid == 1114:
    if isinstance(value, int):
        # ... existing int branch (correct) ...
    elif isinstance(value, dt.datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    elif isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            # POSIXTIME encoded as string — apply correct formula
            unix_us = int(stripped) - POSIXTIME_OFFSET
            ts_obj = dt.datetime(1970, 1, 1) + dt.timedelta(microseconds=unix_us)
            return ts_obj.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        else:
            # Already a datetime string — parse and reformat
            try:
                for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
                            "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%SZ"):
                    try:
                        ts_obj = dt.datetime.strptime(stripped.rstrip("Z"), fmt.rstrip("Z"))
                        return ts_obj.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                    except ValueError:
                        continue
            except Exception:
                pass
            return value  # pass through if unrecognised
```

### Fix 3: `_normalize_parameters` — add datetime branches

```python
if isinstance(param, dt.datetime):
    if param.tzinfo is not None:
        param = param.astimezone(dt.timezone.utc).replace(tzinfo=None)
    new_params[i] = param.strftime("%Y-%m-%d %H:%M:%S.%f")
elif isinstance(param, dt.date):
    new_params[i] = param.strftime("%Y-%m-%d")
elif isinstance(param, str):
    # existing ISO 8601 normalization — also convert non-UTC offsets to UTC
    ...
```

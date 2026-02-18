# Contract: POSIXTIME/TIMESTAMP Fix

**Feature**: `040-fix-posixtime-timestamp`  
**Component**: `IRISExecutor` + `DBAPIExecutor` translation layer  
**Contract File**: `specs/040-fix-posixtime-timestamp/contracts/timestamp-fix-contract.md`  
**Test File**: `tests/contract/test_timestamp_fix_contract.py`

---

## Contract: `_iris_type_to_pg_oid(type_code: int) -> int`

### Preconditions
- `type_code` is a non-negative integer returned by an IRIS DBAPI cursor `description` entry.

### Postconditions

| Input `type_code` | Required Output OID | Meaning |
|---|---|---|
| `91` | `1082` | DATE |
| `92` | `1083` | TIME |
| `93` | `1114` | TIMESTAMP |
| `1091` | `1082` | DATE (IRIS extended) |
| `1092` | `1083` | TIME (IRIS extended) |
| `1093` | `1114` | TIMESTAMP (IRIS extended) |
| `9` | `1082` | DATE (IRIS internal) — pre-existing |
| `10` | `1114` | TIMESTAMP (IRIS internal) — pre-existing |
| any other int | `1043` | VARCHAR (default fallback) |

### Invariants
- Return value is always a positive integer (valid PostgreSQL OID).
- Method is pure (no side effects).

---

## Contract: `_serialize_value(value, type_oid: int) -> Any`

### For `type_oid == 1114` (TIMESTAMP)

| Input `value` type | Input example | Required output |
|---|---|---|
| `None` | `None` | `None` |
| `int` ≥ `POSIXTIME_OFFSET` | `1154692939441846976` | ISO 8601 string `'YYYY-MM-DDTHH:MM:SS.ffffffZ'` |
| `int` < `POSIXTIME_OFFSET` | `1735689600000000` | ISO 8601 string (PG epoch: 2000-01-01 + microseconds) |
| `str` all-digits (POSIXTIME as str) | `'1154692939441846976'` | Same as int ≥ `POSIXTIME_OFFSET` — apply `int(value) - POSIXTIME_OFFSET` |
| `str` datetime string | `'2025-01-01 00:00:00'` | `'2025-01-01T00:00:00.000000Z'` |
| `str` already ISO 8601 with Z | `'2025-01-01T00:00:00.000000Z'` | Pass through unchanged |
| `datetime.datetime` | `datetime(2025,1,1,0,0,0)` | `'2025-01-01T00:00:00.000000Z'` |
| unrecognised str | `'not-a-date'` | Pass through unchanged (no exception) |

### Invariants
- Never raises an exception (degrades gracefully for unrecognised input).
- Output for valid POSIXTIME inputs is always a valid ISO 8601 string ending in `Z`.
- `POSIXTIME_OFFSET` subtraction formula (not division) used for all digit-string inputs.

---

## Contract: `_normalize_parameters(params) -> list`

### For each parameter element

| Input type | Condition | Required output |
|---|---|---|
| `None` | — | `None` (unchanged) |
| `datetime.datetime` | naive | `'YYYY-MM-DD HH:MM:SS.ffffff'` string |
| `datetime.datetime` | UTC-aware | `'YYYY-MM-DD HH:MM:SS.ffffff'` (UTC, tzinfo stripped) |
| `datetime.datetime` | offset-aware (e.g. +8h) | `'YYYY-MM-DD HH:MM:SS.ffffff'` (UTC equivalent) |
| `datetime.date` | — | `'YYYY-MM-DD'` string |
| `str` | ISO 8601 with `T` + `Z` | `'YYYY-MM-DD HH:MM:SS[.fff]'` (T→space, Z removed) |
| `str` | ISO 8601 with `T` + non-UTC offset | `'YYYY-MM-DD HH:MM:SS[.fff]'` (converted to UTC) |
| `str` | Already plain datetime | Unchanged |
| `int` | In PG timestamp range | Converted to IRIS datetime string (pre-existing behavior) |
| `list` | — | IRIS vector string `[x,y,z]` (pre-existing behavior) |
| any other | — | Unchanged |

### Invariants
- Output is always a `list` of the same length as input.
- No exceptions raised for any input type.
- `datetime.datetime` checked **before** `str` (datetime is not a str, but order must be explicit to avoid future bugs).

---

## Contract: `DBAPIExecutor._convert_value_for_iris(value) -> Any`

Identical postconditions to `_normalize_parameters` for a single value (not a list):

| Input | Required output |
|---|---|
| `datetime.datetime` (naive) | `'YYYY-MM-DD HH:MM:SS.ffffff'` |
| `datetime.datetime` (aware) | UTC-converted `'YYYY-MM-DD HH:MM:SS.ffffff'` |
| `datetime.date` | `'YYYY-MM-DD'` |
| ISO 8601 str | Plain datetime str (same as `_normalize_parameters`) |
| anything else | Unchanged |

### Parity Invariant
For any input value `v` of type `datetime.datetime` or `datetime.date`, `DBAPIExecutor._convert_value_for_iris(v)` MUST produce the same string as `IRISExecutor._normalize_parameters([v])[0]`.

---

## Regression Contract

The following existing behavior MUST NOT change:

- `_iris_type_to_pg_oid(4) == 23` (INT4)
- `_iris_type_to_pg_oid(12) == 1043` (VARCHAR)
- `_iris_type_to_pg_oid(9) == 1082` (DATE — pre-existing)
- `_iris_type_to_pg_oid(10) == 1114` (TIMESTAMP — pre-existing)
- `_serialize_value(None, 1114) is None`
- `_serialize_value(42, 23) == 42` (non-timestamp OID passes through)
- `_normalize_parameters([1735689600000000])` → IRIS datetime string (PG timestamp int conversion)
- `_normalize_parameters([[1.0, 2.0, 3.0]])` → `['[1.0,2.0,3.0]']` (vector conversion)

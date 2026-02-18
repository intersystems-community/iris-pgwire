# Quickstart: Fix POSIXTIME/TIMESTAMP Handling

**Branch**: `040-fix-posixtime-timestamp`

## What This Fixes

Three bugs that cause TIMESTAMP columns to be mishandled between IRIS and PostgreSQL clients:

| Bug | Symptom | Fix Location |
|---|---|---|
| Missing JDBC type codes 1091/1092/1093 | Timestamps arrive as plain strings in Drizzle/postgres.js | `iris_executor.py` → `_iris_type_to_pg_oid()` |
| String POSIXTIME not decoded | Raw integer strings returned instead of dates | `iris_executor.py` → `_serialize_value()` |
| datetime objects rejected by IRIS | IRIS errors when binding native Python datetimes | `iris_executor.py` + `dbapi_executor.py` → normalization methods |

---

## Running the Tests

### Contract tests (no IRIS required — fast)

```bash
cd /Users/tdyar/ws/iris-pgwire-gh
pytest tests/contract/test_timestamp_fix_contract.py -v
```

### Protocol regression tests (requires IRIS container)

```bash
pytest tests/protocol/test_type_mapping_repro.py -v
```

### Full test suite

```bash
cd src
pytest
```

---

## Making the Changes

All source changes are in two files. Apply in this order:

### 1. `src/iris_pgwire/iris_executor.py`

**`_iris_type_to_pg_oid()`** (~line 3922) — add to `int_type_mapping`:
```python
91:   1082,   # IRIS DATE (standard JDBC)
92:   1083,   # IRIS TIME (standard JDBC)
93:   1114,   # IRIS TIMESTAMP (standard JDBC)
1091: 1082,   # IRIS extended DATE
1092: 1083,   # IRIS extended TIME
1093: 1114,   # IRIS extended TIMESTAMP
```

**`_serialize_value()`** (~line 527) — add `str` branch inside `if type_oid == 1114:`:
```python
elif isinstance(value, str):
    stripped = value.strip()
    if stripped.isdigit():
        unix_us = int(stripped) - POSIXTIME_OFFSET
        ts_obj = dt.datetime(1970, 1, 1) + dt.timedelta(microseconds=unix_us)
        return ts_obj.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    else:
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                ts_obj = dt.datetime.strptime(stripped.rstrip("Z"), fmt)
                return ts_obj.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            except ValueError:
                continue
        return value
```

**`_normalize_parameters()`** (~line 755) — add datetime handling before the `isinstance(param, str)` branch:
```python
if isinstance(param, dt.datetime):
    if param.tzinfo is not None:
        param = param.astimezone(dt.timezone.utc).replace(tzinfo=None)
    new_params[i] = param.strftime("%Y-%m-%d %H:%M:%S.%f")
elif isinstance(param, dt.date):
    new_params[i] = param.strftime("%Y-%m-%d")
elif isinstance(param, str):
    # existing ISO 8601 normalization + extend to handle non-UTC offsets → UTC
    ...
```

### 2. `src/iris_pgwire/dbapi_executor.py`

At top of file, add import:
```python
from iris_pgwire.iris_executor import POSIXTIME_OFFSET, POSIXTIME_MAX  # noqa
```

In `_convert_value_for_iris()`, add datetime handling before existing `str` branch:
```python
if isinstance(value, dt.datetime):
    if value.tzinfo is not None:
        value = value.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return value.strftime("%Y-%m-%d %H:%M:%S.%f")
elif isinstance(value, dt.date):
    return value.strftime("%Y-%m-%d")
elif isinstance(value, str):
    # existing normalization (extend for non-UTC offset → UTC)
    ...
```

---

## Verifying the Fix

After implementation, these assertions should all pass:

```python
from iris_pgwire.iris_executor import IRISExecutor, POSIXTIME_OFFSET

executor = IRISExecutor(...)

# Bug 1 — OID mapping
assert executor._iris_type_to_pg_oid(1093) == 1114
assert executor._iris_type_to_pg_oid(1091) == 1082

# Bug 2 — string POSIXTIME
result = executor._serialize_value('1154692939441846976', 1114)
assert result == '2026-02-18T17:13:55.000000Z'

# Bug 3 — datetime normalization
import datetime as dt
normalized = executor._normalize_parameters([dt.datetime(2025, 1, 1, 8, 0, 0,
                                              tzinfo=dt.timezone(dt.timedelta(hours=8)))])
assert normalized == ['2025-01-01 00:00:00.000000']
```

---

## Existing Test Updates (FR-008)

Search for tests asserting the now-incorrect behavior:
```bash
grep -rn "1043.*timestamp\|type_oid.*1043\|OID.*1043" tests/ --include="*.py"
```

Any test asserting OID `1043` for a TIMESTAMP column is itself testing the bug. Update it to assert `1114` and `datetime.datetime`.

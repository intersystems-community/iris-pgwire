# Implementation Plan: Fix POSIXTIME/TIMESTAMP Handling

**Branch**: `040-fix-posixtime-timestamp` | **Date**: 2026-02-18 | **Spec**: `specs/040-fix-posixtime-timestamp/spec.md`

## Summary

Three confirmed bugs in the IRIS PGWire gateway's timestamp pipeline prevent ORMs (Drizzle, Prisma, SQLAlchemy) from receiving correctly-typed `datetime` values. The fixes are localized to two files (`iris_executor.py`, `dbapi_executor.py`) and one test file:

1. **Bug 1**: `_iris_type_to_pg_oid()` missing IRIS JDBC extended type codes `1091`/`1092`/`1093` → TIMESTAMP columns sent as VARCHAR (OID 1043) to clients.
2. **Bug 2**: `_serialize_value()` has no `str` branch for OID 1114 → POSIXTIME values returned as digit strings pass through unconverted.
3. **Bug 3**: `_normalize_parameters()` doesn't handle `datetime.datetime`/`datetime.date` objects → IRIS rejects native Python datetime bind parameters.
4. **Structural gap**: `dbapi_executor.py` has the same `datetime` normalization gap and duplicates POSIXTIME constant knowledge.

No new entities, no new APIs, no external dependencies. All changes are internal to the gateway translation layer.

---

## Technical Context

**Language/Version**: Python 3.11+  
**Primary Dependencies**: `intersystems-irispython`, `psycopg[binary]`, `iris-devtester`, `structlog`  
**Storage**: InterSystems IRIS (via embedded Python and DBAPI pool)  
**Testing**: `pytest` — integration tests against live IRIS container via `iris-devtester`; contract tests in `tests/contract/`; protocol regression tests in `tests/protocol/`  
**Target Platform**: Linux server (IRIS container, embedded Python)  
**Performance Goals**: No latency regression; fix is O(1) string/int conversion per value  
**Constraints**: Must not add new dependencies; no feature flags; changes must not break existing passing tests  
**Scale/Scope**: Single gateway process; affects every TIMESTAMP column in every query

---

## Constitution Check

*Constitution template is unpopulated for this project. Applying implicit principles from AGENTS.md and observed codebase patterns.*

| Gate | Status | Notes |
|---|---|---|
| Tests run against live IRIS (SKIP_IRIS_TESTS defaults false) | ✅ PASS | Existing conftest enforces this |
| Port resolution via `iris-devtester` (no hardcoded ports) | ✅ PASS | No new fixtures needed |
| No mocks for IRIS behavior | ✅ PASS | All new tests use `pgwire_client` + `iris_connection` fixtures |
| No new external dependencies | ✅ PASS | Fix uses only stdlib `datetime` |
| Existing tests must not regress | ✅ PASS | SC-007 enforces this; any test asserting OID 1043 for TIMESTAMP is itself a bug and must be updated (FR-008) |
| Constants defined once (DRY) | ✅ PASS | FR-007: `POSIXTIME_OFFSET` imported from `iris_executor.py` in `dbapi_executor.py` |

**Constitution Check: PASSED — no violations.**

---

## Project Structure

### Documentation (this feature)

```text
specs/040-fix-posixtime-timestamp/
├── plan.md              ← this file
├── research.md          ← Phase 0 output
├── data-model.md        ← Phase 1 output (minimal — no new entities)
├── quickstart.md        ← Phase 1 output
├── contracts/
│   └── timestamp-fix-contract.md   ← Phase 1 output
└── tasks.md             ← Phase 2 output (/speckit.tasks — NOT created here)
```

### Source Code (affected files only)

```text
src/iris_pgwire/
├── iris_executor.py          # Bugs 1, 2, 3: _iris_type_to_pg_oid, _serialize_value, _normalize_parameters
└── dbapi_executor.py         # Structural gap: _convert_value_for_iris + import POSIXTIME_OFFSET

tests/
├── protocol/
│   └── test_type_mapping_repro.py   # Extend with new test cases
└── contract/
    └── test_timestamp_fix_contract.py   # New: unit-level contract tests (no IRIS required)
```

---

## Complexity Tracking

No constitution violations. No complexity justification required.

---

## Phase 0: Research

*See `research.md` for full findings. Summary:*

All decisions pre-resolved in spec. No unknowns requiring external research:
- POSIXTIME formula: confirmed `unix_us = int(value) - POSIXTIME_OFFSET` (existing int branch is correct; string branch must match).
- JDBC type codes: confirmed `1091/1092/1093` from IRIS JDBC documentation and bug report.
- UTC conversion: decided in clarification session — convert to UTC then strip tzinfo.
- Backward compatibility: no shim (FR-008); incorrect-behavior tests must be corrected.

---

## Phase 1: Design & Contracts

### Change Inventory

All changes are surgical, localized, and independently testable.

#### Change 1 — `_iris_type_to_pg_oid()` (iris_executor.py ~line 3922)

Add 6 entries to `int_type_mapping`:

```python
91:   1082,   # IRIS DATE (standard JDBC) → pg date
92:   1083,   # IRIS TIME (standard JDBC) → pg time
93:   1114,   # IRIS TIMESTAMP (standard JDBC) → pg timestamp
1091: 1082,   # IRIS extended DATE → pg date
1092: 1083,   # IRIS extended TIME → pg time
1093: 1114,   # IRIS extended TIMESTAMP → pg timestamp
```

**Risk**: Low — dict lookup, no logic change.  
**Test**: Unit assertion `_iris_type_to_pg_oid(1093) == 1114`.

---

#### Change 2 — `_serialize_value()` OID 1114 str branch (iris_executor.py ~line 527)

Insert `elif isinstance(value, str):` branch between existing `int` and `datetime` branches:

```python
elif isinstance(value, str):
    stripped = value.strip()
    if stripped.isdigit():
        # POSIXTIME encoded as digit string — correct formula: subtract offset
        unix_us = int(stripped) - POSIXTIME_OFFSET
        ts_obj = dt.datetime(1970, 1, 1) + dt.timedelta(microseconds=unix_us)
        return ts_obj.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    else:
        # Pre-decoded datetime string from IRIS driver — parse and reformat
        for fmt in (
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
        ):
            try:
                ts_obj = dt.datetime.strptime(stripped.rstrip("Z"), fmt)
                return ts_obj.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            except ValueError:
                continue
        return value  # unrecognised format — pass through
```

**Risk**: Low — new branch, existing int/datetime branches unchanged.  
**Test**: `_serialize_value('1154692939441846976', 1114)` → `'2026-02-18T17:13:55.000000Z'`.

---

#### Change 3 — `_normalize_parameters()` datetime branches (iris_executor.py ~line 755)

Insert `datetime.datetime` and `datetime.date` handling **before** the existing `isinstance(param, str)` branch (order matters — `datetime` is not a `str`):

```python
if isinstance(param, dt.datetime):
    # Convert to UTC if timezone-aware, then strip tzinfo
    if param.tzinfo is not None:
        param = param.astimezone(dt.timezone.utc).replace(tzinfo=None)
    new_params[i] = param.strftime("%Y-%m-%d %H:%M:%S.%f")
elif isinstance(param, dt.date):
    new_params[i] = param.strftime("%Y-%m-%d")
elif isinstance(param, str):
    # ... existing ISO 8601 normalization (extend to handle non-UTC offsets → UTC) ...
```

For the existing `str` branch regex, extend to capture and apply timezone offset:

```python
ts_match = re.match(
    r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2}(?:\.\d+)?)"
    r"(Z|([+-])(\d{2}):?(\d{2}))?$",
    param,
)
if ts_match:
    date_part, time_part = ts_match.group(1), ts_match.group(2)
    tz_raw = ts_match.group(3)
    if tz_raw and tz_raw != "Z" and tz_raw is not None:
        # Non-UTC offset: convert to UTC
        sign, hh, mm = ts_match.group(4), int(ts_match.group(5)), int(ts_match.group(6))
        offset_mins = (hh * 60 + mm) * (1 if sign == "+" else -1)
        naive = dt.datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %H:%M:%S.%f"
                                     if "." in time_part else "%Y-%m-%d %H:%M:%S")
        utc = naive - dt.timedelta(minutes=offset_mins)
        new_params[i] = utc.strftime("%Y-%m-%d %H:%M:%S.%f" if "." in time_part else "%Y-%m-%d %H:%M:%S")
    else:
        new_params[i] = f"{date_part} {time_part}"
```

**Risk**: Medium — modifying an existing regex path. Must not regress existing UTC/Z string tests.  
**Test**: Parametrized over naive datetime, aware datetime, ISO string with Z, ISO string with +08:00.

---

#### Change 4 — `dbapi_executor.py` parity (dbapi_executor.py ~line 130)

1. Import `POSIXTIME_OFFSET` from `iris_executor` at module top (after existing imports).
2. Replace `_convert_value_for_iris` `str`-only body with identical logic to Change 3:

```python
from iris_pgwire.iris_executor import POSIXTIME_OFFSET  # noqa: F401 (for parity)

def _convert_value_for_iris(self, value: Any) -> Any:
    if isinstance(value, dt.datetime):
        if value.tzinfo is not None:
            value = value.astimezone(dt.timezone.utc).replace(tzinfo=None)
        return value.strftime("%Y-%m-%d %H:%M:%S.%f")
    elif isinstance(value, dt.date):
        return value.strftime("%Y-%m-%d")
    elif isinstance(value, str):
        # ... existing regex normalization (same extended version as Change 3) ...
    return value
```

**Risk**: Low — additive; existing str branch preserved and extended.  
**Test**: Parity test running same scenarios through both executors.

---

### Test Plan

#### New: `tests/contract/test_timestamp_fix_contract.py` (no IRIS required)

Pure unit tests — no live connection needed. Fast, always-on.

| Test | Assertion |
|---|---|
| `test_oid_mapping_1093` | `_iris_type_to_pg_oid(1093) == 1114` |
| `test_oid_mapping_1091` | `_iris_type_to_pg_oid(1091) == 1082` |
| `test_oid_mapping_1092` | `_iris_type_to_pg_oid(1092) == 1083` |
| `test_serialize_digit_string_posixtime` | `_serialize_value('1154692939441846976', 1114) == '2026-02-18T17:13:55.000000Z'` |
| `test_serialize_datetime_string` | `_serialize_value('2025-01-01 00:00:00', 1114) == '2025-01-01T00:00:00.000000Z'` |
| `test_serialize_iso_passthrough` | `_serialize_value('2025-01-01T00:00:00.000000Z', 1114)` returns same string |
| `test_serialize_none` | `_serialize_value(None, 1114) is None` |
| `test_normalize_naive_datetime` | `datetime(2025,1,1)` → `'2025-01-01 00:00:00.000000'` |
| `test_normalize_aware_datetime_utc_plus8` | `datetime(2025,1,1,8,tzinfo=+8h)` → `'2025-01-01 00:00:00.000000'` |
| `test_normalize_date` | `date(2025,1,1)` → `'2025-01-01'` |
| `test_normalize_iso_z_string` | `'2025-01-01T00:00:00Z'` → `'2025-01-01 00:00:00'` |
| `test_normalize_iso_offset_string` | `'2025-01-01T08:00:00+08:00'` → `'2025-01-01 00:00:00'` |
| `test_posixtime_boundary_max` | `_serialize_value(POSIXTIME_MAX, 1114)` returns valid ISO string |
| `test_no_false_positive_below_offset` | `_infer_type_from_value(POSIXTIME_OFFSET - 1)` → not 1114 |

#### Extend: `tests/protocol/test_type_mapping_repro.py` (requires IRIS)

- `test_returning_timestamp_posixtime_repro` — already exists; must pass after Bug 1+2 fixed.
- Add `test_datetime_bind_param_insert` — insert with native `datetime` object.
- Add `test_aware_datetime_bind_param` — insert with UTC+8 aware `datetime`.
- Add `test_date_bind_param` — insert with `datetime.date`.
- Add `test_dbapi_executor_datetime_parity` — run same insert/select through DBAPI path.

#### Update: any existing test asserting OID 1043 for TIMESTAMP (FR-008 / SC-010)

Search: `grep -rn "1043.*timestamp\|varchar.*timestamp\|OID.*1043" tests/`

---

## Execution Order (Sequential — dependencies between changes)

```
1. Change 1 (OID mapping) — standalone, no deps
2. Change 2 (serialize str branch) — depends on POSIXTIME_OFFSET (already defined)
3. Change 3 (normalize datetime) — standalone
4. Change 4 (dbapi parity) — depends on Change 3 logic being stable
5. Contract tests (test_timestamp_fix_contract.py) — can be written before impl (TDD)
6. Protocol tests extension — requires IRIS + all 4 changes complete
7. Scan & update any broken existing tests (FR-008)
```

All 4 source changes are in at most 2 files. Changes 1–3 are independent within `iris_executor.py` and can be made in a single edit pass.

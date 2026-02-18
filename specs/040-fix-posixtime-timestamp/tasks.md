# Tasks: Fix POSIXTIME/TIMESTAMP Handling

**Branch**: `040-fix-posixtime-timestamp`  
**Input**: Design documents from `specs/040-fix-posixtime-timestamp/`  
**Prerequisites**: plan.md ✓ spec.md ✓ research.md ✓ data-model.md ✓ contracts/ ✓ quickstart.md ✓

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story this task belongs to (US1, US2, US3)
- All paths are relative to repo root

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Write the contract test file and scan for existing broken assertions before touching source code. Establishes the TDD baseline — tests must fail before fixes are applied.

- [ ] T001 Write contract test file `tests/contract/test_timestamp_fix_contract.py` with all 14 unit tests defined in `specs/040-fix-posixtime-timestamp/contracts/timestamp-fix-contract.md` (no IRIS required; tests must FAIL at this point)
- [ ] T002 Scan for existing tests that assert OID `1043` for TIMESTAMP columns: run `grep -rn "1043" tests/ --include="*.py"` and record any files that need updating after fixes land

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Move the `POSIXTIME_OFFSET` / `POSIXTIME_MAX` constants to their canonical home and wire up the import in `dbapi_executor.py`. This ensures the single-definition invariant (FR-007 / SC-009) holds before any fix is applied to either executor.

**⚠️ CRITICAL**: T003 must complete before T006 (dbapi changes depend on the clean import).

- [ ] T003 Verify `POSIXTIME_OFFSET` and `POSIXTIME_MAX` are defined at module level in `src/iris_pgwire/iris_executor.py` (lines 46–47) and add the import line `from iris_pgwire.iris_executor import POSIXTIME_OFFSET, POSIXTIME_MAX` near the top of `src/iris_pgwire/dbapi_executor.py` (after existing imports, before class definition)

**Checkpoint**: Constants defined once; both executors share the same values. `SC-009` satisfied.

---

## Phase 3: User Story 1 – Round-trip TIMESTAMP via RETURNING (Priority: P1) 🎯 MVP

**Goal**: ORM clients (Drizzle, Prisma, psycopg3) receive `datetime.datetime` objects—not strings or integers—when querying TIMESTAMP columns via `RETURNING` or plain `SELECT`.

**Independent Test**: Run `pytest tests/contract/test_timestamp_fix_contract.py::test_oid_mapping_1093 tests/contract/test_timestamp_fix_contract.py::test_serialize_digit_string_posixtime -v` (no IRIS needed). Then run `pytest tests/protocol/test_type_mapping_repro.py::test_returning_timestamp_posixtime_repro -v` (requires IRIS).

### Bug 1 — Missing JDBC type codes

- [ ] T004 [US1] In `src/iris_pgwire/iris_executor.py`, locate `_iris_type_to_pg_oid()` (~line 3922) and add the following 6 entries to `int_type_mapping` immediately after the existing `10: 1114` entry:
  ```python
  91:   1082,   # IRIS DATE (standard JDBC) → pg date
  92:   1083,   # IRIS TIME (standard JDBC) → pg time
  93:   1114,   # IRIS TIMESTAMP (standard JDBC) → pg timestamp
  1091: 1082,   # IRIS extended DATE → pg date
  1092: 1083,   # IRIS extended TIME → pg time
  1093: 1114,   # IRIS extended TIMESTAMP → pg timestamp
  ```

### Bug 2 — String POSIXTIME not decoded

- [ ] T005 [US1] In `src/iris_pgwire/iris_executor.py`, locate `_serialize_value()` (~line 527). Inside the `if type_oid == 1114:` block, add an `elif isinstance(value, str):` branch **after** the existing `elif isinstance(value, dt.datetime):` branch:
  ```python
  elif isinstance(value, str):
      stripped = value.strip()
      if stripped.isdigit():
          # POSIXTIME encoded as digit string — correct formula (NOT // 10**9)
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
          return value  # unrecognised format — pass through unchanged
  ```

### Validation

- [ ] T006 [US1] Run `pytest tests/contract/test_timestamp_fix_contract.py -k "oid or serialize" -v` and confirm T004–T005 tests pass; run `pytest tests/protocol/test_type_mapping_repro.py::test_returning_timestamp_posixtime_repro -v` against IRIS and confirm it passes

---

## Phase 4: User Story 2 – Inbound `datetime` Parameter Normalization (Priority: P1)

**Goal**: Native Python `datetime.datetime` and `datetime.date` bind parameters are silently converted to the plain string format IRIS requires, with timezone-aware values converted to UTC.

**Independent Test**: Run `pytest tests/contract/test_timestamp_fix_contract.py -k "normalize" -v` (no IRIS). Then insert a row using a native `datetime` object via psycopg and confirm no IRIS error.

### Bug 3 — datetime objects not normalized (iris_executor)

- [ ] T007 [US2] In `src/iris_pgwire/iris_executor.py`, locate `_normalize_parameters()` (~line 755). The loop currently starts with `if isinstance(param, int)`. Add `datetime` and `date` handling as the **first two branches** of the per-parameter `if/elif` chain (before the existing `int` and `str` checks):
  ```python
  if isinstance(param, dt.datetime):
      # datetime MUST be checked before date (datetime is a subclass of date)
      if param.tzinfo is not None:
          param = param.astimezone(dt.timezone.utc).replace(tzinfo=None)
      new_params[i] = param.strftime("%Y-%m-%d %H:%M:%S.%f")
  elif isinstance(param, dt.date):
      new_params[i] = param.strftime("%Y-%m-%d")
  elif isinstance(param, int) and MIN_TIMESTAMP < param < MAX_TIMESTAMP:
      # ... existing int branch unchanged ...
  elif isinstance(param, str):
      # extend existing regex to also handle non-UTC offsets → UTC conversion:
      ts_match = re.match(
          r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2}(?:\.\d+)?)"
          r"(Z|([+-])(\d{2}):?(\d{2}))?$",
          param,
      )
      if ts_match:
          date_part, time_part = ts_match.group(1), ts_match.group(2)
          tz_sign, tz_hh, tz_mm = ts_match.group(4), ts_match.group(5), ts_match.group(6)
          if tz_sign and tz_hh:
              # Non-UTC offset: convert to UTC
              offset_mins = (int(tz_hh) * 60 + int(tz_mm or 0)) * (1 if tz_sign == "+" else -1)
              fmt = "%Y-%m-%d %H:%M:%S.%f" if "." in time_part else "%Y-%m-%d %H:%M:%S"
              naive = dt.datetime.strptime(f"{date_part} {time_part}", fmt)
              utc = naive - dt.timedelta(minutes=offset_mins)
              new_params[i] = utc.strftime(fmt)
          else:
              new_params[i] = f"{date_part} {time_part}"
  elif isinstance(param, list):
      # ... existing list/vector branch unchanged ...
  ```

### Structural gap — dbapi_executor parity

- [ ] T008 [P] [US2] In `src/iris_pgwire/dbapi_executor.py`, locate `_convert_value_for_iris()` (~line 138). Add `datetime` and `date` handling as the first two branches (before the existing `str` check), plus extend the str branch for non-UTC offset handling — identical logic to T007:
  ```python
  def _convert_value_for_iris(self, value: Any) -> Any:
      if isinstance(value, dt.datetime):
          if value.tzinfo is not None:
              value = value.astimezone(dt.timezone.utc).replace(tzinfo=None)
          return value.strftime("%Y-%m-%d %H:%M:%S.%f")
      elif isinstance(value, dt.date):
          return value.strftime("%Y-%m-%d")
      elif isinstance(value, str):
          ts_match = re.match(
              r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2}(?:\.\d+)?)"
              r"(Z|([+-])(\d{2}):?(\d{2}))?$",
              value,
          )
          if ts_match:
              date_part, time_part = ts_match.group(1), ts_match.group(2)
              tz_sign, tz_hh, tz_mm = ts_match.group(4), ts_match.group(5), ts_match.group(6)
              if tz_sign and tz_hh:
                  offset_mins = (int(tz_hh) * 60 + int(tz_mm or 0)) * (1 if tz_sign == "+" else -1)
                  fmt = "%Y-%m-%d %H:%M:%S.%f" if "." in time_part else "%Y-%m-%d %H:%M:%S"
                  naive = dt.datetime.strptime(f"{date_part} {time_part}", fmt)
                  utc = naive - dt.timedelta(minutes=offset_mins)
                  return utc.strftime(fmt)
              return f"{date_part} {time_part}"
      return value
  ```

### Validation

- [ ] T009 [US2] Run `pytest tests/contract/test_timestamp_fix_contract.py -k "normalize" -v` — all normalize contract tests pass. Run `pytest tests/protocol/test_type_mapping_repro.py -k "datetime_bind or date_bind or parity" -v` against IRIS — no IRIS rejection errors.

---

## Phase 5: User Story 3 – Direct `SELECT` of POSIXTIME Integer (Priority: P2)

**Goal**: Any `SELECT` that returns a TIMESTAMP column (as a POSIXTIME integer, digit string, or decoded string) delivers a `datetime.datetime` to the client — no raw integers or unconverted strings.

**Independent Test**: Run `pytest tests/contract/test_timestamp_fix_contract.py -k "boundary or false_positive or passthrough" -v`. Then run `pytest tests/protocol/test_type_mapping_repro.py -v` for the full suite.

- [ ] T010 [US3] Extend `tests/protocol/test_type_mapping_repro.py` with three new test functions:
  - `test_datetime_bind_param_insert`: inserts using `datetime.datetime(2025, 1, 1)` as bind param; asserts row stored and readable back as `datetime.datetime`.
  - `test_aware_datetime_bind_param`: inserts using `datetime.datetime(2025, 1, 1, 8, tzinfo=timezone(timedelta(hours=8)))` as bind param; asserts stored value equals `2025-01-01 00:00:00` (UTC).
  - `test_date_bind_param`: inserts using `datetime.date(2025, 6, 15)` into a `DATE` column; asserts readable back as `datetime.date`.

- [ ] T011 [US3] Verify POSIXTIME integer round-trip in `tests/protocol/test_type_mapping_repro.py`: the existing `test_returning_timestamp_posixtime_repro` scenario 2 (`SELECT {iris_posixtime} AS ts_col`) must return `datetime.datetime` — add an explicit assertion if not already present; confirm `row[0]` is `datetime.datetime` with `year == 2025`.

- [ ] T012 [US3] Run `pytest tests/protocol/test_type_mapping_repro.py -v` (all tests including new ones) against IRIS — confirm all pass and no false-positive TIMESTAMP detection for plain integers outside `[POSIXTIME_OFFSET, POSIXTIME_MAX]`.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Regression safety, test cleanup, and final verification.

- [ ] T013 [P] Scan for existing tests asserting the now-incorrect OID `1043` for TIMESTAMP columns (flagged in T002). For each found: update assertion to `1114` and update any `str` type assertions to `datetime.datetime`. Run updated tests to confirm they pass.

- [ ] T014 [P] Run the full contract test suite: `pytest tests/contract/ -v` — confirm no regressions in `test_dbapi_executor_contract.py` or other contract tests.

- [ ] T015 Run the full test suite from `src/`: `cd src && pytest` — confirm zero regressions across `tests/protocol/`, `tests/integration/`, `tests/contract/`. Note: integration tests require a live IRIS container via `iris-devtester`.

- [ ] T016 [P] Verify constant deduplication (SC-009): run `grep -rn "POSIXTIME_OFFSET\s*=" src/ --include="*.py"` — must show exactly one definition (in `iris_executor.py`); `dbapi_executor.py` must show only an `import` line, not a second assignment.

---

## Dependencies

```
T001 (contract tests, failing)
T002 (scan for broken assertions)
  ↓
T003 (constant import in dbapi_executor) ← required before T008
  ↓
T004 (OID mapping) ──────────────────────────┐
T005 (serialize str branch)                 │  both independent, same file
  ↓                                          │
T006 (validate US1) ────────────────────────┘

T007 (normalize iris_executor) ─────────────┐
T008 (normalize dbapi_executor) [P with T007]┘ independent files
  ↓
T009 (validate US2)

T010 (new protocol tests)  ─────────────────┐
T011 (posixtime round-trip assertion)        │  independent additions
  ↓                                          │
T012 (validate US3) ────────────────────────┘

T013 [P] (fix broken existing tests)
T014 [P] (contract suite)
  ↓
T015 (full suite)
T016 [P] (constant dedup check)
```

---

## Parallel Execution Opportunities

### Within Phase 3 (US1)
- T004 and T005 touch the same file (`iris_executor.py`) — implement in one edit pass to avoid conflicts.

### Within Phase 4 (US2)
- **T007** (`iris_executor.py`) and **T008** (`dbapi_executor.py`) are in different files → implement in parallel.

### Within Phase 6
- **T013**, **T014**, **T016** are all independent → run in parallel.

---

## Implementation Strategy

### MVP Scope (P1 Stories Only)
Complete T001–T009 to ship the two highest-impact fixes:
- ORM `RETURNING` works (US1): Drizzle/Prisma receive `datetime` not string.
- Native datetime bind params work (US2): No IRIS rejection errors.

### Full Scope
Add T010–T012 (US3) for complete POSIXTIME round-trip coverage, then T013–T016 for regression safety.

---

## Summary

| Phase | Tasks | Parallel | Story |
|---|---|---|---|
| 1 – Setup | T001–T002 | — | Pre-TDD baseline |
| 2 – Foundational | T003 | — | Constant DRY |
| 3 – US1 RETURNING | T004–T006 | T004+T005 same pass | Bug 1 + Bug 2 |
| 4 – US2 datetime params | T007–T009 | T007 ∥ T008 | Bug 3 + DBAPI parity |
| 5 – US3 direct SELECT | T010–T012 | T010 ∥ T011 | Full round-trip |
| 6 – Polish | T013–T016 | T013 ∥ T014 ∥ T016 | Regression safety |

**Total tasks**: 16  
**Parallelizable**: T007∥T008, T013∥T014∥T016  
**MVP cutoff**: After T009 (P1 stories complete)  
**IRIS required**: T006, T009, T012, T015 (all validation tasks against live container)

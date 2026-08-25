# Tasks: psycopg3 Pipeline Mode + executemany Support

**Input**: Design documents from `specs/049-pipeline-mode-executemany/`
**Prerequisites**: spec.md ✅, plan.md ✅
**Constitution note**: Tests must use real IRIS (no mocks). Unit tests cover pure-Python logic only (stripping, regex). All executor + protocol behavior tested via skip-guarded integration tests with real psycopg3 + real IRIS.

---

## Phase 1: Source Audit (inline findings — no artifacts needed)

Research findings (already captured in plan.md Research Notes):
- `execute_many()` in `iris_executor.py:1309` — ON CONFLICT strip added in 048; per-row duplicate suppression NOT yet implemented.
- `flush_batch()` in `protocol.py:2393` — flushes DML batch on Sync ✅.
- `handle_sync_message()` in `protocol.py:3532` — calls `flush_batch()` before ReadyForQuery ✅.
- `handle_flush_message()` in `protocol.py:3597` — does NOT send ReadyForQuery ✅ (already correct).
- `_execute_many_inline_fallback()` in `iris_executor.py:1500` — iterates rows one-by-one; wrapping in per-row try/except here is the correct duplicate suppression point.

**Conclusion**: Sync/Flush sequencing is already correct. Work needed: per-row duplicate suppression in `_execute_many_inline_fallback()` + accurate row count.

---

## Phase 2: Foundational

- [X] T001 Create `tests/unit/test_pipeline_executemany.py` with class stubs for pure-Python logic tests; create `tests/integration/test_psycopg3_pipeline.py` stub with `@pytest.mark.skipif` guard — verify pytest collects 0 tests, no import errors.

---

## Phase 3: User Story 1 — executemany ON CONFLICT + row count (P1) 🎯 MVP

**Goal**: executemany with ON CONFLICT DO NOTHING suppresses duplicate key errors per row; `rows_affected` equals successfully inserted rows.

**Independent Test** (unit): Pure-Python logic tests on `_execute_many_inline_fallback` behavior — no IRIS needed.
**Phase gate** (integration): `pytest tests/integration/test_psycopg3_pipeline.py::test_executemany_on_conflict` on real IRIS.

### Tests for User Story 1 ⚠️ WRITE FIRST

- [X] T002 [US1] Write `TestOnConflictFlagPropagation` in `tests/unit/test_pipeline_executemany.py` — pure-Python tests verifying the ON CONFLICT detection flag logic:
  - `test_on_conflict_detected_in_sql` — `re.search(ON_CONFLICT_PAT, sql)` returns match for `ON CONFLICT DO NOTHING`
  - `test_no_on_conflict_not_detected` — plain INSERT returns no match
  - `test_on_conflict_flag_set_after_strip` — verify execute_many() sets `_had_on_conflict=True` on stripped SQL (test via a thin wrapper / returned metadata)
  - Verify ALL FAIL before implementation

- [X] T003 [US1] Write `TestRowCountAccuracy` in `tests/unit/test_pipeline_executemany.py` — pure-Python tests on the row count accumulation:
  - `test_successful_rows_counted` — accumulator increments only on non-error rows
  - `test_zero_rows_on_all_errors` — accumulator stays 0 when every row would error
  - These test the counting logic directly, not the IRIS call
  - Verify ALL FAIL before implementation

### Implementation for User Story 1

- [X] T004 [US1] In `src/iris_pgwire/iris_executor.py` `execute_many()`: record `_had_on_conflict` bool from the ON CONFLICT detection (before strip). Pass it to the execution paths.

- [X] T005 [US1] In `_execute_many_inline_fallback()` in `src/iris_pgwire/iris_executor.py`: add `on_conflict_present=False` parameter. When True, wrap each row's execute call in `try/except`; catch errors whose message contains "Duplicate key" or "5804"; increment `skipped` counter; continue. Set `rows_affected = len(params_list) - skipped` in returned dict.

- [X] T006 [US1] In `execute_many()`: when `_had_on_conflict` is True and native executemany raises (IRIS bulk executemany has no per-row error isolation), fall through to `_execute_many_inline_fallback()` with `on_conflict_present=True` instead of re-raising.

- [X] T007 [US1] Run `pytest tests/unit/test_pipeline_executemany.py` — all tests must pass.

### Integration gate for User Story 1

- [X] T008 [US1] Write integration test `test_executemany_on_conflict_do_nothing` in `tests/integration/test_psycopg3_pipeline.py`:
  - CREATE TABLE t_049(id INT PRIMARY KEY, v TEXT)
  - `cursor.executemany("INSERT INTO t_049 VALUES (%s, %s) ON CONFLICT DO NOTHING", [(1,'a'),(1,'dup'),(2,'b')])`
  - Assert: table has 2 rows, no exception raised.
- [X] T009 [US1] Write integration test `test_executemany_row_count` in same file:
  - executemany 100 unique rows, verify result metadata rows_affected == 100.

**Checkpoint**: Phase 3 done when T007 passes + T008/T009 pass on real IRIS (skip-guarded).

---

## Phase 4: User Story 2 — Pipeline Sync/Flush sequencing confirmed (P2)

**Goal**: Confirm via integration test that psycopg3 pipeline mode sends correct Sync/Flush sequence and server handles it without hanging or missing RFQ.

**Note from source audit**: `handle_sync_message` and `handle_flush_message` already correct. This phase is confirmation only.

### Integration Tests for User Story 2 ⚠️ WRITE FIRST

- [X] T010 [US2] Write integration test `test_pipeline_sync_sends_rfq` in `tests/integration/test_psycopg3_pipeline.py`:
  - Use psycopg3 pipeline context: `with conn.pipeline():` — send 3 INSERTs, call pipeline sync
  - Verify: all 3 rows land, no client hang, connection still usable after pipeline.
- [X] T011 [US2] Write integration test `test_flush_mid_pipeline` in same file:
  - Use psycopg3 to send Flush (via `conn.pgconn.flush()` or pipeline.communicate())
  - Verify: no ReadyForQuery sent prematurely, subsequent queries work.

### Implementation for User Story 2

- [X] T012 [US2] Run integration tests T010/T011 against real IRIS. If tests pass with no code changes → document that Sync/Flush is already correct. If tests fail → fix the specific protocol issue uncovered by the test.

**Checkpoint**: T010/T011 pass on real IRIS.

---

## Phase 5: Polish

- [X] T013 Run `pytest tests/unit/ --tb=short -q` — all existing tests pass, no regressions.
- [X] T014 Update `CHANGELOG.md` under `[Unreleased]` with fix description.
- [X] T015 Mark tasks.md tasks complete as each lands.

---

## Dependencies & Execution Order

- Phase 1 (audit findings, already done above) → Phase 2 (stubs) → Phase 3 (US1 tests-first → impl → integration gate) → Phase 4 (US2 integration confirmation) → Phase 5 (polish)
- T002/T003 must FAIL before T004–T006
- T008/T009/T010/T011 require IRIS container (skip-guarded)

## Implementation Strategy

MVP: Phase 3 only — per-row duplicate suppression + row count accuracy. The most common crash scenario is fixed.
Full: Add Phase 4 confirmation — verifies pipeline Sync/Flush works end-to-end. Expected to pass with zero code changes.

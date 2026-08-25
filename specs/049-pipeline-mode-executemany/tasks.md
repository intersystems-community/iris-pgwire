# Tasks: psycopg3 Pipeline Mode + executemany Support

**Input**: Design documents from `specs/049-pipeline-mode-executemany/`
**Prerequisites**: spec.md ✅, plan.md ✅

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Understand existing execute_many / flush_batch / handle_sync_message internals

- [ ] T001 Read `src/iris_pgwire/iris_executor.py` execute_many() and _execute_many_native() to map current duplicate key error handling
- [ ] T002 Read `src/iris_pgwire/protocol.py` flush_batch(), handle_sync_message(), handle_flush_message() to map current Sync/Flush behaviour
- [ ] T003 Grep for IRIS duplicate key error strings in `src/iris_pgwire/` to know exact error text to catch

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Create test file skeleton and verify test infrastructure

- [ ] T004 Create `tests/unit/test_pipeline_executemany.py` with class stubs and no test bodies — verify pytest collects 0 tests, no import errors

---

## Phase 3: User Story 1 — executemany ON CONFLICT + row count (P1) 🎯 MVP

**Goal**: executemany with ON CONFLICT DO NOTHING completes without error; row count in result is accurate.

**Independent Test**: `pytest tests/unit/test_pipeline_executemany.py::TestExecuteManyOnConflict` passes with zero IRIS dependency.

### Tests for User Story 1 ⚠️ WRITE FIRST

- [ ] T005 [US1] Write `TestExecuteManyOnConflict` unit tests in `tests/unit/test_pipeline_executemany.py`:
  - `test_on_conflict_stripped_before_each_row` — verify SQL reaching IRIS has no ON CONFLICT
  - `test_duplicate_key_suppressed_with_on_conflict_do_nothing` — mock executor raises duplicate error, verify result is success
  - `test_no_on_conflict_error_propagates` — without ON CONFLICT, duplicate error reaches caller
  - `test_row_count_matches_successful_inserts` — verify rows_affected = number of non-duplicate rows
  - Verify ALL FAIL before implementation

- [ ] T006 [US1] Write `TestExecuteManyRowCount` unit tests in `tests/unit/test_pipeline_executemany.py`:
  - `test_row_count_100_rows` — execute_many returns rows_affected=100 for a 100-row batch
  - `test_row_count_empty_batch` — empty params_list returns rows_affected=0
  - Verify ALL FAIL before implementation

### Implementation for User Story 1

- [ ] T007 [US1] In `src/iris_pgwire/iris_executor.py` `_execute_many_native()`: wrap per-row execution in try/except; on `IRIS error` containing "Duplicate key" or "5804", increment `skipped` counter; continue to next row; return `rows_affected = len(params_list) - skipped`.
  - Note: `_execute_many_native()` delegates to `_execute_many_external_async()` or `_execute_many_embedded_async()` — the try/except must wrap the bulk call, OR switch to per-row fallback when ON CONFLICT was present.
  - Simplest safe approach: when `on_conflict_was_present` flag is set (detect from original SQL before stripping), always use per-row execution via `_execute_many_inline_fallback()` which already iterates rows.

- [ ] T008 [US1] Pass `on_conflict_present` flag from `execute_many()` to fallback path: if True, use per-row execution and suppress duplicate key errors per row.

- [ ] T009 [US1] In `_execute_many_inline_fallback()` in `src/iris_pgwire/iris_executor.py`: catch duplicate key errors per row when `on_conflict_present=True`; accumulate `rows_affected` as count of successful rows only.

- [ ] T010 [US1] Run `pytest tests/unit/test_pipeline_executemany.py::TestExecuteManyOnConflict tests/unit/test_pipeline_executemany.py::TestExecuteManyRowCount` — all must pass.

**Checkpoint**: executemany ON CONFLICT works; row count accurate. Story 1 done.

---

## Phase 4: User Story 2 — Pipeline Sync/Flush sequencing (P2)

**Goal**: Sync sends ReadyForQuery after flushing batch; Flush flushes write buffer only.

**Independent Test**: Unit test mocks verifying Sync sends RFQ and Flush does not.

### Tests for User Story 2 ⚠️ WRITE FIRST

- [ ] T011 [US2] Write `TestSyncFlushesBatch` in `tests/unit/test_pipeline_executemany.py`:
  - `test_sync_sends_ready_for_query` — mock handler, verify ReadyForQuery byte sent after flush_batch() on Sync
  - `test_flush_does_not_send_ready_for_query` — Flush message, verify no ReadyForQuery
  - `test_sync_with_empty_batch_still_sends_rfq` — Sync on empty buffer sends RFQ
  - Verify ALL FAIL before implementation

### Implementation for User Story 2

- [ ] T012 [US2] Read `handle_sync_message()` and `handle_flush_message()` in `src/iris_pgwire/protocol.py` to confirm current RFQ/flush ordering. If already correct, the tests will pass without code changes (document finding).

- [ ] T013 [US2] If `handle_flush_message()` incorrectly sends ReadyForQuery: remove the RFQ send; add assert in test that confirms no RFQ after Flush.

- [ ] T014 [US2] If `handle_sync_message()` does not flush batch before RFQ: reorder to call `flush_batch()` before sending ReadyForQuery.

- [ ] T015 [US2] Run `pytest tests/unit/test_pipeline_executemany.py::TestSyncFlushesBatch` — all must pass.

**Checkpoint**: Sync/Flush protocol sequencing correct.

---

## Phase 5: Integration Test (requires IRIS container)

**Goal**: psycopg3 executemany end-to-end with real IRIS.

- [ ] T016 Create `tests/integration/test_psycopg3_pipeline.py` with `@pytest.mark.skipif(not iris_available(), ...)` guard.
- [ ] T017 [P] [US1] Integration test `test_executemany_on_conflict_do_nothing`: CREATE TABLE, executemany 50 unique + 50 duplicate rows with ON CONFLICT DO NOTHING, verify 50 rows in table, no exception.
- [ ] T018 [P] [US2] Integration test `test_executemany_row_count_accurate`: executemany 100 unique rows, verify result rows_affected == 100.

---

## Phase 6: Polish

- [ ] T019 Run full unit suite `pytest tests/unit/ --tb=short -q` and fix any regressions.
- [ ] T020 Update `CHANGELOG.md` under `[Unreleased]` with fix description.

---

## Dependencies & Execution Order

- Phase 1 (research) → Phase 2 (skeleton) → Phase 3 (US1 tests first → US1 impl) → Phase 4 (US2 tests first → US2 impl) → Phase 5 (integration) → Phase 6 (polish)
- T005/T006 must FAIL before T007–T009
- T011 must FAIL before T012–T014
- T017/T018 require IRIS container (skip-guarded)

## Implementation Strategy

MVP: Phase 1–3 (US1 only — executemany ON CONFLICT + row count). Delivers the crash fix.
Full: Add Phase 4 (Sync/Flush sequencing). Delivers pipeline mode correctness.

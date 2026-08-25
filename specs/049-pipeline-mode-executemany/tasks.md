# Tasks: psycopg3 Pipeline Mode + executemany Support

**Input**: `specs/049-pipeline-mode-executemany/`
**Prerequisites**: spec.md ✅, plan.md ✅
**Constitution note**: Unit tests cover pure-Python logic only (no mocks of IRIS or wire protocol). Executor and protocol behavior tested via skip-guarded integration tests with real psycopg3 + real IRIS.

---

## Phase 1: Source Audit

Findings (captured in plan.md):

- `execute_many()` `iris_executor.py:1309` — ON CONFLICT strip added in 048; per-row duplicate suppression not yet implemented.
- `flush_batch()` `protocol.py:2393` — flushes DML batch on Sync ✅
- `handle_sync_message()` `protocol.py:3532` — calls `flush_batch()` before ReadyForQuery ✅
- `handle_flush_message()` `protocol.py:3597` — does NOT send ReadyForQuery ✅
- `_execute_many_inline_fallback()` `iris_executor.py:1500` — iterates rows one-by-one; per-row try/except is the correct suppression point.

**Conclusion**: Sync/Flush sequencing is already correct. Work: per-row duplicate suppression in `_execute_many_inline_fallback()` + accurate row count.

---

## Phase 2: Foundational

- [x] T001 Create `tests/unit/test_pipeline_executemany.py` and `tests/integration/test_psycopg3_pipeline.py` stubs — pytest collects 0 tests, no import errors.

---

## Phase 3: User Story 1 — executemany ON CONFLICT + row count (P1)

**Goal**: executemany with ON CONFLICT DO NOTHING suppresses duplicate key errors per row; `rows_affected` equals successfully inserted rows.

**Unit gate**: `pytest tests/unit/test_pipeline_executemany.py`
**Integration gate**: `pytest tests/integration/test_psycopg3_pipeline.py::test_executemany_on_conflict` on real IRIS.

### Tests (write first)

- [x] T002 [US1] `TestOnConflictFlagPropagation` in `tests/unit/test_pipeline_executemany.py`:
  - `test_on_conflict_detected_in_sql`
  - `test_no_on_conflict_not_detected`
  - `test_on_conflict_flag_set_after_strip`

- [x] T003 [US1] `TestRowCountAccuracy` in same file:
  - `test_successful_rows_counted`
  - `test_zero_rows_on_all_errors`

### Implementation

- [x] T004 [US1] `src/iris_pgwire/iris_executor.py` `execute_many()`: record `_had_on_conflict` bool before stripping. Pass to execution paths.
- [x] T005 [US1] `_execute_many_inline_fallback()`: add `on_conflict_present=False` param. Catch "Duplicate key"/"5804" errors per row when True; increment `skipped`; return `rows_affected = total - skipped`.
- [x] T006 [US1] `execute_many()`: when `_had_on_conflict` is True, route to `_execute_many_inline_fallback()` with `on_conflict_present=True` instead of native executemany.
- [x] T007 [US1] `pytest tests/unit/test_pipeline_executemany.py` — all pass.

### Integration tests

- [x] T008 [US1] `test_executemany_on_conflict_do_nothing`: CREATE TABLE t_049(id INT PRIMARY KEY, v TEXT); executemany 2 unique + 1 duplicate with ON CONFLICT DO NOTHING; assert 2 rows, no exception.
- [x] T009 [US1] `test_executemany_row_count`: executemany 100 unique rows; assert rows_affected == 100.

---

## Phase 4: User Story 2 — Pipeline Sync/Flush confirmed (P2)

**Goal**: Confirm psycopg3 pipeline mode completes without hanging or missing RFQ.
**Note**: `handle_sync_message` and `handle_flush_message` are already correct per source audit.

### Integration tests (write first)

- [x] T010 [US2] `test_pipeline_sync_does_not_hang`: `with conn.pipeline():` — 3 INSERTs; verify all 3 rows land, connection still usable.
- [x] T011 [US2] `test_flush_mid_pipeline`: send Flush; verify no premature ReadyForQuery, subsequent queries work.

### Implementation

- [x] T012 [US2] Run T010/T011 against real IRIS. If pass with no changes, document. If fail, fix the specific issue the test surfaces.

---

## Phase 5: Polish

- [x] T013 `pytest tests/unit/ --tb=short -q` — no regressions.
- [x] T014 Update `CHANGELOG.md` under `[Unreleased]`.
- [x] T015 Mark tasks complete.

---

## Dependencies

Phase 1 → Phase 2 → Phase 3 (tests before impl) → Phase 4 (tests before impl) → Phase 5.
T008/T009/T010/T011 require IRIS container (skip-guarded).

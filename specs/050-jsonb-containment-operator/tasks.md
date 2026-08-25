# Tasks: JSONB Containment Operator (@>) Support

**Input**: Design documents from `specs/050-jsonb-containment-operator/`
**Prerequisites**: spec.md ✅, plan.md ✅

---

## Phase 1: Setup (Research)

**Purpose**: Understand existing JSON/JSONB handling and PGWire procedure install patterns

- [ ] T001 Read `src/iris_pgwire/sql_translator/normalizer.py` — map `normalize_sql_with_result()` pipeline to find correct insertion point for `@>` rewrite (after ILIKE translation, before return)
- [ ] T002 Read `src/iris_pgwire/sql_translator/pg_functions.py` — understand `_rewrite_variadic_calls()` as pattern for regex-based SQL rewriting
- [ ] T003 Read `src/iris_pgwire/catalog/catalog_installer.py` — find where PGWire procedures are installed (e.g. JSONB_BUILD_OBJECT4) to replicate for JSONB_CONTAINS
- [ ] T004 Grep `src/` for `PGWire.JSONB_BUILD_OBJECT4` to find exact install DDL pattern

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Create test file skeleton

- [ ] T005 Create `tests/unit/test_jsonb_containment.py` with class stubs — verify pytest collects 0 tests

---

## Phase 3: User Story 1 — SQL Rewriter for @> and <@ (P1) 🎯 MVP

**Goal**: `col::jsonb @> '{"k":"v"}'::jsonb` is rewritten to `PGWire.JSONB_CONTAINS(col, '{"k":"v"}')` before reaching IRIS.

**Independent Test**: `pytest tests/unit/test_jsonb_containment.py::TestJsonbContainmentRewrite` passes — no IRIS required.

### Tests for User Story 1 ⚠️ WRITE FIRST

- [ ] T006 [US1] Write `TestJsonbContainmentRewrite` in `tests/unit/test_jsonb_containment.py`:
  - `test_at_gt_with_casts` — `col::jsonb @> '{"k":"v"}'::jsonb` → `PGWire.JSONB_CONTAINS(col, '{"k":"v"}')`
  - `test_at_gt_without_casts` — `col @> '{"k":"v"}'` → `PGWire.JSONB_CONTAINS(col, '{"k":"v"}')`
  - `test_at_gt_with_param_placeholder` — `col::jsonb @> ?` → `PGWire.JSONB_CONTAINS(col, ?)`
  - `test_contained_by_swaps_args` — `'{"k":"v"}'::jsonb <@ col::jsonb` → `PGWire.JSONB_CONTAINS(col, '{"k":"v"}')`
  - `test_no_at_gt_unchanged` — query with no `@>` passes through unmodified
  - `test_multiple_at_gt_in_one_query` — two `@>` predicates both rewritten
  - `test_at_gt_in_subquery` — `@>` inside a subquery is also rewritten
  - `test_nested_json_containment` — value with nested object still rewrites correctly
  - Verify ALL FAIL before implementation

### Implementation for User Story 1

- [ ] T007 [US1] In `src/iris_pgwire/sql_translator/normalizer.py`:
  - Add module-level `_JSONB_CONTAINS_PATTERN` regex — match `([\w."]+(?:::jsonb)?)\s*@>\s*('[^']*'|\?|\$\d+)(?:::jsonb)?` (handle cast on either side, literal and placeholder RHS)
  - Add module-level `_JSONB_CONTAINED_BY_PATTERN` for `<@` (same but args swapped in replacement)

- [ ] T008 [US1] In `normalizer.py`, add `_translate_jsonb_containment(sql: str) -> str` function:
  - Apply `_JSONB_CONTAINS_PATTERN` → replace with `PGWire.JSONB_CONTAINS(\1, \2)` (strip `::jsonb` casts from both capture groups)
  - Apply `_JSONB_CONTAINED_BY_PATTERN` → replace with `PGWire.JSONB_CONTAINS(\2, \1)` (args swapped)
  - Return rewritten SQL

- [ ] T009 [US1] In `normalize_sql_with_result()` in `normalizer.py`, insert `normalized_sql = _translate_jsonb_containment(normalized_sql)` after ILIKE translation line.

- [ ] T010 [US1] Run `pytest tests/unit/test_jsonb_containment.py::TestJsonbContainmentRewrite` — all 8+ tests must pass.

**Checkpoint**: SQL rewriter complete. `@>` queries reach IRIS as `PGWire.JSONB_CONTAINS(...)`.

---

## Phase 4: User Story 2 — ObjectScript JSONB_CONTAINS Procedure (P2)

**Goal**: `PGWire.JSONB_CONTAINS(left, right)` installed in IRIS; returns 1 if `right` is contained in `left`, 0 otherwise.

**Independent Test**: Direct procedure call via `iris_execute` returns correct results.

### Tests for User Story 2 ⚠️ WRITE FIRST

- [ ] T011 [US2] Write `TestJsonbContainsProcedure` in `tests/unit/test_jsonb_containment.py` (mock IRIS call):
  - `test_simple_key_value_match` — `'{"a":1,"b":2}'` contains `'{"a":1}'` → 1
  - `test_simple_mismatch` — `'{"a":1}'` does NOT contain `'{"b":2}'` → 0
  - `test_nested_match` — `'{"x":{"y":1}}'` contains `'{"x":{"y":1}}'` → 1
  - `test_empty_right_always_contained` — `right='{}'` → 1 always
  - `test_right_larger_than_left` — `right` has keys not in `left` → 0
  - These are unit tests that call a Python reference implementation; integration tests verify the ObjectScript version

- [ ] T012 [US2] Write Python reference `_jsonb_contains(left_str, right_str)` in `tests/unit/test_jsonb_containment.py` — pure Python, no IRIS — use `json.loads()` + recursive dict subset check. Tests above call this. Verify all pass.

### Implementation for User Story 2

- [ ] T013 [US2] Write ObjectScript procedure DDL in `src/iris_pgwire/catalog/catalog_installer.py`:
  ```sql
  CREATE OR REPLACE PROCEDURE PGWire.JSONB_CONTAINS(
      left_json VARCHAR(65535), right_json VARCHAR(65535)
  ) RETURNS INTEGER LANGUAGE OBJECTSCRIPT {
      -- ObjectScript body: use %DynamicObject.%FromJSON()
      -- Recursively verify all keys in right_json exist with same values in left_json
  }
  ```
  Follow existing pattern for `JSONB_BUILD_OBJECT4` install — idempotent, runs on startup.

- [ ] T014 [US2] ObjectScript procedure body: use `%DynamicObject.%FromJSON(right_json)` → iterate keys via `%GetIterator()` → for each key, check same key-value in left parsed object. For nested objects, recurse. Return 1 if all match, 0 otherwise.

- [ ] T015 [US2] Run integration test `pytest tests/integration/test_jsonb_ops.py -k jsonb_contains` (skip-guarded; only runs with IRIS container).

**Checkpoint**: JSONB_CONTAINS installed on IRIS, returns correct results.

---

## Phase 5: Integration Test

- [ ] T016 Create `tests/integration/test_jsonb_ops.py` with `@pytest.mark.skipif(not iris_available(), ...)` guard.
- [ ] T017 [P] [US1] Integration test `test_jsonb_containment_where_clause`: CREATE TABLE with VARCHAR JSON column, INSERT 3 rows, SELECT with `col::jsonb @> '{"role":"admin"}'::jsonb`, verify 1 row returned.
- [ ] T018 [P] [US2] Integration test `test_jsonb_contains_procedure_direct`: call `SELECT PGWire.JSONB_CONTAINS('{"a":1}','{"a":1}')` — verify returns 1.

---

## Phase 6: Polish

- [ ] T019 Run full unit suite `pytest tests/unit/ --tb=short -q` — verify no regressions.
- [ ] T020 Update `CHANGELOG.md` under `[Unreleased]` with `@>` operator support.

---

## Dependencies & Execution Order

- Phase 1 (research) → Phase 2 (skeleton) → Phase 3 (US1 tests-first → impl) → Phase 4 (US2 tests-first → impl) → Phase 5 (integration) → Phase 6 (polish)
- T006 must FAIL before T007–T009
- T011/T012 inform T013/T014
- T017/T018 require IRIS container (skip-guarded)

## Implementation Strategy

MVP: Phase 1–3 (rewriter only). The rewriter translates `@>` to `PGWire.JSONB_CONTAINS(...)` but the procedure won't exist yet — IRIS returns "undefined function". Still useful for verifying rewrite logic and unblocks Phase 4.
Full: Add Phase 4 (ObjectScript procedure installed). End-to-end queries work.

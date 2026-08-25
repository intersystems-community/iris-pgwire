# Tasks: JSONB Containment Operator (@>) Support

**Input**: `specs/050-jsonb-containment-operator/`
**Prerequisites**: spec.md ✅, plan.md ✅

---

## Phase 1: Research

- [x] T001 Read `src/iris_pgwire/sql_translator/normalizer.py` — locate insertion point for `@>` rewrite (after ILIKE translation line in `normalize_sql_with_result()`)
- [x] T002 Read `src/iris_pgwire/sql_translator/pg_functions.py` — understand `_rewrite_variadic_calls()` as regex rewrite pattern
- [x] T003 Read `src/iris_pgwire/catalog/functions.py` — find `JSONB_BUILD_OBJECT4` as install pattern for `JSONB_CONTAINS`
- [x] T004 Grep `src/` for `PGWire.JSONB_BUILD_OBJECT4` to confirm exact DDL shape

---

## Phase 2: Test skeleton

- [x] T005 Create `tests/unit/test_jsonb_containment.py` with class stubs — verify 0 tests collected

---

## Phase 3: SQL Rewriter (P1)

**Goal**: `col::jsonb @> '{"k":"v"}'::jsonb` → `PGWire.JSONB_CONTAINS(col, '{"k":"v"}')`

**Gate**: `pytest tests/unit/test_jsonb_containment.py::TestJsonbContainmentRewrite` passes

- [x] T006 [US1] Write `TestJsonbContainmentRewrite` — 8+ cases:
  - `test_at_gt_with_casts` — `col::jsonb @> '{"k":"v"}'::jsonb` → `PGWire.JSONB_CONTAINS(col, '{"k":"v"}')`
  - `test_at_gt_without_casts` — bare `col @> '{"k":"v"}'`
  - `test_at_gt_with_param_placeholder` — `col::jsonb @> ?`
  - `test_contained_by_swaps_args` — `'{"k":"v"}'::jsonb <@ col::jsonb` → args swapped
  - `test_no_at_gt_unchanged`
  - `test_multiple_at_gt_in_one_query`
  - `test_at_gt_in_subquery`
  - `test_nested_json_containment`
  - Verify ALL FAIL before T007–T009

- [x] T007 [US1] `normalizer.py`: add `_JSONB_CONTAINS_PATTERN` and `_JSONB_CONTAINED_BY_PATTERN` module-level regexes

- [x] T008 [US1] `normalizer.py`: add `_translate_jsonb_containment(sql)` — applies both patterns, strips `::jsonb` casts, swaps args for `<@`

- [x] T009 [US1] `normalizer.py` `normalize_sql_with_result()`: insert `normalized_sql = _translate_jsonb_containment(normalized_sql)` after ILIKE line

- [x] T010 [US1] `pytest tests/unit/test_jsonb_containment.py::TestJsonbContainmentRewrite` — all pass

---

## Phase 4: ObjectScript JSONB_CONTAINS Procedure (P2)

**Goal**: `PGWire.JSONB_CONTAINS(left, right)` installed in IRIS; returns 1/0 for containment

**Gate**: `pytest tests/integration/test_jsonb_ops.py -k jsonb_contains` passes on real IRIS

- [x] T011 [US2] Write `TestJsonbContainsProcedure` in `test_jsonb_containment.py` — calls Python reference `_jsonb_contains()`:
  - `test_simple_key_value_match`, `test_simple_mismatch`, `test_nested_match`, `test_empty_right_always_contained`, `test_right_larger_than_left`

- [x] T012 [US2] Write `_jsonb_contains(left_str, right_str)` Python reference — `json.loads()` + recursive subset check; all T011 tests call this

- [x] T013 [US2] Add `JSONB_CONTAINS = CatalogFunction(...)` to `src/iris_pgwire/catalog/functions.py` following `JSONB_BUILD_OBJECT4` pattern; signature `left_json VARCHAR(65535), right_json VARCHAR(65535)`, returns `INTEGER`

- [x] T014 [US2] ObjectScript body: `%DynamicAbstractObject.%FromJSON()` on both args; iterate right keys via `%GetIterator()`; for objects compare values, for arrays check membership; return 1/0

- [x] T015 [US2] Add `JSONB_CONTAINS` to `CATALOG_FUNCTIONS` tuple in `functions.py`

---

## Phase 5: Integration Tests (skip-guarded)

- [x] T016 Create `tests/integration/test_jsonb_ops.py` with `skipif(not IRIS_HOST)` guard
- [x] T017 [P] [US1] `test_jsonb_containment_where_clause`: CREATE TABLE, INSERT 3 rows, SELECT with `@>`, verify 1 row returned
- [x] T018 [P] [US2] `test_jsonb_contains_procedure_direct`: `SELECT PGWire.JSONB_CONTAINS('{"a":1}','{"a":1}')` → 1

---

## Phase 6: Polish

- [x] T019 `pytest tests/unit/ --tb=short -q` — no regressions
- [x] T020 Update `CHANGELOG.md` `[Unreleased]`

---

## Dependencies

- T006 fails before T007–T009
- T011/T012 inform T013–T015
- T017/T018 require IRIS container

# Tasks: surp Lint and ERD Support (047)

**Branch**: `047-surp-lint-support`
**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1 = Lint checks, US2 = ERD FK, US3 = No-crash guarantee
- File paths shown are relative to repo root

---

## Phase 1: Setup

**Purpose**: Verify prerequisites; no new files needed (in-place changes only)

- [X] T001 Read `src/iris_pgwire/sql_translator/pipeline.py` — confirm current rewrite pass order and identify insertion point for new passes
- [X] T002 Read `src/iris_pgwire/sql_translator/array_params.py` — confirm `rewrite_any_to_inlist` and `expand_array_literals` signatures
- [X] T003 Read `src/iris_pgwire/sql_translator/pg_functions.py` — confirm `PG_FUNCTION_MAP` dict structure and `rewrite_pg_function_calls` interface
- [X] T004 Read `src/iris_pgwire/catalog/functions.py` — confirm ObjectScript function DDL format, `CREATE OR REPLACE FUNCTION` pattern, and installer invocation

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: New module `array_literal.py` and the `rewrite_any_col_to_instr` function in `array_params.py` are blocking — both are imported by the pipeline and must exist before any story can be tested end-to-end.

**⚠️ CRITICAL**: Complete before Phase 3.

- [X] T005 Write unit tests for `rewrite_array_literals` in `tests/unit/test_047_surp_lint.py` — cover `ARRAY['a','b']` → `'{a,b}'`, `ARRAY['PERFORMANCE']` → `'{PERFORMANCE}'`, `ARRAY[]` → `'{}'`, case-insensitive matching, whitespace tolerance
- [X] T006 Write unit tests for `rewrite_any_col_to_instr` in `tests/unit/test_047_surp_lint.py` — cover `attnum = ANY(con.conkey)`, `a.col = ANY(b.col)`, must NOT match `= ANY($1)` or `= ANY('{...}')` (already handled)
- [X] T007 Create `src/iris_pgwire/sql_translator/array_literal.py` — implement `rewrite_array_literals(sql: str) -> str` using pattern `ARRAY\s*\[\s*((?:'[^']*'(?:\s*,\s*'[^']*')*)?)\s*\]` (case-insensitive); strips individual quotes, joins values with commas inside braces
- [X] T008 Add `rewrite_any_col_to_instr(sql: str) -> str` to `src/iris_pgwire/sql_translator/array_params.py` — pattern `(\w+(?:\.\w+)?)\s*=\s*ANY\s*\(\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)?)\s*\)`; output `INSTR(',' || REPLACE(REPLACE({col}, '{', ''), '}', '') || ',', ',' || CAST({expr} AS VARCHAR) || ',') > 0`; must not match `$n` or quoted-string operands
- [X] T009 Wire both new passes into `src/iris_pgwire/sql_translator/pipeline.py` in order: (1) `rewrite_array_literals` first, then existing passes, (5) `rewrite_any_col_to_instr` last — per R6 pipeline order in research.md
- [X] T010 Run `pytest tests/unit/test_047_surp_lint.py -v` — T005/T006 tests must pass before proceeding

**Checkpoint**: Rewriter infrastructure complete — story phases can proceed.

---

## Phase 3: User Story 1 — Lint Checks Return Results (Priority: P1) 🎯 MVP

**Goal**: At least 5 of 15 surp lint checks (`no_primary_key`, `duplicate_index`,
`function_search_path_mutable`, `extension_in_public`, `unsupported_reg_types`) return
valid result sets with no SQL error.

**Independent Test**: Execute the 5-check subset of splinter.sql against iris-pgwire; verify
no ERROR response, verify rows returned for tables without PKs.

### Unit Tests (write first)

- [X] T011 [US1] Add unit tests for `format()` dispatch to `tests/unit/test_047_surp_lint.py` — `format('%s', 'foo')` → `PGWire.FORMAT2('%s', 'foo')`, `format('%I %s', 'a', 'b')` → `PGWire.FORMAT3('%I %s', 'a', 'b')`, 4-arg `format(...)` passes through unchanged
- [X] T012 [US1] Add unit tests for `jsonb_build_object()` dispatch to `tests/unit/test_047_surp_lint.py` — 4-arg → `PGWire.JSONB_BUILD_OBJECT4(...)`, 6-arg → `PGWire.JSONB_BUILD_OBJECT6(...)`, odd-arg count passes through

### Implementation

- [X] T013 [P] [US1] Add `'format'` entry to `PG_FUNCTION_MAP` in `src/iris_pgwire/sql_translator/pg_functions.py` — dispatch: count args in match, route 2-arg to `PGWire.FORMAT2`, 3-arg to `PGWire.FORMAT3`, higher arity passes through; must not rewrite already-qualified `pg_catalog.format(` calls
- [X] T014 [P] [US1] Add `'jsonb_build_object'` entry to `PG_FUNCTION_MAP` in `src/iris_pgwire/sql_translator/pg_functions.py` — 4-arg → `PGWire.JSONB_BUILD_OBJECT4`, 6-arg → `PGWire.JSONB_BUILD_OBJECT6`, odd count passes through
- [X] T015 [P] [US1] Add `PGWire.FORMAT2` and `PGWire.FORMAT3` ObjectScript SQL functions to `src/iris_pgwire/catalog/functions.py` — FORMAT2(pattern VARCHAR(4096), arg1 VARCHAR(4096)) RETURNS VARCHAR(4096): implements `%s`/`%I`/`%L`/`%%` substitution with `while` loop (no colons in loop syntax); NULL arg1 → return `""`; FORMAT3 same with arg1+arg2 consumed left-to-right
- [X] T016 [P] [US1] Add `PGWire.JSONB_BUILD_OBJECT4` and `PGWire.JSONB_BUILD_OBJECT6` ObjectScript SQL functions to `src/iris_pgwire/catalog/functions.py` — JSONB_BUILD_OBJECT4(k1,v1,k2,v2 VARCHAR) RETURNS VARCHAR(32767): builds `{"k1":"v1","k2":"v2"}` with double-quote escaping; NULL values → JSON `null`; JSONB_BUILD_OBJECT6 adds k3/v3
- [X] T017 [US1] Add `pg_depend` and `pg_extension` catalog views to `src/iris_pgwire/catalog/views/definitions.py` — both always-empty; schemas per data-model.md; register in `CATALOG_VIEWS` tuple; add `deptype` and `extversion` to `CATALOG_COLUMN_TYPE_OIDS` if needed

### E2E Test (phase gate)

- [X] T018 [US1] Write E2E test in `tests/e2e/test_047_surp_e2e.py` — connect to real iris-pgwire, execute the `no_primary_key` and `extension_in_public` CTE branches of splinter.sql verbatim, assert no ERROR response, assert result columns match expected schema (`jsonb_build_object` output parseable as JSON)
- [X] T019 [US1] Run `pytest tests/e2e/test_047_surp_e2e.py::test_lint_no_primary_key tests/e2e/test_047_surp_e2e.py::test_lint_extension_in_public -v` — must pass before Phase 4

---

## Phase 4: User Story 2 — ERD Foreign Key Relationships (Priority: P2)

**Goal**: surp ERD view shows FK edges for tables with FK constraints defined in IRIS.
`ANY(conkey)` rewrite (from foundational) enables the FK column-lookup in the ERD query.

**Independent Test**: Create `orders`/`customers` tables with FK, run ERD query, verify the
FK row appears with correct `fk_table`, `pk_table`, `fk_column`, `pk_column` values.

### Unit Tests (write first)

- [X] T020 [P] [US2] Add unit tests to `tests/unit/test_047_surp_lint.py` — verify `rewrite_any_col_to_instr` rewrites `attnum = ANY(con.conkey)` correctly (from ERD query context), verify `pg_index` view DDL string contains `indisprimary`, `indkey`, `indisunique` columns

### Implementation

- [X] T021 [US2] Add `pg_index` data-backed catalog view to `src/iris_pgwire/catalog/views/definitions.py` — columns per data-model.md: `indexrelid`, `indrelid`, `indnatts`, `indnkeyatts`, `indisunique`, `indisprimary`, `indisexclusion` (0), `indimmediate` (1), `indisclustered` (0), `indisvalid` (1), `indcheckxmin` (0), `indisready` (1), `indislive` (1), `indisreplident` (0), `indkey` (space-separated attnum text), `indpred` (NULL); data source: `INFORMATION_SCHEMA.TABLE_CONSTRAINTS` PK/UNIQUE joined to `KEY_COLUMN_USAGE` and `COLUMNS`; register in `CATALOG_VIEWS` tuple

### E2E Test (phase gate)

- [X] T022 [US2] Add ERD E2E test to `tests/e2e/test_047_surp_e2e.py` — create `pgwire_test_orders` and `pgwire_test_customers` tables with FK constraint, execute surp's ERD FK query verbatim, assert result contains a row with correct `fk_table`=`pgwire_test_orders`, verify `ANY(conkey)` rewrite fires by checking the INSTR pattern appears in translated SQL (via translator debug mode or query plan); teardown drops both tables
- [X] T023 [US2] Run `pytest tests/e2e/test_047_surp_e2e.py::test_erd_fk_relationship -v` — must pass before Phase 5

---

## Phase 5: User Story 3 — No Crash on Unsupported Checks (Priority: P3)

**Goal**: Full splinter.sql (all 15 checks as one multi-CTE UNION) executes without any
ERROR-level protocol response. `pg_policy` and `pg_rewrite` return zero rows.

**Independent Test**: Execute the complete splinter.sql text against iris-pgwire; assert
response is a valid ResultSet (no ErrorResponse wire message).

### Unit Tests (write first)

- [X] T024 [P] [US3] Add unit tests to `tests/unit/test_047_surp_lint.py` — verify `pg_policy` and `pg_rewrite` view DDL strings are present in `definitions.py`; verify both have the required columns per data-model.md

### Implementation

- [X] T025 [US3] Add `pg_policy` and `pg_rewrite` always-empty catalog views to `src/iris_pgwire/catalog/views/definitions.py` — schemas per data-model.md; register in `CATALOG_VIEWS` tuple; `polroles` stored as text (IRIS has no oid[] type)

### E2E Test (phase gate)

- [X] T026 [US3] Add full-splinter E2E test to `tests/e2e/test_047_surp_e2e.py` — load SQL from `tests/fixtures/splinter_excerpt.sql`, execute against iris-pgwire, assert no ErrorResponse, assert result is a list (may be empty), parse the JSON column in each row and assert at least 5 distinct `check_id` key values appear across all rows; measure translation-only time with `time.perf_counter` around the rewrite pipeline call and assert ≤ 10 ms (deviation from the 5 ms constitution budget; rationale: 15-branch multi-CTE UNION, documented in plan.md Complexity Tracking)
- [X] T027 [US3] Run `pytest tests/e2e/test_047_surp_e2e.py::test_full_splinter_no_crash -v` — must pass before Phase 6

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T028 [P] Create `tests/fixtures/splinter_excerpt.sql` — embed the 5 supported CTE branches of surp's splinter.sql (no_primary_key, duplicate_index, function_search_path_mutable, extension_in_public, unsupported_reg_types) plus the ERD FK query as a single multi-CTE UNION; add a comment citing the source (<https://github.com/rexadbapp/surp>)
- [X] T029 [P] Add parametrized backend fixture to `tests/e2e/test_047_surp_e2e.py` — `@pytest.mark.parametrize("backend", ["embedded", "dbapi"])` on all E2E tests so the full suite runs against both backends; skip DBAPI if `IRIS_DBAPI_DSN` env var is absent (constitution §IV: both backends must pass)
- [X] T030 [P] Run full unit test suite `pytest tests/unit/ -v` and confirm zero failures
- [X] T031 [P] Run full E2E test suite with both backends `pytest tests/e2e/ -v` (embedded then DBAPI) and confirm zero failures
- [X] T032 [P] Run `ruff check src/iris_pgwire/sql_translator/ src/iris_pgwire/catalog/` and fix any issues
- [X] T033 [P] Verify `CATALOG_COLUMN_TYPE_OIDS` in `src/iris_pgwire/catalog/views/definitions.py` includes entries for all new view columns that need non-default OID mapping (e.g., `deptype`, `polcmd`, `ev_type`, `ev_enabled` as `"char"` / OID 18)
- [X] T034 Commit all changes on branch `047-surp-lint-support` with message summarising the 5-view + 4-function + 3-rewriter-pass change

---

## Dependencies

```text
Phase 1 (T001–T004)
  └─► Phase 2 (T005–T010)
        ├─► Phase 3 US1 (T011–T019)  ← can start once T010 passes
        ├─► Phase 4 US2 (T020–T023)  ← can start once T010 passes (T021 depends on T017 for indkey column)
        └─► Phase 5 US3 (T024–T027)  ← can start once T017+T025 done
              └─► Phase 6 (T028–T034)
```

**Parallel opportunities within phases**:

- T013, T014 can run in parallel (different dict entries in pg_functions.py — but same file; write sequentially unless using separate hunks)
- T015, T016 can run in parallel (different function names in catalog/functions.py — same file caution)
- T017 (pg_depend/pg_extension) and T021 (pg_index) can run in parallel if split across two working sessions
- T020, T024 (unit tests for US2, US3) can run in parallel after T010

---

## Implementation Strategy

**MVP = Phase 2 + Phase 3** (T005–T019). This delivers US1 (lint checks) which is the
primary user value. Phases 4–5 add ERD and crash-safety on top.

**Suggested sequence for a single session**:

1. T005–T006 (write failing unit tests)
2. T007–T009 (make foundational tests pass)
3. T010 (confirm green)
4. T011–T017 (US1 implementation — T013+T014 in one pg_functions.py edit, T015+T016 in one catalog/functions.py edit)
5. T018–T019 (US1 E2E gate)
6. T020–T023 (US2)
7. T024–T027 (US3)
8. T028–T034 (polish: fixture, dual-backend, lint, commit)

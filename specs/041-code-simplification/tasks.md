# Tasks: Comprehensive Code Simplification

**Input**: Design documents from `/specs/041-code-simplification/`
**Status**: ✅ Complete — this is a retrospective task list (implementation committed as `41801be`)
**No test tasks**: Tests were not requested in spec.md; the existing test suite served as the regression gate.

---

## Phase 1: Setup

**Purpose**: Baseline measurement and simplification tooling

- [x] T001 [P] Measure line counts for all files in `src/iris_pgwire/` to establish baseline
- [x] T002 [P] Confirm full test suite passes on `main` before any changes (`pytest src/`)
- [x] T003 [P] Identify top-priority targets: `protocol.py` (4527 lines), `iris_executor.py` (4503 lines), `sql_translator/` (~13,700 lines)

---

## Phase 2: Foundational (Shared Patterns)

**Purpose**: Establish simplification patterns applied across all phases

- [x] T004 Define and apply **dispatch table pattern**: replace `if/elif` chains with `{key: callable}` dicts
- [x] T005 Define and apply **helper extraction pattern**: decompose functions >50 lines into focused named helpers
- [x] T006 Define and apply **early return pattern**: flatten nesting via guard clauses
- [x] T007 Define and apply **dead code removal**: unused imports, unreachable code after `return`, no-op methods

**Checkpoint**: Patterns established — user story simplification can proceed in parallel

---

## Phase 3: User Story 1 — Core Source Files Simplified (Priority: P1) 🎯 MVP

**Goal**: `src/iris_pgwire/` top-level files readable on first pass; functions ≤50 lines; no nesting >3 levels.

**Independent Test**: Read any file in `src/`; run `pytest src/` to confirm no regressions.

### Implementation for User Story 1

- [x] T010 [US1] Simplify `src/iris_pgwire/protocol.py` (4527 → 4469 lines): extract wire-protocol parsing helpers; preserve inherent domain complexity with comments
- [x] T011 [US1] Simplify `src/iris_pgwire/iris_executor.py` (4503 → 3998 lines, -11%): decompose large handler methods; extract shared `_execute_iris_operation` pattern
- [x] T012 [US1] Simplify `src/iris_pgwire/dbapi_executor.py` (1411 → 1291 lines, -9%): consolidate duplicated logic shared with `iris_executor.py`
- [x] T013 [US1] Simplify `src/iris_pgwire/iris_constructs.py` (849 → 632 lines, -26%): remove dead code; flatten nesting; extract helpers
- [x] T014 [US1] Simplify `src/iris_pgwire/vector_optimizer.py` (912 → 653 lines, -28%): decompose optimization stages into focused helpers
- [x] T015 [US1] Simplify `src/iris_pgwire/iris_user_management.py`: extract `_execute_iris_operation` shared helper
- [x] T016 [US1] Simplify `src/iris_pgwire/bulk_executor.py`: remove dead code; flatten nesting
- [x] T017 [US1] Simplify `src/iris_pgwire/constitutional.py`: replace if/elif chain with dispatch table
- [x] T018 [US1] Simplify `src/iris_pgwire/server.py`: extract setup/teardown helpers
- [x] T019 [US1] Fix regression: `confidence_analyzer.py` — dead `return []` before helper calls introduced during simplification (fixed inline)
- [x] T020 [US1] Fix regression: `ddl_splitter.py` — `_should_toggle_quote()` missing parameter in new signature (fixed inline)
- [x] T021 [US1] Run full test suite post-simplification; confirm 595+ tests pass with zero new failures

**Checkpoint**: US1 complete — core files simplified, test suite clean ✅

---

## Phase 4: User Story 2 — SQL Translator Subpackage Simplified (Priority: P2)

**Goal**: `sql_translator/` (~13,700 lines, ~35 files) simplified; pipeline navigable without reading all files.

**Independent Test**: Review `sql_translator/` in isolation; run `pytest src/` for regression gate.

### Implementation for User Story 2

- [x] T030 [P] [US2] Simplify `src/iris_pgwire/sql_translator/translator.py` (804 lines): separate responsibilities; each function has single clear purpose
- [x] T031 [P] [US2] Simplify `src/iris_pgwire/sql_translator/confidence_analyzer.py`: extract scoring helpers; remove dead code
- [x] T032 [P] [US2] Simplify `src/iris_pgwire/sql_translator/validator.py`: early returns; reduce nesting
- [x] T033 [P] [US2] Simplify `src/iris_pgwire/sql_translator/parser.py`: extract clause-specific parsers
- [x] T034 [P] [US2] Simplify `src/iris_pgwire/sql_translator/metrics.py`: remove duplication; clean imports
- [x] T035 [P] [US2] Simplify `src/iris_pgwire/sql_translator/performance_monitor.py`: keep as separate file from top-level `performance_monitor.py` (different domains, different interfaces — consolidation rejected per research.md)
- [x] T036 [P] [US2] Simplify remaining 29 files in `src/iris_pgwire/sql_translator/`: apply all four patterns uniformly

**Checkpoint**: US2 complete — `sql_translator/` simplified, test suite still clean ✅

---

## Phase 5: User Story 3 — Auth and Catalog Subpackages Simplified (Priority: P3)

**Goal**: `auth/` and `catalog/` cleaned up for clarity and consistency.

**Independent Test**: Each subpackage reviewable independently without running IRIS.

### Implementation for User Story 3

- [x] T040 [P] [US3] Simplify `src/iris_pgwire/auth/scram.py`: single responsibility; remove dead code
- [x] T041 [P] [US3] Simplify `src/iris_pgwire/auth/gssapi_auth.py`: clear interface; no dead code
- [x] T042 [P] [US3] Simplify `src/iris_pgwire/auth/oauth_bridge.py`: clean imports; extract helpers
- [x] T043 [P] [US3] Simplify remaining 2 `auth/` modules: apply all four patterns
- [x] T044 [US3] Simplify `src/iris_pgwire/catalog/catalog_router.py` (994 lines): replace nested if/elif dispatch with `{table_name: handler_method}` dispatch map
- [x] T045 [P] [US3] Simplify `src/iris_pgwire/conversions/ddl_splitter.py`: decompose `_parse_*` helpers; fix `_should_toggle_quote` parameter bug
- [x] T046 [P] [US3] Simplify `src/iris_pgwire/models/`: extract `BackendConfig.from_env()` helper
- [x] T047 [US3] Run full test suite; confirm zero new regressions

**Checkpoint**: All user stories complete — all subpackages simplified ✅

---

## Phase 6: Polish & Cross-Cutting Concerns

- [x] T050 [P] Verify `quality/` subpackage left unchanged (conservative: modifying code-inspection files risks correctness)
- [x] T051 [P] Remove all unused imports across every simplified file
- [x] T052 [P] Ensure no function in `src/` exceeds 50 lines (documented exceptions: wire protocol byte parsing)
- [x] T053 [P] Ensure nesting depth ≤3 levels across all files
- [x] T054 Commit all changes as single logical commit: `refactor: comprehensive code simplification across entire src/ codebase` (`41801be`)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup
- **US1 (Phase 3)**: Depends on Foundational — highest priority, done first
- **US2 (Phase 4)**: Depends on Foundational — parallelisable with US1; done after US1 in practice
- **US3 (Phase 5)**: Depends on Foundational — lowest priority; done last
- **Polish (Phase 6)**: Depends on all stories complete

### Parallel Opportunities (all [P] tasks)

- All file-level simplification tasks within each story are independent and were run in parallel via `@fixer` agents
- Auth modules (T040–T043) were parallelised
- SQL translator files (T030–T036) were parallelised

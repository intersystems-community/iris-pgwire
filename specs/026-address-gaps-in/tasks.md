# Tasks: Address IRIS Bridge Gaps

**Input**: Design documents from `/specs/026-address-gaps-in/`
**Prerequisites**: plan.md (required), research.md, data-model.md, contracts/

## Execution Flow (main)
```
1. Load plan.md from feature directory
   → If not found: ERROR "No implementation plan found"
   → Extract: tech stack, libraries, structure
2. Load optional design documents:
   → data-model.md: Extract entities → model tasks
   → contracts/: Each file → contract test task
   → research.md: Extract decisions → setup tasks
3. Generate tasks by category:
   → Setup: project init, dependencies, linting
   → Tests: contract tests, integration tests
   → Core: models, services, CLI commands
   → Integration: DB, middleware, logging
   → Polish: unit tests, performance, docs
4. Apply task rules:
   → Different files = mark [P] for parallel
   → Same file = sequential (no [P])
   → Tests before implementation (TDD)
5. Number tasks sequentially (T001, T002...)
6. Generate dependency graph
7. Create parallel execution examples
8. Validate task completeness:
   → All contracts have tests?
   → All entities have models?
   → All endpoints implemented?
9. Return: SUCCESS (tasks ready for execution)
```

## Phase 1: Setup
- [x] T001 Initialize project structure for `conversions/` package in `src/iris_pgwire/conversions/`
- [x] T002 Add `intersystems-irispython`, `psycopg[binary]`, and `pytest-benchmark` to project dependencies
- [x] T003 Configure linting rules for `src/iris_pgwire/conversions/` to enforce type annotations and pure functions

## Phase 2: Foundational (Centralized Conversions)
- [x] T004 [P] Implement `horolog_to_pg` and `pg_to_horolog` in `src/iris_pgwire/conversions/date_horolog.py`
- [x] T005 [P] Implement `JsonPathBuilder` in `src/iris_pgwire/conversions/json_path.py`
- [x] T006 [P] Implement `HnswIndexSpec` and distance mapping in `src/iris_pgwire/conversions/vector_syntax.py`
- [x] T007 [P] Implement `DdlErrorHandler` and `DdlResult` in `src/iris_pgwire/conversions/ddl_idempotency.py`
- [x] T008 [P] Implement `BulkInsertJob` state tracker in `src/iris_pgwire/conversions/bulk_insert.py`
- [x] T009 Export all utilities in `src/iris_pgwire/conversions/__init__.py`

## Phase 3: Tests First (TDD) ⚠️ MUST COMPLETE BEFORE IMPLEMENTATION
- [x] T010 [P] [US1] Unit tests for HNSW translation in `tests/unit/test_hnsw_translation.py`
- [x] T011 [P] [US2] Performance benchmark test for bulk insert in `tests/integration/test_bulk_insert.py`
- [x] T012 [P] [US3] Unit tests for recursive JSON path building in `tests/unit/test_json_path.py`
- [x] T013 [P] [US4] Integration tests for DDL idempotency in `tests/integration/test_ddl_idempotency.py`
- [x] T014 [P] Unit tests for all date/horolog conversions in `tests/unit/test_conversions.py`

## Phase 4: US-001 - HNSW Index Support
- [x] T015 [US1] Register HNSW index pattern in `src/iris_pgwire/sql_translator/mappings/constructs.py`
- [x] T016 [US1] Register vector distance functions in `src/iris_pgwire/sql_translator/mappings/functions.py`
- [x] T017 [US1] Implement `translate_hnsw_index` handler in `src/iris_pgwire/sql_translator/mappings/constructs.py` using `HnswIndexSpec`

## Phase 5: US-002 - Fast Bulk Insert
- [x] T018 [US2] Implement `execute_many_native` with parameter binding in `src/iris_pgwire/iris_executor.py`
- [x] T019 [US2] Implement fallback to string inlining in `src/iris_pgwire/iris_executor.py`
- [x] T020 [US2] Integrate `BulkInsertJob` for tracking and monitoring in the executor

## Phase 6: US-003 - Recursive Nested JSON
- [x] T021 [US3] Implement `translate_nested_json` handler in `src/iris_pgwire/sql_translator/mappings/document_filters.py`
- [x] T022 [US3] Integrate `JsonPathBuilder` into the document filter registry

## Phase 7: US-004 - DDL Idempotency
- [x] T023 [US4] Implement `DdlErrorHandler` integration in `src/iris_pgwire/iris_executor.py`
- [x] T024 [US4] Update migration logic to use `DdlErrorHandler` for logging skipped objects

## Phase 8: Polish & Cross-cutting Concerns
- [x] T025 [P] Implement structured audit logging for all transformations in the translator
- [x] T026 [P] Add Prometheus metrics for translation latency and bulk insert throughput
- [x] T027 [P] Update `docs/VECTOR_PARAMETER_BINDING.md` with HNSW and fast insert details
- [x] T028 Remove duplicated conversion code from all executor files
- [x] T029 Run full test suite and verify all success criteria are met (Achieved 3,778 rows/sec)
- [x] T030 [P] Add memory profiling test for bulk insert operations in `tests/integration/test_memory_usage.py` (target <50MB overhead)

## Dependencies
- Phase 1 & 2 block all User Story phases (4-7)
- Phase 3 (Tests) must complete before implementing logic in Phases 4-7
- T004-T008 are parallelizable [P]
- T010-T014 are parallelizable [P]
- T025-T027 are parallelizable [P]

## Parallel Example
```bash
# Launch Foundational utility implementations together:
Task: "Implement date_horolog.py in src/iris_pgwire/conversions/"
Task: "Implement json_path.py in src/iris_pgwire/conversions/"
Task: "Implement vector_syntax.py in src/iris_pgwire/conversions/"
Task: "Implement ddl_idempotency.py in src/iris_pgwire/conversions/"
Task: "Implement bulk_insert.py in src/iris_pgwire/conversions/"
```

## Implementation Strategy
1. **Foundational Package**: Build the `conversions/` package first to provide clean, tested APIs for the rest of the feature.
2. **TDD Loop**: For each user story, ensure the test is failing before adding the mapping or executor logic.
3. **Incremental Migration**: Replace duplicated code in executors only after the new package is fully verified.
4. **Performance Verification**: Run benchmarks early to ensure the fast insert path meets the 333 rows/sec target.

## Summary Statistics
| Metric | Value |
|--------|-------|
| Total Tasks | 30 |
| Setup Tasks | 3 |
| Foundational Tasks | 6 |
| Test Tasks | 5 |
| Implementation Tasks | 10 |
| Polish Tasks | 6 |
| Parallel Opportunities [P] | 14 |
| User Story Tasks | 10 |
| Estimated MVP Scope | Phase 1 + Phase 2 + Phase 3 + Phase 4 (HNSW support) |

---
*Generated tasks for 026-address-gaps-in feature.*

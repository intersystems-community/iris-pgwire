# Tasks: IRIS pgwire compatibility fixes

**Input**: Design documents from `/specs/034-issues-that-likely/`
**Prerequisites**: plan.md (required), research.md, data-model.md, contracts/, quickstart.md

## Phase 1: Setup
- [x] T001 Confirm iris-devtester coverage for pgwire SQL translation in tests/README.md
- [x] T002 Capture current Simple/Extended query flow notes in specs/034-issues-that-likely/research.md

## Phase 2: Foundational
- [x] T003 [P] Add SQL normalization pipeline tests in tests/unit/test_sql_normalizer_fixes.py
- [x] T004 [P] Add DDL splitter comment handling tests in tests/unit/test_ddl_splitter_fixes.py
- [x] T005 [P] Add parameter translation tests in tests/unit/test_parameter_translation_fixes.py
- [x] T006 [P] Add DEFAULT-in-VALUES rewrite tests in tests/unit/test_default_values_rewrite.py
- [x] T007 [P] Add timestamp normalization tests in tests/unit/test_timestamp_normalization_fixes.py
- [x] T008 [P] Add ALTER TABLE translation tests in tests/unit/test_alter_table_translation_fixes.py
- [x] T009 Add iris-devtester stale code detection test in tests/integration/test_code_sync.py

## Phase 2.1: E2E Tests First (Constitution)
- [x] T010 [P] [US1] Add iris-devtester E2E test for multi-statement DDL with comments in tests/integration/test_ddl_comments.py
- [x] T011 [P] [US2] Add iris-devtester E2E test for prepared statement translation in tests/integration/test_prepared_translation.py
- [x] T012 [P] [US3] Add iris-devtester E2E test for DEFAULT in VALUES in tests/integration/test_default_values.py
- [x] T013 [P] [US4] Add iris-devtester E2E test for timestamp normalization in tests/integration/test_timestamp_normalization.py
- [x] T014 [P] [US5] Add iris-devtester E2E test for ALTER TABLE translations in tests/integration/test_alter_table_translation.py

## Phase 3: User Story 1 (P1) – Multi-statement DDL with comments
**Story Goal**: Ensure SQL scripts with comments and multiple statements execute without corruption.
**Independent Test Criteria**: DDL scripts with leading comments execute in order; no no-op SQL injected.
- [x] T015 [US1] Update statement splitting to avoid no-op DDL substitutions in src/iris_pgwire/iris_executor.py
- [x] T016 [US1] Ensure comment-aware splitting in src/iris_pgwire/iris_executor.py
- [x] T017 [US1] Update DDL splitter comment handling in src/iris_pgwire/conversions/ddl_splitter.py

## Phase 4: User Story 2 (P1) – Prepared statement translation ($n → ?)
**Story Goal**: Prepared statements always translate positional parameters across all query paths.
**Independent Test Criteria**: $n placeholders never reach IRIS in Simple or Extended protocol paths.
- [x] T018 [US2] Apply parameter translation before normalization in src/iris_pgwire/protocol.py
- [x] T019 [US2] Ensure translate_postgres_parameters is applied in Simple Query path in src/iris_pgwire/protocol.py
- [x] T020 [US2] Ensure any executor-side ad-hoc SQL uses translated parameters in src/iris_pgwire/iris_executor.py

## Phase 5: User Story 3 (P1) – DEFAULT in VALUES
**Story Goal**: Inserts using per-column DEFAULT values execute successfully in IRIS.
**Independent Test Criteria**: DEFAULT-in-VALUES inserts apply schema defaults and do not error.
- [x] T021 [US3] Implement DEFAULT-in-VALUES rewrite in src/iris_pgwire/sql_translator/normalizer.py
- [x] T022 [US3] Add rewrite helper for DEFAULT-in-VALUES in src/iris_pgwire/sql_translator/default_values.py

## Phase 6: User Story 4 (P1) – Timestamp binding
**Story Goal**: ISO timestamps with T/Z or offsets are accepted by IRIS.
**Independent Test Criteria**: Timestamp literals and bound values normalize to IRIS-compatible strings.
- [x] T023 [US4] Normalize ISO 8601 timestamp literals in src/iris_pgwire/sql_translator/date_translator.py
- [x] T024 [US4] Normalize timestamp bound values in src/iris_pgwire/iris_executor.py
- [x] T025 [US4] Normalize binary timestamp decoding in src/iris_pgwire/protocol.py

## Phase 7: User Story 5 (P1) – ALTER TABLE SET DATA TYPE / DROP NOT NULL
**Story Goal**: ALTER TABLE type and nullability changes work or return clear errors.
**Independent Test Criteria**: Supported changes execute; unsupported changes return actionable errors.
- [x] T026 [US5] Translate ALTER TABLE SET DATA TYPE to ALTER COLUMN in src/iris_pgwire/conversions/ddl_splitter.py
- [x] T027 [US5] Translate DROP NOT NULL to ALTER COLUMN NULL in src/iris_pgwire/conversions/ddl_splitter.py
- [x] T028 [US5] Add clear errors for unsupported ALTER TABLE actions in src/iris_pgwire/iris_executor.py

## Phase 8: Integration & Validation
- [x] T029 Run quickstart validation steps in specs/034-issues-that-likely/quickstart.md
- [x] T030 [P] Add error sanitization integration test in tests/integration/test_error_sanitization.py
- [x] T031 [P] Add observability smoke test in tests/integration/test_observability_smoke.py

## Dependencies
- T003-T014 before T015-T028
- T015-T028 before T029-T031

## Parallel Execution Examples
### Unit tests
- T003, T004, T005, T006, T007, T008 can run in parallel
### E2E tests
- T010, T011, T012, T013, T014 can run in parallel
### US4
- T023, T024, T025 can run in parallel

## Validation Checklist
- [x] All contracts have corresponding tests
- [x] All entities have model tasks
- [x] All tests come before implementation
- [x] Parallel tasks truly independent
- [x] Each task specifies exact file path
- [x] No task modifies same file as another [P] task

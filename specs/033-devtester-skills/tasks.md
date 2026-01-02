# Tasks: IRIS DevTester Agentic Skills Integration

## Status
- **Date**: 2025-01-02
- **Feature**: `033-devtester-skills`
- **Plan**: specs/033-devtester-skills/plan.md

## Implementation Strategy
We follow an MVP-first approach, starting with replacing the manual container management in the main `conftest.py`. Each subsequent phase adds a new "skill" integration, ending with testing new-ish functionality to verify the entire stack.

## Phase 1: Setup
Goal: Prepare the environment and update dependencies.

- [ ] T001 Update `pyproject.toml` to include `iris-devtester` in `test` dependencies
- [ ] T002 Update `AGENTS.md` with new `iris-devtester` skills context
- [ ] T003 [P] Verify local `iris-devtester` installation (editable mode)

## Phase 2: Foundational
Goal: Integrate core `iris-devtester` logic into the testing framework.

- [ ] T004 Refactor `tests/conftest.py` to use `iris_devtester.IRISContainer` for the `iris_container` fixture
- [ ] T005 [P] Implement `iris_config` fixture modernization in `tests/conftest.py`
- [ ] T006 [P] Update `src/iris_pgwire/tests/conftest.py` to match new `iris-devtester` patterns

## Phase 3: User Story 1 - Container Management [US1]
Goal: Automate IRIS container lifecycle (FR-003, FR-004, FR-005).

- [ ] T007 [US1] Update `iris_container` fixture to support `--iris-image` and `--iris-persist` flags in `tests/conftest.py`
- [ ] T008 [P] [US1] Implement automated health checks for container readiness in `tests/conftest.py`
- [ ] T009 [US1] Create integration test `tests/integration/test_container_management.py` to verify container lifecycle

## Phase 4: User Story 2 - Connection & Auto-Remediation [US2]
Goal: Reliable database connections with auto-fix (FR-006, FR-007, FR-008).

- [ ] T010 [US2] Replace manual connection logic with `iris_devtester.connections.get_connection()` in `tests/conftest.py`
- [ ] T011 [P] [US2] Implement auto-remediation for "Password change required" in `tests/conftest.py`
- [ ] T012 [P] [US2] Implement automated CallIn service enablement in `tests/conftest.py`
- [ ] T013 [US2] Create integration test `tests/integration/test_connection_remediation.py`

## Phase 5: User Story 3 - Test Data Management [US3]
Goal: Reproducible test scenarios via fixtures (FR-009, FR-010).

- [ ] T014 [US3] Implement `iris_fixture` fixture using `iris_devtester.fixtures.creator.FixtureCreator` in `tests/conftest.py`
- [ ] T015 [P] [US3] Implement fixture export functionality for debugging in `tests/conftest.py`
- [ ] T016 [US3] Create integration test `tests/integration/test_fixture_management.py` using `.DAT` files

## Phase 6: User Story 4 - Troubleshooting & Diagnostics [US4]
Goal: Actionable failure reports (FR-011, FR-012).

- [ ] T017 [US4] Update `pytest_runtest_makereport` hook to trigger `iris-devtester` troubleshooting logic in `tests/conftest.py`
- [ ] T018 [P] [US4] Implement `test_failures.jsonl` generation with remediation hints in `tests/conftest.py`
- [ ] T019 [US4] Create test case `tests/integration/test_troubleshooting_skill.py` that intentionally fails to verify diagnostic output

## Phase 7: User Story 5 - New Feature Testing [US5]
Goal: Verify new iris-pgwire features using the new infrastructure (FR-013, FR-014).

- [ ] T020 [US5] Implement `tests/integration/test_pg_catalog_emulation.py` using `iris-devtester` fixtures
- [ ] T021 [P] [US5] Implement `tests/integration/test_orm_introspection.py` (SQLAlchemy/Prisma reflection tests)
- [ ] T022 [P] [US5] Implement `tests/integration/test_vector_optimized_ops.py` (HNSW and operator tests)

## Phase 8: Polish
Goal: Cleanup and documentation.

- [ ] T023 Remove legacy Docker/subprocess container management code from `tests/conftest.py`
- [ ] T024 [P] Update `docs/testing.md` to reflect new `iris-devtester` workflow
- [ ] T025 Run full test suite and verify all 14 Functional Requirements are met

## Dependencies
US1 (Container) → US2 (Connection) → US3 (Fixture) → US4 (Troubleshooting) → US5 (New Features)

## Parallel Execution Examples
- T005, T006 (Fixtures & Conftest updates)
- T011, T012 (Connection remediation)
- T020, T021, T022 (New feature tests)

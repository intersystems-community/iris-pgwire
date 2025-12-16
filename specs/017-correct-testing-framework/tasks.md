# Tasks: Correct Testing Framework Additions

**Input**: Design documents from `/specs/017-correct-testing-framework/`
**Prerequisites**: plan.md, research.md, data-model.md, contracts/

## Format: `[ID] [P?] Description`
- **[P]**: Can run in parallel (different files, no dependencies)
- Include exact file paths in descriptions

## Phase 3.1: Setup & Configuration

- [x] **T001** [P] Configure pytest timeout and coverage in `pyproject.toml`
  - Add pytest-timeout>=2.2.0, pytest-cov>=4.1.0 to test dependencies
  - Set global timeout=30s, timeout_func_only=false
  - Configure coverage: --cov=iris_pgwire, terminal + HTML + XML reports
  - Disable parallel execution (no -n flag, --dist no)
  - Add coverage.run.omit for tests/, benchmarks/, specs/
  - **NO** fail_under threshold (informational only)

- [x] **T002** [P] Update `.gitignore` for test artifacts
  - Add htmlcov/, .coverage, coverage.xml
  - Add test_failures.jsonl, .pytest_cache/
  - Add __pycache__/ if not already present

- [x] **T003** [P] Create pytest markers in `pyproject.toml`
  - Add timeout marker: Override default timeout threshold
  - Add flaky marker: Mark known flaky tests for retry
  - Add slow marker: Tests requiring >10 seconds
  - Add e2e marker: End-to-end tests with real clients

## Phase 3.2: Tests First (TDD) ⚠️ MUST COMPLETE BEFORE 3.3

**CRITICAL: These tests MUST be written and MUST FAIL before ANY implementation**

- [x] **T004** [P] Contract test for `embedded_iris` fixture in `tests/contract/test_fixture_contract.py`
  - Test: `test_embedded_iris_fixture_provides_connection`
  - Verify fixture returns valid iris.Connection
  - Execute "SELECT 1" to verify connection works
  - Assert result is 1
  - **MUST FAIL** until fixture implemented

- [x] **T005** [P] Contract test for `embedded_iris` cleanup in `tests/contract/test_fixture_contract.py`
  - Test: `test_embedded_iris_fixture_cleanup_releases_resources`
  - Track connection before fixture teardown
  - Verify connection closed after session ends
  - Check no leaked IRIS processes
  - **MUST FAIL** until cleanup implemented

- [x] **T006** [P] Contract test for `iris_clean_namespace` fixture in `tests/contract/test_fixture_contract.py`
  - Test: `test_iris_clean_namespace_isolates_test_data`
  - Create test table in first test iteration
  - Verify table does NOT exist in second test iteration
  - Assert complete isolation between tests
  - **MUST FAIL** until isolation implemented

- [x] **T007** [P] Contract test for `pgwire_client` fixture in `tests/contract/test_fixture_contract.py`
  - Test: `test_pgwire_client_connects_successfully`
  - Verify fixture returns connected psycopg.Connection
  - Assert connection.status == psycopg.Connection.OK
  - Execute simple query through PGWire
  - **MUST FAIL** until fixture implemented

- [x] **T008** [P] Contract test for timeout handler in `tests/contract/test_timeout_handler.py`
  - Test: `test_timeout_handler_detects_30s_timeout`
  - Simulate hanging test (sleep 31 seconds)
  - Verify timeout detected at ~30 seconds (±100ms precision)
  - Assert DiagnosticContext returned
  - **MUST FAIL** until handler implemented

- [x] **T009** [P] Contract test for timeout diagnostics in `tests/contract/test_timeout_handler.py`
  - Test: `test_timeout_handler_captures_iris_query_history`
  - Execute SQL queries before timeout
  - Verify DiagnosticContext includes query history
  - Assert last 10 queries captured
  - **MUST FAIL** until diagnostics implemented

- [x] **T010** [P] Contract test for component identification in `tests/contract/test_timeout_handler.py`
  - Test: `test_timeout_handler_identifies_hanging_component`
  - Simulate different hanging scenarios (IRIS, PGWire, fixture, test)
  - Verify correct component identified from stack trace
  - Assert hanging_component field accurate
  - **MUST FAIL** until identification logic implemented

- [x] **T011** [P] Integration test for local execution in `tests/integration/test_developer_workflow.py`
  - Test: `test_local_test_execution_completes_without_hanging`
  - Run pytest programmatically via subprocess
  - Verify all tests execute sequentially
  - Assert no hanging processes remain
  - Check clear pass/fail reporting
  - **MUST FAIL** until framework configured

- [x] **T012** [P] Integration test for failure diagnostics in `tests/integration/test_developer_workflow.py`
  - Test: `test_local_test_failure_provides_actionable_diagnostics`
  - Trigger intentional test failure
  - Verify error message includes SQL executed
  - Assert IRIS connection state shown
  - Check namespace and duration included
  - **MUST FAIL** until diagnostic capture implemented

- [x] **T013** [P] Integration test for CI/CD execution in `tests/integration/test_ci_cd_workflow.py`
  - Test: `test_ci_cd_tests_match_local_execution`
  - Set CI=true environment variable
  - Run tests in non-interactive mode
  - Verify results match local execution
  - Assert coverage report generated
  - **MUST FAIL** until CI mode configured

## Phase 3.3: Core Implementation (ONLY after tests are failing)

- [x] **T014** Implement `embedded_iris` session-scoped fixture in `tests/conftest.py`
  - Initialize IRIS connection via `import iris`
  - Use irispython execution (NOT system Python)
  - Verify CallIn service enabled
  - Connect to localhost:1972, namespace=USER
  - Setup completes in <10 seconds
  - Yield iris.Connection instance
  - Teardown: Close connection, release resources

- [x] **T015** Implement `iris_config` session-scoped fixture in `tests/conftest.py`
  - Return dict with host, port, namespace, username, password
  - Values: localhost, 1972, USER, _SYSTEM, SYS
  - No dependencies, pure configuration

- [x] **T016** Implement `iris_clean_namespace` function-scoped fixture in `tests/conftest.py`
  - Depends on: embedded_iris fixture
  - Setup: Create transaction or snapshot namespace state
  - Yield: iris.Connection with clean state
  - Teardown: Drop test tables OR rollback transaction
  - Cleanup completes in <2 seconds

- [x] **T017** Implement `pgwire_client` function-scoped fixture in `tests/conftest.py`
  - Depends on: embedded_iris fixture
  - Setup: Start PGWire server if not running, create psycopg connection
  - Yield: psycopg.Connection instance
  - Teardown: Close connection, leave server running
  - Setup completes in <5 seconds

- [x] **T018** Implement `TimeoutHandler` class in `tests/timeout_handler.py`
  - __init__: Accept timeout_seconds parameter (default 30)
  - monitor_test(): Start background monitoring thread
  - capture_diagnostics(): Capture IRIS state, query history, connection info
  - terminate_process(): SIGTERM then SIGKILL if needed
  - Return DiagnosticContext on timeout, None on success

- [x] **T019** Implement `DiagnosticContext` dataclass in `tests/timeout_handler.py`
  - Fields: test_id, failure_type, elapsed_ms, timeout_threshold_ms
  - IRIS state: iris_connection_state, iris_namespace, iris_query_history, iris_process_id
  - Component: hanging_component (embedded_iris|pgwire|test_fixture|test_body)
  - Context: stack_trace, fixture_stack, environment_vars, log_excerpt

- [x] **T020** Implement pytest hook for timeout monitoring in `tests/conftest.py`
  - Hook: pytest_runtest_call
  - Create TimeoutHandler instance with 30s timeout
  - Monitor test execution
  - On timeout: Capture diagnostics, force exception
  - Attach DiagnosticContext to test item

- [x] **T021** Implement pytest hook for diagnostic capture in `tests/conftest.py`
  - Hook: pytest_runtest_makereport (wrapper, tryfirst)
  - Capture test reports for all phases (setup, call, teardown)
  - On failure: Capture IRIS connection state
  - Log query history (last 10 queries)
  - Write to test_failures.jsonl

- [x] **T022** Implement IRIS state capture function in `tests/conftest.py`
  - Function: capture_iris_state()
  - Query %Library.ProcessInfo for active processes
  - Get connection count and license usage
  - Return dict with process info, connections, system metrics
  - Handle errors gracefully (return error dict)

- [x] **T023** Implement component identification logic in `tests/timeout_handler.py`
  - Analyze stack trace to identify hanging component
  - iris.connect() or iris.cursor.execute() → embedded_iris
  - psycopg.connect() or cursor.execute() → pgwire
  - conftest.py in traceback → test_fixture
  - Test file path in traceback → test_body
  - Set DiagnosticContext.hanging_component field

## Phase 3.4: Integration & Polish

- [x] **T024** [P] Add flaky test detection configuration in `pyproject.toml`
  - Add pytest-flaky>=3.8.0 to test dependencies
  - Configure exception-based retry filter
  - Document flaky test marking strategy

- [x] **T025** [P] Create flaky test tracking document in `tests/flaky_tests.md`
  - Template for tracking flaky tests
  - Sections: test name, status, frequency, cause, mitigation, fix target
  - Instructions for marking tests as @pytest.mark.flaky

- [x] **T026** [P] Update `.gitlab-ci.yml` for sequential test execution
  - Add test stage with pytest command
  - Use --dist no flag (ensure sequential)
  - Generate coverage reports (terminal + XML)
  - Upload coverage to CI artifacts
  - No parallel test execution

- [x] **T027** [P] Create quickstart validation script in `tests/validate_framework.py`
  - Executable script to run all quickstart validations
  - Check pytest.ini configuration
  - Verify fixtures work correctly
  - Test timeout detection
  - Validate diagnostic capture
  - Report success/failure for each criterion

- [x] **T028** [P] Update `README.md` with test execution instructions
  - Section: Running Tests
  - Local execution: pytest -v
  - Coverage reports: pytest --cov --cov-report=html
  - Individual tests: pytest tests/path/to/test.py::test_name
  - Timeout configuration: @pytest.mark.timeout(60)
  - CI/CD integration notes

- [x] **T029** [P] Create test documentation in `docs/testing.md`
  - Overview of testing framework
  - Fixture usage guide (embedded_iris, iris_clean_namespace, pgwire_client)
  - Timeout configuration examples
  - Diagnostic capture explanation
  - Flaky test handling
  - Best practices for writing tests

- [x] **T030** Run full test suite and verify all criteria met
  - Execute: pytest -v
  - Verify: All contract tests pass
  - Verify: Timeout detection works (run T008)
  - Verify: Diagnostic capture works (run T012)
  - Verify: Coverage report generated (>0% baseline)
  - Verify: No hanging processes after execution
  - Verify: Sequential execution (check timing logs)

## Dependencies

### Strict Ordering
- **Setup before Tests**: T001-T003 must complete before T004-T013
- **Tests before Implementation**: T004-T013 must FAIL before starting T014-T023
- **Fixtures before Timeout Handler**: T014-T017 must complete before T018-T023
- **Core before Integration**: T014-T023 must complete before T024-T030

### Parallel Execution Groups

**Group 1: Configuration (T001-T003)**
- All [P] - can run in parallel (different files)

**Group 2: Contract Tests (T004-T010)**
- All [P] - can run in parallel (different test files)

**Group 3: Integration Tests (T011-T013)**
- All [P] - can run in parallel (different test files)

**Group 4: Fixtures (T014-T017)**
- SEQUENTIAL - all modify tests/conftest.py

**Group 5: Timeout Handler (T018-T023)**
- T018-T019 [P] - different files (timeout_handler.py)
- T020-T023 SEQUENTIAL - all modify conftest.py

**Group 6: Polish (T024-T029)**
- All [P] - different files

## Parallel Execution Examples

### Launch Group 1 (Configuration) in Parallel:
```bash
# Create all 3 config files simultaneously
Task 1: "Configure pytest timeout and coverage in pyproject.toml"
Task 2: "Update .gitignore for test artifacts"
Task 3: "Create pytest markers in pyproject.toml"
```

### Launch Group 2 (Contract Tests) in Parallel:
```bash
# Write all contract tests simultaneously
Task 1: "Contract test for embedded_iris fixture in tests/contract/test_fixture_contract.py"
Task 2: "Contract test for embedded_iris cleanup in tests/contract/test_fixture_contract.py"
Task 3: "Contract test for iris_clean_namespace fixture in tests/contract/test_fixture_contract.py"
Task 4: "Contract test for pgwire_client fixture in tests/contract/test_fixture_contract.py"
Task 5: "Contract test for timeout handler in tests/contract/test_timeout_handler.py"
Task 6: "Contract test for timeout diagnostics in tests/contract/test_timeout_handler.py"
Task 7: "Contract test for component identification in tests/contract/test_timeout_handler.py"
```

### Launch Group 6 (Polish) in Parallel:
```bash
# Documentation and CI updates simultaneously
Task 1: "Add flaky test detection configuration in pyproject.toml"
Task 2: "Create flaky test tracking document in tests/flaky_tests.md"
Task 3: "Update .gitlab-ci.yml for sequential test execution"
Task 4: "Create quickstart validation script in tests/validate_framework.py"
Task 5: "Update README.md with test execution instructions"
Task 6: "Create test documentation in docs/testing.md"
```

## Task Validation Checklist

- [x] All contracts have corresponding tests (T004-T010 → contracts in spec)
- [x] All entities have implementation tasks (TestConfiguration→T001, TestFixture→T014-T017, TimeoutHandler→T018-T019, DiagnosticContext→T019)
- [x] All tests come before implementation (T004-T013 before T014-T023)
- [x] Parallel tasks truly independent (all [P] tasks are different files)
- [x] Each task specifies exact file path
- [x] No task modifies same file as another [P] task (verified: conftest.py tasks are sequential)

## Success Criteria

All tasks complete when:
- [ ] pytest.ini configured with 30s timeout, coverage, sequential execution
- [ ] All contract tests written and initially failing
- [ ] All contract tests now passing
- [ ] embedded_iris, iris_clean_namespace, pgwire_client fixtures implemented
- [ ] TimeoutHandler detects 30s timeout with diagnostics
- [ ] DiagnosticContext captures IRIS state, query history, component identification
- [ ] Failure messages include SQL, IRIS state, stack traces
- [ ] Coverage tracked but not enforced
- [ ] Flaky test detection configured
- [ ] CI/CD configured for sequential execution
- [ ] Documentation updated (README.md, docs/testing.md)
- [ ] Full test suite passes: `pytest -v`
- [ ] Quickstart validation script reports all criteria met

## Notes

- **TDD Required**: Verify all contract tests fail before implementing (T004-T013)
- **No Parallel Execution**: Tests MUST run sequentially (single IRIS instance)
- **Timeout Precision**: Use time.perf_counter() for microsecond-precision timing
- **IRIS-Specific Diagnostics**: Capture query history, connection state, process info
- **Commit Strategy**: Commit after each phase completes
- **Constitutional Compliance**: Follows Test-First Development and NO MOCKS principles

# Implementation Plan: Correct Testing Framework Additions

**Branch**: `017-correct-testing-framework` | **Date**: 2025-10-04 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/017-correct-testing-framework/spec.md`

## Summary
Modernize the IRIS PGWire testing framework to eliminate hanging processes, improve failure diagnostics, and ensure reliable test execution against embedded IRIS. The framework will execute tests sequentially with 30-second timeout detection, comprehensive diagnostic output, and informational code coverage tracking.

## Technical Context
**Language/Version**: Python 3.11+
**Primary Dependencies**: pytest 7.0+, pytest-timeout 2.1+, pytest-cov 4.0+, intersystems-irispython
**Storage**: Embedded IRIS via irispython (no external Docker instances)
**Testing**: pytest with embedded IRIS fixtures, sequential execution only
**Target Platform**: macOS/Linux development environments, GitLab CI/CD
**Project Type**: Single project (asyncio-based server with embedded IRIS)
**Performance Goals**: All tests complete within 30 seconds, timeout detection triggers process termination
**Constraints**: Sequential execution only, embedded IRIS exclusive access, no parallel test execution
**Scale/Scope**: ~50-100 test cases across unit/integration/e2e categories

## Constitution Check
*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Principle I: Protocol Fidelity
✅ **COMPLIANT** - Testing framework validates PostgreSQL protocol compliance via real client testing (psql, psycopg)

### Principle II: Test-First Development
✅ **COMPLIANT** - Framework enforces E2E tests with real clients before implementation. This feature improves that foundation.

### Principle III: Phased Implementation
✅ **COMPLIANT** - Testing framework supports the P0-P6 phase validation sequence

### Principle IV: IRIS Integration
✅ **COMPLIANT** - Tests run against embedded IRIS via irispython, matching production patterns. CallIn service enabled via merge.cpf.

### Principle V: Production Readiness
✅ **COMPLIANT** - Improved diagnostics and hang detection enhance production readiness

### Principle VI: Vector Performance Requirements
✅ **COMPLIANT** - Testing framework validates vector performance benchmarks against constitutional thresholds

**Constitution Status**: No violations. Feature aligns with constitutional principles.

## Project Structure

### Documentation (this feature)
```
specs/017-correct-testing-framework/
├── plan.md              # This file (/plan command output)
├── research.md          # Phase 0 output (/plan command)
├── data-model.md        # Phase 1 output (/plan command)
├── quickstart.md        # Phase 1 output (/plan command)
├── contracts/           # Phase 1 output (/plan command)
└── tasks.md             # Phase 2 output (/tasks command - NOT created by /plan)
```

### Source Code (repository root)
```
src/iris_pgwire/
├── server.py
├── protocol.py
├── iris_executor.py
└── vector_optimizer.py

tests/
├── conftest.py          # pytest fixtures (embedded IRIS, timeout handling)
├── unit/                # Unit tests (no IRIS dependency)
├── integration/         # Integration tests (embedded IRIS required)
└── e2e/                 # End-to-end tests (real clients + embedded IRIS)

.gitlab-ci.yml           # CI/CD configuration (sequential test execution)
pytest.ini               # pytest configuration (timeout, coverage, sequential)
```

**Structure Decision**: Single project structure with clear test categorization. Tests execute sequentially against shared embedded IRIS instance accessed via irispython. Fixtures manage IRIS lifecycle and resource cleanup.

## Phase 0: Outline & Research

### Research Tasks

1. **pytest-timeout best practices**
   - How to configure per-test timeouts
   - How to capture diagnostic information on timeout
   - Integration with pytest fixtures for cleanup

2. **Embedded IRIS fixture patterns**
   - Session-scoped vs function-scoped fixtures
   - Namespace cleanup between tests
   - Connection pooling for test performance
   - Detecting and killing hanging IRIS operations

3. **Sequential test execution patterns**
   - pytest-xdist configuration (disable parallel)
   - Resource locking for exclusive access
   - Test ordering strategies

4. **pytest-cov configuration**
   - Coverage reporting without enforcement
   - Integration with CI/CD pipelines
   - HTML vs terminal reports

5. **Flaky test detection**
   - pytest-flaky plugin vs manual detection
   - Test result history tracking
   - Retry policies for truly flaky tests

6. **Diagnostic output on failure/timeout**
   - Capturing IRIS process state
   - Stack traces with full context
   - Integration with pytest reporting

### Output
All findings consolidated in `research.md` with decisions, rationale, and alternatives considered.

## Phase 1: Design & Contracts

### 1. Data Model (`data-model.md`)

**Entities**:
- **TestConfiguration**: pytest.ini settings (timeout=30s, sequential=true, coverage=true)
- **TestFixture**: pytest fixtures (iris_connection, iris_namespace, cleanup_handler)
- **TestReport**: pytest execution results (pass/fail, duration, coverage %, flaky status)
- **TimeoutHandler**: Component monitoring test duration, capturing diagnostics, terminating processes
- **DiagnosticContext**: State captured on failure (SQL executed, IRIS connection state, stack trace)

**State Transitions**:
```
Test Execution Flow:
PENDING → IN_PROGRESS → (SUCCESS | FAILURE | TIMEOUT)

Timeout Detection:
IN_PROGRESS → TIMEOUT (after 30s) → DIAGNOSTIC_CAPTURE → PROCESS_KILL
```

### 2. API Contracts (`contracts/`)

Testing framework doesn't expose external APIs, but has internal contracts:

**Fixture Contract** (`contracts/pytest-fixtures.md`):
```python
@pytest.fixture(scope="session")
def embedded_iris():
    """
    Returns: iris.Connection instance
    Guarantees: CallIn service enabled, USER namespace active
    Cleanup: Connection closed, resources released
    Timeout: Fixture setup completes in <5 seconds
    """

@pytest.fixture(scope="function")
def iris_clean_namespace(embedded_iris):
    """
    Returns: iris.Connection with clean namespace
    Guarantees: No conflicting test data from previous tests
    Cleanup: Tables created during test are dropped
    Timeout: Cleanup completes in <2 seconds
    """
```

**Timeout Handler Contract** (`contracts/timeout-handler.md`):
```python
class TimeoutHandler:
    def monitor_test(test_id: str, timeout_seconds: int = 30):
        """
        Monitors test execution, captures diagnostics on timeout.

        Returns: DiagnosticContext on timeout, None on success
        Side Effects: Terminates hanging process after timeout
        Diagnostic Output: IRIS state, SQL history, connection status
        """
```

### 3. Contract Tests

Create failing contract tests in `tests/contract/`:

**test_fixture_contract.py**:
```python
def test_embedded_iris_fixture_provides_connection(embedded_iris):
    """Verify embedded_iris fixture returns valid IRIS connection"""
    assert embedded_iris is not None
    # This will fail until fixture implemented
    cursor = embedded_iris.cursor()
    cursor.execute("SELECT 1")
    assert cursor.fetchone()[0] == 1

def test_embedded_iris_fixture_cleanup_releases_resources(embedded_iris):
    """Verify fixture cleanup releases IRIS resources"""
    # Track connection before fixture teardown
    # Verify cleanup after test completes
    pass  # Will fail until cleanup implemented

def test_iris_clean_namespace_isolates_test_data(iris_clean_namespace):
    """Verify namespace isolation between tests"""
    # Create test table
    # Verify it doesn't exist in next test
    pass  # Will fail until isolation implemented
```

**test_timeout_handler.py**:
```python
def test_timeout_handler_detects_hanging_test():
    """Verify timeout handler terminates test after 30 seconds"""
    # Simulate hanging test
    # Verify timeout detection
    # Verify process termination
    pass  # Will fail until handler implemented

def test_timeout_handler_captures_diagnostics():
    """Verify diagnostic context includes IRIS state on timeout"""
    # Simulate timeout
    # Verify DiagnosticContext includes SQL, connection state
    pass  # Will fail until diagnostics implemented
```

### 4. Integration Test Scenarios (from user stories)

**test_developer_runs_tests_locally.py**:
```python
def test_local_test_execution_completes_without_hanging():
    """
    Given: Developer has made code changes
    When: They run pytest locally
    Then: All tests execute sequentially with clear reporting
    """
    # Run pytest programmatically
    # Verify no hanging processes
    # Verify clear pass/fail output
    pass

def test_local_test_failure_provides_actionable_diagnostics():
    """
    Given: Test fails
    When: pytest execution completes
    Then: Error message includes SQL, IRIS state, stack trace
    """
    pass
```

**test_ci_cd_execution.py**:
```python
def test_ci_cd_tests_match_local_execution():
    """
    Given: Code pushed to feature branch
    When: CI/CD pipeline runs
    Then: Tests execute sequentially with consistent results
    """
    pass
```

### 5. Update CLAUDE.md

Run the update script:
```bash
.specify/scripts/bash/update-agent-context.sh claude
```

Expected additions to CLAUDE.md:
- pytest-timeout configuration patterns
- Embedded IRIS fixture best practices
- Sequential test execution configuration
- Diagnostic capture on test failure/timeout

**Output**: data-model.md, contracts/pytest-fixtures.md, contracts/timeout-handler.md, failing contract tests, quickstart.md, CLAUDE.md updated

## Phase 2: Task Planning Approach
*This section describes what the /tasks command will do - DO NOT execute during /plan*

**Task Generation Strategy**:
- Load `.specify/templates/tasks-template.md` as base
- Generate tasks from Phase 1 design docs
- Each contract → contract test task [P]
- Each fixture → implementation task (sequential, not parallel)
- Each user story → integration test task
- Configuration tasks for pytest.ini, CI/CD updates

**Task Categories**:
1. **Configuration Tasks**: pytest.ini setup, .gitlab-ci.yml updates
2. **Fixture Implementation**: embedded_iris, iris_clean_namespace, timeout monitoring
3. **Timeout Handler**: Process monitoring, diagnostic capture, termination logic
4. **Contract Tests**: Validate fixtures meet contracts (run first, fail initially)
5. **Integration Tests**: E2E scenarios from user stories
6. **Documentation**: Update README.md with test execution instructions

**Ordering Strategy**:
1. TDD order: Contract tests → Fixture implementation → Integration tests
2. Dependency order: Configuration → Core fixtures → Advanced features
3. Mark [P] for independent configuration files only (pytest.ini, .gitlab-ci.yml can be done in parallel)

**Estimated Output**: 20-25 numbered, ordered tasks in tasks.md

**IMPORTANT**: This phase is executed by the /tasks command, NOT by /plan

## Phase 3+: Future Implementation
*These phases are beyond the scope of the /plan command*

**Phase 3**: Task execution (/tasks command creates tasks.md)
**Phase 4**: Implementation (execute tasks.md following constitutional principles)
**Phase 5**: Validation (run tests, execute quickstart.md, verify timeout handling works)

## Complexity Tracking
*No constitutional violations - section left empty*

## Progress Tracking
*This checklist is updated during execution flow*

**Phase Status**:
- [x] Phase 0: Research complete (/plan command)
- [x] Phase 1: Design complete (/plan command)
- [x] Phase 2: Task planning complete (/plan command - describe approach only)
- [x] Phase 3: Tasks generated (/tasks command)
- [ ] Phase 4: Implementation complete
- [ ] Phase 5: Validation passed

**Gate Status**:
- [x] Initial Constitution Check: PASS
- [x] Post-Design Constitution Check: PASS
- [x] All research questions resolved
- [x] Complexity deviations documented (N/A - no violations)

**Phase 0 Deliverables**:
- [x] research.md created with pytest-timeout, pytest-cov, embedded IRIS fixture patterns
- [x] All technical unknowns resolved
- [x] Best practices documented

**Phase 1 Deliverables**:
- [x] data-model.md created (TestConfiguration, TestFixture, TestReport, TimeoutHandler, DiagnosticContext)
- [x] contracts/pytest-fixtures.md created (fixture interface contracts)
- [x] contracts/timeout-handler.md created (timeout handler contract)
- [x] quickstart.md created (validation test scenarios)
- [x] CLAUDE.md updated with testing framework context

**Ready for /tasks command**: ✅

---
*Based on Constitution v1.2.1 - See `.specify/memory/constitution.md`*

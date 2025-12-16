# Quickstart: Testing Framework Validation

## Purpose
This quickstart validates that the modernized testing framework meets all functional requirements from the specification. Follow these steps to verify the implementation is complete and working correctly.

## Prerequisites

- Python 3.11+ installed
- IRIS container running locally (port 1972)
- PGWire server can be started (port 5434)
- pytest, pytest-timeout, pytest-cov installed

## Setup

```bash
# Install dependencies
pip install pytest pytest-timeout pytest-cov psycopg

# Verify IRIS is running
python -c "import iris; conn = iris.connect(hostname='localhost', port=1972, namespace='USER', username='_SYSTEM', password='SYS'); print('✅ IRIS connected')"

# Verify pytest configuration
pytest --co -q  # Should show test collection
```

## Validation Tests

### 1. Test Configuration (FR-001 to FR-006)

**Test**: Verify pytest.ini configuration
```bash
# Check pytest configuration
cat pytest.ini | grep -E "timeout|addopts|markers"

# Expected output:
# timeout = 30
# addopts = --cov=iris_pgwire --cov-report=term --cov-report=html -p no:xdist
# markers = timeout: Override default timeout
```

**Validation**: Configuration file exists and contains timeout, coverage, sequential execution settings.

---

### 2. Test Execution Reliability (FR-001, FR-002, FR-003)

**Test**: Run full test suite locally
```bash
# Run all tests
pytest -v

# Expected output:
# ===== test session starts =====
# tests/unit/test_*.py::test_*               PASSED
# tests/integration/test_*.py::test_*        PASSED
# tests/e2e/test_*.py::test_*                PASSED
# ===== X passed in Y.YYs =====
```

**Validation Criteria**:
- ✅ All tests pass (no failures)
- ✅ Clear pass/fail status displayed
- ✅ No hanging processes (completes within reasonable time)
- ✅ Coverage report displayed at end

---

### 3. Sequential Execution (FR-006)

**Test**: Verify tests run sequentially (not in parallel)
```bash
# Run with verbose output
pytest -v --tb=short

# Watch for test execution order (should be sequential)
# Each test should start AFTER previous test completes
```

**Validation Criteria**:
- ✅ Tests execute one at a time (no concurrent execution)
- ✅ No resource conflicts reported
- ✅ Deterministic execution order

---

### 4. Embedded IRIS Fixtures (FR-007 to FR-011)

**Test**: Run contract tests for fixtures
```bash
# Test embedded_iris fixture
pytest tests/contract/test_fixture_contract.py::test_embedded_iris_fixture_provides_connection -v

# Test iris_clean_namespace fixture
pytest tests/contract/test_fixture_contract.py::test_iris_clean_namespace_isolates_test_data -v

# Test pgwire_client fixture
pytest tests/contract/test_fixture_contract.py::test_pgwire_client_connects_successfully -v
```

**Validation Criteria**:
- ✅ embedded_iris returns valid IRIS connection
- ✅ iris_clean_namespace isolates test data between tests
- ✅ pgwire_client connects to PGWire server successfully
- ✅ Fixtures complete setup in < 10 seconds (session) or < 2 seconds (function)

---

### 5. Timeout Detection (FR-005, FR-013, FR-014, FR-015)

**Test**: Verify 30-second timeout handling
```bash
# Run timeout test (should timeout after 30 seconds)
pytest tests/contract/test_timeout_handler.py::test_timeout_handler_detects_30s_timeout -v

# Expected output:
# tests/contract/test_timeout_handler.py::test_timeout_handler_detects_30s_timeout TIMEOUT
# ===== TIMEOUT: Test exceeded 30s threshold =====
# Hanging component: test_body
# IRIS connection state: connected
# Last SQL: SELECT * FROM ...
```

**Validation Criteria**:
- ✅ Timeout detected at ~30 seconds (±100ms)
- ✅ Test terminated cleanly
- ✅ Diagnostic output includes:
  - Hanging component identification
  - IRIS connection state
  - Last SQL queries executed
  - Stack trace

---

### 6. Failure Diagnostics (FR-012, FR-024)

**Test**: Verify actionable error messages
```bash
# Run failing test
pytest tests/integration/test_diagnostic_capture.py::test_failure_with_diagnostics -v

# Expected output:
# tests/integration/test_diagnostic_capture.py::test_failure_with_diagnostics FAILED
# ===== FAILURES =====
# AssertionError: Expected 1, got 0
#
# Diagnostic Context:
# - SQL Executed: SELECT COUNT(*) FROM test_table WHERE id = 999
# - IRIS Connection: connected
# - Namespace: USER
# - Test Duration: 1.23s
```

**Validation Criteria**:
- ✅ Error message includes SQL executed
- ✅ IRIS connection state shown
- ✅ Namespace and duration included
- ✅ Stack trace provides line-level detail

---

### 7. Coverage Reporting (FR-016, FR-017, FR-025)

**Test**: Verify coverage is tracked but not enforced
```bash
# Run tests with coverage
pytest --cov=iris_pgwire --cov-report=term

# Expected output:
# Name                              Stmts   Miss  Cover
# -----------------------------------------------------
# iris_pgwire/__init__.py              10      2    80%
# iris_pgwire/server.py               150     30    80%
# iris_pgwire/protocol.py             200     50    75%
# -----------------------------------------------------
# TOTAL                               360     82    77%
```

**Validation Criteria**:
- ✅ Coverage metrics displayed
- ✅ No coverage threshold enforced (tests pass even if coverage < 100%)
- ✅ HTML report generated in htmlcov/

---

### 8. Flaky Test Detection (FR-018, FR-019)

**Test**: Run flaky test multiple times
```bash
# Run test 10 times to detect flakiness
pytest tests/integration/test_flaky_detection.py -v --count=10

# Expected output:
# tests/integration/test_flaky_detection.py::test_intermittent PASSED (7/10)
# tests/integration/test_flaky_detection.py::test_intermittent FAILED (3/10)
# ===== FLAKY TEST DETECTED =====
# Test passed 70% of the time (7/10)
```

**Validation Criteria**:
- ✅ Flaky tests identified (pass rate > 0% and < 100%)
- ✅ Pass rate reported
- ✅ Flaky status tracked separately from consistent failures

---

### 9. CI/CD Integration (FR-002)

**Test**: Simulate CI/CD execution
```bash
# Run tests in CI mode (no interactive output)
CI=true pytest --tb=short --color=no

# Expected output:
# ===== test session starts =====
# tests/unit/test_*.py .....
# tests/integration/test_*.py .....
# tests/e2e/test_*.py .....
# ===== X passed in Y.YYs =====
# Coverage: 77%
```

**Validation Criteria**:
- ✅ Tests run successfully in CI environment
- ✅ Non-interactive output format
- ✅ Coverage report generated
- ✅ Exit code 0 on success, non-zero on failure

---

### 10. Resource Cleanup (FR-008, FR-009, FR-010)

**Test**: Verify IRIS resources are cleaned up after tests
```bash
# Run test that creates tables
pytest tests/integration/test_resource_cleanup.py -v

# After test completes, verify cleanup
python -c "
import iris
conn = iris.connect(hostname='localhost', port=1972, namespace='USER', username='_SYSTEM', password='SYS')
cursor = conn.cursor()
cursor.execute('SHOW TABLES')
tables = cursor.fetchall()
print(f'Tables remaining: {len(tables)}')
# Should show 0 test tables
"
```

**Validation Criteria**:
- ✅ Test tables dropped after test execution
- ✅ IRIS connections closed
- ✅ No resource leaks detected

---

## Success Criteria

All of the following must be true for the testing framework to be considered complete:

- [ ] **Configuration**: pytest.ini contains 30s timeout, sequential execution, coverage settings (FR-001 to FR-006)
- [ ] **Fixtures**: embedded_iris, iris_clean_namespace, pgwire_client fixtures work correctly (FR-007 to FR-011)
- [ ] **Timeout Detection**: 30-second timeout triggers process termination with diagnostics (FR-005, FR-013 to FR-015)
- [ ] **Diagnostics**: Failure messages include SQL, IRIS state, stack traces (FR-012, FR-024)
- [ ] **Coverage**: Coverage tracked but not enforced (FR-016, FR-017, FR-025)
- [ ] **Flaky Detection**: Flaky tests identified and reported separately (FR-018, FR-019)
- [ ] **CI/CD**: Tests run successfully in CI environment (FR-002)
- [ ] **Resource Cleanup**: IRIS resources cleaned up after tests (FR-008 to FR-010)
- [ ] **Documentation**: README.md updated with test execution instructions (FR-023)

## Troubleshooting

### IRIS Connection Failures
```bash
# Check IRIS is running
docker ps | grep iris

# Check CallIn service enabled
python -c "import iris; print('CallIn enabled')"
# If error: Enable CallIn service via merge.cpf
```

### Timeout Not Triggering
```bash
# Verify pytest-timeout installed
pip show pytest-timeout

# Check pytest.ini configuration
cat pytest.ini | grep timeout
```

### Coverage Not Reporting
```bash
# Verify pytest-cov installed
pip show pytest-cov

# Check coverage configuration
pytest --cov=iris_pgwire --cov-report=term
```

### Tests Hanging
```bash
# Kill hanging pytest processes
pkill -f pytest

# Check IRIS connection pool
python -c "
import iris
# Check active connections
"
```

## Next Steps

After all validation tests pass:

1. Run full test suite: `pytest -v`
2. Generate coverage report: `pytest --cov=iris_pgwire --cov-report=html`
3. Review flaky test report: Check for tests with intermittent failures
4. Update CI/CD pipeline: Ensure `.gitlab-ci.yml` uses new configuration
5. Document test execution: Update README.md with instructions

## References

- Specification: `specs/017-correct-testing-framework/spec.md`
- Data Model: `specs/017-correct-testing-framework/data-model.md`
- Contracts: `specs/017-correct-testing-framework/contracts/`
- Constitution: `.specify/memory/constitution.md`

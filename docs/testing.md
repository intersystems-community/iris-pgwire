# IRIS PGWire Testing Framework Documentation

**Version**: 1.0
**Last Updated**: 2025-10-04
**Specification**: `specs/017-correct-testing-framework/`

---

## Table of Contents

1. [Overview](#overview)
2. [Quick Start](#quick-start)
3. [Testing Framework Architecture](#testing-framework-architecture)
4. [Fixtures Reference](#fixtures-reference)
5. [Timeout Configuration](#timeout-configuration)
6. [Diagnostic Capture](#diagnostic-capture)
7. [Flaky Test Handling](#flaky-test-handling)
8. [Best Practices](#best-practices)
9. [CI/CD Integration](#cicd-integration)
10. [Troubleshooting](#troubleshooting)

---

## Overview

The IRIS PGWire testing framework provides a modern, comprehensive testing solution specifically designed for IRIS embedded Python and PostgreSQL wire protocol testing.

### Key Features

✅ **30-Second Timeout Detection**: Automatically detects and terminates hanging tests with comprehensive diagnostics
✅ **Sequential Execution**: Tests run one at a time for predictable IRIS state
✅ **Coverage Tracking**: Informational coverage reports (no enforcement)
✅ **Flaky Test Detection**: Automatic retry mechanisms for unreliable tests
✅ **IRIS State Capture**: Diagnostic information on failures (SQL history, connection state)
✅ **Real Connections**: NO MOCKS - all tests use real IRIS and PostgreSQL clients

### Constitutional Compliance

This framework follows the project's constitutional principles:
- **Principle I**: Test-First Development (TDD)
- **Principle II**: NO MOCKS (real IRIS connections)
- **Principle III**: Protocol Fidelity (real PostgreSQL clients)
- **Principle V**: Diagnostic Excellence (comprehensive failure capture)

---

## Quick Start

### Installation

```bash
# Install test dependencies
pip install -e ".[test]"

# Or with uv
uv sync --frozen --group test
```

### Running Tests

```bash
# Run all tests
pytest -v

# Run with coverage
pytest --cov --cov-report=html
open htmlcov/index.html

# Run specific test file
pytest tests/contract/test_fixture_contract.py -v

# Run specific test
pytest tests/integration/test_developer_workflow.py::test_local_test_execution_completes_without_hanging -v
```

### Validate Framework

```bash
# Verify framework is correctly configured
python tests/validate_framework.py

# Expected output:
# ✓ pytest.ini configured with timeout, coverage, sequential execution
# ✓ embedded_iris fixture implemented
# ✓ TimeoutHandler class defined
# 🎉 All validation criteria passed!
```

---

## Testing Framework Architecture

### Components

```
tests/
├── conftest.py              # Fixtures and pytest hooks
├── timeout_handler.py       # Timeout detection and diagnostics
├── flaky_tests.md          # Flaky test registry
├── validate_framework.py    # Framework validation script
├── contract/               # Contract tests (fixture validation)
│   ├── test_fixture_contract.py
│   └── test_timeout_handler.py
├── integration/            # Integration tests (E2E workflows)
│   ├── test_developer_workflow.py
│   └── test_ci_cd_workflow.py
└── [your test files]
```

### Execution Flow

```
Test Start
    ↓
Session Setup (embedded_iris fixture)
    ↓
Function Setup (iris_clean_namespace fixture)
    ↓
Test Execution (with 30s timeout monitoring)
    ↓
    ├→ Success: Clean exit
    ├→ Failure: Capture diagnostics → test_failures.jsonl
    └→ Timeout: Terminate process → DiagnosticContext
    ↓
Function Teardown (cleanup test data)
    ↓
Session Teardown (close IRIS connection)
```

---

## Fixtures Reference

### `embedded_iris` (Session-Scoped)

**Purpose**: Provides IRIS embedded Python connection for entire test session

**Returns**: `iris.Connection` instance

**Setup Time**: <10 seconds

**Example**:
```python
def test_iris_query(embedded_iris):
    """Test IRIS query execution."""
    cursor = embedded_iris.cursor()
    cursor.execute("SELECT 1")
    result = cursor.fetchone()
    assert result[0] == 1
    cursor.close()
```

**Requirements**:
- Must run tests via `irispython -m pytest` (not system Python)
- IRIS CallIn service must be enabled
- IRIS running on localhost:1972

**Cleanup**: Connection closed at end of session

---

### `iris_config` (Session-Scoped)

**Purpose**: Provides IRIS connection configuration

**Returns**: Dictionary with connection parameters

**Example**:
```python
def test_connection_params(iris_config):
    """Test connection configuration."""
    assert iris_config['host'] == 'localhost'
    assert iris_config['port'] == 1972
    assert iris_config['namespace'] == 'USER'
```

**Configuration**:
```python
{
    'host': 'localhost',
    'port': 1972,
    'namespace': 'USER',
    'username': '_SYSTEM',
    'password': 'SYS'
}
```

---

### `iris_clean_namespace` (Function-Scoped)

**Purpose**: Provides clean IRIS namespace for each test function

**Returns**: `iris.Connection` with isolated namespace state

**Cleanup Time**: <2 seconds

**Example**:
```python
def test_data_isolation(iris_clean_namespace):
    """Test data is isolated between tests."""
    cursor = iris_clean_namespace.cursor()

    # Create test table
    cursor.execute("""
        CREATE TABLE test_data (
            id INT PRIMARY KEY,
            value VARCHAR(50)
        )
    """)

    cursor.execute("INSERT INTO test_data VALUES (1, 'test')")
    iris_clean_namespace.commit()

    # Verify data
    cursor.execute("SELECT COUNT(*) FROM test_data")
    assert cursor.fetchone()[0] == 1

    cursor.close()
    # Table automatically dropped in teardown
```

**Isolation Strategy**:
- Tracks tables created during test
- Drops new tables in teardown
- Commits cleanup changes
- Ensures <2 second cleanup time

---

### `pgwire_client` (Function-Scoped)

**Purpose**: Provides PostgreSQL wire protocol client connection

**Returns**: `psycopg.Connection` instance

**Setup Time**: <5 seconds

**Example**:
```python
def test_pgwire_query(pgwire_client):
    """Test query through PGWire protocol."""
    with pgwire_client.cursor() as cursor:
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        assert result[0] == 1
```

**Requirements**:
- PGWire server running on port 5434
- psycopg3 installed (`pip install psycopg>=3.1.0`)

**Cleanup**: Connection closed after test

---

## Timeout Configuration

### Global Default (30 Seconds)

Configured in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
timeout = 30
timeout_func_only = false  # Include fixture time in timeout
```

All tests automatically timeout after 30 seconds (including fixture setup/teardown).

### Override Timeout

```python
import pytest

# Extend timeout for slow tests
@pytest.mark.timeout(60)
def test_long_running_operation():
    """Test that takes 45 seconds."""
    # Long-running operation
    pass

# Mark test as slow (>10 seconds)
@pytest.mark.slow
def test_slow_database_operation():
    """Test that takes 15 seconds."""
    # Will show up in reports as "slow"
    pass
```

### Timeout Precision

Timeout detection has ±100ms precision using `time.perf_counter()`:

```python
# tests/timeout_handler.py
def _monitor_loop(self, test_id: str, start_time: float):
    """Background monitoring with ±100ms precision."""
    while not self._stop_event.is_set():
        elapsed = time.perf_counter() - start_time
        if elapsed >= self.timeout_seconds:
            break
        time.sleep(0.05)  # 50ms intervals for precise detection
```

---

## Diagnostic Capture

### Failure Diagnostics

When a test fails, the framework captures:

1. **Test Identification**
   - Test ID (nodeid)
   - Phase (setup, call, teardown)
   - Duration

2. **IRIS State**
   - Connection state (connected, disconnected, hung)
   - Active namespace
   - Last 10 SQL queries executed
   - IRIS process ID

3. **Error Context**
   - Error message and type
   - Stack trace
   - Environment variables
   - Fixture stack

4. **Output**
   - Written to `test_failures.jsonl`
   - Structured JSON for analysis

### Example Diagnostic Output

```json
{
  "test_id": "tests/contract/test_fixture_contract.py::test_embedded_iris_fixture_provides_connection",
  "phase": "call",
  "duration_ms": 125.5,
  "failure_type": "assertion_error",
  "error_message": "AssertionError: Connection verification failed",
  "iris_state": {
    "status": "success",
    "process_info": {
      "connection_count": 1,
      "license_usage": 0
    },
    "query_history": [
      "SELECT 1",
      "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES"
    ]
  },
  "timestamp": 1696352400.123
}
```

### Timeout Diagnostics

When a test times out, `TimeoutHandler` captures:

```python
DiagnosticContext(
    test_id="tests/integration/test_slow_query.py::test_times_out",
    failure_type="timeout",
    elapsed_ms=30150.0,
    timeout_threshold_ms=30000.0,
    iris_connection_state="connected",
    iris_namespace="USER",
    iris_query_history=["SELECT * FROM large_table", ...],
    iris_process_id=12345,
    hanging_component="embedded_iris",  # or pgwire, test_fixture, test_body
    stack_trace="...",
    fixture_stack=["embedded_iris", "iris_clean_namespace"],
    environment_vars={"IRIS_HOST": "localhost", ...},
    log_excerpt="Last 50 lines..."
)
```

### Component Identification

The framework identifies which component timed out:

| Component | Detection Pattern | Example Stack Trace |
|-----------|-------------------|---------------------|
| `embedded_iris` | `iris.py`, `iris.connect`, `iris.cursor` | `File "iris.py" in execute()` |
| `pgwire` | `psycopg`, `pgwire`, `postgres` | `File "psycopg/connection.py" in connect()` |
| `test_fixture` | `conftest.py`, `@pytest.fixture` | `File "conftest.py" in iris_clean_namespace()` |
| `test_body` | `test_*.py`, `def test_` | `File "test_query.py" in test_something()` |

---

## Flaky Test Handling

### Marking Flaky Tests

```python
import pytest

# Basic flaky test (1 retry, no delay)
@pytest.mark.flaky
def test_occasionally_fails():
    """Test with intermittent failures."""
    pass

# Configure retries and delay
@pytest.mark.flaky(reruns=3, reruns_delay=2)
def test_timing_sensitive():
    """Test with timing issues - retry up to 3 times with 2s delay."""
    pass
```

### Flaky Test Registry

Document flaky tests in `tests/flaky_tests.md`:

```markdown
#### Test: `test_iris_connection_timeout`

- **Location**: `tests/integration/test_connection.py::test_iris_connection_timeout`
- **Status**: Active
- **Frequency**: Occasional (10%)
- **Root Cause**: Race condition in IRIS connection handshake
- **Mitigation**: @pytest.mark.flaky(reruns=3, reruns_delay=2)
- **Fix Target**: v1.1.0
- **Last Updated**: 2025-10-04
- **Notes**: Fails when IRIS server is under high load
```

### Best Practices

1. **Use `wait_for_condition()` instead of `sleep()`**:

```python
# Good: Poll for condition
def wait_for_condition(check_fn, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        if check_fn():
            return True
        time.sleep(0.1)
    return False

# Usage
assert wait_for_condition(lambda: server.is_ready(), timeout=30)

# Bad: Fixed sleep
time.sleep(5)  # Hope server is ready
```

2. **Wait for resources explicitly**:

```python
# Good: Wait for port
def wait_for_port(host, port, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (socket.error, ConnectionRefusedError):
            time.sleep(0.1)
    return False

# Usage
assert wait_for_port('localhost', 5434, timeout=30)

# Bad: Assume port is ready
connection = psycopg.connect(...)  # Might fail
```

3. **Use fixtures for cleanup**:

```python
# Good: Automatic cleanup via fixture
def test_with_fixture(iris_clean_namespace):
    # Create test data - automatically cleaned up
    pass

# Bad: Manual cleanup that might be skipped
def test_manual_cleanup():
    conn = create_connection()
    try:
        # Test code
        pass
    finally:
        conn.close()  # Might not execute if test crashes
```

---

## Best Practices

### 1. Test Organization

```python
# Group related tests in classes
class TestIRISConnection:
    """Tests for IRIS connection handling."""

    def test_connection_established(self, embedded_iris):
        """Verify IRIS connection works."""
        pass

    def test_connection_timeout_handling(self, embedded_iris):
        """Verify timeout detection."""
        pass
```

### 2. Test Naming

```python
# Good: Descriptive test names
def test_vector_query_returns_top_5_results_ordered_by_cosine_similarity():
    """Test vector similarity query with pgvector syntax."""
    pass

# Bad: Vague test names
def test_query():
    """Test a query."""
    pass
```

### 3. Test Documentation

```python
def test_iris_clean_namespace_isolates_test_data(iris_clean_namespace):
    """
    Verify iris_clean_namespace fixture isolates test data between tests.

    Contract:
    - Returns: iris.Connection with clean state
    - Guarantees: No conflicting test data from previous tests
    - Cleanup time: <2 seconds
    """
    # Test implementation
    pass
```

### 4. Assertion Messages

```python
# Good: Descriptive assertion messages
assert result == expected, \
    f"Expected {expected}, got {result}. SQL: {sql}"

# Bad: No message
assert result == expected
```

### 5. Resource Cleanup

```python
# Good: Use context managers
with iris_clean_namespace.cursor() as cursor:
    cursor.execute("SELECT 1")
    result = cursor.fetchone()

# Good: Use fixtures
def test_with_cleanup(iris_clean_namespace):
    # Automatically cleaned up
    pass
```

---

## CI/CD Integration

### GitLab CI/CD Configuration

Tests run automatically in `.gitlab-ci.yml`:

```yaml
test:
  stage: test
  script:
    - pytest tests/ --verbose --cov --junitxml=test-results.xml
  artifacts:
    paths:
      - coverage.xml
      - htmlcov/
      - test_failures.jsonl
    reports:
      junit: test-results.xml
```

### Environment Variables

```bash
# Set in CI environment
export CI=true
export IRIS_HOST=localhost
export IRIS_PORT=1972
export PYTEST_CURRENT_TEST=tests/integration/test_ci.py::test_something
```

### CI-Specific Behavior

The framework detects CI environments:

```python
import os

if os.environ.get('CI') == 'true':
    # Non-interactive mode
    # Detailed logging
    # Coverage reports in CI-friendly formats
    pass
```

---

## Troubleshooting

### Tests Timeout Without Diagnostics

**Problem**: Tests timeout but no diagnostic information captured

**Solution**:
1. Check `test_failures.jsonl` exists
2. Verify `pytest_runtest_makereport` hook is loaded
3. Run with `-v` flag for verbose output

### IRIS Connection Fails

**Problem**: `embedded_iris` fixture fails with connection error

**Solution**:
1. Verify running via `irispython -m pytest` (not system Python)
2. Check IRIS is running on localhost:1972
3. Verify CallIn service is enabled in IRIS
4. Check credentials: `_SYSTEM/SYS`

### PGWire Client Connection Fails

**Problem**: `pgwire_client` fixture fails with connection refused

**Solution**:
1. Verify PGWire server is running on port 5434
2. Check psycopg3 is installed: `pip install psycopg>=3.1.0`
3. Start PGWire server: `python -m iris_pgwire.server`

### Sequential Execution Not Working

**Problem**: Tests run in parallel

**Solution**:
1. Verify `--dist=no` in `pyproject.toml` addopts
2. Check no `-n` flag in pytest command
3. Confirm pytest-xdist not forcing parallel mode

### Coverage Not Generated

**Problem**: No coverage reports generated

**Solution**:
1. Install pytest-cov: `pip install pytest-cov>=4.1.0`
2. Run with `--cov` flag
3. Check `pyproject.toml` has `--cov=iris_pgwire` in addopts

---

## References

- **Specification**: `specs/017-correct-testing-framework/`
- **Contract Tests**: `tests/contract/`
- **Flaky Test Registry**: `tests/flaky_tests.md`
- **Validation Script**: `tests/validate_framework.py`
- **pytest-timeout**: https://github.com/pytest-dev/pytest-timeout
- **pytest-flaky**: https://github.com/box/flaky
- **pytest-cov**: https://github.com/pytest-dev/pytest-cov

---

**For questions or issues**, see:
- Project README: `/README.md`
- Framework specification: `specs/017-correct-testing-framework/`
- Constitutional principles: `.specify/memory/constitution.md`

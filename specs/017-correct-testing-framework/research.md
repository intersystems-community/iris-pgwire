# Testing Framework Modernization Research

**Date**: 2025-10-04
**Status**: Research Complete
**Purpose**: Comprehensive research on pytest-timeout, pytest-cov, and embedded IRIS fixture patterns for IRIS PGWire testing framework modernization

## Executive Summary

This research document provides comprehensive analysis and recommendations for modernizing the IRIS PGWire testing framework with a focus on:
- **pytest-timeout**: Preventing hanging tests with diagnostic capture
- **pytest-cov**: Coverage reporting without enforcement thresholds
- **Embedded IRIS fixtures**: Session vs function scope for connection management
- **Sequential execution**: Disabling parallel execution for exclusive resource access
- **Flaky test detection**: Identification and retry strategies
- **Diagnostic capture**: Enhanced error messages and context on failure

All recommendations prioritize E2E testing with real IRIS instances following the project's "NO MOCKS" philosophy.

---

## 1. pytest-timeout Best Practices

### Decision: Multi-Layer Timeout Strategy

**Recommended Configuration**:
```ini
# pyproject.toml or pytest.ini
[tool.pytest.ini_options]
timeout = 30  # Global fallback timeout (30 seconds)
timeout_func_only = false  # Include fixture time in timeout
```

**Per-Test Override Pattern**:
```python
import pytest

@pytest.mark.timeout(60)  # Longer timeout for complex E2E tests
def test_vector_similarity_search():
    """E2E test requiring more time for vector operations"""
    pass

@pytest.mark.timeout(10)  # Shorter timeout for unit tests
def test_sql_parser():
    """Fast unit test for SQL parsing logic"""
    pass
```

### Rationale

1. **Global Safety Net**: 30-second default prevents runaway tests while accommodating most IRIS operations
2. **Granular Control**: Per-test markers allow E2E tests to have longer timeouts (60s) while keeping unit tests fast (10s)
3. **Fixture Inclusion**: Including fixture setup/teardown in timeout ensures we catch hanging IRIS connection establishment
4. **CI/CD Optimization**: Environment-aware timeouts support faster feedback in CI while allowing longer local development runs

### Alternatives Considered

**Thread vs Signal Method**:
- **Thread method (default)**: Cross-platform, reliable termination
- **Signal method**: Faster response, but Unix-only and less reliable with threads
- **Recommendation**: Use thread method (default) for cross-platform compatibility

**timeout_func_only Option**:
- **Enabled**: Excludes fixture setup/teardown from timeout
- **Disabled (recommended)**: Includes full test lifecycle
- **Reasoning**: We need to catch hanging IRIS connections in fixtures, not just test execution

### Implementation Notes

**Environment-Aware Configuration**:
```python
# conftest.py
import os

def pytest_configure(config):
    """Set environment-aware timeout defaults"""
    if os.environ.get("CI"):
        config.option.timeout = 20  # Aggressive CI timeout
    else:
        config.option.timeout = 30  # Developer-friendly timeout
```

**Diagnostic Capture on Timeout**:
```python
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Capture diagnostic information on timeout"""
    outcome = yield
    report = outcome.get_result()

    if report.when == "call" and report.failed:
        if "timeout" in str(report.longrepr).lower():
            # Log IRIS connection state
            logger.error("Test timeout detected",
                        test=item.nodeid,
                        duration=call.duration,
                        phase=report.when)
```

**Integration with Fixtures**:
```python
@pytest.fixture(scope="session")
@pytest.mark.timeout(120)  # Longer timeout for session setup
def iris_container():
    """IRIS container setup with extended timeout"""
    # Container startup can take time
    pass
```

---

## 2. pytest-cov Configuration

### Decision: Informational Coverage Without Enforcement

**Recommended Configuration**:
```toml
# pyproject.toml
[tool.pytest.ini_options]
addopts = [
    "--cov=iris_pgwire",
    "--cov-report=term-missing",
    "--cov-report=html:htmlcov",
    "--cov-report=xml:coverage.xml",
    "--cov-branch",
]

[tool.coverage.run]
omit = [
    "tests/*",
    "benchmarks/*",
    "specs/*",
    "*/__pycache__/*",
]

[tool.coverage.report]
# NO fail_under threshold - informational only
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "if TYPE_CHECKING:",
    "raise AssertionError",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
]
```

### Rationale

1. **Informational Approach**: Coverage metrics inform development without blocking progress
2. **Multiple Formats**: Terminal for immediate feedback, HTML for detailed analysis, XML for CI/CD integration
3. **Branch Coverage**: Identifies untested code paths beyond line coverage
4. **Selective Omission**: Excludes test code and generated files from coverage calculation

### Alternatives Considered

**Threshold Enforcement (`fail_under`)**:
- **With Threshold**: Enforces minimum coverage percentage (e.g., 80%)
- **Without Threshold (recommended)**: Provides information without blocking
- **Reasoning**: Early-stage project should focus on E2E correctness over coverage percentages

**Report Formats**:
- **Terminal Only**: Fast, minimal feedback
- **HTML Only**: Detailed but requires browser
- **Multi-Format (recommended)**: Terminal + HTML + XML for all use cases

### Implementation Notes

**CI/CD Integration (GitHub Actions)**:
```yaml
# .github/workflows/test.yml
- name: Run tests with coverage
  run: pytest --cov=iris_pgwire --cov-report=xml

- name: Upload coverage to Codecov
  uses: codecov/codecov-action@v3
  with:
    file: ./coverage.xml
    flags: unittests
    fail_ci_if_error: false  # Informational only
```

**Local Development Workflow**:
```bash
# Quick terminal report during development
pytest --cov --cov-report=term

# Detailed HTML report for analysis
pytest --cov --cov-report=html
open htmlcov/index.html
```

**Coverage Exclusion Patterns**:
```python
# Example: Mark debugging code as no-cover
def debug_dump_state():  # pragma: no cover
    """Debug helper - not covered by tests"""
    import pprint
    pprint.pprint(self.__dict__)
```

---

## 3. Embedded IRIS Fixture Patterns

### Decision: Hybrid Fixture Scope Strategy

**Recommended Pattern**:
```python
# conftest.py
import pytest
import docker
import time

@pytest.fixture(scope="session")
def iris_container():
    """
    Session-scoped: Start IRIS container once per test session

    Rationale:
    - IRIS container startup is expensive (10-30 seconds)
    - Container state is isolated per test session
    - Tests use namespaces for data isolation
    """
    client = docker.from_env()

    # Check for existing container or start new one
    containers = client.containers.list(filters={"name": "iris-pgwire"})
    if containers:
        container = containers[0]
        logger.info("Using existing IRIS container")
    else:
        logger.info("Starting new IRIS container")
        container = client.containers.run(
            "intersystems/iris:latest",
            detach=True,
            name="iris-pgwire-test",
            ports={"1972/tcp": 1975, "52773/tcp": 52777}
        )
        time.sleep(15)  # Wait for IRIS startup

    yield container

    # Cleanup: Stop container after all tests
    # (Optional: could leave running for development)
    # container.stop()

@pytest.fixture(scope="session")
def iris_connection_pool(iris_container):
    """
    Session-scoped: Create connection pool once

    Rationale:
    - Connection pool creation is moderately expensive
    - Pool can be shared across tests safely
    - Individual connections/transactions provide isolation
    """
    import iris

    pool = IRISConnectionPool(
        host="localhost",
        port=1975,
        namespace="USER",
        username="_SYSTEM",
        password="SYS",
        min_connections=2,
        max_connections=10
    )

    yield pool

    pool.close_all()

@pytest.fixture(scope="function")
def iris_namespace_cleanup(iris_connection_pool):
    """
    Function-scoped: Clean namespace before/after each test

    Rationale:
    - Ensures test isolation
    - Prevents data pollution between tests
    - Fast cleanup using IRIS %KillExtent()
    """
    conn = iris_connection_pool.get_connection()

    # Setup: Clean namespace before test
    cursor = conn.cursor()
    cursor.execute("DELETE FROM test_data")
    conn.commit()

    yield conn

    # Teardown: Clean namespace after test
    cursor.execute("DELETE FROM test_data")
    conn.commit()
    iris_connection_pool.return_connection(conn)

@pytest.fixture(scope="function")
def iris_transaction(iris_connection_pool):
    """
    Function-scoped: Transactional test pattern

    Rationale:
    - Transaction rollback provides perfect isolation
    - No cleanup code needed - just rollback
    - Fast teardown
    """
    conn = iris_connection_pool.get_connection()
    transaction = conn.begin()

    yield conn

    # Rollback ensures no state changes persist
    transaction.rollback()
    iris_connection_pool.return_connection(conn)
```

### Rationale

1. **Session Scope for Expensive Resources**: Container startup (10-30s) and pool creation amortized across all tests
2. **Function Scope for Isolation**: Per-test namespace cleanup or transaction rollback ensures test independence
3. **Connection Pooling**: Balances performance (reuse connections) with safety (per-test isolation)
4. **Hybrid Strategy**: Combines performance benefits of session scope with isolation guarantees of function scope

### Alternatives Considered

**Full Function Scope** (Maximum Isolation):
```python
@pytest.fixture(scope="function")
def iris_container():
    """Start fresh container per test"""
    # Pros: Perfect isolation
    # Cons: ~15s overhead per test = impractical
```
- **Rejected**: Too slow for any meaningful test suite

**Full Session Scope** (Maximum Performance):
```python
@pytest.fixture(scope="session")
def iris_connection():
    """Single connection for all tests"""
    # Pros: Fastest possible
    # Cons: Tests contaminate each other
```
- **Rejected**: Test pollution defeats purpose of automated testing

### Implementation Notes

**Namespace Cleanup Pattern**:
```python
def cleanup_iris_namespace(connection, namespace="USER"):
    """Efficiently clean IRIS namespace"""
    cursor = connection.cursor()

    # Option 1: Delete all data from known tables
    tables = ["test_users", "test_vectors", "test_documents"]
    for table in tables:
        cursor.execute(f"DELETE FROM {table}")

    # Option 2: Use IRIS %KillExtent() for class-based tables
    cursor.execute("""
        DO ##class(MyPackage.TestData).%KillExtent()
    """)

    connection.commit()
```

**Connection Pool Implementation**:
```python
class IRISConnectionPool:
    """Simple connection pool for test fixtures"""

    def __init__(self, host, port, namespace, username, password,
                 min_connections=2, max_connections=10):
        self.config = {
            "host": host,
            "port": port,
            "namespace": namespace,
            "username": username,
            "password": password
        }
        self.available = []
        self.in_use = set()
        self.max_connections = max_connections

        # Create minimum connections
        for _ in range(min_connections):
            self.available.append(self._create_connection())

    def _create_connection(self):
        import iris
        return iris.connect(**self.config)

    def get_connection(self):
        if self.available:
            conn = self.available.pop()
        elif len(self.in_use) < self.max_connections:
            conn = self._create_connection()
        else:
            raise RuntimeError("Connection pool exhausted")

        self.in_use.add(conn)
        return conn

    def return_connection(self, conn):
        self.in_use.remove(conn)
        self.available.append(conn)

    def close_all(self):
        for conn in self.available + list(self.in_use):
            conn.close()
```

**Detecting Hanging Operations**:
```python
@pytest.fixture(scope="function")
def iris_connection_with_timeout(iris_connection_pool):
    """Connection with automatic hang detection"""
    conn = iris_connection_pool.get_connection()

    # Set IRIS-level timeout
    cursor = conn.cursor()
    cursor.execute("SET OPTION query_timeout=10")  # 10 second query timeout

    yield conn

    # Check for hanging operations
    cursor.execute("SELECT COUNT(*) FROM %Library.ProcessInfo WHERE ProcessId=?",
                  (conn.process_id,))
    active_processes = cursor.fetchone()[0]

    if active_processes > 0:
        logger.warning("Active IRIS processes detected during cleanup",
                      connection_id=conn.connection_id,
                      process_count=active_processes)

    iris_connection_pool.return_connection(conn)
```

---

## 4. Sequential Test Execution

### Decision: Disable Parallel Execution by Default

**Recommended Configuration**:
```toml
# pyproject.toml
[tool.pytest.ini_options]
# Explicitly disable pytest-xdist parallel execution
addopts = [
    "-n", "0",  # No parallel workers
    # OR
    "--dist", "no",  # Explicitly disable distribution
]
```

### Rationale

1. **Exclusive IRIS Access**: Single IRIS instance cannot safely handle concurrent test connections
2. **Namespace Isolation**: Sequential tests can use same namespace with cleanup between tests
3. **Deterministic Behavior**: Easier debugging and consistent test results
4. **Resource Constraints**: IRIS connection limits and license restrictions

### Alternatives Considered

**Limited Parallelism** (e.g., `-n 2`):
```bash
pytest -n 2  # Two parallel workers
```
- **Pros**: Some speedup without full parallelism
- **Cons**: Still requires complex synchronization for IRIS access
- **Rejected**: Complexity not worth marginal speedup

**Resource-Based Grouping**:
```python
@pytest.mark.database_exclusive
def test_iris_migration():
    """Tests requiring exclusive database access"""
    pass

# Run with: pytest -m "database_exclusive" --dist no
```
- **Pros**: Allows some parallel execution for unit tests
- **Cons**: Complex test organization and execution matrix
- **Deferred**: Consider for future optimization if test suite grows large

### Implementation Notes

**Enforce Sequential Execution**:
```python
# conftest.py
def pytest_configure(config):
    """Ensure sequential execution for IRIS tests"""
    # Check if xdist is trying to run in parallel
    if hasattr(config, 'workerinput'):
        raise RuntimeError(
            "IRIS PGWire tests must run sequentially. "
            "Remove -n flag or use -n 0"
        )
```

**Test Ordering** (if needed):
```python
# Use pytest-ordering plugin for explicit test order
import pytest

@pytest.mark.run(order=1)
def test_01_setup_test_data():
    """Setup test data before other tests"""
    pass

@pytest.mark.run(order=2)
def test_02_query_test_data():
    """Query data created in setup"""
    pass

@pytest.mark.run(order=99)
def test_99_cleanup():
    """Final cleanup after all tests"""
    pass
```

**CI/CD Configuration**:
```yaml
# .github/workflows/test.yml
- name: Run tests (sequential only)
  run: pytest --dist no --timeout 30
  # Do NOT use -n flag
```

---

## 5. Flaky Test Detection and Retry

### Decision: Manual Tracking + pytest-flaky for Specific Tests

**Recommended Approach**:
```python
# Mark known flaky tests for automatic retry
import pytest

@pytest.mark.flaky(retries=3, delay=1)
@pytest.mark.timeout(60)
def test_iris_connection_under_load():
    """
    Known flaky: IRIS connection can timeout under heavy load
    Retry up to 3 times with 1 second delay
    """
    pass

# Track flakiness in test metadata
@pytest.mark.flaky_history([
    "2025-10-01: Failed 2/10 runs - connection timeout",
    "2025-10-02: Failed 1/10 runs - fixed by increasing timeout"
])
def test_vector_search():
    """Test with flakiness history"""
    pass
```

### Rationale

1. **Conservative Retry**: Only retry tests explicitly marked as flaky
2. **Manual Tracking**: Document flakiness patterns to drive fixes
3. **Exception-Based Filtering**: Retry only on specific transient errors (network, timeout)
4. **Avoid Masking Issues**: Don't auto-retry everything - find and fix root causes

### Alternatives Considered

**pytest-flaky Plugin** (Automatic Retry):
```bash
pytest --flake-finder --flake-runs=10
```
- **Pros**: Automatically identifies flaky tests
- **Cons**: Long execution time, may mask real issues
- **Use Case**: Periodic flakiness audit, not regular CI/CD

**pytest-rerunfailures Plugin**:
```bash
pytest --reruns 3 --reruns-delay 1
```
- **Pros**: Simple global retry
- **Cons**: Retries everything, masks real failures
- **Rejected**: Too aggressive for E2E tests with real IRIS

**Manual Flaky Test Tracking** (Recommended):
```python
# tests/flaky_tests.md
# Flaky Test Tracking

## test_iris_connection_timeout
- **Status**: Known flaky
- **Frequency**: ~5% failure rate
- **Cause**: Network timeout to IRIS container
- **Mitigation**: Increased timeout to 60s, added retry
- **Fix Target**: Investigate IRIS connection pooling

## test_vector_similarity_precision
- **Status**: Resolved
- **Frequency**: Was 10% failure rate
- **Cause**: Floating-point precision in vector distance
- **Fix**: Changed to pytest.approx() with rel=1e-6
```

### Implementation Notes

**Exception-Based Retry**:
```python
from pytest_flaky import flaky

def is_transient_error(err, *args):
    """Determine if error is transient and should be retried"""
    if isinstance(err[1], ConnectionError):
        return True
    if isinstance(err[1], TimeoutError):
        return True
    if "IRIS connection lost" in str(err[1]):
        return True
    return False

@flaky(rerun_filter=is_transient_error, max_runs=3)
def test_iris_query():
    """Only retry on transient connection errors"""
    pass
```

**Flakiness Reporting**:
```python
# conftest.py
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Track test flakiness"""
    outcome = yield
    report = outcome.get_result()

    # Track retry attempts
    if hasattr(item, 'execution_count'):
        item.execution_count += 1
    else:
        item.execution_count = 1

    # Log flaky behavior
    if report.failed and hasattr(item, 'flaky'):
        logger.warning("Flaky test failed",
                      test=item.nodeid,
                      attempt=item.execution_count,
                      max_runs=item.flaky.max_runs)
```

**CI/CD Integration**:
```yaml
# .github/workflows/test.yml
- name: Run tests with flaky detection
  run: pytest --flake-finder --flake-runs=5
  # Only on scheduled runs, not every commit
  if: github.event_name == 'schedule'
```

---

## 6. Diagnostic Capture on Failure

### Decision: Multi-Level Diagnostic Capture

**Recommended Implementation**:
```python
# conftest.py
import pytest
import structlog
from typing import Dict
from pytest import StashKey, CollectReport

logger = structlog.get_logger()
phase_report_key = StashKey[Dict[str, CollectReport]]()

@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    """Capture test reports for all phases"""
    rep = yield
    item.stash.setdefault(phase_report_key, {})[rep.when] = rep
    return rep

@pytest.fixture
def diagnostic_capture(request):
    """
    Capture diagnostic information on test failure

    Provides:
    - IRIS connection state
    - Query execution history
    - System resource usage
    - Test phase timing
    """
    diagnostics = {
        "test": request.node.nodeid,
        "start_time": time.time(),
        "iris_state": None,
        "queries": []
    }

    yield diagnostics

    # Access test reports from all phases
    reports = request.node.stash.get(phase_report_key, {})

    # Capture diagnostics on failure
    if "call" in reports and reports["call"].failed:
        diagnostics["end_time"] = time.time()
        diagnostics["duration"] = diagnostics["end_time"] - diagnostics["start_time"]

        # Capture IRIS state
        try:
            diagnostics["iris_state"] = capture_iris_state()
        except Exception as e:
            diagnostics["iris_state"] = f"Failed to capture: {e}"

        # Log comprehensive failure info
        logger.error("Test failed with diagnostics",
                    **diagnostics,
                    error=str(reports["call"].longrepr))

        # Write to failure log
        with open("test_failures.jsonl", "a") as f:
            import json
            f.write(json.dumps(diagnostics) + "\n")

def capture_iris_state():
    """Capture current IRIS system state"""
    import iris

    try:
        conn = iris.connect("localhost", 1975, "USER", "_SYSTEM", "SYS")
        cursor = conn.cursor()

        # Get active processes
        cursor.execute("""
            SELECT ProcessId, ProcessType, State, ProcessMode
            FROM %Library.ProcessInfo
            WHERE State != 'Idle'
        """)
        active_processes = cursor.fetchall()

        # Get connection count
        cursor.execute("""
            SELECT COUNT(*) FROM %Library.ProcessInfo
        """)
        connection_count = cursor.fetchone()[0]

        # Get system metrics
        cursor.execute("""
            SELECT ##class(%SYSTEM.Process).CurrentDirectory(),
                   ##class(%SYSTEM.License).UsedLicenseUnits(),
                   ##class(%SYSTEM.License).ConnectionLimit()
        """)
        system_info = cursor.fetchone()

        conn.close()

        return {
            "active_processes": active_processes,
            "connection_count": connection_count,
            "current_directory": system_info[0],
            "used_licenses": system_info[1],
            "connection_limit": system_info[2]
        }
    except Exception as e:
        return {"error": str(e)}
```

### Rationale

1. **Multi-Phase Capture**: Track setup, call, and teardown phases separately
2. **IRIS-Specific Diagnostics**: Capture IRIS connection state, process info, license usage
3. **Persistent Logging**: Write failures to JSONL for analysis across test runs
4. **Minimal Overhead**: Only capture detailed diagnostics on failure

### Alternatives Considered

**pytest-html Plugin** (Rich HTML Reports):
```bash
pytest --html=report.html --self-contained-html
```
- **Pros**: Beautiful visual reports with screenshots
- **Cons**: Limited programmable access to failure data
- **Complement**: Use alongside custom diagnostics

**pytest-json-report Plugin**:
```bash
pytest --json-report --json-report-file=report.json
```
- **Pros**: Structured JSON output for analysis
- **Cons**: Doesn't capture IRIS-specific state
- **Complement**: Use for test execution metadata

### Implementation Notes

**Enhanced Error Messages**:
```python
def checkconfig(x):
    """Helper with hidden traceback for clean errors"""
    __tracebackhide__ = True
    if not hasattr(x, "config"):
        pytest.fail(f"not configured: {x}\n"
                   f"Expected object with .config attribute, got {type(x)}")

def test_something():
    checkconfig(42)  # Clean error message without helper traceback
```

**Custom Assertion Representations**:
```python
def pytest_assertrepr_compare(op, left, right):
    """Custom assertion failure messages"""
    if isinstance(left, IRISVector) and isinstance(right, IRISVector):
        return [
            f"Vector comparison failed:",
            f"  Expected: {right.to_list()}",
            f"  Got:      {left.to_list()}",
            f"  Distance: {left.cosine_distance(right):.6f}"
        ]
```

**Fixture-Aware Diagnostics**:
```python
@pytest.fixture
def iris_connection_with_diagnostics(request):
    """Connection that tracks query history"""
    conn = create_iris_connection()
    conn.query_history = []

    # Patch execute to track queries
    original_execute = conn.cursor().execute

    def tracked_execute(sql, params=None):
        conn.query_history.append({
            "sql": sql,
            "params": params,
            "timestamp": time.time()
        })
        return original_execute(sql, params)

    conn.cursor().execute = tracked_execute

    yield conn

    # Log query history on failure
    reports = request.node.stash.get(phase_report_key, {})
    if "call" in reports and reports["call"].failed:
        logger.error("Query history before failure",
                    queries=conn.query_history[-10:])  # Last 10 queries

    conn.close()
```

**Timeout Diagnostics**:
```python
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    """Capture stack trace on timeout"""
    outcome = yield

    if outcome.excinfo and "timeout" in str(outcome.excinfo[1]).lower():
        import traceback
        import threading

        # Capture all thread stack traces
        for thread_id, frame in sys._current_frames().items():
            thread = threading._active.get(thread_id)
            logger.error("Thread stack on timeout",
                        thread=thread.name if thread else thread_id,
                        stack=traceback.format_stack(frame))
```

---

## Summary Recommendations

### Immediate Implementation Priorities

1. **pytest-timeout**: Add to dependencies with 30s global timeout, per-test overrides
2. **pytest-cov**: Configure for informational coverage (no fail_under threshold)
3. **IRIS Fixtures**: Implement hybrid session/function scope pattern
4. **Sequential Execution**: Disable pytest-xdist parallel execution
5. **Diagnostic Capture**: Implement failure hooks with IRIS state capture

### Configuration Files

**pyproject.toml**:
```toml
[project.optional-dependencies]
test = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.23.0",
    "pytest-timeout>=2.2.0",
    "pytest-cov>=4.1.0",
    "pytest-flaky>=3.8.0",
    "psycopg>=3.1.0",
    "docker>=6.0.0",
    "structlog>=23.0.0",
]

[tool.pytest.ini_options]
minversion = "7.0"
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
asyncio_mode = "auto"

# Timeout configuration
timeout = 30
timeout_func_only = false

# Coverage configuration
addopts = [
    "--cov=iris_pgwire",
    "--cov-report=term-missing",
    "--cov-report=html:htmlcov",
    "--cov-report=xml:coverage.xml",
    "--cov-branch",
    "--strict-markers",
    "--tb=short",
]

# Sequential execution only
# Do NOT add -n flag or enable xdist

[tool.coverage.run]
omit = [
    "tests/*",
    "benchmarks/*",
    "specs/*",
]

[tool.coverage.report]
# Informational only - no fail_under threshold
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "if TYPE_CHECKING:",
    "raise AssertionError",
    "raise NotImplementedError",
]
```

**conftest.py** (Essential Fixtures):
```python
"""
Pytest configuration for IRIS PGWire tests

Core principles:
- NO MOCKS: Test against real IRIS instance
- E2E FIRST: Validate full protocol stack
- SESSION SCOPE: Expensive resources (container, pool)
- FUNCTION SCOPE: Test isolation (transactions, cleanup)
"""

import pytest
import docker
import time
import structlog
from typing import Dict
from pytest import StashKey, CollectReport

logger = structlog.get_logger()
phase_report_key = StashKey[Dict[str, CollectReport]]()

# Session-scoped fixtures
@pytest.fixture(scope="session")
def iris_container():
    """Start IRIS container once per test session"""
    # Implementation from section 3
    pass

@pytest.fixture(scope="session")
def iris_connection_pool(iris_container):
    """Create connection pool for test session"""
    # Implementation from section 3
    pass

# Function-scoped fixtures
@pytest.fixture(scope="function")
def iris_transaction(iris_connection_pool):
    """Provide transactional isolation per test"""
    # Implementation from section 3
    pass

# Diagnostic capture
@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    """Capture test reports for diagnostic access"""
    # Implementation from section 6
    pass

@pytest.fixture
def diagnostic_capture(request):
    """Capture IRIS state on failure"""
    # Implementation from section 6
    pass
```

### Future Enhancements

1. **Benchmark Integration**: Add pytest-benchmark for performance regression detection
2. **Property-Based Testing**: Consider Hypothesis for IRIS SQL translator edge cases
3. **Parallel Test Grouping**: If test suite grows large (>1000 tests), implement resource-based grouping for limited parallelism
4. **Flakiness Dashboard**: Build dashboard for tracking flaky test trends over time

---

## References

### External Documentation
- pytest-timeout: https://github.com/pytest-dev/pytest-timeout
- pytest-cov: https://pytest-cov.readthedocs.io/
- pytest fixtures: https://docs.pytest.org/en/stable/fixture.html
- pytest-xdist: https://pytest-xdist.readthedocs.io/
- pytest-flaky: https://github.com/box/flaky

### Project Documentation
- `/Users/tdyar/ws/iris-pgwire/CLAUDE.md`: Project development guidelines
- `/Users/tdyar/ws/iris-pgwire/tests/conftest.py`: Current fixture implementation
- `/Users/tdyar/ws/iris-pgwire/tests/integration/test_iris_integration.py`: IRIS integration test patterns

### Constitutional Requirements
- Test-First Development (TDD): Write E2E tests first, implement to make them pass
- NO MOCKS Philosophy: Test against real IRIS instance, real PostgreSQL clients
- Vector Performance Requirements: HNSW benchmarking requires reliable test infrastructure

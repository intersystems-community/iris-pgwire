# Timeout Handler Contract

## Overview
This contract defines the interface and behavior for the TimeoutHandler component that monitors test execution time and terminates hanging processes.

## Purpose
Detect tests that exceed the 30-second timeout threshold, capture comprehensive diagnostic information, and cleanly terminate hanging processes.

## Interface

### Class Definition
```python
class TimeoutHandler:
    """Monitor test execution time and handle timeouts"""

    def __init__(self, timeout_seconds: int = 30):
        """
        Initialize timeout handler.

        Args:
            timeout_seconds: Timeout threshold (default: 30)

        Raises:
            ValueError: If timeout_seconds <= 0 or > 300
        """

    def monitor_test(self, test_id: str) -> Optional[DiagnosticContext]:
        """
        Monitor test execution until completion or timeout.

        Args:
            test_id: pytest node ID (e.g., "tests/test_foo.py::test_bar")

        Returns:
            DiagnosticContext if timeout triggered, None if completed normally

        Side Effects:
            - Starts background monitoring thread
            - Terminates process if timeout exceeded
            - Captures diagnostic information on timeout

        Thread Safety: Safe for concurrent test execution (though tests run sequentially)
        """

    def capture_diagnostics(self) -> DiagnosticContext:
        """
        Capture comprehensive system state for timeout diagnosis.

        Returns:
            DiagnosticContext with IRIS state, query history, connection info

        Called By: Internal - triggered when timeout threshold exceeded
        """

    def terminate_process(self) -> None:
        """
        Cleanly terminate hanging test process.

        Side Effects:
            - Closes IRIS connections
            - Kills test process (SIGTERM, then SIGKILL if needed)
            - Logs termination to pytest output

        Called By: Internal - after diagnostic capture on timeout
        """
```

## Behavior Guarantees

### Timing Precision
- ✅ Timeout detection accurate to ±100ms
- ✅ Uses `time.perf_counter()` for monotonic timing
- ✅ Accounts for fixture setup time in total timeout

### Diagnostic Capture
- ✅ Captures last 10 SQL queries executed against IRIS
- ✅ Records IRIS connection state (connected/disconnected/hung)
- ✅ Includes full Python stack trace
- ✅ Identifies which component is hanging (IRIS, PGWire, test fixture)
- ✅ Diagnostic capture completes in < 2 seconds

### Process Termination
- ✅ Attempts graceful shutdown (SIGTERM) first
- ✅ Escalates to SIGKILL if process doesn't terminate in 5 seconds
- ✅ Ensures IRIS connections are closed before termination
- ✅ Cleans up temporary resources

### Integration with pytest
- ✅ Hooks into `pytest_runtest_call` for monitoring
- ✅ Updates `pytest_runtest_makereport` with timeout status
- ✅ Attaches `DiagnosticContext` to test report

## State Transitions

```
┌──────┐
│ IDLE │ No test running
└───┬──┘
    │ pytest_runtest_call()
    ↓
┌────────────┐
│ MONITORING │ Background thread active, timer running
└──┬──┬──────┘
   │  │
   │  └─ (test completes) ──→ IDLE
   │
   ↓ (elapsed ≥ timeout_seconds)
┌──────────────────┐
│ TIMEOUT_DETECTED │ Threshold exceeded
└───┬──────────────┘
    │
    ↓
┌────────────────────┐
│ DIAGNOSTIC_CAPTURE │ Capture IRIS state, query history
└───┬────────────────┘  (max 2 seconds)
    │
    ↓
┌──────────────┐
│ TERMINATING  │ SIGTERM sent to process
└───┬──────────┘
    │
    ├─ (process exits) ──→ CLEANUP
    │
    └─ (5s timeout) ──→ FORCE_KILL (SIGKILL)
                            ↓
                        CLEANUP
                            ↓
                         IDLE
```

## DiagnosticContext Structure

```python
@dataclass
class DiagnosticContext:
    """Diagnostic information captured on timeout"""

    test_id: str
    failure_type: str = "timeout"

    # Timing
    elapsed_ms: float              # Actual elapsed time
    timeout_threshold_ms: float    # Configured timeout

    # IRIS State
    iris_connection_state: str     # "connected", "disconnected", "hung"
    iris_namespace: str
    iris_query_history: List[str]  # Last 10 SQL statements
    iris_process_id: Optional[int]

    # Component Identification
    hanging_component: str         # "embedded_iris", "pgwire", "test_fixture", "test_body"

    # Stack Trace
    stack_trace: str               # Full Python traceback
    fixture_stack: List[str]       # Active fixtures when timeout occurred

    # Environment
    environment_vars: Dict[str, str]  # IRIS_*, PGWIRE_* env vars
    log_excerpt: str               # Last 50 lines of test output
```

## Hanging Component Detection

The timeout handler identifies which component is hanging based on stack trace analysis:

| Stack Trace Pattern | Identified Component |
|---------------------|---------------------|
| `iris.connect()` or `iris.cursor.execute()` | `embedded_iris` |
| `psycopg.connect()` or `cursor.execute()` | `pgwire` |
| `conftest.py` in traceback | `test_fixture` |
| Test file path in traceback | `test_body` |

## Usage Example

### pytest Integration
```python
# tests/conftest.py
from timeout_handler import TimeoutHandler

@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_call(item):
    """Monitor test execution for timeouts"""
    handler = TimeoutHandler(timeout_seconds=30)
    diagnostic_context = handler.monitor_test(item.nodeid)

    outcome = yield

    if diagnostic_context:
        # Timeout occurred
        outcome.force_exception(TimeoutError(
            f"Test exceeded 30s timeout. Hanging component: {diagnostic_context.hanging_component}"
        ))
        item._timeout_diagnostic = diagnostic_context
```

### Manual Usage
```python
def test_with_custom_timeout():
    """Test that needs longer timeout for E2E scenario"""
    handler = TimeoutHandler(timeout_seconds=60)
    diagnostic = handler.monitor_test("custom_test")

    # Test code here...

    if diagnostic:
        pytest.fail(f"Test timed out: {diagnostic.hanging_component}")
```

## Performance Requirements

- **Monitoring Overhead**: < 1ms per test
- **Diagnostic Capture**: < 2 seconds
- **Process Termination**: < 5 seconds (graceful) + 1 second (forced)
- **Memory Overhead**: < 5MB per monitored test

## Error Handling

### IRIS Connection Hung
```python
# Captured in DiagnosticContext:
{
    "iris_connection_state": "hung",
    "hanging_component": "embedded_iris",
    "iris_query_history": ["SELECT * FROM large_table", "..."],
    "recommendation": "Query execution exceeded timeout - check for missing indexes or table scans"
}
```

### Fixture Setup Hung
```python
# Captured in DiagnosticContext:
{
    "hanging_component": "test_fixture",
    "fixture_stack": ["embedded_iris", "iris_clean_namespace"],
    "recommendation": "Fixture setup exceeded timeout - check IRIS container startup or connection pool initialization"
}
```

### Test Body Hung
```python
# Captured in DiagnosticContext:
{
    "hanging_component": "test_body",
    "stack_trace": "...\n  test_vector_query.py:45 in test_large_dataset\n    result = cursor.execute(query)\n",
    "recommendation": "Test logic exceeded timeout - review query complexity or test data scale"
}
```

## Contract Validation

Contract tests in `tests/contract/test_timeout_handler.py`:

```python
def test_timeout_handler_detects_30s_timeout():
    """Verify timeout detection at 30-second threshold"""
    handler = TimeoutHandler(timeout_seconds=30)

    # Simulate hanging test
    import time
    start = time.perf_counter()
    diagnostic = handler.monitor_test("test_hang")

    # Should trigger at ~30 seconds
    assert diagnostic is not None
    elapsed = time.perf_counter() - start
    assert 29.9 <= elapsed <= 30.5  # ±100ms precision

def test_timeout_handler_captures_iris_query_history():
    """Verify diagnostic context includes SQL history"""
    handler = TimeoutHandler(timeout_seconds=30)

    # Execute queries, then trigger timeout
    cursor.execute("SELECT 1")
    cursor.execute("SELECT 2")
    diagnostic = handler.monitor_test("test_diagnostic")

    assert "SELECT 1" in diagnostic.iris_query_history
    assert "SELECT 2" in diagnostic.iris_query_history

def test_timeout_handler_identifies_hanging_component():
    """Verify component identification from stack trace"""
    handler = TimeoutHandler(timeout_seconds=30)

    # Simulate different hanging scenarios
    # - IRIS connection hang
    # - PGWire hang
    # - Fixture hang
    # - Test body hang

    # Verify correct component identification
    # Implementation TBD
```

## Configuration

Timeout thresholds can be customized via pytest markers:

```python
@pytest.mark.timeout(60)  # Override to 60 seconds for this test
def test_long_running_e2e_scenario():
    """E2E test that legitimately needs more time"""
    pass

@pytest.mark.timeout(10)  # Stricter timeout for unit test
def test_fast_unit_test():
    """Unit test should complete quickly"""
    pass
```

Default: 30 seconds (from TestConfiguration)

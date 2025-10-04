# Flaky Test Tracking

This document tracks flaky tests in the IRIS PGWire test suite as defined in `specs/017-correct-testing-framework/tasks.md` (T025).

## Purpose

Flaky tests are tests that intermittently fail due to:
- Timing issues (race conditions, network delays)
- External dependencies (IRIS connection, Docker containers)
- Resource contention (port conflicts, memory pressure)

Tracking flaky tests helps us:
1. **Identify patterns**: Understand root causes of instability
2. **Prioritize fixes**: Focus on high-impact flakiness
3. **Prevent regressions**: Monitor test stability over time
4. **Guide development**: Inform architectural decisions

## How to Mark Flaky Tests

Use the `@pytest.mark.flaky` decorator with retry configuration:

```python
import pytest

@pytest.mark.flaky(reruns=3, reruns_delay=2)
def test_potentially_flaky_operation():
    """
    This test occasionally fails due to timing issues with IRIS connection.
    Retries up to 3 times with 2-second delay between attempts.
    """
    # Test code here
    pass
```

**Parameters:**
- `reruns`: Number of times to retry (default: 1)
- `reruns_delay`: Delay in seconds between retries (default: 0)

## Flaky Test Registry

### Template

```markdown
#### Test: `test_name`

- **Location**: `tests/path/to/test_file.py::test_name`
- **Status**: Active | Under Investigation | Fixed
- **Frequency**: Rare (<5%) | Occasional (5-25%) | Frequent (>25%)
- **Root Cause**: Race condition | Network timeout | Resource contention | Unknown
- **Mitigation**: @pytest.mark.flaky(reruns=3, reruns_delay=2)
- **Fix Target**: vX.Y.Z | Backlog | Won't Fix
- **Last Updated**: YYYY-MM-DD
- **Notes**: Additional context about the flakiness
```

---

## Active Flaky Tests

_No flaky tests currently tracked. Update this section as tests are identified._

---

## Fixed Flaky Tests

_Tests that were previously flaky but have been fixed._

---

## Best Practices for Avoiding Flakiness

### 1. Use Proper Timeouts
```python
# Good: Explicit timeout with reasonable value
@pytest.mark.timeout(60)
def test_long_operation():
    # Test takes predictably long time
    pass

# Bad: No timeout on potentially hanging operation
def test_long_operation():
    # Could hang indefinitely
    pass
```

### 2. Wait for Resources
```python
# Good: Wait for port to be available
def wait_for_port(host, port, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (socket.error, ConnectionRefusedError):
            time.sleep(0.1)
    return False

# Use in test
def test_server_connection():
    assert wait_for_port('localhost', 5434, timeout=30)
    # Now safe to connect
```

### 3. Clean Up Resources
```python
# Good: Use fixtures for cleanup
@pytest.fixture
def iris_connection(embedded_iris):
    yield embedded_iris
    # Cleanup happens automatically

# Bad: Manual cleanup that might be skipped
def test_manual_cleanup():
    conn = create_connection()
    try:
        # Test code
        pass
    finally:
        conn.close()  # Might not execute if test crashes
```

### 4. Avoid Sleep-Based Timing
```python
# Good: Poll for condition
def wait_for_condition(check_fn, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        if check_fn():
            return True
        time.sleep(0.1)
    return False

# Bad: Fixed sleep
def test_with_sleep():
    trigger_async_operation()
    time.sleep(5)  # Hope operation completes in 5 seconds
    assert operation_done()
```

### 5. Isolate Test Data
```python
# Good: Use iris_clean_namespace fixture
def test_with_isolation(iris_clean_namespace):
    # Each test gets clean state
    cursor = iris_clean_namespace.cursor()
    # Create test data - will be cleaned up

# Bad: Shared state between tests
def test_without_isolation():
    # Might see data from previous test
    cursor = global_connection.cursor()
```

## Flaky Test Workflow

1. **Identify**: Test fails intermittently in CI or local runs
2. **Document**: Add entry to "Active Flaky Tests" section above
3. **Mitigate**: Add `@pytest.mark.flaky` decorator with appropriate retry config
4. **Investigate**: Analyze logs, timing, and failure patterns
5. **Fix**: Address root cause (timing, resource management, etc.)
6. **Verify**: Run test suite multiple times to confirm stability
7. **Update**: Move entry to "Fixed Flaky Tests" section with resolution notes

## Reporting Flaky Tests

If you encounter a flaky test:

1. **Capture diagnostics**: Save test failure output, logs, and timing information
2. **Note frequency**: How often does it fail? (1/10 runs, 1/100 runs, etc.)
3. **Identify pattern**: Does it fail on specific machines, times of day, load conditions?
4. **Create issue**: File a GitHub issue with "flaky-test" label
5. **Update this document**: Add entry to Active Flaky Tests registry
6. **Add mitigation**: Use `@pytest.mark.flaky` while root cause is investigated

## References

- **pytest-flaky documentation**: https://github.com/box/flaky
- **pytest markers**: `pyproject.toml` markers section
- **Testing framework specification**: `specs/017-correct-testing-framework/`
- **Constitutional principle**: Test-First Development (no flaky tests accepted without tracking)

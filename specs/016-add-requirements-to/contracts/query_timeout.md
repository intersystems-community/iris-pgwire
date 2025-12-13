# Contract: Query Timeout Protection

**Requirement**: FR-004 - System MUST implement query timeouts to prevent indefinite hangs on compiler errors

## Contract Definition

### Input
- Query to execute (may hang or cause IRIS compiler crash)
- Timeout duration in seconds (default: 10s)

### Expected Output
- Query result if completed within timeout
- Timeout error if query exceeds timeout duration
- Graceful cleanup (connection released, resources freed)

### Failure Modes
- ❌ Query hangs indefinitely (no timeout) → Benchmark blocks forever
- ❌ Timeout not enforced → Resource leak
- ❌ Improper cleanup → Connection pool exhaustion
- ❌ Timeout too short → Valid queries incorrectly marked as timeout

## Test Cases

### Test 1: Normal Query Completes Within Timeout
```python
def test_normal_query_completes():
    """Normal queries MUST complete within timeout"""
    executor = PGWireExecutor(timeout_seconds=10)

    result = executor.execute_with_timeout("SELECT 1")

    assert result.status == "SUCCESS"
    assert result.elapsed_time_ms < 10000
    assert result.row_count == 1
```

### Test 2: Hanging Query Times Out
```python
def test_hanging_query_times_out():
    """Hanging queries MUST timeout instead of blocking"""
    executor = PGWireExecutor(timeout_seconds=5)

    # Simulate hanging query (if SLEEP supported by IRIS)
    # Or use actual vector query that causes compiler hang
    result = executor.execute_with_timeout(
        "SELECT id, embedding <=> '[MALFORMED' FROM vectors"
    )

    assert result.status == "TIMEOUT"
    assert 5000 <= result.elapsed_time_ms <= 6000  # ~5s + tolerance
    assert result.error_message is not None
```

### Test 3: IRIS Compiler Error Caught Before Timeout
```python
def test_iris_compiler_error_caught():
    """IRIS compiler errors MUST be caught before timeout"""
    executor = PGWireExecutor(timeout_seconds=10)

    # SQL that causes SQLCODE -400 compiler error
    result = executor.execute_with_timeout(
        "SELECT VECTOR_COSINE(embedding, TO_VECTOR('0.1,0.2', FLOAT)) FROM vectors"
    )

    # Error should be caught immediately, not after timeout
    assert result.status == "ERROR"
    assert result.elapsed_time_ms < 5000  # Error detected quickly
    assert "SQLCODE" in result.error_message or "compiler" in result.error_message.lower()
```

### Test 4: Timeout Cleanup Releases Resources
```python
def test_timeout_cleanup_releases_connection():
    """Timeout MUST release connection back to pool"""
    executor = PGWireExecutor(timeout_seconds=2)

    # Execute multiple timeout queries
    for _ in range(5):
        result = executor.execute_with_timeout("SELECT SLEEP(10)")
        assert result.status == "TIMEOUT"

    # Connection pool MUST NOT be exhausted
    result = executor.execute_with_timeout("SELECT 1")
    assert result.status == "SUCCESS"
```

### Test 5: Configurable Timeout Duration
```python
def test_configurable_timeout_duration():
    """Timeout duration MUST be configurable"""
    executor_short = PGWireExecutor(timeout_seconds=2)
    executor_long = PGWireExecutor(timeout_seconds=30)

    # Same query, different timeouts
    sql = "SELECT SLEEP(5)"

    result_short = executor_short.execute_with_timeout(sql)
    assert result_short.status == "TIMEOUT"
    assert result_short.elapsed_time_ms < 3000

    result_long = executor_long.execute_with_timeout(sql)
    assert result_long.status == "SUCCESS"  # Completes within 30s
```

## Timeout Implementation Strategy

### Signal-Based Timeout (Unix)
```python
import signal

@contextmanager
def timeout(seconds):
    def timeout_handler(signum, frame):
        raise TimeoutError(f"Query timed out after {seconds}s")

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)  # Disable alarm
```

### Threading-Based Timeout (Cross-Platform)
```python
import threading

def execute_with_timeout(query, timeout_seconds):
    result = [None]
    exception = [None]

    def worker():
        try:
            result[0] = cursor.execute(query)
        except Exception as e:
            exception[0] = e

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=timeout_seconds)

    if thread.is_alive():
        # Timeout occurred
        cursor.cancel()  # Attempt to cancel query
        return TimeoutResult(status="TIMEOUT")

    if exception[0]:
        return ErrorResult(status="ERROR", error=exception[0])

    return SuccessResult(status="SUCCESS", data=result[0])
```

## Implementation Location

**Test File**: `tests/contract/test_benchmark_timeouts.py`
**Implementation**: `benchmarks/executors/pgwire_executor.py` (new `execute_with_timeout()` method)

## Validation

Run contract tests:
```bash
pytest tests/contract/test_benchmark_timeouts.py -v
```

Expected: All tests PASS after timeout protection implemented.

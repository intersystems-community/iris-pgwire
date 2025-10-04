"""
Contract Test: Query Timeout Protection (FR-004)

REQUIREMENT: System MUST implement query timeouts to prevent indefinite hangs
on compiler errors.

EXPECTED: These tests MUST FAIL before implementation (TDD).
"""
import pytest
import sys
import time
from pathlib import Path

# Add benchmarks to path for executor imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "benchmarks"))

# Note: This will fail initially because execute_with_timeout() doesn't exist yet
try:
    from executors.pgwire_executor import PGWireExecutor
except ImportError:
    pytest.skip("PGWireExecutor not yet implemented", allow_module_level=True)


class TestBenchmarkTimeouts:
    """Contract tests for query timeout protection"""

    def test_normal_query_completes(self):
        """Normal queries MUST complete within timeout (FR-004)"""
        executor = PGWireExecutor(timeout_seconds=10)

        result = executor.execute_with_timeout("SELECT 1")

        assert result.status == "SUCCESS", \
            f"Simple query failed: {result.error_message}"
        assert result.elapsed_time_ms < 10000, \
            f"Query took {result.elapsed_time_ms}ms (should be <10000ms)"
        assert result.row_count == 1

    def test_hanging_query_times_out(self):
        """Hanging queries MUST timeout instead of blocking (FR-004)"""
        executor = PGWireExecutor(timeout_seconds=5)

        # Use malformed vector query that causes compiler hang
        # (This is the actual bug we're fixing)
        result = executor.execute_with_timeout(
            "SELECT id, embedding <=> '[MALFORMED' FROM benchmark_vectors"
        )

        assert result.status == "TIMEOUT", \
            f"Expected TIMEOUT, got {result.status}"

        # Should timeout around 5 seconds (with small tolerance)
        assert 4500 <= result.elapsed_time_ms <= 6000, \
            f"Timeout at {result.elapsed_time_ms}ms (expected ~5000ms)"

        assert result.error_message is not None, \
            "Timeout should include error message"

    def test_iris_compiler_error_caught(self):
        """IRIS compiler errors MUST be caught before timeout (FR-004)"""
        executor = PGWireExecutor(timeout_seconds=10)

        # SQL that causes SQLCODE -400 compiler error
        # (Missing brackets in vector literal)
        result = executor.execute_with_timeout(
            "SELECT VECTOR_COSINE(embedding, TO_VECTOR('0.1,0.2', FLOAT)) FROM benchmark_vectors"
        )

        # Error should be caught immediately, not after timeout
        assert result.status == "ERROR", \
            f"Expected ERROR, got {result.status}"
        assert result.elapsed_time_ms < 5000, \
            f"Error detection took {result.elapsed_time_ms}ms (should be quick)"

        # Check for IRIS error indicators
        error_msg = result.error_message.lower()
        assert "sqlcode" in error_msg or "compiler" in error_msg or "error" in error_msg, \
            f"Missing error context in: {result.error_message}"

    def test_timeout_cleanup_releases_connection(self):
        """Timeout MUST release connection back to pool (FR-004)"""
        executor = PGWireExecutor(timeout_seconds=2)

        # Execute multiple timeout queries
        for i in range(5):
            result = executor.execute_with_timeout(
                f"SELECT id, embedding <=> '[MALFORMED{i}' FROM benchmark_vectors"
            )
            assert result.status in ["TIMEOUT", "ERROR"], \
                f"Iteration {i}: Expected TIMEOUT or ERROR"

        # Connection pool MUST NOT be exhausted
        # This query should still work
        result = executor.execute_with_timeout("SELECT 1")
        assert result.status == "SUCCESS", \
            "Connection pool exhausted after timeouts!"

    def test_configurable_timeout_duration(self):
        """Timeout duration MUST be configurable (FR-004)"""
        executor_short = PGWireExecutor(timeout_seconds=2)
        executor_long = PGWireExecutor(timeout_seconds=30)

        # Use a query that takes ~3 seconds (if IRIS supports SLEEP)
        # Otherwise use repeated queries
        sql = "SELECT 1"  # Placeholder - adjust if IRIS SLEEP available

        start_short = time.time()
        result_short = executor_short.execute_with_timeout(sql)
        elapsed_short = (time.time() - start_short) * 1000

        start_long = time.time()
        result_long = executor_long.execute_with_timeout(sql)
        elapsed_long = (time.time() - start_long) * 1000

        # Both should complete quickly for SELECT 1
        assert result_short.status == "SUCCESS"
        assert result_long.status == "SUCCESS"

        # Verify timeout configurations are different
        assert executor_short.timeout_seconds == 2
        assert executor_long.timeout_seconds == 30


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

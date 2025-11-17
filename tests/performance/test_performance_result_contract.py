"""
Contract tests for PerformanceResult validation (T005).

CRITICAL TDD REQUIREMENT: These tests MUST FAIL before implementation.
Tests validate PerformanceResult.validate() method per specs/015-add-3-way/contracts/benchmark_api.py
"""

import sys
from datetime import datetime
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from benchmarks.config import PerformanceResult


class TestPerformanceResultValidation:
    """Contract tests for PerformanceResult.validate()"""

    def test_valid_performance_result_passes(self):
        """Valid performance result should pass validation with no errors"""
        result = PerformanceResult(
            result_id="result_001",
            method_name="iris_pgwire",
            query_id="query_001",
            timestamp=datetime.now(),
            elapsed_ms=12.5,
            success=True,
            row_count=10,
        )

        errors = result.validate()
        assert errors == [], f"Expected no errors, got: {errors}"

    def test_negative_elapsed_ms_raises_error(self):
        """Negative elapsed_ms should raise validation error"""
        result = PerformanceResult(
            result_id="result_001",
            method_name="iris_pgwire",
            query_id="query_001",
            timestamp=datetime.now(),
            elapsed_ms=-5.0,  # Invalid negative time
            success=True,
            row_count=10,
        )

        errors = result.validate()
        assert any(
            "elapsed_ms cannot be negative" in err for err in errors
        ), f"Expected elapsed_ms error, got: {errors}"

    def test_failed_result_without_error_message_raises_error(self):
        """success=False without error_message should raise validation error"""
        result = PerformanceResult(
            result_id="result_001",
            method_name="iris_pgwire",
            query_id="query_001",
            timestamp=datetime.now(),
            elapsed_ms=12.5,
            success=False,  # Failed
            error_message=None,  # Missing required error message
            row_count=0,
        )

        errors = result.validate()
        assert any(
            "error_message required when success is False" in err for err in errors
        ), f"Expected error_message error, got: {errors}"

    def test_failed_result_with_error_message_passes(self):
        """success=False WITH error_message should pass validation"""
        result = PerformanceResult(
            result_id="result_001",
            method_name="iris_pgwire",
            query_id="query_001",
            timestamp=datetime.now(),
            elapsed_ms=12.5,
            success=False,
            error_message="Connection timeout",  # Error message provided
            row_count=0,
        )

        errors = result.validate()
        assert (
            errors == []
        ), f"Expected no errors for failed result with error_message, got: {errors}"

    def test_negative_row_count_raises_error(self):
        """Negative row_count should raise validation error"""
        result = PerformanceResult(
            result_id="result_001",
            method_name="iris_pgwire",
            query_id="query_001",
            timestamp=datetime.now(),
            elapsed_ms=12.5,
            success=True,
            row_count=-1,  # Invalid negative row count
        )

        errors = result.validate()
        assert any(
            "row_count cannot be negative" in err for err in errors
        ), f"Expected row_count error, got: {errors}"

    def test_zero_elapsed_ms_is_valid(self):
        """Zero elapsed_ms should be valid (very fast query)"""
        result = PerformanceResult(
            result_id="result_001",
            method_name="iris_pgwire",
            query_id="query_001",
            timestamp=datetime.now(),
            elapsed_ms=0.0,  # Valid - extremely fast query
            success=True,
            row_count=0,
        )

        errors = result.validate()
        assert errors == [], f"Expected no errors for zero elapsed_ms, got: {errors}"

    def test_zero_row_count_is_valid(self):
        """Zero row_count should be valid (empty result set)"""
        result = PerformanceResult(
            result_id="result_001",
            method_name="iris_pgwire",
            query_id="query_001",
            timestamp=datetime.now(),
            elapsed_ms=12.5,
            success=True,
            row_count=0,  # Valid - no rows returned
        )

        errors = result.validate()
        assert errors == [], f"Expected no errors for zero row_count, got: {errors}"

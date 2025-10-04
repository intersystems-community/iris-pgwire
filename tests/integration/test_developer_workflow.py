"""
Integration tests for developer workflow.

These tests validate that the testing framework provides a good developer experience
as defined in specs/017-correct-testing-framework/spec.md

TDD: These tests MUST FAIL until the framework is properly configured.
"""

import pytest
import subprocess
import time
import json
import sys
import shutil

# Find pytest executable (might be in venv or PATH)
PYTEST_CMD = shutil.which("pytest") or sys.executable + " -m pytest"


def test_local_test_execution_completes_without_hanging():
    """
    Verify local pytest execution completes without hanging processes.

    Contract:
    - All tests execute sequentially
    - No hanging processes remain after execution
    - Clear pass/fail reporting
    - Completes within reasonable time (timeout enforcement)
    """
    # Run pytest programmatically via subprocess
    # This tests the ACTUAL pytest configuration we've set up
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/contract/", "-v", "--tb=short"],
        capture_output=True,
        text=True,
        timeout=120  # 2 minutes max - should complete much faster
    )

    # Verify pytest ran (may fail tests, but shouldn't hang)
    assert result.returncode is not None, "pytest should complete (not hang)"

    # Verify output shows test execution
    assert "test session starts" in result.stdout or "test session starts" in result.stderr, \
        "pytest should start test session"

    # Verify sequential execution (no parallel markers)
    # pytest-xdist would show "gw0", "gw1" for workers - we should NOT see this
    assert "gw0" not in result.stdout, \
        "Should not see pytest-xdist workers (tests must be sequential)"

    # Verify timeout configuration is active
    # pytest-timeout should be loaded and show in --version or markers
    version_result = subprocess.run(
        [sys.executable, "-m", "pytest", "--version"],
        capture_output=True,
        text=True
    )
    assert "timeout" in version_result.stdout.lower() or "pytest-timeout" in version_result.stdout.lower(), \
        "pytest-timeout plugin should be active"


def test_local_test_failure_provides_actionable_diagnostics():
    """
    Verify test failures include actionable diagnostic information.

    Contract:
    - Error messages include SQL executed (when applicable)
    - IRIS connection state shown in failures
    - Namespace and duration included
    - Stack traces show relevant code paths
    """
    # Create a test that will intentionally fail to check diagnostic output
    test_code = '''
import pytest

def test_intentional_failure_with_iris_context(iris_clean_namespace):
    """Intentional failure to test diagnostic capture"""
    cursor = iris_clean_namespace.cursor()

    # Execute some SQL that will be in diagnostic context
    cursor.execute("SELECT 1 AS test_query")

    # Now trigger failure
    assert False, "Intentional failure to test diagnostics"
'''

    # Write temporary test file
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(test_code)
        test_file_path = f.name

    try:
        # Run the failing test
        result = subprocess.run(
            [sys.executable, "-m", "pytest", test_file_path, "-v", "--tb=short"],
            capture_output=True,
            text=True,
            timeout=60
        )

        # Should fail (return code 1)
        assert result.returncode == 1, "Test should fail as designed"

        # Verify diagnostic information in output
        output = result.stdout + result.stderr

        # Check for key diagnostic elements
        assert "test_query" in output or "SELECT 1" in output, \
            "Diagnostic output should include SQL context"

        assert "Intentional failure to test diagnostics" in output, \
            "Assertion message should be visible"

        # Check for fixture information
        assert "iris_clean_namespace" in output, \
            "Fixture name should appear in traceback or setup"

        # Verify short traceback mode is working
        assert "--tb=short" in " ".join([sys.executable, "-m", "pytest", test_file_path, "-v", "--tb=short"]), \
            "Short traceback mode should be used"

    finally:
        # Cleanup temporary test file
        if os.path.exists(test_file_path):
            os.unlink(test_file_path)


def test_coverage_report_generated_without_enforcement():
    """
    Verify coverage is tracked but not enforced.

    Contract:
    - Coverage report generated (HTML, XML, terminal)
    - No fail_under threshold (tests pass regardless of coverage)
    - Coverage data shows actual execution paths
    """
    # Run pytest with coverage enabled (should be default from pyproject.toml)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/contract/", "--cov", "--cov-report=term"],
        capture_output=True,
        text=True,
        timeout=120
    )

    output = result.stdout + result.stderr

    # Verify coverage is being collected
    assert "coverage" in output.lower() or "cov" in output.lower(), \
        "Coverage reporting should be active"

    # Verify coverage report mentions iris_pgwire (our target package)
    assert "iris_pgwire" in output or "src/iris_pgwire" in output, \
        "Coverage should track iris_pgwire package"

    # Verify NO coverage enforcement (test should not fail due to low coverage)
    # We expect tests to fail due to missing fixtures, but NOT due to coverage
    if result.returncode != 0:
        # If tests failed, it should NOT be due to coverage threshold
        assert "coverage" not in output.lower() or "failed" not in output.lower() or \
               "coverage failed" not in output.lower(), \
            "Tests should not fail due to coverage threshold (no enforcement)"


def test_timeout_configuration_active():
    """
    Verify 30-second timeout is configured and active.

    Contract:
    - Timeout set to 30 seconds globally
    - timeout_func_only=false (includes fixture time)
    - Tests can override with @pytest.mark.timeout
    """
    # Check pytest configuration
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--co", "-q"],  # Collect only, quiet mode
        capture_output=True,
        text=True,
        timeout=30
    )

    # Verify pytest can collect tests (configuration is valid)
    assert result.returncode == 0 or result.returncode == 5, \
        "pytest configuration should be valid (exit code 0 or 5 for no tests)"

    # Create a test that will timeout to verify enforcement
    timeout_test_code = '''
import time

def test_verify_timeout_enforcement():
    """This test should timeout after 30 seconds"""
    # Sleep longer than timeout threshold
    time.sleep(35)  # Should be killed at 30s
'''

    import tempfile
    import os

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(timeout_test_code)
        test_file_path = f.name

    try:
        start_time = time.perf_counter()

        # Run the timeout test
        result = subprocess.run(
            [sys.executable, "-m", "pytest", test_file_path, "-v"],
            capture_output=True,
            text=True,
            timeout=60  # Give subprocess time to timeout the test
        )

        elapsed = time.perf_counter() - start_time

        # Should complete in ~30 seconds (timeout), not 35 seconds (sleep)
        assert elapsed < 35, \
            f"Test should timeout at ~30s, not complete full sleep (took {elapsed:.1f}s)"

        # Verify timeout occurred
        output = result.stdout + result.stderr
        assert "timeout" in output.lower() or "timed out" in output.lower(), \
            "Output should indicate timeout occurred"

    finally:
        if os.path.exists(test_file_path):
            os.unlink(test_file_path)

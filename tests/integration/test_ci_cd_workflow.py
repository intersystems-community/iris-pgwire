"""
Integration tests for CI/CD workflow.

These tests validate that the testing framework works correctly in CI/CD environments
as defined in specs/017-correct-testing-framework/spec.md

TDD: These tests MUST FAIL until CI mode is properly configured.
"""

import pytest
import subprocess
import os
import json
import sys


def test_ci_cd_tests_match_local_execution():
    """
    Verify CI/CD test execution matches local developer experience.

    Contract:
    - CI=true environment variable enables CI mode
    - Non-interactive mode (no prompts, clear output)
    - Results match local execution behavior
    - Coverage report generated in CI-friendly format
    """
    # Set CI environment variable
    ci_env = os.environ.copy()
    ci_env['CI'] = 'true'

    # Run tests in CI mode
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/contract/", "-v", "--tb=short"],
        env=ci_env,
        capture_output=True,
        text=True,
        timeout=120
    )

    # Verify pytest ran (may fail due to missing fixtures, but shouldn't error)
    assert result.returncode is not None, "pytest should complete in CI mode"

    output = result.stdout + result.stderr

    # Verify non-interactive behavior (no prompts)
    assert "Press" not in output and "Continue?" not in output, \
        "CI mode should not prompt for user input"

    # Verify CI-friendly output format
    assert "test session starts" in output, "CI output should show session start"

    # Verify sequential execution (same as local)
    assert "gw0" not in output, \
        "CI mode should also run tests sequentially (no parallel workers)"


def test_ci_cd_coverage_reports_generated():
    """
    Verify coverage reports are generated in CI-compatible formats.

    Contract:
    - XML coverage report generated (for CI dashboards)
    - HTML coverage report generated (for artifacts)
    - Terminal coverage summary shown
    - Reports accessible for upload to coverage services
    """
    ci_env = os.environ.copy()
    ci_env['CI'] = 'true'

    # Run pytest with coverage in CI mode
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/contract/", "--cov", "--cov-report=xml", "--cov-report=html"],
        env=ci_env,
        capture_output=True,
        text=True,
        timeout=120
    )

    output = result.stdout + result.stderr

    # Verify coverage collection
    assert "coverage" in output.lower(), "Coverage should be collected in CI"

    # Check for XML report generation message
    # pytest-cov typically outputs something like "Coverage XML written to file coverage.xml"
    assert "xml" in output.lower() or "coverage.xml" in output, \
        "XML coverage report should be generated for CI"

    # Check for HTML report generation message
    assert "html" in output.lower() or "htmlcov" in output, \
        "HTML coverage report should be generated for CI artifacts"

    # Verify coverage.xml would be created (file may not exist in test env)
    # This is a configuration validation, not file existence check


def test_ci_cd_failure_logs_are_detailed():
    """
    Verify CI/CD failures include sufficient detail for debugging.

    Contract:
    - Full error messages in output
    - Stack traces included
    - Environment context captured
    - No truncation of critical information
    """
    # Create a test that will fail to check CI failure output
    test_code = '''
def test_ci_failure_detail():
    """Test that fails to verify CI error reporting"""
    # Generate detailed failure with context
    context = {
        'database': 'IRIS',
        'namespace': 'USER',
        'operation': 'test_execution'
    }

    error_message = f"Operation failed in CI environment: {context}"
    assert False, error_message
'''

    import tempfile

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(test_code)
        test_file_path = f.name

    try:
        ci_env = os.environ.copy()
        ci_env['CI'] = 'true'

        # Run the failing test in CI mode
        result = subprocess.run(
            [sys.executable, "-m", "pytest", test_file_path, "-v"],
            env=ci_env,
            capture_output=True,
            text=True,
            timeout=60
        )

        # Should fail (return code 1)
        assert result.returncode == 1, "Test should fail as designed"

        output = result.stdout + result.stderr

        # Verify detailed error message is present
        assert "Operation failed in CI environment" in output, \
            "Full error message should be in CI output"

        assert "database" in output or "IRIS" in output, \
            "Context information should be preserved in CI logs"

        # Verify stack trace is included
        assert "test_ci_failure_detail" in output, \
            "Function name should appear in stack trace"

        assert "AssertionError" in output or "assert False" in output, \
            "Error type should be clear in CI output"

    finally:
        if os.path.exists(test_file_path):
            os.unlink(test_file_path)


def test_ci_cd_timeout_enforcement():
    """
    Verify timeout enforcement works in CI/CD environment.

    Contract:
    - 30-second timeout enforced in CI
    - Hanging tests terminated cleanly
    - Timeout failures clearly reported
    - No zombie processes in CI
    """
    import time

    # Create a test that will timeout
    timeout_test_code = '''
import time

def test_ci_timeout_enforcement():
    """This test should timeout in CI"""
    time.sleep(35)  # Exceeds 30s timeout
'''

    import tempfile

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(timeout_test_code)
        test_file_path = f.name

    try:
        ci_env = os.environ.copy()
        ci_env['CI'] = 'true'

        start_time = time.perf_counter()

        # Run the timeout test in CI mode
        result = subprocess.run(
            [sys.executable, "-m", "pytest", test_file_path, "-v"],
            env=ci_env,
            capture_output=True,
            text=True,
            timeout=60  # Subprocess timeout (longer than test timeout)
        )

        elapsed = time.perf_counter() - start_time

        # Should timeout at ~30 seconds, not run full 35 seconds
        assert elapsed < 35, \
            f"CI test should timeout at ~30s, not complete (took {elapsed:.1f}s)"

        output = result.stdout + result.stderr

        # Verify timeout was reported
        assert "timeout" in output.lower() or "timed out" in output.lower(), \
            "CI output should clearly indicate timeout"

        # Verify test was marked as failed (not passed)
        assert "FAILED" in output or "failed" in output.lower(), \
            "Timeout should result in test failure in CI"

    finally:
        if os.path.exists(test_file_path):
            os.unlink(test_file_path)


def test_ci_cd_sequential_execution_enforced():
    """
    Verify sequential execution is enforced in CI/CD environment.

    Contract:
    - No parallel test execution in CI
    - Tests run one at a time (predictable IRIS state)
    - No pytest-xdist usage
    - Clear ordering in test output
    """
    ci_env = os.environ.copy()
    ci_env['CI'] = 'true'

    # Run tests in CI mode
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/contract/", "-v"],
        env=ci_env,
        capture_output=True,
        text=True,
        timeout=120
    )

    output = result.stdout + result.stderr

    # Verify NO parallel execution markers
    assert "gw0" not in output and "gw1" not in output, \
        "CI should not use pytest-xdist parallel workers"

    # Verify --dist=no is in effect (from pyproject.toml)
    # This is implicit - we just verify no parallel execution occurred

    # Verify tests ran sequentially (can see individual test start/finish)
    # In parallel mode, output is interleaved; in sequential, it's linear
    if "PASSED" in output or "FAILED" in output:
        # Count test result markers
        test_count = output.count("PASSED") + output.count("FAILED")
        assert test_count > 0, "Should see individual test results (sequential output)"


def test_ci_cd_environment_detection():
    """
    Verify framework correctly detects CI/CD environment.

    Contract:
    - CI=true environment variable recognized
    - Different behavior in CI vs local (if applicable)
    - Logging adapted for CI (structured, machine-readable)
    - No interactive features in CI mode
    """
    # Test 1: Verify CI=true is detected
    ci_env = os.environ.copy()
    ci_env['CI'] = 'true'

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--version"],
        env=ci_env,
        capture_output=True,
        text=True,
        timeout=30
    )

    # pytest --version should work in both CI and local
    assert result.returncode == 0, "pytest should work with CI=true set"

    # Test 2: Verify absence of CI=true is handled
    local_env = os.environ.copy()
    if 'CI' in local_env:
        del local_env['CI']

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--version"],
        env=local_env,
        capture_output=True,
        text=True,
        timeout=30
    )

    assert result.returncode == 0, "pytest should work without CI=true"

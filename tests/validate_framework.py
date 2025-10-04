#!/usr/bin/env python3
"""
Quickstart validation script for IRIS PGWire testing framework.

This script validates that the testing framework meets all requirements from:
- specs/017-correct-testing-framework/quickstart.md
- specs/017-correct-testing-framework/contracts/

Usage:
    python tests/validate_framework.py

Exit codes:
    0: All validations passed
    1: One or more validations failed
"""

import sys
import os
import subprocess
from pathlib import Path
from typing import List, Tuple

# ANSI color codes for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'


class ValidationResult:
    """Container for validation results."""

    def __init__(self):
        self.total = 0
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.failures: List[Tuple[str, str]] = []

    def add_pass(self, criterion: str):
        """Record a passing criterion."""
        self.total += 1
        self.passed += 1
        print(f"{GREEN}✓{RESET} {criterion}")

    def add_fail(self, criterion: str, reason: str):
        """Record a failing criterion."""
        self.total += 1
        self.failed += 1
        self.failures.append((criterion, reason))
        print(f"{RED}✗{RESET} {criterion}")
        print(f"  {RED}Reason: {reason}{RESET}")

    def add_skip(self, criterion: str, reason: str):
        """Record a skipped criterion."""
        self.total += 1
        self.skipped += 1
        print(f"{YELLOW}○{RESET} {criterion} (skipped: {reason})")

    def summary(self):
        """Print summary and return exit code."""
        print(f"\n{BLUE}{'=' * 70}{RESET}")
        print(f"{BLUE}Validation Summary{RESET}")
        print(f"{BLUE}{'=' * 70}{RESET}")
        print(f"Total criteria:  {self.total}")
        print(f"{GREEN}Passed:          {self.passed}{RESET}")
        print(f"{RED}Failed:          {self.failed}{RESET}")
        print(f"{YELLOW}Skipped:         {self.skipped}{RESET}")

        if self.failures:
            print(f"\n{RED}Failed Criteria:{RESET}")
            for i, (criterion, reason) in enumerate(self.failures, 1):
                print(f"{i}. {criterion}")
                print(f"   {reason}")

        if self.failed == 0:
            print(f"\n{GREEN}🎉 All validation criteria passed!{RESET}")
            return 0
        else:
            print(f"\n{RED}❌ {self.failed} validation(s) failed{RESET}")
            return 1


def check_file_exists(path: str, result: ValidationResult, criterion_name: str):
    """Check if a file exists."""
    if Path(path).exists():
        result.add_pass(criterion_name)
        return True
    else:
        result.add_fail(criterion_name, f"File not found: {path}")
        return False


def check_pytest_config(result: ValidationResult):
    """Validate pytest configuration in pyproject.toml."""
    criterion = "pytest.ini configured with timeout, coverage, sequential execution"

    try:
        import tomli
    except ImportError:
        # Fall back to manual parsing for Python < 3.11
        try:
            import toml as tomli
        except ImportError:
            result.add_skip(criterion, "tomli/toml package not available")
            return

    try:
        with open('pyproject.toml', 'rb') as f:
            config = tomli.load(f)

        pytest_config = config.get('tool', {}).get('pytest', {}).get('ini_options', {})

        # Check timeout
        if pytest_config.get('timeout') == 30:
            result.add_pass("Timeout configured to 30 seconds")
        else:
            result.add_fail("Timeout configuration", f"Expected 30, got {pytest_config.get('timeout')}")

        # Check coverage
        addopts = pytest_config.get('addopts', [])
        if '--cov=iris_pgwire' in addopts:
            result.add_pass("Coverage configured for iris_pgwire")
        else:
            result.add_fail("Coverage configuration", "--cov=iris_pgwire not in addopts")

        # Check sequential execution
        if '--dist=no' in addopts:
            result.add_pass("Sequential execution enforced (--dist=no)")
        else:
            result.add_fail("Sequential execution", "--dist=no not in addopts")

        # Check markers
        markers = pytest_config.get('markers', [])
        required_markers = ['timeout', 'flaky', 'slow']
        for marker in required_markers:
            if any(marker in m for m in markers):
                result.add_pass(f"Marker '{marker}' configured")
            else:
                result.add_fail(f"Marker '{marker}'", "Not found in markers list")

    except Exception as e:
        result.add_fail(criterion, f"Error reading pyproject.toml: {e}")


def check_fixtures(result: ValidationResult):
    """Check that required fixtures are implemented."""
    criterion = "Required fixtures implemented in tests/conftest.py"

    try:
        with open('tests/conftest.py', 'r') as f:
            content = f.read()

        # Check for required fixtures
        required_fixtures = [
            ('iris_config', '@pytest.fixture', 'def iris_config'),
            ('embedded_iris', '@pytest.fixture', 'def embedded_iris'),
            ('iris_clean_namespace', '@pytest.fixture', 'def iris_clean_namespace'),
            ('pgwire_client', '@pytest.fixture', 'def pgwire_client'),
        ]

        for fixture_name, decorator, definition in required_fixtures:
            if decorator in content and definition in content:
                result.add_pass(f"Fixture '{fixture_name}' implemented")
            else:
                result.add_fail(f"Fixture '{fixture_name}'", "Not found in conftest.py")

    except FileNotFoundError:
        result.add_fail(criterion, "tests/conftest.py not found")
    except Exception as e:
        result.add_fail(criterion, f"Error checking fixtures: {e}")


def check_timeout_handler(result: ValidationResult):
    """Check that TimeoutHandler is implemented."""
    criterion = "TimeoutHandler implemented in tests/timeout_handler.py"

    try:
        with open('tests/timeout_handler.py', 'r') as f:
            content = f.read()

        # Check for required components
        if 'class TimeoutHandler' in content:
            result.add_pass("TimeoutHandler class defined")
        else:
            result.add_fail("TimeoutHandler class", "Not found in timeout_handler.py")

        if 'class DiagnosticContext' in content or '@dataclass' in content:
            result.add_pass("DiagnosticContext defined")
        else:
            result.add_fail("DiagnosticContext", "Not found in timeout_handler.py")

        # Check for required methods
        required_methods = ['monitor_test', 'capture_diagnostics', 'terminate_process']
        for method in required_methods:
            if f'def {method}' in content:
                result.add_pass(f"Method '{method}' implemented")
            else:
                result.add_fail(f"Method '{method}'", "Not found in TimeoutHandler")

    except FileNotFoundError:
        result.add_fail(criterion, "tests/timeout_handler.py not found")
    except Exception as e:
        result.add_fail(criterion, f"Error checking timeout handler: {e}")


def check_diagnostic_capture(result: ValidationResult):
    """Check that diagnostic capture hooks are implemented."""
    criterion = "Diagnostic capture hooks implemented"

    try:
        with open('tests/conftest.py', 'r') as f:
            content = f.read()

        # Check for pytest hooks
        if 'pytest_runtest_makereport' in content:
            result.add_pass("pytest_runtest_makereport hook implemented")
        else:
            result.add_fail("pytest_runtest_makereport hook", "Not found in conftest.py")

        if 'capture_iris_state' in content:
            result.add_pass("capture_iris_state function implemented")
        else:
            result.add_fail("capture_iris_state function", "Not found in conftest.py")

    except Exception as e:
        result.add_fail(criterion, f"Error checking diagnostic capture: {e}")


def check_contract_tests(result: ValidationResult):
    """Check that contract tests exist."""
    contract_tests = [
        ('tests/contract/test_fixture_contract.py', "Fixture contract tests"),
        ('tests/contract/test_timeout_handler.py', "Timeout handler contract tests"),
    ]

    for test_file, description in contract_tests:
        check_file_exists(test_file, result, description)


def check_integration_tests(result: ValidationResult):
    """Check that integration tests exist."""
    integration_tests = [
        ('tests/integration/test_developer_workflow.py', "Developer workflow tests"),
        ('tests/integration/test_ci_cd_workflow.py', "CI/CD workflow tests"),
    ]

    for test_file, description in integration_tests:
        check_file_exists(test_file, result, description)


def check_documentation(result: ValidationResult):
    """Check that documentation files exist."""
    docs = [
        ('tests/flaky_tests.md', "Flaky test tracking documentation"),
        ('.gitlab-ci.yml', "GitLab CI/CD configuration"),
    ]

    for doc_file, description in docs:
        check_file_exists(doc_file, result, description)


def main():
    """Run all validation checks."""
    print(f"{BLUE}{'=' * 70}{RESET}")
    print(f"{BLUE}IRIS PGWire Testing Framework Validation{RESET}")
    print(f"{BLUE}{'=' * 70}{RESET}\n")

    result = ValidationResult()

    # Change to project root
    project_root = Path(__file__).parent.parent
    os.chdir(project_root)

    print(f"{BLUE}Checking pytest configuration...{RESET}")
    check_pytest_config(result)

    print(f"\n{BLUE}Checking fixtures...{RESET}")
    check_fixtures(result)

    print(f"\n{BLUE}Checking timeout handler...{RESET}")
    check_timeout_handler(result)

    print(f"\n{BLUE}Checking diagnostic capture...{RESET}")
    check_diagnostic_capture(result)

    print(f"\n{BLUE}Checking contract tests...{RESET}")
    check_contract_tests(result)

    print(f"\n{BLUE}Checking integration tests...{RESET}")
    check_integration_tests(result)

    print(f"\n{BLUE}Checking documentation...{RESET}")
    check_documentation(result)

    # Print summary and exit
    return result.summary()


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""
IRIS SQL Constructs E2E Test Runner

Constitutional Requirement: Test-First Development with real PostgreSQL clients
Executes comprehensive E2E validation of IRIS construct translation.

Usage:
    python test_iris_constructs_e2e.py [--quick] [--integration-only] [--e2e-only]

Options:
    --quick           Run only fast tests (skip full E2E)
    --integration-only Run only integration tests
    --e2e-only        Run only E2E tests
    --contract-only   Run only contract tests
"""

import argparse
import subprocess
import sys
import time

import structlog

logger = structlog.get_logger()


def run_pytest_suite(test_path: str, markers: str = None, verbose: bool = True) -> bool:
    """Run pytest suite with specified markers"""
    cmd = ["python", "-m", "pytest"]

    if verbose:
        cmd.extend(["-v", "-s"])

    if markers:
        cmd.extend(["-m", markers])

    cmd.append(test_path)

    logger.info("Running test suite", command=" ".join(cmd))

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

        if result.returncode == 0:
            logger.info("Test suite passed", test_path=test_path)
            if verbose:
                print(result.stdout)
            return True
        else:
            logger.error(
                "Test suite failed",
                test_path=test_path,
                returncode=result.returncode,
                stderr=result.stderr,
            )
            print("STDOUT:", result.stdout)
            print("STDERR:", result.stderr)
            return False

    except subprocess.TimeoutExpired:
        logger.error("Test suite timed out", test_path=test_path)
        return False
    except FileNotFoundError:
        logger.error("pytest not found - install with: pip install pytest")
        return False


def check_prerequisites() -> bool:
    """Check if prerequisites are available"""
    try:
        # Check if IRIS module can be imported
        from iris_pgwire.iris_constructs import IRISConstructTranslator

        logger.info("IRIS constructs module available")
        return True
    except ImportError as e:
        logger.error("IRIS constructs module not available", error=str(e))
        return False


def main():
    """Main test runner"""
    parser = argparse.ArgumentParser(description="IRIS SQL Constructs E2E Test Runner")
    parser.add_argument("--quick", action="store_true", help="Run only fast tests")
    parser.add_argument(
        "--integration-only", action="store_true", help="Run only integration tests"
    )
    parser.add_argument("--e2e-only", action="store_true", help="Run only E2E tests")
    parser.add_argument("--contract-only", action="store_true", help="Run only contract tests")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    # Check prerequisites
    if not check_prerequisites():
        logger.error("Prerequisites not met")
        return False

    # Determine test suite to run
    test_suites = []

    if args.contract_only:
        test_suites.append(
            ("Contract Tests", "tests/test_contract_iris_translation.py", "contract")
        )
    elif args.integration_only:
        test_suites.append(
            ("Integration Tests", "tests/test_integration_iris_translation.py", "integration")
        )
    elif args.e2e_only:
        test_suites.append(("E2E Tests", "tests/test_e2e_iris_constructs.py", "e2e"))
    elif args.quick:
        # Quick tests: contract and integration only
        test_suites.extend(
            [
                ("Contract Tests", "tests/test_contract_iris_translation.py", "contract"),
                ("Integration Tests", "tests/test_integration_iris_translation.py", "integration"),
            ]
        )
    else:
        # Full test suite
        test_suites.extend(
            [
                ("Contract Tests", "tests/test_contract_iris_translation.py", "contract"),
                ("Integration Tests", "tests/test_integration_iris_translation.py", "integration"),
                ("E2E Tests", "tests/test_e2e_iris_constructs.py", "e2e"),
            ]
        )

    # Run test suites
    results = []
    total_start_time = time.time()

    for suite_name, test_path, markers in test_suites:
        logger.info("Starting test suite", name=suite_name)
        start_time = time.time()

        success = run_pytest_suite(test_path, markers, args.verbose)
        duration = time.time() - start_time

        results.append((suite_name, success, duration))

        if success:
            logger.info("Test suite completed", name=suite_name, duration=f"{duration:.2f}s")
        else:
            logger.error("Test suite failed", name=suite_name, duration=f"{duration:.2f}s")

        print("-" * 80)

    # Summary
    total_duration = time.time() - total_start_time
    passed = sum(1 for _, success, _ in results if success)
    total = len(results)

    print(f"\n{'='*80}")
    print("IRIS SQL Constructs Test Results")
    print(f"{'='*80}")

    for suite_name, success, duration in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {suite_name:<30} ({duration:.2f}s)")

    print(f"{'='*80}")
    print(f"Total: {passed}/{total} test suites passed")
    print(f"Total time: {total_duration:.2f}s")

    if passed == total:
        print("🎉 All test suites passed!")
        logger.info("All test suites passed", passed=passed, total=total, duration=total_duration)
        return True
    else:
        print(f"❌ {total - passed} test suite(s) failed")
        logger.error("Some test suites failed", passed=passed, total=total, failed=total - passed)
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)

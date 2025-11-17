"""
CLI Command for Package Quality Validation (T013)

Usage:
    python -m iris_pgwire.quality [options]

Options:
    --verbose: Show detailed validation output
    --report-format=json|markdown: Output format (default: markdown)
    --fail-fast: Stop on first validation failure

Examples:
    python -m iris_pgwire.quality
    python -m iris_pgwire.quality --verbose
    python -m iris_pgwire.quality --report-format=json
"""

import argparse
import json
import sys
from pathlib import Path

from iris_pgwire.quality.validator import PackageQualityValidator


def main():
    """Main CLI entry point for package validation"""
    parser = argparse.ArgumentParser(
        description="Validate iris-pgwire package quality for PyPI distribution",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m iris_pgwire.quality                      # Run all validations
  python -m iris_pgwire.quality --verbose            # Show detailed output
  python -m iris_pgwire.quality --report-format=json # JSON output
  python -m iris_pgwire.quality --fail-fast          # Stop on first failure

Exit codes:
  0 - Package is ready for PyPI (validation passed)
  1 - Package is not ready (validation failed)
  2 - Error during validation execution
""",
    )

    parser.add_argument("--verbose", action="store_true", help="Show detailed validation output")

    parser.add_argument(
        "--report-format",
        choices=["json", "markdown"],
        default="markdown",
        help="Output report format (default: markdown)",
    )

    parser.add_argument("--fail-fast", action="store_true", help="Stop on first validation failure")

    parser.add_argument(
        "--package-root",
        type=str,
        default=".",
        help="Root directory of package to validate (default: current directory)",
    )

    args = parser.parse_args()

    # Resolve package root to absolute path
    package_root = Path(args.package_root).resolve()
    if not package_root.exists():
        print(f"❌ Error: Package root does not exist: {package_root}", file=sys.stderr)
        sys.exit(2)

    if args.verbose:
        print(f"🔍 Validating package at: {package_root}")
        print()

    # Initialize validator
    try:
        validator = PackageQualityValidator()
    except Exception as e:
        print(f"❌ Error initializing validator: {e}", file=sys.stderr)
        sys.exit(2)

    # Run comprehensive validation
    try:
        if args.verbose:
            print("Running comprehensive package validation...")
            print("  1️⃣  Package metadata (pyroma, check-manifest)")
            print("  2️⃣  Code quality (black, ruff, mypy)")
            print("  3️⃣  Security (bandit, pip-audit)")
            print("  4️⃣  Documentation (interrogate, README, CHANGELOG)")
            print()

        result = validator.validate_all(str(package_root))

        # Generate output based on format
        if args.report_format == "json":
            # Convert result to JSON (TypedDict is JSON-serializable)
            output = json.dumps(result, indent=2, default=str)
            print(output)
        else:
            # Markdown format (default)
            report = validator.generate_report(result)
            print(report)

        # Determine exit code
        if result["is_pypi_ready"]:
            if args.verbose:
                print()
                print("✅ Package validation PASSED - Ready for PyPI distribution")
            sys.exit(0)
        else:
            if args.verbose:
                print()
                print(
                    f"❌ Package validation FAILED - {len(result['blocking_issues'])} blocking issues"
                )
                print()
                print("Blocking issues:")
                for issue in result["blocking_issues"]:
                    print(f"  - {issue}")
            sys.exit(1)

    except FileNotFoundError as e:
        print(f"❌ Error: Required file not found: {e}", file=sys.stderr)
        if args.verbose:
            print("   Ensure pyproject.toml, README.md, and CHANGELOG.md exist", file=sys.stderr)
        sys.exit(2)

    except Exception as e:
        print(f"❌ Error during validation: {e}", file=sys.stderr)
        if args.verbose:
            import traceback

            traceback.print_exc()
        sys.exit(2)


if __name__ == "__main__":
    main()

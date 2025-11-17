"""
Code Quality Validator Implementation (T009)

Validates Python code quality using industry-standard tools:
- black: Code formatter (zero reformatting check)
- ruff: Fast Rust-based linter
- mypy: Static type checking

Constitutional Requirement: Production Readiness (Principle V)
"""

import subprocess
from pathlib import Path
from typing import TypedDict


class CodeQualityValidationResult(TypedDict):
    """Result of code quality validation"""

    is_valid: bool
    black_passed: bool
    ruff_passed: bool
    mypy_passed: bool
    black_errors: list[str]
    ruff_errors: list[str]
    mypy_errors: list[str]
    files_checked: int
    warnings: list[str]


class CodeQualityValidator:
    """
    Validator for Python code quality standards.

    Implements contract: specs/025-comprehensive-code-and/contracts/code_quality_contract.py
    """

    def validate_code_quality(
        self, source_paths: list[str], check_types: bool = True
    ) -> CodeQualityValidationResult:
        """
        Validate code quality across multiple dimensions.

        Args:
            source_paths: List of paths to validate (e.g., ["src/", "tests/"])
            check_types: Whether to run mypy type checking (default: True)

        Returns:
            CodeQualityValidationResult with validation status

        Raises:
            FileNotFoundError: If source_paths do not exist
        """
        # Validate paths exist
        for path in source_paths:
            if not Path(path).exists():
                raise FileNotFoundError(f"Path does not exist: {path}")

        # Run all quality checks
        black_passed, black_errors = self.check_black_formatting(source_paths)
        ruff_passed, ruff_errors = self.check_ruff_linting(source_paths)

        # Type checking is optional (gradual adoption)
        mypy_passed = True
        mypy_errors = []
        if check_types:
            # For mypy, only check public API modules (not all paths)
            public_modules = self._extract_public_modules(source_paths)
            mypy_passed, mypy_errors = self.check_type_annotations(public_modules)

        # Count files checked
        files_checked = self._count_python_files(source_paths)

        # Validation passes if black and ruff pass (mypy is informational)
        is_valid = black_passed and ruff_passed

        # Generate warnings
        warnings = []
        if not mypy_passed:
            warnings.append("Type checking failed - consider adding type hints (gradual adoption)")

        return CodeQualityValidationResult(
            is_valid=is_valid,
            black_passed=black_passed,
            ruff_passed=ruff_passed,
            mypy_passed=mypy_passed,
            black_errors=black_errors,
            ruff_errors=ruff_errors,
            mypy_errors=mypy_errors,
            files_checked=files_checked,
            warnings=warnings,
        )

    def check_black_formatting(self, paths: list[str]) -> tuple[bool, list[str]]:
        """
        Run black formatter in check mode (no modifications).

        Args:
            paths: List of paths to check

        Returns:
            Tuple of (all_formatted: bool, files_needing_format: list[str])
        """
        try:
            result = subprocess.run(
                ["black", "--check", "--quiet"] + paths,
                capture_output=True,
                text=True,
                timeout=60,
            )

            # black --check returns 0 if formatted, 1 if changes needed
            all_formatted = result.returncode == 0

            # Parse output to find files needing formatting
            files_needing_format = []
            if result.returncode != 0:
                # black outputs "would reformat <file>" for each file
                for line in result.stdout.split("\n") + result.stderr.split("\n"):
                    if "would reformat" in line.lower():
                        # Extract filename from "would reformat <file>"
                        parts = line.split()
                        if len(parts) >= 3:
                            files_needing_format.append(parts[2])

            return (all_formatted, files_needing_format)

        except subprocess.TimeoutExpired:
            return (False, ["black check timed out"])
        except FileNotFoundError:
            return (False, ["black not installed"])
        except Exception as e:
            return (False, [f"black check failed: {e}"])

    def check_ruff_linting(self, paths: list[str]) -> tuple[bool, list[str]]:
        """
        Run ruff linter for code quality issues.

        Args:
            paths: List of paths to lint

        Returns:
            Tuple of (no_errors: bool, error_messages: list[str])
        """
        try:
            result = subprocess.run(
                ["ruff", "check"] + paths,
                capture_output=True,
                text=True,
                timeout=60,
            )

            # ruff returns 0 if no errors, non-zero if errors found
            no_errors = result.returncode == 0

            # Parse error messages
            error_messages = []
            if result.returncode != 0:
                # ruff outputs errors line by line
                output = result.stdout + result.stderr
                for line in output.split("\n"):
                    line = line.strip()
                    if line and not line.startswith("Found"):
                        error_messages.append(line)

            return (no_errors, error_messages)

        except subprocess.TimeoutExpired:
            return (False, ["ruff check timed out"])
        except FileNotFoundError:
            return (False, ["ruff not installed"])
        except Exception as e:
            return (False, [f"ruff check failed: {e}"])

    def check_type_annotations(self, modules: list[str]) -> tuple[bool, list[str]]:
        """
        Run mypy type checker for annotation coverage.

        Args:
            modules: List of Python modules to type-check

        Returns:
            Tuple of (no_errors: bool, type_errors: list[str])
        """
        if not modules:
            # No modules to check
            return (True, [])

        try:
            result = subprocess.run(
                ["mypy"] + modules,
                capture_output=True,
                text=True,
                timeout=120,
            )

            # mypy returns 0 if no errors, 1 if errors found
            no_errors = result.returncode == 0

            # Parse error messages
            type_errors = []
            if result.returncode != 0:
                # mypy outputs errors line by line
                output = result.stdout + result.stderr
                for line in output.split("\n"):
                    line = line.strip()
                    if line and "error:" in line.lower():
                        type_errors.append(line)

            return (no_errors, type_errors)

        except subprocess.TimeoutExpired:
            return (False, ["mypy check timed out"])
        except FileNotFoundError:
            return (False, ["mypy not installed"])
        except Exception as e:
            return (False, [f"mypy check failed: {e}"])

    def measure_complexity(self, paths: list[str]) -> dict[str, int]:
        """
        Measure cyclomatic complexity of code (informational).

        Args:
            paths: List of paths to analyze

        Returns:
            Dictionary with complexity metrics
        """
        # Basic implementation: count functions and classes
        # In production, could use radon or other complexity tools
        metrics = {
            "total_functions": 0,
            "total_classes": 0,
            "avg_complexity": 0,  # Placeholder
        }

        for path_str in paths:
            path = Path(path_str)
            if path.is_file() and path.suffix == ".py":
                python_files = [path]
            elif path.is_dir():
                python_files = list(path.rglob("*.py"))
            else:
                continue

            for py_file in python_files:
                try:
                    with open(py_file) as f:
                        content = f.read()
                        # Simple heuristic: count function/class definitions
                        metrics["total_functions"] += content.count("\ndef ")
                        metrics["total_classes"] += content.count("\nclass ")
                except Exception:
                    pass

        return metrics

    def _extract_public_modules(self, source_paths: list[str]) -> list[str]:
        """
        Extract public API modules from source paths.

        For iris-pgwire, public APIs are:
        - src/iris_pgwire/server.py
        - src/iris_pgwire/protocol.py
        """
        public_modules = []

        for path_str in source_paths:
            path = Path(path_str)

            # Check if this is the src/ directory
            if "src" in path.parts or path.name == "src":
                # Look for public API files
                server_py = path / "iris_pgwire" / "server.py" if path.is_dir() else None
                protocol_py = path / "iris_pgwire" / "protocol.py" if path.is_dir() else None

                if server_py and server_py.exists():
                    public_modules.append(str(server_py))
                if protocol_py and protocol_py.exists():
                    public_modules.append(str(protocol_py))

        return public_modules

    def _count_python_files(self, paths: list[str]) -> int:
        """Count total Python files in given paths"""
        count = 0

        for path_str in paths:
            path = Path(path_str)

            if path.is_file() and path.suffix == ".py":
                count += 1
            elif path.is_dir():
                count += len(list(path.rglob("*.py")))

        return count

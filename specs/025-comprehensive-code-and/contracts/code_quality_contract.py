"""
Code Quality Validation Contract (FR-011)

This contract defines the validation interface for Python code quality standards
including PEP 8 compliance, linting, type checking, and complexity analysis.

CONSTITUTIONAL REQUIREMENT: Production Readiness (Principle V)
- Code MUST pass black formatter (zero reformatting needed)
- Code MUST pass ruff linter (zero errors/warnings)
- Public APIs SHOULD have type hints (gradual adoption via mypy)
"""

from typing import Protocol, TypedDict


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


class CodeQualityValidator(Protocol):
    """
    Contract for code quality validation.

    Validates Python code against PEP 8, linting rules, and type annotations.
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

        Validation Criteria (from data-model.md):
        - PEP 8 Compliance: black --check passes (zero reformatting)
        - Linting: ruff check passes (zero errors/warnings)
        - Type Annotations: mypy passes for public APIs
        - Complexity: Cyclomatic complexity <10 per function (informational)

        Pass Criteria:
            black_passed == True AND ruff_passed == True
            (mypy_passed informational for gradual adoption)

        Raises:
            FileNotFoundError: If source_paths do not exist
        """
        ...

    def check_black_formatting(self, paths: list[str]) -> tuple[bool, list[str]]:
        """
        Run black formatter in check mode (no modifications).

        Args:
            paths: List of paths to check

        Returns:
            Tuple of (all_formatted: bool, files_needing_format: list[str])

        Validation Command (from research.md):
            black --check src/ tests/
            # Expected output if formatted:
            # All done! ✨ 🍰 ✨
            # X files would be left unchanged.

        Configuration (from pyproject.toml):
            [tool.black]
            line-length = 100
            target-version = ["py311"]

        Pass Criteria:
            all_formatted == True (zero files need reformatting)
        """
        ...

    def check_ruff_linting(self, paths: list[str]) -> tuple[bool, list[str]]:
        """
        Run ruff linter for code quality issues.

        Args:
            paths: List of paths to lint

        Returns:
            Tuple of (no_errors: bool, error_messages: list[str])

        Validation Command (from research.md):
            ruff check src/ tests/
            # Expected output if clean:
            # All checks passed!

        Configuration (from pyproject.toml):
            [tool.ruff]
            select = ["E", "W", "F", "I", "B", "C4", "UP"]
            # E/W: pycodestyle errors/warnings
            # F: pyflakes
            # I: isort (import ordering)
            # B: flake8-bugbear
            # C4: flake8-comprehensions
            # UP: pyupgrade

        Pass Criteria:
            no_errors == True (zero linter errors/warnings)
        """
        ...

    def check_type_annotations(self, modules: list[str]) -> tuple[bool, list[str]]:
        """
        Run mypy type checker for annotation coverage.

        Args:
            modules: List of Python modules to type-check

        Returns:
            Tuple of (no_errors: bool, type_errors: list[str])

        Validation Command (from research.md):
            mypy src/iris_pgwire/server.py src/iris_pgwire/protocol.py
            # Expected output:
            # Success: no issues found in X source files

        Configuration (from pyproject.toml):
            [tool.mypy]
            python_version = "3.11"
            check_untyped_defs = true
            disallow_incomplete_defs = true

        Implementation Strategy (from research.md):
        - Phase 1: Type check public APIs only (server.py, protocol.py)
        - Phase 2: Type check core modules (iris_executor.py, vector_optimizer.py)
        - Phase 3: Type check entire codebase
        - Use # type: ignore sparingly with justification

        Pass Criteria:
            no_errors == True for specified modules
            (gradual adoption - start with public APIs)
        """
        ...

    def measure_complexity(self, source_path: str) -> dict[str, int]:
        """
        Measure cyclomatic complexity for codebase (informational).

        Args:
            source_path: Path to source code directory

        Returns:
            Dict mapping file paths to complexity scores

        Validation Rules (from data-model.md):
        - Cyclomatic complexity SHOULD be <10 per function
        - File length SHOULD be <500 lines
        - Function length SHOULD be <50 lines

        Note: This is informational only (not a pass/fail criterion)
        Used for identifying refactoring opportunities
        """
        ...


# Contract Test Requirements (TDD):
#
# 1. Test validate_code_quality() on iris-pgwire src/ → returns is_valid=True
# 2. Test validate_code_quality() on unformatted code → returns black_passed=False
# 3. Test check_black_formatting() on formatted code → returns (True, [])
# 4. Test check_black_formatting() on unformatted code → returns (False, [file_list])
# 5. Test check_ruff_linting() on clean code → returns (True, [])
# 6. Test check_ruff_linting() on code with violations → returns (False, [errors])
# 7. Test check_type_annotations() on typed module → returns (True, [])
# 8. Test check_type_annotations() on untyped module → returns (False, [errors])
# 9. Test measure_complexity() returns dict with complexity scores
#
# CRITICAL: All tests MUST fail initially (no implementation exists yet)
# Implement CodeQualityValidator to make tests pass (Red-Green-Refactor)

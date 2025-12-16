"""
Package Metadata Validation Contract (FR-001)

This contract defines the validation interface for package metadata completeness
and quality as specified in PEP 621 and evaluated by pyroma quality checker.

CONSTITUTIONAL REQUIREMENT: Production Readiness (Principle V)
- Package metadata MUST be complete for professional PyPI distribution
- pyroma score MUST be ≥9/10 for release readiness
"""

from typing import Protocol, TypedDict


class PackageMetadataValidationResult(TypedDict):
    """Result of package metadata validation"""

    is_valid: bool
    pyroma_score: int
    pyroma_max_score: int
    missing_fields: list[str]
    invalid_classifiers: list[str]
    validation_errors: list[str]
    warnings: list[str]


class PackageMetadataValidator(Protocol):
    """
    Contract for package metadata validation.

    Validates pyproject.toml completeness against PEP 621 requirements
    and professional packaging standards.
    """

    def validate_metadata(self, pyproject_path: str) -> PackageMetadataValidationResult:
        """
        Validate package metadata completeness and quality.

        Args:
            pyproject_path: Path to pyproject.toml file

        Returns:
            PackageMetadataValidationResult with validation status

        Validation Criteria (from data-model.md):
        - All required PEP 621 fields present (name, version, description, etc.)
        - Version follows semantic versioning (MAJOR.MINOR.PATCH)
        - Classifiers are valid per trove-classifiers package
        - Dependencies have version constraints (>=X.Y)
        - URLs are accessible (Homepage, Documentation, Repository, Issues)
        - pyroma score ≥9/10 for professional packages

        Raises:
            FileNotFoundError: If pyproject_path does not exist
            ValueError: If pyproject.toml is malformed
        """
        ...

    def check_pyroma_score(self, package_path: str) -> tuple[int, int]:
        """
        Run pyroma quality checker and return score.

        Args:
            package_path: Path to package root directory

        Returns:
            Tuple of (actual_score, max_score) - e.g., (9, 10)

        Validation Command (from research.md):
            pyroma .
            # Expected output:
            # Checking .
            # Found iris-pgwire
            # --------------
            # Your package scores 9 out of 10
            # --------------------------

        Pass Criteria:
            actual_score ≥ 9
        """
        ...

    def validate_classifiers(self, classifiers: list[str]) -> tuple[bool, list[str]]:
        """
        Validate PyPI classifiers against trove-classifiers database.

        Args:
            classifiers: List of classifier strings from pyproject.toml

        Returns:
            Tuple of (all_valid: bool, invalid_classifiers: list[str])

        Required Classifier Categories (from research.md):
        - Development Status (Alpha/Beta/Stable)
        - Intended Audience (Developers/System Administrators)
        - License (OSI Approved :: MIT)
        - Operating System (OS Independent)
        - Programming Language (Python :: 3.11, 3.12)
        - Topic (Database, Networking)

        Pass Criteria:
            all_valid == True (no invalid classifiers)
        """
        ...

    def validate_dependencies(self, dependencies: dict[str, str]) -> tuple[bool, list[str]]:
        """
        Validate dependency version constraints.

        Args:
            dependencies: Dict of {package_name: version_constraint}

        Returns:
            Tuple of (all_valid: bool, validation_errors: list[str])

        Validation Rules (from data-model.md):
        - Runtime dependencies MUST use version constraints (>=X.Y)
        - Version constraints MUST be compatible (no conflicts)
        - NO overly permissive constraints without upper bound consideration

        Pass Criteria:
            all_valid == True (all constraints specified correctly)
        """
        ...

    def check_manifest_completeness(self, package_path: str) -> tuple[bool, str]:
        """
        Run check-manifest to validate source distribution completeness.

        Args:
            package_path: Path to package root directory

        Returns:
            Tuple of (is_complete: bool, output_message: str)

        Validation Command (from research.md):
            check-manifest
            # Expected output if valid:
            # lists of files in version control: X
            # lists of files in sdist: X
            # OK

        Pass Criteria:
            output_message contains "OK"
        """
        ...


# Contract Test Requirements (TDD):
#
# 1. Test validate_metadata() with complete pyproject.toml → returns is_valid=True
# 2. Test validate_metadata() with missing required fields → returns is_valid=False, lists missing_fields
# 3. Test check_pyroma_score() on iris-pgwire package → returns score ≥9
# 4. Test validate_classifiers() with valid classifiers → returns (True, [])
# 5. Test validate_classifiers() with invalid classifier → returns (False, [invalid_classifier])
# 6. Test validate_dependencies() with proper constraints → returns (True, [])
# 7. Test validate_dependencies() with missing constraint → returns (False, [error_message])
# 8. Test check_manifest_completeness() on iris-pgwire → returns (True, "OK")
#
# CRITICAL: All tests MUST fail initially (no implementation exists yet)
# Implement PackageMetadataValidator to make tests pass (Red-Green-Refactor)

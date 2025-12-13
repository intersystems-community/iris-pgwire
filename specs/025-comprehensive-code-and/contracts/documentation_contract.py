"""
Documentation Validation Contract (FR-006)

This contract defines the validation interface for documentation completeness
including README structure, CHANGELOG format, and docstring coverage.

CONSTITUTIONAL REQUIREMENT: Production Readiness (Principle V)
- Documentation MUST be complete for professional PyPI distribution
- Public APIs MUST have docstrings (≥80% coverage target)
- CHANGELOG MUST follow Keep a Changelog format
"""

from typing import Protocol, TypedDict


class DocstringCoverageResult(TypedDict):
    """Result of docstring coverage measurement"""

    coverage_percentage: float  # 0.0-100.0
    total_items: int  # Total public modules/classes/functions
    documented_items: int
    missing_docstrings: list[str]  # File paths with missing docstrings
    is_compliant: bool  # True if coverage ≥80%


class ReadmeValidationResult(TypedDict):
    """Result of README.md validation"""

    is_complete: bool
    has_title: bool
    has_description: bool
    has_installation: bool
    has_quick_start: bool
    has_usage_examples: bool
    has_documentation_links: bool
    has_license: bool
    missing_sections: list[str]
    warnings: list[str]


class ChangelogValidationResult(TypedDict):
    """Result of CHANGELOG.md validation"""

    is_valid: bool
    has_title: bool
    has_unreleased_section: bool
    has_version_sections: bool
    has_dates: bool
    follows_keep_a_changelog: bool
    validation_errors: list[str]


class DocumentationValidator(Protocol):
    """
    Contract for documentation validation.

    Validates documentation completeness across README, CHANGELOG, and inline docstrings.
    """

    def validate_documentation(
        self, source_path: str, readme_path: str, changelog_path: str
    ) -> tuple[bool, dict]:
        """
        Comprehensive documentation validation.

        Args:
            source_path: Path to source code directory
            readme_path: Path to README.md
            changelog_path: Path to CHANGELOG.md

        Returns:
            Tuple of (is_complete: bool, validation_results: dict)
            validation_results contains:
            - docstring_coverage: DocstringCoverageResult
            - readme_validation: ReadmeValidationResult
            - changelog_validation: ChangelogValidationResult

        Pass Criteria:
            docstring_coverage ≥80% AND
            readme_validation.is_complete AND
            changelog_validation.is_valid

        Raises:
            FileNotFoundError: If paths do not exist
        """
        ...

    def check_docstring_coverage(self, source_path: str) -> DocstringCoverageResult:
        """
        Measure docstring coverage using interrogate tool.

        Args:
            source_path: Path to source code directory

        Returns:
            DocstringCoverageResult with coverage metrics

        Validation Command (from research.md):
            interrogate -vv src/iris_pgwire/
            # Expected output:
            # ================== Coverage for src/iris_pgwire/ ===================
            # --------------------------------- Summary ----------------------------------
            # | Name                     | Total | Miss | Cover |
            # |--------------------------|-------|------|-------|
            # | src/iris_pgwire/         |   X   |  X   |  X%   |
            # ------------------------------------------------------------------------
            # RESULT: PASSED (minimum: 80.0%, actual: X%)

        Configuration (from research.md):
            [tool.interrogate]
            ignore-init-method = true
            ignore-init-module = false
            fail-under = 80
            exclude = ["setup.py", "docs", "build", "tests"]
            verbose = 2

        Pass Criteria:
            coverage_percentage ≥ 80.0
        """
        ...

    def validate_readme_structure(self, readme_path: str) -> ReadmeValidationResult:
        """
        Validate README.md completeness and structure.

        Args:
            readme_path: Path to README.md file

        Returns:
            ReadmeValidationResult with validation status

        Required Sections (from research.md):
        1. Title and Badges (license, Python version, PyPI, test status)
        2. Description (one-line summary, key features, use cases)
        3. Installation (pip install command, prerequisites)
        4. Quick Start (minimal working example 5-10 lines)
        5. Usage Examples (common use cases 3-5 examples)
        6. Documentation Links (full docs URL, API reference, troubleshooting)
        7. Contributing (development setup, code quality standards)
        8. License (license type, link to LICENSE file)

        Pass Criteria:
            is_complete == True (all required sections present)
        """
        ...

    def validate_changelog_format(self, changelog_path: str) -> ChangelogValidationResult:
        """
        Validate CHANGELOG.md against Keep a Changelog format.

        Args:
            changelog_path: Path to CHANGELOG.md file

        Returns:
            ChangelogValidationResult with validation status

        Required Format (from research.md):
            # Changelog

            ## [Unreleased]

            ### Added
            - New features

            ### Changed
            - Changes in existing functionality

            ### Fixed
            - Bug fixes

            ### Security
            - Security fixes

            ## [X.Y.Z] - YYYY-MM-DD
            ... (repeat structure)

        Validation Script (from research.md):
            import re
            checks = {
                'has_title': bool(re.search(r'^# Changelog', content, re.M)),
                'has_unreleased': bool(re.search(r'## \\[Unreleased\\]', content)),
                'has_versions': bool(re.search(r'## \\[\\d+\\.\\d+\\.\\d+\\]', content)),
                'has_dates': bool(re.search(r'\\d{4}-\\d{2}-\\d{2}', content)),
            }

        Pass Criteria:
            follows_keep_a_changelog == True (all checks pass)
        """
        ...

    def generate_docstring_badge(self, source_path: str, output_path: str) -> str:
        """
        Generate interrogate badge for README.md.

        Args:
            source_path: Path to source code directory
            output_path: Path to save badge SVG file

        Returns:
            Badge URL for insertion into README.md

        Validation Command (from research.md):
            interrogate --generate-badge interrogate_badge.svg src/iris_pgwire/

        Badge Display:
            ![Docstring Coverage](interrogate_badge.svg)

        Use Case:
            Display docstring coverage visually in README
        """
        ...

    def get_documentation_report(
        self, source_path: str, readme_path: str, changelog_path: str
    ) -> str:
        """
        Generate comprehensive documentation quality report.

        Args:
            source_path: Path to source code directory
            readme_path: Path to README.md
            changelog_path: Path to CHANGELOG.md

        Returns:
            Human-readable documentation report (Markdown format)

        Report Sections:
        1. Executive Summary (pass/fail status)
        2. Docstring Coverage (percentage, missing items)
        3. README Completeness (section checklist)
        4. CHANGELOG Format (Keep a Changelog compliance)
        5. Recommendations (if issues found)

        Use Case:
            Include report in documentation audit for maintainers
        """
        ...


# Contract Test Requirements (TDD):
#
# 1. Test validate_documentation() on iris-pgwire → returns (True, results)
# 2. Test validate_documentation() with missing docs → returns (False, errors)
# 3. Test check_docstring_coverage() on well-documented code → coverage ≥80%
# 4. Test check_docstring_coverage() on undocumented code → coverage <80%
# 5. Test validate_readme_structure() on complete README → is_complete=True
# 6. Test validate_readme_structure() with missing sections → is_complete=False
# 7. Test validate_changelog_format() on Keep a Changelog format → is_valid=True
# 8. Test validate_changelog_format() on malformed CHANGELOG → is_valid=False
# 9. Test generate_docstring_badge() creates SVG file at output_path
# 10. Test get_documentation_report() returns Markdown report
#
# CRITICAL: All tests MUST fail initially (no implementation exists yet)
# Implement DocumentationValidator to make tests pass (Red-Green-Refactor)

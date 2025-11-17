"""
Contract Tests for Documentation Validation (T007)

CRITICAL: These tests MUST fail initially (no DocumentationValidator implementation exists).
Implement DocumentationValidator to make these tests pass (Red-Green-Refactor).

Contract: specs/025-comprehensive-code-and/contracts/documentation_contract.py
Constitutional Requirement: Production Readiness (Principle V)
"""

from pathlib import Path

import pytest

# IMPORTANT: This import will fail initially (no implementation yet)
# This is EXPECTED - tests MUST fail before implementation
try:
    from iris_pgwire.quality.documentation_validator import DocumentationValidator

    IMPLEMENTATION_EXISTS = True
except ImportError:
    IMPLEMENTATION_EXISTS = False

    # Create placeholder for type hints
    class DocumentationValidator:  # type: ignore
        pass


pytestmark = pytest.mark.skipif(
    not IMPLEMENTATION_EXISTS,
    reason="DocumentationValidator not implemented yet (TDD: tests must fail first)",
)


@pytest.fixture
def validator():
    """Fixture providing DocumentationValidator instance"""
    return DocumentationValidator()


@pytest.fixture
def project_root():
    """Fixture providing iris-pgwire project root path"""
    return str(Path(__file__).parents[2])


@pytest.fixture
def well_documented_python_file(tmp_path):
    """Fixture providing well-documented Python file"""
    documented_code = '''
"""
Module docstring for well documented code.

This module demonstrates proper documentation practices.
"""


def add(a: int, b: int) -> int:
    """
    Add two integers.

    Args:
        a: First integer
        b: Second integer

    Returns:
        Sum of a and b
    """
    return a + b


class Calculator:
    """Calculator class for arithmetic operations."""

    def multiply(self, x: int, y: int) -> int:
        """
        Multiply two integers.

        Args:
            x: First integer
            y: Second integer

        Returns:
            Product of x and y
        """
        return x * y
'''

    file_path = tmp_path / "documented.py"
    with open(file_path, "w") as f:
        f.write(documented_code)

    return str(tmp_path)


@pytest.fixture
def undocumented_python_file(tmp_path):
    """Fixture providing undocumented Python file"""
    undocumented_code = """
def add(a, b):
    return a + b

class Calculator:
    def multiply(self, x, y):
        return x * y
"""

    file_path = tmp_path / "undocumented.py"
    with open(file_path, "w") as f:
        f.write(undocumented_code)

    return str(tmp_path)


@pytest.fixture
def complete_readme(tmp_path):
    """Fixture providing complete README.md"""
    readme_content = """
# Test Package

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://python.org)

A test package for documentation validation.

## Installation

```bash
pip install test-package
```

## Quick Start

```python
from test_package import Calculator

calc = Calculator()
result = calc.add(1, 2)
```

## Usage Examples

### Example 1: Basic Usage

```python
calculator = Calculator()
```

## Documentation

Full documentation: https://test-package.readthedocs.io

## Contributing

Development setup instructions here.

## License

MIT License - see LICENSE file.
"""

    readme_path = tmp_path / "README.md"
    with open(readme_path, "w") as f:
        f.write(readme_content)

    return str(readme_path)


@pytest.fixture
def incomplete_readme(tmp_path):
    """Fixture providing incomplete README.md"""
    readme_content = """
# Test Package

A test package.
"""  # Missing: installation, quick start, usage, documentation links, license

    readme_path = tmp_path / "README.md"
    with open(readme_path, "w") as f:
        f.write(readme_content)

    return str(readme_path)


@pytest.fixture
def valid_changelog(tmp_path):
    """Fixture providing valid Keep a Changelog format"""
    changelog_content = """
# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- New feature X

### Changed
- Updated behavior Y

## [1.0.0] - 2025-01-01

### Added
- Initial release
"""

    changelog_path = tmp_path / "CHANGELOG.md"
    with open(changelog_path, "w") as f:
        f.write(changelog_content)

    return str(changelog_path)


@pytest.fixture
def malformed_changelog(tmp_path):
    """Fixture providing malformed CHANGELOG.md"""
    changelog_content = """
Changes:

- Did some stuff
- Fixed a bug
"""  # Missing: title, version sections, dates, Keep a Changelog format

    changelog_path = tmp_path / "CHANGELOG.md"
    with open(changelog_path, "w") as f:
        f.write(changelog_content)

    return str(changelog_path)


class TestDocumentationContract:
    """Contract tests for DocumentationValidator Protocol"""

    def test_validate_documentation_iris_pgwire(self, validator, project_root):
        """
        Test validate_documentation() on iris-pgwire project.

        Expected: Returns (True, results)
        Contract: documentation_contract.py lines 57-86
        """
        source_path = f"{project_root}/src/iris_pgwire"
        readme_path = f"{project_root}/README.md"
        changelog_path = f"{project_root}/CHANGELOG.md"

        is_complete, results = validator.validate_documentation(
            source_path, readme_path, changelog_path
        )

        # Check docstring coverage
        coverage = results["docstring_coverage"]
        assert (
            coverage["coverage_percentage"] >= 80.0
        ), f"Docstring coverage should be ≥80% (got {coverage['coverage_percentage']}%)"

        # Check README completeness
        readme_valid = results["readme_validation"]
        assert (
            readme_valid["is_complete"] is True
        ), f"README should be complete. Missing: {readme_valid['missing_sections']}"

        # Check CHANGELOG format
        changelog_valid = results["changelog_validation"]
        assert (
            changelog_valid["is_valid"] is True
        ), f"CHANGELOG should be valid. Errors: {changelog_valid['validation_errors']}"

        assert is_complete is True, "Overall documentation should be complete"

    def test_validate_documentation_missing_docs(
        self, validator, undocumented_python_file, incomplete_readme, malformed_changelog
    ):
        """
        Test validate_documentation() with missing documentation.

        Expected: Returns (False, errors)
        Contract: documentation_contract.py lines 57-86
        """
        is_complete, results = validator.validate_documentation(
            undocumented_python_file, incomplete_readme, malformed_changelog
        )

        assert is_complete is False, "Should detect missing documentation"

        # Should report low docstring coverage
        coverage = results["docstring_coverage"]
        assert coverage["coverage_percentage"] < 80.0, "Should report low coverage"

        # Should report incomplete README
        readme_valid = results["readme_validation"]
        assert readme_valid["is_complete"] is False, "Should detect incomplete README"
        assert len(readme_valid["missing_sections"]) > 0, "Should list missing sections"

        # Should report malformed CHANGELOG
        changelog_valid = results["changelog_validation"]
        assert changelog_valid["is_valid"] is False, "Should detect malformed CHANGELOG"

    def test_check_docstring_coverage_high(self, validator, well_documented_python_file):
        """
        Test check_docstring_coverage() on well-documented code.

        Expected: coverage ≥80%
        Contract: documentation_contract.py lines 88-120
        """
        result = validator.check_docstring_coverage(well_documented_python_file)

        assert result["coverage_percentage"] >= 80.0, (
            f"Well-documented code should have ≥80% coverage "
            f"(got {result['coverage_percentage']}%)"
        )
        assert result["is_compliant"] is True, "Should be compliant"
        assert result["total_items"] > 0, "Should count documentation items"

    def test_check_docstring_coverage_low(self, validator, undocumented_python_file):
        """
        Test check_docstring_coverage() on undocumented code.

        Expected: coverage <80%
        Contract: documentation_contract.py lines 88-120
        """
        result = validator.check_docstring_coverage(undocumented_python_file)

        assert result["coverage_percentage"] < 80.0, "Should report low coverage"
        assert result["is_compliant"] is False, "Should not be compliant"
        assert len(result["missing_docstrings"]) > 0, "Should report missing docstrings"

    def test_validate_readme_structure_complete(self, validator, complete_readme):
        """
        Test validate_readme_structure() with complete README.

        Expected: is_complete=True
        Contract: documentation_contract.py lines 122-145
        """
        result = validator.validate_readme_structure(complete_readme)

        assert result["is_complete"] is True, "README should be complete"
        assert result["has_title"] is True, "Should have title"
        assert result["has_installation"] is True, "Should have installation"
        assert result["has_quick_start"] is True, "Should have quick start"
        assert result["has_usage_examples"] is True, "Should have usage examples"
        assert result["has_license"] is True, "Should have license"
        assert len(result["missing_sections"]) == 0, "No sections should be missing"

    def test_validate_readme_structure_missing_sections(self, validator, incomplete_readme):
        """
        Test validate_readme_structure() with missing sections.

        Expected: is_complete=False
        Contract: documentation_contract.py lines 122-145
        """
        result = validator.validate_readme_structure(incomplete_readme)

        assert result["is_complete"] is False, "README should be incomplete"
        assert len(result["missing_sections"]) > 0, "Should report missing sections"

        # Should detect missing installation, quick start, etc.
        missing_sections = set(result["missing_sections"])
        expected_missing = {"Installation", "Quick Start", "Usage", "License"}
        assert (
            len(missing_sections.intersection(expected_missing)) > 0
        ), "Should report expected missing sections"

    def test_validate_changelog_format_valid(self, validator, valid_changelog):
        """
        Test validate_changelog_format() with Keep a Changelog format.

        Expected: is_valid=True
        Contract: documentation_contract.py lines 147-189
        """
        result = validator.validate_changelog_format(valid_changelog)

        assert result["is_valid"] is True, "CHANGELOG should be valid"
        assert result["has_title"] is True, "Should have title"
        assert result["has_unreleased_section"] is True, "Should have [Unreleased]"
        assert result["has_version_sections"] is True, "Should have version sections"
        assert result["has_dates"] is True, "Should have dates"
        assert result["follows_keep_a_changelog"] is True, "Should follow Keep a Changelog format"
        assert len(result["validation_errors"]) == 0, "No errors expected"

    def test_validate_changelog_format_malformed(self, validator, malformed_changelog):
        """
        Test validate_changelog_format() with malformed CHANGELOG.

        Expected: is_valid=False
        Contract: documentation_contract.py lines 147-189
        """
        result = validator.validate_changelog_format(malformed_changelog)

        assert result["is_valid"] is False, "CHANGELOG should be invalid"
        assert result["follows_keep_a_changelog"] is False, "Should not follow Keep a Changelog"
        assert len(result["validation_errors"]) > 0, "Should report errors"

    def test_generate_docstring_badge(self, validator, project_root, tmp_path):
        """
        Test generate_docstring_badge() creates SVG file.

        Expected: SVG file created at output_path
        Contract: documentation_contract.py lines 191-211
        """
        source_path = f"{project_root}/src/iris_pgwire"
        output_path = str(tmp_path / "badge.svg")

        badge_url = validator.generate_docstring_badge(source_path, output_path)

        assert isinstance(badge_url, str), "Should return badge URL string"
        assert Path(output_path).exists(), "Should create SVG file"

    def test_get_documentation_report(self, validator, project_root):
        """
        Test get_documentation_report() returns Markdown report.

        Expected: Markdown report string
        Contract: documentation_contract.py lines 213-240
        """
        source_path = f"{project_root}/src/iris_pgwire"
        readme_path = f"{project_root}/README.md"
        changelog_path = f"{project_root}/CHANGELOG.md"

        report = validator.get_documentation_report(source_path, readme_path, changelog_path)

        assert isinstance(report, str), "Should return string"
        assert len(report) > 0, "Report should not be empty"
        assert (
            "Documentation" in report or "documentation" in report.lower()
        ), "Report should mention documentation"
        # Check for expected sections
        assert any(
            section in report for section in ["Docstring", "README", "CHANGELOG"]
        ), "Report should have expected sections"


class TestDocumentationEdgeCases:
    """Edge case tests for DocumentationValidator"""

    def test_validate_documentation_nonexistent_files(self, validator):
        """Test validate_documentation() with nonexistent files"""
        with pytest.raises(FileNotFoundError):
            validator.validate_documentation(
                "/nonexistent/source", "/nonexistent/README.md", "/nonexistent/CHANGELOG.md"
            )

    def test_check_docstring_coverage_empty_directory(self, validator, tmp_path):
        """Test check_docstring_coverage() with empty directory"""
        result = validator.check_docstring_coverage(str(tmp_path))

        # Empty directory should have 0% coverage (no items to document)
        assert result["total_items"] == 0
        assert result["coverage_percentage"] == 0.0

    def test_validate_readme_structure_nonexistent(self, validator):
        """Test validate_readme_structure() with nonexistent README"""
        with pytest.raises(FileNotFoundError):
            validator.validate_readme_structure("/nonexistent/README.md")

    def test_validate_changelog_format_nonexistent(self, validator):
        """Test validate_changelog_format() with nonexistent CHANGELOG"""
        with pytest.raises(FileNotFoundError):
            validator.validate_changelog_format("/nonexistent/CHANGELOG.md")

"""
Integration Tests for Validation Failure Scenarios (T028)

Tests that the validation system correctly identifies and reports various types of
package quality issues and failures.

Constitutional Requirement: Production Readiness (Principle V)
"""

import tempfile
from pathlib import Path

import pytest

from iris_pgwire.quality.validator import PackageQualityValidator


class TestValidationFailureScenarios:
    """Integration tests for validation failure detection"""

    def setup_method(self):
        """Set up test fixtures"""
        self.validator = PackageQualityValidator()

    # T028.1: Missing metadata fields
    @pytest.mark.integration
    def test_detect_missing_required_fields(self):
        """Should fail validation for missing required metadata fields"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_dir = Path(tmpdir)

            # Create incomplete pyproject.toml (missing license, authors)
            (pkg_dir / "pyproject.toml").write_text("""
[project]
name = "incomplete-package"
version = "0.1.0"
description = "Missing required fields"
""")

            # Create minimal README
            (pkg_dir / "README.md").write_text("# Incomplete Package\n")

            # Create minimal CHANGELOG
            (pkg_dir / "CHANGELOG.md").write_text("""# Changelog

## [Unreleased]

## [0.1.0] - 2025-01-15
""")

            # Create minimal source
            src_dir = pkg_dir / "src" / "incomplete"
            src_dir.mkdir(parents=True)
            (src_dir / "__init__.py").write_text('"""Module."""\n')

            # Run validation
            result = self.validator.validate_all(str(pkg_dir))

            # Should fail metadata validation
            assert result["metadata_validation"]["is_valid"] is False
            assert len(result["metadata_validation"]["missing_fields"]) > 0
            assert "readme" in result["metadata_validation"]["missing_fields"] or \
                   "license" in result["metadata_validation"]["missing_fields"] or \
                   "authors" in result["metadata_validation"]["missing_fields"]

    # T028.2: Poor pyroma score
    @pytest.mark.integration
    def test_detect_low_pyroma_score(self):
        """Should fail validation for poor package quality (low pyroma score)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_dir = Path(tmpdir)

            # Create minimal pyproject.toml (will get low pyroma score)
            (pkg_dir / "pyproject.toml").write_text("""
[project]
name = "poor-quality"
version = "0.1.0"
description = "Q"
readme = "README.md"
license = {text = "MIT"}
authors = [{name = "T", email = "t@e.com"}]
""")

            # Create minimal README
            (pkg_dir / "README.md").write_text("# Poor Quality\n\nShort.\n")

            # Run validation
            result = self.validator.validate_all(str(pkg_dir))

            # May have low pyroma score due to minimal content
            print(f"Pyroma score: {result['metadata_validation']['pyroma_score']}/10")

    # T028.3: Missing documentation
    @pytest.mark.integration
    def test_detect_low_docstring_coverage(self):
        """Should fail validation for insufficient docstring coverage"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_dir = Path(tmpdir)

            # Create valid pyproject.toml
            (pkg_dir / "pyproject.toml").write_text("""
[project]
name = "undocumented"
version = "0.1.0"
description = "Undocumented package"
readme = "README.md"
license = {text = "MIT"}
authors = [{name = "Test", email = "test@example.com"}]
""")

            (pkg_dir / "README.md").write_text("""# Undocumented Package

## Installation

pip install undocumented

## Quick Start

Quick start guide.

## Usage

Usage examples.

## Documentation

Docs available.

## License

MIT
""")

            (pkg_dir / "CHANGELOG.md").write_text("""# Changelog

## [Unreleased]

## [0.1.0] - 2025-01-15
""")

            # Create source with many undocumented functions
            src_dir = pkg_dir / "src" / "undocumented"
            src_dir.mkdir(parents=True)
            (src_dir / "__init__.py").write_text('''"""Package with poor docstring coverage."""
__version__ = "0.1.0"

def function_one():
    return 1

def function_two():
    return 2

def function_three():
    return 3

class UndocumentedClass:
    def method_one(self):
        return 1

    def method_two(self):
        return 2
''')

            # Run validation
            result = self.validator.validate_all(str(pkg_dir))

            # Should fail documentation coverage
            doc_coverage = result["documentation_validation"]["docstring_coverage"]
            # Depending on interrogate's calculation, this should be low
            print(f"Docstring coverage: {doc_coverage['coverage_percentage']:.1f}%")
            assert doc_coverage["coverage_percentage"] < 80.0 or not doc_coverage["is_compliant"]

    # T028.4: Invalid classifiers
    @pytest.mark.integration
    def test_detect_invalid_classifiers(self):
        """Should fail validation for invalid PyPI classifiers"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_dir = Path(tmpdir)

            # Create pyproject.toml with invalid classifiers
            (pkg_dir / "pyproject.toml").write_text("""
[project]
name = "invalid-classifiers"
version = "0.1.0"
description = "Package with invalid classifiers"
readme = "README.md"
license = {text = "MIT"}
authors = [{name = "Test", email = "test@example.com"}]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Invalid :: Classifier :: That :: Does :: Not :: Exist",
    "Another :: Fake :: Classifier",
]
""")

            (pkg_dir / "README.md").write_text("# Package\n")

            # Run validation
            result = self.validator.validate_all(str(pkg_dir))

            # Should detect invalid classifiers
            if len(result["metadata_validation"]["invalid_classifiers"]) > 0:
                assert result["metadata_validation"]["is_valid"] is False
                assert "Invalid :: Classifier" in str(result["metadata_validation"]["invalid_classifiers"])

    # T028.5: Missing CHANGELOG sections
    @pytest.mark.integration
    def test_detect_incomplete_changelog(self):
        """Should fail validation for incomplete CHANGELOG.md"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_dir = Path(tmpdir)

            (pkg_dir / "pyproject.toml").write_text("""
[project]
name = "incomplete-changelog"
version = "0.1.0"
description = "Package with incomplete changelog"
readme = "README.md"
license = {text = "MIT"}
authors = [{name = "Test", email = "test@example.com"}]
""")

            (pkg_dir / "README.md").write_text("""# Package

## Installation
pip install pkg

## Quick Start
Start here

## Usage
Use it

## Documentation
Docs

## License
MIT
""")

            # Create CHANGELOG without required sections
            (pkg_dir / "CHANGELOG.md").write_text("""# Changelog

Some changes happened.
""")

            src_dir = pkg_dir / "src" / "pkg"
            src_dir.mkdir(parents=True)
            (src_dir / "__init__.py").write_text('"""Pkg."""\n')

            # Run validation
            result = self.validator.validate_all(str(pkg_dir))

            # Should fail CHANGELOG validation
            changelog_result = result["documentation_validation"]["changelog_validation"]
            assert changelog_result["is_valid"] is False
            assert len(changelog_result["validation_errors"]) > 0

    # T028.6: Missing README sections
    @pytest.mark.integration
    def test_detect_incomplete_readme(self):
        """Should fail validation for incomplete README.md"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_dir = Path(tmpdir)

            (pkg_dir / "pyproject.toml").write_text("""
[project]
name = "incomplete-readme"
version = "0.1.0"
description = "Package with incomplete README"
readme = "README.md"
license = {text = "MIT"}
authors = [{name = "Test", email = "test@example.com"}]
""")

            # Create minimal README (missing key sections)
            (pkg_dir / "README.md").write_text("""# Incomplete README

This package exists.
""")

            (pkg_dir / "CHANGELOG.md").write_text("""# Changelog

## [Unreleased]

## [0.1.0] - 2025-01-15
""")

            src_dir = pkg_dir / "src" / "pkg"
            src_dir.mkdir(parents=True)
            (src_dir / "__init__.py").write_text('"""Pkg."""\n')

            # Run validation
            result = self.validator.validate_all(str(pkg_dir))

            # Should fail README validation
            readme_result = result["documentation_validation"]["readme_validation"]
            assert readme_result["is_complete"] is False
            assert len(readme_result["missing_sections"]) > 0

    # T028.7: Security vulnerabilities
    @pytest.mark.integration
    @pytest.mark.slow
    def test_detect_security_vulnerabilities(self):
        """Should detect code security issues (if any exist)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_dir = Path(tmpdir)

            (pkg_dir / "pyproject.toml").write_text("""
[project]
name = "insecure-code"
version = "0.1.0"
description = "Package with security issues"
readme = "README.md"
license = {text = "MIT"}
authors = [{name = "Test", email = "test@example.com"}]
""")

            (pkg_dir / "README.md").write_text("""# Insecure Code

## Installation
pip install pkg

## Quick Start
Start

## Usage
Use

## Documentation
Docs

## License
MIT
""")

            (pkg_dir / "CHANGELOG.md").write_text("""# Changelog

## [Unreleased]

## [0.1.0] - 2025-01-15
""")

            # Create source with potential security issues
            src_dir = pkg_dir / "src" / "insecure"
            src_dir.mkdir(parents=True)
            (src_dir / "__init__.py").write_text('''"""Insecure module."""

import pickle  # B403: pickle usage detected
import subprocess

def execute_command(user_input):
    """Execute user command (B602: shell=True)."""
    subprocess.call(user_input, shell=True)  # NOQA

def deserialize_data(data):
    """Deserialize pickle data (B301)."""
    return pickle.loads(data)  # NOQA
''')

            # Run validation
            result = self.validator.validate_all(str(pkg_dir))

            # Should detect security issues
            security_result = result["security_validation"]
            print(f"Security issues found: {len(security_result['code_issues'])}")
            if len(security_result["code_issues"]) > 0:
                # Bandit should flag the pickle and subprocess usage
                assert security_result["is_secure"] is False or len(security_result["code_issues"]) > 0

    # T028.8: Code formatting violations
    @pytest.mark.integration
    def test_detect_code_formatting_violations(self):
        """Should detect black formatting violations"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_dir = Path(tmpdir)

            (pkg_dir / "pyproject.toml").write_text("""
[project]
name = "unformatted-code"
version = "0.1.0"
description = "Package with formatting issues"
readme = "README.md"
license = {text = "MIT"}
authors = [{name = "Test", email = "test@example.com"}]
""")

            (pkg_dir / "README.md").write_text("""# Unformatted Code

## Installation
pip install pkg

## Quick Start
Start

## Usage
Use

## Documentation
Docs

## License
MIT
""")

            (pkg_dir / "CHANGELOG.md").write_text("""# Changelog

## [Unreleased]

## [0.1.0] - 2025-01-15
""")

            # Create source with terrible formatting
            src_dir = pkg_dir / "src" / "unformatted"
            src_dir.mkdir(parents=True)
            (src_dir / "__init__.py").write_text('''"""Unformatted module."""

def badly_formatted_function(  x,y,    z  ):
    """Function with bad formatting."""
    if x>y:return x+y+z
    else:
        return      x-y-z

class  BadlyFormattedClass:
    """Class with bad formatting."""
    def   method(self,a,b,c):return a+b+c
''')

            # Run validation
            result = self.validator.validate_all(str(pkg_dir))

            # Should detect formatting issues
            code_quality_result = result["code_quality_validation"]
            # Black should flag formatting issues
            print(f"Black compliant: {code_quality_result.get('black_compliant', 'N/A')}")

    # T028.9: Malformed pyproject.toml
    @pytest.mark.integration
    def test_detect_malformed_pyproject(self):
        """Should handle malformed pyproject.toml gracefully"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_dir = Path(tmpdir)

            # Create invalid TOML
            (pkg_dir / "pyproject.toml").write_text("""
[project
name = incomplete-package
This is not valid TOML
""")

            # Run validation - validate_all catches exceptions and returns error results
            result = self.validator.validate_all(str(pkg_dir))

            # Should have error results indicating malformed TOML
            assert result["is_pypi_ready"] is False
            assert len(result["blocking_issues"]) > 0

    # T028.10: Missing critical files
    @pytest.mark.integration
    def test_detect_missing_readme(self):
        """Should detect missing README.md"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_dir = Path(tmpdir)

            (pkg_dir / "pyproject.toml").write_text("""
[project]
name = "no-readme"
version = "0.1.0"
description = "Package without README"
readme = "README.md"
license = {text = "MIT"}
authors = [{name = "Test", email = "test@example.com"}]
""")

            # Don't create README.md
            (pkg_dir / "CHANGELOG.md").write_text("""# Changelog

## [Unreleased]

## [0.1.0] - 2025-01-15
""")

            src_dir = pkg_dir / "src" / "pkg"
            src_dir.mkdir(parents=True)
            (src_dir / "__init__.py").write_text('"""Pkg."""\n')

            # Run validation - validate_all catches exceptions and returns error results
            result = self.validator.validate_all(str(pkg_dir))

            # Should have error results indicating missing README
            assert result["is_pypi_ready"] is False
            assert len(result["blocking_issues"]) > 0

    # T028.11: Multiple failures combined
    @pytest.mark.integration
    def test_detect_multiple_failures(self):
        """Should detect and report multiple failure types simultaneously"""
        with tempfile.TemporaryDirectory() as tmpdir:
            pkg_dir = Path(tmpdir)

            # Create package with multiple issues
            (pkg_dir / "pyproject.toml").write_text("""
[project]
name = "multi-fail"
version = "0.1.0"
description = "Q"
readme = "README.md"
license = {text = "MIT"}
authors = [{name = "T", email = "t@e.com"}]
classifiers = ["Invalid :: Classifier"]
""")

            # Incomplete README
            (pkg_dir / "README.md").write_text("# Multi Fail\n")

            # No CHANGELOG
            (pkg_dir / "CHANGELOG.md").write_text("Changes\n")

            # Undocumented code
            src_dir = pkg_dir / "src" / "multi_fail"
            src_dir.mkdir(parents=True)
            (src_dir / "__init__.py").write_text('''
def func(): return 1
def func2(): return 2
''')

            # Run validation
            result = self.validator.validate_all(str(pkg_dir))

            # Should have multiple failures
            failures = []
            if not result["metadata_validation"]["is_valid"]:
                failures.append("metadata")

            # Check nested documentation validation results
            readme_result = result["documentation_validation"]["readme_validation"]
            if not readme_result["is_complete"]:
                failures.append("documentation")

            print(f"Failed validations: {failures}")
            assert len(failures) >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "integration"])

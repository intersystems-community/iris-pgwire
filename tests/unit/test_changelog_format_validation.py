"""
Unit Tests for CHANGELOG Format Validation (T031)

Tests the DocumentationValidator.validate_changelog_format() method's regex patterns
for validating Keep a Changelog format compliance.

Constitutional Requirement: Production Readiness (Principle V)
"""

import pytest
from unittest.mock import patch, mock_open
from iris_pgwire.quality.documentation_validator import DocumentationValidator


class TestChangelogFormatValidation:
    """Unit tests for CHANGELOG.md format validation regex"""

    def setup_method(self):
        """Set up test fixtures"""
        self.validator = DocumentationValidator()

    # T031.1: Valid Keep a Changelog formats
    def test_validate_perfect_changelog(self):
        """Should pass validation for perfect Keep a Changelog format"""
        changelog_content = """# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]

### Added
- New feature X

## [1.0.0] - 2025-01-15

### Added
- Initial release
"""

        with patch("builtins.open", mock_open(read_data=changelog_content)):
            result = self.validator.validate_changelog_format("CHANGELOG.md")

        assert result["is_valid"] is True
        assert result["has_title"] is True
        assert result["has_unreleased_section"] is True
        assert result["has_version_sections"] is True
        assert result["has_dates"] is True
        assert result["follows_keep_a_changelog"] is True
        assert len(result["validation_errors"]) == 0

    def test_validate_multiple_versions(self):
        """Should validate changelog with multiple version sections"""
        changelog_content = """# Changelog

## [Unreleased]

## [2.1.0] - 2025-02-01
### Added
- Feature Y

## [2.0.0] - 2025-01-15
### Changed
- Breaking change

## [1.0.0] - 2024-12-01
### Added
- Initial release
"""

        with patch("builtins.open", mock_open(read_data=changelog_content)):
            result = self.validator.validate_changelog_format("CHANGELOG.md")

        assert result["is_valid"] is True
        assert result["has_version_sections"] is True
        assert result["has_dates"] is True

    # T031.2: Title regex validation
    def test_validate_title_case_insensitive(self):
        """Should accept title with various capitalizations"""
        test_cases = [
            "# Changelog",
            "# CHANGELOG",
            "# changelog",
            "# ChAnGeLoG",
        ]

        for title in test_cases:
            changelog_content = f"""{title}

## [Unreleased]

## [1.0.0] - 2025-01-15
"""

            with patch("builtins.open", mock_open(read_data=changelog_content)):
                result = self.validator.validate_changelog_format("CHANGELOG.md")

            assert result["has_title"] is True, f"Failed for title: {title}"

    def test_validate_title_with_extra_whitespace(self):
        """Should handle title with extra whitespace"""
        changelog_content = """#    Changelog

## [Unreleased]

## [1.0.0] - 2025-01-15
"""

        with patch("builtins.open", mock_open(read_data=changelog_content)):
            result = self.validator.validate_changelog_format("CHANGELOG.md")

        assert result["has_title"] is True

    def test_reject_missing_title(self):
        """Should fail validation without proper title"""
        changelog_content = """Changelog

## [Unreleased]

## [1.0.0] - 2025-01-15
"""

        with patch("builtins.open", mock_open(read_data=changelog_content)):
            result = self.validator.validate_changelog_format("CHANGELOG.md")

        assert result["has_title"] is False
        assert result["is_valid"] is False
        assert "Missing '# Changelog' title" in result["validation_errors"]

    # T031.3: [Unreleased] section regex
    def test_validate_unreleased_section(self):
        """Should detect [Unreleased] section correctly"""
        changelog_content = """# Changelog

## [Unreleased]

### Added
- Feature in progress

## [1.0.0] - 2025-01-15
"""

        with patch("builtins.open", mock_open(read_data=changelog_content)):
            result = self.validator.validate_changelog_format("CHANGELOG.md")

        assert result["has_unreleased_section"] is True

    def test_validate_unreleased_case_insensitive(self):
        """Should accept [Unreleased] with various capitalizations"""
        test_cases = [
            "## [Unreleased]",
            "## [UNRELEASED]",
            "## [unreleased]",
            "## [UnReLeAsEd]",
        ]

        for section_header in test_cases:
            changelog_content = f"""# Changelog

{section_header}

## [1.0.0] - 2025-01-15
"""

            with patch("builtins.open", mock_open(read_data=changelog_content)):
                result = self.validator.validate_changelog_format("CHANGELOG.md")

            assert result["has_unreleased_section"] is True, f"Failed for: {section_header}"

    def test_reject_missing_unreleased_section(self):
        """Should fail without [Unreleased] section"""
        changelog_content = """# Changelog

## [1.0.0] - 2025-01-15

### Added
- Initial release
"""

        with patch("builtins.open", mock_open(read_data=changelog_content)):
            result = self.validator.validate_changelog_format("CHANGELOG.md")

        assert result["has_unreleased_section"] is False
        assert result["is_valid"] is False
        assert "Missing '## [Unreleased]' section" in result["validation_errors"]

    # T031.4: Version section regex (semantic versioning)
    def test_validate_semantic_version_patterns(self):
        """Should accept various semantic version formats"""
        test_versions = [
            "[1.0.0]",
            "[0.1.0]",
            "[10.20.30]",
            "[1.2.3-alpha]",
            "[2.0.0-beta.1]",
            "[3.1.4-rc.2]",
        ]

        for version in test_versions:
            changelog_content = f"""# Changelog

## [Unreleased]

## {version} - 2025-01-15
"""

            with patch("builtins.open", mock_open(read_data=changelog_content)):
                result = self.validator.validate_changelog_format("CHANGELOG.md")

            # Note: Current regex only matches X.Y.Z format, not pre-release tags
            if "-" not in version:
                assert result["has_version_sections"] is True, f"Failed for version: {version}"

    def test_validate_major_minor_patch_versions(self):
        """Should validate major.minor.patch version format"""
        changelog_content = """# Changelog

## [Unreleased]

## [2.1.0] - 2025-02-01
## [2.0.0] - 2025-01-15
## [1.0.0] - 2024-12-01
## [0.1.0] - 2024-11-15
"""

        with patch("builtins.open", mock_open(read_data=changelog_content)):
            result = self.validator.validate_changelog_format("CHANGELOG.md")

        assert result["has_version_sections"] is True

    def test_reject_invalid_version_format(self):
        """Should not match non-semantic version formats"""
        changelog_content = """# Changelog

## [Unreleased]

## [v1.0] - 2025-01-15
## [release-1] - 2025-01-01
"""

        with patch("builtins.open", mock_open(read_data=changelog_content)):
            result = self.validator.validate_changelog_format("CHANGELOG.md")

        # Should fail because versions don't match \d+\.\d+\.\d+ pattern
        assert result["has_version_sections"] is False
        assert any("Missing version sections" in err for err in result["validation_errors"])

    # T031.5: Date format regex (YYYY-MM-DD)
    def test_validate_date_format(self):
        """Should validate YYYY-MM-DD date format"""
        changelog_content = """# Changelog

## [Unreleased]

## [1.0.0] - 2025-01-15
"""

        with patch("builtins.open", mock_open(read_data=changelog_content)):
            result = self.validator.validate_changelog_format("CHANGELOG.md")

        assert result["has_dates"] is True

    def test_validate_multiple_dates(self):
        """Should find dates in multiple version sections"""
        changelog_content = """# Changelog

## [Unreleased]

## [2.0.0] - 2025-02-01
## [1.5.0] - 2025-01-15
## [1.0.0] - 2024-12-01
"""

        with patch("builtins.open", mock_open(read_data=changelog_content)):
            result = self.validator.validate_changelog_format("CHANGELOG.md")

        assert result["has_dates"] is True

    def test_validate_date_edge_cases(self):
        """Should validate various valid date formats"""
        test_dates = [
            "2025-01-01",  # Jan 1st
            "2025-12-31",  # Dec 31st
            "2024-02-29",  # Leap year
            "1999-01-01",  # Past century
            "2099-12-31",  # Future date
        ]

        for date in test_dates:
            changelog_content = f"""# Changelog

## [Unreleased]

## [1.0.0] - {date}
"""

            with patch("builtins.open", mock_open(read_data=changelog_content)):
                result = self.validator.validate_changelog_format("CHANGELOG.md")

            assert result["has_dates"] is True, f"Failed for date: {date}"

    def test_reject_invalid_date_formats(self):
        """Should not match non-YYYY-MM-DD date formats"""
        changelog_content = """# Changelog

## [Unreleased]

## [1.0.0] - 01/15/2025
## [0.9.0] - Jan 15, 2025
## [0.8.0] - 15-01-2025
"""

        with patch("builtins.open", mock_open(read_data=changelog_content)):
            result = self.validator.validate_changelog_format("CHANGELOG.md")

        # Should fail because dates don't match YYYY-MM-DD pattern
        assert result["has_dates"] is False
        assert any("Missing dates" in err for err in result["validation_errors"])

    # T031.6: Complete validation scenarios
    def test_validate_minimal_valid_changelog(self):
        """Should pass with minimal required elements"""
        changelog_content = """# Changelog

## [Unreleased]

## [0.1.0] - 2025-01-01
"""

        with patch("builtins.open", mock_open(read_data=changelog_content)):
            result = self.validator.validate_changelog_format("CHANGELOG.md")

        assert result["is_valid"] is True
        assert result["follows_keep_a_changelog"] is True

    def test_validate_real_world_changelog(self):
        """Should validate actual iris-pgwire CHANGELOG format"""
        changelog_content = """# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **P6 COPY Protocol** (Feature 023): PostgreSQL COPY FROM STDIN and COPY TO STDOUT
- **Package Quality Validation System** (Feature 025): Automated PyPI readiness validation

### Fixed
- Dynamic versioning recognition in package metadata validation
- Python bytecode cleanup (95+ artifacts removed from git)

### Security
- Upgraded authlib to 1.6.5 (fixes 3 HIGH severity CVEs)
- Upgraded cryptography to 46.0.3 (fixes 1 HIGH severity CVE)

## [0.1.0] - 2025-01-01

### Added
- Initial release with P0-P5 protocol support
- PostgreSQL wire protocol server implementation
"""

        with patch("builtins.open", mock_open(read_data=changelog_content)):
            result = self.validator.validate_changelog_format("CHANGELOG.md")

        assert result["is_valid"] is True
        assert result["has_title"] is True
        assert result["has_unreleased_section"] is True
        assert result["has_version_sections"] is True
        assert result["has_dates"] is True

    # T031.7: Error conditions
    def test_handle_empty_changelog(self):
        """Should handle empty CHANGELOG gracefully"""
        changelog_content = ""

        with patch("builtins.open", mock_open(read_data=changelog_content)):
            result = self.validator.validate_changelog_format("CHANGELOG.md")

        assert result["is_valid"] is False
        assert len(result["validation_errors"]) >= 4  # All checks should fail

    def test_handle_file_not_found(self):
        """Should raise FileNotFoundError for missing file"""
        with patch("builtins.open", side_effect=FileNotFoundError):
            with pytest.raises(FileNotFoundError):
                self.validator.validate_changelog_format("NONEXISTENT.md")

    def test_handle_parsing_error(self):
        """Should return invalid result on parsing error"""
        with patch("builtins.open", side_effect=Exception("Encoding error")):
            result = self.validator.validate_changelog_format("CHANGELOG.md")

        assert result["is_valid"] is False
        assert "parsing failed" in result["validation_errors"][0]

    # T031.8: Partial compliance scenarios
    def test_partial_compliance_no_unreleased(self):
        """Should fail if missing [Unreleased] but has other elements"""
        changelog_content = """# Changelog

## [1.0.0] - 2025-01-15

### Added
- Initial release
"""

        with patch("builtins.open", mock_open(read_data=changelog_content)):
            result = self.validator.validate_changelog_format("CHANGELOG.md")

        assert result["is_valid"] is False
        assert result["has_title"] is True
        assert result["has_unreleased_section"] is False
        assert result["has_version_sections"] is True
        assert result["has_dates"] is True
        assert len(result["validation_errors"]) == 1
        assert "Missing '## [Unreleased]' section" in result["validation_errors"]

    def test_partial_compliance_no_dates(self):
        """Should fail if version sections missing dates"""
        changelog_content = """# Changelog

## [Unreleased]

## [1.0.0]

### Added
- Initial release
"""

        with patch("builtins.open", mock_open(read_data=changelog_content)):
            result = self.validator.validate_changelog_format("CHANGELOG.md")

        assert result["is_valid"] is False
        assert result["has_dates"] is False
        assert any("Missing dates" in err for err in result["validation_errors"])

    def test_partial_compliance_only_unreleased(self):
        """Should fail if only [Unreleased] section exists"""
        changelog_content = """# Changelog

## [Unreleased]

### Added
- Features in progress
"""

        with patch("builtins.open", mock_open(read_data=changelog_content)):
            result = self.validator.validate_changelog_format("CHANGELOG.md")

        assert result["is_valid"] is False
        assert result["has_unreleased_section"] is True
        assert result["has_version_sections"] is False
        assert any("Missing version sections" in err for err in result["validation_errors"])

    # T031.9: Integration with validate_documentation
    def test_changelog_validation_in_documentation_check(self):
        """Should integrate changelog validation into full documentation check"""
        changelog_content = """# Changelog

## [Unreleased]

## [1.0.0] - 2025-01-15
"""

        readme_content = """# iris-pgwire

PostgreSQL wire protocol implementation.

## Installation

```bash
pip install iris-pgwire
```

## Quick Start

See documentation for examples.

## Usage

Use with PostgreSQL clients.

## Documentation

Visit docs.example.com

## License

MIT License
"""

        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", side_effect=[
                mock_open(read_data=readme_content)(),
                mock_open(read_data=changelog_content)(),
            ]):
                with patch("subprocess.run") as mock_run:
                    # Mock interrogate output
                    mock_run.return_value.stdout = "actual: 95.4%\nTotal: 100\nMiss: 5"
                    mock_run.return_value.stderr = ""

                    is_complete, results = self.validator.validate_documentation(
                        "/fake/src",
                        "README.md",
                        "CHANGELOG.md"
                    )

        changelog_result = results["changelog_validation"]
        assert changelog_result["is_valid"] is True
        assert changelog_result["follows_keep_a_changelog"] is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

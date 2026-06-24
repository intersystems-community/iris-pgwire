"""
Unit Tests for DocumentationValidator

Targets branches missed in the 76% coverage baseline:
- validate_documentation path-existence checks (lines 81-85)
- check_docstring_coverage: fallback parsing, timeout, FileNotFoundError, generic exception
- validate_readme_structure: all section flags and warnings
- generate_docstring_badge: badge created, timeout, missing interrogate, generic exception
- get_documentation_report: full report rendering paths

Constitutional Requirement: Production Readiness (Principle V)
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from iris_pgwire.quality.documentation_validator import DocumentationValidator


class TestValidateDocumentationPathChecks:
    """Tests for validate_documentation path-existence guards (lines 79-85)."""

    def setup_method(self):
        self.validator = DocumentationValidator()

    def test_missing_source_path_raises(self):
        """FileNotFoundError when source_path does not exist."""
        with patch.object(Path, "exists", return_value=False):
            with pytest.raises(FileNotFoundError, match="Source path does not exist"):
                self.validator.validate_documentation(
                    "/no/such/src", "README.md", "CHANGELOG.md"
                )

    def test_missing_readme_path_raises(self):
        """FileNotFoundError when readme_path does not exist."""

        def exists_side_effect(self_path):
            return str(self_path) != "README.md"

        with patch.object(Path, "exists", exists_side_effect):
            with pytest.raises(FileNotFoundError, match="README path does not exist"):
                self.validator.validate_documentation(
                    "/some/src", "README.md", "CHANGELOG.md"
                )

    def test_missing_changelog_path_raises(self):
        """FileNotFoundError when changelog_path does not exist."""
        call_count = [0]

        def exists_side_effect(self_path):
            call_count[0] += 1
            # First two paths exist, third does not
            return call_count[0] <= 2

        with patch.object(Path, "exists", exists_side_effect):
            with pytest.raises(FileNotFoundError, match="CHANGELOG path does not exist"):
                self.validator.validate_documentation(
                    "/some/src", "README.md", "CHANGELOG.md"
                )

    def test_all_paths_exist_returns_results(self):
        """When all paths exist, returns (bool, dict) with three keys."""
        with patch.object(Path, "exists", return_value=True):
            with patch.object(
                self.validator, "check_docstring_coverage"
            ) as mock_cov, patch.object(
                self.validator, "validate_readme_structure"
            ) as mock_readme, patch.object(
                self.validator, "validate_changelog_format"
            ) as mock_cl:
                mock_cov.return_value = {
                    "coverage_percentage": 90.0,
                    "total_items": 10,
                    "documented_items": 9,
                    "missing_docstrings": [],
                    "is_compliant": True,
                }
                mock_readme.return_value = {
                    "is_complete": True,
                    "has_title": True,
                    "has_description": True,
                    "has_installation": True,
                    "has_quick_start": True,
                    "has_usage_examples": True,
                    "has_documentation_links": True,
                    "has_license": True,
                    "missing_sections": [],
                    "warnings": [],
                }
                mock_cl.return_value = {
                    "is_valid": True,
                    "has_title": True,
                    "has_unreleased_section": True,
                    "has_version_sections": True,
                    "has_dates": True,
                    "follows_keep_a_changelog": True,
                    "validation_errors": [],
                }
                is_complete, results = self.validator.validate_documentation(
                    "/src", "README.md", "CHANGELOG.md"
                )

        assert is_complete is True
        assert "docstring_coverage" in results
        assert "readme_validation" in results
        assert "changelog_validation" in results

    def test_overall_false_when_any_check_fails(self):
        """is_complete is False when any sub-check fails."""
        with patch.object(Path, "exists", return_value=True):
            with patch.object(
                self.validator, "check_docstring_coverage"
            ) as mock_cov, patch.object(
                self.validator, "validate_readme_structure"
            ) as mock_readme, patch.object(
                self.validator, "validate_changelog_format"
            ) as mock_cl:
                mock_cov.return_value = {"is_compliant": False}
                mock_readme.return_value = {"is_complete": True}
                mock_cl.return_value = {"is_valid": True}
                is_complete, _ = self.validator.validate_documentation(
                    "/src", "README.md", "CHANGELOG.md"
                )

        assert is_complete is False


class TestCheckDocstringCoverage:
    """Tests for check_docstring_coverage (lines 117-213)."""

    def setup_method(self):
        self.validator = DocumentationValidator()

    def _make_run_result(self, stdout: str, stderr: str = "", returncode: int = 0):
        result = MagicMock()
        result.stdout = stdout
        result.stderr = stderr
        result.returncode = returncode
        return result

    def test_parses_actual_percentage_from_result_line(self):
        """Extracts coverage from 'actual: X%' format."""
        output = "RESULT: PASSED (minimum: 80.0%, actual: 92.3%)\nTotal: 50\nMiss: 4"
        with patch("subprocess.run", return_value=self._make_run_result(stdout=output)):
            result = self.validator.check_docstring_coverage("/src")

        assert result["coverage_percentage"] == 92.3
        assert result["is_compliant"] is True

    def test_fallback_to_table_percentage(self):
        """Falls back to table format when 'actual:' not present (line 135-138)."""
        # Table row: | path | 123 | 45 | 63.4% |
        output = "| src/iris_pgwire/ | 123 | 45 | 63.4% |\n"
        with patch("subprocess.run", return_value=self._make_run_result(stdout=output)):
            result = self.validator.check_docstring_coverage("/src")

        assert result["coverage_percentage"] == 63.4
        assert result["is_compliant"] is False  # < 80%

    def test_zero_coverage_when_no_pattern_matches(self):
        """Returns 0.0 when neither pattern matches (line 139)."""
        output = "Some unrecognized interrogate output\n"
        with patch("subprocess.run", return_value=self._make_run_result(stdout=output)):
            result = self.validator.check_docstring_coverage("/src")

        assert result["coverage_percentage"] == 0.0
        assert result["is_compliant"] is False

    def test_parses_total_and_missing_counts(self):
        """Parses Total / Missing counts correctly (lines 143-149)."""
        output = "actual: 80.0%\nTotal: 100\nMissing: 20"
        with patch("subprocess.run", return_value=self._make_run_result(stdout=output)):
            result = self.validator.check_docstring_coverage("/src")

        assert result["total_items"] == 100
        assert result["documented_items"] == 80

    def test_estimates_counts_from_percentage(self):
        """Falls back to estimated counts when Total/Missing not parsed (lines 152-158)."""
        output = "actual: 75.0%\n"  # No Total/Miss lines
        with patch("subprocess.run", return_value=self._make_run_result(stdout=output)):
            result = self.validator.check_docstring_coverage("/src")

        assert result["total_items"] == 100
        assert result["documented_items"] == 75

    def test_zero_counts_when_no_coverage_and_no_counts(self):
        """Zero items when both coverage and count parsing fail (lines 156-158)."""
        output = "unrecognized\n"
        with patch("subprocess.run", return_value=self._make_run_result(stdout=output)):
            result = self.validator.check_docstring_coverage("/src")

        assert result["total_items"] == 0
        assert result["documented_items"] == 0

    def test_extracts_missed_files_from_output(self):
        """Parses MISSED file paths from interrogate table output (lines 163-177)."""
        output = (
            "actual: 90.0%\nTotal: 10\nMiss: 1\n"
            "| src/iris_pgwire/foo.py (module) | MISSED |\n"
            "| src/iris_pgwire/bar.py (module) | MISSED |\n"
        )
        with patch("subprocess.run", return_value=self._make_run_result(stdout=output)):
            result = self.validator.check_docstring_coverage("/src")

        assert any("foo.py" in f for f in result["missing_docstrings"])
        assert any("bar.py" in f for f in result["missing_docstrings"])

    def test_deduplicates_missed_files(self):
        """Same file appearing twice is only listed once."""
        output = (
            "actual: 90.0%\nTotal: 10\nMiss: 1\n"
            "| src/iris_pgwire/foo.py (module) | MISSED |\n"
            "| src/iris_pgwire/foo.py (module) | MISSED |\n"
        )
        with patch("subprocess.run", return_value=self._make_run_result(stdout=output)):
            result = self.validator.check_docstring_coverage("/src")

        foo_entries = [f for f in result["missing_docstrings"] if "foo.py" in f]
        assert len(foo_entries) == 1

    def test_timeout_returns_safe_result(self):
        """TimeoutExpired returns non-compliant result with descriptive message (line 190-197)."""
        with patch(
            "subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="interrogate", timeout=60)
        ):
            result = self.validator.check_docstring_coverage("/src")

        assert result["coverage_percentage"] == 0.0
        assert result["is_compliant"] is False
        assert any("timed out" in m for m in result["missing_docstrings"])

    def test_file_not_found_returns_safe_result(self):
        """FileNotFoundError (interrogate not installed) returns non-compliant result (lines 198-205)."""
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            result = self.validator.check_docstring_coverage("/src")

        assert result["coverage_percentage"] == 0.0
        assert result["is_compliant"] is False
        assert any("not installed" in m for m in result["missing_docstrings"])

    def test_generic_exception_returns_safe_result(self):
        """Any other exception returns non-compliant result (lines 206-213)."""
        with patch("subprocess.run", side_effect=RuntimeError("unexpected error")):
            result = self.validator.check_docstring_coverage("/src")

        assert result["coverage_percentage"] == 0.0
        assert result["is_compliant"] is False
        assert any("failed" in m for m in result["missing_docstrings"])


class TestValidateReadmeStructure:
    """Tests for validate_readme_structure (lines 215-309)."""

    def setup_method(self):
        self.validator = DocumentationValidator()

    def _validate(self, content: str):
        with patch("builtins.open", mock_open(read_data=content)):
            return self.validator.validate_readme_structure("README.md")

    def test_full_readme_is_complete(self):
        """Complete README passes all section checks."""
        content = """# My Project

A great project.

## Installation

pip install myproject

## Quick Start

Getting started quickly is easy.

## Usage

Usage examples here.

## Documentation

https://docs.example.com

## License

MIT License
"""
        result = self._validate(content)
        assert result["is_complete"] is True
        assert result["has_title"] is True
        assert result["has_installation"] is True
        assert result["has_quick_start"] is True
        assert result["has_usage_examples"] is True
        assert result["has_documentation_links"] is True
        assert result["has_license"] is True
        assert result["missing_sections"] == []

    def test_missing_title(self):
        """No H1 title marks has_title=False and adds to missing_sections."""
        content = (
            "pip install x\nGetting started\nUsage examples\ndocumentation https://docs.example.com\nlicense"
        )
        result = self._validate(content)
        assert result["has_title"] is False
        assert "Title" in result["missing_sections"]

    def test_missing_installation(self):
        """Missing install section adds 'Installation' to missing_sections."""
        content = "# Project\nSome description\nQuick Start\nUsage\nDocs https://x.com\nLicense"
        result = self._validate(content)
        assert result["has_installation"] is False
        assert "Installation" in result["missing_sections"]

    def test_setup_py_satisfies_installation(self):
        """'setup.py' in content satisfies installation check."""
        content = "# Project\ninstall via setup.py\nquick start\nusage\ndocs https://x.com\nlicense"
        result = self._validate(content)
        assert result["has_installation"] is True

    def test_getting_started_satisfies_quick_start(self):
        """'getting started' satisfies the quick_start check."""
        content = (
            "# Proj\npip install x\ngetting started is easy\nusage\ndocs https://x.com\nlicense"
        )
        result = self._validate(content)
        assert result["has_quick_start"] is True

    def test_quickstart_satisfies_quick_start(self):
        """'quickstart' satisfies the quick_start check."""
        content = "# Proj\npip install x\nquickstart\nusage\ndocs https://x.com\nlicense"
        result = self._validate(content)
        assert result["has_quick_start"] is True

    def test_missing_quick_start(self):
        """Missing quick start section adds to missing_sections."""
        content = "# Proj\npip install x\nusage examples\ndocs https://x.com\nlicense"
        result = self._validate(content)
        assert result["has_quick_start"] is False
        assert "Quick Start" in result["missing_sections"]

    def test_example_satisfies_usage(self):
        """'example' satisfies usage_examples check."""
        content = "# Proj\npip install x\nquick start\nexample code here\ndocumentation https://x.com\nlicense"
        result = self._validate(content)
        assert result["has_usage_examples"] is True

    def test_missing_usage(self):
        """Missing usage section adds to missing_sections."""
        content = "# Proj\npip install x\nquick start\ndocumentation https://x.com\nlicense"
        result = self._validate(content)
        assert result["has_usage_examples"] is False
        assert "Usage Examples" in result["missing_sections"]

    def test_docs_with_https_satisfies_doc_links(self):
        """'docs' + 'https://' satisfies documentation_links."""
        content = "# Proj\npip install x\nquick start\nusage\ndocs: https://x.com\nlicense"
        result = self._validate(content)
        assert result["has_documentation_links"] is True

    def test_documentation_keyword_satisfies_doc_links(self):
        """'documentation' keyword alone satisfies documentation_links."""
        content = "# Proj\npip install x\nquick start\nusage\ndocumentation section\nlicense"
        result = self._validate(content)
        assert result["has_documentation_links"] is True

    def test_missing_documentation_links(self):
        """Missing docs adds to missing_sections."""
        content = "# Proj\npip install x\nquick start\nusage examples\nlicense"
        result = self._validate(content)
        assert result["has_documentation_links"] is False
        assert "Documentation Links" in result["missing_sections"]

    def test_missing_license(self):
        """Missing license adds to missing_sections."""
        content = "# Proj\npip install x\nquick start\nusage examples\ndocumentation https://x.com"
        result = self._validate(content)
        assert result["has_license"] is False
        assert "License" in result["missing_sections"]

    def test_short_readme_triggers_warning(self):
        """README under 500 chars triggers a warning (line 278-279)."""
        # has_description is False when len < 100
        content = "# P\npip install x\nquick start\nusage\ndocumentation https://x.com\nlicense"
        result = self._validate(content)
        assert len(result["warnings"]) >= 1

    def test_long_readme_no_length_warning(self):
        """README over 500 chars with description does not trigger the short-README warning."""
        padding = "A" * 500
        content = f"# Project\n{padding}\npip install x\nquick start\nusage\ndocumentation https://x.com\nlicense"
        result = self._validate(content)
        # No "very short" warning
        assert not any("very short" in w for w in result["warnings"])

    def test_file_not_found_re_raises(self):
        """FileNotFoundError propagates (line 294-295)."""
        with patch("builtins.open", side_effect=FileNotFoundError):
            with pytest.raises(FileNotFoundError):
                self.validator.validate_readme_structure("README.md")

    def test_generic_exception_returns_incomplete_result(self):
        """Generic exception returns incomplete result dict (lines 296-309)."""
        with patch("builtins.open", side_effect=Exception("decode error")):
            result = self.validator.validate_readme_structure("README.md")

        assert result["is_complete"] is False
        assert any("parsing failed" in w for w in result["warnings"])


class TestGenerateDocstringBadge:
    """Tests for generate_docstring_badge (lines 380-412)."""

    def setup_method(self):
        self.validator = DocumentationValidator()

    def test_badge_created_returns_markdown(self):
        """When badge file exists after run, returns markdown img tag (lines 401-403)."""
        mock_result = MagicMock()
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result), patch(
            "pathlib.Path.exists", return_value=True
        ):
            badge = self.validator.generate_docstring_badge("/src", "/output/badge.svg")

        assert "![Docstring Coverage]" in badge
        assert "/output/badge.svg" in badge

    def test_badge_not_created_returns_comment(self):
        """When badge file not created, returns HTML comment (lines 404-405)."""
        mock_result = MagicMock()
        mock_result.stderr = "some error"
        with patch("subprocess.run", return_value=mock_result), patch(
            "pathlib.Path.exists", return_value=False
        ):
            badge = self.validator.generate_docstring_badge("/src", "/output/badge.svg")

        assert "<!--" in badge
        assert "failed" in badge.lower() or "Badge" in badge

    def test_timeout_returns_comment(self):
        """TimeoutExpired returns HTML comment (lines 407-408)."""
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="interrogate", timeout=60),
        ):
            badge = self.validator.generate_docstring_badge("/src", "/output/badge.svg")

        assert "timed out" in badge

    def test_file_not_found_returns_comment(self):
        """FileNotFoundError returns 'not installed' comment (lines 409-410)."""
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            badge = self.validator.generate_docstring_badge("/src", "/output/badge.svg")

        assert "not installed" in badge

    def test_generic_exception_returns_comment(self):
        """Generic exception returns failure comment (lines 411-412)."""
        with patch("subprocess.run", side_effect=RuntimeError("boom")):
            badge = self.validator.generate_docstring_badge("/src", "/output/badge.svg")

        assert "failed" in badge.lower() or "<!--" in badge


class TestGetDocumentationReport:
    """Tests for get_documentation_report (lines 414-543)."""

    def setup_method(self):
        self.validator = DocumentationValidator()

    def _mock_validate(
        self,
        cov_compliant=True,
        cov_pct=95.0,
        readme_complete=True,
        cl_valid=True,
        missing_docstrings=None,
        readme_missing=None,
        cl_errors=None,
        warnings=None,
    ):
        """Helper: patch validate_documentation to return controlled results."""
        cov = {
            "coverage_percentage": cov_pct,
            "total_items": 100,
            "documented_items": int(cov_pct),
            "missing_docstrings": missing_docstrings or [],
            "is_compliant": cov_compliant,
        }
        readme = {
            "is_complete": readme_complete,
            "has_title": readme_complete,
            "has_description": readme_complete,
            "has_installation": readme_complete,
            "has_quick_start": readme_complete,
            "has_usage_examples": readme_complete,
            "has_documentation_links": readme_complete,
            "has_license": readme_complete,
            "missing_sections": readme_missing or [],
            "warnings": warnings or [],
        }
        cl = {
            "is_valid": cl_valid,
            "has_title": cl_valid,
            "has_unreleased_section": cl_valid,
            "has_version_sections": cl_valid,
            "has_dates": cl_valid,
            "follows_keep_a_changelog": cl_valid,
            "validation_errors": cl_errors or [],
        }
        is_complete = cov_compliant and readme_complete and cl_valid
        return is_complete, {
            "docstring_coverage": cov,
            "readme_validation": readme,
            "changelog_validation": cl,
        }

    def test_report_complete_status(self):
        """Report contains COMPLETE when all checks pass."""
        with patch.object(self.validator, "validate_documentation") as m:
            m.return_value = self._mock_validate()
            report = self.validator.get_documentation_report("/src", "README.md", "CHANGELOG.md")

        assert "COMPLETE" in report

    def test_report_incomplete_status(self):
        """Report contains INCOMPLETE when any check fails."""
        with patch.object(self.validator, "validate_documentation") as m:
            m.return_value = self._mock_validate(cov_compliant=False, cov_pct=70.0)
            report = self.validator.get_documentation_report("/src", "README.md", "CHANGELOG.md")

        assert "INCOMPLETE" in report

    def test_report_below_target_warning(self):
        """Non-compliant docstring coverage shows below-target warning (lines 454-455)."""
        with patch.object(self.validator, "validate_documentation") as m:
            m.return_value = self._mock_validate(cov_compliant=False, cov_pct=70.0)
            report = self.validator.get_documentation_report("/src", "README.md", "CHANGELOG.md")

        assert "Below target" in report or "below target" in report.lower()

    def test_report_lists_missing_docstrings(self):
        """Missing docstring files appear in report (lines 457-463)."""
        missing = [f"file_{i}.py" for i in range(5)]
        with patch.object(self.validator, "validate_documentation") as m:
            m.return_value = self._mock_validate(missing_docstrings=missing)
            report = self.validator.get_documentation_report("/src", "README.md", "CHANGELOG.md")

        assert "file_0.py" in report

    def test_report_truncates_long_missing_list(self):
        """More than 10 missing files shows '...and N more' (lines 461-463)."""
        missing = [f"file_{i}.py" for i in range(15)]
        with patch.object(self.validator, "validate_documentation") as m:
            m.return_value = self._mock_validate(missing_docstrings=missing)
            report = self.validator.get_documentation_report("/src", "README.md", "CHANGELOG.md")

        assert "more" in report

    def test_report_shows_readme_missing_sections(self):
        """Missing README sections appear in report (lines 485-488)."""
        with patch.object(self.validator, "validate_documentation") as m:
            m.return_value = self._mock_validate(
                readme_complete=False, readme_missing=["Installation", "License"]
            )
            report = self.validator.get_documentation_report("/src", "README.md", "CHANGELOG.md")

        assert "Installation" in report or "Missing sections" in report

    def test_report_shows_readme_warnings(self):
        """README warnings appear in report (lines 489-493)."""
        with patch.object(self.validator, "validate_documentation") as m:
            m.return_value = self._mock_validate(
                warnings=["README appears to be very short"]
            )
            report = self.validator.get_documentation_report("/src", "README.md", "CHANGELOG.md")

        assert "very short" in report

    def test_report_shows_changelog_errors(self):
        """Changelog validation errors appear in report (lines 516-519)."""
        with patch.object(self.validator, "validate_documentation") as m:
            m.return_value = self._mock_validate(
                cl_valid=False, cl_errors=["Missing '# Changelog' title"]
            )
            report = self.validator.get_documentation_report("/src", "README.md", "CHANGELOG.md")

        assert "Changelog" in report

    def test_recommendations_section_when_incomplete(self):
        """Recommendations section present when overall check fails (line 522)."""
        with patch.object(self.validator, "validate_documentation") as m:
            m.return_value = self._mock_validate(
                cov_compliant=False,
                cov_pct=60.0,
                readme_complete=False,
                readme_missing=["License"],
                cl_valid=False,
                cl_errors=["Missing title"],
            )
            report = self.validator.get_documentation_report("/src", "README.md", "CHANGELOG.md")

        assert "Recommendation" in report

    def test_no_recommendations_when_complete(self):
        """Recommendations section absent when all checks pass (line 522 branch)."""
        with patch.object(self.validator, "validate_documentation") as m:
            m.return_value = self._mock_validate()
            report = self.validator.get_documentation_report("/src", "README.md", "CHANGELOG.md")

        assert "Recommendation" not in report

    def test_report_is_string(self):
        """Return value is a non-empty string."""
        with patch.object(self.validator, "validate_documentation") as m:
            m.return_value = self._mock_validate()
            report = self.validator.get_documentation_report("/src", "README.md", "CHANGELOG.md")

        assert isinstance(report, str)
        assert len(report) > 0

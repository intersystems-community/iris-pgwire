"""
Unit tests for quality/__main__.py (CLI entry point)

Target: ≥85% coverage on __main__.py (currently 0%)

Tests cover:
- main() normal flow: markdown output, JSON output, verbose mode
- exit codes: 0 (ready), 1 (not ready), 2 (error cases)
- FileNotFoundError propagation
- General exception during validation
- --package-root that does not exist (exit 2)
- Validator init failure (exit 2)

All file I/O and PackageQualityValidator are mocked.
"""

import json
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# We import and call main() directly, catching SystemExit
from iris_pgwire.quality.__main__ import main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _good_result(is_ready=True, status="READY", blocking_issues=None, warnings=None):
    """Minimal ComprehensiveValidationResult-like dict."""
    return {
        "is_pypi_ready": is_ready,
        "overall_status": status,
        "blocking_issues": blocking_issues or [],
        "warnings": warnings or [],
        "metadata_validation": {
            "is_valid": True,
            "pyroma_score": 10,
            "pyroma_max_score": 10,
            "missing_fields": [],
            "invalid_classifiers": [],
            "validation_errors": [],
            "warnings": [],
        },
        "code_quality_validation": {
            "is_valid": True,
            "black_passed": True,
            "ruff_passed": True,
            "mypy_passed": True,
            "black_errors": [],
            "ruff_errors": [],
            "mypy_errors": [],
            "files_checked": 10,
            "warnings": [],
        },
        "security_validation": {
            "is_secure": True,
            "code_issues": [],
            "dependency_vulnerabilities": [],
            "critical_count": 0,
            "high_count": 0,
            "medium_count": 0,
            "low_count": 0,
            "warnings": [],
        },
        "documentation_validation": {
            "docstring_coverage": {
                "coverage_percentage": 90.0,
                "total_items": 100,
                "documented_items": 90,
                "missing_docstrings": [],
                "is_compliant": True,
            },
            "readme_validation": {
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
            },
            "changelog_validation": {
                "is_valid": True,
                "has_title": True,
                "has_unreleased_section": True,
                "has_version_sections": True,
                "has_dates": True,
                "follows_keep_a_changelog": True,
                "validation_errors": [],
            },
        },
    }


def _run_main(argv, mock_validator_class, capsys=None):
    """Invoke main() with given sys.argv and return (exit_code, stdout, stderr)."""
    with patch("sys.argv", ["iris_pgwire.quality"] + argv):
        try:
            main()
            exit_code = 0
        except SystemExit as exc:
            exit_code = exc.code
    return exit_code


# ---------------------------------------------------------------------------
# Package root does not exist → exit 2
# ---------------------------------------------------------------------------

class TestPackageRootMissing:

    def test_nonexistent_root_exits_2(self, tmp_path, capsys):
        missing = str(tmp_path / "does_not_exist")
        with patch("sys.argv", ["q", "--package-root", missing]):
            with pytest.raises(SystemExit) as exc:
                main()
        assert exc.value.code == 2

    def test_nonexistent_root_prints_error(self, tmp_path, capsys):
        missing = str(tmp_path / "does_not_exist")
        with patch("sys.argv", ["q", "--package-root", missing]):
            with pytest.raises(SystemExit):
                main()
        captured = capsys.readouterr()
        assert "does not exist" in captured.err


# ---------------------------------------------------------------------------
# Validator init failure → exit 2
# ---------------------------------------------------------------------------

class TestValidatorInitFailure:

    def test_init_exception_exits_2(self, tmp_path, capsys):
        with patch(
            "iris_pgwire.quality.__main__.PackageQualityValidator",
            side_effect=RuntimeError("init boom"),
        ):
            with patch("sys.argv", ["q", "--package-root", str(tmp_path)]):
                with pytest.raises(SystemExit) as exc:
                    main()
        assert exc.value.code == 2


# ---------------------------------------------------------------------------
# Normal flow – markdown output, exit 0
# ---------------------------------------------------------------------------

class TestNormalFlowMarkdown:

    def _make_mock_validator(self, result):
        mv = MagicMock()
        mv.validate_all.return_value = result
        mv.generate_report.return_value = "# Report\nAll good\n"
        return mv

    def test_exit_0_when_ready(self, tmp_path, capsys):
        result = _good_result(is_ready=True, status="READY")
        mv = self._make_mock_validator(result)

        with patch("iris_pgwire.quality.__main__.PackageQualityValidator", return_value=mv):
            with patch("sys.argv", ["q", "--package-root", str(tmp_path)]):
                with pytest.raises(SystemExit) as exc:
                    main()

        assert exc.value.code == 0

    def test_markdown_report_printed(self, tmp_path, capsys):
        result = _good_result(is_ready=True, status="READY")
        mv = self._make_mock_validator(result)

        with patch("iris_pgwire.quality.__main__.PackageQualityValidator", return_value=mv):
            with patch("sys.argv", ["q", "--package-root", str(tmp_path)]):
                with pytest.raises(SystemExit):
                    main()

        captured = capsys.readouterr()
        assert "# Report" in captured.out

    def test_exit_1_when_not_ready(self, tmp_path, capsys):
        result = _good_result(
            is_ready=False, status="FAILED", blocking_issues=["Missing version"]
        )
        mv = self._make_mock_validator(result)

        with patch("iris_pgwire.quality.__main__.PackageQualityValidator", return_value=mv):
            with patch("sys.argv", ["q", "--package-root", str(tmp_path)]):
                with pytest.raises(SystemExit) as exc:
                    main()

        assert exc.value.code == 1


# ---------------------------------------------------------------------------
# JSON output
# ---------------------------------------------------------------------------

class TestJsonOutput:

    def test_json_format_is_valid_json(self, tmp_path, capsys):
        result = _good_result(is_ready=True, status="READY")
        mv = MagicMock()
        mv.validate_all.return_value = result

        with patch("iris_pgwire.quality.__main__.PackageQualityValidator", return_value=mv):
            with patch(
                "sys.argv", ["q", "--package-root", str(tmp_path), "--report-format=json"]
            ):
                with pytest.raises(SystemExit):
                    main()

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["is_pypi_ready"] is True

    def test_json_format_exit_0_when_ready(self, tmp_path):
        result = _good_result(is_ready=True, status="READY")
        mv = MagicMock()
        mv.validate_all.return_value = result

        with patch("iris_pgwire.quality.__main__.PackageQualityValidator", return_value=mv):
            with patch(
                "sys.argv", ["q", "--package-root", str(tmp_path), "--report-format=json"]
            ):
                with pytest.raises(SystemExit) as exc:
                    main()

        assert exc.value.code == 0

    def test_json_format_exit_1_when_not_ready(self, tmp_path, capsys):
        result = _good_result(is_ready=False, status="FAILED", blocking_issues=["x"])
        mv = MagicMock()
        mv.validate_all.return_value = result

        with patch("iris_pgwire.quality.__main__.PackageQualityValidator", return_value=mv):
            with patch(
                "sys.argv", ["q", "--package-root", str(tmp_path), "--report-format=json"]
            ):
                with pytest.raises(SystemExit) as exc:
                    main()

        assert exc.value.code == 1


# ---------------------------------------------------------------------------
# Verbose mode
# ---------------------------------------------------------------------------

class TestVerboseMode:

    def test_verbose_prints_package_path(self, tmp_path, capsys):
        result = _good_result(is_ready=True, status="READY")
        mv = MagicMock()
        mv.validate_all.return_value = result
        mv.generate_report.return_value = "# R\n"

        with patch("iris_pgwire.quality.__main__.PackageQualityValidator", return_value=mv):
            with patch(
                "sys.argv", ["q", "--package-root", str(tmp_path), "--verbose"]
            ):
                with pytest.raises(SystemExit):
                    main()

        captured = capsys.readouterr()
        assert "Validating package" in captured.out

    def test_verbose_prints_step_descriptions(self, tmp_path, capsys):
        result = _good_result(is_ready=True, status="READY")
        mv = MagicMock()
        mv.validate_all.return_value = result
        mv.generate_report.return_value = "# R\n"

        with patch("iris_pgwire.quality.__main__.PackageQualityValidator", return_value=mv):
            with patch(
                "sys.argv", ["q", "--package-root", str(tmp_path), "--verbose"]
            ):
                with pytest.raises(SystemExit):
                    main()

        captured = capsys.readouterr()
        assert "Package metadata" in captured.out

    def test_verbose_passed_prints_success(self, tmp_path, capsys):
        result = _good_result(is_ready=True, status="READY")
        mv = MagicMock()
        mv.validate_all.return_value = result
        mv.generate_report.return_value = "# R\n"

        with patch("iris_pgwire.quality.__main__.PackageQualityValidator", return_value=mv):
            with patch(
                "sys.argv", ["q", "--package-root", str(tmp_path), "--verbose"]
            ):
                with pytest.raises(SystemExit):
                    main()

        captured = capsys.readouterr()
        assert "PASSED" in captured.out

    def test_verbose_failed_prints_blocking_issues(self, tmp_path, capsys):
        result = _good_result(
            is_ready=False,
            status="FAILED",
            blocking_issues=["issue A", "issue B"],
        )
        mv = MagicMock()
        mv.validate_all.return_value = result
        mv.generate_report.return_value = "# R\n"

        with patch("iris_pgwire.quality.__main__.PackageQualityValidator", return_value=mv):
            with patch(
                "sys.argv", ["q", "--package-root", str(tmp_path), "--verbose"]
            ):
                with pytest.raises(SystemExit):
                    main()

        captured = capsys.readouterr()
        assert "issue A" in captured.out
        assert "issue B" in captured.out


# ---------------------------------------------------------------------------
# FileNotFoundError during validation → exit 2
# ---------------------------------------------------------------------------

class TestFileNotFoundDuringValidation:

    def test_fnf_error_exits_2(self, tmp_path, capsys):
        mv = MagicMock()
        mv.validate_all.side_effect = FileNotFoundError("no pyproject.toml")

        with patch("iris_pgwire.quality.__main__.PackageQualityValidator", return_value=mv):
            with patch("sys.argv", ["q", "--package-root", str(tmp_path)]):
                with pytest.raises(SystemExit) as exc:
                    main()

        assert exc.value.code == 2

    def test_fnf_error_prints_to_stderr(self, tmp_path, capsys):
        mv = MagicMock()
        mv.validate_all.side_effect = FileNotFoundError("no pyproject.toml")

        with patch("iris_pgwire.quality.__main__.PackageQualityValidator", return_value=mv):
            with patch("sys.argv", ["q", "--package-root", str(tmp_path)]):
                with pytest.raises(SystemExit):
                    main()

        captured = capsys.readouterr()
        assert "Required file not found" in captured.err

    def test_fnf_verbose_prints_hint(self, tmp_path, capsys):
        mv = MagicMock()
        mv.validate_all.side_effect = FileNotFoundError("no pyproject.toml")

        with patch("iris_pgwire.quality.__main__.PackageQualityValidator", return_value=mv):
            with patch("sys.argv", ["q", "--package-root", str(tmp_path), "--verbose"]):
                with pytest.raises(SystemExit):
                    main()

        captured = capsys.readouterr()
        assert "pyproject.toml" in captured.err


# ---------------------------------------------------------------------------
# General exception during validation → exit 2
# ---------------------------------------------------------------------------

class TestGeneralExceptionDuringValidation:

    def test_generic_exception_exits_2(self, tmp_path, capsys):
        mv = MagicMock()
        mv.validate_all.side_effect = RuntimeError("unexpected")

        with patch("iris_pgwire.quality.__main__.PackageQualityValidator", return_value=mv):
            with patch("sys.argv", ["q", "--package-root", str(tmp_path)]):
                with pytest.raises(SystemExit) as exc:
                    main()

        assert exc.value.code == 2

    def test_generic_exception_verbose_prints_traceback(self, tmp_path, capsys):
        mv = MagicMock()
        mv.validate_all.side_effect = RuntimeError("unexpected")

        with patch("iris_pgwire.quality.__main__.PackageQualityValidator", return_value=mv):
            with patch("sys.argv", ["q", "--package-root", str(tmp_path), "--verbose"]):
                with pytest.raises(SystemExit):
                    main()

        # In verbose mode traceback.print_exc() is called — check stderr has something
        captured = capsys.readouterr()
        assert "Error during validation" in captured.err

    def test_generic_exception_prints_to_stderr(self, tmp_path, capsys):
        mv = MagicMock()
        mv.validate_all.side_effect = RuntimeError("unexpected")

        with patch("iris_pgwire.quality.__main__.PackageQualityValidator", return_value=mv):
            with patch("sys.argv", ["q", "--package-root", str(tmp_path)]):
                with pytest.raises(SystemExit):
                    main()

        captured = capsys.readouterr()
        assert "Error during validation" in captured.err


# ---------------------------------------------------------------------------
# Default package root (current directory)
# ---------------------------------------------------------------------------

class TestDefaultPackageRoot:

    def test_default_root_uses_cwd(self, tmp_path, capsys, monkeypatch):
        monkeypatch.chdir(tmp_path)

        result = _good_result(is_ready=True, status="READY")
        mv = MagicMock()
        mv.validate_all.return_value = result
        mv.generate_report.return_value = "# R\n"

        with patch("iris_pgwire.quality.__main__.PackageQualityValidator", return_value=mv):
            with patch("sys.argv", ["q"]):
                with pytest.raises(SystemExit) as exc:
                    main()

        assert exc.value.code == 0
        call_root = mv.validate_all.call_args[0][0]
        assert call_root == str(tmp_path)

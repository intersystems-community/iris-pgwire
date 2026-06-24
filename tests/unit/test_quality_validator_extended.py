"""
Extended unit tests for quality/validator.py (PackageQualityValidator)

Target: ≥85% coverage on validator.py (currently 12%)

Tests cover:
- validate_all(): happy path, all validators failing, partial failures,
  exception paths, default/custom paths, source_paths=None
- generate_report(): READY / WARNINGS / FAILED status + all sections
- check_pypi_readiness(): all return paths

All IRIS / file I/O / subprocess calls are mocked.
"""

from unittest.mock import MagicMock, patch

import pytest

from iris_pgwire.quality.code_quality_validator import CodeQualityValidationResult
from iris_pgwire.quality.documentation_validator import (
    ChangelogValidationResult,
    DocstringCoverageResult,
    ReadmeValidationResult,
)
from iris_pgwire.quality.package_metadata_validator import PackageMetadataValidationResult
from iris_pgwire.quality.security_validator import SecurityValidationResult
from iris_pgwire.quality.validator import ComprehensiveValidationResult, PackageQualityValidator


# ---------------------------------------------------------------------------
# Helpers – pre-built "all good" stubs
# ---------------------------------------------------------------------------

def _good_metadata() -> PackageMetadataValidationResult:
    return PackageMetadataValidationResult(
        is_valid=True,
        pyroma_score=10,
        pyroma_max_score=10,
        missing_fields=[],
        invalid_classifiers=[],
        validation_errors=[],
        warnings=[],
    )


def _good_code_quality() -> CodeQualityValidationResult:
    return CodeQualityValidationResult(
        is_valid=True,
        black_passed=True,
        ruff_passed=True,
        mypy_passed=True,
        black_errors=[],
        ruff_errors=[],
        mypy_errors=[],
        files_checked=42,
        warnings=[],
    )


def _good_security() -> SecurityValidationResult:
    return SecurityValidationResult(
        is_secure=True,
        code_issues=[],
        dependency_vulnerabilities=[],
        critical_count=0,
        high_count=0,
        medium_count=0,
        low_count=0,
        warnings=[],
    )


def _good_docstring_coverage() -> DocstringCoverageResult:
    return DocstringCoverageResult(
        coverage_percentage=95.0,
        total_items=100,
        documented_items=95,
        missing_docstrings=[],
        is_compliant=True,
    )


def _good_readme() -> ReadmeValidationResult:
    return ReadmeValidationResult(
        is_complete=True,
        has_title=True,
        has_description=True,
        has_installation=True,
        has_quick_start=True,
        has_usage_examples=True,
        has_documentation_links=True,
        has_license=True,
        missing_sections=[],
        warnings=[],
    )


def _good_changelog() -> ChangelogValidationResult:
    return ChangelogValidationResult(
        is_valid=True,
        has_title=True,
        has_unreleased_section=True,
        has_version_sections=True,
        has_dates=True,
        follows_keep_a_changelog=True,
        validation_errors=[],
    )


def _good_documentation_results():
    return {
        "docstring_coverage": _good_docstring_coverage(),
        "readme_validation": _good_readme(),
        "changelog_validation": _good_changelog(),
    }


# ---------------------------------------------------------------------------
# Fixtures – patch all four sub-validators on PackageQualityValidator
# ---------------------------------------------------------------------------

def _make_validator_with_mocks(
    metadata=None,
    code_quality=None,
    security=None,
    documentation=None,
):
    """Return a PackageQualityValidator whose sub-validators are all mocked."""
    validator = PackageQualityValidator.__new__(PackageQualityValidator)

    mv = MagicMock()
    mv.validate_metadata.return_value = metadata or _good_metadata()

    cqv = MagicMock()
    cqv.validate_code_quality.return_value = code_quality or _good_code_quality()

    sv = MagicMock()
    sv.validate_security.return_value = security or _good_security()

    dv = MagicMock()
    dv.validate_documentation.return_value = (True, documentation or _good_documentation_results())

    validator.metadata_validator = mv
    validator.code_quality_validator = cqv
    validator.security_validator = sv
    validator.documentation_validator = dv

    return validator


# ---------------------------------------------------------------------------
# PackageQualityValidator.__init__
# ---------------------------------------------------------------------------

class TestPackageQualityValidatorInit:
    """PackageQualityValidator instantiation wires up four sub-validators."""

    def test_init_creates_sub_validators(self):
        from iris_pgwire.quality.code_quality_validator import CodeQualityValidator
        from iris_pgwire.quality.documentation_validator import DocumentationValidator
        from iris_pgwire.quality.package_metadata_validator import PackageMetadataValidator
        from iris_pgwire.quality.security_validator import SecurityValidator

        v = PackageQualityValidator()
        assert isinstance(v.metadata_validator, PackageMetadataValidator)
        assert isinstance(v.code_quality_validator, CodeQualityValidator)
        assert isinstance(v.security_validator, SecurityValidator)
        assert isinstance(v.documentation_validator, DocumentationValidator)


# ---------------------------------------------------------------------------
# validate_all – happy path
# ---------------------------------------------------------------------------

class TestValidateAllHappyPath:
    """All validators pass → READY, no blocking issues."""

    def test_all_pass_returns_ready(self, tmp_path):
        validator = _make_validator_with_mocks()
        result = validator.validate_all(str(tmp_path))

        assert result["is_pypi_ready"] is True
        assert result["overall_status"] == "READY"
        assert result["blocking_issues"] == []
        assert result["warnings"] == []

    def test_all_pass_populates_sub_results(self, tmp_path):
        validator = _make_validator_with_mocks()
        result = validator.validate_all(str(tmp_path))

        assert result["metadata_validation"]["is_valid"] is True
        assert result["code_quality_validation"]["is_valid"] is True
        assert result["security_validation"]["is_secure"] is True

    def test_default_paths_are_derived_from_package_root(self, tmp_path):
        """When paths not supplied, defaults use package_root."""
        validator = _make_validator_with_mocks()
        validator.validate_all(str(tmp_path))

        # metadata_validator.validate_metadata called with pyproject.toml path
        call_args = validator.metadata_validator.validate_metadata.call_args[0][0]
        assert call_args == str(tmp_path / "pyproject.toml")

    def test_custom_paths_are_forwarded(self, tmp_path):
        """Explicitly provided paths are passed straight through."""
        validator = _make_validator_with_mocks()
        validator.validate_all(
            str(tmp_path),
            source_paths=["/custom/src"],
            pyproject_path="/custom/pyproject.toml",
            readme_path="/custom/README.md",
            changelog_path="/custom/CHANGELOG.md",
        )

        validator.metadata_validator.validate_metadata.assert_called_once_with(
            "/custom/pyproject.toml"
        )

    def test_source_paths_none_uses_default(self, tmp_path):
        """source_paths=None falls back to package_root/src."""
        validator = _make_validator_with_mocks()
        validator.validate_all(str(tmp_path), source_paths=None)

        cq_call = validator.code_quality_validator.validate_code_quality.call_args[0][0]
        assert cq_call == [str(tmp_path / "src")]

    def test_ready_with_warnings_status(self, tmp_path):
        """WARNINGS status when passing but sub-validator emits warnings."""
        cq = _good_code_quality()
        cq["warnings"] = ["some warning"]

        validator = _make_validator_with_mocks(code_quality=cq)
        result = validator.validate_all(str(tmp_path))

        assert result["is_pypi_ready"] is True
        assert result["overall_status"] == "WARNINGS"
        assert "some warning" in result["warnings"]


# ---------------------------------------------------------------------------
# validate_all – metadata failures
# ---------------------------------------------------------------------------

class TestValidateAllMetadataFailures:

    def test_invalid_metadata_adds_blocking_issue(self, tmp_path):
        bad_meta = _good_metadata()
        bad_meta["is_valid"] = False
        bad_meta["validation_errors"] = ["Missing version"]

        validator = _make_validator_with_mocks(metadata=bad_meta)
        result = validator.validate_all(str(tmp_path))

        assert result["is_pypi_ready"] is False
        assert result["overall_status"] == "FAILED"
        assert "Package metadata validation failed" in result["blocking_issues"]
        assert "Missing version" in result["blocking_issues"]

    def test_metadata_exception_creates_fallback(self, tmp_path):
        validator = _make_validator_with_mocks()
        validator.metadata_validator.validate_metadata.side_effect = RuntimeError("boom")

        result = validator.validate_all(str(tmp_path))

        assert result["is_pypi_ready"] is False
        assert any("Metadata validation error" in i for i in result["blocking_issues"])
        assert result["metadata_validation"]["is_valid"] is False


# ---------------------------------------------------------------------------
# validate_all – code quality failures
# ---------------------------------------------------------------------------

class TestValidateAllCodeQualityFailures:

    def test_invalid_code_quality_adds_blocking_issue(self, tmp_path):
        bad_cq = _good_code_quality()
        bad_cq["is_valid"] = False
        bad_cq["black_passed"] = False
        bad_cq["ruff_passed"] = False

        validator = _make_validator_with_mocks(code_quality=bad_cq)
        result = validator.validate_all(str(tmp_path))

        assert result["is_pypi_ready"] is False
        assert "Code quality validation failed" in result["blocking_issues"]
        assert "Code formatting issues (black)" in result["blocking_issues"]
        assert "Linting issues (ruff)" in result["blocking_issues"]

    def test_code_quality_exception_creates_fallback(self, tmp_path):
        validator = _make_validator_with_mocks()
        validator.code_quality_validator.validate_code_quality.side_effect = ValueError("bad")

        result = validator.validate_all(str(tmp_path))

        assert result["is_pypi_ready"] is False
        assert any("Code quality validation error" in i for i in result["blocking_issues"])

    def test_black_fail_only_adds_black_issue(self, tmp_path):
        bad_cq = _good_code_quality()
        bad_cq["is_valid"] = False
        bad_cq["black_passed"] = False
        bad_cq["ruff_passed"] = True

        validator = _make_validator_with_mocks(code_quality=bad_cq)
        result = validator.validate_all(str(tmp_path))

        assert "Code formatting issues (black)" in result["blocking_issues"]
        assert "Linting issues (ruff)" not in result["blocking_issues"]

    def test_ruff_fail_only_adds_ruff_issue(self, tmp_path):
        bad_cq = _good_code_quality()
        bad_cq["is_valid"] = False
        bad_cq["black_passed"] = True
        bad_cq["ruff_passed"] = False

        validator = _make_validator_with_mocks(code_quality=bad_cq)
        result = validator.validate_all(str(tmp_path))

        assert "Linting issues (ruff)" in result["blocking_issues"]
        assert "Code formatting issues (black)" not in result["blocking_issues"]


# ---------------------------------------------------------------------------
# validate_all – security failures
# ---------------------------------------------------------------------------

class TestValidateAllSecurityFailures:

    def test_insecure_result_adds_blocking_issue(self, tmp_path):
        bad_sec = _good_security()
        bad_sec["is_secure"] = False
        bad_sec["critical_count"] = 2
        bad_sec["high_count"] = 1

        validator = _make_validator_with_mocks(security=bad_sec)
        result = validator.validate_all(str(tmp_path))

        assert "Security validation failed" in result["blocking_issues"]
        assert "2 CRITICAL vulnerabilities" in result["blocking_issues"]
        assert "1 HIGH vulnerabilities" in result["blocking_issues"]

    def test_security_warnings_propagated(self, tmp_path):
        sec = _good_security()
        sec["warnings"] = ["medium vuln in dep"]

        validator = _make_validator_with_mocks(security=sec)
        result = validator.validate_all(str(tmp_path))

        assert "medium vuln in dep" in result["warnings"]

    def test_security_exception_creates_fallback(self, tmp_path):
        validator = _make_validator_with_mocks()
        validator.security_validator.validate_security.side_effect = OSError("network")

        result = validator.validate_all(str(tmp_path))

        assert any("Security validation error" in i for i in result["blocking_issues"])

    def test_security_uses_first_source_path(self, tmp_path):
        validator = _make_validator_with_mocks()
        validator.validate_all(str(tmp_path), source_paths=["/a/src", "/b/src"])

        call_args = validator.security_validator.validate_security.call_args[0][0]
        assert call_args == "/a/src"

    def test_security_no_source_paths_uses_default(self, tmp_path):
        validator = _make_validator_with_mocks()
        validator.validate_all(str(tmp_path), source_paths=[])

        call_args = validator.security_validator.validate_security.call_args[0][0]
        assert call_args == str(tmp_path / "src")


# ---------------------------------------------------------------------------
# validate_all – documentation failures
# ---------------------------------------------------------------------------

class TestValidateAllDocumentationFailures:

    def test_docs_failure_adds_blocking_issue(self, tmp_path):
        bad_docs = _good_documentation_results()
        bad_docs["docstring_coverage"]["is_compliant"] = False
        bad_docs["docstring_coverage"]["coverage_percentage"] = 50.0

        validator = _make_validator_with_mocks()
        validator.documentation_validator.validate_documentation.return_value = (
            False,
            bad_docs,
        )

        result = validator.validate_all(str(tmp_path))

        assert "Documentation validation failed" in result["blocking_issues"]
        assert any("50.0%" in i for i in result["blocking_issues"])

    def test_readme_incomplete_adds_blocking_issue(self, tmp_path):
        bad_docs = _good_documentation_results()
        bad_docs["readme_validation"]["is_complete"] = False
        bad_docs["readme_validation"]["missing_sections"] = ["Installation", "License"]

        validator = _make_validator_with_mocks()
        validator.documentation_validator.validate_documentation.return_value = (
            False,
            bad_docs,
        )

        result = validator.validate_all(str(tmp_path))

        assert any("Installation" in i for i in result["blocking_issues"])
        assert any("License" in i for i in result["blocking_issues"])

    def test_changelog_invalid_adds_blocking_issue(self, tmp_path):
        bad_docs = _good_documentation_results()
        bad_docs["changelog_validation"]["is_valid"] = False

        validator = _make_validator_with_mocks()
        validator.documentation_validator.validate_documentation.return_value = (
            False,
            bad_docs,
        )

        result = validator.validate_all(str(tmp_path))

        assert "CHANGELOG format invalid" in result["blocking_issues"]

    def test_documentation_exception_creates_fallback(self, tmp_path):
        validator = _make_validator_with_mocks()
        validator.documentation_validator.validate_documentation.side_effect = Exception("fail")

        result = validator.validate_all(str(tmp_path))

        assert any("Documentation validation error" in i for i in result["blocking_issues"])


# ---------------------------------------------------------------------------
# generate_report
# ---------------------------------------------------------------------------

class TestGenerateReport:

    def _make_result(
        self,
        status: str = "READY",
        blocking_issues=None,
        warnings=None,
        metadata=None,
        code_quality=None,
        security=None,
        docs=None,
    ) -> ComprehensiveValidationResult:
        return ComprehensiveValidationResult(
            is_pypi_ready=(status != "FAILED"),
            metadata_validation=metadata or _good_metadata(),
            code_quality_validation=code_quality or _good_code_quality(),
            security_validation=security or _good_security(),
            documentation_validation=docs or _good_documentation_results(),
            overall_status=status,
            blocking_issues=blocking_issues or [],
            warnings=warnings or [],
        )

    def test_ready_status_in_report(self):
        v = PackageQualityValidator.__new__(PackageQualityValidator)
        report = v.generate_report(self._make_result("READY"))
        assert "READY FOR PYPI" in report

    def test_warnings_status_in_report(self):
        v = PackageQualityValidator.__new__(PackageQualityValidator)
        report = v.generate_report(self._make_result("WARNINGS", warnings=["w1"]))
        assert "READY WITH WARNINGS" in report
        assert "w1" in report

    def test_failed_status_in_report(self):
        v = PackageQualityValidator.__new__(PackageQualityValidator)
        report = v.generate_report(self._make_result("FAILED", blocking_issues=["bad thing"]))
        assert "NOT READY" in report
        assert "bad thing" in report

    def test_report_contains_metadata_section(self):
        v = PackageQualityValidator.__new__(PackageQualityValidator)
        report = v.generate_report(self._make_result())
        assert "Package Metadata" in report
        assert "pyroma score" in report

    def test_report_shows_missing_fields(self):
        meta = _good_metadata()
        meta["missing_fields"] = ["keywords"]

        v = PackageQualityValidator.__new__(PackageQualityValidator)
        report = v.generate_report(self._make_result(metadata=meta))
        assert "keywords" in report

    def test_report_shows_invalid_classifiers(self):
        meta = _good_metadata()
        meta["invalid_classifiers"] = ["Bad :: Classifier"]

        v = PackageQualityValidator.__new__(PackageQualityValidator)
        report = v.generate_report(self._make_result(metadata=meta))
        assert "Invalid classifiers" in report

    def test_report_contains_code_quality_section(self):
        v = PackageQualityValidator.__new__(PackageQualityValidator)
        report = v.generate_report(self._make_result())
        assert "Code Quality" in report
        assert "black formatting" in report
        assert "ruff linting" in report
        assert "mypy type checking" in report

    def test_report_contains_security_section(self):
        v = PackageQualityValidator.__new__(PackageQualityValidator)
        report = v.generate_report(self._make_result())
        assert "Security" in report
        assert "Critical vulnerabilities" in report

    def test_report_contains_documentation_section(self):
        v = PackageQualityValidator.__new__(PackageQualityValidator)
        report = v.generate_report(self._make_result())
        assert "Documentation" in report
        assert "Docstring coverage" in report

    def test_report_recommendations_when_not_ready(self):
        v = PackageQualityValidator.__new__(PackageQualityValidator)
        report = v.generate_report(self._make_result("FAILED", blocking_issues=["x"]))
        assert "Recommendations" in report

    def test_report_no_recommendations_when_ready(self):
        v = PackageQualityValidator.__new__(PackageQualityValidator)
        report = v.generate_report(self._make_result("READY"))
        assert "Recommendations" not in report

    def test_report_docs_emoji_is_pass_when_all_good(self):
        v = PackageQualityValidator.__new__(PackageQualityValidator)
        report = v.generate_report(self._make_result())
        # Documentation section header should contain ✅
        doc_section_start = report.find("### ")
        # Find the Documentation header specifically
        assert "✅" in report  # at least one pass indicator


# ---------------------------------------------------------------------------
# check_pypi_readiness
# ---------------------------------------------------------------------------

class TestCheckPypiReadiness:

    def test_returns_true_when_ready(self, tmp_path):
        validator = _make_validator_with_mocks()
        is_ready, msg = validator.check_pypi_readiness(str(tmp_path))
        assert is_ready is True
        assert "READY" in msg

    def test_returns_true_with_warnings_message(self, tmp_path):
        cq = _good_code_quality()
        cq["warnings"] = ["w1", "w2"]

        validator = _make_validator_with_mocks(code_quality=cq)
        is_ready, msg = validator.check_pypi_readiness(str(tmp_path))
        assert is_ready is True
        assert "2 warnings" in msg

    def test_returns_false_when_failed(self, tmp_path):
        bad_meta = _good_metadata()
        bad_meta["is_valid"] = False
        bad_meta["validation_errors"] = ["err1", "err2"]

        validator = _make_validator_with_mocks(metadata=bad_meta)
        is_ready, msg = validator.check_pypi_readiness(str(tmp_path))
        assert is_ready is False
        assert "NOT READY" in msg
        # Should report count of blocking issues
        assert "blocking issues" in msg

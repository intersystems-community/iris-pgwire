"""
Package Quality Validator Orchestrator (T012)

Coordinates all validation checks (metadata, code quality, security, documentation)
and provides comprehensive package quality assessment.

Constitutional Requirement: Production Readiness (Principle V)
"""

from pathlib import Path
from typing import TypedDict

from iris_pgwire.quality.code_quality_validator import (
    CodeQualityValidationResult,
    CodeQualityValidator,
)
from iris_pgwire.quality.documentation_validator import (
    ChangelogValidationResult,
    DocstringCoverageResult,
    DocumentationValidator,
    ReadmeValidationResult,
)
from iris_pgwire.quality.package_metadata_validator import (
    PackageMetadataValidationResult,
    PackageMetadataValidator,
)
from iris_pgwire.quality.security_validator import (
    SecurityValidationResult,
    SecurityValidator,
)


class ComprehensiveValidationResult(TypedDict):
    """Result of comprehensive package validation"""

    is_pypi_ready: bool
    metadata_validation: PackageMetadataValidationResult
    code_quality_validation: CodeQualityValidationResult
    security_validation: SecurityValidationResult
    documentation_validation: (
        dict  # Contains docstring_coverage, readme_validation, changelog_validation
    )
    overall_status: str  # "READY", "FAILED", "WARNINGS"
    blocking_issues: list[str]
    warnings: list[str]


class PackageQualityValidator:
    """
    Orchestrator for comprehensive package quality validation.

    Combines metadata, code quality, security, and documentation validators
    to provide a complete assessment of package readiness for PyPI distribution.
    """

    def __init__(self):
        """Initialize all validators"""
        self.metadata_validator = PackageMetadataValidator()
        self.code_quality_validator = CodeQualityValidator()
        self.security_validator = SecurityValidator()
        self.documentation_validator = DocumentationValidator()

    def validate_all(
        self,
        package_root: str,
        source_paths: list[str] | None = None,
        pyproject_path: str | None = None,
        readme_path: str | None = None,
        changelog_path: str | None = None,
    ) -> ComprehensiveValidationResult:
        """
        Run comprehensive validation across all dimensions.

        Args:
            package_root: Root directory of the package
            source_paths: List of source code paths (default: ["src/"])
            pyproject_path: Path to pyproject.toml (default: package_root/pyproject.toml)
            readme_path: Path to README.md (default: package_root/README.md)
            changelog_path: Path to CHANGELOG.md (default: package_root/CHANGELOG.md)

        Returns:
            ComprehensiveValidationResult with all validation results

        Raises:
            FileNotFoundError: If required files do not exist
        """
        # Set default paths
        package_root_path = Path(package_root)
        if source_paths is None:
            source_paths = [str(package_root_path / "src")]
        if pyproject_path is None:
            pyproject_path = str(package_root_path / "pyproject.toml")
        if readme_path is None:
            readme_path = str(package_root_path / "README.md")
        if changelog_path is None:
            changelog_path = str(package_root_path / "CHANGELOG.md")

        # Run all validators
        blocking_issues = []
        warnings = []

        # 1. Package Metadata Validation
        try:
            metadata_result = self.metadata_validator.validate_metadata(pyproject_path)
            if not metadata_result["is_valid"]:
                blocking_issues.append("Package metadata validation failed")
                blocking_issues.extend(metadata_result["validation_errors"])
        except Exception as e:
            metadata_result = PackageMetadataValidationResult(
                is_valid=False,
                pyroma_score=0,
                pyroma_max_score=10,
                missing_fields=[],
                invalid_classifiers=[],
                validation_errors=[f"Metadata validation error: {e}"],
                warnings=[],
            )
            blocking_issues.append(f"Metadata validation error: {e}")

        # 2. Code Quality Validation
        try:
            code_quality_result = self.code_quality_validator.validate_code_quality(
                source_paths, check_types=True
            )
            if not code_quality_result["is_valid"]:
                blocking_issues.append("Code quality validation failed")
                if not code_quality_result["black_passed"]:
                    blocking_issues.append("Code formatting issues (black)")
                if not code_quality_result["ruff_passed"]:
                    blocking_issues.append("Linting issues (ruff)")
            if code_quality_result["warnings"]:
                warnings.extend(code_quality_result["warnings"])
        except Exception as e:
            code_quality_result = CodeQualityValidationResult(
                is_valid=False,
                black_passed=False,
                ruff_passed=False,
                mypy_passed=False,
                black_errors=[f"Code quality validation error: {e}"],
                ruff_errors=[],
                mypy_errors=[],
                files_checked=0,
                warnings=[],
            )
            blocking_issues.append(f"Code quality validation error: {e}")

        # 3. Security Validation
        try:
            # Use first source path for security scanning
            source_path_for_security = (
                source_paths[0] if source_paths else str(package_root_path / "src")
            )
            security_result = self.security_validator.validate_security(
                source_path_for_security, scan_dependencies=True
            )
            if not security_result["is_secure"]:
                blocking_issues.append("Security validation failed")
                if security_result["critical_count"] > 0:
                    blocking_issues.append(
                        f"{security_result['critical_count']} CRITICAL vulnerabilities"
                    )
                if security_result["high_count"] > 0:
                    blocking_issues.append(f"{security_result['high_count']} HIGH vulnerabilities")
            if security_result["warnings"]:
                warnings.extend(security_result["warnings"])
        except Exception as e:
            security_result = SecurityValidationResult(
                is_secure=False,
                code_issues=[],
                dependency_vulnerabilities=[],
                critical_count=0,
                high_count=0,
                medium_count=0,
                low_count=0,
                warnings=[f"Security validation error: {e}"],
            )
            blocking_issues.append(f"Security validation error: {e}")

        # 4. Documentation Validation
        try:
            source_path_for_docs = (
                source_paths[0] if source_paths else str(package_root_path / "src")
            )
            is_docs_complete, documentation_results = (
                self.documentation_validator.validate_documentation(
                    source_path_for_docs, readme_path, changelog_path
                )
            )
            if not is_docs_complete:
                blocking_issues.append("Documentation validation failed")

                docstring_coverage = documentation_results["docstring_coverage"]
                if not docstring_coverage["is_compliant"]:
                    blocking_issues.append(
                        f"Docstring coverage {docstring_coverage['coverage_percentage']:.1f}% < 80%"
                    )

                readme_validation = documentation_results["readme_validation"]
                if not readme_validation["is_complete"]:
                    missing = ", ".join(readme_validation["missing_sections"])
                    blocking_issues.append(f"README incomplete (missing: {missing})")

                changelog_validation = documentation_results["changelog_validation"]
                if not changelog_validation["is_valid"]:
                    blocking_issues.append("CHANGELOG format invalid")

        except Exception as e:
            documentation_results = {
                "docstring_coverage": DocstringCoverageResult(
                    coverage_percentage=0.0,
                    total_items=0,
                    documented_items=0,
                    missing_docstrings=[],
                    is_compliant=False,
                ),
                "readme_validation": ReadmeValidationResult(
                    is_complete=False,
                    has_title=False,
                    has_description=False,
                    has_installation=False,
                    has_quick_start=False,
                    has_usage_examples=False,
                    has_documentation_links=False,
                    has_license=False,
                    missing_sections=["All sections"],
                    warnings=[f"Documentation validation error: {e}"],
                ),
                "changelog_validation": ChangelogValidationResult(
                    is_valid=False,
                    has_title=False,
                    has_unreleased_section=False,
                    has_version_sections=False,
                    has_dates=False,
                    follows_keep_a_changelog=False,
                    validation_errors=[f"Documentation validation error: {e}"],
                ),
            }
            blocking_issues.append(f"Documentation validation error: {e}")

        # Determine overall status
        is_pypi_ready = len(blocking_issues) == 0
        if is_pypi_ready:
            overall_status = "READY" if len(warnings) == 0 else "WARNINGS"
        else:
            overall_status = "FAILED"

        return ComprehensiveValidationResult(
            is_pypi_ready=is_pypi_ready,
            metadata_validation=metadata_result,
            code_quality_validation=code_quality_result,
            security_validation=security_result,
            documentation_validation=documentation_results,
            overall_status=overall_status,
            blocking_issues=blocking_issues,
            warnings=warnings,
        )

    def generate_report(self, result: ComprehensiveValidationResult) -> str:
        """
        Generate human-readable validation report in Markdown format.

        Args:
            result: ComprehensiveValidationResult from validate_all()

        Returns:
            Markdown-formatted comprehensive validation report
        """
        report = ["# Package Quality Validation Report\n"]

        # Overall Status
        if result["overall_status"] == "READY":
            status_emoji = "✅"
            status_text = "READY FOR PYPI"
        elif result["overall_status"] == "WARNINGS":
            status_emoji = "⚠️"
            status_text = "READY WITH WARNINGS"
        else:
            status_emoji = "❌"
            status_text = "NOT READY"

        report.append(f"## Overall Status: {status_emoji} {status_text}\n\n")

        # Blocking Issues
        if result["blocking_issues"]:
            report.append("## ❌ Blocking Issues\n")
            for issue in result["blocking_issues"]:
                report.append(f"- {issue}\n")
            report.append("\n")

        # Warnings
        if result["warnings"]:
            report.append("## ⚠️ Warnings\n")
            for warning in result["warnings"]:
                report.append(f"- {warning}\n")
            report.append("\n")

        # Section Summaries
        report.append("## Validation Summary\n\n")

        # Metadata
        metadata = result["metadata_validation"]
        metadata_emoji = "✅" if metadata["is_valid"] else "❌"
        report.append(f"### {metadata_emoji} Package Metadata\n")
        report.append(
            f"- **pyroma score**: {metadata['pyroma_score']}/{metadata['pyroma_max_score']}\n"
        )
        if metadata["missing_fields"]:
            report.append(f"- **Missing fields**: {', '.join(metadata['missing_fields'])}\n")
        if metadata["invalid_classifiers"]:
            report.append(f"- **Invalid classifiers**: {len(metadata['invalid_classifiers'])}\n")
        report.append("\n")

        # Code Quality
        code_quality = result["code_quality_validation"]
        code_quality_emoji = "✅" if code_quality["is_valid"] else "❌"
        report.append(f"### {code_quality_emoji} Code Quality\n")
        report.append(
            f"- **black formatting**: {'✅ Pass' if code_quality['black_passed'] else '❌ Fail'}\n"
        )
        report.append(
            f"- **ruff linting**: {'✅ Pass' if code_quality['ruff_passed'] else '❌ Fail'}\n"
        )
        report.append(
            f"- **mypy type checking**: {'✅ Pass' if code_quality['mypy_passed'] else '⚠️ Issues'}\n"
        )
        report.append(f"- **Files checked**: {code_quality['files_checked']}\n")
        report.append("\n")

        # Security
        security = result["security_validation"]
        security_emoji = "✅" if security["is_secure"] else "❌"
        report.append(f"### {security_emoji} Security\n")
        report.append(f"- **Critical vulnerabilities**: {security['critical_count']}\n")
        report.append(f"- **High vulnerabilities**: {security['high_count']}\n")
        report.append(f"- **Medium vulnerabilities**: {security['medium_count']}\n")
        report.append(f"- **Low vulnerabilities**: {security['low_count']}\n")
        report.append("\n")

        # Documentation
        docs = result["documentation_validation"]
        docstring_coverage = docs["docstring_coverage"]
        readme_validation = docs["readme_validation"]
        changelog_validation = docs["changelog_validation"]

        docs_emoji = (
            "✅"
            if (
                docstring_coverage["is_compliant"]
                and readme_validation["is_complete"]
                and changelog_validation["is_valid"]
            )
            else "❌"
        )

        report.append(f"### {docs_emoji} Documentation\n")
        report.append(
            f"- **Docstring coverage**: {docstring_coverage['coverage_percentage']:.1f}% "
        )
        report.append(f"({'✅' if docstring_coverage['is_compliant'] else '❌'} target: ≥80%)\n")
        report.append(
            f"- **README complete**: {'✅' if readme_validation['is_complete'] else '❌'}\n"
        )
        report.append(
            f"- **CHANGELOG valid**: {'✅' if changelog_validation['is_valid'] else '❌'}\n"
        )
        report.append("\n")

        # Recommendations
        if not result["is_pypi_ready"]:
            report.append("## 📋 Recommendations\n")
            report.append("Address blocking issues above before publishing to PyPI.\n")

        return "".join(report)

    def check_pypi_readiness(self, package_root: str) -> tuple[bool, str]:
        """
        Quick check for PyPI readiness with summary message.

        Args:
            package_root: Root directory of the package

        Returns:
            Tuple of (is_ready: bool, summary_message: str)
        """
        result = self.validate_all(package_root)

        if result["is_pypi_ready"]:
            if result["overall_status"] == "READY":
                return (True, "✅ Package is READY for PyPI distribution")
            else:
                warnings_count = len(result["warnings"])
                return (True, f"⚠️ Package is READY for PyPI (with {warnings_count} warnings)")
        else:
            issues_count = len(result["blocking_issues"])
            return (False, f"❌ Package is NOT READY for PyPI ({issues_count} blocking issues)")

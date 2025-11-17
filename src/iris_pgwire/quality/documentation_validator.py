"""
Documentation Validator Implementation (T011)

Validates documentation completeness using industry-standard tools:
- interrogate: Docstring coverage measurement (≥80% target)
- README.md structure validation
- CHANGELOG.md Keep a Changelog format validation

Constitutional Requirement: Production Readiness (Principle V)
"""

import re
import subprocess
from pathlib import Path
from typing import TypedDict


class DocstringCoverageResult(TypedDict):
    """Result of docstring coverage measurement"""

    coverage_percentage: float
    total_items: int
    documented_items: int
    missing_docstrings: list[str]
    is_compliant: bool


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


class DocumentationValidator:
    """
    Validator for documentation completeness and quality.

    Implements contract: specs/025-comprehensive-code-and/contracts/documentation_contract.py
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

        Raises:
            FileNotFoundError: If paths do not exist
        """
        # Validate paths exist
        if not Path(source_path).exists():
            raise FileNotFoundError(f"Source path does not exist: {source_path}")
        if not Path(readme_path).exists():
            raise FileNotFoundError(f"README path does not exist: {readme_path}")
        if not Path(changelog_path).exists():
            raise FileNotFoundError(f"CHANGELOG path does not exist: {changelog_path}")

        # Run all validation checks
        docstring_coverage = self.check_docstring_coverage(source_path)
        readme_validation = self.validate_readme_structure(readme_path)
        changelog_validation = self.validate_changelog_format(changelog_path)

        # Overall pass criteria
        is_complete = (
            docstring_coverage["is_compliant"]
            and readme_validation["is_complete"]
            and changelog_validation["is_valid"]
        )

        validation_results = {
            "docstring_coverage": docstring_coverage,
            "readme_validation": readme_validation,
            "changelog_validation": changelog_validation,
        }

        return (is_complete, validation_results)

    def check_docstring_coverage(self, source_path: str) -> DocstringCoverageResult:
        """
        Measure docstring coverage using interrogate tool.

        Args:
            source_path: Path to source code directory

        Returns:
            DocstringCoverageResult with coverage metrics
        """
        try:
            result = subprocess.run(
                ["interrogate", "-vv", source_path],
                capture_output=True,
                text=True,
                timeout=60,
            )

            output = result.stdout + result.stderr

            # Parse interrogate output for coverage percentage
            # Format: "RESULT: PASSED (minimum: 80.0%, actual: X%)"
            coverage_match = re.search(r"actual:\s*([\d\.]+)%", output)
            if coverage_match:
                coverage_percentage = float(coverage_match.group(1))
            else:
                # Fallback: try to parse from summary table
                # | src/iris_pgwire/ | 123 | 45 | 63.4% |
                table_match = re.search(r"\|\s*[\d]+\s*\|\s*[\d]+\s*\|\s*([\d\.]+)%", output)
                if table_match:
                    coverage_percentage = float(table_match.group(1))
                else:
                    coverage_percentage = 0.0

            # Parse total and documented items
            # Format: "Total: 123, Missing: 45" or from table
            total_match = re.search(r"Total[:\s]+(\d+)", output, re.IGNORECASE)
            missing_match = re.search(r"Miss(?:ing)?[:\s]+(\d+)", output, re.IGNORECASE)

            if total_match and missing_match:
                total_items = int(total_match.group(1))
                missing_items = int(missing_match.group(1))
                documented_items = total_items - missing_items
            else:
                # Calculate from percentage if available
                if coverage_percentage > 0:
                    # Assume 100 items if we can't parse actual numbers
                    total_items = 100
                    documented_items = int(total_items * coverage_percentage / 100)
                else:
                    total_items = 0
                    documented_items = 0

            # Extract files with missing docstrings
            # interrogate outputs lines like: "| undocumented.py (module)                         |                    MISSED |"
            missing_docstrings = []
            for line in output.split("\n"):
                # Look for MISSED status in detailed coverage table
                if "MISSED" in line and ".py" in line:
                    # Extract file path from table row: "| path/file.py (module) | MISSED |"
                    # Strip whitespace and table separators
                    parts = line.split("|")
                    if len(parts) >= 2:
                        # First column after separator contains the file info
                        file_info = parts[1].strip()
                        # Extract just the .py file path (remove "(module)" or "(L123)" annotations)
                        path_match = re.search(r"([\w/\-\.]+\.py)", file_info)
                        if path_match:
                            file_path = path_match.group(1)
                            if file_path not in missing_docstrings:
                                missing_docstrings.append(file_path)

            # Compliance check (≥80%)
            is_compliant = coverage_percentage >= 80.0

            return DocstringCoverageResult(
                coverage_percentage=coverage_percentage,
                total_items=total_items,
                documented_items=documented_items,
                missing_docstrings=missing_docstrings,
                is_compliant=is_compliant,
            )

        except subprocess.TimeoutExpired:
            return DocstringCoverageResult(
                coverage_percentage=0.0,
                total_items=0,
                documented_items=0,
                missing_docstrings=["interrogate timed out"],
                is_compliant=False,
            )
        except FileNotFoundError:
            return DocstringCoverageResult(
                coverage_percentage=0.0,
                total_items=0,
                documented_items=0,
                missing_docstrings=["interrogate not installed"],
                is_compliant=False,
            )
        except Exception as e:
            return DocstringCoverageResult(
                coverage_percentage=0.0,
                total_items=0,
                documented_items=0,
                missing_docstrings=[f"interrogate failed: {e}"],
                is_compliant=False,
            )

    def validate_readme_structure(self, readme_path: str) -> ReadmeValidationResult:
        """
        Validate README.md completeness and structure.

        Args:
            readme_path: Path to README.md file

        Returns:
            ReadmeValidationResult with validation status
        """
        try:
            with open(readme_path, encoding="utf-8") as f:
                content = f.read()

            # Check for required sections (case-insensitive)
            content_lower = content.lower()

            has_title = bool(re.search(r"^#\s+", content, re.MULTILINE))
            has_description = len(content) > 100  # At least some description text

            # Installation section
            has_installation = "install" in content_lower and (
                "pip install" in content_lower or "setup.py" in content_lower
            )

            # Quick Start section
            has_quick_start = (
                "quick start" in content_lower
                or "quickstart" in content_lower
                or "getting started" in content_lower
            )

            # Usage examples
            has_usage_examples = "usage" in content_lower or "example" in content_lower

            # Documentation links
            has_documentation_links = "documentation" in content_lower or (
                "docs" in content_lower and ("http" in content or "https" in content)
            )

            # License
            has_license = "license" in content_lower

            # Collect missing sections
            missing_sections = []
            if not has_title:
                missing_sections.append("Title")
            if not has_installation:
                missing_sections.append("Installation")
            if not has_quick_start:
                missing_sections.append("Quick Start")
            if not has_usage_examples:
                missing_sections.append("Usage Examples")
            if not has_documentation_links:
                missing_sections.append("Documentation Links")
            if not has_license:
                missing_sections.append("License")

            # Overall completeness
            is_complete = len(missing_sections) == 0

            # Warnings
            warnings = []
            if not has_description or len(content) < 500:
                warnings.append("README appears to be very short (consider adding more detail)")

            return ReadmeValidationResult(
                is_complete=is_complete,
                has_title=has_title,
                has_description=has_description,
                has_installation=has_installation,
                has_quick_start=has_quick_start,
                has_usage_examples=has_usage_examples,
                has_documentation_links=has_documentation_links,
                has_license=has_license,
                missing_sections=missing_sections,
                warnings=warnings,
            )

        except FileNotFoundError:
            raise
        except Exception as e:
            # Return incomplete result on parsing error
            return ReadmeValidationResult(
                is_complete=False,
                has_title=False,
                has_description=False,
                has_installation=False,
                has_quick_start=False,
                has_usage_examples=False,
                has_documentation_links=False,
                has_license=False,
                missing_sections=["All sections (parsing error)"],
                warnings=[f"README parsing failed: {e}"],
            )

    def validate_changelog_format(self, changelog_path: str) -> ChangelogValidationResult:
        """
        Validate CHANGELOG.md against Keep a Changelog format.

        Args:
            changelog_path: Path to CHANGELOG.md file

        Returns:
            ChangelogValidationResult with validation status
        """
        try:
            with open(changelog_path, encoding="utf-8") as f:
                content = f.read()

            # Check for required Keep a Changelog format elements
            has_title = bool(re.search(r"^#\s*Changelog", content, re.MULTILINE | re.IGNORECASE))

            # Check for [Unreleased] section
            has_unreleased_section = bool(re.search(r"##\s*\[Unreleased\]", content, re.IGNORECASE))

            # Check for version sections: ## [X.Y.Z]
            has_version_sections = bool(re.search(r"##\s*\[\d+\.\d+\.\d+\]", content))

            # Check for dates in version headers: YYYY-MM-DD
            has_dates = bool(re.search(r"\d{4}-\d{2}-\d{2}", content))

            # Keep a Changelog compliance requires all checks
            follows_keep_a_changelog = (
                has_title and has_unreleased_section and has_version_sections and has_dates
            )

            # Overall validity
            is_valid = follows_keep_a_changelog

            # Collect validation errors
            validation_errors = []
            if not has_title:
                validation_errors.append("Missing '# Changelog' title")
            if not has_unreleased_section:
                validation_errors.append("Missing '## [Unreleased]' section")
            if not has_version_sections:
                validation_errors.append("Missing version sections (e.g., '## [1.0.0]')")
            if not has_dates:
                validation_errors.append("Missing dates in version headers (YYYY-MM-DD format)")

            return ChangelogValidationResult(
                is_valid=is_valid,
                has_title=has_title,
                has_unreleased_section=has_unreleased_section,
                has_version_sections=has_version_sections,
                has_dates=has_dates,
                follows_keep_a_changelog=follows_keep_a_changelog,
                validation_errors=validation_errors,
            )

        except FileNotFoundError:
            raise
        except Exception as e:
            # Return invalid result on parsing error
            return ChangelogValidationResult(
                is_valid=False,
                has_title=False,
                has_unreleased_section=False,
                has_version_sections=False,
                has_dates=False,
                follows_keep_a_changelog=False,
                validation_errors=[f"CHANGELOG parsing failed: {e}"],
            )

    def generate_docstring_badge(self, source_path: str, output_path: str) -> str:
        """
        Generate interrogate badge for README.md.

        Args:
            source_path: Path to source code directory
            output_path: Path to save badge SVG file

        Returns:
            Badge URL for insertion into README.md
        """
        try:
            # Run interrogate with badge generation
            result = subprocess.run(
                ["interrogate", "--generate-badge", output_path, source_path],
                capture_output=True,
                text=True,
                timeout=60,
            )

            # Check if badge was created
            if Path(output_path).exists():
                # Return relative path for README insertion
                return f"![Docstring Coverage]({output_path})"
            else:
                return f"<!-- Badge generation failed: {result.stderr} -->"

        except subprocess.TimeoutExpired:
            return "<!-- Badge generation timed out -->"
        except FileNotFoundError:
            return "<!-- interrogate not installed -->"
        except Exception as e:
            return f"<!-- Badge generation failed: {e} -->"

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
            Markdown-formatted documentation report
        """
        is_complete, results = self.validate_documentation(source_path, readme_path, changelog_path)

        # Extract results
        docstring_coverage = results["docstring_coverage"]
        readme_validation = results["readme_validation"]
        changelog_validation = results["changelog_validation"]

        # Build Markdown report
        report = ["# Documentation Validation Report\n"]

        # Executive Summary
        status_emoji = "✅" if is_complete else "❌"
        report.append(
            f"**Overall Status**: {status_emoji} {'COMPLETE' if is_complete else 'INCOMPLETE'}\n\n"
        )

        # Docstring Coverage
        report.append("## Docstring Coverage\n")
        coverage_emoji = "✅" if docstring_coverage["is_compliant"] else "❌"
        report.append(
            f"{coverage_emoji} **Coverage**: {docstring_coverage['coverage_percentage']:.1f}% "
        )
        report.append(
            f"({docstring_coverage['documented_items']}/{docstring_coverage['total_items']} items)\n"
        )

        if not docstring_coverage["is_compliant"]:
            report.append("\n⚠️ **Below target**: Minimum 80% required\n")

        if docstring_coverage["missing_docstrings"]:
            report.append("\n**Files with missing docstrings**:\n")
            for file_path in docstring_coverage["missing_docstrings"][:10]:
                report.append(f"- `{file_path}`\n")
            if len(docstring_coverage["missing_docstrings"]) > 10:
                remaining = len(docstring_coverage["missing_docstrings"]) - 10
                report.append(f"\n_...and {remaining} more files_\n")

        # README Completeness
        report.append("\n## README.md Completeness\n")
        readme_emoji = "✅" if readme_validation["is_complete"] else "❌"
        report.append(
            f"{readme_emoji} **Status**: {'Complete' if readme_validation['is_complete'] else 'Incomplete'}\n\n"
        )

        report.append("**Section Checklist**:\n")
        report.append(f"- {'✅' if readme_validation['has_title'] else '❌'} Title\n")
        report.append(f"- {'✅' if readme_validation['has_description'] else '❌'} Description\n")
        report.append(f"- {'✅' if readme_validation['has_installation'] else '❌'} Installation\n")
        report.append(f"- {'✅' if readme_validation['has_quick_start'] else '❌'} Quick Start\n")
        report.append(
            f"- {'✅' if readme_validation['has_usage_examples'] else '❌'} Usage Examples\n"
        )
        report.append(
            f"- {'✅' if readme_validation['has_documentation_links'] else '❌'} Documentation Links\n"
        )
        report.append(f"- {'✅' if readme_validation['has_license'] else '❌'} License\n")

        if readme_validation["missing_sections"]:
            report.append(
                f"\n**Missing sections**: {', '.join(readme_validation['missing_sections'])}\n"
            )

        if readme_validation["warnings"]:
            report.append("\n**Warnings**:\n")
            for warning in readme_validation["warnings"]:
                report.append(f"- {warning}\n")

        # CHANGELOG Format
        report.append("\n## CHANGELOG.md Format\n")
        changelog_emoji = "✅" if changelog_validation["is_valid"] else "❌"
        report.append(
            f"{changelog_emoji} **Status**: {'Valid' if changelog_validation['is_valid'] else 'Invalid'}\n\n"
        )

        report.append("**Keep a Changelog Compliance**:\n")
        report.append(
            f"- {'✅' if changelog_validation['has_title'] else '❌'} Has '# Changelog' title\n"
        )
        report.append(
            f"- {'✅' if changelog_validation['has_unreleased_section'] else '❌'} Has '[Unreleased]' section\n"
        )
        report.append(
            f"- {'✅' if changelog_validation['has_version_sections'] else '❌'} Has version sections\n"
        )
        report.append(
            f"- {'✅' if changelog_validation['has_dates'] else '❌'} Has dates (YYYY-MM-DD)\n"
        )

        if changelog_validation["validation_errors"]:
            report.append("\n**Validation Errors**:\n")
            for error in changelog_validation["validation_errors"]:
                report.append(f"- {error}\n")

        # Recommendations
        if not is_complete:
            report.append("\n## Recommendations\n")

            if not docstring_coverage["is_compliant"]:
                report.append("1. **Improve docstring coverage**: Add docstrings to public APIs\n")
                report.append(
                    "   - Run: `interrogate -vv src/iris_pgwire/` to identify missing docstrings\n"
                )
                report.append("   - Focus on public modules, classes, and functions\n")

            if not readme_validation["is_complete"]:
                report.append("2. **Complete README.md**: Add missing sections\n")
                for section in readme_validation["missing_sections"]:
                    report.append(f"   - Add {section} section\n")

            if not changelog_validation["is_valid"]:
                report.append("3. **Fix CHANGELOG.md format**: Follow Keep a Changelog standard\n")
                report.append("   - Reference: https://keepachangelog.com/\n")
                for error in changelog_validation["validation_errors"]:
                    report.append(f"   - Fix: {error}\n")

        return "".join(report)

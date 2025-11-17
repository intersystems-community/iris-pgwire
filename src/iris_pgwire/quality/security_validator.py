"""
Security Validator Implementation (T010)

Validates security using industry-standard tools:
- bandit: Python code security analyzer (40+ checks)
- pip-audit: CVE vulnerability scanner for dependencies

Constitutional Requirement: Production Readiness (Principle V)
"""

import json
import subprocess
from pathlib import Path
from typing import TypedDict


class SecurityIssue(TypedDict):
    """Details of a security issue"""

    severity: str
    confidence: str
    issue_type: str
    file_path: str
    line_number: int
    description: str


class DependencyVulnerability(TypedDict):
    """Details of a dependency vulnerability"""

    package_name: str
    installed_version: str
    vulnerability_id: str
    cvss_score: float
    description: str
    fixed_versions: list[str]


class SecurityValidationResult(TypedDict):
    """Result of security validation"""

    is_secure: bool
    code_issues: list[SecurityIssue]
    dependency_vulnerabilities: list[DependencyVulnerability]
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    warnings: list[str]


class SecurityValidator:
    """
    Validator for security vulnerabilities.

    Implements contract: specs/025-comprehensive-code-and/contracts/security_contract.py
    """

    def validate_security(
        self, source_path: str, scan_dependencies: bool = True
    ) -> SecurityValidationResult:
        """
        Comprehensive security validation (code + dependencies).

        Args:
            source_path: Path to source code directory
            scan_dependencies: Whether to scan dependencies (default: True)

        Returns:
            SecurityValidationResult with security status

        Raises:
            FileNotFoundError: If source_path does not exist
        """
        # Validate path exists
        if not Path(source_path).exists():
            raise FileNotFoundError(f"Path does not exist: {source_path}")

        # Scan code security
        code_secure, code_issues = self.scan_code_security(source_path)

        # Scan dependency vulnerabilities
        dependencies_secure = True
        dependency_vulnerabilities = []
        if scan_dependencies:
            dependencies_secure, dependency_vulnerabilities = self.scan_dependency_vulnerabilities()

        # Count severity levels
        critical_count = 0
        high_count = 0
        medium_count = 0
        low_count = 0

        for issue in code_issues:
            severity = issue["severity"].upper()
            if severity == "CRITICAL":
                critical_count += 1
            elif severity == "HIGH":
                high_count += 1
            elif severity == "MEDIUM":
                medium_count += 1
            elif severity == "LOW":
                low_count += 1

        for vuln in dependency_vulnerabilities:
            cvss = vuln["cvss_score"]
            if cvss >= 9.0:
                critical_count += 1
            elif cvss >= 7.0:
                high_count += 1
            elif cvss >= 4.0:
                medium_count += 1
            else:
                low_count += 1

        # Security passes if no critical/high vulnerabilities
        is_secure = critical_count == 0 and high_count == 0

        # Generate warnings
        warnings = []
        if critical_count > 0:
            warnings.append(f"{critical_count} CRITICAL vulnerabilities found - BLOCKING")
        if high_count > 0:
            warnings.append(f"{high_count} HIGH vulnerabilities found - requires review")
        if medium_count > 0:
            warnings.append(f"{medium_count} MEDIUM vulnerabilities found (informational)")

        return SecurityValidationResult(
            is_secure=is_secure,
            code_issues=code_issues,
            dependency_vulnerabilities=dependency_vulnerabilities,
            critical_count=critical_count,
            high_count=high_count,
            medium_count=medium_count,
            low_count=low_count,
            warnings=warnings,
        )

    def scan_code_security(self, source_path: str) -> tuple[bool, list[SecurityIssue]]:
        """
        Run bandit security scanner on code.

        Args:
            source_path: Path to source code

        Returns:
            Tuple of (no_issues: bool, issues: list[SecurityIssue])
        """
        try:
            result = subprocess.run(
                ["bandit", "-r", source_path, "-f", "json"],
                capture_output=True,
                text=True,
                timeout=120,
            )

            # bandit returns JSON output with -f json
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                # If JSON parsing fails, return error
                return (
                    False,
                    [
                        {
                            "severity": "HIGH",
                            "confidence": "HIGH",
                            "issue_type": "TOOL_ERROR",
                            "file_path": source_path,
                            "line_number": 0,
                            "description": "bandit JSON output parsing failed",
                        }
                    ],
                )

            # Extract issues from bandit JSON
            issues = []
            for result_item in data.get("results", []):
                issues.append(
                    SecurityIssue(
                        severity=result_item.get("issue_severity", "MEDIUM"),
                        confidence=result_item.get("issue_confidence", "MEDIUM"),
                        issue_type=result_item.get("test_id", "UNKNOWN"),
                        file_path=result_item.get("filename", "unknown"),
                        line_number=result_item.get("line_number", 0),
                        description=result_item.get("issue_text", "No description"),
                    )
                )

            no_issues = len(issues) == 0
            return (no_issues, issues)

        except subprocess.TimeoutExpired:
            return (
                False,
                [
                    {
                        "severity": "HIGH",
                        "confidence": "HIGH",
                        "issue_type": "TOOL_ERROR",
                        "file_path": source_path,
                        "line_number": 0,
                        "description": "bandit scan timed out",
                    }
                ],
            )
        except FileNotFoundError:
            return (
                False,
                [
                    {
                        "severity": "HIGH",
                        "confidence": "HIGH",
                        "issue_type": "TOOL_ERROR",
                        "file_path": source_path,
                        "line_number": 0,
                        "description": "bandit not installed",
                    }
                ],
            )
        except Exception as e:
            return (
                False,
                [
                    {
                        "severity": "HIGH",
                        "confidence": "HIGH",
                        "issue_type": "TOOL_ERROR",
                        "file_path": source_path,
                        "line_number": 0,
                        "description": f"bandit scan failed: {e}",
                    }
                ],
            )

    def scan_dependency_vulnerabilities(self) -> tuple[bool, list[DependencyVulnerability]]:
        """
        Run pip-audit to check for dependency CVEs.

        Returns:
            Tuple of (no_vulnerabilities: bool, vulnerabilities: list[DependencyVulnerability])
        """
        try:
            result = subprocess.run(
                ["pip-audit", "--format", "json"],
                capture_output=True,
                text=True,
                timeout=120,
            )

            # pip-audit returns JSON with vulnerability data
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                # If JSON parsing fails, return error
                return (
                    False,
                    [
                        {
                            "package_name": "UNKNOWN",
                            "installed_version": "UNKNOWN",
                            "vulnerability_id": "TOOL_ERROR",
                            "cvss_score": 7.0,
                            "description": "pip-audit JSON parsing failed",
                            "fixed_versions": [],
                        }
                    ],
                )

            # Extract vulnerabilities from pip-audit JSON
            vulnerabilities = []

            # pip-audit JSON structure: {"dependencies": [...]}
            for dep in data.get("dependencies", []):
                package_name = dep.get("name", "unknown")
                installed_version = dep.get("version", "unknown")

                for vuln in dep.get("vulns", []):
                    vulnerabilities.append(
                        DependencyVulnerability(
                            package_name=package_name,
                            installed_version=installed_version,
                            vulnerability_id=vuln.get("id", "UNKNOWN"),
                            cvss_score=float(
                                vuln.get("fix_versions", [{}])[0].get("cvss", {}).get("score", 5.0)
                                if vuln.get("fix_versions")
                                else 5.0
                            ),
                            description=vuln.get("description", "No description"),
                            fixed_versions=vuln.get("fix_versions", []),
                        )
                    )

            no_vulnerabilities = len(vulnerabilities) == 0
            return (no_vulnerabilities, vulnerabilities)

        except subprocess.TimeoutExpired:
            return (
                False,
                [
                    {
                        "package_name": "UNKNOWN",
                        "installed_version": "UNKNOWN",
                        "vulnerability_id": "TOOL_ERROR",
                        "cvss_score": 7.0,
                        "description": "pip-audit scan timed out",
                        "fixed_versions": [],
                    }
                ],
            )
        except FileNotFoundError:
            return (
                False,
                [
                    {
                        "package_name": "UNKNOWN",
                        "installed_version": "UNKNOWN",
                        "vulnerability_id": "TOOL_ERROR",
                        "cvss_score": 7.0,
                        "description": "pip-audit not installed",
                        "fixed_versions": [],
                    }
                ],
            )
        except Exception as e:
            return (
                False,
                [
                    {
                        "package_name": "UNKNOWN",
                        "installed_version": "UNKNOWN",
                        "vulnerability_id": "TOOL_ERROR",
                        "cvss_score": 7.0,
                        "description": f"pip-audit scan failed: {e}",
                        "fixed_versions": [],
                    }
                ],
            )

    def check_license_compatibility(self, license_name: str) -> tuple[bool, list[str]]:
        """
        Check if license is compatible with project requirements.

        Args:
            license_name: License identifier (e.g., "MIT", "GPL-3.0")

        Returns:
            Tuple of (is_compatible: bool, incompatible_licenses: list[str])
        """
        # List of incompatible licenses (copyleft licenses)
        INCOMPATIBLE_LICENSES = [
            "GPL",
            "AGPL",
            "LGPL",
            "MPL",
            "EPL",
            "CDDL",
            "OSL",
        ]

        license_upper = license_name.upper()
        incompatible = []

        for incompatible_license in INCOMPATIBLE_LICENSES:
            if incompatible_license in license_upper:
                incompatible.append(license_name)
                break

        is_compatible = len(incompatible) == 0
        return (is_compatible, incompatible)

    def get_security_report(self, source_path: str, scan_dependencies: bool = True) -> str:
        """
        Generate comprehensive security report in Markdown format.

        Args:
            source_path: Path to source code
            scan_dependencies: Whether to scan dependencies

        Returns:
            Markdown-formatted security report
        """
        result = self.validate_security(source_path, scan_dependencies)

        # Build Markdown report
        report = ["# Security Validation Report\n"]

        # Overall status
        status_emoji = "✅" if result["is_secure"] else "❌"
        report.append(
            f"**Overall Status**: {status_emoji} {'SECURE' if result['is_secure'] else 'VULNERABILITIES FOUND'}\n"
        )

        # Severity summary
        report.append("## Severity Summary\n")
        report.append(f"- **Critical**: {result['critical_count']}\n")
        report.append(f"- **High**: {result['high_count']}\n")
        report.append(f"- **Medium**: {result['medium_count']}\n")
        report.append(f"- **Low**: {result['low_count']}\n\n")

        # Code security issues
        if result["code_issues"]:
            report.append("## Code Security Issues\n")
            for issue in result["code_issues"][:10]:  # Limit to first 10
                report.append(f"- **{issue['severity']}** ({issue['confidence']} confidence)\n")
                report.append(f"  - File: `{issue['file_path']}:{issue['line_number']}`\n")
                report.append(f"  - Issue: {issue['issue_type']}\n")
                report.append(f"  - Description: {issue['description']}\n")

            if len(result["code_issues"]) > 10:
                report.append(f"\n_...and {len(result['code_issues']) - 10} more issues_\n")

        # Dependency vulnerabilities
        if result["dependency_vulnerabilities"]:
            report.append("\n## Dependency Vulnerabilities\n")
            for vuln in result["dependency_vulnerabilities"][:10]:  # Limit to first 10
                report.append(f"- **{vuln['package_name']} {vuln['installed_version']}**\n")
                report.append(f"  - CVE: {vuln['vulnerability_id']}\n")
                report.append(f"  - CVSS Score: {vuln['cvss_score']}\n")
                report.append(f"  - Description: {vuln['description']}\n")

            if len(result["dependency_vulnerabilities"]) > 10:
                report.append(
                    f"\n_...and {len(result['dependency_vulnerabilities']) - 10} more vulnerabilities_\n"
                )

        # Warnings
        if result["warnings"]:
            report.append("\n## Warnings\n")
            for warning in result["warnings"]:
                report.append(f"- {warning}\n")

        return "".join(report)

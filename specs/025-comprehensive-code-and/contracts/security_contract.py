"""
Security Validation Contract (FR-020)

This contract defines the validation interface for security vulnerability scanning
including code security analysis and dependency CVE detection.

CONSTITUTIONAL REQUIREMENT: Production Readiness (Principle V)
- Code MUST have zero security issues from bandit scan
- Dependencies MUST have zero critical/high CVEs from pip-audit
- Security vulnerabilities are blocking for PyPI release
"""

from typing import Protocol, TypedDict


class SecurityIssue(TypedDict):
    """Details of a security issue"""

    severity: str  # LOW, MEDIUM, HIGH, CRITICAL
    confidence: str  # LOW, MEDIUM, HIGH
    issue_type: str  # e.g., "B301: pickle usage"
    file_path: str
    line_number: int
    description: str


class DependencyVulnerability(TypedDict):
    """Details of a dependency vulnerability"""

    package_name: str
    installed_version: str
    vulnerability_id: str  # CVE-YYYY-NNNNN
    cvss_score: float  # 0.0-10.0 (Common Vulnerability Scoring System)
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


class SecurityValidator(Protocol):
    """
    Contract for security validation.

    Validates code security and dependency vulnerabilities using industry-standard tools.
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

        Validation Criteria (from data-model.md):
        - NO critical vulnerabilities (CVSS ≥9.0)
        - NO high vulnerabilities (CVSS ≥7.0) without documented exception
        - Code security: NO hardcoded passwords, SQL injection, eval() usage
        - Dependencies: pip-audit reports zero critical/high CVEs

        Pass Criteria:
            critical_count == 0 AND high_count == 0

        Raises:
            FileNotFoundError: If source_path does not exist
        """
        ...

    def scan_code_security(self, source_path: str) -> tuple[bool, list[SecurityIssue]]:
        """
        Run bandit security scanner on source code.

        Args:
            source_path: Path to source code directory

        Returns:
            Tuple of (is_secure: bool, issues: list[SecurityIssue])

        Validation Command (from research.md):
            bandit -r src/iris_pgwire/
            # Expected output:
            # Test results:
            #     No issues identified.
            # Code scanned: X lines
            # Total issues: 0

        Security Checks (from research.md):
        - B201: flask_debug_true
        - B301: pickle usage
        - B303: md5 or sha1 (weak cryptography)
        - B307: eval() usage
        - B501: request_with_no_cert_validation
        - B608: hardcoded_sql_expressions (SQL injection)
        - And 40+ other security patterns

        Pass Criteria:
            is_secure == True (zero HIGH or CRITICAL severity issues)
            MEDIUM and LOW issues acceptable with review
        """
        ...

    def scan_dependency_vulnerabilities(self) -> tuple[bool, list[DependencyVulnerability]]:
        """
        Run pip-audit to scan dependencies for CVEs.

        Returns:
            Tuple of (is_secure: bool, vulnerabilities: list[DependencyVulnerability])

        Validation Command (from research.md):
            pip-audit
            # Expected output:
            # No known vulnerabilities found

        Tool Selection (from research.md):
        - Uses OSV database (Google Open Source Vulnerabilities)
        - Free and open source (vs safety paid subscription)
        - Faster than safety (parallel downloads)

        Exit Codes:
            0: No vulnerabilities found ✅
            1: Vulnerabilities found ❌
            2: Error occurred (network, parsing)

        Pass Criteria:
            is_secure == True (zero CRITICAL or HIGH CVSS vulnerabilities)
            CVSS ≥9.0 = CRITICAL
            CVSS ≥7.0 = HIGH
        """
        ...

    def check_license_compatibility(self, dependencies: list[str]) -> tuple[bool, list[str]]:
        """
        Validate dependency license compatibility with MIT license.

        Args:
            dependencies: List of package names

        Returns:
            Tuple of (all_compatible: bool, incompatible_licenses: list[str])

        Validation Rules (from data-model.md):
        - ALL dependencies MUST have OSI-approved licenses
        - Licenses MUST be compatible with MIT (iris-pgwire license)
        - Copyleft licenses (GPL) SHOULD be avoided for runtime dependencies

        Pass Criteria:
            all_compatible == True (no GPL or incompatible licenses)
        """
        ...

    def get_security_report(self, source_path: str) -> str:
        """
        Generate comprehensive security audit report.

        Args:
            source_path: Path to source code directory

        Returns:
            Human-readable security report (Markdown format)

        Report Sections:
        1. Executive Summary (pass/fail status)
        2. Code Security Issues (bandit results)
        3. Dependency Vulnerabilities (pip-audit results)
        4. License Compatibility (OSI-approved status)
        5. Recommendations (if issues found)

        Use Case:
            Include report in security documentation for audits
        """
        ...


# Contract Test Requirements (TDD):
#
# 1. Test validate_security() on iris-pgwire → returns is_secure=True
# 2. Test validate_security() with vulnerable code → returns is_secure=False
# 3. Test scan_code_security() on clean code → returns (True, [])
# 4. Test scan_code_security() with hardcoded password → returns (False, [issue])
# 5. Test scan_dependency_vulnerabilities() → returns (True, [])
# 6. Test scan_dependency_vulnerabilities() with known CVE → returns (False, [vuln])
# 7. Test check_license_compatibility() with MIT deps → returns (True, [])
# 8. Test check_license_compatibility() with GPL dep → returns (False, [license])
# 9. Test get_security_report() returns Markdown report
#
# CRITICAL: All tests MUST fail initially (no implementation exists yet)
# Implement SecurityValidator to make tests pass (Red-Green-Refactor)

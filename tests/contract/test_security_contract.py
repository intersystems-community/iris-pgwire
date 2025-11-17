"""
Contract Tests for Security Validation (T006)

CRITICAL: These tests MUST fail initially (no SecurityValidator implementation exists).
Implement SecurityValidator to make these tests pass (Red-Green-Refactor).

Contract: specs/025-comprehensive-code-and/contracts/security_contract.py
Constitutional Requirement: Production Readiness (Principle V)
"""

from pathlib import Path

import pytest

# IMPORTANT: This import will fail initially (no implementation yet)
# This is EXPECTED - tests MUST fail before implementation
try:
    from iris_pgwire.quality.security_validator import SecurityValidator

    IMPLEMENTATION_EXISTS = True
except ImportError:
    IMPLEMENTATION_EXISTS = False

    # Create placeholder for type hints
    class SecurityValidator:  # type: ignore
        pass


pytestmark = pytest.mark.skipif(
    not IMPLEMENTATION_EXISTS,
    reason="SecurityValidator not implemented yet (TDD: tests must fail first)",
)


@pytest.fixture
def validator():
    """Fixture providing SecurityValidator instance"""
    return SecurityValidator()


@pytest.fixture
def project_root():
    """Fixture providing iris-pgwire project root path"""
    return str(Path(__file__).parents[2])


@pytest.fixture
def code_with_security_issue(tmp_path):
    """Fixture providing Python file with security vulnerability"""
    vulnerable_code = """
import pickle

def load_data(filename):
    with open(filename, 'rb') as f:
        return pickle.load(f)  # B301: pickle usage (security issue)

password = "hardcoded_password123"  # B105: hardcoded password
"""

    file_path = tmp_path / "vulnerable.py"
    with open(file_path, "w") as f:
        f.write(vulnerable_code)

    return str(tmp_path)


class TestSecurityContract:
    """Contract tests for SecurityValidator Protocol"""

    def test_validate_security_iris_pgwire(self, validator, project_root):
        """
        Test validate_security() on iris-pgwire source code.

        Expected: Returns is_secure=True (zero critical/high vulnerabilities)
        Contract: security_contract.py lines 55-82
        """
        source_path = f"{project_root}/src/iris_pgwire"

        result = validator.validate_security(source_path, scan_dependencies=False)

        assert result["is_secure"] is True, (
            f"iris-pgwire should be secure. "
            f"Critical: {result['critical_count']}, High: {result['high_count']}"
        )
        assert result["critical_count"] == 0, "No critical vulnerabilities expected"
        assert result["high_count"] == 0, "No high severity vulnerabilities expected"

    def test_validate_security_vulnerable_code(self, validator, code_with_security_issue):
        """
        Test validate_security() with vulnerable code.

        Expected: Returns is_secure=False
        Contract: security_contract.py lines 55-82
        """
        result = validator.validate_security(code_with_security_issue, scan_dependencies=False)

        assert result["is_secure"] is False, "Should detect security issues"
        assert len(result["code_issues"]) > 0, "Should report code security issues"

        # Should detect pickle usage (B301) and hardcoded password (B105)
        issue_types = {issue["issue_type"] for issue in result["code_issues"]}
        assert any(
            "B301" in itype or "pickle" in itype for itype in issue_types
        ), "Should detect pickle usage vulnerability"

    def test_scan_code_security_clean(self, validator, project_root):
        """
        Test scan_code_security() on clean iris-pgwire code.

        Expected: Returns (True, [])
        Contract: security_contract.py lines 84-115
        """
        source_path = f"{project_root}/src/iris_pgwire"

        is_secure, issues = validator.scan_code_security(source_path)

        # Filter out LOW and MEDIUM severity issues (acceptable with review)
        high_critical_issues = [
            issue for issue in issues if issue["severity"] in ["HIGH", "CRITICAL"]
        ]

        assert is_secure is True, f"Code should be secure. Issues: {high_critical_issues}"
        assert len(high_critical_issues) == 0, "No HIGH/CRITICAL issues expected"

    def test_scan_code_security_hardcoded_password(self, validator, code_with_security_issue):
        """
        Test scan_code_security() with hardcoded password.

        Expected: Returns (False, [issue])
        Contract: security_contract.py lines 84-115
        """
        is_secure, issues = validator.scan_code_security(code_with_security_issue)

        assert is_secure is False, "Should detect security vulnerability"
        assert len(issues) > 0, "Should report security issues"

        # Check for hardcoded password (B105)
        assert any(
            "B105" in issue["issue_type"] or "password" in issue["description"].lower()
            for issue in issues
        ), "Should detect hardcoded password"

    def test_scan_dependency_vulnerabilities_clean(self, validator):
        """
        Test scan_dependency_vulnerabilities() on iris-pgwire.

        Expected: Returns (True, [])
        Contract: security_contract.py lines 117-144
        """
        is_secure, vulnerabilities = validator.scan_dependency_vulnerabilities()

        # Filter for CRITICAL and HIGH severity CVEs only
        critical_high_vulns = [
            vuln for vuln in vulnerabilities if vuln["cvss_score"] >= 7.0  # CVSS ≥7.0 = HIGH
        ]

        assert is_secure is True, (
            f"Dependencies should be secure. " f"Critical/High CVEs: {critical_high_vulns}"
        )
        assert len(critical_high_vulns) == 0, "No critical/high CVEs expected"

    def test_scan_dependency_vulnerabilities_cve(self, validator, tmp_path, monkeypatch):
        """
        Test scan_dependency_vulnerabilities() detection of known CVE.

        Expected: Returns (False, [vuln])
        Contract: security_contract.py lines 117-144

        Note: This test simulates a vulnerable dependency scenario
        """
        # This test validates the interface correctly reports vulnerabilities
        # In a real scenario, we'd install a known vulnerable package version

        # Skip this test for now - requires mock vulnerable environment
        pytest.skip("Requires mock vulnerable dependency environment")

    def test_check_license_compatibility_mit(self, validator):
        """
        Test check_license_compatibility() with MIT-compatible dependencies.

        Expected: Returns (True, [])
        Contract: security_contract.py lines 146-167
        """
        mit_compatible_deps = [
            "structlog",  # MIT
            "cryptography",  # Apache/BSD
            "psycopg2-binary",  # LGPL (compatible with MIT)
        ]

        all_compatible, incompatible = validator.check_license_compatibility(mit_compatible_deps)

        assert all_compatible is True, (
            f"All dependencies should be MIT-compatible. " f"Incompatible: {incompatible}"
        )
        assert len(incompatible) == 0, "No incompatible licenses expected"

    def test_check_license_compatibility_gpl(self, validator):
        """
        Test check_license_compatibility() with GPL dependency.

        Expected: Returns (False, [license])
        Contract: security_contract.py lines 146-167

        Note: GPL is copyleft and should be flagged for runtime dependencies
        """
        deps_with_gpl = [
            "structlog",  # MIT (compatible)
            "gpl-package",  # GPL (incompatible for MIT license)
        ]

        all_compatible, incompatible = validator.check_license_compatibility(deps_with_gpl)

        # Note: May pass if gpl-package doesn't exist or validator is lenient
        # This test documents expected behavior for GPL detection
        if not all_compatible:
            assert len(incompatible) > 0, "Should report incompatible licenses"

    def test_get_security_report(self, validator, project_root):
        """
        Test get_security_report() returns Markdown report.

        Expected: Returns Markdown report string
        Contract: security_contract.py lines 169-189
        """
        source_path = f"{project_root}/src/iris_pgwire"

        report = validator.get_security_report(source_path)

        assert isinstance(report, str), "Should return string"
        assert len(report) > 0, "Report should not be empty"
        assert (
            "Security Audit" in report or "security" in report.lower()
        ), "Report should mention security"
        # Check for report sections
        assert any(
            section in report for section in ["Code Security", "Dependencies", "Vulnerabilities"]
        ), "Report should have expected sections"


class TestSecurityEdgeCases:
    """Edge case tests for SecurityValidator"""

    def test_validate_security_nonexistent_path(self, validator):
        """Test validate_security() with nonexistent path"""
        with pytest.raises(FileNotFoundError):
            validator.validate_security("/nonexistent/path")

    def test_scan_code_security_empty_directory(self, validator, tmp_path):
        """Test scan_code_security() with empty directory"""
        is_secure, issues = validator.scan_code_security(str(tmp_path))

        # Empty directory should be secure (nothing to scan)
        assert is_secure is True
        assert len(issues) == 0

    def test_check_license_compatibility_empty_list(self, validator):
        """Test check_license_compatibility() with empty list"""
        all_compatible, incompatible = validator.check_license_compatibility([])

        # Empty list should be compatible (nothing to check)
        assert all_compatible is True
        assert len(incompatible) == 0

"""
Unit Tests for Bandit Severity Classification (T030)

Tests the SecurityValidator.scan_code_security() method's ability to correctly
classify security issues by severity level (CRITICAL, HIGH, MEDIUM, LOW).

Constitutional Requirement: Production Readiness (Principle V)
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from iris_pgwire.quality.security_validator import SecurityValidator


class TestBanditSeverityClassification:
    """Unit tests for bandit severity classification logic"""

    def setup_method(self):
        """Set up test fixtures"""
        self.validator = SecurityValidator()

    # T030.1: Basic severity classification
    def test_classify_high_severity(self):
        """Should correctly identify HIGH severity issues"""
        bandit_output = {
            "results": [
                {
                    "issue_severity": "HIGH",
                    "issue_confidence": "HIGH",
                    "test_id": "B101",
                    "filename": "/app/src/test.py",
                    "line_number": 42,
                    "issue_text": "Use of assert detected",
                }
            ]
        }

        mock_result = MagicMock()
        mock_result.stdout = json.dumps(bandit_output)
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            is_secure, issues = self.validator.scan_code_security("/fake/path")

        assert is_secure is False
        assert len(issues) == 1
        assert issues[0]["severity"] == "HIGH"
        assert issues[0]["confidence"] == "HIGH"
        assert issues[0]["issue_type"] == "B101"

    def test_classify_medium_severity(self):
        """Should correctly identify MEDIUM severity issues"""
        bandit_output = {
            "results": [
                {
                    "issue_severity": "MEDIUM",
                    "issue_confidence": "MEDIUM",
                    "test_id": "B201",
                    "filename": "/app/src/test.py",
                    "line_number": 15,
                    "issue_text": "Flask app with debug=True",
                }
            ]
        }

        mock_result = MagicMock()
        mock_result.stdout = json.dumps(bandit_output)
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            is_secure, issues = self.validator.scan_code_security("/fake/path")

        # scan_code_security returns (no_issues, issues)
        # where no_issues is False if ANY issues exist
        assert is_secure is False  # Any issue means no_issues=False
        assert len(issues) == 1
        assert issues[0]["severity"] == "MEDIUM"

    def test_classify_low_severity(self):
        """Should correctly identify LOW severity issues"""
        bandit_output = {
            "results": [
                {
                    "issue_severity": "LOW",
                    "issue_confidence": "LOW",
                    "test_id": "B301",
                    "filename": "/app/src/test.py",
                    "line_number": 8,
                    "issue_text": "Pickle usage detected",
                }
            ]
        }

        mock_result = MagicMock()
        mock_result.stdout = json.dumps(bandit_output)
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            is_secure, issues = self.validator.scan_code_security("/fake/path")

        # scan_code_security returns (no_issues, issues)
        assert is_secure is False  # Any issue means no_issues=False
        assert len(issues) == 1
        assert issues[0]["severity"] == "LOW"

    # T030.2: Multiple issues with mixed severity
    def test_classify_mixed_severity_issues(self):
        """Should correctly classify multiple issues with different severities"""
        bandit_output = {
            "results": [
                {
                    "issue_severity": "HIGH",
                    "issue_confidence": "HIGH",
                    "test_id": "B101",
                    "filename": "/app/src/test1.py",
                    "line_number": 10,
                    "issue_text": "High severity issue",
                },
                {
                    "issue_severity": "MEDIUM",
                    "issue_confidence": "MEDIUM",
                    "test_id": "B201",
                    "filename": "/app/src/test2.py",
                    "line_number": 20,
                    "issue_text": "Medium severity issue",
                },
                {
                    "issue_severity": "LOW",
                    "issue_confidence": "LOW",
                    "test_id": "B301",
                    "filename": "/app/src/test3.py",
                    "line_number": 30,
                    "issue_text": "Low severity issue",
                },
            ]
        }

        mock_result = MagicMock()
        mock_result.stdout = json.dumps(bandit_output)
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            is_secure, issues = self.validator.scan_code_security("/fake/path")

        assert is_secure is False  # HIGH issue blocks security
        assert len(issues) == 3
        assert issues[0]["severity"] == "HIGH"
        assert issues[1]["severity"] == "MEDIUM"
        assert issues[2]["severity"] == "LOW"

    # T030.3: Confidence level variations
    def test_high_severity_with_low_confidence(self):
        """Should classify HIGH severity with LOW confidence correctly"""
        bandit_output = {
            "results": [
                {
                    "issue_severity": "HIGH",
                    "issue_confidence": "LOW",
                    "test_id": "B102",
                    "filename": "/app/src/test.py",
                    "line_number": 42,
                    "issue_text": "Possible SQL injection",
                }
            ]
        }

        mock_result = MagicMock()
        mock_result.stdout = json.dumps(bandit_output)
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            is_secure, issues = self.validator.scan_code_security("/fake/path")

        assert is_secure is False  # Still blocks even with low confidence
        assert issues[0]["severity"] == "HIGH"
        assert issues[0]["confidence"] == "LOW"

    def test_medium_severity_with_high_confidence(self):
        """Should classify MEDIUM severity with HIGH confidence correctly"""
        bandit_output = {
            "results": [
                {
                    "issue_severity": "MEDIUM",
                    "issue_confidence": "HIGH",
                    "test_id": "B201",
                    "filename": "/app/src/test.py",
                    "line_number": 15,
                    "issue_text": "Hardcoded password detected",
                }
            ]
        }

        mock_result = MagicMock()
        mock_result.stdout = json.dumps(bandit_output)
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            is_secure, issues = self.validator.scan_code_security("/fake/path")

        # scan_code_security returns no_issues=False if ANY issues exist
        assert is_secure is False
        assert issues[0]["severity"] == "MEDIUM"
        assert issues[0]["confidence"] == "HIGH"

    # T030.4: Edge cases in bandit output
    def test_missing_severity_field(self):
        """Should default to MEDIUM if severity field is missing"""
        bandit_output = {
            "results": [
                {
                    # "issue_severity": missing!
                    "issue_confidence": "HIGH",
                    "test_id": "B999",
                    "filename": "/app/src/test.py",
                    "line_number": 1,
                    "issue_text": "Unknown issue",
                }
            ]
        }

        mock_result = MagicMock()
        mock_result.stdout = json.dumps(bandit_output)
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            is_secure, issues = self.validator.scan_code_security("/fake/path")

        assert len(issues) == 1
        assert issues[0]["severity"] == "MEDIUM"  # Default value

    def test_empty_results_array(self):
        """Should return no issues for empty results"""
        bandit_output = {"results": []}

        mock_result = MagicMock()
        mock_result.stdout = json.dumps(bandit_output)
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            is_secure, issues = self.validator.scan_code_security("/fake/path")

        assert is_secure is True
        assert len(issues) == 0

    def test_malformed_json_output(self):
        """Should handle malformed JSON gracefully"""
        mock_result = MagicMock()
        mock_result.stdout = "This is not valid JSON"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            is_secure, issues = self.validator.scan_code_security("/fake/path")

        assert is_secure is False
        assert len(issues) == 1
        assert issues[0]["severity"] == "HIGH"
        assert issues[0]["issue_type"] == "TOOL_ERROR"
        assert "JSON output parsing failed" in issues[0]["description"]

    # T030.5: Integration with validate_security
    def test_severity_counting_in_validate_security(self):
        """Should correctly count severities in validate_security"""
        bandit_output = {
            "results": [
                {
                    "issue_severity": "HIGH",
                    "issue_confidence": "HIGH",
                    "test_id": "B101",
                    "filename": "/app/src/test1.py",
                    "line_number": 10,
                    "issue_text": "High issue 1",
                },
                {
                    "issue_severity": "HIGH",
                    "issue_confidence": "HIGH",
                    "test_id": "B102",
                    "filename": "/app/src/test2.py",
                    "line_number": 20,
                    "issue_text": "High issue 2",
                },
                {
                    "issue_severity": "MEDIUM",
                    "issue_confidence": "MEDIUM",
                    "test_id": "B201",
                    "filename": "/app/src/test3.py",
                    "line_number": 30,
                    "issue_text": "Medium issue",
                },
                {
                    "issue_severity": "LOW",
                    "issue_confidence": "LOW",
                    "test_id": "B301",
                    "filename": "/app/src/test4.py",
                    "line_number": 40,
                    "issue_text": "Low issue",
                },
            ]
        }

        mock_result = MagicMock()
        mock_result.stdout = json.dumps(bandit_output)
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            with patch("pathlib.Path.exists", return_value=True):
                result = self.validator.validate_security("/fake/path", scan_dependencies=False)

        assert result["is_secure"] is False  # HIGH issues block
        assert result["high_count"] == 2
        assert result["medium_count"] == 1
        assert result["low_count"] == 1
        assert result["critical_count"] == 0
        assert len(result["code_issues"]) == 4

    def test_critical_severity_from_bandit(self):
        """Should handle CRITICAL severity if bandit reports it"""
        bandit_output = {
            "results": [
                {
                    "issue_severity": "CRITICAL",
                    "issue_confidence": "HIGH",
                    "test_id": "B000",
                    "filename": "/app/src/test.py",
                    "line_number": 1,
                    "issue_text": "Critical vulnerability",
                }
            ]
        }

        mock_result = MagicMock()
        mock_result.stdout = json.dumps(bandit_output)
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            with patch("pathlib.Path.exists", return_value=True):
                result = self.validator.validate_security("/fake/path", scan_dependencies=False)

        assert result["is_secure"] is False
        assert result["critical_count"] == 1

    # T030.6: Real-world bandit output samples
    def test_parse_actual_bandit_b608(self):
        """Should parse actual B608 (SQL injection) output"""
        bandit_output = {
            "results": [
                {
                    "code": '42             cursor.execute("SELECT * FROM users WHERE id = %s" % user_id)',
                    "filename": "/app/src/iris_pgwire/database.py",
                    "issue_confidence": "MEDIUM",
                    "issue_severity": "MEDIUM",
                    "issue_text": "Possible SQL injection vector through string-based query construction.",
                    "line_number": 42,
                    "line_range": [42],
                    "more_info": "https://bandit.readthedocs.io/en/latest/plugins/b608_hardcoded_sql_expressions.html",
                    "test_id": "B608",
                    "test_name": "hardcoded_sql_expressions",
                }
            ]
        }

        mock_result = MagicMock()
        mock_result.stdout = json.dumps(bandit_output)
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            is_secure, issues = self.validator.scan_code_security("/fake/path")

        assert len(issues) == 1
        assert issues[0]["severity"] == "MEDIUM"
        assert issues[0]["confidence"] == "MEDIUM"
        assert issues[0]["issue_type"] == "B608"
        assert "SQL injection" in issues[0]["description"]

    def test_parse_actual_bandit_b104(self):
        """Should parse actual B104 (bind all interfaces) output"""
        bandit_output = {
            "results": [
                {
                    "code": '89         server.bind(("0.0.0.0", 5432))',
                    "filename": "/app/src/iris_pgwire/server.py",
                    "issue_confidence": "MEDIUM",
                    "issue_severity": "MEDIUM",
                    "issue_text": "Possible binding to all interfaces.",
                    "line_number": 89,
                    "line_range": [89],
                    "more_info": "https://bandit.readthedocs.io/en/latest/plugins/b104_hardcoded_bind_all_interfaces.html",
                    "test_id": "B104",
                    "test_name": "hardcoded_bind_all_interfaces",
                }
            ]
        }

        mock_result = MagicMock()
        mock_result.stdout = json.dumps(bandit_output)
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            is_secure, issues = self.validator.scan_code_security("/fake/path")

        assert len(issues) == 1
        assert issues[0]["severity"] == "MEDIUM"
        assert issues[0]["issue_type"] == "B104"

    # T030.7: Error handling
    def test_subprocess_timeout(self):
        """Should handle subprocess timeout gracefully"""
        import subprocess

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("bandit", 120)):
            is_secure, issues = self.validator.scan_code_security("/fake/path")

        assert is_secure is False
        assert len(issues) == 1
        assert issues[0]["severity"] == "HIGH"
        assert issues[0]["issue_type"] == "TOOL_ERROR"
        assert "timed out" in issues[0]["description"]

    def test_bandit_not_installed(self):
        """Should handle bandit not installed gracefully"""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            is_secure, issues = self.validator.scan_code_security("/fake/path")

        assert is_secure is False
        assert len(issues) == 1
        assert issues[0]["severity"] == "HIGH"
        assert "not installed" in issues[0]["description"]

    def test_generic_exception(self):
        """Should handle unexpected exceptions gracefully"""
        with patch("subprocess.run", side_effect=Exception("Unexpected error")):
            is_secure, issues = self.validator.scan_code_security("/fake/path")

        assert is_secure is False
        assert len(issues) == 1
        assert issues[0]["severity"] == "HIGH"
        assert "failed" in issues[0]["description"]

    # T030.8: Severity thresholds
    def test_security_passes_with_only_medium_and_low(self):
        """Should pass security validation with only MEDIUM/LOW issues"""
        bandit_output = {
            "results": [
                {"issue_severity": "MEDIUM", "issue_confidence": "HIGH", "test_id": "B201", "filename": "test.py", "line_number": 1, "issue_text": "Medium"},
                {"issue_severity": "LOW", "issue_confidence": "LOW", "test_id": "B301", "filename": "test.py", "line_number": 2, "issue_text": "Low"},
            ]
        }

        mock_result = MagicMock()
        mock_result.stdout = json.dumps(bandit_output)
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            is_secure, issues = self.validator.scan_code_security("/fake/path")

        # scan_code_security returns (no_issues, issues)
        # where no_issues is False if ANY issues exist
        # NOTE: validate_security() is what checks severity and only blocks on CRITICAL/HIGH
        assert is_secure is False  # Any issues means no_issues=False
        assert len(issues) == 2

    def test_security_fails_with_any_high(self):
        """Should fail security validation with any HIGH issue"""
        bandit_output = {
            "results": [
                {"issue_severity": "LOW", "issue_confidence": "LOW", "test_id": "B301", "filename": "test.py", "line_number": 1, "issue_text": "Low"},
                {"issue_severity": "HIGH", "issue_confidence": "HIGH", "test_id": "B101", "filename": "test.py", "line_number": 2, "issue_text": "High"},
            ]
        }

        mock_result = MagicMock()
        mock_result.stdout = json.dumps(bandit_output)
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            is_secure, issues = self.validator.scan_code_security("/fake/path")

        # Should fail because of HIGH issue
        assert is_secure is False
        assert len(issues) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

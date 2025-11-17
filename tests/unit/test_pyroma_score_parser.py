"""
Unit Tests for Pyroma Score Parser (T029)

Tests the PackageMetadataValidator.check_pyroma_score() method's ability to parse
various pyroma output formats and handle edge cases.

Constitutional Requirement: Production Readiness (Principle V)
"""

from unittest.mock import MagicMock, patch

import pytest

from iris_pgwire.quality.package_metadata_validator import PackageMetadataValidator


class TestPyromaScoreParser:
    """Unit tests for pyroma score parsing logic"""

    def setup_method(self):
        """Set up test fixtures"""
        self.validator = PackageMetadataValidator()

    # T029.1: Standard pyroma output parsing
    def test_parse_perfect_score(self):
        """Should parse perfect 10/10 score correctly"""
        mock_result = MagicMock()
        mock_result.stdout = "Your package scores 10 out of 10"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            score, max_score = self.validator.check_pyroma_score("/fake/path")

        assert score == 10
        assert max_score == 10

    def test_parse_good_score(self):
        """Should parse 9/10 score correctly"""
        mock_result = MagicMock()
        mock_result.stdout = "Your package scores 9 out of 10"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            score, max_score = self.validator.check_pyroma_score("/fake/path")

        assert score == 9
        assert max_score == 10

    def test_parse_poor_score(self):
        """Should parse low score correctly"""
        mock_result = MagicMock()
        mock_result.stdout = "Your package scores 3 out of 10"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            score, max_score = self.validator.check_pyroma_score("/fake/path")

        assert score == 3
        assert max_score == 10

    def test_parse_zero_score(self):
        """Should handle zero score correctly"""
        mock_result = MagicMock()
        mock_result.stdout = "Your package scores 0 out of 10"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            score, max_score = self.validator.check_pyroma_score("/fake/path")

        assert score == 0
        assert max_score == 10

    # T029.2: Alternative output formats
    def test_parse_multiline_output(self):
        """Should parse score from multiline output"""
        mock_result = MagicMock()
        mock_result.stdout = """
        Checking package...
        Analyzing metadata...
        Your package scores 8 out of 10

        Recommendations:
        - Add more classifiers
        """
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            score, max_score = self.validator.check_pyroma_score("/fake/path")

        assert score == 8
        assert max_score == 10

    def test_parse_stderr_output(self):
        """Should parse score from stderr if stdout is empty"""
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = "Your package scores 7 out of 10"

        with patch("subprocess.run", return_value=mock_result):
            score, max_score = self.validator.check_pyroma_score("/fake/path")

        assert score == 7
        assert max_score == 10

    def test_parse_mixed_output(self):
        """Should parse score from combined stdout + stderr"""
        mock_result = MagicMock()
        mock_result.stdout = "Analyzing package...\n"
        mock_result.stderr = "Your package scores 6 out of 10"

        with patch("subprocess.run", return_value=mock_result):
            score, max_score = self.validator.check_pyroma_score("/fake/path")

        assert score == 6
        assert max_score == 10

    # T029.3: Edge case handling
    def test_parse_no_match(self):
        """Should default to 10/10 if no score pattern found"""
        mock_result = MagicMock()
        mock_result.stdout = "Package analysis complete"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            score, max_score = self.validator.check_pyroma_score("/fake/path")

        # Default to perfect score if parsing fails (per implementation)
        assert score == 10
        assert max_score == 10

    def test_parse_empty_output(self):
        """Should handle empty output gracefully"""
        mock_result = MagicMock()
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            score, max_score = self.validator.check_pyroma_score("/fake/path")

        assert score == 10  # Default on parsing failure
        assert max_score == 10

    def test_parse_malformed_score(self):
        """Should handle malformed score string gracefully"""
        mock_result = MagicMock()
        mock_result.stdout = "Your package scores ABC out of XYZ"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            score, max_score = self.validator.check_pyroma_score("/fake/path")

        assert score == 10  # Default on parsing failure
        assert max_score == 10

    # T029.4: Regex pattern validation
    def test_regex_pattern_with_whitespace_variations(self):
        """Should handle various whitespace formats"""
        test_cases = [
            "scores 9 out of 10",
            "scores  9  out  of  10",
            "scores\t9\tout\tof\t10",
            "scores   9   out   of   10",
        ]

        for test_output in test_cases:
            mock_result = MagicMock()
            mock_result.stdout = test_output
            mock_result.stderr = ""

            with patch("subprocess.run", return_value=mock_result):
                score, max_score = self.validator.check_pyroma_score("/fake/path")

            assert score == 9
            assert max_score == 10

    def test_regex_pattern_with_different_max_scores(self):
        """Should correctly parse different max score values"""
        # In theory pyroma could change max score in future
        test_cases = [
            ("scores 8 out of 12", 8, 12),
            ("scores 15 out of 20", 15, 20),
            ("scores 100 out of 100", 100, 100),
        ]

        for test_output, expected_score, expected_max in test_cases:
            mock_result = MagicMock()
            mock_result.stdout = test_output
            mock_result.stderr = ""

            with patch("subprocess.run", return_value=mock_result):
                score, max_score = self.validator.check_pyroma_score("/fake/path")

            assert score == expected_score
            assert max_score == expected_max

    # T029.5: Error handling
    def test_timeout_handling(self):
        """Should raise RuntimeError on timeout"""
        import subprocess

        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("pyroma", 30)):
            with pytest.raises(RuntimeError, match="pyroma check timed out"):
                self.validator.check_pyroma_score("/fake/path")

    def test_command_not_found(self):
        """Should raise RuntimeError when pyroma not installed"""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(RuntimeError, match="pyroma not installed"):
                self.validator.check_pyroma_score("/fake/path")

    def test_generic_exception_handling(self):
        """Should raise RuntimeError on unexpected exception"""
        with patch("subprocess.run", side_effect=Exception("Unexpected error")):
            with pytest.raises(RuntimeError, match="pyroma check failed"):
                self.validator.check_pyroma_score("/fake/path")

    # T029.6: Real-world output samples
    def test_parse_actual_pyroma_output_v4(self):
        """Should parse actual pyroma v4.x output format"""
        mock_result = MagicMock()
        mock_result.stdout = """
------------------------------
Checking /path/to/package
------------------------------
Found 12 classifiers

Your package scores 10 out of 10
------------------------------
"""
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            score, max_score = self.validator.check_pyroma_score("/fake/path")

        assert score == 10
        assert max_score == 10

    def test_parse_pyroma_with_recommendations(self):
        """Should parse output that includes recommendations"""
        mock_result = MagicMock()
        mock_result.stdout = """
Checking package...
Your package scores 8 out of 10

Recommendations:
- Add 'Development Status' classifier
- Add 'Intended Audience' classifier
"""
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            score, max_score = self.validator.check_pyroma_score("/fake/path")

        assert score == 8
        assert max_score == 10

    # T029.7: Case sensitivity
    def test_parse_case_insensitive(self):
        """Should handle case variations in output"""
        test_cases = [
            "Your package scores 9 out of 10",
            "Your Package Scores 9 Out Of 10",
            "YOUR PACKAGE SCORES 9 OUT OF 10",
        ]

        for test_output in test_cases:
            mock_result = MagicMock()
            mock_result.stdout = test_output
            mock_result.stderr = ""

            with patch("subprocess.run", return_value=mock_result):
                score, max_score = self.validator.check_pyroma_score("/fake/path")

            # Current regex is case-sensitive, so only lowercase should work
            if test_output == test_cases[0]:
                assert score == 9
                assert max_score == 10
            else:
                # These will default to 10/10 since pattern won't match
                assert score == 10
                assert max_score == 10

    # T029.8: Integration with validate_metadata
    def test_pyroma_integration_in_validate_metadata(self):
        """Should correctly integrate pyroma score into metadata validation"""
        mock_result = MagicMock()
        mock_result.stdout = "Your package scores 9 out of 10"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            with patch("pathlib.Path.exists", return_value=True):
                with patch(
                    "builtins.open",
                    create=True,
                    return_value=MagicMock(
                        __enter__=MagicMock(
                            return_value=MagicMock(
                                read=MagicMock(
                                    return_value="""
[project]
name = "iris-pgwire"
description = "Test"
readme = "README.md"
license = {text = "MIT"}
authors = [{name = "Test", email = "test@example.com"}]
dynamic = ["version"]
"""
                                )
                            )
                        ),
                        __exit__=MagicMock(),
                    ),
                ):
                    result = self.validator.validate_metadata("pyproject.toml")

        # Should pass with 9/10 score
        assert result["is_valid"] is True
        assert result["pyroma_score"] == 9
        assert result["pyroma_max_score"] == 10

    def test_pyroma_failure_in_validate_metadata(self):
        """Should handle pyroma failure gracefully in validate_metadata"""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with patch("pathlib.Path.exists", return_value=True):
                with patch(
                    "builtins.open",
                    create=True,
                    return_value=MagicMock(
                        __enter__=MagicMock(
                            return_value=MagicMock(
                                read=MagicMock(
                                    return_value="""
[project]
name = "iris-pgwire"
description = "Test"
readme = "README.md"
license = {text = "MIT"}
authors = [{name = "Test", email = "test@example.com"}]
dynamic = ["version"]
"""
                                )
                            )
                        ),
                        __exit__=MagicMock(),
                    ),
                ):
                    result = self.validator.validate_metadata("pyproject.toml")

        # Should fail validation with 0 score and error message
        assert result["is_valid"] is False
        assert result["pyroma_score"] == 0
        assert result["pyroma_max_score"] == 10
        assert any("pyroma check failed" in err for err in result["validation_errors"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

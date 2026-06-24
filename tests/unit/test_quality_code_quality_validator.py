"""
Unit tests for quality/code_quality_validator.py (CodeQualityValidator)

Target: ≥85% coverage on code_quality_validator.py (baseline ~46%)

Tests cover:
- validate_code_quality(): happy path, black/ruff failures, mypy skipped,
  FileNotFoundError, mypy warnings
- check_black_formatting(): pass, fail with reformat messages, empty paths,
  timeout, FileNotFoundError, generic exception
- check_ruff_linting(): pass, fail with errors, empty paths,
  timeout, FileNotFoundError, generic exception
- check_type_annotations(): pass, fail, empty modules, timeout,
  FileNotFoundError, generic exception
- measure_complexity(): file path, directory path, mixed, string input
- _extract_public_modules(): src directory with public files, without
- _count_python_files(): file, directory, mixed

All subprocess calls are mocked.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from iris_pgwire.quality.code_quality_validator import CodeQualityValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sp_result(returncode=0, stdout="", stderr=""):
    r = MagicMock()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


# ---------------------------------------------------------------------------
# validate_code_quality
# ---------------------------------------------------------------------------

class TestValidateCodeQuality:

    def setup_method(self):
        self.validator = CodeQualityValidator()

    def test_happy_path_all_pass(self, tmp_path):
        """All checks pass → is_valid True, no warnings."""
        py_file = tmp_path / "foo.py"
        py_file.write_text("x = 1\n")

        with patch.object(self.validator, "check_black_formatting", return_value=(True, [])), \
             patch.object(self.validator, "check_ruff_linting", return_value=(True, [])), \
             patch.object(self.validator, "check_type_annotations", return_value=(True, [])), \
             patch.object(self.validator, "_extract_public_modules", return_value=[]), \
             patch.object(self.validator, "_count_python_files", return_value=1):

            result = self.validator.validate_code_quality([str(tmp_path)])

        assert result["is_valid"] is True
        assert result["black_passed"] is True
        assert result["ruff_passed"] is True
        assert result["mypy_passed"] is True
        assert result["warnings"] == []
        assert result["files_checked"] == 1

    def test_black_fails_makes_invalid(self, tmp_path):
        py_file = tmp_path / "foo.py"
        py_file.write_text("x = 1\n")

        with patch.object(self.validator, "check_black_formatting", return_value=(False, ["a.py"])), \
             patch.object(self.validator, "check_ruff_linting", return_value=(True, [])), \
             patch.object(self.validator, "check_type_annotations", return_value=(True, [])), \
             patch.object(self.validator, "_extract_public_modules", return_value=[]), \
             patch.object(self.validator, "_count_python_files", return_value=1):

            result = self.validator.validate_code_quality([str(tmp_path)])

        assert result["is_valid"] is False
        assert result["black_passed"] is False
        assert result["black_errors"] == ["a.py"]

    def test_ruff_fails_makes_invalid(self, tmp_path):
        py_file = tmp_path / "foo.py"
        py_file.write_text("x = 1\n")

        with patch.object(self.validator, "check_black_formatting", return_value=(True, [])), \
             patch.object(self.validator, "check_ruff_linting", return_value=(False, ["E501 line too long"])), \
             patch.object(self.validator, "check_type_annotations", return_value=(True, [])), \
             patch.object(self.validator, "_extract_public_modules", return_value=[]), \
             patch.object(self.validator, "_count_python_files", return_value=1):

            result = self.validator.validate_code_quality([str(tmp_path)])

        assert result["is_valid"] is False
        assert result["ruff_passed"] is False
        assert result["ruff_errors"] == ["E501 line too long"]

    def test_mypy_fails_produces_warning_not_blocking(self, tmp_path):
        py_file = tmp_path / "foo.py"
        py_file.write_text("x = 1\n")

        with patch.object(self.validator, "check_black_formatting", return_value=(True, [])), \
             patch.object(self.validator, "check_ruff_linting", return_value=(True, [])), \
             patch.object(self.validator, "check_type_annotations", return_value=(False, ["error: bad"])), \
             patch.object(self.validator, "_extract_public_modules", return_value=["server.py"]), \
             patch.object(self.validator, "_count_python_files", return_value=1):

            result = self.validator.validate_code_quality([str(tmp_path)])

        # mypy failure does NOT make is_valid False
        assert result["is_valid"] is True
        assert result["mypy_passed"] is False
        assert result["mypy_errors"] == ["error: bad"]
        assert len(result["warnings"]) == 1
        assert "type checking" in result["warnings"][0].lower()

    def test_check_types_false_skips_mypy(self, tmp_path):
        py_file = tmp_path / "foo.py"
        py_file.write_text("x = 1\n")

        with patch.object(self.validator, "check_black_formatting", return_value=(True, [])), \
             patch.object(self.validator, "check_ruff_linting", return_value=(True, [])), \
             patch.object(self.validator, "check_type_annotations") as mock_mypy, \
             patch.object(self.validator, "_extract_public_modules", return_value=[]), \
             patch.object(self.validator, "_count_python_files", return_value=1):

            result = self.validator.validate_code_quality([str(tmp_path)], check_types=False)

        mock_mypy.assert_not_called()
        assert result["mypy_passed"] is True

    def test_nonexistent_path_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Path does not exist"):
            self.validator.validate_code_quality([str(tmp_path / "nonexistent")])


# ---------------------------------------------------------------------------
# check_black_formatting
# ---------------------------------------------------------------------------

class TestCheckBlackFormatting:

    def setup_method(self):
        self.validator = CodeQualityValidator()

    def test_empty_paths_returns_pass(self):
        passed, errors = self.validator.check_black_formatting([])
        assert passed is True
        assert errors == []

    def test_black_pass(self):
        with patch("subprocess.run", return_value=_sp_result(returncode=0)):
            passed, errors = self.validator.check_black_formatting(["src/"])
        assert passed is True
        assert errors == []

    def test_black_fail_parses_reformat_lines(self):
        stdout = "would reformat src/foo.py\nwould reformat src/bar.py\n"
        with patch("subprocess.run", return_value=_sp_result(returncode=1, stdout=stdout)):
            passed, errors = self.validator.check_black_formatting(["src/"])
        assert passed is False
        assert "src/foo.py" in errors
        assert "src/bar.py" in errors

    def test_black_fail_stderr_also_parsed(self):
        stderr = "would reformat src/baz.py\n"
        with patch("subprocess.run", return_value=_sp_result(returncode=1, stderr=stderr)):
            passed, errors = self.validator.check_black_formatting(["src/"])
        assert "src/baz.py" in errors

    def test_black_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("black", 60)):
            passed, errors = self.validator.check_black_formatting(["src/"])
        assert passed is False
        assert "timed out" in errors[0]

    def test_black_not_installed(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            passed, errors = self.validator.check_black_formatting(["src/"])
        assert passed is False
        assert "not installed" in errors[0]

    def test_black_generic_exception(self):
        with patch("subprocess.run", side_effect=OSError("disk full")):
            passed, errors = self.validator.check_black_formatting(["src/"])
        assert passed is False
        assert "black check failed" in errors[0]

    def test_black_no_reformat_lines_when_returncode_nonzero(self):
        """Non-zero returncode but no 'would reformat' lines → empty error list."""
        with patch("subprocess.run", return_value=_sp_result(returncode=1, stdout="error: syntax\n")):
            passed, errors = self.validator.check_black_formatting(["src/"])
        assert passed is False
        assert errors == []


# ---------------------------------------------------------------------------
# check_ruff_linting
# ---------------------------------------------------------------------------

class TestCheckRuffLinting:

    def setup_method(self):
        self.validator = CodeQualityValidator()

    def test_empty_paths_returns_pass(self):
        passed, errors = self.validator.check_ruff_linting([])
        assert passed is True
        assert errors == []

    def test_ruff_pass(self):
        with patch("subprocess.run", return_value=_sp_result(returncode=0)):
            passed, errors = self.validator.check_ruff_linting(["src/"])
        assert passed is True
        assert errors == []

    def test_ruff_fail_parses_errors(self):
        stdout = "src/foo.py:1:1: E501 line too long\nsrc/bar.py:2:3: F401 unused import\n"
        with patch("subprocess.run", return_value=_sp_result(returncode=1, stdout=stdout)):
            passed, errors = self.validator.check_ruff_linting(["src/"])
        assert passed is False
        assert any("E501" in e for e in errors)
        assert any("F401" in e for e in errors)

    def test_ruff_skips_found_lines(self):
        """Lines starting with 'Found' are filtered out."""
        stdout = "Found 2 errors.\nsrc/foo.py:1:1: E501 line too long\n"
        with patch("subprocess.run", return_value=_sp_result(returncode=1, stdout=stdout)):
            passed, errors = self.validator.check_ruff_linting(["src/"])
        assert not any("Found" in e for e in errors)

    def test_ruff_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("ruff", 60)):
            passed, errors = self.validator.check_ruff_linting(["src/"])
        assert passed is False
        assert "timed out" in errors[0]

    def test_ruff_not_installed(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            passed, errors = self.validator.check_ruff_linting(["src/"])
        assert passed is False
        assert "not installed" in errors[0]

    def test_ruff_generic_exception(self):
        with patch("subprocess.run", side_effect=RuntimeError("oops")):
            passed, errors = self.validator.check_ruff_linting(["src/"])
        assert passed is False
        assert "ruff check failed" in errors[0]


# ---------------------------------------------------------------------------
# check_type_annotations
# ---------------------------------------------------------------------------

class TestCheckTypeAnnotations:

    def setup_method(self):
        self.validator = CodeQualityValidator()

    def test_empty_modules_returns_pass(self):
        passed, errors = self.validator.check_type_annotations([])
        assert passed is True
        assert errors == []

    def test_mypy_pass(self):
        with patch("subprocess.run", return_value=_sp_result(returncode=0)):
            passed, errors = self.validator.check_type_annotations(["server.py"])
        assert passed is True
        assert errors == []

    def test_mypy_fail_parses_error_lines(self):
        stdout = "server.py:10: error: Argument 1 has wrong type\nfoo.py:5: error: Missing return\n"
        with patch("subprocess.run", return_value=_sp_result(returncode=1, stdout=stdout)):
            passed, errors = self.validator.check_type_annotations(["server.py"])
        assert passed is False
        assert any("Argument 1" in e for e in errors)
        assert any("Missing return" in e for e in errors)

    def test_mypy_fail_filters_non_error_lines(self):
        stdout = "server.py:10: error: Bad type\nSuccess: 0 errors\n"
        with patch("subprocess.run", return_value=_sp_result(returncode=1, stdout=stdout)):
            passed, errors = self.validator.check_type_annotations(["server.py"])
        # "Success: 0 errors" doesn't have "error:" so should be excluded
        assert len(errors) == 1
        assert "Bad type" in errors[0]

    def test_mypy_stderr_errors_included(self):
        stderr = "protocol.py:1: error: Import failed\n"
        with patch("subprocess.run", return_value=_sp_result(returncode=1, stderr=stderr)):
            passed, errors = self.validator.check_type_annotations(["protocol.py"])
        assert any("Import failed" in e for e in errors)

    def test_mypy_timeout(self):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("mypy", 120)):
            passed, errors = self.validator.check_type_annotations(["server.py"])
        assert passed is False
        assert "timed out" in errors[0]

    def test_mypy_not_installed(self):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            passed, errors = self.validator.check_type_annotations(["server.py"])
        assert passed is False
        assert "not installed" in errors[0]

    def test_mypy_generic_exception(self):
        with patch("subprocess.run", side_effect=RuntimeError("crash")):
            passed, errors = self.validator.check_type_annotations(["server.py"])
        assert passed is False
        assert "mypy check failed" in errors[0]


# ---------------------------------------------------------------------------
# measure_complexity
# ---------------------------------------------------------------------------

class TestMeasureComplexity:

    def setup_method(self):
        self.validator = CodeQualityValidator()

    def test_single_python_file(self, tmp_path):
        py_file = tmp_path / "foo.py"
        py_file.write_text("\ndef a():\n    pass\n\ndef b():\n    pass\n\nclass MyClass:\n    pass\n")

        metrics = self.validator.measure_complexity(str(py_file))
        assert metrics["total_functions"] == 2
        assert metrics["total_classes"] == 1

    def test_directory_with_python_files(self, tmp_path):
        (tmp_path / "a.py").write_text("\ndef f():\n    pass\n")
        (tmp_path / "b.py").write_text("\ndef g():\n    pass\n\nclass C:\n    pass\n")

        metrics = self.validator.measure_complexity(str(tmp_path))
        assert metrics["total_functions"] == 2
        assert metrics["total_classes"] == 1

    def test_string_input_converted_to_list(self, tmp_path):
        py_file = tmp_path / "x.py"
        py_file.write_text("\ndef h():\n    pass\n")

        metrics = self.validator.measure_complexity(str(py_file))
        assert metrics["total_functions"] == 1

    def test_list_input_works(self, tmp_path):
        py_file = tmp_path / "x.py"
        py_file.write_text("\ndef h():\n    pass\n")

        metrics = self.validator.measure_complexity([str(py_file)])
        assert metrics["total_functions"] == 1

    def test_non_py_file_skipped(self, tmp_path):
        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("\ndef not_a_function():\n    pass\n")

        metrics = self.validator.measure_complexity(str(txt_file))
        assert metrics["total_functions"] == 0

    def test_nonexistent_path_skipped(self, tmp_path):
        metrics = self.validator.measure_complexity(str(tmp_path / "nonexistent.py"))
        assert metrics["total_functions"] == 0

    def test_empty_paths_returns_zero_metrics(self):
        metrics = self.validator.measure_complexity([])
        assert metrics["total_functions"] == 0
        assert metrics["total_classes"] == 0

    def test_unreadable_file_is_silently_skipped(self, tmp_path):
        """Exception opening a file is caught and skipped — metrics stay at zero."""
        py_file = tmp_path / "bad.py"
        py_file.write_text("\ndef f(): pass\n")

        with patch("builtins.open", side_effect=OSError("permission denied")):
            metrics = self.validator.measure_complexity(str(py_file))

        # Silently skipped — counters unchanged from zero
        assert metrics["total_functions"] == 0


# ---------------------------------------------------------------------------
# _extract_public_modules
# ---------------------------------------------------------------------------

class TestExtractPublicModules:

    def setup_method(self):
        self.validator = CodeQualityValidator()

    def test_finds_server_and_protocol(self, tmp_path):
        """If src/iris_pgwire/server.py and protocol.py exist, both are returned."""
        src_dir = tmp_path / "src" / "iris_pgwire"
        src_dir.mkdir(parents=True)
        (src_dir / "server.py").touch()
        (src_dir / "protocol.py").touch()

        modules = self.validator._extract_public_modules([str(tmp_path / "src")])
        assert any("server.py" in m for m in modules)
        assert any("protocol.py" in m for m in modules)

    def test_missing_server_py_not_included(self, tmp_path):
        src_dir = tmp_path / "src" / "iris_pgwire"
        src_dir.mkdir(parents=True)
        (src_dir / "protocol.py").touch()
        # server.py does not exist

        modules = self.validator._extract_public_modules([str(tmp_path / "src")])
        assert not any("server.py" in m for m in modules)
        assert any("protocol.py" in m for m in modules)

    def test_non_src_path_returns_empty(self, tmp_path):
        other_dir = tmp_path / "other"
        other_dir.mkdir()

        modules = self.validator._extract_public_modules([str(other_dir)])
        assert modules == []

    def test_empty_paths_returns_empty(self):
        modules = self.validator._extract_public_modules([])
        assert modules == []


# ---------------------------------------------------------------------------
# _count_python_files
# ---------------------------------------------------------------------------

class TestCountPythonFiles:

    def setup_method(self):
        self.validator = CodeQualityValidator()

    def test_counts_single_py_file(self, tmp_path):
        (tmp_path / "foo.py").touch()
        assert self.validator._count_python_files([str(tmp_path / "foo.py")]) == 1

    def test_counts_py_files_in_directory(self, tmp_path):
        (tmp_path / "a.py").touch()
        (tmp_path / "b.py").touch()
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "c.py").touch()

        assert self.validator._count_python_files([str(tmp_path)]) == 3

    def test_non_py_file_not_counted(self, tmp_path):
        (tmp_path / "notes.txt").touch()
        assert self.validator._count_python_files([str(tmp_path / "notes.txt")]) == 0

    def test_nonexistent_path_returns_zero(self, tmp_path):
        count = self.validator._count_python_files([str(tmp_path / "nonexistent")])
        assert count == 0

    def test_multiple_paths_summed(self, tmp_path):
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        (dir_a / "x.py").touch()
        (dir_b / "y.py").touch()
        (dir_b / "z.py").touch()

        assert self.validator._count_python_files([str(dir_a), str(dir_b)]) == 3

    def test_empty_paths_returns_zero(self):
        assert self.validator._count_python_files([]) == 0

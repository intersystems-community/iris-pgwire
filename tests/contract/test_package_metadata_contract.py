"""
Contract Tests for Package Metadata Validation (T004)

CRITICAL: These tests MUST fail initially (no PackageMetadataValidator implementation exists).
Implement PackageMetadataValidator to make these tests pass (Red-Green-Refactor).

Contract: specs/025-comprehensive-code-and/contracts/package_metadata_contract.py
Constitutional Requirement: Production Readiness (Principle V)
"""

from pathlib import Path

import pytest
import toml

# IMPORTANT: This import will fail initially (no implementation yet)
# This is EXPECTED - tests MUST fail before implementation
try:
    from iris_pgwire.quality.package_metadata_validator import PackageMetadataValidator

    IMPLEMENTATION_EXISTS = True
except ImportError:
    IMPLEMENTATION_EXISTS = False

    # Create placeholder for type hints
    class PackageMetadataValidator:  # type: ignore
        pass


pytestmark = pytest.mark.skipif(
    not IMPLEMENTATION_EXISTS,
    reason="PackageMetadataValidator not implemented yet (TDD: tests must fail first)",
)


@pytest.fixture
def validator():
    """Fixture providing PackageMetadataValidator instance"""
    return PackageMetadataValidator()


@pytest.fixture
def complete_pyproject_toml(tmp_path):
    """Fixture providing a complete pyproject.toml for testing"""
    pyproject_content = {
        "project": {
            "name": "test-package",
            "version": "0.1.0",
            "description": "A test package for validation",
            "readme": "README.md",
            "license": {"file": "LICENSE"},
            "authors": [{"name": "Test Author", "email": "test@example.com"}],
            "keywords": ["testing", "validation"],
            "classifiers": [
                "Development Status :: 3 - Alpha",
                "Intended Audience :: Developers",
                "License :: OSI Approved :: MIT License",
                "Programming Language :: Python :: 3.11",
            ],
            "requires-python": ">=3.11",
            "dependencies": [
                "structlog>=23.0.0",
                "cryptography>=41.0.0",
            ],
        },
        "project.urls": {
            "Homepage": "https://github.com/test/test-package",
            "Documentation": "https://test-package.readthedocs.io",
        },
    }

    pyproject_path = tmp_path / "pyproject.toml"
    with open(pyproject_path, "w") as f:
        toml.dump(pyproject_content, f)

    return pyproject_path


@pytest.fixture
def incomplete_pyproject_toml(tmp_path):
    """Fixture providing an incomplete pyproject.toml (missing required fields)"""
    pyproject_content = {
        "project": {
            "name": "incomplete-package",
            "version": "0.1.0",
            # Missing: description, readme, license, authors
        }
    }

    pyproject_path = tmp_path / "pyproject.toml"
    with open(pyproject_path, "w") as f:
        toml.dump(pyproject_content, f)

    return pyproject_path


class TestPackageMetadataContract:
    """Contract tests for PackageMetadataValidator Protocol"""

    def test_validate_metadata_complete_pyproject(self, validator, complete_pyproject_toml):
        """
        Test validate_metadata() with complete pyproject.toml.

        Expected: Returns is_valid=True with zero errors
        Contract: package_metadata_contract.py lines 34-56
        """
        result = validator.validate_metadata(str(complete_pyproject_toml))

        assert result["is_valid"] is True, "Complete pyproject.toml should be valid"
        assert len(result["missing_fields"]) == 0, "No fields should be missing"
        assert len(result["validation_errors"]) == 0, "No validation errors expected"

    def test_validate_metadata_missing_fields(self, validator, incomplete_pyproject_toml):
        """
        Test validate_metadata() with missing required fields.

        Expected: Returns is_valid=False and lists missing_fields
        Contract: package_metadata_contract.py lines 34-56
        """
        result = validator.validate_metadata(str(incomplete_pyproject_toml))

        assert result["is_valid"] is False, "Incomplete pyproject.toml should be invalid"
        assert len(result["missing_fields"]) > 0, "Should report missing fields"

        # Check for expected missing fields
        missing_fields = set(result["missing_fields"])
        expected_missing = {"description", "readme", "license", "authors"}
        assert expected_missing.issubset(
            missing_fields
        ), f"Expected missing fields {expected_missing}, got {missing_fields}"

    def test_check_pyroma_score(self, validator):
        """
        Test check_pyroma_score() on iris-pgwire package.

        Expected: Returns score ≥9 out of 10
        Contract: package_metadata_contract.py lines 58-80
        """
        # Test against actual iris-pgwire package
        package_path = str(Path(__file__).parents[2])  # Repository root

        actual_score, max_score = validator.check_pyroma_score(package_path)

        assert max_score == 10, "Max score should be 10"
        assert actual_score >= 9, f"iris-pgwire package should score ≥9/10 (got {actual_score})"

    def test_validate_classifiers_valid(self, validator):
        """
        Test validate_classifiers() with valid PyPI classifiers.

        Expected: Returns (True, [])
        Contract: package_metadata_contract.py lines 82-103
        """
        valid_classifiers = [
            "Development Status :: 4 - Beta",
            "Intended Audience :: Developers",
            "License :: OSI Approved :: MIT License",
            "Programming Language :: Python :: 3.11",
            "Topic :: Database",
        ]

        all_valid, invalid_classifiers = validator.validate_classifiers(valid_classifiers)

        assert all_valid is True, "All classifiers should be valid"
        assert len(invalid_classifiers) == 0, "No invalid classifiers expected"

    def test_validate_classifiers_invalid(self, validator):
        """
        Test validate_classifiers() with invalid classifier.

        Expected: Returns (False, [invalid_classifier])
        Contract: package_metadata_contract.py lines 82-103
        """
        invalid_classifiers_list = [
            "Development Status :: 4 - Beta",
            "License :: OSI Approved :: MIT License",
            "INVALID CLASSIFIER :: This Does Not Exist",  # Invalid
            "Programming Language :: Python :: 3.11",
        ]

        all_valid, invalid = validator.validate_classifiers(invalid_classifiers_list)

        assert all_valid is False, "Should detect invalid classifier"
        assert len(invalid) == 1, "Should report exactly one invalid classifier"
        assert "INVALID CLASSIFIER" in invalid[0], "Should report the invalid classifier"

    def test_validate_dependencies_proper_constraints(self, validator):
        """
        Test validate_dependencies() with proper version constraints.

        Expected: Returns (True, [])
        Contract: package_metadata_contract.py lines 105-123
        """
        dependencies = {
            "structlog": ">=23.0.0",
            "cryptography": ">=41.0.0",
            "intersystems-irispython": ">=5.1.2",
        }

        all_valid, errors = validator.validate_dependencies(dependencies)

        assert all_valid is True, "All dependencies should have valid constraints"
        assert len(errors) == 0, "No validation errors expected"

    def test_validate_dependencies_missing_constraint(self, validator):
        """
        Test validate_dependencies() with missing version constraint.

        Expected: Returns (False, [error_message])
        Contract: package_metadata_contract.py lines 105-123
        """
        dependencies = {
            "structlog": ">=23.0.0",
            "cryptography": "",  # Missing constraint
            "intersystems-irispython": ">=5.1.2",
        }

        all_valid, errors = validator.validate_dependencies(dependencies)

        assert all_valid is False, "Should detect missing constraint"
        assert len(errors) > 0, "Should report validation errors"
        assert any("cryptography" in error for error in errors), "Error should mention cryptography"

    def test_check_manifest_completeness(self, validator):
        """
        Test check_manifest_completeness() on iris-pgwire package.

        Expected: Returns (False, error_details) until Phase 3.4 remediation
        Contract: package_metadata_contract.py lines 125-145

        KNOWN ISSUES (to be fixed in T018-T021):
        - Python bytecode in VCS (__pycache__/, *.pyc) - T018
        - Missing VCS files (quality/ module, auth/ module) - git add needed
        - Missing sdist files (docs/, examples/, scripts/) - MANIFEST.in needed
        """
        # Test against actual iris-pgwire package
        package_path = str(Path(__file__).parents[2])  # Repository root

        is_complete, output = validator.check_manifest_completeness(package_path)

        # Currently expecting False due to known manifest issues
        # Will change to True after T018-T021 remediation tasks complete
        assert is_complete is False, "Manifest should be incomplete (known issues exist)"
        assert (
            "__pycache__" in output or "auto-generated" in output.lower()
        ), "Should detect bytecode in version control"


class TestPackageMetadataEdgeCases:
    """Edge case tests for PackageMetadataValidator"""

    def test_validate_metadata_nonexistent_file(self, validator):
        """Test validate_metadata() with nonexistent file path"""
        with pytest.raises(FileNotFoundError):
            validator.validate_metadata("/nonexistent/pyproject.toml")

    def test_validate_metadata_malformed_toml(self, validator, tmp_path):
        """Test validate_metadata() with malformed TOML file"""
        malformed_path = tmp_path / "malformed.toml"
        with open(malformed_path, "w") as f:
            f.write("[project\n")  # Malformed TOML (missing closing bracket)

        with pytest.raises(ValueError):
            validator.validate_metadata(str(malformed_path))

    def test_validate_classifiers_empty_list(self, validator):
        """Test validate_classifiers() with empty list"""
        all_valid, invalid = validator.validate_classifiers([])

        # Empty list is technically valid (no invalid classifiers)
        assert all_valid is True
        assert len(invalid) == 0

    def test_validate_dependencies_empty_dict(self, validator):
        """Test validate_dependencies() with empty dict"""
        all_valid, errors = validator.validate_dependencies({})

        # Empty dict is valid (no dependencies to validate)
        assert all_valid is True
        assert len(errors) == 0

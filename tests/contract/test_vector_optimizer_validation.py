"""
Contract Test: SQL Syntax Validation (FR-002)

REQUIREMENT: System MUST validate optimized SQL syntax before sending to IRIS
to prevent compiler crashes.

EXPECTED: These tests MUST FAIL before implementation (TDD).
"""
import pytest
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from iris_pgwire.vector_optimizer import VectorQueryOptimizer


class TestVectorOptimizerValidation:
    """Contract tests for SQL syntax validation"""

    def setup_method(self):
        """Initialize optimizer for each test"""
        self.optimizer = VectorQueryOptimizer()

    def test_valid_sql_passes_validation(self):
        """Valid IRIS SQL MUST pass validation (FR-002)"""
        sql = "SELECT id, VECTOR_COSINE(embedding, TO_VECTOR('[0.1,0.2,0.3]', FLOAT)) AS distance FROM vectors"

        # This assumes validate_sql() method exists (will fail initially)
        result = self.optimizer.validate_sql(sql)

        assert result.is_valid is True, \
            f"Valid SQL failed validation: {result.error_message}"
        assert result.has_brackets_in_vector_literals is True, \
            "Bracket detection failed for valid SQL"
        assert result.error_message is None

    def test_missing_brackets_fails_validation(self):
        """SQL with missing brackets MUST fail validation (FR-002)"""
        # Malformed: brackets stripped from vector literal
        sql = "SELECT id, VECTOR_COSINE(embedding, TO_VECTOR('0.1,0.2,0.3', FLOAT)) AS distance FROM vectors"

        result = self.optimizer.validate_sql(sql)

        assert result.is_valid is False, \
            "Validation passed for SQL with missing brackets!"
        assert result.has_brackets_in_vector_literals is False, \
            "Bracket detection incorrectly returned True"
        assert "bracket" in result.error_message.lower(), \
            f"Error message should mention brackets: {result.error_message}"

    def test_malformed_to_vector_fails_validation(self):
        """Malformed TO_VECTOR syntax MUST fail validation (FR-002)"""
        # Missing FLOAT parameter
        sql = "SELECT id, VECTOR_COSINE(embedding, TO_VECTOR('[0.1,0.2,0.3]')) AS distance FROM vectors"

        result = self.optimizer.validate_sql(sql)

        assert result.is_valid is False, \
            "Validation passed for malformed TO_VECTOR!"
        assert "to_vector" in result.error_message.lower() or "parameter" in result.error_message.lower()

    def test_multiple_vector_literals_validated(self):
        """SQL with multiple vector literals MUST validate all (FR-002)"""
        sql = """
        SELECT id,
               VECTOR_COSINE(embedding, TO_VECTOR('[0.1,0.2,0.3]', FLOAT)) AS dist1,
               VECTOR_L2(embedding, TO_VECTOR('[1.0,2.0,3.0]', FLOAT)) AS dist2
        FROM vectors
        """

        result = self.optimizer.validate_sql(sql)

        assert result.is_valid is True, \
            f"Valid multi-vector SQL failed: {result.error_message}"
        assert result.vector_literal_count == 2, \
            f"Expected 2 vector literals, got {result.vector_literal_count}"
        assert result.has_brackets_in_vector_literals is True

    def test_non_vector_sql_passes(self):
        """SQL without vector functions MUST pass validation (FR-002)"""
        sql = "SELECT id, label FROM vectors WHERE id = 1"

        result = self.optimizer.validate_sql(sql)

        assert result.is_valid is True, \
            "Non-vector SQL failed validation"
        assert result.vector_literal_count == 0, \
            "Found vector literals where none exist"
        # Validation should be skipped for non-vector queries
        assert result.validation_applied is False, \
            "Validation was applied to non-vector query"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

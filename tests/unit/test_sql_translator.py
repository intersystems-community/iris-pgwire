"""
Unit Tests for SQLTranslator Main Class (Feature 021)

Tests the main translator orchestrator.

CRITICAL: These tests MUST FAIL initially (TDD approach)
They will pass once T009 implementation is complete.
"""

import pytest


class TestSQLTranslator:
    """Unit tests for SQLTranslator main class"""

    @pytest.fixture
    def translator(self):
        """
        Get SQLTranslator instance.

        EXPECTED TO FAIL: Class doesn't exist yet.
        Will be implemented in T009.
        """
        from iris_pgwire.sql_translator import SQLTranslator

        return SQLTranslator()

    def test_normalize_sql_combines_both(self, translator):
        """normalize_sql() must apply both identifier and DATE normalization"""
        sql = "SELECT FirstName FROM Patients WHERE DateOfBirth = '1985-03-15'"
        normalized = translator.normalize_sql(sql, execution_path="direct")

        # Identifier normalization
        assert "FIRSTNAME" in normalized
        assert "PATIENTS" in normalized

        # DATE translation
        assert "TO_DATE('1985-03-15', 'YYYY-MM-DD')" in normalized

    def test_execution_path_parameter(self, translator):
        """execution_path parameter must be accepted"""
        sql = "SELECT 1"

        # All three execution paths should work
        direct = translator.normalize_sql(sql, execution_path="direct")
        vector = translator.normalize_sql(sql, execution_path="vector")
        external = translator.normalize_sql(sql, execution_path="external")

        # All should return normalized SQL (even if no changes)
        assert isinstance(direct, str)
        assert isinstance(vector, str)
        assert isinstance(external, str)

    def test_get_normalization_metrics(self, translator):
        """get_normalization_metrics() must return performance data"""
        sql = "SELECT FirstName, LastName FROM Patients"
        translator.normalize_sql(sql, execution_path="direct")

        metrics = translator.get_normalization_metrics()

        assert "normalization_time_ms" in metrics
        assert "identifier_count" in metrics
        assert "date_literal_count" in metrics
        assert "sla_violated" in metrics

        assert isinstance(metrics["normalization_time_ms"], float)
        assert isinstance(metrics["identifier_count"], int)
        assert metrics["identifier_count"] >= 3  # FirstName, LastName, Patients

    def test_malformed_sql_raises_valueerror(self, translator):
        """Malformed SQL should raise ValueError or pass through"""
        sql = "SELEC FROM"  # Invalid syntax

        # Implementation choice: either raise ValueError or pass through
        # For now, we'll just ensure it doesn't crash
        try:
            result = translator.normalize_sql(sql, execution_path="direct")
            # If it doesn't raise, it should return a string
            assert isinstance(result, str)
        except ValueError:
            # Raising ValueError is also acceptable
            pass

    def test_empty_sql_handling(self, translator):
        """Empty SQL should be handled gracefully"""
        empty_sql = ""
        result = translator.normalize_sql(empty_sql, execution_path="direct")

        # Should return empty string or raise ValueError
        assert isinstance(result, str)
        assert result == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

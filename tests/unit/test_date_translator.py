"""
Unit Tests for DATETranslator (Feature 021)

Tests the DATE literal translation component.

CRITICAL: These tests MUST FAIL initially (TDD approach)
They will pass once T008 implementation is complete.
"""

import pytest


class TestDATETranslator:
    """Unit tests for DATETranslator class"""

    @pytest.fixture
    def date_translator(self):
        """
        Get DATETranslator instance.

        EXPECTED TO FAIL: Class doesn't exist yet.
        Will be implemented in T008.
        """
        from iris_pgwire.sql_translator.date_translator import DATETranslator

        return DATETranslator()

    def test_translate_iso8601_date(self, date_translator):
        """ISO-8601 DATE literals must be wrapped in TO_DATE()"""
        sql = "WHERE DateOfBirth = '1985-03-15'"
        translated, count = date_translator.translate(sql)

        assert "TO_DATE('1985-03-15', 'YYYY-MM-DD')" in translated
        assert count == 1
        # Original format should be replaced
        assert "= '1985-03-15'" not in translated

    def test_date_in_insert_values(self, date_translator):
        """DATE literals in INSERT VALUES must be translated"""
        sql = "INSERT INTO Patients VALUES (1, 'John', '1985-03-15')"
        translated, count = date_translator.translate(sql)

        assert "TO_DATE('1985-03-15', 'YYYY-MM-DD')" in translated
        assert count == 1

    def test_date_in_where_clause(self, date_translator):
        """DATE literals in WHERE clause must be translated"""
        sql = "WHERE created >= '2024-01-01' AND updated <= '2024-12-31'"
        translated, count = date_translator.translate(sql)

        assert "TO_DATE('2024-01-01', 'YYYY-MM-DD')" in translated
        assert "TO_DATE('2024-12-31', 'YYYY-MM-DD')" in translated
        assert count == 2

    def test_skip_non_date_strings(self, date_translator):
        """Non-DATE strings must NOT be translated"""
        sql = "WHERE description = 'Born 1985-03-15 in NYC'"
        translated, count = date_translator.translate(sql)

        # Should NOT translate partial date in longer string
        assert "TO_DATE" not in translated
        assert count == 0
        assert "'Born 1985-03-15 in NYC'" in translated

    def test_skip_comments(self, date_translator):
        """DATE literals in comments must NOT be translated"""
        sql = "SELECT * FROM Patients -- Created '2024-01-01'"
        translated, count = date_translator.translate(sql)

        # Comment should remain unchanged
        assert "-- Created '2024-01-01'" in translated
        # Should NOT translate date in comment
        assert count == 0

    def test_is_valid_date_literal(self, date_translator):
        """is_valid_date_literal() must validate format correctly"""
        assert date_translator.is_valid_date_literal("'1985-03-15'") == True
        assert date_translator.is_valid_date_literal("'2024-12-31'") == True
        assert date_translator.is_valid_date_literal("'1985-03-15-extra'") == False
        assert date_translator.is_valid_date_literal("'not-a-date'") == False
        assert date_translator.is_valid_date_literal("'2024-13-01'") == False  # Invalid month


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

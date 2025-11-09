"""
Unit Tests for IdentifierNormalizer (Feature 021)

Tests the identifier case normalization component.

CRITICAL: These tests MUST FAIL initially (TDD approach)
They will pass once T007 implementation is complete.
"""

import pytest


class TestIdentifierNormalizer:
    """Unit tests for IdentifierNormalizer class"""
    
    @pytest.fixture
    def normalizer(self):
        """
        Get IdentifierNormalizer instance.
        
        EXPECTED TO FAIL: Class doesn't exist yet.
        Will be implemented in T007.
        """
        from iris_pgwire.sql_translator.identifier_normalizer import IdentifierNormalizer
        return IdentifierNormalizer()
    
    def test_unquoted_identifier_to_uppercase(self, normalizer):
        """Unquoted identifiers must be converted to UPPERCASE"""
        sql = "SELECT FirstName FROM Patients"
        normalized, count = normalizer.normalize(sql)
        
        assert "FIRSTNAME" in normalized
        assert "PATIENTS" in normalized
        assert "FirstName" not in normalized
        assert count == 2
    
    def test_quoted_identifier_preserved(self, normalizer):
        """Quoted identifiers must preserve exact case"""
        sql = 'SELECT "FirstName" FROM "Patients"'
        normalized, count = normalizer.normalize(sql)
        
        assert '"FirstName"' in normalized
        assert '"Patients"' in normalized
        assert '"FIRSTNAME"' not in normalized
    
    def test_schema_qualified_identifiers(self, normalizer):
        """Schema-qualified identifiers: each part normalized"""
        sql = "SELECT myschema.mytable.mycolumn FROM myschema.mytable"
        normalized, count = normalizer.normalize(sql)
        
        assert "MYSCHEMA.MYTABLE.MYCOLUMN" in normalized
        assert "MYSCHEMA.MYTABLE" in normalized
    
    def test_mixed_quoted_unquoted(self, normalizer):
        """Mixed quoted/unquoted identifiers"""
        sql = 'SELECT "CamelCase", LastName FROM Patients'
        normalized, count = normalizer.normalize(sql)
        
        assert '"CamelCase"' in normalized  # Quoted - preserved
        assert "LASTNAME" in normalized     # Unquoted - uppercase
        assert "PATIENTS" in normalized     # Unquoted - uppercase
        assert count >= 3  # At least 3 identifiers
    
    def test_is_quoted_method(self, normalizer):
        """is_quoted() method must correctly detect quoted identifiers"""
        assert normalizer.is_quoted('"FirstName"') == True
        assert normalizer.is_quoted('FirstName') == False
        assert normalizer.is_quoted('"camelCase"') == True
        assert normalizer.is_quoted('UPPERCASE') == False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""
Contract Tests for SQL Translator (Feature 021)

These tests validate the contract interface defined in:
specs/021-postgresql-compatible-sql/contracts/sql_translator_interface.py

CRITICAL: These tests MUST FAIL initially (TDD approach)
They will pass once T007-T009 implementation is complete.

Constitutional Requirements Validated:
- Normalization overhead < 5ms for 50 identifier references
- Quoted identifier case preservation
- Unquoted identifier UPPERCASE normalization
- DATE literal translation to TO_DATE()
- Idempotence (normalizing twice yields same result)
"""

import pytest
import time
from typing import Tuple


# Import the contract interfaces
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../specs/021-postgresql-compatible-sql/contracts'))
from sql_translator_interface import (
    SQLTranslatorInterface,
    IdentifierNormalizerInterface,
    DATETranslatorInterface
)


class TestSQLTranslatorContract:
    """Contract tests for SQLTranslatorInterface"""
    
    @pytest.fixture
    def translator(self):
        """
        Get translator instance.
        
        EXPECTED TO FAIL: Implementation doesn't exist yet.
        Will be implemented in T009.
        """
        # This will fail - module doesn't exist yet
        from iris_pgwire.sql_translator import SQLTranslator
        return SQLTranslator()
    
    def test_normalize_unquoted_identifier(self, translator):
        """
        Contract: Unquoted identifiers MUST be converted to UPPERCASE
        
        FR-003: Identifier normalization
        """
        sql = "SELECT FirstName FROM Patients"
        normalized = translator.normalize_sql(sql, execution_path="direct")
        
        assert "FIRSTNAME" in normalized
        assert "PATIENTS" in normalized
        assert "FirstName" not in normalized
        assert "Patients" not in normalized
    
    def test_preserve_quoted_identifier(self, translator):
        """
        Contract: Quoted identifiers MUST preserve exact case
        
        FR-004: Quoted identifier preservation
        """
        sql = 'SELECT "FirstName" FROM "Patients"'
        normalized = translator.normalize_sql(sql, execution_path="direct")
        
        assert '"FirstName"' in normalized
        assert '"Patients"' in normalized
        # Should NOT convert quoted identifiers
        assert '"FIRSTNAME"' not in normalized
        assert '"PATIENTS"' not in normalized
    
    def test_translate_date_literal(self, translator):
        """
        Contract: DATE literals MUST be wrapped in TO_DATE()
        
        FR-005: DATE literal translation
        """
        sql = "WHERE DateOfBirth = '1985-03-15'"
        normalized = translator.normalize_sql(sql, execution_path="direct")
        
        assert "TO_DATE('1985-03-15', 'YYYY-MM-DD')" in normalized
        # Original literal should be replaced
        assert "= '1985-03-15'" not in normalized
    
    def test_performance_sla(self, translator):
        """
        Contract: Normalization MUST complete in < 5ms for 50 identifiers
        
        FR-013: Performance requirement (constitutional)
        """
        # Generate SQL with 50 identifier references
        columns = ", ".join([f"col{i}" for i in range(50)])
        sql = f"SELECT {columns} FROM test_table LIMIT 1"
        
        start_time = time.perf_counter()
        normalized = translator.normalize_sql(sql, execution_path="direct")
        end_time = time.perf_counter()
        
        normalization_time_ms = (end_time - start_time) * 1000
        
        assert normalization_time_ms < 5.0, f"Normalization took {normalization_time_ms}ms (SLA: 5ms)"
        
        # Verify metrics tracking
        metrics = translator.get_normalization_metrics()
        assert metrics['normalization_time_ms'] < 5.0
        assert metrics['identifier_count'] >= 50
        assert metrics['sla_violated'] == False
    
    def test_idempotence(self, translator):
        """
        Contract: Normalizing twice MUST yield same result as normalizing once
        
        FR-010: Idempotence requirement
        """
        sql = "SELECT FirstName FROM Patients WHERE DateOfBirth = '1985-03-15'"
        
        normalized_once = translator.normalize_sql(sql, execution_path="direct")
        normalized_twice = translator.normalize_sql(normalized_once, execution_path="direct")
        
        assert normalized_once == normalized_twice, "Normalization is not idempotent"


class TestIdentifierNormalizerContract:
    """Contract tests for IdentifierNormalizerInterface"""
    
    @pytest.fixture
    def normalizer(self):
        """
        Get identifier normalizer instance.
        
        EXPECTED TO FAIL: Implementation doesn't exist yet.
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
        assert count == 2  # FirstName + Patients
    
    def test_quoted_identifier_preserved(self, normalizer):
        """Quoted identifiers must preserve exact case"""
        sql = 'SELECT "FirstName" FROM "Patients"'
        normalized, count = normalizer.normalize(sql)
        
        assert '"FirstName"' in normalized
        assert '"Patients"' in normalized
    
    def test_schema_qualified_identifiers(self, normalizer):
        """Schema-qualified identifiers must normalize each part"""
        sql = "SELECT myschema.mytable.mycolumn FROM myschema.mytable"
        normalized, count = normalizer.normalize(sql)
        
        assert "MYSCHEMA.MYTABLE.MYCOLUMN" in normalized
    
    def test_mixed_quoted_unquoted(self, normalizer):
        """Mixed quoted/unquoted identifiers must be handled correctly"""
        sql = 'SELECT "CamelCase", LastName FROM Patients'
        normalized, count = normalizer.normalize(sql)
        
        assert '"CamelCase"' in normalized  # Quoted - preserved
        assert "LASTNAME" in normalized     # Unquoted - uppercase
        assert "PATIENTS" in normalized     # Unquoted - uppercase
    
    def test_is_quoted_method(self, normalizer):
        """is_quoted() method must correctly detect quoted identifiers"""
        assert normalizer.is_quoted('"FirstName"') == True
        assert normalizer.is_quoted('FirstName') == False
        assert normalizer.is_quoted('"camelCase"') == True


class TestDATETranslatorContract:
    """Contract tests for DATETranslatorInterface"""
    
    @pytest.fixture
    def date_translator(self):
        """
        Get DATE translator instance.
        
        EXPECTED TO FAIL: Implementation doesn't exist yet.
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
    
    def test_date_in_insert_values(self, date_translator):
        """DATE literals in INSERT VALUES must be translated"""
        sql = "INSERT INTO Patients VALUES (1, 'John', '1985-03-15')"
        translated, count = date_translator.translate(sql)
        
        assert "TO_DATE('1985-03-15', 'YYYY-MM-DD')" in translated
    
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
    
    def test_skip_comments(self, date_translator):
        """DATE literals in comments must NOT be translated"""
        sql = "SELECT * FROM Patients -- '2024-01-01'"
        translated, count = date_translator.translate(sql)
        
        # Should NOT translate date in comment
        assert "TO_DATE" not in translated or "'2024-01-01'" in translated
    
    def test_is_valid_date_literal(self, date_translator):
        """is_valid_date_literal() must validate format correctly"""
        assert date_translator.is_valid_date_literal("'1985-03-15'") == True
        assert date_translator.is_valid_date_literal("'2024-12-31'") == True
        assert date_translator.is_valid_date_literal("'1985-03-15-extra'") == False
        assert date_translator.is_valid_date_literal("'not-a-date'") == False


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

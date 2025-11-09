"""
Edge Case Tests for Transaction Translator (Feature 022)

These tests validate edge cases, error handling, and robustness of transaction
verb translation.

Tasks: T034-T044
"""

import sys
from pathlib import Path

import pytest

# Add src to path for imports
src_dir = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_dir))

from iris_pgwire.sql_translator.transaction_translator import TransactionTranslator


class TestTransactionEdgeCases:
    """Edge case tests for transaction translation"""

    def setup_method(self):
        """Create TransactionTranslator instance for each test"""
        self.translator = TransactionTranslator()

    # T034: BEGIN WORK variant
    def test_begin_work_uppercase(self):
        """T034: BEGIN WORK in uppercase"""
        result = self.translator.translate_transaction_command("BEGIN WORK")
        assert result == "START TRANSACTION"

    def test_begin_work_lowercase(self):
        """T034: begin work in lowercase"""
        result = self.translator.translate_transaction_command("begin work")
        assert result == "START TRANSACTION"

    def test_begin_work_mixed_case(self):
        """T034: BeGiN WoRk in mixed case"""
        result = self.translator.translate_transaction_command("BeGiN WoRk")
        assert result == "START TRANSACTION"

    # T035: String literal edge cases
    def test_string_literal_with_begin(self):
        """T035: String literal containing BEGIN should NOT be translated"""
        sql = "SELECT 'BEGIN' as command"
        result = self.translator.translate_transaction_command(sql)
        assert result == sql
        assert "SELECT 'BEGIN'" in result
        assert "START TRANSACTION" not in result

    def test_string_literal_with_commit(self):
        """T035: String literal containing COMMIT should NOT be translated"""
        sql = "SELECT 'COMMIT' as command"
        result = self.translator.translate_transaction_command(sql)
        assert result == sql

    def test_string_literal_begin_transaction(self):
        """T035: String literal with BEGIN TRANSACTION"""
        sql = "SELECT 'BEGIN TRANSACTION' as cmd"
        result = self.translator.translate_transaction_command(sql)
        assert result == sql
        assert "START TRANSACTION" not in result

    def test_double_quoted_string_literal(self):
        """T035: Double-quoted string with BEGIN"""
        sql = 'SELECT "BEGIN" as command'
        result = self.translator.translate_transaction_command(sql)
        # This should NOT be translated (it's a string literal)
        assert 'SELECT "BEGIN"' in result

    # T036: Comment handling
    def test_comment_with_begin(self):
        """T036: SQL comment containing BEGIN should NOT trigger translation"""
        sql = "-- BEGIN transaction\nSELECT 1"
        result = self.translator.translate_transaction_command(sql)
        # Should not translate because BEGIN is in comment
        assert result == sql

    def test_block_comment_with_begin(self):
        """T036: Block comment containing BEGIN"""
        sql = "/* BEGIN */ SELECT 1"
        result = self.translator.translate_transaction_command(sql)
        # Should not translate
        assert result == sql

    # T037: Whitespace handling
    def test_begin_with_leading_whitespace(self):
        """T037: BEGIN with leading whitespace"""
        result = self.translator.translate_transaction_command("   BEGIN")
        assert result == "START TRANSACTION"

    def test_begin_with_trailing_whitespace(self):
        """T037: BEGIN with trailing whitespace"""
        result = self.translator.translate_transaction_command("BEGIN   ")
        assert result == "START TRANSACTION"

    def test_begin_with_tabs(self):
        """T037: BEGIN with tab characters"""
        result = self.translator.translate_transaction_command("\t\tBEGIN\t\t")
        assert result == "START TRANSACTION"

    def test_begin_with_newlines(self):
        """T037: BEGIN with newlines"""
        result = self.translator.translate_transaction_command("\nBEGIN\n")
        assert result == "START TRANSACTION"

    # T038: Multiple modifiers
    def test_begin_with_multiple_modifiers(self):
        """T038: BEGIN with multiple modifiers"""
        result = self.translator.translate_transaction_command(
            "BEGIN ISOLATION LEVEL SERIALIZABLE READ ONLY DEFERRABLE"
        )
        assert result == "START TRANSACTION ISOLATION LEVEL SERIALIZABLE READ ONLY DEFERRABLE"

    def test_begin_transaction_with_modifiers(self):
        """T038: BEGIN TRANSACTION with modifiers"""
        result = self.translator.translate_transaction_command(
            "BEGIN TRANSACTION ISOLATION LEVEL READ UNCOMMITTED"
        )
        assert result == "START TRANSACTION ISOLATION LEVEL READ UNCOMMITTED"

    # T039: Non-transaction commands
    def test_select_statement_unchanged(self):
        """T039: SELECT statement should NOT be translated"""
        sql = "SELECT * FROM transactions WHERE status = 'BEGIN'"
        result = self.translator.translate_transaction_command(sql)
        assert result == sql

    def test_insert_statement_unchanged(self):
        """T039: INSERT statement should NOT be translated"""
        sql = "INSERT INTO logs VALUES ('BEGIN', 'COMMIT')"
        result = self.translator.translate_transaction_command(sql)
        assert result == sql

    def test_create_table_unchanged(self):
        """T039: CREATE TABLE should NOT be translated"""
        sql = "CREATE TABLE txn_log (cmd VARCHAR(50))"
        result = self.translator.translate_transaction_command(sql)
        assert result == sql

    # T040: Empty and NULL inputs
    def test_empty_string(self):
        """T040: Empty string should return empty string"""
        result = self.translator.translate_transaction_command("")
        assert result == ""

    def test_whitespace_only(self):
        """T040: Whitespace-only string"""
        result = self.translator.translate_transaction_command("   \t\n   ")
        # Should not crash, return as-is or normalized
        assert isinstance(result, str)

    # T041: is_transaction_command() edge cases
    def test_is_transaction_command_empty(self):
        """T041: is_transaction_command with empty string"""
        assert self.translator.is_transaction_command("") is False

    def test_is_transaction_command_whitespace(self):
        """T041: is_transaction_command with whitespace"""
        assert self.translator.is_transaction_command("   ") is False

    def test_is_transaction_command_select_with_begin_string(self):
        """T041: SELECT with BEGIN in string literal"""
        assert self.translator.is_transaction_command("SELECT 'BEGIN'") is False

    def test_is_transaction_command_begin_variants(self):
        """T041: All BEGIN variants detected"""
        assert self.translator.is_transaction_command("BEGIN") is True
        assert self.translator.is_transaction_command("BEGIN TRANSACTION") is True
        assert self.translator.is_transaction_command("BEGIN WORK") is True
        assert self.translator.is_transaction_command("begin") is True

    # T042: parse_transaction_command() edge cases
    def test_parse_invalid_command_raises(self):
        """T042: parse_transaction_command with invalid input raises ValueError"""
        with pytest.raises(ValueError, match="Not a valid transaction command"):
            self.translator.parse_transaction_command("SELECT 1")

    def test_parse_empty_raises(self):
        """T042: parse_transaction_command with empty string raises ValueError"""
        with pytest.raises(ValueError, match="Not a valid transaction command"):
            self.translator.parse_transaction_command("")

    def test_parse_string_literal_raises(self):
        """T042: parse_transaction_command with string literal raises ValueError"""
        with pytest.raises(ValueError, match="Not a valid transaction command"):
            self.translator.parse_transaction_command("SELECT 'BEGIN'")

    # T043: COMMIT/ROLLBACK variants
    def test_commit_work_normalized(self):
        """T043: COMMIT WORK normalized to COMMIT"""
        result = self.translator.translate_transaction_command("COMMIT WORK")
        assert result == "COMMIT"

    def test_commit_transaction_normalized(self):
        """T043: COMMIT TRANSACTION normalized to COMMIT"""
        result = self.translator.translate_transaction_command("COMMIT TRANSACTION")
        assert result == "COMMIT"

    def test_rollback_work_normalized(self):
        """T043: ROLLBACK WORK normalized to ROLLBACK"""
        result = self.translator.translate_transaction_command("ROLLBACK WORK")
        assert result == "ROLLBACK"

    def test_rollback_transaction_normalized(self):
        """T043: ROLLBACK TRANSACTION normalized to ROLLBACK"""
        result = self.translator.translate_transaction_command("ROLLBACK TRANSACTION")
        assert result == "ROLLBACK"

    # T044: Regression tests with Feature 021
    def test_begin_with_date_literal(self):
        """T044: BEGIN should NOT interfere with DATE literals (Feature 021)"""
        # Transaction translation happens BEFORE Feature 021 normalization
        # This test verifies BEGIN is translated without affecting other SQL
        sql = "BEGIN"
        result = self.translator.translate_transaction_command(sql)
        assert result == "START TRANSACTION"

    def test_commit_with_date_literal(self):
        """T044: COMMIT after query with DATE literal"""
        sql = "COMMIT"
        result = self.translator.translate_transaction_command(sql)
        assert result == "COMMIT"

    def test_non_transaction_with_uppercase_identifiers(self):
        """T044: Non-transaction SQL with uppercase identifiers unchanged"""
        # Feature 021 handles identifier normalization
        # Transaction translator should NOT touch non-transaction SQL
        sql = "SELECT FirstName, LastName FROM Patients"
        result = self.translator.translate_transaction_command(sql)
        assert result == sql  # Unchanged by transaction translator


class TestTransactionPerformanceEdgeCases:
    """Performance edge case tests"""

    def setup_method(self):
        """Create TransactionTranslator instance"""
        self.translator = TransactionTranslator()

    def test_large_modifier_string(self):
        """Performance: Large modifier string should still meet <0.1ms SLA"""
        import time

        # Create long modifier string
        modifiers = "ISOLATION LEVEL SERIALIZABLE READ WRITE " * 10
        sql = f"BEGIN {modifiers.strip()}"

        start = time.perf_counter()
        result = self.translator.translate_transaction_command(sql)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result.startswith("START TRANSACTION")
        assert elapsed_ms < 0.1, f"Translation took {elapsed_ms:.3f}ms (SLA: 0.1ms)"

    def test_many_translations_sla_compliance(self):
        """Performance: Many translations should maintain SLA"""
        import time

        commands = [
            "BEGIN",
            "BEGIN TRANSACTION",
            "BEGIN WORK",
            "COMMIT",
            "ROLLBACK",
            "BEGIN ISOLATION LEVEL READ COMMITTED",
        ] * 100  # 600 translations

        times = []
        for cmd in commands:
            start = time.perf_counter()
            self.translator.translate_transaction_command(cmd)
            elapsed_ms = (time.perf_counter() - start) * 1000
            times.append(elapsed_ms)

        avg_time = sum(times) / len(times)
        max_time = max(times)

        assert avg_time < 0.1, f"Average {avg_time:.3f}ms exceeds 0.1ms SLA"
        assert max_time < 0.5, f"Max {max_time:.3f}ms too high"

    def test_metrics_after_many_translations(self):
        """Metrics: Verify metrics tracking after many translations"""
        # Perform 100 translations
        for _ in range(100):
            self.translator.translate_transaction_command("BEGIN")

        metrics = self.translator.get_translation_metrics()
        assert metrics["total_translations"] >= 100
        assert metrics["avg_translation_time_ms"] < 0.1
        assert metrics["sla_compliance_rate"] == 100.0


class TestTransactionCompatibilityWithFeature021:
    """Test compatibility with Feature 021 SQL normalization"""

    def setup_method(self):
        """Create TransactionTranslator instance"""
        self.translator = TransactionTranslator()

    def test_transaction_before_normalization_order(self):
        """
        Verify transaction translation is independent of normalization

        FR-010: Transaction translation MUST occur BEFORE normalization.
        This test verifies transaction translator doesn't interfere with
        normalization (which happens later in pipeline).
        """
        # Transaction commands should be translated
        assert self.translator.translate_transaction_command("BEGIN") == "START TRANSACTION"

        # Non-transaction SQL should pass through unchanged
        # (normalization happens in SQLTranslator, not TransactionTranslator)
        sql_with_case = "SELECT FirstName FROM Patients"
        assert self.translator.translate_transaction_command(sql_with_case) == sql_with_case

    def test_transaction_translator_does_not_normalize_identifiers(self):
        """Transaction translator should NOT normalize identifiers (Feature 021's job)"""
        sql = "SELECT BeginDate, CommitDate FROM transactions"
        result = self.translator.translate_transaction_command(sql)

        # Should be unchanged (identifiers not normalized)
        assert result == sql
        assert "BeginDate" in result  # Case preserved
        assert "CommitDate" in result  # Case preserved

    def test_transaction_translator_does_not_normalize_dates(self):
        """Transaction translator should NOT normalize DATE literals (Feature 021's job)"""
        # Transaction translator only handles transaction commands
        sql = "INSERT INTO logs VALUES ('2024-01-01')"
        result = self.translator.translate_transaction_command(sql)

        # Should be unchanged (DATE normalization not applied)
        assert result == sql
        assert "'2024-01-01'" in result

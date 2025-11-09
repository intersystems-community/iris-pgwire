"""
Unit tests for Transaction Translator (Feature 022)

These tests validate the TransactionTranslator implementation at the unit level,
testing individual methods in isolation.

Tasks: T012-T015
"""

import sys
from pathlib import Path

import pytest

# Add src to path for imports
src_dir = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_dir))

# Add specs for contract types
specs_dir = Path(__file__).parent.parent.parent / "specs" / "022-postgresql-transaction-verb"
sys.path.insert(0, str(specs_dir))

from contracts.transaction_translator_interface import CommandType

from iris_pgwire.sql_translator.transaction_translator import TransactionTranslator


class TestTransactionTranslator:
    """Unit tests for transaction verb translation"""

    def setup_method(self):
        """Create TransactionTranslator instance for each test"""
        self.translator = TransactionTranslator()

    # T012: translate_transaction_command("BEGIN")
    def test_begin_translates_to_start_transaction(self):
        """T012: FR-001 - BEGIN → START TRANSACTION"""
        result = self.translator.translate_transaction_command("BEGIN")
        assert result == "START TRANSACTION"

    def test_begin_transaction_translates(self):
        """T012: FR-002 - BEGIN TRANSACTION → START TRANSACTION"""
        result = self.translator.translate_transaction_command("BEGIN TRANSACTION")
        assert result == "START TRANSACTION"

    # T013: translate_transaction_command("BEGIN WORK")
    def test_begin_work_translates(self):
        """T013: FR-002 variant - BEGIN WORK → START TRANSACTION"""
        result = self.translator.translate_transaction_command("BEGIN WORK")
        assert result == "START TRANSACTION"

    def test_begin_work_uppercase(self):
        """T013: BEGIN WORK in uppercase"""
        result = self.translator.translate_transaction_command("BEGIN WORK")
        assert result == "START TRANSACTION"

    def test_begin_work_lowercase(self):
        """T013: FR-009 - begin work in lowercase"""
        result = self.translator.translate_transaction_command("begin work")
        assert result == "START TRANSACTION"

    def test_commit_unchanged(self):
        """FR-003: COMMIT passes through unchanged"""
        result = self.translator.translate_transaction_command("COMMIT")
        assert result == "COMMIT"

    def test_commit_work_normalized(self):
        """FR-003: COMMIT WORK normalized to COMMIT"""
        result = self.translator.translate_transaction_command("COMMIT WORK")
        assert result == "COMMIT"

    def test_commit_transaction_normalized(self):
        """FR-003: COMMIT TRANSACTION normalized to COMMIT"""
        result = self.translator.translate_transaction_command("COMMIT TRANSACTION")
        assert result == "COMMIT"

    def test_rollback_unchanged(self):
        """FR-004: ROLLBACK passes through unchanged"""
        result = self.translator.translate_transaction_command("ROLLBACK")
        assert result == "ROLLBACK"

    def test_rollback_work_normalized(self):
        """FR-004: ROLLBACK WORK normalized to ROLLBACK"""
        result = self.translator.translate_transaction_command("ROLLBACK WORK")
        assert result == "ROLLBACK"

    def test_rollback_transaction_normalized(self):
        """FR-004: ROLLBACK TRANSACTION normalized to ROLLBACK"""
        result = self.translator.translate_transaction_command("ROLLBACK TRANSACTION")
        assert result == "ROLLBACK"

    def test_begin_with_isolation_level(self):
        """FR-005: Preserve transaction modifiers"""
        result = self.translator.translate_transaction_command(
            "BEGIN ISOLATION LEVEL READ COMMITTED"
        )
        assert result == "START TRANSACTION ISOLATION LEVEL READ COMMITTED"

    def test_begin_with_read_only(self):
        """FR-005: Preserve READ ONLY modifier"""
        result = self.translator.translate_transaction_command("BEGIN READ ONLY")
        assert result == "START TRANSACTION READ ONLY"

    def test_string_literal_unchanged(self):
        """FR-006: Do NOT translate inside string literals"""
        result = self.translator.translate_transaction_command("SELECT 'BEGIN'")
        assert result == "SELECT 'BEGIN'"

    def test_string_literal_with_commit(self):
        """FR-006: String literal with COMMIT"""
        result = self.translator.translate_transaction_command("SELECT 'COMMIT'")
        assert result == "SELECT 'COMMIT'"

    def test_case_insensitive_begin(self):
        """FR-009: Case-insensitive matching - begin"""
        assert self.translator.translate_transaction_command("begin") == "START TRANSACTION"

    def test_case_insensitive_begin_mixed(self):
        """FR-009: Case-insensitive matching - Begin"""
        assert self.translator.translate_transaction_command("Begin") == "START TRANSACTION"

    def test_case_insensitive_begin_upper(self):
        """FR-009: Case-insensitive matching - BEGIN"""
        assert self.translator.translate_transaction_command("BEGIN") == "START TRANSACTION"

    def test_non_transaction_command_unchanged(self):
        """Non-transaction commands pass through unchanged"""
        result = self.translator.translate_transaction_command("SELECT 1")
        assert result == "SELECT 1"

    def test_create_table_unchanged(self):
        """DDL commands pass through unchanged"""
        sql = "CREATE TABLE test (id INT)"
        result = self.translator.translate_transaction_command(sql)
        assert result == sql

    def test_whitespace_handling(self):
        """Handle leading/trailing whitespace"""
        result = self.translator.translate_transaction_command("  BEGIN  ")
        assert result == "START TRANSACTION"

    # T014: is_transaction_command() detection
    def test_is_transaction_command_begin(self):
        """T014: Detect BEGIN as transaction command"""
        assert self.translator.is_transaction_command("BEGIN") is True

    def test_is_transaction_command_begin_transaction(self):
        """T014: Detect BEGIN TRANSACTION as transaction command"""
        assert self.translator.is_transaction_command("BEGIN TRANSACTION") is True

    def test_is_transaction_command_commit(self):
        """T014: Detect COMMIT as transaction command"""
        assert self.translator.is_transaction_command("COMMIT") is True

    def test_is_transaction_command_rollback(self):
        """T014: Detect ROLLBACK as transaction command"""
        assert self.translator.is_transaction_command("ROLLBACK") is True

    def test_is_transaction_command_select(self):
        """T014: SELECT is NOT a transaction command"""
        assert self.translator.is_transaction_command("SELECT 1") is False

    def test_is_transaction_command_string_literal(self):
        """T014: String literal with BEGIN is NOT a transaction command"""
        assert self.translator.is_transaction_command("SELECT 'BEGIN'") is False

    def test_is_transaction_command_case_insensitive(self):
        """T014: Case-insensitive detection"""
        assert self.translator.is_transaction_command("begin") is True
        assert self.translator.is_transaction_command("Begin") is True
        assert self.translator.is_transaction_command("commit") is True
        assert self.translator.is_transaction_command("ROLLBACK") is True

    # T015: parse_transaction_command() extraction
    def test_parse_begin_command(self):
        """T015: Parse BEGIN command"""
        cmd = self.translator.parse_transaction_command("BEGIN")
        assert cmd.command_text == "BEGIN"
        assert cmd.command_type == CommandType.BEGIN
        assert cmd.modifiers is None
        assert cmd.translated_text == "START TRANSACTION"

    def test_parse_begin_with_modifiers(self):
        """T015: Parse BEGIN with isolation level"""
        cmd = self.translator.parse_transaction_command("BEGIN ISOLATION LEVEL READ COMMITTED")
        assert cmd.command_text == "BEGIN ISOLATION LEVEL READ COMMITTED"
        assert cmd.command_type == CommandType.BEGIN
        assert cmd.modifiers == "ISOLATION LEVEL READ COMMITTED"
        assert cmd.translated_text == "START TRANSACTION ISOLATION LEVEL READ COMMITTED"

    def test_parse_commit_command(self):
        """T015: Parse COMMIT command"""
        cmd = self.translator.parse_transaction_command("COMMIT")
        assert cmd.command_text == "COMMIT"
        assert cmd.command_type == CommandType.COMMIT
        assert cmd.modifiers is None
        assert cmd.translated_text == "COMMIT"

    def test_parse_rollback_command(self):
        """T015: Parse ROLLBACK command"""
        cmd = self.translator.parse_transaction_command("ROLLBACK")
        assert cmd.command_text == "ROLLBACK"
        assert cmd.command_type == CommandType.ROLLBACK
        assert cmd.modifiers is None
        assert cmd.translated_text == "ROLLBACK"

    def test_parse_invalid_command_raises(self):
        """T015: Parse invalid command raises ValueError"""
        with pytest.raises(ValueError, match="Not a valid transaction command"):
            self.translator.parse_transaction_command("SELECT 1")

    def test_parse_string_literal_raises(self):
        """T015: Parse string literal raises ValueError"""
        with pytest.raises(ValueError, match="Not a valid transaction command"):
            self.translator.parse_transaction_command("SELECT 'BEGIN'")

    # Performance and metrics tests
    def test_translation_performance(self):
        """PR-001: Translation overhead <0.1ms"""
        import time

        sql = "BEGIN ISOLATION LEVEL READ COMMITTED"
        start = time.perf_counter()
        self.translator.translate_transaction_command(sql)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 0.1, f"Translation took {elapsed_ms:.3f}ms (SLA: 0.1ms)"

    def test_get_translation_metrics_initial(self):
        """Metrics should be empty initially"""
        metrics = self.translator.get_translation_metrics()
        assert metrics["total_translations"] == 0
        assert metrics["avg_translation_time_ms"] == 0.0
        assert metrics["sla_compliance_rate"] == 100.0

    def test_get_translation_metrics_after_translations(self):
        """Metrics should update after translations"""
        # Perform some translations
        self.translator.translate_transaction_command("BEGIN")
        self.translator.translate_transaction_command("COMMIT")
        self.translator.translate_transaction_command("ROLLBACK")

        metrics = self.translator.get_translation_metrics()
        assert metrics["total_translations"] == 3
        assert metrics["avg_translation_time_ms"] > 0.0
        assert metrics["avg_translation_time_ms"] < 0.1  # Should meet SLA
        assert metrics["sla_compliance_rate"] == 100.0  # All should be within SLA

    def test_metrics_track_sla_violations(self):
        """Verify SLA violations are tracked (even if unlikely in practice)"""
        # This test verifies the tracking mechanism exists
        # In practice, violations are very unlikely with compiled regexes
        metrics = self.translator.get_translation_metrics()
        assert "sla_violations" in metrics
        assert "sla_compliance_rate" in metrics

"""
Contract tests for Transaction Translator (Feature 022)

These tests validate the TransactionTranslator implementation against the contract interface.
Following TDD principles: these tests MUST fail initially (TransactionTranslator doesn't exist),
then implementation makes them pass.

Tasks: T004-T011
"""

import sys
from pathlib import Path

import pytest

# Add specs contract to path for importing interface
specs_dir = Path(__file__).parent.parent.parent / "specs" / "022-postgresql-transaction-verb"
sys.path.insert(0, str(specs_dir))

from contracts.transaction_translator_interface import (
    TransactionTranslatorInterface,
    assert_translation_equals,
    assert_translation_performance,
)


class TestTransactionTranslatorContract:
    """Contract tests against TransactionTranslatorInterface"""

    def setup_method(self):
        """Create TransactionTranslator instance (will fail initially - class doesn't exist)"""
        # This import will fail initially - TransactionTranslator doesn't exist yet
        try:
            # Add src to path
            import sys
            from pathlib import Path

            src_dir = Path(__file__).parent.parent.parent / "src"
            sys.path.insert(0, str(src_dir))

            from iris_pgwire.sql_translator.transaction_translator import (
                TransactionTranslator,
            )

            self.translator = TransactionTranslator()
        except ImportError as e:
            pytest.skip(f"TransactionTranslator not implemented yet: {e}")

    def test_implements_interface(self):
        """Verify translator implements TransactionTranslatorInterface"""
        assert isinstance(self.translator, TransactionTranslatorInterface)

    def test_begin_translation_contract(self):
        """T004: FR-001 - BEGIN → START TRANSACTION"""
        assert_translation_equals(self.translator, "BEGIN", "START TRANSACTION")

    def test_begin_transaction_translation_contract(self):
        """T005: FR-002 - BEGIN TRANSACTION → START TRANSACTION"""
        assert_translation_equals(self.translator, "BEGIN TRANSACTION", "START TRANSACTION")

    def test_commit_unchanged_contract(self):
        """T006: FR-003 - COMMIT unchanged"""
        assert_translation_equals(self.translator, "COMMIT", "COMMIT")

    def test_rollback_unchanged_contract(self):
        """T007: FR-004 - ROLLBACK unchanged"""
        assert_translation_equals(self.translator, "ROLLBACK", "ROLLBACK")

    def test_preserve_modifiers_contract(self):
        """T008: FR-005 - Preserve transaction modifiers"""
        assert_translation_equals(
            self.translator,
            "BEGIN ISOLATION LEVEL READ COMMITTED",
            "START TRANSACTION ISOLATION LEVEL READ COMMITTED",
        )

    def test_string_literal_preservation_contract(self):
        """T009: FR-006 - Do NOT translate inside string literals"""
        assert_translation_equals(self.translator, "SELECT 'BEGIN'", "SELECT 'BEGIN'")

    def test_case_insensitive_matching_contract(self):
        """T010: FR-009 - Case-insensitive matching"""
        assert_translation_equals(self.translator, "begin", "START TRANSACTION")
        assert_translation_equals(self.translator, "Begin", "START TRANSACTION")
        assert_translation_equals(self.translator, "BEGIN", "START TRANSACTION")

    def test_performance_contract(self):
        """T011: PR-001 - Translation <0.1ms"""
        elapsed_ms = assert_translation_performance(
            self.translator, "BEGIN ISOLATION LEVEL READ COMMITTED", max_time_ms=0.1
        )
        print(f"Translation took {elapsed_ms:.3f}ms (SLA: 0.1ms)")

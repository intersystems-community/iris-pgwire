"""
Transaction Translator Contract Interface

This module defines the contract (interface) for PostgreSQL→IRIS transaction verb translation.
Contract tests will be written against this interface following TDD principles (tests first,
implementation second).

Feature: 022-postgresql-transaction-verb
Date: 2025-11-08
Status: Contract Definition (Phase 1 output)
"""

from typing import Dict, Any, Optional
from enum import Enum
from dataclasses import dataclass


class CommandType(Enum):
    """PostgreSQL transaction command types"""

    BEGIN = "BEGIN"
    START_TRANSACTION = "START TRANSACTION"
    COMMIT = "COMMIT"
    ROLLBACK = "ROLLBACK"
    NONE = None  # Not a transaction command


@dataclass
class TransactionCommand:
    """
    Ephemeral value object representing a transaction control command.

    Lifecycle: Single-use, destroyed after translation
    Thread Safety: Immutable after creation (dataclass frozen=True recommended in implementation)
    """

    command_text: str  # Original SQL from client
    command_type: CommandType  # Parsed command type
    modifiers: Optional[str]  # Transaction modifiers (e.g., "ISOLATION LEVEL READ COMMITTED")
    translated_text: str  # Translated SQL for IRIS execution


class TransactionTranslatorInterface:
    """
    Contract for PostgreSQL→IRIS transaction verb translation.

    This interface defines the required methods for translation functionality.
    Implementation must satisfy all functional requirements (FR-001 through FR-010)
    and performance requirements (PR-001 through PR-003).

    Constitutional Requirements:
    - Translation overhead MUST be <0.1ms (PR-001)
    - Must integrate with Feature 021 normalization pipeline (FR-010)
    - Must handle both Simple Query and Extended Protocol (FR-008)
    """

    def translate_transaction_command(self, sql: str) -> str:
        """
        Translate PostgreSQL transaction verbs to IRIS equivalents.

        Functional Requirements Satisfied:
        - FR-001: BEGIN → START TRANSACTION
        - FR-002: BEGIN TRANSACTION → START TRANSACTION
        - FR-003: COMMIT unchanged
        - FR-004: ROLLBACK unchanged
        - FR-005: Preserve transaction modifiers
        - FR-006: Do NOT translate inside string literals
        - FR-009: Case-insensitive matching

        Args:
            sql: SQL command string (may contain transaction control verb)

        Returns:
            Translated SQL with IRIS-compatible transaction verbs

        Raises:
            NotImplementedError: If unsupported transaction syntax detected

        Performance:
            Must complete in <0.1ms (constitutional requirement PR-001)

        Examples:
            >>> translator.translate_transaction_command("BEGIN")
            "START TRANSACTION"

            >>> translator.translate_transaction_command("BEGIN ISOLATION LEVEL READ COMMITTED")
            "START TRANSACTION ISOLATION LEVEL READ COMMITTED"

            >>> translator.translate_transaction_command("COMMIT")
            "COMMIT"

            >>> translator.translate_transaction_command("SELECT 'BEGIN'")
            "SELECT 'BEGIN'"  # Unchanged - inside string literal
        """
        raise NotImplementedError("Contract method - must be implemented")

    def is_transaction_command(self, sql: str) -> bool:
        """
        Check if SQL is a transaction control command.

        Detects: BEGIN, START TRANSACTION, COMMIT, ROLLBACK
        Does NOT detect: String literals, comments, PL/SQL blocks

        Args:
            sql: SQL command string

        Returns:
            True if sql is a transaction control command, False otherwise

        Performance:
            Must complete in <0.01ms (lightweight check)

        Examples:
            >>> translator.is_transaction_command("BEGIN")
            True

            >>> translator.is_transaction_command("SELECT * FROM users")
            False

            >>> translator.is_transaction_command("SELECT 'BEGIN'")
            False  # String literal
        """
        raise NotImplementedError("Contract method - must be implemented")

    def parse_transaction_command(self, sql: str) -> TransactionCommand:
        """
        Parse SQL into TransactionCommand value object.

        Extracts:
        - Command type (BEGIN, COMMIT, ROLLBACK, etc.)
        - Transaction modifiers (ISOLATION LEVEL, READ ONLY, etc.)
        - Translated equivalent for IRIS

        Args:
            sql: SQL command string

        Returns:
            TransactionCommand value object with parsed details

        Raises:
            ValueError: If SQL is not a valid transaction command

        Examples:
            >>> cmd = translator.parse_transaction_command("BEGIN ISOLATION LEVEL READ COMMITTED")
            >>> cmd.command_type
            CommandType.BEGIN
            >>> cmd.modifiers
            "ISOLATION LEVEL READ COMMITTED"
            >>> cmd.translated_text
            "START TRANSACTION ISOLATION LEVEL READ COMMITTED"
        """
        raise NotImplementedError("Contract method - must be implemented")

    def get_translation_metrics(self) -> Dict[str, Any]:
        """
        Return performance metrics for constitutional compliance monitoring.

        Required Metrics:
        - total_translations: Total number of translations performed
        - avg_translation_time_ms: Average translation time in milliseconds
        - max_translation_time_ms: Maximum translation time observed
        - sla_violations: Count of translations exceeding 0.1ms threshold
        - sla_compliance_rate: Percentage of translations within SLA

        Returns:
            Dictionary with performance metrics

        Performance:
            This method should be lightweight (<0.001ms)

        Example:
            >>> metrics = translator.get_translation_metrics()
            >>> metrics
            {
                'total_translations': 1523,
                'avg_translation_time_ms': 0.012,
                'max_translation_time_ms': 0.089,
                'sla_violations': 0,
                'sla_compliance_rate': 100.0
            }
        """
        raise NotImplementedError("Contract method - must be implemented")


# Contract Test Helpers


def assert_translation_equals(
    translator: TransactionTranslatorInterface, input_sql: str, expected_output: str
) -> None:
    """
    Helper function for contract tests - assert translation produces expected output.

    Args:
        translator: TransactionTranslator instance
        input_sql: Input SQL command
        expected_output: Expected translated SQL

    Raises:
        AssertionError: If translation doesn't match expected output
    """
    actual_output = translator.translate_transaction_command(input_sql)
    assert actual_output == expected_output, (
        f"Translation mismatch:\n"
        f"  Input: {input_sql}\n"
        f"  Expected: {expected_output}\n"
        f"  Actual: {actual_output}"
    )


def assert_translation_performance(
    translator: TransactionTranslatorInterface, input_sql: str, max_time_ms: float = 0.1
) -> float:
    """
    Helper function for contract tests - assert translation meets performance SLA.

    Args:
        translator: TransactionTranslator instance
        input_sql: Input SQL command
        max_time_ms: Maximum allowed time in milliseconds (default: 0.1ms constitutional limit)

    Returns:
        Actual translation time in milliseconds

    Raises:
        AssertionError: If translation exceeds max_time_ms
    """
    import time

    start_time = time.perf_counter()
    translator.translate_transaction_command(input_sql)
    elapsed_ms = (time.perf_counter() - start_time) * 1000

    assert elapsed_ms <= max_time_ms, (
        f"Performance SLA violation:\n"
        f"  SQL: {input_sql}\n"
        f"  Elapsed: {elapsed_ms:.3f}ms\n"
        f"  SLA Limit: {max_time_ms}ms"
    )

    return elapsed_ms


# Integration Contract


class IRISExecutorIntegration:
    """
    Contract for integration points with iris_executor.py.

    Transaction translation must be integrated at 3 points (FR-010):
    1. Direct execution path (_execute_embedded_async)
    2. External connection fallback (_execute_external_async)
    3. Vector query optimization (optimize_vector_query)
    """

    def execute_with_transaction_translation(
        self, sql: str, translator: TransactionTranslatorInterface
    ) -> str:
        """
        Execute SQL with transaction verb translation applied BEFORE Feature 021 normalization.

        Integration Order (FR-010):
        1. Transaction verb translation (Feature 022) ← THIS FEATURE
        2. SQL normalization (Feature 021)
        3. IRIS execution

        Args:
            sql: SQL command from client
            translator: TransactionTranslator instance

        Returns:
            SQL ready for Feature 021 normalization

        Example:
            >>> sql = "BEGIN ISOLATION LEVEL READ COMMITTED"
            >>> translated = integration.execute_with_transaction_translation(sql, translator)
            >>> translated
            "START TRANSACTION ISOLATION LEVEL READ COMMITTED"
            >>> # Now pass to Feature 021 normalization...
        """
        raise NotImplementedError("Contract method - must be implemented at integration points")


# Test Contract Validation

if __name__ == "__main__":
    print("Transaction Translator Contract Interface")
    print("=" * 60)
    print(f"CommandType enum: {list(CommandType)}")
    print(f"TransactionCommand fields: command_text, command_type, modifiers, translated_text")
    print(f"TransactionTranslatorInterface methods:")
    print(f"  - translate_transaction_command(sql) -> str")
    print(f"  - is_transaction_command(sql) -> bool")
    print(f"  - parse_transaction_command(sql) -> TransactionCommand")
    print(f"  - get_translation_metrics() -> Dict[str, Any]")
    print("\nContract tests will validate implementation against this interface.")
    print("Phase 1 complete - ready for Phase 2 (task generation via /tasks command)")

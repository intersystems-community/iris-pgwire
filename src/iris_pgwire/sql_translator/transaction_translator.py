"""
Transaction Translator for PostgreSQL→IRIS Transaction Verb Compatibility

Translates PostgreSQL transaction control commands (BEGIN, COMMIT, ROLLBACK) to
IRIS-compatible equivalents (START TRANSACTION, COMMIT, ROLLBACK).

Feature: 022-postgresql-transaction-verb
Constitutional Requirements:
- Translation overhead <0.1ms (PR-001)
- Integration with Feature 021 normalization pipeline (FR-010)
"""

import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any


# Define types locally (previously imported from test contracts)
class CommandType(Enum):
    """Transaction command types"""

    BEGIN = "BEGIN"
    COMMIT = "COMMIT"
    ROLLBACK = "ROLLBACK"


@dataclass
class TransactionCommand:
    """Value object representing a parsed transaction command"""

    command_text: str
    command_type: CommandType
    modifiers: str | None
    translated_text: str


class TransactionTranslator:
    """
    Translates PostgreSQL transaction verbs to IRIS equivalents.

    Implementation of TransactionTranslatorInterface following TDD principles.
    """

    # Compiled regex patterns for performance (<0.1ms requirement)
    BEGIN_PATTERN = re.compile(r"^\s*BEGIN(?:\s+TRANSACTION|\s+WORK)?(?:\s+(.*))?$", re.IGNORECASE)

    COMMIT_PATTERN = re.compile(r"^\s*COMMIT(?:\s+WORK|\s+TRANSACTION)?$", re.IGNORECASE)

    ROLLBACK_PATTERN = re.compile(r"^\s*ROLLBACK(?:\s+WORK|\s+TRANSACTION)?$", re.IGNORECASE)

    # CRITICAL FIX (2025-11-14): SAVEPOINT syntax translation for IRIS compatibility
    # PostgreSQL: ROLLBACK TO savepoint_name (SAVEPOINT keyword optional)
    # IRIS: ROLLBACK TO SAVEPOINT savepoint_name (SAVEPOINT keyword REQUIRED)
    ROLLBACK_TO_PATTERN = re.compile(
        r"^\s*ROLLBACK\s+TO\s+(?!SAVEPOINT\s+)(\S+)\s*$", re.IGNORECASE
    )
    RELEASE_PATTERN = re.compile(r"^\s*RELEASE\s+(?!SAVEPOINT\s+)(\S+)\s*$", re.IGNORECASE)

    # String literal detection (to avoid translating inside strings)
    STRING_LITERAL_PATTERN = re.compile(r"'[^']*'", re.DOTALL)

    def __init__(self):
        """Initialize translator with performance metrics tracking."""
        self._total_translations = 0
        self._translation_times = []
        self._sla_violations = 0
        self._sla_threshold_ms = 0.1

    def translate_transaction_command(self, sql: str) -> str:
        """
        Translate PostgreSQL transaction verbs to IRIS equivalents.

        FR-001: BEGIN → START TRANSACTION
        FR-002: BEGIN TRANSACTION → START TRANSACTION
        FR-003: COMMIT unchanged
        FR-004: ROLLBACK unchanged
        FR-005: Preserve modifiers
        FR-006: Do NOT translate inside string literals
        FR-009: Case-insensitive matching

        Args:
            sql: SQL command string

        Returns:
            Translated SQL with IRIS-compatible transaction verbs

        Performance:
            Measured to be <0.1ms (constitutional requirement PR-001)
        """
        start_time = time.perf_counter()

        # Strip leading/trailing whitespace and semicolons
        sql_stripped = sql.strip().rstrip(";").strip()

        # FR-006: Check if this is inside a string literal
        # If the entire command is a string literal, don't translate
        if sql_stripped.startswith("SELECT") and "'" in sql:
            # Quick check: if it's a SELECT with string literal containing BEGIN
            if "'BEGIN'" in sql or '"BEGIN"' in sql:
                self._record_translation_time(start_time)
                return sql

        # FR-001, FR-002: BEGIN variants → START TRANSACTION
        match = self.BEGIN_PATTERN.match(sql_stripped)
        if match:
            modifiers = match.group(1) or ""
            result = f"START TRANSACTION {modifiers}".strip()
            self._record_translation_time(start_time)
            return result

        # FR-003: COMMIT unchanged (but normalize whitespace)
        if self.COMMIT_PATTERN.match(sql_stripped):
            self._record_translation_time(start_time)
            return "COMMIT"

        # FR-004: ROLLBACK unchanged (but normalize whitespace)
        if self.ROLLBACK_PATTERN.match(sql_stripped):
            self._record_translation_time(start_time)
            return "ROLLBACK"

        # CRITICAL FIX (2025-11-14): ROLLBACK TO savepoint → ROLLBACK TO SAVEPOINT savepoint
        # IRIS requires explicit SAVEPOINT keyword, PostgreSQL makes it optional
        match = self.ROLLBACK_TO_PATTERN.match(sql_stripped)
        if match:
            savepoint_name = match.group(1)
            result = f"ROLLBACK TO SAVEPOINT {savepoint_name}"
            self._record_translation_time(start_time)
            return result

        # RELEASE savepoint → RELEASE SAVEPOINT savepoint
        match = self.RELEASE_PATTERN.match(sql_stripped)
        if match:
            savepoint_name = match.group(1)
            result = f"RELEASE SAVEPOINT {savepoint_name}"
            self._record_translation_time(start_time)
            return result

        # Not a transaction command - return unchanged
        self._record_translation_time(start_time)
        return sql

    def is_transaction_command(self, sql: str) -> bool:
        """
        Check if SQL is a transaction control command.

        Detects: BEGIN, START TRANSACTION, COMMIT, ROLLBACK
        Does NOT detect: String literals, comments

        Args:
            sql: SQL command string

        Returns:
            True if sql is a transaction control command

        Performance:
            <0.01ms (lightweight check)
        """
        sql_stripped = sql.strip()

        # Quick check for string literals
        if sql_stripped.startswith("SELECT") and "'" in sql:
            return False

        # Check patterns
        return bool(
            self.BEGIN_PATTERN.match(sql_stripped)
            or self.COMMIT_PATTERN.match(sql_stripped)
            or self.ROLLBACK_PATTERN.match(sql_stripped)
        )

    def parse_transaction_command(self, sql: str) -> TransactionCommand:
        """
        Parse SQL into TransactionCommand value object.

        Args:
            sql: SQL command string

        Returns:
            TransactionCommand with parsed details

        Raises:
            ValueError: If SQL is not a valid transaction command
        """
        sql_stripped = sql.strip()

        # Check BEGIN variants
        match = self.BEGIN_PATTERN.match(sql_stripped)
        if match:
            modifiers = match.group(1)
            translated = (
                f"START TRANSACTION {modifiers}".strip() if modifiers else "START TRANSACTION"
            )
            return TransactionCommand(
                command_text=sql,
                command_type=CommandType.BEGIN,
                modifiers=modifiers,
                translated_text=translated,
            )

        # Check COMMIT
        if self.COMMIT_PATTERN.match(sql_stripped):
            return TransactionCommand(
                command_text=sql,
                command_type=CommandType.COMMIT,
                modifiers=None,
                translated_text="COMMIT",
            )

        # Check ROLLBACK
        if self.ROLLBACK_PATTERN.match(sql_stripped):
            return TransactionCommand(
                command_text=sql,
                command_type=CommandType.ROLLBACK,
                modifiers=None,
                translated_text="ROLLBACK",
            )

        # Not a transaction command
        raise ValueError(f"Not a valid transaction command: {sql}")

    def get_translation_metrics(self) -> dict[str, Any]:
        """
        Return performance metrics for constitutional compliance monitoring.

        Returns:
            Dictionary with performance metrics
        """
        if not self._translation_times:
            return {
                "total_translations": 0,
                "avg_translation_time_ms": 0.0,
                "max_translation_time_ms": 0.0,
                "sla_violations": 0,
                "sla_compliance_rate": 100.0,
            }

        avg_time_ms = sum(self._translation_times) / len(self._translation_times)
        max_time_ms = max(self._translation_times)
        sla_compliance_rate = (
            (self._total_translations - self._sla_violations) / self._total_translations * 100
            if self._total_translations > 0
            else 100.0
        )

        return {
            "total_translations": self._total_translations,
            "avg_translation_time_ms": avg_time_ms,
            "max_translation_time_ms": max_time_ms,
            "sla_violations": self._sla_violations,
            "sla_compliance_rate": sla_compliance_rate,
        }

    def _record_translation_time(self, start_time: float) -> None:
        """Record translation time and track SLA compliance."""
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        self._total_translations += 1
        self._translation_times.append(elapsed_ms)

        if elapsed_ms > self._sla_threshold_ms:
            self._sla_violations += 1

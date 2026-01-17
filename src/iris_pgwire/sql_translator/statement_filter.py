"""
Statement Filter - Skip unsupported PostgreSQL statements (Feature 035)

Identifies and filters PostgreSQL statements that should be skipped for IRIS:
- CREATE TYPE ... AS ENUM (register enum, skip execution)
- DROP TYPE for registered enums (skip execution)
- ALTER TABLE ... ENABLE/DISABLE ROW LEVEL SECURITY (skip execution)
- CREATE POLICY / DROP POLICY (skip execution)

Constitutional Requirements:
- Return success to client (no-op)
- No SQL sent to IRIS for skipped statements
- Must happen early in translation pipeline
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .enum_registry import EnumTypeRegistry


class SkipReason(Enum):
    """Classification of why a statement was skipped."""

    NOT_SKIPPED = "not_skipped"
    CREATE_TYPE_ENUM = "create_type_enum"
    DROP_TYPE_ENUM = "drop_type_enum"
    RLS_ENABLE = "rls_enable"
    RLS_DISABLE = "rls_disable"
    CREATE_POLICY = "create_policy"
    DROP_POLICY = "drop_policy"


@dataclass
class FilterResult:
    """Result of statement filtering."""

    should_skip: bool
    reason: SkipReason
    command_tag: str  # PostgreSQL command tag for success response
    extracted_type_name: Optional[str] = None  # For CREATE TYPE, the type name to register


class StatementFilter:
    """
    Filters PostgreSQL statements that should be skipped for IRIS compatibility.

    Usage:
        filter = StatementFilter(enum_registry)
        result = filter.check(sql)
        if result.should_skip:
            if result.extracted_type_name:
                enum_registry.register(result.extracted_type_name)
            return success_response(result.command_tag)
    """

    # Compiled regex patterns for statement detection
    # CREATE TYPE ... AS ENUM
    _CREATE_TYPE_ENUM_PATTERN = re.compile(
        r'^\s*CREATE\s+TYPE\s+("?[\w.]+"?\.)?("?[\w]+"?)\s+AS\s+ENUM\s*\(', re.IGNORECASE
    )

    # DROP TYPE (need to check if registered)
    _DROP_TYPE_PATTERN = re.compile(
        r'^\s*DROP\s+TYPE\s+(?:IF\s+EXISTS\s+)?("?[\w.]+"?\.)?("?[\w]+"?)', re.IGNORECASE
    )

    # ALTER TABLE ... ENABLE ROW LEVEL SECURITY
    _RLS_ENABLE_PATTERN = re.compile(
        r"\bALTER\s+TABLE\b.*\bENABLE\s+ROW\s+LEVEL\s+SECURITY\b", re.IGNORECASE
    )

    # ALTER TABLE ... DISABLE ROW LEVEL SECURITY
    _RLS_DISABLE_PATTERN = re.compile(
        r"\bALTER\s+TABLE\b.*\bDISABLE\s+ROW\s+LEVEL\s+SECURITY\b", re.IGNORECASE
    )

    # CREATE POLICY
    _CREATE_POLICY_PATTERN = re.compile(r"^\s*CREATE\s+POLICY\s+", re.IGNORECASE)

    # DROP POLICY
    _DROP_POLICY_PATTERN = re.compile(r"^\s*DROP\s+POLICY\s+", re.IGNORECASE)

    def __init__(self, enum_registry: EnumTypeRegistry):
        """
        Initialize statement filter with enum registry.

        Args:
            enum_registry: Session-scoped enum type registry for DROP TYPE detection
        """
        self._enum_registry = enum_registry

    def check(self, sql: str) -> FilterResult:
        """
        Check if a SQL statement should be skipped.

        Args:
            sql: SQL statement to check

        Returns:
            FilterResult indicating whether to skip and why
        """
        if not sql or not sql.strip():
            return FilterResult(should_skip=False, reason=SkipReason.NOT_SKIPPED, command_tag="")

        # Check CREATE TYPE ... AS ENUM
        match = self._CREATE_TYPE_ENUM_PATTERN.search(sql)
        if match:
            # Extract type name (group 2 is the unqualified name)
            type_name = match.group(2)
            return FilterResult(
                should_skip=True,
                reason=SkipReason.CREATE_TYPE_ENUM,
                command_tag="CREATE TYPE",
                extracted_type_name=type_name,
            )

        # Check DROP TYPE for registered enums
        match = self._DROP_TYPE_PATTERN.search(sql)
        if match:
            type_name = match.group(2)
            if self._enum_registry.is_registered(type_name):
                return FilterResult(
                    should_skip=True, reason=SkipReason.DROP_TYPE_ENUM, command_tag="DROP TYPE"
                )

        # Check RLS ENABLE
        if self._RLS_ENABLE_PATTERN.search(sql):
            return FilterResult(
                should_skip=True, reason=SkipReason.RLS_ENABLE, command_tag="ALTER TABLE"
            )

        # Check RLS DISABLE
        if self._RLS_DISABLE_PATTERN.search(sql):
            return FilterResult(
                should_skip=True, reason=SkipReason.RLS_DISABLE, command_tag="ALTER TABLE"
            )

        # Check CREATE POLICY
        if self._CREATE_POLICY_PATTERN.search(sql):
            return FilterResult(
                should_skip=True, reason=SkipReason.CREATE_POLICY, command_tag="CREATE POLICY"
            )

        # Check DROP POLICY
        if self._DROP_POLICY_PATTERN.search(sql):
            return FilterResult(
                should_skip=True, reason=SkipReason.DROP_POLICY, command_tag="DROP POLICY"
            )

        # Not a skippable statement
        return FilterResult(should_skip=False, reason=SkipReason.NOT_SKIPPED, command_tag="")

"""
Error Handling for Unsupported IRIS Constructs

Implements hybrid strategy for handling unsupported IRIS SQL constructs with
constitutional compliance and graceful degradation patterns.

Constitutional Compliance: Transparent error reporting with fallback strategies.
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .models import (
    IssueSeverity,
    ParsedConstruct,
    PerformanceTimer,
)


class ErrorStrategy(Enum):
    """Error handling strategies for unsupported constructs"""

    FAIL_FAST = "fail_fast"  # Immediate failure on unsupported construct
    BEST_EFFORT = "best_effort"  # Continue with warnings
    PASSTHROUGH = "passthrough"  # Pass unsupported constructs unchanged
    SUBSTITUTE = "substitute"  # Replace with closest equivalent
    HYBRID = "hybrid"  # Adaptive strategy based on construct type


class UnsupportedReason(Enum):
    """Reasons why a construct might be unsupported"""

    NO_MAPPING = "no_mapping"  # No PostgreSQL equivalent exists
    COMPLEX_SYNTAX = "complex_syntax"  # Too complex to translate safely
    IRIS_SPECIFIC = "iris_specific"  # IRIS-only feature
    DEPRECATED = "deprecated"  # Deprecated IRIS construct
    LICENSING = "licensing"  # Requires specific IRIS license
    PERFORMANCE_RISK = "performance_risk"  # Translation would harm performance
    DATA_INTEGRITY = "data_integrity_risk"  # Translation might compromise data


@dataclass
class UnsupportedConstruct:
    """Information about an unsupported IRIS construct"""

    construct_name: str
    construct_type: str  # function, datatype, sql_construct, etc.
    reason: UnsupportedReason
    original_fragment: str
    position_start: int
    position_end: int
    severity: IssueSeverity
    suggested_alternative: str | None = None
    documentation_link: str | None = None
    workaround: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ErrorHandlingResult:
    """Result of error handling process"""

    success: bool
    modified_sql: str
    unsupported_constructs: list[UnsupportedConstruct]
    warnings: list[str]
    errors: list[str]
    fallback_used: bool
    strategy_applied: ErrorStrategy
    processing_time_ms: float


class IRISErrorHandler:
    """
    Error handler for unsupported IRIS constructs

    Features:
    - Multiple error handling strategies
    - Construct-specific fallback mechanisms
    - Constitutional compliance monitoring
    - Comprehensive error reporting
    - Adaptive error recovery
    """

    def __init__(self, default_strategy: ErrorStrategy = ErrorStrategy.HYBRID):
        """
        Initialize error handler

        Args:
            default_strategy: Default error handling strategy
        """
        self.default_strategy = default_strategy
        self.logger = logging.getLogger("iris_pgwire.sql_translator.error_handler")

        # Initialize error handling rules
        self._setup_error_rules()
        self._setup_fallback_mappings()

        # Performance tracking
        self._error_count = 0
        self._fallback_count = 0
        self._passthrough_count = 0

    def handle_unsupported_constructs(
        self,
        sql: str,
        parsed_constructs: list[ParsedConstruct],
        strategy: ErrorStrategy | None = None,
    ) -> ErrorHandlingResult:
        """
        Handle unsupported IRIS constructs in SQL

        Args:
            sql: Original SQL with potentially unsupported constructs
            parsed_constructs: List of parsed constructs from SQL
            strategy: Error handling strategy (uses default if None)

        Returns:
            Error handling result with modified SQL and diagnostics
        """
        with PerformanceTimer() as timer:
            strategy = strategy or self.default_strategy

            # Identify unsupported constructs
            unsupported_constructs = self._identify_unsupported_constructs(sql, parsed_constructs)

            if not unsupported_constructs:
                # No unsupported constructs found
                return ErrorHandlingResult(
                    success=True,
                    modified_sql=sql,
                    unsupported_constructs=[],
                    warnings=[],
                    errors=[],
                    fallback_used=False,
                    strategy_applied=strategy,
                    processing_time_ms=timer.elapsed_ms,
                )

            # Apply error handling strategy
            result = self._apply_error_strategy(sql, unsupported_constructs, strategy)
            result.processing_time_ms = timer.elapsed_ms

            # Update metrics
            self._update_error_metrics(result)

            return result

    def _identify_unsupported_constructs(
        self, sql: str, parsed_constructs: list[ParsedConstruct]
    ) -> list[UnsupportedConstruct]:
        """Identify constructs that are not supported"""
        unsupported = []

        for construct in parsed_constructs:
            unsupported_info = self._check_construct_support(construct, sql)
            if unsupported_info:
                unsupported.append(unsupported_info)

        # Check for additional unsupported patterns not caught by parser
        additional_unsupported = self._scan_for_unsupported_patterns(sql)
        unsupported.extend(additional_unsupported)

        return unsupported

    def _check_construct_support(
        self, construct: ParsedConstruct, sql: str
    ) -> UnsupportedConstruct | None:
        """Check if a parsed construct is supported"""
        construct_name = construct.construct_name.upper()

        # Check against known unsupported constructs
        if construct_name in self.unsupported_functions:
            reason_info = self.unsupported_functions[construct_name]
            return UnsupportedConstruct(
                construct_name=construct_name,
                construct_type=construct.construct_type,
                reason=reason_info["reason"],
                original_fragment=construct.original_text,
                position_start=construct.position_start,
                position_end=construct.position_end,
                severity=reason_info["severity"],
                suggested_alternative=reason_info.get("alternative"),
                documentation_link=reason_info.get("docs"),
                workaround=reason_info.get("workaround"),
            )

        # Check for licensing-dependent constructs
        if construct_name in self.licensing_dependent:
            return UnsupportedConstruct(
                construct_name=construct_name,
                construct_type=construct.construct_type,
                reason=UnsupportedReason.LICENSING,
                original_fragment=construct.original_text,
                position_start=construct.position_start,
                position_end=construct.position_end,
                severity=IssueSeverity.WARNING,
                suggested_alternative="Verify IRIS licensing for this feature",
                workaround="Contact InterSystems for licensing information",
            )

        return None

    def _scan_for_unsupported_patterns(self, sql: str) -> list[UnsupportedConstruct]:
        """Scan SQL for additional unsupported patterns"""
        unsupported = []
        sql_upper = sql.upper()

        # Check for unsupported SQL patterns
        for pattern, info in self.unsupported_patterns.items():
            matches = re.finditer(pattern, sql_upper, re.IGNORECASE)
            for match in matches:
                unsupported.append(
                    UnsupportedConstruct(
                        construct_name=info["name"],
                        construct_type=info["type"],
                        reason=info["reason"],
                        original_fragment=match.group(0),
                        position_start=match.start(),
                        position_end=match.end(),
                        severity=info["severity"],
                        suggested_alternative=info.get("alternative"),
                        workaround=info.get("workaround"),
                    )
                )

        return unsupported

    def _apply_error_strategy(
        self, sql: str, unsupported_constructs: list[UnsupportedConstruct], strategy: ErrorStrategy
    ) -> ErrorHandlingResult:
        """Apply error handling strategy to unsupported constructs"""

        if strategy == ErrorStrategy.FAIL_FAST:
            return self._handle_fail_fast(sql, unsupported_constructs)
        elif strategy == ErrorStrategy.BEST_EFFORT:
            return self._handle_best_effort(sql, unsupported_constructs)
        elif strategy == ErrorStrategy.PASSTHROUGH:
            return self._handle_passthrough(sql, unsupported_constructs)
        elif strategy == ErrorStrategy.SUBSTITUTE:
            return self._handle_substitute(sql, unsupported_constructs)
        elif strategy == ErrorStrategy.HYBRID:
            return self._handle_hybrid(sql, unsupported_constructs)
        else:
            # Default to best effort
            return self._handle_best_effort(sql, unsupported_constructs)

    def _handle_fail_fast(
        self, sql: str, unsupported_constructs: list[UnsupportedConstruct]
    ) -> ErrorHandlingResult:
        """Fail fast strategy - stop on first unsupported construct"""
        if unsupported_constructs:
            first_unsupported = unsupported_constructs[0]
            error_msg = f"Unsupported IRIS construct: {first_unsupported.construct_name} ({first_unsupported.reason.value})"

            return ErrorHandlingResult(
                success=False,
                modified_sql=sql,
                unsupported_constructs=unsupported_constructs,
                warnings=[],
                errors=[error_msg],
                fallback_used=False,
                strategy_applied=ErrorStrategy.FAIL_FAST,
                processing_time_ms=0.0,
            )

        return ErrorHandlingResult(
            success=True,
            modified_sql=sql,
            unsupported_constructs=[],
            warnings=[],
            errors=[],
            fallback_used=False,
            strategy_applied=ErrorStrategy.FAIL_FAST,
            processing_time_ms=0.0,
        )

    def _handle_best_effort(
        self, sql: str, unsupported_constructs: list[UnsupportedConstruct]
    ) -> ErrorHandlingResult:
        """Best effort strategy - continue with warnings"""
        warnings = []
        errors = []

        for construct in unsupported_constructs:
            if construct.severity == IssueSeverity.ERROR:
                errors.append(
                    f"Unsupported construct: {construct.construct_name} - {construct.reason.value}"
                )
            else:
                warnings.append(
                    f"Unsupported construct: {construct.construct_name} - {construct.reason.value}"
                )

        # Success if no critical errors
        success = not any(c.severity == IssueSeverity.ERROR for c in unsupported_constructs)

        return ErrorHandlingResult(
            success=success,
            modified_sql=sql,
            unsupported_constructs=unsupported_constructs,
            warnings=warnings,
            errors=errors,
            fallback_used=False,
            strategy_applied=ErrorStrategy.BEST_EFFORT,
            processing_time_ms=0.0,
        )

    def _handle_passthrough(
        self, sql: str, unsupported_constructs: list[UnsupportedConstruct]
    ) -> ErrorHandlingResult:
        """Passthrough strategy - leave unsupported constructs unchanged"""
        warnings = [
            f"Unsupported construct passed through: {c.construct_name}"
            for c in unsupported_constructs
        ]

        self._passthrough_count += len(unsupported_constructs)

        return ErrorHandlingResult(
            success=True,
            modified_sql=sql,
            unsupported_constructs=unsupported_constructs,
            warnings=warnings,
            errors=[],
            fallback_used=True,
            strategy_applied=ErrorStrategy.PASSTHROUGH,
            processing_time_ms=0.0,
        )

    def _handle_substitute(
        self, sql: str, unsupported_constructs: list[UnsupportedConstruct]
    ) -> ErrorHandlingResult:
        """Substitute strategy - replace with closest equivalents"""
        modified_sql = sql
        warnings = []
        errors = []
        fallback_used = False

        for construct in unsupported_constructs:
            fallback = self._get_fallback_mapping(construct)
            if fallback:
                # Apply substitution
                modified_sql = modified_sql.replace(construct.original_fragment, fallback)
                warnings.append(f"Substituted {construct.construct_name} with {fallback}")
                fallback_used = True
                self._fallback_count += 1
            else:
                errors.append(f"No substitution available for {construct.construct_name}")

        success = len(errors) == 0

        return ErrorHandlingResult(
            success=success,
            modified_sql=modified_sql,
            unsupported_constructs=unsupported_constructs,
            warnings=warnings,
            errors=errors,
            fallback_used=fallback_used,
            strategy_applied=ErrorStrategy.SUBSTITUTE,
            processing_time_ms=0.0,
        )

    def _handle_hybrid(
        self, sql: str, unsupported_constructs: list[UnsupportedConstruct]
    ) -> ErrorHandlingResult:
        """Hybrid strategy - adaptive approach based on construct characteristics"""
        modified_sql = sql
        warnings = []
        errors = []
        fallback_used = False

        for construct in unsupported_constructs:
            # Choose strategy based on construct characteristics
            if construct.reason == UnsupportedReason.DATA_INTEGRITY:
                # Critical - fail for data integrity risks
                errors.append(f"Critical: {construct.construct_name} poses data integrity risk")
            elif construct.severity == IssueSeverity.ERROR:
                # Try substitution first
                fallback = self._get_fallback_mapping(construct)
                if fallback:
                    modified_sql = modified_sql.replace(construct.original_fragment, fallback)
                    warnings.append(f"Substituted {construct.construct_name} with {fallback}")
                    fallback_used = True
                    self._fallback_count += 1
                else:
                    errors.append(f"No safe alternative for {construct.construct_name}")
            else:
                # Warning level - passthrough with warning
                warnings.append(f"Unsupported construct passed through: {construct.construct_name}")
                self._passthrough_count += 1

        success = len(errors) == 0

        return ErrorHandlingResult(
            success=success,
            modified_sql=modified_sql,
            unsupported_constructs=unsupported_constructs,
            warnings=warnings,
            errors=errors,
            fallback_used=fallback_used,
            strategy_applied=ErrorStrategy.HYBRID,
            processing_time_ms=0.0,
        )

    def _get_fallback_mapping(self, construct: UnsupportedConstruct) -> str | None:
        """Get fallback mapping for unsupported construct"""
        return self.fallback_mappings.get(construct.construct_name.upper())

    def _update_error_metrics(self, result: ErrorHandlingResult):
        """Update error handling metrics"""
        if result.unsupported_constructs:
            self._error_count += len(result.unsupported_constructs)

    def _setup_error_rules(self):
        """Setup error handling rules and classifications"""
        # Unsupported functions with detailed information
        self.unsupported_functions = {
            # System functions with no PostgreSQL equivalent
            "%SYSTEM.LICENSE.GETFEATURE": {
                "reason": UnsupportedReason.IRIS_SPECIFIC,
                "severity": IssueSeverity.WARNING,
                "alternative": "Remove licensing checks for PostgreSQL compatibility",
                "docs": "https://docs.intersystems.com/iris/latest/csp/docbook/DocBook.UI.Page.cls?KEY=RCOS_flicense",
                "workaround": "Use configuration-based feature flags instead",
            },
            # Complex ObjectScript functions
            "%SYSTEM.PROCESS.UNIQUEID": {
                "reason": UnsupportedReason.IRIS_SPECIFIC,
                "severity": IssueSeverity.WARNING,
                "alternative": "gen_random_uuid()",
                "workaround": "Use PostgreSQL UUID functions",
            },
            # Deprecated constructs
            "%SQLUPPER": {
                "reason": UnsupportedReason.DEPRECATED,
                "severity": IssueSeverity.WARNING,
                "alternative": "UPPER()",
                "workaround": "Use standard SQL UPPER() function",
            },
            # Performance-risky constructs
            "%ODBCIN": {
                "reason": UnsupportedReason.PERFORMANCE_RISK,
                "severity": IssueSeverity.ERROR,
                "alternative": "Use explicit parameter binding",
                "workaround": "Rewrite query with proper parameters",
            },
            # Data integrity risks
            "%NOLOCK": {
                "reason": UnsupportedReason.DATA_INTEGRITY,
                "severity": IssueSeverity.ERROR,
                "alternative": "Remove hint - PostgreSQL handles concurrency differently",
                "workaround": "Use READ UNCOMMITTED isolation level if necessary",
            },
        }

        # Licensing-dependent constructs
        self.licensing_dependent = {
            "VECTOR_COSINE",
            "VECTOR_DOT_PRODUCT",
            "TO_VECTOR",
            "ML_PREDICT",
            "ML_TRAIN",
            "PROBABILITY",
        }

        # Unsupported SQL patterns
        self.unsupported_patterns = {
            r"\bFOR\s+SYSTEM_TIME\b": {
                "name": "FOR SYSTEM_TIME",
                "type": "temporal_construct",
                "reason": UnsupportedReason.NO_MAPPING,
                "severity": IssueSeverity.ERROR,
                "alternative": "Use timestamp-based queries",
                "workaround": "Implement temporal logic in application layer",
            },
            r"\bPRIVATE\s+TEMP\s+TABLE\b": {
                "name": "PRIVATE TEMP TABLE",
                "type": "ddl_construct",
                "reason": UnsupportedReason.COMPLEX_SYNTAX,
                "severity": IssueSeverity.WARNING,
                "alternative": "CREATE TEMP TABLE",
                "workaround": "Use PostgreSQL temporary tables",
            },
            r"\bCLASSMETHOD\b": {
                "name": "CLASSMETHOD",
                "type": "objectscript_construct",
                "reason": UnsupportedReason.IRIS_SPECIFIC,
                "severity": IssueSeverity.ERROR,
                "alternative": "Use PostgreSQL functions",
                "workaround": "Implement as stored procedures",
            },
        }

    def _setup_fallback_mappings(self):
        """Setup fallback mappings for common unsupported constructs"""
        self.fallback_mappings = {
            # System functions
            "%SYSTEM.PROCESS.UNIQUEID": "gen_random_uuid()",
            "%SQLUPPER": "UPPER",
            "%SQLLOWER": "LOWER",
            # String functions
            "%STARTSWITH": "LIKE",  # Will need parameter adjustment
            "%CONTAINS": "LIKE",  # Will need parameter adjustment
            # Date functions
            "%SYSTEM.UTIL.GETDATE": "CURRENT_DATE",
            "%SYSTEM.UTIL.GETTIME": "CURRENT_TIME",
            # Aggregate functions
            "%EXTERNAL": "",  # Remove external hints
            # Locking hints
            "%NOLOCK": "",  # Remove locking hints
            "%SHARED": "",  # Remove locking hints
        }

    def get_error_stats(self) -> dict[str, Any]:
        """Get error handling statistics"""
        return {
            "total_errors_handled": self._error_count,
            "fallbacks_applied": self._fallback_count,
            "passthroughs_applied": self._passthrough_count,
            "default_strategy": self.default_strategy.value,
            "supported_strategies": [s.value for s in ErrorStrategy],
            "unsupported_functions_count": len(self.unsupported_functions),
            "fallback_mappings_count": len(self.fallback_mappings),
            "constitutional_compliance": {
                "transparent_error_reporting": True,
                "fallback_strategies_available": True,
                "data_integrity_protection": True,
            },
        }


# Global error handler instance
_error_handler = IRISErrorHandler()


def get_error_handler() -> IRISErrorHandler:
    """Get the global error handler instance"""
    return _error_handler


def handle_unsupported_constructs(
    sql: str, parsed_constructs: list[ParsedConstruct], strategy: ErrorStrategy | None = None
) -> ErrorHandlingResult:
    """Handle unsupported constructs (convenience function)"""
    return _error_handler.handle_unsupported_constructs(sql, parsed_constructs, strategy)


# Export main components
__all__ = [
    "IRISErrorHandler",
    "ErrorStrategy",
    "UnsupportedReason",
    "UnsupportedConstruct",
    "ErrorHandlingResult",
    "get_error_handler",
    "handle_unsupported_constructs",
]

"""
Unit tests for iris_pgwire.sql_translator.error_handler

Covers: IRISErrorHandler, all ErrorStrategy branches, pattern scanning,
construct identification, fallback mappings, metrics, and module-level helpers.
No live IRIS connection required.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from iris_pgwire.sql_translator.error_handler import (
    ErrorHandlingResult,
    ErrorStrategy,
    IRISErrorHandler,
    UnsupportedConstruct,
    UnsupportedReason,
    get_error_handler,
    handle_unsupported_constructs,
)
from iris_pgwire.sql_translator.models import ConstructType, IssueSeverity, SourceLocation
from iris_pgwire.sql_translator.parser import ParsedConstruct


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_location(column: int = 1, length: int = 10) -> SourceLocation:
    return SourceLocation(line=1, column=column, length=length)


def _make_construct(
    original_text: str,
    construct_type: ConstructType = ConstructType.FUNCTION,
    column: int = 1,
    length: int = None,
) -> ParsedConstruct:
    if length is None:
        length = len(original_text)
    loc = _make_location(column=column, length=length)
    return ParsedConstruct(
        construct_type=construct_type,
        original_text=original_text,
        location=loc,
        parameters=[],
        metadata={},
    )


def _make_unsupported(
    name: str,
    reason: UnsupportedReason = UnsupportedReason.IRIS_SPECIFIC,
    severity: str = IssueSeverity.WARNING,
    original_fragment: str = "frag",
) -> UnsupportedConstruct:
    return UnsupportedConstruct(
        construct_name=name,
        construct_type="function",
        reason=reason,
        original_fragment=original_fragment,
        position_start=0,
        position_end=4,
        severity=severity,
        suggested_alternative=None,
        documentation_link=None,
        workaround=None,
    )


# ---------------------------------------------------------------------------
# IRISErrorHandler.__init__
# ---------------------------------------------------------------------------


class TestIRISErrorHandlerInit:
    def test_default_strategy(self):
        handler = IRISErrorHandler()
        assert handler.default_strategy == ErrorStrategy.HYBRID

    def test_custom_strategy(self):
        handler = IRISErrorHandler(default_strategy=ErrorStrategy.FAIL_FAST)
        assert handler.default_strategy == ErrorStrategy.FAIL_FAST

    def test_initial_metrics_zero(self):
        handler = IRISErrorHandler()
        stats = handler.get_error_stats()
        assert stats["total_errors_handled"] == 0
        assert stats["fallbacks_applied"] == 0
        assert stats["passthroughs_applied"] == 0

    def test_unsupported_functions_populated(self):
        handler = IRISErrorHandler()
        assert len(handler.unsupported_functions) > 0
        assert "%SQLUPPER" in handler.unsupported_functions

    def test_fallback_mappings_populated(self):
        handler = IRISErrorHandler()
        assert len(handler.fallback_mappings) > 0
        assert "%SQLUPPER" in handler.fallback_mappings

    def test_licensing_dependent_populated(self):
        handler = IRISErrorHandler()
        assert "VECTOR_COSINE" in handler.licensing_dependent


# ---------------------------------------------------------------------------
# handle_unsupported_constructs – no unsupported constructs
# ---------------------------------------------------------------------------


class TestHandleNoUnsupported:
    def setup_method(self):
        self.handler = IRISErrorHandler()

    def test_clean_sql_returns_success(self):
        result = self.handler.handle_unsupported_constructs("SELECT 1", [])
        assert result.success is True
        assert result.modified_sql == "SELECT 1"
        assert result.unsupported_constructs == []
        assert result.fallback_used is False

    def test_processing_time_set(self):
        result = self.handler.handle_unsupported_constructs("SELECT 1", [])
        assert result.processing_time_ms >= 0

    def test_strategy_propagated(self):
        result = self.handler.handle_unsupported_constructs(
            "SELECT 1", [], strategy=ErrorStrategy.FAIL_FAST
        )
        assert result.strategy_applied == ErrorStrategy.FAIL_FAST

    def test_uses_default_strategy_when_none(self):
        handler = IRISErrorHandler(default_strategy=ErrorStrategy.PASSTHROUGH)
        result = handler.handle_unsupported_constructs("SELECT 1", [])
        assert result.strategy_applied == ErrorStrategy.PASSTHROUGH


# ---------------------------------------------------------------------------
# _check_construct_support
# ---------------------------------------------------------------------------


class TestCheckConstructSupport:
    def setup_method(self):
        self.handler = IRISErrorHandler()

    def test_known_unsupported_function(self):
        construct = _make_construct("%SQLUPPER")
        result = self.handler._check_construct_support(construct, "SELECT %SQLUPPER(col) FROM t")
        assert result is not None
        assert result.construct_name == "%SQLUPPER"
        assert result.reason == UnsupportedReason.DEPRECATED

    def test_licensing_dependent(self):
        construct = _make_construct("VECTOR_COSINE")
        result = self.handler._check_construct_support(construct, "SELECT VECTOR_COSINE(a,b)")
        assert result is not None
        assert result.reason == UnsupportedReason.LICENSING
        assert result.severity == IssueSeverity.WARNING

    def test_supported_construct_returns_none(self):
        construct = _make_construct("SELECT")
        result = self.handler._check_construct_support(construct, "SELECT 1")
        assert result is None

    def test_nolock_severity_error(self):
        construct = _make_construct("%NOLOCK")
        result = self.handler._check_construct_support(construct, "SELECT %NOLOCK 1")
        assert result is not None
        assert result.severity == IssueSeverity.ERROR

    def test_construct_position_from_location(self):
        construct = _make_construct("%SQLUPPER", column=5, length=8)
        result = self.handler._check_construct_support(construct, "SELECT %SQLUPPER(x)")
        assert result.position_start == 5
        assert result.position_end == 13


# ---------------------------------------------------------------------------
# _scan_for_unsupported_patterns
# ---------------------------------------------------------------------------


class TestScanForUnsupportedPatterns:
    def setup_method(self):
        self.handler = IRISErrorHandler()

    def test_for_system_time_detected(self):
        sql = "SELECT * FROM t FOR SYSTEM_TIME AS OF '2024-01-01'"
        results = self.handler._scan_for_unsupported_patterns(sql)
        names = [r.construct_name for r in results]
        assert "FOR SYSTEM_TIME" in names

    def test_private_temp_table_detected(self):
        sql = "CREATE PRIVATE TEMP TABLE foo (id INT)"
        results = self.handler._scan_for_unsupported_patterns(sql)
        names = [r.construct_name for r in results]
        assert "PRIVATE TEMP TABLE" in names

    def test_classmethod_detected(self):
        sql = "CALL CLASSMETHOD('MyClass', 'MyMethod')"
        results = self.handler._scan_for_unsupported_patterns(sql)
        names = [r.construct_name for r in results]
        assert "CLASSMETHOD" in names

    def test_no_match_returns_empty(self):
        sql = "SELECT id, name FROM users WHERE id = 1"
        results = self.handler._scan_for_unsupported_patterns(sql)
        assert results == []

    def test_position_info_populated(self):
        sql = "SELECT * FROM t FOR SYSTEM_TIME AS OF NOW()"
        results = self.handler._scan_for_unsupported_patterns(sql)
        assert len(results) > 0
        r = results[0]
        assert r.position_start >= 0
        assert r.position_end > r.position_start


# ---------------------------------------------------------------------------
# _handle_fail_fast
# ---------------------------------------------------------------------------


class TestHandleFailFast:
    def setup_method(self):
        self.handler = IRISErrorHandler()

    def test_fails_on_first_unsupported(self):
        constructs = [
            _make_unsupported("BAD_FUNC"),
            _make_unsupported("OTHER_FUNC"),
        ]
        result = self.handler._handle_fail_fast("SELECT BAD_FUNC()", constructs)
        assert result.success is False
        assert len(result.errors) == 1
        assert "BAD_FUNC" in result.errors[0]

    def test_empty_constructs_succeeds(self):
        result = self.handler._handle_fail_fast("SELECT 1", [])
        assert result.success is True

    def test_strategy_is_fail_fast(self):
        constructs = [_make_unsupported("X")]
        result = self.handler._handle_fail_fast("X", constructs)
        assert result.strategy_applied == ErrorStrategy.FAIL_FAST

    def test_error_contains_reason(self):
        constructs = [_make_unsupported("BAD", reason=UnsupportedReason.NO_MAPPING)]
        result = self.handler._handle_fail_fast("BAD", constructs)
        assert "no_mapping" in result.errors[0]


# ---------------------------------------------------------------------------
# _handle_best_effort
# ---------------------------------------------------------------------------


class TestHandleBestEffort:
    def setup_method(self):
        self.handler = IRISErrorHandler()

    def test_warning_severity_yields_warning(self):
        constructs = [_make_unsupported("WARN_FUNC", severity=IssueSeverity.WARNING)]
        result = self.handler._handle_best_effort("SELECT WARN_FUNC()", constructs)
        assert result.success is True
        assert len(result.warnings) == 1
        assert len(result.errors) == 0

    def test_error_severity_yields_error(self):
        constructs = [_make_unsupported("ERR_FUNC", severity=IssueSeverity.ERROR)]
        result = self.handler._handle_best_effort("SELECT ERR_FUNC()", constructs)
        assert result.success is False
        assert len(result.errors) == 1

    def test_mixed_severity(self):
        constructs = [
            _make_unsupported("ERR_FUNC", severity=IssueSeverity.ERROR),
            _make_unsupported("WARN_FUNC", severity=IssueSeverity.WARNING),
        ]
        result = self.handler._handle_best_effort("SELECT 1", constructs)
        assert result.success is False
        assert len(result.errors) == 1
        assert len(result.warnings) == 1

    def test_strategy_is_best_effort(self):
        constructs = [_make_unsupported("X")]
        result = self.handler._handle_best_effort("X", constructs)
        assert result.strategy_applied == ErrorStrategy.BEST_EFFORT

    def test_sql_unchanged(self):
        sql = "SELECT %SQLUPPER(col)"
        constructs = [_make_unsupported("WARN_FUNC")]
        result = self.handler._handle_best_effort(sql, constructs)
        assert result.modified_sql == sql


# ---------------------------------------------------------------------------
# _handle_passthrough
# ---------------------------------------------------------------------------


class TestHandlePassthrough:
    def setup_method(self):
        self.handler = IRISErrorHandler()

    def test_always_succeeds(self):
        constructs = [_make_unsupported("X", severity=IssueSeverity.ERROR)]
        result = self.handler._handle_passthrough("SELECT X()", constructs)
        assert result.success is True

    def test_warnings_generated(self):
        constructs = [_make_unsupported("X"), _make_unsupported("Y")]
        result = self.handler._handle_passthrough("SELECT 1", constructs)
        assert len(result.warnings) == 2

    def test_fallback_used_true(self):
        constructs = [_make_unsupported("X")]
        result = self.handler._handle_passthrough("X", constructs)
        assert result.fallback_used is True

    def test_passthrough_counter_incremented(self):
        before = self.handler._passthrough_count
        constructs = [_make_unsupported("X"), _make_unsupported("Y")]
        self.handler._handle_passthrough("X Y", constructs)
        assert self.handler._passthrough_count == before + 2

    def test_strategy_is_passthrough(self):
        constructs = [_make_unsupported("X")]
        result = self.handler._handle_passthrough("X", constructs)
        assert result.strategy_applied == ErrorStrategy.PASSTHROUGH


# ---------------------------------------------------------------------------
# _handle_substitute
# ---------------------------------------------------------------------------


class TestHandleSubstitute:
    def setup_method(self):
        self.handler = IRISErrorHandler()

    def test_known_mapping_applied(self):
        # %SQLUPPER has a mapping to UPPER
        c = _make_unsupported("%SQLUPPER", original_fragment="%SQLUPPER")
        result = self.handler._handle_substitute("SELECT %SQLUPPER(col)", [c])
        assert result.success is True
        assert "%SQLUPPER" not in result.modified_sql
        assert result.fallback_used is True

    def test_unknown_mapping_fails(self):
        c = _make_unsupported("UNKNOWN_FUNC", original_fragment="UNKNOWN_FUNC")
        result = self.handler._handle_substitute("SELECT UNKNOWN_FUNC()", [c])
        assert result.success is False
        assert len(result.errors) == 1

    def test_fallback_counter_incremented(self):
        before = self.handler._fallback_count
        c = _make_unsupported("%SQLUPPER", original_fragment="%SQLUPPER")
        self.handler._handle_substitute("SELECT %SQLUPPER(x)", [c])
        assert self.handler._fallback_count == before + 1

    def test_strategy_is_substitute(self):
        c = _make_unsupported("X", original_fragment="X")
        result = self.handler._handle_substitute("X", [c])
        assert result.strategy_applied == ErrorStrategy.SUBSTITUTE

    def test_multiple_substitutions(self):
        c1 = _make_unsupported("%SQLUPPER", original_fragment="%SQLUPPER")
        c2 = _make_unsupported("%SQLLOWER", original_fragment="%SQLLOWER")
        sql = "SELECT %SQLUPPER(a), %SQLLOWER(b)"
        result = self.handler._handle_substitute(sql, [c1, c2])
        assert result.success is True
        assert len(result.warnings) == 2


# ---------------------------------------------------------------------------
# _handle_hybrid
# ---------------------------------------------------------------------------


class TestHandleHybrid:
    def setup_method(self):
        self.handler = IRISErrorHandler()

    def test_data_integrity_risk_causes_error(self):
        c = _make_unsupported(
            "%NOLOCK",
            reason=UnsupportedReason.DATA_INTEGRITY,
            severity=IssueSeverity.ERROR,
            original_fragment="%NOLOCK",
        )
        result = self.handler._handle_hybrid("SELECT %NOLOCK 1", [c])
        assert result.success is False
        assert any("data integrity" in e.lower() for e in result.errors)

    def test_error_severity_with_fallback_substitutes(self):
        # %SQLUPPER has a fallback mapping and is ERROR severity in unsupported_functions
        c = _make_unsupported(
            "%ODBCIN",
            reason=UnsupportedReason.PERFORMANCE_RISK,
            severity=IssueSeverity.ERROR,
            original_fragment="%ODBCIN",
        )
        # %ODBCIN has no fallback mapping — should fail
        result = self.handler._handle_hybrid("SELECT %ODBCIN(x)", [c])
        assert result.success is False

    def test_warning_severity_passthrough(self):
        c = _make_unsupported(
            "SOME_FUNC",
            reason=UnsupportedReason.IRIS_SPECIFIC,
            severity=IssueSeverity.WARNING,
            original_fragment="SOME_FUNC",
        )
        result = self.handler._handle_hybrid("SELECT SOME_FUNC()", [c])
        assert result.success is True
        assert any("passed through" in w for w in result.warnings)

    def test_strategy_is_hybrid(self):
        c = _make_unsupported("X", severity=IssueSeverity.WARNING)
        result = self.handler._handle_hybrid("X", [c])
        assert result.strategy_applied == ErrorStrategy.HYBRID

    def test_hybrid_with_substitutable_error_construct(self):
        # %SQLUPPER WARNING severity in unsupported_functions, but we force ERROR severity
        c = UnsupportedConstruct(
            construct_name="%SQLUPPER",
            construct_type="function",
            reason=UnsupportedReason.DEPRECATED,
            original_fragment="%SQLUPPER",
            position_start=0,
            position_end=8,
            severity=IssueSeverity.ERROR,
        )
        result = self.handler._handle_hybrid("SELECT %SQLUPPER(x)", [c])
        assert result.success is True
        assert result.fallback_used is True


# ---------------------------------------------------------------------------
# _apply_error_strategy routing
# ---------------------------------------------------------------------------


class TestApplyErrorStrategyRouting:
    def setup_method(self):
        self.handler = IRISErrorHandler()
        self.constructs = [_make_unsupported("X")]

    def test_routes_fail_fast(self):
        result = self.handler._apply_error_strategy("X", self.constructs, ErrorStrategy.FAIL_FAST)
        assert result.strategy_applied == ErrorStrategy.FAIL_FAST

    def test_routes_best_effort(self):
        result = self.handler._apply_error_strategy("X", self.constructs, ErrorStrategy.BEST_EFFORT)
        assert result.strategy_applied == ErrorStrategy.BEST_EFFORT

    def test_routes_passthrough(self):
        result = self.handler._apply_error_strategy("X", self.constructs, ErrorStrategy.PASSTHROUGH)
        assert result.strategy_applied == ErrorStrategy.PASSTHROUGH

    def test_routes_substitute(self):
        result = self.handler._apply_error_strategy("X", self.constructs, ErrorStrategy.SUBSTITUTE)
        assert result.strategy_applied == ErrorStrategy.SUBSTITUTE

    def test_routes_hybrid(self):
        result = self.handler._apply_error_strategy("X", self.constructs, ErrorStrategy.HYBRID)
        assert result.strategy_applied == ErrorStrategy.HYBRID


# ---------------------------------------------------------------------------
# _update_error_metrics
# ---------------------------------------------------------------------------


class TestUpdateErrorMetrics:
    def setup_method(self):
        self.handler = IRISErrorHandler()

    def test_metrics_increment_on_unsupported(self):
        result = MagicMock(spec=ErrorHandlingResult)
        result.unsupported_constructs = [MagicMock(), MagicMock()]
        self.handler._update_error_metrics(result)
        assert self.handler._error_count == 2

    def test_metrics_no_increment_on_empty(self):
        result = MagicMock(spec=ErrorHandlingResult)
        result.unsupported_constructs = []
        self.handler._update_error_metrics(result)
        assert self.handler._error_count == 0


# ---------------------------------------------------------------------------
# get_error_stats
# ---------------------------------------------------------------------------


class TestGetErrorStats:
    def setup_method(self):
        self.handler = IRISErrorHandler()

    def test_stats_keys(self):
        stats = self.handler.get_error_stats()
        expected_keys = {
            "total_errors_handled",
            "fallbacks_applied",
            "passthroughs_applied",
            "default_strategy",
            "supported_strategies",
            "unsupported_functions_count",
            "fallback_mappings_count",
            "constitutional_compliance",
        }
        assert expected_keys.issubset(stats.keys())

    def test_supported_strategies_list(self):
        stats = self.handler.get_error_stats()
        assert "hybrid" in stats["supported_strategies"]

    def test_constitutional_compliance_fields(self):
        stats = self.handler.get_error_stats()
        cc = stats["constitutional_compliance"]
        assert cc["transparent_error_reporting"] is True
        assert cc["fallback_strategies_available"] is True
        assert cc["data_integrity_protection"] is True


# ---------------------------------------------------------------------------
# Full integration: handle_unsupported_constructs with real parsed constructs
# ---------------------------------------------------------------------------


class TestHandleUnsupportedConstructsIntegration:
    def setup_method(self):
        self.handler = IRISErrorHandler()

    def test_known_unsupported_function_detected(self):
        c = _make_construct("%SQLUPPER")
        result = self.handler.handle_unsupported_constructs(
            "SELECT %SQLUPPER(col) FROM t", [c], strategy=ErrorStrategy.BEST_EFFORT
        )
        assert len(result.unsupported_constructs) == 1

    def test_pattern_scan_integrated(self):
        # FOR SYSTEM_TIME is in unsupported_patterns — no parsed constructs needed
        result = self.handler.handle_unsupported_constructs(
            "SELECT * FROM t FOR SYSTEM_TIME AS OF NOW()", []
        )
        assert len(result.unsupported_constructs) >= 1

    def test_metrics_updated_after_call(self):
        c = _make_construct("%SQLUPPER")
        self.handler.handle_unsupported_constructs(
            "SELECT %SQLUPPER(col)", [c], strategy=ErrorStrategy.BEST_EFFORT
        )
        stats = self.handler.get_error_stats()
        assert stats["total_errors_handled"] >= 1

    def test_licensing_construct_via_handle(self):
        c = _make_construct("VECTOR_COSINE")
        result = self.handler.handle_unsupported_constructs(
            "SELECT VECTOR_COSINE(a, b)", [c], strategy=ErrorStrategy.BEST_EFFORT
        )
        reasons = [u.reason for u in result.unsupported_constructs]
        assert UnsupportedReason.LICENSING in reasons


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


class TestModuleLevelFunctions:
    def test_get_error_handler_returns_instance(self):
        handler = get_error_handler()
        assert isinstance(handler, IRISErrorHandler)

    def test_get_error_handler_singleton(self):
        h1 = get_error_handler()
        h2 = get_error_handler()
        assert h1 is h2

    def test_handle_unsupported_constructs_delegates(self):
        result = handle_unsupported_constructs("SELECT 1", [])
        assert isinstance(result, ErrorHandlingResult)
        assert result.success is True

    def test_handle_unsupported_constructs_with_strategy(self):
        c = _make_construct("%SQLUPPER")
        result = handle_unsupported_constructs(
            "SELECT %SQLUPPER(x)", [c], strategy=ErrorStrategy.PASSTHROUGH
        )
        assert result.strategy_applied == ErrorStrategy.PASSTHROUGH


# ---------------------------------------------------------------------------
# UnsupportedConstruct dataclass
# ---------------------------------------------------------------------------


class TestUnsupportedConstruct:
    def test_create_with_all_fields(self):
        c = UnsupportedConstruct(
            construct_name="TEST",
            construct_type="function",
            reason=UnsupportedReason.IRIS_SPECIFIC,
            original_fragment="TEST()",
            position_start=0,
            position_end=6,
            severity=IssueSeverity.WARNING,
            suggested_alternative="alt()",
            documentation_link="https://example.com",
            workaround="use alt()",
            metadata={"key": "value"},
        )
        assert c.construct_name == "TEST"
        assert c.metadata["key"] == "value"

    def test_create_with_defaults(self):
        c = UnsupportedConstruct(
            construct_name="X",
            construct_type="function",
            reason=UnsupportedReason.NO_MAPPING,
            original_fragment="X",
            position_start=0,
            position_end=1,
            severity=IssueSeverity.ERROR,
        )
        assert c.suggested_alternative is None
        assert c.metadata == {}


# ---------------------------------------------------------------------------
# ErrorStrategy and UnsupportedReason enums
# ---------------------------------------------------------------------------


class TestEnums:
    def test_error_strategy_values(self):
        assert ErrorStrategy.FAIL_FAST.value == "fail_fast"
        assert ErrorStrategy.BEST_EFFORT.value == "best_effort"
        assert ErrorStrategy.PASSTHROUGH.value == "passthrough"
        assert ErrorStrategy.SUBSTITUTE.value == "substitute"
        assert ErrorStrategy.HYBRID.value == "hybrid"

    def test_unsupported_reason_values(self):
        assert UnsupportedReason.NO_MAPPING.value == "no_mapping"
        assert UnsupportedReason.DATA_INTEGRITY.value == "data_integrity_risk"
        assert UnsupportedReason.LICENSING.value == "licensing"

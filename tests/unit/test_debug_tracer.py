"""
Unit tests for debug_tracer.py

Covers TraceLevel, dataclasses, DebugTracer methods, and global helpers.
No IRIS connection required.
"""

from __future__ import annotations

import time

import pytest

from iris_pgwire.debug_tracer import (
    DebugTrace,
    DebugTracer,
    MappingDecision,
    TraceLevel,
    TraceStep,
    ValidationResult,
    get_tracer,
    reset_tracer,
    set_trace_level,
)


# ---------------------------------------------------------------------------
# Cleanup global state between tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_global_tracer():
    reset_tracer()
    yield
    reset_tracer()


# ---------------------------------------------------------------------------
# TraceLevel enum
# ---------------------------------------------------------------------------

class TestTraceLevel:
    def test_values_exist(self):
        assert TraceLevel.MINIMAL.value == "minimal"
        assert TraceLevel.STANDARD.value == "standard"
        assert TraceLevel.VERBOSE.value == "verbose"

    def test_three_members(self):
        assert len(list(TraceLevel)) == 3


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

class TestTraceStep:
    def test_creation(self):
        step = TraceStep(
            step_id="step_001",
            step_name="parse",
            timestamp=1.0,
            duration_ms=0.5,
            input_data="SELECT 1",
            output_data="SELECT 1",
        )
        assert step.step_id == "step_001"
        assert step.success is True
        assert step.error_message is None
        assert step.metadata == {}


class TestMappingDecision:
    def test_creation(self):
        d = MappingDecision(
            construct="NOW()",
            construct_type="function",
            original_syntax="NOW()",
            translated_syntax="GETDATE()",
            decision_type="DIRECT_MAPPING",
            confidence=1.0,
            rationale="exact equivalent",
        )
        assert d.alternatives_considered == []
        assert d.confidence == 1.0


class TestValidationResult:
    def test_passed(self):
        r = ValidationResult(check_name="sla", passed=True, message="ok")
        assert r.passed is True
        assert r.details == {}

    def test_failed(self):
        r = ValidationResult(check_name="sla", passed=False, message="too slow")
        assert r.passed is False


class TestDebugTrace:
    def test_defaults(self):
        trace = DebugTrace(
            trace_id="abc123",
            sql_original="SELECT 1",
            sql_translated="SELECT 1",
            start_time=0.0,
            end_time=1.0,
            total_duration_ms=1.0,
            sla_compliant=True,
            constructs_detected=0,
            constructs_translated=0,
        )
        assert trace.success is True
        assert trace.error_message is None
        assert trace.parsing_steps == []
        assert trace.mapping_decisions == []
        assert trace.validation_results == []
        assert trace.warnings == []


# ---------------------------------------------------------------------------
# DebugTracer.__init__
# ---------------------------------------------------------------------------

class TestDebugTracerInit:
    def test_default_level(self):
        tracer = DebugTracer()
        assert tracer.trace_level == TraceLevel.STANDARD
        assert tracer.current_trace is None
        assert tracer._step_counter == 0

    def test_custom_level(self):
        tracer = DebugTracer(TraceLevel.VERBOSE)
        assert tracer.trace_level == TraceLevel.VERBOSE


# ---------------------------------------------------------------------------
# start_trace
# ---------------------------------------------------------------------------

class TestStartTrace:
    def test_returns_trace_id(self):
        tracer = DebugTracer()
        tid = tracer.start_trace("SELECT 1")
        assert isinstance(tid, str)
        assert len(tid) == 8  # uuid4()[:8]

    def test_sets_current_trace(self):
        tracer = DebugTracer()
        tracer.start_trace("SELECT 1")
        assert tracer.current_trace is not None
        assert tracer.current_trace.sql_original == "SELECT 1"

    def test_resets_step_counter(self):
        tracer = DebugTracer()
        tracer._step_counter = 99
        tracer.start_trace("SELECT 1")
        assert tracer._step_counter == 0


# ---------------------------------------------------------------------------
# add_parsing_step
# ---------------------------------------------------------------------------

class TestAddParsingStep:
    def test_noop_when_no_trace(self):
        tracer = DebugTracer()
        # Should not raise even with no trace
        tracer.add_parsing_step("parse", "in", "out", 0.5)

    def test_adds_step(self):
        tracer = DebugTracer()
        tracer.start_trace("SELECT 1")
        tracer.add_parsing_step("normalize", "SELECT 1", "SELECT 1", 0.1)
        assert len(tracer.current_trace.parsing_steps) == 1
        step = tracer.current_trace.parsing_steps[0]
        assert step.step_name == "normalize"
        assert step.step_id == "step_000"

    def test_increments_step_counter(self):
        tracer = DebugTracer()
        tracer.start_trace("SELECT 1")
        tracer.add_parsing_step("a", "in", "out", 0.1)
        tracer.add_parsing_step("b", "in", "out", 0.1)
        assert tracer._step_counter == 2

    def test_verbose_level_logs(self):
        tracer = DebugTracer(TraceLevel.VERBOSE)
        tracer.start_trace("SELECT 1")
        # Should not raise — verbose logs via structlog
        tracer.add_parsing_step("verbose_step", "in", "out", 0.1, metadata={"key": "val"})
        assert len(tracer.current_trace.parsing_steps) == 1

    def test_metadata_stored(self):
        tracer = DebugTracer()
        tracer.start_trace("SELECT 1")
        tracer.add_parsing_step("parse", "in", "out", 0.5, metadata={"regex": ".*"})
        assert tracer.current_trace.parsing_steps[0].metadata == {"regex": ".*"}


# ---------------------------------------------------------------------------
# add_mapping_decision
# ---------------------------------------------------------------------------

class TestAddMappingDecision:
    def test_noop_when_no_trace(self):
        tracer = DebugTracer()
        tracer.add_mapping_decision("NOW()", "function", "NOW()", "GETDATE()", "DIRECT_MAPPING", 1.0, "exact")

    def test_adds_decision(self):
        tracer = DebugTracer()
        tracer.start_trace("SELECT NOW()")
        tracer.add_mapping_decision("NOW()", "function", "NOW()", "GETDATE()", "DIRECT_MAPPING", 0.95, "reason", ["alt1"])
        assert len(tracer.current_trace.mapping_decisions) == 1
        d = tracer.current_trace.mapping_decisions[0]
        assert d.construct == "NOW()"
        assert d.alternatives_considered == ["alt1"]

    def test_empty_alternatives(self):
        tracer = DebugTracer()
        tracer.start_trace("SELECT 1")
        tracer.add_mapping_decision("X", "type", "X", "Y", "APPROXIMATION", 0.8, "approx")
        assert tracer.current_trace.mapping_decisions[0].alternatives_considered == []


# ---------------------------------------------------------------------------
# add_validation_result
# ---------------------------------------------------------------------------

class TestAddValidationResult:
    def test_noop_when_no_trace(self):
        tracer = DebugTracer()
        tracer.add_validation_result("check", True, "ok")

    def test_adds_passed_result(self):
        tracer = DebugTracer()
        tracer.start_trace("SELECT 1")
        tracer.add_validation_result("sla", True, "within limit")
        assert len(tracer.current_trace.validation_results) == 1

    def test_adds_failed_result_logs_warning(self):
        tracer = DebugTracer()
        tracer.start_trace("SELECT 1")
        # Should not raise even though passed=False (logs warning via structlog)
        tracer.add_validation_result("sla", False, "too slow", {"ms": 100})
        assert tracer.current_trace.validation_results[0].passed is False


# ---------------------------------------------------------------------------
# add_warning
# ---------------------------------------------------------------------------

class TestAddWarning:
    def test_noop_when_no_trace(self):
        tracer = DebugTracer()
        tracer.add_warning("no trace active, should not crash")

    def test_adds_warning(self):
        tracer = DebugTracer()
        tracer.start_trace("SELECT 1")
        tracer.add_warning("unusual construct detected")
        assert "unusual construct detected" in tracer.current_trace.warnings


# ---------------------------------------------------------------------------
# finish_trace
# ---------------------------------------------------------------------------

class TestFinishTrace:
    def test_raises_when_no_trace(self):
        tracer = DebugTracer()
        with pytest.raises(ValueError, match="No active trace"):
            tracer.finish_trace("SELECT 1", 0, 0)

    def test_returns_trace_and_clears(self):
        tracer = DebugTracer()
        tracer.start_trace("SELECT 1")
        trace = tracer.finish_trace("SELECT 1", constructs_detected=0, constructs_translated=0)
        assert isinstance(trace, DebugTrace)
        assert tracer.current_trace is None

    def test_duration_is_positive(self):
        tracer = DebugTracer()
        tracer.start_trace("SELECT 1")
        time.sleep(0.001)
        trace = tracer.finish_trace("SELECT 1", 0, 0)
        assert trace.total_duration_ms > 0

    def test_sla_compliant_fast(self):
        tracer = DebugTracer()
        tracer.start_trace("SELECT 1")
        trace = tracer.finish_trace("SELECT 1", 0, 0)
        # Fast test — should be well under 5ms
        assert trace.sla_compliant is True

    def test_sla_not_compliant_slow(self):
        tracer = DebugTracer()
        tracer.start_trace("SELECT 1")
        # Fake a slow start time by backdating it
        tracer.current_trace.start_time = time.perf_counter() - 0.01  # 10ms ago
        trace = tracer.finish_trace("SELECT 1", 0, 0)
        assert trace.sla_compliant is False

    def test_sets_sql_translated(self):
        tracer = DebugTracer()
        tracer.start_trace("SELECT 1")
        trace = tracer.finish_trace("SELECT 1 -- translated", 0, 0)
        assert trace.sql_translated == "SELECT 1 -- translated"

    def test_success_false(self):
        tracer = DebugTracer()
        tracer.start_trace("SELECT 1")
        trace = tracer.finish_trace("SELECT 1", 0, 0, success=False, error_message="oops")
        assert trace.success is False
        assert trace.error_message == "oops"

    def test_constructs_stored(self):
        tracer = DebugTracer()
        tracer.start_trace("SELECT 1")
        trace = tracer.finish_trace("SELECT 2", constructs_detected=5, constructs_translated=5)
        assert trace.constructs_detected == 5
        assert trace.constructs_translated == 5

    def test_validation_results_populated(self):
        tracer = DebugTracer()
        tracer.start_trace("SELECT 1")
        trace = tracer.finish_trace("SELECT 1", 0, 0)
        # _validate_constitutional_compliance runs, adding at least sla + semantic + error_handling
        names = [r.check_name for r in trace.validation_results]
        assert "sla_compliance" in names
        assert "semantic_equivalence" in names
        assert "error_handling" in names


# ---------------------------------------------------------------------------
# _validate_constitutional_compliance
# ---------------------------------------------------------------------------

class TestValidateConstitutionalCompliance:
    def test_translation_completeness_90pct(self):
        tracer = DebugTracer()
        tracer.start_trace("SELECT 1")
        trace = tracer.finish_trace("SELECT 1", constructs_detected=10, constructs_translated=9)
        names = {r.check_name: r for r in trace.validation_results}
        assert "translation_completeness" in names
        assert names["translation_completeness"].passed is True

    def test_translation_completeness_below_threshold(self):
        tracer = DebugTracer()
        tracer.start_trace("SELECT 1")
        trace = tracer.finish_trace("SELECT 1", constructs_detected=10, constructs_translated=5)
        names = {r.check_name: r for r in trace.validation_results}
        assert names["translation_completeness"].passed is False

    def test_translation_completeness_skipped_when_zero_constructs(self):
        tracer = DebugTracer()
        tracer.start_trace("SELECT 1")
        trace = tracer.finish_trace("SELECT 1", constructs_detected=0, constructs_translated=0)
        names = [r.check_name for r in trace.validation_results]
        assert "translation_completeness" not in names

    def test_semantic_equivalence_good_ratio(self):
        tracer = DebugTracer()
        tracer.start_trace("SELECT 1")
        # Same length → ratio 1.0 → passes
        trace = tracer.finish_trace("SELECT 1", 0, 0)
        names = {r.check_name: r for r in trace.validation_results}
        assert names["semantic_equivalence"].passed is True

    def test_semantic_equivalence_bad_ratio_too_short(self):
        tracer = DebugTracer()
        tracer.start_trace("SELECT 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20")
        # Very short translated → ratio < 0.5
        trace = tracer.finish_trace("X", 0, 0)
        names = {r.check_name: r for r in trace.validation_results}
        assert names["semantic_equivalence"].passed is False

    def test_semantic_equivalence_bad_ratio_too_long(self):
        tracer = DebugTracer()
        tracer.start_trace("A")
        # Very long translated → ratio > 3.0
        trace = tracer.finish_trace("A" * 100, 0, 0)
        names = {r.check_name: r for r in trace.validation_results}
        assert names["semantic_equivalence"].passed is False

    def test_error_handling_passed_on_success(self):
        tracer = DebugTracer()
        tracer.start_trace("SELECT 1")
        trace = tracer.finish_trace("SELECT 1", 0, 0, success=True)
        names = {r.check_name: r for r in trace.validation_results}
        assert names["error_handling"].passed is True

    def test_error_handling_failed_on_error(self):
        tracer = DebugTracer()
        tracer.start_trace("SELECT 1")
        trace = tracer.finish_trace("SELECT 1", 0, 0, success=False, error_message="bad")
        names = {r.check_name: r for r in trace.validation_results}
        assert names["error_handling"].passed is False


# ---------------------------------------------------------------------------
# Global helpers
# ---------------------------------------------------------------------------

class TestGetTracer:
    def test_returns_new_tracer_when_none(self):
        t = get_tracer()
        assert isinstance(t, DebugTracer)
        assert t.trace_level == TraceLevel.STANDARD

    def test_returns_same_instance_on_repeat_call(self):
        t1 = get_tracer()
        t2 = get_tracer()
        assert t1 is t2

    def test_custom_level_on_first_call(self):
        t = get_tracer(TraceLevel.VERBOSE)
        assert t.trace_level == TraceLevel.VERBOSE


class TestSetTraceLevel:
    def test_creates_tracer_when_none(self):
        set_trace_level(TraceLevel.MINIMAL)
        t = get_tracer()
        assert t.trace_level == TraceLevel.MINIMAL

    def test_updates_existing_tracer(self):
        t = get_tracer(TraceLevel.STANDARD)
        set_trace_level(TraceLevel.VERBOSE)
        assert t.trace_level == TraceLevel.VERBOSE


class TestResetTracer:
    def test_reset_clears_global(self):
        get_tracer()
        reset_tracer()
        # After reset, get_tracer creates a fresh one
        t = get_tracer()
        assert isinstance(t, DebugTracer)

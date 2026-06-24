"""
Unit tests for iris_pgwire.sql_translator.debug

No live IRIS connection required. Tests cover:
- DebugTracer init, enabled/disabled branches
- start_trace, add_parsing_step, add_mapping_decision, add_warning, add_error
- complete_trace (success, SLA violation, unknown trace)
- get_trace_summary, export_trace_json, export_trace_html
- get_session_stats, _collect_event_summaries
- _build_html_header, _render_parsing_steps, _render_mapping_decisions, _render_warnings
- TraceEvent, LogLevel dataclasses
- Module-level convenience functions: get_tracer, start_debug_trace, add_parsing_step,
  add_mapping_decision, complete_debug_trace
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime

import pytest

from iris_pgwire.sql_translator.debug import (
    DebugTracer,
    LogLevel,
    TraceEvent,
    add_mapping_decision,
    add_parsing_step,
    complete_debug_trace,
    get_tracer,
    start_debug_trace,
)
from iris_pgwire.sql_translator.models import DebugTrace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_tracer(enabled: bool = True) -> DebugTracer:
    """Return an isolated DebugTracer so tests don't share global state."""
    return DebugTracer(enabled=enabled)


def _start_and_complete(tracer: DebugTracer, trace_id: str = "t1") -> DebugTrace | None:
    """Utility: start a trace, immediately complete it."""
    tracer.start_trace(trace_id, "SELECT 1")
    return tracer.complete_trace(trace_id, "SELECT 1", success=True, total_duration_ms=0.5)


# ---------------------------------------------------------------------------
# LogLevel enum
# ---------------------------------------------------------------------------


class TestLogLevel:
    def test_all_values_present(self):
        assert {lv.value for lv in LogLevel} == {"TRACE", "DEBUG", "INFO", "WARNING", "ERROR"}


# ---------------------------------------------------------------------------
# TraceEvent dataclass
# ---------------------------------------------------------------------------


class TestTraceEvent:
    def test_fields_stored(self):
        now = datetime.now(UTC)
        evt = TraceEvent(
            timestamp=now,
            level=LogLevel.INFO,
            component="test",
            event_type="test_event",
            message="hello",
            data={"k": "v"},
            duration_ms=1.5,
        )
        assert evt.timestamp == now
        assert evt.level == LogLevel.INFO
        assert evt.duration_ms == 1.5

    def test_duration_ms_defaults_none(self):
        evt = TraceEvent(
            timestamp=datetime.now(UTC),
            level=LogLevel.DEBUG,
            component="c",
            event_type="e",
            message="m",
            data={},
        )
        assert evt.duration_ms is None


# ---------------------------------------------------------------------------
# DebugTracer.__init__
# ---------------------------------------------------------------------------


class TestDebugTracerInit:
    def test_enabled_default(self):
        tracer = _fresh_tracer()
        assert tracer.enabled is True

    def test_disabled_tracer(self):
        tracer = _fresh_tracer(enabled=False)
        assert tracer.enabled is False

    def test_starts_with_no_traces(self):
        tracer = _fresh_tracer()
        assert tracer._traces == {}
        assert tracer._events == []

    def test_session_start_is_utc(self):
        tracer = _fresh_tracer()
        assert tracer._session_start.tzinfo is not None


# ---------------------------------------------------------------------------
# start_trace
# ---------------------------------------------------------------------------


class TestStartTrace:
    def test_returns_debug_trace(self):
        tracer = _fresh_tracer()
        trace = tracer.start_trace("t1", "SELECT 1")
        assert isinstance(trace, DebugTrace)

    def test_trace_registered(self):
        tracer = _fresh_tracer()
        tracer.start_trace("t2", "SELECT 2")
        assert "t2" in tracer._traces

    def test_metadata_populated(self):
        tracer = _fresh_tracer()
        trace = tracer.start_trace("t3", "SELECT 3")
        assert trace.metadata["trace_id"] == "t3"
        assert trace.metadata["original_sql"] == "SELECT 3"

    def test_sql_preview_truncated(self):
        tracer = _fresh_tracer()
        long_sql = "SELECT " + "x" * 200
        tracer.start_trace("t4", long_sql)
        # Just verify no exception and event was logged
        assert any(e.event_type == "trace_started" for e in tracer._events)

    def test_disabled_returns_empty_trace(self):
        tracer = _fresh_tracer(enabled=False)
        trace = tracer.start_trace("t_off", "SELECT 1")
        assert isinstance(trace, DebugTrace)
        assert "t_off" not in tracer._traces


# ---------------------------------------------------------------------------
# add_parsing_step
# ---------------------------------------------------------------------------


class TestAddParsingStep:
    def test_adds_step_to_trace(self):
        tracer = _fresh_tracer()
        tracer.start_trace("ps1", "SELECT 1")
        tracer.add_parsing_step("ps1", "step1", "SELECT 1", "SELECT 1", 0.3)
        assert len(tracer._traces["ps1"].parsing_steps) == 1

    def test_slow_step_logs_warning(self):
        tracer = _fresh_tracer()
        tracer.start_trace("ps2", "SELECT 1")
        tracer.add_parsing_step("ps2", "step1", "SELECT 1", "SELECT 1", duration_ms=5.0)
        slow_events = [e for e in tracer._events if e.event_type == "slow_parsing_step"]
        assert len(slow_events) == 1

    def test_fast_step_no_warning(self):
        tracer = _fresh_tracer()
        tracer.start_trace("ps3", "SELECT 1")
        tracer.add_parsing_step("ps3", "step1", "SELECT 1", "SELECT 1", duration_ms=0.1)
        slow_events = [e for e in tracer._events if e.event_type == "slow_parsing_step"]
        assert len(slow_events) == 0

    def test_unknown_trace_is_noop(self):
        tracer = _fresh_tracer()
        # Should not raise
        tracer.add_parsing_step("nonexistent", "step1", "SELECT 1", "SELECT 1", 0.5)

    def test_disabled_is_noop(self):
        tracer = _fresh_tracer(enabled=False)
        tracer.add_parsing_step("x", "step1", "SELECT 1", "SELECT 1", 0.5)
        assert tracer._events == []


# ---------------------------------------------------------------------------
# add_mapping_decision
# ---------------------------------------------------------------------------


class TestAddMappingDecision:
    def test_adds_decision_to_trace(self):
        tracer = _fresh_tracer()
        tracer.start_trace("md1", "SELECT 1")
        tracer.add_mapping_decision("md1", "NOW()", ["GETDATE()", "NOW()"], "GETDATE()", 0.9, "closest equivalent")
        assert len(tracer._traces["md1"].mapping_decisions) == 1

    def test_low_confidence_logs_warning(self):
        tracer = _fresh_tracer()
        tracer.start_trace("md2", "SELECT 1")
        tracer.add_mapping_decision("md2", "FUNC()", ["FUNC()"], "FUNC()", 0.5, "uncertain")
        low_conf = [e for e in tracer._events if e.event_type == "low_confidence_mapping"]
        assert len(low_conf) == 1

    def test_high_confidence_no_warning(self):
        tracer = _fresh_tracer()
        tracer.start_trace("md3", "SELECT 1")
        tracer.add_mapping_decision("md3", "FUNC()", ["FUNC()"], "FUNC()", 0.95, "clear match")
        low_conf = [e for e in tracer._events if e.event_type == "low_confidence_mapping"]
        assert len(low_conf) == 0

    def test_unknown_trace_is_noop(self):
        tracer = _fresh_tracer()
        tracer.add_mapping_decision("ghost", "X", ["X"], "X", 0.9, "noop")

    def test_disabled_is_noop(self):
        tracer = _fresh_tracer(enabled=False)
        tracer.add_mapping_decision("x", "X", ["X"], "X", 0.9, "noop")
        assert tracer._events == []


# ---------------------------------------------------------------------------
# add_warning
# ---------------------------------------------------------------------------


class TestAddWarning:
    def test_adds_warning(self):
        tracer = _fresh_tracer()
        tracer.start_trace("w1", "SELECT 1")
        tracer.add_warning("w1", "Something looked off")
        assert "Something looked off" in tracer._traces["w1"].warnings

    def test_custom_component(self):
        tracer = _fresh_tracer()
        tracer.start_trace("w2", "SELECT 1")
        tracer.add_warning("w2", "warn msg", component="my_component")
        events = [e for e in tracer._events if e.component == "my_component"]
        assert len(events) >= 1

    def test_unknown_trace_is_noop(self):
        tracer = _fresh_tracer()
        tracer.add_warning("ghost", "msg")

    def test_disabled_is_noop(self):
        tracer = _fresh_tracer(enabled=False)
        tracer.add_warning("x", "msg")
        assert tracer._events == []


# ---------------------------------------------------------------------------
# add_error
# ---------------------------------------------------------------------------


class TestAddError:
    def test_logs_error_event(self):
        tracer = _fresh_tracer()
        tracer.start_trace("e1", "SELECT 1")
        tracer.add_error("e1", "something broke")
        error_events = [e for e in tracer._events if e.event_type == "translation_error"]
        assert len(error_events) >= 1

    def test_adds_error_to_trace_warnings(self):
        tracer = _fresh_tracer()
        tracer.start_trace("e2", "SELECT 1")
        tracer.add_error("e2", "bad thing")
        # The trace should have the error logged as a warning
        assert any("bad thing" in w for w in tracer._traces["e2"].warnings)

    def test_unknown_trace_still_logs_event(self):
        tracer = _fresh_tracer()
        tracer.add_error("ghost", "msg")
        error_events = [e for e in tracer._events if e.event_type == "translation_error"]
        assert len(error_events) == 1

    def test_disabled_is_noop(self):
        tracer = _fresh_tracer(enabled=False)
        tracer.add_error("x", "msg")
        assert tracer._events == []


# ---------------------------------------------------------------------------
# complete_trace
# ---------------------------------------------------------------------------


class TestCompleteTrace:
    def test_returns_completed_trace(self):
        tracer = _fresh_tracer()
        tracer.start_trace("c1", "SELECT 1")
        result = tracer.complete_trace("c1", "SELECT 1", success=True, total_duration_ms=1.0)
        assert isinstance(result, DebugTrace)

    def test_removes_from_active_traces(self):
        tracer = _fresh_tracer()
        tracer.start_trace("c2", "SELECT 1")
        tracer.complete_trace("c2", "SELECT 1", success=True, total_duration_ms=1.0)
        assert "c2" not in tracer._traces

    def test_metadata_updated(self):
        tracer = _fresh_tracer()
        tracer.start_trace("c3", "SELECT 1")
        result = tracer.complete_trace("c3", "SELECT 1", success=True, total_duration_ms=2.0)
        assert result.metadata["success"] is True
        assert result.metadata["total_duration_ms"] == 2.0
        assert result.metadata["final_sql"] == "SELECT 1"

    def test_sla_violation_logs_warning(self):
        tracer = _fresh_tracer()
        tracer.start_trace("c4", "SELECT 1")
        tracer.complete_trace("c4", "SELECT 1", success=True, total_duration_ms=10.0)
        sla_events = [e for e in tracer._events if e.event_type == "sla_violation"]
        assert len(sla_events) == 1

    def test_within_sla_no_violation(self):
        tracer = _fresh_tracer()
        tracer.start_trace("c5", "SELECT 1")
        tracer.complete_trace("c5", "SELECT 1", success=True, total_duration_ms=3.0)
        sla_events = [e for e in tracer._events if e.event_type == "sla_violation"]
        assert len(sla_events) == 0

    def test_unknown_trace_returns_none(self):
        tracer = _fresh_tracer()
        result = tracer.complete_trace("ghost", "SELECT 1", success=True, total_duration_ms=1.0)
        assert result is None

    def test_disabled_returns_none(self):
        tracer = _fresh_tracer(enabled=False)
        result = tracer.complete_trace("x", "SELECT 1", success=True, total_duration_ms=1.0)
        assert result is None

    def test_parsing_step_count_in_metadata(self):
        tracer = _fresh_tracer()
        tracer.start_trace("c6", "SELECT 1")
        tracer.add_parsing_step("c6", "step1", "SELECT 1", "SELECT 1", 0.2)
        tracer.add_parsing_step("c6", "step2", "SELECT 1", "SELECT 1", 0.3)
        result = tracer.complete_trace("c6", "SELECT 1", success=True, total_duration_ms=1.0)
        assert result.metadata["parsing_steps_count"] == 2


# ---------------------------------------------------------------------------
# get_trace_summary
# ---------------------------------------------------------------------------


class TestGetTraceSummary:
    def test_returns_summary_dict(self):
        tracer = _fresh_tracer()
        tracer.start_trace("s1", "SELECT 1")
        summary = tracer.get_trace_summary("s1")
        assert summary is not None
        assert summary["trace_id"] == "s1"
        assert summary["active"] is True

    def test_unknown_trace_returns_none(self):
        tracer = _fresh_tracer()
        assert tracer.get_trace_summary("ghost") is None

    def test_disabled_returns_none(self):
        tracer = _fresh_tracer(enabled=False)
        assert tracer.get_trace_summary("x") is None

    def test_counts_steps_and_decisions(self):
        tracer = _fresh_tracer()
        tracer.start_trace("s2", "SELECT 1")
        tracer.add_parsing_step("s2", "step1", "SELECT 1", "SELECT 1", 0.1)
        tracer.add_mapping_decision("s2", "F()", ["F()"], "F()", 0.8, "ok")
        tracer.add_warning("s2", "a warning")
        summary = tracer.get_trace_summary("s2")
        assert summary["parsing_steps_count"] == 1
        assert summary["mapping_decisions_count"] == 1
        assert summary["warnings_count"] == 1


# ---------------------------------------------------------------------------
# export_trace_json
# ---------------------------------------------------------------------------


class TestExportTraceJson:
    def test_returns_valid_json(self):
        tracer = _fresh_tracer()
        tracer.start_trace("j1", "SELECT 1")
        trace = tracer.complete_trace("j1", "SELECT 1", success=True, total_duration_ms=1.0)
        result = tracer.export_trace_json(trace)
        parsed = json.loads(result)
        assert "parsing_steps" in parsed
        assert "mapping_decisions" in parsed
        assert "warnings" in parsed
        assert "metadata" in parsed

    def test_includes_parsing_steps(self):
        tracer = _fresh_tracer()
        tracer.start_trace("j2", "SELECT 1")
        tracer.add_parsing_step("j2", "step1", "SELECT 1", "SELECT 1", 0.5)
        trace = tracer.complete_trace("j2", "SELECT 1", success=True, total_duration_ms=1.0)
        result = tracer.export_trace_json(trace)
        parsed = json.loads(result)
        assert len(parsed["parsing_steps"]) == 1
        assert parsed["parsing_steps"][0]["step_name"] == "step1"

    def test_disabled_returns_empty_json(self):
        tracer = _fresh_tracer(enabled=False)
        trace = DebugTrace()
        result = tracer.export_trace_json(trace)
        assert result == "{}"


# ---------------------------------------------------------------------------
# export_trace_html
# ---------------------------------------------------------------------------


class TestExportTraceHtml:
    def test_returns_html_string(self):
        tracer = _fresh_tracer()
        tracer.start_trace("h1", "SELECT 1")
        trace = tracer.complete_trace("h1", "SELECT 1", success=True, total_duration_ms=1.0)
        result = tracer.export_trace_html(trace)
        assert "<html>" in result
        assert "</html>" in result

    def test_includes_parsing_steps_section(self):
        tracer = _fresh_tracer()
        tracer.start_trace("h2", "SELECT 1")
        tracer.add_parsing_step("h2", "mystep", "SELECT 1", "SELECT 1", 0.2)
        trace = tracer.complete_trace("h2", "SELECT 1", success=True, total_duration_ms=0.5)
        result = tracer.export_trace_html(trace)
        assert "mystep" in result
        assert "Parsing Steps" in result

    def test_includes_mapping_decisions_section(self):
        tracer = _fresh_tracer()
        tracer.start_trace("h3", "SELECT 1")
        tracer.add_mapping_decision("h3", "NOW()", ["NOW()", "GETDATE()"], "GETDATE()", 0.9, "ok")
        trace = tracer.complete_trace("h3", "SELECT 1", success=True, total_duration_ms=0.5)
        result = tracer.export_trace_html(trace)
        assert "Mapping Decisions" in result
        assert "NOW()" in result

    def test_includes_warnings_section(self):
        tracer = _fresh_tracer()
        tracer.start_trace("h4", "SELECT 1")
        tracer.add_warning("h4", "careful here")
        trace = tracer.complete_trace("h4", "SELECT 1", success=True, total_duration_ms=0.5)
        result = tracer.export_trace_html(trace)
        assert "Warnings" in result
        assert "careful here" in result

    def test_disabled_returns_disabled_html(self):
        tracer = _fresh_tracer(enabled=False)
        trace = DebugTrace()
        result = tracer.export_trace_html(trace)
        assert "disabled" in result.lower()

    def test_low_confidence_mapping_gets_warning_css(self):
        tracer = _fresh_tracer()
        tracer.start_trace("h5", "SELECT 1")
        tracer.add_mapping_decision("h5", "X()", ["X()"], "X()", 0.4, "low confidence")
        trace = tracer.complete_trace("h5", "SELECT 1", success=True, total_duration_ms=0.5)
        result = tracer.export_trace_html(trace)
        # Low-confidence decisions get the "warning" CSS class
        assert "warning" in result


# ---------------------------------------------------------------------------
# _render helpers with empty lists
# ---------------------------------------------------------------------------


class TestRenderHelpersEmpty:
    def test_render_parsing_steps_empty(self):
        tracer = _fresh_tracer()
        trace = DebugTrace()
        parts = tracer._render_parsing_steps(trace)
        assert parts == []

    def test_render_mapping_decisions_empty(self):
        tracer = _fresh_tracer()
        trace = DebugTrace()
        parts = tracer._render_mapping_decisions(trace)
        assert parts == []

    def test_render_warnings_empty(self):
        tracer = _fresh_tracer()
        trace = DebugTrace()
        parts = tracer._render_warnings(trace)
        assert parts == []


# ---------------------------------------------------------------------------
# get_session_stats
# ---------------------------------------------------------------------------


class TestGetSessionStats:
    def test_returns_dict_with_expected_keys(self):
        tracer = _fresh_tracer()
        stats = tracer.get_session_stats()
        assert "session_start" in stats
        assert "session_duration_seconds" in stats
        assert "active_traces" in stats
        assert "total_events" in stats
        assert "events_by_level" in stats
        assert "events_by_component" in stats
        assert "constitutional_compliance" in stats

    def test_active_traces_counted(self):
        tracer = _fresh_tracer()
        tracer.start_trace("st1", "SELECT 1")
        tracer.start_trace("st2", "SELECT 2")
        stats = tracer.get_session_stats()
        assert stats["active_traces"] == 2

    def test_session_duration_positive(self):
        tracer = _fresh_tracer()
        stats = tracer.get_session_stats()
        assert stats["session_duration_seconds"] >= 0.0

    def test_compliance_counts_violations(self):
        tracer = _fresh_tracer()
        tracer.start_trace("cv1", "SELECT 1")
        tracer.add_parsing_step("cv1", "slow", "S", "S", duration_ms=5.0)  # slow step
        tracer.complete_trace("cv1", "SELECT 1", success=True, total_duration_ms=10.0)  # SLA violation
        stats = tracer.get_session_stats()
        compliance = stats["constitutional_compliance"]
        assert compliance["slow_parsing_steps"] == 1
        assert compliance["sla_violations"] == 1


# ---------------------------------------------------------------------------
# _collect_event_summaries
# ---------------------------------------------------------------------------


class TestCollectEventSummaries:
    def test_level_counts_all_levels_present(self):
        tracer = _fresh_tracer()
        tracer.start_trace("cs1", "SELECT 1")
        level_counts, _, _ = tracer._collect_event_summaries()
        # All LogLevel values should be keys
        for level in LogLevel:
            assert level.value in level_counts

    def test_component_counts(self):
        tracer = _fresh_tracer()
        tracer.start_trace("cs2", "SELECT 1")
        _, component_counts, _ = tracer._collect_event_summaries()
        assert "tracer" in component_counts


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_start_trace_safe(self):
        tracer = _fresh_tracer()
        errors = []

        def worker(i):
            try:
                tracer.start_trace(f"thread-{i}", f"SELECT {i}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(tracer._traces) == 20


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


class TestModuleFunctions:
    def test_get_tracer_returns_debug_tracer(self):
        tracer = get_tracer()
        assert isinstance(tracer, DebugTracer)

    def test_start_debug_trace_returns_trace(self):
        trace = start_debug_trace("mod_t1", "SELECT 1")
        assert isinstance(trace, DebugTrace)
        # Clean up from global tracer
        get_tracer()._traces.pop("mod_t1", None)

    def test_add_parsing_step_convenience(self):
        start_debug_trace("mod_t2", "SELECT 1")
        # Should not raise
        add_parsing_step("mod_t2", "step", "SELECT 1", "SELECT 1", 0.1)
        get_tracer()._traces.pop("mod_t2", None)

    def test_add_mapping_decision_convenience(self):
        start_debug_trace("mod_t3", "SELECT 1")
        add_mapping_decision("mod_t3", "F()", ["F()"], "F()", 0.9, "ok")
        get_tracer()._traces.pop("mod_t3", None)

    def test_complete_debug_trace_convenience(self):
        start_debug_trace("mod_t4", "SELECT 1")
        result = complete_debug_trace("mod_t4", "SELECT 1", success=True, total_duration_ms=1.0)
        assert isinstance(result, DebugTrace)

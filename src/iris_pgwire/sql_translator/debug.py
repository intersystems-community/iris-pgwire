"""
Debug Trace Logging Implementation

Comprehensive debug tracing for SQL translation with constitutional transparency
requirements. Provides detailed step-by-step translation logging and analysis.

Constitutional Compliance: Complete transparency in translation decisions.
"""

import json
import logging
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from .models import DebugTrace


class LogLevel(Enum):
    """Debug log levels"""

    TRACE = "TRACE"
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass
class TraceEvent:
    """Individual trace event with timing and context"""

    timestamp: datetime
    level: LogLevel
    component: str
    event_type: str
    message: str
    data: dict[str, Any]
    duration_ms: float | None = None


class DebugTracer:
    """
    Advanced debug tracer for SQL translation process

    Features:
    - Step-by-step translation logging
    - Performance timing for each step
    - Constitutional transparency compliance
    - Structured JSON output
    - Thread-safe operations
    """

    def __init__(self, enabled: bool = True):
        """
        Initialize debug tracer

        Args:
            enabled: Whether tracing is enabled
        """
        self.enabled = enabled
        self._lock = threading.Lock()
        self._traces: dict[str, DebugTrace] = {}
        self._events: list[TraceEvent] = []
        self._session_start = datetime.now(UTC)

        # Setup structured logging
        self._setup_logging()

    def _setup_logging(self):
        """Setup structured logging for debug output"""
        self.logger = logging.getLogger("iris_pgwire.sql_translator.debug")

        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.DEBUG)

    def start_trace(self, trace_id: str, original_sql: str) -> DebugTrace:
        """
        Start a new debug trace session

        Args:
            trace_id: Unique identifier for this trace
            original_sql: Original SQL being translated

        Returns:
            DebugTrace instance for this session
        """
        if not self.enabled:
            return DebugTrace()

        with self._lock:
            trace = DebugTrace()
            trace.metadata["trace_id"] = trace_id
            trace.metadata["original_sql"] = original_sql
            trace.metadata["start_time"] = datetime.now(UTC).isoformat()
            trace.metadata["session_duration_ms"] = 0.0

            self._traces[trace_id] = trace

            self._log_event(
                LogLevel.INFO,
                "tracer",
                "trace_started",
                "Started debug trace for SQL translation",
                {
                    "trace_id": trace_id,
                    "sql_length": len(original_sql),
                    "sql_preview": (
                        original_sql[:100] + "..." if len(original_sql) > 100 else original_sql
                    ),
                },
            )

            return trace

    def add_parsing_step(
        self,
        trace_id: str,
        step_name: str,
        input_sql: str,
        output_sql: str,
        duration_ms: float,
        **metadata,
    ) -> None:
        """
        Add a parsing step to the trace

        Args:
            trace_id: Trace session identifier
            step_name: Name of the parsing step
            input_sql: Input SQL for this step
            output_sql: Output SQL after this step
            duration_ms: Time taken for this step
            **metadata: Additional metadata for this step
        """
        if not self.enabled or trace_id not in self._traces:
            return

        with self._lock:
            trace = self._traces[trace_id]
            trace.add_parsing_step(step_name, input_sql, output_sql, duration_ms, **metadata)

            self._log_event(
                LogLevel.DEBUG,
                "parser",
                "parsing_step",
                f"Parsing step: {step_name}",
                {
                    "trace_id": trace_id,
                    "step_name": step_name,
                    "duration_ms": duration_ms,
                    "input_length": len(input_sql),
                    "output_length": len(output_sql),
                    "metadata": metadata,
                },
            )

            # Constitutional requirement: track slow parsing steps
            if duration_ms > 1.0:  # 1ms threshold
                self._log_event(
                    LogLevel.WARNING,
                    "parser",
                    "slow_parsing_step",
                    f"Slow parsing step detected: {step_name} took {duration_ms}ms",
                    {
                        "trace_id": trace_id,
                        "step_name": step_name,
                        "duration_ms": duration_ms,
                        "sla_threshold_ms": 1.0,
                    },
                )

    def add_mapping_decision(
        self,
        trace_id: str,
        construct: str,
        available_mappings: list[str],
        chosen_mapping: str,
        confidence: float,
        reasoning: str,
        **metadata,
    ) -> None:
        """
        Add a mapping decision to the trace

        Args:
            trace_id: Trace session identifier
            construct: IRIS construct being mapped
            available_mappings: List of available mapping options
            chosen_mapping: The mapping that was chosen
            confidence: Confidence level in the mapping (0.0-1.0)
            reasoning: Reasoning for the mapping choice
            **metadata: Additional metadata for this decision
        """
        if not self.enabled or trace_id not in self._traces:
            return

        with self._lock:
            trace = self._traces[trace_id]
            trace.add_mapping_decision(
                construct, available_mappings, chosen_mapping, confidence, reasoning, **metadata
            )

            self._log_event(
                LogLevel.DEBUG,
                "mapper",
                "mapping_decision",
                f"Mapping decision: {construct} -> {chosen_mapping}",
                {
                    "trace_id": trace_id,
                    "construct": construct,
                    "chosen_mapping": chosen_mapping,
                    "confidence": confidence,
                    "available_options": len(available_mappings),
                    "reasoning": reasoning,
                    "metadata": metadata,
                },
            )

            # Constitutional requirement: flag low-confidence mappings
            if confidence < 0.7:
                self._log_event(
                    LogLevel.WARNING,
                    "mapper",
                    "low_confidence_mapping",
                    f"Low confidence mapping: {construct} -> {chosen_mapping} (confidence: {confidence})",
                    {
                        "trace_id": trace_id,
                        "construct": construct,
                        "chosen_mapping": chosen_mapping,
                        "confidence": confidence,
                        "confidence_threshold": 0.7,
                    },
                )

    def add_warning(
        self, trace_id: str, warning_message: str, component: str = "translator", **metadata
    ) -> None:
        """
        Add a warning to the trace

        Args:
            trace_id: Trace session identifier
            warning_message: Warning message
            component: Component that generated the warning
            **metadata: Additional metadata for the warning
        """
        if not self.enabled or trace_id not in self._traces:
            return

        with self._lock:
            trace = self._traces[trace_id]
            trace.add_warning(warning_message)

            self._log_event(
                LogLevel.WARNING,
                component,
                "translation_warning",
                warning_message,
                {"trace_id": trace_id, "component": component, "metadata": metadata},
            )

    def add_error(
        self,
        trace_id: str,
        error_message: str,
        error_type: str = "TranslationError",
        component: str = "translator",
        **metadata,
    ) -> None:
        """
        Add an error to the trace

        Args:
            trace_id: Trace session identifier
            error_message: Error message
            error_type: Type of error
            component: Component that generated the error
            **metadata: Additional metadata for the error
        """
        if not self.enabled:
            return

        with self._lock:
            if trace_id in self._traces:
                trace = self._traces[trace_id]
                trace.add_warning(f"ERROR: {error_message}")

            self._log_event(
                LogLevel.ERROR,
                component,
                "translation_error",
                error_message,
                {
                    "trace_id": trace_id,
                    "error_type": error_type,
                    "component": component,
                    "metadata": metadata,
                },
            )

    def complete_trace(
        self, trace_id: str, final_sql: str, success: bool, total_duration_ms: float
    ) -> DebugTrace | None:
        """
        Complete a debug trace session

        Args:
            trace_id: Trace session identifier
            final_sql: Final translated SQL
            success: Whether translation was successful
            total_duration_ms: Total time for translation

        Returns:
            Completed DebugTrace or None if trace not found
        """
        if not self.enabled or trace_id not in self._traces:
            return None

        with self._lock:
            trace = self._traces[trace_id]

            # Update metadata
            trace.metadata["end_time"] = datetime.now(UTC).isoformat()
            trace.metadata["total_duration_ms"] = total_duration_ms
            trace.metadata["success"] = success
            trace.metadata["final_sql"] = final_sql
            trace.metadata["final_sql_length"] = len(final_sql)

            # Calculate summary statistics
            trace.metadata["parsing_steps_count"] = len(trace.parsing_steps)
            trace.metadata["mapping_decisions_count"] = len(trace.mapping_decisions)
            trace.metadata["warnings_count"] = len(trace.warnings)
            trace.metadata["total_parsing_time_ms"] = trace.total_parsing_time_ms

            self._log_event(
                LogLevel.INFO,
                "tracer",
                "trace_completed",
                f"Completed debug trace - Success: {success}",
                {
                    "trace_id": trace_id,
                    "success": success,
                    "total_duration_ms": total_duration_ms,
                    "parsing_steps": len(trace.parsing_steps),
                    "mapping_decisions": len(trace.mapping_decisions),
                    "warnings": len(trace.warnings),
                    "constitutional_compliance": {
                        "sla_compliant": total_duration_ms <= 5.0,
                        "sla_requirement_ms": 5.0,
                    },
                },
            )

            # Constitutional requirement: flag SLA violations
            if total_duration_ms > 5.0:
                self._log_event(
                    LogLevel.WARNING,
                    "tracer",
                    "sla_violation",
                    f"Translation exceeded 5ms SLA: {total_duration_ms}ms",
                    {
                        "trace_id": trace_id,
                        "actual_duration_ms": total_duration_ms,
                        "sla_requirement_ms": 5.0,
                        "violation_amount_ms": total_duration_ms - 5.0,
                    },
                )

            # Remove from active traces (keep completed for analysis)
            completed_trace = self._traces.pop(trace_id)
            return completed_trace

    def get_trace_summary(self, trace_id: str) -> dict[str, Any] | None:
        """
        Get summary of a trace session

        Args:
            trace_id: Trace session identifier

        Returns:
            Trace summary or None if not found
        """
        if not self.enabled or trace_id not in self._traces:
            return None

        with self._lock:
            trace = self._traces[trace_id]
            return {
                "trace_id": trace_id,
                "metadata": trace.metadata,
                "parsing_steps_count": len(trace.parsing_steps),
                "mapping_decisions_count": len(trace.mapping_decisions),
                "warnings_count": len(trace.warnings),
                "total_parsing_time_ms": trace.total_parsing_time_ms,
                "active": True,
            }

    def export_trace_json(self, trace: DebugTrace) -> str:
        """
        Export trace to JSON format

        Args:
            trace: DebugTrace to export

        Returns:
            JSON string representation
        """
        if not self.enabled:
            return "{}"

        try:
            # Convert to dictionary with proper serialization
            trace_dict = {
                "parsing_steps": [asdict(step) for step in trace.parsing_steps],
                "mapping_decisions": [asdict(decision) for decision in trace.mapping_decisions],
                "warnings": trace.warnings,
                "metadata": trace.metadata,
            }

            return json.dumps(trace_dict, indent=2, default=str)

        except Exception as e:
            self.logger.error(f"Failed to export trace to JSON: {e}")
            return "{}"

    def export_trace_html(self, trace: DebugTrace) -> str:
        """
        Export trace to HTML format for web viewing

        Args:
            trace: DebugTrace to export

        Returns:
            HTML string representation
        """
        if not self.enabled:
            return "<html><body>Debug tracing disabled</body></html>"

        try:
            html_parts = [
                "<html><head><title>IRIS SQL Translation Debug Trace</title>",
                "<style>",
                "body { font-family: monospace; margin: 20px; }",
                ".step { border: 1px solid #ccc; margin: 10px 0; padding: 10px; }",
                ".warning { background-color: #fff3cd; border-color: #ffeeba; }",
                ".error { background-color: #f8d7da; border-color: #f5c6cb; }",
                ".metadata { background-color: #f8f9fa; padding: 5px; }",
                "pre { white-space: pre-wrap; word-wrap: break-word; }",
                "</style></head><body>",
                "<h1>IRIS SQL Translation Debug Trace</h1>",
                f"<div class='metadata'><h2>Metadata</h2><pre>{json.dumps(trace.metadata, indent=2)}</pre></div>",
            ]

            # Parsing steps
            if trace.parsing_steps:
                html_parts.append("<h2>Parsing Steps</h2>")
                for i, step in enumerate(trace.parsing_steps):
                    html_parts.append("<div class='step'>")
                    html_parts.append(f"<h3>Step {i+1}: {step.step_name}</h3>")
                    html_parts.append(f"<p><strong>Duration:</strong> {step.duration_ms}ms</p>")
                    html_parts.append(f"<p><strong>Input:</strong></p><pre>{step.input_sql}</pre>")
                    html_parts.append(
                        f"<p><strong>Output:</strong></p><pre>{step.output_sql}</pre>"
                    )
                    if step.metadata:
                        html_parts.append(
                            f"<p><strong>Metadata:</strong></p><pre>{json.dumps(step.metadata, indent=2)}</pre>"
                        )
                    html_parts.append("</div>")

            # Mapping decisions
            if trace.mapping_decisions:
                html_parts.append("<h2>Mapping Decisions</h2>")
                for i, decision in enumerate(trace.mapping_decisions):
                    css_class = "warning" if decision.confidence < 0.7 else "step"
                    html_parts.append(f"<div class='{css_class}'>")
                    html_parts.append(f"<h3>Decision {i+1}: {decision.construct}</h3>")
                    html_parts.append(
                        f"<p><strong>Chosen Mapping:</strong> {decision.chosen_mapping}</p>"
                    )
                    html_parts.append(f"<p><strong>Confidence:</strong> {decision.confidence}</p>")
                    html_parts.append(
                        f"<p><strong>Available Mappings:</strong> {', '.join(decision.available_mappings)}</p>"
                    )
                    html_parts.append(f"<p><strong>Reasoning:</strong> {decision.reasoning}</p>")
                    if decision.metadata:
                        html_parts.append(
                            f"<p><strong>Metadata:</strong></p><pre>{json.dumps(decision.metadata, indent=2)}</pre>"
                        )
                    html_parts.append("</div>")

            # Warnings
            if trace.warnings:
                html_parts.append("<h2>Warnings</h2>")
                for i, warning in enumerate(trace.warnings):
                    html_parts.append("<div class='warning'>")
                    html_parts.append(f"<h3>Warning {i+1}</h3>")
                    html_parts.append(f"<p>{warning}</p>")
                    html_parts.append("</div>")

            html_parts.append("</body></html>")
            return "\n".join(html_parts)

        except Exception as e:
            self.logger.error(f"Failed to export trace to HTML: {e}")
            return f"<html><body>Error generating HTML trace: {e}</body></html>"

    def get_session_stats(self) -> dict[str, Any]:
        """
        Get statistics for the current debug session

        Returns:
            Session statistics
        """
        with self._lock:
            session_duration = (datetime.now(UTC) - self._session_start).total_seconds()

            return {
                "session_start": self._session_start.isoformat(),
                "session_duration_seconds": session_duration,
                "active_traces": len(self._traces),
                "total_events": len(self._events),
                "events_by_level": {
                    level.value: len([e for e in self._events if e.level == level])
                    for level in LogLevel
                },
                "events_by_component": {
                    component: len([e for e in self._events if e.component == component])
                    for component in {e.component for e in self._events}
                },
                "constitutional_compliance": {
                    "sla_violations": len(
                        [e for e in self._events if e.event_type == "sla_violation"]
                    ),
                    "low_confidence_mappings": len(
                        [e for e in self._events if e.event_type == "low_confidence_mapping"]
                    ),
                    "slow_parsing_steps": len(
                        [e for e in self._events if e.event_type == "slow_parsing_step"]
                    ),
                },
            }

    def _log_event(
        self,
        level: LogLevel,
        component: str,
        event_type: str,
        message: str,
        data: dict[str, Any],
        duration_ms: float | None = None,
    ):
        """Log a trace event"""
        event = TraceEvent(
            timestamp=datetime.now(UTC),
            level=level,
            component=component,
            event_type=event_type,
            message=message,
            data=data,
            duration_ms=duration_ms,
        )

        self._events.append(event)

        # Log to standard logger
        log_level = getattr(logging, level.value)
        self.logger.log(log_level, f"[{component}] {message}", extra={"data": data})


# Global tracer instance
_tracer = DebugTracer()


def get_tracer() -> DebugTracer:
    """Get the global debug tracer instance"""
    return _tracer


def start_debug_trace(trace_id: str, original_sql: str) -> DebugTrace:
    """Start debug trace (convenience function)"""
    return _tracer.start_trace(trace_id, original_sql)


def add_parsing_step(
    trace_id: str, step_name: str, input_sql: str, output_sql: str, duration_ms: float, **metadata
) -> None:
    """Add parsing step to trace (convenience function)"""
    _tracer.add_parsing_step(trace_id, step_name, input_sql, output_sql, duration_ms, **metadata)


def add_mapping_decision(
    trace_id: str,
    construct: str,
    available_mappings: list[str],
    chosen_mapping: str,
    confidence: float,
    reasoning: str,
    **metadata,
) -> None:
    """Add mapping decision to trace (convenience function)"""
    _tracer.add_mapping_decision(
        trace_id, construct, available_mappings, chosen_mapping, confidence, reasoning, **metadata
    )


def complete_debug_trace(
    trace_id: str, final_sql: str, success: bool, total_duration_ms: float
) -> DebugTrace | None:
    """Complete debug trace (convenience function)"""
    return _tracer.complete_trace(trace_id, final_sql, success, total_duration_ms)


# Export main components
__all__ = [
    "DebugTracer",
    "TraceEvent",
    "LogLevel",
    "get_tracer",
    "start_debug_trace",
    "add_parsing_step",
    "add_mapping_decision",
    "complete_debug_trace",
]

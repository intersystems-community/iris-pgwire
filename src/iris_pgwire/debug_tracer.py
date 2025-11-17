"""
Constitutional Debug Tracing for IRIS SQL Translation

Provides detailed step-by-step logging and tracing of translation operations
for transparency and debugging constitutional compliance issues.
"""

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


class TraceLevel(Enum):
    """Debug trace verbosity levels"""

    MINIMAL = "minimal"  # Only major steps
    STANDARD = "standard"  # Detailed steps
    VERBOSE = "verbose"  # All operations including regex matches


@dataclass
class TraceStep:
    """Individual step in translation trace"""

    step_id: str
    step_name: str
    timestamp: float
    duration_ms: float
    input_data: Any
    output_data: Any
    metadata: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error_message: str | None = None


@dataclass
class MappingDecision:
    """Record of translation mapping decision"""

    construct: str
    construct_type: str
    original_syntax: str
    translated_syntax: str
    decision_type: str  # DIRECT_MAPPING, CUSTOM_FUNCTION, APPROXIMATION, PASS_THROUGH
    confidence: float
    rationale: str
    alternatives_considered: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Result of translation validation check"""

    check_name: str
    passed: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class DebugTrace:
    """Complete debug trace for a translation operation"""

    trace_id: str
    sql_original: str
    sql_translated: str
    start_time: float
    end_time: float
    total_duration_ms: float

    # Constitutional compliance metrics
    sla_compliant: bool
    constructs_detected: int
    constructs_translated: int

    # Detailed trace data
    parsing_steps: list[TraceStep] = field(default_factory=list)
    mapping_decisions: list[MappingDecision] = field(default_factory=list)
    validation_results: list[ValidationResult] = field(default_factory=list)

    # Summary
    success: bool = True
    error_message: str | None = None
    warnings: list[str] = field(default_factory=list)


class DebugTracer:
    """
    Constitutional Debug Tracer

    Provides comprehensive tracing for translation operations
    to ensure transparency and debugging capability.
    """

    def __init__(self, trace_level: TraceLevel = TraceLevel.STANDARD):
        self.trace_level = trace_level
        self.current_trace: DebugTrace | None = None
        self._step_counter = 0

    def start_trace(self, sql: str) -> str:
        """Start a new debug trace session"""
        trace_id = str(uuid.uuid4())[:8]
        self.current_trace = DebugTrace(
            trace_id=trace_id,
            sql_original=sql,
            sql_translated="",  # Will be updated
            start_time=time.perf_counter(),
            end_time=0.0,
            total_duration_ms=0.0,
            sla_compliant=False,
            constructs_detected=0,
            constructs_translated=0,
        )
        self._step_counter = 0

        logger.info(
            "Constitutional debug trace started",
            trace_id=trace_id,
            sql_length=len(sql),
            trace_level=self.trace_level.value,
        )

        return trace_id

    def add_parsing_step(
        self,
        step_name: str,
        input_data: Any,
        output_data: Any,
        duration_ms: float,
        metadata: dict | None = None,
    ) -> None:
        """Add a parsing step to the current trace"""
        if not self.current_trace:
            return

        step = TraceStep(
            step_id=f"step_{self._step_counter:03d}",
            step_name=step_name,
            timestamp=time.perf_counter(),
            duration_ms=duration_ms,
            input_data=input_data,
            output_data=output_data,
            metadata=metadata or {},
        )

        self.current_trace.parsing_steps.append(step)
        self._step_counter += 1

        if self.trace_level == TraceLevel.VERBOSE:
            logger.debug(
                "Parsing step completed",
                trace_id=self.current_trace.trace_id,
                step_name=step_name,
                duration_ms=duration_ms,
            )

    def add_mapping_decision(
        self,
        construct: str,
        construct_type: str,
        original: str,
        translated: str,
        decision_type: str,
        confidence: float,
        rationale: str,
        alternatives: list[str] | None = None,
    ) -> None:
        """Record a translation mapping decision"""
        if not self.current_trace:
            return

        decision = MappingDecision(
            construct=construct,
            construct_type=construct_type,
            original_syntax=original,
            translated_syntax=translated,
            decision_type=decision_type,
            confidence=confidence,
            rationale=rationale,
            alternatives_considered=alternatives or [],
        )

        self.current_trace.mapping_decisions.append(decision)

        logger.debug(
            "Mapping decision recorded",
            trace_id=self.current_trace.trace_id,
            construct=construct,
            decision_type=decision_type,
            confidence=confidence,
        )

    def add_validation_result(
        self, check_name: str, passed: bool, message: str, details: dict | None = None
    ) -> None:
        """Add a validation result to the trace"""
        if not self.current_trace:
            return

        result = ValidationResult(
            check_name=check_name, passed=passed, message=message, details=details or {}
        )

        self.current_trace.validation_results.append(result)

        if not passed:
            logger.warning(
                "Validation check failed",
                trace_id=self.current_trace.trace_id,
                check_name=check_name,
                message=message,
            )

    def add_warning(self, warning: str) -> None:
        """Add a warning to the current trace"""
        if not self.current_trace:
            return

        self.current_trace.warnings.append(warning)
        logger.warning("Translation warning", trace_id=self.current_trace.trace_id, warning=warning)

    def finish_trace(
        self,
        translated_sql: str,
        constructs_detected: int,
        constructs_translated: int,
        success: bool = True,
        error_message: str | None = None,
    ) -> DebugTrace:
        """Complete the current trace and return results"""
        if not self.current_trace:
            raise ValueError("No active trace to finish")

        end_time = time.perf_counter()
        duration_ms = (end_time - self.current_trace.start_time) * 1000

        # Update trace with final results
        self.current_trace.sql_translated = translated_sql
        self.current_trace.end_time = end_time
        self.current_trace.total_duration_ms = duration_ms
        self.current_trace.sla_compliant = duration_ms <= 5.0  # Constitutional requirement
        self.current_trace.constructs_detected = constructs_detected
        self.current_trace.constructs_translated = constructs_translated
        self.current_trace.success = success
        self.current_trace.error_message = error_message

        # Validate constitutional compliance
        self._validate_constitutional_compliance()

        logger.info(
            "Constitutional debug trace completed",
            trace_id=self.current_trace.trace_id,
            duration_ms=duration_ms,
            sla_compliant=self.current_trace.sla_compliant,
            constructs_translated=constructs_translated,
            success=success,
        )

        completed_trace = self.current_trace
        self.current_trace = None
        return completed_trace

    def _validate_constitutional_compliance(self) -> None:
        """Validate constitutional requirements and add results"""
        if not self.current_trace:
            return

        # 1. SLA Compliance (5ms requirement)
        self.add_validation_result(
            check_name="sla_compliance",
            passed=self.current_trace.sla_compliant,
            message=f"Translation completed in {self.current_trace.total_duration_ms:.2f}ms "
            f"({'within' if self.current_trace.sla_compliant else 'exceeds'} 5ms SLA)",
            details={"duration_ms": self.current_trace.total_duration_ms, "sla_limit_ms": 5.0},
        )

        # 2. Translation completeness
        if self.current_trace.constructs_detected > 0:
            completeness_rate = (
                self.current_trace.constructs_translated / self.current_trace.constructs_detected
            ) * 100
            self.add_validation_result(
                check_name="translation_completeness",
                passed=completeness_rate >= 90.0,  # 90% threshold
                message=f"Translated {completeness_rate:.1f}% of detected IRIS constructs",
                details={
                    "detected": self.current_trace.constructs_detected,
                    "translated": self.current_trace.constructs_translated,
                    "rate": completeness_rate,
                },
            )

        # 3. Semantic equivalence (basic check)
        sql_length_ratio = len(self.current_trace.sql_translated) / len(
            self.current_trace.sql_original
        )
        self.add_validation_result(
            check_name="semantic_equivalence",
            passed=0.5 <= sql_length_ratio <= 3.0,  # Reasonable length ratio
            message=f"Translated SQL length ratio: {sql_length_ratio:.2f}",
            details={
                "original_length": len(self.current_trace.sql_original),
                "translated_length": len(self.current_trace.sql_translated),
                "ratio": sql_length_ratio,
            },
        )

        # 4. Error handling
        self.add_validation_result(
            check_name="error_handling",
            passed=self.current_trace.success,
            message=(
                "Translation completed without errors"
                if self.current_trace.success
                else f"Translation failed: {self.current_trace.error_message}"
            ),
            details={"error_occurred": not self.current_trace.success},
        )


# Global debug tracer instance
_global_tracer: DebugTracer | None = None


def get_tracer(trace_level: TraceLevel = TraceLevel.STANDARD) -> DebugTracer:
    """Get global debug tracer instance"""
    global _global_tracer
    if _global_tracer is None:
        _global_tracer = DebugTracer(trace_level)
    return _global_tracer


def set_trace_level(level: TraceLevel) -> None:
    """Set global trace level"""
    global _global_tracer
    if _global_tracer:
        _global_tracer.trace_level = level
    else:
        _global_tracer = DebugTracer(level)


def reset_tracer() -> None:
    """Reset global tracer (for testing)"""
    global _global_tracer
    _global_tracer = None

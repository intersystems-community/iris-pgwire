"""
Performance Monitoring and Constitutional SLA Enforcement

Implements comprehensive performance monitoring with 5ms SLA enforcement,
real-time metrics collection, and constitutional compliance reporting.

Constitutional Compliance: Sub-5ms translation SLA with detailed monitoring.
"""

import os
import statistics
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

# Global switch for performance monitoring
MONITOR_ENABLED = os.getenv("IRIS_PGWIRE_PERF_MONITOR", "false").lower() == "true"

try:
    from prometheus_client import Counter, Summary

    HAS_PROMETHEUS = True
except ImportError:
    HAS_PROMETHEUS = False

    # Dummy classes for LSP and runtime when prometheus is missing
    class DummyMetric:
        def labels(self, *args, **kwargs):
            return self

        def inc(self, *args, **kwargs):
            pass

        def observe(self, *args, **kwargs):
            pass

    Counter = Summary = lambda *args, **kwargs: DummyMetric()

TRANSLATION_LATENCY = Summary(
    "iris_pgwire_translation_latency_ms", "SQL translation latency in milliseconds", ["component"]
)
BULK_INSERT_THROUGHPUT = Summary(
    "iris_pgwire_bulk_insert_throughput_rows_per_sec", "Bulk insert throughput in rows per second"
)
SLA_VIOLATIONS = Counter(
    "iris_pgwire_sla_violations_total",
    "Total number of constitutional SLA violations",
    ["component", "severity"],
)


class MetricType(Enum):
    """Types of performance metrics"""

    TRANSLATION_TIME = "translation_time"
    CACHE_LOOKUP_TIME = "cache_lookup_time"
    VALIDATION_TIME = "validation_time"
    PARSING_TIME = "parsing_time"
    MAPPING_TIME = "mapping_time"
    API_RESPONSE_TIME = "api_response_time"
    BULK_INSERT_THROUGHPUT = "bulk_insert_throughput"
    MEMORY_OVERHEAD = "memory_overhead"


class SLAStatus(Enum):
    """SLA compliance status"""

    COMPLIANT = "compliant"
    WARNING = "warning"  # Approaching SLA threshold
    VIOLATION = "violation"  # SLA violated
    CRITICAL = "critical"  # Multiple consecutive violations


@dataclass
class PerformanceMetric:
    """Individual performance metric record"""

    metric_type: MetricType
    value_ms: float
    timestamp: datetime
    component: str
    session_id: str | None = None
    trace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SLAViolation:
    """Record of SLA violation"""

    violation_id: str
    metric_type: MetricType
    actual_value_ms: float
    sla_threshold_ms: float
    violation_amount_ms: float
    timestamp: datetime
    component: str
    severity: str
    trace_id: str | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class ComponentStats:
    """Performance statistics for a component"""

    component_name: str
    total_operations: int
    total_time_ms: float
    average_time_ms: float
    min_time_ms: float
    max_time_ms: float
    p50_time_ms: float
    p95_time_ms: float
    p99_time_ms: float
    sla_violations: int
    sla_compliance_rate: float
    last_updated: datetime


@dataclass
class ConstitutionalReport:
    """Constitutional compliance report"""

    overall_compliance_rate: float
    sla_requirement_ms: float
    total_violations: int
    violation_rate: float
    critical_violations: int
    status: SLAStatus
    performance_metrics: dict[str, Any]
    component_compliance: dict[str, ComponentStats]
    recent_violations: list[SLAViolation]
    recommendations: list[str]
    report_timestamp: datetime


class PerformanceMonitor:
    """
    Performance monitor with constitutional SLA enforcement

    Features:
    - Real-time performance metric collection
    - 5ms SLA enforcement and violation tracking
    - Component-level performance analysis
    - Constitutional compliance reporting
    - Automatic alerting for SLA violations
    - Historical performance trend analysis
    """

    def __init__(self, sla_threshold_ms: float = 5.0, history_size: int = 10000):
        """
        Initialize performance monitor

        Args:
            sla_threshold_ms: SLA threshold in milliseconds (constitutional requirement: 5ms)
            history_size: Number of metrics to keep in memory
        """
        self.sla_threshold_ms = sla_threshold_ms
        self.history_size = history_size

        # Thread-safe metric storage
        self._lock = threading.RLock()
        self._metrics: deque[PerformanceMetric] = deque(maxlen=history_size)
        self._violations: deque[SLAViolation] = deque(maxlen=1000)  # Keep last 1000 violations

        # Component-specific tracking
        self._component_metrics: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=1000))
        self._component_violations: dict[str, int] = defaultdict(int)

        # Real-time statistics
        self._total_operations = 0
        self._total_violations = 0
        self._consecutive_violations = 0
        self._start_time = datetime.now(UTC)

        # Alert thresholds
        self.warning_threshold_ms = sla_threshold_ms * 0.8  # 80% of SLA
        self.critical_violation_threshold = 5  # Consecutive violations before critical

    def record_metric(
        self,
        metric_type: MetricType | str,
        value_ms: float,
        component: str,
        session_id: str | None = None,
        trace_id: str | None = None,
        **metadata,
    ) -> SLAViolation | None:
        """
        Record a performance metric

        Args:
            metric_type: Type of metric being recorded
            value_ms: Metric value in milliseconds
            component: Component that generated the metric
            session_id: Optional session identifier
            trace_id: Optional trace identifier
            **metadata: Additional metric metadata

        Returns:
            SLA violation record if threshold exceeded, None otherwise
        """
        if not MONITOR_ENABLED:
            return None

        timestamp = datetime.now(UTC)

        with self._lock:
            # Create metric record
            metric = PerformanceMetric(
                metric_type=metric_type,
                value_ms=value_ms,
                timestamp=timestamp,
                component=component,
                session_id=session_id,
                trace_id=trace_id,
                metadata=metadata,
            )

            # Store metric
            self._metrics.append(metric)
            self._component_metrics[component].append(value_ms)
            self._total_operations += 1

            # Check SLA compliance
            violation = None
            if value_ms > self.sla_threshold_ms:
                violation = self._record_sla_violation(metric)
                if HAS_PROMETHEUS:
                    SLA_VIOLATIONS.labels(component=component, severity=violation.severity).inc()

            if HAS_PROMETHEUS:
                if metric_type == MetricType.TRANSLATION_TIME:
                    TRANSLATION_LATENCY.labels(component=component).observe(value_ms)
                elif metric_type == MetricType.BULK_INSERT_THROUGHPUT:
                    BULK_INSERT_THROUGHPUT.observe(value_ms)

            # Update consecutive violation tracking
            if violation:
                self._consecutive_violations += 1
            else:
                self._consecutive_violations = 0

            return violation

    def _record_sla_violation(self, metric: PerformanceMetric) -> SLAViolation:
        """Record an SLA violation"""
        violation_amount = metric.value_ms - self.sla_threshold_ms

        # Determine severity
        if self._consecutive_violations >= self.critical_violation_threshold:
            severity: Literal["critical", "major", "minor"] = "critical"
        elif violation_amount > self.sla_threshold_ms:  # More than double the SLA
            severity: Literal["critical", "major", "minor"] = "major"
        else:
            severity: Literal["critical", "major", "minor"] = "minor"

        violation = SLAViolation(
            violation_id=f"v_{int(time.time() * 1000)}_{self._total_violations}",
            metric_type=metric.metric_type,
            actual_value_ms=metric.value_ms,
            sla_threshold_ms=self.sla_threshold_ms,
            violation_amount_ms=violation_amount,
            timestamp=metric.timestamp,
            component=metric.component,
            severity=severity,
            trace_id=metric.trace_id,
            context={
                "session_id": metric.session_id,
                "consecutive_violations": self._consecutive_violations,
                "metadata": metric.metadata,
            },
        )

        self._violations.append(violation)
        self._component_violations[metric.component] += 1
        self._total_violations += 1

        return violation

    def get_component_stats(self, component: str) -> ComponentStats | None:
        """
        Get performance statistics for a specific component

        Args:
            component: Component name

        Returns:
            Component statistics or None if no data
        """
        with self._lock:
            if component not in self._component_metrics:
                return None

            times = list(self._component_metrics[component])
            if not times:
                return None

            violations = self._component_violations[component]
            compliance_rate = max(0.0, 1.0 - (violations / len(times)))

            return ComponentStats(
                component_name=component,
                total_operations=len(times),
                total_time_ms=sum(times),
                average_time_ms=statistics.mean(times),
                min_time_ms=min(times),
                max_time_ms=max(times),
                p50_time_ms=statistics.median(times),
                p95_time_ms=self._percentile(times, 0.95),
                p99_time_ms=self._percentile(times, 0.99),
                sla_violations=violations,
                sla_compliance_rate=compliance_rate,
                last_updated=datetime.now(UTC),
            )

    def get_constitutional_report(self) -> ConstitutionalReport:
        """
        Generate comprehensive constitutional compliance report

        Returns:
            Constitutional compliance report with detailed metrics
        """
        with self._lock:
            # Calculate overall compliance
            compliance_rate = max(
                0.0, 1.0 - (self._total_violations / max(self._total_operations, 1))
            )
            violation_rate = self._total_violations / max(self._total_operations, 1)

            # Determine overall status
            if self._consecutive_violations >= self.critical_violation_threshold:
                status = SLAStatus.CRITICAL
            elif self._total_violations > 0:
                if compliance_rate < 0.95:  # Less than 95% compliance
                    status = SLAStatus.VIOLATION
                else:
                    status = SLAStatus.WARNING
            else:
                status = SLAStatus.COMPLIANT

            # Get component compliance
            component_compliance = {}
            for component in self._component_metrics:
                stats = self.get_component_stats(component)
                if stats:
                    component_compliance[component] = stats

            # Get recent violations (last 10)
            recent_violations = list(self._violations)[-10:] if self._violations else []

            # Calculate performance metrics
            all_times = [m.value_ms for m in self._metrics]
            performance_metrics = {}
            if all_times:
                performance_metrics = {
                    "total_operations": self._total_operations,
                    "avg_time_ms": statistics.mean(all_times),
                    "min_time_ms": min(all_times),
                    "max_time_ms": max(all_times),
                    "p50_time_ms": statistics.median(all_times),
                    "p95_time_ms": self._percentile(all_times, 0.95),
                    "p99_time_ms": self._percentile(all_times, 0.99),
                    "uptime_seconds": (
                        datetime.now(UTC) - self._start_time
                    ).total_seconds(),
                }

            # Generate recommendations
            recommendations = self._generate_recommendations(
                status, compliance_rate, component_compliance
            )

            # Count critical violations
            critical_violations = sum(1 for v in self._violations if v.severity == "critical")

            return ConstitutionalReport(
                overall_compliance_rate=compliance_rate,
                sla_requirement_ms=self.sla_threshold_ms,
                total_violations=self._total_violations,
                violation_rate=violation_rate,
                critical_violations=critical_violations,
                status=status,
                performance_metrics=performance_metrics,
                component_compliance=component_compliance,
                recent_violations=recent_violations,
                recommendations=recommendations,
                report_timestamp=datetime.now(UTC),
            )

    def get_real_time_status(self) -> dict[str, Any]:
        """
        Get real-time performance status

        Returns:
            Real-time status information
        """
        with self._lock:
            # Get recent metrics (last 100)
            recent_metrics = list(self._metrics)[-100:] if self._metrics else []
            recent_times = [m.value_ms for m in recent_metrics]

            # Calculate current performance
            current_avg = statistics.mean(recent_times) if recent_times else 0.0
            current_p95 = self._percentile(recent_times, 0.95) if recent_times else 0.0

            # SLA status
            sla_status = "compliant"
            if self._consecutive_violations >= self.critical_violation_threshold:
                sla_status = "critical"
            elif self._consecutive_violations > 0:
                sla_status = "violation"
            elif current_p95 > self.warning_threshold_ms:
                sla_status = "warning"

            return {
                "timestamp": datetime.now(UTC).isoformat(),
                "sla_status": sla_status,
                "sla_threshold_ms": self.sla_threshold_ms,
                "current_avg_ms": current_avg,
                "current_p95_ms": current_p95,
                "consecutive_violations": self._consecutive_violations,
                "total_operations": self._total_operations,
                "total_violations": self._total_violations,
                "operations_per_second": self._calculate_ops_per_second(),
                "memory_usage": {
                    "metrics_stored": len(self._metrics),
                    "violations_stored": len(self._violations),
                    "components_tracked": len(self._component_metrics),
                },
            }

    def clear_metrics(self, component: str | None = None) -> int:
        """
        Clear performance metrics

        Args:
            component: Optional component name to clear (clears all if None)

        Returns:
            Number of metrics cleared
        """
        with self._lock:
            if component:
                # Clear specific component
                cleared = len(self._component_metrics.get(component, []))
                if component in self._component_metrics:
                    self._component_metrics[component].clear()
                    self._component_violations[component] = 0
                return cleared
            else:
                # Clear all metrics
                cleared = len(self._metrics)
                self._metrics.clear()
                self._violations.clear()
                self._component_metrics.clear()
                self._component_violations.clear()
                self._total_operations = 0
                self._total_violations = 0
                self._consecutive_violations = 0
                self._start_time = datetime.now(UTC)
                return cleared

    def export_metrics(self, format_type: str = "json") -> str:
        """
        Export metrics for external analysis

        Args:
            format_type: Export format (json, csv)

        Returns:
            Exported metrics string
        """
        with self._lock:
            if format_type.lower() == "json":
                import json

                metrics_data = {
                    "constitutional_report": self.get_constitutional_report().__dict__,
                    "real_time_status": self.get_real_time_status(),
                    "component_stats": {
                        name: stats.__dict__ if stats else None
                        for name, stats in {
                            comp: self.get_component_stats(comp) for comp in self._component_metrics
                        }.items()
                    },
                    "export_timestamp": datetime.now(UTC).isoformat(),
                }
                return json.dumps(metrics_data, indent=2, default=str)
            elif format_type.lower() == "csv":
                # Simple CSV export of recent metrics
                csv_lines = ["timestamp,component,metric_type,value_ms,sla_violation"]
                for metric in list(self._metrics)[-1000:]:  # Last 1000 metrics
                    violation = "yes" if metric.value_ms > self.sla_threshold_ms else "no"
                    csv_lines.append(
                        f"{metric.timestamp.isoformat()},{metric.component},"
                        f"{metric.metric_type.value},{metric.value_ms},{violation}"
                    )
                return "\n".join(csv_lines)
            else:
                raise ValueError(f"Unsupported export format: {format_type}")

    def _percentile(self, values: list[float], percentile: float) -> float:
        """Calculate percentile value"""
        if not values:
            return 0.0
        sorted_values = sorted(values)
        index = int(percentile * len(sorted_values))
        index = min(index, len(sorted_values) - 1)
        return sorted_values[index]

    def _calculate_ops_per_second(self) -> float:
        """Calculate operations per second"""
        uptime = (datetime.now(UTC) - self._start_time).total_seconds()
        return self._total_operations / uptime if uptime > 0 else 0.0

    def _generate_recommendations(
        self,
        status: SLAStatus | str,
        compliance_rate: float,
        component_compliance: dict[str, ComponentStats],
    ) -> list[str]:
        """Generate performance improvement recommendations"""
        recommendations = []

        if status == SLAStatus.CRITICAL:
            recommendations.append("CRITICAL: Immediate performance optimization required")
            recommendations.append("Consider scaling resources or optimizing hot paths")

        if compliance_rate < 0.95:
            recommendations.append("SLA compliance below 95% - investigate performance bottlenecks")

        # Component-specific recommendations
        for component, stats in component_compliance.items():
            if stats.sla_compliance_rate < 0.9:
                recommendations.append(
                    f"Component '{component}' has low compliance rate: {stats.sla_compliance_rate:.2f}"
                )

            if stats.p95_time_ms > self.sla_threshold_ms * 2:
                recommendations.append(
                    f"Component '{component}' P95 latency very high: {stats.p95_time_ms:.2f}ms"
                )

        # General recommendations
        if not recommendations:
            recommendations.append("Performance within constitutional requirements")

        return recommendations


# Global monitor instance
_monitor = PerformanceMonitor()


def get_monitor() -> PerformanceMonitor:
    """Get the global performance monitor instance"""
    return _monitor


def record_translation_time(
    value_ms: float,
    component: str = "translator",
    session_id: str | None = None,
    trace_id: str | None = None,
    **metadata,
) -> SLAViolation | None:
    """Record translation time metric (convenience function)"""
    return _monitor.record_metric(
        MetricType.TRANSLATION_TIME, value_ms, component, session_id, trace_id, **metadata
    )


def get_constitutional_compliance() -> ConstitutionalReport:
    """Get constitutional compliance report (convenience function)"""
    return _monitor.get_constitutional_report()


# Context manager for automatic metric recording
class PerformanceTracker:
    """Context manager for automatic performance tracking"""

    def __init__(
        self,
        metric_type: MetricType,
        component: str,
        session_id: str | None = None,
        trace_id: str | None = None,
        **metadata,
    ):
        self.metric_type = metric_type
        self.component = component
        self.session_id = session_id
        self.trace_id = trace_id
        self.metadata = metadata
        self.start_time = None
        self.violation = None

    def __enter__(self):
        if not MONITOR_ENABLED:
            return self
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if MONITOR_ENABLED and self.start_time:
            # Use perf_counter for duration to avoid timezone/clock-jump issues
            elapsed_ms = (time.perf_counter() - self.start_time) * 1000

            # Use a safe try-except to ensure performance monitoring never crashes the main path
            try:
                self.violation = _monitor.record_metric(
                    self.metric_type,
                    elapsed_ms,
                    self.component,
                    self.session_id,
                    self.trace_id,
                    **self.metadata,
                )
            except Exception:
                # Silently ignore monitoring errors in production-like environments
                pass


# Export main components
__all__ = [
    "PerformanceMonitor",
    "PerformanceMetric",
    "SLAViolation",
    "ComponentStats",
    "ConstitutionalReport",
    "MetricType",
    "SLAStatus",
    "PerformanceTracker",
    "get_monitor",
    "record_translation_time",
    "get_constitutional_compliance",
]

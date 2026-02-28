"""
Performance Monitoring and Constitutional SLA Enforcement

Implements comprehensive performance monitoring with 5ms SLA enforcement,
real-time metrics collection, and constitutional compliance reporting.

Constitutional Compliance: Sub-5ms translation SLA with detailed monitoring.
"""

import json
import os
import statistics
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

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
    """Performance monitoring with constitutional SLA enforcement."""

    def __init__(self, sla_threshold_ms: float = 5.0, history_size: int = 10000):
        self.sla_threshold_ms = sla_threshold_ms
        self.history_size = history_size

        self._lock = threading.RLock()
        self._metrics: deque[PerformanceMetric] = deque(maxlen=history_size)
        self._violations: deque[SLAViolation] = deque(maxlen=1000)
        self._component_metrics: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=1000))
        self._component_violations: dict[str, int] = defaultdict(int)

        self._total_operations = 0
        self._total_violations = 0
        self._consecutive_violations = 0
        self._start_time = datetime.now(UTC)

        self.warning_threshold_ms = sla_threshold_ms * 0.8
        self.critical_violation_threshold = 5

    def record_metric(
        self,
        metric_type: MetricType | str,
        value_ms: float,
        component: str,
        session_id: str | None = None,
        trace_id: str | None = None,
        **metadata,
    ) -> SLAViolation | None:
        if not MONITOR_ENABLED:
            return None

        metric = PerformanceMetric(
            metric_type=self._resolve_metric_type(metric_type),
            value_ms=value_ms,
            timestamp=datetime.now(UTC),
            component=component,
            session_id=session_id,
            trace_id=trace_id,
            metadata=metadata,
        )

        with self._lock:
            self._append_metric(metric)
            violation = self._evaluate_metric(metric)
            return violation

    def _append_metric(self, metric: PerformanceMetric) -> None:
        self._metrics.append(metric)
        self._component_metrics[metric.component].append(metric.value_ms)
        self._total_operations += 1

    def _evaluate_metric(self, metric: PerformanceMetric) -> SLAViolation | None:
        violation = None

        if metric.value_ms > self.sla_threshold_ms:
            violation = self._record_sla_violation(metric)
            self._consecutive_violations += 1
            self._publish_violation(metric.component, violation.severity)
        else:
            self._consecutive_violations = 0

        self._observe_prometheus(metric)
        return violation

    def _observe_prometheus(self, metric: PerformanceMetric) -> None:
        if not HAS_PROMETHEUS:
            return

        metric_type = metric.metric_type
        if metric_type == MetricType.TRANSLATION_TIME:
            TRANSLATION_LATENCY.labels(component=metric.component).observe(metric.value_ms)
        elif metric_type == MetricType.BULK_INSERT_THROUGHPUT:
            BULK_INSERT_THROUGHPUT.observe(metric.value_ms)

    def _publish_violation(self, component: str, severity: str) -> None:
        if not HAS_PROMETHEUS:
            return
        SLA_VIOLATIONS.labels(component=component, severity=severity).inc()

    def _resolve_metric_type(self, metric_type: MetricType | str) -> MetricType:
        if isinstance(metric_type, MetricType):
            return metric_type
        try:
            return MetricType(metric_type)
        except ValueError:
            return MetricType.TRANSLATION_TIME

    def _record_sla_violation(self, metric: PerformanceMetric) -> SLAViolation:
        """Record an SLA violation"""
        violation_amount = metric.value_ms - self.sla_threshold_ms

        # Determine severity
        if self._consecutive_violations >= self.critical_violation_threshold:
            severity = "critical"
        elif violation_amount > self.sla_threshold_ms:  # More than double the SLA
            severity = "major"
        else:
            severity = "minor"

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
        with self._lock:
            compliance_rate, violation_rate, status = self._summarize_compliance()
            component_compliance = self._collect_component_compliance()
            all_times = [m.value_ms for m in self._metrics]
            performance_metrics = self._build_performance_metrics(all_times)
            recommendations = self._generate_recommendations(
                status, compliance_rate, component_compliance
            )
            recent_violations = self._recent_violations_snapshot()
            critical_violations = self._count_critical_violations()

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

    def _summarize_compliance(self) -> tuple[float, float, SLAStatus]:
        total_ops = max(self._total_operations, 1)
        compliance_rate = max(0.0, 1.0 - (self._total_violations / total_ops))
        violation_rate = self._total_violations / total_ops
        status = self._determine_status(compliance_rate)
        return compliance_rate, violation_rate, status

    def _determine_status(self, compliance_rate: float) -> SLAStatus:
        if self._consecutive_violations >= self.critical_violation_threshold:
            return SLAStatus.CRITICAL
        if self._total_violations > 0:
            return SLAStatus.VIOLATION if compliance_rate < 0.95 else SLAStatus.WARNING
        return SLAStatus.COMPLIANT

    def _collect_component_compliance(self) -> dict[str, ComponentStats]:
        component_compliance: dict[str, ComponentStats] = {}
        for component in self._component_metrics:
            stats = self.get_component_stats(component)
            if stats:
                component_compliance[component] = stats
        return component_compliance

    def _build_performance_metrics(self, values: list[float]) -> dict[str, Any]:
        if not values:
            return {}
        return {
            "total_operations": self._total_operations,
            "avg_time_ms": statistics.mean(values),
            "min_time_ms": min(values),
            "max_time_ms": max(values),
            "p50_time_ms": statistics.median(values),
            "p95_time_ms": self._percentile(values, 0.95),
            "p99_time_ms": self._percentile(values, 0.99),
            "uptime_seconds": (datetime.now(UTC) - self._start_time).total_seconds(),
        }

    def _recent_violations_snapshot(self, limit: int = 10) -> list[SLAViolation]:
        return list(self._violations)[-limit:]

    def _count_critical_violations(self) -> int:
        return sum(1 for violation in self._violations if violation.severity == "critical")

    def _recent_metrics_snapshot(self, limit: int | None = None) -> list[PerformanceMetric]:
        metrics = list(self._metrics)
        if limit is None:
            return metrics
        return metrics[-limit:]

    def get_real_time_status(self) -> dict[str, Any]:
        """
        Get real-time performance status

        Returns:
            Real-time status information
        """
        with self._lock:
            # Get recent metrics (last 100)
            recent_metrics = self._recent_metrics_snapshot(100)
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
                for metric in self._recent_metrics_snapshot(1000):
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

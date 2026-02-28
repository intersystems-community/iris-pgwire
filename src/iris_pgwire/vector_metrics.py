"""
Vector Query Optimizer Metrics Export

Provides metrics export and alerting for constitutional SLA compliance monitoring.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class SLAAlert:
    """SLA violation alert"""

    timestamp: float
    violation_type: str  # 'performance', 'error_rate', 'availability'
    severity: str  # 'warning', 'critical'
    message: str
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert alert to dictionary"""
        return {
            "timestamp": self.timestamp,
            "violation_type": self.violation_type,
            "severity": self.severity,
            "message": self.message,
            "metrics": self.metrics,
        }


class VectorMetricsCollector:
    """Collect and export vector optimizer metrics for monitoring"""

    # Alert thresholds
    SLA_COMPLIANCE_WARNING_THRESHOLD = 98.0  # Warn if compliance drops below 98%
    SLA_COMPLIANCE_CRITICAL_THRESHOLD = 95.0  # Critical if compliance drops below 95%
    TRANSFORMATION_TIME_WARNING_MS = 4.0  # Warn if approaching SLA limit
    TRANSFORMATION_TIME_CRITICAL_MS = 5.0  # Critical if exceeding SLA

    def __init__(self):
        self.alerts: list[SLAAlert] = []
        self.alert_callbacks = []

    def _create_alert(
        self,
        stats: dict[str, Any],
        violation_type: str,
        severity: str,
        message: str,
    ) -> SLAAlert:
        """Create an SLA alert and log it at the appropriate level."""
        alert = SLAAlert(
            timestamp=time.time(),
            violation_type=violation_type,
            severity=severity,
            message=message,
            metrics=stats,
        )
        if severity == "critical":
            logger.error(f"🚨 {message}")
        else:
            logger.warning(f"⚠️ {message}")
        return alert

    def _evaluate_threshold_alerts(
        self,
        stats: dict[str, Any],
        value: float,
        violation_type: str,
        thresholds: tuple[tuple[str, float, str, Callable[[float, float], bool]], ...],
    ) -> list[SLAAlert]:
        for severity, threshold, template, comparator in thresholds:
            if comparator(value, threshold):
                message = template.format(value=value, threshold=threshold)
                return [self._create_alert(stats, violation_type, severity, message)]
        return []

    def _append_metric(
        self,
        metrics: list[str],
        metric_name: str,
        help_text: str,
        metric_type: str,
        value: Any,
    ) -> None:
        metrics.append(f"# HELP {metric_name} {help_text}")
        metrics.append(f"# TYPE {metric_name} {metric_type}")
        metrics.append(f"{metric_name} {value}")

    def check_sla_compliance(self, stats: dict[str, Any]) -> list[SLAAlert]:
        """Check SLA compliance and generate alerts if needed"""
        alerts = []

        alerts.extend(
            self._evaluate_threshold_alerts(
                stats,
                stats.get("sla_compliance_rate", 100.0),
                "performance",
                (
                    (
                        "critical",
                        self.SLA_COMPLIANCE_CRITICAL_THRESHOLD,
                        "CRITICAL: SLA compliance rate {value}% below threshold {threshold}%",
                        lambda value, threshold: value < threshold,
                    ),
                    (
                        "warning",
                        self.SLA_COMPLIANCE_WARNING_THRESHOLD,
                        "WARNING: SLA compliance rate {value}% below threshold {threshold}%",
                        lambda value, threshold: value < threshold,
                    ),
                ),
            )
        )

        alerts.extend(
            self._evaluate_threshold_alerts(
                stats,
                stats.get("avg_transformation_time_ms", 0),
                "performance",
                (
                    (
                        "critical",
                        self.TRANSFORMATION_TIME_CRITICAL_MS,
                        "CRITICAL: Average transformation time {value}ms exceeds SLA {threshold}ms",
                        lambda value, threshold: value > threshold,
                    ),
                    (
                        "warning",
                        self.TRANSFORMATION_TIME_WARNING_MS,
                        "WARNING: Average transformation time {value}ms approaching SLA limit {threshold}ms",
                        lambda value, threshold: value > threshold,
                    ),
                ),
            )
        )

        # Store alerts
        self.alerts.extend(alerts)

        # Trigger callbacks
        for callback in self.alert_callbacks:
            for alert in alerts:
                try:
                    callback(alert)
                except Exception as e:
                    logger.error(f"Alert callback failed: {str(e)}")

        return alerts

    def export_prometheus_metrics(self, stats: dict[str, Any]) -> str:
        """Export metrics in Prometheus format"""
        metrics: list[str] = []
        self._append_metric(
            metrics,
            "vector_optimizer_total_optimizations",
            "Total number of vector query optimizations",
            "counter",
            stats.get("total_optimizations", 0),
        )
        self._append_metric(
            metrics,
            "vector_optimizer_sla_violations",
            "Total number of SLA violations",
            "counter",
            stats.get("sla_violations", 0),
        )
        self._append_metric(
            metrics,
            "vector_optimizer_sla_compliance_rate",
            "SLA compliance rate percentage",
            "gauge",
            stats.get("sla_compliance_rate", 100.0),
        )
        self._append_metric(
            metrics,
            "vector_optimizer_avg_transformation_time_ms",
            "Average transformation time in milliseconds",
            "gauge",
            stats.get("avg_transformation_time_ms", 0),
        )
        self._append_metric(
            metrics,
            "vector_optimizer_max_transformation_time_ms",
            "Maximum transformation time in milliseconds",
            "gauge",
            stats.get("max_transformation_time_ms", 0),
        )

        return "\n".join(metrics)

    def export_json_metrics(self, stats: dict[str, Any]) -> dict[str, Any]:
        """Export metrics in JSON format"""
        return {
            "timestamp": time.time(),
            "service": "vector_query_optimizer",
            "constitutional_compliance": {
                "sla_ms": stats.get("constitutional_sla_ms", 5.0),
                "compliance_rate": stats.get("sla_compliance_rate", 100.0),
                "total_operations": stats.get("total_optimizations", 0),
                "violations": stats.get("sla_violations", 0),
                "status": (
                    "compliant"
                    if stats.get("sla_compliance_rate", 100.0) >= 95.0
                    else "non_compliant"
                ),
            },
            "performance": {
                "avg_transformation_time_ms": stats.get("avg_transformation_time_ms", 0),
                "min_transformation_time_ms": stats.get("min_transformation_time_ms", 0),
                "max_transformation_time_ms": stats.get("max_transformation_time_ms", 0),
                "sample_size": stats.get("recent_sample_size", 0),
            },
            "alerts": [alert.to_dict() for alert in self.alerts[-10:]],  # Last 10 alerts
        }

    def register_alert_callback(self, callback):
        """Register a callback to be notified of alerts"""
        self.alert_callbacks.append(callback)

    def clear_alerts(self):
        """Clear alert history"""
        self.alerts.clear()


# Global metrics collector
_metrics_collector = VectorMetricsCollector()


def get_metrics_collector() -> VectorMetricsCollector:
    """Get the global metrics collector instance"""
    return _metrics_collector


def export_prometheus_metrics() -> str:
    """Export current metrics in Prometheus format"""
    from .vector_optimizer import get_performance_stats

    stats = get_performance_stats()
    return _metrics_collector.export_prometheus_metrics(stats)


def export_json_metrics() -> dict[str, Any]:
    """Export current metrics in JSON format"""
    from .vector_optimizer import get_performance_stats

    stats = get_performance_stats()
    return _metrics_collector.export_json_metrics(stats)


def check_and_alert() -> list[SLAAlert]:
    """Check SLA compliance and generate alerts"""
    from .vector_optimizer import get_performance_stats

    stats = get_performance_stats()
    return _metrics_collector.check_sla_compliance(stats)

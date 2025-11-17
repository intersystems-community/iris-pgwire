"""
Vector Query Optimizer Metrics Export

Provides metrics export and alerting for constitutional SLA compliance monitoring.
"""

import logging
import time
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

    def check_sla_compliance(self, stats: dict[str, Any]) -> list[SLAAlert]:
        """Check SLA compliance and generate alerts if needed"""
        alerts = []
        current_time = time.time()

        # Check compliance rate
        compliance_rate = stats.get("sla_compliance_rate", 100.0)
        if compliance_rate < self.SLA_COMPLIANCE_CRITICAL_THRESHOLD:
            alert = SLAAlert(
                timestamp=current_time,
                violation_type="performance",
                severity="critical",
                message=f"CRITICAL: SLA compliance rate {compliance_rate}% below threshold {self.SLA_COMPLIANCE_CRITICAL_THRESHOLD}%",
                metrics=stats,
            )
            alerts.append(alert)
            logger.error(f"🚨 {alert.message}")

        elif compliance_rate < self.SLA_COMPLIANCE_WARNING_THRESHOLD:
            alert = SLAAlert(
                timestamp=current_time,
                violation_type="performance",
                severity="warning",
                message=f"WARNING: SLA compliance rate {compliance_rate}% below threshold {self.SLA_COMPLIANCE_WARNING_THRESHOLD}%",
                metrics=stats,
            )
            alerts.append(alert)
            logger.warning(f"⚠️ {alert.message}")

        # Check average transformation time
        avg_time = stats.get("avg_transformation_time_ms", 0)
        if avg_time > self.TRANSFORMATION_TIME_CRITICAL_MS:
            alert = SLAAlert(
                timestamp=current_time,
                violation_type="performance",
                severity="critical",
                message=f"CRITICAL: Average transformation time {avg_time}ms exceeds SLA {self.TRANSFORMATION_TIME_CRITICAL_MS}ms",
                metrics=stats,
            )
            alerts.append(alert)
            logger.error(f"🚨 {alert.message}")

        elif avg_time > self.TRANSFORMATION_TIME_WARNING_MS:
            alert = SLAAlert(
                timestamp=current_time,
                violation_type="performance",
                severity="warning",
                message=f"WARNING: Average transformation time {avg_time}ms approaching SLA limit {self.TRANSFORMATION_TIME_CRITICAL_MS}ms",
                metrics=stats,
            )
            alerts.append(alert)
            logger.warning(f"⚠️ {alert.message}")

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
        metrics = []

        # Counter metrics
        metrics.append(
            "# HELP vector_optimizer_total_optimizations Total number of vector query optimizations"
        )
        metrics.append("# TYPE vector_optimizer_total_optimizations counter")
        metrics.append(
            f"vector_optimizer_total_optimizations {stats.get('total_optimizations', 0)}"
        )

        metrics.append("# HELP vector_optimizer_sla_violations Total number of SLA violations")
        metrics.append("# TYPE vector_optimizer_sla_violations counter")
        metrics.append(f"vector_optimizer_sla_violations {stats.get('sla_violations', 0)}")

        # Gauge metrics
        metrics.append("# HELP vector_optimizer_sla_compliance_rate SLA compliance rate percentage")
        metrics.append("# TYPE vector_optimizer_sla_compliance_rate gauge")
        metrics.append(
            f"vector_optimizer_sla_compliance_rate {stats.get('sla_compliance_rate', 100.0)}"
        )

        metrics.append(
            "# HELP vector_optimizer_avg_transformation_time_ms Average transformation time in milliseconds"
        )
        metrics.append("# TYPE vector_optimizer_avg_transformation_time_ms gauge")
        metrics.append(
            f"vector_optimizer_avg_transformation_time_ms {stats.get('avg_transformation_time_ms', 0)}"
        )

        metrics.append(
            "# HELP vector_optimizer_max_transformation_time_ms Maximum transformation time in milliseconds"
        )
        metrics.append("# TYPE vector_optimizer_max_transformation_time_ms gauge")
        metrics.append(
            f"vector_optimizer_max_transformation_time_ms {stats.get('max_transformation_time_ms', 0)}"
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

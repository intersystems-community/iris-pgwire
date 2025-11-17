"""
Constitutional Performance Monitoring for IRIS SQL Translation

Implements real-time SLA tracking, metrics collection, and alerting
to ensure constitutional 5ms translation requirement compliance.
"""

import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class TranslationMetrics:
    """Metrics for a single translation operation"""

    start_time: float
    end_time: float
    translation_time_ms: float
    sql_length: int
    constructs_detected: int
    constructs_translated: int
    construct_types: dict[str, int]
    cache_hit: bool = False
    error_occurred: bool = False
    error_message: str | None = None

    @property
    def duration_ms(self) -> float:
        return (self.end_time - self.start_time) * 1000

    @property
    def sla_compliant(self) -> bool:
        """Constitutional requirement: 5ms SLA"""
        return self.translation_time_ms <= 5.0


@dataclass
class PerformanceStats:
    """Aggregated performance statistics"""

    total_translations: int = 0
    sla_violations: int = 0
    total_time_ms: float = 0.0
    avg_time_ms: float = 0.0
    p95_time_ms: float = 0.0
    p99_time_ms: float = 0.0
    cache_hit_rate: float = 0.0
    error_rate: float = 0.0
    construct_usage: dict[str, int] = field(default_factory=dict)

    @property
    def sla_compliance_rate(self) -> float:
        """Percentage of translations meeting 5ms SLA"""
        if self.total_translations == 0:
            return 100.0
        return ((self.total_translations - self.sla_violations) / self.total_translations) * 100


class PerformanceMonitor:
    """
    Constitutional Performance Monitor

    Tracks translation performance against 5ms SLA requirement
    and provides real-time metrics for constitutional compliance.
    """

    def __init__(self, window_size: int = 1000, alert_threshold: float = 90.0):
        self.window_size = window_size
        self.alert_threshold = alert_threshold  # SLA compliance % threshold

        # Thread-safe metrics storage
        self._metrics_lock = threading.RLock()
        self._recent_metrics: deque = deque(maxlen=window_size)
        self._all_times: list[float] = []

        # Aggregated stats
        self._stats = PerformanceStats()

        # Alert tracking
        self._last_alert_time = 0.0
        self._alert_cooldown = 60.0  # seconds

    @contextmanager
    def measure_translation(self, sql: str, constructs_detected: int = 0):
        """Context manager for measuring translation performance"""
        start_time = time.perf_counter()
        error_occurred = False
        error_message = None
        constructs_translated = 0
        construct_types = {}
        cache_hit = False

        try:
            # Yield control to the translation operation
            measurement_context = {
                "constructs_translated": 0,
                "construct_types": {},
                "cache_hit": False,
            }
            yield measurement_context

            # Extract results from context
            constructs_translated = measurement_context.get("constructs_translated", 0)
            construct_types = measurement_context.get("construct_types", {})
            cache_hit = measurement_context.get("cache_hit", False)

        except Exception as e:
            error_occurred = True
            error_message = str(e)
            logger.error("Translation error occurred", error=str(e))
            raise
        finally:
            end_time = time.perf_counter()
            translation_time_ms = (end_time - start_time) * 1000

            # Create metrics record
            metrics = TranslationMetrics(
                start_time=start_time,
                end_time=end_time,
                translation_time_ms=translation_time_ms,
                sql_length=len(sql),
                constructs_detected=constructs_detected,
                constructs_translated=constructs_translated,
                construct_types=construct_types,
                cache_hit=cache_hit,
                error_occurred=error_occurred,
                error_message=error_message,
            )

            # Record metrics
            self._record_metrics(metrics)

            # Check SLA compliance and alert if needed
            if not metrics.sla_compliant:
                self._handle_sla_violation(metrics)

    def _record_metrics(self, metrics: TranslationMetrics) -> None:
        """Record metrics in thread-safe manner"""
        with self._metrics_lock:
            # Add to recent metrics window
            self._recent_metrics.append(metrics)

            # Track all times for percentile calculations
            self._all_times.append(metrics.translation_time_ms)

            # Update aggregated stats
            self._update_stats(metrics)

    def record_operation(self, operation: str, duration_ms: float, success: bool = True):
        """
        Record an operation for constitutional compliance monitoring

        Args:
            operation: Operation type (e.g., 'postgresql_authentication', 'iris_authentication')
            duration_ms: Operation duration in milliseconds
            success: Whether the operation succeeded
        """
        # Create a simplified metrics record for non-translation operations
        start_time = time.perf_counter() - (duration_ms / 1000)
        end_time = time.perf_counter()

        metrics = TranslationMetrics(
            start_time=start_time,
            end_time=end_time,
            translation_time_ms=duration_ms,
            sql_length=0,  # Not applicable for auth operations
            constructs_detected=0,
            constructs_translated=0,
            construct_types={},
            cache_hit=False,
            error_occurred=not success,
            error_message=None if success else f"{operation} failed",
        )

        self._update_stats(metrics)

        logger.info(
            "Operation performance recorded",
            operation=operation,
            duration_ms=duration_ms,
            success=success,
            sla_compliant=duration_ms <= 5.0,
        )

    def reset_stats(self):
        """Reset all performance statistics (for testing)"""
        with self._metrics_lock:
            self._recent_metrics.clear()
            self._all_times.clear()
            self._stats = PerformanceStats()
            logger.info("Performance statistics reset")

    def _update_stats(self, metrics: TranslationMetrics) -> None:
        """Update aggregated statistics"""
        self._stats.total_translations += 1

        if not metrics.sla_compliant:
            self._stats.sla_violations += 1

        if metrics.error_occurred:
            # Error count tracked separately
            pass

        self._stats.total_time_ms += metrics.translation_time_ms
        self._stats.avg_time_ms = self._stats.total_time_ms / self._stats.total_translations

        # Update construct usage
        for construct_type, count in metrics.construct_types.items():
            self._stats.construct_usage[construct_type] = (
                self._stats.construct_usage.get(construct_type, 0) + count
            )

        # Calculate percentiles (simplified - use sorted times)
        if len(self._all_times) > 0:
            sorted_times = sorted(self._all_times)
            n = len(sorted_times)
            self._stats.p95_time_ms = sorted_times[int(0.95 * n)] if n > 0 else 0.0
            self._stats.p99_time_ms = sorted_times[int(0.99 * n)] if n > 0 else 0.0

        # Update cache hit rate
        cache_hits = sum(1 for m in self._recent_metrics if m.cache_hit)
        self._stats.cache_hit_rate = (
            (cache_hits / len(self._recent_metrics)) * 100 if self._recent_metrics else 0.0
        )

        # Update error rate
        errors = sum(1 for m in self._recent_metrics if m.error_occurred)
        self._stats.error_rate = (
            (errors / len(self._recent_metrics)) * 100 if self._recent_metrics else 0.0
        )

    def _handle_sla_violation(self, metrics: TranslationMetrics) -> None:
        """Handle SLA violation with logging and potential alerting"""
        logger.warning(
            "Constitutional SLA violation detected",
            translation_time_ms=metrics.translation_time_ms,
            sla_limit_ms=5.0,
            sql_length=metrics.sql_length,
            constructs_detected=metrics.constructs_detected,
            constructs_translated=metrics.constructs_translated,
        )

        # Check if we should send alert
        current_time = time.time()
        if current_time - self._last_alert_time > self._alert_cooldown:
            sla_compliance = self.get_stats().sla_compliance_rate
            if sla_compliance < self.alert_threshold:
                self._send_alert(sla_compliance, metrics)
                self._last_alert_time = current_time

    def _send_alert(self, compliance_rate: float, metrics: TranslationMetrics) -> None:
        """Send constitutional SLA compliance alert"""
        logger.error(
            "Constitutional SLA compliance alert",
            compliance_rate=compliance_rate,
            threshold=self.alert_threshold,
            recent_violation_ms=metrics.translation_time_ms,
            sla_violations=self._stats.sla_violations,
            total_translations=self._stats.total_translations,
        )

    def get_stats(self) -> PerformanceStats:
        """Get current performance statistics"""
        with self._metrics_lock:
            return PerformanceStats(
                total_translations=self._stats.total_translations,
                sla_violations=self._stats.sla_violations,
                total_time_ms=self._stats.total_time_ms,
                avg_time_ms=self._stats.avg_time_ms,
                p95_time_ms=self._stats.p95_time_ms,
                p99_time_ms=self._stats.p99_time_ms,
                cache_hit_rate=self._stats.cache_hit_rate,
                error_rate=self._stats.error_rate,
                construct_usage=self._stats.construct_usage.copy(),
            )

    def get_recent_metrics(self, count: int | None = None) -> list[TranslationMetrics]:
        """Get recent translation metrics"""
        with self._metrics_lock:
            metrics_list = list(self._recent_metrics)
            if count is not None:
                return metrics_list[-count:]
            return metrics_list

    def get_constitutional_report(self) -> dict[str, Any]:
        """Generate constitutional compliance report"""
        stats = self.get_stats()
        recent_metrics = self.get_recent_metrics(100)  # Last 100 operations

        # Calculate recent SLA compliance
        recent_violations = sum(1 for m in recent_metrics if not m.sla_compliant)
        recent_compliance = (
            ((len(recent_metrics) - recent_violations) / len(recent_metrics)) * 100
            if recent_metrics
            else 100.0
        )

        return {
            "constitutional_compliance": {
                "sla_requirement_ms": 5.0,
                "overall_compliance_rate": stats.sla_compliance_rate,
                "recent_compliance_rate": recent_compliance,
                "total_violations": stats.sla_violations,
                "alert_threshold": self.alert_threshold,
                "status": (
                    "COMPLIANT"
                    if stats.sla_compliance_rate >= self.alert_threshold
                    else "NON_COMPLIANT"
                ),
            },
            "performance_metrics": {
                "total_translations": stats.total_translations,
                "avg_time_ms": stats.avg_time_ms,
                "p95_time_ms": stats.p95_time_ms,
                "p99_time_ms": stats.p99_time_ms,
                "cache_hit_rate": stats.cache_hit_rate,
                "error_rate": stats.error_rate,
            },
            "construct_analytics": {
                "usage_by_type": stats.construct_usage,
                "most_used_construct": (
                    max(stats.construct_usage.items(), key=lambda x: x[1])
                    if stats.construct_usage
                    else None
                ),
            },
            "recent_activity": {
                "last_100_operations": len(recent_metrics),
                "recent_avg_time_ms": (
                    sum(m.translation_time_ms for m in recent_metrics) / len(recent_metrics)
                    if recent_metrics
                    else 0.0
                ),
                "recent_violations": recent_violations,
            },
        }


# Global performance monitor instance
_global_monitor: PerformanceMonitor | None = None


def get_monitor() -> PerformanceMonitor:
    """Get global performance monitor instance"""
    global _global_monitor
    if _global_monitor is None:
        _global_monitor = PerformanceMonitor()
    return _global_monitor


def reset_monitor() -> None:
    """Reset global performance monitor (for testing)"""
    global _global_monitor
    _global_monitor = None

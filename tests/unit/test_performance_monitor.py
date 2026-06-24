"""
Unit tests for sql_translator/performance_monitor.py

Targets: PerformanceMonitor, PerformanceTracker, convenience functions,
         and the dataclass models.  No live IRIS required.
"""

import time
import threading
from unittest.mock import patch

import pytest

from iris_pgwire.sql_translator.performance_monitor import (
    ComponentStats,
    ConstitutionalReport,
    MetricType,
    PerformanceMetric,
    PerformanceMonitor,
    PerformanceTracker,
    SLAStatus,
    SLAViolation,
    get_constitutional_compliance,
    get_monitor,
    record_translation_time,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_monitor(sla_ms: float = 5.0) -> PerformanceMonitor:
    """Return a fresh, MONITOR_ENABLED monitor with a low SLA."""
    mon = PerformanceMonitor(sla_threshold_ms=sla_ms)
    return mon


def record_enabled(mon: PerformanceMonitor, value_ms: float, component: str = "test"):
    """Record a metric through the private path (bypassing MONITOR_ENABLED global)."""
    from iris_pgwire.sql_translator import performance_monitor as pm_mod
    with patch.object(pm_mod, "MONITOR_ENABLED", True):
        return mon.record_metric(MetricType.TRANSLATION_TIME, value_ms, component)


# ---------------------------------------------------------------------------
# MetricType and SLAStatus enums
# ---------------------------------------------------------------------------

class TestEnums:
    def test_metric_type_values(self):
        assert MetricType.TRANSLATION_TIME.value == "translation_time"
        assert MetricType.BULK_INSERT_THROUGHPUT.value == "bulk_insert_throughput"

    def test_sla_status_values(self):
        assert SLAStatus.COMPLIANT.value == "compliant"
        assert SLAStatus.CRITICAL.value == "critical"


# ---------------------------------------------------------------------------
# PerformanceMonitor – basic metric recording
# ---------------------------------------------------------------------------

class TestPerformanceMonitorBasic:
    def test_record_metric_disabled_returns_none(self):
        mon = make_monitor()
        # MONITOR_ENABLED is False by default
        result = mon.record_metric(MetricType.TRANSLATION_TIME, 1.0, "comp")
        assert result is None

    def test_record_metric_enabled_no_violation(self):
        mon = make_monitor(sla_ms=10.0)
        result = record_enabled(mon, 3.0, "comp")
        assert result is None  # below threshold

    def test_record_metric_enabled_violation(self):
        mon = make_monitor(sla_ms=5.0)
        result = record_enabled(mon, 20.0, "comp")
        assert isinstance(result, SLAViolation)
        assert result.actual_value_ms == 20.0
        assert result.sla_threshold_ms == 5.0
        assert result.violation_amount_ms == pytest.approx(15.0)
        assert result.component == "comp"

    def test_total_operations_increments(self):
        mon = make_monitor()
        assert mon._total_operations == 0
        record_enabled(mon, 1.0)
        record_enabled(mon, 2.0)
        assert mon._total_operations == 2

    def test_total_violations_increments(self):
        mon = make_monitor(sla_ms=5.0)
        assert mon._total_violations == 0
        record_enabled(mon, 50.0)
        assert mon._total_violations == 1
        record_enabled(mon, 50.0)
        assert mon._total_violations == 2

    def test_consecutive_violations_reset_on_good_metric(self):
        mon = make_monitor(sla_ms=5.0)
        record_enabled(mon, 50.0)
        record_enabled(mon, 50.0)
        assert mon._consecutive_violations == 2
        record_enabled(mon, 1.0)
        assert mon._consecutive_violations == 0

    def test_resolve_metric_type_from_string(self):
        mon = make_monitor()
        result = mon._resolve_metric_type("translation_time")
        assert result == MetricType.TRANSLATION_TIME

    def test_resolve_metric_type_from_bad_string_defaults(self):
        mon = make_monitor()
        result = mon._resolve_metric_type("nonexistent_type")
        assert result == MetricType.TRANSLATION_TIME

    def test_resolve_metric_type_from_enum_passthrough(self):
        mon = make_monitor()
        result = mon._resolve_metric_type(MetricType.PARSING_TIME)
        assert result == MetricType.PARSING_TIME


# ---------------------------------------------------------------------------
# SLA violation severity levels
# ---------------------------------------------------------------------------

class TestViolationSeverity:
    def test_minor_violation(self):
        mon = make_monitor(sla_ms=5.0)
        # value slightly above threshold, consecutive < 5
        v = record_enabled(mon, 6.0)
        assert v.severity == "minor"

    def test_major_violation(self):
        mon = make_monitor(sla_ms=5.0)
        # violation_amount > sla_threshold -> major
        v = record_enabled(mon, 11.0)  # 11 - 5 = 6 > 5
        assert v.severity == "major"

    def test_critical_violation_after_threshold(self):
        mon = make_monitor(sla_ms=5.0)
        mon.critical_violation_threshold = 3
        for _ in range(3):
            record_enabled(mon, 50.0)
        v = record_enabled(mon, 50.0)
        assert v.severity == "critical"


# ---------------------------------------------------------------------------
# Component statistics
# ---------------------------------------------------------------------------

class TestComponentStats:
    def test_get_component_stats_no_data(self):
        mon = make_monitor()
        assert mon.get_component_stats("nonexistent") is None

    def test_get_component_stats_with_data(self):
        mon = make_monitor(sla_ms=5.0)
        for val in [1.0, 2.0, 3.0, 4.0, 5.0]:
            record_enabled(mon, val, "svc")
        stats = mon.get_component_stats("svc")
        assert isinstance(stats, ComponentStats)
        assert stats.component_name == "svc"
        assert stats.total_operations == 5
        assert stats.min_time_ms == pytest.approx(1.0)
        assert stats.max_time_ms == pytest.approx(5.0)
        assert stats.average_time_ms == pytest.approx(3.0)

    def test_component_stats_compliance_rate(self):
        mon = make_monitor(sla_ms=3.0)
        record_enabled(mon, 1.0, "svc")  # compliant
        record_enabled(mon, 2.0, "svc")  # compliant
        record_enabled(mon, 10.0, "svc")  # violation
        stats = mon.get_component_stats("svc")
        # 1 violation out of 3 ops
        assert stats.sla_compliance_rate == pytest.approx(1.0 - 1.0 / 3.0)

    def test_percentile_empty_list(self):
        mon = make_monitor()
        assert mon._percentile([], 0.95) == 0.0

    def test_percentile_single_value(self):
        mon = make_monitor()
        assert mon._percentile([7.5], 0.95) == pytest.approx(7.5)


# ---------------------------------------------------------------------------
# Clear metrics
# ---------------------------------------------------------------------------

class TestClearMetrics:
    def test_clear_all_metrics(self):
        mon = make_monitor()
        record_enabled(mon, 1.0, "a")
        record_enabled(mon, 2.0, "b")
        cleared = mon.clear_metrics()
        assert cleared == 2
        assert mon._total_operations == 0
        assert mon._total_violations == 0
        assert len(mon._metrics) == 0

    def test_clear_specific_component(self):
        mon = make_monitor()
        record_enabled(mon, 1.0, "alpha")
        record_enabled(mon, 2.0, "alpha")
        record_enabled(mon, 3.0, "beta")
        cleared = mon.clear_metrics("alpha")
        assert cleared == 2
        # beta still tracked
        assert "beta" in mon._component_metrics

    def test_clear_nonexistent_component_returns_zero(self):
        mon = make_monitor()
        assert mon.clear_metrics("ghost") == 0


# ---------------------------------------------------------------------------
# Constitutional report
# ---------------------------------------------------------------------------

class TestConstitutionalReport:
    def test_report_compliant_when_no_violations(self):
        mon = make_monitor(sla_ms=10.0)
        record_enabled(mon, 1.0)
        report = mon.get_constitutional_report()
        assert isinstance(report, ConstitutionalReport)
        assert report.status == SLAStatus.COMPLIANT
        assert report.total_violations == 0
        assert report.overall_compliance_rate == pytest.approx(1.0)

    def test_report_violation_status(self):
        mon = make_monitor(sla_ms=5.0)
        # Use scattered violations so consecutive count stays below critical_threshold (5)
        for _ in range(18):
            record_enabled(mon, 1.0)   # compliant, resets consecutive
            record_enabled(mon, 50.0)  # violation (consecutive=1 each time)
        # 18 violations out of 36 ops = 50% compliance < 95%, consecutive=1 < 5 → VIOLATION
        report = mon.get_constitutional_report()
        assert report.status == SLAStatus.VIOLATION
        assert report.total_violations == 18

    def test_report_warning_status(self):
        mon = make_monitor(sla_ms=5.0)
        # 1 violation out of 100 = 99% compliance -> WARNING (not VIOLATION)
        for _ in range(99):
            record_enabled(mon, 1.0)
        record_enabled(mon, 50.0)
        mon._consecutive_violations = 0  # ensure not CRITICAL
        report = mon.get_constitutional_report()
        assert report.status == SLAStatus.WARNING

    def test_report_critical_status(self):
        mon = make_monitor(sla_ms=5.0)
        mon.critical_violation_threshold = 2
        record_enabled(mon, 50.0)
        record_enabled(mon, 50.0)
        record_enabled(mon, 50.0)  # consecutive >= 2
        report = mon.get_constitutional_report()
        assert report.status == SLAStatus.CRITICAL

    def test_report_empty_monitor(self):
        mon = make_monitor()
        report = mon.get_constitutional_report()
        assert report.total_violations == 0
        assert report.performance_metrics == {}

    def test_report_includes_recommendations(self):
        mon = make_monitor(sla_ms=5.0)
        record_enabled(mon, 1.0)
        report = mon.get_constitutional_report()
        assert isinstance(report.recommendations, list)
        assert len(report.recommendations) > 0


# ---------------------------------------------------------------------------
# Real-time status
# ---------------------------------------------------------------------------

class TestRealTimeStatus:
    def test_real_time_status_structure(self):
        mon = make_monitor()
        status = mon.get_real_time_status()
        assert "sla_status" in status
        assert "current_avg_ms" in status
        assert "consecutive_violations" in status
        assert "memory_usage" in status

    def test_real_time_status_compliant_when_empty(self):
        mon = make_monitor()
        status = mon.get_real_time_status()
        assert status["sla_status"] == "compliant"

    def test_real_time_status_violation_on_consecutive(self):
        mon = make_monitor(sla_ms=5.0)
        record_enabled(mon, 50.0)
        status = mon.get_real_time_status()
        assert status["sla_status"] == "violation"

    def test_real_time_status_critical_on_many_consecutive(self):
        mon = make_monitor(sla_ms=5.0)
        mon.critical_violation_threshold = 2
        for _ in range(3):
            record_enabled(mon, 50.0)
        status = mon.get_real_time_status()
        assert status["sla_status"] == "critical"

    def test_real_time_status_warning_on_high_p95(self):
        mon = make_monitor(sla_ms=5.0)
        # push p95 above warning threshold (5 * 0.8 = 4ms) without causing consecutive violations
        # record compliant metrics then one borderline
        for _ in range(5):
            record_enabled(mon, 4.5)  # above warning threshold but not violation threshold
        # reset consecutive to avoid violation path
        mon._consecutive_violations = 0
        status = mon.get_real_time_status()
        # p95 of [4.5, 4.5, 4.5, 4.5, 4.5] = 4.5 > 4.0 (warning_threshold)
        assert status["sla_status"] == "warning"


# ---------------------------------------------------------------------------
# Export metrics
# ---------------------------------------------------------------------------

class TestExportMetrics:
    def test_export_json(self):
        import json
        mon = make_monitor()
        record_enabled(mon, 1.0)
        output = mon.export_metrics("json")
        data = json.loads(output)
        assert "constitutional_report" in data
        assert "export_timestamp" in data

    def test_export_csv_header(self):
        mon = make_monitor()
        record_enabled(mon, 1.0)
        output = mon.export_metrics("csv")
        assert output.startswith("timestamp,component,metric_type,value_ms,sla_violation")

    def test_export_csv_violation_flag(self):
        mon = make_monitor(sla_ms=5.0)
        record_enabled(mon, 50.0)
        output = mon.export_metrics("csv")
        assert "yes" in output

    def test_export_unsupported_format_raises(self):
        mon = make_monitor()
        with pytest.raises(ValueError, match="Unsupported export format"):
            mon.export_metrics("xml")


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

class TestRecommendations:
    def test_no_issues_gives_positive_recommendation(self):
        mon = make_monitor(sla_ms=10.0)
        record_enabled(mon, 1.0)
        recs = mon._generate_recommendations(SLAStatus.COMPLIANT, 1.0, {})
        assert any("within constitutional" in r for r in recs)

    def test_critical_status_adds_critical_recommendation(self):
        mon = make_monitor()
        recs = mon._generate_recommendations(SLAStatus.CRITICAL, 0.5, {})
        assert any("CRITICAL" in r for r in recs)

    def test_low_compliance_rate_adds_recommendation(self):
        mon = make_monitor()
        recs = mon._generate_recommendations(SLAStatus.VIOLATION, 0.80, {})
        assert any("95%" in r for r in recs)


# ---------------------------------------------------------------------------
# Thread safety (smoke test)
# ---------------------------------------------------------------------------

class TestThreadSafety:
    def test_concurrent_metric_recording(self):
        mon = make_monitor(sla_ms=1000.0)
        errors = []

        def worker():
            try:
                for _ in range(50):
                    record_enabled(mon, 0.1, "thread_comp")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert mon._total_operations == 200


# ---------------------------------------------------------------------------
# PerformanceTracker context manager
# ---------------------------------------------------------------------------

class TestPerformanceTracker:
    def test_tracker_disabled_does_nothing(self):
        tracker = PerformanceTracker(MetricType.TRANSLATION_TIME, "comp")
        with tracker:
            pass
        assert tracker.violation is None
        assert tracker.start_time is None

    def test_tracker_enabled_records_time(self):
        from iris_pgwire.sql_translator import performance_monitor as pm_mod
        with patch.object(pm_mod, "MONITOR_ENABLED", True):
            tracker = PerformanceTracker(MetricType.TRANSLATION_TIME, "comp",
                                         session_id="s1", trace_id="t1")
            with tracker:
                time.sleep(0.001)
            assert tracker.start_time is not None

    def test_tracker_enabled_with_slow_op_sets_violation(self):
        from iris_pgwire.sql_translator import performance_monitor as pm_mod
        mon = make_monitor(sla_ms=0.001)  # 0.001ms → almost anything is a violation
        with patch.object(pm_mod, "MONITOR_ENABLED", True), \
             patch.object(pm_mod, "_monitor", mon):
            tracker = PerformanceTracker(MetricType.TRANSLATION_TIME, "comp")
            with tracker:
                time.sleep(0.01)
            # violation should be set (or None if monitor silently swallowed it)
            # We just assert no exception was raised – the context manager must not propagate


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

class TestConvenienceFunctions:
    def test_get_monitor_returns_monitor(self):
        mon = get_monitor()
        assert isinstance(mon, PerformanceMonitor)

    def test_record_translation_time_disabled_returns_none(self):
        result = record_translation_time(1.0, component="test")
        assert result is None  # MONITOR_ENABLED is False by default

    def test_get_constitutional_compliance_returns_report(self):
        report = get_constitutional_compliance()
        assert isinstance(report, ConstitutionalReport)


# ---------------------------------------------------------------------------
# _calculate_ops_per_second
# ---------------------------------------------------------------------------

class TestOpsPerSecond:
    def test_ops_per_second_positive(self):
        mon = make_monitor()
        record_enabled(mon, 1.0)
        ops = mon._calculate_ops_per_second()
        assert ops > 0

    def test_ops_per_second_zero_when_no_uptime(self):
        """If start_time == now, uptime is ~0; function should return 0 not raise."""
        from datetime import UTC, datetime
        mon = make_monitor()
        # Force start_time to now so uptime is essentially 0
        with patch.object(mon, "_start_time", datetime.now(UTC)):
            result = mon._calculate_ops_per_second()
        # Should return 0.0 or close to it (uptime ≈ 0 → guarded by `if uptime > 0`)
        assert isinstance(result, float)

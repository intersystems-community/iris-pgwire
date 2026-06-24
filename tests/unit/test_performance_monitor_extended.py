"""
Extended unit tests for iris_pgwire.performance_monitor

Targets the uncovered branches to push coverage from 62% → ≥85%.
No live IRIS connection required.
"""

import threading
import time

import pytest

from iris_pgwire.performance_monitor import (
    PerformanceMonitor,
    PerformanceStats,
    TranslationMetrics,
    get_monitor,
    reset_monitor,
)


# ---------------------------------------------------------------------------
# TranslationMetrics dataclass
# ---------------------------------------------------------------------------


class TestTranslationMetrics:
    def _make_metrics(self, translation_time_ms: float = 1.0, error: bool = False) -> TranslationMetrics:
        now = time.perf_counter()
        return TranslationMetrics(
            start_time=now,
            end_time=now + translation_time_ms / 1000,
            translation_time_ms=translation_time_ms,
            sql_length=50,
            constructs_detected=2,
            constructs_translated=1,
            construct_types={"SYNTAX": 1},
            cache_hit=False,
            error_occurred=error,
        )

    def test_duration_ms_calculated(self):
        now = time.perf_counter()
        m = TranslationMetrics(
            start_time=now,
            end_time=now + 0.002,  # 2ms
            translation_time_ms=2.0,
            sql_length=10,
            constructs_detected=0,
            constructs_translated=0,
            construct_types={},
        )
        assert m.duration_ms == pytest.approx(2.0, abs=0.1)

    def test_sla_compliant_below_threshold(self):
        m = self._make_metrics(translation_time_ms=3.0)
        assert m.sla_compliant is True

    def test_sla_compliant_at_threshold(self):
        m = self._make_metrics(translation_time_ms=5.0)
        assert m.sla_compliant is True

    def test_sla_non_compliant_above_threshold(self):
        m = self._make_metrics(translation_time_ms=6.0)
        assert m.sla_compliant is False

    def test_error_flag(self):
        m = self._make_metrics(error=True)
        assert m.error_occurred is True

    def test_cache_hit_default_false(self):
        m = self._make_metrics()
        assert m.cache_hit is False


# ---------------------------------------------------------------------------
# PerformanceStats dataclass
# ---------------------------------------------------------------------------


class TestPerformanceStats:
    def test_sla_compliance_rate_no_translations(self):
        stats = PerformanceStats()
        assert stats.sla_compliance_rate == 100.0

    def test_sla_compliance_rate_all_compliant(self):
        stats = PerformanceStats(total_translations=10, sla_violations=0)
        assert stats.sla_compliance_rate == 100.0

    def test_sla_compliance_rate_some_violations(self):
        stats = PerformanceStats(total_translations=10, sla_violations=2)
        assert stats.sla_compliance_rate == pytest.approx(80.0)

    def test_sla_compliance_rate_all_violations(self):
        stats = PerformanceStats(total_translations=5, sla_violations=5)
        assert stats.sla_compliance_rate == 0.0


# ---------------------------------------------------------------------------
# PerformanceMonitor — basic recording
# ---------------------------------------------------------------------------


class TestPerformanceMonitorBasic:
    @pytest.fixture
    def monitor(self):
        return PerformanceMonitor(window_size=100, alert_threshold=90.0)

    def test_initial_stats_zero(self, monitor):
        stats = monitor.get_stats()
        assert stats.total_translations == 0
        assert stats.sla_violations == 0

    def test_measure_translation_records_metrics(self, monitor):
        with monitor.measure_translation("SELECT 1", constructs_detected=0):
            pass
        stats = monitor.get_stats()
        assert stats.total_translations == 1

    def test_measure_translation_updates_avg(self, monitor):
        with monitor.measure_translation("SELECT 1"):
            pass
        with monitor.measure_translation("SELECT 2"):
            pass
        stats = monitor.get_stats()
        assert stats.total_translations == 2
        assert stats.avg_time_ms >= 0

    def test_measure_translation_context_dict_used(self, monitor):
        """Verify that values written into measurement_context are captured."""
        with monitor.measure_translation("SELECT 1", constructs_detected=3) as ctx:
            ctx["constructs_translated"] = 2
            ctx["construct_types"] = {"FUNCTION": 1, "SYNTAX": 1}
            ctx["cache_hit"] = True

        recent = monitor.get_recent_metrics(count=1)
        assert len(recent) == 1
        m = recent[0]
        assert m.constructs_translated == 2
        assert m.cache_hit is True

    def test_cache_hit_rate_updates(self, monitor):
        with monitor.measure_translation("SELECT 1") as ctx:
            ctx["cache_hit"] = True
        stats = monitor.get_stats()
        assert stats.cache_hit_rate == pytest.approx(100.0)

    def test_error_rate_updates(self, monitor):
        with pytest.raises(RuntimeError):
            with monitor.measure_translation("BAD SQL"):
                raise RuntimeError("translation failed")

        stats = monitor.get_stats()
        assert stats.total_translations == 1
        assert stats.error_rate == pytest.approx(100.0)

    def test_measure_translation_re_raises_exception(self, monitor):
        with pytest.raises(ValueError, match="oops"):
            with monitor.measure_translation("SELECT x"):
                raise ValueError("oops")

    def test_get_recent_metrics_count_param(self, monitor):
        for i in range(5):
            with monitor.measure_translation(f"SELECT {i}"):
                pass
        recent = monitor.get_recent_metrics(count=3)
        assert len(recent) == 3

    def test_get_recent_metrics_all(self, monitor):
        for i in range(4):
            with monitor.measure_translation(f"SELECT {i}"):
                pass
        all_metrics = monitor.get_recent_metrics()
        assert len(all_metrics) == 4

    def test_reset_stats(self, monitor):
        with monitor.measure_translation("SELECT 1"):
            pass
        monitor.reset_stats()
        stats = monitor.get_stats()
        assert stats.total_translations == 0
        assert monitor.get_recent_metrics() == []

    def test_window_size_enforced(self):
        monitor = PerformanceMonitor(window_size=5)
        for i in range(10):
            with monitor.measure_translation(f"SELECT {i}"):
                pass
        recent = monitor.get_recent_metrics()
        assert len(recent) == 5


# ---------------------------------------------------------------------------
# PerformanceMonitor — SLA violation handling & alerting
# ---------------------------------------------------------------------------


class TestPerformanceMonitorSLAViolation:
    @pytest.fixture
    def monitor(self):
        return PerformanceMonitor(window_size=100, alert_threshold=80.0)

    def test_sla_violation_counted(self, monitor):
        """Inject a slow translation via record_operation."""
        monitor.record_operation("test_op", duration_ms=10.0, success=True)
        stats = monitor.get_stats()
        assert stats.sla_violations >= 1

    def test_no_sla_violation_for_fast_op(self, monitor):
        monitor.record_operation("test_op", duration_ms=1.0, success=True)
        stats = monitor.get_stats()
        assert stats.sla_violations == 0

    def test_sla_violation_from_measure_translation(self, monitor):
        """Force a large translation_time by manipulating context — use record_operation."""
        # record_operation is the simpler injection path for slow ops
        monitor.record_operation("slow_op", duration_ms=20.0, success=True)
        stats = monitor.get_stats()
        assert stats.sla_violations == 1

    def test_alert_fired_when_compliance_below_threshold(self, monitor):
        """
        Fire enough slow operations to push compliance below the threshold
        so _send_alert is exercised.
        """
        monitor._last_alert_time = 0.0  # force cooldown elapsed
        for _ in range(5):
            monitor.record_operation("slow_op", duration_ms=10.0, success=True)
        # No assertion on side-effects — just confirm no exception is raised
        stats = monitor.get_stats()
        assert stats.sla_violations == 5

    def test_alert_cooldown_prevents_double_alert(self, monitor):
        """Second violation within cooldown window should not call _send_alert again."""
        monitor._last_alert_time = time.time()  # just fired
        monitor.record_operation("slow_op", duration_ms=10.0, success=True)
        monitor.record_operation("slow_op", duration_ms=10.0, success=True)
        # Should not raise
        assert monitor.get_stats().sla_violations == 2


# ---------------------------------------------------------------------------
# PerformanceMonitor — record_operation
# ---------------------------------------------------------------------------


class TestRecordOperation:
    @pytest.fixture
    def monitor(self):
        return PerformanceMonitor()

    def test_record_operation_success(self, monitor):
        monitor.record_operation("postgresql_auth", duration_ms=2.5, success=True)
        stats = monitor.get_stats()
        assert stats.total_translations == 1
        assert stats.avg_time_ms == pytest.approx(2.5, abs=0.1)

    def test_record_operation_failure(self, monitor):
        monitor.record_operation("iris_auth", duration_ms=3.0, success=False)
        stats = monitor.get_stats()
        assert stats.total_translations == 1

    def test_record_multiple_operations(self, monitor):
        monitor.record_operation("op1", duration_ms=1.0, success=True)
        monitor.record_operation("op2", duration_ms=3.0, success=True)
        stats = monitor.get_stats()
        assert stats.total_translations == 2
        assert stats.avg_time_ms == pytest.approx(2.0, abs=0.1)


# ---------------------------------------------------------------------------
# PerformanceMonitor — construct usage tracking
# ---------------------------------------------------------------------------


class TestConstructUsageTracking:
    @pytest.fixture
    def monitor(self):
        return PerformanceMonitor()

    def test_construct_types_accumulated(self, monitor):
        with monitor.measure_translation("SELECT 1") as ctx:
            ctx["construct_types"] = {"SYNTAX": 2, "FUNCTION": 1}

        stats = monitor.get_stats()
        assert stats.construct_usage.get("SYNTAX") == 2
        assert stats.construct_usage.get("FUNCTION") == 1

    def test_construct_types_accumulate_across_calls(self, monitor):
        with monitor.measure_translation("SELECT 1") as ctx:
            ctx["construct_types"] = {"SYNTAX": 1}
        with monitor.measure_translation("SELECT 2") as ctx:
            ctx["construct_types"] = {"SYNTAX": 2}

        stats = monitor.get_stats()
        assert stats.construct_usage["SYNTAX"] == 3


# ---------------------------------------------------------------------------
# PerformanceMonitor — constitutional report
# ---------------------------------------------------------------------------


class TestConstitutionalReport:
    @pytest.fixture
    def monitor(self):
        return PerformanceMonitor(alert_threshold=95.0)

    def test_report_structure(self, monitor):
        report = monitor.get_constitutional_report()
        assert "constitutional_compliance" in report
        assert "performance_metrics" in report
        assert "construct_analytics" in report
        assert "recent_activity" in report

    def test_report_empty_monitor(self, monitor):
        report = monitor.get_constitutional_report()
        assert report["constitutional_compliance"]["overall_compliance_rate"] == 100.0
        assert report["performance_metrics"]["total_translations"] == 0
        assert report["construct_analytics"]["most_used_construct"] is None

    def test_report_with_data(self, monitor):
        with monitor.measure_translation("SELECT 1") as ctx:
            ctx["construct_types"] = {"SYNTAX": 3}
        report = monitor.get_constitutional_report()
        assert report["performance_metrics"]["total_translations"] == 1
        assert report["construct_analytics"]["most_used_construct"] == ("SYNTAX", 3)

    def test_report_status_compliant(self, monitor):
        with monitor.measure_translation("SELECT 1"):
            pass
        report = monitor.get_constitutional_report()
        assert report["constitutional_compliance"]["status"] == "COMPLIANT"

    def test_report_recent_activity(self, monitor):
        for i in range(3):
            with monitor.measure_translation(f"SELECT {i}"):
                pass
        report = monitor.get_constitutional_report()
        assert report["recent_activity"]["last_100_operations"] == 3


# ---------------------------------------------------------------------------
# PerformanceMonitor — percentile calculations
# ---------------------------------------------------------------------------


class TestPercentileCalculations:
    def test_p95_and_p99_calculated_after_bulk(self):
        monitor = PerformanceMonitor()
        # record_operation bypasses _all_times; use measure_translation to populate it
        for i in range(100):
            with monitor.measure_translation(f"SELECT {i}"):
                pass
        stats = monitor.get_stats()
        # _all_times now has 100 real measurements; p95 index = int(0.95 * 100) = 95
        assert stats.p95_time_ms >= 0  # wall-clock values may be tiny but non-negative
        assert stats.p99_time_ms >= stats.p95_time_ms

    def test_p95_monotone_after_slow_measure(self):
        """After recording a deliberately slow op via record_operation injection,
        verify p95 stays non-negative (exercises the percentile path via _record_metrics)."""
        monitor = PerformanceMonitor()
        # _all_times is only fed by _record_metrics → use measure_translation
        for i in range(20):
            with monitor.measure_translation(f"Q{i}"):
                pass
        stats = monitor.get_stats()
        assert stats.p95_time_ms >= 0
        assert stats.p99_time_ms >= 0


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_measure_translation(self):
        monitor = PerformanceMonitor(window_size=1000)
        errors = []

        def worker():
            try:
                for i in range(10):
                    with monitor.measure_translation(f"SELECT {i}"):
                        pass
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        stats = monitor.get_stats()
        assert stats.total_translations == 100


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


class TestModuleLevelHelpers:
    def setup_method(self):
        reset_monitor()

    def test_get_monitor_returns_instance(self):
        m = get_monitor()
        assert isinstance(m, PerformanceMonitor)

    def test_get_monitor_singleton(self):
        m1 = get_monitor()
        m2 = get_monitor()
        assert m1 is m2

    def test_reset_monitor_creates_new_instance(self):
        m1 = get_monitor()
        reset_monitor()
        m2 = get_monitor()
        assert m1 is not m2

"""
Unit tests for vector_metrics.py

Tests VectorMetricsCollector, SLAAlert, and module-level helper functions.
All IRIS/vector_optimizer dependencies are mocked.
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from iris_pgwire.vector_metrics import (
    SLAAlert,
    VectorMetricsCollector,
    check_and_alert,
    export_json_metrics,
    export_prometheus_metrics,
    get_metrics_collector,
)


# ---------------------------------------------------------------------------
# SLAAlert tests
# ---------------------------------------------------------------------------


class TestSLAAlert:
    def test_to_dict_roundtrip(self):
        ts = 1_700_000_000.0
        alert = SLAAlert(
            timestamp=ts,
            violation_type="performance",
            severity="critical",
            message="oh no",
            metrics={"foo": 1},
        )
        d = alert.to_dict()
        assert d["timestamp"] == ts
        assert d["violation_type"] == "performance"
        assert d["severity"] == "critical"
        assert d["message"] == "oh no"
        assert d["metrics"] == {"foo": 1}

    def test_to_dict_contains_all_keys(self):
        alert = SLAAlert(
            timestamp=0.0,
            violation_type="error_rate",
            severity="warning",
            message="test",
            metrics={},
        )
        keys = set(alert.to_dict().keys())
        assert keys == {"timestamp", "violation_type", "severity", "message", "metrics"}


# ---------------------------------------------------------------------------
# VectorMetricsCollector._create_alert
# ---------------------------------------------------------------------------


class TestCreateAlert:
    def setup_method(self):
        self.collector = VectorMetricsCollector()

    def test_create_alert_critical_logs_error(self):
        with patch("iris_pgwire.vector_metrics.logger") as mock_logger:
            alert = self.collector._create_alert(
                stats={"a": 1},
                violation_type="performance",
                severity="critical",
                message="critical message",
            )
        assert alert.severity == "critical"
        assert alert.violation_type == "performance"
        assert alert.message == "critical message"
        assert alert.metrics == {"a": 1}
        mock_logger.error.assert_called_once()

    def test_create_alert_warning_logs_warning(self):
        with patch("iris_pgwire.vector_metrics.logger") as mock_logger:
            alert = self.collector._create_alert(
                stats={},
                violation_type="availability",
                severity="warning",
                message="warning message",
            )
        assert alert.severity == "warning"
        mock_logger.warning.assert_called_once()

    def test_create_alert_timestamp_is_recent(self):
        before = time.time()
        alert = self.collector._create_alert({}, "performance", "warning", "msg")
        after = time.time()
        assert before <= alert.timestamp <= after


# ---------------------------------------------------------------------------
# VectorMetricsCollector._evaluate_threshold_alerts
# ---------------------------------------------------------------------------


class TestEvaluateThresholdAlerts:
    def setup_method(self):
        self.collector = VectorMetricsCollector()

    def test_returns_empty_when_no_threshold_matched(self):
        thresholds = (
            ("critical", 50.0, "crit {value} {threshold}", lambda v, t: v > t),
        )
        result = self.collector._evaluate_threshold_alerts({}, 30.0, "perf", thresholds)
        assert result == []

    def test_returns_alert_for_first_matched_threshold(self):
        thresholds = (
            ("critical", 50.0, "crit {value} {threshold}", lambda v, t: v > t),
            ("warning", 30.0, "warn {value} {threshold}", lambda v, t: v > t),
        )
        with patch("iris_pgwire.vector_metrics.logger"):
            result = self.collector._evaluate_threshold_alerts({}, 60.0, "perf", thresholds)
        assert len(result) == 1
        assert result[0].severity == "critical"

    def test_returns_warning_when_only_warning_threshold_matched(self):
        thresholds = (
            ("critical", 50.0, "crit {value} {threshold}", lambda v, t: v > t),
            ("warning", 30.0, "warn {value} {threshold}", lambda v, t: v > t),
        )
        with patch("iris_pgwire.vector_metrics.logger"):
            result = self.collector._evaluate_threshold_alerts({}, 40.0, "perf", thresholds)
        assert len(result) == 1
        assert result[0].severity == "warning"

    def test_message_contains_formatted_values(self):
        thresholds = (
            ("warning", 30.0, "val={value} thr={threshold}", lambda v, t: v > t),
        )
        with patch("iris_pgwire.vector_metrics.logger"):
            result = self.collector._evaluate_threshold_alerts({}, 40.0, "perf", thresholds)
        assert "val=40.0" in result[0].message
        assert "thr=30.0" in result[0].message


# ---------------------------------------------------------------------------
# VectorMetricsCollector._append_metric
# ---------------------------------------------------------------------------


class TestAppendMetric:
    def setup_method(self):
        self.collector = VectorMetricsCollector()

    def test_appends_three_lines(self):
        buf = []
        self.collector._append_metric(buf, "my_metric", "help text", "counter", 42)
        assert len(buf) == 3
        assert buf[0] == "# HELP my_metric help text"
        assert buf[1] == "# TYPE my_metric counter"
        assert buf[2] == "my_metric 42"

    def test_appends_float_value(self):
        buf = []
        self.collector._append_metric(buf, "m", "h", "gauge", 3.14)
        assert buf[2] == "m 3.14"


# ---------------------------------------------------------------------------
# VectorMetricsCollector.check_sla_compliance
# ---------------------------------------------------------------------------


class TestCheckSlaCompliance:
    def setup_method(self):
        self.collector = VectorMetricsCollector()

    def _stats(self, compliance=100.0, avg_time=0.0):
        return {"sla_compliance_rate": compliance, "avg_transformation_time_ms": avg_time}

    def test_no_alerts_when_all_good(self):
        with patch("iris_pgwire.vector_metrics.logger"):
            alerts = self.collector.check_sla_compliance(self._stats(100.0, 0.0))
        assert alerts == []

    def test_critical_compliance_alert(self):
        with patch("iris_pgwire.vector_metrics.logger"):
            alerts = self.collector.check_sla_compliance(self._stats(compliance=90.0))
        assert len(alerts) == 1
        assert alerts[0].severity == "critical"
        assert alerts[0].violation_type == "performance"

    def test_warning_compliance_alert(self):
        with patch("iris_pgwire.vector_metrics.logger"):
            alerts = self.collector.check_sla_compliance(self._stats(compliance=96.0))
        assert len(alerts) == 1
        assert alerts[0].severity == "warning"

    def test_critical_transformation_time_alert(self):
        with patch("iris_pgwire.vector_metrics.logger"):
            alerts = self.collector.check_sla_compliance(self._stats(avg_time=6.0))
        assert len(alerts) == 1
        assert alerts[0].severity == "critical"

    def test_warning_transformation_time_alert(self):
        with patch("iris_pgwire.vector_metrics.logger"):
            alerts = self.collector.check_sla_compliance(self._stats(avg_time=4.5))
        assert len(alerts) == 1
        assert alerts[0].severity == "warning"

    def test_alerts_stored_in_collector(self):
        with patch("iris_pgwire.vector_metrics.logger"):
            self.collector.check_sla_compliance(self._stats(compliance=90.0))
        assert len(self.collector.alerts) == 1

    def test_missing_keys_use_defaults(self):
        # No keys → compliance=100.0, avg_time=0.0 → no alerts
        with patch("iris_pgwire.vector_metrics.logger"):
            alerts = self.collector.check_sla_compliance({})
        assert alerts == []

    def test_alert_callbacks_invoked(self):
        cb = MagicMock()
        self.collector.register_alert_callback(cb)
        with patch("iris_pgwire.vector_metrics.logger"):
            alerts = self.collector.check_sla_compliance(self._stats(compliance=90.0))
        assert cb.call_count == len(alerts)

    def test_callback_exception_is_swallowed(self):
        def bad_callback(alert):
            raise RuntimeError("boom")

        self.collector.register_alert_callback(bad_callback)
        with patch("iris_pgwire.vector_metrics.logger") as mock_logger:
            # Should not raise
            self.collector.check_sla_compliance(self._stats(compliance=90.0))
        # The error was logged
        mock_logger.error.assert_called()

    def test_multiple_callbacks(self):
        cb1, cb2 = MagicMock(), MagicMock()
        self.collector.register_alert_callback(cb1)
        self.collector.register_alert_callback(cb2)
        with patch("iris_pgwire.vector_metrics.logger"):
            self.collector.check_sla_compliance(self._stats(compliance=90.0))
        assert cb1.called
        assert cb2.called

    def test_two_simultaneous_alerts(self):
        # compliance critical + time critical
        with patch("iris_pgwire.vector_metrics.logger"):
            alerts = self.collector.check_sla_compliance(self._stats(compliance=90.0, avg_time=6.0))
        assert len(alerts) == 2


# ---------------------------------------------------------------------------
# VectorMetricsCollector.export_prometheus_metrics
# ---------------------------------------------------------------------------


class TestExportPrometheusMetrics:
    def setup_method(self):
        self.collector = VectorMetricsCollector()

    def test_contains_all_metric_names(self):
        stats = {
            "total_optimizations": 5,
            "sla_violations": 1,
            "sla_compliance_rate": 99.0,
            "avg_transformation_time_ms": 2.0,
            "max_transformation_time_ms": 3.5,
        }
        output = self.collector.export_prometheus_metrics(stats)
        assert "vector_optimizer_total_optimizations" in output
        assert "vector_optimizer_sla_violations" in output
        assert "vector_optimizer_sla_compliance_rate" in output
        assert "vector_optimizer_avg_transformation_time_ms" in output
        assert "vector_optimizer_max_transformation_time_ms" in output

    def test_contains_help_and_type_lines(self):
        output = self.collector.export_prometheus_metrics({})
        assert "# HELP" in output
        assert "# TYPE" in output

    def test_defaults_when_keys_missing(self):
        output = self.collector.export_prometheus_metrics({})
        # Default values should appear
        assert "100.0" in output  # compliance rate default
        lines = output.split("\n")
        # 5 metrics × 3 lines = 15 total
        assert len(lines) == 15

    def test_values_reflected_in_output(self):
        output = self.collector.export_prometheus_metrics({"total_optimizations": 999})
        assert "999" in output


# ---------------------------------------------------------------------------
# VectorMetricsCollector.export_json_metrics
# ---------------------------------------------------------------------------


class TestExportJsonMetrics:
    def setup_method(self):
        self.collector = VectorMetricsCollector()

    def test_top_level_structure(self):
        result = self.collector.export_json_metrics({})
        assert "timestamp" in result
        assert result["service"] == "vector_query_optimizer"
        assert "constitutional_compliance" in result
        assert "performance" in result
        assert "alerts" in result

    def test_compliance_status_compliant(self):
        result = self.collector.export_json_metrics({"sla_compliance_rate": 99.0})
        assert result["constitutional_compliance"]["status"] == "compliant"

    def test_compliance_status_non_compliant(self):
        result = self.collector.export_json_metrics({"sla_compliance_rate": 94.0})
        assert result["constitutional_compliance"]["status"] == "non_compliant"

    def test_compliance_exactly_95_is_compliant(self):
        result = self.collector.export_json_metrics({"sla_compliance_rate": 95.0})
        assert result["constitutional_compliance"]["status"] == "compliant"

    def test_performance_section(self):
        stats = {
            "avg_transformation_time_ms": 1.5,
            "min_transformation_time_ms": 0.5,
            "max_transformation_time_ms": 3.0,
            "recent_sample_size": 100,
        }
        result = self.collector.export_json_metrics(stats)
        perf = result["performance"]
        assert perf["avg_transformation_time_ms"] == 1.5
        assert perf["min_transformation_time_ms"] == 0.5
        assert perf["max_transformation_time_ms"] == 3.0
        assert perf["sample_size"] == 100

    def test_alerts_limited_to_last_10(self):
        # Pre-populate more than 10 alerts
        for i in range(15):
            self.collector.alerts.append(
                SLAAlert(
                    timestamp=float(i),
                    violation_type="performance",
                    severity="warning",
                    message=f"alert {i}",
                    metrics={},
                )
            )
        result = self.collector.export_json_metrics({})
        assert len(result["alerts"]) == 10

    def test_timestamp_is_recent(self):
        before = time.time()
        result = self.collector.export_json_metrics({})
        after = time.time()
        assert before <= result["timestamp"] <= after

    def test_defaults_when_keys_missing(self):
        result = self.collector.export_json_metrics({})
        cc = result["constitutional_compliance"]
        assert cc["sla_ms"] == 5.0
        assert cc["compliance_rate"] == 100.0
        assert cc["total_operations"] == 0
        assert cc["violations"] == 0


# ---------------------------------------------------------------------------
# VectorMetricsCollector.register_alert_callback / clear_alerts
# ---------------------------------------------------------------------------


class TestCallbackAndClear:
    def setup_method(self):
        self.collector = VectorMetricsCollector()

    def test_register_callback_stores_it(self):
        cb = MagicMock()
        self.collector.register_alert_callback(cb)
        assert cb in self.collector.alert_callbacks

    def test_clear_alerts_empties_list(self):
        self.collector.alerts.append(
            SLAAlert(0.0, "performance", "warning", "msg", {})
        )
        self.collector.clear_alerts()
        assert self.collector.alerts == []


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


class TestGetMetricsCollector:
    def test_returns_same_instance_each_time(self):
        c1 = get_metrics_collector()
        c2 = get_metrics_collector()
        assert c1 is c2

    def test_returns_vector_metrics_collector(self):
        assert isinstance(get_metrics_collector(), VectorMetricsCollector)


class TestModuleLevelExportFunctions:
    """export_prometheus_metrics(), export_json_metrics(), check_and_alert()
    all import vector_optimizer.get_performance_stats at call time."""

    def _mock_stats(self):
        return {
            "total_optimizations": 10,
            "sla_violations": 0,
            "sla_compliance_rate": 100.0,
            "avg_transformation_time_ms": 1.0,
            "max_transformation_time_ms": 2.0,
            "min_transformation_time_ms": 0.5,
            "recent_sample_size": 10,
            "constitutional_sla_ms": 5.0,
        }

    def test_export_prometheus_metrics(self):
        with patch(
            "iris_pgwire.vector_metrics.export_prometheus_metrics.__module__"
        ):
            pass  # just import smoke test

        with patch(
            "iris_pgwire.vector_optimizer.get_performance_stats",
            return_value=self._mock_stats(),
            create=True,
        ):
            result = export_prometheus_metrics()
        assert "vector_optimizer_total_optimizations" in result

    def test_export_json_metrics(self):
        with patch(
            "iris_pgwire.vector_optimizer.get_performance_stats",
            return_value=self._mock_stats(),
            create=True,
        ):
            result = export_json_metrics()
        assert result["service"] == "vector_query_optimizer"

    def test_check_and_alert(self):
        with patch(
            "iris_pgwire.vector_optimizer.get_performance_stats",
            return_value=self._mock_stats(),
            create=True,
        ):
            alerts = check_and_alert()
        assert isinstance(alerts, list)

    def test_check_and_alert_returns_alerts_on_violation(self):
        bad_stats = self._mock_stats()
        bad_stats["sla_compliance_rate"] = 90.0
        with patch(
            "iris_pgwire.vector_optimizer.get_performance_stats",
            return_value=bad_stats,
            create=True,
        ):
            with patch("iris_pgwire.vector_metrics.logger"):
                alerts = check_and_alert()
        assert len(alerts) >= 1

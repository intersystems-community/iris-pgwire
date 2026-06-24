"""
Unit tests for iris_pgwire/sql_translator/metrics.py

Covers TranslationMetricsCollector, MetricDefinition, MetricEvent, MetricType,
get_metrics_collector, and configure_metrics.  No live IRIS, OTEL, or Prometheus
required — the optional backends are left disabled (the default).
"""

import threading
from collections import deque
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from iris_pgwire.sql_translator.metrics import (
    OTEL_AVAILABLE,
    PROMETHEUS_AVAILABLE,
    MetricDefinition,
    MetricEvent,
    MetricType,
    TranslationMetricsCollector,
    configure_metrics,
    get_metrics_collector,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _collector(**kwargs) -> TranslationMetricsCollector:
    """Return a fresh collector with optional backends disabled by default."""
    return TranslationMetricsCollector(
        enable_otel=kwargs.get("enable_otel", False),
        enable_prometheus=kwargs.get("enable_prometheus", False),
        otel_endpoint=kwargs.get("otel_endpoint", None),
    )


# ---------------------------------------------------------------------------
# MetricType, MetricDefinition, MetricEvent
# ---------------------------------------------------------------------------


class TestDataClasses:
    def test_metric_type_values(self):
        assert MetricType.COUNTER.value == "counter"
        assert MetricType.HISTOGRAM.value == "histogram"
        assert MetricType.GAUGE.value == "gauge"
        assert MetricType.SUMMARY.value == "summary"

    def test_metric_definition_defaults(self):
        md = MetricDefinition("my_metric", MetricType.COUNTER, "A counter metric")
        assert md.name == "my_metric"
        assert md.metric_type == MetricType.COUNTER
        assert md.description == "A counter metric"
        assert md.unit == ""
        assert md.labels == []

    def test_metric_definition_with_all_fields(self):
        md = MetricDefinition(
            "dur_ms",
            MetricType.HISTOGRAM,
            "Duration",
            "ms",
            ["status", "component"],
        )
        assert md.unit == "ms"
        assert md.labels == ["status", "component"]

    def test_metric_event_defaults(self):
        evt = MetricEvent("translation_requests_total", 1)
        assert evt.name == "translation_requests_total"
        assert evt.value == 1
        assert evt.labels == {}
        assert isinstance(evt.timestamp, datetime)

    def test_metric_event_with_labels(self):
        labels = {"status": "ok", "session_id": "sess-1"}
        evt = MetricEvent("translation_requests_total", 5, labels)
        assert evt.labels == labels


# ---------------------------------------------------------------------------
# TranslationMetricsCollector – initialisation
# ---------------------------------------------------------------------------


class TestCollectorInit:
    def test_default_init_no_backends(self):
        c = _collector()
        assert c.enable_otel is False
        assert c.enable_prometheus is False

    def test_metric_definitions_populated(self):
        c = _collector()
        assert "translation_requests_total" in c.metric_definitions
        assert "translation_duration_ms" in c.metric_definitions
        assert "constructs_translated_total" in c.metric_definitions
        assert "cache_operations_total" in c.metric_definitions
        assert "cache_hit_rate" in c.metric_definitions
        assert "sla_violations_total" in c.metric_definitions
        assert "sla_compliance_rate" in c.metric_definitions
        assert "validation_success_total" in c.metric_definitions
        assert "validation_failures_total" in c.metric_definitions
        assert "translation_errors_total" in c.metric_definitions

    def test_internal_storage_starts_empty(self):
        c = _collector()
        assert len(c._counters) == 0
        assert len(c._gauges) == 0
        assert len(c._histograms) == 0
        assert len(c._metric_events) == 0

    def test_otel_disabled_when_not_available(self):
        """Even if enable_otel=True, it is disabled when OTEL_AVAILABLE is False."""
        with patch("iris_pgwire.sql_translator.metrics.OTEL_AVAILABLE", False):
            c = TranslationMetricsCollector(enable_otel=True)
        assert c.enable_otel is False

    def test_prometheus_disabled_when_not_available(self):
        """Even if enable_prometheus=True, disabled when PROMETHEUS_AVAILABLE is False."""
        with patch("iris_pgwire.sql_translator.metrics.PROMETHEUS_AVAILABLE", False):
            c = TranslationMetricsCollector(enable_prometheus=True)
        assert c.enable_prometheus is False


# ---------------------------------------------------------------------------
# record_translation_request
# ---------------------------------------------------------------------------


class TestRecordTranslationRequest:
    def test_increments_counter(self):
        c = _collector()
        c.record_translation_request("success", "sess-1")
        summary = c.get_metrics_summary()
        assert summary["total_events"] == 1
        # Key format: name:label_k=label_v:...
        key = "translation_requests_total:session_id=sess-1:status=success"
        assert summary["counters"][key] == 1

    def test_default_session_id(self):
        c = _collector()
        c.record_translation_request("error")
        summary = c.get_metrics_summary()
        key = "translation_requests_total:session_id=unknown:status=error"
        assert summary["counters"][key] == 1

    def test_accumulates_multiple_calls(self):
        c = _collector()
        c.record_translation_request("success", "s1")
        c.record_translation_request("success", "s1")
        c.record_translation_request("success", "s1")
        key = "translation_requests_total:session_id=s1:status=success"
        assert c.get_metrics_summary()["counters"][key] == 3


# ---------------------------------------------------------------------------
# record_translation_duration
# ---------------------------------------------------------------------------


class TestRecordTranslationDuration:
    def test_fast_duration_no_sla_violation(self):
        c = _collector()
        c.record_translation_duration(1.0, cache_hit=True, constructs_found=2)
        summary = c.get_metrics_summary()
        assert summary["total_events"] == 1
        # No SLA violation counter
        sla_keys = [k for k in summary["counters"] if "sla_violations" in k]
        assert len(sla_keys) == 0

    def test_slow_duration_triggers_sla_violation(self):
        c = _collector()
        c.record_translation_duration(10.0)  # > 5ms threshold
        summary = c.get_metrics_summary()
        # histogram event + sla violation event
        assert summary["total_events"] == 2
        sla_keys = [k for k in summary["counters"] if "sla_violations" in k]
        assert len(sla_keys) == 1

    def test_constructs_found_bucketed(self):
        """constructs_found > 10 is capped at 10."""
        c = _collector()
        c.record_translation_duration(1.0, constructs_found=100)
        # Should not raise; just checks the label is "10"
        key = "translation_duration_ms:cache_hit=False:constructs_found=10"
        assert c._histograms[key][-1] == 1.0

    def test_histogram_stores_value(self):
        c = _collector()
        c.record_translation_duration(3.5)
        hist_counts = c.get_metrics_summary()["histogram_counts"]
        assert any(v > 0 for v in hist_counts.values())


# ---------------------------------------------------------------------------
# record_construct_translated
# ---------------------------------------------------------------------------


class TestRecordConstructTranslated:
    def test_records_counter(self):
        c = _collector()
        c.record_construct_translated("date_literal")
        key = "constructs_translated_total:construct_type=date_literal"
        assert c.get_metrics_summary()["counters"][key] == 1

    def test_different_construct_types_tracked_separately(self):
        c = _collector()
        c.record_construct_translated("date_literal")
        c.record_construct_translated("json_operator")
        summary = c.get_metrics_summary()["counters"]
        assert summary["constructs_translated_total:construct_type=date_literal"] == 1
        assert summary["constructs_translated_total:construct_type=json_operator"] == 1


# ---------------------------------------------------------------------------
# record_cache_operation
# ---------------------------------------------------------------------------


class TestRecordCacheOperation:
    def test_hit(self):
        c = _collector()
        c.record_cache_operation("lookup", "hit")
        key = "cache_operations_total:operation=lookup:result=hit"
        assert c.get_metrics_summary()["counters"][key] == 1

    def test_miss(self):
        c = _collector()
        c.record_cache_operation("lookup", "miss")
        key = "cache_operations_total:operation=lookup:result=miss"
        assert c.get_metrics_summary()["counters"][key] == 1


# ---------------------------------------------------------------------------
# record_sla_violation
# ---------------------------------------------------------------------------


class TestRecordSLAViolation:
    def test_records_violation(self):
        c = _collector()
        c.record_sla_violation("translator", "duration_exceeded", 8.5)
        key = "sla_violations_total:component=translator:violation_type=duration_exceeded"
        assert c.get_metrics_summary()["counters"][key] == 1


# ---------------------------------------------------------------------------
# record_validation_result
# ---------------------------------------------------------------------------


class TestRecordValidationResult:
    def test_success(self):
        c = _collector()
        c.record_validation_result(True, "strict")
        key = "validation_success_total:validation_level=strict"
        assert c.get_metrics_summary()["counters"][key] == 1

    def test_failure_with_issue_type(self):
        c = _collector()
        c.record_validation_result(False, "loose", "syntax_error")
        key = "validation_failures_total:issue_type=syntax_error:validation_level=loose"
        assert c.get_metrics_summary()["counters"][key] == 1

    def test_failure_default_issue_type(self):
        c = _collector()
        c.record_validation_result(False, "strict")
        key = "validation_failures_total:issue_type=unknown:validation_level=strict"
        assert c.get_metrics_summary()["counters"][key] == 1


# ---------------------------------------------------------------------------
# record_translation_error
# ---------------------------------------------------------------------------


class TestRecordTranslationError:
    def test_records_error(self):
        c = _collector()
        c.record_translation_error("parse_error", "ddl_translator")
        key = "translation_errors_total:component=ddl_translator:error_type=parse_error"
        assert c.get_metrics_summary()["counters"][key] == 1


# ---------------------------------------------------------------------------
# update_cache_hit_rate / update_sla_compliance_rate (gauges)
# ---------------------------------------------------------------------------


class TestGaugeUpdates:
    def test_cache_hit_rate(self):
        c = _collector()
        c.update_cache_hit_rate(0.75)
        summary = c.get_metrics_summary()
        # 0.75 → stored as 75.0%
        gauge_key = [k for k in summary["gauges"] if "cache_hit_rate" in k][0]
        assert summary["gauges"][gauge_key] == 75.0

    def test_sla_compliance_rate(self):
        c = _collector()
        c.update_sla_compliance_rate(0.99)
        summary = c.get_metrics_summary()
        gauge_key = [k for k in summary["gauges"] if "sla_compliance_rate" in k][0]
        assert summary["gauges"][gauge_key] == 99.0

    def test_gauge_overwrites_previous_value(self):
        c = _collector()
        c.update_cache_hit_rate(0.50)
        c.update_cache_hit_rate(0.80)
        summary = c.get_metrics_summary()
        gauge_key = [k for k in summary["gauges"] if "cache_hit_rate" in k][0]
        assert summary["gauges"][gauge_key] == 80.0


# ---------------------------------------------------------------------------
# get_metrics_summary structure
# ---------------------------------------------------------------------------


class TestGetMetricsSummary:
    def test_summary_keys_present(self):
        c = _collector()
        summary = c.get_metrics_summary()
        assert "counters" in summary
        assert "gauges" in summary
        assert "histogram_counts" in summary
        assert "total_events" in summary
        assert "backends" in summary
        assert "collection_timestamp" in summary

    def test_backends_reflects_config(self):
        c = _collector()
        backends = c.get_metrics_summary()["backends"]
        assert backends["otel_enabled"] is False
        assert backends["prometheus_enabled"] is False
        assert isinstance(backends["otel_available"], bool)
        assert isinstance(backends["prometheus_available"], bool)

    def test_collection_timestamp_is_iso(self):
        c = _collector()
        ts = c.get_metrics_summary()["collection_timestamp"]
        # Should parse as a valid ISO 8601 datetime
        dt = datetime.fromisoformat(ts)
        assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# get_prometheus_metrics when disabled
# ---------------------------------------------------------------------------


class TestGetPrometheusMetrics:
    def test_returns_none_when_disabled(self):
        c = _collector()
        assert c.get_prometheus_metrics() is None


# ---------------------------------------------------------------------------
# OTEL span helpers when OTEL disabled
# ---------------------------------------------------------------------------


class TestOTELSpanHelpers:
    def test_start_span_returns_none_when_disabled(self):
        c = _collector()
        span = c.start_translation_span("SELECT 1", "sess-1")
        assert span is None

    def test_end_span_noop_when_disabled(self):
        c = _collector()
        # Should not raise
        c.end_translation_span(None, True, 3)
        c.end_translation_span(MagicMock(), True, 3)  # span present but otel off


# ---------------------------------------------------------------------------
# Thread safety – concurrent writes
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_counter_increments(self):
        c = _collector()
        errors = []

        def worker():
            try:
                for _ in range(100):
                    c.record_translation_request("success", "worker")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        key = "translation_requests_total:session_id=worker:status=success"
        assert c._counters[key] == 1000

    def test_concurrent_histogram_records(self):
        c = _collector()
        errors = []

        def worker():
            try:
                for _ in range(50):
                    c.record_translation_duration(1.0)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# ---------------------------------------------------------------------------
# configure_metrics / get_metrics_collector globals
# ---------------------------------------------------------------------------


class TestGlobalCollector:
    def setup_method(self):
        """Reset the global before each test."""
        import iris_pgwire.sql_translator.metrics as mod

        mod._metrics_collector = None

    def test_get_metrics_collector_creates_instance(self):
        c = get_metrics_collector()
        assert isinstance(c, TranslationMetricsCollector)

    def test_get_metrics_collector_is_singleton(self):
        c1 = get_metrics_collector()
        c2 = get_metrics_collector()
        assert c1 is c2

    def test_configure_metrics_replaces_singleton(self):
        c1 = get_metrics_collector()
        c2 = configure_metrics(enable_otel=False, enable_prometheus=False)
        assert c1 is not c2
        assert get_metrics_collector() is c2

    def test_configure_metrics_passes_options(self):
        c = configure_metrics(enable_otel=False, enable_prometheus=False, otel_endpoint=None)
        assert isinstance(c, TranslationMetricsCollector)
        assert c.enable_otel is False
        assert c.enable_prometheus is False

    def teardown_method(self):
        """Clean up global after each test."""
        import iris_pgwire.sql_translator.metrics as mod

        mod._metrics_collector = None


# ---------------------------------------------------------------------------
# _record_* helpers with no labels (branch coverage)
# ---------------------------------------------------------------------------


class TestRecordHelperNoLabels:
    def test_record_counter_no_labels(self):
        c = _collector()
        c._record_counter("translation_requests_total", 1)
        assert c._counters["translation_requests_total:"] == 1

    def test_record_histogram_no_labels(self):
        c = _collector()
        c._record_histogram("translation_duration_ms", 2.5)
        assert c._histograms["translation_duration_ms:"][-1] == 2.5

    def test_record_gauge_no_labels(self):
        c = _collector()
        c._record_gauge("cache_hit_rate", 90.0)
        assert c._gauges["cache_hit_rate:"] == 90.0


# ---------------------------------------------------------------------------
# OTEL backend path (mocked) — exercises _setup_otel, _create_otel_metric
# ---------------------------------------------------------------------------


class TestOTELBackendMocked:
    def test_otel_setup_failure_disables_otel(self):
        """If _setup_otel raises, enable_otel is set to False."""
        with patch("iris_pgwire.sql_translator.metrics.OTEL_AVAILABLE", True):
            with patch(
                "iris_pgwire.sql_translator.metrics.trace.set_tracer_provider",
                side_effect=RuntimeError("otel broken"),
            ):
                c = TranslationMetricsCollector(enable_otel=True)
        assert c.enable_otel is False

    def test_otel_counter_increment_error_swallowed(self):
        """Error in OTEL counter.add is caught and printed, not raised."""
        c = _collector()
        c.enable_otel = True
        mock_counter = MagicMock()
        mock_counter.add.side_effect = RuntimeError("counter broken")
        c._otel_counters = {"translation_requests_total": mock_counter}
        # Should not raise
        c._record_counter("translation_requests_total", 1, {"status": "ok"})
        assert c._counters["translation_requests_total:status=ok"] == 1


# ---------------------------------------------------------------------------
# Prometheus backend path (mocked)
# ---------------------------------------------------------------------------


class TestPrometheusBackendMocked:
    def test_prometheus_setup_failure_disables_prometheus(self):
        """If _setup_prometheus raises, enable_prometheus is set to False."""
        with patch("iris_pgwire.sql_translator.metrics.PROMETHEUS_AVAILABLE", True):
            with patch(
                "iris_pgwire.sql_translator.metrics.CollectorRegistry",
                side_effect=RuntimeError("prometheus broken"),
            ):
                c = TranslationMetricsCollector(enable_prometheus=True)
        assert c.enable_prometheus is False

    def test_prometheus_counter_error_swallowed(self):
        """Error in prometheus counter.inc is caught and printed, not raised."""
        c = _collector()
        c.enable_prometheus = True
        mock_counter = MagicMock()
        mock_counter.labels.return_value.inc.side_effect = RuntimeError("counter broken")
        c._prometheus_counters = {"translation_requests_total": mock_counter}
        c._record_counter("translation_requests_total", 1, {"status": "ok"})
        assert c._counters["translation_requests_total:status=ok"] == 1

    def test_prometheus_histogram_error_swallowed(self):
        c = _collector()
        c.enable_prometheus = True
        mock_hist = MagicMock()
        mock_hist.labels.return_value.observe.side_effect = RuntimeError("hist broken")
        c._prometheus_histograms = {"translation_duration_ms": mock_hist}
        c._record_histogram("translation_duration_ms", 1.0, {"cache_hit": "False"})
        assert len(c._histograms["translation_duration_ms:cache_hit=False"]) == 1

    def test_prometheus_gauge_error_swallowed(self):
        c = _collector()
        c.enable_prometheus = True
        mock_gauge = MagicMock()
        mock_gauge.labels.return_value.set.side_effect = RuntimeError("gauge broken")
        c._prometheus_gauges = {"cache_hit_rate": mock_gauge}
        c._record_gauge("cache_hit_rate", 80.0, {"x": "y"})
        assert c._gauges["cache_hit_rate:x=y"] == 80.0

    def test_prometheus_setup_success_creates_registry(self):
        """Lines 153-157: successful Prometheus setup creates registry and dicts."""
        mock_registry = MagicMock()
        mock_counter_cls = MagicMock()
        mock_histogram_cls = MagicMock()
        mock_gauge_cls = MagicMock()

        with (
            patch("iris_pgwire.sql_translator.metrics.PROMETHEUS_AVAILABLE", True),
            patch("iris_pgwire.sql_translator.metrics.CollectorRegistry", return_value=mock_registry),
            patch("iris_pgwire.sql_translator.metrics.Counter", mock_counter_cls),
            patch("iris_pgwire.sql_translator.metrics.Histogram", mock_histogram_cls),
            patch("iris_pgwire.sql_translator.metrics.Gauge", mock_gauge_cls),
        ):
            c = TranslationMetricsCollector(enable_prometheus=True)

        assert c.enable_prometheus is True
        assert c.prometheus_registry is mock_registry
        # Should have created some counters/histograms/gauges from definitions
        assert mock_counter_cls.called or mock_histogram_cls.called or mock_gauge_cls.called

    def test_prometheus_create_metric_error_is_swallowed(self):
        """Lines 288-289: exception in _create_prometheus_metric is caught."""
        mock_registry = MagicMock()
        mock_counter_cls = MagicMock(side_effect=RuntimeError("counter creation failed"))
        mock_histogram_cls = MagicMock(side_effect=RuntimeError("histogram creation failed"))
        mock_gauge_cls = MagicMock(side_effect=RuntimeError("gauge creation failed"))

        with (
            patch("iris_pgwire.sql_translator.metrics.PROMETHEUS_AVAILABLE", True),
            patch("iris_pgwire.sql_translator.metrics.CollectorRegistry", return_value=mock_registry),
            patch("iris_pgwire.sql_translator.metrics.Counter", mock_counter_cls),
            patch("iris_pgwire.sql_translator.metrics.Histogram", mock_histogram_cls),
            patch("iris_pgwire.sql_translator.metrics.Gauge", mock_gauge_cls),
        ):
            # Should not raise even though all metric creation fails
            c = TranslationMetricsCollector(enable_prometheus=True)

        assert c.enable_prometheus is True

    def test_prometheus_counter_no_labels(self):
        """Lines 374-378 branch: counter increment without labels."""
        c = _collector()
        c.enable_prometheus = True
        mock_counter = MagicMock()
        c._prometheus_counters = {"translation_requests_total": mock_counter}
        c._record_counter("translation_requests_total", 1, {})
        mock_counter.inc.assert_called_once_with(1)

    def test_prometheus_histogram_no_labels(self):
        """Lines 402-404 branch: histogram observe without labels."""
        c = _collector()
        c.enable_prometheus = True
        mock_hist = MagicMock()
        c._prometheus_histograms = {"translation_duration_ms": mock_hist}
        c._record_histogram("translation_duration_ms", 2.5, {})
        mock_hist.observe.assert_called_once_with(2.5)

    def test_prometheus_gauge_no_labels(self):
        """Lines 431-433 branch: gauge set without labels."""
        c = _collector()
        c.enable_prometheus = True
        mock_gauge = MagicMock()
        c._prometheus_gauges = {"cache_hit_rate": mock_gauge}
        c._record_gauge("cache_hit_rate", 75.0, {})
        mock_gauge.set.assert_called_once_with(75.0)

    def test_prometheus_generate_latest_success(self):
        """Lines 489-494: get_prometheus_metrics when enabled and generate_latest works."""
        c = _collector()
        c.enable_prometheus = True
        c.prometheus_registry = MagicMock()

        # generate_latest is imported locally inside get_prometheus_metrics;
        # patch it in the prometheus_client namespace
        import sys
        import types

        fake_prom = types.ModuleType("prometheus_client")
        fake_prom.generate_latest = MagicMock(
            return_value=b"# HELP translation_requests_total ...\n"
        )
        fake_prom.CollectorRegistry = MagicMock
        fake_prom.Counter = MagicMock
        fake_prom.Gauge = MagicMock
        fake_prom.Histogram = MagicMock

        with patch.dict(sys.modules, {"prometheus_client": fake_prom}):
            result = c.get_prometheus_metrics()
        assert result == "# HELP translation_requests_total ...\n"

    def test_prometheus_generate_latest_error(self):
        """Lines 494-495: get_prometheus_metrics when generate_latest raises."""
        c = _collector()
        c.enable_prometheus = True
        c.prometheus_registry = MagicMock()

        import sys
        import types

        fake_prom = types.ModuleType("prometheus_client")
        fake_prom.generate_latest = MagicMock(side_effect=RuntimeError("format error"))
        fake_prom.CollectorRegistry = MagicMock
        fake_prom.Counter = MagicMock
        fake_prom.Gauge = MagicMock
        fake_prom.Histogram = MagicMock

        with patch.dict(sys.modules, {"prometheus_client": fake_prom}):
            result = c.get_prometheus_metrics()
        assert result is None


# ---------------------------------------------------------------------------
# OTEL backend – full setup path (mocked)
# ---------------------------------------------------------------------------


class TestOTELFullSetup:
    def _inject_otel_sys_modules(self):
        """Build and return fake OTEL sys.modules entries + sentinel mocks."""
        import sys
        import types

        mock_tracer = MagicMock()
        mock_meter = MagicMock()
        mock_tracer_provider_instance = MagicMock()

        fake_trace = MagicMock()
        fake_trace.set_tracer_provider = MagicMock()
        fake_trace.get_tracer_provider.return_value = mock_tracer_provider_instance
        fake_trace.get_tracer.return_value = mock_tracer

        fake_otel_metrics = MagicMock()
        fake_otel_metrics.set_meter_provider = MagicMock()
        fake_otel_metrics.get_meter.return_value = mock_meter

        fake_TracerProvider = MagicMock(return_value=mock_tracer_provider_instance)
        fake_MeterProvider = MagicMock()
        fake_BatchSpanProcessor = MagicMock()
        fake_OTLPSpanExporter = MagicMock()
        fake_OTLPMetricExporter = MagicMock()
        fake_PeriodicReader = MagicMock()

        # Build minimal fake modules
        otel_mod = types.ModuleType("opentelemetry")
        otel_trace_mod = types.ModuleType("opentelemetry.trace")
        otel_trace_mod.set_tracer_provider = fake_trace.set_tracer_provider
        otel_trace_mod.get_tracer_provider = fake_trace.get_tracer_provider
        otel_trace_mod.get_tracer = fake_trace.get_tracer

        otel_metrics_mod = types.ModuleType("opentelemetry.metrics")
        otel_metrics_mod.set_meter_provider = fake_otel_metrics.set_meter_provider
        otel_metrics_mod.get_meter = fake_otel_metrics.get_meter

        sdk_trace_mod = types.ModuleType("opentelemetry.sdk.trace")
        sdk_trace_mod.TracerProvider = fake_TracerProvider
        sdk_trace_export_mod = types.ModuleType("opentelemetry.sdk.trace.export")
        sdk_trace_export_mod.BatchSpanProcessor = fake_BatchSpanProcessor
        sdk_metrics_mod = types.ModuleType("opentelemetry.sdk.metrics")
        sdk_metrics_mod.MeterProvider = fake_MeterProvider
        sdk_metrics_export_mod = types.ModuleType("opentelemetry.sdk.metrics.export")
        sdk_metrics_export_mod.PeriodicExportingMetricReader = fake_PeriodicReader
        otlp_trace_mod = types.ModuleType("opentelemetry.exporter.otlp.proto.grpc.trace_exporter")
        otlp_trace_mod.OTLPSpanExporter = fake_OTLPSpanExporter
        otlp_metric_mod = types.ModuleType("opentelemetry.exporter.otlp.proto.grpc.metric_exporter")
        otlp_metric_mod.OTLPMetricExporter = fake_OTLPMetricExporter

        fake_sys_modules = {
            "opentelemetry": otel_mod,
            "opentelemetry.trace": otel_trace_mod,
            "opentelemetry.metrics": otel_metrics_mod,
            "opentelemetry.sdk": types.ModuleType("opentelemetry.sdk"),
            "opentelemetry.sdk.trace": sdk_trace_mod,
            "opentelemetry.sdk.trace.export": sdk_trace_export_mod,
            "opentelemetry.sdk.metrics": sdk_metrics_mod,
            "opentelemetry.sdk.metrics.export": sdk_metrics_export_mod,
            "opentelemetry.exporter": types.ModuleType("opentelemetry.exporter"),
            "opentelemetry.exporter.otlp": types.ModuleType("opentelemetry.exporter.otlp"),
            "opentelemetry.exporter.otlp.proto": types.ModuleType("opentelemetry.exporter.otlp.proto"),
            "opentelemetry.exporter.otlp.proto.grpc": types.ModuleType("opentelemetry.exporter.otlp.proto.grpc"),
            "opentelemetry.exporter.otlp.proto.grpc.trace_exporter": otlp_trace_mod,
            "opentelemetry.exporter.otlp.proto.grpc.metric_exporter": otlp_metric_mod,
        }

        return {
            "sys_modules": fake_sys_modules,
            "mock_tracer": mock_tracer,
            "mock_meter": mock_meter,
            "mock_tracer_provider_instance": mock_tracer_provider_instance,
            "fake_TracerProvider": fake_TracerProvider,
            "fake_BatchSpanProcessor": fake_BatchSpanProcessor,
            "fake_trace": fake_trace,
            "fake_otel_metrics": fake_otel_metrics,
        }

    def test_otel_setup_success_no_endpoint(self):
        """Lines 120-142: _setup_otel succeeds when OTEL_AVAILABLE is True.
        We re-import the module under a patched sys.modules to simulate OTEL being installed.
        """
        # Since OTEL isn't installed we exercise _setup_otel via direct method call
        # with mocked module-level attributes injected at runtime.
        c = _collector()
        c.enable_otel = True

        mock_tracer = MagicMock()
        mock_meter = MagicMock()
        mock_tp = MagicMock()

        import iris_pgwire.sql_translator.metrics as metrics_mod

        orig_otel_available = metrics_mod.OTEL_AVAILABLE
        try:
            metrics_mod.OTEL_AVAILABLE = True
            metrics_mod.TracerProvider = MagicMock(return_value=mock_tp)
            metrics_mod.trace = MagicMock()
            metrics_mod.trace.set_tracer_provider = MagicMock()
            metrics_mod.trace.get_tracer_provider = MagicMock(return_value=mock_tp)
            metrics_mod.trace.get_tracer = MagicMock(return_value=mock_tracer)
            metrics_mod.otel_metrics = MagicMock()
            metrics_mod.otel_metrics.set_meter_provider = MagicMock()
            metrics_mod.otel_metrics.get_meter = MagicMock(return_value=mock_meter)

            c._setup_otel()
        finally:
            metrics_mod.OTEL_AVAILABLE = orig_otel_available
            # Clean up injected attributes
            for attr in ("TracerProvider", "trace", "otel_metrics"):
                if hasattr(metrics_mod, attr):
                    try:
                        delattr(metrics_mod, attr)
                    except AttributeError:
                        pass

        assert c.tracer is mock_tracer
        assert c.meter is mock_meter

    def test_otel_setup_with_endpoint(self):
        """Lines 123-135: _setup_otel with otel_endpoint creates exporters."""
        c = _collector()
        c.enable_otel = True
        c.otel_endpoint = "http://otel-collector:4317"

        mock_tracer = MagicMock()
        mock_meter = MagicMock()
        mock_tp = MagicMock()
        mock_span_processor = MagicMock()

        import iris_pgwire.sql_translator.metrics as metrics_mod

        orig_otel_available = metrics_mod.OTEL_AVAILABLE
        try:
            metrics_mod.OTEL_AVAILABLE = True
            metrics_mod.TracerProvider = MagicMock(return_value=mock_tp)
            metrics_mod.OTLPSpanExporter = MagicMock()
            metrics_mod.BatchSpanProcessor = MagicMock(return_value=mock_span_processor)
            metrics_mod.OTLPMetricExporter = MagicMock()
            metrics_mod.PeriodicExportingMetricReader = MagicMock()
            metrics_mod.MeterProvider = MagicMock()
            metrics_mod.trace = MagicMock()
            metrics_mod.trace.set_tracer_provider = MagicMock()
            metrics_mod.trace.get_tracer_provider = MagicMock(return_value=mock_tp)
            metrics_mod.trace.get_tracer = MagicMock(return_value=mock_tracer)
            metrics_mod.otel_metrics = MagicMock()
            metrics_mod.otel_metrics.set_meter_provider = MagicMock()
            metrics_mod.otel_metrics.get_meter = MagicMock(return_value=mock_meter)

            c._setup_otel()
        finally:
            metrics_mod.OTEL_AVAILABLE = orig_otel_available
            for attr in (
                "TracerProvider", "OTLPSpanExporter", "BatchSpanProcessor",
                "OTLPMetricExporter", "PeriodicExportingMetricReader", "MeterProvider",
                "trace", "otel_metrics",
            ):
                if hasattr(metrics_mod, attr):
                    try:
                        delattr(metrics_mod, attr)
                    except AttributeError:
                        pass

        mock_tp.add_span_processor.assert_called_once_with(mock_span_processor)
        assert c.tracer is mock_tracer

    def test_otel_create_counter_metric(self):
        """Lines 246-249: _create_otel_metric creates a counter."""
        c = _collector()
        c.enable_otel = True
        mock_meter = MagicMock()
        mock_counter = MagicMock()
        mock_meter.create_counter.return_value = mock_counter
        c.meter = mock_meter
        c._otel_counters = {}
        c._otel_histograms = {}
        c._otel_gauges = {}

        defn = MetricDefinition("my_counter", MetricType.COUNTER, "A counter", "ops")
        c._create_otel_metric("my_counter", defn)

        mock_meter.create_counter.assert_called_once()
        assert c._otel_counters["my_counter"] is mock_counter

    def test_otel_create_histogram_metric(self):
        """Lines 250-253: _create_otel_metric creates a histogram."""
        c = _collector()
        c.enable_otel = True
        mock_meter = MagicMock()
        mock_hist = MagicMock()
        mock_meter.create_histogram.return_value = mock_hist
        c.meter = mock_meter
        c._otel_counters = {}
        c._otel_histograms = {}
        c._otel_gauges = {}

        defn = MetricDefinition("my_hist", MetricType.HISTOGRAM, "A histogram", "ms")
        c._create_otel_metric("my_hist", defn)

        mock_meter.create_histogram.assert_called_once()
        assert c._otel_histograms["my_hist"] is mock_hist

    def test_otel_create_gauge_metric(self):
        """Lines 254-257: _create_otel_metric creates a gauge."""
        c = _collector()
        c.enable_otel = True
        mock_meter = MagicMock()
        mock_gauge = MagicMock()
        mock_meter.create_gauge.return_value = mock_gauge
        c.meter = mock_meter
        c._otel_counters = {}
        c._otel_histograms = {}
        c._otel_gauges = {}

        defn = MetricDefinition("my_gauge", MetricType.GAUGE, "A gauge", "%")
        c._create_otel_metric("my_gauge", defn)

        mock_meter.create_gauge.assert_called_once()
        assert c._otel_gauges["my_gauge"] is mock_gauge

    def test_otel_create_metric_disabled_returns_early(self):
        """Line 242-243: _create_otel_metric returns early if otel disabled."""
        c = _collector()
        c.enable_otel = False
        # Should not raise even without meter set up
        defn = MetricDefinition("my_counter", MetricType.COUNTER, "A counter")
        c._create_otel_metric("my_counter", defn)  # no-op

    def test_otel_create_metric_error_swallowed(self):
        """Lines 258-259: exception in _create_otel_metric is caught."""
        c = _collector()
        c.enable_otel = True
        mock_meter = MagicMock()
        mock_meter.create_counter.side_effect = RuntimeError("instrument error")
        c.meter = mock_meter
        c._otel_counters = {}

        defn = MetricDefinition("bad_counter", MetricType.COUNTER, "Should fail")
        c._create_otel_metric("bad_counter", defn)  # should not raise

    def test_otel_histogram_record_with_labels(self):
        """Lines 394-396: OTEL histogram record with labels."""
        c = _collector()
        c.enable_otel = True
        mock_hist = MagicMock()
        c._otel_histograms = {"translation_duration_ms": mock_hist}
        c._record_histogram("translation_duration_ms", 3.0, {"cache_hit": "True"})
        mock_hist.record.assert_called_once_with(3.0, {"cache_hit": "True"})

    def test_otel_gauge_set_with_labels(self):
        """Lines 423-425: OTEL gauge set with labels."""
        c = _collector()
        c.enable_otel = True
        mock_gauge = MagicMock()
        c._otel_gauges = {"cache_hit_rate": mock_gauge}
        c._record_gauge("cache_hit_rate", 90.0, {"x": "y"})
        mock_gauge.set.assert_called_once_with(90.0, {"x": "y"})

    def test_otel_span_start_end_success(self):
        """Lines 444-464: start and end OTEL span when enabled."""
        c = _collector()
        c.enable_otel = True
        mock_span = MagicMock()
        mock_tracer = MagicMock()
        mock_tracer.start_span.return_value = mock_span
        c.tracer = mock_tracer

        span = c.start_translation_span("SELECT 1", "sess-1")
        assert span is mock_span
        mock_span.set_attribute.assert_any_call("sql.length", 8)
        mock_span.set_attribute.assert_any_call("session.id", "sess-1")

        c.end_translation_span(span, True, 2)
        mock_span.set_attribute.assert_any_call("translation.success", True)
        mock_span.set_attribute.assert_any_call("constructs.translated", 2)
        mock_span.end.assert_called_once()

    def test_otel_span_start_error_returns_none(self):
        """Line 451: exception in start_translation_span returns None."""
        c = _collector()
        c.enable_otel = True
        mock_tracer = MagicMock()
        mock_tracer.start_span.side_effect = RuntimeError("span error")
        c.tracer = mock_tracer

        span = c.start_translation_span("SELECT 1", "sess-1")
        assert span is None

    def test_otel_span_end_error_is_swallowed(self):
        """Line 463-464: exception in end_translation_span is swallowed."""
        c = _collector()
        c.enable_otel = True
        mock_span = MagicMock()
        mock_span.end.side_effect = RuntimeError("end error")

        c.end_translation_span(mock_span, True, 0)  # should not raise

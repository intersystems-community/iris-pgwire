"""
Metrics Collection for SQL Translation Performance

Comprehensive metrics collection system with support for multiple backends including
OpenTelemetry (OTEL), Prometheus, and internal monitoring for constitutional compliance.

Constitutional Compliance: Real-time performance metrics and SLA monitoring.
"""

import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Optional OpenTelemetry imports
try:
    from opentelemetry import metrics as otel_metrics
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False

# Optional Prometheus imports
try:
    from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False


class MetricType(Enum):
    """Types of metrics to collect"""

    COUNTER = "counter"
    HISTOGRAM = "histogram"
    GAUGE = "gauge"
    SUMMARY = "summary"


@dataclass
class MetricDefinition:
    """Definition of a metric to collect"""

    name: str
    metric_type: MetricType
    description: str
    unit: str = ""
    labels: list[str] = field(default_factory=list)


@dataclass
class MetricEvent:
    """Individual metric event"""

    name: str
    value: int | float
    labels: dict[str, str] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)


class TranslationMetricsCollector:
    """
    Comprehensive metrics collector for SQL translation system

    Features:
    - OpenTelemetry integration for distributed tracing
    - Prometheus metrics export
    - Internal metrics for constitutional compliance
    - Real-time performance monitoring
    - Custom metric definitions
    """

    def __init__(
        self,
        enable_otel: bool = False,
        enable_prometheus: bool = False,
        otel_endpoint: str | None = None,
        iris_connection=None,
    ):
        """
        Initialize metrics collector

        Args:
            enable_otel: Enable OpenTelemetry integration
            enable_prometheus: Enable Prometheus metrics
            otel_endpoint: OpenTelemetry collector endpoint
            iris_connection: IRIS connection for version detection and fallback monitoring
        """
        self.iris_connection = iris_connection
        self.iris_version = None
        self.iris_otel_native = False
        self.iris_monitor_api_fallback = False

        # Detect IRIS capabilities for OpenTelemetry integration
        self._detect_iris_capabilities()

        # Configure OTEL based on IRIS capabilities
        if enable_otel and OTEL_AVAILABLE:
            if self.iris_otel_native:
                # IRIS 2025.2+ with native OpenTelemetry
                self.enable_otel = True
                self.otel_endpoint = otel_endpoint or self._get_iris_otlp_endpoint()
                logger.info(
                    "Using IRIS native OpenTelemetry (IRIS 2025.2+)", endpoint=self.otel_endpoint
                )
            elif self.iris_monitor_api_fallback:
                # IRIS 2025.1 with /api/monitor fallback
                self.enable_otel = True
                self.otel_endpoint = otel_endpoint  # External OTEL collector
                logger.info(
                    "Using IRIS /api/monitor fallback with external OTEL (IRIS 2025.1)",
                    endpoint=self.otel_endpoint,
                    monitor_api=True,
                )
            else:
                # Pre-2025.1 IRIS - external OTEL only
                self.enable_otel = enable_otel
                self.otel_endpoint = otel_endpoint
                logger.info(
                    "Using external OpenTelemetry only (IRIS < 2025.1)", endpoint=self.otel_endpoint
                )
        else:
            self.enable_otel = enable_otel and OTEL_AVAILABLE
            self.otel_endpoint = otel_endpoint

        self.enable_prometheus = enable_prometheus and PROMETHEUS_AVAILABLE

        # Internal metrics storage
        self._lock = threading.RLock()
        self._counters: dict[str, int] = defaultdict(int)
        self._histograms: dict[str, deque] = defaultdict(lambda: deque(maxlen=10000))
        self._gauges: dict[str, float] = {}
        self._metric_events: deque = deque(maxlen=50000)

        # Initialize backends
        self._setup_otel() if self.enable_otel else None
        self._setup_prometheus() if self.enable_prometheus else None

        # Define standard translation metrics
        self._define_translation_metrics()

    def _setup_otel(self):
        """Setup OpenTelemetry tracing and metrics"""
        if not OTEL_AVAILABLE:
            return

        try:
            # Setup tracing
            trace.set_tracer_provider(TracerProvider())
            tracer_provider = trace.get_tracer_provider()

            if self.otel_endpoint:
                otlp_exporter = OTLPSpanExporter(endpoint=self.otel_endpoint)
                span_processor = BatchSpanProcessor(otlp_exporter)
                tracer_provider.add_span_processor(span_processor)

            self.tracer = trace.get_tracer("iris_pgwire.sql_translator")

            # Setup metrics
            if self.otel_endpoint:
                metric_reader = PeriodicExportingMetricReader(
                    OTLPMetricExporter(endpoint=self.otel_endpoint), export_interval_millis=5000
                )
                otel_metrics.set_meter_provider(MeterProvider(metric_readers=[metric_reader]))

            self.meter = otel_metrics.get_meter("iris_pgwire.sql_translator")

            # Create OTEL instruments
            self._otel_counters = {}
            self._otel_histograms = {}
            self._otel_gauges = {}

        except Exception as e:
            print(f"Failed to setup OpenTelemetry: {e}")
            self.enable_otel = False

    def _setup_prometheus(self):
        """Setup Prometheus metrics"""
        if not PROMETHEUS_AVAILABLE:
            return

        try:
            self.prometheus_registry = CollectorRegistry()
            self._prometheus_counters = {}
            self._prometheus_histograms = {}
            self._prometheus_gauges = {}

        except Exception as e:
            print(f"Failed to setup Prometheus: {e}")
            self.enable_prometheus = False

    def _define_translation_metrics(self):
        """Define standard SQL translation metrics"""
        self.metric_definitions = {
            # Translation performance
            "translation_requests_total": MetricDefinition(
                "translation_requests_total",
                MetricType.COUNTER,
                "Total number of SQL translation requests",
                labels=["status", "session_id"],
            ),
            "translation_duration_ms": MetricDefinition(
                "translation_duration_ms",
                MetricType.HISTOGRAM,
                "SQL translation duration in milliseconds",
                "ms",
                ["cache_hit", "constructs_found"],
            ),
            "constructs_translated_total": MetricDefinition(
                "constructs_translated_total",
                MetricType.COUNTER,
                "Total number of IRIS constructs translated",
                labels=["construct_type"],
            ),
            "cache_operations_total": MetricDefinition(
                "cache_operations_total",
                MetricType.COUNTER,
                "Total cache operations",
                labels=["operation", "result"],
            ),
            "cache_hit_rate": MetricDefinition(
                "cache_hit_rate", MetricType.GAUGE, "Cache hit rate percentage", "%"
            ),
            # Constitutional compliance
            "sla_violations_total": MetricDefinition(
                "sla_violations_total",
                MetricType.COUNTER,
                "Total SLA violations (>5ms)",
                labels=["component", "violation_type"],
            ),
            "sla_compliance_rate": MetricDefinition(
                "sla_compliance_rate", MetricType.GAUGE, "SLA compliance rate percentage", "%"
            ),
            # Validation metrics
            "validation_success_total": MetricDefinition(
                "validation_success_total",
                MetricType.COUNTER,
                "Total successful validations",
                labels=["validation_level"],
            ),
            "validation_failures_total": MetricDefinition(
                "validation_failures_total",
                MetricType.COUNTER,
                "Total validation failures",
                labels=["validation_level", "issue_type"],
            ),
            # Error metrics
            "translation_errors_total": MetricDefinition(
                "translation_errors_total",
                MetricType.COUNTER,
                "Total translation errors",
                labels=["error_type", "component"],
            ),
        }

        # Create metrics in backends
        self._create_backend_metrics()

    def _detect_iris_capabilities(self):
        """
        Detect IRIS version and OpenTelemetry capabilities

        Based on rag-templates pattern for IRIS version detection:
        - IRIS 2025.2+: Native OpenTelemetry with OTLP/HTTP export
        - IRIS 2025.1: /api/monitor fallback with external OTEL
        - IRIS < 2025.1: External OTEL only
        """
        if not self.iris_connection:
            logger.warning("No IRIS connection provided for capability detection")
            return

        try:
            # Detect IRIS version using %SYSTEM.Version
            if hasattr(self.iris_connection, "execute"):
                # Embedded Python connection
                result = self.iris_connection.execute("SELECT %Version FROM %SYSTEM.Version")
                version_string = result.fetchone()[0] if result else None
            else:
                # External connection
                cursor = self.iris_connection.cursor()
                cursor.execute("SELECT %Version FROM %SYSTEM.Version")
                version_string = cursor.fetchone()[0]
                cursor.close()

            if version_string:
                self.iris_version = version_string
                logger.info(f"Detected IRIS version: {version_string}")

                # Parse version to determine capabilities
                # Version format: "IRIS for UNIX (Ubuntu Server 22.04 LTS for x86-64) 2025.2 (Build 123U) Fri Oct 25 2024 17:22:10 EDT"
                if "2025.2" in version_string or "2026." in version_string:
                    self.iris_otel_native = True
                    logger.info("IRIS 2025.2+ detected - native OpenTelemetry available")
                elif "2025.1" in version_string:
                    self.iris_monitor_api_fallback = True
                    logger.info("IRIS 2025.1 detected - using /api/monitor fallback")
                else:
                    logger.info("IRIS < 2025.1 detected - external OpenTelemetry only")

                # Test for /api/monitor availability if fallback mode
                if self.iris_monitor_api_fallback:
                    self._test_monitor_api_availability()

        except Exception as e:
            logger.warning(f"Failed to detect IRIS capabilities: {e}")
            # Fallback to external OTEL only
            self.iris_otel_native = False
            self.iris_monitor_api_fallback = False

    def _get_iris_otlp_endpoint(self) -> str | None:
        """
        Get IRIS native OpenTelemetry OTLP endpoint for IRIS 2025.2+

        In production, this would query IRIS configuration for the OTLP endpoint.
        For now, return a reasonable default.
        """
        # Default IRIS OTLP endpoint (would be configurable in production)
        return "http://localhost:4318/v1/traces"

    def _test_monitor_api_availability(self):
        """
        Test if IRIS /api/monitor endpoint is available for fallback metrics

        This tests the availability of the /api/monitor REST API that can be
        used to export metrics when native OpenTelemetry is not available.
        """
        try:
            # In production, this would make an HTTP request to /api/monitor
            # For now, just log that we're in fallback mode
            logger.info("IRIS /api/monitor fallback mode enabled")

            # TODO: Implement actual HTTP test to IRIS Management Portal API
            # import requests
            # response = requests.get("http://localhost:52773/api/monitor/metrics",
            #                        auth=('_SYSTEM', 'SYS'), timeout=5)
            # if response.status_code == 200:
            #     logger.info("/api/monitor endpoint verified")
            #     return True

        except Exception as e:
            logger.warning(f"Failed to verify /api/monitor endpoint: {e}")
            self.iris_monitor_api_fallback = False

    def _create_backend_metrics(self):
        """Create metrics in configured backends"""
        for name, definition in self.metric_definitions.items():
            # OpenTelemetry
            if self.enable_otel:
                self._create_otel_metric(name, definition)

            # Prometheus
            if self.enable_prometheus:
                self._create_prometheus_metric(name, definition)

    def _create_otel_metric(self, name: str, definition: MetricDefinition):
        """Create OpenTelemetry metric"""
        if not self.enable_otel:
            return

        try:
            if definition.metric_type == MetricType.COUNTER:
                self._otel_counters[name] = self.meter.create_counter(
                    name=name, description=definition.description, unit=definition.unit
                )
            elif definition.metric_type == MetricType.HISTOGRAM:
                self._otel_histograms[name] = self.meter.create_histogram(
                    name=name, description=definition.description, unit=definition.unit
                )
            elif definition.metric_type == MetricType.GAUGE:
                self._otel_gauges[name] = self.meter.create_gauge(
                    name=name, description=definition.description, unit=definition.unit
                )
        except Exception as e:
            print(f"Failed to create OTEL metric {name}: {e}")

    def _create_prometheus_metric(self, name: str, definition: MetricDefinition):
        """Create Prometheus metric"""
        if not self.enable_prometheus:
            return

        try:
            if definition.metric_type == MetricType.COUNTER:
                self._prometheus_counters[name] = Counter(
                    name=name,
                    documentation=definition.description,
                    labelnames=definition.labels,
                    registry=self.prometheus_registry,
                )
            elif definition.metric_type == MetricType.HISTOGRAM:
                self._prometheus_histograms[name] = Histogram(
                    name=name,
                    documentation=definition.description,
                    labelnames=definition.labels,
                    registry=self.prometheus_registry,
                )
            elif definition.metric_type == MetricType.GAUGE:
                self._prometheus_gauges[name] = Gauge(
                    name=name,
                    documentation=definition.description,
                    labelnames=definition.labels,
                    registry=self.prometheus_registry,
                )
        except Exception as e:
            print(f"Failed to create Prometheus metric {name}: {e}")

    # Metric recording methods
    def record_translation_request(self, status: str, session_id: str = "unknown"):
        """Record a translation request"""
        labels = {"status": status, "session_id": session_id}
        self._record_counter("translation_requests_total", 1, labels)

    def record_translation_duration(
        self, duration_ms: float, cache_hit: bool = False, constructs_found: int = 0
    ):
        """Record translation duration"""
        labels = {
            "cache_hit": str(cache_hit),
            "constructs_found": str(min(constructs_found, 10)),  # Bucket large numbers
        }
        self._record_histogram("translation_duration_ms", duration_ms, labels)

        # Check for SLA violation
        if duration_ms > 5.0:
            self.record_sla_violation("translator", "duration_exceeded", duration_ms)

    def record_construct_translated(self, construct_type: str):
        """Record a translated construct"""
        labels = {"construct_type": construct_type}
        self._record_counter("constructs_translated_total", 1, labels)

    def record_cache_operation(self, operation: str, result: str):
        """Record cache operation"""
        labels = {"operation": operation, "result": result}
        self._record_counter("cache_operations_total", 1, labels)

    def record_sla_violation(self, component: str, violation_type: str, actual_value: float):
        """Record SLA violation"""
        labels = {"component": component, "violation_type": violation_type}
        self._record_counter("sla_violations_total", 1, labels)

    def record_validation_result(
        self, success: bool, validation_level: str, issue_type: str | None = None
    ):
        """Record validation result"""
        if success:
            labels = {"validation_level": validation_level}
            self._record_counter("validation_success_total", 1, labels)
        else:
            labels = {"validation_level": validation_level, "issue_type": issue_type or "unknown"}
            self._record_counter("validation_failures_total", 1, labels)

    def record_translation_error(self, error_type: str, component: str):
        """Record translation error"""
        labels = {"error_type": error_type, "component": component}
        self._record_counter("translation_errors_total", 1, labels)

    def update_cache_hit_rate(self, hit_rate: float):
        """Update cache hit rate gauge"""
        self._record_gauge("cache_hit_rate", hit_rate * 100)  # Convert to percentage

    def update_sla_compliance_rate(self, compliance_rate: float):
        """Update SLA compliance rate gauge"""
        self._record_gauge("sla_compliance_rate", compliance_rate * 100)  # Convert to percentage

    # Internal recording methods
    def _record_counter(self, name: str, value: int | float, labels: dict[str, str] = None):
        """Record counter metric"""
        labels = labels or {}

        with self._lock:
            # Internal storage
            key = f"{name}:{':'.join(f'{k}={v}' for k, v in sorted(labels.items()))}"
            self._counters[key] += value

            # Store event
            self._metric_events.append(MetricEvent(name, value, labels))

        # OpenTelemetry
        if self.enable_otel and name in self._otel_counters:
            try:
                self._otel_counters[name].add(value, labels)
            except Exception as e:
                print(f"OTEL counter error: {e}")

        # Prometheus
        if self.enable_prometheus and name in self._prometheus_counters:
            try:
                if labels:
                    self._prometheus_counters[name].labels(**labels).inc(value)
                else:
                    self._prometheus_counters[name].inc(value)
            except Exception as e:
                print(f"Prometheus counter error: {e}")

    def _record_histogram(self, name: str, value: float, labels: dict[str, str] = None):
        """Record histogram metric"""
        labels = labels or {}

        with self._lock:
            # Internal storage
            key = f"{name}:{':'.join(f'{k}={v}' for k, v in sorted(labels.items()))}"
            self._histograms[key].append(value)

            # Store event
            self._metric_events.append(MetricEvent(name, value, labels))

        # OpenTelemetry
        if self.enable_otel and name in self._otel_histograms:
            try:
                self._otel_histograms[name].record(value, labels)
            except Exception as e:
                print(f"OTEL histogram error: {e}")

        # Prometheus
        if self.enable_prometheus and name in self._prometheus_histograms:
            try:
                if labels:
                    self._prometheus_histograms[name].labels(**labels).observe(value)
                else:
                    self._prometheus_histograms[name].observe(value)
            except Exception as e:
                print(f"Prometheus histogram error: {e}")

    def _record_gauge(self, name: str, value: float, labels: dict[str, str] = None):
        """Record gauge metric"""
        labels = labels or {}

        with self._lock:
            # Internal storage
            key = f"{name}:{':'.join(f'{k}={v}' for k, v in sorted(labels.items()))}"
            self._gauges[key] = value

            # Store event
            self._metric_events.append(MetricEvent(name, value, labels))

        # OpenTelemetry
        if self.enable_otel and name in self._otel_gauges:
            try:
                self._otel_gauges[name].set(value, labels)
            except Exception as e:
                print(f"OTEL gauge error: {e}")

        # Prometheus
        if self.enable_prometheus and name in self._prometheus_gauges:
            try:
                if labels:
                    self._prometheus_gauges[name].labels(**labels).set(value)
                else:
                    self._prometheus_gauges[name].set(value)
            except Exception as e:
                print(f"Prometheus gauge error: {e}")

    # OpenTelemetry tracing support
    def start_translation_span(self, sql: str, session_id: str) -> Any | None:
        """Start OpenTelemetry span for translation"""
        if not self.enable_otel:
            return None

        try:
            span = self.tracer.start_span("sql_translation")
            span.set_attribute("sql.length", len(sql))
            span.set_attribute("session.id", session_id)
            span.set_attribute("component", "sql_translator")
            return span
        except Exception as e:
            print(f"Failed to start OTEL span: {e}")
            return None

    def end_translation_span(self, span: Any, success: bool, constructs_translated: int):
        """End OpenTelemetry span"""
        if not self.enable_otel or not span:
            return

        try:
            span.set_attribute("translation.success", success)
            span.set_attribute("constructs.translated", constructs_translated)
            span.end()
        except Exception as e:
            print(f"Failed to end OTEL span: {e}")

    # Metrics retrieval
    def get_metrics_summary(self) -> dict[str, Any]:
        """Get summary of all collected metrics"""
        with self._lock:
            return {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histogram_counts": {k: len(v) for k, v in self._histograms.items()},
                "total_events": len(self._metric_events),
                "backends": {
                    "otel_enabled": self.enable_otel,
                    "prometheus_enabled": self.enable_prometheus,
                    "otel_available": OTEL_AVAILABLE,
                    "prometheus_available": PROMETHEUS_AVAILABLE,
                },
                "collection_timestamp": datetime.now(UTC).isoformat(),
            }

    def get_prometheus_metrics(self) -> str | None:
        """Get Prometheus metrics in text format"""
        if not self.enable_prometheus:
            return None

        try:
            from prometheus_client import generate_latest

            return generate_latest(self.prometheus_registry).decode("utf-8")
        except Exception as e:
            print(f"Failed to generate Prometheus metrics: {e}")
            return None

    def export_to_iris_monitor_api(self) -> bool:
        """
        Export metrics to IRIS /api/monitor endpoint for IRIS 2025.1 fallback

        This implements the fallback pattern from rag-templates where IRIS 2025.1
        uses /api/monitor REST API for metrics collection instead of native OTEL.
        """
        if not self.iris_monitor_api_fallback:
            return False

        try:
            # Collect current metrics in a format suitable for IRIS /api/monitor
            metrics_data = {
                "timestamp": datetime.now(UTC).isoformat(),
                "source": "iris_pgwire_translator",
                "metrics": {},
            }

            with self._lock:
                # Export counters
                for key, value in self._counters.items():
                    metrics_data["metrics"][f"counter_{key}"] = value

                # Export gauges
                for key, value in self._gauges.items():
                    metrics_data["metrics"][f"gauge_{key}"] = value

                # Export histogram stats
                for key, values in self._histograms.items():
                    if values:
                        metrics_data["metrics"][f"histogram_{key}_count"] = len(values)
                        metrics_data["metrics"][f"histogram_{key}_avg"] = sum(values) / len(values)
                        metrics_data["metrics"][f"histogram_{key}_max"] = max(values)
                        metrics_data["metrics"][f"histogram_{key}_min"] = min(values)

            # TODO: In production, POST this data to IRIS /api/monitor endpoint
            # import requests
            # response = requests.post(
            #     "http://localhost:52773/api/monitor/metrics",
            #     json=metrics_data,
            #     auth=('_SYSTEM', 'SYS'),
            #     timeout=10
            # )
            # if response.status_code == 200:
            #     logger.debug("Metrics exported to IRIS /api/monitor successfully")
            #     return True

            # For now, log the metrics that would be exported
            logger.debug(
                "IRIS /api/monitor export (simulated)", metrics_count=len(metrics_data["metrics"])
            )

            return True

        except Exception as e:
            logger.warning(f"Failed to export metrics to IRIS /api/monitor: {e}")
            return False

    def get_iris_integration_status(self) -> dict[str, Any]:
        """
        Get status of IRIS OpenTelemetry integration

        Returns current state of IRIS version detection and telemetry capabilities
        """
        return {
            "iris_version": self.iris_version,
            "iris_otel_native": self.iris_otel_native,
            "iris_monitor_api_fallback": self.iris_monitor_api_fallback,
            "otel_endpoint": self.otel_endpoint,
            "integration_mode": (
                "native_otel"
                if self.iris_otel_native
                else (
                    "monitor_api_fallback"
                    if self.iris_monitor_api_fallback
                    else "external_otel_only"
                )
            ),
            "capabilities": {
                "native_otlp_export": self.iris_otel_native,
                "monitor_api_polling": self.iris_monitor_api_fallback,
                "external_otel_collectors": True,
            },
        }


# Global metrics collector
_metrics_collector = None


def get_metrics_collector() -> TranslationMetricsCollector:
    """Get the global metrics collector instance"""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = TranslationMetricsCollector()
    return _metrics_collector


def configure_metrics(
    enable_otel: bool = False,
    enable_prometheus: bool = False,
    otel_endpoint: str | None = None,
    iris_connection=None,
) -> TranslationMetricsCollector:
    """
    Configure metrics collection with IRIS integration

    Args:
        enable_otel: Enable OpenTelemetry integration
        enable_prometheus: Enable Prometheus metrics
        otel_endpoint: OpenTelemetry collector endpoint
        iris_connection: IRIS connection for version detection and native OTEL

    Returns:
        Configured metrics collector with IRIS integration capabilities
    """
    global _metrics_collector
    _metrics_collector = TranslationMetricsCollector(
        enable_otel=enable_otel,
        enable_prometheus=enable_prometheus,
        otel_endpoint=otel_endpoint,
        iris_connection=iris_connection,
    )
    return _metrics_collector


# Export main components
__all__ = [
    "TranslationMetricsCollector",
    "MetricDefinition",
    "MetricEvent",
    "MetricType",
    "get_metrics_collector",
    "configure_metrics",
    "OTEL_AVAILABLE",
    "PROMETHEUS_AVAILABLE",
]

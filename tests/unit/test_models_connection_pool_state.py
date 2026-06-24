"""
Unit tests for iris_pgwire/models/connection_pool_state.py.

Covers ConnectionPoolState construction, utilization_percent,
is_exhausted, is_degraded, and to_health_check_response — all
without external I/O.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from iris_pgwire.models.connection_pool_state import ConnectionPoolState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _healthy(**kwargs) -> ConnectionPoolState:
    defaults = dict(
        total_connections=100,
        connections_in_use=20,
        connections_available=80,
        max_connections_in_use=50,
        is_healthy=True,
    )
    defaults.update(kwargs)
    return ConnectionPoolState(**defaults)


def _unhealthy(**kwargs) -> ConnectionPoolState:
    defaults = dict(
        total_connections=100,
        connections_in_use=20,
        connections_available=80,
        max_connections_in_use=50,
        is_healthy=False,
        degraded_reason="DB down",
    )
    defaults.update(kwargs)
    return ConnectionPoolState(**defaults)


# ---------------------------------------------------------------------------
# Construction & defaults
# ---------------------------------------------------------------------------


class TestConnectionPoolStateDefaults:
    def test_connections_created_defaults_zero(self):
        s = _healthy()
        assert s.connections_created == 0

    def test_connections_recycled_defaults_zero(self):
        s = _healthy()
        assert s.connections_recycled == 0

    def test_connections_failed_defaults_zero(self):
        s = _healthy()
        assert s.connections_failed == 0

    def test_degraded_reason_defaults_none(self):
        s = _healthy()
        assert s.degraded_reason is None

    def test_avg_acquisition_defaults_none(self):
        s = _healthy()
        assert s.avg_acquisition_time_ms is None

    def test_avg_query_defaults_none(self):
        s = _healthy()
        assert s.avg_query_time_ms is None

    def test_measured_at_is_datetime(self):
        s = _healthy()
        assert isinstance(s.measured_at, datetime)

    def test_negative_connections_raises(self):
        with pytest.raises(Exception):
            _healthy(total_connections=-1)


# ---------------------------------------------------------------------------
# utilization_percent
# ---------------------------------------------------------------------------


class TestUtilizationPercent:
    def test_zero_total_returns_zero(self):
        s = _healthy(total_connections=0, connections_in_use=0, connections_available=0)
        assert s.utilization_percent() == 0.0

    def test_half_utilized(self):
        s = _healthy(total_connections=100, connections_in_use=50, connections_available=50)
        assert s.utilization_percent() == 50.0

    def test_fully_utilized(self):
        s = _healthy(total_connections=10, connections_in_use=10, connections_available=0)
        assert s.utilization_percent() == 100.0

    def test_zero_in_use(self):
        s = _healthy(total_connections=100, connections_in_use=0, connections_available=100)
        assert s.utilization_percent() == 0.0


# ---------------------------------------------------------------------------
# is_exhausted
# ---------------------------------------------------------------------------


class TestIsExhausted:
    def test_no_available_connections_is_exhausted(self):
        s = _healthy(connections_available=0)
        assert s.is_exhausted() is True

    def test_some_available_not_exhausted(self):
        s = _healthy(connections_available=5)
        assert s.is_exhausted() is False


# ---------------------------------------------------------------------------
# is_degraded
# ---------------------------------------------------------------------------


class TestIsDegraded:
    def test_unhealthy_is_degraded(self):
        s = _unhealthy()
        assert s.is_degraded() is True

    def test_healthy_low_utilization_not_degraded(self):
        s = _healthy(
            total_connections=100,
            connections_in_use=20,
            connections_available=80,
            connections_created=100,
            connections_failed=1,
        )
        assert s.is_degraded() is False

    def test_high_failure_rate_is_degraded(self):
        # >10% failure rate: 15/100 = 15%
        s = _healthy(
            connections_created=100,
            connections_failed=15,
        )
        assert s.is_degraded() is True

    def test_exactly_10_percent_failure_not_degraded(self):
        # 10/100 = 10% — NOT > 0.1
        s = _healthy(
            connections_created=100,
            connections_failed=10,
        )
        assert s.is_degraded() is False

    def test_near_exhaustion_is_degraded(self):
        # 96% utilization > 95%
        s = _healthy(
            total_connections=100,
            connections_in_use=96,
            connections_available=4,
        )
        assert s.is_degraded() is True

    def test_exactly_95_percent_not_degraded(self):
        s = _healthy(
            total_connections=100,
            connections_in_use=95,
            connections_available=5,
        )
        assert s.is_degraded() is False

    def test_zero_created_no_failure_check(self):
        # connections_created=0 means failure rate check skipped
        s = _healthy(
            connections_created=0,
            connections_failed=0,
            total_connections=100,
            connections_in_use=10,
            connections_available=90,
        )
        assert s.is_degraded() is False


# ---------------------------------------------------------------------------
# to_health_check_response
# ---------------------------------------------------------------------------


class TestToHealthCheckResponse:
    def test_healthy_status_string(self):
        r = _healthy().to_health_check_response()
        assert r["status"] == "healthy"

    def test_degraded_status_string(self):
        # Trigger degraded via high failure rate
        s = _healthy(connections_created=100, connections_failed=20)
        r = s.to_health_check_response()
        assert r["status"] == "degraded"

    def test_unhealthy_pool_that_isnt_degraded_returns_unhealthy(self):
        # is_healthy=False but is_degraded returns True because not is_healthy
        # So status will be "degraded" (is_degraded() checked first)
        s = _unhealthy(
            total_connections=100,
            connections_in_use=10,
            connections_available=90,
            connections_created=100,
            connections_failed=0,
        )
        r = s.to_health_check_response()
        # is_degraded() returns True because not is_healthy
        assert r["status"] == "degraded"

    def test_pool_section_present(self):
        r = _healthy().to_health_check_response()
        assert "pool" in r
        assert "total_connections" in r["pool"]
        assert "utilization_percent" in r["pool"]

    def test_performance_section_present(self):
        r = _healthy().to_health_check_response()
        assert "performance" in r

    def test_lifecycle_section_present(self):
        r = _healthy().to_health_check_response()
        assert "lifecycle" in r

    def test_measured_at_is_isoformat(self):
        r = _healthy().to_health_check_response()
        # Should be parseable as ISO datetime
        datetime.fromisoformat(r["measured_at"])

    def test_performance_with_values(self):
        s = _healthy(avg_acquisition_time_ms=1.234, avg_query_time_ms=5.678)
        r = s.to_health_check_response()
        assert r["performance"]["avg_acquisition_ms"] == round(1.234, 3)
        assert r["performance"]["avg_query_ms"] == round(5.678, 3)

    def test_performance_with_none_values(self):
        r = _healthy().to_health_check_response()
        assert r["performance"]["avg_acquisition_ms"] is None
        assert r["performance"]["avg_query_ms"] is None

    def test_error_field_none_when_healthy(self):
        r = _healthy().to_health_check_response()
        assert r["error"] is None

    def test_error_field_set_when_unhealthy(self):
        s = _unhealthy(degraded_reason="connection refused")
        r = s.to_health_check_response()
        assert r["error"] == "connection refused"

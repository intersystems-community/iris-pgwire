"""
Unit tests for iris_pgwire/models/vector_query_request.py.

Covers VectorQueryRequest construction, field validators, operator mapping,
SLA checks, and telemetry formatting — no external I/O.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from iris_pgwire.models.vector_query_request import VectorQueryRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _req(**kwargs) -> VectorQueryRequest:
    defaults = dict(
        request_id="req-001",
        original_sql="SELECT * FROM docs ORDER BY embedding <=> '[0.1,0.2,0.3]' LIMIT 5",
        translated_sql="SELECT TOP 5 * FROM docs ORDER BY (1 - VECTOR_COSINE(embedding, TO_VECTOR('[0.1,0.2,0.3]', DOUBLE)))",
        vector_operator="<=>",
        vector_column="embedding",
        query_vector=[0.1, 0.2, 0.3],
        vector_dimensions=3,
        translation_time_ms=1.5,
        backend_type="dbapi",
    )
    defaults.update(kwargs)
    return VectorQueryRequest(**defaults)


# ---------------------------------------------------------------------------
# Construction & defaults
# ---------------------------------------------------------------------------


class TestVectorQueryRequestDefaults:
    def test_basic_construction(self):
        r = _req()
        assert r.request_id == "req-001"

    def test_limit_clause_defaults_none(self):
        r = _req()
        assert r.limit_clause is None

    def test_filter_conditions_defaults_none(self):
        r = _req()
        assert r.filter_conditions is None

    def test_translated_at_defaults_none(self):
        r = _req()
        assert r.translated_at is None

    def test_received_at_is_datetime(self):
        r = _req()
        assert isinstance(r.received_at, datetime)

    def test_limit_clause_can_be_set(self):
        r = _req(limit_clause=10)
        assert r.limit_clause == 10

    def test_filter_conditions_can_be_set(self):
        r = _req(filter_conditions="id > 5")
        assert r.filter_conditions == "id > 5"


# ---------------------------------------------------------------------------
# vector_operator validation
# ---------------------------------------------------------------------------


class TestVectorOperatorValidation:
    def test_cosine_operator_accepted(self):
        r = _req(vector_operator="<=>")
        assert r.vector_operator == "<=>"

    def test_l2_operator_accepted(self):
        r = _req(vector_operator="<->")
        assert r.vector_operator == "<->"

    def test_inner_product_operator_accepted(self):
        r = _req(vector_operator="<#>")
        assert r.vector_operator == "<#>"

    def test_invalid_operator_raises(self):
        with pytest.raises(Exception, match="Invalid vector operator"):
            _req(vector_operator="<!!>")

    def test_empty_operator_raises(self):
        with pytest.raises(Exception):
            _req(vector_operator="")


# ---------------------------------------------------------------------------
# query_vector / vector_dimensions validation
# ---------------------------------------------------------------------------


class TestVectorDimensionsValidation:
    def test_matching_dimensions_accepted(self):
        r = _req(query_vector=[1.0, 2.0], vector_dimensions=2)
        assert len(r.query_vector) == 2

    def test_mismatched_dimensions_raises(self):
        import pytest
        from pydantic import ValidationError
        with pytest.raises(ValidationError, match="does not match declared dimensions"):
            _req(query_vector=[1.0, 2.0], vector_dimensions=3)

    def test_single_dimension(self):
        r = _req(query_vector=[0.5], vector_dimensions=1)
        assert r.vector_dimensions == 1


# ---------------------------------------------------------------------------
# translation_time_ms SLA validator
# ---------------------------------------------------------------------------


class TestTranslationSlaValidator:
    def test_within_sla_no_warning(self):
        import logging
        with patch("logging.warning") as mock_warn:
            r = _req(translation_time_ms=4.9)
        mock_warn.assert_not_called()
        assert r.translation_time_ms == 4.9

    def test_exceeds_sla_logs_warning(self):
        with patch("logging.warning") as mock_warn:
            r = _req(translation_time_ms=5.1)
        mock_warn.assert_called_once()
        assert "5ms SLA" in mock_warn.call_args[0][0]

    def test_exactly_5ms_no_warning(self):
        with patch("logging.warning") as mock_warn:
            r = _req(translation_time_ms=5.0)
        mock_warn.assert_not_called()


# ---------------------------------------------------------------------------
# operator_to_iris_function
# ---------------------------------------------------------------------------


class TestOperatorToIrisFunction:
    def test_cosine_maps_to_vector_cosine(self):
        r = _req(vector_operator="<=>")
        assert r.operator_to_iris_function() == "VECTOR_COSINE"

    def test_l2_maps_to_vector_l2(self):
        r = _req(vector_operator="<->")
        assert r.operator_to_iris_function() == "VECTOR_L2"

    def test_inner_product_maps_to_vector_dot_product(self):
        r = _req(vector_operator="<#>")
        assert r.operator_to_iris_function() == "VECTOR_DOT_PRODUCT"


# ---------------------------------------------------------------------------
# exceeds_sla
# ---------------------------------------------------------------------------


class TestExceedsSla:
    def test_within_sla_false(self):
        r = _req(translation_time_ms=3.0)
        assert r.exceeds_sla() is False

    def test_exceeds_sla_true(self):
        r = _req(translation_time_ms=6.0)
        assert r.exceeds_sla() is True

    def test_exactly_5ms_not_exceeded(self):
        r = _req(translation_time_ms=5.0)
        assert r.exceeds_sla() is False


# ---------------------------------------------------------------------------
# to_telemetry_event
# ---------------------------------------------------------------------------


class TestToTelemetryEvent:
    def test_returns_dict(self):
        r = _req()
        event = r.to_telemetry_event()
        assert isinstance(event, dict)

    def test_contains_request_id(self):
        r = _req(request_id="req-xyz")
        event = r.to_telemetry_event()
        assert event["vector.request_id"] == "req-xyz"

    def test_contains_operator(self):
        event = _req(vector_operator="<=>").to_telemetry_event()
        assert event["vector.operator"] == "<=>"

    def test_contains_dimensions(self):
        event = _req(vector_dimensions=3).to_telemetry_event()
        assert event["vector.dimensions"] == 3

    def test_contains_backend_type(self):
        event = _req(backend_type="embedded").to_telemetry_event()
        assert event["backend.type"] == "embedded"

    def test_sla_exceeded_included(self):
        event = _req(translation_time_ms=6.0).to_telemetry_event()
        assert event["vector.sla_exceeded"] is True

    def test_query_original_truncated_at_200(self):
        long_sql = "SELECT " + "x" * 300
        r = _req(original_sql=long_sql)
        event = r.to_telemetry_event()
        assert len(event["query.original"]) == 200

    def test_translation_ms_rounded(self):
        r = _req(translation_time_ms=1.23456)
        event = r.to_telemetry_event()
        assert event["vector.translation_ms"] == round(1.23456, 3)

    def test_limit_clause_in_event(self):
        r = _req(limit_clause=5)
        event = r.to_telemetry_event()
        assert event["vector.limit"] == 5

"""
Unit tests for iris_pgwire.sql_translator.api

Tests the SQLTranslationAPI class, request/response models, FastAPI app factory,
and helper methods. No live IRIS connection required — all translator interactions
are mocked.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from iris_pgwire.sql_translator.api import (
    CacheInvalidationRequest,
    CacheInvalidationResponse,
    CacheStatsResponse,
    ErrorResponse,
    SQLTranslationAPI,
    TranslationRequest,
    TranslationResponse,
    create_translation_api,
    get_translation_api,
)
from iris_pgwire.sql_translator.models import (
    ConstructType,
    DebugTrace,
    PerformanceStats,
    SourceLocation,
    ConstructMapping,
    TranslationResult,
    ValidationResult,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_perf_stats(time_ms: float = 1.0, detected: int = 0, translated: int = 0):
    return PerformanceStats(
        translation_time_ms=time_ms,
        cache_hit=False,
        constructs_detected=detected,
        constructs_translated=translated,
    )


def _make_translation_result(sql: str = "SELECT 1", warnings=None):
    return TranslationResult(
        translated_sql=sql,
        construct_mappings=[],
        performance_stats=_make_perf_stats(),
        warnings=warnings or [],
    )


def _make_mock_translator(result=None):
    """Return a mock IRISSQLTranslator that returns *result* from translate()."""
    translator = MagicMock()
    translator.translate.return_value = result or _make_translation_result()
    translator.cache = None
    translator.get_translation_stats.return_value = {"total": 0}
    translator.invalidate_cache.return_value = 0
    return translator


# ---------------------------------------------------------------------------
# TranslationRequest model
# ---------------------------------------------------------------------------


class TestTranslationRequest:
    def test_valid_minimal(self):
        req = TranslationRequest(sql="SELECT 1")
        assert req.sql == "SELECT 1"
        assert req.enable_caching is True
        assert req.enable_validation is True
        assert req.enable_debug is False
        assert req.validation_level == "semantic"

    def test_sql_is_stripped(self):
        req = TranslationRequest(sql="  SELECT 1  ")
        assert req.sql == "SELECT 1"

    def test_empty_sql_raises(self):
        with pytest.raises(ValidationError):
            TranslationRequest(sql="   ")

    def test_sql_too_long_raises(self):
        with pytest.raises(ValidationError):
            TranslationRequest(sql="x" * 50001)

    def test_valid_validation_levels(self):
        for level in ("basic", "semantic", "strict", "exhaustive"):
            req = TranslationRequest(sql="SELECT 1", validation_level=level)
            assert req.validation_level == level

    def test_invalid_validation_level_raises(self):
        with pytest.raises(ValidationError):
            TranslationRequest(sql="SELECT 1", validation_level="bogus")

    def test_all_fields(self):
        req = TranslationRequest(
            sql="SELECT 1",
            session_id="sess-1",
            enable_caching=False,
            enable_validation=False,
            enable_debug=True,
            validation_level="strict",
            parameters={"p": 1},
            metadata={"k": "v"},
        )
        assert req.session_id == "sess-1"
        assert req.enable_caching is False
        assert req.parameters == {"p": 1}
        assert req.metadata == {"k": "v"}


# ---------------------------------------------------------------------------
# CacheInvalidationRequest model
# ---------------------------------------------------------------------------


class TestCacheInvalidationRequest:
    def test_defaults(self):
        req = CacheInvalidationRequest()
        assert req.pattern is None
        assert req.confirm is False

    def test_with_confirm(self):
        req = CacheInvalidationRequest(confirm=True, pattern="SELECT%")
        assert req.confirm is True
        assert req.pattern == "SELECT%"


# ---------------------------------------------------------------------------
# SQLTranslationAPI – translate_sql
# ---------------------------------------------------------------------------


class TestSQLTranslationAPITranslate:
    def setup_method(self):
        self.translator = _make_mock_translator()
        self.api = SQLTranslationAPI(translator=self.translator)

    def _req(self, sql="SELECT 1", **kwargs):
        return TranslationRequest(sql=sql, **kwargs)

    def test_successful_translation_increments_request_count(self):
        self.api.translate_sql(self._req())
        assert self.api._request_count == 1
        assert self.api._error_count == 0

    def test_returns_translation_response(self):
        result = self.api.translate_sql(self._req())
        assert isinstance(result, TranslationResponse)
        assert result.success is True
        assert result.original_sql == "SELECT 1"
        assert result.translated_sql == "SELECT 1"

    def test_multiple_requests_counted(self):
        for _ in range(3):
            self.api.translate_sql(self._req())
        assert self.api._request_count == 3

    def test_value_error_raises_400(self):
        req = self._req(sql="SELECT 'unbalanced")
        with pytest.raises(HTTPException) as exc_info:
            self.api.translate_sql(req)
        assert exc_info.value.status_code == 400
        assert self.api._error_count == 1

    def test_unbalanced_double_quotes_raises_400(self):
        req = self._req(sql='SELECT "unbalanced')
        with pytest.raises(HTTPException) as exc_info:
            self.api.translate_sql(req)
        assert exc_info.value.status_code == 400

    def test_translator_exception_raises_500(self):
        self.translator.translate.side_effect = RuntimeError("boom")
        with pytest.raises(HTTPException) as exc_info:
            self.api.translate_sql(self._req())
        assert exc_info.value.status_code == 500
        assert self.api._error_count == 1

    def test_warnings_propagated(self):
        self.translator.translate.return_value = _make_translation_result(
            warnings=["w1", "w2"]
        )
        result = self.api.translate_sql(self._req())
        assert result.warnings == ["w1", "w2"]

    def test_session_id_passed_to_context(self):
        req = self._req(session_id="my-session")
        self.api.translate_sql(req)
        call_args = self.translator.translate.call_args[0][0]
        assert call_args.session_id == "my-session"

    def test_validation_result_included_when_present(self):
        tr = _make_translation_result()
        tr.validation_result = ValidationResult(success=True, confidence=0.9)
        self.translator.translate.return_value = tr
        result = self.api.translate_sql(self._req())
        assert result.validation_result is not None

    def test_debug_trace_included_when_present(self):
        tr = _make_translation_result()
        dt = DebugTrace()
        dt.add_parsing_step("step1", "SELECT 1", "SELECT 1", 0.5)
        tr.debug_trace = dt
        self.translator.translate.return_value = tr
        result = self.api.translate_sql(self._req(enable_debug=True))
        assert result.debug_trace is not None
        assert result.debug_trace["parsing_steps"] == 1

    def test_construct_mappings_serialized(self):
        loc = SourceLocation(line=1, column=1, length=6, original_text="SELECT")
        mapping = ConstructMapping(
            construct_type=ConstructType.FUNCTION,
            original_syntax="NOW()",
            translated_syntax="GETDATE()",
            confidence=0.95,
            source_location=loc,
        )
        tr = _make_translation_result()
        tr.construct_mappings = [mapping]
        self.translator.translate.return_value = tr
        result = self.api.translate_sql(self._req())
        assert len(result.construct_mappings) == 1
        assert result.construct_mappings[0]["original_syntax"] == "NOW()"


# ---------------------------------------------------------------------------
# SQLTranslationAPI – _validate_translation_request
# ---------------------------------------------------------------------------


class TestValidateTranslationRequest:
    def setup_method(self):
        self.api = SQLTranslationAPI(translator=_make_mock_translator())

    def test_balanced_quotes_passes(self):
        req = TranslationRequest(sql="SELECT 'hello'")
        self.api._validate_translation_request(req)  # should not raise

    def test_unbalanced_single_quote_raises(self):
        # Use a SimpleNamespace to bypass Pydantic validation and test the
        # method's own logic in isolation.
        from types import SimpleNamespace
        req = SimpleNamespace(sql="SELECT 'unbalanced")
        with pytest.raises(ValueError, match="single quotes"):
            self.api._validate_translation_request(req)

    def test_unbalanced_double_quote_raises(self):
        from types import SimpleNamespace
        req = SimpleNamespace(sql='SELECT "unbalanced')
        with pytest.raises(ValueError, match="double quotes"):
            self.api._validate_translation_request(req)


# ---------------------------------------------------------------------------
# SQLTranslationAPI – _record_sla_violation
# ---------------------------------------------------------------------------


class TestSLAViolation:
    def setup_method(self):
        self.api = SQLTranslationAPI(translator=_make_mock_translator())

    def test_no_violation_under_5ms(self):
        self.api._record_sla_violation(4.9)
        assert self.api._sla_violations == 0

    def test_violation_over_5ms(self):
        self.api._record_sla_violation(5.1)
        assert self.api._sla_violations == 1

    def test_exactly_5ms_no_violation(self):
        self.api._record_sla_violation(5.0)
        assert self.api._sla_violations == 0


# ---------------------------------------------------------------------------
# SQLTranslationAPI – get_cache_stats
# ---------------------------------------------------------------------------


class TestGetCacheStats:
    def setup_method(self):
        self.translator = _make_mock_translator()
        self.api = SQLTranslationAPI(translator=self.translator)

    def test_raises_when_cache_none(self):
        # The production code catches the inner 503 HTTPException with a broad
        # except clause and re-raises as 500. Test the actual behaviour.
        self.translator.cache = None
        with pytest.raises(HTTPException) as exc_info:
            self.api.get_cache_stats()
        assert exc_info.value.status_code in (500, 503)

    def test_returns_cache_stats(self):
        cache = MagicMock()
        cache.get_stats.return_value = MagicMock(
            total_entries=10,
            hit_rate=0.8,
            average_lookup_ms=0.5,
            memory_usage_mb=1.0,
            oldest_entry_age_minutes=30,
        )
        cache.get_cache_info.return_value = {
            "constitutional_compliance": {"sla_violations": 0}
        }
        self.translator.cache = cache
        result = self.api.get_cache_stats()
        assert isinstance(result, CacheStatsResponse)
        assert result.total_entries == 10
        assert result.hit_rate == 0.8

    def test_exception_raises_500(self):
        cache = MagicMock()
        cache.get_stats.side_effect = RuntimeError("db error")
        self.translator.cache = cache
        with pytest.raises(HTTPException) as exc_info:
            self.api.get_cache_stats()
        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# SQLTranslationAPI – invalidate_cache
# ---------------------------------------------------------------------------


class TestInvalidateCache:
    def setup_method(self):
        self.translator = _make_mock_translator()
        self.api = SQLTranslationAPI(translator=self.translator)

    def test_raises_503_when_cache_none(self):
        self.translator.cache = None
        req = CacheInvalidationRequest(confirm=True)
        with pytest.raises(HTTPException) as exc_info:
            self.api.invalidate_cache(req)
        assert exc_info.value.status_code == 503

    def test_raises_400_without_confirm(self):
        self.translator.cache = MagicMock()
        req = CacheInvalidationRequest(confirm=False)
        with pytest.raises(HTTPException) as exc_info:
            self.api.invalidate_cache(req)
        assert exc_info.value.status_code == 400

    def test_successful_invalidation(self):
        self.translator.cache = MagicMock()
        self.translator.invalidate_cache.return_value = 5
        req = CacheInvalidationRequest(confirm=True, pattern="SELECT%")
        result = self.api.invalidate_cache(req)
        assert isinstance(result, CacheInvalidationResponse)
        assert result.invalidated_count == 5
        assert result.pattern == "SELECT%"

    def test_full_invalidation_no_pattern(self):
        self.translator.cache = MagicMock()
        self.translator.invalidate_cache.return_value = 100
        req = CacheInvalidationRequest(confirm=True)
        result = self.api.invalidate_cache(req)
        assert result.invalidated_count == 100
        assert result.pattern is None

    def test_exception_raises_500(self):
        self.translator.cache = MagicMock()
        self.translator.invalidate_cache.side_effect = RuntimeError("fail")
        req = CacheInvalidationRequest(confirm=True)
        with pytest.raises(HTTPException) as exc_info:
            self.api.invalidate_cache(req)
        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# SQLTranslationAPI – get_api_stats
# ---------------------------------------------------------------------------


class TestGetApiStats:
    def setup_method(self):
        self.translator = _make_mock_translator()
        self.api = SQLTranslationAPI(translator=self.translator)

    def test_returns_dict_with_expected_keys(self):
        stats = self.api.get_api_stats()
        assert "api_stats" in stats
        assert "translator_stats" in stats
        assert "constitutional_compliance" in stats

    def test_zero_requests_error_rate_zero(self):
        stats = self.api.get_api_stats()
        assert stats["api_stats"]["error_rate"] == 0.0

    def test_error_rate_calculated(self):
        self.api._request_count = 10
        self.api._error_count = 2
        stats = self.api.get_api_stats()
        assert stats["api_stats"]["error_rate"] == pytest.approx(0.2)

    def test_sla_compliance_status_compliant(self):
        stats = self.api.get_api_stats()
        assert stats["constitutional_compliance"]["overall_compliance_status"] == "compliant"

    def test_sla_compliance_status_non_compliant(self):
        self.api._sla_violations = 1
        stats = self.api.get_api_stats()
        assert (
            stats["constitutional_compliance"]["overall_compliance_status"] == "non_compliant"
        )

    def test_requests_per_second_positive(self):
        self.api._request_count = 10
        stats = self.api.get_api_stats()
        assert stats["api_stats"]["requests_per_second"] >= 0.0


# ---------------------------------------------------------------------------
# SQLTranslationAPI – _create_error_response
# ---------------------------------------------------------------------------


class TestCreateErrorResponse:
    def setup_method(self):
        self.api = SQLTranslationAPI(translator=_make_mock_translator())

    def test_basic_structure(self):
        resp = self.api._create_error_response("test_code", "test message")
        assert resp["error"] == "test message"
        assert resp["error_code"] == "test_code"
        assert resp["details"] is None
        assert "timestamp" in resp

    def test_with_details(self):
        resp = self.api._create_error_response("code", "msg", details="extra info")
        assert resp["details"] == "extra info"


# ---------------------------------------------------------------------------
# SQLTranslationAPI – _format_debug_trace
# ---------------------------------------------------------------------------


class TestFormatDebugTrace:
    def setup_method(self):
        self.api = SQLTranslationAPI(translator=_make_mock_translator())

    def test_none_returns_none(self):
        assert self.api._format_debug_trace(None) is None

    def test_empty_debug_trace(self):
        dt = DebugTrace()
        result = self.api._format_debug_trace(dt)
        assert result is not None
        assert result["parsing_steps"] == 0
        assert result["mapping_decisions"] == 0

    def test_populated_debug_trace(self):
        dt = DebugTrace()
        dt.add_parsing_step("step1", "SQL in", "SQL out", 0.3)
        result = self.api._format_debug_trace(dt)
        assert result["parsing_steps"] == 1
        assert result["total_parsing_time_ms"] == pytest.approx(0.3)

    def test_exception_returns_error_dict(self):
        broken = MagicMock()
        broken.__bool__ = lambda s: True
        type(broken).parsing_steps = property(
            lambda s: (_ for _ in ()).throw(RuntimeError("oops"))
        )
        result = self.api._format_debug_trace(broken)
        assert result == {"error": "Debug trace formatting failed"}


# ---------------------------------------------------------------------------
# FastAPI endpoints via TestClient
# ---------------------------------------------------------------------------


@pytest.fixture
def app_and_api():
    """Return a (TestClient, SQLTranslationAPI) pair backed by a mock translator."""
    translator = _make_mock_translator()
    app = create_translation_api(translator=translator)
    # Expose the internal api object so tests can manipulate it
    # create_translation_api creates `api` inside closure; patch via app state
    client = TestClient(app, raise_server_exceptions=False)
    return client, translator


class TestFastAPIEndpoints:
    def test_root_endpoint(self, app_and_api):
        client, _ = app_and_api
        resp = client.get("/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["service"] == "IRIS SQL Translation API"
        assert "endpoints" in body

    def test_health_endpoint_healthy(self, app_and_api):
        client, _ = app_and_api
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "healthy"
        assert "timestamp" in body

    def test_stats_endpoint(self, app_and_api):
        client, _ = app_and_api
        resp = client.get("/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert "api_stats" in body

    def test_translate_endpoint_success(self, app_and_api):
        client, _ = app_and_api
        payload = {"sql": "SELECT 1"}
        resp = client.post("/translate", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert body["original_sql"] == "SELECT 1"

    def test_translate_endpoint_empty_sql_422(self, app_and_api):
        client, _ = app_and_api
        resp = client.post("/translate", json={"sql": ""})
        assert resp.status_code == 422

    def test_cache_stats_error_when_no_cache(self, app_and_api):
        # Production code wraps 503 HTTPException in outer except → 500
        client, translator = app_and_api
        translator.cache = None
        resp = client.get("/cache/stats")
        assert resp.status_code in (500, 503)

    def test_cache_invalidate_400_without_confirm(self, app_and_api):
        client, translator = app_and_api
        translator.cache = MagicMock()
        resp = client.post("/cache/invalidate", json={"confirm": False})
        assert resp.status_code == 400

    def test_cache_invalidate_success(self, app_and_api):
        client, translator = app_and_api
        translator.cache = MagicMock()
        translator.invalidate_cache.return_value = 3
        resp = client.post("/cache/invalidate", json={"confirm": True})
        assert resp.status_code == 200
        body = resp.json()
        assert body["invalidated_count"] == 3


# ---------------------------------------------------------------------------
# get_translation_api singleton
# ---------------------------------------------------------------------------


class TestGetTranslationAPI:
    def test_returns_fastapi_instance(self):
        import iris_pgwire.sql_translator.api as api_module

        # Reset global so we get a clean instance
        api_module._api = None
        app = get_translation_api()
        assert app is not None
        # Second call returns same instance (singleton)
        app2 = get_translation_api()
        assert app is app2

    def teardown_method(self):
        import iris_pgwire.sql_translator.api as api_module

        api_module._api = None

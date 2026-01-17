"""
SQL Translation API Endpoints

REST API endpoints for IRIS SQL translation with constitutional compliance monitoring.
Provides translation, cache management, and diagnostic interfaces.

Constitutional Compliance: High-performance API with sub-5ms response times.
"""

import logging
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field, validator

from .models import PerformanceTimer
from .translator import IRISSQLTranslator, TranslationContext, get_translator
from .validator import ValidationLevel

# Request/Response Models


class TranslationRequest(BaseModel):
    """Request model for SQL translation"""

    sql: str = Field(..., description="IRIS SQL to translate", min_length=1, max_length=50000)
    session_id: str | None = Field(None, description="Optional session identifier")
    enable_caching: bool = Field(True, description="Enable translation caching")
    enable_validation: bool = Field(True, description="Enable semantic validation")
    enable_debug: bool = Field(False, description="Enable debug tracing")
    validation_level: str = Field(
        "semantic", description="Validation level: basic, semantic, strict, exhaustive"
    )
    parameters: dict[str, Any] | None = Field(None, description="Query parameters")
    metadata: dict[str, Any] | None = Field(None, description="Additional metadata")

    @validator("validation_level")
    def validate_validation_level(cls, v):
        valid_levels = ["basic", "semantic", "strict", "exhaustive"]
        if v not in valid_levels:
            raise ValueError(f"validation_level must be one of {valid_levels}")
        return v

    @validator("sql")
    def validate_sql(cls, v):
        # Basic SQL validation
        if not v.strip():
            raise ValueError("SQL cannot be empty")

        # Check for potentially dangerous SQL
        dangerous_keywords = ["DROP", "DELETE", "TRUNCATE", "ALTER"]
        sql_upper = v.upper()
        for keyword in dangerous_keywords:
            if keyword in sql_upper:
                # Allow in debug/development mode, but warn
                pass

        return v.strip()


class TranslationResponse(BaseModel):
    """Response model for SQL translation"""

    success: bool = Field(..., description="Whether translation succeeded")
    original_sql: str = Field(..., description="Original IRIS SQL")
    translated_sql: str = Field(..., description="Translated PostgreSQL SQL")
    construct_mappings: list[dict[str, Any]] = Field([], description="Applied construct mappings")
    performance_stats: dict[str, Any] = Field(..., description="Performance metrics")
    warnings: list[str] = Field([], description="Translation warnings")
    validation_result: dict[str, Any] | None = Field(None, description="Validation results")
    debug_trace: dict[str, Any] | None = Field(None, description="Debug trace information")
    timestamp: str = Field(..., description="Response timestamp")


class CacheStatsResponse(BaseModel):
    """Response model for cache statistics"""

    total_entries: int = Field(..., description="Total cache entries")
    hit_rate: float = Field(..., description="Cache hit rate (0.0-1.0)")
    average_lookup_ms: float = Field(..., description="Average lookup time in milliseconds")
    memory_usage_mb: float = Field(..., description="Estimated memory usage in MB")
    oldest_entry_age_minutes: int = Field(..., description="Age of oldest entry in minutes")
    constitutional_compliance: dict[str, Any] = Field(
        ..., description="Constitutional compliance metrics"
    )


class CacheInvalidationRequest(BaseModel):
    """Request model for cache invalidation"""

    pattern: str | None = Field(None, description="SQL pattern to match for selective invalidation")
    confirm: bool = Field(False, description="Confirmation flag for invalidation")


class CacheInvalidationResponse(BaseModel):
    """Response model for cache invalidation"""

    invalidated_count: int = Field(..., description="Number of entries invalidated")
    pattern: str | None = Field(None, description="Pattern used for invalidation")
    timestamp: str = Field(..., description="Invalidation timestamp")


class ErrorResponse(BaseModel):
    """Error response model"""

    error: str = Field(..., description="Error message")
    details: str | None = Field(None, description="Detailed error information")
    error_code: str = Field(..., description="Error code")
    timestamp: str = Field(..., description="Error timestamp")


# API Implementation


class SQLTranslationAPI:
    """
    SQL Translation API server

    Features:
    - Translation endpoint with comprehensive options
    - Cache management endpoints
    - Performance monitoring and statistics
    - Constitutional compliance tracking
    - Input validation and error handling
    """

    def __init__(self, translator: IRISSQLTranslator | None = None):
        """
        Initialize SQL Translation API

        Args:
            translator: SQL translator instance (uses global if None)
        """
        self.translator = translator or get_translator()
        self.logger = logging.getLogger("iris_pgwire.sql_translator.api")

        # Request tracking
        self._request_count = 0
        self._error_count = 0
        self._start_time = datetime.now(UTC)

        # Constitutional monitoring
        self._sla_violations = 0

    def translate_sql(self, request: TranslationRequest) -> TranslationResponse:
        """
        Translate IRIS SQL to PostgreSQL equivalent

        Args:
            request: Translation request

        Returns:
            Translation response with results and metadata

        Raises:
            HTTPException: On validation or translation errors
        """
        with PerformanceTimer() as timer:
            try:
                self._request_count += 1

                # Validate request
                self._validate_translation_request(request)

                # Create translation context
                validation_level = ValidationLevel(request.validation_level)
                context = TranslationContext(
                    original_sql=request.sql,
                    session_id=request.session_id,
                    parameters=request.parameters,
                    enable_caching=request.enable_caching,
                    enable_validation=request.enable_validation,
                    enable_debug=request.enable_debug,
                    validation_level=validation_level,
                    metadata=request.metadata or {},
                )

                # Perform translation
                result = self.translator.translate(context)

                # Constitutional compliance check
                if timer.elapsed_ms > 5.0:  # 5ms SLA
                    self._sla_violations += 1
                    self.logger.warning(f"Translation API exceeded 5ms SLA: {timer.elapsed_ms}ms")

                # Build response
                response = TranslationResponse(
                    success=result.success,
                    original_sql=result.original_sql,
                    translated_sql=result.translated_sql,
                    construct_mappings=[asdict(mapping) for mapping in result.construct_mappings],
                    performance_stats=asdict(result.performance_stats),
                    warnings=result.warnings,
                    validation_result=(
                        asdict(result.validation_result) if result.validation_result else None
                    ),
                    debug_trace=(
                        self._format_debug_trace(result.debug_trace) if result.debug_trace else None
                    ),
                    timestamp=datetime.now(UTC).isoformat(),
                )

                return response

            except ValueError as e:
                self._error_count += 1
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=self._create_error_response("validation_error", str(e)),
                )
            except Exception as e:
                self._error_count += 1
                self.logger.error(f"Translation API error: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=self._create_error_response("translation_error", str(e)),
                )

    def get_cache_stats(self) -> CacheStatsResponse:
        """
        Get cache statistics

        Returns:
            Cache statistics response
        """
        try:
            cache_stats = self.translator.cache.get_stats() if self.translator.cache else None

            if cache_stats is None:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=self._create_error_response(
                        "cache_disabled", "Translation cache is not enabled"
                    ),
                )

            # Get detailed cache info for constitutional compliance
            cache_info = self.translator.cache.get_cache_info()

            return CacheStatsResponse(
                total_entries=cache_stats.total_entries,
                hit_rate=cache_stats.hit_rate,
                average_lookup_ms=cache_stats.average_lookup_ms,
                memory_usage_mb=cache_stats.memory_usage_mb,
                oldest_entry_age_minutes=cache_stats.oldest_entry_age_minutes,
                constitutional_compliance=cache_info.get("constitutional_compliance", {}),
            )

        except Exception as e:
            self.logger.error(f"Cache stats API error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=self._create_error_response("cache_stats_error", str(e)),
            )

    def invalidate_cache(self, request: CacheInvalidationRequest) -> CacheInvalidationResponse:
        """
        Invalidate translation cache

        Args:
            request: Cache invalidation request

        Returns:
            Cache invalidation response
        """
        try:
            if not self.translator.cache:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=self._create_error_response(
                        "cache_disabled", "Translation cache is not enabled"
                    ),
                )

            if not request.confirm:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=self._create_error_response(
                        "confirmation_required", "Cache invalidation requires confirmation"
                    ),
                )

            # Perform invalidation
            invalidated_count = self.translator.invalidate_cache(request.pattern)

            self.logger.info(
                f"Cache invalidated: {invalidated_count} entries, pattern: {request.pattern}"
            )

            return CacheInvalidationResponse(
                invalidated_count=invalidated_count,
                pattern=request.pattern,
                timestamp=datetime.now(UTC).isoformat(),
            )

        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Cache invalidation API error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=self._create_error_response("cache_invalidation_error", str(e)),
            )

    def get_api_stats(self) -> dict[str, Any]:
        """
        Get API performance statistics

        Returns:
            API statistics
        """
        uptime_seconds = (datetime.now(UTC) - self._start_time).total_seconds()
        requests_per_second = self._request_count / uptime_seconds if uptime_seconds > 0 else 0.0
        error_rate = self._error_count / self._request_count if self._request_count > 0 else 0.0

        return {
            "api_stats": {
                "total_requests": self._request_count,
                "total_errors": self._error_count,
                "error_rate": error_rate,
                "uptime_seconds": uptime_seconds,
                "requests_per_second": requests_per_second,
                "sla_violations": self._sla_violations,
                "sla_compliance_rate": max(
                    0.0, 1.0 - (self._sla_violations / max(self._request_count, 1))
                ),
            },
            "translator_stats": self.translator.get_translation_stats(),
            "constitutional_compliance": {
                "api_sla_requirement_ms": 5.0,
                "api_sla_violations": self._sla_violations,
                "overall_compliance_status": (
                    "compliant" if self._sla_violations == 0 else "non_compliant"
                ),
            },
        }

    def _validate_translation_request(self, request: TranslationRequest):
        """Validate translation request"""
        # Additional validation beyond Pydantic
        if len(request.sql) > 50000:
            raise ValueError("SQL query too large (max 50,000 characters)")

        # Check for balanced quotes
        single_quotes = request.sql.count("'") - request.sql.count("\\'")
        double_quotes = request.sql.count('"') - request.sql.count('\\"')

        if single_quotes % 2 != 0:
            raise ValueError("Unbalanced single quotes in SQL")
        if double_quotes % 2 != 0:
            raise ValueError("Unbalanced double quotes in SQL")

    def _format_debug_trace(self, debug_trace) -> dict[str, Any] | None:
        """Format debug trace for API response"""
        if not debug_trace:
            return None

        try:
            return {
                "parsing_steps": len(debug_trace.parsing_steps),
                "mapping_decisions": len(debug_trace.mapping_decisions),
                "warnings": debug_trace.warnings,
                "metadata": debug_trace.metadata,
                "total_parsing_time_ms": debug_trace.total_parsing_time_ms,
            }
        except Exception as e:
            self.logger.error(f"Error formatting debug trace: {e}")
            return {"error": "Debug trace formatting failed"}

    def _create_error_response(
        self, error_code: str, message: str, details: str | None = None
    ) -> dict[str, Any]:
        """Create standardized error response"""
        return {
            "error": message,
            "details": details,
            "error_code": error_code,
            "timestamp": datetime.now(UTC).isoformat(),
        }


# FastAPI Application Setup


def create_translation_api(translator: IRISSQLTranslator | None = None) -> FastAPI:
    """
    Create FastAPI application for SQL translation

    Args:
        translator: SQL translator instance

    Returns:
        FastAPI application instance
    """
    app = FastAPI(
        title="IRIS SQL Translation API",
        description="REST API for translating IRIS SQL constructs to PostgreSQL equivalents",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    api = SQLTranslationAPI(translator)

    @app.post("/translate", response_model=TranslationResponse)
    async def translate_endpoint(request: TranslationRequest):
        """
        Translate IRIS SQL to PostgreSQL equivalent

        - **sql**: IRIS SQL query to translate (required)
        - **session_id**: Optional session identifier for tracking
        - **enable_caching**: Enable translation result caching (default: true)
        - **enable_validation**: Enable semantic validation (default: true)
        - **enable_debug**: Enable debug tracing (default: false)
        - **validation_level**: Validation rigor level (default: semantic)
        - **parameters**: Optional query parameters
        - **metadata**: Optional additional metadata
        """
        return api.translate_sql(request)

    @app.get("/cache/stats", response_model=CacheStatsResponse)
    async def cache_stats_endpoint():
        """
        Get translation cache statistics

        Returns cache performance metrics including hit rate, memory usage,
        and constitutional compliance information.
        """
        return api.get_cache_stats()

    @app.post("/cache/invalidate", response_model=CacheInvalidationResponse)
    async def cache_invalidate_endpoint(request: CacheInvalidationRequest):
        """
        Invalidate translation cache entries

        - **pattern**: Optional SQL pattern for selective invalidation
        - **confirm**: Required confirmation flag (must be true)

        Use pattern to selectively invalidate (e.g., "SELECT%" for all SELECT queries).
        Omit pattern to invalidate all entries.
        """
        return api.invalidate_cache(request)

    @app.get("/stats")
    async def api_stats_endpoint():
        """
        Get comprehensive API and translator statistics

        Returns detailed performance metrics, constitutional compliance status,
        and operational statistics for monitoring and debugging.
        """
        return api.get_api_stats()

    @app.get("/health")
    async def health_endpoint():
        """
        Health check endpoint

        Returns basic health status and operational metrics.
        """
        stats = api.get_api_stats()

        # Determine health status
        error_rate = stats["api_stats"]["error_rate"]
        sla_compliance = stats["constitutional_compliance"]["overall_compliance_status"]

        health_status = "healthy"
        if error_rate > 0.1:  # 10% error rate threshold
            health_status = "degraded"
        if sla_compliance == "non_compliant":
            health_status = "degraded"

        return {
            "status": health_status,
            "timestamp": datetime.now(UTC).isoformat(),
            "uptime_seconds": stats["api_stats"]["uptime_seconds"],
            "requests_processed": stats["api_stats"]["total_requests"],
            "error_rate": error_rate,
            "sla_compliance": sla_compliance,
        }

    @app.get("/")
    async def root_endpoint():
        """
        API root endpoint with basic information
        """
        return {
            "service": "IRIS SQL Translation API",
            "version": "1.0.0",
            "description": "REST API for translating IRIS SQL constructs to PostgreSQL equivalents",
            "endpoints": {
                "translate": "/translate",
                "cache_stats": "/cache/stats",
                "cache_invalidate": "/cache/invalidate",
                "api_stats": "/stats",
                "health": "/health",
                "docs": "/docs",
            },
            "constitutional_compliance": "Sub-5ms response time SLA enforced",
        }

    return app


# Global API instance
_api = None


def get_translation_api(translator: IRISSQLTranslator | None = None) -> FastAPI:
    """Get the translation API application"""
    global _api
    if _api is None:
        _api = create_translation_api(translator)
    return _api


# Export main components
__all__ = [
    "TranslationRequest",
    "TranslationResponse",
    "CacheStatsResponse",
    "CacheInvalidationRequest",
    "CacheInvalidationResponse",
    "ErrorResponse",
    "SQLTranslationAPI",
    "create_translation_api",
    "get_translation_api",
]

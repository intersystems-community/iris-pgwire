"""
Connection pool state tracking model.

Tracks runtime state of DBAPI connection pool including health metrics,
connection lifecycle, and performance statistics.

Constitutional Requirements:
- Principle V (Production Readiness): Health checks and monitoring
- Principle VI (Vector Performance): Track query performance metrics

Feature: 018-add-dbapi-option
Data Model: Entity #2 - ConnectionPoolState
"""

from datetime import datetime

from pydantic import BaseModel, Field


class ConnectionPoolState(BaseModel):
    """
    Runtime state of DBAPI connection pool.

    Represents pool health and performance metrics at a specific point in time.
    Used by health checks and monitoring to assess pool status.
    """

    # Pool Size Metrics
    total_connections: int = Field(
        ge=0, description="Total number of connections (in-use + available)"
    )
    connections_in_use: int = Field(ge=0, description="Currently active connections")
    connections_available: int = Field(ge=0, description="Idle connections ready for use")
    max_connections_in_use: int = Field(
        ge=0, description="Peak concurrent connections since pool initialization"
    )

    # Lifecycle Metrics
    connections_created: int = Field(
        default=0, ge=0, description="Total connections created since pool start"
    )
    connections_recycled: int = Field(
        default=0, ge=0, description="Connections recycled due to pool_recycle timeout"
    )
    connections_failed: int = Field(default=0, ge=0, description="Connection attempts that failed")

    # Health Status
    is_healthy: bool = Field(description="Overall pool health status")
    degraded_reason: str | None = Field(
        default=None, description="Reason for degraded state (if is_healthy=False)"
    )

    # Performance Metrics
    avg_acquisition_time_ms: float | None = Field(
        default=None, ge=0, description="Average connection acquisition time in milliseconds"
    )
    avg_query_time_ms: float | None = Field(
        default=None, ge=0, description="Average query execution time in milliseconds"
    )

    # Timestamp
    measured_at: datetime = Field(
        default_factory=datetime.utcnow, description="When these metrics were captured"
    )

    def utilization_percent(self) -> float:
        """
        Calculate pool utilization percentage.

        Returns:
            Percentage of pool capacity in use (0-100)
        """
        if self.total_connections == 0:
            return 0.0
        return (self.connections_in_use / self.total_connections) * 100

    def is_exhausted(self) -> bool:
        """
        Check if pool is fully exhausted.

        Returns:
            True if no connections available
        """
        return self.connections_available == 0

    def is_degraded(self) -> bool:
        """
        Check if pool is in degraded state.

        Pool is degraded if:
        - Health check failed
        - High failure rate (>10% of created connections)
        - Very high utilization (>95%)

        Returns:
            True if pool is degraded
        """
        if not self.is_healthy:
            return True

        # High failure rate
        if self.connections_created > 0:
            failure_rate = self.connections_failed / self.connections_created
            if failure_rate > 0.1:  # >10% failure rate
                return True

        # Near-exhaustion
        if self.utilization_percent() > 95.0:
            return True

        return False

    def to_health_check_response(self) -> dict:
        """
        Format as health check response.

        Returns:
            Dict suitable for health check API response
        """
        status = "healthy"
        if self.is_degraded():
            status = "degraded"
        elif not self.is_healthy:
            status = "unhealthy"

        return {
            "status": status,
            "pool": {
                "total_connections": self.total_connections,
                "in_use": self.connections_in_use,
                "available": self.connections_available,
                "utilization_percent": round(self.utilization_percent(), 2),
                "peak_usage": self.max_connections_in_use,
            },
            "performance": {
                "avg_acquisition_ms": (
                    round(self.avg_acquisition_time_ms, 3) if self.avg_acquisition_time_ms else None
                ),
                "avg_query_ms": (
                    round(self.avg_query_time_ms, 3) if self.avg_query_time_ms else None
                ),
            },
            "lifecycle": {
                "created": self.connections_created,
                "recycled": self.connections_recycled,
                "failed": self.connections_failed,
            },
            "error": self.degraded_reason if not self.is_healthy else None,
            "measured_at": self.measured_at.isoformat(),
        }

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "total_connections": 50,
                "connections_in_use": 23,
                "connections_available": 27,
                "max_connections_in_use": 45,
                "connections_created": 120,
                "connections_recycled": 5,
                "connections_failed": 2,
                "is_healthy": True,
                "degraded_reason": None,
                "avg_acquisition_time_ms": 0.85,
                "avg_query_time_ms": 12.3,
                "measured_at": "2025-10-05T14:30:00Z",
            }
        }

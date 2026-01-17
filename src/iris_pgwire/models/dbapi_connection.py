"""
DBAPI connection wrapper model.

Wraps intersystems-irispython DBAPI connection with lifecycle tracking,
health checks, and pool management metadata.

Constitutional Requirements:
- Principle V (Production Readiness): Connection lifecycle management
- Principle IV (IRIS Integration): DBAPI backend support

Feature: 018-add-dbapi-option
Data Model: Entity #4 - DBAPIConnection
"""

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ConnectionState(str, Enum):
    """Connection lifecycle state."""

    IDLE = "idle"  # Available in pool
    IN_USE = "in_use"  # Currently executing query
    STALE = "stale"  # Marked for recycling
    FAILED = "failed"  # Connection error occurred


class DBAPIConnection(BaseModel):
    """
    Wrapper for DBAPI connection with pool management metadata.

    Lifecycle:
    1. IDLE: Connection created and added to pool
    2. IN_USE: Acquired by client for query execution
    3. IDLE: Returned to pool after query completion
    4. STALE: Exceeds pool_recycle lifetime, marked for recycling
    5. FAILED: Connection error, removed from pool
    """

    # Connection Identity
    connection_id: str = Field(description="Unique connection identifier")

    # Lifecycle State
    state: ConnectionState = Field(
        default=ConnectionState.IDLE, description="Current connection state"
    )
    created_at: datetime = Field(
        default_factory=datetime.utcnow, description="When connection was created"
    )
    last_used_at: datetime | None = Field(default=None, description="When connection was last used")
    last_recycled_at: datetime | None = Field(
        default=None, description="When connection was last recycled"
    )

    # Usage Statistics
    total_queries: int = Field(default=0, ge=0, description="Total queries executed")
    total_errors: int = Field(default=0, ge=0, description="Total errors encountered")
    total_acquisition_time_ms: float = Field(
        default=0.0, ge=0, description="Cumulative acquisition time"
    )

    # Health Status
    is_healthy: bool = Field(default=True, description="Connection health status")
    last_error: str | None = Field(
        default=None, description="Last error message if is_healthy=False"
    )
    last_health_check_at: datetime | None = Field(
        default=None, description="When connection was last health-checked"
    )

    # IRIS Connection Parameters (read-only snapshot)
    iris_hostname: str = Field(description="IRIS instance hostname")
    iris_port: int = Field(ge=1, le=65535, description="IRIS SuperServer port")
    iris_namespace: str = Field(description="Connected IRIS namespace")

    # Pool Management
    pool_recycle_seconds: int = Field(
        ge=60, description="Maximum connection lifetime before recycling"
    )

    # Pydantic v2 configuration
    model_config = ConfigDict(
        arbitrary_types_allowed=True,  # Allow arbitrary types for DBAPI connection
        extra="allow",  # Allow extra fields like 'connection'
        json_schema_extra={
            "example": {
                "connection_id": "conn-a1b2c3d4",
                "state": "in_use",
                "created_at": "2025-10-05T14:00:00Z",
                "last_used_at": "2025-10-05T14:30:00Z",
                "last_recycled_at": None,
                "total_queries": 142,
                "total_errors": 1,
                "total_acquisition_time_ms": 125.8,
                "is_healthy": True,
                "last_error": None,
                "last_health_check_at": "2025-10-05T14:29:00Z",
                "iris_hostname": "localhost",
                "iris_port": 1972,
                "iris_namespace": "USER",
                "pool_recycle_seconds": 3600,
            }
        },
    )

    def age_seconds(self) -> float:
        """
        Calculate connection age in seconds.

        Returns:
            Seconds since connection creation
        """
        return (datetime.now(UTC) - self.created_at).total_seconds()

    def should_recycle(self) -> bool:
        """
        Check if connection should be recycled based on age.

        Returns:
            True if connection exceeds pool_recycle_seconds
        """
        return self.age_seconds() >= self.pool_recycle_seconds

    def mark_in_use(self) -> None:
        """Mark connection as in-use (acquired from pool)."""
        self.state = ConnectionState.IN_USE
        self.last_used_at = datetime.now(UTC)

    def mark_idle(self) -> None:
        """Mark connection as idle (returned to pool)."""
        self.state = ConnectionState.IDLE

    def mark_stale(self) -> None:
        """Mark connection as stale (ready for recycling)."""
        self.state = ConnectionState.STALE

    def mark_failed(self, error_message: str) -> None:
        """
        Mark connection as failed.

        Args:
            error_message: Error description
        """
        self.state = ConnectionState.FAILED
        self.is_healthy = False
        self.last_error = error_message
        self.total_errors += 1

    def record_query_execution(self, acquisition_time_ms: float, success: bool = True) -> None:
        """
        Record query execution statistics.

        Args:
            acquisition_time_ms: Time taken to acquire connection
            success: Whether query succeeded
        """
        self.total_queries += 1
        self.total_acquisition_time_ms += acquisition_time_ms
        self.last_used_at = datetime.now(UTC)

        if not success:
            self.total_errors += 1

    def record_health_check(self, is_healthy: bool, error_message: str | None = None) -> None:
        """
        Record health check result.

        Args:
            is_healthy: Whether connection passed health check
            error_message: Error message if health check failed
        """
        self.is_healthy = is_healthy
        self.last_health_check_at = datetime.now(UTC)

        if not is_healthy and error_message:
            self.last_error = error_message

    def avg_acquisition_time_ms(self) -> float:
        """
        Calculate average connection acquisition time.

        Returns:
            Average acquisition time in milliseconds
        """
        if self.total_queries == 0:
            return 0.0
        return self.total_acquisition_time_ms / self.total_queries

    def error_rate(self) -> float:
        """
        Calculate error rate percentage.

        Returns:
            Percentage of queries that resulted in errors (0-100)
        """
        if self.total_queries == 0:
            return 0.0
        return (self.total_errors / self.total_queries) * 100

    def to_pool_metrics(self) -> dict:
        """
        Format connection metrics for pool aggregation.

        Returns:
            Dict with connection metrics
        """
        return {
            "connection_id": self.connection_id,
            "state": self.state.value,
            "age_seconds": round(self.age_seconds(), 2),
            "should_recycle": self.should_recycle(),
            "total_queries": self.total_queries,
            "error_rate_percent": round(self.error_rate(), 2),
            "avg_acquisition_ms": round(self.avg_acquisition_time_ms(), 3),
            "is_healthy": self.is_healthy,
            "last_error": self.last_error,
        }

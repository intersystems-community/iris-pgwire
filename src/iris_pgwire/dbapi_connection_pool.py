"""
DBAPI connection pool for InterSystems IRIS.

Queue-based asyncio connection pool with lifecycle management, health checks,
and connection recycling. Supports 50 base connections + 20 overflow under load.

Constitutional Requirements:
- Principle V (Production Readiness): Connection pooling and health checks
- Principle VI (Vector Performance): <1ms average acquisition time

Feature: 018-add-dbapi-option
Research: R2 (Queue-based connection pooling)
"""

import asyncio
import logging
import time
import uuid
from datetime import UTC, datetime

from iris_pgwire.models.backend_config import BackendConfig
from iris_pgwire.models.connection_pool_state import ConnectionPoolState
from iris_pgwire.models.dbapi_connection import (
    ConnectionState,
    DBAPIConnection,
)

logger = logging.getLogger(__name__)


class IRISConnectionPool:
    """
    Queue-based asyncio connection pool for IRIS DBAPI.

    Pool Architecture:
    - Base pool: Always-available connections (pool_size)
    - Overflow pool: Created under load (pool_max_overflow)
    - Timeout: Wait up to pool_timeout seconds for available connection
    - Recycling: Connections recycled after pool_recycle seconds

    Usage:
        pool = IRISConnectionPool(config)
        conn_wrapper = await pool.acquire()
        try:
            # Use conn_wrapper.connection for DBAPI operations
            cursor = conn_wrapper.connection.cursor()
            cursor.execute("SELECT 1")
        finally:
            await pool.release(conn_wrapper)
    """

    def __init__(self, config: BackendConfig):
        """
        Initialize connection pool.

        Args:
            config: Backend configuration with pool parameters
        """
        self.config = config
        self._pool: asyncio.Queue = asyncio.Queue(maxsize=config.total_connections())
        self._connections: dict[str, DBAPIConnection] = {}
        self._lock = asyncio.Lock()

        # Pool statistics
        self._total_created = 0
        self._total_recycled = 0
        self._total_failed = 0
        self._total_acquisitions = 0
        self._total_acquisition_time_ms = 0.0
        self._peak_in_use = 0

        # Health status
        self._is_healthy = True
        self._last_health_check: datetime | None = None
        self._last_error: str | None = None

        logger.info(
            "IRIS connection pool initialized",
            extra={
                "pool_size": config.pool_size,
                "max_overflow": config.pool_max_overflow,
                "total_capacity": config.total_connections(),
                "timeout": config.pool_timeout,
                "recycle": config.pool_recycle,
            },
        )

    async def acquire(self) -> DBAPIConnection:
        """
        Acquire connection from pool.

        Attempts to get connection from queue with timeout. If pool is empty
        and under capacity, creates new connection. If at capacity, waits for
        available connection.

        Returns:
            DBAPIConnection wrapper with IRIS DBAPI connection

        Raises:
            asyncio.TimeoutError: If no connection available within pool_timeout
            ConnectionError: If connection creation fails
        """
        start_time = time.perf_counter()

        while True:
            try:
                # Try to get existing connection from pool (non-blocking first)
                try:
                    conn_wrapper = self._pool.get_nowait()
                    logger.debug(f"Acquired existing connection: {conn_wrapper.connection_id}")

                    # Check if connection needs recycling
                    if conn_wrapper.should_recycle():
                        logger.info(
                            "Connection recycling triggered",
                            extra={
                                "connection_id": conn_wrapper.connection_id,
                                "age_seconds": conn_wrapper.age_seconds(),
                            },
                        )
                        await self._recycle_connection(conn_wrapper)
                        # Continue loop to get another connection
                        continue

                    # OPTIMIZATION: Check health ONLY if idle for more than 10 seconds
                    # This avoids the "SELECT 1" overhead on every acquisition under high load
                    idle_seconds = 0
                    if conn_wrapper.last_used_at:
                        idle_seconds = (datetime.now(UTC) - conn_wrapper.last_used_at).total_seconds()
                    
                    if idle_seconds > 10.0:
                        logger.debug(f"Connection {conn_wrapper.connection_id} idle for {idle_seconds:.1f}s, checking health")
                        is_healthy = await self._check_connection_health(conn_wrapper)
                        if not is_healthy:
                            logger.warning(f"Removing unhealthy connection {conn_wrapper.connection_id} after idle period")
                            await self._remove_connection(conn_wrapper)
                            continue

                    conn_wrapper.mark_in_use()
                    self._record_acquisition(start_time)
                    return conn_wrapper

                except asyncio.QueueEmpty:
                    # Pool empty - check if we can create new connection
                    async with self._lock:
                        if len(self._connections) < self.config.total_connections():
                            # Create new connection
                            conn_wrapper = await self._create_connection()
                            conn_wrapper.mark_in_use()
                            self._record_acquisition(start_time)
                            return conn_wrapper

                    # At capacity - wait for available connection
                    logger.debug("Pool at capacity, waiting for available connection")
                    conn_wrapper = await asyncio.wait_for(
                        self._pool.get(), timeout=self.config.pool_timeout
                    )

                    # Check for recycling
                    if conn_wrapper.should_recycle():
                        await self._recycle_connection(conn_wrapper)
                        # Continue loop to get/create another connection
                        continue
                    
                    # Also check health for connections that just came out of waiting
                    is_healthy = await self._check_connection_health(conn_wrapper)
                    if not is_healthy:
                        await self._remove_connection(conn_wrapper)
                        continue

                    conn_wrapper.mark_in_use()
                    self._record_acquisition(start_time)
                    return conn_wrapper

            except (asyncio.TimeoutError, TimeoutError):
                logger.error(
                    f"Connection acquisition timeout after {self.config.pool_timeout}s",
                    extra={
                        "pool_size": len(self._connections),
                        "in_use": self._connections_in_use(),
                    },
                )
                raise
            except Exception as e:
                logger.error(f"Connection acquisition failed: {e}")
                self._total_failed += 1
                self._is_healthy = False
                self._last_error = str(e)
                raise ConnectionError(f"Failed to acquire connection: {e}") from e

    async def release(self, conn_wrapper: DBAPIConnection) -> None:
        """
        Release connection back to pool.

        Args:
            conn_wrapper: Connection wrapper to release

        Raises:
            ValueError: If connection not from this pool
        """
        if conn_wrapper.connection_id not in self._connections:
            raise ValueError(f"Connection {conn_wrapper.connection_id} not from this pool")

        # CRITICAL OPTIMIZATION: Do NOT check health on every release
        # This was causing massive overhead and flakiness under load.
        # Health is now checked on acquisition if idle for >10s.
        
        # Only remove if explicitly marked as unhealthy during its use
        if not conn_wrapper.is_healthy:
            logger.warning(
                "Unhealthy connection removed from pool",
                extra={"connection_id": conn_wrapper.connection_id},
            )
            await self._remove_connection(conn_wrapper)
            return

        # Return to pool
        conn_wrapper.mark_idle()
        await self._pool.put(conn_wrapper)
        logger.debug(f"Connection released: {conn_wrapper.connection_id}")

    async def health_check(self) -> ConnectionPoolState:
        """
        Perform health check on pool.

        Returns:
            ConnectionPoolState with current pool metrics
        """
        self._last_health_check = datetime.now(UTC)

        connections_in_use = self._connections_in_use()
        connections_available = self._pool.qsize()
        total_connections = len(self._connections)

        # Calculate average acquisition time
        avg_acquisition_ms = (
            self._total_acquisition_time_ms / self._total_acquisitions
            if self._total_acquisitions > 0
            else None
        )

        state = ConnectionPoolState(
            total_connections=total_connections,
            connections_in_use=connections_in_use,
            connections_available=connections_available,
            max_connections_in_use=self._peak_in_use,
            connections_created=self._total_created,
            connections_recycled=self._total_recycled,
            connections_failed=self._total_failed,
            is_healthy=self._is_healthy,
            degraded_reason=self._last_error if not self._is_healthy else None,
            avg_acquisition_time_ms=avg_acquisition_ms,
            measured_at=self._last_health_check,
        )

        logger.info(
            "Pool health check",
            extra={
                "total": total_connections,
                "in_use": connections_in_use,
                "available": connections_available,
                "utilization": state.utilization_percent(),
                "is_healthy": self._is_healthy,
            },
        )

        return state

    async def close(self) -> None:
        """Close all connections and shutdown pool."""
        logger.info("Closing connection pool", extra={"connections": len(self._connections)})

        # Close all connections
        for conn_id, conn_wrapper in list(self._connections.items()):
            try:
                await self._close_connection(conn_wrapper)
            except Exception as e:
                logger.warning(f"Error closing connection {conn_id}: {e}")

        self._connections.clear()
        logger.info("Connection pool closed")

    async def _create_connection(self) -> DBAPIConnection:
        """
        Create new IRIS DBAPI connection.

        Returns:
            DBAPIConnection wrapper

        Raises:
            ConnectionError: If connection creation fails
        """
        try:
            # Import intersystems-irispython DBAPI module
            # NOTE: Package name is 'intersystems-irispython' but module is 'iris.dbapi'
            import iris.dbapi as dbapi

            # Create DBAPI connection
            connection = dbapi.connect(
                hostname=self.config.iris_hostname,
                port=self.config.iris_port,
                namespace=self.config.iris_namespace,
                username=self.config.iris_username,
                password=self.config.iris_password,
            )

            # Wrap in DBAPIConnection model
            conn_id = str(uuid.uuid4())[:8]
            conn_wrapper = DBAPIConnection(
                connection_id=f"conn-{conn_id}",
                state=ConnectionState.IDLE,
                iris_hostname=self.config.iris_hostname,
                iris_port=self.config.iris_port,
                iris_namespace=self.config.iris_namespace,
                pool_recycle_seconds=self.config.pool_recycle,
            )

            # Store raw DBAPI connection (not tracked by Pydantic)
            conn_wrapper.connection = connection  # type: ignore

            self._connections[conn_wrapper.connection_id] = conn_wrapper
            self._total_created += 1

            logger.info(
                "Created new connection",
                extra={
                    "connection_id": conn_wrapper.connection_id,
                    "total_connections": len(self._connections),
                },
            )

            return conn_wrapper

        except Exception as e:
            logger.error(f"Failed to create IRIS connection: {e}")
            self._total_failed += 1
            raise ConnectionError(f"Failed to create IRIS connection: {e}") from e

    async def _recycle_connection(self, conn_wrapper: DBAPIConnection) -> None:
        """
        Recycle stale connection.

        Args:
            conn_wrapper: Connection to recycle
        """
        conn_wrapper.mark_stale()
        await self._close_connection(conn_wrapper)
        del self._connections[conn_wrapper.connection_id]
        self._total_recycled += 1

        logger.info(
            "Connection recycled",
            extra={
                "connection_id": conn_wrapper.connection_id,
                "age_seconds": conn_wrapper.age_seconds(),
            },
        )

    async def _check_connection_health(self, conn_wrapper: DBAPIConnection) -> bool:
        """
        Check connection health with test query.

        Args:
            conn_wrapper: Connection to check

        Returns:
            True if connection is healthy
        """
        try:
            # Execute test query in thread pool to avoid blocking
            def test_query():
                cursor = conn_wrapper.connection.cursor()  # type: ignore
                cursor.execute("SELECT 1")
                cursor.close()
                return True

            await asyncio.to_thread(test_query)
            conn_wrapper.record_health_check(is_healthy=True)
            return True

        except Exception as e:
            logger.warning(f"Connection health check failed: {e}")
            conn_wrapper.record_health_check(is_healthy=False, error_message=str(e))
            return False

    async def _close_connection(self, conn_wrapper: DBAPIConnection) -> None:
        """
        Close DBAPI connection.

        Args:
            conn_wrapper: Connection to close
        """
        try:
            if hasattr(conn_wrapper, "connection"):
                await asyncio.to_thread(conn_wrapper.connection.close)  # type: ignore
        except Exception as e:
            logger.warning(f"Error closing connection: {e}")

    async def _remove_connection(self, conn_wrapper: DBAPIConnection) -> None:
        """
        Remove connection from pool.

        Args:
            conn_wrapper: Connection to remove
        """
        await self._close_connection(conn_wrapper)
        if conn_wrapper.connection_id in self._connections:
            del self._connections[conn_wrapper.connection_id]

    def _connections_in_use(self) -> int:
        """Count connections currently in use."""
        in_use = sum(
            1 for conn in self._connections.values() if conn.state == ConnectionState.IN_USE
        )
        # Update peak usage
        if in_use > self._peak_in_use:
            self._peak_in_use = in_use
        return in_use

    def _record_acquisition(self, start_time: float) -> None:
        """Record connection acquisition metrics."""
        elapsed_ms = (time.perf_counter() - start_time) * 1000
        self._total_acquisitions += 1
        self._total_acquisition_time_ms += elapsed_ms

        # Log if acquisition time exceeds 1ms SLA
        if elapsed_ms > 1.0:
            logger.warning(
                "Slow connection acquisition",
                extra={"acquisition_ms": round(elapsed_ms, 3)},
            )

    @property
    def pool_size(self) -> int:
        """Get configured pool size."""
        return self.config.pool_size

    @property
    def connections_available(self) -> int:
        """Get number of available connections."""
        return self._pool.qsize()

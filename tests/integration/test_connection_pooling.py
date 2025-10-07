"""
Integration tests for DBAPI connection pooling under load.

These tests validate connection pool behavior under production-like load conditions:
- 1000 concurrent client connections
- Pool exhaustion and timeout handling
- Connection recycling after lifecycle expiration
- Health check detection of degraded pool states

Constitutional Requirements:
- Principle V (Production Readiness): Connection pooling, health checks, graceful degradation
- Performance SLA: Average connection acquisition time <1ms

Feature: 018-add-dbapi-option
Test Scenarios: Based on FR-003 (connection pooling) and FR-005 (health checks)
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from iris_pgwire.config_schema import BackendConfig, BackendType

# Will fail until implemented (TDD)
try:
    from iris_pgwire.dbapi_executor import DBAPIExecutor
    from iris_pgwire.models.connection_pool_state import ConnectionPoolState
except ImportError:
    DBAPIExecutor = None
    ConnectionPoolState = None


pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_iris,
    pytest.mark.slow,
    pytest.mark.skipif(DBAPIExecutor is None, reason="DBAPIExecutor not implemented yet (TDD)"),
]


# pool_config fixture provided by conftest.py (uses environment variables)


@pytest.mark.asyncio
async def test_pool_handles_1000_concurrent_connections(pool_config):
    """
    GIVEN DBAPI executor with 50-connection pool + 20 overflow
    WHEN 1000 concurrent clients execute queries
    THEN all queries succeed within pool limits
    """
    executor = DBAPIExecutor(pool_config)

    async def concurrent_query(client_id: int):
        """Simulate single client query"""
        return await executor.execute_query(f"SELECT {client_id} AS client_id")

    # Execute 1000 concurrent queries
    start_time = time.perf_counter()
    tasks = [concurrent_query(i) for i in range(1000)]
    results = await asyncio.gather(*tasks)
    elapsed_ms = (time.perf_counter() - start_time) * 1000

    # Verify all queries succeeded
    assert len(results) == 1000
    for i, result in enumerate(results):
        assert result[0][0] == i

    # Verify pool stayed within limits (50 base + 20 overflow)
    pool_state = await executor.get_pool_state()
    assert pool_state.max_connections_in_use <= 70

    # Log performance for monitoring
    avg_query_time_ms = elapsed_ms / 1000
    print(f"✅ 1000 concurrent queries completed in {elapsed_ms:.2f}ms (avg {avg_query_time_ms:.2f}ms per query)")

    await executor.close()


@pytest.mark.asyncio
async def test_pool_exhaustion_timeout_handling(pool_config):
    """
    GIVEN pool with all connections in use
    WHEN new client attempts to acquire connection
    THEN client waits up to pool_timeout, then raises TimeoutError
    """
    # Configure small pool for faster testing (use environment vars from pool_config)
    small_pool_config = BackendConfig(
        backend_type=BackendType.DBAPI,
        iris_hostname=pool_config.iris_hostname,
        iris_port=pool_config.iris_port,
        iris_namespace=pool_config.iris_namespace,
        iris_username=pool_config.iris_username,
        iris_password=pool_config.iris_password,
        pool_size=2,  # Very small pool
        pool_max_overflow=1,  # Total 3 connections
        pool_timeout=2,  # 2-second timeout
    )

    executor = DBAPIExecutor(small_pool_config)

    async def long_running_query():
        """Hold connection for extended period"""
        await executor.execute_query("SELECT $system.Util.Sleep(5)")  # 5-second sleep

    # Exhaust pool with 3 long-running queries
    tasks = [asyncio.create_task(long_running_query()) for _ in range(3)]

    # Wait for pool to be exhausted
    await asyncio.sleep(0.5)

    # Attempt to acquire 4th connection - should timeout
    start_time = time.perf_counter()
    with pytest.raises(asyncio.TimeoutError):
        await executor.execute_query("SELECT 1")
    timeout_duration = time.perf_counter() - start_time

    # Verify timeout occurred near pool_timeout (2 seconds)
    assert 1.8 <= timeout_duration <= 2.5, f"Timeout duration {timeout_duration:.2f}s outside expected range"

    # Cleanup
    for task in tasks:
        task.cancel()
    await executor.close()


@pytest.mark.asyncio
async def test_connection_recycling_after_lifecycle_expiration(pool_config):
    """
    GIVEN pool with pool_recycle=3600 (1 hour)
    WHEN connection exceeds lifecycle
    THEN pool automatically recycles connection
    """
    # Use short recycle time for testing (use environment vars from pool_config)
    recycle_config = BackendConfig(
        backend_type=BackendType.DBAPI,
        iris_hostname=pool_config.iris_hostname,
        iris_port=pool_config.iris_port,
        iris_namespace=pool_config.iris_namespace,
        iris_username=pool_config.iris_username,
        iris_password=pool_config.iris_password,
        pool_size=5,
        pool_recycle=2,  # Recycle after 2 seconds
    )

    executor = DBAPIExecutor(recycle_config)

    # Execute query to create initial connection
    result1 = await executor.execute_query("SELECT 1")
    initial_pool_state = await executor.get_pool_state()
    initial_connection_count = initial_pool_state.total_connections

    # Wait for recycle timeout
    await asyncio.sleep(3)

    # Execute another query - should trigger recycling
    result2 = await executor.execute_query("SELECT 2")
    post_recycle_state = await executor.get_pool_state()

    # Verify connection was recycled (total connections refreshed)
    assert post_recycle_state.connections_recycled > 0, "No connections recycled after timeout"
    print(f"✅ Recycled {post_recycle_state.connections_recycled} stale connections")

    await executor.close()


@pytest.mark.asyncio
async def test_health_check_detects_degraded_pool(pool_config):
    """
    GIVEN DBAPI executor with health check enabled
    WHEN pool becomes degraded (e.g., IRIS connection failures)
    THEN health check returns unhealthy status
    """
    executor = DBAPIExecutor(pool_config)

    # Initial health check should pass
    health_status = await executor.health_check()
    assert health_status["status"] == "healthy"
    assert health_status["pool"]["available"] >= 0  # Field name is "available" not "available_connections"

    # Simulate pool degradation by closing IRIS connections
    # (In real scenario, this would be IRIS instance restart or network failure)
    with patch.object(executor.pool, "execute_query", side_effect=ConnectionError("IRIS unavailable")):
        # Execute query - should fail and mark pool as degraded
        with pytest.raises(ConnectionError):
            await executor.execute_query("SELECT 1")

        # Health check should now report unhealthy
        degraded_health = await executor.health_check()
        assert degraded_health["status"] == "unhealthy"
        assert "IRIS unavailable" in degraded_health.get("error", "")

    await executor.close()


@pytest.mark.asyncio
async def test_connection_acquisition_performance_sla(pool_config):
    """
    GIVEN warmed-up connection pool
    WHEN acquiring connections under normal load
    THEN average acquisition time <1ms (constitutional SLA)
    """
    executor = DBAPIExecutor(pool_config)

    # Warm up pool by executing initial queries
    for _ in range(10):
        await executor.execute_query("SELECT 1")

    # Measure connection acquisition time over 100 queries
    acquisition_times = []

    for _ in range(100):
        start = time.perf_counter()
        await executor.execute_query("SELECT 1")
        elapsed_ms = (time.perf_counter() - start) * 1000
        acquisition_times.append(elapsed_ms)

    # Calculate average acquisition time
    avg_acquisition_ms = sum(acquisition_times) / len(acquisition_times)
    p95_acquisition_ms = sorted(acquisition_times)[94]  # 95th percentile

    # Verify SLA compliance
    assert avg_acquisition_ms < 1.0, (
        f"Average acquisition time {avg_acquisition_ms:.3f}ms exceeds 1ms SLA"
    )

    print(f"✅ Connection acquisition performance: avg={avg_acquisition_ms:.3f}ms, p95={p95_acquisition_ms:.3f}ms")

    await executor.close()


@pytest.mark.asyncio
async def test_pool_graceful_shutdown_drains_connections(pool_config):
    """
    GIVEN pool with active connections
    WHEN close() is called
    THEN all connections gracefully drain before shutdown
    """
    executor = DBAPIExecutor(pool_config)

    # Create active connections
    async def active_query():
        await executor.execute_query("SELECT $system.Util.Sleep(1)")

    tasks = [asyncio.create_task(active_query()) for _ in range(10)]

    # Wait for queries to start
    await asyncio.sleep(0.2)

    # Initiate graceful shutdown
    shutdown_start = time.perf_counter()
    await executor.close()
    shutdown_duration = time.perf_counter() - shutdown_start

    # Verify all tasks completed
    for task in tasks:
        assert task.done(), "Active query did not complete during shutdown"

    # Verify pool is fully closed
    pool_state = await executor.get_pool_state()
    assert pool_state.total_connections == 0
    assert pool_state.connections_in_use == 0

    print(f"✅ Graceful shutdown completed in {shutdown_duration:.2f}s")


# Meta-test for TDD tracking
def test_tdd_placeholder_connection_pooling():
    """Verify DBAPIExecutor and ConnectionPoolState not implemented yet (TDD)."""
    if DBAPIExecutor is not None and ConnectionPoolState is not None:
        pytest.skip("Connection pooling implemented - remove this placeholder test")

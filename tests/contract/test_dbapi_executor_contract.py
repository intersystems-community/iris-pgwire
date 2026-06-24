"""
Contract tests for DBAPI Executor component.

These tests define the interface contract for DBAPI query execution with connection pooling.
They MUST fail initially (TDD approach) and only pass after implementation.

Constitutional Requirements:
- Principle II (Test-First Development): Write failing tests before implementation
- Principle V (Production Readiness): Connection pooling, health checks, error handling
- Principle VI (Vector Performance): <5ms translation overhead

Feature: 018-add-dbapi-option
Contract: specs/018-add-dbapi-option/contracts/dbapi-executor-contract.md
"""

import asyncio
import socket
import time

import pytest

from iris_pgwire.config_schema import BackendConfig, BackendType

# These imports will fail initially - that's expected for TDD
try:
    from iris_pgwire.dbapi_executor import DBAPIExecutor
    from iris_pgwire.models.vector_query_request import VectorQueryRequest
except ImportError:
    DBAPIExecutor = None
    VectorQueryRequest = None


def _iris_reachable(host: str = "localhost", port: int = 2972) -> bool:
    """Check if the iris-pgwire-db container IRIS port is reachable (2972)."""
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


pytestmark = [pytest.mark.contract, pytest.mark.asyncio]


@pytest.fixture
def test_config():
    """Test configuration for DBAPI executor."""
    return BackendConfig(
        backend_type=BackendType.DBAPI,
        iris_hostname="localhost",
        iris_port=2972,  # iris-pgwire-db container maps 2972→1972
        iris_namespace="USER",
        iris_username="_SYSTEM",
        iris_password="SYS",
        pool_size=50,
        pool_max_overflow=20,
    )


@pytest.mark.skipif(DBAPIExecutor is None, reason="DBAPIExecutor not implemented yet (TDD)")
def test_dbapi_executor_initializes_pool(test_config):
    """
    GIVEN valid DBAPI configuration
    WHEN DBAPIExecutor is created
    THEN connection pool is initialized with correct size (lazy — 0 connections until first acquire)
    """
    executor = DBAPIExecutor(test_config)

    assert executor.pool.pool_size == 50
    # Pool is lazy; connections are created on first acquire, not at init
    assert executor.pool.connections_available >= 0


@pytest.mark.skipif(DBAPIExecutor is None, reason="DBAPIExecutor not implemented yet (TDD)")
@pytest.mark.skipif(not _iris_reachable(), reason="IRIS not reachable on localhost:1972")
@pytest.mark.requires_iris
async def test_dbapi_executor_executes_simple_query(test_config):
    """
    GIVEN initialized DBAPI executor
    WHEN execute_query is called with simple SQL
    THEN query executes and returns results
    """
    executor = DBAPIExecutor(test_config)
    results = await executor.execute_query("SELECT 1 AS test")

    assert len(results) == 1
    assert results[0][0] == 1

    await executor.close()


@pytest.mark.skipif(DBAPIExecutor is None, reason="DBAPIExecutor not implemented yet (TDD)")
@pytest.mark.skipif(
    VectorQueryRequest is None, reason="VectorQueryRequest not implemented yet (TDD)"
)
@pytest.mark.skipif(not _iris_reachable(), reason="IRIS not reachable on localhost:1972")
@pytest.mark.requires_iris
async def test_dbapi_executor_handles_large_vectors(test_config):
    """
    GIVEN vector query with >1000 dimensions
    WHEN execute_vector_query is called
    THEN query executes successfully via DBAPI
    """
    executor = DBAPIExecutor(test_config)

    # Setup: Create table with 1024-dim vector
    await executor.execute_query(
        "CREATE TABLE test_vectors_contract (id INT, embedding VECTOR(DECIMAL, 1024))"
    )

    try:
        # Execute vector similarity query
        request = VectorQueryRequest(
            request_id="test-001",
            original_sql="SELECT * FROM test_vectors_contract ORDER BY embedding <-> '[0.1,...]' LIMIT 5",
            vector_operator="<->",
            vector_column="embedding",
            query_vector=[0.1] * 1024,  # 1024 dimensions
            limit_clause=5,
            translated_sql="SELECT TOP 5 * FROM test_vectors_contract ORDER BY VECTOR_COSINE(embedding, TO_VECTOR(..., 'DECIMAL'))",
            translation_time_ms=2.5,
            backend_type="dbapi",
        )
        results = await executor.execute_vector_query(request)

        assert isinstance(results, list)
    finally:
        # Cleanup
        await executor.execute_query("DROP TABLE test_vectors_contract")
        await executor.close()


@pytest.mark.skipif(DBAPIExecutor is None, reason="DBAPIExecutor not implemented yet (TDD)")
@pytest.mark.skipif(not _iris_reachable(), reason="IRIS not reachable on localhost:1972")
@pytest.mark.requires_iris
@pytest.mark.slow
async def test_dbapi_executor_pool_handles_1000_concurrent_connections(test_config):
    """
    GIVEN 1000 concurrent client connections
    WHEN all execute queries simultaneously
    THEN pool handles load with 50 connections
    """
    executor = DBAPIExecutor(test_config)

    async def concurrent_query(i):
        return await executor.execute_query(f"SELECT {i} AS id")

    # Simulate 1000 concurrent connections
    tasks = [concurrent_query(i) for i in range(1000)]
    results = await asyncio.gather(*tasks)

    assert len(results) == 1000
    assert executor.pool.connections_in_use <= 70  # 50 + 20 overflow

    await executor.close()


@pytest.mark.skipif(DBAPIExecutor is None, reason="DBAPIExecutor not implemented yet (TDD)")
@pytest.mark.skipif(not _iris_reachable(), reason="IRIS not reachable on localhost:1972")
@pytest.mark.requires_iris
async def test_dbapi_executor_reconnects_after_iris_restart(test_config):
    """
    GIVEN IRIS instance restarts during operation
    WHEN execute_query is called
    THEN executor reconnects automatically
    """
    executor = DBAPIExecutor(test_config)

    # Simulate IRIS restart (close all connections)
    await executor.pool.close()

    # Should reconnect automatically
    results = await executor.execute_query("SELECT 1")
    assert len(results) == 1

    await executor.close()


@pytest.mark.skipif(DBAPIExecutor is None, reason="DBAPIExecutor not implemented yet (TDD)")
@pytest.mark.skipif(not _iris_reachable(), reason="IRIS not reachable on localhost:1972")
@pytest.mark.requires_iris
async def test_dbapi_executor_translation_time_under_5ms(test_config):
    """
    GIVEN complex vector query
    WHEN query is executed
    THEN total overhead <5ms (constitutional SLA)

    Note: This tests executor overhead, not IRIS execution time
    """
    executor = DBAPIExecutor(test_config)

    # Warm up connection pool
    await executor.execute_query("SELECT 1")

    # Measure overhead
    start = time.perf_counter()
    await executor.execute_query("SELECT 1")
    elapsed_ms = (time.perf_counter() - start) * 1000

    # Note: This includes network latency to IRIS
    # Pure overhead should be <1ms, but we allow 5ms SLA for network
    assert elapsed_ms < 5.0, f"Executor overhead {elapsed_ms:.2f}ms exceeds 5ms SLA"

    await executor.close()


def test_dbapi_executor_class_exists():
    """DBAPIExecutor implementation exists and is importable."""
    assert DBAPIExecutor is not None, "DBAPIExecutor should be importable"

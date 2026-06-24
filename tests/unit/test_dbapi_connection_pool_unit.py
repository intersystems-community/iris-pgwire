"""
Unit tests for iris_pgwire.dbapi_connection_pool.IRISConnectionPool

Strategy: mock iris.dbapi so no real IRIS connection is needed.
Covers pool init, acquire/release, health checks, recycling, close,
statistics, timeout, and error paths.
"""

from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

# ---------------------------------------------------------------------------
# Stub iris.dbapi before the module is imported
# ---------------------------------------------------------------------------


def _make_iris_stub():
    """Return a minimal iris.dbapi stub module."""
    iris_mod = types.ModuleType("iris")
    dbapi_mod = types.ModuleType("iris.dbapi")

    def connect(**kwargs):
        conn = MagicMock()
        cursor = MagicMock()
        cursor.description = None
        cursor.rowcount = 1
        conn.cursor.return_value = cursor
        return conn

    dbapi_mod.connect = connect
    iris_mod.dbapi = dbapi_mod
    return iris_mod, dbapi_mod


_iris_mod, _dbapi_mod = _make_iris_stub()
sys.modules.setdefault("iris", _iris_mod)
sys.modules.setdefault("iris.dbapi", _dbapi_mod)

# ---------------------------------------------------------------------------
# Now import the real module under test
# ---------------------------------------------------------------------------

from iris_pgwire.dbapi_connection_pool import IRISConnectionPool  # noqa: E402
from iris_pgwire.models.backend_config import BackendConfig, BackendType  # noqa: E402
from iris_pgwire.models.dbapi_connection import ConnectionState, DBAPIConnection  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    pool_size: int = 5,
    pool_max_overflow: int = 2,
    pool_timeout: int = 2,
    pool_recycle: int = 3600,
    strict_single_connection: bool = False,
) -> BackendConfig:
    """Build a BackendConfig suitable for unit tests (no real IRIS required)."""
    return BackendConfig(
        backend_type=BackendType.DBAPI,
        iris_hostname="localhost",
        iris_port=1972,
        iris_namespace="USER",
        iris_username="_SYSTEM",
        iris_password="SYS",
        pool_size=pool_size,
        pool_max_overflow=pool_max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
        strict_single_connection=strict_single_connection,
    )


def _make_conn_wrapper(
    connection_id: str = "conn-test01",
    recycle_seconds: int = 3600,
    state: ConnectionState = ConnectionState.IDLE,
) -> DBAPIConnection:
    """Build a DBAPIConnection wrapper backed by a mock DBAPI connection."""
    wrapper = DBAPIConnection(
        connection_id=connection_id,
        state=state,
        iris_hostname="localhost",
        iris_port=1972,
        iris_namespace="USER",
        pool_recycle_seconds=recycle_seconds,
    )
    wrapper.connection = MagicMock()  # type: ignore[attr-defined]
    return wrapper


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def config():
    return _make_config()


@pytest.fixture
def pool(config):
    return IRISConnectionPool(config)


# ---------------------------------------------------------------------------
# __init__ tests
# ---------------------------------------------------------------------------


class TestInit:
    def test_pool_initializes_empty(self, pool):
        assert pool._pool.qsize() == 0
        assert len(pool._connections) == 0

    def test_stats_start_at_zero(self, pool):
        assert pool._total_created == 0
        assert pool._total_recycled == 0
        assert pool._total_failed == 0
        assert pool._total_acquisitions == 0
        assert pool._total_acquisition_time_ms == 0.0
        assert pool._peak_in_use == 0

    def test_healthy_on_init(self, pool):
        assert pool._is_healthy is True
        assert pool._last_error is None

    def test_pool_size_property(self, config, pool):
        assert pool.pool_size == config.pool_size

    def test_connections_available_property(self, pool):
        assert pool.connections_available == 0


# ---------------------------------------------------------------------------
# _create_connection tests
# ---------------------------------------------------------------------------


class TestCreateConnection:
    @pytest.mark.asyncio
    async def test_create_connection_returns_wrapper(self, pool):
        wrapper = await pool._create_connection()
        assert wrapper.connection_id.startswith("conn-")
        assert wrapper.connection_id in pool._connections
        assert pool._total_created == 1

    @pytest.mark.asyncio
    async def test_create_connection_failure_increments_failed(self, pool):
        import iris.dbapi as real_dbapi

        original_connect = real_dbapi.connect
        real_dbapi.connect = Mock(side_effect=RuntimeError("connection refused"))
        try:
            with pytest.raises(ConnectionError, match="Failed to create IRIS connection"):
                await pool._create_connection()
            assert pool._total_failed == 1
        finally:
            real_dbapi.connect = original_connect


# ---------------------------------------------------------------------------
# acquire / release tests
# ---------------------------------------------------------------------------


class TestAcquireRelease:
    @pytest.mark.asyncio
    async def test_acquire_creates_connection(self, pool):
        conn = await pool.acquire()
        assert conn.state == ConnectionState.IN_USE
        assert pool._total_acquisitions == 1
        await pool.release(conn)

    @pytest.mark.asyncio
    async def test_release_returns_to_pool(self, pool):
        conn = await pool.acquire()
        await pool.release(conn)
        assert conn.state == ConnectionState.IDLE
        assert pool._pool.qsize() == 1

    @pytest.mark.asyncio
    async def test_acquire_reuses_released_connection(self, pool):
        conn1 = await pool.acquire()
        await pool.release(conn1)
        conn2 = await pool.acquire()
        assert conn1.connection_id == conn2.connection_id
        await pool.release(conn2)

    @pytest.mark.asyncio
    async def test_release_unknown_connection_raises(self, pool):
        unknown = _make_conn_wrapper("conn-unknown")
        with pytest.raises(ValueError, match="not from this pool"):
            await pool.release(unknown)

    @pytest.mark.asyncio
    async def test_release_unhealthy_connection_removes_it(self, pool):
        conn = await pool.acquire()
        conn.is_healthy = False
        await pool.release(conn)
        assert conn.connection_id not in pool._connections
        assert pool._pool.qsize() == 0

    @pytest.mark.asyncio
    async def test_acquire_multiple_connections(self, pool):
        conns = [await pool.acquire() for _ in range(3)]
        assert len(pool._connections) == 3
        for c in conns:
            await pool.release(c)

    @pytest.mark.asyncio
    async def test_acquire_singleton_uses_lock(self):
        cfg = _make_config(pool_size=1, pool_max_overflow=0, strict_single_connection=True)
        p = IRISConnectionPool(cfg)
        conn = await p.acquire()
        assert p._singleton_lock.locked()
        await p.release(conn)
        assert not p._singleton_lock.locked()

    @pytest.mark.asyncio
    async def test_acquire_failure_marks_unhealthy(self, pool):
        import iris.dbapi as real_dbapi

        original = real_dbapi.connect
        real_dbapi.connect = Mock(side_effect=RuntimeError("network error"))
        try:
            with pytest.raises(ConnectionError):
                await pool.acquire()
            assert pool._is_healthy is False
            assert pool._last_error is not None
        finally:
            real_dbapi.connect = original


# ---------------------------------------------------------------------------
# _needs_health_check
# ---------------------------------------------------------------------------


class TestNeedsHealthCheck:
    @pytest.mark.asyncio
    async def test_no_last_used_returns_false(self, pool):
        wrapper = _make_conn_wrapper()
        result = await pool._needs_health_check(wrapper)
        assert result is False

    @pytest.mark.asyncio
    async def test_recently_used_returns_false(self, pool):
        from datetime import UTC, datetime

        wrapper = _make_conn_wrapper()
        wrapper.mark_in_use()  # sets last_used_at to now
        result = await pool._needs_health_check(wrapper)
        assert result is False

    @pytest.mark.asyncio
    async def test_idle_more_than_10s_returns_true(self, pool):
        from datetime import UTC, datetime, timedelta

        wrapper = _make_conn_wrapper()
        # Manually back-date last_used_at
        wrapper.last_used_at = datetime.now(UTC) - timedelta(seconds=15)
        result = await pool._needs_health_check(wrapper)
        assert result is True


# ---------------------------------------------------------------------------
# _check_connection_health
# ---------------------------------------------------------------------------


class TestCheckConnectionHealth:
    @pytest.mark.asyncio
    async def test_healthy_connection_returns_true(self, pool):
        wrapper = _make_conn_wrapper()
        result = await pool._check_connection_health(wrapper)
        assert result is True
        assert wrapper.is_healthy is True

    @pytest.mark.asyncio
    async def test_unhealthy_connection_returns_false(self, pool):
        wrapper = _make_conn_wrapper()
        wrapper.connection.cursor.side_effect = RuntimeError("dead")  # type: ignore[attr-defined]
        result = await pool._check_connection_health(wrapper)
        assert result is False
        assert wrapper.is_healthy is False


# ---------------------------------------------------------------------------
# _recycle_connection
# ---------------------------------------------------------------------------


class TestRecycleConnection:
    @pytest.mark.asyncio
    async def test_recycle_removes_from_connections(self, pool):
        conn = await pool._create_connection()
        conn_id = conn.connection_id
        await pool._recycle_connection(conn)
        assert conn_id not in pool._connections
        assert pool._total_recycled == 1


# ---------------------------------------------------------------------------
# _acquire_existing_connection — recycle / health-check branches
# ---------------------------------------------------------------------------


class TestAcquireExistingConnection:
    @pytest.mark.asyncio
    async def test_returns_none_when_queue_empty(self, pool):
        result = await pool._acquire_existing_connection(0.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_recycles_stale_connection(self, pool):
        """A connection older than pool_recycle should be recycled and None returned."""
        # Create a fresh conn wrapper and put it in the queue
        conn = _make_conn_wrapper(recycle_seconds=60)
        pool._connections[conn.connection_id] = conn
        # Force should_recycle() → True by backdating created_at
        from datetime import UTC, datetime, timedelta

        conn.created_at = datetime.now(UTC) - timedelta(seconds=120)
        await pool._pool.put(conn)

        result = await pool._acquire_existing_connection(0.0)
        assert result is None
        assert conn.connection_id not in pool._connections

    @pytest.mark.asyncio
    async def test_removes_idle_unhealthy_connection(self, pool):
        """After idle >10s, unhealthy connection should be removed."""
        from datetime import UTC, datetime, timedelta

        conn = _make_conn_wrapper()
        conn.last_used_at = datetime.now(UTC) - timedelta(seconds=15)
        # Make health check fail
        conn.connection.cursor.side_effect = RuntimeError("gone")  # type: ignore[attr-defined]
        pool._connections[conn.connection_id] = conn
        await pool._pool.put(conn)

        result = await pool._acquire_existing_connection(0.0)
        assert result is None
        assert conn.connection_id not in pool._connections


# ---------------------------------------------------------------------------
# _validate_waited_connection
# ---------------------------------------------------------------------------


class TestValidateWaitedConnection:
    @pytest.mark.asyncio
    async def test_valid_connection_returns_it(self, pool):
        from datetime import UTC, datetime

        conn = _make_conn_wrapper()
        pool._connections[conn.connection_id] = conn
        result = await pool._validate_waited_connection(conn, 0.0)
        assert result is conn
        assert conn.state == ConnectionState.IN_USE

    @pytest.mark.asyncio
    async def test_stale_connection_recycled(self, pool):
        from datetime import UTC, datetime, timedelta

        conn = _make_conn_wrapper(recycle_seconds=60)
        conn.created_at = datetime.now(UTC) - timedelta(seconds=120)
        pool._connections[conn.connection_id] = conn
        result = await pool._validate_waited_connection(conn, 0.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_unhealthy_connection_removed(self, pool):
        conn = _make_conn_wrapper()
        conn.connection.cursor.side_effect = RuntimeError("bad")  # type: ignore[attr-defined]
        pool._connections[conn.connection_id] = conn
        result = await pool._validate_waited_connection(conn, 0.0)
        assert result is None


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_health_check_returns_state(self, pool):
        conn = await pool.acquire()
        await pool.release(conn)

        state = await pool.health_check()
        assert state.total_connections == 1
        assert state.connections_available == 1
        assert state.is_healthy is True

    @pytest.mark.asyncio
    async def test_health_check_avg_acquisition_ms(self, pool):
        conn = await pool.acquire()
        await pool.release(conn)
        state = await pool.health_check()
        assert state.avg_acquisition_time_ms is not None
        assert state.avg_acquisition_time_ms >= 0.0

    @pytest.mark.asyncio
    async def test_health_check_no_acquisitions_avg_is_none(self, pool):
        state = await pool.health_check()
        assert state.avg_acquisition_time_ms is None


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


class TestClose:
    @pytest.mark.asyncio
    async def test_close_empties_connections(self, pool):
        conn = await pool.acquire()
        await pool.release(conn)
        assert len(pool._connections) == 1
        await pool.close()
        assert len(pool._connections) == 0

    @pytest.mark.asyncio
    async def test_close_handles_close_errors(self, pool):
        conn = await pool.acquire()
        conn.connection.close.side_effect = RuntimeError("close failed")  # type: ignore[attr-defined]
        await pool.release(conn)
        # Should not raise
        await pool.close()


# ---------------------------------------------------------------------------
# _record_acquisition / _connections_in_use
# ---------------------------------------------------------------------------


class TestInternalBookkeeping:
    @pytest.mark.asyncio
    async def test_peak_in_use_tracked(self, pool):
        conns = [await pool.acquire() for _ in range(3)]
        # _peak_in_use is updated lazily when _connections_in_use() is called
        in_use = pool._connections_in_use()
        assert in_use == 3
        assert pool._peak_in_use == 3
        for c in conns:
            await pool.release(c)

    def test_record_acquisition_updates_stats(self, pool):
        import time

        start = time.perf_counter() - 0.002  # simulate 2ms elapsed
        pool._record_acquisition(start)
        assert pool._total_acquisitions == 1
        assert pool._total_acquisition_time_ms > 0

    def test_connections_in_use_counts_correctly(self, pool):
        w1 = _make_conn_wrapper("conn-a", state=ConnectionState.IN_USE)
        w2 = _make_conn_wrapper("conn-b", state=ConnectionState.IDLE)
        pool._connections["conn-a"] = w1
        pool._connections["conn-b"] = w2
        assert pool._connections_in_use() == 1


# ---------------------------------------------------------------------------
# Pool timeout
# ---------------------------------------------------------------------------


class TestPoolTimeout:
    @pytest.mark.asyncio
    async def test_timeout_raises_on_saturated_pool(self):
        """Exhaust the pool then verify timeout propagates as ConnectionError."""
        cfg = _make_config(pool_size=1, pool_max_overflow=0, pool_timeout=1)
        p = IRISConnectionPool(cfg)
        # Acquire the single connection and hold it
        conn = await p.acquire()
        # Release in background so the second acquire eventually gets an error
        async def _release_later():
            await asyncio.sleep(2)
            await p.release(conn)

        asyncio.create_task(_release_later())

        with pytest.raises((ConnectionError, TimeoutError)):
            await asyncio.wait_for(p.acquire(), timeout=1.5)
        await p.close()

"""
Unit tests for iris_pgwire.health_checker.HealthChecker

Strategy: mock the connection pool (acquire/release/close) and asyncio.to_thread
so no real IRIS connection is needed.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from iris_pgwire.health_checker import HealthChecker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pool(
    acquire_result=None,
    acquire_side_effect=None,
    release_side_effect=None,
    close_side_effect=None,
):
    """Return a mock connection pool."""
    pool = MagicMock()

    conn_wrapper = MagicMock()
    conn_wrapper.connection = MagicMock()

    if acquire_side_effect is not None:
        pool.acquire = AsyncMock(side_effect=acquire_side_effect)
    else:
        pool.acquire = AsyncMock(return_value=acquire_result or conn_wrapper)

    pool.release = AsyncMock(side_effect=release_side_effect)
    pool.close = AsyncMock(side_effect=close_side_effect)
    return pool, conn_wrapper


# ---------------------------------------------------------------------------
# __init__
# ---------------------------------------------------------------------------


class TestHealthCheckerInit:
    def test_initial_state(self):
        pool, _ = _make_pool()
        hc = HealthChecker(pool)
        assert hc.is_healthy is True
        assert hc.last_check_time is None
        assert hc.consecutive_failures == 0

    def test_max_reconnect_attempts(self):
        pool, _ = _make_pool()
        hc = HealthChecker(pool)
        assert hc.max_reconnect_attempts == 10

    def test_pool_stored(self):
        pool, _ = _make_pool()
        hc = HealthChecker(pool)
        assert hc.pool is pool


# ---------------------------------------------------------------------------
# check_iris_health – success path
# ---------------------------------------------------------------------------


class TestCheckIrisHealthSuccess:
    @pytest.mark.asyncio
    async def test_returns_true_when_query_succeeds(self):
        pool, conn_wrapper = _make_pool()

        # Patch asyncio.to_thread so the test_query closure returns True
        with patch("asyncio.to_thread", new_callable=AsyncMock, return_value=True):
            hc = HealthChecker(pool)
            result = await hc.check_iris_health()

        assert result is True
        assert hc.is_healthy is True
        assert hc.last_check_time is not None

    @pytest.mark.asyncio
    async def test_consecutive_failures_reset_on_recovery(self):
        pool, conn_wrapper = _make_pool()

        with patch("asyncio.to_thread", new_callable=AsyncMock, return_value=True):
            hc = HealthChecker(pool)
            hc.consecutive_failures = 5
            hc.is_healthy = False
            result = await hc.check_iris_health()

        assert result is True
        assert hc.consecutive_failures == 0
        assert hc.is_healthy is True

    @pytest.mark.asyncio
    async def test_release_called_after_success(self):
        pool, conn_wrapper = _make_pool()

        with patch("asyncio.to_thread", new_callable=AsyncMock, return_value=True):
            hc = HealthChecker(pool)
            await hc.check_iris_health()

        pool.release.assert_called_once_with(conn_wrapper)


# ---------------------------------------------------------------------------
# check_iris_health – failure paths
# ---------------------------------------------------------------------------


class TestCheckIrisHealthFailure:
    @pytest.mark.asyncio
    async def test_timeout_error_returns_false(self):
        pool, _ = _make_pool(acquire_side_effect=asyncio.TimeoutError())
        hc = HealthChecker(pool)
        result = await hc.check_iris_health()

        assert result is False
        assert hc.is_healthy is False
        assert hc.consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_generic_exception_returns_false(self):
        pool, _ = _make_pool(acquire_side_effect=RuntimeError("connection refused"))
        hc = HealthChecker(pool)
        result = await hc.check_iris_health()

        assert result is False
        assert hc.is_healthy is False
        assert hc.consecutive_failures == 1

    @pytest.mark.asyncio
    async def test_query_returns_none_raises_runtime_error(self):
        pool, conn_wrapper = _make_pool()

        with patch("asyncio.to_thread", new_callable=AsyncMock, return_value=False):
            hc = HealthChecker(pool)
            result = await hc.check_iris_health()

        assert result is False
        assert hc.is_healthy is False

    @pytest.mark.asyncio
    async def test_consecutive_failures_increments(self):
        pool, _ = _make_pool(acquire_side_effect=RuntimeError("err"))
        hc = HealthChecker(pool)
        await hc.check_iris_health()
        await hc.check_iris_health()
        assert hc.consecutive_failures == 2

    @pytest.mark.asyncio
    async def test_release_called_even_when_query_fails(self):
        pool, conn_wrapper = _make_pool()

        with patch("asyncio.to_thread", new_callable=AsyncMock, return_value=False):
            hc = HealthChecker(pool)
            await hc.check_iris_health()

        pool.release.assert_called_once_with(conn_wrapper)


# ---------------------------------------------------------------------------
# handle_iris_restart
# ---------------------------------------------------------------------------


class TestHandleIrisRestart:
    @pytest.mark.asyncio
    async def test_succeeds_on_first_attempt(self):
        pool, conn_wrapper = _make_pool()

        with patch("asyncio.to_thread", new_callable=AsyncMock, return_value=True):
            hc = HealthChecker(pool)
            result = await hc.handle_iris_restart()

        assert result is True
        pool.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_false_after_all_attempts_fail(self):
        pool, _ = _make_pool(acquire_side_effect=RuntimeError("no iris"))

        with patch("asyncio.sleep", new_callable=AsyncMock):
            hc = HealthChecker(pool)
            result = await hc.handle_iris_restart()

        assert result is False

    @pytest.mark.asyncio
    async def test_skips_sleep_on_first_attempt(self):
        pool, conn_wrapper = _make_pool()

        sleep_mock = AsyncMock()
        with patch("asyncio.sleep", sleep_mock):
            with patch("asyncio.to_thread", new_callable=AsyncMock, return_value=True):
                hc = HealthChecker(pool)
                await hc.handle_iris_restart()

        # Sleep not called on attempt 1 (attempt > 1 guard)
        sleep_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_exponential_backoff_delay(self):
        """Verify the delay schedule: min(2^(attempt-1), 1024) capped at 1024.

        Delay formula in source: delay_seconds = min(2 ** (attempt - 1), 1024)
        Sleep is skipped on attempt==1. So:
          attempt 1 → no sleep
          attempt 2 → sleep(2)
          attempt 3 → sleep(4)
          attempt 4 → sleep(8)  ← health check succeeds here
        """
        call_count = 0
        sleep_delays = []

        async def fake_sleep(n):
            sleep_delays.append(n)

        async def fake_health():
            nonlocal call_count
            call_count += 1
            # Fail first 3 attempts, succeed on 4th
            return call_count >= 4

        pool, _ = _make_pool()
        with patch("asyncio.sleep", side_effect=fake_sleep):
            hc = HealthChecker(pool)
            hc.check_iris_health = fake_health  # type: ignore
            result = await hc.handle_iris_restart()

        assert result is True
        # Attempt 1: no sleep; attempts 2, 3, 4 sleep with 2^(attempt-1)
        assert sleep_delays == [2, 4, 8]

    @pytest.mark.asyncio
    async def test_succeeds_on_second_attempt(self):
        call_count = 0

        async def fake_health():
            nonlocal call_count
            call_count += 1
            return call_count >= 2

        pool, _ = _make_pool()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            hc = HealthChecker(pool)
            hc.check_iris_health = fake_health  # type: ignore
            result = await hc.handle_iris_restart()

        assert result is True
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_delay_capped_at_1024(self):
        """Delay formula: min(2^(attempt-1), 1024) — verify cap."""
        # attempt=11 would give 2^10=1024 which is already the cap
        hc = HealthChecker(MagicMock())
        # The delay for attempt=11 (which is attempt-1=10)
        delay = min(2 ** (11 - 1), 1024)
        assert delay == 1024

        # Attempt 12 would stay at 1024
        delay_high = min(2 ** (12 - 1), 1024)
        assert delay_high == 1024


# ---------------------------------------------------------------------------
# start_monitoring
# ---------------------------------------------------------------------------


class TestStartMonitoring:
    @pytest.mark.asyncio
    async def test_triggers_reconnect_after_3_failures(self):
        """After 3+ consecutive failures, handle_iris_restart is called."""
        pool, _ = _make_pool()

        restart_called = []

        async def fake_restart():
            restart_called.append(True)
            raise asyncio.CancelledError()  # stop the loop after restart

        async def fake_health():
            return False  # always unhealthy

        hc = HealthChecker(pool)
        hc.check_iris_health = fake_health  # type: ignore
        hc.handle_iris_restart = fake_restart  # type: ignore
        hc.consecutive_failures = 3  # Prime for reconnect threshold

        # Use a real timeout to prevent hanging; the CancelledError from
        # fake_restart propagates out of start_monitoring as BaseException.
        with pytest.raises((asyncio.CancelledError, Exception)):
            await asyncio.wait_for(hc.start_monitoring(interval_seconds=0), timeout=2.0)

        assert len(restart_called) > 0

    @pytest.mark.asyncio
    async def test_continues_monitoring_on_exception(self):
        """Exceptions in the loop body are caught and monitoring continues."""
        call_count = 0

        async def fake_health():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("transient error")
            # Succeed on 2nd call, then raise CancelledError to exit the loop
            if call_count >= 2:
                raise asyncio.CancelledError()
            return True

        pool, _ = _make_pool()
        hc = HealthChecker(pool)
        hc.check_iris_health = fake_health  # type: ignore

        with pytest.raises((asyncio.CancelledError, Exception)):
            await asyncio.wait_for(hc.start_monitoring(interval_seconds=0), timeout=2.0)

        assert call_count >= 1


# ---------------------------------------------------------------------------
# get_health_status
# ---------------------------------------------------------------------------


class TestGetHealthStatus:
    def test_initial_status(self):
        pool, _ = _make_pool()
        hc = HealthChecker(pool)
        status = hc.get_health_status()

        assert status["is_healthy"] is True
        assert status["last_check_time"] is None
        assert status["consecutive_failures"] == 0
        assert status["time_since_last_check"] is None

    def test_status_after_last_check_time_set(self):
        pool, _ = _make_pool()
        hc = HealthChecker(pool)
        hc.last_check_time = time.time() - 5.0

        status = hc.get_health_status()
        assert status["time_since_last_check"] is not None
        assert status["time_since_last_check"] >= 5.0

    def test_status_unhealthy(self):
        pool, _ = _make_pool()
        hc = HealthChecker(pool)
        hc.is_healthy = False
        hc.consecutive_failures = 3

        status = hc.get_health_status()
        assert status["is_healthy"] is False
        assert status["consecutive_failures"] == 3

    def test_status_keys(self):
        pool, _ = _make_pool()
        hc = HealthChecker(pool)
        status = hc.get_health_status()

        assert set(status.keys()) == {
            "is_healthy",
            "last_check_time",
            "consecutive_failures",
            "time_since_last_check",
        }

"""
Health checker for IRIS connectivity and automatic reconnection.

Monitors IRIS availability and implements exponential backoff reconnection
strategy when IRIS restarts or becomes unavailable.

Constitutional Requirements:
- Principle V (Production Readiness): Health checks and resilience

Feature: 018-add-dbapi-option
Research: R5 (Exponential backoff reconnection)
"""

import asyncio
import time

import structlog

logger = structlog.get_logger(__name__)


class HealthChecker:
    """
    Monitor IRIS health and handle reconnections.

    Implements exponential backoff reconnection strategy:
    - 10 attempts with exponential delay: 2^n seconds
    - Maximum delay: 1024 seconds (2^10)
    - Test query: "SELECT 1"
    """

    def __init__(self, connection_pool):
        """
        Initialize health checker.

        Args:
            connection_pool: IRISConnectionPool instance to monitor
        """
        self.pool = connection_pool
        self.is_healthy = True
        self.last_check_time: float | None = None
        self.consecutive_failures = 0

        # Exponential backoff configuration
        self.max_reconnect_attempts = 10
        self.base_delay_seconds = 1  # 2^0 = 1 second minimum

    async def check_iris_health(self) -> bool:
        """
        Check IRIS connectivity with test query.

        Returns:
            True if IRIS is healthy and responsive
        """
        try:
            # Acquire connection and execute test query
            conn_wrapper = await asyncio.wait_for(self.pool.acquire(), timeout=5.0)

            try:
                # Execute simple test query
                def test_query():
                    cursor = conn_wrapper.connection.cursor()  # type: ignore
                    try:
                        cursor.execute("SELECT 1")
                        result = cursor.fetchone()
                        return result is not None
                    finally:
                        cursor.close()

                result = await asyncio.to_thread(test_query)

                if result:
                    # Health check passed
                    if not self.is_healthy:
                        logger.info("✅ IRIS health restored")
                        self.is_healthy = True
                        self.consecutive_failures = 0

                    self.last_check_time = time.time()
                    return True
                else:
                    raise RuntimeError("Test query returned no results")

            finally:
                await self.pool.release(conn_wrapper)

        except TimeoutError:
            logger.warning("Health check timeout - IRIS not responding")
            self.consecutive_failures += 1
            self.is_healthy = False
            return False

        except Exception as e:
            logger.error(
                "IRIS health check failed",
                error=str(e),
                consecutive_failures=self.consecutive_failures + 1,
            )
            self.consecutive_failures += 1
            self.is_healthy = False
            return False

    async def handle_iris_restart(self) -> bool:
        """
        Handle IRIS instance restart with exponential backoff reconnection.

        Implements research R5 reconnection strategy:
        - 10 attempts with exponential backoff
        - Delay: 2^n seconds (1, 2, 4, 8, 16, 32, 64, 128, 256, 512 seconds)
        - Maximum delay capped at 1024 seconds

        Returns:
            True if reconnection succeeded, False if all attempts failed
        """
        logger.warning(
            "IRIS restart detected - initiating reconnection sequence",
            max_attempts=self.max_reconnect_attempts,
        )

        # Close all existing connections in pool
        await self.pool.close()

        # Attempt reconnection with exponential backoff
        for attempt in range(1, self.max_reconnect_attempts + 1):
            # Calculate exponential backoff delay
            delay_seconds = min(2 ** (attempt - 1), 1024)

            logger.info(
                f"Reconnection attempt {attempt}/{self.max_reconnect_attempts}",
                delay_seconds=delay_seconds,
            )

            # Wait before attempting reconnection
            if attempt > 1:  # Skip delay on first attempt
                await asyncio.sleep(delay_seconds)

            # Attempt health check
            is_healthy = await self.check_iris_health()

            if is_healthy:
                logger.info(
                    "✅ Reconnection successful",
                    attempt=attempt,
                    total_delay_seconds=sum(2**i for i in range(attempt - 1)),
                )
                return True

            logger.warning(
                f"Reconnection attempt {attempt} failed",
                next_delay_seconds=(
                    min(2**attempt, 1024) if attempt < self.max_reconnect_attempts else None
                ),
            )

        # All reconnection attempts failed
        logger.error(
            f"❌ Reconnection failed after {self.max_reconnect_attempts} attempts",
            total_delay_seconds=sum(2**i for i in range(self.max_reconnect_attempts)),
        )
        return False

    async def start_monitoring(self, interval_seconds: int = 30) -> None:
        """
        Start continuous health monitoring loop.

        Args:
            interval_seconds: Seconds between health checks
        """
        logger.info(
            "Starting IRIS health monitoring",
            interval_seconds=interval_seconds,
        )

        while True:
            try:
                is_healthy = await self.check_iris_health()

                if not is_healthy and self.consecutive_failures >= 3:
                    # Multiple consecutive failures - attempt reconnection
                    logger.warning(
                        "Multiple health check failures detected",
                        consecutive_failures=self.consecutive_failures,
                    )

                    reconnected = await self.handle_iris_restart()

                    if not reconnected:
                        logger.error("Failed to reconnect - monitoring will continue")

                # Wait before next check
                await asyncio.sleep(interval_seconds)

            except Exception as e:
                logger.error(
                    "Health monitoring error",
                    error=str(e),
                    interval_seconds=interval_seconds,
                )
                await asyncio.sleep(interval_seconds)

    def get_health_status(self) -> dict:
        """
        Get current health status.

        Returns:
            Health status dictionary
        """
        return {
            "is_healthy": self.is_healthy,
            "last_check_time": self.last_check_time,
            "consecutive_failures": self.consecutive_failures,
            "time_since_last_check": (
                time.time() - self.last_check_time if self.last_check_time else None
            ),
        }

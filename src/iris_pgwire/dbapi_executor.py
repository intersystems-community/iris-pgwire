"""
DBAPI executor for InterSystems IRIS query execution.

Executes SQL queries via intersystems-irispython DBAPI with connection pooling,
vector query support, and performance monitoring.

Constitutional Requirements:
- Principle IV (IRIS Integration): DBAPI backend support
- Principle V (Production Readiness): Connection pooling, health checks, error handling
- Principle VI (Vector Performance): <5ms translation overhead

Feature: 018-add-dbapi-option
Contract: contracts/dbapi-executor-contract.md
"""

import asyncio
import logging
import time
from typing import Any

from iris_pgwire.dbapi_connection_pool import IRISConnectionPool
from iris_pgwire.models.backend_config import BackendConfig
from iris_pgwire.models.connection_pool_state import ConnectionPoolState
from iris_pgwire.models.vector_query_request import VectorQueryRequest

logger = logging.getLogger(__name__)


class DBAPIExecutor:
    """
    Execute SQL queries against IRIS via DBAPI backend.

    Uses connection pool for efficient connection management and supports
    vector similarity queries with pgvector syntax translation.

    Usage:
        config = BackendConfig(backend_type=BackendType.DBAPI, iris_password="SYS")
        executor = DBAPIExecutor(config)
        results = await executor.execute_query("SELECT 1")
        await executor.close()
    """

    backend_type: str = "dbapi"

    def __init__(self, config: BackendConfig):
        """
        Initialize DBAPI executor with connection pool.

        Args:
            config: Backend configuration with DBAPI parameters
        """
        self.config = config
        self.pool = IRISConnectionPool(config)
        self.backend_type = "dbapi"

        # Performance metrics
        self._total_queries = 0
        self._total_query_time_ms = 0.0
        self._total_errors = 0

        logger.info(
            "DBAPI executor initialized",
            extra={
                "backend_type": self.backend_type,
                "hostname": config.iris_hostname,
                "port": config.iris_port,
                "namespace": config.iris_namespace,
                "pool_size": config.pool_size,
            },
        )

    async def execute_query(self, sql: str, params: tuple | None = None) -> list[tuple[Any, ...]]:
        """
        Execute SQL query via DBAPI connection pool.

        Args:
            sql: SQL query string
            params: Optional query parameters (for prepared statements)

        Returns:
            List of result rows as tuples

        Raises:
            ConnectionError: If connection acquisition fails
            Exception: If query execution fails
        """
        start_time = time.perf_counter()
        conn_wrapper = None

        try:
            # Acquire connection from pool
            conn_wrapper = await self.pool.acquire()

            # Execute query in thread pool (DBAPI is synchronous)
            def execute_in_thread():
                cursor = conn_wrapper.connection.cursor()  # type: ignore
                try:
                    # Strip trailing semicolon for IRIS compatibility
                    clean_sql = sql.strip().rstrip(";")
                    if params:
                        cursor.execute(clean_sql, params)
                    else:
                        cursor.execute(clean_sql)

                    # Fetch results if available
                    if cursor.description:
                        results = cursor.fetchall()
                    else:
                        results = []

                    return results
                finally:
                    cursor.close()

            results = await asyncio.to_thread(execute_in_thread)

            # Record metrics
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            self._total_queries += 1
            self._total_query_time_ms += elapsed_ms

            conn_wrapper.record_query_execution(acquisition_time_ms=elapsed_ms, success=True)

            logger.debug(
                "Query executed",
                extra={
                    "sql": sql[:100],
                    "rows_returned": len(results),
                    "elapsed_ms": round(elapsed_ms, 2),
                },
            )

            return results

        except Exception as e:
            error_str = str(e).lower()
            # Mark connection as unhealthy for common connection errors
            connection_lost = any(msg in error_str for msg in [
                "connection lost",
                "not connected",
                "communication link failure",
                "socket error",
                "operationalerror",
                "interfaceerror"
            ])
            
            logger.error(f"Query execution failed: {e}", extra={
                "sql": sql[:200],
                "connection_lost": connection_lost
            })
            self._total_errors += 1

            if conn_wrapper:
                if connection_lost:
                    conn_wrapper.mark_failed(str(e))
                else:
                    conn_wrapper.record_query_execution(acquisition_time_ms=0, success=False)

            raise

        finally:
            # Release connection back to pool
            if conn_wrapper:
                await self.pool.release(conn_wrapper)

    async def execute_many(
        self, sql: str, params_list: list[tuple] | list[list]
    ) -> dict[str, Any]:
        """
        Execute SQL with multiple parameter sets for batch operations.

        Args:
            sql: SQL query string (usually INSERT)
            params_list: List of parameter tuples/lists

        Returns:
            Dict with execution results (rows_affected, execution_time_ms, etc.)
        """
        start_time = time.perf_counter()
        conn_wrapper = None

        try:
            # Acquire connection from pool
            conn_wrapper = await self.pool.acquire()

            # Execute batch in thread pool
            def execute_batch_in_thread():
                cursor = conn_wrapper.connection.cursor()  # type: ignore
                try:
                    # Strip trailing semicolon for IRIS compatibility
                    clean_sql = sql.strip().rstrip(";")

                    # Pre-process parameters (e.g. convert lists to IRIS vector strings)
                    final_params_list = []
                    for p_set in params_list:
                        processed_params = [
                            "[" + ",".join(map(str, p)) + "]" if isinstance(p, list) else p
                            for p in p_set
                        ]
                        final_params_list.append(tuple(processed_params))

                    logger.debug(
                        "Executing executemany()",
                        extra={
                            "sql": clean_sql[:100],
                            "batch_size": len(final_params_list),
                        },
                    )

                    cursor.executemany(clean_sql, final_params_list)
                    rows_affected = (
                        cursor.rowcount if hasattr(cursor, "rowcount") else len(params_list)
                    )
                    return rows_affected
                finally:
                    cursor.close()

            rows_affected = await asyncio.to_thread(execute_batch_in_thread)

            # Record metrics
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            self._total_queries += 1  # Count batch as one "query" for high-level metrics
            self._total_query_time_ms += elapsed_ms

            conn_wrapper.record_query_execution(acquisition_time_ms=elapsed_ms, success=True)

            logger.info(
                "Batch executed successfully",
                extra={
                    "sql": sql[:100],
                    "rows_affected": rows_affected,
                    "elapsed_ms": round(elapsed_ms, 2),
                },
            )

            return {
                "success": True,
                "rows_affected": rows_affected,
                "execution_time_ms": elapsed_ms,
                "batch_size": len(params_list),
                "rows": [],
                "columns": [],
                "_execution_path": "dbapi_executemany",
            }

        except Exception as e:
            error_str = str(e).lower()
            # Mark connection as unhealthy for common connection errors
            connection_lost = any(msg in error_str for msg in [
                "connection lost",
                "not connected",
                "communication link failure",
                "socket error",
                "operationalerror",
                "interfaceerror"
            ])

            logger.error(f"Batch execution failed: {e}", extra={
                "sql": sql[:200],
                "connection_lost": connection_lost
            })
            self._total_errors += 1

            if conn_wrapper:
                if connection_lost:
                    conn_wrapper.mark_failed(str(e))
                else:
                    conn_wrapper.record_query_execution(acquisition_time_ms=0, success=False)

            raise

        finally:
            # Release connection back to pool
            if conn_wrapper:
                await self.pool.release(conn_wrapper)

    async def execute_vector_query(self, request: VectorQueryRequest) -> list[tuple[Any, ...]]:
        """
        Execute vector similarity query using translated SQL.

        Args:
            request: Vector query request with translated IRIS SQL

        Returns:
            List of result rows as tuples

        Raises:
            ValueError: If translation time exceeds 5ms SLA
            Exception: If query execution fails
        """
        # Validate translation SLA
        if request.exceeds_sla():
            logger.warning(
                "Vector translation exceeded 5ms SLA",
                extra={
                    "request_id": request.request_id,
                    "translation_ms": request.translation_time_ms,
                    "operator": request.vector_operator,
                    "dimensions": request.vector_dimensions,
                },
            )

        # Execute translated SQL
        logger.info(
            "Executing vector query",
            extra={
                "request_id": request.request_id,
                "operator": request.vector_operator,
                "dimensions": request.vector_dimensions,
                "translation_ms": request.translation_time_ms,
            },
        )

        results = await self.execute_query(request.translated_sql)

        logger.debug(
            "Vector query completed",
            extra={
                "request_id": request.request_id,
                "rows_returned": len(results),
            },
        )

        return results

    async def health_check(self) -> dict:
        """
        Perform health check on executor and connection pool.

        Returns:
            Health status dict with pool metrics
        """
        try:
            # Get pool state
            pool_state = await self.pool.health_check()

            # Test query to verify IRIS connectivity
            await self.execute_query("SELECT 1")

            # Calculate average query time
            avg_query_ms = (
                self._total_query_time_ms / self._total_queries if self._total_queries > 0 else None
            )

            return {
                "status": "healthy" if pool_state.is_healthy else "unhealthy",
                "backend_type": self.backend_type,
                "pool": pool_state.to_health_check_response()["pool"],
                "performance": {
                    "total_queries": self._total_queries,
                    "total_errors": self._total_errors,
                    "avg_query_ms": round(avg_query_ms, 3) if avg_query_ms else None,
                    "error_rate_percent": (
                        round((self._total_errors / self._total_queries) * 100, 2)
                        if self._total_queries > 0
                        else 0.0
                    ),
                },
                "error": pool_state.degraded_reason if not pool_state.is_healthy else None,
            }

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "unhealthy",
                "backend_type": self.backend_type,
                "error": str(e),
            }

    async def get_pool_state(self) -> ConnectionPoolState:
        """
        Get current connection pool state.

        Returns:
            ConnectionPoolState with current metrics
        """
        return await self.pool.health_check()

    async def close(self) -> None:
        """
        Close executor and shutdown connection pool.

        Gracefully drains active connections before closing.
        """
        logger.info(
            "Closing DBAPI executor",
            extra={
                "total_queries": self._total_queries,
                "total_errors": self._total_errors,
            },
        )

        # Close connection pool
        await self.pool.close()

        logger.info("DBAPI executor closed")

    def avg_query_time_ms(self) -> float | None:
        """
        Calculate average query execution time.

        Returns:
            Average query time in milliseconds, or None if no queries executed
        """
        if self._total_queries == 0:
            return None
        return self._total_query_time_ms / self._total_queries

    def error_rate(self) -> float:
        """
        Calculate query error rate percentage.

        Returns:
            Percentage of queries that failed (0-100)
        """
        if self._total_queries == 0:
            return 0.0
        return (self._total_errors / self._total_queries) * 100

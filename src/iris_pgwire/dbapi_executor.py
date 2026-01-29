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
import re
import time
from typing import Any

import structlog

from iris_pgwire.catalog import CatalogRouter
from iris_pgwire.dbapi_connection_pool import IRISConnectionPool
from iris_pgwire.models.backend_config import BackendConfig
from iris_pgwire.models.connection_pool_state import ConnectionPoolState
from iris_pgwire.models.vector_query_request import VectorQueryRequest
from iris_pgwire.sql_translator import SQLPipeline
from iris_pgwire.sql_translator.parser import get_parser

logger = structlog.get_logger(__name__)


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
        self.session_namespaces = {}
        self.strict_single_connection = config.strict_single_connection

        # SQL components required by protocol
        self.sql_pipeline = SQLPipeline()
        self.sql_translator = self.sql_pipeline.translator
        self.sql_parser = get_parser()
        self.catalog_router = CatalogRouter()

        # Performance metrics
        self._total_queries = 0
        self._total_query_time_ms = 0.0
        self._total_errors = 0

        logger.info(
            "DBAPI executor initialized",
            backend_type=self.backend_type,
            hostname=config.iris_hostname,
            port=config.iris_port,
            namespace=config.iris_namespace,
            pool_size=config.pool_size,
            strict_single_connection=config.strict_single_connection,
        )

    def _translate_placeholders(self, sql: str) -> str:
        """
        Translate PostgreSQL $1, $2 placeholders to DBAPI ? placeholders.
        """
        return re.sub(r"\$\d+", "?", sql)

    async def execute_query(
        self, sql: str, params: tuple | None = None, session_id: str | None = None, **kwargs
    ) -> dict[str, Any]:
        """
        Execute SQL query via DBAPI connection pool.

        Args:
            sql: SQL query string
            params: Optional query parameters (for prepared statements)
            session_id: Optional session identifier
            **kwargs: Additional execution options

        Returns:
            Dict with 'rows' and 'columns' keys
        """
        start_time = time.perf_counter()
        conn_wrapper = None

        try:
            # Feature: Handle catalog emulation shared across all paths
            catalog_result = await self.catalog_router.handle_catalog_query(
                sql, params, session_id, self
            )
            if catalog_result is not None:
                return catalog_result

            # Translate placeholders ($1 -> ?)
            sql = self._translate_placeholders(sql)

            # Acquire connection from pool
            conn_wrapper = await self.pool.acquire()

            # Execute query in thread pool (DBAPI is synchronous)
            def execute_in_thread():
                cursor = conn_wrapper.connection.cursor()  # type: ignore
                try:
                    # Strip trailing semicolon for IRIS compatibility
                    clean_sql = sql.strip().rstrip(";")

                    # Feature 034: Apply per-session namespace if set
                    if session_id and session_id in self.session_namespaces:
                        ns = self.session_namespaces[session_id]
                        # In DBAPI, we switch namespace by executing a command if supported,
                        # but IRIS DBAPI connection is usually fixed to a namespace.
                        # For now, we log it.
                        logger.debug(f"Session {session_id} using namespace {ns}")

                    if params:
                        cursor.execute(clean_sql, params)
                    else:
                        cursor.execute(clean_sql)

                    # Fetch results if available
                    rows = []
                    columns = []
                    if cursor.description:
                        rows = cursor.fetchall()
                        for desc in cursor.description:
                            columns.append(
                                {
                                    "name": desc[0],
                                    "type_oid": self._map_dbapi_type_to_oid(desc[1]),
                                    "type_size": desc[2] if len(desc) > 2 else -1,
                                    "format_code": 0,
                                }
                            )

                    row_count = cursor.rowcount if hasattr(cursor, "rowcount") else len(rows)
                    if row_count < 0:
                        row_count = len(rows)

                    return rows, columns, row_count
                finally:
                    cursor.close()

            rows, columns, row_count = await asyncio.to_thread(execute_in_thread)

            # Record metrics
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            self._total_queries += 1
            self._total_query_time_ms += elapsed_ms

            conn_wrapper.record_query_execution(acquisition_time_ms=elapsed_ms, success=True)

            logger.debug(
                "Query executed",
                sql=sql[:100],
                rows_returned=len(rows),
                elapsed_ms=round(elapsed_ms, 2),
            )

            return {
                "success": True,
                "rows": rows,
                "columns": columns,
                "row_count": row_count,
                "command_tag": self._determine_command_tag(sql, row_count),
                "execution_time_ms": elapsed_ms,
            }

        except Exception as e:
            error_str = str(e).lower()
            # Mark connection as unhealthy for common connection errors
            connection_lost = any(
                msg in error_str
                for msg in [
                    "connection lost",
                    "not connected",
                    "communication link failure",
                    "socket error",
                    "operationalerror",
                    "interfaceerror",
                ]
            )

            logger.error(
                f"Query execution failed: {e}",
                sql=sql[:200],
                connection_lost=connection_lost,
            )
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
        self, sql: str, params_list: list[tuple] | list[list], session_id: str | None = None
    ) -> dict[str, Any]:
        """
        Execute SQL with multiple parameter sets for batch operations.

        Args:
            sql: SQL query string (usually INSERT)
            params_list: List of parameter tuples/lists
            session_id: Optional session identifier

        Returns:
            Dict with execution results (rows_affected, execution_time_ms, etc.)
        """
        start_time = time.perf_counter()
        conn_wrapper = None

        try:
            # Translate placeholders ($1 -> ?)
            sql = self._translate_placeholders(sql)

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
                        sql=clean_sql[:100],
                        batch_size=len(final_params_list),
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
                sql=sql[:100],
                rows_affected=rows_affected,
                elapsed_ms=round(elapsed_ms, 2),
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
            connection_lost = any(
                msg in error_str
                for msg in [
                    "connection lost",
                    "not connected",
                    "communication link failure",
                    "socket error",
                    "operationalerror",
                    "interfaceerror",
                ]
            )

            logger.error(
                f"Batch execution failed: {e}",
                sql=sql[:200],
                connection_lost=connection_lost,
            )
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

    async def test_connection(self):
        """Test IRIS connectivity by acquiring and releasing a connection."""
        conn_wrapper = await self.pool.acquire()
        try:

            def test_query():
                cursor = conn_wrapper.connection.cursor()
                cursor.execute("SELECT 1")
                cursor.close()

            await asyncio.to_thread(test_query)
        finally:
            await self.pool.release(conn_wrapper)

    def set_session_namespace(self, session_id: str, namespace: str):
        """Set the IRIS namespace for a specific session."""
        self.session_namespaces[session_id] = namespace

    def close_session(self, session_id: str):
        """Close resources for a specific session."""
        if session_id in self.session_namespaces:
            del self.session_namespaces[session_id]

    async def begin_transaction(self, session_id: str | None = None):
        """Begin a transaction."""
        await self.execute_query("START TRANSACTION", session_id=session_id)

    async def commit_transaction(self, session_id: str | None = None):
        """Commit a transaction."""
        await self.execute_query("COMMIT", session_id=session_id)

    async def rollback_transaction(self, session_id: str | None = None):
        """Rollback a transaction."""
        await self.execute_query("ROLLBACK", session_id=session_id)

    async def cancel_query(self, backend_pid: int, backend_secret: int) -> bool:
        """Cancel a running query (DBAPI implementation)."""
        # For external connections, we might need server reference to terminate connection
        logger.warning(f"cancel_query not fully implemented for DBAPI (pid={backend_pid})")
        return False

    def get_iris_type_mapping(self) -> dict[str, dict[str, Any]]:
        """Get IRIS to PostgreSQL type mappings."""
        return {
            "BIGINT": {"oid": 20, "typname": "int8", "typlen": 8},
            "BIT": {"oid": 1560, "typname": "bit", "typlen": -1},
            "BOOLEAN": {"oid": 16, "typname": "bool", "typlen": 1},
            "CHAR": {"oid": 1042, "typname": "bpchar", "typlen": -1},
            "DATE": {"oid": 1082, "typname": "date", "typlen": 4},
            "DOUBLE": {"oid": 701, "typname": "float8", "typlen": 8},
            "FLOAT": {"oid": 701, "typname": "float8", "typlen": 8},
            "INTEGER": {"oid": 23, "typname": "int4", "typlen": 4},
            "NUMERIC": {"oid": 1700, "typname": "numeric", "typlen": -1},
            "SMALLINT": {"oid": 21, "typname": "int2", "typlen": 2},
            "TEXT": {"oid": 25, "typname": "text", "typlen": -1},
            "TIME": {"oid": 1083, "typname": "time", "typlen": 8},
            "TIMESTAMP": {"oid": 1114, "typname": "timestamp", "typlen": 8},
            "VARCHAR": {"oid": 1043, "typname": "varchar", "typlen": -1},
        }

    def has_returning_clause(self, query: str) -> bool:
        """Check if query has a RETURNING clause."""
        if not query:
            return False
        return bool(re.search(r"\bRETURNING\b", query, re.IGNORECASE | re.DOTALL))

    def get_returning_columns(self, query: str) -> list[str]:
        """Extract column names from RETURNING clause."""
        match = re.search(r"RETURNING\s+(.+)$", query, re.IGNORECASE | re.DOTALL)
        if not match:
            return []
        cols_str = match.group(1).strip()
        if cols_str == "*":
            return ["*"]
        return [c.strip() for c in cols_str.split(",")]

    def _map_dbapi_type_to_oid(self, dbapi_type: Any) -> int:
        """Map DBAPI type to PostgreSQL OID."""
        # Simple mapping for now, can be expanded
        type_str = str(dbapi_type).upper()
        if "INT" in type_str:
            return 23
        if "CHAR" in type_str or "STRING" in type_str:
            return 1043
        if "DATE" in type_str:
            return 1082
        if "TIME" in type_str:
            return 1114
        return 1043  # Default to VARCHAR

    def _determine_command_tag(self, sql: str, row_count: int) -> str:
        """Determine PostgreSQL command tag from SQL"""
        sql_clean = sql.strip().upper()
        if not sql_clean:
            return "UNKNOWN"
        first_word = sql_clean.split()[0] if sql_clean.split() else ""
        if first_word == "SELECT":
            return "SELECT"
        elif first_word == "INSERT":
            return f"INSERT 0 {row_count}"
        elif first_word == "UPDATE":
            return f"UPDATE {row_count}"
        elif first_word == "DELETE":
            return f"DELETE {row_count}"
        else:
            return first_word

    async def execute_vector_query(self, request: VectorQueryRequest) -> dict[str, Any]:
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
                request_id=request.request_id,
                translation_ms=request.translation_time_ms,
                operator=request.vector_operator,
                dimensions=request.vector_dimensions,
            )

        # Execute translated SQL
        logger.info(
            "Executing vector query",
            request_id=request.request_id,
            operator=request.vector_operator,
            dimensions=request.vector_dimensions,
            translation_ms=request.translation_time_ms,
        )

        results = await self.execute_query(request.translated_sql)

        logger.debug(
            "Vector query completed",
            request_id=request.request_id,
            rows_returned=len(results.get("rows", [])),
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
            total_queries=self._total_queries,
            total_errors=self._total_errors,
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

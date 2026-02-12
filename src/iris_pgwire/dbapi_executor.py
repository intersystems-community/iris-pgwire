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
import datetime as dt
import re
import time
from typing import Any

import structlog

from iris_pgwire.catalog import CatalogRouter
from iris_pgwire.dbapi_connection_pool import IRISConnectionPool
from iris_pgwire.models.backend_config import BackendConfig
from iris_pgwire.models.connection_pool_state import ConnectionPoolState
from iris_pgwire.models.vector_query_request import VectorQueryRequest
from iris_pgwire.schema_mapper import IRIS_SCHEMA
from iris_pgwire.sql_translator import SQLPipeline
from iris_pgwire.sql_translator.parser import get_parser
from iris_pgwire.sql_translator.returning_plan import ReturningPlan

logger = structlog.get_logger(__name__)


class MockResult:
    """Mock result object for RETURNING emulation"""

    def __init__(self, rows, meta=None):
        self._rows = rows if rows is not None else []
        self._meta = meta
        self.description = meta
        self.rowcount = len(self._rows)
        self._index = 0

    def __iter__(self):
        return iter(self._rows)

    def fetchall(self):
        return self._rows

    def fetchone(self):
        if self._index < len(self._rows):
            row = self._rows[self._index]
            self._index += 1
            return row
        return None

    def fetch(self):
        return self._rows

    def close(self):
        pass


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
        self.session_connections = {}
        self.strict_single_connection = config.strict_single_connection
        self.session_transactions: dict[str, bool] = {}

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

    def _convert_params_for_iris(self, params: Any) -> Any:
        """
        Convert parameters to IRIS-compatible formats.
        Specifically handles ISO 8601 timestamps.
        """
        if params is None:
            return None

        if isinstance(params, list | tuple):
            return [self._convert_value_for_iris(v) for v in params]

        return self._convert_value_for_iris(params)

    def _convert_value_for_iris(self, value: Any) -> Any:
        """Helper to convert a single value."""
        if isinstance(value, str):
            # Check for ISO 8601 timestamp: 2026-01-29T21:27:38.111Z
            # or 2026-01-29T21:27:38.111+00:00
            # IRIS rejects the 'T' and 'Z' or offset in %PosixTime/TIMESTAMP
            ts_match = re.match(
                r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2}(?:\.\d+)?)(?:Z|[+-]\d{2}:?(\d{2})?)?$",
                value,
            )
            if ts_match:
                return f"{ts_match.group(1)} {ts_match.group(2)}"
        return value

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
        release_connection = True
        pinned_connection = False
        original_sql = sql

        try:
            catalog_result = await self.catalog_router.handle_catalog_query(
                sql, params, session_id, self
            )
            if catalog_result is not None:
                return catalog_result

            sql = self._translate_placeholders(sql)
            plan = ReturningPlan.from_sql(sql)
            converted_params = self._convert_params_for_iris(params)

            conn_wrapper, pinned_connection = await self._acquire_connection(session_id)
            release_connection = not pinned_connection

            def execute_in_thread():
                if session_id and session_id in self.session_namespaces:
                    ns = self.session_namespaces[session_id]
                    logger.debug(f"Session {session_id} using namespace {ns}")

                return self._execute_statement_sync(
                    conn_wrapper.connection,
                    plan,
                    converted_params,
                    session_id,
                    original_sql,
                )

            rows, columns, row_count = await asyncio.to_thread(execute_in_thread)

            tx_sql_upper = original_sql.strip().upper()
            self._update_transaction_state(session_id, tx_sql_upper)
            self._maybe_auto_commit(conn_wrapper.connection, session_id, tx_sql_upper)

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
                    if session_id:
                        self.session_connections.pop(session_id, None)
                        self.session_transactions.pop(session_id, None)
                    release_connection = True
                else:
                    conn_wrapper.record_query_execution(acquisition_time_ms=0, success=False)

            raise

        finally:
            if conn_wrapper and release_connection:
                await self.pool.release(conn_wrapper)

    async def execute_many(
        self, sql: str, params_list: list[tuple] | list[list], session_id: str | None = None
    ) -> dict[str, Any]:
        """
        Execute SQL with multiple parameter sets for batch operations.

        RETURNING SUPPORT: When SQL contains RETURNING clause, executes each statement
        individually and aggregates the returned rows.
        """
        start_time = time.perf_counter()
        conn_wrapper = None
        release_connection = True
        pinned_connection = False
        original_sql = sql

        try:
            sql = self._translate_placeholders(sql)
            plan = ReturningPlan.from_sql(sql)

            conn_wrapper, pinned_connection = await self._acquire_connection(session_id)
            release_connection = not pinned_connection

            all_rows: list[Any] = []
            columns_info: list[dict[str, Any]] = []
            rows_affected = 0

            for params in params_list:
                converted_params = self._convert_params_for_iris(params)
                rows, columns, row_count = await asyncio.to_thread(
                    self._execute_statement_sync,
                    conn_wrapper.connection,
                    plan,
                    converted_params,
                    session_id,
                    original_sql,
                )

                if rows:
                    all_rows.extend(rows)
                if columns and not columns_info:
                    columns_info = columns
                rows_affected += row_count

                tx_sql_upper = original_sql.strip().upper()
                self._update_transaction_state(session_id, tx_sql_upper)
                self._maybe_auto_commit(conn_wrapper.connection, session_id, tx_sql_upper)

            elapsed_ms = (time.perf_counter() - start_time) * 1000
            self._total_queries += 1
            self._total_query_time_ms += elapsed_ms

            conn_wrapper.record_query_execution(acquisition_time_ms=elapsed_ms, success=True)

            execution_path = (
                "dbapi_executemany_returning" if plan.has_returning else "dbapi_executemany"
            )

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
                "rows": all_rows,
                "columns": columns_info,
                "_execution_path": execution_path,
            }

        except Exception as e:
            error_str = str(e).lower()
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
                    if session_id:
                        self.session_connections.pop(session_id, None)
                        self.session_transactions.pop(session_id, None)
                    release_connection = True
                else:
                    conn_wrapper.record_query_execution(acquisition_time_ms=0, success=False)

            raise

        finally:
            if conn_wrapper and release_connection:
                await self.pool.release(conn_wrapper)

    async def _acquire_connection(self, session_id: str | None) -> tuple[Any, bool]:
        if session_id and session_id in self.session_connections:
            return self.session_connections[session_id], True

        conn_wrapper = await self.pool.acquire()
        if session_id:
            self.session_connections[session_id] = conn_wrapper
        return conn_wrapper, bool(session_id)

    def _update_transaction_state(self, session_id: str | None, sql_upper: str | None) -> None:
        if not session_id or not sql_upper:
            return
        normalized = sql_upper.strip().upper()
        if normalized.startswith("START TRANSACTION") or normalized.startswith("BEGIN"):
            self.session_transactions[session_id] = True
        elif (
            normalized.startswith("COMMIT")
            or normalized.startswith("ROLLBACK")
            or normalized.startswith("END")
        ):
            self.session_transactions.pop(session_id, None)

    def _is_transaction_control_sql(self, sql_upper: str | None) -> bool:
        if not sql_upper:
            return False
        normalized = sql_upper.strip().upper()
        return any(
            normalized.startswith(keyword)
            for keyword in ("BEGIN", "START TRANSACTION", "COMMIT", "ROLLBACK", "END")
        )

    def _maybe_auto_commit(
        self, connection: Any, session_id: str | None, sql_upper: str | None
    ) -> None:
        if not connection or not sql_upper:
            return
        if self._is_transaction_control_sql(sql_upper):
            return
        if session_id and self.session_transactions.get(session_id):
            return
        try:
            connection.commit()
        except Exception as commit_error:  # pragma: no cover - best effort
            logger.warning("Auto-commit failed", error=str(commit_error), session_id=session_id)

    def _execute_statement_sync(
        self,
        connection: Any,
        plan: ReturningPlan,
        params: list | tuple | None,
        session_id: str | None,
        original_sql: str | None,
    ) -> tuple[list[Any], list[dict[str, Any]], int]:
        cursor = connection.cursor()
        try:
            cleaned_sql = plan.stripped_sql.strip().rstrip(";")
            execute_params = tuple(params) if params else None

            delete_rows: list[Any] = []
            delete_meta: list[dict[str, Any]] | None = None
            if plan.operation == "DELETE" and plan.has_returning:
                delete_rows, delete_meta = self._emulate_returning_sync(
                    connection,
                    plan,
                    params,
                    session_id=session_id,
                    original_sql=original_sql,
                    override_operation="DELETE",
                    override_where=plan.where_clause,
                    override_where_params=self._extract_where_params(plan.where_clause, params),
                )

            try:
                if execute_params:
                    cursor.execute(cleaned_sql, execute_params)
                else:
                    cursor.execute(cleaned_sql)
            except Exception as exc:
                if plan.conflict_action == "DO NOTHING" and self._is_unique_violation(exc):
                    return [], [], 0
                if plan.conflict_action == "DO UPDATE" and self._is_unique_violation(exc):
                    rows, columns = self._handle_on_conflict_update(
                        plan, params, connection, session_id, original_sql
                    )
                    return rows, columns or [], len(rows)
                raise

            rows: list[Any] = []
            columns: list[dict[str, Any]] = []
            row_count = (
                cursor.rowcount if getattr(cursor, "rowcount", -1) and cursor.rowcount >= 0 else 0
            )

            if plan.has_returning:
                if plan.operation == "DELETE":
                    rows, columns = delete_rows, delete_meta or []
                    row_count = len(rows)
                else:
                    rows, columns = self._emulate_returning_sync(
                        connection,
                        plan,
                        params,
                        session_id=session_id,
                        original_sql=original_sql,
                    )
                    row_count = len(rows)
            else:
                if cursor.description:
                    rows = cursor.fetchall()
                    columns = self._build_metadata_from_description(cursor.description)
                row_count = max(row_count, len(rows))

            return rows, columns, row_count
        finally:
            try:
                cursor.close()
            except Exception:
                pass

    def _handle_on_conflict_update(
        self,
        plan: ReturningPlan,
        params: list | tuple | None,
        connection: Any,
        session_id: str | None,
        original_sql: str | None,
    ) -> tuple[list[Any], list[dict[str, Any]] | None]:
        if not plan.table:
            raise RuntimeError("Cannot emulate ON CONFLICT without target table")
        if not plan.conflict_set_clause or not plan.conflict_target_columns:
            raise RuntimeError("ON CONFLICT DO UPDATE clause is incomplete")

        column_values = self._map_insert_column_values(plan, params)
        set_clause, set_params = self._prepare_conflict_set_clause(plan, column_values)
        where_clause, where_params = self._prepare_conflict_where_clause(plan, column_values)

        if not set_clause or not where_clause:
            raise RuntimeError("Insufficient data to build ON CONFLICT UPDATE")

        update_sql = f'UPDATE {IRIS_SCHEMA}."{plan.table}" SET {set_clause} WHERE {where_clause}'
        cursor = connection.cursor()
        try:
            cursor.execute(update_sql, tuple(set_params + where_params))
        finally:
            try:
                cursor.close()
            except Exception:
                pass

        rows, columns = self._emulate_returning_sync(
            connection,
            plan,
            where_params,
            session_id=session_id,
            original_sql=original_sql,
            override_operation="UPDATE",
            override_where=where_clause,
            override_where_params=where_params,
        )
        return rows, columns

    def _is_unique_violation(self, error: Exception) -> bool:
        message = str(error).lower()
        return any(keyword in message for keyword in ("unique", "duplicate", "constraint"))

    def _map_insert_column_values(
        self, plan: ReturningPlan, params: list | tuple | None
    ) -> dict[str, Any]:
        values: dict[str, Any] = {}
        if not params or not plan.insert_columns:
            return values
        for idx, column in enumerate(plan.insert_columns):
            if idx < len(params):
                values[column.lower()] = params[idx]
        return values

    def _prepare_conflict_set_clause(
        self, plan: ReturningPlan, column_values: dict[str, Any]
    ) -> tuple[str, list[Any]]:
        if not plan.conflict_set_clause:
            return "", []
        params: list[Any] = []
        pattern = re.compile(r"\bEXCLUDED\.\"?(\w+)\"?", re.IGNORECASE)

        def _replace(match: re.Match) -> str:
            column = match.group(1).lower()
            params.append(column_values.get(column))
            return "?"

        set_clause = pattern.sub(_replace, plan.conflict_set_clause)
        return set_clause, params

    def _prepare_conflict_where_clause(
        self, plan: ReturningPlan, column_values: dict[str, Any]
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        for column in plan.conflict_target_columns:
            identifier = column.upper()
            clauses.append(f'"{identifier}" = ?')
            params.append(column_values.get(column.lower()))

        where_clause = " AND ".join(clauses)
        if plan.conflict_where_clause:
            if where_clause:
                where_clause = f"{where_clause} AND {plan.conflict_where_clause}"
            else:
                where_clause = plan.conflict_where_clause
        return where_clause, params

    def _extract_where_params(
        self, where_clause: str | None, params: list | tuple | None
    ) -> list[Any]:
        if not where_clause or not params:
            return []
        count = where_clause.count("?")
        if count == 0:
            return []
        values = list(params)
        return values[-count:] if len(values) >= count else values

    def _translate_schema_references(self, clause: str) -> str:
        translated = re.sub(
            r'"public"\s*\.\s*"(\w+)"',
            rf'{IRIS_SCHEMA}."\1"',
            clause,
            flags=re.IGNORECASE,
        )
        translated = re.sub(
            r'\bpublic\s*\.\s*"(\w+)"',
            rf'{IRIS_SCHEMA}."\1"',
            translated,
            flags=re.IGNORECASE,
        )
        return translated

    def _get_primary_key_columns(self, table: str, connection: Any) -> list[str]:
        if not table or not connection:
            return []
        cursor = connection.cursor()
        try:
            metadata_sql = f"""
                SELECT k.COLUMN_NAME
                FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE k
                JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS t
                    ON k.CONSTRAINT_NAME = t.CONSTRAINT_NAME
                WHERE LOWER(t.TABLE_NAME) = LOWER('{table}')
                AND LOWER(t.TABLE_SCHEMA) = LOWER('{IRIS_SCHEMA}')
                AND t.CONSTRAINT_TYPE = 'PRIMARY KEY'
                ORDER BY k.ORDINAL_POSITION
            """
            cursor.execute(metadata_sql)
            rows = cursor.fetchall()
            return [row[0] for row in rows]
        except Exception as e:
            logger.debug("Failed to fetch primary key columns", table=table, error=str(e))
        finally:
            try:
                cursor.close()
            except Exception:
                pass
        return []

    def _fetch_last_identity(self, connection: Any) -> Any | None:
        if not connection:
            return None
        cursor = connection.cursor()
        try:
            cursor.execute("SELECT LAST_IDENTITY()")
            row = cursor.fetchone()
            return row[0] if row else None
        except Exception as e:
            logger.debug("LAST_IDENTITY() failed", error=str(e))
            return None
        finally:
            try:
                cursor.close()
            except Exception:
                pass

    def _build_metadata_from_description(self, description: Any) -> list[dict[str, Any]]:
        columns: list[dict[str, Any]] = []
        if not description:
            return columns
        for desc in description:
            if not desc:
                continue
            name = desc[0]
            type_oid = self._map_dbapi_type_to_oid(desc[1]) if len(desc) > 1 else 1043
            size = desc[2] if len(desc) > 2 else -1
            columns.append(
                {
                    "name": name,
                    "type_oid": type_oid,
                    "type_size": size,
                    "format_code": 0,
                }
            )
        return columns

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

    async def close_session(self, session_id: str):
        """Close resources for a specific session."""
        conn_wrapper = self.session_connections.pop(session_id, None)
        if conn_wrapper:
            logger.info("Closing session connection", session_id=session_id)
            await self.pool.release(conn_wrapper)
        if session_id in self.session_namespaces:
            del self.session_namespaces[session_id]
        self.session_transactions.pop(session_id, None)

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
        """
        Check if query has a RETURNING clause.
        """
        if not query:
            return False
        return bool(re.search(r"\bRETURNING\b", query, re.IGNORECASE | re.DOTALL))

    def get_returning_columns(self, query: str) -> list[str]:
        """
        Extract column names from RETURNING clause.
        """
        match = re.search(r"RETURNING\s+(.+?)(?=$|;)", query, re.IGNORECASE | re.DOTALL)
        if not match:
            return []
        cols_str = match.group(1).strip()
        if cols_str == "*":
            return ["*"]
        return [c.strip() for c in cols_str.split(",")]

    def _get_table_columns_from_schema(self, table: str, cursor=None) -> list[str]:
        """
        Query INFORMATION_SCHEMA.COLUMNS for the given table.
        Returns the list of column names in order.
        """
        if self.strict_single_connection or cursor is None:
            return []
        try:
            table_clean = table.strip('"').strip("'")
            metadata_sql = f"""
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE LOWER(TABLE_NAME) = LOWER('{table_clean}')
                AND LOWER(TABLE_SCHEMA) = LOWER('{IRIS_SCHEMA}')
                ORDER BY ORDINAL_POSITION
            """
            cursor.execute(metadata_sql)
            rows = cursor.fetchall()
            return [row[0] for row in rows]
        except Exception as e:
            logger.debug(f"Failed to get columns from schema for {table}: {e}")
        return []

    def _get_column_type_from_schema(self, table: str, column: str, cursor=None) -> int | None:
        """
        Query INFORMATION_SCHEMA.COLUMNS for the given table and column.
        Returns the PostgreSQL type OID.
        """
        if self.strict_single_connection or cursor is None:
            return None
        try:
            table_clean = table.strip('"').strip("'")
            column_clean = column.strip('"').strip("'")
            metadata_sql = f"""
                SELECT DATA_TYPE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE LOWER(TABLE_NAME) = LOWER('{table_clean}')
                AND LOWER(COLUMN_NAME) = LOWER('{column_clean}')
                AND LOWER(TABLE_SCHEMA) = LOWER('{IRIS_SCHEMA}')
            """
            cursor.execute(metadata_sql)
            row = cursor.fetchone()
            if row:
                iris_type = row[0]
                return self._map_iris_type_to_oid(iris_type)
        except Exception as e:
            logger.debug(f"Failed to get type from schema for {table}.{column}: {e}")
        return None

    def _infer_type_from_value(self, value, column_name: str | None = None) -> int:
        """
        Infer PostgreSQL type OID from Python value
        """
        from decimal import Decimal

        if value is None:
            return 1043  # VARCHAR
        elif isinstance(value, bool):
            return 16  # BOOL
        elif isinstance(value, int):
            if column_name and any(k in column_name.lower() for k in ("id", "key")):
                return 20  # BIGINT
            return 23  # INTEGER
        elif isinstance(value, float):
            return 701  # FLOAT8
        elif isinstance(value, Decimal):
            return 1700  # NUMERIC
        elif isinstance(value, dt.datetime):
            return 1114
        elif isinstance(value, dt.date):
            return 1082
        elif isinstance(value, str):
            return 1043  # VARCHAR
        else:
            return 1043

    def _serialize_value(self, value: Any, type_oid: int) -> Any:
        """
        Robust value serialization for PostgreSQL wire protocol compatibility.
        """
        if value is None:
            return None

        if type_oid == 1114:  # TIMESTAMP
            if isinstance(value, dt.datetime):
                return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
            elif isinstance(value, str):
                return value  # Already a string

        return value

    def _parse_returning_clause(
        self, sql: str
    ) -> tuple[str | None, str | None, Any, str | None, str]:
        """
        Parse RETURNING clause from SQL and return metadata.
        Returns: (operation, table, columns, where_clause, stripped_sql)
        """
        returning_operation = None
        returning_table = None
        returning_columns = None
        returning_where_clause = None

        returning_pattern = r"\s+RETURNING\s+(.*?)($|;)"
        returning_match = re.search(returning_pattern, sql, re.IGNORECASE | re.DOTALL)

        if not returning_match:
            return None, None, None, None, sql

        returning_clause = returning_match.group(1).strip()

        if returning_clause == "*":
            returning_columns = "*"
        else:
            # Better column parsing that preserves expressions and aliases
            # Split by commas but respect parentheses
            returning_columns = []
            current_col = ""
            depth = 0
            for char in returning_clause:
                if char == "(":
                    depth += 1
                elif char == ")":
                    depth -= 1

                if char == "," and depth == 0:
                    col = current_col.strip()
                    # Extract last part of identifier if it's schema-qualified
                    # e.g. public.users.id -> id, or "public"."users"."id" -> id
                    col_match = re.search(r'"?(\w+)"?\s*$', col)
                    if col_match:
                        returning_columns.append(col_match.group(1).lower())
                    else:
                        returning_columns.append(col.lower())
                    current_col = ""
                else:
                    current_col += char
            if current_col.strip():
                col = current_col.strip()
                col_match = re.search(r'"?(\w+)"?\s*$', col)
                if col_match:
                    returning_columns.append(col_match.group(1).lower())
                else:
                    returning_columns.append(col.lower())

        sql_upper = sql.upper().strip()
        # Robust table extraction regex for all operations
        table_regex = r'(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?:(?:"?\w+"?)\s*\.\s*)*"?(\w+)"?'
        table_match = re.search(table_regex, sql, re.IGNORECASE)
        if table_match:
            returning_table = table_match.group(1).upper()

        if sql_upper.startswith("INSERT"):
            returning_operation = "INSERT"
        elif sql_upper.startswith("UPDATE"):
            returning_operation = "UPDATE"
            where_match = re.search(
                r"\bWHERE\s+(.+?)\s+RETURNING\b",
                sql,
                re.IGNORECASE | re.DOTALL,
            )
            if where_match:
                returning_where_clause = where_match.group(1).strip()
        elif sql_upper.startswith("DELETE"):
            returning_operation = "DELETE"
            where_match = re.search(
                r"\bWHERE\s+(.+?)\s+RETURNING\b",
                sql,
                re.IGNORECASE | re.DOTALL,
            )
            if where_match:
                returning_where_clause = where_match.group(1).strip()

        stripped_sql = re.sub(
            r"\s+RETURNING\s+.*?(?=$|;)",
            "",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
            count=1,
        )

        return (
            returning_operation,
            returning_table,
            returning_columns,
            returning_where_clause,
            stripped_sql,
        )

    def _expand_select_star(self, sql: str, expected_columns: int, cursor=None) -> list[str] | None:
        """
        Expand SELECT * or RETURNING * into explicit column names using INFORMATION_SCHEMA.
        """
        try:
            table_name = None
            sql_upper = sql.upper()

            if "RETURNING" in sql_upper:
                table_regex = (
                    r'(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?:(?:"?\w+"?)\s*\.\s*)*"?(\w+)"?'
                )
                table_match = re.search(table_regex, sql, re.IGNORECASE)
                if table_match:
                    table_name = table_match.group(1)
            else:
                from_match = re.search(r"FROM\s+([^\s,;()]+)", sql, re.IGNORECASE)
                if from_match:
                    table_name = from_match.group(1)

            if table_name:
                if "." in table_name:
                    table_name = table_name.split(".")[-1]
                table_name = table_name.strip('"').strip("'")

                schema_columns = self._get_table_columns_from_schema(table_name, cursor)
                if schema_columns:
                    if expected_columns == 0 or len(schema_columns) == expected_columns:
                        return schema_columns
            return None
        except Exception as e:
            logger.debug(f"Failed to expand SELECT *: {e}")
            return None

    def _extract_insert_id_from_sql(
        self, sql: str, params: list | None, session_id: str | None = None
    ) -> tuple[str | None, Any]:
        """
        Extract the ID value from an INSERT statement.
        """
        col_match = re.search(r"INSERT\s+INTO\s+[^\s(]+\s*\(\s*([^)]+)\s*\)", sql, re.IGNORECASE)
        if not col_match:
            return None, None

        columns_str = col_match.group(1)
        columns = [c.strip().strip('"').strip("'").lower() for c in columns_str.split(",")]

        id_col_names = ["id", "uuid", "_id"]
        id_col_idx = None
        id_col_name = None
        for i, col in enumerate(columns):
            if col in id_col_names:
                id_col_idx = i
                id_col_name = col
                break

        if id_col_idx is None:
            return None, None

        if params and len(params) > id_col_idx:
            return id_col_name, params[id_col_idx]

        return None, None

    def _emulate_returning_sync(
        self,
        connection: Any,
        plan: ReturningPlan,
        params: list | tuple | None,
        session_id: str | None = None,
        original_sql: str | None = None,
        override_operation: str | None = None,
        override_where: str | None = None,
        override_where_params: list[Any] | None = None,
    ) -> tuple[list[Any], list[dict[str, Any]]]:
        operation = override_operation or plan.operation
        table = plan.table
        table_normalized = table.upper() if table else None
        if not table_normalized:
            return [], []
        columns = plan.columns or ["*"]
        col_list = "*"

        if columns == "*":
            meta_cursor = connection.cursor()
            try:
                expanded_cols = self._get_table_columns_from_schema(table_normalized, meta_cursor)
            finally:
                try:
                    meta_cursor.close()
                except Exception:
                    pass
            if expanded_cols:
                columns = expanded_cols
                col_list = ", ".join(f'"{col}"' for col in expanded_cols)
            else:
                col_list = "*"
        else:
            if plan.column_meta:
                col_list = plan.select_list
            else:
                processed: list[str] = []
                for col in columns:
                    if re.match(r'^"?\w+"?$', col):
                        stripped_col = col.strip('"')
                        processed.append(f'"{stripped_col}"')
                    else:
                        processed.append(col)
                col_list = ", ".join(processed)

        rows: list[Any] = []
        metadata: list[dict[str, Any]] | None = None
        param_values = list(params) if params else []

        def _fetch_rows(
            query: str, query_params: list[Any] | None = None
        ) -> tuple[list[Any], list[dict[str, Any]]]:
            cur = connection.cursor()
            try:
                if query_params:
                    cur.execute(query, tuple(query_params))
                else:
                    cur.execute(query)
                fetched = cur.fetchall()
                return fetched, self._build_metadata_from_description(cur.description)
            finally:
                try:
                    cur.close()
                except Exception:
                    pass

        try:
            if operation == "INSERT":
                last_identity = self._fetch_last_identity(connection)
                if last_identity is not None:
                    rows, metadata = _fetch_rows(
                        f'SELECT {col_list} FROM {IRIS_SCHEMA}."{table_normalized}" WHERE %ID = ?',
                        [last_identity],
                    )

                if not rows and original_sql:
                    id_col, id_value = self._extract_insert_id_from_sql(
                        original_sql, param_values, session_id
                    )
                    if id_col and id_value is not None:
                        rows, metadata = _fetch_rows(
                            f'SELECT {col_list} FROM {IRIS_SCHEMA}."{table_normalized}" WHERE "{id_col}" = ?',
                            [id_value],
                        )

                if not rows:
                    column_values = self._map_insert_column_values(plan, param_values)
                    pk_columns = self._get_primary_key_columns(table_normalized, connection)
                    if pk_columns:
                        where_parts: list[str] = []
                        where_params: list[Any] = []
                        for pk in pk_columns:
                            where_parts.append(f'"{pk.upper()}" = ?')
                            where_params.append(column_values.get(pk.lower()))
                        if all(val is not None for val in where_params):
                            rows, metadata = _fetch_rows(
                                f'SELECT {col_list} FROM {IRIS_SCHEMA}."{table_normalized}" WHERE {" AND ".join(where_parts)}',
                                where_params,
                            )

                if not rows:
                    logger.warning(
                        "RETURNING fallback: TOP 1 lookup",
                        table=table_normalized,
                    )
                    rows, metadata = _fetch_rows(
                        f'SELECT TOP 1 {col_list} FROM {IRIS_SCHEMA}."{table_normalized}" ORDER BY %ID DESC'
                    )

            elif operation in ("UPDATE", "DELETE"):
                where_clause = override_where or plan.where_clause
                if where_clause:
                    translated_where = self._translate_schema_references(where_clause)
                    where_params = (
                        override_where_params
                        if override_where_params is not None
                        else self._extract_where_params(where_clause, param_values)
                    )
                    rows, metadata = _fetch_rows(
                        f'SELECT {col_list} FROM {IRIS_SCHEMA}."{table_normalized}" WHERE {translated_where}',
                        where_params or None,
                    )

        except Exception as exc:  # pragma: no cover - best effort logging
            logger.error(
                f"RETURNING emulation failed for {operation}",
                table=table_normalized,
                error=str(exc),
            )

        if metadata is None:
            metadata = []
            cursor = connection.cursor()
            try:
                if plan.column_meta:
                    for idx, col_meta in enumerate(plan.column_meta):
                        col_name = col_meta.alias or col_meta.normalized_name
                        col_oid = self._get_column_type_from_schema(
                            table or "", col_name or "", cursor
                        )
                        if col_oid is None and rows and idx < len(rows[0]):
                            col_oid = self._infer_type_from_value(rows[0][idx], col_name)
                        metadata.append(
                            {
                                "name": col_name,
                                "type_oid": col_oid or 1043,
                                "type_size": -1,
                                "format_code": 0,
                            }
                        )
                elif isinstance(columns, list) and columns:
                    for idx, col in enumerate(columns):
                        col_name = col.strip('"') if isinstance(col, str) else str(col)
                        if "." in col_name:
                            col_name = col_name.split(".")[-1]
                        col_oid = self._get_column_type_from_schema(table or "", col_name, cursor)
                        if col_oid is None and rows and idx < len(rows[0]):
                            col_oid = self._infer_type_from_value(rows[0][idx], col_name)
                        metadata.append(
                            {
                                "name": col_name,
                                "type_oid": col_oid or 1043,
                                "type_size": -1,
                                "format_code": 0,
                            }
                        )
            finally:
                try:
                    cursor.close()
                except Exception:
                    pass

        return rows, metadata

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

    def _map_iris_type_to_oid(self, iris_type: str) -> int:
        """
        Map IRIS data type to PostgreSQL type OID.

        Args:
            iris_type: IRIS data type (e.g., 'INT', 'VARCHAR', 'DATE')

        Returns:
            PostgreSQL type OID
        """
        type_map = {
            "INT": 23,  # int4
            "INTEGER": 23,  # int4
            "BIGINT": 20,  # int8
            "SMALLINT": 21,  # int2
            "VARCHAR": 1043,  # varchar
            "CHAR": 1042,  # char
            "TEXT": 25,  # text
            "DATE": 1082,  # date
            "TIME": 1083,  # time
            "TIMESTAMP": 1114,  # timestamp
            "DOUBLE": 701,  # float8
            "FLOAT": 701,  # float8
            "NUMERIC": 1700,  # numeric
            "DECIMAL": 1700,  # numeric
            "BIT": 1560,  # bit
            "BOOLEAN": 16,  # bool
            "VARBINARY": 17,  # bytea
        }

        # Normalize type name (remove size, etc.)
        normalized_type = iris_type.upper().split("(")[0].strip()

        return type_map.get(normalized_type, 1043)  # Default to VARCHAR (OID 1043)

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

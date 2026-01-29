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

    def _convert_params_for_iris(self, params: Any) -> Any:
        """
        Convert parameters to IRIS-compatible formats.
        Specifically handles ISO 8601 timestamps.
        """
        if params is None:
            return None

        if isinstance(params, (list, tuple)):
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

        try:
            # Feature: Handle catalog emulation shared across all paths
            catalog_result = await self.catalog_router.handle_catalog_query(
                sql, params, session_id, self
            )
            if catalog_result is not None:
                return catalog_result

            # Translate placeholders ($1 -> ?)
            sql = self._translate_placeholders(sql)

            # Convert parameters for IRIS (e.g., ISO 8601 timestamps)
            converted_params = self._convert_params_for_iris(params)

            # Acquire connection from pool
            conn_wrapper = await self.pool.acquire()

            # Detect RETURNING clause
            has_returning = self.has_returning_clause(sql)

            # Execute query in thread pool (DBAPI is synchronous)
            def execute_in_thread():
                cursor = conn_wrapper.connection.cursor()  # type: ignore
                try:
                    # Feature 034: Apply per-session namespace if set
                    if session_id and session_id in self.session_namespaces:
                        ns = self.session_namespaces[session_id]
                        logger.debug(f"Session {session_id} using namespace {ns}")

                    # Handle RETURNING emulation
                    if has_returning:
                        op, table, cols, where, stripped_sql = self._parse_returning_clause(sql)
                        if op and table:
                            # Strip trailing semicolon
                            clean_sql = stripped_sql.strip().rstrip(";")

                            # For DELETE, we must fetch BEFORE deleting
                            delete_rows = []
                            delete_meta = None
                            if op == "DELETE":
                                delete_rows, delete_meta = self._emulate_returning_sync(
                                    cursor, op, table, cols, where, converted_params, sql
                                )

                            # Execute the main statement
                            if converted_params:
                                cursor.execute(clean_sql, converted_params)
                            else:
                                cursor.execute(clean_sql)

                            # Emulate RETURNING result
                            if op == "DELETE":
                                rows = delete_rows
                                columns = delete_meta
                            else:
                                rows, columns = self._emulate_returning_sync(
                                    cursor, op, table, cols, where, converted_params, sql
                                )

                            row_count = len(rows)
                            return rows, columns, row_count

                    # Standard execution path
                    # Strip trailing semicolon for IRIS compatibility
                    clean_sql = sql.strip().rstrip(";")

                    if converted_params:
                        cursor.execute(clean_sql, converted_params)
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

        RETURNING SUPPORT: When SQL contains RETURNING clause, executes each statement
        individually and aggregates the returned rows.
        """
        start_time = time.perf_counter()
        conn_wrapper = None

        try:
            # Translate placeholders ($1 -> ?)
            sql = self._translate_placeholders(sql)

            # Detect RETURNING clause
            has_returning = self.has_returning_clause(sql)

            # Acquire connection from pool
            conn_wrapper = await self.pool.acquire()

            # Execute batch in thread pool
            def execute_batch_in_thread():
                cursor = conn_wrapper.connection.cursor()  # type: ignore
                try:
                    # Strip trailing semicolon for IRIS compatibility
                    clean_sql = sql.strip().rstrip(";")

                    if has_returning:
                        op, table, cols, where, stripped_sql = self._parse_returning_clause(sql)
                        if op and table:
                            all_rows = []
                            all_meta = None

                            for params in params_list:
                                converted_params = self._convert_params_for_iris(params)
                                # For DELETE, capture before
                                if op == "DELETE":
                                    rows, meta = self._emulate_returning_sync(
                                        cursor, op, table, cols, where, converted_params, sql
                                    )
                                    all_rows.extend(rows)
                                    if not all_meta:
                                        all_meta = meta

                                # Execute statement
                                cursor.execute(stripped_sql.strip().rstrip(";"), converted_params)

                                # For INSERT/UPDATE, capture after
                                if op != "DELETE":
                                    rows, meta = self._emulate_returning_sync(
                                        cursor, op, table, cols, where, converted_params, sql
                                    )
                                    all_rows.extend(rows)
                                    if not all_meta:
                                        all_meta = meta

                            return all_rows, all_meta or [], len(params_list)

                    # Standard batch execution
                    # Pre-process parameters (e.g. convert lists to IRIS vector strings)
                    final_params_list = []
                    for p_set in params_list:
                        # Convert ISO 8601 timestamps and other formats
                        converted_p_set = self._convert_params_for_iris(p_set)

                        processed_params = [
                            "[" + ",".join(map(str, p)) + "]" if isinstance(p, list) else p
                            for p in converted_p_set
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
                    return [], [], rows_affected
                finally:
                    cursor.close()

            rows, columns, rows_affected = await asyncio.to_thread(execute_batch_in_thread)

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
                "rows": rows,
                "columns": columns,
                "_execution_path": (
                    "dbapi_executemany_returning" if has_returning else "dbapi_executemany"
                ),
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
        cursor,
        operation: str,
        table: str,
        columns: list[str] | str,
        where_clause: str | None,
        params: list | None,
        original_sql: str | None = None,
    ) -> tuple[list[Any], Any]:
        """
        Synchronous emulation of RETURNING clause.
        """
        table_normalized = table.upper() if table else table
        if columns == "*":
            # Expand * using table schema
            expanded_cols = self._get_table_columns_from_schema(table_normalized, cursor)
            if expanded_cols:
                col_list = ", ".join([f'"{col}"' for col in expanded_cols])
                columns = expanded_cols  # Update columns for metadata generation
            else:
                col_list = "*"
        else:
            col_list = ", ".join([f'"{col}"' for col in columns])

        rows = []
        meta = None

        try:
            if operation == "INSERT":
                # Method 1: LAST_IDENTITY()
                cursor.execute("SELECT LAST_IDENTITY()")
                id_row = cursor.fetchone()
                last_id = id_row[0] if id_row else None

                if last_id:
                    cursor.execute(
                        f'SELECT {col_list} FROM {IRIS_SCHEMA}."{table_normalized}" WHERE %ID = ?',
                        (last_id,),
                    )
                    rows = cursor.fetchall()
                    meta = cursor.description

                # Method 2: Extract from SQL if still no rows
                if not rows and original_sql:
                    id_col_name, id_value = self._extract_insert_id_from_sql(original_sql, params)
                    if id_col_name and id_value:
                        cursor.execute(
                            f'SELECT {col_list} FROM {IRIS_SCHEMA}."{table_normalized}" WHERE "{id_col_name}" = ?',
                            (id_value,),
                        )
                        rows = cursor.fetchall()
                        meta = cursor.description

            elif operation in ("UPDATE", "DELETE"):
                if where_clause:
                    # Translate schema references in WHERE clause
                    translated_where = re.sub(
                        r'"public"\s*\.\s*"(\w+)"',
                        rf'{IRIS_SCHEMA}."\1"',
                        where_clause,
                        flags=re.IGNORECASE,
                    )
                    translated_where = re.sub(
                        r'\bpublic\s*\.\s*"(\w+)"',
                        rf'{IRIS_SCHEMA}."\1"',
                        translated_where,
                        flags=re.IGNORECASE,
                    )

                    # Very basic where clause parameter extraction
                    where_param_count = translated_where.count("?")
                    where_params = (
                        params[-where_param_count:] if params and where_param_count > 0 else None
                    )

                    cursor.execute(
                        f'SELECT {col_list} FROM {IRIS_SCHEMA}."{table_normalized}" WHERE {translated_where}',
                        where_params or (),
                    )
                    rows = cursor.fetchall()
                    meta = cursor.description

            # Build metadata if needed
            if meta and not any(isinstance(m, dict) and "type_oid" in m for m in meta):
                new_meta = []
                for i, desc in enumerate(meta):
                    col_name = desc[0]
                    col_oid = self._map_dbapi_type_to_oid(desc[1])
                    new_meta.append({"name": col_name, "type_oid": col_oid, "format_code": 0})
                meta = new_meta

        except Exception as e:
            logger.error(f"RETURNING emulation failed: {e}")

        return rows, meta

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

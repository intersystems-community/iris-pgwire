"""
DBAPI executor for InterSystems IRIS query execution.

Executes SQL queries via intersystems-irispython DBAPI with connection pooling,
vector query support, and performance monitoring.
"""

import asyncio
import datetime as dt
import re
import time
from decimal import Decimal
from typing import Any

import structlog

from iris_pgwire.catalog import CatalogRouter
from iris_pgwire.dbapi_connection_pool import IRISConnectionPool
from iris_pgwire.iris_executor import (  # noqa: F401 — shared constants
    POSIXTIME_MAX,
    POSIXTIME_OFFSET,
)
from iris_pgwire.models.backend_config import BackendConfig
from iris_pgwire.models.connection_pool_state import ConnectionPoolState
from iris_pgwire.models.vector_query_request import VectorQueryRequest
from iris_pgwire.schema_mapper import IRIS_SCHEMA
from iris_pgwire.sql_translator import SQLInterceptor, SQLPipeline
from iris_pgwire.sql_translator.array_params import (
    encode_inlist_params,
    expand_array_literals,
    has_array_param,
    rewrite_any_to_inlist,
)
from iris_pgwire.sql_translator.boolean_expr import (
    has_boolean_literal_comparison,
    has_boolean_projection,
    rewrite_boolean_literal_comparisons,
    rewrite_boolean_projections,
)
from iris_pgwire.sql_translator.parser import get_parser
from iris_pgwire.sql_translator.pg_functions import (
    has_pg_function_call,
    rewrite_pg_function_calls,
)
from iris_pgwire.sql_translator.returning_plan import ReturningPlan
from iris_pgwire.sql_translator.verbatim import is_verbatim

logger = structlog.get_logger(__name__)

# Connection-lost error indicators (shared by execute_query and execute_many)
_CONNECTION_LOST_MARKERS = (
    "connection lost",
    "not connected",
    "communication link failure",
    "socket error",
    "operationalerror",
    "interfaceerror",
)

# Transaction control keywords
_TX_CONTROL_KEYWORDS = ("BEGIN", "START TRANSACTION", "COMMIT", "ROLLBACK", "END")

# IRIS type → PostgreSQL OID mapping
_IRIS_TYPE_TO_OID: dict[str, int] = {
    "INT": 23,
    "INTEGER": 23,
    "BIGINT": 20,
    "SMALLINT": 21,
    "VARCHAR": 1043,
    "CHAR": 1042,
    "TEXT": 25,
    "DATE": 1082,
    "TIME": 1083,
    "TIMESTAMP": 1114,
    "DOUBLE": 701,
    "FLOAT": 701,
    "NUMERIC": 1700,
    "DECIMAL": 1700,
    "BIT": 1560,
    "BOOLEAN": 16,
    "VARBINARY": 17,
}

# Python type → PostgreSQL OID mapping
_PYTHON_TYPE_TO_OID: dict[type, int] = {
    bool: 16,
    int: 23,
    float: 701,
    Decimal: 1700,
    dt.datetime: 1114,
    dt.date: 1082,
    str: 1043,
}


class DBAPIExecutor:
    """Execute SQL queries against IRIS via DBAPI backend.

    Uses connection pool for efficient connection management and supports
    vector similarity queries with pgvector syntax translation.
    """

    backend_type: str = "dbapi"

    def __init__(self, config: BackendConfig):
        self.config = config
        self.pool = IRISConnectionPool(config)
        self.backend_type = "dbapi"
        self.session_namespaces: dict[str, str] = {}
        self.session_connections: dict[str, Any] = {}
        self.strict_single_connection = config.strict_single_connection
        self.session_transactions: dict[str, bool] = {}

        self.sql_pipeline = SQLPipeline()
        self.sql_translator = self.sql_pipeline.translator
        self.sql_parser = get_parser()
        self.catalog_router = CatalogRouter()
        # Handles scalar session functions (version(), current_database(), ...)
        # that IRIS has no equivalent for. The embedded executor has always had
        # this; without it here, DBAPI passed them through to IRIS SQL, which
        # resolved version() as SQLUser.VERSION and errored. That broke every
        # ORM introspection on this backend and violated Principle IV, which
        # requires both backends stay functional.
        self.sql_interceptor = SQLInterceptor(self)

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

    # ------------------------------------------------------------------
    # Parameter conversion
    # ------------------------------------------------------------------

    def _translate_placeholders(self, sql: str) -> str:
        """Translate PostgreSQL $1, $2 placeholders to DBAPI ? placeholders."""
        # SQL pgwire authored itself is left exactly as written. This backend
        # does far less rewriting than the embedded one, but an ObjectScript
        # function body is not PostgreSQL and must not be pattern-matched as
        # though it were. See sql_translator/verbatim.py.
        if is_verbatim():
            return sql
        return re.sub(r"\$\d+", "?", sql)

    def _convert_params_for_iris(self, params: Any) -> Any:
        """Convert parameters to IRIS-compatible formats."""
        if params is None:
            return None
        if isinstance(params, list | tuple):
            return [self._convert_value_for_iris(v) for v in params]
        return self._convert_value_for_iris(params)

    def _convert_value_for_iris(self, value: Any) -> Any:
        """Convert a single value to IRIS-compatible format."""
        # datetime MUST be checked before date (datetime is a subclass of date)
        if isinstance(value, dt.datetime):
            if value.tzinfo is not None:
                value = value.astimezone(dt.UTC).replace(tzinfo=None)
            return value.strftime("%Y-%m-%d %H:%M:%S.%f")

        if isinstance(value, dt.date):
            return value.strftime("%Y-%m-%d")

        if isinstance(value, str):
            return self._convert_iso_timestamp(value)

        return value

    def _convert_iso_timestamp(self, value: str) -> str:
        """Convert ISO 8601 timestamp strings to IRIS-compatible format."""
        ts_match = re.match(
            r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2}(?:\.\d+)?)"
            r"(Z|([+-])(\d{2}):?(\d{2}))?$",
            value,
        )
        if not ts_match:
            return value

        date_part, time_part = ts_match.group(1), ts_match.group(2)
        tz_sign, tz_hh = ts_match.group(4), ts_match.group(5)

        # Strip timezone — IRIS doesn't support tz-aware timestamps; keep local time as-is
        if not (tz_sign and tz_hh):
            return f"{date_part} {time_part}"

        has_frac = "." in time_part
        result = f"{date_part} {time_part}"
        if has_frac and "." in result:
            base, frac = result.rsplit(".", 1)
            result = base + "." + frac[:3]
        return result

    # ------------------------------------------------------------------
    # Query execution
    # ------------------------------------------------------------------

    async def execute_query(
        self, sql: str, params: tuple | None = None, session_id: str | None = None, **kwargs
    ) -> dict[str, Any]:
        """Execute SQL query via DBAPI connection pool."""
        start_time = time.perf_counter()
        conn_wrapper = None
        release_connection = True
        original_sql = sql

        try:
            catalog_result = await self.catalog_router.handle_catalog_query(
                sql, params, session_id, self
            )
            if catalog_result is not None:
                return catalog_result

            intercept_result = self.sql_interceptor.intercept(sql, params, session_id)
            if intercept_result.intercepted:
                return intercept_result.result

            # Rewrite `col = ANY($n)` to `col %INLIST $n`. IRIS has no
            # ANY(array) construct — it reaches the parser as
            # "SELECT expected, ? found" — and the rewrite has to happen
            # whether or not values are bound, because Describe prepares the
            # statement with nothing bound. Applied to every statement rather
            # than only intercepted ones: catalog tables served by IRIS views
            # reach the database for real (feature 044).
            if has_array_param(sql):
                sql = expand_array_literals(rewrite_any_to_inlist(sql))
                params = encode_inlist_params(sql, params)

            # Rewrite a boolean expression used as a projected value into
            # CAST(CASE WHEN ... AS BIT). IRIS has no boolean type and takes
            # AND/OR only in a predicate, so `(a AND b = 1) AS flag` fails at
            # parse time with "ERROR: ) expected, AND found". Prisma's table
            # query projects two of these.
            if has_boolean_projection(sql):
                sql = rewrite_boolean_projections(sql)

            # Point unqualified catalog function calls at the PGWire schema.
            # IRIS resolves `obj_description(...)` against the default schema
            # and reports SQLUSER.OBJ_DESCRIPTION does not exist.
            if has_pg_function_call(sql):
                sql = rewrite_pg_function_calls(sql)

            # `relispartition = 'f'` -> `relispartition = 0`. The views hold 0/1
            # for the columns PostgreSQL declares bool, and comparing one to the
            # string 'f' inside a nested predicate group crashes IRIS outright
            # (SQLCODE -400) rather than erroring — the shape Prisma emits.
            if has_boolean_literal_comparison(sql):
                sql = rewrite_boolean_literal_comparisons(sql)

            sql = self._translate_placeholders(sql)
            plan = ReturningPlan.from_sql(sql)
            converted_params = self._convert_params_for_iris(params)

            conn_wrapper, pinned = await self._acquire_connection(session_id)
            release_connection = not pinned

            def execute_in_thread():
                if session_id and session_id in self.session_namespaces:
                    ns = self.session_namespaces[session_id]
                    logger.debug(f"Session {session_id} using namespace {ns}")
                return self._execute_statement_sync(
                    conn_wrapper.connection, plan, converted_params, session_id, original_sql
                )

            query_timeout = getattr(self.config, "query_timeout", 30.0)
            try:
                rows, columns, row_count = await asyncio.wait_for(
                    asyncio.to_thread(execute_in_thread), timeout=query_timeout
                )
            except TimeoutError:
                logger.error(
                    "Query timed out — evicting connection from pool",
                    sql_preview=sql[:120],
                    timeout_seconds=query_timeout,
                    session_id=session_id,
                )
                # Mark connection unhealthy so it gets evicted, not recycled
                if conn_wrapper:
                    conn_wrapper.is_healthy = False
                raise RuntimeError(
                    f"Query execution timed out after {query_timeout}s. "
                    "The IRIS connection is being evicted to prevent pool exhaustion."
                )

            tx_sql_upper = original_sql.strip().upper()
            self._update_transaction_state(session_id, tx_sql_upper)
            self._maybe_auto_commit(conn_wrapper.connection, session_id, tx_sql_upper)

            elapsed_ms = (time.perf_counter() - start_time) * 1000
            self._record_success(conn_wrapper, elapsed_ms)

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
            self._handle_execution_error(e, conn_wrapper, session_id, sql[:200], "Query")
            raise

        finally:
            if conn_wrapper and release_connection:
                await self.pool.release(conn_wrapper)

    async def execute_many(
        self, sql: str, params_list: list[tuple] | list[list], session_id: str | None = None
    ) -> dict[str, Any]:
        """Execute SQL with multiple parameter sets for batch operations."""
        start_time = time.perf_counter()
        conn_wrapper = None
        release_connection = True
        original_sql = sql

        try:
            sql = self._translate_placeholders(sql)
            plan = ReturningPlan.from_sql(sql)

            conn_wrapper, pinned = await self._acquire_connection(session_id)
            release_connection = not pinned

            all_rows, columns_info, rows_affected = await self._execute_batch_loop(
                conn_wrapper,
                plan,
                params_list,
                session_id,
                original_sql,
            )

            elapsed_ms = (time.perf_counter() - start_time) * 1000
            self._record_success(conn_wrapper, elapsed_ms)

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
                "_execution_path": (
                    "dbapi_executemany_returning" if plan.has_returning else "dbapi_executemany"
                ),
            }

        except Exception as e:
            self._handle_execution_error(e, conn_wrapper, session_id, sql[:200], "Batch")
            raise

        finally:
            if conn_wrapper and release_connection:
                await self.pool.release(conn_wrapper)

    async def _execute_batch_loop(
        self,
        conn_wrapper: Any,
        plan: ReturningPlan,
        params_list: list,
        session_id: str | None,
        original_sql: str,
    ) -> tuple[list[Any], list[dict[str, Any]], int]:
        """Execute each parameter set in the batch and aggregate results."""
        all_rows: list[Any] = []
        columns_info: list[dict[str, Any]] = []
        rows_affected = 0

        for params in params_list:
            converted = self._convert_params_for_iris(params)
            rows, columns, row_count = await asyncio.to_thread(
                self._execute_statement_sync,
                conn_wrapper.connection,
                plan,
                converted,
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

        return all_rows, columns_info, rows_affected

    def _record_success(self, conn_wrapper: Any, elapsed_ms: float) -> None:
        """Record successful query metrics."""
        self._total_queries += 1
        self._total_query_time_ms += elapsed_ms
        conn_wrapper.record_query_execution(acquisition_time_ms=elapsed_ms, success=True)

    def _handle_execution_error(
        self,
        error: Exception,
        conn_wrapper: Any,
        session_id: str | None,
        sql_preview: str,
        label: str,
    ) -> None:
        """Handle errors from execute_query/execute_many with connection-lost detection."""
        error_str = str(error).lower()
        connection_lost = any(msg in error_str for msg in _CONNECTION_LOST_MARKERS)

        logger.error(
            f"{label} execution failed: {error}", sql=sql_preview, connection_lost=connection_lost
        )
        self._total_errors += 1

        if not conn_wrapper:
            return

        if connection_lost:
            conn_wrapper.mark_failed(str(error))
            if session_id:
                self.session_connections.pop(session_id, None)
                self.session_transactions.pop(session_id, None)
        else:
            conn_wrapper.record_query_execution(acquisition_time_ms=0, success=False)

    # ------------------------------------------------------------------
    # Connection & transaction management
    # ------------------------------------------------------------------

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
        elif normalized.startswith(("COMMIT", "ROLLBACK", "END")):
            self.session_transactions.pop(session_id, None)

    def _is_transaction_control_sql(self, sql_upper: str | None) -> bool:
        if not sql_upper:
            return False
        normalized = sql_upper.strip().upper()
        return any(normalized.startswith(kw) for kw in _TX_CONTROL_KEYWORDS)

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

    # ------------------------------------------------------------------
    # Statement execution
    # ------------------------------------------------------------------

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
            return self._execute_with_cursor(
                cursor, connection, plan, params, session_id, original_sql
            )
        finally:
            try:
                cursor.close()
            except Exception:
                pass

    def _execute_with_cursor(
        self,
        cursor: Any,
        connection: Any,
        plan: ReturningPlan,
        params: list | tuple | None,
        session_id: str | None,
        original_sql: str | None,
    ) -> tuple[list[Any], list[dict[str, Any]], int]:
        """Core execution logic, separated from cursor lifecycle."""
        cleaned_sql = plan.stripped_sql.strip().rstrip(";")
        execute_params = tuple(params) if params else None

        # Pre-fetch rows for DELETE RETURNING before the DELETE executes
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
            return self._handle_conflict_exception(
                exc, plan, params, connection, session_id, original_sql
            )

        return self._build_result(
            cursor, connection, plan, params, session_id, original_sql, delete_rows, delete_meta
        )

    def _handle_conflict_exception(
        self,
        exc: Exception,
        plan: ReturningPlan,
        params: list | tuple | None,
        connection: Any,
        session_id: str | None,
        original_sql: str | None,
    ) -> tuple[list[Any], list[dict[str, Any]], int]:
        """Handle ON CONFLICT exceptions during execution."""
        if plan.conflict_action == "DO NOTHING" and self._is_unique_violation(exc):
            return [], [], 0
        if plan.conflict_action == "DO UPDATE" and self._is_unique_violation(exc):
            rows, columns = self._handle_on_conflict_update(
                plan, params, connection, session_id, original_sql
            )
            return rows, columns or [], len(rows)
        raise exc

    def _build_result(
        self,
        cursor: Any,
        connection: Any,
        plan: ReturningPlan,
        params: list | tuple | None,
        session_id: str | None,
        original_sql: str | None,
        delete_rows: list[Any],
        delete_meta: list[dict[str, Any]] | None,
    ) -> tuple[list[Any], list[dict[str, Any]], int]:
        """Build result tuple from cursor after successful execution."""
        row_count = (
            cursor.rowcount if getattr(cursor, "rowcount", -1) and cursor.rowcount >= 0 else 0
        )

        if not plan.has_returning:
            rows, columns = self._fetch_standard_results(cursor, plan.stripped_sql)
            return rows, columns, max(row_count, len(rows))

        if plan.operation == "DELETE":
            return delete_rows, delete_meta or [], len(delete_rows)

        rows, columns = self._emulate_returning_sync(
            connection,
            plan,
            params,
            session_id=session_id,
            original_sql=original_sql,
        )
        return rows, columns, len(rows)

    def _fetch_standard_results(
        self, cursor: Any, sql: str | None = None
    ) -> tuple[list[Any], list[dict[str, Any]]]:
        """Fetch rows and column metadata from a cursor with results."""
        if not cursor.description:
            return [], []
        rows = cursor.fetchall()
        columns = self._build_metadata_from_description(cursor.description)
        if rows:
            columns = self._refine_column_types_from_rows(columns, rows)
        # Last, so it wins: what the SQL says does not depend on a row existing.
        if sql:
            columns = self._apply_sql_column_types(columns, sql)
        return rows, columns

    @staticmethod
    def _apply_sql_column_types(columns: list[dict], sql: str) -> list[dict]:
        """Override types the statement itself settles (T011h / FR-004).

        Value-based refinement below can only run when a row came back, so a
        statement Describe — which executes with dummy parameters that match
        nothing — declared varchar for every column while Execute declared bool.
        A client reading the Describe then cannot decode the DataRow. Resolving
        from the SQL is row-count independent, so the two paths agree.
        """
        from .sql_translator.column_types import resolve_column_type_oids

        try:
            resolved = resolve_column_type_oids(sql)
        except Exception as exc:  # noqa: BLE001 — never fail a query over metadata
            logger.debug("SQL column-type resolution failed", error=str(exc))
            return columns

        if len(resolved) != len(columns):
            # Positions must line up or an override lands on the wrong column;
            # a SELECT * expansion is the usual reason they do not.
            return columns

        return [
            {**col, "type_oid": oid} if oid is not None else col
            for col, oid in zip(columns, resolved)
        ]

    def _refine_column_types_from_rows(
        self, columns: list[dict], rows: list
    ) -> list[dict]:
        """Refine column type OIDs using actual first-row Python values.

        IRIS DBAPI often returns type_code=4 for all columns regardless of type.
        Use the actual Python type of the first row's values to assign correct OIDs.
        Only refines columns that currently have the generic VARCHAR OID (1043).

        A last resort only: it cannot run when a query returns no rows, which is
        what made the declared type depend on the row count (see
        `_apply_sql_column_types`).
        """
        if not rows or not columns:
            return columns
        first_row = rows[0]
        refined = []
        for i, col in enumerate(columns):
            if col.get("type_oid") == 1043 and i < len(first_row):
                val = first_row[i]
                if isinstance(val, bool):
                    refined.append({**col, "type_oid": 16})   # BOOL
                elif isinstance(val, int):
                    refined.append({**col, "type_oid": 23})   # INT4
                elif isinstance(val, float):
                    refined.append({**col, "type_oid": 701})  # FLOAT8
                else:
                    refined.append(col)
            else:
                refined.append(col)
        return refined

    # ------------------------------------------------------------------
    # ON CONFLICT handling
    # ------------------------------------------------------------------

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
        self._execute_with_new_cursor(connection, update_sql, tuple(set_params + where_params))

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
        if not params or not plan.insert_columns:
            return {}
        return {
            column.lower(): params[idx]
            for idx, column in enumerate(plan.insert_columns)
            if idx < len(params)
        }

    def _prepare_conflict_set_clause(
        self, plan: ReturningPlan, column_values: dict[str, Any]
    ) -> tuple[str, list[Any]]:
        if not plan.conflict_set_clause:
            return "", []
        params: list[Any] = []
        pattern = re.compile(r"\bEXCLUDED\.\"?(\w+)\"?", re.IGNORECASE)

        def _replace(match: re.Match) -> str:
            params.append(column_values.get(match.group(1).lower()))
            return "?"

        return pattern.sub(_replace, plan.conflict_set_clause), params

    def _prepare_conflict_where_clause(
        self, plan: ReturningPlan, column_values: dict[str, Any]
    ) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        for column in plan.conflict_target_columns:
            clauses.append(f'"{column.upper()}" = ?')
            params.append(column_values.get(column.lower()))

        where_clause = " AND ".join(clauses)
        if plan.conflict_where_clause:
            where_clause = (
                f"{where_clause} AND {plan.conflict_where_clause}"
                if where_clause
                else plan.conflict_where_clause
            )
        return where_clause, params

    # ------------------------------------------------------------------
    # RETURNING emulation
    # ------------------------------------------------------------------

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
        table_normalized = plan.table.upper() if plan.table else None
        if not table_normalized:
            return [], []

        col_list, columns = self._resolve_returning_columns(connection, plan, table_normalized)
        param_values = list(params) if params else []

        rows, metadata = self._fetch_returning_rows(
            connection,
            operation,
            table_normalized,
            col_list,
            plan,
            param_values,
            session_id,
            original_sql,
            override_where,
            override_where_params,
        )

        if metadata is None:
            metadata = self._build_returning_metadata(
                connection, plan, columns, table_normalized, rows
            )

        return rows, metadata

    def _resolve_returning_columns(
        self,
        connection: Any,
        plan: ReturningPlan,
        table_normalized: str,
    ) -> tuple[str, list[str] | str]:
        """Resolve column list and SELECT expression for RETURNING emulation."""
        columns = plan.columns or ["*"]

        if columns == "*":
            expanded = self._get_table_columns_from_schema(
                table_normalized, connection.cursor() if not self.strict_single_connection else None
            )
            if expanded:
                col_list = ", ".join(f'"{col}"' for col in expanded)
                return col_list, expanded
            return "*", "*"

        if plan.column_meta:
            return plan.select_list, columns

        processed = []
        for col in columns:
            if re.match(r'^"?\w+"?$', col):
                processed.append(f'"{col.strip(chr(34))}"')
            else:
                processed.append(col)
        return ", ".join(processed), columns

    def _fetch_returning_rows(
        self,
        connection: Any,
        operation: str,
        table: str,
        col_list: str,
        plan: ReturningPlan,
        param_values: list[Any],
        session_id: str | None,
        original_sql: str | None,
        override_where: str | None,
        override_where_params: list[Any] | None,
    ) -> tuple[list[Any], list[dict[str, Any]] | None]:
        """Fetch rows for RETURNING emulation based on the operation type."""
        try:
            if operation == "INSERT":
                return self._fetch_returning_insert(
                    connection,
                    table,
                    col_list,
                    plan,
                    param_values,
                    session_id,
                    original_sql,
                )
            if operation in ("UPDATE", "DELETE"):
                return self._fetch_returning_update_delete(
                    connection,
                    table,
                    col_list,
                    plan,
                    param_values,
                    override_where,
                    override_where_params,
                )
        except Exception as exc:  # pragma: no cover - best effort logging
            logger.error(
                f"RETURNING emulation failed for {operation}",
                table=table,
                error=str(exc),
            )
        return [], None

    def _fetch_returning_insert(
        self,
        connection: Any,
        table: str,
        col_list: str,
        plan: ReturningPlan,
        param_values: list[Any],
        session_id: str | None,
        original_sql: str | None,
    ) -> tuple[list[Any], list[dict[str, Any]] | None]:
        """Try multiple strategies to fetch the inserted row."""
        # Strategy 1: LAST_IDENTITY()
        last_identity = self._fetch_last_identity(connection)
        if last_identity is not None:
            rows, meta = self._fetch_with_cursor(
                connection,
                f'SELECT {col_list} FROM {IRIS_SCHEMA}."{table}" WHERE %ID = ?',
                [last_identity],
            )
            if rows:
                return rows, meta

        # Strategy 2: Extract ID from INSERT SQL
        if original_sql:
            id_col, id_value = self._extract_insert_id_from_sql(
                original_sql, param_values, session_id
            )
            if id_col and id_value is not None:
                rows, meta = self._fetch_with_cursor(
                    connection,
                    f'SELECT {col_list} FROM {IRIS_SCHEMA}."{table}" WHERE "{id_col}" = ?',
                    [id_value],
                )
                if rows:
                    return rows, meta

        # Strategy 3: Primary key lookup
        rows, meta = self._fetch_by_primary_key(connection, table, col_list, plan, param_values)
        if rows:
            return rows, meta

        # Strategy 4: Fallback TOP 1
        logger.warning("RETURNING fallback: TOP 1 lookup", table=table)
        return self._fetch_with_cursor(
            connection,
            f'SELECT TOP 1 {col_list} FROM {IRIS_SCHEMA}."{table}" ORDER BY %ID DESC',
        )

    def _fetch_returning_update_delete(
        self,
        connection: Any,
        table: str,
        col_list: str,
        plan: ReturningPlan,
        param_values: list[Any],
        override_where: str | None,
        override_where_params: list[Any] | None,
    ) -> tuple[list[Any], list[dict[str, Any]] | None]:
        where_clause = override_where or plan.where_clause
        if not where_clause:
            return [], None

        translated_where = self._translate_schema_references(where_clause)
        where_params = (
            override_where_params
            if override_where_params is not None
            else self._extract_where_params(where_clause, param_values)
        )
        return self._fetch_with_cursor(
            connection,
            f'SELECT {col_list} FROM {IRIS_SCHEMA}."{table}" WHERE {translated_where}',
            where_params or None,
        )

    def _fetch_by_primary_key(
        self,
        connection: Any,
        table: str,
        col_list: str,
        plan: ReturningPlan,
        param_values: list[Any],
    ) -> tuple[list[Any], list[dict[str, Any]] | None]:
        """Fetch inserted row using primary key columns."""
        column_values = self._map_insert_column_values(plan, param_values)
        pk_columns = self._get_primary_key_columns(table, connection)
        if not pk_columns:
            return [], None

        where_parts = [f'"{pk.upper()}" = ?' for pk in pk_columns]
        where_params = [column_values.get(pk.lower()) for pk in pk_columns]

        if not all(val is not None for val in where_params):
            return [], None

        return self._fetch_with_cursor(
            connection,
            f'SELECT {col_list} FROM {IRIS_SCHEMA}."{table}" WHERE {" AND ".join(where_parts)}',
            where_params,
        )

    def _build_returning_metadata(
        self,
        connection: Any,
        plan: ReturningPlan,
        columns: list[str] | str,
        table: str | None,
        rows: list[Any],
    ) -> list[dict[str, Any]]:
        """Build column metadata when not provided by the cursor."""
        metadata: list[dict[str, Any]] = []
        cursor = connection.cursor()
        try:
            col_source = plan.column_meta if plan.column_meta else None
            if col_source:
                for idx, col_meta in enumerate(col_source):
                    col_name = col_meta.alias or col_meta.normalized_name
                    col_oid = self._resolve_column_oid(cursor, table, col_name, rows, idx)
                    metadata.append(self._make_column_entry(col_name, col_oid))
            elif isinstance(columns, list) and columns:
                for idx, col in enumerate(columns):
                    col_name = self._clean_column_name(col)
                    col_oid = self._resolve_column_oid(cursor, table, col_name, rows, idx)
                    metadata.append(self._make_column_entry(col_name, col_oid))
        finally:
            try:
                cursor.close()
            except Exception:
                pass
        return metadata

    def _resolve_column_oid(
        self,
        cursor: Any,
        table: str | None,
        col_name: str | None,
        rows: list[Any],
        idx: int,
    ) -> int:
        """Look up column type OID from schema, falling back to value inference."""
        col_oid = self._get_column_type_from_schema(table or "", col_name or "", cursor)
        if col_oid is None and rows and idx < len(rows[0]):
            col_oid = self._infer_type_from_value(rows[0][idx], col_name)
        return col_oid or 1043

    @staticmethod
    def _make_column_entry(name: str | None, type_oid: int) -> dict[str, Any]:
        return {"name": name, "type_oid": type_oid, "type_size": -1, "format_code": 0}

    @staticmethod
    def _clean_column_name(col: str) -> str:
        col_name = col.strip('"') if isinstance(col, str) else str(col)
        if "." in col_name:
            col_name = col_name.split(".")[-1]
        return col_name

    # ------------------------------------------------------------------
    # Cursor helpers
    # ------------------------------------------------------------------

    def _fetch_with_cursor(
        self,
        connection: Any,
        query: str,
        query_params: list[Any] | None = None,
    ) -> tuple[list[Any], list[dict[str, Any]]]:
        """Execute a SELECT and return (rows, metadata) with automatic cursor cleanup."""
        cur = connection.cursor()
        try:
            if query_params:
                cur.execute(query, tuple(query_params))
            else:
                cur.execute(query)
            rows = cur.fetchall()
            columns = self._build_metadata_from_description(cur.description)
            if rows:
                columns = self._refine_column_types_from_rows(columns, rows)
            columns = self._apply_sql_column_types(columns, query)
            return rows, columns
        finally:
            try:
                cur.close()
            except Exception:
                pass

    def _execute_with_new_cursor(
        self,
        connection: Any,
        sql: str,
        params: tuple | None = None,
    ) -> None:
        """Execute a statement with a new cursor (no result expected)."""
        cursor = connection.cursor()
        try:
            if params:
                cursor.execute(sql, params)
            else:
                cursor.execute(sql)
        finally:
            try:
                cursor.close()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Schema introspection
    # ------------------------------------------------------------------

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
        return re.sub(
            r'\bpublic\s*\.\s*"(\w+)"',
            rf'{IRIS_SCHEMA}."\1"',
            translated,
            flags=re.IGNORECASE,
        )

    def _get_primary_key_columns(self, table: str, connection: Any) -> list[str]:
        if not table or not connection:
            return []
        cursor = connection.cursor()
        try:
            cursor.execute(f"""
                SELECT k.COLUMN_NAME
                FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE k
                JOIN INFORMATION_SCHEMA.TABLE_CONSTRAINTS t
                    ON k.CONSTRAINT_NAME = t.CONSTRAINT_NAME
                WHERE LOWER(t.TABLE_NAME) = LOWER('{table}')
                AND LOWER(t.TABLE_SCHEMA) = LOWER('{IRIS_SCHEMA}')
                AND t.CONSTRAINT_TYPE = 'PRIMARY KEY'
                ORDER BY k.ORDINAL_POSITION
            """)
            return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.debug("Failed to fetch primary key columns", table=table, error=str(e))
            return []
        finally:
            try:
                cursor.close()
            except Exception:
                pass

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

    def _get_table_columns_from_schema(self, table: str, cursor=None) -> list[str]:
        """Query INFORMATION_SCHEMA.COLUMNS for column names in order."""
        if self.strict_single_connection or cursor is None:
            return []
        try:
            table_clean = table.strip('"').strip("'")
            cursor.execute(f"""
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE LOWER(TABLE_NAME) = LOWER('{table_clean}')
                AND LOWER(TABLE_SCHEMA) = LOWER('{IRIS_SCHEMA}')
                ORDER BY ORDINAL_POSITION
            """)
            return [row[0] for row in cursor.fetchall()]
        except Exception as e:
            logger.debug(f"Failed to get columns from schema for {table}: {e}")
            return []

    def _get_column_type_from_schema(self, table: str, column: str, cursor=None) -> int | None:
        """Query INFORMATION_SCHEMA.COLUMNS for a column's PostgreSQL type OID."""
        if self.strict_single_connection or cursor is None:
            return None
        try:
            table_clean = table.strip('"').strip("'")
            column_clean = column.strip('"').strip("'")
            cursor.execute(f"""
                SELECT DATA_TYPE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE LOWER(TABLE_NAME) = LOWER('{table_clean}')
                AND LOWER(COLUMN_NAME) = LOWER('{column_clean}')
                AND LOWER(TABLE_SCHEMA) = LOWER('{IRIS_SCHEMA}')
            """)
            row = cursor.fetchone()
            if row:
                return self._map_iris_type_to_oid(row[0])
        except Exception as e:
            logger.debug(f"Failed to get type from schema for {table}.{column}: {e}")
        return None

    def _extract_insert_id_from_sql(
        self, sql: str, params: list | None, session_id: str | None = None
    ) -> tuple[str | None, Any]:
        """Extract the ID value from an INSERT statement."""
        col_match = re.search(r"INSERT\s+INTO\s+[^\s(]+\s*\(\s*([^)]+)\s*\)", sql, re.IGNORECASE)
        if not col_match:
            return None, None

        columns = [c.strip().strip('"').strip("'").lower() for c in col_match.group(1).split(",")]

        for i, col in enumerate(columns):
            if col in ("id", "uuid", "_id"):
                if params and len(params) > i:
                    # Return UPPERCASE so the WHERE clause matches IRIS's stored column name.
                    # IRIS stores unquoted column names as uppercase; using "id" (lowercase)
                    # in a quoted identifier fails silently and returns 0 rows.
                    return col.upper(), params[i]
                return None, None

        return None, None

    # ------------------------------------------------------------------
    # Metadata building
    # ------------------------------------------------------------------

    def _build_metadata_from_description(self, description: Any) -> list[dict[str, Any]]:
        if not description:
            return []
        columns: list[dict[str, Any]] = []
        for desc in description:
            if not desc:
                continue
            type_oid = self._map_dbapi_type_to_oid(desc[1]) if len(desc) > 1 else 1043
            columns.append(
                {
                    "name": desc[0],
                    "type_oid": type_oid,
                    "type_size": desc[2] if len(desc) > 2 else -1,
                    "format_code": 0,
                }
            )
        return columns

    # ------------------------------------------------------------------
    # Type mapping
    # ------------------------------------------------------------------

    def _map_dbapi_type_to_oid(self, dbapi_type: Any) -> int:
        """Map DBAPI type to PostgreSQL OID."""
        type_str = str(dbapi_type).upper()
        if "INT" in type_str:
            return 23
        if "CHAR" in type_str or "STRING" in type_str:
            return 1043
        if "DATE" in type_str:
            return 1082
        if "TIME" in type_str:
            return 1114
        return 1043

    def _map_iris_type_to_oid(self, iris_type: str) -> int:
        """Map IRIS data type string to PostgreSQL type OID."""
        normalized = iris_type.upper().split("(")[0].strip()
        return _IRIS_TYPE_TO_OID.get(normalized, 1043)

    def _infer_type_from_value(self, value: Any, column_name: str | None = None) -> int:
        """Infer PostgreSQL type OID from a Python value."""
        if value is None:
            return 1043

        for python_type, oid in _PYTHON_TYPE_TO_OID.items():
            if isinstance(value, python_type):
                # Special case: int columns named id/key → BIGINT
                if python_type is int and column_name:
                    if any(k in column_name.lower() for k in ("id", "key")):
                        return 20
                return oid

        return 1043

    def _serialize_value(self, value: Any, type_oid: int) -> Any:
        """Serialize value for PostgreSQL wire protocol compatibility."""
        if value is None:
            return None
        if type_oid == 1114 and isinstance(value, dt.datetime):
            return value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        return value

    def _determine_command_tag(self, sql: str, row_count: int) -> str:
        """Determine PostgreSQL command tag from SQL."""
        sql_clean = sql.strip().upper()
        if not sql_clean:
            return "UNKNOWN"
        first_word = sql_clean.split()[0] if sql_clean.split() else ""
        if first_word == "SELECT":
            return "SELECT"
        if first_word == "INSERT":
            return f"INSERT 0 {row_count}"
        if first_word in ("UPDATE", "DELETE"):
            return f"{first_word} {row_count}"
        return first_word

    # ------------------------------------------------------------------
    # Public interface methods
    # ------------------------------------------------------------------

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
        match = re.search(r"RETURNING\s+(.+?)(?=$|;)", query, re.IGNORECASE | re.DOTALL)
        if not match:
            return []
        cols_str = match.group(1).strip()
        if cols_str == "*":
            return ["*"]
        return [c.strip() for c in cols_str.split(",")]

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
        self.session_namespaces.pop(session_id, None)
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
        logger.warning(f"cancel_query not fully implemented for DBAPI (pid={backend_pid})")
        return False

    async def execute_vector_query(self, request: VectorQueryRequest) -> dict[str, Any]:
        """Execute vector similarity query using translated SQL."""
        if request.exceeds_sla():
            logger.warning(
                "Vector translation exceeded 5ms SLA",
                request_id=request.request_id,
                translation_ms=request.translation_time_ms,
                operator=request.vector_operator,
                dimensions=request.vector_dimensions,
            )

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
        """Perform health check on executor and connection pool."""
        try:
            pool_state = await self.pool.health_check()
            await self.execute_query("SELECT 1")
            avg_query_ms = self.avg_query_time_ms()

            return {
                "status": "healthy" if pool_state.is_healthy else "unhealthy",
                "backend_type": self.backend_type,
                "pool": pool_state.to_health_check_response()["pool"],
                "performance": {
                    "total_queries": self._total_queries,
                    "total_errors": self._total_errors,
                    "avg_query_ms": round(avg_query_ms, 3) if avg_query_ms else None,
                    "error_rate_percent": round(self.error_rate(), 2),
                },
                "error": pool_state.degraded_reason if not pool_state.is_healthy else None,
            }
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {"status": "unhealthy", "backend_type": self.backend_type, "error": str(e)}

    async def get_pool_state(self) -> ConnectionPoolState:
        """Get current connection pool state."""
        return await self.pool.health_check()

    async def close(self) -> None:
        """Close executor and shutdown connection pool."""
        logger.info(
            "Closing DBAPI executor",
            total_queries=self._total_queries,
            total_errors=self._total_errors,
        )
        await self.pool.close()
        logger.info("DBAPI executor closed")

    def avg_query_time_ms(self) -> float | None:
        """Average query execution time in ms, or None if no queries."""
        if self._total_queries == 0:
            return None
        return self._total_query_time_ms / self._total_queries

    def error_rate(self) -> float:
        """Query error rate percentage (0-100)."""
        if self._total_queries == 0:
            return 0.0
        return (self._total_errors / self._total_queries) * 100

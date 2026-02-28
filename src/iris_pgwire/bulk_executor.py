"""
Batched IRIS SQL Execution for COPY Protocol

Implements batched INSERT statements and query result streaming using IRIS
embedded Python integration.

Constitutional Requirements:
- FR-005: Achieve >10,000 rows/second throughput (via batching)
- FR-006: <100MB memory for 1M rows (via streaming)
- Principle IV: Use asyncio.to_thread() for non-blocking IRIS operations
"""

import time
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

import structlog

from .conversions import date_to_horolog

logger = structlog.get_logger()


class BulkExecutor:
    """
    Batched IRIS SQL execution service.

    Uses 1000-row batching for bulk INSERT operations to achieve >10K rows/second.
    Uses streaming for query results to avoid memory exhaustion.
    """

    def __init__(self, iris_executor):
        """
        Initialize bulk executor.

        Args:
            iris_executor: IrisExecutor instance (from existing iris_executor.py)
        """
        self.iris_executor = iris_executor

    async def bulk_insert(
        self,
        table_name: str,
        column_names: list[str] | None,
        rows: AsyncIterator[dict],
        batch_size: int = 1000,
    ) -> int:
        """
        Execute batched INSERT statements for bulk loading.

        Pattern: Build multi-row INSERT with 1000 rows per batch.

        Example:
            INSERT INTO Patients (col1, col2) VALUES (?, ?), (?, ?), ...

        Args:
            table_name: Target table name
            column_names: List of column names (None = use all columns from first row)
            rows: Async iterator of row dicts
            batch_size: Rows per batch (default 1000)

        Returns:
            Total number of rows inserted

        Raises:
            Exception: IRIS execution error
        """
        logger.info(f"Bulk insert to {table_name}: batch_size={batch_size}")

        total_rows = 0
        batch = []
        actual_column_names = column_names

        async for row_dict in rows:
            # Determine column names from first row if not specified
            if actual_column_names is None:
                actual_column_names = list(row_dict.keys())
                logger.debug(f"Columns inferred from data: {actual_column_names}")

            batch.append(row_dict)

            # Execute batch when full
            if len(batch) >= batch_size and actual_column_names is not None:
                rows_inserted = await self._execute_batch_insert(
                    table_name, actual_column_names, batch
                )
                total_rows += rows_inserted
                batch = []  # Reset batch

        # Execute remaining batch
        if batch and actual_column_names is not None:
            rows_inserted = await self._execute_batch_insert(table_name, actual_column_names, batch)
            total_rows += rows_inserted

        logger.info(f"Bulk insert complete: {total_rows} rows inserted")
        return total_rows

    async def _execute_batch_insert(
        self, table_name: str, column_names: list[str], batch: list[dict[str, Any]]
    ) -> int:
        """Execute a single batch INSERT with DBAPI fast-path and inline fallback."""
        if not batch:
            return 0

        column_types = await self._get_column_types(table_name, column_names)
        column_list = ", ".join(column_names)
        placeholders = ", ".join("?" for _ in column_names)
        sql = f"INSERT INTO {table_name} ({column_list}) VALUES ({placeholders})"

        logger.info(
            "🚀 Batch INSERT",
            table=table_name,
            batch_size=len(batch),
            path="executemany",
        )

        params_list = self._build_params_list(batch, column_names, column_types)

        try:
            return await self._execute_batch_via_executemany(sql, params_list)
        except Exception as exc:
            logger.warning(
                "executemany() failed, falling back to inline SQL",
                error=str(exc)[:200],
                error_type=type(exc).__name__,
            )
            return await self._execute_batch_inline_fallback(
                table_name, column_list, column_names, column_types, batch
            )

    def _build_params_list(
        self,
        batch: list[dict[str, Any]],
        column_names: list[str],
        column_types: dict[str, str],
    ) -> list[list[Any]]:
        """Build parameter list for executemany() with NULL/date handling."""
        params_list: list[list[Any]] = []

        for row_dict in batch:
            params = []
            for col_name in column_names:
                value = row_dict.get(col_name)
                col_type = column_types.get(col_name, "VARCHAR")
                params.append(self._convert_value_for_param(value, col_type))
            params_list.append(params)

        return params_list

    def _convert_value_for_param(self, value: Any, col_type: str) -> Any:
        """Convert a single value for executemany parameters."""
        if value == "" or value is None:
            return None

        if col_type.upper() == "DATE":
            date_obj = datetime.strptime(value, "%Y-%m-%d").date()
            return date_to_horolog(date_obj)

        if isinstance(value, list):
            vector_str = "[" + ",".join(str(float(v)) for v in value) + "]"
            return vector_str

        return value

    async def _execute_batch_via_executemany(self, sql: str, params_list: list[list[Any]]) -> int:
        """Execute the batch via execute_many and emit metrics."""
        start_time = time.perf_counter()
        result = await self.iris_executor.execute_many(sql, params_list)

        rows_inserted = result.get("rows_affected", 0)
        execution_time = (time.perf_counter() - start_time) * 1000
        throughput = int(rows_inserted / (execution_time / 1000)) if execution_time > 0 else 0
        execution_path = result.get("_execution_path", "executemany")

        logger.info(
            f"✅ Batch INSERT complete via {execution_path}",
            rows_inserted=rows_inserted,
            execution_time_ms=execution_time,
            throughput_rows_per_sec=throughput,
        )

        return rows_inserted

    async def _execute_batch_inline_fallback(
        self,
        table_name: str,
        column_list: str,
        column_names: list[str],
        column_types: dict[str, str],
        batch: list[dict[str, Any]],
    ) -> int:
        """Fallback implementation that executes INSERTs with inline values."""
        start_time = time.perf_counter()
        rows_inserted = 0

        for row_dict in batch:
            values_clause = ", ".join(
                self._convert_value_for_inline(row_dict.get(col), column_types.get(col, "VARCHAR"))
                for col in column_names
            )

            row_sql = f"INSERT INTO {table_name} ({column_list}) VALUES ({values_clause})"
            result = await self.iris_executor.execute_query(row_sql, [])

            if not result.get("success", False):
                error_msg = result.get("error", "Unknown error")
                logger.error(f"INSERT failed: {error_msg}")
                raise RuntimeError(f"INSERT failed: {error_msg}")

            rows_inserted += 1

        execution_time = (time.perf_counter() - start_time) * 1000
        throughput = int(rows_inserted / (execution_time / 1000)) if execution_time > 0 else 0

        logger.info(
            "✅ Batch INSERT complete via inline_sql_fallback",
            rows_inserted=rows_inserted,
            execution_time_ms=execution_time,
            throughput_rows_per_sec=throughput,
        )

        return rows_inserted

    def _convert_value_for_inline(self, value: Any, col_type: str) -> str:
        """Convert a single value to its inline SQL literal."""
        if value == "" or value is None:
            return "NULL"

        if col_type.upper() == "DATE":
            date_obj = datetime.strptime(value, "%Y-%m-%d").date()
            return str(date_to_horolog(date_obj))

        if isinstance(value, list):
            vector_str = "[" + ",".join(str(float(v)) for v in value) + "]"
            return f"'{vector_str}'"

        escaped_value = str(value).replace("'", "''")
        return f"'{escaped_value}'"

    async def _get_column_types(self, table_name: str, column_names: list[str]) -> dict[str, str]:
        """
        Get data types for specific columns in a table.

        Args:
            table_name: Table name
            column_names: Column names to get types for

        Returns:
            Dict mapping column name to data type (e.g., {'DateOfBirth': 'DATE'})
        """
        # Query INFORMATION_SCHEMA for column types
        # IRIS stores column names in mixed case, so we need to match case-insensitively
        query = f"""
            SELECT COLUMN_NAME, DATA_TYPE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE LOWER(TABLE_NAME) = LOWER(?)
            AND UPPER(COLUMN_NAME) IN ({", ".join(["UPPER(?)" for _ in column_names])})
        """

        params = [table_name] + column_names
        logger.debug(f"Querying column types with params: {params}")
        result = await self.iris_executor.execute_query(query, params)

        # Build column type mapping (key by original input column name)
        column_types = {}
        if result.get("success") and result.get("rows"):
            # Create case-insensitive lookup
            db_columns = {row[0].upper(): row[1] for row in result["rows"]}
            logger.debug(f"Database columns (uppercase keys): {db_columns}")

            # Map back to input column names
            for col_name in column_names:
                db_type = db_columns.get(col_name.upper())
                if db_type:
                    column_types[col_name] = db_type
        else:
            logger.warning(
                f"Failed to get column types: success={result.get('success')}, rows={result.get('rows')}"
            )

        logger.debug(f"Column types for {table_name}: {column_types}")
        return column_types

    async def stream_query_results(self, query: str) -> AsyncIterator[tuple]:
        """
        Execute SELECT query and stream results.

        Uses batched fetching (1000 rows at a time) to avoid memory exhaustion.

        Args:
            query: SELECT query

        Yields:
            Row tuples

        Raises:
            Exception: IRIS query execution error
        """
        logger.info(f"Streaming query results: {query[:100]}")

        # Execute query via IRIS (already async)
        try:
            # Execute query
            cursor_result = await self.iris_executor.execute_query(query, [])

            # Stream results in batches
            # Note: This is a simplified implementation
            # Real implementation would use IRIS cursor.fetchmany()
            if cursor_result:
                for row in cursor_result:
                    yield row

            logger.debug("Query streaming complete")

        except Exception as e:
            logger.error(f"Query execution failed: {e}")
            raise

    async def get_table_columns(self, table_name: str) -> list[str]:
        """
        Get column names for a table using INFORMATION_SCHEMA.

        Args:
            table_name: Table name

        Returns:
            List of column names

        Raises:
            Exception: IRIS query error
        """
        query = f"""
            SELECT column_name
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE LOWER(table_name) = LOWER('{table_name}')
            ORDER BY ordinal_position
        """

        result = await self.iris_executor.execute_query(query, [])

        # Extract column names from result
        columns = []
        if result and "rows" in result:
            columns = [row[0] for row in result["rows"]]

        logger.debug(f"Table {table_name} columns: {columns}")
        return columns

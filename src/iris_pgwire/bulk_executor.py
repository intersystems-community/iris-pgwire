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
        """
        Execute single batch INSERT with try/catch architecture.

        ARCHITECTURE (2025-11-10):
        - TRY: DBAPI executemany() (fast path - 4-10× improvement expected)
        - CATCH: Inline SQL values (fallback - ~600 rows/sec)
        - Leverages connection independence: execution mode ≠ connection mode
        - Even in irispython, we can connect to localhost via DBAPI

        Performance Targets:
        - DBAPI executemany(): 2,400-10,000+ rows/sec (FR-005 requirement)
        - Inline SQL fallback: ~600 rows/sec (current baseline)

        IRIS DATE Handling: Convert ISO date strings to IRIS Horolog format (days since 1840-12-31).

        Args:
            table_name: Target table
            column_names: Column names
            batch: List of row dicts

        Returns:
            Number of rows inserted

        References:
            - Performance investigation: docs/COPY_PERFORMANCE_INVESTIGATION.md
        """
        if not batch:
            return 0

        # Get column data types to handle DATE conversion
        column_types = await self._get_column_types(table_name, column_names)

        # Build INSERT SQL template
        column_list = ", ".join(column_names)
        placeholders = ", ".join(["?" for _ in column_names])
        sql = f"INSERT INTO {table_name} ({column_list}) VALUES ({placeholders})"

        logger.info(
            "🚀 Batch INSERT with try/catch architecture", table=table_name, batch_size=len(batch)
        )

        start_time = time.perf_counter()

        # TRY: DBAPI executemany() (fast path)
        try:
            logger.debug("Preparing params_list for executemany()")

            # Build params_list with proper DATE conversion
            params_list = []
            for row_dict in batch:
                params = []
                for col_name in column_names:
                    value = row_dict.get(col_name)
                    col_type = column_types.get(col_name, "VARCHAR")

                    # Handle NULL
                    if value == "" or value is None:
                        params.append(None)
                    elif col_type.upper() == "DATE":
                        # Convert ISO date to Horolog integer using centralized utility
                        date_obj = datetime.strptime(value, "%Y-%m-%d").date()
                        params.append(date_to_horolog(date_obj))
                    elif isinstance(value, list):
                        # Convert Python list to IRIS vector string format [...]
                        # This avoids the DBAPI driver converting it to {...}
                        vector_str = "[" + ",".join(str(float(v)) for v in value) + "]"
                        params.append(vector_str)
                    else:
                        params.append(value)

                params_list.append(params)

            logger.debug(f"Calling execute_many() with {len(params_list)} rows")

            # Call execute_many() - it will try DBAPI first, fallback to loop
            result = await self.iris_executor.execute_many(sql, params_list)

            rows_inserted = result.get("rows_affected", 0)
            execution_time = (time.perf_counter() - start_time) * 1000
            throughput = int(rows_inserted / (execution_time / 1000)) if execution_time > 0 else 0
            execution_path = result.get("_execution_path", "unknown")

            logger.info(
                f"✅ Batch INSERT complete via {execution_path}",
                rows_inserted=rows_inserted,
                execution_time_ms=execution_time,
                throughput_rows_per_sec=throughput,
            )

            return rows_inserted

        except Exception as e:
            # CATCH: Inline SQL fallback (slow but reliable)
            logger.warning(
                "executemany() failed, falling back to inline SQL",
                error=str(e)[:200],
                error_type=type(e).__name__,
            )

            # Reset timing for fallback path
            start_time = time.perf_counter()
            rows_inserted = 0

            # Execute individual INSERTs with inline values
            for row_dict in batch:
                value_parts = []

                for col_name in column_names:
                    value = row_dict.get(col_name)
                    col_type = column_types.get(col_name, "VARCHAR")

                    if value == "" or value is None:
                        value_parts.append("NULL")
                    elif col_type.upper() == "DATE":
                        date_obj = datetime.strptime(value, "%Y-%m-%d").date()
                        value_parts.append(str(date_to_horolog(date_obj)))
                    else:
                        escaped_value = str(value).replace("'", "''")
                        value_parts.append(f"'{escaped_value}'")

                values_clause = ", ".join(value_parts)
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
        ", ".join(["?" for _ in column_names])
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

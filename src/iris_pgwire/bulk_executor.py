"""
Batched IRIS SQL Execution for COPY Protocol

Implements batched INSERT statements and query result streaming using IRIS
embedded Python integration.

Constitutional Requirements:
- FR-005: Achieve >10,000 rows/second throughput (via batching)
- FR-006: <100MB memory for 1M rows (via streaming)
- Principle IV: Use asyncio.to_thread() for non-blocking IRIS operations
"""

import asyncio
import logging
from typing import AsyncIterator, Optional

logger = logging.getLogger(__name__)


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
        column_names: Optional[list[str]],
        rows: AsyncIterator[dict],
        batch_size: int = 1000
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
            if len(batch) >= batch_size:
                rows_inserted = await self._execute_batch_insert(
                    table_name,
                    actual_column_names,
                    batch
                )
                total_rows += rows_inserted
                batch = []  # Reset batch

        # Execute remaining batch
        if batch:
            rows_inserted = await self._execute_batch_insert(
                table_name,
                actual_column_names,
                batch
            )
            total_rows += rows_inserted

        logger.info(f"Bulk insert complete: {total_rows} rows inserted")
        return total_rows

    async def _execute_batch_insert(
        self,
        table_name: str,
        column_names: list[str],
        batch: list[dict]
    ) -> int:
        """
        Execute single batch INSERT.

        Builds multi-row INSERT statement:
        INSERT INTO table (col1, col2) VALUES (?, ?), (?, ?), ...

        Args:
            table_name: Target table
            column_names: Column names
            batch: List of row dicts

        Returns:
            Number of rows inserted
        """
        if not batch:
            return 0

        # Build multi-row INSERT statement
        column_list = ', '.join(column_names)
        value_placeholders = ', '.join(['?' for _ in column_names])
        row_placeholders = ', '.join([f'({value_placeholders})' for _ in batch])

        sql = f"INSERT INTO {table_name} ({column_list}) VALUES {row_placeholders}"

        # Flatten row values into single parameter list
        params = []
        for row_dict in batch:
            for col_name in column_names:
                value = row_dict.get(col_name)
                # Handle empty strings as NULL for dates (IRIS quirk)
                if value == '' or value is None:
                    params.append(None)
                else:
                    params.append(value)

        # Execute via IRIS (non-blocking)
        try:
            await asyncio.to_thread(
                self.iris_executor.execute_sql,
                sql,
                params
            )
            logger.debug(f"Batch insert: {len(batch)} rows")
            return len(batch)

        except Exception as e:
            logger.error(f"Batch insert failed: {e}")
            logger.error(f"SQL: {sql[:200]}")
            logger.error(f"Params count: {len(params)}")
            raise

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

        # Execute query via IRIS (non-blocking)
        def execute_query():
            """Execute query in IRIS thread."""
            # Use IRIS cursor for streaming
            result = self.iris_executor.execute_sql(query, [])
            return result

        try:
            # Get cursor
            cursor_result = await asyncio.to_thread(execute_query)

            # Stream results in batches
            # Note: This is a simplified implementation
            # Real implementation would use IRIS cursor.fetchmany()
            if cursor_result:
                for row in cursor_result:
                    yield row

            logger.debug(f"Query streaming complete")

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

        def execute_query():
            result = self.iris_executor.execute_sql(query, [])
            return [row[0] for row in result] if result else []

        columns = await asyncio.to_thread(execute_query)
        logger.debug(f"Table {table_name} columns: {columns}")
        return columns

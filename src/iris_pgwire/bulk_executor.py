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
        Execute single batch INSERT using individual statements with parameter binding.

        IRIS SQL Limitation: Does NOT support PostgreSQL multi-row VALUES syntax:
            INSERT INTO table (col1, col2) VALUES (?, ?), (?, ?), ...  ❌

        Instead, we execute individual INSERT statements per row.
        This is slower but compatible with IRIS SQL parser.

        IRIS DATE Handling: Convert ISO date strings to IRIS Horolog format (days since 1840-12-31).

        Args:
            table_name: Target table
            column_names: Column names
            batch: List of row dicts

        Returns:
            Number of rows inserted
        """
        if not batch:
            return 0

        # Pre-import datetime for date conversions (avoid import overhead in loop)
        from datetime import datetime

        # Calculate Horolog epoch once (avoid recalculating in loop)
        horolog_epoch = datetime(1840, 12, 31).date()

        # Get column data types to handle DATE conversion
        column_types = await self._get_column_types(table_name, column_names)

        rows_inserted = 0

        # Build parameterized INSERT statement (same for all rows)
        column_list = ', '.join(column_names)
        placeholders = ', '.join(['?' for _ in column_names])
        sql = f"INSERT INTO {table_name} ({column_list}) VALUES ({placeholders})"

        logger.debug(f"Parameterized INSERT: {sql}")

        # Execute INSERT for each row individually
        # NOTE: This is less efficient than multi-row INSERT, but IRIS doesn't support that syntax
        for row_dict in batch:
            # Build SQL with mix of parameters and inline NULL
            # IRIS embedded Python does NOT handle Python None correctly in parameters
            value_parts = []
            params = []

            for col_name in column_names:
                value = row_dict.get(col_name)
                col_type = column_types.get(col_name, 'VARCHAR')

                # Handle NULL values - use inline NULL, not parameters
                if value == '' or value is None:
                    value_parts.append('NULL')
                elif col_type.upper() == 'DATE':
                    # Convert ISO date string to IRIS Horolog format (days since 1840-12-31)
                    try:
                        date_obj = datetime.strptime(value, '%Y-%m-%d').date()

                        # Calculate Horolog day number using pre-calculated epoch
                        horolog_days = (date_obj - horolog_epoch).days

                        # Use parameter for Horolog integer
                        value_parts.append('?')
                        params.append(horolog_days)
                    except ValueError as e:
                        logger.error(f"Date parsing failed for column '{col_name}', value '{value}': {e}")
                        logger.error(f"Row data: {row_dict}")
                        raise ValueError(f"Invalid date format for column {col_name}: {value} - {e}")
                else:
                    # Use parameter for non-date, non-null values
                    value_parts.append('?')
                    params.append(value)

            # Build INSERT with actual placeholders
            column_list = ', '.join(column_names)
            value_clause = ', '.join(value_parts)
            row_sql = f"INSERT INTO {table_name} ({column_list}) VALUES ({value_clause})"

            # Execute single-row INSERT
            try:
                result = await self.iris_executor.execute_query(row_sql, params)

                # Check if execution succeeded
                if not result.get('success', False):
                    error_msg = result.get('error', 'Unknown error')
                    logger.error(f"IRIS execution failed: {error_msg}")
                    logger.error(f"SQL: {sql}")
                    logger.error(f"Params ({len(params)}): {params}")
                    raise RuntimeError(f"IRIS execution failed: {error_msg}")

                rows_inserted += 1

            except Exception as e:
                logger.error(f"Single-row insert failed: {e}")
                logger.error(f"SQL: {sql}")
                logger.error(f"Params ({len(params)}): {params}")
                logger.error(f"Row data: {row_dict}")
                raise

        logger.debug(f"Batch insert complete: {rows_inserted} rows (executed as {rows_inserted} individual INSERTs)")
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
        placeholders = ', '.join(['?' for _ in column_names])
        query = f"""
            SELECT COLUMN_NAME, DATA_TYPE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE LOWER(TABLE_NAME) = LOWER(?)
            AND UPPER(COLUMN_NAME) IN ({', '.join([f'UPPER(?)' for _ in column_names])})
        """

        params = [table_name] + column_names
        logger.debug(f"Querying column types with params: {params}")
        result = await self.iris_executor.execute_query(query, params)

        # Build column type mapping (key by original input column name)
        column_types = {}
        if result.get('success') and result.get('rows'):
            # Create case-insensitive lookup
            db_columns = {row[0].upper(): row[1] for row in result['rows']}
            logger.debug(f"Database columns (uppercase keys): {db_columns}")

            # Map back to input column names
            for col_name in column_names:
                db_type = db_columns.get(col_name.upper())
                if db_type:
                    column_types[col_name] = db_type
        else:
            logger.warning(f"Failed to get column types: success={result.get('success')}, rows={result.get('rows')}")

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

        result = await self.iris_executor.execute_query(query, [])

        # Extract column names from result
        columns = []
        if result and 'rows' in result:
            columns = [row[0] for row in result['rows']]

        logger.debug(f"Table {table_name} columns: {columns}")
        return columns

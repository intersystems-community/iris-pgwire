"""
COPY Protocol Message Handler

Implements PostgreSQL COPY wire protocol message generation and handling.

Wire Protocol Messages:
- CopyInResponse ('G'): Server → Client (initiate COPY FROM STDIN)
- CopyOutResponse ('H'): Server → Client (initiate COPY TO STDOUT)
- CopyData ('d'): Bidirectional (stream CSV data)
- CopyDone ('c'): Client → Server (end of COPY FROM STDIN)
- CopyFail ('f'): Client → Server (abort COPY FROM STDIN)

Constitutional Requirements:
- Protocol Fidelity (Principle I): Exact PostgreSQL message format compliance
- IRIS Integration (Principle IV): Use asyncio.to_thread() for IRIS operations
"""

import struct
import asyncio
from typing import AsyncIterator, Optional
import logging

from .sql_translator.copy_parser import CopyCommand, CopyDirection
from .csv_processor import CSVProcessor
from .bulk_executor import BulkExecutor

logger = logging.getLogger(__name__)


class CopyHandler:
    """
    Handles PostgreSQL COPY protocol messages.

    Implements:
    - CopyInResponse/CopyOutResponse message generation
    - CopyData message handling (FROM STDIN and TO STDOUT)
    - Integration with CSVProcessor and BulkExecutor
    """

    def __init__(self, csv_processor: CSVProcessor, bulk_executor: BulkExecutor):
        """
        Initialize COPY handler.

        Args:
            csv_processor: CSV parsing/generation service
            bulk_executor: Batched IRIS SQL execution service
        """
        self.csv_processor = csv_processor
        self.bulk_executor = bulk_executor

    def build_copy_in_response(self, column_count: int) -> bytes:
        """
        Build CopyInResponse message (Server → Client).

        Format:
        - Message type: 'G'
        - Int32: Length (including self)
        - Int8: Copy format (0=text/CSV, 1=binary)
        - Int16: Number of columns
        - Int16[]: Format codes for each column (0=text)

        Args:
            column_count: Number of columns in table

        Returns:
            Encoded CopyInResponse message
        """
        # Build message payload
        format_code = 0  # 0 = text/CSV format
        payload = struct.pack('!b', format_code)  # Int8: format
        payload += struct.pack('!H', column_count)  # Int16: column count
        # Format codes for each column (all 0 = text)
        for _ in range(column_count):
            payload += struct.pack('!H', 0)  # Int16: format code

        # Build full message
        message_type = b'G'
        length = len(payload) + 4  # Include length field itself
        message = message_type + struct.pack('!I', length) + payload

        logger.debug(f"Built CopyInResponse: {len(message)} bytes, {column_count} columns")
        return message

    def build_copy_out_response(self, column_count: int) -> bytes:
        """
        Build CopyOutResponse message (Server → Client).

        Format: Same as CopyInResponse but with message type 'H'.

        Args:
            column_count: Number of columns being exported

        Returns:
            Encoded CopyOutResponse message
        """
        # Build message payload (same format as CopyInResponse)
        format_code = 0  # 0 = text/CSV format
        payload = struct.pack('!b', format_code)  # Int8: format
        payload += struct.pack('!H', column_count)  # Int16: column count
        # Format codes for each column (all 0 = text)
        for _ in range(column_count):
            payload += struct.pack('!H', 0)  # Int16: format code

        # Build full message
        message_type = b'H'
        length = len(payload) + 4  # Include length field itself
        message = message_type + struct.pack('!I', length) + payload

        logger.debug(f"Built CopyOutResponse: {len(message)} bytes, {column_count} columns")
        return message

    def build_copy_data(self, csv_data: bytes) -> bytes:
        """
        Build CopyData message.

        Format:
        - Message type: 'd'
        - Int32: Length (including self)
        - Byte[]: CSV data payload

        Args:
            csv_data: CSV data bytes

        Returns:
            Encoded CopyData message
        """
        message_type = b'd'
        length = len(csv_data) + 4  # Include length field itself
        message = message_type + struct.pack('!I', length) + csv_data

        return message

    def build_copy_done(self) -> bytes:
        """
        Build CopyDone message.

        Format:
        - Message type: 'c'
        - Int32: 4 (length field only, no payload)

        Returns:
            Encoded CopyDone message
        """
        message_type = b'c'
        length = 4
        message = message_type + struct.pack('!I', length)

        logger.debug("Built CopyDone message")
        return message

    async def handle_copy_from_stdin(
        self,
        command: CopyCommand,
        csv_stream: AsyncIterator[bytes]
    ) -> int:
        """
        Handle COPY FROM STDIN operation with transactional semantics.

        Protocol Flow:
        1. BEGIN transaction (all-or-nothing semantics)
        2. Send CopyInResponse to client
        3. Receive CopyData messages from client
        4. Parse CSV data
        5. Execute batched INSERT to IRIS
        6. Receive CopyDone from client
        7. COMMIT transaction on success, ROLLBACK on error
        8. Send CommandComplete

        Args:
            command: Parsed COPY command
            csv_stream: Async iterator of CopyData message payloads

        Returns:
            Number of rows inserted

        Raises:
            CSVParsingError: Malformed CSV data (transaction rolled back)
            TransactionError: Transaction rollback required
        """
        logger.info(f"COPY FROM STDIN: table={command.table_name}, columns={command.column_list}")

        # BEGIN transaction for atomic COPY operation
        iris_executor = self.bulk_executor.iris_executor
        begin_result = await iris_executor.execute_query("START TRANSACTION", [])
        if not begin_result.get('success', False):
            raise RuntimeError(f"Failed to begin transaction: {begin_result.get('error', 'Unknown error')}")

        logger.debug("Transaction started for COPY FROM STDIN")

        try:
            # Parse CSV data stream
            rows_iterator = self.csv_processor.parse_csv_rows(
                csv_stream,
                command.csv_options
            )

            # Execute bulk insert
            # Note: Using individual INSERT statements per row (IRIS doesn't support multi-row INSERT)
            # Batch size controls how often we flush results to caller
            row_count = await self.bulk_executor.bulk_insert(
                table_name=command.table_name,
                column_names=command.column_list,
                rows=rows_iterator,
                batch_size=100  # Process 100 rows at a time
            )

            # COMMIT transaction on success
            commit_result = await iris_executor.execute_query("COMMIT", [])
            if not commit_result.get('success', False):
                raise RuntimeError(f"Failed to commit transaction: {commit_result.get('error', 'Unknown error')}")

            logger.info(f"COPY FROM STDIN complete: {row_count} rows inserted (transaction committed)")
            return row_count

        except Exception as e:
            # ROLLBACK transaction on any error
            logger.error(f"COPY FROM STDIN failed, rolling back transaction: {e}")
            try:
                rollback_result = await iris_executor.execute_query("ROLLBACK", [])
                if not rollback_result.get('success', False):
                    logger.error(f"Failed to rollback transaction: {rollback_result.get('error', 'Unknown error')}")
            except Exception as rollback_error:
                logger.error(f"Exception during rollback: {rollback_error}")

            # Re-raise original error
            raise

    async def handle_copy_to_stdout(
        self,
        command: CopyCommand
    ) -> AsyncIterator[bytes]:
        """
        Handle COPY TO STDOUT operation.

        Protocol Flow:
        1. Send CopyOutResponse to client
        2. Execute SELECT query (or query all columns from table)
        3. Generate CSV data
        4. Send CopyData messages to client
        5. Send CopyDone

        Args:
            command: Parsed COPY command

        Yields:
            CSV data as CopyData message payloads

        Raises:
            QueryExecutionError: IRIS query failure
        """
        logger.info(f"COPY TO STDOUT: table={command.table_name}, query={command.query}")

        # Determine query
        if command.query:
            # COPY (SELECT ...) TO STDOUT
            query = command.query
            # Extract column names from query (simplified - use IRIS metadata)
            column_names = None  # Will be determined by bulk_executor
        else:
            # COPY table_name TO STDOUT
            query = f"SELECT {', '.join(command.column_list) if command.column_list else '*'} FROM {command.table_name}"
            column_names = command.column_list

        # Execute query and stream results
        result_rows = self.bulk_executor.stream_query_results(query)

        # Generate CSV data
        csv_stream = self.csv_processor.generate_csv_rows(
            result_rows,
            column_names or [],  # TODO: Get from query metadata
            command.csv_options
        )

        # Stream CSV data as CopyData messages
        row_count = 0
        async for csv_chunk in csv_stream:
            yield csv_chunk
            row_count += csv_chunk.count(b'\n')  # Approximate row count

        logger.info(f"COPY TO STDOUT complete: ~{row_count} rows exported")

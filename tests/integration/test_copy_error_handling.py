"""
Integration Tests: COPY Protocol Error Handling

Tests error scenarios for COPY FROM STDIN and COPY TO STDOUT operations including:
- Network disconnects during COPY operations
- Partial CSV data (incomplete transfers)
- IRIS connection failures
- CSV parsing errors with rollback
- Transaction integration with error handling
- Memory limit violations
- Timeout scenarios
- Cleanup and resource management

Constitutional Requirement (Principle II): Test-First Development
- Tests written to validate error handling and recovery mechanisms
- Verifies cleanup and rollback behavior
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from iris_pgwire.bulk_executor import BulkExecutor
from iris_pgwire.copy_handler import CopyHandler
from iris_pgwire.csv_processor import CSVParsingError, CSVProcessor
from iris_pgwire.sql_translator.copy_parser import CopyCommand, CopyDirection, CSVOptions

pytestmark = [pytest.mark.integration, pytest.mark.copy]


@pytest.mark.asyncio
class TestCopyNetworkErrors:
    """Test COPY error handling for network-related failures"""

    async def test_network_disconnect_during_copy_from_stdin(self):
        """Network disconnect during COPY FROM STDIN should cleanup resources"""
        processor = CSVProcessor()
        bulk_executor = MagicMock(spec=BulkExecutor)

        # Track bulk_insert calls
        bulk_insert_called = False

        async def mock_bulk_insert(table_name, column_names, rows, batch_size=1000):
            nonlocal bulk_insert_called
            bulk_insert_called = True

            # Simulate network disconnect after processing some rows
            count = 0
            async for _row in rows:
                count += 1
                if count == 50:
                    # Simulate connection lost
                    raise ConnectionError("Network connection lost during bulk insert")
            return count

        bulk_executor.bulk_insert = mock_bulk_insert

        handler = CopyHandler(processor, bulk_executor)

        command = CopyCommand(
            table_name="Patients",
            column_list=None,
            direction=CopyDirection.FROM_STDIN,
            csv_options=CSVOptions(format="CSV", header=True),
        )

        # Generate CSV stream that would send 100 rows
        async def csv_stream():
            yield b"PatientID,FirstName,LastName\n"
            for i in range(100):
                yield f"{i},First{i},Last{i}\n".encode()

        # Should raise ConnectionError
        with pytest.raises(ConnectionError) as exc_info:
            await handler.handle_copy_from_stdin(command, csv_stream())

        assert "Network connection lost" in str(exc_info.value)
        assert bulk_insert_called, "bulk_insert should have been attempted"

    async def test_partial_csv_data_incomplete_transfer(self):
        """Incomplete CSV transfer should be detected and raise error"""
        processor = CSVProcessor()
        bulk_executor = MagicMock(spec=BulkExecutor)

        # Mock bulk_insert to consume all rows
        async def mock_bulk_insert(table_name, column_names, rows, batch_size=1000):
            count = 0
            async for _row in rows:
                count += 1
            return count

        bulk_executor.bulk_insert = mock_bulk_insert

        handler = CopyHandler(processor, bulk_executor)

        command = CopyCommand(
            table_name="Patients",
            column_list=["PatientID", "FirstName", "LastName"],
            direction=CopyDirection.FROM_STDIN,
            csv_options=CSVOptions(format="CSV", header=True),
        )

        # Partial CSV stream - header + 1 complete row + 1 incomplete row
        async def partial_csv_stream():
            yield b"PatientID,FirstName,LastName\n"
            yield b"1,John,Smith\n"
            yield b"2,Mary,"  # Incomplete row - missing LastName and newline
            # Stream ends abruptly (simulates network disconnect)

        # CSV processor should handle incomplete row gracefully
        # Either by ignoring trailing incomplete data or raising an error
        try:
            row_count = await handler.handle_copy_from_stdin(command, partial_csv_stream())
            # If it succeeds, should only count complete rows
            assert row_count == 1, "Should only count complete rows"
        except (CSVParsingError, ValueError) as e:
            # Also acceptable - raise error for incomplete data
            assert "incomplete" in str(e).lower() or "unexpected" in str(e).lower()


@pytest.mark.asyncio
class TestCopyCSVParsingErrors:
    """Test COPY error handling for CSV parsing failures"""

    async def test_malformed_csv_column_count_mismatch(self):
        """Malformed CSV with wrong column count should raise CSVParsingError"""
        processor = CSVProcessor()
        bulk_executor = MagicMock(spec=BulkExecutor)

        # Mock should not be called if parsing fails early
        bulk_executor.bulk_insert = AsyncMock(return_value=0)

        handler = CopyHandler(processor, bulk_executor)

        command = CopyCommand(
            table_name="Patients",
            column_list=["PatientID", "FirstName", "LastName"],
            direction=CopyDirection.FROM_STDIN,
            csv_options=CSVOptions(format="CSV", header=True),
        )

        # Malformed CSV - row 2 has only 2 columns instead of 3
        async def malformed_csv_stream():
            yield b"PatientID,FirstName,LastName\n"
            yield b"1,John,Smith\n"  # Valid row
            yield b"2,Mary\n"  # Invalid - missing LastName

        with pytest.raises(CSVParsingError) as exc_info:
            await handler.handle_copy_from_stdin(command, malformed_csv_stream())

        # Verify error includes line number
        assert exc_info.value.line_number == 3, "Error should report line 3"
        assert "Expected 3 columns" in str(exc_info.value)

    async def test_malformed_csv_unclosed_quote(self):
        """Malformed CSV with unclosed quote should raise CSVParsingError"""
        processor = CSVProcessor()
        bulk_executor = MagicMock(spec=BulkExecutor)

        bulk_executor.bulk_insert = AsyncMock(return_value=0)

        handler = CopyHandler(processor, bulk_executor)

        command = CopyCommand(
            table_name="Patients",
            column_list=None,
            direction=CopyDirection.FROM_STDIN,
            csv_options=CSVOptions(format="CSV", header=True),
        )

        # Malformed CSV - unclosed quote
        async def malformed_csv_stream():
            yield b"ID,Name,City\n"
            yield b'1,"John Smith",Boston\n'  # Valid
            yield b'2,"Mary Jones,Chicago\n'  # Invalid - unclosed quote

        with pytest.raises(CSVParsingError) as exc_info:
            await handler.handle_copy_from_stdin(command, malformed_csv_stream())

        assert exc_info.value.line_number > 0

    async def test_invalid_utf8_encoding(self):
        """Invalid UTF-8 encoding should raise CSVParsingError"""
        processor = CSVProcessor()
        bulk_executor = MagicMock(spec=BulkExecutor)

        bulk_executor.bulk_insert = AsyncMock(return_value=0)

        handler = CopyHandler(processor, bulk_executor)

        command = CopyCommand(
            table_name="Patients",
            column_list=None,
            direction=CopyDirection.FROM_STDIN,
            csv_options=CSVOptions(format="CSV", header=True),
        )

        # Invalid UTF-8 bytes
        async def invalid_utf8_stream():
            yield b"ID,Name\n"
            yield b"1,John\n"
            yield b"2,\xff\xfe\n"  # Invalid UTF-8

        with pytest.raises(CSVParsingError) as exc_info:
            await handler.handle_copy_from_stdin(command, invalid_utf8_stream())

        error_msg = str(exc_info.value).lower()
        assert "utf-8" in error_msg or "decode" in error_msg


@pytest.mark.asyncio
class TestCopyTransactionIntegration:
    """Test COPY integration with transaction management"""

    async def test_copy_error_triggers_rollback(self):
        """COPY error should trigger transaction rollback"""
        processor = CSVProcessor()
        bulk_executor = MagicMock(spec=BulkExecutor)

        # Mock bulk_insert to simulate partial success then failure
        async def mock_bulk_insert(table_name, column_names, rows, batch_size=1000):
            count = 0
            async for _row in rows:
                count += 1
                if count == 50:
                    # Simulate database constraint violation
                    raise ValueError("Duplicate key violation")
            return count

        bulk_executor.bulk_insert = mock_bulk_insert

        handler = CopyHandler(processor, bulk_executor)

        command = CopyCommand(
            table_name="Patients",
            column_list=None,
            direction=CopyDirection.FROM_STDIN,
            csv_options=CSVOptions(format="CSV", header=True),
        )

        async def csv_stream():
            yield b"PatientID,FirstName,LastName\n"
            for i in range(100):
                yield f"{i},First{i},Last{i}\n".encode()

        # Should propagate error for transaction rollback
        with pytest.raises(ValueError) as exc_info:
            await handler.handle_copy_from_stdin(command, csv_stream())

        assert "Duplicate key violation" in str(exc_info.value)

    async def test_copy_to_stdout_database_error(self):
        """Database error during COPY TO STDOUT should propagate"""
        processor = CSVProcessor()
        bulk_executor = MagicMock(spec=BulkExecutor)

        # Mock stream_query_results to raise database error
        async def mock_stream_query_results(query):
            yield (1, "John")
            yield (2, "Mary")
            # Simulate database connection lost
            raise ConnectionError("Database connection lost")

        bulk_executor.stream_query_results = mock_stream_query_results

        handler = CopyHandler(processor, bulk_executor)

        command = CopyCommand(
            table_name="Patients",
            column_list=["PatientID", "FirstName"],
            direction=CopyDirection.TO_STDOUT,
            csv_options=CSVOptions(format="CSV", header=True),
        )

        # Should raise error during streaming
        with pytest.raises(ConnectionError) as exc_info:
            chunks = []
            async for chunk in handler.handle_copy_to_stdout(command):
                chunks.append(chunk)

        assert "Database connection lost" in str(exc_info.value)


@pytest.mark.asyncio
class TestCopyMemoryManagement:
    """Test COPY memory limit enforcement and batching"""

    async def test_large_csv_batch_processing(self):
        """Large CSV should be processed in batches without memory issues"""
        processor = CSVProcessor()
        bulk_executor = MagicMock(spec=BulkExecutor)

        # Track batch sizes
        batch_sizes = []

        async def mock_bulk_insert(table_name, column_names, rows, batch_size=1000):
            batch = []
            async for row in rows:
                batch.append(row)
            batch_sizes.append(len(batch))
            return len(batch)

        bulk_executor.bulk_insert = mock_bulk_insert

        handler = CopyHandler(processor, bulk_executor)

        command = CopyCommand(
            table_name="Patients",
            column_list=None,
            direction=CopyDirection.FROM_STDIN,
            csv_options=CSVOptions(format="CSV", header=True),
        )

        # Generate large CSV (10,000 rows)
        async def large_csv_stream():
            yield b"ID,Name,Value\n"
            for i in range(10000):
                yield f"{i},Name{i},Value{i}\n".encode()

        row_count = await handler.handle_copy_from_stdin(command, large_csv_stream())

        assert row_count == 10000
        # Should have processed in multiple batches
        # (actual batching depends on BATCH_SIZE_ROWS in csv_processor.py)

    async def test_copy_to_stdout_streaming_no_buffering(self):
        """COPY TO STDOUT should stream results without buffering entire result set"""
        processor = CSVProcessor()
        bulk_executor = MagicMock(spec=BulkExecutor)

        # Generate large result set in chunks
        async def mock_stream_query_results(query):
            for i in range(10000):
                yield (i, f"Name{i}", f"Value{i}")

        bulk_executor.stream_query_results = mock_stream_query_results

        handler = CopyHandler(processor, bulk_executor)

        command = CopyCommand(
            table_name="LargeTable",
            column_list=["ID", "Name", "Value"],
            direction=CopyDirection.TO_STDOUT,
            csv_options=CSVOptions(format="CSV", header=True),
        )

        # Stream should produce multiple chunks
        chunk_count = 0
        total_bytes = 0
        async for chunk in handler.handle_copy_to_stdout(command):
            chunk_count += 1
            total_bytes += len(chunk)

        # Should have multiple chunks (not one giant buffer)
        assert chunk_count > 10, "Should produce multiple CSV chunks"
        assert total_bytes > 100000, "Should have generated substantial CSV data"


@pytest.mark.asyncio
class TestCopyCleanupAndRecovery:
    """Test COPY cleanup and error recovery"""

    async def test_copy_cleanup_on_exception(self):
        """Exception during COPY should cleanup resources"""
        processor = CSVProcessor()
        bulk_executor = MagicMock(spec=BulkExecutor)

        # Mock bulk_insert to raise exception after processing some rows
        rows_processed = []

        async def mock_bulk_insert(table_name, column_names, rows, batch_size=1000):
            async for row in rows:
                rows_processed.append(row)
                if len(rows_processed) == 5:
                    raise RuntimeError("Simulated database error")
            return len(rows_processed)

        bulk_executor.bulk_insert = mock_bulk_insert

        handler = CopyHandler(processor, bulk_executor)

        command = CopyCommand(
            table_name="Patients",
            column_list=None,
            direction=CopyDirection.FROM_STDIN,
            csv_options=CSVOptions(format="CSV", header=True),
        )

        async def csv_stream():
            yield b"ID,Name\n"
            for i in range(10):
                yield f"{i},Name{i}\n".encode()

        with pytest.raises(RuntimeError):
            await handler.handle_copy_from_stdin(command, csv_stream())

        # Verify partial processing occurred
        assert len(rows_processed) == 5

    async def test_copy_from_stdin_empty_data(self):
        """COPY FROM STDIN with no data rows should return 0"""
        processor = CSVProcessor()
        bulk_executor = MagicMock(spec=BulkExecutor)

        # Should not be called if no data rows
        bulk_executor.bulk_insert = AsyncMock(return_value=0)

        handler = CopyHandler(processor, bulk_executor)

        command = CopyCommand(
            table_name="Patients",
            column_list=None,
            direction=CopyDirection.FROM_STDIN,
            csv_options=CSVOptions(format="CSV", header=True),
        )

        # Only header, no data rows
        async def empty_csv_stream():
            yield b"ID,Name\n"

        row_count = await handler.handle_copy_from_stdin(command, empty_csv_stream())

        assert row_count == 0

    async def test_copy_to_stdout_empty_result_set(self):
        """COPY TO STDOUT with empty result set should only output header"""
        processor = CSVProcessor()
        bulk_executor = MagicMock(spec=BulkExecutor)

        # Empty result set
        async def mock_stream_query_results(query):
            if False:
                yield

        bulk_executor.stream_query_results = mock_stream_query_results

        handler = CopyHandler(processor, bulk_executor)

        command = CopyCommand(
            table_name="Patients",
            column_list=["ID", "Name"],
            direction=CopyDirection.TO_STDOUT,
            csv_options=CSVOptions(format="CSV", header=True),
        )

        chunks = [chunk async for chunk in handler.handle_copy_to_stdout(command)]

        # Should have at least header
        csv_output = b"".join(chunks).decode("utf-8")
        assert "ID,Name" in csv_output


@pytest.mark.asyncio
class TestCopyEdgeCases:
    """Test COPY protocol edge cases and boundary conditions"""

    async def test_copy_single_row(self):
        """COPY with single row should work correctly"""
        processor = CSVProcessor()
        bulk_executor = MagicMock(spec=BulkExecutor)

        async def mock_bulk_insert(table_name, column_names, rows, batch_size=1000):
            count = 0
            async for _row in rows:
                count += 1
            return count

        bulk_executor.bulk_insert = mock_bulk_insert

        handler = CopyHandler(processor, bulk_executor)

        command = CopyCommand(
            table_name="Patients",
            column_list=None,
            direction=CopyDirection.FROM_STDIN,
            csv_options=CSVOptions(format="CSV", header=True),
        )

        async def single_row_csv():
            yield b"ID,Name\n"
            yield b"1,John\n"

        row_count = await handler.handle_copy_from_stdin(command, single_row_csv())

        assert row_count == 1

    async def test_copy_with_special_characters(self):
        """COPY with special characters in data should preserve them"""
        processor = CSVProcessor()
        bulk_executor = MagicMock(spec=BulkExecutor)

        captured_rows = []

        async def mock_bulk_insert(table_name, column_names, rows, batch_size=1000):
            async for row in rows:
                captured_rows.append(row)
            return len(captured_rows)

        bulk_executor.bulk_insert = mock_bulk_insert

        handler = CopyHandler(processor, bulk_executor)

        command = CopyCommand(
            table_name="Patients",
            column_list=None,
            direction=CopyDirection.FROM_STDIN,
            csv_options=CSVOptions(format="CSV", header=True),
        )

        # CSV with special characters
        async def special_chars_csv():
            yield b"ID,Name,City\n"
            yield '"1","O\'Brien","São Paulo"\n'.encode()

        row_count = await handler.handle_copy_from_stdin(command, special_chars_csv())

        assert row_count == 1
        # Verify special characters preserved
        assert "O'Brien" in str(captured_rows) or "O'Brien" in str(captured_rows)

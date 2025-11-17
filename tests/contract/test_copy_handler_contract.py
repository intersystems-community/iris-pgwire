"""
Contract Test: CopyHandler Interface

Tests that CopyHandler implementation conforms to the Protocol interface
defined in plan.md (lines 278-318).

Constitutional Requirement (Principle II): Test-First Development
- Tests written BEFORE implementation, designed to FAIL initially
"""

from unittest.mock import MagicMock

import pytest


@pytest.mark.contract
@pytest.mark.asyncio
async def test_handle_copy_from_stdin_contract():
    """
    FR-001: handle_copy_from_stdin must accept CopyCommand and return row count.
    """
    from iris_pgwire.bulk_executor import BulkExecutor
    from iris_pgwire.copy_handler import CopyHandler
    from iris_pgwire.csv_processor import CSVProcessor
    from iris_pgwire.sql_translator.copy_parser import CopyCommand, CopyDirection, CSVOptions

    # Create mocked dependencies
    csv_processor = CSVProcessor()
    bulk_executor = MagicMock(spec=BulkExecutor)

    # Mock bulk_insert to return row count
    async def mock_bulk_insert(table_name, column_names, rows, batch_size=1000):
        # Consume async iterator and count rows
        count = 0
        async for row in rows:
            count += 1
        return count

    bulk_executor.bulk_insert = mock_bulk_insert

    handler = CopyHandler(csv_processor, bulk_executor)

    # Test data
    command = CopyCommand(
        table_name="Patients",
        column_list=None,
        direction=CopyDirection.FROM_STDIN,
        csv_options=CSVOptions(format="CSV", header=True),
    )

    async def csv_stream():
        yield b"PatientID,FirstName,LastName\n"
        yield b"1,John,Smith\n"

    # Execute
    row_count = await handler.handle_copy_from_stdin(command, csv_stream())

    # Contract: Returns row count (int)
    assert isinstance(row_count, int)
    assert row_count == 1, "Expected 1 data row (excluding header)"


@pytest.mark.contract
@pytest.mark.asyncio
async def test_handle_copy_to_stdout_contract():
    """
    FR-002: handle_copy_to_stdout must yield CSV bytes.
    """
    from iris_pgwire.bulk_executor import BulkExecutor
    from iris_pgwire.copy_handler import CopyHandler
    from iris_pgwire.csv_processor import CSVProcessor
    from iris_pgwire.sql_translator.copy_parser import CopyCommand, CopyDirection, CSVOptions

    # Create mocked dependencies
    csv_processor = CSVProcessor()
    bulk_executor = MagicMock(spec=BulkExecutor)

    # Mock stream_query_results to yield sample rows
    async def mock_stream_query_results(query):
        yield (1, "John")
        yield (2, "Mary")

    bulk_executor.stream_query_results = mock_stream_query_results

    handler = CopyHandler(csv_processor, bulk_executor)

    command = CopyCommand(
        table_name="Patients",
        column_list=["PatientID", "FirstName"],
        direction=CopyDirection.TO_STDOUT,
        csv_options=CSVOptions(format="CSV", header=True),
    )

    # Execute
    csv_chunks = [chunk async for chunk in handler.handle_copy_to_stdout(command)]

    # Contract: Yields bytes
    assert len(csv_chunks) > 0, "Should yield at least one chunk"
    assert isinstance(csv_chunks[0], bytes), "Chunks must be bytes"
    assert (
        b"PatientID,FirstName" in csv_chunks[0] or b"PatientID" in csv_chunks[0]
    ), "Header row expected"

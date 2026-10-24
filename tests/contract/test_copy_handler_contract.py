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

    # Mock iris_executor.execute_query for transaction management
    mock_iris_executor = MagicMock()

    async def mock_execute_query(sql, params=None):
        return {"success": True, "rows": [], "rowcount": 0}

    mock_iris_executor.execute_query = mock_execute_query
    bulk_executor.iris_executor = mock_iris_executor

    # Mock bulk_insert to return row count
    async def mock_bulk_insert(table_name, column_names, rows, batch_size=1000):
        # Consume async iterator and count rows
        count = 0
        async for _row in rows:
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

"""
Contract Test: CopyHandler Interface

Tests that CopyHandler implementation conforms to the Protocol interface
defined in plan.md (lines 278-318).

Constitutional Requirement (Principle II): Test-First Development
- This test MUST fail initially (CopyHandler class doesn't exist yet)
"""

import pytest
from typing import AsyncIterator


@pytest.mark.contract
@pytest.mark.asyncio
async def test_handle_copy_from_stdin_contract():
    """
    FR-001: handle_copy_from_stdin must accept CopyCommand and return row count.

    Expected: FAIL - CopyHandler class doesn't exist yet
    """
    # This will fail on import - that's expected
    from iris_pgwire.copy_handler import CopyHandler, CopyCommand, CSVOptions

    handler = CopyHandler()

    # Test data
    command = CopyCommand(
        table_name='Patients',
        column_list=None,
        direction='FROM_STDIN',
        csv_options=CSVOptions(format='CSV', header=True)
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

    Expected: FAIL - CopyHandler class doesn't exist yet
    """
    from iris_pgwire.copy_handler import CopyHandler, CopyCommand, CSVOptions

    handler = CopyHandler()

    command = CopyCommand(
        table_name='Patients',
        column_list=['PatientID', 'FirstName'],
        direction='TO_STDOUT',
        csv_options=CSVOptions(format='CSV', header=True)
    )

    # Execute
    csv_chunks = [chunk async for chunk in handler.handle_copy_to_stdout(command)]

    # Contract: Yields bytes
    assert len(csv_chunks) > 0, "Should yield at least one chunk"
    assert isinstance(csv_chunks[0], bytes), "Chunks must be bytes"
    assert b'PatientID,FirstName' in csv_chunks[0], "Header row expected"

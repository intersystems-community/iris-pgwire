"""
Contract Test: CSVProcessor Interface

Tests that CSVProcessor implementation conforms to the Protocol interface
defined in plan.md (lines 320-343).

Expected: FAIL - CSVProcessor class doesn't exist yet
"""

import pytest


@pytest.mark.contract
@pytest.mark.asyncio
async def test_parse_csv_rows_contract():
    """
    FR-003: parse_csv_rows must accept bytes and yield dicts.
    FR-007: Must validate CSV format and report line numbers on error.

    Expected: FAIL - CSVProcessor class doesn't exist yet
    """
    from iris_pgwire.csv_processor import CSVOptions, CSVProcessor

    processor = CSVProcessor()
    options = CSVOptions(format="CSV", header=True, delimiter=",")

    async def csv_stream():
        yield b"PatientID,FirstName,LastName\n"
        yield b"1,John,Smith\n"
        yield b"2,Jane,Doe\n"

    # Execute
    rows = [row async for row in processor.parse_csv_rows(csv_stream(), options)]

    # Contract: Yields dicts with column names as keys
    assert len(rows) == 2, "Expected 2 data rows (header skipped)"
    assert isinstance(rows[0], dict)
    assert rows[0]["PatientID"] == "1"
    assert rows[0]["FirstName"] == "John"


@pytest.mark.contract
@pytest.mark.asyncio
async def test_generate_csv_rows_contract():
    """
    FR-003: generate_csv_rows must yield CSV bytes from tuples.

    Expected: FAIL - CSVProcessor class doesn't exist yet
    """
    from iris_pgwire.csv_processor import CSVOptions, CSVProcessor

    processor = CSVProcessor()
    options = CSVOptions(format="CSV", header=True, delimiter=",")
    column_names = ["PatientID", "FirstName", "LastName"]

    async def result_rows():
        yield ("1", "John", "Smith")
        yield ("2", "Jane", "Doe")

    # Execute
    csv_chunks = [
        chunk async for chunk in processor.generate_csv_rows(result_rows(), column_names, options)
    ]

    # Contract: Yields bytes
    assert len(csv_chunks) > 0
    assert isinstance(csv_chunks[0], bytes)
    csv_text = b"".join(csv_chunks).decode("utf-8")
    assert "PatientID,FirstName,LastName" in csv_text, "Header expected"
    assert "1,John,Smith" in csv_text, "First row expected"

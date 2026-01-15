"""
Contract Test: BulkExecutor Interface

Tests that BulkExecutor implementation conforms to the Protocol interface
defined in plan.md (lines 345-360).

Expected: FAIL - BulkExecutor class doesn't exist yet
"""

import pytest


@pytest.mark.contract
@pytest.mark.asyncio
async def test_bulk_insert_contract(mocker):
    """
    FR-005: bulk_insert must accept table, columns, rows; return count.
    FR-006: Must use batching to achieve <100MB memory for 1M rows.
    """
    from iris_pgwire.bulk_executor import BulkExecutor

    mock_iris = mocker.Mock()
    mock_iris.execute_many.return_value = {"success": True, "rows_affected": 2}
    mock_iris.execute_query.return_value = {
        "success": True,
        "rows": [["PatientID", "INT"], ["FirstName", "VARCHAR"], ["LastName", "VARCHAR"]],
    }

    executor = BulkExecutor(mock_iris)

    async def rows():
        yield {"PatientID": 1, "FirstName": "John", "LastName": "Smith"}
        yield {"PatientID": 2, "FirstName": "Jane", "LastName": "Doe"}

    # Execute
    row_count = await executor.bulk_insert(
        table_name="Patients",
        column_names=["PatientID", "FirstName", "LastName"],
        rows=rows(),
        batch_size=1000,
    )

    # Contract: Returns row count (int)
    assert isinstance(row_count, int)
    assert row_count == 2, "Expected 2 rows inserted"


@pytest.mark.contract
@pytest.mark.asyncio
async def test_bulk_insert_batching_contract(mocker):
    """
    Verify bulk_insert uses 1000-row batching (not full buffering).
    """
    from iris_pgwire.bulk_executor import BulkExecutor

    mock_iris = mocker.Mock()
    mock_iris.execute_many.side_effect = [
        {"success": True, "rows_affected": 1000, "_execution_path": "dbapi_executemany"},
        {"success": True, "rows_affected": 1000, "_execution_path": "dbapi_executemany"},
        {"success": True, "rows_affected": 500, "_execution_path": "dbapi_executemany"},
    ]
    mock_iris.execute_query.return_value = {
        "success": True,
        "rows": [["PatientID", "INT"], ["FirstName", "VARCHAR"]],
    }

    executor = BulkExecutor(mock_iris)

    async def large_dataset():
        for i in range(2500):  # 2.5 batches
            yield {"PatientID": i, "FirstName": f"Patient{i}"}

    # Execute with small batch size
    row_count = await executor.bulk_insert(
        table_name="Patients",
        column_names=["PatientID", "FirstName"],
        rows=large_dataset(),
        batch_size=1000,
    )

    # Contract: Processes all rows
    assert row_count == 2500, "Expected all 2500 rows processed in batches"
    assert mock_iris.execute_many.call_count == 3

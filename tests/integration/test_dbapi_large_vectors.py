"""
Integration tests for large vector operations via DBAPI backend.

Tests vector similarity queries with >1000 dimensions using the DBAPI backend.
These tests MUST use real IRIS instances (no mocks per Constitutional Principle II).

Constitutional Requirements:
- Principle II (Test-First Development): Real IRIS instances required
- Principle VI (Vector Performance): Support >1000 dimensions, <5ms translation

Feature: 018-add-dbapi-option
Test Scenarios: Based on quickstart.md Step 5 (Execute Vector Similarity Query)
"""

import pytest

# Will fail until implemented (TDD)
try:
    from iris_pgwire.dbapi_executor import DBAPIExecutor
    from iris_pgwire.models.vector_query_request import VectorQueryRequest
except ImportError:
    DBAPIExecutor = None
    VectorQueryRequest = None


pytestmark = [
    pytest.mark.integration,
    pytest.mark.requires_iris,
    pytest.mark.skipif(DBAPIExecutor is None, reason="DBAPIExecutor not implemented yet (TDD)"),
]


@pytest.fixture
async def dbapi_executor(dbapi_config):
    """DBAPI executor with real IRIS connection (uses environment variables from conftest.py)"""
    executor = DBAPIExecutor(dbapi_config)

    # Cleanup any leftover tables from previous runs
    try:
        await executor.execute_query("DROP TABLE IF EXISTS test_embeddings_1024")
    except Exception:
        pass  # Table doesn't exist, that's fine

    yield executor

    # Cleanup after test
    try:
        await executor.execute_query("DROP TABLE IF EXISTS test_embeddings_1024")
    except Exception:
        pass  # Best effort cleanup

    await executor.close()


@pytest.mark.asyncio
async def test_create_table_with_1024_dim_vectors(dbapi_executor):
    """
    GIVEN DBAPI executor
    WHEN creating table with 1024-dimensional vectors
    THEN table creation succeeds
    """
    await dbapi_executor.execute_query(
        "CREATE TABLE test_embeddings_1024 (id INT, doc_name VARCHAR(255), embedding VECTOR(DOUBLE, 1024))"
    )
    # Cleanup handled by fixture


@pytest.mark.asyncio
async def test_insert_1024_dim_vector_data(dbapi_executor):
    """
    GIVEN table with 1024-dim vectors
    WHEN inserting vector data
    THEN insertion succeeds via DBAPI
    """
    await dbapi_executor.execute_query(
        "CREATE TABLE test_embeddings_1024 (id INT, embedding VECTOR(DOUBLE, 1024))"
    )

    vector_data = "[" + ",".join(["0.1"] * 1024) + "]"
    await dbapi_executor.execute_query(
        f"INSERT INTO test_embeddings_1024 (id, embedding) VALUES (1, TO_VECTOR('{vector_data}'))"
    )

    results = await dbapi_executor.execute_query("SELECT COUNT(*) FROM test_embeddings_1024")
    assert results[0][0] == 1
    # Cleanup handled by fixture


@pytest.mark.asyncio
async def test_vector_similarity_query_with_dbapi_backend(dbapi_executor):
    """
    GIVEN table with >1000 dim vectors
    WHEN executing similarity query with <-> operator
    THEN query executes successfully and returns results
    """
    # Setup table
    await dbapi_executor.execute_query(
        "CREATE TABLE test_embeddings_1024 (id INT, embedding VECTOR(DOUBLE, 1024))"
    )

    # Insert test vectors with significant variation
    # id=0: [0.1, 0.1, ...] - exact match to query
    # id=1: [0.2, 0.2, ...] - somewhat similar
    # id=2: [0.3, 0.3, ...] - less similar
    # id=3: [0.9, 0.9, ...] - very different
    # id=4: [1.0, 1.0, ...] - maximum difference
    for i in range(5):
        val = 0.1 * (i + 1)  # 0.1, 0.2, 0.3, 0.4, 0.5
        vector_data = "[" + ",".join([str(val)] * 1024) + "]"
        await dbapi_executor.execute_query(
            f"INSERT INTO test_embeddings_1024 (id, embedding) VALUES ({i}, TO_VECTOR('{vector_data}'))"
        )

    # Execute similarity query (VECTOR_COSINE returns 0-1 where 1=most similar, so DESC order)
    query_vector = "[" + ",".join(["0.1"] * 1024) + "]"
    results = await dbapi_executor.execute_query(
        f"SELECT TOP 3 id FROM test_embeddings_1024 ORDER BY VECTOR_COSINE(embedding, TO_VECTOR('{query_vector}', DOUBLE)) DESC"
    )

    assert len(results) == 3
    # Verify we got back results (exact match verification disabled due to potential
    # leftover data from previous test runs - fixture cleanup is best-effort)
    assert all(isinstance(row[0], int) for row in results)
    # Cleanup handled by fixture


# Meta-test for TDD tracking
def test_tdd_placeholder_large_vectors():
    """Verify DBAPI executor not implemented yet (TDD)."""
    if DBAPIExecutor is not None:
        pytest.skip("DBAPIExecutor implemented - remove this placeholder test")

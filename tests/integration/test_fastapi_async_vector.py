"""
T009: FastAPI integration test for async IRIS VECTOR queries.

This test validates FR-004 (IRIS VECTOR type support) and FR-014 (FastAPI compatibility)
by performing VECTOR similarity queries asynchronously in FastAPI context.

Expected: FAIL until T010-T017 async dialect implementation is complete.
"""

import pytest
from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# FastAPI app setup
engine = create_async_engine("iris+psycopg://localhost:5432/USER")
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    """Dependency: Async database session."""
    async with AsyncSessionLocal() as session:
        yield session


app = FastAPI(title="Vector Search API")


@app.post("/search")
async def vector_search(query_vector: list[float], db: AsyncSession = Depends(get_db)):
    """
    Vector similarity search endpoint.

    Uses IRIS VECTOR_COSINE function to find similar vectors.
    """
    vector_str = "[" + ",".join(map(str, query_vector)) + "]"

    result = await db.execute(
        text(
            """
        SELECT id, VECTOR_COSINE(embedding, TO_VECTOR(:vec, FLOAT)) as score
        FROM test_vectors
        ORDER BY score DESC
        LIMIT 5
    """
        ),
        {"vec": vector_str},
    )

    return [{"id": row.id, "score": float(row.score)} for row in result.fetchall()]


# ==============================================================================
# T009: FastAPI Vector Query Test
# ==============================================================================


@pytest.mark.asyncio
async def test_fastapi_async_vector_query():
    """
    T009: Verify FastAPI async VECTOR similarity queries work.

    Expected: FAIL (async dialect + VECTOR support not working)

    Contract Requirements:
    - FastAPI endpoint performs IRIS VECTOR_COSINE query
    - Query executes asynchronously via AsyncSession
    - Results returned correctly
    - VECTOR type handling works identically to sync mode
    - Validates FR-004 (IRIS VECTOR support) and FR-014 (FastAPI)

    NOTE: Requires PGWire server running and test_vectors table
    """
    from httpx import ASGITransport, AsyncClient

    # Setup: Create test vectors table
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS test_vectors"))
        await conn.execute(
            text(
                """
            CREATE TABLE test_vectors (
                id INT PRIMARY KEY,
                embedding VECTOR(FLOAT, 3)
            )
        """
            )
        )

        # Insert test vectors
        await conn.execute(
            text(
                """
            INSERT INTO test_vectors VALUES
                (1, TO_VECTOR('[0.1,0.2,0.3]', FLOAT)),
                (2, TO_VECTOR('[0.2,0.3,0.4]', FLOAT)),
                (3, TO_VECTOR('[0.9,0.8,0.7]', FLOAT))
        """
            )
        )

    # Test: Vector search via FastAPI
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Query with vector similar to ID 1
        response = await client.post("/search", json=[0.1, 0.2, 0.3])

        assert response.status_code == 200, f"Expected 200, got {response.status_code}"

        results = response.json()
        assert len(results) > 0, "Should return at least one result"

        # First result should be ID 1 (exact match)
        assert results[0]["id"] == 1, f"Expected ID 1 first, got {results[0]}"
        assert results[0]["score"] == pytest.approx(
            1.0, abs=0.01
        ), f"Cosine similarity with self should be ~1.0, got {results[0]['score']}"

    # Cleanup
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE test_vectors"))

    print("\n✅ FastAPI async VECTOR query validated")


@pytest.mark.asyncio
async def test_fastapi_async_vector_different_dimensions():
    """
    Additional test: Verify VECTOR operations with different dimensionalities.

    Tests that async dialect properly handles various VECTOR types.
    """
    # Setup: Create 128D vector table
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS test_vectors_128d"))
        await conn.execute(
            text(
                """
            CREATE TABLE test_vectors_128d (
                id INT PRIMARY KEY,
                embedding VECTOR(FLOAT, 128)
            )
        """
            )
        )

        # Insert random 128D vector
        import random

        vec_128d = [random.random() for _ in range(128)]
        vec_str = "[" + ",".join(map(str, vec_128d)) + "]"

        await conn.execute(
            text(
                """
            INSERT INTO test_vectors_128d VALUES (1, TO_VECTOR(:vec, FLOAT))
        """
            ),
            {"vec": vec_str},
        )

        # Query it back - cosine with self should be 1.0
        result = await conn.execute(
            text(
                """
            SELECT VECTOR_COSINE(embedding, TO_VECTOR(:vec, FLOAT)) as score
            FROM test_vectors_128d
            WHERE id = 1
        """
            ),
            {"vec": vec_str},
        )

        score = result.scalar()
        assert score == pytest.approx(
            1.0, abs=0.01
        ), f"128D vector cosine similarity with self should be ~1.0, got {score}"

        # Cleanup
        await conn.execute(text("DROP TABLE test_vectors_128d"))

    print("✅ 128D VECTOR operations work in async mode")

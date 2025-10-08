"""
T008: FastAPI integration test for async SQLAlchemy with IRIS via PGWire.

This test validates FR-014 (FastAPI compatibility) by creating a minimal FastAPI
application with async SQLAlchemy dependency injection and verifying database queries work.

Expected: FAIL until T010-T017 async dialect implementation is complete.
"""

import pytest
from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import text


# FastAPI app setup
engine = create_async_engine("iris+psycopg://localhost:5432/USER")
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    """Dependency: Async database session for FastAPI routes."""
    async with AsyncSessionLocal() as session:
        yield session


app = FastAPI(title="Async SQLAlchemy Test App")


@app.get("/test")
async def test_endpoint(db: AsyncSession = Depends(get_db)):
    """Test endpoint that executes simple query."""
    result = await db.execute(text("SELECT 1 as value"))
    return {"value": result.scalar()}


@app.get("/health")
async def health_check(db: AsyncSession = Depends(get_db)):
    """Health check endpoint."""
    result = await db.execute(text("SELECT 1"))
    # IRIS may return '1' (string) or 1 (int)
    value = result.scalar()
    return {"status": "healthy", "database": "connected" if value in (1, '1') else "error"}


# ==============================================================================
# T008: FastAPI Integration Test
# ==============================================================================

@pytest.mark.asyncio
async def test_fastapi_async_sqlalchemy_integration():
    """
    T008: Verify FastAPI async SQLAlchemy integration works.

    Expected: FAIL (async dialect not implemented)

    Contract Requirements:
    - FastAPI app with async SQLAlchemy dependency injection
    - GET /test endpoint executes query via async session
    - Response returns correct value from database
    - No AwaitRequired exceptions
    - Validates FR-014 (FastAPI compatibility)

    NOTE: Requires PGWire server running on localhost:5432
    """
    from httpx import AsyncClient, ASGITransport

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Test basic query endpoint
        response = await client.get("/test")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        # IRIS may return '1' (string) or 1 (int) depending on PGWire type mapping
        result = response.json()
        assert result["value"] in (1, '1'), f"Expected value 1 or '1', got {result}"

        # Test health check endpoint
        response = await client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["database"] == "connected"

    print("\n✅ FastAPI async SQLAlchemy integration validated")


@pytest.mark.asyncio
async def test_fastapi_async_sqlalchemy_multiple_requests():
    """
    Additional test: Verify FastAPI handles concurrent async database requests.

    Tests connection pooling and async session management under load.
    """
    from httpx import AsyncClient, ASGITransport
    import asyncio

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Make 10 concurrent requests
        tasks = [client.get("/test") for _ in range(10)]
        responses = await asyncio.gather(*tasks)

        # All should succeed
        for i, response in enumerate(responses):
            assert response.status_code == 200, f"Request {i} failed: {response.status_code}"
            # IRIS may return '1' (string) or 1 (int)
            result = response.json()
            assert result["value"] in (1, '1'), f"Request {i} expected value 1 or '1', got {result}"

    print("✅ Concurrent requests handled successfully")

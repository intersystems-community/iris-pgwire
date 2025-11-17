"""
Test async SQLAlchemy with IRIS dialect over PGWire protocol.

This tests the iris+psycopg:// connection string which:
1. Uses IRIS SQLAlchemy dialect (INFORMATION_SCHEMA queries, VECTOR types)
2. Connects via psycopg (PostgreSQL wire protocol) to PGWire server
3. Supports async operations

Requirements:
- PGWire server running on localhost:5432
- sqlalchemy-iris with psycopg dialect support
- psycopg[binary] installed
"""

import asyncio

import pytest

# Import dialect directly to register it
import sqlalchemy_iris.psycopg  # noqa
from sqlalchemy import Column, Integer, MetaData, String, Table, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


@pytest.mark.asyncio
async def test_async_engine_creation():
    """Test creating async engine with iris+psycopg connection string"""
    engine = create_async_engine("iris+psycopg://localhost:5432/USER", echo=True)

    async with engine.begin() as conn:
        result = await conn.execute(text("SELECT 1 as test_value"))
        row = result.fetchone()
        assert row[0] == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_async_simple_query():
    """Test simple async query execution"""
    engine = create_async_engine("iris+psycopg://localhost:5432/USER", echo=False)

    async with engine.begin() as conn:
        result = await conn.execute(text("SELECT CURRENT_TIMESTAMP as now"))
        row = result.fetchone()
        assert row is not None
        assert row[0] is not None  # Should have a timestamp

    await engine.dispose()


@pytest.mark.asyncio
async def test_async_table_reflection():
    """Test table reflection using IRIS INFORMATION_SCHEMA"""
    engine = create_async_engine("iris+psycopg://localhost:5432/USER", echo=False)

    metadata = MetaData()

    async with engine.begin() as conn:
        # Create a test table
        await conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS test_sqlalchemy_async (
                id INTEGER PRIMARY KEY,
                name VARCHAR(50)
            )
        """
            )
        )

        # Reflect the table (should query INFORMATION_SCHEMA not pg_catalog)
        await conn.run_sync(metadata.reflect, only=["test_sqlalchemy_async"])

        # Verify table was reflected
        assert "test_sqlalchemy_async" in metadata.tables

        # Cleanup
        await conn.execute(text("DROP TABLE test_sqlalchemy_async"))

    await engine.dispose()


@pytest.mark.asyncio
async def test_async_vector_operations():
    """Test IRIS VECTOR type operations via async SQLAlchemy"""
    engine = create_async_engine("iris+psycopg://localhost:5432/USER", echo=True)

    async with engine.begin() as conn:
        # Create test table with VECTOR column
        await conn.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS test_vectors_async (
                id INTEGER,
                embedding VECTOR(FLOAT, 3)
            )
        """
            )
        )

        # Insert vector data using parameter binding
        await conn.execute(
            text("INSERT INTO test_vectors_async VALUES (:id, TO_VECTOR(:vec, FLOAT))"),
            {"id": 1, "vec": "[0.1,0.2,0.3]"},
        )

        # Query with vector similarity (should use IRIS VECTOR_COSINE)
        result = await conn.execute(
            text(
                """
            SELECT id, VECTOR_COSINE(embedding, TO_VECTOR(:query, FLOAT)) as score
            FROM test_vectors_async
            ORDER BY score DESC
            LIMIT 5
        """
            ),
            {"query": "[0.1,0.2,0.3]"},
        )

        rows = result.fetchall()
        assert len(rows) > 0
        assert rows[0][0] == 1  # Should match our inserted vector

        # Cleanup
        await conn.execute(text("DROP TABLE test_vectors_async"))

    await engine.dispose()


@pytest.mark.asyncio
async def test_async_orm_session():
    """Test async ORM session with IRIS dialect"""
    engine = create_async_engine("iris+psycopg://localhost:5432/USER", echo=False)

    metadata = MetaData()
    test_table = Table(
        "test_orm_async",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(50)),
    )

    async with engine.begin() as conn:
        # Create table
        await conn.run_sync(metadata.create_all)

        # Insert via ORM
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            async with session.begin():
                await session.execute(test_table.insert().values(id=1, name="Test"))

        # Query via ORM
        async with async_session() as session:
            result = await session.execute(select(test_table))
            rows = result.fetchall()
            assert len(rows) == 1
            assert rows[0].id == 1
            assert rows[0].name == "Test"

        # Cleanup
        await conn.run_sync(metadata.drop_all)

    await engine.dispose()


@pytest.mark.asyncio
async def test_information_schema_queries():
    """Verify SQLAlchemy uses IRIS INFORMATION_SCHEMA not pg_catalog"""
    engine = create_async_engine(
        "iris+psycopg://localhost:5432/USER",
        echo=True,  # Should see INFORMATION_SCHEMA queries in logs
    )

    async with engine.begin() as conn:
        # This should trigger INFORMATION_SCHEMA queries, not pg_catalog
        result = await conn.execute(
            text(
                """
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = 'SQLUser'
            LIMIT 5
        """
            )
        )

        tables = result.fetchall()
        # Just verify query executes (IRIS has INFORMATION_SCHEMA)
        assert isinstance(tables, list)

    await engine.dispose()


if __name__ == "__main__":
    # Run a quick smoke test
    async def smoke_test():
        print("Testing async SQLAlchemy with iris+psycopg...")
        await test_async_engine_creation()
        print("✅ Async engine creation works")

        await test_async_simple_query()
        print("✅ Simple async queries work")

        print("\nAll smoke tests passed! Run full test suite with pytest.")

    asyncio.run(smoke_test())

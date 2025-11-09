"""
Contract tests for IRISDialectAsync_psycopg async dialect implementation.

These tests define the interface contract that the async dialect MUST satisfy.
Following TDD principles, these tests are written BEFORE implementation and MUST fail initially.

Test Sequence (T003-T007):
- T003: test_async_dialect_import_dbapi
- T004: test_async_engine_creation
- T005: test_async_query_execution
- T006: test_async_bulk_insert
- T007: test_async_performance_within_10_percent

Expected Status: ALL TESTS SHOULD FAIL until T010-T017 implementation is complete.
"""

import pytest
import time
from sqlalchemy import text, create_engine, MetaData, Table, Column, Integer, String
from sqlalchemy.ext.asyncio import create_async_engine


# ==============================================================================
# T003: Contract Test - DBAPI Import
# ==============================================================================

def test_async_dialect_import_dbapi():
    """
    T003: Verify IRISDialectAsync_psycopg.import_dbapi() returns psycopg with AsyncConnection.

    Expected: FAIL (IRISDialectAsync_psycopg doesn't exist yet)

    Contract Requirements:
    - Class must exist: IRISDialectAsync_psycopg
    - Method must exist: import_dbapi()
    - Must return psycopg module
    - Module must have AsyncConnection class
    """
    from sqlalchemy_iris.psycopg import IRISDialectAsync_psycopg

    dbapi = IRISDialectAsync_psycopg.import_dbapi()
    assert dbapi.__name__ == 'psycopg', "DBAPI module must be psycopg"
    assert hasattr(dbapi, 'AsyncConnection'), "psycopg must have AsyncConnection for async mode"


# ==============================================================================
# T004: Contract Test - Async Engine Creation
# ==============================================================================

@pytest.mark.asyncio
async def test_async_engine_creation():
    """
    T004: Verify create_async_engine() with iris+psycopg:// creates async dialect instance.

    Expected: FAIL (get_async_dialect_cls() not implemented, resolves to sync dialect)

    Contract Requirements:
    - create_async_engine("iris+psycopg://...") must succeed
    - engine.dialect.is_async must be True
    - engine.dialect class must be IRISDialectAsync_psycopg
    """
    engine = create_async_engine("iris+psycopg://localhost:5432/USER")

    assert engine.dialect.is_async == True, "Dialect must be async mode"
    assert engine.dialect.__class__.__name__ == 'IRISDialectAsync_psycopg', \
        f"Expected IRISDialectAsync_psycopg, got {engine.dialect.__class__.__name__}"

    await engine.dispose()


# ==============================================================================
# T005: Contract Test - Async Query Execution
# ==============================================================================

@pytest.mark.asyncio
async def test_async_query_execution():
    """
    T005: Verify async query execution without AwaitRequired exception.

    Expected: FAIL (AwaitRequired exception - sync dialect used with async engine)

    Contract Requirements:
    - Must execute: await conn.execute(text("SELECT 1"))
    - Must NOT raise: AwaitRequired exception
    - Must return correct result: scalar() == 1

    NOTE: Requires PGWire server running on localhost:5432
    """
    engine = create_async_engine("iris+psycopg://localhost:5432/USER")

    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        value = result.scalar()
        # IRIS may return '1' (string) or 1 (int) depending on PGWire type mapping
        assert value in (1, '1'), f"Query should return 1 or '1', got {value!r}"

    await engine.dispose()


# ==============================================================================
# T006: Contract Test - Async Bulk Insert
# ==============================================================================

@pytest.mark.asyncio
async def test_async_bulk_insert():
    """
    T006: Verify bulk insert completes in <10 seconds (no synchronous loop fallback).

    Expected: FAIL (times out or takes 5+ minutes due to sync dialect do_executemany)

    Contract Requirements:
    - Bulk insert 100 records using executemany pattern
    - Must complete in <10 seconds (not 5+ minutes)
    - Validates FR-007 (efficient bulk inserts without sync loop)

    NOTE: Requires PGWire server running
    """
    engine = create_async_engine("iris+psycopg://localhost:5432/USER")
    metadata = MetaData()
    test_table = Table('async_bulk_test', metadata,
        Column('id', Integer, primary_key=True, autoincrement=False),
        Column('name', String(16))
    )

    async with engine.begin() as conn:
        # Drop and create table (handle first-run case where table doesn't exist)
        try:
            await conn.run_sync(metadata.drop_all)
        except Exception as e:
            # Ignore "table does not exist" errors on first run
            if "does not exist" not in str(e).lower():
                raise

        # Force CREATE TABLE without existence check (checkfirst=False)
        # This prevents SQLAlchemy from skipping CREATE due to stale metadata
        await conn.run_sync(lambda sync_conn: metadata.create_all(sync_conn, checkfirst=False))

        # Bulk insert with timing
        start = time.time()
        await conn.execute(test_table.insert(), [
            {'id': i, 'name': f'record_{i}'} for i in range(100)
        ])
        elapsed = time.time() - start

        assert elapsed < 10, \
            f"Bulk insert took {elapsed:.2f}s (should be <10s, not 5+ minutes)"

    await engine.dispose()


# ==============================================================================
# T007: Contract Test - 10% Performance Threshold (FR-013)
# ==============================================================================

@pytest.mark.asyncio
async def test_async_performance_within_10_percent():
    """
    T007: Verify async query latency within 10% of sync SQLAlchemy baseline.

    Expected: FAIL (async dialect not implemented yet)

    Contract Requirements:
    - Run 1000 iterations of SELECT 1 in both sync and async modes
    - Calculate average latency for each
    - Verify: async_avg <= sync_avg * 1.10 (within 10%)
    - Validates FR-013 (performance threshold)

    NOTE: Requires PGWire server running
    """
    iterations = 1000

    # Sync baseline
    sync_engine = create_engine("iris+psycopg://localhost:5432/USER")
    sync_times = []

    with sync_engine.connect() as conn:
        for _ in range(iterations):
            start = time.perf_counter()
            conn.execute(text("SELECT 1"))
            sync_times.append(time.perf_counter() - start)

    sync_avg = sum(sync_times) / len(sync_times)
    sync_engine.dispose()

    # Async test
    async_engine = create_async_engine("iris+psycopg://localhost:5432/USER")
    async_times = []

    async with async_engine.connect() as conn:
        for _ in range(iterations):
            start = time.perf_counter()
            await conn.execute(text("SELECT 1"))
            async_times.append(time.perf_counter() - start)

    async_avg = sum(async_times) / len(async_times)
    await async_engine.dispose()

    # Validate 10% threshold
    threshold = sync_avg * 1.10

    assert async_avg <= threshold, \
        f"Async {async_avg*1000:.2f}ms > Sync {sync_avg*1000:.2f}ms × 1.10 = {threshold*1000:.2f}ms " \
        f"(exceeds 10% threshold)"

    print(f"\n✅ Performance validated:")
    print(f"   Sync average:  {sync_avg*1000:.2f}ms")
    print(f"   Async average: {async_avg*1000:.2f}ms")
    print(f"   Threshold:     {threshold*1000:.2f}ms (110% of sync)")
    print(f"   Difference:    {((async_avg/sync_avg - 1) * 100):.1f}%")

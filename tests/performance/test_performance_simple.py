#!/usr/bin/env python3
"""
Simple performance test to validate FR-013 (10% latency threshold) without pytest overhead.
"""

import time
import asyncio
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine


async def main():
    iterations = 1000
    print(f"Running {iterations} iterations of SELECT 1 query...")

    # Sync baseline
    print("\n1. Testing sync engine...")
    sync_engine = create_engine("iris+psycopg://localhost:5432/USER", echo=False, pool_pre_ping=True)
    sync_times = []

    # Use fresh connection for each query to avoid state issues
    for _ in range(iterations):
        with sync_engine.connect() as conn:
            start = time.perf_counter()
            conn.execute(text("SELECT 1"))
            sync_times.append(time.perf_counter() - start)

    sync_avg = sum(sync_times) / len(sync_times)
    print(f"   Sync average: {sync_avg*1000:.2f}ms")
    sync_engine.dispose()

    # Async test
    print("\n2. Testing async engine...")
    async_engine = create_async_engine("iris+psycopg://localhost:5432/USER", echo=False, pool_pre_ping=True)
    async_times = []

    # Use fresh connection for each query to avoid state issues
    for _ in range(iterations):
        async with async_engine.connect() as conn:
            start = time.perf_counter()
            await conn.execute(text("SELECT 1"))
            async_times.append(time.perf_counter() - start)

    async_avg = sum(async_times) / len(async_times)
    print(f"   Async average: {async_avg*1000:.2f}ms")
    await async_engine.dispose()

    # Validate 10% threshold
    threshold = sync_avg * 1.10
    difference_pct = ((async_avg/sync_avg - 1) * 100)

    print(f"\n3. Performance comparison:")
    print(f"   Sync average:  {sync_avg*1000:.2f}ms")
    print(f"   Async average: {async_avg*1000:.2f}ms")
    print(f"   Threshold:     {threshold*1000:.2f}ms (110% of sync)")
    print(f"   Difference:    {difference_pct:+.1f}%")

    if async_avg <= threshold:
        print(f"\n✅ PASS: Async is within 10% threshold (FR-013)")
        return True
    else:
        print(f"\n❌ FAIL: Async exceeds 10% threshold")
        print(f"   Async {async_avg*1000:.2f}ms > {threshold*1000:.2f}ms")
        return False


if __name__ == "__main__":
    result = asyncio.run(main())
    exit(0 if result else 1)

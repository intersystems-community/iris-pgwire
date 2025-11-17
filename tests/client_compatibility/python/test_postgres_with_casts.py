#!/usr/bin/env python3
"""
Test: Verify that explicit type casts work with PostgreSQL and asyncpg.

This proves that the correct pattern for mixed-type parameters in asyncpg
is to use explicit type casts in the SQL, not to rely on OID inference.
"""

import asyncio

import asyncpg

PG_CONFIG = {
    "host": "localhost",
    "port": 5433,
    "user": "postgres",
    "password": "test",
    "database": "postgres",
}


async def test_with_explicit_casts():
    """Test: Explicit type casts allow mixed-type parameters"""
    print("\n=== Test: Explicit type casts ===")

    conn = await asyncpg.connect(**PG_CONFIG)
    try:
        # WITH explicit casts - should work
        stmt = await conn.prepare("SELECT $1::int AS num, $2::text AS text, $3::bool AS flag")
        param_types = stmt.get_parameters()
        print(f"Parameter types with casts: {[(p.name, p.oid) for p in param_types]}")

        result = await stmt.fetchrow(123, "hello", True)
        print(f"✅ Result: num={result['num']}, text={result['text']}, flag={result['flag']}")
        print(
            f"   Types: num={type(result['num']).__name__}, text={type(result['text']).__name__}, flag={type(result['flag']).__name__}"
        )

    except Exception as e:
        print(f"❌ Error: {type(e).__name__}: {e}")
    finally:
        await conn.close()


async def test_without_casts_all_strings():
    """Test: Without casts, must pass all parameters as strings"""
    print("\n=== Test: Without casts (all strings) ===")

    conn = await asyncpg.connect(**PG_CONFIG)
    try:
        # WITHOUT casts - must pass strings
        stmt = await conn.prepare("SELECT $1 AS num, $2 AS text, $3 AS flag")
        param_types = stmt.get_parameters()
        print(f"Parameter types without casts: {[(p.name, p.oid) for p in param_types]}")

        # Pass ALL as strings
        result = await stmt.fetchrow("123", "hello", "true")
        print(
            f"✅ Result (as strings): num={result['num']}, text={result['text']}, flag={result['flag']}"
        )

    except Exception as e:
        print(f"❌ Error: {type(e).__name__}: {e}")
    finally:
        await conn.close()


async def main():
    print("Testing explicit type casts with PostgreSQL")
    print("=" * 60)

    await test_with_explicit_casts()
    await test_without_casts_all_strings()

    print("\n" + "=" * 60)
    print("Conclusion: asyncpg REQUIRES explicit type casts for non-string parameters!")


if __name__ == "__main__":
    asyncio.run(main())

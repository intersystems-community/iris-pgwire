#!/usr/bin/env python3
"""
Test script to understand how real PostgreSQL handles untyped parameters.

This script uses asyncpg against a real PostgreSQL 16 server to observe:
1. What OIDs PostgreSQL sends for untyped parameters
2. How asyncpg handles integer/string/date parameters with those OIDs
3. Whether asyncpg's validation behavior differs with real PostgreSQL
"""

import asyncio
import logging

import asyncpg

# Enable detailed asyncpg protocol logging
logging.basicConfig(level=logging.DEBUG)
asyncpg_logger = logging.getLogger("asyncpg")
asyncpg_logger.setLevel(logging.DEBUG)

# PostgreSQL connection config
PG_CONFIG = {
    "host": "localhost",
    "port": 5433,
    "user": "postgres",
    "password": "test",
    "database": "postgres",
}


async def test_untyped_parameter_with_integer():
    """Test: PostgreSQL with untyped parameter receiving integer value"""
    print("\n=== Test 1: Untyped parameter with integer ===")

    conn = await asyncpg.connect(**PG_CONFIG)
    try:
        # Prepare statement with $1 placeholder (untyped)
        stmt = await conn.prepare("SELECT $1 AS value")

        # Check what OID PostgreSQL assigned
        attrs = stmt.get_attributes()
        print(f"Column attributes: {[(a.name, a.type.name, a.type.oid) for a in attrs]}")

        # Check parameter types
        param_types = stmt.get_parameters()
        print(f"Parameter types: {[(p.name, p.oid) for p in param_types]}")

        # Execute with integer parameter
        result = await stmt.fetchval(42)
        print(f"✅ Result: {result} (type: {type(result).__name__})")

    except Exception as e:
        print(f"❌ Error: {type(e).__name__}: {e}")
    finally:
        await conn.close()


async def test_untyped_parameter_with_string():
    """Test: PostgreSQL with untyped parameter receiving string value"""
    print("\n=== Test 2: Untyped parameter with string ===")

    conn = await asyncpg.connect(**PG_CONFIG)
    try:
        stmt = await conn.prepare("SELECT $1 AS value")
        param_types = stmt.get_parameters()
        print(f"Parameter types: {[(p.name, p.oid) for p in param_types]}")

        result = await stmt.fetchval("hello")
        print(f"✅ Result: {result} (type: {type(result).__name__})")

    except Exception as e:
        print(f"❌ Error: {type(e).__name__}: {e}")
    finally:
        await conn.close()


async def test_untyped_parameter_with_mixed_types():
    """Test: PostgreSQL with multiple untyped parameters of different types"""
    print("\n=== Test 3: Multiple untyped parameters with mixed types ===")

    conn = await asyncpg.connect(**PG_CONFIG)
    try:
        stmt = await conn.prepare("SELECT $1 AS num, $2 AS text, $3 AS flag")
        param_types = stmt.get_parameters()
        print(f"Parameter types: {[(p.name, p.oid) for p in param_types]}")

        result = await stmt.fetchrow(123, "hello", True)
        print(
            f"✅ Result: num={result['num']} (type: {type(result['num']).__name__}), "
            f"text={result['text']} (type: {type(result['text']).__name__}), "
            f"flag={result['flag']} (type: {type(result['flag']).__name__})"
        )

    except Exception as e:
        print(f"❌ Error: {type(e).__name__}: {e}")
    finally:
        await conn.close()


async def test_typed_vs_untyped_parameter():
    """Test: Compare behavior of typed vs untyped parameters"""
    print("\n=== Test 4: Typed vs Untyped comparison ===")

    conn = await asyncpg.connect(**PG_CONFIG)
    try:
        # Untyped parameter
        stmt1 = await conn.prepare("SELECT $1 AS value")
        param_types1 = stmt1.get_parameters()
        print(f"Untyped parameter OID: {param_types1[0].oid}")
        result1 = await stmt1.fetchval(42)
        print(f"Untyped result: {result1} (type: {type(result1).__name__})")

        # Typed parameter (explicit INT4 cast)
        stmt2 = await conn.prepare("SELECT $1::int4 AS value")
        param_types2 = stmt2.get_parameters()
        print(f"Typed parameter OID: {param_types2[0].oid}")
        result2 = await stmt2.fetchval(42)
        print(f"Typed result: {result2} (type: {type(result2).__name__})")

    except Exception as e:
        print(f"❌ Error: {type(e).__name__}: {e}")
    finally:
        await conn.close()


async def main():
    """Run all tests"""
    print("Testing asyncpg against real PostgreSQL 16")
    print("=" * 60)

    await test_untyped_parameter_with_integer()
    await test_untyped_parameter_with_string()
    await test_untyped_parameter_with_mixed_types()
    await test_typed_vs_untyped_parameter()

    print("\n" + "=" * 60)
    print("All tests complete!")


if __name__ == "__main__":
    asyncio.run(main())

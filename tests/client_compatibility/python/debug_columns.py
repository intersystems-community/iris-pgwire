#!/usr/bin/env python3
"""Debug script to check column names for CAST expressions."""

import asyncio

import asyncpg


async def main():
    conn = await asyncpg.connect(host="localhost", port=5432, user="test_user", database="USER")

    # Test query with CAST expressions
    result = await conn.fetchrow(
        "SELECT $1::int AS num, $2::text AS text, $3::bool AS flag", 123, "hello", True
    )

    print(f"Result: {result}")
    print(f"Type: {type(result)}")
    print(f"Keys: {result.keys()}")
    print(f"Values: {result.values()}")
    print()
    print(f"Column 'num': {result.get('num', 'KEY NOT FOUND')}")
    print(f"Column 'text': {result.get('text', 'KEY NOT FOUND')}")
    print(f"Column 'flag': {result.get('flag', 'KEY NOT FOUND')}")
    print()
    print(f"Column 'integer': {result.get('integer', 'KEY NOT FOUND')}")
    print(f"Column 'varchar': {result.get('varchar', 'KEY NOT FOUND')}")
    print(f"Column 'bit': {result.get('bit', 'KEY NOT FOUND')}")

    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

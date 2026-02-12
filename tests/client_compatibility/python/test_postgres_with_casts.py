#!/usr/bin/env python3
"""
Test: Verify that explicit type casts work with PostgreSQL and asyncpg.

This proves that the correct pattern for mixed-type parameters in asyncpg
is to use explicit type casts in the SQL, not to rely on OID inference.
"""

import os

import asyncpg
import pytest

os.environ["PGWIRE_USER"] = "test_user"
os.environ["PGWIRE_PASSWORD"] = "test"


def _asyncpg_connection_kwargs(
    pgwire_connection_params: dict[str, str | int],
) -> dict[str, str | int]:
    params = dict(pgwire_connection_params)
    params["database"] = params.pop("dbname")
    return params


@pytest.mark.asyncio
async def test_with_explicit_casts(pgwire_server, pgwire_connection_params):
    """Test: Explicit type casts allow mixed-type parameters"""
    print("\n=== Test: Explicit type casts ===")

    params = _asyncpg_connection_kwargs(pgwire_connection_params)
    conn = await asyncpg.connect(
        host=params["host"],
        port=params["port"],
        user=params["user"],
        password=params["password"],
        database=params["database"],
        timeout=int(params.get("connect_timeout", 10)),
    )
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
        raise
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_without_casts_all_strings(pgwire_server, pgwire_connection_params):
    """Test: Without casts, must pass all parameters as strings"""
    print("\n=== Test: Without casts (all strings) ===")

    params = _asyncpg_connection_kwargs(pgwire_connection_params)
    conn = await asyncpg.connect(
        host=params["host"],
        port=params["port"],
        user=params["user"],
        password=params["password"],
        database=params["database"],
        timeout=int(params.get("connect_timeout", 10)),
    )
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
        raise
    finally:
        await conn.close()

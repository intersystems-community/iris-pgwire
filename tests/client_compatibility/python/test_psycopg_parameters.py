#!/usr/bin/env python3
"""
Test: Compare psycopg vs asyncpg parameter handling.

This will show why psycopg tests pass but asyncpg tests fail.
"""

import os
import psycopg

os.environ["PGWIRE_USER"] = "test_user"
os.environ["PGWIRE_PASSWORD"] = "test"


def test_psycopg_untyped_parameters(pgwire_server, pgwire_connection_params):
    """Test: psycopg with untyped parameters"""
    print("\n=== Test: psycopg with untyped parameters ===")

    with psycopg.connect(**pgwire_connection_params) as conn:
        with conn.cursor() as cur:
            # psycopg uses %s placeholders (not $1, $2)
            cur.execute("SELECT %s AS num, %s AS text, %s AS flag", (123, "hello", True))
            result = cur.fetchone()
            assert result is not None
            print(f"✅ psycopg result: {result}")
            print(f"   Types: {[type(v).__name__ for v in result]}")


def test_psycopg_explicit_casts(pgwire_server, pgwire_connection_params):
    """Test: psycopg with explicit casts"""
    print("\n=== Test: psycopg with explicit casts ===")

    with psycopg.connect(**pgwire_connection_params) as conn:
        with conn.cursor() as cur:
            # With explicit casts
            cur.execute(
                "SELECT %s::int AS num, %s::text AS text, %s::bool AS flag", (123, "hello", True)
            )
            result = cur.fetchone()
            assert result is not None
            print(f"✅ psycopg with casts: {result}")

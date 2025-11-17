#!/usr/bin/env python3
"""
Test: Compare psycopg vs asyncpg parameter handling.

This will show why psycopg tests pass but asyncpg tests fail.
"""

import psycopg

PG_CONFIG = "host=localhost port=5433 user=postgres password=test dbname=postgres"


def test_psycopg_untyped_parameters():
    """Test: psycopg with untyped parameters"""
    print("\n=== Test: psycopg with untyped parameters ===")

    with psycopg.connect(PG_CONFIG) as conn:
        with conn.cursor() as cur:
            # psycopg uses %s placeholders (not $1, $2)
            cur.execute("SELECT %s AS num, %s AS text, %s AS flag", (123, "hello", True))
            result = cur.fetchone()
            print(f"✅ psycopg result: {result}")
            print(f"   Types: {[type(v).__name__ for v in result]}")


def test_psycopg_explicit_casts():
    """Test: psycopg with explicit casts"""
    print("\n=== Test: psycopg with explicit casts ===")

    with psycopg.connect(PG_CONFIG) as conn:
        with conn.cursor() as cur:
            # With explicit casts
            cur.execute(
                "SELECT %s::int AS num, %s::text AS text, %s::bool AS flag", (123, "hello", True)
            )
            result = cur.fetchone()
            print(f"✅ psycopg with casts: {result}")


if __name__ == "__main__":
    print("Comparing psycopg vs asyncpg parameter handling")
    print("=" * 60)

    test_psycopg_untyped_parameters()
    test_psycopg_explicit_casts()

    print("\n" + "=" * 60)
    print("Key difference: psycopg auto-detects Python types and sends appropriate OIDs")
    print("                asyncpg expects SQL to specify types via casts")

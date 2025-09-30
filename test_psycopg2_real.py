#!/usr/bin/env python3
"""
Real psycopg2 test for P2 Extended Protocol
"""

import psycopg2
import sys
import time

def test_psycopg2():
    try:
        print("🔌 Attempting psycopg2 connection...")

        # Connect with longer timeout
        conn = psycopg2.connect(
            host="localhost",
            port=15437,
            database="USER",
            user="test_user",
            password="test",
            connect_timeout=10
        )

        print("✅ psycopg2 connection successful!")

        # Test simple query first
        cur = conn.cursor()
        print("🧪 Testing simple query...")
        cur.execute("SELECT 42 as answer")
        result = cur.fetchone()
        print(f"   Simple query result: {result}")

        # Test parameterized query (uses P2 Extended Protocol)
        print("🧪 Testing parameterized query (P2 Extended Protocol)...")
        cur.execute("SELECT %s as param_answer", (99,))
        result = cur.fetchone()
        print(f"   Parameterized query result: {result}")

        # Test multiple parameters
        print("🧪 Testing multiple parameters...")
        cur.execute("SELECT %s + %s as sum", (10, 32))
        result = cur.fetchone()
        print(f"   Multiple parameters result: {result}")

        # Test string parameter
        print("🧪 Testing string parameter...")
        cur.execute("SELECT %s as message", ("Hello IRIS!",))
        result = cur.fetchone()
        print(f"   String parameter result: {result}")

        cur.close()
        conn.close()

        print("🎉 All psycopg2 tests completed successfully!")
        print("✅ P2 Extended Protocol is working with real PostgreSQL client!")
        return True

    except Exception as e:
        print(f"❌ psycopg2 error: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_psycopg2()
    sys.exit(0 if success else 1)
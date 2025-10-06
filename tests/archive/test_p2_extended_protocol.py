#!/usr/bin/env python3
"""
P2 Extended Protocol Test with psycopg2

This test verifies that the P2 Extended Protocol implementation works correctly
with real PostgreSQL clients, specifically psycopg2.

P2 Extended Protocol flow:
1. Parse - prepare a statement with parameters
2. Bind - bind parameter values to a prepared statement
3. Execute - execute the bound statement
4. Sync - synchronize and return to ready state

psycopg2 uses Extended Protocol automatically for parameterized queries.
"""

import asyncio
import logging
import time
import subprocess
from iris_pgwire.server import PGWireServer

# Enable debug logging
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s:%(name)s:%(message)s')

async def test_p2_extended_protocol():
    """Test P2 Extended Protocol with psycopg2"""
    print("🧪 Testing P2 Extended Protocol with psycopg2")
    print("=" * 50)

    # Start server
    server = PGWireServer(
        host='localhost',
        port=15433,
        iris_host='localhost',
        iris_port=1972,
        iris_username='_SYSTEM',
        iris_password='SYS',
        iris_namespace='USER'
    )

    print("🚀 Starting PGWire server on port 15433...")
    server_task = asyncio.create_task(server.start())

    # Wait for server to start
    await asyncio.sleep(2)

    try:
        # Test with psycopg2 using Python subprocess
        print("📱 Testing psycopg2 Extended Protocol...")

        psycopg2_test = '''
import psycopg2
import sys

try:
    # Connect using psycopg2 (automatically uses Extended Protocol for parameters)
    conn = psycopg2.connect(
        host="localhost",
        port=15433,
        database="USER",
        user="test_user",
        connect_timeout=10
    )

    print("✅ psycopg2 connection successful!")

    # Create cursor
    cur = conn.cursor()

    # Test 1: Simple parameterized query (uses Extended Protocol)
    print("🧪 Test 1: Parameterized query with psycopg2...")
    cur.execute("SELECT %s as param_value", (42,))
    result = cur.fetchone()
    print(f"   Result: {result}")
    assert result[0] == 42, f"Expected 42, got {result[0]}"
    print("✅ Test 1 passed!")

    # Test 2: String parameter
    print("🧪 Test 2: String parameter...")
    cur.execute("SELECT %s as message", ("Hello, IRIS!",))
    result = cur.fetchone()
    print(f"   Result: {result}")
    assert result[0] == "Hello, IRIS!", f"Expected 'Hello, IRIS!', got {result[0]}"
    print("✅ Test 2 passed!")

    # Test 3: Multiple parameters
    print("🧪 Test 3: Multiple parameters...")
    cur.execute("SELECT %s as num, %s as text", (123, "test"))
    result = cur.fetchone()
    print(f"   Result: {result}")
    assert result[0] == 123, f"Expected 123, got {result[0]}"
    assert result[1] == "test", f"Expected 'test', got {result[1]}"
    print("✅ Test 3 passed!")

    # Test 4: Prepared statement reuse (execute multiple times)
    print("🧪 Test 4: Prepared statement reuse...")
    for i in range(3):
        cur.execute("SELECT %s * 2 as doubled", (i,))
        result = cur.fetchone()
        expected = i * 2
        print(f"   Iteration {i}: {result}")
        assert result[0] == expected, f"Expected {expected}, got {result[0]}"
    print("✅ Test 4 passed!")

    # Close connection
    cur.close()
    conn.close()

    print("🎉 All psycopg2 Extended Protocol tests passed!")
    sys.exit(0)

except Exception as e:
    print(f"❌ psycopg2 test failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
'''

        # Run psycopg2 test as subprocess
        result = subprocess.run([
            'uv', 'run', 'python', '-c', psycopg2_test
        ], capture_output=True, text=True, timeout=30)

        print("📋 psycopg2 test output:")
        print(result.stdout)

        if result.stderr:
            print("⚠️  psycopg2 test errors:")
            print(result.stderr)

        if result.returncode == 0:
            print("🎉 P2 Extended Protocol test with psycopg2 SUCCESSFUL!")
        else:
            print(f"❌ P2 Extended Protocol test failed with code {result.returncode}")

    except subprocess.TimeoutExpired:
        print("⏰ psycopg2 test timed out")
    except Exception as e:
        print(f"❌ Test execution error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Stop server
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass
        print("📡 Server stopped")

if __name__ == "__main__":
    asyncio.run(test_p2_extended_protocol())
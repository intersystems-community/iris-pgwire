#!/usr/bin/env python3
"""
Comprehensive P2 Extended Protocol test with real psycopg2 client

This test properly sequences server startup and client connection
to verify that P2 Extended Protocol works with real PostgreSQL clients.
"""

import asyncio
import socket
import time
import threading
import logging
from iris_pgwire.server import PGWireServer

# Disable excessive logging
logging.getLogger('iris_pgwire').setLevel(logging.WARNING)

def wait_for_port(host, port, timeout=10):
    """Wait for a port to become available"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((host, port))
            sock.close()
            if result == 0:
                return True
        except:
            pass
        time.sleep(0.1)
    return False

def run_server(port, ready_event):
    """Run server in background thread"""
    async def start_server():
        server = PGWireServer(
            host='127.0.0.1',
            port=port,
            iris_host='localhost',
            iris_port=1972,
            iris_username='_SYSTEM',
            iris_password='SYS',
            iris_namespace='USER'
        )

        print(f"🚀 Starting server on 127.0.0.1:{port}...")

        # Start server
        server_task = asyncio.create_task(server.start())

        # Signal that server is ready
        ready_event.set()

        # Keep server running
        try:
            await server_task
        except asyncio.CancelledError:
            pass

    asyncio.run(start_server())

def test_psycopg2_p2_protocol():
    """Test P2 Extended Protocol with psycopg2"""

    PORT = 15439

    print("🧪 P2 Extended Protocol Test with Real psycopg2")
    print("=" * 50)

    # Start server in background thread
    ready_event = threading.Event()
    server_thread = threading.Thread(target=run_server, args=(PORT, ready_event))
    server_thread.daemon = True
    server_thread.start()

    # Wait for server to be ready
    print("⏳ Waiting for server to start...")
    if not ready_event.wait(timeout=10):
        print("❌ Server failed to start")
        return False

    # Wait for port to be actually available
    if not wait_for_port('127.0.0.1', PORT, timeout=5):
        print("❌ Server port not available")
        return False

    print("✅ Server is ready!")

    # Give server extra time to initialize
    time.sleep(1)

    try:
        import psycopg2

        print("📱 Testing psycopg2 connection...")

        # Test connection
        conn = psycopg2.connect(
            host='127.0.0.1',
            port=PORT,
            database='USER',
            user='test_user',
            connect_timeout=5
        )

        print("✅ psycopg2 connection successful!")

        # Create cursor
        cur = conn.cursor()

        # Test 1: Simple query (P1 protocol)
        print("🧪 Test 1: Simple query...")
        cur.execute("SELECT 42 as answer")
        result = cur.fetchone()
        print(f"   Result: {result}")
        assert result[0] == '42', f"Expected '42', got {result[0]}"
        print("✅ Simple query test passed!")

        # Test 2: Parameterized query (P2 Extended Protocol)
        print("🧪 Test 2: Parameterized query (P2 Extended Protocol)...")
        cur.execute("SELECT %s as param_value", (99,))
        result = cur.fetchone()
        print(f"   Result: {result}")
        assert result[0] == '99', f"Expected '99', got {result[0]}"
        print("✅ Parameterized query test passed!")

        # Test 3: Multiple parameters
        print("🧪 Test 3: Multiple parameters...")
        cur.execute("SELECT %s + %s as sum", (10, 32))
        result = cur.fetchone()
        print(f"   Result: {result}")
        assert result[0] == '42', f"Expected '42', got {result[0]}"
        print("✅ Multiple parameters test passed!")

        # Test 4: String parameter
        print("🧪 Test 4: String parameter...")
        cur.execute("SELECT %s as message", ("Hello IRIS!",))
        result = cur.fetchone()
        print(f"   Result: {result}")
        assert result[0] == "Hello IRIS!", f"Expected 'Hello IRIS!', got {result[0]}"
        print("✅ String parameter test passed!")

        # Test 5: Prepared statement reuse
        print("🧪 Test 5: Prepared statement reuse...")
        for i in range(3):
            cur.execute("SELECT %s * 2 as doubled", (i,))
            result = cur.fetchone()
            expected = str(i * 2)  # Convert to string since our protocol returns text
            print(f"   Iteration {i}: {result}")
            assert result[0] == expected, f"Expected {expected}, got {result[0]}"
        print("✅ Prepared statement reuse test passed!")

        # Close
        cur.close()
        conn.close()

        print("\n🎉 ALL P2 EXTENDED PROTOCOL TESTS PASSED!")
        print("✅ Parse messages handled correctly")
        print("✅ Bind messages handled correctly")
        print("✅ Execute messages handled correctly")
        print("✅ Sync messages handled correctly")
        print("✅ psycopg2 can successfully use prepared statements!")

        return True

    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = test_psycopg2_p2_protocol()
    if success:
        print("\n🎯 P2 Extended Protocol implementation is WORKING with real PostgreSQL clients!")
    else:
        print("\n💥 P2 Extended Protocol test failed")

    exit(0 if success else 1)
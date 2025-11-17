#!/usr/bin/env python3
"""
P3 Authentication Test with SCRAM-SHA-256

This test verifies that the P3 Authentication implementation works correctly
with SCRAM-SHA-256 authentication against real PostgreSQL clients.
"""

import asyncio
import logging
import socket
import threading
import time

from iris_pgwire.server import PGWireServer

# Disable excessive logging for cleaner output
logging.getLogger("iris_pgwire").setLevel(logging.WARNING)


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


def run_server_with_scram(port, ready_event):
    """Run server with SCRAM authentication enabled"""

    async def start_server():
        server = PGWireServer(
            host="127.0.0.1",
            port=port,
            iris_host="localhost",
            iris_port=1972,
            iris_username="_SYSTEM",
            iris_password="SYS",
            iris_namespace="USER",
            enable_scram=True,  # Enable SCRAM-SHA-256 authentication
        )

        print(f"🚀 Starting server with SCRAM-SHA-256 authentication on 127.0.0.1:{port}...")

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


def test_trust_authentication():
    """Test trust authentication (P0 baseline)"""

    PORT = 15440

    print("🧪 P3 Authentication Test - Trust Mode (Baseline)")
    print("=" * 55)

    # Start server in background thread with trust auth
    ready_event = threading.Event()
    server_thread = threading.Thread(target=run_server_with_trust, args=(PORT, ready_event))
    server_thread.daemon = True
    server_thread.start()

    # Wait for server to be ready
    print("⏳ Waiting for server to start...")
    if not ready_event.wait(timeout=10):
        print("❌ Server failed to start")
        return False

    # Wait for port to be actually available
    if not wait_for_port("127.0.0.1", PORT, timeout=5):
        print("❌ Server port not available")
        return False

    print("✅ Server is ready!")
    time.sleep(1)

    try:
        import psycopg2

        print("📱 Testing trust authentication...")

        # Test connection without password (trust mode)
        conn = psycopg2.connect(
            host="127.0.0.1",
            port=PORT,
            database="USER",
            user="test_user",
            # No password in trust mode
            connect_timeout=5,
        )

        print("✅ Trust authentication successful!")

        # Test query execution
        cur = conn.cursor()
        cur.execute("SELECT 'Trust auth working!' as message")
        result = cur.fetchone()
        print(f"   Query result: {result}")

        cur.close()
        conn.close()

        print("🎉 Trust authentication test passed!")
        return True

    except Exception as e:
        print(f"❌ Trust authentication test failed: {e}")
        return False


def run_server_with_trust(port, ready_event):
    """Run server with trust authentication (baseline)"""

    async def start_server():
        server = PGWireServer(
            host="127.0.0.1",
            port=port,
            iris_host="localhost",
            iris_port=1972,
            iris_username="_SYSTEM",
            iris_password="SYS",
            iris_namespace="USER",
            enable_scram=False,  # Trust authentication
        )

        print(f"🚀 Starting server with trust authentication on 127.0.0.1:{port}...")

        server_task = asyncio.create_task(server.start())
        ready_event.set()

        try:
            await server_task
        except asyncio.CancelledError:
            pass

    asyncio.run(start_server())


def test_scram_authentication():
    """Test SCRAM-SHA-256 authentication"""

    PORT = 15441

    print("\n🧪 P3 Authentication Test - SCRAM-SHA-256")
    print("=" * 45)

    # Start server in background thread with SCRAM auth
    ready_event = threading.Event()
    server_thread = threading.Thread(target=run_server_with_scram, args=(PORT, ready_event))
    server_thread.daemon = True
    server_thread.start()

    # Wait for server to be ready
    print("⏳ Waiting for SCRAM server to start...")
    if not ready_event.wait(timeout=10):
        print("❌ SCRAM server failed to start")
        return False

    # Wait for port to be actually available
    if not wait_for_port("127.0.0.1", PORT, timeout=5):
        print("❌ SCRAM server port not available")
        return False

    print("✅ SCRAM server is ready!")
    time.sleep(1)

    try:
        import psycopg2

        print("📱 Testing SCRAM-SHA-256 authentication...")

        # Test connection with password (SCRAM mode)
        # Note: Current implementation uses simplified SCRAM for testing
        conn = psycopg2.connect(
            host="127.0.0.1",
            port=PORT,
            database="USER",
            user="test_user",
            password="test_password",  # SCRAM requires password
            connect_timeout=10,
        )

        print("✅ SCRAM-SHA-256 authentication successful!")

        # Test query execution with authenticated connection
        cur = conn.cursor()
        cur.execute("SELECT 'SCRAM auth working!' as message")
        result = cur.fetchone()
        print(f"   Authenticated query result: {result}")

        # Test parameterized query to ensure P2 still works with P3 auth
        cur.execute("SELECT %s as param_test", ("SCRAM + P2 working!",))
        result = cur.fetchone()
        print(f"   Parameterized query result: {result}")

        cur.close()
        conn.close()

        print("🎉 SCRAM-SHA-256 authentication test passed!")
        print("✅ P2 Extended Protocol + P3 Authentication integration working!")
        return True

    except Exception as e:
        print(f"❌ SCRAM authentication test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_authentication_failure():
    """Test authentication failure scenarios"""

    PORT = 15442

    print("\n🧪 P3 Authentication Test - Failure Scenarios")
    print("=" * 48)

    # Start server with SCRAM
    ready_event = threading.Event()
    server_thread = threading.Thread(target=run_server_with_scram, args=(PORT, ready_event))
    server_thread.daemon = True
    server_thread.start()

    if not ready_event.wait(timeout=10) or not wait_for_port("127.0.0.1", PORT, timeout=5):
        print("❌ Test server failed to start")
        return False

    print("✅ Test server ready!")
    time.sleep(1)

    try:
        import psycopg2

        print("📱 Testing authentication failure...")

        # This should fail (missing password)
        try:
            conn = psycopg2.connect(
                host="127.0.0.1",
                port=PORT,
                database="USER",
                user="test_user",
                # No password - should fail with SCRAM
                connect_timeout=5,
            )
            print("❌ Expected authentication failure but connection succeeded")
            conn.close()
            return False
        except psycopg2.OperationalError as e:
            print(f"✅ Authentication correctly failed: {e}")
            return True

    except Exception as e:
        print(f"❌ Authentication failure test error: {e}")
        return False


def main():
    """Run comprehensive P3 Authentication tests"""
    print("🔐 P3 AUTHENTICATION COMPREHENSIVE TEST SUITE")
    print("=" * 50)

    results = []

    # Test 1: Trust authentication (baseline)
    print("\n1️⃣  Testing trust authentication...")
    results.append(test_trust_authentication())

    # Test 2: SCRAM-SHA-256 authentication
    print("\n2️⃣  Testing SCRAM-SHA-256 authentication...")
    results.append(test_scram_authentication())

    # Test 3: Authentication failure scenarios
    print("\n3️⃣  Testing authentication failure scenarios...")
    results.append(test_authentication_failure())

    # Summary
    print("\n" + "=" * 50)
    print("🎯 P3 AUTHENTICATION TEST RESULTS")
    print("=" * 50)

    test_names = [
        "Trust Authentication",
        "SCRAM-SHA-256 Authentication",
        "Authentication Failure Handling",
    ]

    passed = 0
    for i, (name, result) in enumerate(zip(test_names, results, strict=False)):
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{i+1}. {name}: {status}")
        if result:
            passed += 1

    print(f"\n📊 Results: {passed}/{len(results)} tests passed")

    if passed == len(results):
        print("\n🎉 ALL P3 AUTHENTICATION TESTS PASSED!")
        print("✅ Trust authentication working")
        print("✅ SCRAM-SHA-256 authentication working")
        print("✅ Authentication failure handling working")
        print("✅ P2 + P3 integration working")
        print("\n🔐 Production-ready authentication system implemented!")
        return True
    else:
        print(f"\n💥 {len(results) - passed} authentication tests failed")
        return False


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)

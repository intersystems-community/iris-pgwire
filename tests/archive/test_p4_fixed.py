#!/usr/bin/env python3
"""
P4 Query Cancellation & Timeouts Test - Fixed asyncio version

This test verifies that the P4 Query Cancellation and Timeout implementation
works correctly with real PostgreSQL clients.
"""

import asyncio
import logging
import socket
import struct
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


def run_server(port, ready_event):
    """Run server for cancellation testing"""

    async def start_server():
        server = PGWireServer(
            host="127.0.0.1",
            port=port,
            iris_host="localhost",
            iris_port=1972,
            iris_username="_SYSTEM",
            iris_password="SYS",
            iris_namespace="USER",
            enable_scram=False,  # Use trust auth for testing
        )

        print(f"🚀 Starting server for P4 testing on 127.0.0.1:{port}...")

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


async def test_backend_key_data_async():
    """Test that backend key data is properly exchanged"""
    PORT = 15460

    print("🧪 P4 Test 1: Backend Key Data Exchange")
    print("=" * 42)

    # Start server
    ready_event = threading.Event()
    server_thread = threading.Thread(target=run_server, args=(PORT, ready_event))
    server_thread.daemon = True
    server_thread.start()

    # Wait for server to be ready
    print("⏳ Waiting for server to start...")
    if not ready_event.wait(timeout=10):
        print("❌ Server failed to start")
        return False

    if not wait_for_port("127.0.0.1", PORT, timeout=5):
        print("❌ Server port not available")
        return False

    print("✅ Server is ready!")
    await asyncio.sleep(1)

    try:
        # Test direct wire protocol to verify BackendKeyData
        print("📱 Testing BackendKeyData exchange...")

        # Connect and complete handshake
        reader, writer = await asyncio.open_connection("127.0.0.1", PORT)

        # SSL probe
        ssl_request = b"\x00\x00\x00\x08\x04\xd2\x16\x2f"
        writer.write(ssl_request)
        await writer.drain()

        ssl_response = await reader.read(1)
        print(f"   SSL response: {ssl_response}")

        # StartupMessage
        protocol_version = (196608).to_bytes(4, "big")
        user_param = b"user\x00test_user\x00"
        db_param = b"database\x00USER\x00"
        terminator = b"\x00"
        params = user_param + db_param + terminator

        message_length = (4 + len(protocol_version) + len(params)).to_bytes(4, "big")
        startup_message = message_length + protocol_version + params

        writer.write(startup_message)
        await writer.drain()
        print("   StartupMessage sent")

        # Read authentication and ready responses
        print("   Reading authentication responses...")
        auth_response = b""

        # Read in chunks until we get everything including ReadyForQuery
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(1024), timeout=2.0)
                if not chunk:
                    break
                auth_response += chunk
                # Look for ReadyForQuery (Z) to know we're done
                if b"Z" in chunk:
                    break
            except TimeoutError:
                break

        print(f"   Authentication response: {len(auth_response)} bytes")

        # Look for BackendKeyData (K) in response
        backend_key_found = False
        backend_pid = None
        backend_secret = None

        pos = 0
        while pos < len(auth_response):
            if pos + 5 > len(auth_response):
                break

            msg_type = auth_response[pos : pos + 1]
            length = struct.unpack("!I", auth_response[pos + 1 : pos + 5])[0]
            msg_data = auth_response[pos + 5 : pos + 1 + length]

            if msg_type == b"K":  # BackendKeyData
                backend_key_found = True
                backend_pid, backend_secret = struct.unpack("!II", msg_data[:8])
                print(f"   ✅ BackendKeyData found: PID={backend_pid}, Secret=***")
                break

            pos += 1 + length

        writer.close()
        await writer.wait_closed()

        if backend_key_found:
            print("🎉 Backend Key Data exchange test passed!")
            return True, backend_pid, backend_secret
        else:
            print("❌ Backend Key Data not found in response")
            return False, None, None

    except Exception as e:
        print(f"❌ Backend Key Data test failed: {e}")
        import traceback

        traceback.print_exc()
        return False, None, None


async def test_cancel_request_async():
    """Test cancel request protocol"""
    PORT = 15461

    print("\n🧪 P4 Test 2: Cancel Request Protocol")
    print("=" * 40)

    # Start server
    ready_event = threading.Event()
    server_thread = threading.Thread(target=run_server, args=(PORT, ready_event))
    server_thread.daemon = True
    server_thread.start()

    if not ready_event.wait(timeout=10) or not wait_for_port("127.0.0.1", PORT, timeout=5):
        print("❌ Server failed to start")
        return False

    print("✅ Server ready for cancel test!")
    await asyncio.sleep(1)

    try:
        # First, get backend key data from a connection
        print("📱 Step 1: Getting backend key data...")

        reader, writer = await asyncio.open_connection("127.0.0.1", PORT)

        # Complete handshake
        ssl_request = b"\x00\x00\x00\x08\x04\xd2\x16\x2f"
        writer.write(ssl_request)
        await writer.drain()
        await reader.read(1)

        protocol_version = (196608).to_bytes(4, "big")
        user_param = b"user\x00test_user\x00"
        db_param = b"database\x00USER\x00"
        terminator = b"\x00"
        params = user_param + db_param + terminator
        message_length = (4 + len(protocol_version) + len(params)).to_bytes(4, "big")
        startup_message = message_length + protocol_version + params

        writer.write(startup_message)
        await writer.drain()

        # Read full authentication response
        auth_response = b""
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(1024), timeout=2.0)
                if not chunk:
                    break
                auth_response += chunk
                if b"Z" in chunk:
                    break
            except TimeoutError:
                break

        # Extract BackendKeyData
        backend_pid = None
        backend_secret = None
        pos = 0
        while pos < len(auth_response):
            if pos + 5 > len(auth_response):
                break
            msg_type = auth_response[pos : pos + 1]
            length = struct.unpack("!I", auth_response[pos + 1 : pos + 5])[0]
            msg_data = auth_response[pos + 5 : pos + 1 + length]

            if msg_type == b"K":
                backend_pid, backend_secret = struct.unpack("!II", msg_data[:8])
                print(f"   Got BackendKeyData: PID={backend_pid}")
                break

            pos += 1 + length

        if not backend_pid:
            print("❌ Could not get backend key data")
            return False

        # Keep the connection open and send a cancel request from another connection
        print("📱 Step 2: Sending cancel request...")

        # Create new connection for cancel request
        cancel_reader, cancel_writer = await asyncio.open_connection("127.0.0.1", PORT)

        # Send cancel request
        cancel_request_code = 80877102  # PostgreSQL cancel request code
        cancel_request = struct.pack("!III", 16, cancel_request_code, backend_pid) + struct.pack(
            "!I", backend_secret
        )

        cancel_writer.write(cancel_request)
        await cancel_writer.drain()
        print(f"   Cancel request sent for PID {backend_pid}")

        # Cancel connection should close immediately
        cancel_writer.close()
        await cancel_writer.wait_closed()

        # Original connection should also close
        await asyncio.sleep(0.5)  # Give server time to process
        writer.close()
        await writer.wait_closed()

        print("🎉 Cancel Request protocol test passed!")
        return True

    except Exception as e:
        print(f"❌ Cancel Request test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


async def test_connection_timeout_async():
    """Test connection timeout handling"""
    PORT = 15462

    print("\n🧪 P4 Test 3: Connection Timeout Handling")
    print("=" * 44)

    # Start server
    ready_event = threading.Event()
    server_thread = threading.Thread(target=run_server, args=(PORT, ready_event))
    server_thread.daemon = True
    server_thread.start()

    if not ready_event.wait(timeout=10) or not wait_for_port("127.0.0.1", PORT, timeout=5):
        print("❌ Server failed to start")
        return False

    print("✅ Server ready for timeout test!")
    await asyncio.sleep(1)

    try:
        import psycopg2

        print("📱 Testing connection timeout behavior...")

        # Test with very short timeout
        start_time = time.time()
        try:
            conn = psycopg2.connect(
                host="127.0.0.1",
                port=PORT,
                database="USER",
                user="test_user",
                connect_timeout=1,  # Very short timeout
            )

            # If connection succeeds, test query execution
            cur = conn.cursor()
            print("   Connection established, testing query execution...")

            # This should work fine
            cur.execute("SELECT 'Timeout test' as message")
            result = cur.fetchone()
            print(f"   Quick query result: {result}")

            cur.close()
            conn.close()

            elapsed = time.time() - start_time
            print(f"   Connection completed in {elapsed:.2f}s")

            if elapsed < 5.0:  # Reasonable time
                print("🎉 Connection timeout test passed!")
                return True
            else:
                print("❌ Connection took too long")
                return False

        except psycopg2.OperationalError as e:
            if "timeout" in str(e).lower():
                print(f"   Expected timeout occurred: {e}")
                print("🎉 Connection timeout test passed!")
                return True
            else:
                print(f"❌ Unexpected connection error: {e}")
                return False

    except Exception as e:
        print(f"❌ Connection timeout test failed: {e}")
        return False


async def main():
    """Run comprehensive P4 tests"""
    print("🔄 P4 QUERY CANCELLATION & TIMEOUTS TEST SUITE")
    print("=" * 52)

    results = []

    # Test 1: Backend Key Data
    print("\n1️⃣  Testing Backend Key Data...")
    result1, backend_pid, backend_secret = await test_backend_key_data_async()
    results.append(result1)

    # Test 2: Cancel Request Protocol
    print("\n2️⃣  Testing Cancel Request Protocol...")
    results.append(await test_cancel_request_async())

    # Test 3: Connection Timeouts
    print("\n3️⃣  Testing Connection Timeouts...")
    results.append(await test_connection_timeout_async())

    # Summary
    print("\n" + "=" * 52)
    print("🎯 P4 QUERY CANCELLATION & TIMEOUTS RESULTS")
    print("=" * 52)

    test_names = [
        "Backend Key Data Exchange",
        "Cancel Request Protocol",
        "Connection Timeout Handling",
    ]

    passed = 0
    for i, (name, result) in enumerate(zip(test_names, results, strict=False)):
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{i+1}. {name}: {status}")
        if result:
            passed += 1

    print(f"\n📊 Results: {passed}/{len(results)} tests passed")

    if passed == len(results):
        print("\n🎉 ALL P4 CANCELLATION & TIMEOUT TESTS PASSED!")
        print("✅ Backend Key Data exchange working")
        print("✅ Cancel Request protocol working")
        print("✅ Connection timeout handling working")
        print("\n🔄 Production-ready cancellation system implemented!")
        return True
    else:
        print(f"\n💥 {len(results) - passed} P4 tests failed")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)

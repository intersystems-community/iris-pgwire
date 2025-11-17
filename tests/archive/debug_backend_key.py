#!/usr/bin/env python3
"""
Debug Backend Key Data issue
"""

import asyncio
import struct

from iris_pgwire.server import PGWireServer


async def debug_backend_key():
    """Debug why BackendKeyData is not being received"""
    print("🔍 Debugging Backend Key Data Issue")
    print("=" * 40)

    # Start server
    server = PGWireServer(
        host="127.0.0.1",
        port=15470,
        iris_host="localhost",
        iris_port=1972,
        iris_username="_SYSTEM",
        iris_password="SYS",
        iris_namespace="USER",
        enable_scram=False,
    )

    print("🚀 Starting debug server...")
    server_task = asyncio.create_task(server.start())

    await asyncio.sleep(1)

    try:
        print("📱 Connecting...")
        reader, writer = await asyncio.open_connection("127.0.0.1", 15470)

        # SSL probe
        print("📤 SSL probe...")
        ssl_request = b"\x00\x00\x00\x08\x04\xd2\x16\x2f"
        writer.write(ssl_request)
        await writer.drain()

        ssl_response = await reader.read(1)
        print(f"📥 SSL response: {ssl_response} ({'No SSL' if ssl_response == b'N' else 'SSL'})")

        # StartupMessage
        print("📤 StartupMessage...")
        protocol_version = (196608).to_bytes(4, "big")  # PostgreSQL 3.0
        user_param = b"user\x00test_user\x00"
        db_param = b"database\x00USER\x00"
        terminator = b"\x00"
        params = user_param + db_param + terminator

        message_length = (4 + len(protocol_version) + len(params)).to_bytes(4, "big")
        startup_message = message_length + protocol_version + params

        writer.write(startup_message)
        await writer.drain()
        print(f"📤 StartupMessage sent ({len(startup_message)} bytes)")

        # Read ALL authentication responses
        print("📥 Reading authentication responses...")
        total_response = b""

        # Read in chunks until we get everything
        while True:
            try:
                chunk = await asyncio.wait_for(reader.read(1024), timeout=2.0)
                if not chunk:
                    break
                total_response += chunk
                print(f"   Received chunk: {len(chunk)} bytes")

                # Look for ReadyForQuery (Z) to know we're done
                if b"Z" in chunk:
                    print("   ReadyForQuery found - authentication complete")
                    break

            except TimeoutError:
                print("   Timeout - assuming complete")
                break

        print(f"📊 Total response: {len(total_response)} bytes")

        # Parse the response byte by byte
        print("🔍 Parsing response messages:")
        pos = 0
        found_backend_key = False

        while pos < len(total_response):
            if pos + 5 > len(total_response):
                print(f"   Incomplete message at position {pos}")
                break

            msg_type = total_response[pos : pos + 1]
            length = struct.unpack("!I", total_response[pos + 1 : pos + 5])[0]

            if pos + 1 + length > len(total_response):
                print(f"   Message extends beyond buffer: type={msg_type}, length={length}")
                break

            msg_data = total_response[pos + 5 : pos + 1 + length]

            print(f"   Message: {msg_type} (length {length})")

            if msg_type == b"R":
                auth_type = struct.unpack("!I", msg_data[:4])[0] if len(msg_data) >= 4 else None
                print(f"     AuthenticationRequest: type={auth_type}")
            elif msg_type == b"S":
                if len(msg_data) > 0:
                    param_data = msg_data.decode("utf-8", errors="ignore")
                    print(f"     ParameterStatus: {param_data[:50]}...")
            elif msg_type == b"K":
                if len(msg_data) >= 8:
                    backend_pid, backend_secret = struct.unpack("!II", msg_data[:8])
                    print(f"     ✅ BackendKeyData: PID={backend_pid}, Secret=***")
                    found_backend_key = True
                else:
                    print(f"     ❌ BackendKeyData too short: {len(msg_data)} bytes")
            elif msg_type == b"Z":
                status = msg_data[0:1] if len(msg_data) > 0 else b"?"
                print(f"     ReadyForQuery: status={status}")
            else:
                print(f"     Unknown message type: {msg_type}")

            pos += 1 + length

        writer.close()
        await writer.wait_closed()

        if found_backend_key:
            print("🎉 Backend Key Data was found in response!")
            print("✅ P4 Backend Key infrastructure is working correctly")
        else:
            print("❌ Backend Key Data was NOT found in response")
            print("🔍 This indicates a possible issue in the startup sequence")

    except Exception as e:
        print(f"❌ Debug failed: {e}")
        import traceback

        traceback.print_exc()
    finally:
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass
        print("📡 Server stopped")


if __name__ == "__main__":
    asyncio.run(debug_backend_key())

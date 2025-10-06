#!/usr/bin/env python3
"""
Test Backend Key Data with added debugging
"""

import asyncio
import struct
import tempfile
import os
from iris_pgwire.server import PGWireServer

# Patch the protocol to add debugging
def patch_protocol():
    """Add debug logging to the protocol"""
    from iris_pgwire import protocol

    # Store original method
    original_send_backend_key_data = protocol.PGWireProtocol.send_backend_key_data
    original_startup_sequence = protocol.PGWireProtocol.startup_sequence

    async def debug_send_backend_key_data(self):
        """Debugging wrapper for send_backend_key_data"""
        print(f"🔧 DEBUG: send_backend_key_data called - PID={self.backend_pid}, Secret={self.backend_secret}")
        try:
            result = await original_send_backend_key_data(self)
            print("🔧 DEBUG: send_backend_key_data completed successfully")
            return result
        except Exception as e:
            print(f"🔧 DEBUG: send_backend_key_data failed: {e}")
            raise

    async def debug_startup_sequence(self):
        """Debugging wrapper for startup_sequence"""
        print("🔧 DEBUG: startup_sequence starting...")
        try:
            result = await original_startup_sequence(self)
            print("🔧 DEBUG: startup_sequence completed successfully")
            return result
        except Exception as e:
            print(f"🔧 DEBUG: startup_sequence failed: {e}")
            raise

    # Apply patches
    protocol.PGWireProtocol.send_backend_key_data = debug_send_backend_key_data
    protocol.PGWireProtocol.startup_sequence = debug_startup_sequence

async def test_with_debug():
    """Test with debugging enabled"""
    print("🔍 Testing Backend Key Data with Debug Logging")
    print("=" * 50)

    # Apply debug patches
    patch_protocol()

    # Start server
    server = PGWireServer(
        host='127.0.0.1',
        port=15475,
        iris_host='localhost',
        iris_port=1972,
        iris_username='_SYSTEM',
        iris_password='SYS',
        iris_namespace='USER',
        enable_scram=False
    )

    print("🚀 Starting debug server...")
    server_task = asyncio.create_task(server.start())

    await asyncio.sleep(1)

    try:
        print("📱 Connecting...")
        reader, writer = await asyncio.open_connection('127.0.0.1', 15475)

        # SSL probe
        print("📤 SSL probe...")
        ssl_request = b'\x00\x00\x00\x08\x04\xd2\x16\x2f'
        writer.write(ssl_request)
        await writer.drain()

        ssl_response = await reader.read(1)
        print(f"📥 SSL response: {ssl_response}")

        # StartupMessage
        print("📤 StartupMessage...")
        protocol_version = (196608).to_bytes(4, 'big')
        user_param = b'user\x00test_user\x00'
        db_param = b'database\x00USER\x00'
        terminator = b'\x00'
        params = user_param + db_param + terminator

        message_length = (4 + len(protocol_version) + len(params)).to_bytes(4, 'big')
        startup_message = message_length + protocol_version + params

        writer.write(startup_message)
        await writer.drain()
        print(f"📤 StartupMessage sent ({len(startup_message)} bytes)")

        # Read response
        print("📥 Reading response...")
        response = await reader.read(2048)
        print(f"📊 Response: {len(response)} bytes")

        # Parse for Backend Key Data
        pos = 0
        found_backend_key = False

        print("🔍 Parsing messages:")
        while pos < len(response):
            if pos + 5 > len(response):
                break

            msg_type = response[pos:pos+1]
            length = struct.unpack('!I', response[pos+1:pos+5])[0]

            if pos + 1 + length > len(response):
                break

            msg_data = response[pos+5:pos+1+length]
            print(f"   Message: {msg_type} (length {length})")

            if msg_type == b'K':
                backend_pid, backend_secret = struct.unpack('!II', msg_data[:8])
                print(f"   ✅ BackendKeyData found: PID={backend_pid}")
                found_backend_key = True

            pos += 1 + length

        writer.close()
        await writer.wait_closed()

        if found_backend_key:
            print("🎉 Backend Key Data test PASSED!")
        else:
            print("❌ Backend Key Data test FAILED!")

    except Exception as e:
        print(f"❌ Test failed: {e}")
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
    asyncio.run(test_with_debug())
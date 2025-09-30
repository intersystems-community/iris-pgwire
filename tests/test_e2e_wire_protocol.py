"""
End-to-End Wire Protocol Tests

These tests start the actual PGWire server and test with real PostgreSQL clients.
This validates the complete wire protocol implementation against IRIS.
"""

import pytest
import asyncio
import subprocess
import socket
import time
import os
import signal
from iris_pgwire.server import PGWireServer


class TestE2EWireProtocol:
    """End-to-end tests with real PostgreSQL clients"""

    @pytest.fixture(scope="class")
    def iris_config(self):
        """IRIS configuration for testing"""
        return {
            'host': 'localhost',
            'port': 1972,
            'username': '_SYSTEM',
            'password': 'SYS',
            'namespace': 'USER'
        }

    @pytest.fixture(scope="class")
    async def pgwire_server(self, iris_config):
        """Start PGWire server for testing"""
        # Use test port to avoid conflicts
        test_port = 15432

        server = PGWireServer(
            host='localhost',
            port=test_port,
            iris_host=iris_config['host'],
            iris_port=iris_config['port'],
            iris_username=iris_config['username'],
            iris_password=iris_config['password'],
            iris_namespace=iris_config['namespace']
        )

        # Start server in background task
        server_task = asyncio.create_task(server.start())

        # Wait for server to be ready
        await self._wait_for_port(test_port, timeout=10)

        yield {'server': server, 'port': test_port, 'task': server_task}

        # Cleanup
        server_task.cancel()
        try:
            await server_task
        except asyncio.CancelledError:
            pass

    async def _wait_for_port(self, port: int, timeout: int = 10) -> None:
        """Wait for port to become available"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(1)
                    result = sock.connect_ex(('localhost', port))
                    if result == 0:
                        return
            except Exception:
                pass
            await asyncio.sleep(0.1)
        raise TimeoutError(f"Port {port} did not become available within {timeout} seconds")

    @pytest.mark.asyncio
    async def test_server_starts_and_accepts_connections(self, pgwire_server):
        """Test that the server starts and accepts connections"""
        port = pgwire_server['port']

        # Test that port is accessible
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(5)
            result = sock.connect_ex(('localhost', port))
            assert result == 0, f"PGWire server should be listening on port {port}"

    @pytest.mark.asyncio
    async def test_basic_connection_handshake(self, pgwire_server):
        """Test basic PostgreSQL connection handshake"""
        port = pgwire_server['port']

        # Test complete P0 handshake with asyncio
        try:
            reader, writer = await asyncio.open_connection('localhost', port)

            # Step 1: SSL negotiation
            ssl_request = b'\x00\x00\x00\x08\x04\xd2\x16\x2f'
            writer.write(ssl_request)
            await writer.drain()

            ssl_response = await reader.read(1)
            assert ssl_response in [b'S', b'N'], f"Expected SSL response, got: {ssl_response}"
            print(f"✅ SSL negotiation successful: {ssl_response}")

            # Step 2: Send StartupMessage
            protocol_version = (196608).to_bytes(4, 'big')  # PostgreSQL 3.0
            user_param = b'user\x00test_user\x00'
            db_param = b'database\x00USER\x00'
            terminator = b'\x00'
            params = user_param + db_param + terminator

            message_length = (4 + len(protocol_version) + len(params)).to_bytes(4, 'big')
            startup_message = message_length + protocol_version + params

            writer.write(startup_message)
            await writer.drain()

            # Step 3: Read authentication response
            auth_response = await asyncio.wait_for(reader.read(1024), timeout=5.0)
            assert len(auth_response) > 0, "Should receive authentication response"

            msg_type = auth_response[0:1]
            assert msg_type == b'R', f"Expected Authentication message (R), got: {msg_type}"
            print(f"✅ Authentication response received: {len(auth_response)} bytes")

            writer.close()
            await writer.wait_closed()

        except Exception as e:
            pytest.fail(f"P0 handshake failed: {e}")

    def test_psycopg_connection_attempt(self, pgwire_server):
        """Test connection with psycopg (may fail but should not crash server)"""
        port = pgwire_server['port']

        try:
            import psycopg

            # Attempt connection (this will likely fail in early implementation)
            # but should not crash the server
            try:
                with psycopg.connect(
                    host='localhost',
                    port=port,
                    user='test_user',
                    dbname='USER'
                ) as conn:
                    # If we get here, the connection worked!
                    with conn.cursor() as cur:
                        cur.execute('SELECT 1')
                        result = cur.fetchone()
                        assert result[0] == 1
                        print("✅ psycopg connection and query successful!")

            except Exception as e:
                # Connection failure is expected in early development
                print(f"🔄 psycopg connection failed (expected): {e}")
                # Verify server is still running after failed connection
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(2)
                    result = sock.connect_ex(('localhost', port))
                    assert result == 0, "Server should still be running after failed connection"

        except ImportError:
            pytest.skip("psycopg not available for testing")

    def test_multiple_connection_attempts(self, pgwire_server):
        """Test that server can handle multiple connection attempts"""
        port = pgwire_server['port']

        # Test multiple rapid connections
        for i in range(5):
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                    sock.settimeout(2)
                    sock.connect(('localhost', port))

                    # Send SSL request
                    ssl_request = b'\x00\x00\x00\x08\x04\xd2\x16\x2f'
                    sock.send(ssl_request)

                    # Get response
                    response = sock.recv(1)
                    assert response in [b'S', b'N']

            except Exception as e:
                pytest.fail(f"Connection {i} failed: {e}")

        print("✅ Multiple connections handled successfully")

    @pytest.mark.asyncio
    async def test_server_shutdown_gracefully(self, iris_config):
        """Test that server can start and shutdown gracefully"""
        test_port = 25432

        server = PGWireServer(
            host='localhost',
            port=test_port,
            iris_host=iris_config['host'],
            iris_port=iris_config['port'],
            iris_username=iris_config['username'],
            iris_password=iris_config['password'],
            iris_namespace=iris_config['namespace']
        )

        # Start server
        server_task = asyncio.create_task(server.start())

        # Wait for startup
        await self._wait_for_port(test_port, timeout=5)

        # Verify it's running
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(2)
            result = sock.connect_ex(('localhost', test_port))
            assert result == 0, "Server should be running"

        # Shutdown
        server_task.cancel()

        try:
            await server_task
        except asyncio.CancelledError:
            pass

        # Wait a moment for cleanup
        await asyncio.sleep(0.5)

        # Verify it's stopped
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            result = sock.connect_ex(('localhost', test_port))
            assert result != 0, "Server should be stopped"

        print("✅ Server shutdown gracefully")


class TestWireProtocolMessages:
    """Test specific wire protocol message handling"""

    def test_ssl_request_format(self):
        """Test SSL request message format"""
        # PostgreSQL SSL request: 8 bytes total
        # 4 bytes: message length (8)
        # 4 bytes: SSL request code (80877103)

        length = (8).to_bytes(4, 'big')
        ssl_code = (80877103).to_bytes(4, 'big')
        ssl_request = length + ssl_code

        assert len(ssl_request) == 8
        assert ssl_request == b'\x00\x00\x00\x08\x04\xd2\x16\x2f'

    def test_startup_message_format(self):
        """Test startup message format"""
        # This tests the format without sending it
        # Real startup message would be larger with parameters

        protocol_version = (196608).to_bytes(4, 'big')  # PostgreSQL 3.0
        assert protocol_version == b'\x00\x03\x00\x00'

        # Parameters would follow: user, database, etc.
        user_param = b'user\x00test_user\x00'
        db_param = b'database\x00USER\x00'
        terminator = b'\x00'

        params = user_param + db_param + terminator

        # Full message would be: length + version + params
        message_length = (4 + 4 + len(params)).to_bytes(4, 'big')
        startup_message = message_length + protocol_version + params

        assert len(startup_message) > 8  # Should be longer than SSL request


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "-s"])
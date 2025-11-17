"""
P0 Handshake E2E Tests

Tests the P0 implementation with REAL PostgreSQL clients.
NO MOCKS - tests actual protocol compatibility.
"""

import pytest
import structlog

logger = structlog.get_logger()


@pytest.mark.e2e
@pytest.mark.requires_iris
class TestP0Handshake:
    """
    E2E tests for P0 handshake implementation

    These tests prove that our PostgreSQL wire protocol implementation
    can successfully handle real PostgreSQL clients through the complete
    P0 handshake sequence.
    """

    async def test_psycopg_connection_establishment(self, psycopg_connection):
        """
        E2E: PostgreSQL client can establish connection

        SUCCESS CRITERIA:
        - psycopg can connect without errors
        - Connection reaches ready state
        - No protocol violations
        """
        # If we get here, the connection was established successfully
        # This tests the complete P0 handshake:
        # 1. SSL probe handling
        # 2. StartupMessage parsing
        # 3. Authentication (basic trust)
        # 4. ParameterStatus emission
        # 5. BackendKeyData generation
        # 6. ReadyForQuery state

        # Verify connection is in good state
        assert psycopg_connection.info.status.name == "OK"
        logger.info(
            "P0 handshake successful with psycopg", status=psycopg_connection.info.status.name
        )

    async def test_psycopg_simple_query_select_1(self, psycopg_connection):
        """
        E2E: Simple query 'SELECT 1' works with real psycopg

        SUCCESS CRITERIA:
        - Query executes without protocol errors
        - Returns correct result (1)
        - Maintains connection state
        """
        async with psycopg_connection.cursor() as cur:
            await cur.execute("SELECT 1")
            result = await cur.fetchone()

            # Verify result
            assert result is not None
            assert result[0] == 1

            logger.info("P0 simple query successful with psycopg", result=result[0])

    async def test_psycopg_connection_info(self, psycopg_connection):
        """
        E2E: Connection info reflects proper PostgreSQL compatibility

        SUCCESS CRITERIA:
        - Server version reported correctly
        - Protocol version is PostgreSQL v3
        - Connection parameters are set
        """
        info = psycopg_connection.info

        # Check basic connection info
        assert info.protocol_version == 3  # PostgreSQL protocol v3
        assert info.server_version >= 160000  # Our reported version

        # Check that we're in a good state
        assert info.status.name == "OK"

        logger.info(
            "P0 connection info validated",
            protocol_version=info.protocol_version,
            server_version=info.server_version,
            status=info.status.name,
        )

    def test_psql_command_line_connection(self, psql_command):
        """
        E2E: Real psql command can connect and execute queries

        SUCCESS CRITERIA:
        - psql connects without errors
        - Can execute simple queries
        - Returns proper exit codes
        """
        # Test basic connection with info command
        result = psql_command("\\conninfo")

        assert result["success"], f"psql connection failed: {result['stderr']}"
        assert (
            "Connected to database" in result["stdout"] or "You are connected" in result["stdout"]
        )

        logger.info("P0 psql connection successful", stdout_snippet=result["stdout"][:100])

    def test_psql_select_1_query(self, psql_command):
        """
        E2E: psql can execute SELECT 1 query

        SUCCESS CRITERIA:
        - Query executes successfully
        - Returns correct result
        - Proper exit code
        """
        result = psql_command("SELECT 1")

        assert result["success"], f"psql query failed: {result['stderr']}"
        assert "1" in result["stdout"]  # Should contain the result

        logger.info("P0 psql SELECT 1 successful", stdout=result["stdout"])

    async def test_multiple_concurrent_connections(self, pgwire_server, pgwire_connection_params):
        """
        E2E: Multiple PostgreSQL clients can connect concurrently

        SUCCESS CRITERIA:
        - Multiple psycopg connections succeed
        - Each gets independent session
        - No connection interference
        """
        import psycopg

        connections = []
        try:
            # Create multiple concurrent connections
            for i in range(3):
                conn = await psycopg.AsyncConnection.connect(**pgwire_connection_params)
                connections.append(conn)

                # Verify each connection works
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1")
                    result = await cur.fetchone()
                    assert result[0] == 1

            logger.info(
                "P0 multiple concurrent connections successful", connection_count=len(connections)
            )

        finally:
            # Cleanup connections
            for conn in connections:
                try:
                    await conn.close()
                except:
                    pass

    async def test_connection_termination(self, pgwire_connection_params):
        """
        E2E: Connections can be properly terminated

        SUCCESS CRITERIA:
        - Connection can be closed cleanly
        - Server handles termination gracefully
        - No protocol errors on close
        """
        import psycopg

        # Create connection
        conn = await psycopg.AsyncConnection.connect(**pgwire_connection_params)

        # Verify it's working
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1")
            result = await cur.fetchone()
            assert result[0] == 1

        # Close connection
        await conn.close()

        # Verify connection is closed
        assert conn.closed

        logger.info("P0 connection termination successful")


@pytest.mark.e2e
@pytest.mark.requires_iris
class TestP0ErrorHandling:
    """
    E2E tests for P0 error handling with real clients
    """

    def test_psql_unsupported_query(self, psql_command):
        """
        E2E: Unsupported queries return proper error messages

        For P0, only SELECT 1 is supported. Other queries should
        return helpful error messages.
        """
        result = psql_command("SELECT * FROM nonexistent_table")

        # Should fail but with proper PostgreSQL error format
        assert not result["success"]
        assert "ERROR" in result["stderr"] or "ERROR" in result["stdout"]

        logger.info("P0 error handling working", error_output=result["stderr"][:100])

    async def test_psycopg_unsupported_query(self, psycopg_connection):
        """
        E2E: psycopg receives proper error responses for unsupported queries
        """
        import psycopg

        async with psycopg_connection.cursor() as cur:
            # This should raise a PostgreSQL-compatible error
            with pytest.raises(psycopg.Error):
                await cur.execute("SELECT * FROM nonexistent_table")

        logger.info("P0 psycopg error handling working")


@pytest.mark.unit
class TestP0ProtocolMessages:
    """
    Unit tests for P0 protocol message handling

    These test the protocol implementation without requiring IRIS.
    """

    def test_ssl_request_constants(self):
        """Verify SSL request constants are correct"""
        from iris_pgwire.protocol import PROTOCOL_VERSION, SSL_REQUEST_CODE

        assert SSL_REQUEST_CODE == 80877103
        assert PROTOCOL_VERSION == 0x00030000

    def test_message_type_constants(self):
        """Verify message type constants"""
        from iris_pgwire.protocol import (
            MSG_AUTHENTICATION,
            MSG_BACKEND_KEY_DATA,
            MSG_PARAMETER_STATUS,
            MSG_QUERY,
            MSG_READY_FOR_QUERY,
        )

        assert MSG_QUERY == b"Q"
        assert MSG_AUTHENTICATION == b"R"
        assert MSG_READY_FOR_QUERY == b"Z"
        assert MSG_PARAMETER_STATUS == b"S"
        assert MSG_BACKEND_KEY_DATA == b"K"

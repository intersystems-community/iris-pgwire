"""
Main PGWire asyncio server implementation - P0 Foundation

This module implements the core asyncio TCP server for PostgreSQL wire protocol
communication with IRIS backend. Follows the embedded Python track from the
specification with E2E testing approach.
"""

import asyncio
import importlib
import logging
import os
import ssl
import sys

import structlog

# Configure structured logging FIRST so we can log reload diagnostics
# Use PrintLoggerFactory() to write directly to stdout (structlog.stdlib.LoggerFactory() needs handlers)
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),  # Write directly to stdout
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Force reload of iris_executor BEFORE importing to bypass Python module cache
# This ensures code changes are picked up in development without container rebuilds
import iris_pgwire.iris_executor

reloaded_module = importlib.reload(iris_pgwire.iris_executor)

# NOW import after reload
from .integratedml import enhance_iris_executor_with_integratedml
from .iris_executor import IRISExecutor
from .protocol import PGWireProtocol


class PGWireServer:
    """
    PostgreSQL Wire Protocol Server for IRIS

    Implements P0 foundation: SSL probe, handshake, and basic session management.
    Uses asyncio for high concurrency with one coroutine per connection.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 5432,
        iris_host: str = "localhost",
        iris_port: int = 1972,
        iris_username: str = "_SYSTEM",
        iris_password: str = "SYS",
        iris_namespace: str = "USER",
        enable_ssl: bool = False,
        ssl_cert_path: str | None = None,
        ssl_key_path: str | None = None,
        enable_scram: bool = False,
    ):

        self.host = host
        self.port = port
        self.enable_ssl = enable_ssl
        self.ssl_cert_path = ssl_cert_path
        self.ssl_key_path = ssl_key_path
        self.enable_scram = enable_scram

        # IRIS connection parameters
        self.iris_config = {
            "host": iris_host,
            "port": iris_port,
            "username": iris_username,
            "password": iris_password,
            "namespace": iris_namespace,
        }

        self.server = None
        self.ssl_context = None
        self.active_connections = set()

        # P4: Connection registry for query cancellation
        self.connection_registry = {}  # backend_pid -> (protocol, backend_secret)

        # Initialize IRIS executor with server reference for P4 cancellation
        self.iris_executor = IRISExecutor(self.iris_config, server=self)

        # Enhance with IntegratedML support
        self.iris_executor = enhance_iris_executor_with_integratedml(self.iris_executor)

        logger.info(
            "PGWire server initialized",
            host=host,
            port=port,
            iris_host=iris_host,
            iris_port=iris_port,
            iris_namespace=iris_namespace,
        )

    # P4: Connection Management for Query Cancellation

    def register_connection(self, protocol):
        """Register a connection for query cancellation"""
        self.connection_registry[protocol.backend_pid] = (protocol, protocol.backend_secret)
        logger.debug(
            "Connection registered",
            backend_pid=protocol.backend_pid,
            connection_id=protocol.connection_id,
        )

    def unregister_connection(self, protocol):
        """Unregister a connection"""
        if protocol.backend_pid in self.connection_registry:
            del self.connection_registry[protocol.backend_pid]
            logger.debug(
                "Connection unregistered",
                backend_pid=protocol.backend_pid,
                connection_id=protocol.connection_id,
            )

    def find_connection_for_cancellation(self, backend_pid: int, backend_secret: int):
        """Find connection for cancellation by PID and secret"""
        if backend_pid in self.connection_registry:
            stored_protocol, stored_secret = self.connection_registry[backend_pid]
            if stored_secret == backend_secret:
                return stored_protocol
        return None

    async def setup_ssl_context(self) -> ssl.SSLContext | None:
        """Setup SSL context for TLS connections if enabled"""
        if not self.enable_ssl:
            return None

        if not self.ssl_cert_path or not self.ssl_key_path:
            logger.warning("SSL enabled but cert/key paths not provided, disabling SSL")
            return None

        try:
            ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ssl_context.load_cert_chain(self.ssl_cert_path, self.ssl_key_path)
            logger.info("SSL context configured", cert_path=self.ssl_cert_path)
            return ssl_context
        except Exception as e:
            logger.error("Failed to setup SSL context", error=str(e))
            return None

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """
        Handle individual client connection with P0 protocol implementation

        P0 Flow:
        1. SSL probe detection (8 bytes)
        2. StartupMessage parsing
        3. Authentication (basic for P0)
        4. ParameterStatus emission
        5. BackendKeyData generation
        6. ReadyForQuery state
        """
        client_addr = writer.get_extra_info("peername")
        connection_id = f"{client_addr[0]}:{client_addr[1]}"

        logger.info("Client connection established", connection_id=connection_id)
        self.active_connections.add(writer)

        try:
            # Create protocol handler for this connection
            protocol = PGWireProtocol(
                reader, writer, self.iris_executor, connection_id, self.enable_scram
            )

            # P0 Phase: Handle SSL probe first
            await protocol.handle_ssl_probe(self.ssl_context)

            # P0 Phase: Handle startup sequence
            await protocol.handle_startup_sequence()

            # P4: Register connection for query cancellation
            self.register_connection(protocol)

            # P0 Phase: Enter message processing loop
            await protocol.message_loop()

        except asyncio.CancelledError:
            logger.info("Connection cancelled", connection_id=connection_id)
        except ConnectionAbortedError as e:
            logger.debug("Connection aborted by client", connection_id=connection_id, error=str(e))
        except Exception as e:
            logger.error("Connection error", connection_id=connection_id, error=str(e))
        finally:
            # P4: Unregister connection from cancellation registry
            if "protocol" in locals():
                self.unregister_connection(protocol)

            self.active_connections.discard(writer)
            if not writer.is_closing():
                writer.close()
                await writer.wait_closed()
            logger.info("Client connection closed", connection_id=connection_id)

    async def start(self):
        """Start the PGWire server"""
        try:
            # Test IRIS connectivity before starting
            await self.iris_executor.test_connection()

            # Setup SSL if enabled
            self.ssl_context = await self.setup_ssl_context()

            # Start TCP server
            self.server = await asyncio.start_server(self.handle_client, self.host, self.port)

            addr = self.server.sockets[0].getsockname()
            logger.info(
                "PGWire server started",
                address=f"{addr[0]}:{addr[1]}",
                ssl_enabled=self.ssl_context is not None,
                active_connections=len(self.active_connections),
            )

            # Serve forever
            async with self.server:
                await self.server.serve_forever()

        except Exception as e:
            logger.error("Failed to start PGWire server", error=str(e))
            raise

    async def stop(self):
        """Stop the PGWire server gracefully"""
        if self.server:
            self.server.close()
            await self.server.wait_closed()

            # Close all active connections
            for writer in list(self.active_connections):
                if not writer.is_closing():
                    writer.close()
                    await writer.wait_closed()

            logger.info("PGWire server stopped", connections_closed=len(self.active_connections))


async def main():
    """Main entry point for the PGWire server"""
    # Read configuration from environment
    host = os.getenv("PGWIRE_HOST", "0.0.0.0")
    port = int(os.getenv("PGWIRE_PORT", "5432"))

    iris_host = os.getenv("IRIS_HOST", "localhost")
    iris_port = int(os.getenv("IRIS_PORT", "1972"))
    iris_username = os.getenv("IRIS_USERNAME", "_SYSTEM")
    iris_password = os.getenv("IRIS_PASSWORD", "SYS")
    iris_namespace = os.getenv("IRIS_NAMESPACE", "USER")

    enable_ssl = os.getenv("PGWIRE_SSL_ENABLED", "false").lower() == "true"
    ssl_cert_path = os.getenv("PGWIRE_SSL_CERT")
    ssl_key_path = os.getenv("PGWIRE_SSL_KEY")

    debug = os.getenv("PGWIRE_DEBUG", "false").lower() == "true"

    if debug:
        logging.basicConfig(level=logging.DEBUG)

    # Create and start server
    server = PGWireServer(
        host=host,
        port=port,
        iris_host=iris_host,
        iris_port=iris_port,
        iris_username=iris_username,
        iris_password=iris_password,
        iris_namespace=iris_namespace,
        enable_ssl=enable_ssl,
        ssl_cert_path=ssl_cert_path,
        ssl_key_path=ssl_key_path,
    )

    try:
        await server.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal, shutting down...")
        await server.stop()
    except Exception as e:
        logger.error("Server error", error=str(e))
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

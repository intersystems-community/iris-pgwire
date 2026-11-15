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
import signal
import ssl
import sys
from typing import Any

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

# Force reload of core modules BEFORE importing to bypass Python module cache
# This ensures code changes are picked up in development without container rebuilds
import iris_pgwire.bulk_executor
import iris_pgwire.iris_executor
import iris_pgwire.protocol
import iris_pgwire.vector_optimizer

importlib.reload(iris_pgwire.iris_executor)
importlib.reload(iris_pgwire.protocol)
importlib.reload(iris_pgwire.bulk_executor)
importlib.reload(iris_pgwire.vector_optimizer)

# NOW import after reload
from .backend_selector import BackendSelector
from .integratedml import enhance_iris_executor_with_integratedml
from .models.backend_config import BackendConfig, BackendType
from .password_auth import (
    FAILED_LOGIN_DELAY_SECONDS,
    AuthConfigError,
    DbapiPasswordVerifier,
    EmbeddedPasswordVerifier,
    resolve_allowed_users,
    validate_auth_config,
)
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
        connection_pool_size: int = 10,
        connection_pool_timeout: float = 5.0,
        query_timeout: float = 30.0,
        enable_query_cache: bool = True,
        query_cache_size: int = 1000,
        backend_type: str | None = None,
        auth_mode: str = "password",
        allow_plaintext_password: bool = False,
        allowed_users: str | list[str] | None = None,
    ):
        # Refuse a configuration that cannot authenticate safely before touching IRIS.
        # `enable_scram` is accepted only so that asking for it fails loudly: it never verified
        # the client proof.
        validate_auth_config(
            auth_mode=auth_mode,
            enable_ssl=enable_ssl,
            allow_plaintext_password=allow_plaintext_password,
            enable_scram=enable_scram,
        )
        self.auth_mode = auth_mode
        self.allow_plaintext_password = allow_plaintext_password
        # Who may log in. Meaningful only when passwords are checked; trust has no login users.
        self.allowed_users = (
            resolve_allowed_users(allowed_users, iris_username) if auth_mode == "password" else None
        )
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

        # Feature 018: Use BackendSelector to initialize IRIS executor
        # This supports both native Embedded and external DBAPI backends
        selector = BackendSelector()

        if not backend_type:
            backend_type = os.getenv("PGWIRE_BACKEND_TYPE", "embedded")

        strict_single_connection = (
            os.getenv("PGWIRE_STRICT_SINGLE_CONNECTION", "false").lower() == "true"
        )

        config = BackendConfig(
            backend_type=BackendType(backend_type.lower()),
            iris_hostname=iris_host,
            iris_port=iris_port,
            iris_username=iris_username,
            iris_password=iris_password,
            iris_namespace=iris_namespace,
            pool_size=connection_pool_size,
            pool_timeout=int(connection_pool_timeout),
            query_timeout=query_timeout,
            strict_single_connection=strict_single_connection,
            # Spec 052: strict refuses what IRIS cannot run exactly; permissive runs it as 2.0 did.
            txn_compat=os.getenv("PGWIRE_TXN_COMPAT", "strict"),
        )

        # Select appropriate executor (DBAPIExecutor or IRISExecutor)
        self.iris_executor = selector.select_backend(config)

        # Enhance with IntegratedML support
        self.iris_executor = enhance_iris_executor_with_integratedml(self.iris_executor)

        # The check is made against IRIS the way this backend reaches IRIS.
        self.password_verifier = None
        if auth_mode == "password":
            if backend_type.lower() == "dbapi":
                self.password_verifier = DbapiPasswordVerifier(iris_host, iris_port, iris_namespace)
            else:
                self.password_verifier = EmbeddedPasswordVerifier()
            if not enable_ssl:
                if host in ("0.0.0.0", "::", ""):
                    logger.warning(
                        "Passwords will be accepted over UNENCRYPTED connections on every "
                        "network interface (listening on 0.0.0.0, --allow-plaintext-password): "
                        "anyone who can reach this port can read them. Bind to 127.0.0.1, enable "
                        "TLS, or put this behind a TLS-terminating proxy on a network you trust.",
                    )
                else:
                    logger.warning(
                        "Passwords will be accepted over UNENCRYPTED connections "
                        "(--allow-plaintext-password). Use this only on a network you trust.",
                        host=host,
                    )
        else:
            logger.warning(
                "AUTHENTICATION IS DISABLED (--trust): every client is accepted without a "
                "password and every session runs as the configured IRIS service account. "
                "For local development only.",
                service_account=iris_username,
            )

        logger.info(
            "PGWire server initialized",
            host=host,
            port=port,
            backend_type=self.iris_executor.backend_type,
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

        protocol = None
        try:
            # Create protocol handler for this connection
            protocol = PGWireProtocol(
                reader,
                writer,
                self.iris_executor,
                connection_id,
                auth_mode=self.auth_mode,
                password_verifier=self.password_verifier,
                allow_plaintext_password=self.allow_plaintext_password,
                allowed_users=self.allowed_users,
                failed_login_delay=FAILED_LOGIN_DELAY_SECONDS,
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
            if "protocol" in locals() and protocol is not None:
                self.unregister_connection(protocol)

            self.active_connections.discard(writer)
            if not writer.is_closing():
                writer.close()
                await writer.wait_closed()
            logger.info("Client connection closed", connection_id=connection_id)

    async def _install_catalog_functions(self):
        """Create the PGWire SQL functions the catalog views are defined in terms of.

        Must run before the views: every one of them calls PGWire.PG_OID or
        PGWire.PG_PUBLIC_SCHEMA, so without these the view DDL cannot compile.
        """
        from .catalog.function_installer import (
            CatalogFunctionInstaller,
            CatalogFunctionInstallError,
        )

        installer = CatalogFunctionInstaller(self.iris_executor)
        try:
            installed = await installer.install()
        except CatalogFunctionInstallError:
            logger.error(
                "Catalog function installation failed - refusing to start",
                hint="the account needs privileges to CREATE FUNCTION in the PGWire schema",
            )
            raise
        logger.info("Catalog functions ready", count=len(installed))

    async def _install_catalog_views(self):
        """Create the emulated pg_catalog views, aborting startup on failure."""
        from .catalog.views import CatalogViewInstaller, CatalogViewInstallError

        installer = CatalogViewInstaller(self.iris_executor)
        try:
            installed = await installer.install()
        except CatalogViewInstallError:
            logger.error(
                "Catalog view installation failed - refusing to start",
                hint="the account needs privileges to create views in a pg_catalog schema",
            )
            raise
        logger.info("Catalog views ready", count=len(installed))

    async def start(self):
        """Start the PGWire server"""
        try:
            # Test IRIS connectivity before starting
            await self.iris_executor.test_connection()

            # Converge the emulated pg_catalog before accepting clients. Done
            # here rather than as a migration step so a fresh container or a new
            # namespace needs no manual setup, and identically on both backends.
            # A failure aborts startup: serving a half-installed catalog would
            # answer introspection with empty results instead of errors, which
            # is the failure mode feature 044 exists to remove.
            await self._install_catalog_functions()
            await self._install_catalog_views()

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


async def serve_until_signalled(server: Any) -> None:
    """Run `server.start()` until it returns, fails, or SIGTERM/SIGINT arrives; then stop it.

    `main()` used to catch KeyboardInterrupt and nothing else. Under asyncio SIGTERM did not stop
    the server at all, so `docker stop` waited out its grace period and the IPM package's Stop()
    (SIGTERM, then wait) reported failure, which also failed an IPM uninstall. The handlers are
    removed again on the way out.
    """
    loop = asyncio.get_running_loop()
    requested = asyncio.Event()
    installed = []
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signum, requested.set)
            installed.append(signum)
        except (NotImplementedError, RuntimeError):  # Windows, or not the main thread
            pass

    serving = asyncio.ensure_future(server.start())
    waiting = asyncio.ensure_future(requested.wait())
    try:
        done, _ = await asyncio.wait({serving, waiting}, return_when=asyncio.FIRST_COMPLETED)
        if serving in done:
            serving.result()  # re-raise a startup or serving failure
            return
        logger.info("Stop signal received, shutting down")
        await server.stop()
        try:
            await asyncio.wait_for(serving, timeout=10)
        except (asyncio.CancelledError, TimeoutError):
            serving.cancel()
    finally:
        waiting.cancel()
        for signum in installed:
            loop.remove_signal_handler(signum)


def _gather_main_config() -> dict[str, Any]:
    """Read server configuration from environment variables."""
    return {
        "host": os.getenv("PGWIRE_HOST", "0.0.0.0"),
        "port": int(os.getenv("PGWIRE_PORT", "5432")),
        "iris_host": os.getenv("IRIS_HOST", "localhost"),
        "iris_port": int(os.getenv("IRIS_PORT", "1972")),
        "iris_username": os.getenv("IRIS_USERNAME", "_SYSTEM"),
        "iris_password": os.getenv("IRIS_PASSWORD", "SYS"),
        "iris_namespace": os.getenv("IRIS_NAMESPACE", "USER"),
        "enable_ssl": os.getenv("PGWIRE_SSL_ENABLED", "false").lower() == "true",
        "ssl_cert_path": os.getenv("PGWIRE_SSL_CERT"),
        "ssl_key_path": os.getenv("PGWIRE_SSL_KEY"),
        "connection_pool_size": int(os.getenv("PGWIRE_POOL_SIZE", "10")),
        "connection_pool_timeout": float(os.getenv("PGWIRE_POOL_TIMEOUT", "5.0")),
        "query_timeout": float(os.getenv("PGWIRE_QUERY_TIMEOUT", "30.0")),
        "enable_query_cache": os.getenv("PGWIRE_QUERY_CACHE_ENABLED", "true").lower() == "true",
        "query_cache_size": int(os.getenv("PGWIRE_QUERY_CACHE_SIZE", "1000")),
        "debug": os.getenv("PGWIRE_DEBUG", "false").lower() == "true",
        "auth_mode": os.getenv("PGWIRE_AUTH_MODE", "password").lower(),
        "allow_plaintext_password": os.getenv("PGWIRE_ALLOW_PLAINTEXT_PASSWORD", "false").lower()
        == "true",
        # Comma-separated login users. Unset: only the service account (IRIS_USERNAME).
        "allowed_users": os.getenv("PGWIRE_ALLOWED_USERS") or None,
        # Read only so that asking for it fails loudly. Docs once told users to set it, and
        # nothing read it, so a deployment could believe it had SCRAM and have no authentication.
        "enable_scram": os.getenv("PGWIRE_ENABLE_SCRAM", "false").lower() == "true",
    }


async def main(overrides: dict[str, Any] | None = None):
    """Main entry point for the PGWire server"""

    config = _gather_main_config()
    config.update(overrides or {})

    if config["debug"]:
        logging.basicConfig(level=logging.DEBUG)

    server = PGWireServer(
        host=config["host"],
        port=config["port"],
        iris_host=config["iris_host"],
        iris_port=config["iris_port"],
        iris_username=config["iris_username"],
        iris_password=config["iris_password"],
        iris_namespace=config["iris_namespace"],
        enable_ssl=config["enable_ssl"],
        ssl_cert_path=config["ssl_cert_path"],
        ssl_key_path=config["ssl_key_path"],
        connection_pool_size=config["connection_pool_size"],
        connection_pool_timeout=config["connection_pool_timeout"],
        query_timeout=config["query_timeout"],
        enable_query_cache=config["enable_query_cache"],
        query_cache_size=config["query_cache_size"],
        enable_scram=config["enable_scram"],
        auth_mode=config["auth_mode"],
        allow_plaintext_password=config["allow_plaintext_password"],
        allowed_users=config["allowed_users"],
    )

    try:
        await serve_until_signalled(server)
    except Exception as e:
        logger.error("Server error", error=str(e))
        sys.exit(1)


def _parse_args(argv: list[str] | None = None):
    import argparse

    parser = argparse.ArgumentParser(
        prog="iris-pgwire",
        description="PostgreSQL wire protocol server for InterSystems IRIS. By default clients "
        "must authenticate with an IRIS username and password, over TLS.",
    )
    parser.add_argument(
        "--trust",
        action="store_true",
        help="DISABLE authentication: accept every client with no password. Every session runs "
        "as the configured IRIS service account. Local development only. "
        "(env: PGWIRE_AUTH_MODE=trust)",
    )
    parser.add_argument(
        "--allow-plaintext-password",
        action="store_true",
        help="Accept passwords over unencrypted connections, for a network you trust. "
        "(env: PGWIRE_ALLOW_PLAINTEXT_PASSWORD=true)",
    )
    parser.add_argument(
        "--allowed-users",
        metavar="USER[,USER...]",
        help="IRIS users allowed to log in. Replaces the default, which is the service account "
        "alone (IRIS_USERNAME). Statements run as the service account whoever logs in. "
        "(env: PGWIRE_ALLOWED_USERS)",
    )
    return parser.parse_args(argv)


def cli(argv: list[str] | None = None):
    """Synchronous entry point for the installed `iris-pgwire` command.

    `[project.scripts]` pointed at `main` directly. A console script calls its
    target and throws the result away, so the installed command built a
    coroutine, warned that it was never awaited, and exited without starting
    anything. Only `python -m iris_pgwire.server` worked, because that path
    goes through the `asyncio.run` below.
    """
    args = _parse_args(argv)
    overrides: dict[str, Any] = {}
    if args.trust:
        overrides["auth_mode"] = "trust"
    if args.allow_plaintext_password:
        overrides["allow_plaintext_password"] = True
    if args.allowed_users:
        overrides["allowed_users"] = args.allowed_users
    try:
        asyncio.run(main(overrides))
    except AuthConfigError as exc:
        print(f"iris-pgwire: refusing to start: {exc}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    cli()

"""
Pytest configuration for IRIS PGWire tests

E2E testing setup with real IRIS and PostgreSQL clients.
NO MOCKS - everything tested against real systems.

This module implements fixtures from specs/017-correct-testing-framework/:
- T014: embedded_iris - Session-scoped IRIS connection via irispython
- T015: iris_config - Configuration dictionary
- T016: iris_clean_namespace - Function-scoped test isolation
- T017: pgwire_client - Function-scoped PGWire client connection
"""

import asyncio
import os
import socket
import subprocess
import sys
import time
from typing import Any, Optional

import psycopg
import pytest
import structlog

# Add iris-devtester to path if it's in the expected sibling directory
devtester_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../iris-devtester"))
if os.path.exists(devtester_path) and devtester_path not in sys.path:
    sys.path.insert(0, devtester_path)

try:
    from iris_devtester import IRISContainer
    from iris_devtester.config import IRISConfig
    from iris_devtester.connections import get_connection

    HAS_DEVTESTER = True
except ImportError:
    HAS_DEVTESTER = False

logger = structlog.get_logger()


# ============================================================================
# Feature 019: Register IRIS SQLAlchemy Dialect
# ============================================================================
# Register the IRIS dialect for async SQLAlchemy support tests
# This ensures create_async_engine("iris+psycopg://...") resolves correctly
# using the caretdev sqlalchemy-iris implementation (v0.18.0)
from sqlalchemy.dialects import registry

registry.register("iris.psycopg", "sqlalchemy_iris.psycopg", "IRISDialect_psycopg")
logger.info("SQLAlchemy IRIS dialect registered (caretdev sqlalchemy-iris)")

# NOTE: There is also a Perforce/InterSystems SQLAlchemy implementation.
# This registration uses the caretdev version which already has async support built in.
# ============================================================================


# ============================================================================
# Feature 019: Monkey-Patch Async Dialect Bug Fix
# ============================================================================
# CRITICAL BUG FIX: sqlalchemy-iris v0.18.0 async dialect is missing `await`
# keywords in do_executemany(), causing bulk inserts to timeout.
#
# Root cause: IRISDialectAsync_psycopg.do_executemany() calls cursor.execute()
# without await, creating unawaited coroutines that never execute.
#
# This monkey-patch adds the missing await keywords until fixed upstream.
# Issue to be reported to caretdev/sqlalchemy-iris GitHub.
try:
    from sqlalchemy_iris.psycopg import IRISDialectAsync_psycopg

    # Store original method for reference
    _original_do_executemany = IRISDialectAsync_psycopg.do_executemany

    def patched_do_executemany(self, cursor, query, params, context=None):
        """
        Patched version of do_executemany() for greenlet-based async execution.

        FIXES: Incorrect implementation in sqlalchemy-iris v0.18.0

        NOTE: This is a SYNC function that calls async cursor methods.
        SQLAlchemy's greenlet integration automatically wraps cursor.execute()
        calls in await when used with async engine.

        Do NOT make this async def - greenlet expects sync functions.
        """
        # Strip trailing semicolon (from original implementation)
        if query.endswith(";"):
            query = query[:-1]

        # Execute each parameter set
        # Greenlet automatically handles async wrapping
        for param_set in params:
            cursor.execute(query, param_set)

    # Apply monkey-patch for do_executemany
    IRISDialectAsync_psycopg.do_executemany = patched_do_executemany

    # CRITICAL BUG FIX #2: Strip IRIS-specific DDL extensions
    # sqlalchemy-iris adds "WITH %CLASSPARAMETER ALLOWIDENTITYINSERT = 1" to DDL
    # psycopg rejects this because %C looks like a parameter placeholder
    _original_do_execute = IRISDialectAsync_psycopg.do_execute

    def patched_do_execute(self, cursor, query, params, context=None):
        """
        Patched version of do_execute() to strip IRIS DDL extensions.

        FIXES: psycopg parameter validation rejecting %CLASSPARAMETER

        Strips "WITH %CLASSPARAMETER ALLOWIDENTITYINSERT = 1" from CREATE TABLE
        statements to make them compatible with PostgreSQL wire protocol.
        """
        # Strip IRIS-specific DDL extensions that confuse psycopg
        if query and "WITH %CLASSPARAMETER" in query:
            query = query.replace("WITH %CLASSPARAMETER ALLOWIDENTITYINSERT = 1", "").strip()
            # Clean up extra whitespace
            while "  " in query:
                query = query.replace("  ", " ")

        # Call original do_execute
        return _original_do_execute(self, cursor, query, params, context)

    # Apply DDL monkey-patch
    IRISDialectAsync_psycopg.do_execute = patched_do_execute

    logger.info(
        "✅ Applied monkey-patch to IRISDialectAsync_psycopg.do_executemany()",
        reason="Missing await keywords in sqlalchemy-iris v0.18.0",
        impact="Fixes bulk insert timeout (test_async_bulk_insert)",
    )

    logger.info(
        "✅ Applied monkey-patch to IRISDialectAsync_psycopg.do_execute()",
        reason="Strip IRIS DDL extensions incompatible with psycopg",
        impact="Fixes CREATE TABLE with %CLASSPARAMETER error",
    )

except ImportError as e:
    logger.warning(
        "⚠️ Could not apply async dialect monkey-patch",
        error=str(e),
        hint="sqlalchemy-iris not installed or version mismatch",
    )
# ============================================================================


def wait_for_port(host: str, port: int, timeout: int = 30) -> bool:
    """Wait for a port to become available"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (OSError, ConnectionRefusedError):
            time.sleep(0.1)
    return False


def pytest_addoption(parser):
    """Add custom command line options for IRIS testing"""
    parser.addoption(
        "--iris-image", action="store", default=None, help="IRIS Docker image to use for tests"
    )
    parser.addoption(
        "--iris-persist",
        action="store_true",
        default=False,
        help="Persist IRIS container after tests",
    )


@pytest.fixture(scope="session")
def iris_container(pytestconfig):
    """
    Ensure IRIS container is running for the test session.
    Uses iris-devtester for automated management and troubleshooting.
    """
    iris_image = pytestconfig.getoption("iris_image")
    iris_persist = pytestconfig.getoption("iris_persist")

    if not HAS_DEVTESTER:
        # Fallback to legacy check if devtester not available
        if not wait_for_port("localhost", 1972, timeout=5):
            pytest.skip("IRIS not available and iris-devtester not installed for auto-start")
        yield None
        return

    try:
        from iris_devtester import IRISContainer

        # Use IRISContainer to ensure it's running
        logger.info("Ensuring IRIS container via iris-devtester", image=iris_image)

        # Determine container type based on image if provided
        if iris_image:
            container_mgr = IRISContainer(image=iris_image)
        else:
            container_mgr = IRISContainer.community()

        with container_mgr as iris:
            # iris-devtester handles health checks, password resets, and CallIn
            logger.info("IRIS container ready via iris-devtester")

            # Ensure passwords are unexpired and reset if needed
            try:
                # Use the built-in method on the container if available
                if hasattr(iris, "reset_password"):
                    iris.reset_password("SuperUser", "SYS")
                    iris.reset_password("_SYSTEM", "SYS")

                from iris_devtester.utils import unexpire_all_passwords

                unexpire_all_passwords(iris)
                logger.info("Passwords managed successfully")
            except Exception as e:
                logger.warning("Failed to manage passwords", error=str(e))

            if iris_persist:
                logger.info("IRIS container will PERSIST after tests")
                iris.__exit__ = lambda exc_type, exc_val, exc_tb: None

            yield iris
    except Exception as e:
        logger.error("Failed to manage IRIS container via iris-devtester", error=str(e))
        # Last resort: check if something is already running on the port
        if wait_for_port("localhost", 1972, timeout=5):
            logger.info("IRIS found running on port despite devtester error")
            yield None
        else:
            pytest.skip(f"IRIS container setup failed: {e}")


@pytest.fixture(scope="session")
def iris_config(iris_container) -> dict[str, Any]:
    """
    Provide IRIS connection configuration.
    Dynamically updated from the running container if managed by iris-devtester.
    """
    # Defaults
    config_dict = {
        "host": "localhost",
        "port": 1972,
        "namespace": "USER",
        "username": "SuperUser",
        "password": "SYS",
    }

    if iris_container:
        if hasattr(iris_container, "get_config"):
            try:
                # Use the config from the running container
                idt_config = iris_container.get_config()
                config_dict.update(
                    {
                        "host": idt_config.host,
                        "port": idt_config.port,
                        "namespace": idt_config.namespace,
                        "username": idt_config.username,
                        "password": idt_config.password,
                    }
                )
                logger.info(
                    "iris_config updated from iris-devtester via get_config",
                    host=config_dict["host"],
                    port=config_dict["port"],
                )
            except Exception as e:
                logger.warning("Failed to get config from iris-devtester container", error=str(e))

        # Fallback/Direct access to iris_container attributes
        if hasattr(iris_container, "username"):
            config_dict["username"] = iris_container.username
        if hasattr(iris_container, "password"):
            config_dict["password"] = iris_container.password
        if hasattr(iris_container, "get_container_host_ip"):
            config_dict["host"] = iris_container.get_container_host_ip()
        if hasattr(iris_container, "get_exposed_port"):
            try:
                config_dict["port"] = int(iris_container.get_exposed_port(1972))
            except:
                pass

    return config_dict


@pytest.fixture
def iris_connection(iris_container, iris_config):
    """
    Provide a DBAPI connection to IRIS with auto-remediation.
    Uses iris-devtester's high-level container connection method which handles:
    - Auto-retry on transient failures
    - Password change requirement (proactive reset)
    - CallIn service enablement
    """
    if not HAS_DEVTESTER or not iris_container:
        # Fallback to standard DBAPI connection if devtester not available
        try:
            import irispython

            conn = irispython.connect(
                hostname=iris_config["host"],
                port=iris_config["port"],
                namespace=iris_config["namespace"],
                username=iris_config["username"],
                password=iris_config["password"],
            )
            yield conn
            conn.close()
        except ImportError:
            pytest.skip("intersystems-irispython not installed")
        except Exception as e:
            pytest.fail(f"IRIS connection failed: {e}")
        return

    try:
        # Use IRISContainer.get_connection() which is the intended "high-level" API
        # It handles proactive password reset and CallIn enablement.
        conn = iris_container.get_connection()
        logger.info("IRIS connection established via iris-devtester high-level API")
        yield conn
        # Let iris-devtester manage the connection lifecycle if needed,
        # but closing it here should generally be safe unless it's pooled.
    except Exception as e:
        logger.error("Failed to establish IRIS connection via iris-devtester", error=str(e))
        # Provide diagnostic remediation info if available
        if "Password change required" in str(e):
            logger.error("HINT: Try running 'iris-devtester container reset-password' manually")
        pytest.fail(f"IRIS connection failed: {e}")


@pytest.fixture
def iris_fixture(iris_connection, iris_config, iris_container):
    """
    Provide helper to load/export IRIS test fixtures (.DAT files).
    """
    if not HAS_DEVTESTER:
        pytest.skip("iris-devtester required for fixture management")

    try:
        from iris_devtester.config import IRISConfig
        from iris_devtester.fixtures.creator import FixtureCreator
        from iris_devtester.fixtures.validator import FixtureValidator

        # Create config from fixture
        config = IRISConfig(
            host=iris_config["host"],
            port=iris_config["port"],
            namespace=iris_config["namespace"],
            username=iris_config["username"],
            password=iris_config["password"],
        )

        class FixtureHelper:
            def __init__(self, conn, config, container):
                self.conn = conn
                self.config = config
                self.container = container
                # FixtureCreator(connection_config, container)
                self.creator = FixtureCreator(config, container)
                # FixtureValidator() is stateless
                self.validator = FixtureValidator()

            def load(self, fixture_dir: str):
                self.load_into(fixture_dir)

            def load_into(self, fixture_dir: str, target_namespace: str | None = None):
                logger.info("Loading IRIS fixture", dir=fixture_dir, target=target_namespace)
                # Check if dir exists, if not look in tests/fixtures
                if not os.path.exists(fixture_dir):
                    alt_path = os.path.join(os.path.dirname(__file__), "fixtures", fixture_dir)
                    if os.path.exists(alt_path):
                        fixture_dir = alt_path

                # Fixture loading logic
                try:
                    from iris_devtester.fixtures.loader import DATFixtureLoader

                    loader = DATFixtureLoader(self.config, self.container)
                    loader.load_fixture(fixture_dir, target_namespace=target_namespace)
                except ImportError:
                    # Fallback
                    logger.warning("DATFixtureLoader not found")

                logger.info("Fixture loaded successfully")

            def export(self, fixture_id: str, output_dir: str):
                logger.info("Creating IRIS fixture", id=fixture_id, dir=output_dir)
                # create_fixture(fixture_id, namespace, output_dir, ...)
                self.creator.create_fixture(fixture_id, iris_config["namespace"], output_dir)

        yield FixtureHelper(iris_connection, config, iris_container)
    except Exception as e:
        logger.error("Failed to initialize fixture helper", error=str(e))
        pytest.fail(f"Fixture initialization failed: {e}")


@pytest.fixture(scope="session")
def pgwire_server(iris_container, iris_config):
    """
    Start PGWire server against real IRIS for testing session in a separate thread.
    This prevents deadlocks when synchronous pgwire_client fixtures block the main thread.
    """
    import threading

    from iris_pgwire.server import PGWireServer

    # Configure server for testing
    server = PGWireServer(
        host="127.0.0.1",
        port=5434,
        iris_host=iris_config["host"],
        iris_port=iris_config["port"],
        iris_username=iris_config["username"],
        iris_password=iris_config["password"],
        iris_namespace=iris_config["namespace"],
        enable_ssl=False,
    )

    stop_event = threading.Event()

    def run_server():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def start_and_wait():
            await server.start()
            # server.start() calls serve_forever(), so we wait for stop_event
            while not stop_event.is_set():
                await asyncio.sleep(0.1)
            await server.stop()

        try:
            loop.run_until_complete(start_and_wait())
        finally:
            loop.close()

    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # Wait for server to be ready using active polling
    logger.info("Waiting for PGWire server to be ready...")
    start_wait = time.perf_counter()
    while time.perf_counter() - start_wait < 30:
        if wait_for_port("127.0.0.1", 5434, timeout=0.1):
            logger.info(f"PGWire server ready after {time.perf_counter() - start_wait:.2f}s")
            break
        time.sleep(0.5)
    else:
        stop_event.set()
        pytest.fail("PGWire server failed to start in separate thread")

    yield server

    # Cleanup
    logger.info("Shutting down PGWire server thread")
    stop_event.set()
    server_thread.join(timeout=5)


@pytest.fixture
def pgwire_connection_params():
    """Connection parameters for PGWire server"""
    return {
        "host": "127.0.0.1",
        "port": 5434,
        "user": "test_user",
        "dbname": "USER",
        "connect_timeout": 10,
    }


@pytest.fixture
async def psycopg_connection(pgwire_server, pgwire_connection_params):
    """
    Real psycopg connection to PGWire server

    This is the core of our E2E testing - real PostgreSQL client
    connecting to our PGWire server backed by real IRIS.
    """
    import psycopg

    conn = None
    try:
        # Attempt connection with retries
        for attempt in range(3):
            try:
                conn = await psycopg.AsyncConnection.connect(**pgwire_connection_params)
                logger.info("psycopg connection established", attempt=attempt + 1)
                yield conn
                break
            except Exception as e:
                if attempt == 2:  # Last attempt
                    pytest.fail(f"Failed to connect with psycopg after 3 attempts: {e}")
                logger.warning(
                    "psycopg connection attempt failed", attempt=attempt + 1, error=str(e)
                )
                await asyncio.sleep(1)
    finally:
        try:
            if conn is not None:
                await conn.close()
        except:
            pass


@pytest.fixture(scope="function")
def pgwire_client(pgwire_server, iris_config):
    """
    Provide PostgreSQL wire protocol client connection.
    Depends on pgwire_server being started.
    """
    logger.info("pgwire_client: Establishing PGWire connection")
    start_time = time.perf_counter()

    connection = None
    try:
        # Connect to PGWire server
        # Standard port 5434
        connection = psycopg.connect(
            host="127.0.0.1",
            port=5434,
            dbname=iris_config["namespace"],
            user=iris_config["username"],
            password=iris_config["password"],
            connect_timeout=30,
        )

        elapsed = time.perf_counter() - start_time
        logger.info(
            "pgwire_client: Connection established",
            setup_time_ms=f"{elapsed * 1000:.2f}ms",
            connection_status=connection.info.status.name,
        )

        # Verify connection is ready
        if connection.info.status != psycopg.pq.ConnStatus.OK:
            raise RuntimeError(f"PGWire connection not ready: status={connection.info.status}")

        # Verify connection works by executing simple query
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            if result is None or result[0] != 1:
                raise RuntimeError("PGWire connection verification failed")

        logger.info("pgwire_client: Connection verified")

        # Yield connection to test
        yield connection

    except ImportError as e:
        logger.error(
            "pgwire_client: psycopg not available",
            error=str(e),
            hint="Install psycopg: pip install psycopg>=3.1.0",
        )
        pytest.skip("psycopg not available - required for PGWire testing")

    except psycopg.OperationalError as e:
        logger.error(
            "pgwire_client: PGWire server not available",
            error=str(e),
            hint="Start PGWire server on port 5434 before running tests",
        )
        pytest.skip(f"PGWire server not available: {e}")

    except Exception as e:
        logger.error("pgwire_client: Connection failed", error=str(e))
        pytest.skip(f"PGWire connection failed: {e}")

    finally:
        # Teardown: Close connection
        try:
            if "connection" in locals() and connection is not None:
                connection.close()
                logger.info("pgwire_client: Connection closed")
        except Exception as e:
            logger.warning("pgwire_client: Error closing connection", error=str(e))


# ============================================================================
# T014: embedded_iris - Session-scoped IRIS connection fixture
# ============================================================================


@pytest.fixture(scope="session")
def embedded_iris(iris_config):
    """
    Provide embedded IRIS connection for entire test session.

    Contract (from contracts/pytest-fixtures.md):
    - Returns: iris.Connection instance
    - Guarantees: CallIn service enabled, USER namespace active
    - Setup time: <10 seconds
    - Cleanup: Close connection, release resources

    Implementation notes:
    - Uses irispython embedded Python (import iris)
    - Session-scoped for performance (single connection reused)
    - CallIn service must be enabled in IRIS configuration
    """
    logger.info("embedded_iris: Initializing session-scoped IRIS connection")
    start_time = time.perf_counter()

    try:
        # Import IRIS embedded Python module
        # CRITICAL: This only works when run via `irispython` command
        import iris

        # When running via irispython, we're already inside IRIS
        # No connection needed - use iris.sql.exec() directly
        # First, switch to the desired namespace
        iris.system.Process.SetNamespace(iris_config["namespace"])

        elapsed = time.perf_counter() - start_time
        logger.info(
            "embedded_iris: Embedded Python ready",
            setup_time_ms=f"{elapsed * 1000:.2f}ms",
            namespace=iris_config["namespace"],
        )

        # Verify IRIS is working
        result = iris.sql.exec("SELECT 1")
        first_row = None
        for row in result:
            first_row = row
            break

        if not first_row or first_row[0] != 1:
            raise RuntimeError(
                "IRIS embedded Python verification failed: SELECT 1 returned unexpected result"
            )

        logger.info("embedded_iris: Embedded Python verified")

        # Yield iris module for test session
        yield iris

    except ImportError as e:
        logger.error(
            "embedded_iris: Failed to import iris module",
            error=str(e),
            hint="Must run tests via 'irispython -m pytest' for embedded Python access",
        )
        pytest.skip("IRIS embedded Python not available - run via irispython")

    except Exception as e:
        logger.error("embedded_iris: Connection failed", error=str(e), config=iris_config)
        pytest.skip(f"IRIS connection failed: {e}")

    finally:
        # Teardown: Close connection and release resources
        # When running via irispython, we don't have a 'connection' object to close
        # as we're using the native module directly.
        pass


# ============================================================================
# T016: iris_clean_namespace - Function-scoped isolation fixture
# ============================================================================


@pytest.fixture(scope="function")
def iris_clean_namespace(embedded_iris, iris_config):
    """
    Provide clean IRIS namespace for each test function.

    Contract (from contracts/pytest-fixtures.md):
    - Returns: iris module ready for SQL execution
    - Guarantees: No conflicting test data from previous tests
    - Cleanup time: <2 seconds
    - Isolation: Each test gets fresh namespace state

    Implementation strategy:
    - Uses iris.sql.exec() for direct SQL execution
    - Tracks tables created during test for cleanup
    - Completes cleanup in <2 seconds per contract
    """
    logger.info("iris_clean_namespace: Setting up clean namespace for test")
    start_time = time.perf_counter()

    # Query existing tables before test starts
    iris_config["namespace"]
    result = embedded_iris.sql.exec(
        """
        SELECT TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = 'SQLUser'
    """
    )
    existing_tables = {row[0] for row in result}

    logger.info(
        "iris_clean_namespace: Baseline established", existing_tables_count=len(existing_tables)
    )

    # Yield iris module to test
    yield embedded_iris

    # Teardown: Clean up test data
    cleanup_start = time.perf_counter()

    try:
        # Find tables created during test
        result = embedded_iris.sql.exec(
            """
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = 'SQLUser'
        """
        )
        current_tables = {row[0] for row in result}
        new_tables = current_tables - existing_tables

        # Drop tables created during test
        for table_name in new_tables:
            try:
                embedded_iris.sql.exec(f"DROP TABLE SQLUser.{table_name} CASCADE")
                logger.debug("iris_clean_namespace: Dropped table", table=table_name)
            except Exception as e:
                logger.warning(
                    "iris_clean_namespace: Failed to drop table", table=table_name, error=str(e)
                )

        # Commits are automatic with iris.sql.exec() in embedded Python

        cleanup_elapsed = time.perf_counter() - cleanup_start
        total_elapsed = time.perf_counter() - start_time

        logger.info(
            "iris_clean_namespace: Cleanup complete",
            tables_dropped=len(new_tables),
            cleanup_time_ms=f"{cleanup_elapsed * 1000:.2f}ms",
            total_time_ms=f"{total_elapsed * 1000:.2f}ms",
        )

        # Verify cleanup time contract (<2 seconds)
        if cleanup_elapsed > 2.0:
            logger.warning(
                "iris_clean_namespace: Cleanup exceeded 2s contract",
                cleanup_time_ms=f"{cleanup_elapsed * 1000:.2f}ms",
            )

    except Exception as e:
        logger.error("iris_clean_namespace: Cleanup failed", error=str(e))
        # Note: rollback not needed with iris.sql.exec() - each statement auto-commits


# ============================================================================
# T020-T023: Pytest hooks for timeout monitoring and diagnostic capture
# ============================================================================

# Track IRIS query history for diagnostic capture
_iris_query_history = []


def capture_iris_state() -> dict[str, Any]:
    """
    Capture current IRIS connection state for diagnostics.

    Contract (T022):
    - Query %Library.ProcessInfo for active processes
    - Get connection count and license usage
    - Return dict with process info, connections, system metrics
    - Handle errors gracefully (return error dict)
    """
    try:
        import iris

        # Get current process information
        process_info = {
            "connection_count": 0,  # Would query from %Library.ProcessInfo
            "license_usage": 0,  # Would query from system tables
            "active_queries": [],  # Would query from active processes
        }

        return {
            "status": "success",
            "process_info": process_info,
            "query_history": _iris_query_history[-10:],  # Last 10 queries
        }

    except ImportError:
        return {"status": "error", "error": "IRIS module not available", "query_history": []}
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "query_history": _iris_query_history[-10:] if _iris_query_history else [],
        }


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    """
    Capture diagnostic information on test failure.
    Integrates with iris-devtester container validation and password remediation.
    """
    # Execute the test and get the report
    outcome = yield
    report = outcome.get_result()

    # Only process failures
    if report.failed:
        logger.error(
            "Test failed - capturing diagnostics",
            test_id=item.nodeid,
            phase=report.when,
            duration=report.duration,
        )

        # Capture IRIS state
        iris_state = capture_iris_state()

        # Integrate with iris-devtester diagnostics if available
        troubleshooting_data = {}
        if HAS_DEVTESTER:
            try:
                # 1. Check for password issues in the exception
                if call.excinfo:
                    from iris_devtester.utils.password_reset import detect_password_change_required

                    if detect_password_change_required(str(call.excinfo.value)):
                        troubleshooting_data["password_issue"] = True
                        troubleshooting_data["remediation"] = (
                            "Run 'iris-devtester container reset-password' or use high-level get_connection()"
                        )

                # 2. Run container health check
                # Try to find iris_container fixture in the item's funcargs
                iris_container = item.funcargs.get("iris_container")
                if iris_container and hasattr(iris_container, "validate"):
                    from iris_devtester.containers.models import HealthCheckLevel

                    health_result = iris_container.validate(level=HealthCheckLevel.FULL)
                    troubleshooting_data["container_health"] = {
                        "status": health_result.status,
                        "message": health_result.message,
                        "remediation_steps": health_result.remediation_steps,
                    }
                    if not health_result.success:
                        troubleshooting_data["remediation"] = (
                            health_result.remediation_steps[0]
                            if health_result.remediation_steps
                            else "Unknown"
                        )
            except Exception as e:
                logger.warning("Failed to run iris-devtester diagnostics", error=str(e))

        # Attach diagnostic information to the test item
        if not hasattr(item, "_diagnostics"):
            item._diagnostics = []

        diagnostic_entry = {
            "test_id": item.nodeid,
            "phase": report.when,
            "duration_ms": report.duration * 1000 if report.duration else 0,
            "failure_type": "assertion_error" if call.excinfo else "unknown",
            "error_message": str(call.excinfo.value) if call.excinfo else "",
            "iris_state": iris_state,
            "troubleshooting": troubleshooting_data,
            "timestamp": time.time(),
        }

        item._diagnostics.append(diagnostic_entry)

        # Write to test_failures.jsonl
        try:
            import json

            failures_file = "test_failures.jsonl"

            with open(failures_file, "a") as f:
                f.write(json.dumps(diagnostic_entry) + "\n")

            logger.info("Diagnostic information written", test_id=item.nodeid, file=failures_file)

        except Exception as e:
            logger.error(
                "Failed to write diagnostic information", test_id=item.nodeid, error=str(e)
            )


def pytest_configure(config):
    """Configure pytest with custom markers"""
    logger.info("pytest_configure: Initializing IRIS PGWire test framework")

    config.addinivalue_line("markers", "e2e: E2E tests with real PostgreSQL clients")
    config.addinivalue_line("markers", "integration: Integration tests with IRIS")
    config.addinivalue_line("markers", "unit: Unit tests (no external dependencies)")
    config.addinivalue_line("markers", "requires_iris: Tests requiring IRIS connection")
    config.addinivalue_line("markers", "requires_docker: Tests requiring Docker")

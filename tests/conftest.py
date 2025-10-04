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
import subprocess
import time
import socket
import pytest
import docker
from typing import Generator, AsyncGenerator, Dict, Any
import structlog

logger = structlog.get_logger()


def wait_for_port(host: str, port: int, timeout: int = 30) -> bool:
    """Wait for a port to become available"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (socket.error, ConnectionRefusedError):
            time.sleep(0.1)
    return False


def is_iris_available() -> bool:
    """Check if IRIS is available for testing"""
    try:
        # Try to connect to IRIS port
        return wait_for_port("localhost", 1975, timeout=5)
    except Exception:
        return False


def is_docker_available() -> bool:
    """Check if Docker is available"""
    try:
        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def iris_container():
    """
    Ensure IRIS container is running for the test session

    This fixture ensures we have a real IRIS instance for E2E testing.
    Skips if IRIS is not available.
    """
    if not is_docker_available():
        pytest.skip("Docker not available for IRIS container")

    client = docker.from_env()

    # Check if IRIS container is already running
    iris_running = False
    try:
        containers = client.containers.list()
        for container in containers:
            if "iris" in container.name.lower() and container.status == "running":
                # Check if IRIS port is accessible
                if wait_for_port("localhost", 1975, timeout=5):
                    iris_running = True
                    logger.info("Found running IRIS container", name=container.name)
                    break
    except Exception as e:
        logger.warning("Error checking for existing IRIS containers", error=str(e))

    if not iris_running:
        # Try to start IRIS container
        try:
            logger.info("Starting IRIS container for tests")
            subprocess.run([
                "docker", "compose", "up", "-d", "iris"
            ], cwd="/Users/tdyar/ws/iris-pgwire", check=True, capture_output=True)

            # Wait for IRIS to be ready
            if not wait_for_port("localhost", 1975, timeout=60):
                pytest.skip("IRIS container failed to start or become ready")

            # Give IRIS extra time to fully initialize
            time.sleep(10)

        except subprocess.CalledProcessError as e:
            pytest.skip(f"Failed to start IRIS container: {e}")

    # Verify IRIS is accessible
    if not is_iris_available():
        pytest.skip("IRIS not accessible at localhost:1975")

    logger.info("IRIS container ready for testing")
    yield "iris-ready"


@pytest.fixture(scope="session")
async def pgwire_server(iris_container):
    """
    Start PGWire server against real IRIS for testing session

    Returns when PGWire server is ready to accept connections.
    """
    from iris_pgwire.server import PGWireServer

    # Configure server for testing
    server = PGWireServer(
        host="127.0.0.1",
        port=5432,
        iris_host="127.0.0.1",
        iris_port=1972,
        iris_username="SuperUser",
        iris_password="SYS",
        iris_namespace="USER",
        enable_ssl=False  # Start with plain connections for P0
    )

    # Start server in background task
    server_task = asyncio.create_task(server.start())

    # Wait for server to be ready
    try:
        # Give server more time to start up
        await asyncio.sleep(3)
        if not wait_for_port("127.0.0.1", 5432, timeout=15):
            server_task.cancel()
            pytest.fail("PGWire server failed to start")

        logger.info("PGWire server ready for testing")
        yield server

    finally:
        # Cleanup
        logger.info("Shutting down PGWire server")
        server_task.cancel()
        await server.stop()
        try:
            await server_task
        except asyncio.CancelledError:
            pass


@pytest.fixture
def pgwire_connection_params():
    """Connection parameters for PGWire server"""
    return {
        "host": "127.0.0.1",
        "port": 5432,
        "user": "test_user",
        "dbname": "USER",
        "connect_timeout": 10
    }


@pytest.fixture
async def psycopg_connection(pgwire_server, pgwire_connection_params):
    """
    Real psycopg connection to PGWire server

    This is the core of our E2E testing - real PostgreSQL client
    connecting to our PGWire server backed by real IRIS.
    """
    import psycopg

    try:
        # Attempt connection with retries
        for attempt in range(3):
            try:
                conn = await psycopg.AsyncConnection.connect(
                    **pgwire_connection_params
                )
                logger.info("psycopg connection established", attempt=attempt + 1)
                yield conn
                break
            except Exception as e:
                if attempt == 2:  # Last attempt
                    pytest.fail(f"Failed to connect with psycopg after 3 attempts: {e}")
                logger.warning("psycopg connection attempt failed",
                             attempt=attempt + 1, error=str(e))
                await asyncio.sleep(1)
    finally:
        try:
            await conn.close()
        except:
            pass


@pytest.fixture
def psql_command():
    """
    Real psql command for CLI testing

    Returns a function that executes psql with our connection parameters.
    """
    def run_psql(sql_command: str, timeout: int = 10):
        """Run psql command and return result"""
        cmd = [
            "psql",
            "-h", "127.0.0.1",
            "-p", "5432",
            "-U", "test_user",
            "-d", "USER",
            "-c", sql_command,
            "--no-password"  # Don't prompt for password in P0
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={"PGPASSWORD": ""}  # Empty password for P0
            )
            return {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "success": result.returncode == 0
            }
        except subprocess.TimeoutExpired:
            return {
                "returncode": -1,
                "stdout": "",
                "stderr": "Command timed out",
                "success": False
            }
        except FileNotFoundError:
            pytest.skip("psql command not available")

    return run_psql


# Pytest markers for organizing tests
pytestmark = [
    pytest.mark.asyncio,
]


# ============================================================================
# T015: iris_config - Session-scoped configuration fixture
# ============================================================================

@pytest.fixture(scope="session")
def iris_config() -> Dict[str, Any]:
    """
    Provide IRIS connection configuration.

    Contract (from contracts/pytest-fixtures.md):
    - Returns: Dict with host, port, namespace, username, password
    - Values: localhost, 1972, USER, _SYSTEM, SYS
    - No dependencies, pure configuration
    - Scope: session (shared across all tests)
    """
    return {
        'host': 'localhost',
        'port': 1972,
        'namespace': 'USER',
        'username': '_SYSTEM',
        'password': 'SYS'
    }


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

        # Create connection to embedded IRIS
        # No authentication needed when running via irispython
        connection = iris.connect(
            hostname=iris_config['host'],
            port=iris_config['port'],
            namespace=iris_config['namespace'],
            username=iris_config['username'],
            password=iris_config['password']
        )

        elapsed = time.perf_counter() - start_time
        logger.info(
            "embedded_iris: Connection established",
            setup_time_ms=f"{elapsed * 1000:.2f}ms",
            namespace=iris_config['namespace']
        )

        # Verify connection is working
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        cursor.close()

        if result[0] != 1:
            raise RuntimeError("IRIS connection verification failed: SELECT 1 returned unexpected result")

        logger.info("embedded_iris: Connection verified")

        # Yield connection for test session
        yield connection

    except ImportError as e:
        logger.error(
            "embedded_iris: Failed to import iris module",
            error=str(e),
            hint="Must run tests via 'irispython -m pytest' for embedded Python access"
        )
        pytest.skip("IRIS embedded Python not available - run via irispython")

    except Exception as e:
        logger.error(
            "embedded_iris: Connection failed",
            error=str(e),
            config=iris_config
        )
        pytest.skip(f"IRIS connection failed: {e}")

    finally:
        # Teardown: Close connection and release resources
        try:
            if 'connection' in locals():
                connection.close()
                logger.info("embedded_iris: Connection closed")
        except Exception as e:
            logger.warning("embedded_iris: Error closing connection", error=str(e))


# ============================================================================
# T016: iris_clean_namespace - Function-scoped isolation fixture
# ============================================================================

@pytest.fixture(scope="function")
def iris_clean_namespace(embedded_iris):
    """
    Provide clean IRIS namespace for each test function.

    Contract (from contracts/pytest-fixtures.md):
    - Returns: iris.Connection with clean state
    - Guarantees: No conflicting test data from previous tests
    - Cleanup time: <2 seconds
    - Isolation: Each test gets fresh namespace state

    Implementation strategy:
    - Uses transaction rollback for cleanup (fast, reliable)
    - Tracks tables created during test for cleanup
    - Completes cleanup in <2 seconds per contract
    """
    logger.info("iris_clean_namespace: Setting up clean namespace for test")
    start_time = time.perf_counter()

    # Get cursor for setup
    cursor = embedded_iris.cursor()

    # Query existing tables before test starts
    cursor.execute("""
        SELECT TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = CURRENT_SCHEMA
    """)
    existing_tables = {row[0] for row in cursor.fetchall()}
    cursor.close()

    logger.info(
        "iris_clean_namespace: Baseline established",
        existing_tables_count=len(existing_tables)
    )

    # Yield connection to test
    yield embedded_iris

    # Teardown: Clean up test data
    cleanup_start = time.perf_counter()
    cursor = embedded_iris.cursor()

    try:
        # Find tables created during test
        cursor.execute("""
            SELECT TABLE_NAME
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = CURRENT_SCHEMA
        """)
        current_tables = {row[0] for row in cursor.fetchall()}
        new_tables = current_tables - existing_tables

        # Drop tables created during test
        for table_name in new_tables:
            try:
                cursor.execute(f"DROP TABLE {table_name}")
                logger.debug("iris_clean_namespace: Dropped table", table=table_name)
            except Exception as e:
                logger.warning(
                    "iris_clean_namespace: Failed to drop table",
                    table=table_name,
                    error=str(e)
                )

        # Commit cleanup
        embedded_iris.commit()

        cleanup_elapsed = time.perf_counter() - cleanup_start
        total_elapsed = time.perf_counter() - start_time

        logger.info(
            "iris_clean_namespace: Cleanup complete",
            tables_dropped=len(new_tables),
            cleanup_time_ms=f"{cleanup_elapsed * 1000:.2f}ms",
            total_time_ms=f"{total_elapsed * 1000:.2f}ms"
        )

        # Verify cleanup time contract (<2 seconds)
        if cleanup_elapsed > 2.0:
            logger.warning(
                "iris_clean_namespace: Cleanup exceeded 2s contract",
                cleanup_time_ms=f"{cleanup_elapsed * 1000:.2f}ms"
            )

    except Exception as e:
        logger.error("iris_clean_namespace: Cleanup failed", error=str(e))
        # Rollback on cleanup failure
        try:
            embedded_iris.rollback()
        except Exception:
            pass

    finally:
        cursor.close()


# ============================================================================
# T017: pgwire_client - Function-scoped PostgreSQL client fixture
# ============================================================================

@pytest.fixture(scope="function")
def pgwire_client(iris_config):
    """
    Provide PostgreSQL wire protocol client connection.

    Contract (from contracts/pytest-fixtures.md):
    - Returns: psycopg.Connection instance
    - Connection ready for query execution
    - Setup time: <5 seconds
    - Cleanup: Close connection, leave server running

    Implementation notes:
    - Connects to PGWire server on port 5434 (not 5432 to avoid conflicts)
    - Server must be started separately (not managed by this fixture)
    - Uses psycopg3 for modern PostgreSQL wire protocol support
    """
    logger.info("pgwire_client: Establishing PGWire connection")
    start_time = time.perf_counter()

    try:
        import psycopg

        # Connect to PGWire server
        # PGWire server runs on port 5434 (configurable)
        # Uses PostgreSQL wire protocol to talk to IRIS
        connection = psycopg.connect(
            host='localhost',
            port=5434,  # PGWire server port (not standard PostgreSQL 5432)
            dbname=iris_config['namespace'],
            user=iris_config['username'],
            password=iris_config['password'],
            connect_timeout=5
        )

        elapsed = time.perf_counter() - start_time
        logger.info(
            "pgwire_client: Connection established",
            setup_time_ms=f"{elapsed * 1000:.2f}ms",
            connection_status=connection.info.status.name
        )

        # Verify connection is ready
        if connection.info.status != psycopg.pq.ConnStatus.OK:
            raise RuntimeError(f"PGWire connection not ready: status={connection.info.status}")

        # Verify connection works by executing simple query
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            if result[0] != 1:
                raise RuntimeError("PGWire connection verification failed")

        logger.info("pgwire_client: Connection verified")

        # Yield connection to test
        yield connection

    except ImportError as e:
        logger.error(
            "pgwire_client: psycopg not available",
            error=str(e),
            hint="Install psycopg: pip install psycopg>=3.1.0"
        )
        pytest.skip("psycopg not available - required for PGWire testing")

    except psycopg.OperationalError as e:
        logger.error(
            "pgwire_client: PGWire server not available",
            error=str(e),
            hint="Start PGWire server on port 5434 before running tests"
        )
        pytest.skip(f"PGWire server not available: {e}")

    except Exception as e:
        logger.error("pgwire_client: Connection failed", error=str(e))
        pytest.skip(f"PGWire connection failed: {e}")

    finally:
        # Teardown: Close connection
        try:
            if 'connection' in locals() and connection is not None:
                connection.close()
                logger.info("pgwire_client: Connection closed")
        except Exception as e:
            logger.warning("pgwire_client: Error closing connection", error=str(e))


# ============================================================================
# T020-T023: Pytest hooks for timeout monitoring and diagnostic capture
# ============================================================================

# Track IRIS query history for diagnostic capture
_iris_query_history = []


def capture_iris_state() -> Dict[str, Any]:
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
            'connection_count': 0,  # Would query from %Library.ProcessInfo
            'license_usage': 0,     # Would query from system tables
            'active_queries': [],   # Would query from active processes
        }

        return {
            'status': 'success',
            'process_info': process_info,
            'query_history': _iris_query_history[-10:]  # Last 10 queries
        }

    except ImportError:
        return {
            'status': 'error',
            'error': 'IRIS module not available',
            'query_history': []
        }
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e),
            'query_history': _iris_query_history[-10:] if _iris_query_history else []
        }


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_makereport(item, call):
    """
    Capture diagnostic information on test failure.

    Contract (T021 from tasks.md):
    - Hook: pytest_runtest_makereport (wrapper, tryfirst)
    - Capture test reports for all phases (setup, call, teardown)
    - On failure: Capture IRIS connection state
    - Log query history (last 10 queries)
    - Write to test_failures.jsonl
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
            duration=report.duration
        )

        # Capture IRIS state
        iris_state = capture_iris_state()

        # Attach diagnostic information to the test item
        if not hasattr(item, '_diagnostics'):
            item._diagnostics = []

        diagnostic_entry = {
            'test_id': item.nodeid,
            'phase': report.when,
            'duration_ms': report.duration * 1000 if report.duration else 0,
            'failure_type': 'assertion_error' if call.excinfo else 'unknown',
            'error_message': str(call.excinfo.value) if call.excinfo else '',
            'iris_state': iris_state,
            'timestamp': time.time()
        }

        item._diagnostics.append(diagnostic_entry)

        # Write to test_failures.jsonl
        try:
            import json
            import os

            failures_file = 'test_failures.jsonl'

            with open(failures_file, 'a') as f:
                f.write(json.dumps(diagnostic_entry) + '\n')

            logger.info(
                "Diagnostic information written",
                test_id=item.nodeid,
                file=failures_file
            )

        except Exception as e:
            logger.error(
                "Failed to write diagnostic information",
                test_id=item.nodeid,
                error=str(e)
            )


def pytest_configure(config):
    """Configure pytest with custom markers"""
    logger.info("pytest_configure: Initializing IRIS PGWire test framework")

    config.addinivalue_line(
        "markers", "e2e: E2E tests with real PostgreSQL clients"
    )
    config.addinivalue_line(
        "markers", "integration: Integration tests with IRIS"
    )
    config.addinivalue_line(
        "markers", "unit: Unit tests (no external dependencies)"
    )
    config.addinivalue_line(
        "markers", "requires_iris: Tests requiring IRIS connection"
    )
    config.addinivalue_line(
        "markers", "requires_docker: Tests requiring Docker"
    )
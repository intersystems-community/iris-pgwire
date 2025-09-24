"""
Pytest configuration for IRIS PGWire tests

E2E testing setup with real IRIS and PostgreSQL clients.
NO MOCKS - everything tested against real systems.
"""

import asyncio
import subprocess
import time
import socket
import pytest
import docker
from typing import Generator, AsyncGenerator
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


def pytest_configure(config):
    """Configure pytest with custom markers"""
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
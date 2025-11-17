"""
E2E Test Infrastructure for P6 COPY Protocol

Provides pytest fixtures for executing psql commands with stdin/stdout redirection
against a running IRIS+PGWire server.

Constitutional Requirements:
- Test-First Development (Principle II): Real PostgreSQL clients for E2E testing
- No Mocks: Tests against actual IRIS database and PGWire protocol
"""

import subprocess
import time
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def iris_container():
    """
    Verify IRIS container is running and accessible.

    Returns:
        dict: Connection parameters for IRIS database
    """
    # IRIS connection parameters from kg-ticket-resolver setup
    params = {
        "host": "localhost",
        "port": 1975,
        "namespace": "USER",
        "username": "_SYSTEM",
        "password": "SYS",
    }

    # TODO: Add health check for IRIS container
    # For now, assume IRIS is running (manual prerequisite)

    return params


@pytest.fixture(scope="session")
def pgwire_server(iris_container):
    """
    Ensure PGWire server is running and ready to accept connections.

    Args:
        iris_container: IRIS connection parameters

    Returns:
        dict: PGWire server connection parameters
    """
    params = {"host": "localhost", "port": 5432, "user": "test_user", "dbname": "USER"}

    # TODO: Add PGWire server startup and health check
    # For now, assume PGWire is running (manual prerequisite)

    # Wait for port to be ready (simple check)
    import socket

    max_retries = 10
    for i in range(max_retries):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex((params["host"], params["port"]))
            sock.close()
            if result == 0:
                break
        except Exception:
            pass
        if i < max_retries - 1:
            time.sleep(1)

    return params


@pytest.fixture
def psql_command(pgwire_server):
    """
    Fixture for executing psql commands with stdin/stdout redirection.

    Pattern: psql_command(sql, stdin_file=None, stdout_file=None) → subprocess.CompletedProcess

    Args:
        pgwire_server: PGWire connection parameters

    Returns:
        callable: Function to execute psql commands

    Example:
        def test_copy_from_stdin(psql_command):
            result = psql_command(
                "COPY Patients FROM STDIN WITH (FORMAT CSV, HEADER)",
                stdin_file="examples/superset-iris-healthcare/data/patients-data.csv"
            )
            assert result.returncode == 0
            assert "COPY 250" in result.stdout
    """

    def _execute_psql(sql, stdin_file=None, stdout_file=None, expect_success=True):
        """
        Execute a psql command with optional stdin/stdout redirection.

        Args:
            sql: SQL command to execute
            stdin_file: Path to file for stdin redirection (optional)
            stdout_file: Path to file for stdout redirection (optional)
            expect_success: Whether command is expected to succeed (default True)

        Returns:
            subprocess.CompletedProcess: Result of psql execution
        """
        # Build psql command
        cmd = [
            "psql",
            "-h",
            pgwire_server["host"],
            "-p",
            str(pgwire_server["port"]),
            "-U",
            pgwire_server["user"],
            "-d",
            pgwire_server["dbname"],
            "-c",
            sql,
        ]

        # Handle stdin redirection
        stdin_data = None
        if stdin_file:
            with open(stdin_file, "rb") as f:
                stdin_data = f.read()

        # Execute command
        try:
            result = subprocess.run(
                cmd,
                input=stdin_data,
                capture_output=True,
                text=False if stdin_file else True,
                timeout=30,
            )

            # Handle stdout redirection
            if stdout_file and result.returncode == 0:
                with open(stdout_file, "wb" if isinstance(result.stdout, bytes) else "w") as f:
                    f.write(result.stdout)

            # Convert bytes to string for easier testing
            if isinstance(result.stdout, bytes):
                result.stdout = result.stdout.decode("utf-8", errors="replace")
            if isinstance(result.stderr, bytes):
                result.stderr = result.stderr.decode("utf-8", errors="replace")

            return result

        except subprocess.TimeoutExpired:
            pytest.fail(f"psql command timed out after 30 seconds: {sql[:100]}")
        except FileNotFoundError:
            pytest.skip("psql command not found - ensure PostgreSQL client is installed")
        except Exception as e:
            pytest.fail(f"psql command failed with exception: {e}")

    return _execute_psql


@pytest.fixture
def test_data_dir():
    """
    Get path to test data directory.

    Returns:
        Path: Path to examples/superset-iris-healthcare/data/
    """
    repo_root = Path(__file__).parent.parent.parent
    return repo_root / "examples" / "superset-iris-healthcare" / "data"


@pytest.fixture
def patients_csv_file(test_data_dir):
    """
    Get path to patients CSV test data.

    Returns:
        Path: Path to patients-data.csv file
    """
    csv_file = test_data_dir / "patients-data.csv"
    if not csv_file.exists():
        pytest.skip(f"Test data file not found: {csv_file}")
    return csv_file


@pytest.fixture(autouse=True)
def cleanup_test_tables(psql_command):
    """
    Clean up test tables before and after each test.

    Ensures tests start with a clean slate and don't leave artifacts.
    """
    # Cleanup before test
    _cleanup(psql_command)

    yield

    # Cleanup after test
    _cleanup(psql_command)


def _cleanup(psql_command):
    """Helper to drop test tables."""
    # Drop Patients table if exists (ignore errors)
    try:
        psql_command("DROP TABLE IF EXISTS Patients", expect_success=False)
    except Exception:
        pass  # Ignore cleanup errors

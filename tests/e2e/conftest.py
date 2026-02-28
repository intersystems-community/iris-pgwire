"""
E2E Test Infrastructure for P6 COPY Protocol

Provides pytest fixtures for executing psql commands with stdin/stdout redirection
against a running IRIS+PGWire server.

Constitutional Requirements:
- Test-First Development (Principle II): Real PostgreSQL clients for E2E testing
- No Mocks: Tests against actual IRIS database and PGWire protocol
"""

import os
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def psql_command(pgwire_connection_params, pgwire_server):
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
            pgwire_connection_params["host"],
            "-p",
            str(pgwire_connection_params["port"]),
            "-U",
            pgwire_connection_params["user"],
            "-d",
            pgwire_connection_params["dbname"],
            "-c",
            sql,
        ]

        # Handle stdin redirection
        stdin_data = None
        if stdin_file:
            with open(stdin_file, "rb") as f:
                stdin_data = f.read()

        # Execute command
        env = None
        if pgwire_connection_params.get("password"):
            env = os.environ.copy()
            env["PGPASSWORD"] = str(pgwire_connection_params["password"])

        try:
            result = subprocess.run(
                cmd,
                input=stdin_data,
                capture_output=True,
                text=False if stdin_file else True,
                timeout=30,
                env=env,
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


@pytest.fixture
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
    """Helper to drop test tables in FK-safe order."""
    # Drop child tables before parent tables to avoid FK constraint errors
    for table in ["LabResults", "Patients"]:
        try:
            psql_command(f"DROP TABLE IF EXISTS {table}", expect_success=False)
        except Exception:
            pass  # Ignore cleanup errors

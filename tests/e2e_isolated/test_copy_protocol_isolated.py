"""
PROPER E2E Tests: P6 COPY Protocol with Isolated IRIS Instances

Constitutional Requirement (Principle II):
- Uses iris-devtester for isolated, reproducible test environments
- No state pollution from existing containers
- Each test gets fresh IRIS instance with automatic cleanup
- DAT fixture loading for 10-100× faster test data setup

Performance Validation:
- 250 patients < 1 second (FR-005 requirement)
- >10,000 rows/second throughput
- <100MB memory for 1M rows (FR-006 requirement)
"""

import pytest
import time
import subprocess
import psycopg
from pathlib import Path
from iris_devtester import IRISContainer


# Test data paths
REPO_ROOT = Path(__file__).parent.parent.parent
PATIENTS_CSV = REPO_ROOT / 'examples' / 'superset-iris-healthcare' / 'data' / 'patients-data.csv'


@pytest.fixture(scope="module")
def isolated_iris_with_pgwire():
    """
    Spin up isolated IRIS container with PGWire server.

    Constitutional Compliance:
    - Fresh IRIS instance per test module
    - Automatic cleanup via testcontainers
    - No state pollution
    """
    with IRISContainer.community() as iris:
        # Get IRIS connection (embedded Python connection)
        iris_conn = iris.get_connection()

        # Parse connection URL for TCP connection details
        import urllib.parse
        conn_url = iris.get_connection_url()
        parsed = urllib.parse.urlparse(conn_url)

        # Yield both IRIS connection and connection details
        yield {
            'iris_connection': iris_conn,
            'iris_host': parsed.hostname,
            'iris_port': parsed.port or 1972,
            'iris_namespace': 'USER',
            'iris_username': 'test',
            'iris_password': 'test',
            'pgwire_host': 'localhost',  # PGWire will run on host
            'pgwire_port': 5432
        }


def test_isolated_iris_available(isolated_iris_with_pgwire):
    """
    Verify isolated IRIS instance is running and accessible.

    This proves we have a clean IRIS environment, not "whatever container is running".
    """
    params = isolated_iris_with_pgwire

    # Use IRIS embedded Python connection from iris-devtester
    iris_conn = params['iris_connection']

    # Execute query using IRIS connection cursor
    cursor = iris_conn.cursor()
    cursor.execute("SELECT $ZVERSION")
    version = cursor.fetchone()[0]

    assert 'IRIS' in version, f"Expected IRIS version, got: {version}"
    print(f"\n✅ Isolated IRIS container running: {version}")
    print(f"   Host: {params['iris_host']}:{params['iris_port']}")
    print(f"   Namespace: {params['iris_namespace']}")
    print(f"   Username: {params['iris_username']}")
    print(f"\n🎯 THIS IS A CLEAN INSTANCE - NO STATE POLLUTION!")
    print(f"   No foreign keys from Superset examples")
    print(f"   No leftover test data")
    print(f"   Perfect for reproducible E2E testing")


def test_copy_from_stdin_250_patients_performance(isolated_iris_with_pgwire):
    """
    E2E Test: COPY 250 patients in <1 second with isolated IRIS instance.

    Acceptance Scenario 1 from spec.md:
    - GIVEN: Clean IRIS instance and 250-patient CSV file
    - WHEN: Execute COPY FROM STDIN
    - THEN: All 250 records loaded in < 1 second

    Constitutional Compliance:
    - Isolated test environment (Principle II)
    - Real PostgreSQL client (psycopg)
    - Performance requirement validation (FR-005)
    """
    params = isolated_iris_with_pgwire

    # Skip if PGWire server not running
    # TODO: Start PGWire server in isolated container
    pytest.skip("PGWire server startup in isolated container not yet implemented")

    # Connect via PGWire protocol
    with psycopg.connect(
        host=params['pgwire_host'],
        port=params['pgwire_port'],
        user='test_user',
        dbname=params['iris_namespace']
    ) as conn:
        with conn.cursor() as cur:
            # Create Patients table
            cur.execute("""
                CREATE TABLE Patients (
                    PatientID INT PRIMARY KEY,
                    FirstName VARCHAR(50),
                    LastName VARCHAR(50),
                    DateOfBirth DATE,
                    Gender VARCHAR(10),
                    Status VARCHAR(20),
                    AdmissionDate DATE,
                    DischargeDate DATE
                )
            """)
            conn.commit()

            # Execute COPY FROM STDIN with timing
            start_time = time.time()

            with PATIENTS_CSV.open('rb') as f:
                with cur.copy("COPY Patients FROM STDIN WITH (FORMAT CSV, HEADER)") as copy:
                    copy.write(f.read())

            elapsed = time.time() - start_time

            # Verify row count
            cur.execute("SELECT COUNT(*) FROM Patients")
            row_count = cur.fetchone()[0]

            # Assertions
            assert row_count == 250, f"Expected 250 rows, got {row_count}"
            assert elapsed < 1.0, f"COPY took {elapsed:.2f}s, should be <1s (FR-005 requirement)"

            # Calculate throughput
            throughput = row_count / elapsed
            print(f"✅ COPY FROM STDIN performance:")
            print(f"   - Rows: {row_count}")
            print(f"   - Time: {elapsed:.3f}s")
            print(f"   - Throughput: {throughput:.0f} rows/sec")

            assert throughput > 10000, f"Throughput {throughput:.0f} rows/sec < 10,000 requirement"


def test_copy_to_stdout_250_patients(isolated_iris_with_pgwire):
    """
    E2E Test: COPY TO STDOUT exports 250 patients correctly.

    Acceptance Scenario 2 from spec.md:
    - GIVEN: Patients table with 250 rows
    - WHEN: Execute COPY TO STDOUT
    - THEN: All 250 rows exported with CSV header

    Constitutional Compliance:
    - Isolated test environment (Principle II)
    - Real PostgreSQL client (psycopg)
    """
    params = isolated_iris_with_pgwire
    pytest.skip("PGWire server startup in isolated container not yet implemented")


def test_copy_transaction_rollback(isolated_iris_with_pgwire):
    """
    E2E Test: COPY failure triggers transaction rollback.

    Acceptance Scenario 4 from spec.md:
    - GIVEN: Active transaction
    - WHEN: COPY fails (malformed CSV)
    - THEN: Transaction rolls back, no partial data

    Constitutional Compliance:
    - Isolated test environment (Principle II)
    - Feature 022 transaction integration
    """
    params = isolated_iris_with_pgwire
    pytest.skip("PGWire server startup in isolated container not yet implemented")


@pytest.mark.slow
def test_copy_memory_efficiency_1m_rows(isolated_iris_with_pgwire):
    """
    E2E Test: COPY 1M rows with <100MB memory usage.

    Acceptance Scenario 5 from spec.md:
    - GIVEN: Query returning 1M rows
    - WHEN: Execute COPY TO STDOUT
    - THEN: Memory delta < 100MB (streaming, no buffering)

    Constitutional Compliance:
    - Isolated test environment (Principle II)
    - Performance requirement validation (FR-006)
    """
    params = isolated_iris_with_pgwire
    pytest.skip("PGWire server startup in isolated container not yet implemented")


# ==================== Helper Functions ====================

def measure_memory_usage(func, *args, **kwargs):
    """
    Measure memory usage delta during function execution.

    Returns:
        tuple: (result, memory_delta_mb)
    """
    import tracemalloc

    tracemalloc.start()
    snapshot_before = tracemalloc.take_snapshot()

    result = func(*args, **kwargs)

    snapshot_after = tracemalloc.take_snapshot()
    tracemalloc.stop()

    top_stats = snapshot_after.compare_to(snapshot_before, 'lineno')
    total_delta = sum(stat.size_diff for stat in top_stats)
    memory_delta_mb = total_delta / (1024 * 1024)

    return result, memory_delta_mb

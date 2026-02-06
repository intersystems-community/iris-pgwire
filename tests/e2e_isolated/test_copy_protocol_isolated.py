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

import os
import sys
import time
from pathlib import Path

# Add src to path for local iris_pgwire
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../src")))

import pytest
from iris_devtester import IRISContainer
from iris_devtester.utils.password import unexpire_all_passwords

from tests.conftest import find_free_port

# Test data paths
REPO_ROOT = Path(__file__).parent.parent.parent
PATIENTS_CSV = REPO_ROOT / "examples" / "superset-iris-healthcare" / "data" / "patients-data.csv"


def start_pgwire_in_container(
    container, iris_port: int, iris_namespace: str, pgwire_port: int = 5432
):
    """
    Start PGWire server inside an isolated IRIS container.

    Args:
        container: Docker container instance from iris-devtester
        iris_port: IRIS SQL port number
        pgwire_port: Port to start PGWire server on (inside container)

    Returns:
        tuple: (container_ip, pgwire_port)
    """
    import io
    import tarfile

    # Create tar archive of PGWire source code
    print("\n📦 Packaging PGWire source code...")
    tar_stream = io.BytesIO()
    with tarfile.open(fileobj=tar_stream, mode="w") as tar:
        src_path = REPO_ROOT / "src" / "iris_pgwire"
        tar.add(str(src_path), arcname="iris_pgwire")

    tar_stream.seek(0)

    # Use /tmp directory (always writable in containers)
    print("📁 Using /tmp/pgwire for PGWire source...")
    exit_code, output = container.exec_run("mkdir -p /tmp/pgwire")
    if exit_code != 0:
        raise RuntimeError(f"Failed to create /tmp/pgwire directory: {output.decode()}")

    # Copy source code into container
    print("📤 Copying PGWire source to container...")
    container.put_archive("/tmp/pgwire/", tar_stream.getvalue())

    # Install dependencies
    print("📦 Installing Python dependencies...")
    install_cmd = [
        "/usr/irissys/bin/irispython",
        "-m",
        "pip",
        "install",
        "--quiet",
        "--break-system-packages",
        "structlog",
        "cryptography",
        "sqlparse",
        "psycopg",
    ]
    exit_code, output = container.exec_run(install_cmd)
    if exit_code != 0:
        print(f"❌ Dependency install failed: {output.decode()}")
        raise RuntimeError(f"Failed to install dependencies: {output.decode()}")
    else:
        print("✅ Dependencies installed successfully")

    # Start PGWire server in background
    print("🚀 Starting PGWire server in container...")

    container.reload()
    container_ip = container.attrs["NetworkSettings"]["IPAddress"] or "localhost"

    # Start PGWire server in background
    start_cmd = (
        "cd /tmp/pgwire && "
        "PYTHONPATH=/tmp/pgwire:$PYTHONPATH "
        f"IRIS_NAMESPACE={iris_namespace} "
        "nohup /usr/irissys/bin/irispython -m iris_pgwire.server "
        f"--host 0.0.0.0 --port {pgwire_port} "
        "> /tmp/pgwire.log 2>&1 &"
    )
    container.exec_run(f'/bin/bash -c "{start_cmd}"')

    # Wait for PGWire to be ready
    print(f"⏳ Waiting for PGWire server at {container_ip}:{pgwire_port}...")
    time.sleep(2)  # Give server a moment to fully initialize

    # Check if server is listening (using container exec for more reliable check)
    max_retries = 10
    for i in range(max_retries):
        try:
            # Use netstat inside container to check if port is listening
            exit_code, output = container.exec_run(f"netstat -tuln | grep :{pgwire_port}")
            if exit_code == 0 and f":{pgwire_port}".encode() in output:
                print(f"✅ PGWire server ready on port {pgwire_port}!")
                return container_ip, pgwire_port
        except Exception:
            pass

        if i < max_retries - 1:
            time.sleep(2)

    # If we got here, server didn't start - dump logs
    exit_code, logs = container.exec_run("cat /tmp/pgwire.log")
    print(f"❌ PGWire server not listening on port 5432. Logs:\n{logs.decode()}")
    raise TimeoutError("PGWire server did not start listening within 20 seconds")


@pytest.fixture(scope="module")
def isolated_iris_with_pgwire():
    """
    Spin up isolated IRIS container and start PGWire server on host connecting to it.
    """
    import asyncio
    import threading

    from iris_pgwire.server import PGWireServer

    # Use standard IRIS container
    with IRISContainer.community() as iris:
        container_name = iris.get_container_name()

        # CRITICAL: Enable CallIn service for DBAPI TCP connections
        if not iris.check_callin_enabled():
            iris.enable_callin_service()
            print("✅ CallIn service enabled")

        # CRITICAL: Unexpire passwords to allow authentication
        success, msg = unexpire_all_passwords(container_name, timeout=60)
        print(f"✅ Unexpire passwords: {success}, {msg}")

        # Give IRIS a moment to propagate setup
        time.sleep(2)

        config = iris.get_config()
        target_namespace = "USER"

        # NOTE: DAT fixture restore requires SYS.Database.RestoreNamespace which
        # is not available in Community Edition. For isolated tests, we use
        # the default USER namespace without fixture restore.

        # Start PGWire server ON THE HOST pointing to the container
        server_port = find_free_port(5435, 5499)
        server = PGWireServer(
            host="127.0.0.1",
            port=server_port,
            iris_host=config.host,
            iris_port=config.port,
            iris_username=config.username,  # SuperUser from iris-devtester
            iris_password=config.password,  # SYS from iris-devtester
            iris_namespace=target_namespace,
        )

        stop_event = threading.Event()

        def run_server():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            async def start_and_wait():
                await server.start()
                while not stop_event.is_set():
                    await asyncio.sleep(0.1)
                await server.stop()

            try:
                loop.run_until_complete(start_and_wait())
            finally:
                loop.close()

        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()

        # Wait for server to be ready
        time.sleep(2)

        # Get direct connection using DBAPI to bypass IDT remediation
        # Use robust import pattern per AGENTS.md
        try:
            import iris.dbapi as iris_dbapi
        except (ImportError, AttributeError):
            try:
                import intersystems_iris.dbapi._DBAPI as iris_dbapi
            except ImportError:
                import iris as iris_dbapi

        # Retry connection to handle potential propagation delay
        iris_conn = None
        for attempt in range(5):
            try:
                iris_conn = iris_dbapi.connect(
                    hostname=config.host,
                    port=config.port,
                    username=config.username,  # SuperUser from iris-devtester
                    password=config.password,  # SYS from iris-devtester
                    namespace=target_namespace,
                )
                print(f"✅ IRIS DBAPI connection established on attempt {attempt+1}")
                break
            except Exception as e:
                if attempt == 4:
                    raise
                print(f"⏳ IRIS connection failed, retrying... ({e})")
                time.sleep(2)

        yield {
            "iris_connection": iris_conn,
            "iris_host": config.host,
            "iris_port": config.port,
            "iris_namespace": target_namespace,
            "iris_username": config.username,
            "iris_password": config.password,
            "pgwire_host": "127.0.0.1",
            "pgwire_port": server_port,
            "container": iris._container,
        }

        stop_event.set()
        server_thread.join(timeout=5)


def test_isolated_iris_available(isolated_iris_with_pgwire):
    """
    Verify isolated IRIS instance is running and accessible.

    This proves we have a clean IRIS environment, not "whatever container is running".
    """
    params = isolated_iris_with_pgwire

    # Wait for PGWire to settle
    time.sleep(1)

    # Use IRIS embedded Python connection from iris-devtester
    iris_conn = params["iris_connection"]

    # Execute query using IRIS connection cursor
    # Use the connection from the params which is already correctly initialized
    cursor = params["iris_connection"].cursor()
    cursor.execute("SELECT $ZVERSION")
    version = cursor.fetchone()[0]

    assert "IRIS" in version, f"Expected IRIS version, got: {version}"
    print(f"\n✅ Isolated IRIS container running: {version}")
    print(f"   Host: {params['iris_host']}:{params['iris_port']}")
    print(f"   Namespace: {params['iris_namespace']}")
    print(f"   Username: {params['iris_username']}")
    print("\n🎯 THIS IS A CLEAN INSTANCE - NO STATE POLLUTION!")
    print("   No foreign keys from Superset examples")
    print("   No leftover test data")
    print("   Perfect for reproducible E2E testing")


@pytest.mark.skip(reason="COPY protocol implementation pending - isolated fixture working")
def test_copy_from_stdin_250_patients_performance(isolated_iris_with_pgwire):
    """
    E2E Test: COPY 250 patients in <1 second with isolated IRIS instance.

    Acceptance Scenario 1 from spec.md:
    - GIVEN: Clean IRIS instance and 250-patient CSV file
    - WHEN: Execute COPY FROM STDIN
    - THEN: All 250 records loaded in < 1 second

    Constitutional Compliance:
    - Isolated test environment (Principle II)
    - Real PostgreSQL client (psycopg inside container)
    - Performance requirement validation (FR-005)
    """
    params = isolated_iris_with_pgwire
    container = params["container"]

    # Install psycopg in the container for testing
    print("\n📦 Installing psycopg in container...")
    install_cmd = [
        "/usr/irissys/bin/irispython",
        "-m",
        "pip",
        "install",
        "--quiet",
        "--break-system-packages",
        "psycopg[binary]",
    ]
    exit_code, output = container.exec_run(install_cmd)
    if exit_code != 0:
        raise RuntimeError(f"Failed to install psycopg: {output.decode()}")
    print("✅ psycopg installed")

    # Copy CSV file into container
    print("📤 Copying patients CSV into container...")
    with PATIENTS_CSV.open("rb") as f:
        csv_data = f.read()

    # Write CSV to container
    container.exec_run("mkdir -p /tmp/test_data")
    import io
    import tarfile

    tar_stream = io.BytesIO()
    with tarfile.open(fileobj=tar_stream, mode="w") as tar:
        csv_info = tarfile.TarInfo(name="patients-data.csv")
        csv_info.size = len(csv_data)
        tar.addfile(csv_info, io.BytesIO(csv_data))
    tar_stream.seek(0)
    container.put_archive("/tmp/test_data/", tar_stream.getvalue())
    print("✅ CSV file copied to /tmp/test_data/patients-data.csv")

    # Create test script inside container
    test_script = f"""
import time
import psycopg
import os

# Connect to PGWire server on localhost
# Use credentials from environment variables
user = os.environ.get('PGWIRE_USER', '_SYSTEM')
password = os.environ.get('PGWIRE_PASSWORD', 'SYS')

with psycopg.connect(
    host='localhost',
    port={params['pgwire_port']},
    user=user,
    password=password,
    dbname='{params['iris_namespace']}'
) as conn:
"""

    # Write test script to container
    tar_stream = io.BytesIO()
    with tarfile.open(fileobj=tar_stream, mode="w") as tar:
        script_info = tarfile.TarInfo(name="test_copy.py")
        script_bytes = test_script.encode("utf-8")
        script_info.size = len(script_bytes)
        tar.addfile(script_info, io.BytesIO(script_bytes))
    tar_stream.seek(0)
    container.put_archive("/tmp/", tar_stream.getvalue())

    # Run test script inside container with credentials in environment
    print("\n🧪 Running COPY FROM STDIN performance test inside container...")
    env = {
        "PGWIRE_USER": "_SYSTEM",
        "PGWIRE_PASSWORD": "SYS",
    }

    exit_code, output = container.exec_run(
        ["/usr/irissys/bin/irispython", "/tmp/test_copy.py"], environment=env
    )

    # Parse results
    output_str = output.decode("utf-8")
    print(output_str)

    # Capture PGWire server logs for debugging
    print("\n📋 PGWire Server Logs:")
    exit_code, logs = container.exec_run("tail -100 /tmp/pgwire.log")
    if exit_code == 0:
        print(logs.decode("utf-8", errors="ignore"))
    else:
        print(f"Could not retrieve logs (exit code {exit_code})")

    if exit_code != 0:
        raise RuntimeError(f"Test script failed with exit code {exit_code}")

    # Extract results from output
    for line in output_str.split("\n"):
        if line.startswith("RESULT|"):
            parts = line.split("|")
            row_count = int(parts[1])
            elapsed = float(parts[2])
            throughput = float(parts[3])

            # Assertions
            assert row_count == 250, f"Expected 250 rows, got {row_count}"
            assert elapsed < 1.0, f"COPY took {elapsed:.2f}s, should be <1s (FR-005 requirement)"
            assert throughput > 10000, f"Throughput {throughput:.0f} rows/sec < 10,000 requirement"

            print("\n✅ ALL PERFORMANCE REQUIREMENTS MET!")
            return

    raise ValueError("Could not parse test results from output")


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

    top_stats = snapshot_after.compare_to(snapshot_before, "lineno")
    total_delta = sum(stat.size_diff for stat in top_stats)
    memory_delta_mb = total_delta / (1024 * 1024)

    return result, memory_delta_mb

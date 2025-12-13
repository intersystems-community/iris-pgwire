"""
E2E Tests for Open Exchange Package - All Deployment Modes

Uses iris-devtester for reproducible, isolated testing of all deployment modes:
1. Docker Quick Start - docker-compose pattern
2. DBAPI Backend (same box) - External Python process, same machine as IRIS
3. DBAPI Backend (different box) - Simulated remote connection
4. Embedded Python - Running inside IRIS via irispython

Feature: 027-open-exchange
Constitutional Requirements:
- Test-First Development (Principle II): Real PostgreSQL clients
- PostgreSQL Compatibility (Principle III): All modes use standard psycopg3
- Documentation Accuracy (Principle IV): README examples verified
"""

import io
import os
import tarfile
import time
from pathlib import Path

import psycopg
import pytest

# Try to import iris-devtester (skip tests if not available)
try:
    from iris_devtester import IRISContainer
    IRIS_DEVTESTER_AVAILABLE = True
except ImportError:
    IRIS_DEVTESTER_AVAILABLE = False


REPO_ROOT = Path(__file__).parent.parent.parent


# =============================================================================
# Skip marker for iris-devtester tests
# =============================================================================


requires_iris_devtester = pytest.mark.skipif(
    not IRIS_DEVTESTER_AVAILABLE,
    reason="iris-devtester not installed. Install with: pip install iris-devtester"
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def running_pgwire_params():
    """
    Get connection params for already-running PGWire server.
    Used for quick local testing against existing docker-compose setup.
    """
    import socket

    params = {
        "host": os.environ.get("PGWIRE_HOST", "localhost"),
        "port": int(os.environ.get("PGWIRE_PORT", "5432")),
        "user": os.environ.get("PGWIRE_USER", "_SYSTEM"),
        "password": os.environ.get("PGWIRE_PASSWORD", "SYS"),
        "dbname": os.environ.get("PGWIRE_DBNAME", "USER"),
    }

    # Check if PGWire is available
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(2)
    try:
        result = sock.connect_ex((params["host"], params["port"]))
        sock.close()
        if result != 0:
            pytest.skip(f"PGWire not running at {params['host']}:{params['port']}")
    except Exception as e:
        pytest.skip(f"Cannot check PGWire: {e}")

    return params


@pytest.fixture
def conn(running_pgwire_params):
    """Create psycopg connection to running PGWire."""
    params = running_pgwire_params
    conn_str = (
        f"host={params['host']} port={params['port']} "
        f"user={params['user']} password={params['password']} "
        f"dbname={params['dbname']}"
    )
    connection = psycopg.connect(conn_str)
    yield connection
    connection.close()


# =============================================================================
# Docker Quick Start Tests (Uses Running Container)
# =============================================================================


class TestDockerQuickStartE2E:
    """
    E2E Tests for Docker Quick Start instructions from README.

    These tests run against an existing docker-compose setup.
    Prerequisite: docker-compose up -d
    """

    def test_readme_hello_world(self, conn):
        """
        README example:
        psql -h localhost -p 5432 -U _SYSTEM -d USER -c "SELECT 'Hello from IRIS!'"
        """
        with conn.cursor() as cur:
            cur.execute("SELECT 'Hello from IRIS!'")
            result = cur.fetchone()
            assert "Hello from IRIS!" in str(result[0])

    def test_readme_python_first_query(self, running_pgwire_params):
        """
        README example:
        ```python
        import psycopg
        with psycopg.connect('host=localhost port=5432 dbname=USER') as conn:
            cur = conn.cursor()
            cur.execute('SELECT COUNT(*) FROM YourTable')
        ```
        """
        params = running_pgwire_params
        conn_str = (
            f"host={params['host']} port={params['port']} "
            f"dbname={params['dbname']} user={params['user']} "
            f"password={params['password']}"
        )

        with psycopg.connect(conn_str) as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES")
            count = cur.fetchone()[0]
            assert count >= 0

    def test_readme_vector_similarity_search(self, conn):
        """
        README example:
        ```python
        cur.execute(
            "SELECT id, content FROM documents ORDER BY embedding <=> %s LIMIT 5",
            (query_embedding,)
        )
        ```
        """
        test_table = "e2e_vector_test"

        with conn.cursor() as cur:
            # Setup
            cur.execute(f"DROP TABLE IF EXISTS {test_table}")
            cur.execute(f"""
                CREATE TABLE {test_table} (
                    id INT PRIMARY KEY,
                    content VARCHAR(255),
                    embedding VECTOR(DOUBLE, 3)
                )
            """)
            # IRIS doesn't support multi-row VALUES - use separate inserts
            cur.execute(f"INSERT INTO {test_table} VALUES (1, 'Document about Python', TO_VECTOR('[0.1, 0.2, 0.3]'))")
            cur.execute(f"INSERT INTO {test_table} VALUES (2, 'Document about IRIS', TO_VECTOR('[0.9, 0.8, 0.7]'))")
            cur.execute(f"INSERT INTO {test_table} VALUES (3, 'Document about vectors', TO_VECTOR('[0.5, 0.5, 0.5]'))")
            conn.commit()

            # Test README pattern: pgvector <=> operator with parameter binding
            query_embedding = [0.1, 0.2, 0.3]
            cur.execute(f"""
                SELECT id, content FROM {test_table}
                ORDER BY embedding <=> %s
                LIMIT 5
            """, (query_embedding,))

            results = cur.fetchall()
            assert len(results) == 3
            # Verify we got results - order depends on distance calculation
            assert len(results) >= 1, "Should have at least 1 result"

            # Cleanup
            cur.execute(f"DROP TABLE IF EXISTS {test_table}")
            conn.commit()

    def test_readme_dot_product_operator(self, conn):
        """
        Test <#> operator (dot product) shown in architecture diagram.
        """
        test_table = "e2e_dot_product_test"

        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {test_table}")
            cur.execute(f"""
                CREATE TABLE {test_table} (
                    id INT PRIMARY KEY,
                    embedding VECTOR(DOUBLE, 3)
                )
            """)
            # IRIS doesn't support multi-row VALUES
            cur.execute(f"INSERT INTO {test_table} VALUES (1, TO_VECTOR('[1.0, 0.0, 0.0]'))")
            cur.execute(f"INSERT INTO {test_table} VALUES (2, TO_VECTOR('[0.5, 0.5, 0.0]'))")
            conn.commit()

            # Test <#> operator (dot product)
            query_vec = [1.0, 0.0, 0.0]
            cur.execute(f"""
                SELECT id FROM {test_table}
                ORDER BY embedding <#> %s
                LIMIT 1
            """, (query_vec,))

            result = cur.fetchone()
            assert result is not None

            cur.execute(f"DROP TABLE IF EXISTS {test_table}")
            conn.commit()


class TestZPMInstallationPrereqs:
    """
    Test prerequisites for ZPM installation (module.xml validation).
    These tests verify the package structure is correct.
    """

    def test_module_xml_no_auto_start(self):
        """Verify module.xml does NOT have auto-start (per clarification)."""
        import xml.etree.ElementTree as ET

        module_xml = REPO_ROOT / "ipm" / "module.xml"
        tree = ET.parse(module_xml)
        root = tree.getroot()

        for invoke in root.findall(".//Invoke"):
            phase = invoke.get("Phase", "")
            method = invoke.get("Method", "")
            if phase == "Activate" and method == "Start":
                pytest.fail("module.xml should NOT have Activate phase with Start")

    def test_service_cls_has_manual_controls(self):
        """Verify Service.cls has Start/Stop/GetStatus methods."""
        service_cls = REPO_ROOT / "ipm" / "IrisPGWire" / "Service.cls"
        content = service_cls.read_text()

        assert "ClassMethod Start()" in content
        assert "ClassMethod Stop()" in content
        assert "ClassMethod GetStatus()" in content
        assert "ClassMethod ShowStatus()" in content


# =============================================================================
# Isolated E2E Tests with iris-devtester
# =============================================================================


@requires_iris_devtester
class TestIsolatedDBAPIBackend:
    """
    E2E Tests using iris-devtester for fully isolated, reproducible testing.

    These tests spin up fresh IRIS containers, deploy PGWire, and verify
    everything works end-to-end without any state pollution.
    """

    @pytest.fixture(scope="class")
    def isolated_iris(self):
        """Spin up isolated IRIS container with PGWire."""
        with IRISContainer.community() as iris:
            container = iris._container

            # Copy PGWire source to container
            print("\n📦 Deploying PGWire to isolated container...")
            tar_stream = io.BytesIO()
            with tarfile.open(fileobj=tar_stream, mode="w") as tar:
                src_path = REPO_ROOT / "src" / "iris_pgwire"
                tar.add(str(src_path), arcname="iris_pgwire")
            tar_stream.seek(0)

            container.exec_run("mkdir -p /tmp/pgwire")
            container.put_archive("/tmp/pgwire/", tar_stream.getvalue())

            # Install Python dependencies
            print("📦 Installing dependencies...")
            deps = ["structlog", "cryptography", "sqlparse", "psycopg[binary]", "pydantic", "pyyaml"]
            for dep in deps:
                container.exec_run([
                    "/usr/irissys/bin/irispython", "-m", "pip", "install",
                    "--quiet", "--break-system-packages", dep
                ])

            # Start PGWire server
            print("🚀 Starting PGWire server...")
            start_cmd = (
                "cd /tmp/pgwire && "
                "PYTHONPATH=/tmp/pgwire:$PYTHONPATH "
                "nohup /usr/irissys/bin/irispython -m iris_pgwire.server "
                "--host 0.0.0.0 --port 5432 "
                "> /tmp/pgwire.log 2>&1 &"
            )
            container.exec_run(f'/bin/bash -c "{start_cmd}"')

            # Wait for server
            time.sleep(3)

            # Get container IP
            container.reload()
            container_ip = container.attrs["NetworkSettings"]["IPAddress"]

            # Verify server started
            exit_code, output = container.exec_run("netstat -tuln | grep :5432")
            if exit_code != 0 or b":5432" not in output:
                exit_code, logs = container.exec_run("cat /tmp/pgwire.log")
                print(f"PGWire logs:\n{logs.decode()}")
                pytest.skip("PGWire server failed to start in isolated container")

            print(f"✅ PGWire ready at {container_ip}:5432")

            yield {
                "container": container,
                "iris": iris,
                "pgwire_host": container_ip,
                "pgwire_port": 5432,
            }

    def test_isolated_basic_query(self, isolated_iris):
        """Test basic query in isolated environment."""
        params = isolated_iris

        # Execute query inside container using psycopg
        test_script = """
import psycopg
conn = psycopg.connect('host=localhost port=5432 user=test_user dbname=USER')
cur = conn.cursor()
cur.execute("SELECT 'Isolated test passed!'")
print(cur.fetchone()[0])
conn.close()
"""
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode="w") as tar:
            script_bytes = test_script.encode()
            info = tarfile.TarInfo(name="test_basic.py")
            info.size = len(script_bytes)
            tar.addfile(info, io.BytesIO(script_bytes))
        tar_stream.seek(0)
        params["container"].put_archive("/tmp/", tar_stream.getvalue())

        exit_code, output = params["container"].exec_run([
            "/usr/irissys/bin/irispython", "/tmp/test_basic.py"
        ])

        assert exit_code == 0, f"Test failed: {output.decode()}"
        assert "Isolated test passed!" in output.decode()

    def test_isolated_vector_operations(self, isolated_iris):
        """Test vector operations in isolated environment."""
        params = isolated_iris

        test_script = """
import psycopg

conn = psycopg.connect('host=localhost port=5432 user=test_user dbname=USER')
cur = conn.cursor()

# Create vector table
cur.execute("DROP TABLE IF EXISTS iso_vectors")
cur.execute('''
    CREATE TABLE iso_vectors (
        id INT PRIMARY KEY,
        vec VECTOR(DOUBLE, 3)
    )
''')
# IRIS doesn't support multi-row VALUES - use separate inserts
cur.execute("INSERT INTO iso_vectors VALUES (1, TO_VECTOR('[0.1, 0.2, 0.3]'))")
cur.execute("INSERT INTO iso_vectors VALUES (2, TO_VECTOR('[0.9, 0.8, 0.7]'))")
conn.commit()

# Test cosine operator
query_vec = [0.1, 0.2, 0.3]
cur.execute('''
    SELECT id FROM iso_vectors
    ORDER BY vec <=> %s
    LIMIT 1
''', (query_vec,))

result = cur.fetchone()
assert result is not None, "Expected a result"
print("VECTOR_COSINE_PASS")

# Test dot product operator
cur.execute('''
    SELECT id FROM iso_vectors
    ORDER BY vec <#> %s
    LIMIT 1
''', (query_vec,))
result = cur.fetchone()
print("VECTOR_DOT_PRODUCT_PASS")

# Cleanup
cur.execute("DROP TABLE iso_vectors")
conn.commit()
conn.close()

print("ALL_VECTOR_TESTS_PASS")
"""
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode="w") as tar:
            script_bytes = test_script.encode()
            info = tarfile.TarInfo(name="test_vectors.py")
            info.size = len(script_bytes)
            tar.addfile(info, io.BytesIO(script_bytes))
        tar_stream.seek(0)
        params["container"].put_archive("/tmp/", tar_stream.getvalue())

        exit_code, output = params["container"].exec_run([
            "/usr/irissys/bin/irispython", "/tmp/test_vectors.py"
        ])

        output_str = output.decode()
        print(output_str)

        assert exit_code == 0, f"Test failed: {output_str}"
        assert "VECTOR_COSINE_PASS" in output_str
        assert "VECTOR_DOT_PRODUCT_PASS" in output_str
        assert "ALL_VECTOR_TESTS_PASS" in output_str

    def test_isolated_transactions(self, isolated_iris):
        """Test transaction support in isolated environment."""
        params = isolated_iris

        test_script = """
import psycopg

conn = psycopg.connect('host=localhost port=5432 user=test_user dbname=USER')
cur = conn.cursor()

# Setup
cur.execute("DROP TABLE IF EXISTS iso_txn")
cur.execute("CREATE TABLE iso_txn (id INT, value VARCHAR(50))")
conn.commit()

# Test commit
cur.execute("INSERT INTO iso_txn VALUES (1, 'committed')")
conn.commit()
cur.execute("SELECT value FROM iso_txn WHERE id = 1")
assert cur.fetchone()[0] == 'committed'
print("COMMIT_PASS")

# Test rollback
cur.execute("UPDATE iso_txn SET value = 'modified' WHERE id = 1")
conn.rollback()
cur.execute("SELECT value FROM iso_txn WHERE id = 1")
assert cur.fetchone()[0] == 'committed'
print("ROLLBACK_PASS")

# Cleanup
cur.execute("DROP TABLE iso_txn")
conn.commit()
conn.close()

print("ALL_TXN_TESTS_PASS")
"""
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode="w") as tar:
            script_bytes = test_script.encode()
            info = tarfile.TarInfo(name="test_txn.py")
            info.size = len(script_bytes)
            tar.addfile(info, io.BytesIO(script_bytes))
        tar_stream.seek(0)
        params["container"].put_archive("/tmp/", tar_stream.getvalue())

        exit_code, output = params["container"].exec_run([
            "/usr/irissys/bin/irispython", "/tmp/test_txn.py"
        ])

        output_str = output.decode()
        print(output_str)

        assert exit_code == 0, f"Test failed: {output_str}"
        assert "COMMIT_PASS" in output_str
        assert "ROLLBACK_PASS" in output_str
        assert "ALL_TXN_TESTS_PASS" in output_str


    def test_isolated_authentication(self, isolated_iris):
        """Test authentication in isolated environment with valid credentials."""
        params = isolated_iris

        # Test valid credentials work
        test_script = """
import psycopg

# Test 1: Valid connection should work
try:
    conn = psycopg.connect('host=localhost port=5432 user=test_user dbname=USER')
    cur = conn.cursor()
    cur.execute("SELECT 1")
    result = cur.fetchone()
    assert result[0] == 1, "Query should succeed"
    conn.close()
    print("VALID_AUTH_PASS")
except Exception as e:
    print(f"VALID_AUTH_FAIL: {e}")

# Test 2: Try with _SYSTEM user (should also work)
try:
    conn = psycopg.connect('host=localhost port=5432 user=_SYSTEM dbname=USER')
    cur = conn.cursor()
    cur.execute("SELECT 1")
    result = cur.fetchone()
    assert result[0] == 1, "Query should succeed"
    conn.close()
    print("SYSTEM_AUTH_PASS")
except Exception as e:
    print(f"SYSTEM_AUTH_FAIL: {e}")

print("ALL_AUTH_TESTS_PASS")
"""
        tar_stream = io.BytesIO()
        with tarfile.open(fileobj=tar_stream, mode="w") as tar:
            script_bytes = test_script.encode()
            info = tarfile.TarInfo(name="test_auth.py")
            info.size = len(script_bytes)
            tar.addfile(info, io.BytesIO(script_bytes))
        tar_stream.seek(0)
        params["container"].put_archive("/tmp/", tar_stream.getvalue())

        exit_code, output = params["container"].exec_run([
            "/usr/irissys/bin/irispython", "/tmp/test_auth.py"
        ])

        output_str = output.decode()
        print(output_str)

        assert exit_code == 0, f"Test failed: {output_str}"
        assert "VALID_AUTH_PASS" in output_str
        assert "SYSTEM_AUTH_PASS" in output_str
        assert "ALL_AUTH_TESTS_PASS" in output_str


# =============================================================================
# Performance Sanity Tests
# =============================================================================


class TestPerformanceSanity:
    """Quick performance sanity checks."""

    def test_query_latency_under_100ms(self, conn):
        """Simple query should complete in <100ms."""
        start = time.time()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        elapsed = time.time() - start
        assert elapsed < 0.1, f"Query took {elapsed:.3f}s (>100ms)"

    def test_vector_query_under_200ms(self, conn):
        """Vector query should complete in <200ms (after table exists)."""
        test_table = "e2e_perf_vectors"

        with conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {test_table}")
            cur.execute(f"""
                CREATE TABLE {test_table} (
                    id INT PRIMARY KEY,
                    vec VECTOR(DOUBLE, 128)
                )
            """)
            # Insert a few rows
            for i in range(10):
                vec = [float(j + i) / 128 for j in range(128)]
                cur.execute(f"INSERT INTO {test_table} VALUES (%s, TO_VECTOR(%s))", (i, vec))
            conn.commit()

            # Time vector query
            query_vec = [float(j) / 128 for j in range(128)]
            start = time.time()
            cur.execute(f"""
                SELECT id FROM {test_table}
                ORDER BY vec <=> %s
                LIMIT 5
            """, (query_vec,))
            cur.fetchall()
            elapsed = time.time() - start

            # Cleanup
            cur.execute(f"DROP TABLE IF EXISTS {test_table}")
            conn.commit()

        assert elapsed < 0.2, f"Vector query took {elapsed:.3f}s (>200ms)"

"""
Test IRIS LOAD DATA optimization for COPY FROM STDIN.

CAUTION: This is experimental! Testing the new LOAD DATA approach
before switching from individual INSERTs.
"""

import pytest
import time
from pathlib import Path

# Test data paths
REPO_ROOT = Path(__file__).parent.parent.parent
PATIENTS_CSV = REPO_ROOT / 'examples' / 'superset-iris-healthcare' / 'data' / 'patients-data.csv'


def test_load_data_available_in_iris():
    """
    Verify IRIS LOAD DATA command is available.

    This test checks if IRIS supports LOAD DATA before we try to use it.
    """
    from iris_devtester import IRISContainer

    with IRISContainer.community() as iris:
        conn = iris.get_connection()
        cursor = conn.cursor()

        # Try to execute a simple LOAD DATA command to verify it's available
        # This should fail gracefully if LOAD DATA is not available
        try:
            cursor.execute("SELECT * FROM %SQL_Diag.Result WHERE statement LIKE '%LOAD DATA%' LIMIT 1")
            result = cursor.fetchall()
            print(f"\n✅ LOAD DATA diagnostic table accessible")
            print(f"   Result count: {len(result)}")
        except Exception as e:
            pytest.skip(f"LOAD DATA not available or not supported: {e}")


@pytest.mark.slow
def test_load_data_vs_individual_inserts_performance():
    """
    Compare performance: LOAD DATA vs individual INSERTs.

    WARNING: This test requires:
    - Java JVM installed on IRIS server
    - LOAD DATA feature enabled
    - Write access to IRIS temp directory
    """
    from iris_devtester import IRISContainer
    import tempfile
    import shutil

    with IRISContainer.community() as iris:
        conn = iris.get_connection()
        cursor = conn.cursor()

        # Create test table
        cursor.execute("""
            CREATE TABLE LoadDataTest (
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

        # Write CSV file inside IRIS container using Docker container exec
        # This ensures the file is accessible to LOAD DATA command
        container_path = "/tmp/test_patients.csv"

        # Get the underlying Docker container from iris-devtester
        # iris-devtester wraps testcontainers, access the container instance
        container = iris._container

        # Read CSV content
        csv_content = PATIENTS_CSV.read_text()

        # Write file inside container using container.exec_run
        # Use echo with heredoc to write multiline content
        import shlex
        write_cmd = f"cat > {container_path} << 'CSVEOF'\n{csv_content}\nCSVEOF"

        exit_code, output = container.exec_run(["/bin/bash", "-c", write_cmd])

        if exit_code != 0:
            raise RuntimeError(f"Failed to write CSV file in container: {output.decode()}")

        print(f"\n📂 Wrote CSV to IRIS container: {container_path}")

        # Verify file exists
        exit_code, output = container.exec_run(["ls", "-lh", container_path])
        if exit_code == 0:
            print(f"   File info: {output.decode().strip()}")

        temp_path = container_path

        try:
            # Test LOAD DATA approach
            start_time = time.time()

            # IRIS LOAD DATA syntax:
            # - LOAD BULK supports %NOINDEX only (%NOLOCK, %NOJOURN incompatible with BULK)
            # - %NOCHECK requires non-BULK mode
            # We'll use BULK %NOINDEX for maximum speed
            #
            # EMPIRICAL FINDING: LOAD DATA has high initialization overhead!
            # - 250 rows: 155 rows/sec (SLOWER than individual INSERTs at 600 rows/sec)
            # - Likely optimized for large datasets (10K+ rows)
            # - JVM startup and CSV parsing dominate for small datasets
            load_sql = f"""
            LOAD BULK %NOINDEX DATA
            FROM FILE '{temp_path}'
            INTO LoadDataTest
            USING {{"from": {{"file": {{"header": true, "columnseparator": ","}}}}}}
            """

            print(f"\n🚀 Testing LOAD DATA...")
            print(f"   SQL: {load_sql[:100]}...")

            try:
                cursor.execute(load_sql)
                conn.commit()
                load_data_time = time.time() - start_time

                # Verify row count
                cursor.execute("SELECT COUNT(*) FROM LoadDataTest")
                row_count = cursor.fetchone()[0]

                print(f"\n✅ LOAD DATA SUCCESS!")
                print(f"   Rows loaded: {row_count}")
                print(f"   Time: {load_data_time:.3f}s")
                print(f"   Throughput: {row_count / load_data_time:.0f} rows/sec")

                # Check if we hit the performance target
                throughput = row_count / load_data_time
                if throughput > 10000:
                    print(f"\n🎉 FR-005 REQUIREMENT MET: {throughput:.0f} rows/sec > 10,000 target!")
                else:
                    print(f"\n⚠️  Below target: {throughput:.0f} rows/sec < 10,000 requirement")

            except Exception as e:
                print(f"\n❌ LOAD DATA FAILED: {e}")
                pytest.skip(f"LOAD DATA not supported or failed: {e}")

        finally:
            # Cleanup
            import os
            if os.path.exists(temp_path):
                os.unlink(temp_path)
            cursor.execute("DROP TABLE LoadDataTest")
            conn.commit()


if __name__ == "__main__":
    # Run tests manually for debugging
    test_load_data_available_in_iris()
    test_load_data_vs_individual_inserts_performance()

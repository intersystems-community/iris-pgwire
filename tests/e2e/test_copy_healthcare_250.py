"""
E2E Test: COPY FROM STDIN - 250 Patient Records

Acceptance Scenario 1 from spec.md:
GIVEN a CSV file with 250 patient records
WHEN the user executes `COPY Patients FROM STDIN WITH (FORMAT CSV, HEADER)`
THEN all 250 records are loaded into IRIS in < 1 second with no errors

Constitutional Requirement (Principle II): Test-First Development
- This test MUST fail initially (no COPY protocol implementation exists)
- Implementation comes AFTER this test is written

Performance Requirement (FR-005):
- >10,000 rows/second throughput
- 250 patients < 1 second (vs 2.5 seconds baseline with INSERT statements)
"""

import time

import pytest


@pytest.mark.e2e
def test_copy_250_patients_from_stdin_performance(psql_command, patients_csv_file):
    """
    Test COPY FROM STDIN performance with 250 patient records.

    Expected: FAIL - no COPY protocol implementation exists yet
    """
    # Create Patients table first
    create_table_sql = """
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
    """
    setup_result = psql_command(create_table_sql)
    assert setup_result.returncode == 0, f"Table creation failed: {setup_result.stderr}"

    # Execute COPY FROM STDIN with timing
    start_time = time.time()

    result = psql_command(
        "COPY Patients FROM STDIN WITH (FORMAT CSV, HEADER)", stdin_file=str(patients_csv_file)
    )

    elapsed = time.time() - start_time

    # Assertions
    assert result.returncode == 0, f"COPY FROM STDIN failed: {result.stderr}"
    assert "COPY 250" in result.stdout, f"Expected 'COPY 250' in output, got: {result.stdout}"
    assert (
        elapsed < 1.0
    ), f"COPY took {elapsed:.2f}s, should be <1s (FR-005 performance requirement)"

    # Verify all 250 rows were inserted
    count_result = psql_command("SELECT COUNT(*) FROM Patients")
    assert count_result.returncode == 0
    assert "250" in count_result.stdout, "Expected 250 rows in Patients table"


@pytest.mark.e2e
def test_copy_from_stdin_with_header_option(psql_command, patients_csv_file):
    """
    Test COPY FROM STDIN correctly skips CSV header row.

    Expected: FAIL - no COPY protocol implementation exists yet
    """
    # Create Patients table
    create_table_sql = """
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
    """
    setup_result = psql_command(create_table_sql)
    assert setup_result.returncode == 0

    # COPY with HEADER option (should skip first row)
    result = psql_command(
        "COPY Patients FROM STDIN WITH (FORMAT CSV, HEADER)", stdin_file=str(patients_csv_file)
    )

    assert result.returncode == 0, f"COPY failed: {result.stderr}"
    assert "COPY 250" in result.stdout

    # Verify first row data (PatientID=1 should exist, not header text)
    check_result = psql_command("SELECT FirstName FROM Patients WHERE PatientID = 1")
    assert check_result.returncode == 0
    assert (
        "John" in check_result.stdout
    ), "First patient should be John, not header text 'FirstName'"


@pytest.mark.e2e
def test_copy_from_stdin_without_header(psql_command, test_data_dir):
    """
    Test COPY FROM STDIN without HEADER option (all rows are data).

    Expected: FAIL - no COPY protocol implementation exists yet
    """
    # Create simple test CSV without header
    import os
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("1,Alice,Test,1990-01-01,F,Active,2024-01-01,\n")
        f.write("2,Bob,Test,1985-05-15,M,Discharged,2024-01-05,2024-01-10\n")
        csv_file = f.name

    try:
        # Create Patients table
        create_table_sql = """
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
        """
        setup_result = psql_command(create_table_sql)
        assert setup_result.returncode == 0

        # COPY without HEADER (all rows are data)
        result = psql_command("COPY Patients FROM STDIN WITH (FORMAT CSV)", stdin_file=csv_file)

        assert result.returncode == 0, f"COPY failed: {result.stderr}"
        assert "COPY 2" in result.stdout, "Expected 2 rows copied"

        # Verify both rows inserted
        count_result = psql_command("SELECT COUNT(*) FROM Patients")
        assert "2" in count_result.stdout

    finally:
        # Cleanup temp file
        os.unlink(csv_file)


@pytest.mark.e2e
def test_copy_from_stdin_column_list(psql_command):
    """
    Test COPY FROM STDIN with explicit column list.

    Expected: FAIL - no COPY protocol implementation exists yet
    """
    import os
    import tempfile

    # Create CSV with only 3 columns
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("1,Alice,Test\n")
        f.write("2,Bob,Sample\n")
        csv_file = f.name

    try:
        # Create Patients table
        create_table_sql = """
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
        """
        setup_result = psql_command(create_table_sql)
        assert setup_result.returncode == 0

        # COPY with column list (only 3 columns)
        result = psql_command(
            "COPY Patients (PatientID, FirstName, LastName) FROM STDIN WITH (FORMAT CSV)",
            stdin_file=csv_file,
        )

        assert result.returncode == 0, f"COPY failed: {result.stderr}"
        assert "COPY 2" in result.stdout

        # Verify rows inserted with NULL for unspecified columns
        check_result = psql_command(
            "SELECT PatientID, FirstName, LastName, Gender FROM Patients WHERE PatientID = 1"
        )
        assert "Alice" in check_result.stdout
        assert "Test" in check_result.stdout

    finally:
        os.unlink(csv_file)

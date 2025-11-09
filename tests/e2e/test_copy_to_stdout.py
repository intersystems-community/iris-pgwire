"""
E2E Test: COPY TO STDOUT - 250 Patient Export

Acceptance Scenario 2 from spec.md:
GIVEN a Patients table with 250 records in IRIS
WHEN the user executes `COPY Patients TO STDOUT WITH (FORMAT CSV, HEADER)`
THEN all 250 records are exported to CSV format and streamed to the client

Constitutional Requirement (Principle II): Test-First Development
- This test MUST fail initially (no COPY TO STDOUT implementation exists)

Performance Requirement (FR-006):
- Server streams results without exceeding 100MB memory for large datasets
"""

import pytest
import tempfile
import os


@pytest.mark.e2e
def test_copy_250_patients_to_stdout(psql_command, patients_csv_file):
    """
    Test COPY TO STDOUT exports 250 patient records to CSV.

    Expected: FAIL - no COPY TO STDOUT implementation exists yet
    """
    # Setup: Create and populate Patients table
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

    # Load data via COPY FROM STDIN first (prerequisite)
    load_result = psql_command(
        "COPY Patients FROM STDIN WITH (FORMAT CSV, HEADER)",
        stdin_file=str(patients_csv_file)
    )
    # Note: This will also fail if T004 implementation isn't done
    # For now, we expect both to fail

    # Export via COPY TO STDOUT
    export_file = tempfile.mktemp(suffix='.csv')
    try:
        result = psql_command(
            "COPY Patients TO STDOUT WITH (FORMAT CSV, HEADER)",
            stdout_file=export_file
        )

        assert result.returncode == 0, f"COPY TO STDOUT failed: {result.stderr}"

        # Verify exported CSV structure
        with open(export_file, 'r') as f:
            lines = f.readlines()
            assert len(lines) == 251, f"Expected 251 lines (1 header + 250 data), got {len(lines)}"
            assert "PatientID,FirstName,LastName" in lines[0], "Header row missing expected columns"
            assert "1,John,Smith" in lines[1], "First data row should be patient 1 (John Smith)"

    finally:
        if os.path.exists(export_file):
            os.unlink(export_file)


@pytest.mark.e2e
def test_copy_to_stdout_with_query(psql_command, patients_csv_file):
    """
    Test COPY (SELECT ...) TO STDOUT for filtered export.

    Expected: FAIL - no COPY TO STDOUT implementation exists yet
    """
    # Setup: Create and populate Patients table
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

    # Load data
    load_result = psql_command(
        "COPY Patients FROM STDIN WITH (FORMAT CSV, HEADER)",
        stdin_file=str(patients_csv_file)
    )

    # Export only Active patients via query
    export_file = tempfile.mktemp(suffix='.csv')
    try:
        result = psql_command(
            "COPY (SELECT PatientID, FirstName, LastName FROM Patients WHERE Status = 'Active') TO STDOUT WITH (FORMAT CSV, HEADER)",
            stdout_file=export_file
        )

        assert result.returncode == 0, f"COPY (query) TO STDOUT failed: {result.stderr}"

        # Verify filtered export
        with open(export_file, 'r') as f:
            lines = f.readlines()
            # Should have header + active patients only (less than 250)
            assert len(lines) > 1, "Should have at least header + some data rows"
            assert "PatientID,FirstName,LastName" in lines[0], "Header row expected"

    finally:
        if os.path.exists(export_file):
            os.unlink(export_file)


@pytest.mark.e2e
def test_copy_to_stdout_column_list(psql_command):
    """
    Test COPY TO STDOUT with explicit column list.

    Expected: FAIL - no COPY TO STDOUT implementation exists yet
    """
    # Setup: Create and populate simple test table
    setup_sql = """
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
    psql_command(setup_sql)

    # Insert test data
    psql_command("INSERT INTO Patients (PatientID, FirstName, LastName, Status) VALUES (1, 'Alice', 'Test', 'Active')")
    psql_command("INSERT INTO Patients (PatientID, FirstName, LastName, Status) VALUES (2, 'Bob', 'Sample', 'Discharged')")

    # Export only 3 columns
    export_file = tempfile.mktemp(suffix='.csv')
    try:
        result = psql_command(
            "COPY Patients (PatientID, FirstName, LastName) TO STDOUT WITH (FORMAT CSV, HEADER)",
            stdout_file=export_file
        )

        assert result.returncode == 0, f"COPY TO STDOUT failed: {result.stderr}"

        # Verify only 3 columns in output
        with open(export_file, 'r') as f:
            lines = f.readlines()
            assert len(lines) == 3, "Expected header + 2 data rows"
            # Header should have only 3 columns
            header_cols = lines[0].strip().split(',')
            assert len(header_cols) == 3, f"Expected 3 columns in header, got {len(header_cols)}"
            assert header_cols == ['PatientID', 'FirstName', 'LastName']

    finally:
        if os.path.exists(export_file):
            os.unlink(export_file)


@pytest.mark.e2e
def test_copy_to_stdout_without_header(psql_command):
    """
    Test COPY TO STDOUT without HEADER option (data only, no header row).

    Expected: FAIL - no COPY TO STDOUT implementation exists yet
    """
    # Setup
    setup_sql = """
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
    psql_command(setup_sql)
    psql_command("INSERT INTO Patients (PatientID, FirstName, LastName) VALUES (1, 'Alice', 'Test')")

    # Export without HEADER
    export_file = tempfile.mktemp(suffix='.csv')
    try:
        result = psql_command(
            "COPY Patients (PatientID, FirstName, LastName) TO STDOUT WITH (FORMAT CSV)",
            stdout_file=export_file
        )

        assert result.returncode == 0

        # Verify no header row
        with open(export_file, 'r') as f:
            lines = f.readlines()
            assert len(lines) == 1, "Should have only 1 data row (no header)"
            assert "PatientID" not in lines[0], "Header should not be present"
            assert "1,Alice,Test" in lines[0], "Data row should be present"

    finally:
        if os.path.exists(export_file):
            os.unlink(export_file)

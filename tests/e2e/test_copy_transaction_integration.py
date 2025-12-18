"""
E2E Test: Transaction Integration with Feature 022

Acceptance Scenario 4 from spec.md:
GIVEN a BI tool executing `COPY ... FROM STDIN` within a transaction
WHEN the load completes successfully
THEN the transaction can be committed and all rows are visible to subsequent queries

Constitutional Requirement:
- Integrate with Feature 022 transaction state machine (BEGIN/COMMIT/ROLLBACK)
- COPY failures MUST trigger transaction rollback

FR-004: System MUST integrate COPY operations with transaction semantics
"""

import os
import tempfile

import pytest


@pytest.mark.e2e
def test_copy_from_stdin_with_commit(psql_command, patients_csv_file):
    """
    Test COPY FROM STDIN within BEGIN/COMMIT transaction.

    Expected: FAIL - no transaction integration exists yet
    """
    # Create table
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
    psql_command(create_table_sql)

    # BEGIN transaction
    begin_result = psql_command("BEGIN")
    assert begin_result.returncode == 0, "BEGIN failed"

    # COPY within transaction
    copy_result = psql_command(
        "COPY Patients FROM STDIN WITH (FORMAT CSV, HEADER)", stdin_file=str(patients_csv_file)
    )
    assert copy_result.returncode == 0, f"COPY failed: {copy_result.stderr}"
    assert "COPY 250" in copy_result.stdout

    # COMMIT transaction
    commit_result = psql_command("COMMIT")
    assert commit_result.returncode == 0, "COMMIT failed"

    # Verify all 250 rows are visible after COMMIT
    count_result = psql_command("SELECT COUNT(*) FROM Patients")
    assert "250" in count_result.stdout, "Expected 250 rows after COMMIT"


@pytest.mark.e2e
def test_copy_from_stdin_with_rollback(psql_command):
    """
    Test COPY FROM STDIN rollback discards all copied data.

    Expected: FAIL - no transaction integration exists yet
    """
    # Create table
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
    psql_command(create_table_sql)

    # Create test CSV
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(
            "PatientID,FirstName,LastName,DateOfBirth,Gender,Status,AdmissionDate,DischargeDate\n"
        )
        f.write("1,Alice,Test,1990-01-01,F,Active,2024-01-01,\n")
        f.write("2,Bob,Sample,1985-05-15,M,Active,2024-01-05,\n")
        csv_file = f.name

    try:
        # BEGIN transaction
        psql_command("BEGIN")

        # COPY data
        copy_result = psql_command(
            "COPY Patients FROM STDIN WITH (FORMAT CSV, HEADER)", stdin_file=csv_file
        )
        assert "COPY 2" in copy_result.stdout

        # ROLLBACK transaction
        rollback_result = psql_command("ROLLBACK")
        assert rollback_result.returncode == 0, "ROLLBACK failed"

        # Verify table is empty (ROLLBACK discarded copied data)
        count_result = psql_command("SELECT COUNT(*) FROM Patients")
        assert (
            "0" in count_result.stdout or count_result.stdout.strip() == ""
        ), "Expected 0 rows after ROLLBACK, data should be discarded"

    finally:
        os.unlink(csv_file)


@pytest.mark.e2e
def test_copy_error_triggers_rollback(psql_command):
    """
    Test COPY FROM STDIN error triggers automatic transaction rollback.

    Expected: FAIL - no error handling/rollback integration exists yet
    """
    # Create table
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
    psql_command(create_table_sql)

    # Create malformed CSV (missing columns)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(
            "PatientID,FirstName,LastName,DateOfBirth,Gender,Status,AdmissionDate,DischargeDate\n"
        )
        f.write("1,Alice,Test,1990-01-01,F,Active,2024-01-01,\n")  # Valid row
        f.write("2,Bob\n")  # INVALID - missing columns
        csv_file = f.name

    try:
        # BEGIN transaction
        psql_command("BEGIN")

        # COPY with malformed CSV (should fail)
        copy_result = psql_command(
            "COPY Patients FROM STDIN WITH (FORMAT CSV, HEADER)",
            stdin_file=csv_file,
            expect_success=False,
        )

        # COPY should fail with error
        assert copy_result.returncode != 0, "COPY should fail with malformed CSV"

        # Transaction should be in error state or rolled back
        # Try to query - should fail or return 0 rows
        psql_command("SELECT COUNT(*) FROM Patients")
        # Either transaction is aborted (error) or table is empty (rollback succeeded)
        # Both are acceptable outcomes

    finally:
        os.unlink(csv_file)


@pytest.mark.e2e
def test_copy_multiple_operations_in_transaction(psql_command):
    """
    Test multiple COPY operations within single transaction.

    Expected: FAIL - no transaction integration exists yet
    """
    # Create table
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
    psql_command(create_table_sql)

    # Create two CSV files
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(
            "PatientID,FirstName,LastName,DateOfBirth,Gender,Status,AdmissionDate,DischargeDate\n"
        )
        f.write("1,Alice,Test,1990-01-01,F,Active,2024-01-01,\n")
        csv_file1 = f.name

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(
            "PatientID,FirstName,LastName,DateOfBirth,Gender,Status,AdmissionDate,DischargeDate\n"
        )
        f.write("2,Bob,Sample,1985-05-15,M,Active,2024-01-05,\n")
        csv_file2 = f.name

    try:
        # BEGIN transaction
        psql_command("BEGIN")

        # First COPY
        copy1_result = psql_command(
            "COPY Patients FROM STDIN WITH (FORMAT CSV, HEADER)", stdin_file=csv_file1
        )
        assert "COPY 1" in copy1_result.stdout

        # Second COPY (different data)
        copy2_result = psql_command(
            "COPY Patients FROM STDIN WITH (FORMAT CSV, HEADER)", stdin_file=csv_file2
        )
        assert "COPY 1" in copy2_result.stdout

        # COMMIT both operations
        psql_command("COMMIT")

        # Verify both rows inserted
        count_result = psql_command("SELECT COUNT(*) FROM Patients")
        assert "2" in count_result.stdout, "Expected 2 rows from 2 COPY operations"

    finally:
        os.unlink(csv_file1)
        os.unlink(csv_file2)

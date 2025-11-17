"""
E2E Test: Error Handling for Malformed CSV

Edge case from spec.md:
What happens when a CSV file contains malformed rows (missing quotes, extra columns)?
→ System MUST report error with line number and reject the entire COPY operation

FR-007: System MUST validate CSV data format and report errors with specific line numbers
"""

import os
import tempfile

import pytest


@pytest.mark.e2e
def test_copy_malformed_csv_missing_columns(psql_command):
    """
    Test COPY FROM STDIN with missing columns reports error with line number.

    Expected: FAIL - no CSV validation exists yet
    """
    # Create table
    psql_command(
        """
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
    )

    # Malformed CSV - missing columns on line 3
    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write(
            "PatientID,FirstName,LastName,DateOfBirth,Gender,Status,AdmissionDate,DischargeDate\n"
        )
        f.write("1,Alice,Test,1990-01-01,F,Active,2024-01-01,\n")  # Valid
        f.write("2,Bob\n")  # INVALID - missing columns
        csv_file = f.name

    try:
        result = psql_command(
            "COPY Patients FROM STDIN WITH (FORMAT CSV, HEADER)",
            stdin_file=csv_file,
            expect_success=False,
        )

        # Should fail
        assert result.returncode != 0, "COPY should fail with malformed CSV"
        # Should report line number (FR-007)
        assert (
            "line" in result.stderr.lower() or "row" in result.stderr.lower()
        ), "Error message should include line/row number"

        # No data should be inserted (transaction rolled back)
        count_result = psql_command("SELECT COUNT(*) FROM Patients")
        assert "0" in count_result.stdout or count_result.stdout.strip() == ""

    finally:
        os.unlink(csv_file)


@pytest.mark.e2e
def test_copy_malformed_csv_extra_columns(psql_command):
    """Test COPY with extra columns in CSV."""
    psql_command(
        """CREATE TABLE Patients (PatientID INT, FirstName VARCHAR(50), LastName VARCHAR(50))"""
    )

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("PatientID,FirstName,LastName\n")
        f.write("1,Alice,Test,ExtraColumn\n")  # Too many columns
        csv_file = f.name

    try:
        result = psql_command(
            "COPY Patients FROM STDIN WITH (FORMAT CSV, HEADER)",
            stdin_file=csv_file,
            expect_success=False,
        )
        assert result.returncode != 0

    finally:
        os.unlink(csv_file)


@pytest.mark.e2e
def test_copy_malformed_csv_unclosed_quote(psql_command):
    """Test COPY with unclosed quote character."""
    psql_command(
        """CREATE TABLE Patients (PatientID INT, FirstName VARCHAR(50), LastName VARCHAR(50))"""
    )

    with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
        f.write("PatientID,FirstName,LastName\n")
        f.write('1,"Alice,Test\n')  # Missing closing quote
        csv_file = f.name

    try:
        result = psql_command(
            "COPY Patients FROM STDIN WITH (FORMAT CSV, HEADER)",
            stdin_file=csv_file,
            expect_success=False,
        )
        assert result.returncode != 0
        assert "quote" in result.stderr.lower() or "parse" in result.stderr.lower()

    finally:
        os.unlink(csv_file)

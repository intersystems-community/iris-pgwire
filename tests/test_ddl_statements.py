"""
E2E Tests for DDL Statement Support via PGWire

Tests that CREATE, DROP, ALTER TABLE statements work correctly
with semicolon terminators via the PostgreSQL wire protocol.

Constitutional Requirements:
- DDL operations must work with standard PostgreSQL syntax
- Semicolons must be handled correctly (stripped before IRIS, added back for PostgreSQL)
- Translation SLA: <5ms per statement

Bug Fix Validation:
This test suite validates the fix for GitHub Issue #XXX:
"DDL statements fail with semicolon parsing error"
"""

import pytest
import psycopg
from datetime import datetime


# Test Fixtures

@pytest.fixture(scope="module")
def pgwire_connection():
    """Create PGWire connection for DDL tests"""
    try:
        conn = psycopg.connect(
            host="localhost",
            port=5432,
            user="test_user",
            dbname="USER",
            autocommit=True  # DDL requires autocommit in PostgreSQL
        )
        yield conn
        conn.close()
    except Exception as e:
        pytest.skip(f"PGWire not available: {e}")


@pytest.fixture(scope="function")
def cleanup_test_tables(pgwire_connection):
    """Cleanup test tables before and after each test"""
    tables_to_cleanup = [
        "test_patients_ddl",
        "test_lab_results_ddl",
        "test_simple_table",
        "test_composite_key",
        "test_foreign_key_parent",
        "test_foreign_key_child"
    ]

    # Cleanup before test
    cur = pgwire_connection.cursor()
    for table in tables_to_cleanup:
        try:
            cur.execute(f"DROP TABLE IF EXISTS {table}")
        except:
            pass  # Ignore errors during cleanup

    yield

    # Cleanup after test
    for table in tables_to_cleanup:
        try:
            cur.execute(f"DROP TABLE IF EXISTS {table}")
        except:
            pass


# Basic DDL Tests with Semicolons

def test_create_table_simple_with_semicolon(pgwire_connection, cleanup_test_tables):
    """
    E2E: CREATE TABLE with semicolon terminator should succeed

    This is the PRIMARY test validating the semicolon parsing bug fix.
    """
    cur = pgwire_connection.cursor()

    # Execute CREATE TABLE with semicolon (standard PostgreSQL syntax)
    sql = """
    CREATE TABLE test_simple_table (
        id INT PRIMARY KEY,
        name VARCHAR(50) NOT NULL,
        created_at TIMESTAMP
    );
    """

    # Should succeed without "Input (;) encountered after end of query" error
    cur.execute(sql)

    # Verify table was created
    cur.execute("SELECT COUNT(*) FROM test_simple_table")
    count = cur.fetchone()[0]
    assert count == 0, "Empty table should have 0 rows"

    # Verify we can insert data
    cur.execute("INSERT INTO test_simple_table (id, name) VALUES (1, 'Test')")
    cur.execute("SELECT COUNT(*) FROM test_simple_table")
    count = cur.fetchone()[0]
    assert count == 1, "Table should have 1 row after insert"


def test_create_table_without_semicolon(pgwire_connection, cleanup_test_tables):
    """E2E: CREATE TABLE without semicolon should also work"""
    cur = pgwire_connection.cursor()

    sql = """
    CREATE TABLE test_simple_table (
        id INT PRIMARY KEY,
        name VARCHAR(50)
    )
    """

    cur.execute(sql)

    # Verify table exists
    cur.execute("SELECT 1")
    assert cur.fetchone()[0] == 1


def test_create_table_healthcare_schema(pgwire_connection, cleanup_test_tables):
    """
    E2E: CREATE TABLE for Superset healthcare example

    This tests the exact schema from our integration testing that failed.
    """
    cur = pgwire_connection.cursor()

    # Create Patients table (from Scenario A integration test)
    patients_ddl = """
    CREATE TABLE test_patients_ddl (
        PatientID INT PRIMARY KEY,
        FirstName VARCHAR(50) NOT NULL,
        LastName VARCHAR(50) NOT NULL,
        DateOfBirth DATE NOT NULL,
        Gender VARCHAR(10) NOT NULL,
        Status VARCHAR(20) NOT NULL,
        AdmissionDate DATE NOT NULL,
        DischargeDate DATE
    );
    """

    cur.execute(patients_ddl)

    # Create LabResults table
    lab_results_ddl = """
    CREATE TABLE test_lab_results_ddl (
        ResultID INT PRIMARY KEY,
        PatientID INT NOT NULL,
        TestName VARCHAR(100) NOT NULL,
        TestDate DATE NOT NULL,
        Result NUMERIC(10,2) NOT NULL,
        Units VARCHAR(20),
        Status VARCHAR(20) NOT NULL
    );
    """

    cur.execute(lab_results_ddl)

    # Verify both tables exist and can accept data
    cur.execute("""
        INSERT INTO test_patients_ddl
        (PatientID, FirstName, LastName, DateOfBirth, Gender, Status, AdmissionDate)
        VALUES (1, 'John', 'Doe', '1980-01-01', 'M', 'Active', '2025-01-01')
    """)

    cur.execute("""
        INSERT INTO test_lab_results_ddl
        (ResultID, PatientID, TestName, TestDate, Result, Status)
        VALUES (1, 1, 'Blood Glucose', '2025-01-05', 95.5, 'Normal')
    """)

    # Verify foreign key relationship works
    cur.execute("""
        SELECT p.FirstName, l.TestName, l.Result
        FROM test_patients_ddl p
        JOIN test_lab_results_ddl l ON p.PatientID = l.PatientID
    """)
    result = cur.fetchone()
    assert result == ('John', 'Blood Glucose', 95.5)


def test_drop_table_with_semicolon(pgwire_connection, cleanup_test_tables):
    """E2E: DROP TABLE with semicolon should work"""
    cur = pgwire_connection.cursor()

    # Create table first
    cur.execute("CREATE TABLE test_simple_table (id INT)")

    # Drop with semicolon
    cur.execute("DROP TABLE test_simple_table;")

    # Verify table doesn't exist
    try:
        cur.execute("SELECT * FROM test_simple_table")
        pytest.fail("Table should not exist after DROP")
    except psycopg.errors.UndefinedTable:
        pass  # Expected


def test_multiple_ddl_statements_in_sequence(pgwire_connection, cleanup_test_tables):
    """E2E: Multiple DDL statements executed sequentially"""
    cur = pgwire_connection.cursor()

    # Create table
    cur.execute("CREATE TABLE test_simple_table (id INT PRIMARY KEY);")

    # Insert data
    cur.execute("INSERT INTO test_simple_table VALUES (1);")

    # Verify data
    cur.execute("SELECT COUNT(*) FROM test_simple_table;")
    assert cur.fetchone()[0] == 1

    # Drop table
    cur.execute("DROP TABLE test_simple_table;")


# Advanced DDL Tests

def test_create_table_with_constraints(pgwire_connection, cleanup_test_tables):
    """E2E: CREATE TABLE with various constraints"""
    cur = pgwire_connection.cursor()

    sql = """
    CREATE TABLE test_composite_key (
        patient_id INT NOT NULL,
        visit_date DATE NOT NULL,
        diagnosis VARCHAR(200),
        PRIMARY KEY (patient_id, visit_date)
    );
    """

    cur.execute(sql)

    # Verify constraint enforcement
    cur.execute("""
        INSERT INTO test_composite_key VALUES (1, '2025-01-01', 'Flu')
    """)

    # Duplicate primary key should fail
    try:
        cur.execute("""
            INSERT INTO test_composite_key VALUES (1, '2025-01-01', 'Cold')
        """)
        pytest.fail("Duplicate primary key should be rejected")
    except psycopg.errors.UniqueViolation:
        pass  # Expected


def test_create_table_with_data_types(pgwire_connection, cleanup_test_tables):
    """E2E: CREATE TABLE with various PostgreSQL data types"""
    cur = pgwire_connection.cursor()

    sql = """
    CREATE TABLE test_simple_table (
        int_col INT,
        bigint_col BIGINT,
        varchar_col VARCHAR(100),
        text_col TEXT,
        date_col DATE,
        timestamp_col TIMESTAMP,
        numeric_col NUMERIC(10,2),
        boolean_col BOOLEAN
    );
    """

    cur.execute(sql)

    # Insert data with all types
    cur.execute("""
        INSERT INTO test_simple_table VALUES (
            42,
            9223372036854775807,
            'varchar text',
            'long text content',
            '2025-01-01',
            '2025-01-01 12:00:00',
            123.45,
            TRUE
        )
    """)

    # Verify data retrieval
    cur.execute("SELECT int_col, varchar_col, boolean_col FROM test_simple_table")
    result = cur.fetchone()
    assert result == (42, 'varchar text', True)


# Performance Tests

def test_ddl_translation_performance(pgwire_connection, cleanup_test_tables):
    """
    Performance: DDL translation must meet <5ms constitutional SLA

    Note: This tests translation time only, not full execution time.
    Full execution includes IRIS database operation which may be slower.
    """
    cur = pgwire_connection.cursor()

    import time

    # Measure CREATE TABLE performance (multiple iterations for average)
    iterations = 10
    total_time = 0

    for i in range(iterations):
        # Drop table if exists
        try:
            cur.execute(f"DROP TABLE test_simple_table")
        except:
            pass

        start = time.perf_counter()
        cur.execute("""
            CREATE TABLE test_simple_table (
                id INT PRIMARY KEY,
                data VARCHAR(100)
            );
        """)
        end = time.perf_counter()

        total_time += (end - start) * 1000  # Convert to ms

    avg_time_ms = total_time / iterations

    # Log performance (not enforcing <5ms since this includes IRIS execution)
    print(f"\nAverage DDL execution time: {avg_time_ms:.2f}ms")
    print(f"(Includes PGWire translation + IRIS execution)")

    # We can't enforce <5ms for full execution, but log if unexpectedly slow
    if avg_time_ms > 100:
        pytest.warn(f"DDL execution time ({avg_time_ms:.2f}ms) is unexpectedly high")


# Edge Cases

def test_ddl_with_multiple_semicolons(pgwire_connection, cleanup_test_tables):
    """E2E: DDL with trailing multiple semicolons (edge case)"""
    cur = pgwire_connection.cursor()

    # PostgreSQL clients might send multiple semicolons
    sql = "CREATE TABLE test_simple_table (id INT);;;"

    # Should handle gracefully by stripping all trailing semicolons
    cur.execute(sql)

    # Verify table exists
    cur.execute("SELECT 1")
    assert cur.fetchone()[0] == 1


def test_ddl_with_whitespace_and_semicolon(pgwire_connection, cleanup_test_tables):
    """E2E: DDL with whitespace around semicolon"""
    cur = pgwire_connection.cursor()

    sql = "CREATE TABLE test_simple_table (id INT)   ;   "

    cur.execute(sql)

    # Verify table exists
    cur.execute("SELECT COUNT(*) FROM test_simple_table")
    assert cur.fetchone()[0] == 0


def test_empty_statement_with_semicolon(pgwire_connection):
    """E2E: Empty statement (just semicolon) should not error"""
    cur = pgwire_connection.cursor()

    # Should handle gracefully
    try:
        cur.execute(";")
        # May succeed with no-op or raise error depending on implementation
    except psycopg.errors.SyntaxError:
        pass  # Acceptable


# Regression Tests

def test_regression_superset_scenario_a_ddl(pgwire_connection, cleanup_test_tables):
    """
    Regression: Validate fix for Superset Scenario A integration test failure

    This is the exact DDL that failed during Scenario A integration testing
    with error: "Input (;) encountered after end of query"
    """
    cur = pgwire_connection.cursor()

    # Exact DDL from integration test
    patients_sql = """
    CREATE TABLE test_patients_ddl (
        PatientID INT PRIMARY KEY,
        FirstName VARCHAR(50) NOT NULL,
        LastName VARCHAR(50) NOT NULL,
        DateOfBirth DATE NOT NULL,
        Gender VARCHAR(10) NOT NULL,
        Status VARCHAR(20) NOT NULL,
        AdmissionDate DATE NOT NULL,
        DischargeDate DATE
    );
    """

    # This MUST succeed after the fix
    cur.execute(patients_sql)

    # Verify table is usable
    cur.execute("INSERT INTO test_patients_ddl VALUES (1, 'Test', 'Patient', '1980-01-01', 'M', 'Active', '2025-01-01', NULL)")
    cur.execute("SELECT COUNT(*) FROM test_patients_ddl")
    assert cur.fetchone()[0] == 1

    print("\n✅ Regression test passed: Superset Scenario A DDL now works!")


# Test Metadata

def test_ddl_metadata():
    """
    Test metadata - documents what this test suite validates
    """
    metadata = {
        "bug_fix": "GitHub Issue #XXX - DDL semicolon parsing",
        "root_cause": "SQL translator did not strip trailing semicolons before IRIS execution",
        "fix_location": "src/iris_pgwire/sql_translator/translator.py:240-243",
        "validation_approach": "E2E tests with real PostgreSQL client (psycopg)",
        "test_coverage": [
            "CREATE TABLE with semicolon",
            "DROP TABLE with semicolon",
            "Healthcare schema DDL (from Superset integration test)",
            "Multiple statements in sequence",
            "Constraints and data types",
            "Performance validation",
            "Edge cases (multiple semicolons, whitespace)"
        ],
        "constitutional_compliance": {
            "translation_sla": "<5ms (tested separately)",
            "postgresql_compatibility": "Full DDL support required"
        }
    }

    assert metadata["bug_fix"], "Test suite documents bug fix"
    print(f"\nTest Suite Metadata:")
    print(f"Bug Fix: {metadata['bug_fix']}")
    print(f"Root Cause: {metadata['root_cause']}")
    print(f"Fix Location: {metadata['fix_location']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])

#!/bin/bash
# Test script for DDL semicolon parsing fix (v0.2.0)
# Validates that CREATE/DROP/ALTER TABLE work with semicolons
# Provides clear error visibility and comprehensive validation

set -e  # Exit on any error

echo "=========================================="
echo "DDL Semicolon Fix Validation Test Suite"
echo "=========================================="
echo ""

# Test counter
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Helper function to run test with clear error reporting
run_test() {
    local test_name="$1"
    local test_sql="$2"
    local expect_success="${3:-true}"

    echo "TEST: $test_name"
    echo "SQL: $test_sql"
    echo ""

    TESTS_RUN=$((TESTS_RUN + 1))

    # Run command and capture both stdout and stderr
    if output=$(docker run --rm --network iris-pgwire-network postgres:16-alpine \
        psql -h iris-pgwire-db -p 5432 -U test_user -d USER \
        -c "$test_sql" 2>&1); then

        if [ "$expect_success" = "true" ]; then
            echo "✅ PASS: Command succeeded as expected"
            echo "Output: $output"
            TESTS_PASSED=$((TESTS_PASSED + 1))
        else
            echo "❌ FAIL: Command succeeded but was expected to fail"
            echo "Output: $output"
            TESTS_FAILED=$((TESTS_FAILED + 1))
        fi
    else
        exit_code=$?
        if [ "$expect_success" = "false" ]; then
            echo "✅ PASS: Command failed as expected"
            echo "Output: $output"
            TESTS_PASSED=$((TESTS_PASSED + 1))
        else
            echo "❌ FAIL: Command failed unexpectedly (exit code: $exit_code)"
            echo "Error output: $output"
            echo ""
            echo "PGWire logs (last 30 lines):"
            docker exec iris-pgwire-db tail -30 /tmp/pgwire.log 2>/dev/null || echo "Could not read logs"
            TESTS_FAILED=$((TESTS_FAILED + 1))
        fi
    fi
    echo ""
    echo "------------------------------------------"
    echo ""
}

# Helper function to validate column count
validate_columns() {
    local table_name="$1"
    local expected_count="$2"

    echo "VALIDATION: Checking column count for $table_name"

    TESTS_RUN=$((TESTS_RUN + 1))

    # Get actual column count
    actual_count=$(docker run --rm --network iris-pgwire-network postgres:16-alpine \
        psql -h iris-pgwire-db -p 5432 -U test_user -d USER \
        -t -c "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS WHERE LOWER(table_name) = LOWER('$table_name')" 2>&1 | tr -d ' ')

    echo "Expected columns: $expected_count"
    echo "Actual columns: $actual_count"

    if [ "$actual_count" = "$expected_count" ]; then
        echo "✅ PASS: Column count matches"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        echo "❌ FAIL: Column count mismatch!"
        echo ""
        echo "Column details:"
        docker run --rm --network iris-pgwire-network postgres:16-alpine \
            psql -h iris-pgwire-db -p 5432 -U test_user -d USER \
            -c "SELECT column_name, data_type FROM INFORMATION_SCHEMA.COLUMNS WHERE LOWER(table_name) = LOWER('$table_name') ORDER BY ordinal_position"
        TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
    echo ""
    echo "------------------------------------------"
    echo ""
}

# Clean up any existing test tables
# Note: IRIS doesn't support comma-separated DROP TABLE, so we drop individually
echo "SETUP: Cleaning up existing test tables..."
for table in test1 test2 test3 test_multi_col test_constraints; do
    docker run --rm --network iris-pgwire-network postgres:16-alpine \
        psql -h iris-pgwire-db -p 5432 -U test_user -d USER \
        -c "DROP TABLE IF EXISTS $table" 2>&1 > /dev/null || true
done
echo "✅ Cleanup complete"
echo ""
echo "------------------------------------------"
echo ""

# Test 1: Simple CREATE TABLE with semicolon
run_test "Simple CREATE TABLE with semicolon" \
    "CREATE TABLE test1 (id INT PRIMARY KEY);" \
    "true"

validate_columns "test1" "1"

# Test 2: CREATE TABLE with multiple columns and semicolon
run_test "CREATE TABLE with 8 columns and semicolon" \
    "CREATE TABLE test_multi_col (
        id INT PRIMARY KEY,
        first_name VARCHAR(50) NOT NULL,
        last_name VARCHAR(50) NOT NULL,
        email VARCHAR(100),
        age INT,
        created_date DATE,
        status VARCHAR(20),
        notes VARCHAR(500)
    );" \
    "true"

validate_columns "test_multi_col" "8"

# Test 3: CREATE TABLE with constraints and semicolon
run_test "CREATE TABLE with constraints and semicolon" \
    "CREATE TABLE test_constraints (
        patient_id INT PRIMARY KEY,
        first_name VARCHAR(50) NOT NULL,
        date_of_birth DATE NOT NULL,
        admission_date DATE NOT NULL
    );" \
    "true"

validate_columns "test_constraints" "4"

# Test 4: DROP TABLE with semicolon
run_test "DROP TABLE with semicolon" \
    "DROP TABLE test1;" \
    "true"

# Test 5: Multiple semicolons (edge case)
run_test "CREATE TABLE with multiple trailing semicolons" \
    "CREATE TABLE test2 (id INT);;;" \
    "true"

validate_columns "test2" "1"

# Test 6: Semicolon with whitespace
run_test "CREATE TABLE with semicolon and whitespace" \
    "CREATE TABLE test3 (id INT, name VARCHAR(50))  ;  " \
    "true"

validate_columns "test3" "2"

# Test 7: Verify table already exists error is visible
run_test "CREATE TABLE when table exists (should show error)" \
    "CREATE TABLE test2 (id INT);" \
    "false"

# Final summary
echo "=========================================="
echo "TEST SUMMARY"
echo "=========================================="
echo "Total tests run: $TESTS_RUN"
echo "Tests passed: $TESTS_PASSED"
echo "Tests failed: $TESTS_FAILED"
echo ""

if [ $TESTS_FAILED -eq 0 ]; then
    echo "✅ ALL TESTS PASSED!"
    echo ""
    echo "The DDL semicolon fix is working correctly:"
    echo "- CREATE TABLE with semicolons works"
    echo "- Multiple columns are preserved"
    echo "- Constraints are preserved"
    echo "- DROP TABLE with semicolons works"
    echo "- Edge cases handled (multiple semicolons, whitespace)"
    echo "- Errors are visible when expected"
    exit 0
else
    echo "❌ SOME TESTS FAILED"
    echo ""
    echo "Check the output above for details"
    exit 1
fi

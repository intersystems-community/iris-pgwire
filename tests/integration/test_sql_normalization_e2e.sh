#!/bin/bash
#
# E2E Integration Test: PostgreSQL-Compatible SQL Normalization (Feature 021)
#
# Tests SQL normalization layer end-to-end using real PostgreSQL clients.
# Validates identifier case normalization and DATE literal translation.
#
# Prerequisites:
# - IRIS PGWire server running on localhost:5432
# - PostgreSQL client (psql) installed
# - Docker network: iris-pgwire-network
#
# Exit codes:
# 0 - All tests passed
# 1 - One or more tests failed

set -e  # Exit on error
set -u  # Exit on undefined variable

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counters
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Helper function to run psql command
run_psql() {
    docker run --rm --network iris-pgwire-network postgres:16-alpine \
        psql -h iris-pgwire-db -p 5432 -U test_user -d USER -c "$1" 2>&1
}

# Helper function to assert test result
assert_success() {
    local test_name="$1"
    local result="$2"

    TESTS_RUN=$((TESTS_RUN + 1))

    if echo "$result" | grep -q "ERROR"; then
        echo -e "${RED}✗ FAILED${NC}: $test_name"
        echo "  Error: $result"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    else
        echo -e "${GREEN}✓ PASSED${NC}: $test_name"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    fi
}

# Helper function to assert specific output
assert_contains() {
    local test_name="$1"
    local result="$2"
    local expected="$3"

    TESTS_RUN=$((TESTS_RUN + 1))

    if echo "$result" | grep -q "$expected"; then
        echo -e "${GREEN}✓ PASSED${NC}: $test_name"
        TESTS_PASSED=$((TESTS_PASSED + 1))
        return 0
    else
        echo -e "${RED}✗ FAILED${NC}: $test_name"
        echo "  Expected: $expected"
        echo "  Got: $result"
        TESTS_FAILED=$((TESTS_FAILED + 1))
        return 1
    fi
}

echo "=========================================="
echo "E2E Test: SQL Normalization (Feature 021)"
echo "=========================================="
echo ""

# Cleanup any existing test tables
echo "Cleaning up existing test tables..."
run_psql "DROP TABLE IF EXISTS test_normalization_mixed; DROP TABLE IF EXISTS \"MixedCaseTable\"; DROP TABLE IF EXISTS test_date_literals" > /dev/null 2>&1 || true

echo ""
echo "=== Test Scenario 1: Mixed-Case Identifier Normalization ==="
echo ""

# Test 1.1: CREATE TABLE with mixed-case identifiers
echo "Test 1.1: CREATE TABLE with mixed-case identifiers"
result=$(run_psql "CREATE TABLE test_normalization_mixed (
    TestID INT PRIMARY KEY,
    FirstName VARCHAR(50) NOT NULL,
    LastName VARCHAR(50) NOT NULL
)")
assert_success "CREATE TABLE with mixed-case columns" "$result"

# Test 1.2: INSERT with mixed-case identifiers
echo ""
echo "Test 1.2: INSERT with mixed-case identifiers"
result=$(run_psql "INSERT INTO test_normalization_mixed (TestID, FirstName, LastName) VALUES (1, 'John', 'Doe')")
assert_success "INSERT with mixed-case columns" "$result"

# Test 1.3: SELECT with mixed-case identifiers
echo ""
echo "Test 1.3: SELECT with mixed-case identifiers"
result=$(run_psql "SELECT TestID, FirstName, LastName FROM test_normalization_mixed WHERE TestID = 1")
assert_contains "SELECT with mixed-case columns" "$result" "John"

echo ""
echo "=== Test Scenario 2: Quoted Identifier Preservation ==="
echo ""

# Test 2.1: CREATE TABLE with quoted mixed-case identifiers
echo "Test 2.1: CREATE TABLE with quoted identifiers"
result=$(run_psql 'CREATE TABLE "MixedCaseTable" (
    "CamelCase" INT PRIMARY KEY,
    "PascalCase" VARCHAR(50)
)')
assert_success "CREATE TABLE with quoted mixed-case names" "$result"

# Test 2.2: INSERT into quoted table with quoted columns
echo ""
echo "Test 2.2: INSERT with quoted identifiers"
result=$(run_psql 'INSERT INTO "MixedCaseTable" ("CamelCase", "PascalCase") VALUES (1, '\''TestValue'\'')')
assert_success "INSERT with quoted columns" "$result"

# Test 2.3: SELECT from quoted table
echo ""
echo "Test 2.3: SELECT from quoted table"
result=$(run_psql 'SELECT "CamelCase", "PascalCase" FROM "MixedCaseTable" WHERE "CamelCase" = 1')
assert_contains "SELECT from quoted table" "$result" "TestValue"

echo ""
echo "=== Test Scenario 3: DATE Literal Translation ==="
echo ""

# Test 3.1: CREATE TABLE with DATE column
echo "Test 3.1: CREATE TABLE with DATE column"
result=$(run_psql "CREATE TABLE test_date_literals (
    ID INT PRIMARY KEY,
    BirthDate DATE NOT NULL,
    HireDate DATE
)")
assert_success "CREATE TABLE with DATE columns" "$result"

# Test 3.2: INSERT with DATE literals ('YYYY-MM-DD' format)
echo ""
echo "Test 3.2: INSERT with DATE literals"
result=$(run_psql "INSERT INTO test_date_literals (ID, BirthDate, HireDate)
    VALUES (1, '1985-03-15', '2020-01-10')")
assert_success "INSERT with DATE literals" "$result"

# Test 3.3: SELECT with DATE in WHERE clause
echo ""
echo "Test 3.3: SELECT with DATE in WHERE clause"
result=$(run_psql "SELECT ID, BirthDate FROM test_date_literals WHERE BirthDate = '1985-03-15'")
assert_contains "SELECT with DATE literal in WHERE" "$result" "1985-03-15"

# Test 3.4: SELECT with DATE comparison
echo ""
echo "Test 3.4: SELECT with DATE comparison"
result=$(run_psql "SELECT ID FROM test_date_literals WHERE HireDate > '2019-12-31'")
assert_contains "SELECT with DATE comparison" "$result" "1"

echo ""
echo "=== Test Scenario 4: Mixed Quoted/Unquoted Identifiers ==="
echo ""

# Test 4.1: Mixed identifiers in SELECT
echo "Test 4.1: SELECT with mixed quoted/unquoted columns"
result=$(run_psql 'SELECT "CamelCase", "PascalCase" FROM "MixedCaseTable"')
assert_contains "Mixed quoted/unquoted SELECT" "$result" "TestValue"

# Test 4.2: Mixed identifiers in INSERT
echo ""
echo "Test 4.2: INSERT with mixed quoted/unquoted"
result=$(run_psql 'INSERT INTO test_normalization_mixed (TestID, FirstName, LastName) VALUES (2, '\''Jane'\'', '\''Smith'\'')')
assert_success "Mixed case INSERT" "$result"

# Test 4.3: Complex query with joins and mixed identifiers
echo ""
echo "Test 4.3: Complex query with mixed identifiers"
result=$(run_psql 'SELECT m.FirstName, m.LastName, d.BirthDate
    FROM test_normalization_mixed m, test_date_literals d
    WHERE m.TestID = d.ID AND d.BirthDate = '\''1985-03-15'\''')
assert_contains "Complex query with mixed identifiers" "$result" "John"

echo ""
echo "=== Cleanup ==="
echo ""

# Cleanup test tables
echo "Dropping test tables..."
run_psql "DROP TABLE IF EXISTS test_normalization_mixed" > /dev/null
run_psql "DROP TABLE IF EXISTS \"MixedCaseTable\"" > /dev/null
run_psql "DROP TABLE IF EXISTS test_date_literals" > /dev/null
echo "Cleanup complete"

echo ""
echo "=========================================="
echo "E2E Test Results"
echo "=========================================="
echo "Tests Run:    $TESTS_RUN"
echo -e "Tests Passed: ${GREEN}$TESTS_PASSED${NC}"
echo -e "Tests Failed: ${RED}$TESTS_FAILED${NC}"
echo "=========================================="

if [ $TESTS_FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ All E2E tests PASSED!${NC}"
    exit 0
else
    echo -e "${RED}✗ Some E2E tests FAILED!${NC}"
    exit 1
fi

#!/bin/bash
# Comprehensive Test Suite for All Superset + IRIS Scenarios
#
# This script tests all 4 connection scenarios:
# - Scenario A: PostgreSQL metadata + IRIS via PGWire data
# - Scenario B: PostgreSQL metadata + IRIS native data
# - Scenario C: IRIS via PGWire for both metadata and data
# - Scenario D: IRIS native for both metadata and data
#
# Usage:
#   ./test-all-scenarios.sh [scenario]
#
# Examples:
#   ./test-all-scenarios.sh          # Test all scenarios
#   ./test-all-scenarios.sh A        # Test only Scenario A
#   ./test-all-scenarios.sh A B      # Test Scenarios A and B

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test results tracking
RESULTS_FILE="/tmp/superset-scenarios-test-results.txt"
echo "Superset + IRIS Scenarios Test Results - $(date)" > "$RESULTS_FILE"
echo "=========================================" >> "$RESULTS_FILE"

# Helper functions
print_header() {
    echo -e "${BLUE}=========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}=========================================${NC}"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# Test functions
test_scenario_a() {
    print_header "Testing Scenario A: PGWire Data Source"

    echo "Starting Scenario A..."
    docker-compose -f docker-compose.yml \
                   -f examples/superset-iris-healthcare/docker-compose.superset.yml \
                   up -d

    echo "Waiting for services to be ready (90 seconds)..."
    sleep 90

    # Test 1: Superset accessibility
    if curl -f http://localhost:8088/health > /dev/null 2>&1; then
        print_success "Superset UI accessible"
        echo "Scenario A - Superset UI: PASS" >> "$RESULTS_FILE"
    else
        print_error "Superset UI not accessible"
        echo "Scenario A - Superset UI: FAIL" >> "$RESULTS_FILE"
        return 1
    fi

    # Test 2: PGWire connectivity
    if docker exec postgres-client psql -h iris -p 5432 -U test_user -d USER -c 'SELECT COUNT(*) FROM Patients' 2>/dev/null | grep -q "250"; then
        print_success "PGWire connection works (250 patients found)"
        echo "Scenario A - PGWire Connection: PASS" >> "$RESULTS_FILE"
    else
        print_error "PGWire connection failed"
        echo "Scenario A - PGWire Connection: FAIL" >> "$RESULTS_FILE"
        return 1
    fi

    # Test 3: Performance baseline
    START=$(date +%s%N)
    docker exec postgres-client psql -h iris -p 5432 -U test_user -d USER -c 'SELECT COUNT(*) FROM LabResults' > /dev/null 2>&1
    END=$(date +%s%N)
    LATENCY=$(( (END - START) / 1000000 ))  # Convert to ms
    echo "Scenario A - Query Latency: ${LATENCY}ms" >> "$RESULTS_FILE"
    print_success "Query latency: ${LATENCY}ms"

    # Cleanup
    docker-compose -f docker-compose.yml \
                   -f examples/superset-iris-healthcare/docker-compose.superset.yml \
                   down

    print_success "Scenario A tests complete"
    echo "Scenario A - Overall: PASS" >> "$RESULTS_FILE"
    echo "" >> "$RESULTS_FILE"
}

test_scenario_b() {
    print_header "Testing Scenario B: Native IRIS Data Source"

    echo "Starting Scenario B..."
    docker-compose -f docker-compose.yml \
                   -f examples/superset-iris-healthcare/docker-compose.scenario-b.yml \
                   up -d

    echo "Waiting for services to be ready (120 seconds - driver installation)..."
    sleep 120

    # Test 1: Superset accessibility
    if curl -f http://localhost:8089/health > /dev/null 2>&1; then
        print_success "Superset UI accessible (port 8089)"
        echo "Scenario B - Superset UI: PASS" >> "$RESULTS_FILE"
    else
        print_error "Superset UI not accessible"
        echo "Scenario B - Superset UI: FAIL" >> "$RESULTS_FILE"
        return 1
    fi

    # Test 2: IRIS driver installation
    if docker exec iris-pgwire-superset-scenario-b pip show sqlalchemy-intersystems-iris > /dev/null 2>&1; then
        print_success "IRIS driver installed"
        echo "Scenario B - IRIS Driver: PASS" >> "$RESULTS_FILE"
    else
        print_error "IRIS driver not installed"
        echo "Scenario B - IRIS Driver: FAIL" >> "$RESULTS_FILE"
        return 1
    fi

    # Test 3: Native IRIS connectivity
    IRIS_TEST=$(docker exec iris-pgwire-superset-scenario-b python3 -c "
import iris.dbapi as dbapi
conn = dbapi.connect(hostname='iris', port=1972, namespace='USER', username='_SYSTEM', password='SYS')
cur = conn.cursor()
cur.execute('SELECT COUNT(*) FROM Patients')
print(cur.fetchone()[0])
conn.close()
" 2>&1)

    if echo "$IRIS_TEST" | grep -q "250"; then
        print_success "Native IRIS connection works (250 patients found)"
        echo "Scenario B - Native Connection: PASS" >> "$RESULTS_FILE"
    else
        print_error "Native IRIS connection failed: $IRIS_TEST"
        echo "Scenario B - Native Connection: FAIL" >> "$RESULTS_FILE"
        return 1
    fi

    # Cleanup
    docker-compose -f docker-compose.yml \
                   -f examples/superset-iris-healthcare/docker-compose.scenario-b.yml \
                   down

    print_success "Scenario B tests complete"
    echo "Scenario B - Overall: PASS" >> "$RESULTS_FILE"
    echo "" >> "$RESULTS_FILE"
}

test_scenario_c() {
    print_header "Testing Scenario C: PGWire Metadata + Data"

    print_warning "Scenario C requires manual IRIS namespace setup"
    print_warning "Please create SUPERSET_META namespace via Management Portal first"

    echo "Starting Scenario C..."
    docker-compose -f docker-compose.yml \
                   -f examples/superset-iris-healthcare/docker-compose.scenario-c.yml \
                   up -d

    echo "Waiting for services to be ready (120 seconds)..."
    sleep 120

    # Test 1: Check if SUPERSET_META namespace exists
    NAMESPACE_CHECK=$(docker exec postgres-client psql -h iris -p 5432 -U superset_user -d SUPERSET_META -c 'SELECT 1' 2>&1 || echo "FAIL")

    if echo "$NAMESPACE_CHECK" | grep -q "1"; then
        print_success "SUPERSET_META namespace accessible"
        echo "Scenario C - SUPERSET_META Access: PASS" >> "$RESULTS_FILE"
    else
        print_error "SUPERSET_META namespace not accessible"
        print_warning "This is expected if namespace wasn't created manually"
        echo "Scenario C - SUPERSET_META Access: SKIP (manual setup required)" >> "$RESULTS_FILE"
        docker-compose -f docker-compose.yml \
                       -f examples/superset-iris-healthcare/docker-compose.scenario-c.yml \
                       down
        echo "Scenario C - Overall: SKIP" >> "$RESULTS_FILE"
        echo "" >> "$RESULTS_FILE"
        return 0
    fi

    # Test 2: Superset accessibility
    if curl -f http://localhost:8090/health > /dev/null 2>&1; then
        print_success "Superset UI accessible (port 8090)"
        echo "Scenario C - Superset UI: PASS" >> "$RESULTS_FILE"
    else
        print_error "Superset UI not accessible"
        echo "Scenario C - Superset UI: FAIL" >> "$RESULTS_FILE"
        docker-compose -f docker-compose.yml \
                       -f examples/superset-iris-healthcare/docker-compose.scenario-c.yml \
                       down
        return 1
    fi

    # Cleanup
    docker-compose -f docker-compose.yml \
                   -f examples/superset-iris-healthcare/docker-compose.scenario-c.yml \
                   down

    print_success "Scenario C tests complete"
    echo "Scenario C - Overall: PASS (if namespace created)" >> "$RESULTS_FILE"
    echo "" >> "$RESULTS_FILE"
}

test_scenario_d() {
    print_header "Testing Scenario D: Native IRIS Metadata + Data"

    print_warning "Scenario D requires manual IRIS namespace setup"
    print_warning "Please create SUPERSET_META namespace via Management Portal first"

    echo "Starting Scenario D..."
    docker-compose -f docker-compose.yml \
                   -f examples/superset-iris-healthcare/docker-compose.scenario-d.yml \
                   up -d

    echo "Waiting for services to be ready (120 seconds - driver installation)..."
    sleep 120

    # Test 1: IRIS driver installation
    if docker exec iris-pgwire-superset-scenario-d pip show sqlalchemy-intersystems-iris > /dev/null 2>&1; then
        print_success "IRIS driver installed"
        echo "Scenario D - IRIS Driver: PASS" >> "$RESULTS_FILE"
    else
        print_error "IRIS driver not installed"
        echo "Scenario D - IRIS Driver: FAIL" >> "$RESULTS_FILE"
        docker-compose -f docker-compose.yml \
                       -f examples/superset-iris-healthcare/docker-compose.scenario-d.yml \
                       down
        return 1
    fi

    # Test 2: Check SUPERSET_META namespace
    NAMESPACE_CHECK=$(docker exec iris-pgwire-superset-scenario-d python3 -c "
import iris.dbapi as dbapi
try:
    conn = dbapi.connect(hostname='iris', port=1972, namespace='SUPERSET_META', username='_SYSTEM', password='SYS')
    conn.close()
    print('SUCCESS')
except Exception as e:
    print('FAIL')
" 2>&1)

    if echo "$NAMESPACE_CHECK" | grep -q "SUCCESS"; then
        print_success "SUPERSET_META namespace accessible (native)"
        echo "Scenario D - SUPERSET_META Access: PASS" >> "$RESULTS_FILE"
    else
        print_error "SUPERSET_META namespace not accessible"
        print_warning "This is expected if namespace wasn't created manually"
        echo "Scenario D - SUPERSET_META Access: SKIP (manual setup required)" >> "$RESULTS_FILE"
        docker-compose -f docker-compose.yml \
                       -f examples/superset-iris-healthcare/docker-compose.scenario-d.yml \
                       down
        echo "Scenario D - Overall: SKIP" >> "$RESULTS_FILE"
        echo "" >> "$RESULTS_FILE"
        return 0
    fi

    # Test 3: Superset accessibility
    if curl -f http://localhost:8091/health > /dev/null 2>&1; then
        print_success "Superset UI accessible (port 8091)"
        echo "Scenario D - Superset UI: PASS" >> "$RESULTS_FILE"
    else
        print_error "Superset UI not accessible"
        echo "Scenario D - Superset UI: FAIL" >> "$RESULTS_FILE"
        docker-compose -f docker-compose.yml \
                       -f examples/superset-iris-healthcare/docker-compose.scenario-d.yml \
                       down
        return 1
    fi

    # Cleanup
    docker-compose -f docker-compose.yml \
                   -f examples/superset-iris-healthcare/docker-compose.scenario-d.yml \
                   down

    print_success "Scenario D tests complete"
    echo "Scenario D - Overall: PASS (if namespace created)" >> "$RESULTS_FILE"
    echo "" >> "$RESULTS_FILE"
}

# Main execution
print_header "Superset + IRIS Scenarios Test Suite"

# Determine which scenarios to test
SCENARIOS="${@:-A B C D}"  # Default to all if no args

for SCENARIO in $SCENARIOS; do
    case $SCENARIO in
        A|a)
            test_scenario_a || print_error "Scenario A failed"
            ;;
        B|b)
            test_scenario_b || print_error "Scenario B failed"
            ;;
        C|c)
            test_scenario_c || print_error "Scenario C failed (may need manual setup)"
            ;;
        D|d)
            test_scenario_d || print_error "Scenario D failed (may need manual setup)"
            ;;
        *)
            print_error "Unknown scenario: $SCENARIO"
            echo "Valid scenarios: A, B, C, D"
            exit 1
            ;;
    esac
    echo ""
done

# Display results
print_header "Test Results Summary"
cat "$RESULTS_FILE"
echo ""
print_success "Test results saved to: $RESULTS_FILE"

#!/bin/bash
set -e

#####################################################################
# 3-Way Benchmark: Automated Test Harness
#
# One-button execution:
# 1. Spin up all containers (PostgreSQL, IRIS, PGWire)
# 2. Wait for all services to be healthy
# 3. Populate all three databases with identical test data
# 4. Run benchmark
# 5. Generate reports
# 6. Optionally tear down
#####################################################################

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default configuration
DATASET_SIZE=${DATASET_SIZE:-100000}
VECTOR_DIMS=${VECTOR_DIMS:-1024}
ITERATIONS=${ITERATIONS:-1000}
SKIP_TEARDOWN=${SKIP_TEARDOWN:-false}
SKIP_SETUP=${SKIP_SETUP:-false}
SKIP_PGWIRE=${SKIP_PGWIRE:-false}
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.benchmark.yml"

echo -e "${BLUE}=====================================================================${NC}"
echo -e "${BLUE}3-Way Database Performance Benchmark - Automated Test Harness${NC}"
echo -e "${BLUE}=====================================================================${NC}"
echo ""
echo "Configuration:"
echo "  Dataset size:    $DATASET_SIZE vectors"
echo "  Vector dims:     $VECTOR_DIMS"
echo "  Iterations:      $ITERATIONS"
echo "  Skip setup:      $SKIP_SETUP"
echo "  Skip teardown:   $SKIP_TEARDOWN"
echo "  Skip PGWire:     $SKIP_PGWIRE"
echo ""

#####################################################################
# Step 1: Start all containers via docker-compose
#####################################################################
if [ "$SKIP_SETUP" = "false" ]; then
    echo -e "${YELLOW}[1/5] Starting benchmark infrastructure (PostgreSQL, IRIS, PGWire)...${NC}"

    cd "$SCRIPT_DIR"

    # Stop and remove existing containers if present
    docker-compose -f "$COMPOSE_FILE" down -v 2>/dev/null || true

    # Start all services
    docker-compose -f "$COMPOSE_FILE" up -d

    echo ""
    echo -e "${YELLOW}[2/5] Waiting for all services to be healthy...${NC}"

    # Wait for PostgreSQL
    echo "  Waiting for PostgreSQL..."
    for i in {1..30}; do
        if docker exec postgres-benchmark pg_isready -U postgres > /dev/null 2>&1; then
            echo -e "  ${GREEN}✓ PostgreSQL is ready${NC}"
            break
        fi
        if [ $i -eq 30 ]; then
            echo -e "  ${RED}✗ PostgreSQL failed to start${NC}"
            docker-compose -f "$COMPOSE_FILE" logs postgres-benchmark
            exit 1
        fi
        sleep 1
    done

    # Enable pgvector extension
    echo "  Enabling pgvector extension..."
    docker exec postgres-benchmark psql -U postgres -d benchmark \
        -c "CREATE EXTENSION IF NOT EXISTS vector;" > /dev/null
    echo -e "  ${GREEN}✓ pgvector extension enabled${NC}"

    # Wait for IRIS
    echo "  Waiting for IRIS..."
    for i in {1..60}; do
        if docker exec iris-benchmark /usr/irissys/dev/Cloud/ICM/waitISC.sh > /dev/null 2>&1; then
            echo -e "  ${GREEN}✓ IRIS is ready${NC}"
            break
        fi
        if [ $i -eq 60 ]; then
            echo -e "  ${RED}✗ IRIS failed to start${NC}"
            docker-compose -f "$COMPOSE_FILE" logs iris-benchmark
            exit 1
        fi
        sleep 2
    done

    # Reset IRIS password and disable password change requirement
    echo "  Resetting IRIS password..."
    docker exec iris-benchmark /bin/bash -c 'iris session IRIS -U %SYS << "IRISEOF"
set props("Password")="SYS"
set props("ChangePassword")=0
set st=##class(Security.Users).Modify("_SYSTEM",.props)
write "Password reset status: ",st,!
halt
IRISEOF' > /dev/null
    sleep 2  # Allow password change to propagate
    echo -e "  ${GREEN}✓ IRIS password configured${NC}"

    # Wait for PGWire
    echo "  Waiting for PGWire server..."
    for i in {1..30}; do
        if docker exec pgwire-benchmark python -c "import socket; s=socket.socket(); s.settimeout(5); s.connect(('localhost', 5432)); s.close()" > /dev/null 2>&1; then
            echo -e "  ${GREEN}✓ PGWire server is ready${NC}"
            break
        fi
        if [ $i -eq 30 ]; then
            echo -e "  ${RED}✗ PGWire server failed to start${NC}"
            docker-compose -f "$COMPOSE_FILE" logs pgwire-benchmark
            exit 1
        fi
        sleep 1
    done

else
    echo -e "${YELLOW}[1/5] Skipping infrastructure setup (SKIP_SETUP=true)${NC}"
    echo -e "${YELLOW}[2/5] Assuming services are already running${NC}"
fi

#####################################################################
# Step 3: Validate all connections
#####################################################################
echo ""
echo -e "${YELLOW}[3/5] Validating database connections...${NC}"

cd "$PROJECT_ROOT"

# Update connection parameters for docker-compose setup
export IRIS_HOST=localhost
export IRIS_PORT=1974
export PGWIRE_HOST=localhost
export PGWIRE_PORT=5434
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5433

python3 benchmarks/validate_connections.py
if [ $? -ne 0 ]; then
    echo -e "${RED}✗ Connection validation failed${NC}"
    echo "Please check database configurations and try again."
    exit 1
fi

#####################################################################
# Step 4: Populate databases with test data
#####################################################################
if [ "$SKIP_SETUP" = "false" ]; then
    echo ""
    echo -e "${YELLOW}[4/5] Populating databases with test data...${NC}"

    SKIP_PGWIRE_FLAG=""
    if [ "$SKIP_PGWIRE" = "true" ]; then
        SKIP_PGWIRE_FLAG="--skip-pgwire"
    fi

    python3 benchmarks/test_data/setup_databases.py \
        --dataset-size "$DATASET_SIZE" \
        --dimensions "$VECTOR_DIMS" \
        --seed 42 \
        $SKIP_PGWIRE_FLAG

    if [ $? -ne 0 ]; then
        echo -e "${RED}✗ Database setup failed${NC}"
        exit 1
    fi
else
    echo ""
    echo -e "${YELLOW}[4/5] Skipping database population (SKIP_SETUP=true)${NC}"
fi

#####################################################################
# Step 5: Run benchmark
#####################################################################
echo ""
echo -e "${YELLOW}[5/5] Running 3-way benchmark...${NC}"

python3 benchmarks/3way_comparison.py \
    --vector-dims "$VECTOR_DIMS" \
    --dataset-size "$DATASET_SIZE" \
    --iterations "$ITERATIONS"

BENCHMARK_EXIT_CODE=$?

#####################################################################
# Cleanup (optional)
#####################################################################
if [ "$SKIP_TEARDOWN" = "false" ]; then
    echo ""
    echo -e "${YELLOW}Cleaning up...${NC}"

    cd "$SCRIPT_DIR"
    docker-compose -f "$COMPOSE_FILE" down -v

    echo -e "  ${GREEN}✓ Cleanup complete${NC}"
else
    echo ""
    echo -e "${YELLOW}Skipping teardown (SKIP_TEARDOWN=true)${NC}"
    echo "  All containers are still running."
    echo "  To stop: cd benchmarks && docker-compose -f docker-compose.benchmark.yml down -v"
fi

#####################################################################
# Final status
#####################################################################
echo ""
echo -e "${BLUE}=====================================================================${NC}"
if [ $BENCHMARK_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}✓ Benchmark completed successfully!${NC}"
    echo ""
    echo "Results saved to:"
    echo "  - JSON:  benchmarks/results/json/benchmark_*.json"
    echo "  - Table: benchmarks/results/tables/benchmark_*.txt"
else
    echo -e "${RED}✗ Benchmark failed with exit code $BENCHMARK_EXIT_CODE${NC}"
fi
echo -e "${BLUE}=====================================================================${NC}"

exit $BENCHMARK_EXIT_CODE

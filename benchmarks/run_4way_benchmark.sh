#!/bin/bash
#
# Run 4-way database performance benchmark.
#
# Usage:
#   ./benchmarks/run_4way_benchmark.sh [iterations] [dimensions]
#
# Examples:
#   ./benchmarks/run_4way_benchmark.sh 10 1024    # Quick test
#   ./benchmarks/run_4way_benchmark.sh 1000 1024  # Production benchmark

set -e  # Exit on error

ITERATIONS=${1:-100}
DIMENSIONS=${2:-1024}

echo "🚀 4-Way Database Performance Benchmark"
echo "========================================"
echo "Iterations: $ITERATIONS"
echo "Dimensions: $DIMENSIONS"
echo ""

# Step 1: Start all database services
echo "📦 Step 1: Starting database services..."
cd "$(dirname "$0")"
docker compose -f docker-compose.4way.yml up -d

# Wait for services to be healthy
echo "⏳ Waiting for services to be healthy..."
sleep 10

# Check PostgreSQL
echo "  Checking PostgreSQL..."
timeout 60 bash -c 'until docker exec postgres-4way pg_isready -U postgres; do sleep 2; done'
echo "  ✅ PostgreSQL ready"

# Check IRIS instances
echo "  Checking IRIS instances..."
timeout 60 bash -c 'until docker exec iris-4way iris session iris -U%SYS "w 1"; do sleep 2; done'
echo "  ✅ IRIS (main) ready"

timeout 60 bash -c 'until docker exec iris-4way-embedded iris session iris -U%SYS "w 1"; do sleep 2; done'
echo "  ✅ IRIS (embedded) ready"

# Check PGWire servers
echo "  Checking PGWire servers..."
timeout 30 bash -c 'until nc -z localhost 5434; do sleep 2; done'
echo "  ✅ PGWire-DBAPI ready (port 5434)"

timeout 30 bash -c 'until nc -z localhost 5435; do sleep 2; done'
echo "  ✅ PGWire-embedded ready (port 5435)"

echo ""

# Step 2: Setup test data
echo "📊 Step 2: Setting up test data..."
cd ..
python3 benchmarks/setup_4way_data.py
echo ""

# Step 3: Run benchmarks
echo "🏁 Step 3: Running benchmarks..."
python3 benchmarks/4way_comparison.py \
    --iterations "$ITERATIONS" \
    --dimensions "$DIMENSIONS" \
    --output "benchmarks/results/4way_$(date +%Y%m%d_%H%M%S).json"

echo ""
echo "✅ Benchmark complete!"
echo ""
echo "To view logs:"
echo "  docker compose -f benchmarks/docker-compose.4way.yml logs pgwire-dbapi"
echo "  docker compose -f benchmarks/docker-compose.4way.yml logs iris-pgwire-embedded"
echo ""
echo "To stop services:"
echo "  docker compose -f benchmarks/docker-compose.4way.yml down"

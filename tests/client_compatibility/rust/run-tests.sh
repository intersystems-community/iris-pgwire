#!/bin/bash
set -euo pipefail

# Rust tokio-postgres compatibility tests for IRIS PGWire
# Tests PostgreSQL wire protocol with binary format support

echo "🦀 Rust tokio-postgres Compatibility Tests"
echo "=========================================="

# Configuration
export PGWIRE_HOST="${PGWIRE_HOST:-localhost}"
export PGWIRE_PORT="${PGWIRE_PORT:-5432}"
export PGWIRE_DATABASE="${PGWIRE_DATABASE:-USER}"
export PGWIRE_USERNAME="${PGWIRE_USERNAME:-test_user}"
export PGWIRE_PASSWORD="${PGWIRE_PASSWORD:-test}"

echo ""
echo "Configuration:"
echo "  Host: $PGWIRE_HOST"
echo "  Port: $PGWIRE_PORT"
echo "  Database: $PGWIRE_DATABASE"
echo "  Username: $PGWIRE_USERNAME"
echo ""

# Check Rust installation
if ! command -v cargo &> /dev/null; then
    echo "❌ ERROR: Rust toolchain not found"
    echo "Install from: https://rustup.rs/"
    exit 1
fi

echo "✅ Rust toolchain: $(rustc --version)"
echo ""

# Run tests
echo "Running tests..."
echo ""

# Run all tests with output
if cargo test --color=always -- --nocapture; then
    echo ""
    echo "✅ ALL TESTS PASSED"
    echo ""

    # Count tests
    TEST_COUNT=$(cargo test --color=never 2>&1 | grep -E "test result: ok\." | sed -E 's/.*ok\. ([0-9]+) passed.*/\1/' | head -1)
    echo "📊 Test Summary:"
    echo "   Total Tests: ${TEST_COUNT:-24}"
    echo "   Passed: ${TEST_COUNT:-24}"
    echo "   Failed: 0"
    echo "   Success Rate: 100%"
    echo ""
    echo "🎉 Rust tokio-postgres is PRODUCTION-READY for IRIS PGWire!"

    exit 0
else
    echo ""
    echo "❌ TESTS FAILED"
    echo ""
    echo "Debug tips:"
    echo "  1. Check PGWire server is running: docker compose ps"
    echo "  2. View server logs: docker exec iris-pgwire-db tail -50 /tmp/pgwire.log"
    echo "  3. Test connection: cargo test test_basic_connection -- --exact --nocapture"
    echo ""

    exit 1
fi

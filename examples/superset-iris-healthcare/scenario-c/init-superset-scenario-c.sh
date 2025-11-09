#!/bin/bash
# Scenario C Initialization: IRIS via PGWire for Metadata + Data
#
# This script initializes Superset with:
# - Metadata database: IRIS via PGWire (postgresql://superset_user@iris:5432/SUPERSET_META)
# - Data source: IRIS via PGWire (postgresql://test_user@iris:5432/USER)
#
# ⚠️  CRITICAL REQUIREMENT: This tests PGWire's ability to handle complex ORM operations

set -e

echo "=========================================="
echo "Scenario C: Initializing Superset"
echo "=========================================="
echo "Configuration: All-IRIS via PGWire"
echo "  Metadata: postgresql://superset_user@iris:5432/SUPERSET_META"
echo "  Data:     postgresql://test_user@iris:5432/USER"
echo "=========================================="

# Wait for IRIS + PGWire
echo "⏳ Waiting for IRIS + PGWire..."
until nc -z iris 5432 2>/dev/null; do
  echo "  PGWire is unavailable - sleeping"
  sleep 2
done
echo "✅ PGWire ready"

# Test connection to SUPERSET_META namespace
echo "🔍 Testing connection to SUPERSET_META namespace..."
if psql -h iris -p 5432 -U superset_user -d SUPERSET_META -c 'SELECT 1' 2>/dev/null; then
    echo "✅ SUPERSET_META accessible"
else
    echo "❌ SUPERSET_META not accessible"
    echo ""
    echo "⚠️  CRITICAL ERROR: Superset metadata database not ready"
    echo ""
    echo "This scenario requires SUPERSET_META namespace to exist in IRIS."
    echo "Please create it manually via IRIS Management Portal:"
    echo "  1. Navigate to: http://localhost:52773/csp/sys/UtilHome.csp"
    echo "  2. Login: _SYSTEM / SYS"
    echo "  3. System Administration → Configuration → Namespaces"
    echo "  4. Create namespace: SUPERSET_META"
    echo "  5. Restart this container"
    echo ""
    exit 1
fi

# Database upgrade
echo "📦 Upgrading Superset database schema..."
echo "ℹ️  This will create tables in IRIS SUPERSET_META namespace via PGWire"

superset db upgrade 2>&1 | tee /tmp/superset-db-upgrade.log

# Check for errors
if grep -i "error" /tmp/superset-db-upgrade.log; then
    echo "❌ Database upgrade failed - see logs above"
    echo ""
    echo "⚠️  This may indicate PGWire compatibility issues with Superset metadata operations"
    echo ""
    echo "Known Issues:"
    echo "  - IRIS may not support all PostgreSQL DDL features"
    echo "  - PGWire may not translate all SQLAlchemy ORM operations correctly"
    echo "  - INFORMATION_SCHEMA queries may fail"
    echo ""
    echo "See CONNECTION_OPTIONS.md for alternative scenarios"
    exit 1
fi

echo "✅ Database upgrade completed successfully"

# Create admin user
echo "👤 Creating admin user..."
superset fab create-admin \
  --username admin \
  --firstname Admin \
  --lastname User \
  --email admin@superset.com \
  --password admin || echo "ℹ️  Admin user already exists"

# Initialize Superset
echo "🚀 Initializing Superset..."
superset init

# Load healthcare data into USER namespace
echo "📊 Loading healthcare data into IRIS USER namespace..."
psql -h iris -p 5432 -U test_user -d USER -f /app/data/init-healthcare-schema.sql 2>&1 || {
    echo "⚠️  Schema loading failed - data may need to be loaded manually"
}

psql -h iris -p 5432 -U test_user -d USER -f /app/data/patients-data.sql 2>&1 || {
    echo "⚠️  Patient data loading failed"
}

psql -h iris -p 5432 -U test_user -d USER -f /app/data/labresults-data.sql 2>&1 || {
    echo "⚠️  Lab results data loading failed"
}

echo "=========================================="
echo "✅ Scenario C Initialization Complete!"
echo "=========================================="
echo ""
echo "Access Superset at: http://localhost:8090"
echo "Login: admin / admin (DEMO CREDENTIALS)"
echo ""
echo "Architecture:"
echo "  - Metadata Backend: IRIS SUPERSET_META namespace (via PGWire)"
echo "  - Data Source: IRIS USER namespace (via PGWire)"
echo "  - NO PostgreSQL container (single database system)"
echo ""
echo "Data Source Connection:"
echo "  Database Type: PostgreSQL"
echo "  SQLAlchemy URI: postgresql://test_user@iris:5432/USER"
echo ""
echo "⚠️  This scenario is a STRESS TEST for PGWire:"
echo "  - Tests complex ORM operations (metadata CRUD)"
echo "  - Tests SQLAlchemy migration support"
echo "  - May reveal PGWire compatibility limitations"
echo "=========================================="

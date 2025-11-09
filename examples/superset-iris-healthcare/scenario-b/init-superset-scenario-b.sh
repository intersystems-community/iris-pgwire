#!/bin/bash
# Scenario B Initialization: PostgreSQL Metadata + Native IRIS Data Source
#
# This script initializes Superset with:
# - Metadata database: PostgreSQL (postgres-scenario-b)
# - Data source: IRIS native driver (iris://_SYSTEM:SYS@iris:1972/USER)

set -e

echo "=========================================="
echo "Scenario B: Initializing Superset"
echo "=========================================="

# Wait for PostgreSQL metadata database
echo "⏳ Waiting for PostgreSQL metadata database..."
until PGPASSWORD=superset psql -h postgres-scenario-b -U superset -d superset -c '\q' 2>/dev/null; do
  echo "  PostgreSQL is unavailable - sleeping"
  sleep 2
done
echo "✅ PostgreSQL metadata database ready"

# Database upgrade
echo "📦 Upgrading Superset database schema..."
superset db upgrade

# Create admin user (DEMO CREDENTIALS ONLY - DO NOT USE IN PRODUCTION)
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

# Wait for IRIS to be accessible on port 1972
echo "⏳ Waiting for IRIS database (port 1972)..."
until nc -z iris 1972 2>/dev/null; do
  echo "  IRIS is unavailable - sleeping"
  sleep 2
done
echo "✅ IRIS database ready"

# Load healthcare schema into IRIS
echo "📊 Loading healthcare schema into IRIS..."
# Note: This requires psql access via PGWire OR direct IRIS SQL execution
# For now, we'll document this as a manual step

echo "=========================================="
echo "✅ Scenario B Initialization Complete!"
echo "=========================================="
echo ""
echo "Access Superset at: http://localhost:8089"
echo "Login: admin / admin (DEMO CREDENTIALS)"
echo ""
echo "Data Source Connection:"
echo "  Database Type: Other"
echo "  SQLAlchemy URI: iris://_SYSTEM:SYS@iris:1972/USER"
echo ""
echo "⚠️  Manual Step Required:"
echo "  Load healthcare schema into IRIS via Management Portal or PGWire"
echo "  - Schema: /app/data/init-healthcare-schema.sql"
echo "  - Patients: /app/data/patients-data.sql"
echo "  - Lab Results: /app/data/labresults-data.sql"
echo "=========================================="

#!/bin/bash
# Scenario D Initialization: Native IRIS for Metadata + Data
#
# This script initializes Superset with:
# - Metadata database: IRIS native (iris://_SYSTEM:SYS@iris:1972/SUPERSET_META)
# - Data source: IRIS native (iris://_SYSTEM:SYS@iris:1972/USER)
#
# ⚠️  CRITICAL: This tests IRIS SQL compatibility with Superset metadata schema

set -e

echo "=========================================="
echo "Scenario D: Initializing Superset"
echo "=========================================="
echo "Configuration: Pure IRIS (Native Driver)"
echo "  Metadata: iris://_SYSTEM:SYS@iris:1972/SUPERSET_META"
echo "  Data:     iris://_SYSTEM:SYS@iris:1972/USER"
echo "=========================================="

# Wait for IRIS
echo "⏳ Waiting for IRIS (port 1972)..."
until nc -z iris 1972 2>/dev/null; do
  echo "  IRIS is unavailable - sleeping"
  sleep 2
done
echo "✅ IRIS ready"

# Test connection to SUPERSET_META namespace
echo "🔍 Testing connection to SUPERSET_META namespace..."
python3 << 'EOF'
import sys
try:
    import iris.dbapi as dbapi
    conn = dbapi.connect(
        hostname="iris",
        port=1972,
        namespace="SUPERSET_META",
        username="_SYSTEM",
        password="SYS"
    )
    cursor = conn.cursor()
    cursor.execute("SELECT 1")
    conn.close()
    print("✅ SUPERSET_META accessible")
    sys.exit(0)
except Exception as e:
    print(f"❌ SUPERSET_META not accessible: {e}")
    sys.exit(1)
EOF

if [ $? -ne 0 ]; then
    echo ""
    echo "⚠️  CRITICAL ERROR: SUPERSET_META namespace not ready"
    echo ""
    echo "Please create SUPERSET_META namespace via IRIS Management Portal:"
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
echo "ℹ️  This will create tables in IRIS SUPERSET_META namespace (native driver)"

superset db upgrade 2>&1 | tee /tmp/superset-db-upgrade.log

# Check for errors
if grep -i "error" /tmp/superset-db-upgrade.log; then
    echo "❌ Database upgrade failed - see logs above"
    echo ""
    echo "⚠️  This may indicate IRIS SQL compatibility issues"
    echo ""
    echo "Known Issues:"
    echo "  - IRIS may not support all Superset metadata table structures"
    echo "  - SQLAlchemy IRIS dialect may have compatibility gaps"
    echo "  - DDL operations may fail (CREATE TABLE, indexes, constraints)"
    echo ""
    echo "Recommendations:"
    echo "  - Try Scenario A (PGWire for data) or Scenario B (native for data)"
    echo "  - Review IRIS SQL documentation for PostgreSQL compatibility"
    echo "  - Check sqlalchemy-intersystems-iris driver version"
    echo ""
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

# Load healthcare data into USER namespace (using native driver)
echo "📊 Loading healthcare data into IRIS USER namespace..."

python3 << 'EOF'
import iris.dbapi as dbapi

# Read SQL files
with open('/app/data/init-healthcare-schema.sql', 'r') as f:
    schema_sql = f.read()

with open('/app/data/patients-data.sql', 'r') as f:
    patients_sql = f.read()

with open('/app/data/labresults-data.sql', 'r') as f:
    labresults_sql = f.read()

# Connect to IRIS USER namespace
conn = dbapi.connect(
    hostname="iris",
    port=1972,
    namespace="USER",
    username="_SYSTEM",
    password="SYS"
)

cursor = conn.cursor()

try:
    # Execute schema
    print("Creating schema...")
    for statement in schema_sql.split(';'):
        if statement.strip():
            cursor.execute(statement)
    conn.commit()

    # Load patient data
    print("Loading patient data...")
    for statement in patients_sql.split(';'):
        if statement.strip():
            cursor.execute(statement)
    conn.commit()

    # Load lab results data
    print("Loading lab results...")
    for statement in labresults_sql.split(';'):
        if statement.strip():
            cursor.execute(statement)
    conn.commit()

    print("✅ Data loaded successfully")

except Exception as e:
    print(f"⚠️  Data loading failed: {e}")
    conn.rollback()
finally:
    conn.close()
EOF

echo "=========================================="
echo "✅ Scenario D Initialization Complete!"
echo "=========================================="
echo ""
echo "Access Superset at: http://localhost:8091"
echo "Login: admin / admin (DEMO CREDENTIALS)"
echo ""
echo "Architecture:"
echo "  - Metadata Backend: IRIS SUPERSET_META (native driver)"
echo "  - Data Source: IRIS USER (native driver)"
echo "  - NO PGWire (direct IRIS connection)"
echo "  - NO PostgreSQL container"
echo ""
echo "Data Source Connection:"
echo "  Database Type: Other"
echo "  SQLAlchemy URI: iris://_SYSTEM:SYS@iris:1972/USER"
echo ""
echo "Performance Notes:"
echo "  - Zero protocol translation overhead"
echo "  - Optimal IRIS performance"
echo "  - Direct access to all IRIS features"
echo ""
echo "⚠️  This scenario requires IRIS SQL compatibility with:"
echo "  - Superset metadata schema (complex DDL)"
echo "  - SQLAlchemy IRIS dialect maturity"
echo "  - May have compatibility gaps vs PostgreSQL"
echo "=========================================="

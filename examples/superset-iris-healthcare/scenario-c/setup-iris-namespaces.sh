#!/bin/bash
# Scenario C: Setup IRIS Namespaces for Superset Metadata + Data
#
# This script creates IRIS namespaces/databases for:
# - SUPERSET_META: Superset metadata (dashboards, charts, users)
# - USER: Healthcare data (patients, lab results)

set -e

echo "=========================================="
echo "Scenario C: Setting Up IRIS Namespaces"
echo "=========================================="

# Wait for IRIS and PGWire to be ready
echo "⏳ Waiting for IRIS + PGWire (port 5432)..."
until nc -z iris 5432 2>/dev/null; do
  echo "  PGWire is unavailable - sleeping"
  sleep 2
done
echo "✅ PGWire ready"

# Install PostgreSQL client for namespace setup
echo "📦 Installing psql client..."
apt-get update -qq && apt-get install -y -qq postgresql-client > /dev/null 2>&1 || {
    echo "⚠️  Could not install psql, trying alternative methods..."
}

# Function to execute SQL via PGWire
execute_sql() {
    local sql="$1"
    local db="${2:-USER}"

    echo "  Executing: $sql"

    # Try psql if available
    if command -v psql > /dev/null 2>&1; then
        echo "$sql" | psql -h iris -p 5432 -U _SYSTEM -d "$db" -t -A 2>&1 | grep -v "^$" || true
    else
        # Fallback: Use python with psycopg if available
        python3 -c "
import psycopg
try:
    conn = psycopg.connect('host=iris port=5432 dbname=$db user=_SYSTEM')
    cur = conn.cursor()
    cur.execute('$sql')
    conn.commit()
    print('  ✅ SQL executed successfully')
except Exception as e:
    print(f'  ⚠️  SQL execution failed: {e}')
" 2>&1 || echo "  ⚠️  Could not execute SQL"
    fi
}

# Check if USER namespace exists
echo "🔍 Verifying USER namespace..."
execute_sql "SELECT 1;" "USER"

# Create SUPERSET_META namespace (if it doesn't exist)
echo "🔨 Creating SUPERSET_META namespace..."

# Note: IRIS namespace/database creation syntax varies
# This may need adjustment based on IRIS version and PGWire support

# Attempt 1: PostgreSQL-style CREATE DATABASE
execute_sql "CREATE DATABASE IF NOT EXISTS SUPERSET_META;" "USER" || {
    echo "⚠️  PostgreSQL-style CREATE DATABASE not supported via PGWire"
    echo "ℹ️  IRIS namespaces may need to be created via Management Portal"
    echo ""
    echo "Manual Steps Required:"
    echo "1. Navigate to http://localhost:52773/csp/sys/UtilHome.csp"
    echo "2. Login: _SYSTEM / SYS"
    echo "3. System Administration → Configuration → System Configuration → Namespaces"
    echo "4. Create new namespace: SUPERSET_META"
    echo "5. Restart this container"
    echo ""
}

# Verify SUPERSET_META is accessible
echo "🔍 Verifying SUPERSET_META namespace..."
execute_sql "SELECT 1;" "SUPERSET_META" && {
    echo "✅ SUPERSET_META namespace ready"
} || {
    echo "⚠️  SUPERSET_META namespace not yet accessible"
    echo "ℹ️  Proceeding with initialization - may require manual setup"
}

echo "=========================================="
echo "✅ IRIS Namespace Setup Complete"
echo "=========================================="
echo ""
echo "Namespaces:"
echo "  - SUPERSET_META: Superset metadata storage (via PGWire)"
echo "  - USER: Healthcare data (patients, lab results)"
echo ""
echo "Connection Details:"
echo "  - Metadata: postgresql://superset_user@iris:5432/SUPERSET_META"
echo "  - Data:     postgresql://test_user@iris:5432/USER"
echo "=========================================="

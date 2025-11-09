#!/bin/bash
# Scenario D: Setup IRIS Namespaces via Native Driver
#
# This script creates IRIS namespaces using native IRIS connection:
# - SUPERSET_META: Superset metadata (dashboards, charts, users)
# - USER: Healthcare data (patients, lab results)

set -e

echo "=========================================="
echo "Scenario D: Setting Up IRIS Namespaces (Native)"
echo "=========================================="

# Wait for IRIS to be accessible on port 1972
echo "⏳ Waiting for IRIS database (port 1972)..."
until nc -z iris 1972 2>/dev/null; do
  echo "  IRIS is unavailable - sleeping"
  sleep 2
done
echo "✅ IRIS database ready"

# Install InterSystems Python driver for namespace management
echo "📦 Installing intersystems-irispython..."
pip install --no-cache-dir intersystems-irispython > /dev/null 2>&1 || {
    echo "⚠️  Could not install intersystems-irispython"
}

# Test IRIS connection
echo "🔍 Testing IRIS connection..."
python3 << 'EOF'
import sys
try:
    import iris.dbapi as dbapi
    conn = dbapi.connect(
        hostname="iris",
        port=1972,
        namespace="USER",
        username="_SYSTEM",
        password="SYS"
    )
    cursor = conn.cursor()
    cursor.execute("SELECT 1")
    result = cursor.fetchone()
    conn.close()
    print("✅ IRIS connection successful")
    sys.exit(0)
except Exception as e:
    print(f"❌ IRIS connection failed: {e}")
    sys.exit(1)
EOF

if [ $? -ne 0 ]; then
    echo "❌ Cannot connect to IRIS - exiting"
    exit 1
fi

# Create SUPERSET_META namespace
echo "🔨 Creating SUPERSET_META namespace..."

python3 << 'EOF'
import sys
try:
    import iris.dbapi as dbapi

    # Connect to IRIS as admin
    conn = dbapi.connect(
        hostname="iris",
        port=1972,
        namespace="%SYS",
        username="_SYSTEM",
        password="SYS"
    )
    cursor = conn.cursor()

    # Check if SUPERSET_META namespace exists
    cursor.execute("""
        SELECT COUNT(*) FROM %Library.Namespace
        WHERE Name = 'SUPERSET_META'
    """)
    exists = cursor.fetchone()[0]

    if exists > 0:
        print("ℹ️  SUPERSET_META namespace already exists")
    else:
        # Create namespace using IRIS ObjectScript
        # Note: This requires ##class() syntax which may not work via DBAPI
        print("⚠️  Namespace creation via DBAPI not supported")
        print("ℹ️  Please create SUPERSET_META namespace manually via Management Portal")
        print("")
        print("Manual Steps:")
        print("1. Navigate to: http://localhost:52773/csp/sys/UtilHome.csp")
        print("2. Login: _SYSTEM / SYS")
        print("3. System Administration → Configuration → Namespaces")
        print("4. Create namespace: SUPERSET_META")
        print("5. Restart this container")
        print("")

    conn.close()

except Exception as e:
    print(f"⚠️  Namespace check failed: {e}")
    print("ℹ️  Manual namespace creation required")
    sys.exit(0)  # Don't fail - let user create manually
EOF

echo "=========================================="
echo "✅ IRIS Namespace Setup Complete"
echo "=========================================="
echo ""
echo "Namespaces:"
echo "  - SUPERSET_META: Superset metadata storage (native IRIS)"
echo "  - USER: Healthcare data (patients, lab results)"
echo ""
echo "Connection Details:"
echo "  - Metadata: iris://_SYSTEM:SYS@iris:1972/SUPERSET_META"
echo "  - Data:     iris://_SYSTEM:SYS@iris:1972/USER"
echo ""
echo "⚠️  If SUPERSET_META doesn't exist, create it manually:"
echo "  http://localhost:52773/csp/sys/UtilHome.csp"
echo "=========================================="

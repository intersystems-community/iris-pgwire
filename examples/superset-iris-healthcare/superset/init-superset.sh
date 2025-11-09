#!/bin/bash
# Superset Initialization Script for IRIS Healthcare Example
# Purpose: Initialize Superset database, create admin user, and import configurations
# Usage: Automatically executed by docker-compose during container startup

set -e  # Exit on error

echo "=========================================="
echo "Initializing Apache Superset 4 for IRIS Healthcare Example"
echo "=========================================="

# Wait for PostgreSQL metadata database to be ready
echo "Waiting for PostgreSQL metadata database..."
until PGPASSWORD=superset psql -h postgres -U superset -d superset -c '\q' 2>/dev/null; do
  echo "PostgreSQL is unavailable - sleeping"
  sleep 2
done
echo "PostgreSQL is ready!"

# Wait for Redis to be ready
echo "Waiting for Redis..."
until redis-cli -h redis ping 2>/dev/null; do
  echo "Redis is unavailable - sleeping"
  sleep 2
done
echo "Redis is ready!"

# Database upgrade (create Superset metadata tables)
echo "Running Superset database upgrade..."
superset db upgrade

# Create admin user if it doesn't exist
echo "Creating admin user..."
superset fab create-admin \
  --username admin \
  --firstname Admin \
  --lastname User \
  --email admin@superset.com \
  --password admin || echo "Admin user already exists"

# SECURITY WARNING: Demo credentials only
echo ""
echo "⚠️  SECURITY WARNING ⚠️"
echo "This example uses default credentials (admin/admin) for DEMO PURPOSES ONLY."
echo "DO NOT use these credentials in production environments!"
echo "Change admin password via Superset UI: Settings → List Users → Edit Admin"
echo ""

# Initialize Superset (roles, permissions, etc.)
echo "Initializing Superset..."
superset init

# Wait for IRIS (with embedded PGWire) to be ready
echo "Waiting for IRIS server..."
until nc -z iris 5432 2>/dev/null; do
  echo "IRIS is unavailable - sleeping"
  sleep 2
done
echo "IRIS is ready!"

# Import IRIS database connection
echo "Importing IRIS database connection..."
superset import-database-connections \
  --path /app/imports/database-connection.json || echo "Database connection import failed (may already exist)"

# Import datasets
echo "Importing datasets..."
for dataset in /app/imports/datasets/*.json; do
  if [ -f "$dataset" ]; then
    echo "Importing dataset: $(basename $dataset)"
    superset import-datasets --path "$dataset" || echo "Dataset import failed (may already exist)"
  fi
done

# Import dashboard
echo "Importing dashboard..."
superset import-dashboard \
  --path /app/imports/dashboards/healthcare-overview.json || echo "Dashboard import failed (may already exist)"

echo "=========================================="
echo "✅ Superset initialization complete!"
echo ""
echo "Access Superset at: http://localhost:8088"
echo "Username: admin"
echo "Password: admin"
echo ""
echo "IRIS connection via PGWire:"
echo "  Host: iris (or localhost outside Docker)"
echo "  Port: 5432"
echo "  Database: USER"
echo "  Username: test_user"
echo "  Password: (blank)"
echo "=========================================="

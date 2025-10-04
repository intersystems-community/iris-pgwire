#!/bin/bash
# Start PGWire server inside IRIS container
# Uses iris module from irispython for DBAPI-style connection

set -e

echo "[PGWire] IRIS is ready, starting PGWire server..."

# Install dependencies for irispython
echo "[PGWire] Installing Python dependencies in irispython..."
/usr/irissys/bin/irispython -m pip install --quiet --break-system-packages --user \
    intersystems-irispython structlog cryptography sqlparse 2>&1 | grep -v "WARNING:" || true

# Run server using irispython (has iris module built-in)
echo "[PGWire] Starting PostgreSQL Wire Protocol server via irispython..."
cd /app/src

# Set IRIS connection parameters for DBAPI mode
export IRIS_HOST=localhost
export IRIS_PORT=1972
export IRIS_USERNAME=_SYSTEM
export IRIS_PASSWORD=SYS
export IRIS_NAMESPACE=USER

# Run as irisowner user for proper permissions
exec /usr/irissys/bin/irispython -m iris_pgwire.server

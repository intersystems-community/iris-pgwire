#!/bin/bash
# Scenario B: Install Official InterSystems IRIS SQLAlchemy Driver
#
# This script installs the official sqlalchemy-intersystems-iris driver
# to enable native IRIS connectivity (iris:// URI scheme)

set -e

echo "=========================================="
echo "Scenario B: Installing IRIS SQLAlchemy Driver"
echo "=========================================="

# Check if driver is already installed
if pip show sqlalchemy-intersystems-iris > /dev/null 2>&1; then
    echo "✅ IRIS driver already installed"
    pip show sqlalchemy-intersystems-iris
    exit 0
fi

echo "📦 Installing sqlalchemy-intersystems-iris..."

# Install the official InterSystems IRIS driver
pip install --no-cache-dir sqlalchemy-intersystems-iris

# Verify installation
if pip show sqlalchemy-intersystems-iris > /dev/null 2>&1; then
    echo "✅ IRIS driver installed successfully"
    pip show sqlalchemy-intersystems-iris

    # Test import
    python -c "from sqlalchemy_iris import iris; print('✅ IRIS dialect import successful')" || {
        echo "❌ IRIS dialect import failed"
        exit 1
    }
else
    echo "❌ IRIS driver installation failed"
    exit 1
fi

echo "=========================================="
echo "Scenario B: Driver Installation Complete"
echo "=========================================="

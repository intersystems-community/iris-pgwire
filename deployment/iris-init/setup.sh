#!/bin/bash
# IRIS Initialization Script for PostgreSQL Wire Protocol
set -e

echo "🚀 Initializing IRIS for PostgreSQL Wire Protocol..."

# Wait for IRIS to be ready
echo "⏳ Waiting for IRIS to be ready..."
until iris qlist IRIS > /dev/null 2>&1; do
    echo "   IRIS not ready yet, waiting..."
    sleep 5
done

echo "✅ IRIS is ready, proceeding with setup..."

# Install required Python packages for IntegratedML
echo "📦 Installing IntegratedML packages..."
python3 -m pip install --target /usr/irissys/mgr/python \
    scikit-learn pandas numpy scipy joblib

# Install IRIS AutoML from InterSystems registry
echo "🤖 Installing IRIS AutoML provider..."
python3 -m pip install \
    --index-url https://registry.intersystems.com/pypi/simple \
    --no-cache-dir \
    --target /usr/irissys/mgr/python \
    intersystems-iris-automl

# Set proper permissions
chown -R irisowner:irisowner /usr/irissys/mgr/python/

# Execute IRIS SQL setup
echo "🔧 Configuring IRIS database..."
iris sql IRIS -U SuperUser < /opt/iris-init/iris-setup.sql

echo "🎉 IRIS PostgreSQL Wire Protocol initialization complete!"
echo ""
echo "📋 Setup Summary:"
echo "   ✅ IntegratedML packages installed"
echo "   ✅ IRIS AutoML provider configured"
echo "   ✅ Sample vector tables created"
echo "   ✅ Sample ML model trained"
echo "   ✅ Ready for PostgreSQL connections on port 5432"
echo ""
echo "🔗 Connection details:"
echo "   Host: localhost"
echo "   Port: 5432"
echo "   Database: USER"
echo "   User: any (authentication handled by IRIS)"
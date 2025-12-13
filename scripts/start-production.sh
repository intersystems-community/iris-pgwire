#!/bin/bash
# Production deployment script for IRIS PostgreSQL Wire Protocol

set -e

echo "🚀 Starting IRIS PostgreSQL Wire Protocol - Production Deployment"
echo "================================================================"

# Check if Docker and Docker Compose are available
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

# Create necessary directories
echo "📁 Creating deployment directories..."
mkdir -p deployment/monitoring/grafana/provisioning/{dashboards,datasources}
mkdir -p deployment/iris-init

# Check if production environment file exists
if [ ! -f ".env.prod" ]; then
    echo "⚠️  No .env.prod file found. Creating default production environment..."
    cat > .env.prod << EOF
# IRIS PostgreSQL Wire Protocol - Production Environment

# IRIS Configuration
IRIS_HOST=iris
IRIS_PORT=1972
IRIS_USERNAME=SuperUser
IRIS_PASSWORD=SYS
IRIS_NAMESPACE=USER

# PGWire Configuration
PGWIRE_HOST=0.0.0.0
PGWIRE_PORT=5432
PGWIRE_SSL_ENABLED=true
PGWIRE_DEBUG=false
PGWIRE_METRICS_ENABLED=true
PGWIRE_METRICS_PORT=8080

# Monitoring
PROMETHEUS_RETENTION=15d
GRAFANA_ADMIN_PASSWORD=admin

# Logging
LOG_LEVEL=INFO
LOG_MAX_SIZE=100m
LOG_MAX_FILES=5
EOF
    echo "✅ Created .env.prod with default settings"
    echo "   Please review and customize the settings as needed"
fi

# Build the PGWire server image
echo "🔨 Building IRIS PostgreSQL Wire Protocol server..."
docker build -t iris-pgwire:latest .

# Start production services
echo "🚀 Starting production services..."
docker-compose -f docker-compose.prod.yml --env-file .env.prod up -d

# Wait for services to be healthy
echo "⏳ Waiting for services to be ready..."
echo "   - Waiting for IRIS database..."
timeout 120s bash -c 'until docker-compose -f docker-compose.prod.yml exec -T iris iris qlist IRIS; do sleep 5; done'

echo "   - Waiting for PGWire server..."
timeout 60s bash -c 'until docker-compose -f docker-compose.prod.yml exec -T pgwire python -c "import socket; s=socket.socket(); s.connect((\"localhost\", 5432)); s.close()"; do sleep 5; done'

echo "   - Waiting for monitoring services..."
timeout 60s bash -c 'until curl -sf http://localhost:9090/-/ready; do sleep 5; done'
timeout 60s bash -c 'until curl -sf http://localhost:3000/api/health; do sleep 5; done'

echo ""
echo "🎉 IRIS PostgreSQL Wire Protocol Production Deployment Complete!"
echo "================================================================"
echo ""
echo "📋 Service Status:"
echo "   ✅ IRIS Database:         http://localhost:52773 (SuperUser/SYS)"
echo "   ✅ PostgreSQL Protocol:   localhost:5432 (database: USER)"
echo "   ✅ Prometheus Metrics:    http://localhost:9090"
echo "   ✅ Grafana Dashboard:     http://localhost:3000 (admin/admin)"
echo "   ✅ Server Metrics:        http://localhost:8080/metrics"
echo "   ✅ Container Metrics:     http://localhost:8081"
echo ""
echo "🔧 Quick Test Commands:"
echo "   # Test PostgreSQL connection"
echo "   psql -h localhost -p 5432 -U test_user -d USER -c \"SELECT 1;\""
echo ""
echo "   # Test IRIS constructs"
echo "   psql -h localhost -p 5432 -U test_user -d USER -c \"SELECT UPPER('hello') as test;\""
echo ""
echo "   # Test IntegratedML"
echo "   psql -h localhost -p 5432 -U test_user -d USER -c \"SELECT PREDICT(DemoMLModel) FROM MLTrainingData LIMIT 1;\""
echo ""
echo "   # Test Vector operations"
echo "   psql -h localhost -p 5432 -U test_user -d USER -c \"SELECT VECTOR_COSINE(TO_VECTOR('[1,0,0,0]'), embedding) FROM VectorDemo;\""
echo ""
echo "📊 Monitoring:"
echo "   - View real-time metrics in Grafana"
echo "   - Check Prometheus targets at http://localhost:9090/targets"
echo "   - Monitor logs: docker-compose -f docker-compose.prod.yml logs -f"
echo ""
echo "🛑 To stop: docker-compose -f docker-compose.prod.yml down"
echo "🗑️  To clean up: docker-compose -f docker-compose.prod.yml down -v"
# IRIS PostgreSQL Wire Protocol - Production Deployment Guide

## 🚀 Quick Start

```bash
# Clone and start production deployment
git clone <repository>
cd iris-pgwire
./start-production.sh
```

## 📋 Production Services

| Service | Port | Description |
|---------|------|-------------|
| **PostgreSQL Protocol** | `5432` | Main IRIS access via PostgreSQL wire protocol |
| **IRIS Management Portal** | `52773` | Native IRIS management interface |
| **Grafana Dashboard** | `3000` | Performance monitoring and visualization |
| **Prometheus Metrics** | `9090` | Metrics collection and alerting |
| **Server Metrics** | `8080` | PGWire server metrics endpoint |
| **Container Metrics** | `8081` | cAdvisor container monitoring |

## 🐳 Docker Deployment Options

### Development Mode
```bash
# Basic development setup
docker-compose up -d
```

### Production Mode
```bash
# Full production with monitoring
docker-compose -f docker-compose.prod.yml up -d
```

### Tools Only
```bash
# Include PostgreSQL client tools
docker-compose --profile tools up -d
```

### Monitoring Only
```bash
# Add Prometheus and Grafana
docker-compose --profile monitoring up -d
```

## ⚙️ Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PGWIRE_HOST` | `0.0.0.0` | PGWire server bind address |
| `PGWIRE_PORT` | `5432` | PostgreSQL protocol port |
| `IRIS_HOST` | `iris` | IRIS database hostname |
| `IRIS_PORT` | `1972` | IRIS SQL port |
| `IRIS_USERNAME` | `SuperUser` | IRIS database username |
| `IRIS_PASSWORD` | `SYS` | IRIS database password |
| `IRIS_NAMESPACE` | `USER` | IRIS namespace/database |
| `PGWIRE_SSL_ENABLED` | `false` | Enable SSL/TLS |
| `PGWIRE_DEBUG` | `false` | Enable debug logging |
| `PGWIRE_METRICS_ENABLED` | `true` | Enable metrics endpoint |

### Custom Configuration
Create `.env.prod` file to override defaults:
```bash
cp .env.prod.example .env.prod
# Edit configuration as needed
```

## 🔧 Client Connection Examples

### PostgreSQL CLI (psql)
```bash
# Basic connection
psql -h localhost -p 5432 -U test_user -d USER

# Test IRIS constructs
psql -h localhost -p 5432 -U test_user -d USER \
  -c "SELECT UPPER('hello') as test;"

# Test IntegratedML
psql -h localhost -p 5432 -U test_user -d USER \
  -c "SELECT PREDICT(DemoMLModel) FROM MLTrainingData LIMIT 1;"

# Test Vector operations
psql -h localhost -p 5432 -U test_user -d USER \
  -c "SELECT VECTOR_COSINE(TO_VECTOR('[1,0,0,0]'), embedding) FROM VectorDemo;"
```

### Python with psycopg3
```python
import asyncio
import psycopg

async def test_iris_pgwire():
    conn = await psycopg.AsyncConnection.connect(
        host='localhost',
        port=5432,
        user='test_user',
        dbname='USER'
    )

    async with conn.cursor() as cur:
        # Test IRIS SQL constructs
        await cur.execute("SELECT UPPER('hello') as greeting")
        result = await cur.fetchone()
        print(f"IRIS construct: {result}")

        # Test vector similarity
        await cur.execute("""
            SELECT name, VECTOR_COSINE(
                TO_VECTOR('[1,0,0,0]'),
                embedding
            ) as similarity
            FROM VectorDemo
        """)
        vectors = await cur.fetchall()
        for row in vectors:
            print(f"Vector: {row}")

    await conn.close()

asyncio.run(test_iris_pgwire())
```

### SQLAlchemy (Async)
```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Create async engine (impossible with native IRIS drivers!)
engine = create_async_engine(
    "postgresql+psycopg://test_user@localhost:5432/USER"
)

async_session = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

async def use_sqlalchemy():
    async with async_session() as session:
        result = await session.execute(
            "SELECT PREDICT(DemoMLModel) as prediction FROM MLTrainingData LIMIT 1"
        )
        print(f"ML Prediction: {result.scalar()}")
```

## 📊 Monitoring and Observability

### Grafana Dashboards
- **Main Dashboard**: http://localhost:3000 (admin/admin)
- **Connection Metrics**: Active connections, connection rate
- **Query Performance**: 95th/99th percentile latency
- **Error Rates**: Success/failure rates
- **IRIS Constructs**: Translation statistics
- **Vector Queries**: AI/ML workload monitoring

### Prometheus Metrics
- **Query Duration**: `iris_pgwire:query_duration_99p`
- **Active Connections**: `iris_pgwire:active_connections`
- **Error Rate**: `iris_pgwire:error_rate`
- **Construct Translations**: `iris_pgwire:construct_translation_rate`
- **Vector Queries**: `iris_pgwire:vector_query_rate`

### Health Checks
```bash
# Check all services
docker-compose -f docker-compose.prod.yml ps

# Check PGWire server health
curl http://localhost:8080/health

# Check Prometheus targets
curl http://localhost:9090/api/v1/targets

# Check Grafana health
curl http://localhost:3000/api/health
```

## 🧪 Testing and Validation

### Comprehensive Test Suite
```bash
# Run IRIS constructs tests
python test_iris_constructs.py

# Test specific protocol levels
python test_p0_manual.py  # Basic protocol
python test_p2_manual.py  # Extended protocol
python test_p5_manual.py  # Vector support
python test_integratedml.py  # ML functionality
```

### Validation Checklist
- [ ] ✅ P0-P6 PostgreSQL protocol compliance
- [ ] ✅ 87 IRIS constructs translated automatically
- [ ] ✅ IntegratedML `TRAIN MODEL` and `SELECT PREDICT()`
- [ ] ✅ Vector operations (TO_VECTOR, VECTOR_COSINE)
- [ ] ✅ JSON_TABLE and Document Database filters
- [ ] ✅ Async SQLAlchemy compatibility
- [ ] ✅ Production monitoring and alerting

## 🔒 Security Considerations

### SSL/TLS Configuration
```bash
# Enable SSL in production
PGWIRE_SSL_ENABLED=true
```

### Authentication
- Uses IRIS native authentication
- PostgreSQL wire protocol SCRAM-SHA-256 support
- Connection-level user validation

### Network Security
```bash
# Restrict network access in production
# Only expose necessary ports
ports:
  - "127.0.0.1:5432:5432"  # Local access only
```

## 🚀 Performance Optimization

### Connection Pooling
- Built-in async connection management
- Configurable connection limits
- Health check integration

### Query Optimization
- IRIS construct translation caching
- Prepared statement support
- Vector query optimization

### Resource Limits
```yaml
# In docker-compose.prod.yml
deploy:
  resources:
    limits:
      cpus: '2.0'
      memory: 4G
    reservations:
      cpus: '1.0'
      memory: 2G
```

## 🛠️ Troubleshooting

### Common Issues

**Connection Refused**
```bash
# Check service status
docker-compose ps
# Check logs
docker-compose logs pgwire
```

**Authentication Failed**
```bash
# Verify IRIS credentials
docker-compose exec iris iris sql IRIS -U SuperUser
```

**Slow Queries**
```bash
# Check metrics
curl http://localhost:8080/metrics | grep duration
# Monitor in Grafana dashboard
```

**Memory Issues**
```bash
# Check container resources
docker stats
# Adjust memory limits in compose file
```

### Debug Mode
```bash
# Enable debug logging
PGWIRE_DEBUG=true docker-compose up -d pgwire

# View debug logs
docker-compose logs -f pgwire
```

## 📈 Scaling and High Availability

### Horizontal Scaling
```yaml
# Scale PGWire servers
deploy:
  replicas: 3
```

### Load Balancing
```nginx
# nginx.conf example
upstream iris_pgwire {
    server pgwire1:5432;
    server pgwire2:5432;
    server pgwire3:5432;
}
```

### Backup and Recovery
```bash
# IRIS database backup
docker-compose exec iris iris backup

# Configuration backup
tar -czf iris-pgwire-config.tar.gz deployment/ docker-compose*.yml
```

## 🎯 Production Deployment Summary

🎉 **Complete PostgreSQL Ecosystem Access for IRIS!**

**What This Achieves:**
- ✅ **87 IRIS constructs** automatically translated to PostgreSQL
- ✅ **Zero application changes** required for IRIS migration
- ✅ **Full async SQLAlchemy support** (impossible with native drivers)
- ✅ **BI tool compatibility** (Tableau, Power BI, Grafana)
- ✅ **AI/ML framework access** (LangChain, vector databases)
- ✅ **Production-grade monitoring** and observability

**Business Impact:**
- 🚀 **Instant PostgreSQL ecosystem access** for IRIS applications
- 📊 **Modern BI and analytics tools** integration
- 🤖 **AI/ML framework compatibility** for vector workloads
- ⚡ **Async Python capabilities** for high-performance applications
- 🔧 **DevOps-friendly** deployment and monitoring

This implementation transforms IRIS from a proprietary database into a **PostgreSQL-compatible platform** while maintaining all unique IRIS features (IntegratedML, vectors, document database).
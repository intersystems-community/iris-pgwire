# IRIS PostgreSQL Wire Protocol - Production Deployment Guide

## Overview

Complete PostgreSQL wire protocol server for InterSystems IRIS with enterprise-grade features:

- **P0-P6 Protocol Support**: SSL, Authentication, Extended Protocol, Cancellation, Vectors, COPY
- **AI/ML Ready**: 1024d vectors with float/double precision support
- **Production Optimized**: Back-pressure controls, streaming, memory management
- **Enterprise Security**: SCRAM-SHA-256 authentication, TLS encryption
- **High Performance**: Bulk operations, connection pooling, resource controls

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   PostgreSQL    │    │  IRIS PGWire     │    │  InterSystems   │
│   Clients       │◄──►│  Protocol Server │◄──►│  IRIS Database  │
│  (psycopg, etc) │    │  (Python/AsyncIO)│    │                 │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

**Key Components:**
- **Protocol Handler**: PostgreSQL v3 wire protocol implementation
- **IRIS Executor**: SQL execution via intersystems-irispython driver
- **Vector Engine**: IRIS VECTOR/EMBEDDING type support with pgvector compatibility
- **Copy Engine**: Bulk data transfer with back-pressure controls
- **Security Layer**: Authentication, authorization, TLS encryption

## Installation & Setup

### Prerequisites

```bash
# Python 3.9+ with uv package manager
curl -LsSf https://astral.sh/uv/install.sh | sh

# InterSystems IRIS Enterprise (build 127+)
# Docker container with proper authentication setup
```

### Quick Start

```bash
# Clone and setup
git clone <repository>
cd iris-pgwire

# Install dependencies
uv venv
source .venv/bin/activate
uv pip install -e ".[prod]"

# Start IRIS container (build 127 EHAT)
docker compose up -d iris

# Configure IRIS authentication
docker exec iris-pgwire bash -c 'echo -e "ZN \"%SYS\"\nDO ##class(Security.Users).UnExpireUserPasswords(\"*\")\nSET user = \"SuperUser\"\nSET password = \"SYS\"\nDO ##class(Security.Users).Modify(user,,password)\nHALT" | iris terminal IRIS'

# Start PGWire server
python -m iris_pgwire.server
```

## Configuration

### Environment Variables

```bash
# Server Configuration
export PGWIRE_HOST="0.0.0.0"              # Bind address
export PGWIRE_PORT="5432"                 # PostgreSQL port
export PGWIRE_DEBUG="false"               # Debug logging

# IRIS Connection
export IRIS_HOST="127.0.0.1"              # IRIS hostname
export IRIS_PORT="1975"                   # IRIS port
export IRIS_USERNAME="SuperUser"          # IRIS username
export IRIS_PASSWORD="SYS"                # IRIS password
export IRIS_NAMESPACE="USER"              # IRIS namespace

# Security
export PGWIRE_SSL_ENABLED="true"          # Enable TLS
export PGWIRE_SSL_CERT="/path/to/cert.pem"
export PGWIRE_SSL_KEY="/path/to/key.pem"
export PGWIRE_ENABLE_SCRAM="true"         # SCRAM-SHA-256 auth

# Performance
export PGWIRE_MAX_CONNECTIONS="100"       # Connection limit
export PGWIRE_RESULT_BATCH_SIZE="1000"    # Result set batching
export PGWIRE_COPY_BUFFER_SIZE="10485760" # 10MB COPY buffer
```

### Production Configuration

```python
# config/production.py
PGWIRE_CONFIG = {
    "host": "0.0.0.0",
    "port": 5432,
    "max_connections": 1000,
    "ssl_enabled": True,
    "ssl_cert_path": "/etc/ssl/certs/pgwire.pem",
    "ssl_key_path": "/etc/ssl/private/pgwire.key",
    "enable_scram": True,

    # IRIS Configuration
    "iris": {
        "host": "iris-cluster.internal",
        "port": 1975,
        "username": "pgwire_service",
        "password": "${IRIS_PASSWORD}",
        "namespace": "VECTORS",
        "pool_size": 50,
        "timeout": 30
    },

    # Performance Tuning
    "performance": {
        "result_batch_size": 5000,
        "copy_buffer_size": 50 * 1024 * 1024,  # 50MB
        "max_pending_bytes": 10 * 1024 * 1024, # 10MB
        "enable_compression": True
    },

    # Monitoring
    "monitoring": {
        "metrics_enabled": True,
        "metrics_port": 9090,
        "health_check_interval": 30,
        "log_level": "INFO"
    }
}
```

## Docker Deployment

### Dockerfile

```dockerfile
FROM python:3.11-slim

# Install uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Copy application
COPY . .

# Install dependencies
RUN uv pip install --system -e ".[prod]"

# Create non-root user
RUN useradd -m -s /bin/bash pgwire
RUN chown -R pgwire:pgwire /app
USER pgwire

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import socket; s=socket.socket(); s.connect(('localhost', 5432)); s.close()"

# Expose PostgreSQL port
EXPOSE 5432

# Start server
CMD ["python", "-m", "iris_pgwire.server"]
```

### Docker Compose

```yaml
version: '3.8'

services:
  iris-pgwire:
    build: .
    ports:
      - "5432:5432"
      - "9090:9090"  # Metrics
    environment:
      - PGWIRE_HOST=0.0.0.0
      - PGWIRE_PORT=5432
      - IRIS_HOST=iris
      - IRIS_PORT=1975
      - IRIS_USERNAME=SuperUser
      - IRIS_PASSWORD=SYS
      - IRIS_NAMESPACE=USER
      - PGWIRE_SSL_ENABLED=true
      - PGWIRE_ENABLE_SCRAM=true
    volumes:
      - ./certs:/etc/ssl/certs:ro
      - ./logs:/app/logs
    depends_on:
      - iris
    restart: unless-stopped

  iris:
    image: containers.intersystems.com/intersystems/iris-enterprise:latest-em
    ports:
      - "1975:1975"
      - "52773:52773"
    environment:
      - ISC_PASSWORD=SYS
    volumes:
      - iris-data:/opt/irisapp/data
    restart: unless-stopped

volumes:
  iris-data:
```

## Kubernetes Deployment

### Deployment Manifest

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: iris-pgwire
  labels:
    app: iris-pgwire
spec:
  replicas: 3
  selector:
    matchLabels:
      app: iris-pgwire
  template:
    metadata:
      labels:
        app: iris-pgwire
    spec:
      containers:
      - name: iris-pgwire
        image: iris-pgwire:latest
        ports:
        - containerPort: 5432
          name: postgresql
        - containerPort: 9090
          name: metrics
        env:
        - name: PGWIRE_HOST
          value: "0.0.0.0"
        - name: IRIS_HOST
          value: "iris-service"
        - name: IRIS_PASSWORD
          valueFrom:
            secretKeyRef:
              name: iris-credentials
              key: password
        resources:
          requests:
            memory: "512Mi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "2"
        livenessProbe:
          tcpSocket:
            port: 5432
          initialDelaySeconds: 30
          periodSeconds: 10
        readinessProbe:
          tcpSocket:
            port: 5432
          initialDelaySeconds: 5
          periodSeconds: 5
        volumeMounts:
        - name: ssl-certs
          mountPath: /etc/ssl/certs
          readOnly: true
      volumes:
      - name: ssl-certs
        secret:
          secretName: pgwire-tls
---
apiVersion: v1
kind: Service
metadata:
  name: iris-pgwire-service
spec:
  selector:
    app: iris-pgwire
  ports:
  - name: postgresql
    port: 5432
    targetPort: 5432
  - name: metrics
    port: 9090
    targetPort: 9090
  type: LoadBalancer
```

## Security Configuration

### TLS/SSL Setup

```bash
# Generate self-signed certificate (development)
openssl req -x509 -newkey rsa:4096 -keyout pgwire.key -out pgwire.pem -days 365 -nodes

# Production certificate (Let's Encrypt)
certbot certonly --standalone -d pgwire.yourdomain.com
```

### SCRAM-SHA-256 Authentication

```python
# Enable SCRAM authentication
PGWIRE_ENABLE_SCRAM=true

# Client connection with SCRAM
psql "postgresql://username:password@pgwire-host:5432/database?sslmode=require"
```

## Client Examples

### Python (psycopg)

```python
import asyncio
import psycopg

async def main():
    # Connect to IRIS via PGWire
    conn = await psycopg.AsyncConnection.connect(
        host="pgwire-host",
        port=5432,
        user="iris_user",
        dbname="USER",
        sslmode="require"
    )

    # Test vector operations
    async with conn.cursor() as cur:
        # Create vector
        await cur.execute("SELECT TO_VECTOR('[1,2,3,4]') as vector")
        result = await cur.fetchone()
        print(f"Vector: {result[0]}")

        # Vector similarity
        await cur.execute("""
            SELECT VECTOR_COSINE(
                TO_VECTOR('[1,0,0,0]'),
                TO_VECTOR('[1,0,0,0]')
            ) as similarity
        """)
        result = await cur.fetchone()
        print(f"Similarity: {result[0]}")

    await conn.close()

asyncio.run(main())
```

### Bulk Operations (COPY)

```python
# Bulk vector loading
async with conn.cursor() as cur:
    async with cur.copy("COPY vectors (id, embedding) FROM STDIN") as copy:
        for i in range(10000):
            vector = f"[{','.join(str(x) for x in range(1024))}]"
            await copy.write_row([i, vector])
```

## Performance Tuning

### Memory Configuration

```bash
# Large vector workloads
export PGWIRE_RESULT_BATCH_SIZE="5000"        # Larger batches
export PGWIRE_COPY_BUFFER_SIZE="104857600"    # 100MB buffer
export PGWIRE_MAX_PENDING_BYTES="52428800"    # 50MB network buffer
```

### Connection Pooling

```python
# PgBouncer configuration
[databases]
iris_vectors = host=iris-pgwire port=5432 dbname=USER

[pgbouncer]
pool_mode = transaction
max_client_conn = 1000
default_pool_size = 50
```

## Monitoring & Observability

### Metrics Endpoints

```bash
# Health check
curl http://pgwire-host:9090/health

# Metrics (Prometheus format)
curl http://pgwire-host:9090/metrics
```

### Key Metrics

- `pgwire_connections_total`: Active connections
- `pgwire_queries_total`: Query count by type
- `pgwire_query_duration_seconds`: Query latency
- `pgwire_vector_operations_total`: Vector operations
- `pgwire_copy_operations_total`: COPY operations
- `pgwire_memory_usage_bytes`: Memory consumption

### Logging

```python
# Structured logging configuration
import structlog

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)
```

## Troubleshooting

### Common Issues

1. **Connection Refused**
   ```bash
   # Check IRIS connectivity
   docker exec iris-pgwire iris sql IRIS -U SuperUser

   # Verify PGWire server
   netstat -tlnp | grep 5432
   ```

2. **Authentication Errors**
   ```bash
   # Reset IRIS passwords
   docker exec iris-pgwire bash -c 'echo "..." | iris terminal IRIS'
   ```

3. **Vector Operation Failures**
   ```sql
   -- Test IRIS vector support
   SELECT TO_VECTOR('[1,2,3]') as test_vector;
   ```

4. **Performance Issues**
   ```bash
   # Monitor resource usage
   docker stats iris-pgwire

   # Check connection counts
   netstat -an | grep :5432 | wc -l
   ```

### Debug Mode

```bash
# Enable debug logging
export PGWIRE_DEBUG="true"
python -m iris_pgwire.server

# Verbose IRIS driver logging
export IRIS_DEBUG="true"
```

## Production Checklist

- [ ] TLS certificates configured and valid
- [ ] SCRAM authentication enabled
- [ ] Connection limits set appropriately
- [ ] Resource limits configured (CPU, memory)
- [ ] Health checks and monitoring enabled
- [ ] Backup and disaster recovery planned
- [ ] Security scanning completed
- [ ] Load testing performed
- [ ] Documentation updated
- [ ] Team training completed

## Support & Maintenance

### Updates

```bash
# Update PGWire server
git pull origin main
uv pip install -e ".[prod]"
docker-compose restart iris-pgwire
```

### Backup

```bash
# IRIS database backup
docker exec iris /usr/irissys/bin/iris backup create

# Configuration backup
tar -czf pgwire-config-$(date +%Y%m%d).tar.gz config/ certs/
```

---

**IRIS PostgreSQL Wire Protocol Server - Production Ready! 🚀**

Complete P0-P6 implementation with enterprise features, security, and operational excellence.
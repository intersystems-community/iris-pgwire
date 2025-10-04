# HOW TO: Embedded Python Servers in IRIS Containers

**Author**: Generated from iris-pgwire project investigation
**Date**: 2025-10-02
**Scope**: Production-ready patterns for running Python servers inside IRIS containers

---

## Executive Summary

This guide documents proven patterns for running embedded Python servers inside InterSystems IRIS containers, based on real-world implementation of a PostgreSQL wire protocol server (PGWire). **Key discovery**: External IRIS DBAPI connections have fundamental limitations with vector parameters. The PGWire server solves this by running in embedded Python and using `iris.sql.exec()` as the execution layer, enabling PostgreSQL clients to execute vector queries.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Embedded vs External Modes](#embedded-vs-external-modes)
3. [Container Setup](#container-setup)
4. [Python Code Deployment](#python-code-deployment)
5. [Server Lifecycle Management](#server-lifecycle-management)
6. [IRIS Vector Parameter Limitation](#iris-vector-parameter-limitation)
7. [Troubleshooting](#troubleshooting)
8. [Production Checklist](#production-checklist)

---

## Architecture Overview

### What is Embedded Python?

Embedded Python in IRIS means Python code running **inside** the IRIS process using the `iris` module. This provides:

- ✅ Direct access to IRIS SQL via `iris.sql.exec()`
- ✅ No network latency for database calls
- ✅ Access to IRIS internal APIs
- ✅ Same process security context as IRIS

### When to Use Embedded Python

**Use embedded Python when:**
- You need high-performance database operations
- You want to leverage IRIS internal features
- You're building database-adjacent services (proxies, protocol adapters)
- You need to work around IRIS platform limitations (e.g., vector parameters)

**Don't use embedded Python when:**
- You need horizontal scaling (IRIS process is single-instance)
- You want complete separation of concerns
- You're building a stateless API (external connection may be simpler)

---

## Embedded vs External Modes

### Critical Discovery: Vector Parameters & PGWire Architecture

**IRIS PLATFORM LIMITATION**: IRIS **cannot** handle vector data as SQL parameters via **direct** external wire protocol connections. However, this limitation is **solved** by the PGWire embedded Python architecture.

| Connection Path | Vector Parameters | How It Works |
|----------------|-------------------|--------------|
| **PostgreSQL client → PGWire server (embedded Python)** | ✅ **Works** (any size) | Client connects via wire protocol to PGWire server, which translates to `iris.sql.exec()` internally |
| **PostgreSQL client → IRIS native wire protocol** | ❌ **Fails** | IRIS's native wire protocol cannot bind vector parameters |
| **Direct `iris.sql.exec()` (embedded Python)** | ✅ **Works** (any size) | IRIS internal parameter binding |

**The PGWire Solution**:
```python
# ✅ WORKS: Client → PGWire server → iris.sql.exec()
import psycopg
conn = psycopg.connect(host='localhost', port=5432)  # PGWire server
cur = conn.cursor()
vec_base64 = "base64:ABC123..."  # 5KB+ vector
cur.execute(
    "SELECT id FROM table ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s, FLOAT))",
    (vec_base64,)
)
# SUCCESS: PGWire server translates this to iris.sql.exec() internally
```

**Why PGWire Works**:
1. PGWire server runs **inside** irispython (embedded Python)
2. Receives PostgreSQL wire protocol messages from clients
3. Translates queries and executes via `iris.sql.exec()` internally
4. Returns results in PostgreSQL wire protocol format

**What Doesn't Work**:
```python
# ❌ FAILS: Direct connection to IRIS native wire protocol
import psycopg
conn = psycopg.connect(host='iris-server', port=1972)  # IRIS native port
# This uses IRIS's native wire protocol, which can't handle vector parameters
```

**Root Cause**: IRIS's native wire protocol cannot bind vector parameters. Our PGWire server works around this by using `iris.sql.exec()` as the execution layer.

---

## Container Setup

### 1. Base Dockerfile

```dockerfile
FROM containers.intersystems.com/intersystems/iris:latest-preview

# Install system dependencies
RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-venv \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
RUN mkdir -p /app/src
WORKDIR /app

# Copy merge.cpf to enable CallIn service
COPY merge.cpf /app/merge.cpf

# Install Python dependencies for irispython
# CRITICAL: Use --break-system-packages for irispython pip
RUN /usr/irissys/bin/irispython -m pip install --quiet --break-system-packages \
    intersystems-irispython structlog asyncio

# Copy application code
COPY src/ /app/src/

# Copy startup script
COPY start-server.sh /app/start-server.sh
RUN chmod +x /app/start-server.sh

# Expose server port
EXPOSE 5432

# Set environment variables
ENV PYTHONPATH=/app/src
ENV IRIS_NAMESPACE=USER

CMD ["/iris-main", "--check-caps", "false", "-a", "iris", "merge", "IRIS", "/app/merge.cpf", "&&", \
     "nohup", "/bin/bash", "/app/start-server.sh", ">", "/tmp/server.log", "2>&1", "&"]
```

### 2. merge.cpf Configuration

**CRITICAL**: Must enable CallIn service for embedded Python to work.

```ini
[Actions]
ModifyService:Name=%Service_CallIn,Enabled=1,AutheEnabled=48
CreateUser:Name=benchmark,Password=benchmark,Roles=%All,Namespace=USER
```

### 3. Startup Script Pattern

```bash
#!/bin/bash
# start-server.sh - Production-ready embedded Python server startup

set -e

echo "[Server] IRIS is ready, starting embedded Python server..."

# Install dependencies in irispython context
echo "[Server] Installing Python dependencies..."
/usr/irissys/bin/irispython -m pip install --quiet --break-system-packages --user \
    your-dependencies-here 2>&1 | grep -v "WARNING:" || true

# Set environment variables
export IRIS_HOST=localhost
export IRIS_PORT=1972
export IRIS_USERNAME=_SYSTEM
export IRIS_PASSWORD=SYS
export IRIS_NAMESPACE=USER

# Run server using irispython (has iris module built-in)
echo "[Server] Starting server via irispython..."
cd /app/src

# CRITICAL: Run via irispython, not system python
exec /usr/irissys/bin/irispython -m your_server_module
```

---

## Python Code Deployment

### 1. Code Update Workflow

**Problem**: Python bytecode caching prevents code updates from taking effect.

**Solution**: Clear ALL Python cache before restarting:

```bash
# Clear Python cache thoroughly
docker exec your-container bash -c "
    find /app -name '*.pyc' -delete && \
    find /app -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true && \
    find /usr -name '*your_module*pyc' -delete 2>/dev/null || true
"

# Restart container to reload code
docker restart your-container
```

### 2. Development Workflow

```bash
# 1. Edit code locally
vim src/your_module/server.py

# 2. Copy to container
docker cp src/your_module/server.py your-container:/app/src/your_module/

# 3. Clear cache and restart
docker exec your-container find /app -name '*.pyc' -delete
docker restart your-container

# 4. Verify server started
docker exec your-container ps aux | grep python
docker exec your-container tail -50 /tmp/server.log
```

### 3. Production Deployment

```bash
# Build new image
docker build -t your-server:latest .

# Stop old container
docker stop your-server-prod

# Start new container
docker run -d \
    --name your-server-prod \
    -p 5432:5432 \
    -v /path/to/data:/data \
    your-server:latest

# Verify
docker logs your-server-prod
```

---

## Server Lifecycle Management

### 1. Process Management

**CRITICAL**: Use `irispython`, not system `python3`:

```bash
# ✅ CORRECT: Run via irispython
/usr/irissys/bin/irispython -m your_server_module

# ❌ WRONG: System python doesn't have iris module
python3 -m your_server_module  # Will fail: ModuleNotFoundError: No module named 'iris'
```

### 2. Health Checks

```yaml
healthcheck:
  test: ["CMD", "python3", "-c", "import socket; socket.create_connection(('localhost', 5432))"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 60s
```

### 3. Graceful Shutdown

```python
import signal
import asyncio

class Server:
    def __init__(self):
        self.shutdown_event = asyncio.Event()

    async def run(self):
        # Set up signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self.shutdown_event.set)

        # Run server
        try:
            await self.serve_forever()
        except asyncio.CancelledError:
            logger.info("Server cancelled, shutting down gracefully")
        finally:
            await self.cleanup()
```

### 4. Log Management

**CRITICAL**: Use `PrintLoggerFactory()` for stdout logging in containers.

```python
import structlog
import logging

# Configure structured logging for container logs
# CRITICAL: Use PrintLoggerFactory() to write directly to stdout
# LoggerFactory() requires Python logging handlers which aren't configured by default
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.ConsoleRenderer()
    ],
    wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),  # NOT LoggerFactory()!
    cache_logger_on_first_use=True
)

logger = structlog.get_logger()
```

**Common Mistake**: Using `structlog.stdlib.LoggerFactory()` will cause silent logging failures. Logger calls execute successfully but produce no output because Python's logging module requires handlers to be configured. Always use `PrintLoggerFactory()` for containerized applications.

---

## IRIS Vector Parameter Limitation

### The Problem

**IRIS CANNOT handle vector data as SQL parameters via external execution paths.** This affects:
- PostgreSQL wire protocol clients (psycopg, asyncpg, JDBC, etc.)
- Any external DBAPI connection
- SQL string execution in general

**Why it happens**:
- IRIS's `TO_VECTOR(?)` function expects vector literals in SQL text
- IRIS parameter binding (via `?` placeholders) cannot serialize/deserialize vector data
- Works only with `iris.sql.exec()` internal parameter binding

### The Solution

**Use `iris.sql.exec()` directly in embedded Python:**

```python
import iris
import struct
import base64
import random

# Generate vector
vec = [random.gauss(0, 1) for _ in range(1024)]
norm = sum(x*x for x in vec) ** 0.5
vec = [x/norm for x in vec]

# Option 1: Base64 format (compact)
vec_bytes = struct.pack('1024f', *vec)
vec_base64 = 'base64:' + base64.b64encode(vec_bytes).decode('ascii')

result = iris.sql.exec(
    "SELECT TOP 5 id FROM vectors ORDER BY VECTOR_COSINE(vec, TO_VECTOR(?, FLOAT))",
    vec_base64
)

# Option 2: JSON array format
vec_json = '[' + ','.join(str(v) for v in vec) + ']'

result = iris.sql.exec(
    "SELECT TOP 5 id FROM vectors ORDER BY VECTOR_COSINE(vec, TO_VECTOR(?, FLOAT))",
    vec_json
)

# Both formats work with iris.sql.exec()
# Performance: 40.6ms P95 latency (proven in production)
```

### What Doesn't Work

```python
# ❌ External connection using IRIS native protocol
import iris
conn = iris.connect('localhost', 1972, 'USER', '_SYSTEM', 'SYS')  # Protocol matters, not port
cursor = conn.cursor()

# This will FAIL for vectors >256 dimensions
cursor.execute(
    "SELECT id FROM vectors ORDER BY VECTOR_COSINE(vec, TO_VECTOR(?, FLOAT))",
    (vec_base64,)
)
# Error: SQLCODE=-52 (IRIS native protocol cannot bind vector parameter)
```

### Production Recommendation

**For vector similarity search**, you have two working options:

**Option 1: PostgreSQL Clients → PGWire Server** (Recommended for external applications)
```python
# ✅ Production pattern: Client connects to PGWire server
import psycopg

# Connect to PGWire server (runs in embedded Python)
conn = psycopg.connect(host='pgwire-server', port=5432, dbname='USER')
cur = conn.cursor()

# PGWire server handles iris.sql.exec() translation internally
vec_base64 = "base64:ABC123..."  # Any size vector works
cur.execute(
    "SELECT id, content FROM documents ORDER BY VECTOR_COSINE(embedding, TO_VECTOR(%s, FLOAT)) LIMIT 5",
    (vec_base64,)
)
results = cur.fetchall()
```

**Option 2: Direct `iris.sql.exec()`** (For code running inside IRIS container)
```python
# ✅ Production pattern: Direct embedded Python
import iris

def vector_search(query_vector: list, limit: int = 5):
    """Vector similarity search via iris.sql.exec()"""
    import struct, base64
    vec_bytes = struct.pack(f'{len(query_vector)}f', *query_vector)
    vec_b64 = 'base64:' + base64.b64encode(vec_bytes).decode('ascii')

    result = iris.sql.exec(
        f"""
        SELECT TOP {limit} id, content,
               VECTOR_COSINE(embedding, TO_VECTOR(?, FLOAT)) as similarity
        FROM documents
        ORDER BY similarity DESC
        """,
        vec_b64
    )
    return [(row[0], row[1], row[2]) for row in result]
```

**Key Difference**:
- **PGWire**: External clients (any PostgreSQL-compatible driver) connect via wire protocol
- **Direct**: Code must run inside IRIS container with embedded Python

Both work because they use `iris.sql.exec()` as the execution layer.

---

## Troubleshooting

### Server Won't Start

**Symptom**: `ModuleNotFoundError: No module named 'iris'`

**Cause**: Running via system python instead of irispython.

**Fix**:
```bash
# Check which Python is being used
docker exec your-container ps aux | grep python

# Should show: /usr/irissys/bin/irispython (irispython ✅)
# NOT: /usr/bin/python3 (system python ❌)

# Fix startup script to use irispython
exec /usr/irissys/bin/irispython -m your_server_module
```

### Code Changes Not Taking Effect

**Symptom**: Updated code doesn't run after docker cp.

**Cause**: Python bytecode cache (`.pyc` files) is stale.

**Fix**:
```bash
# Clear ALL Python cache
docker exec your-container bash -c "
    find /app -name '*.pyc' -delete && \
    find /app -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
"

# Restart container
docker restart your-container
```

### IRIS "CallIn" Errors

**Symptom**: `<PARAMETER> error: 'CallIn' is not valid`

**Cause**: CallIn service not enabled in merge.cpf.

**Fix**:
```ini
# Add to merge.cpf
[Actions]
ModifyService:Name=%Service_CallIn,Enabled=1,AutheEnabled=48
```

### Port Already in Use

**Symptom**: `address already in use` when starting server.

**Cause**: Previous server process still running.

**Fix**:
```bash
# Find and kill process
docker exec your-container ps aux | grep python
docker exec your-container kill <PID>

# Or restart container
docker restart your-container
```

### Vector Queries Fail

**Symptom**: `SQLCODE=-52` for vector similarity queries.

**Cause**: Using external execution path (wire protocol) instead of `iris.sql.exec()`.

**Fix**: See [IRIS Vector Parameter Limitation](#iris-vector-parameter-limitation) section.

```python
# ❌ DON'T: Use wire protocol for vectors
cur.execute("SELECT ... ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s))", (vec,))

# ✅ DO: Use iris.sql.exec() directly
result = iris.sql.exec("SELECT ... ORDER BY VECTOR_COSINE(vec, TO_VECTOR(?, FLOAT))", vec_base64)
```

### Logging Not Appearing

**Symptom**: Server runs but no logs appear. `logger.info()` calls execute without errors but produce no output.

**Cause**: Wrong structlog configuration - `LoggerFactory()` requires Python logging handlers.

**Evidence**:
```python
# Check logger type
logger = structlog.get_logger()
print(f"Logger: {logger}")  # Shows BoundLoggerLazyProxy
logger.info("Test")  # No output!
```

**Fix**:
```python
# ❌ WRONG: LoggerFactory() needs handlers
structlog.configure(
    logger_factory=structlog.stdlib.LoggerFactory(),  # Silent failures!
    ...
)

# ✅ CORRECT: PrintLoggerFactory() writes to stdout
structlog.configure(
    logger_factory=structlog.PrintLoggerFactory(),  # Logs appear!
    ...
)
```

**How to Verify**:
```bash
# Add test logging right after configuration
logger = structlog.get_logger()
logger.info("🔧 TEST: Logging is working")

# If you see this in container logs, structlog is configured correctly
# If you don't see it, you're using LoggerFactory() without handlers
```

---

## Production Checklist

### Pre-Deployment

- [ ] merge.cpf configured with CallIn service enabled
- [ ] Startup script uses `/usr/irissys/bin/irispython`
- [ ] All dependencies installed via `irispython -m pip`
- [ ] Health check configured
- [ ] Logging configured (structured logs)
- [ ] Error handling and graceful shutdown implemented

### Deployment

- [ ] Container build successful
- [ ] Server starts without errors
- [ ] Health check passing
- [ ] Logs flowing correctly
- [ ] Python cache cleared after code updates

### Post-Deployment

- [ ] Monitor server logs for errors
- [ ] Verify query performance (especially vectors)
- [ ] Check memory usage (IRIS process)
- [ ] Set up alerts for server downtime

### Vector Queries (if applicable)

- [ ] Using PGWire server OR direct `iris.sql.exec()` for vector operations
- [ ] NOT using external connection via IRIS native protocol
- [ ] Base64 or JSON array format for vectors
- [ ] Performance validated (<50ms P95 for HNSW queries)
- [ ] Error handling for vector parameter issues

---

## References

### Official Documentation

- [IRIS Embedded Python](https://docs.intersystems.com/iris20252/csp/docbook/DocBook.UI.Page.cls?KEY=GEPYTHON)
- [Flexible Python Runtime](https://docs.intersystems.com/iris20252/csp/docbook/DocBook.UI.Page.cls?KEY=GEPYTHON_flexible)
- [IRIS Docker Images](https://docs.intersystems.com/irislatest/csp/docbook/DocBook.UI.Page.cls?KEY=ADOCK)
- [IRIS Vector Search](https://docs.intersystems.com/iris20252/csp/docbook/Doc.View.cls?KEY=GSQL_vecsearch)

### Community Resources

- [intersystems-community/iris-embedded-python-template](https://github.com/intersystems-community/iris-embedded-python-template) (Official template)
- [caretdev/sqlalchemy-iris](https://github.com/caretdev/sqlalchemy-iris) (Production SQLAlchemy patterns)

### Project-Specific

- `docs/E2E_FINDINGS.md` - Vector parameter limitation discovery
- `docs/HNSW_INVESTIGATION.md` - HNSW index performance analysis
- `.specify/memory/constitution.md` - Principle VI (Vector Performance Requirements)

---

## Conclusion

Embedded Python in IRIS containers provides a powerful platform for database-adjacent services, but requires careful attention to:

1. **Execution context**: Always use `irispython`, never system python
2. **Cache management**: Clear Python bytecode cache when deploying updates
3. **Vector support**: Use PGWire server (for external clients) OR direct `iris.sql.exec()` (for embedded code)
4. **Lifecycle management**: Proper startup scripts, health checks, and graceful shutdown

**Key Takeaway**: For vector similarity search in production, you have **two viable options**:
- **PGWire Server**: External PostgreSQL clients connect via wire protocol (port 5432); PGWire translates to `iris.sql.exec()` internally
- **Direct `iris.sql.exec()`**: Code running inside IRIS container uses embedded Python

**What Doesn't Work**: External connections using IRIS's native wire protocol cannot handle production-sized vector parameters due to IRIS platform limitations. This is why PGWire server runs in embedded Python - to bridge this gap.

---

**Generated from**: iris-pgwire project
**Last Updated**: 2025-10-02
**Status**: Production-ready patterns validated

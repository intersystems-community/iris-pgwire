# DBAPI Backend Troubleshooting Guide

## Overview

The iris-pgwire DBAPI backend provides external connection pooling for IRIS databases. This guide covers common issues, configuration, and performance optimization.

## Architecture

```
PostgreSQL Client → PGWire Server → Connection Pool → intersystems-irispython → IRIS
                                    (asyncio.Queue)
```

## Configuration

### Backend Selection

```yaml
# backend_config.yml
backend_type: dbapi           # Options: 'dbapi' or 'embedded'
iris_host: localhost
iris_port: 1972
iris_username: _SYSTEM
iris_password: SYS
iris_namespace: USER
pool_size: 50                 # Base connection pool size
pool_max_overflow: 20         # Additional overflow connections
pool_timeout: 30.0            # Connection acquisition timeout (seconds)
pool_recycle: 3600            # Recycle connections after 1 hour
```

### Environment Variables

```bash
# DBAPI Backend Configuration
export BACKEND_TYPE=dbapi
export IRIS_HOST=localhost
export IRIS_PORT=1972
export IRIS_USERNAME=_SYSTEM
export IRIS_PASSWORD=SYS
export IRIS_NAMESPACE=USER
export POOL_SIZE=50
export POOL_MAX_OVERFLOW=20
export POOL_TIMEOUT=30.0
export POOL_RECYCLE=3600
```

## Common Issues

### 1. Connection Pool Exhaustion

**Symptom**: `asyncio.TimeoutError: Connection pool timeout after 30.0s`

**Cause**: All 70 connections (50 base + 20 overflow) in use.

**Solution**:
```yaml
# Increase pool size
pool_size: 100
pool_max_overflow: 50

# Or reduce timeout for faster failure
pool_timeout: 10.0
```

**Best Practice**: Monitor connection usage via health checks:
```python
from iris_pgwire.health_checker import HealthChecker

health = HealthChecker(connection_pool)
status = await health.check_connection_pool()
print(f"Available: {status['available_connections']}/{status['total_connections']}")
```

### 2. Connection Recycling Issues

**Symptom**: Stale connections causing query failures

**Cause**: Connections older than `pool_recycle` seconds.

**Solution**:
```yaml
# Reduce recycle time for more aggressive cleanup
pool_recycle: 1800  # 30 minutes instead of 1 hour
```

**Diagnostic**:
```python
# Check connection age
from iris_pgwire.dbapi_connection_pool import IRISConnectionPool

pool = IRISConnectionPool(config)
for conn_id, conn in pool._connections.items():
    age = (datetime.now() - conn.created_at).total_seconds()
    print(f"Connection {conn_id}: {age:.1f}s old (recycle at {config.pool_recycle}s)")
```

### 3. IRIS Restart Handling

**Symptom**: Connections fail after IRIS restart

**Cause**: Pool contains stale connections to stopped instance.

**Solution**: Automatic exponential backoff reconnection:
- 10 reconnection attempts
- Exponential delay: 2^n seconds (1s, 2s, 4s, 8s, ... max 1024s)
- All connections recycled on successful reconnect

**Manual Recovery**:
```python
from iris_pgwire.health_checker import HealthChecker

health = HealthChecker(connection_pool)
success = await health.handle_iris_restart()
if success:
    print("✅ Reconnection successful")
else:
    print("❌ Reconnection failed after 10 attempts")
```

### 4. Connection Leak Detection

**Symptom**: Pool size grows unexpectedly, connections not released

**Cause**: Missing `pool.release()` calls in error paths.

**Solution**: Always use try/finally:
```python
# CORRECT
conn = await pool.acquire()
try:
    result = await execute_query(conn)
    return result
finally:
    await pool.release(conn)

# INCORRECT - connection leaked on exception
conn = await pool.acquire()
result = await execute_query(conn)  # Exception → leak
await pool.release(conn)
```

### 5. Vector Query Performance

**Symptom**: Vector queries slower than expected

**Cause**: VECTOR type displayed as VARCHAR in INFORMATION_SCHEMA via DBAPI.

**Solution**: Use embedded backend for true VECTOR type handling:
```yaml
# Switch to embedded backend
backend_type: embedded
iris_namespace: USER
```

**Workaround**: Verify vector functions work despite VARCHAR display:
```sql
-- This still works correctly in DBAPI backend
SELECT VECTOR_COSINE(
    TO_VECTOR('[1.0,0.0,0.0]', DECIMAL),
    embedding
) AS similarity
FROM vectors
ORDER BY similarity DESC
LIMIT 10;
```

## Performance Tuning

### Connection Pool Sizing

**Formula**: `pool_size + pool_max_overflow <= 200` (IRIS connection limit)

**Recommendation**:
- **Low Load** (< 10 concurrent queries): `pool_size=10, overflow=5`
- **Medium Load** (10-50 queries): `pool_size=50, overflow=20` (default)
- **High Load** (50-100 queries): `pool_size=100, overflow=50`
- **Very High Load** (100+ queries): Use embedded backend

### Connection Acquisition Latency

**Constitutional SLA**: <1ms connection acquisition

**Measurement**:
```python
import time
from iris_pgwire.dbapi_connection_pool import IRISConnectionPool

pool = IRISConnectionPool(config)

start = time.perf_counter()
conn = await pool.acquire()
latency_ms = (time.perf_counter() - start) * 1000
await pool.release(conn)

print(f"Connection acquisition: {latency_ms:.2f}ms")
# Target: <1ms
```

### Connection Recycling Strategy

**Default**: 3600s (1 hour)

**Aggressive** (for unstable networks):
```yaml
pool_recycle: 600  # 10 minutes
```

**Conservative** (for stable networks):
```yaml
pool_recycle: 7200  # 2 hours
```

## Health Monitoring

### Connection Pool Health Check

```python
from iris_pgwire.health_checker import HealthChecker

health = HealthChecker(connection_pool)

# Check pool status
pool_status = await health.check_connection_pool()
print(f"""
Pool Health:
  Total connections: {pool_status['total_connections']}
  Available: {pool_status['available_connections']}
  In use: {pool_status['in_use_connections']}
  Utilization: {pool_status['utilization_percent']:.1f}%
""")

# Check IRIS connectivity
iris_status = await health.check_iris_health()
if iris_status['healthy']:
    print(f"✅ IRIS responding (latency: {iris_status['latency_ms']:.2f}ms)")
else:
    print(f"❌ IRIS unavailable: {iris_status['error']}")
```

### Exponential Backoff Reconnection

```python
# Automatically triggered on connection failures
# Manual invocation:
success = await health.handle_iris_restart()

# Reconnection attempts:
# Attempt 1: delay 1s
# Attempt 2: delay 2s
# Attempt 3: delay 4s
# Attempt 4: delay 8s
# Attempt 5: delay 16s
# Attempt 6: delay 32s
# Attempt 7: delay 64s
# Attempt 8: delay 128s
# Attempt 9: delay 256s
# Attempt 10: delay 512s
# Max delay: 1024s
```

## Observability

### Structured Logging with OTEL Context

```python
import structlog

logger = structlog.get_logger()

# Logs automatically include trace_id and span_id
logger.info("connection_acquired",
    connection_id=conn.connection_id,
    pool_size=pool.size,
    available=pool.available
)

# Output:
# {"event": "connection_acquired", "trace_id": "abc123...", "span_id": "def456..."}
```

### IRIS Log Integration

```python
from iris_pgwire.iris_log_handler import setup_iris_logging

# Setup IRIS message.log integration
setup_iris_logging()

# Logs now appear in IRIS messages.log
logger.info("PGWire server started")
# → /usr/irissys/mgr/messages.log
```

## Migration Strategies

### DBAPI → Embedded Backend Migration

**When to Migrate**:
- Running inside IRIS container
- Need maximum performance (no network overhead)
- Want true VECTOR type handling
- Deploying via IPM package

**Migration Steps**:
1. Update configuration:
```yaml
# OLD: DBAPI
backend_type: dbapi
iris_host: localhost
iris_port: 1972
iris_username: _SYSTEM
iris_password: SYS

# NEW: Embedded
backend_type: embedded
iris_namespace: USER
```

2. Update startup:
```bash
# OLD: External Python
python -m iris_pgwire.server

# NEW: Inside IRIS
irispython -m iris_pgwire.server
```

3. Test vector queries:
```sql
-- Verify VECTOR type (not VARCHAR)
SELECT DATA_TYPE
FROM INFORMATION_SCHEMA.COLUMNS
WHERE TABLE_NAME = 'vectors' AND COLUMN_NAME = 'embedding';
-- Should show: VECTOR(DECIMAL, 1536)
```

## Benchmarking

### Connection Pool Performance

```bash
# Run connection pool benchmark
python benchmarks/test_connection_pool.py

# Expected results:
# Connection acquisition: <1ms (SLA)
# Pool size: 50+20
# Sustained throughput: 1000+ qps
```

### Vector Query Performance

```bash
# Run vector benchmark with DBAPI backend
python benchmarks/test_vector_performance.py --backend dbapi

# Compare with embedded backend
python benchmarks/test_vector_performance.py --backend embedded
```

## Debugging Tips

### Enable Debug Logging

```python
import logging

logging.basicConfig(level=logging.DEBUG)

# Detailed connection pool logs
logger = logging.getLogger('iris_pgwire.dbapi_connection_pool')
logger.setLevel(logging.DEBUG)
```

### Connection Pool State Inspection

```python
from iris_pgwire.dbapi_connection_pool import IRISConnectionPool

pool = IRISConnectionPool(config)

# Dump pool state
print(f"Pool size: {len(pool._connections)}")
print(f"Queue size: {pool._pool.qsize()}")
print(f"Configuration: {pool.config}")

# List all connections
for conn_id, conn in pool._connections.items():
    print(f"  {conn_id}: in_use={conn.in_use}, age={conn.age_seconds():.1f}s")
```

### Trace Individual Queries

```python
import time
import structlog

logger = structlog.get_logger()

async def debug_query(sql: str):
    start = time.perf_counter()

    # Acquire connection
    conn = await pool.acquire()
    acquire_ms = (time.perf_counter() - start) * 1000
    logger.debug("connection_acquired", latency_ms=acquire_ms)

    try:
        # Execute query
        query_start = time.perf_counter()
        result = await conn.execute(sql)
        query_ms = (time.perf_counter() - query_start) * 1000
        logger.debug("query_executed", latency_ms=query_ms, row_count=len(result))

        return result
    finally:
        await pool.release(conn)
        total_ms = (time.perf_counter() - start) * 1000
        logger.debug("query_complete", total_latency_ms=total_ms)
```

## FAQ

### Q: Should I use DBAPI or Embedded backend?

**Use DBAPI when**:
- Running PGWire server outside IRIS container
- Need connection pooling (multiple concurrent clients)
- Testing/development environment
- Multi-IRIS instance deployments

**Use Embedded when**:
- Running inside IRIS via `irispython`
- Maximum performance required
- Deploying via IPM package
- Need true VECTOR type handling

### Q: How many connections should I configure?

**Formula**: `pool_size + pool_max_overflow <= IRIS max connections`

**Default IRIS limit**: 200 connections
**Recommended**: 50 base + 20 overflow (70 total)
**Maximum safe**: 100 base + 50 overflow (150 total)

### Q: What happens when pool is exhausted?

After `pool_timeout` seconds (default 30s), `asyncio.TimeoutError` is raised. Increase pool size or reduce timeout.

### Q: How do I monitor connection pool health?

Use `HealthChecker.check_connection_pool()` for real-time metrics:
```python
health = HealthChecker(pool)
status = await health.check_connection_pool()
# Returns: total_connections, available_connections, in_use_connections, utilization_percent
```

### Q: What's the overhead of DBAPI vs Embedded?

**DBAPI overhead**:
- Connection acquisition: <1ms (constitutional SLA)
- Network latency: ~0.5-2ms per query
- Total overhead: ~1-3ms per query

**Embedded overhead**: Near-zero (direct iris.sql.exec())

### Q: How do I handle IRIS restarts?

Automatic exponential backoff reconnection (10 attempts, 2^n seconds). Monitor with:
```python
health = HealthChecker(pool)
success = await health.handle_iris_restart()
```

## References

- **Backend Selector**: `/Users/tdyar/ws/iris-pgwire/src/iris_pgwire/backend_selector.py`
- **Connection Pool**: `/Users/tdyar/ws/iris-pgwire/src/iris_pgwire/dbapi_connection_pool.py`
- **DBAPI Executor**: `/Users/tdyar/ws/iris-pgwire/src/iris_pgwire/dbapi_executor.py`
- **Health Checker**: `/Users/tdyar/ws/iris-pgwire/src/iris_pgwire/health_checker.py`
- **Feature Spec**: `/Users/tdyar/ws/iris-pgwire/specs/018-add-dbapi-option/spec.md`
- **Quickstart Guide**: `/Users/tdyar/ws/iris-pgwire/specs/018-add-dbapi-option/quickstart.md`

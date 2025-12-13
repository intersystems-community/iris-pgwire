# Quickstart: DBAPI Backend with IPM Installation

**Feature**: 018-add-dbapi-option
**Purpose**: Validate end-to-end installation and operation of iris-pgwire with DBAPI backend via IPM

## Prerequisites

- ✅ IRIS 2024.1+ instance running
- ✅ IPM (ZPM) v0.7.2+ installed
- ✅ IRIS CallIn service enabled (merge.cpf applied)
- ✅ IRIS OTEL enabled (for observability)
- ✅ PostgreSQL client (psql) installed

## Quickstart Workflow (15 minutes)

### Step 1: Install iris-pgwire via IPM (2 min)

```objectscript
// From IRIS Terminal
USER> zpm "install iris-pgwire"

// Expected output:
[iris-pgwire] Installing Python dependencies...
[iris-pgwire] Dependencies installed: intersystems-irispython, opentelemetry-api, ...
[iris-pgwire] Starting PGWire server on port 5432...
[iris-pgwire] Server started (log: /tmp/pgwire.log)
iris-pgwire installed successfully!
```

**Validation**:
```bash
# Verify server is listening
netstat -an | grep 5432
# Expected: tcp4  0  0  *.5432  *.*  LISTEN
```

---

### Step 2: Configure DBAPI Backend (1 min)

```bash
# Option A: Environment variables
export PGWIRE_BACKEND_TYPE=dbapi
export IRIS_HOSTNAME=localhost
export IRIS_PORT=1972
export IRIS_NAMESPACE=USER
export IRIS_USERNAME=_SYSTEM
export IRIS_PASSWORD=SYS

# Option B: config.yaml
cat > /usr/irissys/mgr/iris-pgwire/config.yaml <<EOF
backend:
  type: dbapi
iris:
  hostname: localhost
  port: 1972
  namespace: USER
  username: _SYSTEM
  password: SYS
connection_pool:
  size: 50
  max_overflow: 20
EOF
```

**Restart server** (if using config file):
```objectscript
USER> Do ##class(IrisPGWire.Service).Stop()
USER> Do ##class(IrisPGWire.Service).Start()
```

---

### Step 3: Verify PostgreSQL Connectivity (2 min)

```bash
# Connect with psql
psql -h localhost -p 5432 -d USER

# Test simple query
USER=> SELECT 1 AS test;
 test
------
    1
(1 row)

# Test metadata query
USER=> SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES LIMIT 5;
```

**Expected**: Connection succeeds, queries return results

---

### Step 4: Create Vector Table with Large Dimensions (3 min)

```sql
-- Create table with 1024-dimensional vectors
CREATE TABLE embeddings_1024 (
    id INTEGER PRIMARY KEY,
    doc_name VARCHAR(255),
    embedding VECTOR(DECIMAL, 1024)
);

-- Insert test data
INSERT INTO embeddings_1024 (id, doc_name, embedding)
VALUES (1, 'document1', TO_VECTOR('[0.1,0.2,0.3,...]', 'DECIMAL'));
-- Repeat for 10-20 rows with different vectors

-- Verify insertion
SELECT COUNT(*) FROM embeddings_1024;
```

**Expected**: Table created, data inserted successfully

---

### Step 5: Execute Vector Similarity Query (3 min)

```sql
-- pgvector syntax (will be translated to IRIS VECTOR functions)
SELECT id, doc_name
FROM embeddings_1024
ORDER BY embedding <-> '[0.1,0.2,0.3,...]'::vector
LIMIT 5;
```

**Expected Output**:
```
 id | doc_name
----+-----------
  1 | document1
  3 | document3
  5 | document5
  2 | document2
  7 | document7
(5 rows)
```

**Validation**:
- Query executes without errors
- Results ordered by similarity
- Translation time <5ms (check logs)

---

### Step 6: Verify DBAPI Backend Usage (2 min)

```bash
# Check server logs
tail -f /tmp/pgwire.log

# Expected log entries:
# [INFO] Backend selected: DBAPI
# [INFO] Connection pool initialized: size=50, overflow=20
# [INFO] Query executed: translation_time_ms=2.3, backend=DBAPI
```

**Verify pool metrics**:
```sql
-- Check connection pool state (if monitoring endpoint exists)
-- curl http://localhost:5432/health
```

---

### Step 7: Benchmark Performance vs pgvector PostgreSQL (2 min)

```bash
# Run benchmark script
python benchmarks/compare_dbapi_vs_pgvector.py

# Expected output:
# DBAPI Backend (IRIS):     12.5ms avg, 80 QPS
# pgvector (PostgreSQL):    10.2ms avg, 98 QPS
# Performance ratio:        1.23x (within acceptable range)
```

**Success Criteria**:
- DBAPI performance comparable to pgvector (within 2× range)
- Translation overhead <5ms (constitutional SLA)
- No connection pool exhaustion errors

---

### Step 8: Test Connection Pooling Under Load (Optional, 3 min)

```bash
# Simulate 1000 concurrent connections
python -c "
import asyncio
import psycopg

async def concurrent_query(i):
    conn = await psycopg.AsyncConnection.connect(
        'host=localhost port=5432 dbname=USER'
    )
    async with conn.cursor() as cur:
        await cur.execute(f'SELECT {i} AS id')
        result = await cur.fetchone()
    await conn.close()
    return result

async def main():
    tasks = [concurrent_query(i) for i in range(1000)]
    results = await asyncio.gather(*tasks)
    print(f'Completed {len(results)} queries')

asyncio.run(main())
"
```

**Expected**: All 1000 queries complete successfully with 50-connection pool

---

## Troubleshooting

### Issue: Connection Refused

**Symptom**:
```
psql: error: connection to server at "localhost" (::1), port 5432 failed: Connection refused
```

**Resolution**:
```bash
# Check if server is running
ps aux | grep irispython | grep server

# Check logs
tail -100 /tmp/pgwire.log

# Restart server
iris session IRIS "Do ##class(IrisPGWire.Service).Start()"
```

---

### Issue: DBAPI Backend Not Selected

**Symptom**:
```
[WARN] Backend selected: Embedded (expected DBAPI)
```

**Resolution**:
```bash
# Verify environment variables
echo $PGWIRE_BACKEND_TYPE  # Should output: dbapi

# Or check config file
cat /usr/irissys/mgr/iris-pgwire/config.yaml

# Restart after fixing configuration
```

---

### Issue: Connection Pool Exhausted

**Symptom**:
```
TimeoutError: Connection pool exhausted (timeout=30s)
```

**Resolution**:
```bash
# Increase pool size
export PGWIRE_POOL_SIZE=100
export PGWIRE_POOL_MAX_OVERFLOW=50

# Or reduce concurrent connections
```

---

### Issue: Vector Query Fails

**Symptom**:
```
ERROR: function VECTOR_COSINE does not exist
```

**Resolution**:
```sql
-- Verify IRIS version supports VECTOR functions
SELECT $ZVERSION;  -- Must be 2024.1+

-- Check if vector license enabled
-- (Contact InterSystems support if needed)
```

---

## Validation Checklist

- [ ] IPM installation completes without errors
- [ ] Python dependencies installed via irispip
- [ ] PGWire server starts and listens on port 5432
- [ ] DBAPI backend selected (check logs)
- [ ] Connection pool initialized (size=50)
- [ ] psql connects successfully
- [ ] Simple queries execute (`SELECT 1`)
- [ ] Vector table created with 1024 dimensions
- [ ] Vector similarity queries return results
- [ ] Translation time <5ms (constitutional SLA)
- [ ] Performance comparable to pgvector PostgreSQL
- [ ] 1000 concurrent connections handled (optional)
- [ ] OTEL metrics exported (check OTLP endpoint)

---

## Next Steps

After quickstart validation:

1. **Production Configuration**:
   - Set production credentials (not _SYSTEM/SYS)
   - Configure TLS/SSL encryption
   - Set up OTEL collector endpoint
   - Configure connection pool for expected load

2. **Monitoring Setup**:
   - Deploy OTEL collector (Jaeger/Prometheus)
   - Set up dashboards for pool metrics
   - Configure alerts for SLA violations

3. **Performance Tuning**:
   - Benchmark with production-scale data (≥100K vectors)
   - Create HNSW indexes: `CREATE INDEX idx ON table(vec_col) AS HNSW(Distance='Cosine')`
   - Validate index usage with EXPLAIN plans

4. **Integration Testing**:
   - Test with real application clients (psycopg, JDBC, etc.)
   - Validate authentication (SCRAM-SHA-256)
   - Test connection failover scenarios

---

**Quickstart Status**: ✅ Complete - Ready for implementation validation

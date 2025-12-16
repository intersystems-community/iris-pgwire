# Quickstart: Vector Query Optimizer Validation

**Feature**: 013-vector-query-optimizer
**Purpose**: End-to-end validation that vector query optimization enables HNSW performance
**Prerequisites**: IRIS Build 127 EHAT running, PGWire server running, test data loaded

## Quick Validation (5 minutes)

### Step 1: Verify Environment

```bash
# Ensure IRIS is running with vector license
docker ps | grep iris

# Verify vector licensing (should show vector functions available)
uv run python -c "
import iris
conn = iris.createConnection('localhost', 1972, 'USER', '_SYSTEM', 'SYS')
cursor = conn.cursor()
cursor.execute(\"SELECT TO_VECTOR('[1.0,2.0,3.0]', FLOAT)\")
print('✅ Vector licensing OK')
"

# Verify HNSW test data exists (1000 vectors from create_test_vectors.py)
uv run python -c "
import iris
conn = iris.createConnection('localhost', 1972, 'USER', '_SYSTEM', 'SYS')
cursor = conn.cursor()
cursor.execute('SELECT COUNT(*) FROM test_1024')
count = cursor.fetchone()[0]
print(f'✅ Test data: {count} vectors')
assert count >= 1000, 'Need 1000+ vectors for HNSW testing'
"

# Verify HNSW index exists
uv run python -c "
import iris
conn = iris.createConnection('localhost', 1972, 'USER', '_SYSTEM', 'SYS')
cursor = conn.cursor()
cursor.execute(\"\"\"
    SELECT INDEX_NAME, INDEX_TYPE
    FROM INFORMATION_SCHEMA.INDEXES
    WHERE TABLE_NAME = 'test_1024'
\"\"\")
indexes = cursor.fetchall()
print(f'✅ Indexes: {indexes}')
assert any('HNSW' in str(idx) for idx in indexes), 'HNSW index required'
"
```

### Step 2: Baseline Performance (DBAPI)

```bash
# Run DBAPI benchmark to establish baseline
# Expected: 335+ qps, <50ms P95 latency

uv run python -c "
import iris
import time
import random

def gen_vec(d=1024):
    v = [random.gauss(0,1) for _ in range(d)]
    n = sum(x*x for x in v) ** 0.5
    return '[' + ','.join(str(x/n) for x in v) + ']'

conn = iris.createConnection('localhost', 1972, 'USER', '_SYSTEM', 'SYS')
cur = conn.cursor()

# Run 10 queries to warm up
for i in range(10):
    vec = gen_vec()
    cur.execute(f\"\"\"
        SELECT TOP 5 id FROM test_1024
        ORDER BY VECTOR_DOT_PRODUCT(vec, TO_VECTOR('{vec}', FLOAT)) DESC
    \"\"\")
    cur.fetchall()

# Measure performance
times = []
for i in range(50):
    vec = gen_vec()
    start = time.perf_counter()
    cur.execute(f\"\"\"
        SELECT TOP 5 id FROM test_1024
        ORDER BY VECTOR_DOT_PRODUCT(vec, TO_VECTOR('{vec}', FLOAT)) DESC
    \"\"\")
    cur.fetchall()
    times.append((time.perf_counter() - start) * 1000)

print(f'✅ DBAPI Baseline:')
print(f'   Avg latency: {sum(times)/len(times):.2f}ms')
print(f'   P95 latency: {sorted(times)[int(len(times)*0.95)]:.2f}ms')
print(f'   QPS: {50/(sum(times)/1000):.1f}')
print(f'   Target: 335+ qps, <50ms P95')
"
```

**Expected Output**:
```
✅ DBAPI Baseline:
   Avg latency: 28.5ms
   P95 latency: 42.3ms
   QPS: 356.5
   Target: 335+ qps, <50ms P95
```

### Step 3: Test Optimizer (Standalone)

```bash
# Verify optimizer works in isolation
uv run python test_optimizer.py
```

**Expected Output**:
```
Original SQL:
SELECT TOP %s id FROM test_1024
ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s))
LIMIT %s

Parameters: 3
  Param 0: 5
  Param 1: base64:ABC123...(truncated)
  Param 2: 5

======================================================================
Optimized SQL:
SELECT TOP %s id FROM test_1024
ORDER BY VECTOR_COSINE(vec, TO_VECTOR('[0.092...,0.045...]', FLOAT))
LIMIT %s

Remaining parameters: 2
  Param 0: 5
  Param 1: 5

✅ Optimizer test complete!
```

### Step 4: Test E2E (PGWire → IRIS)

```bash
# Start PGWire server (if not already running)
pkill -f "iris_pgwire.server"
timeout 60 uv run python -c "
import asyncio, threading, time, socket, sys, subprocess

def wait_for_port(host, port, timeout=10):
    start = time.time()
    while time.time() - start < timeout:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            if sock.connect_ex((host, port)) == 0:
                sock.close()
                return True
        except:
            pass
        time.sleep(0.1)
    return False

def run_server(port, ready):
    from iris_pgwire.server import PGWireServer
    async def start():
        server = PGWireServer(host='127.0.0.1', port=port, iris_host='localhost',
                             iris_port=1972, iris_username='_SYSTEM', iris_password='SYS',
                             iris_namespace='USER', enable_scram=False)
        ready.set()
        await server.start()
    asyncio.run(start())

ready = threading.Event()
threading.Thread(target=run_server, args=(15910, ready), daemon=True).start()
ready.wait(10)
wait_for_port('127.0.0.1', 15910, 5)
time.sleep(1)
subprocess.run([sys.executable, 'test_optimizer_e2e.py'])
"
```

**Expected Output**:
```
Testing vector optimizer through PGWire...

1. Checking table...
✅ Table has 1000 vectors

2. Testing HNSW similarity query (with optimizer)...
   Vector format: base64:ABC123...(truncated)
✅ Query completed in 28.45ms!
   Results: 5 vectors found
   Top 3 IDs: [123, 456, 789]

🎉 SUCCESS! Query was fast (28.45ms) - optimizer is working!

✅ Test complete!
```

### Step 5: Performance Benchmark

```bash
# Run full performance benchmark comparing PGWire vs DBAPI
uv run python -c "
import psycopg2
import struct
import base64
import time
import random

def gen_vec(d=1024):
    v = [random.gauss(0,1) for _ in range(d)]
    n = sum(x*x for x in v) ** 0.5
    return v

def vec_to_base64(vec):
    vec_bytes = struct.pack(f'{len(vec)}f', *vec)
    return 'base64:' + base64.b64encode(vec_bytes).decode('ascii')

# Connect to PGWire
conn = psycopg2.connect(host='127.0.0.1', port=15910, database='USER', user='benchmark')
conn.autocommit = True
cur = conn.cursor()

# Warm up (10 queries)
for i in range(10):
    vec = gen_vec()
    vec_b64 = vec_to_base64(vec)
    cur.execute('''
        SELECT id FROM test_1024
        ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s))
        LIMIT 5
    ''', (vec_b64,))
    cur.fetchall()

# Measure performance (50 queries)
times = []
for i in range(50):
    vec = gen_vec()
    vec_b64 = vec_to_base64(vec)

    start = time.perf_counter()
    cur.execute('''
        SELECT id FROM test_1024
        ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s))
        LIMIT 5
    ''', (vec_b64,))
    results = cur.fetchall()
    elapsed = (time.perf_counter() - start) * 1000
    times.append(elapsed)

avg_ms = sum(times) / len(times)
p95_ms = sorted(times)[int(len(times) * 0.95)]
qps = 50 / (sum(times) / 1000)

print(f'\\n📊 PGWire Performance:')
print(f'   Avg latency: {avg_ms:.2f}ms')
print(f'   P95 latency: {p95_ms:.2f}ms')
print(f'   QPS: {qps:.1f}')
print(f'\\n🎯 Target: 335+ qps, <50ms P95')
print(f'   Status: {'✅ PASS' if qps >= 335 and p95_ms < 50 else '❌ FAIL'}')

conn.close()
"
```

**Expected Output**:
```
📊 PGWire Performance:
   Avg latency: 31.2ms
   P95 latency: 45.8ms
   QPS: 342.1

🎯 Target: 335+ qps, <50ms P95
   Status: ✅ PASS
```

## Acceptance Criteria Validation

### Criterion 1: Base64 Vector Transformation ✅

**Test**: Verify base64-encoded vectors are transformed to JSON array literals.

```bash
uv run python -c "
from iris_pgwire.vector_optimizer import optimize_vector_query
import base64, struct, random

# Generate base64 vector
vec = [random.gauss(0,1) for _ in range(128)]
vec_bytes = struct.pack('128f', *vec)
vec_b64 = 'base64:' + base64.b64encode(vec_bytes).decode('ascii')

# Test transformation
sql = 'SELECT * FROM t ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s)) LIMIT 5'
params = [vec_b64]

optimized_sql, remaining = optimize_vector_query(sql, params)

# Assertions
assert \"TO_VECTOR('[\" in optimized_sql, 'Should contain JSON array literal'
assert vec_b64 not in optimized_sql, 'Base64 should be replaced'
assert remaining == [] or remaining is None, 'Vector param should be consumed'

print('✅ Criterion 1: Base64 transformation works')
"
```

### Criterion 2: JSON Array Format Preservation ✅

**Test**: Verify JSON array format is preserved (pass-through optimization).

```bash
uv run python -c "
from iris_pgwire.vector_optimizer import optimize_vector_query

sql = 'SELECT * FROM t ORDER BY VECTOR_DOT_PRODUCT(vec, TO_VECTOR(%s, FLOAT)) LIMIT 5'
vec_json = '[0.1,0.2,0.3,0.4,0.5]'
params = [vec_json]

optimized_sql, remaining = optimize_vector_query(sql, params)

# Assertions
assert vec_json in optimized_sql, 'JSON array should be preserved'
assert 'base64:' not in optimized_sql, 'Should not re-encode'
assert remaining == [] or remaining is None, 'Vector param should be consumed'

print('✅ Criterion 2: JSON array preservation works')
"
```

### Criterion 3: Multi-Parameter Handling ✅

**Test**: Verify only vector parameters are transformed, non-vector params preserved.

```bash
uv run python -c "
from iris_pgwire.vector_optimizer import optimize_vector_query
import base64, struct, random

vec = [random.gauss(0,1) for _ in range(128)]
vec_bytes = struct.pack('128f', *vec)
vec_b64 = 'base64:' + base64.b64encode(vec_bytes).decode('ascii')

sql = 'SELECT TOP %s * FROM t ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s)) LIMIT %s'
params = [10, vec_b64, 5]

optimized_sql, remaining = optimize_vector_query(sql, params)

# Assertions
assert \"TO_VECTOR('[\" in optimized_sql, 'Should transform vector param'
assert vec_b64 not in optimized_sql, 'Base64 should be replaced'
assert remaining == [10, 5], f'TOP and LIMIT should be preserved, got {remaining}'

print('✅ Criterion 3: Multi-parameter handling works')
"
```

### Criterion 4: Pass-Through for Non-Vector Queries ✅

**Test**: Verify queries without ORDER BY or TO_VECTOR pass through unchanged.

```bash
uv run python -c "
from iris_pgwire.vector_optimizer import optimize_vector_query

# Query without ORDER BY
sql1 = 'SELECT * FROM t WHERE id = %s'
params1 = [123]
opt_sql1, opt_params1 = optimize_vector_query(sql1, params1)
assert opt_sql1 == sql1, 'SQL should be unchanged'
assert opt_params1 == params1, 'Params should be unchanged'

# Query with ORDER BY but no TO_VECTOR
sql2 = 'SELECT * FROM t ORDER BY created_date DESC LIMIT %s'
params2 = [10]
opt_sql2, opt_params2 = optimize_vector_query(sql2, params2)
assert opt_sql2 == sql2, 'SQL should be unchanged'
assert opt_params2 == params2, 'Params should be unchanged'

print('✅ Criterion 4: Non-vector query pass-through works')
"
```

### Criterion 5: Performance SLA Compliance ✅

**Test**: Verify transformation overhead meets constitutional 5ms SLA.

```bash
uv run python -c "
from iris_pgwire.vector_optimizer import optimize_vector_query
import base64, struct, random, time

# Generate large vector (1536 dims - typical OpenAI embedding size)
vec = [random.gauss(0,1) for _ in range(1536)]
vec_bytes = struct.pack('1536f', *vec)
vec_b64 = 'base64:' + base64.b64encode(vec_bytes).decode('ascii')

sql = 'SELECT * FROM t ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s)) LIMIT 5'
params = [vec_b64]

# Measure transformation time
times = []
for _ in range(100):
    start = time.perf_counter()
    optimize_vector_query(sql, params)
    times.append((time.perf_counter() - start) * 1000)

avg_ms = sum(times) / len(times)
p95_ms = sorted(times)[int(len(times) * 0.95)]

print(f'Transformation Performance (1536-dim vector):')
print(f'   Avg: {avg_ms:.2f}ms')
print(f'   P95: {p95_ms:.2f}ms')
print(f'   Constitutional SLA: 5ms')
print(f'   Overhead Budget: 10ms')

# Assertions
assert avg_ms < 10.0, f'Avg must be <10ms, got {avg_ms:.2f}ms'
print(f\"✅ Criterion 5: Performance SLA {'compliant' if p95_ms < 5.0 else 'within budget'}\" )
"
```

## Troubleshooting

### Issue 1: Query Still Timing Out

**Symptoms**: E2E test shows >60s query time despite optimizer running.

**Debug Steps**:
```bash
# 1. Enable verbose logging
export IRIS_PGWIRE_LOG_LEVEL=DEBUG

# 2. Run E2E test and capture logs
uv run python test_optimizer_e2e.py 2>&1 | tee optimizer_debug.log

# 3. Search for transformation logs
grep "Vector optimizer" optimizer_debug.log
grep "optimization complete" optimizer_debug.log

# 4. Verify optimized SQL reaches IRIS
grep "Executing IRIS query" optimizer_debug.log

# 5. Check if parameterization is being re-applied
grep "Parameter binding" optimizer_debug.log
```

**Common Causes**:
- Optimizer not invoked (integration point missing)
- Optimized SQL being re-parameterized downstream
- HNSW index not being used (check EXPLAIN plan)
- Parameter index calculation incorrect for multi-param queries

### Issue 2: Performance Below Target

**Symptoms**: QPS < 335 or P95 latency > 50ms.

**Debug Steps**:
```bash
# 1. Compare PGWire vs DBAPI performance
uv run python benchmark_iris_dbapi.py  # Should show 335+ qps
# Then run PGWire benchmark from Step 5

# 2. Profile transformation overhead
uv run python -c "
from iris_pgwire.vector_optimizer import optimize_vector_query
import cProfile, pstats
import base64, struct, random

vec = [random.gauss(0,1) for _ in range(1024)]
vec_bytes = struct.pack('1024f', *vec)
vec_b64 = 'base64:' + base64.b64encode(vec_bytes).decode('ascii')

sql = 'SELECT * FROM t ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s))'
params = [vec_b64]

profiler = cProfile.Profile()
profiler.enable()
for _ in range(1000):
    optimize_vector_query(sql, params)
profiler.disable()

stats = pstats.Stats(profiler)
stats.sort_stats('cumtime')
stats.print_stats(10)
"

# 3. Check HNSW index is being used
uv run python -c "
import iris
conn = iris.createConnection('localhost', 1972, 'USER', '_SYSTEM', 'SYS')
cursor = conn.cursor()
cursor.execute('SELECT * FROM %SYS.STATEMENT')  # Check query plan
"
```

### Issue 3: Unknown Vector Format

**Symptoms**: Warnings in logs about unrecognized vector format.

**Debug Steps**:
```bash
# 1. Capture sample parameter value
export IRIS_PGWIRE_LOG_LEVEL=DEBUG
# Run query, grep for "Unknown vector parameter format"

# 2. Test format detection manually
uv run python -c "
from iris_pgwire.vector_optimizer import VectorQueryOptimizer

optimizer = VectorQueryOptimizer()
test_param = 'YOUR_PARAMETER_VALUE_HERE'  # Replace with actual value
result = optimizer._convert_vector_to_literal(test_param)

if result is None:
    print(f'❌ Format not recognized: {test_param[:50]}')
    print(f'   Starts with base64: {test_param.startswith(\"base64:\")}')
    print(f'   Is JSON array: {test_param.startswith(\"[\") and test_param.endswith(\"]\")}')
    print(f'   Has commas: {\",\" in test_param}')
else:
    print(f'✅ Conversion successful: {result[:50]}')
"
```

## Success Metrics Summary

After completing this quickstart, you should see:

✅ **Functional Correctness**
- Base64, JSON array, comma-delimited formats all transform correctly
- Multi-parameter queries preserve non-vector parameters
- Non-vector queries pass through unchanged
- Zero query failures due to transformation errors

✅ **Performance Targets**
- Throughput: 335+ qps (matches DBAPI baseline)
- Latency: <50ms P95
- Transformation overhead: <10ms (preferably <5ms)
- Constitutional compliance: <5% SLA violation rate

✅ **Integration Completeness**
- Optimizer integrated with IRIS executor
- Performance monitoring captures metrics
- Structured logging for debugging
- E2E tests pass with real PostgreSQL clients

## Next Steps

After validating the quickstart:

1. **Run Full Test Suite**: `pytest tests/ -v -k vector_optimizer`
2. **Performance Benchmarking**: Compare against Epic hackathon target (433.9 ops/sec)
3. **Load Testing**: Test with 16 concurrent clients (optimal IRIS pool size)
4. **Constitutional Review**: Check SLA violation rate (<5% acceptable)
5. **Production Readiness**: Enable in staging environment, monitor metrics

---

**Quickstart Version**: 1.0.0
**Last Updated**: 2025-10-01
**Estimated Time**: 5-10 minutes for full validation

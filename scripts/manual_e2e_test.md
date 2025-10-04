# Manual E2E Test Procedure (psycopg3)

**Estimated Time**: 15 minutes
**Purpose**: Validate vector query optimizer through full PostgreSQL wire protocol stack
**Client**: Uses **psycopg3** (server-side parameter binding) - NOT psycopg2

## Why psycopg3?

✅ **Server-side parameter binding** - Parameters sent separately from SQL (Extended Protocol)
✅ **No literal size limit** - Optimizer transforms parameters before IRIS execution
✅ **Production-ready** - Works with any vector size (1024+ dimensions)

❌ **NOT psycopg2** - Does client-side interpolation, limited to <256 dims

See `specs/013-vector-query-optimizer/CLIENT_COMPATIBILITY.md` for full client comparison.

## Prerequisites

✅ IRIS running on localhost:1972
✅ test_1024 table with 1000+ vectors and HNSW index
✅ Vector optimizer integrated into iris_executor.py
✅ **psycopg3 installed**: `uv pip install psycopg`

## Step 1: Start PGWire Server (Terminal 1)

```bash
cd /Users/tdyar/ws/iris-pgwire

# Set environment variables
export PGWIRE_HOST=127.0.0.1
export PGWIRE_PORT=15910
export IRIS_HOST=localhost
export IRIS_PORT=1972
export IRIS_USERNAME=_SYSTEM
export IRIS_PASSWORD=SYS
export IRIS_NAMESPACE=USER
export PGWIRE_DEBUG=true

# Start server
uv run python -m iris_pgwire.server
```

Expected output:
```
[info] Starting PGWire server on 127.0.0.1:15910
[info] IRIS connection test successful
[info] Vector optimization enabled (DP-444330 pattern)
```

## Step 2: Run E2E Tests with psycopg3 (Terminal 2)

```bash
cd /Users/tdyar/ws/iris-pgwire

# Ensure psycopg3 is installed
uv pip install psycopg

# Run E2E tests (now using psycopg3)
uv run pytest tests/integration/test_vector_optimizer_e2e.py -v -s

# Or run specific test
uv run pytest tests/integration/test_vector_optimizer_e2e.py::TestVectorOptimizerE2E::test_base64_vector_e2e -v -s
```

**Expected Output**:
```
tests/integration/test_vector_optimizer_e2e.py::TestVectorOptimizerE2E::test_base64_vector_e2e PASSED
✅ T009 PASS: Base64 vector query completed in XX.XXms (1024 dims - production size)

tests/integration/test_vector_optimizer_e2e.py::TestVectorOptimizerE2E::test_json_array_vector_e2e PASSED
✅ T010 PASS: JSON array query completed in XX.XXms

tests/integration/test_vector_optimizer_e2e.py::TestVectorOptimizerE2E::test_multi_parameter_e2e PASSED
✅ T011 PASS: Multi-parameter query completed in XX.XXms

tests/integration/test_vector_optimizer_e2e.py::TestVectorOptimizerE2E::test_non_vector_query_passthrough_e2e PASSED
✅ T012 PASS: Non-vector query passed through correctly
```

## Step 3: Manual psycopg3 Test (Alternative)

If pytest is having issues, test directly with **psycopg3** (not psycopg2):

```bash
uv run python -c "
import psycopg  # psycopg3 - server-side parameter binding
import struct
import base64
import random
import time

# Connect using psycopg3
conn = psycopg.connect(
    host='127.0.0.1',
    port=15910,
    dbname='USER',
    user='_SYSTEM',
    password='SYS',
    autocommit=True
)
print('✅ Connected to PGWire via psycopg3')

# Generate 1024-dim vector (production size)
vec = [random.gauss(0,1) for _ in range(1024)]
norm = sum(x*x for x in vec) ** 0.5
vec = [x/norm for x in vec]
vec_bytes = struct.pack('1024f', *vec)
vec_b64 = 'base64:' + base64.b64encode(vec_bytes).decode('ascii')

print(f'Vector size: {len(vec)} dimensions')
print(f'Base64 length: {len(vec_b64)} chars')

# Query with server-side parameter binding
cur = conn.cursor()
start = time.perf_counter()
cur.execute('''
    SELECT id FROM test_1024
    ORDER BY VECTOR_DOT_PRODUCT(vec, TO_VECTOR(%s, FLOAT)) DESC
    LIMIT 5
''', (vec_b64,))
results = cur.fetchall()
elapsed_ms = (time.perf_counter() - start) * 1000

print(f'✅ Query completed in {elapsed_ms:.2f}ms')
print(f'✅ Results: {len(results)} rows')
print(f'   IDs: {[r[0] for r in results]}')
print(f'✅ No IRIS literal size limit with psycopg3!')

conn.close()
"
```

## Step 4: Verify Optimizer Logs (Terminal 1)

Check PGWire server logs for optimizer invocation with **parameters** (not literals):

**Expected Log Output** (psycopg3 server-side binding):
```
DEBUG:iris_pgwire.vector_optimizer:Processing query with 1 parameters
DEBUG:iris_pgwire.vector_optimizer:Found TO_VECTOR pattern at position X
DEBUG:iris_pgwire.vector_optimizer:Decoding base64 vector...
DEBUG:iris_pgwire.vector_optimizer:Base64 decoded to 1024 floats, JSON length=XXXX
DEBUG:iris_pgwire.vector_optimizer:✅ SLA compliant: X.XXms < 5.0ms
INFO:iris_pgwire.vector_optimizer:Optimization complete: 1 params transformed, 0 remaining
INFO:iris_pgwire.iris_executor:[info] Vector optimization applied (external mode)
  optimized_params_preview="['[1.0,2.0,3.0,...]']"  # JSON array, NOT base64
```

**Key Difference from psycopg2**:
- psycopg3 sends `param_count=1` (parameters in Bind message)
- psycopg2 sends `param_count=0` (client-side interpolation)

## Success Criteria

✅ All 4 E2E tests pass
✅ Query latency <50ms (HNSW optimization working)
✅ Server logs show "Vector optimization applied"
✅ Transformation time <5ms (constitutional SLA)
✅ **1024-dim vectors work** (no IRIS literal size limit with psycopg3)

## Troubleshooting

**Issue**: `ModuleNotFoundError: No module named 'psycopg'`
**Solution**: Install psycopg3: `uv pip install psycopg`

**Issue**: Tests timeout or fail to connect
**Solution**: Verify IRIS is running on localhost:1972 and PGWire server started on port 15910

**Issue**: "Table test_1024 not found"
**Solution**: Run test data creation script first:
```bash
uv run python scripts/create_test_vectors.py
```

**Issue**: High latency (>50ms)
**Solution**: Verify HNSW index exists on test_1024 table:
```sql
SELECT * FROM INFORMATION_SCHEMA.INDEXES WHERE TABLE_NAME = 'test_1024'
```

## Comparison: psycopg2 vs psycopg3

| Aspect | psycopg2 | psycopg3 (RECOMMENDED) |
|--------|----------|------------------------|
| Parameter Binding | Client-side (literals) | Server-side (Extended Protocol) |
| Vector Size Limit | <256 dims (~3KB) | No limit (any size) |
| Optimizer Path | Literal transformation | Parameter transformation |
| Production Ready | ❌ Limited | ✅ Yes |
| E2E Test Status | ⚠️ Partial (E2E_FINDINGS.md) | ✅ Should work (needs verification) |

**Next Step**: Run this E2E test to validate psycopg3 works as expected with server-side binding!

# PostgreSQL Client Recommendations for Vector Optimization

**Last Updated**: 2025-10-02
**Feature**: Vector Query Optimizer (013-vector-query-optimizer)

---

## Quick Reference

### ✅ Recommended Clients (Production-Ready)

For **production vector similarity search** with embeddings (1024-1536 dims):

| Language | Client | Why |
|----------|--------|-----|
| **Python (Async)** | `asyncpg` | Server-side binding, highest performance |
| **Python (Sync)** | `psycopg3` | Server-side binding, drop-in upgrade from psycopg2 |
| **Java** | JDBC (PostgreSQL driver) | Server-side binding via PreparedStatement |
| **.NET/C#** | `npgsql` | Server-side binding, .NET best practices |
| **Node.js** | `node-postgres` (pg) | Server-side binding, industry standard |
| **Go** | `go-pq` | Server-side binding, Go standard library design |
| **Python (Direct)** | IRIS DBAPI | Lowest latency, bypasses wire protocol |

### ⚠️ Limited Support

| Client | Limitation | Recommendation |
|--------|-----------|----------------|
| `psycopg2` | Client-side interpolation, <256 dim limit | **Upgrade to psycopg3** |

---

## Why Client Selection Matters

The vector query optimizer transforms queries to enable IRIS HNSW index optimization. **Client parameter binding behavior** determines whether the optimizer can work effectively:

### Server-Side Binding ✅ (Recommended)

```python
# psycopg3 - Parameters sent separately from SQL
import psycopg

cur.execute(
    "SELECT * FROM vectors ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s)) LIMIT 5",
    (vec_b64,)  # Parameter sent in Bind message
)
```

**How it works**:
1. Client sends SQL with `%s` placeholder
2. Client sends parameter separately in Bind message
3. **Optimizer transforms parameter** before IRIS execution
4. No literal size limit (parameter stays as parameter until transformation)

### Client-Side Interpolation ❌ (Limited)

```python
# psycopg2 - Parameters embedded into SQL before sending
import psycopg2

cur.execute(
    "SELECT * FROM vectors ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s)) LIMIT 5",
    (vec_b64,)  # Parameter embedded into SQL by client!
)
```

**How it fails**:
1. Client embeds parameter into SQL as literal string
2. Server receives: `TO_VECTOR('base64:ABC123...')`
3. Optimizer transforms literal, but result is still a literal
4. **IRIS cannot compile SQL with >3KB string literals**
5. 1024-dim vectors create ~21KB JSON arrays → IRIS compilation error

---

## Python: asyncpg vs psycopg3 vs psycopg2

### asyncpg (Recommended for Async)

```python
import asyncpg
import struct
import base64

async def vector_search():
    # Encode vector as base64
    vec_bytes = struct.pack(f'{len(query_vector)}f', *query_vector)
    vec_b64 = 'base64:' + base64.b64encode(vec_bytes).decode('ascii')

    # asyncpg uses server-side binding
    conn = await asyncpg.connect('postgresql://localhost:5432/user')
    results = await conn.fetch(
        'SELECT id FROM vectors ORDER BY VECTOR_COSINE(vec, TO_VECTOR($1)) LIMIT 5',
        vec_b64  # ✅ Parameter (not literal) - no size limit
    )
    await conn.close()
    return results
```

**Why asyncpg**:
- ✅ Server-side parameter binding (Extended Protocol)
- ✅ Highest performance Python PostgreSQL client
- ✅ Async/await native
- ✅ No literal size limit
- ✅ Production-proven

### psycopg3 (Recommended for Sync)

```python
import psycopg
import struct
import base64

def vector_search():
    # Encode vector as base64
    vec_bytes = struct.pack(f'{len(query_vector)}f', *query_vector)
    vec_b64 = 'base64:' + base64.b64encode(vec_bytes).decode('ascii')

    # psycopg3 uses server-side binding
    with psycopg.connect('postgresql://localhost:5432/user') as conn:
        with conn.cursor() as cur:
            cur.execute(
                'SELECT id FROM vectors ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s)) LIMIT 5',
                (vec_b64,)  # ✅ Parameter (not literal) - no size limit
            )
            return cur.fetchall()
```

**Why psycopg3**:
- ✅ Server-side parameter binding (major upgrade from psycopg2)
- ✅ Drop-in replacement for psycopg2 (mostly compatible API)
- ✅ No literal size limit
- ✅ Production-ready

**Migration from psycopg2**:
```bash
# Install psycopg3
pip install psycopg

# Update imports
import psycopg  # was: import psycopg2

# Update connection parameters
conn = psycopg.connect(dbname='USER', ...)  # was: database='USER'
```

### psycopg2 (NOT Recommended)

```python
import psycopg2  # ❌ NOT recommended for large vectors

# psycopg2 does client-side interpolation
cur.execute(
    'SELECT * FROM vectors ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s)) LIMIT 5',
    (vec_b64,)  # ❌ Embedded as literal - 3KB size limit
)
```

**Why NOT psycopg2**:
- ❌ Client-side parameter interpolation
- ❌ Limited to <256 dimensions (~3KB literals)
- ❌ Cannot handle production embeddings (1024-1536 dims)
- ✅ **Solution**: Upgrade to psycopg3 (easy migration)

---

## Other Languages

### Java (JDBC)

```java
import java.sql.*;

Connection conn = DriverManager.getConnection("jdbc:postgresql://localhost:5432/user");
PreparedStatement stmt = conn.prepareStatement(
    "SELECT * FROM vectors ORDER BY VECTOR_COSINE(vec, TO_VECTOR(?)) LIMIT 5"
);
stmt.setString(1, vectorBase64);  // ✅ Server-side binding
ResultSet rs = stmt.executeQuery();
```

**Status**: ✅ Production-ready (JDBC spec requires server-side binding)

### .NET/C# (npgsql)

```csharp
using Npgsql;

using var conn = new NpgsqlConnection("Host=localhost;Port=5432;Database=user");
conn.Open();

using var cmd = new NpgsqlCommand(
    "SELECT * FROM vectors ORDER BY VECTOR_COSINE(vec, TO_VECTOR($1)) LIMIT 5",
    conn
);
cmd.Parameters.AddWithValue(vectorBase64);  // ✅ Server-side binding
var reader = cmd.ExecuteReader();
```

**Status**: ✅ Production-ready (npgsql uses Extended Protocol)

### Node.js (node-postgres)

```javascript
const { Pool } = require('pg');
const pool = new Pool({ host: 'localhost', port: 5432, database: 'user' });

const result = await pool.query(
    'SELECT * FROM vectors ORDER BY VECTOR_COSINE(vec, TO_VECTOR($1)) LIMIT 5',
    [vectorBase64]  // ✅ Server-side binding
);
```

**Status**: ✅ Production-ready (node-postgres uses Extended Protocol)

### Go (go-pq)

```go
import (
    "database/sql"
    _ "github.com/lib/pq"
)

db, _ := sql.Open("postgres", "host=localhost port=5432 dbname=user")
rows, err := db.Query(
    "SELECT * FROM vectors ORDER BY VECTOR_COSINE(vec, TO_VECTOR($1)) LIMIT 5",
    vectorBase64,  // ✅ Server-side binding
)
```

**Status**: ✅ Production-ready (Go database/sql requires server-side binding)

---

## Direct IRIS Connection (Embedded Python)

For **absolute best performance**, bypass PGWire entirely:

```python
import iris
import struct
import base64

def vector_search_iris_direct():
    # Encode vector
    vec_bytes = struct.pack(f'{len(query_vector)}f', *query_vector)
    vec_b64 = 'base64:' + base64.b64encode(vec_bytes).decode('ascii')

    # Direct IRIS execution - NO wire protocol overhead
    result = iris.sql.exec(
        'SELECT id FROM vectors ORDER BY VECTOR_COSINE(vec, TO_VECTOR(?, FLOAT)) LIMIT 5',
        vec_b64
    )
    return list(result)
```

**Performance**: 40.61ms P95 latency (proven in benchmarks)
**Requirement**: Must run inside IRIS process (embedded Python)

---

## Testing Your Client

### Quick Test Script

```python
# Test if your client uses server-side parameter binding
import sys

# Install your client library
# pip install psycopg  # or asyncpg, etc.

import <your_client_lib>

# Connect to PGWire server
conn = <your_client_lib>.connect('postgresql://localhost:15910/user')

# Generate test vector
import struct, base64, random
vec = [random.gauss(0,1) for _ in range(1024)]
norm = sum(x*x for x in vec) ** 0.5
vec = [x/norm for x in vec]
vec_bytes = struct.pack('1024f', *vec)
vec_b64 = 'base64:' + base64.b64encode(vec_bytes).decode('ascii')

# Execute query
cur = conn.cursor()
cur.execute(
    'SELECT id FROM test_1024 ORDER BY VECTOR_COSINE(vec, TO_VECTOR(%s)) LIMIT 5',
    (vec_b64,)
)
results = cur.fetchall()

# Success criteria
if len(results) == 5:
    print("✅ Client works with vector optimizer!")
else:
    print("❌ Client failed - check logs")
```

### Check PGWire Server Logs

**Server-side binding** (✅ Good):
```
DEBUG:vector_optimizer:Processing query with 1 parameters
INFO:vector_optimizer:Optimization complete: 1 params transformed
```

**Client-side interpolation** (⚠️ Limited):
```
INFO:vector_optimizer:Found 1 literal vector strings in SQL
WARNING:vector_optimizer:Skipping literal optimization: vector too large (21657 bytes > 3000 limit)
```

---

## Summary

| Use Case | Recommended Client | Why |
|----------|-------------------|-----|
| Python async production | **asyncpg** | Highest performance, server-side binding |
| Python sync production | **psycopg3** | Easy upgrade from psycopg2, server-side binding |
| Lowest latency | **IRIS DBAPI** | No wire protocol overhead |
| Java enterprise | **JDBC** | Server-side binding via PreparedStatement |
| .NET applications | **npgsql** | Server-side binding, .NET best practices |
| Node.js applications | **node-postgres** | Server-side binding, industry standard |
| Go applications | **go-pq** | Server-side binding, Go standard library |
| Legacy Python code | **Upgrade to psycopg3** | psycopg2 limited to <256 dims |

---

## References

- **Full Client Comparison**: `specs/013-vector-query-optimizer/CLIENT_COMPATIBILITY.md`
- **E2E Test Findings**: `specs/013-vector-query-optimizer/E2E_FINDINGS.md`
- **Manual Test Procedure**: `scripts/manual_e2e_test.md`
- **Implementation Status**: `specs/013-vector-query-optimizer/STATUS.md`

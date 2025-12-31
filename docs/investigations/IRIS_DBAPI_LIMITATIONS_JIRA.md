# IRIS DBAPI Driver Limitations for Vector Queries - JIRA Summary

## Issue Description

The IRIS DBAPI driver has fundamental limitations with vector query parameterization that prevent standard PostgreSQL client patterns from working with production-sized vectors. **This breaks compatibility with PostgreSQL vector extensions (pgvector) and standard PostgreSQL client behavior.**

## Background: PostgreSQL Extended Protocol Behavior

**Standard PostgreSQL clients** (psycopg3, asyncpg, JDBC, node-postgres) use Extended Protocol with full parameterization:

```python
# Standard PostgreSQL/pgvector pattern (what clients expect to work)
import psycopg

conn = psycopg.connect("postgresql://host:5432/db")
cur = conn.cursor()

# Client sends parameters separately from SQL (Extended Protocol)
cur.execute(
    "SELECT * FROM vectors ORDER BY embedding <-> %s LIMIT %s",
    ([0.1, 0.2, 0.3], 5)  # Vector and limit as parameters
)
```

**What happens under the hood**:
1. Client sends SQL: `SELECT * FROM vectors ORDER BY embedding <-> $1 LIMIT $2`
2. Client sends parameters separately: `[[0.1, 0.2, 0.3], 5]`
3. Database binds parameters at execution time
4. ✅ **Works in PostgreSQL, ❌ FAILS in IRIS DBAPI**

## Specific Limitations

### 1. TO_VECTOR() Parameter Restrictions
**Problem**: `TO_VECTOR()` function only accepts a single parameter marker (`?`) for the vector value itself.

**What Works** ✅:
```python
sql = "SELECT TOP 5 id, VECTOR_DOT_PRODUCT(vec, TO_VECTOR(?)) AS score FROM table"
cursor.execute(sql, (vector_string,))
```

**What Fails** ❌:
```python
# Cannot parameterize dimension or type
cursor.execute("... TO_VECTOR(?, ?)", (vector_string, 'FLOAT'))
cursor.execute("... TO_VECTOR(?, ?, ?)", (vec, 'FLOAT', 1024))

# Cannot use PostgreSQL array literal syntax with parameters
cursor.execute("... embedding <-> %s", ([0.1, 0.2, 0.3],))
# IRIS doesn't recognize <-> operator or array parameters
```

### 2. TOP Clause Cannot Be Parameterized
**Problem**: IRIS SQL compiler rejects parameter markers in TOP/LIMIT clauses.

**What Works** ✅:
```python
top_k = 5
sql = f"SELECT TOP {top_k} id FROM table"  # String interpolation required
cursor.execute(sql)
```

**What Fails** ❌:
```python
# Standard PostgreSQL pattern
cursor.execute("SELECT * FROM table LIMIT %s", (5,))

# IRIS pattern (still fails)
cursor.execute("SELECT TOP ? id FROM table", (5,))
```

**Impact**: Cannot safely parameterize result limits - must use string interpolation, which requires careful SQL injection prevention.

### 3. Client Driver Literal Rewriting
**Problem**: Some PostgreSQL client drivers (psycopg2) rewrite parameter markers into string literals before sending to database, causing IRIS to reject large vector strings (>3KB limit).

**Evidence**:
- 1024-dimension vectors as JSON arrays: ~21KB
- IRIS SQL compiler literal size limit: ~3KB
- Result: `SQLCODE: <-400>:<Fatal error occurred>`

**What Fails** ❌:
```python
# psycopg2 client-side parameter interpolation
import psycopg2  # Note: psycopg2, not psycopg3
cur.execute(
    "SELECT * FROM table WHERE vec = %s",
    ([0.1, 0.2, ..., 1024 values])  # Gets converted to 21KB string literal
)
# IRIS Error: String literal exceeds 3KB limit
```

### 4. pgvector Operator Incompatibility
**Problem**: IRIS doesn't recognize PostgreSQL vector operators (`<->`, `<#>`, `<=>`).

**PostgreSQL/pgvector syntax** (what clients send):
```sql
-- L2 distance (Euclidean)
SELECT * FROM items ORDER BY embedding <-> '[0.1,0.2,0.3]' LIMIT 5;

-- Inner product
SELECT * FROM items ORDER BY embedding <#> '[0.1,0.2,0.3]' LIMIT 5;

-- Cosine distance
SELECT * FROM items ORDER BY embedding <=> '[0.1,0.2,0.3]' LIMIT 5;
```

**IRIS native syntax** (what IRIS requires):
```sql
-- Must use function calls, not operators
SELECT TOP 5 * FROM items
ORDER BY VECTOR_L2(embedding, TO_VECTOR('[0.1,0.2,0.3]'));

SELECT TOP 5 * FROM items
ORDER BY VECTOR_DOT_PRODUCT(embedding, TO_VECTOR('[0.1,0.2,0.3]'));

SELECT TOP 5 * FROM items
ORDER BY VECTOR_COSINE(embedding, TO_VECTOR('[0.1,0.2,0.3]'));
```

**Impact**: PostgreSQL clients using pgvector syntax receive errors without query translation layer.

## Safe Pattern (PRODUCTION READY - DBAPI Only)

Based on proven patterns from `rag-templates/common/vector_sql_utils.py`:

```python
# Build SQL with string interpolation for TOP clause
top_k = 5
table = "RAG.SourceDocuments"

# ⚠️ Must use string interpolation for TOP (SQL injection risk if not careful)
sql = f"""
    SELECT TOP {top_k} doc_id,
           VECTOR_DOT_PRODUCT(embedding, TO_VECTOR(?)) AS score
    FROM {table}
    ORDER BY score DESC
"""

# Execute with SINGLE parameter (vector only)
cursor = conn.cursor()
vector_str = ",".join(map(str, query_vector))  # [0.1,0.2,0.3] → "0.1,0.2,0.3"
cursor.execute(sql, (vector_str,))
results = cursor.fetchall()
```

**Limitations of Safe Pattern**:
- ❌ Cannot parameterize TOP/LIMIT (SQL injection risk)
- ❌ Cannot use PostgreSQL array syntax `[0.1,0.2,0.3]`
- ❌ Cannot use pgvector operators (`<->`, `<#>`, `<=>`)
- ❌ Must convert vectors to comma-separated strings manually
- ✅ Can parameterize vector value only (as single `?`)

## Workaround: PGWire Server Architecture

**Solution**: PGWire server runs in embedded Python and translates PostgreSQL wire protocol to `iris.sql.exec()` internally, bypassing DBAPI driver limitations.

### How PGWire Handles pgvector Inputs

**Client Side** (standard PostgreSQL/pgvector):
```python
import psycopg  # or asyncpg, JDBC, node-postgres, etc.

# Client connects to PGWire server (NOT IRIS directly)
conn = psycopg.connect("postgresql://localhost:5432/USER")
cur = conn.cursor()

# ✅ Use standard pgvector syntax with full parameterization
cur.execute(
    "SELECT * FROM vectors ORDER BY embedding <-> %s LIMIT %s",
    ([0.1, 0.2, 0.3, ..., 1024 values], 5)
)
results = cur.fetchall()  # ✅ Works!
```

**PGWire Server Translation** (automatic, invisible to client):
```python
# 1. Receives PostgreSQL Extended Protocol message:
#    SQL: "SELECT * FROM vectors ORDER BY embedding <-> $1 LIMIT $2"
#    Params: [[0.1, 0.2, ..., 1024 values], 5]

# 2. Translates pgvector operator to IRIS function:
#    "<->" → "VECTOR_L2(embedding, TO_VECTOR(...))"

# 3. Substitutes parameters safely:
#    - Vector: Converts to IRIS format and inlines (no 3KB limit in iris.sql.exec())
#    - Limit: Converts LIMIT to TOP clause with value inlined

# 4. Executes via iris.sql.exec() (embedded Python):
import iris
result = iris.sql.exec("""
    SELECT TOP 5 * FROM vectors
    ORDER BY VECTOR_L2(embedding, TO_VECTOR('[0.1,0.2,...,1024 values]'))
""")

# 5. Returns results in PostgreSQL wire protocol format
```

**Architecture Comparison**:

| Approach | Protocol | Parameterization | Vector Size | pgvector Syntax |
|----------|----------|------------------|-------------|-----------------|
| **Direct IRIS DBAPI** | IRIS DBAPI driver | ❌ Limited (single `?` only) | ❌ <3KB limit | ❌ Not supported |
| **PGWire Server** | PostgreSQL wire → iris.sql.exec() | ✅ Full Extended Protocol | ✅ Any size | ✅ Translated automatically |

### Key Differences: PGWire vs Direct DBAPI

1. **Parameter Binding**:
   - **DBAPI**: Limited to single `?` for vector value
   - **PGWire**: Full PostgreSQL Extended Protocol support (unlimited parameters)

2. **Vector Size**:
   - **DBAPI**: 3KB literal limit (≈256 dimensions max)
   - **PGWire**: No limit (1024+ dimensions work)

3. **Syntax Compatibility**:
   - **DBAPI**: Must use IRIS-specific functions (`VECTOR_COSINE()`, `TO_VECTOR()`)
   - **PGWire**: Accepts pgvector syntax (`<->`, `<#>`, `<=>`) and translates automatically

4. **TOP/LIMIT Clauses**:
   - **DBAPI**: Must use string interpolation (SQL injection risk)
   - **PGWire**: Accepts PostgreSQL `LIMIT %s` parameters safely

5. **Client Compatibility**:
   - **DBAPI**: Requires IRIS-specific code patterns
   - **PGWire**: Works with ANY PostgreSQL client unmodified (psycopg, asyncpg, JDBC, node-postgres, Ruby pg, Go pgx, etc.)

## Impact Analysis

### Development Impact
- ❌ **Cannot use standard PostgreSQL patterns** with DBAPI
- ❌ **Code is IRIS-specific** and not portable
- ❌ **SQL injection risk** from required string interpolation for TOP clause
- ⚠️ **Testing complexity**: Must test with IRIS-specific patterns

### Production Impact
- ❌ **Limited to small vectors** (<256 dimensions) with DBAPI
- ❌ **Cannot use pgvector ecosystem tools** directly
- ❌ **Application code must handle IRIS quirks** explicitly
- ✅ **PGWire eliminates all limitations** (recommended for production)

### Client Compatibility Impact

**With DBAPI Driver** (limited):
```python
# ❌ Standard PostgreSQL clients DON'T WORK
import psycopg
conn = psycopg.connect("iris://localhost:1972/USER")  # Fails with vectors
```

**With PGWire Server** (full compatibility):
```python
# ✅ ANY PostgreSQL client works unmodified

# Python psycopg3
import psycopg
conn = psycopg.connect("postgresql://localhost:5432/USER")

# Python asyncpg
import asyncpg
conn = await asyncpg.connect("postgresql://localhost:5432/USER")

# Node.js pg
const { Client } = require('pg');
const client = new Client({ host: 'localhost', port: 5432 });

# Java JDBC
Connection conn = DriverManager.getConnection(
    "jdbc:postgresql://localhost:5432/USER"
);

# Ruby pg
require 'pg'
conn = PG.connect(host: 'localhost', port: 5432, dbname: 'USER')

# Go pgx
conn, _ := pgx.Connect(context.Background(),
    "postgresql://localhost:5432/USER")
```

**All of these clients send identical PostgreSQL wire protocol messages. DBAPI driver cannot handle them; PGWire server can.**

## Recommendations

### For New Development
**✅ Use PGWire Server** (eliminates all limitations):
- Full PostgreSQL compatibility
- Standard pgvector syntax works
- Any vector size supported
- All PostgreSQL clients work unmodified
- No SQL injection risk from parameterization workarounds

### For Existing IRIS DBAPI Code
**⚠️ Use Safe Pattern** (requires careful coding):
- Single `?` parameter for vector value only
- String interpolation for TOP clause (validate inputs!)
- Manual vector format conversion
- IRIS-specific function syntax

### Migration Path
**DBAPI → PGWire**:
```python
# Before (IRIS DBAPI - limited)
top_k = 5  # Cannot parameterize
sql = f"SELECT TOP {top_k} id, VECTOR_DOT_PRODUCT(vec, TO_VECTOR(?)) AS score FROM table"
vector_str = ",".join(map(str, vector))  # Manual conversion
cursor.execute(sql, (vector_str,))

# After (PGWire - standard PostgreSQL)
cur.execute(
    "SELECT * FROM table ORDER BY vec <-> %s LIMIT %s",
    (vector, top_k)  # Both parameterized safely
)
```

**Effort**: Change connection string only - application code unchanged.

## References

- Production DBAPI pattern: `rag-templates/common/vector_sql_utils.py`
- PGWire architecture: `docs/EMBEDDED_PYTHON_SERVERS_HOWTO.md`
- E2E findings: `specs/013-vector-query-optimizer/E2E_FINDINGS.md`
- pgvector documentation: https://github.com/pgvector/pgvector
- PostgreSQL Extended Protocol: https://www.postgresql.org/docs/current/protocol-flow.html

---

**Summary**: IRIS DBAPI driver breaks standard PostgreSQL client patterns for vector queries. PGWire server solves this by translating PostgreSQL wire protocol to `iris.sql.exec()` internally, enabling full PostgreSQL/pgvector compatibility with ANY client library.

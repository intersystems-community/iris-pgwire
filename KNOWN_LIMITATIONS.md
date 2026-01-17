# Known Limitations - IRIS PGWire

This document catalogs known limitations, workarounds, and behavior differences when using IRIS through the PostgreSQL wire protocol.

**Industry Context**: IRIS PGWire follows proven architectural patterns from the PostgreSQL wire protocol ecosystem. Many design decisions (e.g., delegating SSL/TLS to reverse proxy, omitting GSSAPI) match industry leaders like PgBouncer (most deployed connection pooler), YugabyteDB (distributed SQL), and Google Cloud PGAdapter.

**Security Note**: Authentication security is enterprise-grade (OAuth 2.0, IRIS Wallet, SCRAM-SHA-256) with no plain-text password transmission. Transport encryption is delegated to industry-standard reverse proxy pattern (nginx/HAProxy).

---

## 🌐 Industry Comparison: PostgreSQL Wire Protocol Implementations

Based on comprehensive research of 9 major implementations (November 2025):

| Feature | IRIS PGWire | PgBouncer | YugabyteDB | PGAdapter | QuestDB | CockroachDB | Materialize | ClickHouse | Pattern |
|---------|-------------|-----------|------------|-----------|---------|-------------|-------------|------------|---------|
| **Wire Protocol** | ✅ v3.0 | ✅ v3.0 | ✅ v3.0 | ✅ v3.0 | ✅ v3.0 | ✅ v3.0 | ✅ v3.0 | ✅ v3.0 | Universal |
| **SSL/TLS Native** | ❌ Proxy | ✅ Yes | ✅ Yes | ✅ Yes | ❌ No | ✅ Yes | ✅ Yes | ✅ Yes | Mixed (6/8 native) |
| **SCRAM-SHA-256** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes | ❌ No | ✅ Yes | — | ❌ No | Standard (5/8) |
| **OAuth/IAM** | ✅ Yes | ❌ No | ❌ No | ✅ Yes | ❌ No | ❌ No | ❌ No | ❌ No | Rare (2/8) |
| **Kerberos/GSSAPI** | ❌ No | ❌ No | ❌ No | ❌ No | ❌ No | ✅ Yes | ❌ No | ❌ No | **Very Rare (1/8)** |
| **Connection Pool** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes | ❌ No | ✅ Yes | ✅ Yes | — | Common (6/8) |
| **Binary Format** | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes | Universal |

**Key Insights**:

1. **GSSAPI Adoption**: Only 1 of 8 implementations (12.5%) - CockroachDB enterprise feature. Even PostgreSQL core has limited adoption in wire protocol adapters.

2. **SSL/TLS Patterns**:
   - **Native**: Most implementations (6 of 8)
   - **Proxy**: IRIS PGWire (reverse proxy pattern)
   - **None**: QuestDB explicitly omits SSL
   - **Network-layer**: Emerging pattern (Tailscale pgproxy)

3. **Authentication Trends**:
   - **SCRAM-SHA-256**: Standard (5 of 8 implementations)
   - **OAuth/IAM**: Cloud-native pattern (2 of 8 - IRIS PGWire + PGAdapter)
   - **MD5**: Being deprecated across ecosystem (YugabyteDB migration guide)

4. **IRIS PGWire Position**: Matches 6 of 8 implementations in security/authentication profile.

**Technical Reason for GSSAPI Rarity** (from industry research):
> "GSSAPI is an inherently stateful, interactive protocol involving challenge-response exchanges and ticket validation against a centralized Key Distribution Center (KDC). This makes it difficult to implement in connection pooling contexts and cloud-native architectures where authentication delegation is preferred."

**References**:
- Perplexity industry research: PostgreSQL wire protocol ecosystem survey (November 2025)
- CockroachDB, YugabyteDB, PGAdapter, PgBouncer, QuestDB, Materialize, ClickHouse, CrateDB official documentation
- PostgreSQL wire protocol compatibility analysis

---

## 🟢 PostgreSQL DDL Compatibility

**Status**: Enhanced Compatibility ✅
**Feature**: Automated transformations for PostgreSQL-specific DDL

### Capabilities

IRIS PGWire automatically handles several common PostgreSQL DDL constructs that are natively unsupported by IRIS:

- ✅ **Generated Columns**: `GENERATED ALWAYS AS ... STORED` are automatically stripped.
- ✅ **Enum Types**: `CREATE TYPE ... ENUM` are registered and columns mapped to `VARCHAR(64)`.
- ✅ **Storage Parameters**: `WITH (fillfactor = ...)` and `SET (fillfactor)` are stripped/skipped.
- ✅ **Index Methods**: `USING btree` is automatically removed.
- ✅ **Casts**: `'value'::text` syntax in defaults is stripped.
- ✅ **CHECK Constraints**: `ADD CONSTRAINT ... CHECK` are skipped with a warning.

### Configuration

Use the `strict_ddl` flag to control this behavior:
- `strict_ddl = false` (default): Skip/transform with a warning.
- `strict_ddl = true`: Raise an error for unsupported DDL.

---

## 🟡 INFORMATION_SCHEMA Compatibility

**Severity**: Medium
**Affects**: Schema introspection queries

### Issue Description

IRIS uses `INFORMATION_SCHEMA` tables (SQL standard) rather than PostgreSQL's `pg_catalog` system tables. Some PostgreSQL tools expect `pg_catalog`.

### Workaround

PGWire translates common `pg_catalog` queries to `INFORMATION_SCHEMA` equivalents. For unsupported queries, use IRIS native metadata:

```sql
-- PostgreSQL style (may not work)
SELECT * FROM pg_catalog.pg_tables;

-- IRIS equivalent (works)
SELECT * FROM INFORMATION_SCHEMA.TABLES;
```

### Tool Compatibility

- ✅ **Superset**: Works (SQLAlchemy handles INFORMATION_SCHEMA)
- ✅ **DBeaver**: Works (detects INFORMATION_SCHEMA support)
- ⚠️ **pgAdmin**: Partial (some features require pg_catalog)
- ⚠️ **Metabase**: Partial (similar to pgAdmin)

---

## 🟡 HNSW Index Performance Requirements

**Severity**: Medium
**Affects**: Vector similarity search performance

### Issue Description

HNSW vector indexes provide significant performance benefits only at scale:

| Dataset Size | HNSW Performance | Recommendation |
|--------------|------------------|----------------|
| < 10,000 vectors | 0.98-1.02× (negligible) | Use sequential scan |
| 10,000-99,999 vectors | 1.0-2.0× improvement | Consider HNSW with testing |
| ≥ 100,000 vectors | **5.14× improvement** ✅ | **HNSW strongly recommended** |

### Recommendation

Only create HNSW indexes for datasets with 100K+ vectors:

```sql
-- Only beneficial at scale (≥100K vectors)
CREATE INDEX idx_vec ON vectors(vec) AS HNSW(Distance='Cosine');

-- Always specify Distance parameter (required)
CREATE INDEX idx_vec ON vectors(vec) AS HNSW(Distance='DotProduct');
```

**Reference**: See [HNSW Investigation](docs/HNSW_FINDINGS_2025_10_02.md) for detailed benchmarks.

---

## 🟡 pgvector Operator Support

**Severity**: Medium
**Affects**: pgvector compatibility

### Supported Operators

| pgvector Operator | IRIS Translation | Status |
|-------------------|------------------|--------|
| `<=>` (cosine distance) | `VECTOR_COSINE()` | ✅ **Supported** |
| `<#>` (inner/dot product) | `VECTOR_DOT_PRODUCT()` | ✅ **Supported** |
| `<->` (L2/Euclidean distance) | — | ❌ Not implemented |

### Example

```sql
-- ✅ Works: Cosine distance
SELECT * FROM vectors ORDER BY embedding <=> %s LIMIT 5;

-- ✅ Works: Dot product (for MIPS - Maximum Inner Product Search)
SELECT * FROM vectors ORDER BY embedding <#> %s LIMIT 5;

-- ❌ Fails: L2 distance (not available in IRIS)
SELECT * FROM vectors ORDER BY embedding <-> %s LIMIT 5;
```

### Workaround

Use cosine distance (`<=>`) or dot product (`<#>`) instead of L2 distance. For normalized embeddings (OpenAI, Cohere, sentence-transformers), cosine similarity is recommended.

---

## 🟡 SQLAlchemy psycopg2 Dialect Compatibility

**Severity**: Medium
**Affects**: SQLAlchemy applications using psycopg2

### Issue Description

SQLAlchemy's psycopg2 dialect queries PostgreSQL system catalogs (`pg_type`) during connection setup to get HSTORE type OIDs. IRIS doesn't have these PostgreSQL-specific system tables.

### Error

```
IndexError: tuple index out of range
  in psycopg2/extras.py HstoreAdapter.get_oids()
```

### Affected Libraries and Tools

| Tool/Library | PGWire Status | IRIS-Native Alternative |
|--------------|---------------|------------------------|
| **LangChain PGVector** | ❌ Fails | [`langchain-iris`](https://github.com/caretdev/langchain-iris) ✅ |
| **LlamaIndex PGVectorStore** | ❌ Fails | [`llama-iris`](https://github.com/caretdev/llama-iris) ✅ |
| **Haystack PGVector** | ❌ Fails | Custom retriever with psycopg3 |
| **SQLAlchemy + psycopg2** | ❌ Fails | psycopg3 directly |
| **Django ORM (psycopg2)** | ❌ Fails | psycopg3 directly |
| **psycopg3 (psycopg)** | ✅ Works | — |
| **asyncpg** | ✅ Works | — |
| **node-postgres (pg)** | ✅ Works | — |
| **JDBC PostgreSQL** | ✅ Works | — |

### Recommended: IRIS-Native Packages

For LangChain and LlamaIndex applications, use the IRIS-native packages which connect directly to IRIS (not via PGWire):

```bash
pip install langchain-iris llama-iris
```

**LangChain with IRIS:**
```python
from langchain_iris import IRISVector

db = IRISVector(
    embedding_function=embeddings,
    connection_string="iris://_SYSTEM:SYS@localhost:1972/USER",
    collection_name="my_docs"
)
db.add_texts(["Document 1", "Document 2"])
results = db.similarity_search("query", k=5)
```

**LlamaIndex with IRIS:**
```python
from llama_iris import IRISVectorStore

vector_store = IRISVectorStore.from_params(
    connection_string="iris://_SYSTEM:SYS@localhost:1972/USER",
    table_name="my_vectors",
    embed_dim=384
)
```

### Alternative: psycopg3 via PGWire

For direct PGWire access without ORM:

```python
import psycopg

with psycopg.connect("host=localhost port=5432 dbname=USER") as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM docs ORDER BY embedding <=> %s LIMIT 5", (query_vec,))
        results = cur.fetchall()
```

---

## 🟡 Two-Phase Commit Not Supported

**Severity**: Medium
**Affects**: Distributed transactions

### Issue Description

PostgreSQL's `PREPARE TRANSACTION` / `COMMIT PREPARED` two-phase commit protocol is not supported via PGWire.

### Workaround

Use single-phase transactions:

```sql
BEGIN;
-- Your operations
COMMIT;  -- Use COMMIT instead of PREPARE TRANSACTION
```

### Impact

Most applications don't require two-phase commit. Affected scenarios:
- Distributed database transactions (XA protocol)
- Some Java EE application servers
- Microservices requiring cross-database consistency

---

## 🟡 Bulk Insert Performance

**Severity**: Medium
**Affects**: Large data imports

### Issue Description

Bulk inserts via `COPY FROM STDIN` are currently limited by row-by-row processing. Performance expectations:

| Operation | Expected Time | Notes |
|-----------|---------------|-------|
| Single INSERT | 6-8ms | Includes protocol overhead |
| 250-row COPY | 400-600ms | ~2.4ms per row |
| 1000-row COPY | 1.6-2.4s | Row-by-row processing |

### Workaround (Large Imports)

For imports > 10,000 rows, use native IRIS bulk load:

```bash
# Export to CSV
\copy data TO '/tmp/data.csv' CSV

# Import via IRIS native
docker exec -i iris irissession IRIS << 'EOF'
set $namespace="USER"
do ##class(%SQL.Statement).%ExecDirect(, "LOAD DATA FROM '/tmp/data.csv' INTO TABLE data")
halt
EOF
```

### Future Enhancement

Planned optimization: Use IRIS `executemany()` for batch operations (projected 4× speedup to 2,400+ rows/sec).

---

## 🟡 VECTOR Type Display (DBAPI Backend)

**Severity**: Low
**Affects**: Type introspection

### Issue Description

When using the DBAPI backend (external Python process), VECTOR columns show as VARCHAR in INFORMATION_SCHEMA metadata queries. Vector operations work correctly despite the display issue.

### Workaround

Use the embedded Python backend for accurate type introspection:

```bash
# Embedded backend (inside IRIS)
export BACKEND_TYPE=embedded
irispython -m iris_pgwire.server
```

### Impact

- ✅ Vector operations (VECTOR_COSINE, TO_VECTOR) work correctly
- ✅ Vector parameter binding works (up to 188,962 dimensions)
- ⚠️ INFORMATION_SCHEMA.COLUMNS shows VARCHAR instead of VECTOR

---

## 🟡 SSL/TLS Wire Protocol Not Implemented

**Severity**: Medium
**Affects**: Connection transport encryption

**Industry Context**: Many PostgreSQL wire protocol implementations omit SSL/TLS support (e.g., QuestDB) or delegate to network-layer security (e.g., Tailscale's pgproxy). This is a common architectural decision for protocol adapters.

### Issue Description

PGWire responds with 'N' (no SSL) to PostgreSQL client SSL probes. The wire protocol does not support TLS encryption. Authentication security is provided by:
- ✅ **OAuth 2.0**: Token-based authentication (no plain-text passwords)
- ✅ **IRIS Wallet**: Encrypted credential storage (encrypted at rest)
- ✅ **Password Authentication**: SCRAM-SHA-256 protocol (no plain-text transmission)

### Workaround

For production deployments requiring transport encryption:

```bash
# Deploy PGWire behind TLS-terminating reverse proxy
# Example: nginx with TLS → PGWire plain-text (localhost only)

# nginx.conf
upstream pgwire {
    server localhost:5432;
}

server {
    listen 5433 ssl;
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://pgwire;
    }
}
```

**Client Connection**:
```bash
# Connect via TLS proxy on port 5433
psql "host=your-server port=5433 sslmode=require user=_SYSTEM dbname=USER"
```

### Impact

- ❌ Wire protocol does not encrypt PostgreSQL traffic
- ✅ Authentication credentials protected (OAuth tokens, SCRAM-SHA-256, Wallet encryption)
- ✅ Workaround available (reverse proxy with TLS termination)
- ⚠️ Database traffic visible to network observers without proxy

---

## 🟡 Kerberos/GSSAPI Authentication Not Supported

**Severity**: Low (enterprise-specific)
**Affects**: Organizations with centralized Kerberos infrastructure

**Industry Context**: GSSAPI is rarely implemented in PostgreSQL wire protocol ecosystem. Of 9 major implementations surveyed (PgBouncer, YugabyteDB, PGAdapter, ClickHouse, QuestDB, Materialize, CrateDB, pgwire, CockroachDB), only 2 support GSSAPI (CockroachDB enterprise + PostgreSQL core).

### Issue Description

IRIS PGWire does not implement Kerberos/GSSAPI authentication. This matches the pattern of most PostgreSQL wire protocol implementations.

**Technical Reason** (from industry research):
> "GSSAPI is an inherently stateful, interactive protocol involving challenge-response exchanges and ticket validation against a centralized Key Distribution Center (KDC). This makes it difficult to implement in connection pooling contexts and cloud-native architectures." - PostgreSQL Wire Protocol Ecosystem Analysis (2025)

### Alternative Authentication Methods

IRIS PGWire provides enterprise-grade alternatives that match cloud-native patterns:

1. **OAuth 2.0 Token Authentication** (matches Google Cloud PGAdapter approach)
   - Token-based authentication
   - No plain-text passwords
   - 5-minute TTL, automatic refresh
   - Integrated with IRIS security infrastructure

2. **IRIS Wallet** (encrypted credential storage)
   - Credentials encrypted at rest in IRISSECURITY database
   - Automatic password rotation via Wallet API
   - Audit trail of all credential access
   - No plain-text passwords in code or configuration

3. **SCRAM-SHA-256** (industry best practice, YugabyteDB recommended)
   - Challenge-response authentication
   - Cryptographically secure password storage
   - Resistant to replay attacks
   - No plain-text password transmission

### Impact

- ❌ Cannot authenticate using Kerberos tickets
- ❌ No Active Directory SSO integration via GSSAPI
- ✅ OAuth 2.0 provides token-based authentication (cloud-native equivalent)
- ✅ IRIS Wallet provides centralized credential management
- ✅ SCRAM-SHA-256 provides secure password authentication

### Implementations Comparison

| Implementation | GSSAPI Support | Notes |
|----------------|----------------|-------|
| **PostgreSQL Core** | ✅ Yes | Native OS Kerberos integration |
| **CockroachDB** | ✅ Yes | Enterprise feature with keytab management |
| **PgBouncer** | ❌ No | Most deployed connection pooler - GSSAPI omitted |
| **YugabyteDB** | ❌ No | Distributed SQL database - uses password auth |
| **PGAdapter** | ❌ No | Google Cloud - uses IAM instead |
| **ClickHouse** | ❌ No | Analytical database - password only |
| **QuestDB** | ❌ No | Time-series database - no GSSAPI |
| **Materialize** | ❌ No | Streaming warehouse - standard auth only |
| **IRIS PGWire** | ❌ No | **Matches 6 of 9 implementations** |

**Pattern**: Only 2 of 9 implementations support GSSAPI (22% adoption rate in ecosystem)

---

## Reporting Issues

Found a new limitation or unexpected behavior?

### Before Reporting

1. Check this document for known issues
2. Test with minimal reproduction case
3. Verify IRIS and PGWire versions

### Report Format

**GitHub Repository**: https://github.com/isc-tdyar/iris-pgwire/issues

```markdown
## Issue Description
Brief description of the limitation/bug

## Environment
- IRIS Version: X.X.X
- PGWire Version: X.X.X
- Client: psql/psycopg/other

## Reproduction Steps
1. Step 1
2. Step 2
3. Observe behavior

## Expected Behavior
What should happen

## Actual Behavior
What actually happens

## Workaround (if known)
How to work around the issue
```

---

## Contributing

Help us improve! If you find workarounds or solutions:

1. Fork the repository
2. Create a branch: `fix/limitation-name`
3. Implement fix with tests
4. Submit pull request
5. Update this document

**Priority Contributions Welcome**:
- `pg_catalog` emulation for better tool compatibility
- Bulk insert optimization (executemany() integration)
- SSL/TLS wire protocol support
- Performance improvements for large result sets

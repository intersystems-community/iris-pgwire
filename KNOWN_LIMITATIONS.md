# Known Limitations - IRIS PGWire

This document catalogs known limitations, workarounds, and behavior differences when using IRIS through the PostgreSQL wire protocol.

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

## 🟡 L2 Distance Not Supported

**Severity**: Medium
**Affects**: pgvector compatibility

### Issue Description

The L2 distance operator `<->` from pgvector is not supported. IRIS VECTOR functions provide:
- ✅ **Cosine distance**: `<=>` → `VECTOR_COSINE()`
- ✅ **Dot product**: `<#>` → `VECTOR_DOT_PRODUCT()`
- ❌ **L2 distance**: `<->` → NOT SUPPORTED

### Error

```sql
SELECT * FROM vectors ORDER BY embedding <-> '[0.1,0.2]';
-- Raises: NotImplementedError: L2 distance operator (<->) is not supported by IRIS
```

### Workaround

Use cosine distance instead:

```sql
-- Replace:
SELECT * FROM vectors ORDER BY embedding <-> '[0.1,0.2]' LIMIT 5;

-- With:
SELECT * FROM vectors ORDER BY embedding <=> '[0.1,0.2]' LIMIT 5;
```

### Technical Reason

IRIS does not provide a native L2 distance function. Implementing it would require element-wise operations that would violate the <5ms translation performance requirement.

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

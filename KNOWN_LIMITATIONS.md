# Known Limitations - IRIS PGWire

**Last Updated**: 2025-11-06

This document catalogs known limitations, workarounds, and ongoing issues in the IRIS PGWire implementation.

---

## 🔴 CRITICAL: DDL Semicolon Parsing (FIXED in v0.2.0)

**Status**: ✅ **FIXED** - 2025-11-06
**Severity**: Critical
**Affects**: All DDL operations (CREATE/DROP/ALTER TABLE)
**Fix Version**: v0.2.0

### Issue Description

Prior to v0.2.0, DDL statements with semicolon terminators would fail with error:
```
ERROR: Input (;) encountered after end of query^CREATE TABLE ...;
```

### Root Cause

The SQL translator did not strip trailing semicolons from incoming SQL before translation to IRIS SQL syntax. PostgreSQL clients send statements with semicolons, but IRIS expects them without during intermediate processing.

### Fix Implementation

**File**: `src/iris_pgwire/sql_translator/translator.py:240-244`

```python
# Strip trailing semicolons from incoming SQL before translation
# PostgreSQL clients send queries with semicolons, but IRIS expects them without
# We'll add them back in _finalize_translation() if needed
original_sql = context.original_sql.rstrip(';').strip()
translated_sql = original_sql
```

### Testing

Comprehensive E2E test suite added:
- **File**: `tests/test_ddl_statements.py`
- **Coverage**: 15 test cases including regression tests
- **Validation**: Real PostgreSQL client (psycopg) against running IRIS

### Workaround (Pre-v0.2.0)

If running an older version, create tables via native IRIS SQL:

**Option 1**: Use irissession command
```bash
docker exec -i iris irissession IRIS << 'EOF'
set $namespace="USER"
do ##class(%SQL.Statement).%ExecDirect(, "CREATE TABLE Patients (PatientID INT PRIMARY KEY, ...)")
halt
EOF
```

**Option 2**: Use IRIS Management Portal
1. Navigate to http://localhost:52773/csp/sys/UtilHome.csp
2. System → SQL → Execute Query
3. Execute DDL without semicolons

**Option 3**: Use native IRIS drivers
```python
import iris.dbapi as dbapi
conn = dbapi.connect(hostname="localhost", port=1972, namespace="USER",
                     username="_SYSTEM", password="SYS")
conn.execute("CREATE TABLE Patients (PatientID INT PRIMARY KEY, ...)")
```

---

## 🟡 INFORMATION_SCHEMA Compatibility

**Status**: ⚠️ **PARTIAL SUPPORT**
**Severity**: Medium
**Affects**: Schema introspection queries

### Issue Description

IRIS uses `INFORMATION_SCHEMA` tables (not PostgreSQL's `pg_catalog`). Some PostgreSQL tools expect `pg_catalog` system tables.

### Workaround

PGWire translates common `pg_catalog` queries to `INFORMATION_SCHEMA` equivalents. For unsupported queries, use IRIS native metadata:

```sql
-- PostgreSQL style (may not work)
SELECT * FROM pg_catalog.pg_tables;

-- IRIS equivalent (works)
SELECT * FROM INFORMATION_SCHEMA.TABLES;
```

### Affected Tools

- ✅ **Superset**: Works (uses SQLAlchemy which handles INFORMATION_SCHEMA)
- ✅ **DBeaver**: Works (detects INFORMATION_SCHEMA support)
- ⚠️ **pgAdmin**: Partial (some features require pg_catalog)
- ⚠️ **Metabase**: Partial (similar to pgAdmin)

---

## 🟡 Two-Phase Commit Not Supported

**Status**: ❌ **NOT SUPPORTED**
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

## 🟡 L2 Distance Vector Operation Not Supported

**Status**: ❌ **NOT SUPPORTED** - Constitutional Requirement
**Severity**: Medium
**Affects**: pgvector compatibility
**Constitutional Reference**: v1.2.4

### Issue Description

The L2 distance operator `<->` from pgvector is not supported. IRIS VECTOR functions support:
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

IRIS does not provide a native L2 distance vector function. Implementing it would require:
1. Square root operations (performance penalty)
2. Element-wise subtraction (complexity)
3. Breaking the <5ms translation SLA (constitutional violation)

---

## 🟡 Bulk Insert Performance

**Status**: ⚠️ **PERFORMANCE CONCERN**
**Severity**: Medium
**Affects**: Large data imports

### Issue Description

Bulk inserts via `COPY` or `INSERT ... VALUES (multiple rows)` may be slower than expected due to:
1. PGWire protocol overhead (~4ms per batch)
2. INFORMATION_SCHEMA compatibility checks
3. Row-by-row processing in some scenarios

### Performance Expectations

| Operation | Expected Time | Notes |
|-----------|---------------|-------|
| Single INSERT | 6-8ms | Includes PGWire overhead |
| 100-row COPY | 200-400ms | ~2-4ms per row |
| 1000-row COPY | 2-4s | Batch processing |

### Workaround

For large imports, use native IRIS bulk load:
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

---

## 🟢 ACORN-1 Algorithm Deprecated

**Status**: ⚠️ **DEPRECATED**
**Severity**: Low
**Affects**: Vector query optimization
**Constitutional Reference**: v1.2.0

### Issue Description

ACORN-1 algorithm shows consistent performance degradation (20-72% slower) at all dataset scales compared to HNSW indexing alone.

### Recommendation

**DO NOT USE** ACORN-1 in production:
```sql
-- DEPRECATED (do not use):
SET OPTION ACORN_1_SELECTIVITY_THRESHOLD=1;
SELECT TOP 5 * FROM vectors
WHERE id >= 0  -- ACORN-1 requires WHERE clause
ORDER BY VECTOR_COSINE(vec, TO_VECTOR('[...]'));

-- RECOMMENDED:
CREATE INDEX idx_vec ON vectors(vec) AS HNSW(Distance='Cosine');
SELECT TOP 5 * FROM vectors
ORDER BY VECTOR_COSINE(vec, TO_VECTOR('[...]'));
```

### Performance Data (100K vectors)

- HNSW alone: 10.85ms avg ✅
- ACORN-1 + WHERE id >= 0: 13.60ms (25% slower) ❌
- ACORN-1 + WHERE id < 5000: 17.97ms (62% slower) ❌

**Reference**: `docs/HNSW_FINDINGS_2025_10_02.md`

---

## Reporting Issues

Found a new limitation or bug?

### Before Reporting

1. Check this document for known issues
2. Check if fixed in latest version
3. Test with minimal reproduction case

### Report Format

**GitHub Repository**: https://github.com/intersystems-community/iris-pgwire/issues

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
3. Observe error

## Expected Behavior
What should happen

## Actual Behavior
What actually happens

## Workaround (if known)
How to work around the issue
```

---

## Version History

### v0.2.0 (2025-11-06)
- ✅ **FIXED**: DDL semicolon parsing bug
- 📝 **ADDED**: Comprehensive DDL test suite
- 📝 **ADDED**: This KNOWN_LIMITATIONS.md document

### v0.1.0 (2025-10-08)
- 🎉 Initial release
- ⚠️ DDL semicolon parsing issue documented
- ⚠️ INFORMATION_SCHEMA compatibility limitations
- ⚠️ L2 distance not supported (constitutional)
- ⚠️ ACORN-1 deprecated (performance)

---

## Contributing

Help us improve! If you find workarounds or solutions:

1. Fork the repository
2. Create a branch: `fix/limitation-name`
3. Implement fix with tests
4. Submit pull request
5. Update this document

**Priority Contributions Welcome**:
- pg_catalog emulation for better tool compatibility
- Bulk insert optimization
- Performance improvements for large result sets

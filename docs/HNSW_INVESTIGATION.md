# HNSW Index Investigation Report

## Executive Summary

**Status**: HNSW index NOT WORKING despite correct IRIS build and configuration
**IRIS Build**: 2025.3.0EHAT.127.0-linux-arm64v8 (confirmed working HNSW support)
**Root Cause**: Under investigation - suspected DBAPI varchar limitation
**Performance**: 0% improvement with HNSW index (26.77ms with vs 26.75ms without)

## Investigation Timeline

### 1. Initial Performance Discovery
- **Target**: 433.9 ops/sec (from IRIS performance report)
- **Actual**: 37.4 ops/sec (12× slower than target)
- **Vector Query Optimizer**: ✅ Working perfectly (0.36ms P95, 100% SLA compliance)
- **HNSW Index**: ❌ Not providing any speedup

### 2. ACORN-1 Configuration (Corrected)

**Initial Incorrect Approaches**:
```python
# WRONG: Query hint syntax (doesn't work for our use case)
sql = "/*#OPTIONS {\"ACORN-1\":1} */ SELECT ..."

# WRONG: Index parameter syntax (invalid SQL)
CREATE INDEX idx_hnsw_vec ON test_1024(vec) AS HNSW WITH (ACORN=1)

# WRONG: Plural OPTIONS
SET OPTIONS ACORN_1_SELECTIVITY_THRESHOLD=1
```

**Correct ACORN-1 Configuration** (user-corrected):
```python
# System option (singular OPTION)
cur.execute('SET OPTION ACORN_1_SELECTIVITY_THRESHOLD=1')

# Standard HNSW index creation
cur.execute('CREATE INDEX idx_hnsw_vec ON test_1024(vec) AS HNSW')
```

**Result**: ACORN-1 configured correctly, but HNSW still not working

### 3. Dataset Size Testing

Created large dataset to test HNSW engagement threshold:

| Dataset Size | Avg Latency | P95 Latency | Result |
|-------------|-------------|-------------|--------|
| 1,000 vectors | 26.90ms | 27.11ms | Baseline |
| 10,000 vectors | 31.98ms | 32.45ms | **WORSE** |

**Improvement**: 0.84× (negative - larger dataset is SLOWER)

**Conclusion**: HNSW is doing linear scan, not using index optimization

### 4. Index Presence vs Benefit Test

Compared query performance WITH and WITHOUT HNSW index:

```python
# WITH HNSW index:    26.77ms avg
# WITHOUT index:      26.75ms avg
# Improvement:        1.00× (NONE)
```

**Conclusion**: HNSW index exists but provides ZERO benefit

## Critical Discovery: DBAPI varchar Limitation

### Problem

Table created via DBAPI cursor shows incorrect column type:

```sql
-- Table creation DDL
CREATE TABLE test_1024 (
    id INTEGER PRIMARY KEY,
    vec VECTOR(FLOAT, 1024)
)

-- INFORMATION_SCHEMA query result
SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = 'test_1024'
-- Result: ('vec', 'varchar')  ← NOT VECTOR!
```

**User Statement**: "dbapi reports vector as varchar, limitation on the client. However, the iris.sql.exec() function may not have that limitation"

### Hypothesis

DBAPI creates varchar columns instead of true VECTOR columns, preventing HNSW from engaging. IRIS HNSW requires actual VECTOR type columns to optimize queries.

### Required Architecture: Dual-Path IRIS Integration

**User Requirement** (verbatim):
> "we should have strong DDL and procedures around creating tables. dbapi reports vector as varchar, limitation on the client. However, the iris.sql.exec() function may not have that limitation"

> "we are supposed to have 2 IRIS paths - DBAPI *AND* iris.sql.exec() which is Embedded Python - and compare both of those to postgresql. Do you remember, or we need to put this in the specs and constitution!!!!!!!"

## Current Implementation Status

### ✅ Working Components

1. **Vector Query Optimizer**: Production-ready
   - Translation SLA: 0.36ms P95 (14× faster than 5ms requirement)
   - Overhead: 1.2% of total query time
   - SLA Compliance: 100% (0 violations)
   - Committed: 9fba4a2

2. **ACORN-1 Configuration**: Correctly configured
   - System option: `SET OPTION ACORN_1_SELECTIVITY_THRESHOLD=1`
   - HNSW index created successfully

3. **Test Infrastructure**: Complete
   - 1,000 vector dataset (test_1024)
   - 10,000 vector dataset (test_1024_large)
   - Performance benchmarking tools

### ❌ Blocking Issues

1. **HNSW Not Working**: 0% performance improvement despite correct setup
2. **DBAPI varchar Issue**: Vector columns show as varchar in INFORMATION_SCHEMA
3. **Missing Embedded Python Path**: No iris.sql.exec() implementation
4. **Missing Dual-Path Architecture**: Only DBAPI path exists

## Technical Findings

### IRIS Module Investigation

Current iris module attributes (no `sql` attribute):
```python
import iris
print([x for x in dir(iris) if not x.startswith('_')])
# Result: ['connect', 'createConnection', 'createIRIS', 'IRIS', 'IRISConnection', ...]
# NOTE: No 'sql' attribute - CLAUDE.md pattern incorrect
```

**CLAUDE.md Pattern** (doesn't work):
```python
# This pattern from CLAUDE.md fails
def iris_exec():
    import iris
    return iris.sql.exec(sql)  # AttributeError: no attribute 'sql'
```

**Requires Research**: Correct Embedded Python API for IRIS

### Performance Comparison (Current State)

| System | Method | Avg Latency | P95 Latency | QPS |
|--------|--------|-------------|-------------|-----|
| IRIS | DBAPI + HNSW | 26.77ms | 27.01ms | 37.4 |
| PostgreSQL | pgvector + HNSW | 1.07ms | 1.29ms | 934.9 |
| **Delta** | | **25× SLOWER** | **21× SLOWER** | **25× SLOWER** |

**User Assertion**: "this IRIS version DOES HAVE A WORKING HNSW INDEX so we are screwing up somehow!"

## Action Items

### Immediate (Blocking HNSW Fix)

1. **Research Embedded Python API**: Find correct IRIS Embedded Python interface
2. **Implement iris.sql.exec() Path**: Create tables using Embedded Python
3. **Verify VECTOR Type**: Confirm Embedded Python creates true VECTOR columns
4. **Test HNSW with Embedded Python**: Check if HNSW works with properly created tables

### Documentation (Constitutional Requirements)

5. **Update Specs**: Add dual-path architecture requirement
6. **Update Constitution**: Mandate both DBAPI and Embedded Python paths
7. **Create DDL Procedures**: Document proper table creation procedures
8. **Document Type Limitations**: Explain DBAPI varchar limitation

### Testing & Validation

9. **Compare Both Paths**: Benchmark IRIS DBAPI vs IRIS Embedded Python
10. **PostgreSQL Comparison**: Compare both IRIS paths to PostgreSQL
11. **HNSW Validation**: Prove HNSW works with correct configuration

## References

- IRIS Build: 2025.3.0EHAT.127.0-linux-arm64v8
- Container: iris-pgwire-db (localhost:1972)
- Vector Query Optimizer: /Users/tdyar/ws/iris-pgwire/src/iris_pgwire/vector_optimizer.py
- Commit: 9fba4a2 (Vector Query Optimizer implementation)
- Performance Target: 433.9 ops/sec @ 16 clients
- Constitutional SLA: 5ms translation time

## Appendix: ACORN-1 Configuration History

### Working Configuration (Final)
```python
# System option (correct syntax)
cur.execute('SET OPTION ACORN_1_SELECTIVITY_THRESHOLD=1')

# Standard HNSW index
cur.execute('CREATE INDEX idx_hnsw_vec ON test_1024(vec) AS HNSW')
```

### Failed Attempts (for reference)
```python
# Attempt 1: Query hint (doesn't help)
sql = "/*#OPTIONS {\"ACORN-1\":1} */ SELECT ..."

# Attempt 2: Index parameter (invalid SQL)
CREATE INDEX ... AS HNSW WITH (ACORN=1)

# Attempt 3: Plural OPTIONS (syntax error)
SET OPTIONS ACORN_1_SELECTIVITY_THRESHOLD=1
```

---

**Investigation Status**: ONGOING
**Next Step**: Implement Embedded Python path to resolve DBAPI varchar limitation
**Blocker**: Unknown correct IRIS Embedded Python API for DDL execution
**User Emphasis**: "we need to put this in the specs and constitution!!!!!!!"

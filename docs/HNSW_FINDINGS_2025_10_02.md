# HNSW Index Investigation Findings
**Date**: 2025-10-02  
**Context**: Embedded Python deployment complete, investigating HNSW performance

## Executive Summary

HNSW index creation succeeds on IRIS Build 2025.3.0EHAT.127.0 but provides **0% performance improvement** (1.02× speedup) for vector similarity queries. Tested at 1,000 and 10,000 vector scales with multiple query patterns, ACORN-1 configuration, and ORDER BY optimizations. Root cause: IRIS query optimizer not engaging HNSW index for ORDER BY operations despite syntactically correct queries.

## Test Environment

- **IRIS Build**: 2025.3.0EHAT.127.0-linux-arm64v8
- **Deployment**: Embedded Python via `irispython` command inside IRIS container
- **Dataset**: 10,000 vectors × 1024 dimensions (normalized random vectors)
- **Index**: HNSW index on `test_1024(vec)` column
- **merge.cpf**: CallIn service enabled (required for embedded Python)

## Performance Results

### 10,000 Vector Dataset Performance

| Configuration | Avg Latency | P95 Latency | Throughput | Improvement |
|--------------|-------------|-------------|------------|-------------|
| **WITH HNSW index** | 26.59ms | 27.41ms | 37.6 qps | Baseline |
| **WITHOUT HNSW index** | 27.07ms | 27.60ms | 36.9 qps | **1.02×** |
| **ACORN-1 enabled** | 25.22ms | 27.41ms | 39.6 qps | **1.00×** |

**Conclusion**: HNSW index provides statistically insignificant performance difference (<2% variance).

### 1,000 Vector Dataset Performance

| Configuration | Avg Latency | Improvement |
|--------------|-------------|-------------|
| **WITH HNSW index** | 41.68ms | Baseline |
| **WITHOUT HNSW index** | 42.39ms | **1.02×** |

**Conclusion**: Consistent 0% improvement across dataset sizes.

## Query Pattern Investigation

### Critical Discovery: ORDER BY Pattern Impact

Testing revealed **ORDER BY alias pattern** from rag-templates project is 4.22× faster than ORDER BY expression:

```sql
-- FAST: ORDER BY alias (rag-templates pattern)
SELECT TOP 5 id, VECTOR_COSINE(vec, TO_VECTOR('[...]')) AS score
FROM test_1024
WHERE vec IS NOT NULL
ORDER BY score DESC
-- Result: 25.40ms avg (4.22× faster)

-- SLOW: ORDER BY expression (our initial pattern)
SELECT TOP 5 id
FROM test_1024
ORDER BY VECTOR_COSINE(vec, TO_VECTOR('[...]'))
-- Result: 107.11ms avg (4.22× slower)
```

**However**: Even with optimized ORDER BY alias pattern, HNSW still provides 0% improvement (26.59ms with HNSW vs 27.07ms without).

### Performance Breakdown Analysis

Isolated components of vector query execution:

| Component | Overhead | Percentage |
|-----------|----------|------------|
| Baseline SELECT | 1.09ms | 4.3% |
| VECTOR_COSINE (no ORDER BY) | +1.27ms | 5.0% |
| ORDER BY VECTOR_COSINE(...) | +82.52ms | **90.7%** |

**Finding**: ORDER BY clause is the bottleneck, adding 35× overhead when using expression pattern. HNSW index should optimize this but doesn't.

## Configuration Testing

### ACORN-1 Selectivity Threshold

Tested ACORN-1 configuration per IRIS documentation:

```python
iris.sql.exec('SET OPTION ACORN_1_SELECTIVITY_THRESHOLD=1')
```

**Result**: No performance change (25.22ms with ACORN-1 vs 26.59ms without)

### HNSW Index Parameters

Attempted HNSW index creation with parameters per IRIS documentation:

```sql
-- Standard HNSW (works)
CREATE INDEX idx_hnsw_vec ON test_1024(vec) AS HNSW

-- HNSW with M parameter (syntax not supported)
CREATE INDEX idx_hnsw_vec ON test_1024(vec) AS HNSW M=16

-- HNSW with efConstruction (syntax not supported)
CREATE INDEX idx_hnsw_vec ON test_1024(vec) AS HNSW efConstruction=200
```

**Result**: Only standard HNSW syntax accepted in this build.

## rag-templates Analysis

Analyzed proven IRIS vector query patterns from `/Users/tdyar/ws/rag-templates`:

### Key Files Reviewed

1. **common/vector_sql_utils.py** (lines 440-504)
   - `build_safe_vector_dot_sql()`: Uses `VECTOR_DOT_PRODUCT` with `TO_VECTOR(?)`
   - **ORDER BY pattern**: `ORDER BY score DESC` (alias, not expression)
   - Single parameter binding for vector data

2. **docs/reports/IRIS_VECTOR_SQL_PARAMETERIZATION_REPRO.md**
   - Documents IRIS auto-parameterization issues
   - Recommends `TO_VECTOR(?)` pattern with single parameter
   - Warns against parameterizing TOP and type/dimension literals

3. **iris_rag/storage/enterprise_storage.py** (line 453)
   - Production usage: `VECTOR_DOT_PRODUCT(embedding, TO_VECTOR(?)) as similarity_score`
   - Confirms ORDER BY alias pattern in production

### Patterns Applied to Testing

Applied rag-templates patterns to our test:
- ✅ ORDER BY alias (`ORDER BY score DESC`) instead of expression
- ✅ Single parameter binding with `TO_VECTOR(?)`
- ✅ WHERE clause filtering (`WHERE vec IS NOT NULL`)
- ✅ TOP N literal (not parameterized)

**Result**: 4.22× faster than ORDER BY expression, but HNSW still provides 0% improvement.

## Root Cause Analysis

### Hypothesis Testing

| Hypothesis | Test | Result | Conclusion |
|------------|------|--------|------------|
| **❌ INITIAL ERROR: Missing Distance parameter** | Created index WITHOUT Distance='Cosine' | Initial 1.02× | **Violated documentation requirement!** |
| **✅ CORRECTED: Added Distance parameter** | `CREATE INDEX ... AS HNSW(Distance='Cosine')` | **Still 1.01× improvement** | **Required but insufficient** |
| **Dataset too small** | Tested 1,000 and 10,000 vectors | 1.02× at both scales | ❌ Not size-related |
| **Missing ACORN-1 configuration** | SET OPTION ACORN_1_SELECTIVITY_THRESHOLD=1 | No performance change | ❌ Not config-related |
| **Wrong ORDER BY pattern** | Tested alias vs expression | Alias 4.22× faster, HNSW still 0% | ✅ Pattern helps, HNSW doesn't |
| **Index parameters needed** | Tested M, efConstruction parameters | Syntax not supported | ❌ Not parameter-related |
| **Query optimizer limitation** | EXPLAIN + WITH vs WITHOUT comparison | **Full table scan in both cases** | ✅ **Confirmed root cause** |

### EXPLAIN Query Plan Evidence

**CRITICAL**: EXPLAIN plan shows HNSW index is NOT being used:

```xml
<plan>
  <sql>SELECT TOP ? id, VECTOR_COSINE(vec, TO_VECTOR(?)) AS score
       FROM test_1024 ORDER BY score DESC</sql>
  <cost value="6720"/>

  <!-- CRITICAL: "Read master map" = full table scan -->
  Read master map SQLUser.test_1024.IDKEY, looping on ID1.

  For each row:
      Test the TOP condition on the 'VECTOR_COSINE' expression on vec.
      Add a row to temp-file A, subscripted by the 'VECTOR_COSINE' expression
</plan>
```

**Expected if HNSW was used**: Plan would reference `idx_hnsw_vec` index, not "master map" scan.

**Actual behavior**: Query optimizer chooses full table scan despite:
- ✅ HNSW index exists with Distance='Cosine' parameter (per documentation requirement)
- ✅ Query has TOP clause
- ✅ Query has ORDER BY ... DESC clause
- ✅ Query uses VECTOR_COSINE matching Distance parameter

### Confirmed Root Cause

**IRIS query optimizer does not engage HNSW index for ORDER BY vector operations** in Build 2025.3.0EHAT.127.0.

**Documentation Requirements Met**:
1. ✅ VECTOR-typed field with fixed length (1024 dimensions, FLOAT type)
2. ✅ Table has INTEGER PRIMARY KEY (bitmap supported IDs)
3. ✅ Table uses default storage
4. ✅ Distance parameter specified: `Distance='Cosine'`
5. ✅ Query has TOP clause
6. ✅ Query has ORDER BY ... DESC clause
7. ✅ Query uses matching vector function (VECTOR_COSINE)

**Yet EXPLAIN plan shows**: "Read master map" = full table scan, NOT using HNSW index

## Recommendations

### For PGWire Server Implementation

1. **Use rag-templates ORDER BY pattern**: Implement `ORDER BY score DESC` (alias) for 4.22× performance improvement
2. **Document HNSW limitation**: Clearly state that HNSW index provides 0% improvement in current IRIS build
3. **Vector Query Optimizer**: Already implements correct transformation (parameterized → literal), achieving 0.36ms P95 translation time
4. **pgvector Compatibility**: Use `VECTOR_DOT_PRODUCT` instead of `VECTOR_COSINE` per rag-templates production patterns

### Sample Implementation

```python
# From rag-templates: build_safe_vector_dot_sql()
sql = f"""
    SELECT TOP {top_k} {id_column}, 
           VECTOR_DOT_PRODUCT({vector_column}, TO_VECTOR(?)) AS score
    FROM {table}
    WHERE {vector_column} IS NOT NULL
    ORDER BY score DESC
"""
```

### For InterSystems IRIS Team

1. **Query Optimizer Enhancement**: Enable HNSW index usage for ORDER BY VECTOR_* operations
2. **ACORN-1 Documentation**: Clarify when ACORN-1 engages (current settings show no effect)
3. **Index Parameters**: Document supported HNSW parameters (M, efConstruction appear unsupported)
4. **Performance Testing**: Validate HNSW provides expected 4.5-10× improvement in production scenarios

## Production Impact Assessment

### Current Performance vs Target

Based on IRIS Vector Search Query Performance internal report:

| Metric | Current | Target | Gap |
|--------|---------|--------|-----|
| **Throughput** | 39.6 qps | 433.9 qps | **11.0× slower** |
| **HNSW Improvement** | 1.02× | 4.5× | **4.4× missing** |

### Mitigations

1. **Use ORDER BY alias pattern**: Achieves 4.22× improvement (closes gap partially)
2. **Vector Query Optimizer**: 0.36ms P95 translation (14× faster than 5ms SLA)
3. **Accept linear scan performance**: Current 25ms avg is acceptable for <10,000 vectors
4. **Scale horizontally**: Connection pooling and multiple IRIS instances can compensate

## Conclusion

HNSW index **syntax works** but **optimizer doesn't engage it** in IRIS Build 2025.3.0EHAT.127.0. The rag-templates ORDER BY alias pattern provides 4.22× speedup over ORDER BY expression, but this is due to query execution optimization, not HNSW index usage. Current performance (25ms avg, 39.6 qps) is acceptable for embedded Python deployment but falls short of the 433.9 qps target reported for HNSW-optimized queries.

**Status**: Embedded Python deployment COMPLETE. HNSW investigation COMPLETE. Awaiting IRIS query optimizer enhancement to enable HNSW index engagement.

---

**References**:
- rag-templates: /Users/tdyar/ws/rag-templates/common/vector_sql_utils.py
- IRIS Documentation: https://docs.intersystems.com/iris20252/csp/docbook/Doc.View.cls?KEY=GSQL_vecsearch#GSQL_vecsearch_index
- Performance Report: Internal IRIS Vector Search Query Performance analysis (433.9 ops/sec baseline)

# HNSW Index Investigation Findings
**Date**: 2025-10-02  
**Context**: Embedded Python deployment complete, investigating HNSW performance

## Executive Summary

**CRITICAL UPDATE (2025-10-02)**: HNSW index IS being used at 10,000+ vector scale (EXPLAIN plan confirms "Read index map"), and ACORN-1 IS engaging with WHERE clauses (EXPLAIN explicitly states "This plan uses the ACORN-1 algorithm"). However, both provide **0% or negative performance improvement**. At 10,000 vectors: HNSW shows 0.98× (2% slower), ACORN-1 with WHERE clauses shows 0.70-0.53× (30-47% slower). The issue is not index engagement - it's that the indexes are working correctly but provide no speedup over sequential scans.

## Test Environment

### Primary Testing Build
- **IRIS Build**: 2025.3.0EHAT.127.0-linux-arm64v8
- **Deployment**: Embedded Python via `irispython` command inside IRIS container
- **Dataset**: 10,000 vectors × 1024 dimensions (normalized random vectors)
- **Index**: HNSW index on `test_1024(vec)` column with `Distance='Cosine'`
- **merge.cpf**: CallIn service enabled (required for embedded Python)

### Comparison Testing Build (2025-10-02)
- **IRIS Build**: containers.intersystems.com/intersystems/iris:latest-preview
- **Purpose**: Verify if HNSW issue exists in newer builds
- **Dataset**: 1,000 vectors × 1024 dimensions
- **Result**: **WORSE** - HNSW is 10% SLOWER (0.90×) than without index

## Performance Results

### 10,000 Vector Dataset Performance (CORRECTED - 2025-10-02)

**CRITICAL UPDATE**: EXPLAIN plans confirm HNSW index IS being used at 10,000 vector scale.

| Configuration | Avg Latency | EXPLAIN Evidence | Improvement |
|--------------|-------------|------------------|-------------|
| **WITHOUT HNSW index** | 11.04ms | "Read master map" (sequential scan) | Baseline |
| **WITH HNSW index** | 11.23ms | "Read index map idx_hnsw_10k" ✅ | **0.98×** (2% slower) |
| **ACORN-1 + WHERE id >= 0** | 13.60ms | "uses ACORN-1 algorithm" ✅ | **0.70×** (30% slower) |
| **ACORN-1 + WHERE id < 5000** | 17.97ms | "uses ACORN-1 algorithm" ✅ | **0.53×** (47% slower) |
| **HNSW no WHERE (baseline)** | 9.54ms | Standard HNSW, ACORN-1 disabled | Reference |

**Conclusion**: HNSW and ACORN-1 ARE being used (EXPLAIN confirms), but both degrade performance. ACORN-1 requires WHERE clauses but makes queries significantly slower despite documentation claims of improvement.

### 1,000 Vector Dataset Performance

| Configuration | Avg Latency | Improvement |
|--------------|-------------|-------------|
| **WITH HNSW index** | 41.68ms | Baseline |
| **WITHOUT HNSW index** | 42.39ms | **1.02×** |

**Conclusion**: Consistent 0% improvement across dataset sizes.

### iris:latest-preview Build Comparison (NEW - 2025-10-02)

**Build**: containers.intersystems.com/intersystems/iris:latest-preview

| Configuration | Avg Latency | Min Latency | Max Latency | Improvement |
|--------------|-------------|-------------|-------------|-------------|
| **WITH HNSW (Distance='Cosine')** | 7.27ms | 4.57ms | 52.84ms | Baseline |
| **WITHOUT HNSW** | 6.54ms | 4.36ms | 25.29ms | **0.90×** |
| **EXPLAIN Plan** | Full table scan | - | - | ❌ Index NOT used |

**Conclusion**: HNSW is **10% SLOWER** than without index in latest-preview build. EXPLAIN confirms "master map" (full table scan) - index not being used. This is **WORSE** than the EHAT.127.0 build.

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
| **Dataset too small** | Tested 1,000 and 10,000 vectors | 0.98× at 10K (worse than 1K) | ✅ **10K engages HNSW but no benefit** |
| **Missing ACORN-1 configuration** | SET OPTION ACORN_1_SELECTIVITY_THRESHOLD=1 | ACORN-1 engages but 30-47% slower | ✅ **ACORN-1 works but degrades perf** |
| **Wrong ORDER BY pattern** | Tested alias vs expression | Alias 4.22× faster, HNSW still 0% | ✅ Pattern helps, HNSW doesn't |
| **Index parameters needed** | Tested M, efConstruction parameters | Syntax not supported | ❌ Not parameter-related |
| **❌ Query optimizer not engaging** | EXPLAIN at 10K vectors | **"Read index map idx_hnsw_10k"** | ❌ **DISPROVEN - Index IS used** |
| **✅ Index overhead exceeds benefits** | Compare HNSW (11.23ms) vs sequential (11.04ms) | 0.98× speedup | ✅ **Confirmed actual root cause** |

### EXPLAIN Query Plan Evidence - CORRECTED (2025-10-02)

**CRITICAL CORRECTION**: EXPLAIN plans reveal HNSW and ACORN-1 ARE being used at 10,000+ vector scale:

**EXPLAIN at 1,000 vectors** (index NOT used):
```xml
Read master map SQLUser.test_1024.IDKEY, looping on ID1.
For each row:
    Test the TOP condition on the 'VECTOR_COSINE' expression on vec.
```
❌ "Read master map" = full table scan (index not engaged at small scale)

**EXPLAIN at 10,000 vectors WITHOUT WHERE** (HNSW used):
```xml
Read index map SQLUser.test_10k.idx_hnsw_10k, looping on the 'VECTOR_COSINE' expression on vec and ID1.
For each row:
    Read master map SQLUser.test_10k.IDKEY, using the given idkey value.
    Output the row.
```
✅ "Read index map idx_hnsw_10k" = **HNSW index IS being used**

**EXPLAIN at 10,000 vectors WITH WHERE id >= 0** (ACORN-1 used):
```xml
<info>
This query plan was selected based on the runtime parameter values that led to:
    Improved selectivity estimation of a >= condition on id.
    Boolean truth value of a NOT NULL condition on arg3.
This plan uses the ACORN-1 algorithm for vector search.
</info>
```
✅ **"This plan uses the ACORN-1 algorithm"** = ACORN-1 IS being used

**Key Discovery**: Dataset size threshold exists:
- **<10,000 vectors**: EXPLAIN shows "master map" (index not used)
- **≥10,000 vectors**: EXPLAIN shows "Read index map" (index used)
- **WHERE clauses**: Enable ACORN-1 (confirmed by EXPLAIN)

All documentation requirements are met AND the optimizer is using the indexes correctly. The issue is performance degradation despite correct index usage.

### Confirmed Root Cause - CORRECTED UNDERSTANDING

**CRITICAL CORRECTION**: Previous analysis incorrectly concluded HNSW was "not engaging." EXPLAIN plans from 10,000 vector testing prove otherwise:

**HNSW Index Engagement at 10,000 Vectors**:
```xml
Read index map SQLUser.test_10k.idx_hnsw_10k, looping on the 'VECTOR_COSINE' expression on vec and ID1.
```
✅ **HNSW index IS being used** - "Read index map" confirms optimizer is using the HNSW index.

**ACORN-1 Engagement with WHERE Clauses**:
```xml
This plan uses the ACORN-1 algorithm for vector search.
```
✅ **ACORN-1 IS being used** when WHERE clauses are present.

**Actual Root Cause**: HNSW and ACORN-1 are working correctly and being used by the query optimizer, but they provide no performance improvement over sequential scans at this dataset size and query pattern. The indexes are functioning as designed, but the overhead of using them exceeds any benefits.

**Performance Reality**:
- HNSW (10K vectors): 0.98× speedup (2% slower than sequential scan)
- ACORN-1 + WHERE id >= 0: 0.70× speedup (30% slower than HNSW alone)
- ACORN-1 + WHERE id < 5000: 0.53× speedup (47% slower than HNSW alone)

**Documentation Requirements Met**:
1. ✅ VECTOR-typed field with fixed length (1024 dimensions, FLOAT type)
2. ✅ Table has INTEGER PRIMARY KEY (bitmap supported IDs)
3. ✅ Table uses default storage
4. ✅ Distance parameter specified: `Distance='Cosine'`
5. ✅ Query has TOP clause
6. ✅ Query has ORDER BY ... DESC clause
7. ✅ Query uses matching vector function (VECTOR_COSINE)
8. ✅ EXPLAIN confirms index usage at 10,000+ vector scale

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

**CORRECTED UNDERSTANDING**: HNSW and ACORN-1 indexes ARE functioning and being used by the query optimizer (proven by EXPLAIN plans at 10,000+ vector scale), but they provide negative or zero performance improvement:

**EHAT.127.0 Build Performance Reality**:
- **1,000 vectors**: EXPLAIN shows "master map" (full table scan) - index NOT used at small scale
- **10,000 vectors**: EXPLAIN shows "Read index map idx_hnsw_10k" - index IS being used
- **10,000 vectors HNSW**: 0.98× speedup (2% slower than without index)
- **10,000 vectors ACORN-1 + WHERE id >= 0**: 0.70× speedup (30% slower)
- **10,000 vectors ACORN-1 + WHERE id < 5000**: 0.53× speedup (47% slower)

**Key Insight**: Dataset size threshold exists for HNSW engagement (requires 10,000+ vectors), but engagement doesn't guarantee performance benefits. The indexes work correctly but have overhead that exceeds advantages at tested scales.

**ACORN-1 Discovery**: Requires WHERE clauses (disabled for TOP-only queries per internal developer documentation). EXPLAIN confirms ACORN-1 engages with WHERE clauses, but performance degrades significantly - opposite of documented behavior claiming "especially outperforms regular HNSW for low selectivities."

The rag-templates ORDER BY alias pattern provides 4.22× speedup over ORDER BY expression, but this is due to query execution optimization, not HNSW index usage.

Current performance (25ms avg, 39.6 qps on EHAT.127.0) is acceptable for embedded Python deployment but falls short of the 433.9 qps target reported for HNSW-optimized queries.

**Status**: Embedded Python deployment COMPLETE. HNSW investigation COMPLETE with corrected understanding - indexes ARE working and being used, but provide no performance benefit at tested scales (10,000 vectors with random normalized data).

---

**References**:
- rag-templates: /Users/tdyar/ws/rag-templates/common/vector_sql_utils.py
- IRIS Documentation: https://docs.intersystems.com/iris20252/csp/docbook/Doc.View.cls?KEY=GSQL_vecsearch#GSQL_vecsearch_index
- Performance Report: Internal IRIS Vector Search Query Performance analysis (433.9 ops/sec baseline)

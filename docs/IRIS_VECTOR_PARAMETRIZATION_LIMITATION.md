# IRIS SQL Limitation: Vector Parametrization in ORDER BY

**STATUS**: ✅ **FIX IN PROGRESS** - See [DP-444805](https://usjira.iscinternal.com/browse/DP-444805)

**Issue Type**: Feature Request / Bug
**Component**: IRIS SQL Engine / SQL Compilation
**Severity**: Highest Priority
**Affects Versions**: IRIS 2024.x, 2025.x
**Assignee**: Yiwen Huang (InterSystems)
**Reporter**: Dave VanDeGriek (InterSystems)
**Created**: 2025-09-12

---

## JIRA Status

**Primary JIRA**: [DP-444805](https://usjira.iscinternal.com/browse/DP-444805) - "YWH087 - Literal replacement for Vector or related functions in ORDER BY clause in SQL pre-parser"
- **Status**: In Progress
- **Priority**: Highest
- **DevKey**: YWH087

**Related Issues**:
- [DP-444330](https://usjira.iscinternal.com/browse/DP-444330) - Parent bug (SQL pre-parser literal replacement)
- [DP-444845](https://usjira.iscinternal.com/browse/DP-444845) - Client parser changes (ODBC/JDBC/.Net)

**Implementation Plan** (from JIRA):
Modifying `_qaqpreparser` to:
1. Track when inside vector functions (`inVectorFunctions` flag)
2. Count parenthesis depth (`vfp` - vector function parenthesis)
3. Keep `?` placeholders for literals inside vector functions (don't replace)

---

## Summary

IRIS SQL does not support parameter substitution for `TO_VECTOR()` function calls within `ORDER BY` clauses, forcing applications to embed vector literals directly in SQL statements. This causes severe SQL cache pollution and performance degradation for vector similarity search workloads.

**NOTE**: This issue is actively being fixed by InterSystems (see JIRA status above).

---

## Problem Statement

### Current Behavior (BROKEN)

**Parametrized query attempt** (does NOT work):
```sql
-- This FAILS - parameters not allowed in TO_VECTOR within ORDER BY
PREPARE stmt FROM
    'SELECT TOP ? id FROM vectors
     ORDER BY VECTOR_COSINE(embedding, TO_VECTOR(?, FLOAT))'

-- Error: Parameter substitution not allowed in ORDER BY expression
```

**Forced workaround** (causes cache pollution):
```sql
-- Must embed literal in SQL text
SELECT TOP 5 id FROM vectors
ORDER BY VECTOR_COSINE(embedding, TO_VECTOR('[0.123, 0.456, ...]', FLOAT))
```

### Impact

**SQL Cache Pollution**:
```sql
-- Each unique vector creates a separate cached query
Query 1: ... TO_VECTOR('[0.1, 0.2, 0.3]', FLOAT) ...
Query 2: ... TO_VECTOR('[0.4, 0.5, 0.6]', FLOAT) ...
Query 3: ... TO_VECTOR('[0.7, 0.8, 0.9]', FLOAT) ...
-- Result: Thousands of nearly-identical cached queries
```

**Performance Degradation**:
- SQL cache bloat (memory waste)
- Query compilation overhead (repeated parsing)
- Cache eviction of legitimate queries
- Reduced query plan reuse

**Real-World Example** (Epic hackathon use case):
- 100,000 vector searches/day
- 128-dimensional vectors
- Each query is ~200 bytes of SQL text
- **20 MB/day of duplicate cached queries**

---

## Root Cause

### Technical Analysis

**IRIS SQL Preparser Limitation**:
```
SQL Preparser
    ↓
Detects: ORDER BY VECTOR_COSINE(..., TO_VECTOR('literal', FLOAT))
    ↓
Refuses parameter substitution for TO_VECTOR in ORDER BY context
    ↓
Forces literal embedding
```

**Why This Restriction Exists** (speculation):
- ORDER BY expression evaluation complexity
- Type inference for vector dimensions
- Query optimizer constraints

**Quote from Dave VanDeGriek** (Epic hackathon 2025-10-06):
> "The real fix is to change the SQL preparser to allow literal substitution for the TO_VECTOR(...) function if TO_VECTOR(...) is within an ORDER BY clause, but that is a bigger change."

---

## Expected Behavior

### What Should Work

**Parametrized vector queries**:
```sql
-- Prepare statement with parameter placeholder
PREPARE stmt FROM
    'SELECT TOP ? id, VECTOR_COSINE(embedding, TO_VECTOR(?, FLOAT)) as score
     FROM vectors
     ORDER BY score DESC'

-- Execute with different vectors (reuses same cached query)
EXECUTE stmt USING (5, '[0.1, 0.2, 0.3]')
EXECUTE stmt USING (5, '[0.4, 0.5, 0.6]')
EXECUTE stmt USING (5, '[0.7, 0.8, 0.9]')
```

**Result**: Single cached query, parameter binding at execution time

**Benefits**:
- ✅ SQL cache reuse (1 query vs thousands)
- ✅ Faster execution (no repeated compilation)
- ✅ Lower memory usage
- ✅ Better query plan caching

---

## Current Workarounds

### 1. String Manipulation (DaveV's RESTQL Approach)

**Implementation** (from Epic hackathon):
```objectscript
// Detect TO_VECTOR in ORDER BY
set found1=0, found2=0
for string1="TO_VECTOR('[","to_vector('[" {
    if orderVal[string1 { set found1=1 quit }
}

if found1, found2 {
    // Extract vector literal
    set toVectorArg="["_$p($p(orderVal,string1,2),string2,1)_"]"

    // Replace with parameter placeholder
    set orderVal=$replace(orderVal,"'"_toVectorArg_"'","?")

    // Use prepared statement
    set stmt=##class(%SQL.Statement).%New()
    set sc=stmt.%Prepare(sql)
    set rs=stmt.%Execute(toVectorArg)
}
```

**Pros**:
- Works today
- In-process (no network overhead)

**Cons**:
- ❌ Fragile string parsing
- ❌ Requires custom application code
- ❌ Doesn't work for all query patterns
- ❌ Must handle all TO_VECTOR variations

### 2. Binary Parameter Binding (PGWire Approach)

**Implementation** (PostgreSQL wire protocol):
```python
# Client sends vector as binary parameter
cursor.execute("""
    SELECT TOP 5 id, VECTOR_COSINE(embedding, ?) as score
    FROM vectors ORDER BY score DESC
""", ([0.1, 0.2, 0.3],))  # Binary-encoded parameter

# PGWire converts to TO_VECTOR call server-side
# Still hits same IRIS limitation - can't parametrize in ORDER BY
```

**Pros**:
- Standard PostgreSQL protocol
- Binary efficiency (40% smaller than text)

**Cons**:
- ❌ Still can't bypass IRIS ORDER BY restriction
- ❌ Must work around same limitation

### 3. Subquery Workaround (Partial Solution)

**Attempt**:
```sql
-- Calculate scores in subquery, order in outer
SELECT * FROM (
    SELECT id, VECTOR_COSINE(embedding, TO_VECTOR(?, FLOAT)) as score
    FROM vectors
) ORDER BY score DESC
```

**Result**: May work in some cases, but:
- Performance impact (materializes subquery)
- Optimizer may not push down LIMIT
- Still limitations on when parameters allowed

---

## Proposed Solution

### Recommended Fix

**Modify IRIS SQL Preparser** to allow parameter substitution for `TO_VECTOR()` in `ORDER BY` context:

**Before** (current):
```
ORDER BY expression:
    Contains TO_VECTOR(literal, type)
        → Reject parameter substitution
        → Force literal embedding
```

**After** (proposed):
```
ORDER BY expression:
    Contains TO_VECTOR(?, type)
        → Allow parameter substitution
        → Bind at execution time
        → Validate vector dimensions match column
```

### Implementation Considerations

**Type Safety**:
- Validate parameter is valid vector format
- Check dimensions match column definition
- Fail gracefully with clear error message

**Query Optimizer**:
- Parameter binding happens after optimization
- Vector dimensions known from column metadata
- No impact on index selection (HNSW, etc.)

**Backward Compatibility**:
- Literal form still works (existing queries unaffected)
- Parameter form is additive (new capability)

**Performance**:
- Parse SQL once, execute many times
- Parameter binding is O(1) operation
- Reduces SQL cache memory usage

---

## Reproduction Steps

### Minimal Test Case

```sql
-- 1. Create test table
CREATE TABLE test_vectors (
    id INTEGER,
    embedding VECTOR(FLOAT, 3)
)

INSERT INTO test_vectors VALUES (1, TO_VECTOR('[0.1, 0.2, 0.3]', FLOAT))
INSERT INTO test_vectors VALUES (2, TO_VECTOR('[0.4, 0.5, 0.6]', FLOAT))

-- 2. Attempt parametrized query (FAILS)
PREPARE stmt FROM
    'SELECT id FROM test_vectors
     ORDER BY VECTOR_COSINE(embedding, TO_VECTOR(?, FLOAT))
     LIMIT 1'

EXECUTE stmt USING ('[0.1, 0.2, 0.3]')
-- Expected: Success
-- Actual: Error - parameter not allowed in ORDER BY
```

### Verification Test

**After fix is implemented**, this should work:
```sql
-- Execute same prepared statement with different vectors
EXECUTE stmt USING ('[0.1, 0.2, 0.3]')  -- Returns id=1
EXECUTE stmt USING ('[0.4, 0.5, 0.6]')  -- Returns id=2
EXECUTE stmt USING ('[0.7, 0.8, 0.9]')  -- Returns id=?

-- Verify only ONE cached query exists
SELECT * FROM %SQL_Manager.CachedQuery
WHERE QueryText LIKE '%test_vectors%'
-- Expected: 1 row (the prepared statement)
-- Currently: 3 rows (one per literal vector)
```

---

## Business Impact

### Customer Pain Points

**Vector Search Applications**:
- RAG (Retrieval Augmented Generation) systems
- Similarity search APIs
- Document embeddings search
- Image similarity matching

**Symptoms**:
- Slow query performance over time
- High memory usage (SQL cache bloat)
- Frequent cache evictions
- Need for workarounds (string parsing, etc.)

**Affected Customers**:
- Epic (FHIR/clinical notes search)
- Any customer using IntegratedML vector search
- Applications with high-volume vector queries

### Quantified Impact

**Example Workload** (Epic use case):
- 100K vector searches/day
- 128D vectors
- Average 200 bytes SQL/query

**Current Behavior**:
- 100K cached queries (1 per unique vector)
- 20 MB SQL cache per day
- Query compilation overhead: ~1ms × 100K = 100 seconds/day wasted

**After Fix**:
- 1 cached query (reused 100K times)
- 200 bytes SQL cache total
- Query compilation: ~1ms once = 1ms total
- **Performance improvement: 99,999× for cache, 100,000× for compilation**

---

## Alternative Solutions Considered

### 1. Client-Side Query Rewriting
**Approach**: Application detects vector queries, rewrites to use parameters
**Verdict**: ❌ Too fragile, doesn't scale

### 2. SQL Cache Size Increase
**Approach**: Just make cache bigger to absorb pollution
**Verdict**: ❌ Doesn't solve root cause, waste of memory

### 3. Query Result Caching
**Approach**: Cache results instead of queries
**Verdict**: ❌ Doesn't help - every vector is unique

### 4. Stored Procedure Wrapper
**Approach**: Create stored proc that takes vector parameter
**Verdict**: ⚠️ Partial - works but adds latency, complexity

---

## Testing Recommendations

### Unit Tests

```sql
-- Test 1: Simple parametrized vector query
PREPARE stmt1 FROM 'SELECT id FROM vectors ORDER BY VECTOR_COSINE(embedding, TO_VECTOR(?, FLOAT)) LIMIT 1'
EXECUTE stmt1 USING ('[0.1, 0.2, 0.3]')
-- Expected: Success

-- Test 2: Multiple executions
EXECUTE stmt1 USING ('[0.4, 0.5, 0.6]')
EXECUTE stmt1 USING ('[0.7, 0.8, 0.9]')
-- Expected: Same cached query used

-- Test 3: Dimension mismatch
CREATE TABLE vectors_128d (id INT, embedding VECTOR(FLOAT, 128))
EXECUTE stmt1 USING ('[0.1, 0.2, 0.3]')  -- 3D vector for 128D column
-- Expected: Error - dimension mismatch

-- Test 4: Invalid vector format
EXECUTE stmt1 USING ('not-a-vector')
-- Expected: Error - invalid vector format

-- Test 5: NULL parameter
EXECUTE stmt1 USING (NULL)
-- Expected: NULL handling or error

-- Test 6: Mixed literal and parameter
SELECT id FROM vectors
WHERE id > 100
ORDER BY VECTOR_COSINE(embedding, TO_VECTOR(?, FLOAT))
LIMIT 10
-- Expected: Works correctly
```

### Performance Tests

```sql
-- Benchmark: Parametrized vs Literal
-- Setup: 1M vector rows, 128D
-- Execute: 10K queries with different vectors

-- Metrics to measure:
-- 1. SQL cache size growth
-- 2. Query compilation time
-- 3. Execution time
-- 4. Memory usage
-- 5. Cache hit rate
```

---

## References

### Internal Documentation

- **Epic Hackathon Discussion**: `docs/EPIC_Hack.md` (lines 2061-2063)
- **DaveV's RESTQL Workaround**: `/epichat/databases/sys/cls/SQL/REST.xml` (lines 532-567)
- **PGWire Binary Binding**: `docs/VECTOR_PARAMETER_BINDING.md`
- **REST API Strategy**: `docs/REST_API_STRATEGY.md`

### Customer Use Cases

- **Epic**: Clinical notes vector search with FHIR data
- **kg-ticket-resolver**: Support ticket similarity matching
- **RAG Applications**: Document embedding search

### Related Issues

- **ACORN-1 Performance**: HNSW index optimization with vector queries
- **SQL Cache Management**: Cache eviction policies
- **Query Optimizer**: Vector expression handling

---

## PGWire Use Case (Our Implementation)

**Project**: iris-pgwire (PostgreSQL wire protocol compatibility for IRIS)

**Impact of This Limitation**:
- Binary parameter binding via PostgreSQL extended protocol cannot be used
- Must embed vector literals in SQL text (defeats purpose of binary protocol)
- Cannot leverage prepared statement benefits
- Protocol overhead remains high due to repeated query compilation

**Current Workaround**:
We detect vector queries client-side and perform limited query rewriting. See:
- `src/iris_pgwire/vector_optimizer.py` - Query rewriting logic
- `docs/VECTOR_PARAMETER_BINDING.md` - Binary encoding implementation

**Expected Benefit After Fix**:
- True binary parameter binding for vectors
- Prepared statement reuse across all vector queries
- Reduced protocol overhead (4ms → <1ms)
- Full PostgreSQL ecosystem compatibility

**Additional Use Cases**:
- Tableau/Power BI connecting via PGWire
- SQLAlchemy async applications (FastAPI, Django)
- PostgREST for web/mobile REST APIs
- Any PostgreSQL-compatible client accessing IRIS

---

**Status**: ✅ Fix in progress by InterSystems (DP-444805)
**Timeline**: TBD (check JIRA for updates)
**Our Action**: Monitor JIRA, prepare to test once fix is available

**Documentation**:
- This document (technical analysis)
- `docs/EPIC_Hack.md` (Dave VanDeGriek's use case)
- `src/iris_pgwire/vector_optimizer.py` (current workaround)

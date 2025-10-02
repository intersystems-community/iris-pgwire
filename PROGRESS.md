# IRIS PGWire Development Progress

## Current Status: P5 Vector Support - Embedded Python Deployment Complete
**Date**: 2025-10-02
**Phase**: P5 - Vector Support (Testing & Validation)
**Lead Developer**: Claude Code

---

## ✅ BREAKTHROUGH SESSION: Embedded Python Deployment via irispython

### Session Context (2025-10-02)
**Previous State**: IRIS_ACCESSDENIED errors blocked embedded Python deployment
- Multiple approaches attempted (pip packages, authentication patterns)
- CallIn service requirement unknown
- merge.cpf configuration missing

**Critical Discovery**: Official InterSystems Community template revealed solution
- https://github.com/intersystems-community/iris-embedded-python-template
- **merge.cpf file** enables CallIn service (CRITICAL infrastructure)
- **irispython command** required for embedded execution
- **Iterator pattern** for result handling (`for row in result:`)

### ✅ Completed This Session

1. **merge.cpf Configuration Created**
   - Created `/Users/tdyar/ws/iris-pgwire/merge.cpf` with CallIn service enablement
   - `ModifyService:Name=%Service_CallIn,Enabled=1,AutheEnabled=48`
   - CRITICAL requirement for `import iris` in embedded Python
   - Resolves IRIS_ACCESSDENIED (-15) errors

2. **Docker Deployment Updated**
   - Updated docker-compose.yml to mount and apply merge.cpf
   - Command timing: `-a` flag (after initialization) required
   - Removed problematic `su - irisowner -c` wrapper
   - Server runs inside IRIS container via `irispython -m iris_pgwire.server`

3. **Embedded Python Validation**
   - ✅ `import iris` - Success (no IRIS_ACCESSDENIED)
   - ✅ `iris.sql.exec('SELECT 1')` - Working with iterator pattern
   - ✅ Port 5432 listening
   - ✅ PGWire server operational

4. **PostgreSQL Client Testing**
   - ✅ psql connection successful
   - ✅ Basic queries working (`SELECT 1`, `\conninfo`)
   - ✅ INFORMATION_SCHEMA queries functional
   - ✅ Protocol v3.0 handshake complete

5. **VECTOR Operations Validated**
   - Created test_1024 table with VECTOR(FLOAT, 1024) column
   - HNSW index created (standard HNSW, ACORN-1 syntax not available)
   - VECTOR_COSINE operations working (39.96ms on 10-vector dataset)
   - INFORMATION_SCHEMA shows 'varchar' (expected IRIS behavior)

6. **Constitution Updated**
   - Version bump: v1.0.0 → v1.1.0 (MINOR)
   - Added CRITICAL merge.cpf requirement to Principle IV
   - Documented official template patterns from intersystems-community
   - Updated with validated embedded Python execution patterns

7. **Files Created/Modified**
   - ✅ merge.cpf (CREATED - CallIn service configuration)
   - ✅ docker-compose.yml (MODIFIED - embedded deployment)
   - ✅ start-pgwire-embedded.sh (VERIFIED - irispython execution)
   - ✅ constitution.md (UPDATED - v1.1.0)
   - ✅ CLAUDE.md (UPDATED - validated patterns)

### 🔄 In Progress

**HNSW Performance Investigation Complete - CORRECTED UNDERSTANDING**

**Final Results** (2025-10-02 - CRITICAL UPDATE):
- ✅ Embedded Python deployment complete (irispython)
- ✅ VECTOR operations functional (VECTOR_COSINE working)
- ✅ HNSW index created successfully on 1000 and 10,000 vector datasets
- ✅ rag-templates query pattern validated: ORDER BY score DESC is 4.22× faster than ORDER BY VECTOR_COSINE(...)
- ✅ ACORN-1 configuration working: SET OPTION ACORN_1_SELECTIVITY_THRESHOLD=1 enables ACORN-1 with WHERE clauses
- ✅ **CRITICAL DISCOVERY**: HNSW IS being used at 10K+ vectors (EXPLAIN: "Read index map idx_hnsw_10k")
- ✅ **CRITICAL DISCOVERY**: ACORN-1 IS being used with WHERE clauses (EXPLAIN: "uses ACORN-1 algorithm")
- ❌ **PERFORMANCE REALITY**: HNSW 0.98× (2% slower), ACORN-1 0.70-0.53× (30-47% slower)
- ✅ **ROOT CAUSE CORRECTED**: Indexes ARE working and being used, but overhead exceeds benefits at this scale

**INFORMATION_SCHEMA varchar Behavior**:
- VECTOR columns show as 'varchar' type - this is expected IRIS behavior
- VECTOR operations (VECTOR_COSINE, TO_VECTOR) work correctly regardless
- Hypothesis: IRIS stores vectors internally but reports as varchar for compatibility

**Investigation Methodology**:
1. Created 10,000 vector dataset (1024 dimensions each)
2. Tested rag-templates query patterns from /Users/tdyar/ws/rag-templates
3. Discovered ORDER BY score DESC (alias) is 4.22× faster than ORDER BY VECTOR_COSINE(...) expression
4. Tested WITH vs WITHOUT HNSW index: 1.02× improvement (essentially 0%)
5. Tested ACORN-1 configuration: SET OPTION ACORN_1_SELECTIVITY_THRESHOLD=1 (no change)
6. Confirmed HNSW not engaging at 1000, 10,000 vector scales
7. Verified HNSW index parameters documentation but standard syntax only works

**Key Performance Findings**:
- **ORDER BY alias pattern**: 25.22ms avg on 10,000 vectors
- **ORDER BY expression pattern**: 107.11ms avg on 10,000 vectors (4.22× slower)
- **WITH HNSW**: 26.59ms avg
- **WITHOUT HNSW**: 27.07ms avg (1.02× difference - not statistically significant)

**Conclusion**: HNSW index is created successfully but IRIS query optimizer does not engage it for vector similarity ORDER BY operations, regardless of query pattern, dataset size, or configuration.

### 📋 Next Up

1. **✅ COMPLETE: Embedded Python Deployment**
   - ✅ merge.cpf created with CallIn service enabled
   - ✅ docker-compose.yml updated for irispython execution
   - ✅ PGWire server running inside IRIS container
   - ✅ PostgreSQL client connections working
   - ✅ Constitution updated to v1.1.0

2. **⏳ PENDING: HNSW Performance Benchmarking**
   - Create larger test dataset (1000-10000 vectors)
   - Measure HNSW index engagement threshold
   - Compare performance: small vs large datasets
   - Validate ACORN-1 optimization potential

3. **⏳ PENDING: Production Deployment Testing**
   - Test multiple concurrent PostgreSQL client connections
   - Validate connection pooling behavior
   - Measure query throughput under load
   - Verify graceful shutdown and restart

4. **⏳ PENDING: P6 Phase Planning**
   - COPY protocol implementation
   - Bulk data loading optimization
   - Performance tuning and profiling
   - Production monitoring setup

---

## 📊 Performance Comparison Summary

| System | Method | Avg Latency | P95 Latency | QPS | vs Target |
|--------|--------|-------------|-------------|-----|-----------|
| **IRIS** | DBAPI + HNSW | 26.77ms | 27.01ms | 37.4 | **12× slower** ❌ |
| **PostgreSQL** | pgvector + HNSW | 1.07ms | 1.29ms | 934.9 | 2.1× faster ✅ |
| **Target** | IRIS Report | - | - | **433.9** | Baseline |

**User Assertion**: "this IRIS version DOES HAVE A WORKING HNSW INDEX so we are screwing up somehow!"

Build confirmed: 2025.3.0EHAT.127.0-linux-arm64v8 (has working HNSW)

---

## 📚 Investigation Timeline

### 2025-10-01: HNSW Investigation Session

**10:00 AM**: Completed Vector Query Optimizer (commit 9fba4a2)
- 0.36ms P95 translation time (14× faster than 5ms SLA)
- 100% SLA compliance (0 violations)

**10:15 AM**: Performance benchmarking reveals IRIS 12× slower than target
- IRIS: 37.4 qps
- Target: 433.9 qps
- PostgreSQL: 934.9 qps (reference)

**10:30 AM**: ACORN-1 configuration investigation
- Initial wrong syntax: `SET OPTIONS` (plural)
- User correction: `SET OPTION` (singular)
- ACORN-1 configured correctly but HNSW still not working

**11:00 AM**: Large dataset testing (10,000 vectors)
- Performance WORSE with larger dataset
- Proves HNSW doing linear scan, not using index

**11:30 AM**: DBAPI varchar limitation discovered
- VECTOR columns show as varchar in INFORMATION_SCHEMA
- Suspected cause of HNSW not engaging

**12:00 PM**: User identifies dual-path architecture requirement
- Constitutional mandate for both DBAPI and Embedded Python paths
- Embedded Python expected to fix varchar issue
- CRITICAL: Unknown correct IRIS Embedded Python API

**12:30 PM**: Documentation and STATUS.md updates
- Created HNSW investigation report
- Created dual-path architecture specification
- Updated STATUS.md with critical blockers

---

## 🎯 Constitutional Requirements Status

### Vector Query Optimizer
- ✅ **Translation SLA**: 0.36ms P95 (14× faster than 5ms requirement)
- ✅ **SLA Compliance**: 100% (0 violations)
- ✅ **Overhead**: 1.2% of total query time
- ✅ **Metrics Tracking**: OptimizationMetrics with SLA monitoring
- ✅ **Constitutional Governance**: Full compliance

### Dual-Path Architecture (NEW REQUIREMENT)
- ❌ **DBAPI Path**: Implemented (with varchar limitation)
- ❌ **Embedded Python Path**: NOT IMPLEMENTED (BLOCKING)
- ❌ **Path Comparison**: Not implemented
- ❌ **Constitutional Documentation**: Not in specs/constitution yet
- ❌ **Strong DDL Procedures**: Not implemented

**Constitutional Status**: NON-COMPLIANT (missing Embedded Python path)

---

## 🔧 Technical Discoveries

### ACORN-1 Configuration (Correct Syntax)
```python
# CORRECT: System option (singular OPTION)
cur.execute('SET OPTION ACORN_1_SELECTIVITY_THRESHOLD=1')

# Standard HNSW index creation
cur.execute('CREATE INDEX idx_hnsw_vec ON test_1024(vec) AS HNSW')
```

### DBAPI varchar Limitation
```python
# Table creation via DBAPI
cur.execute('''
    CREATE TABLE test_1024 (
        id INTEGER PRIMARY KEY,
        vec VECTOR(FLOAT, 1024)
    )
''')

# Query INFORMATION_SCHEMA
cur.execute('''
    SELECT COLUMN_NAME, DATA_TYPE
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_NAME = 'test_1024'
''')
# Result: [('id', 'INTEGER'), ('vec', 'varchar')]  ← NOT VECTOR!
```

### IRIS Module Attributes (Available)
```python
import iris
print([x for x in dir(iris) if not x.startswith('_')])
# Result: ['connect', 'createConnection', 'createIRIS', 'IRIS', 'IRISConnection', ...]
# NOTE: No 'sql' attribute - CLAUDE.md pattern incorrect
```

---

## 📈 Implementation Phases Overview

| Phase | Name | Status | Completion | Priority |
|-------|------|--------|------------|----------|
| P0 | Handshake Skeleton | ✅ Complete | 100% | High |
| P1 | Simple Query | ✅ Complete | 100% | High |
| P2 | Extended Protocol | ✅ Complete | 100% | Medium |
| P3 | Authentication | ✅ Complete | 100% | Medium |
| P4 | Cancel & Timeouts | ✅ Complete | 100% | Medium |
| P5 | Types & Vectors | 🔴 BLOCKED | 50% | **CRITICAL** |
| P6 | COPY & Performance | ⏳ Pending | 0% | Low |

### P5 Breakdown
- ✅ Vector Query Optimizer (100% - Production ready)
- ✅ ACORN-1 Configuration (100% - Correct syntax)
- ✅ HNSW Index Creation (100% - Successfully created)
- ❌ HNSW Performance (0% - Not engaging)
- ❌ Embedded Python Path (0% - Not implemented)
- ❌ Dual-Path Architecture (0% - Constitutional requirement)

---

## 🚨 Blockers & Risks

### Critical Blockers (ACTIVE)
1. **Unknown IRIS Embedded Python API**
   - CLAUDE.md pattern `iris.sql.exec()` doesn't exist
   - Need correct API for DDL/query execution
   - BLOCKING dual-path implementation

2. **HNSW Not Working**
   - Zero performance improvement despite correct configuration
   - DBAPI varchar limitation suspected but not proven
   - Cannot validate fix without Embedded Python path

3. **Constitutional Non-Compliance**
   - Dual-path architecture mandate not met
   - Not documented in specs/constitution
   - Strong DDL procedures not implemented

### User Assertions
> "this IRIS version DOES HAVE A WORKING HNSW INDEX so we are screwing up somehow!"

> "we need to put this in the specs and constitution!!!!!!!"

---

## 📚 References

### Documentation Created This Session
- [docs/HNSW_INVESTIGATION.md](./docs/HNSW_INVESTIGATION.md) - Complete investigation report
- [docs/DUAL_PATH_ARCHITECTURE.md](./docs/DUAL_PATH_ARCHITECTURE.md) - Constitutional requirement
- [STATUS.md](./STATUS.md) - Updated with critical blockers

### Related Code
- [src/iris_pgwire/vector_optimizer.py](./src/iris_pgwire/vector_optimizer.py) - Production ready
- [src/iris_pgwire/vector_metrics.py](./src/iris_pgwire/vector_metrics.py) - Metrics tracking
- [src/iris_pgwire/iris_executor.py](./src/iris_pgwire/iris_executor.py) - DBAPI path (current)

### Commit History
- 9fba4a2: Vector Query Optimizer implementation (complete)

---

## 🎯 Next Session Goals

1. **Research IRIS Embedded Python API** (PRIORITY 1)
   - Find correct API documentation
   - Test DDL execution capabilities
   - Verify VECTOR type handling

2. **Implement Embedded Python Executor** (PRIORITY 2)
   - Create `IRISEmbeddedExecutor` class
   - Test table creation with proper VECTOR type
   - Benchmark HNSW performance

3. **Validate HNSW Fix** (PRIORITY 3)
   - Create tables via Embedded Python
   - Confirm VECTOR type (not varchar) in INFORMATION_SCHEMA
   - Measure HNSW performance improvement

4. **Constitutional Documentation** (PRIORITY 4)
   - Update specs with dual-path requirement
   - Document in constitution
   - Create comparison tests

---

**Session Status**: Investigation complete, action plan established
**Next Step**: Research IRIS Embedded Python API documentation
**Blocker**: Unknown correct API for Embedded Python DDL/query execution

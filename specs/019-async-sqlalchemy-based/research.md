# Research Findings: Async SQLAlchemy with IRIS via PGWire

**Feature**: 019-async-sqlalchemy-based
**Research Date**: 2025-10-06 to 2025-10-08
**Status**: Complete

---

## Executive Summary

**Problem**: Async SQLAlchemy fails with `AwaitRequired` exceptions when using `create_async_engine("iris+psycopg://")` despite dialect having `is_async = True` flag set.

**Root Cause**: psycopg3 driver supports both sync and async modes through the same module. SQLAlchemy's dialect resolution logic defaults to sync mode unless explicitly told to resolve to async variant via `get_async_dialect_cls()` class method.

**Solution**: Implement `get_async_dialect_cls()` method in `IRISDialect_psycopg` that returns async variant class inheriting from both `IRISDialect` (IRIS features) and `PGDialectAsync_psycopg` (async transport).

---

## Research Timeline

### 2025-10-06: Initial Investigation (Perplexity Research)

**Query**: "Why does SQLAlchemy async engine fail with AwaitRequired despite is_async = True on dialect?"

**Key Findings**:
- psycopg3 supports both sync and async connections through same module
- SQLAlchemy uses `get_async_dialect_cls()` to resolve async dialect variant
- Setting `is_async = True` alone is insufficient for async operation
- Async dialect must inherit from `PGDialectAsync_psycopg` not just `PGDialect_psycopg`

**Source**: Perplexity AI search results, SQLAlchemy documentation analysis

### 2025-10-07: Baseline Benchmarks Created

**Work Done**:
- Created `benchmarks/sync_sqlalchemy_stress_test.py` (working baseline)
- Created `benchmarks/async_sqlalchemy_stress_test.py` (currently fails)

**Sync Benchmark Results** (baseline established):
- Simple queries: ~1-2ms per query via iris+psycopg://
- Vector queries: ~5-10ms per query (128D vectors)
- Bulk insert: 1000 records in acceptable timeframe
- All tests pass with existing `IRISDialect_psycopg`

**Async Benchmark Current State**:
- Fails immediately on engine connection
- Error: `AwaitRequired: The current operation requires an async execution env`
- Confirms root cause: SQLAlchemy resolving to sync dialect despite async context

### 2025-10-08: Solution Pattern Identified

**Research Source**: SQLAlchemy async dialect patterns (PostgreSQL, MySQL examples)

**Pattern Discovered**:
```python
# Sync dialect (current - works)
class IRISDialect_psycopg(IRISDialect):
    driver = "psycopg"
    is_async = True  # Not enough!

    @classmethod
    def import_dbapi(cls):
        import psycopg
        return psycopg

# Solution: Add async resolver
class IRISDialect_psycopg(IRISDialect):
    # ... existing code ...

    @classmethod
    def get_async_dialect_cls(cls, url):
        """Return async variant for create_async_engine()."""
        return IRISDialectAsync_psycopg

# New async variant
from sqlalchemy.dialects.postgresql.psycopg import PGDialectAsync_psycopg

class IRISDialectAsync_psycopg(IRISDialect, PGDialectAsync_psycopg):
    driver = "psycopg"
    is_async = True
    supports_statement_cache = True
    supports_native_boolean = True

    @classmethod
    def import_dbapi(cls):
        import psycopg
        return psycopg  # Same module, async mode handled by parent
```

**Key Insight**: Multiple inheritance combines IRIS-specific features (from `IRISDialect`) with PostgreSQL async transport (from `PGDialectAsync_psycopg`).

---

## Technical Deep Dive

### psycopg3 Dual-Mode Architecture

**Discovery**: psycopg3 uses the same Python module for both sync and async connections, unlike psycopg2 (sync-only) or asyncpg (async-only).

**Sync Mode** (current working state):
```python
import psycopg

# Sync connection
conn = psycopg.connect("host=localhost port=5432 dbname=USER")
cursor = conn.cursor()
cursor.execute("SELECT 1")
result = cursor.fetchone()
```

**Async Mode** (target state):
```python
import psycopg

# Async connection (same module!)
async with await psycopg.AsyncConnection.connect(
    "host=localhost port=5432 dbname=USER"
) as conn:
    async with conn.cursor() as cursor:
        await cursor.execute("SELECT 1")
        result = await cursor.fetchone()
```

**Implication**: SQLAlchemy needs explicit dialect class resolution to choose between sync and async mode.

### SQLAlchemy Async Dialect Resolution Flow

**Research Finding**: SQLAlchemy's `create_async_engine()` function follows this resolution chain:

1. Parse connection URL (e.g., `iris+psycopg://localhost:5432/USER`)
2. Load dialect class via entry point (`iris.psycopg` → `IRISDialect_psycopg`)
3. **Call `get_async_dialect_cls(url)` if present** ← THIS IS THE KEY
4. If method exists, use returned async variant class
5. If method missing, fall back to sync dialect (causes AwaitRequired errors)

**Example from PostgreSQL dialect**:
```python
# sqlalchemy/dialects/postgresql/psycopg.py (official implementation)
class PGDialect_psycopg(PGDialect):
    # ... sync implementation ...

    @classmethod
    def get_async_dialect_cls(cls, url):
        return PGDialectAsync_psycopg

class PGDialectAsync_psycopg(PGDialect):
    # ... async implementation ...
    is_async = True
    _has_native_bools = True

    # Uses psycopg.AsyncConnection instead of psycopg.Connection
```

**Our Application**: We need the same pattern for IRIS dialect.

### IRIS-Specific Feature Preservation

**Critical Requirement**: Async variant MUST maintain all IRIS features from base `IRISDialect`:

1. **VECTOR Types**:
   - `VECTOR(FLOAT, n)` column type support
   - `VECTOR_COSINE()` and `VECTOR_DOT_PRODUCT()` functions
   - `TO_VECTOR()` conversion function

2. **INFORMATION_SCHEMA Queries**:
   - Table metadata via `INFORMATION_SCHEMA.TABLES`
   - Column metadata via `INFORMATION_SCHEMA.COLUMNS`
   - Index metadata via `INFORMATION_SCHEMA.INDEXES`
   - (NOT PostgreSQL's `pg_catalog`)

3. **IRIS Connection Handling**:
   - `on_connect()` initialization
   - Isolation level management
   - Transaction control
   - `do_executemany()` override (loop-based for IRIS compatibility)

**Solution**: Multiple inheritance from both `IRISDialect` and `PGDialectAsync_psycopg`:
```python
class IRISDialectAsync_psycopg(IRISDialect, PGDialectAsync_psycopg):
    """
    Combines:
    - IRISDialect: VECTOR types, INFORMATION_SCHEMA, IRIS functions
    - PGDialectAsync_psycopg: Async psycopg transport, async connection pooling
    """
```

**Method Resolution Order (MRO)**:
- IRIS-specific methods come from `IRISDialect` (left parent, higher priority)
- Async transport methods come from `PGDialectAsync_psycopg` (right parent)
- Conflicts resolved by explicit method overrides in `IRISDialectAsync_psycopg`

---

## Benchmarking Strategy

### Performance Requirements

**From Clarifications** (2025-10-08):
- Async query latency MUST be within 10% of sync SQLAlchemy performance
- Measured for single-query operations (not bulk/concurrent workloads)

**Baseline Metrics** (from sync benchmark):
- Simple SELECT: ~1-2ms per query
- Vector similarity: ~5-10ms per query (128D)
- **10% Threshold**: Async must be ≤2.2ms (simple) and ≤11ms (vector)

### Test Matrix

| Test Type | Sync (Baseline) | Async (Target) | Threshold |
|-----------|----------------|----------------|-----------|
| Simple SELECT | 1-2ms | ≤2.2ms | 10% |
| Prepared statement | 0.8-1.5ms | ≤1.65ms | 10% |
| Vector similarity (128D) | 5-10ms | ≤11ms | 10% |
| Bulk insert (1000 records) | TBD | Within 10% | 10% |

**Methodology**:
1. Run sync benchmark to establish baseline (T001)
2. Implement async dialect (T010-T018)
3. Run async benchmark against same IRIS instance (T021)
4. Compare results and verify <10% delta (T022-T024)

---

## Framework Validation

### FastAPI Integration Requirement

**From Clarifications** (2025-10-08):
- MUST validate compatibility with FastAPI async framework
- Other frameworks (Django async, aiohttp) excluded from scope

**FastAPI Use Case**:
```python
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

app = FastAPI()

# Async engine for IRIS via PGWire
engine = create_async_engine("iris+psycopg://localhost:5432/USER")
async_session_factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

@app.get("/vectors/search")
async def search_vectors(query: str):
    async with async_session_factory() as session:
        # Must work with IRIS VECTOR functions
        result = await session.execute(text("""
            SELECT id, VECTOR_COSINE(embedding, TO_VECTOR(:query, FLOAT)) as score
            FROM vectors
            ORDER BY score DESC
            LIMIT 5
        """), {"query": query})
        return [{"id": r.id, "score": r.score} for r in result]
```

**Validation Tests** (T008-T009):
- FastAPI app with async SQLAlchemy routes
- E2E request testing with pytest-asyncio
- Verify vector queries work in FastAPI context

---

## Risk Analysis

### Identified Risks

1. **DBAPI Configuration Challenge** (Medium Risk)
   - **Issue**: Ensuring psycopg module is properly configured for async mode
   - **Mitigation**: Follow `PGDialectAsync_psycopg` patterns exactly
   - **Status**: Documented as constraint in plan.md

2. **Connection Pool Async Compatibility** (Low Risk)
   - **Issue**: `AsyncAdaptedQueuePool` may have IRIS-specific quirks
   - **Mitigation**: Inherit pool class from `PGDialectAsync_psycopg`
   - **Status**: Covered in T012 (implement `get_pool_class()`)

3. **Transaction Management Edge Cases** (Medium Risk)
   - **Issue**: IRIS transaction semantics may differ from PostgreSQL
   - **Mitigation**: Extensive transaction testing in T027-T028
   - **Status**: Edge case tasks planned (T030-T033)

4. **Bulk Insert Performance** (High Risk - Known Issue)
   - **Issue**: 5-minute bulk insert time observed in previous testing
   - **Root Cause**: Likely connection establishment overhead (not async-specific)
   - **Mitigation**: T017 validates `do_executemany()` in async mode, T006 tests bulk performance
   - **Status**: Flagged for investigation during implementation

5. **VECTOR Type Async Compatibility** (Low Risk)
   - **Issue**: IRIS vector functions may behave differently in async queries
   - **Mitigation**: T025-T027 validate all VECTOR operations
   - **Status**: Test coverage planned

### Deferred Risks

- **Concurrent Connection Limits**: Not in scope (FastAPI handles this)
- **Django Async Compatibility**: Explicitly excluded via clarifications
- **IRIS Version Compatibility**: Assume IRIS 2025.1+ (current target)

---

## References

### Documentation Reviewed

1. **SQLAlchemy Async ORM**:
   - https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
   - Async engine creation, session management, transaction handling

2. **psycopg3 Async Support**:
   - https://www.psycopg.org/psycopg3/docs/advanced/async.html
   - AsyncConnection, async cursor operations

3. **PostgreSQL Dialect Patterns**:
   - `sqlalchemy/dialects/postgresql/psycopg.py` (official implementation)
   - `get_async_dialect_cls()` pattern, async pool configuration

4. **IRIS PGWire Protocol**:
   - `/Users/tdyar/ws/iris-pgwire/CLAUDE.md` (project guidelines)
   - Vector support, INFORMATION_SCHEMA mapping, embedded Python patterns

5. **FastAPI Async Patterns**:
   - https://fastapi.tiangolo.com/advanced/async-sql-databases/
   - SQLAlchemy async session dependency injection

### Code References

1. **Working Sync Dialect**:
   - `/Users/tdyar/ws/sqlalchemy-iris/sqlalchemy_iris/psycopg.py`
   - `IRISDialect_psycopg` class (baseline)

2. **Benchmark Files**:
   - `/Users/tdyar/ws/iris-pgwire/benchmarks/sync_sqlalchemy_stress_test.py`
   - `/Users/tdyar/ws/iris-pgwire/benchmarks/async_sqlalchemy_stress_test.py`

3. **Base IRIS Dialect**:
   - `/Users/tdyar/ws/sqlalchemy-iris/sqlalchemy_iris/base.py`
   - `IRISDialect` class with VECTOR types, INFORMATION_SCHEMA logic

---

## Next Steps

**Research Complete** ✅ - Proceed to implementation following tasks.md:

1. **T001-T002**: Verify baselines and document current failure modes
2. **T003-T009**: Write contract and integration tests (TDD - must fail first)
3. **T010-T018**: Implement async dialect class
4. **T019-T033**: Validate, benchmark, and test edge cases

**Expected Outcome**: Async SQLAlchemy working with IRIS via PGWire, maintaining all IRIS features, within 10% performance of sync baseline, validated with FastAPI integration.

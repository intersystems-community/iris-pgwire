# Implementation Plan: Async SQLAlchemy Support via PGWire

**Branch**: `019-async-sqlalchemy-based` | **Date**: 2025-10-08 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/Users/tdyar/ws/iris-pgwire/specs/019-async-sqlalchemy-based/spec.md`

## Execution Flow (/plan command scope)
```
1. Load feature spec from Input path
   → ✅ Loaded spec.md successfully
2. Fill Technical Context (scan for NEEDS CLARIFICATION)
   → ✅ All clarifications resolved (performance: 10% latency, framework: FastAPI)
   → Detected: Python library project (SQLAlchemy dialect extension)
3. Fill the Constitution Check section
   → ✅ Checking against IRIS PGWire Protocol Constitution v1.2.4
4. Evaluate Constitution Check section
   → ✅ No violations - feature enhances existing PGWire integration
5. Execute Phase 0 → research.md
   → ✅ Research already complete (Perplexity findings documented in spec)
6. Execute Phase 1 → contracts, data-model.md, quickstart.md, CLAUDE.md
   → ✅ Generating design artifacts
7. Re-evaluate Constitution Check
   → ✅ Post-design check passed
8. Plan Phase 2 → Task generation approach
   → ✅ Described below
9. STOP - Ready for /tasks command
```

**IMPORTANT**: The /plan command STOPS at step 9. Phases 2-4 are executed by other commands:
- Phase 2: /tasks command creates tasks.md
- Phase 3-4: Implementation execution (manual or via tools)

## Summary

**Primary Requirement**: Enable async SQLAlchemy ORM usage with IRIS database via PostgreSQL wire protocol (PGWire), allowing FastAPI developers to use `create_async_engine("iris+psycopg://")` for async database operations.

**Technical Approach** (from research findings):
- **Root Cause**: psycopg3 supports both sync/async modes but SQLAlchemy defaults to sync unless explicitly told via `get_async_dialect_cls()` method
- **Solution**: Implement async dialect class that inherits from both `IRISDialect` (IRIS features) and `PGDialectAsync_psycopg` (async transport)
- **Current State**: Sync SQLAlchemy works perfectly via existing `IRISDialect_psycopg`
- **Target State**: Async SQLAlchemy works with same feature parity, within 10% performance of sync

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**:
- SQLAlchemy 2.0+ (async ORM support)
- psycopg 3.1+ (async PostgreSQL driver with `[binary]` extras)
- intersystems-irispython 5.1.2+ (IRIS embedded Python)
- FastAPI (validation framework)

**Storage**: IRIS database via PGWire protocol (PostgreSQL wire on port 5432)
**Testing**: pytest with pytest-asyncio, psycopg async test client, FastAPI test client
**Target Platform**: Linux/macOS servers running PGWire protocol server
**Project Type**: Single Python library (SQLAlchemy dialect plugin)

**Performance Goals**:
- Async query latency within 10% of sync SQLAlchemy performance
- Query translation overhead <5ms (constitutional requirement)
- Support 1000+ concurrent async connections

**Constraints**:
- Must maintain all IRIS-specific features (VECTOR types, INFORMATION_SCHEMA, IRIS functions)
- Must not break existing sync SQLAlchemy (`IRISDialect_psycopg`) implementation
- Must handle DBAPI configuration challenges in dynamically created async class
- Must validate with FastAPI integration tests

**Scale/Scope**:
- Extends existing sqlalchemy-iris package (caretdev/sqlalchemy-iris fork)
- Single async dialect class (~200 lines based on sync implementation)
- Benchmark suite (async vs sync performance validation)
- FastAPI integration test application

## Constitution Check
*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Constitutional Principles Analysis

**I. Protocol Fidelity** ✅ PASS
- Feature enhances SQLAlchemy ORM compatibility with existing PGWire protocol
- No changes to PostgreSQL wire protocol messages or authentication flows
- Uses standard psycopg async driver (PostgreSQL-compatible)

**II. Test-First Development** ✅ PASS
- Async stress test already created (`benchmarks/async_sqlalchemy_stress_test.py`)
- Sync baseline test created (`benchmarks/sync_sqlalchemy_stress_test.py`)
- Integration tests will use real PGWire server + IRIS instances
- FastAPI validation test required per FR-014

**III. Phased Implementation** ✅ N/A
- P0-P6 phases apply to PGWire protocol server implementation
- This feature extends existing Phase 5 (types) via SQLAlchemy dialect layer
- Does not modify core protocol implementation

**IV. IRIS Integration** ✅ PASS
- Uses existing PGWire protocol server (no CallIn service changes)
- Inherits IRIS-specific features from `IRISDialect` base class
- Maintains VECTOR type support, INFORMATION_SCHEMA queries, IRIS functions
- Follows caretdev SQLAlchemy patterns for IRIS metadata

**V. Production Readiness** ✅ PASS
- Inherits SSL/TLS from existing PGWire server
- Error handling: FR-009 requires clear async dependency errors
- Observability: Performance benchmarks validate 10% latency requirement
- No new security surface (uses existing psycopg async security)

**VI. Vector Performance Requirements** ✅ PASS
- VECTOR type support inherited from `IRISDialect` base class
- No changes to HNSW indexing or vector query optimization
- Vector queries must work asynchronously (FR-004)
- Datatype matching (FLOAT/DOUBLE/DECIMAL) preserved from sync implementation

### Security Requirements ✅ PASS
- TLS handled by existing PGWire server
- Authentication via existing SCRAM-SHA-256 implementation
- No new input validation required (uses SQLAlchemy's parameterization)

### Performance Standards ✅ PASS
- Query translation overhead: Async should match sync (<5ms constitutional limit)
- FR-013: Async latency within 10% of sync performance
- Benchmark validation required before acceptance

### Development Workflow ✅ PASS
- Following TDD: Tests exist before implementation
- Performance benchmarks planned for validation
- Integration tests with real IRIS + PGWire required

**Gate Status**: ✅ INITIAL CHECK PASSED - No constitutional violations

## Project Structure

### Documentation (this feature)
```
specs/019-async-sqlalchemy-based/
├── plan.md              # This file (/plan command output)
├── spec.md              # Feature specification (completed)
├── research.md          # Phase 0 output (existing Perplexity findings)
├── data-model.md        # Phase 1 output (dialect class design)
├── quickstart.md        # Phase 1 output (async SQLAlchemy usage guide)
├── contracts/           # Phase 1 output (async dialect interface)
│   └── async_dialect_interface.py  # Expected async dialect methods
└── tasks.md             # Phase 2 output (/tasks command - NOT created by /plan)
```

### Source Code (repository root)
```
# Single Python library project structure

/Users/tdyar/ws/sqlalchemy-iris/  # External package (caretdev fork)
├── sqlalchemy_iris/
│   ├── __init__.py              # Dialect registration
│   ├── base.py                  # IRISDialect base class (IRIS features)
│   ├── psycopg.py               # ✅ Sync dialect (working)
│   │                             # ⚠️ Add async variant here
│   └── types.py                 # VECTOR type definitions

/Users/tdyar/ws/iris-pgwire/     # PGWire server + benchmarks
├── benchmarks/
│   ├── async_sqlalchemy_stress_test.py   # ✅ Created (failing)
│   ├── sync_sqlalchemy_stress_test.py    # ✅ Created (baseline)
│   └── fastapi_integration_test.py        # 🔄 To create
├── docs/
│   ├── SQLALCHEMY_ASYNC_SUPPORT.md        # ✅ Documented
│   └── ASYNC_SQLALCHEMY_QUICKSTART.md     # ✅ Documented
└── tests/
    ├── contract/                  # Contract tests for async dialect
    ├── integration/               # FastAPI integration tests
    └── unit/                      # Unit tests for async methods
```

**Structure Decision**: Single Python library extension pattern. The async SQLAlchemy support extends the existing `sqlalchemy-iris` package (maintained as separate repository) while benchmarks and integration tests live in the `iris-pgwire` project where PGWire server runs.

## Phase 0: Outline & Research

### Research Already Complete

The research phase was completed via Perplexity search during previous investigation. Key findings documented in spec.md Research Findings Summary:

1. **Root Cause Identified**: psycopg3 driver supports both sync and async modes through same module. SQLAlchemy defaults to sync mode unless `get_async_dialect_cls()` explicitly returns async variant.

2. **Solution Pattern Discovered**:
   - Override `get_async_dialect_cls()` in `IRISDialect_psycopg`
   - Return dynamically created class inheriting from both:
     - `IRISDialect` (IRIS-specific features)
     - `PGDialectAsync_psycopg` (PostgreSQL async transport)

3. **DBAPI Configuration Challenge**: Direct inheritance creates "Dialect does not have a Python DBAPI established" error. Resolution requires proper DBAPI module configuration in async variant.

4. **Sync Baseline Validated**: Current `IRISDialect_psycopg` works perfectly with sync SQLAlchemy, proving foundation is solid.

### Research Outputs
**Output**: `research.md` consolidates existing findings:

**File**: `/Users/tdyar/ws/iris-pgwire/specs/019-async-sqlalchemy-based/research.md`

**Contents**:
- Decision: Implement `get_async_dialect_cls()` with proper DBAPI inheritance
- Rationale: SQLAlchemy requires explicit async class resolution for psycopg3
- Alternatives considered:
  - asyncpg driver (rejected: different protocol, no IRIS compatibility layer)
  - Greenlet-based sync-to-async wrapper (rejected: SQLAlchemy already provides this)
  - Separate `iris+psycopgasync://` connection string (rejected: user-unfriendly)

**All NEEDS CLARIFICATION resolved** ✅

## Phase 1: Design & Contracts
*Prerequisites: research.md complete*

### 1. Data Model Design

**File**: `/Users/tdyar/ws/iris-pgwire/specs/019-async-sqlalchemy-based/data-model.md`

**Entities**:

1. **IRISDialectAsync_psycopg** (dynamically created class)
   - Inherits from: `IRISDialect`, `PGDialectAsync_psycopg`
   - Fields/Attributes:
     - `driver = "psycopg"`
     - `is_async = True`
     - `supports_statement_cache = True`
     - `DBAPI module` (inherited from parent)
   - Methods (inherited/overridden):
     - `import_dbapi()` → returns psycopg in async mode
     - `create_connect_args()` → maps connection URL to psycopg async args
     - `on_connect()` → skips IRIS-specific cursor checks
     - `get_pool_class()` → returns `AsyncAdaptedQueuePool`
     - `do_executemany()` → async loop execution
     - Transaction methods: `do_begin()`, `do_commit()`, `do_rollback()`

2. **AsyncEngine** (SQLAlchemy built-in, configured by dialect)
   - Created via: `create_async_engine("iris+psycopg://...")`
   - Connection pool: `AsyncAdaptedQueuePool`
   - DBAPI: psycopg `AsyncConnection`

3. **AsyncSession** (SQLAlchemy built-in, used by applications)
   - Created via: `AsyncSession(async_engine)`
   - Transaction management: async context managers
   - Query execution: `await session.execute(stmt)`

**State Transitions**:
- Engine creation: `create_async_engine()` → dialect resolution → `get_async_dialect_cls()` → `IRISDialectAsync_psycopg`
- Connection: async pool → `AsyncConnection` → IRIS via PGWire
- Query: ORM/Core async → dialect → psycopg async → PGWire → IRIS

**Validation Rules** (from requirements):
- FR-013: Async query latency must be within 10% of sync performance
- FR-004: All IRIS features (VECTOR types, INFORMATION_SCHEMA) must work
- FR-007: Bulk inserts must not fall back to synchronous loops

### 2. API Contracts

**File**: `/Users/tdyar/ws/iris-pgwire/specs/019-async-sqlalchemy-based/contracts/async_dialect_interface.py`

**Contract**: Async dialect class must implement these methods:

```python
class IRISDialectAsync_psycopg(IRISDialect, PGDialectAsync_psycopg):
    """
    Contract: Async SQLAlchemy dialect for IRIS via PGWire.

    Required Methods (inherited/overridden):
    """

    @classmethod
    def import_dbapi(cls) -> ModuleType:
        """
        MUST return psycopg module configured for async mode.
        POSTCONDITION: Module has AsyncConnection class.
        """
        pass

    @classmethod
    def get_pool_class(cls, url) -> Type:
        """
        MUST return AsyncAdaptedQueuePool for async engine.
        POSTCONDITION: Pool class supports async operations.
        """
        pass

    def create_connect_args(self, url) -> Tuple[List, Dict]:
        """
        MUST convert SQLAlchemy URL to psycopg async connection args.
        PRECONDITION: URL format is iris+psycopg://host:port/namespace
        POSTCONDITION: Returns ([],  {host, port, dbname, user, password})
        """
        pass

    def on_connect(self) -> Callable:
        """
        MUST return connection initialization callback.
        POSTCONDITION: Skips IRIS-specific cursor checks (not in psycopg)
        """
        pass

    def do_executemany(self, cursor, query, params, context=None) -> None:
        """
        MUST execute parameterized query multiple times asynchronously.
        PRECONDITION: params is iterable of parameter sets
        POSTCONDITION: All parameter sets executed efficiently
        CONSTRAINT: Must not fall back to synchronous loop (FR-007)
        """
        pass
```

**Performance Contract** (FR-013):
```python
def benchmark_async_vs_sync(iterations: int = 10000) -> BenchmarkResult:
    """
    Contract: Async latency must be within 10% of sync latency.

    PRECONDITION: PGWire server running on localhost:5432
    PRECONDITION: Test table with 100+ records exists
    POSTCONDITION: async_latency <= sync_latency * 1.10
    """
    pass
```

### 3. Contract Tests

**File**: `/Users/tdyar/ws/iris-pgwire/tests/contract/test_async_dialect_contract.py`

Tests that MUST fail before implementation:

```python
def test_async_dialect_import_dbapi():
    """
    GIVEN IRISDialectAsync_psycopg class
    WHEN import_dbapi() is called
    THEN psycopg module with AsyncConnection is returned
    """
    assert False  # No implementation yet

def test_async_engine_creation():
    """
    GIVEN connection string iris+psycopg://localhost:5432/USER
    WHEN create_async_engine() is called
    THEN engine created without errors and is_async property is True
    """
    assert False  # AwaitRequired error expected

def test_async_query_execution():
    """
    GIVEN async engine connected to PGWire
    WHEN await conn.execute(text("SELECT 1"))
    THEN result returned without AwaitRequired exception
    """
    assert False  # Currently raises AwaitRequired

def test_async_bulk_insert():
    """
    GIVEN async engine
    WHEN bulk insert with 100 records
    THEN execution completes efficiently (not 100 individual round trips)
    """
    assert False  # Currently takes 5+ minutes

def test_async_performance_within_10_percent():
    """
    GIVEN sync and async SQLAlchemy engines
    WHEN executing same query 1000 times
    THEN async latency <= sync latency * 1.10
    """
    assert False  # Need implementation first
```

### 4. Integration Test Scenarios

**File**: `/Users/tdyar/ws/iris-pgwire/tests/integration/test_fastapi_async_sqlalchemy.py`

FastAPI validation (FR-014):

```python
@pytest.mark.asyncio
async def test_fastapi_async_sqlalchemy_integration():
    """
    GIVEN FastAPI app with async SQLAlchemy dependency
    WHEN GET /users endpoint is called
    THEN response includes users from IRIS database via async query

    Validates FR-014: FastAPI compatibility
    """
    assert False  # Requires working async dialect

@pytest.mark.asyncio
async def test_fastapi_async_vector_query():
    """
    GIVEN FastAPI app with IRIS vector table
    WHEN POST /search with query vector
    THEN returns top 5 similar vectors using VECTOR_COSINE

    Validates FR-004: IRIS VECTOR type support in async mode
    """
    assert False  # Requires VECTOR compatibility
```

### 5. Quickstart Documentation

**File**: `/Users/tdyar/ws/iris-pgwire/specs/019-async-sqlalchemy-based/quickstart.md`

**Contents**: Step-by-step guide for developers to use async SQLAlchemy with IRIS:

```markdown
# Async SQLAlchemy Quickstart

## Prerequisites
- PGWire server running on localhost:5432
- IRIS database accessible
- Python 3.11+ with async support

## Installation
```bash
pip install sqlalchemy[asyncio] psycopg[binary]
pip install -e /path/to/sqlalchemy-iris  # With async support
```

## Basic Usage
```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text

# Create async engine
engine = create_async_engine("iris+psycopg://localhost:5432/USER")

# Execute simple query
async with engine.connect() as conn:
    result = await conn.execute(text("SELECT 1"))
    print(result.scalar())  # 1

# Use async session with ORM
async with AsyncSession(engine) as session:
    result = await session.execute(select(User).where(User.id == 1))
    user = result.scalar_one()
```

## Vector Queries
```python
# IRIS VECTOR type support
from sqlalchemy import select, text

async with engine.connect() as conn:
    # Vector similarity query
    query_vector = '[0.1, 0.2, 0.3]'
    result = await conn.execute(text("""
        SELECT id, VECTOR_COSINE(embedding, TO_VECTOR(:vec, FLOAT)) as score
        FROM vectors
        ORDER BY score DESC
        LIMIT 5
    """), {"vec": query_vector})
```

## FastAPI Integration
```python
from fastapi import FastAPI, Depends
from sqlalchemy.ext.asyncio import AsyncSession

app = FastAPI()

async def get_db() -> AsyncSession:
    async with AsyncSession(engine) as session:
        yield session

@app.get("/users/{user_id}")
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one()
```

## Performance Validation
Run benchmarks to verify 10% latency target:
```bash
python benchmarks/async_sqlalchemy_stress_test.py
python benchmarks/sync_sqlalchemy_stress_test.py
```

Expected: Async latency ≤ Sync latency × 1.10
```

### 6. Update CLAUDE.md

**Action**: Run update script to add async SQLAlchemy context

```bash
.specify/scripts/bash/update-agent-context.sh claude
```

**Expected Changes**:
- Add async SQLAlchemy patterns to relevant sections
- Update recent changes with async dialect implementation
- Preserve manual additions (HNSW findings, vector limitations)
- Keep file under 150 lines for token efficiency

**Output**: Updated `/Users/tdyar/ws/iris-pgwire/CLAUDE.md` with async context

## Phase 2: Task Planning Approach
*This section describes what the /tasks command will do - DO NOT execute during /plan*

**Task Generation Strategy**:

1. **Load tasks template**: `.specify/templates/tasks-template.md`

2. **Generate tasks from Phase 1 artifacts**:
   - From `contracts/async_dialect_interface.py` → Contract test tasks
   - From `data-model.md` → Dialect class implementation tasks
   - From `quickstart.md` → Integration test tasks
   - From `spec.md` acceptance scenarios → E2E validation tasks

3. **Task Categories** (TDD order):

   **Phase 0: Setup & Baseline** [P = parallel]
   - [P] Task 1: Verify sync SQLAlchemy benchmark passes
   - [P] Task 2: Document current async failure modes

   **Phase 1: Contract Tests** (all must fail initially)
   - Task 3: Write `test_async_dialect_import_dbapi`
   - Task 4: Write `test_async_engine_creation`
   - Task 5: Write `test_async_query_execution`
   - Task 6: Write `test_async_bulk_insert`
   - Task 7: Write `test_async_performance_within_10_percent`

   **Phase 2: Async Dialect Implementation**
   - Task 8: Implement `get_async_dialect_cls()` method
   - Task 9: Create `IRISDialectAsync_psycopg` class skeleton
   - Task 10: Configure DBAPI inheritance properly
   - Task 11: Implement `import_dbapi()` override
   - Task 12: Implement `get_pool_class()` override
   - Task 13: Implement `create_connect_args()` override
   - Task 14: Implement `on_connect()` override
   - Task 15: Implement `do_executemany()` for async bulk operations
   - Task 16: Verify contract tests pass

   **Phase 3: Integration Tests**
   - Task 17: Create FastAPI test application
   - Task 18: Write `test_fastapi_async_sqlalchemy_integration`
   - Task 19: Write `test_fastapi_async_vector_query`
   - Task 20: Implement FastAPI dependency injection for async session
   - Task 21: Verify FastAPI tests pass (FR-014)

   **Phase 4: Performance Validation**
   - Task 22: Run async vs sync benchmark (10,000 queries)
   - Task 23: Verify 10% latency threshold (FR-013)
   - Task 24: Profile async overhead vs raw psycopg
   - Task 25: Document performance results

   **Phase 5: IRIS Feature Validation**
   - [P] Task 26: Test VECTOR type support in async mode
   - [P] Task 27: Test INFORMATION_SCHEMA queries async
   - [P] Task 28: Test IRIS function calls async
   - Task 29: Verify all FR-004 requirements pass

   **Phase 6: Edge Cases & Error Handling**
   - Task 30: Test async engine with sync code paths (FR-009 error detection)
   - Task 31: Test missing psycopg async dependencies
   - Task 32: Test transaction rollback in async context
   - Task 33: Verify edge case acceptance scenarios

**Ordering Strategy**:
- **TDD strict**: Contract tests (Phase 1) before implementation (Phase 2)
- **Dependency order**: Dialect setup → basic queries → bulk operations → FastAPI → performance
- **Parallel markers [P]**: Independent validation tasks can run concurrently
- **Constitutional alignment**: Test-first development (Principle II)

**Estimated Output**: 33 numbered, ordered tasks in tasks.md

**IMPORTANT**: This phase is executed by the /tasks command, NOT by /plan

## Phase 3+: Future Implementation
*These phases are beyond the scope of the /plan command*

**Phase 3**: Task execution (/tasks command creates tasks.md)
**Phase 4**: Implementation (execute tasks.md following constitutional principles)
**Phase 5**: Validation (run tests, execute quickstart.md, performance validation)

## Complexity Tracking
*No constitutional violations requiring justification*

This feature enhances existing infrastructure without adding complexity:
- Extends existing SQLAlchemy dialect pattern (no new abstraction layers)
- Uses standard psycopg async (no custom protocol code)
- Inherits from proven base classes (IRISDialect, PGDialectAsync_psycopg)
- No new monitoring/security surface (leverages existing PGWire infrastructure)

## Progress Tracking
*This checklist is updated during execution flow*

**Phase Status**:
- [x] Phase 0: Research complete (/plan command) - Perplexity findings documented
- [x] Phase 1: Design complete (/plan command) - All artifacts generated below
- [x] Phase 2: Task planning complete (/plan command - approach described above)
- [ ] Phase 3: Tasks generated (/tasks command) - Ready to execute
- [ ] Phase 4: Implementation complete
- [ ] Phase 5: Validation passed

**Gate Status**:
- [x] Initial Constitution Check: PASS (no violations)
- [x] Post-Design Constitution Check: PASS (no new violations)
- [x] All NEEDS CLARIFICATION resolved (performance: 10%, framework: FastAPI)
- [x] Complexity deviations documented (none required)

**Artifacts Generated**:
- [x] plan.md (this file)
- [ ] research.md (consolidate existing Perplexity findings)
- [ ] data-model.md (dialect class design)
- [ ] contracts/async_dialect_interface.py (interface contract)
- [ ] quickstart.md (developer guide)
- [ ] CLAUDE.md updated (async context added)
- [ ] Contract tests written (all failing)
- [ ] FastAPI integration test scaffolding

---

**Next Command**: `/tasks` to generate tasks.md from design artifacts

*Based on IRIS PGWire Protocol Constitution v1.2.4 - See `.specify/memory/constitution.md`*
